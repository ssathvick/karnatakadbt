"""Resolve explicit console rules; an absent permission list never means public."""
import json
from pathlib import Path

AWE_PATHS=frozenset('/awe/'+name for name in ['list_my_tasks','list_tasks_for_request','my_task_stats','submit_task_decision','claim_task','get_request','get_request_events'])

def required_permissions(path,contract,method='POST'):
    operation=contract['paths'].get(path,{}).get(method.lower(),{})
    declared=operation.get('x-required-permissions')
    if declared is not None:return frozenset(declared)
    rules=json.loads(Path(__file__).with_name('registry_auth_contract.json').read_text())
    rule=rules.get(path,{})
    if path=='/awe/webhooks/decision' and method=='POST' and operation and rule.get('scheme')=='hmac-sha256' and rule.get('method')=='POST':return frozenset()
    if path=='/registrant-auth/callback' and method=='GET' and operation and rule.get('scheme')=='oidc-single-use-state' and rule.get('method')=='GET':return frozenset()
    if path=='/ping' and method=='GET' and operation and rule.get('scheme')=='public-health' and rule.get('method')=='GET' and rule.get('required_permissions')==[]:return frozenset()
    if path in AWE_PATHS and method=='POST' and rule.get('scheme')=='console' and rule.get('method')=='POST' and rule.get('required_permissions')==[]:
        return frozenset()
    raise ValueError('Explicit console authentication contract is required: '+path)
