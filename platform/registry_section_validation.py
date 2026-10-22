"""Validate proposed fields against editable section bindings and persisted columns."""
from registry_domain_validation import invalid

CONTROLS={'edit_action','internal_record_id','link_internal_record_id'}
DOCUMENTS={'docs','documents'}
CHILDREN=('panels','widgets','widget-item')
def paths(value):
    if isinstance(value,str):
        if value.strip():yield value.strip()
    elif isinstance(value,dict):
        for v in value.values():yield from paths(v)
    elif isinstance(value,list):
        for v in value:yield from paths(v)
def validate_section_payload(section,columns,proposals,has_documents):
    schema=section.get('section_ui_schema');key=section['section_id']
    def bad(reason):invalid(f"Invalid section payload configuration for section '{key}': {reason}")
    if not isinstance(schema,dict):bad('section_ui_schema must be an object')
    if schema.get('section-editable') is False:bad('section is not editable')
    if not isinstance(schema.get('panels'),list) or not schema['panels']:bad('section_ui_schema has no panels')
    allowed=set()
    def widget(node):return any(k in node for k in ('widget','widget-type','widget-data-path','widget-data-columns'))
    def walk(nodes):
        if isinstance(nodes,list):
            for n in nodes:walk(n)
        elif isinstance(nodes,dict):
            if widget(nodes):
                if nodes.get('widget-readonly') is True:return
                cols=nodes.get('widget-data-columns')
                if nodes.get('widget') in {'table','dialog-table'} or nodes.get('widget-type')=='table' or isinstance(cols,list):
                    for col in cols if isinstance(cols,list) else []:
                        if isinstance(col,dict) and col.get('widget-readonly') is not True and col.get('column-key') in columns:allowed.add(col['column-key'])
                else:
                    for path in paths(nodes.get('widget-data-path')):
                        parts=[p for p in path.split('.') if p];offset=1 if parts and parts[0]==section['section_register_id'] else 0
                        if len(parts)>offset and parts[offset] in columns:allowed.add(parts[offset])
                for child in ('widgets','widget-item'):
                    if child in nodes:walk(nodes[child])
            else:
                for child in CHILDREN:
                    if child in nodes:walk(nodes[child])
    def contains(nodes,document):
        if isinstance(nodes,list):return any(contains(n,document) for n in nodes)
        if not isinstance(nodes,dict) or nodes.get('widget-readonly') is True:return False
        if document and nodes.get('widget') in DOCUMENTS:return True
        if not document and widget(nodes) and nodes.get('widget') not in DOCUMENTS and ('widget-data-path' in nodes or 'widget-data-columns' in nodes):return True
        return any(contains(nodes[k],document) for k in CHILDREN if k in nodes)
    walk(schema['panels'])
    if not allowed:
        if not contains(schema['panels'],True) or contains(schema['panels'],False):bad('section_ui_schema has no editable persisted fields')
        if not has_documents:invalid(f"Document-only section '{key}' requires at least one document")
    violations=[]
    for index,proposal in enumerate(proposals):
        unknown=sorted(set(proposal)-allowed-CONTROLS)
        if unknown:violations.append(f"row {index}: {', '.join(unknown)}")
    if violations:invalid(f"Change payload contains fields not allowed by section '{key}': {'; '.join(violations)}")
