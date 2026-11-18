"""2차 전수조사 제안 20 (P8): 위하고 전표 적요의 '[수금예정일:…]'·'[지급예정일:…]'이 있으면 그 날짜가 먼저 (작성일 + 60일은 없을 때만)."""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report import convert_invoices, convert_projects, wehago  # noqa: E402
import test_convert_invoices as TI  # noqa: E402

MEMO = "매출 - 0000-001-[수금예정일:2026.12.05]-(세금계산서 교부분)[가상고객D]"


class TestMemoDue(unittest.TestCase):
    def test_reads_the_fixed_mark_only(self):
        self.assertEqual(wehago.memo_due(MEMO, "수금"), dt.date(2026, 12, 5))
        self.assertIsNone(wehago.memo_due(MEMO, "지급"))
        self.assertEqual(wehago.memo_due("매입 - x-[지급예정일:2025.11.28]-(세금계산서 교부분)[가]", "지급"), dt.date(2025, 11, 28))
        self.assertIsNone(wehago.memo_due("수금예정일 2026.12.05 쯤", "수금"))     # 정해진 표시가 아니면 읽지 않음
        self.assertIsNone(wehago.memo_due("[수금예정일:2026.02.31]", "수금"))       # 없는 날짜
        self.assertIsNone(wehago.memo_due(None, "수금"))

    def test_journal_invoice_row_carries_it(self):
        def ln(acc, code, debit, credit, memo):
            return {"date": dt.date(2026, 10, 27), "no": "1", "sort": "매출전표", "account": acc, "account_code": code,
                    "debit": debit, "credit": credit, "vendor": "가상고객D", "vendor_code": "00123", "memo": memo, "project_name": ""}
        _, sales = wehago.invoices_from_journal([ln("외상매출금", "10800", 1100, None, MEMO), ln("매출", "40100", None, 1000, MEMO),
                                                 ln("부가세예수금", "25500", None, 100, "")])
        self.assertEqual(sales[0]["due_memo"], dt.date(2026, 12, 5))
        self.assertEqual(wehago._sales_row(sales[0])["due_memo"], dt.date(2026, 12, 5))


class TestInvoiceDue(unittest.TestCase):
    def _build(self, prev_rows):
        sales, books, revenue, projects, cfg = TI.invoice_inputs(self)
        for r in sales["rows"]:
            if r["date"] == dt.date(2026, 10, 27):
                r["due_memo"] = dt.date(2026, 12, 5)
        return convert_invoices.build_invoices(sales, books, revenue, projects, prev_rows, cfg)

    def test_memo_day_wins_over_the_60_day_guess(self):
        t = self._build([])
        self.assertEqual(TI.row_of(t, "2026-10-27")[6:8], ("2026-12-05", "N"))
        self.assertTrue([n for n in t.notes if "위하고 전표 적요의 수금예정일로 채운 계산서 1건" in n])
        self.assertFalse([n for n in t.notes if "작성일 + 60일" in n and "2026-10-27" in n])

    def test_last_time_guess_is_replaced_but_a_hand_date_stays(self):
        t = self._build([TI.prev_row(due="2026-12-26", firm="N")])   # 지난번에 작성일 + 60일로 채운 값
        self.assertEqual(TI.row_of(t, "2026-10-27")[6:8], ("2026-12-05", "N"))
        t = self._build([TI.prev_row(due="2026-11-30", firm="Y")])   # 손으로 넣은 날짜
        self.assertEqual(TI.row_of(t, "2026-10-27")[6:8], ("2026-11-30", "Y"))


class TestPayableRow(unittest.TestCase):
    def _g(self, **kw):
        g = {"project": "P1", "item": "가", "vendor_text": "나", "state": "요청미지급", "supply_cell": "1", "vat_cell": "0",
             "paid_day": None, "firm": False, "basis": "WEHAGO 2026-11-01 전표 1", "memo_day": dt.date(2026, 11, 20)}
        g.update(kw)
        return g

    def test_unpaid_row_without_a_day_takes_the_memo_day(self):
        r = convert_projects._row_of(self._g())
        self.assertEqual((r["일자"], r["확정여부"]), ("2026-11-20", "추정"))
        self.assertIn("위하고 전표 지급예정일", r["근거"])

    def test_a_request_day_or_a_paid_row_is_left_alone(self):
        self.assertEqual(convert_projects._row_of(self._g(paid_day=dt.date(2026, 11, 25)))["일자"], "2026-11-25")
        r = convert_projects._row_of(self._g(state="지급완료", paid_day=dt.date(2026, 11, 5), firm=True))
        self.assertEqual(r["일자"], "2026-11-05")
        self.assertNotIn("지급예정일", r["근거"])


if __name__ == "__main__":
    unittest.main()
