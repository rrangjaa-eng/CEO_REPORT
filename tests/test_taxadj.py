import datetime as dt
import tempfile
import unittest

from ceo_report import corptax, taxadj


def L(d, acct, code, debit=None, credit=None, memo="", sort=""):
    return {"date": d, "account": acct, "account_code": code, "debit": debit, "credit": credit, "memo": memo, "sort": sort}


class Adjust(unittest.TestCase):
    def test_entertainment_over_limit_and_penalty(self):
        J = [L(dt.date(2026, 3, 1), "접대비(기업업무추진비)(판)", "81300", debit=40_000_000),
             L(dt.date(2026, 4, 1), "세금과공과금(판)", "81700", debit=300_000, memo="주정차 과태료")]
        A = taxadj.adjust(J, {}, "2026-06", tempfile.mkdtemp(), revenue=1_000_000_000)
        ent = [i for i in A["items"] if i[0].startswith("접대비")][0]
        # 한도 = (3,600만 + 연 매출 20억 × 0.3%) × 6/12 = 2,100만 → 초과 1,900만
        self.assertEqual(ent[1], 19_000_000)
        self.assertTrue(ent[2])
        self.assertEqual(A["total"], 19_300_000)

    def test_car_and_loan_need_check_or_counted(self):
        J = [L(dt.date(2026, 1, 5), "차량유지비(판)", "82200", debit=12_000_000),
             L(dt.date(2026, 1, 1), "가지급금", "13400", debit=100_000_000)]
        A = taxadj.adjust(J, {}, "2026-12", tempfile.mkdtemp(), revenue=0)
        car = [i for i in A["items"] if "승용차" in i[0]][0]
        self.assertFalse(car[2])                      # 승용차인지 몰라 확인 필요
        loan = [i for i in A["items"] if "인정이자" in i[0]][0]
        self.assertEqual(loan[1], 4_600_000)          # 1억 × 4.6% × 12/12
        self.assertEqual(A["total"], 4_600_000)

    def test_bad_debt(self):
        J = [L(dt.date(2025, 3, 1), "외상매출금", "10800", debit=300_000_000),
             L(dt.date(2026, 3, 1), "외상매출금", "10800", debit=200_000_000),
             L(dt.date(2026, 3, 2), "대손충당금", "10900", credit=1_000_000)]
        B = corptax.bad_debt(J, {}, "2026-10")
        self.assertEqual(B["amount"], 4_000_000)      # 5억 × 1% − 100만
        self.assertFalse(B["partial"])
        B = corptax.bad_debt(J[1:], {}, "2026-10")
        self.assertTrue(B["partial"])


if __name__ == "__main__":
    unittest.main()
