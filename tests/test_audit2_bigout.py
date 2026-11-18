"""2차 전수조사 제안 7 (A6): 창 '배당'에 넣은 큰 지출을 자금 일정의 예상 줄로. 가상 자료만."""
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

from ceo_report import calc, dividend  # noqa: E402
from ceo_report.data import load  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
ASOF = dt.date(2026, 11, 6)


class BigOutflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inp = os.path.join(self.tmp, "입력")
        shutil.copytree(SAMPLE, self.inp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, rows):
        with open(os.path.join(self.inp, dividend.SET_FILE), "w", encoding="utf-8-sig") as f:
            f.write("항목,값\n" + "".join("%s,%s\n" % r for r in rows))

    def R(self):
        return calc.compute(load(self.inp), "weekly", ASOF)

    def test_none_without_setting(self):
        self.assertIsNone(self.R()["big_outflow"])

    def test_expected_line_not_in_firm_available(self):
        before = self.R()
        self.put([("큰지출", "있음"), ("큰지출금액", "100000000"), ("큰지출시기", "2026-11-25")])
        after = self.R()
        self.assertEqual(after["big_outflow"], {"amount": 100_000_000, "date": dt.date(2026, 11, 25)})
        # 여유 자금 큰 숫자(확정·정기 지출)는 그대로, 예상까지 넣은 전망만 그 날짜 뒤로 1억 줄어든다
        for b, a in zip(before["s2"]["periods"], after["s2"]["periods"]):
            self.assertEqual(b["firm"]["avail"], a["firm"]["avail"])
            self.assertEqual(b["all"]["bal"] - a["all"]["bal"], 100_000_000 if a["end"] >= dt.date(2026, 11, 25) else 0)
        self.assertEqual(before["s2"]["periods"][-1]["all"]["bal"] - after["s2"]["periods"][-1]["all"]["bal"], 100_000_000)

    def test_past_or_undated_is_not_scheduled(self):
        self.put([("큰지출", "있음"), ("큰지출금액", "100000000"), ("큰지출시기", "2026-10-01")])
        self.assertEqual(self.R()["big_outflow"]["skipped"], "시기가 지남")
        self.put([("큰지출", "있음"), ("큰지출금액", "100000000")])
        self.assertEqual(self.R()["big_outflow"]["skipped"], "시기를 모름")


if __name__ == "__main__":
    unittest.main()
