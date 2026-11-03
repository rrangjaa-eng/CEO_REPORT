"""WEHAGO 자료를 분개장 하나로 (D-57, 2026-11-03 사용자 결정 카드 '분개장 하나로').

인쇄 분개장의 '유형'이 매입전표·매출전표인 전표로 계산서 단위 자료를 만든다. 매입매출장·전자세금계산서(매입)가 없어도 장부는 ok,
있으면 대조만 한다. 합성 자료만 쓴다.
"""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from ceo_report import wehago  # noqa: E402
import xls_fixture as X  # noqa: E402
from test_journal_xls import HEAD  # noqa: E402
from test_wehago import LEDGER_HEADER, _L, write_xlsx  # noqa: E402

ASOF = dt.date(2026, 10, 31)
P = "[26201] 가상 행사"
# (일자, 번호, 계정코드, 계정과목, 적요, 차변, 대변, 거래처명, 프로젝트명, 유형)
LINES = [
    ("10/05", "50001", "63300", "행사외주비(도)", "음향 장비", 1000000.0, "", "가상음향", P, "매입전표"),
    ("10/05", "50001", "13500", "부가세대급금", "음향 장비", 100000.0, "", "가상음향", P, "매입전표"),
    ("10/05", "50001", "25300", "미지급금", "음향 장비", "", 1100000.0, "가상음향", P, "매입전표"),
    ("10/06", "50002", "81300", "접대비(판)", "식대", 42000.0, "", "가상식당", "", "매입전표"),
    ("10/06", "50002", "25300", "미지급금", "식대", "", 42000.0, "가상식당", "", "매입전표"),
    ("10/07", "50003", "10800", "외상매출금", "행사 대행", 11000000.0, "", "가상고객", P, "매출전표"),
    ("10/07", "50003", "41200", "수입수수료", "행사 대행", "", 10000000.0, "가상고객", P, "매출전표"),
    ("10/07", "50003", "25500", "부가세예수금", "행사 대행", "", 1000000.0, "가상고객", P, "매출전표"),
    ("10/20", "00001", "25300", "미지급금", "음향 지급", 1100000.0, "", "가상음향", "", "일반전표"),
    ("10/20", "00001", "10300", "보통예금", "음향 지급", "", 1100000.0, "가상음향", "", "일반전표"),
]
FULL_HEAD = HEAD


def print_rows(lines=LINES):
    width = len(FULL_HEAD)
    col = dict((h.replace("\n", "").replace(" ", ""), i) for i, h in enumerate(FULL_HEAD))
    rows = [["분개장"] + [""] * (width - 1), ["회사명  :  가상회사", "기 간  : 2026년 01월 01일 ~ 2026년 10월 31일"]
            + [""] * (width - 2), FULL_HEAD]
    for day, no, code, acct, memo, dr, cr, vendor, proj, kind in lines:
        r = [""] * width
        r[col["일자"]], r[col["전표번호"]], r[col["계정코드"]], r[col["계정과목"]], r[col["적요"]] = day, no, code, acct, memo
        r[col["차변"]], r[col["대변"]], r[col["거래처명"]], r[col["프로젝트명"]], r[col["유형"]] = dr, cr, vendor, proj, kind
        r[col["거래처코드"]] = "00001"
        rows.append(r)
    rows.append(["합 계"] + [""] * (width - 1))
    return rows


def write_journal(folder, name="261031 분개장.xls", lines=LINES):
    strings = []
    return X.write_xls(os.path.join(folder, name), X.grid_records(print_rows(lines), strings), strings)


class TestJournalOnly(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def test_journal_alone_is_enough(self):
        write_journal(self.dir)
        b = wehago.load_books(self.dir, ASOF, None)
        self.assertEqual(b.state, "ok", b.reason)
        self.assertTrue(b.from_journal)
        self.assertEqual(b.book_date, dt.date(2026, 10, 31))
        got = sorted((r["date"], r["vendor"], r["supply"], r["vat"], r["total"], r["code"]) for r in b.ledger)
        self.assertEqual(got, [(dt.date(2026, 10, 5), "가상음향", 1000000, 100000, 1100000, "26201"),
                               (dt.date(2026, 10, 6), "가상식당", 42000, 0, 42000, None)])
        self.assertEqual([(r["vendor"], r["supply"], r["vat"], r["code"]) for r in b.journal_sales],
                         [("가상고객", 10000000, 1000000, "26201")])
        self.assertEqual(b.slip_projects.get(("2026-10-05", "50001")), "26201")
        self.assertIn("분개장 매입전표 2건 · 매출전표 1건", b.notes[0])

    def test_sales_come_from_journal(self):
        write_journal(self.dir)
        b = wehago.load_books(self.dir, ASOF, None)
        res = wehago.load_sales(self.dir, ASOF, b)
        self.assertEqual((res["state"], res["source"]), ("ok", "분개장 매출전표"))
        self.assertEqual([(r["vendor"], r["total"]) for r in res["rows"]], [("가상고객", 11000000)])

    def test_already_paid_from_journal_invoices(self):
        write_journal(self.dir)
        b = wehago.load_books(self.dir, ASOF, None)
        paid = wehago.paid_invoices(b)
        idx = [i for i, r in enumerate(b.ledger) if r["vendor"] == "가상음향"][0]
        self.assertIn(("매입매출장", idx), paid)

    def test_ledger_file_is_only_compared(self):
        write_journal(self.dir)
        write_xlsx(os.path.join(self.dir, "매입매출장_20261013.xlsx"), [LEDGER_HEADER] + [
            _L("매입", "2026-10-05", 50001, "가상음향", "", "음향", 1000000, 100000),
            _L("매입", "2026-10-06", 50002, "가상식당", "", "식대", 38182, 0),
            _L("매출", "2026-10-07", 50003, "가상고객", "", "대행", 10000000, 1000000)])
        b = wehago.load_books(self.dir, ASOF, None)
        self.assertEqual(b.state, "ok", b.reason)
        self.assertEqual(b.book_date, dt.date(2026, 10, 31))   # 대조용 파일 날짜는 장부 기준일에 넣지 않는다
        text = "\n".join(b.notes)
        self.assertIn("매입매출장 대조(매입): 분개장 2건 · 매입매출장 2건 · 같음 1건 · 다름 1건", text)
        self.assertIn("매입 2026-10-06 전표 50002: 매입매출장 38,182원 · 분개장 42,000원", text)
        self.assertIn("매입매출장 대조(매출): 분개장 1건 · 매입매출장 1건 · 같음 1건 · 다름 0건", text)

    def test_broken_ledger_does_not_stop_journal(self):
        write_journal(self.dir)
        with open(os.path.join(self.dir, "매입매출장_20261031.xlsx"), "wb") as f:
            f.write(b"broken")
        b = wehago.load_books(self.dir, ASOF, None)
        self.assertEqual(b.state, "ok", b.reason)
        self.assertTrue(any("매입매출장 대조 못함" in n for n in b.notes))

    def test_old_journal_without_invoice_types_still_needs_files(self):
        lines = [l[:9] + ("일반전표",) for l in LINES]
        write_journal(self.dir, lines=lines)
        b = wehago.load_books(self.dir, ASOF, None)
        self.assertEqual(b.state, "자료 없음")
        self.assertIn("매입매출장", b.reason)


if __name__ == "__main__":
    unittest.main()


class TestPriorYearPrint(unittest.TestCase):
    """2026-11-03 실제: '261103 분개장_2025.xls'(작년 기수)와 '261103 분개장.xls'가 이름 앞 날짜가 같다."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def test_year_in_name_marks_prior_file(self):
        write_journal(self.dir)   # 2026
        old = [("12/31", "00019", "17000", "진행중행사", "결산", 500.0, "", "", "", "결산전표"),
               ("12/31", "00019", "63300", "행사외주비(도)", "결산", "", 500.0, "", "", "결산전표")]
        strings = []
        rows = print_rows(old)
        rows[1][1] = "기 간  : 2025년 01월 01일 ~ 2025년 12월 31일"
        path = os.path.join(self.dir, "261103 분개장_2025.xls")
        X.write_xls(path, X.grid_records(rows, strings), strings)
        os.utime(path, None)   # 작년 파일을 나중에 저장해도
        b = wehago.load_books(self.dir, ASOF, None)
        self.assertEqual(b.state, "ok", b.reason)
        self.assertEqual(b.files["분개장"]["name"], "261031 분개장.xls")
        self.assertEqual(b.files["분개장"]["prior"], ["261103 분개장_2025.xls"])
        self.assertEqual(min(x["date"] for x in b.journal), dt.date(2025, 12, 31))
        self.assertEqual(b.book_date, dt.date(2026, 10, 31))

    def test_closing_slip_type_counts_as_closing(self):
        from ceo_report import convert
        self.assertIn("결산전표", convert.DEFAULT_CONFIG["closing_sorts"])
