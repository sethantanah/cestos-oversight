"""Regression tests for sharing route registration with authentication dependencies."""
import unittest
from fastapi import FastAPI
from app.api.v1.endpoints.workbook_shares import router

class SharingRoutes(unittest.TestCase):
    def test_routes_register_with_auth_query_token(self):
        app = FastAPI()
        app.include_router(router, prefix='/api/v1')
        paths = app.openapi()['paths']
        self.assertIn('get', paths['/api/v1/workbook-shares'])
        self.assertIn('post', paths['/api/v1/workbook-shares'])
        for path, method in [('/{share_token}/access', 'get'), ('/{share_token}', 'put')]:
            parameters = paths['/api/v1/workbook-shares' + path][method]['parameters']
            self.assertTrue(any(p['name'] == 'share_token' and p['in'] == 'path' for p in parameters))
            self.assertTrue(any(p['name'] == 'token' and p['in'] == 'query' for p in parameters))
        public = paths['/api/v1/workbook-shares/{share_token}']['get']
        self.assertFalse(public.get('security'))

if __name__ == '__main__':
    unittest.main()
