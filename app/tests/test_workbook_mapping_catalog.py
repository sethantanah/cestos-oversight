import unittest
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from fastapi import APIRouter, FastAPI, Depends
from pydantic import BaseModel
from app.api.v1.endpoints import workbook_connections as mapping
from app.core.exceptions import ForbiddenError

class LocationCreate(BaseModel):
    name:str
class ReadRow(BaseModel):
    id:str
    name:str

class CatalogChecks(unittest.IsolatedAsyncioTestCase):
    def request(self,denied=False):
        code='locations.create'
        async def dependency():return code
        inner=APIRouter()
        @inner.post('/locations',dependencies=[Depends(dependency)])
        async def create(body:LocationCreate):pass
        @inner.get('/read-records',response_model=list[ReadRow],dependencies=[Depends(dependency)])
        async def read():pass
        app=FastAPI();app.include_router(inner,prefix='/api/v1')
        return SimpleNamespace(app=app)

    async def test_nested_create_routes_are_discovered_and_read_schemas_are_draft_only(self):
        permitted=AsyncMock()
        with patch.object(mapping,'require_permission',return_value=permitted):
            request=self.request();catalog=await mapping.catalog(request,object(),object())
            self.assertIn('/api/v1/locations',catalog)
            tables=await mapping.tables(request,object(),object())
            by_id={t['id']:t for t in tables}
            self.assertTrue(by_id['/api/v1/locations']['validationAvailable'])
            self.assertFalse(by_id['/api/v1/read-records']['validationAvailable'])
            self.assertEqual([c['name'] for c in by_id['/api/v1/read-records']['columns']],['id','name'])
            self.assertTrue(permitted.await_count>=2)

    async def test_denied_tables_are_not_disclosed(self):
        with patch.object(mapping,'require_permission',return_value=AsyncMock(side_effect=ForbiddenError('Denied'))):
            self.assertEqual(await mapping.tables(self.request(),object(),object()),[])

    async def test_read_schema_cannot_be_used_as_create_preview(self):
        with patch.object(mapping,'require_permission',return_value=AsyncMock()):
            with self.assertRaises(mapping.HTTPException) as raised:
                await mapping.preview(mapping.MappingRequest(table='/api/v1/read-records',mapping={'name':0},rows=[['Eric']]),self.request(),object(),object())
            self.assertEqual(raised.exception.status_code,403)
