const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
const path = require('node:path');
function node(tag='',text='') { return {tag,text,children:[],classList:{add(){}},append(...items){this.children.push(...items)},addEventListener(){},setAttribute(){},replaceChildren(...items){this.children=items},showModal(){this.open=true},focus(){}}; }
test('equipment profile restricts sections and edit actions to granted permissions', async()=>{
 const nodes=new Map(); const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id)};
 const context=vm.createContext({$:get,el:node,action:task=>task(),URL,openDialogTitle:()=>get('detail-body').replaceChildren(),api:async url=>url.endsWith('/access')?{permissions:['assets.read','assets.meter.read']}:{asset:{id:'a',name:'Rig',asset_number:'A1',is_active:true},reasons:[],status:'AVAILABLE',operational_eligibility:'ELIGIBLE'}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'equipment.js'),'utf8'),context);
 await vm.runInContext("Fleet.open('a')",context);
 const tabs=get('detail-body').children[1].children.map(n=>n.text);
 assert.deepEqual(tabs,['Overview','Assignments','Meter readings','Status history']);
 assert.equal(get('detail-body').children[2].children[0].children.length,0);
});
test('equipment edit form lookups use API paths and preserve the selected record',async()=>{
 const nodes=new Map();const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id)};
 const calls=[];
 const context=vm.createContext({$:get,el:node,document:{createElement:node},employeeId:null,contracts:async()=>({CategoryUpdate:{properties:{parent_category_id:{type:'string'}}}}),resolve:x=>x,relation:()=>null,label:x=>x,button:node,Option:function(text,value){return {text,value}},lookup:async(...args)=>calls.push(args),nameCache:{}});
 const source=fs.readFileSync(path.join(__dirname,'app.js'),'utf8');
 vm.runInContext(source.slice(source.indexOf('  async function form('),source.indexOf('  function employeeWizard(')),context);
 await vm.runInContext("form('Category','CategoryUpdate','/api/v1/asset-categories/a',{record:{parent_category_id:'b'},lookupTargets:{parent_category_id:'asset-categories'}})",context);
 assert.equal(calls[0][1],'/api/v1/asset-categories');
 assert.equal(calls[0][2],'b');
});
