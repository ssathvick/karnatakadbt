"""Fresh Keycloak configuration. This module requires only Python's stdlib."""
import json,pathlib,re,datetime
def resolve(value,secrets):
    if isinstance(value,dict):return {resolve(k,secrets):resolve(v,secrets) for k,v in value.items()}
    if isinstance(value,list):return [resolve(v,secrets) for v in value]
    if isinstance(value,str):
        return re.sub(r'\$\{([^}]+)\}',lambda m:str(secrets.get(m[1].removeprefix('secret:'),m[0])),value)
    return value

def create_realms(root,local,secrets):
    config=resolve(json.loads((root/'deployment/templates/services.json').read_text()),secrets)
    registration=resolve(json.loads((root/'deployment/templates/registration.json').read_text()),secrets)
    metadata=resolve(json.loads((root/'deployment/templates/metadata.json').read_text()),secrets)
    iam=metadata['kdbt_iam'];apps={row['id']:row['application_mnemonic'] for row in iam['staff_portal_applications']}
    client_roles={}
    for role in iam['staff_roles']:client_roles.setdefault(apps[role['application_id']],[]).append(role['role_mnemonic'])
    client_secrets={}
    def collect(value):
        if isinstance(value,dict):
            if value.get('client_id') and value.get('client_secret'):client_secrets[value['client_id']]=value['client_secret']
            for item in value.values():collect(item)
        elif isinstance(value,list):
            for item in value:collect(item)
    collect(config)
    collect(resolve(json.loads((root/'deployment/templates/registry.json').read_text()),secrets))
    staff_id=registration['clients']['staff']['id'];staff_secret=registration['clients']['staff']['secret']
    client_secrets[staff_id]=staff_secret
    clients=set(client_roles)|set(client_secrets)|{'iam-staff-ui','register-staff-portal','local-approval-directory','awe-admin-portal','master-data-ui'}
    realm_roles=['AWE_ADMIN','AWE_VIEWER','KEYMANAGER_ADMIN','CONSENT_MANAGER_ADMIN','CONSENT_MANAGER_APPROVER','partner_manager','iqs-registration-officer','iqs-verification-officer','iqs-programme-supervisor','iqs-intake-reviewer','kdbt-registration-officer','kdbt-verification-officer','kdbt-programme-supervisor','kdbt-intake-reviewer']
    roles_by_user={
      'admin':['AWE_ADMIN','AWE_VIEWER','KEYMANAGER_ADMIN','CONSENT_MANAGER_ADMIN','CONSENT_MANAGER_APPROVER','partner_manager','iqs-programme-supervisor','iqs-intake-reviewer','kdbt-programme-supervisor','kdbt-intake-reviewer'],
      'verifier':['iqs-verification-officer','iqs-intake-reviewer','kdbt-verification-officer','kdbt-intake-reviewer'],
      'officer':['iqs-registration-officer','kdbt-registration-officer'],
    }
    staff_clients=[]
    for name in sorted(clients):
        staff_clients.append({'clientId':name,'enabled':True,'protocol':'openid-connect','publicClient':name not in client_secrets,'secret':client_secrets.get(name),'standardFlowEnabled':True,'directAccessGrantsEnabled':True,'serviceAccountsEnabled':name in client_secrets,'redirectUris':['https://localhost:'+str(port)+'/*' for port in range(8443,8470)],'webOrigins':['https://localhost:'+str(port) for port in range(8443,8470)],'fullScopeAllowed':True,'attributes':{'pkce.code.challenge.method':'S256'} if name==staff_id else {}})
    grants={name:roles for name,roles in client_roles.items()}
    users=[]
    for name,roles in roles_by_user.items():
        assigned=grants if name=='admin' else {'register-staff-portal':['Intake Validator','Data Validator'] if name=='verifier' else ['Intake Officer','Data Editor']}
        users.append({'username':name,'email':name+'@example.invalid','firstName':'Local','lastName':name.title(),'enabled':True,'emailVerified':True,'realmRoles':roles,'clientRoles':{**assigned,**({'realm-management':['realm-admin']} if name=='admin' else {})},'credentials':[{'type':'password','value':secrets[name+'_password'],'temporary':False}]})
    for name in client_secrets:
        service_grants={'register-staff-portal':['KDBT_NATIVE_REGISTRY_WORKER']} if name=='karnatakadbt-native-registry-worker' else grants
        users.append({'username':'service-account-'+name,'serviceAccountClientId':name,'enabled':True,'clientRoles':{**service_grants,'realm-management':['view-users','query-users','view-clients']}})
    for client in staff_clients:
        client['protocolMappers']=[{'name':'local-account-audience','protocol':'openid-connect','protocolMapper':'oidc-audience-mapper','config':{'included.client.audience':'account','access.token.claim':'true','id.token.claim':'false'}}]
    staff={'realm':'staff','enabled':True,'sslRequired':'external','registrationAllowed':False,'roles':{'realm':[{'name':x} for x in realm_roles],'client':{name:[{'name':role} for role in roles] for name,roles in client_roles.items()}},'clients':staff_clients,'users':users}
    beneficiary_id=registration['clients']['beneficiary']['id']
    beneficiary={'realm':'beneficiary','enabled':True,'sslRequired':'external','registrationAllowed':False,'clients':[{'clientId':beneficiary_id,'enabled':True,'secret':registration['clients']['beneficiary']['secret'],'publicClient':False,'standardFlowEnabled':True,'directAccessGrantsEnabled':True,'redirectUris':['https://localhost:'+str(port)+'/*' for port in range(8443,8470)],'webOrigins':['https://localhost:'+str(port) for port in range(8443,8470)],'attributes':{'pkce.code.challenge.method':'S256'}}],'users':[{'username':'citizen','email':'citizen@example.invalid','firstName':'Synthetic','lastName':'Citizen','enabled':True,'emailVerified':True,'credentials':[{'type':'password','value':secrets['beneficiary_password'],'temporary':False}]}]}
    folder=local/'keycloak';folder.mkdir(parents=True,exist_ok=True)
    agent=json.loads(json.dumps(beneficiary));agent['realm']='agent';agent['clients'][0]['clientId']='local-agent'
    agent['clients'][0]['attributes']={};agent['users'][0]['username']='agent'
    for name,value in [('staff',staff),('beneficiary',beneficiary),('agent',agent)]:
        path=folder/(name+'-realm.json');path.write_text(json.dumps(value,indent=2));path.chmod(0o600)
