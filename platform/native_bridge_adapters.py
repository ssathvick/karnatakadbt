"""Native SQL references and explicit HTTP adapters for bridge workers."""
import uuid
from urllib.parse import urlsplit
import httpx
from sqlalchemy import text
from native_bridge_reference import NativeBridgeReference
from native_bridge_payloads import payment_payloads,notification_payload
from native_bridge_reconciliation import reconcile
from native_spar_store import NativeSparStore
from native_farmer_registry import FarmerRegistry


class NativeBridgeAdapters:
    def __init__(self,bridge_engine,mapping_engine,registry_engine,*,bank_origin,registry_targets,notification_origin=None,notification_token=None,transport=None):
        self.references=NativeBridgeReference(bridge_engine);self.mapping=NativeSparStore(mapping_engine);self.registry=registry_engine;self.bank_origin=self.origin(bank_origin);self.targets=dict(registry_targets);self.notification_origin=self.origin(notification_origin) if notification_origin else None;self.notification_token=notification_token;self.transport=transport
    @staticmethod
    def origin(value):
        parsed=urlsplit(value or '')
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {'','/'} or parsed.query or parsed.fragment:raise ValueError('Explicit service origin required')
        return value.rstrip('/')
    def sponsor(self,envelope):return self.references.sponsor(envelope)
    def bank(self,method,configuration,payload,key):
        if configuration['sponsor_bank_code']!='EXAMPLE_BANK' or method not in {'check_funds','block_funds','initiate_payment'}:raise ValueError('Explicit bank capability unavailable')
        with httpx.Client(trust_env=False,follow_redirects=False,timeout=20,transport=self.transport) as http:
            response=http.post(self.bank_origin+'/'+method,json=payload,headers={'Idempotency-Key':key});response.raise_for_status();return response.json()
    def resolve_financial(self,identifiers):
        output=[]
        with self.mapping.engine.connect() as c:self.mapping._resolve(c,[{'id':identifier,'reference_id':str(uuid.uuid4()),'scope':'details'} for identifier in identifiers],output)
        return [{'id':identifier,'fa':row.get('fa'),'name':row.get('name')} for identifier,row in zip(identifiers,output)]
    def resolve_geo(self,envelope,payments):
        target=self.targets.get(envelope['target_registry'])
        if not target:raise ValueError('Explicit native registry geography mapping required')
        result=[]
        with self.registry.connect() as c:
            for payment in payments:
                if target.get('driver')=='native_farmer_registry':
                    value=FarmerRegistry(self.registry).geography(c,payment['beneficiary_id'])
                    result.append(dict(value,beneficiary_id=payment['beneficiary_id'],disbursement_id=payment['id'],beneficiary_name=payment.get('beneficiary_name')))
                    continue
                rows=c.execute(text("SELECT data FROM public.console_record_snapshots WHERE kind='current' AND register_id=:register AND (record_id=:identifier OR link_id=:identifier OR subject_id=:identifier) LIMIT 2"),{'register':target['register_id'],'identifier':payment['beneficiary_id']}).scalars().all()
                if len(rows)!=1:raise ValueError('Unambiguous current beneficiary registry record required')
                data=rows[0];value={}
                for field,path in target['fields'].items():
                    item=data
                    for part in path:item=item.get(part) if isinstance(item,dict) else None
                    if field.startswith('administrative_zone_') and item in {None,''}:raise ValueError('Complete native registry geography required')
                    value[field]=str(item) if item is not None else None
                result.append(dict(value,beneficiary_id=payment['beneficiary_id'],disbursement_id=payment['id'],beneficiary_name=payment.get('beneficiary_name')))
        return result
    def allocate(self,*args):return self.references.allocate(*args)
    def payment_payloads(self,*args):return payment_payloads(*args,agency_account=self.references.agency_account)
    def notification_payload(self,*args):return notification_payload(*args)
    def notify(self,kind,identifier,payload,recipient):
        if not self.notification_origin or not self.notification_token:raise ValueError('Explicit notification delivery capability required')
        with httpx.Client(trust_env=False,follow_redirects=False,timeout=20,transport=self.transport) as http:
            response=http.post(self.notification_origin+'/notifications',json={'notification_id':identifier,'notification_type':kind.upper()+'_NOTIFICATION','payload':payload,'recipient':recipient},headers={'Authorization':'Bearer '+self.notification_token,'Idempotency-Key':identifier});response.raise_for_status();return response.json()
    def reconcile(self,worker,c,statement):return reconcile(worker,c,statement,account_configuration=self.references.account_configuration)
