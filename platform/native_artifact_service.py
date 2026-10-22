"""Read-only native artifact delivery. Retained third-party files keep provenance."""
import json,os
from pathlib import Path
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse,Response
from starlette.routing import Mount,Route
from starlette.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
def build(root,manifest):
 root=Path(root).resolve();types={row['path']:row['content_type'] for row in manifest}
 class Artifacts(StaticFiles):
  async def get_response(self,path,scope):
   if scope['method'] not in {'GET','HEAD'}:return Response(status_code=405,headers={'allow':'GET, HEAD'})
   relative=Path(path)
   if relative.is_absolute() or '..' in relative.parts:raise HTTPException(404)
   candidate=(root/relative).resolve()
   if not candidate.is_relative_to(root):raise HTTPException(404)
   if candidate.is_dir() and not any((candidate/n).is_file() for n in ['index.html','index.htm']):raise HTTPException(403)
   if candidate.is_dir() and not (candidate/'index.html').is_file() and (candidate/'index.htm').is_file():path=str(relative/'index.htm')
   response=await super().get_response(path,scope)
   key=str(relative/'index.html') if candidate.is_dir() else str(relative)
   if key in types and response.status_code not in {304,416}:response.headers['content-type']=types[key]
   response.headers['X-KarnatakaDBT-Artifact-Backend']='native'
   response.headers['X-Content-Type-Options']='nosniff'
   return response
 async def health(request):return JSONResponse({'ready':True,'read_only':True,'artifact_files':len(manifest),'mosip_service_runtime_dependency':False,'third_party_artifacts_retained':True})
 return Starlette(routes=[Route('/_kdbt/health',health),Mount('/',app=Artifacts(directory=str(root),html=True,follow_symlink=False))])
if os.environ.get('KDBT_ARTIFACT_SETTINGS'):
 settings=json.loads(Path(os.environ['KDBT_ARTIFACT_SETTINGS']).read_text());app=build(settings['root'],json.loads(Path(settings['manifest']).read_text()))
