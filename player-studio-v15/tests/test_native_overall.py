import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import native_overall


class NativeOverallTests(unittest.TestCase):
    def test_independent_original_arm64_oracle_all_positions_and_boosters(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/native-overall-probes.json').read_text(encoding='utf8'))
        self.assertEqual({row['position'] for row in fixture['cases']}, set(range(13)))
        self.assertEqual(len(fixture['cases']), 26)
        for case in fixture['cases']:
            parameters = copy.deepcopy(case['parameters'])
            bonus = {int(k): v for k, v in case['boosts'].items()}
            self.assertEqual(native_overall.rating(parameters, case['position'], bonus), case['native_result'])
            self.assertEqual(parameters, case['parameters'])

    def test_invalid_inputs_and_native_integer_result(self):
        params = [40] * 147
        params[0] = 0; params[33] = 1; params[47] = 185
        for position in (-1, 13, True):
            with self.assertRaises(ValueError):
                native_overall.rating(params, position)
        with self.assertRaises(ValueError):
            native_overall.rating(params[:-1])
        self.assertIs(type(native_overall.rating(params)), int)

    def test_positive_stat_bonus_is_monotone(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/native-overall-probes.json').read_text(encoding='utf8'))
        for case in fixture['cases']:
            base = native_overall.rating(case['parameters'], case['position'])
            extra = native_overall.rating(case['parameters'], case['position'], {i: 5 for i in range(14, 41) if i != 33})
            self.assertGreaterEqual(extra, base)


if __name__ == '__main__':
    unittest.main()
