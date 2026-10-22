"""Native public, subject and origination HTTP APIs.

Partner routes require deployment transport isolation, matching the original
service contract. Subject and origination routes require verified bearer tokens;
browser session cookies cannot substitute for subject authentication.
"""
import json
from datetime import datetime
import jwt
from fastapi import FastAPI, Request, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from native_consent_policy import ConsentPolicyError, now
from native_consent_verification import SubjectId


class RequestCreate(BaseModel):
    subject_id: SubjectId
    partner_id: str
    purpose: dict
    requested_scopes: list[str] = Field(min_length=1)
    validity: dict[str, datetime] | None = None


class Authenticate(BaseModel):
    id_token: str = Field(min_length=1, max_length=131072)


class Approve(BaseModel):
    granted_scopes: list[str] = Field(min_length=1)


class Revoke(BaseModel):
    reason: str | None = None
    originated_by: str = 'controller'


class NativeConsentBearer:
    def __init__(self, *, issuer, audience, key_lookup, default_subject_type, algorithms=('RS256',)):
        if not issuer or not audience or not default_subject_type or not callable(key_lookup):
            raise ValueError('Explicit identity trust and subject type required')
        if not algorithms or not set(algorithms).issubset({'RS256', 'ES256', 'EdDSA'}):
            raise ValueError('Asymmetric identity algorithms required')
        self.issuer,self.audience,self.keys,self.subject_type,self.algorithms=issuer,audience,key_lookup,default_subject_type,algorithms

    def __call__(self, request):
        header=request.headers.get('authorization','')
        if not header.startswith('Bearer '):
            raise ConsentPolicyError(401,'Missing bearer token')
        try:
            token=header[7:];protected=jwt.get_unverified_header(token)
            if protected.get('crit') or protected.get('alg') not in self.algorithms:
                raise ValueError()
            key=self.keys(protected.get('kid'))
            if key is None:
                raise ValueError()
            claims=jwt.decode(token,key,algorithms=self.algorithms,issuer=self.issuer,audience=self.audience,
                              options={'require':['iss','aud','sub','exp','iat']})
            if not isinstance(claims['sub'],str) or not claims['sub']:
                raise ValueError()
            return {'subject_id_type':claims.get('subject_id_type') or self.subject_type,
                    'subject_id_value':claims.get('subject_id_value') or claims['sub']}
        except (jwt.PyJWTError,ValueError,TypeError,KeyError):
            raise ConsentPolicyError(401,'Invalid or expired bearer token') from None


def create_native_consent_public_api(store, verifier, receipts, *, authenticate):
    app=FastAPI(title='KarnatakaDBT native consent lifecycle and verification')
    @app.middleware('http')
    async def private_responses(request, call_next):
        response=await call_next(request)
        response.headers['cache-control']='no-store';response.headers['x-content-type-options']='nosniff'
        return response
    @app.exception_handler(ConsentPolicyError)
    async def rejected(request,error):return JSONResponse({'error':error.message},status_code=error.status)
    @app.exception_handler(SQLAlchemyError)
    async def unavailable(request,error):return JSONResponse({'error':'Consent persistence unavailable'},status_code=503)
    def found(value):
        if value is None:raise ConsentPolicyError(404,'not_found')
        return value
    def artefact(value):
        value=found(value)
        fields=['id','subject_id_type','subject_id_value','partner_id','purpose','effective_data_scopes','status','source','valid_from','valid_until','created_at','revoked_at']
        return {**{field:value.get(field) for field in fields},'consent_id':value['id']}
    def request_view(value):
        value=found(value)
        return {field:value.get(field) for field in ['id','subject_id_type','subject_id_value','partner_id','purpose','requested_scopes','status','valid_from','valid_until','created_at']}
    @app.get('/.well-known/jwks.json')
    def jwks():return receipts.jwks()
    @app.post('/consent/v1/validate')
    async def validate(request:Request):
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>256*1024:return dict(decision='deny',reason_code='malformed_object',evaluated_at=now())
        try:payload=json.loads(body)
        except (ValueError,UnicodeDecodeError):payload={}
        return verifier.validate(payload)
    @app.get('/consent/v1/consents/{consent_id}/status')
    def status(consent_id:str):return found(store.status(consent_id))
    @app.get('/consent/v1/receipts/{receipt_id}')
    def receipt(receipt_id:str):return found(store.receipt(receipt_id))['document']
    @app.post('/consent/v1/consent-requests',status_code=201)
    def create_request(request:Request,data:RequestCreate):
        authenticate(request);return request_view(store.create_request(data.model_dump()))
    @app.get('/consent/v1/consent-requests/{request_id}')
    def get_request(request:Request,request_id:str):
        authenticate(request);return request_view(store.request(request_id))
    @app.post('/consent/v1/consent-requests/{request_id}/authenticate')
    def authenticate_subject(request:Request,request_id:str,data:Authenticate):
        authenticate(request);context=store.authenticate(request_id,data.id_token)
        return dict(request_id=request_id,auth_context_id=context['id'],token_validated=context['token_validated'],auth_method=context['auth_method'])
    @app.post('/consent/v1/consent-requests/{request_id}/approve',status_code=201)
    def approve(request:Request,request_id:str,data:Approve):
        authenticate(request);return artefact(store.approve(request_id,data.granted_scopes))
    @app.post('/consent/v1/consent-requests/{request_id}/deny')
    def deny(request:Request,request_id:str,data:Revoke=Revoke()):
        authenticate(request);return request_view(store.deny(request_id))
    def revoked(value):
        value=found(value)
        return dict(consent_id=value['id'],status=value['status'],revoked_at=value['revoked_at'])
    @app.post('/consent/v1/consents/{consent_id}/revoke')
    def revoke(request:Request,consent_id:str,data:Revoke=Revoke()):
        authenticate(request)
        if data.originated_by not in {'subject','controller','partner'}:raise ConsentPolicyError(422,'Invalid revocation origin')
        return revoked(store.revoke(consent_id,originated_by=data.originated_by,reason=data.reason))
    @app.get('/consent/v1/my/consents')
    def my_consents(request:Request,status:str|None=None,page:int=Query(1,ge=1),size:int=Query(20,ge=1,le=100)):
        result=store.subject_consents(authenticate(request),status=status,page=page,size=size)
        result['items']=[artefact(row) for row in result['items']];return result
    @app.get('/consent/v1/my/consents/{consent_id}')
    def my_consent(request:Request,consent_id:str):return artefact(store.subject_artefact(consent_id,authenticate(request)))
    @app.get('/consent/v1/my/receipts/{receipt_id}')
    def my_receipt(request:Request,receipt_id:str):return found(store.receipt(receipt_id,subject=authenticate(request)))['document']
    @app.post('/consent/v1/my/consents/{consent_id}/revoke')
    def my_revoke(request:Request,consent_id:str,data:Revoke=Revoke()):
        return revoked(store.revoke(consent_id,subject=authenticate(request),originated_by='subject',reason=data.reason))
    app.state.native_public_consent_operations=14
    app.state.production_routes_switched=False
    return app
