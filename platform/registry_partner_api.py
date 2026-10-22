"""Native partner admission and consent-protected DCI searches.

Partner requests never borrow a console identity. Registered public keys verify
the exact raw payload, and every DCI item needs a current native consent permit.
"""
import base64,datetime,json,uuid,logging
from pathlib import Path
import httpx,jwt,orjson
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from jwt import PyJWS
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from jsonpath_ng import parse
from sqlalchemy import select,func
from registry_contract_models import ContractModels
from registry_configuration_store import catalog
from registry_ingestion_config_store import patterns
from registry_record_store import records
from registry_message_template_store import templates
from registry_document_store import documents
from registry_metadata_api import RegistryPrincipal,RegistryAuthError,response
from registry_metadata_store import RegistryError
from registry_data_policy import RecordPolicyCompiler
from registry_outgoing_workers import render_outgoing
from registry_worker_transaction import bound_store
from native_partner_signatures import NativePartnerVerificationKeys

INGEST='/partner/ingest_data';SEARCH='/dci/registry/sync/search';PATHS=frozenset({INGEST,SEARCH})
ALGORITHMS=('RS256','ES256','EdDSA')
def reference(sender):
    if not isinstance(sender,str) or not sender.strip() or len(sender)>512:raise RegistryAuthError(401,'Registered partner signature required')
    value=sender.strip().replace('-','_').upper()
    return value if value.startswith('PARTNER_') else 'PARTNER_'+value
def canonical(payload):
    return payload if isinstance(payload,bytes) else payload.encode() if isinstance(payload,str) else orjson.dumps(payload,option=orjson.OPT_SORT_KEYS)
class RegistryPartnerSignatures:
    def __init__(self,lookup):self.lookup=lookup
    def verify(self,signature,payload,sender):
        try:
            if not isinstance(signature,str) or len(signature)>65536:return False
            protected,embedded,signed=signature.split('.');header=jwt.get_unverified_header(signature);alg=header.get('alg');kid=header.get('kid')
            if alg not in ALGORITHMS or header.get('crit') or header.get('b64') is False or kid is not None and (not isinstance(kid,str) or len(kid)>512):return False
            encoded=base64.urlsafe_b64encode(canonical(payload)).rstrip(b'=').decode()
            if embedded and embedded!=encoded:return False
            complete=protected+'.'+encoded+'.'+signed
        except (ValueError,TypeError,KeyError):return False
        for entry in self.lookup(reference(sender),kid):
            if kid and entry.get('kid') and kid!=entry['kid'] or entry.get('algorithm') and entry['algorithm']!=alg:continue
            try:
                pem=entry['public_key'].encode();key=x509.load_pem_x509_certificate(pem).public_key() if b'BEGIN CERTIFICATE' in pem else serialization.load_pem_public_key(pem)
                PyJWS().decode(complete,key,algorithms=[alg]);return True
            except Exception:continue
        return False

class RegistryDciSearch:
    def __init__(self,store,allowed_fields):self.store=store;self.allowed=set(allowed_fields)
    def conditions(self,criteria,columns):
        query=criteria['query']['value'];kind=criteria['query_type'];compiler=RecordPolicyCompiler(records,columns)
        if kind=='idtype-value':
            if not isinstance(query.get('id_type'),str) or not query['id_type'].strip():raise ValueError('id_type required')
            search=query.get('id_value')
        elif kind=='expression':
            expression=(query.get('expression') or {}).get('query')
            if not isinstance(expression,dict) or not expression or len(expression)>32:raise ValueError('Nonempty bounded expression required')
            if list(expression)==['search_text'] and isinstance(expression['search_text'],dict) and list(expression['search_text'])==['$eq']:search=expression['search_text']['$eq']
            else:
                result=[]
                for field,operators in expression.items():
                    if field not in self.allowed or field not in columns:raise ValueError('Expression field not allowed')
                    column,typ=compiler.column(field)
                    if not isinstance(operators,dict):operators={'$eq':operators}
                    if not operators or len(operators)>12:raise ValueError('Expression operators required')
                    for op,value in operators.items():
                        if typ=='date':
                            def date(v):return datetime.datetime.fromisoformat(v.replace('Z','+00:00')).date() if isinstance(v,str) else v
                            value=[date(v) for v in value] if isinstance(value,list) else date(value)
                        if op in {'$in','$nin'}:
                            if not isinstance(value,list) or len(value)>1000:raise ValueError('Bounded list required')
                            condition=column.in_(value) if op=='$in' else ~column.in_(value)
                        elif op in {'$eq','$ne','$neq','$gt','$gte','$lt','$lte'}:condition={'$eq':column.__eq__,'$ne':column.__ne__,'$neq':column.__ne__,'$gt':column.__gt__,'$gte':column.__ge__,'$lt':column.__lt__,'$lte':column.__le__}[op](value)
                        elif op in {'$contains','$startsWith','$endsWith'}:condition=column.ilike(('%' if op!='$startsWith' else '')+str(value)+('%' if op!='$endsWith' else ''))
                        else:raise ValueError('Unsupported expression operator')
                        result.append(condition)
                return result,False
        else:raise ValueError('Unsupported query_type')
        if not isinstance(search,str) or not search.strip():raise ValueError('Nonempty search text required')
        return [records.c.data['search_text'].astext.ilike('%'+search.strip()+'%')],True
    def search(self,item,scopes):
        criteria=item['search_criteria'];pagination=criteria.get('pagination') or {};page=pagination.get('page_number',1);size=pagination.get('page_size',10)
        if type(page) is not int or type(size) is not int or page<1 or not 1<=size<=1000:raise ValueError('Invalid bounded pagination')
        with self.store.engine.connect() as c:
            definitions=[d for d in self.store.definitions(c) if d['register_mnemonic']==criteria['reg_type']]
            if len(definitions)!=1:raise ValueError('Register unavailable')
            definition=definitions[0];profile=self.store.record_interface(definition)
            if not profile or not profile.get('current'):raise ValueError('Register implementation unavailable')
            columns=profile['current']['columns'];conditions,deep=self.conditions(criteria,columns);conditions+=[records.c.kind=='current',records.c.register_id==definition['register_id']]
            total=c.execute(select(func.count()).select_from(records).where(*conditions)).scalar_one()
            models=[v for v in self.store.model_rows(c) if v['data_model_mnemonic']=='DCI']
            if len(models)!=1:raise ValueError('DCI data model unavailable')
            matches=[v for v in self.store.template_rows(c,'outgoing') if v['register_id']==definition['register_id'] and v['data_model_id']==models[0]['data_model_id']]
            if len(matches)!=1:raise ValueError('Outgoing DCI template unavailable')
            document=self.store.validate_template_document(c,matches[0]['template_document_id']);template=self.store.storage.get_bytes(document['document_store_id'],document['bucket']).decode()
            query=select(records.c.source_json,records.c.data).where(*conditions);sort=(criteria.get('sort') or [None])[0]
            if sort and sort['attribute_name'] in columns:
                column,_=RecordPolicyCompiler(records,columns).column(sort['attribute_name']);query=query.order_by(column.desc() if sort['sort_order']=='desc' else column.asc())
            elif deep:query=query.order_by(records.c.data['last_approved_at'].astext.desc())
            values=[]
            for raw,projected in c.execute(query.offset((page-1)*size).limit(size)):
                value=self.store.record_value(raw,columns)
                # Deep search exposes the hierarchy expected by outgoing DCI templates.
                if deep:value=self.store.approval_outgoing_hierarchy(c,definition,projected['internal_record_id'])
                rendered=render_outgoing(template,value)
                if not isinstance(rendered,dict):raise ValueError('DCI template must produce an object')
                values.append({key:value for key,value in rendered.items() if key in scopes})
        return {'reference_id':item['reference_id'],'timestamp':datetime.datetime.now().isoformat(),'status':'succ','data':{'reg_type':criteria['reg_type'],'reg_record_type':criteria['reg_record_type'],'reg_records':values},'pagination':{'page_number':page,'page_size':size,'total_count':total},'locale':'en'}

def install_partner_api(app,store,audit,settings,*,verifier=None,consent=None,signer=None):
    contract=json.loads(Path(__file__).with_name('registry_partner_contract.json').read_text());models=ContractModels(contract)
    verifier=verifier or RegistryPartnerSignatures(NativePartnerVerificationKeys(settings['partner_key_origin'],soft_ttl=0,hard_ttl=0,negative_ttl=0))
    search=RegistryDciSearch(store,settings['expression_allowed_fields'])
    def validate_consent(token,sender):
        if not isinstance(token,str) or not token:return {'decision':'deny'}
        result=httpx.post(settings['consent_origin']+'/consent/v1/validate',json={'consent_jws':token,'partner_id':sender},trust_env=False,timeout=10);result.raise_for_status();return result.json()
    consent=consent or validate_consent
    def sign(payload):
        cfg=json.loads(Path(settings['signing_settings_path']).read_text());key=serialization.load_pem_private_key(Path(cfg['key_path']).read_bytes(),password=None)
        full=PyJWS().encode(canonical(payload),key,algorithm=cfg['algorithm'],headers={'kid':cfg['kid']});a,_,b=full.split('.');return a+'..'+b
    signer=signer or sign
    def dci(body):
        req=models.model('DciSearchRequestEnvelope').model_validate(body).model_dump(mode='json');header=req['header'];message=req['message'];items=[];code=None;error=None
        try:
            if header.get('is_msg_encrypted'):raise ValueError('Encrypted request unsupported')
            if not verifier.verify(body['signature'],{'header':body['header'],'message':body['message']},header['sender_id']):raise RegistryAuthError(401,'Partner signature rejected')
            store.partner_client.require_active(header['sender_id']);seen=set();permits=[]
            for item in message['search_request']:
                if item['reference_id'] in seen:raise ValueError('Duplicate reference_id')
                seen.add(item['reference_id']);authorize=item['search_criteria'].get('authorize') or {};decision=consent(authorize.get('consent_jws'),header['sender_id']);scopes=decision.get('effective_data_scopes')
                if decision.get('decision')!='permit' or not isinstance(scopes,list) or any(not isinstance(s,str) for s in scopes):raise RegistryAuthError(403,'Consent denied')
                permits.append((item,set(scopes)))
            items=[search.search(item,scopes) for item,scopes in permits]
        except RegistryAuthError:code='REQ-VAL-001';error='REQUEST_VALIDATION_ERROR'
        except RegistryError as e:code=e.code;error=e.message
        except ValueError:code='rjct.search_criteria.invalid';error='Search criteria invalid'
        except Exception:code='SYS-ERR-001';error='UNEXPECTED_ERROR'
        response_header={'version':'1.0.0','message_id':header['message_id'],'message_ts':header['message_ts'],'action':'search','sender_id':header['receiver_id'],'receiver_id':header['sender_id'],'sender_uri':header.get('sender_uri'),'status':'rjct' if code else 'succ','status_reason_code':code,'status_reason_message':error,'total_count':len(message['search_request']),'completed_count':0 if code else len(items),'is_msg_encrypted':False,'meta':{'signature_validation':'enabled','consent_enforcement':'enabled'}}
        payload={'header':response_header,'message':{'transaction_id':message['transaction_id'],'correlation_id':uuid.uuid4().hex,'search_response':[] if code else items}}
        # A signer failure never returns an unsigned success or any records.
        result=models.model('DciSearchResponseEnvelope').model_validate({'signature':'',**payload}).model_dump(mode='json')
        result['signature']=signer({'header':result['header'],'message':result['message']})
        return result
    def ingest(body,headers,query):
        envelope={'body':body,'headers':headers}
        def extract(path):
            matches=parse(path).find(envelope);return matches[0].value if matches else None
        with store.engine.begin() as c:
            mnemonic=query.get('data_model');mnemonic=mnemonic.upper() if mnemonic else None
            for model in ([] if mnemonic else store.model_rows(c)):
                import re
                path,regex=model['pattern_for_data_model'].split('=>',1);value=extract(path);mnemonic=value if value is not None and re.fullmatch(regex,str(value)) else None
            models_found=[m for m in store.model_rows(c) if m['data_model_mnemonic']==mnemonic]
            if len(models_found)!=1:raise RegistryError('SYS-ERR-001','DATA_MODEL_NOT_FOUND')
            model=models_found[0];keys=list(c.execute(select(patterns.c.data).where(patterns.c.kind=='key',patterns.c.data['data_model_id'].as_string()==model['data_model_id'])).scalars())
            if len(keys)!=1:raise ValueError('Ingestion key mapping unavailable')
            key=keys[0];sender=extract(key['key_path_for_sender']);signature=extract(key['key_path_for_signature']);payload=extract(key['key_path_for_signature_payload'])
            if payload is None or not verifier.verify(signature,payload,sender):raise RegistryAuthError(401,'Partner signature rejected')
            store.partner_client.require_active(sender)
            document=store.validate_template_document(c,model['response_template_document_id']) if model.get('response_template_document_id') else None
            template=store.storage.get_bytes(document['document_store_id'],document['bucket']).decode() if document else None
            result=bound_store(store,c).admit_ingest(body,headers,query,RegistryPrincipal('partner:'+reference(sender),frozenset()))
            value=response('',result)
            # Rendering is inside the same transaction as queue admission.
            return render_outgoing(template,value) if template else value
    async def handle(request,action):
        raw=bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw)>2*1024*1024:return JSONResponse({'error':'Request too large'},status_code=413)
        try:body=json.loads(raw)
        except (ValueError,UnicodeError):return JSONResponse({'error':'Malformed JSON'},status_code=400)
        try:event=await run_in_threadpool(audit.begin,request.url.path,request.method)
        except Exception:return JSONResponse({'error':'Audit admission unavailable'},status_code=503)
        status=200;failed=False
        try:
            args=(body,) if action==dci else (body,dict(request.headers),dict(request.query_params))
            value=await run_in_threadpool(action,*args);failed=value.get('header',{}).get('status')=='rjct'
        except RegistryAuthError as e:status=e.status;value=response('',code='HTTP-'+str(status),message=e.message);failed=True
        except Exception:status=503;value={'error':'Partner request unavailable'};failed=True
        try:await run_in_threadpool(audit.finish,event,None,status,failed)
        except Exception:logging.getLogger(__name__).error('Partner HTTP audit completion pending for event %s',event)
        return JSONResponse(value,status_code=status,headers={'cache-control':'no-store','X-KarnatakaDBT-Registry-Partner':'native'})
    async def dci_endpoint(request:Request,data):return await handle(request,dci)
    dci_endpoint.__annotations__['data']=models.model('DciSearchRequestEnvelope')
    app.add_api_route(SEARCH,dci_endpoint,methods=['POST'],response_model=models.model('DciSearchResponseEnvelope'))
    @app.post(INGEST)
    async def ingest_endpoint(request:Request):return await handle(request,ingest)
