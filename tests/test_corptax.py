"""법인세 예상 (사용자 2026-11-04). 합성 숫자만 쓴다."""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from ceo_report import corptax  # noqa: E402


class TestRates(unittest.TestCase):
    def test_2026_brackets_10_20(self):
        self.assertEqual(corptax.corp_tax(100_000_000, "2026"), 10_000_000)
        self.assertEqual(corptax.corp_tax(300_000_000, "2026"), 20_000_000 + 20_000_000)
        self.assertEqual(corptax.corp_tax(300_000_000, "2025"), 18_000_000 + 19_000_000)
        self.assertEqual(corptax.corp_tax(-5, "2026"), 0)
        self.assertIsNone(corptax.corp_tax(None, "2026"))


class TestDepreciation(unittest.TestCase):
    acc = [{"ym": "2025-12", "name": "감가상각비(판)", "amount": 12_000_000},
           {"ym": "2026-03", "name": "복리후생비(판)", "amount": 5}]

    def test_last_year_full_amount_by_default(self):   # 사용자 2026-11-04: 작년 금액 전부
        d = corptax.depreciation(self.acc, {}, "2026-10")
        self.assertEqual((d["annual"], d["extra"], d["cur"], d["source"]), (12_000_000, 12_000_000, None, "작년 장부"))

    def test_prorate_mode(self):
        d = corptax.depreciation(self.acc, {}, "2026-10", "prorate")
        self.assertEqual((d["extra"], d["cur"]), (10_000_000, 1_000_000))

    def test_manual_wins_and_booked_not_double_counted(self):
        acc = self.acc + [{"ym": "2026-06", "name": "감가상각비(판)", "amount": 4_000_000}]
        d = corptax.depreciation(acc, {"2026": 24_000_000}, "2026-10")
        self.assertEqual((d["annual"], d["booked"], d["extra"], d["source"]), (24_000_000, 4_000_000, 20_000_000, "직접 입력"))

    def test_unknown(self):
        self.assertIsNone(corptax.depreciation([], {}, "2026-10")["extra"])

    def test_apply_lowers_pretax(self):
        N = corptax.apply({"pretax": 100}, 30)
        self.assertEqual((N["pretax"], N["dep"]), (70, 30))
        self.assertEqual(corptax.apply({"pretax": None}, 30)["pretax"], None)


class TestSave(unittest.TestCase):
    def test_save_read_and_clear(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        corptax.save(tmp, "2026", "24,000,000")
        self.assertEqual(corptax.read(tmp), {"2026": 24_000_000})
        corptax.save(tmp, "2026", "")
        self.assertEqual(corptax.read(tmp), {})
        with self.assertRaises(ValueError):
            corptax.save(tmp, "26", "1")


class TestFromJournal(unittest.TestCase):
    def test_pretax_minus_dep_minus_prepaid(self):
        sys.path.insert(0, HERE)
        from test_dept import line
        from ceo_report import convert
        D = dt.date
        j = [line(D(2025, 12, 31), "81800", "감가상각비(판)", 12_000_000),
             line(D(2026, 3, 5), "41200", "용역매출", credit=300_000_000),
             line(D(2026, 3, 5), "61000", "외주비(도)", 100_000_000),
             line(D(2026, 4, 5), "80200", "직원급여(판)", 50_000_000),
             line(D(2026, 5, 5), "92200", "정부지원금수익", credit=10_000_000),
             line(D(2026, 8, 31), "13600", "선납세금", 4_000_000),
             line(D(2026, 11, 2), "41200", "용역매출", credit=999_999_999)]   # 기준일 달(11월)은 아직 넣지 않음
        cfg = dict(convert.DEFAULT_CONFIG)
        rows, note = corptax.from_journal(j, cfg, D(2026, 11, 4), {})
        ct, lt = rows
        # 300 − 100 − 50 + 10 = 160, − 감가상각 12 = 148 (백만) → 14.8 − 선납 4 = 10.8
        self.assertEqual((ct["과세표준"], ct["산출세액"], ct["기납부"], ct["금액"]), ("148000000", "14800000", "4000000", "10800000"))
        self.assertEqual((ct["납부예정일"], ct["상태"], lt["세목"], lt["금액"], lt["납부예정일"]),
                         ("2027-03-31", "예상", "법인지방소득세", "1480000", "2027-04-30"))
        self.assertIn("1월~10월", ct["대상기간"])


class TestClosingSlips(unittest.TestCase):
    """2026-11-04 실제 2025 분개장: 결산전표가 (도) 원가를 행사매출원가로 옮기고 감가상각비를 넣고, 잉여금관련전표가 손익을 0으로 돌린다."""

    def journal(self):
        sys.path.insert(0, HERE)
        from test_dept import line
        D = dt.date(2025, 12, 31)

        def c(ln, sort):
            ln["sort"] = sort
            return ln
        return [line(dt.date(2025, 6, 5), "61000", "외주비(도)", 70_000_000),
                line(dt.date(2025, 6, 5), "81100", "복리후생비(판)", 3_000_000),
                c(line(D, "61000", "외주비(도)", credit=70_000_000), "결산전표"),
                c(line(D, "45100", "행사매출원가", 70_000_000), "결산전표"),
                c(line(D, "17000", "진행중행사", 70_000_000, 70_000_000), "결산전표"),
                c(line(D, "81800", "감가상각비(판)", 6_000_000), "결산전표"),
                c(line(D, "20900", "감가상각누계액", credit=6_000_000), "결산전표"),
                c(line(D, "81800", "감가상각비(판)", credit=6_000_000), "잉여금관련전표"),
                c(line(D, "81100", "복리후생비(판)", credit=3_000_000), "잉여금관련전표"),
                c(line(D, "37500", "이월이익잉여금", 9_000_000), "잉여금관련전표")]

    def test_drop_keeps_only_dep_debit_and_balance_lines(self):
        from ceo_report import convert

        class B(object):
            pass
        b = B()
        b.journal, b.notes = self.journal(), []
        self.assertEqual(convert.drop_closing_pl(b, dict(convert.DEFAULT_CONFIG)), 4)
        dep = [ln for ln in b.journal if ln["account_code"] == "81800"]
        self.assertEqual([(ln["debit"], ln["credit"]) for ln in dep], [(6_000_000, None)])
        self.assertEqual(sum(ln["debit"] or 0 for ln in b.journal if ln["account_code"] == "61000"), 70_000_000)
        self.assertTrue(any(ln["account_code"] == "37500" for ln in b.journal))   # 대차대조표 줄은 남김 (결산한 해 판단)
        self.assertIn("결산 전표 손익 줄 4건 뺌", b.notes[0])

    def test_last_year_dep_from_closing_slip(self):
        from ceo_report import convert
        rows, _ = corptax.from_journal(self.journal(), dict(convert.DEFAULT_CONFIG), dt.date(2026, 11, 4), {})
        self.assertIn("감가상각비 예상 6,000,000", rows[0]["근거"])


class TestReport(unittest.TestCase):
    def test_monthly_shows_final_pretax_tax_minus_prepaid(self):
        from ceo_report.calc import compute
        from ceo_report.data import load
        from ceo_report.render import render
        R = compute(load(os.path.join(os.path.dirname(HERE), "입력양식", "샘플")), "monthly", dt.date(2026, 10, 31))
        for ed in ("ceo", "mgmt"):
            h = render(R, ed)
            self.assertNotIn("영업외 수익 뺀 세전 이익 기준", h)   # 사용자 2026-11-04: 최종 세전 이익 기준만
            # 두 판 모두 한 줄 (월간 3쪽, 사용자 2026-11-04), 표는 경영관리용에만
            self.assertIn("법인세 예상 13,500,000 + 지방소득세 1,350,000 − 중간예납 등 기납부 4,000,000 = 납부 10,850,000 (2027-03-31 예상)", h)
            if ed == "mgmt":
                self.assertIn("법인세 예상 (1월~10월 누적 세전 이익 기준)", h)
                row = h.split("<table class='pt tx'>")[1].split("</table>")[0]
                for v in ("135,000,000", "13,500,000", "4,000,000", "9,500,000", "1,350,000", "10,850,000"):
                    self.assertIn(v, row)
            else:
                self.assertNotIn("<table class='pt tx'>", h)
            self.assertIn("− 감가상각비 (예상, 작년 연간 12,000,000)", h)
        ev = [(e["date"], e["amount"]) for e in R["events"] if e["cat"].startswith("법인")]
        self.assertEqual(ev, [(dt.date(2027, 3, 31), 9_500_000), (dt.date(2027, 4, 30), 1_350_000)])   # 지급 예상에 들어감


if __name__ == "__main__":
    unittest.main()
