"""Own bounded HTTP reader for authoritative attribute code lists."""
import datetime,time,uuid,threading
import httpx
from registry_metadata_api import RegistryAuthError
class MasterCodeClient:
    def __init__(self,settings,transport=None):
        self.settings=dict(settings);self.transport=transport;self._codes=None;self._until=0;self._token=None;self._token_until=0;self._lock=threading.Lock()
    def codes(self):
        with self._lock:
            if self._codes is not None and time.monotonic()<self._until:return self._codes
            cfg=self.settings;base=cfg.get('api_url','').rstrip('/')
            if not base:raise RegistryAuthError(503,'Authoritative attribute code service is unavailable')
            timeout=float(cfg.get('timeout_seconds') or 10)
            try:
                with httpx.Client(timeout=timeout,transport=self.transport,trust_env=False,follow_redirects=False) as client:
                    def token(refresh=False):
                        if refresh:self._token=None
                        if not all(cfg.get(k) for k in ['token_url','client_id','client_secret']):return None
                        if not self._token or time.monotonic()>=self._token_until:
                            response=client.post(cfg['token_url'],data={'grant_type':'client_credentials','client_id':cfg['client_id'],'client_secret':cfg['client_secret']});response.raise_for_status();value=response.json();self._token=value.get('access_token')
                            if not self._token:raise ValueError('Missing service token')
                            self._token_until=time.monotonic()+max(float(value.get('expires_in') or 300)-30,1)
                        return self._token
                    codes={}
                    for page in range(1,201):
                        envelope={'request_header':{'sender_app_mnemonic':'KarnatakaDBT','sender_app_url':'https://localhost:8443','request_id':uuid.uuid4().hex,'request_timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat()},'request_body':{'request_payload':{'attribute_id':None},'pagination_request':{'current_page':page,'page_size':1000}}}
                        def send(access):return client.post(base+'/attributes/get_attribute_values',json=envelope,headers={'authorization':'Bearer '+access} if access else {})
                        access=token();response=send(access)
                        if response.status_code==401 and access:response=send(token(True))
                        response.raise_for_status();body=response.json();header=body.get('response_header') or {}
                        if header.get('response_status') not in {None,'','SUCCESS'}:raise ValueError('Code service rejected request')
                        payload=(body.get('response_body') or {}).get('response_payload');values=payload.get('attribute_values') or [] if isinstance(payload,dict) else payload
                        if not isinstance(values,list):raise ValueError('Malformed code list')
                        for row in values:
                            if isinstance(row,dict) and row.get('attribute_id') and row.get('value_code'):codes.setdefault(row['attribute_id'],set()).add(row['value_code'])
                        total=payload.get('total') if isinstance(payload,dict) else None
                        if len(values)<1000 or total is not None and page*1000>=int(total):break
                    else:raise ValueError('Code list exceeded bounded pagination')
            except Exception:raise RegistryAuthError(503,'Authoritative attribute code service is unavailable') from None
            self._codes=codes;self._until=time.monotonic()+float(cfg.get('cache_seconds') or 0);return codes
