"""2026-11-17 사용자: 감면·공제 '받음' 체크가 '배당 판단 질문' 창 안에 숨어 있어 못 찾음 → 목록에 '법인세 감면·공제'로 따로.
가상 자료만."""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import app, dividend, taxbreak  # noqa: E402

GUI = os.environ.get("CEO_REPORT_GUI_TEST") == "1"


class PickStates(unittest.TestCase):
    def test_defaults_last_year_on_new_off(self):
        rows = dict((n, ok) for n, ok, _ in taxbreak.pick_states({}))
        self.assertTrue(rows["중소기업 특별세액감면 (작년 신고서 비율)"])
        self.assertTrue(rows["작년에서 넘어온 세액공제"])
        self.assertFalse(rows["올해 통합고용 세액공제"])
        self.assertEqual(len(rows), 6)

    def test_own_choice_and_rule(self):
        rows = dict((n, ok) for n, ok, _ in taxbreak.pick_states({"반영_고용": "받음", "반영_특별감면": "안 받음"}))
        self.assertTrue(rows["올해 통합고용 세액공제"])
        self.assertFalse(rows["중소기업 특별세액감면 (작년 신고서 비율)"])
        rows = dict((n, ok) for n, ok, _ in taxbreak.pick_states({"반영기본": "계산된 것만"}))
        self.assertTrue(rows["올해 통합고용 세액공제"])          # 법령 금액으로 계산되는 것
        self.assertFalse(rows["통합투자 세액공제"])              # 세무사 인정 범위 확인 전

    def test_states_match_what_tax_calc_uses(self):
        """창에 보이는 '넣음'과 실제 계산(chosen)이 같은 규칙인지."""
        for a in ({}, {"반영기본": "모두 받음"}, {"반영기본": "계산된 것만", "반영_투자": "받음"}, {"반영_연구": "안 받음"}):
            shown = dict((n, ok) for n, ok, _ in taxbreak.pick_states(a))
            for name, k, _, _, _ in taxbreak.PICK:
                ok, _ = taxbreak.chosen(a, name, "해당", 1000)
                self.assertEqual(ok, shown[taxbreak.PICK_LABEL[k]], (a, name))


class GroupSave(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_tax_window_saves_without_dividend_answers(self):
        """감면 창은 감면 묶음의 ★만 막고, 배당 질문이 비어 있어도 저장된다."""
        need = [k for k, g, _, _, _, dflt, n in dividend.QUESTIONS if g == dividend.TAX_GROUP and n and not dflt]
        vals = dict((k, dict((q[0], q[4]) for q in dividend.QUESTIONS)[k][0]) for k in need)
        vals["반영_고용"] = "받음"
        app.save_holder_settings(self.d, vals, group=dividend.TAX_GROUP)
        self.assertEqual(dividend.read_settings(self.d)["반영_고용"], "받음")
        self.assertIn("올해 통합고용 세액공제", app.taxbreak_text(self.d).split("\n")[0])
        self.assertEqual(app.taxbreak_count(self.d), "넣는 것 3개")

    def test_tax_window_blocks_its_own_required(self):
        with self.assertRaises(ValueError):
            app.save_holder_settings(self.d, {"반영_고용": "받음"}, group=dividend.TAX_GROUP)

    def test_dividend_text_does_not_count_tax_questions(self):
        miss_all = dividend.missing_required({})
        miss_div = dividend.missing_required({}, exclude=dividend.TAX_GROUP)
        self.assertLess(len(miss_div), len(miss_all))
        self.assertNotIn("감면", app.question_text(self.d))


@unittest.skipUnless(GUI, "화면 시험은 CEO_REPORT_GUI_TEST=1 일 때만")
class Window(unittest.TestCase):
    def setUp(self):
        import datetime as dt
        import tkinter as tk
        from unittest import mock
        from ceo_report import gui
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        shutil.copytree(os.path.join(ROOT, "입력양식", "샘플"), os.path.join(self.d, "입력"))
        os.makedirs(os.path.join(self.d, "출력"))
        os.makedirs(os.path.join(self.d, "수집", "위하고"))
        self.P = app.Paths(self.d)
        p = mock.patch.object(app, "chrome_download_dirs", lambda env=None: [])
        p.start()
        self.addCleanup(p.stop)
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.w = gui.Window(self.root, paths=self.P, today=dt.date(2026, 11, 17))
        self.root.update()

    def test_list_has_tax_item_and_window_shows_only_tax_questions(self):
        w = self.w
        self.assertIn("법인세 감면·공제", w.rare_names)
        w.pick_rare("법인세 감면·공제")
        w.open_taxbreak()
        self.root.update()
        self.assertEqual(w.q_win.title(), "법인세 감면·공제 고르기")
        groups = set(dividend.GROUP_OF[k] for k in w.q_vars)
        self.assertEqual(groups, {dividend.TAX_GROUP})
        self.assertIn("반영_고용", w.q_vars)
        w.open_questions()   # 배당 질문 창으로 바꾸면 감면 칸은 없음
        self.root.update()
        self.assertEqual(w.q_win.title(), "배당 판단 질문")
        self.assertNotIn("반영_고용", w.q_vars)
        self.assertNotIn(dividend.TAX_GROUP, set(dividend.GROUP_OF[k] for k in w.q_vars))

    def test_save_in_tax_window_updates_status(self):
        w = self.w
        w.open_taxbreak()
        self.root.update()
        for k, g, _, kind, opts, dflt, need in dividend.QUESTIONS:
            if k in w.q_vars and need and not w.q_vars[k].get():
                w.q_vars[k].set(opts[0])
        w.q_vars["반영_고용"].set("받음")
        w.save_questions()
        self.root.update()
        self.assertEqual(dividend.read_settings(self.P.input)["반영_고용"], "받음")
        self.assertIn("올해 통합고용 세액공제", w.tb_now.get().split("\n")[0])
        self.assertTrue(w.rare_status("법인세 감면·공제").startswith("넣는 것"))


if __name__ == "__main__":
    unittest.main()
