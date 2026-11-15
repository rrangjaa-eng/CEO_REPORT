"""팀 매출·원가 = 분개장 부서명 (사용자 2026-11-04). 합성 숫자만 쓴다."""
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from ceo_report import convert, convert_pl  # noqa: E402
from test_dept import Books, line  # noqa: E402

D = dt.date(2026, 10, 5)


def journal():
    return [line(D, "41200", "용역매출", credit=50_000_000, dept="기획1팀"),
            line(D, "41200", "용역매출", credit=30_000_000, dept="기획2팀"),
            line(D, "61000", "외주비(도)", 20_000_000, dept="기획1팀"),
            line(D, "61000", "외주비(도)", 9_000_000, dept="기획2팀"),
            line(D, "61000", "외주비(도)", 1_000_000, dept="기획본부"),
            line(D, "61000", "외주비(도)", 500_000, dept=""),
            line(D, "80200", "직원급여(판)", 7_000_000, dept="기획1팀")]


class TestTeamByDept(unittest.TestCase):
    def test_teams_from_dept_and_rest_unassigned(self):
        t = convert_pl._dept_team_totals(Books(journal()), dict(convert.DEFAULT_CONFIG))["2026-10"]
        self.assertEqual(list(t), ["기획1팀", "기획2팀", "팀 미지정"])
        self.assertEqual(t["기획1팀"], {"revenue": [50_000_000, 0], "direct": [20_000_000, 0]})
        self.assertEqual(t["팀 미지정"], {"revenue": [0, 0], "direct": [1_500_000, 0]})

    def test_no_dept_column_gives_none(self):
        j = [line(D, "41200", "용역매출", credit=1)]
        self.assertIsNone(convert_pl._dept_team_totals(Books(j), dict(convert.DEFAULT_CONFIG)))

    def test_pl_csv_team_rows_without_snapshot(self):
        b = Books(journal())
        table = convert_pl.build_pl(b, dict(convert.DEFAULT_CONFIG), [], None)
        teams = [(r["대상"], r["매출"], r["직접비"]) for r in table.rows if r["단위"] == "팀"]
        self.assertEqual(teams, [("기획1팀", "50000000", "20000000"), ("기획2팀", "30000000", "9000000"),
                                 ("팀 미지정", "0", "1500000")])


class TestTeamWithoutCostLines(unittest.TestCase):
    def test_team_with_only_direct_cost_has_zero_salary(self):   # 실제 자료: 원가만 있는 기획3팀
        from ceo_report import teamprofit
        cur = lambda rev, gp: {"revenue": rev, "gp": gp, "common": None}
        table = [{"unit": "회사", "target": "회사 전체", "cur": cur(100, 40), "ytd": None},
                 {"unit": "팀", "target": "기획3팀", "cur": cur(0, -5), "ytd": None}]
        dept = [{"ym": "2026-10", "dept": "기획1팀", "salary": 8, "sga": 2, "heads": 2, "nonop_in": 0, "nonop_out": 0,
                 "has_nonop": True}]
        T = teamprofit.build(table, dept, "2026-10")
        row = [r for r in T["rows"] if r["label"] == "기획3팀"][0]
        self.assertEqual((row["salary"], row["sga"], row["net"]), (0, 0, -5))


if __name__ == "__main__":
    unittest.main()
