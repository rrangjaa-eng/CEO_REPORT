"""새 자료 자동 반영 (사용자 2026-11-12): 지금 현황 화면, 자동 실행 판단, PDF 만든 시각·정리."""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import app, live, pdfname  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")


def touch(path, when):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a"):
        pass
    t = when.timestamp()
    os.utime(path, (t, t))


class TestPdfName(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.base = os.path.join(self.dir, "2026-11-12_주간_대표보고")

    def tearDown(self):
        shutil.rmtree(self.dir, True)

    def test_stamped_name(self):
        p = pdfname.stamped(self.base, dt.datetime(2026, 11, 12, 14, 5))
        self.assertTrue(p.endswith("2026-11-12_주간_대표보고 (11-12 14시05분 만듦).pdf"))

    def make(self, n):
        out = []
        for i in range(n):
            p = pdfname.stamped(self.base, dt.datetime(2026, 11, 12, 9, i))
            touch(p, dt.datetime(2026, 11, 12, 9, i))
            out.append(p)
        return out

    def test_four_kept(self):
        self.make(4)
        self.assertEqual(pdfname.prune(self.base), [])
        self.assertEqual(len(pdfname.same_report(self.base)), 4)

    def test_five_keeps_newest_three(self):
        made = self.make(5)
        touch(self.base + ".pdf", dt.datetime(2026, 11, 11, 9, 0))   # 예전 이름도 같은 보고
        edited = self.base + "_수정.pdf"
        touch(edited, dt.datetime(2026, 11, 1, 9, 0))                  # 수정 모드 PDF 는 건드리지 않음
        other = os.path.join(self.dir, "2026-11-12_주간_경영관리보고 (11-12 09시00분 만듦).pdf")
        touch(other, dt.datetime(2026, 11, 12, 9, 0))                   # 다른 보고도 그대로
        gone = pdfname.prune(self.base)
        self.assertEqual(len(gone), 3)
        self.assertEqual(sorted(pdfname.same_report(self.base)), sorted(made[2:]))
        self.assertTrue(os.path.exists(edited) and os.path.exists(other))
        self.assertEqual(pdfname.newest(self.base), made[-1])


class TestAutoSignature(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.P = app.Paths(self.root)
        os.makedirs(self.P.input)

    def tearDown(self):
        shutil.rmtree(self.root, True)

    def test_waits_until_file_settles_then_once_per_convert(self):
        got = dt.datetime(2026, 11, 12, 10, 0, 0)
        touch(os.path.join(self.P.wehago, "261112 분개장 자동수집.json"), got)
        self.assertIsNone(app.auto_signature(self.P, got + dt.timedelta(seconds=5)))    # 아직 쓰는 중일 수 있음
        sig = app.auto_signature(self.P, got + dt.timedelta(seconds=60))
        self.assertIn("분개장", sig)
        # 변환한 뒤에는 같은 자료로 다시 돌리지 않는다 (같은 분에 받은 자료도)
        from ceo_report import checklist
        touch(os.path.join(self.P.input, checklist.CONVERT_FILE), got + dt.timedelta(seconds=30))
        self.assertIsNone(app.auto_signature(self.P, got + dt.timedelta(seconds=90)))


class TestLive(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.out, True)

    def test_build_and_changes(self):
        path, diff = live.build(SAMPLE, self.out, dt.date(2026, 11, 6), dt.datetime(2026, 11, 12, 9, 0))
        self.assertEqual(diff, [])
        with open(path, encoding="utf-8") as f:
            page = f.read()
        for word in ("지금 현황", "주별 여유 자금", "낼 세금", "프로젝트 수익·비용", "A사 연례 컨퍼런스", "http-equiv='refresh'"):
            self.assertIn(word, page)
        # 기준일이 바뀌면 숫자가 달라지고 '바뀐 것'에 나온다
        path, diff = live.build(SAMPLE, self.out, dt.date(2026, 11, 13), dt.datetime(2026, 11, 12, 10, 0))
        names = [d[0] for d in diff]
        self.assertTrue(names)
        with open(path, encoding="utf-8") as f:
            self.assertIn("지난 현황 뒤 바뀐 것", f.read())

    def test_changes_lists_project_profit(self):
        a = {"bank": 100, "projects": {"P1": {"name": "가", "profit": 10}}}
        b = {"bank": 120, "avail_label": "4주째", "projects": {"P1": {"name": "가", "profit": 7}, "P2": {"name": "나", "profit": 3}}}
        got = live.changes(a, b)
        self.assertIn(("통장 잔액", 100, 120), got)
        self.assertIn(("가 예상 이익", 10, 7), got)
        self.assertIn(("새 프로젝트 나", None, 3), got)


if __name__ == "__main__":
    unittest.main()
