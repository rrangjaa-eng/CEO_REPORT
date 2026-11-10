"""창 상태 계산 (사용자 2026-11-05: 창을 쓰기 편하게 다시 꾸미기)."""
import datetime as dt
import os
import shutil
import tempfile
import time
import unittest

from ceo_report import app, checklist, winstate


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.P = app.Paths(self.tmp)
        for d in (self.P.input, self.P.wehago, self.P.output):
            os.makedirs(d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def touch(self, path, when):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("x")
        t = time.mktime(when.timetuple())
        os.utime(path, (t, t))


class TestDays(unittest.TestCase):
    def test_day_label(self):
        self.assertEqual(winstate.day_label("2026-11-13"), ("(금)", False))
        self.assertEqual(winstate.day_label("2026.11.6"), ("(금)", False))
        self.assertEqual(winstate.day_label("", "비우면 11/13"), ("비우면 11/13", False))
        self.assertTrue(winstate.day_label("2026-13-01"), ("형식 오류", True))

    def test_next_friday_and_transfer(self):
        self.assertEqual(winstate.next_friday(dt.date(2026, 11, 5)), dt.date(2026, 11, 6))
        self.assertEqual(winstate.next_friday(dt.date(2026, 11, 6)), dt.date(2026, 11, 13))
        self.assertEqual(winstate.transfer_range(dt.date(2026, 11, 13)), (dt.date(2026, 11, 7), dt.date(2026, 11, 13)))
        self.assertEqual(winstate.transfer_range(dt.date(2026, 11, 6), dt.date(2026, 11, 5)),
                         (dt.date(2026, 11, 6), dt.date(2026, 11, 6)))

    def test_money(self):
        self.assertEqual(winstate.money("1234000"), "1,234,000")
        self.assertEqual(winstate.money("1,23"), "123")
        self.assertEqual(winstate.money("-5000원"), "-5,000")
        self.assertEqual(winstate.money("abc"), "abc")
        self.assertEqual(winstate.money(""), "")

    def test_level(self):
        asof = dt.date(2026, 11, 6)
        self.assertEqual(winstate.level(dt.date(2026, 10, 30), asof), "g")
        self.assertEqual(winstate.level(dt.date(2026, 10, 29), asof), "y")
        self.assertEqual(winstate.level(dt.date(2026, 10, 7), asof), "y")
        self.assertEqual(winstate.level(dt.date(2026, 10, 6), asof), "r")
        self.assertEqual(winstate.level(None, asof), "none")
        self.assertEqual(winstate.when_text(dt.datetime(2026, 11, 6, 9, 12), asof), "오늘 09:12")
        self.assertEqual(winstate.when_text(dt.date(2026, 11, 5), asof), "11/5 · 1일 전")


class TestState(Base):
    def test_remember_values(self):
        today = dt.date(2026, 11, 5)
        self.assertEqual(winstate.start_values(self.P.input, today), {"asof": "2026-11-05", "payday": "", "pick": ""})
        winstate.save(self.P.input, payday="2026-11-13", pick="2026-10-01")
        v = winstate.start_values(self.P.input, today)
        self.assertEqual(v["payday"], "2026-11-13")
        self.assertEqual(v["pick"], "")   # 이미 지난 날은 비움
        winstate.remember_run(self.P.input, "변환", True, now=dt.datetime(2026, 11, 5, 18, 40))
        self.assertEqual(winstate.load(self.P.input)["runs"]["변환"], {"at": "2026-11-05 18:40", "ok": True})
        self.assertEqual(winstate.load(self.P.input)["payday"], "2026-11-13")


class TestFreshAndSteps(Base):
    def test_sources_and_steps(self):
        asof = dt.date(2026, 11, 6)
        P = self.P
        self.assertEqual(winstate.steps(P)["now"], 1)
        self.touch(os.path.join(P.wehago, "분개장_2026.xls"), dt.datetime(2026, 11, 5, 10, 0))
        self.touch(os.path.join(P.wehago, "자금계획서_지출입금현황_2026-11.xls"), dt.datetime(2026, 10, 1, 10, 0))
        self.touch(os.path.join(P.collect, "홈택스", "매출.xls"), dt.datetime(2026, 9, 1, 10, 0))
        checklist.save_bank(P.input, "2026-11-04", "1,000")
        F = {f["name"]: f for f in winstate.freshness(P, asof)}
        self.assertEqual(F["분개장"]["level"], "g")
        self.assertEqual(F["자금계획서"]["level"], "r")
        self.assertEqual(F["홈택스 세금계산서"]["level"], "r")
        self.assertEqual(F["통장 잔액"]["text"], "11/4 · 2일 전")
        self.assertEqual(F["인트라넷 (지급요청·견적)"]["level"], "none")
        S = winstate.steps(P)
        self.assertEqual(S["now"], 2)   # 변환 전
        checklist.save_convert_items(P.input, [], now=dt.datetime(2026, 11, 5, 18, 0))
        S = winstate.steps(P)
        self.assertEqual((S["now"], S["new_since"]), (3, []))
        self.touch(os.path.join(P.wehago, "분개장_2026_2.xls"), dt.datetime(2026, 11, 5, 19, 0))
        S = winstate.steps(P)
        self.assertEqual((S["now"], S["new_since"]), (2, ["분개장"]))

    def test_auto_collected_json(self):
        # 크롬 확장 자동수집 json 만 있어도 '없음'이 아님 (2026-11-10 사용자: 창에 자금계획서가 없음으로 나옴)
        asof = dt.date(2026, 11, 10)
        P = self.P
        self.touch(os.path.join(P.wehago, "261110 분개장 자동수집.json"), dt.datetime(2026, 11, 10, 17, 35))
        self.touch(os.path.join(P.wehago, "261110 자금계획 자동수집.json"), dt.datetime(2026, 11, 10, 17, 36))
        F = {f["name"]: f for f in winstate.freshness(P, asof)}
        self.assertEqual(F["분개장"]["level"], "g")
        self.assertEqual(F["자금계획서"]["level"], "g")
        self.assertEqual(F["자금계획서"]["text"], "오늘 17:36")

    def test_latest_reports(self):
        P = self.P
        self.assertEqual(winstate.latest_reports(P.output), {})
        for n, t in (("2026-10-31_월간_대표보고.html", 1), ("2026-11-05_주간_대표보고.html", 2),
                     ("2026-11-05_주간_대표보고.pdf", 2), ("2026-11-05_주간_경영관리보고.html", 2)):
            self.touch(os.path.join(P.output, n), dt.datetime(2026, 11, 5, 10, t))
        R = winstate.latest_reports(P.output)
        self.assertEqual(R["kind"], "주간")
        self.assertTrue(R["대표"].endswith("2026-11-05_주간_대표보고.pdf"))
        self.assertTrue(R["경영관리"].endswith("2026-11-05_주간_경영관리보고.html"))


class TestMergeAndEvidence(Base):
    def test_merge_candidates(self):
        rows = [{"desc": "(주)에이치앤비", "amount": 1000}, {"desc": "에이치앤비", "amount": 2000},
                {"desc": "에이치앤비 ", "amount": None}, {"desc": "한빛인쇄", "amount": 500},
                {"desc": "대한조명", "amount": 10}, {"desc": "대한조명", "amount": 20}, {"desc": "", "amount": 1}]
        C = winstate.merge_candidates(self.P.input, dt.date(2026, 11, 6), rows=rows)
        self.assertEqual([(g["name"], g["n"], g["total"]) for g in C], [("(주)에이치앤비", 3, 3000), ("대한조명", 2, 30)])
        self.assertEqual(winstate.merge_label(C[0]), "(주)에이치앤비 · 3건 · 3,000원 + 금액 미확인 1건")

    def test_merge_candidates_from_sample(self):
        sample = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "입력양식", "샘플")
        C = winstate.merge_candidates(sample, dt.date(2026, 11, 2))
        self.assertIsInstance(C, list)

    def test_evidence_choices(self):
        P = self.P
        self.assertEqual(winstate.evidence_choices(P.output, "주간"), (None, []))
        html = "<tr><td><b>근거 1-1</b></td><td>지금 자금</td><td><a href='#ev-1-1'>"
        with open(os.path.join(P.output, "2026-11-05_주간_경영관리보고.html"), "w", encoding="utf-8") as f:
            f.write(html)
        name, rows = winstate.evidence_choices(P.output, "주간", dt.date(2026, 11, 5))
        self.assertEqual(rows, [("1-1", "지금 자금")])


class TestMessages(unittest.TestCase):
    def test_rc(self):
        self.assertEqual(winstate.rc_message("변환", 0), (True, "변환 완료. 다음: 확인할 것을 보고 3단계 보고 만들기"))
        ok, text = winstate.rc_message("인트라넷", 3)
        self.assertFalse(ok)
        self.assertIn("비밀번호", text)
        self.assertNotIn("종료코드", winstate.rc_message("주간", 7)[1])


if __name__ == "__main__":
    unittest.main()
