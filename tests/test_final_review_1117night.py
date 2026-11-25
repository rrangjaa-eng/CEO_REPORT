"""11/17 밤 최종 exe 검토 N1·N2·N3·N5 고침 시험 (예시 자료·합성 자료)."""
import csv
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from ceo_report import budget, insights, insights_more, insights_render  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
D = dt.date


class N1IdleCash(unittest.TestCase):
    """N1: '당분간 안 쓸 돈' 6달 줄이 자금계획서 끝에서 잘려 그 뒤 급여·세금이 빠지던 것."""
    def test_six_months_include_known_regular_outflows(self):
        with mock.patch.dict(os.environ, {"CEO_REPORT_TEST_GATE_OFF": "1"}):
            R = compute(load(SAMPLE), "monthly", D(2026, 10, 31))
        ic = insights_more.idle_cash(R)
        six = [r for r in ic["rows"] if r["months"] == 6][0]
        cal = insights.calendar(R, (six["upto"] - R["asof"]).days)
        low = min(min(c["firm"], c["all"]) for c in cal)
        self.assertEqual(six["low"], low)
        # 예시 자료: 자금계획(기간)은 1/31까지, 일정에는 4/30 지방세까지 → 6달 최저는 4/30 51,530,000 → 안 쓸 돈 0
        self.assertEqual((six["low"], six["low_day"], six["idle"], six["short"], six["after_plan"]),
                         (51_530_000, D(2027, 4, 30), 0, False, True))


class N3IssueFirm(unittest.TestCase):
    """N3: 예상 입금 포함으로는 안 모자라도 확정 기준으로 모자라면 경영관리 문장에 한 줄."""
    def test_firm_short_line(self):
        Dd = {"n": 1, "rows": [], "total": 49_500_000, "short": None, "firm_short": (D(2027, 4, 25), 47_100_000, D(2027, 4, 30), 48_470_000),
              "horizon": D(2027, 4, 30), "horizon_plan": False, "days": 60, "pay_if_today": D(2026, 12, 30)}
        s = insights_render.ceo_issue(Dd)
        self.assertIn("내려가지 않습니다", s)
        self.assertIn("다만 예상 입금이 늦으면", s)
        self.assertIn("4/25에 47,100,000원 모자랍니다", s)
        self.assertIn("2/24까지 발행해야", s)

    def test_firm_short_already_late(self):
        Dd = {"n": 1, "rows": [], "total": 1, "short": None, "firm_short": (D(2026, 12, 1), 5, D(2026, 12, 1), 5),
              "horizon": D(2027, 4, 30), "horizon_plan": False, "days": 60, "pay_if_today": D(2026, 12, 30)}
        s = insights_render.ceo_issue(Dd)
        self.assertIn("발행했어야", s)
        self.assertIn("12/30 입금", s)

    def test_no_line_when_firm_ok(self):
        Dd = {"n": 1, "rows": [], "total": 1, "short": None, "firm_short": None,
              "horizon": D(2027, 4, 30), "horizon_plan": False, "days": 60, "pay_if_today": D(2026, 12, 30)}
        self.assertNotIn("다만", insights_render.ceo_issue(Dd))


class N2BudgetTax(unittest.TestCase):
    """N2: 예산 법인세도 월간과 같은 과세표준(대손충당금·세무조정)·감면 계산, 지방세는 원천 지방세 뺌, 중간예납은 감면 뒤 × 6/12."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inp = os.path.join(self.tmp, "입력")
        shutil.copytree(SAMPLE, self.inp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _B(self):
        d = load(self.inp)
        return budget.compute(d, budget.read_values(self.inp), 2027, D(2026, 11, 6), d.settings, self.inp)

    def _set_tax_cols(self, bad_debt, adj, calc, local_amt):
        p = os.path.join(self.inp, "세금예상.csv")
        with open(p, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        cols = list(rows[0].keys()) + [c for c in ("대손충당금", "세무조정") if c not in rows[0]]
        for r in rows:
            r.setdefault("대손충당금", "")
            r.setdefault("세무조정", "")
            if r["세목"] == "법인세" and r["대상기간"].startswith("2026년 (1월~"):
                r["대손충당금"], r["세무조정"], r["산출세액"] = str(bad_debt), str(adj), str(calc)
            if r["세목"] == "법인지방소득세" and r["대상기간"].startswith("2026년 (1월~"):
                r["금액"] = str(local_amt)
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, cols)
            w.writeheader()
            w.writerows(rows)

    def test_uses_monthly_base(self):
        from ceo_report.corptax import corp_tax
        before = self._B()
        self._set_tax_cols(5_000_000, 1_000_000, 13_700_000, 1_000_000)   # 원천 지방세 1,370,000 − 1,000,000 = 370,000
        B = self._B()
        m = budget._tax_book(load(self.inp).tax, 2026)["m"]
        adj_y = int(round(1_000_000 * 12.0 / m))
        lc = corp_tax(B["L"]["pre"] - 5_000_000 + adj_y, 2026)
        self.assertEqual(B["L"]["tax"], lc + int(lc * 0.1))
        self.assertNotEqual(B["L"]["tax"], before["L"]["tax"])
        yc = corp_tax(B["Y"]["pre"] + adj_y, 2027)   # 내년은 대손충당금 안 뺌
        self.assertEqual(B["Y"]["tax"], yc + int(yc * 0.1))
        fix = dict((f["day"], f) for f in B["fix"])
        self.assertEqual(fix["4/30"]["amount"], int(lc * 0.1) - 370_000)
        self.assertIn("원천징수된 지방소득세 370,000", fix["4/30"]["how"])
        self.assertEqual(fix["8/31"]["amount"], budget._r4(int(lc * 6 / 12)))

    def test_small_interim_skipped(self):
        self.assertEqual(budget._tax_calc(None, 2026, None), None)
        T = budget._tax_calc(1_000_000, 2026, None)   # 산출세액 9만 → 중간예납 4.5만 < 50만
        self.assertLess(int(T["final"] * 6 / 12), 500_000)


class N5Secured(unittest.TestCase):
    def test_secured_and_more(self):
        months = {"2026-%02d" % m: (100_000_000, 70_000_000, 20_000_000) for m in range(1, 11)}
        bm = [(ym, [{"unit": "회사", "target": "회사 전체", "cur": {"revenue": r, "direct": c, "common": g}}]) for ym, (r, c, g) in sorted(months.items())]
        R = {"asof": D(2026, 10, 31), "s4": {"sources": {"WEHAGO": {"by_month": bm}}}, "targets": {"1팀": {"revenue": 1_200_000_000}},
             "s5": {"expected": {"missing": False, "est_n": 2, "past": 50_000_000, "this_year": 100_000_000}}}
        b = insights_more.breakeven(R)
        self.assertEqual((b["secured"], b["more"]), (150_000_000, 50_000_000))
        R["s5"]["expected"]["missing"] = True
        b = insights_more.breakeven(R)
        self.assertEqual((b["secured"], b["more"]), (None, None))


if __name__ == "__main__":
    unittest.main()
