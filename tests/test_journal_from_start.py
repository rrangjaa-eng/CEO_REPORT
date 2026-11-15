"""작년 분개장이 빠진 경우 (2026-11-04 정합성 점검): 다음 기수 분개장엔 전기이월이 없어 잔액이 '올해 증감'뿐이 된다."""
import datetime as dt
import unittest
from types import SimpleNamespace

from ceo_report import convert, wehago

D = dt.date


def L(day, code, debit=0, credit=0, memo="", vendor="은행A", no="1"):
    return {"date": day, "no": no, "account_code": code, "account": "", "debit": debit, "credit": credit, "memo": memo,
            "vendor": vendor}


FOUNDED = [L(D(2025, 2, 1), "10300", debit=100), L(D(2025, 2, 1), "33100", credit=100)]
THIS_YEAR = [L(D(2026, 1, 2), "10300", credit=30, no="2"), L(D(2026, 1, 2), "81100", debit=30, no="2")]
CFG = {"cash_codes": ["10300"]}


class TestJournalFromStart(unittest.TestCase):
    def test_capital_in_first_month_or_opening_line_is_from_start(self):
        self.assertTrue(wehago.journal_from_start(FOUNDED + THIS_YEAR))
        self.assertFalse(wehago.journal_from_start(THIS_YEAR))
        self.assertTrue(wehago.journal_from_start([L(D(2026, 1, 1), "10300", debit=70, memo="전기 이월")] + THIS_YEAR))

    def test_bank_balance_not_built_without_last_year(self):
        books = SimpleNamespace(journal=THIS_YEAR, from_start=False)
        bal, txn = convert.build_bank(books, CFG)
        self.assertTrue(bal.written)
        self.assertEqual((bal.rows, txn.rows), ([], []))   # 머리글만: 예전 파일의 낡은 잔액을 쓰지 않게
        self.assertIn("작년 분개장 없음", bal.notes[0])

    def test_bank_balance_from_founding(self):
        books = SimpleNamespace(journal=FOUNDED + THIS_YEAR, from_start=True)
        bal, _ = convert.build_bank(books, CFG)
        last = max(r["기준일"] for r in bal.rows)
        self.assertEqual(sum(int(r["잔액"]) for r in bal.rows if r["기준일"] == last), 70)


if __name__ == "__main__":
    unittest.main()
