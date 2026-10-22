"""Cross-platform local installer/controller. No production credentials required."""
import argparse,base64,csv,getpass,json,os,pathlib,secrets,shutil,ssl,subprocess,sys,time,urllib.request,webbrowser
ROOT=pathlib.Path(__file__).resolve().parent
LOCAL=ROOT/'.local'
def run(args,**kw):return subprocess.run(args,cwd=ROOT,check=True,**kw)
def compose(*args,**kw):return run(['docker','compose','--env-file',str(LOCAL/'compose.env'),*args],**kw)
def prerequisites():
    if not shutil.which('docker'):raise SystemExit('Install Docker Desktop (Windows/macOS) or Docker Engine with the Compose plugin (Linux). See README.md.')
    try:run(['docker','info'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);run(['docker','compose','version'],stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError:raise SystemExit('Start Docker and enable Linux containers, then retry. On Linux, ensure this user can access Docker.')
def private_folder():
    LOCAL.mkdir(mode=0o700,exist_ok=True)
    if os.name=='nt':
        row=next(csv.reader(subprocess.check_output(['whoami','/user','/fo','csv','/nh'],text=True).splitlines()))
        run(['icacls',str(LOCAL),'/inheritance:r','/grant:r','*'+row[1]+':(OI)(CI)F','*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F'],stdout=subprocess.DEVNULL)
    else:LOCAL.chmod(0o700)
def generate():
    private_folder();file=LOCAL/'secrets.json'
    if file.exists():return json.loads(file.read_text())
    types=json.loads((ROOT/'deployment/secret-types.json').read_text())
    values={key:base64.urlsafe_b64encode(secrets.token_bytes(32)).decode() if kind=='base64' else secrets.token_urlsafe(40) for key,kind in types.items()}
    for key in ['postgres_password','redis_password','minio_password','keycloak_admin_password','admin_password','verifier_password','officer_password','beneficiary_password']:values[key]=secrets.token_urlsafe(24)
    values['installation_id']=__import__('uuid').uuid4().hex
    file.write_text(json.dumps(values,indent=2));file.chmod(0o600)
    (LOCAL/'compose.env').write_text('\n'.join(k.upper()+'='+values[k] for k in ['postgres_password','redis_password','minio_password','keycloak_admin_password'])+'\n')
    (LOCAL/'runtime.env').write_text('KDBT_DEPLOYMENT_MODE=local\n')
    credentials={'notice':'Generated for this machine only; do not commit or share this file.','staff':{'admin':values['admin_password'],'verifier':values['verifier_password'],'officer':values['officer_password']},'beneficiary':{'citizen':values['beneficiary_password']},'keycloak':{'local-root':values['keycloak_admin_password']}}
    (LOCAL/'credentials.json').write_text(json.dumps(credentials,indent=2));(LOCAL/'credentials.json').chmod(0o600)
    # Realm imports are generated from public roles/configuration, not exported users.
    from deployment.host_setup import create_realms
    create_realms(ROOT,LOCAL,values)
    return values
def status():compose('ps')
def trust():
    cert=LOCAL/'caddy/pki/authorities/local/root.crt'
    cert.parent.mkdir(parents=True,exist_ok=True)
    compose('cp','app:/runtime/caddy/pki/authorities/local/root.crt',str(cert))
    if not cert.is_file():raise SystemExit('Start the application first; its local CA has not been generated yet.')
    if os.name=='nt':run(['certutil','-user','-addstore','Root',str(cert)])
    elif sys.platform=='darwin':run(['security','add-trusted-cert','-d','-r','trustRoot','-k',str(pathlib.Path.home()/'Library/Keychains/login.keychain-db'),str(cert)])
    else:
        target='/usr/local/share/ca-certificates/karnatakadbt-local.crt'
        run(['sudo','install','-m','644',str(cert),target]);run(['sudo','update-ca-certificates'])
    print('Trusted this installation CA. Some browsers maintain their own trust store; see README.md.')
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['up','down','status','logs','trust','check']);parser.add_argument('--no-browser',action='store_true');a=parser.parse_args()
    prerequisites()
    if a.action=='up':
        generate();compose('up','-d','--build')
        print('Waiting for native services. Initial builds/startup may take several minutes.')
        ready=False
        for _ in range(180):
            result=subprocess.run(['docker','compose','--env-file',str(LOCAL/'compose.env'),'exec','-T','app','python','deployment/healthcheck.py'],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            if result.returncode==0:ready=True;break
            time.sleep(5)
        if not ready:raise SystemExit('Startup did not pass all health checks. Data is retained; run python manage.py logs.')
        cert=LOCAL/'caddy/pki/authorities/local/root.crt';cert.parent.mkdir(parents=True,exist_ok=True)
        compose('cp','app:/runtime/caddy/pki/authorities/local/root.crt',str(cert))
        print('Ready: https://localhost:8443/registration/next/\nCredentials: '+str(LOCAL/'credentials.json')+'\nTrust local HTTPS once: python manage.py trust')
        if not a.no_browser:webbrowser.open('https://localhost:8443/registration/next/')
    elif a.action=='down':compose('down');print('Stopped. Named volumes and .local are retained.')
    elif a.action=='status':status()
    elif a.action=='logs':compose('logs','--tail=150','-f','app')
    elif a.action=='trust':trust()
    elif a.action=='check':compose('exec','-T','app','python','deployment/healthcheck.py')
if __name__=='__main__':main()
