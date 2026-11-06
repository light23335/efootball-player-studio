"""Independent mathematical and fixed-seed sample checks (no user data)."""

import copy
import json
import math
import random
import sys
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tournament_simulation as sim


def ratings(value=80, **overrides):
    return dict(dict.fromkeys(sim.RATING_KEYS, value), **overrides)


def batch(home, away, count=20000, offset=0):
    counts, sums = Counter(), [0, 0]
    for i in range(count):
        result = sim.sample_period(home, away, seed=i + offset, neutral=True)
        score = tuple(result["score"])
        sums[0] += score[0]
        sums[1] += score[1]
        counts[score] += 1
    return {"count": count, "means": [value / count for value in sums],
            "home_wins": sum(n for (h, a), n in counts.items() if h > a) / count,
            "away_wins": sum(n for (h, a), n in counts.items() if a > h) / count,
            "draws": sum(n for (h, a), n in counts.items() if h == a) / count,
            "max_goals": max(max(score) for score in counts), "counts": counts}


class ScoreModelTests(unittest.TestCase):
    def test_equal_strength_baseline_home_effect_and_neutrality(self):
        r = ratings()
        equal = sim.expected_goals(r, r, neutral=True)
        self.assertEqual(equal["xg"], [1.3, 1.3])
        for value in (40, 60, 100, 120):
            self.assertEqual(sim.expected_goals(ratings(value), ratings(value),
                                              neutral=True)["xg"], [1.3, 1.3])
        home = sim.expected_goals(r, r, neutral=False)["xg"]
        self.assertGreater(home[0], 1.3)
        self.assertLess(home[1], 1.3)
        self.assertLess(home[0] / home[1], 1.15)

    def test_individual_dimensions_and_smooth_bounded_correction(self):
        r = ratings()
        for key in ("attack", "creation", "depth"):
            result = sim.expected_goals(ratings(**{key: 105}), r, neutral=True)
            self.assertGreater(result["xg"][0], 1.3, key)
        for key in ("defence", "goalkeeping"):
            result = sim.expected_goals(r, ratings(**{key: 105}), neutral=True)
            self.assertLess(result["xg"][0], 1.3, key)
        xg = [sim.expected_goals(ratings(attack=v), r, neutral=True)["xg"][0]
              for v in (80, 81, 90, 120, 160, 240, 1000)]
        self.assertEqual(xg, sorted(xg))
        self.assertLess(xg[-1], 1.3 * math.exp(sim.STRENGTH_LOG_LIMIT))
        near = sim.expected_goals(ratings(attack=80.001), r, neutral=True)["xg"][0]
        self.assertLess(abs(near - 1.3), .001)

    def test_form_is_one_small_modifier_and_resets_on_opposite_result(self):
        r = ratings()
        for count in (3, 6, 100):
            self.assertEqual(sim.form_modifier(["W"] * count), sim.FORM_LOG_EFFECT)
            self.assertEqual(sim.form_modifier(["L", "D"] * count), -sim.FORM_LOG_EFFECT)
        self.assertEqual(sim.form_modifier(["W", "W"]), 0)
        self.assertEqual(sim.form_modifier(["D", "L"]), 0)
        self.assertEqual(sim.form_modifier(["W"] * 6 + ["D"]), 0)
        self.assertEqual(sim.form_modifier(["D"] * 6 + ["W"]), 0)
        old = {"win_streak": 3, "nonwin_streak": 0}
        self.assertEqual(sim.advance_form(old, "L"), {"win_streak": 0, "nonwin_streak": 1})
        self.assertEqual(old["win_streak"], 3)
        boost = sim.expected_goals(r, r, neutral=True, form_home=["W"] * 3)
        self.assertAlmostEqual(boost["xg"][0] / 1.3, math.exp(.035))
        self.assertEqual(boost["xg"][1], 1.3)

    def test_extra_time_scale_separate_streams_and_no_automatic_extra_time(self):
        r = ratings()
        regular = sim.sample_period(r, r, seed=1, minutes=90, neutral=True)
        extra = sim.sample_period(r, r, seed=2, minutes=30, neutral=True)
        self.assertEqual(extra["xg_90"], regular["xg_90"])
        self.assertAlmostEqual(extra["xg"][0] / regular["xg"][0], 1 / 3)
        self.assertEqual(regular["minutes"], 90)
        self.assertNotIn("penalties", regular)
        streams = sim.seed_streams(1234, "fixture-1")
        self.assertEqual(len(set(streams.values())), 4)
        self.assertEqual(streams, sim.seed_streams(1234, "fixture-1"))
        self.assertNotEqual(streams, sim.seed_streams(1234, "fixture-2"))
        self.assertNotEqual(sim.derive_seed(1, "23"), sim.derive_seed(12, "3"))
        self.assertNotEqual(sim.derive_seed(1), sim.derive_seed("1"))
        before = sim.sample_period(r, r, seed=streams["regulation"])
        sim.penalty_shootout(r, r, seed=streams["penalties"])
        sim.sample_period(r, r, seed=streams["extra_time"], minutes=30)
        self.assertEqual(before, sim.sample_period(r, r, seed=streams["regulation"]))

    def test_determinism_no_input_mutation_or_global_random_state(self):
        h, a = ratings(85, name="Famous club", audit={"snapshot": [1, 2]}), ratings(75)
        original = copy.deepcopy(h)
        global_state = random.getstate()
        one = sim.simulate_match(h, a, root_seed=123, match_id="one", neutral=True)
        self.assertEqual(one, sim.simulate_match(h, a, root_seed=123, match_id="one", neutral=True))
        h["name"] = "Unknown club"
        self.assertEqual(one, sim.simulate_match(h, a, root_seed=123, match_id="one", neutral=True))
        h["name"] = "Famous club"
        self.assertEqual(h, original)
        sim.penalty_shootout(h, a, seed=123)
        self.assertEqual(random.getstate(), global_state)
        self.assertEqual(one["model_version"], sim.MODEL_VERSION)
        self.assertIn("sampler", one["audit"])
        self.assertIn("modifiers", one)
        json.dumps(one, allow_nan=False)

    def test_original_tau_joint_mass_marginals_and_swap_symmetry(self):
        lam, mu, rho = 2.1, .9, -.08
        self.assertAlmostEqual(sim.dixon_coles_tau(0, 0, lam, mu, rho), 1 - lam * mu * rho)
        self.assertAlmostEqual(sim.dixon_coles_tau(0, 1, lam, mu, rho), 1 + lam * rho)
        self.assertAlmostEqual(sim.dixon_coles_tau(1, 0, lam, mu, rho), 1 + mu * rho)
        self.assertAlmostEqual(sim.dixon_coles_tau(1, 1, lam, mu, rho), 1 - rho)
        self.assertEqual(sim.dixon_coles_tau(7, 0, lam, mu, rho), 1)
        def poisson(k, mean):
            return math.exp(-mean) * mean ** k / math.factorial(k)
        mass, means = 0.0, [0.0, 0.0]
        for h in range(25):
            row = 0.0
            for a in range(25):
                probability = poisson(h, lam) * poisson(a, mu) * sim.dixon_coles_tau(h, a, lam, mu, rho)
                swapped = poisson(a, mu) * poisson(h, lam) * sim.dixon_coles_tau(a, h, mu, lam, rho)
                self.assertAlmostEqual(probability, swapped, places=15)
                self.assertGreaterEqual(probability, 0)
                mass += probability
                means[0] += h * probability
                means[1] += a * probability
                row += probability
            self.assertAlmostEqual(row, poisson(h, lam), places=12)
        self.assertAlmostEqual(mass, 1, places=12)
        self.assertAlmostEqual(means[0], lam, places=12)
        self.assertAlmostEqual(means[1], mu, places=12)

    def test_invalid_inputs_and_archived_versions_fail_explicitly(self):
        r = ratings()
        for value in (None, True, float("nan"), float("inf"), "80"):
            with self.assertRaises(ValueError):
                sim.sample_period(ratings(attack=value), r, seed=1)
        for kwargs in ({"minutes": -1}, {"minutes": 121}, {"seed": True},
                       {"neutral": "yes"}, {"model_version": "unknown-v9"},
                       {"form_home": {"win_streak": 3, "nonwin_streak": 3}}):
            with self.assertRaises(ValueError):
                sim.sample_period(r, r, **dict({"seed": 1}, **kwargs))
        with self.assertRaises(ValueError):
            sim.penalty_shootout(r, r, seed=1, model_version="future")
        self.assertEqual(sim.sample_period(r, r, seed=1, minutes=0)["score"], [0, 0])


class ScoreDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = ratings()
        cls.samples = {
            "balanced": batch(base, base),
            "strong_attack": batch(ratings(attack=105), base),
            "strong_creation": batch(ratings(creation=105), base),
            "strong_defence": batch(base, ratings(defence=105)),
            "strong_goalkeeper": batch(base, ratings(goalkeeping=105)),
            "strong_team": batch(ratings(110), ratings(70)),
        }

    def test_sample_mean_increases_with_attack_and_creation(self):
        samples = self.samples
        baseline = samples["balanced"]["means"][0]
        self.assertGreater(samples["strong_attack"]["means"][0], baseline + .6)
        self.assertGreater(samples["strong_creation"]["means"][0], baseline + .15)

    def test_sample_conceding_decreases_with_defence_and_goalkeeping(self):
        samples = self.samples
        baseline = samples["balanced"]["means"][0]
        self.assertLess(samples["strong_defence"]["means"][0], baseline - .35)
        self.assertLess(samples["strong_goalkeeper"]["means"][0], baseline - .15)

    def test_balanced_symmetry_mean_dc_cells_and_uncapped_tail(self):
        sample = self.samples["balanced"]
        self.assertLess(abs(sample["means"][0] - 1.3), .03)
        self.assertLess(abs(sample["means"][1] - 1.3), .03)
        self.assertLess(abs(sample["home_wins"] - sample["away_wins"]), .025)
        self.assertGreater(sample["max_goals"], 6)
        for h, a in ((0, 0), (0, 1), (1, 0), (1, 1)):
            probability = (math.exp(-2.6) * 1.3 ** (h + a)
                           * sim.dixon_coles_tau(h, a, 1.3, 1.3))
            observed = sample["counts"][(h, a)] / sample["count"]
            self.assertLess(abs(observed - probability), .008)

    def test_better_team_is_favoured_but_upsets_remain_possible(self):
        sample = self.samples["strong_team"]
        self.assertGreater(sample["home_wins"], .7)
        self.assertGreater(sample["away_wins"], .01)
        self.assertLess(sample["home_wins"], .95)


class PenaltyTests(unittest.TestCase):
    def actual_ratings(self, *, native_first=1):
        # Real strength aggregation, isolated synthetic native entry. Reserve
        # finishers are deliberately much better and must never take a kick.
        import tournament_sim_strength as strength
        from test_tournament_sim_strength import document, team_snapshot
        team = team_snapshot()
        for index, player in enumerate(team["player_list"]):
            for field in sim.PENALTY_TAKER_FIELDS:
                player["parameters"][field] = 45 + index * 4 if index < 11 else 120
        team["squad_data"]["squad_gameplan"]["match_plan_settings"]["set_piece_taker"] = [1] * 5 + [native_first]
        result = strength.ratings(team, document=document())
        # Metadata is read from the saved native duty by strength, not inferred
        # from player identity or an invented full native shootout order.
        self.assertEqual(result["audit"]["penalty_plan"]["native_first_taker_roster_index"], native_first)
        return result

    def test_actual_starters_native_preference_and_goalkeeper_have_effective_ability_audit(self):
        home, away = self.actual_ratings(), self.actual_ratings(native_first=2)
        before = copy.deepcopy(home)
        result = sim.penalty_shootout(home, away, seed=100)
        squads = result["audit"]["squads"]
        self.assertEqual(squads["home"]["source"], "actual_starting_xi")
        self.assertEqual(squads["home"]["takers"][0]["roster_index"], 1)
        self.assertEqual(squads["away"]["takers"][0]["roster_index"], 2)
        for side, source in (("home", home), ("away", away)):
            allowed = {p["roster_index"] for p in source["audit"]["players"] if p["is_starter"]}
            self.assertEqual({p["roster_index"] for p in squads[side]["takers"]}, allowed)
            self.assertEqual(len(squads[side]["takers"]), 11)
            for kick in (k for k in result["kicks"] if k["side"] == side):
                self.assertIn(kick["taker"]["roster_index"], allowed)
                self.assertEqual(set(kick["taker"]["effective"]), set(sim.PENALTY_TAKER_FIELDS))
                self.assertEqual(set(kick["keeper"]["effective"]), set(sim.PENALTY_KEEPER_FIELDS))
                self.assertEqual(kick["keeper"]["order"], 0)
                self.assertEqual(kick["taker_source"], "actual_starting_xi")
        self.assertEqual(home, before)
        # Persisted JSON key conversion cannot change effective skills/order.
        self.assertEqual(result, sim.penalty_shootout(json.loads(json.dumps(home)),
                                                     json.loads(json.dumps(away)), seed=100))

    def test_actual_eleven_cycle_after_all_have_taken_and_bench_duty_is_ignored(self):
        home, away = self.actual_ratings(native_first=22), self.actual_ratings(native_first=22)
        # All score for eleven rounds; in the twelfth home scores, away misses.
        sequence = iter([.01] * 23 + [.99])
        fake = SimpleNamespace(randrange=lambda _: 0, random=lambda: next(sequence))
        with patch.object(sim.random, "Random", return_value=fake):
            result = sim.penalty_shootout(home, away, seed=5)
        self.assertEqual(result["rounds"], 12)
        self.assertEqual(result["score"], [12, 11])
        for side in ("home", "away"):
            self.assertFalse(result["audit"]["squads"][side]["native_first_taker_used"])
            self.assertEqual(result["audit"]["squads"][side]["takers"][0]["order"], 10)
            ids = [kick["taker"]["gameplayer_id"]["id"] for kick in result["kicks"] if kick["side"] == side]
            self.assertEqual(len(set(ids[:11])), 11)
            self.assertEqual(ids[0], ids[11])

    def test_actual_player_and_keeper_changes_have_bounded_per_kick_influence(self):
        home, away = self.actual_ratings(), self.actual_ratings()
        before = sim.penalty_shootout(home, away, seed=10)["audit"]["probability_schedules"][0][0]
        stronger = copy.deepcopy(home)
        for field in sim.PENALTY_TAKER_FIELDS:
            stronger["audit"]["players"][1]["effective"][field] += 20
        finishing = sim.penalty_shootout(stronger, away, seed=10)["audit"]["probability_schedules"][0][0]
        self.assertGreater(finishing, before)
        keeper = copy.deepcopy(away)
        for field in sim.PENALTY_KEEPER_FIELDS:
            keeper["audit"]["players"][0]["effective"][field] += 20
        kept = sim.penalty_shootout(home, keeper, seed=10)["audit"]["probability_schedules"][0][0]
        self.assertLess(kept, before)
        self.assertLess(finishing - kept, .18)

    def test_incomplete_actual_audit_cannot_silently_fall_back_to_numeric_proxy(self):
        home, away = self.actual_ratings(), self.actual_ratings()
        home["audit"]["players"][1]["is_starter"] = False
        with self.assertRaisesRegex(ValueError, "exact eleven"):
            sim.penalty_shootout(home, away, seed=5)
        home = self.actual_ratings()
        home["audit"]["contributions"]["goalkeeping"] = []
        with self.assertRaisesRegex(ValueError, "on-field GK"):
            sim.penalty_shootout(home, away, seed=5)
        home = self.actual_ratings()
        del home["audit"]["players"]
        with self.assertRaisesRegex(ValueError, "missing the starting players"):
            sim.penalty_shootout(home, away, seed=5)

    def test_each_kick_alternates_updates_score_and_obeys_early_stop(self):
        endings, finals, first_sides = Counter(), set(), set()
        for seed in range(1000):
            result = sim.penalty_shootout(ratings(), ratings(), seed=seed)
            self.assertEqual(result, sim.penalty_shootout(ratings(), ratings(), seed=seed))
            endings[result["audit"]["ended_by"]] += 1
            finals.add(tuple(result["score"]))
            first_sides.add(result["audit"]["first_side"])
            score, taken, previous = [0, 0], [0, 0], None
            for index, kick in enumerate(result["kicks"]):
                side = 0 if kick["side"] == "home" else 1
                self.assertNotEqual(side, previous)
                previous = side
                taken[side] += 1
                score[side] += int(kick["scored"])
                self.assertEqual(kick["score"], score)
                self.assertEqual(kick["round"], taken[side])
                last = index == len(result["kicks"]) - 1
                if kick["round"] <= 5:
                    remaining = [5 - taken[0], 5 - taken[1]]
                    decided = score[0] > score[1] + remaining[1] or score[1] > score[0] + remaining[0]
                    if decided:
                        self.assertTrue(last)
                elif taken[0] == taken[1] and score[0] != score[1]:
                    self.assertTrue(last)
            self.assertEqual(score, result["score"])
            self.assertEqual(taken, result["audit"]["kicks_taken"])
            self.assertNotEqual(score[0], score[1])
            self.assertEqual(result["winner"], "home" if score[0] > score[1] else "away")
        self.assertGreater(endings["early_elimination"], 0)
        self.assertGreater(endings["sudden_death"], 0)
        self.assertGreater(endings["five_kicks"], 0)
        self.assertGreater(len(finals), 10)
        self.assertEqual(first_sides, {"home", "away"})

    def test_ability_effect_is_limited_and_neutral_penalties_are_symmetric(self):
        wins = 0
        for seed in range(5000):
            result = sim.penalty_shootout(ratings(120), ratings(40), seed=seed)
            wins += result["winner"] == "home"
            self.assertTrue(all(.66 <= p <= .84 for p in result["audit"]["probabilities"]))
        self.assertGreater(wins / 5000, .6)
        equal_wins = sum(sim.penalty_shootout(ratings(), ratings(), seed=seed)["winner"] == "home"
                         for seed in range(5000))
        self.assertLess(abs(equal_wins / 5000 - .5), .03)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if hasattr(ScoreDistributionTests, "samples"):
        report = {name: {key: value for key, value in sample.items() if key != "counts"}
                  for name, sample in ScoreDistributionTests.samples.items()}
        print("SAMPLE_EVIDENCE=" + json.dumps(report, sort_keys=True))
    sys.exit(not result.wasSuccessful())
