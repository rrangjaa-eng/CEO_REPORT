"""수정(감액) 계산서가 다른 프로젝트에 붙어 있어도 같은 거래처 미수에서 뺀다 (2026-11-04: 미수금 1억여 원 부풀던 것)."""
import datetime as dt
import unittest

from ceo_report.calc import _net_credits


def inv(project, client, kind, outstanding, date):
    return {"project": project, "client": client, "kind": kind, "outstanding": outstanding, "date": dt.date(*date)}


class TestClientNetting(unittest.TestCase):
    def test_credit_on_other_project_reduces_same_client_oldest_first(self):
        a = inv("P1", "A사", "발행", 100, (2026, 9, 1))
        b = inv("P3", "A사", "발행", 50, (2026, 10, 1))
        c = inv("P2", "A사", "수정", -120, (2026, 10, 5))
        other = inv("P9", "B사", "발행", 70, (2026, 8, 1))
        _net_credits([a, b, c, other])
        self.assertEqual((a["outstanding"], b["outstanding"], other["outstanding"]), (0, 30, 70))
        self.assertEqual((c["credit_applied"], c["credit_left"]), (120, 0))

    def test_same_project_first_then_client(self):
        a = inv("P1", "A사", "발행", 100, (2026, 9, 1))
        b = inv("P2", "A사", "발행", 40, (2026, 10, 1))
        c = inv("P2", "A사", "수정", -60, (2026, 10, 5))
        _net_credits([a, b, c])
        self.assertEqual((a["outstanding"], b["outstanding"]), (80, 0))

    def test_never_below_zero_and_no_client_left_alone(self):
        a = inv("P1", "A사", "발행", 10, (2026, 9, 1))
        c = inv("P2", "A사", "수정", -30, (2026, 10, 5))
        d = inv("", "", "수정", -5, (2026, 10, 5))
        _net_credits([a, c, d])
        self.assertEqual(a["outstanding"], 0)
        self.assertEqual(c["credit_left"], 20)
        self.assertEqual(d["credit_left"], 5)


if __name__ == "__main__":
    unittest.main()
