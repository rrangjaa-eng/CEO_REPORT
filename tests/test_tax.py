"""세금 납부 예상 (사용자 2026-11-03): 분개장 부가세예수금·부가세대급금·예수금으로 부가세(분기)·원천세 납부액. 합성 자료만."""
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from ceo_report import tax  # noqa: E402

D = dt.date


def ln(day, no, code, debit=None, credit=None, vendor=""):
    return {"date": day, "no": no, "account_code": code, "account": "", "debit": debit, "credit": credit, "vendor": vendor}


class TestVat(unittest.TestCase):
    def journal(self):
        return [
            # 3분기: 매출세액 100, 매입세액 30, 분기말 상계(예수금 차변 30 / 대급금 대변 30), 10/23 미지급 계상 70
            ln(D(2026, 8, 5), "1", "25500", credit=100), ln(D(2026, 8, 6), "2", "13500", debit=30),
            ln(D(2026, 9, 30), "8", "25500", debit=30), ln(D(2026, 9, 30), "8", "13500", credit=30),
            ln(D(2026, 10, 23), "9", "25500", debit=70), ln(D(2026, 10, 23), "9", "26200", credit=70),
            # 4분기 (진행 중): 매출세액 500 − 매입세액 120 − 매출 취소 20 (매출 계정과 같은 전표)
            ln(D(2026, 10, 10), "3", "25500", credit=500), ln(D(2026, 10, 20), "4", "13500", debit=120),
            ln(D(2026, 11, 2), "5", "25500", debit=20), ln(D(2026, 11, 2), "5", "41200", debit=200),
        ]

    def test_open_quarter_estimate_excludes_previous_quarter_payment(self):
        rows = tax.vat(self.journal(), D(2026, 11, 3))
        self.assertEqual([(r["대상기간"], r["납부예정일"], r["금액"], r["상태"]) for r in rows],
                         [("2026년 4분기 (10~12월)", "2027-01-25", "360", "예상")])
        self.assertIn("2026-11-02까지", rows[0]["근거"])

    def test_estimate_before_payment_equals_payment_slip(self):
        before = tax.vat([x for x in self.journal() if x["date"] <= D(2026, 9, 30)], D(2026, 10, 3))
        self.assertEqual((before[0]["금액"], before[0]["상태"]), ("70", "예상"))
        after = tax.vat(self.journal(), D(2026, 10, 3))
        self.assertEqual((after[0]["대상기간"], after[0]["납부예정일"], after[0]["금액"], after[0]["상태"]),
                         ("2026년 3분기 (7~9월)", "2026-10-26", "70", "확정(전표)"))   # 10/25 일요일 → 월요일


class TestWithholding(unittest.TestCase):
    def test_half_year_payer_accumulates_to_january(self):
        j = [ln(D(2026, 1, 9), "1", "25400", debit=50, vendor="역삼세무서"),
             ln(D(2026, 7, 10), "2", "25400", debit=60, vendor="역삼세무서"),
             ln(D(2026, 8, 25), "3", "25400", credit=10, vendor="역삼세무서"),
             ln(D(2026, 8, 25), "3", "25400", credit=1, vendor="강남구청"),
             ln(D(2026, 9, 25), "4", "25400", credit=10, vendor="역삼세무서"),
             ln(D(2026, 9, 25), "4", "25400", credit=7, vendor="건강보험공단")]   # 4대보험은 넣지 않음
        rows = tax.withholding(j, D(2026, 11, 3))
        self.assertEqual([(r["대상기간"], r["납부예정일"], r["금액"]) for r in rows], [("2026년 하반기 (7~12월)", "2027-01-11", "21")])

    def test_monthly_payer_due_next_month_tenth(self):
        j = [ln(D(2026, 9, 10), "1", "25400", debit=5, vendor="역삼세무서"),
             ln(D(2026, 10, 25), "2", "25400", credit=8, vendor="역삼세무서")]
        rows = tax.withholding(j, D(2026, 11, 3))
        self.assertEqual([(r["대상기간"], r["납부예정일"], r["금액"]) for r in rows], [("2026년 10월분", "2026-11-10", "8")])


class TestMerge(unittest.TestCase):
    T = {"kind": "부가세", "period": "2026년 4분기", "due": D(2027, 1, 25), "amount": 360, "state": "예상", "basis": ""}

    def test_estimate_added_when_plan_has_no_tax(self):
        events, info = tax.merge([], [self.T])
        self.assertEqual([(e["date"], e["amount"], e["firm"], e["source"]) for e in events], [(D(2027, 1, 25), 360, False, "세금예상")])
        self.assertIsNone(info[0]["matched"])

    def test_plan_entry_wins_and_difference_is_shown(self):
        plan = {"date": D(2027, 1, 25), "io": "out", "amount": 400, "firm": True, "cat": "", "desc": "역삼세무서", "basis": ""}
        events, info = tax.merge([plan], [self.T])
        self.assertEqual(events, [plan])   # 두 번 빼지 않음
        self.assertEqual(info[0]["diff"], 40)


if __name__ == "__main__":
    unittest.main()
