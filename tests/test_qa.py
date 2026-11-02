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
