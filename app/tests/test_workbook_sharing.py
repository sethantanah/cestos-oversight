"""Dependency-free checks of the production validation and revision functions.
These do not replace HTTP/database integration tests in the backend environment.
"""
import ast, asyncio, copy, json, math, re, unittest
from pathlib import Path
from types import SimpleNamespace as Obj

source=Path(__file__).resolve().parents[1]/'api/v1/endpoints/workbook_shares.py'
tree=ast.parse(source.read_text(encoding='utf-8'))
class HTTPException(Exception):
    def __init__(self,status_code,detail):self.status_code=status_code;super().__init__(detail)
namespace={'json':json,'math':math,'re':re,'HTTPException':HTTPException}
for node in tree.body:
    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in ['clean_workbook','can_edit','update']:
        node.decorator_list=[]
        for arg in node.args.args:arg.annotation=None
        node.args.defaults=[ast.Constant(None) for _ in node.args.defaults]
        node.returns=None
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(source),'exec'),namespace)

def book():return {'version':1,'id':'book','name':'Test','source':{'base64':'secret'},'sheets':[{'id':'s','name':'Sheet','cells':[['1'],['2']],'widths':[160],'heights':[34,34],'merges':[],'connection':{'table':'private'}}]}
class SharingChecks(unittest.TestCase):
    def test_date_time_formats_survive_sharing(self):
        value=book()
        style={"dataType":"datetime","dateOrder":"dmy","dateSeparator":"/","timeClock":"12","showSeconds":True}
        value['sheets'][0]['formats']={"0:0":style}
        self.assertEqual(namespace['clean_workbook'](value)['sheets'][0]['formats']['0:0'],style)
        value['sheets'][0]['formats']['0:0']['dateSeparator']='bad'
        with self.assertRaises(HTTPException):namespace['clean_workbook'](value)

    def test_view_print_and_larger_sheets(self):
        value=book();s=value['sheets'][0]
        s['cells']=[['']*100 for _ in range(2000)];s['widths']=[100]*100;s['heights']=[30]*2000
        s['view']={'freezeRows':1,'freezeColumns':2,'filterColumn':4,'filterText':'test'}
        s['print']={'orientation':'portrait','fit':'width','repeatRows':1,'breakRows':[40], 'area':{'r':0,'c':0,'er':99,'ec':10}}
        clean=namespace['clean_workbook'](value)['sheets'][0]
        self.assertEqual(clean['view'],s['view']);self.assertEqual(clean['print'],s['print'])
        s['print']['breakRows']=[2000]
        with self.assertRaises(HTTPException):namespace['clean_workbook'](value)

    def test_excludes_private_metadata(self):
        value=book();value['sheets'].append(dict(value['sheets'][0],id='hidden',hidden=True))
        clean=namespace['clean_workbook'](value)
        self.assertNotIn('source',clean);self.assertNotIn('connection',clean['sheets'][0]);self.assertEqual(len(clean['sheets']),1)
    def test_rejects_corrupt_rows(self):
        value=book();value['sheets'][0]['cells'][0].append('extra')
        with self.assertRaises(HTTPException):namespace['clean_workbook'](value)
    def test_rejects_overlapping_merges(self):
        value=book();value['sheets'][0]['merges']=[{'r':0,'c':0,'er':1,'ec':0}]*2
        with self.assertRaises(HTTPException):namespace['clean_workbook'](value)
    def test_editor_must_match_organization_and_grant(self):
        row=Obj(organization_id='org',owner_id='owner',editor_ids=['editor'])
        self.assertTrue(namespace['can_edit'](row,Obj(organization_id='org',id='editor')))
        self.assertFalse(namespace['can_edit'](row,Obj(organization_id='other',id='editor')))
        self.assertFalse(namespace['can_edit'](row,Obj(organization_id='org',id='stranger')))
    def test_conflicting_save_does_not_mutate(self):
        row=Obj(organization_id='org',owner_id='owner',editor_ids=[],revision=2,workbook_id='book',workbook=book(),history=[])
        async def lookup(*args):return row
        namespace['lookup']=lookup;namespace['audit']=lambda *args:None
        with self.assertRaises(HTTPException) as raised:asyncio.run(namespace['update']('token',Obj(workbook=book(),revision=1),Obj(organization_id='org',id='owner'),Obj()))
        self.assertEqual(raised.exception.status_code,409);self.assertEqual(row.revision,2);self.assertEqual(row.history,[])
    def test_successful_save_preserves_previous_revision(self):
        row=Obj(organization_id='org',owner_id='owner',editor_ids=[],revision=2,workbook_id='book',workbook=book(),history=[])
        async def lookup(*args):return row
        async def commit():pass
        namespace['lookup']=lookup;namespace['audit']=lambda *args:None
        changed=book();changed['sheets'][0]['cells'][0][0]='new'
        result=asyncio.run(namespace['update']('token',Obj(workbook=changed,revision=2),Obj(organization_id='org',id='owner'),Obj(commit=commit)))
        self.assertEqual(result['revision'],3);self.assertEqual(row.history[0]['workbook']['sheets'][0]['cells'][0][0],'1')
if __name__=='__main__':unittest.main()
