"""Native bridge state machines and transactional dispatch, without legacy imports.

Adapters are explicit capabilities. None of these tasks discovers remote hosts,
sends notifications, or authorizes financial transfers by itself.
"""
import json,uuid
from sqlalchemy import MetaData,Table,select,text,update
from native_bridge_business import now


class NativeBridgeWorkers:
    SPECS={
        'mapper_resolution_worker':('disbursement_batch_control','fa_resolution','id'),
        'geo_resolution_worker':('disbursement_batch_control','geo_resolution','id'),
        'warehouse_allocation_worker':('disbursement_batch_control','warehouse_allocation','id'),
        'agency_allocation_worker':('disbursement_batch_control','agency_allocation','id'),
        'disburse_funds_from_bank_worker':('disbursement_batch_control','sponsor_bank_dispatch','id'),
        'check_funds_with_bank_worker':('envelope_batch_status_for_cash','funds_available','disbursement_envelope_id'),
        'block_funds_with_bank_worker':('envelope_batch_status_for_cash','funds_blocked','disbursement_envelope_id'),
        'warehouse_notification_worker':('disbursement_batch_control_geo','warehouse_notification','id'),
        'agency_notification_worker':('disbursement_batch_control_geo','agency_notification','id'),
        'beneficiary_notification_worker':('disbursement_resolution_geo_address','beneficiary_notification','disbursement_id'),
        'mt940_processor_worker':('account_statements','statement_process','statement_id')}
    def __init__(self,engine,adapters,*,max_attempts=3,process_future=False,suppress_notifications=False):
        self.engine,self.adapters=engine,adapters;self.max_attempts=max_attempts;self.process_future=process_future;self.suppress_notifications=suppress_notifications
        if type(max_attempts) is not int or max_attempts<1:raise ValueError('Positive retry limit required')
        metadata=MetaData();names=['disbursement_batch_control','disbursement_envelopes','envelope_control','envelope_batch_status_for_cash','disbursements','disbursement_resolution_financial_address','disbursement_resolution_geo_address','disbursement_batch_control_geo','disbursement_batch_control_geo_attributes','notification_logs','account_statements','account_statement_lobs','disbursement_recons','disbursement_error_recons']
        self.tables={name:Table(name,metadata,schema='public',autoload_with=engine) for name in names}

    def initialize_queue(self):
        with self.engine.begin() as c:
            if not c.scalar(text('SELECT current_database()')).startswith('kdbt_registry_candidate_bridge_'):raise ValueError('Dedicated native bridge database required')
            c.execute(text('CREATE SCHEMA IF NOT EXISTS kdbt_bridge_queue'));c.execute(text('REVOKE ALL ON SCHEMA kdbt_bridge_queue FROM PUBLIC'))
            c.execute(text("CREATE TABLE IF NOT EXISTS kdbt_bridge_queue.jobs(id uuid PRIMARY KEY,job_key text UNIQUE NOT NULL,task text NOT NULL,identifier text NOT NULL,state text NOT NULL DEFAULT 'PENDING',attempts integer NOT NULL DEFAULT 0,available_at timestamptz NOT NULL DEFAULT now(),last_error text)"))

    def rows(self,c,kind,*,locked=False,**filters):
        table=self.tables[kind];query=select(table)
        for key,value in filters.items():query=query.where(table.c[key]==value)
        if locked:query=query.with_for_update()
        return list(c.execute(query).mappings())
    def one(self,c,kind,**filters):
        rows=self.rows(c,kind,**filters)
        if not rows:raise ValueError('Required bridge state missing')
        return rows[0]
    def put(self,c,kind,**values):
        table=self.tables[kind];values.setdefault('id',str(uuid.uuid4()));values.update(created_at=now(),updated_at=now())
        return dict(c.execute(table.insert().values(**values).returning(table)).mappings().one())
    def change(self,c,kind,identifier,**values):
        table=self.tables[kind];c.execute(update(table).where(table.c.id==identifier).values(updated_at=now(),**values))
    @staticmethod
    def status_column(phase):return phase+'_with_bank' if phase in {'funds_available','funds_blocked'} else phase+'_status'
    @staticmethod
    def error_column(phase):return phase+'_error_code' if phase=='statement_process' else phase+'_latest_error_code'
    @staticmethod
    def timestamp_column(phase):return phase+'_latest_timestamp' if phase in {'funds_available','funds_blocked'} else phase+'_timestamp'
    def due(self,c,task,row):
        if task in {'check_funds_with_bank_worker','block_funds_with_bank_worker','disburse_funds_from_bank_worker'}:
            envelope=self.one(c,'disbursement_envelopes',id=row['disbursement_envelope_id'])
            if envelope['cancellation_status']=='Cancelled' or not self.process_future and envelope['disbursement_schedule_date']!=now().date():return False
            if task=='check_funds_with_bank_worker':
                control=self.one(c,'envelope_control',disbursement_envelope_id=envelope['id'])
                return control['number_of_disbursements_received']==envelope['number_of_disbursements'] and control['total_disbursement_quantity_received']==envelope['total_disbursement_quantity']
            cash=self.one(c,'envelope_batch_status_for_cash',disbursement_envelope_id=envelope['id'])
            return cash['funds_available_with_bank']=='FUNDS_AVAILABLE' if task=='block_funds_with_bank_worker' else cash['funds_blocked_with_bank']=='FUNDS_BLOCK_SUCCESS'
        return True

    def schedule(self,task,*,limit=100):
        if task not in self.SPECS or not 1<=limit<=1000:raise ValueError('Unknown scheduler or invalid batch size')
        kind,phase,key=self.SPECS[task];table=self.tables[kind];column=self.status_column(phase)
        pending=['PENDING_CHECK','FUNDS_NOT_AVAILABLE'] if phase=='funds_available' else ['PENDING_CHECK','FUNDS_BLOCK_FAILURE'] if phase=='funds_blocked' else ['PENDING'];count=0
        with self.engine.begin() as c:
            rows=c.execute(select(table).where(table.c[column].in_(pending),table.c[phase+'_attempts']<self.max_attempts).order_by(table.c.id).limit(limit).with_for_update(skip_locked=True)).mappings()
            for row in rows:
                if not self.due(c,task,row):continue
                identifier=row[key];job_key=task+':'+identifier+':'+str(row[phase+'_attempts'])
                c.execute(text('INSERT INTO kdbt_bridge_queue.jobs(id,job_key,task,identifier) VALUES(:id,:key,:task,:identifier) ON CONFLICT(job_key) DO NOTHING'),{'id':str(uuid.uuid4()),'key':job_key,'task':task,'identifier':identifier})
                self.change(c,kind,row['id'],**{column:'CHECK_IN_PROGRESS' if phase in {'funds_available','funds_blocked'} else 'PROCESSING'});count+=1
        return count

    def run_one(self):
        job=None
        try:
            with self.engine.begin() as c:
                job=c.execute(text("SELECT id,task,identifier FROM kdbt_bridge_queue.jobs WHERE state='PENDING' AND available_at<=now() ORDER BY available_at,id FOR UPDATE SKIP LOCKED LIMIT 1")).mappings().first()
                if job is None:return False
                self.task(job['task'],job['identifier'])
                c.execute(text("UPDATE kdbt_bridge_queue.jobs SET state='SUCCESS',attempts=attempts+1,last_error=NULL WHERE id=:id"),{'id':job['id']})
            return True
        except Exception:
            if job:
                with self.engine.begin() as c:c.execute(text("UPDATE kdbt_bridge_queue.jobs SET attempts=attempts+1,last_error='NATIVE_BRIDGE_TASK_RETRY_REQUIRED',available_at=now()+interval '30 seconds' WHERE id=:id AND state='PENDING'"),{'id':job['id']})
            raise

    def task(self,name,identifier=None):
        if name.endswith('_beat_producer'):
            return self.schedule(name.removesuffix('_beat_producer')+'_worker')
        if name not in self.SPECS:raise ValueError('Unknown bridge task')
        kind,phase,key=self.SPECS[name];column=self.status_column(phase);row=None
        try:
            with self.engine.begin() as c:
                row=self.one(c,kind,locked=True,**{key:identifier})
                terminal={'PROCESSED','NOT_APPLICABLE','ERROR','FUNDS_AVAILABLE' if phase=='funds_available' else 'FUNDS_BLOCK_SUCCESS'}
                if row[column] in terminal:return False
                if not self.due(c,name,row):
                    self.change(c,kind,row['id'],**{column:'PENDING_CHECK' if phase in {'funds_available','funds_blocked'} else 'PENDING'});return False
                if phase in {'funds_available','funds_blocked'}:self.funds(c,phase,row)
                elif phase=='fa_resolution':self.financial(c,row)
                elif phase=='geo_resolution':self.geo(c,row)
                elif phase in {'warehouse_allocation','agency_allocation'}:self.allocate(c,phase.split('_')[0],row)
                elif phase.endswith('_notification'):self.notify(c,phase.split('_')[0],row)
                elif phase=='sponsor_bank_dispatch':self.disburse(c,row)
                elif phase=='statement_process':self.adapters.reconcile(self,c,row)
                values={phase+'_attempts':row[phase+'_attempts']+1,self.error_column(phase):None}
                timestamp=self.timestamp_column(phase)
                if timestamp in self.tables[kind].c:values[timestamp]=now()
                self.change(c,kind,row['id'],**values)
            return True
        except Exception:
            if row:
                with self.engine.begin() as c:
                    fresh=self.one(c,kind,locked=True,**{key:identifier});attempts=fresh[phase+'_attempts']+1
                    values={phase+'_attempts':attempts,self.error_column(phase):'NATIVE_BRIDGE_ADAPTER_OR_STATE_ERROR',column:'ERROR' if attempts>=self.max_attempts else 'PENDING_CHECK' if phase in {'funds_available','funds_blocked'} else 'PENDING'}
                    timestamp=self.timestamp_column(phase)
                    if timestamp in self.tables[kind].c:values[timestamp]=now()
                    self.change(c,kind,fresh['id'],**values)
            raise

    def funds(self,c,phase,row):
        envelope=self.one(c,'disbursement_envelopes',id=row['disbursement_envelope_id']);configuration=self.adapters.sponsor(envelope)
        if envelope['total_disbursement_quantity']==0:
            values={'funds_available_with_bank':'FUNDS_AVAILABLE'} if phase=='funds_available' else {'funds_blocked_with_bank':'FUNDS_BLOCK_SUCCESS','funds_blocked_reference_number':'NO_FUNDS_REQUIRED'}
            self.change(c,'envelope_batch_status_for_cash',row['id'],**values);return
        payload={'account_number':configuration['program_account_number'],'currency':envelope['measurement_unit'],'amount':envelope['total_disbursement_quantity']} if phase=='funds_blocked' else {'account_number':configuration['program_account_number'],'account_currency':envelope['measurement_unit'],'total_funds_needed':envelope['total_disbursement_quantity']}
        response=self.adapters.bank('block_funds' if phase=='funds_blocked' else 'check_funds',configuration,payload,'bridge:'+phase+':'+envelope['id'])
        if phase=='funds_blocked':
            if response['status']!='success' or not response.get('block_reference_no'):raise ValueError('Bank reservation not acknowledged')
            self.change(c,'envelope_batch_status_for_cash',row['id'],funds_blocked_with_bank='FUNDS_BLOCK_SUCCESS',funds_blocked_reference_number=response['block_reference_no'])
        else:self.change(c,'envelope_batch_status_for_cash',row['id'],funds_available_with_bank='FUNDS_AVAILABLE' if response['status']=='success' else 'FUNDS_NOT_AVAILABLE')

    def financial(self,c,batch):
        payments=[row for row in self.rows(c,'disbursements',disbursement_batch_control_id=batch['id']) if row['cancellation_status']!='CANCELLED']
        missing=[row for row in payments if not self.rows(c,'disbursement_resolution_financial_address',disbursement_id=row['id'])]
        resolved=self.adapters.resolve_financial(sorted({row['beneficiary_id'] for row in missing})) if missing else []
        mapping={row['id']:row for row in resolved}
        for payment in missing:
            value=mapping.get(payment['beneficiary_id']);address=value.get('fa') if value else None
            if not isinstance(address,dict) or not address.get('account_number'):raise ValueError('Complete financial resolution required')
            self.put(c,'disbursement_resolution_financial_address',disbursement_batch_control_id=batch['id'],disbursement_id=payment['id'],beneficiary_id=payment['beneficiary_id'],mapper_resolved_fa=json.dumps(address,sort_keys=True),mapper_resolved_name=value.get('name'),mapper_resolved_fa_type=address.get('fa_type'),bank_account_number=address.get('account_number'),bank_code=address.get('bank_code'),branch_code=address.get('branch_code'),mobile_number=address.get('mobile_number'),mobile_wallet_provider=address.get('mobile_wallet_provider'),email_address=address.get('email_address'),email_wallet_provider=address.get('email_wallet_provider'))
        self.change(c,'disbursement_batch_control',batch['id'],fa_resolution_status='PROCESSED',sponsor_bank_dispatch_status='PENDING')

    def geo(self,c,batch):
        envelope=self.one(c,'disbursement_envelopes',id=batch['disbursement_envelope_id']);payments=[row for row in self.rows(c,'disbursements',disbursement_batch_control_id=batch['id']) if row['cancellation_status']!='CANCELLED']
        resolved=self.adapters.resolve_geo(envelope,payments);mapping={row['disbursement_id']:row for row in resolved}
        if len(mapping)!=len(resolved) or set(mapping)!={row['id'] for row in payments}:raise ValueError('One complete geo resolution per payment required')
        groups={}
        for payment in payments:
            value=mapping[payment['id']]
            if value['beneficiary_id']!=payment['beneficiary_id']:raise ValueError('Geo beneficiary identity mismatch')
            group=(value['administrative_zone_id_large'],value['administrative_zone_id_small']);groups.setdefault(group,[]).append(payment)
        for group,members in groups.items():
            value=mapping[members[0]['id']];identifier=str(uuid.uuid4());base={key:value[key] for key in ['administrative_zone_id_large','administrative_zone_mnemonic_large','administrative_zone_id_small','administrative_zone_mnemonic_small']}
            self.put(c,'disbursement_batch_control_geo',id=identifier,disbursement_cycle_id=batch['disbursement_cycle_id'],disbursement_envelope_id=envelope['id'],disbursement_batch_control_id=batch['id'],**base,no_of_beneficiaries=len(members),total_quantity=sum(row['disbursement_quantity'] for row in members),warehouse_notification_status='NOT_APPLICABLE',agency_notification_status='NOT_APPLICABLE',warehouse_notification_attempts=0,agency_notification_attempts=0)
            self.put(c,'disbursement_batch_control_geo_attributes',id=identifier,disbursement_batch_control_id=batch['id'])
            for payment in members:
                value=mapping[payment['id']]
                self.put(c,'disbursement_resolution_geo_address',id=payment['id'],disbursement_id=payment['id'],disbursement_cycle_id=batch['disbursement_cycle_id'],disbursement_envelope_id=envelope['id'],disbursement_batch_control_id=batch['id'],disbursement_batch_control_geo_id=identifier,beneficiary_id=payment['beneficiary_id'],**base,beneficiary_name=value.get('beneficiary_name'),beneficiary_email=value.get('beneficiary_email'),beneficiary_phone=value.get('beneficiary_phone'),beneficiary_notification_status='NOT_APPLICABLE',beneficiary_notification_attempts=0)
        next_phase='agency_allocation' if envelope['benefit_type']=='CASH_PHYSICAL' else 'warehouse_allocation'
        self.change(c,'disbursement_batch_control',batch['id'],geo_resolution_status='PROCESSED',**{next_phase+'_status':'PENDING'})

    def allocate(self,c,kind,batch):
        envelope=self.one(c,'disbursement_envelopes',id=batch['disbursement_envelope_id']);geos=self.rows(c,'disbursement_batch_control_geo',disbursement_batch_control_id=batch['id']);results=self.adapters.allocate(kind,envelope,geos)
        mapped={value['batch_control_geo_id']:value for value in results}
        if len(mapped)!=len(results) or set(mapped)!={row['id'] for row in geos}:raise ValueError('Complete keyed allocation required')
        for geo in geos:
            value=mapped[geo['id']];updates={key:value[key] for key in [kind+'_id',kind+'_mnemonic']};extra=value.get(kind+'_additional_attributes');updates[kind+'_additional_attributes']=json.dumps(extra,sort_keys=True) if isinstance(extra,(dict,list)) else extra
            if kind=='agency':updates.update(agency_notification_status='PROCESSED' if self.suppress_notifications else 'PENDING',warehouse_notification_status=('PROCESSED' if self.suppress_notifications else 'PENDING') if envelope['benefit_type'] in {'SERVICE','COMMODITY','COMBINATION'} else 'NOT_APPLICABLE')
            self.change(c,'disbursement_batch_control_geo',geo['id'],**updates)
            table=self.tables['disbursement_resolution_geo_address'];values={key:value[key] for key in [kind+'_id',kind+'_mnemonic']}
            if kind=='agency':values['beneficiary_notification_status']='PROCESSED' if self.suppress_notifications else 'PENDING'
            c.execute(update(table).where(table.c.disbursement_batch_control_geo_id==geo['id']).values(**values))
            self.change(c,'disbursement_batch_control_geo_attributes',geo['id'],**{kind+'_'+field:value.get(kind+'_'+field) for field in ['name','admin_name','admin_email','admin_phone']})
        updates={kind+'_allocation_status':'PROCESSED'}
        if kind=='warehouse':updates['agency_allocation_status']='PENDING'
        elif envelope['benefit_type']=='CASH_PHYSICAL':updates['sponsor_bank_dispatch_status']='PENDING'
        self.change(c,'disbursement_batch_control',batch['id'],**updates)

    def notify(self,c,kind,row):
        target='disbursement_resolution_geo_address' if kind=='beneficiary' else 'disbursement_batch_control_geo'
        if self.suppress_notifications:
            self.change(c,target,row['id'],**{kind+'_notification_status':'PROCESSED'});return
        # A stable notification identity allows receiver-side replay protection.
        identifier=str(uuid.uuid5(uuid.NAMESPACE_URL,'kdbt-bridge-'+kind+':'+row['id']));payload,recipient=self.adapters.notification_payload(self,c,kind,row)
        response=self.adapters.notify(kind,identifier,payload,recipient)
        if response.get('status')!='SUCCESS':raise ValueError('Notification not acknowledged')
        if not self.rows(c,'notification_logs',id=identifier):self.put(c,'notification_logs',id=identifier,notification_type=kind.upper()+'_NOTIFICATION',recipient=str(recipient['recipient_id']),payload=json.dumps(payload,default=str,sort_keys=True),response=json.dumps(response.get('response'),default=str),sent_at=now(),processed_at=now())
        self.change(c,target,row['id'],**{kind+'_notification_status':'PROCESSED'})

    def disburse(self,c,batch):
        envelope=self.one(c,'disbursement_envelopes',id=batch['disbursement_envelope_id']);cash=self.one(c,'envelope_batch_status_for_cash',locked=True,disbursement_envelope_id=envelope['id']);configuration=self.adapters.sponsor(envelope)
        payments=self.adapters.payment_payloads(self,c,envelope,batch,cash,configuration)
        response=self.adapters.bank('initiate_payment',configuration,payments,'bridge:dispatch:'+batch['id']) if payments else {'status':'success'}
        if response['status']!='success':raise ValueError('Bank dispatch not acknowledged')
        self.change(c,'disbursement_batch_control',batch['id'],sponsor_bank_dispatch_status='PROCESSED')
        self.change(c,'envelope_batch_status_for_cash',cash['id'],number_of_disbursements_shipped=cash['number_of_disbursements_shipped']+len(payments))
