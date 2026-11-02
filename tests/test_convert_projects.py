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


if __name__ == "__main__":
    unittest.main()
