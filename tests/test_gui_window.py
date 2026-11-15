"""실제 창(tkinter)을 띄워 보는 시험 — 화면이 있는 곳에서만 (CEO_REPORT_GUI_TEST=1, 예: xvfb-run python3.12 -m unittest tests.test_gui_window).
2차 P6-7 (2026-11-15): 세법 기준 확인 창을 닫은 뒤 '자료 변환'을 누르면 오류가 나고 그 뒤 모든 단추가 안 먹었다."""
import datetime as dt
import os
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@unittest.skipUnless(os.environ.get("CEO_REPORT_GUI_TEST") == "1", "화면 시험은 CEO_REPORT_GUI_TEST=1 일 때만")
class TestClosedSubwindowDoesNotFreeze(unittest.TestCase):
    def test_convert_after_closing_law_window(self):
        import tkinter as tk
        from ceo_report import app, gui
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        shutil.copytree(os.path.join(ROOT, "입력양식", "샘플"), os.path.join(d, "입력"))
        os.makedirs(os.path.join(d, "출력"))
        os.makedirs(os.path.join(d, "수집", "위하고"))
        root = tk.Tk()
        self.addCleanup(root.destroy)
        w = gui.Window(root, paths=app.Paths(d), today=dt.date(2026, 11, 13))
        root.update()
        calls = []
        real = app.run_task
        app.run_task = lambda *a, **k: (calls.append(a[0]), (0, []))[1]
        self.addCleanup(setattr, app, "run_task", real)
        w.open_law()
        root.update()
        w.law_win.destroy()
        root.update()
        w.start("변환")   # 예전엔 여기서 TclError
        for _ in range(50):
            root.update()
            if calls:
                break
        self.assertEqual(calls[:1], ["변환"])


    def test_account_save_twice_keeps_account(self):
        """2차 P5-1: 저장 뒤 칸이 빈 채로 '저장'을 다시 누르면 그 거래처 계좌가 모두 지워졌다."""
        import tkinter as tk
        from ceo_report import app, gui, transfer
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        shutil.copytree(os.path.join(ROOT, "입력양식", "샘플"), os.path.join(d, "입력"))
        os.makedirs(os.path.join(d, "출력"))
        os.makedirs(os.path.join(d, "수집", "위하고"))
        root = tk.Tk()
        self.addCleanup(root.destroy)
        w = gui.Window(root, paths=app.Paths(d), today=dt.date(2026, 11, 13))
        root.update()
        w.a_code.set("000777")
        w.a_name.set("가상업체")
        w.a_bank.set("신한")
        w.a_no.set("100-000-000777")
        w.a_holder.set("가상업체")
        w.save_account()
        w.save_account()   # 칸이 비었는데 다시 저장
        rows, _ = transfer._read_rows(os.path.join(d, "입력"))
        self.assertTrue(any(r["계좌번호"] == "100-000-000777" for r in rows))


if __name__ == "__main__":
    unittest.main()
