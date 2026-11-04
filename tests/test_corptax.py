"""법인세 예상 (사용자 2026-11-04). 합성 숫자만 쓴다."""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from ceo_report import corptax  # noqa: E402


class TestRates(unittest.TestCase):
    def test_2026_brackets_10_20(self):
        self.assertEqual(corptax.corp_tax(100_000_000, "2026"), 10_000_000)
        self.assertEqual(corptax.corp_tax(300_000_000, "2026"), 20_000_000 + 20_000_000)
        self.assertEqual(corptax.corp_tax(300_000_000, "2025"), 18_000_000 + 19_000_000)
        self.assertEqual(corptax.corp_tax(-5, "2026"), 0)
        self.assertIsNone(corptax.corp_tax(None, "2026"))


class TestDepreciation(unittest.TestCase):
    acc = [{"ym": "2025-12", "name": "감가상각비(판)", "amount": 12_000_000},
           {"ym": "2026-03", "name": "복리후생비(판)", "amount": 5}]

    def test_last_year_prorated(self):
        d = corptax.depreciation(self.acc, {}, "2026-10")
        self.assertEqual((d["annual"], d["extra"], d["source"]), (12_000_000, 10_000_000, "작년 장부"))

    def test_manual_wins_and_booked_not_double_counted(self):
        acc = self.acc + [{"ym": "2026-06", "name": "감가상각비(판)", "amount": 4_000_000}]
        d = corptax.depreciation(acc, {"2026": 24_000_000}, "2026-10")
        self.assertEqual((d["annual"], d["booked"], d["extra"], d["source"]), (24_000_000, 4_000_000, 16_000_000, "직접 입력"))

    def test_unknown(self):
        self.assertIsNone(corptax.depreciation([], {}, "2026-10")["extra"])


class TestEstimate(unittest.TestCase):
    def test_two_rows_without_and_with_nonop_income(self):
        dep = {"extra": 10_000_000}
        a, b = corptax.estimate(147_000_000, 20_000_000, dep, "2026-10")
        self.assertEqual((a["base"], a["corp"], a["local"], a["total"]), (117_000_000, 11_700_000, 1_170_000, 12_870_000))
        self.assertEqual((b["base"], b["total"]), (137_000_000, 15_070_000))


class TestSave(unittest.TestCase):
    def test_save_read_and_clear(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        corptax.save(tmp, "2026", "24,000,000")
        self.assertEqual(corptax.read(tmp), {"2026": 24_000_000})
        corptax.save(tmp, "2026", "")
        self.assertEqual(corptax.read(tmp), {})
        with self.assertRaises(ValueError):
            corptax.save(tmp, "26", "1")


class TestReport(unittest.TestCase):
    def test_monthly_shows_both_estimates_in_both_editions(self):
        from ceo_report.calc import compute
        from ceo_report.data import load
        from ceo_report.render import render
        R = compute(load(os.path.join(os.path.dirname(HERE), "입력양식", "샘플")), "monthly", dt.date(2026, 10, 31))
        for ed in ("ceo", "mgmt"):
            h = render(R, ed)
            self.assertIn("법인세 예상 (1월~10월 누적 기준)", h)
            self.assertIn("12,870,000", h)
            self.assertIn("15,070,000", h)
            self.assertIn("감가상각비 10,000,000 미리 뺌", h)


if __name__ == "__main__":
    unittest.main()
