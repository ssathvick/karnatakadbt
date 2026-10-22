"""Own simulator batching, ledger processing, scheduling and statement retry.

No original worker modules or broker clients are imported. External statement
delivery must be supplied explicitly; an absent adapter never sends data.
"""
import json,secrets
from sqlalchemy import select,text,update
from native_example_bank import now
from native_bank_statements import statement_text


class NativeExampleBankWorker:
    TASKS=frozenset({'batching_request_beat_producer','batching_request_worker','process_payments_beat_producer','process_payments_worker','account_statement_generator'})
    def __init__(self,store,*,statement_delivery=None,payment_attempts=3,simulate_failure=None):
        self.store,self.engine=store,store.engine;self.delivery=statement_delivery;self.payment_attempts=payment_attempts;self.simulate_failure=simulate_failure or (lambda payment:None)

    def task(self,name,args):
        if name not in self.TASKS:raise ValueError('Unknown bank task')
        return getattr(self,name)(*args)

    def run_one(self):
        job=None
        try:
            # Keep the job-row lock until the idempotent business handler and
            # acknowledgement finish. A crashed runner exposes the pending job
            # again; committed batch/statement state prevents duplicate effects.
            with self.engine.begin() as c:
                job=c.execute(text("SELECT id,task,args FROM kdbt_bank_queue.jobs WHERE state='PENDING' AND available_at<=now() ORDER BY available_at,id FOR UPDATE SKIP LOCKED LIMIT 1")).mappings().first()
                if job is None:return False
                self.task(job['task'],job['args'])
                c.execute(text("UPDATE kdbt_bank_queue.jobs SET state='SUCCESS',attempts=attempts+1,last_error=NULL WHERE id=:id"),{'id':job['id']})
            return True
        except Exception:
            if job is not None:
                with self.engine.begin() as c:c.execute(text("UPDATE kdbt_bank_queue.jobs SET attempts=attempts+1,last_error='NATIVE_BANK_TASK_RETRY_REQUIRED',available_at=now()+interval '30 seconds' WHERE id=:id AND state='PENDING'"),{'id':job['id']})
            raise

    def batching_request_beat_producer(self):return self._schedule('batching_request_status','batching_request_worker','batching')
    def process_payments_beat_producer(self):return self._schedule('payment_status','process_payments_worker','payment')

    def _schedule(self,column,task,prefix):
        table=self.store.tables['initiate_payment_batch_requests'];count=0
        with self.engine.begin() as c:
            query=select(table).where(table.c[column]=='PENDING')
            if column=='payment_status':query=query.where(table.c.payment_initiate_attempts<self.payment_attempts)
            rows=list(c.execute(query.with_for_update(skip_locked=True)).mappings())
            for row in rows:
                suffix=':'+str(row['payment_initiate_attempts']) if column=='payment_status' else ''
                self.store.enqueue(c,task,[row['batch_id']],prefix+':'+row['batch_id']+suffix)
                c.execute(update(table).where(table.c.id==row['id']).values(**{column:'PROCESSING'}));count+=1
        return count

    def batch(self,c,batch_id):
        table=self.store.tables['initiate_payment_batch_requests']
        return c.execute(select(table).where(table.c.batch_id==batch_id).with_for_update()).mappings().first()

    def batching_request_worker(self,batch_id):
        with self.engine.begin() as c:
            batch=self.batch(c,batch_id)
            if batch is None or batch['batching_request_status']=='SUCCESS':return 0
            payloads=batch['initiate_payment_payloads'];payloads=json.loads(payloads) if isinstance(payloads,str) else payloads
            for payload in payloads:
                columns=set(self.store.tables['initiate_payment_requests'].c.keys())-{'id','active','created_at','updated_at','batch_id'}
                self.store.put(c,'initiate_payment_requests',batch_id=batch_id,**{column:payload.get(column) for column in columns})
            table=self.store.tables['initiate_payment_batch_requests'];c.execute(update(table).where(table.c.id==batch['id']).values(batching_request_status='SUCCESS',batching_request_latest_error_code=None,payment_status='PENDING'))
            self.store.enqueue(c,'process_payments_worker',[batch_id],'payment:'+batch_id+':'+str(batch['payment_initiate_attempts']))
            return len(payloads)

    @staticmethod
    def credit_number(payment):
        kind=payment['beneficiary_account_type']
        if kind=='BANK_ACCOUNT':return payment['beneficiary_account'] if payment['beneficiary_bank_code']=='EXAMPLE_BANK' else 'CLEARING - '+payment['beneficiary_bank_code']
        if kind=='MOBILE_WALLET':return 'CLEARING - '+payment['beneficiary_mobile_wallet_provider']
        if kind=='EMAIL_WALLET':return 'CLEARING - '+payment['beneficiary_email_wallet_provider']
        raise ValueError('Unsupported simulator account type')

    def _ledger(self,c,payment,debit_number,credit_number,amount,*,reversal=None):
        account_table=self.store.tables['accounts'];block_table=self.store.tables['fund_blocks']
        debit=self.store.account(c,debit_number,locked=True);credit=self.store.account(c,credit_number,locked=True)
        block=c.execute(select(block_table).where(block_table.c.block_reference_no==payment['funds_blocked_reference_number']).with_for_update()).mappings().first()
        if debit is None or block is None:raise ValueError('Simulator debit account or reservation missing')
        if amount>0 and (block['account_number']!=debit_number or block['currency']!=payment['remitting_account_currency'] or block['amount']-block['amount_released']<amount or debit['blocked_amount']<amount):raise ValueError('Simulator reservation does not cover payment')
        if credit is None:
            internal=payment['beneficiary_account_type']=='BANK_ACCOUNT' and payment['beneficiary_bank_code']=='EXAMPLE_BANK'
            credit=self.store.put(c,'accounts',account_holder_name=payment['beneficiary_name'] if internal else 'Clearing account for '+credit_number.removeprefix('CLEARING - '),account_number=credit_number,account_currency=payment['beneficiary_account_currency'],account_holder_phone=payment.get('beneficiary_phone_no') if internal else None,account_holder_email=payment.get('beneficiary_email') if internal else None,book_balance=0,available_balance=0,blocked_amount=0)
        book=debit['book_balance']-amount;blocked=debit['blocked_amount']-amount
        c.execute(update(account_table).where(account_table.c.id==debit['id']).values(book_balance=book,blocked_amount=blocked,available_balance=book-blocked))
        c.execute(update(block_table).where(block_table.c.id==block['id']).values(amount_released=block['amount_released']+amount))
        credit_book,credit_blocked=(book,blocked) if credit['id']==debit['id'] else (credit['book_balance'],credit['blocked_amount'])
        c.execute(update(account_table).where(account_table.c.id==credit['id']).values(book_balance=credit_book+amount,available_balance=credit_book+amount-credit_blocked))
        for direction,number in [('DEBIT',debit_number),('CREDIT',credit_number)]:
            narrative={f'narrative_{i}':payment.get(f'narrative_{i}') for i in range(1,7)}
            if reversal:narrative['narrative_6']=reversal
            self.store.put(c,'accounting_logs',reference_no=secrets.token_urlsafe(18)[:23],corresponding_block_reference_no=payment['funds_blocked_reference_number'] if direction=='DEBIT' and not reversal else '',customer_reference_no=payment['payment_reference_number'],debit_credit=direction,account_number=number,transaction_amount=amount,transaction_date=now(),transaction_currency=payment['remitting_account_currency'],transaction_code='DBT',reported_in_mt940=False,**narrative)

    def process_payments_worker(self,batch_id):
        try:
            with self.engine.begin() as c:
                batch=self.batch(c,batch_id)
                if batch is None or batch['payment_status']=='SUCCESS':return 0
                if batch['payment_initiate_attempts']>=self.payment_attempts:return 0
                table=self.store.tables['initiate_payment_requests'];payments=list(c.execute(select(table).where(table.c.batch_id==batch_id).order_by(table.c.id)).mappings())
                if not payments:raise ValueError('Simulator payment batch is empty')
                # Stable account lock order covers both existing and newly
                # created clearing accounts across concurrent batches.
                numbers=sorted({number for payment in payments for number in [payment['remitting_account'],self.credit_number(payment)]})
                for number in numbers:c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:account,0))'),{'account':'kdbt-bank-ledger:'+number})
                for payment in payments:
                    debit,credit=payment['remitting_account'],self.credit_number(payment);amount=payment['payment_amount']
                    self._ledger(c,payment,debit,credit,amount)
                    reason=self.simulate_failure(payment)
                    if reason:self._ledger(c,payment,debit,credit,-amount,reversal=reason)
                table=self.store.tables['initiate_payment_batch_requests'];c.execute(update(table).where(table.c.id==batch['id']).values(payment_status='SUCCESS',payment_initiate_attempts=batch['payment_initiate_attempts']+1))
                statement=self.store.put(c,'account_statements',account_number=payments[0]['remitting_account'],account_statement_lob=None,account_statement_generation_status='PENDING',account_statement_date=now().date())
                self.store.enqueue(c,'account_statement_generator',[statement['id']],'statement:'+str(statement['id']))
                return len(payments)
        except Exception:
            with self.engine.begin() as c:
                batch=self.batch(c,batch_id)
                if batch is not None and batch['payment_status']!='SUCCESS':
                    table=self.store.tables['initiate_payment_batch_requests'];c.execute(update(table).where(table.c.id==batch['id']).values(payment_status='PENDING',payment_initiate_attempts=batch['payment_initiate_attempts']+1))
            raise

    def account_statement_generator(self,statement_id):
        statements=self.store.tables['account_statements'];ledger=self.store.tables['accounting_logs']
        with self.engine.begin() as c:
            statement=c.execute(select(statements).where(statements.c.id==statement_id).with_for_update()).mappings().first()
            if statement is None or statement['account_statement_generation_status']=='SUCCESS':return False
            saved=statement['account_statement_lob']
            if not saved:
                account=self.store.account(c,statement['account_number'],locked=True)
                if account is None:return False
                logs=list(c.execute(select(ledger).where(ledger.c.account_number==statement['account_number'],ledger.c.reported_in_mt940.is_(False)).order_by(ledger.c.id).with_for_update()).mappings())
                if not logs:
                    c.execute(update(statements).where(statements.c.id==statement_id).values(account_statement_generation_status='NOT_APPLICABLE'));return False
                saved=statement_text(statement,account,logs)
                c.execute(update(statements).where(statements.c.id==statement_id).values(account_statement_lob=saved))
                c.execute(update(ledger).where(ledger.c.id.in_([row['id'] for row in logs])).values(reported_in_mt940=True))
        try:
            if self.delivery is None:raise ValueError('Explicit native statement delivery adapter required')
            if self.delivery(statement_id,saved) is not True:raise ValueError('Statement receiver rejected delivery')
        except Exception:
            with self.engine.begin() as c:c.execute(update(statements).where(statements.c.id==statement_id).values(account_statement_generation_status='FAILED'))
            raise
        with self.engine.begin() as c:c.execute(update(statements).where(statements.c.id==statement_id).values(account_statement_generation_status='SUCCESS'))
        return True
