import copy,json,sqlite3,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
import tournament_reward_ui as ui
import tournament_runtime as runtime
from test_tournament_rewards import competition


class RewardUITests(unittest.TestCase):
    def test_reward_waits_for_pending_native_promotion_confirmation(self):
        import tournament_promotion as promotion
        event=promotion._event(self.state,0,'table','advanced','group_qualification',[1])
        event['status']='pending';promotion._journal(self.state)['events'].append(event);self.save()
        self.signal=(1,self.event);p=self.presenter()
        self.assertFalse(p.tick());self.assertEqual(self.shown,[])
        pending=promotion.begin(self.state,'test-menu')
        self.assertTrue(promotion.confirm(self.state,event['id'],pending['delivery']['token']));self.save()
        self.assertTrue(p.tick());self.assertEqual(len(self.shown),1)

    def test_reward_waits_for_native_fade_out_even_after_database_confirmation(self):
        busy=[True];self.channel.promotion_busy=lambda:busy[0]
        self.signal=(1,self.event);p=self.presenter()
        self.assertFalse(p.tick());self.assertEqual(self.shown,[])
        busy[0]=False;self.signal=(2,self.event)
        self.assertTrue(p.tick());self.assertEqual(len(self.shown),1)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);folder=self.root/'outputs/efootball';folder.mkdir(parents=True)
        self.path=folder/'local-club.sqlite3';self.conn=sqlite3.connect(self.path);self.addCleanup(self.conn.close)
        self.conn.execute('create table meta(key primary key,value)')
        self.state=competition();self.definition=runtime.configuration([self.state['definition']])[0]
        self.state['definition']=self.definition
        self.state['reinforcements']={'version':1,'run_id':self.state['run_id'],'awards':{
            'stage-a':{'stage_uuid':'stage-a','granted':8,'used':0,'notified':False}},'rentals':[],'draw_receipts':{}}
        self.save();runtime.put(self.conn,'unrelated',{'owned':[1,2],'progress':12});self.conn.commit()
        self.event=self.definition['event_id'];self.signal=(0,0)
        self.service=types.SimpleNamespace(root=self.root,definitions=lambda:[self.definition])
        self.channel=types.SimpleNamespace(rendered=lambda:self.signal)

    def save(self):
        runtime.put(self.conn,runtime.PREFIX+self.definition['uuid'],self.state);self.conn.commit()

    def saved(self):return runtime.get(self.conn,runtime.PREFIX+self.definition['uuid'])

    def presenter(self,fail=False):
        self.shown=[]
        def show(ticket,accepted,failed):
            self.shown.append((ticket,accepted,failed))
            return not fail
        return ui.Presenter(self.service,self.channel,lambda:types.SimpleNamespace(show=show),clock=lambda:100)

    def test_actual_home_signal_required_and_confirmed_only_after_user_click(self):
        p=self.presenter()
        self.assertFalse(p.tick());self.assertEqual(self.shown,[])
        self.signal=(1,self.event);self.assertTrue(p.tick())
        self.assertFalse(p.tick());self.assertEqual(len(self.shown),1)
        self.assertFalse(self.saved()['reinforcements']['awards']['stage-a']['notified'])
        self.shown[0][1]();self.assertFalse(p.tick())
        self.assertTrue(self.saved()['reinforcements']['awards']['stage-a']['notified'])
        self.assertEqual(len(self.shown),1)
        self.signal=(2,self.event);self.assertFalse(p.tick())

    def test_confirmation_preserves_changes_made_since_window_opened(self):
        ticket=ui.offer(self.root,[self.definition],self.event)
        self.state['receipts']['later-result']={'result':'NOERR'}
        self.state['reinforcements']['awards']['stage-a']['used']=2
        self.state['reinforcements']['draw_receipts']['later-draw']={'loan':{'card_id':123}}
        self.save();before=self.saved()
        self.assertTrue(ui.confirm(self.root,ticket));self.assertTrue(ui.confirm(self.root,ticket))
        expected=copy.deepcopy(before);expected['reinforcements']['awards']['stage-a']['notified']=True
        self.assertEqual(self.saved(),expected)
        self.assertEqual(runtime.get(self.conn,'unrelated'),{'owned':[1,2],'progress':12})

    def test_failed_show_and_process_restart_do_not_consume_award(self):
        self.signal=(1,self.event);before=self.saved();p=self.presenter(fail=True)
        self.assertFalse(p.tick());self.assertEqual(self.saved(),before)
        p=self.presenter();self.assertTrue(p.tick());self.assertEqual(self.saved(),before)
        restarted=self.presenter();self.assertTrue(restarted.tick())
        self.assertEqual(self.saved(),before)

    def test_stale_run_deleted_event_and_completed_tournament_cannot_confirm_new_awards(self):
        ticket=ui.offer(self.root,[self.definition],self.event)
        self.state['run_id']='new-run';self.state['reinforcements']['run_id']='new-run';self.save()
        self.assertFalse(ui.confirm(self.root,ticket))
        self.assertIsNone(ui.offer(self.root,[],self.event))
        self.assertIsNone(ui.offer(self.root,[dict(self.definition,enabled=False)],self.event))
        self.state['completed']=True;self.save()
        self.assertIsNone(ui.offer(self.root,[self.definition],self.event))

    def test_existing_unnotified_award_is_recovered_without_regranting(self):
        self.state['reinforcements']['awards']['stage-a'].update(granted=10,used=10);self.save()
        ticket=ui.offer(self.root,[self.definition],self.event)
        self.assertEqual((ticket['granted'],ticket['available']),(10,0))
        before=self.saved();self.assertTrue(ui.confirm(self.root,ticket))
        before['reinforcements']['awards']['stage-a']['notified']=True
        self.assertEqual(self.saved(),before)
        self.state.pop('reinforcements');self.save()
        self.assertIsNone(ui.offer(self.root,[self.definition],self.event))

    def test_other_event_or_open_schedule_never_opens_reward(self):
        self.signal=(1,self.event+1);p=self.presenter();self.assertFalse(p.tick())
        self.signal=(2,self.event)
        import native_tournament_schedule_ui as schedule
        with patch.object(schedule,'_HOST',types.SimpleNamespace(pending=False,shown=True)):
            self.assertFalse(p.tick());self.assertEqual(self.shown,[])

    def test_failed_show_does_not_retry_over_a_later_screen_using_stale_home_signal(self):
        now=[100];self.signal=(1,self.event);p=self.presenter(fail=True);p.clock=lambda:now[0]
        self.assertFalse(p.tick());self.assertEqual(len(self.shown),1)
        now[0]=104
        self.assertFalse(p.tick());self.assertEqual(len(self.shown),1)


if __name__=='__main__':unittest.main()
