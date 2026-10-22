"""Keep original human-facing bookmarks without changing JSON API contracts.

Only browser HTML navigations are redirected. A bookmark can open a form but
cannot submit a mutation. Identifiers are encoded as query values, never routes.
"""
from urllib.parse import urlencode,unquote
from fastapi.responses import RedirectResponse

def mount_console_bookmarks(app,profile):
    if profile not in {'iam','master-data','partner','registry'}:return
    def target(path):
        parts=[unquote(value) for value in path.strip('/').split('/') if value]
        if parts and parts[0] in {'en','de','cs'}:parts=parts[1:]
        query={}
        if profile=='registry':
            pages={
                '':'/register-metadata/get_dashboard_registers',
                'configuration/registry/details':'/registry-config/get_registry_configuration',
                'configuration/registry/languages':'/registry-language/get_all_languages',
                'configuration/registry/themes':'/registry-theme/get_all_themes',
                'configuration/registry/themes/create':'/registry-theme/create_theme',
                'configuration/registers':'/register-metadata/get_all_registers',
                'configuration/intake-forms':'/intake-form-metadata/get_all_intake_forms',
                'configuration/data-models':'/data-model/get_all_data_models',
                'configuration/awe-policy-config':'/awe-policy-config/get_all_awe_policy_configurations',
                'configuration/ingest-configurations/key-paths':'/ingestion-config/get_all_incoming_key_paths',
                'configuration/ingest-configurations/manage-subscription':'/ingestion-config/get_all_subscription_activity_logs',
                'configuration/ingest-configurations/semantic-patterns':'/ingestion-config/get_all_semantic_patterns',
                'configuration/ingest-configurations/templates':'/ingestion-config/get_all_templates',
                'configuration/outgest-configurations/templates':'/outgestion-config/get_all_templates',
                'configuration/outgest-configurations/topics':'/outgestion-config/get_all_topics',
                'incoming-messages':'/ingestion-data/search_in_ingestion_data',
                'outgoing-messages':'/outgestion-data/search_in_outgestion_data',
                'change-request':'/change-requests/get_change_requests',
                'tasks/change-request':'/awe/list_my_tasks',
                'tasks/intake-form':'/awe/list_my_tasks'}
            operation=pages.get('/'.join(parts));values={}
            if len(parts)>=3 and parts[:2]==['configuration','registers']:
                values={'register_id':parts[2]};operation='/register-metadata/get_register_schema'
                if len(parts)==5:
                    group,identifier=parts[3:]
                    detail={'sections':('/register-section-metadata/get_section','section_id'),'tabs':('/register-tab-metadata/get_tab','tab_id'),'scores':('/computation-score/get_score_contributing_attributes','score_definition_id')}.get(group)
                    if detail:operation,key=detail;values[key]=identifier
            elif len(parts)>=3 and parts[:2]==['configuration','intake-forms']:
                values={'form_id':parts[2]};operation='/intake-form-metadata/get_intake_form'
                if len(parts)==5 and parts[3]=='tabs':operation='/intake-form-metadata/get_tab';values['tab_id']=parts[4]
            elif parts and parts[0]=='register' and len(parts)>=2:
                values={'register_mnemonic':parts[1]};operation='/register-data/search_in_a_register'
                if len(parts)>=3:values.update(internal_record_id=parts[2],subject_record_id=parts[2]);operation='/register-data/get_subject_record'
                if len(parts)==4 and parts[3]=='version-history':operation='/register-data/get_record_history'
                if len(parts)>=4 and parts[3]=='change-request':
                    operation='/change-requests/get_change_requests'
                    if len(parts)==5:operation='/change-requests/get_change_request';values['change_request_id']=parts[4]
            elif parts and parts[0]=='intake-form' and len(parts)>=2:
                operation='/intake-form-data/search_in_intake_form_submissions'
                if len(parts)==4 and parts[2]=='new':operation='/intake-form-metadata/render_intake_form';values['form_id']=parts[3]
                elif len(parts)==4 and parts[2]=='submission':operation='/intake-form-data/get_intake_form_submission';values['submission_id']=parts[3]
            elif len(parts)==2 and parts[0]=='change-request':operation='/change-requests/get_change_request';values['change_request_id']=parts[1]
            elif len(parts)==3 and parts[:2] in [['incoming-messages','change-request'],['tasks','change-request']]:operation='/change-requests/get_change_request';values['change_request_id']=parts[2]
            elif len(parts)==4 and parts[:2]==['tasks','intake-form']:operation='/intake-form-data/get_intake_form_submission';values['submission_id']=parts[3]
            if operation:query={'operation':operation,'method':'post',**values}
        elif profile=='master-data':
            if not parts or parts==['geo-locations']:
                query={'workspace':'geo','operation':'/geo/get_all_geo_levels','method':'post'}
            elif parts==['reference-data']:
                query={'workspace':'attributes','operation':'/attributes/get_all_attributes','method':'post'}
            elif len(parts)==2 and parts[0]=='reference-data':
                query={'workspace':'attributes','operation':'/attributes/get_attribute_values','method':'post','attribute_id':parts[1]}
        elif profile=='iam':
            if not parts or parts==['applications']:
                query={'workspace':'applications','operation':'/applications/get_applications','method':'post'}
            elif len(parts)==2 and parts[0]=='applications':
                query={'workspace':'applications','operation':'/applications/get_application','method':'post','id':parts[1]}
            elif len(parts)==4 and parts[0]=='applications' and parts[2:]==['data-policies','create']:
                query={'workspace':'data-policies','operation':'/data-policies/add_policy','method':'post','application_id':parts[1]}
            elif parts==['login-providers']:
                query={'workspace':'login-providers','operation':'/login-providers/get_login_providers','method':'post'}
            elif len(parts)==2 and parts[0]=='login-providers':
                query={'workspace':'login-providers','operation':'/login-providers/get_login_provider','method':'post','id':parts[1]}
        else:
            if not parts or parts==['partners']:
                query={'workspace':'partners','operation':'/partners','load':'1'}
            elif parts==['onboard']:
                query={'workspace':'partner-requests','operation':'/partners/requests/onboarding','method':'post'}
            elif len(parts)==2 and parts[0]=='partners':
                query={'workspace':'partners','operation':'/partners/{partner_id}','partner_id':parts[1],'load':'1'}
            elif parts==['requests']:
                query={'workspace':'partner-requests','operation':'/partners/requests','load':'1'}
            elif len(parts)==2 and parts[0]=='requests':
                query={'workspace':'partner-requests','operation':'/partners/requests/{request_id}','request_id':parts[1],'load':'1'}
        return '/console/?'+urlencode(query) if query else None

    @app.middleware('http')
    async def original_browser_bookmarks(request,call_next):
        if request.method=='GET' and 'text/html' in request.headers.get('accept',''):
            location=target(request.url.path)
            if location:
                return RedirectResponse(location,status_code=303,headers={'cache-control':'no-store','referrer-policy':'no-referrer'})
        return await call_next(request)
