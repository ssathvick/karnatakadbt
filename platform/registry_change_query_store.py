"""Own indexed change-request sequence, counts, references and verification reads."""
from sqlalchemy import select,func
from registry_readable_store import RegistryReadableStore
from registry_row_store import rows
from registry_layout_store import layouts
from registry_configuration_store import catalog
from registry_record_store import record_timestamp
from registry_metadata_store import RegistryError

SUPPORTED_PATHS=frozenset('/change-requests/'+name for name in [
    'check_change_request_sequence','get_number_of_pending_change_requests',
    'get_number_of_cross_register_changes','get_cross_register_changes',
    'get_verifications_for_change_request'])

class RegistryChangeQueryStore(RegistryReadableStore):
    def change(self,c,key):
        value=c.execute(select(rows.c.data).where(rows.c.kind=='change',rows.c.key==self.row_key('change',{'change_request_id':key}))).scalar_one_or_none()
        if value is None:self.fail('CHANGE_REQUEST_NOT_FOUND')
        return dict(value)
    def execute_request(self,path,p,actor,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_request(path,p,actor,pagination)
        op=path.rsplit('/',1)[-1]
        if op=='get_verifications_for_change_request':
            # The retained legacy wrapper ignores submission_id and requires a
            # pagination object; its newer counterpart has a distinct error.
            if pagination is None:raise RegistryError('SYS-ERR-001')
            return super().execute_request('/verifications/get_verifications',{'change_request_id':p.get('change_request_id')},actor,pagination)
        with self.engine.connect() as c:
            if op=='check_change_request_sequence':
                value=self.change(c,p['change_request_id'])
                total=c.execute(select(func.count()).select_from(rows).where(rows.c.kind=='change',rows.c.record_id==value['internal_record_id'],rows.c.status=='PENDING',rows.c.at<record_timestamp(value['created_at']))).scalar_one()
                return {'change_request_id':value['change_request_id'],'internal_record_id':value['internal_record_id'],'has_earlier_pending_change_requests':total>0,'number_of_earlier_pending_change_requests':total,'approval_decision_blocked':value['approval_status']=='PENDING' and total>0},None
            self.require_definition(c,p['subject_register_id'])
            if op=='get_number_of_pending_change_requests':
                total=c.execute(select(func.count()).select_from(rows).where(rows.c.kind=='change',rows.c.register_id==p['subject_register_id'],rows.c.record_id==p['subject_record_id'],rows.c.data['tab_id'].astext==p['tab_id'],rows.c.status=='PENDING')).scalar_one()
                return {**p,'number_of_pending_change_requests':total},None
            payload=rows.alias('change_payload')
            joined=rows.join(payload,(payload.c.kind=='change-payload') & (rows.c.data['change_request_id'].astext==payload.c.data['change_request_id'].astext))
            condition=(rows.c.kind=='change') & (rows.c.status=='PENDING') & payload.c.data['search_text'].astext.ilike('%'+p['subject_record_id']+'%')
            if op=='get_number_of_cross_register_changes':
                total=c.execute(select(func.count()).select_from(joined).where(condition)).scalar_one()
                return {**p,'number_of_cross_register_changes':total},None
            joined=joined.join(catalog,(catalog.c.kind=='register') & (catalog.c.id==rows.c.register_id)).join(layouts,(layouts.c.kind=='tab') & (layouts.c.id==rows.c.data['tab_id'].astext))
            query=select(rows.c.data,catalog.c.data['register_mnemonic'].as_string(),layouts.c.data['tab_label'].as_string()).select_from(joined).where(condition).order_by(rows.c.at.desc())
            output=[]
            for value,mnemonic,label in c.execute(query):
                item={name:value.get(name) for name in self.models.definitions['CrossRegisterChangeRequestData']['properties']}
                item.update(register_mnemonic=mnemonic,tab_label=label)
                for name in ['created_at','approved_at']:item[name]=record_timestamp(value[name]).isoformat() if value.get(name) else None
                output.append(self.models.model('CrossRegisterChangeRequestData').model_validate(item).model_dump(mode='json'))
            return {'cross_register_changes':output},None
