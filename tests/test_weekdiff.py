"""주간 보고: 지난주 예상 대비 이번 주 지급 변동 (사용자 2026-11-03). 시험 자료는 전부 가상이다.

지난주 보고가 '이번 주(기준일 다음 날부터 7일)에 나갈 것'으로 예상한 지급과, 이번 주 보고의 지급 예정 목록을 비교한다.
매주 보고서를 만들 때 앞으로 14일 지급 예정을 출력 폴더의 지급예정기록에 남겨 두고, 다음 주에 읽는다.
"""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report import weekdiff  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import render  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
D = dt.date


def ev(day, amount, desc, project="", cat="외주", firm=True):
    return {"date": day, "io": "out", "amount": amount, "desc": desc, "project": project, "cat": cat, "firm": firm}


def first_screen(html):
    return html.split("<div class='toc'>")[0]


class TestRecord(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_record_keeps_two_weeks_of_outflows_and_reads_back(self):
        R = {"asof": D(2026, 10, 24), "events": [
            ev(D(2026, 10, 20), 5, "지난 일"),             # 기준일 이전 (예정일 지남) → 기록 안 함
            ev(D(2026, 10, 25), 100, "가"),
            ev(D(2026, 11, 7), None, "나", firm=False),    # 금액 미확인도 남긴다
            ev(D(2026, 11, 8), 7, "14일 넘음"),
            {"date": D(2026, 10, 26), "io": "in", "amount": 9, "desc": "입금", "project": "", "cat": "", "firm": True}]}
        path = weekdiff.write_record(self.dir, R)
        self.assertTrue(path.endswith(os.path.join(weekdiff.RECORD_DIR, "지급예정_2026-10-24.csv")))
        prev = weekdiff.load_previous(self.dir, D(2026, 10, 31))
        self.assertEqual(prev["asof"], D(2026, 10, 24))
        self.assertEqual([(r["date"], r["amount"], r["desc"], r["firm"]) for r in prev["rows"]],
                         [(D(2026, 10, 25), 100, "가", True), (D(2026, 11, 7), None, "나", False)])

    def test_previous_is_latest_record_within_two_weeks_before(self):
        for day in ("2026-10-10", "2026-10-17", "2026-10-24", "2026-10-31"):
            weekdiff.write_record(self.dir, {"asof": D.fromisoformat(day), "events": []})
        self.assertEqual(weekdiff.load_previous(self.dir, D(2026, 10, 31))["asof"], D(2026, 10, 24))   # 같은 날 기록은 쓰지 않음
        self.assertEqual(weekdiff.load_previous(self.dir, D(2026, 11, 5))["asof"], D(2026, 10, 31))
        self.assertIsNone(weekdiff.load_previous(self.dir, D(2026, 11, 20)))   # 14일 넘게 지난 기록은 비교 안 함
        self.assertIsNone(weekdiff.load_previous(os.path.join(self.dir, "없음"), D(2026, 10, 31)))


class TestCompare(unittest.TestCase):
    def test_changes_are_listed_and_totals_differ_by_their_sum(self):
        start, end = D(2026, 11, 1), D(2026, 11, 7)
        prev = {"asof": D(2026, 10, 24), "rows": [
            ev(D(2026, 11, 2), 100, "가", "P1"),
            ev(D(2026, 11, 3), 50, "나", "P2"),
            ev(D(2026, 11, 4), 30, "다"),
            ev(D(2026, 11, 9), 999, "이번 주 밖")]}
        cur = [ev(D(2026, 11, 2), 120, "가", "P1"),      # 금액 바뀜
               ev(D(2026, 11, 5), 50, "나", "P2"),       # 날짜만 바뀜
               ev(D(2026, 11, 6), 40, "라"),             # 새로 생김
               ev(D(2026, 10, 30), 7, "예정일 지남")]     # 예정일 지난 미처리는 비교에서 뺀다 (지난주 예상 범위 밖)
        C = weekdiff.compare(prev, cur, start, end)
        self.assertEqual((C["prev_total"], C["cur_total"], C["diff"]), (180, 210, 30))
        kinds = [(c["kind"], c["desc"], c["prev"], c["cur"]) for c in C["changes"]]
        self.assertEqual(kinds, [("금액 바뀜", "가", 100, 120), ("빠짐", "다", 30, None),
                                 ("날짜 바뀜", "나", 50, 50), ("새로 생김", "라", None, 40)])
        self.assertEqual(sum((c["cur"] or 0) - (c["prev"] or 0) for c in C["changes"]), C["diff"])

    def test_unknown_amount_is_not_counted_as_zero(self):
        prev = {"asof": D(2026, 10, 24), "rows": [ev(D(2026, 11, 2), None, "가")]}
        C = weekdiff.compare(prev, [ev(D(2026, 11, 2), 10, "가")], D(2026, 11, 1), D(2026, 11, 7))
        self.assertIsNone(C["diff"])
        self.assertEqual(C["prev_unknown"], 1)
        self.assertEqual(C["changes"][0]["kind"], "금액 확인됨")


class TestWeeklyReport(unittest.TestCase):
    def test_outflow_list_is_first_and_shows_change_from_last_week(self):
        R = compute(load(SAMPLE), "weekly", D(2026, 10, 31))
        R["week_prev"] = {"asof": D(2026, 10, 24), "rows": [ev(D(2026, 11, 6), 45_000_000, "샘플 지급")]}
        for edition in ("ceo", "mgmt"):
            fs = first_screen(render(R, edition))
            self.assertLess(fs.index("출금 목록"), fs.index("지금 자금은?"))
            self.assertIn("지난주 대비:", fs)
            self.assertIn("45,000,000", fs)

    def test_change_line_has_only_dropped_added_changed(self):
        """금요일 목록 표 + 다음 주 항목별 요약 표. 아래 한 줄엔 빠진 것·추가된 것·변동된 것만 (사용자 2026-11-03)."""
        R = compute(load(SAMPLE), "weekly", D(2026, 10, 31))
        R["week_prev"] = {"asof": D(2026, 10, 24), "rows": [ev(D(2026, 11, 6), 8_800_000, "샘플 빠진 지급"),
                                                            ev(D(2026, 11, 9), 1_000_000, "다음 주 것")]}
        fs = first_screen(render(R, "ceo"))
        part = fs[fs.index("출금 목록"):fs.index("10월 실적")]
        # 비교 줄은 금요일 출금 카드 안 (다음 주 요약 표 앞): 지난주가 이번 금요일까지로 본 금액 vs 이번 금요일 (사용자 2026-11-03)
        self.assertLess(part.index("지난주 대비:"), part.index("다음 주 지급 예정"))
        self.assertEqual(part.count("<table"), 2)   # 금요일 출금 + 다음 주 항목별 요약
        self.assertIn("항목별 요약", part)
        line = part[part.index("지난주 대비:"):]
        line = line[:line.index("</div>")]
        self.assertIn("빠진 것 1건 −8,800,000 (샘플 빠진 지급)", line)
        self.assertIn("추가된 것", line)
        self.assertIn("지난주(10/24) 확정 8,800,000 → 이번 출금", line)   # 다음 주(11/09) 것은 비교에 넣지 않음
        self.assertNotIn("다음 주 것", line)
        for wordy in ("일정에서 없어짐", "= 지금"):
            self.assertNotIn(wordy, line)

    def test_next_week_is_summed_by_item(self):
        from ceo_report.render import _next_week_summary
        rows = [ev(D(2026, 11, 9), 1_000, "가"), ev(D(2026, 11, 12), 2_000, "나")]
        for r in rows:
            r["cat"] = "프로젝트 지급요청"
        html = _next_week_summary({"rows": rows, "total": 3_000})
        self.assertIn("<td>프로젝트 지급요청</td><td>2건</td><td>11/09~11/12</td>", html)
        self.assertIn("3,000", html)

    def test_without_last_week_record_says_so(self):
        R = compute(load(SAMPLE), "weekly", D(2026, 10, 31))
        fs = first_screen(render(R, "ceo"))
        self.assertIn("지난주 기록 없음", fs)
        self.assertNotIn("지난주 대비", render(compute(load(SAMPLE), "monthly", D(2026, 10, 31)), "ceo"))


class TestCli(unittest.TestCase):
    def test_second_week_compares_with_record_left_by_first_week(self):
        import contextlib
        import importlib.util
        import io
        spec = importlib.util.spec_from_file_location("report_cli", os.path.join(ROOT, "보고서.py"))
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        for day in ("2026-10-26", "2026-11-02"):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["주간", "--기준일", day, "--입력", SAMPLE, "--출력", out, "--pdf", "안함"]), 0)
        self.assertEqual(sorted(os.listdir(os.path.join(out, weekdiff.RECORD_DIR))),
                         ["지급예정_2026-10-26.csv", "지급예정_2026-11-02.csv"])
        with open(os.path.join(out, "2026-11-02_주간_대표보고.html"), encoding="utf-8") as f:
            self.assertIn("지난주 대비:", f.read())
        with open(os.path.join(out, "2026-10-26_주간_대표보고.html"), encoding="utf-8") as f:
            self.assertIn("지난주 기록 없음", f.read())


if __name__ == "__main__":
    unittest.main()
