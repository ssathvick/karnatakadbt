"""Preserved source import receipts, with original identities and no invented ingestion IDs."""
from sqlalchemy import MetaData,Table,Column,String,Integer,DateTime,Index
from sqlalchemy.dialects.postgresql import JSONB
metadata=MetaData()
history=Table('native_registry_import_history',metadata,Column('id',String,primary_key=True),Column('document_id',String,nullable=False),Column('record_number',Integer,nullable=False),Column('import_file_id',String,nullable=False),Column('at',DateTime,nullable=False),Column('data',JSONB,nullable=False))
Index('native_registry_import_history_position',history.c.document_id,history.c.record_number)
