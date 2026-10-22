"""PDF CMS signing with the scoped native key, without remote key services."""
import io,uuid
from asn1crypto import keys,x509 as asn1_x509
from cryptography.hazmat.primitives import serialization
from pypdf import PdfReader
from pyhanko.sign import signers,fields
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko_certvalidator.registry import SimpleCertificateStore
from native_keymanager import certificate,VaultFailure
from native_keymanager_aux import text,when
from native_keymanager_jose import unbase
from native_key_vault import encode


def sign_pdf(aux,request):
    app,ref=request.get('applicationId'),request.get('referenceId') or ''
    aux.engine.policy(app,ref);at=when(request.get('timeStamp'));reason=text(request.get('reason'),maximum=1024)
    raw=unbase(request.get('data'))
    if not raw.startswith(b'%PDF-') or len(raw)>8*1024*1024:raise VaultFailure('Bounded PDF data is required')
    try:
        reader=PdfReader(io.BytesIO(raw),strict=True)
        password=request.get('password','')
        if not isinstance(password,str) or len(password)>1024:raise VaultFailure('Invalid PDF password')
        if reader.is_encrypted and not reader.decrypt(password):raise VaultFailure('PDF password is invalid')
        page=request.get('pageNumber',1)
        if not isinstance(page,int) or isinstance(page,bool) or page<0:raise VaultFailure('Invalid PDF page number')
        page=max(1,page)-1
        if page>=len(reader.pages):raise VaultFailure('PDF page is outside the document')
        box=None
        coords=[request.get(n,0) for n in ['lowerLeftX','lowerLeftY','upperRightX','upperRightY']]
        if any(not isinstance(v,int) or isinstance(v,bool) or v<0 for v in coords):raise VaultFailure('Invalid signature coordinates')
        if any(coords):
            x1,y1,x2,y2=coords;bounds=reader.pages[page].mediabox
            if not float(bounds.left)<=x1<x2<=float(bounds.right) or not float(bounds.bottom)<=y1<y2<=float(bounds.top):raise VaultFailure('Signature box is outside the page')
            box=tuple(coords)
        with aux.engine.vault.connect() as c:
            row=aux.engine._row(c,app,ref);cert=certificate(row['certificate']);aux.engine._valid(cert);private=aux.engine.vault._private(row)
            roots=[certificate(r[0]) for r in c.execute('''SELECT t.certificate FROM vault_aliases a JOIN km_certificates t ON a.key_id=t.key_id
WHERE a.application=? AND a.reference='' ''',(app,))]
        if not cert.not_valid_before_utc<=at<cert.not_valid_after_utc:raise VaultFailure('Requested timestamp is outside certificate validity')
        registry=SimpleCertificateStore()
        for root in roots:registry.register(asn1_x509.Certificate.load(root.public_bytes(serialization.Encoding.DER)))
        signer=signers.SimpleSigner(signing_cert=asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER)),
            signing_key=keys.PrivateKeyInfo.load(private.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())),cert_registry=registry)
        writer=IncrementalPdfFileWriter(io.BytesIO(raw),strict=True)
        if reader.is_encrypted:writer.encrypt(password)
        name='NativeSignature-'+uuid.uuid4().hex
        metadata=signers.PdfSignatureMetadata(field_name=name,md_algorithm='sha256',reason=reason,signer_key_usage={'digital_signature'})
        output=signers.PdfSigner(metadata,signer,new_field_spec=fields.SigFieldSpec(name,on_page=page,box=box)).sign_pdf(writer)
        return {'data':encode(output.getvalue())}
    except VaultFailure:raise
    except Exception:
        raise VaultFailure('PDF parsing or signing failed')
