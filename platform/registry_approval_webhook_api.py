"""Explicit HMAC POST route, separate from all console-authenticated routes."""
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from registry_approval_webhook import WEBHOOK_PATH
from registry_metadata_api import RegistryAuthError
from registry_metadata_store import RegistryError
from pydantic import BaseModel

class AweWebhookDecisionResponse(BaseModel):
    event_id:str
    applied:bool
    message:str='ok'

def install_approval_webhook(app,store,audit):
    @app.post(WEBHOOK_PATH,response_model=AweWebhookDecisionResponse)
    async def decision_webhook(request:Request):
        try:key=await run_in_threadpool(audit.begin,WEBHOOK_PATH,'POST')
        except Exception:return JSONResponse({'detail':'audit unavailable'},status_code=503)
        status=200;value=None
        try:
            body=bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body)>1048576:raise RegistryAuthError(413,'Webhook body is too large')
            value=await run_in_threadpool(store.handle_approval_webhook,bytes(body),request.headers.get('X-Approval-Signature'),request.headers.get('X-Approval-Timestamp'),request.headers.get('X-Approval-Event-Id'))
        except RegistryAuthError as error:status=error.status;value={'detail':error.message}
        except RegistryError:status=422;value={'detail':'webhook processing failed'}
        except ValidationError:status=422;value={'detail':'invalid webhook event'}
        except Exception:status=500;value={'detail':'internal error'}
        try:await run_in_threadpool(audit.finish,key,None,status,status>=400)
        except Exception:pass
        return JSONResponse(value,status_code=status,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
