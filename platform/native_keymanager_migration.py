"""Native key import and legacy per-record encryption compatibility."""
import datetime,hashlib,secrets,sqlite3,struct,uuid
from cryptography import x509
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from native_keymanager import certificate,public_bytes,stamp,utc,VaultFailure
from native_keymanager_aux import text,when
from native_keymanager_jose import unbase
from native_keymanager_wire import oaep
from native_key_vault import encode


def derived(identifier,key):
    cipher=Cipher(algorithms.AES(key),modes.ECB()).encryptor()
    return cipher.update(hashlib.sha256(identifier.encode()).digest())+cipher.finalize()


def import_base(aux,request):
    engine=aux.engine;app,ref=request.get('applicationId'),request.get('referenceId')
    engine.policy(app,ref);text(ref,maximum=256)
    cert=certificate(request.get('certificateData'));engine._valid(cert)
    start=when(request['notBefore']) if request.get('notBefore') else cert.not_valid_before_utc
    end=when(request['notAfter']) if request.get('notAfter') else cert.not_valid_after_utc
    if start>=end or start<cert.not_valid_before_utc or end>cert.not_valid_after_utc:raise VaultFailure('Invalid import validity interval')
    blob=unbase(request.get('encryptedKeyData'))
    with engine.vault.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT 1 FROM vault_aliases WHERE application=? AND reference=?',(app,ref)).fetchone():
            return {'status':'Migration Not Allowed. Valid Key Exists.','timestamp':stamp(engine.clock())}
        master=engine._row(c,app,'');key=engine.vault._private(master);size=key.key_size//8;splitter=aux.settings['data_key_splitter'].encode()
        if blob[size:size+len(splitter)]!=splitter:raise VaultFailure('Invalid encrypted base-key envelope')
        try:
            cek=key.decrypt(blob[:size],oaep());cipher=blob[size+len(splitter):]
            private=serialization.load_der_private_key(AESGCM(cek).decrypt(cipher[-16:],cipher[:-16],None),None)
        except (ValueError,InvalidTag):raise VaultFailure('Base-key envelope authentication failed')
        if public_bytes(private.public_key())!=public_bytes(cert.public_key()):raise VaultFailure('Imported private key and certificate do not match')
        identifier=str(uuid.uuid4());row={'id':identifier,'application':app,'reference':ref,'algorithm':'RS256'}
        pem=private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        c.execute('INSERT INTO vault_keys VALUES(?,?,?,?,?,?,?,?)',(identifier,app,ref,'RS256',engine.vault._wrap(row,pem),
            private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo),'ACTIVE',start.timestamp()))
        c.execute('INSERT INTO km_certificates VALUES(?,?)',(identifier,request['certificateData']))
        c.execute('INSERT INTO km_effective_validity VALUES(?,?,?)',(identifier,start.timestamp(),end.timestamp()))
        c.execute('INSERT INTO km_jose_ids VALUES(?,?)',(identifier,encode(hashlib.sha256(bytes.fromhex(identifier.replace('-',''))).digest())))
        c.execute('INSERT INTO vault_aliases VALUES(?,?,?)',(app,ref,identifier))
        aux.put(c,'base-import',app,identifier,{'reference':ref,'notBefore':stamp(start),'notAfter':stamp(end),'original_encrypted_key':request['encryptedKeyData']})
    return {'status':'Migration Success','timestamp':stamp(engine.clock())}


class RecordCrypto:
    def __init__(self,aux):self.aux=aux;self.engine=aux.engine

    def scope(self):return self.aux.settings['zk_application']

    def temporary(self):
        app=self.aux.settings['migration_application'];ref=self.aux.settings.get('migration_reference','ZK_TEMP')
        policy=self.engine.policy(app,ref);now=utc(self.engine.clock()).replace(microsecond=0)
        with self.engine.vault.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('''SELECT k.*,t.certificate FROM vault_aliases a JOIN vault_keys k ON k.id=a.key_id
JOIN km_certificates t ON t.key_id=k.id WHERE a.application=? AND a.reference=?''',(app,ref)).fetchone()
            if old:
                cert=certificate(old['certificate'])
                if old['state']=='REVOKED' or old['private_blob'] is None:raise VaultFailure('Temporary key is unavailable')
                if now<cert.not_valid_before_utc:raise VaultFailure('Temporary key is not yet valid')
                if now<cert.not_valid_after_utc:
                    self.engine._row(c,app,ref)
                    return app,ref,self.engine._response(cert)
            if c.execute('SELECT 1 FROM km_disabled WHERE application=? AND reference=?',(app,ref)).fetchone():
                raise VaultFailure('Automatic temporary key generation is disabled')
            # Like the original migration protocol, this is an independent
            # one-day key. It must renew even when an application CA expires.
            size=policy.get('key_size',2048)
            if size not in {2048,3072,4096}:raise VaultFailure('Unsupported temporary RSA key size')
            key=rsa.generate_private_key(public_exponent=65537,key_size=size);identifier=uuid.uuid4().hex
            subject=self.engine.subject({'commonName':'Temporary record-key migration'},app)
            cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(seconds=30)).not_valid_after(now+datetime.timedelta(days=1))
                .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True).sign(key,hashes.SHA256()))
            row={'id':identifier,'application':app,'reference':ref,'algorithm':'RS256'}
            pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
            c.execute('INSERT INTO vault_keys VALUES(?,?,?,?,?,?,?,?)',(identifier,app,ref,'RS256',self.engine.vault._wrap(row,pem),
                key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo),'ACTIVE',now.timestamp()))
            c.execute('INSERT INTO km_certificates VALUES(?,?)',(identifier,cert.public_bytes(serialization.Encoding.PEM).decode()))
            c.execute('INSERT INTO km_jose_ids VALUES(?,?)',(identifier,encode(hashlib.sha256(bytes.fromhex(identifier)).digest())))
            if old:c.execute("UPDATE vault_keys SET state='REVOKED' WHERE id=?",(old['id'],))
            c.execute('INSERT OR REPLACE INTO vault_aliases VALUES(?,?,?)',(app,ref,identifier))
            c.execute('INSERT INTO vault_audit(action,key_id,at) VALUES(?,?,?)',('temporary-key-generation',identifier,now.timestamp()))
        return app,ref,self.engine.get(app,ref)

    def temp_certificate(self):
        app,ref,value=self.temporary()
        return {'certificate':value['certificate'],'timestamp':stamp(self.engine.clock())}

    def migrate(self,request):
        items=request.get('zkEncryptedDataList',[]);purge=request.get('purgeTempKeyFlag',False)
        if not isinstance(items,list) or len(items)>1024 or not isinstance(purge,bool):raise VaultFailure('Invalid key migration batch')
        app,ref,_=self.temporary();private=self.engine.vault._private(self.engine.vault.active(app,ref));result=[]
        with self.engine.vault.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            for item in items:
                if not isinstance(item,dict):raise VaultFailure('Invalid key migration item')
                index=item.get('keyIndex')
                if not isinstance(index,int) or isinstance(index,bool) or not 0<=index<2**31:raise VaultFailure('Invalid key index')
                if c.execute("SELECT 1 FROM km_records WHERE kind='zk-key' AND scope=? AND identifier=?",(self.scope(),str(index))).fetchone():
                    message='Migration Not Allowed. Valid Key Exists.'
                else:
                    try:
                        key=private.decrypt(unbase(item.get('encryptedKeyData')),oaep())
                        if len(key)!=32:raise ValueError()
                        self.aux.put(c,'zk-key',self.scope(),str(index),{'key':encode(key),'active':True});message='Migration Success'
                    except (ValueError,VaultFailure):message='Error in Migration'
                result.append({'keyIndex':index,'statusMessage':message})
        if purge and all(v['statusMessage']!='Error in Migration' for v in result):self.engine.revoke({'applicationId':app,'referenceId':ref})
        return {'zkEncryptedDataList':result}

    def wrap(self,key):
        output=[]
        for scope in self.aux.settings['zk_recipients']:
            cert=certificate(self.engine.get(scope['application'],scope['reference'])['certificate'])
            output.append(encode(cert.fingerprint(hashes.SHA256())+cert.public_key().encrypt(key,oaep())))
        if not output:raise VaultFailure('No configured wrapping recipient')
        return '.'.join(output)

    def attributes(self,request,*,decrypt=False):
        identifier=text(request.get('id'),maximum=4096);items=request.get('zkDataAttributes')
        if not isinstance(items,list) or not 1<=len(items)<=1024:raise VaultFailure('A bounded attribute list is required')
        output=[];chosen=None
        with self.engine.vault.connect() as c:
            if not decrypt:
                rows=c.execute("SELECT * FROM km_records WHERE kind='zk-key' AND scope=?",(self.scope(),)).fetchall()
                rows=[r for r in rows if self.aux.open(r)['active']]
                if not rows:raise VaultFailure('No active data-encryption key is configured')
                row=secrets.choice(rows);chosen=int(row['identifier']);key=unbase(self.aux.open(row)['key']);derivative=derived(identifier,key)
            for item in items:
                if not isinstance(item,dict):raise VaultFailure('Invalid attribute')
                name=text(item.get('identifier'),maximum=256)
                if decrypt:
                    raw=unbase(item.get('value'))
                    if len(raw)<64:raise VaultFailure('Truncated attribute ciphertext')
                    index=struct.unpack('>i',raw[:4])[0]
                    record=self.aux.load(c,'zk-key',self.scope(),str(index))
                    if not record['active']:raise VaultFailure('Attribute encryption key is not active')
                    try:value=AESGCM(derived(identifier,unbase(record['key']))).decrypt(raw[4:16],raw[48:],raw[16:48]).decode()
                    except (InvalidTag,ValueError):raise VaultFailure('Attribute authentication failed')
                else:
                    plain=text(item.get('value')).encode();iv=secrets.token_bytes(12);aad=secrets.token_bytes(32)
                    value=encode(struct.pack('>i',chosen)+iv+aad+AESGCM(derivative).encrypt(iv,plain,aad))
                output.append({'identifier':name,'value':value})
        result={'zkDataAttributes':output}
        if not decrypt:result.update(rankomKeyIndex=str(chosen),encryptedRandomKey=self.wrap(key))
        return result

    def rewrap(self,request):
        raw=unbase(request.get('encryptedKey'))
        if len(raw)<32+256:raise VaultFailure('Invalid wrapped random key')
        fingerprint=raw[:32]
        with self.engine.vault.connect() as c:
            rows=c.execute('''SELECT k.*,t.certificate FROM vault_keys k JOIN km_certificates t ON k.id=t.key_id
WHERE k.private_blob IS NOT NULL AND k.state IN ('ACTIVE','VERIFY_ONLY')''').fetchall()
        scopes={(v['application'],v['reference']) for v in self.aux.settings['zk_recipients']}
        matches=[dict(r) for r in rows if (r['application'],r['reference']) in scopes and certificate(r['certificate']).fingerprint(hashes.SHA256())==fingerprint]
        if len(matches)!=1:raise VaultFailure('Wrapping key is not registered for this operation')
        row=matches[0];row['state']='ACTIVE'
        try:key=self.engine.vault._private(row).decrypt(raw[32:],oaep())
        except ValueError:raise VaultFailure('Random key unwrap failed')
        if len(key)!=32:raise VaultFailure('Invalid random key length')
        return {'encryptedKey':self.wrap(key)}
