"""월간 2쪽 '월별 매출·매입·영업이익 흐름' 그림 (사용자 2026-11-04: 2쪽 남는 자리에, 매출·매입은 증빙 작성일자 기준)."""
import datetime as dt
import unittest
from types import SimpleNamespace
from unittest import mock

from ceo_report import convert, render as rd


def T(rev, np_):
    return [{"unit": "회사", "target": "회사", "cur": {"revenue": rev, "direct": rev // 2, "np": np_}, "ytd": None}]


BY_MONTH = [("2025-12", T(9, 9)), ("2026-01", T(300, 50)), ("2026-02", T(100, -40)),
            ("2026-03", T(200, 10)), ("2026-11", T(1, 1))]
EV = {"2025-12": (1, 1), "2026-01": (310, 120), "2026-02": (90, 70), "2026-03": (220, 0), "2026-04": (5, 5)}


def R(dept=None, ev=EV):
    return {"evid_month": ev, "s4": {"ym": "2026-03", "dept": dept,
                                     "sources": {"WEHAGO": {"table": T(600, 999), "by_month": BY_MONTH}}}}


class TestMonthChart(unittest.TestCase):
    def test_bars_use_evidence_months_profit_uses_pl(self):
        self.assertEqual(rd._month_series(R()),
                         [("2026-01", 310, 120, 50), ("2026-02", 90, 70, -40), ("2026-03", 220, 0, 10)])

    def test_without_evidence_file_sales_from_pl_and_no_buys(self):
        self.assertEqual(rd._month_series(R(ev=None)),
                         [("2026-01", 300, None, 50), ("2026-02", 100, None, -40), ("2026-03", 200, None, 10)])
        h = rd._month_chart(R(ev=None))
        self.assertIn("매출 (손익 기준)", h)
        self.assertEqual(h.count('fill="#d8964a"'), 0)      # 매입 막대 없음

    def test_profit_uses_each_months_own_table(self):
        # 부서 비용이 있으면 그 달 표로 팀 표 회사 영업이익을 만든다 (누적 표를 넘기면 달마다 같은 값이 됨)
        def fake(table, dept, ym, ytd):
            return {"company": {"net": table[0]["cur"]["np"] * 2}}
        with mock.patch("ceo_report.teamprofit.build", fake):
            ser = rd._month_series(R(dept=[]))
        self.assertEqual([p for _, _, _, p in ser], [100, -80, 20])

    def test_chart_marks_loss_month_and_has_legend(self):
        h = rd._month_chart(R())
        self.assertIn("월별 매출·매입·영업이익 흐름 (%s~%s)" % (rd._ym_text("2026-01"), rd._ym_text("2026-03")), h)
        self.assertEqual(h.count("<circle"), 3)
        self.assertEqual(h.count('fill="#b5523b"'), 1)      # 손실 달 점 하나
        self.assertIn("class='legend'", h)
        self.assertEqual(h.count('fill="#d8964a"'), 2)      # 매입 0인 3월은 막대 없음
        self.assertIn("증빙 작성일자 기준", h)
        self.assertNotIn("<polyline", rd._month_chart({"s4": {"ym": "2026-01", "dept": None, "sources": {}}}))

    def test_one_month_no_chart(self):
        r = R()
        r["s4"]["ym"] = "2026-01"
        self.assertEqual(rd._month_chart(r), "")


class TestBuildEvidence(unittest.TestCase):
    def test_monthly_supply_sums_and_keeps_old_months(self):
        d = dt.date
        sales = {"state": "ok", "source": "분개장 매출전표",
                 "rows": [{"date": d(2026, 1, 5), "supply": 100}, {"date": d(2026, 1, 20), "supply": -10},
                          {"date": d(2026, 2, 1), "supply": 50}]}
        books = SimpleNamespace(state="ok", from_journal=True,
                                ledger=[{"date": d(2026, 1, 9), "supply": 30}, {"date": d(2026, 2, 3), "supply": None}])
        t = convert.build_evidence(books, sales, [{"연월": "2025-12", "매출": "7", "매입": "8"},
                                                  {"연월": "2026-01", "매출": "1", "매입": "1"}])
        self.assertEqual([(r["연월"], r["매출"], r["매입"]) for r in t.rows],
                         [("2025-12", "7", "8"), ("2026-01", "90", "30"), ("2026-02", "50", "")])

    def test_no_sources_keeps_old_file(self):
        t = convert.build_evidence(SimpleNamespace(state="자료 없음", ledger=[]), {"state": "자료 없음"})
        self.assertFalse(t.written)


if __name__ == "__main__":
    unittest.main()
