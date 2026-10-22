"""Own beneficiary domain rules shared by write admission paths."""
from datetime import date,datetime
from registry_metadata_store import RegistryError

def invalid(message):raise RegistryError('REQ-VAL-001',message)
def blank(v):return v is None or isinstance(v,(str,list,dict,tuple,set)) and not (v.strip() if isinstance(v,str) else v)
def number(v,kind=int):
    try:return None if v is None or v=='' else kind(v)
    except (ValueError,TypeError):return None
def boolean(v):
    if v is None or v=='':return None
    if isinstance(v,str):
        if v.strip().lower() in {'true','1','yes'}:return True
        if v.strip().lower() in {'false','0','no'}:return False
    return bool(v)
def day(v):
    if isinstance(v,datetime):return v.date()
    if isinstance(v,date):return v
    if isinstance(v,str) and v.strip():
        try:return datetime.fromisoformat(v.strip().replace('Z','+00:00')).date()
        except ValueError:pass
        for fmt in ['%Y-%m-%d','%d-%m-%Y','%d/%m/%Y','%Y/%m/%d']:
            try:return datetime.strptime(v.strip(),fmt).date()
            except ValueError:pass
    return None
def validate_domain(mnemonic,records,today=None):
    today=today or date.today();records=[r for r in records if r.get('edit_action')!='DELETE'];seen=set();programs=[]
    for r in records:
        has=lambda *keys:all(k in r for k in keys)
        if mnemonic=='Individual':
            if has('middle_name') and blank(r['middle_name']):invalid('middle_name is required')
            birth=day(r.get('birth_date'))
            if birth and birth>today:invalid('birth_date must not be in the future')
            age=number(r.get('estimated_age'))
            if birth and age is not None and abs(age-(today.year-birth.year-((today.month,today.day)<(birth.month,birth.day))))>1:invalid('estimated_age must be consistent with birth_date within one year')
        if mnemonic=='Household':
            total=number(r.get('size_total'));keys=['number_of_male_members','number_of_female_members'];parts=[number(r.get(k)) for k in keys]
            if has('size_total',*keys) and total is not None and all(v is not None for v in parts) and total!=sum(parts):invalid('size_total must equal number_of_male_members + number_of_female_members')
            keys=['size_adults','size_children_u5','size_school_age','size_elderly'];parts=[number(r.get(k)) for k in keys]
            if has('size_total',*keys) and total is not None and all(v is not None for v in parts) and total!=sum(parts):invalid('size_total must equal size_adults + size_children_u5 + size_school_age + size_elderly')
            crowd=number(r.get('overcrowding_indicator'),float)
            if total is not None and crowd is not None and crowd>total:invalid('overcrowding_indicator must not exceed size_total')
            if has('elderly_member_present','size_elderly') and boolean(r['elderly_member_present']) is False and number(r['size_elderly']) not in (None,0):invalid('size_elderly must be empty or zero when elderly_member_present is false')
        if mnemonic in {'IndividualDisability','IndividualLivestock'}:
            key='disability_domain' if mnemonic=='IndividualDisability' else 'livestock_species';value=r.get(key)
            if not blank(value):
                value=str(value).strip()
                if value in seen:invalid('Duplicate '+key+' entries are not allowed')
                seen.add(value)
        if mnemonic in {'IndividualProgram','HouseholdProgram'}:
            start=day(r.get('program_start_date'));end=day(r.get('program_exit_date'))
            if start and end and end<start:invalid('program_exit_date must be on or after program_start_date')
            if end and end>today:invalid('program_exit_date must not be in the future')
            name=str(r.get('program_name')).strip() if r.get('program_name') is not None else ''
            if name:
                if any(n==name and (start is None or s is None or start<=(e or date.max) and s<=(end or date.max)) for n,s,e in programs):invalid("Duplicate program '"+name+"' with overlapping dates is not allowed")
                programs.append((name,start,end))
        if mnemonic=='IndividualVulnerability':
            if has('plw_status','plw_status_date') and boolean(r['plw_status']) is False and not blank(r['plw_status_date']):invalid('plw_status_date must be empty when plw_status is false')
            if r.get('pastoralist_classification')=='SETTLED' and boolean(r.get('high_mobility_indicator')) is True:invalid('high_mobility_indicator must be false when pastoralist_classification is SETTLED')
        if mnemonic=='IndividualLand' and has('land_access'):
            access=boolean(r['land_access']);size=number(r.get('land_size'),float)
            if access is False:
                if size is not None and size>0:invalid('land_size must be empty when land_access is false')
                if not blank(r.get('productive_assets')):invalid('productive_assets must be empty when land_access is false')
            if access is True and has('land_size') and (size is None or size<=0):invalid('land_size must be greater than zero when land_access is true')
        if mnemonic=='IndividualLivelihood' and has('primary_livelihood','secondary_livelihood') and not blank(r['primary_livelihood']) and not blank(r['secondary_livelihood']) and str(r['primary_livelihood']).strip()==str(r['secondary_livelihood']).strip():invalid('primary_livelihood and secondary_livelihood must be different')
