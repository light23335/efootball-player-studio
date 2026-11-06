"""Run production rule transport and V17's actual 90/120-minute decisions.

This is an isolated Unicorn instruction test, not a running-game test. Only
world selectors, frame score inputs and unrelated ET substitution effects are
fixtures. Original MatchParam copy/setters, native adapter and both period
decision functions execute their real instructions. STUDIO_TEST_ADAPTER can
point at the adapter extracted from a final APK for the same tests.
"""
import copy,hashlib,itertools,json,os,struct,tempfile,types,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
from unicorn.arm64_const import *
import ai_match_runtime as runtime
import test_tournament_difficulty_native as native
from test_ai_match_manager import fixture
from tournament_runtime import Service

PARAMS=native.DATA+0x170000
CONTROLLER=native.DATA+0x100000
END90,END120,ENTER_ET,ENTER_PK,FINISH=0x6b1e400,0x6b1e534,4,8,10
SOURCE=Path(__file__).resolve().parents[1]


def rule(**kw):
    return dict(two_leg=False,first_leg=False,second_leg=False,prior_goals=[0,0],
                extra_time=True,penalties=True,away_goals=False,away_goals_extra_time=False,**kw)


class PeriodVM(native.VM):
    def __init__(self):
        super().__init__()
        self.regular=[0,0];self.extra_first=[0,0];self.extra_second=[0,0]
        self.stubs.update({0x6b09c98:lambda:native.ROOT,0x72c3eb0:lambda:PARAMS,
                           0x6991db8:self.goals,0x6b27a94:lambda:0,0x6b27b78:lambda:0,
                           0x698f7e0:lambda:native.ROOT})
        self.u64(native.ROOT+0x480,native.DATA+0x180000)
        self.u64(CONTROLLER+0x20418,native.ROOT)
        # Leave a5 (ET substitution policy) owned by the original game.
        self.uc.mem_write(PARAMS,bytes(0x160));self.uc.mem_write(PARAMS+0xa5,b'\1')

    def goals(self):
        side,kind=self.reg(1),self.reg(2)
        return (self.extra_first if kind==2 else self.extra_second if kind==3
                else [self.regular[i]+self.extra_first[i]+self.extra_second[i]for i in (0,1)])[side]

    def original_copy(self,extra=True,pk=True):
        """Execute all of 6a6479c, with frontend values supplied as inputs."""
        saved=dict(self.stubs)
        code=native.raw[0x6a6479c-16384:0x6a64b18-16384]
        # The copied frontend record's other fields are fixture zeros. Keep
        # every original display setter, including 121/122,128..135, real.
        setters=set(range(0x72ea648,0x72ea74c,4))
        for ins in Cs(CS_ARCH_ARM64,CS_MODE_ARM).disasm(code,0x6a6479c):
            if ins.mnemonic in ('bl','b')and ins.op_str.startswith('#'):
                target=int(ins.op_str[1:],16)
                if target not in setters and not 0x6a6479c<=target<0x6a64b18:
                    self.stubs[target]=lambda:0
        self.stubs[0x72ebb8c]=lambda:int(extra)
        self.stubs[0x72ebbd4]=lambda:int(pk)
        self.stubs[0x68fb46c]=lambda:native.DATA+0x1c0000
        self.stubs[0x68fb51c]=lambda:native.DATA+0x1c0000
        self.call(0x6a6479c,PARAMS,native.DATA+0x1c0000)
        self.stubs=saved

    def abi_call(self,address,*args):
        preserved=[UC_ARM64_REG_X19+i for i in range(10)]
        values=[0x12340000+i*16 for i in range(10)]
        for reg,value in zip(preserved,values):self.uc.reg_write(reg,value)
        sp=self.uc.reg_read(UC_ARM64_REG_SP)
        result=self.call(address,*args)
        assert [self.uc.reg_read(r)for r in preserved]==values
        assert self.uc.reg_read(UC_ARM64_REG_SP)==sp
        return result

    def observe(self):
        return self.abi_call(native.EXT+native.bundle['helper_entries']['studio_observe'],
                             native.SELF,native.EVENT,1)

    def decision(self,period):
        result=self.abi_call(END90 if period==3 else END120,CONTROLLER)
        # Execute the real half-end dispatcher tail as well, through its
        # native period setter; stop immediately before clock reset work.
        self.uc.reg_write(UC_ARM64_REG_X19,CONTROLLER)
        self.uc.reg_write(UC_ARM64_REG_X21,native.INFO)
        self.uc.reg_write(UC_ARM64_REG_X22,CONTROLLER+0x1f7c)
        self.u32(native.INFO+0x22c,0) # normal, non-forfeit input
        self.stubs[0x72e9b04]=lambda:0
        self.uc.emu_start(0x6b1dfbc if period==3 else 0x6b1dfd0,0x6b1dff8,count=10000)
        assert self.read32(CONTROLLER+0x1f7c)==result
        return result


@unittest.skipUnless(native.APK.is_file(),'requires original V17 APK')
class TournamentPeriodNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with zipfile.ZipFile(native.APK)as z:native.raw=z.read('lib/arm64-v8a/libUE4.so')
        assert hashlib.sha256(native.raw).hexdigest()=='efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8'
        resource=Path(os.environ.get('STUDIO_TEST_ADAPTER',str(SOURCE/'resources/native-ai-match-adapter.json')))
        native.bundle=json.loads(resource.read_text('utf8'));native.layout=native.bundle['channel_schema']

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)

    def bridge(self,spec=None):
        spec=fixture()[0]if spec is None else spec
        spec.setdefault('entry_id','native-period-test')
        bridge=runtime.Bridge(bytearray(32768),0,native.layout,lambda:None,
                              dict.fromkeys(runtime.REQUIRED_PROOFS,True),lambda *_:None)
        with patch.object(bridge,'log'):bridge.configure(spec,self.temp.name)
        return bridge

    def configure(self,v,rules,coaching=True,team=1,bridge=None):
        spec=fixture()[0];spec.update(entry_id='native-period-test',auto_coaching=coaching,
                                    tournament_rules=rules)
        bridge=self.bridge(spec)if bridge is None else bridge
        if bridge.spec!=spec:
            with patch.object(bridge,'log'):bridge.configure(spec,self.temp.name)
        v.uc.mem_write(native.BUS,bridge.read(0,32768));v.u32(native.SELF+8,team)
        self.assertEqual(v.observe(),1)
        self.assertEqual(v.read32(native.BUS+native.layout['rules_applied']),1)
        return bridge

    def test_display_yes_alone_reproduces_90_minute_end_then_live_rules_enter_extra_time(self):
        v=PeriodVM();v.original_copy()
        self.assertEqual(bytes(v.uc.mem_read(PARAMS+0x121,2)),b'\1\1')
        self.assertEqual(v.decision(3),FINISH)
        self.configure(v,rule())
        self.assertEqual(v.decision(3),ENTER_ET)
        self.assertEqual(v.decision(7),ENTER_PK)

    def test_90_minute_consumer_matrix_aggregate_away_goals_coaching_and_both_sides(self):
        cases=0
        for leg,et,pk,away,away_extra,coaching,team in itertools.product(
                ('single','first','second'),*( (False,True),)*5,(0,1)):
            r=rule();r.update(two_leg=leg!='single',first_leg=leg=='first',second_leg=leg=='second',
                extra_time=et and leg!='first',penalties=pk and leg!='first',
                away_goals=away and leg=='second',away_goals_extra_time=away_extra)
            v=PeriodVM();v.original_copy()
            for prior in ([0,0],[1,0],[0,2],[1,1]):
                r['prior_goals']=prior if leg=='second'else[0,0]
                self.configure(v,r,coaching,team)
                for score in ([0,0],[1,0],[0,1],[1,1],[2,1],[1,2]):
                    with self.subTest(leg=leg,et=et,pk=pk,away=away,extra=away_extra,
                                      coaching=coaching,team=team,prior=prior,score=score):
                        v.regular=list(score);ph,pa=r['prior_goals']
                        tie=score[0]+ph==score[1]+pa
                        if r['away_goals']and ph!=score[1]:tie=False
                        expected=(ENTER_ET if r['extra_time']else ENTER_PK if r['penalties']else FINISH)if tie else FINISH
                        self.assertEqual(v.decision(3),expected);cases+=1
        self.assertEqual(cases,4608)

    def test_120_minute_consumer_matrix_extra_scores_and_away_extra_rule(self):
        cases=0
        for second,pk,away,away_extra,coaching,team in itertools.product(*( (False,True),)*6):
            r=rule();r.update(two_leg=second,second_leg=second,penalties=pk,
                away_goals=second and away,away_goals_extra_time=away_extra,
                prior_goals=[1,2]if second else[0,0])
            v=PeriodVM();self.configure(v,r,coaching,int(team))
            # In a second leg 2:1 plus prior 1:2 admits ET; no ET goal is
            # included in the regular-time fixture totals.
            v.regular=[2,1]if second else[0,0]
            for first,second_half in itertools.product(([0,0],[1,0],[0,1],[1,1]),repeat=2):
                v.extra_first=list(first);v.extra_second=list(second_half)
                eh,ea=[first[i]+second_half[i]for i in (0,1)]
                tied=eh==ea and not(r['away_goals']and away_extra and eh>0)
                expected=ENTER_PK if tied and pk else FINISH
                self.assertEqual(v.decision(7),expected);cases+=1
        self.assertEqual(cases,1024)

    def test_ordinary_modes_human_roster_mismatch_and_other_root_never_change_rules(self):
        for reason in ('ordinary','human','identity','different_root','disabled'):
            v=PeriodVM();v.original_copy();before=bytes(v.uc.mem_read(PARAMS,0x160))
            self.configure(v,rule())
            v.uc.mem_write(PARAMS,before)
            if reason=='ordinary':
                ordinary=fixture()[0];ordinary['entry_id']='ordinary-division'
                v.uc.mem_write(native.BUS,self.bridge(ordinary).read(0,32768))
            if reason=='human':v.human=True
            if reason=='identity':v.u64(native.BUS+native.layout['expected'],999)
            if reason=='different_root':v.u64(native.SELF+0x370,native.ROOT+0x100)
            if reason=='disabled':v.u32(native.BUS+native.layout['enabled'],0)
            v.observe();self.assertEqual(bytes(v.uc.mem_read(PARAMS,0x160)),before)

    def test_cached_start_reply_and_process_restart_rearm_same_real_period_consumer(self):
        spec=fixture()[0];spec['style']='possession'
        team={'_studio_tournament_squad':{'tactical_spec':spec,'team_id':1}}
        active=dict(game_id=7,fixture_id=8,player_side='HOME',home=team,away=team,
                    native_rules=rule(),match_env={'cpu_level':'HARDEST'},
                    started=True,start_contract=5,start_reply={'game_id':7,'kept':'saved teams'})
        current={'run_id':'kept-run','active':active,'receipts':{}}
        service=Service(lambda:{},self.temp.name,None)
        logic=types.SimpleNamespace(conn=object())
        channels=[]
        def activate(handed,_root):
            bridge=self.bridge(handed);channels.append(bridge)
            return {'status':'configured','execution_enabled':bridge.execute}
        modules={'custom_stadium':types.SimpleNamespace(apply=lambda *_:None)}
        with patch.dict('sys.modules',modules),patch.object(service,'repair_rentals'),patch('ai_match_runtime.activate',activate):
            for coaching in (False,True):
                for _restart in range(2):
                    restored=json.loads(json.dumps(current))
                    reply=service.start(logic,{'auto_coaching':coaching,'difficulty':'HARDEST'},restored,{'game_id':7})
                    self.assertEqual(reply,active['start_reply'])
                    v=PeriodVM();v.original_copy()
                    for i in range(23):v.u32(native.PLAYERS+0xa8+i*0x198+0x30,0xfffffffe)
                    v.uc.mem_write(native.BUS,channels[-1].read(0,32768))
                    self.assertEqual(v.observe(),1)
                    self.assertEqual(v.decision(3),ENTER_ET);self.assertEqual(v.decision(7),ENTER_PK)
                    self.assertEqual(v.read32(native.BUS+native.layout['difficulty_applied']),1)
                    self.assertEqual(v.read32(native.BUS+native.layout['difficulty_after_offense']),5)
                    self.assertEqual(channels[-1].execute,coaching)
                    self.assertEqual(restored['run_id'],'kept-run');self.assertEqual(restored['receipts'],{})

    def test_fresh_start_handoff_reaches_same_native_consumer_with_coaching_on_or_off(self):
        spec=fixture()[0];spec['style']='possession'
        squad={'player_list':[{'gameplayer_id':{'id':p['id'],'serial':p['serial']}}for p in spec['players']],
               'squad_gameplan':{'match_plan_settings':{'order':list(range(11))}}}
        team={'_studio_tournament_squad':{'tactical_spec':spec,'team_id':1},
              'squad_data':squad,'coach_data':{'coach_id':1},
              'player_list':[{'gameplayer_id':{'id':p['id'],'serial':p['serial']},
                              'parameters':copy.deepcopy(p['parameters'])}for p in spec['players']]}
        logic=types.SimpleNamespace(conn=object(),responses={'CMD_START_GAME':{
            'uniform_list_home':{},'uniform_list_away':{}}},templates={})
        modules={'custom_stadium':types.SimpleNamespace(apply=lambda *_:None),
                 'club_store':types.SimpleNamespace(default_uniforms=lambda *_:[])}
        pool={(p['id'],p['serial']):{'parameters':p['parameters']}for p in spec['players']}
        service=Service(lambda:{},self.temp.name,None);channels=[]
        def activate(handed,_root):
            bridge=self.bridge(handed);channels.append(bridge)
            return {'status':'configured','execution_enabled':bridge.execute}
        def frozen_contract(conn,current,fixture,active):
            # This test executes the native consumer of these exact protocol
            # rows. Full legal-roster scoring has its own lifecycle tests.
            self.assertEqual(fixture['id'],active['fixture_id'])
            return {'frozen':True,'source':'explicit native-consumer test fixture',
                    'teams':{side:copy.deepcopy(active[side])for side in('home','away')}}
        with patch.dict('sys.modules',modules),patch('ai_match_runtime.activate',activate),\
             patch.object(service,'repair_rentals'),patch.object(service,'player_pool',return_value=pool),\
             patch.object(service,'freeze_fixture',side_effect=frozen_contract):
            for coaching,side in itertools.product((False,True),('HOME','AWAY')):
                current={'run_id':'new-run','active':dict(game_id=7,fixture_id=8,player_side=side,
                    home=copy.deepcopy(team),away=copy.deepcopy(team),native_rules=rule(),
                    match_env={'cpu_level':'HARDEST'}),'receipts':{},'fixtures':[{'id':8,'played':False}]}
                reply=service.start(logic,{'auto_coaching':coaching,'difficulty':'HARDEST'},current,{'game_id':7,'side':side})
                self.assertEqual(reply['game_id'],7);self.assertEqual(current['active']['start_contract'],5)
                v=PeriodVM();v.original_copy();v.u32(native.SELF+8,int(side=='HOME'))
                for i in range(23):v.u32(native.PLAYERS+0xa8+i*0x198+0x30,0xfffffffd if side=='AWAY'else 0xfffffffe)
                v.uc.mem_write(native.BUS,channels[-1].read(0,32768))
                self.assertEqual(v.observe(),1);self.assertEqual(v.decision(3),ENTER_ET)
                self.assertEqual(v.decision(7),ENTER_PK);self.assertEqual(channels[-1].execute,coaching)
                self.assertEqual(v.read32(native.BUS+native.layout['difficulty_after_offense']),5)

    def test_current_definition_overrides_cached_difficulty_for_every_level_side_and_coaching_gate(self):
        levels=('VERYEASY','EASY','NORMAL','HARD','VERYHARD','HARDEST','LEGEND')
        spec=fixture()[0];spec['style']='possession'
        team={'_studio_tournament_squad':{'tactical_spec':spec,'team_id':1},'cpu_level':'HARDEST'}
        service=Service(lambda:{},self.temp.name,None);logic=types.SimpleNamespace(conn=object());channels=[]
        def activate(handed,_root):
            bridge=self.bridge(handed);channels.append(bridge)
            return {'status':'configured','execution_enabled':bridge.execute}
        modules={'custom_stadium':types.SimpleNamespace(apply=lambda *_:None)}
        with patch.dict('sys.modules',modules),patch.object(service,'repair_rentals'),patch('ai_match_runtime.activate',activate):
            for level,coaching,side in itertools.product(levels,(False,True),('HOME','AWAY')):
                with self.subTest(level=level,coaching=coaching,side=side):
                    active=dict(game_id=7,fixture_id=8,player_side=side,home=copy.deepcopy(team),away=copy.deepcopy(team),
                        native_rules=rule(),match_env={'cpu_level':'HARDEST','exTime':'YES','pk':'YES'},
                        started=True,start_contract=5,start_reply={'game_id':7,'cpu_level':'HARDEST','random_seed':56789})
                    current={'run_id':'same-edition','active':active,'fixtures':[{'id':8,'played':False}],
                             'receipts':{'previous-game':{'kept':True}},'difficulty':level}
                    before=copy.deepcopy(current)
                    out=service.start(logic,{'difficulty':level,'auto_coaching':coaching},current,{'game_id':7,'side':side})
                    self.assertEqual(out,{'game_id':7,'cpu_level':level,'random_seed':56789})
                    self.assertEqual(active['match_env'],{'cpu_level':level,'exTime':'YES','pk':'YES'})
                    self.assertEqual(active['home']['cpu_level'],level);self.assertEqual(active['away']['cpu_level'],level)
                    for key in ('run_id','fixtures','receipts'):self.assertEqual(current[key],before[key])
                    self.assertEqual(active['native_rules'],before['active']['native_rules'])
                    v=PeriodVM();v.u32(native.SELF+8,int(side=='HOME'))
                    expected_serial=0xfffffffd if side=='AWAY'else 0xfffffffe
                    for i in range(23):v.u32(native.PLAYERS+0xa8+i*0x198+0x30,expected_serial)
                    v.uc.mem_write(native.BUS,channels[-1].read(0,32768));self.assertEqual(v.observe(),1)
                    actual=levels.index(level)
                    for field in ('requested','after_offense','after_defense'):
                        self.assertEqual(v.read32(native.BUS+native.layout['difficulty_'+field]),actual)
                    self.assertEqual(v.read32(native.BUS+native.layout['difficulty_applied']),1)
                    self.assertEqual(channels[-1].execute,coaching)
                    # The same catalogue cards under the OTHER foreign serial
                    # remain rejected. This repair does not loosen scope.
                    wrong=PeriodVM();wrong.u32(native.SELF+8,int(side=='HOME'))
                    for i in range(23):wrong.u32(native.PLAYERS+0xa8+i*0x198+0x30,0xfffffffe if side=='AWAY'else 0xfffffffd)
                    wrong.uc.mem_write(native.BUS,channels[-1].read(0,32768))
                    self.assertEqual(wrong.observe(),0)
                    self.assertEqual(wrong.read32(native.BUS+native.layout['diagnostic']+16),7)


if __name__=='__main__':unittest.main()
