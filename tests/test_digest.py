"""경영관리보고 짧게 (사용자 2026-11-12 승인): 1쪽 요약·본문, 부록 A·B 에 모든 장 그대로, 결산·세무·신용평가는 정기 절 부록 C."""
import copy
import datetime as dt
import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report import digest  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import render  # noqa: E402
from sample_input import SAMPLE, refresh as refresh_sample  # noqa: E402


def area_ids(page):
    return re.findall(r"<section class='area' id='a-([^']+)'", page)


def month_R(month):
    d = load(SAMPLE)
    end = (dt.date(2026, month + 1, 1) - dt.timedelta(days=1)) if month < 12 else dt.date(2026, 12, 31)
    return compute(d, "monthly", end)


class TestPeriodic(unittest.TestCase):
    def test_which_months_get_which_regular_parts(self):
        for m, want in ((1, set()), (3, {"q"}), (6, {"q", "h"}), (9, {"q", "prep"}), (10, set()), (11, set()), (12, {"q", "h"})):
            R = {"kind": "monthly", "period": (dt.date(2026, m, 1), dt.date(2026, m, 28))}
            self.assertEqual(digest.periodic(R), want, m)
        self.assertEqual(digest.periodic({"kind": "weekly", "period": (dt.date(2026, 9, 1), dt.date(2026, 9, 30))}), set())


class TestReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        refresh_sample()
        cls.oct = month_R(10)
        cls.sep = month_R(9)
        cls.jun = month_R(6)

    def test_monthly_without_regular_part_has_no_tax_or_credit(self):
        page = render(self.oct, "mgmt")
        self.assertEqual(area_ids(page)[0], "one")
        self.assertFalse([k for k in area_ids(page) if k.startswith("c")])
        for word in ("이익잉여금처분계산서", "기업신용평가 미리보기", "신고 일정 (장부 기준)", "세무조정 예상 ("):
            self.assertNotIn(word, page)

    def test_quarter_half_and_closing_prep(self):
        self.assertEqual([k for k in area_ids(render(self.jun, "mgmt")) if k.startswith("c")], ["c1", "c2", "c3", "c4"])
        self.assertEqual([k for k in area_ids(render(self.sep, "mgmt")) if k.startswith("c")], ["c1", "c2", "c3", "c5"])

    def test_every_old_chapter_is_still_in_the_appendix(self):
        page = render(self.oct, "mgmt")
        for i in range(1, 10):
            self.assertIn("<h2 id='s%d'>" % i if i < 9 else "id='a-s9'", page)
        for k in ("sum", "ev", "risk", "auto"):
            self.assertIn("id='a-%s'" % k, page)
        self.assertIn("15. 지난 예상 대비 실제 오차", page)

    def test_ceo_edition_unchanged_by_summary(self):
        page = render(self.oct, "ceo")
        self.assertNotIn("1쪽 요약", page)
        self.assertNotIn("신호등", page)

    def test_one_page_summary_parts(self):
        page = render(self.oct, "mgmt")
        one = page[page.index("id='a-one'"):page.index("id='a-sum'")]
        self.assertIn("영역별 신호등", one)
        self.assertIn("지난 예상 대비 실제", one)
        self.assertIn("해야 할 일", one)
        self.assertIn("이번 달 기한 신고", one)
        self.assertEqual(one.count("class='tile "), 8)   # 월간 8영역
        week = compute(load(SAMPLE), "weekly", dt.date(2026, 11, 2))
        p = render(week, "mgmt")
        self.assertEqual(p[p.index("id='a-one'"):p.index("id='a-sum'")].count("class='tile "), 6)

    def test_lights_follow_existing_risk_levels(self):
        R = copy.copy(self.oct)
        R["risks"] = [{"level": "높음", "area": "수금", "fact": "가", "action": "나"},
                      {"level": "중간", "area": "자금", "fact": "다", "action": "라"}]
        L = dict((x["key"], x["lv"]) for x in digest.lights(R))
        self.assertEqual((L["ar"], L["cash"], L["proj"]), ("bad", "wa", "ok"))
        self.assertEqual(digest.todos(R)[0][:2], ("ar", "나"))

    def test_fold_rule(self):
        L = [{"key": "a", "lv": "wa"}, {"key": "b", "lv": "wa"}, {"key": "c", "lv": "ok"}, {"key": "d", "lv": "bad"}]
        prev = (dt.date(2026, 9, 30), {"a": "wa", "b": "ok", "c": "wa", "d": "bad"})
        out = dict((x["key"], x["open"]) for x in digest.decide(copy.deepcopy(L), prev, {"d"}))
        # a: 주의 그대로·할 일 없음 → 접음 (사용자 카드), b: 나빠짐 → 펼침, c: 좋아짐 → 접음, d: 할 일 → 펼침
        self.assertEqual(out, {"a": False, "b": True, "c": False, "d": True})
        first = dict((x["key"], x["open"]) for x in digest.decide(copy.deepcopy(L), None, set()))
        self.assertEqual(first, {"a": True, "b": True, "c": False, "d": True})

    def test_record_round_trip(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        R = {"kind": "monthly", "asof": dt.date(2026, 9, 30), "_lights": [{"key": "cash", "lv": "wa"}]}
        digest.write_record(out, R)
        self.assertEqual(digest.load_previous(out, "monthly", dt.date(2026, 10, 31)), (dt.date(2026, 9, 30), {"cash": "wa"}))
        self.assertIsNone(digest.load_previous(out, "monthly", dt.date(2026, 9, 30)))
        self.assertIsNone(digest.load_previous(out, "weekly", dt.date(2026, 10, 31)))

    def test_filing_line_only_this_month(self):
        R = {"asof": dt.date(2026, 10, 31), "filing": [
            {"기한": "2026-11-10", "신고": "원천세", "대상": "10월", "상태": "남음"},
            {"기한": "2027-01-25", "신고": "부가세", "대상": "4분기", "상태": "남음"},
            {"기한": "2026-11-10", "신고": "지방소득세", "대상": "10월", "상태": "냄"}]}
        self.assertEqual(digest.filing_line(R), ["2026-11-10 원천세 (10월)"])


if __name__ == "__main__":
    unittest.main()
