"""금요일 출금 목록 상세 내역 (사용자 2026-11-03)."""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import paydetail  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import render  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")


def ev(desc, amount):
    return {"io": "out", "desc": desc, "amount": amount}


class TestAttach(unittest.TestCase):
    def test_same_vendor_and_amount_only(self):
        es = [ev("(주)전시제작사", 100), ev("전시제작사", 200), ev("다른곳", 100), ev("전시제작사", None)]
        n = paydetail.attach(es, [{"vendor": "전시 제작사", "amount": 100, "text": "부스", "source": "수기"}])
        self.assertEqual(n, 1)
        self.assertEqual(es[0]["detail"], "부스")
        self.assertTrue(all("detail" not in e for e in es[1:]))

    def test_manual_wins_over_intranet(self):
        es = [ev("가", 5)]
        paydetail.attach(es, [{"vendor": "가", "amount": 5, "text": "결의서", "source": "지출결의서"},
                              {"vendor": "가", "amount": 5, "text": "손으로", "source": "수기"}])
        self.assertEqual(es[0]["detail"], "손으로")


class TestSave(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_save_replace_and_delete(self):
        paydetail.save(self.dir, "가", "1,000", "처음")
        paydetail.save(self.dir, "가", "1000", "고침")
        self.assertEqual([r["text"] for r in paydetail.read(self.dir)], ["고침"])
        self.assertEqual(paydetail.save(self.dir, "가", "1000", ""), 0)

    def test_bad_input(self):
        for v, a in (("", "1000"), ("가", "abc"), ("가", "0")):
            with self.assertRaises(ValueError):
                paydetail.save(self.dir, v, a, "x")


class TestFridayList(unittest.TestCase):
    def test_detail_shows_under_vendor(self):
        html = render(compute(load(SAMPLE), "weekly", dt.date(2026, 10, 31)), "ceo")
        self.assertIn("<b class='vn'>전시제작사</b><small class='dt'>C사 전시 부스 목공·도장 잔금</small>", html)
        self.assertIn("상세 미입력", html)


if __name__ == "__main__":
    unittest.main()
