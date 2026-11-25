"""2026-11-17 편의성 남은 17건 (문서 번호 21·32·34~48) 중 창 밖에서 확인할 수 있는 것. 가상 자료만."""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import editmode, gate, winstate  # noqa: E402

OPEN = urllib.request.build_opener(urllib.request.ProxyHandler({})).open
PAGE = "<!doctype html><html><head><title>t</title></head><body><h1>매출 100원</h1></body></html>"


def get(url):
    try:
        with OPEN(url, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {}


def post(url, body):
    req = urllib.request.Request(url, data=body.encode("utf-8"), method="POST",
                                 headers={"Content-Type": "text/html; charset=utf-8"})
    try:
        with OPEN(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


class Caret45(unittest.TestCase):
    def test_caret_stays_after_digit_count(self):
        self.assertEqual(winstate.caret_after_money("1,2345,67", "1,234,567", 5), 5)   # '1,234|' 그대로
        self.assertEqual(winstate.caret_after_money("12345", "12,345", 5), 6)          # 끝이면 끝
        self.assertEqual(winstate.caret_after_money("1,23945", "123,945", 5), 5)       # '123,9|'
        self.assertEqual(winstate.caret_after_money("5", "5", 0), 0)


class EditMode32and48(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.src = os.path.join(self.d, "2026-11-02_주간_대표보고.html")
        with open(self.src, "w", encoding="utf-8") as f:
            f.write(PAGE)
        self.fail_pdf = None
        self.s = editmode.Session(self.src, editmode.edited_path(self.src), lambda h, p: self.fail_pdf)
        self.url = self.s.start()
        self.addCleanup(self.s.stop)
        self.base = self.url.rsplit("/", 1)[0]

    def test_bar_says_totals_not_recalculated(self):
        with OPEN(self.url, timeout=10) as r:
            page = r.read().decode("utf-8")
        self.assertIn("합계·비율·근거자료는 다시 계산되지 않습니다", page)
        self.assertIn("edit-stale", page)
        self.assertNotIn("edit-stale", editmode.strip(page))

    def test_html_saved_pdf_failed_is_told_apart(self):
        self.fail_pdf = "브라우저 없음"
        with OPEN(self.url, timeout=10) as r:
            page = r.read().decode("utf-8")
        st, r = post(self.base + "/save?k=" + self.s.key, page)
        self.assertFalse(r["ok"])
        self.assertTrue(r["html"])
        self.assertTrue(r["msg"].startswith("HTML 저장됨 / PDF 못 만듦"))
        self.assertTrue(os.path.isfile(editmode.edited_path(self.src)))

    def test_state_tells_when_original_changed(self):
        self.assertEqual(get(self.base + "/state?k=" + self.s.key), (200, {"stale": False}))
        self.assertEqual(get(self.base + "/state?k=bad")[0], 403)
        time.sleep(0.02)
        with open(self.src, "w", encoding="utf-8") as f:
            f.write(PAGE.replace("100", "1000"))
        self.assertEqual(get(self.base + "/state?k=" + self.s.key), (200, {"stale": True}))


class Checklist21(unittest.TestCase):
    def test_state_endpoint_and_old_tab_note(self):
        from ceo_report import checklist
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        inp = os.path.join(d, "입력")
        shutil.copytree(os.path.join(ROOT, "입력양식", "샘플"), inp)
        s = checklist.Session(d, inp, dt.date(2026, 11, 2))
        url = s.start()
        self.addCleanup(s.stop)
        with OPEN(url, timeout=30) as r:
            page = r.read().decode("utf-8")
        self.assertIn("이 탭은 닫으세요", page)
        self.assertIn("다시 모으기", page)
        base = url.rsplit("/", 1)[0]
        self.assertEqual(get(base + "/state?k=" + s.key), (200, {"changed": False}))
        self.assertEqual(get(base + "/state?k=bad")[0], 403)


class Texts35and44(unittest.TestCase):
    def test_gate_stop_page_points_to_report_buttons(self):
        page = gate.stop_page("대표 보고", ["자금계획서가 없습니다"])
        self.assertIn("주간·월간 보고 단추를 누르면", page)
        self.assertNotIn("자료 변환을 다시 하면 만들어집니다", page)

    def test_no_old_window_numbers_in_messages(self):
        import glob
        import re
        bad = re.compile(r"창 [②⑥⑦⑧⑨]|'⑧ 팀 목표'|⑥ 이체 파일 만들기")
        for f in glob.glob(os.path.join(ROOT, "ceo_report", "*.py")):
            with open(f, encoding="utf-8") as h:
                for i, line in enumerate(h, 1):
                    if line.lstrip().startswith("#"):
                        continue
                    code = line.split("  #", 1)[0]
                    self.assertIsNone(bad.search(code), "%s:%d %s" % (os.path.basename(f), i, line.strip()[:80]))


class Live36(unittest.TestCase):
    def test_live_is_remade_when_window_date_differs(self):
        from ceo_report import live
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)

        class P:
            input = os.path.join(d, "입력")
            output = os.path.join(d, "출력")
        os.makedirs(P.input)
        os.makedirs(P.output)
        with open(os.path.join(P.output, live.FILE), "w", encoding="utf-8") as f:
            f.write("<html><header><h1>지금 현황 · 2026-10-31 기준</h1></header></html>")
        self.assertEqual(live.page_asof(os.path.join(P.output, live.FILE)), "2026-10-31")
        self.assertTrue(winstate.live_stale(P, "2026-11-16"))
        self.assertFalse(winstate.live_stale(P, "2026-10-31"))


if __name__ == "__main__":
    unittest.main()
