"""변환.py 가 자금계획서 지출입금현황(.xls)을 자금계획.csv 로 만든다 (D-55). 가상 자료만 쓴다."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import fundplan  # noqa: E402
from test_convert import cli_argv, read_result_lines, run_convert  # noqa: E402
from test_convert import setUpModule  # noqa: E402,F401
from test_convert_e2e import full_company, read_csv_rows  # noqa: E402
from test_fundplan import print_rows, write_plan  # noqa: E402

NAME = "261102 자금계획서지출입금현황_2611.xls"
# 장부(FAKE_PL_JOURNAL): 2026-10-05 가상고객A 보통예금 입금 110,000,000 / 장부 기준일 2026-10-31 / 기준일 2026-11-02
ITEMS = [
    ("지급계획", "미지급금 지급", 6, "가상상사", "000001", 990000),
    ("입금계획", "외상대금 회수", 2, "가상고객X", "000902", 22000000),
    ("입금계획", "외상대금 회수", 6, "가상고객A", "000900", 110000000),
]


class TestConvertFundPlan(unittest.TestCase):
    def run_with(self, plan=True):
        tmp, input_dir, collect, wehago_dir = full_company(self)
        if plan:
            write_plan(wehago_dir, NAME, print_rows(2026, 11, ITEMS, split=0))
        rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        return input_dir, rc, out

    def test_plan_written_with_states(self):
        input_dir, rc, out = self.run_with()
        rows = read_csv_rows(os.path.join(input_dir, "자금계획.csv"))
        self.assertEqual(rows[0], fundplan.COLUMNS)
        got = dict((r[3], r[9]) for r in rows[1:])
        self.assertEqual(got, {"가상상사": "예정", "가상고객X": "예정일 지남", "가상고객A": "이미 입금"})
        lines = read_result_lines(input_dir)
        self.assertIn("[자금계획.csv] 만듦 3줄", lines)
        text = "\n".join(lines)
        self.assertIn("자료일 2026-11-02", text)
        self.assertIn("장부 기준일 2026-10-31", text)
        self.assertIn("이미 입금 1", text)
        self.assertIn("자금계획.csv 만듦 3줄", out)

    def test_no_plan_keeps_existing_file(self):
        tmp, input_dir, collect, wehago_dir = full_company(self)
        path = os.path.join(input_dir, "자금계획.csv")
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write("예전 파일\n")
        rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        with open(path, encoding="utf-8-sig") as f:
            self.assertEqual(f.read(), "예전 파일\n")
        self.assertTrue(any(ln.startswith("[자금계획.csv] 만들지 않음") and "파일 없음" in ln
                            for ln in read_result_lines(input_dir)))

    def test_broken_plan_is_named(self):
        tmp, input_dir, collect, wehago_dir = full_company(self)
        with open(os.path.join(wehago_dir, NAME), "wb") as f:
            f.write(b"broken" * 200)
        run_convert(cli_argv(input_dir, collect, wehago_dir))
        self.assertFalse(os.path.exists(os.path.join(input_dir, "자금계획.csv")))
        text = "\n".join(read_result_lines(input_dir))
        self.assertIn("읽지 못함", text)


if __name__ == "__main__":
    unittest.main()
