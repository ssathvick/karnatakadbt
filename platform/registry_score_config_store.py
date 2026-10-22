"""Custom score-definition and contributing-attribute configuration storage."""
import uuid
from sqlalchemy import MetaData,Table,Column,String,JSON,Integer,select,insert,update,delete,func
from registry_ingestion_config_store import RegistryIngestionConfigStore
from registry_metadata_store import RegistryError

metadata=MetaData()
scores=Table('console_score_configuration',metadata,Column('kind',String,primary_key=True),Column('id',String,primary_key=True),Column('data',JSON,nullable=False),Column('position',Integer,nullable=False))
KEYS={'definition':'score_definition_id','attribute':'contributing_attribute_id','queue':'queue_id'}
SUPPORTED_PATHS=frozenset('/computation-score/'+name for name in ['get_score_definitions','create_score_definition','update_score_definition','delete_score_definition','get_score_contributing_attributes','create_score_contributing_attribute','update_score_contributing_attribute','delete_score_contributing_attribute'])

class RegistryScoreConfigStore(RegistryIngestionConfigStore):
    def initialize(self):super().initialize();metadata.create_all(self.engine)
    def score_rows(self,c,kind):return [dict(row) for row in c.execute(select(scores.c.data).where(scores.c.kind==kind).order_by(scores.c.position)).scalars()]
    def seed_scores(self,dataset):
        with self.write() as c:
            if c.execute(select(scores.c.id)).first():raise RuntimeError('Refusing to overwrite scoring metadata')
            for kind,rows in dataset.items():
                for position,row in enumerate(rows):c.execute(insert(scores).values(kind=kind,id=row[KEYS[kind]],data=row,position=position))
    def put_score(self,c,kind,row,new=False):
        key=row[KEYS[kind]]
        if new:
            position=(c.execute(select(func.max(scores.c.position))).scalar_one() or 0)+1
            c.execute(insert(scores).values(kind=kind,id=key,data=row,position=position))
        else:c.execute(update(scores).where(scores.c.kind==kind,scores.c.id==key).values(data=row))
    def score(self,c,kind,key):
        row=c.execute(select(scores.c.data).where(scores.c.kind==kind,scores.c.id==key)).scalar_one_or_none()
        if row is None:self.fail('SCORE_DEFINITION_NOT_FOUND' if kind=='definition' else 'SCORE_CONTRIBUTING_ATTRIBUTE_NOT_FOUND',('Score definition not found: ' if kind=='definition' else 'Score contributing attribute not found: ')+str(key))
        return dict(row)
    def score_register(self,c,mnemonic):
        if not any(row['register_mnemonic']==mnemonic and row['register_purpose']=='REGISTER' for row in self.definitions(c)):
            self.fail('SCORE_DEFINITION_NOT_ALLOWED_FOR_REGISTER_PURPOSE','Score definitions are only allowed for registers with register_purpose = REGISTER')
    def definition_wire(self,row):return self.models.model('ScoreDefinitionData').model_validate(row).model_dump(mode='json')
    def attribute_wire(self,row):return self.models.model('ScoreContributingAttributeData').model_validate(row).model_dump(mode='json')
    def attribute_name(self,c,row,exclude=None):
        if any(other['register_mnemonic']==row['register_mnemonic'] and other['score_type']==row['score_type'] and other['attribute_name']==row['attribute_name'] and other['contributing_attribute_id']!=exclude for other in self.score_rows(c,'attribute')):
            self.fail('SCORE_DEFINITION_CONTRIBUTING_ATTRIBUTES_INVALID','Contributing attribute already exists for name: '+row['attribute_name'])
    def execute_request(self,path,p,actor,pagination=None):
        if path not in SUPPORTED_PATHS:return super().execute_request(path,p,actor,pagination)
        operation=path.rsplit('/',1)[-1];reading=operation.startswith('get_')
        if reading and pagination is None:raise RegistryError('SYS-ERR-001')
        with (self.engine.connect() if reading else self.write()) as c:
            if operation=='get_score_definitions':
                if pagination is None:raise RegistryError('SYS-ERR-001')
                register=self.definition(c,'register',p['register_id'])
                rows=[row for row in self.score_rows(c,'definition') if register and row['register_mnemonic']==register['register_mnemonic']]
                rows.sort(key=lambda row:row['score_type']);rows,page=self.page(rows,pagination)
                return {'score_definitions':[self.definition_wire(row) for row in rows]},page
            if operation=='create_score_definition':
                register=self.definition(c,'register',p['register_id'])
                if not register or register['register_purpose']!='REGISTER':self.fail('SCORE_DEFINITION_NOT_ALLOWED_FOR_REGISTER_PURPOSE','Score definitions are only allowed for registers with register_purpose = REGISTER')
                row=next((row for row in self.score_rows(c,'definition') if row['register_mnemonic']==register['register_mnemonic'] and row['score_type']==p['score_type']),None)
                new=row is None
                if new:row={'score_definition_id':str(uuid.uuid4()),'register_mnemonic':register['register_mnemonic'],'score_type':p['score_type']}
                row['is_enabled']=True;self.put_score(c,'definition',row,new);key=row['score_definition_id'];result={'score_definition':self.definition_wire(row)}
            elif operation in {'update_score_definition','delete_score_definition','get_score_contributing_attributes','create_score_contributing_attribute'}:
                definition=self.score(c,'definition',p['score_definition_id']);self.score_register(c,definition['register_mnemonic']);key=definition['score_definition_id']
                if operation=='update_score_definition':
                    if p.get('is_enabled') is not None:definition['is_enabled']=p['is_enabled']
                    self.put_score(c,'definition',definition);result={'score_definition':self.definition_wire(definition)}
                elif operation=='delete_score_definition':
                    for kind in ['attribute','queue']:
                        for row in self.score_rows(c,kind):
                            if (kind=='queue' and row['score_definition_id']==key) or (kind=='attribute' and row['register_mnemonic']==definition['register_mnemonic'] and row['score_type']==definition['score_type']):
                                c.execute(delete(scores).where(scores.c.kind==kind,scores.c.id==row[KEYS[kind]]))
                    c.execute(delete(scores).where(scores.c.kind=='definition',scores.c.id==key));result={'score_definition_id':key}
                elif operation=='get_score_contributing_attributes':
                    if pagination is None:raise RegistryError('SYS-ERR-001')
                    rows=[row for row in self.score_rows(c,'attribute') if row['register_mnemonic']==definition['register_mnemonic'] and row['score_type']==definition['score_type']]
                    rows.sort(key=lambda row:row['attribute_name']);rows,page=self.page(rows,pagination)
                    return {'contributing_attributes':[self.attribute_wire(row) for row in rows]},page
                else:
                    if not p['attribute_name'].strip():self.fail('SCORE_DEFINITION_CONTRIBUTING_ATTRIBUTES_INVALID','attribute_name must be non-empty')
                    row={field:p.get(field) for field in ['attribute_name','attribute_computation_required','attribute_computation_value','attribute_weightage']}
                    row.update(contributing_attribute_id=str(uuid.uuid4()),register_mnemonic=definition['register_mnemonic'],score_type=definition['score_type'],attribute_name=p['attribute_name'].strip())
                    self.attribute_name(c,row);self.put_score(c,'attribute',row,True);key=row['contributing_attribute_id'];result={'contributing_attribute':self.attribute_wire(row)}
            else:
                row=self.score(c,'attribute',p['contributing_attribute_id']);self.score_register(c,row['register_mnemonic']);key=row['contributing_attribute_id']
                if operation=='delete_score_contributing_attribute':
                    c.execute(delete(scores).where(scores.c.kind=='attribute',scores.c.id==key));result={'contributing_attribute_id':key}
                elif operation=='update_score_contributing_attribute':
                    fields=['attribute_name','attribute_computation_required','attribute_computation_value','attribute_weightage']
                    if all(p.get(field) is None for field in fields):self.fail('SCORE_VALIDATION_ERROR','At least one field must be provided to update')
                    if p.get('attribute_name') is not None:
                        row['attribute_name']=p['attribute_name'].strip()
                        if not row['attribute_name']:self.fail('SCORE_DEFINITION_CONTRIBUTING_ATTRIBUTES_INVALID','attribute_name cannot be empty')
                        self.attribute_name(c,row,key)
                    row.update({field:p[field] for field in fields if field!='attribute_name' and p.get(field) is not None})
                    self.put_score(c,'attribute',row);result={'contributing_attribute':self.attribute_wire(row)}
                else:raise KeyError(path)
            self.record(c,actor,operation,key,result)
            return result,None
