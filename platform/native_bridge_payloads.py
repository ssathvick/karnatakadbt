"""Native payment and notification projections for the retained bank protocol."""
from native_bridge_business import now


def payment_payloads(worker,c,envelope,batch,cash,configuration,*,agency_account):
    digital=envelope['benefit_type']=='CASH_DIGITAL'
    if envelope['benefit_type'] not in {'CASH_DIGITAL','CASH_PHYSICAL'}:raise ValueError('Cash dispatch only')
    rows=worker.rows(c,'disbursements' if digital else 'disbursement_batch_control_geo',disbursement_batch_control_id=batch['id']);payloads=[];zero_count=0
    for row in rows:
        if digital and row['cancellation_status']=='CANCELLED':continue
        quantity=row['disbursement_quantity'] if digital else row['total_quantity']
        if quantity<=0:
            filters={'disbursement_id' if digital else 'disbursement_batch_control_geo_id':row['id']}
            if not worker.rows(c,'disbursement_recons',**filters):
                worker.put(c,'disbursement_recons',disbursement_batch_control_id=batch['id'],disbursement_id=row['id'],disbursement_batch_control_geo_id=None if digital else row['id'],disbursement_envelope_id=envelope['id'],reversal_found=False);zero_count+=1
            continue
        if digital:
            address=worker.one(c,'disbursement_resolution_financial_address',disbursement_id=row['id'])
            account={'number':address['bank_account_number'],'bank':address['bank_code'],'branch':address['branch_code'],'type':address['mapper_resolved_fa_type'],'phone':address['mobile_number'],'email':address['email_address'],'mobile_wallet':address['mobile_wallet_provider'],'email_wallet':address['email_wallet_provider']}
            name=row['beneficiary_name'] or address['mapper_resolved_name'] or 'N/A';beneficiary=row['beneficiary_id'];narrative=row['narrative']
        else:
            account=agency_account(row['agency_id'],envelope);attributes=worker.one(c,'disbursement_batch_control_geo_attributes',id=row['id']);account=dict(account,phone=attributes['agency_admin_phone'],email=attributes['agency_admin_email'],mobile_wallet=None,email_wallet=None)
            name=account['name'];beneficiary=row['agency_id'];narrative='PAYMENT_TO_AGENCY_FOR_PHYSICAL_CASH_DISTRIBUTION'
        payloads.append({'payment_reference_number':row['id'],'remitting_account':configuration['program_account_number'],'remitting_account_currency':envelope['measurement_unit'],'payment_amount':quantity,'funds_blocked_reference_number':cash['funds_blocked_reference_number'],'beneficiary_name':name,'beneficiary_account':account['number'],'beneficiary_account_currency':envelope['measurement_unit'],'beneficiary_account_type':account['type'] or 'BANK_ACCOUNT','beneficiary_bank_code':account['bank'],'beneficiary_branch_code':account['branch'] or '', 'beneficiary_mobile_wallet_provider':account.get('mobile_wallet'),'beneficiary_phone_no':account.get('phone'),'beneficiary_email':account.get('email'),'beneficiary_email_wallet_provider':account.get('email_wallet'),'payment_date':str(envelope['disbursement_schedule_date']),'narrative_1':narrative,'narrative_2':envelope['benefit_program_mnemonic'],'narrative_3':envelope['cycle_code_mnemonic'],'narrative_4':str(beneficiary),'narrative_5':'','narrative_6':''})
    if zero_count:worker.change(c,'envelope_batch_status_for_cash',cash['id'],number_of_disbursements_reconciled=cash['number_of_disbursements_reconciled']+zero_count)
    return payloads


def notification_payload(worker,c,kind,row):
    envelope=worker.one(c,'disbursement_envelopes',id=row['disbursement_envelope_id']);geo=worker.one(c,'disbursement_batch_control_geo',id=row['disbursement_batch_control_geo_id']) if kind=='beneficiary' else row
    attributes=worker.one(c,'disbursement_batch_control_geo_attributes',id=geo['id'])
    payload={'program_mnemonic':envelope['benefit_program_mnemonic'],'program_description':envelope['benefit_program_description'],'target_registry':envelope['target_registry'],'disbursement_cycle_mnemonic':envelope['cycle_code_mnemonic'],'disbursement_date':str(envelope['disbursement_schedule_date']),'benefit_code_id':envelope['benefit_code_id'],'benefit_code_mnemonic':envelope['benefit_code_mnemonic'],'benefit_type':envelope['benefit_type'],'measurement_unit':envelope['measurement_unit'],'benefit_description':envelope['benefit_code_description']}
    if kind!='beneficiary':payload['benefit_code_description']=envelope['benefit_code_description']
    for place in ['warehouse','agency']:
        for field in ['id','mnemonic']:payload[place+'_'+field]=geo[place+'_'+field]
        payload[place+'_name']=attributes[place+'_name']
    for size in ['large','small']:
        for field in ['id','mnemonic']:payload['administrative_zone_'+field+'_'+size]=geo['administrative_zone_'+field+'_'+size]
    if kind=='beneficiary':
        payment=worker.one(c,'disbursements',id=row['disbursement_id']);payload.update(beneficiary_id=row['beneficiary_id'],beneficiary_name=payment['beneficiary_name'],total_quantity=payment['disbursement_quantity']);recipient={'recipient_id':row['beneficiary_id'],'recipient_name':row['beneficiary_name'],'recipient_email':row['beneficiary_email'],'recipient_phone':row['beneficiary_phone']}
    else:
        payload.update(total_quantity=geo['total_quantity'],no_of_bebeficiaries=geo['no_of_beneficiaries']);recipient={'recipient_id':geo[kind+'_id'],'recipient_name':attributes[kind+'_admin_name'],'recipient_email':attributes[kind+'_admin_email'],'recipient_phone':attributes[kind+'_admin_phone']}
        if kind=='agency':payload['beneficiary_entitlements']=[{'beneficiary_id':payment['beneficiary_id'],'beneficiary_name':payment['beneficiary_name'],'total_quantity':payment['disbursement_quantity']} for payment in worker.rows(c,'disbursements',disbursement_batch_control_id=row['disbursement_batch_control_id']) if payment['cancellation_status']!='CANCELLED' and worker.rows(c,'disbursement_resolution_geo_address',disbursement_id=payment['id'],disbursement_batch_control_geo_id=geo['id'])]
    return payload,recipient
