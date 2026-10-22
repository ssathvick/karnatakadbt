"""Validated, declarative household eligibility conditions; never evaluated as code."""
import datetime,json
from pathlib import Path

DISTRICTS={d['id']:d['name'] for d in json.loads(Path(__file__).with_name('karnataka-geography.json').read_text(encoding='utf-8'))['districts']}

def validate_rules(value,minimum=1):
    if isinstance(value,str):
        try:value=json.loads(value)
        except (ValueError,TypeError):raise ValueError('Invalid eligibility rule data.') from None
    if value is None:value={}
    if not isinstance(value,dict) or set(value)-{'districts','max_members','min_age','max_age','gender'}:raise ValueError('Unsupported eligibility rule.')
    result={}
    for key in ['max_members','min_age','max_age']:
        if value.get(key) in (None,''):continue
        n=value[key]
        if isinstance(n,bool) or not isinstance(n,int):raise ValueError('Rule limits must be whole numbers.')
        if not (1<=n<=8 if key=='max_members' else 0<=n<=125):raise ValueError('Rule limit is outside the supported range.')
        result[key]=n
    if result.get('max_members',8)<minimum:raise ValueError('Maximum household size must be at least the minimum.')
    if result.get('min_age',0)>result.get('max_age',125):raise ValueError('Maximum age must be at least the minimum age.')
    districts=value.get('districts',[])
    if not isinstance(districts,list) or len(districts)>31 or any(not isinstance(d,str) or d not in DISTRICTS for d in districts):raise ValueError('Choose valid Karnataka districts.')
    if districts:result['districts']=sorted(set(districts))
    if value.get('gender') not in (None,''):
        if value['gender'] not in ['Female','Male','Other']:raise ValueError('Choose a supported member gender.')
        result['gender']=value['gender']
    return result

def today():return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5,minutes=30))).date()

def evaluate_rules(data,rules,on=None):
    rules=validate_rules(rules);checks=[];on=on or today()
    if 'max_members' in rules:checks.append({'rule':'Maximum household members','actual':len(data.get('members',[])),'maximum':rules['max_members'],'passed':len(data.get('members',[]))<=rules['max_members']})
    if rules.get('districts'):checks.append({'rule':'Eligible district','actual':data.get('state'),'allowed':rules['districts'],'passed':data.get('state') in rules['districts']})
    if any(k in rules for k in ['min_age','max_age','gender']):
        matches=[]
        for member in data.get('members',[]):
            if rules.get('gender') and member.get('gender')!=rules['gender']:continue
            if 'min_age' in rules or 'max_age' in rules:
                try:
                    birth=datetime.date.fromisoformat(member['birth_date']);age=on.year-birth.year-((on.month,on.day)<(birth.month,birth.day))
                    if birth>on or not rules.get('min_age',0)<=age<=rules.get('max_age',125):continue
                except (KeyError,TypeError,ValueError):continue
            matches.append(member.get('ref'))
        checks.append({'rule':'At least one member meets all age and gender conditions','conditions':{k:rules[k] for k in ['min_age','max_age','gender'] if k in rules},'matching_members':matches,'as_of':on.isoformat(),'passed':bool(matches)})
    return checks
