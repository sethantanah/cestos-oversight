"use strict";
const Fleet = (() => {
  let access = {permissions: []};
  let selected = null;
  let tabName = 'overview';
  let photoUrls = [];
  function clearPhotos(){for(const url of photoUrls)URL.revokeObjectURL(url);photoUrls=[];}
  $('detail-dialog').addEventListener('close',clearPhotos);
  const can = code => access.superadmin || access.permissions.includes(code) || ({'assets.meter.record':'assets.record_meter','assets.documents.read':'asset_documents.read','assets.documents.manage':'asset_documents.manage'}[code] && access.permissions.includes({'assets.meter.record':'assets.record_meter','assets.documents.read':'asset_documents.read','assets.documents.manage':'asset_documents.manage'}[code]));
  const label = key => key.replaceAll('_',' ').replaceAll('-',' ');
  function button(title, task, primary=false) { const node=el('button',title,primary?'primary':'secondary');node.type='button';node.onclick=()=>action(task);return node; }
  const config = {
    assignments:['Assignments','assets.read','assets.assign','AssetAssignmentCreate','asset-assignments'],
    'location-history':['Location history','assets.location.read','assets.location.manage','LocationEvent','asset-location-events'],
    'meter-readings':['Meter readings','assets.meter.read','assets.meter.record','AssetMeterReadingCreate','asset-meter-readings'],
    components:['Components','assets.components.read','assets.components.manage','AssetComponentCreate','asset-components','ComponentUpdate'],
    inspections:['Inspections','assets.inspections.read','assets.inspections.manage','InspectionCreate','asset-inspections','InspectionUpdate'],
    defects:['Defects','assets.defects.read','assets.defects.manage','DefectCreate','asset-defects','DefectUpdate'],
    documents:['Documents','assets.documents.read','assets.documents.manage','AssetDocumentCreate','asset-documents','DocumentUpdate'],
    insurance:['Insurance','assets.insurance.read','assets.insurance.manage','InsuranceCreate','asset-insurance','InsuranceUpdate'],
    registrations:['Registration','assets.registration.read','assets.registration.manage','RegistrationCreate','asset-registrations','RegistrationUpdate'],
    media:['Photos','assets.media.read','assets.media.manage','MediaCreate','asset-media','MediaUpdate'],
    ownership:['Ownership','assets.ownership.read','assets.ownership.manage','OwnershipCreate','asset-ownership'],
    'status-history':['Status history','assets.read'],
    activity:['Activity','assets.audit.read']
  };
  async function initialize(){access=await api('/api/v1/equipment/access');}
  function form(title,schema,path,opts={}){
    const lookups={category_id:'asset-categories',parent_category_id:'asset-categories',default_location_id:'locations',responsible_employee_id:'employees',primary_operator_id:'employees',inspected_by_id:'users',parent_component_id:`assets/${selected}/components`,document_id:`assets/${selected}/documents`,inspection_id:`assets/${selected}/inspections`};
    return Workforce.form(title,schema,path,{contextId:null,lookupTargets:lookups,done:()=>selected?open(selected,tabName):loadList('assets'),...opts});
  }
  async function create(){await initialize();selected=null;return form('Register equipment','AssetCreate','/api/v1/assets',{done:async row=>{await loadList('assets');await open(row.id);}});}
  function facts(data,parent){const list=el('dl',undefined,'detail-list');for(const [key,value] of Object.entries(data)){if(value==null||['id','organization_id','asset_id','storage_path','created_by_id','updated_by_id'].includes(key)||typeof value==='object')continue;list.append(el('dt',label(key)),el('dd',String(value)));}parent.append(list);}
  async function open(id, tab='overview'){
    clearPhotos();selected=id;tabName=tab;await initialize();
    const overview=await api(`/api/v1/assets/${id}/overview`);
    openDialogTitle('EQUIPMENT · '+overview.asset.asset_number,overview.asset.name);
    $('detail-dialog').classList.add('equipment-dialog');
    const area=$('detail-body');
    const banner=el('div',undefined,'equipment-banner');
    banner.append(el('strong',overview.status),el('span',overview.operational_eligibility),el('span',overview.current_project?.name||'No active project'),el('span',overview.current_location?.name||'Location not recorded'));
    area.append(banner);
    const tabs=el('nav',undefined,'equipment-tabs');tabs.setAttribute('aria-label','Equipment record sections');
    for(const [key,title] of [['overview','Overview'],...Object.entries(config).filter(([,cfg])=>can(cfg[1])).map(([key,cfg])=>[key,cfg[0]])]){const b=button(title,()=>open(id,key));b.setAttribute('aria-pressed',String(key===tab));tabs.append(b);}area.append(tabs);
    const content=el('div',undefined,'equipment-content');area.append(content);
    if(tab==='overview'){
      const actions=el('div',undefined,'row-actions');
      if(can('assets.update'))actions.append(button('Edit equipment',()=>form('Edit equipment','AssetUpdate',`/api/v1/assets/${id}`,{record:overview.asset})));
      if(can('assets.status.change'))actions.append(button('Change status',()=>form('Change operational status','StatusChange',`/api/v1/assets/${id}/status`)));
      if(can('assets.transfer')&&overview.current_assignment)actions.append(button('Transfer equipment',()=>form('Transfer equipment','AssetTransfer',`/api/v1/assets/${id}/transfer`)));
      if(can('assets.archive'))actions.append(button(overview.asset.is_active?'Archive':'Restore',async()=>{await api(`/api/v1/assets/${id}/${overview.asset.is_active?'archive':'restore'}`,{method:'POST'});await open(id);}));
      content.append(actions);
      for(const reason of overview.reasons)content.append(el('p',reason,'access-note'));
      facts({...overview.asset,category:overview.category?.name,project:overview.current_project?.name,location:overview.current_location?.name,responsible:overview.responsible_employee&&`${overview.responsible_employee.first_name} ${overview.responsible_employee.last_name}`,operator:overview.primary_operator&&`${overview.primary_operator.first_name} ${overview.primary_operator.last_name}`,meter_status:overview.meter_status,meter_reading_age_days:overview.meter_reading_age_days},content);
      return;
    }
    const cfg=config[tab];
    const toolbar=el('div',undefined,'row-actions');content.append(toolbar);
    if(cfg[2]&&can(cfg[2]))toolbar.append(button('Add '+cfg[0].toLowerCase(),()=>form('Add '+cfg[0].toLowerCase(),cfg[3],`/api/v1/assets/${id}/${tab==='location-history'?'location-events':tab}`),true));
    if(tab==='meter-readings'&&can('assets.meter.override'))toolbar.append(button('Reset / replace meter',()=>form('Reset or replace meter','MeterReset',`/api/v1/assets/${id}/meter-reset`)));
    if(tab==='documents'&&can(cfg[2]))content.append(uploadForm('assets',id));
    if(tab==='media'&&can(cfg[2])){
      const input=el('input');input.type='file';input.accept='.png,.jpg,.jpeg';input.setAttribute('aria-label','Choose equipment photo');
      const error=el('p','','form-error');error.id='equipment-photo-error';
      toolbar.append(input,button('Upload photo',async()=>{if(!input.files[0])throw Error('Choose a photo');const body=new FormData();body.append('file',input.files[0]);await sendForm(`/api/v1/assets/${id}/media/upload`,body);await open(id,tab);}));content.append(error);
    }
    try{
      const response=await api(`/api/v1/assets/${id}/${tab}`);const rows=Array.isArray(response)?response:response.items;
      if(!rows.length)content.append(el('p','No records yet.','hint'));
      for(const row of rows){
        const card=el('article',undefined,'employee-record');facts(row,card);const actions=el('div',undefined,'row-actions');card.append(actions);content.append(card);
        if(cfg[5]&&can(cfg[2]))actions.append(button('Edit',()=>form('Edit '+cfg[0],cfg[5],`/api/v1/${cfg[4]}/${row.id}`,{record:row})));
        if(tab==='assignments'&&['ACTIVE','PLANNED'].includes(row.status)&&can('assets.assign')){
          actions.append(button('Complete',()=>form('Complete assignment','AssetAssignmentUpdate',`/api/v1/asset-assignments/${row.id}/complete`)),button('Cancel assignment',async()=>{await api(`/api/v1/asset-assignments/${row.id}/cancel`,{method:'POST'});await open(id,tab);}));
        }
        if(tab==='components'&&can(cfg[2])&&!['REMOVED','REPLACED','SCRAPPED'].includes(row.status))actions.append(button('Remove',()=>form('Remove component','ComponentRemoval',`/api/v1/asset-components/${row.id}/remove`)),button('Replace',()=>form('Install replacement component','AssetComponentCreate',`/api/v1/asset-components/${row.id}/replace`)));
        if(tab==='defects'&&can(cfg[2])&&['OPEN','ACKNOWLEDGED'].includes(row.status))actions.append(button('Resolve',()=>form('Resolve defect','ResolveDefect',`/api/v1/asset-defects/${row.id}/resolve`)));
        if(tab==='documents'){
          if(row.file_url?.startsWith('/api/'))actions.append(downloadButton('Download document',row.file_url));
          else if(/^https?:\/\//.test(row.file_url||'')){const link=el('a','Open document','secondary');link.href=row.file_url;link.target='_blank';link.rel='noopener noreferrer';actions.append(link);}
          for(const op of ['verify','archive'])if(can(op==='verify'?'assets.documents.verify':cfg[2])&&row.is_active)actions.append(button(label(op),async()=>{await api(`/api/v1/asset-documents/${row.id}/${op}`,{method:'POST'});await open(id,tab);}));
        }
        if(tab==='media'){
          if(row.media_type==='PHOTO'&&row.is_active&&row.file_url?.startsWith('/api/')){const result=await apiBlob(row.file_url);const image=el('img');image.alt=row.caption||row.file_name||'Equipment photo';image.className='equipment-photo';image.src=URL.createObjectURL(result.blob);photoUrls.push(image.src);card.prepend(image);}
          if(row.file_url?.startsWith('/api/'))actions.append(downloadButton('Download photo',row.file_url));
          if(can(cfg[2])&&row.is_active)for(const op of ['set-primary','archive'])actions.append(button(label(op),async()=>{await api(`/api/v1/asset-media/${row.id}/${op}`,{method:'POST'});await open(id,tab);}));
        }
      }
    }catch(error){content.append(el('p',error.message,'form-error'));}
  }
  async function dashboard(){
    await initialize();
    let area=$('fleet-summary');
    if(!area){area=el('div');area.id='fleet-summary';$('assets-view').insertBefore(area,$('assets-view').children[1]);}
    area.replaceChildren();
    const data=await api('/api/v1/assets/dashboard-summary');const summary=el('div',undefined,'equipment-summary');
    for(const key of ['total_assets','available_assets','assigned_assets','maintenance_assets','breakdown_assets','critical_open_defects']){const item=el('article');item.append(el('strong',String(data[key]??0)),el('span',label(key)));summary.append(item);}area.append(summary);
    const tools=el('div',undefined,'row-actions');
    if(can('assets.create'))tools.append(button('New category',()=>form('New asset category','AssetCategoryCreate','/api/v1/asset-categories',{done:()=>loadList('assets')})));
    tools.append(button('Manage categories',categories));
    const code=el('input');code.placeholder='Scan or enter asset tag';code.setAttribute('aria-label','Asset tag lookup');tools.append(code,button('Find asset tag',async()=>{const result=await api('/api/v1/assets/lookup?code='+encodeURIComponent(code.value.trim()));await open(result.asset.id);}));area.append(tools);
    if(!$('fleet-category_id')){const cats=await api('/api/v1/asset-categories');for(const [key,title,choices] of [['category_id','All categories',cats.map(c=>[c.id,c.name])],['status','All statuses',['AVAILABLE','ASSIGNED','OPERATING','STANDBY','MOBILIZING','DEMOBILIZING','UNDER_MAINTENANCE','BREAKDOWN','OUT_OF_SERVICE','QUARANTINED','DISPOSED','LOST','STOLEN'].map(v=>[v,label(v)])]]){const select=el('select');select.id='fleet-'+key;select.setAttribute('aria-label',title);select.append(new Option(title,''));for(const [value,name] of choices)select.append(new Option(name,value));select.onchange=()=>action(()=>loadList('assets'));$('asset-search').parentElement.prepend(select);}}
    if(!$('fleet-filter')){const select=el('select');select.id='fleet-filter';select.setAttribute('aria-label','Filter equipment');for(const [value,title] of [['','All equipment'],['is_available=true','Available for deployment'],['has_critical_defects=true','Critical defects'],['document_expiring_within_days=30','Documents expiring within 30 days'],['insurance_expiring_within_days=30','Insurance expiring within 30 days'],['registration_expiring_within_days=30','Registration expiring within 30 days']])select.append(new Option(title,value));select.onchange=()=>action(()=>loadList('assets'));$('asset-search').parentElement.prepend(select);}
  }
    async function categories(){openDialogTitle('EQUIPMENT','Asset categories');const rows=await api('/api/v1/asset-categories');for(const row of rows){const card=el('article',undefined,'employee-record');facts(row,card);if(can('assets.update'))card.append(button('Edit category',()=>form('Edit category','CategoryUpdate',`/api/v1/asset-categories/${row.id}`,{record:row,done:categories})));$('detail-body').append(card);}}
  function filters(){let result=$('fleet-filter')?.value?'&'+$('fleet-filter').value:'';for(const key of ['category_id','status'])if($('fleet-'+key)?.value)result+='&'+key+'='+encodeURIComponent($('fleet-'+key).value);return result;}
  return {open,create,dashboard,filters};
})();
