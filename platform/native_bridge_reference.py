"""Native programme/warehouse/agency reference catalogue, with no ERP runtime."""
import hashlib,json,re
from sqlalchemy import text


KINDS={'warehouse':'g2p_warehouse','warehouse_program':'g2p_warehouse_program_benefit_codes','warehouse_geo':'g2p_administrative_area_large_g2p_warehouse_rel','agency':'g2p_agency','agency_program':'g2p_agency_program_benefit_codes','agency_geo':'g2p_administrative_area_small_g2p_agency_rel'}
KEYS={'warehouse':['id'],'warehouse_program':['id'],'warehouse_geo':['g2p_warehouse_id','g2p_administrative_area_large_id'],'agency':['id'],'agency_program':['id'],'agency_geo':['g2p_agency_id','g2p_administrative_area_small_id']}


class NativeBridgeReference:
    def __init__(self,engine):self.engine=engine
    def initialize(self):
        with self.engine.begin() as c:
            if not c.scalar(text('SELECT current_database()')).startswith('kdbt_registry_candidate_bridge_'):raise ValueError('Dedicated native bridge reference database required')
            c.execute(text('CREATE SCHEMA IF NOT EXISTS kdbt_bridge_reference'));c.execute(text('REVOKE ALL ON SCHEMA kdbt_bridge_reference FROM PUBLIC'))
            c.execute(text('CREATE TABLE IF NOT EXISTS kdbt_bridge_reference.entries(kind text NOT NULL,row_key jsonb NOT NULL,body jsonb NOT NULL,PRIMARY KEY(kind,row_key))'))
            c.execute(text('CREATE TABLE IF NOT EXISTS kdbt_bridge_reference.state(singleton boolean PRIMARY KEY CHECK(singleton),source_identity jsonb NOT NULL,snapshot_sha256 text NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())'))
    def replace_source(self,source_identity,tables):
        if set(tables)!=set(KINDS.values()):raise ValueError('Complete reference catalogue required')
        entries=[]
        for kind,table in KINDS.items():
            rows=tables[table]
            for row in rows:entries.append({'kind':kind,'key':json.dumps({key:row[key] for key in KEYS[kind]},sort_keys=True),'body':json.dumps(row,sort_keys=True)})
        digest=hashlib.sha256(json.dumps(sorted((row['kind'],row['key'],row['body']) for row in entries)).encode()).hexdigest()
        with self.engine.begin() as c:
            c.execute(text("SELECT pg_advisory_xact_lock_shared(hashtextextended('karnatakadbt-bridge-ownership',0))"))
            if c.scalar(text('SELECT owner FROM kdbt_bridge_control.ownership WHERE singleton'))!='SOURCE':raise ValueError('Reference source projection requires SOURCE ownership')
            prior=c.execute(text('SELECT source_identity,snapshot_sha256 FROM kdbt_bridge_reference.state WHERE singleton FOR UPDATE')).mappings().first()
            if prior and prior['source_identity']!=source_identity:raise ValueError('Reference source identity changed')
            if prior and prior['snapshot_sha256']==digest:return len(entries)
            c.execute(text('DELETE FROM kdbt_bridge_reference.entries'))
            for row in entries:c.execute(text('INSERT INTO kdbt_bridge_reference.entries(kind,row_key,body) VALUES(:kind,CAST(:key AS jsonb),CAST(:body AS jsonb))'),row)
            c.execute(text('INSERT INTO kdbt_bridge_reference.state(singleton,source_identity,snapshot_sha256) VALUES(true,CAST(:identity AS jsonb),:digest) ON CONFLICT(singleton) DO UPDATE SET snapshot_sha256=EXCLUDED.snapshot_sha256,updated_at=now()'),{'identity':json.dumps(source_identity),'digest':digest})
        return len(entries)
    def rows(self,kind):
        if kind not in KINDS:raise ValueError('Unknown reference kind')
        with self.engine.connect() as c:return c.execute(text('SELECT body FROM kdbt_bridge_reference.entries WHERE kind=:kind ORDER BY row_key::text'),{'kind':kind}).scalars().all()
    @staticmethod
    def tags(value):return {match[0]:match[1] for match in re.findall(r'#([A-Z]+)#([^#]*)',value or '')}
    def sponsor(self,envelope):
        rows=[row for row in self.rows('warehouse_program') if row['program_id']==envelope['benefit_program_id'] and row['benefit_code_id']==envelope['benefit_code_id']]
        configurations={json.dumps({'program_account_number':self.tags(row.get('additional_info')).get('ACCOUNT'),'program_account_type':self.tags(row.get('additional_info')).get('TYPE'),'program_account_branch_code':self.tags(row.get('additional_info')).get('BRANCH'),'sponsor_bank_code':row['warehouse_mnemonic']},sort_keys=True) for row in rows}
        if len(configurations)!=1:raise ValueError('One unambiguous programme sponsor configuration required')
        result=json.loads(next(iter(configurations)))
        if not result['program_account_number'] or not result['sponsor_bank_code']:raise ValueError('Complete programme sponsor configuration required')
        return result
    def account_configuration(self,number):
        rows=[row for row in self.rows('warehouse_program') if self.tags(row.get('additional_info')).get('ACCOUNT')==number]
        if not rows:return None
        result=self.sponsor({'benefit_program_id':rows[0]['program_id'],'benefit_code_id':rows[0]['benefit_code_id']})
        if any(row['warehouse_mnemonic']!=result['sponsor_bank_code'] for row in rows):raise ValueError('Ambiguous account bank configuration')
        return result
    def agency_account(self,identifier,envelope):
        rows=[row for row in self.rows('agency_program') if str(row['agency_id'])==str(identifier) and row['program_id']==envelope['benefit_program_id'] and row['benefit_code_id']==envelope['benefit_code_id']]
        if len(rows)!=1:raise ValueError('One programme agency account required')
        row=rows[0];tags=self.tags(row.get('additional_info'))
        if not tags.get('ACCOUNT') or not tags.get('BANK'):raise ValueError('Complete agency account required')
        return {'number':tags['ACCOUNT'],'type':tags.get('TYPE') or 'BANK_ACCOUNT','bank':tags['BANK'],'branch':tags.get('BRANCH'),'name':row.get('agency_name')}
    def allocate(self,kind,envelope,geos):
        if kind not in {'warehouse','agency'}:raise ValueError('Explicit allocation kind required')
        programmes=[row for row in self.rows(kind+'_program') if row['program_id']==envelope['benefit_program_id'] and row['benefit_code_id']==envelope['benefit_code_id']];places={str(row['id']):row for row in self.rows(kind)};relations=self.rows(kind+'_geo');size='large' if kind=='warehouse' else 'small';result=[]
        for geo in geos:
            covered={str(row['g2p_'+kind+'_id']) for row in relations if str(row['g2p_administrative_area_'+size+'_id'])==str(geo['administrative_zone_id_'+size])};available=sorted((row for row in programmes if str(row[kind+'_id']) in covered and str(row[kind+'_id']) in places),key=lambda row:str(row[kind+'_id']))
            if not available:raise ValueError('No eligible programme allocation for geography')
            # Stable assignment makes retries reproducible; it never allocates
            # outside the configured programme and administrative area.
            chosen=available[int(hashlib.sha256(geo['id'].encode()).hexdigest(),16)%len(available)];place=places[str(chosen[kind+'_id'])]
            result.append({'batch_control_geo_id':geo['id'],kind+'_id':str(place['id']),kind+'_mnemonic':place[kind+'_mnemonic'],kind+'_name':place.get('name'),kind+'_admin_name':place.get('admin_name'),kind+'_admin_email':place.get('admin_email'),kind+'_admin_phone':place.get('admin_mobile'),kind+'_additional_attributes':chosen.get('additional_info')})
        return result
