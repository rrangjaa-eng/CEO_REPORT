import csv
import datetime as dt
import os
import shutil
import tempfile
import unittest

from ceo_report import payroll


def write(path, cols, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)


class Detail(Base):
    def setUp(self):
        super().setUp()
        write(os.path.join(self.d, "사원.csv"),
              ["사원명", "생년월일", "입사일", "퇴사일", "고용형태", "주소정근로시간", "임원", "부양가족수", "자녀수"],
              [["김정상", "1990-01-01", "2024-03-01", "", "정규", "40", "", "1", "1"],
               ["이저임", "1995-05-05", "2026-10-15", "", "정규", "40", "", "0", "0"],
               ["대표", "1970-01-01", "2025-01-01", "", "임원", "40", "예", "0", "0"]])
        rows = []
        for m in ("2026-09", "2026-10"):
            rows += [[m, "김정상", "지급", "기본급", "3000000"], [m, "김정상", "지급", "식대", "200000"],
                     [m, "김정상", "공제", "국민연금", "142500"], [m, "김정상", "공제", "건강보험", "107850"],
                     [m, "김정상", "공제", "장기요양보험", "14170"], [m, "김정상", "공제", "고용보험", "27000"],
                     [m, "김정상", "공제", "소득세", "84850"], [m, "김정상", "공제", "지방소득세", "8480"]]
        rows += [["2026-10", "이저임", "지급", "기본급", "2000000"],      # 2,000,000/209 = 9,569 < 10,320, 공제 없음
                 ["2026-11", "이저임", "지급", "기본급", "2000000"],
                 ["2026-10", "대표", "지급", "기본급", "1000000"]]
        write(os.path.join(self.d, "급여명세.csv"), ["연월", "사원명", "구분", "항목", "금액"], rows)

    def test_check(self):
        C = payroll.check(self.d, "2026-10", holders=("대표",))
        got = dict(((a, b), (c, d)) for a, b, c, d in C)
        self.assertNotIn("대표", [a for a, *_ in C])
        self.assertEqual(got[("김정상", "최저임금")][0], "ok")
        self.assertEqual(got[("김정상", "4대보험")], ("ok", "요율대로 공제됨"))
        self.assertEqual(got[("이저임", "최저임금")][0], "warn")
        self.assertEqual(got[("이저임", "4대보험")][0], "warn")
        self.assertEqual(got[("이저임", "입사 달 일할")][0], "warn")
        self.assertIn("퇴직금", [b for a, b, *_ in C if a == "김정상"])
        self.assertIn("연차 15일", got[("김정상", "연차")][1])

    def test_yearend(self):
        Y = payroll.yearend(self.d, 2026, dt.date(2026, 10, 31), holders=("대표",))
        y = dict((r["name"], r) for r in Y)["김정상"]
        self.assertEqual(y["months"], 2)
        self.assertEqual(y["gross"], 36_000_000)            # (3.2백만 − 식대 20만) × 12
        self.assertIsNotNone(y["diff"])
        self.assertGreater(y["tax"], 0)

    def test_officer_skipped_and_report(self):
        C = payroll.check(self.d, "2026-10")          # 사원.csv 임원=예 → 근로자 점검 제외
        self.assertNotIn("대표", [a for a, *_ in C])
        h = payroll.for_report(self.d, dt.date(2026, 11, 30))
        self.assertIn("2026-11 급여 점검", h)
        self.assertNotIn("대표", h)

    def test_last_year_yearend_used(self):
        base = dict((r["name"], r) for r in payroll.yearend(self.d, 2026, dt.date(2026, 10, 31)))["김정상"]
        cols = payroll.YE_COLUMNS
        v = dict.fromkeys(cols, "0")
        v.update({"귀속연도": "2025", "사원명": "김정상", "기본공제인원": "4", "경로우대": "1", "자녀세액공제인원": "2",
                  "그밖소득공제": "2000000", "특별세액공제": "300000"})
        write(os.path.join(self.d, "연말정산.csv"), cols, [[v[c] for c in cols]])
        y = dict((r["name"], r) for r in payroll.yearend(self.d, 2026, dt.date(2026, 10, 31)))["김정상"]
        self.assertLess(y["tax"], base["tax"])
        self.assertGreater(y["diff"], base["diff"])
        self.assertIn("2025년 연말정산 공제 그대로 (본인 포함 4명, 자녀 2명)", y["notes"])

    def test_render(self):
        h = payroll.render(payroll.check(self.d, "2026-10"), payroll.yearend(self.d, 2026, dt.date(2026, 10, 31)),
                           lambda s: s, "2026-10", 2026)
        self.assertIn("확인 필요", h)
        self.assertIn("연말정산 예상", h)


class TotalsOnly(Base):
    def test_fallback(self):
        write(os.path.join(self.d, "사원급여.csv"), ["연월", "사원명", "급여"], [["2026-10", "박총액", "2500000"]])
        C = payroll.check(self.d, "2026-10")
        self.assertEqual([(a, b, c) for a, b, c, _ in C], [("박총액", "최저임금", "info")])
        Y = payroll.yearend(self.d, 2026, dt.date(2026, 10, 31))
        self.assertIsNone(Y[0]["paid"])
        self.assertIn("급여 명세 없음", Y[0]["notes"][0])

    def test_no_detail_files_no_chapter(self):
        write(os.path.join(self.d, "사원급여.csv"), ["연월", "사원명", "급여"], [["2026-10", "박총액", "2500000"]])
        self.assertIsNone(payroll.for_report(self.d, dt.date(2026, 10, 31)))

    def test_empty(self):
        self.assertEqual(payroll.check(self.d, "2026-10"), [])
        self.assertEqual(payroll.yearend(self.d, 2026, dt.date(2026, 10, 31)), [])


if __name__ == "__main__":
    unittest.main()
