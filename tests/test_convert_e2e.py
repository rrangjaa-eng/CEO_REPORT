"""변환 전체 시험 (Phase 2, 계획 02-07): 가상 회사 한 곳을 변환.py 로 끝까지 돌린다.

모든 장부·스냅숏·매출 계산서·입력 폴더는 시험 때 임시 폴더에 가상 자료로 만든다. 실제 입력/·수집/ 폴더와 실제 WEHAGO 파일은
열지 않는다 (모든 시험이 --입력, --수집폴더, --위하고폴더 에 임시 폴더를 넘긴다).
"""
import csv
import hashlib
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
                "  대조 지급요청 건수: 승인·대기 8 = 원가 줄에 표시 3 + 요청 줄 4 + 이미 지급 1: 원본 8건 · CSV 8건 → 일치",
                "  대조 지급요청 금액 (금액 있는 승인·대기 7건) = 원가 줄 표시 + 요청 줄 + 이미 지급: "
                "원본 265,264,000 · CSV 265,264,000 → 일치",
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
        company = [dict(zip(head, r)) for r in pl[1:] if r[0] == "WEHAGO" and r[2] == "회사"]
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


if __name__ == "__main__":
    unittest.main()
