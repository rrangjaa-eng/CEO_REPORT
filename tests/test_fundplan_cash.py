"""자금계획서 인쇄형태 '현금대비잔액' 읽기 (2026-11-05 사용자 선택). 합성 자료만 쓴다.

모양(실제 파일 확인): 머리글 '일자|항목명|입금액|지출액|현금잔액', '[전월이월]' 잔액, 분류 줄 'DD|항목명|입금 합|지출 합',
상세 '예정일:YYYY.MM.YYYYMMDD-거래처[코드]', 이미 반제된 상세는 금액 없음, 쪽마다 머리 되풀이, 끝에 '[합계]'."""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from ceo_report import convert, fundplan  # noqa: E402
from test_fundplan import print_rows, write_plan, ITEMS_NOV  # noqa: E402

HEAD = ["일자", "항목명", "입금액", "지출액", "현금잔액"]
# (일, 분류, [(거래처, 코드, 입금, 지출)])  — 금액 0,0 은 이미 반제된 줄
DAYS = [
    (4, "외상대금 회수", [("가상고객", "000900", 0, 0)]),
    (6, "미지급금 지급", [("가상상사", "000001", 0, 990000), ("가상상사", "000001", 0, 1000), ("가상인쇄", "000002", 0, 4114000)]),
    (13, "미지급금 지급", [("가상음향", "000003", 0, 2451900)]),
    (20, "외상대금 회수", [("가상고객2", "000901", 15922199, 0), ("가상고객3", "000902", 0, 0)]),
]


def cash_rows(year=2026, month=11, days=DAYS, opening=350893674, page=6, break_total=False):
    rows = [["자 금 계 획 서"], [], ["계획기간 : %d년%d월" % (year, month)], [], ["회사명 :가상회사", "", "", "", "단위(원)"], [], HEAD,
            ["", "          [전   월   이   월]", float(opening), "", ""]]
    body, bal = [], opening
    tin = tout = 0
    for d, cat, lines in days:
        ci, co = sum(x[2] for x in lines), sum(x[3] for x in lines)
        body.append(["%02d" % d, cat, float(ci) if ci else "", float(co) if co else "", ""])
        for k, (v, code, i, o) in enumerate(lines):
            bal += i - o
            last = k == len(lines) - 1
            body.append(["", "예정일:%d.%02d.%d%02d%02d-%s[%s]" % (year, month, year, month, d, v, code),
                         float(i) if i else "", float(o) if o else "", float(bal) if last else ""])
        tin, tout = tin + ci, tout + co
    for i in range(0, len(body), page):
        rows += body[i:i + page]
        if i + page < len(body):
            rows += [[], [], ["회사명 :가상회사", "", "", "", "단위(원)"], [], HEAD]
    rows.append(["", "          [합              계]", float(tin + (1 if break_total else 0)), float(tout), float(bal)])
    return rows


class TestCashForm(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def test_parse_lines_settled_and_opening(self):
        r = fundplan.parse_cash(cash_rows())
        self.assertTrue(r["ok"], r["reason"])
        self.assertEqual(r["month"], (2026, 11))
        self.assertEqual(r["opening"], 350893674)
        self.assertEqual([(i["date"].day, i["io"], i["vendor_code"], i["amount"]) for i in r["items"]],
                         [(6, "out", "000001", 990000), (6, "out", "000001", 1000), (6, "out", "000002", 4114000),
                          (13, "out", "000003", 2451900), (20, "in", "000901", 15922199)])
        self.assertEqual(sorted((s["date"].day, s["vendor_code"]) for s in r["settled"]), [(4, "000900"), (20, "000902")])

    def test_total_mismatch_not_used(self):
        r = fundplan.parse_cash(cash_rows(break_total=True))
        self.assertFalse(r["ok"])
        self.assertIn("합계", r["reason"])

    def test_detected_by_header(self):
        self.assertTrue(fundplan.is_cash_form(cash_rows()))
        self.assertFalse(fundplan.is_cash_form(print_rows(2026, 11, ITEMS_NOV)))
        self.assertTrue(fundplan.is_fundplan_name("261105 자금계획서_현금대비잔액.xls"))

    def test_load_prefers_cash_form_same_day(self):
        write_plan(self.dir, "261105 자금계획서_지출입금현황.xls", print_rows(2026, 11, ITEMS_NOV))
        write_plan(self.dir, "261105 자금계획서_현금대비잔액.xls", cash_rows())
        res = fundplan.load(self.dir)
        self.assertEqual([m[1] for m in res["months"]], ["261105 자금계획서_현금대비잔액.xls"])
        self.assertIn("261105 자금계획서_지출입금현황.xls", res["unused"])
        self.assertEqual(res["openings"], [((2026, 11), 350893674, "261105 자금계획서_현금대비잔액.xls")])
        self.assertEqual(len(res["settled"]), 2)
        self.assertEqual(len(res["rows"]), 5)

    def test_newer_spending_form_still_wins(self):
        write_plan(self.dir, "261104 자금계획서_현금대비잔액.xls", cash_rows())
        write_plan(self.dir, "261105 자금계획서_지출입금현황.xls", print_rows(2026, 11, ITEMS_NOV))
        res = fundplan.load(self.dir)
        self.assertEqual([m[1] for m in res["months"]], ["261105 자금계획서_지출입금현황.xls"])

    def test_cash_rows_ignore_payments_before_file_date(self):
        # 10/30 에 같은 거래처·같은 금액을 이미 낸 전표(지난 계산서) — 현금대비잔액은 위하고가 남은 건이라 했으므로 '예정'
        rows = [{"예정일": "2026-11-13", "입출금": "지급", "분류": "", "거래처": "가상음향", "거래처코드": "000003",
                 "금액": 2451900, "자료일": "2026-11-05", "파일": "261105 자금계획서_현금대비잔액.xls", "상태": "", "근거": ""}]
        line = {"date": dt.date(2026, 10, 30), "account_code": "25300", "debit": 2451900, "credit": None,
                "vendor": "가상음향", "vendor_code": "00003", "no": "00017", "account": "미지급금"}
        books = SimpleNamespace(state="ok", journal=[line], book_date=dt.date(2026, 11, 5))
        fundplan.settle(rows, books, dt.date(2026, 11, 5))
        self.assertEqual(rows[0]["상태"], "예정")
        rows[0].update(파일="261105 자금계획서_지출입금현황.xls", 상태="")   # 예전 양식은 지금처럼 추정
        fundplan.settle(rows, books, dt.date(2026, 11, 5))
        self.assertEqual(rows[0]["상태"], "이미 지급")

    def test_opening_check(self):
        cfg = {"cash_codes": ("10300",)}
        j = [{"date": dt.date(2025, 2, 1), "account_code": "10300", "debit": 350000000, "credit": None},
             {"date": dt.date(2026, 10, 31), "account_code": "10300", "debit": 893674, "credit": None},
             {"date": dt.date(2026, 11, 2), "account_code": "10300", "debit": None, "credit": 5000}]
        books = SimpleNamespace(journal=j, book_date=dt.date(2026, 11, 5), from_start=True)
        ok = convert.fundplan_opening_checks([((2026, 11), 350893674, "f.xls")], books, cfg)
        self.assertIn("일치", ok[0])
        bad = convert.fundplan_opening_checks([((2026, 11), 350000000, "f.xls")], books, cfg)
        self.assertTrue(bad[0].startswith("[확인]"))
        books.from_start = False
        self.assertIn("대조 안 함", convert.fundplan_opening_checks([((2026, 11), 1, "f.xls")], books, cfg)[0])


if __name__ == "__main__":
    unittest.main()
