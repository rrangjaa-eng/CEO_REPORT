"""02-REVIEW.md 결함 고정 시험 (Phase 2 코드 검토: CR-01..CR-05, WR-01..WR-06).

검토의 재현 스크립트(repro_a..g)를 그대로 시험으로 옮겼다. 모든 장부·스냅숏은 가상 자료이고 임시 폴더에만 쓴다.
실제 입력/·수집/ 폴더와 실제 WEHAGO 파일은 열지 않는다. 결함마다 (1) 고친 결과와 (2) 변환의 대조가 고치기 전의 결과를
'불일치' 또는 '판단 불가'로 잡는지 둘 다 본다.
"""
import datetime as dt
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import convert, convert_projects, convert_xchk, linking, wehago  # noqa: E402
from ceo_report.approval import project_code  # noqa: E402

ASOF = dt.date(2026, 10, 31)
NOW = dt.datetime(2026, 10, 31, 9, 0)


def jl(date, no, code, account, debit, credit, vendor, memo="", sort="대체"):
    return {"date": date, "no": str(no), "account_code": code, "account": account, "debit": debit, "credit": credit,
            "vendor": vendor, "memo": memo, "sort": sort, "code": project_code(memo),
            "vendor_norm": wehago.norm_vendor(vendor)}


def inv(date, vendor, item, supply, vat):
    return {"date": date, "no": "", "vendor": vendor, "item": item, "supply": supply, "vat": vat,
            "total": supply + vat, "code": project_code(item), "vendor_norm": wehago.norm_vendor(vendor)}


class Snap(object):
    def __init__(self, payments, projects):
        self.payments, self.projects = payments, projects


def pay(no, title, vendor, reg, amount, boss="승인"):
    return {"번호": str(no), "행사명": title, "파트너": vendor, "등록일": reg, "행사일": "", "금액": str(amount),
            "지급요청일": "", "등록자": "x", "팀장승인": "승인", "관리팀승인": "승인", "사장님승인": boss}


def proj(no, title, budget="1000000000", event="2026-11-20"):
    return {"번호": str(no), "클라이언트": "가상고객", "담당자": "", "PO번호": "", "행사일": event, "행사명": title,
            "국": "", "팀": "가상팀", "등록자": "", "계산서": "", "사전견적": "", "견적금액": "", "실행가": budget,
            "수익률": "", "승인_담당자": "", "승인_팀장": "", "승인_관리팀": "", "승인_대표이사": "", "pro_num": ""}


def books_of(journal, ledger=(), einvoice=()):
    b = wehago.Books()
    b.state, b.book_date = "ok", ASOF
    b.journal, b.ledger, b.einvoice = list(journal), list(ledger), list(einvoice)
    return b


class Run(object):
    """변환과 같은 순서로 연결 → 요청 대조 → 프로젝트집행."""

    def __init__(self, journal, payments, projects, ledger=(), prev=(), link_days=90):
        self.cfg = convert.Config(convert.DEFAULT_CONFIG)
        self.books = books_of(journal, ledger)
        self.snap = Snap(payments, projects)
        self.requests = linking.requests_of(self.snap, ASOF, NOW)
        self.projects = linking.projects_of(self.snap)
        self.costs = linking.link_costs(self.books, self.requests, self.projects, {}, link_days)
        self.revenue = linking.link_revenue(self.books, self.projects, {})
        self.match = wehago.match_requests(self.books, self.requests)
        self.execs = convert_projects.build_execs(self.books, self.costs, self.requests, self.match, list(prev), self.cfg,
                                                  self.projects)

    def xchk(self, project_rows=()):
        return convert_xchk.build_xchk(self.books, self.costs, self.revenue, self.projects, self.requests, self.match,
                                       list(project_rows), {"장부 기준일": ASOF.isoformat()}, self.cfg, {})


def naming(table, number):
    pattern = re.compile(r"지급요청 %s(?!\d)" % number)
    return [r for r in table.rows if pattern.search(r["근거"])]


def money(r):
    return int(r["공급가액"] or 0) + int(r["부가세"] or 0)


def unpaid_total(table):
    return sum(money(r) for r in table.rows if r["상태"] in ("요청미지급", "카드사용미결제"))


def results(table):
    return dict((c.label, convert.check_result(c)) for c in table.checks)


def new_tmp(test):
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    return tmp


# ───────────── CR-01: 자동 연결(D-38)된 요청은 그 WEHAGO 줄과 같은 빚이다 ─────────────
D40 = dt.date(2026, 10, 30)
AUTO_JOURNAL = [jl(D40, 40, "61101", "행사외주비(도)", 200000, None, "가상조명", "조명 추가"),
                jl(D40, 40, "13500", "부가세대급금", 20000, None, "가상조명"),
                jl(D40, 40, "25300", "미지급금", None, 220000, "가상조명")]
AUTO_LEDGER = [inv(D40, "가상조명", "조명 추가", 200000, 20000)]   # 품명에 [코드]가 없다 (그래서 자동 연결이 필요했다)
AUTO_PAYMENTS = [pay(6001, "[26220] 가상 전시", "가상조명", "2026-10-20 09:00:00", 220000)]
AUTO_PROJECTS = [proj(1, "[26220] 가상 전시")]


class TestCR01AutoLinkedRequest(unittest.TestCase):
    def test_auto_linked_request_annotates_the_wehago_row_instead_of_a_second_row(self):
        r = Run(AUTO_JOURNAL, AUTO_PAYMENTS, AUTO_PROJECTS, AUTO_LEDGER)
        ln = r.costs["lines"][0]
        self.assertEqual((ln["basis"], ln["project"], ln["request"]), ("자동", "26220", "6001"))
        self.assertEqual(r.match["rows"]["6001"]["status"], "계산서 없음")
        rows = naming(r.execs, "6001")
        self.assertEqual(len(rows), 1, r.execs.rows)
        self.assertTrue(rows[0]["근거"].startswith("WEHAGO 2026-10-30 전표 40"), rows[0])
        self.assertIn("· 지급요청 6001", rows[0]["근거"])
        self.assertEqual(unpaid_total(r.execs), 220000)
        self.assertFalse([n for n in r.execs.notes if "중복 가능" in n and "6001" in n], r.execs.notes)
        for label, res in results(r.execs).items():
            self.assertEqual(res, "일치", label)

    def test_auto_linked_request_larger_than_the_row_adds_a_diff_row(self):
        # 줄 금액(200,000)과 같은 요청이 자동 연결된 뒤 인트라넷 금액이 올라간 경우와 같은 모양: 직접 늘려 본다
        r = Run(AUTO_JOURNAL, AUTO_PAYMENTS, AUTO_PROJECTS, AUTO_LEDGER)
        for rq in r.requests:
            rq["amount"] = 300000
        t = convert_projects.build_execs(r.books, r.costs, r.requests, r.match, [], r.cfg, r.projects)
        rows = naming(t, "6001")
        self.assertEqual(sum(money(x) for x in rows), 300000)
        diff = [x for x in rows if "차액" in x["근거"]]
        self.assertEqual(len(diff), 1)
        self.assertEqual(diff[0]["공급가액"], "80000")
        self.assertEqual(unpaid_total(t), 300000)
        d50 = [c for c in t.checks if c.label.startswith("계산서·요청 금액이 다르면 큰 쪽")][0]
        self.assertEqual((d50.source, d50.csv), (300000, 300000))
        for label, res in results(t).items():
            self.assertEqual(res, "일치", label)

    def test_basis_check_catches_a_request_counted_on_two_rows(self):
        """고치기 전 모양(자동 연결된 원가 줄 + 따로 넣은 요청 줄)을 새 대조가 '불일치'로 잡는다."""
        groups = [{"lines": [{"request": "6001", "basis": "자동"}], "basis": "WEHAGO 2026-10-30 전표 40"}]
        request_rows = [{"근거": "지급요청 6001 (인트라넷 금액, 부가세 포함 여부 미확인)"}]
        c = convert_projects.basis_check(groups, request_rows)
        self.assertEqual(convert.check_result(c), "불일치")
        self.assertTrue(c.label.startswith("지급요청마다 일정 근거 하나"), c.label)
        fixed = [{"lines": [{"request": "6001", "basis": "자동"}], "basis": "WEHAGO 2026-10-30 전표 40 · 지급요청 6001"}]
        self.assertEqual(convert.check_result(convert_projects.basis_check(fixed, [])), "일치")

    def test_basis_check_is_in_the_table(self):
        r = Run(AUTO_JOURNAL, AUTO_PAYMENTS, AUTO_PROJECTS, AUTO_LEDGER)
        found = [c for c in r.execs.checks if c.label.startswith("지급요청마다 일정 근거 하나")]
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].source, found[0].csv), (1, 1))


# ───────────── CR-02: 이미 지급된 계산서보다 요청이 크면 차액은 아직 나갈 돈 (D-50) ─────────────
D25 = dt.date(2026, 10, 25)
PAID_JOURNAL = [jl(D25, 50, "61101", "행사외주비(도)", 5000000, None, "가상무대", "[26220] 무대"),
                jl(D25, 50, "13500", "부가세대급금", 500000, None, "가상무대"),
                jl(D25, 50, "10300", "보통예금", None, 5500000, "가상무대")]
PAID_LEDGER = [inv(D25, "가상무대", "[26220] 무대", 5000000, 500000)]
PAID_PAYMENTS = [pay(6101, "[26220] 가상 전시", "가상무대", "2026-10-20 09:00:00", 6000000)]


class TestCR02PaidInvoiceDiff(unittest.TestCase):
    def test_paid_invoice_below_the_request_adds_the_diff_as_an_estimated_unpaid_row(self):
        r = Run(PAID_JOURNAL, PAID_PAYMENTS, AUTO_PROJECTS, PAID_LEDGER)
        m = r.match["rows"]["6101"]
        self.assertEqual((m["status"], m["invoice_total"], m["schedule_amount"]), ("금액 차이", 5500000, 6000000))
        rows = naming(r.execs, "6101")
        self.assertEqual(sorted(x["상태"] for x in rows), ["요청미지급", "지급완료"])
        diff = [x for x in rows if x["상태"] == "요청미지급"][0]
        self.assertEqual((diff["공급가액"], diff["부가세"], diff["확정여부"]), ("500000", "", "추정"))
        self.assertIn("차액", diff["근거"])
        self.assertIn("계산서는 이미 지급", diff["근거"])
        # 이 요청을 가리키는 줄의 합 = 승인 화면이 일정에 넣는 금액 (D-30b schedule_amount)
        self.assertEqual(sum(money(x) for x in rows), m["schedule_amount"])
        self.assertEqual(unpaid_total(r.execs), 500000)
        self.assertTrue([n for n in r.execs.notes if "6101" in n and "500,000" in n and "확인" in n], r.execs.notes)
        for label, res in results(r.execs).items():
            self.assertEqual(res, "일치", label)

    def test_d50_check_catches_the_dropped_diff(self):
        """고치기 전 모양(지급완료 줄만, 요청 번호도 차액 줄도 없음)을 D-50 대조가 '불일치'로 잡는다."""
        r = Run(PAID_JOURNAL, PAID_PAYMENTS, AUTO_PROJECTS, PAID_LEDGER)
        before = [dict(x, 근거="WEHAGO 2026-10-25 전표 50") for x in r.execs.rows if x["상태"] == "지급완료"]
        active = [rq for rq in r.requests if rq["status"] in ("approved", "pending")]
        c = convert_projects.d50_check(active, r.match, [], before)
        self.assertEqual((c.source, c.csv), (6000000, 0))
        self.assertEqual(convert.check_result(c), "불일치")
        c = convert_projects.d50_check(active, r.match, [], r.execs.rows)
        self.assertEqual(convert.check_result(c), "일치")

    def test_amount_check_counts_only_the_invoice_part_of_a_paid_row(self):
        """이미 지급된 원가 줄은 계산서 몫(5,500,000)만 맡는다: 차액 줄이 없으면 금액 대조가 '불일치' (고치기 전에는 요청 전액을 '맡음'으로 셌다)."""
        r = Run(PAID_JOURNAL, PAID_PAYMENTS, AUTO_PROJECTS, PAID_LEDGER)
        c = [c for c in r.execs.checks if c.label.startswith("지급요청 금액 (금액 있는")][0]
        self.assertEqual((c.source, c.csv), (6000000, 6000000))
        part = {"covered": {"6101": 5500000}, "paid_nos": []}
        without_diff = [x for x in r.execs.rows if "차액" not in x["근거"]]
        c = convert_projects.amount_check(r.requests, part, without_diff)
        self.assertEqual((c.source, c.csv), (6000000, 5500000))
        self.assertEqual(convert.check_result(c), "불일치")


if __name__ == "__main__":
    unittest.main()
