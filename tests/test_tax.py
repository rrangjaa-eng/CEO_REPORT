"""세금 납부 예상 (사용자 2026-11-03): 분개장 부가세예수금·부가세대급금·예수금으로 부가세(분기)·원천세 납부액. 합성 자료만."""
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from ceo_report import tax  # noqa: E402

D = dt.date


def ln(day, no, code, debit=None, credit=None, vendor=""):
    return {"date": day, "no": no, "account_code": code, "account": "", "debit": debit, "credit": credit, "vendor": vendor}


class TestVat(unittest.TestCase):
    def journal(self):
        return [
            # 3분기: 매출세액 100, 매입세액 30, 분기말 상계(예수금 차변 30 / 대급금 대변 30), 10/23 미지급 계상 70
            ln(D(2026, 8, 5), "1", "25500", credit=100), ln(D(2026, 8, 6), "2", "13500", debit=30),
            ln(D(2026, 9, 30), "8", "25500", debit=30), ln(D(2026, 9, 30), "8", "13500", credit=30),
            ln(D(2026, 10, 23), "9", "25500", debit=70), ln(D(2026, 10, 23), "9", "26200", credit=70),
            # 4분기 (진행 중): 매출세액 500 − 매입세액 120 − 매출 취소 20 (매출 계정과 같은 전표)
            ln(D(2026, 10, 10), "3", "25500", credit=500), ln(D(2026, 10, 20), "4", "13500", debit=120),
            ln(D(2026, 11, 2), "5", "25500", debit=20), ln(D(2026, 11, 2), "5", "41200", debit=200),
        ]

    def test_open_quarter_estimate_excludes_previous_quarter_payment(self):
        rows = tax.vat(self.journal(), D(2026, 11, 3))
        self.assertEqual([(r["대상기간"], r["납부예정일"], r["금액"], r["상태"]) for r in rows],
                         [("2026년 4분기 (10~12월)", "2027-01-25", "360", "예상")])
        self.assertIn("2026-11-02까지", rows[0]["근거"])

    def test_estimate_before_payment_equals_payment_slip(self):
        before = tax.vat([x for x in self.journal() if x["date"] <= D(2026, 9, 30)], D(2026, 10, 3))
        self.assertEqual((before[0]["금액"], before[0]["상태"]), ("70", "예상"))
        after = tax.vat(self.journal(), D(2026, 10, 3))
        self.assertEqual((after[0]["대상기간"], after[0]["납부예정일"], after[0]["금액"], after[0]["상태"]),
                         ("2026년 3분기 (7~9월)", "2026-10-26", "70", "확정(전표)"))   # 10/25 일요일 → 월요일


class TestWithholding(unittest.TestCase):
    def test_half_year_payer_accumulates_to_january(self):
        j = [ln(D(2026, 1, 9), "1", "25400", debit=50, vendor="역삼세무서"),
             ln(D(2026, 7, 10), "2", "25400", debit=60, vendor="역삼세무서"),
             ln(D(2026, 8, 25), "3", "25400", credit=10, vendor="역삼세무서"),
             ln(D(2026, 8, 25), "3", "25400", credit=1, vendor="강남구청"),
             ln(D(2026, 9, 25), "4", "25400", credit=10, vendor="역삼세무서"),
             ln(D(2026, 9, 25), "4", "25400", credit=7, vendor="건강보험공단")]   # 4대보험은 넣지 않음
        rows = tax.withholding(j, D(2026, 11, 3))
        self.assertEqual([(r["대상기간"], r["납부예정일"], r["금액"]) for r in rows], [("2026년 하반기 (7~12월)", "2027-01-11", "21")])

    def test_monthly_payer_due_next_month_tenth(self):
        j = [ln(D(2026, 9, 10), "1", "25400", debit=5, vendor="역삼세무서"),
             ln(D(2026, 10, 25), "2", "25400", credit=8, vendor="역삼세무서")]
        rows = tax.withholding(j, D(2026, 11, 3))
        self.assertEqual([(r["대상기간"], r["납부예정일"], r["금액"]) for r in rows], [("2026년 10월분", "2026-11-10", "8")])


class TestMerge(unittest.TestCase):
    T = {"kind": "부가세", "period": "2026년 4분기", "due": D(2027, 1, 25), "amount": 360, "state": "예상", "basis": ""}

    def test_estimate_added_when_plan_has_no_tax(self):
        events, info = tax.merge([], [self.T])
        self.assertEqual([(e["date"], e["amount"], e["firm"], e["source"]) for e in events], [(D(2027, 1, 25), 360, False, "세금예상")])
        self.assertIsNone(info[0]["matched"])

    def test_plan_entry_wins_and_difference_is_shown(self):
        plan = {"date": D(2027, 1, 25), "io": "out", "amount": 400, "firm": True, "cat": "", "desc": "역삼세무서", "basis": ""}
        events, info = tax.merge([plan], [self.T])
        self.assertEqual(events, [plan])   # 두 번 빼지 않음
        self.assertEqual(info[0]["diff"], 40)


class TestPaidBeforeDueIsNotCountedTwice(unittest.TestCase):
    """이미 통장에서 나간 세금은 납부일 전이라도 예상에 다시 넣지 않는다 (사용자 2026-11-03: 계산 오류 없게)."""

    def test_vat_paid_from_bank_before_due_is_dropped(self):
        j = TestVat().journal()
        j = [x for x in j if x["no"] != "9"] + [ln(D(2026, 10, 20), "9", "25500", debit=70), ln(D(2026, 10, 20), "9", "10300", credit=70)]
        rows = tax.vat(j, D(2026, 10, 21))
        self.assertNotIn("2026년 3분기 (7~9월)", [r["대상기간"] for r in rows])
        # 미지급비용으로 잡은 것은 아직 안 나간 것: 확정 금액으로 남는다
        self.assertEqual(tax.vat(TestVat().journal(), D(2026, 10, 24))[0]["상태"], "확정(전표)")

    def test_withholding_paid_early_is_dropped(self):
        j = [ln(D(2026, 1, 9), "1", "25400", debit=50, vendor="역삼세무서"),
             ln(D(2026, 8, 25), "3", "25400", credit=10, vendor="역삼세무서"),
             ln(D(2027, 1, 8), "9", "25400", debit=10, vendor="역삼세무서")]
        self.assertEqual(tax.withholding(j, D(2027, 1, 9)), [])


class TestSocialInsurance(unittest.TestCase):
    """4대보험: 전달 급여에서 뗀 직원분(예수금, 공단 거래처) + 회사 부담분을 다음 달 10일에 낸다. 회사분은 납부일에 비용 처리하므로
    직전 납부의 회사분÷직원분 비율로 추정한다."""

    def journal(self):
        return [
            # 9월분 떼어 둠 100, 10/10 납부: 직원분 100 + 회사분(복리후생비·세금과공과·보험료) 110
            ln(D(2026, 9, 25), "1", "25400", credit=100, vendor="국민연금공단"),
            ln(D(2026, 10, 10), "2", "25400", debit=100, vendor="국민연금공단"),
            ln(D(2026, 10, 10), "2", "81701", debit=60, vendor="국민연금공단"),
            ln(D(2026, 10, 10), "2", "82101", debit=50, vendor="근로복지공단"),
            ln(D(2026, 10, 10), "2", "10300", credit=210),
            # 10월분 떼어 둠 200 (건강보험 80, 연금 120)
            ln(D(2026, 10, 25), "3", "25400", credit=80, vendor="건강보험공단"),
            ln(D(2026, 10, 25), "3", "25400", credit=120, vendor="국민연금공단"),
            ln(D(2026, 10, 25), "3", "25400", credit=30, vendor="역삼세무서"),       # 원천세는 넣지 않음
        ]

    def test_next_payment_is_withheld_plus_company_share(self):
        rows = tax.social(self.journal(), D(2026, 11, 3))
        self.assertEqual([(r["세목"], r["대상기간"], r["납부예정일"], r["금액"], r["상태"]) for r in rows],
                         [("4대보험", "2026년 10월분", "2026-11-10", "420", "예상")])   # 200 + 200 × 110/100
        self.assertIn("1.10", rows[0]["근거"])

    def test_paid_month_is_not_listed(self):
        self.assertEqual([r["대상기간"] for r in tax.social(self.journal()[:1], D(2026, 10, 5))], ["2026년 9월분"])
        self.assertEqual(tax.social(self.journal()[:5], D(2026, 10, 10)), [])

    def test_month_end_accrual_of_company_share_is_used_as_confirmed(self):
        """사용자 2026-11-03: 월말에 회사분을 일반전표(비용 / 미지급비용, 공단)로 넣으면 추정 대신 그 금액을 확정으로 쓴다."""
        j = self.journal() + [ln(D(2026, 10, 31), "7", "81106", debit=90, vendor="건강보험공단"),
                              ln(D(2026, 10, 31), "7", "81701", debit=125, vendor="국민연금공단"),
                              ln(D(2026, 10, 31), "7", "26200", credit=215, vendor="국민연금공단")]
        rows = tax.social(j, D(2026, 11, 3))
        self.assertEqual((rows[0]["금액"], rows[0]["상태"]), ("415", "확정(전표)"))   # 200 + 215
        # 다음 달 10일 납부 전표가 미지급비용을 지우는 형태여도 납부로 알아보고 목록에서 뺀다
        paid = j + [ln(D(2026, 11, 10), "8", "25400", debit=200, vendor="국민연금공단"),
                    ln(D(2026, 11, 10), "8", "26200", debit=215, vendor="국민연금공단"),
                    ln(D(2026, 11, 10), "8", "10300", credit=415)]
        self.assertEqual(tax.social(paid, D(2026, 11, 10)), [])
        # 그 다음 달 비율도 미지급비용 차변을 회사분으로 쳐서 계산
        nxt = paid + [ln(D(2026, 11, 25), "9", "25400", credit=100, vendor="국민연금공단")]
        self.assertEqual(tax.social(nxt, D(2026, 11, 26))[0]["금액"], "208")   # 100 + 100 × 215/200

    def test_without_past_payment_company_share_equals_employee_share(self):
        rows = tax.social(self.journal()[5:], D(2026, 11, 3))
        self.assertEqual(rows[0]["금액"], "400")
        self.assertIn("직원분과 같게", rows[0]["근거"])


class TestMergeMatching(unittest.TestCase):
    def test_insurance_matches_plan_by_name_and_tax_office_does_not(self):
        T = {"kind": "4대보험", "period": "2026년 10월분", "due": D(2026, 11, 10), "amount": 420, "state": "예상", "basis": ""}
        office = {"date": D(2026, 11, 10), "io": "out", "amount": 30, "firm": True, "cat": "", "desc": "역삼세무서", "basis": ""}
        plan = {"date": D(2026, 11, 10), "io": "out", "amount": 430, "firm": True, "cat": "", "desc": "건강보험 등 4대보험", "basis": ""}
        events, info = tax.merge([office, plan], [T])
        self.assertEqual(events, [office, plan])
        self.assertIs(info[0]["matched"], plan)
        self.assertEqual(info[0]["diff"], 10)

    def test_same_amount_on_near_date_counts_as_same_tax(self):
        T = TestMerge.T
        plan = {"date": D(2027, 1, 25), "io": "out", "amount": 360, "firm": True, "cat": "", "desc": "기타", "basis": ""}
        events, info = tax.merge([plan], [T])
        self.assertEqual(events, [plan])

    def test_keyword_match_wins_over_office_match(self):
        vat = dict(TestMerge.T, due=D(2027, 1, 15))
        wh = {"kind": "원천세", "period": "하반기", "due": D(2027, 1, 11), "amount": 21, "state": "예상", "basis": ""}
        a = {"date": D(2027, 1, 11), "io": "out", "amount": 25, "firm": True, "cat": "", "desc": "역삼세무서 원천세", "basis": ""}
        b = {"date": D(2027, 1, 15), "io": "out", "amount": 365, "firm": True, "cat": "", "desc": "부가세", "basis": ""}
        _, info = tax.merge([a, b], [vat, wh])
        self.assertEqual([i["matched"] is not None and i["matched"]["desc"] for i in info], ["부가세", "역삼세무서 원천세"])


if __name__ == "__main__":
    unittest.main()


class TestSalary(unittest.TestCase):
    """급여일은 다음 달 5일, 쉬는 날이면 그 전 영업일 (사용자 2026-11-03)."""

    def accrual(self):
        return [ln(D(2026, 9, 30), "1", "80200", debit=100), ln(D(2026, 9, 30), "1", "25400", credit=10),
                ln(D(2026, 9, 30), "1", "26200", credit=90, vendor="가상직원")]

    def test_accrued_month_is_firm_and_holiday_moves_earlier(self):
        rows = tax.salary(self.accrual(), D(2026, 10, 1))
        got = [(r["대상기간"], r["납부예정일"], r["금액"], r["상태"]) for r in rows]
        self.assertEqual(got[0], ("2026년 9월분", "2026-10-02", "90", "확정(전표)"))   # 10/5 대체공휴일 → 10/2 금
        self.assertEqual(got[1:], [("2026년 10월분", "2026-11-05", "90", "예상"), ("2026년 11월분", "2026-12-04", "90", "예상"),
                                   ("2026년 12월분", "2027-01-05", "90", "예상")])   # 12/5 토 → 12/4

    def test_paid_salary_is_not_counted_again(self):
        j = self.accrual() + [ln(D(2026, 10, 2), "2", "26200", debit=90), ln(D(2026, 10, 2), "2", "10300", credit=90)]
        rows = tax.salary(j, D(2026, 10, 3))
        self.assertNotIn("2026년 9월분", [r["대상기간"] for r in rows])

    def test_no_salary_slip_no_rows(self):
        self.assertEqual(tax.salary([ln(D(2026, 9, 1), "1", "10300", debit=5)], D(2026, 10, 1)), [])


class TestCards(unittest.TestCase):
    """카드별 납부일·기산일로 결제일 계산 (사용자 2026-11-03)."""

    def test_due_from_pay_day_and_start_day(self):
        self.assertEqual(tax.card_due(D(2026, 10, 20), 15, 1), D(2026, 11, 16))    # 10월 사용 → 11/15 일요일 → 11/16
        self.assertEqual(tax.card_due(D(2026, 10, 20), 25, 12), D(2026, 11, 25))   # 10/12~11/11 사용 → 11/25
        self.assertEqual(tax.card_due(D(2026, 10, 5), 25, 12), D(2026, 10, 26))    # 9/12~10/11 사용 → 10/25 일 → 10/26
        self.assertEqual(tax.card_due(D(2026, 10, 31), 14, 31), D(2026, 12, 14))   # 10/31~11/29 사용 → 12/14

    def test_payments_clear_oldest_and_unknown_card_has_no_date(self):
        j = [ln(D(2026, 9, 10), "1", "26200", credit=100, vendor="신한_0001"),
             ln(D(2026, 10, 10), "2", "26200", credit=200, vendor="신한_0001"),
             ln(D(2026, 10, 15), "3", "26200", debit=100, vendor="신한_0001"),
             ln(D(2026, 9, 20), "4", "26200", credit=30, vendor="롯데_0002"),
             ln(D(2026, 10, 1), "5", "26200", credit=50, vendor="삼성_0003")]
        rows = tax.cards(j, D(2026, 11, 3), {"신한": (15, 1), "롯데": (14, 1)})
        got = [(r["대상기간"], r["납부예정일"], r["금액"], r["상태"]) for r in rows]
        self.assertEqual(got, [("롯데카드 11월 16일 결제", "2026-11-16", "30", "예상"),   # 10/14 지났는데 남음 → 다음 납부일
                               ("삼성카드 미결제 잔액", "", "50", "납부일 확인 필요"),
                               ("신한카드 11월 16일 결제", "2026-11-16", "200", "예상")])

    def test_card_file_and_defaults(self):
        import tempfile, shutil
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        days, notes = tax.read_card_days(tmp)
        self.assertEqual(days, {"신한": (15, 1), "롯데": (14, 1), "비씨": (25, 1)})
        self.assertIn("기본값", notes[0])
        with open(os.path.join(tmp, tax.CARD_FILE), "w", encoding="utf-8-sig") as f:
            f.write("카드사,납부일,기산일\nBC카드,25일,12\n신한,40,1\n")
        days, notes = tax.read_card_days(tmp)
        self.assertEqual(days, {"비씨": (25, 12)})
        self.assertIn("신한", notes[0])
