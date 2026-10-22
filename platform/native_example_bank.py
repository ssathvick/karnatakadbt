"""Own bank-simulator ledger and durable job admission.

This preserves the existing example-bank protocol; it is a simulator, not a
connection to an authorized banking/payment network. No payment worker is
started implicitly. Production activation needs separately accepted handoff.
"""
import hashlib,json,uuid
from datetime import datetime,timezone
from sqlalchemy import MetaData,Table,select,text,update


def now():return datetime.now(timezone.utc).replace(tzinfo=None)


class NativeExampleBank:
    def __init__(self,engine):
        self.engine=engine;metadata=MetaData()
        self.tables={name:Table(name,metadata,schema='public',autoload_with=engine) for name in ['accounts','fund_blocks','initiate_payment_batch_requests','initiate_payment_requests','account_statements','accounting_logs']}

    def initialize_queue(self):
        with self.engine.begin() as c:
            if not c.execute(text('SELECT current_database()')).scalar_one().startswith('kdbt_registry_candidate_bank_'):raise ValueError('Dedicated native bank database required')
            c.execute(text('CREATE SCHEMA IF NOT EXISTS kdbt_bank_queue'))
            c.execute(text('REVOKE ALL ON SCHEMA kdbt_bank_queue FROM PUBLIC'))
            c.execute(text("CREATE TABLE IF NOT EXISTS kdbt_bank_queue.jobs(id uuid PRIMARY KEY,job_key text UNIQUE NOT NULL,task text NOT NULL,args jsonb NOT NULL,state text NOT NULL DEFAULT 'PENDING',attempts integer NOT NULL DEFAULT 0,available_at timestamptz NOT NULL DEFAULT now(),last_error text)"))
            c.execute(text('CREATE TABLE IF NOT EXISTS kdbt_bank_queue.request_receipts(operation text NOT NULL,request_key text NOT NULL,payload_sha256 text NOT NULL,response jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(operation,request_key))'))

    @staticmethod
    def receipt(c,operation,key,payload):
        if key is None:return None
        if not isinstance(key,str) or not 1<=len(key)<=256:raise ValueError('Invalid bank idempotency key')
        c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'kdbt-bank-request:'+operation+':'+key})
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        row=c.execute(text('SELECT payload_sha256,response FROM kdbt_bank_queue.request_receipts WHERE operation=:operation AND request_key=:key'),{'operation':operation,'key':key}).mappings().first()
        if row and row['payload_sha256']!=digest:raise ValueError('Bank idempotency key payload differs')
        return row['response'] if row else None

    @staticmethod
    def remember(c,operation,key,payload,response):
        if key is not None:
            digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
            c.execute(text('INSERT INTO kdbt_bank_queue.request_receipts(operation,request_key,payload_sha256,response) VALUES(:operation,:key,:digest,CAST(:response AS jsonb))'),{'operation':operation,'key':key,'digest':digest,'response':json.dumps(response)})
        return response

    @staticmethod
    def enqueue(c,task,args,key):
        c.execute(text('INSERT INTO kdbt_bank_queue.jobs(id,job_key,task,args) VALUES(:id,:key,:task,CAST(:args AS jsonb)) ON CONFLICT(job_key) DO NOTHING'),{'id':str(uuid.uuid4()),'key':key,'task':task,'args':json.dumps(args)})

    def put(self,c,kind,**values):
        table=self.tables[kind]
        return dict(c.execute(table.insert().values(created_at=now(),updated_at=now(),active=True,**values).returning(table)).mappings().one())

    def account(self,c,number,*,currency=None,locked=False):
        table=self.tables['accounts'];query=select(table).where(table.c.account_number==number)
        if currency is not None:query=query.where(table.c.account_currency==currency)
        if locked:query=query.with_for_update()
        return c.execute(query).mappings().first()

    def check_funds(self,request):
        with self.engine.connect() as c:account=self.account(c,request['account_number'])
        sufficient=account is not None and account['available_balance']>=request['total_funds_needed']
        return {'status':'success' if sufficient else 'failed','account_number':request['account_number'],'has_sufficient_funds':sufficient,'error_message':'' if sufficient else 'Account not found' if account is None else 'Insufficient funds'}

    def block_funds(self,request,*,idempotency_key=None):
        with self.engine.begin() as c:
            prior=self.receipt(c,'block_funds',idempotency_key,request)
            if prior is not None:return prior
            account=self.account(c,request['account_number'],currency=request['currency'],locked=True)
            if account is None:return {'status':'failed','block_reference_no':'','error_message':'Account not found'}
            if account['available_balance']<request['amount']:return {'status':'failed','block_reference_no':'','error_message':'Insufficient funds'}
            blocked=account['blocked_amount']+request['amount'];table=self.tables['accounts']
            # Preserve account selection and balances, while serializing
            # concurrent block requests so they cannot spend the same funds.
            c.execute(update(table).where(table.c.id==account['id']).values(available_balance=account['book_balance']-blocked,blocked_amount=blocked))
            reference=str(uuid.uuid4());self.put(c,'fund_blocks',block_reference_no=reference,account_number=request['account_number'],amount=request['amount'],currency=request['currency'],amount_released=0)
            return self.remember(c,'block_funds',idempotency_key,request,{'status':'success','block_reference_no':reference,'error_message':''})

    def initiate_payment(self,payloads,*,idempotency_key=None):
        with self.engine.begin() as c:
            prior=self.receipt(c,'initiate_payment',idempotency_key,payloads)
            if prior is not None:return prior
            batch=str(uuid.uuid4());self.put(c,'initiate_payment_batch_requests',batch_id=batch,initiate_payment_payloads=json.dumps(payloads),batching_request_status='PENDING',payment_status='NOT_APPLICABLE',payment_initiate_attempts=0,batching_request_latest_error_code=None)
            self.enqueue(c,'batching_request_worker',[batch],'batching:'+batch)
            return self.remember(c,'initiate_payment',idempotency_key,payloads,{'status':'success','error_message':''})

    def generate_account_statement(self,request):
        with self.engine.begin() as c:
            if self.account(c,request['program_account_number']) is None:return {'status':'failed','error_message':'Account not found','account_statement_id':None}
            statement=self.put(c,'account_statements',account_number=request['program_account_number'],account_statement_lob=None,account_statement_generation_status='PENDING',account_statement_date=now().date())
            self.enqueue(c,'account_statement_generator',[statement['id']],'statement:'+str(statement['id']))
        return {'status':'success','account_statement_id':str(statement['id']),'error_message':None}

    def ussd(self,phone_number,choice=''):
        if choice=='':return 'CON Welcome to Example Bank. What do you want to do? \n \n1. Get account balance \n2. Initiate transfer \n3. See recent transactions'
        if choice=='2':return 'END Bye!'
        if choice not in {'1','3'}:return 'END Invalid choice selected!'
        with self.engine.connect() as c:
            table=self.tables['accounts'];account=c.execute(select(table).where(table.c.account_holder_phone==phone_number[1:])).mappings().first()
            if account is None:return 'END Account not found for this phone number: '+phone_number
            if choice=='1':return f"END Available balance in account ending with {account['account_number'][-4:]} is ${account['available_balance']:,.2f}"
            table=self.tables['accounting_logs'];logs=c.execute(select(table).where(table.c.account_number==account['account_number']).order_by(table.c.id.desc()).limit(3)).mappings()
            result=''
            for row in logs:
                direction='CR' if row['debit_credit']=='CREDIT' else 'DR';date=row['transaction_date'].strftime('%d/%b').upper()
                result+=f"{direction} - ${row['transaction_amount']:,.2f} - {date} - {row['narrative_3']} - {row['narrative_4']} \n"
            return 'END '+result
