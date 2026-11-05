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
    """지난주 대비 (사용자 2026-11-05): 지난주 출금일(이번 출금일 − 7일)에 통장에서 실제 나간 돈과 비교.
    대표용은 한 줄(빠진 것·추가된 것·변동된 것 건수와 금액), 건별 표는 경영관리용에만."""

    def R(self, rows):
        R = compute(load(SAMPLE), "weekly", D(2026, 10, 31))
        R["last_pay"] = {"date": D(2026, 10, 30), "rows": rows, "total": sum(r["amount"] for r in rows)}
        return R

    def test_outflow_list_is_first_and_shows_change_from_last_week(self):
        R = self.R([{"vendor": "샘플 지급처", "amount": 45_000_000, "memo": ""}])
        for edition in ("ceo", "mgmt"):
            fs = first_screen(render(R, edition))
            self.assertLess(fs.index("출금 목록"), fs.index("지금 자금은?"))
            self.assertIn("지난주 대비: 지난주(10/30) 출금 45,000,000 → 이번 출금", fs)

    def test_renders_when_last_week_record_exists(self):
        """지난주 보고 기록(지급예정_*.csv)이 있어도 두 판 모두 만들어짐 (11/5 PC에서 NameError 'compare')."""
        R = self.R([{"vendor": "샘플 지급처", "amount": 45_000_000, "memo": ""}])
        R["week_prev"] = {"asof": D(2026, 10, 24), "rows": [{"date": D(2026, 10, 30), "desc": "샘플 지급처", "project": "",
                                                            "cat": "미지급금", "amount": 45_000_000, "firm": True}]}
        for edition in ("ceo", "mgmt"):
            self.assertIn("지난주 대비", render(R, edition))

    def test_change_line_has_only_counts_and_detail_is_mgmt_only(self):
        from ceo_report.render import week_outflows
        R = self.R([{"vendor": "샘플 빠진 지급", "amount": 8_800_000, "memo": ""}])
        cur = week_outflows(R)["pay"]
        ceo, mg = first_screen(render(R, "ceo")), first_screen(render(R, "mgmt"))
        part = ceo[ceo.index("출금 목록"):]
        line = part[part.index("지난주 대비:"):]
        line = line[:line.index("</div>")]
        self.assertIn("빠진 것 1건 −8,800,000", line)
        self.assertIn("추가된 것 %d건" % len(cur["rows"]), line)
        self.assertNotIn("샘플 빠진 지급", ceo)          # 건별 이름은 대표용에 없음
        self.assertIn("대비 건별", mg)
        self.assertIn("샘플 빠진 지급", mg)
        self.assertLess(part.index("지난주 대비:"), part.index("다음 주 지급 예정"))

    def test_same_vendor_is_a_change_not_drop_and_add(self):
        from ceo_report.render import week_outflows
        e = week_outflows(self.R([]))["pay"]["rows"][0]
        R = self.R([{"vendor": "㈜ " + (e.get("desc") or ""), "amount": (e["amount"] or 0) + 100, "memo": ""}])
        ceo = first_screen(render(R, "ceo"))
        line = ceo[ceo.index("지난주 대비:"):]
        line = line[:line.index("</div>")]
        self.assertIn("변동된 것 1건 −100", line)
        self.assertNotIn("빠진 것", line)

    def test_next_week_is_summed_by_item(self):
        from ceo_report.render import _next_week_summary
        rows = [ev(D(2026, 11, 9), 1_000, "가"), ev(D(2026, 11, 12), 2_000, "나")]
        for r in rows:
            r["cat"] = "프로젝트 지급요청"
        html = _next_week_summary({"rows": rows, "total": 3_000})
        self.assertIn("<td>행사 외주·제작비</td><td>2건</td><td>11/09~11/12</td>", html)
        self.assertIn("3,000", html)

    def test_without_last_week_bank_data_says_so(self):
        R = compute(load(SAMPLE), "weekly", D(2026, 10, 31))
        R["last_pay"] = None
        fs = first_screen(render(R, "ceo"))
        self.assertIn("지난주(10/30) 출금 자료 없음", fs)
        self.assertNotIn("지난주 대비", render(compute(load(SAMPLE), "monthly", D(2026, 10, 31)), "ceo"))


class TestLastPayday(unittest.TestCase):
    def test_bank_outflows_on_last_payday_without_transfers(self):
        from ceo_report.calc import last_payday_out
        t = lambda d, io, amt, cat="", v="가": {"date": d, "io": io, "amount": amt, "cat": cat, "vendor": v, "memo": ""}
        txns = [t(D(2026, 10, 30), "출금", 100), t(D(2026, 10, 30), "출금", 50, "계좌간이체"), t(D(2026, 10, 30), "입금", 7),
                t(D(2026, 10, 29), "출금", 9), t(D(2026, 11, 2), "출금", 1)]
        L = last_payday_out(txns, D(2026, 11, 6))
        self.assertEqual((L["date"], L["total"], len(L["rows"])), (D(2026, 10, 30), 100, 1))
        self.assertIsNone(last_payday_out([t(D(2026, 10, 20), "출금", 1)], D(2026, 11, 6)))   # 그날까지 자료 없음


if __name__ == "__main__":
    unittest.main()
