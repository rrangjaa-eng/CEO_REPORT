"""변환 전체 시험 (Phase 2, 계획 02-07): 가상 회사 한 곳을 변환.py 로 끝까지 돌린다.

모든 장부·스냅숏·매출 계산서·입력 폴더는 시험 때 임시 폴더에 가상 자료로 만든다. 실제 입력/·수집/ 폴더와 실제 WEHAGO 파일은
열지 않는다 (모든 시험이 --입력, --수집폴더, --위하고폴더 에 임시 폴더를 넘긴다).
"""
import csv
import hashlib
import os
import re
import sys
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_approval import write_fake_snapshot  # noqa: E402
from test_convert import FAKE_PL_JOURNAL, cli_argv, convert_input, read_result_lines, run_convert, write_convert_books  # noqa: E402
from test_convert import ASOF, NOW  # noqa: E402
from test_convert import setUpModule  # noqa: E402,F401  (샘플을 임시 폴더에 새로 쓴다)
from test_convert_invoices import PURCHASE_LEDGER, SALES_EINVOICE, write_sales  # noqa: E402

GENERATED_CSV = ("손익.csv", "계산서.csv", "프로젝트.csv", "프로젝트집행.csv", "위하고대조.csv")
MANUAL_FILES = ("계좌잔액.csv", "설정.csv", "지급계획.csv", "변경내역.csv", "자료기준일.csv", "프로젝트연결.csv")
NEVER_WRITTEN = ("입출금내역.csv", "자금일정.csv", "자료차이.csv")
RRN_RUN = re.compile(r"\d{6}-?\d{7}")


def full_company(test, snapshot=True, sales=True, journal=None):
    """가상 회사 한 곳: 장부(FAKE_PL_JOURNAL) + 매출 계산서 엑셀(같은 폴더) + 인트라넷 스냅숏(<tmp>/수집).

    (tmp, 입력 폴더, 수집 폴더, 위하고 폴더)를 돌려준다. 입력 폴더는 샘플 복사본이다.
    """
    tmp, input_dir, collect, wehago_dir = convert_input(test)
    write_convert_books(wehago_dir, journal=FAKE_PL_JOURNAL if journal is None else journal, ledger=PURCHASE_LEDGER)
    if sales:
        write_sales(wehago_dir, SALES_EINVOICE)
    if snapshot:
        write_fake_snapshot(collect)
    return tmp, input_dir, collect, wehago_dir


def run_full(test, **kw):
    """full_company 를 변환.py 로 한 번 돌린다 -> (tmp, 입력, 수집, 위하고, 종료 코드, 표준 출력)."""
    tmp, input_dir, collect, wehago_dir = full_company(test, **kw)
    rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
    return tmp, input_dir, collect, wehago_dir, rc, out


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def read_csv_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def section(lines, header):
    """'[이름...' 으로 시작하는 줄부터 다음 '[' 줄 앞까지."""
    out, on = [], False
    for ln in lines:
        if not ln.startswith("  "):
            on = ln.startswith(header)
        elif on:
            out.append(ln)
    return out


class TestConvertEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Holder(unittest.TestCase):
            def runTest(self):
                pass
        cls.holder = Holder()
        cls.tmp, cls.input_dir, cls.collect, cls.wehago_dir = full_company(cls.holder)
        cls.before = dict((n, sha(os.path.join(cls.input_dir, n)))
                          for n in MANUAL_FILES + NEVER_WRITTEN if os.path.exists(os.path.join(cls.input_dir, n)))
        cls.rc, cls.out = run_convert(cli_argv(cls.input_dir, cls.collect, cls.wehago_dir))
        cls.lines = read_result_lines(cls.input_dir)

    @classmethod
    def tearDownClass(cls):
        cls.holder.doCleanups()

    def test_exits_zero_and_writes_the_five_csv_files_and_the_result_file(self):
        self.assertEqual(self.rc, 0, self.out)
        for name in GENERATED_CSV + ("변환결과.txt",):
            self.assertTrue(os.path.exists(os.path.join(self.input_dir, name)), name)
        for name in GENERATED_CSV:
            self.assertIn("[%s] 만듦" % name, "\n".join(self.lines))

    def test_every_check_matches_and_the_file_ends_with_zero_mismatches(self):
        checks = [ln for ln in self.lines if ln.startswith("  대조 ")]
        self.assertGreater(len(checks), 30)
        for ln in checks:
            self.assertTrue(ln.endswith("→ 일치"), ln)
        self.assertEqual(self.lines[-1], "대조 불일치 0건")

    def test_snapshot_money_reconciliation_lines(self):
        for want in (
                "  대조 사전견적 합계 (빈칸 제외): 원본 820,000,000 · CSV 820,000,000 → 일치",
                "  대조 사전견적 빈칸: 원본 0건 · CSV 0건 → 일치",
                "  대조 실행가 합계 (빈칸 제외): 원본 610,000,000 · CSV 610,000,000 → 일치",
                "  대조 실행가 빈칸: 원본 1건 · CSV 1건 → 일치",
                # 02-REVIEW CR-03 / D-52: 상태 확인 필요(반려) 5107 도 요청 줄로 센다 (예전 8건 · 7건 265,264,000)
                "  대조 지급요청 건수: 승인·대기 8 + 상태 확인 필요 1 = 원가 줄에 표시 3 + 요청 줄 5 + 이미 지급 1: 원본 9건 · CSV 9건 → 일치",
                "  대조 지급요청 금액 (금액 있는 승인·대기·상태 확인 필요 8건) = 원가 줄 표시 + 요청 줄 + 이미 지급: "
                "원본 266,364,000 · CSV 266,364,000 → 일치",
                "  대조 지급요청 금액 미확인: 원본 1건 · CSV 1건 → 일치"):
            self.assertIn(want, self.lines)

    def test_cross_file_totals_agree(self):
        lines = section(self.lines, "[파일 사이 대조]")
        self.assertEqual(len(lines), 5, lines)
        for want in (
                "  대조 손익 직접비 = 프로젝트집행 원가 줄 합계: 원본 259,500,000 · CSV 259,500,000 → 일치",
                "  대조 손익 직접비 = 위하고대조 (도) 원가: 원본 259,500,000 · CSV 259,500,000 → 일치",
                "  대조 손익 매출 = 위하고대조 매출: 원본 194,000,000 · CSV 194,000,000 → 일치",
                "  대조 손익 프로젝트 미연결 직접비 = 위하고대조 미연결원가: 원본 1,100,000 · CSV 1,100,000 → 일치",
                "  대조 손익 프로젝트 미연결 직접비 = 프로젝트집행 프로젝트.csv에 없는 번호의 원가 부분: "
                "원본 1,100,000 · CSV 1,100,000 → 일치"):
            self.assertIn(want, lines)

    def test_cross_file_totals_agree_in_the_written_files(self):
        pl = read_csv_rows(os.path.join(self.input_dir, "손익.csv"))
        head = pl[0]
        # 02-REVIEW CR-04: 새 분개장 밖 달의 이전 회사 줄은 남으므로 새 분개장의 달(2026-09~10)만 더한다
        company = [dict(zip(head, r)) for r in pl[1:] if r[0] == "WEHAGO" and r[2] == "회사" and r[1] in ("2026-09", "2026-10")]
        self.assertEqual(sum(int(r["직접비"]) for r in company), 259500000)
        self.assertEqual(sum(int(r["매출"]) for r in company), 194000000)
        unlinked = [dict(zip(head, r)) for r in pl[1:] if r[0] == "WEHAGO" and r[2] == "프로젝트" and r[3] == "프로젝트 미연결"]
        self.assertEqual(sum(int(r["직접비"] or 0) for r in unlinked), 1100000)
        keys = set(r[0] for r in read_csv_rows(os.path.join(self.input_dir, "프로젝트.csv"))[1:])
        execs = read_csv_rows(os.path.join(self.input_dir, "프로젝트집행.csv"))
        rows = [dict(zip(execs[0], r)) for r in execs[1:]]
        d50 = [r for r in rows if re.search(r"지급요청 5103(?!\d)", r["근거"])]
        self.assertEqual(sum(int(r["공급가액"] or 0) + int(r["부가세"] or 0) for r in d50), 165000000)
        xchk = read_csv_rows(os.path.join(self.input_dir, "위하고대조.csv"))
        facts = [dict(zip(xchk[0], r)) for r in xchk[1:]]
        row = [r for r in facts if r["구분"] == "미연결원가" and r["대상"] == "합계"][0]
        self.assertEqual(row["금액"], "1100000")
        self.assertTrue(keys)

    def test_cross_file_check_reports_a_difference(self):
        from ceo_report import convert
        tmp, input_dir, collect, wehago_dir = full_company(self.holder)
        res = convert.run(input_dir, collect, wehago_dir, ASOF, NOW, "20261102_000000")
        self.assertEqual(res.code, 0, res.lines)
        self.assertEqual([c for c in convert.cross_checks(res.tables) if convert.check_result(c) != "일치"], [])
        execs = [t for t in res.tables if t.name == "프로젝트집행.csv"][0]
        i = [k for k, p in enumerate(execs.extra["cost_portions"]) if p is not None][0]
        execs.extra["cost_portions"][i] += 1
        execs.rows[i]["공급가액"] = str(int(execs.rows[i]["공급가액"]) + 1)
        execs.checks[0] = convert.Check(execs.checks[0].label, execs.checks[0].source, execs.checks[0].csv + 1)
        bad = [c.label for c in convert.cross_checks(res.tables) if convert.check_result(c) == "불일치"]
        self.assertIn("손익 직접비 = 프로젝트집행 원가 줄 합계", bad)

    def test_csv_headers_are_the_schema(self):
        from ceo_report import data
        from ceo_report.convert_xchk import XCHK_COLUMNS
        want = dict((n, data.SCHEMA[n]) for n in GENERATED_CSV if n in data.SCHEMA)
        want["프로젝트.csv"] = data.SCHEMA["프로젝트.csv"] + ["실행가"]
        want["위하고대조.csv"] = XCHK_COLUMNS
        for name in GENERATED_CSV:
            self.assertEqual(read_csv_rows(os.path.join(self.input_dir, name))[0], want[name], name)

    def test_manual_files_and_bank_files_are_untouched_and_nothing_is_written_to_the_bank_file(self):
        for name, digest in self.before.items():
            self.assertEqual(sha(os.path.join(self.input_dir, name)), digest, name)
        for name in NEVER_WRITTEN:
            self.assertNotIn("[%s]" % name, "\n".join(self.lines))
        self.assertFalse([n for n in os.listdir(self.input_dir) if n.endswith(".변환중")])

    def test_previous_generated_files_are_kept_in_a_stamp_folder(self):
        base = os.path.join(self.input_dir, "이전")
        stamps = os.listdir(base)
        self.assertEqual(len(stamps), 1, stamps)
        kept = set(os.listdir(os.path.join(base, stamps[0])))
        for name in ("손익.csv", "계산서.csv", "프로젝트.csv", "프로젝트집행.csv"):
            self.assertIn(name, kept)
        self.assertEqual(kept & set(MANUAL_FILES + NEVER_WRITTEN), set())

    def test_no_resident_number_in_any_written_file_or_stdout(self):
        self.assertIsNone(RRN_RUN.search(self.out))
        for name in GENERATED_CSV + ("변환결과.txt",):
            with open(os.path.join(self.input_dir, name), encoding="utf-8-sig") as f:
                self.assertIsNone(RRN_RUN.search(f.read()), name)

    def test_stdout_has_one_line_per_file_and_the_result_path(self):
        out = self.out.splitlines()
        for name in GENERATED_CSV:
            self.assertEqual(len([ln for ln in out if ln.startswith(name + " ")]), 1, name)
        self.assertIn("대조 불일치 0건", out)
        self.assertEqual(out[-1], "대조 내용: " + os.path.join(self.input_dir, "변환결과.txt"))


# ───────────── Task 2: 만들지 못한 파일(D-46), 쓰기 전체 취소(T-02-29), 다시 돌리기, 자금일정 겹침, 입력 확인 목록 ─────────────
def tree(folder):
    """폴더 안 모든 파일의 {상대 경로: sha256}."""
    out = {}
    for base, _, files in os.walk(folder):
        for n in files:
            full = os.path.join(base, n)
            out[os.path.relpath(full, folder).replace(os.sep, "/")] = sha(full)
    return out


def set_day(path, year, month, day):
    stamp = time.mktime((year, month, day, 12, 0, 0, 0, 0, -1))
    os.utime(path, (stamp, stamp))


def run_core(input_dir, collect, wehago_dir, stamp="20261102_000000"):
    from ceo_report import convert
    return convert.run(input_dir, collect, wehago_dir, ASOF, NOW, stamp)


def backups(input_dir):
    base = os.path.join(input_dir, "이전")
    return sorted(os.listdir(base)) if os.path.isdir(base) else []


class TestConvertDegraded(unittest.TestCase):
    def test_no_snapshot_writes_pl_and_invoices_and_leaves_the_other_three_files_alone(self):
        tmp, input_dir, collect, wehago_dir = full_company(self, snapshot=False)
        before = dict((n, sha(os.path.join(input_dir, n))) for n in ("프로젝트.csv", "프로젝트집행.csv"))
        self.assertFalse(os.path.exists(os.path.join(input_dir, "위하고대조.csv")))
        rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        self.assertEqual(rc, 0, out)
        lines = read_result_lines(input_dir)
        for name in ("손익.csv", "계산서.csv"):
            self.assertIn("[%s] 만듦" % name, "\n".join(lines))
        for name in ("프로젝트.csv", "프로젝트집행.csv", "위하고대조.csv"):
            want = "[%s] 만들지 않음 — 인트라넷 스냅숏 없음 (기존 파일 그대로)" % name
            self.assertIn(want, lines)
            self.assertIn(want, out.splitlines())
        for name, digest in before.items():
            self.assertEqual(sha(os.path.join(input_dir, name)), digest, name)
        self.assertFalse(os.path.exists(os.path.join(input_dir, "위하고대조.csv")))
        kept = os.listdir(os.path.join(input_dir, "이전", backups(input_dir)[0]))
        self.assertEqual(sorted(kept), ["계산서.csv", "계정별비용.csv", "세금예상.csv", "손익.csv"])
        self.assertEqual(section(lines, "[파일 사이 대조]"), [])
        self.assertEqual(lines[-1], "대조 불일치 0건")

    def test_no_sales_file_keeps_the_existing_invoice_file_and_says_when_it_was_written(self):
        tmp, input_dir, collect, wehago_dir = full_company(self, sales=False)
        path = os.path.join(input_dir, "계산서.csv")
        set_day(path, 2026, 10, 15)
        before = sha(path)
        mtime = os.path.getmtime(path)
        rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        self.assertEqual(rc, 0, out)
        want = "[계산서.csv] 만들지 않음 — 매출 계산서 엑셀 없음 → 기존 계산서.csv 유지 (갱신 안 됨, 작성일 2026-10-15)"
        self.assertIn(want, read_result_lines(input_dir))
        self.assertIn(want, out.splitlines())
        self.assertEqual(sha(path), before)
        self.assertEqual(os.path.getmtime(path), mtime)
        for stamp in backups(input_dir):
            self.assertNotIn("계산서.csv", os.listdir(os.path.join(input_dir, "이전", stamp)))
        self.assertIn("[손익.csv] 만듦", "\n".join(read_result_lines(input_dir)))
        self.assertIn("[프로젝트.csv] 만듦", "\n".join(read_result_lines(input_dir)))

    def test_sales_file_with_a_missing_column_names_the_reason_first_and_keeps_the_file(self):
        tmp, input_dir, collect, wehago_dir = full_company(self, sales=False)
        write_sales(wehago_dir, SALES_EINVOICE, header=["일자", "거래처"])
        path = os.path.join(input_dir, "계산서.csv")
        set_day(path, 2026, 10, 15)
        before = sha(path)
        rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        self.assertEqual(rc, 0, out)
        line = [ln for ln in read_result_lines(input_dir) if ln.startswith("[계산서.csv] 만들지 않음")][0]
        self.assertTrue(line.startswith("[계산서.csv] 만들지 않음 — 매출 계산서 엑셀 머리글 다름"), line)
        self.assertTrue(line.endswith(" → 기존 계산서.csv 유지 (갱신 안 됨, 작성일 2026-10-15)"), line)
        self.assertIn(line, out.splitlines())
        self.assertEqual(sha(path), before)

    def test_no_sales_file_and_no_invoice_file_leaves_the_invoice_data_missing_not_zero(self):
        from ceo_report import calc, data
        tmp, input_dir, collect, wehago_dir = full_company(self, sales=False)
        os.remove(os.path.join(input_dir, "계산서.csv"))
        rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        self.assertEqual(rc, 0, out)
        self.assertIn("[계산서.csv] 만들지 않음 — 자료 없음 (매출 계산서 엑셀)", read_result_lines(input_dir))
        self.assertFalse(os.path.exists(os.path.join(input_dir, "계산서.csv")))
        d = data.load(input_dir)
        self.assertTrue(d.in_missing)
        R = calc.compute(d, "weekly", ASOF)
        self.assertTrue(R["s2"]["in_missing"])
        self.assertIsNone(R["s5"]["issued"])

    def test_each_locked_target_stops_with_exit_7_and_replaces_nothing(self):
        from ceo_report import convert
        tmp, input_dir, collect, wehago_dir = full_company(self)
        rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))   # 다섯 파일이 모두 있게 한 번 만든다
        self.assertEqual(rc, 0, out)
        real = convert._check_writable
        for locked_name in GENERATED_CSV + ("변환결과.txt",):
            before = tree(input_dir)

            def locked(path, locked_name=locked_name):
                if os.path.basename(path) == locked_name:
                    raise PermissionError(13, "Permission denied", path)
                return real(path)

            with mock.patch.object(convert, "_check_writable", side_effect=locked):
                rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
            self.assertEqual(rc, 7, (locked_name, out))
            self.assertIn("입력/%s을(를) 쓸 수 없음" % locked_name, out)
            self.assertEqual(tree(input_dir), before, locked_name)


class TestConvertRerun(unittest.TestCase):
    def test_second_run_on_its_own_output_gives_identical_files(self):
        tmp, input_dir, collect, wehago_dir = full_company(self)
        res = run_core(input_dir, collect, wehago_dir, "20261102_000000")
        self.assertEqual(res.code, 0, res.lines)
        first = dict((n, sha(os.path.join(input_dir, n))) for n in GENERATED_CSV)
        res = run_core(input_dir, collect, wehago_dir, "20261102_000001")
        self.assertEqual(res.code, 0, res.lines)
        for name in GENERATED_CSV:
            self.assertEqual(sha(os.path.join(input_dir, name)), first[name], name)
        self.assertEqual(backups(input_dir), ["20261102_000000", "20261102_000001"])
        self.assertEqual(read_result_lines(input_dir)[-1], "대조 불일치 0건")

    def test_carried_columns_survive_a_rerun(self):
        tmp, input_dir, collect, wehago_dir = full_company(self)
        run_core(input_dir, collect, wehago_dir, "20261102_000000")
        run_core(input_dir, collect, wehago_dir, "20261102_000001")
        projects = [dict(zip(read_csv_rows(os.path.join(input_dir, "프로젝트.csv"))[0], r))
                    for r in read_csv_rows(os.path.join(input_dir, "프로젝트.csv"))[1:]]
        by = dict((r["프로젝트번호"], r) for r in projects)
        self.assertEqual((by["26201"]["상태"], by["26201"]["예산수정일"], by["26201"]["계약금액"]), ("진행", "2026-09-15", "360000000"))
        self.assertEqual(by["26203"]["상태"], "진행")
        execs = read_csv_rows(os.path.join(input_dir, "프로젝트집행.csv"))
        plan = [r for r in execs[1:] if r[3] == "집행계획미요청"]
        self.assertEqual(len(plan), 4)
        self.assertIn("P26207", [r[0] for r in plan])
        pl = read_csv_rows(os.path.join(input_dir, "손익.csv"))
        self.assertEqual(len([r for r in pl[1:] if r[0] != "WEHAGO"]), 3)


def with_schedule_row(input_dir, row):
    """자금일정.csv 끝에 줄 하나를 더한다 (시험용 입력)."""
    path = os.path.join(input_dir, "자금일정.csv")
    with open(path, "a", encoding="utf-8", newline="") as f:
        csv.writer(f).writerow(row)


ADDED_SCHEDULE = ["2026-11-13", "출금", "44,000,000", "확정", "거래처미지급", "26201", "가상음향", "청구서", ""]
OVERLAP_HEAD = "자금일정.csv와 겹칠 수 있는 줄 %d건 (자금일정.csv는 바꾸지 않음)"


class TestConvertListings(unittest.TestCase):
    def test_plain_sample_has_no_overlap(self):
        tmp, input_dir, collect, wehago_dir, rc, out = run_full(self)
        self.assertEqual(rc, 0, out)
        lines = read_result_lines(input_dir)
        self.assertIn(OVERLAP_HEAD % 0, lines)
        self.assertEqual([ln for ln in lines if ln.startswith("  겹침 ")], [])

    def test_added_schedule_row_is_listed_once_and_the_schedule_file_is_not_changed(self):
        tmp, input_dir, collect, wehago_dir = full_company(self)
        with_schedule_row(input_dir, ADDED_SCHEDULE)
        before = sha(os.path.join(input_dir, "자금일정.csv"))
        rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        self.assertEqual(rc, 0, out)
        lines = read_result_lines(input_dir)
        self.assertIn(OVERLAP_HEAD % 1, lines)
        pairs = [ln for ln in lines if ln.startswith("  겹침 ")]
        self.assertEqual(len(pairs), 1, pairs)
        self.assertIn("2026-11-13 출금 44,000,000 26201 가상음향", pairs[0])
        self.assertIn("요청미지급", pairs[0])
        self.assertEqual(sha(os.path.join(input_dir, "자금일정.csv")), before)
        self.assertLess(lines.index(OVERLAP_HEAD % 1), lines.index("대조 불일치 0건"))
        self.assertIn(OVERLAP_HEAD % 1, out.splitlines())

    def test_input_check_listing_has_the_same_count_as_data_load(self):
        from ceo_report import data
        tmp, input_dir, collect, wehago_dir, rc, out = run_full(self)
        self.assertEqual(rc, 0, out)
        issues = data.load(input_dir).issues.items
        lines = read_result_lines(input_dir)
        self.assertGreater(len(issues), 0)
        self.assertIn("보고서 입력 확인 필요 %d건" % len(issues), lines)
        listed = [ln for ln in lines if ln.startswith("  확인 ")]
        self.assertEqual(len(listed), len(issues))
        self.assertIn("보고서 입력 확인 필요 %d건" % len(issues), out.splitlines())
        self.assertTrue([ln for ln in listed if "프로젝트 미연결" in ln], listed)

    def test_stdout_summary_lines_and_order(self):
        tmp, input_dir, collect, wehago_dir, rc, out = run_full(self)
        lines = out.splitlines()
        self.assertEqual(lines[0], "WEHAGO 장부 기준일 2026-10-31 · 기준일보다 2일 이전")
        # 02-REVIEW WR-06: 둘째 줄은 쓴 스냅숏과 나이 (예전: 바로 파일 줄)
        self.assertEqual(lines[1], "인트라넷 스냅숏 인트라넷_20261101_180000 (수집 2026-11-01 18:00:00, 기준일보다 1일 이전)")
        self.assertEqual([ln.split(" ")[0] for ln in lines[2:7]], list(GENERATED_CSV))
        tail = lines[-4:]
        self.assertEqual(tail[0], "대조 불일치 0건")
        self.assertTrue(tail[1].startswith("자금일정.csv와 겹칠 수 있는 줄 "))
        self.assertTrue(tail[2].startswith("보고서 입력 확인 필요 "))
        self.assertEqual(tail[3], "대조 내용: " + os.path.join(input_dir, "변환결과.txt"))

    def test_resident_numbers_never_reach_a_written_file_or_stdout(self):
        from test_approval import FAKE_PAYMENTS
        row = list(FAKE_PAYMENTS[0])
        row[0], row[1] = "5190", "[26201] 강사 900101-1234567 사례"
        tmp, input_dir, collect, wehago_dir = full_company(self, snapshot=False)
        write_fake_snapshot(collect, extra=[row])
        with_schedule_row(input_dir, ["2026-11-13", "출금", "1,000", "확정", "기타", "", "강사 900101-1234567", "", ""])
        rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        self.assertEqual(rc, 0, out)
        self.assertIsNone(RRN_RUN.search(out))
        for name in os.listdir(input_dir):
            path = os.path.join(input_dir, name)
            if os.path.isfile(path) and name in GENERATED_CSV + ("변환결과.txt",):
                with open(path, encoding="utf-8-sig") as f:
                    self.assertIsNone(RRN_RUN.search(f.read()), name)
        self.assertEqual(read_result_lines(input_dir)[-1], "대조 불일치 0건")


if __name__ == "__main__":
    unittest.main()
