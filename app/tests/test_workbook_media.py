import unittest,copy
from app.services.workbook_media import clean_workbook_media
from app.api.v1.endpoints.workbook_shares import clean_workbook

def book():
    return {'version':1,'id':'book','name':'Media','folders':[{'id':'f','name':'Reports'},{'id':'hidden-folder','name':'Hidden folder'}],'assets':{'a':{'id':'a','name':'file.txt','mime':'application/octet-stream','size':3,'data':'YWJj'},'hidden':{'id':'hidden','name':'private.txt','mime':'application/octet-stream','size':3,'data':'YWJj'}},'sheets':[{'id':'s','name':'Data','folderId':'f','cells':[['hello']],'widths':[160],'heights':[34],'merges':[],'media':{'0:0':['a']}},{'id':'hidden','name':'Hidden','hidden':True,'folderId':'hidden-folder','cells':[['secret']],'widths':[160],'heights':[34],'merges':[],'media':{'0:0':['hidden']}}]}
class MediaChecks(unittest.TestCase):
    def test_shared_copy_keeps_visible_media_and_folders_only(self):
        result=clean_workbook(book())
        self.assertEqual(set(result['assets']),{'a'})
        self.assertEqual(result['folders'],[{'id':'f','name':'Reports'}])
        self.assertEqual(result['sheets'][0]['media'],{'0:0':['a']})
    def test_malformed_media_and_references_are_rejected(self):
        for change in ('data','size','mime','ref','cell','folder'):
            b=book()
            if change=='data':b['assets']['a']['data']='!!!!'
            if change=='size':b['assets']['a']['size']=4
            if change=='mime':b['assets']['a']['mime']='text/html'
            if change=='ref':b['sheets'][0]['media']={'0:0':['missing']}
            if change=='cell':b['sheets'][0]['media']={'2:0':['a']}
            if change=='folder':b['sheets'][0]['folderId']='missing'
            with self.assertRaises(ValueError):clean_workbook_media(b,copy.deepcopy(b['sheets']))
    def test_media_validator_does_not_modify_original_asset_data(self):
        b=book();before=copy.deepcopy(b);clean_workbook_media(b,copy.deepcopy(b['sheets']));self.assertEqual(b,before)
