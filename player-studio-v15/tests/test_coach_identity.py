from pathlib import Path
import copy,io,json,sqlite3,struct,sys,tempfile,unittest,uuid,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coach_identity import normalize,country,owned_payloads,repair_catalogue,REVISION
from native_coaches import compile_coaches,bitfield,COACH,BOOSTER,TACTICS
from native_cpk import wrap,unwrap
RESOURCE=Path(__file__).resolve().parents[1]/'resources'
APK=Path('C:/Users/1/Downloads/73efootball-V17.apk')
HEADER=struct.pack('<BBB5sII',255,0x21,0x83,b'WESYS',0,0)

class Archive:
 def __init__(self,rows):self.files={COACH:wrap(b''.join(rows),HEADER),BOOSTER:wrap(bytes(4),HEADER)}
 def read(self,name):return self.files[name]

def native_row(cid,nation,marker):
 row=bytearray(176);struct.pack_into('<QQ',row,0,cid,marker)
 return bitfield(int.from_bytes(row,'little'),170,9,nation).to_bytes(176,'little')

class CoachIdentityTests(unittest.TestCase):
 def test_legacy_owned_club_is_retained_but_explicit_zero_overrides_it(self):
  self.assertEqual(normalize({'raw_payload':{'initial_base_team_id':103}}),{'nation_id':0,'team_id':103,'native_source_id':None})
  self.assertEqual(normalize({'team_id':0,'raw_payload':{'initial_base_team_id':103}})['team_id'],0)
  for bad in ({'nation_id':512},{'nation_id':True},{'team_id':-1},{'team_id':131072},{'native_source_id':'custom:invalid'}):
   with self.subTest(bad=bad),self.assertRaises(ValueError):normalize(bad)

 def test_compile_uses_selected_source_and_writes_country_and_owned_club(self):
  originals=[native_row(8,146,123),native_row(9,210,987)]
  catalogue=[{'id':str(cid),'age':45,'raw_payload':{'initial_base_team_id':4183,'marker':cid}} for cid in (8,9)]
  coach={'uuid':str(uuid.uuid4()),'name':'My Coach','effects':{},'tactics':dict.fromkeys(TACTICS,88),'nation_id':208,'team_id':103,'native_source_id':'9'}
  files,definitions=compile_coaches(Archive(originals),[coach],catalogue,{})
  raw=unwrap(files[COACH]);rows={int.from_bytes(raw[i:i+8],'little'):raw[i:i+176] for i in range(0,len(raw),176)};definition=definitions[0];changed=rows[definition['id']]
  self.assertEqual([rows[8],rows[9]],originals);self.assertEqual(changed[8:16],originals[1][8:16]);self.assertEqual(country(changed),208)
  self.assertEqual(definition['payload']['initial_base_team_id'],103);self.assertEqual(definition['payload']['marker'],9)
  self.assertEqual((definition['nation_id'],definition['team_id'],definition['native_source_id']),(208,103,'9'))
  coach.update(nation_id=0,team_id=0,native_source_id=None)
  _,empty=compile_coaches(Archive(originals),[coach],catalogue,{})
  self.assertEqual(empty[0]['payload']['initial_base_team_id'],0)

 def test_current_owned_and_personal_payloads_override_other_coach_templates(self):
  db=sqlite3.connect(':memory:');db.execute('create table coaches(coach_id integer,json text)');db.execute('insert into coaches values(8,?)',(json.dumps({'initial_base_team_id':101}),));raw=db.serialize();db.close();buffer=io.BytesIO()
  from personal_source import PATH
  with zipfile.ZipFile(buffer,'w') as z:
   z.writestr('assets/gateway-release/outputs/efootball/local-club.sqlite3',raw)
   z.writestr(PATH,json.dumps({'coaches':[{'id':9,'payload':{'initial_base_team_id':103}}]}))
  with zipfile.ZipFile(buffer) as z:payloads=owned_payloads(z)
  self.assertEqual(payloads['8']['initial_base_team_id'],101);self.assertEqual(payloads['9']['initial_base_team_id'],103);self.assertNotIn('10',payloads)

 @unittest.skipUnless(APK.is_file(),'requires original V17 APK')
 def test_import_and_old_catalogue_repair_read_the_actual_country_and_club(self):
  from apk_database import read_coaches
  import shutil
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp)
   for name in ('coaches.json','native-coach-links.json'):shutil.copy2(RESOURCE/name,folder/name)
   with zipfile.ZipFile(APK) as z:self.assertEqual(read_coaches(z,folder),1661)
   data=json.loads((folder/'coaches.json').read_text(encoding='utf8'));rows={c['id']:c for c in data['coaches']}
   self.assertEqual(rows['8']['nation_id'],146);self.assertEqual(rows['8']['team_id'],0);self.assertEqual(rows['8']['team_source'],'unavailable')
   klopp=rows['17605071047055'];self.assertEqual(klopp['nation_id'],210);self.assertEqual(klopp['team_id'],klopp['raw_payload']['initial_base_team_id']);self.assertTrue(klopp['raw_payload_verified'])
   data.pop('coach_identity_revision')
   for c in data['coaches']:
    for key in ('nation_id','team_id','native_source_id','identity_available','team_source'):c.pop(key,None)
   (folder/'import-report.json').write_text(json.dumps({'apk':str(APK)}),encoding='utf8');before=(folder/'coaches.json').read_bytes();fixed=repair_catalogue(data,folder)
   self.assertEqual(fixed['coach_identity_revision'],REVISION);self.assertEqual(fixed['coaches'][0]['nation_id'],146);self.assertEqual((folder/'coaches.json').read_bytes(),before)

 @unittest.skipUnless(APK.is_file(),'requires original V17 APK')
 def test_real_country_getter_returns_compiled_native_field(self):
  try:
   from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
   from unicorn import arm64_const as r
  except ImportError:self.skipTest('requires optional ARM64 emulator')
  address=0x8250588
  with zipfile.ZipFile(APK) as z,z.open('lib/arm64-v8a/libUE4.so') as f:f.seek(address-16384);code=f.read(40)
  for selected in (0,146,208,210,511):
   with self.subTest(country=selected):
    vm=Uc(UC_ARCH_ARM64,UC_MODE_ARM);vm.mem_map(address&~4095,4096);vm.mem_write(address,code);vm.mem_map(0x100000,4096);vm.mem_write(0x100000,native_row(8,selected,987))
    vm.reg_write(r.UC_ARM64_REG_X0,0x100000);vm.reg_write(r.UC_ARM64_REG_X1,0);vm.reg_write(r.UC_ARM64_REG_X30,0x200000);vm.emu_start(address,0x200000,count=100)
    self.assertEqual(vm.reg_read(r.UC_ARM64_REG_X0),selected)

if __name__=='__main__':unittest.main()
