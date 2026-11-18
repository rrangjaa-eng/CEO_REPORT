"""2차 전수조사 제안 9 (J1): 월간 '향후 자금 전망' 표는 줄마다 그 달 안에서 가장 적을 때. 가상 자료만."""
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import calc, render  # noqa: E402
from ceo_report.data import load  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
ASOF = dt.date(2026, 11, 6)


class PeriodLowest(unittest.TestCase):
    def R(self, kind):
        return calc.compute(load(SAMPLE), kind, ASOF)

    def test_period_low_is_within_the_period(self):
        for kind in ("weekly", "monthly"):
            R = self.R(kind)
            mc = R["s2"].get("min_cash")
            prev_end = None
            for p in R["s2"]["periods"]:
                for k in ("firm", "all"):
                    r = p[k]
                    if r.get("plow") is None:
                        continue
                    # 그 기간 안에서 본 값은 오늘부터 본 값(low)보다 작을 수 없다
                    self.assertGreaterEqual(r["plow"], r["low"])
                    self.assertLessEqual(r["plow"], r["bal"] if r["plow_date"] == p["end"] else max(r["plow"], r["bal"]))
                    self.assertLessEqual(r["plow_date"], p["end"])
                    if prev_end:
                        self.assertGreaterEqual(r["plow_date"], prev_end)
                    if mc is not None:
                        self.assertEqual(r["pavail"], r["plow"] - mc)
                prev_end = p["end"]
            # 첫 기간은 오늘부터라 두 값이 같다
            f = R["s2"]["periods"][0]["firm"]
            if f.get("plow") is not None:
                self.assertEqual(f["plow"], f["low"])

    def test_monthly_table_uses_period_value_and_weekly_keeps_running_value(self):
        R = self.R("monthly")
        h = render._avail_table(R, "mgmt")
        self.assertIn("그 달 가장 적을 때 잔액", h)
        self.assertIn("잔액이 가장 적은 날", h)
        W = self.R("weekly")
        hw = render._avail_table(W, "mgmt")
        self.assertIn("오늘부터 가장 적을 때 잔액", hw)
        self.assertNotIn("그 달 가장 적을 때", hw)

    def test_glossary_matches(self):
        self.assertIn("그 달 안에서", render._glossary({"kind": "monthly"}))
        self.assertNotIn("그 달 안에서", render._glossary({"kind": "weekly"}))


if __name__ == "__main__":
    unittest.main()
