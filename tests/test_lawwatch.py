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

    def test_due_when_not_fetched_in_7_days(self):
        """사용자 2026-11-17: 법령 관련 항목은 최신 법령을 먼저 확인 → 7일 안에 받은 적 없으면 보고 전에 받음 (예전: 1·7월만)."""
        d = tempfile.mkdtemp()
        self.assertFalse(lw.due(d, dt.date(2027, 1, 3)))   # 아이디 없으면 못 받음
        lw.save_oc(d, "me")
        self.assertTrue(lw.due(d, dt.date(2027, 2, 3)))
        S = lw.load(d)
        S["last"] = "2027-02-01"
        lw._write(d, S)
        self.assertFalse(lw.due(d, dt.date(2027, 2, 7)))
        self.assertTrue(lw.due(d, dt.date(2027, 2, 8)))

    def test_state_message_and_ensure_failure_does_not_stop(self):
        d = tempfile.mkdtemp()
        self.assertIn("최신 법령 확인 못 함", lw.state(d, dt.date(2027, 2, 3))["msg"])
        lw.save_oc(d, "me")

        def broken(url, timeout=0):
            raise OSError("접속 안 됨")
        st = lw.ensure(d, 2027, dt.date(2027, 2, 3), broken)
        self.assertFalse(st["ok"])
        self.assertIn("받기 실패", st["msg"])
        S = lw.load(d)
        S["last"] = "2027-02-01"
        S["last_try"] = {"날": "2027-02-01", "받음": 31, "전체": 31, "실패": []}
        lw._write(d, S)
        st = lw.state(d, dt.date(2027, 2, 3))
        self.assertTrue(st["ok"])
        self.assertIn("2027-02-01 (2일 전)", st["msg"])


if __name__ == "__main__":
    unittest.main()


class TestRefusedAnswer1117(unittest.TestCase):
    """2026-11-17 PC 확인: Referer 없이 부르면 200 + '사용자 정보 검증에 실패' JSON. 실패로 알리고, 머리글엔 Referer 를 넣는다."""

    def test_refused_json_is_an_error(self):
        import io
        from ceo_report import lawwatch

        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        body = '{ "result" : "사용자 정보 검증에 실패하였습니다.", "msg" : "IP주소 및 도메인주소를 등록해 주세요." }'.encode("utf-8")
        with self.assertRaises(ValueError) as c:
            lawwatch._get("https://x", opener=lambda url, timeout=None: R(body))
        self.assertIn("사용자 정보 검증에 실패", str(c.exception))

    def test_referer_header(self):
        from ceo_report import lawwatch
        self.assertEqual(lawwatch.HEADERS["Referer"], "https://www.law.go.kr/")


class PcFindings1117(unittest.TestCase):
    """2026-11-17 새 exe로 PC에서 받아 본 결과: 17개 중 14개 받음, 3개 TypeError, 확인한 값 5개가 '값 안 보임'으로 막힘."""

    def test_nested_list_text(self):
        from ceo_report import lawwatch
        o = {"목": [{"목내용": [["가. 중소기업의 경우", "│ 증가 인원 수 × 400만원 │"]]}]}
        self.assertIn("400만원", lawwatch._texts(o))
        self.assertIn(4_000_000, lawwatch.numbers(lawwatch._texts(o))["원"])

    def test_cheon_baek_amount(self):
        from ceo_report import lawwatch
        self.assertEqual(lawwatch.kor_amount("1천5백만원"), 15_000_000)
        self.assertEqual(lawwatch.kor_amount("39억8천만원"), 3_980_000_000)

    def test_confirmed_value_stays_usable_when_only_not_seen(self):
        import json, os, tempfile
        from ceo_report import lawwatch, taxlaw
        d = tempfile.mkdtemp()
        taxlaw.confirm(d, 2026, {"국민연금요율": "9.5%"}, "세무사", today=dt.date(2026, 11, 13))
        S = {"oc": "x", "last": "", "items": {"국민연금법 88조": {"hash": "h", "text": "1천분의 65", "시행일자": "20261020", "공포일자": "",
             "keys": ["국민연금요율"], "seen": "2026-11-17", "flag": True, "changed": "", "miss": ["국민연금 요율"]}}}
        with open(os.path.join(d, lawwatch.FILE), "w", encoding="utf-8") as f:
            json.dump(S, f, ensure_ascii=False)
        self.assertTrue(taxlaw.value(d, 2026, "국민연금요율", today=dt.date(2026, 11, 17))[1])   # 부칙에 있는 단계 인상값 → 그대로 씀
        S["items"]["국민연금법 88조"]["changed"] = "2026-11-17"
        with open(os.path.join(d, lawwatch.FILE), "w", encoding="utf-8") as f:
            json.dump(S, f, ensure_ascii=False)
        self.assertFalse(taxlaw.value(d, 2026, "국민연금요율", today=dt.date(2026, 11, 17))[1])  # 확인 뒤 실제 개정 → 다시 확인

    def test_min_wage_notice_pick(self):
        from ceo_report import lawwatch
        body = {"AdmRulSearch": {"admrul": [
            {"행정규칙명": "통계작성의 변경승인(협의) 고시(최저임금적용효과에관한실태조사)", "행정규칙일련번호": "1", "시행일자": "20261115"},
            {"행정규칙명": "2027년 적용 최저임금안 고시", "행정규칙일련번호": "2", "시행일자": "20260805"},
            {"행정규칙명": "2026년 적용 최저임금 고시", "행정규칙일련번호": "3", "시행일자": "20260101"}]}}
        import io

        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        got = lawwatch.find_admrul("x", "최저임금", opener=lambda url, timeout=None: R(json.dumps(body).encode("utf-8")), ref="20261117")
        self.assertEqual(got["mst"], "3")
