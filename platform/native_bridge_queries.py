"""Read-only bridge reconciliation and batch status, independent of legacy code."""
import json
from pathlib import Path
from sqlalchemy import MetaData,Table,select
from native_bridge_business import NativeBridgeBusiness,BridgeBusinessError


class NativeBridgeQueries:
    def __init__(self,engine):
        self.engine=engine
        metadata=MetaData()
        self.tables={name:Table(name,metadata,schema='public',autoload_with=engine) for name in ['disbursement_recons','disbursement_error_recons','disbursement_batch_control','disbursement_batch_control_geo','disbursement_envelopes']}
        for name in ['envelope_control','envelope_batch_status_for_cash','disbursement_resolution_geo_address']:self.tables[name]=Table(name,metadata,schema='public',autoload_with=engine)
        self.schemas=json.loads(Path(__file__).with_name('native_bridge_partner_contract.json').read_text())['components']['schemas']

    def project(self,schema,row,**overrides):
        values=dict(row);values.update(overrides)
        return {key:values.get(key) for key in self.schemas[schema]['properties']}

    def rows(self,c,kind,**filters):
        table=self.tables[kind];query=select(table)
        for key,value in filters.items():query=query.where(table.c[key]==value)
        return list(c.execute(query).mappings())

    def execute(self,operation,request):
        methods={'get_disbursement_status':self.status,'get_disbursement_batch_control':self.batch,'get_disbursement_envelope_status':self.envelope}
        if operation not in methods:raise ValueError('Unknown bridge query')
        try:
            with self.engine.connect() as c:
                result=methods[operation](c,request['request_body']['request_payload'])
        except BridgeBusinessError as error:return NativeBridgeBusiness.response(request,None,error.code)
        return NativeBridgeBusiness.response(request,result)

    def status(self,c,identifiers):
        result=[]
        for identifier in identifiers:
            recons=self.rows(c,'disbursement_recons',disbursement_id=identifier)
            errors=[]
            # reconciliation_id is the payment reference, including errors
            # recorded before any successful reconciliation row exists.
            errors.extend(self.project('DisbursementErrorReconPayload',row,disbursement_id=identifier) for row in self.rows(c,'disbursement_error_recons',reconciliation_id=identifier))
            result.append({'disbursement_id':identifier,'disbursement_recon_records':{'disbursement_recon_payloads':[self.project('DisbursementReconPayload',row,bank_disbursement_batch_id=row['disbursement_batch_control_id']) for row in recons],'disbursement_error_recon_payloads':errors}})
        return result

    def batch(self,c,identifier):
        rows=self.rows(c,'disbursement_batch_control',id=identifier)
        if not rows:return None
        row=rows[0]
        envelope=self.rows(c,'disbursement_envelopes',id=row['disbursement_envelope_id'])[0]
        geos=[self.project('DisbursementBatchControlGeoPayload',geo,disbursement_batch_control_geo_id=geo['id']) for geo in self.rows(c,'disbursement_batch_control_geo',disbursement_batch_control_id=identifier)]
        values=dict(envelope);values.update(row)
        return self.project('DisbursementBatchControlPayload',values,disbursement_batch_control_id=identifier,disbursement_cycle_code_mnemonic=envelope['cycle_code_mnemonic'],disbursement_batch_control_geos=geos)

    def envelope(self,c,identifier):
        rows=self.rows(c,'disbursement_envelopes',id=identifier)
        if not rows:raise BridgeBusinessError('DISBURSEMENT_ENVELOPE_NOT_FOUND')
        row=rows[0];controls=self.rows(c,'envelope_control',disbursement_envelope_id=identifier);control=controls[0] if controls else {}
        cash_rows=self.rows(c,'envelope_batch_status_for_cash',disbursement_envelope_id=identifier) if row['benefit_type'] in {'CASH_DIGITAL','CASH_PHYSICAL'} else []
        cash=cash_rows[0] if cash_rows else {};digital=row['benefit_type']=='CASH_DIGITAL'
        geos=[] if digital else self.rows(c,'disbursement_batch_control_geo',disbursement_envelope_id=identifier)
        notified=[] if digital else self.rows(c,'disbursement_resolution_geo_address',disbursement_envelope_id=identifier,beneficiary_notification_status='PROCESSED')
        values=dict(row);values.update(cash)
        for key in ['funds_available_attempts','funds_blocked_attempts','number_of_disbursements_shipped','number_of_disbursements_reconciled','number_of_disbursements_reversed']:values[key]=cash.get(key) or 0
        values.update(disbursement_envelope_id=identifier,number_of_beneficiaries_received=row['number_of_beneficiaries'],number_of_beneficiaries_declared=row['number_of_beneficiaries'],number_of_disbursements_declared=row['number_of_disbursements'],number_of_disbursements_received=control.get('number_of_disbursements_received',0),total_disbursement_quantity_declared=row['total_disbursement_quantity'],total_disbursement_quantity_received=control.get('total_disbursement_quantity_received',0),no_of_beneficiaries_notified=len(notified),no_of_pods_received=None,disbursement_batch_control_geos=None if digital else [self.project('DisbursementBatchControlGeoPayload',geo,disbursement_batch_control_geo_id=geo['id']) for geo in geos])
        for kind,plural in [('warehouse','warehouses'),('agency','agencies')]:
            values['no_of_'+plural+'_allocated']=len({geo[kind+'_id'] for geo in geos if geo[kind+'_id'] is not None})
            values['no_of_'+plural+'_notified']=len({geo[kind+'_id'] for geo in geos if geo[kind+'_id'] is not None and geo[kind+'_notification_status']=='PROCESSED'})
        return self.project('DisbursementEnvelopeStatusPayload',values)
