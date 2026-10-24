from pathlib import Path
import copy,hashlib,json,random,struct,sys,unittest,uuid,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from custom_boosters import BOOSTER_BITS,issues,validate_projects
from native_tables import booster_table,BOOSTERS
from native_cpk import Cpk,unwrap
from native_strings import booster_rows
RESOURCE=Path(__file__).resolve().parents[1]/'resources'

def project(name='守门员',effects=None,conditional=False):
    p=app.default_project();p['identity']['name']=name;p['booster_ids']=[0,1000]
    p['custom_boosters']=[{'id':1000,'uuid':str(uuid.uuid4()),'label':'独立守门增能','effects':effects or {'16':2,'30':7,'31':13},'conditional':conditional}]
    return p


class BoosterValidationTests(unittest.TestCase):
    def test_gk_and_16_to_20_are_accepted(self):
        p=project(effects={'16':2,'30':7,'31':13,'29':19,'32':20,'14':16})
        self.assertEqual(issues(p),[]);validate_projects([p])
    def test_reports_all_selected_invalid_boosters_with_player_and_label(self):
        a=project('门将甲',{'16':-1});b=project('门将乙',{'30':21},True)
        with self.assertRaises(ValueError) as result:validate_projects([a,b],{'16':'守门意识','30':'解围'})
        message=str(result.exception)
        for text in ['门将甲','门将乙','独立守门增能','ID 1000','守门意识=-1','解围=21','条件触发']:self.assertIn(text,message)
    def test_legacy_settings_are_kept_and_unused_invalid_definitions_do_not_block_build(self):
        p=project(effects={'16':-2},conditional=True);p['booster_ids']=[0,0];before=copy.deepcopy(p)
        self.assertEqual(app.normalize_project(p)['custom_boosters'][0]['effects']['16'],-2)
        validate_projects([p]);self.assertEqual(before,p)
    def test_zero_keys_are_not_a_false_shared_uuid_conflict(self):
        p=project();q=copy.deepcopy(p);q['identity']['name']='另一门将';q['custom_boosters'][0]['effects']['14']=0
        validate_projects([p,q]);booster_rows([p,q],app.CATALOG['ABILITIES'])
        donor=(76<<112).to_bytes(40,'little');encoded=booster_table(donor,[p,q])
        self.assertEqual(len(encoded),80)
    def test_changed_shared_definition_names_both_players(self):
        p=project('甲');q=copy.deepcopy(p);q['identity']['name']='乙';q['custom_boosters'][0]['effects']['16']=5
        with self.assertRaisesRegex(ValueError,'同一永久增能'):validate_projects([p,q])
    def test_unknown_attributes_do_not_get_mislabeled_as_gk(self):
        p=project(effects={'999':3})
        self.assertIn('未知能力编号：999',issues(p)[0]);self.assertNotIn('守门员字段',issues(p)[0])
    def test_existing_native_id_conflict_identifies_booster(self):
        p=project();data=(76<<112).to_bytes(40,'little')+(1000<<112).to_bytes(40,'little')
        with self.assertRaisesRegex(ValueError,'守门员.*独立守门增能.*已有增能冲突'):booster_table(data,[p])


class NativeAccessorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
            from unicorn import arm64_const as r
        except ImportError:raise unittest.SkipTest('optional ARM64 emulator')
        root=Path(__file__).resolve().parents[2];apk=root/'球员工坊-V15/原始APK/73efootball-V15.apk'
        if not apk.exists():raise unittest.SkipTest('requires original V15 APK')
        cls.evidence=json.loads((RESOURCE/'native-booster-accessors.json').read_text(encoding='utf8'))
        cls.catalog=json.loads((RESOURCE/'catalog.json').read_text(encoding='utf8'));cls.r=r
        with zipfile.ZipFile(apk) as z:
            engine=z.read('lib/arm64-v8a/libUE4.so');cls.data=unwrap(Cpk(z.read('assets/gateway-release/custom-resources/legends-v10/dt870_mobile_and.cpk')).read(BOOSTERS))
        assert hashlib.sha256(engine).hexdigest()==cls.evidence['engine_sha256']
        cls.uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM);cls.uc.mem_map(0x82ae000,0x1000);cls.uc.mem_map(0x200000,0x1000);cls.uc.mem_map(0x300000,0x1000)
        for row in cls.evidence['rows']:
            raw=engine[row['file_offset']:row['file_offset']+40];assert raw.hex()==row['expected_hex'];cls.uc.mem_write(row['address'],raw)
    def read_native(self,row,mode=0):
        uc=self.uc;r=self.r;uc.mem_write(0x200000,row);result={}
        for field in self.evidence['rows']:
            uc.reg_write(r.UC_ARM64_REG_X0,0x200000);uc.reg_write(r.UC_ARM64_REG_X1,mode);uc.reg_write(r.UC_ARM64_REG_X30,0x300000)
            uc.emu_start(field['address'],0x300000,count=20);result[field['ability']]=uc.reg_read(r.UC_ARM64_REG_X0)
        return result
    def test_all_original_definitions_match_actual_native_readers(self):
        records={int.from_bytes(self.data[i+14:i+16],'little')&1023:self.data[i:i+40] for i in range(0,len(self.data),40)}
        for booster in self.catalog['boosters']:
            self.assertEqual(self.read_native(records[booster['id']]),{k:booster['effects'].get(k,0) for k in BOOSTER_BITS},booster['id'])
    def test_custom_independent_gk_and_all_26_ranges_survive_actual_native_readers(self):
        rng=random.Random(20261022);cases=[{'16':2,'30':7,'31':13,'29':19,'32':20},dict.fromkeys(BOOSTER_BITS,20),dict.fromkeys(BOOSTER_BITS,0)]
        cases.extend({k:rng.randrange(21) for k in BOOSTER_BITS} for _ in range(8))
        for effects in cases:
            p=project(effects=effects);before=bytes(self.data);encoded=booster_table(self.data,[p])
            self.assertTrue(encoded.startswith(before));row=next(encoded[i:i+40] for i in range(0,len(encoded),40) if int.from_bytes(encoded[i+14:i+16],'little')&1023==1000)
            self.assertEqual(self.read_native(row),{k:effects.get(k,0) for k in BOOSTER_BITS})
    def test_native_accessor_exposes_21_as_reserved_bound(self):
        self.assertEqual(set(self.read_native(bytes(40),mode=2).values()),{21})

if __name__=='__main__':unittest.main()
