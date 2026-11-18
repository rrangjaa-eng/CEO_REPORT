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


if __name__ == "__main__":
    unittest.main()
