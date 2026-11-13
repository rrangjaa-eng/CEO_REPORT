import csv
import datetime as dt
import os
import tempfile
import unittest

from ceo_report import taxreturn as tr

ROWS = [["2025", "확정", "2025.02.01 ~ 2025.12.31", "2415897844", "152382770", "156565001", "14090850", "3131300", "10959550",
         "17990", "10941560", "1409080", "11010090", "2026-03-16", "2026-03-31", "외부"],
        ["2026", "중간예납", "2026.01.01 ~ 2026.06.30", "1980548075", "", "", "", "", "", "", "5470780", "", "5470780", "", "2026-08-18", ""]]


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
        self.assertTrue(tr.at_min_tax(last))                 # 156,565,001 × 7% = 10,959,550
        T = tr.for_report(d, dt.date(2026, 10, 31), 209_694_399, 21_938_880)
        self.assertEqual(T["adj"], 4_182_231)
        self.assertEqual(T["floor_now"], 14_678_607)
        txt = " ".join(T["notes"])
        self.assertIn("68,530원 다릅니다", txt)
        self.assertIn("5,470,780", txt)
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
