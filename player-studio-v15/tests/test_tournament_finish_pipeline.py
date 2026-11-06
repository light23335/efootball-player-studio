"""Real result score parser -> tournament settlement; game serializer is a fixture."""
import copy
import os
from pathlib import Path
import sqlite3
import sys
import types
import unittest
import uuid
from unittest.mock import patch

import tournament_rules as rules
import tournament_runtime as runtime


class TournamentFinishPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(root / '.work/v20-content-delta-20261030'))
        from static_reader import module_reader
        reader = module_reader(Path(os.environ.get('STUDIO_TEST_RESULT_APK',str(root/'球员工坊-V17/data/exports/73efootball-V17-个人球员-20261104-225236-b6a1.apk'))))
        def walk(code):
            yield code
            for value in code.co_consts:
                if isinstance(value, types.CodeType):
                    yield from walk(value)
        code = next(c for c in walk(reader('cup16_mode')) if c.co_name == '_scores')
        cls.score_parser = staticmethod(types.FunctionType(code, {'Cup16Error': ValueError}))

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.addCleanup(self.conn.close)
        self.conn.execute('create table meta(key primary key,value)')
        runtime.put(self.conn, 'unrelated-owned-progress', {'XP': 123456, 'level': 27})
        self.calls = []
        def serialize(logic, request, config, home, away, outcome):
            self.calls.append((home, away, outcome))
            return {'game_end_result': {'match_result': {'player_data': {}}}}
        modules = {
            'cup16_mode': types.SimpleNamespace(_scores=self.score_parser,
                game_id=lambda request: request['match_result']['game_id']),
            'cup16_service': types.SimpleNamespace(Cup16Service=types.SimpleNamespace(_result_reply=serialize)),
            'vscom_result': types.SimpleNamespace(outcome=lambda request, side, home, away:
                (home-away) * (1 if side == 'HOME' else -1)),
            'ai_match_runtime': types.SimpleNamespace(deactivate_for_match=lambda *args: False),
        }
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules, modules).start()
        self.logic = types.SimpleNamespace(conn=self.conn)
        self.service = runtime.Service(lambda: {}, '.', None)

    def start(self, stage):
        definition = dict(uuid=str(uuid.uuid4()), name='Settlement Cup', enabled=True,
            team_ids=[1, 2], player_team_id=1, stages=[stage])
        state = rules.start(definition, 7)
        state['receipts'] = {}
        return state

    def finish(self, state, fixture, score, *, extra=(0, 0), pk=None, side='HOME', gid=71):
        state['active'] = dict(game_id=gid, fixture_id=fixture['id'], started=True,
            player_side=side, match_env=runtime.match_environment(state, fixture))
        request = {'match_result': {'game_id': gid, 'pk_flag': 'YES' if pk is not None else 'NO'},
            'score': [dict(score_1st=score[i]-extra[i], score_2nd=0,
                score_ex1st=extra[i], score_ex2nd=0, score_pk=(pk or [0, 0])[i]) for i in range(2)]}
        response = self.service.finish(self.logic, state['definition'], state, request)
        after = copy.deepcopy(state)
        calls = len(self.calls)
        self.assertEqual(self.service.finish(self.logic, state['definition'], state, request), response)
        self.assertEqual(state, after)
        self.assertEqual(len(self.calls), calls, 'duplicate receipt must not serialize rewards twice')
        self.assertEqual(response['game_end_result']['match_result']['player_data']['side'], side)
        self.assertEqual(runtime.get(self.conn, 'unrelated-owned-progress'), {'XP': 123456, 'level': 27})
        self.assertEqual(fixture['score'], list(score))
        self.assertEqual(fixture['extra_time_score'], list(extra))
        return response

    def test_single_leg_regular_extra_time_and_penalty_results_both_player_sides(self):
        for side in ('HOME', 'AWAY'):
            for score, extra, pk in (((2, 1), (0, 0), None), ((2, 1), (1, 0), None),
                    ((0, 0), (0, 0), (4, 5)), ((2, 2), (1, 1), (5, 4))):
                with self.subTest(side=side, score=score, extra=extra, pk=pk):
                    s = self.start({'type': 'knockout'})
                    f = rules.due(s)[0]
                    self.finish(s, f, score, extra=extra, pk=pk, side=side)
                    winner = f['home'] if (pk or score)[0] > (pk or score)[1] else f['away']
                    self.assertEqual(s['champion'], winner)
                    self.assertEqual(f['penalties'], list(pk) if pk else None)

    def test_first_leg_draw_then_aggregate_away_goals_extra_time_and_penalties(self):
        # First-leg scores and all second-leg scores are in that match's home order.
        cases = [
            (False, False, (0, 0), (0, 0), (0, 0), (5, 4)),
            (False, False, (2, 1), (0, 0), (0, 0), None),
            (True, False, (2, 1), (1, 0), (0, 0), None),
            (False, False, (2, 1), (1, 0), (0, 0), (4, 5)),
            (True, True, (1, 1), (2, 2), (1, 1), None),
            (True, False, (1, 1), (2, 2), (1, 1), (5, 4)),
            (False, False, (1, 1), (2, 1), (1, 0), None),
        ]
        for away, away_extra, first_score, score, extra, pk in cases:
            with self.subTest(away=away, away_extra=away_extra, score=score, extra=extra):
                s = self.start(dict(type='knockout', legs=2, away_goals=away, away_goals_extra_time=away_extra))
                first = rules.due(s)[0]
                self.finish(s, first, first_score, gid=71)
                self.assertFalse(s['completed'])
                second = rules.due(s)[0]
                self.assertEqual((second['home'], second['away']), (first['away'], first['home']))
                self.finish(s, second, score, extra=extra, pk=pk, gid=72)
                self.assertTrue(s['completed'])
                self.assertIsNotNone(s['champion'])

    def test_group_and_league_draw_settles_without_penalties(self):
        for kind in ('league', 'groups'):
            s = self.start(dict(type=kind, groups=1, advance_per_group=1))
            f = rules.due(s)[0]
            self.finish(s, f, (0, 0))
            self.assertTrue(f['played'])
            self.assertIsNone(f['penalties'])

    def test_missing_or_tied_penalties_keep_fixture_and_progress_pending_then_valid_retry_succeeds(self):
        for pk in (None, (3, 3)):
            s = self.start({'type': 'knockout'})
            f = rules.due(s)[0]
            s['active'] = dict(game_id=71, fixture_id=f['id'], started=True, player_side='HOME')
            before = copy.deepcopy(s)
            request = {'match_result': {'game_id': 71, 'pk_flag': 'YES' if pk else 'NO'},
                'score': [dict(score_1st=0, score_2nd=0, score_ex1st=0, score_ex2nd=0,
                    score_pk=(pk or (0, 0))[i]) for i in range(2)]}
            calls = len(self.calls)
            with self.assertRaises(ValueError):
                self.service.finish(self.logic, s['definition'], s, request)
            self.assertEqual(s, before)
            self.assertEqual(len(self.calls), calls)
            self.finish(s, f, (0, 0), pk=(4, 5))
            self.assertTrue(s['completed'])


if __name__ == '__main__':
    unittest.main()
