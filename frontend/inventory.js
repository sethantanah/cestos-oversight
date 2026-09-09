"use strict";
const Inventory = (() => {
  const root='/api/v1/inventory';
  let access={permissions:[]}, section='items', currentItem=null, search='', currentPage=1;
  const names={'items':'Items','stock':'Stock by store','transactions':'Ledger','receipts':'Receipts','issues':'Issues','returns':'Returns','transfers':'Transfers','requests':'Requests','reservations':'Reservations','stock-counts':'Stock counts','adjustments':'Adjustments','forecast':'Forecast & reorder','categories':'Categories','units':'Units','conversions':'Unit conversions','stores':'Stores','bins':'Bins','suppliers':'Suppliers','stock-policies':'Stock policies','item-suppliers':'Item suppliers','compatibility':'Asset compatibility','lots':'Lots','serials':'Serials','custody':'Tools in custody','reconciliation':'Reconciliation'};
  const masters={items:'InventoryItem',categories:'InventoryCategory',units:'UnitOfMeasure',conversions:'UnitConversion',stores:'InventoryStore',bins:'InventoryBin',suppliers:'Supplier','stock-policies':'InventoryStockPolicy','item-suppliers':'InventoryItemSupplier',compatibility:'InventoryCompatibility'};
  const documentKinds=['receipts','issues','returns','transfers','requests','stock-counts','adjustments'];
  const transitions={receipts:{DRAFT:['post','cancel']},issues:{DRAFT:['approve','post','cancel'],APPROVED:['post','cancel']},returns:{DRAFT:['post']},transfers:{DRAFT:['approve','cancel'],APPROVED:['dispatch','cancel'],IN_TRANSIT:['receive']},requests:{DRAFT:['submit','cancel'],SUBMITTED:['approve','reject','cancel'],APPROVED:['create-issue','cancel'],PARTIALLY_ISSUED:['create-issue']},'stock-counts':{DRAFT:['start'],IN_PROGRESS:['submit','restart'],SUBMITTED:['approve','restart'],APPROVED:['post','restart']},adjustments:{DRAFT:['approve','cancel'],APPROVED:['post','cancel']}};
  const pretty=k=>({'quantity_on_hand':'On hand','quantity_available':'Available','quantity_reserved':'Reserved','quantity_quarantined':'Quarantined','quantity_in_transit':'In transit'}[k]||k.replaceAll('_',' ').replaceAll('-',' '));
  function display(value){if(value==null)return '�';if(typeof value==='boolean')return value?'Yes':'No';const text=String(value);if(/^-?\d+(\.\d+)?$/.test(text)){const [whole,fraction='']=text.split('.');const decimals=fraction.slice(0,4).replace(/0+$/,'');return whole.replace(/\B(?=(\d{3})+(?!\d))/g,',')+(decimals?'.'+decimals:'');}if(/^0E-/.test(text))return '0';return text;}
  const can=code=>access.superadmin||access.permissions.includes('inventory.admin')||access.permissions.includes(code);
  const grant=kind=>'inventory.'+kind.replaceAll('-','_');
  const btn=(title,task,primary=false)=>{const b=el('button',title,primary?'primary':'secondary');b.type='button';b.onclick=()=>action(task);return b;};
  function facts(row,parent){const dl=el('dl',undefined,'detail-list');for(const [key,value] of Object.entries(row)){if(value==null||typeof value==='object'||key.endsWith('_id')||['id','organization_id'].includes(key))continue;dl.append(el('dt',pretty(key)),el('dd',display(value)));}parent.append(dl);}
  function permissions(kind){if(documentKinds.includes(kind))return grant(kind)+'.read';if(kind==='reservations')return 'inventory.reservations.read';if(kind==='forecast')return 'inventory.forecast.read';if(kind==='reconciliation')return 'inventory.reconciliation.read';return 'inventory.read';}
  async function open(kind=section,page=1){
    section=kind;currentPage=page;access=await api(root+'/access');
    const area=$('inventory-content');area.replaceChildren();
    const tabs=el('nav',undefined,'equipment-tabs');tabs.setAttribute('aria-label','Inventory sections');
    for(const [key,title] of Object.entries(names))if(can(permissions(key))){const b=btn(title,()=>{search='';return open(key)});b.setAttribute('aria-pressed',String(key===kind));tabs.append(b);}area.append(tabs);
    if(kind==='items'){
      const summary=await api(root+'/dashboard-summary');const cards=el('div',undefined,'equipment-summary');
      for(const key of ['total_inventory_items','items_in_stock','low_stock_items','out_of_stock_items','items_requiring_reorder','total_inventory_value'])if(summary[key]!=null){const card=el('article');card.append(el('strong',display(summary[key])),el('span',pretty(key)));cards.append(card);}area.append(cards);
    }
    const toolbar=el('div',undefined,'row-actions');area.append(toolbar);
    const query=el('input');query.type='search';query.placeholder='Search '+names[kind].toLowerCase();query.value=search;query.setAttribute('aria-label','Search inventory');
    toolbar.append(query,btn('Search',()=>{search=query.value;return open(kind)}));
    if(['items','stock','transactions','receipts','issues','returns','transfers','requests','stock-counts','adjustments'].includes(kind))toolbar.append(btn('Export CSV',async()=>{const result=await apiBlob(root+'/exports/'+kind);downloadBlob(result.blob,result.filename)}));
    if(kind==='items'&&can('inventory.admin'))toolbar.append(btn('Import CSV',importForm));
    if(masters[kind]&&can(kind==='items'?'inventory.items.create':'inventory.catalog.manage'))toolbar.append(btn('Add '+names[kind].toLowerCase(),()=>masterForm(kind),true));
    if(documentKinds.includes(kind)&&can(grant(kind)+'.create'))toolbar.append(btn('New '+names[kind].toLowerCase(),()=>documentForm(kind),true));
    if(kind==='reservations'&&can('inventory.reservations.manage'))toolbar.append(btn('Reserve stock',()=>masterForm('reservations'),true));
    if(kind==='items'){
      const code=el('input');code.placeholder='Scan barcode or enter item number';code.setAttribute('aria-label','Inventory tag');toolbar.append(code,btn('Find tag',async()=>{const data=await api(root+'/lookup?code='+encodeURIComponent(code.value));await item(data.item.id)}));
      toolbar.append(btn('Low stock',()=>loadFiltered('low_stock=true')),btn('Out of stock',()=>loadFiltered('out_of_stock=true')));
    }
    const response=await api(`${root}/${kind}?page=${page}&page_size=25${search?'&search='+encodeURIComponent(search):''}`);
    if(kind==='reconciliation')area.append(el('p',response.consistent?'Ledger and balances agree.':'Differences found. Review before making an approved correction.','hint'));
    renderTable(response.items||[],area,kind);
    const paging=el('div',undefined,'row-actions');const back=btn('Previous',()=>open(kind,page-1)),next=btn('Next',()=>open(kind,page+1));back.disabled=page<=1;next.disabled=page>=response.pages;paging.append(back,el('span',`Page ${page} of ${response.pages||1} · ${response.total||0} records`),next);area.append(paging);
  }
  async function loadFiltered(filter){const area=$('inventory-content');const response=await api(root+'/items?'+filter);const results=el('section');results.append(el('h2',filter.startsWith('low')?'Low stock':'Out of stock'));renderTable(response.items,results,'items');area.append(results);}
  function renderTable(rows,parent,kind){
    if(!rows.length){parent.append(el('p','No records yet.','hint'));return;}
    const keys=kind==='items'||kind==='forecast'?['item_number','name','unit','quantity_on_hand','quantity_available','quantity_reserved','quantity_quarantined','quantity_in_transit','reorder_status',...(kind==='forecast'?['average_daily_consumption','days_remaining','recommended_order_quantity']:[])]:kind==='stock'?['item_name','store_name','quantity_on_hand','quantity_available','quantity_reserved','quantity_quarantined','quantity_in_transit']:kind==='transactions'?['transaction_number','transaction_type','normalized_quantity','transaction_date','reference_number','unit_cost','total_cost']:documentKinds.includes(kind)?['document_number','status','purpose','transaction_date']:Object.keys(rows[0]).filter(k=>!k.endsWith('_id')&&!['id','organization_id','updated_at','created_at','notes','description'].includes(k)).slice(0,7);
    const wrapper=el('div',undefined,'inventory-table-wrap'),table=el('table'),head=el('thead'),tr=el('tr');for(const key of keys)tr.append(el('th',pretty(key)));head.append(tr);table.append(head);const body=el('tbody');table.append(body);
    for(const row of rows){const r=el('tr');for(const key of keys)r.append(el('td',row[key]==null?'—':String(row[key])));r.tabIndex=0;const show=()=>kind==='items'||kind==='forecast'?item(row.id):documentKinds.includes(kind)?documentDetail(kind,row.id):record(kind,row);r.onclick=()=>action(show);r.onkeydown=e=>{if(e.key==='Enter')action(show)};body.append(r);}wrapper.append(table);parent.append(wrapper);
  }
  const lookups={category_id:'inventory/categories',parent_category_id:'inventory/categories',base_unit_id:'inventory/units',unit_id:'inventory/units',from_unit_id:'inventory/units',to_unit_id:'inventory/units',item_id:'inventory/items',store_id:'inventory/stores',bin_id:'inventory/bins',supplier_id:'inventory/suppliers',preferred_supplier_id:'inventory/suppliers',manager_employee_id:'employees',asset_category_id:'asset-categories',lot_id:'inventory/lots',serial_id:'inventory/serials'};
  async function masterForm(kind,row=null){return Workforce.form((row?'Edit ':'Add ')+names[kind],kind==='reservations'?'InventoryReservationCreate':masters[kind]+(row?'Update':'Create'),root+'/'+kind+(row?'/'+row.id:''),{record:row,contextId:null,lookupTargets:lookups,done:()=>open(kind)});}
  async function item(id){
    currentItem=id;const data=await api(root+`/items/${id}/overview`);openDialogTitle('INVENTORY · '+data.item.item_number,data.item.name);const area=$('detail-body');$('detail-dialog').classList.add('equipment-dialog');
    const actions=el('div',undefined,'row-actions');if(can('inventory.items.update'))actions.append(btn('Edit item',()=>masterForm('items',data.item)));
    if(can('inventory.items.archive'))actions.append(btn(data.item.is_active?'Archive':'Restore',async()=>{await api(root+`/items/${id}/${data.item.is_active?'archive':'restore'}`,{method:'POST'});await item(id)}));area.append(actions);
    const metrics=el('div',undefined,'equipment-summary');for(const key of ['quantity_on_hand','quantity_available','quantity_reserved','quantity_quarantined','quantity_in_transit']){const card=el('article');card.append(el('strong',display(data[key])),el('span',pretty(key)));metrics.append(card);}area.append(metrics);
    facts({sku:data.item.sku,category:data.category?.name,base_unit:data.base_unit?.name,criticality:data.item.criticality,tracking_method:data.item.tracking_method,reorder_status:data.reorder_status,average_daily_consumption:data.average_daily_consumption,days_remaining:data.days_remaining,estimated_stockout_date:data.estimated_stockout_date,lead_time_days:data.lead_time_days,recommended_order_quantity:data.recommended_order_quantity,inventory_value:data.inventory_value,average_unit_cost:data.average_unit_cost,currency:data.item.default_currency},area);
    const tabs=el('nav',undefined,'equipment-tabs'),body=el('div');area.append(tabs,body);
    const choices={'stock':'Stock','transactions':'Transactions','receipts':'Receipts','issues':'Issues','transfers':'Transfers','lots':'Lots','item-suppliers':'Suppliers','compatibility':'Assets','stock-policies':'Policies','stock-counts':'Stock counts','adjustments':'Adjustments','activity':'Activity'};
    for(const [key,title]of Object.entries(choices))if(key==='activity'||can(permissions(key)))tabs.append(btn(title,async()=>{body.replaceChildren();const path=key==='activity'?`/items/${id}/activity`:`/${key}?item_id=${id}`;const response=await api(root+path);renderTable(response.items,body,key)}));
    renderTable(data.stock.items,body,'stock');
  }
  async function record(kind,row){openDialogTitle('INVENTORY',row.name||row.transaction_number||names[kind]);const area=$('detail-body');facts(row,area);if(masters[kind]&&can('inventory.catalog.manage'))area.append(btn('Edit',()=>masterForm(kind,row)));if(kind==='reservations'&&row.status==='ACTIVE'&&can('inventory.reservations.manage'))area.append(btn('Release reservation',async()=>{await api(root+`/reservations/${row.id}/release`,{method:'POST'});$('detail-dialog').close();await open(kind)}));if(kind==='transactions'&&can('inventory.transactions.reverse'))area.append(btn('Reverse transaction',()=>Workforce.form('Reverse transaction','InventoryReverse',root+`/transactions/${row.id}/reverse`,{contextId:null,done:()=>open('transactions')})));}
  async function documentDetail(kind,id){
    const doc=await api(root+`/${kind}/${id}`);openDialogTitle(names[kind].toUpperCase(),doc.document_number);const area=$('detail-body');facts(doc,area);
    const actions=el('div',undefined,'row-actions');area.append(actions);const countInputs={};
    if(doc.status==='DRAFT'&&can(grant(kind)+'.create'))actions.append(btn('Edit draft',()=>documentForm(kind,doc)));
    for(const op of transitions[kind][doc.status]||[]){const required=op==='create-issue'?'inventory.issues.create':grant(kind)+'.'+(['submit','start','restart','cancel'].includes(op)?'create':op==='reject'?'approve':op);if(!can(required))continue;
      actions.append(btn(pretty(op),async()=>{
        if(op==='restart')return Workforce.form('Restart stock count','InventoryReverse',root+`/stock-counts/${id}/restart`,{contextId:null,done:()=>documentDetail(kind,id)});
        if(op==='create-issue')return Workforce.form('Create issue from request','InventoryAction',root+`/requests/${id}/create-issue`,{contextId:null,fields:{store_id:{type:'string',format:'uuid'}},lookupTargets:lookups,done:doc=>documentDetail('issues',doc.id)});
        await api(root+`/${kind}/${id}/${op}`,{method:'POST',body:kind==='stock-counts'&&op==='submit'?{quantities:Object.fromEntries(Object.entries(countInputs).map(([key,field])=>[key,field.value]))}:{}});await documentDetail(kind,id);
      },['post','dispatch','receive'].includes(op)));
    }
    for(const row of doc.items){const card=el('article',undefined,'employee-record');const details=await api(root+'/items/'+row.item_id);card.append(el('h3',details.name));facts(row,card);if(kind==='stock-counts'&&doc.status==='IN_PROGRESS')countInputs[row.id]=input(card,'Counted quantity','number',row.counted_quantity??'',true);area.append(card);}
  }
  async function choose(parent,title,path,value=null,required=false){
    const wrapper=el('div'),caption=el('label',title),select=el('select');select.setAttribute('aria-label',title);select.required=required;wrapper.append(caption,select);parent.append(wrapper);
    const find=el('input');find.type='search';find.placeholder='Search '+title.toLowerCase();find.setAttribute('aria-label','Find '+title.toLowerCase());
    async function load(){const endpoint=typeof path==='function'?path():path;const data=await api(endpoint+(endpoint.includes('?')?'&':'?')+'page_size=100&search='+encodeURIComponent(find.value));const rows=Array.isArray(data)?data:data.items;const previous=select.value||value;select.replaceChildren(new Option('Choose…',''));for(const row of rows)select.append(new Option(row.name||row.lot_number||row.serial_number||row.document_number||[row.first_name,row.last_name].filter(Boolean).join(' ')||row.id,row.id));if(previous&&!rows.some(r=>r.id===previous))select.append(new Option('Current selection',previous));select.value=previous||'';}
    wrapper.append(find,btn('Find',load));await load();return select;
  }
  function input(parent,title,type='text',value='',required=false){const wrap=el('div'),caption=el('label',title),field=el('input');field.type=type;field.value=value??'';field.required=required;field.setAttribute('aria-label',title);if(type==='number'){field.min='0';field.step='0.0001'}wrap.append(caption,field);parent.append(wrap);return field;}
  async function documentForm(kind,doc=null){
    const dialog=$('workforce-form-dialog');$('workforce-form-title').textContent=(doc?'Edit ':'New ')+names[kind].toLowerCase();const content=$('workforce-form-content');content.replaceChildren();if(!dialog.open)dialog.showModal();
    const form=el('form',undefined,'inventory-document-form'),grid=el('div',undefined,'form-grid');form.append(grid);content.append(form);const fields={};
    const specs=kind==='transfers'?{from_store_id:['From store',root+'/stores'],to_store_id:['To store',root+'/stores']}:{store_id:['Store',root+'/stores']};
    if(kind==='receipts')specs.supplier_id=['Supplier',root+'/suppliers'];
    if(kind==='returns')specs.original_issue_id=['Original issue',root+'/issues?status=POSTED'];
    if(['issues','requests','returns','transfers'].includes(kind)){specs.project_id=['Project','/api/v1/projects'];specs.asset_id=['Asset','/api/v1/assets'];specs.employee_id=['Employee','/api/v1/employees'];}
    for(const [key,[title,path]]of Object.entries(specs))fields[key]=await choose(grid,title,path,doc?.[key],key.includes('store')&&kind!=='requests'||key==='original_issue_id');
    const purpose=el('select');purpose.setAttribute('aria-label','Purpose');const choices=kind==='adjustments'?['POSITIVE_ADJUSTMENT','NEGATIVE_ADJUSTMENT','QUARANTINE','RELEASE_FROM_QUARANTINE','WRITE_OFF','DAMAGE','LOSS']:kind==='receipts'?['PURCHASE_RECEIPT','OTHER_RECEIPT','OPENING_BALANCE']:['OTHER','PROJECT_CONSUMPTION','ASSET_CONSUMPTION','MAINTENANCE','EMPLOYEE_USE','PPE','TOOLS','OFFICE_USE','CAMP_USE'];for(const v of choices)purpose.append(new Option(pretty(v),v));purpose.value=doc?.purpose||choices[0];grid.append(el('label','Purpose'),purpose);fields.purpose=purpose;
    if(kind==='returns'){const condition=el('select');condition.setAttribute('aria-label','Return condition');for(const value of ['GOOD','USED_SERVICEABLE','DAMAGED','DEFECTIVE','QUARANTINE','SCRAP'])condition.append(new Option(pretty(value),value));condition.value=doc?.condition||'GOOD';grid.append(el('label','Return condition'),condition);fields.condition=condition;}
    fields.reason=input(grid,'Reason','text',doc?.reason,kind==='adjustments');fields.notes=input(grid,'Notes','text',doc?.notes);
    const lines=el('div');form.append(el('h3','Items'),lines);const controls=[];
    async function addLine(existing={}){
      const card=el('fieldset',undefined,'inventory-line');card.append(el('legend','Stock item'));lines.append(card);const row={};
      row.item_id=await choose(card,'Item',root+'/items',existing.item_id,true);row.unit_id=await choose(card,'Unit',root+'/units',existing.unit_id,true);
      row.item_id.onchange=async()=>{if(!row.item_id.value)return;const data=await api(root+'/items/'+row.item_id.value);row.unit_id.value=data.base_unit_id;};
      row.quantity=input(card,'Quantity','number',existing.quantity||'1',true);
      if(['receipts','adjustments'].includes(kind))row.unit_cost=input(card,'Unit cost per selected unit','number',existing.unit_cost||'0',kind==='receipts');
      if(kind==='stock-counts')row.counted_quantity=input(card,'Counted quantity','number',existing.counted_quantity??'',true);
      row.bin_id=await choose(card,kind==='transfers'?'Source bin':'Bin',()=>root+'/bins'+((fields.store_id||fields.from_store_id)?.value?'?store_id='+(fields.store_id||fields.from_store_id).value:''),existing.bin_id||existing.from_bin_id);
      if(kind==='transfers')row.to_bin_id=await choose(card,'Destination bin',()=>root+'/bins'+(fields.to_store_id.value?'?store_id='+fields.to_store_id.value:''),existing.to_bin_id);
      if(kind==='receipts'){row.lot_number=input(card,'Lot / batch number','text',existing.lot_number);row.expiry_date=input(card,'Expiry date','date',existing.expiry_date);row.serial_number=input(card,'Serial number','text',existing.serial_number);}
      else {row.lot_id=await choose(card,'Lot',()=>root+'/lots'+(row.item_id.value?'?item_id='+row.item_id.value:''),existing.lot_id);row.serial_id=await choose(card,'Serial',()=>root+'/serials'+(row.item_id.value?'?item_id='+row.item_id.value:''),existing.serial_id);}
      controls.push({row,card});card.append(btn('Remove line',()=>{card.remove();controls.splice(controls.findIndex(c=>c.card===card),1)}));
    }
    for(const row of doc?.items||[{}])await addLine(row);
    form.append(btn('Add another item',()=>addLine()));const error=el('p','','form-error');error.id='inventory-form-error';error.hidden=true;form.append(error);const save=el('button','Save draft','primary');save.type='submit';form.append(save);
    form.onsubmit=e=>{e.preventDefault();action(async()=>{
      if(!controls.length)throw Error('Add at least one item');const payload={};for(const[key,field]of Object.entries(fields))if(field.value)payload[key]=field.value;
      payload.items=controls.map(({row})=>{const data={};for(const[key,field]of Object.entries(row))if(field.value)data[kind==='transfers'&&key==='bin_id'?'from_bin_id':key]=field.value;return data;});
      const saved=await api(root+'/'+kind+(doc?'/'+doc.id:''),{method:doc?'PATCH':'POST',body:payload});dialog.close();await documentDetail(kind,saved.id);
    },error.id)};
  }
  async function importForm(){
    openDialogTitle('INVENTORY IMPORT','Preview a CSV file');const area=$('detail-body');
    area.append(el('p','Choose item master, opening stock, or stock policies. Preview validates every row. Stock is added only after you confirm. Files may contain up to 200 rows.','hint'));
    const kind=el('select');kind.setAttribute('aria-label','Import type');for(const value of ['items','opening-stock','stock-policies'])kind.append(new Option(pretty(value),value));
    const file=el('input');file.type='file';file.accept='.csv';file.setAttribute('aria-label','CSV file');area.append(kind,file,btn('Validate and preview',async()=>{
      if(!file.files[0])throw Error('Choose a CSV file');const data=new FormData();data.append('file',file.files[0]);const result=await sendForm(root+'/imports/'+kind.value+'/preview',data);
      const preview=el('section');preview.append(el('h3',result.row_count+' rows'));area.append(preview);
      for(const error of result.errors)preview.append(el('p',`Row ${error.row}: ${error.message}`,'form-error'));
      const table=el('pre');table.textContent=JSON.stringify(result.rows,null,2);preview.append(table);
      if(result.can_import)preview.append(btn('Confirm import',async()=>{await api(root+'/imports/'+result.id+'/confirm',{method:'POST'});$('detail-dialog').close();await open('items')},true));
    }));
  }
  return {open,item,documentForm};
})();
