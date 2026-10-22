"""Portal household/member projection shared by native and transition writers."""
import datetime,json,uuid
import karnataka_geography as geo


def build(r,p):
    data=json.loads(p['data']);household=p['household_ref'];location=geo.geography(data);head=data['members'][0]
    base={'geo_lowest_level_value_id':location['state_id'],'latitude':location['latitude'],'longitude':location['longitude'],'geo_code_hierarchy_json':{'karnatakadbt':location}}
    hid=str(uuid.uuid5(uuid.NAMESPACE_URL,household));stamp=r.stamp()
    adults=sum((datetime.date.today()-datetime.date.fromisoformat(m['birth_date'])).days/365.2425>=18 for m in data['members'])
    result=[('g2p_register_households',{'internal_record_id':hid,'functional_record_id':household,'record_name':data['household_name'],'created_by':'karnatakadbt-core','created_at':stamp,'last_approved_at':stamp,'last_approved_by':'staff-review','record_status':'ACTIVE','search_text':data['household_name']+' '+household,'household_head_internal_record_id':str(uuid.uuid5(uuid.NAMESPACE_URL,head['ref'])),'household_head_name':head['given']+' '+head['family'],'size_total':len(data['members']),'size_adults':adults,'country_code':'IND',**base})]
    for m in data['members']:
        name=m['given']+' '+m['family']
        result.append(('g2p_register_individuals',{'internal_record_id':str(uuid.uuid5(uuid.NAMESPACE_URL,m['ref'])),'functional_record_id':m['ref'],'link_internal_record_id':hid,'record_name':name,'created_by':'karnatakadbt-core','created_at':stamp,'last_approved_at':stamp,'last_approved_by':'staff-review','record_status':'ACTIVE','search_text':name+' '+m['ref'],'first_name':m['given'],'last_name':m['family'],'given_name':m['given'],'full_name':name,'gender':m['gender'],'birth_date':m['birth_date'],'country_code':'IND',**{**base,'latitude':None,'longitude':None},'address_line_1':data.get('community','')}))
    return result
