"""프로젝트 이익 차이: 인트라넷 ↔ 장부 원인별 (사용자 2026-11-16).

· 인트라넷 이익 = 견적금액(없으면 사전견적) − 실행가, 장부 이익 = 장부 매출 − 장부 원가.
· 차이를 원인별 금액으로 나누고, 더하면 차이와 같다.
· 작년(예전 인트라넷) 프로젝트는 장부 줄이 '참고'로 따로 있어 '작년 프로젝트'로 묶는다.
· 경영관리 상세에만 붙는다 (최종 실행가 차이 표 위).
"""
import datetime as dt
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import render  # noqa: E402

ASOF = dt.date(2026, 11, 16)


def xp(key, cost, budget, vat=None, lines=3):
    return {"key": key, "name": "가상 " + key, "cost": cost, "cost_lines": lines, "cost_note": "", "cost_period": None,
            "out_of_period": False, "budget": budget, "budget_note": "", "has_budget": budget is not None, "requested": None,
            "card_vat": vat, "card_n": 1 if vat else None}


def xr(key, amount, lines=1):
    return {"key": key, "name": "가상 " + key, "wehago": amount, "wehago_lines": lines, "wehago_note": "",
            "out_of_period": False, "quote": None}


def P(key, quote, approval="", event="2026-10-01", state="", estimate=None):
    return {"id": key, "name": "가상 " + key, "quote": quote, "estimate": estimate, "approval": approval, "event_date": event,
            "state": state}


def rows_of(projects, revenue, plist):
    return dict((r["key"], r) for r in render._profit_rows({"projects": projects, "revenue": revenue},
                                                             {"asof": ASOF, "s3": {"projects": plist}}))


class TestProfitCauses(unittest.TestCase):
    def test_parts_add_up_to_the_difference(self):
        r = rows_of([xp("A", 9_000_000, 10_000_000, vat=600_000)], [xr("A", 14_000_000)], [P("A", 15_000_000, "대표이사")])["A"]
        self.assertEqual((r["iprofit"], r["bprofit"], r["diff"]), (5_000_000, 5_000_000, 0))
        self.assertEqual(dict(r["parts"]), {"revenue_diff": -1_000_000, "card_vat": 600_000, "cost_less": 400_000})
        self.assertEqual(sum(r["parts"].values()), r["diff"])

    def test_book_cost_above_budget(self):
        r = rows_of([xp("D", 12_000_000, 10_000_000)], [xr("D", 15_000_000)], [P("D", 15_000_000, "팀장")])["D"]
        self.assertEqual(dict(r["parts"]), {"cost_more": -2_000_000})

    def test_no_book_lines_before_the_event_is_timing(self):
        r = rows_of([xp("B", 0, 5_000_000, lines=0)], [xr("B", 0, 0)], [P("B", 8_000_000, event="2026-12-01")])["B"]
        self.assertEqual(dict(r["parts"]), {"before": -3_000_000})

    def test_no_book_lines_after_the_event_is_missing(self):
        r = rows_of([xp("B", 0, 5_000_000, lines=0)], [xr("B", 0, 0)], [P("B", 8_000_000, event="2026-09-01")])["B"]
        self.assertEqual(dict(r["parts"]), {"missing_book": -3_000_000})

    def test_old_intranet_project_without_lines_is_prior(self):
        r = rows_of([xp("53", 0, 3_000_000, lines=0)], [xr("53", 0, 0)],
                    [P("53", 6_000_000, event="2025-05-01", state="완료(예전 인트라넷)")])["53"]
        self.assertEqual(dict(r["parts"]), {"prior": -3_000_000})

    def test_tiny_or_blank_budget_is_an_intranet_input_gap(self):
        r = rows_of([xp("E", 60_000, 69_000)], [xr("E", 0)], [P("E", None, estimate=70_000_000, event="2026-11-25")])["E"]
        self.assertEqual(r["irev"], 70_000_000)   # 견적 없으면 사전견적
        self.assertEqual(list(r["parts"]), ["intranet_blank"])

    def test_table_has_summary_structure_and_rows(self):
        X = {"projects": [xp("A", 9_000_000, 10_000_000, vat=600_000), xp("D", 12_000_000, 10_000_000)],
             "revenue": [xr("A", 14_000_000), xr("D", 15_000_000)],
             "unlinked_lines": [{"amount": 500, "label": "자동 연결 후보 0건"}, {"amount": 9_999, "label": "참고 (지난해 프로젝트 · 연결하지 않음)"}]}
        R = {"asof": ASOF, "s3": {"projects": [P("A", 15_000_000, "대표이사"), P("D", 15_000_000, "팀장")]}}
        html = render._xk_profit_causes(X, R)
        text = re.sub(r"<[^>]+>", " ", html)
        self.assertIn("xchk-profit-causes", html)
        self.assertIn("마감 뒤에도 남음", text)
        self.assertIn("판관비", text)
        self.assertIn("회사 이익에 주는 영향 −500", text)   # 참고 줄은 빼고
        self.assertIn("−2,000,000", text)
        self.assertIn("xchk-profit-rows", html)

    def test_no_project_list_says_so(self):
        self.assertIn("인트라넷 프로젝트 자료 없음", render._xk_profit_causes({"projects": []}, {"s3": {}}))

    def test_detail_section_puts_it_above_the_final_execution_table(self):
        import inspect
        src = inspect.getsource(render._xk_detail)
        self.assertLess(src.index("_xk_profit_causes(X, R)"), src.index("_xk_final_table(X, R)"))


class TestPriorYearLink(unittest.TestCase):
    """작년 프로젝트: '참고' 줄을 옛 번호로 모아 이익 비교에 씀 (사용자 2026-11-16)."""

    def ln(self, code, amount, prior=True, slip=None):
        return {"prior": prior, "project": None, "code": code, "slip_code": slip, "amount": amount}

    def test_prior_lines_are_grouped_by_old_code(self):
        from ceo_report import convert_xchk
        projects = {"93": {"name": "가상 93"}, "26001": {"name": "가상 26001"}}
        costs = {"lines": [self.ln("93", 100), self.ln(None, 7, slip="93"), self.ln("44", 5), self.ln(None, 3),
                           self.ln("26001", 999, prior=False)]}
        revenue = {"lines": [self.ln("93", 300)]}
        rows = convert_xchk._prior_link_rows(projects, costs, revenue)
        got = dict(((r["구분"], r["대상"], r["항목"]), (r["금액"], r["건수"])) for r in rows)
        self.assertEqual(got[("지난해이음", "93", "원가")], ("107", "2"))
        self.assertEqual(got[("지난해이음", "93", "매출")], ("300", "1"))
        self.assertEqual(got[("지난해못이음", "합계", "원가")], ("8", "2"))   # 목록에 없는 44 + 번호 없음
        self.assertNotIn(("지난해이음", "26001", "원가"), got)

    def test_linked_prior_project_is_compared_normally(self):
        X = {"projects": [xp("93", 0, 7_000_000, lines=0)], "revenue": [xr("93", 0, 0)],
             "prior_link": {"93": {"원가": (7_500_000, 12), "매출": (10_000_000, 1)}}}
        R = {"asof": ASOF, "s3": {"projects": [P("93", 10_000_000, event="2025-05-01", state="완료(예전 인트라넷)")]}}
        r = dict((x["key"], x) for x in render._profit_rows(X, R))["93"]
        self.assertTrue(r["linked_prior"])
        self.assertEqual((r["brev"], r["bcost"], r["diff"]), (10_000_000, 7_500_000, -500_000))
        self.assertEqual(dict(r["parts"]), {"cost_more": -500_000})

    def test_prior_project_without_lines_stays_prior(self):
        X = {"projects": [xp("94", 0, 7_000_000, lines=0)], "revenue": [xr("94", 0, 0)], "prior_link": {},
             "prior_left": {"원가": {"amount": 8, "count": 2, "note": ""}}}
        R = {"asof": ASOF, "s3": {"projects": [P("94", 10_000_000, event="2025-05-01", state="완료(예전 인트라넷)")]}}
        r = dict((x["key"], x) for x in render._profit_rows(X, R))["94"]
        self.assertEqual(list(r["parts"]), ["prior"])
        text = re.sub(r"<[^>]+>", " ", render._xk_profit_causes(X, R))
        self.assertIn("작년 전표 중 번호로 못 이은 것: 원가 2줄 8", text)
    def test_rows_are_read_back_by_the_loader(self):
        from ceo_report import convert_xchk
        projects = {"93": {"name": "가상 93"}}
        rows = convert_xchk._prior_link_rows(projects, {"lines": [self.ln("93", 100), self.ln(None, 3)]}, {"lines": []})
        for r in rows:
            r["_line"] = 1
        X = convert_xchk._load_rows([convert_xchk._parse(dict(r)) for r in rows])
        self.assertEqual(X["prior_link"]["93"]["원가"], (100, 1))
        self.assertEqual(X["prior_left"]["원가"]["count"], 1)
        self.assertEqual(X["prior_left"]["매출"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
