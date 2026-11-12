"""자동 분석 13가지 (사용자 2026-11-12)."""
import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import insights, insights_render  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402

D = dt.date
SAMPLE = os.path.join(ROOT, "입력양식", "샘플")


def bank_out(day, no, amount, payee, account="미지급금", code="25300"):
    return [{"date": day, "no": no, "account_code": "10300", "account": "보통예금", "debit": None, "credit": amount, "vendor": "신한은행"},
            {"date": day, "no": no, "account_code": code, "account": account, "debit": amount, "credit": None, "vendor": payee}]


class TestBookFacts(unittest.TestCase):
    def test_recurring_found_and_salary_card_skipped(self):
        J = []
        for m in (7, 8, 9, 10):
            J += bank_out(D(2026, m, 21), "1", 1534390, "하나캐피탈")
            J += bank_out(D(2026, m, 5), "2", 30000000 + m, "직원급여")              # 급여는 다른 계산
            J += bank_out(D(2026, m, 15), "3", 5000000, "신한_5860", "미지급비용", "26200")   # 카드대금도
        J += bank_out(D(2026, 8, 3), "4", 999000, "한번만")
        rec = insights.recurring(J, D(2026, 11, 12))
        self.assertEqual([r["name"] for r in rec], ["하나캐피탈"])
        self.assertEqual((rec[0]["amount"], rec[0]["day"]), (1534390, 21))

    def test_amounts_must_be_close(self):
        J = []
        for m, a in ((7, 100000), (8, 300000), (9, 100000), (10, 100000)):
            J += bank_out(D(2026, m, 3), "1", a, "들쭉날쭉")
        self.assertEqual(insights.recurring(J, D(2026, 11, 12)), [])


class TestMissing(unittest.TestCase):
    def R(self, asof):
        return {"asof": asof}

    def test_thin_last_month_and_not_yet_this_month(self):
        facts = {"presence": {"카드 롯데_7344 사용": {"2026-07": [3000000, 30], "2026-08": [4000000, 31], "2026-09": [5000000, 30],
                                                   "2026-10": [8177, 31]},
                              "급여": {"2026-08": [1, 31], "2026-09": [1, 30], "2026-10": [1, 31]}},
                 "recurring": [{"name": "하나캐피탈", "amount": 1534390, "day": 5, "months": {"2026-10": 1}}]}
        got = dict(insights.missing_entries(self.R(D(2026, 11, 12)), facts))
        self.assertIn("덜 들어감", got["카드 롯데_7344 사용"])
        self.assertNotIn("급여", got)             # 급여는 보통 31일쯤: 11/12엔 아직 빠졌다고 하지 않음
        self.assertIn("하나캐피탈", got)          # 5일+5일 지남


class TestOnSample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = load(SAMPLE)
        cls.R = compute(d, "weekly", D(2026, 11, 6))
        cls.d = d

    def test_compute_and_render_all(self):
        prev = insights.events_for_record(self.R)
        prev = [e for e in prev if e["desc"] != "C사"]
        I = insights.compute(self.R, None, self.d.invoices, prev)
        self.assertTrue(any("C사" in t and v == 88000000 for t, v in I["reasons"]))
        self.assertEqual(len(I["calendar"]), insights.CAL_DAYS)
        self.assertTrue(I["delay"] and I["delay"][0]["desc"] == "C사" and I["delay"][0]["drop"] < 0)
        html = insights_render.mgmt_section(I, self.R)
        for t in ("경보", "이미 쌓인 세금", "날마다 잔액", "입금 습관", "고정비", "입력 누락", "받을 돈 나이", "계산서 짝", "이익 흐름", "팀별"):
            self.assertIn(t, html)
        # 대표 보고 경보는 여유 자금 부족만 (적자 프로젝트는 뺌, 사용자 2026-11-12)
        I["alerts"] = [("높음", "[P1] 가 예상 적자 1원"), ("높음", "4주째 여유 자금이 1원 모자람")]
        self.assertNotIn("적자", insights_render.ceo_alert(I))
        self.assertIn("여유 자금", insights_render.ceo_alert(I))

    def test_tax_after_period(self):
        T = insights.taxes_set_aside(self.R)
        self.assertEqual(T["after"], T["avail"] - T["later_total"])
        self.assertTrue(all(t["due"] > self.R["s2"]["periods"][-1]["end"] for t in T["later"]))

    def test_mgmt_report_has_auto_area(self):
        from ceo_report.render import render
        page = render(self.R, "mgmt")
        self.assertIn("id='a-auto'", page)
        self.assertNotIn("a-auto", render(self.R, "ceo"))


if __name__ == "__main__":
    unittest.main()


def _fake_R(asof, start, min_cash, events, unissued):
    P = lambda i, n: {"id": i, "name": n}
    return {"asof": asof, "kind": "weekly",
            "s2": {"start": start, "min_cash": min_cash, "dated": events, "periods": []},
            "s5": {"event_unissued": {"missing": False, "total": sum(u for _, u in unissued),
                                      "rows": [{"P": P("P%d" % k, "프로젝트%d" % k), "event": asof - dt.timedelta(days=10 + k),
                                                "days": 10 + k, "unissued": u} for k, (_, u) in enumerate(unissued)]}}}


class TestIssueDeadline(unittest.TestCase):
    """계산서 발행 기한 (사용자 2026-11-12): 작성일 뒤 60일 입금, 자금이 모자라는 날 − 60일까지 발행."""

    def test_deadline_is_short_day_minus_60(self):
        ev = [{"date": D(2027, 1, 11), "io": "out", "amount": 50, "firm": False}]
        R = _fake_R(D(2026, 11, 2), 120, 100, ev, [("a", 1000000), ("b", 500)])
        X = insights.issue_deadline(R)
        self.assertEqual(X["short"][:2], (D(2027, 1, 11), 30))
        self.assertEqual(X["deadline"], D(2026, 11, 12))
        self.assertFalse(X["late"])
        self.assertEqual([r["amount"] for r in X["rows"]], [1100000])   # 부가세 포함, 1만 원 밑 끝전은 뺌
        self.assertEqual(X["small_n"], 1)
        self.assertEqual(X["rows"][0]["pay_if_today"], D(2027, 1, 1))
        html = insights_render.ceo_issue(X)
        self.assertIn("11/12까지 발행", html)
        self.assertIn("1,100,000", html)

    def test_late_when_deadline_passed(self):
        ev = [{"date": D(2026, 12, 1), "io": "out", "amount": 50, "firm": True}]
        X = insights.issue_deadline(_fake_R(D(2026, 11, 12), 120, 100, ev, [("a", 1000000)]))
        self.assertTrue(X["late"])
        self.assertEqual(X["firm_short"][0], D(2026, 12, 1))
        self.assertIn("발행했어야", insights_render.ceo_issue(X))

    def test_no_short_one_line(self):
        ev = [{"date": D(2026, 12, 1), "io": "out", "amount": 5, "firm": True}]
        X = insights.issue_deadline(_fake_R(D(2026, 11, 12), 120, 100, ev, [("a", 1000000)]))
        self.assertIsNone(X["deadline"])
        html = insights_render.ceo_issue(X)
        self.assertIn("자금은 모자라지 않습니다", html)
        self.assertNotIn("<table", html)

    def test_ceo_reports_carry_issue_and_month_line(self):
        d = load(SAMPLE)
        from ceo_report.render import render
        from ceo_report.areas import strip_ui
        R = compute(d, "weekly", D(2026, 11, 6))
        h = render(R, "ceo")
        self.assertIn("행사 끝나고 아직 발행 안 한 계산서", h)
        self.assertIn("11월 예상 영업이익", h)
        import re
        self.assertNotIn("예산", re.sub(r"<[^>]+>", "", h[h.index("<body"):]))   # 대표용엔 '예산' 글자 없음
        self.assertNotIn("<!--ins-->", strip_ui(h))
