"""Custom registry configuration, languages and themes, with atomic audit events."""
import base64,binascii,contextlib,datetime,io,re,uuid
import filetype
from PIL import Image,UnidentifiedImageError
from sqlalchemy import MetaData,Table,Column,String,Text,Boolean,Integer,JSON,select,insert,update,delete,Index,text

metadata=MetaData()
languages=Table('console_languages',metadata,Column('id',String,primary_key=True),Column('code',String(10),unique=True,nullable=False),Column('label',String(100),nullable=False),Column('flag',Text),Column('is_default',Boolean,nullable=False),Column('core',JSON),Column('domain',JSON))
themes=Table('console_themes',metadata,Column('id',String,primary_key=True),Column('name',String(50),unique=True,nullable=False),Column('factory',Boolean,nullable=False))
values=Table('console_theme_values',metadata,Column('id',String,primary_key=True),Column('theme',String,nullable=False),Column('attribute',String,nullable=False),Column('value',Text,nullable=False),Column('position',Integer,nullable=False))
configuration=Table('console_configuration',metadata,Column('singleton',Integer,primary_key=True),Column('id',String,nullable=False,unique=True),Column('name',String,nullable=False),Column('logo',Text),Column('favicon',Text),Column('theme',String),Column('language',String))
mutex=Table('console_metadata_mutex',metadata,Column('id',Integer,primary_key=True))
events=Table('console_metadata_events',metadata,Column('id',String,primary_key=True),Column('actor',String,nullable=False),Column('operation',String,nullable=False),Column('entity',String,nullable=False),Column('result',JSON,nullable=False),Column('at',String,nullable=False))
Index('ix_console_theme_values',values.c.theme)
Index('ix_console_single_default',languages.c.is_default,unique=True,postgresql_where=languages.c.is_default.is_(True),sqlite_where=languages.c.is_default.is_(True))
ATTRIBUTES={'primary_color_1','primary_color_2','secondary_color_1','secondary_color_2','secondary_color_3','neutral_color_1','neutral_color_2','font_family','font_url','dashboard_image'}
ERRORS={'RLG-ERR-001':'REGISTRY_LANGUAGE_NOT_FOUND','RLG-ERR-002':'REGISTRY_LANGUAGE_EXISTS',
        'RTH-ERR-001':'REGISTRY_THEME_NOT_FOUND','RTH-ERR-002':'REGISTRY_THEME_EXISTS',
        'RTH-ERR-003':'FACTORY_THEME_DELETE_NOT_ALLOWED','RTH-ERR-004':'FACTORY_THEME_UPDATE_NOT_ALLOWED',
        'RCF-ERR-001':'REGISTRY_CONFIGURATION_NOT_FOUND','RCF-ERR-002':'REGISTRY_CONFIGURATION_EXISTS','SYS-ERR-001':'UNEXPECTED_ERROR'}
class RegistryError(ValueError):
    def __init__(self,code,message=None):self.code=code;self.message=message or ERRORS[code];super().__init__(self.message)

def image_value(value,width=1024,height=1024):
    raw=value.strip()
    if not raw:raise RegistryError('DOC-VAL-005','Value is empty.')
    match=re.match(r'^data:[^;,]+;base64,(.*)$',raw,re.DOTALL|re.IGNORECASE)
    try:data=base64.b64decode(''.join((match.group(1) if match else raw).split()),validate=True)
    except (ValueError,binascii.Error):raise RegistryError('DOC-VAL-005','Invalid base64 encoding.') from None
    if not data:raise RegistryError('DOC-VAL-005','File content is empty.')
    if len(data)>1048576:raise RegistryError('DOC-VAL-003',f'File size ({len(data)} bytes) exceeds maximum of 1048576 bytes.')
    kind=filetype.guess(data)
    if kind is None:raise RegistryError('DOC-VAL-005','File content could not be identified as an allowed type.')
    mime=kind.mime.lower()
    if not mime.startswith('image/'):raise RegistryError('DOC-VAL-002',f"Detected file type '{mime}' is not an image.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load();w,h=image.size;detected=image.format.upper()
    except UnidentifiedImageError:raise RegistryError('DOC-VAL-005','File content could not be identified as a valid image.') from None
    except OSError as e:raise RegistryError('DOC-VAL-005',f'File content could not be decoded: {e}') from None
    mime={'PNG':'image/png','JPEG':'image/jpeg','WEBP':'image/webp','GIF':'image/gif'}.get(detected)
    if mime is None:raise RegistryError('DOC-VAL-002',f"Detected image format '{detected or 'unknown'}' is not supported.")
    if mime not in ['image/jpeg','image/png','image/webp']:raise RegistryError('DOC-VAL-002',f"Detected file type '{mime}' is not allowed. Allowed MIME types: image/jpeg, image/png, image/webp.")
    if w>width:raise RegistryError('DOC-VAL-004',f'Image width ({w}px) exceeds maximum of {width}px.')
    if h>height:raise RegistryError('DOC-VAL-004',f'Image height ({h}px) exceeds maximum of {height}px.')
    return 'data:'+mime+';base64,'+base64.b64encode(data).decode()

def language_wire(row):return dict(language_id=row['id'],language_code=row['code'],language_label=row['label'],language_flag_base64=row['flag'],is_default=row['is_default'],core_translation=row['core'],domain_translation=row['domain'])
def theme_wire(row):return dict(theme_id=row['id'],theme_mnemonic=row['name'],is_factory_shipped=row['factory'])
def config_wire(row):return dict(configuration_id=row['id'],registry_name=row['name'],registry_logo=row['logo'],registry_favicon=row['favicon'],registry_theme_id=row['theme'],registry_language_id=row['language'])

class RegistryMetadataStore:
    def __init__(self,engine):self.engine=engine
    def initialize(self):
        metadata.create_all(self.engine)
        with self.engine.begin() as c:
            if not c.execute(select(mutex.c.id)).first():c.execute(insert(mutex).values(id=1))
    @contextlib.contextmanager
    def write(self):
        with self.engine.begin() as c:
            c.execute(select(mutex).where(mutex.c.id==1).with_for_update()).one()
            yield c
    def record(self,c,actor,operation,entity,result):
        c.execute(insert(events).values(id=str(uuid.uuid4()),actor=actor,operation=operation,entity=entity,result=result,at=datetime.datetime.now(datetime.timezone.utc).isoformat()))
    def one(self,c,table,key,code):
        row=c.execute(select(table).where(table.c.id==key)).mappings().first()
        if row is None:raise RegistryError(code)
        return dict(row)
    def default_language(self,c,key):
        c.execute(update(languages).values(is_default=False));c.execute(update(languages).where(languages.c.id==key).values(is_default=True))
    def seed(self,data):
        with self.write() as c:
            if c.execute(select(languages.c.id)).first() or c.execute(select(themes.c.id)).first():raise RuntimeError('Refusing to overwrite registry metadata')
            for row in data['registry_languages']:
                c.execute(insert(languages).values(id=row['language_id'],code=row['language_code'],label=row['language_label'],flag=row['language_flag_base64'],is_default=row['is_default'],core=row['core_translation'],domain=row['domain_translation']))
            for row in data['registry_themes']:c.execute(insert(themes).values(id=row['theme_id'],name=row['theme_mnemonic'],factory=row['is_factory_shipped']))
            for position,row in enumerate(data['registry_theme_values']):c.execute(insert(values).values(id=row['theme_value_id'],theme=row['theme_id'],attribute=row['attribute_name'],value=row['attribute_value'],position=position))
            for row in data['g2p_registry_configuration']:c.execute(insert(configuration).values(singleton=1,id=row['configuration_id'],name=row['registry_name'],logo=row['registry_logo'],favicon=row['registry_favicon'],theme=row['registry_theme_id'],language=row['registry_language_id']))
    def execute(self,path,p,actor):
        operation=path.rsplit('/',1)[-1]
        read=operation.startswith('get_')
        with (self.engine.connect() if read else self.write()) as c:
            if path.startswith('/registry-language/'):
                if operation=='get_all_languages':return [language_wire(x) for x in c.execute(select(languages)).mappings()]
                if operation=='get_language':return language_wire(self.one(c,languages,p['language_id'],'RLG-ERR-001'))
                if operation=='create_language':
                    if c.execute(select(languages.c.id).where(languages.c.code==p['language_code'])).first():raise RegistryError('RLG-ERR-002')
                    if p.get('is_default'):c.execute(update(languages).values(is_default=False))
                    row=dict(id=str(uuid.uuid4()),code=p['language_code'],label=p['language_label'],flag=image_value(p['language_flag_base64']) if p.get('language_flag_base64') else None,is_default=p.get('is_default',False),core=p.get('core_translation'),domain=p.get('domain_translation'))
                    c.execute(insert(languages).values(**row));result=language_wire(row)
                elif operation=='update_language':
                    row=self.one(c,languages,p['language_id'],'RLG-ERR-001')
                    if p.get('language_code') is not None and p['language_code']!=row['code'] and c.execute(select(languages.c.id).where(languages.c.code==p['language_code'])).first():raise RegistryError('RLG-ERR-002')
                    changes={target:p[source] for source,target in [('language_code','code'),('language_label','label'),('core_translation','core'),('domain_translation','domain'),('is_default','is_default')] if p.get(source) is not None}
                    if p.get('language_flag_base64') is not None:changes['flag']=image_value(p['language_flag_base64']) if p['language_flag_base64'] else None
                    if changes.get('is_default'):c.execute(update(languages).values(is_default=False))
                    row.update(changes);c.execute(update(languages).where(languages.c.id==row['id']).values(**changes)) if changes else None
                    result=language_wire(row)
                elif operation=='remove_language':
                    row=self.one(c,languages,p['language_id'],'RLG-ERR-001');result=language_wire(row);c.execute(delete(languages).where(languages.c.id==row['id']))
                else:raise KeyError(path)
                self.record(c,actor,operation,result['language_id'],result);return result
            if path.startswith('/registry-theme/'):
                if operation=='get_all_themes':return [theme_wire(x) for x in c.execute(select(themes)).mappings()]
                if operation=='create_theme':
                    if c.execute(select(themes.c.id).where(themes.c.name==p['theme_mnemonic'])).first():raise RegistryError('RTH-ERR-002')
                    key=str(uuid.uuid4());c.execute(insert(themes).values(id=key,name=p['theme_mnemonic'],factory=False));items=p['theme_values']
                else:
                    row=self.one(c,themes,p['theme_id'],'RTH-ERR-001');key=row['id']
                    if operation=='get_theme_values':return [{'theme_value_id':x['id'],'theme_id':key,'attribute_name':x['attribute'],'attribute_value':x['value']} for x in c.execute(select(values).where(values.c.theme==key).order_by(values.c.position)).mappings()]
                    if row['factory']:raise RegistryError('RTH-ERR-003' if operation=='remove_theme' else 'RTH-ERR-004')
                    c.execute(delete(values).where(values.c.theme==key))
                    if operation=='remove_theme':c.execute(delete(themes).where(themes.c.id==key));items=[]
                    elif operation=='update_theme_values':items=p['theme_attribute_values']
                    else:raise KeyError(path)
                for i,item in enumerate(items):
                    if item['attribute_name'] not in ATTRIBUTES:raise RegistryError('SYS-ERR-001')
                    value=image_value(item['attribute_value'],1200,600) if item['attribute_name']=='dashboard_image' and item['attribute_value'] else item['attribute_value']
                    c.execute(insert(values).values(id=str(uuid.uuid4()),theme=key,attribute=item['attribute_name'],value=value,position=i))
                result={'theme_id':key,'success':True};self.record(c,actor,operation,key,result);return result
            if path.startswith('/registry-config/'):
                if operation=='get_registry_configuration':
                    row=c.execute(select(configuration)).mappings().first()
                    if row is None:raise RegistryError('RCF-ERR-001')
                    return config_wire(row)
                if p.get('registry_theme_id'):self.one(c,themes,p['registry_theme_id'],'RTH-ERR-001')
                if p.get('registry_language_id'):self.one(c,languages,p['registry_language_id'],'RLG-ERR-001')
                if operation=='create_registry_configuration':
                    if c.execute(select(configuration)).first():raise RegistryError('RCF-ERR-002')
                    row=dict(singleton=1,id=str(uuid.uuid4()),name=p['registry_name'],logo=p.get('registry_logo'),favicon=p.get('registry_favicon'),theme=p.get('registry_theme_id'),language=p.get('registry_language_id'))
                    c.execute(insert(configuration).values(**row))
                elif operation=='update_registry_configuration':
                    row=self.one(c,configuration,p['configuration_id'],'RCF-ERR-001')
                    changes={target:p[source] for source,target in [('registry_name','name'),('registry_logo','logo'),('registry_favicon','favicon'),('registry_theme_id','theme'),('registry_language_id','language')] if p.get(source) is not None}
                    row.update(changes)
                    if changes:c.execute(update(configuration).where(configuration.c.id==row['id']).values(**changes))
                else:raise KeyError(path)
                if p.get('registry_language_id'):self.default_language(c,p['registry_language_id'])
                result=config_wire(row);self.record(c,actor,operation,row['id'],result);return result
            raise KeyError(path)
