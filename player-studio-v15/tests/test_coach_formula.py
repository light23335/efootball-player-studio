from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).absolute().parents[1]))
from coach_formula import factor, displayed


class NativeCoachFormulaTests(unittest.TestCase):
    def test_native_88_proficiency_legend_calibration(self):
        self.assertAlmostEqual(factor(88),1.0353086,places=7)
        self.assertEqual(displayed(94,5,0,factor(88)),102)
        self.assertEqual(displayed(85,5,0,factor(88)),93)
        self.assertEqual(displayed(38,0,0,factor(88)),40)
        self.assertEqual(displayed(105,20,2,factor(88)),120)

    def test_native_linear_branch_and_missing_coach_sentinel(self):
        self.assertEqual(factor(90),1.036180019378662)
        self.assertEqual(factor(99),1.0405449867248535)
        self.assertEqual(factor(127),1.0)
        self.assertEqual(factor(None),1.0)
        self.assertEqual(displayed(65,0,1,factor(90)),68)


if __name__=='__main__':unittest.main()
