'use strict';
const $=selector=>document.querySelector(selector);
const el=(tag,text,attrs={})=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;for(const [key,value]of Object.entries(attrs))node.setAttribute(key,value);return node;};
const friendly=value=>value.replaceAll('_',' ').replace(/\b\w/g,ch=>ch.toUpperCase());
$('#signout').onclick=async()=>{try{const response=await fetch('/console/logout',{method:'POST',credentials:'same-origin',headers:{'x-csrf-token':csrf()}});if(!response.ok)throw Error('Sign-out could not be completed.');location.replace('/console/');}catch(error){$('#notice').textContent=error.message;}};
const names={'registry-config':'Registry settings','registry-theme':'Appearance','registry-language':'Languages','register-metadata':'Register definitions','register-data':'Beneficiary records','intake-form-metadata':'Intake forms','intake-form-data':'Intake submissions','change-requests':'Change requests','change-requests-core-data':'Core record changes','register-tab-metadata':'Record layouts','register-section-metadata':'Record sections','computation-score':'Scoring rules','completion-score':'Completion scores','ingestion-config':'Incoming programme data','ingestion-data':'Incoming messages','outgestion-config':'Outgoing subscriptions','outgestion-data':'Outgoing messages','awe-policy-config':'Approval policies','input-mechanism-metadata':'Input channels','data-model':'Data models','registry-document':'Documents'};
let contract,identity,activeGroup,operations=[];
Object.assign(names,{'geo':'Geographic hierarchy','attributes':'Reference code lists'});
Object.assign(names,{'applications':'Applications, roles and permissions','login-providers':'Identity providers','auth':'Login providers','data-policies':'Access policies','consent-partners':'Partner sharing policies','consent-approvals':'Consent approval tasks','consent-decisions':'Consent decision records','partner-requests':'Onboarding and key requests','partners':'Partner directory'});
function resolve(value){if(value?.$ref)return resolve(contract.components.schemas[value.$ref.split('/').pop()]);if(value?.anyOf)return resolve(value.anyOf.find(item=>item.type!=='null'));return value||{};}
function csrf(){const item=document.cookie.split(';').map(item=>item.trim()).find(item=>item.startsWith('X-CSRF-Token='));return item?decodeURIComponent(item.slice(item.indexOf('=')+1)):'';}
async function api(path,body,method='POST'){
 if(body?.request_body?.pagination_request&&body.request_body.pagination_request.search_text===undefined)body.request_body.pagination_request.search_text='';
 const response=await fetch(path,{method,credentials:'same-origin',cache:'no-store',headers:{'content-type':'application/json','x-csrf-token':csrf()},...(!['GET','HEAD'].includes(method)&&body!==undefined?{body:JSON.stringify(body)}:{})});
 const value=response.status===204?null:await response.json();
 if(response.status===401)throw Error('Your session has expired. Sign in again.');
 if(!response.ok)throw Error(response.status===403?'You do not have permission for this operation.':typeof value?.detail==='string'?value.detail:typeof value?.error==='string'?value.error:'The request could not be completed.');
 if(value?.response_header&&value.response_header.response_status!=='SUCCESS')throw Error(value.response_header.response_error_message||'The operation could not be completed.');
 if(!['GET','HEAD'].includes(method)&&!/\/(get_|search_|check_|count_|list_|render_)/.test(path))window.dispatchEvent(new Event('kdbt-data-changed'));
 return value;
}
function render(value,pagination){
 value=redactDisplay(value);
 const root=$('#results');root.replaceChildren();const article=el('article');
 if(pagination)article.append(el('p',`${pagination.number_of_items??0} records · ${pagination.number_of_pages??0} pages`));
 const wrapper=value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).every(key=>['attributes','attribute_values','documents','total','count','partners','requests','items','events','applications','roles','permissions','role_permissions','policies','providers','login_providers','tasks','page','page_size'].includes(key));
 const collections=wrapper?Object.values(value).filter(Array.isArray):[];
 const rows=Array.isArray(value)?value:collections.length===1?collections[0]:[value];
 if(!rows.length){article.append(el('p','No records found.',{class:'empty'}));root.append(article);return;}
 const objects=rows.filter(row=>row&&typeof row==='object'&&!Array.isArray(row));
 if(objects.length===rows.length){
  const fields=[...new Set(objects.flatMap(row=>Object.keys(row).filter(key=>row[key]===null||typeof row[key]!=='object')))];
  const table=el('table'),head=el('tr');
  for(const name of fields.slice(0,8))head.append(el('th',friendly(name),{scope:'col'}));head.append(el('th','Details',{scope:'col'}));
  const thead=el('thead');thead.append(head);table.append(thead);const tbody=el('tbody');
  for(const row of objects){const tr=el('tr');for(const name of fields.slice(0,8))tr.append(el('td',row[name]===null?'—':String(row[name]??'')));const td=el('td'),details=el('details');details.append(el('summary','Full record'),el('pre',JSON.stringify(row,null,2)));td.append(details);tr.append(td);tbody.append(tr);}
  table.append(tbody);article.append(table);
 }else article.append(el('pre',JSON.stringify(value,null,2)));
 root.append(article);
}
function redactDisplay(value){
 if(Array.isArray(value))return value.map(redactDisplay);
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([name,item])=>[name,/(^|_)(password|secret|private_key|access_token|refresh_token|id_token)$/.test(name)?'[hidden]':redactDisplay(item)]));
 return value;
}
function field(name,node,required,initial){node=resolve(node);const label=el('label',friendly(name)+(required?' *':''));label.append(el('small',node.description||''));let input;if(node.enum||node.type==='boolean'){input=el('select');input.append(el('option','Choose…',{value:''}));for(const choice of node.enum||[true,false])input.append(el('option',String(choice),{value:String(choice)}));}else if(node.type==='object'||node.properties||node.type==='array'){input=el('textarea');input.dataset.json='true';label.append(el('small','Enter valid JSON. Use {} for an object or [] for a list.'));}else{input=el('input');input.type=['integer','number'].includes(node.type)?'number':node.format==='password'||/(^|_)(password|secret|private_key|access_token|refresh_token)$/.test(name)?'password':'text';if(input.type==='password')input.autocomplete='off';if(input.type==='number')input.step=node.type==='integer'?'1':'any';if(node.minimum!==undefined)input.min=node.minimum;if(node.maximum!==undefined)input.max=node.maximum;if(node.maxLength)input.maxLength=node.maxLength;}input.name=name;input.required=required;input.dataset.kind=node.type||'string';if(initial!==undefined&&initial!==null)input.value=typeof initial==='object'?JSON.stringify(initial,null,2):String(initial);label.append(input);return label;}
function openUpload(operation){
 $('#operation-title').textContent='Upload documents';$('#operation-help').textContent='Select files to upload. The server validates their contents and your permissions.';$('#fields').replaceChildren();$('#form-error').textContent='';
 const files=el('input',undefined,{type:'file',name:'documents',multiple:'multiple',required:'required'});const label=el('label','Documents *');label.append(files);$('#fields').append(label);
 const body=resolve(operation.spec.requestBody.content['multipart/form-data'].schema);$('#fields').append(field('bucket',body.properties?.bucket||{type:'string'},true,resolve(body.properties?.bucket).default||'documents'));
 $('#submit').textContent='Upload';$('#operation-form').onsubmit=async event=>{event.preventDefault();$('#submit').disabled=true;$('#form-error').textContent='';try{const data=new FormData();for(const file of files.files)data.append('documents',file);data.append('bucket',$('#fields [name="bucket"]').value);const response=await fetch(operation.path,{method:'POST',credentials:'same-origin',headers:{'x-csrf-token':csrf()},body:data});const value=await response.json();if(!response.ok||value.response_header?.response_status!=='SUCCESS')throw Error(value.response_header?.response_error_message||'The upload could not be completed.');$('#operation').close();render(value.response_body?.response_payload);$('#notice').textContent='Documents uploaded.';}catch(error){$('#form-error').textContent=error.message;}finally{$('#submit').disabled=false;}};$('#operation').showModal();
}
function openOperation(operation){if(operation.spec.requestBody?.content?.['multipart/form-data'])return openUpload(operation);const {path,method,spec}=operation;$('#operation-title').textContent=spec.summary||friendly(path.split('/').pop());$('#operation-help').textContent=operation.read?'Load records using the filters below.':'This operation changes application data. Review all values before saving.';$('#fields').replaceChildren();$('#form-error').textContent='';const body=resolve(spec.requestBody?.content?.['application/json']?.schema),enveloped=!!body.properties?.request_body,request=enveloped?resolve(body.properties.request_body):body,payload=enveloped?resolve(request.properties?.request_payload):body;const fields=[];
for(const [name,node]of Object.entries(payload.properties||{})){const required=(payload.required||[]).includes(name);$('#fields').append(field(name,node,required,resolve(node).default));fields.push({name,node,where:'payload'});}
if(request.properties?.pagination_request){const page=el('fieldset');page.append(el('legend','Pagination and search'));const schema=resolve(request.properties.pagination_request);for(const [name,node]of Object.entries(schema.properties||{})){page.append(field(name,node,(schema.required||[]).includes(name),resolve(node).default??(name==='current_page'?1:name==='page_size'?20:undefined)));fields.push({name,node,where:'pagination'});}$('#fields').append(page);}
for(const parameter of spec.parameters||[]){if(!['query','path'].includes(parameter.in))continue;$('#fields').append(field(parameter.name,parameter.schema,parameter.required,resolve(parameter.schema).default));fields.push({name:parameter.name,node:parameter.schema,where:parameter.in});}
$('#submit').textContent=operation.read?'Load':'Save changes';$('#operation-form').onsubmit=async event=>{
 event.preventDefault();$('#submit').disabled=true;$('#form-error').textContent='';
 try{
  const data={},pagination={},query=new URLSearchParams();let url=path;
  for(const item of fields){const input=$('#fields').querySelector('[name="'+item.name+'"]');if(input.value==='')continue;const value=input.dataset.json?JSON.parse(input.value):['number','integer'].includes(input.dataset.kind)?Number(input.value):input.dataset.kind==='boolean'?input.value==='true':input.value;if(item.where==='payload')data[item.name]=value;else if(item.where==='pagination')pagination[item.name]=value;else if(item.where==='query')query.set(item.name,String(value));else url=url.replace('{'+item.name+'}',encodeURIComponent(String(value)));}
  if(url.includes('{'))throw Error('Complete the required resource identifiers.');
  const envelope=enveloped?{request_header:{sender_app_mnemonic:'KDBT_NATIVE_CONSOLE',sender_app_url:location.origin,request_id:crypto.randomUUID(),request_timestamp:new Date().toISOString()},request_body:{request_payload:data,...(request.properties?.pagination_request?{pagination_request:pagination}:{})}}:spec.requestBody?data:undefined;
  const value=await api(url+(query.size?'?'+query:''),envelope,method.toUpperCase());$('#operation').close();render(value?.response_body?.response_payload??value?.response_body??value,value?.response_body?.pagination_response);$('#notice').textContent=operation.read?'Records loaded.':'Changes saved.';
 }catch(error){$('#form-error').textContent=error.message;}finally{$('#submit').disabled=false;}
};$('#operation').showModal();}
function group(name){activeGroup=name;$('#title').textContent=names[name]||friendly(name.replaceAll('-',' '));$('#description').textContent='Choose an action. Access is checked against your current staff permissions.';$('#actions').replaceChildren();$('#results').replaceChildren();document.querySelectorAll('nav button').forEach(button=>button.setAttribute('aria-current',button.dataset.group===name?'page':'false'));for(const operation of operations.filter(item=>item.group===name)){const button=el('button',operation.spec.summary||friendly(operation.path.split('/').pop()),{type:'button'});button.dataset.path=operation.path;button.dataset.method=operation.method;button.onclick=()=>openOperation(operation);$('#actions').append(button);}}
$('#cancel').onclick=()=>$('#operation').close();$('#navigation-search').oninput=event=>{const value=event.target.value.toLowerCase();document.querySelectorAll('nav button').forEach(button=>button.hidden=!button.textContent.toLowerCase().includes(value));};
(async()=>{
 contract=await(await fetch('/console/contract.json',{cache:'no-store'})).json();const response=await fetch('/console/session',{credentials:'same-origin',cache:'no-store'});
 if(response.status===401){$('#notice').textContent='Sign in with your staff account to continue.';$('#identity').append(el('a','Sign in',{href:'/console/login'}));return;}
 if(!response.ok)throw Error('Staff authentication is unavailable.');identity=await response.json();$('#identity').textContent=identity.name||'Signed in';const permissions=new Set(identity.permissions);const policy=await(await fetch('/console/permissions.json',{cache:'no-store'})).json();
 for(const [path,methods]of Object.entries(contract.paths))for(const [method,spec]of Object.entries(methods)){
  if(!['get','post','put','patch','delete'].includes(method))continue;const authorization=policy[path];if(!authorization||authorization.scheme!=='console')continue;
  if(!(authorization.required_permissions||[]).every(permission=>permissions.has(permission)))continue;
  const name=path.startsWith('/consent/v1/awe/')?'consent-approvals':path.startsWith('/consent/v1/partners')?'consent-partners':path.startsWith('/consent/v1/decisions')?'consent-decisions':path.startsWith('/partners/requests')?'partner-requests':path.split('/')[1];
  operations.push({path,method,spec,group:name,read:method==='get'||/\/(get_|search_|check_|count_|list_|render_)/.test(path)});
 }
 for(const name of [...new Set(operations.map(item=>item.group))]){const button=el('button',names[name]||friendly(name.replaceAll('-',' ')),{type:'button'});button.dataset.group=name;button.onclick=()=>group(name);$('nav').append(button);}
 $('#notice').textContent='';if(operations.length){const params=new URLSearchParams(location.search),selected=operations.find(item=>item.path===params.get('operation')&&item.method===(params.get('method')||'get').toLowerCase());group(selected?.group||operations.find(item=>item.group===params.get('workspace'))?.group||operations.find(item=>item.group==='register-data')?.group||operations[0].group);if(selected){openOperation(selected);for(const input of $('#fields').querySelectorAll('[name]')){if(params.has(input.name))input.value=params.get(input.name);}if(params.get('load')==='1'&&selected.read&&selected.method==='get')$('#operation-form').requestSubmit();}}else $('#notice').textContent='No administration operations are assigned to your account.';
})().catch(error=>$('#notice').textContent=error.message);
