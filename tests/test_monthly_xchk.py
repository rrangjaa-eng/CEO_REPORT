"""월간 보고 8번 'WEHAGO 기준 대조' 시험 (Phase 2, 계획 02-09, D-44 D-48 D-49).

모든 입력은 시험 때 임시 폴더에 만든다: 샘플 입력 복사본 + 02-06 가상 자료로 만든 위하고대조.csv.
실제 입력/·수집/ 폴더와 실제 WEHAGO 파일은 열지 않는다. 다른 시험 파일에서는 함수와 상수만 가져온다.
"""
import contextlib
import html as htmllib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import datetime as dt  # noqa: E402

from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import render  # noqa: E402
from sample_input import SAMPLE, refresh as refresh_sample  # noqa: E402
from test_convert_xchk import (BANK_BALANCES, BANK_TX, OPENING_CASH, cash_table, shared_inputs,  # noqa: E402
                               write_xchk, xchk_table)
from test_report import FORBIDDEN, load_cli, numbers_of, section  # noqa: E402

BASELINE = "cbc5497"
BASE_ASOF = "2026-10-31"
WEEKLY_ASOF = "2026-11-02"
MONTHLY_FILES = {"ceo": "%s_월간_대표보고.html", "mgmt": "%s_월간_경영관리보고.html"}
WEEKLY_FILES = {"ceo": "%s_주간_대표보고.html", "mgmt": "%s_주간_경영관리보고.html"}
STAMP = re.compile(r"작성 \d{4}-\d{2}-\d{2} \d{2}:\d{2}")

STATUS_TEXT = ("계산서 있음 3건 51,700,000 · 금액 차이 1건 160,500,000 · 계산서 없음 1건 264,000 · 이미 지급 1건 49,500,000 · "
               "연결 불가 3건 금액 판단 불가 (미확인 1건) · 판단 불가 0건")
PROJECT_TEXT = ("258,400,000 (4개 프로젝트 · 실행가 입력 3건 합계 610,000,000 · 실행가 빈칸 1건 · "
                "원가가 실행가보다 큰 프로젝트 0건)")
REVENUE_TEXT = ("194,000,000 · 프로젝트 연결 175,000,000 · 미연결 2줄 19,000,000 · "
                "계약금액 (수동 입력) 합계 530,000,000 (미등록 2건)")


def setUpModule():
    refresh_sample()  # 샘플은 임시 폴더에 쓴다 (실제 입력 폴더를 건드리지 않음)


def plain(markup):
    """태그를 떼고 HTML 글자를 풀어 보통 글자로."""
    return htmllib.unescape(re.sub(r"<[^>]+>", "", markup))


def write_raw(folder, table):
    """표를 가리지 않고 그대로 쓴다 (사람이 엑셀에서 고친 파일 흉내: 변환기가 가린 글자가 아닌 날 글자가 들어온 경우)."""
    import csv
    with open(os.path.join(folder, "위하고대조.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(table.columns)
        for row in table.rows:
            w.writerow([row.get(c, "") for c in table.columns])


def sample_folder(test, xchk=None, raw=False):
    """샘플 입력을 임시 폴더에 복사하고, 표(xchk)가 있으면 위하고대조.csv 로 쓴다. 폴더 경로를 돌려준다."""
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    folder = os.path.join(tmp, "입력")
    shutil.copytree(SAMPLE, folder)
    if xchk is not None:
        (write_raw if raw else write_xchk)(folder, xchk)
    return folder


def run_cli(test, folder, kind, asof, extra=()):
    """보고서.py 를 한 번 돌린다 -> (종료 코드, 표준 출력, {'ceo': html, 'mgmt': html}, 출력 폴더)."""
    out_dir = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, out_dir, True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = load_cli().main([kind, "--기준일", asof, "--입력", folder, "--출력", out_dir, "--pdf", "안함"] + list(extra))
    files = MONTHLY_FILES if kind in ("월간", "monthly") else WEEKLY_FILES
    pages = {}
    for mode, pattern in files.items():
        path = os.path.join(out_dir, pattern % asof)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                pages[mode] = f.read()
    return rc, buf.getvalue(), pages, out_dir


def summary_rows(page):
    """8번 요약 표 -> {이름: 보통 글자 값}."""
    start = page.index("<table id=\"xchk-summary\"")
    body = page[start:page.index("</table>", start)]
    return dict((plain(k), plain(v)) for k, v in re.findall(r"<tr><th>(.*?)</th><td[^>]*>(.*?)</td></tr>", body, re.S))


def section8(page):
    return page[page.index("<h2 id='s8'>"):]


def meta_line(page):
    m = re.search(r"<div class=\"meta xchk-meta\">(.*?)</div>", section8(page), re.S)
    return plain(m.group(1)) if m else None


def editions_ok(test, ceo, mgmt):
    """대표용 규칙: 금지어 없음, 숫자 동일."""
    for word in FORBIDDEN:
        test.assertNotIn(word, ceo, word)
    test.assertEqual(numbers_of(ceo), numbers_of(mgmt))


def pages_for(test, table, asof=BASE_ASOF, raw=False):
    """표(위하고대조.csv가 될 것)로 월간 보고를 한 번 만든다 -> {'ceo': html, 'mgmt': html}."""
    rc, out, pages, _ = run_cli(test, sample_folder(test, table, raw), "월간", asof)
    test.assertEqual(rc, 0)
    return pages


def table_cells(page, tid):
    """id 가 tid 인 표 -> [{머리글: 보통 글자}, ...] (본문 줄만, 합계 줄 포함)."""
    start = page.index('<table id="%s"' % tid)
    body = page[start:page.index("</table>", start)]
    head = [plain(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", body.split("</thead>")[0], re.S)]
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", body.split("</thead>")[1], re.S)
    return [dict(zip(head, [plain(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.S)])) for r in rows]


def detail_block(page):
    start = page.index("<div id='xchk-detail'>")
    return page[start:page.index("<!-- /xchk-detail -->", start)]


def with_rows(table, edit):
    """표의 줄 목록을 edit(rows)로 고친다 (표를 그대로 돌려줌)."""
    edit(table.rows)
    return table


def fact_row(kind, target="", name="", item="", amount="", count="", note=""):
    return {"구분": kind, "대상": target, "이름": name, "항목": item, "금액": amount, "건수": count, "비고": note}


DETAIL_IDS = ("xchk-status", "xchk-projects", "xchk-outside", "xchk-unlinked", "xchk-vendors-m", "xchk-revenue",
              "xchk-revenue-unlinked", "xchk-cash")


# ───────────── Task 1 (tracer): 위하고대조.csv -> 보고서.py 월간 -> 8번 요약 (두 판 모두) ─────────────
class TestMonthlySection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dirs = []
        tmp = tempfile.mkdtemp()
        cls.test_dirs.append(tmp)
        cls.folder = os.path.join(tmp, "입력")
        shutil.copytree(SAMPLE, cls.folder)
        write_xchk(cls.folder, xchk_table(shared_inputs()))
        out_dir = tempfile.mkdtemp()
        cls.test_dirs.append(out_dir)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cls.rc = load_cli().main(["월간", "--기준일", BASE_ASOF, "--입력", cls.folder, "--출력", out_dir, "--pdf", "안함"])
        cls.stdout = buf.getvalue()
        cls.pages = {}
        for mode, pattern in MONTHLY_FILES.items():
            with open(os.path.join(out_dir, pattern % BASE_ASOF), encoding="utf-8") as f:
                cls.pages[mode] = f.read()

    @classmethod
    def tearDownClass(cls):
        for d in cls.test_dirs:
            shutil.rmtree(d, True)

    def test_the_run_finishes_and_prints_no_facts_file_line(self):
        self.assertEqual(self.rc, 0)
        self.assertNotIn("위하고 대조 자료 없음", self.stdout)

    def test_heading_and_table_of_contents_link_in_both_editions(self):
        for mode, page in self.pages.items():
            with self.subTest(mode):
                self.assertIn("<h2 id='s8'>8. WEHAGO 기준 대조</h2>", page)
                self.assertIn('<a href="#s8">8. WEHAGO 기준 대조</a>', page)

    def test_section_8_comes_after_section_7(self):
        for page in self.pages.values():
            self.assertLess(page.index("<h2 id='s7'>"), page.index("<h2 id='s8'>"))

    def test_meta_line_has_book_date_snapshot_and_conversion_time(self):
        for mode, page in self.pages.items():
            with self.subTest(mode):
                self.assertEqual(meta_line(page), "장부 기준일 2026-10-31 · 인트라넷 스냅숏 20261102_000000 (수집 2026-11-02 00:00:00)"
                                 " · 변환 시각 2026-11-02 00:00:00")

    def test_summary_rows_have_the_known_labels_in_order(self):
        for mode, page in self.pages.items():
            with self.subTest(mode):
                self.assertEqual(list(summary_rows(page)), ["지급요청 대조", "프로젝트 (도)원가", "프로젝트 미연결 원가", "거래처 미지급",
                                                            "매출 (분개장)", "보통예금 (WEHAGO 10300)"])

    def test_payment_request_row_counts_by_status(self):
        for mode, page in self.pages.items():
            with self.subTest(mode):
                self.assertEqual(summary_rows(page)["지급요청 대조"], "9건 (%s)" % STATUS_TEXT)

    def test_project_cost_row(self):
        for mode, page in self.pages.items():
            with self.subTest(mode):
                self.assertEqual(summary_rows(page)["프로젝트 (도)원가"], PROJECT_TEXT)

    def test_unlinked_cost_row(self):
        for mode, page in self.pages.items():
            with self.subTest(mode):
                self.assertEqual(summary_rows(page)["프로젝트 미연결 원가"], "2줄 1,100,000")

    def test_vendor_row(self):
        for mode, page in self.pages.items():
            with self.subTest(mode):
                self.assertTrue(summary_rows(page)["거래처 미지급"].startswith("비교 9곳 · 차이 5곳 13,176,000 · 판단 불가 2곳"),
                                summary_rows(page)["거래처 미지급"])

    def test_revenue_row_with_manual_contract_label_and_unregistered_count(self):
        for mode, page in self.pages.items():
            with self.subTest(mode):
                self.assertEqual(summary_rows(page)["매출 (분개장)"], REVENUE_TEXT)

    def test_cash_row_without_opening_line_is_unknown_not_zero(self):
        for mode, page in self.pages.items():
            with self.subTest(mode):
                value = summary_rows(page)["보통예금 (WEHAGO 10300)"]
                self.assertTrue(value.startswith("증감 45,000,000 · 장부 잔액 판단 불가 (기초 잔액 줄 없음)"), value)

    def test_summary_is_identical_in_both_editions(self):
        self.assertEqual(summary_rows(self.pages["ceo"]), summary_rows(self.pages["mgmt"]))
        self.assertEqual(meta_line(self.pages["ceo"]), meta_line(self.pages["mgmt"]))

    def test_ceo_edition_has_no_detail_block_and_no_forbidden_word(self):
        ceo = self.pages["ceo"]
        self.assertNotIn("xchk-detail", ceo)
        for word in FORBIDDEN:
            self.assertNotIn(word, ceo, word)

    def test_numbers_of_is_equal_for_the_two_editions(self):
        editions_ok(self, self.pages["ceo"], self.pages["mgmt"])

    def test_check_editions_of_test_report_passes_with_the_facts_attached(self):
        from ceo_report.convert_xchk import load_xchk
        from test_report import check_editions
        R = compute(load(self.folder), "monthly", dt.date(2026, 10, 31))
        R["xchk"] = load_xchk(self.folder)
        check_editions(self, R)

    def test_weekly_has_no_section_8_and_no_link(self):
        rc, out, pages, _ = run_cli(self, self.folder, "주간", WEEKLY_ASOF)
        self.assertEqual(rc, 0)
        for page in pages.values():
            self.assertNotIn("id='s8'", page)
            self.assertNotIn("WEHAGO 기준 대조", page)
            self.assertNotIn("xchk", page)

    def test_the_report_reads_only_the_facts_file_never_collected_files(self):
        """보고서.py 와 render.py 는 수집/ 이나 WEHAGO 엑셀을 열지 않는다 (SRC-01)."""
        for name in ("보고서.py", os.path.join("ceo_report", "render.py")):
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                code = f.read()
            for word in ("수집", ".xlsx", "openpyxl"):
                self.assertNotIn(word, code, "%s: %s" % (name, word))
            self.assertIsNone(re.search(r"import\s+wehago|from\s+\S*wehago|\.wehago", code), name)

    def test_calc_and_data_are_unchanged_from_the_baseline(self):
        try:
            rc = subprocess.run(["git", "-C", ROOT, "diff", "--quiet", BASELINE, "--", "ceo_report/calc.py", "ceo_report/data.py"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
        except OSError:
            self.skipTest("git 없음")
        if rc not in (0, 1):
            self.skipTest("git 기준 커밋 %s 없음" % BASELINE)
        self.assertEqual(rc, 0)


# ───────────── Task 2: 경영관리용 상세 표, 모름·미등록 표시, 보통예금 줄 ─────────────
class TestMonthlyDetail(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dirs = []
        tmp = tempfile.mkdtemp()
        cls.dirs.append(tmp)
        folder = os.path.join(tmp, "입력")
        shutil.copytree(SAMPLE, folder)
        write_xchk(folder, xchk_table(shared_inputs()))
        out_dir = tempfile.mkdtemp()
        cls.dirs.append(out_dir)
        with contextlib.redirect_stdout(io.StringIO()):
            assert load_cli().main(["월간", "--기준일", BASE_ASOF, "--입력", folder, "--출력", out_dir, "--pdf", "안함"]) == 0
        cls.pages = {}
        for mode, pattern in MONTHLY_FILES.items():
            with open(os.path.join(out_dir, pattern % BASE_ASOF), encoding="utf-8") as f:
                cls.pages[mode] = f.read()

    @classmethod
    def tearDownClass(cls):
        for d in cls.dirs:
            shutil.rmtree(d, True)

    def test_management_edition_has_the_detail_block_with_all_tables_inside_it(self):
        page = self.pages["mgmt"]
        block = detail_block(page)
        self.assertEqual(page.count("<div id='xchk-detail'>"), 1)
        self.assertEqual(page.count("<!-- /xchk-detail -->"), 1)
        self.assertTrue(block.startswith("<div id='xchk-detail'>"))
        for tid in DETAIL_IDS:
            with self.subTest(tid):
                self.assertEqual(page.count('<table id="%s"' % tid), 1)
                self.assertIn('<table id="%s"' % tid, block)

    def test_the_block_is_closed_by_a_div_right_before_the_marker(self):
        page = self.pages["mgmt"]
        self.assertIn("</div><!-- /xchk-detail -->", page)
        start = page.index("<div id='xchk-detail'>")
        end = page.index("<!-- /xchk-detail -->")
        self.assertEqual(page[start:end].count("<div"), page[start:end].count("</div>"))

    def test_ceo_edition_has_no_detail_block_and_none_of_its_tables(self):
        ceo = self.pages["ceo"]
        self.assertNotIn("xchk-detail", ceo)
        for tid in DETAIL_IDS + ("xchk-cash-months",):
            self.assertNotIn(tid, ceo)
        self.assertIn('<table id="xchk-summary"', ceo)

    def test_the_summary_sits_outside_the_detail_block(self):
        page = self.pages["mgmt"]
        self.assertLess(page.index('<table id="xchk-summary"'), page.index("<div id='xchk-detail'>"))
        self.assertNotIn('<table id="xchk-summary"', detail_block(page))

    def test_numbers_of_ignores_the_detail_block(self):
        self.assertEqual(numbers_of(self.pages["ceo"]), numbers_of(self.pages["mgmt"]))
        self.assertNotEqual(re.findall(r"−?\d[\d,.]*", self.pages["ceo"]), re.findall(r"−?\d[\d,.]*", self.pages["mgmt"]))

    def test_status_table(self):
        rows = table_cells(self.pages["mgmt"], "xchk-status")
        self.assertEqual([r["요청 상태"] for r in rows], ["계산서 있음", "금액 차이", "계산서 없음", "이미 지급", "연결 불가", "판단 불가"])
        diff = rows[1]
        self.assertEqual((diff["인트라넷 요청 건수"], diff["인트라넷 요청 금액"], diff["WEHAGO 계산서 건수"], diff["WEHAGO 계산서 금액"]),
                         ("1건", "160,500,000", "1건", "165,000,000"))
        self.assertEqual(rows[0]["WEHAGO 계산서 금액"], "51,700,000")
        self.assertEqual((rows[2]["WEHAGO 계산서 건수"], rows[2]["WEHAGO 계산서 금액"]), ("-", "-"))
        self.assertEqual((rows[5]["인트라넷 요청 건수"], rows[5]["인트라넷 요청 금액"]), ("0건", "-"))

    def test_project_table(self):
        rows = dict((r["번호"], r) for r in table_cells(self.pages["mgmt"], "xchk-projects"))
        self.assertEqual(list(rows), ["26201", "26220", "26221", "26203"])
        a = rows["26201"]
        self.assertEqual((a["프로젝트"], a["WEHAGO 원가"], a["원가 줄"], a["실행가"], a["원가−실행가"]),
                         ("가상 컨퍼런스", "50,000,000", "2줄", "300,000,000", "−250,000,000"))
        self.assertEqual((a["요청 누계"], a["요청 건수"], a["요청 누계−원가"]), ("44,264,000", "2건", "−5,736,000"))
        b = rows["26220"]
        self.assertEqual((b["WEHAGO 원가"], b["실행가"], b["원가−실행가"], b["요청 누계"]),
                         ("158,000,000", "250,000,000", "−92,000,000", "166,000,000"))

    def test_outside_requests_table(self):
        rows = table_cells(self.pages["mgmt"], "xchk-outside")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["건수"], rows[0]["금액"]), ("1건", "2,200,000"))

    def test_unlinked_cost_lines_table_with_masked_memo(self):
        rows = table_cells(self.pages["mgmt"], "xchk-unlinked")
        lines = [r for r in rows if r["전표"] != "합계"]
        self.assertEqual([r["전표"] for r in lines], ["2026-10-29 22-1", "2026-10-29 23-1"])
        self.assertEqual((lines[0]["거래처"], lines[0]["금액"]), ("가상강사", "800,000"))
        self.assertIn("******-*******", lines[0]["적요"])
        self.assertEqual([r["금액"] for r in rows if r["전표"] == "합계"], ["1,100,000"])
        self.assertIn("전체 2줄 모두 표시", detail_block(self.pages["mgmt"]))

    def test_vendor_table(self):
        rows = dict((r["거래처"], r) for r in table_cells(self.pages["mgmt"], "xchk-vendors-m"))
        self.assertEqual(len(rows), 7 + 2)
        v = rows["㈜가상제작"]
        self.assertEqual((v["WEHAGO 미지급"], v["인트라넷 요청 건수"], v["인트라넷 요청 금액"], v["차이 (WEHAGO−요청)"]),
                         ("165,000,000", "1건", "160,500,000", "4,500,000"))
        self.assertEqual(rows["가상임대"]["차이 (WEHAGO−요청)"], "3,000,000")

    def test_revenue_table_with_manual_contract_amounts(self):
        rows = table_cells(self.pages["mgmt"], "xchk-revenue")
        by = dict((r["번호"], r) for r in rows)
        a = by["26201"]
        self.assertEqual((a["WEHAGO 매출"], a["매출 줄"], a["계약금액 (수동 입력)"], a["견적금액"]),
                         ("100,000,000", "1줄", "360,000,000", "420,000,000"))
        total = [r for r in rows if r["번호"] == "합계"][0]
        self.assertEqual((total["WEHAGO 매출"], total["계약금액 (수동 입력)"]), ("175,000,000", "530,000,000"))
        self.assertIn("미등록 2건", total["비고"])

    def test_unlinked_revenue_lines_table(self):
        rows = table_cells(self.pages["mgmt"], "xchk-revenue-unlinked")
        lines = [r for r in rows if r["전표"] != "합계"]
        self.assertEqual([(r["전표"], r["금액"]) for r in lines], [("2026-10-28 32-2", "20,000,000"), ("2026-10-29 38-1", "−1,000,000")])
        self.assertEqual([r["금액"] for r in rows if r["전표"] == "합계"], ["19,000,000"])

    def test_cash_tables(self):
        cash = dict((r["항목"], r) for r in table_cells(self.pages["mgmt"], "xchk-cash"))
        self.assertEqual(cash["WEHAGO 증감 (전체 기간)"]["금액"], "45,000,000")
        self.assertEqual(cash["WEHAGO 증감 (전체 기간)"]["건수"], "9줄")
        self.assertEqual(cash["WEHAGO 잔액 (장부 기준일)"]["금액"], "판단 불가")
        months = dict((r["월"], r) for r in table_cells(self.pages["mgmt"], "xchk-cash-months"))
        self.assertEqual(months["2026-10"]["WEHAGO 증감"], "57,000,000")
        self.assertEqual(months["2026-09"]["WEHAGO 증감"], "−12,000,000")


class TestMonthlyDetailLists(unittest.TestCase):
    def long_lines(self, n, kind):
        return [fact_row(kind, "2026-10-%02d 9-%d" % (i % 28 + 1, i), "가상거래처%02d" % i, "미연결 (코드 없음)", "%d" % (1000 * (i + 1)), "1",
                         "적요 %02d" % i) for i in range(n)]

    def test_21_unlinked_cost_lines_show_20_rows_and_the_count(self):
        table = xchk_table(shared_inputs())
        table.rows[:] = [r for r in table.rows if r["구분"] != "미연결원가줄"] + self.long_lines(21, "미연결원가줄")
        page = pages_for(self, table)["mgmt"]
        rows = [r for r in table_cells(page, "xchk-unlinked") if r["전표"] != "합계"]
        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[0]["거래처"], "가상거래처00")
        self.assertEqual(rows[-1]["거래처"], "가상거래처19")
        self.assertIn("전체 21줄 중 20줄 표시", detail_block(page))

    def test_21_unlinked_revenue_lines_show_20_rows_and_the_count(self):
        table = xchk_table(shared_inputs())
        table.rows[:] = [r for r in table.rows if r["구분"] != "매출미연결줄"] + self.long_lines(21, "매출미연결줄")
        page = pages_for(self, table)["mgmt"]
        rows = [r for r in table_cells(page, "xchk-revenue-unlinked") if r["전표"] != "합계"]
        self.assertEqual(len(rows), 20)
        self.assertIn("전체 21줄 중 20줄 표시", detail_block(page))

    def test_exactly_20_lines_are_all_shown_without_the_cut_text(self):
        table = xchk_table(shared_inputs())
        table.rows[:] = [r for r in table.rows if r["구분"] != "미연결원가줄"] + self.long_lines(20, "미연결원가줄")
        page = pages_for(self, table)["mgmt"]
        self.assertEqual(len([r for r in table_cells(page, "xchk-unlinked") if r["전표"] != "합계"]), 20)
        self.assertIn("전체 20줄 모두 표시", detail_block(page))
        self.assertNotIn("20줄 표시", detail_block(page))


def hostile_table():
    table = xchk_table(shared_inputs())

    def edit(rows):
        for r in rows:
            if r["구분"] == "프로젝트원가" and r["대상"] == "26201":
                r["이름"] = "<b>가상</b> 900101-1234567"
            if r["구분"] == "미연결원가줄" and r["대상"].endswith("22-1"):
                r["이름"], r["비고"] = "<script>alert(1)</script>", "메모 900101-1234567 & <i>x</i>"
            if r["구분"] == "거래처미지급" and r["이름"] == "가상임대":
                r["이름"], r["비고"] = "가상임대 900101 1234567", "<img src=x>"
            if r["구분"] == "기준" and r["항목"] == "인트라넷 스냅숏":
                r["비고"] = "스냅숏 900101-1234567 <u>"
    return with_rows(table, edit)


class TestMonthlyTextCells(unittest.TestCase):
    """모든 글자 칸은 esc(mask_rrn(...)) 를 지난다 (T-02-37, T-02-38)."""

    def test_detail_cells_and_meta_are_masked_and_escaped(self):
        for mode, page in pages_for(self, hostile_table(), raw=True).items():
            with self.subTest(mode):
                self.assertNotIn("900101", page)
                self.assertNotIn("1234567", page)
                self.assertNotIn("<script>alert(1)", page)
                self.assertNotIn("<img src=x>", page)
                self.assertNotIn("<b>가상</b>", page)
                self.assertNotIn("스냅숏 900101", page)
        mgmt = pages_for(self, hostile_table(), raw=True)["mgmt"]
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", mgmt)
        self.assertIn("******-*******", mgmt)


# ───────────── 모름은 0이 아니다, 계약금액은 수동 입력, 보통예금 ─────────────
def cash_pages(test, journal=None, bank=None, edit=None):
    x, table = cash_table(journal=journal, bank=bank)
    if edit:
        edit(table.rows)
    return pages_for(test, table)


class TestMonthlyUnknowns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dirs = []
        tmp = tempfile.mkdtemp()
        cls.dirs.append(tmp)
        folder = os.path.join(tmp, "입력")
        shutil.copytree(SAMPLE, folder)
        write_xchk(folder, xchk_table(shared_inputs()))
        out_dir = tempfile.mkdtemp()
        cls.dirs.append(out_dir)
        with contextlib.redirect_stdout(io.StringIO()):
            assert load_cli().main(["월간", "--기준일", BASE_ASOF, "--입력", folder, "--출력", out_dir, "--pdf", "안함"]) == 0
        cls.pages = {}
        for mode, pattern in MONTHLY_FILES.items():
            with open(os.path.join(out_dir, pattern % BASE_ASOF), encoding="utf-8") as f:
                cls.pages[mode] = f.read()

    @classmethod
    def tearDownClass(cls):
        for d in cls.dirs:
            shutil.rmtree(d, True)

    def test_unlinked_request_amount_is_unknown_with_the_unconfirmed_count(self):
        rows = dict((r["요청 상태"], r) for r in table_cells(self.pages["mgmt"], "xchk-status"))
        self.assertEqual(rows["연결 불가"]["인트라넷 요청 금액"], "판단 불가 (미확인 1건)")
        self.assertEqual(rows["연결 불가"]["인트라넷 요청 건수"], "3건")

    def test_request_total_of_a_project_with_an_unreadable_amount_is_unknown(self):
        rows = dict((r["번호"], r) for r in table_cells(self.pages["mgmt"], "xchk-projects"))
        p = rows["26221"]
        self.assertEqual(p["요청 누계"], "판단 불가 (미확인 1건)")
        self.assertEqual(p["요청 건수"], "2건")
        self.assertEqual(p["요청 누계−원가"], "판단 불가")
        self.assertEqual(p["실행가"], "판단 불가")
        self.assertEqual(p["원가−실행가"], "판단 불가")
        self.assertIn("실행가 빈칸", p["비고"])
        for key in ("요청 누계", "실행가", "원가−실행가", "요청 누계−원가"):
            self.assertNotEqual(p[key], "0")

    def test_blank_contract_amount_reads_unregistered_and_the_label_says_manual_input(self):
        page = self.pages["mgmt"]
        rows = dict((r["번호"], r) for r in table_cells(page, "xchk-revenue"))
        self.assertEqual(rows["26220"]["계약금액 (수동 입력)"], "미등록")
        self.assertEqual(rows["26221"]["계약금액 (수동 입력)"], "미등록")
        self.assertEqual(rows["26220"]["WEHAGO 매출"], "0")
        self.assertIn("계약금액 (수동 입력)", summary_rows(page)["매출 (분개장)"])
        self.assertNotIn("<th>계약금액</th>", page)
        self.assertNotIn("계약금액 합계", page)

    def test_vendor_without_a_payable_line_is_unknown_not_zero(self):
        rows = dict((r["거래처"], r) for r in table_cells(self.pages["mgmt"], "xchk-vendors-m"))
        v = rows["가상꽃"]
        self.assertEqual((v["WEHAGO 미지급"], v["차이 (WEHAGO−요청)"]), ("판단 불가", "판단 불가"))
        self.assertIn("분개장 미지급금 줄 없음", v["비고"])
        w = rows["가상숙박"]
        self.assertEqual((w["인트라넷 요청 금액"], w["차이 (WEHAGO−요청)"]), ("판단 불가 (미확인 1건)", "판단 불가"))

    def test_cash_detail_without_opening_line_and_bank_files(self):
        cash = dict((r["항목"], r) for r in table_cells(self.pages["mgmt"], "xchk-cash"))
        self.assertEqual(cash["기초 잔액"]["금액"], "판단 불가")
        self.assertIn("기초 잔액 줄 없음", cash["기초 잔액"]["비고"])
        self.assertEqual(cash["계좌잔액.csv 잔액 합계"]["금액"], "판단 불가")
        self.assertIn("계좌잔액.csv 없음", cash["계좌잔액.csv 잔액 합계"]["비고"])
        self.assertEqual(cash["차이 (장부 잔액 − 계좌잔액.csv)"]["금액"], "판단 불가")
        for r in table_cells(self.pages["mgmt"], "xchk-cash-months"):
            self.assertEqual(r["입출금내역 증감 (입금−출금)"], "판단 불가")
            self.assertEqual(r["차이 (WEHAGO−입출금내역)"], "판단 불가")
            self.assertIn("입출금내역.csv 없음", r["비고"])

    def test_cash_summary_with_opening_balance_and_bank_balances(self):
        bank = {"balances": BANK_BALANCES, "transactions": BANK_TX}
        for mode, page in cash_pages(self, journal=OPENING_CASH, bank=bank).items():
            with self.subTest(mode):
                self.assertEqual(summary_rows(page)["보통예금 (WEHAGO 10300)"],
                                 "증감 45,000,000 · 장부 잔액 345,000,000 · 계좌잔액.csv 합계 345,000,000 · 차이 0")
        mgmt = cash_pages(self, journal=OPENING_CASH, bank=bank)["mgmt"]
        months = dict((r["월"], r) for r in table_cells(mgmt, "xchk-cash-months"))
        self.assertEqual((months["2026-10"]["WEHAGO 증감"], months["2026-10"]["입출금내역 증감 (입금−출금)"],
                          months["2026-10"]["차이 (WEHAGO−입출금내역)"]), ("57,000,000", "57,000,000", "0"))
        self.assertEqual(months["2026-09"]["입출금내역 증감 (입금−출금)"], "판단 불가")
        self.assertEqual(months["2026-09"]["차이 (WEHAGO−입출금내역)"], "판단 불가")
        cash = dict((r["항목"], r) for r in table_cells(mgmt, "xchk-cash"))
        self.assertEqual(cash["기초 잔액"]["금액"], "300,000,000")
        self.assertEqual(cash["차이 (장부 잔액 − 계좌잔액.csv)"]["금액"], "0")

    def test_cash_summary_shows_a_real_difference_with_its_sign(self):
        bank = {"balances": [dict(BANK_BALANCES[0]), dict(BANK_BALANCES[1], 잔액="100,000,000")], "transactions": None}
        pages = cash_pages(self, journal=OPENING_CASH, bank=bank)
        self.assertEqual(summary_rows(pages["ceo"])["보통예금 (WEHAGO 10300)"],
                         "증감 45,000,000 · 장부 잔액 345,000,000 · 계좌잔액.csv 합계 300,000,000 · 차이 45,000,000")

    def test_cash_summary_with_bank_balance_but_no_opening_line_has_no_difference(self):
        bank = {"balances": BANK_BALANCES, "transactions": None}
        value = summary_rows(cash_pages(self, bank=bank)["ceo"])["보통예금 (WEHAGO 10300)"]
        self.assertEqual(value, "증감 45,000,000 · 장부 잔액 판단 불가 (기초 잔액 줄 없음) · 계좌잔액.csv 합계 345,000,000 · 차이 판단 불가")

    def test_no_registered_contract_amount_is_not_a_zero_total(self):
        def edit(rows):
            for r in rows:
                if r["구분"] == "매출계약" and r["항목"] == "계약금액 (수동 입력)":
                    r["금액"], r["비고"] = "", "미등록"
        table = with_rows(xchk_table(shared_inputs()), edit)
        value = summary_rows(pages_for(self, table)["ceo"])["매출 (분개장)"]
        self.assertIn("계약금액 (수동 입력) 등록된 값 없음 (미등록 4건)", value)
        self.assertNotIn("합계 0", value)

    def test_a_project_without_a_known_cost_makes_the_cost_total_unknown(self):
        def edit(rows):
            for r in rows:
                if r["구분"] == "프로젝트원가" and r["대상"] == "26203" and r["항목"] == "WEHAGO 원가":
                    r["금액"], r["비고"] = "", "금액 미확인 1줄"
        table = with_rows(xchk_table(shared_inputs()), edit)
        pages = pages_for(self, table)
        value = summary_rows(pages["ceo"])["프로젝트 (도)원가"]
        self.assertTrue(value.startswith("판단 불가 (금액 미확인 1개 프로젝트) 확인된 합계 213,400,000"), value)
        self.assertIn("원가 판단 불가 1개 프로젝트는 제외", value)
        rows = dict((r["번호"], r) for r in table_cells(pages["mgmt"], "xchk-projects"))
        self.assertEqual(rows["26203"]["WEHAGO 원가"], "판단 불가 (미확인 1줄)")
        self.assertEqual(rows["26203"]["원가−실행가"], "판단 불가")
        self.assertEqual(summary_rows(pages["ceo"]), summary_rows(pages["mgmt"]))

    def test_unlinked_total_with_an_unknown_line_is_unknown_with_the_count(self):
        def edit(rows):
            for r in rows:
                if r["구분"] == "미연결원가" and r["항목"] == "WEHAGO 원가":
                    r["금액"], r["비고"] = "", "금액 미확인 1줄"
        pages = pages_for(self, with_rows(xchk_table(shared_inputs()), edit))
        self.assertEqual(summary_rows(pages["ceo"])["프로젝트 미연결 원가"], "2줄 금액 판단 불가 (미확인 1줄)")

    def test_both_editions_stay_equal_for_every_variant(self):
        bank = {"balances": BANK_BALANCES, "transactions": BANK_TX}
        for name, pages in (("fixture", pages_for(self, xchk_table(shared_inputs()))),
                            ("cash", cash_pages(self, journal=OPENING_CASH, bank=bank)),
                            ("hostile", pages_for(self, hostile_table(), raw=True))):
            with self.subTest(name):
                editions_ok(self, pages["ceo"], pages["mgmt"])


# ───────────── 주간 보고는 바뀌지 않는다 (cbc5497 코드와 같은 HTML) ─────────────
_BASELINE_TREE = []


def baseline_tree(test):
    """git archive cbc5497 을 임시 폴더에 풀어 경로를 돌려준다 (한 번만). git 이나 커밋이 없으면 시험을 건너뛴다."""
    if _BASELINE_TREE:
        return _BASELINE_TREE[0]
    try:
        proc = subprocess.run(["git", "-C", ROOT, "archive", "--format=tar", BASELINE], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    except OSError:
        test.skipTest("git 없음")
    if proc.returncode != 0:
        test.skipTest("git 기준 커밋 %s 를 풀 수 없음" % BASELINE)
    tmp = tempfile.mkdtemp(prefix="ceo_report_base_")
    import atexit
    atexit.register(shutil.rmtree, tmp, True)
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(tmp, filter="data")
        else:
            tar.extractall(tmp)
    _BASELINE_TREE.append(tmp)
    return tmp


def weekly_baseline(test, input_dir, asof=WEEKLY_ASOF):
    """cbc5497 코드로 주간 보고를 만든다 (하위 프로세스, PDF 안함) -> {'ceo': html, 'mgmt': html}."""
    tree = baseline_tree(test)
    out_dir = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, out_dir, True)
    proc = subprocess.run([sys.executable, os.path.join(tree, "보고서.py"), "주간", "--기준일", asof, "--입력", input_dir,
                           "--출력", out_dir, "--pdf", "안함"], cwd=tree, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    test.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
    pages = {}
    for mode, pattern in WEEKLY_FILES.items():
        with open(os.path.join(out_dir, pattern % asof), encoding="utf-8") as f:
            pages[mode] = f.read()
    return pages


class TestWeeklyUnchanged(unittest.TestCase):
    def test_weekly_html_equals_the_baseline_code_for_both_editions(self):
        folder = sample_folder(self, xchk_table(shared_inputs()))
        old = weekly_baseline(self, folder)
        rc, out, new, _ = run_cli(self, folder, "주간", WEEKLY_ASOF)
        self.assertEqual(rc, 0)
        for mode in ("ceo", "mgmt"):
            with self.subTest(mode):
                self.assertEqual(STAMP.sub("", new[mode]), STAMP.sub("", old[mode]))

    def test_weekly_never_imports_or_calls_load_xchk(self):
        folder = sample_folder(self, xchk_table(shared_inputs()))
        out_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out_dir, True)
        code = ("import importlib.util, sys\n"
                "spec = importlib.util.spec_from_file_location('report_cli', sys.argv[1])\n"
                "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
                "import io, contextlib\n"
                "with contextlib.redirect_stdout(io.StringIO()):\n"
                "    rc = m.main(['주간', '--기준일', sys.argv[2], '--입력', sys.argv[3], '--출력', sys.argv[4], '--pdf', '안함'])\n"
                "print(rc, 'ceo_report.convert_xchk' in sys.modules)\n")
        proc = subprocess.run([sys.executable, "-c", code, os.path.join(ROOT, "보고서.py"), WEEKLY_ASOF, folder, out_dir],
                              cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.stdout.decode("utf-8").split(), ["0", "False"], proc.stderr.decode("utf-8", "replace"))

    def test_weekly_prints_nothing_about_the_facts_file(self):
        folder = sample_folder(self)  # 위하고대조.csv 없음
        rc, out, pages, _ = run_cli(self, folder, "주간", WEEKLY_ASOF)
        self.assertEqual(rc, 0)
        self.assertNotIn("위하고", out)


if __name__ == "__main__":
    unittest.main()
