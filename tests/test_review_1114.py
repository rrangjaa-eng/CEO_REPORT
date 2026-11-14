"""2026-11-14 코덱스 전체 검토에서 확인한 오류를 다시 생기지 않게 막는 시험."""
import datetime as dt
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import gate  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
D = dt.date
ON = {gate.TEST_OFF: ""}


class TestGate(unittest.TestCase):
    @mock.patch.dict(os.environ, ON)
    def test_setting_cannot_stretch_beyond_7_days(self):
        R = {"asof": D(2026, 11, 14), "settings_num": {"위험_자료경과일": 30},
             "fundplan": {"used": True, "stamp": D(2026, 11, 13)}, "auto_facts": {"book_date": "2026-11-01"}}
        self.assertTrue(gate.problems(R))
        R["settings_num"]["위험_자료경과일"] = 3
        R["auto_facts"]["book_date"] = "2026-11-10"
        self.assertTrue(gate.problems(R))   # 더 짧게는 쓸 수 있다

    @mock.patch.dict(os.environ, ON)
    def test_blocked_mgmt_and_live_numbers_are_blank(self):
        R = compute(load(SAMPLE), "weekly", D(2026, 11, 6))   # 예시 자료엔 자금계획서가 없다
        self.assertIsNotNone(R["s2"]["periods"][-1]["firm"]["avail"])
        self.assertTrue(gate.blank_funds(R))
        self.assertIsNone(R["s1"]["total"])
        self.assertIsNone(R["s2"]["start"])
        for p in R["s2"]["periods"]:
            self.assertIsNone(p["firm"]["avail"])
            self.assertIsNone(p["all"]["bal"])
        from ceo_report.render import render
        page = render(R, "mgmt")
        self.assertIn("비웠습니다", page)

    @mock.patch.dict(os.environ, ON)
    def test_live_page_blank(self):
        from ceo_report import live
        with tempfile.TemporaryDirectory() as out:
            path, _ = live.build(SAMPLE, out, D(2026, 11, 6))
            with open(path, encoding="utf-8") as f:
                page = f.read()
            self.assertIn("비웠습니다", page)

    def test_evidence_keeps_warning(self):
        from ceo_report import evidence
        mg = ("<html><head><title>x 경영관리 보고</title></head><body>" + gate.banner(["자금계획서 없음"])
              + "<table><tr><td><b>근거 2-1</b></td><td>일정</td><td><a href='#s2'>보기</a></td></tr></table>"
              + "<h2 id='s2'>2. 일정</h2><p>표</p><h2 id='s3'>3</h2></body></html>")
        page = evidence.build(mg, ["2-1"])
        self.assertIn("class='gate'", page)

    def test_latest_report_does_not_open_old_pdf_when_blocked(self):
        from ceo_report import winstate
        with tempfile.TemporaryDirectory() as out:
            base = os.path.join(out, "2026-11-14_주간")
            open(base + "_대표보고 (11-13 10시00분 만듦).pdf", "w").close()
            with open(base + "_대표보고.html", "w", encoding="utf-8") as f:
                f.write(gate.stop_page("주간 대표보고", ["자금계획서 없음"]))
            got = winstate.latest_reports(out)
            self.assertTrue(got["대표"].endswith(".html"))

    def test_default_min_cash_is_100m(self):
        from ceo_report.data import DEFAULT_SETTINGS
        self.assertEqual(DEFAULT_SETTINGS["위험_최소보유현금"], "100000000")


if __name__ == "__main__":
    unittest.main()


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestFunds(unittest.TestCase):
    def _books(self, lines):
        from ceo_report import wehago
        b = wehago.Books()
        b.state, b.book_date = "ok", D(2026, 11, 12)
        for no, day, code, account, debit, credit, vendor in lines:
            b.journal.append({"date": day, "no": no, "account_code": code, "account": account, "debit": debit,
                              "credit": credit, "vendor": vendor, "memo": "", "sort": ""})
        return b

    def test_one_slip_not_used_for_two_plan_lines(self):
        from ceo_report import fundplan
        from test_fundplan import plan_row
        rows = [plan_row("2026-11-13", "지급", "가상음향", 1000000), plan_row("2026-11-20", "지급", "가상음향", 1000000)]
        books = self._books([("7", D(2026, 11, 10), "25300", "미지급금", 1000000, None, "가상음향"),
                             ("7", D(2026, 11, 10), "10300", "보통예금", None, 1000000, "가상음향")])
        fundplan.settle(rows, books, D(2026, 11, 12))
        self.assertEqual(sorted(r["상태"] for r in rows), ["예정", "이미 지급"])

    def test_nine_plan_lines_same_vendor_do_not_crash(self):
        from ceo_report import fundplan
        from test_fundplan import plan_row
        rows = [plan_row("2026-11-%02d" % (13 + i % 5), "지급", "가상음향", (i + 1) * 1000000) for i in range(9)]
        books = self._books([("1", D(2026, 11, 10), "25300", "미지급금", 15000000, None, "가상음향"),
                             ("2", D(2026, 11, 11), "25300", "미지급금", 20000000, None, "가상음향")])
        fundplan.settle(rows, books, D(2026, 11, 12))   # 예전엔 KeyError

    def test_plan_line_does_not_replace_other_vendor_by_amount(self):
        from ceo_report import fundplan
        ev = {"date": D(2026, 11, 20), "io": "out", "amount": 30000000, "firm": True, "desc": "B상사", "vendor_code": "222",
              "source": "자금일정", "cat": "기타지급"}
        plan = [{"date": D(2026, 11, 20), "io": "지급", "cat": "미지급금 지급", "vendor": "A상사", "vendor_code": "000111",
                 "amount": 30000000, "ym": "2026-11", "stamp": D(2026, 11, 13), "state": "예정", "basis": "", "file": ""}]
        new, info = fundplan.apply([ev], plan, D(2026, 11, 14), 7, cash_date=D(2026, 11, 13), txns=[])
        self.assertEqual(sum(e["amount"] for e in new if e["io"] == "out"), 60000000)

    def test_shared_vendor_schedule_subtracted_once(self):
        from ceo_report import debts
        rows = [{"kind": debts.PAYABLE, "vcode": "5", "vendor": "가상", "balance": 10000000, "account": "미지급금", "date": "2026-11-13"},
                {"kind": debts.PAYABLE, "vcode": "5", "vendor": "가상", "balance": 10000000, "account": "미지급비용", "date": "2026-11-13"}]
        ev = [{"io": "out", "amount": 10000000, "date": D(2026, 11, 20), "vendor_code": "5", "desc": "가상", "cat": ""}]
        C = debts.compare(rows, ev, D(2026, 11, 14))
        self.assertEqual(C["unscheduled_total"], 10000000)

    def test_short_from_today(self):
        from ceo_report import insights
        R = {"asof": D(2026, 11, 14), "s2": {"start": 90000000, "min_cash": 100000000, "dated": []}}
        self.assertEqual(insights._first_short(R, "firm")[0], D(2026, 11, 14))


class TestConvert(unittest.TestCase):
    def test_closing_keeps_real_accrual_expense(self):
        from ceo_report.convert import closing_pl_line
        sorts = ("결산전표",)
        keep = closing_pl_line({"sort": "결산전표", "account_code": "80800", "account": "퇴직급여", "debit": 5000000, "credit": None}, sorts)
        self.assertEqual(keep["debit"], 5000000)
        self.assertIsNone(closing_pl_line({"sort": "결산전표", "account_code": "45100", "account": "원가(도)", "debit": None,
                                           "credit": 9000000}, sorts))

    def test_wehago_raw_file_without_year_is_not_used(self):
        import json
        from ceo_report import wehago_raw
        with tempfile.TemporaryDirectory() as t:
            for n, year in (("a 결산_고정자산관리대장 자동수집.json", None), ("b 결산_고정자산관리대장 자동수집.json", 2026)):
                d = {"종류": "결산원본", "화면": "고정자산관리대장", "수집시각": "2026-11-13", "응답": []}
                if year:
                    d["연도"] = year
                with open(os.path.join(t, n), "w", encoding="utf-8") as f:
                    json.dump(d, f, ensure_ascii=False)
            self.assertEqual([k[1] for k in wehago_raw.files(t)], [2026])


class TestTaxClose(unittest.TestCase):
    def test_partial_receipt_counts_rest_as_open(self):
        import tempfile, shutil, datetime as dt
        from ceo_report import cashflow as C
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        with open(os.path.join(d, "계산서.csv"), "w", encoding="utf-8-sig") as f:
            f.write("프로젝트번호,거래처,발행일,구분,공급가액,부가세,입금예정일,예정일확정,입금일,입금액\n")
            f.write(",가,2026-09-01,발행,1000,100,,,2026-10-05,600\n")
        c = C.collection(d, dt.date(2026, 10, 1), dt.date(2026, 10, 31))
        self.assertEqual(c["open_total"], 500)   # 1,100 중 600만 받음 → 500 남음
