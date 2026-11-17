"""2026-11-16 편의성 개선 — 실제 창(tkinter)으로 확인 (CEO_REPORT_GUI_TEST=1, xvfb). 번호는 편의성 제안 문서의 번호.
운영-03(출금일 표시)·운영-05(드문 카드는 목록에서 골라 입력, 한 화면)의 '확인'도 여기. 모두 가상 자료."""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

GUI = os.environ.get("CEO_REPORT_GUI_TEST") == "1"
MON, FRI = dt.date(2026, 11, 16), dt.date(2026, 11, 20)


@unittest.skipUnless(GUI, "화면 시험은 CEO_REPORT_GUI_TEST=1 일 때만")
class GuiCase(unittest.TestCase):
    today = MON

    def setUp(self):
        import tkinter as tk
        from ceo_report import app, gui
        self.app, self.gui = app, gui
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        shutil.copytree(os.path.join(ROOT, "입력양식", "샘플"), os.path.join(self.d, "입력"))
        os.makedirs(os.path.join(self.d, "출력"))
        os.makedirs(os.path.join(self.d, "수집", "위하고"))
        self.P = app.Paths(self.d)
        p = mock.patch.object(app, "chrome_download_dirs", lambda env=None: [])
        p.start()
        self.addCleanup(p.stop)
        self.prepare()
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.w = gui.Window(self.root, paths=self.P, today=self.today)
        self.root.update()

    def prepare(self):
        pass

    def pump(self, n=20):
        import time
        for _ in range(n):
            self.root.update()
            time.sleep(0.01)

    def stop_page(self, kind="주간", day=None):
        from ceo_report import gate
        p = os.path.join(self.P.output, "%s_%s_대표보고.html" % ((day or self.today).isoformat(), kind))
        with open(p, "w", encoding="utf-8") as f:
            f.write(gate.stop_page("대표 보고", ["자금계획서가 없습니다"]))
        return p

    def converted(self):
        """자료를 받고 변환까지 끝낸 상태 (3단계 차례)."""
        import time
        from ceo_report import checklist
        j = os.path.join(self.P.wehago, "261116 분개장 자동수집.json")
        with open(j, "w", encoding="utf-8") as f:
            f.write("{}")
        old = time.time() - 3600
        os.utime(j, (old, old))
        c = os.path.join(self.P.input, checklist.CONVERT_FILE)
        with open(c, "w", encoding="utf-8") as f:
            f.write("{}")
        old = time.time() - 1800
        os.utime(c, (old, old))


class TestItem1And2Blocked(GuiCase):
    def test_blocked_week_is_red_not_done(self):
        """1: 막혀 '만들지 않음' 안내만 생긴 주엔 3단계가 초록 '완료'가 아니라 빨강, 열기 단추는 '까닭 보기'."""
        self.converted()
        self.stop_page()
        self.w.refresh_state()
        chip = self.w.s3.chip
        self.assertIn("보고 만들지 않음", chip.cget("text"))
        self.assertEqual(chip.cget("background"), self.gui.C["chip_bad"][0])
        self.assertEqual(self.w.open_ceo.cget("text"), "까닭 보기")

    def test_gate_line_before_pressing(self):
        """2: 누르기 전에 주간 보고 단추 위에 '대표 보고: 만들 수 있음 / 막힘 — 까닭 → 할 일'."""
        self.w.apply_gate(self.w.asof_date(), {"problems": ["자금계획서가 없습니다 — 위하고에서 받으세요"], "book_date": None, "plan_date": None})
        self.assertIn("막힘", self.w.gate_info.get())
        self.assertEqual(str(self.w.gate_lab.cget("foreground")), self.gui.C["red"])
        self.w.apply_gate(self.w.asof_date(), {"problems": [], "book_date": MON, "plan_date": MON})
        self.assertIn("만들 수 있음", self.w.gate_info.get())
        # 다른 기준일로 계산한 결과는 쓰지 않는다
        self.w.apply_gate(dt.date(2026, 1, 1), {"problems": ["x"], "book_date": None, "plan_date": None})
        self.assertIn("만들 수 있음", self.w.gate_info.get())

    def test_convert_result_line_tells_gate(self):
        """2·8: 변환이 끝나면 맨 위 상태 줄이 막힌 까닭·다음 행동을 먼저 말한다."""
        with mock.patch.object(self.w, "refresh_gate"), mock.patch.object(self.w, "refresh_checks"):
            self.w.finish("변환", 0, [])
        self.w.apply_gate(self.w.asof_date(), {"problems": ["자금계획서가 없습니다"], "book_date": None, "plan_date": None})
        self.assertIn("막힘", self.w.status.get())
        self.assertIn("변환 완료", self.w.status.get())


class TestRuleOps03Friday(GuiCase):
    today = FRI

    def test_pay_line_and_today_button(self):
        """운영-03 (3): 기본 출금일은 그대로(다음 주 금요일), 주간 보고 단추 옆에 실제 출금일·이체 기간, 금요일엔 '오늘 출금용'."""
        self.assertEqual(self.w.payday.get(), "")
        self.assertIn("출금 11/27(금)", self.w.pay_info.get())
        self.assertIn("이체 11/21~11/27", self.w.pay_info.get())
        self.assertTrue(self.w.today_btn.winfo_manager())
        self.w.use_today_pay()
        self.assertEqual(self.w.asof.get(), "2026-11-19")
        self.assertIn("출금 11/20(금)", self.w.pay_info.get())
        self.assertFalse(self.w.today_btn.winfo_manager())


class TestItem4To6(GuiCase):
    def test_no_today_button_on_monday(self):
        self.assertFalse(self.w.today_btn.winfo_manager())

    def test_asof_follows_new_day_only_when_untouched(self):
        """4: 창을 켜 둔 채 날이 바뀌면 손대지 않은 기준일만 오늘로, 직접 고친 날짜는 그대로 '오늘과 다름'."""
        self.w.clock = lambda: dt.date(2026, 11, 17)
        self.w.tick_day()
        self.assertEqual(self.w.asof.get(), "2026-11-17")
        self.w.asof.set("2026-11-10")
        self.w.clock = lambda: dt.date(2026, 11, 18)
        self.w.tick_day()
        self.assertEqual(self.w.asof.get(), "2026-11-10")
        self.assertIn("오늘과 다름", self.w.asof_day.cget("text"))

    def test_counts_refresh_when_decision_saved(self):
        """5: 확인할 것에서 결정을 저장하면 창 건수를 바로 다시 센다."""
        from ceo_report import checklist
        made = {}

        class Fake(object):
            server = None

            def __init__(self, *a, **k):
                made.update(k)

            def start(self):
                return "http://127.0.0.1:1/"
        with mock.patch.object(checklist, "Session", Fake), mock.patch.object(self.gui.webbrowser, "open"):
            self.w.open_checklist()
        with mock.patch.object(self.w, "refresh_checks") as rc:
            made["on_counts"]({"open": 0})
            self.pump(30)
            self.assertTrue(rc.called)

    def test_only_one_blue_button(self):
        """6: 지금 할 단계의 한 동작만 파랑. 자료가 없는 첫 화면은 '인트라넷 자료 가져오기'."""
        blue = self.gui.C["blue"]
        self.w.refresh_state()
        on = [k for k, b in self.w.mains.items() if b.cget("background") == blue]
        self.assertEqual(on, ["collect"])
        # 작업 중이었다가 끝나도 그대로
        self.w.set_busy(True, "x")
        self.w.set_busy(False, "y")
        self.assertEqual([k for k, b in self.w.mains.items() if b.cget("background") == blue], ["collect"])


class TestItem7To9(GuiCase):
    def test_send_list(self):
        """7: 3단계 '만든 뒤'에 이번 기준일의 보낼 파일 5줄 (상태와 함께). 막힌 보고는 '막힘'."""
        self.stop_page()
        self.w.refresh_state()
        rows = [self.w.send_list.get(i) for i in range(self.w.send_list.size())]
        self.assertEqual(len(rows), 5)
        self.assertTrue(rows[0].startswith("주간 대표 — 막힘"))
        self.assertTrue(rows[1].startswith("월간 대표 — 없음"))
        self.assertTrue(rows[2].startswith("팀장용"))
        self.w.send_list.selection_set(0)
        with mock.patch.object(self.gui, "open_path", return_value=True) as op:
            self.w.open_send()
            self.assertTrue(op.call_args[0][0].endswith("주간_대표보고.html"))

    def test_log_folds_detail_lines(self):
        """8: 작업이 내는 자세한 글(파일마다 n줄 만듦)은 접어 두고, 경고·구분 줄은 늘 보인다. '자세히'를 켜면 다 보인다."""
        self.w.busy = True
        self.w.say("거래내역.csv 120줄 만듦")
        self.w.say("[확인] 자금계획서 없음")
        self.w.busy = False
        self.pump(15)
        ranges = self.w.log.tag_ranges("detail")
        self.assertEqual(len(ranges), 2)
        self.assertIn("120줄", self.w.log.get(ranges[0], ranges[1]))
        self.assertEqual(str(self.w.log.tag_cget("detail", "elide")), "1")
        self.w.log_all.set(True)
        self.w.toggle_log()
        self.assertEqual(str(self.w.log.tag_cget("detail", "elide")), "0")

    def test_cause_specific_error_line(self):
        self.w.finish("인트라넷", 5, [])
        self.assertIn("연결하지 못했습니다", self.w.status.get())
        self.w.finish("주간", 7, [], True)
        self.assertIn("변환이 아직 끝나지 않았습니다", self.w.status.get())

    def test_three_merge_modes(self):
        """9: '건별 / 모두 합침 / 고른 곳만 합침'을 따로 고른다. 고른 곳만 합침에 0곳이면 모두 합치지 않는다."""
        self.assertEqual([str(r.cget("value")) for r in self.w.merge_radios], ["건별", "거래처별", "고른곳만"])
        self.assertEqual([str(r.cget("text")) for r in self.w.merge_radios], ["건별", "모두 합침", "고른 곳만 합침"])
        self.w.group.set("고른곳만")
        self.w.only.set("")
        self.w.merge_changed()
        self.assertIn("고른 곳 없음", self.w.merge_info.get())
        self.assertNotIn("모두 합침", self.w.merge_info.get())
        self.assertEqual(self.app.load_merge(self.P), ("고른곳만", ""))
        self.w.group.set("거래처별")
        self.w.merge_changed()
        self.assertTrue(self.w.merge_btn.instate(["disabled"]))


class TestTransferOnFirstTab(GuiCase):
    def test_transfer_lives_in_step3(self):
        """10: 이체 파일 만들기는 첫 탭에 있다 — 사용자 2026-11-17 디자인부터는 보고를 만든 뒤인 4단계 '보내기'에."""
        self.assertTrue(str(self.w.t_btn).startswith(str(self.w.s4)))
        self.assertTrue(str(self.w.send_list).startswith(str(self.w.s4)))


class TestReaderDesignWindow(GuiCase):
    """사용자 2026-11-17: 왼쪽 띠에 네 단계, 가운데엔 지금 단계 하나만, 가끔 넣는 값은 왼쪽 목록에서 고른 것 하나만."""

    def test_one_step_at_a_time_and_size_stays(self):
        w = self.w
        self.assertEqual([r["title"].cget("text") for r in w.nav_rows], ["자료 모으기", "변환하고 확인", "보고 만들기", "보내기"])
        size = None
        for i in (1, 2, 3, 4):
            w.show_step(i)
            self.root.update()
            self.assertEqual([k for k, p in enumerate(w.step_pages, start=1) if p.winfo_ismapped()], [i])
            now = (self.root.winfo_reqwidth(), self.root.winfo_reqheight())
            self.assertEqual(size or now, now)
            size = now

    def test_left_line_shows_the_same_state_as_the_step(self):
        w = self.w
        w.refresh_state()
        for page, row in zip(w.step_pages, w.nav_rows):
            self.assertTrue(page.chip.cget("text"))
            self.assertEqual(row["sub"].cget("text"), page.chip.cget("text"))
        now = w.state["now"]
        self.assertEqual([r["state"] for r in w.nav_rows][:now], ["done"] * (now - 1) + ["now"])
        self.assertEqual(w.step_shown, now)   # 지금 할 차례인 단계가 열려 있다

    def test_tabs_are_two_buttons_and_left_list_follows(self):
        w = self.w
        w.seg[1].event_generate("<Button-1>")
        self.root.update()
        self.assertEqual(w.nb.index("current"), 1)
        self.assertEqual(w.seg[1].cget("background"), self.gui.C["card"])
        names = [n for _, ns in self.gui.ITEM_GROUPS for n in ns]
        self.assertEqual(sorted(w.item_rows), sorted(names))
        for name in names:
            w.pick_item(name)
            self.root.update()
            shown = [p for p in set(w.item_pages.values()) if p.winfo_ismapped()]
            self.assertEqual(shown, [w.item_pages[name]], name)
        w.pick_item("대출 만기")
        self.assertEqual(w.rare_now, "대출 만기")
        w.show_step(2)   # 단계를 누르면 '이번 주 할 일'로 돌아온다
        self.root.update()
        self.assertEqual(w.nb.index("current"), 0)

    def test_checklist_done_button_opens_step3(self):
        """확인할 것 화면의 '다 봤음 · 보고 만들러 가기' → 창이 3단계를 보인다."""
        w = self.w
        with mock.patch.object(self.gui.webbrowser, "open"), mock.patch.object(self.gui.checklist.Session, "start", return_value="http://x"):
            w.open_checklist()
        w.show_step(1)
        w.check.on_seen()
        self.pump()
        self.assertEqual(w.step_shown, 3)

    def test_dates_follow_payday_until_really_changed(self):
        """12: 지급일 칸은 날짜가 실제로 바뀔 때만 '직접 지정'. 키만 누르고 지나가면 출금일을 계속 따라간다."""
        self.assertEqual(self.w.t_mode.get(), "출금일 따라감")
        self.w.t_entries[0].event_generate("<Key>", keysym="Tab")
        self.w.payday.set("2026-11-27")
        self.assertEqual((self.w.t_from.get(), self.w.t_to.get()), ("2026-11-17", "2026-11-27"))
        self.w.t_to.set("2026-11-26")
        self.assertEqual(self.w.t_mode.get(), "직접 지정")
        self.w.payday.set("2026-12-04")
        self.assertEqual(self.w.t_to.get(), "2026-11-26")
        self.w.follow_payday()
        self.assertEqual(self.w.t_mode.get(), "출금일 따라감")
        self.assertEqual(self.w.t_to.get(), "2026-12-04")

    def test_result_stays_in_transfer_box(self):
        """11: 넣은 건수·합계·못 넣음·중복 의심을 이체 칸에 남기고, 중복 의심이면 빨강."""
        from ceo_report import transfer

        def fake(inp, out, start, end, say, **k):
            k["result"]["summary"] = {"n": 2, "total": 3300000, "rows": [], "blocked": [],
                                      "repeats": [("가상디자인", 1100000, "2026-11-13 10:00", "x.xlsx")]}
            return os.path.join(out, "이체.xlsx")
        with mock.patch.object(transfer, "make_file", fake), mock.patch.object(self.w, "open_dir"):
            self.w.make_transfer()
        self.assertIn("넣음 2건", self.w.t_result.get())
        self.assertIn("중복 의심 1건", self.w.t_result.get())
        self.assertEqual(str(self.w.t_result_lab.cget("foreground")), self.gui.C["red"])


class TestAccounts(GuiCase):
    def prepare(self):
        with open(os.path.join(self.P.input, "거래처계좌.csv"), "w", encoding="utf-8-sig") as f:
            f.write("거래처코드,거래처,은행,계좌번호,예금주\n000101,가상에이,신한,110-000-000101,가상에이\n"
                    "000202,가상비,국민,220-000-000202,가상비\n"
                    "000303,가상씨,신한,330-000-000301,김가나\n000303,가상씨,우리,330-000-000302,이다라\n")

    def rows(self):
        from ceo_report import transfer
        return transfer._read_rows(self.P.input)[0]

    def load(self, code):
        label = next(c[0] for c in self.w.account_rows if c[1] == code)
        self.w.a_pick.set(label)
        self.w.load_account()

    def test_changing_search_text_drops_target(self):
        """14: A를 불러온 뒤 위 칸에 B 이름을 치고 저장해도 A의 계좌가 바뀌지 않는다 (저장 대상이 풀리고 저장이 잠김)."""
        self.load("000101")
        self.assertIn("가상에이 [000101]", self.w.a_target.get())
        self.w.a_pick.set("가상비")
        self.assertEqual(self.w.a_code.get(), "")
        self.assertIn("저장 대상 없음", self.w.a_target.get())
        self.assertTrue(self.w.a_save.instate(["disabled"]))
        self.w.a_bank.set("우리")
        self.w.a_no.set("999-000-000999")
        self.w.a_holder.set("가상비")
        self.w.save_account()
        self.assertFalse(any(r["계좌번호"] == "999-000-000999" for r in self.rows()))
        self.assertTrue(any(r["계좌번호"] == "110-000-000101" for r in self.rows()))

    def test_multi_holder_pick_and_separate_deletes(self):
        """15: 예금주별로 골라 고치고, '이 계좌 지우기'와 '전부 지우기'는 따로 — 지우기 전에 한 번 묻는다."""
        self.load("000303")
        self.assertEqual(list(self.w.a_hbox.cget("values")), ["김가나", "이다라"])
        self.w.a_holder.set("이다라")
        self.w.pick_holder()
        self.assertEqual(self.w.a_no.get(), "330-000-000302")
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=False) as ask:
            self.w.delete_account()
            self.assertTrue(ask.called)
        self.assertEqual(len([r for r in self.rows() if r["거래처코드"] == "000303"]), 2)
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            self.w.delete_account()
        left = [r for r in self.rows() if r["거래처코드"] == "000303"]
        self.assertEqual([r["예금주"] for r in left], ["김가나"])
        # 예금주를 고르지 않으면 '이 계좌 지우기'는 아무것도 지우지 않는다 (전부 지우기는 따로)
        self.load("000101")
        self.w.a_holder.set("")
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            self.w.delete_account()
        self.assertTrue(any(r["거래처코드"] == "000101" for r in self.rows()))
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            self.w.delete_account(all_=True)
        self.assertFalse(any(r["거래처코드"] == "000101" and r["계좌번호"] for r in self.rows()))


class TestOccasional(GuiCase):
    def test_saved_values_fill_fields(self):
        """22: 연도·팀·카드사를 고르면 저장된 값이 칸에 채워진다. 빈칸으로 저장하면 그대로, 지울 땐 '지우기'."""
        from ceo_report import occasional
        self.app.save_team_target(self.P.input, "2031", "기획1팀", "900,000,000", "30")
        self.w.g_year.set("2031")
        self.w.g_team.set("기획1팀")
        self.assertEqual(self.w.g_rev.get(), "900,000,000")
        self.assertEqual(self.w.g_rate.get(), "30")
        self.w.g_rev.set("")
        self.w.g_rate.set("35")
        self.w.save_target()
        self.assertEqual(occasional.saved_target(self.P.input, "2031", "기획1팀"), ("900,000,000", "35"))
        self.w.delete_target()
        self.assertEqual(occasional.saved_target(self.P.input, "2031", "기획1팀"), ("", ""))
        # 감가상각비: 빈칸 저장은 그대로 (예전엔 지워짐)
        self.app.save_depreciation(self.P.input, "2031", "12,000,000")
        self.w.v_year.set("2031")
        self.assertEqual(self.w.v_amt.get(), "12,000,000")
        self.w.v_amt.set("")
        self.w.save_dep()
        self.assertEqual(occasional.saved_dep(self.P.input, "2031"), "12,000,000")
        self.w.delete_dep()
        self.assertEqual(occasional.saved_dep(self.P.input, "2031"), "")
        # 카드사
        self.app.save_card(self.P.input, "삼성", "13", "2")
        self.w.c_co.set("삼성")
        self.w.fill_card()
        self.assertEqual((self.w.c_pay.get(), self.w.c_start.get()), ("13", "2"))

    def test_budget_fill_and_blank_keeps(self):
        from ceo_report import occasional
        self.app.save_budget_values(self.P.input, "2031", [("성장률", "기획2팀", "7"), ("급여인상률", "", "3")])
        self.w.pick_rare("내년 예산")
        self.w.b_year.set("2031")
        self.w.b_team.set("기획2팀")
        self.assertEqual(self.w.b_grow.get(), "7")
        self.assertEqual(self.w.b_raise.get(), "3")
        self.w.b_grow.set("")
        self.w.save_budget_team()
        self.assertEqual(occasional.saved_budget(self.P.input, "2031", "기획2팀")["성장률"], "7")
        self.w.delete_budget_team()
        self.assertEqual(occasional.saved_budget(self.P.input, "2031", "기획2팀")["성장률"], "")

    def test_schedule_window_edits_and_deletes(self):
        """22: 지급·입금 예정은 창 안 목록(보조 창)에서 골라 고치고 지운다 (CSV를 열지 않음)."""
        from ceo_report import occasional
        self.app.add_schedule(self.P.input, "2026-11-30", "지급", "3,300,000", "예상", "가상업체", memo="시험")
        n0 = len(occasional.schedule_rows(self.P.input))
        self.w.open_schedule()
        self.root.update()
        labels = [self.w.sch_list.get(i) for i in range(self.w.sch_list.size())]
        i = next(k for k, t in enumerate(labels) if "가상업체" in t)
        self.w.sch_list.selection_set(i)
        self.w.sch_pick()
        self.assertEqual(self.w.sch_vars["금액"].get(), "3,300,000")
        self.w.sch_vars["금액"].set("4,400,000")
        self.w.sch_save()
        self.assertTrue(any("4,400,000" in occasional.schedule_label(r) for r in occasional.schedule_rows(self.P.input)))
        i = next(k for k in range(self.w.sch_list.size()) if "가상업체" in self.w.sch_list.get(k))
        self.w.sch_list.selection_clear(0, "end")
        self.w.sch_list.selection_set(i)
        self.w.sch_pick()
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True):
            self.w.sch_delete()
        self.assertEqual(len(occasional.schedule_rows(self.P.input)), n0 - 1)

    def test_loan_maturity_window(self):
        """23: '대출 만기' 보조 창에서 대출별 새 만기일·근거 메모를 넣는다."""
        from ceo_report import occasional
        self.w.open_maturity()
        self.root.update()
        self.assertGreaterEqual(self.w.mat_list.size(), 1)
        self.w.mat_list.selection_set(0)
        self.w.mat_pick()
        self.w.mat_vars["새만기일"].set("2028-04-17")
        self.w.mat_vars["메모"].set("")
        self.w.mat_save()
        self.assertIn("근거", self.w.mat_msg.get())
        self.w.mat_vars["메모"].set("2027-04 은행 연장 확인")
        self.w.mat_save()
        self.assertEqual(occasional.maturity_rows(self.P.input)[0]["새만기일"], "2028-04-17")

    def test_holder_loads_with_checks(self):
        """24: 저장된 주주를 골라 불러오면 '미성년자·회사 급여' 체크까지 채워져, 지분율만 고쳐 저장해도 체크가 풀리지 않는다."""
        from ceo_report import occasional
        self.app.save_holder(self.P.input, "가상주주", "40", True, True, "1,000,000", "", False, "2")
        self.w.pick_rare("주주")
        self.w.refresh_holders()
        self.assertIn("가상주주", list(self.w.h_box.cget("values")))
        self.w.h_name.set("가상주주")
        self.w.load_holder()
        self.assertTrue(self.w.h_minor.get() and self.w.h_wage.get())
        self.w.h_share.set("45")
        self.w.save_holder()
        got = occasional.saved_holder(self.P.input, "가상주주")
        self.assertEqual((got["지분율"], got["미성년자"], got["회사급여"]), ("45", True, True))

    def test_uncheck_remember_asks_to_forget(self):
        """26: '계정 기억'을 끄면 저장된 계정도 지울지 한 번 묻고, 지금 기억 중인지 옆에 보인다."""
        from ceo_report import credstore
        credstore.save(self.P.input, "tester", "pw-not-real")
        self.w.remember_info.set(__import__("ceo_report.occasional", fromlist=["x"]).remember_text(self.P.input))
        self.assertIn("기억 중", self.w.remember_info.get())
        self.w.remember.set(False)
        with mock.patch.object(self.gui.messagebox, "askyesno", return_value=True) as ask:
            self.w.remember_changed()
            self.assertTrue(ask.called)
        self.assertIsNone(credstore.load(self.P.input))
        self.assertIn("기억한 계정 없음", self.w.remember_info.get())

    def test_schedule_card_says_next_report(self):
        """33: '가용자금에 바로 반영'이 아니라 '다음 보고부터 반영'."""
        self.assertEqual(self.w.f_sched.sub.cget("text"), "다음 보고부터 반영")


class TestRuleOps05RareList(GuiCase):
    def test_rare_cards_are_a_list_and_only_chosen_opens(self):
        """운영-05 (25): 주주·배당·세법·신용평가·내년 예산(+대출 만기)은 이름 목록으로 두고 고른 것만 입력이 열린다."""
        w = self.w
        self.assertEqual(tuple(w.rare_names), ("주주", "배당 판단 질문", "법인세 감면·공제", "세법 기준 확인", "신용평가 체크리스트", "내년 예산", "대출 만기"))
        self.assertEqual([w.rare_list.get(i).split(" · ")[0] for i in range(w.rare_list.size())], list(w.rare_names))
        w.nb.select(1)
        self.root.update()
        self.assertFalse(any(p.winfo_ismapped() for p in w.rare_panels.values()))
        w.pick_rare("내년 예산")
        self.root.update()
        self.assertEqual([n for n, p in w.rare_panels.items() if p.winfo_ismapped()], ["내년 예산"])
        w.pick_rare("주주")
        self.root.update()
        self.assertEqual([n for n, p in w.rare_panels.items() if p.winfo_ismapped()], ["주주"])

    def test_one_screen_without_scroll_or_smaller_font(self):
        """운영-05: 스크롤 없이 한 화면, 글자도 더 줄이지 않는다 — 창이 예전(높이 802)보다 낮아지고, 고른 카드를 바꿔도 크기가 그대로."""
        import tkinter as tk
        from tkinter import ttk
        w = self.w

        def walk(x):
            yield x
            for c in x.winfo_children():
                for y in walk(c):
                    yield y
        tab2 = w.nb.nametowidget(w.nb.tabs()[1])
        self.assertFalse([x for x in walk(tab2) if isinstance(x, (tk.Scrollbar, ttk.Scrollbar))])
        self.assertEqual(w.scale, 1.0)
        self.assertEqual(w.fonts["base"].cget("size"), 10)
        h0 = self.root.winfo_reqheight()
        self.assertLessEqual(h0, 760)
        for name in w.rare_names:
            w.pick_rare(name)
            self.root.update()
            self.assertEqual(self.root.winfo_reqheight(), h0, name)
        self.assertIn("가끔 넣는 값", w.nb.tab(1, "text"))
        self.assertNotIn("(8)", w.nb.tab(1, "text"))


class TestAutoStatus(GuiCase):
    def test_auto_line_and_retry_button(self):
        """27·28: 자동 반영 옆에 지금 상태, 실패하면 '실패 — 다시 하기' 단추."""
        self.w.auto_tick()
        self.assertIn("새 자료 없음", self.w.auto_info.get())
        self.assertFalse(self.w.auto_retry.winfo_manager())
        self.w.finish("자동", 3, [])
        self.assertIn("실패", self.w.auto_info.get())
        self.assertTrue(self.w.auto_retry.winfo_manager())
        started = []
        with mock.patch.object(self.w, "start", lambda task, **k: started.append(task) or True):
            self.w.retry_auto()
        self.assertEqual(started, ["자동"])

    def test_wrong_date_does_not_burn_the_try(self):
        """28: 기준일 칸이 틀려 시작조차 못 했으면, 날짜를 고친 뒤 같은 자료로 다시 돈다."""
        st = {"state": "ready", "sig": "분개장 x", "text": "새 자료 받음"}
        self.w.asof.set("틀림")
        with mock.patch.object(self.app, "auto_state", lambda *a, **k: st):
            self.w.auto_tick()
            self.assertIsNone(self.w.auto_tried)
            self.assertIn("실패", self.w.auto_info.get())
            self.w.asof.set("2026-11-16")
            with mock.patch.object(self.app, "run_task", lambda *a, **k: (0, [])):
                self.w.auto_tick()
                self.assertEqual(self.w.auto_tried, "분개장 x")
                self.pump(30)

    def test_retry_only_failed_kind(self):
        """29: 월간 PDF만 못 만들었으면 '다시 하기'는 월간만 다시 만든다."""
        out = self.P.output
        files = [os.path.join(out, "2026-11-16_주간_대표보고.html"), os.path.join(out, "2026-11-16_주간_대표보고_1116_0900.pdf"),
                 os.path.join(out, "2026-11-16_월간_대표보고.html")]
        for f in files:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("<html></html>")
        self.w.finish("자동", 0, files)
        self.assertIn("월간 PDF 못 만듦", self.w.status.get())
        started = []
        with mock.patch.object(self.w, "start", lambda task, **k: started.append(task) or True):
            self.w.retry_auto()
        self.assertEqual(started, ["월간"])

    def test_open_live_rebuilds_after_schedule_change(self):
        """33: 지급·입금 예정을 넣은 뒤 '지금 현황'은 새로 만들어 연다."""
        from ceo_report import live
        import time
        page = os.path.join(self.P.output, live.FILE)
        with open(page, "w", encoding="utf-8") as f:
            f.write("<html>지금 현황</html>")
        old = time.time() - 600
        os.utime(page, (old, old))
        self.app.add_schedule(self.P.input, "2026-11-30", "지급", "1,000", "예상", "가상업체")
        built = []
        with mock.patch.object(self.app, "build_live", lambda *a, **k: built.append(1)), mock.patch.object(self.gui, "open_path"):
            self.w.open_live()
        self.assertEqual(built, [1])


if __name__ == "__main__":
    unittest.main()
