"""행사일이 지났는데 매출 계산서가 덜 나간 프로젝트 (사용자 2026-11-03: 인트라넷 행사일 기준 미발행을 보고서에).

받을 금액 = 인트라넷 사전견적(공급가액, 사용자 선택). 미발행 = 사전견적 − 발행 공급가액(환불 제외). 행사일이 기준일보다 앞선 것만.
사전견적·행사일·발행금액을 모르면 0으로 치지 않고 '판단 불가'로 센다.
"""
import datetime as dt
import unittest

from ceo_report.calc import event_unissued

ASOF = dt.date(2026, 11, 2)


def P(pid, event, quote):
    return {"id": pid, "name": pid + " 행사", "event_date": event, "estimate": quote}


def X(p, issued):
    return {"P": p, "issued": issued}


class TestEventUnissued(unittest.TestCase):
    def test_past_event_with_remaining_amount_listed_oldest_first(self):
        a, b = P("P1", "2026-10-01", 100_000_000), P("P2", "2026-09-01", 50_000_000)
        r = event_unissued([X(a, 40_000_000), X(b, 0)], ASOF, False)
        self.assertEqual([y["P"]["id"] for y in r["rows"]], ["P2", "P1"])
        self.assertEqual(r["rows"][1]["unissued"], 60_000_000)
        self.assertEqual(r["rows"][0]["days"], (ASOF - dt.date(2026, 9, 1)).days)
        self.assertEqual(r["total"], 110_000_000)

    def test_future_or_today_event_not_listed(self):
        r = event_unissued([X(P("P1", "2026-11-02", 10), 0), X(P("P2", "2026-12-01", 10), 0)], ASOF, False)
        self.assertEqual(r["rows"], [])
        self.assertEqual(r["total"], 0)

    def test_fully_or_over_issued_not_listed(self):
        r = event_unissued([X(P("P1", "2026-10-01", 100), 100), X(P("P2", "2026-10-01", 100), 120)], ASOF, False)
        self.assertEqual(r["rows"], [])

    def test_unknown_inputs_counted_not_zero(self):
        r = event_unissued([X(P("P1", "2026-10-01", None), 0),          # 사전견적 없음
                            X(P("P2", "", 100), 0),                       # 행사일 없음
                            X(P("P3", "2026-10-01", 100), None)], ASOF, False)  # 발행금액 미확인
        self.assertEqual(r["rows"], [])
        self.assertEqual(sorted(u["why"] for u in r["unknown"]), sorted(["사전견적 없음", "발행금액 미확인", "행사일 없음"]))
        self.assertEqual(r["total"], 0)

    def test_no_invoice_source_is_unknown_total(self):
        r = event_unissued([X(P("P1", "2026-10-01", 100), None)], ASOF, True)
        self.assertIsNone(r["total"])
        self.assertTrue(r["missing"])


if __name__ == "__main__":
    unittest.main()


class TestEventUnissuedRender(unittest.TestCase):
    def test_section5_lists_rows_total_and_unknown_reasons(self):
        from ceo_report import render as rd
        p = {"id": "P1", "name": "가 행사", "event_date": "2026-10-01", "estimate": 100_000_000}
        q = {"id": "P2", "name": "나 행사", "event_date": "", "estimate": 10}
        s5 = {"event_unissued": event_unissued([X(p, 30_000_000), X(q, 0)], ASOF, False)}
        html = rd._event_unissued_table(s5)
        self.assertIn("행사 끝난 뒤 계산서 미발행 (1건)", html)
        self.assertIn("70,000,000", html)
        self.assertIn("2026-10-01", html)
        self.assertIn("판단 불가 1건 (행사일 없음 1건)", html)

    def test_section5_no_invoice_source(self):
        from ceo_report import render as rd
        s5 = {"event_unissued": event_unissued([X(P("P1", "2026-10-01", 1), None)], ASOF, True)}
        self.assertIn("자료 없음", rd._event_unissued_table(s5))
