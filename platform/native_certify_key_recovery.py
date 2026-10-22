"""Authenticated, data-only export to the retained generic JCA keystore reader.

Export a stopped or SQLite-backup snapshot. Never writes plaintext private-key
material. The coordinator must separately project SQL alias/certificate/trust
metadata; a PKCS#12 export alone is not complete state recovery.
"""
import io
import json
import os
import re
import secrets
import struct
import datetime
import hashlib
from pathlib import Path
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from native_key_vault import NativeKeyVault, canonical


def project_retained_metadata(engine, connection, *, quiescent, recovered_private=None):
    """Project certificates/validity for retained aliases in one SQL transaction.

    Call only while both engines and their schedulers are fenced. Unknown key
    generations deliberately block. CA import is separately completed through
    the retained trust manager after its domain configuration is restored.
    """
    from native_keymanager_aux import Auxiliary
    if not callable(quiescent) or quiescent() is not True:
        raise ValueError('Observed key/worker quiescence required')
    auxiliary=Auxiliary(engine,{})
    with engine.vault.connect() as native:
        native.execute('BEGIN')
        source_aliases={row['identifier']:auxiliary.open(row) for row in native.execute("SELECT * FROM km_records WHERE kind='source-alias'")}
        keys={row['id']:dict(row) for row in native.execute('SELECT k.*,c.certificate,v.not_before,v.not_after FROM vault_keys k JOIN km_certificates c ON c.key_id=k.id LEFT JOIN km_effective_validity v ON v.key_id=k.id')}
        symmetric={row['identifier'] for row in native.execute("SELECT identifier FROM km_records WHERE kind='source-symmetric'")}
        all_native_keys={row[0] for row in native.execute('SELECT id FROM vault_keys')}
        new_aliases=set(keys)-set(source_aliases)
        new_private={kid for kid in new_aliases if keys[kid]['private_blob'] is not None}
        new_public=new_aliases-new_private
        if all_native_keys!=set(keys) or not set(source_aliases)<=set(keys)|symmetric or any(keys[kid]['state']!='VERIFY_ONLY' for kid in new_public):
            raise ValueError('Unsupported key inventory')
        reference_wrappers={}
        if new_private:
            from native_certify_recovered_key_proof import RecoveredKeyProof
            if not isinstance(recovered_private,RecoveredKeyProof):
                raise ValueError('Recovered private-key possession proof required')
            for kid in new_private:
                # Master signing generations use the retained keystore path.
                # Reference-specific database wrapping needs a separate adapter.
                if keys[kid]['algorithm']!='RS256':
                    raise ValueError('Non-RSA private generation requires its storage adapter')
                recovered_private.require(kid,keys[kid]['certificate'])
                if keys[kid]['reference']:
                    from native_certify_reference_recovery import ReferenceRecoveredKeyProof
                    if not isinstance(recovered_private,ReferenceRecoveredKeyProof):
                        raise ValueError('Original reference-key unwrap proof required')
                    wrapper=recovered_private.reference_wrapper(kid,keys[kid]['certificate'])
                    master=keys.get(wrapper['master'])
                    if not master or master['reference'] or master['application']!=keys[kid]['application']:
                        raise ValueError('Reference wrapping master scope differs')
                    reference_wrappers[kid]=wrapper
        trust_rows=[dict(row) for row in native.execute('SELECT domain,fingerprint,certificate FROM km_trust')]
        disabled={(row[0],row[1]) for row in native.execute('SELECT application,reference FROM km_disabled')}
        active_aliases={(row[0],row[1]):row[2] for row in native.execute('SELECT application,reference,key_id FROM vault_aliases')}
    changed=0
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout='5s'")
        cursor.execute('LOCK TABLE certify.key_alias,certify.key_store,certify.ca_cert_store IN ACCESS EXCLUSIVE MODE')
        cursor.execute('SELECT partner_domain,cert_data FROM certify.ca_cert_store WHERE is_deleted=false')
        retained_trust={(domain,x509.load_pem_x509_certificate(pem.encode()).fingerprint(hashes.SHA256()).hex()) for domain,pem in cursor.fetchall()}
        trust_count=0
        for row in trust_rows:
            fingerprint=x509.load_pem_x509_certificate(row['certificate'].encode()).fingerprint(hashes.SHA256()).hex()
            if fingerprint!=row['fingerprint']:raise ValueError('Native trust fingerprint differs')
            if (row['domain'],fingerprint) not in retained_trust:trust_count+=1
        cursor.execute('SELECT row_to_json(t) FROM certify.key_alias t')
        destination={row[0]['id']:row[0] for row in cursor.fetchall()}
        if not set(source_aliases)<=set(destination) or set(destination)-set(source_aliases)-new_aliases:
            raise ValueError('Retained SQL alias inventory differs')
        for kid,source in source_aliases.items():
            if (destination[kid]['app_id'],destination[kid]['ref_id'] or '')!=(source['app_id'],source['ref_id'] or ''):
                raise ValueError('Retained SQL key scope differs')
        if quiescent() is not True:raise ValueError('Key/worker fence changed before projection')
        for kid,row in sorted(keys.items(),key=lambda item:(bool(item[1]['reference']),item[0])):
            cert=x509.load_pem_x509_certificate(row['certificate'].encode())
            if kid in destination and (destination[kid]['app_id'],destination[kid]['ref_id'] or '')!=(row['application'],row['reference']):
                raise ValueError('Existing native alias scope differs')
            if kid not in destination:
                from psycopg2.extras import Json
                template=next((dict(value) for value in source_aliases.values() if value['app_id']==row['application']),None)
                if template is None:raise ValueError('Public alias application has no retained policy')
                expected_jose=__import__('base64').urlsafe_b64encode(hashlib.sha256(bytes.fromhex(kid.replace('-',''))).digest()).decode().rstrip('=')
                if engine.jose_id(row)!=expected_jose:raise ValueError('Public alias JOSE identity cannot be preserved')
                template.update(id=kid,ref_id=row['reference'],uni_ident=kid.replace('-',''),cert_thumbprint=cert.fingerprint(hashes.SHA256()).hex().upper(),
                    key_gen_dtimes=cert.not_valid_before_utc.isoformat(),key_expire_dtimes=cert.not_valid_after_utc.isoformat(),
                    cr_by='native-recovery',cr_dtimes=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    upd_by=None,upd_dtimes=None,is_deleted=False,del_dtimes=None)
                cursor.execute('INSERT INTO certify.key_alias SELECT * FROM json_populate_record(NULL::certify.key_alias,%s::json)',(Json(template),))
                destination[kid]=template
            thumbprint=cert.fingerprint(hashes.SHA256()).hex().upper()
            old_thumbprint=destination[kid].get('cert_thumbprint') or ''
            if old_thumbprint and old_thumbprint!=old_thumbprint.upper():thumbprint=thumbprint.lower()
            start=(datetime.datetime.fromtimestamp(row['not_before'],datetime.timezone.utc) if row['not_before'] is not None else cert.not_valid_before_utc).replace(tzinfo=None)
            end=(datetime.datetime.fromtimestamp(row['not_after'],datetime.timezone.utc) if row['not_after'] is not None else cert.not_valid_after_utc).replace(tzinfo=None)
            active_id=active_aliases.get((row['application'],row['reference']))
            rotated_scope=any(keys[new]['application']==row['application'] and keys[new]['reference']==row['reference'] for new in new_private)
            if (kid in new_public or rotated_scope) and active_id and active_id!=kid:
                # Retain public-certificate history without reactivating an old
                # reference and making the legacy lookup ambiguous.
                end=min(end,datetime.datetime.fromtimestamp(keys[active_id]['created'],datetime.timezone.utc).replace(tzinfo=None))
            is_deleted=(row['application'],row['reference']) in disabled
            cursor.execute('UPDATE certify.key_alias SET cert_thumbprint=%s,key_gen_dtimes=%s,key_expire_dtimes=%s,is_deleted=%s WHERE id=%s',
                (thumbprint,start,end,is_deleted,kid))
            cursor.execute('UPDATE certify.key_store SET certificate_data=%s WHERE id=%s',(row['certificate'],kid))
            if kid in reference_wrappers:
                wrapper=reference_wrappers[kid]
                cursor.execute('''INSERT INTO certify.key_store
                    (id,master_key,private_key,certificate_data,cr_by,cr_dtimes,is_deleted)
                    VALUES(%s,%s,%s,%s,'native-recovery',CURRENT_TIMESTAMP,false)
                    ON CONFLICT(id) DO UPDATE SET master_key=EXCLUDED.master_key,
                        private_key=EXCLUDED.private_key,certificate_data=EXCLUDED.certificate_data''',
                    (kid,wrapper['master'],wrapper['private_key'],row['certificate']))
            if kid in new_public:
                cursor.execute('SELECT master_key,private_key FROM certify.key_store WHERE id=%s',(kid,))
                stored=cursor.fetchone()
                if stored is not None and stored!=(kid,'NA'):
                    raise ValueError('Verification alias cannot overwrite retained private-key storage')
                cursor.execute('''INSERT INTO certify.key_store
                    (id,master_key,private_key,certificate_data,cr_by,cr_dtimes,is_deleted)
                    VALUES(%s,%s,'NA',%s,'native-recovery',CURRENT_TIMESTAMP,false)
                    ON CONFLICT(id) DO UPDATE SET certificate_data=EXCLUDED.certificate_data''',
                    (kid,kid,row['certificate']))
            changed+=1
        # Verify current material in SQL before the caller commits its transaction.
        cursor.execute('SELECT id,cert_thumbprint FROM certify.key_alias')
        actual=dict(cursor.fetchall())
        for kid,row in keys.items():
            cert=x509.load_pem_x509_certificate(row['certificate'].encode())
            assert actual[kid].lower()==hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
        if quiescent() is not True:raise ValueError('Key/worker fence changed before commit')
        for kid in new_private:
            recovered_private.require(kid,keys[kid]['certificate'])
            if kid in reference_wrappers:recovered_private.reference_wrapper(kid,keys[kid]['certificate'])
    return {'asymmetric_aliases_projected':changed,'symmetric_aliases_preserved':len(symmetric),
            'new_public_aliases_projected':len(new_public),'encrypted_database_private_key_records_preserved':True,
            'new_private_aliases_projected':len(new_private),
            'new_wrapped_reference_aliases_projected':len(reference_wrappers),
            'ca_trust_entries_pending_retained_import':trust_count}


def export_material(engine, directory):
    directory = Path(directory).resolve(strict=True)
    if not directory.is_relative_to(Path('/opt/karnatakadbt/private/mosip-migration/remaining-three')):
        raise ValueError('Private migration directory required')
    if directory.stat().st_uid != 0 or directory.stat().st_mode & 0o077:
        raise ValueError('Private root-owned migration directory required')
    if any((directory/name).exists() for name in ['material.bin','transfer.key']):
        raise ValueError('Retain existing recovery material')
    entries, names = [], set()
    with engine.vault.connect() as connection:
        connection.execute('BEGIN')
        rows = connection.execute('SELECT k.*,c.certificate FROM vault_keys k LEFT JOIN km_certificates c ON c.key_id=k.id ORDER BY k.id').fetchall()
        certificates = {row['id']:x509.load_pem_x509_certificate(row['certificate'].encode()) for row in rows if row['certificate']}
        for row in rows:
            if not row['certificate']:
                raise ValueError('Certificate missing from native asymmetric key')
            cert = certificates[row['id']]
            chain, visited = [cert], {row['id']}
            while chain[-1].issuer != chain[-1].subject:
                parents = [(kid,parent) for kid,parent in certificates.items() if parent.subject == chain[-1].issuer and kid not in visited]
                verified = []
                for kid,parent in parents:
                    try:chain[-1].verify_directly_issued_by(parent)
                    except (ValueError,TypeError,InvalidSignature):continue
                    verified.append((kid,parent))
                if len(verified) != 1:
                    raise ValueError('Unresolved or ambiguous native certificate chain')
                kid,parent = verified[0];visited.add(kid);chain.append(parent)
                if len(chain)>32:raise ValueError('Native certificate chain exceeds bound')
            material = b''
            if row['private_blob'] is not None:
                blob = bytes(row['private_blob'])
                private = serialization.load_pem_private_key(engine.vault.aead.decrypt(blob[:12],blob[12:],NativeKeyVault.aad(row)),None)
                if private.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo) != cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo):
                    raise ValueError('Scoped private key and certificate differ')
                algorithm = 'RSA' if isinstance(private,rsa.RSAPrivateKey) else 'EC' if isinstance(private,ec.EllipticCurvePrivateKey) else 'Ed25519' if isinstance(private,ed25519.Ed25519PrivateKey) else None
                if algorithm is None:raise ValueError('Unsupported private key recovery algorithm')
                material = private.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
                kind = 1
            else:
                algorithm,kind,chain = 'PUBLIC',3,[cert]
            entries.append((row['id'],algorithm,kind,material,[c.public_bytes(serialization.Encoding.DER) for c in chain]))
        for row in connection.execute("SELECT * FROM km_records WHERE kind='source-symmetric' ORDER BY identifier"):
            blob = bytes(row['content'])
            value = json.loads(engine.vault.aead.decrypt(blob[:12],blob[12:],canonical([row['kind'],row['scope'],row['identifier']])))
            import base64
            material = base64.urlsafe_b64decode(value['key'] + '=' * (-len(value['key']) % 4))
            if len(material) not in [16,24,32]:raise ValueError('Invalid recovered AES key length')
            entries.append((row['identifier'],'AES',2,material,[]))
    stream = io.BytesIO()
    def text(value):
        encoded=value.encode('ascii');stream.write(struct.pack('>H',len(encoded))+encoded)
    def binary(value):stream.write(struct.pack('>i',len(value))+value)
    text('KDBT-CERTIFY-KEYS-V1');stream.write(struct.pack('>i',len(entries)))
    if not 1<=len(entries)<=10000:raise ValueError('Recovery alias count exceeds bound')
    for alias,algorithm,kind,material,chain in entries:
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}',alias) or alias.lower() in names:
            raise ValueError('Recovery alias collision')
        names.add(alias.lower());text(alias);text(algorithm);stream.write(struct.pack('>i',kind));binary(material)
        stream.write(struct.pack('>i',len(chain)))
        for cert in chain:binary(cert)
    if stream.tell()>31*1024*1024:raise ValueError('Recovery material exceeds bound')
    key,nonce=secrets.token_bytes(32),secrets.token_bytes(12)
    sealed=nonce+AESGCM(key).encrypt(nonce,stream.getvalue(),b'kdbt-certify-pkcs12-recovery-v1')
    for name,value in [('transfer.key',key),('material.bin',sealed)]:
        descriptor=os.open(directory/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'wb') as output:output.write(value);output.flush();os.fsync(output.fileno())
    return {'aliases':len(entries),'private_keys':sum(e[2]==1 for e in entries),'symmetric_keys':sum(e[2]==2 for e in entries)}
