"""부서별 급여·판관비·영업외 (사용자 2026-11-03): 분개장 관리항목 부서명·사원명으로 팀 순수익을 계산한다. 합성 자료만 쓴다."""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from ceo_report import convert, convert_pl, teamprofit, wehago  # noqa: E402
import xls_fixture as X  # noqa: E402

D = dt.date


def line(day, code, account, debit=None, credit=None, dept=None, emp=None):
    ln = {"date": day, "no": "1", "account_code": code, "account": account, "debit": debit, "credit": credit,
          "vendor": "", "memo": "", "sort": ""}
    if dept is not None:
        ln["dept"] = dept
    if emp is not None:
        ln["employee"] = emp
    return ln


class Books(object):
    def __init__(self, journal):
        self.journal = journal


CFG = dict(convert.DEFAULT_CONFIG)
OCT = D(2026, 10, 25)


class TestBuildDept(unittest.TestCase):
    def test_salary_sga_heads_and_nonop_by_dept(self):
        books = Books([
            line(OCT, "80200", "직원급여(판)", 3_000_000, dept="기획1팀", emp="가"),
            line(OCT, "80200", "직원급여(판)", 2_000_000, dept="기획1팀", emp="나"),
            line(OCT, "81201", "여비교통비_택시(판)", 50_000, dept="기획1팀"),
            line(OCT, "80200", "직원급여(판)", 4_000_000, dept="기획본부", emp="다"),
            line(OCT, "83100", "지급수수료(판)", 70_000, dept=""),                 # 부서 없음
            line(OCT, "92200", "정부지원금수익", credit=1_000_000, dept="경영관리"),
            line(OCT, "93100", "이자비용", 30_000, dept="기획본부"),
            line(OCT, "61000", "외주비(도)", 9_999_999, dept="기획1팀"),           # 원가는 넣지 않음
        ])
        T = convert_pl.build_dept(books, CFG)
        self.assertTrue(T.written)
        rows = dict((r["부서"], r) for r in T.rows)
        self.assertEqual((rows["기획1팀"]["급여"], rows["기획1팀"]["판관비"], rows["기획1팀"]["인원"]), ("5000000", "50000", "2"))
        self.assertEqual((rows["기획본부"]["급여"], rows["기획본부"]["영업외비용"]), ("4000000", "30000"))
        self.assertEqual(rows["부서 없음"]["판관비"], "70000")
        self.assertEqual(rows["경영관리"]["영업외수익"], "1000000")
        self.assertEqual(convert.check_result(T.checks[0]), "일치")

    def test_nameless_salary_line_leaves_heads_blank(self):
        books = Books([line(OCT, "80200", "직원급여(판)", 3_000_000, dept="기획1팀", emp="가"),
                       line(OCT, "80200", "직원급여(판)", 3_000_000, dept="기획1팀", emp="")])
        T = convert_pl.build_dept(books, CFG)
        self.assertEqual(T.rows[0]["인원"], "")
        self.assertTrue(any("사원명 없는 급여 줄 1건" in n for n in T.notes))

    def test_journal_without_dept_column_is_not_written(self):
        T = convert_pl.build_dept(Books([line(OCT, "80200", "직원급여(판)", 1)]), CFG)
        self.assertFalse(T.written)
        self.assertIn("부서명", T.reason)

    def test_months_missing_from_new_journal_keep_previous_rows(self):
        prev = [{"연월": "2026-01", "부서": "기획1팀", "급여": "1", "판관비": "2", "인원": "1", "영업외수익": "", "영업외비용": ""},
                {"연월": "2026-10", "부서": "기획1팀", "급여": "9", "판관비": "9", "인원": "9", "영업외수익": "", "영업외비용": ""}]
        T = convert_pl.build_dept(Books([line(OCT, "80200", "직원급여(판)", 5, dept="기획1팀", emp="가")]), CFG, prev)
        self.assertEqual([(r["연월"], r["급여"]) for r in T.rows], [("2026-01", "1"), ("2026-10", "5")])


class TestPrintJournalDept(unittest.TestCase):
    def test_print_xls_keeps_dept_and_employee(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        head = ["일자", "전표번호", "계정코드", "계정과목", "적요", "차변", "대변", "구분", "거래처코드", "거래처명",
                "부서코드", "부서명", "사원명", "프로젝트", "프로젝트명", "유형"]
        grid = [["회사명  :  가상회사", "기 간  : 2026년 01월 01일 ~ 2026년 10월 31일"] + [""] * 14, head,
                ["10/25", "00001", "80200", "직원급여(판)", "10월 급여", 3000000.0, "", "차변", "", "", "1", "기획1팀", "가상사원",
                 "", "", "일반전표"]]
        strings = []
        path = X.write_xls(os.path.join(tmp, "261103 분개장.xls"), X.grid_records(grid, strings), strings)
        rows, info = wehago.read_book(path, "분개장")
        self.assertEqual((rows[0]["dept"], rows[0]["employee"]), ("기획1팀", "가상사원"))
        self.assertEqual(info["extra_columns"], [])


class TestTeamProfit(unittest.TestCase):
    def table(self):
        cur = lambda rev, gp, common=None: {"revenue": rev, "gp": gp, "common": common}
        return [{"unit": "회사", "target": "회사 전체", "cur": cur(100, 40, 25), "ytd": None},
                {"unit": "팀", "target": "기획1팀", "cur": cur(60, 30), "ytd": None},
                {"unit": "팀", "target": "기획2팀", "cur": cur(40, 10), "ytd": None}]

    def dept(self, **over):
        rows = [("기획1팀", 8, 2, 2), ("기획2팀", 4, 1, 1), ("기획본부", 3, 1, 1), ("경영관리", 5, 1, 1)]
        out = [{"ym": "2026-10", "dept": d, "salary": s, "sga": g, "heads": h, "nonop_in": 0, "nonop_out": 0, "has_nonop": True}
               for d, s, g, h in rows]
        out[3]["nonop_in"] = 7
        return out

    def test_team_hq_company_rows_and_allocation(self):
        T = teamprofit.allocate(teamprofit.build(self.table(), self.dept(), "2026-10"))
        got = [(r["label"], r["net"]) for r in T["rows"]]
        self.assertEqual(got, [("기획1팀", 20), ("기획2팀", 5), ("기획본부 자체 비용", -4), ("기획본부 합계", 21), ("경영관리", -6)])
        self.assertEqual(T["company"]["net"], 15)                 # 40 − (8+2+4+1+3+1+5+1)
        self.assertEqual(T["check"], (25, 25))
        teams = [r for r in T["rows"] if r["kind"] == "team"]
        self.assertAlmostEqual(sum(r["alloc"] for r in teams), 15)   # 나눈 뒤 팀 합계 = 회사 영업이익
        self.assertAlmostEqual(teams[0]["alloc"], 20 + (15 - 25) * 2 / 3)
        self.assertEqual(T["nonop"]["pretax"], 22)
        self.assertNotIn("before_in", T["nonop"])

    def test_missing_dept_month_is_unknown_not_zero(self):
        T = teamprofit.build(self.table(), [], "2026-10")
        self.assertIsNone(T["rows"][0]["salary"])
        self.assertIsNone(T["company"]["net"])
        self.assertFalse(T["dept_ok"])


if __name__ == "__main__":
    unittest.main()
