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
from test_wehago import FAKE_LEDGER, _L, _jl, post  # noqa: E402
from test_convert import PL_EXTRA  # noqa: E402


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


# 02-REVIEW WR-03: 샘플 이전 프로젝트.csv 에만 있는 프로젝트는 스냅숏 줄 뒤에 번호 순으로 그대로 옮긴다 (예전: 버림)
CARRIED_PROJECTS = [
    ("P26202", "B사 고객 세미나", "기획2팀", "B사", "완료", "80000000", "2026-08-20", "100000000", "100000000", "2026-09-18",
     "2026-09-19", ""),
    ("P26204", "D사 신제품 런칭", "기획1팀", "D사", "진행", "", "", "50000000", "0", "2026-12-03", "", ""),
    ("P26205", "E사 파트너 포럼", "기획1팀", "E사", "완료", "45000000", "2026-08-01", "60000000", "60000000", "2026-09-19",
     "2026-09-20", ""),
    ("P26206", "F사 임직원 워크숍", "기획2팀", "F사", "완료", "40000000", "2026-09-01", "50000000", "50000000", "2026-10-15",
     "2026-10-16", ""),
    ("P26207", "G사 VIP 초청행사", "기획2팀", "G사", "진행", "30000000", "2026-10-10", "38000000", "0", "2026-11-28", "", ""),
    ("P26208", "H사 사내 행사", "기획1팀", "H사", "준비", "20000000", "2026-10-20", "", "0", "2027-01-20", "", ""),
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
        # 02-REVIEW WR-03: 스냅숏 4줄 뒤에 이전 파일에만 있는 6줄 (예전: 4줄만)
        self.assertEqual(cell_rows(project_table()), EXPECTED_PROJECTS + CARRIED_PROJECTS)

    def test_checks_read_match_for_counts_and_snapshot_money_totals(self):
        lines = check_lines(project_table())
        for want in ("프로젝트 수 (스냅숏 → CSV): 원본 4 · CSV 4 → 일치",
                     "사전견적 합계 (빈칸 제외): 원본 820,000,000 · CSV 820,000,000 → 일치",
                     "사전견적 빈칸: 원본 0 · CSV 0 → 일치",
                     "실행가 합계 (빈칸 제외): 원본 610,000,000 · CSV 610,000,000 → 일치",
                     "실행가 빈칸: 원본 1 · CSV 1 → 일치",
                     "매출 줄 합계 = 매출반영누계 합계 + 미연결 매출: 원본 194,000,000 · CSV 194,000,000 → 일치",
                     "이전 프로젝트.csv에만 있는 프로젝트 → 옮긴 줄: 원본 6 · CSV 6 → 일치"):   # WR-03 새 대조
            self.assertIn(want, lines)
        self.assertEqual(len(lines), 7)

    def test_note_lists_projects_only_in_the_previous_file(self):
        t = project_table()
        # 02-REVIEW WR-03: 옮긴다 (예전 알림: '... 6건 (옮기지 않음): ...')
        self.assertIn("이전 프로젝트.csv에만 있는 프로젝트 6건 → 옮김 (스냅숏에 없음, 이전 줄 그대로): "
                      "P26202, P26204, P26205, P26206, P26207, P26208", t.notes)

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
        self.assertEqual(len(t.rows), 4 + len(CARRIED_PROJECTS))   # WR-03: 스냅숏 4줄 + 이전 파일에만 있는 6줄
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

    def test_vat_with_other_vendor_goes_to_the_only_cost_group_of_the_slip(self):
        """실제 자료 2025-12 8건: 부가세 줄 거래처(가맹점)와 원가 줄 거래처가 다른 카드 매입 → 전표의 원가 묶음이 하나면 거기에."""
        other = [_jl(_D, 52, "61101", "행사외주비(도)", 100000, None, "가상가게", "[26201] 다른 거래처 부가세"),
                 _jl(_D, 52, "13500", "부가세대급금", 10000, None, "가상가맹점", "[26201] 다른 거래처 부가세"),
                 _jl(_D, 52, "25300", "미지급금", None, 110000, "가상가게", "[26201] 다른 거래처 부가세")]
        t = exec_table(exec_inputs(journal_with(other)))
        self.assertEqual(by_slip(t, 52)[5], "10000")
        self.assertIn("원가 전표 부가세대급금: 원본 24,850,000 · CSV 24,850,000 → 일치", check_lines(t))

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
        # 전표에 원가 묶음이 둘 이상이면 어느 것에 붙일지 몰라 놓지 않는다 (하나면 거기에 붙임, 위 시험)
        lines = [_jl(dt.date(2026, 10, 20), 1, "13500", "부가세대급금", 1000, None, "가상다른곳", "부가세"),
                 _jl(dt.date(2026, 10, 20), 1, "61101", "행사외주비(도)", 5000, None, "가상셋째", "[26201] 셋째")]
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


# ───────────── Task 3: 아직 장부에 없는 지급요청, 큰 쪽 반영, 옮겨 온 집행계획 줄, 두 번 세지 않음 ─────────────
def full_table(inp=None, prev=None, **kw):
    inp = inp or exec_inputs(FAKE_PL_JOURNAL)
    return exec_table(inp, requests=True, prev=prev_execs() if prev is None else prev, **kw)


def lines_of(table):
    return check_lines(table)


def naming(table, number):
    """근거에 '지급요청 <번호>'가 들어 있는 줄들."""
    pattern = re.compile(r"지급요청 %s(?!\d)" % number)
    return [r for r in cell_rows(table) if pattern.search(r[8])]


def total_of(rows):
    return sum(int(r[4] or 0) + int(r[5] or 0) for r in rows)


REQUEST_ROWS = [   # 번호 순: 5102, 5105, 5106, 5107 (02-REVIEW CR-03 / D-52: 사장님승인 '반려'는 상태 확인 필요 → 추정 줄), 5108
    ("26201", "[26201] 가상 컨퍼런스", "가상조명", "요청미지급", "264000", "", "2026-11-06", "추정",
     "지급요청 5102 (인트라넷 금액, 부가세 포함 여부 미확인)"),
    ("26221", "[26221] 가상 워크숍", "가상버스", "요청미지급", "3300000", "", "2026-11-10", "확정",
     "지급요청 5105 (인트라넷 금액, 부가세 포함 여부 미확인)"),
    ("26221", "[26221] 가상 워크숍", "가상숙박", "요청미지급", "", "", "2026-11-17", "추정",
     "지급요청 5106 (인트라넷 금액, 부가세 포함 여부 미확인)"),
    ("26201", "[26201] 가상 컨퍼런스", "가상케이터링", "요청미지급", "1100000", "", "2026-11-06", "추정",
     "지급요청 5107 상태 확인 필요 (반려) (인트라넷 금액, 부가세 포함 여부 미확인)"),
    ("26299", "[26299] 목록에 없는 행사", "가상꽃", "요청미지급", "2200000", "", "2026-11-06", "추정",
     "지급요청 5108 (인트라넷 금액, 부가세 포함 여부 미확인)"),
]


class TestBuildExecsRequests(unittest.TestCase):
    def test_requests_with_an_invoice_are_noted_on_the_wehago_row(self):
        t = full_table()
        one, two, five = by_slip(t, 1), by_slip(t, 2), by_slip(t, 5)
        self.assertEqual(one, ("26201", "[26201] 가상 컨퍼런스 음향", "(주)가상음향", "요청미지급", "40000000", "4000000", "2026-11-13",
                               "추정", "WEHAGO 2026-10-20 전표 1 · 지급요청 1201"))
        self.assertEqual((two[3], two[4], two[5], two[6], two[7], two[8]),
                         ("요청미지급", "150000000", "15000000", "2026-11-20", "추정", "WEHAGO 2026-10-21 전표 2 · 지급요청 5103"))
        self.assertEqual((five[3], five[4], five[5], five[6], five[7], five[8]),
                         ("요청미지급", "5000000", "500000", "2026-10-30", "확정", "WEHAGO 2026-10-23 전표 5 · 지급요청 5104"))
        for no in (4, 6, 7, 8):
            self.assertEqual((by_slip(t, no)[3], by_slip(t, no)[6], by_slip(t, no)[7]), ("요청미지급", "", "추정"))
        self.assertEqual(by_slip(t, 3)[3:], BASE_ROWS[4][3:])
        for no, want in ((22, BASE_ROWS[9]), (23, BASE_ROWS[10]), (37, BASE_ROWS[0])):
            self.assertEqual(by_slip(t, no)[3:], want[3:])

    def test_five_request_rows_follow_the_wehago_rows_in_number_order(self):
        t = full_table()
        rows = cell_rows(t)
        self.assertEqual(rows[11:16], REQUEST_ROWS)
        self.assertEqual(t.extra["cost_portions"][11:16], [None] * 5)

    def test_no_payment_is_counted_twice(self):
        t = full_table()
        self.assertEqual(naming(t, "5109"), [])
        self.assertEqual(by_slip(t, 3)[3], "지급완료")
        self.assertTrue([n for n in t.notes if n.startswith("지급요청 5109: 이미 지급") and n.endswith("→ 넣지 않음")], t.notes)
        for number in ("1201", "5102", "5103", "5104", "5105", "5106", "5107", "5108"):
            self.assertEqual(len(naming(t, number)), 1, number)

    def test_request_count_and_money_checks_read_match(self):
        t = full_table()
        lines = lines_of(t)
        for want in ("지급요청 건수: 승인·대기 8 + 상태 확인 필요 1 = 원가 줄에 표시 3 + 요청 줄 5 + 이미 지급 1: 원본 9 · CSV 9 → 일치",
                     "지급요청 금액 (금액 있는 승인·대기·상태 확인 필요 8건) = 원가 줄 표시 + 요청 줄 + 이미 지급: "
                     "원본 266,364,000 · CSV 266,364,000 → 일치",
                     "지급요청 금액 미확인: 원본 1 · CSV 1 → 일치",
                     "계산서·요청 금액이 다르면 큰 쪽: 지급요청을 가리키는 줄 합계 = max(계산서, 요청): 원본 216,700,000 · CSV 216,700,000 → 일치"):
            self.assertIn(want, lines)
        for c in t.checks:
            self.assertEqual(mod("convert").check_result(c), "일치", c.label)

    def test_5103_is_carried_at_the_larger_invoice_amount_without_a_diff_row(self):
        t = full_table()
        self.assertEqual(total_of(naming(t, "5103")), 165000000)
        self.assertEqual(len(naming(t, "5103")), 1)

    def test_status_unknown_request_is_an_estimated_row_with_a_note(self):
        # 02-REVIEW CR-03 / D-52: 사장님승인을 읽지 못한 요청은 버리지 않고 요청미지급(추정) 줄로 넣는다 (예전: 넣지 않음)
        t = full_table()
        self.assertIn("상태 확인 필요 1건 → 요청미지급(추정)으로 넣음 (D-52: 사장님승인이 빈칸이거나 알 수 없는 값)", t.notes)
        self.assertTrue([n for n in t.notes if "5107" in n and "1,100,000" in n and "(반려)" in n], t.notes)
        row = naming(t, "5107")
        self.assertEqual([(r[3], r[4], r[7]) for r in row], [("요청미지급", "1100000", "추정")])

    def test_duplicate_possible_notes_name_the_requests_added_next_to_unpaid_rows(self):
        t = full_table()
        self.assertIn("중복 가능: 지급요청 5102 — 같은 거래처의 미지급 원가 줄 1건", t.notes)
        self.assertIn("중복 가능: 지급요청 5105 — 같은 거래처의 미지급 원가 줄 2건", t.notes)
        self.assertIn("지급요청 5108: 계산서 있음이나 원가 줄을 하나로 정하지 못함 → 요청으로 넣음 (중복 가능)", t.notes)
        self.assertEqual([n for n in t.notes if n.startswith("중복 가능")].__len__(), 2)

    def test_unknown_request_amount_is_blank_never_zero(self):
        t = full_table()
        row = naming(t, "5106")[0]
        self.assertEqual((row[4], row[5]), ("", ""))
        self.assertFalse([r for r in cell_rows(t) if r[3] == "요청미지급" and r[4] == "0"])

    def test_invoice_below_the_request_adds_a_diff_row_so_the_rows_equal_the_request(self):
        ledger = [list(r) for r in FAKE_LEDGER]
        ledger[0] = _L("매입", "2026-10-20", 1, "(주)가상음향", "000-00-00001", "[26201] 가상 컨퍼런스 음향", 36000000, 4000000)
        journal = post(ledger) + PL_EXTRA
        inp = exec_inputs(journal, ledger=ledger)
        self.assertEqual(inp.match["rows"]["1201"]["status"], "금액 차이")
        t = full_table(inp)
        self.assertEqual(by_slip(t, 1)[4:6], ("36000000", "4000000"))
        diff = [r for r in naming(t, "1201") if "차액" in r[8]]
        self.assertEqual(len(diff), 1)
        self.assertEqual((diff[0][3], diff[0][4], diff[0][5], diff[0][6]), ("요청미지급", "4000000", "", "2026-11-13"))
        self.assertEqual(diff[0][8], "지급요청 1201 차액 (인트라넷 요청 44,000,000 − 계산서 40,000,000)")
        self.assertEqual(total_of(naming(t, "1201")), 44000000)
        self.assertIn("지급요청 건수: 승인·대기 8 + 상태 확인 필요 1 = 원가 줄에 표시 3 + 요청 줄 5 + 이미 지급 1: 원본 9 · CSV 9 → 일치",
                      lines_of(t))

    def test_invoice_above_the_request_with_an_ambiguous_group_adds_the_request_and_a_diff_row(self):
        second = [_jl(dt.date(2026, 10, 27), 70, "61101", "행사외주비(도)", 150000000, None, "가상제작", "[26220] 가상 전시 제작 2차"),
                  _jl(dt.date(2026, 10, 27), 70, "13500", "부가세대급금", 15000000, None, "가상제작", "[26220] 가상 전시 제작 2차"),
                  _jl(dt.date(2026, 10, 27), 70, "25300", "미지급금", None, 165000000, "가상제작", "[26220] 가상 전시 제작 2차")]
        t = full_table(exec_inputs(journal_with(second)))
        rows = naming(t, "5103")
        self.assertEqual(len(rows), 2)
        request = [r for r in rows if "차액" not in r[8]][0]
        diff = [r for r in rows if "차액" in r[8]][0]
        self.assertEqual((request[4], request[5], request[6], request[7]), ("160500000", "", "2026-11-20", "추정"))
        self.assertEqual((diff[3], diff[4], diff[5]), ("요청미지급", "4500000", ""))
        self.assertEqual(diff[8], "지급요청 5103 차액 (계산서 165,000,000 − 인트라넷 요청 160,500,000)")
        self.assertEqual(total_of(rows), 165000000)
        self.assertTrue([n for n in t.notes if "5103" in n and "중복 가능" in n], t.notes)
        self.assertEqual(by_slip(t, 2)[8], "WEHAGO 2026-10-21 전표 2")
        lines = lines_of(t)
        self.assertIn("지급요청 건수: 승인·대기 8 + 상태 확인 필요 1 = 원가 줄에 표시 2 + 요청 줄 6 + 이미 지급 1: 원본 9 · CSV 9 → 일치",
                      lines)
        self.assertIn("지급요청 금액 (금액 있는 승인·대기·상태 확인 필요 8건) = 원가 줄 표시 + 요청 줄 + 이미 지급: "
                      "원본 266,364,000 · CSV 266,364,000 → 일치", lines)
        for c in t.checks:
            self.assertEqual(mod("convert").check_result(c), "일치", c.label)

    def test_an_invoice_row_already_paid_means_no_request_row_and_a_note(self):
        t = full_table(exec_inputs(journal_with(OPENING_EXTRA)))
        # 02-REVIEW CR-02: 이미 지급된 계산서 줄에 요청 번호를 붙인다 (D-50 합계가 그 줄을 센다). 나갈 돈 줄은 없다 (요청 = 계산서)
        self.assertEqual([r[3] for r in naming(t, "5104")], ["지급완료"])
        self.assertTrue(by_slip(t, 5)[8].endswith(" · 지급요청 5104"), by_slip(t, 5))
        self.assertIn("지급요청 5104: 계산서의 원가 줄이 이미 지급완료 → 요청 줄 넣지 않음 (원가 줄에 번호 표시)", t.notes)
        self.assertEqual(by_slip(t, 5)[3], "지급완료")
        lines = lines_of(t)
        self.assertIn("지급요청 건수: 승인·대기 8 + 상태 확인 필요 1 = 원가 줄에 표시 2 + 요청 줄 5 + 이미 지급 1 + 이미 지급된 원가 줄 1: "
                      "원본 9 · CSV 9 → 일치", lines)
        self.assertIn("지급요청 금액 (금액 있는 승인·대기·상태 확인 필요 8건) = 원가 줄 표시 + 요청 줄 + 이미 지급: "
                      "원본 266,364,000 · CSV 266,364,000 → 일치", lines)

    def test_unknown_request_amount_with_an_invoice_gives_a_note_and_no_diff_row(self):
        inp = exec_inputs(FAKE_PL_JOURNAL)
        for rq in inp.requests:
            if rq["번호"] == "1201":
                rq["amount"] = None
        t = full_table(inp)
        self.assertIn("지급요청 1201 금액 미확인 → 차액 판단 불가", t.notes)
        rows = naming(t, "1201")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][4], "")
        self.assertFalse([r for r in cell_rows(t) if "차액" in r[8]])

    def test_a_group_wanted_by_two_requests_is_given_to_neither(self):
        inp = exec_inputs(FAKE_PL_JOURNAL)
        twin = dict([rq for rq in inp.requests if rq["번호"] == "1201"][0], 번호="1299", id="r99")
        inp.requests.append(twin)
        row = dict(inp.match["rows"]["1201"])
        inp.match["rows"]["1299"] = row
        t = full_table(inp)
        self.assertEqual(by_slip(t, 1)[8], "WEHAGO 2026-10-20 전표 1")
        self.assertEqual(len(naming(t, "1201")), 1)
        self.assertEqual(len(naming(t, "1299")), 1)
        self.assertTrue([n for n in t.notes if "1299" in n and "중복 가능" in n], t.notes)

    def test_result_does_not_depend_on_the_order_of_requests_or_journal(self):
        base = cell_rows(full_table())
        inp = exec_inputs(FAKE_PL_JOURNAL)
        inp.requests.reverse()
        self.assertEqual(cell_rows(full_table(inp)), base)

    def test_previous_plan_rows_are_carried_with_the_new_project_number(self):
        t = full_table()
        carried = cell_rows(t)[16:20]
        self.assertEqual([(r[0], r[1], r[3]) for r in carried],
                         [("26201", "케이터링", "집행계획미요청"), ("26201", "영상·중계", "집행계획미요청"),
                          ("26203", "현장 인력", "집행계획미요청"), ("P26207", "공연", "집행계획미요청")])
        self.assertEqual(carried[0][4:], ("55,000,000", "5,500,000", "2026-11-25", "추정", "계약서"))
        # 02-REVIEW WR-04: 손으로 넣은 미지급 줄 4건도 옮긴다 (예전: 버리고 알림만). 지급완료 손 줄과 '지급요청' 줄은 옮기지 않는다
        self.assertEqual([(r[0], r[3], r[4], r[5], r[8]) for r in cell_rows(t)[20:]],
                         [("26201", "카드사용미결제", "3200000", "", "카드 사용"), ("P26204", "요청미지급", "10000000", "1000000", "가계약서"),
                          ("P26206", "요청미지급", "", "", "금액 확인 중"), ("P26208", "카드사용미결제", "350000", "", "카드 사용")])
        self.assertEqual(t.extra["cost_portions"][16:], [None] * 8)
        self.assertIn("이전 프로젝트집행.csv 줄 16건 옮기지 않음 (WEHAGO·인트라넷으로 다시 만듦)", t.notes)   # 예전 20건
        self.assertTrue([n for n in t.notes if "P26207" in n and "번호 그대로" in n], t.notes)
        unpaid = [n for n in t.notes if "아직 나가지 않은 돈" in n]
        self.assertEqual(len(unpaid), 1)
        self.assertIn("2건", unpaid[0])   # 예전 6건 (금액 미확인 1건 제외): 이제 남은 것은 다시 만드는 '지급요청' 줄 2건뿐
        self.assertNotIn("금액 미확인", unpaid[0])

    def test_without_the_project_list_the_linked_keys_and_request_codes_are_used(self):
        inp = exec_inputs(FAKE_PL_JOURNAL)
        t = mod("convert_projects").build_execs(inp.books, inp.costs, inp.requests, inp.match, prev_execs(), inp.cfg)
        self.assertEqual([r[0] for r in cell_rows(t)[16:]], ["26201", "26201", "26203", "P26207",
                                                               "26201", "P26204", "P26206", "P26208"])   # WR-04: 손 줄 4건 추가

    def test_nothing_is_carried_when_there_is_no_previous_file_and_no_note_is_made_up(self):
        t = full_table(prev=[])
        self.assertEqual(len(t.rows), 16)
        self.assertFalse([n for n in t.notes if "이전 프로젝트집행.csv" in n])

    def test_second_run_on_its_own_output_gives_the_same_rows(self):
        first = full_table()
        tmp = new_tmp(self)
        input_dir, d = write_and_load(tmp, [first])
        again = full_table(prev=mod("convert").read_prev(input_dir, "프로젝트집행.csv"))
        self.assertEqual([r[:2] + r[3:] for r in cell_rows(again)], [r[:2] + r[3:] for r in cell_rows(first)])
        self.assertEqual([r[0] for r in cell_rows(again)], [r[0] for r in cell_rows(first)])

    def test_written_file_loads_with_only_the_unlinked_project_issues(self):
        tmp = new_tmp(self)
        input_dir, d = write_and_load(tmp, [project_table(), full_table()])
        issues = [it for it in d.issues.items if it[0] == "프로젝트집행.csv"]
        # 02-REVIEW WR-03: P26207 은 이전 프로젝트.csv 에서 옮겨져 이제 프로젝트.csv 에 있다 (예전 4건)
        self.assertEqual(len(issues), 3, issues)
        # 빈 번호 줄은 줄마다가 아니라 한 줄로 센다 (실제 자료 2천 줄 넘음, 2026-11-04)
        got = sorted(re.match(r"프로젝트번호 '(.*)'가 프로젝트.csv에 없음 \(프로젝트 미연결로 집계\)$", it[2]).group(1)
                     for it in issues if not it[2].startswith("프로젝트번호 빈칸"))
        self.assertEqual(got, ["26299", "26999"])
        self.assertIn("프로젝트번호 빈칸 줄 1건", " ".join(it[2] for it in issues))
        self.assertEqual([it for it in d.issues.items if it[0] == "프로젝트.csv"], [])


class TestBuildExecsNoDouble(unittest.TestCase):
    def _written(self, table_rows=None):
        tmp = new_tmp(self)
        tables = [project_table(), full_table()]
        input_dir, d = write_and_load(tmp, tables)
        return tmp, input_dir, d

    def test_calc_events_name_each_request_at_most_once_and_5103_is_165_million(self):
        tmp, input_dir, d = self._written()
        R = mod("calc").compute(d, "weekly", dt.date(2026, 11, 2))
        events = [e for e in R["events"] if e["source"] == "프로젝트집행"]
        # 5107 (사장님승인 '반려' = 상태 확인 필요)도 한 번 들어간다 (02-REVIEW CR-03 / D-52, 예전: 들어가지 않음)
        for number in ("1201", "5102", "5103", "5104", "5105", "5106", "5107", "5108"):
            named = [e for e in events if re.search(r"지급요청 %s(?!\d)" % number, e["basis"] or "")]
            self.assertEqual(len(named), 1, number)
        five = [e for e in events if "지급요청 5103" in (e["basis"] or "")]
        self.assertEqual(sum(e["amount"] for e in five), 165000000)
        self.assertFalse([e for e in events if "지급요청 5109" in (e["basis"] or "")])

    def test_approval_screen_replaces_the_rows_that_name_a_scheduled_request_and_schedules_none_twice(self):
        approval, snapshot = mod("approval"), mod("snapshot")
        tmp, input_dir, d = self._written()
        snap = snapshot.read_snapshot(write_fake_snapshot(os.path.join(tmp, "스냅숏")))
        A = approval.build(d, snap, ASOF, NOW)
        scheduled = sorted(rq["번호"] for rq in A["requests_all"] if rq["scheduled"])
        self.assertEqual(scheduled, ["1201", "5102", "5103", "5105", "5108", "5109"])
        replaced = sorted(re.search(r"지급요청 (\d+)", e["basis"]).group(1) for e in A["replaced"])
        self.assertEqual(replaced, ["1201", "5102", "5103", "5105", "5108"])
        for e in A["unmatched_exec"] + A["duplicates"] + A["possible_duplicates"]:
            m = re.search(r"지급요청 (\d+)", e["basis"] or "")
            self.assertFalse(m and m.group(1) in scheduled, e)
        # 같은 화면을 요청 이름이 붙은 줄 없이 만들어도 일정 합계가 같다 (요청이 대신 들어가므로)
        reduced = os.path.join(tmp, "줄임")
        shutil.copytree(input_dir, reduced)
        convert = mod("convert")
        rest = [r for r in convert.read_prev(input_dir, "프로젝트집행.csv")
                if not any(re.search(r"지급요청 %s(?!\d)" % n, r["근거"]) for n in scheduled)]
        table = mod("convert").Table("프로젝트집행.csv", mod("data").SCHEMA["프로젝트집행.csv"], rest)
        convert.write_table(os.path.join(reduced, "프로젝트집행.csv"), table)
        B = approval.build(mod("data").load(reduced), snap, ASOF, NOW)
        # 남은 예산 지급 예정(D-54)은 프로젝트집행 줄이 빠지면 커지는 것이 맞으므로 비교에서 뺀다
        total = lambda X: (sum(x["amount"] for x in X["data"]["requests"]) + sum(X["data"]["base_out"])
                           - sum(ev["amount"] for ev in X["budget_sched"]))
        self.assertEqual(total(A), total(B))
        self.assertGreater(total(A), 0)


# ───── 인트라넷을 가용자금 일정에 넣던 규칙 (calc.INTRANET_IN_FUNDS=True) 으로 시험 ─────
# 사용자 결정(2026-11-04 '비교만') 뒤 기본은 False. 이 파일은 그 규칙이 켜졌을 때의 일정 계산을 그대로 지킨다.
import ceo_report.calc as _calc_for_flag  # noqa: E402
_setup_before_flag = globals().get("setUpModule")
_teardown_before_flag = globals().get("tearDownModule")


def setUpModule():  # noqa: F811
    _calc_for_flag.INTRANET_IN_FUNDS = True
    if _setup_before_flag:
        _setup_before_flag()


def tearDownModule():  # noqa: F811
    _calc_for_flag.INTRANET_IN_FUNDS = False
    if _teardown_before_flag:
        _teardown_before_flag()


if __name__ == "__main__":
    unittest.main()
