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

    def test_paid_early_moves_future_line(self):
        # 예정일(11/20)보다 9일 먼저 같은 거래처로 나감 → 아직 안 온 줄도 옮긴다 (사용자 2026-11-12)
        self.add(["2026-11-20", "지급", "800000", "확정", "기타지급", "", "나상", "직접 입력", ""])
        J = [ln(D(2026, 11, 11), "5", "10300", None, 800000, "나상", "일반")]
        out = RC.archive_paid_schedule(self.dir, J, D(2026, 11, 12))
        self.assertIn("1줄", out[0])
        arc = self.rows(RC.ARCHIVE)
        self.assertEqual(arc[0]["금액"], "800000")
        self.assertIn("예정일 9일 전", arc[0]["정리 근거"])

    def test_early_needs_same_vendor(self):
        # 일찍 나간 같은 금액이라도 거래처를 모르거나 다르면 맞추지 않는다
        J = [ln(D(2026, 11, 12), "6", "10300", None, 300000, "", "일반")]
        RC.archive_paid_schedule(self.dir, J, D(2026, 11, 12))
        self.assertEqual(len(self.rows(RC.SCHEDULE)), 3)

    def test_too_early_not_matched(self):
        self.add(["2026-12-20", "지급", "800000", "확정", "기타지급", "", "나상", "직접 입력", ""])
        J = [ln(D(2026, 11, 20), "5", "10300", None, 800000, "나상", "일반")]   # 30일 전: 지난달 같은 지급일 수 있음
        RC.archive_paid_schedule(self.dir, J, D(2026, 11, 25))
        self.assertEqual(len(self.rows(RC.SCHEDULE)), 4)

    def test_income_line_matched_by_bank_deposit(self):
        self.add(["2026-12-10", "입금", "5500000", "확정", "기타입금", "", "고객", "직접 입력", ""])
        J = [ln(D(2026, 11, 10), "7", "10300", 5500000, None, "고객", "일반")]   # 30일 먼저 입금 (입금은 45일까지)
        out = RC.archive_paid_schedule(self.dir, J, D(2026, 11, 12))
        self.assertIn("1줄", out[0])
        self.assertIn("보통예금 입금", self.rows(RC.ARCHIVE)[0]["정리 근거"])

    def test_deposit_does_not_settle_payment(self):
        J = [ln(D(2026, 11, 6), "8", "10300", 500000, None, "가상", "일반")]   # 같은 금액이 들어온 것은 지급이 아님
        RC.archive_paid_schedule(self.dir, J, D(2026, 11, 10))
        self.assertEqual(len(self.rows(RC.SCHEDULE)), 3)

    def test_late_payment_same_vendor(self):
        J = [ln(D(2026, 11, 16), "9", "10300", None, 700000, "가상", "일반")]   # 10일 늦게
        RC.archive_paid_schedule(self.dir, J, D(2026, 11, 17))
        self.assertIn("예정일 10일 뒤", self.rows(RC.ARCHIVE)[0]["정리 근거"])

    def test_archived_bank_line_not_reused(self):
        # 10월 줄에 쓴 출금을 다음 변환에서 11월 같은 금액 줄에 또 쓰지 않는다
        J = [ln(D(2026, 11, 7), "1", "10300", None, 500000, "가상", "일반")]
        RC.archive_paid_schedule(self.dir, J, D(2026, 11, 10))
        self.add(["2026-11-18", "지급", "500000", "확정", "기타지급", "", "가상", "다음 달", ""])
        RC.archive_paid_schedule(self.dir, J, D(2026, 11, 10))
        self.assertIn("다음 달", [r["근거"] for r in self.rows(RC.SCHEDULE)])
        self.assertEqual(len(self.rows(RC.ARCHIVE)), 1)

    def add(self, row):
        with open(os.path.join(self.dir, RC.SCHEDULE), "a", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow(row)


if __name__ == "__main__":
    unittest.main()
