"""2차 전수조사 제안 10 (A7): 3년 넘게 벗어난 날짜는 '날짜 의심'. 가상 자료만."""
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

from ceo_report import approval, calc  # noqa: E402
from ceo_report.data import load  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
ASOF = dt.date(2026, 11, 6)
NOW = dt.datetime(2026, 11, 6, 9, 0)


class RequestDay(unittest.TestCase):
    REG = dt.datetime(2026, 9, 17, 1, 14, 58)

    def test_typo_year_is_not_used(self):
        for raw in ("2060.09.18", "2002.06.05"):
            self.assertEqual(approval.request_day({"지급요청일": raw}, self.REG), (None, raw))

    def test_normal_date_and_unknown_registration_are_kept(self):
        self.assertEqual(approval.request_day({"지급요청일": "2026.09.18"}, self.REG), (dt.date(2026, 9, 18), ""))
        self.assertEqual(approval.request_day({"지급요청일": "2027-01-15"}, self.REG), (dt.date(2027, 1, 15), ""))
        self.assertEqual(approval.request_day({"지급요청일": "2060.09.18"}, None), (dt.date(2060, 9, 18), ""))
        self.assertEqual(approval.request_day({"지급요청일": ""}, self.REG), (None, ""))

    def test_expected_date_falls_back_to_the_friday_rule_and_says_why(self):
        rq = {"request_date": None, "date_suspect": "2060.09.18", "status": "approved", "registered": self.REG}
        day, rule = approval._expected_date(rq, ASOF, NOW)
        self.assertEqual(day, dt.date(2026, 9, 18))   # 등록 9/17(목) 01시 → 그날 14시 승인 → 금요일
        self.assertIn("'2060.09.18' 날짜 의심", rule)
        self.assertNotIn("지급요청일 없음", rule)


class FarDateIssue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inp = os.path.join(self.tmp, "입력")
        shutil.copytree(SAMPLE, self.inp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def issues(self):
        return [m for _, _, m in calc.compute(load(self.inp), "weekly", ASOF)["s7"]["issues"] if "날짜 의심" in m]

    def test_sample_has_none(self):
        self.assertEqual(self.issues(), [])

    def test_far_future_schedule_row_is_reported(self):
        p = os.path.join(self.inp, "자금일정.csv")
        with open(p, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
        head = lines[0].split(",")
        row = lines[1].split(",")
        row[head.index("예정일")] = "2060-09-18"
        with open(p, "w", encoding="utf-8-sig") as f:
            f.write("\n".join([lines[0], ",".join(row)] + lines[2:]) + "\n")
        got = self.issues()
        self.assertEqual(len(got), 1)
        self.assertIn("예정일 2060-09-18 날짜 의심", got[0])


class EventDateForms(unittest.TestCase):
    """제안 12 (D2): 자동 분석 7 은 '2026.10.27' 꼴·기간 꼴 행사일도 읽는다 (예전엔 늘 0건)."""

    def R(self, ev):
        return {"asof": ASOF, "s5": {}, "s3": {"projects": [
            {"id": "26231", "name": "가상", "event_date": ev, "recognized": 0, "paid_total": 7_000_000}]}}

    def test_all_forms(self):
        from ceo_report import insights
        for ev in ("2026.10.27", "2026-10-27", "2026.10.25-2026.10.27", "2026/10/27"):
            got = insights.invoice_pairs(self.R(ev))
            self.assertEqual(len(got), 1, ev)
            self.assertIn("행사 2026-10-27 끝", got[0][1])
        self.assertEqual(insights.invoice_pairs(self.R("2026.12.27")), [])
        self.assertEqual(insights.invoice_pairs(self.R("")), [])


if __name__ == "__main__":
    unittest.main()
