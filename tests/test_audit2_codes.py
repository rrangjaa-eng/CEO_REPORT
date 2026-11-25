"""2차 전수조사 제안 16 (P4·D6·D8): 낱말 판단을 한곳에, 계산서 거래처코드. 가상 자료만."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import budget, calc, codes, insights, teamreport, wehago  # noqa: E402


class Codes(unittest.TestCase):
    def test_pay_accounts_by_code_then_name(self):
        self.assertTrue(codes.is_pay_account("아무이름", "80500"))      # 코드가 먼저 (잡급)
        self.assertTrue(codes.is_pay_account("잡급(판)"))
        self.assertTrue(codes.is_pay_account("퇴직급여(판)", "80800"))
        self.assertFalse(codes.is_pay_account("복리후생비(판)", "81100"))
        self.assertTrue(codes.is_dep_account("감가상각비(판)"))

    def test_team_leader_report_hides_jabgeup(self):
        self.assertTrue(teamreport._is_pay_account("잡급(판)"))
        self.assertTrue(teamreport._is_pay_account("퇴직급여(판)"))
        self.assertFalse(teamreport._is_pay_account("복리후생비(판)"))

    def test_word_lists_are_shared(self):
        self.assertEqual(calc.MUST_VENDOR, ("세무서", "구청", "시청", "군청", "공단"))
        self.assertEqual(insights.TAXOFF, ("세무서", "구청", "시청", "군청"))
        for w in ("급여", "상여", "퇴직", "임금", "제수당", "잡급"):
            self.assertIn(w, budget.SALARY_WORDS)

    def test_judged_lines_show_code(self):
        J = [{"vendor": "역삼세무서", "vendor_code": "00133", "account_code": "25400", "account": "예수금"},
             {"vendor": "신한_5860", "vendor_code": "00201", "account_code": "25300", "account": "미지급금"},
             {"vendor": "", "vendor_code": "", "account_code": "80500", "account": "잡급(판)"},
             {"vendor": "가상상사", "vendor_code": "00999", "account_code": "83100", "account": "지급수수료(판)"}]
        got = "\n".join(codes.judged_lines(J))
        self.assertIn("역삼세무서(00133)", got)
        self.assertIn("신한_5860(00201)", got)
        self.assertIn("잡급(판)(80500)", got)
        self.assertNotIn("가상상사", got)


class SalesVendorCode(unittest.TestCase):   # D6
    def test_sales_row_keeps_vendor_code(self):
        row = wehago._sales_row({"date": None, "vendor": "가", "vendor_norm": "가", "item": "", "supply": 1, "vat": 0, "total": 1,
                                 "code": None, "vendor_code": "00101"})
        self.assertEqual(row["vendor_code"], "101")


if __name__ == "__main__":
    unittest.main()
