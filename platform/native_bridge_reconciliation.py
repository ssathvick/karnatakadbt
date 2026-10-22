"""Atomic MT940 reconciliation using the retained general-purpose parser."""
from datetime import datetime,time
import mt940
from sqlalchemy import select,or_
from native_bridge_business import now


def at(value):return datetime.combine(value,time()) if value is not None and not isinstance(value,datetime) else value


class NativeReferenceStatement(mt940.tags.Statement):
    # Internal payment references include UUIDs. Preserve them in full instead
    # of truncating to the parser's optional 16-character customer reference.
    pattern=mt940.tags.Statement.pattern.replace('{0,16}','{0,256}')


def reconcile(worker,c,statement,*,account_configuration):
    lob=worker.one(c,'account_statement_lobs',statement_id=statement['statement_id']);tag=NativeReferenceStatement();parsed=mt940.models.Transactions(processors={'pre_statement':[mt940.processors.add_currency_pre_processor('')]},tags={tag.id:tag})
    parsed.parse(lob['statement_lob']);account=parsed.data.get('account_identification','')
    configuration=account_configuration(account)
    if not configuration or configuration.get('sponsor_bank_code')!='EXAMPLE_BANK':raise ValueError('Configured statement account and bank parser required')
    header={'statement_number':parsed.data.get('statement_number',''),'sequence_number':parsed.data.get('sequence_number','')};worker.change(c,'account_statements',statement['id'],account_number=account,reference_number=parsed.data.get('transaction_reference',''),**header)
    # Serialize statements for the same account; counters and reconciliation
    # records commit together, including debit and reversal in one statement.
    from sqlalchemy import text
    c.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':'kdbt-bridge-recon-account:'+account})
    transactions=list(parsed)
    ordered=[(index,tx) for index,tx in enumerate(transactions,1) if tx.data['status']=='D']+[(index,tx) for index,tx in enumerate(transactions,1) if tx.data['status']=='RD']
    for index,transaction in ordered:
        data=transaction.data;reference=data.get('customer_reference','');debit=data['status']=='D';details=(data.get('transaction_details') or '').split('\n')
        payment_rows=worker.rows(c,'disbursements',id=reference);geo_rows=[] if payment_rows else worker.rows(c,'disbursement_batch_control_geo',id=reference);target=(payment_rows or geo_rows or [None])[0]
        table=worker.tables['disbursement_recons'];existing=c.execute(select(table).where(or_(table.c.disbursement_id==reference,table.c.disbursement_batch_control_geo_id==reference)).with_for_update()).mappings().first()
        reason='INVALID_RECONCILIATION_ID' if target is None else 'DUPLICATE_DISBURSEMENT' if debit and existing else 'INVALID_REVERSAL' if not debit and (not existing or existing['reversal_found']) else None
        if reason:
            worker.put(c,'disbursement_error_recons',statement_id=statement['statement_id'],statement_number=header['statement_number'],statement_sequence=header['sequence_number'],entry_sequence=str(index),entry_date=at(data.get('entry_date')),value_date=at(data.get('date')),error_reason=reason,reconciliation_id=reference,bank_reference_number=data.get('bank_reference'))
            continue
        # Never reconcile another programme's payment from this account.
        envelope=worker.one(c,'disbursement_envelopes',id=target['disbursement_envelope_id']);sponsor=worker.adapters.sponsor(envelope)
        if sponsor['program_account_number']!=account:raise ValueError('Statement account does not own payment programme')
        cash=worker.one(c,'envelope_batch_status_for_cash',locked=True,disbursement_envelope_id=envelope['id'])
        if debit:
            worker.put(c,'disbursement_recons',disbursement_batch_control_id=target['disbursement_batch_control_id'],disbursement_id=reference,disbursement_batch_control_geo_id=reference if geo_rows else None,disbursement_envelope_id=envelope['id'],beneficiary_name_from_bank=details[3] if len(details)>3 else None,remittance_reference_number=data.get('bank_reference'),remittance_statement_id=statement['statement_id'],remittance_statement_number=header['statement_number'],remittance_statement_sequence=header['sequence_number'],remittance_entry_sequence=str(index),remittance_entry_date=at(data.get('entry_date')),remittance_value_date=at(data.get('date')),reversal_found=False)
            worker.change(c,'envelope_batch_status_for_cash',cash['id'],number_of_disbursements_reconciled=cash['number_of_disbursements_reconciled']+1)
        else:
            worker.change(c,'disbursement_recons',existing['id'],reversal_found=True,reversal_statement_id=statement['statement_id'],reversal_statement_number=header['statement_number'],reversal_statement_sequence=header['sequence_number'],reversal_entry_sequence=str(index),reversal_entry_date=at(data.get('entry_date')),reversal_value_date=at(data.get('date')),reversal_reason=details[-1] if details else None)
            worker.change(c,'envelope_batch_status_for_cash',cash['id'],number_of_disbursements_reversed=cash['number_of_disbursements_reversed']+1)
    worker.change(c,'account_statements',statement['id'],statement_process_status='PROCESSED')
