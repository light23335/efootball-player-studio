"""Independent AI style: project -> disk -> compact -> match/UI transport."""
import copy,json,sqlite3,struct,sys,tempfile,unittest,zipfile
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(SOURCE),str(SOURCE/'maintenance')]
import app
from ai_playing_styles import FIELDS,OPTIONS,CUSTOM_SOURCE_BIT,from_record,project_value
from native_player import compile_player
from native_tables import player_record
from native_skill_effects import required,text_groups
import test_skill_effects_v2 as nativefixtures
APK=nativefixtures.APK


class LoneWolfDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with sqlite3.connect(app.RESOURCE/'library.sqlite3')as db:
            cls.source=json.loads(db.execute('select payload from players where id="7511"').fetchone()[0])
        cls.costs=json.loads((app.RESOURCE/'native-progression.json').read_text('utf8'))['costs']
        cls.fields=json.loads((app.RESOURCE/'native-player-fields.json').read_text('utf8'))
        cls.abilities=json.loads((app.RESOURCE/'native-ability-bits.json').read_text('utf8'))
        cls.skills=json.loads((app.RESOURCE/'native-skill-bits.json').read_text('utf8'))

    def compile(self,styles):
        p=app.default_project();p['identity']['name']='Lone Wolf Test';p['ai_playing_styles']=styles
        identity={'card_id':90000001,'person_id':90000001,'package_id':p['package_id'],'previous_card_ids':[]}
        source=bytes.fromhex(self.source['_studio_client_record'])
        definition=compile_player(p,app.CATALOG,self.costs,identity,self.source,18,103,source)
        row=player_record(source,p,definition,self.fields,self.abilities,self.skills)
        return p,definition,row

    def test_independent_style_is_selectable_without_repurposing_native_fields(self):
        self.assertEqual(len(FIELDS),7);self.assertEqual(len(OPTIONS),8)
        p,d,row=self.compile(['lone_wolf'])
        self.assertEqual(from_record(row),['lone_wolf'])
        self.assertEqual(d['ai_playing_styles'],['lone_wolf'])
        self.assertEqual(d['owned']['ai_playing_styles'],['lone_wolf'])
        self.assertEqual(len(d['base_parameters']),147)
        self.assertEqual(d['base_parameters'][63:70],[0]*7)
        self.assertTrue(required([d],app.CATALOG))

    def test_style_sets_one_disk_bit_and_clearing_preserves_native_choices(self):
        _,before,a=self.compile(['incisive_run','long_ranger'])
        _,after,b=self.compile(['incisive_run','long_ranger','lone_wolf'])
        self.assertEqual(before['base_parameters'],after['base_parameters'])
        self.assertEqual(int.from_bytes(a,'little')^int.from_bytes(b,'little'),1<<CUSTOM_SOURCE_BIT)
        self.assertEqual(from_record(b),['incisive_run','long_ranger','lone_wolf'])

    def test_project_sharing_preserves_custom_style_and_explicit_clear(self):
        with tempfile.TemporaryDirectory()as folder:
            a=app.Store(Path(folder)/'a');b=app.Store(Path(folder)/'b')
            p,_,_=self.compile(['incisive_run','lone_wolf'])
            imported=b.import_project(a.export_project(p)['path'])
            self.assertEqual(imported['ai_playing_styles'],p['ai_playing_styles'])
            imported['ai_playing_styles']=[]
            self.assertEqual(project_value(imported),[])

    def test_name_resolves_in_chinese_and_english_without_becoming_a_skill(self):
        for language,expected in [('zha','独狼'),('eng','Lone Wolf')]:
            groups={g['id']:g for g in text_groups(locale=language)}
            self.assertEqual(groups[352]['items'][60010],expected)
        self.assertNotIn('151',app.CATALOG['PARAMETER_BY_SKILL'])

    def test_old_owned_only_definition_requires_the_display_protocol(self):
        from ai_playing_styles import definition_value
        from native_ai_style_ui import preflight
        legacy={'owned':{'ai_playing_styles':['lone_wolf'],'additional_skill_id':[]},
                'base_parameters':[0]*147}
        self.assertEqual(definition_value(legacy),['lone_wolf'])
        self.assertTrue(required([legacy],app.CATALOG))
        with self.assertRaisesRegex(ValueError,'缺少入口'):preflight([legacy],[])
        legacy['ai_playing_styles']=[]
        self.assertFalse(required([legacy],app.CATALOG))
        self.assertEqual(preflight([legacy],[])['lone_wolf_players'],0)

    def test_lone_wolf_text_is_not_gated_by_custom_skills(self):
        from unittest.mock import patch
        with patch('custom_skills.enabled',return_value=False):
            groups={g['id']:g for g in text_groups(locale='zha')}
        self.assertEqual(groups[352]['items'][60010],'独狼')

    def test_card_transport_uses_exact_ids_and_explicit_off_for_previous_aliases(self):
        from native_skill_effects import lone_wolf_bindings
        rows=[{'identity':{'card_id':90000000001,'previous_card_ids':[90000000000]},
               'owned':{'ai_playing_styles':['lone_wolf']}},
              {'identity':{'card_id':90000000002},'ai_playing_styles':[],
               'owned':{'ai_playing_styles':['lone_wolf']}}]
        self.assertEqual(lone_wolf_bindings(rows),[(90000000000,128),(90000000001,128),(90000000002,0)])
        conflict=copy.deepcopy(rows[1]);conflict['identity']['previous_card_ids']=[90000000000]
        with self.assertRaisesRegex(ValueError,'冲突'):lone_wolf_bindings(rows+[conflict])


@unittest.skipUnless(APK.is_file(),'requires original V17 APK')
class LoneWolfNativeTransportTests(unittest.TestCase):
    machine=nativefixtures.NativeSkillV2Tests.machine
    install_all=nativefixtures.NativeSkillV2Tests.install_all
    relocate_state=nativefixtures.NativeSkillV2Tests.relocate_state
    execute=nativefixtures.NativeSkillV2Tests.execute
    get_parameter=nativefixtures.NativeSkillV2Tests.get_parameter
    set_parameter=nativefixtures.NativeSkillV2Tests.set_parameter

    @classmethod
    def setUpClass(cls):nativefixtures.NativeSkillV2Tests.setUpClass.__func__(cls)

    def decode(self,vm,value):
        vm.mem_write(0x41000000,value.to_bytes(400,'little'))
        vm.mem_write(0x41001000,bytes([0xa5])*512)
        for n,v in enumerate([0x41001000,0x41000000,0]):vm.reg_write(getattr(self.r,'UC_ARM64_REG_X'+str(n)),v)
        self.execute(vm,0x82aa124)

    def test_all_skill_and_style_combinations_survive_real_source_decoder(self):
        vm=self.machine({});self.install_all(vm)
        for mask in range(16):
            for wolf in [0,1]:
                self.decode(vm,(mask<<683)|(wolf<<687))
                self.assertEqual([self.get_parameter(vm,0x41001000,n)for n in range(147,152)],
                                 [(mask>>n)&1 for n in range(4)]+[wolf])
                self.assertEqual(bytes(vm.mem_read(0x41001038,32)),bytes([0xa5])*32)

    def test_owned_override_and_setters_keep_the_independent_style(self):
        vm=self.machine({});self.install_all(vm)
        self.decode(vm,(15<<683)|(1<<687))
        self.set_parameter(vm,0x41001000,148,0)
        self.assertEqual(self.get_parameter(vm,0x41001000,151),1)
        self.set_parameter(vm,0x41001000,151,0)
        self.assertEqual([self.get_parameter(vm,0x41001000,n)for n in range(147,152)],[1,0,1,1,0])
        self.set_parameter(vm,0x41001000,151,1)
        vm.mem_write(0x41000080,bytes(56))
        vm.reg_write(self.r.UC_ARM64_REG_X19,0x41001000)
        vm.reg_write(self.r.UC_ARM64_REG_X20,0x41000000)
        self.execute(vm,0x7a87ff8,0x7a88030)
        self.assertEqual(self.get_parameter(vm,0x41001000,151),1)
        self.assertEqual(vm.reg_read(self.r.UC_ARM64_REG_W22),147)

    def test_match_flag_and_ui_index_preserve_all_seven_native_styles(self):
        vm=self.machine({});self.install_all(vm)
        for wolf in [0,1]:
            self.decode(vm,wolf<<687)
            vm.mem_write(0x410020d4,struct.pack('<I',0x7f))
            vm.reg_write(self.r.UC_ARM64_REG_X19,0x41002000)
            vm.reg_write(self.r.UC_ARM64_REG_X20,0x41001000)
            self.execute(vm,0x6a74f08,0x6a74f0c)
            self.assertEqual(struct.unpack('<I',vm.mem_read(0x410020d4,4))[0],0x7f|(wolf<<7))
        for index in range(8):
            vm.reg_write(self.r.UC_ARM64_REG_W0,index);self.execute(vm,0x82a2208)
            parameter=vm.reg_read(self.r.UC_ARM64_REG_W0)
            self.assertIn(parameter,range(63,70)if index<7 else [151])
        vm.mem_write(0x41003000,struct.pack('<I',151))
        vm.reg_write(self.r.UC_ARM64_REG_X0,0x41003000);self.execute(vm,0x82bb60c)
        self.assertEqual(vm.reg_read(self.r.UC_ARM64_REG_W0),(352<<16)|60010)

    def card_bound_machine(self,definitions):
        from native_skill_effects import bind_lone_wolf_cards
        self.candidate=copy.deepcopy(type(self).candidate)
        self.candidate['bundles']=[bind_lone_wolf_cards(b,definitions)for b in self.candidate['bundles']]
        key=0x123456789ab
        vm=self.machine({0x6774740:lambda m:m.reg_write(self.r.UC_ARM64_REG_X0,key)})
        self.install_all(vm)
        return vm,key

    def compile_match_styles(self,vm,key,cid,serial=0,tag=0):
        source,target=0x41001000,0x41002000
        vm.mem_write(source,bytes(512));vm.mem_write(target,bytes(512))
        for index in range(63,70):self.set_parameter(vm,source,index,1)
        vm.mem_write(source+0x34,struct.pack('<I',tag))
        vm.mem_write(source+0x38,struct.pack('<I',serial&0xffffffff))
        vm.mem_write(source+0x40,struct.pack('<Q',cid^key))
        vm.mem_write(target+0xd4,struct.pack('<I',0x01000080))
        vm.reg_write(self.r.UC_ARM64_REG_X19,target)
        vm.reg_write(self.r.UC_ARM64_REG_X20,source)
        # Execute every original native style read/set, then the actual linked
        # transport hook and the native64-bit encrypted identity getter.
        self.execute(vm,0x6a74d9c,0x6a74f0c)
        self.assertEqual(vm.reg_read(self.r.UC_ARM64_REG_X0),vm.reg_read(self.r.UC_ARM64_REG_SP)+8)
        return struct.unpack('<I',vm.mem_read(target+0xd4,4))[0]

    def test_native_match_reconstruction_carries_wolf_without_compact_padding(self):
        cid=90159685099299
        vm,key=self.card_bound_machine([{'identity':{'card_id':cid},'ai_playing_styles':['lone_wolf']}])
        for serial in (0,123,0xfffffffd):
            self.assertEqual(self.compile_match_styles(vm,key,cid,serial),0x010000ff)

    def test_native_match_transport_does_not_mark_unregistered_cards_or_same_low_word(self):
        cid=90159685099299
        vm,key=self.card_bound_machine([{'identity':{'card_id':cid},'ai_playing_styles':['lone_wolf']}])
        for other in (0,cid+1,cid+(1<<32)):
            self.assertEqual(self.compile_match_styles(vm,key,other),0x0100007f)

    def test_native_match_off_edit_clears_stale_flag_and_old_card_alias(self):
        cid,alias=90159685099299,90159685099298
        definition={'identity':{'card_id':cid,'previous_card_ids':[alias]},'ai_playing_styles':[]}
        vm,key=self.card_bound_machine([definition])
        from custom_skills import COMPACT_TAG
        for value in (cid,alias):
            self.assertEqual(self.compile_match_styles(vm,key,value,tag=COMPACT_TAG|0x80),0x0100007f)

    def test_native_match_on_edit_carries_old_card_alias(self):
        cid,alias=90159685099299,90159685099298
        definition={'identity':{'card_id':cid,'previous_card_ids':[alias]},'ai_playing_styles':['lone_wolf']}
        vm,key=self.card_bound_machine([definition])
        self.assertEqual(self.compile_match_styles(vm,key,alias),0x010000ff)

    def test_strong_foot_byte_is_produced_by_the_original_native_compiler(self):
        for foot,stop in [(0,0x6a74604),(1,0x6a74628)]:
            vm=self.machine({});self.install_all(vm);self.decode(vm,0)
            self.set_parameter(vm,0x41001000,43,foot)
            sp=vm.reg_read(self.r.UC_ARM64_REG_SP)
            vm.mem_write(sp+8,struct.pack('<Q',0x41002000))
            vm.reg_write(self.r.UC_ARM64_REG_X20,0x41001000)
            self.execute(vm,0x6a745e0,stop)
            self.assertEqual(vm.mem_read(0x41002035,1),bytes([foot]))

    def test_new_source_bit_and_text_key_are_empty_in_actual_original_apk(self):
        from apk_database import read_tables,PREFIX
        from native_tables import PLAYER
        from native_cpk import Cpk
        from native_strings import read,unwrap
        with zipfile.ZipFile(APK)as apk:
            rows=read_tables(apk)[PLAYER]
            cpk=Cpk(apk.read(PREFIX+'livedata/dt870_mobile_and.cpk'))
        self.assertGreater(len(rows),46000)
        self.assertFalse(any((int.from_bytes(row,'little')>>687)&1 for row in rows.values()))
        for name in cpk.files:
            if not name.endswith(('/string/all.str','/string/all_diff.str')):continue
            for group in read(unwrap(cpk.read(name))):
                if group['id']in(352,353):self.assertNotIn(60010,group['items'])


if __name__=='__main__':unittest.main()
