import copy,json,sqlite3,sys,tempfile,types,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import draw_v22 as draw
from native_draw_v22 import apply
from personal_runtime import draw_response_fields,sanitize_draw_effects
import packs

CORE=Path(__file__).resolve().parents[1]
PROFILES=json.loads((CORE/'resources/native-draw-profiles.json').read_text('utf8'))
def card(i,kind='BigTime',score=90,family=5):
 return {'gameplayer_id':{'id':(family<<44)+i,'serial':i+100},'overall':score,
  draw.SCORE:score,draw.META:{'card_type':kind,'pickup':i==1,'presentation_version':3,'lighting_version':1,'lighting_effect':'SPOTLIGHT_WIN'}}

class DrawV22Tests(unittest.TestCase):
 def test_single_exactly_uses_218_selector_and_fixed_lighting(self):
  for kind in('Epic','BigTime','ShowTime','Legendary','Standard'):
   batch=[card(1,kind)]
   self.assertEqual(draw.response_fields(batch,profiles=PROFILES),draw_response_fields(batch,PROFILES))
   self.assertEqual(draw.response_fields(batch,profiles=PROFILES)['special_gacha_effect_player_id'],{'id':0,'serial':0})
  self.assertIn('SPOTLIGHT_BIGWIN',draw.response_fields([card(1)],profiles=PROFILES)['effect_list'])

 def test_v22_multi_counts_scenes_with_218_lighting_and_auto_actor(self):
  expected={0:[],1:['PROMOTION_DRIBBLE','REVIVAL_SOLO'],2:['GORGEOUS_STADIUM_ROOF','ENTRANCE_TWO'],3:['GORGEOUS_STADIUM_ROOF','ENTRANCE_TWO','REVIVAL_SOLO'],4:['GORGEOUS_STADIUM_ROOF','ENTRANCE_TWO','REVIVAL_TWO']}
  for size in(10,20,30):
   for count in range(11):
    batch=[card(i,'Epic'if i<count else'Standard',family=5 if i<count else 0)for i in range(size)]
    out=draw.response_fields(batch,profiles=PROFILES)
    self.assertEqual(out['effect_list'],['OPENING_EPIC','WIN_SCREEN','SPOTLIGHT_WIN','RED_CARPET']+expected[min(count,4)]if count else[],(size,count))
    self.assertEqual(out['special_gacha_effect_player_id'],{'id':0,'serial':0})
  batch=[card(i,'Standard',family=0)for i in range(30)];batch[-1]=card(91)
  self.assertEqual(draw.response_fields(batch)['effect_list'],[])

 def test_first_recognized_series_wins_instead_of_v22_priority(self):
  batch=[card(1,'Epic',80),card(2,'BigTime',128),*[card(i,'Standard',family=0)for i in range(3,11)]]
  out=draw.response_fields(batch,profiles=PROFILES)
  self.assertIn('OPENING_EPIC',out['effect_list']);self.assertIn('SPOTLIGHT_WIN',out['effect_list'])
  self.assertNotIn('OPENING_BIGTIME',out['effect_list']);self.assertNotIn('SPOTLIGHT_BIGWIN',out['effect_list'])

 def test_freeze_keeps_every_identity_and_input_order_without_preview_or_random_lights(self):
  original=[card(i,score=80+i%4)for i in range(20)];before=copy.deepcopy(original)
  frozen=draw.freeze(original,lambda p:(_ for _ in()).throw(AssertionError('No preview calculation')),'SPOTLIGHT_BIGWIN')
  self.assertEqual(original,before)
  self.assertEqual([p['gameplayer_id']for p in frozen],[p['gameplayer_id']for p in original])
  self.assertTrue(all(p[draw.META]['presentation_version']==4 and'lighting_effect'not in p[draw.META]and draw.SCORE not in p for p in frozen))

 def test_aliases_restore_source_freezer_sort_and_frozen_receipts_are_immutable(self):
  calls=[]
  def original(conn,aid,players,pool=None):
   calls.append(aid);return [dict(p,**{draw.META:{'card_type':'Epic','lighting_effect':'SPOTLIGHT_BIGWIN','lighting_version':1}})for p in reversed(players)]
  def response(players):return {'base':True}
  module=types.ModuleType('draw_presentation');module.freeze_gacha=original;module.response_fields=response
  alias=types.ModuleType('draw_test_alias');alias.freeze=original;alias.fields=response
  with patch.dict(sys.modules,draw_presentation=module,draw_test_alias=alias):
   draw.install(lambda:{'draw_profiles':PROFILES})
   self.assertIs(alias.freeze,module.freeze_gacha);self.assertIs(alias.fields,module.response_fields)
   players=[{'gameplayer_id':{'id':(5<<44)+i,'serial':99+i}}for i in range(10)]
   first=alias.freeze(None,1,players)
   self.assertEqual([p['gameplayer_id']for p in first],[p['gameplayer_id']for p in players])
   self.assertIs(alias.freeze(None,1,first),first);self.assertEqual(calls,[1])
   self.assertTrue(alias.fields([{**card(1),draw.META:{'test_profile':'effect_test'}}])['base'])

 def test_old_random_light_metadata_does_not_affect_hybrid_lighting(self):
  batch=[card(i)for i in range(10)];batch[1][draw.META]['lighting_effect']='SPOTLIGHT_BIGWIN'
  self.assertIn('SPOTLIGHT_BIGWIN',draw.response_fields(batch,profiles=PROFILES)['effect_list'])

 def test_multidraw_revival_is_retained_and_single_reverts_to_218_safety_filter(self):
  doc={'draw_presentation_revision':draw.REVISION,'players':[{'identity':{'previous_card_ids':[42]}}]}
  for count in(1,10,20,30):
   response={'effect_list':['OPENING_BIGTIME','REVIVAL_SOLO'],'gameplayer_list':[{'gameplayer':{'gameplayer_id':{'id':42}}}for _ in range(count)]}
   sanitize_draw_effects(response,doc)
   self.assertEqual('REVIVAL_SOLO'in response['effect_list'],count!=1)

 def test_v22_audio_patch_guards_and_repeated_export(self):
  import base64,hashlib
  raw=b'012345';changed=b'01ab45';sha=lambda b:hashlib.sha256(b).hexdigest()
  p={'bytes':6,'before_sha256':sha(raw),'after_sha256':sha(changed),'edits':[[2,base64.b64encode(b'ab').decode()]]}
  self.assertEqual(apply(raw,p),(changed,'updated'));self.assertEqual(apply(changed,p),(changed,'reused'))
  with self.assertRaisesRegex(ValueError,'未知内容'):apply(b'abcdef',p)

 def test_pack_draw_count_persists_and_compiles_to_free_native_price(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);db=sqlite3.connect(root/'library.sqlite3');db.execute('create table players(id text,card_type text,payload text)')
   params=[0]*147;params[47]=180;db.execute('insert into players values(?,?,?)',('1','Epic',json.dumps({'parameters':params})));db.commit();db.close()
   (root/'native-pack-template.json').write_bytes((CORE/'resources/native-pack-template.json').read_bytes())
   pack={'uuid':str(uuid.uuid4()),'name':'Cup','members':[{'kind':'original','id':'1','weight':1}]}
   self.assertEqual(packs.normalize(pack)['draw_count'],10)
   for n in(10,20,30):
    pack['draw_count']=n;result=packs.compile_packs([pack],[],root,excluded={})[0]
    self.assertEqual([p['multiple_count']for p in result['price']['price_list']],[1,n]);self.assertTrue(all(p['price']['coin_price']==0 for p in result['price']['price_list']))
   pack['draw_count']=25
   with self.assertRaisesRegex(ValueError,'连抽'):packs.normalize(pack)

if __name__=='__main__':unittest.main()
