"""Regression: native Standard cards omitted by the Contract catalogue."""
import copy,json,sqlite3,unittest
from types import SimpleNamespace
from tournament_squads import export_standard_cards,club_cards


def card(cid,team=2625,cap=None,nation=0):
    return {'gameplayer_id':{'id':cid,'serial':0},'parameters':[0]*147,
            'level_info':{'level':1,'level_limit':cap},'initial_base_team_id':team,'_nation_id':nation}


class StandardCardTests(unittest.TestCase):
    def setUp(self):
        self.source=sqlite3.connect(':memory:');self.addCleanup(self.source.close)
        self.source.execute('create table players(id,payload,card_type)')
        self.conn=sqlite3.connect(':memory:');self.addCleanup(self.conn.close)
        self.conn.execute('create table managed_cards(card_id,fingerprint,payload)')
        self.doc={'players':[],'tournaments':[{'team_ids':[2625]}],
                  'native_player_catalogue':{'version':1,'card_ids':list(range(1,20))}}
        owner=self
        class BorrowedConnection:
            def execute(self,*args):return owner.source.execute(*args)
            def close(self):pass
        self.library=SimpleNamespace(db=BorrowedConnection)

    def add(self,c,kind='Standard'):
        self.source.execute('insert into players values(?,?,?)',(str(c['gameplayer_id']['id']),json.dumps(c),kind))

    def test_unknown_standard_cap_is_35_known_cap_and_actual_abilities_preserved(self):
        a=card(1);a['parameters'][14]=74
        b=card(2,cap=27)
        self.add(a);self.add(b)
        before=self.source.execute('select * from players').fetchall()
        out=export_standard_cards(self.library,self.doc)
        self.assertEqual(out['1']['level_info']['level_limit'],35)
        self.assertEqual(out['1']['_studio_tournament_level_limit_source'],'user-default-35')
        self.assertEqual(out['2']['level_info']['level_limit'],27)
        self.assertEqual(out['2']['_studio_tournament_level_limit_source'],'verified-source')
        self.assertEqual(out['1']['parameters'],a['parameters'])
        self.assertEqual(self.source.execute('select * from players').fetchall(),before)

    def test_only_participating_native_standard_cards_no_recycled_or_diy_alias(self):
        self.doc['catalogue_recycle_bin']=[{'id':3}]
        self.doc['players']=[{'identity':{'card_id':4}}]
        for c,kind in [(card(1),'Standard'),(card(2),'Epic'),(card(3),'Standard'),(card(4),'Standard'),
                       (card(5,team=101),'Standard'),(card(99),'Standard')]:self.add(c,kind)
        self.assertEqual(set(export_standard_cards(self.library,self.doc)),{'1'})

    def test_national_team_membership_uses_actual_nation(self):
        self.doc['tournaments']=[{'team_ids':[999]}]
        self.doc['tournament_national_team_nations']={'999':7}
        self.add(card(1,team=101,nation=7));self.add(card(2,team=101,nation=8))
        self.assertEqual(set(export_standard_cards(self.library,self.doc)),{'1'})

    def test_private_pool_adds_missing_normals_repairs_null_cap_without_db_write(self):
        existing=card(1);existing['original_runtime_field']='retained'
        self.conn.execute('insert into managed_cards values(?,?,?)',('1','old',json.dumps(existing)))
        self.add(card(1));self.add(card(2))
        self.doc['tournament_standard_cards']=export_standard_cards(self.library,self.doc)
        before=self.conn.execute('select * from managed_cards').fetchall()
        rows=club_cards(self.conn,self.doc,2625)
        self.assertEqual({p['gameplayer_id']['id']for p in rows},{1,2})
        self.assertTrue(all(p['level_info']['level_limit']==35 for p in rows))
        self.assertEqual(next(p for p in rows if p['gameplayer_id']['id']==1)['original_runtime_field'],'retained')
        self.assertEqual(self.conn.execute('select * from managed_cards').fetchall(),before)

    def test_runtime_known_cap_is_not_replaced_by_fallback(self):
        known=card(1,cap=42)
        self.conn.execute('insert into managed_cards values(?,?,?)',('1','known',json.dumps(known)))
        self.add(card(1));self.doc['tournament_standard_cards']=export_standard_cards(self.library,self.doc)
        self.assertEqual(club_cards(self.conn,self.doc,2625)[0]['level_info']['level_limit'],42)

    def test_runtime_exclusion_and_final_native_gate_still_apply(self):
        self.add(card(1));self.add(card(2))
        self.doc['tournament_standard_cards']=export_standard_cards(self.library,self.doc)
        self.doc['division_squads']={'excluded_ids':['1']}
        self.assertEqual([p['gameplayer_id']['id']for p in club_cards(self.conn,self.doc,2625)],[2])
        self.doc['native_player_catalogue']['card_ids']=[1]
        self.assertEqual(club_cards(self.conn,self.doc,2625),[])

    def test_invalid_source_is_rejected_instead_of_inventing_data(self):
        broken=card(1);broken['parameters']=[0]*146;self.add(broken)
        with self.assertRaisesRegex(ValueError,'原生资料'):export_standard_cards(self.library,self.doc)

    def test_malformed_cached_normal_can_use_validated_native_definition(self):
        self.add(card(1));self.doc['tournament_standard_cards']=export_standard_cards(self.library,self.doc)
        for raw in ('broken-json','[]',json.dumps(dict(card(1),level_info=None))):
            self.conn.execute('delete from managed_cards')
            self.conn.execute('insert into managed_cards values(?,?,?)',('1','bad',raw))
            rows=club_cards(self.conn,self.doc,2625)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['level_info']['level_limit'],35)


if __name__=='__main__':unittest.main()
