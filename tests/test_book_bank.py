"""통장 잔액·입출금 = 분개장 보통예금 (사용자 2026-11-04). 합성 숫자만 쓴다."""
import csv
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from ceo_report import convert, data  # noqa: E402
from test_dept import Books, line  # noqa: E402

D = dt.date


def bank(day, no, vendor, debit=None, credit=None):
    ln = line(day, "10300", "보통예금", debit, credit)
    ln["no"], ln["vendor"] = no, vendor
    return ln


def journal():
    return [bank(D(2025, 2, 3), "1", "가은행", debit=100_000_000),
            bank(D(2025, 3, 10), "2", "가은행", credit=30_000_000),
            bank(D(2025, 3, 20), "3", "가은행", credit=5_000_000),   # 계좌간이체: 같은 전표
            bank(D(2025, 3, 20), "3", "나은행", debit=5_000_000),
            line(D(2025, 3, 10), "25300", "미지급금", 30_000_000),
            bank(D(2025, 5, 2), "4", "나은행", debit=1_000_000)]


class TestBuildBank(unittest.TestCase):
    def test_month_end_and_last_day_balances_and_transfer(self):
        bal, txn = convert.build_bank(Books(journal()), dict(convert.DEFAULT_CONFIG))
        snaps = [(r["기준일"], r["계좌명"], r["잔액"]) for r in bal.rows]
        self.assertIn(("2025-02-28", "가은행", "100000000"), snaps)
        self.assertIn(("2025-03-31", "가은행", "65000000"), snaps)
        self.assertIn(("2025-04-30", "나은행", "5000000"), snaps)      # 입출금 없는 달도 말일 잔액
        self.assertIn(("2025-05-02", "나은행", "6000000"), snaps)      # 장부 마지막 날
        self.assertEqual([(r["입출금"], r["금액"], r["분류"]) for r in txn.rows],
                         [("입금", "100000000", ""), ("출금", "30000000", ""), ("출금", "5000000", data.TRANSFER),
                          ("입금", "5000000", data.TRANSFER), ("입금", "1000000", "")])
        self.assertIn("합계 71,000,000", bal.notes[0])

    def test_no_cash_lines_writes_nothing(self):
        out = convert.build_bank(Books([line(D(2025, 3, 1), "25300", "미지급금", 1)]), dict(convert.DEFAULT_CONFIG))
        self.assertEqual([t.written for t in out], [False, False])


class TestLoadUsesBookBank(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def put(self, name, header, rows):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)

    def test_book_rows_and_restriction_only(self):
        bal, txn = convert.build_bank(Books(journal()), dict(convert.DEFAULT_CONFIG))
        self.put(data.BOOK_BAL_FILE, data.BOOK_BAL_KEYS, [[r[k] for k in data.BOOK_BAL_KEYS] for r in bal.rows])
        self.put(data.BOOK_TXN_FILE, data.SCHEMA["입출금내역.csv"],
                 [[r[k] for k in data.SCHEMA["입출금내역.csv"]] for r in txn.rows])
        self.put("계좌잔액.csv", data.SCHEMA["계좌잔액.csv"], [["2025-05-01", "가은행", "", "999", "20000000", "담보"]])
        self.put("입출금내역.csv", data.SCHEMA["입출금내역.csv"], [["2025-05-01", "가은행", "입금", "777", "", "", "", ""]])
        d = data.load(self.dir)
        self.assertTrue(d.book_bank)
        restr = [b for b in d.balances if b["restricted"]]
        self.assertEqual([(b["account"], b["balance"], b["restricted"]) for b in restr], [("사용제한: 가은행", 0, 20_000_000)])
        self.assertNotIn(777, [t["amount"] for t in d.txns])
        self.assertEqual(len(d.txns), 5)


if __name__ == "__main__":
    unittest.main()


class TestCardFeeDeductedAtSale(unittest.TestCase):
    """2026-11-04 실제 자료: 카드 매출 전표는 매출채권을 수수료 뺀 금액만 잡고 수수료는 지급수수료 차변."""

    def test_fee_goes_into_paid_so_nothing_left_owed(self):
        from ceo_report import wehago

        def ln(code, name, debit=None, credit=None, vendor="가카드"):
            x = line(D(2026, 3, 2), code, name, debit, credit)
            x["no"], x["vendor"], x["sort"] = "7", vendor, "매출전표"
            return x
        j = [ln("10800", "외상매출금", debit=1_078_000), ln("83100", "지급수수료(판)", debit=22_000),
             ln("41200", "용역매출", credit=1_000_000), ln("25500", "부가세예수금", credit=100_000)]
        _, sales = wehago.invoices_from_journal(j)
        self.assertEqual((sales[0]["total"], sales[0]["deducted"]), (1_100_000, 22_000))
