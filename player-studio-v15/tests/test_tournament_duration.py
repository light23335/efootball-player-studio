"""Per-event minutes survive exports, fixtures, START retries and save reloads.

Native input conversion is exercised separately by test_native_tournament_env_bridge;
the service fixtures here do not start the workshop or game.
"""
import copy,sqlite3,tempfile,types,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import tournament_rules as rules
import tournament_runtime as rt
import world_workspace as world


def definition(minutes=0):
    return rt.configuration([{'uuid':str(uuid.uuid4()),'name':'Duration cup','enabled':True,
        'team_ids':[1,2,3,4],'player_team_id':1,'match_minutes':minutes,
        'stages':[{'type':'league','advance_per_group':2},{'type':'knockout','advance':1}]}])[0]


class DurationValidationTests(unittest.TestCase):
    def test_legacy_projects_default_without_mutating_inputs_and_explicit_minutes_export(self):
        original=definition();original.pop('match_minutes')
        doc=world.default();doc['tournaments']=[original]
        self.assertEqual(world.normalize(doc)['tournaments'][0]['match_minutes'],0)
        self.assertNotIn('match_minutes',original)
        for minutes in (0,3,5,30):
            with self.subTest(minutes=minutes):
                edited=dict(original,match_minutes=minutes)
                local=world.normalize(dict(doc,tournaments=[edited]))['tournaments'][0]
                compiled=rt.configuration([local])[0]
                self.assertEqual(compiled['match_minutes'],minutes)
                self.assertEqual(rt.configuration([compiled]),[compiled])
                self.assertEqual(rt.export_selection([local],[],[local['uuid']],'full')[0]['match_minutes'],minutes)
                self.assertEqual(rt.export_selection([], [compiled], [], 'incremental')[0]['match_minutes'],minutes)

    def test_invalid_duration_is_rejected_in_both_workspace_and_runtime(self):
        original=definition()
        for invalid in (True,False,None,'5',5.0,-1,1,2,31):
            with self.subTest(value=invalid):
                edited=dict(original,match_minutes=invalid)
                with self.assertRaisesRegex(ValueError,'单场比赛时长'):rt.configuration([edited])
                doc=world.default();doc['tournaments']=[edited]
                with self.assertRaisesRegex(ValueError,'单场比赛时长'):world.normalize(doc)


class DurationLifecycleTests(unittest.TestCase):
    def setUp(self):
        from tournament_sim_test_support import patch_strength
        patch_strength(self)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'save.sqlite3'
        self.conn=sqlite3.connect(self.path);self.addCleanup(lambda:self.conn.close())
        self.conn.execute('create table meta(key primary key,value)')
        self.conn.execute('create table managed_cards(card_id,fingerprint,payload)')
        self.conn.execute('insert into meta values(?,?)',('unrelated-owned-training','keep-98765'))
        self.t=definition(3)
        self.document={'tournaments':[self.t]}
        self.service=rt.Service(lambda:self.document,self.temp.name,None)
        def build(conn,proto,team,diy,rng,cpu,*,simulation_only=False):
            identities=[{'id':1000*team+i,'serial':-2 if cpu else 0}for i in range(23)]
            roster=[{'gameplayer_id':ident,'parameters':[70]*147}for ident in identities]
            squad={'team_id':team,'player_list':[{'gameplayer_id':copy.deepcopy(ident)}for ident in identities],
                'squad_gameplan':{'match_plan_settings':{'order':list(range(23))+[255]*17}}}
            return {'player_list':roster,'squad_data':squad,'coach_data':{'coach_id':{'id':7,'serial':0}},
                    '_studio_tournament_squad':{'team_id':team}}
        self.service.generator=types.SimpleNamespace(build_club=build,repair_cpu_boosters=lambda *a:False)
        self.modules={'ziru_data':types.SimpleNamespace(vscom_opponent=lambda:{}),
            'cup16_mode':types.SimpleNamespace(game_id=lambda req:req.get('game_id')or(req.get('match_result')or{}).get('game_id')),
            'custom_stadium':types.SimpleNamespace(apply=lambda *a:None),
            'club_store':types.SimpleNamespace(default_uniforms=lambda team:[team*2,team*2+1])}
        self.addCleanup(patch.stopall);patch.dict('sys.modules',self.modules).start()
        patch.object(self.service,'repair_rentals').start();patch.object(self.service,'activate_coaching').start()
        self.logic=types.SimpleNamespace(conn=self.conn,templates={},responses={
            'CMD_START_GAME':{'uniform_list_home':{},'uniform_list_away':{}},
            'CMD_GET_EVENT_INFO':{'match_env':{'match_time':8,'weather':'FINE'}},
            'CMD_GET_EVENT_COMPE_INFO':{'match_env':{'match_time':8,'weather':'FINE'}}})

    def events(self,definitions=None):
        response={'result':'NOERR','event_list':[{'event_id':1120005,'ch_event_type':'CHALLENGE',
            'match_env':{'match_time':8,'weather':'FINE'}}]}
        return rt.project_events(self.logic,response,definitions or self.document['tournaments'])['event_list']

    def change(self,current,minutes):
        rt.put(self.conn,rt.PREFIX+self.t['uuid'],current)
        self.t=rt.configuration([dict(self.t,match_minutes=minutes)])[0]
        self.document['tournaments'][0]=self.t
        return rt.state(self.conn,self.t)

    def start(self,current):
        a=current['active']
        return self.service.start(self.logic,self.t,current,{'game_id':a['game_id'],'side':a['player_side']})

    def test_separate_events_and_detail_responses_use_own_minutes(self):
        other=definition(5)
        rows=self.events([self.t,other])
        self.assertEqual([r['match_env']['match_time']for r in rows],[3,5])
        self.assertTrue(all(r['match_env']['weather']=='FINE'for r in rows))
        for command in ('CMD_GET_EVENT_INFO','CMD_GET_EVENT_COMPE_INFO'):
            out=self.service.handle(self.logic,command,{'event_id':rt.event_id(self.t)},lambda *a:self.fail('native fallback'))
            self.assertEqual(out['match_env']['match_time'],3)
            self.assertEqual(out['match_env']['weather'],'FINE')
            self.assertEqual(self.logic.responses[command]['match_env']['match_time'],8)

    def test_duration_edit_preserves_scores_points_receipts_and_other_mode(self):
        current=rt.state(self.conn,self.t)
        fixture=rules.due(current)[0];rules.record(current,fixture['id'],2,1)
        current['receipts']={'old-game':{'result':'NOERR'}}
        before=copy.deepcopy(current)
        changed=self.change(current,5)
        for key in ('run_id','seed','fixtures','stage_index','stage_history','receipts'):
            self.assertEqual(changed[key],before[key],key)
        for group in range(len(before['groups'])):
            self.assertEqual(rules.standings(changed,group),rules.standings(before,group))
        self.assertEqual(changed['definition']['match_minutes'],5)
        self.assertFalse(self.conn.execute("select 1 from meta where key like '%:backup:%'").fetchone())
        self.assertEqual(self.conn.execute('select value from meta where key=?',('unrelated-owned-training',)).fetchone()[0],'keep-98765')

    def test_unstarted_preparation_refreshes_time_without_redrawing_squads(self):
        current=rt.state(self.conn,self.t);active=self.service.prepare(self.conn,self.t,current,{})
        before=copy.deepcopy(active);changed=self.change(current,5)
        active=self.service.prepare(self.conn,self.t,changed,{})
        self.assertEqual(active['game_id'],before['game_id'])
        self.assertEqual(active['home'],before['home']);self.assertEqual(active['away'],before['away'])
        self.assertEqual(active['match_env']['match_time'],5)
        self.start(changed);self.assertTrue(active['started'])
        self.assertEqual(active['match_env']['match_time'],5)

    def test_first_start_refreshes_unissued_environment_without_prepare_retry(self):
        current=rt.state(self.conn,self.t);self.service.prepare(self.conn,self.t,current,{})
        changed=self.change(current,5)
        self.start(changed)
        self.assertEqual(changed['active']['match_env']['match_time'],5)

    def test_started_fixture_keeps_issued_time_through_reload_event_detail_and_start_retry(self):
        self.events();current=rt.state(self.conn,self.t)
        active=self.service.prepare(self.conn,self.t,current,{});issued=self.start(current)
        changed=self.change(current,5);game=active['game_id']
        rt.put(self.conn,rt.PREFIX+self.t['uuid'],changed);self.conn.commit();self.conn.close()
        self.conn=sqlite3.connect(self.path);self.logic.conn=self.conn
        current=rt.state(self.conn,self.t)
        self.assertEqual(current['active']['match_env']['match_time'],3)
        self.assertEqual(self.events()[0]['match_env']['match_time'],3)
        for command in ('CMD_GET_EVENT_INFO','CMD_GET_EVENT_COMPE_INFO'):
            out=self.service.handle(self.logic,command,{'event_id':rt.event_id(self.t)},lambda *a:{})
            self.assertEqual(out['match_env']['match_time'],3)
        self.assertEqual(self.start(current),issued)
        self.assertEqual(current['active']['game_id'],game)
        self.assertEqual(current['active']['match_env']['match_time'],3)

    def test_finished_match_uses_new_time_only_for_next_fixture(self):
        current=rt.state(self.conn,self.t);active=self.service.prepare(self.conn,self.t,current,{})
        self.start(current);current=self.change(current,5);old_game=active['game_id']
        zero={'score_1st':0,'score_2nd':0,'score_ex1st':0,'score_ex2nd':0,'score_pk':0}
        scores=[copy.deepcopy(zero),copy.deepcopy(zero)]
        scores[0 if active['player_side']=='HOME'else 1]['score_1st']=2
        modules={'cup16_mode':types.SimpleNamespace(_scores=lambda req:[sum(r[k]for k in('score_1st','score_2nd'))for r in req['score']],game_id=lambda req:req['match_result']['game_id']),
            'cup16_service':types.SimpleNamespace(Cup16Service=types.SimpleNamespace(_result_reply=lambda *a:{'game_end_result':{'match_result':{'player_data':{}}}})),
            'vscom_result':types.SimpleNamespace(outcome=lambda *a:'WIN'),
            'ai_match_runtime':types.SimpleNamespace(deactivate=lambda *a:None,deactivate_for_match=lambda *a:False)}
        with patch.dict('sys.modules',modules):
            self.service.finish(self.logic,self.t,current,{'score':scores,'match_result':{'game_id':old_game,'pk_flag':'NO'}})
        self.assertNotIn('active',current)
        next_active=self.service.prepare(self.conn,self.t,current,{})
        self.assertNotEqual(next_active['game_id'],old_game)
        self.assertEqual(next_active['match_env']['match_time'],5)

    def test_native_default_is_preserved_for_an_issued_match_and_can_be_reselected(self):
        self.t=dict(self.t,match_minutes=0);self.document['tournaments'][0]=self.t
        self.assertEqual(self.events()[0]['match_env']['match_time'],8)
        current=rt.state(self.conn,self.t);self.service.prepare(self.conn,self.t,current,{})
        self.start(current);changed=self.change(current,5)
        self.assertEqual(changed['active']['match_env']['match_time'],8)
        changed['active'].pop('started');changed['active'].pop('start_reply')
        self.service.prepare(self.conn,self.t,changed,{})
        self.assertEqual(changed['active']['match_env']['match_time'],5)
        changed=self.change(changed,0);self.service.prepare(self.conn,self.t,changed,{})
        self.assertEqual(changed['active']['match_env']['match_time'],8)

    def test_legacy_started_explicit_minutes_migrate_before_config_changes(self):
        current=rt.state(self.conn,self.t);active=self.service.prepare(self.conn,self.t,current,{})
        self.start(current);active['match_env'].pop('match_time')
        changed=self.change(current,5)
        self.assertEqual(changed['active']['match_env']['match_time'],3)
        self.assertEqual(changed['definition']['match_minutes'],5)


if __name__=='__main__':unittest.main()
