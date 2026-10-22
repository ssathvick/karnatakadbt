"""Legacy-compatible binary envelopes implemented with standard primitives."""
import base64,hashlib,secrets,struct
from cryptography import x509
from cryptography.exceptions import InvalidTag,InvalidSignature
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding,rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from native_keymanager import certificate,VaultFailure
from native_keymanager_aux import text,when
from native_keymanager_jose import unbase
from native_key_vault import encode

def oaep(*,android=False,label=None):
    return padding.OAEP(mgf=padding.MGF1(hashes.SHA1() if android else hashes.SHA256()),algorithm=hashes.SHA256(),label=label)


def tpm_public(raw):
    """Decode bounded RSA TPMT_PUBLIC, without claiming a physical TPM."""
    offset=0
    def number(size):
        nonlocal offset
        if offset+size>len(raw):raise VaultFailure('Truncated TPM public area')
        value=int.from_bytes(raw[offset:offset+size],'big');offset+=size;return value
    def blob():
        nonlocal offset
        size=number(2)
        if size>4096 or offset+size>len(raw):raise VaultFailure('Invalid TPM public area')
        value=raw[offset:offset+size];offset+=size;return value
    if not isinstance(raw,bytes) or len(raw)>8192 or number(2)!=1:raise VaultFailure('RSA TPM public area required')
    name_alg=number(2)
    if name_alg not in {0x000b,0x0004}:raise VaultFailure('Unsupported TPM name algorithm')
    number(4);blob()
    symmetric=number(2)
    if symmetric!=0x0010:number(2);number(2)
    scheme=number(2)
    if scheme!=0x0010:number(2)
    bits=number(2);exponent=number(4) or 65537;modulus=blob()
    if offset!=len(raw) or bits<2048 or bits>8192 or len(modulus)*8!=bits:raise VaultFailure('Invalid TPM RSA modulus')
    return rsa.RSAPublicNumbers(exponent,int.from_bytes(modulus,'big')).public_key(),name_alg


def client_public(request):
    raw=unbase(request.get('publicKey'))
    client=request.get('clientType','LOCAL') or 'LOCAL'
    if client not in {'LOCAL','ANDROID','TPM'}:raise VaultFailure('Unknown client type')
    if raw.startswith(b'\x00\x01'):
        key,name_alg=tpm_public(raw);return key,'TPM',name_alg
    if client=='TPM':raise VaultFailure('TPM public area required')
    try:key=serialization.load_der_public_key(raw)
    except ValueError:raise VaultFailure('Invalid client public key')
    if not isinstance(key,rsa.RSAPublicKey) or not 2048<=key.key_size<=8192:raise VaultFailure('Bounded RSA client key required')
    return key,client,None


def client_key(aux):
    if aux.settings.get('client_key_scope'):
        scope=aux.settings['client_key_scope'];aux.engine.get(scope['application'],scope['reference'])
        return aux.engine.vault._private(aux.engine.vault.active(scope['application'],scope['reference']))
    with aux.engine.vault.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT * FROM km_records WHERE kind='client-key' AND scope='server' AND identifier='rsa'").fetchone()
        if row:private=unbase(aux.open(row)['private'])
        else:
            key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            private=key.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
            aux.put(c,'client-key','server','rsa',{'private':encode(private),'provider':'LOCAL'})
    return serialization.load_der_private_key(private,password=None)


def client_operation(aux, operation, request):
    if operation in {'getSigningPublicKey','getEncPublicKey'}:
        text(request.get('serverProfile'),maximum=128)
        key=client_key(aux)
        return {'publicKey':encode(key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo))}
    if operation=='signData':
        return {'data':encode(client_key(aux).sign(unbase(request.get('data')),padding.PKCS1v15(),hashes.SHA256()))}
    if operation=='verifySignature':
        key,client,name_alg=client_public(request)
        valid=False
        try:key.verify(unbase(request.get('signature')),unbase(request.get('data')),padding.PKCS1v15(),hashes.SHA256());valid=True
        except InvalidSignature:pass
        return {'verified':valid}
    if operation=='tpmEncrypt':
        key,client,name_alg=client_public(request);data=unbase(request.get('value'));cek=secrets.token_bytes(32);iv=secrets.token_bytes(12);aad=secrets.token_bytes(32)
        if client=='TPM':
            digest=hashes.SHA256() if name_alg==0x000b else hashes.SHA1()
            pad=padding.OAEP(mgf=padding.MGF1(digest),algorithm=digest,label=b'\0')
        else:pad=oaep(android=client=='ANDROID')
        return {'value':encode(key.encrypt(cek,pad)+iv+aad+AESGCM(cek).encrypt(iv,data,aad))}
    if operation=='tpmDecrypt':
        key=client_key(aux);raw=unbase(request.get('value'));size=key.key_size//8
        if len(raw)<size+60:raise VaultFailure('Invalid client ciphertext')
        try:
            cek=key.decrypt(raw[:size],oaep());iv=raw[size:size+12];aad=raw[size+12:size+44]
            return {'value':encode(AESGCM(cek).decrypt(iv,raw[size+44:],aad))}
        except (ValueError,InvalidTag):raise VaultFailure('Client ciphertext authentication failed')
    raise VaultFailure('Unknown client operation')


def hybrid(aux,request,*,decrypt=False):
    engine=aux.engine;app,ref=request.get('applicationId'),request.get('referenceId') or ''
    engine.policy(app,ref);when(request.get('timeStamp'))
    splitter=aux.settings['data_key_splitter'].encode()
    if not splitter or len(splitter)>128:raise VaultFailure('Invalid configured key delimiter')
    salt=unbase(request['salt']) if request.get('salt') else None
    aad=unbase(request['aad']) if request.get('aad') else None
    if salt is not None and not 8<=len(salt)<=128:raise VaultFailure('Invalid GCM nonce')
    if not decrypt:
        cert=certificate(engine.get(app,ref)['certificate']);key=cert.public_key();plain=unbase(request.get('data'));cek=secrets.token_bytes(32)
        header=b''
        if salt is not None:data=AESGCM(cek).encrypt(salt,plain,aad)
        elif not aad:
            aad=secrets.token_bytes(32);data=aad+AESGCM(cek).encrypt(aad[:12],plain,aad);header=b'VER_R2'
        else:
            iv=secrets.token_bytes(16);data=AESGCM(cek).encrypt(iv,plain,aad)+iv
        return {'data':encode(header+cert.fingerprint(hashes.SHA256())+key.encrypt(cek,oaep())+splitter+data)}
    raw=unbase(request.get('data'));version=raw.startswith(b'VER_R2');offset=6 if version else 0
    if len(raw)<offset+32+256+len(splitter)+16:raise VaultFailure('Truncated hybrid ciphertext')
    fingerprint=raw[offset:offset+32]
    with engine.vault.connect() as c:
        rows=c.execute('''SELECT k.*,t.certificate FROM vault_keys k JOIN km_certificates t ON k.id=t.key_id
WHERE k.application=? AND k.reference=? AND k.state IN ('ACTIVE','VERIFY_ONLY') AND k.private_blob IS NOT NULL''',(app,ref)).fetchall()
    matches=[dict(r) for r in rows if certificate(r['certificate']).fingerprint(hashes.SHA256())==fingerprint]
    if len(matches)!=1:raise VaultFailure('Ciphertext key is outside this scope')
    row=matches[0];row['state']='ACTIVE';key=engine.vault._private(row);start=offset+32;end=start+key.key_size//8
    if raw[end:end+len(splitter)]!=splitter:raise VaultFailure('Invalid hybrid ciphertext delimiter')
    data=raw[end+len(splitter):]
    try:
        cek=key.decrypt(raw[start:end],oaep())
        if salt is not None:plain=AESGCM(cek).decrypt(salt,data,aad)
        elif version:plain=AESGCM(cek).decrypt(data[:12],data[32:],data[:32])
        else:plain=AESGCM(cek).decrypt(data[-16:],data[:-16],aad)
        return {'data':encode(plain)}
    except (ValueError,InvalidTag):raise VaultFailure('Hybrid ciphertext authentication failed')


def token_id(aux, request):
    uin=text(request.get('uin'),maximum=256);partner=text(request.get('partnercode'),maximum=256)
    config=aux.settings['token_id']
    first=hashlib.sha256((uin+config['uin_salt']).encode()).hexdigest().upper()
    second=hashlib.sha256((config['partner_salt']+partner+first).encode()).hexdigest().upper()
    value=str(int.from_bytes(second.encode(),'big',signed=True))
    length=config['length']
    if not isinstance(length,int) or not 1<=length<=100 or length>len(value):raise VaultFailure('Invalid token length policy')
    return {'tokenID':value[:length]}
