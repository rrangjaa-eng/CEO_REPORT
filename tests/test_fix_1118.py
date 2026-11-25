"""11/18 전수 점검 (원래 목적·계획에 어긋난 출력) 고침 시험. 합성 자료만."""
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from ceo_report import annual, credit, digest, insights_more, tax  # noqa: E402

D = dt.date


def ln(day, no, code, debit=None, credit=None, vendor=""):
    return {"date": day, "no": no, "account_code": code, "account": "", "debit": debit, "credit": credit, "vendor": vendor, "memo": ""}


class TestEventDay(unittest.TestCase):
    def test_dotted_and_range_dates_are_read(self):
        # 6달 일감(17)·고객사별 이익(19)이 '2026.11.25' 꼴 행사일을 못 읽어 비던 것
        self.assertEqual(insights_more._day("2026.11.25"), D(2026, 11, 25))
        self.assertEqual(insights_more._day("2026/11/25"), D(2026, 11, 25))
        self.assertEqual(insights_more._day("2026.04.06-2026.04.08"), D(2026, 4, 8))
        self.assertIsNone(insights_more._day(""))


class TestWithholdingPartialMonth(unittest.TestCase):
    J = [ln(D(2026, 1, 9), "1", "25400", debit=50, vendor="역삼세무서"),
         ln(D(2026, 7, 10), "2", "25400", debit=60, vendor="역삼세무서"),
         ln(D(2026, 10, 30), "3", "25400", credit=100, vendor="역삼세무서"),
         ln(D(2026, 11, 5), "4", "25400", credit=10, vendor="역삼세무서")]

    def test_asof_month_is_not_used_as_recent_month(self):
        # 10월은 다 끝난 달(급여 포함 100), 11월은 기준일까지 일부(10)만 → 12월·다음 반기는 10월 100으로 (예전엔 11월 10 × 6 = 60)
        rows = tax.withholding(self.J, D(2026, 11, 18))
        got = dict((r["대상기간"], int(r["금액"])) for r in rows)
        self.assertEqual(got["2026년 하반기 (7~12월)"], 100 + 10 + 100)
        self.assertEqual(got["2027년 상반기 (1~6월)"], 600)
        self.assertIn("2026-10 금액", rows[1]["근거"])

    def test_screen_month_without_wage_gets_recent_wage(self):
        # 위하고 화면에 11·12월 근로(급여) 원천세가 아직 없음 (사업·기타만 30·20) → 근로는 최근 급여 달 70으로 채운다
        rows = tax.withholding(self.J, D(2026, 11, 18), screen={(2026, 11): 30, (2026, 12): 20},
                               wage_gap={(2026, 11): 70, (2026, 12): 70})
        got = dict((r["대상기간"], int(r["금액"])) for r in rows)
        self.assertEqual(got["2026년 하반기 (7~12월)"], 100 + (30 + 70) + (20 + 70))   # 11월은 장부 10에서 100까지 채움
        self.assertIn("근로 70원(최근 급여 달)", rows[0]["근거"])

    def test_screen_value_with_wage_is_used_as_is(self):
        rows = tax.withholding(self.J, D(2026, 11, 18), screen={(2026, 12): 150})
        got = dict((r["대상기간"], int(r["금액"])) for r in rows)
        self.assertEqual(got["2026년 하반기 (7~12월)"], 100 + 10 + 150)   # 받은 자료(화면 값) 먼저


    def test_wage_gap_from_screen(self):
        from ceo_report import screen_tax
        old = screen_tax.income_tax
        screen_tax.income_tax = lambda F: {(2026, 10): {"근로": 70, "사업": 5, "기타": 0}, (2026, 11): {"근로": 0, "사업": 30, "기타": 0},
                                           (2026, 12): {"근로": 0, "사업": 20, "기타": 0}, (2026, 9): {"근로": 60}}
        try:
            self.assertEqual(screen_tax.wage_gap(None, D(2026, 11, 18)), {(2026, 11): 70, (2026, 12): 70})
            self.assertEqual(screen_tax.wage_gap(None, D(2026, 10, 31)), {(2026, 11): 70, (2026, 12): 70})   # 10월은 급여가 있어 채울 달 아님
        finally:
            screen_tax.income_tax = old


class TestTrackLine(unittest.TestCase):
    def c(self, f, a, act):
        return {"firm": f, "all": a, "actual": act}

    def test_uses_latest_month_first(self):
        K = {"months": [{"ym": "2026-10", "in": self.c(0, 100, 50), "out": self.c(0, 100, 100)},
                        {"ym": "2026-09", "in": self.c(0, 100, 200), "out": self.c(0, 100, 100)}]}
        line = digest._track_line(K)
        self.assertTrue(line.startswith("2026-10 한 달"))
        self.assertIn("입금 예측이 실제보다 50% 많음", line)

    def test_falls_back_to_report_weeks(self):
        # 다 끝난 달이 없어도 보고 기록이 있으면 '지난 보고 기록 없음'이 아니라 그 뒤 기간으로 견준다
        K = {"months": [], "weeks": [
            {"made": D(2026, 11, 16), "to": D(2026, 11, 17), "part": True, "in": self.c(0, 0, 0), "out": self.c(0, 10, 12)},
            {"made": D(2026, 10, 31), "to": D(2026, 11, 17), "part": True, "in": self.c(80, 80, 100), "out": self.c(50, 100, 150)}]}
        line = digest._track_line(K)
        self.assertTrue(line.startswith("10/31 보고 → 11/17 (진행 중)"))
        self.assertIn("출금 예측이 실제보다 50% 적음", line)
        self.assertEqual(digest._track_line({"months": [], "weeks": []}), "")


class TestAnnualDepSpread(unittest.TestCase):
    def test_monthly_rows_add_up_to_summary(self):
        P = {"common_m": [10] * 10 + [0, 0], "op_m": [5] * 10 + [0, 0], "common": 100, "op": 50, "dep_pending": 1003,
             "acct": {"급여": 100}}
        V = annual._with_dep(P, 10)
        self.assertEqual(sum(V["common_m"]), V["common"])
        self.assertEqual(sum(V["op_m"]), V["op"])
        self.assertEqual(V["op"], 50 - 1003)
        self.assertEqual(V["acct"]["감가상각비"], 1003)
        self.assertEqual(V["common_m"][10:], [0, 0])
        self.assertEqual(P["op"], 50)   # 원본은 그대로
        self.assertIs(annual._with_dep(dict(P, dep_pending=None), 10)["op"], 50)


class TestCreditGrowthLabel(unittest.TestCase):
    def test_label_follows_source(self):
        f = [x for x in credit.FIN if x[0] == "growth"][0]
        self.assertEqual(credit._how(f, {}), f[3])
        self.assertIn("작년 평가서 매출", credit._how(f, {"growth_src": "작년 평가서 매출 1원 대비 올해 연 환산"}))


class TestDividendAdvise(unittest.TestCase):
    """배당 제안: 한도는 처분계산서 쪽과 같게(앞 해 자본금·이익준비금 이어 씀), '해당' 후보는 '받음'(넣음)만, 같은 이름 세금 줄 구별."""

    def setUp(self):
        from test_dividend import ready, R
        self.ready, self.R = ready, R

    def test_limit_carries_capital_from_last_year(self):
        from ceo_report import dividend as dv
        S = {"year": 2026, "cur": {"미처분": (220_000_000, "예상", "")},
             "years": [(2025, {"미처분": (100_000_000, "확정", ""), "자본금": (20_000_000, "확정", ""), "이익준비금잔액": (0, "확정", "")}),
                       (2026, {"미처분": (220_000_000, "예상", "")})]}
        A = dv.advise(self.R(100_000_000), S, None, self.ready())
        lim = dict((k, v) for k, v in A["facts"])["배당 한도 (이익준비금 적립 몫 뺌)"]
        self.assertEqual(lim, dv.div_limit(220_000_000, 20_000_000, 0))
        self.assertEqual(lim, 210_000_000)   # 예전엔 자본금을 몰라 ÷1.1 = 2억

    def test_only_checked_breaks_are_subtracted_and_rest_row_labelled(self):
        from ceo_report import dividend as dv
        from ceo_report.tax import REST_MARK
        tb = {"total": 5_000_000, "rows": [("중소기업 특별세액감면", "해당", 5_000_000, "", "", "", "안 넣음 · 기본 규칙")]}
        S = {"year": 2026, "cur": {"미처분": (330_000_000, "예상", "")}, "tb": tb}
        tax = [{"kind": "법인세", "due": D(2027, 3, 31), "amount": 20_000_000, "period": "2026년"},
               {"kind": "법인세", "due": D(2027, 3, 31), "amount": 3_000_000, "period": "2026년 12~12월" + REST_MARK}]
        A = dv.advise(self.R(200_000_000, tax=tax), S, {"best": 33_000_000}, self.ready())
        names = [k for k, _ in A["facts"]]
        self.assertFalse([k for k in names if "후보 반영" in k])
        self.assertIn("− 법인세 (2027-03-31)", names)
        self.assertIn("− 법인세 — 2026년 12~12월 남은 기간 예상 (2027-03-31)", names)
        tb2 = {"total": 5_000_000, "rows": [("중소기업 특별세액감면", "해당", 5_000_000, "", "", "", "넣음 · 받음 표시")]}
        A2 = dv.advise(self.R(200_000_000, tax=tax[:1]), dict(S, tb=tb2), {"best": 33_000_000}, self.ready())
        self.assertIn(("− 법인세 (2027-03-31) — '받음' 감면·공제 5,000,000원 뺌", 15_000_000), A2["facts"])


if __name__ == "__main__":
    unittest.main()
