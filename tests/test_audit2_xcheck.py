"""2차 전수조사 제안 8: 보고끼리 숫자 맞춰 보기. 가상 자료만."""
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

from ceo_report import xcheck  # noqa: E402

D = dt.date(2026, 11, 18)


class Compare(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_same_numbers_no_warning(self):
        self.assertEqual(xcheck.compare(self.out, D, "weekly", {"법인세 낼 돈 (1~10월 이익 기준)": 100}, "t1"), [])
        self.assertEqual(xcheck.compare(self.out, D, "monthly", {"법인세 낼 돈 (1~10월 이익 기준)": 100, "세전 이익 (1~10월)": 5}, "t1"), [])

    def test_difference_is_reported_with_both_values(self):
        xcheck.compare(self.out, D, "weekly", {"법인세 낼 돈 (1~10월 이익 기준)": 13_676_883}, "t1")
        got = xcheck.compare(self.out, D, "monthly", {"법인세 낼 돈 (1~10월 이익 기준)": 16_908_998}, "t1")
        self.assertEqual(got, [("법인세 낼 돈 (1~10월 이익 기준)", 16_908_998, "주간 보고", 13_676_883)])
        text = xcheck.lines(got, "monthly")[0]
        self.assertIn("이 월간 보고 16,908,998원 ↔ 주간 보고 13,676,883원", text)
        self.assertIn("보고끼리 숫자가 다릅니다 (1건)", xcheck.banner(got, "monthly"))
        self.assertEqual(xcheck.banner([], "monthly"), "")

    def test_other_period_other_date_other_conversion_not_compared(self):
        xcheck.compare(self.out, D, "weekly", {"법인세 낼 돈 (1~10월 이익 기준)": 1}, "t1")
        self.assertEqual(xcheck.compare(self.out, D, "monthly", {"법인세 낼 돈 (1~11월 이익 기준)": 2}, "t1"), [])   # 기간이 다른 키
        self.assertEqual(xcheck.compare(self.out, D, "annual", {"법인세 낼 돈 (1~10월 이익 기준)": 2}, "t2"), [])    # 변환이 다름
        self.assertEqual(xcheck.compare(self.out, dt.date(2026, 11, 19), "annual", {"법인세 낼 돈 (1~10월 이익 기준)": 2}, "t1"), [])

    def test_from_budget_and_annual(self):
        B = {"base": 2026, "tax_shared": True, "fix": [{"name": "법인세 (2026년분)", "amount": 10}, {"name": "법인세 분납분 (2026년분)", "amount": 5},
                                                       {"name": "지방소득세 (2026년분)", "amount": 3}, {"name": "법인세 중간예납 (2027년분)", "amount": 9}]}
        self.assertEqual(xcheck.from_budget(B), {"법인세 낼 돈 (2026년 연말 예상)": 15, "지방소득세 낼 돈 (2026년 연말 예상)": 3})
        self.assertEqual(xcheck.from_budget(dict(B, tax_shared=False)), {})
        A = {"Y": {"pre": 100, "net": 80}, "cut": 10, "tax_same": True, "corp": 15, "prepaid": 5, "local": 5, "local_paid": 1}
        self.assertEqual(xcheck.from_annual(A), {"세전 이익 (1~10월)": 100, "순이익 예상 (1~10월)": 80,
                                                 "법인세 낼 돈 (1~10월 이익 기준)": 10, "지방소득세 낼 돈 (1~10월 이익 기준)": 4})


class RealFlow(unittest.TestCase):
    """예시 자료로 주간 → 월간을 만들면 기록이 남고 서로 다르지 않다."""
    def test_weekly_then_monthly(self):
        import subprocess
        from unittest import mock
        import 보고서
        from ceo_report import gate
        tmp = tempfile.mkdtemp()
        try:
            inp, out = os.path.join(tmp, "입력"), os.path.join(tmp, "출력")
            subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_sample.py"), inp], check=True, stdout=subprocess.DEVNULL)
            with mock.patch.dict(os.environ, {gate.TEST_OFF: "1"}):
                for k in ("주간", "월간"):
                    self.assertEqual(보고서.main([k, "--기준일", "2026-10-31", "--입력", inp, "--출력", out, "--pdf", "안함"]), 0)
            S = xcheck._load(out, dt.date(2026, 10, 31))
            self.assertEqual(sorted(S), ["monthly", "weekly"])
            both = set(S["weekly"]["values"]) & set(S["monthly"]["values"])
            self.assertTrue(both)
            for k in both:
                self.assertEqual(S["weekly"]["values"][k], S["monthly"]["values"][k], k)
            with open(os.path.join(out, "2026-10-31_월간_경영관리보고.html"), encoding="utf-8") as f:
                self.assertNotIn("보고끼리 숫자가 다릅니다", f.read())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
