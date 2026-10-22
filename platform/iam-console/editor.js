'use strict';
// Guided controls write the same contract fields used by the native API.
function iamControl(tag,text,attrs={}){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;for(const[k,v]of Object.entries(attrs))node.setAttribute(k,v);return node;}
async function iamCatalogue(kind,query={}){const response=await fetch('/console/catalogue/'+kind+'?'+new URLSearchParams(query),{credentials:'same-origin',cache:'no-store'});if(!response.ok)throw Error(response.status===403?'Catalogue access is not assigned.':'Named choices are temporarily unavailable.');return response.json();}
function iamImageField(input){
 const file=iamControl('input',undefined,{type:'file',accept:'image/svg+xml,image/png,image/jpeg,image/gif,image/bmp','aria-label':'Choose application or provider image'}),status=iamControl('small','Choose an image, or enter an existing image value.');
 file.addEventListener('change',async()=>{const selected=file.files[0];if(!selected)return;try{if(selected.size>2*1024*1024)throw Error('Choose an image smaller than 2 MB.');if(!['image/svg+xml','image/png','image/jpeg','image/gif','image/bmp'].includes(selected.type))throw Error('Choose SVG, PNG, JPEG, GIF or BMP.');const value=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('The image could not be read.'));reader.readAsDataURL(selected);});if(!input.isConnected)return;input.value=value;status.textContent=selected.name+' selected.';}catch(error){status.textContent=error.message;file.value='';}});
 input.after(file,status);
}
function iamPolicyBuilder(input){
 const panel=iamControl('fieldset',undefined,{id:'policy-builder'});panel.append(iamControl('legend','Filter rules'));
 const hint=iamControl('p','Build conditions and nested AND, OR or NOT groups. The JSON field remains available for advanced editing.'),tree=iamControl('div'),preview=iamControl('pre',''),error=iamControl('p','',{role:'status'});panel.append(hint,tree,preview,error);input.parentElement.after(panel);
 let root;try{root=JSON.parse(input.value);}catch{}if(!root?.type)root={type:'GROUP',operator:'AND',children:[{type:'CONDITION',field_id:'',operator:'eq',value:''}]};
 const parse=text=>{try{return JSON.parse(text);}catch{return text;}};
 function update(){input.value=JSON.stringify(root,null,2);preview.textContent=input.value;error.textContent='';}
 function button(label,action,parent){const b=iamControl('button',label,{type:'button'});b.onclick=action;parent.append(b);return b;}
 function select(values,current,change,label){const s=iamControl('select',undefined,{'aria-label':label});for(const value of values)s.append(iamControl('option',value,{value}));s.value=current;s.onchange=()=>change(s.value);return s;}
 function render(node,parent,remove,depth=0){
  const box=iamControl('fieldset',undefined,{'data-rule-type':node.type});parent.append(box);
  if(node.type==='GROUP'){
   box.append(select(['AND','OR','NOT'],node.operator,value=>{node.operator=value;update();},'Group operator'));
   for(const child of node.children)render(child,box,()=>{node.children.splice(node.children.indexOf(child),1);draw();});
   button('Add condition',()=>{node.children.push({type:'CONDITION',field_id:'',operator:'eq',value:''});draw();},box);
   if(depth<16)button('Add group',()=>{node.children.push({type:'GROUP',operator:'AND',children:[]});draw();},box);
  }else{
   const field=iamControl('input',undefined,{'aria-label':'Field identifier',placeholder:'Field identifier',list:'policy-field-choices'});field.value=node.field_id;field.oninput=()=>{node.field_id=field.value;update();};box.append(field);
   box.append(select(['eq','neq','in','nin','contains','ncontains','startsWith','endsWith','gt','gte','lt','lte','isNull'],node.operator,value=>{node.operator=value;if(['in','nin'].includes(value)){node.values=Array.isArray(node.values)?node.values:[];delete node.value;}else{delete node.values;node.value=value==='isNull'?true:'';}draw();},'Condition operator'));
   const value=iamControl('input',undefined,{'aria-label':'Condition value',placeholder:['in','nin'].includes(node.operator)?'JSON array, for example ["A","B"]':'Value (JSON for numbers, booleans or lists)'});const v=['in','nin'].includes(node.operator)?node.values:node.value;value.value=typeof v==='string'?v:JSON.stringify(v);value.oninput=()=>{const parsed=parse(value.value);if(['in','nin'].includes(node.operator)){if(!Array.isArray(parsed)){error.textContent='Use a JSON array for membership conditions.';return;}node.values=parsed;}else node.value=parsed;update();};box.append(value);
  }
  if(remove)button('Remove rule',remove,box);
 }
 function draw(){tree.replaceChildren();render(root,tree);update();}
 const importButton=button('Load JSON into builder',()=>{try{const value=JSON.parse(input.value);if(!['GROUP','CONDITION'].includes(value?.type))throw Error();root=value;tree.replaceChildren();render(root,tree);preview.textContent=input.value;error.textContent='';}catch{error.textContent='Enter a valid filter tree before loading.';}},panel);
 importButton.setAttribute('aria-label','Load JSON into filter builder');draw();
 const list=iamControl('datalist',undefined,{id:'policy-field-choices'});panel.append(list);
 const catalogueStatus=iamControl('p','',{role:'status'}),catalogues=iamControl('div');panel.append(catalogues,catalogueStatus);
 let lookupGeneration=0;
 async function namedChoices(){
  const generation=++lookupGeneration;
  const target=document.querySelector('#fields [name="policy_target"]')?.value||'REGISTER_RECORD';list.replaceChildren();catalogues.replaceChildren();
  try{
   const kind=target==='GEO'?'geo-levels':target==='ATTRIBUTE'?'attributes':'registers';const data=await iamCatalogue(kind);if(!panel.isConnected||generation!==lookupGeneration)return;
   const rows=Array.isArray(data)?data:data.attributes||[];
   const selector=iamControl('select',undefined,{'aria-label':target==='REGISTER_RECORD'?'Policy register':'Policy dimension'});selector.append(iamControl('option','Choose…',{value:''}));
   for(const row of rows){const id=row.register_id||row.level_id||row.attribute_id,label=row.register_label||row.register_mnemonic||row.level_mnemonic||row.attribute_display||row.attribute_code||id;selector.append(iamControl('option',label,{value:id}));if(target!=='REGISTER_RECORD')list.append(iamControl('option',label,{value:row.level_mnemonic||row.attribute_code||id}));}
   selector.onchange=async()=>{try{if(target==='REGISTER_RECORD'){const register=document.querySelector('#fields [name="register_id"]');if(register)register.value=selector.value;const fields=await iamCatalogue('register-fields',{register_id:selector.value});if(!panel.isConnected)return;list.replaceChildren();for(const field of (Array.isArray(fields)?fields:fields.fields||[]))list.append(iamControl('option',field.field_name||field.column_name||field.name||field.field_id,{value:field.field_id||field.field_name||field.column_name||field.name}));}else{const values=await iamCatalogue(target==='GEO'?'geo-values':'attribute-values',target==='GEO'?{level_id:selector.value}:{attribute_id:selector.value});if(!panel.isConnected)return;let pre=catalogues.querySelector('pre');if(!pre){pre=iamControl('pre');catalogues.append(pre);}pre.textContent=JSON.stringify(values,null,2);}catalogueStatus.textContent='';}catch(error){catalogueStatus.textContent=error.message;}};catalogues.append(selector);catalogueStatus.textContent='';
  }catch(error){if(panel.isConnected)catalogueStatus.textContent=error.message+' You can enter supplied field identifiers.';}
 }
 const target=document.querySelector('#fields [name="policy_target"]');target?.addEventListener('change',namedChoices);namedChoices();
}
function initializeIamFields(){
 const icon=document.querySelector('#fields [name="icon_base64"]');if(icon&&!icon.dataset.iamInitialized){icon.dataset.iamInitialized='true';iamImageField(icon);}
 const expression=document.querySelector('#fields textarea[name="policy_filter_expression"]');if(expression&&!expression.dataset.iamInitialized){expression.dataset.iamInitialized='true';iamPolicyBuilder(expression);}
}
new MutationObserver(initializeIamFields).observe(document.querySelector('#fields'),{childList:true});initializeIamFields();
document.addEventListener('submit',event=>{
 if(event.target.id!=='operation-form')return;
 const input=document.querySelector('#fields textarea[name="policy_filter_expression"]');if(!input)return;
 let count=0;
 function validate(node,depth=0){
  if(++count>512||depth>32||!node||typeof node!=='object')throw Error('Use a filter tree with at most 512 rules and 32 nested levels.');
  if(node.type==='GROUP'){if(!['AND','OR','NOT'].includes(node.operator)||!Array.isArray(node.children)||!node.children.length)throw Error('Every filter group needs an operator and at least one rule.');node.children.forEach(child=>validate(child,depth+1));}
  else if(node.type==='CONDITION'){if(typeof node.field_id!=='string'||!node.field_id.trim())throw Error('Every condition needs a field identifier.');if(['in','nin'].includes(node.operator)&&!Array.isArray(node.values))throw Error('Membership conditions need a JSON array.');}
  else throw Error('Use condition or group filter nodes.');
 }
 try{validate(JSON.parse(input.value));}catch(error){event.preventDefault();event.stopImmediatePropagation();document.querySelector('#form-error').textContent=error instanceof SyntaxError?'Enter valid filter JSON.':error.message;}
},true);
