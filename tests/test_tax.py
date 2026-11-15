"""세금 납부 예상 (사용자 2026-11-03): 분개장 부가세예수금·부가세대급금·예수금으로 부가세(분기)·원천세 납부액. 합성 자료만."""
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from ceo_report import tax  # noqa: E402

D = dt.date


def ln(day, no, code, debit=None, credit=None, vendor="", memo=""):
    return {"date": day, "no": no, "account_code": code, "account": "", "debit": debit, "credit": credit, "vendor": vendor,
            "memo": memo}


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
        # 3분기분은 미지급으로만 잡혀 있고 11/2까지의 장부에 통장 납부가 없음 → 납부일이 지나도 지우지 않는다 (F3, 2026-11-14)
        self.assertEqual([(r["대상기간"], r["납부예정일"], r["금액"], r["상태"]) for r in rows],
                         [("2026년 3분기 (7~9월)", "2026-10-26", "70", "확정(전표)"),
                          ("2026년 4분기 (10~12월)", "2027-01-25", "360", "예상")])
        self.assertIn("2026-11-02까지", rows[1]["근거"])
        self.assertEqual(rows[0]["장부기준일"], "2026-11-02")

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
        # 9월까지 뗀 21 + 아직 급여 전표 없는 10~12월은 9월 금액 10으로 (F4, 2026-11-14). 다음 상반기도 같은 금액으로 6달
        self.assertEqual([(r["대상기간"], r["납부예정일"], r["금액"]) for r in rows],
                         [("2026년 하반기 (7~12월)", "2027-01-11", "51"), ("2027년 상반기 (1~6월)", "2027-07-12", "60")])
        self.assertIn("2026-09 금액", rows[0]["근거"])

    def test_monthly_payer_due_next_month_tenth(self):
        j = [ln(D(2026, 9, 10), "1", "25400", debit=5, vendor="역삼세무서"),
             ln(D(2026, 10, 25), "2", "25400", credit=8, vendor="역삼세무서")]
        rows = tax.withholding(j, D(2026, 11, 3))
        got = [(r["대상기간"], r["납부예정일"], r["금액"], r["상태"]) for r in rows]
        self.assertEqual(got[0], ("2026년 10월분", "2026-11-10", "8", "예상"))
        # 급여 전표 전 달도 최근 달 금액으로 기준일 달 + 7달 전까지 (F4: 12/10 원천세 줄이 없던 것)
        self.assertEqual(got[1:3], [("2026년 11월분", "2026-12-10", "8", "예상"), ("2026년 12월분", "2027-01-11", "8", "예상")])
        self.assertEqual(got[-1][0], "2027년 5월분")


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
        self.assertNotIn("2026년 하반기 (7~12월)", [r["대상기간"] for r in tax.withholding(j, D(2027, 1, 9))])


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
        self.assertEqual([(r["세목"], r["대상기간"], r["납부예정일"], r["금액"], r["상태"]) for r in rows][:2],
                         [("4대보험", "2026년 10월분", "2026-11-10", "420", "예상"),    # 200 + 200 × 110/100
                          ("4대보험", "2026년 11월분", "2026-12-10", "420", "예상")])   # 급여 전표 전 달은 최근 달 금액 (F4)
        self.assertIn("1.10", rows[0]["근거"])
        self.assertIn("급여 전표 전", rows[1]["근거"])
        self.assertEqual(rows[-1]["대상기간"], "2027년 5월분")
        self.assertEqual(rows[0]["거래처코드"], "")   # 합성 줄엔 코드 없음

    def test_paid_month_is_not_listed(self):
        self.assertEqual([r["대상기간"] for r in tax.social(self.journal()[:1], D(2026, 10, 5))][:2], ["2026년 9월분", "2026년 10월분"])
        self.assertNotIn("2026년 9월분", [r["대상기간"] for r in tax.social(self.journal()[:5], D(2026, 10, 10))])

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
        self.assertNotIn("2026년 10월분", [r["대상기간"] for r in tax.social(paid, D(2026, 11, 10))])
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
                                   ("2026년 12월분", "2027-01-05", "90", "예상"), ("2027년 1월분", "2027-02-05", "90", "예상"),
                                   ("2027년 2월분", "2027-03-05", "90", "예상"), ("2027년 3월분", "2027-04-05", "90", "예상"),
                                   ("2027년 4월분", "2027-05-04", "90", "예상"), ("2027년 5월분", "2027-06-04", "90", "예상")])   # 12/5 토 → 12/4, 5/5 어린이날 → 5/4 (기준일 달 + 7달 전까지, F4)

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

    @staticmethod
    def paid(day, no, amount, vendor="신한_0001"):
        """통장에서 나간 카드 결제 전표 (미지급비용 차변 / 보통예금 대변)."""
        return [ln(day, no, "26200", debit=amount, vendor=vendor), ln(day, no, "10300", credit=amount, vendor="신한은행")]

    def test_payments_clear_oldest_and_unknown_card_has_no_date(self):
        j = [ln(D(2026, 9, 10), "1", "26200", credit=100, vendor="신한_0001"),
             ln(D(2026, 10, 10), "2", "26200", credit=200, vendor="신한_0001"),
             *self.paid(D(2026, 10, 15), "3", 100),
             ln(D(2026, 9, 20), "4", "26200", credit=30, vendor="롯데_0002"),
             ln(D(2026, 10, 1), "5", "26200", credit=50, vendor="삼성_0003")]
        rows = tax.cards(j, D(2026, 11, 3), {"신한": (15, 1), "롯데": (14, 1)})
        got = [(r["대상기간"], r["납부예정일"], r["금액"], r["상태"]) for r in rows]
        # 사용자 2026-11-12: 전표로 들어간 사용 − 결제는 확정 (여유 자금에서 뺌)
        # 10/14 결제일이 지났는데 장부에 결제가 없음: 다음 결제일로 미루지 않고 그 날짜로 둔다 (F3, 2026-11-14 — 보고서가 장부
        # 기준일을 보고 다음 금요일로 옮기거나 통장 잔액에 반영된 것으로 봄)
        self.assertEqual(got, [("롯데카드 10월 14일 결제", "2026-10-14", "30", "확정(전표)"),
                               ("삼성카드 미결제 잔액", "", "50", "납부일 확인 필요"),
                               ("신한카드 11월 16일 결제", "2026-11-16", "200", "확정(전표)")])

    def history(self, vendor, amounts, no=""):
        """6~9월 사용, 다음 달 15일에 통장 결제."""
        j = []
        for m, a in zip((6, 7, 8, 9), amounts):
            j.append(ln(D(2026, m, 10), "u%d%s" % (m, no), "26200", credit=a, vendor=vendor))
            j.extend(self.paid(D(2026, m + 1, 15), "p%d%s" % (m, no), a, vendor))
        return j

    def test_month_not_entered_yet_uses_three_month_average(self):
        """사용자 2026-11-04: 카드 전표는 한 달에 한 번 전월분을 한꺼번에 넣음 → 입력 전 달은 최근 3달 평균으로 예상 + 표시.
        사용자 2026-11-12: 입력된 부분은 확정, 평균과의 차이만 예상.
        사용자 2026-11-13: 끝난 이용기간에 전표가 하나도 없을 때만 '입력 전' 경고. 지금 이용기간은 경고 없이 '이번 달 사용 추정'."""
        K = 10000
        j = self.history("신한_0001", (100 * K, 200 * K, 300 * K, 210 * K))
        rows = tax.cards(j, D(2026, 11, 4), {"신한": (15, 1)})
        avg = (200 + 300 + 210) * K // 3
        got = [(r["대상기간"], r["납부예정일"], r["금액"], r["상태"]) for r in rows]
        self.assertEqual(got, [("신한카드 11월 16일 결제 (전표 입력 전 추정)", "2026-11-16", str(avg), "예상"),
                               ("신한카드 12월 15일 결제 (이번 달 사용 추정)", "2026-12-15", str(avg), "예상")])
        self.assertTrue(rows[0]["근거"].startswith(tax.CARD_THIN_MARK))
        self.assertTrue(rows[1]["근거"].startswith(tax.CARD_OPEN_MARK))

    def test_entered_month_with_low_use_is_not_thin(self):
        """사용자 2026-11-13 ("카드 전표가 다 들어갔는데 왜 덜 들어갔다고 나와"): 지난달 전표가 들어간 카드는 적게 썼어도 채우지 않는다."""
        K = 10000
        j = self.history("신한_0001", (100 * K, 200 * K, 300 * K, 210 * K))
        j.append(ln(D(2026, 10, 3), "u10", "26200", credit=20 * K, vendor="신한_0001"))   # 10월은 적게 씀 (전표는 넣음)
        rows = tax.cards(j, D(2026, 11, 13), {"신한": (15, 1)})
        got = [(r["대상기간"], r["금액"], r["상태"]) for r in rows]
        self.assertEqual(got[0], ("신한카드 11월 16일 결제", str(20 * K), "확정(전표)"))
        self.assertFalse(any(r["근거"].startswith(tax.CARD_THIN_MARK) for r in rows))

    def test_rarely_used_card_is_not_filled(self):
        """평균 10만 원 밑 카드(한 달 몇천 원)는 전표가 없어도 채우지 않는다 (사용자 2026-11-13)."""
        j = self.history("롯데_0359", (2700, 5400, 4050, 4050))
        rows = tax.cards(j, D(2026, 11, 13), {"롯데": (14, 1)})
        self.assertEqual(rows, [])

    def test_thin_is_judged_per_card_number(self):
        """사용자 2026-11-12: 한 카드사에서 일부 카드만 10월 전표가 들어간 달도 빠진 카드만 평균으로 채운다."""
        K = 10000
        j = self.history("신한_0001", (100 * K,) * 4, "a") + self.history("신한_0002", (50 * K,) * 4, "b")
        j.append(ln(D(2026, 10, 3), "u10a", "26200", credit=100 * K, vendor="신한_0001"))   # 0001 은 10월분 다 넣음, 0002 는 아직
        j.append(ln(D(2026, 11, 2), "u11a", "26200", credit=100 * K, vendor="신한_0001"))
        j.append(ln(D(2026, 11, 2), "u11b", "26200", credit=50 * K, vendor="신한_0002"))
        rows = tax.cards(j, D(2026, 11, 4), {"신한": (15, 1)})
        got = [(r["대상기간"], r["금액"], r["상태"]) for r in rows]
        self.assertEqual(got, [("신한카드 11월 16일 결제", str(100 * K), "확정(전표)"),
                               ("신한카드 11월 16일 결제 (전표 입력 전 추정)", str(50 * K), "예상"),
                               ("신한카드 12월 15일 결제", str(150 * K), "확정(전표)")])
        self.assertIn("신한_0002", rows[1]["근거"])

    def test_pay_as_you_go_card_and_reversal(self):
        """사용자 2026-11-12: 한도 증액 카드는 쓰는 대로 은행에서 먼저 갚고(일반전표), 임시로 넣은 사용은 나중에 대체로 되돌린다.
        통장 없는 차변(대체)은 결제가 아니라 사용 취소, 쓰는 대로 갚는 카드는 평균으로 채우지 않는다."""
        j = []
        for m in (6, 7, 8, 9, 10):
            j.append(ln(D(2026, m, 5), "u%d" % m, "26200", credit=1000, vendor="롯데_1842"))
            j.extend(self.paid(D(2026, m, 6), "p%d" % m, 1000, "롯데_1842"))
        j.append(ln(D(2026, 11, 6), "t1", "26200", credit=600, vendor="롯데_1842"))      # 임시 사용
        j.append(ln(D(2026, 11, 6), "t2", "26200", debit=600, vendor="롯데_1842"))       # 대체 (통장 없음)
        j.extend(self.paid(D(2026, 11, 6), "t3", 600, "롯데_1842"))                       # 은행 출금
        rows = tax.cards(j, D(2026, 11, 12), {"롯데": (14, 1)})
        self.assertEqual(rows, [])   # 갚을 것 없음, 평균 채움 없음 (11월 사용 전표가 들어오면 미리 낸 600과 상계)

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


class TestDeposits(unittest.TestCase):
    """정기예금 가입·만기 (사용자 2026-11-03). 가상 금액."""

    def j(self):
        M = "정기예금입금"
        return [ln(D(2026, 2, 19), "1", "10500", debit=70, memo=M), ln(D(2026, 2, 19), "1", "10300", credit=70),
                ln(D(2026, 3, 19), "2", "10500", credit=70, memo="정기예금만기해지"),
                ln(D(2026, 5, 4), "3", "10500", debit=40, memo=M), ln(D(2026, 6, 4), "4", "10500", credit=40, memo="정기예금만기해지"),
                ln(D(2026, 10, 17), "5", "10500", debit=90, memo=M),
                ln(D(2026, 10, 25), "6", "10500", debit=5, memo="공제부금_3회차"),   # 정기예금이 아님
                ln(D(2026, 11, 20), "7", "10500", debit=30, memo=M)]                 # 미리 넣은 가입 전표

    def test_open_deposit_matures_after_usual_term(self):
        rows = tax.deposits(self.j(), D(2026, 11, 3))
        got = [(r["세목"], r["납부예정일"], r["금액"], r["상태"]) for r in rows]
        self.assertEqual(got, [("정기예금 만기", "2026-11-17", "90", "예상"),       # 10/17 + 1개월
                               ("정기예금 가입", "2026-11-20", "30", "확정(전표)"),
                               ("정기예금 만기", "2026-12-21", "30", "예상")])      # 12/20 일 → 12/21
        self.assertIn("2건", rows[0]["근거"])

    def test_maturity_is_cash_in_on_the_schedule(self):
        rows = tax.deposits(self.j(), D(2026, 11, 3))
        taxes = [{"kind": r["세목"], "period": r["대상기간"], "due": D.fromisoformat(r["납부예정일"]), "amount": int(r["금액"]),
                  "state": r["상태"], "basis": r["근거"]} for r in rows]
        events, _ = tax.merge([], taxes)
        self.assertEqual([(e["date"], e["io"], e["amount"]) for e in events],
                         [(D(2026, 11, 17), "in", 90), (D(2026, 11, 20), "out", 30), (D(2026, 12, 21), "in", 30)])

    def test_overdue_maturity_moves_to_today(self):
        rows = tax.deposits([ln(D(2026, 9, 1), "1", "10500", debit=50, memo="정기예금")], D(2026, 11, 3))
        self.assertEqual((rows[0]["납부예정일"], rows[0]["금액"]), ("2026-11-03", "50"))
        self.assertIn("해지 전표 없음", rows[0]["근거"])


class TestCardMatchNeedsSameCompany(unittest.TestCase):
    def test_lotte_payment_is_not_taken_by_shinhan_schedule(self):
        sched = [{"date": D(2026, 11, 14), "io": "out", "amount": 14, "firm": True, "cat": "카드대금", "desc": "신한카드", "basis": ""}]
        t = [{"kind": "카드대금", "period": "롯데카드 11월 16일 결제", "due": D(2026, 11, 16), "amount": 3, "state": "예상", "basis": ""},
             {"kind": "카드대금", "period": "신한카드 11월 16일 결제", "due": D(2026, 11, 16), "amount": 5, "state": "예상", "basis": ""}]
        events, info = tax.merge(sched, t)
        self.assertIsNone(info[0]["matched"])
        self.assertEqual(info[1]["matched"]["desc"], "신한카드")
        self.assertEqual(len(events), 2)

    def test_statement_amount_replaces_both_firm_and_estimated_rows(self):
        """명세서 금액을 일정에 넣으면 같은 카드사·결제일의 확정분·추정분 둘 다 넣지 않는다 (이중으로 빠지지 않게)."""
        sched = [{"date": D(2026, 11, 16), "io": "out", "amount": 900, "firm": True, "cat": "카드대금", "desc": "신한카드", "basis": ""}]
        t = [{"kind": "카드대금", "period": "신한카드 11월 16일 결제", "due": D(2026, 11, 16), "amount": 500, "state": "확정(전표)", "basis": ""},
             {"kind": "카드대금", "period": "신한카드 11월 16일 결제 (전표 입력 전 추정)", "due": D(2026, 11, 16), "amount": 300,
              "state": "예상", "basis": tax.CARD_THIN_MARK}]
        events, info = tax.merge(sched, t)
        self.assertEqual(len(events), 1)
        self.assertIsNotNone(info[1]["matched"])
