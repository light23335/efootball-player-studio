"""Edits survive native re-entry, process exit and the next fixture."""
import copy,json,sqlite3,tempfile,types,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import tournament_runtime as rt
import tournament_rules as rules
from tournament_squads import bind_team_identity,STYLES


class PlanPersistenceTests(unittest.TestCase):
    def setUp(self):
        from tournament_sim_test_support import patch_strength
        patch_strength(self)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'save.sqlite3'
        self.db=sqlite3.connect(self.path);self.addCleanup(lambda:self.db.close())
        self.db.execute('create table meta(key primary key,value)')
        self.db.execute('create table managed_cards(card_id,fingerprint,payload)')
        self.db.execute('create table protected_training(id primary key,exp)')
        self.db.execute('insert into protected_training values(1,98765)')
        self.coaches=[{'payload':{'coach_id':{'id':8+i,'serial':23+i},**{s:88 for s in STYLES}}}for i in range(2)]
        self.calls=[]
        def build(conn,template,team,diy,rng,cpu,*,simulation_only=False):
            self.calls.append((team,cpu))
            roster=[{'gameplayer_id':{'id':team*1000+i,'serial':810000001+i if cpu else 0},'parameters':[70]*147}for i in range(23)]
            squad={'team_id':team,'player_list':[{'gameplayer_id':copy.deepcopy(p['gameplayer_id'])}for p in roster],
                'coach':[{'coach_id':copy.deepcopy(self.coaches[0]['payload']['coach_id'])}],
                'squad_gameplan':{'formation':[{'team_style':0,'formation_offensive':[{'role':0,'position_x':3,'position_y':52}]}],
                    'match_plan_settings':{'order':list(range(23))+[255]*17,'captain':0}}}
            return {'player_list':roster,'squad_data':squad,'coach_data':copy.deepcopy(self.coaches[0]['payload']),
                'team_data':{'base_team_id':7,'team_name':'Spain','team_name_short':'ESP'},
                '_studio_tournament_squad':{'team_id':team,'style':STYLES[0]}}
        generator=types.SimpleNamespace(build_club=build,owned_coaches=lambda c:self.coaches,
            repair_rental_boosters=lambda *a:False,repair_cpu_boosters=lambda *a:False,payload_rating=lambda *a:104)
        self.definition=rt.configuration([{'uuid':str(uuid.uuid4()),'name':'国家队','enabled':True,
            'team_ids':[52,7,14,18],'player_team_id':52,
            'stages':[{'type':'league','advance_per_group':2},{'type':'knockout','advance':1}]}])[0]
        self.service=rt.Service(lambda:{'tournaments':[self.definition],'tournament_team_names':{'52':'中国','7':'西班牙'}},self.tmp.name,generator)
        self.current=rules.start(self.definition,17)
        self.modules={'ziru_data':types.SimpleNamespace(vscom_opponent=lambda:{}),
            'club_store':types.SimpleNamespace(default_uniforms=lambda team:[team*16384,team*16384+1]),
            'custom_stadium':types.SimpleNamespace(apply=lambda *a:None)}
        self.logic=types.SimpleNamespace(conn=self.db,responses={'CMD_START_GAME':{'uniform_list_home':{},'uniform_list_away':{}}},templates={})
        self.addCleanup(patch.stopall);patch.dict('sys.modules',self.modules).start()
        patch.object(self.service,'activate_coaching').start()

    def enter(self):return self.service.special(self.db,self.definition,self.current,{})

    def edit(self):
        plan=copy.deepcopy(self.enter()['squad_data'])
        plan['squad_gameplan']['match_plan_settings'].update(order=[0,2,1,*range(3,23)]+[255]*17,captain=2)
        plan['squad_gameplan']['formation'][0]['formation_offensive'][0]['position_y']=51
        plan['coach']=[{'coach_id':copy.deepcopy(self.coaches[1]['payload']['coach_id'])}]
        self.assertEqual(self.service.save_plan(self.db,self.definition,self.current,{'special_squad_data':{'squad_data':plan}})['result'],'NOERR')
        return plan

    def test_changed_coach_order_duties_and_positions_survive_reentry_disk_and_start(self):
        plan=self.edit();game=self.current['active']['game_id']
        rt.put(self.db,rt.PREFIX+self.definition['uuid'],self.current);self.db.commit();self.db.close()
        self.db=sqlite3.connect(self.path);self.logic.conn=self.db
        self.current=rt.state(self.db,self.definition)
        self.assertEqual(self.enter()['squad_data'],plan)
        out=self.service.start(self.logic,self.definition,self.current,{'game_id':game})
        self.assertEqual(out['squad_data_home']['coach'],self.coaches[1]['payload'])
        self.assertEqual(out['squad_data_home']['squad_gameplan'],plan['squad_gameplan'])
        self.assertEqual(list(self.db.execute('select *from protected_training')),[(1,98765)])

    def test_next_fixture_and_home_away_swap_reuse_player_plan_but_draw_new_cpu(self):
        plan=self.edit();first=self.current['active'];run=self.current['run_id']
        f=next(f for f in self.current['fixtures']if f['id']==first['fixture_id'])
        rt.remember_plan(self.current,first)
        rules.record(self.current,f['id'],1,0);self.current.pop('active')
        next_f=self.service.next_fixture(self.db,self.current)
        if next_f['home']==52:next_f['home'],next_f['away']=next_f['away'],next_f['home']
        self.assertEqual(self.enter()['squad_data'],plan)
        self.assertEqual(self.current['run_id'],run)
        self.assertEqual(sum(team==52 and not cpu for team,cpu in self.calls),1)
        # Two player opponents plus both real squads in the intervening CPU fixture.
        self.assertEqual(sum(cpu for team,cpu in self.calls),4)
        out=self.service.start(self.logic,self.definition,self.current,{'game_id':self.current['active']['game_id'],'side':'AWAY'})
        self.assertEqual(out['squad_data_home']['coach'],self.coaches[1]['payload'])
        self.assertEqual(out['squad_data_home']['team_id'],52)
        self.assertEqual(out['uniform_list_away']['base_team_id'],52)

    def test_team_switch_keeps_separate_plans_without_resetting_results(self):
        plan=self.edit();run=self.current['run_id']
        rt.put(self.db,rt.PREFIX+self.definition['uuid'],self.current)
        changed=dict(self.definition,player_team_id=7)
        switched=rt.state(self.db,changed)
        self.assertEqual(switched['run_id'],run);self.assertNotIn('active',switched)
        self.assertEqual(switched['team_plans_v1']['52']['squad'],plan)
        self.assertNotIn('7',switched['team_plans_v1'])

    def test_real_finish_route_carries_edited_plan_into_next_match(self):
        plan=self.edit();a=self.current['active'];a['started']=True
        zero={'score_1st':0,'score_2nd':0,'score_ex1st':0,'score_ex2nd':0,'score_pk':0}
        rows=[copy.deepcopy(zero),copy.deepcopy(zero)]
        rows[0 if a['player_side']=='HOME'else 1]['score_1st']=2
        modules={'cup16_mode':types.SimpleNamespace(_scores=lambda req:[sum(r[k]for k in('score_1st','score_2nd'))for r in req['score']],game_id=lambda req:req['match_result']['game_id']),
            'cup16_service':types.SimpleNamespace(Cup16Service=types.SimpleNamespace(_result_reply=lambda *a:{'game_end_result':{'match_result':{'player_data':{}}}})),
            'vscom_result':types.SimpleNamespace(outcome=lambda *a:'WIN'),
            'ai_match_runtime':types.SimpleNamespace(deactivate=lambda *a:None,deactivate_for_match=lambda *a:False)}
        with patch.dict('sys.modules',modules):
            self.service.finish(self.logic,self.definition,self.current,{'score':rows,'match_result':{'game_id':a['game_id'],'pk_flag':'NO'}})
        self.assertNotIn('active',self.current)
        self.assertEqual(self.current['team_plans_v1']['52']['squad'],plan)
        self.assertEqual(self.enter()['squad_data'],plan)

    def test_country_team_against_spain_and_other_opponents_keeps_physical_kits(self):
        for side in ('HOME','AWAY'):
            for opponent in (7,14):
                with self.subTest(side=side,opponent=opponent):
                    self.current=rules.start(self.definition,17)
                    f=rt.next_fixture(self.current)
                    f.update(home=52 if side=='HOME'else opponent,away=opponent if side=='HOME'else 52)
                    self.enter();a=self.current['active']
                    own=a[side.lower()]
                    self.assertEqual(own['team_data']['base_team_id'],52)
                    self.assertEqual(own['team_data']['team_name'],'中国')
                    out=self.service.start(self.logic,self.definition,self.current,{'game_id':a['game_id'],'side':side})
                    self.assertEqual(out['squad_data_home']['team_id'],52)
                    self.assertEqual(out['uniform_list_'+side.lower()]['uniform_list'],[52*16384,52*16384+1])
                    self.assertEqual(out['uniform_list_'+('away'if side=='HOME'else'home')]['base_team_id'],opponent)

    def test_partial_native_patch_keeps_other_gameplan_settings(self):
        plan=self.edit()
        self.service.save_plan(self.db,self.definition,self.current,{'special_squad_data':{'squad_data':{
            'squad_gameplan':{'match_plan_settings':{'captain':3}}}}})
        plan['squad_gameplan']['match_plan_settings']['captain']=3
        self.assertEqual(self.enter()['squad_data'],plan)

    def test_unowned_coach_rejected_without_mutating_existing_plan(self):
        self.edit();before=copy.deepcopy(self.current)
        with self.assertRaisesRegex(ValueError,'已持有'):
            self.service.save_plan(self.db,self.definition,self.current,{'special_squad_data':{'squad_data':{'coach':[{'coach_id':{'id':9,'serial':999}}]}}})
        self.assertEqual(self.current,before)

    def test_cached_country_identity_cannot_fall_back_to_spain(self):
        self.enter();a=self.current['active'];own=a[a['player_side'].lower()]
        own['team_data']={'base_team_id':7,'team_name':'Spain','team_name_short':'ESP'}
        self.enter()
        self.assertEqual(own['team_data']['base_team_id'],52)
        self.assertEqual(own['team_data']['team_name'],'中国')
        self.assertEqual(own['squad_data']['team_id'],52)


if __name__=='__main__':unittest.main()
