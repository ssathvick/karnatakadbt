"""Translate historical native queue URLs to the retained worker's pool IDs."""
from urllib.parse import urlsplit

def normalize_status_queue(connection, *, issuer, fenced):
    parsed=urlsplit(issuer)
    if parsed.scheme not in {'http','https'} or not parsed.netloc or parsed.query or parsed.fragment or issuer.endswith('/'):
        raise ValueError('Explicit canonical credential issuer required')
    if not callable(fenced) or fenced() is not True:raise ValueError('Observed producer fence required')
    prefix=issuer+'/v1/certify/credentials/status-list/'
    with connection.cursor() as cursor:
        cursor.execute('SELECT transaction_log_id,status_list_credential_id FROM certify.credential_status_transaction ORDER BY transaction_log_id FOR UPDATE')
        rows=cursor.fetchmany(100001)
        if len(rows)>100000:raise ValueError('Bounded status queue migration exceeded')
        changes=[]
        for transaction_id,value in rows:
            if not isinstance(value,str):raise ValueError('Unknown status pool reference')
            identifier=value[len(prefix):] if value.startswith(prefix) else value
            if not identifier or len(identifier)>128 or any(c in identifier for c in '/?#:'):
                raise ValueError('Unknown issuer or status pool reference')
            cursor.execute('SELECT 1 FROM certify.status_list_credential WHERE id=%s FOR KEY SHARE',(identifier,))
            if cursor.fetchone() is None:raise ValueError('Status queue refers to a missing pool')
            if identifier!=value:changes.append((identifier,transaction_id,value))
        if fenced() is not True:raise ValueError('Status queue fence changed')
        for identifier,transaction_id,before in changes:
            cursor.execute('UPDATE certify.credential_status_transaction SET status_list_credential_id=%s WHERE transaction_log_id=%s AND status_list_credential_id=%s',(identifier,transaction_id,before))
            if cursor.rowcount!=1:raise ValueError('Status queue changed during normalization')
    if fenced() is not True:raise ValueError('Status queue fence changed before commit')
    return {'queue_rows_verified':len(rows),'historical_url_references_converted':len(changes)}
