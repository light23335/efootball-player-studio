"""Dynamic selection warnings and random eligibility, no user save or game."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import types
import unittest
import uuid

import world_workspace as world
from division_squads import ROLE_NAMES,APTITUDE_INDEX


class SelectionAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'assets').mkdir();(self.root/'players').mkdir()
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.db.execute('create table players(id,payload,card_type)')
        self.identities={'nation':[{'id':9,'name':'斯洛伐克','name_en':'Slovakia'},
                                   {'id':10,'name':'刚果','name_en':'Congo'}],
                         'team':[{'id':20,'name':'斯洛伐克','name_en':'Slovakia'},
                                 {'id':82020,'name':'斯洛伐克队套','name_en':'Slovakia'},
                                 {'id':1087,'name':'刚果','name_en':'Congo'},
                                 {'id':101,'name':'正常俱乐部','name_en':'Club'},
                                 {'id':5010,'name':'待补球员俱乐部','name_en':'Short club'},
                                 {'id':999,'name':'暂无球员','name_en':'Empty'}]}
        parent=self
        class Borrowed:
            def execute(self,*a):return parent.db.execute(*a)
            def close(self):pass
        self.library=types.SimpleNamespace(db=Borrowed,identities=lambda:copy.deepcopy(self.identities),resources=self.root)
        (self.root/'team-leagues.json').write_text(json.dumps({'competitions':{
            'all':{'name':'Mixed','team_ids':[20,82020,1087,101,5010,999]}}}),'utf8')
        self.store=types.SimpleNamespace(root=self.root,lock=threading.RLock())
        for i in range(25):self.card(100+i,club=101,nation=9,full=True)
        for i in range(11):self.card(200+i,club=888,nation=10,full=False)
        for i in range(10):self.card(300+i,club=5010,nation=0,full=False)

    def card(self,cid,club,nation,full):
        params=[0]*147;params[0]=12
        if full:params[1:14]=[2]*13
        else:params[APTITUDE_INDEX[12]]=2
        row={'gameplayer_id':{'id':cid,'serial':0},'parameters':params,'_nation_id':nation,
             'initial_base_team_id':club,'initial_base_national_team_id':0,
             'level_info':{'level':1,'level_limit':35}}
        self.db.execute('insert into players values(?,?,?)',(str(cid),json.dumps(row),'Standard'))

    def test_all_manual_ids_remain_visible_restored_country_aliases_share_pool_and_no_gk_warns(self):
        before=self.db.execute('select *from players').fetchall()
        catalogue=world.team_catalogue(self.library,self.store);rows={r['id']:r for r in catalogue['teams']}
        self.assertEqual(set(rows),{20,82020,1087,101,5010,999})
        self.assertEqual(rows[20]['tournament_eligibility'],rows[82020]['tournament_eligibility'])
        self.assertEqual(rows[20]['tournament_eligibility']['with_diy']['cpu']['source_people'],25)
        congo=rows[1087]['tournament_eligibility']['with_diy']['cpu']
        self.assertEqual(congo['current_people'],11);self.assertEqual(congo['full_goalkeepers'],0)
        self.assertTrue(congo['random_eligible']);self.assertEqual(congo['mode'],'fallback')
        self.assertFalse(rows[999]['tournament_eligibility']['with_diy']['cpu']['random_eligible'])
        self.assertEqual(self.db.execute('select *from players').fetchall(),before)

    def test_local_diy_changes_current_count_only_when_allowed_and_does_not_create_fake_native_cards(self):
        project={'package_id':str(uuid.uuid4()),'identity':{'name':'New real DIY','team_id':5010,'nation_id':9},
                 'position_aptitudes':dict.fromkeys(ROLE_NAMES,0)}
        project['position_aptitudes']['CF']=2;self.store.project=project
        catalogue=world.team_catalogue(self.library,self.store);row=next(r for r in catalogue['teams']if r['id']==5010)
        enabled=row['tournament_eligibility']['with_diy']['cpu']
        disabled=row['tournament_eligibility']['without_diy']['cpu']
        self.assertEqual((enabled['source_people'],enabled['current_people'],enabled['local_pending_export']),(10,11,1))
        self.assertTrue(enabled['random_eligible']);self.assertFalse(disabled['random_eligible'])
        self.assertEqual(disabled['current_people'],10)
        self.assertEqual(self.db.execute('select count(*)from players').fetchone()[0],46)
        self.assertNotIn('gameplayer_id',project)

    def test_under_11_manual_design_and_player_choice_persist_and_export_warnings_never_block(self):
        design=world.default();design['tournaments']=[{'uuid':str(uuid.uuid4()),'name':'Keep manual choices',
            'enabled':True,'include_diy':True,'team_ids':[5010,999],'player_team_id':999,
            'stages':[{'type':'knockout'}]}]
        saved=world.save(self.store,design)['document'];before=copy.deepcopy(saved)
        warnings=world.selection_warnings(self.library,self.store,saved['tournaments'])
        self.assertTrue(warnings);self.assertTrue(all(r['export_blocked']is False for r in warnings))
        self.assertTrue(any('无法组成11人首发'in r['message']for r in warnings))
        self.assertEqual(saved,before);self.assertEqual(world.load(self.store),before)
        self.assertEqual(saved['tournaments'][0]['player_team_id'],999)
        self.assertEqual(saved['tournaments'][0]['team_ids'],[5010,999])
        self.assertNotIn('selection_review',saved['tournaments'][0])


if __name__=='__main__':unittest.main()
