"""월간 2쪽 '월별 매출·영업이익 흐름' 그림 (사용자 2026-11-04: 2쪽 남는 자리에)."""
import unittest
from unittest import mock

from ceo_report import render as rd

def T(rev, np_):
    return [{"unit": "회사", "target": "회사", "cur": {"revenue": rev, "np": np_}, "ytd": None}]

BY_MONTH = [("2025-12", T(9, 9)), ("2026-01", T(300, 50)), ("2026-02", T(100, -40)),
            ("2026-03", T(200, 10)), ("2026-11", T(1, 1))]

def R(dept=None):
    return {"s4": {"ym": "2026-03", "dept": dept,
                   "sources": {"WEHAGO": {"table": T(600, 999), "by_month": BY_MONTH}}}}

class TestMonthChart(unittest.TestCase):
    def test_series_is_this_year_up_to_report_month(self):
        self.assertEqual(rd._month_series(R()), [("2026-01", 300, 50), ("2026-02", 100, -40), ("2026-03", 200, 10)])

    def test_profit_uses_each_months_own_table(self):
        # 부서 비용이 있으면 그 달 표로 팀 표 회사 영업이익을 만든다 (누적 표를 넘기면 달마다 같은 값이 됨)
        def fake(table, dept, ym, ytd):
            return {"company": {"net": table[0]["cur"]["np"] * 2}}
        with mock.patch("ceo_report.teamprofit.build", fake):
            ser = rd._month_series(R(dept=[]))
        self.assertEqual([p for _, _, p in ser], [100, -80, 20])

    def test_chart_marks_loss_month_and_has_legend(self):
        h = rd._month_chart(R())
        self.assertIn("월별 매출·영업이익 흐름 (%s~%s)" % (rd._ym_text("2026-01"), rd._ym_text("2026-03")), h)
        self.assertEqual(h.count("<circle"), 3)
        self.assertEqual(h.count('fill="#b5523b"'), 1)      # 손실 달 점 하나
        self.assertIn("class='legend'", h)
        self.assertNotIn("<polyline", rd._month_chart({"s4": {"ym": "2026-01", "dept": None, "sources": {}}}))

    def test_one_month_no_chart(self):
        r = R()
        r["s4"]["ym"] = "2026-01"
        self.assertEqual(rd._month_chart(r), "")

if __name__ == "__main__":
    unittest.main()
