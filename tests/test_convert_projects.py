"""프로젝트.csv·프로젝트집행.csv 만들기 시험 (Phase 2, 계획 02-04).

모든 장부·스냅숏은 시험 때 임시 폴더에 가상 자료로 만든다. 실제 입력/·수집/ 폴더와 실제 WEHAGO 파일은 열지 않는다.
다른 시험 파일에서는 함수와 상수만 가져온다 (TestCase 클래스를 가져오면 시험이 두 번 돈다).
"""
import datetime as dt
import importlib
import os
import random
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
from test_approval import (ASOF, COLLECTED, FAKE_PAYMENTS, FAKE_PROJECTS, NOW, as_dicts,  # noqa: E402
                           write_fake_snapshot)
from test_convert import FAKE_PL_JOURNAL, write_convert_books  # noqa: E402
from test_convert import setUpModule  # noqa: E402,F401  (샘플을 임시 폴더에 새로 쓴다)
from test_wehago import _jl  # noqa: E402


def mod(name):
    return importlib.import_module("ceo_report." + name)


class Inputs(object):
    """한 번의 변환 입력: 장부, 설정, 연결 결과, 요청 대조. 임시 폴더는 읽은 뒤 바로 지운다."""


def make_inputs(journal=FAKE_PL_JOURNAL, extra_requests=None, ledger=None, projects=None, with_snapshot=True):
    """가상 장부 + 가상 스냅숏 -> convert.build_links 까지 (convert.run 이 하는 순서 그대로)."""
    convert, wehago, snapshot = mod("convert"), mod("wehago"), mod("snapshot")
    tmp = tempfile.mkdtemp()
    try:
        wdir = os.path.join(tmp, "위하고")
        extra = {} if ledger is None else {"ledger": ledger}
        write_convert_books(wdir, journal=journal, **extra)
        collect = os.path.join(tmp, "수집")
        if with_snapshot:
            if projects is None:
                write_fake_snapshot(collect, extra=extra_requests)
            else:
                rows = [list(r) for r in FAKE_PAYMENTS] + [list(r) for r in (extra_requests or [])]
                snapshot.write_snapshot(collect, COLLECTED, as_dicts(rows, snapshot.PAYMENT_COLUMNS),
                                        as_dicts(projects, snapshot.PROJECT_COLUMNS))
        input_dir = os.path.join(tmp, "입력")
        os.makedirs(input_dir)
        books = wehago.load_books(wdir, ASOF, None)
        assert books.state == "ok", books.reason
        snap, _ = convert.read_latest_snapshot(collect)
        out = Inputs()
        out.books = books
        out.cfg, _ = convert.read_config(input_dir)
        out.snap = snap
        out.links = convert.build_links(books, out.cfg, snap, input_dir, ASOF, NOW)
        out.projects = out.links["projects"]
        out.revenue = out.links["revenue"]
        out.costs = out.links["costs"]
        out.requests = out.links["requests"]
        out.match = wehago.match_requests(books, out.requests)
        return out
    finally:
        shutil.rmtree(tmp, True)


def prev_projects():
    return mod("convert").read_prev(SAMPLE, "프로젝트.csv")


def prev_execs():
    return mod("convert").read_prev(SAMPLE, "프로젝트집행.csv")


def project_table(inp=None, prev=None):
    inp = inp or make_inputs()
    return mod("convert_projects").build_projects(inp.projects, inp.revenue, prev_projects() if prev is None else prev)


def cell_rows(table):
    """표의 줄을 칸 글자 튜플로 (열 순서대로)."""
    return [tuple(r.get(c, "") for c in table.columns) for r in table.rows]


def check_lines(table):
    """변환결과.txt 와 같은 모양의 대조 줄 (  대조 <label>: 원본 · CSV → 결과)."""
    convert = mod("convert")
    return ["%s: 원본 %s · CSV %s → %s" % (c.label, mod("util").won(c.source), mod("util").won(c.csv), convert.check_result(c))
            for c in table.checks]


def write_and_load(tmp, tables):
    """샘플 입력을 tmp/입력 에 복사하고 표를 써서 data.load 로 읽는다 -> (입력 폴더, Data)."""
    input_dir = os.path.join(tmp, "입력")
    shutil.copytree(SAMPLE, input_dir)
    convert = mod("convert")
    for t in tables:
        convert.write_table(os.path.join(input_dir, t.name), t)
    return input_dir, mod("data").load(input_dir)


def new_tmp(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    return tmp


PROJECT_COLUMNS = ["프로젝트번호", "프로젝트명", "팀", "클라이언트", "상태", "사전견적예산", "예산수정일", "계약금액", "매출반영누계",
                   "행사일", "완료일", "실행가"]

# ───────────── Task 1 (tracer): 스냅숏 프로젝트 + 매출 연결 -> build_projects -> CSV -> data.load -> 보고서 예산 ─────────────
EXPECTED_PROJECTS = [
    ("26201", "가상 컨퍼런스", "1팀", "가상고객A", "진행", "400000000", "2026-09-15", "360000000", "100000000", "2026-11-20", "",
     "300000000"),
    ("26220", "가상 전시", "2팀", "가상고객B", "", "300000000", "", "", "0", "2026-11-12", "", "250000000"),
    ("26221", "가상 워크숍", "1팀", "가상고객C", "", "50000000", "", "", "0", "2026-11-25", "", ""),
    ("26203", "가상 전시부스", "2팀", "가상고객D", "진행", "70000000", "2026-10-29", "170000000", "75000000", "2026-11-12", "",
     "60000000"),
]


def snapshot_projects(**changes):
    """FAKE_PROJECTS 사본. changes: {번호: {열 위치: 값}} (열 위치: 10 사전견적, 12 실행가, 4 행사일)."""
    rows = [list(r) for r in FAKE_PROJECTS]
    for r in rows:
        for pos, value in changes.get(r[0], {}).items():
            r[pos] = value
    return rows


class TestBuildProjects(unittest.TestCase):
    def test_columns_are_the_schema_plus_execution_price(self):
        t = project_table()
        self.assertEqual(t.name, "프로젝트.csv")
        self.assertEqual(t.columns, mod("data").SCHEMA["프로젝트.csv"] + ["실행가"])
        self.assertEqual(t.columns, PROJECT_COLUMNS)
        self.assertTrue(t.written)

    def test_four_rows_in_snapshot_order_with_carried_columns(self):
        self.assertEqual(cell_rows(project_table()), EXPECTED_PROJECTS)

    def test_checks_read_match_for_counts_and_snapshot_money_totals(self):
        lines = check_lines(project_table())
        for want in ("프로젝트 수 (스냅숏 → CSV): 원본 4 · CSV 4 → 일치",
                     "사전견적 합계 (빈칸 제외): 원본 820,000,000 · CSV 820,000,000 → 일치",
                     "사전견적 빈칸: 원본 0 · CSV 0 → 일치",
                     "실행가 합계 (빈칸 제외): 원본 610,000,000 · CSV 610,000,000 → 일치",
                     "실행가 빈칸: 원본 1 · CSV 1 → 일치",
                     "매출 줄 합계 = 매출반영누계 합계 + 미연결 매출: 원본 194,000,000 · CSV 194,000,000 → 일치"):
            self.assertIn(want, lines)
        self.assertEqual(len(lines), 6)

    def test_note_lists_projects_only_in_the_previous_file(self):
        t = project_table()
        self.assertIn("이전 프로젝트.csv에만 있는 프로젝트 6건 (옮기지 않음): P26202, P26204, P26205, P26206, P26207, P26208",
                      t.notes)

    def test_written_file_loads_and_the_report_budget_is_estimate_times_rate(self):
        tmp = new_tmp(self)
        input_dir, d = write_and_load(tmp, [project_table()])
        p = d.projects["26203"]
        self.assertEqual((p["estimate"], p["contract"], p["recognized"]), (70000000, 170000000, 75000000))
        self.assertEqual([it for it in d.issues.items if it[0] == "프로젝트.csv"], [])
        R = mod("calc").compute(d, "weekly", dt.date(2026, 11, 2))
        budgets = dict((P["id"], P["budget"]) for P in R["s3"]["projects"])
        self.assertEqual(budgets["26203"], 49000000)
        self.assertEqual(d.projects["26203"]["contract"], 170000000)

    def test_contract_is_never_filled_from_revenue_when_there_is_no_previous_file(self):
        t = project_table(prev=[])
        rows = dict((r[0], r) for r in cell_rows(t))
        for key in ("26201", "26203"):   # 이 둘은 매출이 있다: 그래도 계약금액·상태·날짜는 빈칸 (D-49)
            self.assertEqual(rows[key][4:5] + rows[key][6:8] + rows[key][10:11], ("", "", "", ""))
        self.assertEqual(rows["26203"][8], "75000000")
        self.assertEqual(t.notes, [])

    def test_non_numeric_estimate_is_blank_with_a_note_never_zero(self):
        inp = make_inputs(projects=snapshot_projects(**{"26221": {10: "abc"}}))
        t = project_table(inp)
        rows = dict((r[0], r) for r in cell_rows(t))
        self.assertEqual(rows["26221"][5], "")
        self.assertIn("26221 사전견적 숫자 아님 → 빈칸", t.notes)
        lines = check_lines(t)
        self.assertIn("사전견적 빈칸: 원본 1 · CSV 1 → 일치", lines)
        self.assertIn("사전견적 합계 (빈칸 제외): 원본 770,000,000 · CSV 770,000,000 → 일치", lines)

    def test_non_numeric_execution_price_is_blank_with_a_note(self):
        inp = make_inputs(projects=snapshot_projects(**{"26201": {12: "협의중"}}))
        t = project_table(inp)
        rows = dict((r[0], r) for r in cell_rows(t))
        self.assertEqual(rows["26201"][11], "")
        self.assertIn("26201 실행가 숫자 아님 → 빈칸", t.notes)

    def test_repeated_snapshot_key_keeps_the_first_row_with_a_note(self):
        extra = ["26201", "가상고객Z", "홍길동", "PO-9", "2026-12-01", "가상 중복", "1국", "9팀", "홍길동", "발행", "1,000", "2,000",
                 "3,000", "", "승인", "승인", "승인", "승인", "999"]
        inp = make_inputs(projects=snapshot_projects() + [extra])
        t = project_table(inp)
        self.assertEqual(len(t.rows), 4)
        self.assertEqual(cell_rows(t)[0][1], "가상 컨퍼런스")
        self.assertIn("프로젝트번호 26201 겹침 → 첫 줄만", t.notes)
        self.assertIn("프로젝트 수 (스냅숏 → CSV): 원본 4 · CSV 4 → 일치", check_lines(t))

    def test_carry_uses_the_digits_and_only_when_exactly_one_previous_row_matches(self):
        prev = prev_projects() + [dict(prev_projects()[0], 프로젝트번호="26201", 상태="완료", 계약금액="1")]
        t = project_table(prev=prev)
        row = dict((r[0], r) for r in cell_rows(t))["26201"]
        self.assertEqual((row[4], row[6], row[7], row[10]), ("", "", "", ""))
        self.assertTrue([n for n in t.notes if "26201" in n and "여러 줄" in n], t.notes)
        other = dict((r[0], r) for r in cell_rows(t))["26203"]
        self.assertEqual(other[7], "170000000")

    def test_previous_values_are_normalised_and_unreadable_ones_are_dropped_with_a_note(self):
        prev = [{"프로젝트번호": "P26201", "상태": " 진행 ", "예산수정일": "2026.09.15", "계약금액": "(5,000)", "완료일": "내일"}]
        t = project_table(prev=prev)
        row = dict((r[0], r) for r in cell_rows(t))["26201"]
        self.assertEqual((row[4], row[6], row[7], row[10]), ("진행", "2026-09-15", "-5000", ""))
        self.assertTrue([n for n in t.notes if "26201" in n and "완료일" in n], t.notes)

    def test_unknown_revenue_amount_makes_the_cell_blank_and_the_check_undecided(self):
        journal = list(FAKE_PL_JOURNAL) + [
            _jl(dt.date(2026, 10, 30), 90, "41200", "수입수수료", None, None, "가상고객A", "[26201] 금액 없음")]
        t = project_table(make_inputs(journal=journal))
        rows = dict((r[0], r) for r in cell_rows(t))
        self.assertEqual(rows["26201"][8], "")
        self.assertEqual(rows["26203"][8], "75000000")
        line = [c for c in t.checks if c.label.startswith("매출 줄 합계")][0]
        self.assertEqual(mod("convert").check_result(line), "판단 불가")

    def test_result_does_not_depend_on_the_journal_or_previous_row_order(self):
        base = project_table()
        journal = list(FAKE_PL_JOURNAL)
        random.Random(7).shuffle(journal)
        prev = list(reversed(prev_projects()))
        again = project_table(make_inputs(journal=journal), prev=prev)
        self.assertEqual(cell_rows(again), cell_rows(base))
        self.assertEqual(check_lines(again), check_lines(base))

    def test_projects_of_keeps_the_unread_text_of_estimate_execution_price_and_event_date(self):
        inp = make_inputs(projects=snapshot_projects(**{"26221": {10: "abc", 12: "협의중"}}))
        p = inp.projects["26221"]
        self.assertEqual((p["estimate"], p["estimate_text"], p["budget"], p["budget_text"], p["event_text"]),
                         (None, "abc", None, "협의중", "2026-11-25"))

    def test_builder_does_not_touch_files(self):
        path = os.path.join(ROOT, "ceo_report", "convert_projects.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("open(", src)
        self.assertNotIn("os.remove", src)
        import ast
        ast.parse(src, feature_version=(3, 8))

    def test_texts_are_masked_by_the_write_path(self):
        projects = snapshot_projects()
        projects[0][5] = "가상 컨퍼런스 900101-1234567"
        t = project_table(make_inputs(projects=projects))
        tmp = new_tmp(self)
        input_dir, d = write_and_load(tmp, [t])
        with open(os.path.join(input_dir, "프로젝트.csv"), encoding="utf-8-sig") as f:
            text = f.read()
        self.assertFalse(re.search(r"\d{6}-?\d{7}", text), text)



# ───────────── Task 2: 프로젝트집행.csv WEHAGO 줄 — 원가 묶음, 부가세, 현금 / 미지급 / 카드, 지급 배분, 대조 ─────────────
_D = dt.date(2026, 10, 30)
CARD_EXTRA = [   # 전표 50: 카드 사용 (공급가 330,000 + 부가세 33,000 = 미지급금 대변 363,000, 거래처 이름에 '카드')
    _jl(_D, 50, "61101", "행사외주비(도)", 330000, None, "가상카드", "[26201] 카드 사용"),
    _jl(_D, 50, "13500", "부가세대급금", 33000, None, "가상카드", "[26201] 카드 사용"),
    _jl(_D, 50, "25300", "미지급금", None, 363000, "가상카드", "[26201] 카드 사용"),
]
CARD_PAID_EXTRA = [   # 전표 51: 카드 대금 결제 (미지급금 차변)
    _jl(dt.date(2026, 10, 31), 51, "25300", "미지급금", 363000, None, "가상카드", "카드대금 결제"),
    _jl(dt.date(2026, 10, 31), 51, "10300", "보통예금", None, 363000, "가상카드", "카드대금 결제"),
]
OPENING_EXTRA = [   # 가상인력: 전기이월 1,000,000 + 10월 지급 6,500,000 (전표 5 = 5,500,000, 전표 6 = 2,200,000)
    _jl(dt.date(2026, 1, 2), 60, "25300", "미지급금", None, 1000000, "가상인력", "전기이월"),
    _jl(dt.date(2026, 1, 2), 60, "37500", "이월이익잉여금", 1000000, None, "가상인력", "전기이월"),
    _jl(dt.date(2026, 10, 31), 61, "25300", "미지급금", 6500000, None, "가상인력", "10월 지급"),
    _jl(dt.date(2026, 10, 31), 61, "10300", "보통예금", None, 6500000, "가상인력", "10월 지급"),
]

EXEC_COLUMNS = ["프로젝트번호", "항목", "거래처", "상태", "공급가액", "부가세", "일자", "확정여부", "근거"]
BASE_ROWS = [   # 날짜 순 (E-6): 전표 37 (09-20), 4 (10-15), 1, 2, 3, 5, 6, 7, 8, 22, 23. 전표 22 의 항목은 따로 확인
    ("26201", "[26201] 9월 인쇄", "가상인쇄", "지급완료", "10000000", "0", "2026-09-20", "확정", "WEHAGO 2026-09-20 전표 37"),
    ("26220", "[26220] 가상 전시 조명", "가상 조명", "요청미지급", "1000000", "100000", "", "추정", "WEHAGO 2026-10-15 전표 4"),
    ("26201", "[26201] 가상 컨퍼런스 음향", "(주)가상음향", "요청미지급", "40000000", "4000000", "", "추정", "WEHAGO 2026-10-20 전표 1"),
    ("26220", "[26220] 가상 전시 제작", "㈜가상제작", "요청미지급", "150000000", "15000000", "", "추정", "WEHAGO 2026-10-21 전표 2"),
    ("26203", "[26203] 가상 전시부스", "주식회사 가상부스", "지급완료", "45000000", "4500000", "2026-10-30", "확정",
     "WEHAGO 2026-10-22 전표 3 · 지급 2026-10-30 전표 20"),
    ("26220", "[26220] 가상 전시 인력", "가상인력", "요청미지급", "5000000", "500000", "", "추정", "WEHAGO 2026-10-23 전표 5"),
    ("26220", "[26220] 가상 전시 인력 추가", "가상인력", "요청미지급", "2000000", "200000", "", "추정", "WEHAGO 2026-10-24 전표 6"),
    ("26221", "[26221] 가상 워크숍 버스 1차", "(주) 가상버스", "요청미지급", "2700000", "270000", "", "추정", "WEHAGO 2026-10-25 전표 7"),
    ("26221", "[26221] 가상 워크숍 버스 2차", "(주) 가상버스", "요청미지급", "2700000", "270000", "", "추정", "WEHAGO 2026-10-26 전표 8"),
    ("", None, "가상강사", "지급완료", "800000", "0", "2026-10-29", "확정", "WEHAGO 2026-10-29 전표 22"),
    ("26999", "[26999] 가상 기타 행사", "가상기타", "지급완료", "300000", "0", "2026-10-29", "확정", "WEHAGO 2026-10-29 전표 23"),
]


def exec_inputs(journal, extra_requests=None, ledger=None, projects=None):
    """가상 장부(+ 가상 요청) -> 연결 결과와 요청 대조까지 (make_inputs)."""
    return make_inputs(journal=journal, extra_requests=extra_requests, ledger=ledger, projects=projects)


def exec_table(inp, requests=False, prev=None, cfg=None):
    """build_execs. requests=False 는 요청 없이(요청 목록과 대조가 비어 있음) 장부 줄만 만든다."""
    req = inp.requests if requests else []
    match = inp.match if requests else {"rows": {}, "summary": {}}
    return mod("convert_projects").build_execs(inp.books, inp.costs, req, match, [] if prev is None else prev,
                                               cfg or inp.cfg, projects=inp.projects)


def wehago_rows(table):
    return [r for r in cell_rows(table) if r[8].startswith("WEHAGO ")]


def by_slip(table, no):
    """근거가 'WEHAGO <일자> 전표 <번호>' 인 줄 하나."""
    found = [r for r in cell_rows(table) if re.match(r"^WEHAGO \S+ 전표 %s( |$)" % no, r[8])]
    assert len(found) == 1, (no, found)
    return found[0]


def journal_with(*extras):
    out = list(FAKE_PL_JOURNAL)
    for e in extras:
        out += e
    return out


class TestBuildExecsBooks(unittest.TestCase):
    def test_columns_are_the_schema(self):
        t = exec_table(exec_inputs(FAKE_PL_JOURNAL))
        self.assertEqual(t.name, "프로젝트집행.csv")
        self.assertEqual(t.columns, mod("data").SCHEMA["프로젝트집행.csv"])
        self.assertEqual(t.columns, EXEC_COLUMNS)

    def test_eleven_wehago_rows_without_requests(self):
        t = exec_table(exec_inputs(FAKE_PL_JOURNAL))
        rows = cell_rows(t)
        self.assertEqual(len(rows), 11)
        self.assertEqual(len(wehago_rows(t)), 11)
        for got, want in zip(rows, BASE_ROWS):
            if want[1] is None:   # 전표 22: 적요에 주민번호 모양이 있어 가려진 글자 (6+7 자리 없음)
                self.assertTrue(got[1].startswith("가상 개인강사"), got)
                self.assertFalse(re.search(r"\d{6}-?\d{7}", got[1]), got)
                got = (got[0], None) + got[2:]
            self.assertEqual(got, want)

    def test_checks_for_cost_vat_line_count_and_payment_allocation(self):
        lines = check_lines(exec_table(exec_inputs(FAKE_PL_JOURNAL)))
        for want in ("원가 줄 합계 ((도) 차변−대변): 원본 259,500,000 · CSV 259,500,000 → 일치",
                     "원가 전표 부가세대급금: 원본 24,840,000 · CSV 24,840,000 → 일치",
                     "원가 줄 수: 원본 11 · CSV 11 → 일치",
                     "미지급 지급 줄 배분: 원본 49,500,000 · CSV 49,500,000 → 일치"):
            self.assertIn(want, lines)

    def test_cost_portions_are_aligned_with_the_rows_and_add_up_to_the_cost_check(self):
        t = exec_table(exec_inputs(FAKE_PL_JOURNAL))
        portions = t.extra["cost_portions"]
        self.assertEqual(len(portions), len(t.rows))
        self.assertEqual(sum(portions), 259500000)
        self.assertEqual(portions[0], 10000000)

    def test_unlinked_cost_rows_are_written_not_dropped(self):
        t = exec_table(exec_inputs(FAKE_PL_JOURNAL))
        self.assertEqual(by_slip(t, 22)[0], "")
        self.assertEqual(by_slip(t, 23)[0], "26999")

    def test_card_use_is_one_total_row_without_vat_until_it_is_paid(self):
        t = exec_table(exec_inputs(journal_with(CARD_EXTRA)))
        row = by_slip(t, 50)
        self.assertEqual(row[:8], ("26201", "[26201] 카드 사용", "가상카드", "카드사용미결제", "363000", "", "", "확정"))
        self.assertEqual(row[8], "WEHAGO 2026-10-30 전표 50")
        portions = dict((r[8], p) for r, p in zip(cell_rows(t), t.extra["cost_portions"]))
        self.assertEqual(portions["WEHAGO 2026-10-30 전표 50"], 330000)
        self.assertEqual(sum(t.extra["cost_portions"]), 259830000)
        lines = check_lines(t)
        self.assertIn("원가 줄 합계 ((도) 차변−대변): 원본 259,830,000 · CSV 259,830,000 → 일치", lines)
        self.assertIn("원가 전표 부가세대급금: 원본 24,873,000 · CSV 24,873,000 → 일치", lines)
        self.assertIn("원가 줄 수: 원본 12 · CSV 12 → 일치", lines)

    def test_card_bill_payment_makes_it_paid_on_the_payment_date(self):
        t = exec_table(exec_inputs(journal_with(CARD_EXTRA, CARD_PAID_EXTRA)))
        row = by_slip(t, 50)
        self.assertEqual(row[:8], ("26201", "[26201] 카드 사용", "가상카드", "카드결제완료", "363000", "", "2026-10-31", "확정"))
        self.assertEqual(row[8], "WEHAGO 2026-10-30 전표 50 · 지급 2026-10-31 전표 51")
        lines = check_lines(t)
        self.assertIn("원가 줄 합계 ((도) 차변−대변): 원본 259,830,000 · CSV 259,830,000 → 일치", lines)
        self.assertIn("원가 전표 부가세대급금: 원본 24,873,000 · CSV 24,873,000 → 일치", lines)
        self.assertIn("미지급 지급 줄 배분: 원본 49,863,000 · CSV 49,863,000 → 일치", lines)

    def test_without_an_opening_line_only_exact_payments_settle(self):
        lines = [_jl(dt.date(2026, 10, 31), 62, "25300", "미지급금", 1000000, None, "가상인력", "일부 지급"),
                 _jl(dt.date(2026, 10, 31), 62, "10300", "보통예금", None, 1000000, "가상인력", "일부 지급")]
        inp = exec_inputs(journal_with(lines))
        t = exec_table(inp)
        paid = [r for r in cell_rows(t) if r[3] == "지급완료" and "전표 3 " in r[8]]
        self.assertEqual(len(paid), 1)
        self.assertEqual(by_slip(t, 5)[3], "요청미지급")
        self.assertEqual(by_slip(t, 6)[3], "요청미지급")
        self.assertIn("미배분 지급 1건 1,000,000", t.notes)
        self.assertIn("미지급 지급 줄 배분: 원본 50,500,000 · CSV 50,500,000 → 일치", check_lines(t))

    def test_an_opening_line_lets_payments_settle_oldest_first(self):
        t = exec_table(exec_inputs(journal_with(OPENING_EXTRA)))
        five = by_slip(t, 5)
        self.assertEqual((five[3], five[6]), ("지급완료", "2026-10-31"))
        self.assertEqual(five[8], "WEHAGO 2026-10-23 전표 5 · 지급 2026-10-31 전표 61")
        self.assertEqual(by_slip(t, 6)[3], "요청미지급")
        self.assertEqual(by_slip(t, 6)[6], "")
        self.assertIn("미배분 지급 0건 0", t.notes)
        self.assertIn("미지급 지급 줄 배분: 원본 56,000,000 · CSV 56,000,000 → 일치", check_lines(t))

    def test_a_partial_payment_leaves_the_row_unpaid_with_the_paid_part_named(self):
        lines = [_jl(dt.date(2026, 1, 2), 60, "25300", "미지급금", None, 1000000, "가상인력", "기초잔액"),
                 _jl(dt.date(2026, 1, 2), 60, "37500", "이월이익잉여금", 1000000, None, "가상인력", "기초잔액"),
                 _jl(dt.date(2026, 10, 31), 61, "25300", "미지급금", 3000000, None, "가상인력", "일부 지급"),
                 _jl(dt.date(2026, 10, 31), 61, "10300", "보통예금", None, 3000000, "가상인력", "일부 지급")]
        t = exec_table(exec_inputs(journal_with(lines)))
        five = by_slip(t, 5)
        self.assertEqual((five[3], five[6]), ("요청미지급", ""))
        self.assertTrue(five[8].endswith(" · 일부 지급 2,000,000"), five[8])
        self.assertIn("미배분 지급 0건 0", t.notes)

    def test_unknown_vat_is_blank_never_zero_and_the_vat_check_cannot_decide(self):
        unknown = [_jl(dt.date(2026, 10, 20), 1, "13500", "부가세대급금", None, None, "(주)가상음향", "[26201] 부가세 금액 없음")]
        t = exec_table(exec_inputs(journal_with(unknown)))
        self.assertEqual(by_slip(t, 1)[5], "")
        self.assertEqual(by_slip(t, 2)[5], "15000000")
        chk = [c for c in t.checks if c.label == "원가 전표 부가세대급금"][0]
        self.assertEqual(mod("convert").check_result(chk), "판단 불가")
        self.assertEqual(mod("convert").check_result([c for c in t.checks if c.label == "원가 줄 수"][0]), "일치")

    def test_card_total_is_blank_when_the_vat_is_unknown(self):
        unknown = [_jl(_D, 50, "13500", "부가세대급금", None, None, "가상카드", "[26201] 부가세 금액 없음")]
        t = exec_table(exec_inputs(journal_with(CARD_EXTRA, unknown)))
        row = by_slip(t, 50)
        self.assertEqual((row[3], row[4], row[5]), ("카드사용미결제", "", ""))

    def test_unknown_cost_amount_is_blank_and_the_cost_check_cannot_decide(self):
        unknown = [_jl(dt.date(2026, 10, 30), 70, "61101", "행사외주비(도)", None, None, "가상기타", "[26201] 금액 없음"),
                   _jl(dt.date(2026, 10, 30), 70, "10300", "보통예금", None, 100, "가상기타", "[26201] 금액 없음")]
        t = exec_table(exec_inputs(journal_with(unknown)))
        row = by_slip(t, 70)
        self.assertEqual((row[3], row[4]), ("지급완료", ""))
        chk = [c for c in t.checks if c.label.startswith("원가 줄 합계")][0]
        self.assertEqual(mod("convert").check_result(chk), "판단 불가")
        self.assertIsNone(t.extra["cost_portions"][cell_rows(t).index(row)])

    def test_a_slip_with_only_a_prepayment_credit_is_unpaid_and_says_it_cannot_tell(self):
        lines = [_jl(dt.date(2026, 10, 30), 71, "61101", "행사외주비(도)", 500000, None, "가상선급", "[26201] 선급 정산"),
                 _jl(dt.date(2026, 10, 30), 71, "25900", "선급금", None, 500000, "가상선급", "[26201] 선급 정산")]
        row = by_slip(exec_table(exec_inputs(journal_with(lines))), 71)
        self.assertEqual((row[3], row[6], row[7]), ("요청미지급", "", "추정"))
        self.assertTrue(row[8].endswith(" · 지급 여부 확인 불가 (현금·미지급 대변 없음)"), row[8])

    def test_a_slip_credited_to_both_cash_and_payable_is_not_called_paid(self):
        lines = [_jl(dt.date(2026, 10, 30), 72, "61101", "행사외주비(도)", 1000000, None, "가상혼합", "[26201] 일부 현금"),
                 _jl(dt.date(2026, 10, 30), 72, "10300", "보통예금", None, 400000, "가상혼합", "[26201] 일부 현금"),
                 _jl(dt.date(2026, 10, 30), 72, "25300", "미지급금", None, 600000, "가상혼합", "[26201] 일부 현금")]
        t = exec_table(exec_inputs(journal_with(lines)))
        row = by_slip(t, 72)
        self.assertEqual((row[3], row[4]), ("요청미지급", "1000000"))
        self.assertTrue(" · 현금·미지급 대변 함께 있음" in row[8], row[8])

    def test_vat_goes_on_the_largest_group_of_the_same_slip_and_vendor(self):
        d = dt.date(2026, 10, 30)
        lines = [_jl(d, 73, "61101", "행사외주비(도)", 100000, None, "가상나눔", "[26201] 작은 건"),
                 _jl(d, 73, "61101", "행사외주비(도)", 300000, None, "가상나눔", "[26220] 큰 건"),
                 _jl(d, 73, "13500", "부가세대급금", 40000, None, "가상나눔", "부가세"),
                 _jl(d, 73, "25300", "미지급금", None, 440000, "가상나눔", "나눔")]
        t = exec_table(exec_inputs(journal_with(lines)))
        rows = [r for r in cell_rows(t) if " 전표 73" in r[8]]
        self.assertEqual(sorted((r[0], r[4], r[5]) for r in rows), [("26201", "100000", "0"), ("26220", "300000", "40000")])

    def test_same_slip_vendor_and_project_make_one_row_with_two_lines(self):
        d = dt.date(2026, 10, 30)
        lines = [_jl(d, 74, "61101", "행사외주비(도)", 100000, None, "가상한줄", "[26201] 하나"),
                 _jl(d, 74, "61101", "행사외주비(도)", 200000, None, "가상한줄", "[26201] 둘"),
                 _jl(d, 74, "10300", "보통예금", None, 300000, "가상한줄", "[26201] 하나")]
        t = exec_table(exec_inputs(journal_with(lines)))
        row = by_slip(t, 74)
        self.assertEqual((row[1], row[4]), ("[26201] 하나", "300000"))
        self.assertIn("원가 줄 수: 원본 13 · CSV 13 → 일치", check_lines(t))

    def test_a_vat_line_of_another_vendor_cannot_be_placed_and_shows_as_a_mismatch(self):
        lines = [_jl(dt.date(2026, 10, 20), 1, "13500", "부가세대급금", 1000, None, "가상다른곳", "부가세")]
        t = exec_table(exec_inputs(journal_with(lines)))
        chk = [c for c in t.checks if c.label == "원가 전표 부가세대급금"][0]
        self.assertEqual(mod("convert").check_result(chk), "불일치")
        self.assertTrue([n for n in t.notes if "부가세대급금" in n and "1,000" in n], t.notes)

    def test_rows_do_not_depend_on_the_journal_order(self):
        base = cell_rows(exec_table(exec_inputs(FAKE_PL_JOURNAL)))
        journal = list(FAKE_PL_JOURNAL)
        random.Random(3).shuffle(journal)
        self.assertEqual(cell_rows(exec_table(exec_inputs(journal))), base)

    def test_codes_come_from_the_settings(self):
        inp = exec_inputs(FAKE_PL_JOURNAL)
        cfg = dict(inp.cfg)
        cfg["cash_codes"] = ("99999",)
        t = exec_table(inp, cfg=cfg)
        self.assertEqual(by_slip(t, 22)[3], "요청미지급")   # 보통예금이 현금 계정이 아니면 지급 여부를 알 수 없다
        self.assertTrue(by_slip(t, 22)[8].endswith("지급 여부 확인 불가 (현금·미지급 대변 없음)"))

    def test_builder_returns_a_table_and_leaves_the_inputs_alone(self):
        inp = exec_inputs(FAKE_PL_JOURNAL)
        before = repr((inp.books.journal, inp.costs["lines"]))
        exec_table(inp)
        self.assertEqual(repr((inp.books.journal, inp.costs["lines"])), before)


if __name__ == "__main__":
    unittest.main()
