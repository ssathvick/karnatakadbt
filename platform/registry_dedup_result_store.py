"""Own persisted duplicate-match result views; matching workers migrate separately."""
from sqlalchemy import MetaData,Table,Column,String,BigInteger,Identity,Index,select,func
from sqlalchemy.dialects.postgresql import JSONB
from registry_change_policy_store import RegistryChangePolicyStore
from registry_configuration_store import catalog
from registry_record_store import record_timestamp
from registry_metadata_store import RegistryError

metadata=MetaData()
matches=Table('console_duplicate_matches',metadata,Column('kind',String,primary_key=True),Column('id',String,primary_key=True),Column('target_id',String,nullable=False),Column('sequence',BigInteger,Identity(),nullable=False),Column('data',JSONB,nullable=False))
Index('ix_console_duplicate_target',matches.c.kind,matches.c.target_id,matches.c.sequence)
OPERATIONS={
    '/register-data/get_deduplication_register_results':('change-register','DeduplicationRegisterResultData'),
    '/register-data/get_deduplication_change_request_results':('change-change','DeduplicationChangerequestResultData'),
    '/intake-form-data/get_deduplication_intake_form_register_results':('intake-register','DeduplicationIntakeFormRegisterResultData'),
    '/intake-form-data/get_deduplication_intake_form_intake_form_results':('intake-intake','DeduplicationIntakeFormIntakeFormResultData')}
SUPPORTED_PATHS=frozenset(OPERATIONS)
class RegistryDedupResultStore(RegistryChangePolicyStore):
    def initialize(self):super().initialize();metadata.create_all(self.engine)
    def execute_request(self,path,p,actor,pagination=None):
        if path not in OPERATIONS:return super().execute_request(path,p,actor,pagination)
        kind,model=OPERATIONS[path];intake=kind.startswith('intake-')
        if not intake and pagination is None:raise RegistryError('SYS-ERR-001')
        field='submission_id' if intake else 'change_request_id'
        with self.engine.connect() as c:
            condition=(matches.c.kind==kind) & (matches.c.target_id==p[field]);query=select(matches.c.data).where(condition).order_by(matches.c.sequence)
            total=c.execute(select(func.count()).select_from(matches).where(condition)).scalar_one()
            if not intake:query=query.offset((pagination['current_page']-1)*pagination['page_size']).limit(pagination['page_size'])
            values=list(c.execute(query).scalars());names={}
            if intake:
                ids={value['section_register_id'] for value in values}
                names={row['register_id']:row['register_mnemonic'] for row in c.execute(select(catalog.c.data).where(catalog.c.kind=='register',catalog.c.id.in_(ids))).scalars()} if ids else {}
            output=[]
            for original in values:
                value=dict(original);value['created_at']=record_timestamp(value['created_at']).isoformat() if value.get('created_at') else None
                if intake:value['section_register_mnemonic']=names.get(value['section_register_id'])
                output.append(self.models.model(model).model_validate(value).model_dump(mode='json'))
            return output if intake else {'results':output},{'number_of_items':total,'number_of_pages':1 if intake else (total+pagination['page_size']-1)//pagination['page_size']}
