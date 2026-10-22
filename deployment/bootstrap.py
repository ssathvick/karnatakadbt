"""Create new local state from empty schemas; never import production records."""
import base64,datetime,json,os,pathlib,secrets,shutil,ssl,time,uuid
import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json
from sqlalchemy import create_engine,text
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization,hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography import x509
from cryptography.x509.oid import NameOID
from host_setup import resolve

ROOT=pathlib.Path('/app');STATE=pathlib.Path('/runtime')
def save(path,value):
    path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    path.write_bytes(value if isinstance(value,bytes) else (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode());path.chmod(0o600)
def fresh(path,value):
    if not pathlib.Path(path).exists():save(path,value)
def initialize():
    values=json.loads((STATE/'secrets.json').read_text());identifier=str(uuid.UUID(values['installation_id']))
    marker={'kind':'fresh-local-install','installation_id':identifier}
    fresh(STATE/'installation.json',marker)
    if json.loads((STATE/'installation.json').read_text())!=marker:raise ValueError('Local installation identity mismatch')
    for folder in ['databases','keys','config/registry','config/references','registration','status','logs']:(STATE/folder).mkdir(parents=True,exist_ok=True,mode=0o700)
    ca=STATE/'caddy/pki/authorities/local/root.crt'
    save(STATE/'tls/combined-ca.crt',pathlib.Path('/etc/ssl/certs/ca-certificates.crt').read_bytes()+b'\n'+ca.read_bytes())
    conf=resolve(json.loads((ROOT/'deployment/templates/services.json').read_text()),values)
    conn=dict(host='postgres',port=5432,user='kdbt',password=values['postgres_password'])
    admin=psycopg2.connect(**conn,dbname='postgres');admin.autocommit=True
    for schema in sorted((ROOT/'deployment/schemas').glob('*.sql')):
        name=schema.stem
        with admin.cursor() as q:
            q.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,))
            if not q.fetchone():q.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        with psycopg2.connect(**conn,dbname=name) as db,db.cursor() as q:
            q.execute("SELECT to_regclass('kdbt_local_control.installation')")
            if q.fetchone()[0] is None:
                q.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS pgcrypto;')
                q.execute(schema.read_text().replace('CREATE SCHEMA public;','CREATE SCHEMA IF NOT EXISTS public;'))
                q.execute('CREATE SCHEMA kdbt_local_control')
                q.execute('CREATE TABLE kdbt_local_control.installation(singleton boolean PRIMARY KEY CHECK(singleton),installation_id uuid NOT NULL,owner text NOT NULL)')
                q.execute("INSERT INTO kdbt_local_control.installation VALUES(true,%s,'NATIVE')",(identifier,))
            q.execute('SELECT installation_id::text FROM kdbt_local_control.installation WHERE singleton')
            if q.fetchone()[0]!=identifier:raise ValueError('Existing database belongs to another installation')
    admin.close()
    agent_database=conf['native-agent-oauth']['database_url'].rsplit('/',1)[-1]
    with psycopg2.connect(**conn,dbname=agent_database) as db,db.cursor() as q:
        q.execute("SELECT count(*) FROM login_providers WHERE issuer='https://localhost:8444/realms/agent'")
        if not q.fetchone()[0]:q.execute("INSERT INTO login_providers(id,created_at,updated_at,provider_name,client_id,client_secret,token_endpoint_auth_method,issuer,oauth_callback_url,default_redirect_uri,scope,enable_pkce,active) VALUES(2,NOW(),NOW(),'Local agent','local-agent',%s,'client_secret_post','https://localhost:8444/realms/agent','https://localhost:8443/auth/callback','https://localhost:8443','openid profile email',true,true)",(resolve(json.loads((ROOT/'deployment/templates/registration.json').read_text()),values)['clients']['beneficiary']['secret'],))
    metadata=resolve(json.loads((ROOT/'deployment/templates/metadata.json').read_text()),values)
    for database,tables in metadata.items():
        with psycopg2.connect(**conn,dbname=database) as db,db.cursor() as q:
            for table,rows in tables.items():
                q.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table)))
                if q.fetchone()[0]:continue
                for row in rows:
                    q.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,row)),sql.SQL(',').join(sql.Placeholder() for _ in row)),[Json(v) if isinstance(v,(dict,list)) else v for v in row.values()])
            q.execute("SELECT table_name,column_name,pg_get_serial_sequence(quote_ident(table_name),column_name) FROM information_schema.columns WHERE table_schema='public' AND column_default LIKE 'nextval%%'")
            for table,column,sequence in q.fetchall():
                if sequence:q.execute(sql.SQL('SELECT setval(%s,GREATEST(COALESCE(MAX({}),0),1),true) FROM {}').format(sql.Identifier(column),sql.Identifier(table)),(sequence,))
    for name,key in [('registry-journal.key',Fernet.generate_key()),('capture.key',secrets.token_urlsafe(40).encode()),('archive.key',Fernet.generate_key())]:fresh(STATE/'keys'/name,key)
    keypath=STATE/'keys/consent.pem'
    fresh(keypath,rsa.generate_private_key(public_exponent=65537,key_size=2048).private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    references=resolve(json.loads((ROOT/'deployment/templates/references.json').read_text()),values)
    for name,value in references.items():save(STATE/'config/references'/name,value)
    def patch(value):
        if isinstance(value,dict):
            for key,item in list(value.items()):
                if key=='cluster_hosts':value[key]={}
                elif key in ['historical_rows','source_digest','historical_sha256','source_baseline_snapshot','build_time']:value[key]=None
                elif key=='approval_url':value[key]='http://127.0.0.1:18087'
                elif key=='jwks_url' and isinstance(item,str) and '10.43.' in item:value[key]='https://localhost:8444/realms/staff/protocol/openid-connect/certs'
                elif key=='master_key' and isinstance(item,str):value[key]=base64.b64encode(base64.urlsafe_b64decode(item)).decode()
                elif key in ['cache_key','state_key'] and isinstance(item,str):value[key]=base64.b64encode(base64.urlsafe_b64decode(item)).decode()
                elif key=='native_recovery_settings_path':value.pop(key)
                else:patch(item)
        elif isinstance(value,list):
            for item in value:patch(item)
    patch(conf)
    conf['native-keymanager']['database']='/runtime/databases/keymanager.sqlite'
    conf['native-certify-candidate']['crypto']['database']='/runtime/databases/credential-crypto.sqlite'
    for name in ['native-iam','native-staff','native-partner','native-consent-staff','native-consent-public']:
        conf[name]['consent_public']['signing_kid']='kdbt-local-'+identifier
    conf['native-audit']['database_url']=conf['native-audit']['database_url'].replace('/kdbt_audit','/kdbt_audit_candidate_local')
    # Fresh native ownership uses empty databases. No legacy handoff receipts are fabricated.
    from native_domain_ownership import NativeDomainOwnership
    from native_spar_ownership import NativeSparOwnership
    from native_administration_ownership import AdministrationOwnership
    groups=[(NativeDomainOwnership,conf['native-bank-api']['database_url'],'bank'),(NativeDomainOwnership,conf['native-bridge-worker']['database_url'],'bridge'),(NativeSparOwnership,conf['native-spar-partner']['database_url'],None)]
    groups += [(AdministrationOwnership,conf[name]['database_url'],profile) for name,profile in [('native-iam','iam'),('native-partner','partner'),('native-consent-staff','consent')]]
    for cls,url,profile in groups:
        engine=create_engine(url,hide_parameters=True);owner=cls(engine,profile) if profile else cls(engine);owner.initialize(identifier)
        schema='kdbt_administration_control' if cls is AdministrationOwnership else ('kdbt_spar_control' if profile is None else 'kdbt_'+profile+'_control')
        predicate="profile=:profile" if cls is AdministrationOwnership else 'singleton'
        with engine.connect() as c:current=c.execute(text('SELECT owner,generation FROM '+schema+'.ownership WHERE '+predicate),{'profile':profile}).one()
        if cls is NativeSparOwnership:
            with engine.begin() as c:
                c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('karnatakadbt-account-mapping-ownership',0))"))
                c.execute(text("UPDATE kdbt_spar_control.ownership SET owner='NATIVE',generation=generation+1 WHERE singleton AND owner IN ('SOURCE','FENCED')"))
            engine.dispose();continue
        if current[0]=='SOURCE':
            with owner.transition('SOURCE',current[1]) as change:change('FENCED')
            current=('FENCED',current[1]+1)
        if current[0]=='FENCED':
            with owner.transition('FENCED',current[1]) as change:change('NATIVE')
        engine.dispose()
    # Generate independent RSA authorities for authorization and synthetic identity.
    identity_public=None
    for scope,directory in [('esignet','auth'),('mock','mock')]:
        folder=STATE/'signing'/directory;folder.mkdir(parents=True,exist_ok=True)
        if not (folder/'vault.bin').exists():
            master=secrets.token_bytes(32);entries={};now=datetime.datetime.now(datetime.timezone.utc)
            apps=conf['native-auth-candidate']['signing']['applications'] if scope=='esignet' else ['MOCK']
            for app in apps:
                alias=str(uuid.uuid4());key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
                subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'KarnatakaDBT local '+app)])
                cert=x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=1)).not_valid_after(now+datetime.timedelta(days=1095)).sign(key,hashes.SHA256())
                entries[alias]={'private':base64.b64encode(key.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())).decode(),'certificate':base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()}
                if scope=='esignet':
                    with psycopg2.connect(**conn,dbname='kdbt_authorization') as db,db.cursor() as q:q.execute("INSERT INTO esignet.key_alias(id,app_id,ref_id,key_gen_dtimes,key_expire_dtimes,status_code,lang_code,cr_by,cr_dtimes,is_deleted,cert_thumbprint,uni_ident) VALUES(%s,%s,'',%s,%s,'Active','eng','local-installer',%s,false,%s,%s)",(alias,app,now,now+datetime.timedelta(days=1095),now,cert.fingerprint(hashes.SHA256()).hex(),uuid.uuid4().hex))
            nonce=secrets.token_bytes(12);save(folder/'master.key',master);save(folder/'vault.bin',nonce+AESGCM(master).encrypt(nonce,json.dumps(entries).encode(),('native-java-keystore-v1:'+scope).encode()))
        if scope=='mock':
            raw=(folder/'vault.bin').read_bytes();entries=json.loads(AESGCM((folder/'master.key').read_bytes()).decrypt(raw[:12],raw[12:],b'native-java-keystore-v1:mock'))
            alias,entry=next(iter(entries.items()));cert=x509.load_der_x509_certificate(base64.b64decode(entry['certificate']));identity_public=cert.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
            for name in ['native-identity-authority','native-wallet-identity-candidate']:conf[name].update(signing_alias=alias,signing_vault_directory=str(folder),authority_owner='CANDIDATE',production_signing_verified=False)
    conf['native-certify-candidate']['business']['did']='did:web:localhost%3A8456:v1:certify'
    auth=conf['native-auth-candidate'];auth['signing'].update(directory='/runtime/signing/auth',jose_ids={});auth['identity_verification_keys']=[identity_public]
    save(STATE/'config/session-templates.json',{})
    # Retained key names and operation identifiers describe wire compatibility only.
    for name,config in conf.items():
        for field,value in list(config.items()):
            if field.endswith('_path') and isinstance(value,str) and value.startswith('/runtime/config/references/') and not pathlib.Path(value).exists():
                if field=='archive_key_path':fresh(value,(STATE/'keys/archive.key').read_bytes())
                elif field=='callback_settings_path':save(value,{'callback_secret':values['s016']})
                elif field=='identity_recovery_settings_path':save(value,{'identity_recovery_key':values['s016']})
                elif field=='master_ownership_settings_path':config.pop(field)
                else:fresh(value,(STATE/'keys/capture.key').read_bytes())
        if 'audit_config' in config:config['audit_config']=None
    approval=conf['approval'];callback_cipher=Fernet(pathlib.Path(approval['archive_key_path']).read_bytes());callback_path=pathlib.Path(approval['native_callback_secrets_path'])
    callbacks=json.loads(callback_cipher.decrypt(callback_path.read_bytes())) if callback_path.exists() else {}
    callbacks.setdefault('register',conf['native-registry']['webhook_settings']['hmac_secret']);callbacks.setdefault('consent',values['s016'])
    save(callback_path,callback_cipher.encrypt(json.dumps(callbacks).encode()))
    approval['callback_origins']=['http://127.0.0.1:18120','http://127.0.0.1:18111','https://localhost:8446','https://localhost:8449']
    conf['native-audit']['audit_manager']['kafka']['bootstrap_servers']='kafka:9092'
    registry=resolve(json.loads((ROOT/'deployment/templates/registry.json').read_text()),values)
    worker_identity=registry['worker-authority-settings.json']
    worker_identity.update(token_url='http://keycloak:8080/realms/staff/protocol/openid-connect/token',iam_url='http://127.0.0.1:18110',allowed_origins=['http://keycloak:8080','http://127.0.0.1:18110'])
    import httpx,jwt
    for attempt in range(120):
        try:
            response=httpx.post(worker_identity['token_url'],data={'grant_type':'client_credentials','client_id':worker_identity['client_id'],'client_secret':worker_identity['client_secret']},timeout=5)
            response.raise_for_status();worker_identity['subject']=jwt.decode(response.json()['access_token'],options={'verify_signature':False})['sub'];break
        except Exception:
            if attempt==119:raise RuntimeError('Fresh worker service-account login failed') from None
            time.sleep(2)
    for name,config in registry.items():
        if 'token_url' in config:config['token_url']='http://keycloak:8080/realms/staff/protocol/openid-connect/token'
        if name=='workflow-settings.json':config['callback_url']='http://127.0.0.1:18120/awe/webhooks/decision'
        if name=='worker-integration-settings.json':config.update(keycloak_admin_realm='staff',keycloak_admin_url='http://keycloak:8080')
        if name=='storage-settings.json':config.update(endpoint='minio:9000',access_key='local-storage',secret_key=values['minio_password'],bucket='kdbt-registry-canary-local',public_endpoint='localhost:8468')
        save(STATE/'config/registry'/name,config)
    from minio import Minio
    storage=Minio('minio:9000',access_key='local-storage',secret_key=values['minio_password'],secure=False)
    if not storage.bucket_exists('kdbt-registry-canary-local'):storage.make_bucket('kdbt-registry-canary-local')
    # Configure IAM's freshly created staff provider; no imported users or old secrets.
    issuer='https://localhost:8444/realms/staff';client='iqs-registration-staff';secret=resolve(json.loads((ROOT/'deployment/templates/registration.json').read_text()),values)['clients']['staff']['secret']
    with psycopg2.connect(**conn,dbname='kdbt_iam') as db,db.cursor() as q:
        q.execute("SELECT count(*) FROM login_providers WHERE issuer='https://localhost:8444/realms/staff'")
        if not q.fetchone()[0]:q.execute("INSERT INTO login_providers(id,created_at,updated_at,provider_name,description,client_id,client_secret,token_endpoint_auth_method,issuer,oauth_callback_url,default_redirect_uri,scope,enable_pkce,active) VALUES(1,NOW(),NOW(),'Local staff','Fresh local Keycloak realm',%s,%s,'client_secret_post',%s,'https://localhost:8445/auth/callback','https://localhost:8445/console/','openid profile email',true,true)",(client,secret,issuer))
    for name,config in conf.items():save(STATE/'config'/(name+'.json'),config)
    from types import SimpleNamespace
    from native_bridge_workers import NativeBridgeWorkers
    from native_example_bank import NativeExampleBank
    engine=create_engine(conf['native-bank-worker']['database_url'],hide_parameters=True)
    NativeExampleBank(engine).initialize_queue();engine.dispose()
    engine=create_engine(conf['native-bridge-worker']['database_url'],hide_parameters=True)
    NativeBridgeWorkers.initialize_queue(SimpleNamespace(engine=engine));engine.dispose()
    from native_farmer_registry import FarmerRegistry
    engine=create_engine(conf['native-farmer']['database_url'],hide_parameters=True)
    with engine.begin() as c:c.execute(text('CREATE SCHEMA IF NOT EXISTS kdbt_farmer_registry'))
    FarmerRegistry(engine).initialize();engine.dispose()
    from native_identity_recovery import RecoverableIdentityAdmin
    engine=create_engine(conf['native-iam']['database_url'],hide_parameters=True)
    RecoverableIdentityAdmin(engine,None,values['s016']).initialize();engine.dispose()
    registration=STATE/'registration'
    for directory in ['templates','static']:
        target=registration/directory
        if not target.exists():target.symlink_to(ROOT/'platform'/directory,target_is_directory=True)
    save(registration/'config.json',resolve(json.loads((ROOT/'deployment/templates/registration.json').read_text()),values))
    core_url='postgresql+psycopg2://kdbt:'+values['postgres_password']+'@postgres:5432/kdbt_core'
    save(registration/'core-connections.json',{'url':core_url})
    save(registration/'g2p-migration-policy.json',{'legacy_registry_projection':False,'registry_projection_mode':'standalone'})
    save(registration/'native-registry-writer-settings.json',{'url':conf['native-registry']['database_url']})
    from core_store import CoreStore
    store=CoreStore(core_url);store.migrate();store.engine.dispose()
    identifier_config={'id_generator':{'sequence_limit':3,'repeating_limit':2,'repeating_block_limit':2,'conjugative_even_digits_limit':3,'digits_group_limit':5,'reverse_digits_group_limit':5,'not_start_with':['0','1'],'restricted_numbers':[],'pool_min_threshold':100,'pool_generation_batch_size':500,'pool_check_interval_seconds':30,'exhaustion_max_attempts':1000,'sub_batch_size':1000,'id_types':{'farmer':{'id_length':12},'household':{'id_length':10},'individual':{'id_length':12}}}}
    save(registration/'identifier-config.json',identifier_config)
    from identifier_store import IdentifierStore,metadata as identifier_metadata
    engine=create_engine(core_url,hide_parameters=True);identifier_metadata.create_all(engine);IdentifierStore(engine).configure(identifier_config['id_generator']);engine.dispose()
    services=json.loads((ROOT/'deployment/services.json').read_text())
    services += [{'name':'portal','factory':'local_portal','port':18081},{'name':'approval-console','module':'native_approval_console_service','factory':'app','port':18135,'env':'KDBT_APPROVAL_CONSOLE_SETTINGS'}]
    services += [{'name':'identifiers','module':'identifier_api','factory':'native_app','port':18082}]
    worker=resolve(json.loads((ROOT/'deployment/templates/registry-worker.json').read_text()),values)
    worker.update(approval_url='http://127.0.0.1:18087',identifier_url='http://127.0.0.1:18082',health_file='/runtime/status/registry-worker.json',sync_health_file=None)
    save(STATE/'config/registry-worker.json',worker)
    services += [{'name':'registry-worker','module':'registry_worker_service','kind':'worker','env':'KDBT_REGISTRY_WORKER_SETTINGS'}]
    save(STATE/'config/approval-console.json',{'directory':'/app/platform/approval-console'})
    paths={'portal':'/registration/api/v2/health','native-audit':'/v1/auditmanager/health','approval':'/v1/awe/health','identifiers':'/v1/idgenerator/health'}
    for row in services:
        if row.get('port'):row['health']='http://127.0.0.1:'+str(row['port'])+paths.get(row['name'],'/health')
    save(STATE/'services.json',services)
