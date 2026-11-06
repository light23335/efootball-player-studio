import copy
import json
from pathlib import Path
import random
import types
import unittest
from unittest.mock import patch

import tournament_agents as agents
import tournament_rewards as rewards
import tournament_runtime as runtime
from test_tournament_rewards import competition, card, database


STOCK = {'agent_id':1366,'title':'Unrelated normal deal','count':0,
         'agent_type':'BOX_AGENT','pickup_list':[]}
PRICE = {'agent_id':1366,'price_list':[{'multiple_count':1,'price':{'coin_price':100}}]}


class NativeChanceTests(unittest.TestCase):
    def setUp(self):
        self.conn=database([card()]);self.addCleanup(self.conn.close)
        self.conn.execute('CREATE TABLE agents(agent_id PRIMARY KEY,json)')
        self.conn.execute('CREATE TABLE gameplayers(card_id PRIMARY KEY,json)')
        self.conn.execute('INSERT INTO gameplayers VALUES(7,?)',('owned-unchanged',))
        self.conn.execute('INSERT INTO agents VALUES(?,?)',(1366,json.dumps(STOCK)))
        self.current=competition()
        self.definition=runtime.configuration([self.current['definition']])[0]
        self.current['definition']=self.definition
        self.document={'players':[],'tournaments':[self.definition],'tournament_team_names':{'1':'Club A','2':'Club B'},
                       'tournament_entry_image':'/packaged/tournament.jpg'}
        self.generator=types.SimpleNamespace(prepared=lambda p:copy.deepcopy(p),rental_prepared=lambda p,seed:copy.deepcopy(p))
        self.service=runtime.Service(lambda:self.document,Path('.'),self.generator)
        self.stock=dict(result='NOERR',agent_list=[copy.deepcopy(STOCK)],agent_price_list=[copy.deepcopy(PRICE)])
        self.logic=types.SimpleNamespace(conn=self.conn,responses={agents.LIST:self.stock},templates={},
                                        _currency=lambda out:dict(out,gp=99999,coin=99999))
        runtime.put(self.conn,runtime.PREFIX+self.definition['uuid'],self.current);self.conn.commit()

    def listing(self):
        return self.service.handle(self.logic,agents.LIST,{'rqid':1},self.original)

    def original(self,logic,command,request):
        self.assertEqual(command,agents.LIST,'Must never call the stock permanent draw')
        return copy.deepcopy(self.stock)

    def advance(self):
        self.current[rewards.KEY]={'version':1,'run_id':self.current['run_id'],
            'awards':{'stage-1':{'stage_uuid':'stage-1','granted':3,'used':0}},'rentals':[],'draw_receipts':{}}
        runtime.put(self.conn,runtime.PREFIX+self.definition['uuid'],self.current);self.conn.commit()

    def request(self,aid,rqid=20,**extra):
        return dict(agent_id=aid,rqid=rqid,user_id='local-user',count=1,**extra)

    def draw(self,request):
        with patch.dict('sys.modules',{'draw_presentation':types.SimpleNamespace(response_fields=lambda p:{'effect_list':[]})}):
            return self.service.handle(self.logic,agents.DRAW,request,self.original)

    def test_named_native_deal_exists_before_earning_with_no_paid_price(self):
        out=self.listing();deal=out['agent_list'][-1]
        self.assertEqual(deal['title'],'锦标赛特殊机会抽取')
        self.assertEqual(deal['count'],0)
        self.assertEqual(out['agent_price_list'][-1]['price_list'],[])
        self.assertEqual(deal['banner_file_c_name'],'/packaged/tournament.jpg')
        self.assertEqual(deal['pickup_list'][0]['initial_base_team_id'],1)
        self.assertEqual(out['agent_list'][0],STOCK);self.assertEqual(out['agent_price_list'][0],PRICE)
        self.assertEqual(deal['can_reset'],'NO')
        self.assertEqual(deal['expiration_date'],0)
        self.assertIn('可用机会 0 次',deal['subcategory'])

    def test_pending_contract_does_not_enroll_or_create_progress(self):
        self.conn.execute('DELETE FROM meta WHERE key=?',(runtime.PREFIX+self.definition['uuid'],));self.conn.commit()
        self.assertEqual(self.listing()['agent_list'][-1]['count'],0)
        self.assertIsNone(runtime.get(self.conn,runtime.PREFIX+self.definition['uuid']))

    def test_each_competitions_contract_uses_its_custom_cover_and_reset_restores_default(self):
        self.definition['cover_artwork']={'request':'/player-studio/pack-covers/custom'}
        out=self.listing();deal=out['agent_list'][-1]
        self.assertEqual(deal['banner_file_c_name'],'/player-studio/pack-covers/custom')
        self.assertEqual(deal['banner_file_d_name'],'/player-studio/pack-covers/custom')
        self.assertEqual(out['agent_list'][0],STOCK)
        self.definition.pop('cover_artwork')
        self.assertEqual(self.listing()['agent_list'][-1]['banner_file_c_name'],'/packaged/tournament.jpg')

    def test_earned_native_count_and_atomic_rental_draw_no_owned_grant(self):
        self.advance();deal=self.listing()['agent_list'][-1]
        self.assertEqual(deal['count'],3)
        before=list(self.conn.execute('SELECT * FROM gameplayers'))
        result=self.draw(self.request(deal['agent_id']))
        self.assertEqual(result['agent_list'][-1]['count'],2)
        refreshed=result['agent_list'][-1]
        self.assertEqual(refreshed['player_list_total'],1)
        self.assertEqual(sum(refreshed['base_player_count']),1)
        self.assertEqual(sum(refreshed['remaining_player_count']),0)
        box=self.service.handle(self.logic,agents.BOX,self.request(deal['agent_id'],21),self.original)
        self.assertEqual(box['base_player_count'],refreshed['base_player_count'])
        self.assertEqual(box['remaining_player_count'],refreshed['remaining_player_count'])
        loan=result['gameplayer_list'][0]['gameplayer']
        self.assertEqual(loan['type'],'RENTAL');self.assertEqual(loan['gameplayer_id']['serial'],0)
        self.assertEqual(loan['initial_base_team_id'],1)
        self.assertEqual(list(self.conn.execute('SELECT * FROM gameplayers')),before)
        self.assertEqual(json.loads(self.conn.execute('SELECT payload FROM managed_cards').fetchone()[0])['initial_base_team_id'],108)
        self.assertEqual(len(self.conn.execute('SELECT * FROM agents').fetchall()),1)
        self.assertEqual(self.draw(self.request(deal['agent_id'])),result)
        saved=runtime.get(self.conn,runtime.PREFIX+self.definition['uuid'])
        self.assertEqual(rewards.status(saved)['available'],2)
        with patch.dict('sys.modules',{'club_store':types.SimpleNamespace(players=lambda conn:[])}):
            pool=self.service.player_pool(self.conn,self.definition,{'player_side':'HOME','home':{'player_list':[]}})
        self.assertIn((card()['gameplayer_id']['id'],0),pool)

    def test_unearned_chance_cannot_be_bypassed_by_direct_draw_coin_or_reset(self):
        aid=self.listing()['agent_list'][-1]['agent_id']
        with self.assertRaises(ValueError):self.draw(self.request(aid))
        self.advance()
        for kw in ({'payment_kind':'COIN'},{'payment_kind':'GP'},{'count':0},{'count':11},{'count':True},{'count':'10'}):
            req=self.request(aid);req.update(kw)
            with self.assertRaises(ValueError):self.draw(req)
        with self.assertRaises(ValueError):self.service.handle(self.logic,agents.RESET,self.request(aid),self.original)
        self.assertEqual(rewards.status(runtime.get(self.conn,runtime.PREFIX+self.definition['uuid']))['available'],3)

    def batch_pool(self,balance):
        self.advance()
        self.current[rewards.KEY]['awards']['stage-1']['granted']=balance
        self.conn.execute('delete from managed_cards')
        for row in rewards.catalogue()['cards'][:12]:
            p=card(row['card_id'])
            self.conn.execute('insert into managed_cards values(?,?,?)',(str(row['card_id']),'source',json.dumps(p)))
        runtime.put(self.conn,runtime.PREFIX+self.definition['uuid'],self.current);self.conn.commit()
        return self.listing()['agent_list'][-1]['agent_id']

    def test_bulk_one_through_ten_native_response_and_idempotent_retry(self):
        for balance in (1,2,7,8,9,10,12):
            with self.subTest(balance=balance):
                aid=self.batch_pool(balance);req=self.request(aid,100+balance);req['count']=10
                before=list(self.conn.execute('select * from gameplayers'))
                out=self.draw(req);n=min(balance,10)
                ids=[r['gameplayer']['gameplayer_id']['id']for r in out['gameplayer_list']]
                self.assertEqual(len(ids),n);self.assertEqual(len(set(ids)),n)
                self.assertEqual(out['agent_list'][-1]['count'],balance-n)
                self.assertEqual(self.draw(req),out)
                self.assertEqual(list(self.conn.execute('select * from gameplayers')),before)
                saved=runtime.get(self.conn,runtime.PREFIX+self.definition['uuid'])
                self.assertEqual(len(saved[rewards.KEY]['draw_receipts']),1)
                self.assertEqual(rewards.status(saved)['available'],balance-n)

    def test_native_eight_or_nine_request_and_full_batch_rollback_on_presentation_failure(self):
        for quantity in (8,9):
            aid=self.batch_pool(quantity);req=self.request(aid,200+quantity);req['count']=quantity
            before=list(self.conn.execute('select * from meta'))
            with patch.dict('sys.modules',{'draw_presentation':types.SimpleNamespace(response_fields=lambda p:(_ for _ in ()).throw(ValueError('render')))}):
                with self.assertRaisesRegex(ValueError,'render'):self.service.handle(self.logic,agents.DRAW,req,self.original)
            self.assertEqual(list(self.conn.execute('select * from meta')),before)
            out=self.draw(req);self.assertEqual(len(out['gameplayer_list']),quantity)
            changed=dict(req,count=1)
            with self.assertRaisesRegex(ValueError,'数量'):self.draw(changed)

    def test_small_remaining_pool_caps_bulk_spend_without_duplicates(self):
        aid=self.batch_pool(9)
        self.conn.execute('delete from managed_cards where card_id not in (select card_id from managed_cards limit 3)');self.conn.commit()
        req=self.request(aid);req['count']=10
        out=self.draw(req)
        self.assertEqual(len(out['gameplayer_list']),3);self.assertEqual(out['agent_list'][-1]['count'],6)

    def test_each_tournament_has_separate_deal_club_and_chances(self):
        self.advance()
        b=competition();b['definition']['player_team_id']=2
        d=runtime.configuration([b['definition']])[0];b['definition']=d
        self.document['tournaments'].append(d)
        runtime.put(self.conn,runtime.PREFIX+d['uuid'],b);self.conn.commit()
        out=self.listing();a,b=out['agent_list'][-2:]
        self.assertNotEqual(a['agent_id'],b['agent_id'])
        self.assertEqual([a['count'],b['count']],[3,0])
        self.assertEqual([a['pickup_list'][0]['initial_base_team_id'],b['pickup_list'][0]['initial_base_team_id']],[1,2])
        with self.assertRaises(ValueError):self.draw(self.request(b['agent_id']))

    def test_missing_card_causes_no_spend(self):
        self.advance();aid=self.listing()['agent_list'][-1]['agent_id']
        self.conn.execute('DELETE FROM managed_cards');self.conn.commit()
        with self.assertRaisesRegex(ValueError,'未消耗'):self.draw(self.request(aid))
        self.assertEqual(rewards.status(runtime.get(self.conn,runtime.PREFIX+self.definition['uuid']))['available'],3)

    def test_serialization_failure_rolls_back_draw_and_loan(self):
        self.advance();aid=self.listing()['agent_list'][-1]['agent_id']
        with patch.dict('sys.modules',{'draw_presentation':types.SimpleNamespace(response_fields=lambda p:(_ for _ in ()).throw(ValueError('render')))}):
            with self.assertRaises(ValueError):self.service.handle(self.logic,agents.DRAW,self.request(aid),self.original)
        saved=runtime.get(self.conn,runtime.PREFIX+self.definition['uuid'])
        self.assertEqual(rewards.status(saved)['available'],3);self.assertEqual(rewards.rental_ids(saved),[])

    def test_new_edition_rejects_delayed_request_from_old_deal(self):
        self.advance();old=self.listing()['agent_list'][-1]['agent_id']
        self.current['run_id']='new-edition';self.current.pop(rewards.KEY)
        runtime.put(self.conn,runtime.PREFIX+self.definition['uuid'],self.current);self.conn.commit()
        new=self.listing()['agent_list'][-1]
        self.assertNotEqual(old,new['agent_id']);self.assertEqual(new['count'],0)
        with self.assertRaisesRegex(ValueError,'届次'):self.draw(self.request(old))

    def test_finished_or_deleted_tournament_never_falls_to_global_draw(self):
        self.advance();aid=self.listing()['agent_list'][-1]['agent_id']
        self.current['completed']=True;rewards.settle(self.current,[])
        runtime.put(self.conn,runtime.PREFIX+self.definition['uuid'],self.current);self.conn.commit()
        self.assertEqual(self.listing()['agent_list'][-1]['count'],0)
        with self.assertRaises(ValueError):self.draw(self.request(aid))
        self.document['tournaments']=[]
        self.assertEqual(self.listing()['agent_list'],[STOCK])
        with self.assertRaises(ValueError):self.draw(self.request(aid))

    def test_native_preview_uses_rentals_and_has_no_global_ownership(self):
        aid=self.listing()['agent_list'][-1]['agent_id']
        out=self.service.handle(self.logic,agents.CARDS,self.request(aid),self.original)
        self.assertEqual(out['acquired_player_list'],[])
        self.assertEqual(out['gameplayer_list'][0]['gameplayer']['initial_base_team_id'],1)
        self.assertEqual(len(list(self.conn.execute('SELECT * FROM gameplayers'))),1)

    def test_ids_stable_on_reload_and_never_collide_with_existing_agent(self):
        aid=self.listing()['agent_list'][-1]['agent_id']
        self.assertEqual(self.listing()['agent_list'][-1]['agent_id'],aid)
        reg=runtime.get(self.conn,agents.REGISTRY);self.assertEqual(list(reg.values()),[aid])
        self.assertNotEqual(aid,1366)


if __name__=='__main__':unittest.main()
