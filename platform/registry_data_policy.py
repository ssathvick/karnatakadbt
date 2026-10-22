"""Own parameterized compiler for authoritative IAM register-record policies."""
from sqlalchemy import and_,or_,not_,cast,case,null,Text,JSON,Numeric,Boolean,Date,DateTime,func
from sqlalchemy.dialects.postgresql import JSONB,UUID
from registry_metadata_api import RegistryAuthError

POLICY_PATHS=frozenset(['/register-data/get_record_history','/register-data/get_register_summary_data','/register-data/get_subject_record','/change-requests/get_change_requests','/change-requests/get_register_change_request_summary_data','/register-data/get_section_records','/register-data/get_tab_records','/register-data/get_allowed_parents_for_a_child_section','/register-data/search_in_a_register','/change-requests/search_in_change_request'])
POLICY_PATHS=POLICY_PATHS|frozenset('/intake-form-data/'+name for name in ['get_intake_form_submission','get_tab_records','get_intake_form_submissions_summary','search_in_intake_form_submissions','get_intake_allowed_parents'])
POLICY_PATHS=POLICY_PATHS|frozenset(['/intake-form-data/delete_intake_form_submission','/change-requests/reject_change_request','/change-requests-core-data/reject_change_request_for_core_data'])
POLICY_PATHS=POLICY_PATHS|{'/intake-form-data/reject_intake_form_submission'}
POLICY_PATHS=POLICY_PATHS|{'/change-requests/get_change_request'}
POLICY_PATHS=POLICY_PATHS|{'/intake-form-data/approve_intake_form_submission','/input-mechanism-data/enqueue_import_file'}
POLICY_PATHS=POLICY_PATHS|{'/intake-form-data/finalize_intake_form_submission','/register-data/export_register_records'}
POLICY_PATHS=POLICY_PATHS|{'/change-requests/create_change_request','/change-requests-core-data/create_change_request_for_core_data'}
POLICY_PATHS=POLICY_PATHS|{'/intake-form-data/save_intake_form_submission'}
POLICY_PATHS=POLICY_PATHS|{'/input-mechanism-data/ingest-data'}
POLICY_PATHS=POLICY_PATHS|{'/register-data/authenticate_registrant'}
POLICY_PATHS=POLICY_PATHS|{'/change-requests/approve_change_request','/change-requests-core-data/approve_change_request_for_core_data'}

class PolicyConfigurationError(RegistryAuthError):
    def __init__(self):super().__init__(503,'Record access policy is unavailable or invalid')

class RecordPolicyCompiler:
    def __init__(self,table,columns):self.table=table;self.columns=columns;self.nodes=0;self.requires_json_nullness=False
    def column(self,field):
        if not isinstance(field,str) or field not in self.columns:raise PolicyConfigurationError()
        typ=self.columns[field]['type'];column=self.table.c.data[field].astext
        if typ in {'json','jsonb'}:
            self.requires_json_nullness=True
            value=cast(self.table.c.source_json,JSON)[field] if typ=='json' else self.table.c.data[field]
            column=case((self.table.c.json_null_fields.contains([field]),null()),else_=value)
        elif typ in {'integer','bigint','smallint'}:column=cast(column,Numeric(scale=0))
        elif typ in {'numeric','double precision','real'}:column=cast(column,Numeric)
        elif typ=='boolean':column=cast(column,Boolean)
        elif typ=='date':column=cast(column,Date)
        elif typ=='uuid':column=cast(column,UUID)
        elif typ.startswith('timestamp'):column=cast(column,DateTime)
        return column,typ
    def expression(self,node,depth=0):
        self.nodes+=1
        if depth>32 or self.nodes>512 or not isinstance(node,dict):raise PolicyConfigurationError()
        if node.get('type')=='GROUP' or 'children' in node:
            children=node.get('children');op=str(node.get('operator') or 'AND').upper()
            if not isinstance(children,list) or not children or op not in {'AND','OR','NOT'}:raise PolicyConfigurationError()
            children=[self.expression(child,depth+1) for child in children]
            return or_(*children) if op=='OR' else (not_(and_(*children)) if op=='NOT' else and_(*children))
        if node.get('type')!='CONDITION':raise PolicyConfigurationError()
        column,typ=self.column(node.get('field_id'));op=node.get('operator') or 'eq';value=node.get('value');values=node.get('values')
        text=cast(column,Text) if typ in {'json','jsonb'} else column
        if typ=='json' and op not in {'contains','ncontains','startsWith','endsWith','isNull'}:raise PolicyConfigurationError()
        if op=='eq':result=column==value
        elif op=='neq':result=column!=value
        elif op in {'in','nin'}:
            values=values or []
            if not isinstance(values,list) or len(values)>1000:raise PolicyConfigurationError()
            result=column.in_(values)
            if op=='nin':result=not_(result)
        elif op in {'contains','ncontains','startsWith','endsWith'}:
            pattern={'contains':'%'+str(value)+'%','ncontains':'%'+str(value)+'%','startsWith':str(value)+'%','endsWith':'%'+str(value)}[op]
            result=text.ilike(pattern)
            if op=='ncontains':result=not_(result)
        elif op in {'gt','gte','lt','lte'}:
            if value is None:raise PolicyConfigurationError()
            result={'gt':column.__gt__,'gte':column.__ge__,'lt':column.__lt__,'lte':column.__le__}[op](value)
        elif op=='between':
            if not isinstance(value,list) or len(value)!=2:raise PolicyConfigurationError()
            result=column.between(value[0],value[1])
        elif op=='isNull':result=column.is_(None) if value else column.is_not(None)
        else:raise PolicyConfigurationError()
        return result
    def resolve(self,policies,register):
        allow=[];deny=[]
        if not isinstance(policies,(list,tuple)):raise PolicyConfigurationError()
        for policy in policies:
            if not isinstance(policy,dict) or policy.get('policy_target') not in {'REGISTER_RECORD','ATTRIBUTE'} or policy.get('policy_type') not in {'ALLOW','DISALLOW'}:raise PolicyConfigurationError()
            if policy['policy_target']!='REGISTER_RECORD' or policy.get('register_id')!=register:continue
            target=deny if policy['policy_type']=='DISALLOW' else allow
            target.append(self.expression(policy.get('policy_filter_expression')))
        parts=[]
        if allow:parts.append(or_(*allow))
        if deny:parts.append(not_(or_(*deny)))
        # Apply the knowledge guard after ALLOW/DISALLOW composition. Placing
        # it inside a deny predicate would invert missing metadata into access.
        if parts and self.requires_json_nullness:parts.append(func.jsonb_typeof(self.table.c.json_null_fields)=='array')
        return and_(*parts) if parts else None
