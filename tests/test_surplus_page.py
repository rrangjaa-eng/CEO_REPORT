import datetime as dt
import os
import tempfile
import unittest

from ceo_report import surplus


S = {"year": 2026, "cur": {"당기순이익": (185_561_631, "예상", "1~10월"), "전기이월": (139_945_610, "확정", "2025 분개장"),
                           "미처분": (325_507_241, "예상", ""), "차기이월": (325_507_241, "예상", "")},
     "years": [(2025, {"당기순이익": (139_945_610, "확정", ""), "처분액": (0, "확정", ""), "차기이월": (139_945_610, "확정", "")})],
     "advice": {"verdict": "이월", "amount": 0, "reasons": ["4월 대출 만기"], "timing": "", "facts": [], "checklist": []}}


class Page(unittest.TestCase):
    def test_page_has_numbers_and_proposal(self):
        h = surplus.page(dict(S, advice=None), dt.date(2026, 11, 13))
        for x in ("139,945,610", "185,561,631", "325,507,241", "이익잉여금처분계산서", "처리 방법 4가지", "결산 때 처리 순서", "세무사 확인"):
            self.assertIn(x, h)
        self.assertTrue(h.startswith("<!doctype html>"))

    def test_write(self):
        d = tempfile.mkdtemp()
        p = surplus.write_page(dict(S, advice=None), d, dt.date(2026, 11, 13))
        self.assertTrue(p.endswith(os.path.join("결산", "2026_이익잉여금_설명.html")))
        self.assertIsNone(surplus.write_page(None, d, dt.date(2026, 11, 13)))


class Articles(unittest.TestCase):
    def test_rules_and_todo(self):
        from ceo_report import articles
        from ceo_report.util import esc
        h = articles.render({}, esc)
        self.assertIn("임원퇴직금지급규정", h)
        self.assertIn("중간배당", h)
        self.assertEqual(len(articles.todo({"임원퇴직금규정": "있음", "임원보수한도": "있음"})), 1)
        self.assertEqual(articles.SHARES * articles.PAR, 20_000_000)


if __name__ == "__main__":
    unittest.main()
