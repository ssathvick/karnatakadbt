"""Explicit source-schema reverse contracts for remaining registry families.

The source table allowlist comes from independently implemented native business
families, not arbitrary database names. Recovery is still restricted to restored
reference databases until coordinated production authorization is implemented.
"""
from registry_record_rollback import RecordRollback
from registry_metadata_rollback import MetadataRollback
from registry_queue_rollback import QueueRollback
from registry_structured_sync import structured_specs
from registry_auxiliary_sync import NativeAuxiliaryProjector
from registry_remaining_sync import NativeRemainingProjector


def remaining_tables(source_contract):
    covered=set(RecordRollback().mapping)|set(MetadataRollback(source_contract).mapping)|set(QueueRollback(source_contract).mapping)
    families=set(structured_specs())|set(NativeAuxiliaryProjector().mapping)|set(NativeRemainingProjector().mapping)|{'g2p_registrant_authentication_providers','g2p_registrant_authentications'}
    return families-covered


class RemainingRegistryRollback(RecordRollback):
    def __init__(self,source_contract):
        self.mapping={}
        for table in sorted(remaining_tables(source_contract)):
            if table not in source_contract:raise ValueError('Complete remaining registry source contract required')
            profile=source_contract[table]
            if not profile['keys'] or len(set(profile['keys']))!=len(profile['keys']):raise ValueError('Stable source recovery identity required')
            columns={name:{'type':typ,'nullable':nullable=='YES'} for name,typ,udt,nullable in profile['columns']}
            if set(profile['keys'])-set(columns):raise ValueError('Recovery identity absent from source columns')
            self.mapping[table]={'primary_key':profile['keys'],'columns':columns}
