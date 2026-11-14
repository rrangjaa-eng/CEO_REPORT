"""2026-11-14 코덱스 전체 검토에서 확인한 오류를 다시 생기지 않게 막는 시험."""
import datetime as dt
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import gate  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
D = dt.date
ON = {gate.TEST_OFF: ""}


class TestGate(unittest.TestCase):
    @mock.patch.dict(os.environ, ON)
    def test_setting_cannot_stretch_beyond_7_days(self):
        R = {"asof": D(2026, 11, 14), "settings_num": {"위험_자료경과일": 30},
             "fundplan": {"used": True, "stamp": D(2026, 11, 13)}, "auto_facts": {"book_date": "2026-11-01"}}
        self.assertTrue(gate.problems(R))
        R["settings_num"]["위험_자료경과일"] = 3
        R["auto_facts"]["book_date"] = "2026-11-10"
        self.assertTrue(gate.problems(R))   # 더 짧게는 쓸 수 있다

    @mock.patch.dict(os.environ, ON)
    def test_blocked_mgmt_and_live_numbers_are_blank(self):
        R = compute(load(SAMPLE), "weekly", D(2026, 11, 6))   # 예시 자료엔 자금계획서가 없다
        self.assertIsNotNone(R["s2"]["periods"][-1]["firm"]["avail"])
        self.assertTrue(gate.blank_funds(R))
        self.assertIsNone(R["s1"]["total"])
        self.assertIsNone(R["s2"]["start"])
        for p in R["s2"]["periods"]:
            self.assertIsNone(p["firm"]["avail"])
            self.assertIsNone(p["all"]["bal"])
        from ceo_report.render import render
        page = render(R, "mgmt")
        self.assertIn("비웠습니다", page)

    @mock.patch.dict(os.environ, ON)
    def test_live_page_blank(self):
        from ceo_report import live
        with tempfile.TemporaryDirectory() as out:
            path, _ = live.build(SAMPLE, out, D(2026, 11, 6))
            with open(path, encoding="utf-8") as f:
                page = f.read()
            self.assertIn("비웠습니다", page)

    def test_evidence_keeps_warning(self):
        from ceo_report import evidence
        mg = ("<html><head><title>x 경영관리 보고</title></head><body>" + gate.banner(["자금계획서 없음"])
              + "<table><tr><td><b>근거 2-1</b></td><td>일정</td><td><a href='#s2'>보기</a></td></tr></table>"
              + "<h2 id='s2'>2. 일정</h2><p>표</p><h2 id='s3'>3</h2></body></html>")
        page = evidence.build(mg, ["2-1"])
        self.assertIn("class='gate'", page)

    def test_latest_report_does_not_open_old_pdf_when_blocked(self):
        from ceo_report import winstate
        with tempfile.TemporaryDirectory() as out:
            base = os.path.join(out, "2026-11-14_주간")
            open(base + "_대표보고 (11-13 10시00분 만듦).pdf", "w").close()
            with open(base + "_대표보고.html", "w", encoding="utf-8") as f:
                f.write(gate.stop_page("주간 대표보고", ["자금계획서 없음"]))
            got = winstate.latest_reports(out)
            self.assertTrue(got["대표"].endswith(".html"))

    def test_default_min_cash_is_100m(self):
        from ceo_report.data import DEFAULT_SETTINGS
        self.assertEqual(DEFAULT_SETTINGS["위험_최소보유현금"], "100000000")


if __name__ == "__main__":
    unittest.main()
