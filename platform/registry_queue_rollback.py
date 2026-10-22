"""Strict reverse contracts for native registry operational queue payloads.

Native-only authorization context must remain in the native recovery backup.
This adapter never fabricates legacy actor fields or resets processing status.
"""
from registry_record_rollback import RecordRollback

QUEUE_TABLES={
    'completion':('g2p_completion_score_computation_queue','queue_id'),
    'functional':('g2p_functional_id_generation_queue','queue_id'),
    'export':('g2p_register_export_data_queue','export_id'),
    'import':('import_file_process_queue','import_file_id'),
    'outgoing-transformed':('outgoing_transformed_data_payloads','outgest_id'),
    'score':('g2p_score_compute_queue','queue_id'),
}

class QueueRollback(RecordRollback):
    def __init__(self,source_contract):
        self.mapping={}
        for kind,(table,key) in QUEUE_TABLES.items():
            if table not in source_contract or source_contract[table]['keys']!=[key]:raise ValueError('Complete operational queue contracts required')
            self.mapping[table]={'primary_key':[key],'columns':{name:{'type':typ,'nullable':nullable=='YES'} for name,typ,udt,nullable in source_contract[table]['columns']}}
