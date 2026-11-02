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
from test_approval import edit_csv  # noqa: E402
from test_convert import ASOF, NOW, cli_argv, run_convert  # noqa: E402
from test_convert import setUpModule  # noqa: E402,F401  (샘플을 임시 폴더에 새로 쓴다)
from test_convert_e2e import full_company  # noqa: E402
from test_monthly_xchk import (BASE_ASOF, STAMP, WEEKLY_ASOF, editions_ok, plain, run_cli,  # noqa: E402
                               section8, summary_rows, weekly_baseline)
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


if __name__ == "__main__":
    unittest.main()
