import json, unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from pydantic import ValidationError
from app.services import workbook_mapping_assistant as ai
from app.api.v1.endpoints import workbook_connections as routes

def sample():return ai.SheetSample(rowCount=4,columnCount=2,cells=[ai.SampleCell(r=0,c=0,text='Name',bold=True),ai.SampleCell(r=1,c=0,text='Eric',bold=False)],merges=[],sampled=True)
def table():return {'id':'/api/v1/records','columns':[{'name':'name','required':True,'type':'VARCHAR'},{'name':'project_id','required':True,'type':'UUID'}]}
def proposal():return ai.Proposal(mode='rows',headerRows=[0],labelColumn=0,start=1,end=3,blockSize=1,exclude=[],fields=[ai.SuggestedField(field='name',kind='column',r=0,c=0,confidence='high',reason='Header match')],summary='Rows under Name',warnings=[])
class PlannerChecks(unittest.TestCase):
    def test_required_fields_and_sampling_are_not_silently_accepted(self):
        result=ai.validate_proposal(proposal(),sample(),table())
        self.assertTrue(any('project_id' in w for w in result['warnings']))
        self.assertTrue(any('sample' in w for w in result['warnings']))
    def test_unknown_duplicate_and_outside_fields_rejected(self):
        for mode in ('unknown','duplicate','coordinate','range','kind'):
            p=proposal()
            if mode=='unknown':p.fields[0].field='password'
            if mode=='duplicate':p.fields.append(p.fields[0])
            if mode=='coordinate':p.fields[0].c=9
            if mode=='range':p.end=10
            if mode=='kind':p.fields[0].kind='row'
            with self.assertRaises(ValueError):ai.validate_proposal(p,sample(),table())
    def test_fixed_sources_must_be_in_the_observed_sample(self):
        p=proposal();p.mode='form';p.fields[0].kind='cell';p.fields[0].r=3
        with self.assertRaises(ValueError):ai.validate_proposal(p,sample(),table())
    def test_sample_limits_and_duplicates(self):
        s=sample();s.cells.append(s.cells[0])
        with self.assertRaises(ValueError):ai.validate_sample(s)
        with self.assertRaises(ValidationError):ai.SampleCell(r=0,c=0,text='x'*161,bold=False)
class PlannerApiChecks(unittest.IsolatedAsyncioTestCase):
    async def test_unconfigured_never_contacts_provider(self):
        with patch.object(ai.httpx,'AsyncClient') as client:
            with self.assertRaisesRegex(RuntimeError,'not configured'):await ai.propose_mapping(sample(),table(),'',SimpleNamespace(openai_api_key=None))
            client.assert_not_called()
    async def test_permission_denied_before_provider_call(self):
        body=ai.AssistRequest(table='/api/v1/secret',sheet=sample())
        with patch.object(routes,'tables',AsyncMock(return_value=[])),patch.object(routes,'propose_mapping',AsyncMock()) as call:
            with self.assertRaises(routes.HTTPException) as raised:await routes.assist(body,object(),object(),object())
            self.assertEqual(raised.exception.status_code,403);call.assert_not_awaited()
    async def test_schema_is_loaded_on_server(self):
        body=ai.AssistRequest(table='/api/v1/records',sheet=sample(),guidance='Use rows')
        with patch.object(routes,'tables',AsyncMock(return_value=[table()])),patch.object(routes,'get_settings',return_value=object()),patch.object(routes,'propose_mapping',AsyncMock(return_value={'ok':True})) as call:
            await routes.assist(body,object(),object(),object())
            self.assertEqual(call.call_args.args[1],table())
    async def test_provider_payload_is_structured_read_only_and_result_is_validated(self):
        response=SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'choices':[{'finish_reason':'stop','message':{'content':proposal().model_dump_json()}}]})
        client=AsyncMock();client.post.return_value=response
        context=AsyncMock();context.__aenter__.return_value=client
        with patch.object(ai.httpx,'AsyncClient',return_value=context):
            result=await ai.propose_mapping(sample(),table(),'Ignore totals',SimpleNamespace(openai_api_key='test-only',openai_model='configured-model'))
        payload=client.post.call_args.kwargs['json']
        self.assertFalse(payload['store']);self.assertNotIn('tools',payload)
        self.assertEqual(payload['model'],'configured-model');self.assertTrue(payload['response_format']['json_schema']['strict'])
        self.assertEqual(result['fields'][0]['field'],'name')
    async def test_refusal_and_truncated_output_fail_safely(self):
        for choice in [{'finish_reason':'length','message':{'content':'{}'}},{'finish_reason':'stop','message':{'refusal':'No'}}]:
            response=SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'choices':[choice]})
            client=AsyncMock();client.post.return_value=response;context=AsyncMock();context.__aenter__.return_value=client
            with patch.object(ai.httpx,'AsyncClient',return_value=context):
                with self.assertRaises(RuntimeError):await ai.propose_mapping(sample(),table(),'',SimpleNamespace(openai_api_key='test-only',openai_model='configured-model'))
