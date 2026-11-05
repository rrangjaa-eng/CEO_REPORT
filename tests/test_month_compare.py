"""월간 ⑤ 매출·영업이익 칸의 '지난달 대비 · 작년 같은 달 대비' (사용자 2026-11-05). 합성 자료만 쓴다."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ceo_report import render as rd  # noqa: E402


def tbl(rev, np_):
    return [{"unit": "회사", "target": "회사 전체", "cur": {"revenue": rev, "np": np_, "gp": 0, "provisional": False}, "ytd": None}]


class TestMonthCompare(unittest.TestCase):
    def R(self, prev):
        return {"s4": {"ym": "2026-10", "dept": None}}, {"by_month": [("2026-09", tbl(200, 30)), ("2026-10", tbl(180, 27))],
                                                          "by_month_prev": prev}

    def test_last_month_and_last_year(self):
        R, src = self.R([("2025-10", tbl(100, 40))])
        rev, np_ = rd._month_compare(R, src, tbl(180, 27)[0]["cur"])
        self.assertIn("지난달 대비 −20 (−10.0%)", rev)
        self.assertIn("작년 10월 대비 +80 (+80.0%)", rev)
        self.assertIn("지난달 대비 −3", np_)
        self.assertIn("작년 10월 대비 −13", np_)

    def test_missing_last_year_is_left_out(self):
        R, src = self.R([])
        rev, np_ = rd._month_compare(R, src, tbl(180, 27)[0]["cur"])
        self.assertIn("지난달 대비", rev)
        self.assertNotIn("작년", rev + np_)


if __name__ == "__main__":
    unittest.main()
