"""기간별 가용자금 (사용자 2026-11-03): 주간은 1~4주, 월간은 1~3개월.

예상 잔액 = 시작 가용액 + 그날까지 입금 예정 − 지급 예정. 기간 중 최저 잔액(날짜 포함)도 함께.
가용자금 = 기간 중 최저 잔액 − 최소 보유현금. 확정분만 / 예상분 포함 두 가지.
"""
import datetime as dt
import unittest

from ceo_report.calc import period_ends, available_periods

D = dt.date


def ev(day, io, amount, firm=True):
    return {"date": day, "io": io, "amount": amount, "firm": firm}


class TestPeriodEnds(unittest.TestCase):
    def test_weekly_four_weeks(self):
        self.assertEqual(period_ends("weekly", D(2026, 10, 31)),
                         [("이번 주", D(2026, 11, 6)), ("다음 주", D(2026, 11, 13)), ("3주째", D(2026, 11, 20)), ("4주째", D(2026, 11, 27))])

    def test_weekly_weeks_end_on_pay_friday(self):
        """주간 기간 = 금요일 출금 주(토~금) (사용자 2026-11-03: 다음 주 지급 예정 목록과 같은 금액). 금요일 기준일이면 그날 지급은 지난 것."""
        self.assertEqual(period_ends("weekly", D(2026, 11, 6))[0], ("다음 주", D(2026, 11, 13)))
        self.assertEqual(period_ends("weekly", D(2026, 11, 2))[0], ("이번 주", D(2026, 11, 6)))

    def test_monthly_three_month_ends(self):
        self.assertEqual(period_ends("monthly", D(2026, 10, 31)),
                         [("11월", D(2026, 11, 30)), ("12월", D(2026, 12, 31)), ("1월", D(2027, 1, 31))])


class TestAvailablePeriods(unittest.TestCase):
    EV = [ev(D(2026, 11, 3), "out", 300), ev(D(2026, 11, 10), "in", 500, firm=False), ev(D(2026, 11, 20), "out", 100)]

    def test_balance_low_and_available_both_modes(self):
        rows = available_periods(1000, self.EV, [("1주", D(2026, 11, 7)), ("3주", D(2026, 11, 21))], 200, D(2026, 10, 31))
        w1, w3 = rows
        self.assertEqual((w1["all"]["in"], w1["all"]["out"], w1["all"]["bal"]), (0, 300, 700))
        self.assertEqual((w1["all"]["low"], w1["all"]["low_date"], w1["all"]["avail"]), (700, D(2026, 11, 3), 500))
        self.assertEqual((w3["all"]["bal"], w3["all"]["low"], w3["all"]["avail"]), (1100, 700, 500))
        self.assertEqual((w3["firm"]["in"], w3["firm"]["bal"], w3["firm"]["low"]), (0, 600, 600))
        self.assertEqual(w3["firm"]["low_date"], D(2026, 11, 20))

    def test_no_events_low_is_start_today(self):
        r = available_periods(1000, [], [("1주", D(2026, 11, 7))], 200, D(2026, 10, 31))[0]["all"]
        self.assertEqual((r["bal"], r["low"], r["low_date"], r["avail"]), (1000, 1000, D(2026, 10, 31), 800))

    def test_unknown_start_or_min_cash_is_none_not_zero(self):
        r = available_periods(None, self.EV, [("1주", D(2026, 11, 7))], 200, D(2026, 10, 31))[0]["all"]
        self.assertIsNone(r["bal"])
        self.assertIsNone(r["avail"])
        r = available_periods(1000, self.EV, [("1주", D(2026, 11, 7))], None, D(2026, 10, 31))[0]["all"]
        self.assertEqual(r["bal"], 700)
        self.assertIsNone(r["avail"])

    def test_same_day_events_net_before_low(self):
        evs = [ev(D(2026, 11, 3), "out", 900), ev(D(2026, 11, 3), "in", 900)]
        r = available_periods(1000, evs, [("1주", D(2026, 11, 7))], 0, D(2026, 10, 31))[0]["all"]
        self.assertEqual(r["low"], 1000)


if __name__ == "__main__":
    unittest.main()
