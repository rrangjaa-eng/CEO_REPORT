"""2차 전수조사 제안 23·27 (P9·P10·D5·V10): 해가 바뀔 때 손볼 것을 12월~3월 경영관리 할 일로 띄운다."""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ceo_report import convert, guides, tax, yearly  # noqa: E402


def facts(R):
    return [x["fact"] for x in yearly.items(R)]


class TestWindow(unittest.TestCase):
    def test_only_december_to_march(self):
        self.assertIsNone(yearly.window(dt.date(2026, 11, 30)))
        self.assertEqual(yearly.window(dt.date(2026, 12, 1)), (2027, "준비"))
        self.assertEqual(yearly.window(dt.date(2027, 3, 31)), (2027, "새 해"))
        self.assertIsNone(yearly.window(dt.date(2027, 4, 1)))
        self.assertEqual(yearly.items({"asof": dt.date(2026, 11, 18)}), [])


class TestItems(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_december_asks_for_next_years_values(self):
        f = facts({"asof": dt.date(2026, 12, 10), "input_dir": self.d})
        self.assertTrue(any("2027년 세법 기준" in x for x in f))
        self.assertTrue(any("2027년 팀 목표" in x for x in f))
        self.assertFalse(any("결산 전표" in x for x in f))        # 지난해 분개장은 1~3월에만
        self.assertFalse(any("공휴일" in x for x in f))            # 2027년은 정부 발표와 대조함

    def test_target_item_goes_away_once_entered(self):
        from ceo_report import targets
        targets.save(self.d, "2027", "기획1팀", "1000000", "30")
        self.assertFalse(any("팀 목표" in x for x in facts({"asof": dt.date(2026, 12, 10), "input_dir": self.d})))

    def test_january_adds_last_years_books_and_intranet(self):
        P = [{"id": "26001", "event_date": "2026-03-01"}, {"id": "27001", "event_date": "2027-02-01"}]
        its = yearly.items({"asof": dt.date(2027, 1, 12), "input_dir": self.d, "s3": {"projects": P}})
        f = [x["fact"] for x in its]
        self.assertTrue(any("2026년 결산 전표는 1~3월" in x for x in f))
        self.assertTrue(any("2026년 프로젝트 1건" in x for x in f))
        self.assertTrue(any("오차범위" in x and guides.MEASURED_ON in x for x in f))
        book = [x for x in its if "결산 전표" in x["fact"]][0]
        self.assertEqual(book["due"], dt.date(2027, 3, 31))
        none = yearly.items({"asof": dt.date(2027, 1, 12), "input_dir": self.d, "s3": {"projects": P[1:]}})
        hit = [x for x in none if "프로젝트 0건" in x["fact"]][0]
        self.assertEqual(hit["level"], "높음")                    # 지난해 것이 하나도 없으면 크게

    def test_unchecked_holiday_year_is_listed(self):
        with mock.patch.object(tax, "HOLIDAY_CHECKED", 2027):
            self.assertTrue(any("2028년 공휴일" in x for x in facts({"asof": dt.date(2027, 12, 5), "input_dir": self.d})))


class TestHolidays(unittest.TestCase):
    def test_2026_09_28_was_a_working_day(self):        # V10
        self.assertNotIn(dt.date(2026, 9, 28), tax.KR_HOLIDAYS)

    def test_2027_matches_the_government_calendar(self):
        for d in ((2, 8), (2, 9), (5, 3), (7, 19), (8, 16), (10, 4), (10, 11), (12, 27)):
            self.assertIn(dt.date(2027, *d), tax.KR_HOLIDAYS)


class TestPrepaidSetting(unittest.TestCase):
    def test_prefix_comes_from_settings(self):          # P10: 코드 안 고정값 → 설정
        self.assertEqual(convert.DEFAULT_CONFIG["prepaid_prefixes"], ("131",))
        self.assertIn(("변환_선급금계정앞자리", "prepaid_prefixes", "숫자목록"), convert.CONFIG_ITEMS)


if __name__ == "__main__":
    unittest.main()
