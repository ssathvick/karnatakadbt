"""Hold registry ownership throughout each state-changing HTTP request."""
from fastapi.responses import JSONResponse
from registry_worker_admission import RegistryWorkerAdmission


def install_registry_http_ownership(app,engine,*,business_paths,safe_reads,health_paths):
    admission=RegistryWorkerAdmission(engine,'registry')
    @app.middleware('http')
    async def owned_writer(request,call_next):
        if request.url.path not in business_paths or request.url.path in health_paths or request.url.path in safe_reads and request.method in {'GET','HEAD','POST'}:
            return await call_next(request)
        # The coordinator cannot revoke ownership midway through a request:
        # this shared row lock spans SQL, document and external API effects.
        with admission.acquire() as accepted:
            if not accepted:
                return JSONResponse({'error':'Native registry writer ownership is not admitted'},status_code=503,headers={'cache-control':'no-store','retry-after':'5'})
            return await call_next(request)
    return admission
