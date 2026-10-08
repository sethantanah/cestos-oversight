"""Anyone with an unguessable link may read; only named active users may edit."""
import hashlib
import json
import secrets
import re
import math
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_current_active_user
from app.db.session import get_session
from app.models import User
from app.models.workbook_share import WorkbookShare
from app.services.audit import record_audit
router=APIRouter(prefix="/workbook-shares",tags=["Workbook sharing"])

class ShareCreate(BaseModel):
    workbook: dict
    editor_emails: list[str] = Field(default_factory=list,max_length=30)
    expires_days: int = Field(default=7,ge=1,le=90)
class ShareUpdate(BaseModel):
    workbook: dict
    revision: int = Field(ge=1)

def clean_workbook(value):
    # Public payloads exclude source Excel bytes, hidden sheets, and database mappings.
    if len(json.dumps(value))>5_000_000:raise HTTPException(413,"Shared workbook exceeds 5 MB")
    if value.get("version")!=1 or not isinstance(value.get("id"),str) or len(value["id"])>100:raise HTTPException(422,"Invalid workbook")
    sheets=value.get("sheets")
    if not isinstance(sheets,list) or not 1<=len(sheets)<=30:raise HTTPException(422,"Invalid sheets")
    clean=[]
    ids=set();names=set()
    for sheet in sheets:
        if not isinstance(sheet,dict):raise HTTPException(422,"Invalid sheet")
        if sheet.get("hidden"):continue
        if sheet.get("previewLimited"):raise HTTPException(422,"Partially loaded sheets cannot be shared")
        rows=sheet.get("cells")
        widths=sheet.get("widths",[]);heights=sheet.get("heights",[])
        if not isinstance(rows,list) or not 1<=len(rows)<=500 or not isinstance(widths,list) or not 1<=len(widths)<=50 or not isinstance(heights,list) or len(heights)!=len(rows):raise HTTPException(422,"Invalid sheet dimensions")
        if any(not isinstance(row,list) or len(row)!=len(widths) or any(not isinstance(cell,str) or len(cell)>32767 for cell in row) for row in rows):raise HTTPException(422,"Invalid cells")
        if any(not isinstance(n,(int,float)) or not math.isfinite(n) or not 0<=n<=10000 for n in widths+heights):raise HTTPException(422,"Invalid dimensions")
        merges=sheet.get("merges",[])
        if not isinstance(merges,list) or len(merges)>25000:raise HTTPException(422,"Invalid merges")
        occupied=set()
        for m in merges:
            if not isinstance(m,dict) or any(type(m.get(k)) is not int for k in ["r","c","er","ec"]) or not (0<=m["r"]<=m["er"]<len(rows) and 0<=m["c"]<=m["ec"]<len(widths)):raise HTTPException(422,"Invalid merge")
            for r in range(m["r"],m["er"]+1):
                for c in range(m["c"],m["ec"]+1):
                    if (r,c) in occupied:raise HTTPException(422,"Overlapping merges")
                    occupied.add((r,c))
        if not isinstance(sheet.get("id"),str) or not isinstance(sheet.get("name"),str):raise HTTPException(422,"Invalid sheet name")
        if sheet["id"] in ids or not sheet["name"].strip() or len(sheet["name"])>31 or re.search(r"[\\/?*\[\]:]",sheet["name"]) or sheet["name"].lower() in names:raise HTTPException(422,"Duplicate or invalid sheet name")
        ids.add(sheet["id"]);names.add(sheet["name"].lower())
        formats=sheet.get("formats",{})
        if not isinstance(formats,dict) or any(not isinstance(v,dict) for v in formats.values()):raise HTTPException(422,"Invalid formatting")
        safe_formats={}
        for key,format in formats.items():
            if not re.fullmatch(r"\d+:\d+",key):raise HTTPException(422,"Invalid format coordinates")
            r,c=map(int,key.split(":"))
            if r>=len(rows) or c>=len(widths):raise HTTPException(422,"Invalid format coordinates")
            safe={}
            for field in ["bold","italic","underline","strike","wrap"]:
                if field in format:
                    if type(format[field]) is not bool:raise HTTPException(422,"Invalid format")
                    safe[field]=format[field]
            for field,allowed in {"align":["left","center","right"],"vertical":["top","middle","bottom"],"dataType":["general","text","number","currency","percent","date","time","datetime"]}.items():
                if field in format:
                    if format[field] not in allowed:raise HTTPException(422,"Invalid format")
                    safe[field]=format[field]
            for field in ["color","background"]:
                if field in format and isinstance(format[field],str) and re.fullmatch(r"#[0-9a-fA-F]{6}",format[field]):safe[field]=format[field]
            for field in ["fontName","currency"]:
                if field in format and isinstance(format[field],str):safe[field]=format[field][:100]
            for field in ["fontSize","decimals"]:
                if field in format and type(format[field]) in (int,float) and 0<=format[field]<=100:safe[field]=format[field]
            safe_formats[key]=safe
        clean.append({"id":sheet["id"],"name":sheet["name"][:31],"cells":rows,"widths":widths,"heights":heights,"merges":merges,"formats":safe_formats,"imported":True})
    if not clean:raise HTTPException(422,"No visible sheets to share")
    return {"version":1,"id":value["id"],"name":str(value.get("name","Workbook"))[:250],"template":False,"sheets":clean}

def digest(token):return hashlib.sha256(token.encode()).hexdigest()
async def lookup(session,token,lock=False):
    if not 30<=len(token)<=100:raise HTTPException(404,"Share not found")
    query=select(WorkbookShare).where(WorkbookShare.token_hash==digest(token),WorkbookShare.revoked.is_(False),WorkbookShare.expires_at>datetime.now(timezone.utc))
    if lock:query=query.with_for_update()
    row=await session.scalar(query)
    if row is None:raise HTTPException(404,"Share expired, revoked or unavailable")
    return row

def can_edit(row,actor):return row.organization_id==actor.organization_id and (row.owner_id==actor.id or str(actor.id) in row.editor_ids)
def audit(session,actor,row,action):
    record_audit(session,organization_id=actor.organization_id,actor_user_id=actor.id,action=action,entity_type="workbook_share",entity_id=row.id,new_values={"revision":row.revision,"workbook_id":row.workbook_id})

@router.post("")
async def create(payload:ShareCreate,actor:User=Depends(get_current_active_user),session:AsyncSession=Depends(get_session)):
    book=clean_workbook(payload.workbook)
    editors=[]
    for email in set(e.strip().lower() for e in payload.editor_emails):
        user=await session.scalar(select(User).where(User.organization_id==actor.organization_id,func.lower(User.email)==email,User.is_active.is_(True),User.archived_at.is_(None)))
        if user is None:raise HTTPException(422,"An editor email does not match an active account in your organization")
        editors.append(str(user.id))
    token=secrets.token_urlsafe(32)
    row=WorkbookShare(organization_id=actor.organization_id,owner_id=actor.id,workbook_id=book["id"],token_hash=digest(token),workbook=book,editor_ids=editors,revision=1,history=[],revoked=False,expires_at=datetime.now(timezone.utc)+timedelta(days=payload.expires_days))
    session.add(row);await session.flush();audit(session,actor,row,"workbook_share.created");await session.commit()
    return {"id":str(row.id),"token":token,"expires_at":row.expires_at}

@router.get("")
async def list_shares(workbook_id:str,actor:User=Depends(get_current_active_user),session:AsyncSession=Depends(get_session)):
    rows=(await session.scalars(select(WorkbookShare).where(WorkbookShare.owner_id==actor.id,WorkbookShare.organization_id==actor.organization_id,WorkbookShare.workbook_id==workbook_id,WorkbookShare.revoked.is_(False)))).all()
    return [{"id":str(row.id),"expires_at":row.expires_at,"editors":len(row.editor_ids)} for row in rows]

@router.delete("/{identifier}")
async def revoke(identifier:uuid.UUID,actor:User=Depends(get_current_active_user),session:AsyncSession=Depends(get_session)):
    row=await session.scalar(select(WorkbookShare).where(WorkbookShare.id==identifier,WorkbookShare.owner_id==actor.id,WorkbookShare.organization_id==actor.organization_id).with_for_update())
    if row is None:raise HTTPException(404,"Share not found")
    row.revoked=True;audit(session,actor,row,"workbook_share.revoked");await session.commit();return {"revoked":True}

@router.get("/{token}")
async def read(token:str,response:Response,session:AsyncSession=Depends(get_session)):
    row=await lookup(session,token);response.headers["Cache-Control"]="no-store";response.headers["Referrer-Policy"]="no-referrer"
    return {"workbook":row.workbook,"revision":row.revision}

@router.get("/{token}/access")
async def access(token:str,actor:User=Depends(get_current_active_user),session:AsyncSession=Depends(get_session)):
    row=await lookup(session,token);return {"can_edit":can_edit(row,actor)}

@router.put("/{token}")
async def update(token:str,payload:ShareUpdate,actor:User=Depends(get_current_active_user),session:AsyncSession=Depends(get_session)):
    row=await lookup(session,token,True)
    if not can_edit(row,actor):raise HTTPException(403,"This link is read-only for your account")
    if row.revision!=payload.revision:raise HTTPException(409,"Another editor saved a newer version. Download your backup, reload and reconcile your changes.")
    book=clean_workbook(payload.workbook)
    if book["id"]!=row.workbook_id:raise HTTPException(422,"Workbook identity cannot change")
    row.history=([{"revision":row.revision,"workbook":row.workbook}]+row.history)[:5]
    row.workbook=book;row.revision+=1;audit(session,actor,row,"workbook_share.updated");await session.commit()
    return {"revision":row.revision}
