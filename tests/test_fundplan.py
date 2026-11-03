"""SmartA 자금계획서 '지출입금현황' 인쇄 저장 파일 읽기 (D-55). 합성 파일만 쓴다."""
import calendar
import datetime as dt
import os
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report import fundplan  # noqa: E402
import xls_fixture as X  # noqa: E402

# (구분, 분류, 예정일 일, 거래처, 코드, 금액)
ITEMS_NOV = [
    ("지급계획", "미지급금 지급", 6, "가상상사", "000001", 990000),
    ("지급계획", "미지급금 지급", 6, "가상인쇄", "000002", 4114000),
    ("지급계획", "미지급금 지급", 13, "가상음향", "000003", 3410000),
    ("지급계획", "미지급금 지급", 20, "가상조명", "000004", 2587200),
    ("지급계획", "미지급금 지급", 27, "가상무대", "000005", 40750400),
    ("지급계획", "인건비", 5, "직원급여", "000135", 35102733),
    ("입금계획", "외상대금 회수", 9, "가상고객", "000900", 4466441),
    ("입금계획", "외상대금 회수", 30, "가상고객2", "000901", 15922199),
]


def print_rows(year, month, items, split=3):
    """인쇄 모양 행 목록: 7일씩 쪽, 줄 세트 두 개(앞 세트는 '미지급금 지급' 상세 split 줄까지)."""
    last = calendar.monthrange(year, month)[1]
    lines = []   # (글자, 분류 키, 상세 일 또는 None, 금액)
    for sec in ("지급계획", "입금계획"):
        lines.append(("▶" + sec, None, None, 0))
        cats = []
        for it in items:
            if it[0] == sec and it[1] not in cats:
                cats.append(it[1])
        for cat in cats:
            lines.append((cat, (sec, cat), None, 0))
            for it in items:
                if it[0] == sec and it[1] == cat:
                    lines.append(("예정일:%d.%02d.%02d-%s[%s]" % (year, month, it[2], it[3], it[4]), None, it[2], it[5]))
        lines.append(("계", ("계", sec), None, 0))
    cut = 3 + split
    sets = [lines[:cut], lines[cut:]]
    rows = []
    for rowset in sets:
        for start in range(1, last + 1, 7):
            days = list(range(start, min(start + 7, last + 1)))
            rows += [["", "", "", "자 금 계 획 서", "", "", "", ""], [""] * 8,
                     ["", "", "", "계획기간 : %d년 %d월" % (year, month), "", "", "", ""], [""] * 8,
                     ["회사명 :가상회사", "", "", "", "", "", "", "단위(원)"], [""] * 8,
                     ["자금구분"] + ["%d일" % d for d in days] + [""] * (7 - len(days))]
            for text, key, day, amount in lines and rowset:
                row = [text] + [""] * 7
                for k, d in enumerate(days):
                    if key and key[0] == "계":
                        v = sum(it[5] for it in items if it[0] == key[1] and it[2] == d)
                    elif key:
                        v = sum(it[5] for it in items if (it[0], it[1]) == key and it[2] == d)
                    else:
                        v = amount if day == d else 0
                    if v:
                        row[1 + k] = float(v)
                rows.append(row)
            rows += [[""] * 8, [""] * 8]
    return rows


def write_plan(folder, name, rows):
    strings = []
    return X.write_xls(os.path.join(folder, name), X.grid_records(rows, strings), strings)


class TestParse(unittest.TestCase):
    def test_reads_every_detail_line_once_with_its_section_and_category(self):
        res = fundplan.parse(print_rows(2026, 11, ITEMS_NOV))
        self.assertTrue(res["ok"], res["reason"])
        self.assertEqual(res["month"], (2026, 11))
        got = sorted((it["io"], it["cat"], it["date"].day, it["vendor"], it["vendor_code"], it["amount"])
                     for it in res["items"])
        want = sorted(({"지급계획": "out", "입금계획": "in"}[s], c, d, v, code, a) for s, c, d, v, code, a in ITEMS_NOV)
        self.assertEqual(got, want)
        self.assertTrue(all(c[3] for c in res["checks"]))

    def test_category_carries_across_page_and_row_set(self):
        # 앞 줄 세트가 미지급금 상세 중간에서 끊겨도 뒤 세트의 상세는 미지급금(지급)이고, 인건비 쪽으로 새지 않는다
        res = fundplan.parse(print_rows(2026, 11, ITEMS_NOV, split=1))
        self.assertTrue(res["ok"], res["reason"])
        cats = dict((it["vendor"], (it["io"], it["cat"])) for it in res["items"])
        self.assertEqual(cats["가상무대"], ("out", "미지급금 지급"))
        self.assertEqual(cats["직원급여"], ("out", "인건비"))
        self.assertEqual(cats["가상고객2"], ("in", "외상대금 회수"))

    def test_subtotal_mismatch_is_not_used(self):
        rows = print_rows(2026, 11, ITEMS_NOV)
        for row in rows:
            if row[0].startswith("예정일:2026.11.13-가상음향"):
                for i, v in enumerate(row):
                    if isinstance(v, float):
                        row[i] = v + 1
        res = fundplan.parse(rows)
        self.assertFalse(res["ok"])
        self.assertIn("소계", res["reason"])

    def test_missing_period_is_not_used(self):
        rows = [r for r in print_rows(2026, 11, ITEMS_NOV) if not any("계획기간" in str(v) for v in r)]
        self.assertFalse(fundplan.parse(rows)["ok"])


class TestLoad(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def test_months_newest_file_wins_and_rows(self):
        write_plan(self.dir, "261027 자금계획서지출입금현황_2611.xls", print_rows(2026, 11, ITEMS_NOV[:2]))
        write_plan(self.dir, "261103 자금계획서지출입금현황_2611.xls", print_rows(2026, 11, ITEMS_NOV))
        dec = [("지급계획", "미지급금 지급", 4, "가상상사", "000001", 29200000)]
        write_plan(self.dir, "261103 자금계획서지출입금현황_2612.xls", print_rows(2026, 12, dec, split=0))
        with open(os.path.join(self.dir, "다른파일.xls"), "wb") as f:
            f.write(b"x")
        res = fundplan.load(self.dir)
        self.assertEqual([(m, n, d) for m, n, d in res["months"]],
                         [("2026-11", "261103 자금계획서지출입금현황_2611.xls", dt.date(2026, 11, 3)),
                          ("2026-12", "261103 자금계획서지출입금현황_2612.xls", dt.date(2026, 11, 3))])
        self.assertEqual(res["unused"], ["261027 자금계획서지출입금현황_2611.xls"])
        self.assertEqual(len(res["rows"]), len(ITEMS_NOV) + 1)
        first = res["rows"][0]
        self.assertEqual((first["예정일"], first["입출금"], first["분류"], first["거래처"], first["금액"], first["대상월"]),
                         ("2026-11-05", "지급", "인건비", "직원급여", 35102733, "2026-11"))
        self.assertEqual(list(first), fundplan.COLUMNS)

    def test_broken_file_is_named_not_fatal(self):
        with open(os.path.join(self.dir, "261103 자금계획서지출입금현황_2611.xls"), "wb") as f:
            f.write(b"not an excel file" * 40)
        res = fundplan.load(self.dir)
        self.assertEqual(res["rows"], [])
        self.assertIn("읽지 못함", res["notes"][0])

    def test_no_folder(self):
        res = fundplan.load(os.path.join(self.dir, "없음"))
        self.assertEqual((res["rows"], res["months"]), ([], []))


def plan_row(due, io, vendor, amount):
    return {"예정일": due, "입출금": io, "분류": "", "거래처": vendor, "거래처코드": "", "금액": amount, "대상월": due[:7],
            "자료일": "2026-11-03", "파일": "f.xls", "상태": "", "근거": ""}


def books_with(lines, book_date=dt.date(2026, 11, 2)):
    from ceo_report import wehago
    b = wehago.Books()
    b.state, b.book_date = "ok", book_date
    for i, (day, account, debit, credit, vendor) in enumerate(lines):
        code = {"미지급금": "25300", "보통예금": "10300", "외상매출금": "10800"}[account]
        b.journal.append({"date": day, "no": str(i + 1), "account_code": code, "account": account, "debit": debit,
                          "credit": credit, "vendor": vendor, "memo": "", "sort": ""})
    return b


class TestSettle(unittest.TestCase):
    ASOF = dt.date(2026, 11, 3)

    def test_paid_before_due_is_already_paid(self):
        rows = [plan_row("2026-11-13", "지급", "가상음향", 3410000)]
        books = books_with([(dt.date(2026, 10, 30), "미지급금", 3410000, None, "가상음향"),
                            (dt.date(2026, 10, 30), "보통예금", None, 3410000, "")])
        counts = fundplan.settle(rows, books, self.ASOF)
        self.assertEqual(rows[0]["상태"], "이미 지급")
        self.assertIn("2026-10-30", rows[0]["근거"])
        self.assertEqual(counts["이미 지급"], 1)

    def test_other_vendor_payable_does_not_count(self):
        rows = [plan_row("2026-11-13", "지급", "가상음향", 3410000)]
        books = books_with([(dt.date(2026, 10, 30), "미지급금", 3410000, None, "다른회사")])
        fundplan.settle(rows, books, self.ASOF)
        self.assertEqual(rows[0]["상태"], "예정")

    def test_too_early_payment_does_not_count(self):
        rows = [plan_row("2026-12-20", "지급", "가상음향", 3410000)]
        books = books_with([(dt.date(2026, 10, 1), "미지급금", 3410000, None, "가상음향")])
        fundplan.settle(rows, books, self.ASOF)
        self.assertEqual(rows[0]["상태"], "예정")

    def test_overdue_unpaid(self):
        rows = [plan_row("2026-11-02", "지급", "가상상사", 990000)]
        fundplan.settle(rows, books_with([]), self.ASOF)
        self.assertEqual(rows[0]["상태"], "예정일 지남")
        self.assertIn("2026-11-02", rows[0]["근거"])

    def test_received_early_and_one_line_used_once(self):
        rows = [plan_row("2026-11-09", "입금", "가상고객", 4466441), plan_row("2026-11-30", "입금", "가상고객", 4466441)]
        books = books_with([(dt.date(2026, 11, 2), "외상매출금", None, 4466441, "가상고객")])
        counts = fundplan.settle(rows, books, self.ASOF)
        self.assertEqual([r["상태"] for r in rows], ["이미 입금", "예정"])
        self.assertEqual(counts["이미 입금"], 1)

    def test_without_books_nothing_is_removed(self):
        rows = [plan_row("2026-11-02", "지급", "가상상사", 990000), plan_row("2026-11-20", "지급", "가상인쇄", 4114000)]
        fundplan.settle(rows, None, self.ASOF)
        self.assertEqual([r["상태"] for r in rows], ["예정일 지남", "예정"])
        self.assertTrue(all("확인 못함" in r["근거"] for r in rows))


if __name__ == "__main__":
    unittest.main()
