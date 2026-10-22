"""Subject-bound beneficiary history and summaries over native bridge storage."""
from sqlalchemy import MetaData,Table,select,func
from native_bridge_business import NativeBridgeBusiness


class NativeBridgeBeneficiary:
    def __init__(self,engine):
        self.engine=engine;metadata=MetaData()
        self.disbursements=Table('disbursements',metadata,schema='public',autoload_with=engine)
        self.envelopes=Table('disbursement_envelopes',metadata,schema='public',autoload_with=engine)

    def execute(self,operation,request,*,subject):
        # Callers supply the verified token subject, never a payload beneficiary ID.
        if not isinstance(subject,str) or not subject.strip():raise PermissionError('Verified beneficiary subject required')
        if operation not in {'get_all_disbursements','get_disbursement_summary_till_date'}:raise ValueError('Unknown beneficiary operation')
        d,e=self.disbursements,self.envelopes
        joined=d.join(e,e.c.id==d.c.disbursement_envelope_id)
        with self.engine.connect() as c:
            if operation=='get_disbursement_summary_till_date':
                fields=[e.c.benefit_code_mnemonic,e.c.benefit_type,e.c.measurement_unit]
                rows=c.execute(select(*fields,func.sum(d.c.disbursement_quantity).label('total_quantity_received')).select_from(joined).where(d.c.beneficiary_id==subject).group_by(*fields).order_by(*fields)).mappings()
                payload=[dict(row,total_quantity_received=float(row['total_quantity_received'])) for row in rows]
                return NativeBridgeBusiness.response(request,payload,None if payload else 'DISBURSEMENT_SUMMARY_NOT_FOUND')
            pagination=(request.get('request_body') or {}).get('pagination_request') or {}
            page_size=pagination.get('page_size',30);page=pagination.get('current_page',1)
            if type(page_size) is not int or type(page) is not int or not 1<=page_size<=1000 or page<1:raise ValueError('Invalid pagination')
            total=c.scalar(select(func.count()).select_from(d).where(d.c.beneficiary_id==subject))
            # Joining batches by envelope duplicated a payment for every batch.
            # History has one row per actual payment and stable pagination.
            query=select(d.c.id.label('disbursement_id'),d.c.disbursement_envelope_id,e.c.benefit_program_mnemonic.label('program_mnemonic'),e.c.cycle_code_mnemonic,d.c.disbursement_quantity,e.c.benefit_code_mnemonic.label('benefit_code'),e.c.benefit_type,e.c.measurement_unit,e.c.disbursement_schedule_date).select_from(joined).where(d.c.beneficiary_id==subject).order_by(d.c.created_at,d.c.id).offset((page-1)*page_size).limit(page_size)
            payload=[dict(row,agency_mnemonic='AGENCY_PLACEHOLDER') for row in c.execute(query).mappings()]
            response=NativeBridgeBusiness.response(request,payload,None if payload else 'DISBURSEMENT_NOT_FOUND')
            response['response_body']['pagination_response']={'number_of_items':total,'number_of_pages':(total+page_size-1)//page_size}
            return response
