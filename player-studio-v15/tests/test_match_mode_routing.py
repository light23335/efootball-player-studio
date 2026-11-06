"""Both real installed bridges over original GateLogic and division dispatch.

Protected code objects are read without importing their application modules.
The original handle/opponent dispatch and division prepare/start/finish execute;
asset/profile services and native START serialization are explicit fixtures.
Only an in-memory SQLite database is used.
"""
import copy
import dis
import functools
import hashlib
import json
import marshal
import os
from pathlib import Path
import threading
import time
import types
import unittest
from unittest.mock import patch

import ai_division_sessions as sessions
import tournament_runtime as tournament
import test_tournament_sim_lifecycle as fixtures
from apk_literals import module_reader,literal_assignments

ROOT=Path(__file__).resolve().parents[2]


def _codes(code):
    yield code
    for value in code.co_consts:
        child=value
        if isinstance(value,bytes)and value[:1]in(b'c',b'\xe3'):
            try:child=marshal.loads(value)
            except(ValueError,EOFError,TypeError):continue
        if isinstance(child,types.CodeType):yield from _codes(child)


@functools.lru_cache(maxsize=1)
def original_contract():
    delivery=json.loads((ROOT/'.work/tournament-entry-person-repair-20261105/game-delivery.json').read_text('utf8'))
    reader=module_reader(Path(os.environ.get('STUDIO_TEST_RESULT_APK',delivery['path'])))
    gate=list(_codes(reader('gate_logic')));ai=reader('ai_division')
    functions={c.co_name:c for c in ai.co_consts if isinstance(c,types.CodeType)}
    constants=literal_assignments(ai,{'NATIVE_LEVELS','LEVELS','STATE_KEY','RULE_VERSION','RATING_START',
                                    'RATING_FLOOR','PHASE_ID','PHASE_START_TIME','PHASE_END_TIME'})
    instructions=list(dis.get_instructions(ai));defaults={}
    for i,op in enumerate(instructions):
        if op.opname=='MAKE_FUNCTION'and op.arg&1:
            code=instructions[i-1].argval;value=instructions[i-2].argval
            if isinstance(code,types.CodeType)and isinstance(value,tuple):defaults[code.co_name]=value
    constants['_fixture_function_defaults']=defaults
    return (next(c for c in gate if c.co_name=='handle'and c.co_firstlineno==212),
            next(c for c in gate if c.co_name=='_vscom_opponent'),functions,constants)


class ModeRoutingTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.SimulationLifecycleTests();f.setUp();self.addCleanup(f.doCleanups)
        self.f=f;self.db=f.db;self.service=f.service;self.entries=sessions.Entries('routing-A')
        self.trace=[];self.history=[]
        base_handle,opponent,functions,constants=original_contract()
        def get_meta(conn,key,default=None):
            row=conn.execute('select value from meta where key=?',(key,)).fetchone()
            return row[0]if row else default
        def set_meta(conn,key,value):conn.execute('insert into meta values(?,?) on conflict(key)do update set value=excluded.value',(key,value))
        store=types.SimpleNamespace(get_meta=get_meta,set_meta=set_meta,log_event=lambda *a:None,
            player_identity=types.SimpleNamespace(canonical_request=lambda conn,req:req),
            squads=lambda conn:[],main_squad_id=lambda conn:1)
        native_ai=types.ModuleType('native_ai_division_routing_fixture')
        native_ai.__dict__.update(constants,copy=copy,json=json,time=time,store=store,
            ziru_data=types.SimpleNamespace(normalize_opponent_team=lambda p,*a:p),
            owned_coaches=types.SimpleNamespace(sync_opponent=lambda *a:None),
            division_history=types.SimpleNamespace(own_snapshot=lambda *a:{'kept':'owned'},
                record=lambda conn,a,req,result:self.history.append(a['game_id']),records=lambda *a:[]),
            player_match_stats=types.SimpleNamespace(record=lambda *a:None))
        for name,code in functions.items():
            setattr(native_ai,name,types.FunctionType(code,native_ai.__dict__,argdefs=constants['_fixture_function_defaults'].get(name)))
        def outcome(req,side,home,away):
            own,other=(home,away)if side=='HOME'else(away,home)
            return 'WIN'if own>other else'LOSE'if own<other else'DRAW'
        native_ai.vscom_result=types.SimpleNamespace(outcome=outcome)
        native_ai._result_response=lambda resp,req,state,*args:{'result':'NOERR','owner':'division',
            'game_id':sessions.game_id(req),'rqid':req.get('rqid'),'division_state':copy.deepcopy(state)}
        self.ai=native_ai
        source_prepare=native_ai.prepare
        def prepare(conn,response,req):
            self.trace.append(('division_prepare',copy.deepcopy(req)))
            return source_prepare(conn,response,req)
        native_ai.prepare=prepare
        source_info=native_ai.info
        def info(conn,response):
            self.trace.append(('division_info',{}));return source_info(conn,response)
        native_ai.info=info
        no_entry=types.SimpleNamespace(handle=lambda *a:None,project=lambda mid,resp,conn:resp,LIST_COMMANDS=())
        vscom=types.SimpleNamespace(outcome=outcome,
            finish=lambda conn,response,req:dict(response,owner='ordinary'),
            prepare=lambda conn,response,req=None:dict(response,owner='ordinary',game_id=87654))
        namespace=dict(copy=copy,json=json,hashlib=hashlib,legend_cr7_grants=None,store=store,
            ml_event_entry=no_entry,cup_entry=no_entry,ai_division=native_ai,
            my_league=types.SimpleNamespace(state=lambda conn:None,is_season=lambda req:False,handles_result=lambda *a:False),
            opponent_squad=types.SimpleNamespace(build=lambda *a:None,last_error=lambda *a:None),
            ziru_data=types.SimpleNamespace(normalize_opponent_team=lambda p,*a:p),
            vscom_result=vscom,
            player_match_stats=types.SimpleNamespace(attach_result_updates=lambda conn,response,req:response),
            player_training=types.SimpleNamespace(lock_reply_inventory=lambda *a:None),
            account_state=types.SimpleNamespace(apply=lambda *a:None))
        class Logic:
            def _align_live_data_version(self,out):return out
            def _profile_index(self,*a):return 0
            def _ported(self,name,callback):return copy.deepcopy(f.proto)
            def _quiet_home(self,mid,out):return out
            def _rewrite_activity_links(self,out):return out
            def fixup(self,out):return out
            def _home_entries(self,*a):return []
            def _start_game(inner,mid,req):
                self.trace.append(('native_start',copy.deepcopy(req)))
                if not native_ai.is_league(req)or not native_ai.start(inner.conn,req):
                    return {'result':'ERR_INVALID_PARAM','owner':'ordinary'}
                return {'result':'NOERR','owner':'division','game_id':req['game_id'],'kept':'native start'}
        Logic.handle=types.FunctionType(base_handle,namespace)
        self.base_handle=Logic.handle
        Logic._vscom_opponent=types.FunctionType(opponent,namespace)
        self.logic=Logic();self.logic.conn=self.db;self.logic.responses=copy.deepcopy(f.logic.responses)
        self.logic.templates={}
        self.logic.responses['CMD_GET_EVENT_LIST_AND_LOG']={'result':'NOERR','event_list':[
            {'event_id':1120005,'ch_event_type':'CHALLENGE','is_custom_team':'YES','match_env':{'match_time':10}}],
            'event_log_list':[{'event_id':1120005,'entry_status':'ENTRY'}]}
        self.logic.responses['CMD_GET_VSCOM_OPPONENT']=copy.deepcopy(f.proto)
        self.logic.responses['CMD_GET_MYCLUB_VSCOM_OPPONENT']=copy.deepcopy(f.proto)
        self.logic.responses['CMD_GET_LEAGUE_COM_INFO']={'result':'NOERR'}
        self.logic.responses['CMD_GET_MAINMENU_INFO']={'result':'NOERR'}
        sessions.bridge(self.logic,self.entries,threading.RLock())
        modules={'developed_preview':types.SimpleNamespace(),
                 'club_store':types.SimpleNamespace(wire_player=lambda p:p,default_uniforms=lambda team:[team]),
                 'opponent_squad':types.SimpleNamespace(external_caps=None,formation_for_roles=None),
                 'ziru_data':types.SimpleNamespace(teams=None,normalize_opponent_team=None,vscom_opponent=lambda:copy.deepcopy(f.proto)),
                 'cup16_mode':types.SimpleNamespace(game_id=sessions.game_id,_scores=native_ai._scores),
                 'vscom_result':vscom,
                 'ai_match_runtime':types.SimpleNamespace(deactivate=lambda *a:None,deactivate_for_match=lambda *a:False),
                 'cup16_service':types.SimpleNamespace(Cup16Service=types.SimpleNamespace(
                     _result_reply=lambda logic,req,team,h,a,outcome:{'result':'NOERR','owner':'tournament',
                         'game_end_result':{'match_result':{'player_data':{}}}}))}
        self.addCleanup(patch.stopall)
        patch.dict('sys.modules',modules).start()
        patch.object(tournament.logging.getLogger(tournament.__name__),'exception').start()
        for module in('tournament_promotion_ui','native_tournament_schedule_ui','tournament_reward_ui'):
            patch(module+'.configure').start()
        with patch.object(tournament,'ClubGenerator',return_value=f.generator),patch.object(tournament,'Service',return_value=self.service):
            tournament.install(lambda:f.document,'.',self.logic)
        self.db.commit()

    def cold_gateway(self,reverse=False):
        cls=type('ColdLogic',(type(self.logic),),{'handle':self.base_handle})
        logic=cls();logic.conn=self.db;logic.responses=copy.deepcopy(self.logic.responses);logic.templates={}
        entries=sessions.Entries('routing-B')
        if not reverse:sessions.bridge(logic,entries,threading.RLock())
        service=tournament.Service(lambda:self.f.document,'.',self.f.generator)
        for name,options in(('activate_coaching',{}),('reinforcements',{'return_value':[]})):
            patch.object(service,name,**options).start()
        with patch.object(tournament,'ClubGenerator',return_value=self.f.generator),patch.object(tournament,'Service',return_value=service):
            tournament.install(lambda:self.f.document,'.',logic)
        if reverse:sessions.bridge(logic,entries,threading.RLock())
        return logic,service,entries

    def enter_tournament(self):
        return self.logic.handle('CMD_SET_EVENT_ENTER',{'event_id':self.f.definition['event_id']})

    def seed_division(self,started=False,game=12345):
        self.ai.state(self.db)
        entry=self.entries.draw(self.db,None,__import__('random').Random(4),'shuffle_bag')
        entry['game_id']=game
        opponent=copy.deepcopy(self.f.proto)
        opponent.update(result='NOERR',rqid=0,msgid='CMD_GET_VSCOM_OPPONENT')
        opponent[sessions.MARKER]={'entry_id':entry['entry_id'],'process_id':entry['process_id'],
                                   'draw_state_after':entry['draw_state_after']}
        active={'game_id':game,'round':self.ai.state(self.db)['round'],'division':self.ai.state(self.db)['division'],
                'started':started,'side':'HOME','opponent':opponent,'match_category':'LEAGUE_COM_CUSTOM'}
        with self.db:
            sessions.write(self.db,'ai_division_active_match',active)
            self.entries.commit(self.db,entry,opponent[sessions.MARKER])
        return copy.deepcopy(active)

    def stored_tournament(self):return tournament.get(self.db,tournament.PREFIX+self.f.definition['uuid'])

    def result(self,gid):
        return {'match_result':{'game_id':gid,'pk_flag':'NO'},
                'score':[{'score_1st':1,'score_2nd':1},{'score_1st':0,'score_2nd':0}]}

    def test_real_league_menu_then_generic_opponent_cannot_use_previous_tournament(self):
        self.assertEqual(self.enter_tournament()['result'],'NOERR')
        before=copy.deepcopy(tournament.get(self.db,tournament.PREFIX+self.f.definition['uuid']))
        self.seed_division()
        self.assertEqual(self.logic.handle('CMD_GET_LEAGUE_COM_INFO',{})['result'],'NOERR')
        self.assertIsNone(tournament.get(self.db,tournament.CONTEXT))
        opponent=self.logic.handle('CMD_GET_VSCOM_OPPONENT',{})
        self.assertEqual(opponent['game_id'],12345)
        self.assertEqual(self.trace[-1][0],'division_prepare')
        self.assertEqual(self.trace[-1][1]['match_category'],'LEAGUE_COM_CUSTOM')
        self.assertEqual(tournament.get(self.db,tournament.PREFIX+self.f.definition['uuid']),before)

    def test_successful_tournament_entry_owns_generic_opponent_and_start(self):
        self.seed_division();self.assertEqual(self.enter_tournament()['result'],'NOERR')
        active=tournament.get(self.db,tournament.PREFIX+self.f.definition['uuid'])['active']
        opponent=self.logic.handle('CMD_GET_VSCOM_OPPONENT',{})
        self.assertEqual(opponent['game_id'],active['game_id'])
        self.assertFalse(any(c=='division_prepare'for c,_ in self.trace))
        reply=self.logic.handle('CMD_START_GAME',{'game_id':active['game_id']})
        self.assertEqual(reply['game_id'],active['game_id'])
        self.assertNotIn('owner',reply)

    def test_each_accepted_native_navigation_clears_routing_without_erasing_saved_match(self):
        for command in sorted(sessions.EXIT_COMMANDS):
            with self.subTest(command=command):
                self.assertEqual(self.enter_tournament()['result'],'NOERR')
                active=copy.deepcopy(self.stored_tournament()['active'])
                out=self.logic.handle(command,{})
                self.assertEqual(out['result'],'NOERR')
                self.assertIsNone(tournament.get(self.db,tournament.CONTEXT))
                self.assertEqual(sessions.routing(self.logic).mode,'division'if command=='CMD_GET_LEAGUE_COM_INFO'else None)
                self.assertEqual(self.stored_tournament()['active'],active)

    def test_rejected_navigation_keeps_existing_tournament_route(self):
        self.enter_tournament();active=copy.deepcopy(self.stored_tournament()['active'])
        self.logic.responses['CMD_GET_MAINMENU_INFO']={'result':'ERR_BUSY'}
        self.assertEqual(self.logic.handle('CMD_GET_MAINMENU_INFO',{})['result'],'ERR_BUSY')
        self.assertEqual(self.logic.handle('CMD_GET_VSCOM_OPPONENT',{})['game_id'],active['game_id'])

    def test_cold_gateway_does_not_restore_generic_route_from_legacy_database_context(self):
        self.enter_tournament();before=copy.deepcopy(self.stored_tournament())
        division=self.seed_division(started=True)
        cold,service,entries=self.cold_gateway()
        out=cold.handle('CMD_GET_VSCOM_OPPONENT',{})
        self.assertNotEqual(out.get('game_id'),before['active']['game_id'])
        self.assertFalse(any(name=='division_prepare'for name,_ in self.trace))
        self.assertIsNone(tournament.get(self.db,tournament.CONTEXT))
        self.assertEqual(self.stored_tournament(),before)
        self.assertEqual(sessions.read(self.db,'ai_division_active_match'),division)

    def test_details_select_generic_entry_but_do_not_authorize_generic_opponent(self):
        self.assertEqual(self.logic.handle('CMD_GET_EVENT_INFO',{'event_id':self.f.definition['event_id']})['result'],'NOERR')
        out=self.logic.handle('CMD_GET_VSCOM_OPPONENT',{})
        self.assertNotIn('active',self.stored_tournament())
        self.assertEqual(self.logic.handle('CMD_ENTER_EVENT_COMPE',{})['result'],'NOERR')
        self.assertEqual(self.logic.handle('CMD_GET_VSCOM_OPPONENT',{})['game_id'],self.stored_tournament()['active']['game_id'])

    def test_explicit_division_category_overrides_tournament_for_both_opponent_commands(self):
        self.seed_division()
        for command in sorted(sessions.OPPONENT_COMMANDS):
            with self.subTest(command=command):
                self.enter_tournament();before=copy.deepcopy(self.stored_tournament())
                out=self.logic.handle(command,{'match_category':'LEAGUE_COM_CUSTOM'})
                self.assertEqual(out['game_id'],12345)
                self.assertEqual(self.stored_tournament(),before)
                self.assertIsNone(tournament.get(self.db,tournament.CONTEXT))
                self.assertEqual(sessions.routing(self.logic).mode,'division')

    def test_unknown_explicit_event_does_not_fall_back_to_tournament_context(self):
        self.enter_tournament();before=copy.deepcopy(self.stored_tournament())
        self.assertEqual(self.logic.handle('CMD_GET_EVENT_INFO',{'event_id':1120005})['result'],'NOERR')
        out=self.logic.handle('CMD_GET_VSCOM_OPPONENT',{})
        self.assertNotEqual(out.get('game_id'),before['active']['game_id'])
        self.assertEqual(self.stored_tournament(),before)
        self.assertIsNone(tournament.get(self.db,tournament.CONTEXT))

    def test_event_game_and_category_conflicts_cannot_reach_other_native_mode(self):
        self.enter_tournament();tid=self.stored_tournament()['active']['game_id'];self.seed_division()
        eid=self.f.definition['event_id']
        cases=[{'game_id':tid,'match_category':'LEAGUE_COM_CUSTOM'},
               {'game_id':tid,'event_id':1120005},
               {'game_id':12345,'event_id':eid},
               {'game_id':12345,'match_category':'EVENT_CHALLENGE_CUSTOM'},
               {'game_id':tid,'match_result':{'game_id':12345}},
               {'event_id':1120005,'compe_unit_id':eid,'game_id':tid},
               {'game_id':999999}]
        for command in sorted(sessions.CALLBACK_COMMANDS):
            for request in cases:
                with self.subTest(command=command,request=request):
                    before=list(self.db.execute('select key,value from meta order by key'))
                    self.assertEqual(self.logic.handle(command,request)['result'],'ERR_INVALID_PARAM')
                    self.assertEqual(list(self.db.execute('select key,value from meta order by key')),before)
                    self.assertFalse(any(name=='native_start'for name,_ in self.trace))

    def test_opponent_requests_cannot_mix_another_modes_event_and_game_identity(self):
        self.enter_tournament();tid=self.stored_tournament()['active']['game_id'];self.seed_division()
        eid=self.f.definition['event_id']
        for command in sessions.OPPONENT_COMMANDS:
            for request in({'event_id':eid,'game_id':12345},
                            {'event_id':eid,'game_id':999999},
                            {'game_id':tid,'match_category':'LEAGUE_COM_CUSTOM'}):
                with self.subTest(command=command,request=request):
                    before=list(self.db.execute('select key,value from meta order by key'))
                    self.assertEqual(self.logic.handle(command,request)['result'],'ERR_INVALID_PARAM')
                    self.assertEqual(list(self.db.execute('select key,value from meta order by key')),before)

    def test_dispatch_survives_reverse_install_order_and_outer_observer_layers(self):
        self.seed_division(started=True)
        for reverse in(False,True):
            with self.subTest(reverse=reverse):
                logic,service,entries=self.cold_gateway(reverse=reverse)
                import action_trace,league_availability
                with patch.object(action_trace,'record_lifecycle'):
                    action_trace.install_lifecycle(logic)
                    league_availability.install(logic,clock=lambda:1793937000)
                    self.assertEqual(logic.handle('CMD_SET_EVENT_ENTER',{'event_id':self.f.definition['event_id']})['result'],'NOERR')
                    tid=self.stored_tournament()['active']['game_id']
                    self.assertEqual(logic.handle('CMD_GET_VSCOM_OPPONENT',{})['game_id'],tid)
                    self.assertEqual(logic.handle('CMD_GET_LEAGUE_COM_INFO',{})['result'],'NOERR')
                    self.assertEqual(logic.handle('CMD_GET_VSCOM_OPPONENT',{})['game_id'],12345)
                    self.assertIsNone(tournament.get(self.db,tournament.CONTEXT))

    def test_explicit_game_ids_resume_correct_mode_including_cold_tournament_start(self):
        self.enter_tournament();tid=self.stored_tournament()['active']['game_id']
        first=self.logic.handle('CMD_START_GAME',{'game_id':tid})
        issued=copy.deepcopy(self.stored_tournament()['active']);self.seed_division(started=True)
        self.logic.handle('CMD_GET_LEAGUE_COM_INFO',{})
        cold,service,entries=self.cold_gateway()
        again=cold.handle('CMD_START_GAME',{'game_id':tid})
        self.assertEqual(again,first)
        self.assertEqual(self.stored_tournament()['active'],issued)
        out=cold.handle('CMD_START_GAME',{'game_id':12345})
        self.assertEqual(out['owner'],'division')
        self.assertEqual(self.trace[-1][1]['match_category'],'LEAGUE_COM_CUSTOM')
        self.assertIsNone(tournament.get(self.db,tournament.CONTEXT))

    def test_issued_division_snapshot_rebinds_after_cold_navigation_without_draw_or_replacement(self):
        active=self.seed_division(started=True);draw=copy.deepcopy(sessions.read(self.db,sessions.DRAW_KEY))
        self.enter_tournament();self.logic.handle('CMD_GET_MAINMENU_INFO',{})
        cold,service,entries=self.cold_gateway()
        self.assertEqual(cold.handle('CMD_GET_LEAGUE_COM_INFO',{})['result'],'NOERR')
        self.assertEqual(cold.handle('CMD_GET_VSCOM_OPPONENT',{})['game_id'],active['game_id'])
        self.assertTrue(entries.reusable(self.db,sessions.read(self.db,'ai_division_active_match')))
        saved=sessions.read(self.db,'ai_division_active_match')
        self.assertTrue(saved['started'])
        self.assertEqual(saved['opponent']['player_list'],active['opponent']['player_list'])
        self.assertEqual(sessions.read(self.db,sessions.DRAW_KEY),draw)
        self.assertEqual(self.db.execute('select count(*)from personal_ai_entries').fetchone()[0],1)

    def test_closed_unissued_division_id_cannot_start_or_settle_a_replacement(self):
        self.seed_division(game=12345)
        self.assertEqual(self.logic.handle('CMD_GET_MAINMENU_INFO',{})['result'],'NOERR')
        self.assertTrue(self.entries.current(self.db)['closed'])
        replacement=self.seed_division(game=12346)
        self.enter_tournament();tournament_before=copy.deepcopy(self.stored_tournament())
        cold,service,entries=self.cold_gateway()
        for command in sorted(sessions.CALLBACK_COMMANDS):
            for category in(None,'LEAGUE_COM_CUSTOM'):
                with self.subTest(command=command,category=category):
                    request=self.result(12345)if command=='CMD_GET_VSCOM_GAME_RESULT'else{'game_id':12345}
                    if category:request['match_category']=category
                    before=list(self.db.execute('select key,value from meta order by key'))
                    self.assertEqual(cold.handle(command,request)['result'],'ERR_INVALID_PARAM')
                    self.assertEqual(list(self.db.execute('select key,value from meta order by key')),before)
                    self.assertFalse(any(name=='native_start'for name,_ in self.trace))
        self.assertEqual(sessions.read(self.db,'ai_division_active_match'),replacement)
        self.assertEqual(self.stored_tournament(),tournament_before)
        self.assertEqual(self.db.execute('select count(*)from personal_ai_entries').fetchone()[0],2)
        self.assertEqual(cold.handle('CMD_START_GAME',{'game_id':12346})['owner'],'division')
        self.assertTrue(sessions.read(self.db,'ai_division_active_match')['started'])

    def test_old_division_receipt_only_replays_result_and_cannot_start_new_active(self):
        self.seed_division(started=True,game=12345)
        receipt=self.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.result(12345))
        replacement=self.seed_division(game=12346)
        self.enter_tournament();route=sessions.routing(self.logic)
        binding=(route.mode,route.tournament,route.selection)
        before=list(self.db.execute('select key,value from meta order by key'))
        self.assertEqual(self.logic.handle('CMD_START_GAME',{'game_id':12345})['result'],'ERR_INVALID_PARAM')
        self.assertFalse(any(name=='native_start'for name,_ in self.trace))
        self.assertEqual(list(self.db.execute('select key,value from meta order by key')),before)
        self.assertEqual(self.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.result(12345)),receipt)
        self.assertEqual((route.mode,route.tournament,route.selection),binding)
        self.assertEqual(sessions.read(self.db,'ai_division_active_match'),replacement)
        self.assertEqual(list(self.db.execute('select key,value from meta order by key')),before)
        self.assertEqual(self.history,[12345])

    def test_division_settlement_and_receipt_replay_do_not_switch_live_tournament_route(self):
        active=self.seed_division(started=True)
        self.enter_tournament();before=copy.deepcopy(self.stored_tournament())
        out=self.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.result(active['game_id']))
        self.assertEqual(out['owner'],'division')
        self.assertEqual(self.history,[active['game_id']])
        state=copy.deepcopy(self.ai.state(self.db));self.assertEqual(state['matches'],1)
        self.assertEqual(self.stored_tournament(),before)
        self.assertEqual(sessions.routing(self.logic).mode,'tournament')
        self.logic.handle('CMD_GET_MAINMENU_INFO',{})
        replay=self.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.result(active['game_id']))
        self.assertEqual(replay['owner'],'division')
        self.assertEqual(self.ai.state(self.db),state)
        self.assertEqual(self.history,[active['game_id']])

    def test_tournament_settlement_and_receipt_replay_do_not_switch_live_division_route(self):
        self.enter_tournament();tid=self.stored_tournament()['active']['game_id']
        self.logic.handle('CMD_START_GAME',{'game_id':tid});self.seed_division(started=True)
        self.logic.handle('CMD_GET_LEAGUE_COM_INFO',{})
        division=copy.deepcopy(sessions.read(self.db,'ai_division_active_match'))
        out=self.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.result(tid))
        self.assertEqual(out['owner'],'tournament')
        self.assertEqual(sessions.routing(self.logic).mode,'division')
        self.assertIsNone(tournament.get(self.db,tournament.CONTEXT))
        settled=copy.deepcopy(self.stored_tournament())
        self.assertIn(str(tid),settled['receipts'])
        self.assertEqual(self.logic.handle('CMD_GET_VSCOM_GAME_RESULT',self.result(tid)),out)
        self.assertEqual(self.stored_tournament(),settled)
        self.assertEqual(sessions.read(self.db,'ai_division_active_match'),division)


if __name__=='__main__':unittest.main()
