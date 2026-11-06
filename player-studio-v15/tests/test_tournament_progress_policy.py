"""Changes to one competition never clear another mode's saved data."""
import copy,json,sqlite3,unittest,uuid
import tournament_rules as rules
import tournament_runtime as runtime

class TournamentProgressPolicyTests(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:');self.addCleanup(self.conn.close)
        self.conn.execute('create table meta(key text primary key,value text)')
        self.definition=runtime.configuration([{'uuid':str(uuid.uuid4()),'name':'Cup','enabled':True,
            'team_ids':list(range(1,9)),'player_team_id':1,'difficulty':'HARD',
            'stages':[{'type':'league','advance_per_group':2},{'type':'knockout','advance':1}]}])[0]
        self.current=runtime.state(self.conn,self.definition)
        f=self.current['fixtures'][0];rules.record(self.current,f['id'],2,1)
        self.current['receipts']={'game-before-update':{'result':'NOERR'}}
        self.current['reinforcements']={'rentals':[{'card_id':7}],'chances':3}
        runtime.put(self.conn,runtime.PREFIX+self.definition['uuid'],self.current)
        self.other_keys={'unrelated-mode':{'wins':12},'owned-player-training':{'exp':34999},
                        runtime.PREFIX+str(uuid.uuid4()):{'run_id':'other-cup','played':6}}
        for k,v in self.other_keys.items():runtime.put(self.conn,k,v)
        self.conn.commit()

    def assert_progress(self,result):
        for key in ('run_id','seed','fixtures','receipts','stage_index','stage_history','reinforcements'):
            self.assertEqual(result[key],self.current[key],key)
        for k,v in self.other_keys.items():self.assertEqual(runtime.get(self.conn,k),v)
        self.assertFalse(self.conn.execute("select 1 from meta where key like ?",(runtime.PREFIX+self.definition['uuid']+':backup:%',)).fetchone())

    def test_control_team_and_difficulty_keep_the_same_edition_results_and_ownership(self):
        changed=copy.deepcopy(self.definition);changed.update(player_team_id=2,difficulty='LEGEND')
        result=runtime.state(self.conn,changed);self.assert_progress(result)
        self.assertEqual(result['definition']['player_team_id'],2);self.assertEqual(result['difficulty'],'LEGEND')

    def test_names_coaching_diy_and_participant_order_are_not_structure_changes(self):
        changed=copy.deepcopy(self.definition);changed.update(name='New title',auto_coaching=False,include_diy=False)
        changed['team_ids'].reverse()
        for stage in changed['stages']:stage.update(uuid=str(uuid.uuid4()),name='New phase title')
        result=runtime.state(self.conn,changed);self.assert_progress(result)
        self.assertEqual([s['uuid']for s in result['definition']['stages']],[s['uuid']for s in self.definition['stages']])

    def test_unstarted_match_plan_changes_with_controller_without_clearing_competition(self):
        self.current['active']={'started':False,'game_id':77,'own_plan':{'team_id':1}}
        runtime.put(self.conn,runtime.PREFIX+self.definition['uuid'],self.current)
        changed=dict(self.definition,player_team_id=2)
        result=runtime.state(self.conn,changed);self.assert_progress(result);self.assertNotIn('active',result)

    def test_interrupted_match_keeps_its_actual_side_then_switches_controller_after_settlement(self):
        self.current['active']={'started':True,'game_id':77,'player_side':'AWAY','fixture_id':9}
        runtime.put(self.conn,runtime.PREFIX+self.definition['uuid'],self.current)
        changed=dict(self.definition,player_team_id=2)
        result=runtime.state(self.conn,changed);self.assert_progress(result)
        self.assertEqual(result['active'],self.current['active']);self.assertEqual(result['definition']['player_team_id'],1)
        self.assertEqual(result['pending_player_team_id'],2)
        result.pop('active');runtime.put(self.conn,runtime.PREFIX+self.definition['uuid'],result)
        after=runtime.state(self.conn,changed);self.assert_progress(after)
        self.assertEqual(after['definition']['player_team_id'],2);self.assertNotIn('pending_player_team_id',after)

    def test_rule_change_resets_only_this_competition_and_preserves_its_backup(self):
        changed=copy.deepcopy(self.definition);changed['stages'][0]['win_points']=4
        result=runtime.state(self.conn,changed)
        self.assertNotEqual(result['run_id'],self.current['run_id'])
        self.assertEqual(runtime.get(self.conn,runtime.PREFIX+self.definition['uuid']+':backup:'+self.current['run_id']),self.current)
        for k,v in self.other_keys.items():self.assertEqual(runtime.get(self.conn,k),v)

    def test_participant_membership_change_resets_only_this_competition(self):
        changed=copy.deepcopy(self.definition);changed['team_ids'][-1]=99
        result=runtime.state(self.conn,changed)
        self.assertNotEqual(result['run_id'],self.current['run_id'])
        for k,v in self.other_keys.items():self.assertEqual(runtime.get(self.conn,k),v)
