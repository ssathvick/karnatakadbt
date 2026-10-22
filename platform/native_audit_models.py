"""Independent CloudEvents-compatible audit models and column projection."""
from datetime import datetime,timezone
from typing import Any,Literal
from uuid import uuid4
from pydantic import BaseModel,ConfigDict,Field

class AuditActor(BaseModel):
    model_config=ConfigDict(extra='allow')
    id:str
    type:Literal['user','system','service','anonymous']='user'
    name:str|None=None
    roles:list[str]=Field(default_factory=list)
    ip:str|None=None
    session_id:str|None=None

class AuditResource(BaseModel):
    model_config=ConfigDict(extra='allow')
    type:str
    id:str|None=None

class AuditData(BaseModel):
    model_config=ConfigDict(extra='allow')
    actor:AuditActor
    action:str
    outcome:Literal['success','failure','denied']
    resource:AuditResource|None=None
    reason:str|None=None

class AuditEvent(BaseModel):
    model_config=ConfigDict(extra='allow')
    specversion:Literal['1.0']='1.0'
    id:str=Field(default_factory=lambda:str(uuid4()))
    source:str
    type:str
    subject:str|None=None
    time:datetime=Field(default_factory=lambda:datetime.now(timezone.utc))
    datacontenttype:str='application/json'
    traceparent:str|None=None
    data:AuditData

    def occurred_at(self):
        return self.time.replace(tzinfo=timezone.utc) if self.time.tzinfo is None else self.time.astimezone(timezone.utc)

    def record(self):
        data=self.data.model_dump(mode='json',exclude_none=True);extras={}
        for field,value in data.items():
            if field in {'action','outcome','reason'}:continue
            if field in {'actor','resource'}:
                value={k:v for k,v in value.items() if k not in {'id','type'} and v is not None and v not in ('',[],{})}
                if not value:continue
            extras[field]=value
        trace=self.traceparent.split('-') if self.traceparent else []
        return {'id':self.id,'occurred_at':self.occurred_at(),'source':self.source,'type':self.type,'subject':self.subject,
                'actor_type':self.data.actor.type,'actor_id':self.data.actor.id,'resource_type':self.data.resource.type if self.data.resource else None,
                'resource_id':self.data.resource.id if self.data.resource else None,'action':self.data.action,'outcome':self.data.outcome,
                'reason':self.data.reason,'trace_id':trace[1] if len(trace)>=3 else None,'details':extras or None}

class AuditBatch(BaseModel):
    events:list[AuditEvent]

class AuditErrorDetail(BaseModel):
    errorCode:str
    message:str

class AuditEnvelope(BaseModel):
    id:str
    version:str='1.0'
    responsetime:str
    errors:list[AuditErrorDetail]=Field(default_factory=list)

class AuditErrorResponse(AuditEnvelope):
    response:None=None

class AuditAccepted(BaseModel):
    accepted:str

class AuditBatchAccepted(BaseModel):
    accepted:list[str]
    count:int

class AuditAcceptedResponse(AuditEnvelope):
    response:AuditAccepted

class AuditBatchAcceptedResponse(AuditEnvelope):
    response:AuditBatchAccepted

class AuditStatus(BaseModel):
    status:str

class AuditHealthResponse(AuditEnvelope):
    response:AuditStatus

class AuditVersion(BaseModel):
    service_version:str
    build_time:str
    git_commit:str

class AuditVersionResponse(AuditEnvelope):
    response:AuditVersion

class AuditConfiguration(BaseModel):
    service_id:str
    api_version:str
    ingest:dict[str,Any]
    kafka:dict[str,Any]
    database:dict[str,Any]

class AuditConfigResponse(AuditEnvelope):
    response:AuditConfiguration
