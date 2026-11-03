"""승인 검토 화면 테스트. 실행: python3 -m unittest discover -s tests

시험 자료는 전부 가상이다 (D-28). 실제 회사 자료를 읽거나 베끼지 않는다.
ceo_report 모듈은 시험 안에서 불러온다: 모듈이 없으면 해당 시험만 실패한다.
"""
import contextlib
import copy
import csv
import datetime as dt
import html as htmlmod
import importlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sample_input import SAMPLE, refresh as refresh_sample  # noqa: E402

ASOF = dt.date(2026, 11, 2)
NOW = dt.datetime(2026, 11, 2, 0, 0)
COLLECTED = dt.datetime(2026, 11, 1, 18, 0, 0)


def mod(name):
    """ceo_report 모듈을 시험 안에서 불러온다."""
    return importlib.import_module("ceo_report." + name)


def setUpModule():
    refresh_sample()  # 샘플은 임시 폴더에 쓴다 (실제 입력 폴더를 건드리지 않음)


# ───────────── 가상 스냅숏 (PAYMENT_COLUMNS 순서) ─────────────
# 번호, 행사명, 파트너, 등록일, 행사일, 금액, 지급요청일, 등록자, 팀장승인, 관리팀승인, 사장님승인
FAKE_PAYMENTS = [
    ["1201", "[26201] 가상 컨퍼런스", "가상음향", "2026-10-30 10:00:00", "2026-11-20", "44,000,000", "2026-11-13", "홍길동", "승인", "승인", "미승인"],
    ["5102", "[26201] 가상 컨퍼런스", "가상조명", "2026-11-01 09:00:00", "2026-11-20", "264,000", "", "홍길동", "승인", "수락요청중", "미승인"],
    ["5103", "[26220] 가상 전시", "가상제작", "2026-10-28 15:52:03", "2026-11-12", "160,500,000", "2026-11-20", "김철수", "수락요청중", "미승인", "미승인"],
    ["5104", "[26220] 가상 전시", "가상인력", "2026-10-26 11:00:00", "2026-11-12", "5,500,000", "", "김철수", "승인", "승인", "승인"],
    ["5105", "[26221] 가상 워크숍", "가상버스", "2026-10-29 16:00:00", "2026-11-25", "3,300,000", "2026-11-10", "이영희", "승인", "승인", "승인"],
    ["5106", "[26221] 가상 워크숍", "가상숙박", "2026-11-01 08:00:00", "2026-11-25", "", "2026-11-17", "이영희", "승인", "미승인", "미승인"],
    ["5107", "[26201] 가상 컨퍼런스", "가상케이터링", "2026-10-31 12:00:00", "2026-11-20", "1,100,000", "2026-11-06", "박민수", "승인", "승인", "반려"],
    ["5108", "[26299] 목록에 없는 행사", "가상꽃", "2026-10-30 09:00:00", "2026-11-27", "2,200,000", "2026-10-30", "박민수", "승인", "승인", "미승인"],
    ["5109", "[26203] 가상 전시부스", "가상부스", "2026-10-29 10:00:00", "2026-11-12", "49,500,000", "2026-11-06", "김철수", "승인", "승인", "승인"],
]
# 번호, 클라이언트, 담당자, PO번호, 행사일, 행사명, 국, 팀, 등록자, 계산서, 사전견적, 견적금액, 실행가, 수익률,
# 승인_담당자, 승인_팀장, 승인_관리팀, 승인_대표이사, pro_num
FAKE_PROJECTS = [
    ["26201", "가상고객A", "홍길동", "PO-1", "2026-11-20", "가상 컨퍼런스", "1국", "1팀", "홍길동", "발행", "400,000,000", "420,000,000", "300,000,000", "28.6%", "승인", "승인", "승인", "승인", "901"],
    ["26220", "가상고객B", "김철수", "PO-2", "2026-11-12", "가상 전시", "2국", "2팀", "김철수", "미발행", "300,000,000", "320,000,000", "250,000,000", "21.9%", "승인", "승인", "승인", "승인", "902"],
    ["26221", "가상고객C", "이영희", "PO-3", "2026-11-25", "가상 워크숍", "1국", "1팀", "이영희", "미발행", "50,000,000", "55,000,000", "", "", "승인", "승인", "미승인", "미승인", "903"],
    ["26203", "가상고객D", "김철수", "PO-4", "2026-11-12", "가상 전시부스", "2국", "2팀", "김철수", "발행", "70,000,000", "75,000,000", "60,000,000", "20.0%", "승인", "승인", "승인", "승인", "904"],
]
MINI_IDS = ("1201", "5103")


def as_dicts(rows, columns):
    return [dict(zip(columns, r)) for r in rows]


def write_fake_snapshot(root, ids=None, extra=None, collected_at=COLLECTED):
    """가상 스냅숏 폴더를 root 아래에 쓰고 폴더 경로를 돌려준다."""
    snapshot = mod("snapshot")
    rows = [r for r in FAKE_PAYMENTS if ids is None or r[0] in ids] + [list(r) for r in (extra or [])]
    return snapshot.write_snapshot(root, collected_at, as_dicts(rows, snapshot.PAYMENT_COLUMNS),
                                   as_dicts(FAKE_PROJECTS, snapshot.PROJECT_COLUMNS))


def new_tmp(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    return tmp


_CLI = None


def load_approval_cli():
    """승인검토.py는 이름이 한글이라 import 할 수 없다. 경로로 읽어 한 번만 만든다."""
    global _CLI
    if _CLI is None:
        spec = importlib.util.spec_from_file_location("approval_cli", os.path.join(ROOT, "승인검토.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _CLI = m
    return _CLI


def run_cli(argv):
    cli = load_approval_cli()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(argv)
    return rc, buf.getvalue()


class _Grab(HTMLParser):
    def __init__(self, target):
        HTMLParser.__init__(self, convert_charrefs=False)
        self.target, self.tag, self.depth, self.parts, self.done = target, None, 0, [], False

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if self.tag is None:
            if dict(attrs).get("id") == self.target:
                self.tag, self.depth = tag, 1
            return
        self.parts.append(self.get_starttag_text())
        if tag == self.tag:
            self.depth += 1

    def handle_endtag(self, tag):
        if self.done or self.tag is None:
            return
        if tag == self.tag:
            self.depth -= 1
            if self.depth == 0:
                self.done = True
                return
        self.parts.append("</%s>" % tag)

    def handle_data(self, data):
        if self.tag is not None and not self.done:
            self.parts.append(data)

    def handle_entityref(self, name):
        if self.tag is not None and not self.done:
            self.parts.append("&%s;" % name)

    def handle_charref(self, name):
        if self.tag is not None and not self.done:
            self.parts.append("&#%s;" % name)


def element_html(html, id_):
    """id가 id_ 인 요소의 안쪽 HTML. 없으면 None."""
    g = _Grab(id_)
    g.feed(html)
    return "".join(g.parts) if g.tag is not None else None


def text_of(fragment):
    """태그를 없애고 HTML 글자를 풀어 공백을 하나로 줄인 글."""
    s = re.sub(r"<[^>]+>", "", fragment or "")
    return re.sub(r"\s+", " ", htmlmod.unescape(s)).strip()


def T(page, id_):
    return text_of(element_html(page, id_))


def script_text(page, id_):
    m = re.search(r'<script[^>]*id="%s"[^>]*>(.*?)</script>' % re.escape(id_), page, re.S)
    return m.group(1) if m else None


def row_html(page, data_id):
    m = re.search(r'<tr[^>]*data-id="%s"[^>]*>(.*?)</tr>' % re.escape(data_id), page, re.S)
    return m.group(1) if m else None


def span_text(fragment, cls):
    m = re.search(r'<span[^>]*class="%s"[^>]*>(.*?)</span>' % re.escape(cls), fragment, re.S)
    return text_of(m.group(1)) if m else None


def week_cell(page, week, cls):
    m = re.search(r'<tr[^>]*data-week="%d"[^>]*>(.*?)</tr>' % week, page, re.S)
    c = re.search(r'<td[^>]*\b%s\b[^>]*>(.*?)</td>' % re.escape(cls), m.group(1), re.S)
    return text_of(c.group(1))


def checked_req_ids(page):
    tags = re.findall(r'<input[^>]*class="req"[^>]*>', page)
    return [re.search(r'data-id="([^"]+)"', t).group(1) for t in tags if " checked" in t]


def run_node(js_text, data, checked):
    """script#approval-calc 글을 node 로 돌려 approvalCalc(data, checked)의 JSON 결과를 돌려준다."""
    tmp = tempfile.mkdtemp()
    try:
        jpath, dpath = os.path.join(tmp, "calc.js"), os.path.join(tmp, "data.json")
        with open(dpath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        with open(jpath, "w", encoding="utf-8") as f:
            f.write(js_text + "\nconst fs = require('fs');\n"
                    "const data = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));\n"
                    "const checked = JSON.parse(process.argv[3]);\n"
                    "console.log(JSON.stringify(approvalCalc(data, checked)));\n")
        out = subprocess.run(["node", jpath, dpath, json.dumps(sorted(checked))], check=True, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE).stdout.decode("utf-8")
        return json.loads(out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def engine_data(start=100):
    days = [(dt.date(2026, 11, 2) + dt.timedelta(days=i)).isoformat() for i in range(14)]
    base_out, est_in = [0] * 14, [0] * 14
    base_out[1] = 30
    est_in[8] = 20
    return {"asof": "2026-11-02", "start": start, "reserve": 50, "days": days, "weeks": [[0, 6], [7, 13]],
            "base_in": [0] * 14, "base_out": base_out, "est_in": est_in,
            "requests": [{"id": "r0", "day": 4, "amount": 40}, {"id": "r1", "day": 8, "amount": 50}]}


class TestSnapshotFormat(unittest.TestCase):
    def snap_dicts(self):
        s = mod("snapshot")
        return as_dicts(FAKE_PAYMENTS, s.PAYMENT_COLUMNS), as_dicts(FAKE_PROJECTS, s.PROJECT_COLUMNS)

    def test_write_creates_exactly_the_three_files(self):
        s = mod("snapshot")
        tmp = new_tmp(self)
        pay, proj = self.snap_dicts()
        folder = s.write_snapshot(tmp, COLLECTED, pay, proj)
        self.assertEqual(folder, os.path.join(tmp, "인트라넷_20261101_180000"))
        self.assertEqual(sorted(os.listdir(folder)), sorted(["지급요청.csv", "프로젝트목록.csv", "수집정보.csv"]))
        with open(os.path.join(folder, "지급요청.csv"), encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0], ["수집시각"] + s.PAYMENT_COLUMNS)
        self.assertEqual(rows[1][0], "2026-11-01 18:00:00")
        with open(os.path.join(folder, "지급요청.csv"), "rb") as f:
            self.assertTrue(f.read(3) == b"\xef\xbb\xbf", "UTF-8 BOM")
        self.assertFalse([n for n in os.listdir(tmp) if n.endswith(".작성중")])

    def test_column_contract(self):
        s = mod("snapshot")
        self.assertEqual(len(s.PAYMENT_COLUMNS), 11)
        self.assertEqual(s.PAYMENT_COLUMNS[0], "번호")
        self.assertEqual(s.PAYMENT_COLUMNS[-1], "사장님승인")
        self.assertEqual(len(s.PROJECT_COLUMNS), 19)
        self.assertEqual(s.PROJECT_COLUMNS[-1], "pro_num")

    def test_latest_snapshot_ignores_unfinished_folder(self):
        s = mod("snapshot")
        tmp = new_tmp(self)
        pay, proj = self.snap_dicts()
        folder = s.write_snapshot(tmp, COLLECTED, pay, proj)
        os.makedirs(os.path.join(tmp, "인트라넷_20261102_000000.작성중"))
        self.assertEqual(s.latest_snapshot(tmp), folder)
        self.assertIsNone(s.latest_snapshot(os.path.join(tmp, "없는폴더")))

    def test_read_snapshot_roundtrip(self):
        s = mod("snapshot")
        tmp = new_tmp(self)
        pay, proj = self.snap_dicts()
        snap = s.read_snapshot(s.write_snapshot(tmp, COLLECTED, pay, proj))
        self.assertEqual(len(snap.payments), 9)
        self.assertEqual(snap.payments[0]["번호"], "1201")
        self.assertEqual(snap.payments[0]["금액"], "44,000,000")
        self.assertEqual(snap.collected_at, COLLECTED)
        self.assertEqual(len(snap.projects), 4)

    def test_missing_column_stops(self):
        s = mod("snapshot")
        tmp = new_tmp(self)
        pay, proj = self.snap_dicts()
        folder = s.write_snapshot(tmp, COLLECTED, pay, proj)
        path = os.path.join(folder, "지급요청.csv")
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        k = rows[0].index("금액")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows([r[:k] + r[k + 1:] for r in rows])
        with self.assertRaises(s.SnapshotError) as cm:
            s.read_snapshot(folder)
        self.assertIn("금액", str(cm.exception))

    def test_row_count_mismatch_stops(self):
        s = mod("snapshot")
        tmp = new_tmp(self)
        pay, proj = self.snap_dicts()
        folder = s.write_snapshot(tmp, COLLECTED, pay, proj)
        path = os.path.join(folder, "지급요청.csv")
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(rows[:-1])
        with self.assertRaises(s.SnapshotError) as cm:
            s.read_snapshot(folder)
        self.assertIn("건수", str(cm.exception))

    def test_duplicate_or_empty_request_number_stops(self):
        """WR-07: 지급요청 번호는 요청을 가리키는 열쇠다. 비었거나 겹치면 덮어쓰지 않고 멈춘다 (D-29)."""
        s = mod("snapshot")
        cases = (([r[0] for r in FAKE_PAYMENTS[:3]] + ["5103"], "번호가 겹치는 줄 2건 (5103)"),
                 ([r[0] for r in FAKE_PAYMENTS[:3]] + [""], "번호가 빈 줄 1건"),
                 (["", ""], "번호가 빈 줄 2건"))
        for numbers, text in cases:
            tmp = new_tmp(self)
            rows = [[no] + list(FAKE_PAYMENTS[i % len(FAKE_PAYMENTS)][1:]) for i, no in enumerate(numbers)]
            folder = s.write_snapshot(tmp, COLLECTED, as_dicts(rows, s.PAYMENT_COLUMNS),
                                      as_dicts(FAKE_PROJECTS, s.PROJECT_COLUMNS))
            with self.assertRaises(s.SnapshotError) as cm:
                s.read_snapshot(folder)
            self.assertIn(text, str(cm.exception))
            self.assertIn("지급요청", str(cm.exception))

    def test_same_time_twice_is_refused(self):
        s = mod("snapshot")
        tmp = new_tmp(self)
        pay, proj = self.snap_dicts()
        s.write_snapshot(tmp, COLLECTED, pay, proj)
        with self.assertRaises(s.SnapshotError):
            s.write_snapshot(tmp, COLLECTED, pay, proj)

    def test_failed_rename_leaves_nothing_behind(self):
        s = mod("snapshot")
        tmp = new_tmp(self)
        pay, proj = self.snap_dicts()
        with mock.patch("os.rename", side_effect=PermissionError("막힘")):
            with self.assertRaises(PermissionError):
                s.write_snapshot(tmp, COLLECTED, pay, proj)
        self.assertEqual(os.listdir(tmp), [])


class TestApprovalEngine(unittest.TestCase):
    def test_all_checked(self):
        sc = mod("approval").scenario
        r = sc(engine_data(), {"r0", "r1"})
        self.assertEqual((r["low"], r["low_day"]), (-20, "2026-11-10"))
        w1, w2 = r["weeks"]
        self.assertEqual((w1["min"], w1["end"], w1["level"]), (30, 30, "최소보유현금 미만"))
        self.assertEqual((w2["min"], w2["end"], w2["level"]), (-20, -20, "부족"))
        self.assertEqual((r["est_low"], r["est_low_day"]), (0, "2026-11-10"))
        self.assertEqual(r["toggle"]["r0"], [20, "2026-11-10"])
        self.assertEqual(r["toggle"]["r1"], [30, "2026-11-06"])
        self.assertEqual((r["checked_n"], r["checked_sum"]), (2, 90))

    def test_week_sums(self):
        sc = mod("approval").scenario
        r = sc(engine_data(), {"r0", "r1"})
        self.assertEqual([(w["in"], w["out"], w["est_in"]) for w in r["weeks"]], [(0, 70, 0), (0, 50, 20)])

    def test_none_checked(self):
        sc = mod("approval").scenario
        r = sc(engine_data(), set())
        self.assertEqual((r["low"], r["low_day"]), (70, "2026-11-03"))
        self.assertEqual(r["toggle"]["r0"], [30, "2026-11-06"])
        self.assertEqual((r["checked_n"], r["checked_sum"]), (0, 0))

    def test_unknown_start_is_never_zero(self):
        sc = mod("approval").scenario
        r = sc(engine_data(start=None), {"r0", "r1"})
        self.assertIsNone(r["low"])
        self.assertIsNone(r["est_low"])
        for w in r["weeks"]:
            self.assertIsNone(w["min"])
            self.assertIsNone(w["end"])
            self.assertEqual(w["level"], "")
        self.assertEqual(r["toggle"]["r0"], [None, None])

    def test_formatters(self):
        a = mod("approval")
        self.assertEqual(a.fmt_man(98236000), "98.2")
        self.assertEqual(a.fmt_man(None), "미확인")
        self.assertEqual(a.fmt_man(-301764000), "−301.8")
        self.assertEqual(a.fmt_man(30000), "30,000원")
        self.assertEqual(a.fmt_man(0), "0.0")
        self.assertEqual(a.fmt_won(264000), "264,000")
        self.assertEqual(a.fmt_won(-1100000), "−1,100,000")


class TestApprovalTracer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.root, cls.out = os.path.join(cls.tmp, "수집"), os.path.join(cls.tmp, "출력")
        cls.snap = write_fake_snapshot(cls.root, MINI_IDS)
        cls.rc, cls.stdout = run_cli(["--기준일", "2026-11-02", "--입력", SAMPLE, "--수집폴더", cls.root, "--출력", cls.out, "--열기", "안함"])
        files = os.listdir(cls.out) if os.path.isdir(cls.out) else []
        cls.files = files
        cls.page = ""
        if files:
            with open(os.path.join(cls.out, files[0]), encoding="utf-8") as f:
                cls.page = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_exit_and_single_file(self):
        self.assertEqual(self.rc, 0, self.stdout)
        self.assertEqual(len(self.files), 1)
        self.assertRegex(self.files[0], r"^승인검토_\d{8}_\d{4}\.html$")

    def test_headline_is_first_and_before_tables(self):
        p = self.page
        self.assertLess(p.index('id="headline"'), p.index("<table"))
        h = T(p, "headline")
        self.assertIn("전부 승인 시 최저 잔액 89.2 백만원 · 2026-12-25", h)
        # D-54: 남은 예산 7,700,000(12/25)이 들어가 마지막 주가 최소보유현금 미만이 된다
        self.assertIn("최소보유현금 미만 12/21~12/27", h)
        open_tag = re.search(r'<div[^>]*id="headline"[^>]*>', p).group(0)
        self.assertNotIn("lv-short", open_tag)
        self.assertIn("lv-reserve", open_tag)
        self.assertEqual(T(p, "h-sum"), "(체크 합계 204,500,000원)")

    def test_estimate_line_and_start_line(self):
        p = self.page
        self.assertIn("추정 입금 포함 시 최저 잔액 111.2 백만원 · 2026-12-25", T(p, "h-est"))
        s = T(p, "start-line")
        self.assertIn("시작 잔액(사용 가능액) 542.4 백만원", s)
        self.assertIn("잔액 기준일 2026-11-02", s)
        self.assertIn("인트라넷 수집 시각 2026-11-01 18:00:00 (마지막 스냅숏)", s)
        self.assertEqual(T(p, "snap-age"), "기준일보다 1일 전 수집")

    def test_requests_checked_and_toggle_cells(self):
        p = self.page
        self.assertEqual(sorted(checked_req_ids(p)), ["r0", "r1"])
        r0, r1 = row_html(p, "r0"), row_html(p, "r1")
        self.assertEqual(span_text(r0, "r-toggle-v"), "133.2")
        self.assertEqual(span_text(r1, "r-toggle-v"), "249.7")
        self.assertEqual(span_text(r0, "r-mode"), "빼면")
        self.assertLess(p.index('data-id="r0"'), p.index('data-id="r1"'))
        self.assertIn("1201 가상음향 44,000,000 승인 가정", text_of(r0))

    def test_week_cells_and_css(self):
        p = self.page
        self.assertEqual(week_cell(p, 0, "w-out"), "52,545,735")   # + 남은 예산 매주 나눔 1,845,735 (사용자 2026-11-03)
        self.assertIn("position:sticky", p)
        self.assertIn(":root{--ink:#1d2433;--sub:#5b6475;--line:#d9dde5;--soft:#f3f5f8;--accent:#1f4e8c;--in:#2f7d5b;"
                      "--out:#b5523b;", p)
        self.assertIsNone(re.search(r"src=|https?://", p))

    def test_embedded_json_equals_engine_input(self):
        cli = load_approval_cli()
        d_html, A = cli.make_screen(SAMPLE, os.path.join(self.tmp, "o2"), self.snap, ASOF, NOW, False)
        with open(d_html, encoding="utf-8") as f:
            page = f.read()
        self.assertEqual(json.loads(script_text(page, "approval-data")), A["data"])
        self.assertEqual(A["data"]["start"], 542400000)

    def test_no_snapshot_and_bad_date(self):
        empty = new_tmp(self)
        rc, out = run_cli(["--기준일", "2026-11-02", "--입력", SAMPLE, "--수집폴더", empty, "--출력", os.path.join(empty, "o"), "--열기", "안함"])
        self.assertEqual(rc, 2)
        self.assertIn("인트라넷 수집 스냅숏이 없습니다", out)
        rc, _ = run_cli(["--기준일", "2026-13-45", "--입력", SAMPLE, "--수집폴더", self.root, "--출력", os.path.join(empty, "o"), "--열기", "안함"])
        self.assertEqual(rc, 2)


@unittest.skipIf(shutil.which("node") is None, "node 없음")
class TestApprovalJsParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        root = os.path.join(cls.tmp, "수집")
        snap = write_fake_snapshot(root, MINI_IDS)
        cli = load_approval_cli()
        path, cls.A = cli.make_screen(SAMPLE, os.path.join(cls.tmp, "o"), snap, ASOF, NOW, False)
        with open(path, encoding="utf-8") as f:
            cls.js = script_text(f.read(), "approval-calc")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def check(self, data, sets):
        sc = mod("approval").scenario
        for chk in sets:
            self.assertEqual(run_node(self.js, data, chk), json.loads(json.dumps(sc(data, set(chk)))), chk)

    def test_synthetic(self):
        self.check(engine_data(), [["r0", "r1"], [], ["r0"], ["r1"]])
        self.check(engine_data(start=None), [["r0", "r1"], []])

    def test_tracer_data(self):
        data = self.A["data"]
        ids = [r["id"] for r in data["requests"]]
        self.assertEqual(ids, ["r0", "r1"])
        self.check(data, [ids, [], [ids[0]], [ids[1]]])


# ───────────── Task 2: 요청 규칙 ─────────────
STAMP_RE = re.compile(r"작성 [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}")


def edit_csv(folder, filename, mutate):
    """폴더 안의 CSV 한 개를 읽어 mutate(rows)로 고쳐 다시 쓴다."""
    path = os.path.join(folder, filename)
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    mutate(rows)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)


def sample_copy(test):
    """샘플 입력 전체를 임시 폴더에 복사한다 (여러 파일을 고칠 때)."""
    tmp = new_tmp(test)
    folder = os.path.join(tmp, "입력")
    shutil.copytree(SAMPLE, folder)
    return folder


def set_setting(rows, key, value):
    """설정.csv 줄의 값을 바꾸고, 줄이 없으면 끝에 붙인다. value가 None이면 줄을 지운다."""
    rows[:] = [r for r in rows if not (r and r[0] == key)]
    if value is not None:
        rows.append([key, value])


def full_screen(test, input_dir=SAMPLE, extra=None, ids=None, collected_at=COLLECTED):
    """전체 가상 스냅숏 + 입력 폴더로 화면을 만들어 (page, A)를 돌려준다."""
    tmp = new_tmp(test)
    snap = write_fake_snapshot(os.path.join(tmp, "수집"), ids=ids, extra=extra, collected_at=collected_at)
    path, A = load_approval_cli().make_screen(input_dir, os.path.join(tmp, "출력"), snap, ASOF, NOW, False)
    with open(path, encoding="utf-8") as f:
        return f.read(), A


def by_no(A):
    return {r["번호"]: r for r in A["requests_all"]}


def all_ids(A):
    return [r["id"] for r in A["data"]["requests"]]


def ssum_amounts(items):
    return sum(i["amount"] for i in items if i["amount"] is not None)


class TestApprovalDates(unittest.TestCase):
    def test_friday_after(self):
        f = mod("approval").friday_after
        D = dt.datetime
        self.assertEqual(f(D(2026, 11, 2, 0, 0)), dt.date(2026, 11, 6))
        self.assertEqual(f(D(2026, 11, 5, 13, 59)), dt.date(2026, 11, 6))
        self.assertEqual(f(D(2026, 11, 5, 14, 0)), dt.date(2026, 11, 13))
        self.assertEqual(f(D(2026, 11, 6, 9, 0)), dt.date(2026, 11, 13))
        self.assertEqual(f(D(2026, 11, 1, 18, 0)), dt.date(2026, 11, 6))
        self.assertEqual(f(D(2026, 10, 26, 11, 0)), dt.date(2026, 10, 30))

    def test_parse_registered(self):
        p = mod("approval").parse_registered
        self.assertEqual(p("2026-10-28 15:52:03"), dt.datetime(2026, 10, 28, 15, 52, 3))
        self.assertEqual(p("2026-10-28 15:52"), dt.datetime(2026, 10, 28, 15, 52))
        self.assertEqual(p("2026-10-28"), dt.datetime(2026, 10, 28))
        self.assertIsNone(p("abc"))
        self.assertIsNone(p(""))

    def test_project_code(self):
        c = mod("approval").project_code
        self.assertEqual(c("[26201] 가상 컨퍼런스"), "26201")
        self.assertEqual(c(" [26201]가상"), "26201")
        self.assertIsNone(c("가상 [26201]"))
        self.assertIsNone(c(""))


class TestApprovalRequests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        snap = write_fake_snapshot(os.path.join(cls.tmp, "수집"))
        path, cls.A = load_approval_cli().make_screen(SAMPLE, os.path.join(cls.tmp, "출력"), snap, ASOF, NOW, False)
        with open(path, encoding="utf-8") as f:
            cls.page = f.read()
        cls.S = mod("approval").scenario(cls.A, all_ids(cls.A))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_expected_dates_and_rules(self):
        r = by_no(self.A)
        self.assertEqual(r["5102"]["date"], dt.date(2026, 11, 6))
        self.assertEqual(r["5102"]["rule"], "지급요청일 없음 → 목요일 14시 승인·금요일 지급 (지금 기준)")
        self.assertEqual(r["5108"]["date"], dt.date(2026, 11, 6))
        self.assertEqual(r["5108"]["rule"], "지급요청일 지남·대기 중 → 목요일 14시 승인·금요일 지급 (지금 기준)")
        self.assertEqual(r["1201"]["rule"], "지급요청일")
        self.assertEqual(r["5104"]["date"], dt.date(2026, 10, 30))
        self.assertEqual(r["5104"]["rule"], "지급요청일 없음 → 목요일 14시 승인·금요일 지급 (등록 시각 기준)")

    def test_toggleable_and_unknown_requests(self):
        r = by_no(self.A)
        self.assertEqual(sorted(k for k, v in r.items() if v["toggle"]), ["1201", "5102", "5103", "5108"])
        self.assertEqual(r["5106"]["reason"], "금액 미확인")
        self.assertEqual([x["번호"] for x in self.A["amount_unknown"]], ["5106"])
        self.assertEqual([x["번호"] for x in self.A["status_unknown"]], ["5107"])
        self.assertEqual(ssum_amounts(self.A["status_unknown"]), 1100000)

    def test_approved_requests_against_balance_date(self):
        A = self.A
        self.assertEqual(A["balance_date"], dt.date(2026, 11, 2))
        self.assertEqual(sorted(x["번호"] for x in A["approved_future"]), ["5105", "5109"])
        self.assertEqual([x["번호"] for x in A["approved_paid"]], ["5104"])
        self.assertEqual(ssum_amounts(A["approved_paid"]), 5500000)
        self.assertEqual(A["rolled"], [])
        self.assertEqual(A["data"]["base_out"][4], 49500000 + 1845735)   # 금요일: 남은 예산 나눔 883,235 + 962,500
        self.assertEqual(A["data"]["base_out"][8], 14900000)
        r = by_no(A)
        self.assertFalse(r["5105"]["toggle"])
        self.assertFalse(r["5109"]["toggle"])

    def test_snapshot_matching(self):
        A = self.A
        self.assertEqual(len(A["replaced"]), 2)
        self.assertEqual(ssum_amounts(A["replaced"]), 93500000)
        self.assertEqual(sorted(e["project"] for e in A["unmatched_exec"]), ["P26204", "P26206"])
        self.assertEqual(A["duplicates"], [])
        self.assertEqual(A["possible_duplicates"], [])

    def test_all_checked_numbers(self):
        S = self.S
        self.assertEqual((S["low"], S["low_day"]), (83470120, "2026-12-25"))   # 남은 예산 매주 나눔: P26208 몫 8주 7,065,880 먼저
        self.assertEqual((S["est_low"], S["est_low_day"]), (105470120, "2026-12-25"))
        w = S["weeks"]
        self.assertEqual((w[0]["out"], w[0]["min"], w[0]["end"]), (55009735, 487390265, 487390265))   # 주마다 남은 예산 나눔 1,845,735 더 나감
        self.assertEqual((w[1]["in"], w[1]["out"], w[1]["min"], w[1]["end"]), (88000000, 94545735, 392844530, 480844530))
        self.assertEqual((w[2]["out"], w[2]["est_in"], w[2]["end"]), (163145735, 22000000, 317698795))
        self.assertEqual((w[7]["out"], w[7]["end"], w[7]["level"]), (54845735, 83470120, "최소보유현금 미만"))   # 12/25 몫 7,700,000 한꺼번에 → 나눔 1,845,735
        self.assertEqual([x["level"] for x in w[:7]], [""] * 7)

    def test_toggle_values_and_none_checked(self):
        r = by_no(self.A)
        tg = self.S["toggle"]
        self.assertEqual(tg[r["1201"]["id"]][0], 127470120)
        self.assertEqual(tg[r["5102"]["id"]][0], 83734120)
        self.assertEqual(tg[r["5103"]["id"]][0], 243970120)
        self.assertEqual(tg[r["5108"]["id"]][0], 85670120)
        self.assertEqual(mod("approval").scenario(self.A, [])["low"], 290434120)

    def test_unknowns_are_listed_not_summed(self):
        A = self.A
        io = lambda items, k: [e for e in items if e["io"] == k]  # noqa: E731
        self.assertEqual((len(io(A["undated"], "in")), ssum_amounts(io(A["undated"], "in"))), (1, 30000000))  # 검토 3: P26204 D사 취소 −11,000,000이 수정 8,800,000 미수를 상계
        self.assertEqual((len(io(A["undated"], "out")), ssum_amounts(io(A["undated"], "out"))), (4, 105000000))
        self.assertEqual((len(io(A["past"], "in")), ssum_amounts(io(A["past"], "in"))), (1, 110000000))
        self.assertEqual(len(io(A["past"], "out")), 0)
        self.assertEqual((len(io(A["beyond"], "in")), len(io(A["beyond"], "out"))), (1, 35))  # 남은 예산 매주 나눔: P26208 2027-02-26까지 중 8주 밖 9줄
        self.assertEqual(len(A["amount_unknown_events"]), 1)

    def test_screen_headline_and_notes(self):
        h = T(self.page, "headline")
        self.assertIn("전부 승인 시 최저 잔액 83.5 백만원 · 2026-12-25", h)
        self.assertIn("최소보유현금 미만", h)
        self.assertIn("12/21~12/27", h)
        self.assertIn("추정 입금 포함 시 최저 잔액 105.5 백만원 · 2026-12-25", T(self.page, "h-est"))
        n = T(self.page, "schedule-notes")
        for line in (
                "승인 완료·예상 지급일이 잔액 기준일(2026-11-02) 이전 또는 당일 1건 5,500,000 (잔액에 반영된 것으로 봄)",
                "잔액 기준일(2026-11-02) 이후·1주 시작(11/02) 전 일정 0건",
                "프로젝트집행.csv 요청미지급 중 인트라넷 스냅숏으로 대체 2건 (확인된 금액 93,500,000)",
                "스냅숏과 연결 안 된 프로젝트집행 요청미지급 2건 (확인된 금액 11,000,000, 금액 미확인 1건) — 일반 일정 규칙대로 반영",
                "중복 제외 0건", "중복 가능성 0건"):
            self.assertIn(line, n)

    def test_probe_a_balance_date_before_asof(self):
        folder = sample_copy(self)
        edit_csv(folder, "계좌잔액.csv", lambda rows: [r.__setitem__(0, "2026-10-30") for r in rows if r[0] == "2026-11-02"])
        edit_csv(folder, "자금일정.csv", lambda rows: rows.extend([
            ["2026-10-31", "입금", "4,000,000", "확정", "기타입금", "", "", "", ""],
            ["2026-11-01", "지급", "7,000,000", "확정", "거래처미지급", "", "", "", ""]]))
        extra = [["5110", "[26203] 가상 전시부스", "가상전기", "2026-10-29 11:00:00", "2026-11-12", "6,000,000", "2026-11-02",
                  "김철수", "승인", "승인", "승인"],
                 ["5111", "[26203] 가상 전시부스", "가상통신", "2026-10-29 11:30:00", "2026-11-12", "1,000,000", "2026-10-31",
                  "김철수", "승인", "승인", "승인"]]
        page, A = full_screen(self, folder, extra=extra)
        self.assertEqual(A["balance_date"], dt.date(2026, 10, 30))
        self.assertEqual(A["data"]["start"], 542400000)
        self.assertIn("5110", [x["번호"] for x in A["approved_future"]])
        self.assertEqual(A["data"]["base_out"][0] > 0, True)
        rolled_in = [e for e in A["rolled"] if e["io"] == "in"]
        rolled_out = [e for e in A["rolled"] if e["io"] == "out"]
        self.assertEqual((len(rolled_in), ssum_amounts(rolled_in)), (1, 4000000))
        self.assertEqual((len(rolled_out), ssum_amounts(rolled_out)), (2, 8000000))
        self.assertEqual([x["번호"] for x in A["approved_paid"]], ["5104"])
        self.assertEqual(ssum_amounts([e for e in A["past"] if e["io"] == "in"]), 110000000)
        S = mod("approval").scenario(A, all_ids(A))
        self.assertEqual((S["low"], S["low_day"]), (73470120, "2026-12-25"))
        w0 = S["weeks"][0]
        self.assertEqual((w0["in"], w0["out"], w0["min"]), (4000000, 69009735, 477390265))
        n = T(page, "schedule-notes")
        self.assertIn("잔액 기준일(2026-10-30) 이후·1주 시작(11/02) 전 일정: 입금 1건 4,000,000 · 지급 2건 8,000,000 "
                      "(1주 첫날 11/02에 반영)", n)
        self.assertIn("승인 완료·예상 지급일이 잔액 기준일(2026-10-30) 이전 또는 당일 1건 5,500,000 (잔액에 반영된 것으로 봄)", n)

    def test_accounts_with_different_dates_use_the_earliest_as_the_balance_date(self):
        """WR-05: 계좌마다 잔액 날짜가 다르면 가장 이른 날짜가 잔액 기준일. 그 뒤 지급은 일정에 넣고, 사이 입금은 두 번 넣지 않는다."""
        folder = sample_copy(self)
        edit_csv(folder, "계좌잔액.csv", lambda rows: [r.__setitem__(0, "2026-10-29") for r in rows
                                                     if r[0] == "2026-11-02" and r[1] == "급여계좌"])
        edit_csv(folder, "자금일정.csv", lambda rows: rows.extend([
            ["2026-10-31", "입금", "4,000,000", "확정", "기타입금", "", "", "", ""],
            ["2026-11-01", "지급", "7,000,000", "확정", "거래처미지급", "", "", "", ""]]))
        page, A = full_screen(self, folder)
        self.assertEqual((A["balance_date"], A["cutoff"]), (dt.date(2026, 10, 29), dt.date(2026, 10, 29)))
        out = [e for e in A["rolled"] if e["io"] == "out"]
        self.assertIn(7000000, [e["amount"] for e in out])  # 11-01 지급: 급여계좌 잔액에 없을 수 있다 → 일정에 넣음
        self.assertIn("5104", [x["번호"] for x in out if x.get("번호")])  # 승인 완료 10-30 예상 지급도 일정에 넣음
        self.assertEqual(A["approved_paid"], [])
        self.assertNotIn(4000000, [e["amount"] for e in A["rolled"] if e["io"] == "in"])  # 10-31 입금은 두 번 넣지 않음
        self.assertIn(4000000, [e["amount"] for e in A["past"] if e["io"] == "in"])
        n = T(page, "schedule-notes")
        self.assertIn("계좌별 잔액 기준일이 다름: 운영계좌 2026-11-02 · 프로젝트계좌 2026-11-02 · 급여계좌 2026-10-29"
                      " → 가장 이른 2026-10-29를 잔액 기준일로 씀", n)
        self.assertIn("잔액 기준일(2026-10-29) 이후·가장 늦은 계좌 기준일(2026-11-02) 이전 또는 당일 입금 1건 4,000,000"
                      " (잔액에 이미 있을 수 있어 일정에 넣지 않음)", n)
        self.assertIn("잔액 기준일 2026-10-29 (계좌 잔액 입력의 가장 이른 기준일)", T(page, "basis"))

    def test_probe_b_key_match_and_possible_duplicate(self):
        folder = sample_copy(self)
        edit_csv(folder, "프로젝트집행.csv", lambda rows: rows.append(
            ["P26221", "버스 임차", "가상버스", "요청미지급", "3,000,000", "300,000", "2026-11-10", "확정", "발주서"]))
        edit_csv(folder, "자금일정.csv", lambda rows: rows.append(
            ["2026-11-20", "지급", "160,500,000", "확정", "거래처미지급", "P26220", "", "계약서", ""]))
        page, A = full_screen(self, folder)
        self.assertEqual(len(A["replaced"]), 3)
        self.assertEqual(ssum_amounts(A["replaced"]), 96800000)
        S = mod("approval").scenario(A, all_ids(A))
        self.assertEqual(S["weeks"][1]["out"], 94545735)
        self.assertEqual(len(A["possible_duplicates"]), 1)
        self.assertEqual((S["low"], S["low_day"]), (-77029880, "2026-12-25"))
        self.assertIn("중복 가능성 1건 (확인된 금액 160,500,000) — 일정에 그대로 둠, 확인 필요", T(page, "schedule-notes"))

    def test_probe_c_number_duplicate_is_dropped(self):
        folder = sample_copy(self)
        edit_csv(folder, "자금일정.csv", lambda rows: rows.append(
            ["2026-11-12", "지급", "3,300,000", "확정", "거래처미지급", "", "", "지급요청 5105", ""]))
        page, A = full_screen(self, folder)
        self.assertEqual(len(A["duplicates"]), 1)
        self.assertIn("중복 제외 1건 (확인된 금액 3,300,000)", T(page, "schedule-notes"))
        S = mod("approval").scenario(A, all_ids(A))
        self.assertEqual((S["low"], S["weeks"][1]["out"]), (83470120, 94545735))

    def test_number_match_drops_an_input_line_only_when_the_request_is_scheduled(self):
        """WR-06: 번호가 같아도 스냅숏 요청이 일정에 없으면(금액 미확인 5106, 반려 5107) 입력 일정은 그대로 둔다."""
        folder = sample_copy(self)
        edit_csv(folder, "자금일정.csv", lambda rows: rows.extend([
            ["2026-11-17", "지급", "3,000,000", "확정", "거래처미지급", "", "", "지급요청 5106", ""],
            ["2026-11-12", "지급", "3,300,000", "확정", "거래처미지급", "", "", "지급요청 5105", ""]]))
        edit_csv(folder, "프로젝트집행.csv", lambda rows: rows.append(
            ["P26201", "케이터링", "가상케이터링", "요청미지급", "1,000,000", "100,000", "2026-11-06", "확정", "지급요청 5107"]))
        page, A = full_screen(self, folder)
        self.assertEqual([e["basis"] for e in A["duplicates"]], ["지급요청 5105"])  # 5105 는 승인 완료·고정 지급
        self.assertNotIn("지급요청 5107", [e["basis"] for e in A["replaced"]])
        self.assertIn("지급요청 5107", [e["basis"] for e in A["unmatched_exec"]])
        kept = sorted(e["basis"] for e in A["number_kept"])
        self.assertEqual(kept, ["지급요청 5106", "지급요청 5107"])
        S = mod("approval").scenario(A, all_ids(A))
        base = mod("approval").scenario(full_screen(self)[1], all_ids(A))
        self.assertEqual(S["weeks"][2]["out"] - base["weeks"][2]["out"], 3000000)  # 11-17 주: 5106 입력 금액이 남음
        self.assertEqual(S["weeks"][0]["out"] - base["weeks"][0]["out"], 1100000)  # 11-06 주: 5107 입력 금액이 남음
        self.assertIn("번호는 같으나 스냅숏 요청이 일정에 없어 입력 일정 유지 2건 (확인된 금액 4,100,000)", T(page, "schedule-notes"))

    def test_probe_big_pending_request(self):
        extra = [["9001", "[26201] 가상 컨퍼런스", "가상기기", "2026-11-01 10:00:00", "2026-11-20", "400,000,000", "2026-11-13",
                  "홍길동", "승인", "승인", "미승인"]]
        page, A = full_screen(self, extra=extra)
        S = mod("approval").scenario(A, all_ids(A))
        self.assertEqual(S["low"], -316529880)
        self.assertEqual(S["weeks"][0]["level"], "")
        self.assertEqual([w["level"] for w in S["weeks"][1:]], ["부족"] * 7)
        self.assertIn("부족", T(page, "headline"))

    def test_probe_unreadable_date_and_beyond_horizon(self):
        extra = [["9002", "[26201] 가상 컨퍼런스", "가상기기", "abc", "2026-11-20", "1,000,000", "", "홍길동", "승인", "승인", "미승인"],
                 ["9003", "[26201] 가상 컨퍼런스", "가상기기", "2026-11-01 10:00:00", "2026-11-20", "2,000,000", "2027-01-15",
                  "홍길동", "승인", "승인", "미승인"]]
        page, A = full_screen(self, extra=extra)
        r = by_no(A)
        self.assertEqual(r["9002"]["reason"], "날짜 확인 불가")
        self.assertFalse(r["9002"]["toggle"])
        self.assertEqual([x["번호"] for x in A["date_unknown"]], ["9002"])
        self.assertEqual([x["번호"] for x in A["beyond_requests"]], ["9003"])
        self.assertFalse(r["9003"]["toggle"])


class TestApprovalSettings(unittest.TestCase):
    def build(self, mutate):
        folder = sample_copy(self)
        edit_csv(folder, "설정.csv", mutate)
        page, A = full_screen(self, folder, ids=MINI_IDS)
        return page, A

    def issues_with(self, A, key):
        return [i for i in A["issues"] if i[0] == "설정.csv" and key in i[2]]

    def test_weeks_setting(self):
        page, A = self.build(lambda rows: set_setting(rows, "승인검토_주수", "12"))
        self.assertEqual(len(A["data"]["days"]), 84)
        self.assertEqual(len(A["data"]["weeks"]), 12)
        self.assertEqual(self.issues_with(A, "승인검토_주수"), [])

    def test_bad_weeks_fall_back_to_eight_with_issue(self):
        for value in (None, "", "abc", "0", "2.5"):
            page, A = self.build(lambda rows, v=value: set_setting(rows, "승인검토_주수", v))
            self.assertEqual(len(A["data"]["weeks"]), 8, value)
            found = self.issues_with(A, "승인검토_주수")
            self.assertTrue(found and "기본값 8 사용" in found[0][2], value)
            self.assertIn("기본값 8 사용", T(page, "issues"))

    def test_regular_categories_default_with_issue(self):
        for value in (None, ""):
            page, A = self.build(lambda rows, v=value: set_setting(rows, "승인검토_정기지출", v))
            self.assertEqual(A["regular"], ["급여", "임차료", "카드대금", "부가세"])
            found = self.issues_with(A, "승인검토_정기지출")
            self.assertTrue(found and "기본값 사용" in found[0][2], value)

    def test_regular_categories_custom(self):
        page, A = self.build(lambda rows: set_setting(rows, "승인검토_정기지출", "급여, 임차료"))
        self.assertEqual(A["regular"], ["급여", "임차료"])

    def test_regenerated_sample_has_both_rows_and_no_issue(self):
        with open(os.path.join(SAMPLE, "설정.csv"), encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[-2:], [["승인검토_주수", "8"], ["승인검토_정기지출", "급여,임차료,카드대금,부가세"]])
        self.assertEqual(rows[8][0], "예산_원가율")  # 파일 9번째 줄 (머리글 포함)
        page, A = full_screen(self, ids=MINI_IDS)
        self.assertEqual([i for i in A["issues"] if "승인검토" in i[2]], [])


class TestReportsUnchanged(unittest.TestCase):
    def reports(self, folder):
        calc, data, render = mod("calc"), mod("data"), mod("render")
        d = data.load(folder)
        out = []
        for kind, asof in (("weekly", dt.date(2026, 11, 2)), ("monthly", dt.date(2026, 10, 31))):
            R = calc.compute(d, kind, asof)
            for mode in ("ceo", "mgmt"):
                out.append(STAMP_RE.sub("", render.render(R, mode)))
        return out

    def test_reports_identical_with_or_without_new_settings(self):
        with_rows = sample_copy(self)
        without = sample_copy(self)
        edit_csv(with_rows, "설정.csv", lambda rows: (set_setting(rows, "승인검토_주수", "8"),
                                                     set_setting(rows, "승인검토_정기지출", "급여,임차료,카드대금,부가세")))
        edit_csv(without, "설정.csv", lambda rows: (set_setting(rows, "승인검토_주수", None),
                                                   set_setting(rows, "승인검토_정기지출", None)))
        self.assertEqual(self.reports(with_rows), self.reports(without))

    def test_build_does_not_change_loaded_data(self):
        data, calc = mod("data"), mod("approval")
        d = data.load(SAMPLE)
        before = (copy.deepcopy(d.issues.items), copy.deepcopy(d.schedule), copy.deepcopy(d.execs))
        tmp = new_tmp(self)
        snapshot = mod("snapshot")
        snap = snapshot.read_snapshot(write_fake_snapshot(tmp))
        calc.build(d, snap, ASOF, NOW)
        self.assertEqual((d.issues.items, d.schedule, d.execs), before)

    def test_profit_file_is_not_an_approval_input(self):
        base_page, base = full_screen(self)
        folder = sample_copy(self)
        os.remove(os.path.join(folder, "손익.csv"))
        page, A = full_screen(self, folder)
        sc = mod("approval").scenario
        self.assertEqual(sc(A, all_ids(A)), sc(base, all_ids(base)))


# ───────────── plan 01.1-04 Task 1: 미확인 항목 화면 (APPR-04) ─────────────
def cell_text(row, cls):
    """tr 안쪽 HTML에서 class 가 cls 인 td 글. 없으면 None."""
    m = re.search(r'<td[^>]*class="[^"]*\b%s\b[^"]*"[^>]*>(.*?)</td>' % re.escape(cls), row or "", re.S)
    return text_of(m.group(1)) if m else None


def rows_of(fragment):
    """표 안쪽 HTML의 tr 들 (머리글 제외)."""
    return [m for m in re.findall(r"<tr[^>]*>.*?</tr>", fragment or "", re.S) if "<td" in m]


def build_screen(test, mutate_input=None, extra=None):
    """(page, A): 가상 스냅숏 전체 + 입력 폴더(필요하면 고쳐서)로 만든 화면."""
    folder = SAMPLE
    if mutate_input is not None:
        folder = sample_copy(test)
        mutate_input(folder)
    return full_screen(test, folder, extra=extra)


class TestApprovalPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        snap = write_fake_snapshot(os.path.join(cls.tmp, "수집"))
        path, cls.A = load_approval_cli().make_screen(SAMPLE, os.path.join(cls.tmp, "출력"), snap, ASOF, NOW, False)
        with open(path, encoding="utf-8") as f:
            cls.page = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_unknowns_panel_lines(self):
        u = T(self.page, "unknowns")
        for line in (
                "금액 미확인 요청 1건 (일정 제외)",
                "날짜 미확인 요청 0건 (일정 제외)",
                "상태 확인 필요 1건 (일정 제외, 확인된 금액 1,100,000)",
                "지급요청일 없음 2건 (목요일 14시 승인 → 금요일 지급 규칙으로 계산)",
                "지급요청일 지남·대기 중 1건 (목요일 14시 승인 → 금요일 지급 규칙으로 다시 계산)",
                "날짜 없는 예정 금액: 입금 1건 30,000,000 · 지급 4건 105,000,000",  # 검토 3: P26204 D사 취소 −11,000,000이 수정 8,800,000 미수를 상계
                "예정일이 잔액 기준일(2026-11-02) 이전 또는 당일인 미처리: 입금 1건 110,000,000 · 지급 0건",
                "기간 밖(8주 이후): 입금 1건 · 지급 35건 · 대기 요청 0건",
                "잔액 미확인 0계좌",
                "부가세 미확인 일정 0건 (공급가액만 반영)"):
            self.assertIn(line, u)

    def test_panel_is_counts_of_the_lists(self):
        P = self.A["panel"]
        self.assertEqual(P["amount_unknown"]["n"], len(self.A["amount_unknown"]))
        self.assertEqual((P["status_unknown"]["n"], P["status_unknown"]["sum"]), (1, 1100000))
        self.assertEqual(P["undated"]["n"], 5)  # 검토 3: P26204 D사 취소 −11,000,000이 수정 8,800,000 미수를 상계
        self.assertEqual((P["pending"]["n"], P["pending"]["sum"], P["pending"]["unknown"]), (5, 206964000, 1))

    def test_unknown_amount_event_is_listed_not_summed(self):
        u = T(self.page, "unknowns")
        self.assertIn("금액 미확인 일정 1건 (일정 제외)", u)

    def test_scope_line_and_amount_cells(self):
        self.assertEqual(T(self.page, "req-scope"), "대기 요청 5건 · 확인된 금액 합계 206,964,000 · 금액 미확인 1건")
        r = by_no(self.A)
        self.assertEqual(cell_text(row_html(self.page, r["5106"]["id"]), "r-amt"), "미확인")
        for rq in self.A["requests_all"]:
            self.assertNotEqual(cell_text(row_html(self.page, rq["id"]), "r-amt"), "0", rq["번호"])

    def test_scope_line_all_unknown_amounts_is_not_zero(self):
        folder_page, A = full_screen(self, ids=("5106",))
        self.assertEqual(T(folder_page, "req-scope"), "대기 요청 1건 · 확인된 금액 합계 없음 · 금액 미확인 1건")

    def test_stage_columns(self):
        row = row_html(self.page, by_no(self.A)["5103"]["id"])
        self.assertEqual([cell_text(row, c) for c in ("s-team", "s-mgmt", "s-boss")], ["수락요청중", "미승인", "미승인"])
        for h in ("팀장승인", "관리팀승인", "사장님승인"):
            self.assertIn(h, T(self.page, "requests"))

    def test_approved_table(self):
        frag = element_html(self.page, "approved")
        self.assertIsNotNone(frag)
        rows = rows_of(frag)
        self.assertEqual([cell_text(x, "a-no") for x in rows], ["5109", "5105"])
        self.assertEqual([cell_text(x, "a-date") for x in rows], ["2026-11-06", "2026-11-10"])
        self.assertEqual([cell_text(x, "a-amt") for x in rows], ["49,500,000", "3,300,000"])
        self.assertNotIn("<input", frag)

    def test_probe_a_past_line_names_the_balance_date(self):
        page, A = build_screen(self, lambda folder: edit_csv(
            folder, "계좌잔액.csv", lambda rows: [r.__setitem__(0, "2026-10-30") for r in rows if r[0] == "2026-11-02"]))
        self.assertIn("예정일이 잔액 기준일(2026-10-30) 이전 또는 당일인 미처리: 입금 1건 110,000,000 · 지급 0건",
                      T(page, "unknowns"))


# ───────────── plan 01.1-04 Task 2: A-5, A-6, 계산 기준, 글자·단위 ─────────────
FORBIDDEN_WORDS = ("위험", "해결방안", "권고", "우려", "추천")


def scenario_of(A):
    return mod("approval").scenario(A, all_ids(A))


class TestApprovalProjects(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        snap = write_fake_snapshot(os.path.join(cls.tmp, "수집"))
        path, cls.A = load_approval_cli().make_screen(SAMPLE, os.path.join(cls.tmp, "출력"), snap, ASOF, NOW, False)
        with open(path, encoding="utf-8") as f:
            cls.page = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_project_rows(self):
        rows = {p["code"]: p for p in self.A["projects"]}
        self.assertEqual([p["code"] for p in self.A["projects"]], ["26201", "26220", "26221", "26203"])
        self.assertEqual((rows["26201"]["budget"], rows["26201"]["requested"], rows["26201"]["remaining"]),
                         (300000000, 44264000, 255736000))
        self.assertEqual((rows["26220"]["budget"], rows["26220"]["requested"]), (250000000, 166000000))
        self.assertEqual((rows["26203"]["budget"], rows["26203"]["requested"]), (60000000, 49500000))
        self.assertEqual(rows["26201"]["name"], "가상 컨퍼런스")
        self.assertEqual(rows["26201"]["state"], "")
        r = rows["26221"]
        self.assertIsNone(r["budget"])
        self.assertIsNone(r["requested"])
        self.assertEqual((r["requested_unknown"], r["state"]), (1, "판단 불가"))
        self.assertIsNone(r["remaining"])

    def test_unrequested_table_and_summary(self):
        frag = element_html(self.page, "unrequested")
        rows = rows_of(frag)
        self.assertEqual([cell_text(x, "u-code") for x in rows], ["26201", "26220", "26203"])
        self.assertEqual([cell_text(x, "u-remaining") for x in rows], ["255,736,000", "84,000,000", "10,500,000"])
        self.assertNotIn("26221", text_of(frag))
        self.assertEqual([x["code"] for x in self.A["unrequested"]], ["26201", "26220", "26203"])
        self.assertIn("표시 3건 / 전체 3건 / 합계 350,236,000", T(self.page, "unrequested-sum"))

    def test_unknowns_a6_lines(self):
        u = T(self.page, "unknowns")
        self.assertIn("프로젝트 미연결 1건 (확인된 금액 2,200,000)", u)
        self.assertIn("미요청 실행가 (참고, 일정 제외, 부가세 기준 미확인): 표시 3건 / 전체 3건 / 합계 350,236,000, "
                      "판단 불가 1건", u)
        self.assertIn("부가세 일정 미등록", u)
        self.assertEqual((self.A["unlinked"]["n"], self.A["unlinked"]["sum"]), (1, 2200000))
        self.assertEqual(self.A["regular_missing"], ["부가세"])

    def test_a5_probe_missing_payroll(self):
        page, A = build_screen(self, lambda folder: edit_csv(
            folder, "자금일정.csv", lambda rows: rows.__setitem__(slice(None), [r for r in rows if r[4:5] != ["급여"]])))
        self.assertEqual(A["regular_missing"], ["급여", "부가세"])
        self.assertIn("급여, 부가세 일정 미등록", T(page, "unknowns"))

    def test_a6_probe_unlinked_request(self):
        extra = [["9100", "가상 미연결 행사", "가상기기", "2026-11-01 10:00:00", "2026-11-20", "1,000,000", "2026-11-13",
                  "홍길동", "승인", "승인", "미승인"]]
        page, A = build_screen(self, extra=extra)
        self.assertIn("프로젝트 미연결 2건 (확인된 금액 3,200,000)", T(page, "unknowns"))
        self.assertEqual(A["unlinked"]["n"], 2)

    def test_unrequested_never_enters_the_schedule(self):
        snapshot = mod("snapshot")
        tmp = new_tmp(self)
        projects = [list(r) for r in FAKE_PROJECTS]
        for r in projects:
            r[12] = "999,000,000"  # 실행가를 바꿔도 일정은 그대로여야 한다
        snap = snapshot.write_snapshot(os.path.join(tmp, "수집"), COLLECTED, as_dicts(FAKE_PAYMENTS, snapshot.PAYMENT_COLUMNS),
                                       as_dicts(projects, snapshot.PROJECT_COLUMNS))
        path, A2 = load_approval_cli().make_screen(SAMPLE, os.path.join(tmp, "출력"), snap, ASOF, NOW, False)
        self.assertNotEqual([p["remaining"] for p in A2["projects"]], [p["remaining"] for p in self.A["projects"]])
        self.assertEqual(scenario_of(A2), scenario_of(self.A))
        self.assertEqual(A2["data"], self.A["data"])

    def test_duplicate_project_key_is_not_judged(self):
        snapshot = mod("snapshot")
        tmp = new_tmp(self)
        projects = [list(r) for r in FAKE_PROJECTS] + [list(FAKE_PROJECTS[0])]
        snap = snapshot.write_snapshot(os.path.join(tmp, "수집"), COLLECTED, as_dicts(FAKE_PAYMENTS, snapshot.PAYMENT_COLUMNS),
                                       as_dicts(projects, snapshot.PROJECT_COLUMNS))
        path, A2 = load_approval_cli().make_screen(SAMPLE, os.path.join(tmp, "출력"), snap, ASOF, NOW, False)
        states = [p["state"] for p in A2["projects"] if p["code"] == "26201"]
        self.assertEqual(states, ["판단 불가", "판단 불가"])
        self.assertNotIn("26201", [p["code"] for p in A2["unrequested"]])

    def test_requested_total_covering_the_budget_is_counted(self):
        extra = [["9101", "[26203] 가상 전시부스", "가상기기", "2026-11-01 10:00:00", "2026-11-20", "20,000,000", "2026-11-13",
                  "김철수", "승인", "승인", "미승인"]]
        page, A = build_screen(self, extra=extra)
        self.assertEqual(A["over_requested"], 1)
        self.assertEqual([p["code"] for p in A["unrequested"]], ["26201", "26220"])
        self.assertIn("요청 누계가 실행가 이상 1건", T(page, "unrequested-sum"))

    def test_basis_lines(self):
        b = T(self.page, "basis")
        for k in range(1, 7):
            self.assertIn("가정 %d " % k, b)
        for line in ("가정 1 대기 요청 = 사장님승인이 '승인'이 아닌 요청(팀장·관리팀 단계 포함) · 상태 확인 필요 1건",
                     "지급요청일 없음 2건", "지급요청일 지남·대기 중 1건",
                     "확정 지급 2건", "잔액 반영 1건",
                     "금액 미확인 1건은 0이 아니라 일정에서 제외",
                     "일정이 없는 분류 부가세", "프로젝트 미연결 1건",
                     "잔액 기준일 2026-11-02", "1주 시작(11/02)", "대체 2건"):
            self.assertIn(line, b)

    def test_issues_block_lists_input_issues(self):
        page, A = build_screen(self, lambda folder: edit_csv(
            folder, "설정.csv", lambda rows: set_setting(rows, "승인검토_주수", "abc")))
        n = len(A["issues"])
        self.assertGreaterEqual(n, 1)
        self.assertIn("입력 자료 확인 필요 %d건" % n, T(page, "issues"))
        self.assertIn("기본값 8 사용", T(page, "issues"))
        self.assertIn("입력 자료 확인 필요 %d건 → 아래 상세" % n, T(page, "attention"))


class TestApprovalLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        snap = write_fake_snapshot(os.path.join(cls.tmp, "수집"))
        path, cls.A = load_approval_cli().make_screen(SAMPLE, os.path.join(cls.tmp, "출력"), snap, ASOF, NOW, False)
        with open(path, encoding="utf-8") as f:
            cls.page = f.read()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_attention_line(self):
        t = T(self.page, "attention")
        self.assertTrue(t.startswith("확인 필요: 금액 미확인 요청 1건 · 상태 확인 필요 1건 · 날짜 없는 예정 금액 5건 · "
                                     "프로젝트 미연결 1건 · 부가세 일정 미등록"), t)
        self.assertTrue(t.endswith(" → 아래 상세"), t)
        tail = len(self.A["issues"])
        if tail:
            self.assertIn(" · 입력 자료 확인 필요 %d건 → 아래 상세" % tail, t)
        else:
            self.assertTrue(t.endswith("부가세 일정 미등록 → 아래 상세"), t)

    def test_every_item_links_to_unknowns(self):
        frag = element_html(self.page, "attention")
        hrefs = re.findall(r'<a [^>]*href="([^"]*)"', frag)
        self.assertGreaterEqual(len(hrefs), 5)
        self.assertEqual(set(hrefs), {"#unknowns"})

    def test_nothing_to_report(self):
        A = copy.deepcopy(self.A)

        def zero(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k in ("n", "unknown") and isinstance(v, int):
                        node[k] = 0
                    elif k == "sum":
                        node[k] = None
                    else:
                        zero(v)

        zero(A["panel"])
        A["regular_missing"] = []
        A["unlinked"] = {"n": 0, "sum": None, "unknown": 0}
        A["issues"] = []
        page = mod("approval_render").render_approval(A, False)
        self.assertEqual(T(page, "attention"), "확인 필요 항목 없음")

    def test_block_order(self):
        p = self.page
        marks = ["<h1", 'id="headline"', 'id="h-est"', 'id="start-line"', 'id="attention"', 'id="req-scope"',
                 '<table id="requests"', '<table id="weeks"', '<table id="approved"', 'id="schedule-notes"',
                 'id="unknowns"', '<table id="unrequested"', 'id="basis"', 'id="issues"']
        at = [p.index(m) for m in marks]
        self.assertEqual(at, sorted(at), list(zip(marks, at)))
        self.assertEqual(len(set(at)), len(at))


class TestApprovalEscapingAndUnits(unittest.TestCase):
    def test_intranet_text_is_escaped(self):
        snapshot = mod("snapshot")
        tmp = new_tmp(self)
        extra = [["9200", "<script>alert(1)</script>", '"><img src=x onerror=alert(1)>', "2026-11-01 10:00:00", "2026-11-20",
                  "1,000,000", "2026-11-13", "<b>등록자</b>", "승인", "승인", "미승인"],
                 ["9201", "[26201] 가상 컨퍼런스", "가상기기", "2026-11-01 10:00:00", "2026-11-20", "9,000,000", "2026-11-13",
                  "홍길동", "<i>x</i>", "승인", "미승인"]]
        projects = [list(r) for r in FAKE_PROJECTS]
        projects[0][5] = "[26201]<script>alert(2)</script>"
        snap = snapshot.write_snapshot(os.path.join(tmp, "수집"), COLLECTED,
                                       as_dicts([list(r) for r in FAKE_PAYMENTS] + extra, snapshot.PAYMENT_COLUMNS),
                                       as_dicts(projects, snapshot.PROJECT_COLUMNS))
        path, A = load_approval_cli().make_screen(SAMPLE, os.path.join(tmp, "출력"), snap, ASOF, NOW, False)
        with open(path, encoding="utf-8") as f:
            page = f.read()
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("&quot;&gt;&lt;img", page)
        self.assertIn("&lt;script&gt;alert(2)&lt;/script&gt;", page)
        self.assertIn("&lt;i&gt;x&lt;/i&gt;", page)
        for raw in ("<script>alert(1)", "<img src=x", "<script>alert(2)", "<i>x</i>", "<b>등록자"):
            self.assertNotIn(raw, page)
        payload = script_text(page, "approval-data")
        for name in ("alert", "img", "등록자", "가상기기", "가상 미연결"):
            self.assertNotIn(name, payload)
        self.assertEqual(json.loads(payload), A["data"])

    @unittest.skipIf(shutil.which("node") is None, "node 없음")
    def test_formatters_agree_between_python_and_js(self):
        a, util = mod("approval"), mod("util")
        man_cases = [(98236000, "98.2"), (250000, "0.3"), (350000, "0.4"), (-301764000, "−301.8"), (0, "0.0"),
                     (30000, "30,000원"), (-49999, "−49,999원"), (None, "미확인")]
        won_cases = [264000, -1100000, 0]
        for v, text in man_cases:
            self.assertEqual(a.fmt_man(v), text, v)
        for v in won_cases:
            self.assertEqual(a.fmt_won(v), util.won(v))
        tmp = new_tmp(self)
        page, A = full_screen(self)
        js = script_text(page, "approval-calc")
        path = os.path.join(tmp, "fmt.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(js + "\nconsole.log(JSON.stringify([%s, %s]));\n" % (
                json.dumps([v for v, _ in man_cases]) + ".map(fmtMan)", json.dumps(won_cases) + ".map(fmtWon)"))
        out = subprocess.run(["node", path], check=True, stdout=subprocess.PIPE).stdout.decode("utf-8")
        got_man, got_won = json.loads(out)
        self.assertEqual(got_man, [t for _, t in man_cases])
        self.assertEqual(got_won, [util.won(v) for v in won_cases])

    def test_no_recommendation_words(self):
        page, A = full_screen(self)
        for w in FORBIDDEN_WORDS:
            self.assertNotIn(w, page)
        self.assertNotIn("위험_최소보유현금", page)
        self.assertIn("최소 보유현금", page)


# ───────────── plan 01.1-04 Task 3: 실제 브라우저 (APPR-01) ─────────────
def class_screen(cls):
    """setUpClass 안에서 쓰는 full_screen: (page, A)."""
    tmp = tempfile.mkdtemp()
    cls.addClassCleanup(shutil.rmtree, tmp, True)
    snap = write_fake_snapshot(os.path.join(tmp, "수집"))
    path, A = load_approval_cli().make_screen(SAMPLE, os.path.join(tmp, "출력"), snap, ASOF, NOW, False)
    with open(path, encoding="utf-8") as f:
        return f.read(), A


_REPORT_CLI = None


def load_report_cli():
    """보고서.py를 경로로 읽는다 (find_browser 를 쓰려고)."""
    global _REPORT_CLI
    if _REPORT_CLI is None:
        spec = importlib.util.spec_from_file_location("report_cli", os.path.join(ROOT, "보고서.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _REPORT_CLI = m
    return _REPORT_CLI


MIN_WINDOW_WIDTH = 500


def browser_dom(test, page, script, size=(1280, 900)):
    """화면 파일 뒤에 script 를 붙여 헤드리스 브라우저로 열고, 끝난 뒤의 DOM 글을 돌려준다.

    네트워크 없이 file:// 로만 연다. 보고서.py to_pdf 와 같은 머리 없는 실행 옵션을 쓴다."""
    browser = load_report_cli().find_browser()
    if browser is None:
        test.skipTest("브라우저 없음")
    tmp = new_tmp(test)
    path = os.path.join(tmp, "screen.html")
    assert "</body>" in page
    doc = page.replace("</body>", "<script>%s</script></body>" % script)
    if size[0] < MIN_WINDOW_WIDTH:
        # 이 브라우저는 창을 500px 아래로 줄이지 못한다(--window-size=390,844 도 500x701 이 된다).
        # 폭 390px 의 iframe 안에 화면을 넣어, 그 안의 배치 폭과 미디어 쿼리가 390px 로 계산되게 한다.
        inner = json.dumps(doc).replace("</", "<\\/").replace("<!--", "<\\!--")
        doc = ('<!DOCTYPE html><html><body style="margin:0"><iframe id="f" style="width:%dpx;height:%dpx;border:0"></iframe>'
               '<script>var f=document.getElementById("f");f.onload=function(){var a=f.contentDocument.body.attributes;'
               'for(var i=0;i<a.length;i++){if(a[i].name.indexOf("data-")===0)document.body.setAttribute(a[i].name,a[i].value);}};'
               'f.srcdoc=%s;</script></body></html>') % (size[0], size[1], inner)
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    profile = os.path.join(tmp, "profile")
    cmd = [browser, "--headless", "--disable-gpu", "--user-data-dir=" + profile, "--no-first-run",
           "--disable-field-trial-config", "--disable-background-networking", "--disable-component-update",
           "--window-size=%d,%d" % size, "--dump-dom", pathlib_uri(path)]
    if os.name != "nt":
        cmd.insert(2, "--no-sandbox")
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120)
    return r.stdout.decode("utf-8", "replace")


def pathlib_uri(path):
    import pathlib
    return pathlib.Path(path).resolve().as_uri()


def body_attr(dom, name):
    m = re.search(r"<body[^>]*\b%s=\"([^\"]*)\"" % re.escape(name), dom)
    return m.group(1) if m else None


UNCHECK_5103 = """
(function(){
  var tr=document.querySelector('tr[data-no="5103"]');
  var box=tr.querySelector('input.req');
  var t0=performance.now();
  box.checked=false;
  box.dispatchEvent(new Event('change',{bubbles:true}));
  document.body.setAttribute('data-ms',String(performance.now()-t0));
})();
"""


class TestApprovalBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page, cls.A = class_screen(cls)

    def test_uncheck_updates_headline_in_under_a_second(self):
        dom = browser_dom(self, self.page, UNCHECK_5103)
        self.assertEqual(T(dom, "h-low"), "244.0")
        self.assertEqual(T(dom, "h-label"), "체크한 3건 승인 시")
        self.assertEqual(week_cell(dom, 7, "w-level"), "")
        ms = body_attr(dom, "data-ms")
        self.assertIsNotNone(ms, "주입한 시간 측정이 돌지 않음")
        self.assertLess(float(ms), 1000)

    def test_screen_file_is_git_ignored(self):
        if shutil.which("git") is None:
            self.skipTest("git 없음")
        r = subprocess.run(["git", "check-ignore", "-q", "출력/승인검토_20261102_0900.html"], cwd=ROOT)
        self.assertEqual(r.returncode, 0)


@unittest.skipIf(shutil.which("node") is None, "node 없음")
class TestApprovalSpeed(unittest.TestCase):
    def test_56_days_500_requests_all_toggles_under_a_second(self):
        page, A = full_screen(self)
        js = script_text(page, "approval-calc")
        tmp = new_tmp(self)
        path = os.path.join(tmp, "speed.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(js + """
var days=[],bi=[],bo=[],ei=[],reqs=[],ids=[],i;
for(i=0;i<56;i++){days.push('d'+i);bi.push(1000);bo.push(500);ei.push(10);}
for(i=0;i<500;i++){reqs.push({id:'r'+i,day:i%56,amount:100000+i});ids.push('r'+i);}
var data={asof:'d0',start:1000000000,reserve:1000,days:days,
  weeks:[[0,6],[7,13],[14,20],[21,27],[28,34],[35,41],[42,48],[49,55]],
  base_in:bi,base_out:bo,est_in:ei,requests:reqs};
var t0=Date.now();var r=approvalCalc(data,ids);var ms=Date.now()-t0;
console.log(JSON.stringify({ms:ms,toggles:Object.keys(r.toggle).length}));
""")
        out = json.loads(subprocess.run(["node", path], check=True, stdout=subprocess.PIPE).stdout.decode("utf-8"))
        self.assertEqual(out["toggles"], 500)
        self.assertLess(out["ms"], 1000)


MEASURE = """
(function(){
  var b=document.body;
  var tr=document.querySelector('tr[data-no="5103"]');
  var td=tr.querySelector('td');
  var lab=td.querySelector('label');
  var tw=document.getElementById('requests').parentNode;
  b.setAttribute('data-iw',String(window.innerWidth));
  b.setAttribute('data-sw',String(document.documentElement.scrollWidth));
  b.setAttribute('data-pos',getComputedStyle(td).position);
  b.setAttribute('data-left',getComputedStyle(td).left);
  b.setAttribute('data-lh',String(lab.getBoundingClientRect().height));
  b.setAttribute('data-twsw',String(tw.scrollWidth));
  b.setAttribute('data-twcw',String(tw.clientWidth));
  b.setAttribute('data-class',tw.className);
})();
"""


class TestApprovalWidths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page, cls.A = class_screen(cls)

    def test_phone_width(self):
        dom = browser_dom(self, self.page, MEASURE, size=(390, 844))
        self.assertEqual(float(body_attr(dom, "data-iw")), 390)
        self.assertLessEqual(float(body_attr(dom, "data-sw")), 390)
        self.assertEqual(body_attr(dom, "data-pos"), "sticky")
        self.assertEqual(body_attr(dom, "data-left"), "0px")
        self.assertGreaterEqual(float(body_attr(dom, "data-lh")), 44)
        self.assertEqual(body_attr(dom, "data-class"), "tw")

    def test_desk_width_shows_every_request_column(self):
        dom = browser_dom(self, self.page, MEASURE, size=(1280, 900))
        self.assertEqual(float(body_attr(dom, "data-iw")), 1280)
        self.assertLessEqual(float(body_attr(dom, "data-sw")), 1280)
        self.assertEqual(body_attr(dom, "data-twsw"), body_attr(dom, "data-twcw"))


CLICK_BUTTONS = """
(function(){
  var b=document.body;
  function snap(tag){
    b.setAttribute('data-'+tag+'-label',document.getElementById('h-label').textContent);
    b.setAttribute('data-'+tag+'-low',document.getElementById('h-low').textContent);
    var dis=document.querySelector('tr[data-no="5106"] input.req');
    b.setAttribute('data-'+tag+'-dis',String(dis.checked));
  }
  document.getElementById('check-none').click();
  snap('none');
  document.getElementById('check-all').click();
  snap('all');
})();
"""


class TestApprovalControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page, cls.A = class_screen(cls)

    def test_buttons_exist_with_labels_and_touch_height(self):
        self.assertEqual(T(self.page, "check-all"), "전부 체크")
        self.assertEqual(T(self.page, "check-none"), "전부 해제")
        self.assertLess(self.page.index('id="check-all"'), self.page.index('<table id="requests"'))
        self.assertRegex(self.page, r"button[^{]*\{[^}]*min-height:44px")

    def test_headline_is_a_polite_live_region(self):
        self.assertRegex(self.page, r'<div[^>]*id="headline"[^>]*aria-live="polite"')

    def test_check_none_and_check_all_in_a_browser(self):
        dom = browser_dom(self, self.page, CLICK_BUTTONS)
        self.assertEqual(body_attr(dom, "data-none-label"), "체크한 0건 승인 시")
        self.assertEqual(body_attr(dom, "data-none-low"), "290.4")
        self.assertEqual(body_attr(dom, "data-all-label"), "전부 승인 시")
        self.assertEqual(body_attr(dom, "data-all-low"), "83.5")
        self.assertEqual(body_attr(dom, "data-none-dis"), "false")
        self.assertEqual(body_attr(dom, "data-all-dis"), "false")

    def test_page_has_no_network_or_external_resource(self):
        self.assertIsNone(re.search(r"fetch\(|XMLHttpRequest|src=|https?://", self.page))


if __name__ == "__main__":
    unittest.main()
