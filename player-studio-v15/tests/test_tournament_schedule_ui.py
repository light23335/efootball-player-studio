import copy
import base64
from contextlib import closing
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tournament_rules as rules
import tournament_schedule_ui as ui
import native_tournament_schedule_ui as native


def definition(n=8, stages=None):
    return {'uuid': str(uuid.uuid4()), 'name': '冠军之路', 'team_ids': list(range(1,n+1)),
            'player_team_id': 1, 'stages': stages or [{'type':'knockout','legs':2,'advance':1,
            'away_goals':True,'round_overrides':{'2':{'legs':1}}}]}


def play_one(s):
    f = rules.due(s)[0]
    rules.record(s, f['id'], 2, 1, penalties=[5,4] if rules.needs_decision(s,f,[2,1]) else None)


def db(root, s):
    path = root/'outputs/efootball/local-club.sqlite3'
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute('CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)')
        conn.execute('INSERT INTO meta VALUES (?, ?)', (ui.PREFIX+s['uuid'],json.dumps(s)))
        conn.commit()
    return path


class ScheduleTests(unittest.TestCase):
    def test_all_difficulties_render_chinese_labels_without_touching_progress(self):
        s=rules.start(definition(),5);play_one(s)
        for code,label in rules.DIFFICULTIES.items():
            current=copy.deepcopy(s);current['difficulty']=code;before=copy.deepcopy(current)
            view=ui.presentation(current)
            self.assertEqual((view['difficulty'],view['difficulty_name']),(code,label))
            self.assertNotIn('division',view)
            self.assertEqual(current,before)
            self.assertEqual(current['run_id'],s['run_id'])
            self.assertEqual(current['fixtures'],s['fixtures'])
        legacy=copy.deepcopy(s);legacy.pop('difficulty',None);legacy['division']=1
        view=ui.presentation(legacy)
        self.assertEqual((view['difficulty'],view['difficulty_name']),('LEGEND','传奇'))

    def test_view_never_mutates_state_even_when_cpu_fixtures_are_due(self):
        s = rules.start(definition(), 5)
        before = copy.deepcopy(s)
        for _ in range(3):
            view = ui.presentation(s)
            ui.overview_html(s)
        self.assertEqual(s, before)
        self.assertEqual(len(view['fixtures']),8)
        self.assertFalse(any(f['played'] for f in view['fixtures']))
        self.assertTrue(all(f['penalties'] is None and f['penalties_allowed'] for f in view['fixtures']))
        self.assertEqual([r['generated'] for r in view['stages'][0]['bracket']], [True,False,False])
        self.assertTrue(all(n['teams']==[None,None] for r in view['stages'][0]['bracket'][1:] for n in r['nodes']))

    def test_all_knockout_sizes_have_exact_native_edges(self):
        for n in (2,3,5,16,31,64,128):
            s = rules.start(definition(n), 9)
            while not s['completed']:
                play_one(s)
            bracket = ui.presentation(s)['stages'][0]['bracket']
            nodes = {node['id']:node for r in bracket for node in r['nodes']}
            self.assertEqual(len(nodes), (1<<(n-1).bit_length())-1)
            for node in nodes.values():
                if node['sources']:
                    winners = [nodes[key]['winner'] for key in node['sources']]
                    self.assertEqual(node['teams'], winners, (n,node))
            self.assertEqual(bracket[-1]['nodes'][0]['winner'],s['champion'])

    def test_historical_group_tables_survive_playoff_and_final(self):
        s = rules.start(definition(12,[{'type':'groups','groups':4,'advance_per_group':1,'playoff_per_group':2},
             {'type':'playoff','advance':4}, {'type':'knockout','advance':1}]),6)
        while s['stage_index']==0:
            play_one(s)
        v = ui.presentation(s)
        self.assertEqual(len(v['stages'][0]['groups']),4)
        self.assertEqual(v['stages'][0]['groups'][0]['table'],s['stage_history'][0]['tables'][0])
        self.assertEqual(v['stages'][1]['rules']['bypass_count'],4)
        self.assertEqual(v['stages'][2]['status'],'pending')
        self.assertEqual(v['stages'][2]['bracket'],[])
        while not s['completed']:
            play_one(s)
        final = ui.presentation(s)
        self.assertTrue(final['completed'])
        self.assertEqual(v['stages'][0]['groups'],final['stages'][0]['groups'])

    def test_odd_league_byes_and_rules(self):
        s = rules.start(definition(5,[{'type':'league','cycles':2,'advance_per_group':1}]),1)
        v=ui.presentation(s); stage=v['stages'][0]
        self.assertEqual(len(stage['byes']),10)
        for r in range(10):
            games=[f for f in v['fixtures'] if f['round']==r]
            bye=next(b['team'] for b in stage['byes'] if b['round']==r)
            self.assertNotIn(bye,[f[k] for f in games for k in ('home','away')])
        self.assertEqual(stage['rules']['cycles'],2)

    def test_scores_extra_time_and_penalties_are_preserved_in_home_order(self):
        s=rules.start(definition(2),4)
        f=rules.due(s)[0]
        rules.record(s,f['id'],3,2,extra=[1,1])  # single-leg final override
        shown=ui.presentation(s)['fixtures'][0]
        self.assertEqual(shown['score'],[3,2])
        self.assertEqual(shown['extra_time_score'],[1,1])
        s=rules.start(definition(2),4);f=rules.due(s)[0]
        rules.record(s,f['id'],1,1,penalties=[4,5])
        self.assertEqual(ui.presentation(s)['fixtures'][0]['penalties'],[4,5])

    def test_eliminated_player_is_not_shown_as_waiting_in_same_stage(self):
        s=rules.start(definition(8,[{'type':'knockout','legs':1,'advance':1}]),2)
        for _ in range(4):
            f=rules.due(s)[0]
            score=[0,1] if f['home']==1 else [1,0]
            rules.record(s,f['id'],*score)
        self.assertEqual(s['round'],1)
        self.assertEqual(ui.presentation(s)['player_status'],'eliminated')
        self.assertIsNone(ui.presentation(s)['next_fixture_id'])

    def test_large_double_round_league_is_complete_and_compact(self):
        s=rules.start(definition(128,[{'type':'league','cycles':2,'advance_per_group':1}]),3)
        v=ui.presentation(s)
        self.assertEqual(len(v['fixtures']),16256)
        self.assertEqual(len(v['stages'][0]['groups'][0]['table']),128)
        raw=ui.overview_html(s)
        self.assertLess(len(raw),8*1024*1024)

    def test_inert_json_handles_malicious_team_and_stage_names(self):
        attack='</script><script>window.pwned=true</script>&\u2028'
        s=rules.start(definition(),2);s['definition']['name']=attack
        raw=ui.overview_html(s,{'1':attack}).decode()
        self.assertNotIn(attack,raw)
        class Parser(HTMLParser):
            def __init__(self):super().__init__();self.record=False;self.data=''
            def handle_starttag(self,t,a):
                if t=='script' and dict(a).get('id')=='schedule-data':self.record=True
            def handle_endtag(self,t):
                if t=='script':self.record=False
            def handle_data(self,text):
                if self.record:self.data+=text
        p=Parser();p.feed(raw);data=json.loads(p.data)
        self.assertEqual(data['name'],attack)
        self.assertEqual(data['teams'][0]['name'],attack)

    def test_database_is_pure_read_and_missing_save_is_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);s=rules.start(definition(),2)
            self.assertIsNone(ui.read_saved(root,s['uuid']))
            self.assertFalse((root/'outputs').exists())
            p=db(root,s);before=hashlib.sha256(p.read_bytes()).hexdigest()
            self.assertIsNone(ui.saved_overview(root,str(uuid.uuid4())))
            self.assertIsNotNone(ui.saved_overview(root,s['uuid']))
            self.assertEqual(before,hashlib.sha256(p.read_bytes()).hexdigest())
            with closing(sqlite3.connect(p)) as conn:
                self.assertEqual(conn.execute('select count(*) from meta').fetchone()[0],1)

    def test_android_embedded_assets_work_without_real_file_paths(self):
        module=types.ModuleType('isolated_schedule')
        module.__file__='/virtual/chaquopy/app.imy/tournament_schedule_ui.pyc'
        source=ui.runtime_source()
        exec(compile(source,module.__file__,'exec'),module.__dict__)
        s=rules.start(definition(),2)
        self.assertEqual(module.overview_html(s),ui.overview_html(s))
        self.assertIsNotNone(module._EMBEDDED_ASSETS)

    def test_emblem_hash_and_local_png_are_required(self):
        s=rules.start(definition(),2)
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
        valid={'uri':'data:image/png;base64,'+base64.b64encode(png).decode(),'sha256':hashlib.sha256(png).hexdigest(),
               'source':'game/e_000001_r_l.uasset','kind':'club'}
        v=ui.presentation(s,emblems={'1':valid,'2':dict(valid,sha256='wrong'),
             '3':dict(valid,uri='https://example.com/logo.png')})
        self.assertEqual(v['teams'][0]['emblem']['source'],valid['source'])
        self.assertIsNone(v['teams'][1]['emblem']);self.assertIsNone(v['teams'][2]['emblem'])
        self.assertIn('data:image/png;base64,',ui.overview_html(s,emblems={'1':valid}).decode())

    def test_native_url_rejects_remote_or_wrong_competition(self):
        uid=str(uuid.uuid4());base='http://127.0.0.1:43125/player-studio/tournaments/'+uid
        self.assertEqual(native.local_schedule_url(base,uid),base+'?host=android')
        for url in ('https://example.com/player-studio/tournaments/'+uid,
                    'http://127.0.0.1.evil:4/player-studio/tournaments/'+uid,
                    base.replace(uid,str(uuid.uuid4())),base.replace('43125','0'),
                    base.replace('127.0.0.1','name@127.0.0.1')):
            with self.assertRaises(ValueError):native.local_schedule_url(url,uid)

    def test_native_dispatch_does_not_modify_progress_and_reports_real_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);s=rules.start(definition(),2);p=db(root,s)
            before=p.read_bytes();calls=[]
            opener=lambda url,uid:calls.append((url,uid)) or True
            self.assertIsNone(native.dispatch_saved_schedule('CMD_START_GAME',root,s['uuid'],'http://127.0.0.1:9',opener=opener))
            for command in (native.ENTRY_EVIDENCE['schedule_request'],native.ENTRY_EVIDENCE['challenge_schedule_request']):
                self.assertIsNone(native.dispatch_saved_schedule(command,root,s['uuid'],
                    'http://127.0.0.1:9/player-studio/tournaments',opener=opener))
            self.assertEqual(calls,[])
            result=native.schedule_button_clicked(root,s['uuid'],
                    'http://127.0.0.1:9/player-studio/tournaments',opener=opener)
            self.assertEqual(len(calls),1)
            self.assertTrue(result['queued']);self.assertFalse(result['device_validated'])
            self.assertTrue(result['requires_native_menu_integration'])
            self.assertEqual(p.read_bytes(),before)

    def test_click_intent_expires_and_cannot_be_reused_or_cross_events(self):
        now=[1.0];uid=str(uuid.uuid4());click=native.ScheduleClick(uid,clock=lambda:now[0])
        self.assertFalse(click.consume(str(uuid.uuid4())))
        self.assertTrue(click.consume(uid));self.assertFalse(click.consume(uid))
        click=native.ScheduleClick(uid,clock=lambda:now[0]);now[0]+=4
        self.assertFalse(click.consume(uid))


if __name__=='__main__':unittest.main()
