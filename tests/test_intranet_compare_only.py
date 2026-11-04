"""인트라넷은 비교만 (사용자 결정 2026-11-04 카드 '비교만').

가용자금 일정은 위하고 분개장·자금계획서만 쓴다. 인트라넷에서 온 지급요청(요청미지급)·집행계획(집행계획미요청)과
프로젝트 남은 예산은 일정에 더하지 않고, R["intranet_only"] 에 건수·합계로만 남긴다.
"""
import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report import calc  # noqa: E402
from ceo_report.data import load  # noqa: E402
from sample_input import SAMPLE, refresh  # noqa: E402

ASOF = dt.date(2026, 11, 2)
INTRANET_SOURCES = ()
INTRANET_CATS = ("프로젝트 지급요청", "프로젝트 집행계획")


class TestCompareOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        refresh()
        cls.d = load(SAMPLE)

    def run_with(self, flag):
        old = calc.INTRANET_IN_FUNDS
        calc.INTRANET_IN_FUNDS = flag
        try:
            return calc.compute(load(SAMPLE), "weekly", ASOF)
        finally:
            calc.INTRANET_IN_FUNDS = old

    def test_default_is_compare_only(self):
        self.assertFalse(calc.INTRANET_IN_FUNDS)

    def test_no_intranet_lines_in_the_schedule(self):
        R = self.run_with(False)
        bad = [e for e in R["events"] if e["source"] in INTRANET_SOURCES or e.get("cat") in INTRANET_CATS]
        self.assertEqual(bad, [])

    def test_skipped_lines_are_counted_for_comparison(self):
        on, off = self.run_with(True), self.run_with(False)
        n_req = sum(1 for e in on["events"] if e.get("cat") in INTRANET_CATS)
        budget = sum(e["amount"] or 0 for e in on["events"] if e["source"] == "남은 예산")
        self.assertGreater(n_req, 0)
        self.assertEqual(off["intranet_only"]["requests"][0], n_req)
        # 남은 예산은 따로 정한다 (BUDGET_IN_FUNDS): 켜져 있으면 일정에 그대로 있다
        self.assertEqual(sum(e["amount"] or 0 for e in off["events"] if e["source"] == "남은 예산"), budget)

    def test_budget_can_be_compare_only_too(self):
        old = calc.BUDGET_IN_FUNDS
        calc.BUDGET_IN_FUNDS = False
        try:
            on, off = self.run_with(True), self.run_with(False)
        finally:
            calc.BUDGET_IN_FUNDS = old
        budget = sum(e["amount"] or 0 for e in on["events"] if e["source"] == "남은 예산")
        self.assertFalse([e for e in off["events"] if e["source"] == "남은 예산"])
        self.assertGreater(off["intranet_only"]["budget"][0], 0)
        self.assertEqual(off["intranet_only"]["budget"][1], budget)


if __name__ == "__main__":
    unittest.main()
