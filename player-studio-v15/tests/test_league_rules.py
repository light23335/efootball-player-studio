import copy,json,sys,unittest,sqlite3,types
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import league_rules as r
def state(d=3,p=1200,**kw):return dict(division=d,best=d,points=p,matches=0,wins=0,draws=0,losses=0,round=4,**kw)
class LeagueRulesTests(unittest.TestCase):
    def test_rating_promotions_inherit_crossing_score(self):
        s=state(p=1480);_,out,_=r.advance(s,'WIN',32)
        self.assertEqual((s['division'],s['points'],out),(2,1512,'PROMOTED'))
        s['points']=1794;r.advance(s,'WIN',19);self.assertEqual((s['division'],s['points']),(1,1813))
    def test_floor_protection_all_rated_divisions(self):
        for d,p in r.FLOORS.items():
            s=state(d,p);r.advance(s,'LOSE',-40);self.assertEqual((s['division'],s['points']),(d,p))
            self.assertIsNone(r.transition(s,True))
    def test_read_migration_keeps_round_and_history(self):
        s=state(2,1907);s.update(matches=9,wins=4,draws=2,losses=3,rule_version=2)
        self.assertEqual(r.load_state(json.dumps(s)),s)
    def test_ten_games_and_only_mathematically_decided_skip(self):
        s=state(4,0)
        self.assertIsNone(r.transition(s,True))
        for _ in range(7):r.advance(s,'WIN')
        self.assertEqual(s['division'],4);self.assertIsNone(r.transition(s,True))
        r.advance(s,'WIN');self.assertEqual(r.transition(s,True),(3,'PROMOTED'))
        for _ in range(2):r.advance(s,'LOSE')
        self.assertEqual((s['division'],s['points']),(3,1200))
    def test_expected_score_changes_with_both_ratings(self):
        self.assertLess(r.rating_delta(1900,1400,'WIN'),r.rating_delta(1400,1900,'WIN'))
        self.assertLess(r.rating_delta(1900,1400,'LOSE'),r.rating_delta(1400,1900,'LOSE'))
        marker=lambda n:{'division':2,'opponent':{'_studio_division_squad_v1':{'native_lower_bound_strength':n}}}
        self.assertGreater(r.opponent_rating(marker(3500)),r.opponent_rating(marker(3300)))

class NativeLeagueIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:');self.addCleanup(self.conn.close)
        self.conn.execute('create table meta(key text primary key,value text)')
        self.events=[];self.history=[]
        get=lambda c,k,default='':next(iter(c.execute('select value from meta where key=?',(k,))),[default])[0]
        def put(c,k,v):c.execute('insert into meta values(?,?) on conflict(key) do update set value=excluded.value',(k,v))
        self.store=types.SimpleNamespace(get_meta=get,set_meta=put,log_event=lambda c,k,v:self.events.append((k,v)))
        self.ai=types.ModuleType('ai_division');a=self.ai
        a.store=self.store;a.STATE_KEY='league';a.view=lambda t,s,*args:dict(t or {},points=s['points'])
        a.rules=lambda:{};a.start=lambda c,q:{'result':'NOERR'};a._begin=lambda c:c.execute('BEGIN IMMEDIATE')
        a._refresh_phase=lambda out:out;a.is_league=lambda req:True;a._scores=lambda req:(2,0)
        a.vscom_result=types.SimpleNamespace(outcome=lambda *args:'WIN');a.LEVELS={d:5 for d in range(1,11)}
        a.save=lambda c,s:put(c,'league',json.dumps(s))
        a.division_history=types.SimpleNamespace(own_snapshot=lambda *args:{},record=lambda c,*args:self.history.append(args),records=lambda *args:[])
        a.player_match_stats=types.SimpleNamespace(record=lambda *args:None)
        a._result_response=lambda resp,req,s,outcome,*args:dict(result='NOERR',rqid=req['rqid'],state=copy.deepcopy(s),outcome=outcome)
        with patch.dict(sys.modules,{'ai_division':a}):r.install()
    def put(self,key,value):
        self.store.set_meta(self.conn,key,json.dumps(value));self.conn.commit()
    def test_finish_promotes_with_real_score_and_replays_without_double_settlement(self):
        self.put('league',state(3,1495));self.put('ai_division_active_match',dict(game_id=77,started=True,round=4,division=3,side='HOME',_studio_rating_opponent=1700))
        response=self.ai.finish(self.conn,{},dict(rqid='first',game_id=77))
        self.assertEqual(response['state']['division'],2);self.assertGreater(response['state']['points'],1500)
        replay=self.ai.finish(self.conn,{},dict(rqid='retry',game_id=77))
        self.assertEqual(replay['state'],response['state']);self.assertEqual(replay['rqid'],'retry')
        self.assertEqual(len(self.history),1);self.assertEqual(len(self.events),1)
    def test_skip_cannot_promote_rated_or_unresolved_round_and_has_replay_receipt(self):
        self.put('league',state(3,1600))
        request={'rqid':'one','session_id':'session','user_id':1}
        self.assertEqual(self.ai.skip(self.conn,{},request)['result'],'ERR_INVALID_PARAM')
        s=state(4,21);s.update(matches=7,wins=7);self.put('league',s)
        self.assertEqual(self.ai.skip(self.conn,{},request)['result'],'ERR_INVALID_PARAM')
        s.update(points=24,matches=8,wins=8);self.put('league',s)
        first=self.ai.skip(self.conn,{},request);second=self.ai.skip(self.conn,{},request)
        self.assertEqual(first,second);self.assertEqual(self.ai.state(self.conn)['division'],3)
        self.assertEqual(len(self.events),1)
