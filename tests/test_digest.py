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
    return re.findall(r"<section class='area[^']*' id='a-([^']+)'", page)


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
        self.assertEqual(area_ids(page)[0], "home")   # 첫 화면 (2026-11-14 주제별 묶기)
        self.assertFalse([k for k in area_ids(page) if re.fullmatch(r"c\d", k)])
        for hid in ("c1", "c2", "c3", "c4", "c5"):
            self.assertNotIn("<h2 id='%s'>" % hid, page)
        # 대신 자료 안내에 줄이 있고 언제 들어가는지 적힘 (사용자 2026-11-13)
        docs = page[page.index("id='a-docs'"):page.index("id='a-all'")]
        for word in ("이익잉여금처분계산서", "기업신용평가", "신고 일정", "세무조정 예상", "내년 예산", "연간 보고", "팀장용", "예측 오차", "현금흐름표"):
            self.assertIn(word, docs)
        self.assertIn("반기(6·12월)분 보고에 들어감", docs)

    def test_every_area_has_easy_explanation_and_suggestion(self):
        for R in (self.oct, self.sep, self.jun):
            page = render(R, "mgmt")
            secs = re.findall(r"<section class='area[^']*' id='a-([^']+)'.*?</section>", page, flags=re.S)
            for k, body in zip(secs, re.findall(r"<section class='area[^']*' id='a-[^']+'.*?</section>", page, flags=re.S)):
                with self.subTest(k):
                    self.assertIn("<b class='gk'>쉬운 설명</b>", body)
                    self.assertIn("<b class='gk'>제안</b>", body)

    def test_credit_brief_line_in_docs(self):
        import copy as _c
        R = _c.copy(self.oct)
        R["credit_brief"] = "기업신용평가 미리보기 (2026년 결산 기준): 추정 BB0 ~ BBB-"
        page = render(R, "mgmt")
        docs = page[page.index("id='a-docs'"):page.index("id='a-all'")]
        self.assertIn("최근 결과: 기업신용평가 미리보기 (2026년 결산 기준): 추정 BB0 ~ BBB-", docs)

    def test_track_suggestions(self):
        K = {"months": [{"ym": "2026-10", "made": dt.date(2026, 9, 25),
                         "in": {"firm": 88000000, "all": 110000000, "actual": 70000000},
                         "out": {"firm": 97300000, "all": 210263610, "actual": 90614701}}]}
        s = digest.track_suggest(K)
        self.assertTrue(any("예상 포함 출금이 실제보다 57% 많았습니다" in x for x in s), s)
        self.assertTrue(any("확정이라던 입금이 20% 덜" in x for x in s), s)

    def test_quarter_half_and_closing_prep(self):
        self.assertEqual([k for k in area_ids(render(self.jun, "mgmt")) if re.fullmatch(r"c\d", k)], ["c1", "c2", "c3", "c4"])
        self.assertEqual([k for k in area_ids(render(self.sep, "mgmt")) if re.fullmatch(r"c\d", k)], ["c1", "c2", "c3", "c5"])

    def test_every_old_chapter_is_still_in_the_appendix(self):
        page = render(self.oct, "mgmt")
        for i in range(1, 10):
            self.assertIn("<h2 id='s%d'>" % i if i < 9 else "id='a-s9'", page)
        for k in ("sum", "ev", "risk", "auto"):   # 예전 영역 이름은 그 자리를 가리키는 표시로 남음 (링크가 그대로 감)
            self.assertIn("id='a-%s'" % k, page)
        self.assertIn("지난 예상 대비 실제 오차 (보고 기록 ↔ 나중 장부) <small class='oldl'>자동 분석 15</small>", page)

    def test_ceo_edition_unchanged_by_summary(self):
        page = render(self.oct, "ceo")
        self.assertNotIn("1쪽 요약", page)
        self.assertNotIn("신호등", page)

    def test_one_page_summary_parts(self):
        page = render(self.oct, "mgmt")
        one = page[page.index("id='a-home'"):page.index("id='a-cash'")]   # 첫 화면 (2026-11-14 주제별 묶기)
        for word in ("자료 상태", "대표에게 나간 숫자", "주제별 신호", "할 일", "지난 예상 대비 실제", "이번 달 기한 신고"):
            self.assertIn(word, one)
        self.assertEqual(one.count("<a class='tq-sg "), 8)   # 월간 8주제
        week = compute(load(SAMPLE), "weekly", dt.date(2026, 11, 2))
        p = render(week, "mgmt")
        self.assertEqual(p[p.index("id='a-home'"):p.index("id='a-cash'")].count("<a class='tq-sg "), 6)

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
