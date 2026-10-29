import copy
import json
import random
import sqlite3
import threading
import unittest

import ai_division_sessions as s


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.execute('create table meta(key text primary key,value text)')
        self.entries=s.Entries('runtime-A')
    def tearDown(self):self.db.close()

    def seeded(self):
        entry=self.entries.draw(self.db,None,random.Random(3),'shuffle_bag')
        entry['game_id']=123
        opponent={s.MARKER:{'entry_id':entry['entry_id'],'process_id':entry['process_id'],
                            'draw_state_after':entry['draw_state_after']},'player_list':[1,2,3]}
        active={'game_id':123,'division':3,'round':7,'started':True,'history_own':{'old':True},'opponent':opponent}
        with self.db:
            self.db.execute('begin immediate');s.write(self.db,'ai_division_active_match',active)
            self.entries.commit(self.db,entry,opponent[s.MARKER])
        return active,entry

    def test_six_style_bags_and_no_cross_bag_repeat(self):
        state={};rng=random.Random(28);styles=[]
        for _ in range(120):
            style,state=s.preview_draw(state,rng);styles.append(style)
        for i in range(0,120,6):self.assertEqual(set(styles[i:i+6]),set(s.STYLES))
        for i in range(6,120,6):self.assertNotEqual(styles[i],styles[i-1])
        self.assertEqual(state['draw_sequence'],120)

    def test_failed_generation_consumes_nothing_and_bag_survives_restart(self):
        active,entry=self.seeded();before=s.read(self.db,s.DRAW_KEY)
        self.entries.draw(self.db,active,random.Random(7),'shuffle_bag')
        self.assertEqual(s.read(self.db,s.DRAW_KEY),before)
        restarted=s.Entries('runtime-B')
        self.assertFalse(restarted.reusable(self.db,active))
        next_entry=restarted.draw(self.db,active,random.Random(8),'shuffle_bag')
        self.assertEqual(next_entry['style'],before['bag'][0])
        self.assertEqual(next_entry['draw_state_after']['draw_sequence'],2)

    def test_retries_ignore_request_id_changes_and_time(self):
        active,entry=self.seeded()
        self.assertTrue(self.entries.reusable(self.db,active))
        self.assertTrue(self.entries.reusable(self.db,copy.deepcopy(active)))
        self.assertEqual(s.read(self.db,s.DRAW_KEY)['draw_sequence'],1)

    def test_explicit_exit_new_round_atomic_replacement_and_stale_callback(self):
        active,entry=self.seeded()
        self.assertTrue(self.entries.leave(self.db,'CMD_GET_MAINMENU_INFO'))
        self.assertFalse(self.entries.leave(self.db,'duplicate menu retry'))
        self.assertFalse(self.entries.reusable(self.db,active))
        next_entry=self.entries.draw(self.db,active,random.Random(4),'shuffle_bag')
        out={'player_list':[4,5,6],s.MARKER:{'entry_id':next_entry['entry_id']}}
        with self.db:
            self.db.execute('begin immediate')
            replacement=self.entries.replace_active(self.db,active,out,next_entry)
        self.assertNotEqual(replacement['game_id'],active['game_id'])
        self.assertEqual(replacement['round'],active['round'])
        self.assertEqual(replacement['division'],active['division'])
        self.assertFalse(replacement['started']);self.assertNotIn('history_own',replacement)
        self.assertEqual(s.read(self.db,s.DRAW_KEY)['draw_sequence'],2)
        self.assertTrue(self.entries.stale_callback(self.db,{'game_id':123}))
        self.assertFalse(self.entries.stale_callback(self.db,{'game_id':replacement['game_id']}))
        self.assertFalse(self.entries.stale_callback(self.db,{'game_id':888}))
        self.assertEqual(self.db.execute('select count(*) from personal_ai_entries').fetchone()[0],2)

    def test_replacement_failure_rolls_back_snapshot_and_rotation_together(self):
        active,entry=self.seeded();before=self.db.iterdump();before=list(before)
        with self.assertRaises(RuntimeError):
            with self.db:
                self.db.execute('begin immediate')
                e=self.entries.draw(self.db,active,random.Random(7),'shuffle_bag')
                self.entries.replace_active(self.db,active,{s.MARKER:{}},e)
                raise RuntimeError('native preparation failure')
        self.assertEqual(list(self.db.iterdump()),before)

    def test_snapshot_recovers_rotation_after_postcommit_index_failure(self):
        active,entry=self.seeded()
        with self.db:s.write(self.db,s.DRAW_KEY,{'draw_sequence':0})
        next_entry=self.entries.draw(self.db,active,random.Random(7),'shuffle_bag')
        self.assertEqual(next_entry['draw_state_after']['draw_sequence'],2)
        self.assertEqual(next_entry['style'],entry['draw_state_after']['bag'][0])

    def test_bridge_only_accepted_explicit_menu_exit_invalidates_round(self):
        active,entry=self.seeded();calls=[]
        class Logic:
            def __init__(self,conn):self.conn=conn
            def handle(self,command,req):calls.append(command);return {'result':req.get('result','NOERR')}
        logic=Logic(self.db);invalidated=[]
        s.bridge(logic,self.entries,threading.RLock(),lambda:invalidated.append(True))
        for command in ('CMD_SET_GAMERELAY_QUALITY','CMD_GET_MYCLUB_SQUAD_INFO','CMD_CHECK_MATCH_ENABLE'):
            logic.handle(command,{})
            self.assertTrue(self.entries.reusable(self.db,active))
        logic.handle('CMD_GET_MAINMENU_INFO',{'result':'ERR_BUSY'})
        self.assertTrue(self.entries.reusable(self.db,active))
        logic.handle('CMD_GET_MAINMENU_INFO',{})
        self.assertEqual(invalidated,[True]);self.assertFalse(self.entries.reusable(self.db,active))
        result=logic.handle('CMD_GET_VSCOM_GAME_RESULT',{'game_id':123,'rqid':1})
        self.assertEqual(result['result'],'ERR_INVALID_PARAM')
        self.assertNotIn('CMD_GET_VSCOM_GAME_RESULT',calls)

    def test_disabled_bridge_leaves_original_native_callbacks_and_menu_untouched(self):
        active,entry=self.seeded();calls=[]
        class Logic:
            def __init__(self,conn):self.conn=conn
            def handle(self,command,req):calls.append(command);return {'result':'NOERR'}
        logic=Logic(self.db)
        s.bridge(logic,self.entries,threading.RLock(),enabled=lambda:False)
        logic.handle('CMD_GET_MAINMENU_INFO',{})
        self.assertTrue(self.entries.reusable(self.db,active))
        result=logic.handle('CMD_GET_VSCOM_GAME_RESULT',{'game_id':999,'rqid':1})
        self.assertEqual(result['result'],'NOERR');self.assertEqual(len(calls),2)


if __name__=='__main__':unittest.main()
