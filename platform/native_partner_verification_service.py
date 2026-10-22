"""Registered-key verification compatible with retained consumers' wire protocol.

No certificate supplied by a caller is trusted. Keys come only from the native
approved partner directory, with no stale-key or legacy-verifier fallback.
"""
import base64,datetime,json,os
from pathlib import Path
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from native_partner_signatures import NativePartnerSignatures,NativePartnerVerificationKeys,PartnerKeyUnavailable

def build(settings):
    applications=settings['allowed_application_ids']
    if not applications or any(not isinstance(v,str) or not v for v in applications):raise ValueError('Explicit signature application scope required')
    keys=NativePartnerVerificationKeys(settings['partner_key_origin'],soft_ttl=0,hard_ttl=0,negative_ttl=0)
    verifier=NativePartnerSignatures(keys,algorithms=('RS256','RS384','RS512','PS256','PS384','PS512','ES256','ES384','ES512','EdDSA'))
    app=FastAPI(title='KarnatakaDBT registered partner signature verification')
    metrics={'requests':0,'verified':0,'last_result':None,'last_application_id':None}
    @app.get('/health')
    def health():return {'ready':True,'native_registered_keys_only':True,'legacy_crypto_http_dependency':False,**metrics}
    @app.post('/v1/keymanager/jwtVerify')
    async def verify(request:Request):
        body=bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body)>256*1024:return JSONResponse({'error':'Verification request too large'},status_code=413)
        valid=False;metrics['requests']+=1;metrics['last_result']='malformed-request'
        try:
            envelope=json.loads(body);value=envelope['request'];signature=value['jwtSignatureData'];actual=value['actualData']
            if not isinstance(signature,str) or len(signature)>65536 or not isinstance(actual,str) or len(actual)>131072:raise ValueError()
            parts=signature.split('.')
            metrics['last_application_id']=value.get('applicationId') if value.get('applicationId') in applications else 'unrecognised'
            if len(parts)!=3 or parts[1]!=actual:metrics['last_result']='detached-payload-mismatch';raise ValueError()
            if value['applicationId'] not in applications:metrics['last_result']='application-scope';raise ValueError()
            if value.get('certificateData'):metrics['last_result']='caller-certificate';raise ValueError()
            payload=json.loads(base64.urlsafe_b64decode(actual+'='*(-len(actual)%4)))
            if not isinstance(payload,dict) or value['referenceId']!=verifier.partner_reference(payload):metrics['last_result']='partner-reference-scope';raise ValueError()
            valid=await run_in_threadpool(verifier.verify,signature,payload)
            metrics['last_result']='verified' if valid else 'signature-invalid';metrics['verified']+=int(valid)
        except PartnerKeyUnavailable:return JSONResponse({'error':'Approved partner key directory unavailable'},status_code=503)
        except (ValueError,TypeError,KeyError,UnicodeError):pass
        return JSONResponse({'response':{'signatureValid':bool(valid)},'errors':[],'responsetime':datetime.datetime.now(datetime.timezone.utc).isoformat()},headers={'cache-control':'no-store','X-KarnatakaDBT-Partner-Verification':'native'})
    return app

if os.environ.get('KDBT_PARTNER_VERIFICATION_SETTINGS'):app=build(json.loads(Path(os.environ['KDBT_PARTNER_VERIFICATION_SETTINGS']).read_text()))
