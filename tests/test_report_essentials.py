"""대표용은 꼭 알아야 할 것만 (사용자 2026-11-03). 시험 자료는 전부 가상이다."""
import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import render, month_flow, week_outflows  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
D = dt.date


class TestMonthFlowStartsOnTheFirst(unittest.TestCase):
    """월간 자금 흐름 그림은 그 달 1일부터, 달마다 (사용자 2026-11-03)."""

    def test_first_bar_is_the_report_month_from_day_one(self):
        for asof in (D(2026, 10, 31), D(2026, 10, 20)):
            R = compute(load(SAMPLE), "monthly", asof)
            mf = month_flow(R)
            bs = mf["buckets"]
            self.assertEqual(mf["first"], D(2026, 10, 1))
            self.assertEqual([b["label"].split(" ")[1].split("(")[0] for b in bs][:3], ["10월", "11월", "12월"])
            self.assertEqual((bs[0]["in_firm"] - sum(e["amount"] for e in R["s2"]["dated"] if e["io"] == "in" and e["firm"] and e["date"].month == 10),
                              bs[0]["out_firm"] - sum(e["amount"] for e in R["s2"]["dated"] if e["io"] == "out" and e["firm"] and e["date"].month == 10)),
                             (R["s1"]["in"], R["s1"]["out"]))
            # 1일 가용액 + 이번 달 실적 = 오늘 가용액, 그 뒤 예정은 s2 일정 그대로
            if R["s2"]["start"] is None:   # 잔액을 모르면 선을 그리지 않는다 (0에서 시작하지 않음)
                self.assertIsNone(mf["start"])
                self.assertIsNone(bs[-1]["bal_all"])
                continue
            self.assertEqual(mf["start"] + R["s1"]["in"] - R["s1"]["out"], R["s2"]["start"])
            total = sum(b["in_firm"] + b["in_est"] - b["out_firm"] - b["out_est"] for b in bs)
            self.assertEqual(bs[-1]["bal_all"], mf["start"] + total)
        R = compute(load(SAMPLE), "monthly", D(2026, 10, 31))
        self.assertIn("10월(실적)", month_flow(R)["buckets"][0]["label"])
        html = render(R, "ceo")
        self.assertIn("월별 자금 흐름 (10월 1일 가용액", html)
        self.assertIn("월별 (첫 달은 1일부터)", html)

    def test_weekly_chart_is_unchanged(self):
        html = render(compute(load(SAMPLE), "weekly", D(2026, 10, 31)), "ceo")
        self.assertIn("기간별 자금 흐름 (시작: 오늘 가용액", html)
        self.assertNotIn("월별 자금 흐름", html)


class TestWeeklyHasNoPastDue(unittest.TestCase):
    """주간: 미수금·예정 지난 미지급은 싣지 않는다, 월간에만 (사용자 2026-11-03)."""

    def test_friday_list_skips_past_due_but_keeps_friday_itself(self):
        R = compute(load(SAMPLE), "weekly", D(2026, 10, 31))
        R["events"] = R["events"] + [
            {"date": D(2026, 10, 20), "io": "out", "amount": 7, "desc": "지난 것", "firm": True, "cat": "x"}]
        self.assertFalse([e for e in week_outflows(R)["rows"] if e["desc"] == "지난 것"])
        R2 = compute(load(SAMPLE), "weekly", D(2026, 11, 6))   # 금요일 당일 보고: 그날 것은 이미 나간 것 (자금 표와 같은 규칙)
        W = week_outflows(R2)
        self.assertEqual(W["fri"], D(2026, 11, 13))
        self.assertTrue(all(e["date"] > D(2026, 11, 6) for e in W["rows"]))

    def test_monthly_still_has_the_past_due_box(self):
        M = render(compute(load(SAMPLE), "monthly", D(2026, 10, 31)), "ceo")
        for t in ("입금일 지난 미수금", "지급일 지난 출금", "미수금 (세금계산서 발행 후)"):
            self.assertIn(t, M)


class TestEvidenceOnlyInManagement(unittest.TestCase):
    def test_ceo_has_footer_and_no_evidence_blocks(self):
        for kind in ("weekly", "monthly"):
            R = compute(load(SAMPLE), kind, D(2026, 10, 31))
            ceo, mgmt = render(R, "ceo"), render(R, "mgmt")
            self.assertIn("‘근거’ 번호로 요청하시면 경영관리가 해당 근거자료를 제출합니다", ceo)
            self.assertNotIn("class='mgonly'", ceo)
            self.assertNotIn("<div class='xbox'>", ceo.split("<div class='toc'>")[0])
            self.assertIn("class='mgonly'", mgmt)
            self.assertIn("프로젝트별 원가 예산·집행", mgmt)


if __name__ == "__main__":
    unittest.main()
