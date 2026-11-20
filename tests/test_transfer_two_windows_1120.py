"""2026-11-20 사용자: 이체 파일에 사업소득(한 거래처코드에 예금주 3명)이 빠졌다.
계좌 없는 거래처가 하나라도 남으면 그 창만 다시 뜨고 예금주별 금액 창은 한 번도 뜨지 않았다 → 두 창을 차례로,
못 넣은 지급은 결과 칸에 금액·까닭과 함께 빨강, 창에서 이어서 다시 만든 파일끼리는 '중복 의심'으로 세지 않음. 모두 가상 자료."""
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

from ceo_report import transfer, winstate   # noqa: E402

GUI = os.environ.get("CEO_REPORT_GUI_TEST") == "1"
MISSING = {"vendor": "가상벤처", "code": "001272", "amount": 1320000, "date": "2026-11-20", "why": "계좌 정보 없음"}
MULTI = {"vendor": "사업소득", "code": "000147", "amount": 1066700, "holders": ["가갑", "나을", "다병"],
         "parts": [920000, 96700, 50000]}
BLOCKED = [("사업소득", 1066700, "계좌 3개 (가갑, 나을, 다병) — 예금주별 금액 필요 (합계 1,066,700원)"),
           ("가상벤처", 1320000, "계좌 정보 없음 (목록에 거래처만 있음 — 창 ‘가끔 넣는 값 › 거래처 계좌’에서 넣으세요)")]


class TestSummaryRed(unittest.TestCase):
    def test_blocked_is_red_with_amount_and_reason(self):
        text, bad = winstate.transfer_summary({"summary": {"n": 13, "total": 37576140, "rows": [], "blocked": BLOCKED, "repeats": []}})
        self.assertTrue(bad)
        self.assertIn("못 넣음 2건 2,386,700원: 사업소득(예금주별 금액 필요), 가상벤처(계좌 정보 없음)", text)

    def test_nothing_blocked_stays_green(self):
        text, bad = winstate.transfer_summary({"summary": {"n": 1, "total": 10, "rows": [], "blocked": [], "repeats": []}})
        self.assertFalse(bad)
        self.assertNotIn("못 넣음", text)

    def test_many_blocked_shows_four_then_count(self):
        many = [("가%d" % i, 1000, "금액 미확인") for i in range(6)]
        text, _ = winstate.transfer_summary({"summary": {"n": 1, "total": 10, "rows": [], "blocked": many, "repeats": []}})
        self.assertIn("가1(금액 미확인) 외", text)
        self.assertNotIn("가2", text)


class TestPartsShown(unittest.TestCase):
    def test_merged_lines_keep_each_amount(self):
        """같은 거래처코드로 합친 지급(사업소득 3줄)은 합치기 전 금액을 함께 넘겨 예금주별 금액 창에 보인다."""
        D = dt.date(2026, 11, 20)
        ev = [{"date": D, "io": "out", "amount": a, "firm": True, "cat": "외주용역비", "desc": "사업소득",
               "vendor_code": "000147", "project": "", "source": "자금계획서"} for a in (920000, 96700, 50000)]
        acc = {"#147": [{"거래처코드": "147", "거래처": "사업소득", "은행": "국민", "계좌번호": "1%d" % i, "예금주": h}
                        for i, h in enumerate(("가갑", "나을", "다병"))]}
        multi = []
        rows, blocked, _ = transfer.build(ev, acc, D, D, None, multi)
        self.assertEqual(rows, [])
        self.assertEqual((multi[0]["amount"], multi[0]["parts"]), (1066700, [920000, 96700, 50000]))


class TestRepeatsReplaced(unittest.TestCase):
    def test_file_replaced_in_this_flow_is_not_a_repeat(self):
        now = dt.datetime(2026, 11, 20, 12, 5)
        log = [{"만든시각": "2026-11-20 12:03:02", "계좌번호": "111", "금액": "100", "파일": "a.xlsx"},
               {"만든시각": "2026-11-19 17:00:00", "계좌번호": "222", "금액": "200", "파일": "b.xlsx"}]
        rows = [["088", "111", "가", "100"], ["088", "222", "나", "200"]]
        self.assertEqual(len(transfer.repeats(log, rows, now)), 2)
        got = transfer.repeats(log, rows, now, replaced=["a.xlsx"])
        self.assertEqual([r[0][1] for r in got], ["222"])   # 어제 만든 다른 파일은 그대로 중복 의심


@unittest.skipUnless(GUI, "화면 시험은 CEO_REPORT_GUI_TEST=1 일 때만")
class TestTwoWindows(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from ceo_report import app, gui
        self.gui = gui
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
        self.w = gui.Window(self.root, paths=self.P, today=dt.date(2026, 11, 19))
        self.root.update()
        self.calls = []

    def fake(self, inp, out, start, end, say, **k):
        """실제 11/20 상황: 가상벤처는 계좌 없음, 사업소득은 예금주 3명. 나눔을 받으면 사업소득은 넣는다."""
        self.calls.append(dict(k))
        n = len(self.calls)
        path = os.path.join(out, "이체_%d.xlsx" % n)
        split = (k.get("splits") or {}).get(transfer.code_key("000147"))
        blocked = [b for b in BLOCKED if not (split and b[0] == "사업소득")]
        k["missing"].append(dict(MISSING))
        if not split:
            k["multi"].append(dict(MULTI))
        k["result"]["summary"] = {"n": 13, "total": 1, "rows": [], "blocked": blocked, "repeats": []}
        return path

    def tops(self):
        import tkinter as tk
        self.root.update()
        return [t for t in self.root.winfo_children() if isinstance(t, tk.Toplevel) and t.winfo_exists()]

    def button(self, top, text):
        from tkinter import ttk

        def walk(wd):
            for c in wd.winfo_children():
                if isinstance(c, ttk.Button) and c.cget("text") == text:
                    return c
                got = walk(c)
                if got:
                    return got
        b = walk(top)
        self.assertIsNotNone(b, text)
        return b

    def test_save_with_blank_then_splits_window(self):
        with mock.patch.object(transfer, "make_file", self.fake), mock.patch.object(self.w, "open_dir"), \
                mock.patch.object(self.w, "refresh_accounts"):
            self.w.make_transfer()
            t = self.tops()
            self.assertEqual([x.title() for x in t], ["계좌 없는 거래처 1곳"])
            self.assertEqual(str(self.w.t_result_lab.cget("foreground")), self.gui.C["red"])
            self.assertIn("사업소득(예금주별 금액 필요)", self.w.t_result.get())
            self.button(t[0], "저장하고 다시 만들기").invoke()   # 가상벤처는 비워 둠 (은행에서 직접)
            t = self.tops()
            self.assertEqual([x.title() for x in t], ["예금주별 금액 1곳"])   # 예전엔 계좌 창만 다시 떴다
            self.assertTrue(any("920,000 · 96,700 · 50,000원" in x for x in self._labels(t[0])))
            self.assertEqual(self.calls[1]["replaced"], ["이체_1.xlsx"])
            entries = [e for e in self._entries(t[0])]
            for e, v in zip(entries, ("920000", "96700", "50000")):
                e.insert(0, v)
            self.button(t[0], "나눠서 다시 만들기").invoke()
            self.assertEqual(self.tops(), [])   # 비워 둔 가상벤처 때문에 계좌 창이 또 뜨지 않음
            self.assertEqual(self.calls[2]["splits"][transfer.code_key("000147")], {"가갑": 920000, "나을": 96700, "다병": 50000})
            self.assertEqual(self.calls[2]["replaced"], ["이체_1.xlsx", "이체_2.xlsx"])
            self.assertIn("못 넣음 1건 1,320,000원", self.w.t_result.get())
            # 단추로 새로 만들면 이어 가던 기록을 비운다 (비워 둔 거래처를 다시 묻고, 앞 파일은 중복 의심으로 셈)
            self.w.make_transfer()
            self.assertEqual(self.calls[3]["replaced"], [])
            self.assertEqual([x.title() for x in self.tops()], ["계좌 없는 거래처 1곳"])

    def test_close_accounts_window_opens_splits(self):
        with mock.patch.object(transfer, "make_file", self.fake), mock.patch.object(self.w, "open_dir") as od:
            self.w.make_transfer()
            t = self.tops()
            self.button(t[0], "닫고 예금주별 금액으로").invoke()
            self.assertEqual([x.title() for x in self.tops()], ["예금주별 금액 1곳"])
            od.assert_not_called()

    def test_no_multi_keeps_old_close_button(self):
        def fake(inp, out, start, end, say, **k):
            k["missing"].append(dict(MISSING))
            k["result"]["summary"] = {"n": 1, "total": 1, "rows": [], "blocked": BLOCKED[1:], "repeats": []}
            return os.path.join(out, "x.xlsx")
        with mock.patch.object(transfer, "make_file", fake), mock.patch.object(self.w, "open_dir") as od:
            self.w.make_transfer()
            t = self.tops()
            self.button(t[0], "닫기 (이대로 둠)").invoke()
            self.assertEqual(self.tops(), [])
            od.assert_called_once()

    def _labels(self, top):
        from tkinter import ttk
        out = []

        def walk(wd):
            for c in wd.winfo_children():
                if isinstance(c, ttk.Label):
                    out.append(str(c.cget("text")))
                walk(c)
        walk(top)
        return out

    def _entries(self, top):
        from tkinter import ttk
        out = []

        def walk(wd):
            for c in wd.winfo_children():
                if isinstance(c, ttk.Entry) and not isinstance(c, ttk.Combobox):
                    out.append(c)
                walk(c)
        walk(top)
        return out


if __name__ == "__main__":
    unittest.main()
