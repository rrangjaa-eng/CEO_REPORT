import csv
import os
import tempfile
import unittest

from ceo_report import taxbreak as tb


def folder(pay, base=200_000_000, tax=20_000_000, year=2026):
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "사원급여.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["연월", "부서", "사원명", "급여"])
        for ym, names in pay.items():
            for n in names:
                w.writerow([ym, "팀", n, "3000000"])
    with open(os.path.join(d, "세금예상.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["세목", "대상기간", "납부예정일", "금액", "상태", "근거", "과세표준", "산출세액", "기납부"])
        w.writerow(["법인세", "%d년 (1월~10월 장부 기준)" % year, "%d-03-31" % (year + 1), tax, "예상", "", base, tax, 0])
    return d


YES = {"과밀억제": "아니오", "수도권": "예", "청년창업": "아니오", "신규창업": "예", "감면업종": "예", "작년감면": "둘 다", "연구전담": "아니오"}


def row(T, name):
    return [r for r in T["rows"] if r[0].startswith(name)][0]


class Startup(unittest.TestCase):
    def test_rate_by_region_and_age(self):
        d = folder({})
        T = tb.check(d, 2026, YES)
        self.assertEqual(row(T, "창업중소기업")[1:3], ("해당", 10_000_000))   # 과밀 밖, 35세 이상 → 50%
        T = tb.check(d, 2026, dict(YES, 과밀억제="예"))
        self.assertEqual(row(T, "창업중소기업")[1], "해당 없음")
        T = tb.check(d, 2026, dict(YES, 과밀억제="예", 청년창업="예"))
        self.assertEqual(row(T, "창업중소기업")[2], 10_000_000)

    def test_unknown_industry_needs_check_not_counted(self):
        T = tb.check(folder({}), 2026, dict(YES, 감면업종="모름"))
        self.assertEqual(row(T, "창업중소기업")[1], "확인 필요")
        self.assertEqual(T["total"], 0)

    def test_min_tax_caps_total(self):
        T = tb.check(folder({}, base=200_000_000, tax=20_000_000), 2026, YES)
        self.assertEqual(T["total"], 6_000_000)   # 2천만 − 최저한세 1,400만
        self.assertIn("최저한세", T["note"])

    def test_period_over(self):
        self.assertEqual(row(tb.check(folder({}, year=2030), 2030, YES), "창업중소기업")[1], "해당 없음")


class Hiring(unittest.TestCase):
    def test_increase_counts_and_shareholders_excluded(self):
        pay = dict(("2025-%02d" % m, ["대표", "a", "b"]) for m in range(1, 13))
        pay.update(("2026-%02d" % m, ["대표", "a", "b", "c", "d"]) for m in range(1, 13))
        T = tb.check(folder(pay), 2026, YES, holders=["대표"])
        r = row(T, "통합고용")
        self.assertEqual(r[1], "해당")
        self.assertEqual(r[2], 4 * 8_500_000)   # 2025년 +2명(첫해, 0명에서) + 2026년 +2명, 수도권 그 밖 850만

    def test_prev_year_unknown(self):
        pay = dict(("2026-%02d" % m, ["a"]) for m in range(1, 11))
        r = row(tb.check(folder(pay), 2026, YES), "통합고용")
        self.assertEqual(r[1], "확인 필요")
        self.assertIn("2025년 인원을 몰라", r[3])

    def test_missed_last_year_claim(self):
        T = tb.check(folder({}), 2026, dict(YES, 작년감면="없음"))
        self.assertIn("경정청구", row(T, "2025년분")[0])

    def test_render(self):
        from ceo_report.util import esc
        h = tb.render(tb.check(folder({}), 2026, YES), esc)
        self.assertIn("세무사 확인", h)
        self.assertIn("창업중소기업", h)


if __name__ == "__main__":
    unittest.main()
