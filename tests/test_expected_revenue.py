"""인트라넷 사전견적(예상 매출) 중 계산서 안 나간 금액을 행사일로 나눠 대표 월간 보고에 (사용자 2026-11-04)."""
import datetime as dt
import unittest

from ceo_report import render as rd
from ceo_report.calc import event_unissued, expected_revenue

ASOF = dt.date(2026, 10, 31)


def X(pid, event, est, issued):
    return {"P": {"id": pid, "name": pid, "event_date": event, "estimate": est}, "issued": issued}


ROWS = [X("P1", "2026-09-01", 100, 40), X("P2", "2026-11-20", 300, 0), X("P3", "2027-01-20", 20, 0),
        X("P4", "2026-12-01", 50, 60), X("P5", "", 70, 0), X("P6", "2026-11-01", 30, None), X("P7", "2026-11-01", None, 0)]


class TestExpectedRevenue(unittest.TestCase):
    def test_groups_by_event_date(self):
        E = expected_revenue(ROWS, ASOF, False)
        self.assertEqual((E["past"], E["past_n"]), (60, 1))
        self.assertEqual((E["this_year"], E["this_year_n"]), (300, 1))   # 초과 발행(P4)은 0, 빼지 않음
        self.assertEqual((E["later"], E["later_n"]), (20, 1))
        self.assertEqual((E["no_date_n"], E["unknown_n"], E["est_n"]), (1, 1, 6))
        self.assertEqual((E["year_est"], E["year_n"]), (100 + 300 + 50 + 30, 4))

    def test_past_equals_event_unissued_total(self):
        self.assertEqual(expected_revenue(ROWS, ASOF, False)["past"], event_unissued(ROWS, ASOF, False)["total"])

    def test_strip_in_both_editions_definition_only_in_mgmt(self):
        rows = ROWS[:3] + [X("Q1", "2026-11-05", 40, 0)]
        for r, t in zip(rows, ("기획1팀", "기획2팀", "기획1팀", "")):
            r["P"]["team"] = t
        E = expected_revenue(rows, ASOF, False)
        self.assertEqual(E["by_team"]["기획1팀"], {"past": 60, "this_year": 0, "n": 1})   # 2027년 행사(P3)는 빠짐
        R = {"asof": ASOF, "s5": {"expected": E},
             "s4": {"ym": "2026-10", "sources": {"WEHAGO": {"table": [{"unit": "회사", "ytd": {"revenue": 250}}]}}}}
        ceo, mg = rd._expected_strip(R, "ceo"), rd._expected_strip(R, "mgmt")
        for h in (ceo, mg):
            # 누적 250 + 앞으로 들어올 매출(행사 끝남 60 + 남은 행사 340) 400 = 650. 2027년 행사(P3)는 빠짐
            self.assertIn("<div class='big'>250</div>", h)
            self.assertIn("<div class='big'>400 <small>3건</small></div>", h)
            self.assertIn("<div class='big'>650</div>", h)
        # 풀이 줄(계산식·뺀 것)은 경영관리용에만, 대표용은 머리말 한 구절 (사용자 2026-11-05: 안내 최소)
        self.assertIn("2027년 이후 행사 제외", ceo)
        self.assertNotIn("내년 보고에", ceo)
        self.assertIn("2027년 이후 행사 1건은 내년 보고에", mg)
        self.assertNotIn("모두 공급가액", ceo)
        self.assertIn("모두 공급가액", mg)

    def test_no_intranet_data_says_so(self):
        R = {"asof": ASOF, "s5": {"expected": expected_revenue([], ASOF, False)}, "s4": {"ym": "2026-10"}}
        self.assertIn("자료 없음", rd._expected_strip(R))
