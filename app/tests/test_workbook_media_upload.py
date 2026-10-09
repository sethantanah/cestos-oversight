import hashlib,io,unittest,uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from fastapi import UploadFile
from app.api.v1.endpoints.documents import upload
from app.core.exceptions import ValidationError
class MediaUpload(unittest.IsolatedAsyncioTestCase):
 async def run_upload(self,content_hash):
  previous=SimpleNamespace(content_hash=content_hash)
  session=SimpleNamespace(scalar=AsyncMock(return_value=previous))
  with patch('app.api.v1.endpoints.workbook_sync.lock_workbook',AsyncMock()) as lock, patch('app.api.v1.endpoints.documents.public',return_value={'id':'stored'}) as public:
   result=await upload(file=UploadFile(filename='photo.png',file=io.BytesIO(b'abc')),title='photo.png',category='Workbook Media',tags='wm-test',source_type=None,source_id=None,visibility='PRIVATE',actor=SimpleNamespace(id=uuid.uuid4(),organization_id=uuid.uuid4()),session=session,storage=SimpleNamespace(max_bytes=100))
   lock.assert_awaited_once();public.assert_called_once();return result
 async def test_retries_return_existing_document_without_saving_another_file(self):
  self.assertEqual(await self.run_upload(hashlib.sha256(b'abc').hexdigest()),{'id':'stored'})
 async def test_reusing_identifier_for_different_bytes_is_rejected(self):
  with self.assertRaises(ValidationError):await self.run_upload('different')
