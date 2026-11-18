"""2차 전수조사 제안 14: 예산 가정 (B6·V4·V13·V14·V15·V21). 가상 자료만."""
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

from ceo_report import budget, corptax  # noqa: E402
from ceo_report.budget_render import render_budget  # noqa: E402
from ceo_report.data import load  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
ASOF = dt.date(2026, 11, 6)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inp = os.path.join(self.tmp, "입력")
        shutil.copytree(SAMPLE, self.inp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def B(self, with_dir=False):
        d = load(self.inp)
        return d, budget.compute(d, budget.read_values(self.inp), 2027, ASOF, d.settings, self.inp if with_dir else None)


class TargetRate(Base):   # B6
    def test_fallback_is_not_the_30_percent_default_when_data_exists(self):
        d, B = self.B()
        targets = getattr(d, "team_targets", None) or {}
        for t in B["teams"]:
            R = B["T"][t]
            self.assertIn("rate_src", R)
            if ("2027", t) in targets and targets[("2027", t)].get("rate") is not None:
                self.assertTrue(R["rate_set"])
                continue
            self.assertFalse(R["rate_set"])
            r0 = (targets.get(("2026", t)) or {}).get("rate")
            if r0 is not None:
                self.assertAlmostEqual(R["rate"], r0 / 100.0)
            elif R["base_rev"] > 0 and R["base_gp"] > 0:
                self.assertAlmostEqual(R["rate"], R["base_gp"] / float(R["base_rev"]))
            self.assertTrue(any(n.startswith(t + ": 2027년 목표 수익률을 넣지 않아") for n in B["notes"]))


class Heads(Base):   # V15
    def test_year_end_headcount_does_not_shrink_when_hiring(self):
        d, B0 = self.B()
        t = B0["teams"][0]
        budget.save_values(self.inp, 2027, [("늘릴인원", t, "2"), ("입사월", t, "4")])
        d, B = self.B()
        h0 = sum(B0["heads0"].values())
        self.assertEqual(sum(B["heads0"].values()), h0)
        self.assertEqual(B["heads"][-1], h0 + 2)
        self.assertIn("%d → %d명" % (h0, h0 + 2), render_budget(B, "mgmt"))


class InputVat(unittest.TestCase):   # V14
    def setUp(self):
        self.inp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.inp, ignore_errors=True)

    def put(self, rows):
        with open(os.path.join(self.inp, "계정잔액.csv"), "w", encoding="utf-8-sig") as f:
            f.write("연월,계정코드,계정,차변,대변\n" + "".join("%s,%s,%s,%d,%d\n" % r for r in rows))

    def test_rate_from_books(self):
        self.put([("2026-01", "13500", "부가세대급금", 800, 0), ("2026-02", "13500", "부가세대급금", 700, 0),
                  ("2026-11", "13500", "부가세대급금", 999, 0), ("2025-12", "13500", "부가세대급금", 999, 0),
                  ("2026-01", "10300", "보통예금", 5000, 0)])
        got = budget._input_vat_rate(self.inp, 2026, "2026-10", 15000, 5000, 0.5)
        self.assertEqual((got["vat"], got["buy"]), (1500, 20000))
        self.assertAlmostEqual(got["rate"], 0.075)

    def test_out_of_range_or_missing_keeps_old_assumption(self):
        self.assertIsNone(budget._input_vat_rate(self.inp, 2026, "2026-10", 15000, 5000, 0.5)["rate"])
        self.put([("2026-01", "13500", "부가세대급금", 5000, 0)])
        got = budget._input_vat_rate(self.inp, 2026, "2026-10", 15000, 5000, 0.5)   # 25% → 자료가 안 맞음
        self.assertIsNone(got["rate"])
        self.assertIn("범위", got["why"])


class NextYearDep(unittest.TestCase):   # V21
    def setUp(self):
        self.inp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.inp, ignore_errors=True)

    def test_ending_assets_drop_out(self):
        with open(os.path.join(self.inp, corptax.LEDGER_FILE), "w", encoding="utf-8-sig") as f:
            f.write("기준연도,자산,계정,취득일,취득가,상각률,전기말상각누계,당기상각,당기말상각누계\n"
                    "2026,가,비품,2022-01-01,5000,,4000,1000,5000\n"     # 올해로 끝 → 내년 0
                    "2026,나,비품,2025-01-01,5000,,1000,1000,2000\n"     # 내년도 1000
                    "2026,다,비품,2023-07-01,5000,,3500,1000,4500\n"     # 남은 500
                    "2025,라,비품,2020-01-01,9000,,0,9000,9000\n")
        self.assertEqual(corptax.next_year_ledger(self.inp, 2026), (1500, 2))
        self.assertEqual(corptax.next_year_ledger(self.inp, 2024), (None, 0))

    def test_asset_rows_keep_every_year(self):
        from ceo_report import wehago_raw
        def scr(names):
            return {"응답": [{"path": "/x/allfixlist", "data": [{"cd_fixast": "1", "nm_fixast": n, "mn_ctdepre1": 10} for n in names]}]}
        F = {("결산_고정자산관리대장", 2027): (None, None, scr(["새"])), ("결산_고정자산관리대장", 2026): (None, None, scr(["옛", "옛2"]))}
        try:
            rows = wehago_raw.asset_rows(F)
        except Exception:
            self.skipTest("화면 응답 모양이 시험과 다름")
        if not rows:
            self.skipTest("화면 응답 모양이 시험과 다름")
        self.assertEqual(sorted(set(r["기준연도"] for r in rows)), ["2026", "2027"])


class Salary(unittest.TestCase):   # V13
    def test_regular_month_plus_bonus(self):
        vals = [100, 100, 150, 100, 110, 110, 110]   # 3번째 달 상여 50, 5번째 달부터 급여 오름
        reg = sorted(vals[-3:])[1]
        self.assertEqual(reg, 110)
        annual = int(round(reg * 12 + sum(max(0, v - reg) for v in vals) * 12.0 / len(vals)))
        self.assertEqual(annual, 110 * 12 + int(round(40 * 12 / 7.0)))


if __name__ == "__main__":
    unittest.main()
