"""추정 예산 = 사전견적 × (100% − 팀 목표 수익률) (사용자 2026-11-05). 팀 목표가 없으면 설정.csv 예산_원가율(기본 70%)."""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report.calc import _cost_rate_of, compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import render  # noqa: E402

ASOF = dt.date(2026, 10, 31)
SAMPLE = os.path.join(ROOT, "입력양식", "샘플")


class TestCostRateOf(unittest.TestCase):
    T = {("2026", "기획1팀"): {"revenue": 900_000_000, "rate": 32.0}, ("2026", "기획2팀"): {"revenue": 1, "rate": None}}

    def test_team_target_rate(self):
        self.assertEqual(_cost_rate_of({"team": "기획1팀", "event_date": "2026-11-20"}, 0.7, self.T, ASOF), (0.68, "팀 목표"))

    def test_period_event_uses_end_year(self):
        p = {"team": "기획1팀", "event_date": "2025.12.30-2026.01.02"}
        self.assertEqual(_cost_rate_of(p, 0.7, self.T, ASOF), (0.68, "팀 목표"))

    def test_fallbacks(self):
        self.assertEqual(_cost_rate_of({"team": "기획1팀", "event_date": "2027-01-20"}, 0.7, self.T, ASOF), (0.7, "기본"))   # 그 해 목표 없음
        self.assertEqual(_cost_rate_of({"team": "기획2팀", "event_date": "2026-11-01"}, 0.7, self.T, ASOF), (0.7, "기본"))   # 수익률 빈칸
        self.assertEqual(_cost_rate_of({"team": "기획3팀", "event_date": ""}, 0.7, self.T, ASOF), (0.7, "기본"))           # 팀 목표 없음
        self.assertEqual(_cost_rate_of({"team": "기획1팀", "event_date": ""}, 0.7, self.T, ASOF), (0.68, "팀 목표"))       # 행사일 없으면 기준일의 해

    def test_setting_error_is_not_hidden_by_team_target(self):
        self.assertEqual(_cost_rate_of({"team": "기획1팀", "event_date": "2026-11-20"}, None, self.T, ASOF), (None, "기본"))


class TestBudgetFollowsTeamTarget(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.folder = os.path.join(self.tmp, "입력")
        shutil.copytree(SAMPLE, self.folder)
        with open(os.path.join(self.folder, "팀목표.csv"), "w", encoding="utf-8-sig", newline="") as f:
            f.write("연도,팀,매출목표,목표수익률\r\n2026,기획1팀,900000000,33\r\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_budget_and_label(self):
        R = compute(load(self.folder), "weekly", ASOF)
        P = {p["id"]: p for p in R["s3"]["projects"]}
        self.assertEqual(P["P26201"]["budget"], round(300_000_000 * 0.67))   # 기획1팀 2026 목표 33%
        self.assertEqual(P["P26201"]["cost_rate_source"], "팀 목표")
        self.assertEqual(P["P26203"]["budget"], round(150_000_000 * 0.7))    # 기획2팀 목표 없음 → 70%
        self.assertEqual(P["P26208"]["budget"], round(20_000_000 * 0.7))     # 2027 행사, 2027 목표 없음 → 70%
        self.assertEqual(R["s3"]["team_rate_n"], 3)   # P26201·P26204·P26205 (P26204 는 사전견적이 없어 예산은 없지만 원가율은 팀 목표)
        h = render(R, "mgmt")
        self.assertIn("추정 예산 = 사전견적 × (1 − 팀 목표 수익률)", h)
        self.assertNotIn("70%", h)

    def test_same_as_default_keeps_label(self):
        with open(os.path.join(self.folder, "팀목표.csv"), "w", encoding="utf-8-sig", newline="") as f:
            f.write("연도,팀,매출목표,목표수익률\r\n2026,기획1팀,900000000,30\r\n")
        R = compute(load(self.folder), "weekly", ASOF)
        self.assertEqual(R["s3"]["team_rate_n"], 0)
        self.assertNotIn("팀 목표 수익률이 있는 팀은", render(R, "mgmt"))


if __name__ == "__main__":
    unittest.main()
