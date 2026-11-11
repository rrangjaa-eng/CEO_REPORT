"""연간 보고 (사용자 2026-11-10 목업 승인). 가상 자료만 쓴다."""
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
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from ceo_report import annual, app, convert  # noqa: E402
from ceo_report.areas import strip_ui  # noqa: E402
import annual_sample  # noqa: E402

D = dt.date
CFG = dict(convert.DEFAULT_CONFIG)


def ln(day, no, code, account, debit=None, credit=None, vendor="", vcode="", memo=""):
    return {"date": day, "no": no, "account_code": code, "account": account, "debit": debit, "credit": credit,
            "vendor": vendor, "vendor_code": vcode, "memo": memo, "sort": ""}


class Books(object):
    state = "ok"

    def __init__(self, journal, ledger=()):
        self.journal = journal
        self.ledger = list(ledger)


class TestBuildTable(unittest.TestCase):
    def setUp(self):
        d = D(2026, 5, 10)
        self.books = Books([
            ln(d, "1", "10300", "보통예금", 1100, vendor="국민은행"), ln(d, "1", "10800", "외상매출금", credit=1100, vendor="A사", vcode="01023"),
            ln(d, "2", "10300", "보통예금", credit=500), ln(d, "2", "25100", "외상매입금", 500, vendor="갑제작", vcode="2011"),
            ln(d, "3", "10300", "보통예금", credit=300), ln(d, "3", "25500", "부가세예수금", 300),
            ln(d, "4", "10300", "보통예금", credit=200), ln(d, "4", "21200", "비품", 200),
            ln(d, "5", "10300", "보통예금", 1000), ln(d, "5", "26000", "단기차입금", credit=1000),
            ln(d, "6", "10300", "보통예금", 700, vendor="신한"), ln(d, "6", "10300", "보통예금", credit=700, vendor="국민"),   # 계좌간이체
            ln(D(2025, 2, 1), "1", "10300", "보통예금", 5000), ln(D(2025, 2, 1), "1", "33100", "자본금", credit=5000),
            ln(D(2026, 12, 31), "9", "99800", "법인세등", 2000), ln(D(2026, 12, 31), "9", "26100", "미지급법인세", credit=2000),
            ln(D(2026, 8, 31), "8", "13600", "선납세금", 650), ln(D(2026, 8, 31), "8", "10300", "보통예금", credit=650),
        ], ledger=[{"date": d, "vendor": "갑제작", "supply": 450}])
        self.sales = {"state": "ok", "rows": [{"date": d, "vendor": "A사", "supply": 1000}, {"date": D(2025, 6, 1), "vendor": "A사", "supply": 300}]}

    def rows(self, prev=()):
        t = annual.build_table(self.books, CFG, self.sales, prev)
        return dict(((r["연도"], r["구분"], r["항목"]), (r["코드"], int(r["금액"]))) for r in t.rows)

    def test_cash_flow_classes_and_transfer_excluded(self):
        R = self.rows()
        self.assertEqual(R[("2026", "현금흐름", "영업 입금")][1], 1100)
        self.assertEqual(R[("2026", "현금흐름", "영업 지급")][1], -500)
        self.assertEqual(R[("2026", "현금흐름", "세금")][1], -300 - 650)   # 부가세 + 선납세금(중간예납)
        self.assertEqual(R[("2026", "현금흐름", "투자")][1], -200)
        self.assertEqual(R[("2026", "현금흐름", "대출 받음")][1], 1000)
        self.assertEqual(R[("2025", "현금흐름", "자본금 납입")][1], 5000)
        self.assertNotIn(("2026", "현금흐름", "대출 갚음"), R)

    def test_vendors_with_code_and_closing(self):
        R = self.rows()
        self.assertEqual(R[("2026", "매출거래처", "A사")], ("1023", 1000))   # 코드 앞 0 제거
        self.assertEqual(R[("2025", "매출거래처", "A사")][1], 300)
        self.assertEqual(R[("2026", "매입거래처", "갑제작")], ("2011", 450))
        self.assertEqual(R[("2026", "결산", "법인세등")][1], 2000)
        self.assertEqual(R[("2026", "결산", "선납세금")][1], 650)

    def test_keeps_years_missing_from_new_journal(self):
        prev = [{"연도": "2024", "구분": "매출거래처", "항목": "옛사", "코드": "9", "금액": "7"},
                {"연도": "2026", "구분": "매출거래처", "항목": "지운사", "코드": "8", "금액": "9"}]
        R = self.rows(prev)
        self.assertIn(("2024", "매출거래처", "옛사"), R)
        self.assertNotIn(("2026", "매출거래처", "지운사"), R)

    def test_no_journal_keeps_file(self):
        b = Books([])
        b.state = "자료 없음"
        self.assertFalse(annual.build_table(b, CFG, {}, []).written)


class TestReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="annual_")
        cls.inp = os.path.join(cls.tmp, "입력")
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_sample.py"), cls.inp], check=True, stdout=subprocess.DEVNULL)
        annual_sample.extend(cls.inp)
        cls.A = annual.compute(cls.inp, 2026, {"회사명": "(샘플)", "위험_최소보유현금": "100000000"})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def test_pl_and_last_year(self):
        Y, L = self.A["Y"], self.A["L"]
        self.assertTrue(Y["full"])
        self.assertEqual(Y["op"], Y["rev"] - Y["cogs"] - Y["common"])
        self.assertEqual(Y["pre"], Y["op"] + Y["nin"] - Y["nout"])
        self.assertEqual(len(L["months"]), 11)
        self.assertEqual(L["rev"], sum(annual_sample.REV25.values()) * annual_sample.M)

    def test_closing_values_fixed(self):
        A = self.A
        self.assertTrue(A["closed"])
        self.assertTrue(A["tax_fixed"])
        self.assertEqual(A["tax"], 21311400)
        self.assertEqual(A["dep_est"], 12000000)   # 작년 장부 감가상각비
        self.assertEqual(A["prepaid"], 6500000)
        self.assertEqual(A["pay_corp_day"], D(2027, 3, 31))
        self.assertEqual(A["pay_local_day"], D(2027, 4, 30))

    def test_not_closed_subtracts_depreciation_estimate(self):
        tmp = tempfile.mkdtemp()
        try:
            shutil.copytree(self.inp, os.path.join(tmp, "입력"))
            p = os.path.join(tmp, "입력", "계정별비용.csv")
            with open(p, encoding="utf-8-sig") as f:
                keep = [x for x in f if not ("2026-12" in x and "감가상각비" in x)]
            with open(p, "w", encoding="utf-8-sig") as f:
                f.writelines(keep)
            A = annual.compute(os.path.join(tmp, "입력"), 2026, {})
            self.assertFalse(A["closed"])
            self.assertEqual(A["Y"]["dep_pending"], 12000000)
            self.assertEqual(A["Y"]["pre"], A["Y"]["op"] + A["Y"]["nin"] - A["Y"]["nout"] - 12000000)
        finally:
            shutil.rmtree(tmp, True)

    def test_cash_flow_adds_up(self):
        A = self.A
        self.assertEqual(A["bal0"] + sum(v for _, v in A["cf"]) + A.get("cf_gap", 0), A["bal_end"])

    def test_customers_change(self):
        A = self.A
        self.assertEqual([n for n, _, _ in A["new"]], ["G사", "H사"])
        self.assertEqual([n for n, _, _ in A["lost"]], ["가사"])
        self.assertEqual(sorted(A["kept"]), ["A사", "B사", "C사"])

    def test_speed_and_next_year(self):
        S = self.A["speed"]
        self.assertGreaterEqual(S["n"], 2)
        self.assertTrue(any(x[0] == "B사" and x[5] > 60 for x in S["over60"]))
        ids = [p["id"] for p in self.A["next"]]
        self.assertIn("P27003", ids)   # 행사일이 기간이면 끝난 날의 해
        self.assertIn("P27005", ids)
        self.assertNotIn("P27001", ids)
        self.assertEqual(self.A["goals_next"]["기획1팀"][0], 1100000000)

    def test_render_both_modes(self):
        ceo, mg = annual.render(self.A, "ceo"), annual.render(self.A, "mgmt")
        for page in (ceo, mg):
            self.assertNotIn("None", re.sub(r"<[^>]+>", " ", page))
            self.assertIn("2026년 연간", page)
            self.assertIn("A사 [1023]", page)   # 거래처명 [코드]
            self.assertNotIn("70%", re.sub(r"<[^>]+>", " ", page))   # '추정 예산'이라 부르고 70% 표기 안 함
            self.assertNotIn("지원금", page)
        self.assertNotIn("위험 분석", ceo)
        self.assertIn("위험 분석", mg)
        self.assertIn("경영관리용", mg)
        self.assertNotIn("<script", ceo)
        self.assertNotIn("<script", strip_ui(mg))   # 경영관리용은 영역별 보기 장치만 (사용자 2026-11-11)
        self.assertIn("id='anav'", mg)
        self.assertEqual(re.findall(r"<section class='area' id='a-([^']+)'", mg), ["sum", "risk", "d1", "d2", "d3", "d4", "d5", "d6"])
        self.assertEqual(mg.count("<div"), mg.count("</div>"))

    def test_cli_writes_files(self):
        out = os.path.join(self.tmp, "출력")
        import 보고서
        self.assertEqual(보고서.main(["연간", "--연도", "2026", "--입력", self.inp, "--출력", out, "--pdf", "안함"]), 0)
        self.assertTrue(os.path.isfile(os.path.join(out, "2026_연간_대표보고.html")))
        self.assertTrue(os.path.isfile(os.path.join(out, "2026_연간_경영관리보고.html")))
        self.assertEqual(보고서.main(["연간", "--연도", "1999", "--입력", self.inp, "--출력", out, "--pdf", "안함"]), 2)
        self.assertEqual(보고서.main(["연간", "--연도", "26", "--입력", self.inp, "--출력", out, "--pdf", "안함"]), 2)

    def test_task_argv(self):
        P = app.Paths(self.tmp)
        name, argv = app.task_argv("연간", P, asof="2027-02-20", year="2026")
        self.assertEqual(name, "보고서")
        self.assertEqual(argv[:3], ["연간", "--기준일", "2027-02-20"])
        self.assertIn("2026", argv)


if __name__ == "__main__":
    unittest.main()
