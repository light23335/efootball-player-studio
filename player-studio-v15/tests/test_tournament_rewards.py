import copy
from contextlib import closing
import json
from pathlib import Path
import random
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import patch
import uuid

import tournament_promotion as promotion
import tournament_rewards as rewards
import tournament_rules as rules
import tournament_runtime as runtime


def competition():
    return rules.start({'uuid':str(uuid.uuid4()),'name':'Cup','enabled':True,
                        'team_ids':[1,2,3,4],'player_team_id':1,
                        'stages':[{'type':'league','advance_per_group':2},
                                  {'type':'knockout','advance':1}]},4)


def card(cid=89138556575063,team=108):
    return {'gameplayer_id':{'id':cid,'serial':7},'parameters':[80]*147,
            'initial_base_team_id':team,'name':'Source club player'}


def database(rows):
    conn=sqlite3.connect(':memory:')
    conn.execute('create table managed_cards(card_id primary key,fingerprint,payload)')
    conn.execute('create table meta(key primary key,value)')
    for row in rows:
        conn.execute('insert into managed_cards values(?,?,?)',(str(row['gameplayer_id']['id']),'fingerprint',json.dumps(row)))
    return conn


class RewardsTests(unittest.TestCase):
    def test_attachment_allowlist_is_exactly_118_unique_cards(self):
        pool=rewards.catalogue();ids=[r['card_id']for r in pool['cards']]
        self.assertEqual(len(ids),118);self.assertEqual(len(set(ids)),118)
        self.assertEqual(pool['group_counts'],{'attack':79,'midfield':22,'defence_goalkeeper':17})
        self.assertNotIn(89138556678270,ids)
        self.assertEqual(pool['source_sha256'],'040b9acab0ffebb37d30c34c215db72d174e0e56339fc9a98b657ee391b1a582')

    def test_runtime_pool_embedded_and_independent_of_file_paths(self):
        source=rewards.runtime_source();module=types.ModuleType('embedded_reward_probe')
        exec(compile(source,'embedded_reward_probe.py','exec'),module.__dict__)
        self.assertEqual(module.catalogue(),rewards.catalogue())
        with patch.object(rewards,'_EMBEDDED_POOL',None),patch.object(Path,'read_text',side_effect=AssertionError('no resources')):
            self.assertEqual(len(module.catalogue()['cards']),118)

    def test_excluded_or_duplicate_id_cannot_enter_pool(self):
        for row in ({'card_id':89138556678270},{'card_id':True},{'id':1}):
            pool=rewards.catalogue();pool['cards'].append(row)
            with self.assertRaises(ValueError):rewards.validate_catalogue(pool)
        pool=rewards.catalogue();pool['cards'].append(copy.deepcopy(pool['cards'][0]))
        with self.assertRaises(ValueError):rewards.validate_catalogue(pool)

    def test_current_catalogue_filters_missing_recycled_and_invalid_wire(self):
        ids=[r['card_id']for r in rewards.catalogue()['cards'][:4]]
        a,b,c,d=map(card,ids);d['parameters']=[40]
        conn=database([a,b,c,d]);self.addCleanup(conn.close)
        document={'native_player_catalogue':{'version':1,'card_ids':[ids[0],ids[2],ids[3]]},
                  'catalogue_recycle_bin':[{'id':str(ids[2]),'name':'trashed'}]}
        rows,report=rewards.available(conn,document)
        self.assertEqual([r['gameplayer_id']['id']for r in rows],[ids[0]])
        self.assertIn(ids[1],report['missing_ids']);self.assertIn(ids[2],report['missing_ids'])
        self.assertIn(ids[3],report['unusable_ids']);self.assertEqual(report['listed'],118)
        self.assertEqual(rows[0]['parameters'],a['parameters'])

    def test_reference_ratings_and_boosters_never_overwrite_game_data(self):
        conn=database([card()]);self.addCleanup(conn.close)
        seen=[];generator=types.SimpleNamespace(prepared=lambda p:seen.append(copy.deepcopy(p))or p)
        rows,_=rewards.available(conn,{},generator)
        self.assertEqual(rows[0]['parameters'],[80]*147)
        self.assertEqual(seen[0]['parameters'],[80]*147)
        self.assertNotIn('reference_overall',rows[0])
        self.assertNotIn('reference_booster_ids',rows[0])

    def test_native_special_card_uses_scoped_export_without_global_reinsertion(self):
        cid=123236838841410
        conn=database([]);self.addCleanup(conn.close)
        document={'native_player_catalogue':{'version':1,'card_ids':[cid]},
                  'tournament_reinforcement_cards':{str(cid):card(cid)}}
        rows,_=rewards.available(conn,document)
        self.assertEqual([p['gameplayer_id']['id']for p in rows],[cid])
        self.assertEqual(conn.execute('SELECT count(*) FROM managed_cards').fetchone()[0],0)
        document['catalogue_recycle_bin']=[{'id':str(cid)}]
        self.assertEqual(rewards.available(conn,document)[0],[])
        document['catalogue_recycle_bin']=[]
        document['native_player_catalogue']['card_ids']=[]
        self.assertEqual(rewards.available(conn,document)[0],[])

    def test_ten_winrate_bands_and_no_divide_by_zero(self):
        self.assertEqual([rewards.chances(w,10)for w in range(11)],[1,1,2,3,4,5,6,7,8,9,10])
        self.assertEqual(rewards.chances(2,3),7)
        for args in ((0,0),(4,3),(-1,3),(True,3)):
            with self.assertRaises(ValueError):rewards.chances(*args)

    def advance_league(self,s):
        events=[]
        while s['stage_index']==0:
            f=rules.due(s)[0];before=promotion.capture(s)
            score=[2,0]if 1!=f['away']else[0,2]
            rules.record(s,f['id'],*score)
            new=promotion.settle(s,before);events.extend(new);rewards.settle(s,new)
        return events

    def test_stage_awards_once_only_after_real_qualification(self):
        s=competition();events=self.advance_league(s)
        self.assertEqual(rewards.status(s)['available'],10)
        self.assertEqual(len(rewards.status(s)['awards']),1)
        snapshot=copy.deepcopy(s);rewards.settle(s,events)
        self.assertEqual(s,snapshot)
        self.assertEqual(rewards.status(s)['awards'][0]['wins'],3)

    def test_knockout_round_win_does_not_repeat_stage_award(self):
        s=competition();events=self.advance_league(s)
        rewards.settle(s,[dict(events[0],stage_index=s['stage_index'])])
        self.assertEqual(rewards.status(s)['available'],10)

    def test_reading_historical_save_never_grants_retroactive_award(self):
        s=competition();self.advance_league(s);s.pop(rewards.KEY)
        baseline=promotion.capture(s)
        self.assertEqual(promotion.settle(s,baseline),[])
        rewards.settle(s,[])
        self.assertEqual(rewards.status(s)['available'],0)

    def test_draw_idempotent_and_current_club_only_in_run_ledger(self):
        conn=database([card()]);self.addCleanup(conn.close)
        s=competition();self.advance_league(s);before=conn.total_changes
        result=rewards.draw(s,conn,{},'request-1',rng=random.Random(1))
        repeat=rewards.draw(s,conn,{},'request-1')
        self.assertEqual(result,repeat);self.assertEqual(rewards.status(s)['available'],9)
        self.assertEqual(result['loan']['team_id'],1)
        self.assertEqual(result['loan']['run_id'],s['run_id'])
        self.assertEqual(conn.total_changes,before)
        self.assertEqual(json.loads(conn.execute('select payload from managed_cards').fetchone()[0])['initial_base_team_id'],108)

    def test_no_available_card_never_consumes_chance(self):
        conn=database([]);self.addCleanup(conn.close)
        s=competition();self.advance_league(s);before=copy.deepcopy(s)
        with self.assertRaisesRegex(ValueError,'未消耗'):rewards.draw(s,conn,{},'request-1')
        self.assertEqual(s,before)

    def test_no_repeat_card_and_no_cross_run_receipt(self):
        conn=database([card()]);self.addCleanup(conn.close)
        s=competition();self.advance_league(s);rewards.draw(s,conn,{},'request-1')
        with self.assertRaisesRegex(ValueError,'未消耗'):rewards.draw(s,conn,{},'request-2')
        s['run_id']='new-run'
        with self.assertRaisesRegex(ValueError,'本届'):rewards.draw(s,conn,{},'request-1')

    def test_tournament_end_expires_loans_and_chances(self):
        conn=database([card()]);self.addCleanup(conn.close)
        s=competition();self.advance_league(s);rewards.draw(s,conn,{},'request-1')
        s['completed']=True;rewards.settle(s,[])
        self.assertEqual(rewards.status(s)['rentals'],[]);self.assertEqual(rewards.status(s)['available'],0)
        with self.assertRaises(ValueError):rewards.draw(s,conn,{},'request-1')

    def test_two_tournaments_scope_same_loan_to_different_clubs(self):
        conn=database([card()]);self.addCleanup(conn.close)
        a=competition();self.advance_league(a)
        b=copy.deepcopy(a);b['definition']['uuid']=str(uuid.uuid4());b['definition']['player_team_id']=2
        b['run_id']='second-run';b.pop(rewards.KEY)
        b[rewards.KEY]={'version':1,'run_id':b['run_id'],'awards':{'test':{'stage_uuid':'test','granted':1,'used':0}},'rentals':[],'draw_receipts':{}}
        first=rewards.draw(a,conn,{},'same-request');second=rewards.draw(b,conn,{},'same-request')
        self.assertEqual(first['loan']['card_id'],second['loan']['card_id'])
        self.assertEqual([first['loan']['team_id'],second['loan']['team_id']],[1,2])

    def test_native_rental_wire_is_copy_and_uses_serial_zero(self):
        source=card();conn=database([source]);self.addCleanup(conn.close)
        s=competition();self.advance_league(s);rewards.draw(s,conn,{},'request-1')
        prepared=copy.deepcopy(source);prepared['parameters']+=[1,2]
        generator=types.SimpleNamespace(rental_prepared=lambda p,seed:prepared)
        service=runtime.Service(lambda:{},Path('.'),generator)
        wire=service.reinforcements(conn,s['definition'],s)[0]
        self.assertEqual(wire['gameplayer_id'],{'id':source['gameplayer_id']['id'],'serial':0})
        self.assertEqual(wire['type'],'RENTAL');self.assertEqual(wire['initial_base_team_id'],1)
        self.assertEqual(len(wire['parameters']),147);self.assertEqual(prepared['initial_base_team_id'],108)
        self.assertEqual(prepared['gameplayer_id']['serial'],7)

    def test_schedule_has_no_draw_ui_and_stays_read_only(self):
        from tournament_schedule_ui import overview_html
        s=competition();self.advance_league(s);before=copy.deepcopy(s)
        raw=overview_html(s)
        self.assertEqual(s,before)
        self.assertNotIn(b'reinforce-draw',raw)
        self.assertNotIn(b'/reinforcements',raw)

    def test_difficulty_and_auto_coaching_preserve_run_but_rules_reset(self):
        conn=database([]);self.addCleanup(conn.close)
        definition=competition()['definition'];definition['enabled']=True
        one=runtime.configuration([definition])[0];s=runtime.state(conn,one)
        first=rules.due(s)[0];rules.record(s,first['id'],2,0);runtime.put(conn,runtime.PREFIX+one['uuid'],s)
        changed=copy.deepcopy(definition);changed.update(difficulty='LEGEND',auto_coaching=False)
        two=runtime.configuration([changed])[0];current=runtime.state(conn,two)
        self.assertEqual(s['run_id'],current['run_id']);self.assertEqual(s['fixtures'],current['fixtures'])
        self.assertEqual(current['difficulty'],'LEGEND')
        changed['stages'][0]['cycles']=2
        three=runtime.configuration([changed])[0]
        self.assertNotEqual(runtime.state(conn,three)['run_id'],s['run_id'])


if __name__=='__main__':unittest.main()
