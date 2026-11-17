"""받은 자료 먼저 (사용자 2026-11-17): 내년 예산 자금표는 자금계획서·계산서에 이미 있는 예산 연도 입금·지급을 그 날짜·금액 그대로 쓰고,
공식(60일, 40%·60%)은 아직 장부에 안 잡힌 매출·매입에만 쓴다."""
import datetime as dt
import unittest
from unittest import mock

from ceo_report import budget


class _D(object):
    def __init__(self):
        self.pl = [{"source": "WEHAGO", "unit": "팀", "ym": "2026-%02d" % m, "target": "기획1팀", "revenue": 100000000, "direct": 70000000}
                   for m in range(1, 12)]
        self.projects = {"P1": {"id": "P1", "name": "12월 행사", "team": "기획1팀", "event_date": "2026.12.10", "estimate": 50000000,
                                "booked": 0, "state": "", "quote": None, "contract": None}}
        self.team_targets = {}
        self.balances = []
        self.invoices = []
        self.tax = []
        self.debts = None


def _w(events):
    return {"events": events, "s2": {"start": 300000000, "dated": [], "horizon": dt.date(2027, 5, 31)}}


class KnownLinesFirst(unittest.TestCase):
    def _run(self, events, raises=False):
        d = _D()
        left = [{"P": d.projects["P1"], "event": dt.date(2026, 12, 10), "left": 50000000, "prior": False}]
        side = RuntimeError("x") if raises else None
        with mock.patch("ceo_report.calc.compute", side_effect=side, return_value=_w(events)), \
                mock.patch.object(budget, "year_revenue_left", return_value=left):
            return budget.compute(d, {}, 2027, dt.date(2026, 11, 17))

    def test_plan_lines_used_and_formula_only_for_unbooked(self):
        ev = [{"date": dt.date(2027, 1, 11), "io": "in", "amount": 88000000, "source": "자금계획서", "cat": "자금계획서 외상대금 회수"},
              {"date": dt.date(2027, 2, 15), "io": "out", "amount": 33000000, "source": "자금계획서", "cat": "자금계획서 미지급금 지급"},
              {"date": dt.date(2027, 1, 20), "io": "out", "amount": 5000000, "source": "남은 예산", "cat": "남은 예산"},
              {"date": dt.date(2026, 12, 24), "io": "in", "amount": 110000000, "source": "자금계획서", "cat": "자금계획서 외상대금 회수"}]
        B = self._run(ev)
        c = B["cash"]
        self.assertTrue(c["known"]["used"])
        self.assertEqual(c["known"]["in"][0], 88000000)      # 연말 전 줄(12/24)과 남은 예산 줄은 넣지 않는다
        self.assertEqual(c["known"]["out"][1], 33000000)
        self.assertEqual((c["known"]["in_n"], c["known"]["out_n"]), (1, 1))
        # 1월 입금 = 자금계획서 8,800만 (11월 장부 매출 1억은 공식으로 다시 넣지 않음). 2월 = 12월 안 잡힌 매출 5,000만 × 1.1
        self.assertEqual(c["cin"][0], 88000000)
        self.assertEqual(c["cin"][1], 55000000)
        self.assertTrue(any("그 날짜·금액 그대로" in n for n in B["notes"]))

    def test_without_schedule_keeps_formula(self):
        B = self._run([], raises=True)
        c = B["cash"]
        self.assertFalse(c["known"]["used"])
        self.assertEqual(c["cin"][0], 110000000)   # 11월 매출 1억 × 1.1 (예전 공식 그대로)


if __name__ == "__main__":
    unittest.main()
