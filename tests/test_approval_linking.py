"""승인 화면의 프로젝트 연결(D-47) 시험 (Phase 2, 계획 02-08).

승인 검토 화면의 프로젝트별 (도) 원가와 프로젝트 미연결 원가가 월간 보고와 같은 linking.py 규칙(D-38)을 쓰는지 본다.
모든 장부·스냅숏·입력 폴더는 시험 때 임시 폴더에 가상 자료로 만든다. 실제 입력/·수집/ 폴더와 실제 WEHAGO 파일은 열지 않는다.
다른 시험 파일에서는 함수와 상수만 가져온다 (TestCase 클래스를 가져오면 시험이 두 번 돈다).
"""
import ast
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

from sample_input import SAMPLE, refresh as refresh_sample  # noqa: E402
from test_approval import (ASOF, NOW, edit_csv, load_approval_cli, sample_copy, set_setting,  # noqa: E402
                           write_fake_snapshot)
from test_approval_wehago import body_rows, cells, code_row, new_tmp, T  # noqa: E402
from test_linking import LINK_EXTRA, LINK_REQUESTS, setup_cost, write_links_csv  # noqa: E402
from test_wehago import FAKE_JOURNAL, _jl, write_fake_books  # noqa: E402


def mod(name):
    return importlib.import_module("ceo_report." + name)


def setUpModule():
    refresh_sample()  # 샘플은 임시 폴더에 쓴다 (실제 입력 폴더를 건드리지 않음)


LINK_JOURNAL = list(FAKE_JOURNAL) + list(LINK_EXTRA)
LINK_COST_TOTAL = 251800000   # LINK 가상 장부의 (도) 원가 줄 합 (계획 02-02 요약)


def work_input(test, link_days=None, links=None):
    """샘플 입력 폴더의 복사본. link_days 는 설정.csv 변환_자동연결일수, links 는 프로젝트연결.csv 줄 목록."""
    folder = sample_copy(test)
    if link_days is not None:
        edit_csv(folder, "설정.csv", lambda rows: set_setting(rows, "변환_자동연결일수", str(link_days)))
    if links is not None:
        write_links_csv(folder, links)
    return folder


def screen(test, input_dir=None, journal=None, extra=LINK_REQUESTS):
    """가상 장부와 가상 스냅숏(+ LINK 요청)으로 make_screen 을 돌린다 -> (page, A, tmp). input_dir 기본값은 샘플 입력 폴더."""
    tmp = new_tmp(test)
    write_fake_books(os.path.join(tmp, "위하고"), journal=LINK_JOURNAL if journal is None else journal)
    snap = write_fake_snapshot(os.path.join(tmp, "수집"), extra=extra)
    path, A = load_approval_cli().make_screen(input_dir or SAMPLE, os.path.join(tmp, "출력"), snap, ASOF, NOW, False,
                                              wehago_dir=os.path.join(tmp, "위하고"))
    with open(path, encoding="utf-8") as f:
        return f.read(), A, tmp


def project_costs_of(A):
    """{프로젝트 코드: 원가} (승인 화면 프로젝트 표)"""
    return dict((r["code"], r["cost"]) for r in A["xchk"]["projects"])


def table_costs(page):
    """{코드: 화면에 보이는 WEHAGO (도) 원가 글자} (xchk-projects 표)"""
    return dict((cells(r)[0], cells(r)[4]) for r in body_rows(page, "xchk-projects"))


def cost_total(A):
    x = A["xchk"]
    rows = sum(r["cost"] or 0 for r in x["projects"])
    return rows + (x["unlinked"]["sum"] or 0)


# ───────────── Task 1 (tracer): LINK 장부 → approval.build(input_dir) → link_costs → project_costs(links) → 승인 화면 ─────────────
class TestApprovalLinking(unittest.TestCase):
    def link_result(self, overrides=None, journal=None):
        books, requests, projects = setup_cost(self, journal=LINK_JOURNAL if journal is None else journal)
        result = mod("linking").link_costs(books, requests, projects, overrides or {})
        return books, projects, result

    # --- truth 1: wehago.project_costs(books, keys, links=None) ---
    def test_project_costs_without_links_is_the_code_only_result_of_01_1(self):
        books, projects, _ = self.link_result(journal=FAKE_JOURNAL)
        wehago = mod("wehago")
        keys = list(projects)
        plain = wehago.project_costs(books, keys)
        again = wehago.project_costs(books, keys, links=None)
        self.assertEqual(plain, again)
        self.assertEqual(dict((k, v["cost"]) for k, v in plain["by_code"].items()),
                         {"26201": 40000000, "26220": 158000000, "26221": 5400000, "26203": 45000000})
        self.assertEqual((plain["unlinked"]["count"], plain["unlinked"]["sum"]), (2, 1100000))
        for item in plain["by_code"]["26201"]["lines"]:
            self.assertEqual(sorted(item), ["amount", "date", "memo", "vendor"])  # 01.1 모양 그대로 (basis 없음)

    def test_links_put_every_linked_line_under_its_project_and_the_rest_in_unlinked(self):
        books, projects, result = self.link_result()
        pc = mod("wehago").project_costs(books, list(projects), links=result)
        self.assertEqual(dict((k, v["cost"]) for k, v in pc["by_code"].items()),
                         {"26201": 40000000, "26220": 158200000, "26221": 5400000, "26203": 45000000})
        self.assertEqual((pc["unlinked"]["count"], pc["unlinked"]["sum"], pc["unlinked"]["unknown"]), (6, 3200000, 0))
        self.assertIn("숙박 1", [i["memo"] for i in pc["unlinked"]["lines"]])
        self.assertNotIn("조명 추가", [i["memo"] for i in pc["unlinked"]["lines"]])  # 전표 40 은 지급요청 6001 로 연결됨
        linked = [i for i in pc["by_code"]["26220"]["lines"] if i["request"] == "6001"]
        self.assertEqual(len(linked), 1)
        self.assertEqual((linked[0]["basis"], linked[0]["amount"], linked[0]["vendor"]), ("자동", 200000, "가상조명"))
        self.assertEqual(linked[0]["label"], "자동 (지급요청 6001)")

    def test_every_item_keeps_date_vendor_memo_amount_and_adds_basis_label_request(self):
        books, projects, result = self.link_result()
        pc = mod("wehago").project_costs(books, list(projects), links=result)
        items = [i for v in pc["by_code"].values() for i in v["lines"]] + pc["unlinked"]["lines"]
        self.assertEqual(len(items), len(result["lines"]))
        for i in items:
            self.assertEqual(sorted(i), ["amount", "basis", "date", "label", "memo", "request", "vendor"])
        self.assertEqual(sorted(set(i["basis"] for i in pc["unlinked"]["lines"])), ["미연결"])
        self.assertNotIn("미연결", set(i["basis"] for v in pc["by_code"].values() for i in v["lines"]))

    def test_a_key_outside_the_project_list_still_holds_its_lines(self):
        books, projects, result = self.link_result({("2026-10-29", "22", 1): "26888"})
        pc = mod("wehago").project_costs(books, list(projects), links=result)
        self.assertIn("26888", pc["by_code"])
        self.assertEqual(pc["by_code"]["26888"]["cost"], 800000)
        self.assertEqual(pc["unlinked"]["count"], 5)
        self.assertEqual(pc["unlinked"]["sum"], 2400000)

    def test_links_on_a_book_that_is_not_ok_change_nothing(self):
        wehago = mod("wehago")
        pc = wehago.project_costs(wehago.Books(), ["26201"], links={"lines": []})
        self.assertEqual(pc["by_code"], {})
        self.assertEqual(pc["unlinked"]["count"], 0)

    def test_sums_keep_ssum_or_none_when_a_linked_line_has_no_amount(self):
        journal = list(FAKE_JOURNAL) + [_jl(dt.date(2026, 10, 30), 60, "61101", "행사외주비(도)", None, None, "가상금액모름",
                                            "[26201] 금액 모름")]
        books, projects, result = self.link_result(journal=journal)
        pc = mod("wehago").project_costs(books, list(projects), links=result)
        self.assertEqual(pc["by_code"]["26201"]["unknown"], 1)
        self.assertEqual(pc["by_code"]["26201"]["cost"], 40000000)   # 모르는 줄은 0으로 더하지 않고 개수로 센다

    # --- truth 2, 3 (기본 설정) ---
    def test_the_approval_screen_shows_the_auto_linked_cost_on_26220(self):
        page, A, _ = screen(self)
        self.assertEqual(project_costs_of(A), {"26201": 40000000, "26220": 158200000, "26221": 5400000, "26203": 45000000})
        self.assertEqual(code_row(page, "xchk-projects", "26220")[4], "158,200,000")
        self.assertEqual(table_costs(page), {"26201": "40,000,000", "26220": "158,200,000", "26221": "5,400,000",
                                             "26203": "45,000,000"})

    def test_the_unlinked_panel_has_six_lines_3200000(self):
        page, A, _ = screen(self)
        u = A["xchk"]["unlinked"]
        self.assertEqual((u["count"], u["sum"]), (6, 3200000))
        self.assertTrue(T(page, "xchk-unlinked").startswith("프로젝트 미연결 원가 6건 3,200,000"), T(page, "xchk-unlinked"))

    def test_build_without_input_dir_equals_build_with_a_folder_that_has_no_link_file_and_no_settings(self):
        tmp = new_tmp(self)
        write_fake_books(os.path.join(tmp, "위하고"), journal=LINK_JOURNAL)
        snap = mod("snapshot").read_snapshot(write_fake_snapshot(os.path.join(tmp, "수집"), extra=LINK_REQUESTS))
        d = mod("data").load(SAMPLE)
        wdir = os.path.join(tmp, "위하고")
        approval = mod("approval")
        plain = approval.build(d, snap, ASOF, NOW, wdir)
        empty = os.path.join(tmp, "빈입력")
        os.makedirs(empty)
        with_dir = approval.build(d, snap, ASOF, NOW, wdir, input_dir=empty)
        sample = approval.build(d, snap, ASOF, NOW, wdir, input_dir=SAMPLE)
        for A in (with_dir, sample):
            self.assertEqual(plain["xchk"]["projects"], A["xchk"]["projects"])
            self.assertEqual(plain["xchk"]["unlinked"], A["xchk"]["unlinked"])
        self.assertEqual(project_costs_of(plain)["26220"], 158200000)

    def test_make_screen_passes_its_input_folder_to_build(self):
        # 설정.csv 변환_자동연결일수 200 은 입력 폴더를 build 에 넘겨야만 화면에 닿는다 (전표 41 이 지급요청 6005 로 연결, 계획 truth 3)
        page, A, _ = screen(self, input_dir=work_input(self, link_days=200))
        self.assertEqual(project_costs_of(A)["26201"], 41000000)
        self.assertEqual(code_row(page, "xchk-projects", "26201")[4], "41,000,000")

    def test_the_input_dir_keyword_exists_and_defaults_to_none(self):
        import inspect
        sig = inspect.signature(mod("approval").build)
        self.assertIn("input_dir", sig.parameters)
        self.assertIsNone(sig.parameters["input_dir"].default)
        self.assertIn("links", inspect.signature(mod("wehago").project_costs).parameters)

    def test_no_module_level_import_of_linking_or_convert_in_approval_and_wehago(self):
        for name in ("approval.py", "wehago.py"):
            with open(os.path.join(ROOT, "ceo_report", name), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in tree.body:
                names = []
                if isinstance(node, ast.ImportFrom):
                    names = [node.module or ""] + [a.name for a in node.names]
                elif isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                for n in names:
                    self.assertNotIn("linking", n, name)
                    self.assertNotIn("convert", n, name)


if __name__ == "__main__":
    unittest.main()
