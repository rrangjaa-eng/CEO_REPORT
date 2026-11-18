"""2차 전수조사 제안 13: 신고 도우미 (V3·V6·V7·V8·V11·J16·J17). 가상 자료만."""
import csv
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import checklist, filehelp, filing  # noqa: E402

D = dt.date


def ln(date, no, sort, code, account, debit=0, credit=0, vendor="", memo=""):
    return {"date": date, "no": no, "sort": sort, "account_code": code, "account": account, "debit": debit, "credit": credit,
            "vendor": vendor, "memo": memo}


class Vat(unittest.TestCase):
    def test_car_purchase_is_a_non_deductible_candidate(self):   # V3
        J = [ln(D(2026, 8, 1), "1", "매입전표", "82200", "차량유지비(판)", debit=100000),
             ln(D(2026, 8, 1), "1", "매입전표", "13500", "부가세대급금", debit=10000),
             ln(D(2026, 8, 1), "1", "매입전표", "25300", "미지급금", credit=110000, vendor="주유소"),
             ln(D(2026, 8, 2), "2", "매입전표", "83100", "지급수수료(판)", debit=200000),
             ln(D(2026, 8, 2), "2", "매입전표", "13500", "부가세대급금", debit=20000),
             ln(D(2026, 8, 2), "2", "매입전표", "25300", "미지급금", credit=220000, vendor="가상")]
        V = filehelp.vat(J, D(2026, 7, 1), D(2026, 9, 30))
        self.assertEqual(V["in"], 20000)   # 차량 10,000 은 공제에서 뺌
        box16 = [r for r in V["rows"] if r[0] == "16"][0]
        self.assertEqual((box16[2], box16[3]), (100000, 10000))
        self.assertIn("승용차", box16[1])
        self.assertTrue(any("차량유지비·차량운반구 매입 1장" in c for c in V["check"]))

    def test_cancelled_sales_invoice_keeps_supply_and_tax_in_step(self):   # V7
        J = [ln(D(2026, 8, 1), "1", "매출전표", "40100", "매출", credit=1000000),
             ln(D(2026, 8, 1), "1", "매출전표", "25500", "부가세예수금", credit=100000),
             ln(D(2026, 8, 1), "1", "매출전표", "10800", "외상매출금", debit=1100000),
             ln(D(2026, 8, 5), "2", "매출전표", "40100", "매출", debit=400000),
             ln(D(2026, 8, 5), "2", "매출전표", "25500", "부가세예수금", debit=40000),
             ln(D(2026, 8, 5), "2", "매출전표", "10800", "외상매출금", credit=440000)]
        V = filehelp.vat(J, D(2026, 7, 1), D(2026, 9, 30))
        r = [x for x in V["rows"] if x[0] == "1"][0]
        self.assertEqual((r[2], r[3]), (600000, 60000))


class Withholding(unittest.TestCase):
    def test_half_year_in_january_and_july_is_the_one_just_ended(self):   # V8
        self.assertEqual(filehelp.half_of(D(2026, 7, 5)), (D(2026, 1, 1), D(2026, 6, 30)))
        self.assertEqual(filehelp.half_of(D(2026, 7, 31)), (D(2026, 1, 1), D(2026, 6, 30)))
        self.assertEqual(filehelp.half_of(D(2026, 8, 1)), (D(2026, 7, 1), D(2026, 12, 31)))
        self.assertEqual(filehelp.half_of(D(2027, 1, 9)), (D(2026, 7, 1), D(2026, 12, 31)))
        self.assertEqual(filehelp.half_of(D(2026, 6, 30)), (D(2026, 1, 1), D(2026, 6, 30)))

    def test_unclassified_memo_is_shown_not_dropped(self):   # V6
        J = [ln(D(2026, 8, 5), "1", "", "25400", "예수금", credit=1000, vendor="역삼세무서", memo="급여지급시 소득세예수"),
             ln(D(2026, 8, 5), "1", "", "25400", "예수금", credit=700, vendor="역삼세무서", memo="8월 원천징수분"),
             ln(D(2026, 8, 5), "1", "", "25400", "예수금", credit=70, vendor="강남구청", memo="8월 원천징수분")]
        got = filehelp.withholding(J, D(2026, 7, 1), D(2026, 12, 31))
        self.assertEqual([(k, a, b) for k, _, a, b in got], [("A01", 1000, 0), ("?", 700, 70)])


class Deadlines(unittest.TestCase):
    def test_holiday_moves_to_next_working_day(self):   # V11
        self.assertEqual(filing._workday(D(2027, 2, 28)), D(2027, 3, 2))   # 일요일 → 3/1 삼일절 → 3/2
        self.assertEqual(filing._workday(D(2026, 10, 25)), D(2026, 10, 26))
        self.assertEqual(filing._workday(D(2026, 11, 10)), D(2026, 11, 10))

    def test_past_due_label(self):   # J17
        rows = [{"신고": "부가세", "기간": "2026년 2기 예정 (7~9월)", "기한": "2026-10-26", "칸": "1", "이름": "가", "공급가액": "1",
                 "세액": "1", "지방소득세": "", "근거": ""}]
        self.assertIn("기한이 지난 신고", filehelp.render(rows, str, D(2026, 11, 18)))
        self.assertNotIn("기한이 지난 신고", filehelp.render(rows, str, D(2026, 10, 20)))


class DoneFromChecklist(unittest.TestCase):   # J16
    def setUp(self):
        self.inp = tempfile.mkdtemp()
        with open(os.path.join(self.inp, filing.FILE), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, filing.COLUMNS)
            w.writeheader()
            w.writerow({"기한": "2026-10-26", "신고": "부가세 2기 예정신고", "대상": "2026년 7~9월", "장부 근거": "", "어디서": "",
                        "상태": "지남 — 했는지 확인"})
            w.writerow({"기한": "2026-11-30", "신고": "사업소득 간이지급명세서", "대상": "2026년 10월 지급분", "장부 근거": "",
                        "어디서": "", "상태": "12일 남음"})

    def tearDown(self):
        shutil.rmtree(self.inp, ignore_errors=True)

    def test_overdue_item_goes_away_after_done(self):
        asof = D(2026, 11, 18)
        items = filing.check_items(self.inp)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], "신고 기한")
        for ch in items[0]["choices"]:
            self.assertIn(ch, checklist.CHOICE_STATE)
        self.assertEqual(len(filing.live_lines(filing.load(self.inp), asof)), 2)
        checklist.save_decision(self.inp, items[0]["id"], "처리함")
        rows = filing.load(self.inp)
        self.assertTrue(rows[0]["상태"].startswith("했음"))
        lines = filing.live_lines(rows, asof)
        self.assertEqual(len(lines), 1)
        self.assertIn("사업소득 간이지급명세서", lines[0])

    def test_in_progress_stays(self):
        items = filing.check_items(self.inp)
        checklist.save_decision(self.inp, items[0]["id"], "진행 중 — 확인 필요")
        self.assertTrue(filing.load(self.inp)[0]["상태"].startswith("지남"))


if __name__ == "__main__":
    unittest.main()
