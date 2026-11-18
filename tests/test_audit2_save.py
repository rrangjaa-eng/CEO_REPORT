"""2차 전수조사 제안 17 (P5·P6·P12·P13): 저장·읽기 안전. 가상 자료만."""
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

from ceo_report import budget, calc, choices, gate, targets  # noqa: E402
from ceo_report.data import load  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
ASOF = dt.date(2026, 11, 6)
BAD = b"\xff\xfe\x00\x81\x00\x8d\xff"   # UTF-8·CP949 어느 쪽으로도 못 읽는 바이트


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inp = os.path.join(self.tmp, "입력")
        shutil.copytree(SAMPLE, self.inp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def bad(self, name):
        with open(os.path.join(self.inp, name), "wb") as f:
            f.write(BAD)


class ConfirmKeepsOtherYears(Base):   # P5
    def test_unreadable_file_stops_instead_of_overwriting(self):
        d = load(self.inp)
        B = budget.compute(d, budget.read_values(self.inp), 2027, ASOF, d.settings)
        self.bad(budget.CONFIRM_FILE)
        with self.assertRaises(ValueError):
            budget.confirm(self.inp, B)
        with open(os.path.join(self.inp, budget.CONFIRM_FILE), "rb") as f:
            self.assertEqual(f.read(), BAD)   # 그대로 둠

    def test_choices_unreadable_stops(self):
        self.bad(choices.FILE)
        k = next(iter(choices.KEYS))
        v = (choices.KEYS[k] or ["3.0"])[0]
        with self.assertRaises(ValueError):
            choices.save(self.inp, {k: v})


class Targets(Base):   # P6
    def test_unreadable_targets_block_reports(self):
        self.assertEqual(targets.problem(self.inp), "")
        self.bad(targets.TARGET_FILE)
        self.assertIn("읽지 못함", targets.problem(self.inp))
        R = calc.compute(load(self.inp), "weekly", ASOF)
        self.assertIn("팀목표.csv", R["targets_problem"])
        with mock.patch.dict(os.environ, {gate.TEST_OFF: "0"}):
            self.assertTrue(any("팀목표.csv" in p for p in gate.problems(dict(R, input_dir=None))))


class CostRate(Base):   # P12
    def B(self, value):
        d = load(self.inp)
        d.settings["예산_원가율"] = value
        d.team_targets = {}
        return budget.compute(d, {}, 2027, ASOF, d.settings)

    def test_percent_and_out_of_range(self):
        self.assertAlmostEqual(self.B("70%")["cost_rate"], 0.70)
        self.assertAlmostEqual(self.B("0.65")["cost_rate"], 0.65)
        B = self.B("70")
        self.assertAlmostEqual(B["cost_rate"], 0.70)
        self.assertTrue(any("예산_원가율 '70' 값 오류" in n for n in B["notes"]))


class ScheduleDropped(Base):   # P13
    def test_bad_io_value_is_counted(self):
        p = os.path.join(self.inp, "자금일정.csv")
        with open(p, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
        head = lines[0].split(",")
        row = lines[1].split(",")
        row[head.index("입출금")] = "지츨"
        with open(p, "w", encoding="utf-8-sig") as f:
            f.write("\n".join([lines[0], ",".join(row)] + lines[2:]) + "\n")
        R = calc.compute(load(self.inp), "weekly", ASOF)
        self.assertEqual(len(R["sched_dropped"]), 1)
        with mock.patch.dict(os.environ, {gate.TEST_OFF: "0"}):
            probs = gate.problems(dict(R, input_dir=None))
        self.assertTrue(any("'입출금' 칸 값이 틀려 일정에서 빠짐" in x for x in probs))


if __name__ == "__main__":
    unittest.main()
