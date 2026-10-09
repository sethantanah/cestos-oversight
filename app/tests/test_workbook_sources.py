import unittest
from fastapi import APIRouter, Query
from pydantic import BaseModel
from app.api.v1.endpoints.workbook_connections import readable_source, effective_api_routes
class Row(BaseModel):
    id:str
    name:str
    nested:dict
class Page(BaseModel):
    items:list[Row]
    total:int
class Sources(unittest.TestCase):
    def test_flat_columns_and_pagination(self):
        router=APIRouter()
        @router.get('/api/v1/equipment',response_model=Page)
        async def listing(page:int=1,page_size:int=100):pass
        source=readable_source(router.routes[0])
        self.assertEqual(source['pagination'],'page')
        self.assertEqual([c['name'] for c in source['columns']],['id','name'])
    def test_required_context_and_sensitive_routes_excluded(self):
        router=APIRouter()
        @router.get('/api/v1/assets',response_model=list[Row])
        async def listing(project:str=Query(...)):pass
        @router.get('/api/v1/users',response_model=list[Row])
        async def users():pass
        for route in router.routes:self.assertIsNone(readable_source(route))

    def test_nested_router_prefix_and_dependencies_survive_discovery(self):
        from fastapi import Depends
        async def guard():return True
        inner=APIRouter()
        @inner.get('/records',response_model=list[Row])
        async def listing():pass
        outer=APIRouter()
        outer.include_router(inner,prefix='/api/v1',dependencies=[Depends(guard)])
        routes=list(effective_api_routes(outer.routes))
        self.assertEqual(readable_source(routes[0])['id'],'/api/v1/records')
        self.assertTrue(any(dep.call is guard for dep in routes[0].dependant.dependencies))

class SourcePermissions(unittest.IsolatedAsyncioTestCase):
    async def test_read_permission_denial_hides_source(self):
        from unittest.mock import patch, AsyncMock
        from fastapi import Depends
        from app.api.v1.endpoints.workbook_connections import read_permitted
        from app.core.exceptions import ForbiddenError
        code='assets.read'
        async def dependency():return code
        router=APIRouter()
        @router.get('/api/v1/assets',response_model=list[Row],dependencies=[Depends(dependency)])
        async def listing():pass
        denied=AsyncMock(side_effect=ForbiddenError('Denied'))
        with patch('app.api.v1.endpoints.workbook_connections.require_permission',return_value=denied):
            self.assertFalse(await read_permitted(router.routes[0].dependant,object(),object()))
