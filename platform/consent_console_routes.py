"""Original consent staff entry URLs mapped to permission-checked native actions."""
from urllib.parse import urlencode
from fastapi.responses import RedirectResponse

def mount_staff_routes(app):
    def target(workspace,operation=None,method='get',**values):
        query={'workspace':workspace,**values}
        if operation:query.update(operation=operation,method=method)
        return RedirectResponse('/console/?'+urlencode(query),status_code=303)
    @app.get('/',include_in_schema=False)
    def root():return target('consent-partners','/consent/v1/partners',load='1')
    @app.get('/partners',include_in_schema=False)
    def partners():return target('consent-partners','/consent/v1/partners',load='1')
    @app.get('/partners/new',include_in_schema=False)
    def create():return target('consent-partners','/consent/v1/partners',method='post')
    @app.get('/partners/{partner_id}',include_in_schema=False)
    def partner(partner_id:str):return target('consent-partners','/consent/v1/partners/{partner_id}',partner_id=partner_id,load='1')
    @app.get('/approvals',include_in_schema=False)
    def approvals():return target('consent-approvals','/consent/v1/awe/tasks',load='1')
    @app.get('/decisions',include_in_schema=False)
    def decisions():return target('consent-decisions','/consent/v1/decisions',load='1')
