"""Own detached-JWS verification with registered partner public keys."""
import base64,json,threading,time
from urllib.parse import quote,urlsplit
import httpx,jwt,orjson
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from jwt.api_jws import PyJWS

class PartnerKeyUnavailable(Exception):pass

class NativePartnerVerificationKeys:
    def __init__(self,url,*,soft_ttl=300,hard_ttl=900,negative_ttl=30,timeout=5,transport=None):
        parsed=urlsplit(url)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('Explicit partner key service origin required')
        if min(soft_ttl,hard_ttl,negative_ttl)<0 or hard_ttl<soft_ttl:raise ValueError('Invalid partner key cache windows')
        self.url=url.rstrip('/');self.soft,self.hard,self.negative,self.timeout=soft_ttl,hard_ttl,negative_ttl,timeout;self.transport=transport;self.cache={};self.lock=threading.Lock()
    def __call__(self,reference,kid=None):
        with self.lock:
            now=time.monotonic();prior=self.cache.get(reference)
            if prior and prior['soft']>now and (not kid or not prior['keys'] or any(row.get('kid')==kid for row in prior['keys'])):return prior['keys']
            try:
                with httpx.Client(trust_env=False,follow_redirects=False,timeout=self.timeout,transport=self.transport) as client:
                    headers={'If-None-Match':prior['etag']} if prior and prior.get('etag') else {}
                    response=client.get(self.url+'/keys/'+quote(reference,safe=''),headers=headers)
                if response.status_code==304:
                    if not prior:raise PartnerKeyUnavailable('Partner key cache was not initialized')
                    prior.update(soft=now+self.soft,hard=now+self.hard);return prior['keys']
                if response.status_code in {404,410}:keys=[];ttl=self.negative
                elif response.status_code==200:
                    keys=response.json()['keys'];ttl=self.soft
                    for directive in response.headers.get('cache-control','').lower().split(','):
                        directive=directive.strip()
                        if directive.startswith('max-age='):
                            try:ttl=min(ttl,max(0,float(directive.split('=',1)[1])))
                            except ValueError:pass
                    if not isinstance(keys,list) or any(not isinstance(row,dict) or not row.get('public_key') for row in keys):raise ValueError('Invalid partner public key response')
                else:raise PartnerKeyUnavailable('Partner key service unavailable')
                if len(self.cache)>=1024:self.cache.clear()
                self.cache[reference]={'keys':keys,'soft':now+ttl,'hard':now+(self.hard if keys else ttl),'etag':response.headers.get('etag')};return keys
            except Exception:
                if prior and prior['keys'] and prior['hard']>now:return prior['keys']
                raise PartnerKeyUnavailable('Partner key lookup unavailable') from None

class NativePartnerSignatures:
    def __init__(self,lookup,*,algorithms=('RS256',)):
        supported={'RS256','RS384','RS512','PS256','PS384','PS512','ES256','ES384','ES512','EdDSA'}
        if not algorithms or set(algorithms)-supported:raise ValueError('Explicit asymmetric signature algorithms required')
        self.lookup,self.algorithms=lookup,tuple(algorithms);self.jws=PyJWS()
    @staticmethod
    def partner_reference(payload):
        header=payload.get('header') or payload.get('request_header') or {};sender=header.get('sender_id') if payload.get('header') else header.get('sender_app_mnemonic')
        if not isinstance(sender,str) or not sender:return 'PARTNER_UNKNOWN'
        return 'PARTNER_'+sender.replace('-','_').upper()
    def verify(self,signature,payload):
        if not isinstance(signature,str) or len(signature)>65536:return False
        try:
            protected,ignored,signed=signature.split('.');header=jwt.get_unverified_header(signature);algorithm=header.get('alg');kid=header.get('kid')
            if algorithm not in self.algorithms or header.get('crit') or header.get('b64') is False or kid is not None and (not isinstance(kid,str) or len(kid)>512):return False
            encoded=base64.urlsafe_b64encode(orjson.dumps(payload,option=orjson.OPT_SORT_KEYS)).rstrip(b'=').decode();complete=protected+'.'+encoded+'.'+signed
        except Exception:return False
        keys=self.lookup(self.partner_reference(payload),kid)
        for row in keys:
            if kid and row.get('kid') and row['kid']!=kid or row.get('algorithm') and row['algorithm']!=algorithm:continue
            try:
                pem=row['public_key'].encode();key=x509.load_pem_x509_certificate(pem).public_key() if b'BEGIN CERTIFICATE' in pem else serialization.load_pem_public_key(pem)
                self.jws.decode(complete,key,algorithms=[algorithm]);return True
            except Exception:continue
        return False
