"""자료 정합성 점검 (대표보고.exe --정합성): 입력 폴더를 바꾸지 않고 결과 파일만 쓴다."""
import datetime as dt
import hashlib
import os
import shutil
import tempfile
import unittest

from ceo_report import integrity

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def digest(folder):
    h = hashlib.sha256()
    for name in sorted(os.listdir(folder)):
        p = os.path.join(folder, name)
        if os.path.isfile(p):
            h.update(name.encode())
            with open(p, "rb") as f:
                h.update(f.read())
    return h.hexdigest()


class TestIntegrity(unittest.TestCase):
    def test_runs_on_sample_without_touching_input(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(os.path.join(ROOT, "입력양식", "샘플"), os.path.join(tmp, "입력"))
        os.makedirs(os.path.join(tmp, "수집", "위하고"))
        before = digest(os.path.join(tmp, "입력"))
        out = os.path.join(tmp, "정합성.txt")
        integrity.run(tmp, out, dt.date(2026, 10, 31))
        with open(out, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("# 자료 정합성 점검", text)
        self.assertIn("## 보고서 만들기", text)
        self.assertNotIn("점검 오류", text)
        self.assertEqual(digest(os.path.join(tmp, "입력")), before)
        self.assertFalse(os.path.exists(os.path.join(tmp, "출력")) and os.listdir(os.path.join(tmp, "출력")))


if __name__ == "__main__":
    unittest.main()
