"""변환 추가 점검: 중복 입력 의심 전표, 장부에 들어온 수동 출금 정리 (사용자 2026-11-04)."""
import csv
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import review_checks as RC  # noqa: E402

D = dt.date


def ln(day, no, code, debit, credit, vendor, kind="매출전표"):
    return {"date": day, "no": no, "account_code": code, "debit": debit, "credit": credit, "vendor": vendor,
            "vendor_norm": vendor, "type": kind}


class TestDuplicates(unittest.TestCase):
    def test_same_slip_twice(self):
        J = [ln(D(2026, 10, 22), "50008", "10800", 1100000, None, "가"), ln(D(2026, 10, 22), "50008", "41200", None, 1100000, "가"),
             ln(D(2026, 10, 22), "50012", "10800", 1100000, None, "가"), ln(D(2026, 10, 22), "50012", "41200", None, 1100000, "가"),
             ln(D(2026, 10, 22), "50013", "10800", 1100000, None, "나"), ln(D(2026, 10, 22), "50013", "41200", None, 1100000, "나")]
        self.assertEqual(RC.duplicate_slips(J), [(D(2026, 10, 22), ["50008", "50012"], 1100000)])

    def test_prior_year_and_small_ignored(self):
        J = [ln(D(2025, 10, 22), n, "10800", 1100000, None, "가") for n in ("1", "2")]
        J += [ln(D(2026, 10, 22), n, "10800", 5000, None, "가") for n in ("3", "4")]
        self.assertEqual(RC.duplicate_slips(J), [])


class TestArchive(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, RC.SCHEDULE), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["예정일", "입출금", "금액", "확정여부", "분류", "프로젝트번호", "거래처", "근거", "비고"])
            w.writerow(["2026-11-06", "출금", "500000", "확정", "급한 지급", "", "가상", "금요일 급한 출금", ""])
            w.writerow(["2026-11-06", "출금", "700000", "확정", "급한 지급", "", "가상", "장부에 없음", ""])
            w.writerow(["2026-11-20", "출금", "300000", "확정", "예정", "", "", "앞으로", ""])

    def tearDown(self):
        shutil.rmtree(self.dir, True)

    def rows(self, name):
        with open(os.path.join(self.dir, name), encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    def test_paid_line_moves_to_archive(self):
        J = [ln(D(2026, 11, 7), "1", "10300", None, 500000, "가상", "일반"),
             ln(D(2026, 11, 7), "2", "10300", None, 300000, "다른", "일반")]
        out = RC.archive_paid_schedule(self.dir, J, D(2026, 11, 10))
        self.assertIn("1줄", out[0])
        self.assertEqual([r["근거"] for r in self.rows(RC.SCHEDULE)], ["장부에 없음", "앞으로"])   # 미래 줄은 그대로
        arc = self.rows(RC.ARCHIVE)
        self.assertEqual([r["근거"] for r in arc], ["금요일 급한 출금"])
        self.assertIn("전표 1", arc[0]["정리 근거"])
        # 다시 돌려도 같은 출금을 두 번 쓰지 않는다
        RC.archive_paid_schedule(self.dir, J, D(2026, 11, 10))
        self.assertEqual(len(self.rows(RC.ARCHIVE)), 1)

    def test_other_vendor_not_matched(self):
        J = [ln(D(2026, 11, 6), "1", "10300", None, 500000, "딴곳", "일반")]
        RC.archive_paid_schedule(self.dir, J, D(2026, 11, 10))
        self.assertEqual(len(self.rows(RC.SCHEDULE)), 3)


if __name__ == "__main__":
    unittest.main()
