"""Pinned issuer/audience and per-operation role checks for Keymanager."""
import ssl,jwt
from native_key_vault import VaultFailure


class KeymanagerIdentity:
    def __init__(self,settings,key_lookup=None):
        self.settings=settings
        self.key_lookup=key_lookup or jwt.PyJWKClient(settings['jwks_url'],ssl_context=ssl.create_default_context(
            cafile=settings.get('ca_file','/etc/ssl/certs/ca-certificates.crt')),timeout=5).get_signing_key_from_jwt

    def authorize(self,token,operation,permission,applications):
        try:
            key=self.key_lookup(token);key=getattr(key,'key',key)
            claims=jwt.decode(token,key,algorithms=['RS256'],issuer=self.settings['issuer'],audience=self.settings['audiences'],
                leeway=10,options={'require':['exp','iat','iss','aud','sub']})
            roles=set(claims.get('realm_access',{}).get('roles',[]))
            for resource in claims.get('resource_access',{}).values():roles.update(resource.get('roles',[]))
            if not all(isinstance(v,str) for v in roles):raise ValueError()
            roles={r.removeprefix('ROLE_') for r in roles}
            required=set(self.settings['operation_roles'].get(operation,[]))
            if '__AUTHENTICATED__' not in required and not roles.intersection(required):raise VaultFailure('role_denied')
            return {'permissions':[permission],'applications':applications,'domains':self.settings['domains'],
                'all_tsp_ids':True,'all_partner_codes':True,'authenticated_subject':claims['sub']}
        except VaultFailure:raise
        except (jwt.PyJWTError,ValueError,TypeError,KeyError,AttributeError):raise VaultFailure('invalid_token')
