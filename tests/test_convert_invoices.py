"""계산서.csv 만들기 시험 (Phase 2, 계획 02-05): 매출 계산서 원천 읽기(wehago.load_sales)와 build_invoices.

모든 장부·스냅숏은 시험 때 임시 폴더에 가상 자료로 만든다. 실제 입력/·수집/ 폴더와 실제 WEHAGO 파일은 열지 않는다.
다른 시험 파일에서는 함수와 상수만 가져온다 (TestCase 클래스를 가져오면 시험이 두 번 돈다).
"""
import csv
import datetime as dt
import importlib
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sample_input import SAMPLE  # noqa: E402
from test_approval import ASOF, NOW, write_fake_snapshot  # noqa: E402
from test_convert import FAKE_PL_JOURNAL, write_convert_books  # noqa: E402
from test_convert import setUpModule  # noqa: E402,F401  (샘플을 임시 폴더에 새로 쓴다)
from test_wehago import (EINVOICE_HEADER, FAKE_EINVOICE, FAKE_LEDGER, LEDGER_HEADER, _L, _jl,  # noqa: E402
                         write_fake_books, write_xlsx)

# 01.1 의 FAKE_LEDGER 에는 매출 줄이 하나 있다. 매출 원천 우선순위(매입매출장의 매출 > 별도 파일)를 시험에서 고르려고
# 기본 시험 장부는 매입 줄만 쓰고, 매출 줄이 있는 경우는 TestSalesSources 가 따로 만든다.
PURCHASE_LEDGER = [r for r in FAKE_LEDGER if r[0] == "매입"]
SALES_NAME = "전자세금계산서(매출)_20261031.xlsx"
_ACC = ("수입수수료미수금", "수입수수료", None, "처리")
SALES_EINVOICE = [
    ["09-15", "C201", "가상고객A", "일반", "[26201] 가상 컨퍼런스 선금", 100000000, 10000000, 110000000] + list(_ACC),
    ["10-27", "C202", "가상고객D", "일반", "가상 전시부스 잔금", 75000000, 7500000, 82500000] + list(_ACC),
    ["10-28", "C203", "가상고객X", "일반", "기타 용역", 20000000, 2000000, 22000000] + list(_ACC),
    ["10-29", "C203", "가상고객X", "수정", "매출 정정", -1000000, -100000, -1100000] + list(_ACC),
]
OPENING_AR = [
    _jl(dt.date(2026, 1, 2), 70, "10800", "수입수수료미수금", 5500000, None, "가상고객D", "전기이월"),
    _jl(dt.date(2026, 1, 2), 70, "37500", "이월이익잉여금", None, 5500000, "가상고객D", "전기이월"),
]
RECEIPT_D = [
    _jl(dt.date(2026, 10, 31), 71, "10300", "보통예금", 50000000, None, "가상고객D", "입금"),
    _jl(dt.date(2026, 10, 31), 71, "10800", "수입수수료미수금", None, 50000000, "가상고객D", "입금"),
]
SALES_COLUMNS = ["프로젝트번호", "거래처", "발행일", "구분", "공급가액", "부가세", "입금예정일", "예정일확정", "입금일", "입금액"]


def mod(name):
    return importlib.import_module("ceo_report." + name)


def new_tmp(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    return tmp


def write_sales(folder, rows, name=SALES_NAME):
    """매출 전자세금계산서 엑셀(머리글은 전자세금계산서(매입)과 같다)을 folder 에 쓴다."""
    os.makedirs(folder, exist_ok=True)
    return write_xlsx(os.path.join(folder, name), [EINVOICE_HEADER] + [list(r) for r in rows])


def write_prev_csv(input_dir, rows):
    """이전 계산서.csv (UTF-8 BOM)를 input_dir 에 쓴다. rows 는 칸 목록들."""
    os.makedirs(input_dir, exist_ok=True)
    with open(os.path.join(input_dir, "계산서.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(SALES_COLUMNS)
        w.writerows(rows)


def invoice_inputs(test, journal=None, sales=SALES_EINVOICE, ledger=None, prev=None, snapshot=True, files=None):
    """(sales, books, revenue, projects, cfg) — convert.run 이 하는 순서 그대로, 임시 폴더만 쓴다.

    sales 가 None 이면 매출 파일을 쓰지 않는다. files = [(이름, 행 목록)] 는 전자세금계산서 모양으로 더 쓸 매출 파일.
    prev 가 있으면 이전 계산서.csv 의 줄 목록(모양은 SALES_COLUMNS)을 입력 폴더에 쓰고 test.prev_rows 에 읽은 값을 남긴다.
    """
    convert, wehago = mod("convert"), mod("wehago")
    tmp = new_tmp(test)
    wdir = os.path.join(tmp, "위하고")
    write_convert_books(wdir, journal=FAKE_PL_JOURNAL if journal is None else journal,
                        ledger=PURCHASE_LEDGER if ledger is None else ledger)
    if sales is not None:
        write_sales(wdir, sales)
    for name, rows in (files or []):
        write_sales(wdir, rows, name)
    collect = os.path.join(tmp, "수집")
    if snapshot:
        write_fake_snapshot(collect)
    input_dir = os.path.join(tmp, "입력")
    os.makedirs(input_dir)
    if prev is not None:
        write_prev_csv(input_dir, prev)
    test.prev_rows = convert.read_prev(input_dir, "계산서.csv")
    books = wehago.load_books(wdir, ASOF, None)
    assert books.state == "ok", books.reason
    snap, _ = convert.read_latest_snapshot(collect)
    cfg, _ = convert.read_config(input_dir)
    links = convert.build_links(books, cfg, snap, input_dir, ASOF, NOW)
    test.wehago_dir = wdir
    return wehago.load_sales(wdir, ASOF, books), books, links["revenue"], links["projects"], cfg


def build(test, prev=None, **kw):
    """invoice_inputs → build_invoices (이전 줄은 prev 로 준 계산서.csv 에서 읽은 값)."""
    sales, books, revenue, projects, cfg = invoice_inputs(test, prev=prev, **kw)
    return mod("convert_invoices").build_invoices(sales, books, revenue, projects, test.prev_rows, cfg)


def cell_rows(table):
    return [tuple(r.get(c, "") for c in table.columns) for r in table.rows]


def check_lines(table):
    """변환결과.txt 와 같은 모양의 대조 줄 (label: 원본 · CSV → 결과)."""
    convert, util = mod("convert"), mod("util")
    return ["%s: 원본 %s · CSV %s → %s" % (c.label, util.won(c.source), util.won(c.csv), convert.check_result(c))
            for c in table.checks]


RECEIPT_LABEL = "수금 (매출채권 대변 · 같은 전표 현금 차변) = 입금액 합계 + 기초 미수 배분 + 미배분"
CREDIT_LABEL = "매출채권 대변 합계 = 현금 입금 + 수정(계산서 감액)"
EXPECTED_ROWS = [
    ("26201", "가상고객A", "2026-09-15", "선수금", "100000000", "10000000", "", "", "2026-10-05", "110000000"),
    ("26203", "가상고객D", "2026-10-27", "발행", "75000000", "7500000", "", "", "", ""),
    ("", "가상고객X", "2026-10-28", "발행", "20000000", "2000000", "", "", "", ""),
    ("", "가상고객X", "2026-10-29", "수정", "-1000000", "-100000", "", "", "", ""),
]
EXPECTED_CHECKS = [
    "계산서 줄 수: 원본 4 · CSV 4 → 일치",
    "공급가액 합계: 원본 194,000,000 · CSV 194,000,000 → 일치",
    "부가세 합계: 원본 19,400,000 · CSV 19,400,000 → 일치",
    RECEIPT_LABEL + ": 원본 110,000,000 · CSV 110,000,000 → 일치",
    CREDIT_LABEL + ": 원본 111,100,000 · CSV 111,100,000 → 일치",
]
CREDIT_LINE = "  수정(계산서 감액) 2026-10-29 가상고객X 1,100,000 (전표 38 · 같은 금액의 수정 계산서 2026-10-29 있음)"


# ───────────── Task 1 (tracer): 전자세금계산서(매출) → load_sales → build_invoices → 계산서.csv → data.load → calc ─────────────
class TestSalesRead(unittest.TestCase):
    def test_sales_kind_of(self):
        w = mod("wehago")
        self.assertEqual(w.SALES_KINDS, ("매입매출장(매출)", "전자세금계산서(매출)"))
        self.assertEqual(w._sales_kind_of("매입매출장(매출)_20261031.xlsx"), "매입매출장(매출)")
        self.assertEqual(w._sales_kind_of("전자세금계산서(매출)_20261031.xlsx"), "전자세금계산서(매출)")
        self.assertIsNone(w._sales_kind_of("매입매출장_20261031.xlsx"))
        self.assertIsNone(w._sales_kind_of("전자세금계산서(매입)_20261031.xlsx"))
        self.assertIsNone(w._sales_kind_of("분개장_20261031.xlsx"))

    def test_kind_of_keeps_sales_files_out_of_the_purchase_choice(self):
        w = mod("wehago")
        self.assertEqual(w._kind_of("매입매출장_20261031.xlsx"), ("매입매출장", True))
        self.assertEqual(w._kind_of("매입매출장(매출)_20261031.xlsx"), ("매입매출장", False))
        self.assertEqual(w._kind_of("전자세금계산서(매출)_20261031.xlsx"), ("전자세금계산서(매입)", False))
        self.assertEqual(w._kind_of("전자세금계산서(매입)_20261031.xlsx"), ("전자세금계산서(매입)", True))

    def test_load_books_choice_is_unchanged_and_lists_the_sales_file(self):
        _, books, _, _, _ = invoice_inputs(self)
        self.assertEqual(books.state, "ok")
        self.assertEqual([books.files[k]["name"] for k in mod("wehago").KINDS],
                         ["분개장_20261031.xlsx", "매입매출장_20261031.xlsx", "전자세금계산서(매입)_20261031.xlsx"])
        self.assertEqual(books.unused, [SALES_NAME])

    def test_load_sales_reads_the_einvoice_sales_file(self):
        sales, books, _, _, _ = invoice_inputs(self)
        self.assertEqual((sales["state"], sales["source"], sales["file"]), ("ok", "전자세금계산서(매출)", SALES_NAME))
        self.assertEqual(sales["file_date"], dt.date(2026, 10, 31))
        self.assertEqual([r["date"] for r in sales["rows"]],
                         [dt.date(2026, 9, 15), dt.date(2026, 10, 27), dt.date(2026, 10, 28), dt.date(2026, 10, 29)])
        self.assertEqual([r["supply"] for r in sales["rows"]], [100000000, 75000000, 20000000, -1000000])
        self.assertEqual([r["vat"] for r in sales["rows"]], [10000000, 7500000, 2000000, -100000])
        self.assertEqual([r["total"] for r in sales["rows"]], [110000000, 82500000, 22000000, -1100000])
        self.assertEqual([r["vendor"] for r in sales["rows"]], ["가상고객A", "가상고객D", "가상고객X", "가상고객X"])
        self.assertEqual(sales["rows"][0]["code"], "26201")
        self.assertIsNone(sales["rows"][1]["code"])
        self.assertEqual([r["type"] for r in sales["rows"]], ["일반", "일반", "일반", "수정"])
        self.assertEqual(sales["rows"][0]["credit_account"], "수입수수료")
        for key in ("no", "vendor_norm", "item"):
            self.assertIn(key, sales["rows"][0])
        self.assertEqual(sales["rows"][0]["vendor_norm"], "가상고객A")

    def test_the_year_comes_from_the_file_name(self):
        tmp = new_tmp(self)
        write_sales(tmp, [["12-30", "C1", "가상고객A", "일반", "x", 1000, 100, 1100] + list(_ACC),
                          ["01-02", "C1", "가상고객A", "일반", "y", 2000, 200, 2200] + list(_ACC)],
                    "전자세금계산서(매출)_20270105.xlsx")
        write_convert_books(os.path.join(tmp, "b"), journal=FAKE_PL_JOURNAL, ledger=PURCHASE_LEDGER)
        books = mod("wehago").load_books(os.path.join(tmp, "b"), ASOF, None)
        sales = mod("wehago").load_sales(tmp, ASOF, books)
        self.assertEqual(sales["state"], "ok")
        self.assertEqual([r["date"] for r in sales["rows"]], [dt.date(2026, 12, 30), dt.date(2027, 1, 2)])

    def test_read_book_gives_credit_account_and_empty_sales_rows(self):
        w = mod("wehago")
        tmp = new_tmp(self)
        write_fake_books(tmp)
        rows, info = w.read_book(os.path.join(tmp, "전자세금계산서(매입)_20261031.xlsx"), "전자세금계산서(매입)",
                                 dt.date(2026, 10, 31), ASOF)
        self.assertEqual([r["credit_account"] for r in rows], ["미지급금", "미지급금"])
        self.assertEqual(info["sales_rows"], [])
        rows, info = w.read_book(os.path.join(tmp, "매입매출장_20261031.xlsx"), "매입매출장", dt.date(2026, 10, 31), ASOF)
        self.assertEqual((info["sales"], info["sales_rows"]), (1, []))

    def test_keep_sales_adds_sales_rows_and_leaves_purchase_rows_alone(self):
        w = mod("wehago")
        tmp = new_tmp(self)
        write_fake_books(tmp)
        path = os.path.join(tmp, "매입매출장_20261031.xlsx")
        plain_rows, plain_info = w.read_book(path, "매입매출장", dt.date(2026, 10, 31), ASOF)
        rows, info = w.read_book(path, "매입매출장", dt.date(2026, 10, 31), ASOF, keep_sales=True)
        self.assertEqual(rows, plain_rows)
        self.assertEqual(len(info["sales_rows"]), 1)
        sale = info["sales_rows"][0]
        self.assertEqual((sale["vendor"], sale["supply"], sale["vat"], sale["type"]), ("가상고객A", 100000000, 10000000, "과세"))
        self.assertEqual(sale["date"], dt.date(2026, 10, 27))
        for key in ("sales", "other", "rows", "skipped", "undated", "after_ref", "last_date"):
            self.assertEqual(info[key], plain_info[key])


class TestBuildInvoices(unittest.TestCase):
    def test_four_rows_in_issue_order_with_projects_and_the_receipt(self):
        t = build(self)
        self.assertEqual((t.name, t.written, t.reason), ("계산서.csv", True, ""))
        self.assertEqual(t.columns, mod("data").SCHEMA["계산서.csv"])
        self.assertEqual(cell_rows(t), EXPECTED_ROWS)

    def test_checks_read_like_the_conversion_result(self):
        self.assertEqual(check_lines(build(self)), EXPECTED_CHECKS)

    def test_notes_carry_the_facts_and_list_every_unlinked_invoice(self):
        notes = build(self).notes
        for text in ("프로젝트 연결: 코드 1건 100,000,000 · 분개장 매출 줄 1건 75,000,000 · 자동 0건 0 · 미연결 2건 19,000,000",
                     "참고 매출 계산서 공급가액 194,000,000 · 분개장 매출 194,000,000",
                     "참고 매출채권 잔액: 분개장 103,400,000 · 계산서 기준 103,400,000 (차이 0)",
                     "미배분 수금 0건 0", CREDIT_LINE):
            self.assertIn(text, notes)
        unlinked = [n for n in notes if n.startswith("  미연결 계산서")]
        self.assertEqual(len(unlinked), 2)
        self.assertIn("2026-10-28", unlinked[0])
        self.assertIn("가상고객X", unlinked[0])
        self.assertIn("2026-10-29", unlinked[1])

    def test_unknown_supply_is_blank_not_zero(self):
        rows = [list(r) for r in SALES_EINVOICE]
        rows[2][5] = None   # 가상고객X 10-28 공급가액 빈칸
        t = build(self, sales=rows)
        x = [r for r in cell_rows(t) if r[2] == "2026-10-28"][0]
        self.assertEqual(x[4], "")
        self.assertEqual(x[5], "2000000")
        lines = check_lines(t)
        self.assertEqual(lines[1], "공급가액 합계: 원본 미확인 · CSV 미확인 → 판단 불가")
        self.assertIn("계산서 줄 수: 원본 4 · CSV 4 → 일치", lines)
        self.assertNotIn("0", [c for r in cell_rows(t) for c in r])

    def test_unknown_vat_is_blank_and_no_receipt_is_matched(self):
        rows = [list(r) for r in SALES_EINVOICE]
        rows[0][6] = None   # 가상고객A 09-15 부가세 빈칸 (합계 칸은 있어도 쓰지 않는다)
        t = build(self, sales=rows)
        a = cell_rows(t)[0]
        self.assertEqual((a[4], a[5], a[8], a[9]), ("100000000", "", "", ""))
        lines = check_lines(t)
        self.assertEqual(lines[2], "부가세 합계: 원본 미확인 · CSV 미확인 → 판단 불가")
        self.assertIn(RECEIPT_LABEL + ": 원본 110,000,000 · CSV 110,000,000 → 일치", lines)
        self.assertIn("미배분 수금 1건 110,000,000", t.notes)
        self.assertIn("  미배분 수금 2026-10-05 가상고객A 110,000,000 (전표 33)", t.notes)

    def test_written_csv_loads_without_input_issues_and_the_receivable_events_add_up(self):
        t = build(self)
        tmp = new_tmp(self)
        input_dir = os.path.join(tmp, "입력")
        shutil.copytree(SAMPLE, input_dir)
        path = os.path.join(input_dir, "프로젝트.csv")
        with open(path, encoding="utf-8-sig", newline="") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            f.write(re.sub(r"(?m)^P(262\d\d)", r"\1", text))
        mod("convert").write_table(os.path.join(input_dir, "계산서.csv"), t)
        d = mod("data").load(input_dir)
        self.assertEqual([it for it in d.issues.items if it[0] == "계산서.csv"], [])
        R = mod("calc").compute(d, "weekly", ASOF)
        events = [e for e in R["events"] if e["source"] == "계산서"]
        self.assertEqual(sorted((e["desc"], e["amount"]) for e in events),
                         [("가상고객D", 82500000), ("가상고객X", 20900000)])
        self.assertEqual(sum(e["amount"] for e in events), 103400000)


if __name__ == "__main__":
    unittest.main()
