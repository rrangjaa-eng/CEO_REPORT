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
        with open(mod("convert_xchk").__file__, encoding="utf-8") as f:
            src = f.read()
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


# ───────────── Task 2: 요청 상태·누계, 거래처 미지급, 매출 대 계약금액 (수동 입력), 미연결 줄, 대조, B5 ─────────────
def relink(x, cost_links=None, revenue_links=None):
    """수동 연결 {줄 열쇠: 프로젝트번호}를 얹어 원가·매출 연결을 다시 만든 입력 사본 (장부는 그대로)."""
    linking = mod("linking")
    y = XInputs()
    y.__dict__.update(x.__dict__)
    cfg = x.cfg
    over = dict(cost_links or {})
    over.update(revenue_links or {})
    y.costs = linking.link_costs(x.books, x.requests, x.projects, over, cfg["link_days"], cfg["direct_prefixes"],
                                 cfg["direct_mark"], cfg["vat_codes"])
    y.revenue = linking.link_revenue(x.books, x.projects, over, cfg["revenue_codes"])
    return y


def with_contract(x, key, text):
    """프로젝트.csv 줄의 계약금액 글자를 바꾼 입력 사본."""
    y = XInputs()
    y.__dict__.update(x.__dict__)
    y.project_rows = [dict(r, 계약금액=text) if r["프로젝트번호"] == key else dict(r) for r in x.project_rows]
    return y


RRN_RUN = re.compile(r"\d{6}\s*[-.]?\s*\d{7}")


class TestXchkFacts(unittest.TestCase):
    def setUp(self):
        self.x = shared_inputs()
        self.table = xchk_table(self.x)

    def test_row_kinds_come_in_the_planned_order(self):
        seen = []
        for r in self.table.rows:
            if not seen or seen[-1] != r["구분"]:
                seen.append(r["구분"])
        self.assertEqual(seen, ["기준", "요청상태", "프로젝트원가", "프로젝트밖요청", "미연결원가", "미연결원가줄", "거래처미지급",
                                "거래처미지급요약", "매출계약", "매출미연결", "매출미연결줄"])

    def test_request_total_per_project(self):
        want = {"26201": ("44264000", "2", ""), "26220": ("166000000", "2", ""),
                "26221": ("", "2", "금액 미확인 1건"), "26203": ("49500000", "1", "")}
        for key, expected in want.items():
            self.assertEqual(cells(one(self, self.table, "프로젝트원가", key, "요청 누계")), expected, key)

    def test_request_total_row_follows_cost_and_budget_of_its_project(self):
        items = [r["항목"] for r in self.table.rows if r["구분"] == "프로젝트원가" and r["대상"] == "26201"]
        self.assertEqual(items, ["WEHAGO 원가", "실행가", "요청 누계"])

    def test_request_total_follows_the_approval_rule(self):
        # 요청 누계 = 코드가 프로젝트 키이고 상태를 읽은 요청 (반려 5107 은 상태를 읽지 못해 빠진다)
        for key in ("26201", "26220", "26221", "26203"):
            mine = [r for r in self.x.requests if r["code"] == key and r["status"] != "status_unknown"]
            known = [r["amount"] for r in mine if r["amount"] is not None]
            row = one(self, self.table, "프로젝트원가", key, "요청 누계")
            self.assertEqual(row["건수"], str(len(mine)))
            if len(known) == len(mine):
                self.assertEqual(row["금액"], str(sum(known)))
            else:
                self.assertEqual(row["금액"], "")

    def test_requests_outside_the_project_list(self):
        row = one(self, self.table, "프로젝트밖요청", "합계")
        self.assertEqual(cells(row), ("2200000", "1", ""))

    def test_request_status_rows_equal_match_requests_summary(self):
        wehago = mod("wehago")
        summary = self.x.match["summary"]
        rows = [r for r in self.table.rows if r["구분"] == "요청상태" and r["항목"] == "인트라넷 요청"]
        self.assertEqual([r["대상"] for r in rows], list(wehago.STATUSES))
        for r in rows:
            s = summary[r["대상"]]
            self.assertEqual(r["건수"], str(s["count"]), r["대상"])
            self.assertEqual(r["금액"], "" if s["unknown"] else str(s["sum"]), r["대상"])

    def test_request_status_numbers(self):
        want = {"계산서 있음": ("51700000", "3", ""), "금액 차이": ("160500000", "1", ""), "계산서 없음": ("264000", "1", ""),
                "이미 지급": ("49500000", "1", ""), "연결 불가": ("", "3", "금액 미확인 1건"), "판단 불가": ("0", "0", "")}
        for status, expected in want.items():
            self.assertEqual(cells(one(self, self.table, "요청상태", status, "인트라넷 요청")), expected, status)

    def test_wehago_invoice_rows_only_for_the_two_statuses_with_an_invoice(self):
        self.assertEqual(cells(one(self, self.table, "요청상태", "계산서 있음", "WEHAGO 계산서")), ("51700000", "3", ""))
        self.assertEqual(cells(one(self, self.table, "요청상태", "금액 차이", "WEHAGO 계산서")), ("165000000", "1", ""))
        self.assertEqual(len(picked(self.table, "요청상태", item="WEHAGO 계산서")), 2)

    def test_vendor_payable_rows_are_the_wehago_vendor_payables_rows(self):
        vp = mod("wehago").vendor_payables(self.x.books, self.x.requests, self.x.match)
        self.assertEqual(len(vp["rows"]), 7)
        names = [r["이름"] for r in self.table.rows if r["구분"] == "거래처미지급" and r["항목"] == "WEHAGO 미지급"]
        self.assertEqual(names, [r["vendor"] for r in vp["rows"]])
        for v in vp["rows"]:
            pay = one(self, self.table, "거래처미지급", None, "WEHAGO 미지급", v["vendor"])
            ask = one(self, self.table, "거래처미지급", None, "인트라넷 요청", v["vendor"])
            self.assertEqual(pay["금액"], "" if v["payable"] is None else str(v["payable"]), v["vendor"])
            self.assertEqual(pay["비고"], v["reason"], v["vendor"])
            self.assertEqual(ask["금액"], "" if v["requested_unknown"] else str(v["requested"]), v["vendor"])

    def test_vendor_payable_examples(self):
        t = self.table
        self.assertEqual(one(self, t, "거래처미지급", None, "WEHAGO 미지급", "㈜가상제작")["금액"], "165000000")
        self.assertEqual(one(self, t, "거래처미지급", None, "인트라넷 요청", "㈜가상제작")["금액"], "160500000")
        flower = one(self, t, "거래처미지급", None, "WEHAGO 미지급", "가상꽃")
        self.assertEqual((flower["금액"], flower["비고"]), ("", "분개장 미지급금 줄 없음"))
        stay = one(self, t, "거래처미지급", None, "인트라넷 요청", "가상숙박")
        self.assertEqual((stay["금액"], stay["건수"], stay["비고"]), ("", "1", "금액 미확인 1건"))
        rent = one(self, t, "거래처미지급", None, "인트라넷 요청", "가상임대")
        self.assertEqual((rent["금액"], rent["건수"]), ("0", "0"))

    def test_vendor_summary(self):
        t = self.table
        self.assertEqual(cells(one(self, t, "거래처미지급요약", None, "비교 거래처")), ("", "9", "기초잔액 미반영"))
        diff = one(self, t, "거래처미지급요약", None, "차이 있는 거래처")
        self.assertEqual((diff["금액"], diff["건수"]), ("13176000", "5"))
        self.assertEqual(cells(one(self, t, "거래처미지급요약", None, "판단 불가 거래처"))[:2], ("", "2"))

    def test_revenue_against_contract_rows(self):
        want = {"26201": "100000000", "26220": "0", "26221": "0", "26203": "75000000"}
        for key, amount in want.items():
            self.assertEqual(one(self, self.table, "매출계약", key, "WEHAGO 매출")["금액"], amount, key)
        self.assertEqual(one(self, self.table, "매출계약", "26201", "WEHAGO 매출")["건수"], "1")
        self.assertEqual(one(self, self.table, "매출계약", "26220", "WEHAGO 매출")["건수"], "0")

    def test_contract_amount_is_the_manual_value_and_blank_means_not_registered(self):
        want = {"26201": ("360000000", ""), "26220": ("", "미등록"), "26221": ("", "미등록"), "26203": ("170000000", "")}
        for key, (amount, note) in want.items():
            row = one(self, self.table, "매출계약", key, "계약금액 (수동 입력)")
            self.assertEqual((row["금액"], row["비고"]), (amount, note), key)

    def test_quote_rows(self):
        want = {"26201": "420000000", "26220": "320000000", "26221": "55000000", "26203": "75000000"}
        for key, amount in want.items():
            self.assertEqual(one(self, self.table, "매출계약", key, "견적금액")["금액"], amount, key)

    def test_unlinked_revenue_total_and_lines(self):
        self.assertEqual(cells(one(self, self.table, "매출미연결", "합계")), ("19000000", "2", ""))
        lines = picked(self.table, "매출미연결줄")
        self.assertEqual([r["대상"] for r in lines], ["2026-10-28 32-2", "2026-10-29 38-1"])
        self.assertEqual([r["금액"] for r in lines], ["20000000", "-1000000"])
        self.assertEqual([r["이름"] for r in lines], ["가상고객X", "가상고객X"])

    def test_checks_except_the_cash_one(self):
        lines = check_lines(self.table)
        for want in ("(도) 원가 = 프로젝트원가 + 미연결원가: 원본 259,500,000 · CSV 259,500,000 → 일치",
                     "매출 = 매출계약 WEHAGO 매출 + 매출미연결: 원본 194,000,000 · CSV 194,000,000 → 일치",
                     "지급요청 건수 = 요청상태 건수 합계: 원본 9 · CSV 9 → 일치",
                     "미연결 원가 줄: 원본 2 · CSV 2 → 일치"):
            self.assertIn(want, lines)

    def test_manual_link_to_a_project_not_in_the_list_adds_a_row_and_keeps_the_check(self):
        y = relink(self.x, cost_links={("2026-10-29", "22", 1): "26888"})
        t = xchk_table(y)
        row = one(self, t, "프로젝트원가", "26888", "WEHAGO 원가")
        self.assertEqual((row["이름"], row["금액"], row["건수"]), ("(프로젝트 목록에 없음)", "800000", "1"))
        self.assertEqual(cells(one(self, t, "미연결원가", "합계")), ("300000", "1", ""))
        self.assertIn("(도) 원가 = 프로젝트원가 + 미연결원가: 원본 259,500,000 · CSV 259,500,000 → 일치", check_lines(t))
        self.assertEqual(len(picked(t, "프로젝트원가", "26888")), 1)   # 실행가·요청 누계 줄은 없다

    def test_manual_revenue_link_to_a_project_not_in_the_list_keeps_the_check(self):
        y = relink(self.x, revenue_links={("2026-10-28", "32", 2): "26888"})
        t = xchk_table(y)
        self.assertEqual(one(self, t, "매출계약", "26888", "WEHAGO 매출")["금액"], "20000000")
        self.assertEqual(cells(one(self, t, "매출미연결", "합계")), ("-1000000", "1", ""))
        self.assertIn("매출 = 매출계약 WEHAGO 매출 + 매출미연결: 원본 194,000,000 · CSV 194,000,000 → 일치", check_lines(t))

    def test_unreadable_request_status_is_listed_in_a_note(self):
        notes = " ".join(self.table.notes)
        self.assertIn("5107", notes)
        self.assertIn("1,100,000", notes)

    def test_load_xchk_gives_the_same_numbers_back(self):
        tmp = new_tmp(self)
        write_xchk(os.path.join(tmp, "입력"), self.table)
        got = mod("convert_xchk").load_xchk(os.path.join(tmp, "입력"))
        self.assertEqual(got["state"], "ok", got["reason"])
        by = dict((p["key"], p) for p in got["projects"])
        self.assertEqual((by["26201"]["requested"], by["26201"]["requested_count"]), (44264000, 2))
        self.assertEqual((by["26221"]["requested"], by["26221"]["requested_count"], by["26221"]["requested_note"]),
                         (None, 2, "금액 미확인 1건"))
        self.assertEqual((got["outside"]["amount"], got["outside"]["count"]), (2200000, 1))
        self.assertEqual([(k, v["amount"], v["count"]) for k, v in got["status"].items()],
                         [("계산서 있음", 51700000, 3), ("금액 차이", 160500000, 1), ("계산서 없음", 264000, 1),
                          ("이미 지급", 49500000, 1), ("연결 불가", None, 3), ("판단 불가", 0, 0)])
        self.assertEqual(got["status"]["금액 차이"]["invoice"], 165000000)
        self.assertEqual(got["status"]["계산서 있음"]["invoice"], 51700000)
        self.assertEqual(got["status"]["연결 불가"]["note"], "금액 미확인 1건")
        self.assertEqual(len(got["vendors"]), 7)
        self.assertEqual(got["vendor_summary"]["compared"], 9)
        self.assertEqual(got["vendor_summary"]["diff_count"], 5)
        self.assertEqual(got["vendor_summary"]["diff_sum"], 13176000)
        self.assertEqual(got["vendor_summary"]["unknown_count"], 2)
        self.assertEqual(got["vendor_summary"]["note"], "기초잔액 미반영")
        rev = dict((r["key"], r) for r in got["revenue"])
        self.assertEqual([rev[k]["wehago"] for k in ("26201", "26220", "26221", "26203")], [100000000, 0, 0, 75000000])
        self.assertEqual([rev[k]["contract"] for k in ("26201", "26220", "26221", "26203")],
                         [360000000, None, None, 170000000])
        self.assertEqual(rev["26220"]["contract_note"], "미등록")
        self.assertEqual((got["revenue_unlinked"]["amount"], got["revenue_unlinked"]["count"]), (19000000, 2))
        self.assertEqual([l["amount"] for l in got["revenue_unlinked_lines"]], [20000000, -1000000])


class TestXchkUnknown(unittest.TestCase):
    """B5: 모르는 값이 하나라도 섞인 칸은 부분 합계가 아니라 빈칸이고, 개수는 비고에만 적는다."""

    def setUp(self):
        self.x = shared_inputs()

    def test_cost_line_without_amount_blanks_the_project_cost_and_counts_the_line(self):
        unknown = _jl(dt.date(2026, 10, 30), 50, "61101", "행사외주비(도)", None, None, "가상미정", "[26201] 금액 미정")
        t = xchk_table(xchk_inputs(self, journal=FAKE_PL_JOURNAL + [unknown]))
        row = one(self, t, "프로젝트원가", "26201", "WEHAGO 원가")
        self.assertEqual(cells(row), ("", "3", "금액 미확인 1줄"))
        self.assertNotEqual(row["금액"], "50000000")
        self.assertIn("(도) 원가 = 프로젝트원가 + 미연결원가: 원본 미확인 · CSV 미확인 → 판단 불가", check_lines(t))
        other = one(self, t, "프로젝트원가", "26220", "WEHAGO 원가")
        self.assertEqual(other["금액"], "158000000")      # 다른 프로젝트는 영향 없음

    def test_unlinked_cost_line_without_amount_blanks_the_unlinked_total(self):
        unknown = _jl(dt.date(2026, 10, 30), 50, "61101", "행사외주비(도)", None, None, "가상미정", "코드 없는 줄")
        t = xchk_table(xchk_inputs(self, journal=FAKE_PL_JOURNAL + [unknown]))
        self.assertEqual(cells(one(self, t, "미연결원가", "합계")), ("", "3", "금액 미확인 1줄"))
        line = [r for r in picked(t, "미연결원가줄") if r["이름"] == "가상미정"][0]
        self.assertEqual((line["금액"], line["건수"]), ("", "1"))

    def test_revenue_line_without_amount_blanks_the_project_revenue(self):
        unknown = _jl(dt.date(2026, 10, 30), 51, "41200", "수입수수료", None, None, "가상고객A", "[26201] 금액 미정")
        t = xchk_table(xchk_inputs(self, journal=FAKE_PL_JOURNAL + [unknown]))
        self.assertEqual(cells(one(self, t, "매출계약", "26201", "WEHAGO 매출")), ("", "2", "금액 미확인 1줄"))
        self.assertIn("매출 = 매출계약 WEHAGO 매출 + 매출미연결: 원본 미확인 · CSV 미확인 → 판단 불가", check_lines(t))

    def test_request_without_amount_blanks_totals_and_keeps_the_count(self):
        t = xchk_table(self.x)
        row = one(self, t, "프로젝트원가", "26221", "요청 누계")
        self.assertEqual((row["금액"], row["건수"]), ("", "2"))
        self.assertNotEqual(row["금액"], "3300000")
        row = one(self, t, "요청상태", "연결 불가", "인트라넷 요청")
        self.assertEqual((row["금액"], row["건수"]), ("", "3"))
        self.assertNotEqual(row["금액"], "4400000")

    def test_contract_text_that_is_not_a_number_is_not_registered(self):
        for text in ("abc", "", "  "):
            t = xchk_table(with_contract(self.x, "26201", text))
            row = one(self, t, "매출계약", "26201", "계약금액 (수동 입력)")
            self.assertEqual((row["금액"], row["비고"]), ("", "미등록"), repr(text))

    def test_contract_is_never_filled_from_revenue(self):
        t = xchk_table(self.x)
        for key in ("26220", "26221"):
            self.assertEqual(one(self, t, "매출계약", key, "계약금액 (수동 입력)")["금액"], "")
        t = xchk_table(with_contract(self.x, "26201", ""))
        self.assertEqual(one(self, t, "매출계약", "26201", "WEHAGO 매출")["금액"], "100000000")
        self.assertEqual(one(self, t, "매출계약", "26201", "계약금액 (수동 입력)")["금액"], "")

    def test_a_project_row_missing_from_project_rows_is_not_registered(self):
        y = XInputs()
        y.__dict__.update(self.x.__dict__)
        y.project_rows = []
        t = xchk_table(y)
        for key in ("26201", "26203"):
            row = one(self, t, "매출계약", key, "계약금액 (수동 입력)")
            self.assertEqual((row["금액"], row["비고"]), ("", "미등록"))

    def test_unknown_request_status_rows_never_become_zero(self):
        t = xchk_table(self.x)
        rows = picked(t, "거래처미지급", item="인트라넷 요청", name="가상숙박")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["금액"], "")

    def test_social_security_number_in_a_memo_is_masked_in_the_table_and_the_file(self):
        t = xchk_table(self.x)
        line = [r for r in picked(t, "미연결원가줄") if r["이름"] == "가상강사"][0]
        self.assertIn("******-*******", line["비고"])
        self.assertIsNone(RRN_RUN.search(line["비고"]))
        tmp = new_tmp(self)
        path = write_xchk(os.path.join(tmp, "입력"), t)
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
        self.assertIsNone(RRN_RUN.search(text))
        self.assertIn("******-*******", text)

    def test_a_social_security_number_shaped_meta_value_is_masked(self):
        y = XInputs()
        y.__dict__.update(self.x.__dict__)
        y.meta = collections.OrderedDict([("분개장", "분개장 900101-1234567.xlsx")])
        t = xchk_table(y)
        self.assertIn("******-*******", t.rows[0]["비고"])


if __name__ == "__main__":
    unittest.main()
