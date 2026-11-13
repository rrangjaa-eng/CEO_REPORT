"""가수금 갚을 시기 (사용자 2026-11-13)."""
import datetime as dt
import os
import tempfile
import unittest
from unittest import mock

from ceo_report import gasu

D = dt.date


def _R(events, start=150000000, asof=D(2026, 11, 13)):
    return {"asof": asof, "s2": {"start": start, "min_cash": 100000000, "dated": events, "horizon": D(2027, 5, 31)}}


def _ev(d, io, amt, firm=True, src="자금계획서", desc="거래처"):
    return {"date": d, "io": io, "amount": amt, "firm": firm, "source": src, "desc": desc, "cat": "자금계획서"}


def _books(folder, rows, start=True):
    with open(os.path.join(folder, "계정잔액.csv"), "w", encoding="utf-8-sig") as f:
        f.write("연월,계정코드,계정,차변,대변\n처음부터,,%s,,\n" % ("예" if start else "아니오"))
        for r in rows:
            f.write(",".join(str(x) for x in r) + "\n")


class TestGasu(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        _books(self.t, [("2025-02", "25700", "가수금", 0, 60000000), ("2026-05", "25700", "가수금", 20000000, 0),
                        ("2026-12", "25700", "가수금", 5000000, 0)])
        p = mock.patch("ceo_report.gate.problems", return_value=[])
        p.start(); self.addCleanup(p.stop)
        q = mock.patch("ceo_report.gate.sources_line", return_value="사용한 자료: 시험")
        q.start(); self.addCleanup(q.stop)

    def test_balance_until_asof_month(self):
        self.assertEqual(gasu.balance(self.t, D(2026, 11, 13)), (40000000, ""))

    def test_balance_unknown_when_not_from_start(self):
        _books(self.t, [("2026-05", "25700", "가수금", 0, 1)], start=False)
        v, why = gasu.balance(self.t, D(2026, 11, 13))
        self.assertIsNone(v)
        self.assertIn("처음부터", why)

    def test_wait_until_big_inflow(self):
        # 11/27 6천만 나감(예상) → 잔액 9천만, 12/24 2억 들어옴(확정)
        R = _R([_ev(D(2026, 11, 27), "out", 60000000, firm=False, src="세금예상", desc="급여"),
                _ev(D(2026, 12, 24), "in", 200000000, desc="큰 거래처"), _ev(D(2027, 2, 10), "out", 1, desc="끝")])
        G = gasu.compute(self.t, R)
        self.assertEqual(G["rest"], 40000000)
        self.assertEqual(G["first_all"], D(2026, 12, 24))
        self.assertEqual(G["first_firm"], D(2026, 11, 13))
        c = dict((x["date"], x) for x in G["cases"])
        self.assertFalse(c[D(2026, 11, 13)]["all"]["safe"])
        self.assertEqual(c[D(2026, 11, 13)]["all"]["short"], 50000000)   # 1.5억−0.6억−0.4억 = 0.5억 → 0.5억 부족
        self.assertEqual(c[D(2026, 11, 13)]["all"]["more"], 40000000)
        self.assertTrue(c[D(2026, 11, 13)]["firm"]["safe"])
        self.assertTrue(c[D(2026, 12, 31)]["all"]["safe"])
        a = gasu.advice(G)
        self.assertTrue(a[0].startswith("12/24 이후에 갚으세요"))
        self.assertIn("12/24 무렵 들어올 확정 입금(큰 거래처", a[0])
        h = gasu.render(G)
        self.assertIn("B-2-1 가수금 갚을 시기", h)
        self.assertIn("40,000,000", h)
        self.assertIn("사용한 자료: 시험", h)

    def test_safe_now(self):
        R = _R([_ev(D(2027, 2, 10), "out", 1)], start=300000000)
        G = gasu.compute(self.t, R)
        self.assertEqual(G["first_all"], D(2026, 11, 13))
        self.assertIn("지금 40,000,000원을 전부 갚아도", gasu.advice(G)[0])

    def test_planned_in_fund_plan_is_not_counted_twice(self):
        R = _R([_ev(D(2026, 11, 20), "out", 40000000, desc="대표이사 가수금 상환")], start=300000000)
        G = gasu.compute(self.t, R)
        self.assertEqual(G["rest"], 0)
        self.assertEqual(G["cases"], [])
        self.assertIn("이미 갚을 날", gasu.advice(G)[0])

    def test_blocked_without_fund_plan(self):
        with mock.patch("ceo_report.gate.problems", return_value=["자금계획서 없음"]):
            G = gasu.compute(self.t, _R([]))
        self.assertFalse(G["ok"])
        self.assertIn("자금계획서 없음", gasu.render(G))

    def test_candidates(self):
        c = gasu.candidates(D(2026, 11, 13), D(2027, 2, 28))
        self.assertEqual([d for _, d in c], [D(2026, 11, 13), D(2026, 11, 20), D(2026, 11, 30), D(2026, 12, 31), D(2027, 1, 29)])


if __name__ == "__main__":
    unittest.main()
