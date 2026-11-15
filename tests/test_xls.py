""".xls(BIFF8) 읽기: 표준 라이브러리만, 합성 파일로 확인한다."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report.xls import XlsError, read_xls  # noqa: E402
import xls_fixture as X  # noqa: E402


class TestReadXls(unittest.TestCase):
    def tmp(self, name="a.xls"):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d))
        return os.path.join(d, name)

    def sample_cells(self):
        strings = ["자금구분", "예정일:2026.11.06-가상상사[000001]", "abc"]
        cells = [X.labelsst(0, 0, 0), X.labelsst(1, 0, 1), X.number(1, 3, 990000.0),
                 X.label(2, 0, "미지급금 지급"), X.rk(2, 1, X.rk_int(12345)), X.rk(2, 2, X.rk_int(150, div100=True)),
                 X.mulrk(3, 1, [X.rk_int(1), X.rk_int(2), X.rk_int(3)]), X.formula_num(4, 0, 7.5),
                 X.labelsst(5, 2, 2)] + X.formula_str(4, 1, "계")
        want = [["자금구분", "", "", ""],
                ["예정일:2026.11.06-가상상사[000001]", "", "", 990000.0],
                ["미지급금 지급", 12345.0, 1.5, ""],
                ["", 1.0, 2.0, 3.0],
                [7.5, "계", "", ""],
                ["", "", "abc", ""]]
        return cells, strings, want

    def test_small_stream(self):
        cells, strings, want = self.sample_cells()
        self.assertEqual(read_xls(X.write_xls(self.tmp(), cells, strings)), want)

    def test_large_stream(self):
        cells, strings, want = self.sample_cells()
        self.assertEqual(read_xls(X.write_xls(self.tmp(), cells, strings, pad=6000)), want)

    def test_string_split_across_continue(self):
        strings = ["앞", "예정일:2026.12.04-가상인쇄[000002]", "뒤"]
        cells = [X.labelsst(0, 0, 0), X.labelsst(1, 0, 1), X.labelsst(2, 0, 2)]
        path = X.write_xls(self.tmp(), cells, strings, split_at=(1, 9))
        self.assertEqual([r[0] for r in read_xls(path)], strings)

    def test_not_an_xls(self):
        path = self.tmp()
        with open(path, "wb") as f:
            f.write(b"PK\x03\x04 not an old excel file" * 30)
        with self.assertRaises(XlsError):
            read_xls(path)

    def test_old_biff_version_is_refused(self):
        cells, strings, _ = self.sample_cells()
        with self.assertRaises(XlsError):
            read_xls(X.write_xls(self.tmp(), cells, strings, biff_version=0x500))


if __name__ == "__main__":
    unittest.main()
