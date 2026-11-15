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
# 인트라넷에서 온 줄 = 변환이 지급요청으로 만든 요청미지급 (근거 '지급요청 …'). 손으로 넣은 요청·집행계획은 그대로 일정에 있다.
is_intranet = lambda e: e.get("cat") == "프로젝트 지급요청" and str(e.get("basis") or "").startswith("지급요청")


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
        self.assertEqual([e for e in R["events"] if e.get("cat") == "프로젝트 지급요청"], [])
        self.assertTrue([e for e in R["events"] if e.get("cat") == "프로젝트 집행계획"])   # 손으로 넣은 계획은 남음

    def test_skipped_lines_are_counted_for_comparison(self):
        on, off = self.run_with(True), self.run_with(False)
        # 일정에서 빠지는 줄 = 요청미지급 전부 (지급은 자금계획서가 잡음)
        n_req = sum(1 for e in on["events"] if e.get("cat") == "프로젝트 지급요청")
        budget = sum(e["amount"] or 0 for e in on["events"] if e["source"] == "남은 예산")
        self.assertGreater(n_req, 0)
        self.assertEqual(off["intranet_only"]["requests"][0], n_req)
        # 남은 예산은 따로 정한다 (BUDGET_IN_FUNDS, 사용자 카드 2026-11-04 '계속 뺌'): 일정에 그대로 있고,
        # 쓴 돈에서 인트라넷 요청이 빠지므로 켰을 때보다 크거나 같다
        self.assertGreaterEqual(sum(e["amount"] or 0 for e in off["events"] if e["source"] == "남은 예산"), budget)

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
        self.assertGreater(off["intranet_only"]["budget"][1], 0)

    def test_spent_money_excludes_intranet_requests(self):
        """남은 예산의 '쓴 돈'은 위하고 원가·손으로 넣은 줄만 (인트라넷 지급요청 제외) → 남은 예산은 그만큼 크다."""
        on, off = self.run_with(True), self.run_with(False)
        P_on = dict((P["id"], P) for P in on["s3"]["projects"])
        P_off = dict((P["id"], P) for P in off["s3"]["projects"])
        self.assertTrue(any(P_off[k]["requested"] < P_on[k]["requested"] for k in P_on))
        for k in P_on:
            gap = P_on[k]["requested"] - P_off[k]["requested"]
            self.assertEqual(P_on[k]["expected"] - P_off[k]["expected"], gap)


if __name__ == "__main__":
    unittest.main()
