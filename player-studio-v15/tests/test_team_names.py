import copy,json,sqlite3,tempfile,types,unittest
from pathlib import Path
from team_names import display,aliases
from write_modes import design,statuses

class RealTeamNamesTests(unittest.TestCase):
 def test_aliases_are_display_only_guarded_by_id_and_exact_native_source(self):
  original={'kind':'team','id':109,'name':'马德里查马丁 白','name_en':'Madrid Chamartin B'}
  before=copy.deepcopy(original);real=display(original)
  self.assertEqual(real['name'],'皇家马德里');self.assertEqual(real['source_name'],original['name']);self.assertEqual(original,before)
  self.assertEqual(display(dict(original,name_en='Another user club')),dict(original,name_en='Another user club'))
  nation={'kind':'nation','id':109,'name':'Other','name_en':'Madrid Chamartin B'};self.assertEqual(display(nation),nation)
  self.assertEqual(len(aliases()),372)
 def test_identity_catalogue_does_not_touch_raw_player_or_project_receipts(self):
  from native_library import NativeLibrary
  with tempfile.TemporaryDirectory()as temp:
   root=Path(temp);(root/'assets').mkdir();db=sqlite3.connect(root/'library.sqlite3')
   db.execute('create table identities(kind,id,name,name_en)');db.execute('insert into identities values(?,?,?,?)',('team',173,'曼彻斯特 蓝','Manchester B'));db.commit();db.close()
   lib=object.__new__(NativeLibrary);lib.resources=root
   project={'package_id':'a','identity':{'team_id':173,'team':'曼彻斯特 蓝'}};store=types.SimpleNamespace(root=root)
   digest=design('players',project,store);doc={'players':[{'identity':{'package_id':'a'}}],'write_designs':{'version':1,'players':{'a':digest}}}
   for _ in range(3):self.assertEqual(lib.identities()['team'][0]['name'],'曼城')
   self.assertEqual(statuses('players',[project],doc,store)['a'],'unchanged')
   db=sqlite3.connect(root/'library.sqlite3');self.assertEqual(db.execute('select name from identities').fetchone()[0],'曼彻斯特 蓝');db.close()

if __name__=='__main__':unittest.main()
