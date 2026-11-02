"""위하고대조.csv 만들기·읽기 시험 (Phase 2, 계획 02-06, D-44 D-48 D-49).

모든 장부·스냅숏·은행 줄은 시험 때 임시 폴더나 코드 안의 가상 자료로 만든다. 실제 입력/·수집/ 폴더와 실제 WEHAGO 파일은 열지 않는다.
다른 시험 파일에서는 함수와 상수만 가져온다 (TestCase 클래스를 가져오면 시험이 두 번 돈다).
"""
import collections
import datetime as dt
import importlib
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_convert import FAKE_PL_JOURNAL  # noqa: E402
from test_convert import setUpModule  # noqa: E402,F401  (샘플을 임시 폴더에 새로 쓴다)
from test_convert_projects import check_lines, make_inputs, new_tmp, project_table  # noqa: E402
from test_wehago import _jl  # noqa: E402


def mod(name):
    return importlib.import_module("ceo_report." + name)


# ───────────── 은행·현금 가상 자료 (PATTERNS 5: OPENING_CASH, BANK_BALANCES, BANK_TX) ─────────────
OPENING_CASH = [
    _jl(dt.date(2026, 1, 2), 80, "10300", "보통예금", 300000000, None, "가상은행", "전기이월"),
    _jl(dt.date(2026, 1, 2), 80, "37500", "이월이익잉여금", None, 300000000, "가상은행", "전기이월"),
]
BANK_BALANCES = [
    {"기준일": "2026-10-31", "계좌명": "운영계좌", "은행": "가상은행", "잔액": "200,000,000", "사용제한금액": "", "제한사유": ""},
    {"기준일": "2026-10-31", "계좌명": "프로젝트계좌", "은행": "가상은행", "잔액": "145,000,000", "사용제한금액": "", "제한사유": ""},
]
BANK_TX = [
    {"일자": "2026-10-05", "계좌명": "운영계좌", "입출금": "입금", "금액": "110,000,000", "분류": "", "프로젝트번호": "",
     "거래처": "가상고객A", "적요": "선금 입금"},
    {"일자": "2026-10-30", "계좌명": "운영계좌", "입출금": "출금", "금액": "53,000,000", "분류": "", "프로젝트번호": "",
     "거래처": "가상부스", "적요": "부스 지급"},
]

META = collections.OrderedDict([
    ("장부 기준일", "2026-10-31"),
    ("분개장", "분개장_20261031.xlsx"),
    ("매입매출장", "매입매출장_20261031.xlsx"),
    ("전자세금계산서(매입)", "전자세금계산서(매입)_20261031.xlsx"),
    ("인트라넷 스냅숏", "20261102_000000 (수집 2026-11-02 00:00:00)"),
    ("변환 시각", "2026-11-02 00:00:00"),
])
NO_BANK = {"balances": None, "transactions": None}


class XInputs(object):
    """build_xchk 에 넣는 입력 한 벌 (모두 가상 자료)."""


def xchk_inputs(test, journal=None, bank=None, extra_requests=None):
    """가상 장부(journal, 기본 FAKE_PL_JOURNAL) + 가상 스냅숏 -> build_xchk 입력. 장부·스냅숏 폴더는 임시 폴더에만 쓴다."""
    inp = make_inputs(journal=FAKE_PL_JOURNAL if journal is None else journal, extra_requests=extra_requests)
    x = XInputs()
    x.books, x.cfg, x.costs, x.revenue = inp.books, inp.cfg, inp.costs, inp.revenue
    x.projects, x.requests, x.match = inp.projects, inp.requests, inp.match
    x.project_rows = project_table(inp).rows
    x.meta = collections.OrderedDict(META)
    x.bank = dict(NO_BANK) if bank is None else bank
    return x


_SHARED = []


def shared_inputs():
    """읽기만 하는 시험이 함께 쓰는 입력 한 벌 (장부·스냅숏 만들기는 느리다). 쓰는 쪽은 바꾸지 않는다."""
    if not _SHARED:
        _SHARED.append(xchk_inputs(None))
    return _SHARED[0]


def xchk_table(x):
    return mod("convert_xchk").build_xchk(x.books, x.costs, x.revenue, x.projects, x.requests, x.match, x.project_rows,
                                          x.meta, x.cfg, x.bank)


def write_xchk(input_dir, table):
    """표를 input_dir/위하고대조.csv 로 쓴다 (convert.write_table, 입력 폴더가 없으면 만든다)."""
    os.makedirs(input_dir, exist_ok=True)
    path = os.path.join(input_dir, mod("convert_xchk").XCHK_FILE)
    mod("convert").write_table(path, table)
    return path


def picked(table, kind, target=None, item=None, name=None):
    """조건에 맞는 줄 목록."""
    return [r for r in table.rows if r["구분"] == kind and (target is None or r["대상"] == target)
            and (item is None or r["항목"] == item) and (name is None or r["이름"] == name)]


def one(test, table, kind, target=None, item=None, name=None):
    found = picked(table, kind, target, item, name)
    test.assertEqual(len(found), 1, "%s/%s/%s/%s: %d줄" % (kind, target, item, name, len(found)))
    return found[0]


def cells(row):
    """(금액, 건수, 비고)"""
    return row["금액"], row["건수"], row["비고"]


# ───────────── Task 1 (tracer): 연결 결과 -> build_xchk 기준 / 프로젝트원가 / 미연결원가 -> write_table -> load_xchk ─────────────
class TestXchkTracer(unittest.TestCase):
    def setUp(self):
        self.x = shared_inputs()
        self.table = xchk_table(self.x)

    def test_constants(self):
        m = mod("convert_xchk")
        self.assertEqual(m.XCHK_FILE, "위하고대조.csv")
        self.assertEqual(m.XCHK_COLUMNS, ["구분", "대상", "이름", "항목", "금액", "건수", "비고"])
        self.assertIn(m.XCHK_FILE, mod("convert").GENERATED)

    def test_table_has_the_file_name_columns_and_full_rows(self):
        t = self.table
        self.assertEqual(t.name, "위하고대조.csv")
        self.assertEqual(t.columns, ["구분", "대상", "이름", "항목", "금액", "건수", "비고"])
        self.assertTrue(t.written)
        for r in t.rows:
            self.assertEqual(sorted(r), sorted(t.columns))

    def test_basis_rows_come_first_in_meta_order(self):
        rows = self.table.rows[:len(META)]
        self.assertEqual([(r["구분"], r["항목"], r["비고"]) for r in rows],
                         [("기준", k, v) for k, v in META.items()])
        for r in rows:
            self.assertEqual((r["대상"], r["이름"], r["금액"], r["건수"]), ("", "", "", ""))

    def test_project_cost_rows_per_project_in_snapshot_order(self):
        order = [r["대상"] for r in self.table.rows if r["구분"] == "프로젝트원가" and r["항목"] == "WEHAGO 원가"]
        self.assertEqual(order, ["26201", "26220", "26221", "26203"])
        names = [r["이름"] for r in picked(self.table, "프로젝트원가", item="WEHAGO 원가")]
        self.assertEqual(names, ["가상 컨퍼런스", "가상 전시", "가상 워크숍", "가상 전시부스"])

    def test_wehago_cost_amounts_and_line_counts(self):
        want = {"26201": ("50000000", "2"), "26220": ("158000000", "4"), "26221": ("5400000", "2"),
                "26203": ("45000000", "1")}
        for key, (amount, count) in want.items():
            row = one(self, self.table, "프로젝트원가", key, "WEHAGO 원가")
            self.assertEqual((row["금액"], row["건수"], row["비고"]), (amount, count, ""), key)

    def test_execution_price_rows_and_the_blank_one(self):
        want = {"26201": "300000000", "26220": "250000000", "26221": "", "26203": "60000000"}
        for key, amount in want.items():
            row = one(self, self.table, "프로젝트원가", key, "실행가")
            self.assertEqual(row["금액"], amount, key)
            self.assertEqual(row["건수"], "")
        self.assertEqual(one(self, self.table, "프로젝트원가", "26221", "실행가")["비고"], "실행가 빈칸")
        self.assertEqual(one(self, self.table, "프로젝트원가", "26201", "실행가")["비고"], "")

    def test_unlinked_cost_total(self):
        row = one(self, self.table, "미연결원가", "합계")
        self.assertEqual(cells(row), ("1100000", "2", ""))
        self.assertEqual(row["항목"], "WEHAGO 원가")

    def test_one_unlinked_line_row_for_slip_22_and_slip_23(self):
        lines = picked(self.table, "미연결원가줄")
        self.assertEqual([r["대상"] for r in lines], ["2026-10-29 22-1", "2026-10-29 23-1"])
        by = dict((r["대상"], r) for r in lines)
        a, b = by["2026-10-29 22-1"], by["2026-10-29 23-1"]
        self.assertEqual((a["이름"], a["금액"], a["건수"]), ("가상강사", "800000", "1"))
        self.assertEqual((b["이름"], b["금액"], b["건수"]), ("가상기타", "300000", "1"))
        self.assertTrue(a["항목"].startswith("미연결"), a["항목"])
        self.assertIn("코드 26999", b["항목"])
        self.assertIn("[26999]", b["비고"])

    def test_cost_check_matches_the_books(self):
        lines = check_lines(self.table)
        self.assertIn("(도) 원가 = 프로젝트원가 + 미연결원가: 원본 259,500,000 · CSV 259,500,000 → 일치", lines)
        self.assertIn("미연결 원가 줄: 원본 2 · CSV 2 → 일치", lines)

    def test_cell_amounts_are_plain_integers_or_blank(self):
        for r in self.table.rows:
            self.assertTrue(re.match(r"^-?\d*$", r["금액"]), r)
            self.assertTrue(re.match(r"^\d*$", r["건수"]), r)

    def test_inputs_are_not_changed(self):
        before = (repr(self.x.costs["lines"]), repr(self.x.revenue["lines"]), repr(self.x.match["summary"]),
                  repr(self.x.project_rows), repr(self.x.meta))
        xchk_table(self.x)
        after = (repr(self.x.costs["lines"]), repr(self.x.revenue["lines"]), repr(self.x.match["summary"]),
                 repr(self.x.project_rows), repr(self.x.meta))
        self.assertEqual(before, after)

    def test_builder_does_not_touch_files(self):
        src = open(mod("convert_xchk").__file__, encoding="utf-8").read()
        self.assertNotIn("open(", src)
        self.assertNotIn("'w'", src)
        self.assertNotIn('"w"', src)

    def test_round_trip_through_the_file_gives_the_same_numbers(self):
        tmp = new_tmp(self)
        write_xchk(os.path.join(tmp, "입력"), self.table)
        got = mod("convert_xchk").load_xchk(os.path.join(tmp, "입력"))
        self.assertEqual(got["state"], "ok", got["reason"])
        self.assertEqual(got["meta"], dict(META))
        by = dict((p["key"], p) for p in got["projects"])
        self.assertEqual([p["key"] for p in got["projects"]], ["26201", "26220", "26221", "26203"])
        self.assertEqual((by["26201"]["cost"], by["26201"]["cost_lines"]), (50000000, 2))
        self.assertEqual((by["26220"]["cost"], by["26220"]["cost_lines"]), (158000000, 4))
        self.assertEqual((by["26221"]["cost"], by["26221"]["cost_lines"]), (5400000, 2))
        self.assertEqual((by["26203"]["cost"], by["26203"]["cost_lines"]), (45000000, 1))
        self.assertEqual([by[k]["budget"] for k in ("26201", "26220", "26221", "26203")],
                         [300000000, 250000000, None, 60000000])
        self.assertEqual(by["26221"]["budget_note"], "실행가 빈칸")
        self.assertEqual((got["unlinked"]["amount"], got["unlinked"]["count"]), (1100000, 2))
        self.assertEqual([l["key"] for l in got["unlinked_lines"]], ["2026-10-29 22-1", "2026-10-29 23-1"])
        self.assertEqual([l["amount"] for l in got["unlinked_lines"]], [800000, 300000])

    def test_a_file_with_another_header_is_unreadable_not_empty(self):
        tmp = new_tmp(self)
        os.makedirs(os.path.join(tmp, "입력"))
        with open(os.path.join(tmp, "입력", "위하고대조.csv"), "w", encoding="utf-8-sig", newline="") as f:
            f.write("구분,대상,이름,항목,금액\r\n기준,,,장부 기준일,\r\n")
        got = mod("convert_xchk").load_xchk(os.path.join(tmp, "입력"))
        self.assertEqual(got["state"], "읽을 수 없음")
        self.assertEqual(got["reason"], "위하고대조.csv 머리글 다름")


if __name__ == "__main__":
    unittest.main()
