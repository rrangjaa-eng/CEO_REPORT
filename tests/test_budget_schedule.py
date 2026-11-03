"""남은 예산을 지급 예정으로 (D-54, 2026-11-03 사용자 결정: D-06 뒤집음).

남은 예산 = 원가 예산 − 예상총집행. 0보다 크면 행사일 다음 달 마지막 금요일에 부가세 10%를 더해 지급 예정으로 둔다.
그 날이 기준일 이전·당일이면 기준일 다음 금요일. 행사일이 없으면 날짜 없는 지급 예정. 완료 프로젝트는 넣지 않는다.
연도를 넘는 날짜(12월 행사 → 1월 말)도 그대로 이어진다.
"""
import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report.calc import budget_due, compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from sample_input import SAMPLE, refresh  # noqa: E402
from test_report import probe_folder  # noqa: E402

ASOF = dt.date(2026, 11, 2)


def budget_events(R):
    return dict((e["project"], e) for e in R["events"] if e["source"] == "남은 예산")


class TestBudgetDue(unittest.TestCase):
    def test_last_friday_of_next_month(self):
        self.assertEqual(budget_due(dt.date(2026, 11, 28), ASOF), dt.date(2026, 12, 25))

    def test_crosses_year(self):
        self.assertEqual(budget_due(dt.date(2026, 12, 3), ASOF), dt.date(2027, 1, 29))
        self.assertEqual(budget_due(dt.date(2027, 1, 20), ASOF), dt.date(2027, 2, 26))

    def test_past_due_moves_to_next_friday(self):
        # 9월 행사 → 10월 30일(금)은 기준일 이전 → 기준일 다음 금요일
        self.assertEqual(budget_due(dt.date(2026, 9, 18), ASOF), dt.date(2026, 11, 6))
        self.assertEqual(budget_due(dt.date(2026, 9, 18), dt.date(2026, 11, 6)), dt.date(2026, 11, 13))

    def test_unknown_event_date(self):
        self.assertIsNone(budget_due(None, ASOF))


class TestBudgetEvents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        refresh()

    def test_remaining_budget_is_planned_payment_with_vat(self):
        R = compute(load(SAMPLE), "weekly", ASOF)
        ev = budget_events(R)
        # P26207: 예산 21,000,000 − 예상집행 14,000,000 = 7,000,000, 부가세 더해 7,700,000, 행사 11/28 → 12/25
        self.assertEqual(ev["P26207"]["amount"], 7700000)
        self.assertEqual(ev["P26207"]["date"], dt.date(2026, 12, 25))
        self.assertEqual(ev["P26207"]["io"], "out")
        self.assertFalse(ev["P26207"]["firm"])
        self.assertIn("남은 예산", ev["P26207"]["cat"])
        # P26208: 2027-01-20 행사 → 2027-02-26 (해를 넘김), 13,650,000 × 1.1
        self.assertEqual(ev["P26208"]["date"], dt.date(2027, 2, 26))
        self.assertEqual(ev["P26208"]["amount"], 15015000)

    def test_not_for_done_over_or_unknown(self):
        ev = budget_events(compute(load(SAMPLE), "weekly", ASOF))
        for pid in ("P26202", "P26205",   # 완료
                    "P26201", "P26203",   # 예산 초과(남은 예산 ≤ 0)
                    "P26204",             # 예산 미지정
                    "P26206"):            # 금액 미확인 원가 → 판단 불가 (0으로 넣지 않음)
            self.assertNotIn(pid, ev)

    def test_unknown_remaining_listed(self):
        R = compute(load(SAMPLE), "weekly", ASOF)
        self.assertEqual([P["id"] for P in R["s3"]["remain_unknown"]], ["P26206"])

    def test_missing_event_date_is_undated(self):
        def blank_date(rows):
            i = rows[0].index("행사일")
            for r in rows[1:]:
                if r[0] == "P26207":
                    r[i] = ""
        R = compute(load(probe_folder(self, "프로젝트.csv", blank_date)), "weekly", ASOF)
        ev = budget_events(R)["P26207"]
        self.assertIsNone(ev["date"])
        self.assertEqual(ev["amount"], 7700000)

    def test_monthly_buckets_include_budget(self):
        R = compute(load(SAMPLE), "weekly", ASOF)
        dec = [b for b in R["s2"]["buckets"] if b["type"] == "month" and b["from"].month == 12][0]
        R0 = compute(load(SAMPLE), "weekly", ASOF)
        self.assertGreaterEqual(dec["out_est"], 7700000)
        self.assertEqual(R0["s2"]["buckets"][0]["label"], "1주차")


if __name__ == "__main__":
    unittest.main()
