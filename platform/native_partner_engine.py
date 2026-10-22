"""Independent partner lifecycle implementation using SQLAlchemy Core.

No legacy framework imports, proxy business calls or background side effects.
The migration-preserved four-table schema supports exact fallback recovery.
Mutations serialize under one PostgreSQL transaction lock and append audit rows
in that transaction. Only caller-authenticated identities may reach this engine.
"""
import hashlib,json,uuid
from datetime import datetime,timezone
from contextlib import contextmanager
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec,ed25519,rsa
from cryptography.x509 import load_pem_x509_certificate
from jwt.algorithms import ECAlgorithm,OKPAlgorithm,RSAAlgorithm
from sqlalchemy import MetaData,Table,select,text

class PartnerError(Exception):
    def __init__(self,code,message,status=400):self.code,self.message,self.status=code,message,status;super().__init__(message)

def utcnow():return datetime.now(timezone.utc).replace(tzinfo=None)
def row_identity():return {'id':str(uuid.uuid4()),'created_at':utcnow(),'updated_at':utcnow()}
def invalid(message):return PartnerError('PM-KEY-400',message)

class PartnerKeys:
    def __init__(self,allowed=('RS256','ES256','EdDSA'),minimum_rsa_bits=2048):self.allowed=set(allowed);self.minimum_rsa_bits=minimum_rsa_bits
    def normalize(self,value):
        pem=value.get('public_key');jwk=value.get('jwk')
        if bool(pem)==bool(jwk):raise invalid("Provide exactly one of 'public_key' or 'jwk'.")
        try:
            if jwk:
                if any(k in jwk for k in ['d','p','q','dp','dq','qi','oth','k']):raise invalid('A private key was supplied. Provide the public key only.')
                parser={'RSA':RSAAlgorithm,'EC':ECAlgorithm,'OKP':OKPAlgorithm}.get(jwk.get('kty'))
                if not parser:raise invalid('Unsupported JWK key type.')
                pub=parser.from_jwk(json.dumps(jwk))
            else:
                if 'PRIVATE KEY' in pem:raise invalid('A private key was supplied. Provide the public key only.')
                pub=load_pem_x509_certificate(pem.encode()).public_key() if 'BEGIN CERTIFICATE' in pem else serialization.load_pem_public_key(pem.encode())
        except PartnerError:raise
        except Exception:raise invalid('Could not parse public key.') from None
        if isinstance(pub,rsa.RSAPublicKey):
            if pub.key_size<self.minimum_rsa_bits:raise invalid('RSA key is below the minimum permitted size.')
            algorithm='RS256'
        elif isinstance(pub,ec.EllipticCurvePublicKey) and pub.curve.name=='secp256r1':algorithm='ES256'
        elif isinstance(pub,ed25519.Ed25519PublicKey):algorithm='EdDSA'
        else:raise invalid('Unsupported public key type or curve.')
        declared=(value.get('algorithm') or algorithm).strip()
        if declared!=algorithm:raise invalid('Declared algorithm does not match the key.')
        if algorithm not in self.allowed:raise invalid('Algorithm is not allowed.')
        fingerprint=hashlib.sha256(pub.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
        date=lambda v:v.isoformat() if isinstance(v,datetime) else v
        return {'kid':(value.get('kid') or '').strip() or 'pm-'+fingerprint[:16],'algorithm':algorithm,'public_key':pub.public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode(),'key_fingerprint':fingerprint,'not_before':date(value.get('not_before')),'not_after':date(value.get('not_after'))}
    def jwks(self,keys):
        result=[]
        for value in keys:
            pub=serialization.load_pem_public_key(value['public_key'].encode())
            parser=RSAAlgorithm if isinstance(pub,rsa.RSAPublicKey) else ECAlgorithm if isinstance(pub,ec.EllipticCurvePublicKey) else OKPAlgorithm
            result.append({**json.loads(parser.to_jwk(pub)),'kid':value['kid'],'alg':value['algorithm'],'use':'sig'})
        return {'keys':result}

class NativePartnerEngine:
    def __init__(self,engine,*,keys=None):
        self.engine=engine;self.keys=keys or PartnerKeys();metadata=MetaData()
        self.tables={name:Table('pm_'+name,metadata,autoload_with=engine,schema='public') for name in ['partners','partner_keys','partner_requests','audit_events']}
    @contextmanager
    def transaction(self):
        with self.engine.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('karnatakadbt-native-partners',0))"))
            yield c
    def one(self,c,kind,**where):
        table=self.tables[kind];query=select(table)
        for field,value in where.items():query=query.where(table.c[field]==value)
        row=c.execute(query).mappings().first();return dict(row) if row else None
    def put(self,c,kind,values):
        table=self.tables[kind];row={**row_identity(),**values};c.execute(table.insert().values(**row));return self.one(c,kind,id=row['id'])
    def update(self,c,kind,identifier,values):
        table=self.tables[kind];c.execute(table.update().where(table.c.id==identifier).values(**values,updated_at=utcnow()));return self.one(c,kind,id=identifier)
    def audit(self,c,action,entity,identifier,partner,actor,request=None,details=None):
        self.put(c,'audit_events',{'action':action,'entity_type':entity,'entity_id':identifier,'partner_id':partner,'request_id':request,'actor_id':actor.get('id'),'actor_name':actor.get('name'),'details':details or {}})
    def partner(self,c,identifier):
        row=self.one(c,'partners',partner_id=identifier)
        if not row:raise PartnerError('PM-PRT-404',f"Partner '{identifier}' not found.",404)
        return row
    def request(self,c,identifier):
        row=self.one(c,'partner_requests',id=identifier)
        if not row:raise PartnerError('PM-REQ-404',f"Request '{identifier}' not found.",404)
        return row
    def list(self,kind,**filters):
        table=self.tables[kind];query=select(table).order_by(table.c.created_at.desc())
        for key,value in filters.items():
            if value:query=query.where(table.c[key]==value)
        with self.engine.connect() as c:return [dict(row) for row in c.execute(query).mappings()]
    def collect_keys(self,data,imported=None):
        inputs=list(data.get('keys') or [])
        if data.get('import_from_jwks_url'):
            if not data.get('jwks_url'):raise invalid('import_from_jwks_url is set but jwks_url is empty.')
            if imported is None:raise PartnerError('PM-JWK-502','JWKS import result is required.')
            inputs.extend({'jwk':value,'kid':value.get('kid')} for value in imported)
        result={}
        for value in inputs:
            key=self.keys.normalize(value);result[key['key_fingerprint']]=key
        return list(result.values())
    def create(self,kind,data,actor,imported=None):
        with self.transaction() as c:
            existing=self.one(c,'partners',partner_id=data['partner_id'])
            if kind=='onboarding' and existing:raise PartnerError('PM-PRT-409',f"Partner '{data['partner_id']}' already exists.")
            if kind=='key_update' and not existing:self.partner(c,data['partner_id'])
            proposed=self.collect_keys(data,imported)
            if not proposed and (kind=='onboarding' or not data.get('revoke_kids')):raise invalid('At least one public key is required to onboard a partner.' if kind=='onboarding' else 'Provide at least one key to add or one kid to revoke.')
            values={'request_type':kind,'partner_id':data['partner_id'],'description':data.get('description'),'jwks_url':data.get('jwks_url'),'proposed_keys':proposed,'revoke_kids':[] if kind=='onboarding' else list(data.get('revoke_kids') or []),'status':'created','submitted_by':actor.get('name')}
            if kind=='onboarding':values.update({key:data.get(key) for key in ['name','org_name']})
            request=self.put(c,'partner_requests',values)
            if kind=='onboarding':
                partner=self.put(c,'partners',{'partner_id':data['partner_id'],'name':data['name'],'org_name':data.get('org_name'),'description':data.get('description'),'jwks_url':data.get('jwks_url'),'status':'created','created_by':actor.get('name')})
                self.audit(c,'partner.created','partner',partner['id'],data['partner_id'],actor,request['id'],{'status':'created'})
                details={'type':'onboarding','keys':len(proposed)}
            else:details={'type':'key_update','keys_proposed':[key['kid'] for key in proposed],'revoke_kids':list(data.get('revoke_kids') or [])}
            self.audit(c,'request.submitted','partner_request',request['id'],data['partner_id'],actor,request['id'],details)
            return request
    def decide(self,identifier,approved,actor,notes=None):
        with self.transaction() as c:
            request=self.request(c,identifier)
            if request['status']!='created':raise PartnerError('PM-REQ-409',f"Request is '{request['status']}', only 'created' requests can be {'approved' if approved else 'rejected'}.")
            partnerid=request['partner_id'];added=[];revoked=[]
            if approved:
                partner=self.partner(c,partnerid)
                if request['request_type']=='onboarding':
                    self.update(c,'partners',partner['id'],{'status':'active','approved_by':actor.get('name')})
                    self.audit(c,'partner.approved','partner',partner['id'],partnerid,actor,identifier,{'from':'created','to':'active'})
                for key in request['proposed_keys'] or []:
                    existing=self.one(c,'partner_keys',partner_id=partnerid,kid=key['kid']);values={**key,'partner_id':partnerid,'status':'active'}
                    for field in ['not_before','not_after']:
                        if isinstance(values.get(field),str):values[field]=datetime.fromisoformat(values[field])
                    self.update(c,'partner_keys',existing['id'],values) if existing else self.put(c,'partner_keys',values)
                    added.append(key['kid']);self.audit(c,'key.added','partner_key',key['kid'],partnerid,actor,identifier,{'kid':key['kid'],'algorithm':key.get('algorithm')})
                for kid in request['revoke_kids'] or []:
                    existing=self.one(c,'partner_keys',partner_id=partnerid,kid=kid)
                    if existing and existing['status']!='revoked':
                        self.update(c,'partner_keys',existing['id'],{'status':'revoked'});revoked.append(kid)
                        self.audit(c,'key.revoked','partner_key',kid,partnerid,actor,identifier,{'kid':kid})
            result=self.update(c,'partner_requests',identifier,{'status':'approved' if approved else 'rejected','reviewed_by':actor.get('name'),'review_notes':notes})
            self.audit(c,'request.approved' if approved else 'request.rejected','partner_request',identifier,partnerid,actor,identifier,{'kids_added':added,'kids_revoked':revoked} if approved else {'type':request['request_type'],'notes':notes})
            return result
    def set_status(self,identifier,active,actor):
        with self.transaction() as c:
            partner=self.partner(c,identifier);status='active' if active else 'disabled';values={'status':status}
            if active:values['approved_by']=actor.get('name')
            result=self.update(c,'partners',partner['id'],values)
            self.audit(c,'partner.enabled' if active else 'partner.disabled','partner',partner['id'],identifier,actor,details={'from':partner['status'],'to':status});return result
    def servable_keys(self,identifier):
        with self.engine.connect() as c:
            partner=self.one(c,'partners',partner_id=identifier)
            if not partner or partner['status']!='active':return []
            table=self.tables['partner_keys'];rows=c.execute(select(table).where(table.c.partner_id==identifier,table.c.status=='active')).mappings().all()
        now=datetime.now(timezone.utc);result=[]
        for row in rows:
            date=lambda value:value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value
            if row['not_before'] and date(row['not_before'])>now:continue
            if row['not_after'] and date(row['not_after'])<now:continue
            result.append({key:row[key] for key in ['partner_id','kid','algorithm','public_key','not_before','not_after']})
        return result
