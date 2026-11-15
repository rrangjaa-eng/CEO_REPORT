"""정합성 점검 핵심 숫자: 지난 점검과 비교해 바뀐 것만 표시 (사용자 2026-11-04 ⑤)."""
import os
import shutil
import sys
import tempfile
import unittest
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ceo_report import integrity  # noqa: E402


class TestKeys(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "입력"))

    def tearDown(self):
        shutil.rmtree(self.dir, True)

    def test_second_run_shows_changes(self):
        out = []
        integrity.compare_keys(self.dir, OrderedDict([("통장", 100), ("매출", 5)]), out)
        self.assertIn("- 바뀐 숫자 0개", out)
        out = []
        integrity.compare_keys(self.dir, OrderedDict([("통장", 100), ("매출", 7)]), out)
        self.assertIn("- 매출: 5 → 7  ← 바뀜", out)
        self.assertTrue(out[-1].startswith("- 바뀐 숫자 1개"))


if __name__ == "__main__":
    unittest.main()
