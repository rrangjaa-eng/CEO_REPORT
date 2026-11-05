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

    def test_bank_line_for_another_vendor_does_not_count(self):
        rows = [plan_row("2026-11-06", "지급", "가상음향", 990000)]
        books = books_with([(dt.date(2026, 10, 23), "미지급금", 990000, None, "다른회사"),
                            (dt.date(2026, 10, 23), "보통예금", None, 990000, "다른회사")])
        fundplan.settle(rows, books, self.ASOF)
        self.assertEqual(rows[0]["상태"], "예정")

    def test_too_early_payment_does_not_count(self):
        rows = [plan_row("2026-12-20", "지급", "가상음향", 3410000)]
        books = books_with([(dt.date(2026, 10, 1), "미지급금", 3410000, None, "가상음향")])
        fundplan.settle(rows, books, self.ASOF)
        self.assertEqual(rows[0]["상태"], "예정")

    def test_last_month_recurring_payment_is_not_this_month(self):
        # 매달 5일 같은 거래처·같은 금액: 10/2 전표는 11/5 줄의 미리 지급이 아니다
        rows = [plan_row("2026-11-05", "지급", "복지업체", 120000)]
        books = books_with([(dt.date(2026, 10, 2), "미지급금", 120000, None, "복지업체")])
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

    def test_due_after_book_date_is_not_called_overdue(self):
        # 분개장이 11/2 까지만 있으면 11/3 예정은 '안 나감'으로 단정하지 않는다 (사용자 2026-11-05 급여)
        rows = [plan_row("2026-11-03", "지급", "직원급여", 35102733)]
        fundplan.settle(rows, books_with([]), dt.date(2026, 11, 3))
        self.assertEqual(rows[0]["상태"], "예정")
        self.assertIn("장부 기준일 2026-11-02 뒤", rows[0]["근거"])


def plan_ev(due, state, basis, amount=35102733, io="지급"):
    return {"date": dt.date(*map(int, due.split("-"))), "io": io, "cat": "인건비", "vendor": "직원급여", "vendor_code": "",
            "amount": amount, "ym": due[:7], "stamp": dt.date(2026, 11, 4), "state": state, "basis": basis, "file": ""}


class TestApplyBookGap(unittest.TestCase):
    ASOF = dt.date(2026, 11, 5)

    def test_paid_day_inside_bank_balance_is_not_listed_again(self):
        plan = [plan_ev("2026-11-05", "예정일 지남", "분개장에 출금 없음 (장부 기준일 2026-11-04)")]
        new, info = fundplan.apply([], plan, self.ASOF, 7, cash_date=dt.date(2026, 11, 5), txns=[])
        self.assertEqual(new, [])
        self.assertEqual(info["done"][0]["plan"]["state"], "통장 잔액에 반영")
        self.assertEqual(info["moved"], [])

    def test_same_amount_in_bank_lines_is_named(self):
        plan = [plan_ev("2026-11-05", "예정", "장부 기준일 2026-11-04 뒤 예정일: 분개장으로 출금 확인 못함", amount=990000)]
        txns = [{"date": dt.date(2026, 11, 5), "io": "출금", "amount": 990000}]
        _, info = fundplan.apply([], plan, self.ASOF, 7, cash_date=dt.date(2026, 11, 5), txns=txns)
        self.assertIn("통장 2026-11-05 출금 같은 금액", info["done"][0]["plan"]["basis"])

    def test_bank_balance_older_than_due_still_moves_to_friday(self):
        plan = [plan_ev("2026-11-05", "예정", "장부 기준일 2026-11-04 뒤 예정일: 분개장으로 출금 확인 못함")]
        new, info = fundplan.apply([], plan, self.ASOF, 7, cash_date=dt.date(2026, 11, 4), txns=[])
        self.assertEqual(new[0]["date"], dt.date(2026, 11, 6))
        self.assertIn("이미 나갔으면 빼도 됨", new[0]["basis"])

    def test_books_covering_due_keep_overdue(self):
        plan = [plan_ev("2026-11-03", "예정일 지남", "분개장에 출금 없음 (장부 기준일 2026-11-04)")]
        new, info = fundplan.apply([], plan, self.ASOF, 7, cash_date=dt.date(2026, 11, 5), txns=[])
        self.assertEqual(len(info["moved"]), 1)
        self.assertEqual(info["done"], [])


class TestWeekListGap(unittest.TestCase):
    def test_gap_payment_is_not_on_payday_list(self):
        from ceo_report.render import week_outflows
        ev = lambda day, amt, **k: dict({"date": day, "io": "out", "amount": amt, "firm": True, "cat": "자금계획서 인건비",
                                         "desc": "직원급여", "project": "", "source": "자금계획서"}, **k)
        R = {"asof": dt.date(2026, 11, 5), "payday": dt.date(2026, 11, 6),
             "events": [ev(dt.date(2026, 11, 6), 500, gap=dt.date(2026, 11, 5)), ev(dt.date(2026, 11, 6), 70)]}
        W = week_outflows(R)
        self.assertEqual(W["pay"]["total"], 70)
        self.assertEqual(W["gap"]["total"], 500)


class TestFillProjects(unittest.TestCase):
    def ex(self, vendor, project, supply, vat, basis="WEHAGO 2026-10-02 전표 1", state="요청미지급"):
        return {"vendor": vendor, "project": project, "supply": supply, "vat": vat, "basis": basis, "state": state}

    def ev(self, vendor, amount):
        return {"io": "out", "source": "자금계획서", "desc": vendor, "amount": amount, "project": "", "basis": "자금계획서"}

    def test_same_amount_then_single_project_then_many(self):
        execs = [self.ex("가상음향", "26001", 1000, 100), self.ex("가상음향", "26002", 2000, 200),
                 self.ex("가상조명", "26003", 500, 50), self.ex("가상조명", "26003", 700, 70),
                 self.ex("가상무대", "26004", 100, 10), self.ex("가상무대", "26005", 300, 30),
                 self.ex("가상인쇄", "26006", 100, 10, basis="지급요청 1")]
        evs = [self.ev("가상음향", 2200), self.ev("가상조명", 1320), self.ev("가상무대", 440), self.ev("직원급여", 9),
               self.ev("가상인쇄", 110)]
        self.assertEqual(fundplan.fill_projects(evs, execs), 2)
        self.assertEqual([e["project"] for e in evs], ["26002", "26003", "", "", ""])
        self.assertIn("여러 프로젝트", evs[2]["basis"])


if __name__ == "__main__":
    unittest.main()
