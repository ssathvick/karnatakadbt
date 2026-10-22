"""Karnataka revenue districts and optional reported household coordinates."""
import json,math
from pathlib import Path
CATALOGUE=json.loads(Path(__file__).with_name('karnataka-geography.json').read_text(encoding='utf-8'))
AREAS={a['id']:a for a in CATALOGUE['districts']}
BOUNDARIES=json.loads((Path(__file__).parent/'static/karnataka-districts.geojson').read_text(encoding='utf-8'))
SHAPES={f['properties']['district_id']:f for f in BOUNDARIES['features']}

def inside_ring(lon,lat,ring):
 inside=False
 for a,b in zip(ring,ring[1:]):
  if (a[1]>lat)!=(b[1]>lat) and lon<(b[0]-a[0])*(lat-a[1])/(b[1]-a[1])+a[0]:inside=not inside
 return inside

def inside_district(district_id,lat,lon):
 shape=SHAPES[district_id]['geometry'];polygons=[shape['coordinates']] if shape['type']=='Polygon' else shape['coordinates']
 return any(inside_ring(lon,lat,p[0]) and not any(inside_ring(lon,lat,h) for h in p[1:]) for p in polygons)
def geography(data):
 district=AREAS.get(data.get('state'))
 if not district:raise ValueError('Choose one of Karnataka’s 31 districts.')
 old=data.get('geography') or {}
 return {**old,'schema_version':1,'country_code':'IND','region_code':'IN-KA','region_name':'Karnataka','zone_id':district['zone_id'],'zone_name':district['division'],'division_name':district['division'],'district_id':district['id'],'district_name':district['name'],'state_id':district['id'],'state_name':district['name'],'lga_id':None,'lga_name':old.get('lga_name'),'ward':old.get('ward'),'community':data.get('community'),'latitude':old.get('latitude'),'longitude':old.get('longitude'),'accuracy_m':old.get('accuracy_m'),'coordinate_source':old.get('coordinate_source','not_captured'),'coordinate_verified':False,'administrative_level':'district','code_system':CATALOGUE['code_system']}
def capture(form,data):
 lat=(form.get('latitude') or '').strip();lon=(form.get('longitude') or '').strip();acc=(form.get('accuracy_m') or '').strip()
 if bool(lat)!=bool(lon):raise ValueError('Supply both latitude and longitude or leave both empty.')
 if acc and not lat:raise ValueError('Coordinate accuracy requires coordinates.')
 try:
  lat=float(lat) if lat else None;lon=float(lon) if lon else None;acc=float(acc) if acc else None
  if lat is not None and (not math.isfinite(lat) or not math.isfinite(lon) or not 11<=lat<=19 or not 73<=lon<=79):raise ValueError()
  if acc is not None and (not math.isfinite(acc) or not 0<=acc<=100000):raise ValueError()
 except (ValueError,TypeError):raise ValueError('Enter valid Karnataka coordinate numbers and non-negative accuracy.')
 if lat is not None and not inside_district(data['state'],lat,lon):raise ValueError('Coordinates must fall within the selected district boundary. Check the district and coordinate pair.')
 taluk=(form.get('lga') or '').strip();ward=(form.get('ward') or '').strip()
 if len(taluk)>100 or len(ward)>100:raise ValueError('Taluk and ward must be at most 100 characters.')
 data['geography']={'lga_name':taluk or None,'ward':ward or None,'latitude':lat,'longitude':lon,'accuracy_m':acc,'coordinate_source':'user_reported' if lat is not None else 'not_captured'}
 return geography(data)
def summary(r):
 counts=[];totals={'household':0,'individual':0};coordinates=0
 all_profiles=[json.loads(p['data']) for p in r.rows('SELECT data FROM profiles')]
 for district in AREAS.values():
  profiles=[p for p in all_profiles if p['state']==district['id']]
  for kind in ['household','individual']:
   count=len(profiles) if kind=='household' else sum(len(p['members']) for p in profiles)
   points=sum(p['geography'].get('latitude') is not None for p in profiles) if kind=='household' else 0
   area=SHAPES[district['id']]['properties']['area_km2']
   counts.append(dict(record_type=kind,zone_id=district['zone_id'],zone_name=district['division'],state_id=district['id'],state_name=district['name'],district_id=district['id'],district_name=district['name'],lga_id=None,lga_name=None,administrative_level='district',record_count=count,coordinates_present=points,area_km2=area,density_per_km2=round(count/area,6)));totals[kind]+=count;coordinates+=points
 return {'source':'KarnatakaDBT isolated synthetic registry','synthetic':True,'generated_at':r.stamp(),'measure':'Synthetic registry records, not actual benefit recipients','counts':counts,'totals':totals,'coordinates_present':coordinates,'catalogue':{'districts':31,'divisions':4},'notes':CATALOGUE['notes']}
def install(r):
 from flask import Blueprint,g,redirect,request,abort
 bp=Blueprint('geography',__name__)
 with r.db() as c:c.execute('CREATE TABLE IF NOT EXISTS geography_sync(reference TEXT PRIMARY KEY,status TEXT,error TEXT,updated TEXT)')
 def require():
  r.require_user()
  if g.session.get('mode')!='staff':__import__('flask').abort(403)
 @bp.get(r.PREFIX+'/api/geography/areas')
 def areas():return CATALOGUE
 @bp.get(r.PREFIX+'/api/geography/summary')
 def api_summary():require();return summary(r)
 @bp.get(r.PREFIX+'/api/geography/districts.geojson')
 def boundaries():require();return BOUNDARIES
 @bp.get(r.PREFIX+'/api/geography/households.geojson')
 def points():
  require();features=[];total=0
  for p in r.rows('SELECT household_ref,data,updated,status FROM profiles'):
   total+=1;d=json.loads(p['data']);geo=geography(d)
   if geo['latitude'] is not None:features.append({'type':'Feature','geometry':{'type':'Point','coordinates':[geo['longitude'],geo['latitude']]},'properties':{'reference':p['household_ref'],'name':d['household_name'],'members':len(d['members']),'district_id':geo['district_id'],'district_name':geo['district_name'],'coordinate_source':geo['coordinate_source'],'coordinate_verified':False,'accuracy_m':geo.get('accuracy_m'),'version':p['updated'],'status':p['status'],'synthetic':True}})
  return {'type':'FeatureCollection','features':features,'metadata':{'synthetic':True,'households_total':total,'households_with_coordinates':len(features),'households_missing_coordinates':total-len(features),'coordinate_verified':False}}
 @bp.get(r.PREFIX+'/api/geography/households')
 def households():
  require();result=[]
  for p in r.rows('SELECT household_ref,data,updated,status FROM profiles ORDER BY household_ref'):
   d=json.loads(p['data']);geo=geography(d)
   result.append({'reference':p['household_ref'],'name':d['household_name'],'district_id':geo['district_id'],'district_name':geo['district_name'],'latitude':geo['latitude'],'longitude':geo['longitude'],'accuracy_m':geo.get('accuracy_m'),'coordinate_source':geo['coordinate_source'],'members':len(d['members']),'version':p['updated'],'status':p['status']})
  return {'households':result}
 @bp.post(r.PREFIX+'/api/geography/households/<reference>/location')
 def save_location(reference):
  r.require_user()
  p=r.one('SELECT * FROM profiles WHERE household_ref=?',(reference,))
  if not p:abort(404)
  own_household=g.session.get('mode')=='beneficiary' and p['sub']==g.user.get('sub')
  if not own_household:
   require()
   if not g.staff and g.session.get('role') not in ['officer','verifier','supervisor']:abort(403)
  if request.form.get('version')!=p['updated']:return {'error':'This record changed. Reload the household before saving.'},409
  d=json.loads(p['data']);old=geography(d)
  try:
   geo=capture({**request.form.to_dict(),'lga':old.get('lga_name') or '', 'ward':old.get('ward') or ''},d)
  except ValueError as e:return {'error':str(e)},400
  geo['coordinate_source']='user_reported' if geo['latitude'] is not None else 'not_captured';geo['coordinate_verified']=False
  d['geography']=geo;version=r.stamp()
  with r.db() as c:
   changed=c.execute('UPDATE profiles SET data=?,updated=?,last_editor=? WHERE household_ref=? AND updated=?',(json.dumps(d),version,g.user['sub'],reference,p['updated'])).rowcount
   if not changed:return {'error':'This record changed. Reload before saving.'},409
   c.execute('INSERT OR REPLACE INTO geography_sync VALUES(?,?,?,?)',(reference,'pending',None,version))
  r.audit('household_location_updated',reference)
  synced=sync_location(r,reference)
  return {'saved':True,'native_synced':synced,'version':version,'latitude':geo['latitude'],'longitude':geo['longitude'],'coordinate_source':geo['coordinate_source']}
 @bp.get(r.PREFIX+'/geography')
 def overview():
  if not g.user:
   return redirect(r.PREFIX+'/login?mode=staff&geography=1')
  require();return r.page('geography.html',report=summary(r))
 r.app.register_blueprint(bp)

def sync_location(r,reference):
 import os,hashlib
 if os.name=='nt':return _sync_location(r,reference)
 import fcntl
 with open('/tmp/karnatakadbt-geo-'+hashlib.sha256(reference.encode()).hexdigest()+'.lock','w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  return _sync_location(r,reference)

def _sync_location(r,reference):
 """Idempotent coordinate-only updates; preserve approval and programme records."""
 if hasattr(r,'backend'):
  try:return r.backend.sync_location(reference)
  except Exception:
   with r.db() as c:c.execute('UPDATE geography_sync SET status=?,error=?,updated=? WHERE reference=?',('pending','Core coordinate projection pending; will retry automatically.',r.stamp(),reference))
   return False
 p=r.one('SELECT * FROM profiles WHERE household_ref=?',(reference,));d=json.loads(p['data']);geo=geography(d)
 try:
  if hasattr(r,'pg'):
   refs=[reference]+[m['ref'] for m in d['members']]
   with r.pg('register') as c,c.cursor() as cur:
    for table in ['g2p_register_households','g2p_register_individuals']:
     cur.execute('UPDATE '+table+' SET latitude=%s,longitude=%s,geo_code_hierarchy_json=jsonb_set(COALESCE(geo_code_hierarchy_json,\'{}\'::jsonb),\'{karnatakadbt}\',%s::jsonb) WHERE functional_record_id=ANY(%s)',(geo['latitude'],geo['longitude'],json.dumps(geo),refs))
   for service,database in [('registry-postgresql','socialregistrydb'),('portal-backend-postgresql','portalpbmsdb')]:
    with r.pg(database,service) as c,c.cursor() as cur:cur.execute('UPDATE res_partner SET partner_latitude=%s,partner_longitude=%s WHERE ref=ANY(%s)',(geo['latitude'] or 0,geo['longitude'] or 0,refs))
  with r.db() as c:c.execute('UPDATE geography_sync SET status=?,error=NULL,updated=? WHERE reference=?',('complete',r.stamp(),reference))
  return True
 except Exception:
  with r.db() as c:c.execute('UPDATE geography_sync SET status=?,error=?,updated=? WHERE reference=?',('pending','Native coordinate sync pending; will retry automatically.',r.stamp(),reference))
  return False
