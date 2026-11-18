"""2026-11-16 편의성 개선 — 자동 반영·지금 현황·신고 도우미 (문서 27·28·30·31·33번). 모두 가상 자료."""
import datetime as dt
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import app, digest, live  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
T0 = dt.datetime(2026, 11, 12, 10, 0, 0)


def touch(path, when, text="{}"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    t = when.timestamp()
    os.utime(path, (t, t))


def sec(n):
    return T0 + dt.timedelta(seconds=n)


class AutoCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.P = app.Paths(self.root)
        os.makedirs(self.P.input)
        self.dl = os.path.join(self.root, "dl")

    def mark(self, state, when, where="folder", fail=0):
        p = os.path.join(self.P.wehago if where == "folder" else os.path.join(self.dl, app.AUTO_DIR), app.MARK_FILE)
        touch(p, when, json.dumps({"상태": state, "못받음": fail}, ensure_ascii=False))


class TestItem27CollectMark(AutoCase):
    def test_waits_while_extension_says_collecting_even_after_quiet_time(self):
        """27: 받기 중간에 90초 넘게 멈춰도(저장 허용 대기 등) 확장이 '받는 중'이라고 적어 둔 동안은 자동 반영을 시작하지 않는다."""
        self.mark("받는 중", sec(-5))
        touch(os.path.join(self.P.wehago, "261112 분개장 자동수집.json"), T0)
        self.assertIsNone(app.auto_signature(self.P, sec(300), dirs=[]))
        st = app.auto_state(self.P, sec(300), dirs=[])
        self.assertEqual(st["state"], "collecting")
        self.assertIn("받는 중", st["text"])

    def test_starts_soon_after_end_mark_without_quiet_wait(self):
        """27: '이번 받기 끝' 표시가 마지막 파일 뒤에 있으면 90초를 더 기다리지 않는다 (쓰기 끝날 20초만)."""
        touch(os.path.join(self.P.wehago, "261112 분개장 자동수집.json"), T0)
        touch(os.path.join(self.P.wehago, "261112 자금계획 자동수집.json"), sec(40))
        self.mark("끝", sec(41))
        self.assertIsNone(app.auto_signature(self.P, sec(50), dirs=[]))
        sig = app.auto_signature(self.P, sec(65), dirs=[])
        self.assertIn("분개장", sig)
        self.assertEqual(app.auto_state(self.P, sec(65), dirs=[])["state"], "ready")

    def test_stale_collecting_mark_falls_back_to_quiet_rule(self):
        """27: 크롬이 꺼져 '받는 중'이 남은 채면(20분 넘음) 예전 규칙(마지막 파일 뒤 90초)으로 돈다 — 영영 멈추지 않게."""
        self.mark("받는 중", sec(-5))
        touch(os.path.join(self.P.wehago, "261112 분개장 자동수집.json"), T0)
        self.assertIsNotNone(app.auto_signature(self.P, sec(app.MARK_FRESH_SEC + 60), dirs=[]))

    def test_old_end_mark_and_no_mark_keep_quiet_rule(self):
        """27: 끝 표시가 새 파일보다 앞(지난번 받기 것)이거나 없으면(분개장만 따로 받기·예전 확장) 지금처럼 90초 조용할 때."""
        self.mark("끝", sec(-600))
        touch(os.path.join(self.P.wehago, "261112 분개장 자동수집.json"), T0)
        st = app.auto_state(self.P, sec(60), dirs=[])
        self.assertEqual(st["state"], "wait")
        self.assertIn("기다림", st["text"])
        self.assertIsNotNone(app.auto_signature(self.P, sec(120), dirs=[]))

    def test_mark_in_download_folder_counts(self):
        """27: 저장 폴더를 안 고른 PC는 표시도 다운로드 폴더에 생긴다."""
        self.mark("받는 중", sec(-5), where="dl")
        touch(os.path.join(self.dl, app.AUTO_DIR, "261112 분개장 자동수집.json"), T0)
        self.assertEqual(app.auto_state(self.P, sec(300), dirs=[self.dl])["state"], "collecting")

    def test_no_new_data_state(self):
        self.assertEqual(app.auto_state(self.P, T0, dirs=[])["state"], "none")

    def test_mark_is_not_data(self):
        """27: 표시 파일은 자료가 아니다 — '다른 위하고 자료'로 세지 않고 다운로드에서 가져오지도 않는다."""
        from ceo_report import winstate
        self.mark("끝", T0)
        self.mark("끝", T0, where="dl")
        self.assertIsNone(winstate.other_wehago_time(self.P))
        self.assertEqual(app.pending_downloads([self.dl]), [])

    def test_extension_writes_marks_around_collect_all(self):
        """27: 확장 '모두 받기'가 시작할 때 '받는 중', 끝날 때 '끝'을 같은 이름 파일에 남긴다 (프로그램과 같은 이름)."""
        with open(os.path.join(ROOT, "chrome_extension", "background.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn('"%s"' % app.MARK_FILE, js)
        body = js[js.index("async function collectAll"):]
        body = body[:body.index("\n}\n")]
        a, b = body.index('writeMark("받는 중"'), body.index('writeMark("끝"')
        self.assertLess(a, body.index("collectJournal"))
        self.assertGreater(b, body.index("collectPlan"))


class TestItem28Retry(unittest.TestCase):
    def test_auto_line_and_retry(self):
        """28: 자동 반영 옆에 지금 무엇을 기다리는지, 실패했으면 '실패 — 다시 하기'."""
        from ceo_report import winstate
        self.assertEqual(winstate.auto_line({"state": "none", "text": "새 자료 없음"}, failed=""), ("자동 반영: 새 자료 없음", "idle", False))
        self.assertEqual(winstate.auto_line({"state": "collecting", "text": "위하고 확장이 받는 중"}, failed="")[1], "wait")
        text, kind, retry = winstate.auto_line({"state": "none", "text": "새 자료 없음"}, failed="기준일 형식 오류")
        self.assertIn("실패", text)
        self.assertIn("기준일 형식 오류", text)
        self.assertEqual((kind, retry), ("bad", True))
        self.assertEqual(winstate.auto_line(None, failed="", running=True), ("자동 반영: 반영 중", "now", False))


class TestItem30LiveColours(unittest.TestCase):
    def test_outgoing_money_up_is_bad(self):
        """30: 곧 낼 세금·카드·보험·급여가 늘면 빨강(나쁨), 줄면 초록. 통장 잔액은 늘면 초록."""
        self.assertEqual(live.change_class("곧 낼 세금·카드·보험·급여", 5), "down")
        self.assertEqual(live.change_class("곧 낼 세금·카드·보험·급여", -5), "up")
        self.assertEqual(live.change_class("통장 잔액", 5), "up")
        self.assertEqual(live.change_class("가 예상 이익", -1), "down")

    def test_rendered_page(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        path, _ = live.build(SAMPLE, out, dt.date(2026, 11, 6), dt.datetime(2026, 11, 12, 9, 0))
        hist = os.path.join(out, live.HISTORY)
        with open(hist, encoding="utf-8") as f:
            h = json.load(f)
        h[-1]["tax_total"] = (h[-1]["tax_total"] or 0) - 1000000
        with open(hist, "w", encoding="utf-8") as f:
            json.dump(h, f, ensure_ascii=False)
        path, diff = live.build(SAMPLE, out, dt.date(2026, 11, 6), dt.datetime(2026, 11, 12, 10, 0))
        with open(path, encoding="utf-8") as f:
            page = f.read()
        m = re.search(r"<li>곧 낼 세금[^<]*: [^<]*<b>[^<]*</b> <span class='(\w+)'>\(\+", page)
        self.assertTrue(m, page[:3000])
        self.assertEqual(m.group(1), "down")

    def test_negative_total_is_refund_not_red_number(self):
        """30: 합계가 음수면 낼 돈인지 돌려받을 돈인지 알 수 없는 빨강 숫자 대신 '환급 예상 — 확인 필요'."""
        k, v, s, cls = live.tax_card(-15440000)
        self.assertIn("환급 예상", v)
        self.assertIn("15,440,000", v)
        self.assertIn("확인 필요", s)
        self.assertEqual(cls, "est")
        k, v, s, cls = live.tax_card(3000)
        self.assertEqual((v, cls), ("3,000", ""))


class TestItem31FilingHelp(unittest.TestCase):
    def R(self, month, filing):
        end = dt.date(2026, month, 28)
        return {"kind": "monthly", "period": (dt.date(2026, month, 1), end), "asof": end, "filing": filing,
                "filing_help": "<h2>신고 도우미</h2><p>칸별 값</p>"}

    def test_month_with_filing_gets_helper(self):
        """31: 분기 달이 아니어도 이번 달 기한 신고가 있으면(원천세 등) 월간 경영관리에 신고 도우미가 붙는다."""
        from ceo_report import render
        fl = [{"기한": "2026-11-10", "신고": "원천세", "대상": "10월분", "상태": "", "장부 근거": "예수금", "어디서": "홈택스"}]
        R = self.R(10, fl)
        P = digest.periodic(R)
        self.assertIn("f", P)
        self.assertNotIn("q", P)
        keys = [k for k, _, _ in render._periodic(R, P)]
        self.assertEqual(keys, ["c2", "c6"])   # C-6 감면·공제 검토는 매달 (2026-11-17)
        body = render._periodic(R, P)[0][2]
        self.assertIn("신고 도우미", body)
        self.assertIn("칸별 값", body)
        self.assertNotIn("(분기)", body)
        # 신고가 없는 달엔 붙지 않고, 분기 달은 예전 그대로
        self.assertEqual(digest.periodic(self.R(10, [])), set())
        self.assertEqual(digest.periodic(self.R(9, fl)), {"q", "prep"})
        self.assertIn("c2", [k for k, _, _ in render._periodic(self.R(9, fl), {"q", "prep"})])

    def test_no_text_points_to_missing_window_button(self):
        """31: 창에는 '신고 도우미' 단추가 없다 — 안내는 실제 있는 곳(월간 경영관리 부록 C-2)을 가리킨다."""
        for name in ("digest.py", "mgmt_topics.py"):
            with open(os.path.join(ROOT, "ceo_report", name), encoding="utf-8") as f:
                src = f.read()
            self.assertNotIn("신고 도우미는 창에서", src, name)
            self.assertNotIn("창 ‘신고 도우미’", src, name)
        fl = [{"기한": "2026-11-10", "신고": "원천세", "대상": "10월분", "상태": "", "장부 근거": "예수금", "어디서": "홈택스"}]
        self.assertIn("부록 C-2", digest.filing_where(self.R(10, fl)))
        wk = dict(self.R(10, fl), kind="weekly")
        self.assertIn("월간 경영관리 보고", digest.filing_where(wk))


class TestItem33LiveStale(unittest.TestCase):
    def test_live_is_stale_when_schedule_input_changed(self):
        """33: '장부에 없는 지급·입금 예정'(자금일정.csv)을 고친 뒤 '지금 현황'을 열면 예전 화면이 아니라 새로 만든다."""
        from ceo_report import winstate
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        P = app.Paths(root)
        os.makedirs(P.input)
        os.makedirs(P.output)
        page = os.path.join(P.output, live.FILE)
        touch(page, T0, "<html>")
        self.assertFalse(winstate.live_stale(P))
        touch(os.path.join(P.input, "자금일정.csv"), sec(60), "x")
        self.assertTrue(winstate.live_stale(P))
        touch(page, sec(120), "<html>")
        self.assertFalse(winstate.live_stale(P))
        os.remove(page)
        self.assertTrue(winstate.live_stale(P))

    def test_card_text_says_next_report(self):
        with open(os.path.join(ROOT, "ceo_report", "gui.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("가용자금에 바로 반영", src)
        self.assertIn("다음 보고부터 반영", src)


if __name__ == "__main__":
    unittest.main()
