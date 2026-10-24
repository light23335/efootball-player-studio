from pathlib import Path
import copy,json,struct,sys,unittest,sqlite3
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from card_motion import patch_tick,stock_routes
from card_presentation import repair_routes,key
from personal_runtime import render_commands

class RenderAndCardTests(unittest.TestCase):
 def test_4k_preserves_aspect_ratio_and_queues_real_engine_commands(self):
  options={'display':{'enabled':True,'height':2160},'frame_rate':{'enabled':True,'target':240}}
  commands,size=render_commands(options,1920,1080);self.assertEqual(size,(3840,2160));self.assertIn('r.SetRes 3840x2160f',commands);self.assertIn('t.MaxFPS 240',commands)
  _,size=render_commands(options,2400,1080);self.assertLessEqual(max(size),3840);self.assertAlmostEqual(size[0]/size[1],2400/1080,places=2)
  self.assertEqual(render_commands({},1920,1080),([],None))
 def test_stock_mini_uses_its_own_movie_or_same_series_large_background(self):
  cid=89135066911146;lib=SimpleNamespace(card_media={'movies':['Movies/0501_278_f02_v.usm','Movies/0501_m06_v.usm']},db=lambda:sqlite3.connect(':memory:'),_alias=lambda db,name:name)
  rows=stock_routes(lib,{cid:b'',cid+1:b''});self.assertEqual(rows,[{'key':cid>>28,'names':['0501_278_f02','0501_m06']}])
  lib.card_media['movies'].append('Movies/0501_278_m02_v.usm');self.assertEqual(stock_routes(lib,{cid:b''})[0]['names'][0],'0501_278_m02')
 def test_bound_identity_keeps_private_portrait_but_uses_real_art_series(self):
  original=89135066911146;bound=90159685099299
  definition={'identity':{'card_id':bound,'bound_original_player_id':57123,'previous_card_ids':[]},'card_art_source':{'source_id':str(original),'native_style':'0501','native_agent':278}}
  route={'cardId':bound,'suiteDonorId':bound,'portraitKey':'8001234','modelFaceKey':'8001234','thumbnail_names':['8001234_b','0501_278_f02','','8001234_m','','']};before=copy.deepcopy(route)
  self.assertEqual(repair_routes([route],[definition],{original:b''})[0]['suiteDonorId'],original)
  for name,value in before.items():
   if name!='suiteDonorId':self.assertEqual(route[name],value)
  definition.pop('card_art_source');route['thumbnail_names'][1]='0501_278_m02';route['suiteDonorId']=bound
  self.assertEqual(repair_routes([route],[definition],{original:b''})[0]['suiteDonorId'],original)

@unittest.skipUnless((Path(__file__).resolve().parents[2]/'球员工坊-V17/library/versions/V17-1f38a585/containers').is_dir(),'requires original card widget cache')
class NativeWidgetTests(unittest.TestCase):
 def test_tick_inserts_only_an_idempotent_play_check_and_keeps_destruct(self):
  from native_art import Assets
  from card_motion import packages
  from native_iostore import package_names
  root=Path(__file__).resolve().parents[2];assets=Assets(root/'球员工坊-V17/library/versions/V17-1f38a585/containers')
  for row in json.loads((root/'player-studio-v15/resources/native-card-motion.json').read_text())['widgets']:
   raw,meta=assets.get(row['path']);patched,report=patch_tick(raw,row)
   self.assertEqual(len(patched),len(raw)+6);self.assertEqual(package_names(raw),package_names(patched));self.assertTrue(report['native_destruct_cleanup_preserved']);self.assertEqual(patch_tick(patched,row)[0],patched)
   # Destruct's generated call bytes survive byte-for-byte elsewhere in the package.
   self.assertIn(bytes.fromhex('040b53'),patched)
   corrupted=bytearray(raw);h=struct.unpack_from('<16I',raw);corrupted[h[13]+h[14]+1]^=1
   # Exact Tick verification is exercised by changing its recorded script.
   bad=copy.deepcopy(row);bad['script_hex']='00'
   with self.assertRaises(ValueError):patch_tick(raw,bad)

if __name__=='__main__':unittest.main()
