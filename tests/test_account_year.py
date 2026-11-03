"""월간 보고 계정과목별 연간표 (사용자 2026-11-03: 해당 월 금액이 채워지고 월간 보고 때마다 누적)."""
import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report.calc import account_year, compute  # noqa: E402
from ceo_report.convert_pl import build_accounts  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import render  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")


def row(ym, group, code, name, amount):
    return {"ym": ym, "group": group, "code": code, "name": name, "amount": amount}


class TestAccountYear(unittest.TestCase):
    def test_fills_months_up_to_report_month_and_leaves_later_blank(self):
        rows = [row("2026-%02d" % m, "판매비와관리비", "81100", "복리후생비", 100) for m in range(1, 13)]
        A = account_year(rows, "2026-03")
        a = A["groups"][0]["accounts"][0]
        self.assertEqual(a["months"][:3], [100, 100, 100])
        self.assertEqual(a["months"][3:], [None] * 9)
        self.assertEqual(a["total"], 300)
        self.assertEqual(A["total"], 300)

    def test_other_years_are_left_out_and_groups_keep_order(self):
        rows = [row("2025-12", "원가", "53300", "외주", 999), row("2026-01", "영업외비용", "93100", "이자비용", 5),
                row("2026-01", "원가", "53300", "외주", 7), row("2026-02", "판매비와관리비", "81100", "복리", 3)]
        A = account_year(rows, "2026-02")
        self.assertEqual([g["name"] for g in A["groups"]], ["원가", "판매비와관리비", "영업외비용"])
        self.assertEqual(A["months"][:2], [12, 3])
        self.assertEqual(A["total"], 15)

    def test_unknown_amount_makes_the_cell_unknown_not_zero(self):
        rows = [row("2026-01", "원가", "53300", "외주", None), row("2026-02", "원가", "53300", "외주", 4)]
        A = account_year(rows, "2026-02")
        g = A["groups"][0]
        self.assertIsNone(g["accounts"][0]["months"][0])
        self.assertIsNone(g["months"][0])
        self.assertTrue(A["partial"])

    def test_no_file_says_so(self):
        self.assertEqual(account_year(None, "2026-10")["state"], "자료 없음")


class TestAccumulation(unittest.TestCase):
    def test_months_missing_from_new_journal_are_kept(self):
        """새 분개장에 없는 달의 이전 줄은 계정별비용.csv 에 그대로 남는다 (누적)."""
        prev = [{"연월": "2026-01", "구분": "원가", "계정코드": "53300", "계정과목": "외주", "금액": "1,000"}]
        books = type("B", (), {"journal": []})()
        T = build_accounts(books, {"nonop_out_codes": []}, prev)
        self.assertTrue(any(r["연월"] == "2026-01" for r in T.rows))


class TestMonthlyPage(unittest.TestCase):
    def test_monthly_reports_have_the_table_and_weekly_does_not(self):
        d = load(SAMPLE)
        M = compute(d, "monthly", dt.date(2026, 10, 31))
        for mode in ("ceo", "mgmt"):
            html = render(M, mode)
            self.assertIn("계정과목별 사용 금액 (2026년 1월~10월)", html)
            self.assertIn("판매비와관리비 소계", html)
        W = compute(load(SAMPLE), "weekly", dt.date(2026, 10, 31))
        self.assertNotIn("계정과목별 사용 금액", render(W, "ceo"))


if __name__ == "__main__":
    unittest.main()
