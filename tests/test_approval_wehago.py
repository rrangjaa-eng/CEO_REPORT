"""승인 화면의 WEHAGO 대조 시험 (계획 01.1-06).

시험 자료는 전부 가상이다 (D-28, D-36): 가상 스냅숏과 가상 엑셀(tests/test_wehago.py)만 쓴다.
다른 시험 파일에서는 함수와 상수만 가져온다 (TestCase 클래스를 가져오면 시험이 두 번 돈다).
"""
import copy
import datetime as dt
import importlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sample_input import refresh as refresh_sample  # noqa: E402
from test_approval import (SAMPLE, element_html, edit_csv, load_approval_cli, row_html, run_cli,  # noqa: E402
                           run_node, sample_copy, script_text, span_text, text_of, week_cell, write_fake_snapshot)
from test_approval_cli import fake_site, run_cli as run_collect_cli, sweep  # noqa: E402
from test_wehago import (EINVOICE_HEADER, FAKE_EINVOICE, FAKE_JOURNAL, FAKE_LEDGER, JOURNAL_HEADER, LEDGER_HEADER,  # noqa: E402
                         _jl, _L, requests_all, serial, write_fake_books, write_xlsx)

ASOF = dt.date(2026, 11, 2)
NOW = dt.datetime(2026, 11, 2, 0, 0)

HEAD_ALL = "전부 승인 시 최저 잔액 128.5 백만원 · 2026-12-25"
HEAD_INTRANET = "전부 승인 시 최저 잔액 83.5 백만원 · 2026-12-25"
SUMMARY_OK = ("WEHAGO 대조 (장부 기준일 2026-10-31): 계산서 있음 3건 51,700,000 · 금액 차이 1건 165,000,000 "
              "(인트라넷 요청 160,500,000 · 차액 +4,500,000, 일정은 계산서 금액) · 계산서 없음 1건 264,000 · "
              "이미 지급 1건 49,500,000 (일정에서 뺌) · 연결 불가 3건 4,400,000 외 금액 미확인 1건")
BOOK_DATES = ("장부 기준일: 분개장 2026-10-31 (마지막 전표 2026-10-30) · 매입매출장 2026-10-31 (마지막 전표 2026-10-27)"
              " · 전자세금계산서(매입) 2026-10-31 (마지막 일자 2026-10-28)")
NO_BOOKS = ("WEHAGO 대조: 판단 불가(WEHAGO 자료 없음: 분개장, 매입매출장, 전자세금계산서(매입)) · 일정은 인트라넷 기준")


def mod(name):
    return importlib.import_module("ceo_report." + name)


def setUpModule():
    refresh_sample()  # 샘플은 임시 폴더에 쓴다 (실제 입력 폴더를 건드리지 않음)


def T(page, id_):
    frag = element_html(page, id_)
    return None if frag is None else text_of(frag)


def new_tmp(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    return tmp


def read_only_html(out):
    names = [n for n in os.listdir(out) if n.endswith(".html")]
    assert len(names) == 1, names
    with open(os.path.join(out, names[0]), encoding="utf-8") as f:
        return f.read()


def cli_screen(test, books=True, prep=None, extra=(), input_dir=None, **book_kw):
    """수집 폴더에 가상 스냅숏(+가상 장부)을 만들고 CLI 로 화면을 만든다. (rc, stdout, page, root, out)."""
    tmp = new_tmp(test)
    root, out = os.path.join(tmp, "수집"), os.path.join(tmp, "출력")
    write_fake_snapshot(root)
    if books:
        write_fake_books(os.path.join(root, "위하고"), **book_kw)
    if prep:
        prep(os.path.join(root, "위하고"))
    argv = ["--기준일", "2026-11-02", "--수집폴더", root, "--출력", out, "--열기", "안함"]
    argv += ["--입력", input_dir or SAMPLE]
    rc, text = run_cli(argv + list(extra))
    page = read_only_html(out) if os.path.isdir(out) and os.listdir(out) else None
    return rc, text, page, root, out


def make_screen(test, wehago_dir, input_dir=SAMPLE):
    """CLI 대신 make_screen 으로 (page, A). wehago_dir 가 None 이면 스냅숏 옆 위하고 폴더."""
    tmp = new_tmp(test)
    snap = write_fake_snapshot(os.path.join(tmp, "수집"))
    kw = {} if wehago_dir == "default" else {"wehago_dir": wehago_dir}
    path, A = load_approval_cli().make_screen(input_dir, os.path.join(tmp, "출력"), snap, ASOF, NOW, False, **kw)
    with open(path, encoding="utf-8") as f:
        return f.read(), A


def req_row(page, no):
    frag = element_html(page, "requests")
    m = re.search(r'<tr[^>]*data-no="%s"[^>]*>(.*?)</tr>' % re.escape(no), frag, re.S)
    return m.group(1) if m else None


def table_row(page, table_id, no):
    frag = element_html(page, table_id)
    m = re.search(r'<tr[^>]*data-no="%s"[^>]*>(.*?)</tr>' % re.escape(no), frag or "", re.S)
    return m.group(1) if m else None


def td(row, cls):
    m = re.search(r'<td[^>]*class="[^"]*\b%s\b[^"]*"[^>]*>(.*?)</td>' % re.escape(cls), row, re.S)
    return None if m is None else text_of(m.group(1))


def after_h1(page):
    """h1 바로 뒤 첫 요소의 시작 글자."""
    tail = page[page.index("</h1>") + 5:]
    return tail.lstrip()[:60]


def journal_paid_on(date):
    """분개장 전표 20(5109 지급)의 날짜를 바꾼 가상 분개장."""
    rows = copy.deepcopy(FAKE_JOURNAL)
    for r in rows:
        if r[1] == 20:
            r[0] = serial(date)
    return rows


def redate_balance(old, new):
    def go(folder):
        def mutate(rows):
            for r in rows:
                if r and r[0] == old:
                    r[0] = new
        edit_csv(folder, "계좌잔액.csv", mutate)
    return go




def td_html(row, cls):
    m = re.search(r'<td[^>]*class="[^"]*\b%s\b[^"]*"[^>]*>.*?</td>' % re.escape(cls), row, re.S)
    return None if m is None else m.group(0)




# ───────────── Task 2: 없음·경과·머리글 다름·읽기 실패 ─────────────
NOT_OK_LABELS = {"자료 없음": "판단 불가(WEHAGO 자료 없음)", "경과": "판단 불가(WEHAGO 자료 경과)",
                 "머리글 다름": "판단 불가(머리글 다름)", "읽기 실패": "판단 불가(WEHAGO 읽기 실패)"}


def plain_data():
    """위하고 폴더 없이 만든 화면의 계산 자료 (인트라넷만 쓴 일정)."""
    tmp = tempfile.mkdtemp()
    try:
        snap = write_fake_snapshot(os.path.join(tmp, "수집"))
        A = mod("approval").build(mod("data").load(SAMPLE), mod("snapshot").read_snapshot(snap), ASOF, NOW)
        return A["data"]
    finally:
        shutil.rmtree(tmp, True)










# ───────────── Task 3: 거래처·프로젝트 패널, 개인정보, git 제외 ─────────────
RRN_RE = re.compile(r"\d{6}[- ]?\d{7}")  # 앞뒤 숫자 제한 없음: 더 긴 숫자 안의 6+7자리도 잡는다


def cells(row):
    return [text_of(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]


def body_rows(page, table_id):
    frag = element_html(page, table_id) or ""
    return [m for m in re.findall(r"<tr[^>]*>(.*?)</tr>", frag, re.S) if "<td" in m]


def code_row(page, table_id, code):
    frag = element_html(page, table_id) or ""
    m = re.search(r'<tr[^>]*data-code="%s"[^>]*>(.*?)</tr>' % re.escape(code), frag, re.S)
    return None if m is None else cells(m.group(1))






class TestXchkIgnored(unittest.TestCase):
    def git(self, *args):
        try:
            return subprocess.run(("git",) + args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError:
            self.skipTest("git 없음")

    def test_gitignore_has_the_xlsx_line(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as f:
            lines = [ln.strip() for ln in f.read().splitlines()]
        self.assertIn("*.xlsx", lines)

    def test_wehago_paths_are_ignored(self):
        for path in ("수집/위하고/분개장_20261031.xlsx", "입력/분개장_20261031.xlsx"):
            self.assertEqual(self.git("check-ignore", "-q", path).returncode, 0, path)

    def test_no_xlsx_is_tracked(self):
        res = self.git("ls-files", "*.xlsx")
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.decode("utf-8").strip(), "")


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
