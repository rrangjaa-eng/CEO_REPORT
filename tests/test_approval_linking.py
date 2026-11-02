"""승인 화면의 프로젝트 연결(D-47) 시험 (Phase 2, 계획 02-08).

승인 검토 화면의 프로젝트별 (도) 원가와 프로젝트 미연결 원가가 월간 보고와 같은 linking.py 규칙(D-38)을 쓰는지 본다.
모든 장부·스냅숏·입력 폴더는 시험 때 임시 폴더에 가상 자료로 만든다. 실제 입력/·수집/ 폴더와 실제 WEHAGO 파일은 열지 않는다.
다른 시험 파일에서는 함수와 상수만 가져온다 (TestCase 클래스를 가져오면 시험이 두 번 돈다).
"""
import ast
import csv
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
from test_approval import (ASOF, NOW, edit_csv, element_html, load_approval_cli, sample_copy,  # noqa: E402
                           set_setting, write_fake_snapshot)
from test_approval_wehago import body_rows, cells, code_row, new_tmp, T  # noqa: E402
from test_convert_xchk import write_xchk  # noqa: E402
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


def screen(test, input_dir=None, journal=None, extra=LINK_REQUESTS, books=True):
    """가상 장부와 가상 스냅숏(+ LINK 요청)으로 make_screen 을 돌린다 -> (page, A, tmp). input_dir 기본값은 샘플 입력 폴더.
    books=False 면 위하고 폴더가 비어 있다 (장부 '자료 없음')."""
    tmp = new_tmp(test)
    if books:
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


# ───────────── Task 2: 수동 연결·설정·목록 밖 키·연결 열·01.1 기대값 ─────────────
FAKE_ONLY = dict(journal=FAKE_JOURNAL, extra=None)   # 01.1 가상 장부와 가상 스냅숏 그대로


def unlinked_rows(page):
    return [cells(r) for r in body_rows(page, "xchk-unlinked")]


def unlinked_nos(A):
    """미연결 줄의 적요 (전표 22·23·41~44 를 가려내는 데 쓴다)"""
    return [i["memo"] for i in A["xchk"]["unlinked"]["lines"]]


MANUAL_22 = [["2026-10-29", "22", "1", "26221"]]
LINES_UNLINKED_DEFAULT = ["가상 개인강사 ******-******* 강사료", "[26999] 가상 기타 행사", "케이터링", "숙박 1", "숙박 2", "음향 추가"]


class TestApprovalLinkingCases(unittest.TestCase):
    def test_default_unlinked_panel_lists_the_lines_of_slips_22_23_41_42_43_44(self):
        page, A, _ = screen(self)
        self.assertEqual(unlinked_nos(A), LINES_UNLINKED_DEFAULT)
        self.assertEqual([r[3] for r in unlinked_rows(page)],
                         ["800,000", "300,000", "500,000", "300,000", "300,000", "1,000,000"])

    def test_link_days_200_moves_slip_41_to_26201(self):
        page, A, _ = screen(self, input_dir=work_input(self, link_days=200))
        self.assertEqual(project_costs_of(A), {"26201": 41000000, "26220": 158200000, "26221": 5400000, "26203": 45000000})
        u = A["xchk"]["unlinked"]
        self.assertEqual((u["count"], u["sum"]), (5, 2200000))
        self.assertTrue(T(page, "xchk-unlinked").startswith("프로젝트 미연결 원가 5건 2,200,000"), T(page, "xchk-unlinked"))
        self.assertNotIn("음향 추가", unlinked_nos(A))

    def test_a_manual_link_of_slip_22_to_26221(self):
        page, A, _ = screen(self, input_dir=work_input(self, links=MANUAL_22))
        self.assertEqual(project_costs_of(A)["26221"], 6200000)
        self.assertEqual(code_row(page, "xchk-projects", "26221")[4], "6,200,000")
        u = A["xchk"]["unlinked"]
        self.assertEqual((u["count"], u["sum"]), (5, 2400000))
        self.assertTrue(T(page, "xchk-unlinked").startswith("프로젝트 미연결 원가 5건 2,400,000"), T(page, "xchk-unlinked"))
        self.assertNotIn("가상 개인강사 ******-******* 강사료", unlinked_nos(A))
        line = [i for p in A["xchk"]["projects"] if p["code"] == "26221" for i in [p]][0]
        self.assertEqual(line["cost"], 6200000)

    def test_a_manual_link_to_a_key_outside_the_list_adds_a_row_and_keeps_the_cost(self):
        page, A, _ = screen(self, input_dir=work_input(self, links=[["2026-10-29", "22", "1", "26888"]]))
        codes = [cells(r)[0] for r in body_rows(page, "xchk-projects")]
        self.assertEqual(codes, ["26201", "26220", "26221", "26203", "26888"])   # 목록 프로젝트 뒤에
        self.assertEqual(code_row(page, "xchk-projects", "26888"),
                         ["26888", "(프로젝트 목록에 없음)", "미확인", "판단 불가", "800,000", "판단 불가", "판단 불가"])
        row = [r for r in A["xchk"]["projects"] if r["code"] == "26888"][0]
        self.assertEqual((row["budget"], row["requested"], row["cost"]), (None, None, 800000))
        self.assertEqual(A["xchk"]["projects_without_cost"], 0)
        u = A["xchk"]["unlinked"]
        self.assertEqual((u["count"], u["sum"]), (5, 2400000))
        self.assertEqual(cost_total(A), LINK_COST_TOTAL)

    def test_rows_plus_unlinked_equal_the_books_total_in_every_case(self):
        cases = [("default", None), ("link-days 200", work_input(self, link_days=200)),
                 ("manual 22 -> 26221", work_input(self, links=MANUAL_22)),
                 ("manual 22 -> 26888", work_input(self, links=[["2026-10-29", "22", "1", "26888"]]))]
        for label, folder in cases:
            page, A, _ = screen(self, input_dir=folder)
            self.assertEqual(cost_total(A), LINK_COST_TOTAL, label)

    def test_the_01_1_fixtures_keep_their_numbers(self):
        page, A, _ = screen(self, **FAKE_ONLY)
        self.assertEqual(project_costs_of(A), {"26201": 40000000, "26220": 158000000, "26221": 5400000, "26203": 45000000})
        u = A["xchk"]["unlinked"]
        self.assertEqual((u["count"], u["sum"]), (2, 1100000))
        self.assertTrue(T(page, "xchk-unlinked").startswith("프로젝트 미연결 원가 2건 1,100,000"))
        self.assertEqual(unlinked_nos(A), ["가상 개인강사 ******-******* 강사료", "[26999] 가상 기타 행사"])

    def test_books_that_are_not_ok_are_not_linked(self):
        page, A, _ = screen(self, books=False, input_dir=work_input(self, links=MANUAL_22))
        self.assertEqual(A["xchk"]["state"], "자료 없음")
        self.assertIsNone(A["xchk"]["projects"])
        self.assertIsNone(A["xchk"]["unlinked"])
        self.assertIsNone(A["xchk"]["link_summary"])
        self.assertEqual(T(page, "xchk-unlinked"), "판단 불가(WEHAGO 자료 없음)")

    def test_a_bad_link_row_is_shown_in_the_approval_issues(self):
        folder = work_input(self, links=[["오늘", "22", "1", "26221"], ["2026-10-29", "23", "1", "26221"]])
        page, A, _ = screen(self, input_dir=folder)
        notes = [(f, m) for f, line, m in A["issues"] if f == "프로젝트연결.csv"]
        self.assertEqual(len(notes), 1)
        self.assertIn("전표일자를 날짜로 읽지 못함", notes[0][1])
        self.assertIn("전표일자를 날짜로 읽지 못함", T(page, "issues"))
        self.assertEqual(project_costs_of(A)["26221"], 5700000)   # 쓸 수 있는 줄(전표 23)만 적용

    def test_an_unusable_conversion_setting_is_shown_in_the_approval_issues(self):
        folder = work_input(self)
        edit_csv(folder, "설정.csv", lambda rows: set_setting(rows, "변환_자동연결일수", "많이"))
        page, A, _ = screen(self, input_dir=folder)
        notes = [m for f, line, m in A["issues"] if "변환_자동연결일수" in m]
        self.assertEqual(len(notes), 1)
        self.assertIn("사용할 수 없음", notes[0])
        self.assertEqual(project_costs_of(A)["26201"], 40000000)   # 기본 90일

    def test_a_missing_link_file_and_a_missing_settings_note_add_no_issue(self):
        tmp = new_tmp(self)
        write_fake_books(os.path.join(tmp, "위하고"), journal=LINK_JOURNAL)
        snap = mod("snapshot").read_snapshot(write_fake_snapshot(os.path.join(tmp, "수집"), extra=LINK_REQUESTS))
        d = mod("data").load(SAMPLE)
        approval = mod("approval")
        wdir = os.path.join(tmp, "위하고")
        plain = approval.build(d, snap, ASOF, NOW, wdir)
        empty = os.path.join(tmp, "빈입력")
        os.makedirs(empty)
        for folder in (SAMPLE, empty):
            self.assertEqual(approval.build(d, snap, ASOF, NOW, wdir, input_dir=folder)["issues"], plain["issues"])


class TestApprovalLinkingPanel(unittest.TestCase):
    def test_the_unlinked_table_has_a_last_column_with_each_lines_label(self):
        page, A, _ = screen(self)
        head = cells(re.search(r"<thead>(.*?)</thead>", element_html(page, "xchk-unlinked"), re.S).group(1))
        self.assertEqual(head, ["전표일자", "거래처", "적요", "금액(원)", "연결"])
        rows = unlinked_rows(page)
        self.assertTrue(all(len(r) == 5 for r in rows), rows)
        labels = dict((r[1], r[4]) for r in rows)
        self.assertEqual(labels["가상케이터링"], "미연결 (자동 연결 후보 2건: 지급요청 6002, 6003)")
        self.assertEqual(labels["가상음향"], "미연결 (코드 없음 · 자동 연결 후보 0건)")
        self.assertEqual(labels["가상기타"], "미연결 (코드 26999 프로젝트 목록에 없음 · 자동 연결 후보 0건)")
        self.assertEqual([r[4] for r in rows if r[1] == "가상숙박"],
                         ["미연결 (자동 연결 후보 공유: 지급요청 6004)"] * 2)

    def test_the_panel_line_keeps_its_start_and_adds_the_link_summary(self):
        page, A, _ = screen(self)
        t = T(page, "xchk-unlinked")
        self.assertTrue(t.startswith("프로젝트 미연결 원가 6건 3,200,000"), t)
        self.assertIn(" · 연결: 수동 0줄 · 코드 8줄 · 자동 1줄 · 미연결 6줄", t)
        s = A["xchk"]["link_summary"]
        self.assertEqual([(b, s[b]["count"]) for b in ("수동", "코드", "자동", "미연결")],
                         [("수동", 0), ("코드", 8), ("자동", 1), ("미연결", 6)])

    def test_the_link_summary_counts_a_manual_line(self):
        page, A, _ = screen(self, input_dir=work_input(self, links=MANUAL_22))
        self.assertIn(" · 연결: 수동 1줄 · 코드 8줄 · 자동 1줄 · 미연결 5줄", T(page, "xchk-unlinked"))

    def test_basis_rule_5_reads_the_d38_order(self):
        page, A, _ = screen(self)
        t = T(page, "basis")
        i5 = t.index("WEHAGO 규칙 5")
        rule = t[i5:]
        self.assertIn("프로젝트 원가 = 계정과목에 (도)가 있고", rule)
        order = [rule.index(w) for w in ("수동(프로젝트연결.csv)", "[프로젝트 코드]", "자동(거래처·금액·기간", "미연결")]
        self.assertEqual(order, sorted(order), order)
        self.assertIn("후보 하나", rule)
        for word in ("위험", "해결방안", "권고", "우려", "추천"):
            self.assertNotIn(word, t)

    def test_every_new_cell_is_masked_and_escaped(self):
        render = mod("approval_render")
        raw = "900101-1234567"
        line = {"date": dt.date(2026, 10, 29), "vendor": "<b>가상</b>", "memo": raw, "amount": 1000, "basis": "미연결",
                "label": "미연결 (%s <i>x</i>)" % raw, "request": None}
        A = {"xchk": {"state": "ok", "unlinked": {"count": 1, "sum": 1000, "unknown": 0, "lines": [line]},
                      "link_summary": dict((b, {"count": 0, "sum": 0, "unknown": 0}) for b in ("수동", "코드", "자동", "미연결"))}}
        html = render._unlinked_panel(A)
        self.assertNotIn(raw, html)
        self.assertIn("******-*******", html)
        self.assertNotIn("<i>x", html)
        self.assertIn("&lt;i&gt;x", html)
        self.assertNotIn("<b>가상", html)

    def test_the_real_screen_shows_no_social_security_number(self):
        page, A, _ = screen(self)
        self.assertIsNone(re.search(r"\d{6}\s*[-.]?\s*\d{7}", page))
        self.assertIn("가상 개인강사 ******-******* 강사료", element_html(page, "xchk-unlinked"))

    def test_an_empty_unlinked_panel_still_shows_the_link_summary(self):
        render = mod("approval_render")
        summary = dict((b, {"count": 3, "sum": 5, "unknown": 0}) for b in ("수동", "코드", "자동", "미연결"))
        summary["미연결"] = {"count": 0, "sum": 0, "unknown": 0}
        A = {"xchk": {"state": "ok", "unlinked": {"count": 0, "sum": 0, "unknown": 0, "lines": []}, "link_summary": summary}}
        html = render._unlinked_panel(A)
        self.assertIn("프로젝트 미연결 원가 0건", html)
        self.assertIn("연결: 수동 3줄 · 코드 3줄 · 자동 3줄 · 미연결 0줄", html)


# ───────────── Task 3: 승인 화면 = 월간 8번 (같은 장부·스냅숏·입력 폴더, 프로젝트별) ─────────────
def monthly_side(test, tmp, input_dir):
    """변환.py 가 하는 순서 그대로(convert.run 의 _build_tables): 같은 위하고 폴더·수집 폴더·입력 폴더에서
    build_links -> build_xchk -> write_table -> load_xchk. 월간 쪽 위하고대조.csv 는 입력 폴더가 아닌 새 임시 폴더에 쓴다."""
    convert, wehago = mod("convert"), mod("wehago")
    books = wehago.load_books(os.path.join(tmp, "위하고"), ASOF, None)
    assert books.state == "ok", books.reason
    snap, _ = convert.read_latest_snapshot(os.path.join(tmp, "수집"))
    cfg, _ = convert.read_config(input_dir)
    links = convert.build_links(books, cfg, snap, input_dir, ASOF, NOW)
    match = wehago.match_requests(books, links["requests"])
    project_table = mod("convert_projects").build_projects(links["projects"], links["revenue"],
                                                           convert.read_prev(input_dir, "프로젝트.csv"))
    table = mod("convert_xchk").build_xchk(books, links["costs"], links["revenue"], links["projects"], links["requests"],
                                           match, project_table.rows, convert.xchk_meta(books, snap, NOW), cfg,
                                           convert.read_bank(input_dir))
    out = os.path.join(tmp, "월간")
    path = write_xchk(out, table)
    return mod("convert_xchk").load_xchk(out), path


def csv_cell(path, kind, target, item):
    """위하고대조.csv 에서 (구분, 대상, 항목) 줄의 금액 칸 글자"""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["구분"] == kind and r["대상"] == target and r["항목"] == item]
    assert len(rows) == 1, (kind, target, item, len(rows))
    return rows[0]["금액"]


def both(test, input_dir=None, journal=None):
    """같은 장부·스냅숏·입력 폴더로 승인 화면과 월간 8번을 만든다 -> (page, A, monthly, monthly_csv_path)"""
    folder = input_dir or SAMPLE
    page, A, tmp = screen(test, input_dir=folder, journal=journal)
    monthly, path = monthly_side(test, tmp, folder)
    return page, A, monthly, path


class TestApprovalMonthlyEqual(unittest.TestCase):
    """RED 증거 (계획 W6): 이 클래스를 계획 02-08 의 연결 배선이 없는 커밋 6e3b9be(RED Task 1 tracer)에서 돌리면 7개 중 4개가 실패한다
    (26220 승인 158,000,000 대 월간 158,200,000, 미연결 7건 대 6건). 배선이 있는 Task 1·2 GREEN 뒤에는 모두 통과하므로
    Task 3 에서 고칠 코드는 없었고, 이 시험은 두 화면이 어긋나지 않게 지키는 시험이다."""
    CASES = (("default", {}), ("link-days 200", {"link_days": 200}), ("manual 22 -> 26221", {"links": MANUAL_22}),
             ("manual 22 -> 26888 (not in list)", {"links": [["2026-10-29", "22", "1", "26888"]]}))

    def assert_equal_per_project(self, page, A, monthly, label):
        self.assertEqual(monthly["state"], "ok", label)
        by_code = dict((r["code"], r) for r in A["xchk"]["projects"])
        seen = 0
        for p in monthly["projects"]:
            row = by_code.get(p["key"])
            if row is None:
                # 원가 줄이 없는 프로젝트는 승인 표에 없다 (01.1 규칙): 월간 건수가 0 일 때만 허용
                self.assertEqual((p["cost_lines"], p["cost"]), (0, 0), "%s %s: 승인 화면에 행이 없는데 월간 원가 줄이 있음" % (label, p["key"]))
                continue
            seen += 1
            self.assertEqual(row["cost"], p["cost"], "%s %s WEHAGO 원가" % (label, p["key"]))
            self.assertEqual(row["requested"], p["requested"], "%s %s 요청 누계" % (label, p["key"]))
            self.assertEqual(table_costs(page)[p["key"]], "미확인" if p["cost"] is None else "{:,}".format(p["cost"]),
                             "%s %s 화면 글자" % (label, p["key"]))
        self.assertEqual(seen, len(by_code), label)   # 승인 화면의 모든 행이 월간에도 있다

    def test_per_project_cost_and_request_total_equal_for_every_setting(self):
        for label, kw in self.CASES:
            page, A, monthly, _ = both(self, input_dir=work_input(self, **kw))
            self.assert_equal_per_project(page, A, monthly, label)

    def test_unlinked_count_and_sum_equal_the_monthly_unlinked_total(self):
        for label, kw in self.CASES:
            page, A, monthly, _ = both(self, input_dir=work_input(self, **kw))
            u = A["xchk"]["unlinked"]
            self.assertEqual(u["count"], monthly["unlinked"]["count"], label)
            self.assertEqual(u["sum"], monthly["unlinked"]["amount"], label)
            self.assertEqual(len(monthly["unlinked_lines"]), u["count"], label)
            self.assertEqual([i["amount"] for i in u["lines"]], [l["amount"] for l in monthly["unlinked_lines"]], label)

    def test_the_known_numbers_of_the_three_settings(self):
        expect = {"default": (26201, 40000000, 6, 3200000), "link-days 200": (26201, 41000000, 5, 2200000),
                  "manual 22 -> 26221": (26221, 6200000, 5, 2400000)}
        for label, kw in self.CASES[:3]:
            page, A, monthly, _ = both(self, input_dir=work_input(self, **kw))
            key, cost, count, total = expect[label]
            mp = dict((p["key"], p) for p in monthly["projects"])
            self.assertEqual(mp[str(key)]["cost"], cost, label)
            self.assertEqual((monthly["unlinked"]["count"], monthly["unlinked"]["amount"]), (count, total), label)
        # 26220 은 전표 40 이 지급요청 6001 로 자동 연결되어 월간도 158,200,000
        page, A, monthly, _ = both(self)
        self.assertEqual(dict((p["key"], p["cost"]) for p in monthly["projects"])["26220"], 158200000)

    def test_a_request_total_with_an_unknown_amount_is_blank_on_both_surfaces(self):
        page, A, monthly, path = both(self)
        row = [r for r in A["xchk"]["projects"] if r["code"] == "26221"][0]
        self.assertIsNone(row["requested"])                                       # 5106 의 금액을 모른다
        self.assertEqual(csv_cell(path, "프로젝트원가", "26221", "요청 누계"), "")   # 월간 CSV 칸은 빈칸 (A-6)
        self.assertIsNone([p for p in monthly["projects"] if p["key"] == "26221"][0]["requested"])
        self.assertEqual(code_row(page, "xchk-projects", "26221")[3], "판단 불가")

    def test_the_manual_link_to_a_key_outside_the_list_is_on_both_surfaces(self):
        page, A, monthly, path = both(self, input_dir=work_input(self, links=[["2026-10-29", "22", "1", "26888"]]))
        mp = dict((p["key"], p) for p in monthly["projects"])
        self.assertEqual((mp["26888"]["name"], mp["26888"]["cost"]), ("(프로젝트 목록에 없음)", 800000))
        self.assertIsNone(mp["26888"]["requested"])
        self.assertEqual(code_row(page, "xchk-projects", "26888")[:2], ["26888", "(프로젝트 목록에 없음)"])
        self.assertEqual(csv_cell(path, "프로젝트원가", "26888", "WEHAGO 원가"), "800000")

    def test_projects_without_a_cost_line_are_only_in_the_monthly_table_with_zero_lines(self):
        # 01.1 가상 장부(LINK 줄 없음)에서도 월간 표의 모든 프로젝트가 승인 표와 맞고, 빠진 프로젝트는 건수 0 이다
        page, A, monthly, _ = both(self, journal=FAKE_JOURNAL)
        self.assert_equal_per_project(page, A, monthly, "01.1 장부")
        missing = [p for p in monthly["projects"] if p["key"] not in project_costs_of(A)]
        for p in missing:
            self.assertEqual(p["cost_lines"], 0)

    def test_a_cost_line_without_an_amount_is_unknown_on_the_monthly_side_and_flagged_on_the_screen(self):
        journal = LINK_JOURNAL + [_jl(dt.date(2026, 10, 30), 60, "61101", "행사외주비(도)", None, None, "가상금액모름",
                                      "[26201] 금액 모름")]
        page, A, monthly, _ = both(self, journal=journal)
        mp = dict((p["key"], p) for p in monthly["projects"])
        self.assertIsNone(mp["26201"]["cost"])     # 월간: 모르는 줄이 하나라도 있으면 칸이 빈칸 (B5)
        row = [r for r in A["xchk"]["projects"] if r["code"] == "26201"][0]
        self.assertEqual(row["cost_unknown"], 1)   # 승인 화면(01.1 규칙): 확인된 금액 옆에 '외 금액 미확인 1줄'
        self.assertIn("외 금액 미확인 1줄", code_row(page, "xchk-projects", "26201")[4])
        for key in ("26220", "26221", "26203"):    # 나머지 프로젝트는 그대로 같다
            self.assertEqual(dict((r["code"], r["cost"]) for r in A["xchk"]["projects"])[key], mp[key]["cost"])


if __name__ == "__main__":
    unittest.main()
