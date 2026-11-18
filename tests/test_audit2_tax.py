"""2차 전수조사 제안 3·15 (2026-11-18): 법인세를 한 군데서만 계산, 근거 글이 아니라 숫자 칸으로 넘김. 가상 자료만."""
import csv
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import budget, corptax, planbs, tax  # noqa: E402
from ceo_report.data import load  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
ASOF = dt.date(2026, 11, 6)


def rewrite_tax(folder, change):
    """세금예상.csv 를 새 칸(감가상각·연말과세표준)까지 넣어 다시 쓴다. change(rows) 가 줄을 고친다."""
    path = os.path.join(folder, "세금예상.csv")
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    rows = change(rows)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, tax.COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(dict((k, r.get(k, "")) for k in tax.COLUMNS))


class BudgetUsesSharedYearEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inp = os.path.join(self.tmp, "입력")
        shutil.copytree(SAMPLE, self.inp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def B(self):
        d = load(self.inp)
        return budget.compute(d, budget.read_values(self.inp), 2027, ASOF, d.settings)

    def fix(self):
        return dict(((f["day"], f["name"]), f["amount"]) for f in self.B()["fix"])

    def test_budget_tax_equals_schedule_rows(self):
        def change(rows):
            main = [r for r in rows if r["세목"] == "법인세" and "(1월~" in r["대상기간"]][0]
            main.update({"과세표준": "100000000", "산출세액": "10000000", "기납부": "4000000", "감가상각": "0", "금액": "6000000"})
            rest = dict(main, 대상기간="2026년 11~12월" + tax.REST_MARK, 금액="5000000", 과세표준="", 산출세액="", 기납부="",
                        감가상각="", 연말과세표준="150000000")
            return rows + [rest]
        rewrite_tax(self.inp, change)
        B = self.B()
        self.assertTrue(B["tax_shared"])
        got = dict(((f["day"], f["name"]), f["amount"]) for f in B["fix"])
        corp = corptax.corp_tax(150_000_000, 2026)
        # 3/31 법인세 = 연말 예상 과세표준 1.5억의 세금 − 기납부 = 자금 일정 두 줄(600만 + 500만)과 같은 금액
        self.assertEqual(got[("3/31", "법인세 (2026년분)")], corp - 4_000_000)
        self.assertEqual(corp - 4_000_000, 6_000_000 + 5_000_000)
        self.assertEqual(B["L"]["tax"], corp + int(corp * 0.1))

    def test_no_rest_row_means_to_date_base(self):
        def change(rows):
            main = [r for r in rows if r["세목"] == "법인세" and "(1월~" in r["대상기간"]][0]
            main.update({"과세표준": "100000000", "산출세액": "10000000", "기납부": "4000000", "감가상각": "0"})
            return rows
        rewrite_tax(self.inp, change)
        self.assertEqual(self.fix()[("3/31", "법인세 (2026년분)")], 6_000_000)

    def test_old_file_keeps_old_calc(self):
        B = self.B()   # 샘플 파일에는 새 칸이 없다
        self.assertFalse(B["tax_shared"])


class NumbersNotFromText(unittest.TestCase):
    def test_columns(self):
        for c in ("감가상각", "연말과세표준"):
            self.assertIn(c, tax.COLUMNS)
        self.assertEqual(tax._row("법인세", "p", None, 1, "예상", "글")["감가상각"], "")

    def test_rest_row_has_year_end_base_only(self):
        by = {"2026-08": 30_000_000, "2026-09": 30_000_000, "2026-10": 30_000_000}
        nat, corp, _ = corptax.national(300_000_000, "2026")
        rows = corptax.rest_rows(by, "2026-10", {"annual": 12_000_000}, 300_000_000, nat, corp, "2026", None)
        self.assertEqual(rows[0]["연말과세표준"], "358000000")
        self.assertEqual(rows[0]["과세표준"], "")

    def test_monthly_reads_numbers_when_text_changes(self):
        from ceo_report import render as RD
        row = {"kind": "법인세", "period": "2026년 (1월~10월 장부 기준)", "basis": "글을 쉬운 말로 다 바꿈", "base": 100, "calc": 9,
               "prepaid": 0, "bad_debt": 7_000_000, "adj": 5, "due": None}
        R = {"tax": [row], "asof": dt.date(2026, 10, 31)}
        T = {"nonop": {"pretax": 50_000_000}}
        RD._bad_into(R, T, "2026-10")
        self.assertEqual(T["nonop"]["bad"], 7_000_000)
        self.assertEqual(T["nonop"]["pretax"], 43_000_000)


class ExcelTaxSameAsProgram(unittest.TestCase):
    def test_ratio_credit_follows_base(self):
        TI = {"min": 0.07, "sp_rate": 0.2, "pool": 40_000_000, "nong_share": 1.0, "nong": 0.2, "out": 0, "local": 0.1}
        for base in (50_000_000, 150_000_000, 400_000_000):
            cp = corptax.corp_tax(base, 2026)
            floor = int(base * 0.07)
            sp = min(int(cp * 0.2), cp - floor)
            used = min(40_000_000, cp - sp - floor)
            want = cp - sp - used + int(used * 0.2) // 10 * 10 + int(cp * 0.1)
            self.assertEqual(planbs.excel_tax(base, TI, 2026), want)
        # 이익이 줄면 감면도 같이 줄어든다 (예전: 고정 금액)
        self.assertLess(planbs.excel_tax(50_000_000, TI, 2026), planbs.excel_tax(150_000_000, TI, 2026))


if __name__ == "__main__":
    unittest.main()
