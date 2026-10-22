"""Own configurable application-reference formatter."""
import datetime,re,secrets,string,uuid
def application_reference(pattern,now=None):
    if not isinstance(pattern,str) or not pattern.strip():raise ValueError('Application reference format is empty')
    now=now or datetime.datetime.now()
    def segment(match):
        token=match[1];modifier=None
        if '|' in token:
            token,modifier=token.rsplit('|',1)
            if modifier!='upper':raise ValueError('Unsupported reference modifier')
        name,sep,arg=token.partition(':');name=name.strip().upper()
        if name in {'DATE','TIME'}:
            if not sep or not arg:raise ValueError('Reference date pattern required')
            value=now.strftime(arg);return value.upper() if modifier else value
        if name=='UUID8':
            if sep:raise ValueError('UUID8 has no argument')
            return uuid.uuid4().hex[:8].upper()
        if name not in {'SECONDS','EPOCH','RAND','RAND_ALNUM'}:raise ValueError('Unknown reference token')
        width=int(arg);limit=5 if name=='SECONDS' else 12
        if not 1<=width<=limit:raise ValueError('Invalid reference width')
        if name=='RAND_ALNUM':return ''.join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(width))
        value=now.hour*3600+now.minute*60+now.second if name=='SECONDS' else int(now.timestamp()) if name=='EPOCH' else secrets.randbelow(10**width)
        return str(value).zfill(width)
    value=re.sub(r'\{([^}]+)\}',segment,pattern)
    if len(value)>64:raise ValueError('Application reference exceeds 64 characters')
    return value
