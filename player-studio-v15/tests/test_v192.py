from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import copy,hashlib,json,sqlite3,sys,tempfile,unittest,uuid,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from PIL import Image
from coach_portraits import normalize,pixels
from engine_compatibility import detect,game_version
from native_player import compile_player
from native_tables import player_record


class V192Tests(unittest.TestCase):
 def test_gateway_initialization_forwards_v16_arguments_and_keeps_legacy_call(self):
  from personal_runtime import install,MANIFEST
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);manifest=root/MANIFEST;manifest.parent.mkdir(parents=True)
   manifest.write_text(json.dumps({'revision':'test','resource_files':{}}))
   legends=SimpleNamespace(_SOURCE_CHECKS=[],_ACTIVE_CHECKS=[],_source_verified=set(),_active_fingerprint=None,activate=lambda *a:{'status':'waiting'})
   protected=SimpleNamespace(install_root=lambda r:None);calls=[];callback=object()
   def original(root,progress=None,*,mode=None):calls.append((root,progress,mode));return {'ready':True}
   namespace={'initialize':original}
   with patch.dict(sys.modules,{'_protected_runtime':protected,'legends_v10':legends}),patch('personal_runtime.install_pack_images'),patch('personal_runtime.patch_resource_checks'),patch('personal_runtime.install_display_previews'):
    install(namespace)
    self.assertEqual(namespace['initialize'](str(root),callback,mode='v16'),{'ready':True})
    self.assertIs(calls[-1][1],callback);self.assertEqual(calls[-1][2],'v16')
    namespace['initialize'](str(root));self.assertEqual(calls[-1],(root,None,None))

 def test_source_contract_version_is_not_the_game_version(self):
  release='20261023-models-card-art-source-contract-v1-default-live-v2026102401'
  self.assertEqual(game_version('73efootball-V16(1).apk',release,'V15'),'V16')
  self.assertEqual(game_version('renamed.apk',release,'V16'),'V16')
  self.assertEqual(game_version('renamed.apk','20261024-V17-fixed','V16'),'V17')

 def test_fourth_weak_foot_level_survives_project_compiler_and_native_record(self):
  with sqlite3.connect(app.RESOURCE/'library.sqlite3') as db:
   source=json.loads(db.execute('select payload from players where id="7511"').fetchone()[0])
  costs=json.loads((app.RESOURCE/'native-progression.json').read_text(encoding='utf8'))['costs']
  fields=json.loads((app.RESOURCE/'native-player-fields.json').read_text(encoding='utf8'))
  abilities=json.loads((app.RESOURCE/'native-ability-bits.json').read_text(encoding='utf8'));skills=json.loads((app.RESOURCE/'native-skill-bits.json').read_text(encoding='utf8'))
  p=app.default_project();p['identity']['name']='Test';p['traits']['weak_foot_usage']='极高'
  identity={'card_id':90000001,'person_id':90000001,'package_id':p['package_id'],'previous_card_ids':[]}
  for index,label in enumerate(('低','普通','高','极高')):
   p['traits']['weak_foot_usage']=label;p=app.normalize_project(p)
   definition=compile_player(p,app.CATALOG,costs,identity,source,18,103)
   self.assertEqual(definition['base_parameters'][45],index)
   row=player_record(bytes.fromhex(source['_studio_client_record']),p,definition,fields,abilities,skills)
   self.assertEqual((int.from_bytes(row,'little')>>478)&3,index)
  p['traits']['weak_foot_usage']='UNKNOWN'
  with self.assertRaises(ValueError):app.normalize_project(p)

 def test_portrait_cropping_and_project_sharing_preserve_coach_identity_and_bytes(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);store=app.Store(root/'one');image=root/'avatar.png'
   source=Image.new('RGBA',(240,120),'red');source.paste('blue',(120,0,240,120));source.save(image)
   asset=store.import_asset(image,'image');uid=str(uuid.uuid4())
   coach=store.coaches.save({'uuid':uid,'name':'Coach','portrait':{'asset_id':asset['id'],'x':100}})['coach']
   self.assertEqual(pixels(coach['portrait'],store).getpixel((64,64)),(0,0,255,255))
   project=app.default_project();project['identity']['name']='Player';project['custom_coaches']=[coach]
   exported=store.export_project(project);other=app.Store(root/'two');imported=other.import_project(exported['path'])
   self.assertEqual(imported['custom_coaches'][0],coach)
   self.assertEqual((other.root/'assets'/asset['id']).read_bytes(),image.read_bytes())
   self.assertEqual(pixels(imported['custom_coaches'][0]['portrait'],other).tobytes(),pixels(coach['portrait'],store).tobytes())
   for value in ({'asset_id':'../avatar.png'},{'asset_id':asset['id'],'zoom':float('nan')},{'asset_id':asset['id'],'x':101}):
    with self.assertRaises(ValueError):normalize(value)
   (store.root/'assets'/asset['id']).unlink()
   with self.assertRaisesRegex(ValueError,'缺失'):store.coaches.save(coach)

 def test_unknown_engine_hash_is_allowed_when_used_interfaces_match(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);engine=bytearray(1024);engine[:6]=b'\x7fELF\x02\x01';engine[18:20]=(183).to_bytes(2,'little');engine[100:132]=b'k'*32;engine[200:264]=b'a'*64
   (root/'native-resource-profile.json').write_text(json.dumps({'resource_key_offset':100,'resource_key_sha256':hashlib.sha256(b'k'*32).hexdigest(),'family':'V14','game_version':'V16'}))
   (root/'native-compatibility.json').write_text(json.dumps({'regions':[{'offset':200,'bytes':64,'sha256':hashlib.sha256(b'a'*64).hexdigest(),'name':'test interface'}]}))
   (root/'native-route-templates.json').write_text('{}')
   for name in ('position','acquisition','overall','thumbnail'):(root/('native-'+name+'-hook.json')).write_text('{}')
   apk=root/'game-V17.apk'
   def write():
    with zipfile.ZipFile(apk,'w') as z:z.writestr('lib/arm64-v8a/libUE4.so',engine)
   with patch('native_binding_source.read_installer',return_value=({},None)),patch('native_binding_source.verify_installer',return_value={}):
    write();first=detect(apk,root,'new release');self.assertEqual(first['game_version'],'V17')
    engine[900]=1;write();self.assertEqual(detect(apk,root,'new release')['compatibility']['mode'],'interfaces')
    engine[200]=0;write()
    with self.assertRaisesRegex(ValueError,'关键接口'):detect(apk,root,'new release')

if __name__=='__main__':unittest.main()
