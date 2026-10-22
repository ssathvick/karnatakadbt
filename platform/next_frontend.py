"""Serve the exported Next.js UI alongside the existing authenticated APIs."""
from pathlib import Path
from flask import Blueprint, abort, g, redirect, send_from_directory, request

# Entry pages move to the React workspace; detail pages and all POST/API routes
# remain owned by their existing authenticated handlers.
WORKSPACE_ENTRIES={
    '/':'Overview','/registration':'Overview','/registration/':'Overview',
    '/registration/workspace':'Overview','/registration/staff':'Households',
    '/registration/profile':'Registration',
}

def install(r):
    bp=Blueprint('next_frontend',__name__)
    root=Path(__file__).resolve().parent/'next-ui'/'out'

    @r.app.before_request
    def workspace_entry():
        section=WORKSPACE_ENTRIES.get(request.path)
        if section and request.method in ('GET','HEAD'):
            return redirect(r.PREFIX+'/next/#'+section,code=302)

    @bp.get(r.PREFIX+'/api/next/session')
    def session():
        if not g.user:return {'authenticated':False}
        return {'authenticated':True,'name':g.user.get('name','Signed-in user'),'csrf':g.session['csrf']}

    @bp.get(r.PREFIX+'/next')
    def canonical():
        return redirect(r.PREFIX+'/next/',code=308)

    @bp.get(r.PREFIX+'/next/',defaults={'name':''})
    @bp.get(r.PREFIX+'/next/<path:name>')
    def frontend(name):
        candidate=(root/name).resolve()
        if not candidate.is_relative_to(root.resolve()):abort(404)
        if candidate.is_dir():candidate=candidate/'index.html'
        if not candidate.is_file():abort(404)
        response=send_from_directory(root,candidate.relative_to(root.resolve()).as_posix())
        # No personalized data is embedded in the exported HTML. API responses
        # remain session protected and retain the backend's no-store policy.
        response.headers['X-Content-Type-Options']='nosniff'
        return response

    r.app.register_blueprint(bp)
    import next_workflows
    next_workflows.install(r)
