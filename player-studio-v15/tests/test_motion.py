from pathlib import Path
import copy,io,json,struct,sys,tempfile,types,unittest,uuid,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from native_motion import FIELDS,from_player,normalize,patch_record,apply_definition,MotionPresets

class MotionTests(unittest.TestCase):
 def style(self):return {'mode':'source','source_id':'7511','source_name':'Reference','parameters':{'52':4,'53':9,'54':2,'55':7}}
 def test_native_source_and_export_change_only_the_four_posture_fields(self):
  raw=bytes((i*17)%256 for i in range(400));selected=self.style();result=patch_record(raw,{'motion_style':selected})
  mask=sum(((1<<width)-1)<<bit for bit,width,_ in FIELDS.values())
  self.assertEqual(int.from_bytes(raw,'little')&~mask,int.from_bytes(result,'little')&~mask)
  loaded=from_player({'id':7511,'name':'Reference','payload':{'_studio_client_record':result.hex()}})
  self.assertEqual(loaded['parameters'],selected['parameters'])
  self.assertEqual(patch_record(raw,{}),raw)
  self.assertEqual(patch_record(raw,{'motion_style':{'mode':'legacy'}}),raw)
 def test_owned_and_native_growth_bases_agree_without_changing_identity(self):
  definition={'identity':{'card_id':90000001},'base_parameters':[0]*147,
              'owned':{'parameters':[0]*147,'_careerplan_base_parameters':[0]*147},'maximum_development':{'parameters':[0]*147}}
  result=apply_definition({'motion_style':self.style()},copy.deepcopy(definition))
  for array in (result['base_parameters'],result['owned']['parameters'],result['owned']['_careerplan_base_parameters'],result['maximum_development']['parameters']):
   self.assertEqual(array[52:56],[4,9,2,7]);self.assertEqual(array[:52],[0]*52);self.assertEqual(array[56:],[0]*91)
  self.assertEqual(result['identity'],definition['identity'])
 def test_invalid_or_incomplete_native_posture_is_rejected(self):
  for field,value in [('52',5),('53',10),('54',True),('55',-1)]:
   style=self.style();style['parameters'][field]=value
   with self.assertRaises(ValueError):normalize(style)
  with self.assertRaises(ValueError):from_player({'payload':{}})
 def test_style_roundtrips_through_project_and_reusable_presets(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=app.Store(Path(tmp));project=app.default_project();project['motion_style']=self.style();saved=store.save(project)
   self.assertEqual(store.project['motion_style']['parameters'],self.style()['parameters'])
   presets=MotionPresets(store);row=presets.save({'label':'青年边锋','style':store.project['motion_style']})['row']
   self.assertEqual(presets.list()[0],row);self.assertEqual(len(presets.list()),1)

if __name__=='__main__':unittest.main()
