import csv
import datetime as dt
import os
import tempfile
import unittest

from ceo_report import taxreturn as tr

# 가짜 숫자 (과세표준 1억 → 산출 9백만, 최저한세 7백만)
ROWS = [["2025", "확정", "2025.01.01 ~ 2025.12.31", "1000000000", "97000000", "100000000", "9000000", "2000000", "7000000",
         "10000", "6990000", "900000", "7040000", "2026-03-10", "2026-03-31", "외부"],
        ["2026", "중간예납", "2026.01.01 ~ 2026.06.30", "600000000", "", "", "", "", "", "", "3495000", "", "3495000", "", "2026-08-20", ""]]


def folder():
    d = tempfile.mkdtemp()
    with open(os.path.join(d, tr.FILE), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(tr.COLUMNS)
        w.writerows(ROWS)
    return d


class Return(unittest.TestCase):
    def test_min_tax_and_notes(self):
        d = folder()
        last = tr.load(d)[(2025, "확정")]
        self.assertTrue(tr.at_min_tax(last))                 # 1억 × 7% = 7백만
        T = tr.for_report(d, dt.date(2026, 10, 31), 150_000_000, 15_000_000)
        self.assertEqual(T["adj"], 3_000_000)
        self.assertEqual(T["floor_now"], 10_500_000)
        txt = " ".join(T["notes"])
        self.assertIn("50,000원 다릅니다", txt)
        self.assertIn("3,495,000", txt)
        h = tr.render(T, lambda s: s)
        self.assertIn("최저한세 7%에 걸림", h)

    def test_no_file(self):
        self.assertIsNone(tr.for_report(tempfile.mkdtemp(), dt.date(2026, 10, 31)))

    def test_taxbreak_claim_row(self):
        from ceo_report import taxbreak
        d = folder()
        T = taxbreak.check(d, 2026, {"과밀억제": "아니오", "수도권": "예", "청년창업": "아니오", "신규창업": "예", "감면업종": "예",
                                      "작년감면": "없음", "연구전담": "아니오"})
        r = [x for x in T["rows"] if x[0].startswith("2025년분")][0]
        self.assertEqual(r[1], "해당 없음")


if __name__ == "__main__":
    unittest.main()
