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
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import convert, convert_projects, convert_xchk, linking, wehago  # noqa: E402
from ceo_report.approval import project_code  # noqa: E402
from test_convert import setUpModule  # noqa: E402,F401  (샘플을 임시 폴더에 새로 쓴다)

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


# ───────────── CR-03 / D-52: 사장님승인을 읽지 못한 요청은 버리지 않는다 ─────────────
D25B = dt.date(2026, 10, 25)
UNKNOWN_JOURNAL = [jl(D25B, 60, "61101", "행사외주비(도)", 1000000, None, "가상음향", "[26220] 음향"),
                   jl(D25B, 60, "10300", "보통예금", None, 1000000, "가상음향")]
UNKNOWN_PAYMENTS = [pay(6201, "[26220] 가상 전시", "가상케이터링", "2026-10-20 09:00:00", 30000000, boss=""),
                    pay(6202, "[99999] 프로젝트 밖", "가상렌탈", "2026-10-20 09:00:00", 7000000, boss="보류")]


def xchk_rows(table, kind, item=None):
    return [r for r in table.rows if r["구분"] == kind and (item is None or r["항목"] == item)]


def render_s8(test, table, mode="mgmt"):
    from ceo_report import render
    tmp = new_tmp(test)
    with open(os.path.join(tmp, "위하고대조.csv"), "wb") as f:
        f.write(convert.table_bytes(table))
    X = convert_xchk.load_xchk(tmp)
    return X, render._s8({"xchk": X, "asof": ASOF}, mode)


class TestCR03StatusUnknown(unittest.TestCase):
    def test_unknown_status_requests_become_estimated_unpaid_rows(self):
        r = Run(UNKNOWN_JOURNAL, UNKNOWN_PAYMENTS, AUTO_PROJECTS)
        self.assertEqual([(q["번호"], q["status"], q["status_text"]) for q in r.requests],
                         [("6201", "status_unknown", ""), ("6202", "status_unknown", "보류")])
        one, two = naming(r.execs, "6201"), naming(r.execs, "6202")
        self.assertEqual(len(one), 1)
        self.assertEqual(len(two), 1)
        self.assertEqual((one[0]["상태"], one[0]["공급가액"], one[0]["확정여부"]), ("요청미지급", "30000000", "추정"))
        self.assertIn("상태 확인 필요 (빈칸)", one[0]["근거"])
        self.assertIn("상태 확인 필요 (보류)", two[0]["근거"])
        self.assertEqual(unpaid_total(r.execs), 37000000)
        for label, res in results(r.execs).items():
            self.assertEqual(res, "일치", label)

    def test_xchk_counts_them_in_request_totals_and_lists_them(self):
        r = Run(UNKNOWN_JOURNAL, UNKNOWN_PAYMENTS, AUTO_PROJECTS)
        x = r.xchk()
        total = xchk_rows(x, "프로젝트원가", "요청 누계")[0]
        self.assertEqual((total["금액"], total["건수"]), ("30000000", "1"))
        self.assertIn("상태 확인 필요 1건 포함", total["비고"])
        outside = xchk_rows(x, "프로젝트밖요청")[0]
        self.assertEqual((outside["금액"], outside["건수"]), ("7000000", "1"))
        head = xchk_rows(x, "요청상태확인필요")
        self.assertEqual([(h["금액"], h["건수"]) for h in head], [("37000000", "2")])
        lines = xchk_rows(x, "요청상태확인필요줄")
        self.assertEqual([(ln["대상"], ln["이름"], ln["금액"]) for ln in lines],
                         [("6201", "가상케이터링", "30000000"), ("6202", "가상렌탈", "7000000")])
        for label, res in results(x).items():
            self.assertEqual(res, "일치", label)

    def test_unknown_amount_of_an_unknown_status_request_blanks_the_total(self):
        payments = [dict(UNKNOWN_PAYMENTS[0], 금액="")] + UNKNOWN_PAYMENTS[1:]
        r = Run(UNKNOWN_JOURNAL, payments, AUTO_PROJECTS)
        x = r.xchk()
        total = xchk_rows(x, "프로젝트원가", "요청 누계")[0]
        self.assertEqual((total["금액"], total["건수"]), ("", "1"))
        self.assertEqual(xchk_rows(x, "요청상태확인필요")[0]["금액"], "")
        self.assertEqual(naming(r.execs, "6201")[0]["공급가액"], "")

    def test_request_total_check_catches_requests_left_out_of_the_totals(self):
        """고치기 전 모양(요청 누계 0건 · 프로젝트밖요청 0건)을 새 대조가 '불일치'로 잡는다."""
        r = Run(UNKNOWN_JOURNAL, UNKNOWN_PAYMENTS, AUTO_PROJECTS)
        before = [{"구분": "프로젝트원가", "대상": "26220", "항목": "요청 누계", "금액": "0", "건수": "0"},
                  {"구분": "프로젝트밖요청", "대상": "합계", "항목": "인트라넷 요청", "금액": "0", "건수": "0"}]
        c = convert_xchk.request_total_check(r.requests, before)
        self.assertEqual(convert.check_result(c), "불일치")
        self.assertEqual(convert.check_result(convert_xchk.request_total_check(r.requests, r.xchk().rows)), "일치")

    def test_section_8_shows_the_status_check_count_and_amount_in_both_editions(self):
        r = Run(UNKNOWN_JOURNAL, UNKNOWN_PAYMENTS, AUTO_PROJECTS)
        for mode in ("ceo", "mgmt"):
            X, html = render_s8(self, r.xchk(), mode)
            self.assertEqual((X["status_check"]["count"], X["status_check"]["amount"]), (2, 37000000))
            self.assertIn("상태 확인 필요 2건 37,000,000", re.sub(r"<[^>]+>", "", html), mode)
        X, html = render_s8(self, r.xchk(), "mgmt")
        text = re.sub(r"<[^>]+>", "", html)
        self.assertIn("6201", text)
        self.assertIn("보류", text)
        self.assertEqual([(p["requested"], p["requested_count"]) for p in X["projects"]], [(30000000, 1)])
        self.assertEqual((X["outside"]["amount"], X["outside"]["count"]), (7000000, 1))



def company(test, payments=None, journal=None, snapshot_at=None):
    """가상 회사 한 곳을 임시 폴더에 쓴다 (test_convert_e2e.full_company 와 같은 장부·매출 엑셀, 스냅숏의 요청만 바꿀 수 있다).

    -> (tmp, 입력, 수집, 위하고). 입력 폴더는 샘플 복사본이다.
    """
    from ceo_report import snapshot
    from test_approval import COLLECTED, FAKE_PAYMENTS, FAKE_PROJECTS, as_dicts
    from test_convert import FAKE_PL_JOURNAL, convert_input, write_convert_books
    from test_convert_e2e import PURCHASE_LEDGER, SALES_EINVOICE, write_sales
    tmp, input_dir, collect, wehago_dir = convert_input(test)
    write_convert_books(wehago_dir, journal=FAKE_PL_JOURNAL if journal is None else journal, ledger=PURCHASE_LEDGER)
    write_sales(wehago_dir, SALES_EINVOICE)
    rows = FAKE_PAYMENTS if payments is None else payments
    snapshot.write_snapshot(collect, snapshot_at or COLLECTED, as_dicts(rows, snapshot.PAYMENT_COLUMNS),
                            as_dicts(FAKE_PROJECTS, snapshot.PROJECT_COLUMNS))
    return tmp, input_dir, collect, wehago_dir


def run_convert_core(input_dir, collect, wehago_dir, asof=dt.date(2026, 11, 2), now=dt.datetime(2026, 11, 2, 0, 0)):
    return convert.run(input_dir, collect, wehago_dir, asof, now, "20261102_000000")


def result_text(input_dir):
    with open(os.path.join(input_dir, "변환결과.txt"), encoding="utf-8-sig") as f:
        return f.read()


class TestCR03RunLevel(unittest.TestCase):
    def test_every_request_with_a_blank_status_is_said_loudly(self):
        from test_approval import FAKE_PAYMENTS
        blank = [list(r[:10]) + [""] for r in FAKE_PAYMENTS]
        tmp, input_dir, collect, wehago_dir = company(self, payments=blank)
        res = run_convert_core(input_dir, collect, wehago_dir)
        self.assertEqual(res.code, 0, res.lines)
        warn = [ln for ln in res.lines if ln.startswith("경고: 인트라넷 지급요청 9건 모두 사장님승인 빈칸")]
        self.assertEqual(len(warn), 1, res.lines)
        self.assertIn(warn[0], result_text(input_dir).splitlines())
        rows = [r for r in convert.read_prev(input_dir, "프로젝트집행.csv") if "상태 확인 필요 (빈칸)" in r["근거"]]
        self.assertTrue(rows)

    def test_no_warning_when_some_status_is_read(self):
        tmp, input_dir, collect, wehago_dir = company(self)
        res = run_convert_core(input_dir, collect, wehago_dir)
        self.assertFalse([ln for ln in res.lines if ln.startswith("경고: 인트라넷 지급요청")], res.lines)

    def test_approval_attention_count_equals_section_8_count_on_the_same_input(self):
        from ceo_report import approval, data, render, snapshot
        from test_approval import FAKE_PAYMENTS
        extra = [["6201", "[26220] 가상 전시", "가상케이터링", "2026-10-20 09:00:00", "2026-11-12", "30,000,000", "", "x", "승인", "승인", ""],
                 ["6202", "[99999] 프로젝트 밖", "가상렌탈", "2026-10-20 09:00:00", "2026-11-12", "", "", "x", "승인", "승인", "보류"]]
        tmp, input_dir, collect, wehago_dir = company(self, payments=[list(r) for r in FAKE_PAYMENTS] + extra)
        res = run_convert_core(input_dir, collect, wehago_dir)
        self.assertEqual(res.code, 0, res.lines)
        snap = snapshot.read_snapshot(snapshot.latest_snapshot(collect))
        A = approval.build(data.load(input_dir), snap, dt.date(2026, 11, 2), dt.datetime(2026, 11, 2), wehago_dir, input_dir)
        X = convert_xchk.load_xchk(input_dir)
        self.assertEqual(A["panel"]["status_unknown"]["n"], 3)                    # 5107 반려 · 6201 빈칸 · 6202 보류
        self.assertEqual(X["status_check"]["count"], A["panel"]["status_unknown"]["n"])
        html = re.sub(r"<[^>]+>", "", render._s8({"xchk": X, "asof": dt.date(2026, 11, 2)}, "ceo"))
        self.assertIn("상태 확인 필요 3건 금액 판단 불가 (미확인 1건)", html)
        self.assertEqual(sorted(ln["key"] for ln in X["status_check_lines"]), ["5107", "6201", "6202"])



# ───────────── CR-04: 일부 기간 분개장은 그 기간의 손익 줄만 바꾼다 ─────────────
D27 = dt.date(2026, 10, 27)
OCT_JOURNAL = [jl(D27, 31, "10800", "수입수수료미수금", 82500000, None, "가상고객D", "잔금"),
               jl(D27, 31, "41200", "수입수수료", None, 75000000, "가상고객D", "잔금"),
               jl(D27, 31, "25500", "부가세예수금", None, 7500000, "가상고객D")]


def prev_pl(months, unit="회사", target="회사 전체"):
    return [{"출처": "WEHAGO", "연월": "2026-%02d" % m, "단위": unit, "대상": target, "매출": "100000000", "직접비": "60000000",
             "공통비": "5000000", "잠정": "Y"} for m in months]


class TestCR04PartialJournal(unittest.TestCase):
    def build(self, prev, journal=OCT_JOURNAL):
        from ceo_report import convert_pl
        return convert_pl.build_pl(books_of(journal), convert.Config(convert.DEFAULT_CONFIG), prev, None)

    def test_months_outside_the_journal_are_kept_with_a_note(self):
        t = self.build(prev_pl(range(1, 10)) + prev_pl([10]))
        company = [(r["연월"], r["매출"]) for r in t.rows if r["단위"] == "회사"]
        self.assertEqual(company, [("2026-%02d" % m, "100000000") for m in range(1, 10)] + [("2026-10", "75000000")])
        self.assertEqual(sum(int(r["매출"]) for r in t.rows if r["단위"] == "회사"), 975000000)
        self.assertIn("이전 변환 유지 2026-01~2026-09 (WEHAGO 줄 9건: 회사 9) — 새 분개장(2026-10~2026-10)에 없는 달", t.notes)
        self.assertIn("이전 손익.csv의 WEHAGO 줄 1건(회사 1)은 새로 만든 줄로 바꿈", t.notes)
        self.assertIn("분개장 기간 2026-10-27~2026-10-27", t.notes)
        for label, res in results(t).items():
            self.assertEqual(res, "일치", label)

    def test_later_months_are_kept_too_and_the_journal_months_are_replaced(self):
        t = self.build(prev_pl([9, 10, 11]) + prev_pl([10], "팀", "가상팀"))
        months = [(r["연월"], r["단위"]) for r in t.rows]
        self.assertEqual(months, [("2026-09", "회사"), ("2026-10", "회사"), ("2026-11", "회사")])
        self.assertTrue([n for n in t.notes if n.startswith("이전 변환 유지 2026-09, 2026-11 ")], t.notes)

    def test_ytd_check_catches_dropped_months(self):
        """고치기 전 모양(10월 줄만)을 올해 누계 대조가 '불일치'로 잡는다. 새 분개장보다 CSV 누계가 작아지면 안 된다."""
        from ceo_report import convert_pl
        prev = prev_pl(range(1, 10))
        before = [{"출처": "WEHAGO", "연월": "2026-10", "단위": "회사", "대상": "회사 전체", "매출": "75000000", "직접비": "0",
                   "공통비": "0", "잠정": "Y"}]
        per = {"2026-10": {"revenue": 75000000, "direct": 0, "common": 0}}
        checks = convert_pl.ytd_checks(per, prev, before)
        revenue = [c for c in checks if "매출" in c.label][0]
        self.assertEqual((revenue.source, revenue.csv), (975000000, 75000000))
        self.assertEqual(convert.check_result(revenue), "불일치")
        self.assertTrue(revenue.label.startswith("올해(2026) 누계 매출: 새 분개장 + 이전 변환 유지 달"), revenue.label)
        t = self.build(prev)
        got = [c for c in t.checks if c.label.startswith("올해(2026) 누계 매출")][0]
        self.assertEqual((got.source, got.csv), (975000000, 975000000))
        self.assertGreaterEqual(got.csv, 75000000)



# ───────────── CR-05: 나눠 받거나 수수료를 떼고 받은 입금도 계산서에 붙는다 ─────────────
D15, D05, D20 = dt.date(2026, 9, 15), dt.date(2026, 10, 5), dt.date(2026, 10, 20)
SALE_A = [jl(D15, 30, "10800", "수입수수료미수금", 110000000, None, "가상고객A", "[26201] 선금"),
          jl(D15, 30, "41200", "수입수수료", None, 100000000, "가상고객A", "[26201] 선금"),
          jl(D15, 30, "25500", "부가세예수금", None, 10000000, "가상고객A")]


def receipt(day, no, amount, vendor="가상고객A", code="10300", account="보통예금", memo="입금"):
    return [jl(day, no, code, account, amount, None, vendor, memo),
            jl(day, no, "10800", "수입수수료미수금", None, amount, vendor, memo)]


def sale(day, vendor, supply, item="[26201] 가상 컨퍼런스"):
    return {"date": day, "no": "", "vendor": vendor, "vendor_norm": wehago.norm_vendor(vendor), "item": item,
            "supply": supply, "vat": supply // 10, "total": supply + supply // 10, "code": project_code(item),
            "type": "일반", "credit_account": ""}


def build_inv(journal, sales):
    from ceo_report import convert_invoices
    return convert_invoices.build_invoices({"state": "ok", "reason": "", "notes": [], "rows": list(sales)},
                                           books_of(journal), None, {}, [], convert.Config(convert.DEFAULT_CONFIG))


def paid(table):
    return [(r["거래처"], r["발행일"], r["입금일"], r["입금액"]) for r in table.rows]


BALANCE = "매출채권 잔액"


def balance_check(table):
    got = [c for c in table.checks if c.label.startswith(BALANCE)]
    assert len(got) == 1, [c.label for c in table.checks]
    return got[0]


class TestCR05Receipts(unittest.TestCase):
    def test_two_installments_without_an_opening_line_pay_the_invoice(self):
        """repro_e: 55,000,000 + 55,000,000 (전기이월 줄 없음) -> 입금액 110,000,000, 미배분 0."""
        t = build_inv(SALE_A + receipt(D05, 33, 55000000) + receipt(D20, 34, 55000000), [sale(D15, "가상고객A", 100000000)])
        self.assertEqual(paid(t), [("가상고객A", "2026-09-15", "2026-10-20", "110000000")])
        self.assertIn("미배분 수금 0건 0", t.notes)
        self.assertEqual((balance_check(t).source, balance_check(t).csv), (0, 0))
        for label, res in results(t).items():
            self.assertEqual(res, "일치", label)

    def test_a_bank_fee_is_not_forgiven_the_remainder_stays_outstanding_and_is_listed(self):
        t = build_inv(SALE_A + receipt(D05, 33, 109998700), [sale(D15, "가상고객A", 100000000)])
        self.assertEqual(paid(t), [("가상고객A", "2026-09-15", "2026-10-05", "109998700")])
        self.assertIn("부분 입금 계산서 1건 남은 금액 1,300 (수수료 차감 등도 자동으로 지우지 않음 — 미수로 둠)", t.notes)
        self.assertIn("  부분 입금 2026-09-15 가상고객A 합계 110,000,000 · 입금 109,998,700 · 남음 1,300", t.notes)
        self.assertEqual((balance_check(t).source, balance_check(t).csv), (1300, 1300))
        self.assertIn("참고 매출채권 잔액: 분개장 1,300 · 계산서 기준 1,300 (차이 0)", t.notes)
        for label, res in results(t).items():
            self.assertEqual(res, "일치", label)

    def test_one_payment_covers_two_invoices_oldest_first(self):
        d2 = dt.date(2026, 9, 30)
        journal = (SALE_A + [jl(d2, 31, "10800", "수입수수료미수금", 22000000, None, "가상고객A", "[26201] 잔금"),
                             jl(d2, 31, "41200", "수입수수료", None, 20000000, "가상고객A", "[26201] 잔금"),
                             jl(d2, 31, "25500", "부가세예수금", None, 2000000, "가상고객A")]
                   + receipt(D05, 33, 120000000))
        t = build_inv(journal, [sale(D15, "가상고객A", 100000000), sale(d2, "가상고객A", 20000000)])
        self.assertEqual(paid(t), [("가상고객A", "2026-09-15", "2026-10-05", "110000000"),
                                   ("가상고객A", "2026-09-30", "2026-10-05", "10000000")])
        self.assertIn("  부분 입금 2026-09-30 가상고객A 합계 22,000,000 · 입금 10,000,000 · 남음 12,000,000", t.notes)
        self.assertEqual(convert.check_result(balance_check(t)), "일치")

    def test_a_receipt_into_any_asset_account_is_a_receipt_not_a_correction(self):
        for code, account in (("10301", "보통예금(2)"), ("10100", "현금"), ("10350", "정기예금")):
            t = build_inv(SALE_A + receipt(D05, 33, 110000000, code=code, account=account), [sale(D15, "가상고객A", 100000000)])
            self.assertEqual(paid(t), [("가상고객A", "2026-09-15", "2026-10-05", "110000000")], code)
            self.assertFalse([n for n in t.notes if n.startswith("수정(계산서 감액)")], (code, t.notes))
            for label, res in results(t).items():
                self.assertEqual(res, "일치", (code, label))

    def test_a_credit_without_any_asset_debit_stays_a_correction(self):
        cut = [jl(D05, 33, "41200", "수입수수료", 10000000, None, "가상고객A", "감액"),
               jl(D05, 33, "25500", "부가세예수금", 1000000, None, "가상고객A", "감액"),
               jl(D05, 33, "10800", "수입수수료미수금", None, 11000000, "가상고객A", "감액")]
        t = build_inv(SALE_A + cut, [sale(D15, "가상고객A", 100000000)])
        self.assertEqual(paid(t), [("가상고객A", "2026-09-15", "", "")])
        self.assertIn("수정(계산서 감액) 1건 11,000,000", t.notes)
        # 감액 계산서가 계산서 목록에 없으니 계산서.csv 미수가 분개장보다 크다: 대조가 잡는다
        self.assertEqual((balance_check(t).source, balance_check(t).csv), (99000000, 110000000))
        self.assertEqual(convert.check_result(balance_check(t)), "불일치")

    def test_a_receipt_before_the_invoice_date_is_not_applied_and_the_check_says_undecidable(self):
        t = build_inv(SALE_A + receipt(dt.date(2026, 9, 10), 29, 110000000), [sale(D15, "가상고객A", 100000000)])
        self.assertEqual(paid(t), [("가상고객A", "2026-09-15", "", "")])
        self.assertIn("  미배분 수금 2026-09-10 가상고객A 110,000,000 (전표 29)", t.notes)
        self.assertEqual(convert.check_result(balance_check(t)), "판단 불가")
        self.assertTrue([n for n in t.notes if n.startswith("매출채권 잔액 대조 판단 불가: 분개장에 전기이월·기초잔액 줄이 없고")],
                        t.notes)

    def test_the_per_customer_note_shows_the_real_difference(self):
        """고치기 전에는 '계산서 기준'에서 미배분 수금을 빼서 늘 차이 0 이었다. 이제 계산서.csv 미수(+기초 미수 남음)와 비교한다."""
        opening = [jl(dt.date(2026, 1, 2), 1, "10800", "수입수수료미수금", 5000000, None, "가상고객B", "전기이월")]
        t = build_inv(SALE_A + opening + receipt(dt.date(2026, 9, 10), 29, 110000000, vendor="가상고객A")
                      + receipt(D05, 34, 2000000, vendor="가상고객B"),
                      [sale(D15, "가상고객A", 100000000)])
        self.assertIn("매출채권 잔액 차이 가상고객A: 분개장 0 · 계산서 기준 110,000,000 (차이 −110,000,000 · 미배분 수금 110,000,000)",
                      t.notes)
        self.assertIn("참고 매출채권 잔액: 분개장 3,000,000 · 계산서 기준 113,000,000 (차이 −110,000,000)", t.notes)
        self.assertEqual((balance_check(t).source, balance_check(t).csv), (3000000, 113000000))
        self.assertEqual(convert.check_result(balance_check(t)), "불일치")

    def test_the_balance_check_catches_the_pre_fix_rows(self):
        """고치기 전 결과(입금액 빈칸, 입금은 미배분)를 새 대조에 넣으면 기초 줄이 있을 때 '불일치', 없을 때 '판단 불가'."""
        from ceo_report import convert_invoices
        before = [{"공급가액": "100000000", "부가세": "10000000", "입금액": ""}]
        c = convert_invoices.balance_check(0, before, 0, "")
        self.assertEqual((c.source, c.csv, convert.check_result(c)), (0, 110000000, "불일치"))
        c = convert_invoices.balance_check(0, before, 0, "분개장에 전기이월·기초잔액 줄이 없고 미배분 수금 2건")
        self.assertEqual(convert.check_result(c), "판단 불가")
        c = convert_invoices.balance_check(0, [{"공급가액": "100000000", "부가세": "", "입금액": ""}], 0, "")
        self.assertEqual(convert.check_result(c), "판단 불가")



# ───────────── WR-01: 바꿔치기가 중간에 실패하면 이미 바꾼 파일을 되돌린다 ─────────────
class FlakyReplace(object):
    """os.replace 대신: '.변환중' 임시 파일을 대상에 놓는 n번째 호출만 실패한다 (윈도 공유 위반·백신 검사 흉내)."""

    def __init__(self, fail_at):
        self.real, self.fail_at, self.calls = os.replace, fail_at, []

    def __call__(self, src, dst):
        if str(src).endswith(".변환중"):
            self.calls.append(os.path.basename(dst))
            if len(self.calls) == self.fail_at:
                raise PermissionError(13, "sharing violation", dst)
        return self.real(src, dst)


def read_text(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


class TestWR01Rollback(unittest.TestCase):
    def write(self, folder, names):
        for n in names:
            with open(os.path.join(folder, n), "w", encoding="utf-8") as f:
                f.write("OLD " + n)

    def test_repro_f_the_replaced_file_is_restored_from_the_backup(self):
        d = new_tmp(self)
        self.write(d, ("손익.csv", "계산서.csv"))
        flaky = FlakyReplace(2)
        with unittest.mock.patch.object(convert.os, "replace", flaky):
            with self.assertRaises(convert.WriteFailed) as cm:
                convert.write_files(d, [("손익.csv", b"NEW"), ("계산서.csv", b"NEW")], "20261102_090000")
        e = cm.exception
        self.assertEqual((e.name, e.replaced, e.restored, e.lost), ("계산서.csv", ["손익.csv"], ["손익.csv"], []))
        for n in ("손익.csv", "계산서.csv"):
            self.assertEqual(read_text(os.path.join(d, n)), "OLD " + n)
        self.assertEqual(sorted(os.listdir(d)), ["계산서.csv", "손익.csv", "이전"])   # 임시 파일 없음
        lines = convert._write_failed_lines(e)
        self.assertIn("이미 바꾼 파일을 이전 내용으로 되돌림: 손익.csv (입력/이전/20261102_090000/ 에서)", lines)

    def test_a_file_that_did_not_exist_before_is_removed_again(self):
        d = new_tmp(self)
        self.write(d, ("계산서.csv",))
        with unittest.mock.patch.object(convert.os, "replace", FlakyReplace(2)):
            with self.assertRaises(convert.WriteFailed) as cm:
                convert.write_files(d, [("손익.csv", b"NEW"), ("계산서.csv", b"NEW")], "20261102_090000")
        self.assertEqual(cm.exception.restored, ["손익.csv"])
        self.assertFalse(os.path.exists(os.path.join(d, "손익.csv")))
        self.assertEqual(read_text(os.path.join(d, "계산서.csv")), "OLD 계산서.csv")

    def test_a_rollback_that_fails_is_named(self):
        d = new_tmp(self)
        self.write(d, ("손익.csv", "계산서.csv"))
        real_copy = convert.shutil.copy2

        def copy2(src, dst, *a, **k):
            if os.sep + "이전" + os.sep in str(src):
                raise PermissionError(13, "denied", dst)
            return real_copy(src, dst, *a, **k)

        with unittest.mock.patch.object(convert.os, "replace", FlakyReplace(2)):
            with unittest.mock.patch.object(convert.shutil, "copy2", copy2):
                with self.assertRaises(convert.WriteFailed) as cm:
                    convert.write_files(d, [("손익.csv", b"NEW"), ("계산서.csv", b"NEW")], "20261102_090000")
        e = cm.exception
        self.assertEqual((e.restored, e.lost), ([], ["손익.csv"]))
        self.assertTrue([ln for ln in convert._write_failed_lines(e) if ln.startswith("되돌리지 못한 파일 (새 내용 그대로): 손익.csv")])

    def test_run_restores_every_csv_writes_the_failure_result_and_exits_7(self):
        from test_convert import convert_input, write_convert_books
        from test_approval import write_fake_snapshot
        tmp, input_dir, collect, wehago_dir = convert_input(self)
        write_convert_books(wehago_dir)
        write_fake_snapshot(collect)
        names = ("손익.csv", "계산서.csv", "프로젝트.csv", "프로젝트집행.csv", "위하고대조.csv")
        before = dict((n, read_text(os.path.join(input_dir, n))) for n in names if os.path.exists(os.path.join(input_dir, n)))
        flaky = FlakyReplace(3)
        with unittest.mock.patch.object(convert.os, "replace", flaky):
            res = convert.run(input_dir, collect, wehago_dir, dt.date(2026, 11, 2), dt.datetime(2026, 11, 2, 0, 0))
        self.assertEqual(res.code, 7, res.lines)
        for n in names:
            path = os.path.join(input_dir, n)
            if n in before:
                self.assertEqual(read_text(path), before[n], n)
            else:
                self.assertFalse(os.path.exists(path), n)
        text = read_text(os.path.join(input_dir, "변환결과.txt")).splitlines()
        failed = flaky.calls[2]
        self.assertIn("변환 실패 — 파일을 바꾸는 중 멈춤 (종료 코드 7): 입력의 CSV는 이전 변환 그대로입니다", text)
        self.assertIn("입력/%s을(를) 쓸 수 없음 (엑셀에서 열려 있으면 닫고 다시 실행)" % failed, text)
        self.assertTrue([ln for ln in text if ln.startswith("이미 바꾼 파일을 이전 내용으로 되돌림: %s, %s" % tuple(flaky.calls[:2]))], text)
        self.assertIn("변환 실패 — 파일을 바꾸는 중 멈춤 (종료 코드 7): 입력의 CSV는 이전 변환 그대로입니다", res.lines)

    def test_when_the_result_file_cannot_be_written_the_csvs_are_restored_too(self):
        from test_convert import convert_input, write_convert_books
        from test_approval import write_fake_snapshot
        tmp, input_dir, collect, wehago_dir = convert_input(self)
        write_convert_books(wehago_dir)
        write_fake_snapshot(collect)
        names = ("손익.csv", "계산서.csv", "프로젝트.csv", "프로젝트집행.csv", "위하고대조.csv", "세금예상.csv", "계정별비용.csv",
                 "증빙월별.csv", "장부잔액.csv", "장부입출금.csv", "장부채무.csv", "연간자료.csv", "현금흐름.csv", "계정잔액.csv", "변환결과.txt")
        before = dict((n, read_text(os.path.join(input_dir, n))) for n in names if os.path.exists(os.path.join(input_dir, n)))
        flaky = FlakyReplace(15)   # CSV 열네 개(연간자료.csv·현금흐름.csv·계정잔액.csv 포함)는 바뀌고 변환결과.txt 에서 실패
        with unittest.mock.patch.object(convert.os, "replace", flaky):
            res = convert.run(input_dir, collect, wehago_dir, dt.date(2026, 11, 2), dt.datetime(2026, 11, 2, 0, 0))
        self.assertEqual(res.code, 7, res.lines)
        self.assertEqual(flaky.calls[-1], "변환결과.txt")
        for n in names:
            path = os.path.join(input_dir, n)
            self.assertEqual(read_text(path) if os.path.exists(path) else None, before.get(n), n)
        self.assertTrue([ln for ln in res.lines if ln.startswith("이미 바꾼 파일을 이전 내용으로 되돌림: 손익.csv")], res.lines)



# ───────────── WR-02: 날짜 수 설정은 1~3650 으로, 어떤 값에도 트레이스백 없이 ─────────────
def settings_folder(test, *rows):
    import csv
    folder = new_tmp(test)
    with open(os.path.join(folder, "설정.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["항목", "값"])
        for r in rows:
            w.writerow(r)
    return folder


def set_setting_rows(rows, key, value):
    for r in rows[1:]:
        if r and r[0] == key:
            r[1] = value
            return rows
    rows.append([key, value])
    return rows


class TestWR02DaySettings(unittest.TestCase):
    def test_a_huge_link_days_is_clamped_with_a_note(self):
        cfg, notes = convert.read_config(settings_folder(self, ["변환_자동연결일수", "3000000"]))
        self.assertEqual(cfg["link_days"], 3650)
        self.assertIn("설정 변환_자동연결일수 값 3000000 범위 밖 (1~3650) → 3650 사용", notes)

    def test_zero_is_raised_to_one_with_a_note(self):
        cfg, notes = convert.read_config(settings_folder(self, ["변환_자동연결일수", "0"]))
        self.assertEqual(cfg["link_days"], 1)
        self.assertIn("설정 변환_자동연결일수 값 0 범위 밖 (1~3650) → 1 사용", notes)

    def test_repro_g_linking_with_the_setting_does_not_crash(self):
        cfg, _ = convert.read_config(settings_folder(self, ["변환_자동연결일수", "3000000"]))
        journal = [jl(D40, 41, "61101", "행사외주비(도)", 500000, None, "가상케이터링", "케이터링"),
                   jl(D40, 41, "10300", "보통예금", None, 500000, "가상케이터링")]
        snap = Snap([pay(6002, "[26201] 가상 컨퍼런스", "가상케이터링", "2026-10-25 09:00:00", 500000)], [proj(1, "[26201] 가상 컨퍼런스")])
        costs = linking.link_costs(books_of(journal), linking.requests_of(snap, ASOF, NOW), linking.projects_of(snap), {},
                                   cfg["link_days"])
        self.assertEqual(costs["lines"][0]["request"], "6002")

    def test_linking_never_overflows_even_when_called_with_a_huge_number(self):
        journal = [jl(D40, 41, "61101", "행사외주비(도)", 500000, None, "가상케이터링", "케이터링")]
        snap = Snap([pay(6002, "[26201] 가상 컨퍼런스", "가상케이터링", "2026-10-25 09:00:00", 500000)], [proj(1, "[26201] 가상 컨퍼런스")])
        costs = linking.link_costs(books_of(journal), linking.requests_of(snap, ASOF, NOW), linking.projects_of(snap), {},
                                   10 ** 9)
        self.assertEqual(costs["lines"][0]["request"], "6002")

    def test_the_conversion_cli_runs_with_the_huge_setting(self):
        from test_convert import cli_argv, convert_input, run_convert, write_convert_books
        from test_approval import write_fake_snapshot, edit_csv
        tmp, input_dir, collect, wehago_dir = convert_input(self)
        write_convert_books(wehago_dir)
        write_fake_snapshot(collect)
        edit_csv(input_dir, "설정.csv", lambda rows: set_setting_rows(rows, "변환_자동연결일수", "3000000"))
        rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        self.assertEqual(rc, 0, out)
        self.assertNotIn("Traceback", out)
        self.assertIn("설정 변환_자동연결일수 값 3000000 범위 밖 (1~3650) → 3650 사용", result_text(input_dir))

    def test_an_unexpected_error_in_the_conversion_is_one_line_and_exit_7(self):
        from test_convert import cli_argv, convert_input, load_cli, run_convert
        tmp, input_dir, collect, wehago_dir = convert_input(self)
        cli = load_cli()
        with unittest.mock.patch.object(cli.convert, "run", side_effect=OverflowError("date value out of range 900101-1234567")):
            rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        self.assertEqual(rc, 7, out)
        self.assertIn("변환 중 예상하지 못한 오류 (OverflowError)", out)
        self.assertNotIn("1234567", out)
        self.assertNotIn("Traceback", out)

    def test_the_approval_screen_runs_with_the_huge_settings(self):
        from test_approval import edit_csv, run_cli, sample_copy, write_fake_snapshot
        from test_wehago import write_fake_books
        folder = sample_copy(self)
        edit_csv(folder, "설정.csv", lambda rows: set_setting_rows(set_setting_rows(rows, "변환_자동연결일수", "3000000"),
                                                                    "승인검토_주수", "999999"))
        tmp = new_tmp(self)
        write_fake_books(os.path.join(tmp, "수집", "위하고"))
        write_fake_snapshot(os.path.join(tmp, "수집"))
        rc, out = run_cli(["--기준일", "2026-11-02", "--입력", folder, "--수집폴더", os.path.join(tmp, "수집"),
                           "--출력", os.path.join(tmp, "출력"), "--열기", "안함"])
        self.assertEqual(rc, 0, out)
        self.assertNotIn("Traceback", out)
        from ceo_report import approval, data
        snap_path = __import__("ceo_report.snapshot", fromlist=["x"]).latest_snapshot(os.path.join(tmp, "수집"))
        A = approval.build(data.load(folder), __import__("ceo_report.snapshot", fromlist=["x"]).read_snapshot(snap_path),
                           dt.date(2026, 11, 2), dt.datetime(2026, 11, 2), os.path.join(tmp, "수집", "위하고"), input_dir=folder)
        notes = [m for f, line, m in A["issues"] if "승인검토_주수" in m or "변환_자동연결일수" in m]
        self.assertTrue([m for m in notes if "승인검토_주수 값 999999 범위 밖 (1~521) → 521 사용" in m], notes)
        self.assertTrue([m for m in notes if "변환_자동연결일수 값 3000000 범위 밖 (1~3650) → 3650 사용" in m], notes)
        self.assertEqual((A["n_weeks"], len(A["data"]["days"])), (521, 521 * 7))

    def test_an_unexpected_error_in_the_approval_screen_is_one_line(self):
        from test_approval import load_approval_cli, run_cli, sample_copy, write_fake_snapshot
        folder = sample_copy(self)
        tmp = new_tmp(self)
        write_fake_snapshot(os.path.join(tmp, "수집"))
        cli = load_approval_cli()
        with unittest.mock.patch.object(cli, "build", side_effect=OverflowError("date value out of range")):
            rc, out = run_cli(["--기준일", "2026-11-02", "--입력", folder, "--수집폴더", os.path.join(tmp, "수집"),
                               "--출력", os.path.join(tmp, "출력"), "--열기", "안함"])
        self.assertEqual(rc, 6, out)
        self.assertIn("승인 검토 화면을 만들던 중 예상하지 못한 오류 (OverflowError)", out)
        self.assertNotIn("Traceback", out)



# ───────────── WR-03: 이전 프로젝트.csv 에만 있는 프로젝트는 수동 칸과 함께 옮긴다 ─────────────
PREV_PROJECTS = [
    {"프로젝트번호": "26220", "프로젝트명": "가상 전시", "팀": "가상팀", "클라이언트": "가상고객", "상태": "진행", "사전견적예산": "",
     "예산수정일": "", "계약금액": "300,000,000", "매출반영누계": "0", "행사일": "2026-11-20", "완료일": "", "실행가": ""},
    {"프로젝트번호": "P26299", "프로젝트명": "가상 지난 행사", "팀": "가상팀", "클라이언트": "가상고객Q", "상태": "진행",
     "사전견적예산": "80,000,000", "예산수정일": "2026.08.01", "계약금액": "50,000,000", "매출반영누계": "20,000,000",
     "행사일": "2026-08-20", "완료일": "", "실행가": ""},
]


class TestWR03PreviousOnlyProjects(unittest.TestCase):
    def build(self, prev):
        r = Run([], [], AUTO_PROJECTS)
        return convert_projects.build_projects(r.projects, r.revenue, prev)

    def test_a_project_only_in_the_previous_file_is_carried_with_its_manual_fields(self):
        t = self.build(PREV_PROJECTS)
        rows = dict((r["프로젝트번호"], r) for r in t.rows)
        self.assertEqual(list(rows), ["26220", "P26299"])
        old = rows["P26299"]
        self.assertEqual((old["프로젝트명"], old["상태"], old["계약금액"], old["예산수정일"], old["사전견적예산"], old["매출반영누계"]),
                         ("가상 지난 행사", "진행", "50000000", "2026-08-01", "80000000", "20000000"))
        self.assertIn("이전 프로젝트.csv에만 있는 프로젝트 1건 → 옮김 (스냅숏에 없음, 이전 줄 그대로): P26299", t.notes)
        for label, res in results(t).items():
            self.assertEqual(res, "일치", label)
        got = dict((c.label, (c.source, c.csv)) for c in t.checks)
        self.assertEqual(got["프로젝트 수 (스냅숏 → CSV)"], (1, 1))
        self.assertEqual(got[convert_projects.CARRY_LABEL], (1, 1))

    def test_the_carry_check_catches_the_pre_fix_rows(self):
        t = self.build(PREV_PROJECTS)
        before = [r for r in t.rows if r["프로젝트번호"] != "P26299"]
        c = convert_projects.carry_check(PREV_PROJECTS, ["26220"], before)
        self.assertEqual((c.source, c.csv, convert.check_result(c)), (1, 0, "불일치"))

    def test_the_written_file_keeps_the_contract_for_the_report(self):
        from ceo_report import data
        t = self.build(PREV_PROJECTS)
        tmp = new_tmp(self)
        from sample_input import SAMPLE
        input_dir = os.path.join(tmp, "입력")
        shutil.copytree(SAMPLE, input_dir)
        convert.write_table(os.path.join(input_dir, "프로젝트.csv"), t)
        d = data.load(input_dir)
        self.assertEqual(d.projects["P26299"]["contract"], 50000000)
        self.assertEqual([it for it in d.issues.items if it[0] == "프로젝트.csv"], [])

    def test_a_repeated_previous_only_key_is_carried_once_with_a_note(self):
        t = self.build(PREV_PROJECTS + [dict(PREV_PROJECTS[1], 계약금액="1")])
        self.assertEqual([r["프로젝트번호"] for r in t.rows], ["26220", "P26299"])
        self.assertEqual(t.rows[1]["계약금액"], "50000000")
        self.assertTrue([n for n in t.notes if "P26299" in n and "여러 줄" in n], t.notes)



# ───────────── WR-04: 손으로 넣은 미지급 줄은 옮기고, 새로 만든 줄과 겹치는지 대조한다 ─────────────
def exec_row(project, item, vendor, state, supply, vat, basis, firm="확정"):
    return {"프로젝트번호": project, "항목": item, "거래처": vendor, "상태": state, "공급가액": supply, "부가세": vat, "일자": "",
            "확정여부": firm, "근거": basis}


HAND_PREV = [
    exec_row("26220", "무대", "가상무대", "요청미지급", "1,000,000", "100,000", "구두 발주"),
    exec_row("26220", "카드", "", "카드사용미결제", "300,000", "", "카드 사용"),
    exec_row("26220", "확인 중", "가상음향", "요청미지급", "", "", "금액 확인 중"),
    exec_row("26220", "조명", "가상조명", "요청미지급", "200,000", "20,000", "지급요청 6001 (인트라넷 금액)"),
    exec_row("26220", "원가", "가상조명", "요청미지급", "200,000", "20,000", "WEHAGO 2026-10-01 전표 1"),
    exec_row("26220", "발주", "가상무대", "지급완료", "5,000,000", "500,000", "발주서"),
]


def hand_rows(table):
    return [r for r in table.rows if r["근거"] in ("구두 발주", "카드 사용", "금액 확인 중", "가상조명 구두")]


class TestWR04HandEnteredRows(unittest.TestCase):
    def test_unpaid_hand_rows_are_carried_and_generated_or_paid_ones_are_not(self):
        r = Run([], [], AUTO_PROJECTS, prev=HAND_PREV)
        got = [(x["근거"], x["상태"], x["공급가액"], x["부가세"]) for x in hand_rows(r.execs)]
        self.assertEqual(got, [("구두 발주", "요청미지급", "1000000", "100000"), ("카드 사용", "카드사용미결제", "300000", ""),
                               ("금액 확인 중", "요청미지급", "", "")])
        self.assertFalse([x for x in r.execs.rows if x["근거"] in ("발주서", "WEHAGO 2026-10-01 전표 1")
                          or x["근거"].startswith("지급요청 6001")])
        self.assertIn("이전 프로젝트집행.csv 손으로 넣은 미지급 줄 3건 옮김 (근거가 'WEHAGO '·'지급요청'으로 시작하지 않는 "
                      "요청미지급·카드사용미결제): 공급가액+부가세 1,400,000원 (금액 미확인 1건)", r.execs.notes)
        res = results(r.execs)
        self.assertEqual(res[convert_projects.HAND_LABEL], "일치")
        self.assertEqual(res[convert_projects.OVERLAP_LABEL], "일치")

    def test_a_hand_row_that_matches_a_regenerated_row_is_kept_and_flagged(self):
        prev = [exec_row("26220", "조명", "가상조명", "요청미지급", "200,000", "20,000", "가상조명 구두")]
        r = Run(AUTO_JOURNAL, AUTO_PAYMENTS, AUTO_PROJECTS, AUTO_LEDGER, prev=prev)
        self.assertEqual(len(hand_rows(r.execs)), 1)   # 지출을 적게 잡지 않는다: 옮기고 알린다
        c = [x for x in r.execs.checks if x.label == convert_projects.OVERLAP_LABEL][0]
        self.assertEqual((c.source, c.csv, convert.check_result(c)), (0, 1, "불일치"))
        self.assertTrue([n for n in r.execs.notes if n.startswith("겹칠 수 있음: 손으로 넣은 줄 26220 가상조명 220,000 (가상조명 구두)")],
                        r.execs.notes)

    def test_a_hand_row_naming_a_regenerated_request_is_an_overlap(self):
        prev = [exec_row("26220", "조명", "", "요청미지급", "100,000", "", "구두 (지급요청 6001 일부)")]
        r = Run(AUTO_JOURNAL, AUTO_PAYMENTS, AUTO_PROJECTS, AUTO_LEDGER, prev=prev)
        c = [x for x in r.execs.checks if x.label == convert_projects.OVERLAP_LABEL][0]
        self.assertEqual(c.csv, 1)

    def test_the_hand_check_catches_the_pre_fix_rows(self):
        r = Run([], [], AUTO_PROJECTS, prev=HAND_PREV)
        before = [x for x in r.execs.rows if x not in hand_rows(r.execs)]
        c = convert_projects.hand_check(HAND_PREV, before)
        self.assertEqual((c.source, c.csv, convert.check_result(c)), (3, 0, "불일치"))



# ───────────── WR-05: 누계는 분개장 기간 기준, 기간 앞 이력이 있으면 판단 불가 (기간 밖) ─────────────
D_EARLY = dt.date(2026, 10, 1)
PERIOD_JOURNAL = AUTO_JOURNAL + [
    jl(D_EARLY, 39, "10800", "수입수수료미수금", 33000000, None, "가상고객", "[26220] 선금"),
    jl(D_EARLY, 39, "41200", "수입수수료", None, 30000000, "가상고객", "[26220] 선금"),
    jl(D_EARLY, 39, "25500", "부가세예수금", None, 3000000, "가상고객")]
# 26220 의 지급요청 6001 은 2026-10-20 에 등록 (분개장 시작 2026-10-01 뒤), 26221 은 행사일이 분개장 시작 전 (2026-09-10)
PERIOD_PROJECTS = [proj(1, "[26220] 가상 전시"), proj(2, "[26221] 가상 지난 워크숍", event="2026-09-10")]
EARLY_PAYMENTS = AUTO_PAYMENTS + [pay(6009, "[26220] 가상 전시", "가상무대", "2026-09-01 09:00:00", 5000000)]


def xrow(table, key, item):
    got = [r for r in table.rows if r["대상"] == key and r["항목"] == item]
    return got[0] if got else None


class TestWR05JournalPeriod(unittest.TestCase):
    def test_the_period_is_recorded_and_in_period_projects_keep_their_numbers(self):
        r = Run(PERIOD_JOURNAL, AUTO_PAYMENTS, PERIOD_PROJECTS, AUTO_LEDGER)
        t = r.xchk()
        self.assertEqual(xrow(t, "", "분개장 기간")["비고"], "2026-10-01~2026-10-30")
        self.assertEqual(xrow(t, "26220", "WEHAGO 원가")["금액"], "200000")
        self.assertEqual(xrow(t, "26220", "WEHAGO 매출")["금액"], "30000000")
        # 26221: 행사일 2026-09-10 이 분개장 시작(2026-10-01) 전 → 0 이 아니라 판단 불가 (기간 밖)
        cell = xrow(t, "26221", "WEHAGO 원가")
        self.assertEqual(cell["금액"], "")
        self.assertIn("판단 불가 (기간 밖: 분개장 시작 2026-10-01 전 행사일 2026-09-10)", cell["비고"])
        self.assertEqual(xrow(t, "26221", "WEHAGO 원가 (분개장 기간)")["금액"], "0")
        self.assertEqual(xrow(t, "26221", "WEHAGO 매출")["금액"], "")
        for label, res in results(t).items():
            self.assertEqual(res, "일치", label)

    def test_a_request_registered_before_the_journal_start_marks_the_project(self):
        r = Run(PERIOD_JOURNAL, EARLY_PAYMENTS, PERIOD_PROJECTS, AUTO_LEDGER)
        t = r.xchk()
        cell = xrow(t, "26220", "WEHAGO 원가")
        self.assertEqual(cell["금액"], "")
        self.assertIn("판단 불가 (기간 밖: 분개장 시작 2026-10-01 전 지급요청 등록 2026-09-01)", cell["비고"])
        self.assertEqual(xrow(t, "26220", "WEHAGO 원가 (분개장 기간)")["금액"], "200000")
        for label, res in results(t).items():   # 대조는 기간 합계로 한다
            self.assertEqual(res, "일치", label)

    def test_project_csv_revenue_total_is_unknown_for_out_of_period_projects(self):
        r = Run(PERIOD_JOURNAL, EARLY_PAYMENTS, PERIOD_PROJECTS, AUTO_LEDGER)
        history = convert_projects.out_of_period(r.books, r.projects, r.requests)
        self.assertEqual(sorted(history), ["26220", "26221"])
        t = convert_projects.build_projects(r.projects, r.revenue, [], history, convert_projects.period_text(r.books))
        rows = dict((x["프로젝트번호"], x) for x in t.rows)
        self.assertEqual((rows["26220"]["매출반영누계"], rows["26221"]["매출반영누계"]), ("", ""))
        self.assertTrue([n for n in t.notes if n.startswith("매출반영누계 판단 불가 (기간 밖) 2건")], t.notes)
        self.assertTrue([n for n in t.notes if n.startswith("매출반영누계는 분개장 기간 2026-10-01~2026-10-30 합계")], t.notes)
        for label, res in results(t).items():
            self.assertEqual(res, "일치", label)

    def test_the_period_checks_catch_a_known_zero(self):
        r = Run(PERIOD_JOURNAL, AUTO_PAYMENTS, PERIOD_PROJECTS, AUTO_LEDGER)
        t = r.xchk()
        before = [dict(x) for x in t.rows]
        for x in before:   # 고치기 전 모양: 기간 밖 프로젝트의 누계가 0 (아는 값)
            if x["대상"] == "26221" and x["항목"] in ("WEHAGO 원가", "WEHAGO 매출"):
                x["금액"] = "0"
        history = convert_projects.out_of_period(r.books, r.projects, r.requests)
        for c in convert_xchk.period_checks(history, before):
            self.assertEqual(convert.check_result(c), "불일치", c.label)
        h = convert_projects.out_of_period(r.books, r.projects, r.requests)
        rows = [{"프로젝트번호": "26221", "매출반영누계": "0"}, {"프로젝트번호": "26220", "매출반영누계": "30000000"}]
        self.assertEqual(convert.check_result(convert_projects.period_check(h, rows)), "불일치")

    def test_section_8_labels_the_period_and_shows_out_of_period_cells(self):
        r = Run(PERIOD_JOURNAL, AUTO_PAYMENTS, PERIOD_PROJECTS, AUTO_LEDGER)
        X, html = render_s8(self, r.xchk())
        self.assertIn("WEHAGO 원가 (2026-10~2026-10 장부 기준)", html)
        self.assertIn("WEHAGO 매출 (2026-10~2026-10 장부 기준)", html)
        self.assertIn("분개장 기간 2026-10-01~2026-10-30", html)
        p = [x for x in X["projects"] if x["key"] == "26221"][0]
        self.assertTrue(p["out_of_period"])
        self.assertIsNone(p["cost_vs_budget"])
        self.assertIn("판단 불가 (기간 밖)", html)



# ───────────── WR-06: 어떤 스냅숏을 썼는지 화면에 보이고, 오래됐거나 기준일 뒤면 경고 ─────────────
class TestWR06SnapshotAge(unittest.TestCase):
    def test_the_console_names_the_snapshot_and_its_age(self):
        tmp, input_dir, collect, wehago_dir = company(self, snapshot_at=dt.datetime(2026, 10, 30, 18, 0))
        res = run_convert_core(input_dir, collect, wehago_dir)
        self.assertEqual(res.code, 0, res.lines)
        self.assertIn("인트라넷 스냅숏 인트라넷_20261030_180000 (수집 2026-10-30 18:00:00, 기준일보다 3일 이전)", res.lines)
        self.assertFalse([ln for ln in res.lines if ln.startswith("경고: 인트라넷 스냅숏")], res.lines)
        self.assertNotIn("경고: 인트라넷 스냅숏", result_text(input_dir))

    def test_an_old_snapshot_is_warned_on_the_console_and_in_the_result(self):
        tmp, input_dir, collect, wehago_dir = company(self, snapshot_at=dt.datetime(2026, 10, 1, 9, 0))
        res = run_convert_core(input_dir, collect, wehago_dir)
        self.assertEqual(res.code, 0, res.lines)
        want = ("경고: 인트라넷 스냅숏이 기준일보다 32일 이전 (수집 2026-10-01 09:00:00) — 설정 변환_스냅숏경과일 7일을 넘음: "
                "지급요청·프로젝트가 오래됐을 수 있음 (승인검토.py로 새로 수집한 뒤 다시 변환)")
        self.assertIn(want, res.lines)
        self.assertIn(want, result_text(input_dir).splitlines())

    def test_the_limit_comes_from_the_setting(self):
        from test_approval import edit_csv
        tmp, input_dir, collect, wehago_dir = company(self, snapshot_at=dt.datetime(2026, 10, 1, 9, 0))
        edit_csv(input_dir, "설정.csv", lambda rows: set_setting_rows(rows, "변환_스냅숏경과일", "40"))
        res = run_convert_core(input_dir, collect, wehago_dir)
        self.assertFalse([ln for ln in res.lines if ln.startswith("경고: 인트라넷 스냅숏")], res.lines)
        cfg, notes = convert.read_config(settings_folder(self, ["변환_스냅숏경과일", "0"]))
        self.assertEqual(cfg["snapshot_days"], 1)
        self.assertIn("설정 변환_스냅숏경과일 값 0 범위 밖 (1~3650) → 1 사용", notes)
        self.assertEqual(convert.read_config(settings_folder(self))[0]["snapshot_days"], 7)

    def test_a_snapshot_collected_after_the_report_date_is_warned(self):
        tmp, input_dir, collect, wehago_dir = company(self, snapshot_at=dt.datetime(2026, 11, 5, 9, 0))
        res = run_convert_core(input_dir, collect, wehago_dir)
        want = ("경고: 인트라넷 스냅숏이 기준일(2026-11-02)보다 3일 뒤에 수집됨 (수집 2026-11-05 09:00:00) — "
                "기준일 시점의 지급요청·프로젝트가 아닐 수 있음")
        self.assertIn(want, res.lines)
        self.assertIn(want, result_text(input_dir).splitlines())

    def test_without_a_snapshot_the_console_says_so(self):
        from test_convert import convert_input, write_convert_books
        tmp, input_dir, collect, wehago_dir = convert_input(self)
        write_convert_books(wehago_dir)
        res = run_convert_core(input_dir, collect, wehago_dir)
        self.assertIn("인트라넷 스냅숏: 없음 — 자동 연결 안 함", res.lines)


if __name__ == "__main__":
    unittest.main()
