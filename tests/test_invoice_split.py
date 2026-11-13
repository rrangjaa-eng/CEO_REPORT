"""여러 프로젝트로 나뉜 계산서 (사용자 2026-11-11).

세금계산서 한 장(매출전표)의 매출 줄이 여러 프로젝트로 나뉘어 있으면 계산서.csv 도 프로젝트마다 한 줄로 적는다.
한 프로젝트에 통째로 붙이면 나머지 프로젝트가 '발행 0원'(행사 후 미발행)으로 잘못 보인다.
"""
import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import convert_invoices as ci  # noqa: E402

DAY = dt.date(2026, 4, 20)


class Books(object):
    def __init__(self, journal):
        self.journal = journal


def jl(code, debit, credit, no="50010", day=DAY, vendor="가상고객S", memo=""):
    return {"date": day, "no": no, "account_code": code, "debit": debit, "credit": credit, "vendor": vendor,
            "vendor_norm": vendor, "memo": memo}


def rev(project, amount, no="50010", day=DAY, prior=False):
    ln = {"date": day, "no": no, "amount": amount, "project": project, "vendor_norm": "가상고객S"}
    if prior:
        ln["prior"] = True
    return ln


def sale(supply, vat, code, no="50010", day=DAY):
    return {"date": day, "no": no, "vendor": "가상고객S", "vendor_norm": "가상고객S", "item": "용역", "supply": supply, "vat": vat,
            "total": supply + vat, "code": code, "type": "", "deducted": 0}


CFG = {"receivable_codes": ("10800",), "cash_codes": ("10300",)}
PROJECTS = dict((k, {"dup": False, "client_norm": "가상고객S", "quote": None}) for k in ("26201", "26202", "26203"))


def build(sales_rows, rev_lines, journal, prev=()):
    sales = {"state": "ok", "rows": sales_rows, "notes": []}
    return ci.build_invoices(sales, Books(journal), {"lines": rev_lines, "summary": {}}, PROJECTS, list(prev), CFG)


class TestPortions(unittest.TestCase):
    def inv(self, supply=1000, no="50010"):
        return {"no": no, "date": DAY, "supply": supply}

    def test_lines_of_several_projects_are_grouped_by_project(self):
        got = ci._portions(self.inv(), [rev("26201", 600), rev("26202", 300), rev("26201", 100)])
        self.assertEqual(got, [("26201", 700), ("26202", 300)])

    def test_one_project_or_other_slip_or_wrong_sum_is_not_split(self):
        self.assertIsNone(ci._portions(self.inv(), [rev("26201", 600), rev("26201", 400)]))
        self.assertIsNone(ci._portions(self.inv(), [rev("26201", 600), rev("26202", 400, no="50011")]))
        self.assertIsNone(ci._portions(self.inv(), [rev("26201", 600), rev("26202", 300)]))
        self.assertIsNone(ci._portions(self.inv(no=""), [rev("26201", 600, no=""), rev("26202", 400, no="")]))

    def test_last_year_lines_and_unlinked_lines_keep_no_number(self):
        got = ci._portions(self.inv(), [rev("092", 500, prior=True), rev("26201", 300), rev(None, 200)])
        self.assertEqual(got, [("", 700), ("26201", 300)])

    def test_share_keeps_the_total(self):
        self.assertEqual(ci._share(100, [1, 1, 1]), [33, 33, 34])
        self.assertEqual(sum(ci._share(1448000, [1830213, 1353000, 1528800, 9767987])), 1448000)
        self.assertEqual(ci._share(0, [5, 5]), [0, 0])


class TestSplitRows(unittest.TestCase):
    JOURNAL = [jl("10800", 11000000, None), jl("41200", None, 7000000), jl("41200", None, 3000000), jl("25500", None, 1000000),
               jl("10300", 11000000, None, no="00007", day=dt.date(2026, 6, 16)),
               jl("10800", None, 11000000, no="00007", day=dt.date(2026, 6, 16))]
    REV = [rev("26201", 7000000), rev("26202", 3000000)]

    def test_each_project_gets_its_own_row_and_the_sums_stay(self):
        t = build([sale(10000000, 1000000, "26201")], self.REV, self.JOURNAL)
        got = [(r["프로젝트번호"], r["공급가액"], r["부가세"], r["입금일"], r["입금액"]) for r in t.rows]
        self.assertEqual(got, [("26201", "7000000", "700000", "2026-06-16", "7700000"),
                               ("26202", "3000000", "300000", "2026-06-16", "3300000")])
        self.assertTrue(all(c.source == c.csv for c in t.checks if c.label in ("계산서 줄 수", "공급가액 합계", "부가세 합계")),
                        [(c.label, c.source, c.csv) for c in t.checks])
        self.assertTrue(any("여러 프로젝트로 나뉜 계산서 1장 → 프로젝트마다 한 줄씩 2줄" in n for n in t.notes))

    def test_single_project_invoice_is_written_as_before(self):
        t = build([sale(10000000, 1000000, "26201")], [rev("26201", 10000000)], self.JOURNAL)
        self.assertEqual([(r["프로젝트번호"], r["공급가액"]) for r in t.rows], [("26201", "10000000")])
        self.assertFalse(any("여러 프로젝트로 나뉜" in n for n in t.notes))

    def test_due_date_is_carried_from_whole_row_and_later_from_split_rows(self):
        whole = [{"프로젝트번호": "26201", "거래처": "가상고객S", "발행일": "2026-04-20", "구분": "발행", "공급가액": "10000000",
                  "부가세": "1000000", "입금예정일": "2026-06-30", "예정일확정": "Y", "입금일": "", "입금액": ""}]
        t = build([sale(10000000, 1000000, "26201")], self.REV, self.JOURNAL[:4], whole)
        self.assertEqual([(r["입금예정일"], r["예정일확정"]) for r in t.rows], [("2026-06-30", "Y")] * 2)
        again = [dict(r) for r in t.rows]
        again[1]["입금예정일"] = "2026-07-15"
        t2 = build([sale(10000000, 1000000, "26201")], self.REV, self.JOURNAL[:4], again)
        self.assertEqual([r["입금예정일"] for r in t2.rows], ["2026-06-30", "2026-07-15"])


if __name__ == "__main__":
    unittest.main()
