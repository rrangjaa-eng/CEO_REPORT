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
        self.assertFalse(car[2])                      # 한도 1,500만 안 넘음 → 0
        loan = [i for i in A["items"] if "인정이자" in i[0]][0]
        self.assertEqual(loan[1], 4_600_000)          # 1억 × 4.6% × 12/12
        self.assertEqual(A["total"], 4_600_000)

    def test_car_over_limit_is_added_1117(self):
        # 사용자 2026-11-17 (카드): 운행기록부 없음·1대로 보고 넘는 몫을 바로 과세표준에 더함
        J = [L(dt.date(2026, 1, 5), "차량유지비(판)", "82200", debit=18_000_000)]
        A = taxadj.adjust(J, {}, "2026-12", tempfile.mkdtemp(), revenue=0)
        car = [i for i in A["items"] if "승용차" in i[0]][0]
        self.assertEqual((car[1], car[2]), (3_000_000, True))
        self.assertEqual(A["total"], 3_000_000)
        A = taxadj.adjust(J, {}, "2026-12", tempfile.mkdtemp(), revenue=0, answers={"승용차기록": "씀"})
        self.assertEqual(A["total"], 0)

    def test_no_log_counts_depreciation_1117(self):
        # 11/17 최종 점검: 기록부 없음이면 감가상각비도 관련비용 (시행령 50조의2 ②⑦⑩). 가짜 숫자, 1~10월
        items = [("업무용 승용차 비용", 0, False, "")]
        old = taxadj._ledger_car
        taxadj._ledger_car = lambda *a, **k: 24_000_000          # 1년 치 상각 → 10달 2,000만
        try:
            dep = taxadj._no_log(items, ("업무용 승용차 감가상각비 한도", 999, True, "작년 → 한도 x"), 5_000_000,
                                 15_000_000, (8_000_000, True, ""), None, 2026, None, 10)
        finally:
            taxadj._ledger_car = old
        # 관련비용 2,500만 vs 한도 1,250만 → 넘는 1,250만, 비율 50% → 상각 2,000만 × 50% = 1,000만 − 666만 = 333만
        self.assertEqual((items[0][1], items[0][2]), (12_500_000, True))
        self.assertEqual((dep[1], dep[2]), (3_333_334, True))
        self.assertIn("업무사용비율 50.0%", dep[3])

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
