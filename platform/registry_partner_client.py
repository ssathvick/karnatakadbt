"""Own bounded HTTP partner lookup; no partner-management implementation imports."""
import threading,time
from urllib.parse import quote
import httpx
from registry_metadata_api import RegistryAuthError
from registry_metadata_store import RegistryError
class RegistryPartnerClient:
    def __init__(self,settings,transport=None):self.settings=dict(settings);self.transport=transport;self._token=None;self._until=0;self._cache={};self._lock=threading.Lock()
    def require_active(self,sender):
        raw=(sender or '').strip();mapped=raw.replace('-','_').replace(' ','_').upper();mapped=mapped if mapped.startswith('PARTNER_') else 'PARTNER_'+mapped if mapped else '';candidates=list(dict.fromkeys(v for v in [raw,mapped] if v));cfg=self.settings
        def denied():raise RegistryError('REGP-ERR-001','PARTNER_NOT_REGISTERED')
        if not candidates:denied()
        admin=all(cfg.get(k) for k in ['admin_api_url','token_url','client_id','client_secret']);keys=cfg.get('keys_api_url');ttl=float(cfg.get('cache_seconds') or 0)
        if not admin and not keys:raise RegistryAuthError(503,'Partner verification service is not configured')
        with self._lock:
            for key in candidates:
                cached=self._cache.get(key)
                if cached and cached[0]>time.monotonic():
                    if cached[1] is None:denied()
                    return cached[1]
            try:
                with httpx.Client(timeout=float(cfg.get('timeout_seconds') or 5),transport=self.transport,trust_env=False,follow_redirects=False) as client:
                    def token(refresh=False):
                        if refresh:self._token=None
                        if not self._token or time.monotonic()>=self._until:
                            response=client.post(cfg['token_url'],data={'grant_type':'client_credentials','client_id':cfg['client_id'],'client_secret':cfg['client_secret']})
                            if not response.is_success:denied()
                            body=response.json();self._token=body.get('access_token')
                            if not self._token:denied()
                            try:lifetime=float(body.get('expires_in') or 300)
                            except (TypeError,ValueError):lifetime=300
                            self._until=time.monotonic()+max(lifetime-30,1)
                        return self._token
                    partner=None
                    for candidate in candidates:
                        if admin:
                            url=cfg['admin_api_url'].rstrip('/')+'/partners/'+quote(candidate,safe='');response=client.get(url,headers={'authorization':'Bearer '+token()})
                            if response.status_code==401:response=client.get(url,headers={'authorization':'Bearer '+token(True)})
                            if response.is_success:
                                body=response.json()
                                if str(body.get('status') or '').lower()=='active':partner={'partner_id':body.get('partner_id') or candidate,'name':body.get('name') or '','status':'active'}
                        if partner is None and keys:
                            response=client.get(keys.rstrip('/')+'/keys/'+quote(candidate,safe=''))
                            if response.status_code==200:partner={'partner_id':candidate,'name':'','status':'active'}
                        if partner:break
            except RegistryError:raise
            except Exception:raise RegistryAuthError(503,'Partner verification service is unavailable') from None
            if len(self._cache)>=1024:self._cache.clear()
            if ttl>0:
                for key in candidates+([partner['partner_id']] if partner else []):self._cache[key]=(time.monotonic()+ttl,partner)
            if partner is None:denied()
            return partner
