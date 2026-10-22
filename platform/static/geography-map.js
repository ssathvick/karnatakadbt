(async()=>{
'use strict';
const $=id=>document.getElementById(id),host=$('state-map');if(!host)return;
const ns='http://www.w3.org/2000/svg',colors=['#fff0a3','#f9d25b','#f3a039','#e56832','#ca342b','#8f1428'];
const report=JSON.parse($('map-report').textContent),measure=$('map-measure'),mode=$('map-mode'),districtSelect=$('map-state'),householdSelect=$('geo-household'),form=$('geo-location-form');
let selectedDistrict='',selectedHousehold='',households=[],busy=false,view=[0,0,600,700];
function node(tag,text,cls){const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e}
function svgNode(tag,attrs={}){const e=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);return e}
async function get(path){const response=await fetch('/registration/api/geography/'+path,{cache:'no-store'});if(!response.ok)throw Error('Could not load map data. Sign in again if your session expired.');return response.json()}
try{
const [boundaries,catalogue,records]=await Promise.all([get('districts.geojson'),get('areas'),get('households')]);households=records.households;
const districts=catalogue.districts,polygons=new Map(),pointNodes=new Map(),svg=svgNode('svg',{viewBox:view.join(' '),role:'group','aria-label':'Karnataka map: 31 districts, density shading and household locations'});
const project=([lon,lat])=>[(lon-73.75)*114+15,(18.65-lat)*96+12];
const shapeLayer=svgNode('g'),pointLayer=svgNode('g'),labelLayer=svgNode('g');svg.append(shapeLayer,pointLayer,labelLayer);host.append(svg);
for(const f of boundaries.features){
 const id=f.properties.district_id,d=districts.find(d=>d.id===id),rings=f.geometry.type==='Polygon'?[f.geometry.coordinates]:f.geometry.coordinates;
 const pathData=rings.flatMap(p=>p.map(r=>r.map((coord,i)=>(i?'L':'M')+project(coord).join(',')).join(' ')+'Z')).join(' ');
 const path=svgNode('path',{d:pathData,class:'district',tabindex:0,role:'button','fill-rule':'evenodd','data-district':id});const title=svgNode('title');path.append(title);shapeLayer.append(path);polygons.set(id,{path,title,feature:f});
 const label=svgNode('text',{x:project([d.longitude,d.latitude])[0],y:project([d.longitude,d.latitude])[1],class:'map-label'});label.textContent=d.name;labelLayer.append(label);
 path.addEventListener('click',()=>chooseDistrict(id));path.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();chooseDistrict(id)}});
 const option=node('option',d.name);option.value=id;districtSelect.append(option);
}
function row(id){return report.counts.find(r=>r.district_id===id&&r.record_type===measure.value)}
function value(id){const r=row(id);return mode.value==='density'?r.density_per_km2:r.record_count}
function number(n){return mode.value==='density'?n.toFixed(4):n.toLocaleString()}
function renderDistrict(){
 const target=$('map-detail');target.replaceChildren();const d=districts.find(d=>d.id===selectedDistrict);
 if(!d){target.append(node('h3','All Karnataka'),node('strong',report.totals[measure.value].toLocaleString()+' records'),node('p','Select a district to see density, mapped area and household locations.'));return}
 const r=row(d.id);target.append(node('h3',d.name),node('p',d.division+' revenue division'),node('strong',number(value(d.id))+(mode.value==='density'?' / km²':' records')),node('p',r.record_count+' '+measure.value+' records · '+r.area_km2.toLocaleString()+' approximate km²'),node('small',households.filter(h=>h.district_id===d.id&&h.latitude!=null).length+' located households in this district'));
}
function updateMap(){
 const max=Math.max(...districts.map(d=>value(d.id))),cuts=[0,.08,.18,.35,.6,.8].map(v=>v*max);
 for(const d of districts){const item=polygons.get(d.id),v=value(d.id);let index=cuts.reduce((i,c,j)=>v>=c?j:i,0);item.path.setAttribute('fill',colors[index]);item.path.classList.toggle('selected',d.id===selectedDistrict);item.path.classList.toggle('dimmed',!!selectedDistrict&&d.id!==selectedDistrict);const label=d.name+': '+number(v)+(mode.value==='density'?' records per square kilometre':' records');item.title.textContent=label;item.path.setAttribute('aria-label',label)}
 const legend=$('map-legend');legend.replaceChildren(node('strong',mode.value==='density'?'Records / km²':'Records'));
 cuts.forEach((cut,i)=>{const span=node('span');const swatch=node('i');swatch.style.background=colors[i];span.append(swatch,document.createTextNode(number(cut)+(i===cuts.length-1?'+':'–'+number(cuts[i+1]))));legend.append(span)});
 const same=new Set(districts.map(d=>row(d.id).record_count)).size===1;$('geo-uniform-note').textContent=same?'The synthetic dataset contains the same record count in each district. Count mode therefore uses one colour; density mode differs because district areas vary.':'';
 renderDistrict();renderPoints();
}
function renderPoints(){
 pointLayer.replaceChildren();pointNodes.clear();const visible=$('map-demo-points').checked;
 for(const h of households){if(!visible||h.latitude==null||(selectedDistrict&&h.district_id!==selectedDistrict))continue;
 const [x,y]=project([h.longitude,h.latitude]),isDemo=h.coordinate_source==='synthetic_demo';const point=svgNode('circle',{cx:x,cy:y,r:h.reference===selectedHousehold?4:2.1,class:'household-point'+(!isDemo?' reported':'')+(h.reference===selectedHousehold?' selected':''),'data-household':h.reference,tabindex:0,role:'button','aria-label':h.name+', '+h.district_name+', '+(isDemo?'synthetic demonstration':'user-reported')+' location'});const title=svgNode('title');title.textContent=h.reference+' · '+h.name+' · '+h.latitude.toFixed(5)+', '+h.longitude.toFixed(5);point.append(title);point.addEventListener('click',()=>chooseHousehold(h.reference));point.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();chooseHousehold(h.reference)}});pointLayer.append(point);pointNodes.set(h.reference,point);
 }
 const located=households.filter(h=>h.latitude!=null).length,demo=households.filter(h=>h.coordinate_source==='synthetic_demo'&&h.latitude!=null).length;$('geo-located').textContent=located.toLocaleString();$('geo-missing').textContent=(households.length-located)+' households without coordinates';$('map-coverage').textContent='31 district boundaries · '+located.toLocaleString()+' located households · '+demo.toLocaleString()+' simulated points · '+(located-demo)+' user-reported points';
}
function listHouseholds(){const query=$('geo-search').value.trim().toLowerCase();householdSelect.replaceChildren(node('option','Choose a household'));householdSelect.firstElementChild.value='';for(const h of households.filter(h=>(!selectedDistrict||h.district_id===selectedDistrict)&&(!query||(h.name+' '+h.reference).toLowerCase().includes(query)))){const option=node('option',h.reference+' · '+h.name);option.value=h.reference;householdSelect.append(option)}householdSelect.value=selectedHousehold}
function chooseDistrict(id){selectedDistrict=id;districtSelect.value=id;if(selectedHousehold&&households.find(h=>h.reference===selectedHousehold)?.district_id!==id)chooseHousehold('');listHouseholds();updateMap()}
function chooseHousehold(reference){selectedHousehold=reference;const h=households.find(h=>h.reference===reference);$('geo-save-status').textContent='';$('geo-location-fields').disabled=!h;if(!h){$('geo-household-detail').textContent='Select a household to enter or update its coordinates.';renderPoints();return}
 if(selectedDistrict&&h.district_id!==selectedDistrict){selectedDistrict=h.district_id;districtSelect.value=selectedDistrict;updateMap()}
 $('geo-search').value='';listHouseholds();householdSelect.value=reference;$('geo-household-detail').textContent=h.name+' · '+h.district_name+' · '+h.members+' members · '+(h.coordinate_source==='synthetic_demo'?'Simulated location':h.latitude==null?'No coordinates':'User-reported, unverified');form.elements.latitude.value=h.latitude??'';form.elements.longitude.value=h.longitude??'';form.elements.accuracy_m.value=h.accuracy_m??'';renderPoints();
}
function zoom(factor){const [x,y,w,h]=view;const nw=Math.max(130,Math.min(900,w*factor)),nh=nw*700/600;view=[x+(w-nw)/2,y+(h-nh)/2,nw,nh];svg.setAttribute('viewBox',view.join(' '))}
$('map-zoom-in').addEventListener('click',()=>zoom(.8));$('map-zoom-out').addEventListener('click',()=>zoom(1.25));$('map-reset').addEventListener('click',()=>{view=[0,0,600,700];svg.setAttribute('viewBox',view.join(' '));chooseDistrict('')});
measure.addEventListener('change',updateMap);mode.addEventListener('change',updateMap);districtSelect.addEventListener('change',()=>chooseDistrict(districtSelect.value));$('map-demo-points').addEventListener('change',renderPoints);$('geo-search').addEventListener('input',listHouseholds);householdSelect.addEventListener('change',()=>chooseHousehold(householdSelect.value));
$('geo-device').addEventListener('click',()=>{const status=$('geo-save-status');if(!navigator.geolocation){status.textContent='Device location is unavailable in this browser.';return}status.textContent='Waiting for your browser location permission…';navigator.geolocation.getCurrentPosition(position=>{form.elements.latitude.value=position.coords.latitude.toFixed(7);form.elements.longitude.value=position.coords.longitude.toFixed(7);form.elements.accuracy_m.value=Math.round(position.coords.accuracy);status.textContent='Location entered. Check the district and save to store it.'},()=>{status.textContent='Location was not available or permission was declined. You can enter coordinates manually.'},{enableHighAccuracy:true,timeout:15000,maximumAge:0})});
form.addEventListener('submit',async e=>{e.preventDefault();if(busy||!selectedHousehold)return;const h=households.find(h=>h.reference===selectedHousehold);if(!h)return;busy=true;$('geo-save').disabled=true;const status=$('geo-save-status');status.textContent='Saving coordinates…';try{const data=new URLSearchParams(new FormData(form));data.set('version',h.version);const response=await fetch('/registration/api/geography/households/'+encodeURIComponent(h.reference)+'/location',{method:'POST',body:data});const result=await response.json();if(!response.ok)throw Error(result.error||'Coordinates could not be saved. Reload and try again.');const records=await get('households');households=records.households;const ref=h.reference;chooseHousehold(ref);renderDistrict();status.textContent=result.native_synced?'Coordinates saved and synced to the native registries.':'Coordinates saved. Native registry sync is queued for automatic retry.'}catch(error){status.textContent=error.message}finally{busy=false;$('geo-save').disabled=false}});
listHouseholds();updateMap();
}catch(error){host.replaceChildren(node('p',error.message||'Map data could not load. Reload or sign in again.'));console.error(error)}
})();
