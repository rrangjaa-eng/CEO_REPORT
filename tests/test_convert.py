"""변환(원천자료 → 입력 CSV) 시험 (Phase 2, 계획 02-01).

모든 장부는 시험 때 임시 폴더에 가상 자료로 만든다. 실제 입력/·수집/ 폴더와 실제 WEHAGO 파일은 열지 않는다
(명령 줄은 항상 --입력 --수집폴더 --위하고폴더 를 임시 폴더로 넘긴다).
"""
import contextlib
import csv
import datetime as dt
import importlib
import importlib.util
import io
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

# 함수와 상수만 가져온다 (TestCase 클래스를 가져오면 시험이 두 번 돈다).
from sample_input import SAMPLE, refresh as refresh_sample  # noqa: E402
from test_wehago import FAKE_JOURNAL, JOURNAL_HEADER, _jl, serial, write_fake_books, write_xlsx  # noqa: E402

ASOF = dt.date(2026, 11, 2)
NOW = dt.datetime(2026, 11, 2, 0, 0)

_SAME = "[26201] 가상 컨퍼런스 선금"
PL_EXTRA = [
    _jl(dt.date(2026, 9, 15), 30, "10800", "수입수수료미수금", 110000000, None, "가상고객A", _SAME),
    _jl(dt.date(2026, 9, 15), 30, "41200", "수입수수료", None, 100000000, "가상고객A", _SAME),
    _jl(dt.date(2026, 9, 15), 30, "25500", "부가세예수금", None, 10000000, "가상고객A", _SAME),
    _jl(dt.date(2026, 10, 27), 31, "10800", "수입수수료미수금", 82500000, None, "가상고객D", "가상 전시부스 잔금"),
    _jl(dt.date(2026, 10, 27), 31, "41200", "수입수수료", None, 75000000, "가상고객D", "가상 전시부스 잔금"),
    _jl(dt.date(2026, 10, 27), 31, "25500", "부가세예수금", None, 7500000, "가상고객D", "가상 전시부스 잔금"),
    _jl(dt.date(2026, 10, 28), 32, "10800", "수입수수료미수금", 22000000, None, "가상고객X", "기타 용역"),
    _jl(dt.date(2026, 10, 28), 32, "41200", "수입수수료", None, 20000000, "가상고객X", "기타 용역"),
    _jl(dt.date(2026, 10, 28), 32, "25500", "부가세예수금", None, 2000000, "가상고객X", "기타 용역"),
    _jl(dt.date(2026, 10, 5), 33, "10300", "보통예금", 110000000, None, "가상고객A", "선금 입금"),
    _jl(dt.date(2026, 10, 5), 33, "10800", "수입수수료미수금", None, 110000000, "가상고객A", "선금 입금"),
    _jl(dt.date(2026, 9, 30), 34, "81100", "복리후생비(판)", 2000000, None, "가상식당", "9월 식대"),
    _jl(dt.date(2026, 9, 30), 34, "10300", "보통예금", None, 2000000, "가상식당", "9월 식대"),
    _jl(dt.date(2026, 10, 31), 35, "81100", "복리후생비(판)", 1500000, None, "가상식당", "10월 식대"),
    _jl(dt.date(2026, 10, 31), 35, "10300", "보통예금", None, 1500000, "가상식당", "10월 식대"),
    _jl(dt.date(2026, 10, 31), 36, "93100", "이자비용", 400000, None, "가상은행", "이자"),
    _jl(dt.date(2026, 10, 31), 36, "10300", "보통예금", None, 400000, "가상은행", "이자"),
    _jl(dt.date(2026, 9, 20), 37, "61101", "행사외주비(도)", 10000000, None, "가상인쇄", "[26201] 9월 인쇄"),
    _jl(dt.date(2026, 9, 20), 37, "10300", "보통예금", None, 10000000, "가상인쇄", "[26201] 9월 인쇄"),
    _jl(dt.date(2026, 10, 29), 38, "41200", "수입수수료", 1000000, None, "가상고객X", "매출 정정"),
    _jl(dt.date(2026, 10, 29), 38, "25500", "부가세예수금", 100000, None, "가상고객X", "매출 정정"),
    _jl(dt.date(2026, 10, 29), 38, "10800", "수입수수료미수금", None, 1100000, "가상고객X", "매출 정정"),
]
FAKE_PL_JOURNAL = FAKE_JOURNAL + PL_EXTRA

PL_COLUMNS = ["출처", "연월", "단위", "대상", "매출", "직접비", "공통비", "잠정"]


def jl_sort(date, no, sort, code, account, debit, credit, vendor, memo):
    """구분(sort)을 고를 수 있는 분개장 한 줄 (_jl 은 구분이 늘 '대체')."""
    return [serial(date), no, sort, code, account, debit, credit, vendor, "V000", memo]


def write_convert_books(folder, stamp="20261031", journal=FAKE_PL_JOURNAL, **kw):
    return write_fake_books(folder, stamp=stamp, journal=journal, **kw)


def setUpModule():
    refresh_sample()  # 샘플은 임시 폴더에 쓴다 (실제 입력 폴더를 건드리지 않음)


def convert_input(test):
    """임시 폴더 <tmp>/입력 (샘플 복사), <tmp>/수집, <tmp>/수집/위하고 를 만들어 (tmp, 입력, 수집, 위하고)를 돌려준다."""
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    input_dir = os.path.join(tmp, "입력")
    shutil.copytree(SAMPLE, input_dir)
    collect = os.path.join(tmp, "수집")
    wehago_dir = os.path.join(collect, "위하고")
    os.makedirs(wehago_dir)
    return tmp, input_dir, collect, wehago_dir


_CLI = None


def load_cli():
    """변환.py 는 이름이 한글이라 import 할 수 없다. 경로로 읽어 한 번만 만든다."""
    global _CLI
    if _CLI is None:
        spec = importlib.util.spec_from_file_location("convert_cli", os.path.join(ROOT, "변환.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _CLI = m
    return _CLI


def cli_argv(input_dir, collect, wehago_dir, asof="2026-11-02"):
    return ["--기준일", asof, "--입력", input_dir, "--수집폴더", collect, "--위하고폴더", wehago_dir]


def run_convert(argv):
    cli = load_cli()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(argv)
    return rc, buf.getvalue()


def read_result_lines(input_dir):
    with open(os.path.join(input_dir, "변환결과.txt"), encoding="utf-8-sig") as f:
        return f.read().splitlines()


def read_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def mod(name):
    return importlib.import_module("ceo_report." + name)


def converted(test, journal=FAKE_PL_JOURNAL, stamp="20261031", asof="2026-11-02", setup=None):
    """가상 장부 + 샘플 입력으로 변환을 한 번 돌린다. (tmp, 입력, 수집, 위하고, rc, stdout)."""
    tmp, input_dir, collect, wehago_dir = convert_input(test)
    write_convert_books(wehago_dir, stamp=stamp, journal=journal)
    if setup:
        setup(input_dir, collect, wehago_dir)
    rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir, asof))
    return tmp, input_dir, collect, wehago_dir, rc, out


# ───────────── Task 1 (tracer): 변환.py → 손익.csv 회사 줄 → 변환결과.txt 대조 → 보고서가 읽는다 ─────────────
class TestConvertTracer(unittest.TestCase):
    def test_cli_writes_the_two_company_rows_then_carries_the_intranet_rows(self):
        with open(os.path.join(SAMPLE, "손익.csv"), encoding="utf-8-sig", newline="") as f:
            old = list(csv.reader(f))
        carried = [r for r in old[1:] if r[0] == "인트라넷완료보고"]
        self.assertEqual(len(carried), 3)
        tmp, input_dir, collect, wehago_dir, rc, out = converted(self)
        self.assertEqual(rc, 0, out)
        rows = read_rows(os.path.join(input_dir, "손익.csv"))
        self.assertEqual(rows[0], PL_COLUMNS)
        self.assertEqual(rows[1], "WEHAGO,2026-09,회사,회사 전체,100000000,10000000,2000000,Y".split(","))
        self.assertEqual(rows[2], "WEHAGO,2026-10,회사,회사 전체,94000000,249500000,4500000,Y".split(","))
        self.assertEqual(rows[3:6], carried)
        self.assertEqual(len(rows), 6)
        self.assertEqual(sum(1 for r in rows[1:] if r[0] == "WEHAGO"), 2)

    def test_result_file_has_source_vs_csv_checks(self):
        tmp, input_dir, collect, wehago_dir, rc, out = converted(self)
        lines = read_result_lines(input_dir)
        for want in ("  대조 매출 (41200 대변−차변): 원본 194,000,000 · CSV 194,000,000 → 일치",
                     "  대조 직접비 (6xxxx (도) 차변−대변): 원본 259,500,000 · CSV 259,500,000 → 일치",
                     "  대조 공통비 (8xxxx 차변−대변): 원본 6,500,000 · CSV 6,500,000 → 일치",
                     "대조 불일치 0건"):
            self.assertIn(want, lines)
        text = "\n".join(lines)
        self.assertIn("손익.csv에 넣지 않은 손익 계정: 45100 (도)외주비 1줄 500,000 · 93100 이자비용 1줄 400,000", text)
        self.assertIn("공통비 중 (판) 표시 없음: 81900 임차료 1줄 3,000,000 (공통비에 넣음)", text)
        self.assertTrue(lines[0].startswith("변환 시각 "), lines[0])
        self.assertIn("[손익.csv] 만듦 2줄", lines)
        self.assertTrue(any(ln.startswith("WEHAGO 장부: ") and "장부 기준일 2026-10-31" in ln for ln in lines))

    def test_stdout_is_a_short_summary(self):
        tmp, input_dir, collect, wehago_dir, rc, out = converted(self)
        self.assertIn("손익.csv 만듦 2줄", out)
        self.assertIn("대조 불일치 0건", out)
        self.assertIn("변환결과.txt", out)
        self.assertIn("2026-10-31", out)

    def test_report_reads_the_converted_file(self):
        tmp, input_dir, collect, wehago_dir, rc, out = converted(self)
        d = mod("data").load(input_dir)
        self.assertEqual([it for it in d.issues.items if it[0] == "손익.csv"], [])
        R = mod("calc").compute(d, "monthly", dt.date(2026, 10, 31))
        table = R["s4"]["sources"]["WEHAGO"]["table"]
        company = [t for t in table if t["unit"] == "회사"]
        self.assertEqual(len(company), 1)
        cur, ytd = company[0]["cur"], company[0]["ytd"]
        self.assertEqual((cur["revenue"], cur["direct"], cur["common"]), (94000000, 249500000, 4500000))
        self.assertEqual((ytd["revenue"], ytd["direct"], ytd["common"]), (194000000, 259500000, 6500000))
        self.assertTrue(cur["provisional"])

    def test_bad_asof_is_exit_2(self):
        tmp, input_dir, collect, wehago_dir = convert_input(self)
        rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir, asof="2026-13-45"))
        self.assertEqual(rc, 2)
        self.assertIn("기준일 형식 오류", out)

    def test_wehago_age_can_be_ignored_but_approval_behaviour_is_unchanged(self):
        w = mod("wehago")
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        folder = os.path.join(tmp, "위하고")
        write_convert_books(folder, stamp="20260901")
        ignored = w.load_books(folder, ASOF, None)
        self.assertEqual(ignored.state, "ok", ignored.reason)
        self.assertEqual(w.load_books(folder, ASOF, 7).state, "경과")
        self.assertEqual({r["sort"] for r in ignored.journal}, {"대체"})

    def test_unknown_book_date_is_still_stale_without_an_age_limit(self):
        w = mod("wehago")
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        folder = os.path.join(tmp, "위하고")
        write_fake_books(folder, stamp="x", journal=[], ledger=[], einvoice=[])
        books = w.load_books(folder, ASOF, None)
        self.assertEqual(books.state, "경과")
        self.assertIn("장부 기준일을 알 수 없음", books.reason)

    def test_journal_sort_is_read_from_the_구분_column(self):
        w = mod("wehago")
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        folder = os.path.join(tmp, "위하고")
        line = jl_sort(dt.date(2026, 10, 31), 90, "결차", "37500", "이월이익잉여금", 0, None, "", "연말 결산")
        write_convert_books(folder, journal=FAKE_PL_JOURNAL + [line])
        books = w.load_books(folder, ASOF, None)
        self.assertEqual(books.journal[-1]["sort"], "결차")


if __name__ == "__main__":
    unittest.main()
