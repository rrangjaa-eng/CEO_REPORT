"""QA 회귀 시험 (.planning/QA-REPORT.md). 시험 자료는 전부 가상이다: 샘플 입력, 가상 스냅숏, 가상 엑셀만 쓴다.

다른 시험 파일에서는 함수와 상수만 가져온다 (TestCase 클래스를 가져오면 시험이 두 번 돈다).
"""
import csv
import datetime as dt
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

from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import render  # noqa: E402
from sample_input import SAMPLE, refresh as refresh_sample  # noqa: E402
from test_approval import T, load_approval_cli, write_fake_snapshot  # noqa: E402

ASOF = dt.date(2026, 11, 2)
NOW = dt.datetime(2026, 11, 2, 0, 0)
OUT_FILES = ("자금일정.csv", "프로젝트집행.csv")


def setUpModule():
    refresh_sample()


def new_tmp(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    return tmp


def sample_copy(test):
    folder = os.path.join(new_tmp(test), "입력")
    shutil.copytree(SAMPLE, folder)
    return folder


def rewrite(folder, name, mutate=None, encoding="utf-8-sig", delimiter=","):
    """CSV 한 개를 읽어 mutate(rows)로 고치고 다른 인코딩·구분자로 다시 쓴다."""
    path = os.path.join(folder, name)
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if mutate:
        mutate(rows)
    with open(path, "w", encoding=encoding, newline="") as f:
        csv.writer(f, delimiter=delimiter).writerows(rows)


def drop_column(col):
    def mutate(rows):
        i = rows[0].index(col)
        for r in rows:
            del r[i]
    return mutate


def run_report(test, argv, out=None):
    """보고서.py main 을 부르고 (종료 코드, 출력 글)을 돌려준다. --출력 이 없으면 임시 폴더를 쓴다."""
    import contextlib
    import io
    from test_approval import load_report_cli
    if "--출력" not in argv:
        argv = list(argv) + ["--출력", out or os.path.join(new_tmp(test), "출력")]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = load_report_cli().main(argv)
    return rc, buf.getvalue()


def kpi(html, label):
    m = re.search(r"<div class='l'>" + re.escape(label) + r"</div><div class='v'>(.*?)</div><div class='s'>(.*?)</div>",
                  html, re.S)
    return (m.group(1), m.group(2)) if m else (None, None)


def text(fragment):
    return re.sub(r"<[^>]+>", "", fragment or "")


class TestOutflowFileUnusable(unittest.TestCase):
    """지급 자료 파일(자금일정·프로젝트집행)이 없거나 읽을 수 없으면 최저 계산 잔액을 숫자로 만들지 않는다.

    전에는 파일이 없거나(UTF-16 저장·머리글 다름 포함) 지급 0원으로 계산해 첫 화면에 안전해 보이는 최저 잔액이 나왔다.
    """

    def report(self, folder):
        R = compute(load(folder), "weekly", ASOF)
        return R, render(R, "ceo"), render(R, "mgmt")

    def assert_not_computed(self, folder, name):
        R, ceo, mgmt = self.report(folder)
        self.assertEqual(R["s2"]["min"]["firm"], (None, None))
        self.assertEqual(R["s2"]["min"]["all"], (None, None))
        self.assertTrue(any(name in m for m in R["s2"]["out_missing"]), R["s2"]["out_missing"])
        for b in R["s2"]["buckets"]:
            self.assertIsNone(b["bal_firm"])
            self.assertIsNone(b["bal_all"])
        for html in (ceo, mgmt):
            v, s = kpi(html, "최저 계산 잔액 (확정 일정만)")
            self.assertIn("판단 불가", text(v))
            self.assertIn(name, text(s))
            v, s = kpi(html, "향후 4주 지급예정")
            self.assertIn(name, text(s))
            self.assertNotIn("시작 잔액을 몰라", html)
        # 시작 잔액(사용 가능액)은 그대로 알린다: 모르는 것은 지급 쪽이다
        self.assertEqual(R["s1"]["available"], compute(load(SAMPLE), "weekly", ASOF)["s1"]["available"])
        self.assertTrue(any(r["area"] == "자료" and name in r["fact"] for r in R["risks"]), R["risks"])

    def test_missing_schedule_file(self):
        folder = sample_copy(self)
        os.remove(os.path.join(folder, "자금일정.csv"))
        self.assert_not_computed(folder, "자금일정.csv")

    def test_missing_exec_file(self):
        folder = sample_copy(self)
        os.remove(os.path.join(folder, "프로젝트집행.csv"))
        self.assert_not_computed(folder, "프로젝트집행.csv")

    def test_amount_column_missing(self):
        folder = sample_copy(self)
        rewrite(folder, "프로젝트집행.csv", drop_column("공급가액"))
        self.assert_not_computed(folder, "프로젝트집행.csv")

    def test_unreadable_encoding(self):
        folder = sample_copy(self)
        path = os.path.join(folder, "자금일정.csv")
        with open(path, "wb") as f:
            f.write(b"\xff\xfe\x00\xd8garbage\x81\x82\x83")
        self.assert_not_computed(folder, "자금일정.csv")

    def test_optional_column_missing_still_computes(self):
        folder = sample_copy(self)
        rewrite(folder, "자금일정.csv", drop_column("비고"))
        R, ceo, _ = self.report(folder)
        base = compute(load(SAMPLE), "weekly", ASOF)
        self.assertEqual(R["s2"]["out_missing"], [])
        self.assertEqual(R["s2"]["min"], base["s2"]["min"])

    def test_sample_unchanged(self):
        R = compute(load(SAMPLE), "weekly", ASOF)
        self.assertEqual(R["s2"]["out_missing"], [])
        self.assertIsNotNone(R["s2"]["min"]["firm"][0])

    def test_report_cli_says_why(self):
        folder = sample_copy(self)
        os.remove(os.path.join(folder, "자금일정.csv"))
        rc, out = run_report(self, ["주간", "--기준일", "2026-11-02", "--입력", folder, "--pdf", "안함"])
        self.assertEqual(rc, 0)
        self.assertIn("지급 자료 없음: 자금일정.csv (파일 없음)", out)

    def test_approval_screen_does_not_compute_low(self):
        folder = sample_copy(self)
        os.remove(os.path.join(folder, "자금일정.csv"))
        tmp = new_tmp(self)
        snap = write_fake_snapshot(os.path.join(tmp, "수집"))
        path, A = load_approval_cli().make_screen(folder, os.path.join(tmp, "출력"), snap, ASOF, NOW, False)
        with open(path, encoding="utf-8") as f:
            page = f.read()
        self.assertIsNone(A["data"]["start"])
        self.assertIsNotNone(A["start"])  # 시작 잔액 줄은 그대로
        self.assertEqual(T(page, "h-low"), "미확인")
        self.assertIn("자금일정.csv", T(page, "h-short"))
        self.assertIn("자금일정.csv", A["data"]["no_calc"])
        self.assertIn("542.4", T(page, "start-line"))


if __name__ == "__main__":
    unittest.main()


class TestTitleRowAboveHeader(unittest.TestCase):
    """엑셀에서 표 위에 제목 줄('2026년 11월 자금일정')을 두고 저장한 CSV도 머리글을 찾아 읽는다.

    전에는 제목 줄을 머리글로 읽어 모든 줄을 버렸다 (지급예정 0원).
    """

    def add_title(self, folder, name, lines=1):
        def mutate(rows):
            width = len(rows[0])
            for i in range(lines):
                rows.insert(0, ["2026년 11월 자료 %d" % i] + [""] * (width - 1))
        rewrite(folder, name, mutate)

    def test_schedule_with_title_row_reads_like_sample(self):
        folder = sample_copy(self)
        self.add_title(folder, "자금일정.csv")
        self.add_title(folder, "프로젝트집행.csv", lines=2)
        R = compute(load(folder), "weekly", ASOF)
        base = compute(load(SAMPLE), "weekly", ASOF)
        self.assertEqual(R["s2"]["out_missing"], [])
        self.assertEqual(R["s2"]["min"], base["s2"]["min"])
        self.assertEqual(R["s2"]["out4_firm"], base["s2"]["out4_firm"])
        notes = [(f, line, m) for f, line, m in R["s7"]["issues"] if f == "프로젝트집행.csv"]
        self.assertTrue(any("제목 줄" in m and line == 3 for f, line, m in notes), notes)

    def test_issue_line_numbers_still_file_lines(self):
        from ceo_report.util import Issues, read_csv
        tmp = new_tmp(self)
        path = os.path.join(tmp, "x.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            f.write("제목,\r\n\r\na,b\r\n1,x\r\n2,y\r\n")
        rows, ok = read_csv(path, ["a", "b"], Issues())
        self.assertTrue(ok)
        self.assertEqual([(r["a"], r["_line"]) for r in rows], [("1", 4), ("2", 5)])

    def test_no_header_anywhere_keeps_first_row(self):
        from ceo_report.util import Issues, read_csv
        tmp = new_tmp(self)
        path = os.path.join(tmp, "x.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            f.write("p,q\r\n1,2\r\n")
        iss = Issues()
        info = {}
        rows, ok = read_csv(path, ["a", "b"], iss, info)
        self.assertEqual(info["missing"], ["a", "b"])
        self.assertTrue(any("필수 열 없음" in m for _, _, m in iss.items))


class _FixedNow(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 2, 9, 30, 5)


class TestApprovalSameMinute(unittest.TestCase):
    """같은 분에 두 번 만들면 앞 화면을 덮어쓰지 않는다 (기준일을 바꿔 비교하는 경우 앞 화면이 사라졌다)."""

    def test_second_run_gets_its_own_file(self):
        from unittest import mock
        cli = load_approval_cli()
        tmp = new_tmp(self)
        snap = write_fake_snapshot(os.path.join(tmp, "수집"))
        out = os.path.join(tmp, "출력")
        fake = type("dtmod", (), {"datetime": _FixedNow, "date": dt.date, "time": dt.time, "timedelta": dt.timedelta})
        with mock.patch.object(cli, "dt", fake):
            p1, _ = cli.make_screen(SAMPLE, out, snap, ASOF, NOW, False)
            p2, _ = cli.make_screen(SAMPLE, out, snap, dt.date(2026, 12, 31), dt.datetime(2026, 12, 31), False)
        self.assertNotEqual(p1, p2)
        self.assertEqual(os.path.basename(p1), "승인검토_20261102_0930.html")
        self.assertEqual(os.path.basename(p2), "승인검토_20261102_0930_2.html")
        with open(p1, encoding="utf-8") as f:
            self.assertIn("기준일 2026-11-02", f.read())
        with open(p2, encoding="utf-8") as f:
            self.assertIn("기준일 2026-12-31", f.read())
