"""2차 전수조사 제안 22: 문구 고치기 (단위·증감률·날짜 형식·경영관리 용어)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ceo_report import annual, budget_render, plainwords, teamreport  # noqa: E402


class TestPlainWords(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        p = mock.patch.dict(os.environ, {plainwords.TEST_OFF: "0"})
        p.start()
        self.addCleanup(p.stop)

    def test_cli_writes_the_management_report_through_it(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "보고서.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("page = plainwords.plain(page)", src)

    def test_only_visible_text_changes(self):
        page = ("<style>.x:after{content:'잠정'}</style><script>var s='판단 불가';</script>"
                "<td class='미연결' title='잠정'>잠정</td><td>판단 불가</td><p>프로젝트 미연결 지급 0원 · 미연결 3건 · (잠정)</p>")
        out = plainwords.plain(page)
        self.assertIn("content:'잠정'", out)
        self.assertIn("var s='판단 불가'", out)
        self.assertIn("class='미연결' title='잠정'>마감 전</td>", out)
        self.assertIn("<td>알 수 없음</td>", out)
        self.assertIn("프로젝트를 못 찾은 지급 0원 · 못 찾음 3건 · (마감 전)", out)


class TestChange(unittest.TestCase):
    def test_tiny_last_year_is_said_in_words(self):      # J7
        self.assertEqual(annual.chg(28808416, 68594), "작년 거의 없음")
        self.assertEqual(annual.chg(5037980, 10000), "작년 거의 없음")
        self.assertEqual(annual.chg(738491753, 55306643), "+1235.3%")   # 작년 금액이 크면 비율 그대로
        self.assertEqual(annual.chg(150, 100), "+50.0%")

    def test_budget_never_shows_minus_zero(self):         # 1차 C6
        self.assertEqual(budget_render._chg(4036130000, 4036131893), "0.0%")
        self.assertEqual(budget_render._chg(90, 100), "−10.0%")
        self.assertEqual(budget_render._chg(110, 100), "+10.0%")


class TestTeamDoc(unittest.TestCase):
    def test_negative_rate_uses_the_same_mark_as_amounts(self):   # 1차 C5
        self.assertEqual(teamreport.P(-76, 1000), "△7.6%")
        self.assertEqual(teamreport.P(76, 1000), "7.6%")
        self.assertEqual(teamreport.P(-0.1, 1000), "0.0%")
        self.assertEqual(teamreport.P(1, 0), "-")

    def test_dates_use_dots(self):
        self.assertEqual(teamreport._dots("2026-01-10"), "2026.01.10")
        self.assertEqual(teamreport._dots("2026.04.06"), "2026.04.06")
        self.assertEqual(teamreport._dots("2026-4-6~2026-4-8"), "2026.04.06~2026.04.08")
        self.assertEqual(teamreport._dots(""), "")


if __name__ == "__main__":
    unittest.main()
