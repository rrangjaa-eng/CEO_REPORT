"""11/17 저녁 제안(오류·빠진 기능·추가 기능) 고침 시험. 합성 자료만."""
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

D = dt.date


def jl(day, no, code, name, debit=None, credit=None, vendor="", vcode="", memo="", sort="매출전표"):
    return {"date": day, "no": no, "account_code": code, "account": name, "debit": debit, "credit": credit,
            "vendor": vendor, "vendor_code": vcode, "memo": memo, "sort": sort, "project_name": ""}


class TestE3VendorCode(unittest.TestCase):
    """E3 (계산-01): 매출 계산서에 거래처코드를 남기고 입금 습관을 코드로 묶는다."""
    def test_sales_invoice_keeps_vendor_code(self):
        from ceo_report import wehago
        j = [jl(D(2026, 3, 2), "7", "10800", "외상매출금", debit=1_100_000, vendor="가회사", vcode="00123"),
             jl(D(2026, 3, 2), "7", "41200", "용역매출", credit=1_000_000, vendor="가회사", vcode="00123"),
             jl(D(2026, 3, 2), "7", "25500", "부가세예수금", credit=100_000)]
        _, sales = wehago.invoices_from_journal(j)
        self.assertEqual(sales[0]["vendor_code"], "123")

    def test_pay_habits_group_by_code_not_name(self):
        from ceo_report import insights
        inv = lambda name, code, due, paid: {"client": name, "client_code": code, "due": due, "paid_date": paid}
        invs = [inv("가회사", "123", D(2026, 1, 1), D(2026, 1, 11)), inv("(주)가회사", "123", D(2026, 2, 1), D(2026, 2, 11)),
                inv("가회사", "999", D(2026, 1, 1), D(2026, 1, 1))]
        R = {"s2": {"dated": []}}
        out = insights.pay_habits(R, invs)
        # 이름이 달라도 코드 123 은 한 거래처 (2건 평균 10일), 이름이 같아도 코드 999 는 다른 거래처 (1건이라 빠짐)
        self.assertEqual([(c[1], c[2]) for c in out["clients"]], [(10, 2)])
        self.assertTrue(out["clients"][0][0].endswith("[123]"))


if __name__ == "__main__":
    unittest.main()


class TestE3Words(unittest.TestCase):
    def test_penalty_by_account_first_and_memo_lines_shown(self):
        from ceo_report import taxadj
        import inspect
        src = inspect.getsource(taxadj)
        self.assertIn("pen_memo.append", src)
        self.assertTrue(taxadj.PENALTY.search("세금과공과벌과금"))

    def test_local_prepaid_lines_are_reported_in_basis(self):
        from ceo_report import corptax
        self.assertIn("구청", corptax.LOCAL_WORDS)
