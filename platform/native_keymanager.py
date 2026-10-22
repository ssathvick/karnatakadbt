"""Native certificate/key lifecycle engine, independent of MOSIP libraries.

This is a candidate engine. Production compatibility, state handoff and rollback
are separate gates; serving a route does not establish migration acceptance.
"""
import datetime, hashlib, json, secrets, sqlite3, uuid
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa,ed25519
from cryptography.x509.oid import NameOID
from native_key_vault import NativeKeyVault, VaultFailure, canonical,encode

UTC = datetime.timezone.utc


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def stamp(value):
    return utc(value).isoformat().replace('+00:00', 'Z')


def certificate(value):
    if not isinstance(value, str) or len(value) > 128 * 1024:
        raise VaultFailure('A bounded PEM certificate is required')
    try:
        return x509.load_pem_x509_certificate(value.encode())
    except ValueError:
        raise VaultFailure('Invalid PEM certificate')


def public_bytes(key):
    return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


class NativeKeymanager:
    """Transactional scoped keys and certificate history with encrypted PKCS8.

    Policies are explicit application allowlists. A caller cannot create a new
    application or change its key validity by sending arbitrary API properties.
    """
    def __init__(self, path, master_key, policies, *, clock=None):
        self.vault = NativeKeyVault(path, master_key)
        self.policies = policies
        self.clock = clock or (lambda: datetime.datetime.now(UTC))
        with self.vault.connect() as c:
            c.executescript('''
CREATE TABLE IF NOT EXISTS km_certificates(key_id TEXT PRIMARY KEY, certificate TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS km_disabled(application TEXT NOT NULL, reference TEXT NOT NULL, PRIMARY KEY(application,reference));
CREATE TABLE IF NOT EXISTS km_trust(domain TEXT NOT NULL, fingerprint TEXT NOT NULL, certificate TEXT NOT NULL, PRIMARY KEY(domain,fingerprint));
CREATE TABLE IF NOT EXISTS km_jose_ids(key_id TEXT PRIMARY KEY,identifier TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS km_effective_validity(key_id TEXT PRIMARY KEY,not_before REAL NOT NULL,not_after REAL NOT NULL);
''')

    def policy(self, application, reference):
        self.vault.scope(application, reference)
        policy = self.policies.get(application)
        if not policy or policy.get('active') is not True:
            raise VaultFailure('Application policy is not active')
        days = policy.get('validity_days')
        if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 36500:
            raise VaultFailure('Invalid certificate validity policy')
        return policy

    def subject(self, request, application):
        fields = [('commonName', NameOID.COMMON_NAME), ('organizationUnit', NameOID.ORGANIZATIONAL_UNIT_NAME),
                  ('organization', NameOID.ORGANIZATION_NAME), ('location', NameOID.LOCALITY_NAME),
                  ('state', NameOID.STATE_OR_PROVINCE_NAME), ('country', NameOID.COUNTRY_NAME)]
        values = []
        for name, oid in fields:
            value = request.get(name, application if name == 'commonName' else None)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip() or len(value) > 128 or '\x00' in value:
                raise VaultFailure('Invalid certificate subject')
            if name == 'country' and (len(value) != 2 or not value.isascii() or not value.isalpha()):
                raise VaultFailure('Country must have two ASCII letters')
            values.append(x509.NameAttribute(oid, value.upper() if name == 'country' else value))
        return x509.Name(values)

    def _row(self, c, application, reference):
        row = c.execute('''SELECT k.*,t.certificate FROM vault_aliases a
JOIN vault_keys k ON a.key_id=k.id JOIN km_certificates t ON k.id=t.key_id
WHERE a.application=? AND a.reference=?''', (application, reference)).fetchone()
        if not row or row['state'] not in {'ACTIVE', 'VERIFY_ONLY'}:
            raise VaultFailure('No active certificate in this scope')
        validity=c.execute('SELECT not_before,not_after FROM km_effective_validity WHERE key_id=?',(row['id'],)).fetchone()
        if validity and not validity['not_before']<=utc(self.clock()).timestamp()<validity['not_after']:
            raise VaultFailure('Key alias is outside its effective validity period')
        return dict(row)

    def jose_id(self,row):
        with self.vault.connect() as c:
            value=c.execute('SELECT identifier FROM km_jose_ids WHERE key_id=?',(row['id'],)).fetchone()
        return value[0] if value else row['id']

    def _valid(self, cert):
        now = utc(self.clock())
        if not utc(cert.not_valid_before_utc) <= now < utc(cert.not_valid_after_utc):
            raise VaultFailure('Certificate is outside its validity period')

    def _response(self, cert, *, csr=None):
        return {'certificate': cert.public_bytes(serialization.Encoding.PEM).decode(),
                'certSignRequest': csr, 'issuedAt': stamp(cert.not_valid_before_utc),
                'expiryAt': stamp(cert.not_valid_after_utc), 'timestamp': stamp(self.clock())}

    def generate(self, request, object_type='CERTIFICATE'):
        application, reference = request.get('applicationId'), request.get('referenceId') or ''
        policy = self.policy(application, reference)
        if object_type not in {'CERTIFICATE', 'CSR'}:
            raise VaultFailure('objectType must be CERTIFICATE or CSR')
        if not isinstance(request.get('force', False), bool):
            raise VaultFailure('force must be boolean')
        subject = self.subject(request, application)
        with self.vault.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT key_id FROM vault_aliases WHERE application=? AND reference=?', (application, reference)).fetchone()
            if old and not request.get('force', False):
                row = self._row(c, application, reference)
                cert = certificate(row['certificate']); self._valid(cert)
                if object_type == 'CSR':
                    key = self.vault._private(row)
                    csr = x509.CertificateSigningRequestBuilder().subject_name(subject).sign(key, None if isinstance(key,ed25519.Ed25519PrivateKey) else hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode()
                else:
                    csr = None
                return self._response(cert, csr=csr)
            if c.execute('SELECT 1 FROM km_disabled WHERE application=? AND reference=?', (application, reference)).fetchone():
                raise VaultFailure('Automatic generation is disabled for this scope')
            key_size=policy.get('key_size',3072)
            if key_size not in {2048,3072,4096}:raise VaultFailure('Unsupported RSA key-size policy')
            key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
            now = utc(self.clock()).replace(microsecond=0)
            end = now + datetime.timedelta(days=policy['validity_days'])
            issuer_application=application if reference else policy.get('issuer_application')
            if issuer_application:
                issuer_row = self._row(c, issuer_application, '')
                issuer = certificate(issuer_row['certificate']); self._valid(issuer)
                if not issuer.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
                    raise VaultFailure('Application master certificate is not a CA')
                issuer_name = issuer.subject
                issuer_key = self.vault._private(issuer_row)
                end = min(end, utc(issuer.not_valid_after_utc))
            else:
                issuer_name, issuer_key = subject, key
            cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer_name)
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now - datetime.timedelta(seconds=30)).not_valid_after(end)
                    .add_extension(x509.BasicConstraints(ca=not bool(reference), path_length=policy.get('ca_path_length',0) if not reference else None), critical=True)
                    .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                        key_encipherment=bool(reference), data_encipherment=False, key_agreement=False,
                        key_cert_sign=not bool(reference), crl_sign=not bool(reference),
                        encipher_only=False, decipher_only=False), critical=True)
                    .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
                    .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False)
                    .sign(issuer_key, hashes.SHA256()))
            row = {'id': uuid.uuid4().hex, 'application': application, 'reference': reference, 'algorithm': 'RS256'}
            pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
            c.execute('INSERT INTO vault_keys VALUES(?,?,?,?,?,?,?,?)', (row['id'], application, reference, 'RS256',
                self.vault._wrap(row, pem), key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo), 'ACTIVE', now.timestamp()))
            c.execute('INSERT INTO km_certificates VALUES(?,?)', (row['id'], cert.public_bytes(serialization.Encoding.PEM).decode()))
            c.execute('INSERT INTO km_jose_ids VALUES(?,?)',(row['id'],encode(hashlib.sha256(bytes.fromhex(row['id'])).digest())))
            if old:
                c.execute("UPDATE vault_keys SET state='VERIFY_ONLY' WHERE id=?", (old['key_id'],))
            c.execute('INSERT OR REPLACE INTO vault_aliases VALUES(?,?,?)', (application, reference, row['id']))
            c.execute('INSERT INTO vault_audit(action,key_id,at) VALUES(?,?,?)', ('certificate-generation', row['id'], now.timestamp()))
            csr = x509.CertificateSigningRequestBuilder().subject_name(subject).sign(key, None if isinstance(key,ed25519.Ed25519PrivateKey) else hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode() if object_type == 'CSR' else None
            return self._response(cert, csr=csr)

    def get(self, application, reference=''):
        self.policy(application, reference)
        with self.vault.connect() as c:
            cert = certificate(self._row(c, application, reference)['certificate']); self._valid(cert)
            return self._response(cert)

    def all(self, application, reference=''):
        self.policy(application, reference)
        with self.vault.connect() as c:
            rows = c.execute('''SELECT k.id,t.certificate FROM vault_keys k JOIN km_certificates t ON k.id=t.key_id
WHERE k.application=? AND k.reference=? ORDER BY k.created,k.id''', (application, reference)).fetchall()
        result = []
        for row in rows:
            cert = certificate(row['certificate'])
            result.append({'keyId': row['id'], 'certificateData': row['certificate'],
                           'issuedAt': stamp(cert.not_valid_before_utc), 'expiryAt': stamp(cert.not_valid_after_utc)})
        return {'allCertificates': result}

    def csr(self, request):
        application, reference = request.get('applicationId'), request.get('referenceId') or ''
        self.policy(application, reference); subject = self.subject(request, application)
        with self.vault.connect() as c:
            row = self._row(c, application, reference); cert = certificate(row['certificate']); self._valid(cert)
            key = self.vault._private(row)
            csr = x509.CertificateSigningRequestBuilder().subject_name(subject).sign(key, None if isinstance(key,ed25519.Ed25519PrivateKey) else hashes.SHA256())
            return self._response(cert, csr=csr.public_bytes(serialization.Encoding.PEM).decode())

    def revoke(self, request):
        application, reference = request.get('applicationId'), request.get('referenceId') or ''
        self.policy(application, reference)
        if not isinstance(request.get('disableAutoGen', False), bool):
            raise VaultFailure('disableAutoGen must be boolean')
        with self.vault.connect() as c:
            c.execute('BEGIN IMMEDIATE'); row = self._row(c, application, reference)
            c.execute("UPDATE vault_keys SET state='REVOKED' WHERE id=?", (row['id'],))
            c.execute('DELETE FROM vault_aliases WHERE application=? AND reference=?', (application, reference))
            if request.get('disableAutoGen'):
                c.execute('INSERT OR IGNORE INTO km_disabled VALUES(?,?)', (application, reference))
            c.execute('INSERT INTO vault_audit(action,key_id,at) VALUES(?,?,?)', ('certificate-revocation', row['id'], utc(self.clock()).timestamp()))
        return {'status': 'SUCCESS', 'timestamp': stamp(self.clock())}

    def upload(self, request, *, verification_only=False):
        application, reference = request.get('applicationId'), request.get('referenceId') or ''
        self.policy(application, reference); cert = certificate(request.get('certificateData')); self._valid(cert)
        with self.vault.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if verification_only:
                # Register immutable verification material; never replace a private alias.
                existing = c.execute('''SELECT k.* FROM vault_aliases a JOIN vault_keys k ON a.key_id=k.id
WHERE a.application=? AND a.reference=?''', (application, reference)).fetchone()
                if existing:
                    if existing['private_blob'] is not None:
                        raise VaultFailure('A private alias cannot be overwritten with public material')
                    old_cert=certificate(c.execute('SELECT certificate FROM km_certificates WHERE key_id=?',(existing['id'],)).fetchone()[0])
                    if old_cert.fingerprint(hashes.SHA256())==cert.fingerprint(hashes.SHA256()):
                        return {'status':'SUCCESS','timestamp':stamp(self.clock())}
                kid = uuid.uuid4().hex
                if not isinstance(cert.public_key(), rsa.RSAPublicKey) or cert.public_key().key_size < 2048:
                    raise VaultFailure('An RSA certificate of at least 2048 bits is required')
                c.execute('INSERT INTO vault_keys VALUES(?,?,?,?,?,?,?,?)', (kid, application, reference, 'RS256', None,
                    cert.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo), 'VERIFY_ONLY', utc(self.clock()).timestamp()))
                c.execute('INSERT INTO km_certificates VALUES(?,?)', (kid, request['certificateData']))
                c.execute('INSERT INTO km_jose_ids VALUES(?,?)',(kid,encode(hashlib.sha256(bytes.fromhex(kid)).digest())))
                c.execute('INSERT OR REPLACE INTO vault_aliases VALUES(?,?,?)', (application, reference, kid))
            else:
                row = self._row(c, application, reference); kid = row['id']
                if public_bytes(cert.public_key()) != public_bytes(serialization.load_pem_public_key(row['public_pem'])):
                    raise VaultFailure('Certificate does not match the scoped private key')
                policy=self.policy(application,reference)
                if reference:
                    issuer_app=policy.get('reference_issuer_application',application)
                    issuer = certificate(self._row(c, issuer_app, '')['certificate'])
                    self._ca(issuer)
                elif policy.get('issuer_application') and policy['issuer_application']!=application:
                    issuer=certificate(self._row(c,policy['issuer_application'],'')['certificate']);self._ca(issuer)
                else:
                    issuer = cert
                    self._ca(issuer)
                try:
                    if reference and cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca and not policy.get('allow_reference_ca',False):
                        raise VaultFailure('A reference certificate cannot become a CA')
                except x509.ExtensionNotFound:
                    pass
                self._valid(issuer)
                try:
                    cert.verify_directly_issued_by(issuer)
                except (ValueError, TypeError, InvalidSignature):
                    raise VaultFailure('Certificate issuer or signature is invalid')
                c.execute('UPDATE km_certificates SET certificate=? WHERE key_id=?', (request['certificateData'], kid))
            c.execute('INSERT INTO vault_audit(action,key_id,at) VALUES(?,?,?)', ('public-certificate-upload' if verification_only else 'certificate-upload', kid, utc(self.clock()).timestamp()))
        return {'status': 'SUCCESS', 'timestamp': stamp(self.clock())}

    def _domain(self, domain):
        if not isinstance(domain, str) or not domain or len(domain) > 128 or any(ord(v) < 33 for v in domain):
            raise VaultFailure('Invalid partner domain')
        return domain

    def _ca(self, cert):
        self._valid(cert)
        try:
            if not cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
                raise VaultFailure('A CA certificate is required')
            try:
                if not cert.extensions.get_extension_for_class(x509.KeyUsage).value.key_cert_sign:
                    raise VaultFailure('CA certificate cannot sign certificates')
            except x509.ExtensionNotFound:
                pass
        except x509.ExtensionNotFound:
            raise VaultFailure('CA basic constraints are required')

    def _chain(self, leaf, certificates):
        known_critical = {x509.ExtensionOID.BASIC_CONSTRAINTS, x509.ExtensionOID.KEY_USAGE,
            x509.ExtensionOID.SUBJECT_ALTERNATIVE_NAME, x509.ExtensionOID.EXTENDED_KEY_USAGE,
            x509.ExtensionOID.CERTIFICATE_POLICIES, x509.ExtensionOID.NAME_CONSTRAINTS}
        # Name constraints require a dedicated policy verifier. Refuse rather
        # than silently accepting a critical constraint we do not enforce.
        known_critical.discard(x509.ExtensionOID.NAME_CONSTRAINTS)
        def follow(current, visited, ca_below):
            self._valid(current)
            if any(e.critical and e.oid not in known_critical for e in current.extensions):
                return False
            fingerprint = current.fingerprint(hashes.SHA256()).hex()
            if fingerprint in visited or len(visited) > 10:
                return False
            if current.issuer == current.subject:
                if any(c.fingerprint(hashes.SHA256()) == current.fingerprint(hashes.SHA256()) for c in certificates):
                    try:
                        self._ca(current); current.verify_directly_issued_by(current)
                        return True
                    except (VaultFailure, InvalidSignature, ValueError, TypeError):
                        pass
                # Equal distinguished names do not establish self-signing:
                # an issuer and its leaf can have the same subject name.
            try:
                is_ca = current.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
            except x509.ExtensionNotFound:
                is_ca = False
            below = ca_below + int(is_ca and current.issuer != current.subject)
            for parent in certificates:
                if parent.subject != current.issuer:
                    continue
                try:
                    self._ca(parent)
                    path_length = parent.extensions.get_extension_for_class(x509.BasicConstraints).value.path_length
                    if path_length is not None and below > path_length:
                        continue
                    current.verify_directly_issued_by(parent)
                    if follow(parent, visited | {fingerprint}, below):
                        return True
                except (VaultFailure, InvalidSignature, ValueError, TypeError):
                    continue
            return False
        return follow(leaf, set(), 0)

    def upload_ca(self, request):
        domain = self._domain(request.get('partnerDomain'))
        data = request.get('certificateData')
        if not isinstance(data, str) or len(data) > 128 * 1024:
            raise VaultFailure('Bounded PEM CA certificates required')
        try:
            incoming = x509.load_pem_x509_certificates(data.encode())
        except ValueError:
            raise VaultFailure('Invalid CA certificates')
        if not incoming or len(incoming) > 10:
            raise VaultFailure('Between one and ten CA certificates required')
        with self.vault.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            retained = [certificate(r[0]) for r in c.execute('SELECT certificate FROM km_trust WHERE domain=?', (domain,))]
            for cert in incoming:
                self._ca(cert)
                if not self._chain(cert, retained + incoming):
                    raise VaultFailure('CA chain is invalid or has an unsupported critical constraint')
            for cert in incoming:
                c.execute('INSERT OR IGNORE INTO km_trust VALUES(?,?,?)', (domain, cert.fingerprint(hashes.SHA256()).hex(), cert.public_bytes(serialization.Encoding.PEM).decode()))
            c.execute('INSERT INTO vault_audit(action,key_id,at) VALUES(?,?,?)', ('ca-upload', None, utc(self.clock()).timestamp()))
        return {'status': 'SUCCESS', 'timestamp': stamp(self.clock())}

    def trust(self, request):
        domain = self._domain(request.get('partnerDomain'))
        leaf = certificate(request.get('certificateData'))
        with self.vault.connect() as c:
            anchors = [certificate(r[0]) for r in c.execute('SELECT certificate FROM km_trust WHERE domain=?', (domain,))]
        try:
            valid = self._chain(leaf, anchors)
        except VaultFailure:
            valid = False
        return {'status': valid}
