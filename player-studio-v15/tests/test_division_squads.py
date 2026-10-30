import copy
import io
import json
import random
import sqlite3
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import division_squads as ds
import native_overall
from coach_formula import factor
from native_package import bytecode, hook_archive


def card(cid, role, rating=112):
    params = [0] * 147
    params[0] = role
    params[1:14] = [2] * 13
    params[14:41] = [90] * 27
    params[33] = 1
    params[47] = 185
    return {'gameplayer_id': {'id': cid, 'serial': 0}, 'parameters': params,
            '_overall': rating, 'default_rarity': 4, 'level_info': {'level': 1, 'level_limit': 1}}


def template():
    plan = {'formation_offensive': [], 'formation_defensive': [], 'team_style': 2,
            'coach_link_data': [{'is_link_on': 'YES', 'key_member_Id': 12, 'link_member_Id': 22}]}
    return {'rqid': 1, 'msgid': 'prepare', 'team_data': {}, 'user_info': {}, 'player_list': [],
            'squad_data': {'coach': [], 'player_list': [], 'squad_gameplan': {
                'formation': [plan, copy.deepcopy(plan)], 'match_plan_settings': {}}}}


def native_formation(roles):
    return list(roles), [{'role': ds.ROLE_NAMES.index(role), 'position_x': 5 + i * 4,
                          'position_y': 8 + i * 7} for i, role in enumerate(roles)]


class DivisionSquadTests(unittest.TestCase):
    def test_content_delta_cards_are_stock_pool_when_diy_switch_is_off(self):
        cid=52904601946818;p=card(cid,12);p['_content_package']='V18-V19'
        self.put_card(p);self.doc['division_squads']['include_diy']=False
        self.doc['content_catalogue']={'players':[{'card_id':str(cid),'definition':p}]}
        self.assertIn(cid,{r['gameplayer_id']['id']for r in self.g.cards(self.db)})
        self.doc['division_squads']['excluded_ids'].append(str(cid))
        self.assertNotIn(cid,{r['gameplayer_id']['id']for r in self.g.cards(self.db)})
    def test_optional_diy_exclusion_covers_current_and_previously_installed_cards(self):
        known=card(999001,0);legacy=card(999002,0);legacy['_personal_player_uuid']='previous-export'
        self.put_card(known);self.put_card(legacy)
        self.doc['players']=[{'identity':{'card_id':999001,'previous_card_ids':[999001]}}]
        self.assertIn(999001,{p['gameplayer_id']['id'] for p in self.g.cards(self.db)})
        self.doc['division_squads']['include_diy']=False
        result={p['gameplayer_id']['id'] for p in self.g.cards(self.db)}
        self.assertNotIn(999001,result);self.assertNotIn(999002,result);self.assertIn(1000,result)
        self.assertTrue(ds.configuration({},[],{'include_diy':False})['include_diy'] is False)
    def test_exact_stock_custom_cards_are_ai_only_excluded_but_diy_and_namesakes_remain(self):
        before=self.db.execute('select count(*)from managed_cards').fetchone()[0]
        for cid in ds.STOCK_AI_EXCLUDED_CARD_IDS:self.put_card(card(cid,12))
        copied=90159680001234;self.put_card(card(copied,12))
        keeper=copied+1;self.put_card(card(keeper,0))
        self.doc['players']=[{'identity':{'card_id':copied,'bound_original_player_id':89136418985304},'owned':{'name':'Paul Pogba'}},
                             {'identity':{'card_id':keeper,'bound_original_player_id':8554053},'owned':{'name':'My goalkeeper'}}]
        ids={int(c['gameplayer_id']['id'])for c in self.g.cards(self.db)}
        self.assertFalse(ids&ds.STOCK_AI_EXCLUDED_CARD_IDS);self.assertIn(copied,ids);self.assertIn(keeper,ids)
        self.assertEqual(self.db.execute('select count(*)from managed_cards').fetchone()[0],before+len(ds.STOCK_AI_EXCLUDED_CARD_IDS)+2)

    def test_v18_v19_exact_cards_excluded_from_ai_without_removing_player_cards(self):
        excluded={89136418985321,89136418985316,89136418985320,89136418985323,
                  89136418985324,89136418985322,89136418985325}
        self.assertTrue(excluded <= ds.STOCK_AI_EXCLUDED_CARD_IDS)
        for cid in excluded:
            p=card(cid,12);p['_content_package']='V18-V19';self.put_card(p)
        # Same footballer on another stock card, and a DIY copied from an
        # excluded card, remain eligible under the existing pool rules.
        namesake=89136418985321+(1<<28);copied=90159680001999
        self.put_card(card(namesake,12));self.put_card(card(copied,12))
        self.doc['players']=[{'identity':{'card_id':copied,'bound_original_player_id':89136418985321}}]
        before=list(self.db.execute('select card_id,fingerprint,payload from managed_cards order by card_id'))
        for include_diy in (True,False):
            self.doc['division_squads']['include_diy']=include_diy
            ids={p['gameplayer_id']['id']for p in self.g.cards(self.db)}
            self.assertFalse(ids & excluded);self.assertIn(namesake,ids)
            self.assertEqual(copied in ids,include_diy)
        self.assertEqual(before,list(self.db.execute('select card_id,fingerprint,payload from managed_cards order by card_id')))

    def test_bound_custom_variants_share_original_person_but_unbound_remain_independent(self):
        original=(397808<<28)|4522
        doc={'players':[{'identity':{'card_id':90159685046698,'bound_original_player_id':original,'independent_person_id':96151466}},
                        {'identity':{'card_id':90159416611242,'previous_card_ids':[90159694943574],'bound_original_player_id':str(original),'independent_person_id':93089768}},
                        {'identity':{'card_id':90159410000001,'person_id':4522,'independent_person_id':93080001}},
                        {'identity':{'card_id':90159410000002,'person_id':4522,'independent_person_id':93080002}}]}
        before=copy.deepcopy(doc);identities=ds.personal_identities(doc)
        self.assertEqual([identities[n]for n in (90159685046698,90159416611242,90159694943574)],[4522]*3)
        cards=[dict(card(n,12),_studio_squad_person_id=identities[n])for n in (90159685046698,90159416611242,90159410000001,90159410000002)]
        self.assertEqual(ds.person(cards[0]),ds.person(card(original,12)))
        self.assertEqual(len({ds.person(c)for c in cards}),3)
        self.assertEqual(doc,before,'Identity deduplication must not edit or remove projects')

    def setUp(self):
        mixing = patch.object(ds, 'MIX_STEPS', 128)
        mixing.start(); self.addCleanup(mixing.stop)
        self.db = sqlite3.connect(':memory:')
        self.db.executescript('create table meta(key text primary key,value text);'
                              'create table managed_cards(card_id text primary key,fingerprint text,payload text);'
                              'create table coaches(coach_id integer,serial integer,json text);'
                              'create table excluded_catalog_ids(card_id text primary key,reason text);')
        for role in range(13):
            for n in range(7):
                c = card(1000 + role * 10 + n, role)
                self.put_card(c)
        coaches = []
        for i, style in enumerate(ds.STYLES):
            p = {'coach_id': {'id': i + 1, 'serial': 0}, **dict.fromkeys(ds.STYLES, 60), style: 90}
            coaches.append({'payload': p, 'effects': {}})
        self.doc = {'revision': 'fixture', 'division_squads': {'enabled': True, 'coaches': coaches,
                    'rating_margin': 1, 'excluded_ids': []}, 'players': [], 'preview_boosters': {}}
        self.developed = types.SimpleNamespace(developed=lambda p, boosts=None: copy.deepcopy(p),
                                              apply_display_overall=lambda p: p.update(overall=p['_overall']))
        self.g = ds.Generator(lambda: self.doc, self.developed, lambda p, mode: copy.deepcopy(p),
                              lambda: {}, native_formation,
                              lambda: {'121': {}, '122': {}, '123': {}},
                              lambda p, team_id: dict(p, team_data={'base_team_id': team_id}))

    def tearDown(self):
        self.db.close()

    def put_card(self, c):
        raw = json.dumps(c)
        self.db.execute('insert or replace into managed_cards values(?,?,?)', (str(c['gameplayer_id']['id']), raw, raw))
        self.db.commit()

    def test_native_strength_examples(self):
        self.assertEqual(ds.strength([100] * 23), 3100)
        self.assertEqual(ds.strength([110] * 23), 3410)
        self.assertEqual(ds.strength([0] * 23), 0)
        self.assertEqual(ds.strength([100] * 11 + [0] * 12), 1980)
        self.assertEqual(ds.strength(list(range(80, 103))), ds.strength(list(range(102, 79, -1))))
        for invalid in ([100] * 22, [100] * 22 + [256], [100] * 22 + [True]):
            with self.assertRaises(ValueError): ds.strength(invalid)

    def test_exported_opponent_switch_and_native_cache_restore(self):
        self.assertTrue(ds.configuration({},[])['enabled'])
        self.assertFalse(ds.configuration({},[],{'enabled':False})['enabled'])
        with self.assertRaises(ValueError):ds.configuration({},[],{'enabled':0})
        state=json.dumps({'division':3,'points':1900,'round':2})
        self.db.execute('insert into meta values(?,?)',('ai_division_state',state))
        custom=json.dumps({'game_id':123,'opponent':{ds.MARKER:{'revision':'old'},'player_list':[1,2,3]}})
        self.db.execute('insert into meta values(?,?)',('ai_division_active_match',custom));self.db.commit()
        cards=list(self.db.execute('select * from managed_cards'))
        self.assertTrue(ds.release_cached_opponent(self.db))
        self.assertIsNone(self.db.execute("select value from meta where key='ai_division_active_match'").fetchone())
        self.assertEqual(self.db.execute('select value from meta where key=?',('personal_ai_disabled_snapshot_v1:123',)).fetchone()[0],custom)
        self.assertEqual(self.db.execute("select value from meta where key='ai_division_state'").fetchone()[0],state)
        self.assertEqual(list(self.db.execute('select * from managed_cards')),cards)
        self.assertFalse(ds.release_cached_opponent(self.db))
        original=json.dumps({'game_id':124,'opponent':{'player_list':[4,5,6]}})
        self.db.execute('insert into meta values(?,?)',('ai_division_active_match',original));self.db.commit()
        self.assertFalse(ds.release_cached_opponent(self.db))
        self.assertEqual(self.db.execute("select value from meta where key='ai_division_active_match'").fetchone()[0],original)

    def test_disabled_installer_calls_original_prepare_and_does_not_warm_library(self):
        calls=[]
        def native(conn,response,request):calls.append((response,request));return dict(response,native=True)
        ai=types.SimpleNamespace(prepare=native)
        modules={'ai_division':ai,'developed_preview':self.developed,
                 'club_store':types.SimpleNamespace(wire_player=lambda *a:None),
                 'opponent_squad':types.SimpleNamespace(external_caps=lambda:{},formation_for_roles=lambda *a:None),
                 'ziru_data':types.SimpleNamespace(teams=lambda:{},normalize_opponent_team=lambda *a:None),
                 'owned_coaches':types.SimpleNamespace(sync_opponent=lambda *a:None)}
        self.doc['division_squads']['enabled']=False
        with patch.dict(sys.modules,modules),patch.object(ds.threading,'Thread') as thread:
            ds.install(lambda:self.doc,None)
            self.assertEqual(ai.prepare(self.db,{'msgid':'prepare'},{'rqid':7}),{'msgid':'prepare','native':True})
            thread.assert_not_called()
        self.assertEqual(calls,[({'msgid':'prepare'},{'rqid':7})])

    def test_coach_factor_matches_existing_native_formula(self):
        for proficiency in range(80, 100):
            self.assertEqual(ds.proficiency_factor(proficiency), factor(proficiency))

    def test_all_ten_divisions_have_required_threshold_and_roster(self):
        for division in range(1, 11):
            response = self.g.build(self.db, template(), division, random.Random(division))
            report = response[ds.MARKER]
            self.assertGreaterEqual(report['conservative_strength'], 3300 if division <= 3 else 3200)
            roster = response['player_list']
            self.assertEqual(len(roster), 23)
            self.assertEqual(len({ds.person(c) for c in roster}), 23)
            for i, p in enumerate(roster[:11]):
                self.assertEqual(p['parameters'][ds.APTITUDE_INDEX[report['attack_roles'][i]]], 2)
                self.assertEqual(p['parameters'][ds.APTITUDE_INDEX[report['defence_roles'][i]]], 2)
            self.assertTrue(all(len(p['parameters']) == 149 for p in roster))
            self.assertEqual([p['gameplayer_id'] for p in roster], [p['gameplayer_id'] for p in response['squad_data']['player_list']])
            self.assertEqual(response['coach_data']['coach_id'], response['squad_data']['coach'][0]['coach_id'])
            for plan in response['squad_data']['squad_gameplan']['formation']:
                # Original V17 UI maps3 toLong Ball and4 toOut Wide;
                # never infer the protocol from the editor's presentation order.
                self.assertEqual(plan['team_style'], {'possession':0,'short_counter':1,
                    'long_counter':2,'side_attack':4,'long_ball':3,'overload':5}[report['style']])
                self.assertEqual(len(plan['formation_offensive']), 11)
                self.assertTrue(all(isinstance(row, dict) and 'position_x' in row for row in plan['formation_offensive']))
                self.assertEqual([row['role'] for row in plan['formation_offensive']], report['attack_roles'])
                self.assertEqual([row['role'] for row in plan['formation_defensive']], report['defence_roles'])
                self.assertNotEqual(plan['formation_offensive'], plan['formation_defensive'])
                self.assertEqual(plan['coach_link_data'][0]['is_link_on'], 'NO')

    def test_legacy_display_cache_is_refreshed_without_changing_catalogue(self):
        before=list(self.db.execute('select card_id,payload from managed_cards order by card_id'))
        self.g.wire=lambda p,mode:dict(copy.deepcopy(p),disp_overall=13,disp_max_overall=13)
        out=self.g.build(self.db,template(),3,random.Random(18))
        self.assertTrue(all(p['disp_overall']>40 and p['disp_max_overall']==p['disp_overall'] for p in out['player_list']))
        self.assertEqual(before,list(self.db.execute('select card_id,payload from managed_cards order by card_id')))

    def test_reused_current_snapshot_repairs_40_display_cache_without_redrawing(self):
        out=self.g.build(self.db,template(),3,random.Random(18))
        before=copy.deepcopy(out)
        out['player_list'][3]['disp_overall']=40
        out['player_list'][3]['disp_max_overall']=40
        self.assertTrue(self.g.repair_snapshot(self.db,out))
        self.assertGreater(out['player_list'][3]['disp_overall'],40)
        self.assertEqual(out['player_list'][3]['parameters'],before['player_list'][3]['parameters'])
        self.assertEqual(out[ds.MARKER]['card_ids'],before[ds.MARKER]['card_ids'])
        self.assertEqual(out['squad_data'],before['squad_data'])
        self.assertEqual(out['coach_data'],before['coach_data'])
        self.assertFalse(self.g.repair_snapshot(self.db,out))

    def test_reused_snapshot_recovers_collapsed_parameters_from_same_card_only(self):
        out=self.g.build(self.db,template(),3,random.Random(18))
        before=copy.deepcopy(out)
        out['player_list'][4]['parameters'][14:41]=[0]*27
        out['player_list'][4]['disp_overall']=100  # A good cache cannot hide bad real attributes.
        self.assertTrue(self.g.repair_snapshot(self.db,out))
        self.assertEqual(out['player_list'][4]['parameters'],before['player_list'][4]['parameters'])
        self.assertEqual(out[ds.MARKER]['card_ids'],before[ds.MARKER]['card_ids'])
        self.assertGreater(out['player_list'][4]['disp_overall'],40)
        self.assertTrue(any(r['kind']=='parameters' for r in out[ds.MARKER]['payload_repairs']))

    def test_primary_aptitudes_use_distinct_native_order(self):
        self.assertEqual(ds.APTITUDE_INDEX, (13, 10, 11, 12, 6, 7, 8, 9, 5, 3, 4, 2, 1))
        catalog = json.loads((Path(__file__).resolve().parents[1] / 'resources/catalog.json').read_text(encoding='utf8'))
        self.assertEqual(list(ds.APTITUDE_INDEX), [catalog['APTITUDES'].index(p) + 1 for p in catalog['POSITIONS']])
        roster = self.g.build(self.db, template(), 1, random.Random(1))['player_list']
        for player in roster:
            params = player['parameters']
            raw = self.db.execute('select payload from managed_cards where card_id=?', (str(player['gameplayer_id']['id']),)).fetchone()[0]
            self.assertEqual(params[1:14], json.loads(raw)['parameters'][1:14])

    def test_unfinished_training_is_not_sent_to_game(self):
        self.developed.developed = lambda p, boosts: dict(p, level_info={'level':1,'level_limit':40})
        with self.assertRaisesRegex(ValueError, '满级'):
            self.g.build(self.db, template(), 1, random.Random(1))

    def test_coach_threshold_is_85_for_stock_and_custom_coaches(self):
        self.doc['division_squads']['coaches']=[{'payload':{'coach_id':{'id':1,'serial':0},**dict.fromkeys(ds.STYLES,84)},'effects':{}}]
        with self.assertRaises(ValueError):self.g.build(self.db,template(),1,random.Random(2))
        self.doc['coaches']=[{'id':600001,'payload':{'coach_id':{'id':600001,'serial':0},**dict.fromkeys(ds.STYLES,85)},'effects':{}}]
        out=self.g.build(self.db,template(),1,random.Random(2))
        self.assertEqual(out[ds.MARKER]['proficiency'],85)
        self.assertEqual(out['coach_data']['coach_id']['id'],600001)

    def test_real_roster_gets_three_strategy_preflight_without_catalogue_edits(self):
        out=self.g.build(self.db,template(),1,random.Random(12));spec=out[ds.MARKER]['tactical_spec']
        self.assertEqual(len(spec['players']),23)
        self.assertEqual(spec['style'],out[ds.MARKER]['style'])
        self.assertEqual(spec['base_profile']['id'],out[ds.MARKER]['formation_id'])
        for kind in ('chase','protect'):
            prepared=spec['prepared'][kind]
            self.assertTrue(prepared['available'])
            self.assertLessEqual(prepared['evaluated_shapes'],48)
            for option in prepared['options']:
                self.assertLessEqual(option['required_changes'],2)
                self.assertGreaterEqual(option['native_lower_bound_strength'],3300)

    def test_v1_snapshot_repairs_positions_and_aptitudes_without_rerolling(self):
        out = self.g.build(self.db, template(), 1, random.Random(1))
        out[ds.MARKER]['revision'] = 'v17-division-library-v1'
        before = copy.deepcopy(out)
        for plan in out['squad_data']['squad_gameplan']['formation']:
            plan['formation_offensive'] = native_formation([ds.ROLE_NAMES[r] for r in ds.STARTERS])
            plan['formation_defensive'] = copy.deepcopy(plan['formation_offensive'])
        for player in out['player_list']:
            params = player['parameters']; params[1 + params[0]] = 2
        self.assertTrue(self.g.repair_snapshot(self.db, out))
        self.assertEqual(out['coach_data'], before['coach_data'])
        self.assertEqual(out['team_data'], before['team_data'])
        self.assertEqual(out['player_list'], before['player_list'])
        for plan in out['squad_data']['squad_gameplan']['formation']:
            self.assertEqual(plan['formation_offensive'], self.g.positions(before['player_list']))
        self.assertFalse(self.g.repair_snapshot(self.db, out))

    def test_random_styles_teams_and_cards_change(self):
        reports = [self.g.build(self.db, template(), 1, random.Random(i))[ds.MARKER] for i in range(40)]
        self.assertEqual({r['style'] for r in reports}, set(ds.STYLES))
        self.assertGreater(len({r['base_team_id'] for r in reports}), 1)
        self.assertGreater(len({tuple(r['card_ids']) for r in reports}), 30)
        self.assertGreaterEqual(len({r['formation_id'] for r in reports}), 10)
        self.assertTrue(all(r['individual_rating_method'] == 'v17-native-integer-lower-bound' for r in reports))

    def test_exclusions_allow_china_and_reject_broken_payload(self):
        self.db.execute("insert into excluded_catalog_ids values('1000','China edition')")
        self.db.execute("insert into excluded_catalog_ids values('1001','bad animation')")
        self.doc['division_squads']['excluded_ids'] = ['1002']
        broken = card(1003, 0); broken['parameters'] = []
        self.put_card(broken)
        ids = {p['gameplayer_id']['id'] for p in self.g.cards(self.db)}
        self.assertIn(1000, ids)
        self.assertTrue({1001, 1002, 1003}.isdisjoint(ids))

    def test_only_five_stars_and_above_including_diy(self):
        for offset, rarity in enumerate((0, 1, 2, 3, 4, 5, None, True, 999)):
            c = card(9900 + offset, 12)
            c['default_rarity'] = rarity
            c['_personal_player_uuid'] = 'diy-star-filter'
            self.put_card(c)
        selected = {c['gameplayer_id']['id'] for c in self.g.cards(self.db)}
        self.assertTrue({9904, 9905}.issubset(selected))
        self.assertTrue({9900, 9901, 9902, 9903, 9906, 9907, 9908}.isdisjoint(selected))

    def test_saved_overall_does_not_control_native_rating(self):
        c = self.g.cards(self.db)[0]
        coach = {'payload': {'possession': 90}, 'effects': {}}
        score = self.g.rating(c, coach, 'possession', 12)
        changed = copy.deepcopy(c)
        changed['_overall'] = 1
        changed['_studio_fingerprint'] = 'fake-saved-overall'
        self.assertEqual(score, self.g.rating(changed, coach, 'possession', 12))

    def test_stock_flat_attribute_placeholder_identities_are_never_selected(self):
        for cid in (8554053, 8554076, 25331269):
            self.put_card(card(cid, 0))
            self.put_card(card((1 << 40) + cid, 0))
        personal = card(91000000, 0)
        personal['_personal_player_uuid'] = 'legitimate-high-stat-diy'
        personal['parameters'][14:33] = [99] * 19
        self.put_card(personal)
        pool = self.g.cards(self.db)
        self.assertTrue(all(ds.person(c) not in ds.STOCK_TEST_PERSON_IDS for c in pool))
        self.assertIn(91000000, {c['gameplayer_id']['id'] for c in pool})

    def test_mixed_single_dmf_and_cmf_do_not_overlap(self):
        def original_collision(roles):
            chosen, coords = native_formation(roles)
            for row in coords:
                if row['role'] == 4: row.update(position_x=22, position_y=64)
                if row['role'] == 5: row.update(position_x=24, position_y=65)
            return chosen, coords
        self.g.formation = original_collision
        profile = next(p for p in self.g.profiles() if p['family'] == '442')
        for phase in ('attack', 'defence'):
            rows = self.g.positions([], profile[phase], phase, 'overload')
            dmf, cmf = [r for r in rows if r['role'] in (4, 5)]
            self.assertGreaterEqual(abs(dmf['position_y']-cmf['position_y']), 30)

    def test_preferred_band_applies_to_whole_squad_without_changing_cards(self):
        rng = random.Random(32)
        for n in range(180):
            c = card(93000000+n, n % 13)
            for i in range(14, 41):
                if i != 33: c['parameters'][i] = rng.randrange(80, 100)
            self.put_card(c)
        cards = self.g.cards(self.db)
        coach = {'payload': {'possession': 90}, 'effects': {}}
        profile = next(p for p in self.g.profiles() if p['family'] == '442')
        result = self.g.select(cards, coach, 'possession', 3300, random.Random(83), profile, maximum=3399)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(ds.strength(result[1]), 3300)
        self.assertLessEqual(ds.strength(result[1]), 3399)

    def test_all_formation_templates_have_eleven_players_and_valid_phases(self):
        profiles = self.g.profiles()
        self.assertEqual(len({p['family'] for p in profiles}), 18)
        self.assertEqual(len({p['id'] for p in profiles}), len(profiles))
        for profile in profiles:
            self.assertEqual(len(profile['attack']), 11)
            self.assertEqual(len(profile['defence']), 11)
            self.assertEqual(profile['attack'].count(0), 1)
            self.assertEqual(profile['defence'].count(0), 1)
            self.assertTrue(all(0 <= role <= 12 for role in profile['attack'] + profile['defence']))

    def test_no_fixed_strongest_diy_core_on_equal_native_attributes(self):
        for n in range(7):
            c = card(90000000 + n, 12)
            c['_overall'] = 127
            c['_personal_player_uuid'] = 'equal-attributes-diy'
            self.put_card(c)
        reports = [self.g.build(self.db, template(), 1, random.Random(100 + n))[ds.MARKER] for n in range(32)]
        always = set(reports[0]['card_ids']).intersection(*(set(r['card_ids']) for r in reports[1:]))
        self.assertEqual(always, set())
        self.assertTrue(all(not r['sampling']['fixed_top_card_repair'] and not r['sampling']['top_n_pool_limit'] for r in reports))

    def test_variant_identity_cannot_play_twice(self):
        self.put_card(card((1 << 40) + 1000, 0))
        for seed in range(10):
            roster = self.g.build(self.db, template(), 1, random.Random(seed))['player_list']
            self.assertEqual(len({ds.person(p) for p in roster}), 23)

    def test_installed_diy_and_custom_coach_are_selected(self):
        for role in range(13):
            for i in range(4):
                c = card(90000000 + role * 10 + i, role)
                c['_personal_player_uuid'] = 'installed-diy'
                self.put_card(c)
        custom = {'id': 600001, 'payload': {'coach_id': {'id': 600001, 'serial': 0}, **dict.fromkeys(ds.STYLES, 88)},
                  'effects': {'14': 2}}
        self.doc['coaches'] = [custom]
        self.doc['division_squads']['coaches'] = []
        response = self.g.build(self.db, template(), 1, random.Random(1))
        self.assertEqual(response['coach_data']['coach_id']['id'], 600001)
        self.assertEqual(self.g.coaches(self.db)[0]['effects'], {'14': 2})
        self.assertTrue(any(p['gameplayer_id']['id'] >= 90000000 for p in response['player_list']))

    def test_no_owned_or_catalogue_mutation(self):
        rows = self.db.execute('select * from managed_cards').fetchall()
        own = template(); original = copy.deepcopy(own)
        self.g.build(self.db, own, 1, random.Random(1))
        self.assertEqual(own, original)
        self.assertEqual(rows, self.db.execute('select * from managed_cards').fetchall())

    def test_strength_failure_does_not_return_weak_team(self):
        for cid, raw in self.db.execute('select card_id,payload from managed_cards').fetchall():
            c = json.loads(raw)
            for i in range(14, 41):
                if i != 33: c['parameters'][i] = 40
            self.put_card(c)
        with self.assertRaisesRegex(ValueError, '3300'):
            self.g.build(self.db, template(), 1, random.Random(1))

    def test_rating_does_not_bake_manager_or_boosters_into_match_stats(self):
        self.doc['preview_boosters']['1'] = {'effects': {'14': 4}, 'conditional': False}
        c = self.g.cards(self.db)[0]; c['parameters'][144] = 1
        source = copy.deepcopy(c)
        coach = {'payload': {'possession': 90}, 'effects': {'14': 2}}
        value = self.g.rating(c, coach, 'possession', 12)
        plain = self.g.rating(dict(c, _studio_fingerprint='without-bonus', parameters=list(c['parameters'][:144]) + [0, 0, 0]),
                              {'payload': {'possession': 90}, 'effects': {}}, 'possession', 12)
        self.assertGreater(value, plain)
        self.assertEqual(c, source)
        self.assertEqual(self.g.trained(c)['parameters'][14], 90)

    def test_runtime_packaging_replaces_stale_helper(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as z:
            z.writestr('embedded_gateway.pyc', bytecode('pass', 'embedded_gateway.py'))
            z.writestr('division_squads.pyc', b'stale')
            z.writestr('native_overall.pyc', b'stale')
            z.writestr('preserved.bin', b'original')
        source = (Path(ds.__file__)).read_text(encoding='utf8')
        rating_source = Path(native_overall.__file__).read_text(encoding='utf8')
        with zipfile.ZipFile(io.BytesIO(hook_archive(raw.getvalue(), 'pass', 'pass', source, rating_source))) as z:
            self.assertEqual(z.read('preserved.bin'), b'original')
            self.assertEqual(z.read('division_squads.pyc'), bytecode(source, 'division_squads.py'))
            self.assertEqual(z.namelist().count('division_squads.pyc'), 1)
            self.assertEqual(z.read('native_overall.pyc'), bytecode(rating_source, 'native_overall.py'))
            self.assertEqual(z.namelist().count('native_overall.pyc'), 1)

    def test_committed_prepare_recovers_failed_index_without_redraw_or_new_native_epoch(self):
        from ai_division_sessions import Entries, DRAW_KEY, ENTRY_KEY, read
        from ai_match_runtime import Bridge
        import ai_match_runtime as coaching
        layout=json.loads((Path(ds.__file__).parent/'resources/native-ai-match-adapter.json').read_text('utf8'))['channel_schema']
        channel=Bridge(bytearray(32768),0,layout,lambda:None)
        native_calls=[]
        def original(conn,response,request):
            active=read(conn,'ai_division_active_match')
            if active is None:
                active={'game_id':123,'opponent':copy.deepcopy(response)}
                conn.execute('insert into meta values(?,?)',('ai_division_active_match',json.dumps(active)))
                conn.commit()
            native_calls.append(active['game_id'])
            return dict(copy.deepcopy(active['opponent']),game_id=active['game_id'],rqid=request['rqid'])
        modules={'ai_division':types.SimpleNamespace(prepare=original,state=lambda conn:{'division':3}),
                 'developed_preview':self.developed,'club_store':types.SimpleNamespace(wire_player=self.g.wire),
                 'opponent_squad':types.SimpleNamespace(external_caps=self.g.caps,formation_for_roles=self.g.formation),
                 'ziru_data':types.SimpleNamespace(teams=self.g.teams,normalize_opponent_team=self.g.normalize),
                 'owned_coaches':types.SimpleNamespace(sync_opponent=lambda *args:None)}
        real_commit=Entries.commit;fail=[True]
        def commit(entries,conn,entry,report):
            if fail[0]:
                fail[0]=False
                raise RuntimeError('injected after native prepare committed')
            return real_commit(entries,conn,entry,report)
        def activate(spec,root):
            channel.configure(spec,root)
            return {'channels':1,'execution_enabled':False,'status':'observing'}
        progress=json.dumps({'division':3,'points':1900,'round':9})
        self.db.execute('insert into meta values(?,?)',('ai_division_state',progress));self.db.commit()
        owned=list(self.db.execute('select * from managed_cards'))
        with tempfile.TemporaryDirectory() as folder,patch.dict(sys.modules,modules),patch.object(ds.threading.Thread,'start'), \
             patch.object(Entries,'commit',commit),patch.object(coaching,'activate',activate), \
             patch.object(ds.Generator,'build',autospec=True,side_effect=ds.Generator.build) as build:
            ds.install(lambda:self.doc,folder)
            with self.assertRaisesRegex(RuntimeError,'injected after native'):
                modules['ai_division'].prepare(self.db,template(),{'rqid':1})
            active=read(self.db,'ai_division_active_match');marker=active['opponent'][ds.MARKER]
            epoch=channel.epoch
            self.assertIsNone(read(self.db,ENTRY_KEY))
            result=modules['ai_division'].prepare(self.db,template(),{'rqid':2})
            entry=read(self.db,ENTRY_KEY)
            self.assertEqual(entry['entry_id'],marker['entry_id'])
            self.assertEqual(entry['game_id'],123)
            self.assertEqual(read(self.db,DRAW_KEY)['draw_sequence'],1)
            self.assertEqual(channel.epoch,epoch)
            self.assertEqual(build.call_count,1)
            self.assertEqual(native_calls,[123,123])
            self.assertEqual(result['player_list'],active['opponent']['player_list'])
            self.assertEqual(self.db.execute('select count(*) from personal_ai_entries').fetchone()[0],1)
            self.assertEqual(self.db.execute("select count(*) from personal_ai_events where event='entry_index_recovered'").fetchone()[0],1)
            self.assertEqual(self.db.execute("select value from meta where key='ai_division_state'").fetchone()[0],progress)
            self.assertEqual(list(self.db.execute('select * from managed_cards')),owned)

    def test_prepare_keeps_one_match_snapshot_and_preserves_foreign_coach(self):
        sequence = [122]
        def original(conn, response, req):
            active = conn.execute("select value from meta where key='ai_division_active_match'").fetchone()
            if not active: sequence[0] += 1
            snapshot = json.loads(active[0]) if active else {'game_id':sequence[0]}
            response = snapshot['opponent'] if active else copy.deepcopy(response)
            modules['owned_coaches'].sync_opponent(conn, response)
            snapshot['opponent'] = response
            conn.execute("insert or replace into meta values('ai_division_active_match',?)", (json.dumps(snapshot),))
            conn.commit()
            return dict(response, game_id=snapshot['game_id'], rqid=req['rqid'])
        modules = {name: types.ModuleType(name) for name in ('ai_division', 'developed_preview', 'club_store', 'opponent_squad', 'ziru_data', 'owned_coaches')}
        modules['ai_division'].prepare = original
        modules['ai_division'].state = lambda conn: {'division': 1}
        modules['developed_preview'].__dict__.update(vars(self.developed))
        modules['club_store'].wire_player = self.g.wire
        modules['opponent_squad'].external_caps = self.g.caps
        modules['opponent_squad'].formation_for_roles = self.g.formation
        modules['ziru_data'].teams = self.g.teams
        modules['ziru_data'].normalize_opponent_team = self.g.normalize
        modules['owned_coaches'].sync_opponent = lambda conn, response: self.fail('original resolver would replace an unowned coach')
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules, modules), patch.object(ds.threading.Thread, 'start'):
            ds.install(lambda: self.doc, folder)
            prepare = modules['ai_division'].prepare
            a = prepare(self.db, template(), {'rqid': 1})
            first_formation = json.loads(self.db.execute('select value from meta where key=?', (ds.LAST_FORMATION,)).fetchone()[0])['id']
            b = prepare(self.db, template(), {'rqid': 2})
            self.assertEqual(a['player_list'], b['player_list'])
            self.assertEqual(a['coach_data'], b['coach_data'])
            self.assertEqual(b['rqid'], 2)
            self.assertNotIn(ds.MARKER, a)
            ds.install(lambda: self.doc, folder)
            self.assertIs(prepare, modules['ai_division'].prepare)
            self.db.execute("delete from meta where key='ai_division_active_match'"); self.db.commit()
            c = prepare(self.db, template(), {'rqid': 3})
            self.assertNotEqual(a['player_list'], c['player_list'])
            next_formation = json.loads(self.db.execute('select value from meta where key=?', (ds.LAST_FORMATION,)).fetchone()[0])['id']
            self.assertNotEqual(first_formation, next_formation)
            active = json.loads(self.db.execute("select value from meta where key='ai_division_active_match'").fetchone()[0])
            active.update(game_id=456, started=True, round=7, division=1)
            from ai_division_sessions import ENTRY_KEY,read,write
            entry=read(self.db,ENTRY_KEY);entry['game_id']=456
            write(self.db,ENTRY_KEY,entry)
            opponent = active['opponent']; opponent[ds.MARKER]['revision'] = 'v17-division-library-v1'
            for plan in opponent['squad_data']['squad_gameplan']['formation']:
                plan['formation_offensive'] = [[], []]
            raw = json.dumps(active)
            self.db.execute("update meta set value=? where key='ai_division_active_match'", (raw,)); self.db.commit()
            repaired = prepare(self.db, template(), {'rqid': 4})
            saved = json.loads(self.db.execute("select value from meta where key='ai_division_active_match'").fetchone()[0])
            self.assertEqual({k: saved[k] for k in ('game_id', 'started', 'round', 'division')},
                             {'game_id': 456, 'started': True, 'round': 7, 'division': 1})
            self.assertEqual(repaired['player_list'], c['player_list'])
            self.assertEqual(len(repaired['squad_data']['squad_gameplan']['formation'][0]['formation_offensive']), 11)
            backup = self.db.execute("select value from meta where key='personal_ai_formation_backup_v1:456'").fetchone()[0]
            self.assertEqual(backup, raw)
            self.db.execute('begin')
            self.db.execute("insert into meta values('foreign_transaction','pending')")
            with self.assertRaisesRegex(ValueError, 'transaction boundary'):
                prepare(self.db, template(), {'rqid': 5})
            self.assertTrue(self.db.in_transaction)
            self.db.rollback()
            self.assertIsNone(self.db.execute("select value from meta where key='foreign_transaction'").fetchone())


if __name__ == '__main__':
    unittest.main()
