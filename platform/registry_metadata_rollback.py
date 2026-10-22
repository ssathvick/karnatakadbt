"""Exact reverse writes for the 27 metadata/message/score JSON projections.

Inherits transactional receipts, before-image conflicts, SQL/JSON null handling
and the isolated recovery database guard. This does not authorize live cutover.
"""
from registry_record_rollback import RecordRollback
from registry_json_sync import SPECS

class MetadataRollback(RecordRollback):
    def __init__(self,source_contract):
        if set(SPECS)-set(source_contract):raise ValueError('Complete metadata source contracts required')
        self.mapping={}
        for table,spec in SPECS.items():
            profile=source_contract[table]
            if profile['keys']!=[spec['key']]:raise ValueError('Metadata identity contract changed')
            columns={name:{'type':typ,'nullable':nullable=='YES'} for name,typ,udt,nullable in profile['columns']}
            self.mapping[table]={'primary_key':profile['keys'],'columns':columns}
