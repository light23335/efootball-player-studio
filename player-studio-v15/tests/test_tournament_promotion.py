import copy
import json
from pathlib import Path
import sqlite3
import sys
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tournament_rules as rules
import tournament_promotion as promotion


def definition(n=4, stages=None):
    return {'uuid': str(uuid.uuid4()), 'enabled': True, 'name': '测试赛事',
            'player_team_id': 1, 'team_ids': list(range(1, n + 1)),
            'stages': stages or [{'type': 'knockout', 'legs': 1, 'advance': 1}]}


def record(state, fixture, score, **kwargs):
    before = promotion.capture(state)
    rules.record(state, fixture['id'], *score, **kwargs)
    return promotion.settle(state, before, 10000 + fixture['id'])


def own_score(fixture, win=True, goals=2):
    return [goals, 0] if (fixture['home'] == 1) == win else [0, goals]


def play(state, own_wins=True):
    events = []
    while not state['completed']:
        fixture = rules.due(state)[0]
        score = own_score(fixture, own_wins) if 1 in (fixture['home'], fixture['away']) else [2, 0]
        events += record(state, fixture, score)
    return events


class TournamentPromotionTests(unittest.TestCase):
    def test_each_knockout_win_and_champion_only_once(self):
        state = rules.start(definition(8), 4)
        events = play(state)
        self.assertEqual([event['outcome'] for event in events], ['advanced', 'advanced', 'champion'])
        self.assertEqual(len({event['id'] for event in events}), 3)
        self.assertEqual([event['animation'] for event in events], ['PROMOTED'] * 3)

    def test_elimination_is_once_even_when_remaining_cpu_rounds_finish(self):
        state = rules.start(definition(8), 3)
        events = play(state, False)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['outcome'], 'eliminated')
        self.assertEqual(events[0]['animation'], 'RELEGATED')

    def test_group_and_league_single_loss_never_eliminates(self):
        for kind in ('groups', 'league'):
            with self.subTest(kind=kind):
                state = rules.start(definition(4, [dict(type=kind, groups=1, advance_per_group=2),
                                                   dict(type='knockout', advance=1)]), 1)
                own = next(f for f in rules.due(state) if 1 in (f['home'], f['away']))
                self.assertEqual(record(state, own, own_score(own, False)), [])
                self.assertIsNone(promotion.pending(state))

    def test_tables_qualify_or_eliminate_at_phase_end(self):
        for kind in ('groups', 'league'):
            for wins in (True, False):
                with self.subTest(kind=kind, wins=wins):
                    state = rules.start(definition(4, [dict(type=kind, groups=1, advance_per_group=2),
                                                       dict(type='knockout', advance=1)]), 1)
                    events = []
                    while state['stage_index'] == 0:
                        f = rules.due(state)[0]
                        events += record(state, f, own_score(f, wins) if 1 in (f['home'], f['away']) else [2, 0])
                    self.assertEqual(len(events), 1)
                    self.assertEqual(events[0]['outcome'], 'advanced' if wins else 'eliminated')
                    self.assertEqual(events[0]['reason'], ('group_' if kind == 'groups' else 'league_') + ('qualification' if wins else 'elimination'))

    def test_final_league_awards_champion_once_without_new_division(self):
        state = rules.start(definition(4, [dict(type='league', advance_per_group=1)]), 1)
        events = play(state)
        self.assertEqual([(e['outcome'], e['reason']) for e in events], [('champion', 'champion')])
        self.assertNotIn('division', promotion.view(state, events[0]))

    def test_two_legs_wait_and_second_leg_loss_can_still_advance(self):
        state = rules.start(definition(2, [dict(type='knockout', advance=1, legs=2)]), 0)
        first = rules.due(state)[0]
        self.assertEqual(record(state, first, own_score(first, True, 4)), [])
        second = rules.due(state)[0]
        events = record(state, second, own_score(second, False, 1))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['outcome'], 'champion')
        self.assertEqual(events[0]['fixture_ids'], [first['id'], second['id']])

    def test_second_leg_win_can_be_elimination_on_aggregate(self):
        state = rules.start(definition(2, [dict(type='knockout', advance=1, legs=2)]), 0)
        first = rules.due(state)[0]
        self.assertEqual(record(state, first, own_score(first, False, 4)), [])
        second = rules.due(state)[0]
        events = record(state, second, own_score(second, True, 1))
        self.assertEqual(events[0]['outcome'], 'eliminated')

    def test_away_goals_and_pk_use_authoritative_tie_winner(self):
        for away_goals in (False, True):
            state = rules.start(definition(2, [dict(type='knockout', advance=1, legs=2,
                                                   away_goals=away_goals)]), 0)
            first = rules.due(state)[0]
            self.assertEqual(record(state, first, [2, 1]), [])
            second = rules.due(state)[0]
            if not away_goals:
                snapshot = copy.deepcopy(state)
                with self.assertRaises(ValueError):
                    record(state, second, [1, 0])
                self.assertEqual(state, snapshot)
            events = record(state, second, [1, 0], penalties=None if away_goals else [4, 5])
            winner = rules.tie_winner([first, second])
            self.assertEqual(events[0]['outcome'], 'champion' if winner == 1 else 'eliminated')

    def test_extra_time_away_goal_policy(self):
        for include_extra in (False, True):
            state = rules.start(definition(2, [dict(type='knockout', advance=1, legs=2,
                                                   away_goals=True, away_goals_extra_time=include_extra)]), 0)
            first = rules.due(state)[0]
            record(state, first, [1, 0])
            last = rules.due(state)[0]
            needs_pk = rules.needs_decision(state, last, [2, 1], [1, 1])
            events = record(state, last, [2, 1], extra=[1, 1], penalties=[4, 5] if needs_pk else None)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]['outcome'], 'champion' if state['champion'] == 1 else 'eliminated')

    def test_playoff_qualification_win_and_bypass(self):
        d = definition(6, [dict(type='groups', groups=2, advance_per_group=1, playoff_per_group=2),
                           dict(type='playoff', advance=2), dict(type='knockout', advance=1)])
        state = rules.start(d, 0)
        events = play(state)
        self.assertEqual(events[0]['reason'], 'group_qualification')
        self.assertNotIn('playoff_win', [e['reason'] for e in events])  # Direct qualifier bypasses.
        # Find a seed/first-phase score pattern placing our club in the playoff.
        found = None
        for seed in range(12):
            state = rules.start(d, seed)
            own_count = 0; events = []
            while state['stage_index'] == 0:
                f = rules.due(state)[0]
                own = 1 in (f['home'], f['away'])
                score = own_score(f, own_count == 0) if own else [2, 0]
                own_count += int(own)
                events += record(state, f, score)
            if events and events[0]['reason'] == 'playoff_qualification':
                found = state
                break
        self.assertIsNotNone(found)
        later = play(found)
        self.assertIn('playoff_win', [e['reason'] for e in later])
        self.assertEqual(later[-1]['outcome'], 'champion')

    def test_retries_names_difficulty_and_save_reload_preserve_identity(self):
        state = rules.start(definition(2), 0)
        f = rules.due(state)[0];before = promotion.capture(state)
        rules.record(state, f['id'], *own_score(f))
        event = promotion.settle(state, before, 'g1')[0]
        self.assertEqual(promotion.settle(state, before, 'g1'), [])
        state = rules.State(json.loads(json.dumps(state)))
        state['definition']['difficulty'] = 'super_star'
        state['definition']['name'] = '新名称'
        self.assertEqual(promotion.pending(state)['id'], event['id'])
        self.assertEqual(promotion.settle(state, before, 'g1'), [])

    def test_existing_saved_history_is_not_replayed_on_first_observation(self):
        state = rules.start(definition(8), 0)
        while not state['completed']:
            f = rules.due(state)[0]
            rules.record(state, f['id'], *own_score(f))
        before = promotion.capture(state)
        self.assertEqual(promotion.settle(state, before), [])
        self.assertIsNone(promotion.pending(state))

    def test_session_dedup_recovery_confirmation_and_stale_ack(self):
        state = rules.start(definition(2), 0);event = play(state)[0]
        first = promotion.begin(state, 'process-A/menu-1')
        self.assertIsNone(promotion.begin(state, 'process-A/menu-1'))
        self.assertFalse(promotion.confirm(state, event['id'], 'foreign-token'))
        recovered = rules.State(json.loads(json.dumps(state)))
        second = promotion.begin(recovered, 'process-B/menu-1')
        self.assertEqual(first['event']['id'], second['event']['id'])
        self.assertFalse(promotion.confirm(recovered, event['id'], first['delivery']['token']))
        self.assertTrue(promotion.confirm(recovered, event['id'], second['delivery']['token']))
        self.assertTrue(promotion.confirm(recovered, event['id'], second['delivery']['token']))
        self.assertIsNone(promotion.pending(recovered))
        self.assertIsNone(promotion.begin(recovered, 'process-C/menu-1'))

    def test_release_only_on_verified_failure_and_no_guessed_native_fallback(self):
        state = rules.start(definition(2), 0);play(state)
        before = copy.deepcopy(state)
        with self.assertRaises(promotion.NativePresenterUnavailable):
            promotion.dispatch(state, 'session')
        self.assertEqual(state, before)
        offer = promotion.begin(state, 'session')
        self.assertFalse(promotion.release(state, offer['event']['id'], 'bad-token'))
        self.assertTrue(promotion.release(state, offer['event']['id'], offer['delivery']['token']))
        self.assertIsNotNone(promotion.begin(state, 'session'))

    def test_old_run_and_other_tournament_cannot_consume_current(self):
        d = definition(2);a = rules.start(d, 0);old = promotion.capture(a)
        play(a);offer = promotion.begin(a, 'session')
        b = rules.start(d, 0)
        pristine = copy.deepcopy(b)
        with self.assertRaises(ValueError):promotion.settle(b, old)
        self.assertFalse(promotion.confirm(b, offer['event']['id'], offer['delivery']['token']))
        self.assertEqual(b, pristine)
        other = rules.start(definition(2), 0)
        with self.assertRaises(ValueError):promotion.view(other, offer['event'])

    def test_byes_do_not_make_an_extra_postmatch_animation(self):
        for n in (3, 5, 7, 17):
            state = rules.start(definition(n), 0)
            events = play(state)
            played = [f for f in state['fixtures'] if not f.get('bye') and 1 in (f['home'], f['away'])]
            self.assertEqual(len(events), len(played))

    def test_journal_and_result_receipt_commit_or_rollback_together(self):
        conn = sqlite3.connect(':memory:')
        conn.execute('create table meta(key text primary key,value text)')
        protected = {'ai_division_state': '{"division":3,"points":1450}',
                     'ai_division_active_match': '{"game_id":"other"}',
                     'vsuser_rating': '1930', 'cup16_progress': '{"round":2}'}
        conn.executemany('insert into meta values(?,?)', protected.items());conn.commit()
        state = rules.start(definition(2), 0)
        with self.assertRaises(RuntimeError):
            with conn:
                play(state)
                conn.execute('insert into meta values(?,?)', ('tournament', json.dumps(state)))
                raise RuntimeError('simulated receipt/save failure')
        self.assertIsNone(conn.execute("select value from meta where key='tournament'").fetchone())
        self.assertEqual(dict(conn.execute('select key,value from meta')), protected)
        fresh = rules.start(definition(2), 0)
        with conn:
            event = play(fresh)[0]
            fresh['receipts']['g1'] = {'result': 'NOERR', 'normal_reward': []}
            conn.execute('insert into meta values(?,?)', ('tournament', json.dumps(fresh)))
        saved = json.loads(conn.execute("select value from meta where key='tournament'").fetchone()[0])
        self.assertEqual(promotion.pending(saved)['id'], event['id'])
        self.assertIn('g1', saved['receipts'])
        self.assertEqual({key: value for key, value in conn.execute('select key,value from meta') if key != 'tournament'}, protected)


if __name__ == '__main__':
    unittest.main()
