"""Independent, durable numeric identifiers with configurable validation rules.

The checksum is Verhoeff's published dihedral-group algorithm. Allocation uses
our Core ledger and a permutation cursor, not a third-party G2P runtime.
"""
import datetime,hashlib,hmac,itertools,secrets,time
from sqlalchemy import (MetaData,Table,Column,String,Integer,Numeric,JSON,Index,
                        select,insert,update,func)

metadata=MetaData()
namespaces=Table('identifier_namespaces',metadata,
    Column('name',String(64),primary_key=True),Column('length',Integer,nullable=False),
    Column('filters',JSON,nullable=False),Column('cursor',Numeric(40,0),nullable=False),
    Column('offset',Numeric(40,0),nullable=False),Column('multiplier',Numeric(40,0),nullable=False))
ledger=Table('identifier_ledger',metadata,
    Column('namespace',String(64),primary_key=True),Column('value',String(32),primary_key=True),
    Column('state',String(12),nullable=False),Column('created_at',String(64),nullable=False),
    Column('issued_at',String(64)))
Index('ix_identifier_ready',ledger.c.namespace,ledger.c.state)

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()

def product(a,b):
    """D5 multiplication using rotations (0..4) and reflections (5..9)."""
    return ((a%5)+(b%5)*(1 if a<5 else -1))%5 + (5 if (a<5)!=(b<5) else 0)

PERMUTATION=(1,5,7,6,2,8,3,0,9,4)
def permute(digit,rounds):
    for _ in range(rounds%8):digit=PERMUTATION[digit]
    return digit

def checksum(prefix):
    state=0
    for i,d in enumerate(reversed(prefix)):state=product(state,permute(int(d),i+1))
    return str((-state)%5 if state<5 else state)

def checksum_valid(value):
    state=0
    for i,d in enumerate(reversed(value)):state=product(state,permute(int(d),i))
    return state==0

def repetend(prime):
    remainder=1;digits=[]
    while True:
        digit,remainder=divmod(remainder*10,prime);digits.append(str(digit))
        if remainder==1:return ''.join(digits)

CYCLIC_PATTERNS=tuple(repetend(p) for p in (7,17,19,23,29,47,59,61,97))

def mixed_prefix(number,width,seed):
    """Keyed decimal Feistel permutation: opaque prefixes without ID reuse.

    This is an identifier randomization mechanism, not an authentication token
    or a general encryption interface. Every input still has one unique output.
    """
    key=bytes.fromhex(seed)
    if width==1:
        order=sorted(range(10),key=lambda n:hmac.digest(key,bytes([n]),'sha256'))
        return str(order[number])
    digits=str(number).zfill(width);lw=width//2;rw=width-lw
    left,right=int(digits[:lw]),int(digits[lw:])
    for round_number in range(10):
        salt=bytes([round_number])+right.to_bytes(16,'big')
        shift=int.from_bytes(hmac.digest(key,salt,'sha256'),'big')
        left,right=right,(left+shift)%(10**lw);lw,rw=rw,lw
    return str(left).zfill(lw)+str(right).zfill(rw)

def valid(value,length,rules):
    if len(value)!=length or not value.isdecimal():return False
    if value[0] in rules['not_start_with'] or not checksum_valid(value):return False
    digits=list(map(int,value))
    for size in (rules['sequence_limit'],):
        # Like the deployed contract, a one-digit sequence is rejected only
        # when the adjacent-digit scan actually reaches a matching run.
        for direction in (1,-1):
            run=1
            for a,b in zip(digits,digits[1:]):
                run=run+1 if b-a==direction else 1
                if run>=size:return False
    gap=rules['repeating_limit']
    if any(digits[i]==digits[j] for i in range(len(digits)) for j in range(i+1,min(len(digits),i+gap))):return False
    size=rules['repeating_block_limit'];first={}
    for i in range(len(value)-size+1):
        block=value[i:i+size]
        if block in first and i-first[block]>=size:return False
        first.setdefault(block,i)
    if any(digit%2==0 and len(list(group))>=rules['conjugative_even_digits_limit']
           for digit,group in itertools.groupby(digits,key=lambda d:d%2)):
        return False
    for key,reverse in [('digits_group_limit',False),('reverse_digits_group_limit',True)]:
        size=rules[key]
        if size and len(value)>=size*2 and value[:size]==(value[-size:][::-1] if reverse else value[-size:]):return False
    return not any(x and x in value for x in [*rules['restricted_numbers'],*CYCLIC_PATTERNS])

class IdentifierStore:
    def __init__(self,engine):self.engine=engine

    def seed_namespace(self,name,length,rules):
        space=10**(length-1)
        with self.engine.begin() as c:
            prior=c.execute(select(namespaces).where(namespaces.c.name==name)).mappings().first()
            if prior:
                if '_permutation_key' not in prior['filters']:
                    if int(prior['cursor']):raise RuntimeError('Existing generated namespace needs an explicit key migration')
                    c.execute(update(namespaces).where(namespaces.c.name==name).values(filters={**rules,'_permutation_key':secrets.token_hex(32)}))
                return
            c.execute(insert(namespaces).values(name=name,length=length,filters={**rules,'_permutation_key':secrets.token_hex(32)},cursor=0,
                offset=secrets.randbelow(space),multiplier=472882049))

    def configure(self,config):
        rules={k:v for k,v in config.items() if k not in ['id_types','pool_min_threshold','pool_generation_batch_size','pool_check_interval_seconds','exhaustion_max_attempts','sub_batch_size']}
        for name,settings in config['id_types'].items():self.seed_namespace(name,settings['id_length'],rules)

    def _insert(self,c,rows):
        if not rows:return
        if self.engine.dialect.name=='postgresql':from sqlalchemy.dialects.postgresql import insert as upsert
        else:from sqlalchemy.dialects.sqlite import insert as upsert
        c.execute(upsert(ledger).values(rows).on_conflict_do_nothing(index_elements=['namespace','value']))

    def replenish(self,name,target=128,budget=.3):
        deadline=time.monotonic()+budget
        with self.engine.begin() as c:
            state=c.execute(select(namespaces).where(namespaces.c.name==name).with_for_update(skip_locked=True)).mappings().first()
            if not state:return 0
            cursor=int(state['cursor']);limit=10**(state['length']-1);rows=[]
            while cursor<limit and len(rows)<target:
                number=(int(state['multiplier'])*cursor+int(state['offset']))%limit;cursor+=1
                prefix=mixed_prefix(number,state['length']-1,state['filters']['_permutation_key']);value=prefix+checksum(prefix)
                if valid(value,state['length'],state['filters']):
                    rows.append({'namespace':name,'value':value,'state':'ready','created_at':now(),'issued_at':None})
                if time.monotonic()>deadline:break
            self._insert(c,rows)
            c.execute(update(namespaces).where(namespaces.c.name==name).values(cursor=cursor))
            return len(rows)

    def take(self,name):
        with self.engine.begin() as c:
            available=select(ledger.c.value).where(ledger.c.namespace==name,ledger.c.state=='ready').limit(1).with_for_update(skip_locked=True).scalar_subquery()
            return c.execute(update(ledger).where(ledger.c.namespace==name,ledger.c.value==available,ledger.c.state=='ready')
                .values(state='issued',issued_at=now()).returning(ledger.c.value)).scalar_one_or_none()

    def issue(self,name):
        value=self.take(name)
        if value is not None:return value,None
        self.replenish(name)
        value=self.take(name)
        if value is not None:return value,None
        with self.engine.connect() as c:
            state=c.execute(select(namespaces).where(namespaces.c.name==name)).mappings().one()
        return None,'exhausted' if int(state['cursor'])>=10**(state['length']-1) else 'busy'

    def ready_count(self,name):
        with self.engine.connect() as c:return c.execute(select(func.count()).select_from(ledger).where(ledger.c.namespace==name,ledger.c.state=='ready')).scalar_one()
