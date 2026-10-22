"""Conflict-checked native projections of documents, dedup results and operations.

All outputs of a source event share its destination transaction. Object storage
is never mutated by this projector. Export policies stay in the private worker
queue; the user-facing operation view receives only its contract's safe fields.
"""
import datetime,hashlib,json,re
from pathlib import Path
from psycopg2 import sql


def digest_key(values):return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()


class NativeAuxiliaryProjector:
    def __init__(self,native_schema='public'):
        self.schema=native_schema
        self.operations=json.loads(Path(__file__).with_name('registry_operation_contract.json').read_text())
        self.mapping={v['source_table']:('dedup',k) for k,v in json.loads(Path(__file__).with_name('registry_dedup_contract.json').read_text()).items()}
        self.mapping.update({t:('document',k) for t,k in [('g2p_registry_documents','catalog'),('g2p_change_request_documents','change'),('g2p_intake_section_documents','intake'),('g2p_register_section_documents','section'),('g2p_register_document_history','history')]})
        self.mapping.update(awe_req_events=('operation','event'),g2p_register_export_data_queue=('operation','export'),subscription_activity_logs=('subscription',None))
        self.mapping.update(registry_languages=('metadata','language'),registry_themes=('metadata','theme'),registry_theme_values=('metadata','value'),g2p_registry_configuration=('metadata','configuration'))

    def initialize(self,c):
        c.execute(sql.SQL('CREATE TABLE IF NOT EXISTS {}.native_auxiliary_sync_state(source_table text NOT NULL,source_key text NOT NULL,raw text NOT NULL,PRIMARY KEY(source_table,source_key))').format(sql.Identifier(self.schema)))

    def encode_state(self,raw):return raw
    def decode_state(self,raw):return raw
    def remove_output(self,c,output):
        target,keys,_,_=output
        c.execute(sql.SQL('DELETE FROM {}.{} WHERE {}').format(sql.Identifier(self.schema),sql.Identifier(target),self.predicate(keys)),tuple(keys.values()))
    def output_exists(self,c,output):
        target,keys,_,_=output
        c.execute(sql.SQL('SELECT 1 FROM {}.{} WHERE {} FOR UPDATE').format(sql.Identifier(self.schema),sql.Identifier(target),self.predicate(keys)),tuple(keys.values()))
        return c.fetchone() is not None

    def source_key(self,table,raw):
        v=json.loads(raw);family,kind=self.mapping[table]
        if family=='dedup':fields=['dedup_result_id']
        elif family=='document':fields={'catalog':['document_id'],'change':['change_request_id','document_id'],'intake':['submission_id','document_id'],'section':['internal_record_id','document_id'],'history':['document_history_id']}[kind]
        elif family=='operation':fields=self.operations[kind]['primary_key']
        elif family=='metadata':fields=[{'language':'language_id','theme':'theme_id','value':'theme_value_id','configuration':'configuration_id'}[kind]]
        else:fields=['subscription_activity_log_id']
        if any(v.get(k) is None for k in fields):raise ValueError('Stable auxiliary source identity required')
        return digest_key([v[k] for k in fields])

    def outputs(self,c,table,raw):
        """Return target, PK, typed index attributes, and exact JSON text."""
        v=json.loads(raw);family,kind=self.mapping[table]
        if family=='metadata':
            target,fields={
                'language':('console_languages',{'id':'language_id','code':'language_code','label':'language_label','flag':'language_flag_base64','is_default':'is_default','core':'core_translation','domain':'domain_translation'}),
                'theme':('console_themes',{'id':'theme_id','name':'theme_mnemonic','factory':'is_factory_shipped'}),
                'value':('console_theme_values',{'id':'theme_value_id','theme':'theme_id','attribute':'attribute_name','value':'attribute_value'}),
                'configuration':('console_configuration',{'id':'configuration_id','name':'registry_name','logo':'registry_logo','favicon':'registry_favicon','theme':'registry_theme_id','language':'registry_language_id'})}[kind]
            # PostgreSQL builds the renamed JSON so translation decimals and
            # JSON nulls are not rounded through a Python float conversion.
            c.execute('SELECT jsonb_object_agg(p.key,x.value ->> p.value)::text FROM jsonb_each_text(%s::jsonb) p CROSS JOIN (SELECT %s::jsonb value) x',(json.dumps(fields),raw));attrs=json.loads(c.fetchone()[0])
            for field in ['is_default','factory']:
                if field in attrs:attrs[field]=v[fields[field]]
            if kind=='language':
                # JSON-valued translations must remain JSON, not quoted text.
                c.execute("SELECT jsonb_build_object('core',value->'core_translation','domain',value->'domain_translation')::text FROM (SELECT %s::jsonb value) x",(raw,));translations=c.fetchone()[0]
                attrs.pop('core');attrs.pop('domain')
            else:translations=None
            key={'singleton':1} if kind=='configuration' else {'id':attrs.pop('id')}
            return [(target,key,attrs,translations)]
        if family=='dedup':return [('console_duplicate_matches',{'kind':kind,'id':v['dedup_result_id']},{'target_id':v['submission_id' if kind.startswith('intake') else 'change_request_id']},raw)]
        if family=='document':
            key=v['document_id'] if kind=='catalog' else digest_key(v)
            return [('console_document_catalog',{'kind':kind,'id':key},{'state':'READY'},raw)]
        if family=='subscription':return [('console_subscription_activity',{'id':v['subscription_activity_log_id']},{'partner_id':v['partner_id'],'at':v['date_time']},raw)]
        # Build the public view inside PostgreSQL, preserving numeric precision.
        c.execute('SELECT coalesce(jsonb_object_agg(k,val),\'{}\'::jsonb)::text FROM jsonb_each(%s::jsonb) e(k,val) WHERE k=ANY(%s)',(raw,self.operations[kind]['selected_fields']));safe=c.fetchone()[0]
        def stamp(value):
            if value is None:return None
            normalized=re.sub(r'\.(\d+)(?=[+-]\d\d:?\d\d$|$)',lambda m:'.'+m[1].ljust(6,'0'),value.replace('Z','+00:00'))
            parsed=datetime.datetime.fromisoformat(normalized)
            return (parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed).isoformat()
        result=[('console_registry_operations',{'kind':kind,'key':digest_key([v[k] for k in self.operations[kind]['primary_key']])},{'owner':v.get('requested_by'),'artifact_type':v.get('artifact_type'),'artifact_id':v.get('artifact_id'),'applied':v.get('applied'),'at':stamp(v.get('queued_at') if kind=='export' else v.get('occurred_at')),'received_at':stamp(v.get('received_at'))},safe)]
        if kind=='export':result.append(('console_registry_export_queue',{'id':v['export_id']},{'owner':v['requested_by'],'status':v['export_status'],'queued_at':v['queued_at']},raw))
        return result

    def predicate(self,keys):return sql.SQL(' AND ').join(sql.SQL('{}=%s').format(sql.Identifier(k)) for k in keys)

    def assert_output(self,c,output,allow_missing=False):
        target,keys,attrs,raw=output
        # Compare typed indexes using jsonb_populate_record; timestamps are
        # normalized exactly as the native table, not as Python float/strings.
        plain=target in {'console_languages','console_themes','console_theme_values','console_configuration'}
        expression=sql.SQL('TRUE') if plain else sql.SQL('t.data::jsonb=%s::jsonb')
        if target=='console_languages':expression=sql.SQL("jsonb_build_object('core',t.core,'domain',t.domain)=%s::jsonb")
        parameters=([raw] if not plain or target=='console_languages' else [])+[json.dumps(attrs)]+list(keys.values())
        c.execute(sql.SQL('SELECT {} AND {} FROM {}.{} t,jsonb_populate_record(NULL::{}.{},%s::jsonb) expected WHERE {}').format(expression,
            sql.SQL(' AND ').join(sql.SQL('t.{} IS NOT DISTINCT FROM expected.{}').format(sql.Identifier(k),sql.Identifier(k)) for k in attrs) if attrs else sql.SQL('TRUE'),
            sql.Identifier(self.schema),sql.Identifier(target),sql.Identifier(self.schema),sql.Identifier(target),sql.SQL(' AND ').join(sql.SQL('t.{}=%s').format(sql.Identifier(k)) for k in keys)),parameters)
        row=c.fetchone()
        if row is None and allow_missing:return False
        if row is None or not row[0]:raise ValueError('NATIVE_AUXILIARY_SYNC_CONFLICT')
        return True

    def put_output(self,c,output):
        target,keys,attrs,raw=output;plain=target in {'console_languages','console_themes','console_theme_values','console_configuration'}
        attrs=dict(attrs)
        names=list(keys)+list(attrs);values=list(keys.values())+list(attrs.values());placeholders=[sql.Placeholder() for _ in names];update_fields=list(attrs)
        if not plain:names.append('data');values.append(raw);placeholders.append(sql.SQL('%s::jsonb'));update_fields.append('data')
        if target=='console_languages':
            for field in ['core','domain']:
                names.append(field);values.append(raw);placeholders.append(sql.SQL('%s::jsonb -> {}').format(sql.Literal(field)));update_fields.append(field)
        if target=='console_document_catalog':
            names.append('position');placeholders.append(sql.SQL('(SELECT coalesce(max(position),0)+1 FROM {}.{})').format(sql.Identifier(self.schema),sql.Identifier(target)))
        if target=='console_theme_values':
            names.append('position');placeholders.append(sql.SQL('(SELECT coalesce(max(position),0)+1 FROM {}.{})').format(sql.Identifier(self.schema),sql.Identifier(target)))
        c.execute(sql.SQL('INSERT INTO {}.{} ({}) SELECT {} FROM jsonb_populate_record(NULL::{}.{},%s::jsonb) typed ON CONFLICT ({}) DO UPDATE SET {}').format(sql.Identifier(self.schema),sql.Identifier(target),sql.SQL(',').join(map(sql.Identifier,names)),sql.SQL(',').join(sql.SQL('typed.{}').format(sql.Identifier(name)) if name in attrs else ph for name,ph in zip(names,placeholders)),sql.Identifier(self.schema),sql.Identifier(target),sql.SQL(',').join(map(sql.Identifier,keys)),sql.SQL(',').join(sql.SQL('{}=excluded.{}').format(sql.Identifier(k),sql.Identifier(k)) for k in update_fields)),[value for name,value in zip(list(keys)+list(attrs)+([] if plain else ['data'])+(['core','domain'] if target=='console_languages' else []),values) if name not in attrs]+[json.dumps(attrs)])

    def event(self,c,table,operation,before,after,nulls):
        if table not in self.mapping:return
        if operation=='TRUNCATE':
            c.execute(sql.SQL('SELECT raw FROM {}.native_auxiliary_sync_state WHERE source_table=%s FOR UPDATE').format(sql.Identifier(self.schema)),(table,))
            for (raw,) in c.fetchall():self.event(c,table,'DELETE',self.decode_state(raw),None,[])
            return
        oldkey=self.source_key(table,before) if before else None;newkey=self.source_key(table,after) if after else None
        c.execute(sql.SQL('SELECT source_key,raw FROM {}.native_auxiliary_sync_state WHERE source_table=%s AND source_key=ANY(%s) FOR UPDATE').format(sql.Identifier(self.schema)),(table,list({k for k in [oldkey,newkey] if k})))
        prior={key:self.decode_state(raw) for key,raw in c.fetchall()}
        for key,raw in prior.items():
            for out in self.outputs(c,table,raw):self.assert_output(c,out)
        if before and oldkey not in prior:raise ValueError('Auxiliary before image is not synchronized')
        if before:
            c.execute('SELECT %s::jsonb=%s::jsonb',(before,prior[oldkey]))
            if not c.fetchone()[0]:raise ValueError('Auxiliary source before image mismatch')
        if newkey in prior and newkey!=oldkey:raise ValueError('Auxiliary destination identity collision')
        next_outputs=self.outputs(c,table,after) if after else []
        old_outputs=[out for raw in prior.values() for out in self.outputs(c,table,raw)]
        for out in next_outputs:
            if not any(out[0:2]==old[0:2] for old in old_outputs):
                if self.output_exists(c,out):raise ValueError('Native auxiliary identity already exists')
        for target,keys,_,_ in old_outputs:
            if not any(target==out[0] and keys==out[1] for out in next_outputs):
                self.remove_output(c,(target,keys,None,None))
        for out in next_outputs:self.put_output(c,out)
        c.execute(sql.SQL('DELETE FROM {}.native_auxiliary_sync_state WHERE source_table=%s AND source_key=ANY(%s)').format(sql.Identifier(self.schema)),(table,list(prior)))
        if after:c.execute(sql.SQL('INSERT INTO {}.native_auxiliary_sync_state VALUES(%s,%s,%s)').format(sql.Identifier(self.schema)),(table,newkey,self.encode_state(after)))

    def seed(self,c,mirror_schema,source_id):
        self.initialize(c);counts={}
        for table in self.mapping:
            c.execute(sql.SQL('SELECT data::text FROM {}.rows WHERE source_id=%s AND table_name=%s').format(sql.Identifier(mirror_schema)),(source_id,table));rows=c.fetchall()
            for (raw,) in rows:
                for out in self.outputs(c,table,raw):
                    if not self.assert_output(c,out,allow_missing=True):self.put_output(c,out)
                c.execute(sql.SQL('INSERT INTO {}.native_auxiliary_sync_state VALUES(%s,%s,%s) ON CONFLICT(source_table,source_key) DO UPDATE SET raw=excluded.raw').format(sql.Identifier(self.schema)),(table,self.source_key(table,raw),self.encode_state(raw)))
            # Every source namespace must match, including an empty source.
            if rows:examples=self.outputs(c,table,rows[0][0])
            else:examples=self.namespace_outputs(table)
            for target,kind in [(out[0],out[1].get('kind')) for out in examples]:
                clause=sql.SQL(' WHERE kind=%s') if kind is not None else sql.SQL('')
                c.execute(sql.SQL('SELECT count(*) FROM {}.{}').format(sql.Identifier(self.schema),sql.Identifier(target))+clause,(kind,) if kind is not None else ())
                if c.fetchone()[0]!=len(rows):raise ValueError('Extra native auxiliary rows absent from mirror')
            counts[table]=len(rows)
        return counts

    def namespace_outputs(self,table):
        family,kind=self.mapping[table]
        if family=='dedup':return [('console_duplicate_matches',{'kind':kind})]
        if family=='document':return [('console_document_catalog',{'kind':kind})]
        if family=='subscription':return [('console_subscription_activity',{})]
        if family=='metadata':return [({'language':'console_languages','theme':'console_themes','value':'console_theme_values','configuration':'console_configuration'}[kind],{})]
        result=[('console_registry_operations',{'kind':kind})]
        if kind=='export':result.append(('console_registry_export_queue',{}))
        return result

