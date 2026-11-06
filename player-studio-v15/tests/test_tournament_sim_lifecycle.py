"""Real ClubGenerator -> saved squad -> native/CPU result, isolated SQLite only."""
import copy
import json
import types
import unittest
import uuid
from unittest.mock import patch

import tournament_rules as rules
import tournament_runtime as runtime
import tournament_simulation as model
from test_tournament_sim_strength import generator_fixture


class SimulationLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.generator,self.db,self.document,self.proto=generator_fixture()
        self.addCleanup(self.db.close)
        originals=list(self.db.execute('select payload from managed_cards'))
        for team in(122,123,124):
            for raw, in originals:
                card=json.loads(raw);card['gameplayer_id']['id']+=team*10000
                card['initial_base_team_id']=team;encoded=json.dumps(card)
                self.db.execute('insert into managed_cards values(?,?,?)',
                                (str(card['gameplayer_id']['id']),encoded,encoded))
        coach=copy.deepcopy(self.document['division_squads']['coaches'][0]['payload'])
        self.db.execute('insert into coaches values(?,?,?)',(coach['coach_id']['id'],0,json.dumps(coach)))
        self.definition=runtime.configuration([dict(uuid=str(uuid.uuid4()),name='Saved simulation',enabled=True,
            team_ids=[121,122,123,124],player_team_id=121,
            stages=[dict(type='league',advance_per_group=2),dict(type='knockout')])])[0]
        self.document['tournaments']=[self.definition]
        self.service=runtime.Service(lambda:self.document,'.',self.generator)
        self.current=rules.start(self.definition,71)
        self.logic=types.SimpleNamespace(conn=self.db,templates={},responses={
            'CMD_START_GAME':{'uniform_list_home':{},'uniform_list_away':{}}})
        modules={'ziru_data':types.SimpleNamespace(vscom_opponent=lambda:copy.deepcopy(self.proto)),
                 'ai_match_manager':types.SimpleNamespace(prepare_strategies=lambda *a:None),
                 'custom_stadium':types.SimpleNamespace(apply=lambda *a:None),
                 'club_store':types.SimpleNamespace(default_uniforms=lambda team:[team])}
        self.addCleanup(patch.stopall)
        patch.dict('sys.modules',modules).start()
        patch.object(self.service,'activate_coaching').start()
        patch.object(self.service,'reinforcements',return_value=[]).start()

    def start(self):
        active=self.service.prepare(self.db,self.definition,self.current,{})
        reply=self.service.start(self.logic,self.definition,self.current,
                                 dict(game_id=active['game_id'],side=active['player_side']))
        fixture=next(f for f in self.current['fixtures']if f['id']==active['fixture_id'])
        return active,fixture,reply

    def knockout(self,**options):
        definition=dict(self.definition,team_ids=[122,123],player_team_id=122,
                        stages=[dict(type='knockout',**options)])
        self.current=rules.start(definition,91)
        return rules.due(self.current)[0]

    def test_start_freezes_accepted_plan_and_exact_native_roster_then_restart_keeps_it(self):
        active=self.service.prepare(self.db,self.definition,self.current,{})
        plan=copy.deepcopy(active[active['player_side'].lower()]['squad_data'])
        order=plan['squad_gameplan']['match_plan_settings']['order'];order[1],order[12]=order[12],order[1]
        self.service.save_plan(self.db,self.definition,self.current,{'special_squad_data':{'squad_data':plan}})
        active,fixture,issued=self.start();contract=fixture['simulation_v1']
        self.assertTrue(contract['frozen'])
        own=contract['teams'][active['player_side'].lower()]
        self.assertEqual(own['squad_data']['squad_gameplan'],plan['squad_gameplan'])
        self.assertEqual([p['parameters'][:147]for p in own['player_list']],
                         [p['parameters']for p in issued['squad_data_home']['player_list']])
        self.assertEqual(set(contract['ratings']['home'])-{'audit'},set(model.RATING_KEYS))
        self.assertEqual(set(contract['seeds']),{'lineup','regulation','extra_time','penalties'})
        self.assertEqual(len(set(contract['seeds'].values())),4)
        before=json.loads(json.dumps(contract))
        runtime.put(self.db,runtime.PREFIX+self.definition['uuid'],self.current)
        self.document['preview_boosters']['7']['effects']['20']=99
        self.definition=dict(self.definition,difficulty='LEGEND')
        self.document['tournaments']=[self.definition]
        self.current=runtime.state(self.db,self.definition)
        self.service.prepare(self.db,self.definition,self.current,{})
        resumed=self.service.start(self.logic,self.definition,self.current,
                                   dict(game_id=active['game_id'],side=active['player_side']))
        self.assertEqual(resumed,issued)
        self.assertEqual(self.current['fixtures'][fixture['id']-1]['simulation_v1'],before)
        self.assertIn('已关闭',self.service.save_plan(self.db,self.definition,self.current,
            {'special_squad_data':{'squad_data':plan}})['studio_notice'])

    def test_cpu_uses_real_23_players_and_persists_every_rating_without_redraw(self):
        fixture=next(f for f in rules.due(self.current)if 121 not in(f['home'],f['away']))
        before=list(self.db.execute('select * from managed_cards'))
        self.service.simulate_fixture(self.db,self.current,fixture)
        contract=fixture['simulation_v1']
        for side in('home','away'):
            team=contract['teams'][side]
            self.assertEqual(len(team['player_list']),23)
            self.assertEqual(len({p['gameplayer_id']['id']for p in team['player_list']}),23)
            self.assertEqual(len(team['squad_data']['squad_gameplan']['formation'][0]['formation_offensive']),11)
            self.assertEqual(len(team['squad_data']['squad_gameplan']['formation'][0]['formation_defensive']),11)
            self.assertTrue(all(p['level_info']['level']==p['level_info']['level_limit']for p in team['player_list']))
        self.assertEqual(list(self.db.execute('select * from managed_cards')),before)
        saved=json.loads(json.dumps(self.current));old=copy.deepcopy(saved['fixtures'])
        with patch.object(model,'sample_period',side_effect=AssertionError('settled result redrawn')):
            self.service.simulate_fixture(self.db,saved,saved['fixtures'][fixture['id']-1])
        self.assertEqual(saved['fixtures'],old)

    def test_failed_first_start_keeps_plan_editable_and_only_success_publishes_frozen_contract(self):
        active=self.service.prepare(self.db,self.definition,self.current,{})
        fixture=next(f for f in self.current['fixtures']if f['id']==active['fixture_id'])
        self.logic.responses['CMD_START_GAME']['uniform_list_home']=None
        with self.assertRaisesRegex(ValueError,'球衣字段'):
            self.service.start(self.logic,self.definition,self.current,dict(game_id=active['game_id']))
        self.assertFalse(fixture['simulation_v1']['frozen']);self.assertFalse(active['started'])
        plan=copy.deepcopy(active[active['player_side'].lower()]['squad_data'])
        plan['squad_gameplan']['match_plan_settings']['order'][1:3]=[2,1]
        self.service.save_plan(self.db,self.definition,self.current,{'special_squad_data':{'squad_data':plan}})
        self.logic.responses['CMD_START_GAME']['uniform_list_home']={}
        active,fixture,reply=self.start()
        self.assertTrue(fixture['simulation_v1']['frozen'])
        self.assertEqual(reply['squad_data_home']['squad_gameplan'],plan['squad_gameplan'])

    def test_real_snapshots_follow_both_physical_sides_and_home_effect(self):
        for side in('home','away'):
            with self.subTest(side=side):
                definition=runtime.configuration([dict(self.definition,team_ids=[121,122],
                    stages=[dict(type='knockout',neutral_final=False)])])[0]
                self.current=rules.start(definition,55);self.definition=definition
                fixture=rules.due(self.current)[0]
                fixture.update(home=121 if side=='home'else 122,away=122 if side=='home'else 121)
                active,fixture,reply=self.start();contract=fixture['simulation_v1']
                self.assertEqual(active['player_side'],side.upper())
                self.assertEqual(contract['teams'][side]['squad_data']['team_id'],121)
                self.assertEqual(reply['squad_data_home']['team_id'],121)
                self.assertEqual(reply['squad_data_away']['team_id'],122)
                self.assertGreater(contract['expected']['modifiers']['home']['home_log'],0)
                self.assertLess(contract['expected']['modifiers']['away']['home_log'],0)

    def test_explicit_prestart_control_team_change_reissues_native_identity_but_keeps_edition_and_seeds(self):
        active=self.service.prepare(self.db,self.definition,self.current,{})
        fixture=next(f for f in self.current['fixtures']if f['id']==active['fixture_id'])
        seeds=copy.deepcopy(fixture['simulation_v1']['seeds']);run=self.current['run_id']
        opponent=fixture['away']if fixture['home']==121 else fixture['home']
        runtime.put(self.db,runtime.PREFIX+self.definition['uuid'],self.current)
        self.definition=dict(self.definition,player_team_id=opponent)
        self.document['tournaments']=[self.definition]
        self.current=runtime.state(self.db,self.definition)
        active=self.service.prepare(self.db,self.definition,self.current,{})
        self.assertEqual(self.current['run_id'],run)
        self.assertEqual(fixture['simulation_v1']['seeds'],seeds)
        own=active[active['player_side'].lower()]
        self.assertEqual(own['squad_data']['team_id'],opponent)
        self.assertTrue(all(p['gameplayer_id']['serial']==0 for p in own['player_list']))
        cpu=active['away'if active['player_side']=='HOME'else'home']
        self.assertTrue(all(p['gameplayer_id']['serial']!=0 for p in cpu['player_list']))

    def test_knockout_extra_time_then_real_penalty_log_and_no_extra_time_option(self):
        for allow in(False,True):
            with self.subTest(allow=allow):
                fixture=self.knockout(extra_time=allow)
                with patch.object(model,'sample_period',return_value={'score':[0,0],'xg':[1,1]})as sample:
                    self.service.simulate_fixture(self.db,self.current,fixture)
                self.assertEqual(sample.call_count,2 if allow else 1)
                if allow:self.assertEqual(sample.call_args.kwargs['minutes'],30)
                contract=fixture['simulation_v1'];shootout=contract['result']['shootout']
                self.assertTrue(shootout['kicks'])
                self.assertNotEqual(*shootout['score'])
                for kick in shootout['kicks']:
                    own=kick['side'];opponent='away'if own=='home'else'home'
                    starters=[p for p in contract['ratings'][own]['audit']['players']if p['is_starter']]
                    allowed={tuple(p['gameplayer_id'][k]for k in('id','serial'))for p in starters}
                    self.assertIn(tuple(kick['taker']['gameplayer_id'][k]for k in('id','serial')),allowed)
                    opposing=contract['ratings'][opponent]['audit']
                    keeper_slot=next(r['slot']for r in opposing['contributions']['goalkeeping']if r['role']=='GK')
                    keeper=next(p for p in opposing['players']if p['is_starter']and p['order']==keeper_slot)
                    self.assertEqual(kick['keeper']['gameplayer_id'],keeper['gameplayer_id'])
                    self.assertEqual(kick['taker_source'],'actual_starting_xi')
                self.assertEqual(fixture['penalties'],shootout['score'])
                self.assertTrue(self.current['completed'])

    def test_two_legs_aggregate_away_goals_and_extra_time_away_goals(self):
        for away_extra,needs_pk in((False,True),(True,False)):
            with self.subTest(away_extra=away_extra):
                first=self.knockout(legs=2,away_goals=True,away_goals_extra_time=away_extra)
                rules.record(self.current,first['id'],1,1)
                second=rules.due(self.current)[0]
                with patch.object(model,'sample_period',side_effect=[{'score':[1,1],'xg':[1,1]},
                                                                   {'score':[1,1],'xg':[.3,.3]}]):
                    self.service.simulate_fixture(self.db,self.current,second)
                self.assertEqual(second['score'],[2,2]);self.assertEqual(second['extra_time_score'],[1,1])
                self.assertEqual(second['penalties']is not None,needs_pk)
        first=self.knockout(legs=2,away_goals=True)
        rules.record(self.current,first['id'],2,1)
        second=rules.due(self.current)[0]
        with patch.object(model,'sample_period',return_value={'score':[1,0],'xg':[1,1]})as sample:
            self.service.simulate_fixture(self.db,self.current,second)
        self.assertEqual(sample.call_count,1);self.assertIsNone(second['penalties'])

    def test_neutral_and_home_orientation_reach_model_and_version_is_pinned(self):
        fixture=self.knockout(neutral_final=True)
        self.service.simulate_fixture(self.db,self.current,fixture)
        result=fixture['simulation_v1']
        self.assertEqual(result['expected']['modifiers']['home']['home_log'],0)
        self.assertEqual(result['expected']['modifiers']['away']['home_log'],0)
        self.assertEqual(result['model_version'],self.current['simulation_policy_v1']['model_version'])
        old=copy.deepcopy(self.current['fixtures'])
        self.current['simulation_policy_v1']['model_version']='future-version'
        self.service.simulate_fixture(self.db,self.current,fixture)
        self.assertEqual(self.current['fixtures'],old)
        fresh=self.knockout();self.current['simulation_policy_v1']={'model_version':'unavailable'}
        with self.assertRaisesRegex(ValueError,'算法暂不可用'):
            self.service.simulate_fixture(self.db,self.current,fresh)
        self.assertFalse(fresh['played'])

    def test_prior_form_counts_only_settled_appearances_and_never_stacks_modifier(self):
        fixture=rules.due(self.current)[0];team=fixture['home']
        self.current['fixtures'].extend(dict(id=100+i,home=team,away=999,played=True,
            score=[2,0],bye=False)for i in range(7))
        self.current['fixtures'].append(dict(id=200,home=team,away=None,played=True,score=[0,0],bye=True))
        form=runtime.prior_form(self.current,team,fixture)
        self.assertEqual(form,{'win_streak':7,'nonwin_streak':0})
        self.assertEqual(model.form_modifier(form),model.form_modifier(['W']*3))
        self.current['fixtures'].append(dict(id=201,home=999,away=team,played=True,score=[0,0]))
        self.assertEqual(runtime.prior_form(self.current,team,fixture),{'win_streak':0,'nonwin_streak':1})

    def test_contextless_cpu_progress_is_rejected_and_legacy_settled_rows_unchanged(self):
        pending=rules.due(self.current)
        own=next(f for f in pending if 121 in(f['home'],f['away']))
        rules.record(self.current,own['id'],1,0)
        old=copy.deepcopy(own)
        with self.assertRaisesRegex(ValueError,'真实锦标赛阵容上下文'):runtime.next_fixture(self.current)
        self.assertEqual(own,old)
        self.service.next_fixture(self.db,self.current)
        self.assertEqual(own,old);self.assertNotIn('simulation_v1',own)

    def test_real_native_finish_keeps_submitted_extra_time_and_penalties_without_model_rewrite(self):
        fixture=self.knockout()
        self.definition=self.current['definition'];self.document['tournaments']=[self.definition]
        active,fixture,reply=self.start()
        request={'match_result':{'game_id':active['game_id'],'pk_flag':'YES'},
                 'score':[dict(score_1st=1,score_2nd=0,score_ex1st=1,score_ex2nd=0,score_pk=4),
                          dict(score_1st=1,score_2nd=0,score_ex1st=0,score_ex2nd=1,score_pk=5)]}
        calls=[]
        def serialize(logic,received,config,home,away,outcome):
            calls.append([home,away]);return {'game_end_result':{'match_result':{'player_data':{}}}}
        modules={'cup16_mode':types.SimpleNamespace(
                    _scores=lambda req:[sum(row[k]for k in('score_1st','score_2nd','score_ex1st','score_ex2nd'))for row in req['score']],
                    game_id=lambda req:req['match_result']['game_id']),
                 'cup16_service':types.SimpleNamespace(Cup16Service=types.SimpleNamespace(_result_reply=serialize)),
                 'vscom_result':types.SimpleNamespace(outcome=lambda *a:'LOSE'),
                 'ai_match_runtime':types.SimpleNamespace(deactivate=lambda *a:None,deactivate_for_match=lambda *a:False)}
        with patch.dict('sys.modules',modules),patch.object(model,'sample_period',side_effect=AssertionError('native rewritten')):
            out=self.service.finish(self.logic,self.definition,self.current,request)
            before=copy.deepcopy(self.current)
            self.assertEqual(self.service.finish(self.logic,self.definition,self.current,request),out)
        self.assertEqual(calls,[[2,2]])
        self.assertEqual(self.current,before)
        self.assertEqual(fixture['score'],[2,2]);self.assertEqual(fixture['extra_time_score'],[1,1])
        self.assertEqual(fixture['penalties'],[4,5])
        self.assertEqual(fixture['simulation_v1']['result']['final_score'],[2,2])
        self.assertEqual(fixture['simulation_v1']['result']['raw_score'],[1,1])
        self.assertEqual(fixture['simulation_v1']['result']['source'],'native')

    def test_real_cpu_progresses_league_direct_bypass_playoffs_and_knockout_after_reload(self):
        definition=runtime.configuration([dict(self.definition,stages=[dict(type='league',advance_per_group=1,playoff_per_group=2),
            dict(type='playoff',advance=1),dict(type='knockout')])])[0]
        self.current=rules.start(definition,41);player=definition['player_team_id'];old_rows={}
        while not self.current['completed']:
            fixture=self.service.next_fixture(self.db,self.current)
            if fixture is None:break
            score=[3,0]if fixture['home']==player else[0,3]
            rules.record(self.current,fixture['id'],*score)
            for row in self.current['fixtures']:
                if row['id']in old_rows:self.assertEqual(row,old_rows[row['id']])
            old_rows.update({row['id']:json.loads(json.dumps(row))for row in self.current['fixtures']if row['played']})
            runtime.put(self.db,runtime.PREFIX+definition['uuid'],self.current)
            self.current=runtime.state(self.db,definition)
        self.assertEqual(self.current['champion'],player)
        self.assertEqual(self.current['stage_index'],2)
        playoffs=[f for f in self.current['fixtures']if f['stage']==1]
        self.assertTrue(playoffs);self.assertTrue(all(f['played']for f in playoffs))
        self.assertTrue(all(player not in(f['home'],f['away'])for f in playoffs))
        cpu=[f for f in self.current['fixtures']if f.get('simulation_v1',{}).get('settled')]
        self.assertTrue(cpu)
        self.assertTrue(all(f['simulation_v1']['source']=='cpu'for f in cpu))


if __name__=='__main__':unittest.main()
