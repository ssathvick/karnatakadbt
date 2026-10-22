'use strict';
// Own section designer and structured payload editor. Unknown schema properties
// survive edits; stored configuration never executes code in the preview.
function registryNode(tag,text,attrs={}){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);return n;}
function registryButton(text,handler,parent){const b=registryNode('button',text,{type:'button'});b.onclick=handler;parent.append(b);return b;}
function registryInput(label,value,onchange,type='text'){const l=registryNode('label',label),i=registryNode('input',undefined,{'aria-label':label,type});if(type==='checkbox')i.checked=!!value;else if(type!=='file')i.value=value??'';i.oninput=()=>onchange(type==='checkbox'?i.checked:type==='number'?Number(i.value):i.value);l.append(i);return l;}
function registrySectionDesigner(input){
 const panel=registryNode('fieldset',undefined,{'data-designer':input.name});panel.append(registryNode('legend','Section layout designer'));const body=registryNode('div'),preview=registryNode('div'),status=registryNode('p','',{role:'status'});panel.append(body,preview,status);input.parentElement.after(panel);
 const dragKey=crypto.randomUUID();let schema;try{schema=JSON.parse(input.value);}catch{}if(!schema||typeof schema!=='object'||Array.isArray(schema))schema={};
 function save(){input.value=JSON.stringify(schema,null,2);status.textContent='Layout updated. Review the form before saving.';}
 function panels(){if(!Array.isArray(schema.panels))schema.panels=[];return schema.panels;}
 function widgetPreview(widget,parent){const title=widget['widget-label']||widget['widget-data-path']||widget.widget||'Field';const kind=widget.widget||'text';
  if(['table','dialog-table'].includes(kind)){const table=registryNode('table'),tr=registryNode('tr');for(const column of widget['widget-data-columns']||[])tr.append(registryNode('th',column['column-label']||column['column-key']||'Column'));table.append(tr);parent.append(registryNode('p',title),table);return;}
  if(['panel','grid','horizontal'].includes(kind)){for(const child of widget.widgets||[])widgetPreview(child,parent);return;}
  const field=registryInput(title,widget['widget-data-default'],()=>{},['number','numeric','numeric-decimal'].includes(kind)?'number':kind==='date'?'date':kind==='docs'?'file':'text');const control=field.querySelector('input');control.setAttribute('aria-required',String(!!widget['widget-required']));control.readOnly=!!widget['widget-readonly'];parent.append(field);
 }
 function renderPreview(){preview.replaceChildren(registryNode('h3','Layout preview'));for(const p of panels()){const group=registryNode('fieldset');group.append(registryNode('legend',p['panel-id']||'Panel'));for(const w of p.widgets||[])widgetPreview(w,group);preview.append(group);}}
 function draw(){body.replaceChildren();const arrangement=registryNode('fieldset');arrangement.append(registryNode('legend','Arrange widgets (drag between panels)'));
 panels().forEach((p,panelIndex)=>(p.widgets||[]).forEach((widget,widgetIndex)=>{
  const row=registryNode('div'),handle=registryButton('Panel '+(panelIndex+1)+': '+(widget['widget-label']||widget.widget||'Field'),()=>{},row);handle.draggable=true;handle.dataset.dragPanel=panelIndex;handle.dataset.dragWidget=widgetIndex;
  handle.addEventListener('dragstart',event=>{event.stopPropagation();event.dataTransfer.setData('text/plain',JSON.stringify({designer:dragKey,panel:panelIndex,widget:widgetIndex}));});handle.addEventListener('dragover',event=>event.preventDefault());handle.addEventListener('drop',event=>{event.preventDefault();event.stopPropagation();try{const from=JSON.parse(event.dataTransfer.getData('text/plain')),source=schema.panels[from.panel]?.widgets;if(from.designer===dragKey&&Number.isInteger(from.widget)&&Array.isArray(source)&&from.widget>=0&&from.widget<source.length){const[item]=source.splice(from.widget,1);p.widgets.splice(widgetIndex,0,item);draw();}}catch{status.textContent='Drop a widget from this layout.';}});arrangement.append(row);
 }));body.append(arrangement);panels().forEach((p,index)=>{
  const box=registryNode('fieldset',undefined,{'data-panel-index':index});box.append(registryNode('legend','Panel '+(index+1)));box.append(registryInput('Panel identifier',p['panel-id'],v=>{p['panel-id']=v;save();renderPreview();}));
  registryButton('Move panel up',()=>{if(index){[schema.panels[index-1],schema.panels[index]]=[p,schema.panels[index-1]];draw();}},box);registryButton('Move panel down',()=>{if(index+1<schema.panels.length){[schema.panels[index+1],schema.panels[index]]=[p,schema.panels[index+1]];draw();}},box);registryButton('Remove panel',()=>{schema.panels.splice(index,1);draw();},box);
  const widgets=registryNode('div');box.append(widgets);if(!Array.isArray(p.widgets))p.widgets=[];
  p.widgets.forEach((w,position)=>{const card=registryNode('fieldset',undefined,{draggable:'true','data-widget-index':position});card.append(registryNode('legend','Widget '+(position+1)));
   const handle=registryButton('Drag widget',()=>{},card);handle.draggable=true;handle.addEventListener('dragstart',event=>{event.stopPropagation();event.dataTransfer.setData('text/plain',JSON.stringify({designer:dragKey,panel:index,widget:position}));});card.addEventListener('dragover',event=>event.preventDefault());card.addEventListener('drop',event=>{event.preventDefault();event.stopPropagation();try{const from=JSON.parse(event.dataTransfer.getData('text/plain')),source=schema.panels[from.panel]?.widgets;if(from.designer===dragKey&&Number.isInteger(from.panel)&&Number.isInteger(from.widget)&&Array.isArray(source)&&from.widget>=0&&from.widget<source.length){const [item]=source.splice(from.widget,1);p.widgets.splice(position,0,item);draw();}}catch{status.textContent='Drop a widget from this layout.';}});
   for(const[key,label]of [['widget','Widget type'],['widget-label','Field label'],['widget-data-path','Record field'],['widget-id','Widget identifier']])card.append(registryInput(label,w[key],v=>{w[key]=v;save();renderPreview();}));
   for(const[key,label]of [['widget-required','Required field'],['widget-readonly','Read-only field']])card.append(registryInput(label,w[key],v=>{w[key]=v;save();renderPreview();},'checkbox'));
   registryButton('Move widget up',()=>{if(position){[p.widgets[position-1],p.widgets[position]]=[w,p.widgets[position-1]];draw();}},card);registryButton('Move widget down',()=>{if(position+1<p.widgets.length){[p.widgets[position+1],p.widgets[position]]=[w,p.widgets[position+1]];draw();}},card);registryButton('Remove widget',()=>{p.widgets.splice(position,1);draw();},card);widgets.append(card);
  });
  registryButton('Add widget',()=>{p.widgets.push({widget:'text','widget-id':crypto.randomUUID(),'widget-label':'New field','widget-data-path':''});draw();},box);body.append(box);
 });save();renderPreview();}
 registryButton('Add panel',()=>{panels().push({'panel-id':crypto.randomUUID(),'panel-orientation':'vertical',widgets:[]});draw();},panel);
 registryButton('Load layout JSON',()=>{try{const candidate=JSON.parse(input.value);if(!candidate||Array.isArray(candidate)||typeof candidate!=='object')throw Error();schema=candidate;draw();}catch{status.textContent='Use a JSON object for the section layout.';}},panel);
 // Merely opening a form must never populate an optional null schema.
 if(input.value)draw();else status.textContent='Add a panel to begin, or load existing layout JSON.';
}
function registryPayloadEditor(input){
 const details=registryNode('details',undefined,{'data-json-editor':input.name});details.append(registryNode('summary','Edit '+friendly(input.name)+' as fields'));const tree=registryNode('div'),status=registryNode('p','',{role:'status'});details.append(tree,status);input.parentElement.after(details);let value;
 function save(){input.value=JSON.stringify(value,null,2);}
 function typeOf(v){return v===null?'null':Array.isArray(v)?'array':typeof v;}
 function blank(type){return({object:{},array:[],string:'',number:0,boolean:false,null:null})[type];}
 function render(v,parent,set,remove,depth=0){if(depth>24){parent.append(registryNode('p','Use the JSON field for deeper values.'));return;}const type=typeOf(v),box=registryNode('fieldset');parent.append(box);
  const selector=registryNode('select',undefined,{'aria-label':'Value type'});for(const kind of ['object','array','string','number','boolean','null'])selector.append(registryNode('option',kind,{value:kind}));selector.value=type;selector.onchange=()=>{set(blank(selector.value));draw();};box.append(selector);
  if(type==='object'){
   for(const[key,child]of Object.entries(v)){const item=registryNode('div');item.append(registryNode('strong',key));box.append(item);render(child,item,next=>{v[key]=next;save();},()=>{delete v[key];draw();},depth+1);}
   const name=registryNode('input',undefined,{'aria-label':'New field name',placeholder:'New field name'});box.append(name);registryButton('Add field',()=>{const key=name.value.trim();if(!key||['__proto__','prototype','constructor'].includes(key)||Object.hasOwn(v,key)){status.textContent='Choose a new field name.';return;}v[key]='';draw();},box);
  }else if(type==='array'){
   v.forEach((child,index)=>{const row=registryNode('div');row.append(registryNode('strong','Row '+(index+1)));box.append(row);render(child,row,next=>{v[index]=next;save();},()=>{v.splice(index,1);draw();},depth+1);registryButton('Move row up',()=>{if(index){[v[index-1],v[index]]=[v[index],v[index-1]];draw();}},row);registryButton('Move row down',()=>{if(index+1<v.length){[v[index+1],v[index]]=[v[index],v[index+1]];draw();}},row);});registryButton('Add row',()=>{v.push({});draw();},box);
  }else if(type!=='null')box.append(registryInput('Field value',v,next=>{set(next);save();},type==='boolean'?'checkbox':type==='number'?'number':'text'));
  if(remove)registryButton('Remove value',remove,box);
 }
 function draw(){tree.replaceChildren();render(value,tree,next=>{value=next;save();});save();status.textContent='';}
 registryButton('Load JSON fields',()=>{try{value=JSON.parse(input.value|| (input.dataset.kind==='array'?'[]':'{}'));draw();}catch{status.textContent='Enter valid JSON before loading.';}},details);
 registryButton('Start empty fields',()=>{value=input.dataset.kind==='array'?[]:{};draw();},details);
}
function initializeRegistryEditors(){
 for(const input of document.querySelectorAll('#fields textarea[data-json="true"]')){if(input.dataset.registryEditor)continue;input.dataset.registryEditor='true';if(/ui_schema/.test(input.name))registrySectionDesigner(input);else registryPayloadEditor(input);}
 for(const input of document.querySelectorAll('#fields input[name]')){
  if(!['registry_logo','registry_favicon','language_flag_base64','register_icon'].includes(input.name)||input.dataset.registryImage)continue;input.dataset.registryImage='true';
  const file=registryNode('input',undefined,{type:'file',accept:'image/png,image/jpeg,image/webp','aria-label':'Choose '+friendly(input.name)}),status=registryNode('small','PNG, JPEG or WebP; up to 1 MB. Server checks dimensions and contents.');input.after(file,status);
  file.onchange=async()=>{const selected=file.files[0];if(!selected)return;try{if(selected.size>1024*1024||!['image/png','image/jpeg','image/webp'].includes(selected.type))throw Error('Choose a PNG, JPEG or WebP image up to 1 MB.');const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('Image could not be read.'));reader.readAsDataURL(selected);});if(!input.isConnected)return;input.value=data;status.textContent=selected.name+' selected.';}catch(error){status.textContent=error.message;file.value='';}};
 }
}
new MutationObserver(initializeRegistryEditors).observe(document.querySelector('#fields'),{childList:true});
