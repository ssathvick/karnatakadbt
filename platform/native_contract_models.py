"""Build Pydantic DTOs from trusted local service contracts, without eval."""
from datetime import date,datetime
from typing import Any,Literal,Union
from pydantic import Field,create_model
class ContractModels:
    def __init__(self,contract):self.schemas=contract['components']['schemas'];self.cache={};self.active=set()
    def type(self,spec,name='Payload'):
        if '$ref' in spec:
            prefix='#/components/schemas/'
            if not spec['$ref'].startswith(prefix):raise ValueError('Only local contract references are supported')
            key=spec['$ref'][len(prefix):]
            if key in self.cache:return self.cache[key]
            if key in self.active:raise ValueError('Recursive DTO requires an explicit native model')
            self.active.add(key)
            try:self.cache[key]=self.type(self.schemas[key],key);return self.cache[key]
            finally:self.active.remove(key)
        if 'const' in spec:return Literal[spec['const']]
        if 'enum' in spec:return Literal[tuple(spec['enum'])]
        alternatives=spec.get('anyOf') or spec.get('oneOf')
        if alternatives:return Union[tuple(self.type(item,name+'Choice') for item in alternatives)]
        kind=spec.get('type')
        if kind=='null':return type(None)
        if kind=='array':return list[self.type(spec.get('items',{}),name+'Item')]
        if kind=='object' or 'properties' in spec:
            if 'properties' not in spec:return dict[str,Any]
            fields={};required=set(spec.get('required',[]))
            for key,value in spec['properties'].items():
                annotation=self.type(value,name+'_'+key);default=... if key in required else value.get('default',None)
                limits={target:value[source] for source,target in [('minLength','min_length'),('maxLength','max_length'),('minimum','ge'),('maximum','le'),('exclusiveMinimum','gt'),('exclusiveMaximum','lt'),('minItems','min_length'),('maxItems','max_length')] if source in value}
                fields[key]=(annotation,Field(default=default,**limits))
            return create_model(name,**fields)
        if kind=='string':return datetime if spec.get('format')=='date-time' else date if spec.get('format')=='date' else str
        if kind=='integer':return int
        if kind=='number':return float
        if kind=='boolean':return bool
        if not spec:return Any
        raise ValueError('Unsupported native contract DTO')
