"""2026-11-17 결정 카드 A: 프로그램 '위하고에서 받기' 단추 → 크롬 표시 주소 → 확장 '모두 받기'. 모두 가상 자료."""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import app, winstate  # noqa: E402

T0 = dt.datetime(2026, 11, 17, 10, 0, 0)
BG = os.path.join(ROOT, "chrome_extension", "background.js")


def touch(path, when, text="{}"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.utime(path, (when.timestamp(), when.timestamp()))


class TestStart(unittest.TestCase):
    def test_opens_trigger_url_in_chrome_only(self):
        calls = []
        ok, text = app.start_wehago_collect(chrome="C:/chrome.exe", popen=calls.append)
        self.assertTrue(ok)
        self.assertEqual(calls, [["C:/chrome.exe", app.WEHAGO_TRIGGER]])
        self.assertIn("자동 반영", text)

    def test_same_url_as_extension(self):
        with open(BG, encoding="utf-8") as f:
            self.assertIn('const TRIGGER = "%s"' % app.WEHAGO_TRIGGER, f.read())

    def test_no_chrome_says_what_to_do(self):
        self.assertIsNone(app.find_chrome(env={}, exists=lambda p: False, which=lambda n: None))
        orig = app.find_chrome
        app.find_chrome = lambda: None
        try:
            ok, text = app.start_wehago_collect(popen=lambda a: self.fail("열면 안 됨"))
        finally:
            app.find_chrome = orig
        self.assertFalse(ok)
        self.assertIn("모두 받기", text)

    def test_popen_error_is_words_not_traceback(self):
        def boom(a):
            raise OSError(2, "없음")
        ok, text = app.start_wehago_collect(chrome="x", popen=boom)
        self.assertFalse(ok)
        self.assertIn("크롬을 열지 못함", text)

    def test_finds_user_chrome_not_edge(self):
        env = {"LOCALAPPDATA": "/u"}
        want = os.path.join("/u", "Google", "Chrome", "Application", "chrome.exe")
        self.assertEqual(app.find_chrome(env=env, exists=lambda p: p == want, which=lambda n: None), want)
        self.assertIsNone(app.find_chrome(env={}, exists=lambda p: "Edge" in p, which=lambda n: None))


class TestFailShown(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.P = app.Paths(self.root)
        os.makedirs(self.P.input)

    def mark(self, when, **d):
        touch(os.path.join(self.P.wehago, app.MARK_FILE), when, json.dumps(d, ensure_ascii=False))

    def test_error_from_extension_shown_red(self):
        self.mark(T0, **{"상태": "끝", "못받음": 1, "오류": "위하고 회계(SmartA) 화면이 열려 있지 않음"})
        st = app.auto_state(self.P, T0 + dt.timedelta(seconds=30), dirs=[])
        self.assertEqual(st["state"], "none")
        self.assertIn("SmartA", st["text"])
        text, kind, retry = winstate.auto_line(st)
        self.assertEqual(kind, "bad")
        self.assertFalse(retry)

    def test_old_error_or_no_error_is_quiet(self):
        self.mark(T0, **{"상태": "끝", "못받음": 1, "오류": "x"})
        self.assertEqual(app.auto_state(self.P, T0 + dt.timedelta(hours=1), dirs=[])["text"], "새 자료 없음")
        self.mark(T0, **{"상태": "끝", "못받음": 0})   # 예전 확장(오류 칸 없음)
        self.assertEqual(app.auto_state(self.P, T0 + dt.timedelta(seconds=30), dirs=[])["text"], "새 자료 없음")


@unittest.skipUnless(shutil.which("node"), "node 없음")
class TestExtensionTrigger(unittest.TestCase):
    def run_sim(self, scenario):
        out = subprocess.run(["node", os.path.join(HERE, "js", "trigger_sim.js"), scenario],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout.strip().splitlines()[-1])

    def test_program_tab_starts_collect_all_once_and_closes(self):
        r = self.run_sim("normal")
        self.assertEqual(r["collectAll"], 1)
        self.assertEqual(r["months"], 3)
        self.assertEqual(r["removed"], [5])

    def test_program_tab_works_long_after_extension_woke(self):
        self.assertEqual(self.run_sim("late")["collectAll"], 1)

    def test_second_press_while_busy_only_closes_tab(self):
        r = self.run_sim("double")
        self.assertEqual(r["collectAll"], 1)
        self.assertEqual(sorted(r["removed"]), [5, 6])

    def test_page_opened_tab_ignored(self):
        r = self.run_sim("opener")
        self.assertEqual((r["collectAll"], r["removed"]), (0, []))

    def test_existing_tab_navigating_ignored(self):
        r = self.run_sim("existing")
        self.assertEqual((r["collectAll"], r["removed"]), (0, []))

    def test_no_smarta_tab_writes_reason_and_opens_wehago(self):
        r = self.run_sim("nosmarta")
        self.assertEqual(r["collectAll"], 0)
        self.assertEqual(r["created"], ["https://www.wehago.com/"])
        self.assertEqual(r["marks"][-1]["상태"], "끝")
        self.assertIn("로그인", r["marks"][-1]["오류"])


if __name__ == "__main__":
    unittest.main()
