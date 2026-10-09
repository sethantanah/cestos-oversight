import hashlib
import json
import unittest
import uuid
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock, Mock
from app.api.v1.endpoints.workbook_sync import WorkbookSave, payload_bytes, check_revision, save_workbook
from app.core.exceptions import ConflictError

def book():
    return {'version':1,'id':str(uuid.uuid4()),'name':'Field log','source':{'base64':'original'},'sheets':[{'id':'s','name':'Sheet','cells':[['Asset']], 'widths':[160], 'heights':[34], 'merges':[], 'connection':{'table':'/api/v1/assets'}}]}

class SyncChecks(unittest.IsolatedAsyncioTestCase):
    def test_payload_preserves_original_and_mapping(self):
        value=book()
        self.assertEqual(json.loads(payload_bytes(value)),value)
    def test_stale_or_deleted_revision_is_rejected(self):
        latest=Obj(id=uuid.uuid4(),is_active=True)
        with self.assertRaises(ConflictError):check_revision(latest,None)
        check_revision(latest,latest.id)
        latest.is_active=False
        with self.assertRaises(ConflictError):check_revision(latest,latest.id)
    def context(self):
        actor=Obj(id=uuid.uuid4(),organization_id=uuid.uuid4())
        session=Obj(scalar=AsyncMock(side_effect=[None,None]),execute=AsyncMock(),add=Mock(),flush=AsyncMock(),commit=AsyncMock(),rollback=AsyncMock())
        stored=Obj(relative_path='saved/file',filename='book.cestos.json',mime_type='application/json',size_bytes=100)
        storage=Obj(save=Mock(return_value=stored),delete=Mock())
        return actor,session,storage
    async def test_new_save_is_private_and_audited_under_lock(self):
        actor,session,storage=self.context()
        payload=WorkbookSave(workbook=book(),operation_id=uuid.uuid4())
        result=await save_workbook(payload,actor,session,storage)
        self.assertEqual(result['operation_id'],str(payload.operation_id))
        self.assertIn('pg_advisory_xact_lock',str(session.execute.call_args.args[0]))
        row=session.add.call_args_list[0].args[0]
        self.assertEqual(row.owner_id,actor.id)
        self.assertEqual(row.visibility,'PRIVATE')
        self.assertEqual(row.source_id,payload.operation_id)
        session.commit.assert_awaited_once()
    async def test_response_lost_retry_returns_same_version_without_writing(self):
        actor,session,storage=self.context()
        value=book(); payload=WorkbookSave(workbook=value,operation_id=uuid.uuid4())
        previous=Obj(id=uuid.uuid4(),owner_id=actor.id,tags=['wb-'+value['id']],content_hash=hashlib.sha256(payload_bytes(value)).hexdigest(),is_active=True)
        session.scalar=AsyncMock(return_value=previous)
        result=await save_workbook(payload,actor,session,storage)
        self.assertEqual(result['version'],str(previous.id))
        storage.save.assert_not_called();session.add.assert_not_called()
    async def test_retry_with_changed_content_fails(self):
        actor,session,storage=self.context();value=book()
        session.scalar=AsyncMock(return_value=Obj(owner_id=actor.id,tags=['wb-'+value['id']],content_hash='different'))
        with self.assertRaises(ConflictError):await save_workbook(WorkbookSave(workbook=value,operation_id=uuid.uuid4()),actor,session,storage)
        storage.save.assert_not_called()
    async def test_server_conflict_does_not_write_files(self):
        actor,session,storage=self.context()
        session.scalar=AsyncMock(side_effect=[None,Obj(owner_id=actor.id,id=uuid.uuid4(),is_active=True)])
        with self.assertRaises(ConflictError):await save_workbook(WorkbookSave(workbook=book(),operation_id=uuid.uuid4()),actor,session,storage)
        storage.save.assert_not_called()
    async def test_failed_commit_removes_only_new_file(self):
        actor,session,storage=self.context();session.commit.side_effect=RuntimeError('failed')
        with self.assertRaises(RuntimeError):await save_workbook(WorkbookSave(workbook=book(),operation_id=uuid.uuid4()),actor,session,storage)
        storage.delete.assert_called_once_with('saved/file');session.rollback.assert_awaited_once()
