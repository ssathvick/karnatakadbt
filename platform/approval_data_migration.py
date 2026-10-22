"""Lossless historical approval import with encrypted source and secret preservation."""
import copy,hashlib,json
from cryptography.fernet import Fernet
from sqlalchemy import Table,Column,String,Text,select,insert
from approval_policy_store import metadata,policies,audit
from approval_engine_store import objects

archive=Table('native_approval_source_archive',metadata,Column('table_name',String,primary_key=True),
              Column('ciphertext',Text,nullable=False),Column('sha256',String,nullable=False))

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()

class ApprovalDataMigration:
    def __init__(self,store,key):self.store=store;self.cipher=Fernet(key)

    def source(self):
        with self.store.engine.connect() as connection:
            return {row['table_name']:json.loads(self.cipher.decrypt(row['ciphertext'].encode()))
                    for row in connection.execute(select(archive)).mappings()}

    def secret(self,identifier):
        # Ciphertext is retained in the database; the key stays outside it.
        with self.store.engine.connect() as connection:
            encrypted=connection.scalar(select(archive.c.ciphertext).where(archive.c.table_name=='callback_secret'))
        rows=json.loads(self.cipher.decrypt(encrypted.encode())) if encrypted else []
        row=next((row for row in rows if row['id']==identifier),None)
        return row['secret_hash'] if row and row['status']=='active' else None

    def import_source(self,tables):
        store=self.store
        store.initialize()
        by_policy={};by_stage={row['id']:row for row in tables['approval_stage']}
        for row in tables['approval_policy']:
            value=copy.deepcopy(row);value['stages']=[]
            for original in sorted([item for item in tables['approval_stage'] if item['policy_id']==row['id']],key=lambda item:item['stage_order']):
                stage={key:copy.deepcopy(item) for key,item in original.items() if key not in {'policy_id','created_at','updated_at','escalation_rules_json'}}
                stage['escalation_rules']=[dict(rule,id=f"esc-{stage['id']}-{index}") for index,rule in enumerate(original.get('escalation_rules_json') or [])]
                stage['rules']=[{key:copy.deepcopy(item) for key,item in rule.items() if key not in {'stage_id','created_at','updated_at'}}
                                for rule in tables['approver_rule'] if rule['stage_id']==stage['id']]
                value['stages'].append(stage)
            by_policy[value['id']]=value
        requests={row['id']:dict(copy.deepcopy(row),_policy=by_policy[row['policy_id']]) for row in tables['approval_request']}
        tasks={row['id']:copy.deepcopy(row) for row in tables['approval_task']}
        events={row['id']:row for row in tables['approval_event']}
        required={}
        for row in tables['approval_event']:
            if row['event_type']=='stage_started':
                required[(row['request_id'],row['payload']['stage_order'])]=set(row['payload'].get('required_approvers') or [])
        with store.engine.begin() as connection:
            if connection.scalar(select(archive.c.table_name).limit(1)) or connection.scalar(select(policies.c.id).limit(1)) or connection.scalar(select(objects.c.id).limit(1)):
                raise ValueError('Historical import requires an empty dedicated target')
            for name,dataset in tables.items():
                connection.execute(insert(archive).values(table_name=name,ciphertext=self.cipher.encrypt(json.dumps(dataset).encode()).decode(),sha256=fingerprint(dataset)))
            for value in by_policy.values():
                connection.execute(insert(policies).values(id=value['id'],policy_key=value['policy_key'],version=value['version'],status=value['status'],data=value))
            for value in requests.values():store._save(connection,'request',value)
            for row in tables['approval_task']:
                value=copy.deepcopy(row);value['_source_updated_at']=value.pop('updated_at')
                stage=by_stage[value['stage_id']]
                needed=required.get((value['request_id'],value['stage_order']))
                if needed is None:
                    rules=[rule for rule in tables['approver_rule'] if rule['stage_id']==stage['id'] and rule['kind']=='approver' and rule['required']]
                    if any(rule['rule_type']!='user' for rule in rules):
                        raise ValueError('Cannot infer historical dynamic required-approver membership without its stage event')
                    needed={rule['rule_value']['user_id'] for rule in rules}
                value['_required']=any(value.get(field) in needed for field in ['assignee','delegated_from','reassigned_from'])
                store._save(connection,'task',value,value['request_id'])
            for row in tables['approval_decision']:
                value=copy.deepcopy(row);value['_source_updated_at']=value.pop('updated_at')
                value['_assignee']=tasks[value['task_id']]['assignee']
                store._save(connection,'decision',value,value['request_id'])
            for row in tables['approval_event']:store._save(connection,'event',copy.deepcopy(row),row['request_id'])
            for row in tables['webhook_delivery']:
                value=dict(copy.deepcopy(row),request_id=events[row['event_id']]['request_id'],event_type=events[row['event_id']]['event_type'])
                store._save(connection,'delivery',value,value['request_id'])
            for row in tables['user_delegation']:store._save(connection,'delegation',copy.deepcopy(row))
            for row in tables['audit_action']:
                value=copy.deepcopy(row);value['at']=value.pop('occurred_at');connection.execute(insert(audit).values(**value))
            for row in tables['idempotency_key']:
                response=row['response_payload'];request=requests.get(response.get('request_id'))
                if request is None:raise ValueError('Historical idempotency result has no owning request')
                payload={key:copy.deepcopy(request.get(key)) for key in ['policy_key','artifact_type','artifact_id','context','callback_url','callback_secret_id','requester']}
                identifier='idem:'+hashlib.sha256((request['source_service']+':'+row['key']).encode()).hexdigest()
                store._save(connection,'idempotency',dict(id=identifier,payload=payload,response=response,
                    _legacy_payload=True,_legacy_key=row['key'],_owner=request['source_service'],created_at=row['created_at']))
        self.verify(tables)

    def verify(self,tables):
        store=self.store
        if self.source()!=tables:raise AssertionError('Encrypted historical archive does not match source')
        with store.engine.connect() as connection:
            for original in tables['approval_policy']:
                value=connection.scalar(select(policies.c.data).where(policies.c.id==original['id']))
                if {key:value[key] for key in original}!=original:raise AssertionError('Policy metadata differs')
                for stage in value['stages']:
                    original_stage=next(row for row in tables['approval_stage'] if row['id']==stage['id'])
                    for key in stage:
                        if key not in {'rules','escalation_rules'} and stage[key]!=original_stage[key]:raise AssertionError('Stage field differs')
                    for rule in stage['rules']:
                        source_rule=next(row for row in tables['approver_rule'] if row['id']==rule['id'])
                        if any(source_rule[key]!=value for key,value in rule.items()):raise AssertionError('Approver rule differs')
            for table,kind in [('approval_request','request'),('approval_task','task'),('approval_decision','decision'),
                               ('approval_event','event'),('webhook_delivery','delivery'),('user_delegation','delegation')]:
                values=store._items(connection,kind)
                if len(values)!=len(tables[table]):raise AssertionError('Historical row count differs')
                by_id={row['id']:row for row in values}
                for original in tables[table]:
                    value=by_id[original['id']]
                    for key,item in original.items():
                        actual=value.get('_source_updated_at') if key=='updated_at' and kind in {'task','decision'} else value.get(key)
                        if actual!=item:raise AssertionError('Historical field differs: '+table+'.'+key)
            if len(connection.execute(select(audit)).all())!=len(tables['audit_action']):raise AssertionError('Audit count differs')
        return True

    def rollback_projection(self):
        """Reconstruct the former schema, including writes made after cutover.

        Idempotency keys are caller-namespaced. The prepared fallback adapter
        applies the same namespace to incoming headers before original auth
        and controller execution; no caller can replay another caller's key.
        """
        source=self.source();result={name:[] for name in source};store=self.store
        originals={name:{row.get('id',row.get('key')):row for row in values} for name,values in source.items()}
        fallback_fields={
            'user_delegation':['id','user_id','delegate_to','starts_at','ends_at','reason','created_by','created_at','updated_at']}
        def row(table,value,extra=None):
            before=copy.deepcopy(originals[table].get(value['id'],{}))
            fields=list(next(iter(originals[table].values())).keys()) if originals[table] else fallback_fields.get(table,[])
            for key in fields:
                if key in value:before[key]=copy.deepcopy(value[key])
            if extra:before.update(extra)
            if 'created_at' in fields:before.setdefault('created_at',value.get('created_at') or store.clock())
            if 'updated_at' in fields:
                original=originals[table].get(value['id'])
                changed=not original or any(value.get(key,original.get(key))!=original.get(key) for key in fields if key not in {'created_at','updated_at'})
                before['updated_at']=value.get('updated_at') or (store.clock() if changed else original['updated_at'])
            if set(before)!=set(fields):raise ValueError('Rollback projection is incomplete for '+table)
            result[table].append(before)
        with store.engine.connect() as connection:
            for value in connection.scalars(select(policies.c.data)):
                row('approval_policy',value)
                for stage in value['stages']:
                    escalation=[{key:item for key,item in rule.items() if key!='id'} for rule in stage.get('escalation_rules',[])] or None
                    row('approval_stage',dict(stage,policy_id=value['id']),{'escalation_rules_json':escalation})
                    for rule in stage['rules']:row('approver_rule',dict(rule,stage_id=stage['id']))
            for table,kind in [('approval_request','request'),('approval_task','task'),('approval_decision','decision'),
                               ('approval_event','event'),('webhook_delivery','delivery'),('user_delegation','delegation')]:
                for value in store._items(connection,kind):row(table,value)
            for value in connection.execute(select(audit)).mappings():
                result['audit_action'].append({('occurred_at' if key=='at' else key):copy.deepcopy(item) for key,item in value.items()})
            result['callback_secret']=source['callback_secret']
            for value in store._items(connection,'idempotency'):
                if not value.get('_legacy_key') or not value.get('_owner'):raise ValueError('Cannot reconstruct idempotency owner/key')
                result['idempotency_key'].append({'key':value['id'],'response_payload':value['response'],'created_at':value['created_at']})
        return result

def apply_source_projection(engine,projection,expected_database):
    """Transactional fallback load; callers must fence both writers beforehand."""
    import datetime
    from sqlalchemy import MetaData,DateTime,text,update
    expected={'callback_secret','approval_policy','approval_stage','approver_rule','approval_request','approval_task','approval_decision',
              'approval_event','webhook_delivery','user_delegation','audit_action','idempotency_key'}
    if engine.url.database!=expected_database or set(projection)!=expected:raise ValueError('Explicit fallback database and exact schema required')
    meta=MetaData();tables={name:Table(name,meta,autoload_with=engine) for name in expected}
    def typed(name,row):
        return {key:datetime.datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) and isinstance(tables[name].c[key].type,DateTime) else value for key,value in row.items()}
    with engine.begin() as connection:
        connection.execute(text('TRUNCATE '+','.join('"'+name+'"' for name in sorted(expected))+' RESTRICT'))
        for name in ['callback_secret','approval_policy','approval_stage','approver_rule','approval_request','approval_task','approval_decision',
                     'approval_event','webhook_delivery','user_delegation','audit_action','idempotency_key']:
            values=[typed(name,row) for row in projection[name]]
            if name=='approval_task':values=[dict(value,decision_id=None) for value in values]
            if values:connection.execute(tables[name].insert(),values)
        for value in projection['approval_task']:
            if value['decision_id']:connection.execute(update(tables['approval_task']).where(tables['approval_task'].c.id==value['id']).values(decision_id=value['decision_id']))
