"""Conflict-checked operational queue projections without inventing authority.

Completion, functional IDs and transformed outgoing payloads preserve source
JSON exactly. Import/export authorization and consumer ownership remain separate.
"""
from registry_json_sync import NativeJsonProjector

OPERATIONAL_SPECS={
    'g2p_completion_score_computation_queue':{'target':'console_registry_approval_jobs','kind':'completion','key':'queue_id','position':False,'key_column':'id'},
    'g2p_functional_id_generation_queue':{'target':'console_registry_approval_jobs','kind':'functional','key':'queue_id','position':False,'key_column':'id'},
    'outgoing_transformed_data_payloads':{'target':'native_registry_worker_outputs','kind':'outgoing-transformed','key':'outgest_id','position':False,'key_column':'key'},
}


class NativeOperationalProjector(NativeJsonProjector):
    def __init__(self,native_schema='public'):
        super().__init__(native_schema,OPERATIONAL_SPECS)
