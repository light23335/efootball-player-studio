import copy,json,sqlite3,struct,unittest
from unittest.mock import patch
import league_availability as availability
from league_availability import DAYS,DURATION,KEY,REVISION,install,project,targets,window

NOW=1793872800
OLD_END=1793843999


def entry():
    return {'result':'NOERR','msgid':'CMD_GET_MAINMENU_MATCH_CREATIVE_INFO','league_info':
        {'league_banner':'/banner/league/000057/original','league_phase_start_time':1791424800,
         'league_phase_end_time':OLD_END},'event_info_list':[{'event_end_time':123}],
        'campaign_pass_info':{'phase_end_time':456}}


def detail():
    return {'result':'NOERR','msgid':'CMD_GET_LEAGUE_COM_INFO','league_info':
        {'phase_id':56,'phase_start_time':1786586400,'phase_end_time':1893455999,
         'current_division':2,'current_point':1587,'personal_best_division':1,
         'round_match_count':7,'rating':1587,'is_promoted':'NO','is_relegated':'NO'}}


class LeagueAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.db.execute('create table meta(key text primary key,value text)')
        self.db.execute('create table owned(serial integer primary key,payload text)')
        self.db.execute('insert into owned values(1,?)',('unchanged trained player',))
        self.saved={'ai_division_state_v1':{'division':2,'points':1587,'round':9,'matches':7},
                    'ai_division_active_match':{'game_id':12345,'started':True},
                    'ai_division_result_12344':{'result':'NOERR','score':[2,1]},
                    'league_ranking':'original ranking'}
        self.db.executemany('insert into meta values(?,?)',[(k,json.dumps(v))for k,v in self.saved.items()]);self.db.commit()

    def assert_saved(self):
        self.assertEqual({k:json.loads(v)for k,v in self.db.execute('select * from meta where key!=?',(KEY,))},self.saved)
        self.assertEqual(self.db.execute('select * from owned').fetchall(),[(1,'unchanged trained player')])

    def test_original_capture_is_expired_and_saved_window_is_exactly_2500_days(self):
        self.assertLess(OLD_END,NOW)
        value=window(self.db,NOW)
        self.assertEqual(value['end']-NOW,2500*86400);self.assertEqual(value['days'],2500)
        self.assertEqual(value['end']-value['start'],DURATION);self.assert_saved()

    def test_all_three_original_native_paths_share_one_window(self):
        value=window(self.db,NOW);home=entry();info=detail()
        result={'result':'NOERR','game_end_result':{'extra_match_result':{'league_match_result':copy.deepcopy(info)}}}
        for response in (home,info,result):
            project(response,value)
            self.assertTrue(targets(response))
            for row,start,end in targets(response):
                self.assertLessEqual(row[start],NOW);self.assertEqual(row[end],NOW+DURATION)
        self.assertEqual(info['league_info']['phase_id'],56)
        self.assertEqual(info['league_info']['rating'],1587);self.assert_saved()

    def test_deadline_does_not_drift_between_requests_or_process_reopen(self):
        first=window(self.db,NOW)
        for delta in (1,60,86400,DURATION-1):self.assertEqual(window(self.db,NOW+delta),first)
        copydb=sqlite3.connect(':memory:');self.addCleanup(copydb.close)
        copydb.deserialize(self.db.serialize())
        self.assertEqual(window(copydb,NOW+1000),first)

    def test_expired_window_renews_only_its_own_metadata(self):
        first=window(self.db,NOW);later=window(self.db,first['end'])
        self.assertEqual(later['start'],first['end']);self.assertEqual(later['end']-later['start'],DURATION)
        self.assert_saved()

    def test_local_clock_rollback_reanchors_once_without_state_reset(self):
        window(self.db,NOW);earlier=window(self.db,NOW-3600)
        self.assertEqual(earlier['start'],NOW-3600)
        self.assertEqual(earlier,window(self.db,NOW-3500));self.assert_saved()

    def test_other_events_campaign_dates_and_error_responses_unchanged(self):
        value=window(self.db,NOW);response=entry();before=copy.deepcopy(response)
        project(response,value)
        self.assertEqual(response['event_info_list'],before['event_info_list'])
        self.assertEqual(response['campaign_pass_info'],before['campaign_pass_info'])
        for response in ({'result':'ERR_INVALID_PARAM','league_info':detail()['league_info']},
                         {'result':'NOERR','phase_end_time':7,'season_info':detail()['league_info']},
                         {'result':'NOERR','league_info':{'phase_end_time':7}}):
            old=copy.deepcopy(response);project(response,value);self.assertEqual(response,old)

    def test_projection_changes_only_the_native_availability_fields(self):
        response=detail();old=copy.deepcopy(response);value=window(self.db,NOW);project(response,value)
        for key in ('phase_start_time','phase_end_time'):old['league_info'][key]=response['league_info'][key]
        self.assertEqual(response,old)

    def test_foreign_transaction_is_not_committed(self):
        self.db.execute('insert into owned values(2,?)',('transaction sentinel',))
        window(self.db,NOW);self.assertTrue(self.db.in_transaction)
        self.db.rollback()
        self.assertIsNone(self.db.execute('select value from meta where key=?',(KEY,)).fetchone())
        self.assert_saved()

    def test_gateway_wrapper_refreshes_cached_entry_detail_and_receipt_without_mutating_cache(self):
        class Logic:
            def handle(self,command,request):return copy.deepcopy(self.cached[command])
        logic=Logic();logic.conn=self.db;logic.cached={'entry':entry(),'detail':detail()}
        old=copy.deepcopy(logic.cached);now=[NOW]
        self.assertTrue(install(logic,lambda:now[0]));self.assertFalse(install(logic,lambda:0))
        first=logic.handle('entry',{})['league_info']['league_phase_end_time'];now[0]+=600
        second=logic.handle('detail',{})['league_info']['phase_end_time']
        self.assertEqual(first,second);self.assertEqual(logic.cached,old);self.assert_saved()

    def test_install_none_does_nothing_and_invalid_clock_does_not_write(self):
        self.assertFalse(install(None))
        for bad in (-1,float('nan'),float('inf'),'today',None):
            with self.assertRaises(ValueError):window(self.db,bad)
        self.assertIsNone(self.db.execute('select value from meta where key=?',(KEY,)).fetchone())

    def test_old_phase_opening_is_not_moved_forward_by_replies(self):
        value=window(self.db,NOW);response=entry();opening=response['league_info']['league_phase_start_time']
        project(response,value)
        self.assertEqual(response['league_info']['league_phase_start_time'],opening)
        self.assertEqual(response['league_info']['league_phase_end_time'],NOW+DURATION)

    def test_startup_publishes_existing_v1_deadline_before_any_menu_request(self):
        first=window(self.db,NOW-100)
        class Logic:
            def handle(self,*args):return {'result':'NOERR'}
        logic=Logic();logic.conn=self.db
        buffer=bytearray(133184);sentinel=bytes([83])*40;buffer[:40]=sentinel
        channel=type('Channel',(),{'buffer':buffer,'offset':0,'fence':lambda s:None})()
        with patch.object(availability,'_CHANNEL',channel),patch.object(availability,'_WINDOW',None):
            self.assertTrue(install(logic,lambda:NOW))
            seq,magic,start,end=struct.unpack_from('<IIQQ',buffer,40)
            self.assertEqual(seq,2);self.assertEqual(magic,availability.NATIVE_MAGIC)
            self.assertEqual((start,end),(first['start'],first['end']))
            self.assertEqual(bytes(buffer[:40]),sentinel)
            self.assertEqual(window(self.db,NOW),first);self.assert_saved()

    def test_native_channel_ready_before_or_after_startup_and_home_publication_keeps_window(self):
        import tournament_home as home
        value=window(self.db,NOW)
        for ready_first in (False,True):
            buffer=bytearray(home.SCHEMA['bytes']);channel=home.Channel(buffer,0,lambda:None)
            with patch.object(availability,'_CHANNEL',None),patch.object(availability,'_WINDOW',None):
                if ready_first:availability.channel_ready(channel)
                availability.publish_native(value)
                if not ready_first:availability.channel_ready(channel)
                snapshot=bytes(buffer[40:64]);self.assertNotEqual(snapshot,bytes(24))
                channel.publish(home.encode({}),0);self.assertEqual(bytes(buffer[40:64]),snapshot)
                channel.publish(home.encode({}),0);self.assertEqual(bytes(buffer[40:64]),snapshot)


if __name__=='__main__':unittest.main()
