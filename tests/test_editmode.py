"""수정 모드 (사용자 2026-11-04): 대표 보고를 브라우저에서 고치고 _수정 HTML·PDF 로 저장."""
import json
import os
import shutil
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from ceo_report import editmode

OPEN = urllib.request.build_opener(urllib.request.ProxyHandler({})).open   # 이 컴퓨터 안 주소: 프록시 안 씀
PAGE = "<!doctype html><html><head><title>t</title></head><body class='b'><h1>매출 100원</h1></body></html>"


def post(url, body):
    req = urllib.request.Request(url, data=body.encode("utf-8"), method="POST",
                                 headers={"Content-Type": "text/html; charset=utf-8"})
    try:
        with OPEN(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {}


class TestFiles(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, True)

    def touch(self, name, t):
        p = os.path.join(self.d, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(PAGE)
        os.utime(p, (t, t))
        return p

    def test_latest_and_edited_continue(self):
        self.assertEqual(editmode.latest_report(self.d, "주간"), (None, None))
        self.touch("2026-10-26_주간_대표보고.html", 100)
        new = self.touch("2026-11-02_주간_대표보고.html", 200)
        self.touch("2026-11-02_주간_경영관리보고.html", 300)
        self.assertEqual(editmode.latest_report(self.d, "주간"), (new, new))
        ed = self.touch("2026-11-02_주간_대표보고_수정.html", 250)
        self.assertEqual(editmode.latest_report(self.d, "주간"), (new, ed))
        os.utime(new, (400, 400))   # 보고서를 다시 만들면 예전 수정본은 쓰지 않는다
        self.assertEqual(editmode.latest_report(self.d, "주간"), (new, new))
        self.assertEqual(editmode.latest_report(self.d, "월간"), (None, None))

    def test_paths(self):
        self.assertEqual(editmode.edited_path("a/x_대표보고.html"), "a/x_대표보고_수정.html")
        self.assertEqual(editmode.original_path("a/x_대표보고_수정.html"), "a/x_대표보고.html")

    def test_inject_strip_roundtrip(self):
        page = editmode.inject(PAGE, "KEY")
        self.assertIn("edit-bar", page)
        self.assertIn('"KEY"', page)
        self.assertLess(page.index("<body"), page.index("edit-bar"))
        out = editmode.strip(page.replace("<body class='b'>", "<body class='b' contenteditable=\"true\">"))
        self.assertEqual(out, PAGE)
        # 브라우저가 띠를 남긴 채(표시 없이) 보내도 뺀다
        leftover = PAGE.replace("<h1>", '<div id="edit-bar" contenteditable="false"><b>수정 모드</b></div><h1>')
        self.assertEqual(editmode.strip(leftover), PAGE)


class TestServer(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.src = os.path.join(self.d, "2026-11-02_주간_대표보고.html")
        with open(self.src, "w", encoding="utf-8") as f:
            f.write(PAGE)
        self.saved = []

        def make_pdf(html, pdf):
            with open(pdf, "wb") as f:
                f.write(b"%PDF")
            return None
        self.s = editmode.Session(self.src, editmode.edited_path(self.src), make_pdf,
                                  on_saved=lambda pdf, t: self.saved.append(pdf))
        self.url = self.s.start()

    def tearDown(self):
        self.s.stop()
        shutil.rmtree(self.d, True)

    def test_get_save_close(self):
        self.assertTrue(self.url.startswith("http://127.0.0.1:"))
        with OPEN(self.url, timeout=10) as r:
            page = r.read().decode("utf-8")
        self.assertIn("저장하고 PDF 만들기", page)
        base = self.url.rsplit("/", 1)[0]
        st, r = post(base + "/save?k=" + self.s.key, page.replace("매출 100원", "매출 120원"))
        self.assertEqual((st, r["ok"]), (200, True))
        ed = editmode.edited_path(self.src)
        with open(ed, encoding="utf-8") as f:
            got = f.read()
        self.assertIn("매출 120원", got)
        self.assertNotIn("edit-bar", got)
        self.assertNotIn("contenteditable", got)
        with open(self.src, encoding="utf-8") as f:
            self.assertIn("매출 100원", f.read())      # 원래 보고서는 그대로
        self.assertTrue(os.path.isfile(os.path.splitext(ed)[0] + ".pdf"))
        self.assertEqual(len(self.saved), 1)
        # 다시 열면 고친 것부터
        with OPEN(self.url, timeout=10) as r:
            self.assertIn("매출 120원", r.read().decode("utf-8"))
        st, _ = post(base + "/close?k=" + self.s.key, "")
        self.assertEqual(st, 200)
        for _ in range(50):
            if self.s.server is None:
                break
            time.sleep(0.05)
        self.assertIsNone(self.s.server)

    def test_wrong_key_refused(self):
        base = self.url.rsplit("/", 1)[0]
        st, _ = post(base + "/save?k=bad", PAGE)
        self.assertEqual(st, 403)
        self.assertFalse(os.path.exists(editmode.edited_path(self.src)))
        with self.assertRaises(urllib.error.HTTPError):
            OPEN(base + "/other", timeout=10)

    def test_not_html_refused(self):
        base = self.url.rsplit("/", 1)[0]
        st, r = post(base + "/save?k=" + self.s.key, "hello")
        self.assertEqual(st, 500)
        self.assertFalse(os.path.exists(editmode.edited_path(self.src)))


if __name__ == "__main__":
    unittest.main()
