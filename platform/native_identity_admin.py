"""Fixed-realm Keycloak REST adapter; callers supply their verified staff JWT."""
from urllib.parse import quote,urlsplit
import httpx
from native_iam_business import IamBusinessError
class NativeIdentityAdmin:
    def __init__(self,url,token,*,realm='staff',verify=True,transport=None):
        p=urlsplit(url)
        if p.scheme not in {'http','https'} or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in {'','/'} or realm!='staff' or not token:raise ValueError('Explicit staff identity origin and verified token required')
        self.url=url.rstrip('/')+'/admin/realms/'+realm;self.token=token;self.verify=verify;self.transport=transport
    def call(self,method,path,*,params=None,body=None):
        try:
            with httpx.Client(timeout=20,trust_env=False,verify=self.verify,transport=self.transport,follow_redirects=False) as c:result=c.request(method,self.url+path,params=params,json=body,headers={'authorization':'Bearer '+self.token})
        except httpx.HTTPError:raise IamBusinessError('Identity administration service unavailable') from None
        if result.status_code==404:return {'not_found':True}
        if result.status_code==409:return {'conflict':True}
        if not result.is_success:raise IamBusinessError('Identity administration request rejected')
        if not result.content:return None
        try:return result.json()
        except ValueError:raise IamBusinessError('Identity administration response is invalid') from None
    def resolve(self,name):
        values=self.call('GET','/clients',params={'clientId':name})
        if not isinstance(values,list):raise IamBusinessError('Identity client lookup failed')
        match=next((item for item in values if item.get('clientId')==name and item.get('id')),None)
        return match['id'] if match else None
    def create_client(self,name,description=None):
        if self.resolve(name):return name,True
        result=self.call('POST','/clients',body={'clientId':name,'enabled':True,'clientAuthenticatorType':'client-secret','secret':'','protocol':'openid-connect','publicClient':False,**({'description':description} if description else {})})
        return name,bool(isinstance(result,dict) and result.get('conflict'))
    def delete_client(self,name):
        identifier=self.resolve(name)
        if not identifier:return False
        result=self.call('DELETE','/clients/'+quote(identifier,safe=''));return not(isinstance(result,dict) and result.get('not_found'))
    def create_role(self,name,application,role_description=None):
        identifier=self.resolve(application)
        if not identifier:raise IamBusinessError('Identity application client not found')
        result=self.call('POST','/clients/'+quote(identifier,safe='')+'/roles',body={'name':name,**({'description':role_description} if role_description else {})})
        return name,bool(isinstance(result,dict) and result.get('conflict'))
    def delete_role(self,name,application):
        identifier=self.resolve(application)
        if not identifier:raise IamBusinessError('Identity application client not found')
        result=self.call('DELETE','/clients/'+quote(identifier,safe='')+'/roles/'+quote(name,safe=''));return not(isinstance(result,dict) and result.get('not_found'))
