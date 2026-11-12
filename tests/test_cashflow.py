"""현금흐름표 (사용자 2026-11-12): 직접법 = 통장 증감, 이익→현금 맞추기 = 본업 합계, 경영관리 보고에만."""
import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import cashflow as C  # noqa: E402

D = dt.date


def ln(day, no, code, name, dr=0, cr=0, vendor="", memo="", sort="일반전표"):
    return {"date": day, "no": no, "sort": sort, "account_code": code, "account": name,
            "debit": dr or None, "credit": cr or None, "vendor": vendor, "memo": memo}


def journal():
    j = []
    # 9월: 매출 계산서 (현금 없음) 1,100 → 10월 입금
    j += [ln(D(2026, 9, 30), "1", "10800", "수입수수료미수금", dr=1100, vendor="고객A", sort="매출전표"),
          ln(D(2026, 9, 30), "1", "41200", "수입수수료", cr=1000, vendor="고객A", sort="매출전표"),
          ln(D(2026, 9, 30), "1", "25500", "부가세예수금", cr=100, vendor="고객A", sort="매출전표")]
    j += [ln(D(2026, 10, 2), "1", "10300", "보통예금", dr=1100, vendor="신한은행"),
          ln(D(2026, 10, 2), "1", "10800", "수입수수료미수금", cr=1100, vendor="고객A")]
    # 10월: 업체 비용 550 미지급 → 일부 300 지급
    j += [ln(D(2026, 10, 5), "50001", "63300", "행사외주비(도)", dr=500, vendor="업체B", sort="매입전표"),
          ln(D(2026, 10, 5), "50001", "13500", "부가세대급금", dr=50, vendor="업체B", sort="매입전표"),
          ln(D(2026, 10, 5), "50001", "25300", "미지급금", cr=550, vendor="업체B", sort="매입전표")]
    j += [ln(D(2026, 10, 6), "2", "25300", "미지급금", dr=300, vendor="업체B"),
          ln(D(2026, 10, 6), "2", "10300", "보통예금", cr=300, vendor="신한은행")]
    # 카드 대금, 대출+이자, 정기예금, 계좌 사이 이체, 전기이월(빼야 함)
    j += [ln(D(2026, 10, 15), "3", "26200", "미지급비용", dr=200, vendor="신한_5860"),
          ln(D(2026, 10, 15), "3", "10300", "보통예금", cr=200, vendor="신한은행")]
    j += [ln(D(2026, 10, 20), "4", "29300", "장기차입금", dr=100, vendor="신한은행"),
          ln(D(2026, 10, 20), "4", "93100", "이자비용", dr=10, vendor="신한은행"),
          ln(D(2026, 10, 20), "4", "10300", "보통예금", cr=110, vendor="신한은행")]
    j += [ln(D(2026, 10, 21), "5", "10500", "정기예.적금", dr=400, vendor="신한은행"),
          ln(D(2026, 10, 21), "5", "10300", "보통예금", cr=400, vendor="신한은행")]
    j += [ln(D(2026, 10, 22), "6", "10300", "보통예금", dr=50, vendor="기업은행", memo="계좌이체"),
          ln(D(2026, 10, 22), "6", "10300", "보통예금", cr=50, vendor="신한은행", memo="계좌이체")]
    j += [ln(D(2026, 1, 1), "9", "10300", "보통예금", dr=9999, memo="전기이월"),
          ln(D(2026, 1, 1), "9", "33100", "자본금", cr=9999, memo="전기이월")]
    return j


class TestCashflow(unittest.TestCase):
    def setUp(self):
        self.rows = C.build_rows(journal(), ("10300",))
        self.CF = C.compute(self.rows, D(2026, 10, 1), D(2026, 10, 31), 5000, None, "10월")

    def test_direct_sum_equals_bank_change_and_items(self):
        M = self.CF["M"]
        self.assertEqual(M["total"], 1100 - 300 - 200 - 110 - 400)
        self.assertEqual(M["cash"]["고객"], 1100)
        self.assertEqual(M["cash"]["업체"], -300)
        self.assertEqual(M["cash"]["카드"], -200)
        self.assertEqual(M["cash"]["이자낸"], -10)
        self.assertEqual(M["cash"]["대출갚음"], -100)
        self.assertEqual(M["cash"]["정기넣음"], -400)
        self.assertEqual(M["op"] + M["inv"] + M["fin"], M["total"])
        self.assertNotIn("자본", M["cash"])   # 전기이월 전표는 넣지 않음

    def test_profit_to_cash_reconciles_to_operating(self):
        M = self.CF["M"]
        r = M["rec"]
        self.assertEqual(r["이익"], -510)          # 10월: 외주비 500 + 이자 10
        self.assertEqual(r["받을돈"], 1100)        # 미수금 줄어듦 → 현금 +
        self.assertEqual(r["줄돈"], 550 - 300 - 200)
        self.assertEqual(r["세금예수"], -50)
        self.assertEqual(r["그밖"], 0)
        self.assertEqual(sum(r.values()), M["op"])

    def test_balances_are_backed_out_from_end(self):
        self.assertEqual(self.CF["start"], 5000 - self.CF["M"]["total"])
        self.assertEqual(self.CF["ystart"], 5000 - self.CF["Y"]["total"])
        self.assertEqual(self.CF["months"][-1][4], 5000)

    def test_diagnosis_and_insights_follow_numbers(self):
        dg = C.diagnose(self.CF)
        self.assertIn(dg["name"], [v[0] for v in C.STATES.values()])
        self.assertEqual(len(dg["signs"]), 3)
        html = C.render(self.CF)
        for t in ("지금 회사 상태", "이 표로 알 수 있는 것", "현금흐름을 좋게 하려면", "영업활동 현금흐름", "투자활동 현금흐름", "재무활동 현금흐름", "낱말 풀이"):
            self.assertIn(t, html)

    def test_states_cover_every_sign_combination(self):
        for a in "+-":
            for b in "+-":
                for c in "+-":
                    self.assertIn(a + b + c, C.STATES)

    def test_annual_period(self):
        A = C.annual(self.rows, 2026, 5000)
        self.assertTrue(A["annual"])
        self.assertEqual(A["p0"], D(2026, 1, 1))
        self.assertIn("2026년", C.render(A))

    def test_missing_file_renders_note(self):
        self.assertIn("현금흐름표 자료 없음", C.render(None))


class TestCashflowInReport(unittest.TestCase):
    def test_monthly_management_has_chapter_but_ceo_does_not(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from sample_input import SAMPLE, refresh
        from ceo_report.calc import compute
        from ceo_report.data import load
        from ceo_report.render import render
        refresh()
        R = compute(load(SAMPLE), "monthly", D(2026, 10, 31))
        rows = C.build_rows(journal(), ("10300",))
        R["cf"] = C.compute(rows, D(2026, 10, 1), D(2026, 10, 31), 5000, None, "10월")
        self.assertIn("9. 현금흐름표", render(R, "mgmt"))
        self.assertNotIn("현금흐름표", render(R, "ceo"))


if __name__ == "__main__":
    unittest.main()
