'use strict';
// Resolve common domain identities into named choices. No token or beneficiary
// data is persisted outside the page. Server authorization remains authoritative.
const lookupDefinitions={
 register_id:{path:'/register-metadata/get_all_registers',key:'register_id',labels:['register_label','register_name','register_mnemonic']},
 subject_register_id:{path:'/register-metadata/get_all_registers',key:'register_id',labels:['register_label','register_name','register_mnemonic']},
 form_id:{path:'/intake-form-metadata/get_all_intake_forms',key:'form_id',labels:['form_label','form_name','form_mnemonic']},
 intake_form_id:{path:'/intake-form-metadata/get_all_intake_forms',key:'form_id',labels:['form_label','form_name','form_mnemonic']},
 data_model_id:{path:'/data-model/get_all_data_models',key:'data_model_id',labels:['data_model_label','data_model_name','data_model_mnemonic']}
};
const lookupCache=new Map();
window.addEventListener('kdbt-data-changed',()=>lookupCache.clear());
function choices(definition){if(!lookupCache.has(definition.path)){const body={request_header:{sender_app_mnemonic:'KDBT_NATIVE_CONSOLE',sender_app_url:location.origin,request_id:crypto.randomUUID(),request_timestamp:new Date().toISOString()},request_body:{request_payload:{}}};lookupCache.set(definition.path,api(definition.path,body).then(result=>{const value=result.response_body?.response_payload;const rows=Array.isArray(value)?value:value?.attributes;if(!Array.isArray(rows))throw Error('Named choices unavailable');return rows;}).catch(error=>{lookupCache.delete(definition.path);throw error;}));}return lookupCache.get(definition.path);}
document.addEventListener('click',event=>{
 if(!event.target.closest('#actions button'))return;
 if(contract.paths['/data-policies/add_policy'])return; // IAM uses its authorized policy catalogue.
 if(contract.paths['/attributes/get_all_attributes']){
  lookupDefinitions.attribute_id={path:'/attributes/get_all_attributes',key:'attribute_id',labels:['attribute_display','attribute_code']};
  lookupDefinitions.level_id={path:'/geo/get_all_geo_levels',key:'level_id',labels:['level_mnemonic']};
  lookupDefinitions.parent_level_id=lookupDefinitions.level_id;
 }
 for(const [name,definition]of Object.entries(lookupDefinitions)){
  const input=document.querySelector('#fields input[name="'+name+'"]');if(!input)continue;
  choices(definition).then(rows=>{
   // A delayed lookup must never replace a field in a later operation dialog.
   if(!input.isConnected||!document.querySelector('#operation').open)return;
   const select=document.createElement('select');select.name=input.name;select.required=input.required;select.dataset.kind='string';
   const empty=document.createElement('option');empty.value='';empty.textContent='Choose…';select.append(empty);
   for(const row of rows){const option=document.createElement('option');option.value=String(row[definition.key]);option.textContent=definition.labels.map(key=>row[key]).find(Boolean)||option.value;select.append(option);}
   select.value=input.value;input.replaceWith(select);
  }).catch(()=>{if(input.isConnected){const hint=document.createElement('small');hint.textContent='Named choices are unavailable. Enter the identifier supplied by your administrator.';input.parentElement.append(hint);}});
 }
});
// Original record bookmarks carry a register mnemonic. Resolve it through the
// authorized native catalogue instead of treating a label as a database ID.
new MutationObserver(()=>{
 const params=new URLSearchParams(location.search),mnemonic=params.get('register_mnemonic');
 if(!mnemonic||params.has('register_id')||!contract?.paths['/register-metadata/get_all_registers'])return;
 const input=document.querySelector('#fields [name="register_id"],#fields [name="subject_register_id"]');if(!input||input.dataset.bookmarkResolved)return;input.dataset.bookmarkResolved='true';
 const normalize=value=>String(value||'').toLowerCase().replaceAll('_','').replaceAll('-','');
 choices(lookupDefinitions.register_id).then(rows=>{if(!input.isConnected)return;const matches=rows.filter(row=>normalize(row.register_mnemonic)===normalize(mnemonic));if(matches.length!==1)throw Error('This bookmark does not identify a unique accessible register.');input.value=matches[0].register_id;}).catch(error=>{if(input.isConnected)document.querySelector('#form-error').textContent=error.message;});
}).observe(document.querySelector('#fields'),{childList:true});
