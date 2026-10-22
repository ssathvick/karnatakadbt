"""Administrative geography and optional reported coordinates. No inferred GPS locations."""
import json,math
from pathlib import Path
CATALOGUE=json.loads(Path(__file__).with_name('nigeria-geography.json').read_text(encoding='utf-8'))
AREAS={a['id']:a for a in CATALOGUE['areas']}
def geography(data):
 old=data.get('geography') or {};state=AREAS.get(data.get('state'))
 if not state or state['level']!='state':raise ValueError('Choose a valid Nigeria state or FCT.')
 lga_id=old.get('lga_id') or None;lga=AREAS.get(lga_id)
 if lga_id and (not lga or lga['level']!='lga' or lga['state_id']!=state['id']):raise ValueError('The LGA must belong to the selected state.')
 return {'schema_version':1,'country_code':'NGA','zone_id':state['zone_id'],'zone_name':state['zone_name'],'state_id':state['id'],'state_name':state['name'],'lga_id':lga_id,'lga_name':lga['name'] if lga else None,'ward':old.get('ward') or None,'community':data.get('community') or None,'latitude':old.get('latitude'),'longitude':old.get('longitude'),'accuracy_m':old.get('accuracy_m'),'coordinate_source':old.get('coordinate_source') or 'not_captured','coordinate_verified':False,'administrative_level':'lga' if lga else 'state','code_system':CATALOGUE['code_system']}
def capture(form,data):
 ward=(form.get('ward') or '').strip()
 if len(ward)>100:raise ValueError('Ward exceeds 100 characters.')
 lat=(form.get('latitude') or '').strip();lon=(form.get('longitude') or '').strip();accuracy=(form.get('accuracy_m') or '').strip()
 if bool(lat)!=bool(lon):raise ValueError('Enter both latitude and longitude, or leave both empty.')
 if accuracy and not lat:raise ValueError('Coordinate accuracy requires latitude and longitude.')
 try:
  lat=float(lat) if lat else None;lon=float(lon) if lon else None;accuracy=float(accuracy) if accuracy else None
  if lat is not None and (not math.isfinite(lat) or not -90<=lat<=90 or not math.isfinite(lon) or not -180<=lon<=180):raise ValueError()
  if accuracy is not None and (not math.isfinite(accuracy) or not 0<=accuracy<=100000):raise ValueError()
 except (ValueError,TypeError):raise ValueError('Enter valid coordinate numbers and non-negative accuracy in metres.')
 data['geography']={'lga_id':(form.get('lga') or '').strip() or None,'ward':ward,'latitude':lat,'longitude':lon,'accuracy_m':accuracy,'coordinate_source':('device_gps_reported' if form.get('coordinate_source')=='device_gps_reported' else 'user_reported') if lat is not None else 'not_captured'}
 return geography(data)
def summary(r):
 with r.pg('register') as c:
  with c.cursor() as cur:
   cur.execute('SELECT record_type,zone_id,zone_name,state_id,state_name,lga_id,lga_name,administrative_level,record_count,coordinates_present FROM ng2p_geography_record_counts ORDER BY record_type,state_name,lga_name NULLS FIRST')
   keys=[d[0] for d in cur.description];counts=[dict(zip(keys,row)) for row in cur.fetchall()]
 return {'source':'Modern social registry','synthetic':True,'generated_at':r.stamp(),'measure':'Registry records, not confirmed programme beneficiaries','counts':counts,'totals':{kind:sum(x['record_count'] for x in counts if x['record_type']==kind) for kind in ['individual','household']},'coordinates_present':sum(x['coordinates_present'] for x in counts),'catalogue':{'states_and_fct':37,'lgas':6,'zones':6},'notes':['Households and individuals are separate measures. Do not add them to count people.','Missing LGA, ward and coordinates remain unknown.','Coordinate presence does not mean field verification. No state centroid is an individual location.','Project area identifiers need an explicit crosswalk to the future map boundary dataset.']}
def household_points(r):
 with r.pg('register') as c:
  with c.cursor() as cur:
   cur.execute("SELECT g.internal_record_id,g.record_status,g.zone_id,g.zone_name,g.state_id,g.state_name,g.lga_id,g.lga_name,g.ward,g.latitude,g.longitude,g.coordinate_source,h.geo_code_hierarchy_json->'nigeriag2p'->'accuracy_m' AS reported_accuracy_m FROM ng2p_record_geography g JOIN g2p_register_households h ON h.internal_record_id=g.internal_record_id WHERE g.record_type='household' AND g.latitude IS NOT NULL AND g.longitude IS NOT NULL ORDER BY g.internal_record_id")
   keys=[d[0] for d in cur.description];records=[dict(zip(keys,row)) for row in cur.fetchall()]
   cur.execute("SELECT count(*) FROM ng2p_record_geography WHERE record_type='household'");total=cur.fetchone()[0]
 for row in records:
  row['coordinate_is_demo']=row['coordinate_source']=='synthetic_demo'
  row['coordinate_verified']=False
  row['coordinate_scope']='state_only' if row['coordinate_is_demo'] else 'reported_household'
 features=[{'type':'Feature','id':row['internal_record_id'],'geometry':{'type':'Point','coordinates':[row['longitude'],row['latitude']]},'properties':{k:v for k,v in row.items() if k not in ['latitude','longitude']}} for row in records]
 return {'type':'FeatureCollection','features':features,'metadata':{'generated_at':r.stamp(),'source':'Modern social registry','synthetic':True,'measure':'Household registry locations, not confirmed benefit recipients','households_total':total,'households_with_coordinates':len(features),'households_missing_coordinates':total-len(features),'coordinate_system':'WGS84 (EPSG:4326), longitude then latitude','coordinate_verified':False,'demo_coordinate_count':sum(row['coordinate_is_demo'] for row in records),'notes':['Synthetic demonstration points are generated within the recorded state, not verified residences or LGA locations.','Unlocated households have no map point.','Reported coordinates do not establish a verified household residence.','This endpoint uses the existing sandbox supervisor scope. Production jurisdiction restrictions remain required.']}}
def install(r):
 from flask import Blueprint,g,abort,render_template,redirect
 bp=Blueprint('geography',__name__)
 def require():
  r.require_user()
  if not (g.staff or 'iqs-programme-supervisor' in g.user.get('roles',[])):abort(403,'This geographic overview requires supervisor access.')
 @bp.get(r.PREFIX+'/api/geography/areas')
 def areas():return CATALOGUE
 @bp.get(r.PREFIX+'/api/geography/summary')
 def api_summary():require();return summary(r)
 @bp.get(r.PREFIX+'/api/geography/households.geojson')
 def points():require();return household_points(r)
 @bp.get(r.PREFIX+'/geography')
 def overview():
  if not g.user:return redirect(r.PREFIX+'/login?mode=staff&geography=1')
  require();return r.page('geography.html',report=summary(r))
 r.app.register_blueprint(bp)
