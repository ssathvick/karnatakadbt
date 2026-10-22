"""Restartable local process assembly; named volumes retain all application state."""
import json,os,pathlib,signal,subprocess,sys,time
ROOT=pathlib.Path('/runtime');ROOT.mkdir(parents=True,exist_ok=True)
os.umask(0o077)
import shutil
if not (ROOT/'secrets.json').exists():
    shutil.copyfile('/host-input/secrets.json',ROOT/'secrets.json');(ROOT/'secrets.json').chmod(0o600)
elif json.loads((ROOT/'secrets.json').read_text())['installation_id']!=json.loads(pathlib.Path('/host-input/secrets.json').read_text())['installation_id']:
    raise ValueError('Runtime volume and host configuration belong to different installations')
from gateway import generate
generate(ROOT/'Caddyfile')
proxy=subprocess.Popen(['caddy','run','--config',str(ROOT/'Caddyfile'),'--adapter','caddyfile'],stdout=None)
children={};stopping=False
def stop(*_):
    global stopping
    stopping=True
    for child in [*children.values(),proxy]:
        if child.poll() is None:child.terminate()
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
try:
    for _ in range(120):
        if (ROOT/'caddy/pki/authorities/local/root.crt').is_file():break
        if proxy.poll() is not None:raise RuntimeError('Local HTTPS proxy failed')
        time.sleep(1)
    from bootstrap import initialize
    initialize()
    services=json.loads((ROOT/'services.json').read_text())
    (ROOT/'logs').mkdir(exist_ok=True)
    def start(row):
        log=(ROOT/'logs'/(row['name']+'.log')).open('ab')
        child=subprocess.Popen([sys.executable,'/app/deployment/service_runner.py',row['name']],stdout=log,stderr=subprocess.STDOUT);log.close();return child
    while not stopping:
        if proxy.poll() is not None:raise RuntimeError('Local HTTPS proxy stopped')
        for row in services:
            child=children.get(row['name'])
            if child is None or child.poll() is not None:
                if child is not None:print('Restarting local service: '+row['name'],flush=True)
                children[row['name']]=start(row)
        time.sleep(3)
finally:
    stop()
    for child in children.values():
        try:child.wait(timeout=20)
        except subprocess.TimeoutExpired:child.kill()
    try:proxy.wait(timeout=10)
    except subprocess.TimeoutExpired:proxy.kill()
