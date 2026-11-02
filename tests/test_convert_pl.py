"""손익.csv 팀·프로젝트 줄과 프로젝트 연결 (Phase 2, 계획 02-03).

모든 장부·스냅숏은 시험 때 임시 폴더에 가상 자료로 만든다. 실제 입력/·수집/ 폴더와 실제 WEHAGO 파일은 열지 않는다.
다른 시험 파일에서는 함수와 상수만 가져온다 (TestCase 클래스를 가져오면 시험이 두 번 돈다).
"""
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

from test_approval import write_fake_snapshot  # noqa: E402
from test_convert import (ASOF, FAKE_PL_JOURNAL, NOW, convert_input, read_result_lines,  # noqa: E402
                          write_convert_books)
from test_convert import setUpModule  # noqa: E402,F401  (샘플을 임시 폴더에 새로 쓴다)
from test_linking import write_links_csv  # noqa: E402


def mod(name):
    return importlib.import_module("ceo_report." + name)


class Ran(object):
    """한 번의 변환: 폴더들과 convert.run 결과."""

    def __init__(self, tmp, input_dir, collect, wehago_dir, res):
        self.tmp, self.input_dir, self.collect, self.wehago_dir, self.res = tmp, input_dir, collect, wehago_dir, res
        self.code = res.code
        self.stdout = "\n".join(res.lines)

    def csv_rows(self, name="손익.csv"):
        with open(os.path.join(self.input_dir, name), encoding="utf-8-sig", newline="") as f:
            return list(csv.reader(f))

    def wehago_rows(self):
        return [tuple(r) for r in self.csv_rows()[1:] if r[0] == "WEHAGO"]

    def result_lines(self):
        return read_result_lines(self.input_dir)


def convert_with_snapshot(test, links_rows=None, snapshot=True, journal=FAKE_PL_JOURNAL, setup=None):
    """가상 장부 + (가상 스냅숏) + 샘플 입력으로 convert.run 을 한 번 돌린다 (기준일 2026-11-02).

    links_rows 를 주면 입력/프로젝트연결.csv 를 먼저 쓴다. setup(input_dir, collect, wehago_dir) 은 변환 직전에 불린다.
    """
    tmp, input_dir, collect, wehago_dir = convert_input(test)
    write_convert_books(wehago_dir, journal=journal)
    if snapshot:
        write_fake_snapshot(collect)
    if links_rows is not None:
        write_links_csv(input_dir, links_rows)
    if setup:
        setup(input_dir, collect, wehago_dir)
    res = mod("convert").run(input_dir, collect, wehago_dir, ASOF, NOW)
    return Ran(tmp, input_dir, collect, wehago_dir, res)


# ───────────── Task 1 (tracer): 스냅숏 → 연결 → 프로젝트 손익 줄 → 손익.csv → 보고서 s4 ─────────────
class TestConvertPlTracer(unittest.TestCase):
    def test_project_row_of_a_linked_revenue_and_cost_reaches_the_csv(self):
        r = convert_with_snapshot(self)
        self.assertEqual(r.code, 0, r.stdout)
        rows = r.csv_rows()
        want = "WEHAGO,2026-10,프로젝트,26203 가상 전시부스,75000000,45000000,,Y".split(",")
        self.assertIn(want, rows)

    def test_report_s4_has_the_project_row(self):
        r = convert_with_snapshot(self)
        d = mod("data").load(r.input_dir)
        self.assertEqual([it for it in d.issues.items if it[0] == "손익.csv"], [])
        R = mod("calc").compute(d, "monthly", dt.date(2026, 10, 31))
        table = R["s4"]["sources"]["WEHAGO"]["table"]
        row = [t for t in table if t["unit"] == "프로젝트" and t["target"] == "26203 가상 전시부스"]
        self.assertEqual(len(row), 1)
        self.assertEqual((row[0]["cur"]["revenue"], row[0]["cur"]["direct"]), (75000000, 45000000))
        self.assertIn("인트라넷완료보고", R["s4"]["sources"])

    def test_result_file_names_the_snapshot(self):
        r = convert_with_snapshot(self)
        self.assertIn("인트라넷 스냅숏: 인트라넷_20261101_180000 (수집 2026-11-01 18:00:00) · 지급요청 9건 · 프로젝트 4건",
                      r.result_lines())

    def test_unlinked_amount_is_not_dropped(self):
        r = convert_with_snapshot(self)
        rows = r.csv_rows()
        self.assertIn("WEHAGO,2026-10,프로젝트,프로젝트 미연결,19000000,1100000,,Y".split(","), rows)

    def test_common_cost_is_never_given_to_a_project(self):
        r = convert_with_snapshot(self)
        for row in r.wehago_rows():
            if row[2] == "프로젝트":
                self.assertEqual(row[6], "", row)


if __name__ == "__main__":
    unittest.main()
