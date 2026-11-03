"""2026-11-03 밤 계산 검토에서 찾은 오류 고침 확인. 합성 자료만."""
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import approval, fundplan, tax, teamprofit  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import month_flow  # noqa: E402

D = dt.date
SAMPLE = os.path.join(ROOT, "입력양식", "샘플")


def ln(day, no, code, debit=None, credit=None, vendor=""):
    return {"date": day, "no": no, "account_code": code, "account": "", "debit": debit, "credit": credit, "vendor": vendor, "memo": ""}


class TestVatIsNotTakenByBudgetSlice(unittest.TestCase):
    """남은 예산 줄의 근거 글('부가세 10%')을 부가세 일정으로 잘못 짝짓지 않는다."""

    def test_budget_slice_does_not_swallow_vat(self):
        slice_ = {"date": D(2027, 1, 22), "io": "out", "amount": 962_500, "firm": False, "cat": "프로젝트 남은 예산",
                  "desc": "G사", "basis": "남은 예산 875,000원 + 부가세 10%", "project": "P1", "source": "남은 예산"}
        vat_row = {"세목": "부가세", "kind": "부가세", "period": "2026년 4분기", "due": D(2027, 1, 25), "amount": 360_000,
                   "state": "예상", "basis": ""}
        out, info = tax.merge([slice_], [vat_row])
        self.assertIsNone(info[0]["matched"])
        self.assertEqual([e["amount"] for e in out if e["source"] == "세금예상"], [360_000])


class TestVatSettlement(unittest.TestCase):
    def test_one_slip_quarter_end_settlement_keeps_the_amount(self):
        j = [ln(D(2026, 8, 5), "1", "25500", credit=100), ln(D(2026, 8, 6), "2", "13500", debit=30),
             ln(D(2026, 9, 30), "8", "25500", debit=100), ln(D(2026, 9, 30), "8", "13500", credit=30),
             ln(D(2026, 9, 30), "8", "26100", credit=70)]
        rows = tax.vat(j, D(2026, 10, 3))
        self.assertEqual([(r["대상기간"], r["금액"], r["상태"]) for r in rows], [("2026년 3분기 (7~9월)", "70", "확정(전표)")])

    def test_accrued_vat_paid_from_bank_before_due_is_not_counted_again(self):
        j = [ln(D(2026, 8, 5), "1", "25500", credit=100), ln(D(2026, 8, 6), "2", "13500", debit=30),
             ln(D(2026, 9, 30), "8", "25500", debit=30), ln(D(2026, 9, 30), "8", "13500", credit=30),
             ln(D(2026, 10, 23), "9", "25500", debit=70), ln(D(2026, 10, 23), "9", "26200", credit=70)]
        q3 = lambda rows: [r for r in rows if r["대상기간"].startswith("2026년 3분기")]
        self.assertEqual([r["상태"] for r in q3(tax.vat(j, D(2026, 10, 25)))], ["확정(전표)"])   # 아직 안 갚음
        j += [ln(D(2026, 10, 24), "10", "26200", debit=70), ln(D(2026, 10, 24), "10", "10300", credit=70)]
        self.assertEqual(q3(tax.vat(j, D(2026, 10, 25))), [])


class TestFundPlanPastDateStillPlanned(unittest.TestCase):
    def test_planned_row_past_by_report_date_moves_to_next_friday(self):
        plan = [{"date": D(2026, 11, 4), "io": "지급", "amount": 30_000_000, "state": "예정", "cat": "", "vendor": "가상업체",
                 "file": "", "stamp": D(2026, 11, 2), "ym": "2026-11"}]
        out, info = fundplan.apply([], plan, D(2026, 11, 5), 7)
        self.assertEqual([(e["date"], e["amount"]) for e in out], [(D(2026, 11, 6), 30_000_000)])
        self.assertEqual(len(info["moved"]), 1)


class TestTeamWithoutCostRowIsUnknown(unittest.TestCase):
    def test_team_missing_from_dept_costs(self):
        cur = lambda rev, gp: {"revenue": rev, "gp": gp, "common": None}
        table = [{"unit": "회사", "target": "회사 전체", "cur": cur(100, 40), "ytd": None},
                 {"unit": "팀", "target": "기획1팀", "cur": cur(60, 30), "ytd": None}]
        dept = [{"ym": "2026-10", "dept": "기획 1팀", "salary": 8, "sga": 2, "heads": 2, "nonop_in": 0, "nonop_out": 0,
                 "has_nonop": True}]
        T = teamprofit.build(table, dept, "2026-10")
        row = [r for r in T["rows"] if r["label"] == "기획1팀"][0]
        self.assertEqual((row["salary"], row["sga"], row["net"]), (None, None, None))


class TestApprovalBudgetNote(unittest.TestCase):
    def test_counts_projects_not_weekly_slices(self):
        sl = [{"project": "P1", "amount": 100}, {"project": "P1", "amount": 100}, {"project": "P2", "amount": 50}]
        note = approval._budget_note(sl)
        self.assertIn("2개 프로젝트", note)
        self.assertIn("250", note)
        self.assertIn("매주 나눠", note)


class TestMonthFlowStartIgnoresUnknownBalanceAccounts(unittest.TestCase):
    def test_unknown_account_flow_is_not_reversed(self):
        R = compute(load(SAMPLE), "monthly", D(2026, 10, 31))
        base = month_flow(R)["start"]
        acc = R["s1"]["accounts"][0]["account"]
        R["s1"]["accounts"] = [dict(a, balance=None) if a["account"] == acc else a for a in R["s1"]["accounts"]]
        moved = sum((t["amount"] if t["io"] == "입금" else -t["amount"]) for t in R["s1"]["txns"]
                    if t["account"] == acc and t["cat"] != "계좌간이체")
        self.assertEqual(month_flow(R)["start"], base + moved)


if __name__ == "__main__":
    unittest.main()
