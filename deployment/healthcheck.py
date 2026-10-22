import datetime,json,pathlib,sys,urllib.request
def main():
    path=pathlib.Path('/runtime/services.json')
    if not path.is_file():return 1
    rows=json.loads(path.read_text());failed=[]
    for row in rows:
        if not row.get('health'):continue
        try:
            with urllib.request.urlopen(row['health'],timeout=2) as response:
                if response.status!=200:failed.append(row['name'])
                else:
                    value=json.load(response)
                    if value.get('ready') is False:failed.append(row['name'])
                    if row['name'] in ['native-bank-worker','native-bridge-worker'] and value.get('worker_state')!='RUNNING':failed.append(row['name'])
        except Exception:failed.append(row['name'])
    try:
        state=json.loads(pathlib.Path('/runtime/status/registry-worker.json').read_text())
        if state.get('state')!='RUNNING' or not state.get('ownership_admitted'):failed.append('registry-worker')
        if (datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(state['at'])).total_seconds()>30:failed.append('registry-worker-heartbeat')
    except Exception:failed.append('registry-worker')
    print(json.dumps({'ready':not failed,'services':len(rows),'not_ready':failed}))
    return int(bool(failed))
if __name__=='__main__':sys.exit(main())
