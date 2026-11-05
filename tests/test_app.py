"""한 화면 프로그램의 일 (사용자 2026-11-03): 버튼 하나로 변환·보고서·승인검토, 예정 지출·입금 넣기, 예전 파일 지난자료로. 가상 자료만."""
import datetime as dt
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

from ceo_report import app  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from test_fundplan import print_rows, write_plan  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
D = dt.date


def program(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    shutil.copytree(SAMPLE, os.path.join(tmp, "입력"))
    os.makedirs(os.path.join(tmp, "수집", "위하고"))
    return app.Paths(tmp)


class TestRunTask(unittest.TestCase):
    def test_weekly_button_makes_the_report_and_shows_lines(self):
        P = program(self)
        lines = []
        rc, files = app.run_task("주간", P, lines.append, asof="2026-10-31")
        self.assertEqual(rc, 0, lines)
        self.assertTrue(any(f.endswith("_주간_대표보고.html") for f in files), files)
        self.assertTrue(lines)

    def test_bad_date_is_a_message_not_a_crash(self):
        lines = []
        rc, files = app.run_task("월간", program(self), lines.append, asof="2026-13-40")
        self.assertEqual((rc, files), (2, []))
        self.assertIn("기준일 형식 오류", lines[0])

    def test_pick_date_goes_to_the_report(self):
        name, argv = app.task_argv("월간", app.Paths("/x"), "2026-10-31", "2026-12-15")
        self.assertEqual(name, "보고서")
        self.assertEqual(argv[:5], ["월간", "--기준일", "2026-10-31", "--가용일", "2026-12-15"])

    def test_approval_uses_the_window_password_and_restores_the_hook(self):
        import 승인검토
        seen = []
        P = program(self)

        def fake_collect(a, asof, now):
            seen.append(승인검토.ask_credentials())
            return 0
        orig = 승인검토.run_collect
        승인검토.run_collect = fake_collect
        try:
            rc, _ = app.run_task("승인검토", P, lambda s: None, asof="2026-11-02", collect=True,
                                 credentials=lambda: (" 가상ID ", "가상비번"))
        finally:
            승인검토.run_collect = orig
        self.assertEqual(rc, 0)
        self.assertEqual(seen, [("가상ID", "가상비번", None)])
        self.assertIsNone(승인검토.CREDENTIALS)


class TestAddSchedule(unittest.TestCase):
    def test_added_row_counts_in_available_cash(self):
        P = program(self)
        before = compute(load(P.input), "weekly", D(2026, 10, 31))
        row = app.add_schedule(P.input, "2026-11-04", "지급", "3,000,000", "예상", "가상 인쇄소", basis="견적")
        self.assertEqual((row["금액"], row["확정여부"], row["분류"]), ("3,000,000", "예상", "기타지급"))
        after = compute(load(P.input), "weekly", D(2026, 10, 31))
        self.assertEqual(before["s2"]["periods"][0]["all"]["out"] + 3_000_000, after["s2"]["periods"][0]["all"]["out"])
        with open(os.path.join(P.input, "자금일정.csv"), "rb") as f:
            raw = f.read()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw.count(b"\xef\xbb\xbf"), 1)

    def test_new_file_gets_the_header(self):
        P = program(self)
        os.remove(os.path.join(P.input, "자금일정.csv"))
        app.add_schedule(P.input, "2026-11-04", "입금", "1000", "확정", "가상고객")
        with open(os.path.join(P.input, "자금일정.csv"), encoding="utf-8-sig") as f:
            text = f.read().splitlines()
        self.assertEqual(text[0], "예정일,입출금,금액,확정여부,분류,프로젝트번호,거래처,근거,비고")
        self.assertEqual(text[1], "2026-11-04,입금,\"1,000\",확정,기타입금,,가상고객,직접 입력,")

    def test_wrong_values_are_refused_with_a_reason(self):
        P = program(self)
        for args, word in ((("", "지급", "1", "예상", "가"), "예정일"), (("2026-11-04", "지급", "0", "예상", "가"), "금액"),
                           (("2026-11-04", "지급", "1", "모름", "가"), "확정여부"), (("2026-11-04", "지급", "1", "예상", " "), "거래처")):
            with self.subTest(word):
                with self.assertRaises(ValueError) as cm:
                    app.add_schedule(P.input, *args)
                self.assertIn(word, str(cm.exception))


class TestArchiveOld(unittest.TestCase):
    def folder(self):
        P = program(self)
        for n in ("261001 분개장.xlsx", "261103 분개장.xls", "260105 분개장_2025.xls", "261103 분개장_2025.xls",
                  "261001 매입매출장.xlsx", "261103 매입매출장.xlsx", "메모.txt"):
            with open(os.path.join(P.wehago, n), "wb") as f:
                f.write(b"x")
        write_plan(P.wehago, "261002 자금계획서지출입금현황_2610.xls", print_rows(2026, 10, [("지급계획", "미지급금 지급", 6, "가상상사", "000001", 1000)], split=0))
        write_plan(P.wehago, "261102 자금계획서지출입금현황_2611.xls", print_rows(2026, 11, [("지급계획", "미지급금 지급", 6, "가상상사", "000001", 1000)], split=0))
        write_plan(P.wehago, "261101 자금계획서지출입금현황_2611.xls", print_rows(2026, 11, [("지급계획", "미지급금 지급", 6, "가상상사", "000001", 900)], split=0))
        return P

    def test_moves_only_files_the_conversion_does_not_use(self):
        P = self.folder()
        lines = []
        n = app.archive_old(P.wehago, D(2026, 11, 3), lines.append)
        moved = sorted(os.listdir(os.path.join(P.wehago, app.ARCHIVE)))
        self.assertEqual(moved, sorted(["261001 분개장.xlsx", "260105 분개장_2025.xls", "261001 매입매출장.xlsx",
                                        "261002 자금계획서지출입금현황_2610.xls", "261101 자금계획서지출입금현황_2611.xls"]))
        self.assertEqual(n, 5)
        left = sorted(n for n in os.listdir(P.wehago) if n != app.ARCHIVE)
        self.assertEqual(left, sorted(["261103 분개장.xls", "261103 분개장_2025.xls", "261103 매입매출장.xlsx", "메모.txt",
                                       "261102 자금계획서지출입금현황_2611.xls"]))
        self.assertTrue(any("지우지 않음" in ln for ln in lines))

    def test_nothing_to_move_says_so(self):
        P = program(self)
        lines = []
        self.assertEqual(app.archive_old(P.wehago, D(2026, 11, 3), lines.append), 0)
        self.assertIn("옮길 예전 파일이 없습니다", lines[0])


class TestCardDays(unittest.TestCase):
    """창에서 카드별 납부일·기산일을 넣는다 (사용자 2026-11-03)."""

    def test_save_adds_and_updates(self):
        P = program(self)
        rows = app.save_card(P.input, "비씨카드", "25", "12")
        self.assertIn(("비씨", 25, 12), rows)
        rows = app.save_card(P.input, "신한", "10일", "")
        self.assertIn(("신한", 10, 1), rows)
        self.assertEqual(len([r for r in rows if r[0] == "신한"]), 1)
        self.assertIn("비씨 25일(기산 12일)", app.card_list(P.input))

    def test_bad_values_are_refused(self):
        P = program(self)
        for args, word in ((("", "15", "1"), "카드사"), (("신한", "32", "1"), "납부일"), (("신한", "15", "x"), "기산일")):
            with self.subTest(word):
                with self.assertRaises(ValueError) as cm:
                    app.save_card(P.input, *args)
                self.assertIn(word, str(cm.exception))


class TestOneWindow(unittest.TestCase):
    """실행 파일은 하나 (사용자 2026-11-03): 예전 실행_*.bat 넷 대신 대표보고.pyw / 대표보고.exe."""

    def test_only_one_launcher(self):
        self.assertEqual([n for n in os.listdir(ROOT) if n.lower().endswith(".bat")], [])
        with open(os.path.join(ROOT, "대표보고.pyw"), encoding="utf-8") as f:
            self.assertIn("from ceo_report.gui import main", f.read())

    def test_exe_build_checks_itself(self):
        with open(os.path.join(ROOT, ".github", "workflows", "build-exe.yml"), encoding="utf-8") as f:
            text = f.read()
        for needle in ("--onefile", "--windowed", "--hidden-import 변환", "--hidden-import 보고서", "--hidden-import 승인검토",
                       "--점검", "입력양식;입력양식"):
            self.assertIn(needle, text)

    def test_window_draws_sharp_text(self):
        """글자 번짐 (사용자 2026-11-05): Tk 를 만들기 전에 화면 배율 인식을 켠다."""
        with open(os.path.join(ROOT, "ceo_report", "gui.py"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("SetProcessDpiAwareness", text)
        self.assertLess(text.index("    sharp_text()\n    root = tk.Tk()"), len(text))

    def test_window_module_has_no_password_logging(self):
        with open(os.path.join(ROOT, "ceo_report", "gui.py"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn('show="●"', text)
        self.assertIn('self.pw.set("")', text)
        self.assertNotIn("self.pw.get()))", text.replace("(uid, pw)", ""))


if __name__ == "__main__":
    unittest.main()
