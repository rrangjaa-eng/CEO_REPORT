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
from test_convert_xchk import (BANK_BALANCES, BANK_TX, OPENING_CASH, FAKE_PL_JOURNAL, shared_inputs,  # noqa: E402
                               write_xchk, xchk_inputs, xchk_table)
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


def sample_folder(test, xchk=None):
    """샘플 입력을 임시 폴더에 복사하고, 표(xchk)가 있으면 위하고대조.csv 로 쓴다. 폴더 경로를 돌려준다."""
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    folder = os.path.join(tmp, "입력")
    shutil.copytree(SAMPLE, folder)
    if xchk is not None:
        write_xchk(folder, xchk)
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
    m = re.search(r"<div class=\"xchk-meta\">(.*?)</div>", section8(page), re.S)
    return plain(m.group(1)) if m else None


def editions_ok(test, ceo, mgmt):
    """대표용 규칙: 금지어 없음, 숫자 동일."""
    for word in FORBIDDEN:
        test.assertNotIn(word, ceo, word)
    test.assertEqual(numbers_of(ceo), numbers_of(mgmt))


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
            for word in ("수집", ".xlsx", "openpyxl", "wehago"):
                self.assertNotIn(word, code, "%s: %s" % (name, word))

    def test_calc_and_data_are_unchanged_from_the_baseline(self):
        try:
            rc = subprocess.run(["git", "-C", ROOT, "diff", "--quiet", BASELINE, "--", "ceo_report/calc.py", "ceo_report/data.py"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
        except OSError:
            self.skipTest("git 없음")
        if rc not in (0, 1):
            self.skipTest("git 기준 커밋 %s 없음" % BASELINE)
        self.assertEqual(rc, 0)


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
