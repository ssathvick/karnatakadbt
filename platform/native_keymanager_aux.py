"""Native auxiliary key operations with encrypted transactional state.

Legacy wire formats are explicit; no MOSIP code or network forwarding is used.
"""
import base64, datetime, hashlib, hmac, json, re, secrets, uuid
from cryptography import x509
from cryptography.exceptions import InvalidTag, InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from argon2.low_level import hash_secret_raw, Type
from native_keymanager import certificate, VaultFailure, stamp, utc, UTC
from native_keymanager_jose import unbase
from native_key_vault import canonical, encode


def text(value, *, maximum=1024*1024):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > maximum:
        raise VaultFailure('Bounded non-empty text required')
    return value


def when(value):
    try:
        if isinstance(value, list) and 3 <= len(value) <= 7:
            year, month, day, hour, minute, second, nano = (value+[0]*7)[:7]
            return datetime.datetime(year, month, day, hour, minute, second, nano//1000, tzinfo=UTC)
        raw=text(value, maximum=64).replace('Z','+00:00')
        # Python 3.10 accepts only millisecond or microsecond fractions; Java
        # and PostgreSQL emit any precision through nanoseconds.
        raw=re.sub(r'\.(\d{1,9})(?=Z|[+-]\d\d:\d\d|$)',lambda m:'.'+(m[1]+'000000')[:6],raw)
        return utc(datetime.datetime.fromisoformat(raw))
    except (ValueError, TypeError, OverflowError):
        raise VaultFailure('Invalid UTC timestamp')


class Auxiliary:
    def __init__(self, engine, settings):
        self.engine, self.settings = engine, settings
        with engine.vault.connect() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS km_records(kind TEXT NOT NULL,scope TEXT NOT NULL,
identifier TEXT NOT NULL,content BLOB NOT NULL,PRIMARY KEY(kind,scope,identifier))''')

    def seal(self, kind, scope, identifier, content):
        iv=secrets.token_bytes(12)
        return iv+self.engine.vault.aead.encrypt(iv,canonical(content),canonical([kind,scope,identifier]))

    def open(self, row):
        try:
            blob=row['content']
            return json.loads(self.engine.vault.aead.decrypt(blob[:12],blob[12:],canonical([row['kind'],row['scope'],row['identifier']])))
        except (ValueError, InvalidTag):
            raise VaultFailure('Stored record authentication failed')

    def load(self, c, kind, scope, identifier):
        row=c.execute('SELECT * FROM km_records WHERE kind=? AND scope=? AND identifier=?',(kind,scope,identifier)).fetchone()
        if not row:raise VaultFailure('Record is not registered in this scope')
        return self.open(row)

    def put(self, c, kind, scope, identifier, content, *, replace=False):
        c.execute(('INSERT OR REPLACE' if replace else 'INSERT')+' INTO km_records VALUES(?,?,?,?)',
                  (kind,scope,identifier,self.seal(kind,scope,identifier,content)))

    def pin(self, request, *, decrypt=False):
        pin=text(request.get('userPin'),maximum=4096).encode()
        data=text(request.get('data')).encode()
        if decrypt:
            raw=unbase(data.decode())
            if len(raw)<60:raise VaultFailure('Invalid PIN ciphertext')
            salt,iv,cipher=raw[:32],raw[32:44],raw[44:]
        else:salt,iv=secrets.token_bytes(32),secrets.token_bytes(12)
        key=hashlib.pbkdf2_hmac('sha512',pin,salt,self.settings.get('pin_iterations',100000),dklen=32)
        try:
            if decrypt:return {'data':AESGCM(key).decrypt(iv,cipher,salt).decode()}
            return {'data':encode(salt+iv+AESGCM(key).encrypt(iv,data,salt))}
        except (InvalidTag,UnicodeError):raise VaultFailure('PIN ciphertext authentication failed')

    def argon(self, request):
        data=text(request.get('inputData')).encode()
        salt=unbase(request['salt']) if request.get('salt') else secrets.token_bytes(16)
        if not 8<=len(salt)<=1024:raise VaultFailure('Invalid Argon2 salt')
        params=self.settings.get('argon2',{'iterations':10,'memory':65536,'parallelism':2})
        value=hash_secret_raw(data,salt,time_cost=params['iterations'],memory_cost=params['memory'],parallelism=params['parallelism'],hash_len=32,type=Type.ID,version=19)
        return {'hashValue':encode(value),'salt':encode(salt)}

    def symmetric(self, request):
        app,ref=request.get('applicationId'),request.get('referenceId')
        self.engine.policy(app,ref)
        force=request.get('force',False)
        if not isinstance(force,bool):raise VaultFailure('force must be boolean')
        scope=json.dumps([app,ref],separators=(',',':'))
        with self.engine.vault.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            exists=c.execute("SELECT 1 FROM km_records WHERE kind='symmetric-active' AND scope=? AND identifier='active'",(scope,)).fetchone()
            if not exists or force:
                identifier=uuid.uuid4().hex
                self.put(c,'symmetric-key',scope,identifier,{'key':encode(secrets.token_bytes(32)),'created':stamp(self.engine.clock()),'revoked':False})
                self.put(c,'symmetric-active',scope,'active',{'id':identifier},replace=True)
        return {'status':'SUCCESS','timestamp':stamp(self.engine.clock())}

    def raw_sign(self, request):
        app,ref=self.settings['default_application'],self.settings['default_reference']
        self.engine.get(app,ref)
        key=self.engine.vault._private(self.engine.vault.active(app,ref))
        header=encode(b'{"alg":"RS256"}')
        signing=(header+'.'+encode(text(request.get('data')).encode())).encode()
        signature=key.sign(signing,padding.PKCS1v15(),hashes.SHA256())
        return {'signature':header+'..'+encode(signature),'timestamp':utc(self.engine.clock()).isoformat(timespec='milliseconds').replace('+00:00','Z')}

    def raw_validate(self, request):
        app,ref=self.settings['default_application'],self.settings['default_reference']
        at=when(request.get('timestamp'));value=text(request.get('signature'));data=text(request.get('data')).encode()
        parts=value.split('.')
        if len(parts)!=3 or parts[1] or json.loads(unbase(parts[0]))!={'alg':'RS256'}:
            raise VaultFailure('Invalid detached signature')
        signature=unbase(parts[2]);data=(parts[0]+'.'+encode(data)).encode()
        with self.engine.vault.connect() as c:
            rows=c.execute('''SELECT k.state,t.certificate FROM vault_keys k JOIN km_certificates t ON k.id=t.key_id
WHERE k.application=? AND k.reference=? AND k.state IN ('ACTIVE','VERIFY_ONLY')''',(app,ref)).fetchall()
        for row in rows:
            cert=certificate(row['certificate'])
            if not cert.not_valid_before_utc<=at<cert.not_valid_after_utc:continue
            try:
                cert.public_key().verify(signature,data,padding.PKCS1v15(),hashes.SHA256())
                return {'status':'success','message':'Validation Successful'}
            except InvalidSignature:pass
        raise VaultFailure('Signature validation failed')

    def license_generate(self, request):
        tsp=text(request.get('tspId'),maximum=36);expiry=when(request.get('licenseExpiryTime'))
        if expiry<=utc(self.engine.clock()):raise VaultFailure('License must expire in the future')
        key=secrets.token_urlsafe(48);identifier=hashlib.sha256(key.encode()).hexdigest()
        with self.engine.vault.connect() as c:
            self.put(c,'license',tsp,identifier,{'license_key':key,'expires':stamp(expiry),'permissions':[],'active':True})
        return {'licenseKey':key}

    def license_permissions(self, request, *, update=False):
        tsp=text(request.get('tspId'),maximum=36);key=text(request.get('licenseKey'),maximum=255)
        identifier=hashlib.sha256(key.encode()).hexdigest()
        with self.engine.vault.connect() as c:
            if update:c.execute('BEGIN IMMEDIATE')
            row=self.load(c,'license',tsp,identifier)
            if not hmac.compare_digest(row['license_key'],key) or not row['active'] or when(row['expires'])<=utc(self.engine.clock()):
                raise VaultFailure('License is not active')
            if update:
                permissions=request.get('permissions')
                if not isinstance(permissions,list) or len(permissions)>256 or any(not isinstance(p,str) or p not in self.settings.get('license_permissions',[]) for p in permissions):
                    raise VaultFailure('Permission is not registered in the master list')
                row['permissions']=sorted(set(permissions));self.put(c,'license',tsp,identifier,row,replace=True)
                return {'status':'SUCCESS'}
            return {'permissions':row['permissions']}

    def partner_upload(self, request):
        domain=self.engine._domain(request.get('partnerDomain'));original=certificate(request.get('certificateData'))
        organization=text(request.get('organizationName'),maximum=256)
        if not self.engine.trust(request)['status']:raise VaultFailure('Partner certificate is not trusted in this domain')
        organizations=original.subject.get_attributes_for_oid(x509.NameOID.ORGANIZATION_NAME)
        if not organizations or any(v.value!=organization for v in organizations):raise VaultFailure('Organization does not match the certificate')
        app=self.settings['partner_signing_application']
        with self.engine.vault.connect() as c:
            c.execute('BEGIN IMMEDIATE');issuer_row=self.engine._row(c,app,'');issuer=certificate(issuer_row['certificate']);self.engine._ca(issuer)
            key=self.engine.vault._private(issuer_row);now=utc(self.engine.clock()).replace(microsecond=0)
            end=min(original.not_valid_after_utc,issuer.not_valid_after_utc,now+datetime.timedelta(days=self.settings.get('partner_validity_days',365)))
            signed=(x509.CertificateBuilder().subject_name(original.subject).issuer_name(issuer.subject).public_key(original.public_key())
                    .serial_number(x509.random_serial_number()).not_valid_before(max(original.not_valid_before_utc,now-datetime.timedelta(seconds=30)))
                    .not_valid_after(end).add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
                    .add_extension(x509.KeyUsage(digital_signature=True,content_commitment=True,key_encipherment=True,data_encipherment=False,
                       key_agreement=False,key_cert_sign=False,crl_sign=False,encipher_only=False,decipher_only=False),critical=True).sign(key,hashes.SHA256()))
            identifier=str(uuid.uuid4());pem=signed.public_bytes(serialization.Encoding.PEM).decode()
            self.put(c,'partner-certificate',domain,identifier,{'original':request['certificateData'],'signed':pem,'organization':organization})
        return {'certificateId':identifier,'signedCertificateData':pem,'timestamp':stamp(self.engine.clock())}

    def partner_get(self, identifier, domains, *, both=False):
        text(identifier,maximum=128)
        with self.engine.vault.connect() as c:
            rows=c.execute("SELECT * FROM km_records WHERE kind='partner-certificate' AND identifier=?",(identifier,)).fetchall()
        allowed=[r for r in rows if r['scope'] in domains]
        if len(allowed)!=1:raise VaultFailure('Partner certificate is not registered in an allowed domain')
        value=self.open(allowed[0])
        if both:return {'caSignedCertificateData':value['original'],'mosipSignedCertificateData':value['signed'],'timestamp':stamp(self.engine.clock())}
        return {'certificateData':value['signed'],'timestamp':stamp(self.engine.clock())}
