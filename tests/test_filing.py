import datetime as dt
import unittest

from ceo_report import filehelp, filing


def L(d, acct, code, vendor="", debit=None, credit=None, memo="", sort="", no=1):
    return {"date": d, "account": acct, "account_code": code, "vendor": vendor, "debit": debit, "credit": credit,
            "memo": memo, "sort": sort, "no": no}


J = [L(dt.date(2026, 10, 15), "예수금", "25400", "역삼세무서", credit=30_000, memo="사업소득지급시 소득세예수"),
     L(dt.date(2026, 10, 20), "예수금", "25400", "역삼세무서", credit=100_000, memo="급여지급시 소득세예수"),
     L(dt.date(2026, 7, 10), "예수금", "25400", "역삼세무서", debit=500_000, memo="근로소득세_26년상반기"),
     L(dt.date(2026, 1, 12), "예수금", "25400", "역삼세무서", debit=400_000, memo="근로소득세_25년하반기")]


class Calendar(unittest.TestCase):
    def test_deadlines_from_journal(self):
        rows = filing.calendar(J, dt.date(2026, 11, 12))
        names = [(r["기한"], r["신고"]) for r in rows]
        self.assertIn(("2026-11-30", "사업소득 간이지급명세서"), names)
        self.assertIn(("2027-01-11", "원천세 신고·납부 (반기)"), names)          # 1/10 일요일 → 월요일
        self.assertIn(("2027-02-01", "근로소득 간이지급명세서 (반기)"), names)  # 2026년은 반기 (매월은 2027년 지급분부터)
        self.assertIn(("2027-01-25", "부가세 2기 확정신고"), names)
        self.assertEqual([r["상태"] for r in rows if r["신고"] == "사업소득 간이지급명세서"][0], "18일 남음")

    def test_live_lines(self):
        rows = filing.calendar(J, dt.date(2026, 11, 20))
        self.assertTrue(any("사업소득 간이지급명세서" in x for x in filing.live_lines(rows, dt.date(2026, 11, 20))))


class Vat(unittest.TestCase):
    def test_boxes(self):
        S = [L(dt.date(2026, 8, 1), "수입수수료미수금", "10800", "고객", debit=1_100_000, sort="매출전표", no=1),
             L(dt.date(2026, 8, 1), "수입수수료", "40100", "", credit=1_000_000, sort="매출전표", no=1),
             L(dt.date(2026, 8, 1), "부가세예수금", "25500", "", credit=100_000, sort="매출전표", no=1),
             L(dt.date(2026, 8, 2), "소모품비", "83000", "", debit=200_000, sort="매입전표", no=2),
             L(dt.date(2026, 8, 2), "부가세대급금", "13500", "", debit=20_000, sort="매입전표", no=2),
             L(dt.date(2026, 8, 2), "미지급비용", "26200", "신한_5860", credit=220_000, sort="매입전표", no=2),
             L(dt.date(2026, 8, 3), "외주비", "53000", "", debit=500_000, sort="매입전표", no=3),
             L(dt.date(2026, 8, 3), "부가세대급금", "13500", "", debit=50_000, sort="매입전표", no=3),
             L(dt.date(2026, 8, 3), "미지급금", "25300", "업체", credit=550_000, sort="매입전표", no=3)]
        V = filehelp.vat(S, dt.date(2026, 7, 1), dt.date(2026, 9, 30))
        box = dict((r[0], r[3]) for r in V["rows"])
        self.assertEqual(box, {"1": 100_000, "10": 50_000, "14": 20_000})
        self.assertEqual(V["pay"], 30_000)

    def test_quarter(self):
        self.assertEqual(filehelp._quarter(dt.date(2026, 11, 12))[2], "2026년 2기 예정 (7~9월)")
        self.assertEqual(filehelp._quarter(dt.date(2027, 1, 5))[2], "2026년 2기 확정 (10~12월)")


if __name__ == "__main__":
    unittest.main()
