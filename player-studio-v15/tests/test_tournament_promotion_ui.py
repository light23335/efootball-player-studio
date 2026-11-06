import copy,json,sqlite3,tempfile,unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tournament_promotion as promotion
import tournament_promotion_ui as ui
import tournament_home as home
from tournament_runtime import PREFIX
from test_tournament_promotion import definition,play
import tournament_rules as rules


class Channel:
    def __init__(self):self.menu={'event':205060988,'generation':1,'tick':1};self.state=None;self.requests=[];self.cleared=[]
    def promotion_menu(self):return self.menu
    def promotion_status(self):return self.state
    def promotion_request(self,ticket):self.requests.append(copy.deepcopy(ticket))
    def promotion_clear(self,ticket):self.cleared.append(copy.deepcopy(ticket));return True
    def status(self,ticket,status):self.state={'status':status,'token':ticket['token'][:32],'generation':ticket['generation'],'reason':0}


class PromotionUITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.path=self.root/'outputs/efootball/local-club.sqlite3';self.path.parent.mkdir(parents=True)
        self.current=rules.start(definition(4),0);play(self.current)
        self.current['reinforcements']={'marker':'existing rental/receipts retained'}
        self.definition=dict(self.current['definition'],event_id=205060988)
        self.key=PREFIX+self.definition['uuid']
        with closing(sqlite3.connect(self.path))as conn,conn:
            conn.execute('create table meta(key text primary key,value text)')
            conn.execute('insert into meta values(?,?)',(self.key,json.dumps(self.current)))
            conn.execute('insert into meta values(?,?)',('AI_DIVISION_SENTINEL','unchanged'))
        self.service=SimpleNamespace(root=self.root,definitions=lambda:[self.definition]);self.channel=Channel();self.now=0
        self.presenter=ui.Presenter(self.service,self.channel,clock=lambda:self.now,process='process-A')

    def state(self):
        with closing(sqlite3.connect(self.path))as conn:
            self.assertEqual(conn.execute('select value from meta where key=?',('AI_DIVISION_SENTINEL',)).fetchone()[0],'unchanged')
            return json.loads(conn.execute('select value from meta where key=?',(self.key,)).fetchone()[0])

    def test_delivery_is_committed_before_native_publication_and_only_user_confirmation_consumes(self):
        def submit(ticket):
            state=self.state();delivery=state[promotion.KEY]['delivery']
            self.assertEqual(delivery['token'],ticket['token'])
            self.channel.requests.append(copy.deepcopy(ticket))
        self.channel.promotion_request=submit
        self.assertTrue(self.presenter.tick());ticket=self.presenter.ticket
        self.channel.status(ticket,1);self.presenter.tick()
        self.assertEqual(promotion.pending(self.state())['id'],ticket['event_id'])
        self.channel.status(ticket,2);self.presenter.tick()
        self.assertEqual(self.state()[promotion.KEY]['events'][0]['status'],'confirmed')
        self.assertIsNotNone(self.presenter.ticket) # Wait for original fade-out before another window.
        self.channel.status(ticket,5);self.presenter.tick();self.assertIsNone(self.presenter.ticket)
        actual=self.state();before=copy.deepcopy(self.current)
        actual.pop(promotion.KEY);before.pop(promotion.KEY)
        self.assertEqual(actual,before)

    def test_confirmed_event_not_replayed_and_next_event_has_its_own_token(self):
        self.presenter.tick();first=self.presenter.ticket
        self.channel.status(first,5);self.presenter.tick();self.presenter.tick()
        second=self.presenter.ticket
        self.assertNotEqual(second['event_id'],first['event_id']);self.assertNotEqual(second['token'],first['token'])
        self.channel.status(second,5);self.presenter.tick();self.presenter.tick()
        self.assertIsNone(self.presenter.ticket);self.assertEqual(len(self.channel.requests),2)

    def test_unconfirmed_close_is_retained_until_new_menu_and_restart_changes_delivery(self):
        self.presenter.tick();first=self.presenter.ticket
        self.channel.status(first,4);self.presenter.tick()
        self.now=10;self.presenter.tick();self.assertEqual(len(self.channel.requests),1)
        self.channel.menu.update(generation=2,tick=2);self.presenter.tick()
        second=self.presenter.ticket
        self.assertEqual(first['event_id'],second['event_id']);self.assertNotEqual(first['token'],second['token'])
        self.assertFalse(ui._receipt(self.root,first,True))
        self.assertTrue(ui._receipt(self.root,second,True))

    def test_stale_signal_foreign_token_and_failed_persistence_never_consume_progression(self):
        with patch.object(ui,'offer',return_value=None):self.presenter.tick()
        self.now=3;self.assertFalse(self.presenter.tick());self.assertEqual(self.channel.requests,[])
        self.channel.menu['tick']=2;self.presenter.tick();ticket=self.presenter.ticket
        self.channel.state={'status':2,'token':'f'*32,'generation':ticket['generation'],'reason':0}
        self.presenter.tick();self.assertEqual(self.state()[promotion.KEY]['events'][0]['status'],'presenting')
        self.channel.status(ticket,2)
        with patch.object(ui,'_receipt',side_effect=OSError('fixture write failure')):
            with self.assertRaises(OSError):self.presenter.tick()
        self.assertFalse(self.presenter.confirmed);self.presenter.tick()
        self.assertTrue(self.presenter.confirmed)

    def test_buffer_has_separate_request_status_and_menu_sequences(self):
        data=bytearray(home.SCHEMA['bytes']);channel=home.Channel(data,0,lambda:None);at=home.SCHEMA['promotion_offset']
        channel.promotion_enable();self.assertEqual(int.from_bytes(data[at+912:at+916],'little'),1)
        ticket=ui.offer(self.root,[self.definition],205060988,1,'process-A')
        sequence=channel.promotion_request(ticket);self.assertEqual(sequence,2)
        self.assertEqual(data[at+56:at+72].hex(),ticket['token'][:32])
        import struct
        struct.pack_into('<IIQQQQ',data,at,2,205060988,0,0,1,99)
        self.assertEqual(channel.promotion_menu(),{'event':205060988,'generation':1,'tick':99})
        struct.pack_into('<II16s',data,at+848,2,2,bytes.fromhex(ticket['token'][:32]))
        struct.pack_into('<Q',data,at+904,1)
        self.assertTrue(channel.promotion_busy());self.assertEqual(channel.promotion_status()['token'],ticket['token'][:32])
        self.assertTrue(channel.promotion_clear(ticket));self.assertEqual(int.from_bytes(data[at+40:at+44],'little'),0)

    def test_false_receipt_retains_both_confirmation_and_release_for_retry(self):
        for status in (3,5):
            with self.subTest(native_status=status):
                presenter=ui.Presenter(self.service,self.channel,clock=lambda:self.now,process='process-false-'+str(status))
                self.channel.state=None;self.channel.cleared=[]
                self.assertTrue(presenter.tick());ticket=presenter.ticket
                self.channel.status(ticket,status)
                with patch.object(ui,'_receipt',return_value=False):
                    self.assertFalse(presenter.tick())
                self.assertIs(presenter.ticket,ticket);self.assertFalse(presenter.confirmed)
                self.assertEqual(self.channel.cleared,[])
                self.assertTrue(promotion.pending(self.state()))
                presenter.tick();self.assertIsNone(presenter.ticket)

    def test_missing_database_keeps_native_confirmation_until_storage_returns(self):
        self.presenter.tick();ticket=self.presenter.ticket;self.channel.status(ticket,5)
        missing=self.path.with_suffix('.temporarily-unavailable');self.path.rename(missing)
        try:
            self.assertFalse(self.presenter.tick());self.assertFalse(self.presenter.confirmed)
            self.assertIs(self.presenter.ticket,ticket);self.assertEqual(self.channel.cleared,[])
        finally:missing.rename(self.path)
        self.presenter.tick();self.assertIsNone(self.presenter.ticket)
        self.assertEqual(self.state()[promotion.KEY]['events'][0]['status'],'confirmed')

    def test_superseded_delivery_is_handed_off_without_confirming_new_token(self):
        self.presenter.tick();old=self.presenter.ticket
        new=ui.offer(self.root,[self.definition],205060988,2,'process-B')
        self.assertNotEqual(old['token'],new['token'])
        self.channel.status(old,5);self.assertFalse(self.presenter.tick())
        self.assertIsNone(self.presenter.ticket);self.assertFalse(self.presenter.confirmed)
        journal=self.state()[promotion.KEY]
        self.assertEqual(journal['delivery']['token'],new['token'])
        self.assertEqual(journal['events'][0]['status'],'presenting')

    def test_replaced_run_is_handed_off_without_writing_old_receipt_into_new_progress(self):
        self.presenter.tick();old=self.presenter.ticket
        current=rules.start(self.current['definition'],9)
        with closing(sqlite3.connect(self.path))as conn,conn:
            conn.execute('update meta set value=? where key=?',(json.dumps(current),self.key))
        before=self.state();self.channel.status(old,5)
        self.assertFalse(self.presenter.tick());self.assertIsNone(self.presenter.ticket)
        self.assertFalse(self.presenter.confirmed);self.assertEqual(self.state(),before)

if __name__=='__main__':unittest.main()
