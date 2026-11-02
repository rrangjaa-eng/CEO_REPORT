"""변환(원천자료 → 입력 CSV) 시험 (Phase 2, 계획 02-01).

모든 장부는 시험 때 임시 폴더에 가상 자료로 만든다. 실제 입력/·수집/ 폴더와 실제 WEHAGO 파일은 열지 않는다
(명령 줄은 항상 --입력 --수집폴더 --위하고폴더 를 임시 폴더로 넘긴다).
"""
import contextlib
import csv
import datetime as dt
import hashlib
import importlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

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


KEPT_SAMPLE_MONTHS = [   # 02-REVIEW CR-04: 샘플 이전 손익.csv 중 새 분개장(2026-09~2026-10) 밖의 달은 이전 변환 그대로 남는다
    "WEHAGO,2026-01,회사,회사 전체,0,0,30000000,", "WEHAGO,2026-02,회사,회사 전체,80000000,54400000,30000000,",
    "WEHAGO,2026-03,회사,회사 전체,120000000,81600000,30000000,", "WEHAGO,2026-04,회사,회사 전체,150000000,102000000,30000000,",
    "WEHAGO,2026-05,회사,회사 전체,90000000,61200000,30000000,", "WEHAGO,2026-06,회사,회사 전체,200000000,136000000,30000000,",
    "WEHAGO,2026-07,회사,회사 전체,160000000,108800000,30000000,", "WEHAGO,2026-08,회사,회사 전체,140000000,95200000,30000000,"]
KEPT_SAMPLE_LATER = ["WEHAGO,2026-11,회사,회사 전체,30000000,20400000,30000000,Y"]
JOURNAL_MONTHS = ("2026-09", "2026-10")   # FAKE_PL_JOURNAL 의 달


def company_rows(rows, months=JOURNAL_MONTHS):
    """읽은 손익.csv 줄 중 WEHAGO 회사 줄만 (02-03부터 같은 파일에 팀·프로젝트 줄도 있다).

    months: 이 달들의 줄만 (기본: 새 분개장 FAKE_PL_JOURNAL 의 달). 02-REVIEW CR-04 부터 분개장 밖 달의 이전 줄은 남으므로
    새로 만든 줄만 보려면 달로 거른다. None 이면 모든 회사 줄.
    """
    return [r for r in rows[1:] if r[0] == "WEHAGO" and r[2] == "회사" and (months is None or r[1] in months)]


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
        # 02-03: 스냅숏이 없어도 [코드]로 이은 프로젝트 줄이 회사 줄 뒤에 붙는다 (회사 줄은 그대로)
        self.assertEqual(company_rows(rows), ["WEHAGO,2026-09,회사,회사 전체,100000000,10000000,2000000,Y".split(","),
                                              "WEHAGO,2026-10,회사,회사 전체,94000000,249500000,4500000,Y".split(",")])
        # 02-REVIEW CR-04: 새 분개장 밖의 달(2026-01~08 앞, 2026-11 뒤)은 이전 변환 줄(회사·팀)을 그대로 남긴다 (예전: 모두 지움)
        self.assertEqual(company_rows(rows, None), [r.split(",") for r in KEPT_SAMPLE_MONTHS] + company_rows(rows)
                         + [r.split(",") for r in KEPT_SAMPLE_LATER])
        self.assertEqual(rows[1], KEPT_SAMPLE_MONTHS[0].split(","))
        self.assertEqual(rows[-3:], carried)
        self.assertEqual(len(rows), 40)  # 머리글 + 이전 유지 24줄 (8달 × 회사·팀 2) + 새 9줄 + 이전 유지 3줄 (2026-11) + 옮긴 3줄
        self.assertEqual(sum(1 for r in rows[1:] if r[0] == "WEHAGO"), 36)

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
        self.assertIn("[손익.csv] 만듦 39줄", lines)   # 02-REVIEW CR-04: 이전 변환 유지 27줄 포함 (예전 12줄)
        self.assertIn("  알림 이전 변환 유지 2026-01~2026-08, 2026-11 (WEHAGO 줄 27건: 회사 9 · 팀 18) — 새 분개장(2026-09~2026-10)에 없는 달",
                      lines)
        self.assertIn("  알림 분개장 기간 2026-09-15~2026-10-31", lines)
        self.assertTrue(any(ln.startswith("WEHAGO 장부: ") and "장부 기준일 2026-10-31" in ln for ln in lines))

    def test_stdout_is_a_short_summary(self):
        tmp, input_dir, collect, wehago_dir, rc, out = converted(self)
        self.assertIn("손익.csv 만듦 39줄", out)   # 02-REVIEW CR-04: 이전 변환 유지 27줄 포함
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
        # 02-REVIEW CR-04: 누계에 이전 변환 유지 달(샘플 2026-01~08)이 남는다 (예전: 새 분개장 두 달 194,000,000 · 259,500,000 · 6,500,000)
        self.assertEqual((ytd["revenue"], ytd["direct"], ytd["common"]), (1134000000, 898700000, 246500000))
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


# ───────────── Task 2: 안전한 덮어쓰기와 멈춤 상태 (D-43, D-45, D-35a) ─────────────
RRN = re.compile(r"\d{6}\s*[-.]?\s*\d{7}")
STAMP = "20261102_000000"


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def tree(folder):
    """폴더 안 모든 파일의 {상대 경로: sha256}."""
    out = {}
    for base, _, files in os.walk(folder):
        for n in files:
            full = os.path.join(base, n)
            out[os.path.relpath(full, folder).replace(os.sep, "/")] = sha(full)
    return out


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def backup_dirs(input_dir):
    base = os.path.join(input_dir, "이전")
    return sorted(os.listdir(base)) if os.path.isdir(base) else []


def convert_run(input_dir, collect, wehago_dir, stamp=None, asof=ASOF, now=NOW):
    return mod("convert").run(input_dir, collect, wehago_dir, asof, now, stamp)


class TestConvertSafety(unittest.TestCase):
    def prepared(self, **kw):
        tmp, input_dir, collect, wehago_dir = convert_input(self)
        write_convert_books(wehago_dir, **kw)
        return tmp, input_dir, collect, wehago_dir

    def test_old_file_is_copied_to_a_time_folder_before_it_is_replaced(self):
        tmp, input_dir, collect, wehago_dir = self.prepared()
        old = read_bytes(os.path.join(input_dir, "손익.csv"))
        res = convert_run(input_dir, collect, wehago_dir, stamp=STAMP)
        self.assertEqual(res.code, 0, res.lines)
        self.assertEqual(backup_dirs(input_dir), [STAMP])
        self.assertEqual(read_bytes(os.path.join(input_dir, "이전", STAMP, "손익.csv")), old)
        self.assertNotEqual(read_bytes(os.path.join(input_dir, "손익.csv")), old)
        self.assertFalse(os.path.exists(os.path.join(input_dir, "이전", STAMP, "변환결과.txt")))  # 처음엔 없었다
        self.assertIn("이전 파일: 입력/이전/%s/ (손익.csv, 계산서.csv)" % STAMP, read_result_lines(input_dir))

    def test_a_second_run_in_the_same_second_gets_a_new_folder(self):
        tmp, input_dir, collect, wehago_dir = self.prepared()
        convert_run(input_dir, collect, wehago_dir, stamp=STAMP)
        first = read_bytes(os.path.join(input_dir, "손익.csv"))
        convert_run(input_dir, collect, wehago_dir, stamp=STAMP)
        self.assertEqual(backup_dirs(input_dir), [STAMP, STAMP + "_2"])
        self.assertEqual(read_bytes(os.path.join(input_dir, "이전", STAMP + "_2", "손익.csv")), first)
        self.assertTrue(os.path.exists(os.path.join(input_dir, "이전", STAMP + "_2", "변환결과.txt")))

    def test_cli_backup_folder_name_is_a_time_stamp(self):
        tmp, input_dir, collect, wehago_dir = self.prepared()
        rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        self.assertEqual(rc, 0, out)
        names = backup_dirs(input_dir)
        self.assertEqual(len(names), 1)
        self.assertRegex(names[0], r"^\d{8}_\d{6}(_\d+)?$")

    def test_no_backup_folder_when_nothing_existed_before(self):
        tmp, input_dir, collect, wehago_dir = self.prepared()
        for name in ("손익.csv", "계산서.csv"):   # 02-07부터 계산서.csv 도 만든다
            os.remove(os.path.join(input_dir, name))
        res = convert_run(input_dir, collect, wehago_dir, stamp=STAMP)
        self.assertEqual(res.code, 0, res.lines)
        self.assertEqual(backup_dirs(input_dir), [])
        self.assertIn("이전 파일: 없음", read_result_lines(input_dir))

    def test_manual_files_are_never_touched(self):
        tmp, input_dir, collect, wehago_dir = self.prepared()
        manual = ("계좌잔액.csv", "설정.csv", "지급계획.csv", "변경내역.csv", "자료기준일.csv")
        before = dict((n, sha(os.path.join(input_dir, n))) for n in manual)
        full_before = tree(input_dir)
        self.assertFalse(os.path.exists(os.path.join(input_dir, "프로젝트연결.csv")))
        res = convert_run(input_dir, collect, wehago_dir, stamp=STAMP)
        self.assertEqual(res.code, 0)
        self.assertEqual(before, dict((n, sha(os.path.join(input_dir, n))) for n in manual))
        self.assertFalse(os.path.exists(os.path.join(input_dir, "프로젝트연결.csv")))
        full_after = tree(input_dir)
        convert = mod("convert")
        for path, digest in full_after.items():
            if full_before.get(path) != digest:
                self.assertTrue(path in convert.GENERATED or path.startswith("이전/"), path)
        for path in full_before:
            self.assertIn(path, full_after, "지워진 파일: " + path)

    def test_only_generated_names_may_be_written(self):
        tmp, input_dir, collect, wehago_dir = self.prepared()
        before = tree(input_dir)
        convert = mod("convert")
        for name in convert.MANUAL:
            with self.assertRaises(ValueError):
                convert.write_files(input_dir, [(name, b"x")], STAMP)
        with self.assertRaises(ValueError):
            convert.write_files(input_dir, [("../밖.csv", b"x")], STAMP)
        self.assertEqual(tree(input_dir), before)

    def books_failure(self, tmp, input_dir, collect, wehago_dir, reason):
        before = read_bytes(os.path.join(input_dir, "손익.csv"))
        tree_before = tree(input_dir)
        rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        self.assertEqual(rc, 3, out)
        self.assertEqual(read_bytes(os.path.join(input_dir, "손익.csv")), before)
        lines = read_result_lines(input_dir)
        text = "\n".join(lines)
        self.assertIn(reason, text)
        self.assertIn("[손익.csv] 만들지 않음 — WEHAGO 장부를 쓸 수 없음", lines)
        self.assertIn("변환하지 않음", out)
        self.assertIn(reason, out)
        for path, digest in tree(input_dir).items():
            if tree_before.get(path) != digest:
                self.assertTrue(path == "변환결과.txt" or path.startswith("이전/"), path)

    def test_missing_books_folder_stops_every_wehago_file(self):
        tmp, input_dir, collect, wehago_dir = self.prepared()
        shutil.rmtree(wehago_dir)
        self.books_failure(tmp, input_dir, collect, wehago_dir,
                           "자료 없음: 분개장, 매입매출장, 전자세금계산서(매입) (폴더를 찾을 수 없음)")

    def test_renamed_required_column_stops(self):
        tmp, input_dir, collect, wehago_dir = self.prepared()
        header = ["메모" if h == "적요" else h for h in JOURNAL_HEADER]
        write_xlsx(os.path.join(wehago_dir, "분개장_20261031.xlsx"), [header] + [list(r) for r in FAKE_PL_JOURNAL])
        self.books_failure(tmp, input_dir, collect, wehago_dir, "머리글이 예상과 다름")

    def test_non_zip_journal_stops(self):
        tmp, input_dir, collect, wehago_dir = self.prepared()
        with open(os.path.join(wehago_dir, "분개장_20261031.xlsx"), "wb") as f:
            f.write(b"not a zip")
        self.books_failure(tmp, input_dir, collect, wehago_dir, "읽기 실패")

    def test_age_alone_never_stops_conversion(self):
        tmp, input_dir, collect, wehago_dir = self.prepared(stamp="20261020")
        rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        self.assertEqual(rc, 0, out)
        lines = read_result_lines(input_dir)
        self.assertTrue(any(ln.startswith("WEHAGO 장부: ") and "장부 기준일 2026-10-20 · 기준일보다 13일 이전" in ln
                            for ln in lines), lines[:3])
        self.assertIn("기준일보다 13일 이전", out)

    def test_locked_target_stops_with_exit_7_and_changes_nothing(self):
        tmp, input_dir, collect, wehago_dir = self.prepared()
        before = tree(input_dir)
        convert = mod("convert")
        real = convert._check_writable

        def locked(path):
            if os.path.basename(path) == "손익.csv":
                raise PermissionError(13, "Permission denied", path)
            return real(path)

        with mock.patch.object(convert, "_check_writable", side_effect=locked):
            rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        self.assertEqual(rc, 7, out)
        self.assertIn("입력/손익.csv을(를) 쓸 수 없음 (엑셀에서 열려 있으면 닫고 다시 실행)", out)
        self.assertEqual(tree(input_dir), before)  # 이전 폴더도, 임시 파일도, 변환결과.txt 도 생기지 않는다

    def test_failed_write_removes_temp_files_and_replaces_nothing(self):
        tmp, input_dir, collect, wehago_dir = self.prepared()
        before = tree(input_dir)
        convert = mod("convert")
        real = convert._write_temp
        calls = []

        def flaky(path, payload):
            calls.append(path)
            if len(calls) == 2:
                raise OSError(28, "No space left on device", path)
            return real(path, payload)

        with mock.patch.object(convert, "_write_temp", side_effect=flaky):
            rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        self.assertEqual(rc, 7, out)
        self.assertIn("을(를) 쓸 수 없음", out)
        self.assertEqual(len(calls), 2)
        self.assertEqual(tree(input_dir), before)

    def test_intranet_rows_are_carried_after_the_books_rows_unchanged(self):
        with open(os.path.join(SAMPLE, "손익.csv"), encoding="utf-8-sig", newline="") as f:
            old = list(csv.reader(f))
        carried = [r for r in old[1:] if r[0] == "인트라넷완료보고"]
        tmp, input_dir, collect, wehago_dir, rc, out = converted(self)
        rows = read_rows(os.path.join(input_dir, "손익.csv"))
        self.assertEqual(rows[-3:], carried)
        self.assertEqual([r[0] for r in rows[1:-3]], ["WEHAGO"] * (len(rows) - 4))
        self.assertIn("  알림 이전 손익.csv의 WEHAGO 외 출처 줄 3건 그대로 옮김", read_result_lines(input_dir))

    def test_unreadable_previous_file_is_reported_not_silently_dropped(self):
        tmp, input_dir, collect, wehago_dir = self.prepared()
        with open(os.path.join(input_dir, "손익.csv"), "w", encoding="utf-8") as f:
            f.write("가,나\n1,2\n")
        res = convert_run(input_dir, collect, wehago_dir, stamp=STAMP)
        self.assertEqual(res.code, 0)
        text = "\n".join(read_result_lines(input_dir))
        self.assertIn("이전 손익.csv를 읽지 못해 WEHAGO 외 출처 줄을 옮기지 못함 (입력/이전/%s/ 에 원본 보관)" % STAMP, text)
        self.assertTrue(os.path.exists(os.path.join(input_dir, "이전", STAMP, "손익.csv")))

    def test_resident_numbers_are_masked_everywhere(self):
        def setup(input_dir, collect, wehago_dir):
            with open(os.path.join(input_dir, "손익.csv"), "a", encoding="utf-8", newline="") as f:
                f.write("인트라넷완료보고,2026-10,프로젝트,강사 900101-1234567,\"1,000\",,,\n")

        tmp, input_dir, collect, wehago_dir, rc, out = converted(self, setup=setup)
        self.assertEqual(rc, 0, out)
        csv_text = read_bytes(os.path.join(input_dir, "손익.csv")).decode("utf-8")
        self.assertIn("강사 ******-*******", csv_text)
        self.assertIsNone(RRN.search(csv_text))
        self.assertIsNone(RRN.search(read_bytes(os.path.join(input_dir, "변환결과.txt")).decode("utf-8")))
        self.assertIsNone(RRN.search(out))

    def test_missing_input_folder_is_created_and_missing_manual_files_are_named(self):
        tmp, input_dir, collect, wehago_dir = self.prepared()
        shutil.rmtree(input_dir)
        rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        self.assertEqual(rc, 0, out)
        rows = read_rows(os.path.join(input_dir, "손익.csv"))
        self.assertEqual(len(company_rows(rows)), 2)  # 샘플의 이전 손익.csv 가 없으니 이어 붙일 줄이 없다
        self.assertEqual(len(rows), 10)  # 회사 2 + 프로젝트 7 (스냅숏이 없어 [코드]로만 잇는다)
        text = "\n".join(read_result_lines(input_dir))
        for name in mod("convert").MANUAL:
            self.assertIn(name, text)
        self.assertIn("손대지 않은 파일: 없음", text)
        self.assertEqual(backup_dirs(input_dir), [])
        self.assertEqual(sorted(os.listdir(input_dir)), ["계산서.csv", "변환결과.txt", "손익.csv"])

    def test_backup_and_log_paths_are_git_ignored(self):
        for rel in ("입력/이전/20261102_000000/손익.csv", "입력/변환결과.txt"):
            rc = subprocess.call(["git", "-C", ROOT, "check-ignore", "-q", rel])
            self.assertEqual(rc, 0, rel)


# ───────────── Task 3: 계정 설정(D-39), 잠정(Q-3), 금액 없는 줄, 실행_변환.bat ─────────────
def add_settings(input_dir, *rows):
    """설정.csv 끝에 '변환_*' 행을 붙인다 (시험용 임시 복사본에만)."""
    with open(os.path.join(input_dir, "설정.csv"), "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for r in rows:
            w.writerow(r)


def settings_only(test, *rows):
    """설정.csv 만 있는 임시 입력 폴더."""
    folder = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, folder, True)
    with open(os.path.join(folder, "설정.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["항목", "값"])
        for r in rows:
            w.writerow(r)
    return folder


class TestConvertConfig(unittest.TestCase):
    def test_sample_copy_has_every_default_and_no_notes(self):
        convert = mod("convert")
        tmp, input_dir, collect, wehago_dir = convert_input(self)
        cfg, notes = convert.read_config(input_dir)
        self.assertEqual(notes, [])
        self.assertEqual(dict(cfg), {
            "revenue_codes": ("41200",), "receivable_codes": ("10800",), "direct_prefixes": ("6",),
            "direct_mark": "(도)", "common_prefixes": ("8",), "common_mark": "(판)",
            "payable_codes": ("25300", "26200"), "cash_codes": ("10300",), "vat_codes": ("13500",),
            "closing_sorts": ("결차", "결대"), "link_days": 90, "card_words": ("카드",)})

    def test_every_item_is_read_from_the_settings(self):
        convert = mod("convert")
        folder = settings_only(
            self, ["변환_매출계정", "41200, 41300"], ["변환_매출채권계정", "10900"], ["변환_직접비코드", "6,7"],
            ["변환_직접비표시", "(원가)"], ["변환_공통비코드", "8,9"], ["변환_공통비표시", "(관리)"],
            ["변환_미지급계정", "25300"], ["변환_현금계정", "10300,10310"], ["변환_부가세대급금계정", "13500"],
            ["변환_결산구분", "결산 , 결차"], ["변환_자동연결일수", "30"], ["변환_카드거래처", "카드,체크"])
        cfg, notes = convert.read_config(folder)
        self.assertEqual(notes, [])
        self.assertTrue(cfg.from_file)
        self.assertEqual(cfg["revenue_codes"], ("41200", "41300"))
        self.assertEqual(cfg["receivable_codes"], ("10900",))
        self.assertEqual(cfg["direct_prefixes"], ("6", "7"))
        self.assertEqual(cfg["direct_mark"], "(원가)")
        self.assertEqual(cfg["common_prefixes"], ("8", "9"))
        self.assertEqual(cfg["common_mark"], "(관리)")
        self.assertEqual(cfg["payable_codes"], ("25300",))
        self.assertEqual(cfg["cash_codes"], ("10300", "10310"))
        self.assertEqual(cfg["closing_sorts"], ("결산", "결차"))
        self.assertEqual(cfg["link_days"], 30)
        self.assertEqual(cfg["card_words"], ("카드", "체크"))

    def test_bad_values_fall_back_to_the_default_with_a_note(self):
        convert = mod("convert")
        folder = settings_only(self, ["변환_매출계정", "abc"], ["변환_자동연결일수", "-3"], ["변환_현금계정", "10300,x1"],
                               ["변환_직접비표시", ""], ["변환_결산구분", "-"], ["변환_자동연결일수", "-3"],
                               ["변환_공통비코드", "8.5"], ["변환_카드거래처", "3.5"])
        cfg, notes = convert.read_config(folder)
        self.assertEqual(cfg["revenue_codes"], ("41200",))
        self.assertEqual(cfg["link_days"], 90)
        self.assertEqual(cfg["cash_codes"], ("10300",))
        self.assertEqual(cfg["direct_mark"], "(도)")
        self.assertEqual(cfg["closing_sorts"], ("결차", "결대"))
        self.assertEqual(cfg["common_prefixes"], ("8",))
        self.assertIn("설정 변환_매출계정 값 'abc' 사용할 수 없음 → 기본값 41200", notes)
        self.assertIn("설정 변환_자동연결일수 값 '-3' 사용할 수 없음 → 기본값 90", notes)
        self.assertIn("설정 변환_현금계정 값 '10300,x1' 사용할 수 없음 → 기본값 10300", notes)
        self.assertIn("설정 변환_직접비표시 비어 있음 → 기본값 (도)", notes)
        self.assertIn("설정 변환_결산구분 비어 있음 → 기본값 결차,결대", notes)
        self.assertIn("설정 변환_공통비코드 값 '8.5' 사용할 수 없음 → 기본값 8", notes)

    def test_zero_link_days_is_allowed_and_unknown_items_are_reported(self):
        convert = mod("convert")
        folder = settings_only(self, ["변환_자동연결일수", "0"], ["변환_매출계좌", "41200"], ["회사명", "가상"])
        cfg, notes = convert.read_config(folder)
        self.assertEqual(cfg["link_days"], 0)
        self.assertEqual(notes, ["설정 변환_매출계좌 알 수 없는 변환 항목 → 무시"])

    def test_missing_settings_file_uses_defaults_with_a_note(self):
        convert = mod("convert")
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        cfg, notes = convert.read_config(folder)
        self.assertEqual(dict(cfg), dict(convert.DEFAULT_CONFIG))
        self.assertEqual(notes, ["설정.csv 없음 → 변환 설정 기본값 사용"])
        self.assertFalse(os.path.exists(os.path.join(folder, "설정.csv")))

    def test_the_settings_file_is_never_written(self):
        tmp, input_dir, collect, wehago_dir = convert_input(self)
        add_settings(input_dir, ["변환_공통비코드", "8,9"], ["변환_매출계정", "abc"])
        write_convert_books(wehago_dir)
        before = sha(os.path.join(input_dir, "설정.csv"))
        rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        self.assertEqual(rc, 0, out)
        self.assertEqual(sha(os.path.join(input_dir, "설정.csv")), before)

    def test_common_codes_from_settings_change_the_csv_and_the_listing(self):
        def setup(input_dir, collect, wehago_dir):
            add_settings(input_dir, ["변환_공통비코드", "8,9"])

        tmp, input_dir, collect, wehago_dir, rc, out = converted(self, setup=setup)
        self.assertEqual(rc, 0, out)
        rows = company_rows(read_rows(os.path.join(input_dir, "손익.csv")))
        self.assertEqual(rows[1][1:], "2026-10,회사,회사 전체,94000000,249500000,4900000,Y".split(","))
        lines = read_result_lines(input_dir)
        self.assertIn("  대조 공통비 (8xxxx,9xxxx 차변−대변): 원본 6,900,000 · CSV 6,900,000 → 일치", lines)
        text = "\n".join(lines)
        self.assertIn("손익.csv에 넣지 않은 손익 계정: 45100 (도)외주비 1줄 500,000\n", text + "\n")
        self.assertIn("93100 이자비용 1줄 400,000", text)
        self.assertIn("설정: 설정.csv 변환 항목 반영", lines)

    def test_bad_revenue_code_falls_back_and_is_reported(self):
        def setup(input_dir, collect, wehago_dir):
            add_settings(input_dir, ["변환_매출계정", "abc"])

        tmp, input_dir, collect, wehago_dir, rc, out = converted(self, setup=setup)
        self.assertEqual(rc, 0, out)
        lines = read_result_lines(input_dir)
        self.assertIn("  알림 설정 변환_매출계정 값 'abc' 사용할 수 없음 → 기본값 41200", lines)
        self.assertIn("  대조 매출 (41200 대변−차변): 원본 194,000,000 · CSV 194,000,000 → 일치", lines)

    def test_revenue_code_from_settings_moves_the_revenue(self):
        def setup(input_dir, collect, wehago_dir):
            add_settings(input_dir, ["변환_매출계정", "45100"])

        tmp, input_dir, collect, wehago_dir, rc, out = converted(self, setup=setup)
        rows = company_rows(read_rows(os.path.join(input_dir, "손익.csv")))
        self.assertEqual(rows[1][4], "-500000")  # 45100 차변 500,000 → 대변−차변
        self.assertIn("  대조 매출 (45100 대변−차변): 원본 -500,000 · CSV -500,000 → 일치".replace("-", "−"),
                      read_result_lines(input_dir))


CLOSE_DEBIT = jl_sort(dt.date(2026, 10, 31), 90, "결차", "37500", "이월이익잉여금", 0, None, "", "연말 결산")


class TestConvertProvisional(unittest.TestCase):
    def pl_rows(self, journal, setup=None):
        tmp, input_dir, collect, wehago_dir, rc, out = converted(self, journal=journal, setup=setup)
        self.assertEqual(rc, 0, out)
        return company_rows(read_rows(os.path.join(input_dir, "손익.csv"))), input_dir

    def test_without_closing_lines_every_month_is_provisional(self):
        rows, _ = self.pl_rows(FAKE_PL_JOURNAL)
        self.assertEqual([r[7] for r in rows], ["Y", "Y"])

    def test_a_closing_line_in_the_year_makes_all_its_months_final(self):
        rows, input_dir = self.pl_rows(FAKE_PL_JOURNAL + [CLOSE_DEBIT])
        self.assertEqual([(r[1], r[7]) for r in rows], [("2026-09", ""), ("2026-10", "")])
        self.assertEqual([r[4:7] for r in rows], [["100000000", "10000000", "2000000"],
                                                  ["94000000", "249500000", "4500000"]])  # 결산 줄은 손익 합계를 바꾸지 않는다

    def test_a_closing_line_of_last_year_only_closes_last_year(self):
        line = jl_sort(dt.date(2025, 12, 31), 91, "결대", "37500", "이월이익잉여금", None, 0, "", "전기 결산")
        tmp, input_dir, collect, wehago_dir, rc, out = converted(self, journal=FAKE_PL_JOURNAL + [line])
        rows = company_rows(read_rows(os.path.join(input_dir, "손익.csv")), None)
        # 02-REVIEW CR-04: 분개장이 2025-12~2026-10 을 덮으므로 그 사이 샘플 줄은 바뀌고 뒤의 2026-11 만 이전 변환 그대로 남는다
        self.assertEqual([(r[1], r[4:7], r[7]) for r in rows],
                         [("2025-12", ["0", "0", "0"], ""), ("2026-09", ["100000000", "10000000", "2000000"], "Y"),
                          ("2026-10", ["94000000", "249500000", "4500000"], "Y"),
                          ("2026-11", ["30000000", "20400000", "30000000"], "Y")])

    def test_closing_words_come_from_the_settings(self):
        other = jl_sort(dt.date(2026, 10, 31), 92, "결산", "37500", "이월이익잉여금", 0, None, "", "연말 결산")

        def setup(input_dir, collect, wehago_dir):
            add_settings(input_dir, ["변환_결산구분", "결산"])

        rows, _ = self.pl_rows(FAKE_PL_JOURNAL + [other], setup=setup)
        self.assertEqual([r[7] for r in rows], ["", ""])
        rows, _ = self.pl_rows(FAKE_PL_JOURNAL + [CLOSE_DEBIT], setup=setup)  # 기본 낱말은 더 이상 결산이 아니다
        self.assertEqual([r[7] for r in rows], ["Y", "Y"])

    def test_a_line_without_any_amount_blanks_that_month_and_the_check_cannot_judge(self):
        blank = jl_sort(dt.date(2026, 10, 5), 93, "대체", "41200", "수입수수료", None, None, "가상고객X", "금액 없음")
        tmp, input_dir, collect, wehago_dir, rc, out = converted(self, journal=FAKE_PL_JOURNAL + [blank])
        self.assertEqual(rc, 0, out)
        rows = company_rows(read_rows(os.path.join(input_dir, "손익.csv")))
        self.assertEqual(rows[0][4:7], ["100000000", "10000000", "2000000"])
        self.assertEqual(rows[1][4:7], ["", "249500000", "4500000"])  # 매출 칸은 0이 아니라 빈칸
        lines = read_result_lines(input_dir)
        self.assertIn("  알림 금액 없는 손익 줄 1건 (2026-10 매출) → 그 달 칸 비움", lines)
        self.assertIn("  대조 매출 (41200 대변−차변): 원본 194,000,000 · CSV 미확인 → 판단 불가", lines)
        self.assertIn("  대조 직접비 (6xxxx (도) 차변−대변): 원본 259,500,000 · CSV 259,500,000 → 일치", lines)
        self.assertIn("대조 불일치 0건", lines)
        # 02-03: 회사 합계 확인 1건 + 프로젝트별 합계 확인(2026-10 매출) 1건
        # + 02-REVIEW CR-04 올해 누계 매출 확인 1건 (모르는 칸이 있으니 판단 불가; 예전 2건)
        self.assertIn("대조 판단 불가 3건", lines)
        self.assertIn("대조 판단 불가 3건", out)
        d = mod("data").load(input_dir)
        R = mod("calc").compute(d, "monthly", dt.date(2026, 10, 31))
        company = [t for t in R["s4"]["sources"]["WEHAGO"]["table"] if t["unit"] == "회사"][0]
        self.assertIsNone(company["cur"]["revenue"])
        self.assertIsNone(company["ytd"]["revenue"])

    def test_a_line_without_a_date_is_listed_and_the_check_does_not_hide_it(self):
        undated = [None, 94, "대체", "61101", "행사외주비(도)", 700000, None, "가상기타", "V000", "날짜 없음"]
        tmp, input_dir, collect, wehago_dir, rc, out = converted(self, journal=FAKE_PL_JOURNAL + [undated])
        lines = read_result_lines(input_dir)
        self.assertEqual(rc, 0, out)
        self.assertIn("  알림 날짜 없는 손익 줄 1건 (직접비) 700,000", lines)
        self.assertIn("  대조 직접비 (6xxxx (도) 차변−대변): 원본 260,200,000 · CSV 259,500,000 → 불일치", lines)
        self.assertIn("대조 불일치 1건", lines)


class TestConvertLauncher(unittest.TestCase):
    NAME = "실행_변환.bat"

    def raw(self, name=None):
        with open(os.path.join(ROOT, name or self.NAME), "rb") as f:
            return f.read()

    def lines(self, name=None):
        return self.raw(name).decode("utf-8").split("\r\n")

    def test_bytes_are_utf8_crlf_without_bom_and_chcp_comes_first(self):
        raw = self.raw()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "BOM")
        self.assertEqual(raw.count(b"\r\n"), raw.count(b"\n"), "모든 줄이 CRLF")
        text = raw.decode("utf-8")
        first_non_ascii = min(i for i, ch in enumerate(text) if ord(ch) > 127)
        self.assertLess(text.index("chcp 65001"), first_non_ascii)

    def test_same_shape_as_the_monthly_launcher_except_three_lines(self):
        month = self.lines("실행_월간.bat")
        mine = self.lines()
        self.assertEqual(len(month), len(mine))
        diff = [i for i, (a, b) in enumerate(zip(month, mine)) if a != b]
        self.assertEqual(len(diff), 3, diff)
        echo, run, ok = diff
        self.assertTrue(mine[echo].lower().startswith("echo ") and "입력" in mine[echo] and "입력양식" in mine[echo])
        self.assertEqual(mine[run], "%PY% 변환.py %*")
        self.assertEqual(mine[ok], "echo 변환을 마쳤습니다. 입력\\변환결과.txt에 원본 합계 대조가 있습니다.")
        self.assertLess(echo, run)

    def test_one_pushd_one_note_exit_code_flow(self):
        lines = self.lines()
        self.assertEqual(len([i for i, ln in enumerate(lines) if ln.strip() == 'pushd "%~dp0"']), 1)
        run = next(i for i, ln in enumerate(lines) if ln.startswith("%PY% "))
        notes = [ln for ln in lines[:run] if ln.lower().startswith("echo") and "입력" in ln and "입력양식" in ln]
        self.assertEqual(len(notes), 1)
        rc = next(i for i, ln in enumerate(lines) if ln == 'set "RC=%ERRORLEVEL%"')
        ok = next(i for i, ln in enumerate(lines) if "변환을 마쳤습니다" in ln)
        fail = next(i for i, ln in enumerate(lines) if "오류가 발생했습니다" in ln)
        self.assertLess(run, rc)
        self.assertLess(rc, fail)
        self.assertLess(fail, ok)
        self.assertEqual(lines[-2], "exit /b %RC%")
        self.assertEqual(sum(1 for ln in lines if ln.strip().lower().startswith("exit /b")), 2)
        checks = [ln for ln in lines if "version_info" in ln and "(3, 8)" in ln]
        self.assertEqual(len(checks), 2)


if __name__ == "__main__":
    unittest.main()
