"""First-party UI localization. No external translation or beneficiary data access."""
import json
from pathlib import Path
from flask import request
LANGUAGES={'en':'English','kn':'ಕನ್ನಡ'}
CATALOGUE=json.loads((Path(__file__).parent/'locales/kn.json').read_text(encoding='utf-8'))
def language():
 value=request.args.get('lang') or request.cookies.get('KDBT-Language','en')
 return value if value in LANGUAGES else 'en'
def tr(value):return CATALOGUE.get(str(value),value) if language()=='kn' else value
def install(r):
 if r.app.extensions.get('kdbt_localization'):return
 r.app.extensions['kdbt_localization']=True
 @r.app.context_processor
 def context():return {'ui_language':language(),'tr':tr,'ui_languages':LANGUAGES}
 @r.app.after_request
 def response_locale(response):
  response.headers.add('Vary','Cookie')
  if 'lang' in request.args and request.args['lang'] in LANGUAGES and '/api/' not in request.path:
   domain='localhost:8443' if request.host.split(':')[0].endswith('localhost:8443') else None
   response.set_cookie('KDBT-Language',request.args['lang'],max_age=31536000,secure=True,samesite='Lax',domain=domain)
  if response.mimetype=='text/html':response.headers['Content-Language']=language()
  return response
