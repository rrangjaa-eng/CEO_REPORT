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


# ───────────── Task 2: 요청 하나로 자동 연결, 후보 여럿·공유, 기간, 수동 지정 ─────────────
def cost_extra(test, link_days=90, **kw):
    """FAKE_JOURNAL + LINK_EXTRA, 스냅숏 FAKE + LINK_REQUESTS 로 link_costs 결과를 돌려준다."""
    L = mod("linking")
    books, reqs, projects = setup_cost(test, journal=FAKE_JOURNAL + LINK_EXTRA)
    return L.link_costs(books, reqs, projects, kw.pop("overrides", {}), link_days=link_days, **kw), books, reqs, projects


class TestLinkingAuto(unittest.TestCase):
    def test_truth_3_labels_and_summary(self):
        res, _, _, _ = cost_extra(self)
        n = by_no(res)
        (a,) = n["40"]
        self.assertEqual((a["project"], a["basis"], a["request"], a["label"], a["amount"]),
                         ("26220", "자동", "6001", "자동 (지급요청 6001)", 200000))
        (b,) = n["41"]
        self.assertEqual((b["project"], b["basis"], b["label"], b["candidates"]),
                         (None, "미연결", "미연결 (자동 연결 후보 2건: 지급요청 6002, 6003)", 2))
        for no in ("42", "43"):
            (c,) = n[no]
            self.assertEqual((c["project"], c["basis"], c["label"], c["candidates"]),
                             (None, "미연결", "미연결 (자동 연결 후보 공유: 지급요청 6004)", 1))
        (d,) = n["44"]
        self.assertEqual((d["project"], d["basis"], d["label"]), (None, "미연결", "미연결 (코드 없음 · 자동 연결 후보 0건)"))
        self.assertEqual(n["22"][0]["label"], "미연결 (코드 없음 · 자동 연결 후보 0건)")
        self.assertEqual(n["23"][0]["label"], "미연결 (코드 26999 프로젝트 목록에 없음 · 자동 연결 후보 0건)")
        self.assertEqual(cnt(res), {"수동": (0, 0), "코드": (8, 248400000), "자동": (1, 200000), "미연결": (6, 3200000)})
        self.assertEqual(len(res["lines"]), 15)
        self.assertEqual(total(res), 251800000)
        self.assertEqual(sum(v["count"] for v in res["summary"].values()), 15)

    def test_auto_amount_equals_request_only_with_vat_added(self):
        res, _, reqs, _ = cost_extra(self)
        line = by_no(res)["40"][0]
        self.assertEqual(line["amount"] + 20000, dict((r["번호"], r) for r in reqs)["6001"]["amount"])

    def test_longer_window_links_line_44(self):
        res, _, _, _ = cost_extra(self, link_days=200)
        (d,) = by_no(res)["44"]
        self.assertEqual((d["project"], d["basis"], d["request"], d["label"]),
                         ("26201", "자동", "6005", "자동 (지급요청 6005)"))
        self.assertEqual(cnt(res)["자동"], (2, 1200000))
        self.assertEqual(total(res), 251800000)

    def test_window_edges_are_inclusive(self):
        res, _, _, _ = cost_extra(self, link_days=151)
        self.assertEqual(by_no(res)["44"][0]["basis"], "자동")
        res, _, _, _ = cost_extra(self, link_days=150)
        self.assertEqual(by_no(res)["44"][0]["basis"], "미연결")

    def test_zero_days_leaves_line_40_unlinked(self):
        res, _, _, _ = cost_extra(self, link_days=0)
        (a,) = by_no(res)["40"]
        self.assertEqual((a["basis"], a["label"]), ("미연결", "미연결 (코드 없음 · 자동 연결 후보 0건)"))
        self.assertEqual(total(res), 251800000)

    def test_a_line_before_the_registration_date_is_not_linked(self):
        res, books, reqs, projects = cost_extra(self)
        L = mod("linking")
        later = [dict(r, registered=dt.datetime(2026, 10, 31, 9, 0)) if r["번호"] == "6001" else r for r in reqs]
        res = L.link_costs(books, later, projects, {})
        self.assertEqual(by_no(res)["40"][0]["basis"], "미연결")

    def test_unreadable_registration_or_unknown_amount_is_never_a_candidate(self):
        res, books, reqs, projects = cost_extra(self)
        L = mod("linking")
        for change in ({"registered": None}, {"amount": None}):
            bad = [dict(r, **change) if r["번호"] == "6001" else r for r in reqs]
            out = L.link_costs(books, bad, projects, {})
            self.assertEqual(by_no(out)["40"][0]["basis"], "미연결", change)

    def test_request_with_code_outside_the_project_list_is_never_a_candidate(self):
        res, books, reqs, projects = cost_extra(self)
        L = mod("linking")
        bad = [dict(r, code="26999") if r["번호"] == "6001" else r for r in reqs]
        self.assertEqual(by_no(L.link_costs(books, bad, projects, {}))["40"][0]["basis"], "미연결")
        bad = [dict(r, code=None) if r["번호"] == "6001" else r for r in reqs]
        self.assertEqual(by_no(L.link_costs(books, bad, projects, {}))["40"][0]["basis"], "미연결")

    def test_other_vendor_or_other_amount_is_not_a_candidate(self):
        res, books, reqs, projects = cost_extra(self)
        L = mod("linking")
        bad = [dict(r, vendor="가상다른곳") if r["번호"] == "6001" else r for r in reqs]
        self.assertEqual(by_no(L.link_costs(books, bad, projects, {}))["40"][0]["basis"], "미연결")
        bad = [dict(r, amount=221000) if r["번호"] == "6001" else r for r in reqs]
        self.assertEqual(by_no(L.link_costs(books, bad, projects, {}))["40"][0]["basis"], "미연결")
        # 공급가액과 같아도 연결된다
        ok = [dict(r, amount=200000) if r["번호"] == "6001" else r for r in reqs]
        self.assertEqual(by_no(L.link_costs(books, ok, projects, {}))["40"][0]["request"], "6001")

    def test_request_status_does_not_matter(self):
        res, books, reqs, projects = cost_extra(self)
        L = mod("linking")
        for status in ("approved", "pending", "status_unknown"):
            other = [dict(r, status=status) if r["번호"] == "6001" else r for r in reqs]
            self.assertEqual(by_no(L.link_costs(books, other, projects, {}))["40"][0]["basis"], "자동", status)

    def test_a_request_that_is_candidate_of_two_lines_links_neither(self):
        # 6001 은 줄 40 의 하나뿐인 후보지만, 다른 줄(같은 거래처·같은 금액)도 후보로 삼으면 둘 다 미연결
        twin = [_jl(_D, 45, "61101", "행사외주비(도)", 220000, None, "가상조명", "조명 또 추가"),
                _jl(_D, 45, "10300", "보통예금", None, 220000, "가상조명", "조명 또 추가")]
        L = mod("linking")
        books, reqs, projects = setup_cost(self, journal=FAKE_JOURNAL + LINK_EXTRA + twin)
        res = L.link_costs(books, reqs, projects, {})
        n = by_no(res)
        self.assertEqual(n["40"][0]["label"], "미연결 (자동 연결 후보 공유: 지급요청 6001)")
        self.assertEqual(n["45"][0]["label"], "미연결 (자동 연결 후보 공유: 지급요청 6001)")
        self.assertEqual(total(res), 251800000 + 220000)

    def test_vat_total_needs_exactly_one_cost_line_of_the_vendor_in_the_slip(self):
        two = [_jl(_D, 46, "61101", "행사외주비(도)", 100000, None, "가상조명", "조명 A"),
               _jl(_D, 46, "61101", "행사외주비(도)", 100000, None, "가상조명", "조명 B"),
               _jl(_D, 46, "13500", "부가세대급금", 20000, None, "가상조명", "조명 VAT"),
               _jl(_D, 46, "25300", "미지급금", None, 220000, "가상조명", "조명")]
        L = mod("linking")
        books, reqs, projects = setup_cost(self, journal=FAKE_JOURNAL + two)
        res = L.link_costs(books, reqs, projects, {})
        self.assertEqual([ln["basis"] for ln in by_no(res)["46"]], ["미연결", "미연결"])

    def test_unknown_amount_is_counted_as_unknown_never_zero(self):
        blank = [_jl(_D, 47, "61101", "행사외주비(도)", None, None, "가상조명", "금액 빈칸"),
                 _jl(_D, 47, "10300", "보통예금", None, None, "가상조명", "금액 빈칸"),
                 _jl(_D, 48, "61101", "행사외주비(도)", None, None, "가상조명", "[26201] 금액 빈칸 코드")]
        L = mod("linking")
        books, reqs, projects = setup_cost(self, journal=FAKE_JOURNAL + blank)
        res = L.link_costs(books, reqs, projects, {})
        (a,) = by_no(res)["47"]
        self.assertEqual((a["amount"], a["basis"], a["label"]), (None, "미연결", "미연결 (금액 미확인)"))
        (b,) = by_no(res)["48"]
        self.assertEqual((b["amount"], b["basis"], b["label"]), (None, "코드", "코드 [26201]"))
        self.assertEqual(res["summary"]["미연결"], {"count": 3, "sum": 1100000, "unknown": 1})
        self.assertEqual(res["summary"]["코드"]["unknown"], 1)
        self.assertEqual(res["summary"]["코드"]["sum"], 248400000)

    def test_order_does_not_change_the_result(self):
        L = mod("linking")

        def content(res, books):
            out = {}
            for ln in res["lines"]:
                out[(ln["date"], ln["no"], ln["account_code"], ln["vendor"], ln["memo"], ln["amount"])] = (
                    ln["project"], ln["basis"], ln["label"], ln["request"])
            return out

        res, books, reqs, projects = cost_extra(self)
        want = content(res, books)
        rev_journal = list(reversed(FAKE_JOURNAL + LINK_EXTRA))
        books2, reqs2, projects2 = setup_cost(self, journal=rev_journal)
        got = L.link_costs(books2, list(reversed(reqs2)), projects2, {})
        self.assertEqual(content(got, books2), want)
        self.assertEqual(got["summary"], res["summary"])
        self.assertEqual(len(got["lines"]), 15)

    def test_pure_with_auto_inputs_unchanged(self):
        import copy
        res, books, reqs, projects = cost_extra(self)
        L = mod("linking")
        before = (copy.deepcopy(books.journal), copy.deepcopy(reqs), copy.deepcopy(projects))
        L.link_costs(books, reqs, projects, {"x": "y"})
        self.assertEqual((books.journal, reqs, projects), before)

    def test_settings_prefix_and_mark_come_from_the_arguments(self):
        res, _, _, _ = cost_extra(self, direct_prefixes=("4",), direct_mark="(도)")
        self.assertEqual([ln["account_code"] for ln in res["lines"]], ["45100"])
        res, _, _, _ = cost_extra(self, direct_mark="(판)")
        self.assertEqual(res["lines"], [])


KEY22 = ("2026-10-29", "22", 1)


class TestLinkingManual(unittest.TestCase):
    def _links(self, rows, header=None):
        input_dir = os.path.join(new_tmp(self), "입력")
        write_links_csv(input_dir, rows, header)
        return mod("linking").read_links(input_dir)

    def test_missing_file_gives_empty_and_note(self):
        L = mod("linking")
        self.assertEqual(L.read_links(os.path.join(new_tmp(self), "없는폴더")), ({}, ["프로젝트연결.csv 없음 (수동 지정 0건)"]))

    def test_header_only_file_gives_nothing_and_no_note(self):
        self.assertEqual(self._links([]), ({}, []))

    def test_truth_4_manual_rows_win_over_code_and_auto(self):
        L = mod("linking")
        input_dir = os.path.join(new_tmp(self), "입력")
        write_links_csv(input_dir, [["2026-10-29", "22", "1", "26221"], ["2026-10-30", "41", "1", "26201"],
                                    ["2026-10-20", "1", "1", "26220"], ["2026-10-01", "99", "1", "26201"],
                                    ["2026-10-20", "1", "2", "26201"]])
        overrides, notes = L.read_links(input_dir)
        self.assertEqual(notes, [])
        self.assertEqual(len(overrides), 5)
        res, books, reqs, projects = cost_extra(self, overrides=overrides)
        n = by_no(res)
        for no, proj in (("22", "26221"), ("41", "26201")):
            (ln,) = n[no]
            self.assertEqual((ln["project"], ln["basis"], ln["label"], ln["request"]),
                             (proj, "수동", "수동 (프로젝트연결.csv)", None))
        (one,) = n["1"]
        self.assertEqual((one["project"], one["basis"], one["code"]), ("26220", "수동", "26201"))
        self.assertEqual(cnt(res), {"수동": (3, 41300000), "코드": (7, 208400000),
                                    "자동": (1, 200000), "미연결": (4, 1900000)})
        self.assertEqual(total(res), 251800000)
        self.assertEqual(res["used"], set([KEY22, ("2026-10-30", "41", 1), ("2026-10-20", "1", 1)]))
        un = L.unused_links(books, overrides, res["used"])
        self.assertEqual(un, [(("2026-10-01", "99", 1), "26201", "지정한 줄 없음"),
                              (("2026-10-20", "1", 2), "26201", "원가·매출 줄이 아님")])

    def test_conflicting_duplicate_rows_are_both_ignored(self):
        overrides, notes = self._links([["2026-10-29", "22", "1", "26221"], ["2026.10.29", "22", "1", "26220"]])
        self.assertEqual(overrides, {})
        self.assertEqual(notes, ["프로젝트연결.csv 같은 줄(2026-10-29 22-1)에 다른 프로젝트 지정 → 둘 다 무시"])

    def test_same_row_twice_with_same_project_is_one(self):
        overrides, notes = self._links([["2026-10-29", "22", "1", "26221"], ["2026-10-29", "22", "1", "26221"]])
        self.assertEqual(overrides, {KEY22: "26221"})
        self.assertEqual(notes, [])

    def test_excel_style_values_still_match(self):
        overrides, notes = self._links([["2026.10.29", "22.0", "1", "[26221]"], ["20261030", " 41 ", "1.0", " 26201 "]])
        self.assertEqual(overrides, {KEY22: "26221", ("2026-10-30", "41", 1): "26201"})
        self.assertEqual(notes, [])
        res, _, _, _ = cost_extra(self, overrides=overrides)
        self.assertEqual(by_no(res)["22"][0]["basis"], "수동")

    def test_extra_columns_are_ignored(self):
        overrides, notes = self._links([["2026-10-29", "22", "1", "26221", "메모"]],
                                       header=["전표일자", "전표번호", "줄", "프로젝트번호", "비고"])
        self.assertEqual((overrides, notes), ({KEY22: "26221"}, []))

    def test_bad_rows_are_ignored_with_the_file_line_number(self):
        overrides, notes = self._links([["2026-10-29", "22", "1", "26221"], ["2026-10-30", "41", "x", "26201"],
                                        ["아님", "41", "1", "26201"], ["2026-10-30", "", "1", "26201"],
                                        ["2026-10-30", "41", "0", "26201"], ["2026-10-30", "41", "1", ""]])
        self.assertEqual(overrides, {KEY22: "26221"})
        self.assertEqual(notes, [
            "프로젝트연결.csv 3번째 줄: 줄 값이 1 이상 정수가 아님 → 무시",
            "프로젝트연결.csv 4번째 줄: 전표일자를 날짜로 읽지 못함 → 무시",
            "프로젝트연결.csv 5번째 줄: 전표번호가 비어 있음 → 무시",
            "프로젝트연결.csv 6번째 줄: 줄 값이 1 이상 정수가 아님 → 무시",
            "프로젝트연결.csv 7번째 줄: 프로젝트번호가 비어 있음 → 무시"])

    def test_file_without_required_columns_applies_nothing(self):
        overrides, notes = self._links([["2026-10-29", "22", "26221"]], header=["전표일자", "전표번호", "프로젝트번호"])
        self.assertEqual(overrides, {})
        self.assertTrue(any("필수 열 없음: 줄" in n for n in notes), notes)

    def test_manual_project_not_in_the_list_still_applies_with_a_note_in_the_label(self):
        L = mod("linking")
        res, _, _, _ = cost_extra(self, overrides={KEY22: "26999"})
        (ln,) = by_no(res)["22"]
        self.assertEqual((ln["project"], ln["basis"], ln["label"]),
                         ("26999", "수동", "수동 (프로젝트연결.csv · 프로젝트 목록에 없는 번호)"))

    def test_manual_beats_a_code(self):
        res, _, _, _ = cost_extra(self, overrides={("2026-10-20", "1", 1): "26220"})
        (ln,) = by_no(res)["1"]
        self.assertEqual((ln["project"], ln["basis"]), ("26220", "수동"))

    def test_read_links_does_not_write(self):
        L = mod("linking")
        input_dir = os.path.join(new_tmp(self), "입력")
        path = write_links_csv(input_dir, [["2026-10-29", "22", "1", "26221"]])
        with open(path, "rb") as f:
            before = f.read()
        before_names = sorted(os.listdir(input_dir))
        L.read_links(input_dir)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(sorted(os.listdir(input_dir)), before_names)

    def test_template_has_bom_and_only_the_header(self):
        path = os.path.join(ROOT, "입력양식", "프로젝트연결.csv")
        with open(path, "rb") as f:
            raw = f.read()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(raw.decode("utf-8-sig").splitlines()))
        self.assertEqual(rows, [mod("linking").LINK_COLUMNS])


# ───────────── Task 3: 매출 줄, 스냅숏 없음, 가리기 ─────────────
def setup_rev(test, projects=None, extra=None):
    L = mod("linking")
    books, reqs, projs = setup_cost(test, journal=FAKE_JOURNAL + REV_LINES, extra=extra, projects=projects)
    return L, books, reqs, projs


class TestLinkingRevenue(unittest.TestCase):
    def test_truth_5_labels_projects_and_summary(self):
        L, books, _, projects = setup_rev(self)
        res = L.link_revenue(books, projects, {})
        n = by_no(res)
        self.assertEqual(len(res["lines"]), 4)
        (a,) = n["30"]
        self.assertEqual((a["project"], a["basis"], a["label"], a["amount"], a["account_code"]),
                         ("26201", "코드", "코드 [26201]", 100000000, "41200"))
        (b,) = n["31"]
        self.assertEqual((b["project"], b["basis"], b["label"], b["amount"], b["request"]),
                         ("26203", "자동", "자동 (클라이언트·견적금액)", 75000000, None))
        (c,) = n["32"]
        self.assertEqual((c["project"], c["basis"], c["label"], c["amount"]),
                         (None, "미연결", "미연결 (코드 없음 · 클라이언트·견적금액 후보 0건)", 20000000))
        (d,) = n["38"]
        self.assertEqual((d["project"], d["basis"], d["amount"]), (None, "미연결", -1000000))
        self.assertEqual(cnt(res), {"수동": (0, 0), "코드": (1, 100000000), "자동": (1, 75000000), "미연결": (2, 19000000)})
        self.assertEqual(total(res), 194000000)
        self.assertEqual(res["used"], set())

    def test_revenue_total_is_every_revenue_line(self):
        L, books, _, projects = setup_rev(self)
        res = L.link_revenue(books, projects, {})
        rows = [r for r in books.journal if r["account_code"] == "41200"]
        self.assertEqual(len(res["lines"]), len(rows))
        self.assertEqual(total(res), sum((r["credit"] or 0) - (r["debit"] or 0) for r in rows))

    def test_two_candidates_stay_unlinked_with_the_count(self):
        twin = [list(r) for r in FAKE_PROJECTS] + [list(FAKE_PROJECTS[3])]
        twin[-1][0], twin[-1][5] = "26230", "[26230] 가상 전시부스 둘째"
        L, books, _, projects = setup_rev(self, projects=twin)
        res = L.link_revenue(books, projects, {})
        (b,) = by_no(res)["31"]
        self.assertEqual((b["project"], b["basis"], b["label"], b["candidates"]),
                         (None, "미연결", "미연결 (클라이언트·견적금액 후보 2건)", 2))
        self.assertEqual(total(res), 194000000)

    def test_duplicate_key_project_is_not_a_candidate(self):
        dup = [list(r) for r in FAKE_PROJECTS] + [list(FAKE_PROJECTS[3])]
        L, books, _, projects = setup_rev(self, projects=dup)
        self.assertTrue(projects["26203"]["dup"])
        (b,) = by_no(L.link_revenue(books, projects, {}))["31"]
        self.assertEqual((b["basis"], b["label"]), ("미연결", "미연결 (코드 없음 · 클라이언트·견적금액 후보 0건)"))

    def test_other_client_or_other_amount_is_no_candidate(self):
        other = [list(r) for r in FAKE_PROJECTS]
        other[3][11] = "76,000,000"
        L, books, _, projects = setup_rev(self, projects=other)
        self.assertEqual(by_no(L.link_revenue(books, projects, {}))["31"][0]["basis"], "미연결")

    def test_code_not_in_the_project_list_is_named(self):
        line = [_jl(dt.date(2026, 10, 29), 39, "41200", "수입수수료", None, 5000000, "가상고객Z", "[26998] 없는 행사"),
                _jl(dt.date(2026, 10, 29), 39, "10800", "수입수수료미수금", 5000000, None, "가상고객Z", "[26998] 없는 행사")]
        L = mod("linking")
        books, _, projects = setup_cost(self, journal=FAKE_JOURNAL + line)
        (ln,) = by_no(L.link_revenue(books, projects, {}))["39"]
        self.assertEqual(ln["label"], "미연결 (코드 26998 프로젝트 목록에 없음 · 클라이언트·견적금액 후보 0건)")

    def test_manual_row_wins_and_costs_ignore_it(self):
        L, books, reqs, projects = setup_rev(self)
        key = ("2026-10-28", "32", 2)
        res = L.link_revenue(books, projects, {key: "26220"})
        (c,) = by_no(res)["32"]
        self.assertEqual((c["project"], c["basis"], c["label"]), ("26220", "수동", "수동 (프로젝트연결.csv)"))
        self.assertEqual(res["used"], set([key]))
        self.assertEqual(cnt(res), {"수동": (1, 20000000), "코드": (1, 100000000), "자동": (1, 75000000), "미연결": (1, -1000000)})
        costs = L.link_costs(books, reqs, projects, {key: "26220"})
        self.assertEqual(costs["used"], set())
        self.assertEqual(L.unused_links(books, {key: "26220"}, costs["used"]), [(key, "26220", "원가·매출 줄이 아님")])
        both = costs["used"] | res["used"]
        self.assertEqual(L.unused_links(books, {key: "26220"}, both), [])

    def test_manual_beats_a_code_on_revenue(self):
        L, books, _, projects = setup_rev(self)
        key = ("2026-09-15", "30", 2)
        (a,) = by_no(L.link_revenue(books, projects, {key: "26221"}))["30"]
        self.assertEqual((a["project"], a["basis"]), ("26221", "수동"))

    def test_unknown_revenue_amount_is_unknown_not_zero(self):
        blank = [_jl(dt.date(2026, 10, 29), 39, "41200", "수입수수료", None, None, "가상고객D", "금액 빈칸")]
        L = mod("linking")
        books, _, projects = setup_cost(self, journal=FAKE_JOURNAL + blank)
        res = L.link_revenue(books, projects, {})
        (ln,) = by_no(res)["39"]
        self.assertEqual((ln["amount"], ln["basis"], ln["label"]), (None, "미연결", "미연결 (금액 미확인)"))
        self.assertEqual(res["summary"]["미연결"], {"count": 1, "sum": 0, "unknown": 1})

    def test_revenue_codes_come_from_the_argument(self):
        L, books, _, projects = setup_rev(self)
        self.assertEqual(L.link_revenue(books, projects, {}, revenue_codes=("99999",))["lines"], [])
        res = L.link_revenue(books, projects, {}, revenue_codes=("10800",))
        self.assertEqual(set(ln["account_code"] for ln in res["lines"]), {"10800"})

    def test_pure_and_order_independent(self):
        import copy
        L, books, _, projects = setup_rev(self)
        before = (copy.deepcopy(books.journal), copy.deepcopy(projects))
        res = L.link_revenue(books, projects, {})
        self.assertEqual((books.journal, projects), before)
        books2, _, projects2 = setup_cost(self, journal=list(reversed(FAKE_JOURNAL + REV_LINES)))
        got = L.link_revenue(books2, projects2, {})
        pick = lambda r: sorted((x["no"], x["amount"], x["project"], x["basis"], x["label"]) for x in r["lines"])
        self.assertEqual(pick(got), pick(res))


class TestLinkingNoSnapshot(unittest.TestCase):
    def test_projects_of_none_and_costs_accept_codes_as_is(self):
        L = mod("linking")
        self.assertEqual(len(L.projects_of(None)), 0)
        books, reqs, _ = setup_cost(self, journal=FAKE_JOURNAL + LINK_EXTRA)
        res = L.link_costs(books, reqs, L.projects_of(None), {})
        n = by_no(res)
        (b,) = n["23"]
        self.assertEqual((b["project"], b["basis"], b["label"]), ("26999", "코드", "코드 [26999] (프로젝트 목록 없음)"))
        (a,) = n["1"]
        self.assertEqual((a["project"], a["basis"], a["label"]), ("26201", "코드", "코드 [26201] (프로젝트 목록 없음)"))
        self.assertEqual(res["summary"]["자동"], {"count": 0, "sum": 0, "unknown": 0})
        self.assertEqual(n["40"][0]["label"], "미연결 (코드 없음 · 프로젝트 목록 없음)")
        self.assertEqual(n["22"][0]["basis"], "미연결")
        self.assertEqual(total(res), 251800000)

    def test_no_line_is_linked_automatically_even_with_requests(self):
        L = mod("linking")
        books, reqs, _ = setup_cost(self, journal=FAKE_JOURNAL + LINK_EXTRA)
        self.assertTrue(any(r["번호"] == "6001" for r in reqs))
        res = L.link_costs(books, reqs, {}, {})
        self.assertEqual([ln["label"] for ln in res["lines"] if ln["basis"] == "자동"], [])

    def test_manual_without_snapshot_uses_the_plain_label(self):
        L = mod("linking")
        books, reqs, _ = setup_cost(self, journal=FAKE_JOURNAL)
        res = L.link_costs(books, reqs, {}, {KEY22: "26221"})
        self.assertEqual(by_no(res)["22"][0]["label"], "수동 (프로젝트연결.csv)")

    def test_revenue_without_snapshot(self):
        L = mod("linking")
        books, _, _ = setup_cost(self, journal=FAKE_JOURNAL + REV_LINES)
        res = L.link_revenue(books, L.projects_of(None), {})
        n = by_no(res)
        self.assertEqual((n["30"][0]["project"], n["30"][0]["basis"], n["30"][0]["label"]),
                         ("26201", "코드", "코드 [26201] (프로젝트 목록 없음)"))
        self.assertEqual(n["31"][0]["basis"], "미연결")
        self.assertEqual(n["31"][0]["label"], "미연결 (코드 없음 · 프로젝트 목록 없음)")
        self.assertEqual(res["summary"]["자동"]["count"], 0)
        self.assertEqual(total(res), 194000000)

    def test_rrn_in_request_name_and_memo_is_masked(self):
        L = mod("linking")
        extra = [["6101", "[26201] 강사 900101-1234567", "가상강사", "2026-10-20 09:00:00", "2026-11-20", "800,000", "",
                  "홍길동", "승인", "승인", "승인"]]
        tmp = new_tmp(self)
        snap = link_snapshot(os.path.join(tmp, "s"), extra=extra)
        reqs = L.requests_of(snap, ASOF, NOW)
        (r,) = [x for x in reqs if x["번호"] == "6101"]
        self.assertEqual(r["name"], "[26201] 강사 ******-*******")
        self.assertEqual(r["code"], "26201")
        books = write_link_books(os.path.join(tmp, "b"), FAKE_JOURNAL)
        res = L.link_costs(books, reqs, L.projects_of(snap), {})
        (ln,) = by_no(res)["22"]
        self.assertIn("******-*******", ln["memo"])
        self.assertIsNone(re.search(r"\d{6}\s*[-.]?\s*\d{7}", repr(res["lines"])))
        # 가상강사 800,000 은 요청 6101 의 후보: 줄 22 가 자동 연결된다 (같은 거래처·금액·기간)
        self.assertEqual((ln["basis"], ln["request"], ln["project"]), ("자동", "6101", "26201"))
        self.assertIsNone(re.search(r"\d{6}\s*[-.]?\s*\d{7}", repr(reqs)))


class TestLinkingScope(unittest.TestCase):
    def _git(self, *args):
        import subprocess
        try:
            return subprocess.run(("git",) + args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  universal_newlines=True)
        except OSError:
            self.skipTest("git 없음")

    def test_approval_calc_data_unchanged_and_no_02_02_commit_touches_wehago(self):
        if self._git("rev-parse", "--verify", "-q", "cbc5497^{commit}").returncode != 0:
            self.skipTest("cbc5497 없음")
        diff = self._git("diff", "--quiet", "cbc5497", "--", "ceo_report/approval.py", "ceo_report/calc.py", "ceo_report/data.py")
        self.assertEqual(diff.returncode, 0)
        log = self._git("log", "--format=%s", "cbc5497..HEAD", "--", "ceo_report/wehago.py").stdout
        self.assertNotIn("02-02", log)


if __name__ == "__main__":
    unittest.main()
