"""Serve the accepted native Approval frontend; business APIs retain JWT checks."""
import re
from pathlib import Path
from fastapi import FastAPI,HTTPException
from fastapi.responses import FileResponse
app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
folder=Path(__file__).with_name('approval-console')
assets={'index.html','console.js','console.css','console-config.json','approval-contract.json'}
@app.middleware('http')
async def security(request,call_next):
 response=await call_next(request)
 response.headers.update({'X-KarnatakaDBT-Native-Profile':'approval','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'same-origin','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self' https://localhost:8444; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self' https://localhost:8444"})
 return response
@app.get('/health')
def health():return {'ready':all((folder/n).is_file() for n in assets),'native_approval_console':True}
@app.get('/{path:path}')
def frontend(path:str):
 name=path if path in assets else 'index.html' if re.fullmatch(r'(?:policies(?:/.*)?|requests(?:/.*)?|audit|delegations|deliveries|tasks|directory)?',path) else None
 if name is None:raise HTTPException(404)
 return FileResponse(folder/name)
