"""2차 전수조사 제안 4 (P1, 사용자 2026-11-18 결정 '대표·팀장 보고를 막음'): 변환 뒤 새로 받은 분개장·자금계획서가 있으면 막는다."""
import datetime as dt
import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import gate  # noqa: E402


class Unconverted(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.inp = os.path.join(self.root, "입력")
        self.col = os.path.join(self.root, "수집", "위하고")
        os.makedirs(self.inp)
        os.makedirs(self.col)
        self.when = dt.datetime.now().replace(microsecond=0) - dt.timedelta(hours=2)
        with open(os.path.join(self.inp, "변환결과.txt"), "w", encoding="utf-8") as f:
            f.write("변환 시각 %s\n" % self.when.strftime("%Y-%m-%d %H:%M:%S"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def put(self, name, minutes):
        p = os.path.join(self.col, name)
        open(p, "w").close()
        t = time.mktime((self.when + dt.timedelta(minutes=minutes)).timetuple())
        os.utime(p, (t, t))

    def test_old_files_pass(self):
        self.put("261118 분개장_2026.json", -30)
        self.assertEqual(gate.unconverted(self.inp, downloads=[]), [])

    def test_new_book_blocks(self):
        self.put("261118 분개장_2026.json", 30)
        got = gate.unconverted(self.inp, downloads=[])
        self.assertEqual(len(got), 1)
        self.assertIn("새로 받은 파일이 있음: 261118 분개장_2026.json", got[0])
        self.assertIn("자료 변환을 먼저 하세요", got[0])

    def test_new_plan_blocks_but_other_files_do_not(self):
        self.put("261118 시산표.json", 30)
        self.assertEqual(gate.unconverted(self.inp, downloads=[]), [])
        self.put("261118 자금계획_2026-11.json", 30)
        self.assertEqual(len(gate.unconverted(self.inp, downloads=[])), 1)

    def test_problems_uses_it(self):
        self.put("261118 분개장_2026.json", 30)
        R = {"asof": dt.date.today(), "fundplan": {"used": True}, "input_dir": self.inp, "book_date": dt.date.today()}
        from unittest import mock
        with mock.patch.dict(os.environ, {gate.TEST_OFF: "0"}):   # 다른 시험이 켜 둔 끄개와 상관없이
            probs = gate.problems(R)
        self.assertTrue(any("새로 받은 파일이 있음" in p for p in probs))

    def test_no_convert_record_is_not_judged(self):
        os.remove(os.path.join(self.inp, "변환결과.txt"))
        self.put("261118 분개장_2026.json", 30)
        self.assertEqual(gate.unconverted(self.inp, downloads=[]), [])


class AsofMismatch(unittest.TestCase):
    """제안 11 (D1): 보고 기준일과 자료 변환 기준일이 어긋나면 막는다."""

    def setUp(self):
        self.inp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.inp, ignore_errors=True)

    def conv(self, day, cut=False):
        from ceo_report.wehago import CUT_MARK
        with open(os.path.join(self.inp, "변환결과.txt"), "w", encoding="utf-8-sig") as f:
            f.write("변환 시각 2026-11-18 10:00:00 · 기준일 %s\nWEHAGO 장부: ok\n" % day)
            if cut:
                f.write("  알림 %s %s — 그 뒤 전표 3줄을 빼고 계산\n" % (CUT_MARK, day))

    def test_same_day_and_later_report_pass(self):
        self.conv("2026-11-18")
        self.assertEqual(gate.asof_mismatch(self.inp, dt.date(2026, 11, 18)), [])
        self.assertEqual(gate.asof_mismatch(self.inp, dt.date(2026, 11, 20)), [])

    def test_report_before_conversion_day_blocks(self):
        self.conv("2026-11-18")
        got = gate.asof_mismatch(self.inp, dt.date(2026, 10, 31))
        self.assertEqual(len(got), 1)
        self.assertIn("기준일을 2026-10-31 로 두고 '자료 변환'을 다시", got[0])

    def test_cut_conversion_only_serves_its_own_day(self):
        self.conv("2026-10-31", cut=True)
        self.assertEqual(gate.asof_mismatch(self.inp, dt.date(2026, 10, 31)), [])
        self.assertEqual(len(gate.asof_mismatch(self.inp, dt.date(2026, 11, 18))), 1)

    def test_no_record_is_left_to_other_checks(self):
        self.assertEqual(gate.asof_mismatch(self.inp, dt.date(2026, 11, 18)), [])


class CutBooks(unittest.TestCase):
    """지난 기준일이면 그 뒤 전표를 빼고, 보통 날에는 앞날짜 전표도 그대로."""

    def test_cut_only_when_asof_is_before_the_book_day(self):
        from ceo_report import wehago
        from test_wehago import write_fake_books
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        folder = os.path.join(root, "위하고")
        write_fake_books(folder)   # 파일 날짜 2026-10-31, 전표 ~10/30
        full = wehago.load_books(folder, dt.date(2026, 11, 2), None)
        self.assertEqual(full.state, "ok")
        self.assertIsNone(full.cut_after)
        days = sorted(r["date"] for r in full.journal if r.get("date"))
        mid = days[len(days) // 2]
        self.assertLess(mid, days[-1])
        part = wehago.load_books(folder, mid, None)
        self.assertTrue(all(r["date"] <= mid for r in part.journal if r.get("date")))
        self.assertEqual(len(part.journal), sum(1 for d in days if d <= mid) + sum(1 for r in full.journal if not r.get("date")))
        self.assertGreater(part.cut_after["n"], 0)
        self.assertTrue(any(wehago.CUT_MARK in n for n in part.notes))


if __name__ == "__main__":
    unittest.main()
