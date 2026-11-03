"""팀별 연간 목표 대비 (사용자 2026-11-03)."""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import targets  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import render  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")


class TestSave(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_save_and_replace(self):
        targets.save(self.dir, "2026", "기획1팀", "1,000", "30")
        targets.save(self.dir, "2026", "기획1팀", "2000", "31.5%")
        self.assertEqual(targets.read(self.dir), {("2026", "기획1팀"): {"revenue": 2000, "rate": 31.5}})

    def test_bad_input(self):
        for args in (("26", "가", "1", "1"), ("2026", "", "1", "1"), ("2026", "가", "0", "1"), ("2026", "가", "1", "120")):
            with self.assertRaises(ValueError):
                targets.save(self.dir, *args)


class TestMonthly(unittest.TestCase):
    def test_target_table_in_ytd(self):
        html = render(compute(load(SAMPLE), "monthly", dt.date(2026, 10, 31)), "ceo")
        self.assertIn("목표 대비 (진도 기준 10월/12 = 83%)", html)
        self.assertIn("<td>기획1팀</td><td>900,000,000</td><td>742,500,000</td>", html)
        self.assertIn("82.5%", html)
        self.assertIn("목표 미달", html)   # 82.5% < 83%
        self.assertIn("목표 이상", html)   # 기획2팀 86.8%

    def test_without_targets_says_how(self):
        R = compute(load(SAMPLE), "monthly", dt.date(2026, 10, 31))
        R["targets"] = {}
        self.assertIn("'⑧ 팀 목표'", render(R, "ceo"))


if __name__ == "__main__":
    unittest.main()
