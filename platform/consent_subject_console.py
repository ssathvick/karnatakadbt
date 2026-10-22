"""Own consent review and withdrawal screens, isolated from staff cookies."""
from pathlib import Path
from urllib.parse import urlsplit
from fastapi.responses import FileResponse,JSONResponse

def mount_subject_console(app,config):
    issuer=urlsplit(config['issuer']);redirect=urlsplit(config['redirect_uri'])
    if issuer.scheme!='https' or issuer.netloc!='localhost:8444' or issuer.path!='/realms/staff' or redirect.scheme!='https' or redirect.netloc!='localhost:8449' or redirect.path!='/subject/' or not config['client_id']:raise ValueError('Explicit consent browser identity trust required')
    folder=Path(__file__).with_name('consent-subject-console')
    def protected(response):
        response.headers['cache-control']='no-store';response.headers['x-content-type-options']='nosniff';response.headers['referrer-policy']='no-referrer';response.headers['content-security-policy']="default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self' "+issuer.scheme+'://'+issuer.netloc+"; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        return response
    @app.get('/subject/config.json',include_in_schema=False)
    def settings():return protected(JSONResponse({k:config[k] for k in ['issuer','client_id','redirect_uri']}))
    @app.get('/subject/subject.js',include_in_schema=False)
    def script():return protected(FileResponse(folder/'subject.js',media_type='text/javascript'))
    @app.get('/subject/subject.css',include_in_schema=False)
    def style():return protected(FileResponse(folder/'subject.css',media_type='text/css'))
    def screen():return protected(FileResponse(folder/'index.html',media_type='text/html'))
    app.add_api_route('/subject/',screen,methods=['GET'],include_in_schema=False)
    app.add_api_route('/my/consents',screen,methods=['GET'],include_in_schema=False)
    @app.get('/consent/{request_id}',include_in_schema=False)
    def review(request_id:str):return screen()
