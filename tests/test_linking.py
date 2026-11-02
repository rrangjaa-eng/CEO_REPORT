"""프로젝트 연결(D-38) 시험 (Phase 2, 계획 02-02).

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

from sample_input import SAMPLE, refresh as refresh_sample  # noqa: E402
from test_approval import (ASOF, COLLECTED, FAKE_PAYMENTS, FAKE_PROJECTS, NOW, as_dicts,  # noqa: E402
                           write_fake_snapshot)
from test_wehago import FAKE_JOURNAL, _jl, write_fake_books  # noqa: E402


def mod(name):
    return importlib.import_module("ceo_report." + name)


def setUpModule():
    refresh_sample()  # 샘플은 임시 폴더에 쓴다 (실제 입력 폴더를 건드리지 않음)


def new_tmp(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    return tmp


# ───────────── 가상 자료 (02-PATTERNS §5) ─────────────
_D = dt.date(2026, 10, 30)
LINK_EXTRA = [
    _jl(_D, 40, "61101", "행사외주비(도)", 200000, None, "가상조명", "조명 추가"),
    _jl(_D, 40, "13500", "부가세대급금", 20000, None, "가상조명", "조명 추가"),
    _jl(_D, 40, "25300", "미지급금", None, 220000, "가상조명", "조명 추가"),
    _jl(_D, 41, "61101", "행사외주비(도)", 500000, None, "가상케이터링", "케이터링"),
    _jl(_D, 41, "10300", "보통예금", None, 500000, "가상케이터링", "케이터링"),
    _jl(_D, 42, "61101", "행사외주비(도)", 300000, None, "가상숙박", "숙박 1"),
    _jl(_D, 42, "10300", "보통예금", None, 300000, "가상숙박", "숙박 1"),
    _jl(_D, 43, "61101", "행사외주비(도)", 300000, None, "가상숙박", "숙박 2"),
    _jl(_D, 43, "10300", "보통예금", None, 300000, "가상숙박", "숙박 2"),
    _jl(_D, 44, "61101", "행사외주비(도)", 1000000, None, "가상음향", "음향 추가"),
    _jl(_D, 44, "10300", "보통예금", None, 1000000, "가상음향", "음향 추가"),
]
# PAYMENT_COLUMNS 순서: 번호, 행사명, 파트너, 등록일, 행사일, 금액, 지급요청일, 등록자, 팀장승인, 관리팀승인, 사장님승인
LINK_REQUESTS = [
    ["6001", "[26220] 가상 전시", "가상조명", "2026-10-20 09:00:00", "2026-11-12", "220,000", "", "김철수", "승인", "승인", "승인"],
    ["6002", "[26201] 가상 컨퍼런스", "가상케이터링", "2026-10-25 09:00:00", "2026-11-20", "500,000", "", "홍길동", "승인", "승인", "미승인"],
    ["6003", "[26220] 가상 전시", "가상케이터링", "2026-10-26 09:00:00", "2026-11-12", "500,000", "", "김철수", "승인", "승인", "미승인"],
    ["6004", "[26221] 가상 워크숍", "가상숙박", "2026-10-28 09:00:00", "2026-11-25", "300,000", "", "이영희", "승인", "승인", "미승인"],
    ["6005", "[26201] 가상 컨퍼런스", "가상음향", "2026-06-01 09:00:00", "2026-11-20", "1,000,000", "", "홍길동", "승인", "승인", "승인"],
]
# 손익 가상 전표 30·31·32·38 (매출 줄 포함 전 줄)
_SAME = "[26201] 가상 컨퍼런스 선금"
REV_LINES = [
    _jl(dt.date(2026, 9, 15), 30, "10800", "수입수수료미수금", 110000000, None, "가상고객A", _SAME),
    _jl(dt.date(2026, 9, 15), 30, "41200", "수입수수료", None, 100000000, "가상고객A", _SAME),
    _jl(dt.date(2026, 9, 15), 30, "25500", "부가세예수금", None, 10000000, "가상고객A", _SAME),
    _jl(dt.date(2026, 10, 27), 31, "10800", "수입수수료미수금", 82500000, None, "가상고객D", "가상 전시부스 잔금"),
    _jl(dt.date(2026, 10, 27), 31, "41200", "수입수수료", None, 75000000, "가상고객D", "가상 전시부스 잔금"),
    _jl(dt.date(2026, 10, 27), 31, "25500", "부가세예수금", None, 7500000, "가상고객D", "가상 전시부스 잔금"),
    _jl(dt.date(2026, 10, 28), 32, "10800", "수입수수료미수금", 22000000, None, "가상고객X", "기타 용역"),
    _jl(dt.date(2026, 10, 28), 32, "41200", "수입수수료", None, 20000000, "가상고객X", "기타 용역"),
    _jl(dt.date(2026, 10, 28), 32, "25500", "부가세예수금", None, 2000000, "가상고객X", "기타 용역"),
    _jl(dt.date(2026, 10, 29), 38, "41200", "수입수수료", 1000000, None, "가상고객X", "매출 정정"),
    _jl(dt.date(2026, 10, 29), 38, "25500", "부가세예수금", 100000, None, "가상고객X", "매출 정정"),
    _jl(dt.date(2026, 10, 29), 38, "10800", "수입수수료미수금", None, 1100000, "가상고객X", "매출 정정"),
]


def write_link_books(folder, journal):
    """분개장을 folder 에 쓰고 wehago.load_books 로 읽어 돌려준다 (장부 날짜 검사 없음)."""
    write_fake_books(folder, journal=journal)
    books = mod("wehago").load_books(folder, ASOF, None)
    assert books.state == "ok", books.reason
    return books


_DEFAULT = object()


def link_snapshot(tmp, extra=_DEFAULT, projects=None):
    """가상 스냅숏을 읽어 돌려준다. extra 기본값은 LINK_REQUESTS, None 이면 FAKE 9건만. projects 는 프로젝트 줄 목록(기본 FAKE)."""
    snapshot = mod("snapshot")
    rows = [list(r) for r in FAKE_PAYMENTS] + [list(r) for r in (LINK_REQUESTS if extra is _DEFAULT else (extra or []))]
    proj = FAKE_PROJECTS if projects is None else projects
    folder = snapshot.write_snapshot(tmp, COLLECTED, as_dicts(rows, snapshot.PAYMENT_COLUMNS),
                                     as_dicts(proj, snapshot.PROJECT_COLUMNS))
    return snapshot.read_snapshot(folder)


def write_links_csv(input_dir, rows, header=None):
    """입력/프로젝트연결.csv 를 쓴다 (UTF-8 BOM). rows 는 칸 목록들."""
    os.makedirs(input_dir, exist_ok=True)
    path = os.path.join(input_dir, "프로젝트연결.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header or ["전표일자", "전표번호", "줄", "프로젝트번호"])
        w.writerows(rows)
    return path


def setup_cost(test, journal=FAKE_JOURNAL, extra=_DEFAULT, projects=None):
    """(books, requests, projects) — 가상 장부와 스냅숏."""
    tmp = new_tmp(test)
    books = write_link_books(os.path.join(tmp, "book"), journal)
    snap = link_snapshot(os.path.join(tmp, "snap"), extra=extra, projects=projects)
    L = mod("linking")
    return books, L.requests_of(snap, ASOF, NOW), L.projects_of(snap)


def by_no(result):
    """{전표번호: 줄 목록}"""
    out = {}
    for ln in result["lines"]:
        out.setdefault(ln["no"], []).append(ln)
    return out


def total(result):
    return sum(v["sum"] for v in result["summary"].values())


def cnt(result):
    return dict((b, (v["count"], v["sum"])) for b, v in result["summary"].items())


# ───────────── Task 1 (tracer): 요청·프로젝트 → [코드] 연결 ─────────────
class TestLinkingTracer(unittest.TestCase):
    def test_requests_of_gives_the_nine_fake_requests_with_approval_shapes(self):
        tmp = new_tmp(self)
        L = mod("linking")
        snap = link_snapshot(tmp, extra=None)
        reqs = L.requests_of(snap, ASOF, NOW)
        self.assertEqual([r["번호"] for r in reqs], [p[0] for p in FAKE_PAYMENTS])
        r = dict((x["번호"], x) for x in reqs)
        self.assertEqual((r["1201"]["status"], r["1201"]["amount"], r["1201"]["code"]), ("pending", 44000000, "26201"))
        self.assertEqual(r["1201"]["date"], dt.date(2026, 11, 13))
        self.assertEqual(r["5104"]["status"], "approved")
        self.assertEqual(r["5104"]["date"], dt.date(2026, 10, 30))
        self.assertEqual(r["5104"]["rule"], "지급요청일 없음 → 목요일 14시 승인·금요일 지급 (등록 시각 기준)")
        self.assertIsNone(r["5106"]["amount"])
        self.assertEqual(r["5107"]["status"], "status_unknown")
        for k in ("id", "번호", "name", "vendor", "code", "registered", "status", "amount", "request_date", "date", "rule"):
            self.assertIn(k, reqs[0])

    def test_request_shapes_equal_approval_build_requests_all(self):
        tmp = new_tmp(self)
        L = mod("linking")
        snap = link_snapshot(tmp, extra=None)
        reqs = L.requests_of(snap, ASOF, NOW)
        A = mod("approval").build(mod("data").load(SAMPLE), snap, ASOF, NOW)
        self.assertEqual(len(reqs), len(A["requests_all"]))
        for mine, theirs in zip(reqs, A["requests_all"]):
            for k in mine:
                self.assertEqual(mine[k], theirs[k], "%s %s" % (mine["번호"], k))

    def test_projects_of_gives_four_projects_with_team_budget_and_quote(self):
        tmp = new_tmp(self)
        L = mod("linking")
        projects = L.projects_of(link_snapshot(tmp, extra=None))
        self.assertEqual(list(projects), ["26201", "26220", "26221", "26203"])
        self.assertEqual([p["team"] for p in projects.values()], ["1팀", "2팀", "1팀", "2팀"])
        self.assertEqual([p["budget"] for p in projects.values()], [300000000, 250000000, None, 60000000])
        self.assertEqual([p["quote"] for p in projects.values()], [420000000, 320000000, 55000000, 75000000])
        self.assertEqual(projects["26201"]["name"], "가상 컨퍼런스")
        self.assertEqual(projects["26201"]["client_norm"], "가상고객A")
        self.assertEqual(projects["26201"]["estimate"], 400000000)
        self.assertFalse(projects["26201"]["dup"])

    def test_projects_of_repeated_key_keeps_first_and_marks_dup(self):
        tmp = new_tmp(self)
        L = mod("linking")
        rows = [list(r) for r in FAKE_PROJECTS] + [list(FAKE_PROJECTS[1])]
        rows[-1][12] = "1"
        projects = L.projects_of(link_snapshot(tmp, extra=None, projects=rows))
        self.assertEqual(len(projects), 4)
        self.assertTrue(projects["26220"]["dup"])
        self.assertEqual(projects["26220"]["budget"], 250000000)
        self.assertFalse(projects["26201"]["dup"])

    def test_projects_of_none_is_empty(self):
        L = mod("linking")
        self.assertEqual(len(L.projects_of(None)), 0)
        self.assertEqual(list(L.projects_of(None)), [])

    def test_line_keys_count_lines_within_a_slip(self):
        L = mod("linking")
        keys = L.line_keys(self._books().journal)
        self.assertEqual(keys[0], ("2026-10-20", "1", 1))
        self.assertEqual(keys[1], ("2026-10-20", "1", 2))
        self.assertEqual(keys[2], ("2026-10-20", "1", 3))
        j = self._books().journal
        at = [i for i, r in enumerate(j) if r["no"] == "22"][0]
        self.assertEqual(keys[at], ("2026-10-29", "22", 1))
        self.assertEqual(keys[at + 1], ("2026-10-29", "22", 2))
        self.assertEqual(len(keys), len(j))
        self.assertEqual(len(set(keys)), len(keys))

    def _books(self):
        if not hasattr(self, "_cached"):
            self._cached = write_link_books(os.path.join(new_tmp(self), "b"), FAKE_JOURNAL)
        return self._cached

    def test_link_costs_by_code_matches_truth_2(self):
        L = mod("linking")
        books, reqs, projects = setup_cost(self, extra=None)
        res = L.link_costs(books, reqs, projects, {})
        n = by_no(res)
        self.assertEqual(len(res["lines"]), 10)
        for no, code in (("1", "26201"), ("2", "26220"), ("3", "26203"), ("4", "26220"), ("5", "26220"),
                         ("6", "26220"), ("7", "26221"), ("8", "26221")):
            (ln,) = n[no]
            self.assertEqual((ln["project"], ln["basis"], ln["label"]), (code, "코드", "코드 [%s]" % code))
            self.assertIsNone(ln["request"])
            self.assertEqual(ln["code"], code)
        (a,) = n["22"]
        (b,) = n["23"]
        self.assertEqual((a["project"], a["basis"], a["label"], a["amount"]),
                         (None, "미연결", "미연결 (코드 없음 · 자동 연결 후보 0건)", 800000))
        self.assertEqual((b["project"], b["basis"], b["label"], b["amount"]),
                         (None, "미연결", "미연결 (코드 26999 프로젝트 목록에 없음 · 자동 연결 후보 0건)", 300000))
        self.assertEqual(b["code"], "26999")
        self.assertEqual(cnt(res), {"수동": (0, 0), "코드": (8, 248400000), "자동": (0, 0), "미연결": (2, 1100000)})
        self.assertEqual(res["summary"]["코드"], {"count": 8, "sum": 248400000, "unknown": 0})
        self.assertEqual(res["summary"]["미연결"], {"count": 2, "sum": 1100000, "unknown": 0})
        self.assertEqual(total(res), 249500000)
        self.assertEqual(res["used"], set())

    def test_cost_total_equals_wehago_project_costs(self):
        L = mod("linking")
        W = mod("wehago")
        books, reqs, projects = setup_cost(self, extra=None)
        res = L.link_costs(books, reqs, projects, {})
        pc = W.project_costs(books, list(projects))
        want = sum(v["cost"] for v in pc["by_code"].values()) + pc["unlinked"]["sum"]
        self.assertEqual(total(res), want)
        self.assertEqual(res["summary"]["코드"]["sum"], sum(v["cost"] for v in pc["by_code"].values()))

    def test_only_direct_lines_are_cost_lines(self):
        L = mod("linking")
        books, reqs, projects = setup_cost(self, extra=None)
        res = L.link_costs(books, reqs, projects, {})
        self.assertEqual(set(ln["account_code"] for ln in res["lines"]), {"61101"})
        self.assertNotIn("24", by_no(res))   # 45100 (도)외주비는 원가 줄이 아니다
        self.assertNotIn("21", by_no(res))   # 81900 임차료
        self.assertNotIn("20", by_no(res))

    def test_line_fields(self):
        L = mod("linking")
        books, reqs, projects = setup_cost(self, extra=None)
        res = L.link_costs(books, reqs, projects, {})
        ln = by_no(res)["1"][0]
        for k in ("index", "key", "date", "no", "line", "vendor", "vendor_norm", "memo", "account_code", "account",
                  "amount", "project", "basis", "request", "candidates", "label", "code"):
            self.assertIn(k, ln)
        self.assertEqual(ln["key"], ("2026-10-20", "1", 1))
        self.assertEqual(ln["date"], dt.date(2026, 10, 20))
        self.assertEqual((ln["no"], ln["line"], ln["amount"], ln["account"]), ("1", 1, 40000000, "행사외주비(도)"))
        self.assertEqual(ln["vendor_norm"], "가상음향")
        self.assertEqual(books.journal[ln["index"]]["memo"], ln["memo"])

    def test_pure_does_not_change_inputs(self):
        import copy
        L = mod("linking")
        books, reqs, projects = setup_cost(self)
        before = (copy.deepcopy(books.journal), copy.deepcopy(reqs), copy.deepcopy(projects))
        L.link_costs(books, reqs, projects, {})
        self.assertEqual((books.journal, reqs, projects), before)

    def test_module_parses_as_python_38(self):
        import ast
        with open(os.path.join(ROOT, "ceo_report", "linking.py"), encoding="utf-8") as f:
            ast.parse(f.read(), feature_version=(3, 8))
        L = mod("linking")
        self.assertEqual(L.LINK_FILE, "프로젝트연결.csv")
        self.assertEqual(L.LINK_COLUMNS, ["전표일자", "전표번호", "줄", "프로젝트번호"])


if __name__ == "__main__":
    unittest.main()
