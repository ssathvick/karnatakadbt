"""Reconcile bank-committed effects whose bridge acknowledgement was lost."""
import hashlib,json
from datetime import timezone
from decimal import Decimal
from psycopg2.extras import RealDictCursor
import registry_producer_fence as fence


def reconcile_bank_effects(bank,bridge,*,account_for_envelope):
    if not bank.admitted or not bridge.admitted or bank.domain!='bank' or bridge.domain!='bridge':raise ValueError('Both payment domains require pinned closed-fence recovery admission')
    native_bank,native_bridge=bank.native,bridge.native;settings=bridge.settings;repaired_blocks=repaired_dispatches=0
    fence.authorize_recovery(native_bridge,settings['native_capability'])
    with native_bridge.cursor() as c:
        c.execute("SELECT set_config('kdbt.native_capture_key',%s,true)",(settings['capture_key'],));c.execute("SELECT set_config('kdbt.native_capture_writer','native-worker',true)")
    with native_bank.cursor(cursor_factory=RealDictCursor) as b,native_bridge.cursor(cursor_factory=RealDictCursor) as c:
        b.execute("SELECT operation,request_key,payload_sha256,response,created_at FROM kdbt_bank_queue.request_receipts WHERE response->>'status'='success' ORDER BY created_at,operation,request_key")
        receipts=b.fetchall()
        for receipt in receipts:
            key=receipt['request_key'];stamp=receipt['created_at'].astimezone(timezone.utc).replace(tzinfo=None)
            if receipt['operation']=='block_funds' and key.startswith('bridge:funds_blocked:'):
                identifier=key.removeprefix('bridge:funds_blocked:');c.execute('SELECT * FROM public.disbursement_envelopes WHERE id=%s',(identifier,));envelope=c.fetchone()
                if envelope is None:raise ValueError('Bank reservation references a missing bridge envelope')
                c.execute('SELECT * FROM public.envelope_batch_status_for_cash WHERE disbursement_envelope_id=%s FOR UPDATE',(identifier,));cash=c.fetchone()
                if cash is None:raise ValueError('Bank reservation bridge state is missing')
                reference=receipt['response'].get('block_reference_no');b.execute('SELECT * FROM public.fund_blocks WHERE block_reference_no=%s',(reference,));block=b.fetchone();configuration=account_for_envelope(envelope)
                if not block or block['account_number']!=configuration['program_account_number'] or block['currency']!=envelope['measurement_unit'] or Decimal(str(block['amount']))!=Decimal(str(envelope['total_disbursement_quantity'])):raise ValueError('Retained bank reservation does not match the bridge envelope')
                if cash['funds_blocked_with_bank']=='FUNDS_BLOCK_SUCCESS':
                    if cash['funds_blocked_reference_number']!=reference:raise ValueError('Bridge and bank reservation references conflict')
                    continue
                c.execute("UPDATE public.envelope_batch_status_for_cash SET funds_blocked_with_bank='FUNDS_BLOCK_SUCCESS',funds_blocked_reference_number=%s,funds_blocked_latest_error_code=NULL,funds_blocked_latest_timestamp=%s,funds_blocked_attempts=GREATEST(funds_blocked_attempts,1),updated_at=%s WHERE id=%s",(reference,stamp,stamp,cash['id']));repaired_blocks+=1
        # Reservation repair precedes dispatch repair, independently of the
        # database order in which the remote acknowledgement receipts arrived.
        b.execute('SELECT initiate_payment_payloads FROM public.initiate_payment_batch_requests');batches={}
        for row in b.fetchall():
            payloads=row['initiate_payment_payloads'];payloads=json.loads(payloads) if isinstance(payloads,str) else payloads;digest=hashlib.sha256(json.dumps(payloads,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest();batches.setdefault(digest,[]).append(payloads)
        for receipt in receipts:
            key=receipt['request_key']
            if receipt['operation']!='initiate_payment' or not key.startswith('bridge:dispatch:'):continue
            identifier=key.removeprefix('bridge:dispatch:');c.execute('SELECT * FROM public.disbursement_batch_control WHERE id=%s FOR UPDATE',(identifier,));batch=c.fetchone()
            if batch is None:raise ValueError('Retained bank dispatch references a missing bridge batch')
            if batch['sponsor_bank_dispatch_status']=='PROCESSED':continue
            matches=batches.get(receipt['payload_sha256'],[])
            if len(matches)!=1:raise ValueError('Unambiguous durable bank batch required before repairing bridge acknowledgement')
            payloads=matches[0];c.execute('SELECT * FROM public.disbursement_envelopes WHERE id=%s',(batch['disbursement_envelope_id'],));envelope=c.fetchone();configuration=account_for_envelope(envelope)
            if envelope['benefit_type']=='CASH_DIGITAL':c.execute("SELECT id,disbursement_quantity AS quantity FROM public.disbursements WHERE disbursement_batch_control_id=%s AND cancellation_status<>'CANCELLED' AND disbursement_quantity>0",(identifier,))
            elif envelope['benefit_type']=='CASH_PHYSICAL':c.execute('SELECT id,total_quantity AS quantity FROM public.disbursement_batch_control_geo WHERE disbursement_batch_control_id=%s AND total_quantity>0',(identifier,))
            else:raise ValueError('Non-cash batch cannot own a bank dispatch receipt')
            expected={row['id']:row['quantity'] for row in c.fetchall()};actual={row['payment_reference_number']:row for row in payloads}
            if len(actual)!=len(payloads) or set(actual)!=set(expected):raise ValueError('Bank dispatch payment references differ from bridge instructions')
            c.execute('SELECT * FROM public.envelope_batch_status_for_cash WHERE disbursement_envelope_id=%s FOR UPDATE',(envelope['id'],));cash=c.fetchone()
            if cash is None:raise ValueError('Bank dispatch envelope state missing')
            for reference,payload in actual.items():
                if payload['remitting_account']!=configuration['program_account_number'] or payload['remitting_account_currency']!=envelope['measurement_unit'] or Decimal(str(payload['payment_amount']))!=Decimal(str(expected[reference])) or payload['funds_blocked_reference_number']!=cash['funds_blocked_reference_number']:raise ValueError('Bank dispatch amount, account or reservation differs')
            stamp=receipt['created_at'].astimezone(timezone.utc).replace(tzinfo=None)
            c.execute("UPDATE public.disbursement_batch_control SET sponsor_bank_dispatch_status='PROCESSED',sponsor_bank_dispatch_latest_error_code=NULL,sponsor_bank_dispatch_timestamp=%s,sponsor_bank_dispatch_attempts=GREATEST(sponsor_bank_dispatch_attempts,1),updated_at=%s WHERE id=%s",(stamp,stamp,identifier));c.execute('UPDATE public.envelope_batch_status_for_cash SET number_of_disbursements_shipped=number_of_disbursements_shipped+%s,updated_at=%s WHERE id=%s',(len(payloads),stamp,cash['id']));repaired_dispatches+=1
    native_bridge.commit()
    return {'repaired_reservations':repaired_blocks,'repaired_dispatches':repaired_dispatches}
