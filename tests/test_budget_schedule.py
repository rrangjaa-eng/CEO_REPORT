"""남은 예산을 지급 예정으로 (D-54, 2026-11-03 사용자 결정: D-06 뒤집음).

남은 예산 = 원가 예산 − 예상총집행. 0보다 크면 행사일 다음 달 마지막 금요일에 부가세 10%를 더해 지급 예정으로 둔다.
그 날이 기준일 이전·당일이면 기준일 다음 금요일. 행사일이 없으면 날짜 없는 지급 예정. 완료 프로젝트는 넣지 않는다.
연도를 넘는 날짜(12월 행사 → 1월 말)도 그대로 이어진다.
"""
import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report.calc import budget_due, compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from sample_input import SAMPLE, refresh  # noqa: E402
from test_report import probe_folder  # noqa: E402

ASOF = dt.date(2026, 11, 2)


def budget_events(R):
    """프로젝트별로 묶음: 금액 = 나눠 잡은 줄의 합, date = 마지막 날 (행사일 다음 달 말 금요일), dates = 매주 금요일 목록."""
    out = {}
    for e in R["events"]:
        if e["source"] == "남은 예산":
            g = out.setdefault(e["project"], dict(e, amount=0, dates=[]))
            g["amount"] += e["amount"]
            g["dates"].append(e["date"])
            g["date"] = e["date"]
    return out


class TestBudgetDue(unittest.TestCase):
    def test_last_friday_of_next_month(self):
        self.assertEqual(budget_due(dt.date(2026, 11, 28), ASOF), dt.date(2026, 12, 25))

    def test_crosses_year(self):
        self.assertEqual(budget_due(dt.date(2026, 12, 3), ASOF), dt.date(2027, 1, 29))
        self.assertEqual(budget_due(dt.date(2027, 1, 20), ASOF), dt.date(2027, 2, 26))

    def test_past_due_spreads_to_month_end_friday(self):
        # 9월 행사 → 10월 30일(금)은 기준일 이전 → 그달 남은 금요일에 나눔: 끝 = 11월 마지막 금요일 (사용자 2026-11-05 결정)
        self.assertEqual(budget_due(dt.date(2026, 9, 18), ASOF), dt.date(2026, 11, 27))
        self.assertEqual(budget_due(dt.date(2026, 9, 18), dt.date(2026, 11, 6)), dt.date(2026, 11, 27))
        # 그달 남은 금요일이 하나뿐이면 다음 달 마지막 금요일까지
        self.assertEqual(budget_due(dt.date(2026, 9, 18), dt.date(2026, 11, 23)), dt.date(2026, 12, 25))

    def test_unknown_event_date(self):
        self.assertIsNone(budget_due(None, ASOF))


class TestBudgetEvents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        refresh()

    def test_remaining_budget_is_planned_payment_with_vat(self):
        R = compute(load(SAMPLE), "weekly", ASOF)
        ev = budget_events(R)
        # P26207: 예산 21,000,000 − 예상집행 14,000,000 = 7,000,000, 부가세 더해 7,700,000, 행사 11/28 → 12/25
        self.assertEqual(ev["P26207"]["amount"], 7700000)
        self.assertEqual(ev["P26207"]["date"], dt.date(2026, 12, 25))
        self.assertEqual(ev["P26207"]["io"], "out")
        self.assertFalse(ev["P26207"]["firm"])
        self.assertIn("남은 예산", ev["P26207"]["cat"])
        # P26208: 2027-01-20 행사 → 2027-02-26 (해를 넘김), 13,650,000 × 1.1
        self.assertEqual(ev["P26208"]["date"], dt.date(2027, 2, 26))
        self.assertEqual(ev["P26208"]["amount"], 15015000)

    def test_spread_over_every_friday_until_due(self):
        """진행 중 계속 쓰는 예산: 다음 금요일부터 행사일 다음 달 말 금요일까지 매주 나눠 잡는다 (사용자 2026-11-03)."""
        R = compute(load(SAMPLE), "weekly", ASOF)
        ev = budget_events(R)["P26207"]
        self.assertEqual(ev["dates"][0], dt.date(2026, 11, 6))
        self.assertEqual(ev["dates"], [dt.date(2026, 11, 6) + dt.timedelta(days=7 * k) for k in range(len(ev["dates"]))])
        self.assertEqual(len(ev["dates"]), 8)   # 11/06 ~ 12/25
        rows = [e for e in R["events"] if e["source"] == "남은 예산" and e["project"] == "P26207"]
        self.assertEqual(sorted(set(e["amount"] for e in rows[:-1])), [7700000 // 8])
        self.assertIn("매주 금요일 나눔 (1/8)", rows[0]["basis"])

    def test_not_for_done_over_or_unknown(self):
        ev = budget_events(compute(load(SAMPLE), "weekly", ASOF))
        for pid in ("P26202", "P26205",   # 완료
                    "P26201", "P26203",   # 예산 초과(남은 예산 ≤ 0)
                    "P26204",             # 예산 미지정
                    "P26206"):            # 금액 미확인 원가 → 판단 불가 (0으로 넣지 않음)
            self.assertNotIn(pid, ev)

    def test_unknown_remaining_listed(self):
        # 완료 프로젝트는 목록에도 없다. 진행 중인데 금액 미확인 원가가 있으면 남은 예산 판단 불가로 목록에 남는다
        self.assertEqual(compute(load(SAMPLE), "weekly", ASOF)["s3"]["remain_unknown"], [])

        def reopen(rows):
            i = rows[0].index("상태")
            for r in rows[1:]:
                if r[0] == "P26206":
                    r[i] = "진행"
        R = compute(load(probe_folder(self, "프로젝트.csv", reopen)), "weekly", ASOF)
        self.assertEqual([P["id"] for P in R["s3"]["remain_unknown"]], ["P26206"])
        self.assertNotIn("P26206", budget_events(R))

    def test_missing_event_date_is_undated(self):
        def blank_date(rows):
            i = rows[0].index("행사일")
            for r in rows[1:]:
                if r[0] == "P26207":
                    r[i] = ""
        R = compute(load(probe_folder(self, "프로젝트.csv", blank_date)), "weekly", ASOF)
        ev = budget_events(R)["P26207"]
        self.assertIsNone(ev["date"])
        self.assertEqual(ev["amount"], 7700000)

    def test_monthly_buckets_include_budget(self):
        R = compute(load(SAMPLE), "weekly", ASOF)
        dec = [b for b in R["s2"]["buckets"] if b["type"] == "month" and b["from"].month == 12][0]
        R0 = compute(load(SAMPLE), "weekly", ASOF)
        self.assertGreaterEqual(dec["out_est"], 7700000)
        self.assertEqual(R0["s2"]["buckets"][0]["label"], "1주차")


class TestTeamBudget(unittest.TestCase):
    """팀별 예산 (2026-11-03 사용자 "이어서 넣어"): 프로젝트 예산을 담당 팀(프로젝트.csv 팀)별로 더한다.
    WEHAGO 예산입력에 부서 예산을 두 번 넣지 않고 보고서에서 묶는다. 모르는 값은 0으로 넣지 않는다."""

    @classmethod
    def setUpClass(cls):
        refresh()
        cls.R = compute(load(SAMPLE), "weekly", ASOF)

    def team(self, name):
        return [t for t in self.R["s3"]["by_team"] if t["team"] == name][0]

    def test_team_rows_cover_every_project_once(self):
        teams = self.R["s3"]["by_team"]
        self.assertEqual([t["team"] for t in teams], ["기획1팀", "기획2팀"])
        self.assertEqual(sum(t["n"] for t in teams), len(self.R["s3"]["projects"]))

    def test_team_sums(self):
        t1 = self.team("기획1팀")   # P26201 210,000,000 · P26204 예산 미지정 · P26205 31,500,000 · P26208 14,000,000
        self.assertEqual((t1["n"], t1["budget"], t1["no_budget"]), (4, 255500000, 1))
        self.assertEqual(t1["expected"], 238200000 + 18000000 + 31000000 + 350000)
        # 잔여: P26201 −28,200,000 + P26205 500,000 + P26208 13,650,000 (예산 지정분만)
        self.assertEqual((t1["remain"], t1["remain_unknown"]), (-14050000, 0))
        self.assertEqual(t1["planned_pay"], 15015000)   # 진행 중 남은 예산 지급 예정(부가세 포함): P26208

    def test_unknown_remain_is_counted_not_zero(self):
        t2 = self.team("기획2팀")   # P26206 금액 미확인 원가 → 잔여 판단 불가
        self.assertEqual(t2["remain_unknown"], 1)
        self.assertEqual(t2["planned_pay"], 7700000)

    def test_rendered_in_section_3(self):
        from ceo_report.render import render
        html = render(self.R, "mgmt")
        self.assertIn("팀별 예산·집행", html)
        self.assertIn("기획1팀", html)


# ───── 인트라넷을 가용자금 일정에 넣던 규칙 (calc.INTRANET_IN_FUNDS=True) 으로 시험 ─────
# 사용자 결정(2026-11-04 '비교만') 뒤 기본은 False. 이 파일은 그 규칙이 켜졌을 때의 일정 계산을 그대로 지킨다.
import ceo_report.calc as _calc_for_flag  # noqa: E402
_setup_before_flag = globals().get("setUpModule")
_teardown_before_flag = globals().get("tearDownModule")


def setUpModule():  # noqa: F811
    _calc_for_flag.INTRANET_IN_FUNDS = True
    if _setup_before_flag:
        _setup_before_flag()


def tearDownModule():  # noqa: F811
    _calc_for_flag.INTRANET_IN_FUNDS = False
    if _teardown_before_flag:
        _teardown_before_flag()


if __name__ == "__main__":
    unittest.main()
