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

class TestCeoWordingAndTopStrip(unittest.TestCase):
    """결정 3 (대표용 이름) · 결정 4·5 (주간 첫 줄) · 결정 6 (디자인)."""

    @classmethod
    def setUpClass(cls):
        cls.R = compute(load(SAMPLE), "weekly", D(2026, 10, 31))
        cls.ceo, cls.mgmt = render(cls.R, "ceo"), render(cls.R, "mgmt")

    def test_restriction_name(self):
        self.assertIn("쓸 수 없는 돈 (담보·전용) 30,000,000", self.ceo)
        self.assertNotIn("사용제한", self.ceo.split("<div class='toc'>")[0].split("<body")[1])
        self.assertIn("− 사용제한 30,000,000", self.mgmt)

    def test_top_strip_repeats_the_table_numbers(self):
        from ceo_report.render import week_outflows
        strip = self.ceo[self.ceo.index("<div class='four top'>"):]
        strip = strip[:strip.index("<div class='sec'>")]
        p = [x for x in self.R["s2"]["periods"] if not x.get("pick")]
        for v in (week_outflows(self.R)["pay"]["total"], p[0]["all"]["avail"], p[-1]["all"]["avail"],
                  self.R["s5"]["overdue_total"]):
            self.assertIn("{:,}".format(v), strip)
        self.assertIn("입금일 지난 미수금", strip)
        self.assertLess(self.ceo.index("<div class='four top'>"), self.ceo.index("출금 목록"))

    def test_chart_uses_table_week_names_and_short_axis(self):
        self.assertIn(">이번 주</text>", self.ceo)
        self.assertNotIn("1주차", self.ceo)
        self.assertRegex(self.ceo, r">\d(\.\d+)?억</text>")

    def test_evidence_tags_are_one_range(self):
        self.assertIn("<span class='ev'>근거 1-1~1-3</span>", self.ceo)

    def test_monthly_tables(self):
        M = render(compute(load(SAMPLE), "monthly", D(2026, 10, 31)), "mgmt")   # ⑦ 계정표는 경영관리용에만 (2026-11-04)
        self.assertIn("<th>다음 출금일</th><th>다음 출금액</th>", M)
        ay = M[M.index("class='pt ayt'"):]
        ay = ay[:ay.index("</thead>")]
        self.assertIn("<th>10월</th>", ay)
        self.assertNotIn("11월", ay)


if __name__ == "__main__":
    unittest.main()
