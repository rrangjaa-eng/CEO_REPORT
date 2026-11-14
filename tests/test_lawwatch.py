import datetime as dt
import io
import json
import tempfile
import unittest
import urllib.parse

from ceo_report import lawwatch as lw, taxlaw


class Numbers(unittest.TestCase):
    def test_korean_amounts_and_ratios(self):
        self.assertEqual(lw.kor_amount("1천450만원"), 14_500_000)
        self.assertEqual(lw.kor_amount("3천600만원"), 36_000_000)
        self.assertEqual(lw.kor_amount("800만원"), 8_000_000)
        self.assertEqual(lw.kor_amount("2억원"), 200_000_000)
        n = lw.numbers("과세표준의 100분의 7 … 1만분의 30 … 연 1천분의 46 … 1천500만원")
        self.assertEqual(n["비율"], [0.003, 0.046, 0.07])
        self.assertEqual(n["원"], [15_000_000])


def fake(articles):
    """law.go.kr 흉내: lawSearch → 법령 목록, lawService → 조문."""
    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(url, timeout=0):
        q = dict(urllib.parse.parse_qsl(url.split("?", 1)[1]))
        if "lawSearch" in url:
            body = {"LawSearch": {"law": [{"법령명한글": q["query"], "법령일련번호": "1", "시행일자": "20260101", "공포일자": "20251223"}]}}
        else:
            body = {"법령": {"조문": {"조문단위": [{"조문내용": articles.get(q["JO"], "")}]}}}
        return R(json.dumps(body, ensure_ascii=False).encode("utf-8"))
    return opener


class Check(unittest.TestCase):
    def test_first_then_changed_blocks_until_confirmed(self):
        d = tempfile.mkdtemp()
        lw.save_oc(d, "me")
        arts = {"013200": "최저한세 … 100분의 7"}
        res = lw.check(d, 2026, dt.date(2026, 1, 5), fake(arts))
        r = [x for x in res if "132조" in x[1]][0]
        self.assertEqual(r[2], "처음 받음")
        self.assertTrue(taxlaw.value(d, 2026, "최저한세율")[1])
        arts["013200"] = "최저한세 … 100분의 8"
        r = [x for x in lw.check(d, 2026, dt.date(2026, 7, 2), fake(arts)) if "132조" in x[1]][0]
        self.assertEqual(r[2], "개정됨")
        self.assertIn("안 보임", r[4])
        v, ok, why = taxlaw.value(d, 2026, "최저한세율")
        self.assertFalse(ok)
        self.assertIn("조문 확인 필요", why)
        taxlaw.confirm(d, 2026, {"최저한세율": "8%"}, "세무사", today=dt.date(2026, 7, 3))
        self.assertEqual(taxlaw.value(d, 2026, "최저한세율")[:2], (0.08, True))

    def test_needs_oc_and_network_failure_reported(self):
        d = tempfile.mkdtemp()
        with self.assertRaises(ValueError):
            lw.check(d, 2026)
        lw.save_oc(d, "me")

        def broken(url, timeout=0):
            raise OSError("접속 안 됨")
        res = lw.check(d, 2026, dt.date(2026, 1, 5), broken)
        self.assertTrue(all(r[2] == "실패" for r in res))

    def test_due_in_january_and_july(self):
        d = tempfile.mkdtemp()
        self.assertFalse(lw.due(d, dt.date(2027, 1, 3)))
        lw.save_oc(d, "me")
        self.assertTrue(lw.due(d, dt.date(2027, 1, 3)))
        self.assertFalse(lw.due(d, dt.date(2027, 2, 3)))


if __name__ == "__main__":
    unittest.main()
