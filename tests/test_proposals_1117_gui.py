"""2026-11-17 제안 A6('이렇게 하면?')·A4/A5('자금 선택') 창 — 실제 창(tkinter)으로 확인 (CEO_REPORT_GUI_TEST=1, xvfb). 가상 자료만."""
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_usability_1116_gui import GUI, GuiCase  # noqa: E402


@unittest.skipUnless(GUI, "화면 시험은 CEO_REPORT_GUI_TEST=1 일 때만")
class TestChoicesAndWhatif(GuiCase):
    def test_rare_list_has_new_panels(self):
        self.assertIn("이렇게 하면?", self.gui.RARE)
        self.assertIn("자금 선택", self.gui.RARE)
        self.w.pick_rare("자금 선택")
        self.root.update()

    def test_save_choices(self):
        from ceo_report import choices
        self.w.fc_inst.set(True)
        self.w.fc_rate.set("3.5")
        self.w.save_choices()
        self.assertEqual(choices.read(self.P.input), {"법인세분납": "예", "예금금리": "3.5"})
        self.assertIn("분납 함", self.w.rare_status("자금 선택"))
        self.w.fc_rate.set("abc")
        self.w.save_choices()
        self.assertIn("저장하지 못함", self.w.fc_now.get())

    def test_whatif_runs_without_saving(self):
        before = sorted(os.listdir(self.P.input))
        self.w.wi_kind.set("한 번 지출")
        self.w.wi_amt.set("5,000,000")
        self.w.whatif_run()
        for _ in range(300):
            self.w.pump()
            self.root.update()
            if self.w.wi_out.get() not in ("", "계산 중…"):
                break
            time.sleep(0.05)
        out = self.w.wi_out.get()
        self.assertNotIn("계산 중", out)
        self.assertTrue("여유 자금" in out or "계산하지 못함" in out or "자료가 없어" in out, out)
        self.assertEqual(sorted(os.listdir(self.P.input)), before)


if __name__ == "__main__":
    unittest.main()
