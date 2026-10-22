"""Own intake detail, tabs, search, summary and parent-choice operations."""
import uuid
from sqlalchemy import select,func,exists,and_,or_,cast,Numeric,Boolean,DateTime,JSON
from registry_intake_record_store import RegistryIntakeRecordStore,intake_records
from registry_row_store import rows
from registry_record_store import record_timestamp
from registry_layout_store import layouts
from registry_document_store import documents
from registry_data_policy import RecordPolicyCompiler
from registry_search_store import filter_conditions
from registry_metadata_store import RegistryError
from registry_metadata_api import RegistryPrincipal

SUPPORTED_PATHS=frozenset('/intake-form-data/'+name for name in ['get_intake_form_submission','get_tab_records','get_intake_form_submissions_summary','search_in_intake_form_submissions','get_intake_allowed_parents'])

class RegistryIntakeViewStore(RegistryIntakeRecordStore):
    def intake_meta(self,c,key,lock=False):
        key=str(uuid.UUID(key));query=select(rows.c.data).where(rows.c.kind=='intake',rows.c.key==self.row_key('intake',{'submission_id':key}))
        if lock:query=query.with_for_update()
        value=c.execute(query).scalar_one_or_none()
        if value is None:self.fail('INTAKE_FORM_NOT_FOUND','INTAKE_FORM_NOT_FOUND: '+key)
        return dict(value)
    def intake_interface(self,c,register):
        self.require_definition(c,register);meta=self.intake_contract.get(register)
        if meta is None:raise RegistryError('SYS-ERR-001')
        return meta
    def intake_policy(self,c,register,policies):return RecordPolicyCompiler(intake_records,self.intake_interface(c,register)['columns']).resolve(policies,register)
    def readable_submission(self,c,key,policies):
        value=self.intake_meta(c,key);condition=self.intake_policy(c,value['register_id'],policies)
        if condition is not None:
            query=select(intake_records.c.key).where(intake_records.c.register_id==value['register_id'],intake_records.c.submission_id==str(value['submission_id']))
            if not c.execute(query.where(condition)).first() and c.execute(query).first():self.fail('RECORD_ACCESS_DENIED')
        return value
    def intake_summary_policy(self,c,policies):
        if not policies:return None
        clauses=[]
        for definition in self.definitions(c):
            register=definition['register_id'];meta=self.intake_contract.get(register)
            if meta is None:continue
            condition=RecordPolicyCompiler(intake_records,meta['columns']).resolve(policies,register);clause=rows.c.register_id==register
            if condition is not None:clause=and_(clause,exists(select(1).select_from(intake_records).where(intake_records.c.register_id==register,intake_records.c.submission_id==rows.c.data['submission_id'].astext,condition)))
            clauses.append(clause)
        return or_(*clauses) if clauses else None
    def submission_sections(self,c,form,tab=None):
        tabs={value['tab_id']:value for value in self.rows(c,'intake-tab') if value['form_id']==form and (tab is None or value['tab_id']==tab)};sections={value['section_id']:value for value in self.rows(c,'section')};links=[value for value in self.rows(c,'intake-link') if value['tab_id'] in tabs and value['section_id'] in sections]
        links.sort(key=lambda value:(tabs[value['tab_id']]['tab_order'],value['section_order'],value['section_id']))
        return [(sections[value['section_id']],value['section_order']) for value in links]
    def submission_documents(self,c,key):
        links=list(c.execute(select(documents.c.data).where(documents.c.kind=='intake',documents.c.state=='READY',documents.c.data['submission_id'].as_string()==str(key)).order_by(documents.c.position)).scalars());ids=[value['document_id'] for value in links]
        catalog={value['document_id']:value for value in c.execute(select(documents.c.data).where(documents.c.kind=='catalog',documents.c.state=='READY',documents.c.id.in_(ids))).scalars()} if ids else {};result={}
        for link in links:
            if link.get('section_id') and link['document_id'] in catalog:result.setdefault(link['section_id'],[]).append(self.doc_wire(catalog[link['document_id']],link['section_id'],link.get('label')))
        return result
    def intake_query(self,register,key,section=None):
        query=select(intake_records.c.source_json).where(intake_records.c.register_id==register,intake_records.c.submission_id==str(key))
        if section is not None and 'section_id' in self.intake_contract[register]['columns']:query=query.where(intake_records.c.section_id==section)
        return query.order_by(intake_records.c.position)
    def section_payloads(self,c,submission,policies=(),tab=None):
        by_section=self.submission_documents(c,submission['submission_id']);sections=self.submission_sections(c,submission['form_id'],tab);result=[]
        for section,order in sections:
            register=section['section_register_id'];meta=self.intake_interface(c,register);condition=RecordPolicyCompiler(intake_records,meta['columns']).resolve(policies,register);query=self.intake_query(register,submission['submission_id'],section['section_id'])
            if condition is not None:query=query.where(condition)
            values=[self.record_value(original,meta['columns']) for original in c.execute(query).scalars()];docs=by_section.get(section['section_id'])
            # Documents lack a per-row key. Do not expose a section's files
            # when every row in that section is denied by a record policy.
            if condition is not None and not values:docs=None
            if not values and not docs:continue
            for value in values:value.pop('submission_id',None);value.pop('section_id',None)
            item={'section_id':section['section_id'],'section_register_id':register,'is_list':section['is_list'],'records':values,'documents':docs}
            if tab is not None:item['section_order']=order
            result.append(self.models.model('SectionPayloadResponseItem').model_validate(item).model_dump(mode='json'))
        return result
    def submission_payload(self,submission,sections=None,name=None,display=None):
        fields=set(self.models.definitions['SubmissionResponsePayload']['properties'])-{'record_name','section_payloads','display_fields'};fields={field for field in fields if not field.startswith('deduplication_')}
        value={field:submission.get(field) for field in fields}
        for field in ['approved_at','finalized_at','first_created_at','last_updated_at','register_ingest_processed_timestamp']:
            if value.get(field):value[field]=record_timestamp(value[field]).isoformat()
        value.update(record_name=name,section_payloads=sections)
        if display is not None:value['display_fields']=display
        return self.models.model('SubmissionResponsePayload').model_validate(value).model_dump(mode='json')
    def execute_policy_request(self,path,p,principal,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_policy_request(path,p,principal,pagination)
        if not isinstance(principal,RegistryPrincipal):raise ValueError('Trusted intake principal required')
        policies=principal.data_policies
        with self.engine.connect() as c:
            if path.endswith('/get_intake_form_submissions_summary'):
                query=select(rows.c.data['draft_status'].astext,rows.c.status,rows.c.data['register_ingest_process_status'].astext,func.count()).where(rows.c.kind=='intake');condition=self.intake_summary_policy(c,policies)
                if condition is not None:query=query.where(condition)
                result={key:0 for key in self.models.definitions['IntakeFormSubmissionsSummaryData']['properties']}
                for draft,status,process,count in c.execute(query.group_by(rows.c.data['draft_status'].astext,rows.c.status,rows.c.data['register_ingest_process_status'].astext)):
                    result['total_submissions']+=count
                    for key,test in [('total_draft_submissions',draft=='DRAFT'),('total_final_submissions',draft=='FINAL'),('total_approval_pending_submissions',draft=='FINAL' and status=='PENDING'),('total_ingested_submissions',process=='PROCESSED'),('total_approved_submissions',status=='APPROVED'),('total_rejected_submissions',status=='REJECTED')]:
                        if test:result[key]+=count
                return result,None
            if path.endswith('/search_in_intake_form_submissions'):return self.search_submissions(c,p,policies,pagination)
            submission=self.readable_submission(c,p['submission_id'],policies)
            if path.endswith('/get_intake_allowed_parents'):
                definition=self.definition(c,'register',p['section_register_id'])
                if definition is None:self.fail('REGISTER_NOT_FOUND',f"Register '{p['section_register_id']}' was not found")
                parent=definition.get('master_register_id');result={'parent_register_id':None,'parent_register_mnemonic':None,'link_required':bool(parent and p['section_register_id']!=p['form_register_id']),'allow_live_parent':bool(parent and p['section_register_id']==p['form_register_id']),'requires_selection':False,'allowed_parents':[]}
                if parent:
                    parent_def=self.require_definition(c,parent);meta=self.intake_interface(c,parent);query=self.intake_query(parent,submission['submission_id']);condition=RecordPolicyCompiler(intake_records,meta['columns']).resolve(policies,parent)
                    if condition is not None:query=query.where(condition)
                    values=[self.record_value(original,meta['columns']) for original in c.execute(query).scalars()];choices=[{'internal_record_id':value['internal_record_id'],'record_name':value.get('record_name')} for value in values if value.get('internal_record_id')]
                    result.update(parent_register_id=parent,parent_register_mnemonic=parent_def['register_mnemonic'],requires_selection=len(choices)>1,allowed_parents=choices)
                return result,None
            if path.endswith('/get_tab_records'):
                tab=c.execute(select(layouts.c.data).where(layouts.c.kind=='intake-tab',layouts.c.id==p['tab_id'])).scalar_one_or_none()
                if not tab or tab['form_id']!=submission['form_id']:self.fail('REQUEST_VALIDATION_ERROR',f"Tab '{p['tab_id']}' is not part of form '{submission['form_id']}'")
                return self.section_payloads(c,submission,policies,p['tab_id']),None
            sections=self.section_payloads(c,submission,policies);name=next((record['record_name'] for section in sections for record in section['records'] if record.get('record_name')),None)
            return self.submission_payload(submission,sections,name),None
    def search_submissions(self,c,p,policies,pagination):
        pagination=pagination or {'current_page':1,'page_size':10};register=p['register_id'];meta=self.intake_interface(c,register);schema=self.state(c,register).get('schema') or {};conditions=[];search=pagination.get('search_text')
        if search:conditions.append(intake_records.c.data['search_text'].astext.ilike('%'+search+'%'))
        try:conditions.extend(filter_conditions(schema.get('filter_schema'),meta['columns'],pagination.get('filter_by'),intake_records))
        except ValueError as error:self.fail('REQUEST_VALIDATION_ERROR',str(error))
        condition=RecordPolicyCompiler(intake_records,meta['columns']).resolve(policies,register)
        if condition is not None:conditions.append(condition)
        base=[rows.c.kind=='intake',rows.c.register_id==register]
        if conditions:base.append(rows.c.data['submission_id'].astext.in_(select(intake_records.c.submission_id).where(intake_records.c.register_id==register,*conditions).distinct()))
        total=c.execute(select(func.count()).select_from(rows).where(*base)).scalar_one();name=(pagination.get('sort_by') or '').lstrip('-');descending=bool(pagination.get('sort_by') and pagination['sort_by'].startswith('-'))
        from pathlib import Path
        import json
        columns=json.loads(Path(__file__).with_name('registry_row_contract.json').read_text())['intake']['columns']
        if name not in columns:name='last_updated_at';descending=True
        typ=columns[name]['type'];order=rows.c.data[name].astext
        if typ.startswith('timestamp'):order=cast(order,DateTime)
        elif typ in {'integer','smallint','bigint','numeric','double precision'}:order=cast(order,Numeric)
        elif typ=='boolean':order=cast(order,Boolean)
        elif typ in {'json','jsonb'}:order=cast(rows.c.data[name],JSON)
        page=pagination['current_page'];size=pagination['page_size'];submissions=list(c.execute(select(rows.c.data).where(*base).order_by(order.desc() if descending else order.asc()).offset((page-1)*size).limit(size)).scalars());ids=[str(value['submission_id']) for value in submissions]
        query=select(intake_records.c.submission_id,intake_records.c.source_json).where(intake_records.c.register_id==register,intake_records.c.submission_id.in_(ids)).order_by(intake_records.c.position)
        if condition is not None:query=query.where(condition)
        first={}
        for sid,original in c.execute(query):
            if sid not in first:first[sid]=self.record_value(original,meta['columns'])
        fields=sorted(schema.get('search_result_schema') or [],key=lambda value:value.get('order',999));result=[]
        for submission in submissions:
            value=first.get(str(submission['submission_id'])) or {};display=[{'field_name':field.get('field_name'),'value':str(value[field['field_name']]) if value.get(field['field_name']) is not None else None,'order':field.get('order',999)} for field in fields]
            result.append(self.submission_payload(submission,None,value.get('record_name'),display or None))
        return result,{'number_of_items':total,'number_of_pages':(total+size-1)//size}
