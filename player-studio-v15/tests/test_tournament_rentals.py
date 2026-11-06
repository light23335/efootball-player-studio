"""Rental identity and reference resolution regressions from native V17."""
import copy,json,sqlite3,unittest
from types import SimpleNamespace
from unittest.mock import patch
from tournament_squads import ClubGenerator,STYLES,STYLE_WIRE
from tournament_runtime import Service


class TournamentRentalTests(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:');self.addCleanup(self.conn.close)
        self.conn.execute('create table coaches(json)')
        self.coach={'coach_id':{'id':8,'serial':23},**{s:88 for s in STYLES}}
        self.conn.execute('insert into coaches values(?)',(json.dumps(self.coach),))

    def test_owned_coach_references_keep_actual_serial_and_do_not_grant_catalogue(self):
        generator=object.__new__(ClubGenerator)
        catalogue=[{'payload':{'coach_id':{'id':8,'serial':0}},'effects':{'1':2}},
                   {'payload':{'coach_id':{'id':9,'serial':0}},'effects':{}}]
        before=self.conn.total_changes
        with patch.object(generator,'coaches',return_value=catalogue):
            rows=generator.owned_coaches(self.conn)
        self.assertEqual(rows,[{'payload':self.coach,'effects':{'1':2}}])
        self.assertEqual(self.conn.total_changes,before)

    def test_cached_rental_migration_keeps_owned_replacement_and_same_fixture(self):
        style=STYLES[0]
        old=[{'gameplayer_id':{'id':100+i,'serial':820000001+i},'parameters':[70]*149}for i in range(23)]
        plan={'player_list':[{'gameplayer_id':p['gameplayer_id'].copy()}for p in old],
              'coach':[{'coach_id':{'id':99,'serial':0}}],
              'squad_gameplan':{'formation':[{'team_style':'OLD'},{'team_style':'OLD'}]}}
        owned_replacement={'id':999,'serial':654321}
        own_plan=copy.deepcopy(plan);own_plan['player_list'][3]['gameplayer_id']=owned_replacement.copy()
        active={'game_id':123,'player_side':'AWAY','fixture_id':7,'started':False,
                'own_plan':own_plan,
                'home':{'cpu_marker':True},'away':{'player_list':old,'squad_data':plan,
                'coach_data':{'coach_id':{'id':99,'serial':0}},'_studio_tournament_squad':{'style':style}}}
        generator=SimpleNamespace(owned_coaches=lambda c:[{'payload':self.coach,'effects':{}}],payload_rating=lambda *args:104,
                                  repair_rental_boosters=lambda *args:False)
        service=Service(lambda:{},'.',generator);before=self.conn.total_changes
        service.repair_rentals(self.conn,{},active)
        self.assertEqual(active['fixture_id'],7);self.assertEqual(active['home'],{'cpu_marker':True})
        self.assertTrue(all(p['gameplayer_id']['serial']==0 and p['type']=='RENTAL'for p in old))
        self.assertEqual(active['own_plan']['player_list'][3]['gameplayer_id'],owned_replacement)
        self.assertEqual(plan['player_list'][3]['gameplayer_id'],{'id':103,'serial':0})
        self.assertEqual(active['own_plan']['coach'][0]['coach_id'],self.coach['coach_id'])
        self.assertEqual(active['away']['coach_data'],self.coach)
        self.assertEqual([f['team_style']for f in own_plan['squad_gameplan']['formation']],[STYLE_WIRE[style]]*2)
        self.assertNotIn('start_reply',active);self.assertNotIn('start_contract',active)
        self.assertEqual(self.conn.total_changes,before)
        expected=copy.deepcopy(active);service.repair_rentals(self.conn,{},active);self.assertEqual(active,expected)

    def test_missing_owned_coach_is_not_silently_replaced_with_unowned_catalogue(self):
        service=Service(lambda:{},'.',SimpleNamespace(owned_coaches=lambda c:[]))
        active={'game_id':1,'player_side':'HOME','home':{'player_list':[],
                'squad_data':{'player_list':[]},'coach_data':{'coach_id':{'id':9,'serial':0}},
                '_studio_tournament_squad':{'style':STYLES[0]}}}
        with self.assertRaisesRegex(ValueError,'已持有'):service.repair_rentals(self.conn,{},active)


if __name__=='__main__':unittest.main()
