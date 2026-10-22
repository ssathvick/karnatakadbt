"""Custom completion, score-history and pending-request status operations."""
import datetime
from sqlalchemy import select,func
from registry_row_store import RegistryRowStore,rows

SUPPORTED_PATHS=frozenset(['/completion-score/'+name for name in ['get_ideal_completion_score_for_register','get_ideal_completion_score_for_section','get_computed_completion_score_for_section','get_computed_completion_score_for_record']]+['/register-data/get_scores','/register-data/get_score_history','/registry-config/get_number_of_requests_pending','/registry-config/get_earliest_pending_change_request'])

class RegistryStatusStore(RegistryRowStore):
    def ideal(self,c,register):
        return sum((section.get('section_weightage') or 0.0) for section in self.rows(c,'section') if section['register_id']==register and (section['section_register_id']==register or section['is_list']))
    def completion_wire(self,c,row):
        section=next((section for section in self.rows(c,'section') if section['section_id']==row['section_id']),None)
        return {'register_id':row['register_id'],'internal_record_id':row['internal_record_id'],'section_id':row['section_id'],'computed_section_completion_score':row['computed_section_completion_score'],'section_weightage':(section.get('section_weightage') if section else 0.0) or 0.0,'computed_timestamp':row.get('computed_timestamp')}
    def datetime_string(self,value):return str(datetime.datetime.fromisoformat(value.replace('Z','+00:00'))) if value else None
    def execute_request(self,path,p,actor,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_request(path,p,actor,pagination)
        op=path.rsplit('/',1)[-1]
        with self.engine.connect() as c:
            if op=='get_ideal_completion_score_for_register':return {'register_id':p['register_id'],'ideal_completion_score':self.ideal(c,p['register_id'])},None
            if op=='get_ideal_completion_score_for_section':
                section=next((row for row in self.rows(c,'section') if row['section_id']==p['section_id']),None)
                if section is None:self.fail('SECTION_NOT_FOUND')
                return {'section_id':p['section_id'],'section_weightage':section.get('section_weightage') or 0.0},None
            if op in {'get_computed_completion_score_for_section','get_computed_completion_score_for_record'}:
                filters={'register_id':p['register_id'],'record_id':p['internal_record_id']}
                if op.endswith('_for_section'):filters['section_id']=p['section_id']
                values=self.state_rows(c,'completion',**filters)
                if op.endswith('_for_section'):
                    if not values:self.fail('COMPLETION_SCORE_NOT_FOUND')
                    return self.completion_wire(c,values[0]),None
                return {'register_id':p['register_id'],'internal_record_id':p['internal_record_id'],'section_scores':[self.completion_wire(c,row) for row in values],'actual_score':sum(row['computed_section_completion_score'] or 0.0 for row in values),'ideal_score':self.ideal(c,p['register_id'])},None
            if op in {'get_scores','get_score_history'}:
                kind='score' if op=='get_scores' else 'score-history'
                query=select(rows.c.data).where(rows.c.kind==kind,rows.c.link_id==p['link_internal_record_id'])
                if op=='get_score_history':query=query.where(rows.c.data['score_type'].astext==p['score_type'])
                output=[]
                for row in c.execute(query.order_by(rows.c.sequence)).scalars():
                    item={key:row.get(key) for key in ['computed_score','triggered_by_cr_id','triggered_by_submission_id']};item['computed_at']=self.datetime_string(row.get('computed_at'))
                    if op=='get_scores':item['score_type']=row['score_type']
                    output.append(item)
                return {'scores' if op=='get_scores' else 'history':output},None
            pending=rows.c.kind=='change';status=rows.c.status=='PENDING'
            if op=='get_number_of_requests_pending':return {'number_of_requests_pending':c.execute(select(func.count()).select_from(rows).where(pending,status)).scalar_one()},None
            first=c.execute(select(rows.c.data).where(pending,status).order_by(rows.c.at.asc()).limit(1)).scalar_one_or_none()
            if first is None:return self.models.model('EarliestPendingChangeRequestData').model_validate({}).model_dump(mode='json'),None
            fields=self.models.definitions['EarliestPendingChangeRequestData']['properties'];result={key:first.get(key) for key in fields};result['created_at']=self.datetime_string(first.get('created_at'))
            key=self.row_key('change-payload',{'change_request_id':first['change_request_id']})
            payload=c.execute(select(rows.c.data).where(rows.c.kind=='change-payload',rows.c.key==key)).scalar_one_or_none()
            result['change_payload']=payload['change_payload'] if payload else None
            return result,None
