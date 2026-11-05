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


class TestXchkScreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        root, out = os.path.join(cls.tmp, "수집"), os.path.join(cls.tmp, "출력")
        write_fake_snapshot(root)
        write_fake_books(os.path.join(root, "위하고"))
        cls.rc, cls.stdout = run_cli(["--기준일", "2026-11-02", "--입력", SAMPLE, "--수집폴더", root, "--출력", out, "--열기", "안함"])
        cls.page = read_only_html(out)
        snap = mod("snapshot").latest_snapshot(root)
        _, cls.A = load_approval_cli().make_screen(SAMPLE, os.path.join(cls.tmp, "o2"), snap, ASOF, NOW, False)
        cls.books = mod("wehago").load_books(os.path.join(root, "위하고"), ASOF, 7)
        cls.match = mod("wehago").match_requests(cls.books, requests_all())

    def test_cli_default_folder_is_next_to_snapshots(self):
        self.assertEqual(self.rc, 0)
        self.assertTrue(T(self.page, "headline").startswith(HEAD_ALL), T(self.page, "headline"))
        self.assertIn("부족·최소보유현금 미만 주 없음", T(self.page, "headline"))
        self.assertEqual(T(self.page, "h-est"), "추정 입금 포함 시 최저 잔액 150.5 백만원 · 2026-12-25")

    def test_week_totals_and_toggle_cells(self):
        self.assertEqual(week_cell(self.page, 0, "w-out"), "5,509,735")
        self.assertEqual(week_cell(self.page, 2, "w-out"), "167,645,735")
        for no, want in (("1201", "172.5"), ("5102", "128.7"), ("5103", "293.5"), ("5108", "130.7")):
            row = req_row(self.page, no)
            self.assertEqual(span_text(row, "r-toggle-v"), want, no)

    def test_already_paid_leaves_the_schedule(self):
        self.assertIsNone(table_row(self.page, "approved", "5109"))
        row = table_row(self.page, "already-paid", "5109")
        self.assertIsNotNone(row)
        self.assertNotIn("<input", row)
        self.assertIn("2026-10-30", text_of(row))
        self.assertIn("일정에서 뺌", text_of(row))
        self.assertEqual([r["번호"] for r in self.A["already_paid"]], ["5109"])
        self.assertEqual(self.A["paid_after_balance"], [])
        self.assertNotIn("5109", [r["번호"] for r in self.A["approved_future"]])
        self.assertIn("5105", [r["번호"] for r in self.A["approved_future"]])
        # 요청 표에는 체크 없이 남고 근거만 보인다
        mine = req_row(self.page, "5109")
        self.assertIn("disabled", mine)
        self.assertNotIn(" checked", mine)

    def test_amount_difference_uses_the_invoice_total(self):
        row = req_row(self.page, "5103")
        amount = td(row, "r-amt")
        self.assertIn("165,000,000", amount)
        self.assertIn("인트라넷 요청 160,500,000 · 차액 +4,500,000", amount)
        rid = re.search(r'data-id="([^"]+)"', row).group(1)
        sched = [r for r in self.A["data"]["requests"] if r["id"] == rid][0]
        self.assertEqual(sched["amount"], 165000000)
        entry = [r for r in self.A["requests_all"] if r["번호"] == "5103"][0]
        self.assertEqual((entry["amount"], entry["schedule_amount"], entry["amount_source"]),
                         (160500000, 165000000, "WEHAGO 계산서"))
        other = [r for r in self.A["requests_all"] if r["번호"] == "1201"][0]
        self.assertEqual((other["schedule_amount"], other["amount_source"]), (44000000, "인트라넷 요청"))

    def test_summary_line_and_book_dates(self):
        self.assertEqual(T(self.page, "xchk-summary"), SUMMARY_OK)
        self.assertTrue(T(self.page, "book-dates").startswith(BOOK_DATES), T(self.page, "book-dates"))
        for name in ("분개장_20261031.xlsx", "매입매출장_20261031.xlsx", "전자세금계산서(매입)_20261031.xlsx"):
            self.assertIn(name, T(self.page, "book-dates"))
        self.assertRegex(self.page, r'id="h-est".*?</div>\s*<div id="xchk-summary"')

    def test_status_column_everywhere(self):
        rows = self.match["rows"]
        self.assertEqual(len(rows), 9)
        for no, m in rows.items():
            self.assertEqual(td(table_row(self.page, "xchk", no), "x-status"), m["label"], no)
            self.assertEqual(td(req_row(self.page, no), "r-xchk"), m["label"], no)
        self.assertEqual(len(re.findall(r'<tr[^>]*data-no=', element_html(self.page, "xchk"))), 9)

    def test_status_chip_classes(self):
        self.assertIn('class="xs xs-diff"', req_row(self.page, "5103"))
        self.assertIn('class="xs xs-ok"', req_row(self.page, "1201"))
        self.assertIn('class="xs xs-none"', req_row(self.page, "5102"))
        self.assertIn('class="xs xs-na"', req_row(self.page, "5106"))
        self.assertIn('title="', td_html(req_row(self.page, "5103"), "r-xchk"))

    def test_schedule_notes_line(self):
        self.assertIn("이미 지급 중 지급일이 잔액 기준일(2026-11-02) 이후 0건", T(self.page, "schedule-notes"))

    def test_block_order(self):
        p = self.page
        marks = ['id="h-est"', 'id="xchk-summary"', 'id="attention"', '<table id="requests"', '<table id="weeks"',
                 '<table id="approved"', '<table id="already-paid"', 'id="book-dates"', '<table id="xchk"']
        at = [p.index(m) for m in marks]
        self.assertEqual(at, sorted(at), list(zip(marks, at)))

    def test_stdout_has_counts_only(self):
        self.assertIn("WEHAGO 대조: 계산서 있음 3건 · 금액 차이 1건 · 계산서 없음 1건 · 이미 지급 1건 · 연결 불가 3건", self.stdout)
        self.assertIn(BOOK_DATES, self.stdout)
        self.assertIn("전부 승인 시 최저 잔액 128.5", self.stdout)
        for text in ("가상음향", "44,000,000", "165,000,000", "49,500,000"):
            self.assertNotIn(text, self.stdout)

    def test_embedded_json_has_no_wehago_text(self):
        data = script_text(self.page, "approval-data")
        for text in ("분개장", "가상제작", "미지급금", "49,500,000"):
            self.assertNotIn(text, data)

    def test_js_parity_on_adjusted_data(self):
        A = self.A
        ids = [r["id"] for r in A["data"]["requests"]]
        js = run_node(script_text(self.page, "approval-calc"), A["data"], ids)
        py = mod("approval").scenario(A, ids)
        self.assertEqual(js["low"], py["low"])
        self.assertEqual(js["low_day"], py["low_day"])
        self.assertEqual(js["est_low"], py["est_low"])
        self.assertEqual(js["weeks"], py["weeks"])
        self.assertEqual(js["toggle"], {k: list(v) for k, v in py["toggle"].items()})

    def test_option_wins_over_the_default_folder(self):
        tmp = new_tmp(self)
        empty = os.path.join(tmp, "비어있음")
        os.makedirs(empty)
        rc, text, page, _, _ = cli_screen(self, extra=["--위하고폴더", empty])
        self.assertEqual(rc, 0)
        self.assertTrue(T(page, "headline").startswith(HEAD_INTRANET), T(page, "headline"))
        self.assertEqual(T(page, "xchk-summary").split(" · 일정")[0],
                         "WEHAGO 대조: 판단 불가(WEHAGO 자료 없음: 분개장, 매입매출장, 전자세금계산서(매입))")
        self.assertIn("판단 불가", text)


def td_html(row, cls):
    m = re.search(r'<td[^>]*class="[^"]*\b%s\b[^"]*"[^>]*>.*?</td>' % re.escape(cls), row, re.S)
    return None if m is None else m.group(0)


class TestXchkPaidAfterBalance(unittest.TestCase):
    """D-35b: 지급일이 잔액 기준일 이후인 '이미 지급'은 지급일에 확정 지급으로 일정에 남는다."""

    def run_probe(self, balance_date, paid_date):
        folder = sample_copy(self)
        redate_balance("2026-11-02", balance_date)(folder)
        tmp = new_tmp(self)
        write_fake_books(os.path.join(tmp, "위하고"), journal=journal_paid_on(paid_date))
        page, A = make_screen(self, os.path.join(tmp, "위하고"), input_dir=folder)
        return page, A

    def test_payment_after_the_balance_date_stays_as_a_fixed_outflow(self):
        page, A = self.run_probe("2026-10-29", dt.date(2026, 10, 30))
        self.assertEqual([r["번호"] for r in A["already_paid"]], ["5109"])
        self.assertEqual([r["번호"] for r in A["paid_after_balance"]], ["5109"])
        notes = T(page, "schedule-notes")
        self.assertIn("이미 지급 중 지급일이 잔액 기준일(2026-10-29) 이후 1건 49,500,000 "
                      "(잔액에 아직 없음 → 지급일에 확정 지급으로 일정에 넣음)", notes)
        self.assertNotIn("(일정에서 뺌", notes)
        self.assertIsNotNone(table_row(page, "already-paid", "5109"))
        self.assertNotIn(" checked", req_row(page, "5109"))
        self.assertIsNone(table_row(page, "approved", "5109"))
        self.assertIn("확정 지급으로 일정에 둠", T(page, "already-paid"))
        # 같은 달력에서 지급일을 잔액 기준일 이전으로 옮기면 빠진다: 차이는 5109 금액 하나
        _, removed = self.run_probe("2026-10-29", dt.date(2026, 10, 29))
        self.assertEqual([r["번호"] for r in removed["already_paid"]], ["5109"])
        self.assertEqual(removed["paid_after_balance"], [])
        self.assertEqual(sum(A["data"]["base_out"]) - sum(removed["data"]["base_out"]), 49500000)
        self.assertEqual(A["data"]["base_out"][0] - removed["data"]["base_out"][0], 49500000)  # 1주 첫날에 반영(P-8)
        self.assertEqual([r["id"] for r in A["data"]["requests"]], [r["id"] for r in removed["data"]["requests"]])

    def test_headline_drops_by_the_amount_vs_the_removed_case(self):
        _, stay = self.run_probe("2026-10-30", dt.date(2026, 10, 31))
        _, gone = self.run_probe("2026-10-30", dt.date(2026, 10, 30))
        approval = mod("approval")
        ids_s = [r["id"] for r in stay["data"]["requests"]]
        ids_g = [r["id"] for r in gone["data"]["requests"]]
        self.assertEqual(ids_s, ids_g)
        s_low = approval.scenario(stay, ids_s)["low"]
        g_low = approval.scenario(gone, ids_g)["low"]
        self.assertEqual(g_low - s_low, 49500000)
        # 지급일 10-31 은 1주(11-02 월요일 시작) 앞이라 1주 첫날에 반영, 주 합계 지급에 들어간다
        w0 = approval.scenario(stay, ids_s)["weeks"][0]["out"] - approval.scenario(gone, ids_g)["weeks"][0]["out"]
        self.assertEqual(w0, 49500000)

    def test_payment_on_the_balance_date_is_removed(self):
        page, A = self.run_probe("2026-10-30", dt.date(2026, 10, 30))
        self.assertEqual(A["paid_after_balance"], [])
        self.assertIn("이미 지급 중 지급일이 잔액 기준일(2026-10-30) 이후 0건", T(page, "schedule-notes"))
        self.assertIn("이미 지급 1건 49,500,000 (일정에서 뺌)", T(page, "xchk-summary"))
        self.assertNotIn("확정 지급으로 일정에 둠", T(page, "already-paid"))

    def test_summary_line_names_the_kept_payment(self):
        page, _ = self.run_probe("2026-10-29", dt.date(2026, 10, 30))
        self.assertIn("이미 지급 1건 49,500,000 (일정에 둠: 지급일이 잔액 기준일 이후)", T(page, "xchk-summary"))


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


class TestXchkFallback(unittest.TestCase):
    def fallback(self, prep_books, state, label=None):
        """prep_books(folder) 로 이상한 장부를 만들고 CLI 와 make_screen 으로 화면을 만든다."""
        tmp = new_tmp(self)
        root, out = os.path.join(tmp, "수집"), os.path.join(tmp, "출력")
        write_fake_snapshot(root)
        if prep_books:
            prep_books(os.path.join(root, "위하고"))
        rc, text = run_cli(["--기준일", "2026-11-02", "--입력", SAMPLE, "--수집폴더", root, "--출력", out, "--열기", "안함"])
        self.assertEqual(rc, 0)
        page = read_only_html(out)
        _, A = load_approval_cli().make_screen(SAMPLE, os.path.join(tmp, "o2"), mod("snapshot").latest_snapshot(root),
                                               ASOF, NOW, False)
        self.assertEqual(A["xchk"]["state"], state)
        self.assertTrue(T(page, "headline").startswith(HEAD_INTRANET), T(page, "headline"))
        want = label or NOT_OK_LABELS[state]
        self.assertEqual(len(re.findall(r'<td class="x-status">', page)), 9)
        for rq in A["requests_all"]:
            self.assertEqual(td(table_row(page, "xchk", rq["번호"]), "x-status"), want)
            self.assertEqual(td(req_row(page, rq["번호"]), "r-xchk"), want)
        self.assertEqual(re.findall(r'<tr[^>]*data-no=', element_html(page, "already-paid")), [])
        self.assertEqual(A["already_paid"], [])
        self.assertEqual(A["data"], plain_data())  # 일정 숫자도 금액도 인트라넷만 쓴 것과 같다
        self.assertNotIn("165,000,000", page)  # WEHAGO 금액이 어디에도 없다
        self.assertEqual(sum(1 for r in A["requests_all"] if r["amount_source"] != "인트라넷 요청"), 0)
        return page, A, text

    def test_no_folder(self):
        page, A, text = self.fallback(None, "자료 없음")
        self.assertEqual(T(page, "xchk-summary"), NO_BOOKS)
        self.assertIn("폴더를 찾을 수 없음", T(page, "book-dates"))
        self.assertIn(NO_BOOKS, text)
        self.assertNotIn('id="xchk-stop"', page)
        self.assertTrue(T(page, "book-dates").startswith("장부 기준일: 알 수 없음"))

    def test_stale_files(self):
        page, A, text = self.fallback(lambda f: write_fake_books(f, stamp="20261025"), "경과")
        s = T(page, "xchk-summary")
        self.assertTrue(s.startswith("WEHAGO 대조: 판단 불가(WEHAGO 자료 경과: "), s)
        self.assertIn("2026-10-25", s)
        self.assertTrue(s.endswith(" · 일정은 인트라넷 기준"), s)
        self.assertIn("2026-10-25", T(page, "book-dates"))
        self.assertIn("자료 경과", text)

    def test_header_mismatch_stops_the_cross_check(self):
        def prep(folder):
            write_fake_books(folder)
            header = ["메모" if h == "적요" else h for h in JOURNAL_HEADER]
            write_xlsx(os.path.join(folder, "분개장_20261031.xlsx"), [header] + [list(r) for r in FAKE_JOURNAL])
        page, A, text = self.fallback(prep, "머리글 다름", "판단 불가(머리글 다름)")
        self.assertTrue(after_h1(page).startswith('<div id="xchk-stop"'), after_h1(page))
        self.assertLess(page.index('id="xchk-stop"'), page.index('id="headline"'))
        stop = T(page, "xchk-stop")
        self.assertIn("WEHAGO 대조 멈춤: 분개장_20261031.xlsx 머리글이 예상과 다름 — 없음: 적요 · 추가: 메모", stop)
        self.assertIn("대조 상태는 모두 판단 불가(머리글 다름) · 일정은 인트라넷 기준", stop)
        self.assertEqual(text.splitlines()[3], "WEHAGO 대조 멈춤: 분개장_20261031.xlsx 머리글이 예상과 다름 — 없음: 적요 · 추가: 메모")

    def test_missing_ledger_column_names_the_file(self):
        def prep(folder):
            write_fake_books(folder)
            header = ["품목" if h == "품명" else h for h in LEDGER_HEADER]
            write_xlsx(os.path.join(folder, "매입매출장_20261031.xlsx"), [header] + [list(r) for r in FAKE_LEDGER])
        page, A, text = self.fallback(prep, "머리글 다름", "판단 불가(머리글 다름)")
        self.assertIn("매입매출장_20261031.xlsx 머리글이 예상과 다름 — 없음: 품명 · 추가: 품목", T(page, "xchk-stop"))

    def test_unreadable_journal(self):
        def prep(folder):
            write_fake_books(folder)
            with open(os.path.join(folder, "분개장_20261031.xlsx"), "wb") as f:
                f.write(bytes(range(256)) * 8)
        page, A, text = self.fallback(prep, "읽기 실패")
        self.assertTrue(after_h1(page).startswith('<div id="xchk-stop"'))
        self.assertIn("읽기 실패", T(page, "xchk-stop"))
        self.assertIn("읽기 실패", text)


class TestXchkExtraColumns(unittest.TestCase):
    """D-35c: 추가 열만으로는 멈추지 않는다. 기준일 이후 전표는 세어 보인다."""

    def test_extra_ledger_column_is_ignored_and_named(self):
        def prep(folder):
            write_fake_books(folder)
            rows = [LEDGER_HEADER + ["비고"]] + [list(r) + [""] for r in FAKE_LEDGER]
            write_xlsx(os.path.join(folder, "매입매출장_20261031.xlsx"), rows)
        rc, text, page, _, _ = cli_screen(self, books=False, prep=prep)
        self.assertEqual(rc, 0)
        self.assertTrue(T(page, "headline").startswith(HEAD_ALL), T(page, "headline"))
        self.assertNotIn('id="xchk-stop"', page)
        self.assertEqual(T(page, "xchk-summary"), SUMMARY_OK)
        book = T(page, "book-dates")
        self.assertTrue(book.startswith(BOOK_DATES), book)
        self.assertIn("매입매출장 추가 열 무시: 비고", book)
        self.assertNotIn("전표 0건", book)

    def test_rows_after_the_book_date_are_counted(self):
        journal = list(FAKE_JOURNAL) + [_jl(dt.date(2026, 11, 15), 30, "81900", "임차료", 1000, None, "가상임대", "11월 임차료"),
                                        _jl(dt.date(2026, 11, 15), 30, "26200", "미지급비용", None, 1000, "가상임대", "11월 임차료")]
        rc, text, page, _, _ = cli_screen(self, journal=journal)
        self.assertEqual(rc, 0)
        self.assertIn("분개장 장부 기준일 이후 전표 2건", T(page, "book-dates"))
        self.assertTrue(T(page, "book-dates").startswith(BOOK_DATES.replace("마지막 전표 2026-10-30", "마지막 전표 2026-11-15")),
                        T(page, "book-dates"))
        self.assertTrue(T(page, "xchk-summary").startswith("WEHAGO 대조 (장부 기준일 2026-10-31)"))
        self.assertIn("이미 지급 1건 49,500,000", T(page, "xchk-summary"))

    def test_payment_after_the_book_date_is_not_a_paid_request(self):
        rows = copy.deepcopy(FAKE_JOURNAL)
        for r in rows:
            if r[1] == 20:
                r[0] = serial(dt.date(2026, 11, 1))  # 장부 기준일(2026-10-31) 다음 날 출금
        rc, text, page, _, _ = cli_screen(self, journal=rows)
        self.assertEqual(rc, 0)
        self.assertNotIn("이미 지급 1건", T(page, "xchk-summary"))
        self.assertIsNone(table_row(page, "already-paid", "5109"))
        self.assertIsNotNone(table_row(page, "approved", "5109"))


class TestXchkAmountRule(unittest.TestCase):
    """D-30a: 금액 차이 요청은 승인 완료여도 계산서 합계로 고정 지급."""

    def test_approved_request_uses_the_invoice_total(self):
        ledger = list(FAKE_LEDGER)
        ledger[6:8] = [_L("매입", "2026-10-25", 7, "(주) 가상버스", "000-00-00006", "[26221] 가상 워크숍 버스", 3300000, 330000)]
        rc, text, page, _, _ = cli_screen(self, ledger=ledger)
        self.assertEqual(rc, 0)
        row = table_row(page, "approved", "5105")
        self.assertIn("3,630,000", td(row, "a-amt"))
        self.assertIn("인트라넷 요청 3,300,000 · 차액 +330,000", td(row, "a-amt"))
        self.assertEqual(week_cell(page, 1, "w-out"), "94,875,735")
        self.assertTrue(T(page, "headline").startswith("전부 승인 시 최저 잔액 128.1 백만원"), T(page, "headline"))


class TestXchkCollect(unittest.TestCase):
    """실행_승인검토.bat 경로(--수집 함): 장부가 있으면 대조가 같이 나오고 ID·비밀번호는 어디에도 남지 않는다 (APPR-06)."""

    def test_collection_run_carries_the_cross_check(self):
        tmp = new_tmp(self)
        root, out = os.path.join(tmp, "수집"), os.path.join(tmp, "출력")
        write_fake_books(os.path.join(root, "위하고"))
        argv = ["--수집", "함", "--기준일", "2026-11-02", "--입력", SAMPLE, "--수집폴더", root, "--출력", out]
        rc, text, err, fake, mocks = run_collect_cli(self, argv)
        self.assertEqual(rc, 0, text)
        page = read_only_html(out)
        self.assertIn("128.5", T(page, "headline"))
        self.assertIn("WEHAGO 대조 (장부 기준일 2026-10-31)", T(page, "xchk-summary"))
        self.assertIn("WEHAGO 대조: 계산서 있음 3건", text)
        self.assertTrue(mocks["browser"].called)
        sweep(self, tmp, [text, err, page], fake)


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


class TestXchkPanels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, tmp, True)
        write_fake_books(os.path.join(tmp, "위하고"))
        snap = write_fake_snapshot(os.path.join(tmp, "수집"))
        path, cls.A = load_approval_cli().make_screen(SAMPLE, os.path.join(tmp, "출력"), snap, ASOF, NOW, False,
                                                      wehago_dir=os.path.join(tmp, "위하고"))
        with open(path, encoding="utf-8") as f:
            cls.page = f.read()

    def test_vendor_panel(self):
        # WR-03: 분개장에 미지급금 줄이 없는 가상꽃은 0이 아니라 미확인·판단 불가 (전에는 6곳 +10,976,000 · 판단 불가 1곳)
        # WR-04: 5104(가상인력)는 일정이 잔액에 반영된 것으로 보므로 요청 쪽에서 뺀다 (가상인력 차이 +2,200,000 → +7,700,000)
        self.assertEqual(T(self.page, "xchk-vendors-sum"),
                         "차이 있는 거래처 표시 5곳 / 전체 5곳 · 차이 합계 +18,676,000 · 판단 불가 2곳 (분개장 미지급금 줄 없음 2곳)"
                         " · 비교 거래처 9곳 · 기초잔액 미반영")
        rows = body_rows(self.page, "xchk-vendors")
        self.assertEqual(cells(rows[0]), ["가상인력", "7,700,000", "0", "+7,700,000"])
        self.assertEqual(cells(rows[1]), ["㈜가상제작", "165,000,000", "160,500,000", "+4,500,000"])
        self.assertIn(["가상꽃", "미확인", "2,200,000", "판단 불가 (분개장 미지급금 줄 없음)"], [cells(r) for r in rows])
        self.assertEqual(len(rows), 7)
        # 가상숙박: 금액 미확인 요청이 있고 분개장에 미지급금 줄도 없어 차이를 알 수 없다 (WR-03: 전에는 미지급금 0, '판단 불가')
        self.assertEqual(cells(rows[-1])[1:], ["미확인", "미확인", "판단 불가 (분개장 미지급금 줄 없음)"])
        head = element_html(self.page, "xchk-vendors")
        for h in ("거래처", "WEHAGO 미지급금", "인트라넷 요청", "차이"):
            self.assertIn(h, head)

    def test_project_panel(self):
        self.assertEqual(code_row(self.page, "xchk-projects", "26201"),
                         ["26201", "가상 컨퍼런스", "300,000,000", "44,264,000", "40,000,000", "260,000,000", "4,264,000"])
        self.assertEqual(code_row(self.page, "xchk-projects", "26220")[2:],
                         ["250,000,000", "166,000,000", "158,000,000", "92,000,000", "8,000,000"])
        self.assertEqual(code_row(self.page, "xchk-projects", "26221")[2:],
                         ["미확인", "판단 불가", "5,400,000", "판단 불가", "판단 불가"])
        self.assertEqual(code_row(self.page, "xchk-projects", "26203")[2:],
                         ["60,000,000", "49,500,000", "45,000,000", "15,000,000", "4,500,000"])
        self.assertEqual([cells(r)[0] for r in body_rows(self.page, "xchk-projects")], ["26201", "26220", "26221", "26203"])
        self.assertIn("원가는 공급가액 기준, 요청 금액은 인트라넷 표시 금액(부가세 기준 미확인)", T(self.page, "xchk-projects"))

    def test_unlinked_cost(self):
        t = T(self.page, "xchk-unlinked")
        self.assertTrue(t.startswith("프로젝트 미연결 원가 2건 1,100,000"), t)
        rows = [cells(r) for r in body_rows(self.page, "xchk-unlinked")]
        # D-47: 미연결 원가 표에 마지막 '연결' 열(그 줄의 연결 설명)이 생겼다. 앞의 네 칸은 01.1 그대로, 다섯째 칸만 새로 맞춘다
        self.assertIn(["2026-10-29", "가상강사", "가상 개인강사 ******-******* 강사료", "800,000",
                       "미연결 (코드 없음 · 자동 연결 후보 0건)"], rows)
        self.assertIn(["2026-10-29", "가상기타", "[26999] 가상 기타 행사", "300,000",
                       "미연결 (코드 26999 프로젝트 목록에 없음 · 자동 연결 후보 0건)"], rows)
        self.assertEqual(len(rows), 2)  # 계정 Code 4xxxx 인 (도)외주비 줄은 원가가 아니다

    def test_panel_order(self):
        marks = ['<table id="xchk"', '<table id="xchk-vendors"', '<table id="xchk-projects"', 'id="xchk-unlinked"', 'id="basis"']
        at = [self.page.index(m) for m in marks]
        self.assertEqual(at, sorted(at), list(zip(marks, at)))
        self.assertLess(self.page.index('id="unrequested"'), self.page.index('id="book-dates"'))

    def test_wehago_rules_in_the_basis(self):
        t = T(self.page, "basis")
        for n in range(1, 6):
            self.assertIn("WEHAGO 규칙 %d" % n, t)
        for fact in ("주식회사", "이미 지급", "계산서 합계", "기초잔액", "(도)"):
            self.assertIn(fact, t)
        for word in ("위험", "해결방안", "권고", "우려", "추천"):
            self.assertNotIn(word, T(self.page, "xchk-summary") + T(self.page, "xchk-vendors") + T(self.page, "basis"))

    def test_opening_balance_removes_the_label(self):
        journal = list(FAKE_JOURNAL) + [_jl(dt.date(2026, 10, 1), 40, "25300", "미지급금", None, 1000000, "가상임대", "전기이월")]
        rc, text, page, _, _ = cli_screen(self, journal=journal)
        self.assertEqual(rc, 0)
        self.assertNotIn("기초잔액 미반영", T(page, "xchk-vendors-sum"))
        rows = [cells(r) for r in body_rows(page, "xchk-vendors")]
        self.assertIn(["가상임대", "4,000,000", "0", "+4,000,000"], rows)

    def test_not_ok_books_give_one_line_per_panel(self):
        for prep, label in ((None, "판단 불가(WEHAGO 자료 없음)"), (lambda f: write_fake_books(f, stamp="20261025"), "판단 불가(WEHAGO 자료 경과)")):
            rc, text, page, _, _ = cli_screen(self, books=False, prep=prep)
            for panel in ("xchk-vendors", "xchk-projects", "xchk-unlinked"):
                self.assertEqual(T(page, panel), label, panel)
                self.assertEqual(body_rows(page, panel), [], panel)

    def test_header_stop_gives_one_line_per_panel(self):
        def prep(folder):
            write_fake_books(folder)
            header = ["메모" if h == "적요" else h for h in JOURNAL_HEADER]
            write_xlsx(os.path.join(folder, "분개장_20261031.xlsx"), [header] + [list(r) for r in FAKE_JOURNAL])
        rc, text, page, _, _ = cli_screen(self, books=False, prep=prep)
        for panel in ("xchk-vendors", "xchk-projects", "xchk-unlinked"):
            self.assertEqual(T(page, panel), "판단 불가(머리글 다름)", panel)


class TestXchkPrivacy(unittest.TestCase):
    def sweep_rrn(self, texts, folder):
        for t in texts:
            self.assertIsNone(RRN_RE.search(t), RRN_RE.search(t))
        for dirpath, _, files in os.walk(folder):
            for name in files:
                with open(os.path.join(dirpath, name), "rb") as f:
                    data = f.read().decode("utf-8", "replace")
                self.assertIsNone(RRN_RE.search(data), name)

    def test_screen_stdout_and_files_have_no_rrn_like_run(self):
        rc, text, page, root, out = cli_screen(self)
        self.assertEqual(rc, 0)
        self.assertIn("가상 개인강사 ******-******* 강사료", page)
        self.assertNotIn("900101-1234567", page + text)
        self.sweep_rrn([page, text], out)

    def test_a_longer_digit_run_is_masked_too(self):
        journal = list(FAKE_JOURNAL) + [
            _jl(dt.date(2026, 10, 29), 41, "61101", "행사외주비(도)", 700000, None, "가상강사2", "강사료 계좌 12345678901234", "V041"),
            _jl(dt.date(2026, 10, 29), 41, "10300", "보통예금", None, 700000, "가상강사2", "강사료 계좌 12345678901234", "V041")]
        rc, text, page, root, out = cli_screen(self, journal=journal)
        self.sweep_rrn([page, text], out)
        self.assertIn("******-*******", page)

    def test_collection_run_has_no_rrn_like_run(self):
        tmp = new_tmp(self)
        root, out = os.path.join(tmp, "수집"), os.path.join(tmp, "출력")
        write_fake_books(os.path.join(root, "위하고"))
        rc, text, err, fake, _ = run_collect_cli(self, ["--수집", "함", "--기준일", "2026-11-02", "--입력", SAMPLE, "--수집폴더", root, "--출력", out])
        self.assertEqual(rc, 0)
        self.sweep_rrn([text, err, read_only_html(out)], out)

    def test_vendor_and_unlinked_text_is_escaped(self):
        journal = list(FAKE_JOURNAL) + [
            _jl(dt.date(2026, 10, 29), 42, "25300", "미지급금", None, 1000000, "<b>가상</b>", "[26201] 가상 태그", "V042"),
            _jl(dt.date(2026, 10, 29), 43, "61101", "행사외주비(도)", 250000, None, "<b>가상</b>", "<i>메모</i>", "V042"),
            _jl(dt.date(2026, 10, 29), 43, "10300", "보통예금", None, 250000, "<b>가상</b>", "<i>메모</i>", "V042")]
        rc, text, page, _, _ = cli_screen(self, journal=journal)
        self.assertEqual(rc, 0)
        self.assertIn("&lt;b&gt;", element_html(page, "xchk-vendors"))
        self.assertIn("&lt;b&gt;", element_html(page, "xchk-unlinked"))
        self.assertIn("&lt;i&gt;", element_html(page, "xchk-unlinked"))
        self.assertNotIn("<b>가상", page)
        self.assertNotIn("<i>메모", page)


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
