"""Custom change-request/intake verifications with per-target row locking."""
import datetime,uuid
from sqlalchemy import select,func
from registry_status_store import RegistryStatusStore
from registry_row_store import rows
from registry_metadata_store import RegistryError

SUPPORTED_PATHS=frozenset(['/verifications/get_verifications','/verifications/add_verification'])

class RegistryVerificationStore(RegistryStatusStore):
    def __init__(self,engine,storage=None,clock=None):
        super().__init__(engine,storage)
        self.clock=clock or (lambda:datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))
    def verification_target(self,c,p,lock=False):
        change=p.get('change_request_id');submission=p.get('submission_id')
        if bool(change)==bool(submission):self.fail('REQUEST_VALIDATION_ERROR','Exactly one of change_request_id or submission_id is required')
        kind='change' if change else 'intake';field='change_request_id' if change else 'submission_id';target=change or submission
        if not change:
            try:target=str(uuid.UUID(target))
            except (ValueError,AttributeError,TypeError):raise RegistryError('SYS-ERR-001') from None
        key=self.row_key(kind,{field:target});query=select(rows.c.data).where(rows.c.kind==kind,rows.c.key==key)
        if lock:query=query.with_for_update()
        value=c.execute(query).scalar_one_or_none()
        if value is None:self.fail('CHANGE_REQUEST_NOT_FOUND' if change else 'INTAKE_FORM_NOT_FOUND',None if change else f'INTAKE_FORM_NOT_FOUND: {submission}')
        return kind,field,dict(value)
    def execute_request(self,path,p,actor,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_request(path,p,actor,pagination)
        read=path.endswith('/get_verifications')
        if read and pagination is None:self.fail('REQUEST_VALIDATION_ERROR','pagination_request is required for this endpoint')
        # No global configuration mutex on record transactions. Only the target
        # request/submission is locked, allowing unrelated records to progress.
        with (self.engine.connect() if read else self.engine.begin()) as c:
            kind,field,target=self.verification_target(c,p,lock=not read)
            if read:
                condition=(rows.c.kind=='verification') & (rows.c.data[field].astext==str(target[field]))
                total=c.execute(select(func.count()).select_from(rows).where(condition)).scalar_one()
                sort=pagination.get('sort_by') or '-verified_at';reverse=sort.startswith('-');name=sort.removeprefix('-')
                if name not in self.models.definitions['VerificationData']['properties']:name='verified_at';reverse=True
                order=rows.c.data[name].astext
                query=select(rows.c.data).where(condition).order_by(order.desc() if reverse else order.asc()).offset((pagination['current_page']-1)*pagination['page_size']).limit(pagination['page_size'])
                return {'verifications':[self.models.model('VerificationData').model_validate(value).model_dump(mode='json') for value in c.execute(query).scalars()]},{'number_of_items':total,'number_of_pages':(total+pagination['page_size']-1)//pagination['page_size']}
            stamp=self.clock().isoformat();key=str(uuid.uuid4())
            value={'verification_id':key,'register_id':target['register_id'],'internal_record_id':target.get('internal_record_id') if kind=='change' else None,'section_id':target.get('section_id') if kind=='change' else None,'change_request_id':target['change_request_id'] if kind=='change' else None,'submission_id':target['submission_id'] if kind=='intake' else None,'verified_by':p['verified_by'],'verified_at':stamp,'verification_observations':p.get('verification_observations'),'is_approved':p['is_approved']}
            counter='no_of_verifications_done' if kind=='change' else 'number_of_verifications_done';target[counter]=(target.get(counter) or 0)+1
            self.put_row(c,kind,target);self.put_row(c,'verification',value,True)
            self.record(c,actor,'add_verification',key,{'verification_id':key,field:target[field]})
            return self.models.model('VerificationData').model_validate(value).model_dump(mode='json'),None
