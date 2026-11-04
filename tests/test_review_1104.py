"""2026-11-04 아침 사용자 결정 반영 확인. 합성 자료만."""
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import render  # noqa: E402

D = dt.date
SAMPLE = os.path.join(ROOT, "입력양식", "샘플")


class TestBalanceRolledForwardWithTransactions(unittest.TestCase):
    """은행 잔액 기준일 뒤 입출금내역을 반영해 오늘 잔액으로 본다 (결정 2)."""

    def setUp(self):
        self.d = load(SAMPLE)
        self.R = compute(self.d, "weekly", D(2026, 10, 31))

    def test_rolled_balance_equals_bank_at_the_next_snapshot(self):
        # 11-02 은행 잔액 − 11-02 거래 = 10-31 까지 반영한 잔액이어야 한다
        nxt = {b["account"]: b["balance"] for b in self.d.balances if b["date"] == D(2026, 11, 2)}
        day = {}
        for t in self.d.txns:
            if t["date"] == D(2026, 11, 2):
                day[t["account"]] = day.get(t["account"], 0) + (t["amount"] if t["io"] == "입금" else -t["amount"])
        for a in self.R["s1"]["accounts"]:
            with self.subTest(a=a["account"]):
                self.assertEqual(a["balance"], nxt[a["account"]] - day.get(a["account"], 0))
                self.assertEqual((a["date"], a["bank_date"]), (D(2026, 10, 31), D(2026, 10, 26)))

    def test_available_and_notes(self):
        s1 = self.R["s1"]
        self.assertEqual((s1["total"], s1["available"]), (574_600_000, 544_600_000))
        self.assertEqual(s1["stale"], [])
        self.assertIn("은행 기준일 2026-10-26 + 입출금 2026-10-31까지 반영", render(self.R, "mgmt"))

    def test_no_transactions_after_the_bank_date_keeps_the_bank_balance(self):
        self.d.txns = [t for t in self.d.txns if t["date"] <= D(2026, 10, 26)]
        R = compute(self.d, "weekly", D(2026, 10, 31))
        self.assertEqual(R["s1"]["total"], 558_000_000)
        self.assertEqual(R["s1"]["rolled"], [])


if __name__ == "__main__":
    unittest.main()
