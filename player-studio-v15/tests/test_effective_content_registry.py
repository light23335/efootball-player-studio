from pathlib import Path
import copy,json,sys,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from art_registry import verify_content
from native_binding_source import read_installer,verify_installer
from personal_binding import fingerprint

ROUTES=[{'cardId':89136418985317,'suiteDonorId':89139630444046,'portraitKey':'9500022','modelFaceKey':'','modelNativeId':56328,'club_id':50,'position':11,'maximum_overall':90,'presentation_rarity':10},
        {'cardId':89136418985334,'suiteDonorId':88037702764935,'portraitKey':'9500033','modelFaceKey':'','modelNativeId':56336,'club_id':12,'position':2,'maximum_overall':91,'presentation_rarity':10}]

class EffectiveContentRegistryTests(unittest.TestCase):
 def test_missing_or_changed_same_count_routes_are_rejected_with_player_id(self):
  doc={'content_catalogue':{'routes':ROUTES},'native_binding':{'source':{'registry':{'content_routes':[]}}}}
  with self.assertRaisesRegex(ValueError,'89136418985317'):verify_content(doc)
  doc['native_binding']['source']['registry']['content_routes']=copy.deepcopy(ROUTES)
  doc['native_binding']['source']['registry']['content_routes'][0]['portraitKey']='wrong'
  with self.assertRaisesRegex(ValueError,'应注册 2 条，实际 2 条'):verify_content(doc)
 def test_equal_routes_normalize_order_and_exact_duplicate_without_mutation(self):
  doc={'content_catalogue':{'routes':ROUTES},'native_binding':{'source':{'registry':{'content_routes':[ROUTES[1],ROUTES[0],ROUTES[1]]}}}}
  before=copy.deepcopy(doc);result=verify_content(doc)
  self.assertEqual(result['registered_routes'],2);self.assertEqual(doc,before)
  self.assertEqual(result['card_ids'],sorted(r['cardId']for r in ROUTES))
 def test_native_only_legacy_document_needs_no_new_registry(self):
  self.assertEqual(verify_content({})['registered_routes'],0)
 def test_supplied_effective_routes_on_unsupported_interface_cannot_be_silently_ignored(self):
  code=compile("def _start_legend_portrait_binding(root):\n PAYLOAD={'blob_hex':'00','hooks':[],'offsets':{},'back_fixup':0}\n raise RuntimeError('must not run')",'fixture.py','exec')
  with patch('native_binding_source.module_reader',return_value=lambda name:code):
   with self.assertRaisesRegex(ValueError,'不支持'):read_installer('unused.apk',content_catalogue={'routes':ROUTES})
 def test_real_clean_v17_uses_supplied_content_and_passes_actual_runtime_preflight(self):
  root=Path(__file__).resolve().parents[2];apk=root.parent/'73efootball安装包及资源/73efootball-V17.apk'
  if not apk.is_file():self.skipTest('requires original V17 APK')
  baseline,_=read_installer(apk)
  payload,installer=read_installer(apk,content_catalogue={'format':'studio-content-catalogue-v1','routes':ROUTES})
  self.assertNotEqual(fingerprint(payload),fingerprint(baseline))
  doc={'content_catalogue':{'routes':ROUTES},'native_binding':{'source':installer.proof}}
  self.assertTrue(verify_content(doc)['verified'])
  resource=root/'player-studio-v15/resources';profile=json.loads((resource/'native-route-templates.json').read_text('utf8'));profile.update(external_routes=True,club_emblems=True)
  for name in ('position','acquisition','overall','thumbnail'):profile[name+'_hook']=json.loads((resource/('native-'+name+'-hook.json')).read_text('utf8'))
  binding={'routes':[{'cardId':990001,'suiteDonorId':990001,'portraitKey':'8900001','modelFaceKey':'8900001','club_id':108,'position':1,'maximum_overall':99,'presentation_rarity':10}],'profile':profile,'source':installer.proof,'original_fingerprint':installer.proof['raw_fingerprint'],'prepared_fingerprint':fingerprint(payload)}
  result=verify_installer(installer,binding)
  self.assertTrue(result['shared_registry_pipeline']);self.assertTrue(result['allocator_contract_verified'])

 def test_compiled_arm64_resolves_both_missing_portraits_and_native_models(self):
  try:
   from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
   from unicorn import arm64_const as r
  except ImportError:self.skipTest('requires optional ARM64 emulator')
  root=Path(__file__).resolve().parents[2];apk=root.parent/'73efootball安装包及资源/73efootball-V17.apk'
  if not apk.is_file():self.skipTest('requires original V17 APK')
  payload,installer=read_installer(apk,content_catalogue={'routes':ROUTES})
  profile=json.loads((root/'player-studio-v15/resources/native-route-templates.json').read_text('utf8'))
  from personal_binding import compose,relocate_code
  profile.update(external_routes=True,club_emblems=True)
  for name in ('position','acquisition','overall','thumbnail'):profile[name+'_hook']=json.loads((root/'player-studio-v15/resources'/('native-'+name+'-hook.json')).read_text('utf8'))
  personal={'cardId':990001,'suiteDonorId':990001,'portraitKey':'8900001','modelFaceKey':'8900001','club_id':108,'position':1,'maximum_overall':99,'presentation_rarity':10}
  for wrapped in (False,True):
   out=compose(payload,[personal],profile)if wrapped else payload
   start=0x100000;extension_address=0x300000;table_address=0x500000;object_address=0x900000
   raw=bytearray.fromhex(out['blob_hex']);extension=b''
   if wrapped:
    import struct
    struct.pack_into('<Q',raw,out['back_fixup'],0x7000000000+out['hooks'][0]['address']+4)
    raw,extension=relocate_code(out,bytes(raw),start,extension_address,table_address+144)
   for route in ROUTES:
    for kind in ('portrait','face'):
     with self.subTest(player=route['cardId'],kind=kind,personal_dispatch=wrapped):
      vm=Uc(UC_ARCH_ARM64,UC_MODE_ARM);vm.mem_map(start,0x10000);vm.mem_write(start,bytes(raw));vm.mem_map(object_address,0x10000)
      if wrapped:
       vm.mem_map(extension_address,0x10000);vm.mem_write(extension_address,extension);vm.mem_map(table_address,0x10000);vm.mem_write(table_address,bytes(144)+bytes.fromhex(out['route_table_hex']))
      vm.reg_write(r.UC_ARM64_REG_SP,object_address+0x8000);vm.reg_write(r.UC_ARM64_REG_X19,object_address);vm.reg_write(r.UC_ARM64_REG_X23,route['cardId']);vm.reg_write(r.UC_ARM64_REG_X1,route['cardId'])
      address=profile['sites'][kind];hook=next(h for h in out['hooks']if h['address']==address)
      original_offset=next(h['offset']for h in installer.raw_payload['hooks']if h['address']==address)
      delegate=start+original_offset if not wrapped or original_offset<out['root_prefix_bytes']else extension_address+original_offset-out['root_prefix_bytes']
      seen=[]
      def stop(machine,pc,size,unused):
       if pc==delegate:seen.append(machine.reg_read(r.UC_ARM64_REG_X1));machine.emu_stop()
      vm.hook_add(UC_HOOK_CODE,stop);vm.emu_start(start+hook['offset'],start+len(raw),count=2000)
      self.assertTrue(seen,'did not reach original fallback');self.assertEqual(vm.reg_read(r.UC_ARM64_REG_SP),object_address+0x8000)
      if kind=='face':self.assertEqual(seen,[route['modelNativeId']])
      else:
       def text(offset):
        value=bytes(vm.mem_read(object_address+offset,24));return value[1:1+(value[0]>>1)].decode('ascii')
       self.assertEqual(text(0x158),route['portraitKey']+'_');self.assertEqual(text(0x98),route['portraitKey']+'f')

if __name__=='__main__':unittest.main()
