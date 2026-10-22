"""Atomic, content-addressed statement ingestion for native reconciliation."""
import hashlib,uuid
from sqlalchemy import MetaData,Table,select,text
from native_bridge_business import NativeBridgeBusiness,now


class NativeBridgeStatements:
    def __init__(self,engine,*,max_size,supported_types,detect_mime):
        if type(max_size) is not int or max_size<=0:raise ValueError('Explicit upload size required')
        self.engine,self.max_size,self.supported_types,self.detect_mime=engine,max_size,set(supported_types),detect_mime
        metadata=MetaData();self.statements=Table('account_statements',metadata,schema='public',autoload_with=engine);self.lobs=Table('account_statement_lobs',metadata,schema='public',autoload_with=engine)

    def upload(self,body,content_type):
        request={'request_header':{'request_id':''}}
        if not isinstance(body,bytes) or len(body)>self.max_size or content_type not in self.supported_types or self.detect_mime(body[:1024]) not in self.supported_types:return NativeBridgeBusiness.response(request,None,'REQUEST_VALIDATION_ERROR')
        try:decoded=body.decode('utf-8')
        except UnicodeDecodeError:return NativeBridgeBusiness.response(request,None,'REQUEST_VALIDATION_ERROR')
        identifier=str(uuid.uuid5(uuid.NAMESPACE_URL,hashlib.sha256(body).hexdigest()))
        with self.engine.begin() as c:
            # Both duplicate delivery and concurrent requests use the same lock.
            c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'kdbt-bridge-statement:'+identifier})
            if not c.execute(select(self.statements.c.id).where(self.statements.c.statement_id==identifier)).first():
                timestamp=now();common={'created_at':timestamp,'updated_at':timestamp,'statement_id':identifier}
                c.execute(self.statements.insert().values(**common,id=str(uuid.uuid4()),statement_date=timestamp,statement_upload_timestamp=timestamp,statement_process_status='PENDING',statement_process_attempts=0))
                c.execute(self.lobs.insert().values(**common,id=str(uuid.uuid4()),statement_lob=decoded))
        return NativeBridgeBusiness.response(request,{'statement_id':identifier})
