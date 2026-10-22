import importlib,json,os,pathlib,sys,runpy
def main():
    name=sys.argv[1];services=json.loads(pathlib.Path('/runtime/services.json').read_text());row=next(r for r in services if r['name']==name)
    if row.get('env'):os.environ[row['env']]='/runtime/config/'+name+'.json'
    from standalone_ownership import install_profile
    install_profile()
    if row.get('kind')=='worker':return runpy.run_module(row['module'],run_name='__main__')
    import uvicorn
    if row.get('factory')=='local_portal':
        from portal import create_app
        app=create_app()
    else:
        module=importlib.import_module(row['module']);app=getattr(module,row.get('factory','app'))
        if row.get('factory') not in {'app',None}:app=app()
    uvicorn.run(app,host='0.0.0.0',port=row['port'],access_log=False,log_level='warning',proxy_headers=True,forwarded_allow_ips='127.0.0.1')
if __name__=='__main__':main()
