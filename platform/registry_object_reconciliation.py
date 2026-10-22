"""Read-only source object reconciliation into the private migration namespace.

Copies use a source ETag precondition. Receipts commit only after streaming
checksum verification; native conflicts stop reconciliation. Source deletions
retain recovery copies rather than destroying rollback material.
"""
import hashlib
from minio.commonconfig import CopySource
from minio.error import S3Error


def digest(client,bucket,key):
    response=client.get_object(bucket,key)
    value=hashlib.sha256()
    try:
        for block in response.stream(1024*1024):value.update(block)
    finally:
        response.close();response.release_conn()
    return value.hexdigest()


def optional_digest(client,bucket,key):
    try:return digest(client,bucket,key)
    except S3Error as error:
        if error.code not in {'NoSuchKey','NoSuchObject'}:raise
        return None


def reconcile_object(storage,store_id,bucket,previous=None):
    """Return a durable-receipt payload; caller serializes and commits receipts.

    The caller must retain source ownership and block native object writers.
    An unknown existing object may be adopted only when its content matches
    the source. Changed or missing receipt-owned native objects fail closed.
    """
    key=storage.key(store_id,bucket)
    client=storage.client
    source=client.stat_object(bucket,store_id)
    before=optional_digest(client,storage.bucket,key)
    if previous is not None and before!=previous['sha256']:
        raise ValueError('Native object differs from its committed sync receipt')
    source_hash=digest(client,bucket,store_id)
    after_read=client.stat_object(bucket,store_id)
    identity=lambda value:(value.etag,value.size,value.version_id)
    if identity(source)!=identity(after_read):
        raise ValueError('Source object changed during checksum verification')
    if previous is None and before is not None and before!=source_hash:
        raise ValueError('Unowned native object conflicts with source')
    if before!=source_hash:
        client.copy_object(storage.bucket,key,CopySource(bucket,store_id,match_etag=source.etag))
    if digest(client,storage.bucket,key)!=source_hash:
        raise ValueError('Native object checksum differs after copy')
    final=client.stat_object(bucket,store_id)
    if identity(source)!=identity(final):
        raise ValueError('Source changed before reconciliation completed')
    return {'sha256':source_hash,'source_etag':source.etag,'size':source.size,
            'source_version':source.version_id,'copied':before!=source_hash}


def recover_native_object(storage,store_id,bucket,baseline,*,recovery_key,
                          assert_fenced,persist_intent):
    """Recover one frozen native object, retaining the original before image.

    Both object producers must remain fenced for the entire call. The caller
    supplies a durable intent writer and reuses its unique recovery key on
    retries. This primitive does not grant production recovery admission.
    ``baseline`` is the checksum receipt captured before native ownership,
    or None for an originally absent object. Never infer it from live content.
    """
    if not recovery_key.startswith('recovery/native-return/') or '..' in recovery_key.split('/'):
        raise ValueError('Dedicated recovery object key required')
    client=storage.client;native_key=storage.key(store_id,bucket)
    expected=None if baseline is None else baseline['sha256']
    assert_fenced()
    target=optional_digest(client,bucket,store_id)
    desired=optional_digest(client,storage.bucket,native_key)
    # A crash after the copy/delete but before receipt persistence is retryable.
    if target==desired:
        return {'sha256':desired,'recovered':False,'recovery_key':recovery_key}
    if target!=expected:
        raise ValueError('Original object changed since the ownership baseline')
    if expected is not None:
        before=client.stat_object(bucket,store_id)
        saved=optional_digest(client,storage.bucket,recovery_key)
        if saved is not None and saved!=expected:
            raise ValueError('Recovery before image conflicts with baseline')
        if saved is None:
            assert_fenced()
            client.copy_object(storage.bucket,recovery_key,CopySource(bucket,store_id,match_etag=before.etag))
        if digest(client,storage.bucket,recovery_key)!=expected:
            raise ValueError('Recovery before image checksum mismatch')
    persist_intent({'bucket':bucket,'store_id':store_id,'before_sha256':expected,
                    'after_sha256':desired,'recovery_key':recovery_key})
    assert_fenced()
    if optional_digest(client,bucket,store_id)!=expected:
        raise ValueError('Original object changed before recovery commit')
    if optional_digest(client,storage.bucket,native_key)!=desired:
        raise ValueError('Native object changed before recovery commit')
    if desired is None:
        client.remove_object(bucket,store_id)
    else:
        native=client.stat_object(storage.bucket,native_key)
        client.copy_object(bucket,store_id,CopySource(storage.bucket,native_key,match_etag=native.etag))
    if optional_digest(client,bucket,store_id)!=desired:
        raise ValueError('Recovered object checksum mismatch')
    assert_fenced()
    return {'sha256':desired,'recovered':True,'recovery_key':recovery_key}
