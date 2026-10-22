"""Compile interface DTOs using Pydantic; no application framework is imported."""
import datetime,typing,copy
from pydantic import ConfigDict,Field,create_model

class ContractModels:
    def __init__(self,contract):
        self.contract=contract;self.definitions=contract['components']['schemas'];self.models={};self.building=set()
    def model(self,name):
        if name in self.models:return self.models[name]
        if name in self.building:raise ValueError('Recursive DTO requires explicit support: '+name)
        schema=self.definitions[name]
        if name=='RecordHistoryData':
            # Intake-origin history legitimately has no staff change request.
            # Preserve the captured interface file and publish the corrected
            # nullable response field through the own generated OpenAPI model.
            schema=copy.deepcopy(schema)
            schema['properties']['change_request_id']={'anyOf':[{'type':'string'},{'type':'null'}],'title':'Change Request Id'}
        if schema.get('type')!='object' and 'properties' not in schema:
            self.models[name]=self.annotation(schema);return self.models[name]
        self.building.add(name);fields={};required=set(schema.get('required',[]))
        for key,node in schema.get('properties',{}).items():
            default=... if key in required else node.get('default',None)
            options={}
            for source,target in [('minimum','ge'),('maximum','le'),('exclusiveMinimum','gt'),('exclusiveMaximum','lt'),('minLength','min_length'),('maxLength','max_length'),('minItems','min_length'),('maxItems','max_length'),('pattern','pattern')]:
                if source in node:options[target]=node[source]
            fields[key]=(self.annotation(node),Field(default=default,**options))
        model=create_model(name,__config__=ConfigDict(extra='allow' if schema.get('additionalProperties') is True else 'ignore'),**fields)
        self.models[name]=model;self.building.remove(name);return model
    def annotation(self,node):
        if '$ref' in node:return self.model(node['$ref'].split('/')[-1])
        if 'anyOf' in node:return typing.Union[tuple(self.annotation(x) for x in node['anyOf'])]
        if 'enum' in node:return typing.Literal[tuple(node['enum'])]
        kind=node.get('type')
        if kind=='array':return list[self.annotation(node.get('items',{}))]
        if kind=='object':return dict[str,self.annotation(node.get('additionalProperties',{})) if isinstance(node.get('additionalProperties'),dict) else typing.Any]
        if kind=='string':return datetime.datetime if node.get('format')=='date-time' else str
        return {'integer':int,'number':float,'boolean':bool,'null':type(None)}.get(kind,typing.Any)
    def request_for(self,path):
        root=self.contract['paths'][path]['post']['requestBody']['content']['application/json']['schema']['$ref']
        return self.model(root.split('/')[-1])
    def response_for(self,path):
        root=self.contract['paths'][path]['post']['responses']['200']['content']['application/json']['schema']['$ref']
        return self.model(root.split('/')[-1])
