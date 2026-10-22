"""Independent geography and reference-data business engine.

Uses only SQLAlchemy and the four documented storage tables. No legacy service
or ERP implementation is imported. Transactions serialize hierarchy mutations,
including application-level constraints absent from the original database.
"""
import uuid
from sqlalchemy import MetaData,Table,select,delete,func,text,and_,or_,not_,true

TABLES=('g2p_geo_levels','g2p_geo_level_values','g2p_attributes','g2p_attribute_values')
VIEWS={TABLES[0]:('level_id','level_mnemonic','parent_level_id'),
       TABLES[1]:('level_value_id','level_id','level_value_mnemonic','parent_level_value_id'),
       TABLES[2]:('attribute_id','attribute_code','attribute_display','is_hierarchical'),
       TABLES[3]:('value_id','attribute_id','value_code','value_display','parent_value_id','sort_order')}

class MasterDataError(Exception):
    def __init__(self,family,status,message):
        self.code='G2P-'+family+'-'+str(status);self.message=message;super().__init__(message)

class NativeMasterData:
    def __init__(self,engine,schema='public'):
        self.engine=engine;meta=MetaData(schema=schema)
        self.tables={name:Table(name,meta,autoload_with=engine) for name in TABLES}
        self.level,self.geo,self.attribute,self.value=(self.tables[name] for name in TABLES)
    @staticmethod
    def clean(value):return value.strip() or None if isinstance(value,str) else value
    @staticmethod
    def view(table,row):return {key:row[key] for key in VIEWS[table.name]}
    def fail(self,table,status,message):raise MasterDataError('GEO' if table in (self.level,self.geo) else 'ATTR',status,message)
    def require(self,c,table,**keys):
        rows=c.execute(select(table).where(*(table.c[k]==v for k,v in keys.items()))).mappings().all()
        if not rows:self.fail(table,404,'Requested record not found')
        if len(rows)>1:self.fail(table,409,'Composite identity is required for this value')
        return dict(rows[0])
    def exists(self,c,table,*conditions):return bool(c.execute(select(func.count()).select_from(table).where(*conditions)).scalar_one())
    def policy(self,policies,target,context=None):
        """Compile scoped cross-dimension policies; malformed rules fail closed."""
        dimension,values,dimension_id,code,value_code=(self.level,self.geo,'level_id','level_mnemonic','level_value_mnemonic') if target=='GEO' else (self.attribute,self.value,'attribute_id','attribute_code','value_code')
        nodes=0
        def expression(node,depth=0):
            nonlocal nodes
            nodes+=1
            if nodes>512 or depth>32 or not isinstance(node,dict):raise ValueError('Invalid data policy')
            if node.get('type')=='GROUP' or 'children' in node:
                children=node.get('children');operator=node.get('operator','AND')
                if not isinstance(children,list) or not children or operator not in {'AND','OR','NOT'}:raise ValueError('Invalid data policy group')
                compiled=[expression(child,depth+1) for child in children];compiled=[item for item in compiled if item is not None]
                if not compiled:return None
                if operator=='NOT':return not_(and_(*compiled))
                return or_(*compiled) if operator=='OR' or not context else and_(*compiled)
            if node.get('type')!='CONDITION' or not isinstance(node.get('field_id'),str):raise ValueError('Invalid data policy condition')
            if context and node['field_id']!=context:return None
            column=values.c[value_code];operator=node.get('operator') or 'eq';value=node.get('value');items=node.get('values')
            if operator in {'eq','neq'} and value is not None:term=column==value if operator=='eq' else column!=value
            elif operator in {'in','nin'} and isinstance(items,list) and 0<len(items)<=1000:term=column.in_(items) if operator=='in' else column.not_in(items)
            elif operator in {'contains','startsWith','endsWith'} and isinstance(value,str):term=column.ilike(('%' if operator!='startsWith' else '')+value+('%' if operator!='endsWith' else ''))
            else:raise ValueError('Unsupported data policy operator')
            return and_(values.c[dimension_id].in_(select(dimension.c[dimension_id]).where(dimension.c[code]==node['field_id'])),term)
        allow=[];deny=[]
        for rule in policies:
            if rule.get('policy_target')!=target:continue
            if rule.get('policy_type') not in {'ALLOW','DISALLOW'}:raise ValueError('Invalid policy effect')
            clause=expression(rule.get('policy_filter_expression'))
            if clause is not None:(allow if rule['policy_type']=='ALLOW' else deny).append(clause)
        return and_(*( ([or_(*allow)] if allow else [])+([not_(or_(*deny))] if deny else []) )) if allow or deny else true()
    def execute(self,path,payload,*,policies=(),pagination=None):
        operation=path.rsplit('/',1)[-1];p=dict(payload)
        with self.engine.begin() as c:
            if not operation.startswith('get_'):
                c.execute(text("SELECT pg_advisory_xact_lock(hashtextextended('karnatakadbt:master-data-business:v1',0))"))
            if operation=='get_all_geo_levels':return [self.view(self.level,row) for row in c.execute(select(self.level)).mappings()],None
            if operation=='get_all_attributes':return {'attributes':[self.view(self.attribute,row) for row in c.execute(select(self.attribute)).mappings()]},None
            if operation=='get_geo_level_values':
                level=c.execute(select(self.level).where(self.level.c.level_id==p['level_id'])).mappings().first()
                if not level:level=c.execute(select(self.level).where(self.level.c.level_mnemonic==p['level_id'])).mappings().first()
                if not level:return [],None
                q=select(self.geo).where(self.geo.c.level_id==level['level_id'])
                parent=p.get('parent_level_value_id')
                if parent:q=q.where(self.geo.c.parent_level_value_id==parent)
                elif not level['parent_level_id']:q=q.where(or_(self.geo.c.parent_level_value_id.is_(None),self.geo.c.parent_level_value_id.in_(['','NULL'])))
                q=q.where(self.policy(policies,'GEO',level['level_mnemonic']))
                return [self.view(self.geo,row) for row in c.execute(q).mappings()],None
            if operation=='get_attribute_values':
                q=select(self.value);identifier=p.get('attribute_id');context=None
                if identifier:
                    q=q.where(self.value.c.attribute_id==identifier)
                    context=c.execute(select(self.attribute.c.attribute_code).where(self.attribute.c.attribute_id==identifier)).scalar_one_or_none()
                q=q.where(self.policy(policies,'ATTRIBUTE',context));total=c.execute(select(func.count()).select_from(q.subquery())).scalar_one()
                pagination=pagination or {};size=pagination.get('page_size') or 1000;page=pagination.get('current_page') or 1
                if not 1<=size<=10000 or page<1:self.fail(self.value,400,'Invalid pagination')
                rows=c.execute(q.order_by(self.value.c.attribute_id,self.value.c.sort_order).limit(size).offset((page-1)*size)).mappings()
                return {'attribute_values':[self.view(self.value,row) for row in rows],'total':total},{'number_of_items':total,'number_of_pages':(total+size-1)//size}
            if operation.endswith('geo_level_value'):table=self.geo;identity='level_value_id'
            elif operation.endswith('geo_level'):table=self.level;identity='level_id'
            elif operation.endswith('attribute_value'):table=self.value;identity='value_id'
            elif operation.endswith('attribute'):table=self.attribute;identity='attribute_id'
            else:raise ValueError('Unknown master-data operation')
            verb=operation.split('_',1)[0];keys={identity:p[identity]} if verb!='add' else {}
            if table is self.value and p.get('attribute_id') and verb!='add':keys['attribute_id']=p['attribute_id']
            old=self.require(c,table,**keys) if verb!='add' else None
            if verb=='delete':
                if table is self.level:
                    if self.exists(c,self.level,self.level.c.parent_level_id==p[identity]) or self.exists(c,self.geo,self.geo.c.level_id==p[identity]):self.fail(table,409,'Cannot delete a level with child levels or values')
                elif table is self.geo:
                    descendants=[];frontier=[p[identity]];seen=set(frontier)
                    while frontier:
                        found=c.execute(select(self.geo.c.level_value_id).where(self.geo.c.parent_level_value_id.in_(frontier))).scalars().all();frontier=[item for item in found if item not in seen];seen.update(frontier);descendants.extend(frontier)
                    if descendants and not p.get('cascade'):self.fail(table,409,'Cannot delete a value with descendants')
                    if descendants:c.execute(delete(table).where(table.c[identity].in_(descendants)))
                elif table is self.attribute:
                    children=self.exists(c,self.value,self.value.c.attribute_id==p[identity])
                    if children and not p.get('cascade'):self.fail(table,409,'Cannot delete an attribute with values')
                    if children:c.execute(delete(self.value).where(self.value.c.attribute_id==p[identity]))
                elif self.exists(c,self.value,self.value.c.attribute_id==old['attribute_id'],self.value.c.parent_value_id==old['value_id']):self.fail(table,409,'Cannot delete an attribute value with children')
                exact={column.name:old[column.name] for column in table.primary_key};c.execute(delete(table).where(*(table.c[k]==v for k,v in exact.items())))
                result={identity:old[identity]}
                if table is self.value:result['attribute_id']=old['attribute_id']
                return result,None
            fields={key:self.clean(value) for key,value in p.items() if key in VIEWS[table.name] and key!=identity}
            if verb=='update' and not fields:self.fail(table,400,'At least one field must be provided to update')
            value={**(old or {}),**fields}
            for key in VIEWS[table.name]:value.setdefault(key,None)
            if verb=='add':value[identity]=str(uuid.uuid4())
            required={self.level:('level_mnemonic',),self.geo:('level_id','level_value_mnemonic'),self.attribute:('attribute_code','attribute_display'),self.value:('attribute_id','value_code','value_display')}[table]
            if any(not value.get(key) for key in required):self.fail(table,400,'Required field cannot be empty')
            if table is self.level:
                parent=value.get('parent_level_id')
                if parent:
                    self.require(c,self.level,level_id=parent)
                    if parent==value[identity]:self.fail(table,400,'Level cannot be its own parent')
                    seen={value[identity]};cursor=parent
                    while cursor:
                        if cursor in seen:self.fail(table,400,'Geographic hierarchy cycle')
                        seen.add(cursor);cursor=self.require(c,self.level,level_id=cursor)['parent_level_id']
                unique=[table.c.level_mnemonic==value['level_mnemonic'],table.c.parent_level_id==parent]
            elif table is self.geo:
                self.require(c,self.level,level_id=value['level_id']);parent=value.get('parent_level_value_id')
                if parent:
                    self.require(c,self.geo,level_value_id=parent)
                    seen={value[identity]};cursor=parent
                    while cursor:
                        if cursor in seen:self.fail(table,400,'Geographic value hierarchy cycle')
                        seen.add(cursor);cursor=self.require(c,self.geo,level_value_id=cursor)['parent_level_value_id']
                unique=[table.c.level_id==value['level_id'],table.c.level_value_mnemonic==value['level_value_mnemonic'],table.c.parent_level_value_id==parent]
            elif table is self.attribute:
                value['is_hierarchical']=bool(value.get('is_hierarchical'))
                if not value['is_hierarchical'] and self.exists(c,self.value,self.value.c.attribute_id==value[identity],self.value.c.parent_value_id.is_not(None)):self.fail(table,409,'Existing values require a hierarchical attribute')
                unique=[table.c.attribute_code==value['attribute_code']]
            else:
                attribute=self.require(c,self.attribute,attribute_id=value['attribute_id']);parent=value.get('parent_value_id')
                if parent:
                    if not attribute['is_hierarchical']:self.fail(table,400,'Parent values require a hierarchical attribute')
                    self.require(c,self.value,attribute_id=value['attribute_id'],value_id=parent)
                    seen={value[identity]};cursor=parent
                    while cursor:
                        if cursor in seen:self.fail(table,400,'Attribute value hierarchy cycle')
                        seen.add(cursor);cursor=self.require(c,self.value,attribute_id=value['attribute_id'],value_id=cursor)['parent_value_id']
                if verb=='add' and value.get('sort_order') is None:value['sort_order']=0
                unique=[table.c.attribute_id==value['attribute_id'],table.c.value_code==value['value_code']]
            if old:unique.append(table.c[identity]!=old[identity])
            if self.exists(c,table,*unique):self.fail(table,409,'Code or mnemonic already exists in this scope')
            values={key:value[key] for key in VIEWS[table.name] if key in value}
            if old:
                exact={column.name:old[column.name] for column in table.primary_key};c.execute(table.update().where(*(table.c[k]==v for k,v in exact.items())).values(**values))
            else:c.execute(table.insert().values(**values))
            return self.view(table,value),None
