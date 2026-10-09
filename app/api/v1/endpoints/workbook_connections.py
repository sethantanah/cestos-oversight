"""Read-only schema discovery and validation for workbook mappings. No database writes."""
import inspect
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_current_active_user, require_permission, require_role
from app.core.exceptions import ForbiddenError
from app.db.session import get_session
from app.db.base import Base
from app.models import User

router = APIRouter(prefix="/workbook-connections", tags=["Workbook mapping previews"])

class MappingRequest(BaseModel):
    table: str
    mapping: dict[str, int]
    rows: list[list[str]] = Field(max_length=2000)

async def catalog(request, actor, session):
    models={m.class_.__name__:m.class_ for m in Base.registry.mappers}
    result={}
    for route in request.app.routes:
        if not isinstance(route,APIRoute) or "POST" not in route.methods or "{" in route.path or not route.path.startswith("/api/v1/"): continue
        if len(route.dependant.body_params)!=1: continue
        schema=route.dependant.body_params[0].type_
        if not inspect.isclass(schema) or not issubclass(schema,BaseModel) or not schema.__name__.endswith("Create"): continue
        model=models.get(schema.__name__[:-6])
        if model is None or not hasattr(model,"organization_id") or model.__name__ in {"User","Role","Permission","Organization"}: continue
        if not set(schema.model_fields).issubset(set(model.__table__.columns.keys())): continue
        async def permitted(dependant):
            for dep in dependant.dependencies:
                call=dep.call
                if call and getattr(call,"__name__","")=="dependency":
                    variables=inspect.getclosurevars(call).nonlocals
                    try:
                        if "code" in variables: await require_permission(variables["code"])(actor,session)
                        elif "name" in variables: await require_role(variables["name"])(actor)
                        else: return False
                    except ForbiddenError: return False
                if not await permitted(dep): return False
            return True
        if await permitted(route.dependant): result[route.path]=(schema,model)
    return result

@router.get("/tables")
async def tables(request:Request, actor:User=Depends(get_current_active_user), session:AsyncSession=Depends(get_session)):
    result=[]
    for path,(schema,model) in (await catalog(request,actor,session)).items():
        contract=schema.model_json_schema(); required=set(contract.get("required",[]))
        columns=[{"name":name,"schema":definition,"required":name in required,"nullable":model.__table__.c[name].nullable,"type":str(model.__table__.c[name].type)} for name,definition in contract.get("properties",{}).items()]
        result.append({"id":path,"name":model.__tablename__,"columns":columns})
    return result

@router.post("/preview")
async def preview(body:MappingRequest, request:Request, actor:User=Depends(get_current_active_user), session:AsyncSession=Depends(get_session)):
    entry=(await catalog(request,actor,session)).get(body.table)
    if not entry: raise HTTPException(403,"This table is not available for workbook mappings")
    schema,model=entry
    if set(body.mapping)-set(schema.model_fields) or len(set(body.mapping.values()))!=len(body.mapping): raise HTTPException(422,"Map each sheet column to at most one supported database field")
    if any(i<0 or i>=100 for i in body.mapping.values()): raise HTTPException(422,"Invalid sheet column")
    issues=[]; prepared=[]
    for index,row in enumerate(body.rows):
        if not any(value.strip() for value in row): continue
        data={field:row[col].strip() for field,col in body.mapping.items() if col<len(row) and row[col].strip()}
        try:
            record=schema.model_validate(data); values=record.model_dump()
            for name,value in values.items():
                column=model.__table__.c[name]
                if value is None and not column.nullable and column.default is None and column.server_default is None: issues.append({"row":index+1,"field":name,"message":"Database field cannot be null"})
                for fk in column.foreign_keys:
                    if value is None: continue
                    target=fk.column.table; query=select(fk.column).where(fk.column==value)
                    if "organization_id" not in target.c:
                        issues.append({"row":index+1,"field":name,"message":"This relationship requires review in the destination form"}); continue
                    query=query.where(target.c.organization_id==actor.organization_id)
                    if "archived_at" in target.c: query=query.where(target.c.archived_at.is_(None))
                    if await session.scalar(query) is None: issues.append({"row":index+1,"field":name,"message":"Related record not found in your organization; enter its record ID"})
            keys=[list(c.columns.keys()) for c in model.__table__.constraints if isinstance(c,UniqueConstraint)]
            keys += [[c.name] for c in model.__table__.columns if c.unique]
            scoped={**values,"organization_id":actor.organization_id}
            for names in keys:
                if all(scoped.get(name) is not None for name in names):
                    query=select(model.id).where(model.organization_id==actor.organization_id,*(model.__table__.c[name]==scoped[name] for name in names))
                    if await session.scalar(query) is not None: issues.append({"row":index+1,"field":", ".join(names),"message":"Unique values already exist"})
                    if any(all({**prior,"organization_id":actor.organization_id}.get(name)==scoped[name] for name in names) for prior in prepared): issues.append({"row":index+1,"field":", ".join(names),"message":"Duplicate unique values in sheet"})
            prepared.append(values)
        except ValidationError as exc:
            issues.extend({"row":index+1,"field":".".join(map(str,e["loc"])),"message":e["msg"]} for e in exc.errors())
    if not prepared and not issues: issues.append({"row":0,"field":"","message":"No data rows"})
    return {"issues":issues,"count":len(prepared),"preview":prepared[:10],"writes_enabled":False}


def effective_api_routes(routes):
    # FastAPI may retain included routers rather than flattening app.routes.
    # Effective candidates include inherited prefixes and authentication dependencies.
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif callable(getattr(route, 'effective_candidates', None)):
            yield from effective_api_routes(route.effective_candidates())
        elif isinstance(getattr(route, 'original_route', None), APIRoute):
            yield route


def readable_source(route):
    """Describe supported collection responses; data is fetched via the original secured route."""
    from typing import get_args, get_origin
    if not isinstance(getattr(route, 'original_route', route), APIRoute) or 'GET' not in route.methods or '{' in route.path or not route.path.startswith('/api/v1/'):
        return None
    if route.path.startswith(('/api/v1/auth', '/api/v1/workbook-', '/api/v1/sync', '/api/v1/users', '/api/v1/roles', '/api/v1/permissions', '/api/v1/organizations')):
        return None
    if any(field.field_info.is_required() for field in route.dependant.query_params):
        return None
    response = route.response_model
    pagination = 'none'
    if get_origin(response) is list:
        row = get_args(response)[0]
    elif inspect.isclass(response) and issubclass(response, BaseModel) and 'items' in response.model_fields:
        items = response.model_fields['items'].annotation
        if get_origin(items) is not list:
            return None
        row = get_args(items)[0]
        queries = {field.name for field in route.dependant.query_params}
        if not {'page', 'page_size'}.issubset(queries):
            return None
        pagination = 'page'
    else:
        return None
    if not inspect.isclass(row) or not issubclass(row, BaseModel):
        return None
    contract = row.model_json_schema()
    columns = []
    for name, definition in contract.get('properties', {}).items():
        choices = definition.get('anyOf', [definition])
        flat = [item for item in choices if item.get('type') != 'null']
        if len(flat) != 1:
            continue
        field = flat[0]
        if '$ref' in field:
            field = contract.get('$defs', {}).get(field['$ref'].split('/')[-1], {})
        if field.get('type') not in ('string', 'number', 'integer', 'boolean'):
            continue
        columns.append({'name': name, 'type': field['type'], 'format': field.get('format')})
    if not columns:
        return None
    return {'id': route.path, 'name': route.path.removeprefix('/api/v1/').replace('-', ' ').replace('/', ' / ').title(), 'columns': columns, 'pagination': pagination}

async def read_permitted(dependant, actor, session):
    for dep in dependant.dependencies:
        call = dep.call
        if call and getattr(call, '__name__', '') == 'dependency':
            variables = inspect.getclosurevars(call).nonlocals
            try:
                if 'code' in variables:
                    await require_permission(variables['code'])(actor, session)
                elif 'name' in variables:
                    await require_role(variables['name'])(actor)
                else:
                    return False
            except ForbiddenError:
                return False
        if not await read_permitted(dep, actor, session):
            return False
    return True

@router.get('/sources')
async def sources(request:Request, actor:User=Depends(get_current_active_user), session:AsyncSession=Depends(get_session)):
    result = {}
    for route in effective_api_routes(request.app.routes):
        source = readable_source(route)
        if source and await read_permitted(route.dependant, actor, session):
            result[source['id']] = source
    return sorted(result.values(), key=lambda source: source['name'])
