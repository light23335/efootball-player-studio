"""First START projects stadium slots; an issued reply remains exact."""
import copy,sqlite3,types,unittest
from unittest.mock import patch
from tournament_runtime import Service


class StartEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.db.execute('create table meta(key primary key,value)')
        self.logic=types.SimpleNamespace(conn=self.db,responses={'CMD_START_GAME':{
            'custom_stadium_list':[{'stadium_id':101,'entrance_set':1}],
            'uniform_list_home':{},'uniform_list_away':{}}},templates={})
        self.slots=[{'stadium_id':101,'entrance_set':200},{'stadium_id':102,'entrance_set':201},{'stadium_id':103,'entrance_set':202}]
        def apply(conn,response):
            self.assertIs(conn,self.db);response['custom_stadium_list']=copy.deepcopy(self.slots)
        self.modules={'custom_stadium':types.SimpleNamespace(apply=apply),
                      'club_store':types.SimpleNamespace(default_uniforms=lambda team:[])}
        self.service=Service(lambda:{},'.',None)
        self.active={'game_id':7,'player_side':'HOME'}
        self.current={'active':self.active}
    def test_old_start_preserves_issued_stadium_teams_and_game_on_every_retry(self):
        for side in ('HOME','AWAY'):
            with self.subTest(side=side):
                self.active.update(player_side=side,start_contract=4,start_reply={
                    'game_id':7,'squad_data_home':{'local':True},'squad_data_away':{'cpu':True},
                    'custom_stadium_list':[{'stadium_id':101,'entrance_set':1}]})
                before=copy.deepcopy(self.active['start_reply'])
                with patch.dict('sys.modules',self.modules),patch.object(self.service,'repair_rentals'),patch.object(self.service,'activate_coaching')as activate:
                    reply=self.service.start(self.logic,{},self.current,{'game_id':7,'side':side})
                    self.assertEqual(activate.call_count,1)
                    self.assertEqual(reply,before)
                    for key in ('game_id','squad_data_home','squad_data_away'):self.assertEqual(reply[key],before[key])
                    self.assertEqual(self.active['start_contract'],4)
                    self.slots[0]['entrance_set']=203
                    retry=self.service.start(self.logic,{},self.current,{'game_id':7,'side':side})
                    self.assertEqual(retry,before)
                    self.assertEqual(reply['custom_stadium_list'][0]['entrance_set'],1)
    def test_first_start_projects_slots_after_preserving_android_local_cpu_layout(self):
        ident={'id':11,'serial':0}
        plan={'player_list':[{'gameplayer_id':ident}],'squad_gameplan':{'match_plan_settings':{'order':[0]*11}}}
        self.active.update(home={'squad_data':plan,'coach_data':{'coach_id':1},'_studio_tournament_squad':{'team_id':1}},
                           away={'squad_data':{'cpu':True},'_studio_tournament_squad':{'team_id':2}})
        self.active['home']['player_list']=[{'gameplayer_id':ident,'parameters':[0]*147}]
        self.active['fixture_id']=1;self.current['fixtures']=[{'id':1}]
        with patch.dict('sys.modules',self.modules),patch.object(self.service,'repair_rentals'),patch.object(self.service,'activate_coaching'),patch.object(self.service,'freeze_fixture',return_value={'teams':self.active}):
            reply=self.service.start(self.logic,{},self.current,{'game_id':7})
        self.assertEqual(reply['custom_stadium_list'],self.slots)
        self.assertEqual(reply['squad_data_away'],{'cpu':True})
        self.assertEqual(len(reply['squad_data_home']['player_list'][0]['parameters']),147)
        self.assertEqual(self.logic.responses['CMD_START_GAME']['custom_stadium_list'][0]['entrance_set'],1)


if __name__=='__main__':unittest.main()
