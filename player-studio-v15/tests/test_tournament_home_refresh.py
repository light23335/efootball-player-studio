"""A match result refreshes the native home without re-entering the event."""
import copy,sqlite3,struct,unittest,uuid
from types import SimpleNamespace
from unittest.mock import patch
import tournament_home as home
import tournament_runtime as runtime
import tournament_rules as rules


class HomeRefreshTests(unittest.TestCase):
    def test_result_publishes_next_leg_before_reply_and_preserves_other_competitions(self):
        conn=sqlite3.connect(':memory:');self.addCleanup(conn.close)
        conn.execute('create table meta(key primary key,value)')
        definitions=runtime.configuration([{'uuid':str(uuid.uuid4()),'name':name,'enabled':True,
            'team_ids':[101,127],'player_team_id':127,'difficulty':'HARDEST',
            'stages':[{'type':'knockout','legs':2}]}for name in('Cup A','Cup B')])
        first,second=[runtime.state(conn,t)for t in definitions]
        fixture=runtime.next_fixture(first);gid=123
        first['active']={'fixture_id':fixture['id'],'game_id':gid,'started':True}
        runtime.put(conn,runtime.PREFIX+definitions[0]['uuid'],first)
        runtime.put(conn,'unrelated-save',{'wins':8,'exp':9000})
        buffer=bytearray(home.SCHEMA['bytes'])
        buffer[home.SCHEMA['promotion_offset']:]=b'P'*home.SCHEMA['promotion_bytes']
        channel=home.Channel(buffer,0,lambda:None)
        service=runtime.Service(lambda:{'tournaments':definitions,'tournament_team_names':{'101':'Arsenal','127':'Bayern'}},'.',None)
        logic=SimpleNamespace(conn=conn)
        def settle(logic,t,current,request):
            rules.record(current,current['active']['fixture_id'],2,1)
            current.pop('active');runtime.next_fixture(current)
            return {'game_id':gid}
        def reply(logic,t,current,request,settled):
            current['receipts'][str(gid)]={'result':'NOERR'}
            return {'result':'NOERR'}
        with patch.object(home,'_CHANNEL',channel),patch.object(service,'settle_result',side_effect=settle),patch.object(service,'result_reply',side_effect=reply),patch.object(service,'close_result'),patch.dict('sys.modules',{'cup16_mode':SimpleNamespace(game_id=lambda r:r.get('game_id'))}):
            runtime.publish_saved_home(conn,definitions,service.names())
            previous=bytes(buffer);before=copy.deepcopy(first)
            out=service.handle(logic,'CMD_GET_VSCOM_GAME_RESULT',{'game_id':gid},lambda *a:self.fail('fell through'))
            saved=runtime.get(conn,runtime.PREFIX+definitions[0]['uuid'])
            self.assertEqual(out['result'],'NOERR')
            self.assertNotEqual(bytes(buffer),previous)
            self.assertEqual(struct.unpack_from('<II',buffer),(1,2))
            self.assertEqual(bytes(buffer[64:home.SCHEMA['promotion_offset']]),home.encode({runtime.event_id(t):home.model(s,service.names(),membership={'kind':'club','entity_id':127})for t,s in zip(definitions,(saved,second))}))
            self.assertEqual(buffer[home.SCHEMA['promotion_offset']:],b'P'*home.SCHEMA['promotion_bytes'])
            self.assertEqual(saved['run_id'],before['run_id'])
            self.assertIn(str(gid),saved['receipts'])
            self.assertEqual(home.model(saved)['remaining'],'1 场')
            self.assertIn('第 2 回合',home.model(saved)['fixture'])
            self.assertEqual(runtime.get(conn,runtime.PREFIX+definitions[1]['uuid']),second)
            self.assertEqual(runtime.get(conn,'unrelated-save'),{'wins':8,'exp':9000})


if __name__=='__main__':unittest.main()
