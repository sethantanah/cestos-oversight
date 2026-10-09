"""Validate embedded workbook media and select only assets belonging to shared sheets."""
import base64,binascii,re

def clean_workbook_media(book,sheets):
    folders=book.get('folders',[]);assets=book.get('assets',{})
    if not isinstance(folders,list) or len(folders)>50 or not isinstance(assets,dict):raise ValueError('Invalid workbook folders or attachments')
    clean_folders=[];ids=set();names=set()
    for f in folders:
        if not isinstance(f,dict) or not isinstance(f.get('id'),str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',f['id']) or f['id']=='unfiled' or f['id'] in ids or not isinstance(f.get('name'),str) or not f['name'].strip() or len(f['name'])>60 or f['name'].strip().lower() in names:raise ValueError('Invalid sheet folder')
        ids.add(f['id']);names.add(f['name'].strip().lower());clean_folders.append({'id':f['id'],'name':f['name']})
    original={s['id']:s for s in book['sheets']};used=set()
    for target in sheets:
        source=original[target['id']];folder=source.get('folderId');media=source.get('media',{})
        if folder:
            if folder not in ids:raise ValueError('Missing sheet folder')
            target['folderId']=folder
        if not isinstance(media,dict):raise ValueError('Invalid cell attachments')
        safe={}
        for key,refs in media.items():
            if not isinstance(key,str) or not re.fullmatch(r'\d+:\d+',key) or not isinstance(refs,list) or len(refs)>10 or any(not isinstance(i,str) for i in refs) or len(set(refs))!=len(refs):raise ValueError('Invalid cell attachment reference')
            r,c=map(int,key.split(':'))
            if r>=len(target['cells']) or c>=len(target['widths']) or any(i not in assets for i in refs):raise ValueError('Missing cell attachment')
            safe[key]=refs;used.update(refs)
        if safe:target['media']=safe
    total=0;clean_assets={}
    for id in used:
        a=assets[id]
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',id) or not isinstance(a,dict) or a.get('id')!=id or not isinstance(a.get('name'),str) or not a['name'] or len(a['name'])>250 or type(a.get('size')) is not int or not 1<=a['size']<=8*1024*1024 or a.get('mime') not in ('image/png','image/jpeg','image/gif','image/webp','video/mp4','video/webm','video/ogg','application/octet-stream') or not isinstance(a.get('data'),str) or len(a['data'])!=4*((a['size']+2)//3):raise ValueError('Invalid workbook attachment')
        try:decoded=base64.b64decode(a['data'],validate=True)
        except (ValueError,binascii.Error):raise ValueError('Invalid attachment encoding')
        if len(decoded)!=a['size']:raise ValueError('Invalid attachment size')
        if a.get('documentId') is not None and (not isinstance(a['documentId'],str) or not re.fullmatch(r'[0-9a-fA-F-]{36}',a['documentId'])):raise ValueError('Invalid media document ID')
        total+=a['size']
        if total>20*1024*1024:raise ValueError('Workbook attachments exceed 20 MB')
        clean_assets[id]={k:a[k] for k in ('id','name','size','mime','data')}
        if a.get('documentId'):clean_assets[id]['documentId']=a['documentId']
    visible_folders={s.get('folderId') for s in sheets}
    return {'folders':[f for f in clean_folders if f['id'] in visible_folders],'assets':clean_assets}
