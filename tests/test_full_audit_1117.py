"""11/17 전수 점검에서 찾은 것 (F1·F4·F5·F6·F7·F9·F10·F11·Y1) — 다시 생기면 실패."""
import datetime as dt
import unittest

from ceo_report import annual, calc, mgmt_topics, surplus, taxbreak, teamprofit, teamreport
from ceo_report.convert_pl import build_accounts


def dept(ym, d, salary, sga, heads):
    return {"ym": ym, "dept": d, "salary": salary, "sga": sga, "heads": heads, "nonop_in": 0, "nonop_out": 0, "has_nonop": True}


class F1MidMonthHeads(unittest.TestCase):
    ROWS = [dept("2026-09", "기획1팀", 10_000_000, 1, 3), dept("2026-10", "기획1팀", 10_000_000, 1, 3),
            dept("2026-11", "기획1팀", 0, 5, None)]

    def test_paid_months_skip_month_without_salary(self):
        self.assertEqual(teamprofit.paid_months(self.ROWS), {"2026-09", "2026-10"})

    def test_this_month_uses_last_month_heads(self):
        c = teamprofit._dept_costs(self.ROWS, ["2026-11"])
        self.assertEqual(c["기획1팀"]["heads"], 3)
        self.assertEqual(c["기획1팀"]["heads_from"], "2026-10")

    def test_ytd_average_only_paid_months(self):
        c = teamprofit._dept_costs(self.ROWS, ["2026-09", "2026-10", "2026-11"])
        self.assertEqual(c["기획1팀"]["heads"], 3.0)   # 예전엔 6/3 = 2.0


class F11NoPayInTeamLeader(unittest.TestCase):
    def test_pay_like_accounts(self):
        for nm in ("퇴직급여", "퇴직연금", "상여금", "임원급여"):
            self.assertTrue(teamreport._is_pay_account(nm), nm)
        for nm in ("복리후생비_야근", "여비교통비_택시", "운반비_행사"):
            self.assertFalse(teamreport._is_pay_account(nm), nm)


class F7TargetRate(unittest.TestCase):
    def test_half_percent_kept(self):
        self.assertEqual(annual._tpct(0.285), "28.5%")
        self.assertEqual(annual._tpct(0.28), "28%")


class F9CrossCheckWithDiffs(unittest.TestCase):
    def test_diff_is_not_no_data(self):
        self.assertFalse(mgmt_topics._is_na({"key": "xchk", "num": "차이 2건"}))
        self.assertTrue(mgmt_topics._is_na({"key": "xchk", "num": "자료 없음"}))
        self.assertFalse(mgmt_topics._is_na({"key": "xchk", "num": "대조함"}))


class F10NonOpIncome(unittest.TestCase):
    def test_interest_in_accounts_and_not_in_cost_table(self):
        class B:
            journal = [{"date": dt.date(2026, 3, 31), "account_code": "90100", "account": "이자수익", "debit": None, "credit": 120_000}]
        cfg = {"nonop_out_codes": ["95100"], "nonop_in_codes": ["90100"], "direct_prefixes": ["5"], "common_prefixes": ["8"],
               "direct_mark": "", "revenue_codes": ["40100"]}
        T = build_accounts(B, cfg)
        rows = [r for r in T.rows if r["구분"] == "영업외수익"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0]["금액"]), 120_000)   # 대변 − 차변
        A = calc.account_year([{"ym": "2026-03", "group": "영업외수익", "code": "90100", "name": "이자수익", "amount": 120_000}], "2026-03")
        self.assertEqual(A["groups"], [])   # 비용 표엔 안 들어감


class F5PassengerCar(unittest.TestCase):
    def test_vehicle_not_counted_as_equipment(self):
        j = [{"date": dt.date(2025, 5, 1), "account_code": "20800", "account": "차량운반구", "debit": 123_644_603},
             {"date": dt.date(2025, 6, 1), "account_code": "21200", "account": "비품", "debit": 3_000_000},
             {"date": dt.date(2025, 7, 1), "account_code": "20900", "account": "감가상각누계액", "debit": 500_000}]
        self.assertEqual(taxbreak.assets_by_year(j)[2025][0], 3_000_000)


class F6TeamNone(unittest.TestCase):
    def test_unassigned_row(self):
        rows = [{"단위": "팀", "대상": "기획1팀", "연월": "2025-03", "매출": "100", "직접비": "50"},
                {"단위": "팀", "대상": "팀 미지정", "연월": "2025-03", "매출": "40", "직접비": "10"},
                {"단위": "팀", "대상": "팀 미지정", "연월": "2026-03", "매출": "0", "직접비": "5"}]
        T = annual._team_none(rows, "2026", "2025", 10)
        self.assertEqual((T["rev"], T["gp"], T["lrev"]), (0, -5, 40))
        self.assertIsNone(annual._team_none(rows[:1], "2026", "2025", 10))


class Y1UnclosedLastYear(unittest.TestCase):
    def test_two_estimates_chain(self):
        S = surplus.statements({}, 2025, [(2025, 100, "작년 예상"), (2026, 50, "올해 예상")])
        y25, y26 = S
        self.assertEqual((y25["상태"], y25["당기순이익"]), ("예상", 100))
        self.assertEqual(y26["전기이월"], 100)
        self.assertEqual(y26["미처분"], 150)
        self.assertEqual(y26.get("전기이월상태"), "예상")   # 앞 해가 예상이면 이월도 '확정'이라 하지 않음


if __name__ == "__main__":
    unittest.main()


class RemainingFixes(unittest.TestCase):
    def test_vendor_alias_match(self):
        from ceo_report import wehago
        known = {"한진기획", "레지스토", "에이치에스지알(HSGR)", "브라더코(BROTHERCO)", "메이"}
        idx = {}
        for k in known:
            for a in wehago._vendor_aliases(k):
                idx.setdefault(a, set()).add(k)
        self.assertEqual(wehago._resolve_vendor("한진기획(메이)", known, idx), "한진기획")   # 괄호 앞 이름 먼저
        self.assertEqual(wehago._resolve_vendor("레지스토_김정운", known, idx), "레지스토")
        self.assertEqual(wehago._resolve_vendor("HSGR(언니네와인샵)", known, idx), "에이치에스지알(HSGR)")
        self.assertEqual(wehago._resolve_vendor("브라더코", known, idx), "브라더코(BROTHERCO)")
        self.assertEqual(wehago._resolve_vendor("디자이너_최은지", known, idx), "디자이너_최은지")   # 못 찾으면 그대로

    def test_holidays_through_2030(self):
        from ceo_report import tax
        for y in (2028, 2029, 2030):
            self.assertIn(y, tax.HOLIDAY_YEARS)
        self.assertIn(dt.date(2028, 10, 5), tax.KR_HOLIDAYS)   # 추석·개천절 겹침 대체공휴일
