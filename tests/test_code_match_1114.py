"""이름 대신 거래처코드로 맞추기·지난 납부일 줄 (2026-11-14 사용자 "이름으로 맞추지 말고 코드나 확실한 정보로", 점검 F3·F4·F15·F18).

실제 장부 모양: 위하고 분개장 줄은 거래처Code(앞 0 있음, 예 '00101')를 갖고, 자금계획서는 [000101] 꼴(앞 0을 떼면 같음).
통장(보통예금) 줄의 거래처는 은행이고, 진짜 거래처는 같은 전표의 미지급금·선급금 줄에 있다. 합성 자료만.
"""
import csv
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from ceo_report import app, tax  # noqa: E402
from ceo_report import review_checks as RC  # noqa: E402

D = dt.date


def ln(day, no, code, debit=None, credit=None, vendor="", vcode="", memo=""):
    return {"date": day, "no": no, "account_code": code, "account": "", "debit": debit, "credit": credit,
            "vendor": vendor, "vendor_code": vcode, "memo": memo}


def ev(day, amount, desc="", code="", source="자금계획서", io="out"):
    return {"date": day, "io": io, "amount": amount, "firm": True, "cat": "", "desc": desc, "basis": "",
            "project": "", "source": source, "vendor_code": code}


class TestTaxRowsCarryCodes(unittest.TestCase):
    def test_withholding_and_insurance_rows_carry_book_vendor_codes(self):
        j = [ln(D(2026, 10, 31), "1", "80200", debit=100),
             ln(D(2026, 10, 31), "1", "25400", credit=8, vendor="역삼세무서", vcode="00201"),
             ln(D(2026, 10, 31), "1", "25400", credit=1, vendor="강남구청", vcode="00202"),
             ln(D(2026, 10, 31), "1", "25400", credit=5, vendor="국민연금공단", vcode="00301"),
             ln(D(2026, 10, 31), "1", "26200", credit=86, vendor="급여", vcode="00401")]
        wh = tax.withholding(j, D(2026, 11, 3))
        self.assertEqual(wh[0]["거래처코드"], "201 202")
        self.assertEqual(wh[0]["장부기준일"], "2026-10-31")
        self.assertEqual(tax.social(j, D(2026, 11, 3))[0]["거래처코드"], "301")
        self.assertEqual(tax.salary(j, D(2026, 11, 3))[0]["거래처코드"], "401")


class TestMergeByCode(unittest.TestCase):
    T = {"kind": "원천세", "period": "2026년 10월분", "due": D(2026, 11, 10), "amount": 9, "state": "예상", "basis": "",
         "codes": ("201", "202"), "book": D(2026, 10, 31)}

    def test_income_tax_and_local_tax_lines_both_belong_to_the_withholding_row(self):
        a, b = ev(D(2026, 11, 10), 8, "역삼세무서", "000201"), ev(D(2026, 11, 10), 1, "강남구청", "000202")
        events, info = tax.merge([a, b], [self.T])
        self.assertEqual(events, [a, b])          # 장부 계산을 따로 더하지 않음 (두 번 빼지 않음)
        self.assertEqual(info[0]["diff"], 0)       # 두 줄 합 9 = 장부 계산 9 → 차액 줄 없음 (예전엔 한 줄만 보고 1을 또 더함)
        self.assertFalse(info[0]["by_name"])

    def test_same_amount_rent_with_other_code_is_not_taken_as_tax(self):
        """F18 ③: 같은 날짜 근처·같은 금액인 임차료가 세금에 흡수되던 것."""
        T = dict(self.T, kind="부가세", amount=300, codes=("501",))
        rent = ev(D(2026, 11, 10), 300, "가상빌딩 임차료", "000777")
        events, info = tax.merge([rent], [T])
        self.assertIsNone(info[0]["matched"])
        self.assertEqual(sorted(e["amount"] for e in events), [300, 300])   # 임차료도, 부가세도 남는다

    def test_old_line_without_code_matches_by_name_and_is_marked(self):
        plan = ev(D(2026, 11, 10), 9, "원천세 납부")
        _, info = tax.merge([plan], [self.T])
        self.assertIs(info[0]["matched"], plan)
        self.assertTrue(info[0]["by_name"])


class TestPastDueRowsStay(unittest.TestCase):
    """F3: 납부일이 지났는데 장부에 납부가 없으면 줄을 지우지 않는다 (자금계획서 '예정일 지남'과 같은 규칙)."""
    T = {"kind": "급여", "period": "2026년 10월분", "due": D(2026, 11, 5), "amount": 43_000_000, "state": "확정(전표)",
         "basis": "월말 급여 전표", "codes": ("401",)}

    def test_book_covers_due_date_so_unpaid_goes_to_next_friday(self):
        events, info = tax.merge([], [dict(self.T, book=D(2026, 11, 12))], D(2026, 11, 14), cash_date=D(2026, 11, 12))
        self.assertEqual([(e["date"], e["amount"], e["firm"]) for e in events], [(D(2026, 11, 20), 43_000_000, True)])
        self.assertNotIn("gap", events[0])
        self.assertIn("다음 금요일", info[0]["moved"])

    def test_book_stops_before_due_and_bank_balance_is_older_too(self):
        events, _ = tax.merge([], [dict(self.T, book=D(2026, 11, 3))], D(2026, 11, 14), cash_date=D(2026, 11, 3))
        self.assertEqual(events[0]["date"], D(2026, 11, 20))
        self.assertEqual(events[0]["gap"], D(2026, 11, 5))   # 큰 숫자엔 들어가고 출금 목록엔 따로 알림

    def test_bank_balance_after_due_already_reflects_it(self):
        events, info = tax.merge([], [dict(self.T, book=D(2026, 11, 3))], D(2026, 11, 14), cash_date=D(2026, 11, 13))
        self.assertEqual(events, [])
        self.assertIn("잔액에 이미 반영", info[0]["moved"])

    def test_late_salary_slip_keeps_the_row(self):
        """합성 11/14: 11/5 급여 4,300만이 장부에 없음 → 예전엔 줄이 사라져 그만큼 여유 자금이 크게 나왔다."""
        j = [ln(D(2026, 10, 31), "1", "80200", debit=50_000_000),
             ln(D(2026, 10, 31), "1", "26200", credit=43_000_000, vendor="급여", vcode="00401"),
             ln(D(2026, 11, 3), "2", "10300", debit=1)]
        rows = tax.salary(j, D(2026, 11, 14))
        self.assertEqual((rows[0]["대상기간"], rows[0]["납부예정일"], rows[0]["상태"]), ("2026년 10월분", "2026-11-05", "확정(전표)"))

    def test_card_payment_of_same_amount_is_not_salary(self):
        """F18 ④: 거래처를 보지 않고 금액만 같은 미지급비용 지급(카드대금)을 급여로 보지 않는다."""
        j = [ln(D(2026, 10, 31), "1", "80200", debit=100),
             ln(D(2026, 10, 31), "1", "26200", credit=90, vendor="급여", vcode="00401"),
             ln(D(2026, 11, 5), "2", "26200", debit=90, vendor="신한_0001", vcode="00901"),
             ln(D(2026, 11, 5), "2", "10300", credit=90)]
        self.assertIn("2026년 10월분", [r["대상기간"] for r in tax.salary(j, D(2026, 11, 6))])
        j[2]["vendor_code"], j[2]["vendor"] = "00401", "급여"
        self.assertNotIn("2026년 10월분", [r["대상기간"] for r in tax.salary(j, D(2026, 11, 6))])


class TestReplacedCard(unittest.TestCase):
    """F15 ①: 카드를 바꾸면(롯데_7344 → 7972) 옛 카드 번호에 평균이 계속 붙던 것."""

    def test_old_card_is_not_filled_after_new_card_starts(self):
        K = 10000
        j = []
        for m in (6, 7, 8):
            j.append(ln(D(2026, m, 10), "o%d" % m, "26200", credit=300 * K, vendor="롯데_7344"))
            j += [ln(D(2026, m + 1, 14), "op%d" % m, "26200", debit=300 * K, vendor="롯데_7344"),
                  ln(D(2026, m + 1, 14), "op%d" % m, "10300", credit=300 * K)]
        for m in (9, 10):
            j.append(ln(D(2026, m, 10), "n%d" % m, "26200", credit=300 * K, vendor="롯데_7972"))
            j += [ln(D(2026, m + 1, 14), "np%d" % m, "26200", debit=300 * K, vendor="롯데_7972"),
                  ln(D(2026, m + 1, 14), "np%d" % m, "10300", credit=300 * K)]
        rows = tax.cards(j, D(2026, 11, 20), {"롯데": (14, 1)})
        self.assertFalse(any("롯데_7344" in r["근거"] for r in rows), [r["근거"] for r in rows])


class TestScheduleCode(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def read(self, name=RC.SCHEDULE):
        with open(os.path.join(self.dir, name), encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    def test_picked_vendor_code_is_saved_and_old_file_gets_the_column(self):
        with open(os.path.join(self.dir, RC.SCHEDULE), "w", encoding="utf-8-sig", newline="") as f:
            f.write("예정일,입출금,금액,확정여부,분류,프로젝트번호,거래처,근거,비고\r\n2026-11-20,지급,1000,확정,,,가,,\r\n")
        app.add_schedule(self.dir, "2026-11-27", "지급", "2,000", "확정", "가상 인쇄소", vendor_code="00123")
        rows = self.read()
        self.assertEqual([(r["거래처"], r["거래처코드"] or "") for r in rows], [("가", ""), ("가상 인쇄소", "00123")])

    def test_archive_matches_by_code_on_the_other_line_of_the_bank_slip(self):
        """통장 줄 거래처는 은행, 같은 전표 선급금 줄에 진짜 거래처 코드 (적요·이름이 아니라 계정·거래처로, 사용자 2026-11-14)."""
        with open(os.path.join(self.dir, RC.SCHEDULE), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["예정일", "입출금", "금액", "확정여부", "분류", "프로젝트번호", "거래처", "근거", "비고", "거래처코드"])
            w.writerow(["2026-11-06", "지급", "500000", "확정", "", "", "가상 인쇄소", "선급", "", "00123"])
            w.writerow(["2026-11-06", "지급", "700000", "확정", "", "", "가상 인쇄소", "다른 거래처 같은 이름", "", "00999"])
        J = [ln(D(2026, 11, 6), "1", "13100", debit=500000, vendor="(주)가상인쇄", vcode="00123"),
             ln(D(2026, 11, 6), "1", "10300", credit=500000, vendor="신한은행", vcode="98001"),
             ln(D(2026, 11, 6), "2", "13100", debit=700000, vendor="가상 인쇄소", vcode="00124"),
             ln(D(2026, 11, 6), "2", "10300", credit=700000, vendor="신한은행", vcode="98001")]
        RC.archive_paid_schedule(self.dir, J, D(2026, 11, 10))
        left = self.read()
        self.assertEqual([r["근거"] for r in left], ["다른 거래처 같은 이름"])   # 이름이 같아도 코드가 다르면 다른 지급
        self.assertEqual(left[0]["거래처코드"], "00999")                           # 다시 쓸 때 코드 칸이 남는다
        self.assertEqual([r["거래처코드"] for r in self.read(RC.ARCHIVE)], ["00123"])


if __name__ == "__main__":
    unittest.main()
