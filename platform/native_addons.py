import json
from pathlib import Path
from flask import g,request
def install(r):
 r.BASE_DIR=Path('/app/platform')
 r.CATALOGUE=json.loads((r.BASE_DIR/'karnataka-geography.json').read_text())
 r.DISTRICTS={d['id']:d for d in r.CATALOGUE['districts']}
 r.ROLEMAP={'officer':['iqs-registration-officer'],'verifier':['iqs-verification-officer'],'supervisor':['iqs-programme-supervisor'],'citizen':[]}
 @r.app.before_request
 def assigned_role():
  if hasattr(g,'user') and g.user:
   roles=g.user.get('roles',[])
   g.session['role']='supervisor' if 'iqs-programme-supervisor' in roles else 'verifier' if 'iqs-verification-officer' in roles else 'officer' if 'iqs-registration-officer' in roles else 'citizen'
 @r.app.get('/native/health')
 def native_health():return {'project':'KarnatakaDBT','mode':'independent-native-backend','synthetic':True,'districts':31}
