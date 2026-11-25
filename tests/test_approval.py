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




# ───────────── plan 01.1-04 Task 2: A-5, A-6, 계산 기준, 글자·단위 ─────────────
FORBIDDEN_WORDS = ("위험", "해결방안", "권고", "우려", "추천")


def scenario_of(A):
    return mod("approval").scenario(A, all_ids(A))








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
        m.PDF_WAIT = 0.5  # 시험: PDF 가 안 생기는 경우를 오래 기다리지 않게
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
