"""승인 검토 화면 테스트. 실행: python3 -m unittest discover -s tests

시험 자료는 전부 가상이다 (D-28). 실제 회사 자료를 읽거나 베끼지 않는다.
ceo_report 모듈은 시험 안에서 불러온다: 모듈이 없으면 해당 시험만 실패한다.
"""
import contextlib
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

SAMPLE = os.path.join(ROOT, "입력")
ASOF = dt.date(2026, 11, 2)
NOW = dt.datetime(2026, 11, 2, 0, 0)
COLLECTED = dt.datetime(2026, 11, 1, 18, 0, 0)


def mod(name):
    """ceo_report 모듈을 시험 안에서 불러온다."""
    return importlib.import_module("ceo_report." + name)


def setUpModule():
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_sample.py")], check=True,
                   stdout=subprocess.DEVNULL)


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
        cls.rc, cls.stdout = run_cli(["--기준일", "2026-11-02", "--수집폴더", cls.root, "--출력", cls.out, "--열기", "안함"])
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
        self.assertIn("전부 승인 시 최저 잔액 104.0 백만원 · 2026-12-25", h)
        self.assertIn("부족·최소보유현금 미만 주 없음", h)
        open_tag = re.search(r'<div[^>]*id="headline"[^>]*>', p).group(0)
        self.assertNotIn("lv-short", open_tag)
        self.assertNotIn("lv-reserve", open_tag)
        self.assertEqual(T(p, "h-sum"), "(체크 합계 204,500,000원)")

    def test_estimate_line_and_start_line(self):
        p = self.page
        self.assertIn("추정 입금 포함 시 최저 잔액 126.0 백만원 · 2026-12-25", T(p, "h-est"))
        s = T(p, "start-line")
        self.assertIn("시작 잔액(사용 가능액) 542.4 백만원", s)
        self.assertIn("잔액 기준일 2026-11-02", s)
        self.assertIn("인트라넷 수집 시각 2026-11-01 18:00:00 (마지막 스냅숏)", s)
        self.assertEqual(T(p, "snap-age"), "기준일보다 1일 전 수집")

    def test_requests_checked_and_toggle_cells(self):
        p = self.page
        self.assertEqual(sorted(checked_req_ids(p)), ["r0", "r1"])
        r0, r1 = row_html(p, "r0"), row_html(p, "r1")
        self.assertEqual(span_text(r0, "r-toggle-v"), "148.0")
        self.assertEqual(span_text(r1, "r-toggle-v"), "264.5")
        self.assertEqual(span_text(r0, "r-mode"), "빼면")
        self.assertLess(p.index('data-id="r0"'), p.index('data-id="r1"'))
        self.assertIn("1201 가상음향 44,000,000 승인 가정", text_of(r0))

    def test_week_cells_and_css(self):
        p = self.page
        self.assertEqual(week_cell(p, 0, "w-out"), "50,700,000")
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
        rc, out = run_cli(["--기준일", "2026-11-02", "--수집폴더", empty, "--출력", os.path.join(empty, "o"), "--열기", "안함"])
        self.assertEqual(rc, 2)
        self.assertIn("인트라넷 수집 스냅숏이 없습니다", out)
        rc, _ = run_cli(["--기준일", "2026-13-45", "--수집폴더", self.root, "--출력", os.path.join(empty, "o"), "--열기", "안함"])
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


if __name__ == "__main__":
    unittest.main()
