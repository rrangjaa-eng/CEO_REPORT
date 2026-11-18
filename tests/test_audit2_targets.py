"""2차 전수조사 제안 18 (J2): 연중 목표 판정은 '누적 매출 + 앞으로 잡힐 매출'을 연 목표와 비교한다."""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ceo_report import annual  # noqa: E402
from ceo_report.render import _target_table  # noqa: E402


def _R(left, target=1000):
    return {"targets": {"기획1팀": {"revenue": target, "rate": None}},
            "s5": {"expected": None if left is None else {"missing": False, "by_team": {"기획1팀": {"past": left, "this_year": 0, "n": 1}}}}}


def _Y(rev):
    return {"rows": [{"kind": "team", "label": "기획1팀", "revenue": rev, "gp": 100}]}


class TestMonthlyVerdict(unittest.TestCase):
    def test_behind_pace_but_enough_coming_is_not_short(self):
        h = _target_table(_R(400), _Y(700), "2026-10")   # 70% < 83% 이지만 700 + 400 ≥ 1000
        self.assertIn("올해 예상 달성", h)
        self.assertNotIn("미달", h)
        self.assertIn("<td>1,100<br><small>목표의 110.0%</small></td>", h)

    def test_ahead_of_pace_but_nothing_coming_is_short(self):
        h = _target_table(_R(0), _Y(900), "2026-10")     # 90% ≥ 83% 이지만 더 잡힐 매출이 없음
        self.assertIn("올해 예상 미달", h)

    def test_already_over_target(self):
        self.assertIn("목표 이상", _target_table(_R(0), _Y(1000), "2026-10"))

    def test_unknown_coming_revenue_gives_no_verdict(self):
        h = _target_table(_R(None), _Y(700), "2026-10")
        self.assertNotIn("올해 예상", h)
        self.assertNotIn("목표 미달", h)
        self.assertIn("미확인", h)

    def test_december_compares_booked_revenue_only(self):
        h = _target_table(_R(400), _Y(700), "2026-12")
        self.assertIn("목표 미달", h)
        self.assertNotIn("올해 매출 예상", h)


class TestAnnualRisk(unittest.TestCase):
    def _A(self, cut, left):
        return {"cust": [], "speed": {}, "cut": cut, "mid": cut < 12, "closed": True, "asof": dt.date(2026, 11, 18),
                "teams": [{"name": "기획2팀", "rev": 700, "gp": 70, "goal": (1000, None), "left": left}],
                "proj": {"list": []}, "Y": {"rev": 700, "acct": {}}, "L": None}

    def _team_risks(self, A):
        return [r for r in annual._risks(A) if r[1] == "팀"]

    def test_mid_year_enough_coming_is_no_risk(self):
        self.assertEqual(self._team_risks(self._A(10, 400)), [])

    def test_mid_year_short_even_with_coming(self):
        r = self._team_risks(self._A(10, 100))
        self.assertEqual(len(r), 1)
        self.assertIn("앞으로 잡힐 매출까지 더하면 80.0%", r[0][2])
        self.assertIn("200", r[0][3])

    def test_mid_year_unknown_is_not_listed(self):
        self.assertEqual(self._team_risks(self._A(10, None)), [])

    def test_full_year_unchanged(self):
        r = self._team_risks(self._A(12, 400))
        self.assertEqual(len(r), 1)
        self.assertIn("매출 목표 70.0%, 수익률", r[0][2])


if __name__ == "__main__":
    unittest.main()
