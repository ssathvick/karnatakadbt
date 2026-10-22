"""Browser acceptance against the local installation; creates fictional test records.
Install Playwright and its Chromium browser first. Never targets a remote host.
"""
import json,pathlib,uuid,os
from playwright.sync_api import sync_playwright
root=pathlib.Path(__file__).resolve().parents[1];creds=json.loads((root/'.local/credentials.json').read_text());base='https://localhost:8443'
def call(c,path,data=None):
 r=c.request.get(base+path) if data is None else c.request.post(base+path,form=data)
 assert r.status<400,(path,r.status,r.text()[:220]);return r.json()
def login(b,mode,user,password):
 c=b.new_context(ignore_https_errors=True);p=c.new_page();p.goto(base+'/registration/login?mode='+mode);p.locator('#username').fill(user);p.locator('#password').fill(password);p.locator('#kc-login').click();p.wait_for_url(base+'/registration/**');return c,p
with sync_playwright() as p:
 b=p.chromium.launch(headless=True,**({'executable_path':os.environ['KDBT_TEST_BROWSER_PATH']} if os.environ.get('KDBT_TEST_BROWSER_PATH') else {}))
 staff,sp=login(b,'staff','admin',creds['staff']['admin']);citizen,cp=login(b,'beneficiary','citizen',creds['beneficiary']['citizen'])
 sw=call(staff,'/registration/api/next/workflows');cw=call(citizen,'/registration/api/next/households/me');csrf=cw['csrf'];sub=cw['sub']
 print('Staff and beneficiary OIDC browser logins passed')
 if not cw['profile']:
  call(citizen,'/registration/api/next/households/me',{'csrf':csrf,'version':'','state':cw['districts'][0]['id'],'income':'1000','household_name':'Synthetic Local Acceptance Household','community':'TEST','synthetic':'1','given_0':'Synthetic','family_0':'Citizen','birth_0':'1990-01-01','gender_0':'Female'})
  print('Household registration saved')
 profiles=call(staff,'/registration/api/workspace')['profiles'];profile=next(x for x in profiles if x['sub']==sub)
 if profile['status']!='approved':call(staff,'/registration/api/workspace/profile/'+sub+'/approve',{'csrf':sw['csrf'],'version':profile['version'],'checks':'confirmed'})
 profiles=call(staff,'/registration/api/workspace')['profiles'];profile=next(x for x in profiles if x['sub']==sub);assert profile['sync']=='complete',profile
 print('Independent review and native registry projection passed')
 mnemonic='LOCAL_'+uuid.uuid4().hex[:8].upper();call(staff,'/registration/api/next/programmes',{'csrf':sw['csrf'],'mnemonic':mnemonic,'name':'Synthetic Local Acceptance Programme','amount':'500','max_income':'5000','min_members':'1'})
 sw=call(staff,'/registration/api/next/workflows');programme=next(x for x in sw['programmes'] if x['mnemonic'].endswith(mnemonic));pid=programme['id']
 call(citizen,'/registration/api/next/programmes/'+str(pid)+'/apply',{'csrf':csrf})
 sw=call(staff,'/registration/api/next/workflows');a=next(x for x in sw['applications'] if x['program']==pid)
 for action in ['check','enroll']:
  call(staff,'/registration/api/next/applications/'+str(a['id'])+'/'+action,{'csrf':sw['csrf'],'expected_status':a['status']});sw=call(staff,'/registration/api/next/workflows');a=next(x for x in sw['applications'] if x['program']==pid)
 assert a['status']=='enrolled',a;print('Programme creation, application, eligibility and enrolment passed')
 denied=citizen.request.get(base+'/registration/api/v2/events');assert denied.status==403;print('Beneficiary denied privileged audit access')
 sp.goto('https://localhost:8445/console/login');sp.wait_for_timeout(1500);assert sp.locator('body').inner_text().find('Login providers')>=0;print('IAM browser SSO passed')
 for port in [8445,8446,8447,8448,8449,8451]:
  response=staff.request.get('https://localhost:'+str(port)+'/console/session');assert response.status==200,(port,response.status,response.text()[:180]);print('Console session passed:',port)
 b.close()
