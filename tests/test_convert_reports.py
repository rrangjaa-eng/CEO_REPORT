"""변환 결과를 보고서와 승인 화면이 읽는지 보는 통합 시험 (Phase 2, 계획 02-10, D-42 D-44 D-45 D-47 D-50).

가상 회사 한 곳(test_convert_e2e.full_company)을 변환.py 로 끝까지 돌린 뒤, 그 결과 폴더만 보고서.py 와 승인검토.py 에 넘긴다.
모든 장부·스냅숏·입력 폴더는 시험 때 임시 폴더에 가상 자료로 만든다. 실제 입력/·수집/ 폴더와 실제 WEHAGO 파일은 열지 않는다
(모든 실행이 --입력, --수집폴더, --위하고폴더, --출력 에 임시 폴더를 넘긴다).

이 파일의 시험은 이미 끝난 동작을 이어 붙여 보는 시험이다 (계획 V-1): 처음부터 통과하면 특성 시험(characterization test)이고,
실패하면 그 실패가 RED 증거이며 고치는 곳은 해당 모듈의 별도 'fix' 커밋이다.
"""
import collections
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import approval, calc, data, snapshot  # noqa: E402
from ceo_report.convert_xchk import load_xchk  # noqa: E402
from ceo_report.render import render  # noqa: E402
from test_approval import edit_csv, load_approval_cli, set_setting  # noqa: E402
from test_approval_wehago import body_rows, cells  # noqa: E402
from test_convert import ASOF, NOW, cli_argv, run_convert  # noqa: E402
from test_convert import setUpModule  # noqa: E402,F401  (샘플을 임시 폴더에 새로 쓴다)
from test_convert_e2e import full_company, run_core  # noqa: E402
from test_linking import write_links_csv  # noqa: E402
from test_monthly_xchk import (BASE_ASOF, STAMP, WEEKLY_ASOF, editions_ok, plain, run_cli,  # noqa: E402
                               section8, summary_rows, table_cells, weekly_baseline)
from test_report import check_editions  # noqa: E402

REQUEST_NO = re.compile(r"지급요청 (\d+)(?!\d)")


class Holder(unittest.TestCase):
    """setUpClass 에서 임시 폴더 정리를 맡기는 빈 시험 (full_company 가 test.addCleanup 을 쓴다)."""
    def runTest(self):
        pass


def converted_company(holder):
    """가상 회사 -> 변환.py (CLI) 한 번 -> (tmp, 입력, 수집, 위하고)."""
    tmp, input_dir, collect, wehago_dir = full_company(holder)
    rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
    assert rc == 0, out
    return tmp, input_dir, collect, wehago_dir


def request_numbers(text):
    return REQUEST_NO.findall(text or "")


# ───────────── Task 1 (tracer): 변환.py -> 보고서.py 주간·월간 ─────────────
class TestConvertedReports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.holder = Holder()
        cls.tmp, cls.input_dir, cls.collect, cls.wehago_dir = converted_company(cls.holder)
        cls.m_rc, cls.m_out, cls.monthly, _ = run_cli(cls.holder, cls.input_dir, "월간", BASE_ASOF)
        cls.w_rc, cls.w_out, cls.weekly, _ = run_cli(cls.holder, cls.input_dir, "주간", WEEKLY_ASOF)

    @classmethod
    def tearDownClass(cls):
        cls.holder.doCleanups()

    def test_both_report_runs_exit_zero_and_make_both_editions(self):
        self.assertEqual(self.m_rc, 0, self.m_out)
        self.assertEqual(self.w_rc, 0, self.w_out)
        self.assertEqual(sorted(self.monthly), ["ceo", "mgmt"])
        self.assertEqual(sorted(self.weekly), ["ceo", "mgmt"])

    def test_every_run_uses_temp_folders_never_the_real_input_or_collect_folders(self):
        for path in (self.input_dir, self.collect, self.wehago_dir):
            real = os.path.realpath(path)
            self.assertFalse(real == ROOT or real.startswith(ROOT + os.sep), path)

    def test_monthly_section_8_has_the_project_cost_in_both_editions(self):
        for mode in ("ceo", "mgmt"):
            with self.subTest(mode):
                self.assertIn("id='s8'", self.monthly[mode])
                rows = summary_rows(self.monthly[mode])
                self.assertTrue(rows["프로젝트 (도)원가"].startswith("258,400,000 ("), rows["프로젝트 (도)원가"])
                self.assertIn("258,400,000", plain(section8(self.monthly[mode])))

    def test_summary_rows_of_the_two_editions_are_the_same(self):
        self.assertEqual(summary_rows(self.monthly["ceo"]), summary_rows(self.monthly["mgmt"]))

    def test_ceo_edition_has_no_forbidden_word_and_the_same_numbers(self):
        editions_ok(self, self.monthly["ceo"], self.monthly["mgmt"])
        self.assertNotIn("xchk-detail", self.monthly["ceo"])
        self.assertIn("xchk-detail", self.monthly["mgmt"])

    def test_check_editions_of_test_report_passes_on_the_converted_folder(self):
        R = calc.compute(data.load(self.input_dir), "monthly", dt.date(2026, 10, 31))
        R["xchk"] = load_xchk(self.input_dir)
        self.assertEqual(R["xchk"]["state"], "ok")
        check_editions(self, R)
        self.assertIn("258,400,000", render(R, "ceo"))

    def test_weekly_html_equals_the_baseline_code_for_both_editions(self):
        old = weekly_baseline(self, self.input_dir)
        for mode in ("ceo", "mgmt"):
            with self.subTest(mode):
                self.assertEqual(STAMP.sub("", self.weekly[mode]), STAMP.sub("", old[mode]))

    def test_weekly_has_no_section_8(self):
        for page in self.weekly.values():
            self.assertNotIn("id='s8'", page)
            self.assertNotIn("WEHAGO 기준 대조", page)


# ───────────── Task 1: 변환 뒤 같은 지급을 두 번 세지 않음 (D-42, D-50) ─────────────
def copy_without_request_rows(test, input_dir):
    """변환 결과 폴더의 복사본에서 프로젝트집행.csv 의 '지급요청'이 근거에 있는 줄을 모두 뺀다."""
    folder = os.path.join(tempfile.mkdtemp(), "입력")
    test.addCleanup(shutil.rmtree, os.path.dirname(folder), True)
    shutil.copytree(input_dir, folder)

    def drop(rows):
        col = rows[0].index("근거")
        rows[:] = [rows[0]] + [r for r in rows[1:] if "지급요청" not in r[col]]
    edit_csv(folder, "프로젝트집행.csv", drop)
    return folder


def scheduled_total(A):
    return sum(r["schedule_amount"] for r in A["requests_all"] if r["scheduled"])


def outflow_total(A):
    """8주 일정에 들어간 지급 합계: 고정 지급(날짜별) + 체크할 수 있는 요청."""
    return sum(A["data"]["base_out"]) + sum(r["amount"] for r in A["data"]["requests"])


class TestConvertedNoDouble(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.holder = Holder()
        cls.tmp, cls.input_dir, cls.collect, cls.wehago_dir = converted_company(cls.holder)
        cls.snap = snapshot.read_snapshot(snapshot.latest_snapshot(cls.collect))
        cls.d = data.load(cls.input_dir)
        cls.R = calc.compute(cls.d, "weekly", ASOF)
        cls.A = approval.build(cls.d, cls.snap, ASOF, NOW, cls.wehago_dir, cls.input_dir)
        cls.bare_dir = copy_without_request_rows(cls.holder, cls.input_dir)
        cls.B = approval.build(data.load(cls.bare_dir), cls.snap, ASOF, NOW, cls.wehago_dir, cls.bare_dir)

    @classmethod
    def tearDownClass(cls):
        cls.holder.doCleanups()

    def exec_events(self):
        return [ev for ev in self.R["events"] if ev["source"] == "프로젝트집행" and ev["io"] == "out"]

    def test_calc_events_name_each_payment_request_number_at_most_once(self):
        seen = collections.Counter(n for ev in self.exec_events() for n in request_numbers(ev["basis"]))
        self.assertEqual(sorted(seen), ["1201", "5102", "5103", "5104", "5105", "5106", "5108"])
        self.assertEqual([n for n, c in seen.items() if c > 1], [])

    def test_requests_already_paid_or_without_a_known_state_are_not_events(self):
        named = set(n for ev in self.exec_events() for n in request_numbers(ev["basis"]))
        self.assertNotIn("5109", named)   # 장부에서 이미 지급
        self.assertNotIn("5107", named)

    def test_events_naming_5103_sum_to_the_larger_invoice_amount(self):
        events = [ev for ev in self.exec_events() if "5103" in request_numbers(ev["basis"])]
        self.assertEqual(sum(ev["amount"] for ev in events), 165000000)   # 요청 160,500,000 < 계산서 165,000,000

    def test_approval_schedules_each_request_once(self):
        scheduled = collections.Counter(r["번호"] for r in self.A["requests_all"] if r["scheduled"])
        self.assertEqual(sorted(scheduled), ["1201", "5102", "5103", "5105", "5108"])
        self.assertEqual([n for n, c in scheduled.items() if c > 1], [])
        ids = [r["id"] for r in self.A["data"]["requests"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_approval_schedules_5103_at_the_larger_amount(self):
        row = [r for r in self.A["requests_all"] if r["번호"] == "5103"][0]
        self.assertEqual((row["schedule_amount"], row["scheduled"], row["amount"]), (165000000, True, 160500000))

    def test_the_execution_rows_naming_a_scheduled_request_are_replaced_not_added(self):
        replaced = collections.Counter(n for ev in self.A["replaced"] for n in request_numbers(ev["basis"]))
        self.assertEqual(sorted(replaced), ["1201", "5102", "5103", "5105", "5108"])
        for ev in self.A["unmatched_exec"] + self.A["duplicates"] + self.A["possible_duplicates"]:
            self.assertFalse(set(request_numbers(ev["basis"])) & set(replaced), ev["basis"])

    def test_scheduled_request_amounts_equal_the_build_without_any_payment_request_rows(self):
        self.assertEqual(scheduled_total(self.A), 214764000)
        self.assertEqual(scheduled_total(self.A), scheduled_total(self.B))
        self.assertEqual([(r["번호"], r["schedule_amount"]) for r in self.A["requests_all"] if r["scheduled"]],
                         [(r["번호"], r["schedule_amount"]) for r in self.B["requests_all"] if r["scheduled"]])

    def test_the_whole_outflow_schedule_is_the_same_with_and_without_those_rows(self):
        self.assertEqual(outflow_total(self.A), outflow_total(self.B))
        self.assertEqual(self.A["data"]["base_out"], self.B["data"]["base_out"])
        self.assertEqual(self.A["data"]["requests"], self.B["data"]["requests"])

    def test_the_request_with_an_unknown_amount_is_listed_not_added_as_zero(self):
        self.assertEqual([r["번호"] for r in self.A["amount_unknown"]], ["5106"])
        self.assertEqual([request_numbers(ev["basis"]) for ev in self.A["amount_unknown_events"]], [["5106"]])
        self.assertEqual([r["번호"] for r in self.B["amount_unknown"]], ["5106"])


# ───────────── Task 2: 승인 화면 = 월간 8번 (변환 결과 폴더에서, D-47) ─────────────
def screen_for(test, tmp, input_dir, collect, wehago_dir):
    """승인 화면을 변환 결과 폴더로 만든다 -> (page, A)."""
    out = os.path.join(tmp, "승인출력")
    path, A = load_approval_cli().make_screen(input_dir, out, snapshot.latest_snapshot(collect), ASOF, NOW, False,
                                              wehago_dir=wehago_dir)
    with open(path, encoding="utf-8") as f:
        return f.read(), A


def monthly_projects(page):
    """월간 8번 프로젝트 표 -> {번호: 줄}"""
    return dict((r["번호"], r) for r in table_cells(page, "xchk-projects"))


def screen_projects(page):
    """승인 화면 프로젝트 표 -> {코드: [코드, 이름, 실행가, 요청 누계, WEHAGO 원가, ...]}"""
    return dict((cells(r)[0], cells(r)) for r in body_rows(page, "xchk-projects"))


def monthly_unlinked(page):
    """월간 8번 미연결 원가 -> (건수, 금액 글자). 상세 표의 합계 줄과 요약 줄이 같아야 한다."""
    lines = table_cells(page, "xchk-unlinked")
    total = [r for r in lines if r["전표"] == "합계"][0]["금액"]
    return len(lines) - 1, total


def head(text):
    """'판단 불가 (미확인 1건)' 처럼 뒤에 설명이 붙은 글자는 앞 낱말만 비교한다."""
    return "판단 불가" if text.startswith("판단 불가") else text


def assert_equal_surfaces(test, month_page, screen_page, A, label):
    monthly, screen = monthly_projects(month_page), screen_projects(screen_page)
    test.assertTrue(screen, label)
    for code, row in screen.items():
        test.assertIn(code, monthly, "%s %s: 월간 표에 없음" % (label, code))
        test.assertEqual(row[4], head(monthly[code]["WEHAGO 원가"]), "%s %s WEHAGO (도) 원가" % (label, code))
        test.assertEqual(row[3], head(monthly[code]["요청 누계"]), "%s %s 요청 누계" % (label, code))
    for code, row in monthly.items():
        if code not in screen:   # 원가 줄이 없는 프로젝트는 승인 표에 없다 (01.1 규칙)
            test.assertEqual(row["원가 줄"], "0줄", "%s %s" % (label, code))
    count, total = monthly_unlinked(month_page)
    u = A["xchk"]["unlinked"]
    test.assertEqual(count, u["count"], label)
    test.assertEqual(total, "{:,}".format(u["sum"]), label)
    test.assertEqual(summary_rows(month_page)["프로젝트 미연결 원가"], "%d줄 %s" % (count, total), label)
    test.assertIn("프로젝트 미연결 원가 %d건 %s" % (u["count"], total), plain(screen_page), label)


class TestConvertedApprovalEqual(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.holder = Holder()
        cls.tmp, cls.input_dir, cls.collect, cls.wehago_dir = converted_company(cls.holder)
        cls.dflt = cls.reports(cls.input_dir)
        # 사람이 프로젝트연결.csv 한 줄과 설정.csv 한 값을 고친 뒤 다시 변환한다
        write_links_csv(cls.input_dir, [["2026-10-29", "22", "1", "26221"]])
        edit_csv(cls.input_dir, "설정.csv", lambda rows: set_setting(rows, "변환_자동연결일수", "200"))
        res = run_core(cls.input_dir, cls.collect, cls.wehago_dir, "20261102_000001")
        assert res.code == 0, res.lines
        cls.linked = cls.reports(cls.input_dir)

    @classmethod
    def reports(cls, input_dir):
        rc, out, pages, _ = run_cli(cls.holder, input_dir, "월간", BASE_ASOF)
        assert rc == 0, out
        screen_page, A = screen_for(cls.holder, cls.tmp, input_dir, cls.collect, cls.wehago_dir)
        return pages, screen_page, A

    @classmethod
    def tearDownClass(cls):
        cls.holder.doCleanups()

    def test_default_settings_per_project_cost_and_request_total_equal(self):
        pages, screen_page, A = self.dflt
        for mode in ("ceo", "mgmt"):
            self.assertIn("258,400,000", plain(section8(pages[mode])))
        assert_equal_surfaces(self, pages["mgmt"], screen_page, A, "default")

    def test_default_known_numbers(self):
        pages, screen_page, A = self.dflt
        monthly, screen = monthly_projects(pages["mgmt"]), screen_projects(screen_page)
        self.assertEqual(sorted(screen), ["26201", "26203", "26220", "26221"])
        self.assertEqual(dict((k, v["WEHAGO 원가"]) for k, v in monthly.items()),
                         {"26201": "50,000,000", "26220": "158,000,000", "26221": "5,400,000", "26203": "45,000,000"})
        self.assertEqual(monthly_unlinked(pages["mgmt"]), (2, "1,100,000"))
        self.assertEqual((A["xchk"]["unlinked"]["count"], A["xchk"]["unlinked"]["sum"]), (2, 1100000))

    def test_an_unknown_request_total_reads_the_same_on_both_surfaces(self):
        pages, screen_page, A = self.dflt
        self.assertTrue(monthly_projects(pages["mgmt"])["26221"]["요청 누계"].startswith("판단 불가"))
        self.assertEqual(screen_projects(screen_page)["26221"][3], "판단 불가")
        self.assertIsNone([r for r in A["xchk"]["projects"] if r["code"] == "26221"][0]["requested"])

    def test_manual_link_and_link_days_after_converting_again_equal_on_both_surfaces(self):
        pages, screen_page, A = self.linked
        assert_equal_surfaces(self, pages["mgmt"], screen_page, A, "manual + 200")

    def test_the_manual_link_moves_the_cost_and_shrinks_the_unlinked_list_on_both_surfaces(self):
        pages, screen_page, A = self.linked
        self.assertEqual(monthly_projects(pages["mgmt"])["26221"]["WEHAGO 원가"], "6,200,000")   # 5,400,000 + 800,000
        self.assertEqual(screen_projects(screen_page)["26221"][4], "6,200,000")
        self.assertEqual(monthly_unlinked(pages["mgmt"]), (1, "300,000"))
        self.assertEqual((A["xchk"]["unlinked"]["count"], A["xchk"]["unlinked"]["sum"]), (1, 300000))

    def test_the_second_conversion_ends_with_zero_mismatches(self):
        with open(os.path.join(self.input_dir, "변환결과.txt"), encoding="utf-8-sig") as f:
            self.assertEqual(f.read().splitlines()[-1], "대조 불일치 0건")

    def test_the_total_project_cost_is_the_same_in_the_summary_and_on_the_screen(self):
        for pages, screen_page, A in (self.dflt, self.linked):
            total = sum(r["cost"] for r in A["xchk"]["projects"])
            self.assertTrue(summary_rows(pages["ceo"])["프로젝트 (도)원가"].startswith("{:,} (".format(total)))


# ───────────── Task 2: 회사 자료가 git 에 들어가지 않음 (D-45, T-02-31) ─────────────
class TestConvertedIgnored(unittest.TestCase):
    PATHS = ("입력/변환결과.txt", "입력/위하고대조.csv", "입력/이전/x.csv", "수집/위하고/전자세금계산서(매출)_20261031.xlsx")

    def check_ignore(self, path):
        try:
            return subprocess.run(["git", "-C", ROOT, "check-ignore", "-q", path],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
        except OSError:
            self.skipTest("git 없음")

    def test_generated_and_collected_company_files_are_ignored(self):
        for path in self.PATHS:
            with self.subTest(path):
                rc = self.check_ignore(path)
                if rc not in (0, 1):
                    self.skipTest("git 저장소 아님")
                self.assertEqual(rc, 0, "%s 가 git 무시 목록에 없음" % path)

    def test_the_blank_templates_are_not_ignored(self):
        rc = self.check_ignore("입력양식/설정.csv")
        if rc not in (0, 1):
            self.skipTest("git 저장소 아님")
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
