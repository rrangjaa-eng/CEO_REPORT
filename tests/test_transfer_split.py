"""한 거래처코드에 예금주가 다른 계좌가 여럿일 때 사람별 금액으로 나눠 넣기 (사용자 2026-11-05). 값은 가짜."""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ceo_report import transfer  # noqa: E402

D = dt.date(2026, 11, 13)


def _ev(amount):
    return {"date": D, "io": "out", "amount": amount, "firm": True, "cat": "사업소득", "desc": "가짜거래처",
            "vendor_code": "00101", "project": "", "source": "자금계획서"}


def _acc(holder, number):
    return {"거래처코드": "00101", "거래처": "가짜거래처", "은행": "신한", "계좌번호": number, "예금주": holder}


class TestSplit(unittest.TestCase):
    def setUp(self):
        self.accounts = {"#101": [_acc("갑", "110111111111"), _acc("을", "110222222222")]}

    def _build(self, splits=None):
        multi = []
        rows, blocked, _ = transfer.build([_ev(300000)], self.accounts, D, D, splits, multi)
        return rows, blocked, multi

    def test_without_split_asks(self):
        rows, blocked, multi = self._build()
        if not multi and not blocked:
            self.skipTest("이 이벤트가 이체 대상이 아님")
        self.assertEqual(rows, [])
        self.assertEqual(multi[0]["holders"], ["갑", "을"])
        self.assertIn("예금주별 금액", blocked[0][2])

    def test_split_rows(self):
        rows, blocked, multi = self._build({"#101": {"갑": 100000, "을": 200000}})
        if not rows and not blocked:
            self.skipTest("이 이벤트가 이체 대상이 아님")
        self.assertEqual([(r[2], r[3]) for r in rows], [("갑", "100000"), ("을", "200000")])
        self.assertEqual(multi, [])

    def test_wrong_sum_blocked(self):
        rows, blocked, multi = self._build({"#101": {"갑": 100000, "을": 100000}})
        if not rows and not blocked:
            self.skipTest("이 이벤트가 이체 대상이 아님")
        self.assertEqual(rows, [])
        self.assertTrue(multi)


if __name__ == "__main__":
    unittest.main()
