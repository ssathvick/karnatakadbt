"""Native change-triggered score admission rules; workers remain separate."""
import json

def changed_paths(payloads):
    found=set()
    def walk(item,prefix=''):
        for key,value in item.items():
            if key in {'edit_action','internal_record_id','link_internal_record_id'}:continue
            path=prefix+'.'+key if prefix else key
            if isinstance(value,dict) and value:walk(value,path)
            else:found.add(path)
    for item in payloads or []:
        if isinstance(item,dict) and item.get('edit_action')!='NO_CHANGE':walk(item)
    return found

def path_value(record,path):
    current=record
    for part in path.split('.') if path else []:
        current=current.get(part) if isinstance(current,dict) else getattr(current,part,None)
        if current is None:break
    return current

def contributing_snapshot(record,paths):return {path:path_value(record,path) for path in paths}

def should_queue(current,touched,previous=None):
    relevant=[path for path in current if any(path==leaf or path.startswith(leaf+'.') or leaf.startswith(path+'.') for leaf in touched)]
    def present(value):return value is not None and not (isinstance(value,str) and not value.strip()) and not (isinstance(value,(list,tuple,dict)) and not value)
    if not relevant or not any(present(current[path]) for path in relevant):return False
    return previous is None or any(path not in previous or json.dumps(previous[path],sort_keys=True,default=str)!=json.dumps(current[path],sort_keys=True,default=str) for path in relevant)
