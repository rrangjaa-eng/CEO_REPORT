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
            fs = fs_of(html)
            for cells in tr_avail_rows(fs):
                self.assertIn("지급 자료 없음", cells[2])
                for val in cells[3:]:
                    self.assertIn("확인 필요", val)       # 잔액·최저·가용자금은 계산하지 않음
            self.assertIn("지급 자료 없음: ", fs)
            self.assertIn(name, fs.split("지급 자료 없음: ")[1].split("—")[0])
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


def fs_of(html):
    return html.split("<div class='toc'>")[0]


def tr_avail_rows(html):
    import test_report
    return test_report.avail_rows(html)


def tr_box_items(html):
    import test_report
    return test_report.box_items(html)


def tr_box_item(html, prefix):
    import test_report
    return test_report.box_item(html, prefix)


def kv_value(html, label):
    """첫 화면·상세의 '이름 / 값' 줄에서 첫 번째로 나오는 값 글자."""
    m = re.search(r'<div class="kv"><span>' + re.escape(label) + r"</span><span>(.*?)</span></div>", html, re.S)
    return text(m.group(1)) if m else None


def section(html, i):
    """상세 i번 묶음 (다음 묶음 머리글 앞까지)."""
    start = html.index("<h2 id='s%d'>" % i)
    end = html.find("<h2 id='s%d'>" % (i + 1), start)
    return html[start:end if end > 0 else len(html)]


class TestInvoiceFileUnusable(unittest.TestCase):
    """계산서.csv가 없거나 읽을 수 없거나 금액·날짜 열이 없으면 발행 후 미수·발행금액·입금예정을 0으로 보이지 않는다 (QA L2).

    전에는 첫 화면이 발행 후 미수 0.0, 발행금액 0.0, 향후 4주 입금예정 0.0으로 나왔다. 최저 계산 잔액은 계산서 입금 없이
    계산한다 (입금이 빠지면 잔액이 낮아지는 쪽이므로 보수적). 대신 그 사실과 파일 이름을 함께 적는다.
    """

    LABEL = "자료 없음 (계산서.csv)"

    def report(self, folder):
        R = compute(load(folder), "weekly", ASOF)
        return R, render(R, "ceo"), render(R, "mgmt")

    def assert_unknown(self, folder, why):
        R, ceo, mgmt = self.report(folder)
        base = compute(load(SAMPLE), "weekly", ASOF)
        s5 = R["s5"]
        self.assertEqual(R["s2"]["in_missing"], ["계산서.csv (%s)" % why])
        for key in ("issued", "ar", "unissued", "overdue_total"):
            self.assertIsNone(s5[key], key)
        for x in s5["by_project"]:
            self.assertIsNone(x["issued"])
            self.assertIsNone(x["ar"])
            self.assertIsNone(x["unissued"])
        self.assertEqual(s5["unissued_aged"], [])
        self.assertFalse([ev for ev in R["events"] if ev["source"] == "계산서"])
        # 최저 잔액은 계산한다: 계산서 입금이 빠졌으므로 샘플보다 높을 수 없다
        low, _ = R["s2"]["min"]["firm"]
        self.assertIsNotNone(low)
        self.assertLessEqual(low, base["s2"]["min"]["firm"][0])
        self.assertTrue(any(r["area"] == "자료" and "계산서.csv" in r["fact"] for r in R["risks"]), R["risks"])
        # 발행금액 0으로 만든 미발행·미수 위험을 만들지 않는다
        self.assertFalse([r for r in R["risks"] if r["area"] == "수금"])
        for html in (ceo, mgmt):
            fs = fs_of(html)
            # 첫 화면(2026-11-03 개편): 가용자금 표의 입금 칸마다 '계산서 자료 없음', 표 아래에 파일 이름. 잔액은 계산한다 (보수적)
            for cells in tr_avail_rows(fs):
                self.assertIn("계산서 자료 없음", cells[1])
                self.assertNotIn("확인 필요", cells[3])
            self.assertIn("계산서 입금 예정 미반영 (자료 없음: 계산서.csv)", fs)
            self.assertIn(self.LABEL, text(fs.split("행사 후 세금계산서 미발행</div><div class='big'>")[1].split("</div>")[0]))
            self.assertNotIn("미수금 (세금계산서 발행 후)", fs)   # 주간엔 미수금 없음, 월간에만 (사용자 2026-11-03)
        # 월간: 미수금 칸, 경영관리용 근거 묶음의 확인 목록
        RM = compute(load(folder), "monthly", ASOF)
        mfs = fs_of(render(RM, "mgmt"))
        for card in ("미수금 (세금계산서 발행 후)", "행사 후 세금계산서 미발행"):
            self.assertIn(self.LABEL, text(mfs.split(card + "</div><div class='big'>")[1].split("</div>")[0]), card)
        self.assertIn("입금예정일 지난 미수금: 계산서 자료 없음 (계산서.csv)", mfs)
        for prefix in ("날짜 없는 입금 예정", "예정일 지난 미처리"):
            inflow_side = tr_box_item(mfs, prefix).split(" / ")[0]
            self.assertIn("계산서 자료 없음", inflow_side, prefix)  # 입금 쪽 '0건 0'만 보이지 않는다
        for html in (ceo, mgmt):
            if html is ceo:   # 대표 보고는 요약만 (문서 1~2쪽, 사용자 2026-11-03). 상세 5번은 경영관리 보고에서 본다
                self.assertNotIn("<h2 id='s5'>", ceo)
                continue
            s5_html = section(html, 5)
            first = R["s3"]["projects"][0]["id"]
            row = re.search(r"<tr class=\"\"><td>%s</td>.*?</tr>" % re.escape(first), s5_html, re.S).group(0)
            self.assertEqual(text(row).count(self.LABEL), 3, text(row))
            total = re.search(r'<tr class="tot">.*?</tr>', s5_html, re.S).group(0)
            self.assertEqual(text(total).count(self.LABEL), 3, text(total))
            self.assertIn("계산서.csv (%s)" % why, text(s5_html))
        # 대표용과 경영관리용은 같은 숫자를 보인다. 확인 목록(근거)은 경영관리용에만 (사용자 2026-11-03)
        self.assertNotIn("<div class='xbox'>", fs_of(ceo))
        self.assertEqual(tr_avail_rows(fs_of(ceo)), tr_avail_rows(fs_of(mgmt)))
        self.assertNotIn("<h2 id='s5'>", ceo)   # 대표 보고는 요약만 (문서 1~2쪽, 사용자 2026-11-03)
        return R

    def test_missing_file(self):
        folder = sample_copy(self)
        os.remove(os.path.join(folder, "계산서.csv"))
        self.assert_unknown(folder, "파일 없음")

    def test_unreadable_encoding(self):
        folder = sample_copy(self)
        with open(os.path.join(folder, "계산서.csv"), "wb") as f:
            f.write(b"\xff\xfe\x00\xd8garbage\x81\x82\x83")
        self.assert_unknown(folder, "읽지 못함")

    def test_amount_column_missing(self):
        folder = sample_copy(self)
        rewrite(folder, "계산서.csv", drop_column("공급가액"))
        self.assert_unknown(folder, "필수 열 없음: 공급가액")

    def test_paid_column_missing(self):
        folder = sample_copy(self)
        rewrite(folder, "계산서.csv", drop_column("입금액"))  # 입금액을 모르면 전부 미수로 보여 입금예정이 부풀려진다
        self.assert_unknown(folder, "필수 열 없음: 입금액")

    def test_date_column_missing(self):
        folder = sample_copy(self)
        rewrite(folder, "계산서.csv", drop_column("입금예정일"))
        self.assert_unknown(folder, "필수 열 없음: 입금예정일")

    def test_optional_column_missing_still_computes(self):
        folder = sample_copy(self)
        rewrite(folder, "계산서.csv", drop_column("예정일확정"))
        R, _, _ = self.report(folder)
        base = compute(load(SAMPLE), "weekly", ASOF)
        self.assertEqual(R["s2"]["in_missing"], [])
        self.assertEqual(R["s5"]["issued"], base["s5"]["issued"])
        self.assertEqual(R["s5"]["ar"], base["s5"]["ar"])

    def test_sample_unchanged(self):
        R, ceo, _ = self.report(SAMPLE)
        self.assertEqual(R["s2"]["in_missing"], [])
        self.assertIsNotNone(R["s5"]["issued"])
        self.assertIsNotNone(R["s5"]["ar"])
        self.assertNotIn("계산서.csv", ceo)

    def test_report_cli_says_why(self):
        folder = sample_copy(self)
        os.remove(os.path.join(folder, "계산서.csv"))
        rc, out = run_report(self, ["주간", "--기준일", "2026-11-02", "--입력", folder, "--pdf", "안함"])
        self.assertEqual(rc, 0)
        self.assertIn("계산서 자료 없음: 계산서.csv (파일 없음)", out)

    def test_approval_screen_says_inflows_missing(self):
        import contextlib
        import io
        folder = sample_copy(self)
        os.remove(os.path.join(folder, "계산서.csv"))
        tmp = new_tmp(self)
        snap = write_fake_snapshot(os.path.join(tmp, "수집"))
        cli = load_approval_cli()
        path, A = cli.make_screen(folder, os.path.join(tmp, "출력"), snap, ASOF, NOW, False)
        with open(path, encoding="utf-8") as f:
            page = f.read()
        self.assertEqual(A["in_missing"], ["계산서.csv (파일 없음)"])
        self.assertNotEqual(T(page, "h-low"), "미확인")  # 최저 잔액은 계산한다 (계산서 입금 없이)
        self.assertIn("계산서.csv", T(page, "in-missing"))
        self.assertIn("계산서.csv", T(page, "attention"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.report(path, A, "(마지막 스냅숏)")
        self.assertIn("계산서 자료 없음: 계산서.csv (파일 없음)", buf.getvalue())

    def test_approval_sample_has_no_note(self):
        tmp = new_tmp(self)
        snap = write_fake_snapshot(os.path.join(tmp, "수집"))
        path, A = load_approval_cli().make_screen(SAMPLE, os.path.join(tmp, "출력"), snap, ASOF, NOW, False)
        with open(path, encoding="utf-8") as f:
            page = f.read()
        self.assertEqual(A["in_missing"], [])
        self.assertNotIn('id="in-missing"', page)


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


class TestOutputFolderUnwritable(unittest.TestCase):
    """--출력 이 파일이거나 만들 수 없는 경로면 트레이스백 대신 한 줄 안내와 종료 코드 7."""

    def blocked(self):
        tmp = new_tmp(self)
        path = os.path.join(tmp, "출력")
        with open(path, "w") as f:
            f.write("x")  # 같은 이름의 파일이 있어 폴더를 만들 수 없다
        return path

    def test_report(self):
        out = self.blocked()
        rc, text = run_report(self, ["주간", "--기준일", "2026-11-02", "--입력", SAMPLE, "--pdf", "안함", "--출력", out])
        self.assertEqual(rc, 7)
        self.assertIn("출력 폴더에 파일을 쓰지 못했습니다", text)
        self.assertIn(out, text)

    def test_approval(self):
        import contextlib
        import io
        out = self.blocked()
        root = os.path.join(new_tmp(self), "수집")
        write_fake_snapshot(root)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = load_approval_cli().main(["--기준일", "2026-11-02", "--입력", SAMPLE, "--수집폴더", root,
                                           "--출력", out, "--열기", "안함"])
        self.assertEqual(rc, 7)
        self.assertIn("출력 폴더에 파일을 쓰지 못했습니다", buf.getvalue())


class TestCsvOpenElsewhere(unittest.TestCase):
    """엑셀이 CSV를 열어 두면 Windows에서 읽기가 PermissionError 로 막힌다. 트레이스백 대신 입력 확인 목록에 남긴다.

    리눅스 시험에서는 같은 이름의 폴더로 open() 실패(OSError)를 만든다.
    """

    def test_report_runs_and_names_the_file(self):
        folder = sample_copy(self)
        os.remove(os.path.join(folder, "자금일정.csv"))
        os.mkdir(os.path.join(folder, "자금일정.csv"))
        rc, out = run_report(self, ["주간", "--기준일", "2026-11-02", "--입력", folder, "--pdf", "안함"])
        self.assertEqual(rc, 0)
        self.assertIn("자금일정.csv (읽지 못함)", out)
        R = compute(load(folder), "weekly", ASOF)
        self.assertTrue(any(f == "자금일정.csv" and "열 수 없음" in m and "엑셀" in m for f, _, m in R["s7"]["issues"]),
                        R["s7"]["issues"])
        self.assertEqual(R["s2"]["min"]["firm"], (None, None))


class TestPdfFailureMessage(unittest.TestCase):
    """PDF를 못 만들면 어느 파일인지와 대신 할 일(HTML 인쇄 → PDF로 저장)을 한국어로 알린다."""

    def test_names_file_and_fallback(self):
        from unittest import mock
        from test_approval import load_report_cli
        cli = load_report_cli()
        with mock.patch.object(cli, "find_browser", return_value="/없는/브라우저"), \
                mock.patch.object(cli, "to_pdf", return_value="PDF 실패 (브라우저가 파일을 만들지 않음)"):
            rc, out = run_report(self, ["주간", "--기준일", "2026-11-02", "--입력", SAMPLE])
        self.assertEqual(rc, 0)
        self.assertIn("2026-11-02_주간_대표보고.pdf", out)
        self.assertIn("2026-11-02_주간_경영관리보고.pdf", out)
        self.assertIn("'PDF로 저장'", out)

    def test_timeout_is_korean(self):
        import subprocess
        from unittest import mock
        from test_approval import load_report_cli
        cli = load_report_cli()
        tmp = new_tmp(self)
        html = os.path.join(tmp, "a.html")
        with open(html, "w", encoding="utf-8") as f:
            f.write("<html></html>")

        def slow(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 120)
        with mock.patch.object(cli.subprocess, "run", side_effect=slow):
            err = cli.to_pdf("b", html, os.path.join(tmp, "a.pdf"))
        self.assertIn("120초", err)
        self.assertNotIn("timed out", err)
        self.assertNotIn("--user-data-dir", err)
