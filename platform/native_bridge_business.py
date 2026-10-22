"""Independent envelope/disbursement transactions over the retained SQL contract."""
import copy,uuid
from datetime import date,datetime,timezone
from sqlalchemy import MetaData,Table,select,update


class BridgeBusinessError(ValueError):
    def __init__(self,code,payload=None):self.code,self.payload=code,payload;super().__init__(code)

def now():return datetime.now(timezone.utc).replace(tzinfo=None)


class NativeBridgeBusiness:
    def __init__(self,engine):
        self.engine=engine;metadata=MetaData()
        self.tables={name:Table(name,metadata,schema='public',autoload_with=engine) for name in ['disbursement_envelopes','envelope_control','envelope_batch_status_for_cash','disbursements','disbursement_batch_control']}

    def put(self,c,kind,**values):
        table=self.tables[kind];values=dict(values);values['id']=values.get('id') or str(uuid.uuid4());values.update(created_at=now(),updated_at=now())
        if 'active' in table.c:values.setdefault('active',True)
        return dict(c.execute(table.insert().values(**values).returning(table)).mappings().one())

    def one(self,c,kind,*,locked=False,**filters):
        table=self.tables[kind];query=select(table)
        for key,value in filters.items():query=query.where(table.c[key]==value)
        if locked:query=query.with_for_update()
        return c.execute(query).mappings().first()

    def change(self,c,kind,identifier,**values):
        table=self.tables[kind];c.execute(update(table).where(table.c.id==identifier).values(**values))

    @staticmethod
    def response(request,payload,code=None):
        return {'response_header':{'request_id':request['request_header']['request_id'],'response_status':'ERROR' if code else 'SUCCESS','response_error_code':code,'response_error_message':code,'response_timestamp':now()},'response_body':{'response_payload':payload}}

    def execute(self,operation,request):
        methods={'create_disbursement_envelopes':self.create_envelopes,'cancel_disbursement_envelope':self.cancel_envelope,'amend_disbursement_envelope':self.amend_envelope,'create_disbursements':self.create_disbursements,'cancel_disbursements':self.cancel_disbursements}
        if operation not in methods:raise ValueError('Unknown bridge business operation')
        body=copy.deepcopy(request['request_body']);payload=body['request_payload']
        try:
            if not payload:raise BridgeBusinessError('REQUEST_VALIDATION_ERROR')
            with self.engine.begin() as c:result=methods[operation](c,body)
            return self.response(request,result)
        except BridgeBusinessError as error:
            return self.response(request,error.payload or [],error.code)

    @staticmethod
    def validate_envelope(payload,*,amend=False):
        for field,code in [('benefit_program_id','INVALID_PROGRAM_ID'),('cycle_code_mnemonic','INVALID_CYCLE_CODE_MNEMONIC'),('benefit_code_id','INVALID_BENEFIT_CODE_ID')]:
            if payload.get(field) in {None,''}:raise BridgeBusinessError(code)
        for field,code,minimum in [('number_of_beneficiaries','INVALID_NO_OF_BENEFICIARIES',1),('number_of_disbursements','INVALID_NO_OF_DISBURSEMENTS',1),('total_disbursement_quantity','INVALID_DISBURSEMENT_QUANTITY',0)]:
            if payload.get(field) is None or payload[field]<minimum:raise BridgeBusinessError(code)
        if payload.get('disbursement_frequency') not in {'Daily','Weekly','Fortnightly','Monthly','BiMonthly','Quarterly','SemiAnnually','Annually','OnDemand'}:raise BridgeBusinessError('INVALID_DISBURSEMENT_FREQUENCY')
        if amend and not payload.get('benefit_program_mnemonic'):raise BridgeBusinessError('INVALID_PROGRAM_MNEMONIC')

    def create_envelopes(self,c,body):
        payloads=body['request_payload']
        for payload in payloads:
            self.validate_envelope(payload)
            table=self.tables['disbursement_envelopes'];values={key:value for key,value in payload.items() if key in table.c and key not in {'receipt_time_stamp','cancellation_status','cancellation_timestamp'}}
            if isinstance(values.get('disbursement_schedule_date'),str):values['disbursement_schedule_date']=date.fromisoformat(values['disbursement_schedule_date'])
            row=self.put(c,'disbursement_envelopes',**values,receipt_time_stamp=now(),cancellation_status='Not_Cancelled',cancellation_timestamp=None)
            self.put(c,'envelope_control',id=row['id'],disbursement_envelope_id=row['id'],number_of_disbursements_received=0,total_disbursement_quantity_received=0)
            if row['benefit_type'] in {'CASH_DIGITAL','CASH_PHYSICAL'}:
                self.put(c,'envelope_batch_status_for_cash',disbursement_envelope_id=row['id'],funds_available_with_bank='PENDING_CHECK',funds_blocked_with_bank='PENDING_CHECK',funds_available_attempts=0,funds_blocked_attempts=0,number_of_disbursements_shipped=0,number_of_disbursements_reconciled=0,number_of_disbursements_reversed=0)
        return payloads

    def envelope(self,c,identifier):
        row=self.one(c,'disbursement_envelopes',id=identifier,locked=True)
        if row is None:raise BridgeBusinessError('DISBURSEMENT_ENVELOPE_NOT_FOUND')
        if row['cancellation_status']=='Cancelled':raise BridgeBusinessError('DISBURSEMENT_ENVELOPE_ALREADY_CANCELED')
        return row

    def cancel_envelope(self,c,body):
        payload=body['request_payload'][0];row=self.envelope(c,payload.get('id'));self.change(c,'disbursement_envelopes',row['id'],cancellation_status='Cancelled',cancellation_timestamp=now());return [payload]

    def amend_envelope(self,c,body):
        payload=body['request_payload'][0]
        if not payload.get('id'):raise BridgeBusinessError('INVALID_DISBURSEMENT_ENVELOPE_ID')
        self.validate_envelope(payload,amend=True);row=self.envelope(c,payload['id'])
        if row['disbursement_schedule_date']<=now().date():raise BridgeBusinessError('DISBURSEMENT_ENVELOPE_DATE_PASSED')
        control=self.one(c,'envelope_control',disbursement_envelope_id=row['id'],locked=True)
        if payload['number_of_disbursements']<control['number_of_disbursements_received']:raise BridgeBusinessError('NO_OF_DISBUESEMENTS_EXCEEDS_DECLARED')
        if payload['total_disbursement_quantity']<control['total_disbursement_quantity_received']:raise BridgeBusinessError('TOTAL_DISBURSEMENT_QUANTITY_EXCEEDS_DECLARED')
        values={key:payload[key] for key in ['number_of_beneficiaries','number_of_disbursements','total_disbursement_quantity','disbursement_schedule_date']}
        if isinstance(values['disbursement_schedule_date'],str):values['disbursement_schedule_date']=date.fromisoformat(values['disbursement_schedule_date'])
        self.change(c,'disbursement_envelopes',row['id'],**values);return [payload]

    def create_disbursements(self,c,body):
        payloads=body['request_payload'];identifier=payloads[0].get('disbursement_envelope_id')
        if any(payload.get('disbursement_envelope_id')!=identifier for payload in payloads):raise BridgeBusinessError('MULTIPLE_ENVELOPES_FOUND',payloads)
        envelope=self.envelope(c,identifier);control=self.one(c,'envelope_control',disbursement_envelope_id=identifier,locked=True)
        count=control['number_of_disbursements_received']+len(payloads)
        quantity=control['total_disbursement_quantity_received']+sum(payload.get('disbursement_quantity') or 0 for payload in payloads)
        if count>envelope['number_of_disbursements']:raise BridgeBusinessError('NO_OF_DISBUESEMENTS_EXCEEDS_DECLARED',payloads)
        if quantity>envelope['total_disbursement_quantity']:raise BridgeBusinessError('TOTAL_DISBURSEMENT_QUANTITY_EXCEEDS_DECLARED',payloads)
        valid=True
        for payload in payloads:
            errors=[]
            if not payload.get('disbursement_envelope_id'):errors.append('INVALID_DISBURSEMENT_ENVELOPE_ID')
            if payload.get('disbursement_quantity') is None or payload['disbursement_quantity']<0:errors.append('INVALID_DISBURSEMENT_QUANTITY')
            if not payload.get('beneficiary_id'):errors.append('INVALID_BENEFICIARY_ID')
            if not payload.get('narrative'):errors.append('INVALID_NARRATIVE')
            payload['response_error_codes']=errors;valid=valid and not errors
        if not valid:raise BridgeBusinessError('INVALID_DISBURSEMENT_PAYLOAD',payloads)
        phases=['fa_resolution','sponsor_bank_dispatch','geo_resolution','warehouse_allocation','agency_allocation'];batch_values={}
        for phase in phases:batch_values.update({phase+'_status':'PENDING' if phase==('fa_resolution' if envelope['benefit_type']=='CASH_DIGITAL' else 'geo_resolution') else 'NOT_APPLICABLE',phase+'_timestamp':None,phase+'_latest_error_code':None,phase+'_attempts':0})
        batch=self.put(c,'disbursement_batch_control',id=body.get('disbursement_batch_control_id'),disbursement_cycle_id=envelope['disbursement_cycle_id'],disbursement_envelope_id=identifier,**batch_values)
        for payload in payloads:
            self.put(c,'disbursements',id=payload['disbursement_id'],disbursement_envelope_id=identifier,beneficiary_id=payload['beneficiary_id'],beneficiary_name=payload.get('beneficiary_name'),disbursement_quantity=payload['disbursement_quantity'],compute_elements=payload.get('compute_elements'),narrative=payload['narrative'],receipt_time_stamp=now(),cancellation_status='NOT_CANCELLED',cancellation_time_stamp=None,disbursement_cycle_id=payload.get('disbursement_cycle_id'),disbursement_batch_control_id=batch['id'])
        self.change(c,'envelope_control',control['id'],number_of_disbursements_received=count,total_disbursement_quantity_received=quantity);return payloads

    def cancel_disbursements(self,c,body):
        payloads=body['request_payload'];ids=[payload['disbursement_id'] for payload in payloads];table=self.tables['disbursements']
        rows=list(c.execute(select(table).where(table.c.id.in_(ids)).order_by(table.c.id).with_for_update()).mappings())
        if not rows:raise BridgeBusinessError('INVALID_DISBURSEMENT_ID',payloads)
        envelopes={row['disbursement_envelope_id'] for row in rows}
        if len(envelopes)!=1:raise BridgeBusinessError('MULTIPLE_ENVELOPES_FOUND',payloads)
        envelope=self.envelope(c,next(iter(envelopes)))
        if envelope['disbursement_schedule_date']<=now().date():raise BridgeBusinessError('DISBURSEMENT_ENVELOPE_SCHEDULE_DATE_REACHED',payloads)
        found={row['id']:row for row in rows};invalid=False
        for payload in payloads:
            errors=[];row=found.get(payload['disbursement_id'])
            if row is None:errors.append('INVALID_DISBURSEMENT_ID')
            elif row['cancellation_status']=='CANCELLED':errors.append('DISBURSEMENT_ALREADY_CANCELED')
            payload['response_error_codes']=errors;invalid=invalid or bool(errors)
        if invalid:raise BridgeBusinessError('INVALID_DISBURSEMENT_PAYLOAD',payloads)
        control=self.one(c,'envelope_control',disbursement_envelope_id=envelope['id'],locked=True);count=control['number_of_disbursements_received']-len(rows);quantity=control['total_disbursement_quantity_received']-sum(row['disbursement_quantity'] for row in rows)
        if count<0:raise BridgeBusinessError('NO_OF_DISBURSEMENTS_LESS_THAN_ZERO',payloads)
        if quantity<0:raise BridgeBusinessError('TOTAL_DISBURSEMENT_QUANTITY_LESS_THAN_ZERO',payloads)
        for row in rows:self.change(c,'disbursements',row['id'],cancellation_status='CANCELLED',cancellation_time_stamp=now())
        self.change(c,'envelope_control',control['id'],number_of_disbursements_received=count,total_disbursement_quantity_received=quantity);return payloads
