"""팀원별 순이익 몫 (사용자 2026-11-04: 1인당 순이익을 본인 급여 비율로만 나눔). 합성 자료만 쓴다."""
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from ceo_report import convert, convert_pl, teamprofit  # noqa: E402
from test_dept import Books, line  # noqa: E402

D = dt.date
CFG = dict(convert.DEFAULT_CONFIG)


def table(gp1, gp2):
    cur = lambda rev, gp, common=None: {"revenue": rev, "gp": gp, "common": common}
    return [{"unit": "회사", "target": "회사 전체", "cur": cur(100, gp1 + gp2), "ytd": None},
            {"unit": "팀", "target": "기획1팀", "cur": cur(60, gp1), "ytd": None},
            {"unit": "팀", "target": "기획2팀", "cur": cur(40, gp2), "ytd": None}]


def dept(ym, s1=6, s2=2, hq=4):
    return [{"ym": ym, "dept": d, "salary": s, "sga": 0, "heads": h, "nonop_in": 0, "nonop_out": 0, "has_nonop": True}
            for d, s, h in (("기획1팀", s1, 2), ("기획2팀", s2, 1), ("기획본부", hq, 1))]


def staff(ym, a=4, b=2, c=2):
    return [{"ym": ym, "dept": "기획1팀", "name": "가", "salary": a}, {"ym": ym, "dept": "기획1팀", "name": "나", "salary": b},
            {"ym": ym, "dept": "기획2팀", "name": "다", "salary": c}]


class TestPerPerson(unittest.TestCase):
    def test_share_is_team_alloc_times_own_salary_ratio(self):
        months = [("2026-09", table(30, 12)), ("2026-10", table(30, 12))]
        P = teamprofit.per_person(months, dept("2026-09") + dept("2026-10"), staff("2026-09") + staff("2026-10"), "2026-10")
        got = dict(((p["team"], p["name"]), p) for p in P["people"])
        t1 = P["teams"]["기획1팀"]["cur"]
        self.assertAlmostEqual(got[("기획1팀", "가")]["share"], t1 * 4 / 6)
        self.assertAlmostEqual(got[("기획1팀", "나")]["share"], t1 * 2 / 6)
        self.assertAlmostEqual(got[("기획1팀", "가")]["share"] + got[("기획1팀", "나")]["share"], t1)   # 팀 몫 합 = 팀 나눈 뒤 순수익
        self.assertAlmostEqual(got[("기획2팀", "다")]["share_ytd"], P["teams"]["기획2팀"]["ytd"])
        self.assertEqual((got[("기획1팀", "가")]["salary_ytd"], got[("기획1팀", "가")]["months"]), (8, 2))
        self.assertEqual([p["name"] for p in P["people"]], ["가", "나", "다"])

    def test_staff_sum_not_matching_dept_salary_is_unknown(self):   # 사원명 없는 급여 줄이 있던 달
        P = teamprofit.per_person([("2026-10", table(30, 12))], dept("2026-10", s1=7), staff("2026-10"), "2026-10")
        got = dict((p["name"], p) for p in P["people"])
        self.assertIsNone(got["가"]["share"])
        self.assertIsNone(got["가"]["share_ytd"])
        self.assertIsNotNone(got["다"]["share"])

    def test_no_staff_file_gives_none(self):
        self.assertIsNone(teamprofit.per_person([("2026-10", table(30, 12))], dept("2026-10"), None, "2026-10"))


class TestBuildStaff(unittest.TestCase):
    def test_rows_per_month_dept_employee_and_nameless_note(self):
        OCT = D(2026, 10, 25)
        books = Books([line(OCT, "80200", "직원급여(판)", 3_000_000, dept="기획1팀", emp="가"),
                       line(OCT, "80200", "직원급여(판)", 1_000_000, dept="기획1팀", emp="가"),
                       line(OCT, "80200", "직원급여(판)", 2_000_000, dept="기획2팀", emp="나"),
                       line(OCT, "80200", "직원급여(판)", 2_000_000, dept="기획2팀", emp=""),
                       line(OCT, "81201", "여비교통비_택시(판)", 50_000, dept="기획1팀", emp="가")])
        T = convert_pl.build_staff(books, CFG, [{"연월": "2026-01", "부서": "기획1팀", "사원명": "가", "급여": "1"},
                                               {"연월": "2026-10", "부서": "기획1팀", "사원명": "옛", "급여": "9"}])
        self.assertEqual([(r["연월"], r["부서"], r["사원명"], r["급여"]) for r in T.rows],
                         [("2026-01", "기획1팀", "가", "1"), ("2026-10", "기획1팀", "가", "4000000"),
                          ("2026-10", "기획2팀", "나", "2000000")])
        self.assertTrue(any("사원명 없는 급여 줄 1건" in n for n in T.notes))

    def test_journal_without_employee_column_is_not_written(self):
        T = convert_pl.build_staff(Books([line(D(2026, 10, 1), "80200", "직원급여(판)", 1)]), CFG)
        self.assertFalse(T.written)


class TestRender(unittest.TestCase):
    def test_person_table_only_in_mgmt_edition(self):
        from ceo_report.calc import compute
        from ceo_report.data import load
        from ceo_report.render import render
        R = compute(load(os.path.join(os.path.dirname(HERE), "입력양식", "샘플")), "monthly", D(2026, 10, 31))
        mg, ceo = render(R, "mgmt"), render(R, "ceo")
        self.assertIn("팀원별 순이익 몫", mg)
        self.assertIn("사원A", mg)
        self.assertNotIn("팀원별 순이익 몫", ceo)
        self.assertNotIn("사원A", ceo)


if __name__ == "__main__":
    unittest.main()
