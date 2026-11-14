"""2026-11-14 오후 '숫자 오차·오해 소지' 점검(Claude+코덱스)에서 확인한 오류를 다시 생기지 않게 막는 시험.

번호(F1·T4 …)는 /mnt/project-files/ceo-report/숫자오차·오해소지·코드점검_20261114.md 의 항목 번호.
"""
import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

D = dt.date


def _books(lines, book_date=D(2026, 11, 12)):
    from ceo_report import wehago
    b = wehago.Books()
    b.state, b.book_date = "ok", book_date
    for no, day, code, account, debit, credit, vendor in lines:
        b.journal.append({"date": day, "no": no, "account_code": code, "account": account, "debit": debit,
                          "credit": credit, "vendor": vendor, "memo": "", "sort": ""})
    return b


class TestF1OneSlipManyVendors(unittest.TestCase):
    """F1: 한 이체 전표로 여러 거래처에 준 돈 — 둘째 거래처를 '안 준 돈'으로 남기면 다음 금요일 출금 목록에 다시 올라간다."""

    def _settle(self, rows, lines):
        from ceo_report import fundplan
        fundplan.settle(rows, _books(lines), D(2026, 11, 12))
        return [r["상태"] for r in rows]

    def test_one_transfer_slip_two_vendors_one_bank_line(self):
        from test_fundplan import plan_row
        rows = [plan_row("2026-11-10", "지급", "가상음향", 10000000), plan_row("2026-11-10", "지급", "나무조명", 20000000)]
        lines = [("8", D(2026, 11, 10), "25300", "미지급금", 10000000, None, "가상음향"),
                 ("8", D(2026, 11, 10), "25300", "미지급금", 20000000, None, "나무조명"),
                 ("8", D(2026, 11, 10), "10300", "보통예금", None, 30000000, "")]
        self.assertEqual(self._settle(rows, lines), ["이미 지급", "이미 지급"])

    def test_one_transfer_slip_two_vendors_bank_line_each(self):
        from test_fundplan import plan_row
        rows = [plan_row("2026-11-10", "지급", "가상음향", 10000000), plan_row("2026-11-10", "지급", "나무조명", 20000000)]
        lines = [("8", D(2026, 11, 10), "25300", "미지급금", 10000000, None, "가상음향"),
                 ("8", D(2026, 11, 10), "10300", "보통예금", None, 10000000, "가상음향"),
                 ("8", D(2026, 11, 10), "25300", "미지급금", 20000000, None, "나무조명"),
                 ("8", D(2026, 11, 10), "10300", "보통예금", None, 20000000, "나무조명")]
        self.assertEqual(self._settle(rows, lines), ["이미 지급", "이미 지급"])

    def test_one_slip_two_invoices_same_vendor(self):
        # 같은 거래처 계산서 두 장을 한 전표로 지급: 채무 줄 두 개 + 예금 줄 하나
        from test_fundplan import plan_row
        rows = [plan_row("2026-11-10", "지급", "가상음향", 10000000), plan_row("2026-11-11", "지급", "가상음향", 10000000)]
        lines = [("8", D(2026, 11, 10), "25300", "미지급금", 10000000, None, "가상음향"),
                 ("8", D(2026, 11, 10), "25300", "미지급금", 10000000, None, "가상음향"),
                 ("8", D(2026, 11, 10), "10300", "보통예금", None, 20000000, "가상음향")]
        self.assertEqual(self._settle(rows, lines), ["이미 지급", "이미 지급"])

    def test_payable_and_bank_line_of_one_payment_still_count_once(self):
        # PR #20 이 막으려던 것: 한 지급의 채무 줄·예금 줄로 같은 금액 계획 두 줄을 모두 '이미 지급'으로 보지 않는다
        from test_fundplan import plan_row
        rows = [plan_row("2026-11-10", "지급", "가상음향", 10000000), plan_row("2026-11-20", "지급", "가상음향", 10000000)]
        lines = [("7", D(2026, 11, 10), "25300", "미지급금", 10000000, None, "가상음향"),
                 ("7", D(2026, 11, 10), "10300", "보통예금", None, 10000000, "가상음향")]
        self.assertEqual(sorted(self._settle(rows, lines)), ["예정", "이미 지급"])

    def test_receipt_slip_two_customers(self):
        from test_fundplan import plan_row
        rows = [plan_row("2026-11-10", "입금", "가상기획", 11000000), plan_row("2026-11-10", "입금", "나무물산", 22000000)]
        lines = [("9", D(2026, 11, 10), "10300", "보통예금", 33000000, None, ""),
                 ("9", D(2026, 11, 10), "10800", "외상매출금", None, 11000000, "가상기획"),
                 ("9", D(2026, 11, 10), "10800", "외상매출금", None, 22000000, "나무물산")]
        self.assertEqual(self._settle(rows, lines), ["이미 입금", "이미 입금"])

    def test_paid_in_five_installments(self):
        # 다섯 번 나눠 낸 지급: 그 거래처의 기간 안 지급을 모두 더한 것이 계획 금액과 같으면 '이미 지급'
        from test_fundplan import plan_row
        rows = [plan_row("2026-11-10", "지급", "가상음향", 15000000)]
        lines = [(str(10 + i), D(2026, 11, 1 + i), "25300", "미지급금", 3000000, None, "가상음향") for i in range(5)]
        self.assertEqual(self._settle(rows, lines), ["이미 지급"])


from test_teamreport import TeamReportCase, _append, text  # noqa: E402


class TestT4UnknownCostKeepsProject(TeamReportCase):
    """T4: 집행 금액 미확인 줄이 한 건 있으면 그 프로젝트 사전견적까지 팀장 '올해 예상'에서 빠지던 것 (PR #20 에서 생김).

    매출 합계는 사전견적만, 이익 예상은 사전견적·추정 예산만 있으면 된다. 집행액을 모르는 것은 집행액·잔여 칸만 '미확인'."""

    def _unknown_cost_row(self):
        _append(os.path.join(self.folder, "프로젝트집행.csv"), [
            {"프로젝트번호": "P26201", "항목": "추가 장비", "거래처": "가상장비", "상태": "요청미지급", "공급가액": "",
             "부가세": "", "일자": "2026-10-28", "확정여부": "확정", "근거": "금액 확인 중"}])

    def test_unknown_cost_does_not_drop_revenue_or_profit_expectation(self):
        _, _, before, _ = self.make()
        self._unknown_cost_row()
        _, _, after, _ = self.make()
        a = [r for r in after["up"] if r["id"] == "P26201"][0]
        self.assertIsNone(a["paid"])   # 집행액은 미확인 그대로
        self.assertEqual(after["exp_rev"], before["exp_rev"])
        self.assertEqual(after["exp_gp"], before["exp_gp"])
        self.assertEqual(after["up_tot"]["estimate"], before["up_tot"]["estimate"])
        self.assertEqual(after["up_missing"], before["up_missing"])   # '사전견적·추정 예산 없음'은 P26204 한 건 그대로

    def test_paid_and_left_totals_are_unknown_with_the_right_reason(self):
        self._unknown_cost_row()
        _, _, T, page = self.make()
        self.assertIsNone(T["up_tot"]["paid"])
        self.assertIsNone(T["up_tot"]["left"])
        self.assertIn("집행 금액 미확인 1건", text(page))
        self.assertIn("사전견적 또는 추정 예산이 없는 1건", text(page))


if __name__ == "__main__":
    unittest.main()
