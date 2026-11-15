"""2026-11-15 규칙(안전·계산·보고·운영)을 번호대로 고정하는 시험. 프로젝트 메모리의 규칙 줄마다 '확인: 같은 번호'.

모두 가상 자료다 (실제 입력/·수집/ 폴더는 열지 않는다). 실제 자료에서 찾은 오류(R1·R2·R10 …)를 다시 만드는 모양을
가상 자료로 옮겼다: 고친 뒤에 다시 생기면 실패한다. 통과는 '이미 알고 막은 것'만 보증한다 (점검 방법 4).
"""
import datetime as dt
import io
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import approval, checklist, convert, corptax, linking, payreq, screen_values  # noqa: E402
from ceo_report.convert_projects import split_vat, withholding_gross  # noqa: E402
from test_convert_review_fixes import (AUTO_PROJECTS, Run, jl, money, naming, pay, results,  # noqa: E402
                                       unpaid_total)

D = dt.date


def _read(path, enc="utf-8"):
    with open(path, encoding=enc) as f:
        return f.read()
D25 = D(2026, 10, 25)


# ───────────── 안전-07: 화면에서 읽는 승인 글자는 한 곳의 목록, 처음 보는 글자는 숫자에 넣지 않음 ─────────────
class TestSafety07ScreenValues(unittest.TestCase):
    def test_safety07_the_lists_are_what_was_seen_on_the_real_screen(self):
        # 글자를 더하거나 빼면 이 시험도 고친다 (본 날짜·건수는 screen_values.py 에)
        self.assertEqual(screen_values.CEO_APPROVED, ("수락완료", "승인"))
        self.assertEqual(screen_values.CEO_PENDING, ("미승인", "수락요청중"))
        self.assertEqual(screen_values.ADMIN_DONE_WAITING, ("반려",))
        self.assertEqual(screen_values.PROJECT_STAGE_DONE, ("완료", "수락완료", "승인완료", "반려"))
        self.assertEqual(screen_values.PROJECT_STAGE_ALL_DONE, ("완료", "수락완료", "승인완료"))
        self.assertEqual(screen_values.PROJECT_STAGE_WAITING, ("승인", "미승인", ""))

    def test_safety07_every_reader_uses_the_one_list(self):
        # R1: '수락완료'를 한 곳(payreq)은 끝남, 다른 곳(approval·linking)은 모름으로 읽었다
        for text, want in (("수락완료", "approved"), ("승인", "approved"), (" 수락완료 ", "approved"),
                           ("미승인", "pending"), ("수락요청중", "pending"), ("", "status_unknown"), ("반려", "status_unknown")):
            self.assertEqual(approval._status(text), want, text)
            self.assertEqual(screen_values.ceo_status(text), want, text)
        self.assertEqual(payreq.CEO_DONE, screen_values.CEO_APPROVED)
        self.assertEqual(payreq.ADMIN_DONE_WAITING, screen_values.ADMIN_DONE_WAITING)
        self.assertEqual(linking.APPROVAL_DONE, screen_values.PROJECT_STAGE_DONE)

    def test_safety07_blank_is_not_a_new_value(self):
        self.assertTrue(screen_values.is_new_ceo_value("보류"))
        self.assertFalse(screen_values.is_new_ceo_value(""))
        self.assertFalse(screen_values.is_new_ceo_value(None))
        self.assertFalse(screen_values.is_new_ceo_value("수락완료"))
        self.assertTrue(screen_values.is_new_project_value("보류"))
        self.assertFalse(screen_values.is_new_project_value("반려"))

    def test_safety07_new_value_is_left_out_of_the_numbers_and_named(self):
        journal = [jl(D25, 60, "61101", "행사외주비(도)", 1000000, None, "가상음향", "[26220] 음향"),
                   jl(D25, 60, "10300", "보통예금", None, 1000000, "가상음향")]
        r = Run(journal, [pay(6202, "[26220] 가상 전시", "가상렌탈", "2026-10-20 09:00:00", 7000000, boss="보류")], AUTO_PROJECTS)
        self.assertEqual(naming(r.execs, "6202"), [])
        self.assertEqual(unpaid_total(r.execs), 0)
        self.assertIn("처음 보는 사장님승인 글자 1건 → 프로젝트집행에 넣지 않음 (규칙 안전-07, 화면 확인 필요): 6202 '보류'",
                      r.execs.notes)
        x = r.xchk()   # 경영관리 대조표에는 그대로 보인다 (경고)
        lines = [row for row in x.rows if row["구분"] == "요청상태확인필요줄"]
        self.assertEqual([(row["대상"], row["항목"]) for row in lines], [("6202", "사장님승인 '보류' 처음 보는 글자")])
        for label, res in results(r.execs).items():
            self.assertEqual(res, "일치", label)


# ───────────── 계산-12 (결정 b): 지급요청 금액은 부가세 포함 → 예산 비교는 공급가액 ─────────────
class TestCalc12VatSplit(unittest.TestCase):
    def test_calc12_split_values(self):
        for amount, want in ((1100000, (1000000, 100000)), (264000, (240000, 24000)), (160500000, (145909091, 14590909)),
                             (10, (9, 1)), (1, (1, 0)), (0, (0, 0)), (-1100000, (-1000000, -100000)), (None, (None, None))):
            self.assertEqual(split_vat(amount), want, amount)

    def test_calc12_the_two_parts_always_add_back_to_the_request(self):
        for amount in list(range(-200, 2000)) + [999999999, 123456789]:
            supply, vat = split_vat(amount)
            self.assertEqual(supply + vat, amount, amount)
            self.assertLessEqual(abs(vat * 10 - supply), 10, amount)   # 부가세 ≈ 공급가액의 10%

    def test_calc12_request_row_has_both_columns(self):
        # R2: 예전에는 부가세 포함 금액 전부를 공급가액 칸에 넣어 예산 대비 쓴 돈이 10% 크게 잡혔다
        r = Run([], [pay(6301, "[26220] 가상 전시", "가상새거래처", "2026-10-20 09:00:00", 3300000)], AUTO_PROJECTS)
        row = naming(r.execs, "6301")
        self.assertEqual([(x["공급가액"], x["부가세"]) for x in row], [("3000000", "300000")])
        self.assertIn("부가세 포함으로 나눔", row[0]["근거"])
        for label, res in results(r.execs).items():
            self.assertEqual(res, "일치", label)


    def test_calc12_withholding_amounts_are_not_split(self):
        # 11/15 카드: 원천세(사업소득 3.3%·기타소득 8.8%) 뗀 금액으로 딱 떨어지고 부가세로는 안 떨어지면 떼기 전 금액(추정)
        for amount, want in ((290100, (300000, 0.033)), (67690, (70000, 0.033)), (967000, (1000000, 0.033)),
                             (456000, (500000, 0.088)), (912000, (1000000, 0.088)),
                             (1100000, None), (264000, None), (3300000, None), (87700, None), (1000000, None),
                             (0, None), (None, None), (-967000, None),
                             # 소액부징수: 국세 원천세 1,000원 미만이면 떼지 않으므로 원천세 뗀 금액으로 보지 않음 (실제 14,500원 요청)
                             (14500, None), (19340, None), (32880, (34000, 0.033)), (31920, (35000, 0.088))):
            self.assertEqual(withholding_gross(amount), want, amount)

    def test_calc12_withholding_request_row_is_the_amount_before_withholding(self):
        r = Run([], [pay(6302, "[26220] 가상 전시", "디자이너_가상", "2026-10-20 09:00:00", 967000),
                     pay(6303, "[26220] 가상 전시", "가상새거래처", "2026-10-20 09:00:00", 1100000)], AUTO_PROJECTS)
        one, two = naming(r.execs, "6302"), naming(r.execs, "6303")
        self.assertEqual([(x["공급가액"], x["부가세"]) for x in one], [("1000000", "0")])
        self.assertIn("원천세 3.3% 뗀 금액으로 보아 떼기 전 금액 추정", one[0]["근거"])
        self.assertEqual([(x["공급가액"], x["부가세"]) for x in two], [("1000000", "100000")])
        for label, res in results(r.execs).items():   # 금액 대조는 더한 원천세만큼 빼고 맞춘다
            self.assertEqual(res, "일치", label)


# ───────────── 계산-15 (결정 a): '수락완료' = 대표 승인 끝 · 이미 지급한 요청을 다시 미지급으로 세지 않음 ─────────────
def paid_slip(day, no, vendor, supply, vat=0, memo="[26220] 행사", withheld=0):
    """원가 (도) 줄 + (부가세) + 원천세 예수금 + 통장 출금: 바로 지급한 전표."""
    out = [jl(day, no, "61101", "행사외주비(도)", supply, None, vendor, memo)]
    if vat:
        out.append(jl(day, no, "13500", "부가세대급금", vat, None, vendor, memo))
    if withheld:
        out.append(jl(day, no, "25400", "예수금", None, withheld, vendor, memo))
    out.append(jl(day, no, "10300", "보통예금", None, supply + vat - withheld, vendor, memo))
    return out


def payable_slip(day, no, vendor, supply, vat, memo="[26220] 행사"):
    """원가 (도) 줄 + 부가세 + 미지급금: 계산서만 받고 아직 안 낸 전표."""
    return [jl(day, no, "61101", "행사외주비(도)", supply, None, vendor, memo),
            jl(day, no, "13500", "부가세대급금", vat, None, vendor, memo),
            jl(day, no, "25300", "미지급금", None, supply + vat, vendor, memo)]


class TestCalc15AcceptedRequests(unittest.TestCase):
    def test_calc15_accepted_request_paid_through_payables_is_already_paid(self):
        journal = payable_slip(D(2026, 10, 15), 70, "가상조명", 1000000, 100000) + [
            jl(D(2026, 10, 23), 71, "25300", "미지급금", 1100000, None, "가상조명", "[26220] 조명"),
            jl(D(2026, 10, 23), 71, "10300", "보통예금", None, 1100000, "가상조명", "[26220] 조명")]
        r = Run(journal, [pay(7101, "[26220] 가상 전시", "가상조명", "2026-10-20 09:00:00", 1100000, boss="수락완료")],
                AUTO_PROJECTS)
        self.assertEqual(r.requests[0]["status"], "approved")
        self.assertEqual(r.match["rows"]["7101"]["status"], "이미 지급")
        self.assertFalse([x for x in r.execs.rows if x["상태"] == "요청미지급" and x["근거"].startswith("지급요청 7101")])

    def test_calc15_vendor_name_differs_but_project_and_amount_match_a_paid_row(self):
        # R1 실제 모양: 인트라넷 '파트너'는 줄인 이름, 장부는 법인 이름 → 거래처 후보 0건 → 예전엔 요청 줄을 또 넣어 두 번 셈
        journal = paid_slip(D(2026, 10, 24), 72, "주식회사 가상아웃컴퍼니", 1000000, 100000)
        r = Run(journal, [pay(7102, "[26220] 가상 전시", "가상아웃", "2026-10-20 09:00:00", 1100000, boss="수락완료")],
                AUTO_PROJECTS)
        self.assertTrue(r.match["rows"]["7102"]["label"].startswith("연결 불가 (거래처 후보 0건)"))
        rows = naming(r.execs, "7102")
        self.assertEqual([(x["상태"], money(x)) for x in rows], [("지급완료", 1100000)])
        self.assertIn("(프로젝트·금액으로 짝지음)", rows[0]["근거"])
        self.assertEqual(unpaid_total(r.execs), 0)
        self.assertTrue([n for n in r.execs.notes if n.startswith("장부 원가 줄과 프로젝트·금액으로 짝지은 지급요청 1건")], r.execs.notes)
        for label, res in results(r.execs).items():
            self.assertEqual(res, "일치", label)

    def test_calc15_freelancer_request_is_the_amount_after_withholding(self):
        # 실제: 강사·디자이너 요청은 3.3%(사업소득)·8.8%(기타소득) 뗀 금액, 장부 원가는 떼기 전 금액이고 거래처는 '사업소득'
        journal = (paid_slip(D(2026, 10, 24), 73, "사업소득", 1000000, withheld=33000)
                   + paid_slip(D(2026, 10, 24), 74, "기타소득", 500000, withheld=44000))
        r = Run(journal, [pay(7103, "[26220] 가상 전시", "디자이너_가상", "2026-10-20 09:00:00", 967000, boss="수락완료"),
                          pay(7104, "[26220] 가상 전시", "강사_가상", "2026-10-20 09:00:00", 456000, boss="수락완료")],
                AUTO_PROJECTS)
        for no in ("7103", "7104"):
            rows = naming(r.execs, no)
            self.assertEqual([x["상태"] for x in rows], ["지급완료"], no)
            self.assertIn("(프로젝트·원천세 뗀 금액으로 짝지음)", rows[0]["근거"], no)
        self.assertEqual(unpaid_total(r.execs), 0)
        for label, res in results(r.execs).items():
            self.assertEqual(res, "일치", label)

    def test_calc15_request_before_ceo_approval_never_pairs_with_a_paid_row(self):
        # D-17: 대표 승인 전에는 지급하지 않는다 → 같은 금액이 이미 나갔어도 다른 지급이다 (요청 줄로 남김)
        journal = paid_slip(D(2026, 10, 24), 75, "주식회사 가상아웃컴퍼니", 1000000, 100000)
        r = Run(journal, [pay(7105, "[26220] 가상 전시", "가상아웃", "2026-10-20 09:00:00", 1100000, boss="미승인")],
                AUTO_PROJECTS)
        self.assertEqual([x["상태"] for x in naming(r.execs, "7105")], ["요청미지급"])
        self.assertEqual(unpaid_total(r.execs), 1100000)

    def test_calc15_pending_request_pairs_with_the_unpaid_invoice_row(self):
        journal = payable_slip(D(2026, 10, 22), 76, "주식회사 가상한진기획", 500000, 50000)
        r = Run(journal, [pay(7106, "[26220] 가상 전시", "가상한진기획 (메이)", "2026-10-20 09:00:00", 550000, boss="미승인")],
                AUTO_PROJECTS)
        rows = naming(r.execs, "7106")
        self.assertEqual([(x["상태"], money(x), x["확정여부"]) for x in rows], [("요청미지급", 550000, "추정")])
        self.assertTrue(rows[0]["근거"].startswith("WEHAGO 2026-10-22 전표 76"), rows[0])
        self.assertEqual(unpaid_total(r.execs), 550000)   # 두 번 세지 않음 (예전 1,100,000)

    def test_calc15_payment_before_the_request_was_registered_is_another_payment(self):
        # D-30b: 등록 전에 나간 같은 금액은 이 요청의 지급이 아니다
        journal = paid_slip(D(2026, 10, 10), 77, "주식회사 가상아웃컴퍼니", 1000000, 100000)
        r = Run(journal, [pay(7107, "[26220] 가상 전시", "가상아웃", "2026-10-20 09:00:00", 1100000, boss="수락완료")],
                AUTO_PROJECTS)
        self.assertEqual([x["상태"] for x in naming(r.execs, "7107")], ["요청미지급"])

    def test_calc15_two_same_rows_are_paired_one_each_and_listed_for_checking(self):
        # 계산-01: 후보가 둘 이상이면 확인할 것에 (금액이 같아 합계는 같음)
        journal = (paid_slip(D(2026, 10, 22), 78, "사업소득", 70000, withheld=2310)
                   + paid_slip(D(2026, 10, 29), 79, "사업소득", 70000, withheld=2310))
        r = Run(journal, [pay(7108, "[26220] 가상 전시", "디자이너_가상", "2026-10-20 09:00:00", 67690, boss="수락완료")],
                AUTO_PROJECTS)
        self.assertEqual(len(naming(r.execs, "7108")), 1)
        self.assertEqual(unpaid_total(r.execs), 0)
        note = [n for n in r.execs.notes if n.startswith("[확인] 지급요청 짝짓기")]
        self.assertEqual(len(note), 1, r.execs.notes)
        self.assertIn("1건", note[0])
        items = checklist.convert_items([], [], r.execs.notes)
        self.assertEqual([it["kind"] for it in items if it["id"].startswith("요청짝|")], ["변환 대조"])

    def test_calc15_two_requests_and_one_row_count_the_second_request(self):
        journal = paid_slip(D(2026, 10, 24), 80, "주식회사 가상아웃컴퍼니", 1000000, 100000)
        r = Run(journal, [pay(7109, "[26220] 가상 전시", "가상아웃", "2026-10-20 09:00:00", 1100000, boss="수락완료"),
                          pay(7110, "[26220] 가상 전시", "가상아웃", "2026-10-21 09:00:00", 1100000, boss="수락완료")],
                AUTO_PROJECTS)
        self.assertEqual([x["상태"] for x in naming(r.execs, "7109")], ["지급완료"])   # 먼저 등록한 요청이 그 줄
        self.assertEqual([x["상태"] for x in naming(r.execs, "7110")], ["요청미지급"])
        self.assertEqual(unpaid_total(r.execs), 1100000)

    def test_calc15_result_does_not_depend_on_request_order(self):
        journal = (paid_slip(D(2026, 10, 22), 81, "사업소득", 70000, withheld=2310)
                   + payable_slip(D(2026, 10, 23), 82, "주식회사 가상한진기획", 500000, 50000))
        pays = [pay(7111, "[26220] 가상 전시", "디자이너_가상", "2026-10-20 09:00:00", 67690, boss="수락완료"),
                pay(7112, "[26220] 가상 전시", "가상한진기획", "2026-10-20 10:00:00", 550000, boss="미승인")]
        a = Run(journal, pays, AUTO_PROJECTS)
        b = Run(journal, list(reversed(pays)), AUTO_PROJECTS)
        self.assertEqual([(x["근거"], money(x)) for x in a.execs.rows], [(x["근거"], money(x)) for x in b.execs.rows])


# ───────────── 계산-08 (결정 d): 법인세 예상은 장부에 넣은 비용만 뺌, 대손충당금은 '쌓으면 세금 −X'만 ─────────────
class TestCalc08BadDebt(unittest.TestCase):
    def journal(self):
        from test_dept import line
        return [line(D(2026, 3, 5), "41200", "용역매출", credit=300_000_000),
                line(D(2026, 3, 5), "10800", "외상매출금", 330_000_000),
                line(D(2026, 3, 5), "61000", "외주비(도)", 100_000_000)]

    def test_calc08_bad_debt_is_not_taken_off_the_tax_base(self):
        rows, _ = corptax.from_journal(self.journal(), dict(convert.DEFAULT_CONFIG), D(2026, 11, 4), {})
        ct = rows[0]
        # 300 − 100 = 200 (백만): 대손충당금 예상 3.3백만(외상매출금 330 × 1%)을 빼지 않는다 (예전 196.7)
        self.assertEqual(ct["과세표준"], "200000000")
        self.assertEqual(ct["대손충당금"], "3300000")
        self.assertIn("대손충당금 예상 3,300,000원은 세무사 확인 전이라 빼지 않음 (쌓으면 세금 −", ct["근거"])
        m = re.search(corptax.BAD_DEBT_HINT_RE, ct["근거"])
        saving = int(m.group(2).replace(",", ""))
        nat, corp, _ = corptax.national(200_000_000, "2026")
        nat2, corp2, _ = corptax.national(200_000_000 - 3_300_000, "2026")
        self.assertEqual(saving, nat + int(corp * corptax.LOCAL_RATE) - nat2 - int(corp2 * corptax.LOCAL_RATE))
        self.assertGreater(saving, 0)

    def test_calc08_no_hint_when_nothing_to_set_aside(self):
        from test_dept import line
        rows, _ = corptax.from_journal([line(D(2026, 3, 5), "41200", "용역매출", credit=300_000_000)],
                                       dict(convert.DEFAULT_CONFIG), D(2026, 11, 4), {})
        self.assertNotIn("세무사 확인 전이라 빼지 않음", rows[0]["근거"])


class TestReportChartBasis(unittest.TestCase):
    """대표 월간 월별 그림 막대는 계산서 기준 그대로, 범례에 '계산서 기준' (사용자 카드 2026-11-15)."""

    def test_bars_are_labelled_invoice_basis(self):
        from test_month_chart import R as month_report
        from ceo_report import render as rd
        h = rd._month_chart(month_report())
        self.assertIn("매출 (계산서 기준)", h)
        self.assertIn("매입 (계산서 기준)", h)
        h = rd._month_chart(month_report(ev=None))          # 증빙월별.csv 없으면 손익 기준 매출만
        self.assertIn("매출 (손익 기준)", h)
        self.assertNotIn("계산서 기준", h)


class TestArticlesInterimDividend(unittest.TestCase):
    """정관 42조 중간배당: 영업연도 중 1회 (괄호의 '주총 결의로 분기별'은 상장회사 특례, 정관 원문 확인 2026-11-15)."""

    def test_interim_dividend_once_a_year(self):
        from ceo_report import articles
        rules = {a: (b, c) for a, b, c in articles.RULES}
        law, plain = rules["중간배당"]
        self.assertIn("1회", law)
        self.assertNotIn("분기마다", law + plain)
        self.assertIn("1년에 한 번", plain)
        self.assertIn("주주총회 결의 또는 대표권 있는 이사(대표이사)의 결정", rules["누가 결정하나"][0])


class TestAssumptionMinorDividend(unittest.TestCase):
    """미성년 주주 배당은 이자·배당을 합쳐 연 2천만 원 이하로 권함 (사용자 카드 2026-11-15)."""

    def plan(self, interest):
        import tempfile
        from ceo_report import dividend as dv
        d = tempfile.mkdtemp()
        dv.save(d, "부모", "50", False, False, "", "")
        dv.save(d, "자녀", "50", True, False, interest, "")
        return dv.plan(d, D(2026, 11, 12), 500_000_000)

    def test_minor_interest_counts_toward_the_20m(self):
        self.assertEqual(self.plan("")["best"], 40_000_000)            # 자녀 배당 2천만
        self.assertEqual(self.plan("15000000")["best"], 10_000_000)    # 자녀 이자 1,500만 + 배당 500만 = 2천만


class TestDecisionCMissingContract(unittest.TestCase):
    """결정 c (2026-11-15): 계약금액이 없어 예상 이익을 못 낸 프로젝트 수를 팀장·대표 보고에 한 줄 (실제 302개 모두 빈칸, R3)."""

    def R(self):
        return {"asof": D(2026, 11, 13), "s5": {},
                "s3": {"projects": [{"id": "26001", "name": "가 행사", "team": "기획1팀", "contract": None},
                                    {"id": "26002", "name": "나 행사", "team": "기획2팀", "contract": 5_000_000},
                                    {"id": "26003", "name": "다 행사", "team": "기획1팀", "contract": 0}]}}

    def test_count_and_ceo_line(self):
        from ceo_report import insights, render
        R = self.R()
        self.assertEqual(insights.missing_contracts(R), 2)
        self.assertEqual(insights.missing_contracts(R, "기획1팀"), 2)
        self.assertEqual(insights.missing_contracts(R, "기획2팀"), 0)
        self.assertIn("계약금액이 없어 지금 예상 이익을 못 낸 프로젝트 2개", render._contract_line(R))
        R["s3"]["projects"] = R["s3"]["projects"][1:2]
        self.assertEqual(render._contract_line(R), "")

    def test_team_report_shows_the_count_even_without_profit_rows(self):
        from ceo_report import insights_render
        I = {"flow": [], "alerts": [], "pairs": []}
        h = insights_render.team_section(I, self.R(), "기획1팀")
        self.assertIn("프로젝트 이익 흐름", h)
        self.assertIn("계약금액이 없어 지금 예상 이익을 못 낸 프로젝트 2개", h)
        self.assertEqual(insights_render.team_section(I, self.R(), "기획2팀"), "")


class TestSafety05DownloadMove(unittest.TestCase):
    """안전-05 (R4·C10): 다운로드 폴더 자동수집 파일은 외장하드로 옮긴 뒤 지우고, 지난자료에 있는 것은 다시 가져오지 않음."""

    def setUp(self):
        import tempfile
        from ceo_report import app
        self.app = app
        self.dir = tempfile.mkdtemp()
        self.dl = os.path.join(self.dir, "dl")
        os.makedirs(os.path.join(self.dl, app.AUTO_DIR))
        self.paths = app.Paths(os.path.join(self.dir, "prog"))
        self.said = []

    def put(self, folder, name, text, mtime=None):
        os.makedirs(folder, exist_ok=True)
        p = os.path.join(folder, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        if mtime:
            os.utime(p, (mtime, mtime))
        return p

    def run_import(self):
        return self.app.import_auto(self.paths, self.said.append, dirs=[self.dl])

    def test_moved_not_copied(self):
        src = self.put(os.path.join(self.dl, self.app.AUTO_DIR), "261105 분개장 자동수집.json", '{"a": 1}')
        self.assertEqual(self.run_import(), 1)
        self.assertFalse(os.path.exists(src))                      # 다운로드 폴더에 남지 않음
        with open(os.path.join(self.paths.wehago, "261105 분개장 자동수집.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"a": 1}')

    def test_archived_file_is_not_imported_again(self):
        arch = os.path.join(self.paths.wehago, self.app.ARCHIVE)
        self.put(arch, "261105 분개장 자동수집.json", '{"old": 1}')
        src = self.put(os.path.join(self.dl, self.app.AUTO_DIR), "261105 분개장 자동수집.json", '{"old": 1}')
        self.assertEqual(self.run_import(), 0)
        self.assertFalse(os.path.exists(os.path.join(self.paths.wehago, "261105 분개장 자동수집.json")))
        self.assertFalse(os.path.exists(src))                      # 같은 내용이 지난자료에 있어 다운로드 쪽만 지움
        self.assertIn("다시 가져오지 않음", " ".join(self.said))

    def test_older_download_goes_to_archive_not_deleted(self):
        self.put(self.paths.wehago, "261105 분개장 자동수집.json", '{"new": 2}', mtime=2_000_000_000)
        src = self.put(os.path.join(self.dl, self.app.AUTO_DIR), "261105 분개장 자동수집.json", '{"old": 1}', mtime=1_900_000_000)
        self.assertEqual(self.run_import(), 0)
        self.assertFalse(os.path.exists(src))
        arch = os.path.join(self.paths.wehago, self.app.ARCHIVE)
        self.assertEqual(os.listdir(arch), ["261105 분개장 자동수집.json"])
        with open(os.path.join(self.paths.wehago, "261105 분개장 자동수집.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"new": 2}')

    def test_newer_download_keeps_the_old_file_in_archive(self):
        self.put(self.paths.wehago, "261105 분개장 자동수집.json", '{"old": 1}', mtime=1_900_000_000)
        self.put(os.path.join(self.dl, self.app.AUTO_DIR), "261105 분개장 자동수집.json", '{"new": 2}', mtime=2_000_000_000)
        self.assertEqual(self.run_import(), 1)
        with open(os.path.join(self.paths.wehago, "261105 분개장 자동수집.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"new": 2}')
        with open(os.path.join(self.paths.wehago, self.app.ARCHIVE, "261105 분개장 자동수집.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"old": 1}')                # 덮어써 잃지 않음


class TestN4ConversionTime(unittest.TestCase):
    """N4 (R5): 변환 시각은 실제 시각으로 (창은 기준일을 넘겨 예전엔 늘 기준일 00:00:00)."""

    def test_conversion_time_is_the_real_time(self):
        import tempfile
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        import 변환
        t = tempfile.mkdtemp()
        before = dt.datetime.now().replace(microsecond=0)
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            변환.main(["--기준일", "2026-01-02", "--입력", os.path.join(t, "입력"), "--수집폴더", os.path.join(t, "수집")])
        with open(os.path.join(t, "입력", "변환결과.txt"), encoding="utf-8-sig") as f:
            first = f.readline()
        m = re.match(r"변환 시각 (\S+ \S+) · 기준일 2026-01-02", first)
        self.assertIsNotNone(m, first)
        when = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        self.assertGreaterEqual(when, before)
        self.assertLessEqual(when, dt.datetime.now())


class TestCalc04PeriodValues(unittest.TestCase):
    """계산-04·R8: 국민연금 상한은 기간 값 (2026-07부터 659만), 기간 끝난 값은 그대로 쓰지 않음. 결정 h: 확인 기록."""

    def test_pension_cap_by_period(self):
        import tempfile
        from ceo_report import taxlaw
        d = tempfile.mkdtemp()
        self.assertEqual(taxlaw.value_on(d, "국민연금상한", D(2026, 6, 30))[:2], (6_370_000, True))
        self.assertEqual(taxlaw.value_on(d, "국민연금상한", D(2026, 7, 1))[:2], (6_590_000, True))
        self.assertEqual(taxlaw.value_on(d, "국민연금상한", D(2027, 7, 1))[:2], (None, False))   # 기간 밖: 옛 값으로 대신하지 않음

    def test_old_confirmation_of_ended_period_value_is_not_used(self):
        import tempfile
        from ceo_report import taxlaw
        d = tempfile.mkdtemp()
        taxlaw.confirm(d, 2026, {"국민연금상한": "6,370,000"}, "", today=D(2026, 11, 13))   # 실제: 11/13 637만 확인
        v, ok, why = taxlaw.value(d, 2026, "국민연금상한", today=D(2026, 11, 15))
        self.assertEqual((v, ok), (6_590_000, True))
        self.assertIn("다름", why)
        st = taxlaw.status(d, 2026, today=D(2026, 11, 15))
        row = [r for r in st["rows"] if r[0] == "국민연금상한"][0]
        self.assertFalse(row[5])                                   # '확인함'으로 보이지 않음

    def test_confirmation_record_has_no_default_source_and_keeps_who_and_effective_date(self):
        import csv as _csv
        import tempfile
        from ceo_report import taxlaw
        d = tempfile.mkdtemp()
        taxlaw.confirm(d, 2026, {"국민연금상한": "6,590,000"}, "", today=D(2026, 11, 16))
        taxlaw.confirm(d, 2026, {"최저한세율": "7%"}, "○○세무회계", today=D(2026, 11, 16), who="담당자", effective="2026-01-01")
        with open(os.path.join(d, taxlaw.FILE), encoding="utf-8-sig") as f:
            rows = {r["항목"]: r for r in _csv.DictReader(f)}
        self.assertEqual(rows["국민연금상한"]["출처"], "")            # 기본값 '세무사'로 채우지 않음
        self.assertEqual(rows["국민연금상한"]["시행일"], "2026-07-01")  # 기간 값은 그 기간 시작일
        self.assertEqual((rows["최저한세율"]["확인한 사람"], rows["최저한세율"]["시행일"]), ("담당자", "2026-01-01"))
        with self.assertRaises(ValueError):
            taxlaw.confirm(d, 2026, {"최저한세율": "7%"}, "고시", who="담당자", effective="7월1일")

    def test_payroll_uses_the_cap_of_that_month(self):
        from ceo_report import taxlaw
        import ceo_report.payroll as pr
        seen = []
        real = taxlaw.value_on
        def spy(input_dir, key, day, today=None):
            seen.append((key, day))
            return real(input_dir, key, day, today)
        import tempfile
        with mock_patch(taxlaw, "value_on", spy):
            pr.check(tempfile.mkdtemp(), "2026-08")
        self.assertIn(("국민연금상한", D(2026, 8, 1)), seen)


class TestR11LawFetchFailure(unittest.TestCase):
    """R11·A3: 법령 조문을 하나도 못 받으면 'N개 받음'이 아니라 '못 받음', 받은 날도 남기지 않음 (자동 확인이 다시 해 보게)."""

    def test_all_failed(self):
        import tempfile
        from ceo_report import app, lawwatch
        d = tempfile.mkdtemp()
        lawwatch.save_oc(d, "me")

        def broken(url, timeout=0):
            raise OSError("이름을 찾을 수 없음")
        rows = lawwatch.check(d, 2026, D(2026, 7, 2), broken)
        self.assertTrue(rows and all(r[2] == "실패" for r in rows))
        S = lawwatch.load(d)
        self.assertEqual(S.get("last", ""), "")
        self.assertEqual(S["last_try"]["받음"], 0)
        self.assertTrue(lawwatch.due(d, D(2026, 7, 20)))          # 그달에 다시 해 봄
        with mock_patch(lawwatch, "check", lambda i, y: rows):
            head = app.law_check(d, 2026)[0]
        self.assertIn("하나도 받지 못함", head)
        self.assertNotIn("개 받음", head)


class mock_patch(object):
    def __init__(self, obj, name, new):
        self.obj, self.name, self.new = obj, name, new

    def __enter__(self):
        self.old = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.new)

    def __exit__(self, *a):
        setattr(self.obj, self.name, self.old)


if __name__ == "__main__":
    unittest.main()


# ───────────── 계산-13 (결정 e): 예산의 수금도 계산서 작성일 + 60일, 장부 평균은 참고로만 ─────────────
class TestCalc13BudgetCollect(unittest.TestCase):
    def test_budget_uses_60_days_like_available_cash(self):
        import shutil
        import tempfile
        from ceo_report import budget
        from ceo_report.budget_render import render_budget
        from ceo_report.data import load
        tmp = tempfile.mkdtemp()
        try:
            inp = os.path.join(tmp, "입력")
            shutil.copytree(os.path.join(ROOT, "입력양식", "샘플"), inp)
            d = load(inp)
            B = budget.compute(d, budget.read_values(inp), 2027, D(2026, 11, 6), d.settings)
            self.assertEqual(B["cash"]["days_used"], 60)
            self.assertEqual(B["cash"]["days_used"], budget.COLLECT_DAYS)
            html = render_budget(B, mode="mgmt")
            self.assertIn("작성일 뒤 60일, 가용자금과 같은 기준", html)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ───────────── 계산-05 (결정 g): 자금계획서에 없는 매달 같은 고정 지출도 꼭 나갈 정기 지출 ─────────────
def bank_slip(day, no, lines):
    """통장 출금 전표: lines = [(계정코드, 계정, 거래처코드, 거래처, 차변, 적요)] + 보통예금 대변."""
    out = [{"date": day, "no": str(no), "account_code": a, "account": n, "vendor_code": vc, "vendor": v,
            "debit": amt, "credit": None, "memo": memo} for a, n, vc, v, amt, memo in lines]
    out.append({"date": day, "no": str(no), "account_code": "10300", "account": "보통예금", "vendor_code": "", "vendor": "",
                "debit": None, "credit": sum(x[4] for x in lines), "memo": ""})
    return out


class TestCalc05FixedCosts(unittest.TestCase):
    def journal(self):
        J, no = [], 0
        for m, (prin, intr) in zip((8, 9, 10), ((1200000, 334390), (1210000, 324390), (1220000, 314390))):
            no += 1   # 할부: 원금 + 이자 합계가 매달 같음
            J += bank_slip(D(2026, m, 21), no, [("29300", "장기차입금", "00679", "캐피탈", prin, ""), ("93100", "이자비용", "00679", "캐피탈", intr, "")])
        for m, d, a in ((9, 11, 895068), (10, 11, 867945), (11, 11, 924904)):
            no += 1   # 대출 이자: 조금씩 다름 (±15% 안)
            J += bank_slip(D(2026, m, d), no, [("93100", "이자비용", "1107", "대출_보증기금", a, "")])
        for m, d in ((8, 25), (9, 28), (10, 26)):
            no += 1   # 공제부금 (정기예금 계정이지만 '공제')
            J += bank_slip(D(2026, m, d), no, [("10500", "정기예.적금", "257", "공제부금", 300000, "공제부금 불입")])
            no += 1   # 정기예금 가입 (공제·적금 아님) → 보지 않음 (deposits 가 다룸)
            J += bank_slip(D(2026, m, d), no, [("10500", "정기예.적금", "900", "은행", 300000, "정기예금 가입")])
            no += 1   # 미지급금 지급 → 보지 않음 (계산서·자금계획서 쪽)
            J += bank_slip(D(2026, m, 4), no, [("25300", "미지급금", "371", "직원", 100000, "")])
        for m, a in ((8, 100000), (9, 300000), (10, 100000)):
            no += 1   # 금액이 들쭉날쭉 → 매달 같은 돈 아님
            J += bank_slip(D(2026, m, 10), no, [("81900", "임차료", "500", "창고", a, "")])
        for m in (6, 7, 8):
            no += 1   # 9월부터 안 나감 → 끝난 지출
            J += bank_slip(D(2026, m, 15), no, [("81900", "임차료", "501", "옛 창고", 500000, "")])
        for m in (8, 9, 10):
            no += 1   # 거래처코드 없음 → 이름으로 묶지 않음 (계산-01)
            J += bank_slip(D(2026, m, 15), no, [("83100", "지급수수료", "", "이름만", 50000, "")])
        return J

    def test_finds_monthly_fixed_costs_by_code(self):
        from ceo_report import tax
        rows = tax.fixed_costs(self.journal(), D(2026, 11, 15))
        self.assertEqual(sorted(set(r["거래처코드"] for r in rows)), ["1107", "257", "679"])
        first = {}
        for r in rows:
            first.setdefault(r["거래처코드"], r)
            self.assertEqual(r["세목"], tax.FIXED_KIND)
            self.assertEqual(r["상태"], "예상")
        self.assertEqual((first["679"]["납부예정일"], first["679"]["금액"]), ("2026-11-23", "1534390"))   # 21일이 토요일 → 월요일
        self.assertEqual((first["1107"]["납부예정일"], first["1107"]["금액"]), ("2026-12-11", "924904"))  # 11월분은 이미 나감
        self.assertEqual((first["257"]["납부예정일"], first["257"]["금액"]), ("2026-11-25", "300000"))   # 가장 이른 날 25일
        self.assertIn("결정 g", first["679"]["근거"])
        self.assertEqual(sum(1 for r in rows if r["거래처코드"] == "679"), 8)   # 11월 ~ 기준일 달 + 7달 (2027-06)

    def test_codes_of_other_rows_are_skipped(self):
        from ceo_report import tax
        rows = tax.fixed_costs(self.journal(), D(2026, 11, 15), skip_codes=["679"])
        self.assertNotIn("679", set(r["거래처코드"] for r in rows))

    def test_fixed_cost_is_a_must_pay_and_plan_row_with_same_code_wins(self):
        from ceo_report import calc, tax
        self.assertIn(tax.FIXED_KIND, calc.MUST_KINDS)
        t = {"kind": tax.FIXED_KIND, "period": "캐피탈 2026년 11월분", "due": D(2026, 11, 23), "amount": 1534390, "state": "예상",
             "basis": "", "codes": ("679",), "book": D(2026, 11, 14)}
        events, info = tax.merge([], [t], D(2026, 11, 15))
        self.assertEqual(len(events), 1)
        calc.mark_must(events, info)
        self.assertTrue(events[0]["must"])
        plan = {"date": D(2026, 11, 21), "io": "out", "amount": 1534390, "firm": True, "cat": "차입금 상환", "desc": "하나캐피탈",
                "vendor_code": "679", "source": "자금계획서"}
        events, info = tax.merge([plan], [t], D(2026, 11, 15))
        self.assertEqual(events, [plan])   # 자금계획서에 있으면 두 번 빼지 않음
        calc.mark_must(events, info)
        self.assertTrue(plan["must"])


# ───────────── 보고-05 (결정 M1): 대표 월간에는 '예산 대비' 표가 없고 경영관리용에만 ─────────────
class TestReport05BudgetTableMgmtOnly(unittest.TestCase):
    def test_budget_table_only_in_mgmt(self):
        import csv as _csv
        import shutil
        import tempfile
        from ceo_report import budget
        from ceo_report.calc import compute
        from ceo_report.data import load
        from ceo_report.render import render
        tmp = tempfile.mkdtemp()
        try:
            inp = os.path.join(tmp, "입력")
            shutil.copytree(os.path.join(ROOT, "입력양식", "샘플"), inp)
            with open(os.path.join(inp, budget.CONFIRM_FILE), "w", encoding="utf-8-sig", newline="") as f:
                w = _csv.writer(f)
                w.writerow(budget.CONFIRM_COLUMNS)
                for m in range(1, 13):
                    w.writerow([2026, m, "기획1팀", 70000000, 21000000, "", "", "", "", "", "2025-12-20"])
                    w.writerow([2026, m, budget.COMPANY, 70000000, 21000000, 2000000, 1000000, 0, 0, 0, "2025-12-20"])
            R = compute(load(inp), "monthly", D(2026, 10, 31))
            self.assertIsNotNone(R["budget_cmp"])
            self.assertNotIn("예산 대비", render(R, "ceo"))
            self.assertIn("예산 대비 (2025-12-20 확정 예산)", render(R, "mgmt"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ───────────── 보고-08 (결정 A8): 매년 연장 대출은 만기 60일 전 '연장 확인' 할 일 + 경영관리에 '안 되면 원금 상환' 한 줄 ─────────────
class TestReport08LoanExtension(unittest.TestCase):
    def make(self, new_due):
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        inp = os.path.join(tmp, "입력")
        shutil.copytree(os.path.join(ROOT, "입력양식", "샘플"), inp)
        with open(os.path.join(inp, "장부채무.csv"), "w", encoding="utf-8-sig", newline="") as f:
            f.write("구분,계정코드,계정과목,거래처코드,거래처,잔액,기준일,만기일,만기근거,전기이월\n"
                    "차입금,29300,장기차입금,00256,가상은행 보증대출,200000000,2026-10-31,2026-04-17,적요,\n"
                    "차입금,29300,장기차입금,00900,가상캐피탈,50000000,2026-10-31,2026-12-01,적요,\n")
        with open(os.path.join(inp, "대출만기.csv"), "w", encoding="utf-8-sig", newline="") as f:
            f.write("거래처코드,차입처,새만기일,매년연장,메모\n256,가상은행 보증대출,%s,예,가상 연장\n900,가상캐피탈,,,\n" % new_due)
        from ceo_report.calc import compute
        from ceo_report.data import load
        return compute(load(inp), "monthly", D(2026, 10, 31))

    def test_todo_within_60_days_only_for_yearly_loans(self):
        from ceo_report.render import render
        R = self.make("2026-12-20")   # 50일 남음
        mine = [r for r in R["risks"] if r["fact"].startswith("대출 ")]
        self.assertEqual(len(mine), 1)   # 매년 연장이 아닌 가상캐피탈(만기 31일 남음)은 넓히지 않음
        self.assertIn("가상은행 보증대출 만기 2026-12-20 (50일 남음)", mine[0]["fact"])
        self.assertIn("대출만기.csv", mine[0]["action"])
        mg, ceo = render(R, "mgmt"), render(R, "ceo")
        self.assertIn("연장이 안 되면 만기에 원금 200,000,000을 갚아야 함", mg)
        self.assertNotIn("연장이 안 되면", ceo)

    def test_no_todo_when_far_but_line_stays(self):
        from ceo_report.render import render
        R = self.make("2027-04-17")
        self.assertFalse([r for r in R["risks"] if r["fact"].startswith("대출 ")])
        self.assertIn("만기 2027-04-17, 매년 연장 예정, 만기일 직접 입력", render(R, "mgmt"))


# ───────────── 가정 표시: 최소 보유현금은 한 달 고정 지출 몇 달 치인지 예산 화면(경영관리용)에 (11/15 카드) ─────────────
class TestAssumptionMinCashMonths(unittest.TestCase):
    def test_budget_mgmt_shows_months_of_fixed_costs(self):
        import shutil
        import tempfile
        from ceo_report import budget
        from ceo_report.budget_render import render_budget
        from ceo_report.data import load
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        inp = os.path.join(tmp, "입력")
        shutil.copytree(os.path.join(ROOT, "입력양식", "샘플"), inp)
        d = load(inp)
        B = budget.compute(d, budget.read_values(inp), 2027, D(2026, 11, 6), d.settings)
        mg = render_budget(B, mode="mgmt")
        m = re.search(r"최소 보유현금 ([\d,]+) = 이 예산의 한 달 고정 지출\(급여·판관비, 감가상각 뺌\) ([\d,]+)의 ([\d.]+)달 치", mg)
        self.assertTrue(m, "줄 없음")
        mc, fixed, n = int(m.group(1).replace(",", "")), int(m.group(2).replace(",", "")), float(m.group(3))
        self.assertAlmostEqual(mc / float(fixed), n, places=1)
        self.assertIn("다시 정하세요", mg)
        self.assertNotIn("다시 정하세요", render_budget(B, mode="ceo"))


# ───────────── 계산-06 (N1): 장부의 마지막 통장 거래일이 기준일보다 7일 넘게 앞서면 대표·팀장 보고에 한 줄 ─────────────
class TestCalc06BankLag(unittest.TestCase):
    def test_last_bank_day_from_journal(self):
        from ceo_report import insights
        J = bank_slip(D(2026, 11, 3), 1, [("81900", "임차료", "500", "창고", 100000, "")]) + \
            [{"date": D(2026, 11, 12), "no": "2", "account_code": "41200", "account": "매출", "vendor_code": "", "vendor": "",
              "debit": None, "credit": 500000, "memo": ""}]   # 통장 아닌 줄은 보지 않음
        self.assertEqual(insights.last_bank_day(J, D(2026, 11, 15)), D(2026, 11, 3))
        self.assertEqual(insights.book_facts(J, D(2026, 11, 15), D(2026, 11, 15))["last_bank"], "2026-11-03")

    def test_note_only_when_more_than_7_days(self):
        from ceo_report import gate
        R = {"asof": D(2026, 11, 15), "auto_facts": {"last_bank": "2026-11-08"}}
        self.assertEqual(gate.bank_lag_note(R), "")
        R["auto_facts"]["last_bank"] = "2026-11-07"
        self.assertIn("마지막 통장 거래가 2026-11-07 (기준일보다 8일 전)", gate.bank_lag_note(R))
        self.assertEqual(gate.bank_lag_note({"asof": D(2026, 11, 15), "auto_facts": None}), "")

    def test_ceo_report_shows_the_line(self):
        from ceo_report.calc import compute
        from ceo_report.data import load
        from ceo_report.render import render
        R = compute(load(os.path.join(ROOT, "입력양식", "샘플")), "weekly", D(2026, 10, 31))
        R["auto_facts"] = {"last_bank": "2026-10-20"}
        for mode in ("ceo", "mgmt"):
            self.assertIn("마지막 통장 거래가 2026-10-20 (기준일보다 11일 전)", render(R, mode))


# ───────────── 안전-08 (N3): 위하고가 알려 준 전표 수와 받은 전표 수가 다르면 막음 ─────────────
class TestSafety08SlipCount(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def doc(self):
        from test_journal_json import auto_json
        return auto_json()

    def write(self, name, doc):
        from test_journal_json import write_json
        write_json(self.tmp, name, doc)
        return os.path.join(self.tmp, name)

    def test_matching_counts_read(self):
        from ceo_report import wehago
        rows = wehago.read_journal_json(self.write("261105 분개장 자동수집.json", self.doc()))
        self.assertGreater(len(rows), 1)

    def test_fewer_slips_than_wehago_said_is_refused(self):
        from ceo_report import wehago
        d = self.doc()
        d["전표수"] += 1
        with self.assertRaises(wehago.WehagoError) as e:
            wehago.read_journal_json(self.write("261105 분개장 자동수집.json", d))
        self.assertIn("위하고가 알려 준 전표는", str(e.exception))
        d = self.doc()
        d["줄"] = d["줄"][:-1]   # 줄 수가 적힌 것보다 적음
        with self.assertRaises(wehago.WehagoError):
            wehago.read_journal_json(self.write("261105 분개장 자동수집.json", d))

    def test_newest_partial_file_blocks_instead_of_using_older(self):
        from ceo_report import wehago
        self.write("261101 분개장 자동수집.json", self.doc())
        d = self.doc()
        d["전표수"] += 3
        self.write("261105 분개장 자동수집.json", d)
        B = wehago.load_books(self.tmp, D(2026, 11, 5), None)
        self.assertEqual(B.state, "읽기 실패")
        self.assertIn("261105 분개장 자동수집.json", B.reason)


# ───────────── 안전-01 (결정 f·P5-4·P5-5·P5-3): 이체 파일은 대표 보고와 같은 자료 확인을 통과해야 ─────────────
class TestSafety01TransferGate(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile
        from unittest import mock
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.inp = os.path.join(self.tmp, "입력")
        self.out = os.path.join(self.tmp, "출력")
        self.col = os.path.join(self.tmp, "수집", "위하고")
        os.makedirs(self.col)
        shutil.copytree(os.path.join(ROOT, "입력양식", "샘플"), self.inp)
        with open(os.path.join(self.inp, "거래처계좌.csv"), "w", encoding="utf-8-sig") as f:
            f.write("거래처,은행,계좌번호,예금주\n디자인스튜디오,우리은행,1002-000-000003,가상디자인\n")
        self.conv(dt.datetime.now())
        env = dict(os.environ)
        env.pop("CEO_REPORT_TEST_GATE_OFF", None)
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def conv(self, when, failed=False):
        with open(os.path.join(self.inp, "변환결과.txt"), "w", encoding="utf-8-sig") as f:
            f.write("변환 시각 %s · 기준일 2026-10-31\n%s\n" % (when.strftime("%Y-%m-%d %H:%M:%S"),
                                                         "변환 실패 — 가상" if failed else "WEHAGO 장부: ok"))

    def make(self, gate_off=True, **kw):
        from unittest import mock
        from ceo_report import transfer
        lines, result = [], {}
        env = {"CEO_REPORT_TEST_GATE_OFF": "1"} if gate_off else {}
        with mock.patch.dict(os.environ, env):
            path = transfer.make_file(self.inp, self.out, D(2026, 11, 1), D(2026, 11, 30), lines.append, asof=D(2026, 10, 31),
                                      collect_dir=self.col, result=result, **kw)
        return path, lines, result

    def test_blocked_when_ceo_report_would_be_blocked_and_override_is_logged(self):
        from ceo_report import transfer
        os.makedirs(self.out)
        old = os.path.join(self.out, "신한대량이체_1101_1130.xlsx")   # 예전 이름의 같은 기간 파일
        open(old, "w").close()
        path, lines, result = self.make(gate_off=False)   # 샘플엔 자금계획서가 없음 → 대표 보고가 막히는 자료
        self.assertIsNone(path)
        self.assertTrue(any("자금계획서" in p for p in result["blocked"]))
        self.assertFalse(os.path.exists(old))   # 막히면 같은 기간 옛 파일을 치움 (지우지 않고 옮김)
        self.assertTrue(os.path.exists(os.path.join(self.out, transfer.OLD_DIR, "신한대량이체_1101_1130.xlsx")))
        path, lines, result = self.make(gate_off=False, override="가상 급한 지급", now=dt.datetime(2026, 10, 31, 9, 30, 5))
        self.assertTrue(path and path.endswith("신한대량이체_20261101_20261130_093005.xlsx"), lines)   # 연도·시각
        log = transfer.read_log(self.inp)
        self.assertEqual(log[0]["푼이유"], "가상 급한 지급")
        self.assertTrue(log[0]["자료확인"].startswith("막힘: "))

    def test_newer_collected_file_or_failed_conversion_blocks(self):
        self.conv(dt.datetime.now() - dt.timedelta(hours=2))
        open(os.path.join(self.col, "261031 분개장 자동수집.json"), "w").close()   # 변환 뒤에 받은 분개장
        path, lines, result = self.make()
        self.assertIsNone(path)
        self.assertTrue(any("뒤에 새로 받은 파일" in p for p in result["blocked"]))
        os.remove(os.path.join(self.col, "261031 분개장 자동수집.json"))
        self.conv(dt.datetime.now(), failed=True)
        path, lines, result = self.make()
        self.assertIsNone(path)
        self.assertTrue(any("변환이 실패" in p for p in result["blocked"]))

    def test_zero_rows_puts_old_file_away_and_repeat_warns(self):
        from ceo_report import transfer
        p1, lines, _ = self.make(now=dt.datetime(2026, 10, 31, 9, 0, 0))
        self.assertTrue(p1)
        p2, lines, _ = self.make(now=dt.datetime(2026, 10, 31, 10, 0, 0))   # 같은 지급을 다시 담음
        self.assertTrue(any("같은 계좌·금액이 이미 있습니다" in ln for ln in lines))
        self.assertFalse(os.path.exists(p1))   # 같은 기간 예전 파일은 지난이체파일 로
        self.assertEqual(transfer._period_files(self.out, D(2026, 11, 1), D(2026, 11, 30)), [os.path.basename(p2)])
        os.remove(os.path.join(self.inp, "거래처계좌.csv"))
        with open(os.path.join(self.inp, "거래처계좌.csv"), "w", encoding="utf-8-sig") as f:
            f.write("거래처,은행,계좌번호,예금주\n")
        p3, lines, _ = self.make(now=dt.datetime(2026, 10, 31, 11, 0, 0))
        self.assertIsNone(p3)
        self.assertEqual(transfer._period_files(self.out, D(2026, 11, 1), D(2026, 11, 30)), [])   # 0건이면 옛 파일도 치움

    def test_code_payment_never_uses_name_only_account(self):
        from ceo_report import transfer
        accounts = {transfer.vendor_key("가상업체"): {"거래처코드": "", "거래처": "가상업체", "은행": "우리은행", "계좌번호": "1", "예금주": "가"}}
        acc, why = transfer.find_account(accounts, {"vendor": "가상업체", "code": "00123"})
        self.assertIsNone(acc)
        self.assertIn("코드 없는", why)
        acc, why = transfer.find_account(accounts, {"vendor": "가상업체", "code": ""})
        self.assertIsNotNone(acc)   # 코드 없는 손 일정은 이름이 한 곳과 맞을 때만 (예전 그대로)

    def test_exe_ignores_test_switch(self):
        import sys as _sys
        from unittest import mock
        from ceo_report import gate
        with mock.patch.dict(os.environ, {"CEO_REPORT_TEST_GATE_OFF": "1"}):
            self.assertTrue(gate._test_off())
            with mock.patch.object(_sys, "frozen", True, create=True):
                self.assertFalse(gate._test_off())


# ───────────── P2-12: 엑셀에서 CP949 로 저장한 자금일정 지난기록도 읽고, 머리줄이 달라도 칸이 밀리지 않게 ─────────────
class TestSafetyArchiveEncoding(unittest.TestCase):
    HEAD = ["예정일", "입출금", "금액", "확정여부", "분류", "프로젝트번호", "거래처", "근거", "비고"]

    def setUp(self):
        import shutil
        import tempfile
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def write(self, name, head, rows, enc="utf-8-sig"):
        import csv
        with open(os.path.join(self.dir, name), "w", encoding=enc, newline="") as f:
            w = csv.writer(f)
            w.writerow(head)
            w.writerows(rows)

    def read(self, name):
        import csv
        with open(os.path.join(self.dir, name), encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))

    def bank(self, no, amount, vendor):
        return [{"date": D(2026, 11, 7), "no": no, "account_code": "10300", "debit": None, "credit": amount,
                 "vendor": vendor, "vendor_norm": vendor, "type": "일반"}]

    def test_cp949_archive_still_blocks_reusing_a_bank_line(self):
        from ceo_report import review_checks as RC
        # 지난번에 전표 1(50만)을 '가상' 일정에 이미 썼다 — 사용자가 엑셀로 열어 CP949 로 저장
        self.write(RC.ARCHIVE, self.HEAD + ["정리일", "정리 근거"],
                   [["2026-11-06", "출금", "500000", "확정", "급한 지급", "", "가상", "첫 지급", "", "2026-11-08",
                     "분개장 2026-11-07 전표 1 보통예금 출금과 맞음"]], enc="cp949")
        self.write(RC.SCHEDULE, self.HEAD, [["2026-11-07", "출금", "500000", "확정", "급한 지급", "", "가상", "아직 안 나감", ""]])
        out = RC.archive_paid_schedule(self.dir, self.bank("1", 500000, "가상"), D(2026, 11, 10))
        self.assertIn("없음", out[0])   # 같은 통장 줄을 또 쓰지 않음 → 아직 안 나간 일정이 남는다
        self.assertEqual([r["근거"] for r in self.read(RC.SCHEDULE)], ["아직 안 나감"])

    def test_header_union_keeps_columns_aligned(self):
        from ceo_report import review_checks as RC
        self.write(RC.ARCHIVE, self.HEAD + ["정리일", "정리 근거"],
                   [["2026-10-01", "출금", "100000", "확정", "예정", "", "옛곳", "옛 줄", "", "2026-10-02",
                     "분개장 2026-10-01 전표 9 보통예금 출금과 맞음"]], enc="cp949")
        self.write(RC.SCHEDULE, self.HEAD + ["거래처코드"],
                   [["2026-11-07", "출금", "500000", "확정", "급한 지급", "", "가상", "새 줄", "", "00123"]])
        J = self.bank("1", 500000, "가상")
        J[0]["vendor_code"] = "123"
        out = RC.archive_paid_schedule(self.dir, J, D(2026, 11, 10))
        self.assertIn("1줄", out[0])
        arc = self.read(RC.ARCHIVE)   # 통째로 UTF-8 로 다시 씀 — 옛 줄 글자도 그대로
        self.assertEqual([(r["근거"], r["거래처코드"], r["정리 근거"][:14]) for r in arc],
                         [("옛 줄", "", "분개장 2026-10-01"), ("새 줄", "00123", "분개장 2026-11-07")])

    def test_unreadable_archive_changes_nothing(self):
        from ceo_report import review_checks as RC
        with open(os.path.join(self.dir, RC.ARCHIVE), "wb") as f:
            f.write(b"\xff\xfe\x00\xd8broken\x80\x81")
        self.write(RC.SCHEDULE, self.HEAD, [["2026-11-07", "출금", "500000", "확정", "급한 지급", "", "가상", "그대로", ""]])
        with open(os.path.join(self.dir, RC.SCHEDULE), "rb") as f:
            before = f.read()
        out = RC.archive_paid_schedule(self.dir, self.bank("1", 500000, "가상"), D(2026, 11, 10))
        self.assertIn("읽지 못해 그대로 둠", out[0])
        with open(os.path.join(self.dir, RC.SCHEDULE), "rb") as f:
            self.assertEqual(f.read(), before)


# ───────────── P2-10: 수동 프로젝트 연결은 다시 받은 장부에서 다른 줄에 붙지 않음 ─────────────
class TestLinkFollowsTheSameLine(unittest.TestCase):
    def J(self, *lines):
        return [{"date": D(2026, 10, 20), "no": "7", "vendor_code": c, "debit": a, "credit": None} for c, a in lines]

    def links(self, rows):
        import csv
        import shutil
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with open(os.path.join(d, linking.LINK_FILE), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(linking.LINK_TEMPLATE)
            w.writerows(rows)
        return linking.read_links(d)

    def test_same_line_is_kept(self):
        ov, notes = self.links([["2026-10-20", "7", "2", "00200", "300000", "26201"]])
        out, more = linking.check_links(self.J(("00100", 500000), ("00200", 300000)), ov)
        self.assertEqual((dict(out), more, notes), ({("2026-10-20", "7", 2): "26201"}, [], []))

    def test_reordered_slip_moves_to_the_one_matching_line(self):
        ov, _ = self.links([["2026-10-20", "7", "2", "00200", "300000", "26201"]])
        # 다시 받은 장부: 같은 전표 안 줄 순서가 바뀜 (예전 2번째 줄 = 지금 1번째 줄)
        out, more = linking.check_links(self.J(("00200", 300000), ("00100", 500000)), ov)
        self.assertEqual(dict(out), {("2026-10-20", "7", 1): "26201"})
        self.assertIn("1번째로 옮겨져", more[0])

    def test_other_vendor_on_that_line_is_not_linked(self):
        ov, _ = self.links([["2026-10-20", "7", "2", "00200", "300000", "26201"]])
        out, more = linking.check_links(self.J(("00100", 500000), ("00300", 300000)), ov)
        self.assertEqual(dict(out), {})   # 업체 B 원가가 그 프로젝트로 들어가지 않는다
        self.assertIn("연결하지 않음", more[0])

    def test_rows_without_check_columns_work_as_before_with_a_hint(self):
        ov, notes = self.links([["2026-10-20", "7", "2", "", "", "26201"]])
        out, more = linking.check_links(self.J(("00100", 500000), ("00300", 300000)), ov)
        self.assertEqual((dict(out), more, notes, out.unchecked), ({("2026-10-20", "7", 2): "26201"}, [], [], 1))


# ───────────── P3-3: 자금계획서가 없는 날까지 가수금 상환을 '안전'으로 보지 않음 ─────────────
class TestSuspenseRepayOnlyWithinPlan(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile
        from unittest import mock
        self.t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.t, True)
        with open(os.path.join(self.t, "계정잔액.csv"), "w", encoding="utf-8-sig") as f:
            f.write("연월,계정코드,계정,차변,대변\n처음부터,,예,,\n2025-02,25700,가수금,0,40000000\n")
        for target, value in (("ceo_report.gate.problems", []), ("ceo_report.gate.sources_line", "사용한 자료: 시험")):
            p = mock.patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def R(self, received, events):
        return {"asof": D(2026, 11, 13), "fundplan": {"received": received},
                "s2": {"start": 300000000, "min_cash": 100000000, "horizon": D(2027, 5, 31),
                       "dated": [{"date": d, "io": "out", "amount": a, "firm": True, "source": "자금계획서", "desc": "가", "cat": "자금계획서"}
                                 for d, a in events]}}

    def test_short_plan_is_not_judged(self):
        from ceo_report import gasu
        G = gasu.compute(self.t, self.R(["2026-11", "2026-12"], [(D(2026, 12, 10), 1000000)]))
        self.assertFalse(G["ok"])
        self.assertIn("2026-12-31까지만", G["why"])

    def test_end_is_the_plan_end_not_stretched(self):
        from ceo_report import gasu
        # 계획 줄은 12월까지지만 2027-02 까지 받은 달(줄 없는 달) → 2월 말까지 보고 판단
        G = gasu.compute(self.t, self.R(["2026-11", "2026-12", "2027-01", "2027-02"], [(D(2026, 12, 10), 1000000)]))
        self.assertTrue(G["ok"])
        self.assertEqual(G["end"], D(2027, 2, 28))


# ───────────── P5-22: 못 읽은 지급 요청서·출금 상세를 0건으로 쓰거나 덮지 않음 ─────────────
class TestPayDetailUnreadable(unittest.TestCase):
    def test_conversion_keeps_old_details_when_snapshot_file_is_unreadable(self):
        import test_convert
        from test_books_stability_1114 import _company, _run
        from ceo_report import payreq
        test_convert.setUpModule()   # 샘플을 임시 폴더에 새로 쓴다
        input_dir, collect, wehago_dir = _company(self)
        snap = max((os.path.join(collect, n) for n in os.listdir(collect)), key=os.path.getmtime)
        payreq.write(snap, [{"key": "k1", "project": "26201", "vendor": "가상", "amount": 1100000, "note": "가상 세부"}])
        self.assertEqual(_run(input_dir, collect, wehago_dir).code, 0)
        with open(os.path.join(input_dir, payreq.FILE), "rb") as f:
            before = f.read()
        self.assertIn("가상 세부".encode("utf-8"), before)
        with open(os.path.join(snap, payreq.FILE), "wb") as f:
            f.write(b"\xff\xfe\x00broken")   # 못 읽는 파일
        res = _run(input_dir, collect, wehago_dir)
        with open(os.path.join(input_dir, payreq.FILE), "rb") as f:
            self.assertEqual(f.read(), before)   # 0건으로 덮지 않음
        self.assertTrue([ln for ln in res.lines if "지급 요청서" in ln and "읽지 못함" in ln], res.lines)

    def test_cp949_files_are_read_and_save_refuses_unreadable(self):
        import shutil
        import tempfile
        from ceo_report import data, paydetail, payreq
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with open(os.path.join(d, payreq.FILE), "w", encoding="cp949", newline="") as f:
            f.write("키,프로젝트,업체명,금액,세부사항\r\nk1,26201,가상,1100000,엑셀 저장\r\n")
        rows, why = payreq.read_checked(d)
        self.assertEqual((rows[0]["note"], why), ("엑셀 저장", None))
        with open(os.path.join(d, paydetail.DETAIL_FILE), "wb") as f:
            f.write(b"\xff\xfe\x00broken")
        with self.assertRaises(ValueError):
            paydetail.save(d, "가상", "1000", "새 상세")
        with open(os.path.join(d, paydetail.DETAIL_FILE), "rb") as f:
            self.assertEqual(f.read(), b"\xff\xfe\x00broken")   # 덮지 않음
        hit = [m for f, _, m in data.load(d).issues.items if f == paydetail.DETAIL_FILE]
        self.assertTrue(hit and "읽지 못해" in hit[0])


# ───────────── C5: 엑셀에서 CP949 로 다시 저장한 입력 파일도 읽고, 못 읽으면 새 줄만으로 덮지 않음 ─────────────
class TestSafetyCp949Inputs(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def put(self, name, text, enc="cp949"):
        with open(os.path.join(self.d, name), "wb") as f:
            f.write(text.encode(enc) if isinstance(text, str) else text)

    def test_cp949_files_keep_their_rows_when_saving(self):
        from ceo_report import checklist, targets
        self.put(targets.TARGET_FILE, "연도,팀,매출목표,목표수익률\r\n2026,기획1팀,1000000000,30\r\n")
        targets.save(self.d, "2026", "기획3팀", "500,000,000", "20")
        self.assertEqual(sorted(t for _, t in targets.read(self.d)), ["기획1팀", "기획3팀"])
        self.put(checklist.STORE, ",".join(checklist.STORE_COLS) + "\r\nA1,확인함,메모,2026-11-10,내용\r\n")
        checklist.save_decision(self.d, "A2", "확인함", "새 메모", "내용2")
        self.assertEqual(sorted(checklist.read_decisions(self.d)), ["A1", "A2"])
        self.put(checklist.BANK_FILE, ",".join(checklist.BANK_COLS) + "\r\n2026-11-01,100,가\r\n")
        checklist.save_bank(self.d, "2026-11-15", "300")
        self.assertEqual(len(checklist.read_bank(self.d)), 2)

    def test_unreadable_file_is_not_overwritten(self):
        from ceo_report import targets
        self.put(targets.TARGET_FILE, b"\xff\xfe\x00\xd8broken\x80")
        with self.assertRaises(ValueError) as cm:
            targets.save(self.d, "2026", "기획3팀", "500,000,000", "20")
        self.assertIn("그대로 둠", str(cm.exception))
        with open(os.path.join(self.d, targets.TARGET_FILE), "rb") as f:
            self.assertEqual(f.read(), b"\xff\xfe\x00\xd8broken\x80")


# ───────────── P1-3: 같은 날 다른 해·기간 분개장을 받아도 앞 원본을 덮지 않음 (확장 파일 이름에 기간) ─────────────
class TestJournalNamesKeepPeriods(unittest.TestCase):
    def test_extension_names_by_period_and_program_ranks_them(self):
        from ceo_report import wehago as W
        with open(os.path.join(ROOT, "chrome_extension", "background.js"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("periodTag(msg.kind, msg.params)", src)
        self.assertIn("_기간${s}-${e}", src)
        # 확장이 만드는 이름 (올해 전체 · 지난해 전체 · 지난해 일부 · 올해 일부) — 모두 분개장으로 읽고 받은 날이 맞아야 함
        want = {"261115 분개장 자동수집.json": D(2026, 11, 15),
                "261115 분개장_2025 자동수집.json": D(2025, 12, 31),
                "261115 분개장_2025_기간20251201-20251231 자동수집.json": D(2025, 12, 31),
                "261115 분개장_기간20261101-20261115 자동수집.json": D(2026, 11, 15)}
        for name, rank in want.items():
            self.assertEqual((W._kind_of(name), W._rank_date(name)), (("분개장", True), rank), name)


# ───────────── P2-13: 머리글이 두 번 있으면 뒤 칸이 앞 칸을 말없이 덮지 않음 ─────────────
class TestDuplicateHeaders(unittest.TestCase):
    def read(self, text, required):
        import shutil
        import tempfile
        from ceo_report import util
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "자금일정.csv")
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            f.write(text)
        iss, info = util.Issues(), {}
        rows, ok = util.read_csv(p, required, iss, info)
        return rows, ok, [m for _, _, m in iss.items]

    def test_required_column_twice_refuses_the_file(self):
        rows, ok, notes = self.read("예정일,금액,금액\r\n2026-11-20,1000000,100000\r\n", ["예정일", "금액"])
        self.assertEqual((rows, ok), ([], False))
        self.assertIn("머리글이 두 번 있음: 금액", notes[0])

    def test_other_column_twice_uses_the_first(self):
        rows, ok, notes = self.read("예정일,금액,비고,비고\r\n2026-11-20,1000000,앞,뒤\r\n", ["예정일", "금액"])
        self.assertTrue(ok)
        self.assertEqual(rows[0]["비고"], "앞")
        self.assertIn("앞 칸 값을 씀", notes[0])


# ───────────── C6: 변환이 도는 중(잠금)에는 보고를 만들지 않음 · 창은 작업이 끝난 뒤 닫힘 ─────────────
class TestNoReportDuringConversion(unittest.TestCase):
    def test_report_refused_while_lock_is_fresh(self):
        import shutil
        import tempfile
        import time
        from ceo_report import app, convert
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        P = app.Paths(tmp)
        os.makedirs(P.input, exist_ok=True)
        lock = os.path.join(P.input, convert.LOCK_FILE)
        with open(lock, "w") as f:
            f.write("1 2026-11-15")
        said = []
        rc, files = app.run_task("주간", P, said.append, asof="2026-11-13")
        self.assertEqual((rc, files), (7, []))
        self.assertIn("자료 변환이 아직 끝나지 않았습니다", said[0])
        old = time.time() - convert.LOCK_STALE_SECONDS - 60   # 15분 지난 잠금은 끊긴 것으로 보고 막지 않음
        os.utime(lock, (old, old))
        self.assertIsNone(convert.lock_age(P.input))

    def test_window_close_waits_for_work(self):
        src = _read(os.path.join(ROOT, "ceo_report", "gui.py"))
        body = src[src.index("    def close(self):"):src.index("    def ask_splits(self, multi):")]
        self.assertLess(body.index("if self.busy:"), body.index("self.root.destroy()"))
        self.assertIn("close_when_done", src[src.index("    def set_busy("):src.index("    def report(self, kind):")])


# ───────────── P3-2: 오래전에 받은 '빈 달'을 지금 받은 달로 보지 않음 ─────────────
class TestStaleEmptyPlanMonth(unittest.TestCase):
    def test_old_empty_month_is_still_a_gap(self):
        import shutil
        import tempfile
        from ceo_report import gate
        from ceo_report.calc import compute
        from ceo_report.data import load
        sample = os.path.join(ROOT, "입력양식", "샘플")
        with tempfile.TemporaryDirectory() as t:
            shutil.copytree(sample, t, dirs_exist_ok=True)
            with open(os.path.join(t, "자금계획.csv"), "w", encoding="utf-8-sig") as f:
                f.write("예정일,입출금,분류,거래처,거래처코드,금액,대상월,자료일,파일,상태,근거,원전표,프로젝트\n"
                        "2026-11-20,지급,미지급금 지급,가상상사,000001,990000,2026-11,2026-10-30,a.json,예정,,,\n")
            with open(os.path.join(t, "자금계획받은달.csv"), "w", encoding="utf-8-sig") as f:
                # 12월은 10월 1일에 받은 옛 파일에서만 (줄 없음) — 지금 자료가 아님
                f.write("대상월,자료일,파일\n2026-11,2026-10-30,a.json\n2026-12,2026-10-01,old.json\n")
            d = load(t)
            self.assertEqual(d.fundplan_received_at["2026-12"], D(2026, 10, 1))
            R = compute(d, "weekly", D(2026, 10, 31))
            self.assertEqual(R["fundplan"]["received"], ["2026-11"])
            R["fundplan"]["used"] = True
            R["s2"]["periods"] = [{"label": "12월", "end": D(2026, 12, 31), "firm": {"avail": 1}, "all": {"avail": 1}}]
            self.assertIn("2026-12", gate.blank_plan_gaps(R))


# ───────────── P3-8: 서로 반대인 대조 차이가 더해져 대표 경고가 사라지지 않음 ─────────────
class TestReconWarningsDoNotCancel(unittest.TestCase):
    def write(self, rows):
        import csv
        import shutil
        import tempfile
        from ceo_report import reconcile
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with open(os.path.join(d, reconcile.FILE), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["구분", "항목", "비교자료", "비교값", "장부값", "차이", "기준", "판정", "할일", "대표경고"])
            w.writerows(rows)
        return reconcile.for_report(d)[0]

    def test_opposite_differences_from_two_sources_keep_the_warning(self):
        warn = self.write([["잔액", "보통예금", "합계잔액시산표", "0", "20000000", "20000000", "", "다름", "", "예"],
                           ["잔액", "보통예금", "재무상태표 2026", "40000000", "20000000", "-20000000", "", "다름", "", "예"]])
        self.assertEqual([(w["what"], abs(w["diff"])) for w in warn], [("통장", 20000000)])

    def test_parts_of_one_item_in_one_source_still_add_up(self):
        warn = self.write([["잔액", "단기차입금", "합계잔액시산표", "0", "15000000", "15000000", "", "다름", "", "예"],
                           ["잔액", "장기차입금", "합계잔액시산표", "15000000", "0", "-15000000", "", "다름", "", "예"]])
        self.assertEqual([(w["what"], w["diff"]) for w in warn], [("차입금", 0)])   # 차입금 합계는 같음


# ───────────── P1-4: 조건·오류 응답만 받은 위하고 화면 파일은 쓰지 않고 그 전 파일을 씀 ─────────────
class TestRawFilesNeedTheDataResponse(unittest.TestCase):
    def setUp(self):
        import shutil
        import tempfile
        self.t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.t, True)

    def put(self, name, when, responses):
        import json
        d = {"종류": "결산원본", "화면": "재무상태표", "화면코드": "SACL0105", "연도": 2026, "수집시각": when,
             "응답": [{"path": p, "data": x} for p, x in responses]}
        with open(os.path.join(self.t, name), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

    def test_condition_or_error_only_file_is_skipped(self):
        from ceo_report import reconcile, wehago_raw
        good = {"error_str": "", "error_view": "", "main": [{"cd_acctit": "10300", "mn_bungae_left": "100"}]}   # 실제: 정상에도 error_str 칸
        self.put("261113 결산_재무상태표 자동수집.json", "2026-11-13 10:00:00",
                 [("/smarta/sacl0105/check_unapproved_slip/", {"data_count": 0}), ("/smarta/sacl0105/main/", good)])
        self.put("261115 결산_재무상태표 자동수집.json", "2026-11-15 10:00:00",
                 [("/smarta/sacl0105/check_unapproved_slip/", {"data_count": 0})])            # 조건 응답만
        self.put("261116 결산_재무상태표 자동수집.json", "2026-11-16 10:00:00",
                 [("/smarta/sacl0105/main/", {"status": 500, "error": "Internal Server Error"})])   # 오류 응답만
        skipped = []
        raw = reconcile.raw_files(self.t, skipped)
        self.assertEqual([w.day for w, _, _ in raw["SACL0105"]], [13])   # 그 전에 받은 정상 파일
        self.assertEqual(sorted(skipped), ["261115 결산_재무상태표 자동수집.json", "261116 결산_재무상태표 자동수집.json"])
        F = wehago_raw.files(self.t)
        self.assertTrue(F[("결산_재무상태표", 2026)][1].endswith("261113 결산_재무상태표 자동수집.json"))

    def test_extension_counts_only_the_data_response_as_success(self):
        import json
        from ceo_report.wehago_raw import NEED
        src = _read(os.path.join(ROOT, "chrome_extension", "background.js"))
        self.assertEqual(src.count("hasData(sc, r.got)"), 2)   # 결산·인사급여 모두 받기, 대조 화면
        self.assertIn("hasData({code: ack.code}, run.got)", src)   # 지금 열린 화면 받기
        js = json.loads(re.search(r"const NEED = (\{.*?\});", src).group(1))
        self.assertEqual(js, NEED)   # 확장과 프로그램이 같은 자료 응답을 본다


class TestOtherCompanyTabs(unittest.TestCase):
    """P1-1·P2-4: 여러 회사 SmartA 탭 — 확장은 보고 있는 탭을 쓰고, 프로그램은 다른 회사 장부·자금계획서를 섞거나 보고하지 않는다."""

    def setUp(self):
        import shutil
        import tempfile
        self.t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.t, True)

    def journal(self, name, company, start, end, rows):
        from test_journal_json import COLS, write_json
        doc = {"종류": "분개장", "형식": 1, "회사": company, "기간": {"start_date": start, "end_date": end, "gisu": "2"},
               "열": COLS, "줄": rows}
        write_json(self.t, name, doc)

    def row(self, day, no, code, acct, dr, cr, sq):
        return [day, no, "매입전표", "차변" if dr else "대변", code, acct, dr, cr, "가상", "00001", "메모", "", "", "",
                "2026-11-13T10:00:00.000", sq]

    def test_company_names_compare_loosely(self):
        from ceo_report.wehago import same_company
        self.assertTrue(same_company("주식회사 가나상사", "(주)가나상사"))
        self.assertTrue(same_company("주식회사 가나상사", "가나상사"))
        self.assertTrue(same_company("", "다라상사"))   # 모르면 막지 않음
        self.assertFalse(same_company("주식회사 가나상사", "주식회사 다라상사"))

    def test_other_company_prior_year_is_not_mixed_in(self):
        from ceo_report import wehago
        self.journal("261113 분개장 자동수집.json", "주식회사 가나상사", "20260101", "20261113",
                     [self.row("20261010", "00001", "81300", "접대비(판)", 100, 0, 1),
                      self.row("20261010", "00001", "25300", "미지급금", 0, 100, 2)])
        self.journal("261103 분개장_2025.json", "주식회사 다라상사", "20250101", "20251231",
                     [self.row("20250510", "00001", "81300", "접대비(판)", 900, 0, 1),
                      self.row("20250510", "00001", "25300", "미지급금", 0, 900, 2)])
        b = wehago.load_books(self.t, dt.date(2026, 11, 13), None)
        self.assertEqual(b.company, "주식회사 가나상사")
        self.assertEqual(sorted(set(r["date"].year for r in b.journal)), [2026])   # 다른 회사 2025 장부는 쓰지 않음
        self.assertEqual(b.files["분개장"]["prior"], [])
        self.assertTrue(any("다른 회사(주식회사 다라상사)" in n and n.startswith("[확인]") for n in b.notes), b.notes)
        self.assertNotIn("261103 분개장_2025.json", wehago.journal_layers(self.t, ["261103 분개장_2025.json", "261113 분개장 자동수집.json"]))

    def test_same_company_prior_year_still_used(self):
        from ceo_report import wehago
        self.journal("261113 분개장 자동수집.json", "주식회사 가나상사", "20260101", "20261113",
                     [self.row("20261010", "00001", "81300", "접대비(판)", 100, 0, 1),
                      self.row("20261010", "00001", "25300", "미지급금", 0, 100, 2)])
        self.journal("261103 분개장_2025.json", "(주)가나상사", "20250101", "20251231",
                     [self.row("20250510", "00001", "81300", "접대비(판)", 900, 0, 1),
                      self.row("20250510", "00001", "25300", "미지급금", 0, 900, 2)])
        b = wehago.load_books(self.t, dt.date(2026, 11, 13), None)
        self.assertEqual(sorted(set(r["date"].year for r in b.journal)), [2025, 2026])

    def test_gate_blocks_other_company(self):
        from ceo_report import gate
        R = {"settings": {"회사명": "주식회사 가나상사"}, "auto_facts": {"book_company": "주식회사 다라상사", "plan_companies": []}}
        self.assertEqual(len(gate.company_problems(R)), 1)
        self.assertIn("분개장이 다른 회사(주식회사 다라상사)", gate.company_problems(R)[0])
        R["auto_facts"] = {"book_company": "주식회사 가나상사", "plan_companies": ["주식회사 다라상사"]}
        self.assertIn("자금계획서가 다른 회사(주식회사 다라상사)", gate.company_problems(R)[0])
        R["auto_facts"] = {"book_company": "가나상사", "plan_companies": ["(주)가나상사"]}
        self.assertEqual(gate.company_problems(R), [])
        R = {"settings": {"회사명": "회사명"}, "auto_facts": {"book_company": "주식회사 다라상사"}}   # 설정 기본값: 이름 모름
        self.assertEqual(gate.company_problems(R), [])

    def test_extension_prefers_the_tab_being_viewed(self):
        with open(os.path.join(ROOT, "chrome_extension", "background.js"), encoding="utf-8") as f:
            src = f.read()
        body = re.search(r"async function findSmartaTab\(\) \{.*?\n\}", src, re.S).group(0)
        self.assertIn("active: true, lastFocusedWindow: true", body)   # 지금 보고 있는 탭 먼저
        self.assertIn("여러 회사", body)                                 # 회사가 섞여 있으면 받지 않음
        self.assertNotIn("tabs.find((t) => /[?&]cno=/.test(t.url)) || null", src)


class TestOneSlipSeveralLinesOneVendor(unittest.TestCase):
    """1차 자금-4: 한 전표에 같은 거래처 채무 줄이 여럿(계산서 여러 장을 한 번에 지급)이고 자금계획서는 합계 한 줄이면
    '예정일 지남'으로 남아 다음 금요일 출금 목록에 다시 올라갔다 (실제 장부에 이런 전표 12개)."""

    def settle(self, rows, lines):
        from test_review_1114b import _books
        from ceo_report import fundplan
        fundplan.settle(rows, _books(lines), dt.date(2026, 11, 12))
        return rows

    def test_two_payable_lines_one_plan_line(self):
        from test_fundplan import plan_row
        D = dt.date
        for bank_vendor in ("가상음향", "신한은행"):
            rows = self.settle([plan_row("2026-11-10", "지급", "가상음향", 15000000), plan_row("2026-11-20", "지급", "가상음향", 15000000)],
                               [("8", D(2026, 11, 10), "25300", "미지급금", 10000000, None, "가상음향"),
                                ("8", D(2026, 11, 10), "25300", "미지급금", 5000000, None, "가상음향"),
                                ("8", D(2026, 11, 10), "10300", "보통예금", None, 15000000, bank_vendor)])
            self.assertEqual([r["상태"] for r in rows], ["이미 지급", "예정"])   # 같은 돈을 다음 줄에 또 쓰지 않음
            self.assertIn("2줄 합계", rows[0]["근거"])

    def test_receipts_too(self):
        from test_fundplan import plan_row
        D = dt.date
        rows = self.settle([plan_row("2026-11-10", "입금", "가상기획", 33000000)],
                           [("9", D(2026, 11, 10), "10300", "보통예금", 33000000, None, ""),
                            ("9", D(2026, 11, 10), "10800", "외상매출금", None, 11000000, "가상기획"),
                            ("9", D(2026, 11, 10), "10800", "외상매출금", None, 22000000, "가상기획")])
        self.assertEqual(rows[0]["상태"], "이미 입금")

    def test_other_vendor_lines_do_not_add_up(self):
        from test_fundplan import plan_row
        D = dt.date
        rows = self.settle([plan_row("2026-11-10", "지급", "가상음향", 15000000)],
                           [("8", D(2026, 11, 10), "25300", "미지급금", 10000000, None, "가상음향"),
                            ("8", D(2026, 11, 10), "25300", "미지급금", 5000000, None, "나무조명")])
        self.assertEqual(rows[0]["상태"], "예정일 지남")


class TestProjectProfitOneBasis(unittest.TestCase):
    """1차 E1·B5·B6: 경영관리 '종료 시점 예상이익'·예산 초과·위험표가 장부 전 지급요청과 남은 예산을 안 봐
    팀장 '지금 예상 이익'과 달랐다 (예시 A사 4,000만·C사 4,500만, A사 113% 초과를 놓침)."""

    @classmethod
    def setUpClass(cls):
        from test_review_1114b import SAMPLE_DIR
        from ceo_report.calc import compute
        from ceo_report.data import load
        cls.R = compute(load(SAMPLE_DIR), "weekly", dt.date(2026, 11, 6))

    def test_end_profit_equals_profit_now(self):
        for P in self.R["s3"]["projects"]:
            if P["profit_now"] is not None:
                self.assertEqual(P["profit_end"], P["profit_now"], P["id"])

    def test_requests_before_books_count_for_over_budget(self):
        from ceo_report import render
        a = [P for P in self.R["s3"]["projects"] if P["id"] == "P26201"][0]
        self.assertLess(a["remain_all"], 0)          # 장부 전 요청까지 넣으면 예산 초과
        self.assertGreater(a["remain"], 0)           # 자금 일정의 남은 예산(장부 전 요청 뺀 것)은 그대로
        self.assertIn("A사 연례 컨퍼런스", render._over_line(self.R))
        self.assertTrue(any("P26201" in str(r) and "등록 지출(장부 전 지급요청 포함)" in str(r) for r in self.R["risks"]))



from test_teamreport import TeamReportCase  # noqa: E402


class TestTeamProfitCountsOverBudget(TeamReportCase):
    """1차 N1·B2: 팀장 '올해 매출총이익 예상'이 예산을 넘은 요청·계획을 빼지 않아 예시 A사 이익을 2,820만 크게 보였다."""

    def test_over_budget_spending_is_subtracted(self):
        _, R, T, page = self.make()
        a = [r for r in T["up"] if r["id"] == "P26201"][0]
        P = [p for p in R["s3"]["projects"] if p["id"] == "P26201"][0]
        self.assertGreater(P["committed"], P["budget"])                         # 예시 A사: 등록 지출이 예산을 넘음
        self.assertEqual(a["rem_cost"], max(P["committed"] - a["cost_done"], 0))   # 예산이 아니라 등록 지출까지 뺌
        self.assertIn("남은 원가 = 추정 예산(요청·계획이 예산을 넘었으면 그 금액)", page)


class TestBlockedMgmtShowsNoBalances(unittest.TestCase):
    """1차 자금-1·E6: 자료가 막혀 대표 보고를 안 만들 때도 경영관리에 구간별 계산 잔액·'최저 계산 잔액 …원'이 남았다."""

    def test_buckets_and_low_balance_risks_are_blank(self):
        import re
        from unittest import mock
        from ceo_report import gate
        from ceo_report.calc import compute
        from ceo_report.data import load
        from ceo_report.render import render
        from test_review_1114b import SAMPLE_DIR
        with mock.patch.dict(os.environ, {"CEO_REPORT_TEST_GATE_OFF": "0"}):
            R = compute(load(SAMPLE_DIR), "monthly", dt.date(2026, 10, 31))   # 예시 자료엔 자금계획서가 없어 막힘
            vals = [v for b in R["s2"]["buckets"] for v in (b["bal_firm"], b["bal_all"]) if isinstance(v, int) and abs(v) > 10 ** 6]
            low = R["s2"]["min"]["firm"][0]
            self.assertTrue(vals and low)
            self.assertTrue(gate.blank_funds(R))
        txt = re.sub(r"<[^>]+>", " ", render(R, "mgmt"))
        for v in vals + [low]:
            self.assertNotIn("{:,}".format(v), txt)
        self.assertFalse([r for r in R["risks"] if "최저 계산 잔액" in r["fact"]])
        self.assertTrue(R["risks"][0]["fact"].startswith("자료 확인에서 막혀"))


class TestDividendNeedsCashAndLimit(unittest.TestCase):
    """1차 C18·C17: 여유 자금을 몰라도 배당을 권했고('한도·현금·회사 상태 모두 괜찮습니다'), 한도 0원이어도 권장 배당 칸에 금액이 나왔다."""

    def test_unknown_cash_holds(self):
        from test_dividend import R, S, ready
        from ceo_report import dividend as dv
        A = dv.advise(R(None), S, {"best": 33_000_000}, ready())
        self.assertEqual(A["verdict"], "보류")
        self.assertEqual(A["amount"], 0)
        self.assertIn("여유 자금을 계산하지 못해", A["reasons"][0])
        self.assertNotIn("모두 괜찮습니다", " ".join(A["reasons"]))

    def test_zero_limit_has_no_recommended_amount(self):
        from test_dividend import folder
        from ceo_report import dividend as dv
        d = folder([("대표", "100", False, False, "", "")])
        D = dv.plan(d, dt.date(2026, 11, 30), 0)
        self.assertEqual((D["best"], D["table"]), (0, []))
        self.assertIn("배당 한도가 0원", dv.render(D, lambda x: x))


class TestGateNeedsTaxEstimates(unittest.TestCase):
    """1차 자금-20: 세금예상.csv 가 없거나 읽지 못해도 대표 보고가 통과해 정기 지출이 빠진 큰 숫자가 나왔다."""

    def test_missing_tax_file_blocks(self):
        from unittest import mock
        from ceo_report import gate
        R = {"asof": dt.date(2026, 11, 15), "fundplan": {"used": True}, "auto_facts": {"book_date": "2026-11-15"},
             "settings_num": {}, "tax_missing": True}
        with mock.patch.dict(os.environ, {"CEO_REPORT_TEST_GATE_OFF": "0"}):   # 다른 시험 파일이 켜 둔 끄개와 상관없이
            self.assertTrue(any("세금예상.csv" in p for p in gate.problems(R)))
            R["tax_missing"] = False
            self.assertEqual(gate.problems(R), [])

    def test_compute_marks_missing_tax_file(self):
        import shutil
        import tempfile
        from ceo_report.calc import compute
        from ceo_report.data import load
        from test_review_1114b import SAMPLE_DIR
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        shutil.copytree(SAMPLE_DIR, os.path.join(t, "in"))
        self.assertFalse(compute(load(os.path.join(t, "in")), "weekly", dt.date(2026, 11, 6))["tax_missing"])
        os.remove(os.path.join(t, "in", "세금예상.csv"))
        self.assertTrue(compute(load(os.path.join(t, "in")), "weekly", dt.date(2026, 11, 6))["tax_missing"])


class TestSourcesLineShowsLastBankDay(unittest.TestCase):
    """1차 N13: 분개장 날짜 = 위하고에서 받은 날 → 회계 입력이 밀려도 머리글엔 '분개장 11/14'만 보였다."""

    def test_last_bank_day_in_header(self):
        from ceo_report import gate
        R = {"asof": dt.date(2026, 11, 15), "auto_facts": {"book_date": "2026-11-14", "last_bank": "2026-11-03"}, "fundplan": None}
        self.assertIn("분개장 2026-11-14 (통장 거래 2026-11-03까지 입력)", gate.sources_line(R))
        R["auto_facts"]["last_bank"] = "2026-11-14"
        self.assertIn("분개장 2026-11-14 ·", gate.sources_line(R))


class TestRecognizedRevenueCutAtAsof(unittest.TestCase):
    """1차 N12·E2·B12: 월말 며칠 뒤 만든 월간은 매출반영누계에 기준일 뒤 달 매출이 섞여 '올해 매출 예상'이 그만큼 작아졌다."""

    def test_later_month_revenue_is_taken_out(self):
        import shutil
        import tempfile
        from ceo_report.calc import compute
        from ceo_report.data import load
        from test_review_1114b import SAMPLE_DIR
        from test_teamreport import _append
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        f = os.path.join(t, "in")
        shutil.copytree(SAMPLE_DIR, f)
        before = compute(load(f), "monthly", dt.date(2026, 10, 31))
        P0 = [p for p in before["s3"]["projects"] if p["id"] == "P26203"][0]
        _append(os.path.join(f, "손익.csv"), [{"출처": "WEHAGO", "연월": "2026-11", "단위": "프로젝트", "대상": "P26203 C사 전시 부스",
                                              "매출": "30,000,000", "직접비": "0"}])
        import csv
        rows = list(csv.DictReader(io.StringIO(_read(os.path.join(f, "프로젝트.csv"), "utf-8-sig"))))
        for r in rows:
            if r["프로젝트번호"] == "P26203":
                r["매출반영누계"] = str(int((r["매출반영누계"] or "0").replace(",", "")) + 30000000)
        with open(os.path.join(f, "프로젝트.csv"), "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        after = compute(load(f), "monthly", dt.date(2026, 10, 31))
        P1 = [p for p in after["s3"]["projects"] if p["id"] == "P26203"][0]
        self.assertEqual(P1["recognized"], P0["recognized"])         # 10/31 기준으로는 11월 매출이 없던 것과 같다
        self.assertEqual(P1["recognized_after"], 30000000)


class TestPartlyPaidTaxesStay(unittest.TestCase):
    """1차 자금-6: 원천세를 세무서분만, 4대보험을 한 공단만 내도 그 기간 줄 전체가 사라져 남은 돈이 '꼭 나갈 돈'에서 빠졌다."""

    def ln(self, day, no, code, vendor, debit=None, credit=None):
        return {"date": day, "no": no, "account_code": code, "account": "", "debit": debit, "credit": credit, "vendor": vendor,
                "vendor_code": "", "memo": ""}

    def test_withholding_local_part_left(self):
        from ceo_report import tax
        D = dt.date
        j = [self.ln(D(2026, 9, 25), "1", "25400", "역삼세무서", credit=1000000),
             self.ln(D(2026, 9, 25), "1", "25400", "강남구청", credit=100000),
             self.ln(D(2026, 10, 10), "2", "25400", "역삼세무서", debit=1000000),
             self.ln(D(2026, 10, 10), "2", "10300", "신한", credit=1000000)]
        rows = [r for r in tax.withholding(j, D(2026, 10, 15), mode="매월") if "9월" in r["대상기간"]]
        self.assertEqual([r["금액"] for r in rows], ["100000"])
        self.assertIn("남은 지자체분만", rows[0]["근거"])
        j.append(self.ln(D(2026, 10, 12), "3", "25400", "강남구청", debit=100000))
        self.assertFalse([r for r in tax.withholding(j, D(2026, 10, 15), mode="매월") if "9월" in r["대상기간"]])

    def test_social_one_insurer_paid(self):
        from ceo_report import tax
        D = dt.date
        j = [self.ln(D(2026, 9, 25), "1", "25400", "국민연금공단", credit=200000),
             self.ln(D(2026, 9, 25), "1", "25400", "건강보험공단", credit=100000),
             self.ln(D(2026, 10, 10), "2", "25400", "국민연금공단", debit=200000),
             self.ln(D(2026, 10, 10), "2", "81700", "국민연금공단", debit=200000),
             self.ln(D(2026, 10, 10), "2", "10300", "신한", credit=400000)]
        rows = [r for r in tax.social(j, D(2026, 10, 15)) if r["대상기간"] == "2026년 9월분"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["금액"], "200000")   # 건강보험 직원분 10만 + 같은 비율 회사분 10만
        self.assertIn("국민연금 납부 확인", rows[0]["근거"])

    def test_social_all_paid_under_one_insurer_name(self):
        from ceo_report import tax
        D = dt.date   # 두 공단분을 한 공단 거래처로 몰아 냈어도 금액이 다 찼으면 다 낸 것
        j = [self.ln(D(2026, 9, 25), "1", "25400", "국민연금공단", credit=200000),
             self.ln(D(2026, 9, 25), "1", "25400", "건강보험공단", credit=100000),
             self.ln(D(2026, 10, 10), "2", "25400", "국민연금공단", debit=300000),
             self.ln(D(2026, 10, 10), "2", "10300", "신한", credit=300000)]
        self.assertFalse([r for r in tax.social(j, D(2026, 10, 15)) if r["대상기간"] == "2026년 9월분"])


class TestClosingSlipKeepsCorpTax(unittest.TestCase):
    """1차 C5·D8: 결산전표의 법인세 줄(법인세등 차변)을 변환이 지워 결산 뒤 연간 보고도 실제 대신 예상 법인세를 썼다."""

    def test_corp_tax_debit_survives(self):
        from ceo_report import convert
        ln = {"date": dt.date(2025, 12, 31), "no": "9", "sort": "결차", "account_code": "99800", "account": "법인세등",
              "debit": 12345000, "credit": None}
        kept = convert.closing_pl_line(ln, ("결차", "결대"))
        self.assertEqual((kept["debit"], kept["credit"]), (12345000, None))
        moved = dict(ln, sort="결대", debit=None, credit=12345000)   # 손익 대체 쪽은 그대로 뺌
        self.assertIsNone(convert.closing_pl_line(moved, ("결차", "결대")))


class TestTodoIdsKeepProjectsApart(unittest.TestCase):
    """2차 P3-9·P4-10: 이름이 숫자만 다른 두 프로젝트의 할 일이 한 ID가 되어 하나가 사라졌고, 차이 10만에 한 결정이 5천만 차이에도 붙었다."""

    def test_names_differing_in_numbers_stay_apart(self):
        from ceo_report import mgmt_topics as M
        a = M.todo_id("프로젝트", "[26101] 가을 행사 1차: 예산 초과 1,200,000원", "예산 다시 보기")
        b = M.todo_id("프로젝트", "[26102] 가을 행사 2차: 예산 초과 1,200,000원", "예산 다시 보기")
        self.assertNotEqual(a, b)

    def test_small_decision_does_not_cover_big_gap(self):
        from ceo_report import mgmt_topics as M
        small = M.todo_id("자료", "장부와 위하고 차이 100,000원", "차이 원인 확인")
        big = M.todo_id("자료", "장부와 위하고 차이 50,000,000원", "차이 원인 확인")
        near = M.todo_id("자료", "장부와 위하고 차이 120,000원", "차이 원인 확인")
        self.assertNotEqual(small, big)
        self.assertEqual(small, near)


class TestBlindCashTodosNotDone(unittest.TestCase):
    """2차 P4-12: 자료가 막혀 자금을 판단하지 못한 보고에서 지난번 자금 할 일이 '처리'로 표시됐다."""

    def test_cash_todo_is_not_marked_done_when_blind(self):
        from ceo_report import mgmt_topics as M
        prev = {"items": {"할일|자금|x": {"n": 1, "first": "2026-11-01", "text": "잔액 확인", "topic": "cash", "owner": "경영관리"},
                          "할일|자료|y": {"n": 1, "first": "2026-11-01", "text": "자료 받기", "topic": "data", "owner": "경영관리"}}}
        R = {"asof": D(2026, 11, 8), "todo_prev": prev, "todo_decisions": {}, "_gate_hidden": {}}
        _, done = M.todo_status(R, [])
        st = dict((d["id"], d["st"]) for d in done)
        self.assertEqual(st, {"할일|자금|x": "na", "할일|자료|y": "done"})
        R.pop("_gate_hidden")
        _, done = M.todo_status(R, [])
        self.assertEqual(set(d["st"] for d in done), {"done"})


class TestPlanMatchNeedsSameVendor(unittest.TestCase):
    """2차 P5-28: 지급요청을 자금계획서 줄과 날짜·금액만으로 이어, 승인 가정 체크를 풀면 다른 거래처의 확정 지급까지 사라졌다."""

    def test_other_vendor_same_amount_near_date_not_taken(self):
        from ceo_report import approval
        norm = lambda v: (v or "").replace(" ", "").replace("(주)", "")
        ev = {"source": "자금계획서", "io": "out", "amount": 1000000, "desc": "을상사", "date": D(2026, 11, 20), "project": ""}
        rq = {"status": "pending", "amount": 1000000, "schedule_amount": None, "vendor": "갑상사", "code": "",
              "date": D(2026, 11, 19), "xstatus": "", "rule": ""}
        F = {"used": True, "months": {"2026-11"}}
        taken, moved, absent = approval._match_plan([rq], [ev], F, norm)
        self.assertEqual(taken, set())
        same = dict(rq, vendor="을상사")
        taken, moved, absent = approval._match_plan([same], [ev], F, norm)
        self.assertEqual(taken, {id(ev)})
        blank = dict(ev, desc="")   # 계획서에 거래처가 비었으면 예전처럼 날짜로 잇는다
        taken, _, _ = approval._match_plan([dict(rq)], [blank], F, norm)
        self.assertEqual(taken, {id(blank)})


class TestIntegrityWarningsKept(unittest.TestCase):
    """2차 P3-12: 정합성 결과 줄에 '0건·0개'가 어디든 있으면 버려 '10건'·'…3개 확인 필요, 금액 빈 줄 0개' 경고도 사라졌다."""

    def test_counts_next_to_words_decide(self):
        from ceo_report.checklist import _integrity_warn as w
        self.assertTrue(w("입력 자료 확인 필요 10건 (파일 · 내용 · 건수)"))
        self.assertTrue(w("전표 1,230개 중 차변≠대변 3개 확인 필요, 금액 빈 줄 0개"))
        self.assertTrue(w("· 확인 필요: 설정.csv — 값 이상 (3건)"))
        self.assertTrue(w("대조 불일치 2건"))
        self.assertFalse(w("입력 자료 확인 필요 없음"))
        self.assertFalse(w("전표 1,230개 중 차변≠대변 0개 OK, 금액 빈 줄 0개"))
        self.assertFalse(w("대조 불일치 0건"))
        self.assertTrue(w("자금계획 ← 바뀜"))


class TestXchkSignalShowsGaps(unittest.TestCase):
    """2차 P3-15: 위하고 대조에 차이가 있어도 경영관리 신호는 '양호·대조함'이었다."""

    def test_vendor_or_cash_gap_turns_warning(self):
        from ceo_report import digest
        R = {"kind": "monthly", "xchk": {"state": "ok", "vendor_summary": {"diff_count": 2, "diff_sum": 3500000},
                                         "cash": {"balance_diff": 0}}}
        try:
            L = digest.lights(R)
        except Exception:
            self.skipTest("lights() needs a fuller report")
        x = [v for v in L if v["key"] == "xchk"][0]
        self.assertEqual(x["lv"], digest.WA)
        self.assertIn("거래처 미지급 차이 2곳", x["facts"][0])


class TestSavedValuesNotLost(unittest.TestCase):
    """2차 P5-17·P2-9·P5-19·P5-20: 창에서 저장하면 예전 값이 지워지거나, 다른 줄이 사라지거나, 엉뚱한 값이 '확인함'이 됐다."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, True)

    def test_shareholder_blank_fields_keep_old_values(self):
        from ceo_report import dividend
        dividend.save(self.tmp, "가상주주", "60", False, True, "1,000,000", "2,000,000", dependents="3")
        dividend.save(self.tmp, "가상주주", "70", False, True, "", "", dependents="")
        r = [x for x in dividend.read(self.tmp) if x["이름"] == "가상주주"][0]
        self.assertEqual((r["지분율"], r["다른금융소득"], r["그밖소득"], r["공제인원"]), ("70", "1000000", "2000000", "3"))
        dividend.save(self.tmp, "가상주주", "70", False, True, "-", "", dependents="")
        r = [x for x in dividend.read(self.tmp) if x["이름"] == "가상주주"][0]
        self.assertEqual((r["다른금융소득"], r["그밖소득"]), ("", "2000000"))

    def test_card_save_refuses_to_drop_other_bad_line(self):
        from ceo_report import app, tax
        with open(os.path.join(self.tmp, tax.CARD_FILE), "w", encoding="utf-8-sig") as f:
            f.write("카드사,납부일,기산일\n신한,15,1\n롯데,삼십,1\n")
        with self.assertRaises(ValueError):
            app.save_card(self.tmp, "신한", "20")
        self.assertIn("롯데,삼십", _read(os.path.join(self.tmp, tax.CARD_FILE), "utf-8-sig"))
        app.save_card(self.tmp, "롯데", "25")   # 잘못된 줄을 그 카드로 고치는 것은 됨
        self.assertEqual(tax.read_card_days(self.tmp)[0]["롯데"], (25, 1))

    def test_schedule_into_empty_file_gets_header(self):
        from ceo_report import app, data
        open(os.path.join(self.tmp, app.SCHED_FILE), "w").close()
        app.add_schedule(self.tmp, "2026-11-30", "지급", "1,000,000", "확정", "가상업체")
        text = _read(os.path.join(self.tmp, app.SCHED_FILE), "utf-8-sig")
        self.assertTrue(text.startswith("예정일") or text.splitlines()[0].count(",") >= 3)
        self.assertIn("가상업체", text.splitlines()[1])

    def test_tax_standard_rejects_odd_values(self):
        from ceo_report import taxlaw
        rate = next(k for k, u in taxlaw.UNIT.items() if u == "비율")
        won_key = next(k for k, u in taxlaw.UNIT.items() if u == "원")
        for bad in ({rate: "-5%"}, {rate: "200%"}, {rate: "nan"}, {won_key: "-1000"}, {won_key: "abc"}):
            with self.assertRaises(ValueError):
                taxlaw.confirm(self.tmp, 2026, bad, source="시험")
        self.assertEqual(taxlaw.confirm(self.tmp, 2026, {rate: "9.5%"}, source="시험"), 1)

    def test_account_resave_with_blank_fields_does_not_delete(self):
        src = _read(os.path.join(ROOT, "ceo_report", "gui.py"))   # 시험 PC에 tkinter 가 없어 글로 본다
        src = src[src.find("    def save_account(self, delete=False):"):]
        i, j = src.find("계좌를 지우려면 '지우기'"), src.find("transfer.save_account(")
        self.assertTrue(0 <= i < j, "빈 칸 '저장'은 지우기 전에 막아야 함")


class TestFinishMessagesTellTheTruth(unittest.TestCase):
    """2차 C11·C12·P5-23, 1차 E10: 막혔거나 PDF가 없어도 'PDF를 열었습니다'·'자동 완료'로 보였고, 예산·팀장 출력은 찾지도 못했다."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, True)

    def _w(self, rel, text):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_blocked_and_missing_pdf_are_not_success(self):
        from ceo_report import winstate, gate
        stop = self._w("2026-11-15_주간_대표보고.html", gate.stop_page("주간 대표 보고", ["자금계획서 없음"]))
        ok, line = winstate.outcome("주간", 0, [stop])
        self.assertFalse(ok)
        self.assertIn("막혀", line)
        html_only = self._w("2026-11-08_주간_대표보고.html", "<html>보고</html>")
        ok, line = winstate.outcome("주간", 0, [html_only])
        self.assertFalse(ok)
        self.assertIn("찾지 못했습니다", line)
        pdf = self._w("2026-11-08_주간_대표보고.pdf", "%PDF")
        self.assertEqual(winstate.outcome("주간", 0, [html_only, pdf]), winstate.rc_message("주간", 0))

    def test_new_files_sees_budget_and_team_folders(self):
        import time
        from ceo_report import app
        t0 = time.time() - 5
        a = self._w(os.path.join("예산", "2027_예산_대표용.pdf"), "%PDF")
        b = self._w(os.path.join("팀장용", "2026-10-31_월간_팀장_기획1팀.pdf"), "%PDF")
        got = app.new_files(self.tmp, t0)
        self.assertIn(a, got)
        self.assertIn(b, got)
        from ceo_report import winstate
        self.assertTrue(winstate.outcome("예산", 0, got)[0])


class TestBuildStamp(unittest.TestCase):
    """2차 C16·P6-12: exe 에 판(커밋) 표시가 없어 어떤 판이 깔렸는지 알 수 없었다."""

    def test_stamp_and_display(self):
        from ceo_report import version
        self.assertTrue(version.build())
        wf = _read(os.path.join(ROOT, ".github", "workflows", "build-exe.yml"))
        self.assertLess(wf.find("tools/stamp_build.py"), wf.find("PyInstaller --noconfirm"))
        self.assertIn("ceo_report._build", wf)
        self.assertIn("판 %s", _read(os.path.join(ROOT, "ceo_report", "gui.py")))


class TestForecastTrackHonest(unittest.TestCase):
    """1차 B15·B16: 예상 입금이 80% 빗나가도 '믿고 써도 됨'이었고, 같은 기준일을 며칠 뒤 다시 만들면 예측 기록을 덮어 오차가 0이 됐다."""

    def test_expected_inflow_miss_is_flagged(self):
        from ceo_report import digest
        K = {"months": [{"in": {"firm": 0, "all": 100000000, "actual": 20000000},
                         "out": {"firm": 0, "all": 0, "actual": 0}}]}
        out = digest.track_suggest(K)
        self.assertTrue(any("덜 들어왔습니다" in x for x in out))
        self.assertFalse(any("믿고 써도" in x for x in out))

    def test_earlier_day_record_is_kept(self):
        import tempfile, shutil, time
        from ceo_report import insights
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        folder = os.path.join(tmp, insights.RECORD_DIR)
        os.makedirs(folder)
        path = os.path.join(folder, "일정_2026-11-08.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write('[{"old": 1}]')
        old = time.time() - 3 * 86400
        os.utime(path, (old, old))
        self.assertTrue(insights._frozen(path))
        os.utime(path, None)
        self.assertFalse(insights._frozen(path))


class TestUnknownAmountsStayUnknown(unittest.TestCase):
    """1차 B7·B13: 계산서 일부 금액을 몰라도 미발행을 확정처럼, 끝난 프로젝트 원가를 몰라도 팀 이익을 확정처럼 보였다."""

    def test_partly_unknown_invoices_make_unissued_unknown(self):
        from ceo_report import calc
        P = {"id": "26101", "event_date": "2026-10-01", "estimate": 100000000, "contract": 100000000}
        x = {"P": P, "issued": 40000000, "issued_unknown": 1}
        E = calc.event_unissued([x], D(2026, 11, 15), False)
        self.assertEqual(E["rows"], [])
        self.assertIn("일부 미확인", E["unknown"][0]["why"])
        E = calc.event_unissued([dict(x, issued_unknown=0)], D(2026, 11, 15), False)
        self.assertEqual(E["rows"][0]["unissued"], 60000000)

    def test_closed_project_with_unknown_cost_counts_as_unknown_profit(self):
        src = _read(os.path.join(ROOT, "ceo_report", "teamreport.py"))
        self.assertIn('rem_cost = None if P_.get("unknown_cost") else 0', src)


class TestIntegrityFailsOnMismatch(unittest.TestCase):
    """1차 D18·2차 P5-25: 차변≠대변을 찾거나 보고를 못 만들어도 정합성 점검이 '성공(0)'으로 끝났다."""

    def test_unbalanced_slip_is_not_ok(self):
        from types import SimpleNamespace
        from ceo_report import integrity
        ln = lambda no, code, dr, cr: {"date": D(2026, 1, 2), "no": no, "account_code": code, "debit": dr, "credit": cr, "sort": "일반"}
        base = [ln("1", "33100", None, 20000000), ln("1", "10300", 20000000, None)]   # 설립 자본금 (처음부터 있음)
        mk = lambda J: SimpleNamespace(journal=J, files={}, unused=[])
        out = []
        ok = integrity._journal_checks(mk(base), out)
        bad = base + [ln("2", "81100", 1000000, None), ln("2", "10300", None, 900000)]
        out2 = []
        self.assertFalse(integrity._journal_checks(mk(bad), out2))
        self.assertTrue(any("확인 필요" in x for x in out2))
        src = _read(os.path.join(ROOT, "ceo_report", "integrity.py"))
        self.assertIn("if not _report_checks(tmp, temp_input, asof, out):", src)
        self.assertIsInstance(ok, bool)


class TestDividendUsesTaxStandards(unittest.TestCase):
    """1차 C19: '세법 기준 확인'에서 바꾼 건강보험료율이 배당 계산에 가지 않았다."""

    def test_confirmed_health_rate_changes_extra_premium(self):
        import tempfile, shutil
        from ceo_report import dividend, taxlaw
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        dividend.save(tmp, "가상주주", "100", False, True, "15,000,000", "0")
        asof = D(2026, 11, 15)
        before = dividend.plan(tmp, asof, 100000000)
        taxlaw.confirm(tmp, 2026, {"건강보험료율": "10%"}, source="시험")
        after = dividend.plan(tmp, asof, 100000000)
        tax = lambda r: [t["tax"] for t in r["table"]]
        self.assertNotEqual(tax(before), tax(after))
        self.assertEqual(dividend.HEALTH_RATE, 0.0719)   # 계산이 끝나면 원래 값으로


class TestWrongTermJournalWarned(unittest.TestCase):
    """2차 C14: 지난 기수 분개장을 오늘 받으면 받은 날만 보고 최신으로 통과했다 — 마지막 통장 거래가 아주 오래면 크게 알린다."""

    def test_old_term_note(self):
        from ceo_report import gate
        R = {"asof": D(2026, 11, 15), "auto_facts": {"last_bank": "2025-12-31"}}
        self.assertIn("지난 기수", gate.bank_lag_note(R))
        R["auto_facts"]["last_bank"] = "2026-11-01"
        self.assertNotIn("지난 기수", gate.bank_lag_note(R))
        self.assertIn("기준일보다 14일 전", gate.bank_lag_note(R))


class TestMalformedJournalRowsRefused(unittest.TestCase):
    """2차 P2-5: 분개장 JSON 의 짧은 줄을 조용히 버려 일부가 빠진 장부를 정상으로 썼다."""

    def test_short_row_refuses_file(self):
        import sys, tempfile, shutil
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        from test_journal_json import COLS, write_json
        from ceo_report import wehago
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        good = ["20261005", "00001", "매입전표", "차변", "81300", "접대비(판)", 100, 0, "가상", "00001", "메모", "", "", "",
                "2026-11-13T10:00:00.000", 1]
        doc = {"종류": "분개장", "형식": 1, "기간": {"start_date": "20260101", "end_date": "20261113", "gisu": "2"},
               "열": COLS, "줄": [good, good[:5]]}
        write_json(tmp, "261113 분개장 자동수집.json", doc)
        with self.assertRaises(wehago.WehagoError):
            wehago.read_journal_json(os.path.join(tmp, "261113 분개장 자동수집.json"))


class TestTeamReportFailuresShown(TeamReportCase):
    """2차 P3-19·P4-5: 자동 분석 실패가 팀장 보고에서 말없이 빠졌고, 한 팀을 못 쓰면 나머지도 안 쓰고 월간은 '완료'였다."""

    def test_analysis_failure_note_and_per_team_failure(self):
        from unittest import mock
        from ceo_report import teamreport, insights
        d, R, _, _ = self.make()
        out = os.path.join(self.tmp, "출력")
        with mock.patch.object(insights, "for_report", return_value=(None, "KeyError: 'x'")):
            pages = teamreport.write_all(d, R, out)
        self.assertTrue(pages)
        self.assertIn("자동 분석 절", _read(pages[0]))
        # 첫 팀 자리에 폴더를 만들어 쓰기를 막아도 다른 팀은 쓰고, 실패는 모은다
        teams = teamreport.team_names(d)
        bad = pages[0] + ".tmp"
        os.makedirs(bad)
        R.pop("_team_failed", None)
        pages2 = teamreport.write_all(d, R, out)
        self.assertEqual(len(pages2), len(teams) - 1)
        self.assertEqual(len(R["_team_failed"]), 1)
        self.assertIn("return 7   # 팀장 보고 일부를 못 씀", _read(os.path.join(ROOT, "보고서.py")))


# ───────────── 2차 P2-14·P3-10: 자동분석·확인할것 저장 실패가 '변환 완료'에 묻히지 않음 ─────────────
class TestConvertSideFilesFailLoudly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_convert
        test_convert.setUpModule()   # 샘플을 임시 폴더에 새로 쓴다

    def _company(self):
        from test_convert_review_fixes import company
        return company(self)

    def test_side_file_failures_are_said_and_stale_copies_removed(self):
        from unittest import mock
        from ceo_report import insights
        from test_convert_review_fixes import result_text, run_convert_core
        tmp, input_dir, collect, wehago_dir = self._company()
        for name in (insights.FILE, checklist.CONVERT_FILE):   # 지난 실행이 남긴 것 (지난 장부 날짜)
            with open(os.path.join(input_dir, name), "w", encoding="utf-8") as f:
                f.write('{"book_date": "2026-01-02"}')
        with mock.patch.object(insights, "write_facts", return_value=False), \
                mock.patch.object(checklist, "save_convert_items", return_value=False):
            res = run_convert_core(input_dir, collect, wehago_dir)
        self.assertEqual(res.code, 7, res.lines)
        warn = [ln for ln in res.lines if ln.startswith("경고: ") and "쓰지 못함" in ln]
        self.assertEqual(len(warn), 2, res.lines)
        self.assertIn("예전 것은 지워", warn[0])
        self.assertIn("예전 항목은 지움", warn[1])
        text = result_text(input_dir)
        for w in warn:
            self.assertIn(w, text)
        self.assertFalse(os.path.exists(os.path.join(input_dir, insights.FILE)))
        self.assertFalse(os.path.exists(os.path.join(input_dir, checklist.CONVERT_FILE)))

    def test_normal_run_writes_both_and_stays_zero(self):
        from ceo_report import insights
        from test_convert_review_fixes import run_convert_core
        tmp, input_dir, collect, wehago_dir = self._company()
        res = run_convert_core(input_dir, collect, wehago_dir)
        self.assertEqual(res.code, 0, res.lines)
        self.assertTrue(os.path.exists(os.path.join(input_dir, insights.FILE)))
        self.assertTrue(os.path.exists(os.path.join(input_dir, checklist.CONVERT_FILE)))
        self.assertFalse([ln for ln in res.lines if "쓰지 못함" in ln], res.lines)


# ───────────── 2차 C2·P5-8: 거래처 이름 낱말로 이체 파일에서 빼지 않음, 뺀 것은 이름으로 ─────────────
class TestTransferRegularByCategory(unittest.TestCase):
    def _ev(self, desc, cat="자금계획서 미지급금 지급", source="자금계획서", amount=1_000_000):
        return {"date": D(2026, 11, 4), "io": "out", "amount": amount, "desc": desc, "cat": cat, "source": source,
                "project": "", "firm": True, "basis": "", "vendor_code": ""}

    def test_vendor_name_words_do_not_drop_a_vendor_payment(self):
        from ceo_report import transfer
        info = {}
        picked, skipped = transfer.pick([self._ev("초대카드제작소"),
                                         self._ev("인건비", cat="프로젝트 지급요청", source="프로젝트집행")],
                                        D(2026, 11, 1), D(2026, 11, 7), info)
        self.assertEqual(skipped, 0)
        self.assertEqual(sorted(ln["vendor"] for _, ln in picked), ["인건비", "초대카드제작소"])
        self.assertIn(("초대카드제작소", "카드"), info["hints"])

    def test_category_tax_and_card_company_still_left_out_with_names(self):
        from ceo_report import transfer
        info = {}
        evs = [self._ev("가상건물", cat="임차료", source="자금일정"),
               self._ev("급여 10월분", cat="급여 (장부 계산)", source="세금예상"),
               self._ev("신한카드"),                       # 카드사 (이름 끝이 카드) — 꼭 나갈 돈 한 곳의 규칙
               self._ev("신한_5860"),                      # 장부 카드 거래처
               self._ev("가상세무서")]                      # 세무서
        picked, skipped = transfer.pick(evs, D(2026, 11, 1), D(2026, 11, 7), info)
        self.assertEqual((picked, skipped), ([], 5))
        self.assertEqual([v for v, _, _ in info["regular"]], ["가상건물", "급여 10월분", "신한카드", "신한_5860", "가상세무서"])
        self.assertTrue(all(why for _, _, why in info["regular"]))

    def test_make_file_says_what_it_left_out(self):
        src = _read(os.path.join(ROOT, "ceo_report", "transfer.py"))
        self.assertIn("정기 지급이라 뺌: %s", src)


# ───────────── 2차 P5-7: 출금일을 멀리 잡아도 이체 기간 = 보고 출금 목록 기간 ─────────────
class TestTransferRangeMatchesReportList(unittest.TestCase):
    def test_far_payday_starts_the_day_after_asof(self):
        from ceo_report import winstate
        self.assertEqual(winstate.transfer_range(D(2026, 11, 27), D(2026, 11, 10)), (D(2026, 11, 11), D(2026, 11, 27)))

    def test_near_payday_and_unknown_asof_unchanged(self):
        from ceo_report import winstate
        self.assertEqual(winstate.transfer_range(D(2026, 11, 13), D(2026, 11, 10)), (D(2026, 11, 11), D(2026, 11, 13)))
        self.assertEqual(winstate.transfer_range(D(2026, 11, 13)), (D(2026, 11, 7), D(2026, 11, 13)))


# ───────────── 2차 P5-21: 상세 내역은 한 지급에만, 다른 거래처 요청 상세는 붙이지 않음 ─────────────
class TestPayDetailsAttachOnce(unittest.TestCase):
    def test_manual_detail_goes_to_the_earliest_line_only(self):
        from ceo_report import paydetail
        a = {"io": "out", "date": D(2026, 12, 4), "amount": 500_000, "desc": "가상음향"}
        b = {"io": "out", "date": D(2026, 11, 6), "amount": 500_000, "desc": "(주)가상음향"}
        n = paydetail.attach([a, b], [{"vendor": "가상음향", "amount": 500_000, "text": "11월 장비", "source": "수기"}])
        self.assertEqual(n, 1)
        self.assertEqual(b["detail"], "11월 장비")
        self.assertNotIn("detail", a)

    def test_request_detail_of_another_vendor_in_the_same_project_is_not_used(self):
        light = {"io": "out", "date": D(2026, 11, 6), "amount": 2_200_000, "project": "[26201] 가상 행사", "desc": "가상조명"}
        sound = {"key": "1", "project": "26201", "vendor": "가상음향", "amount": 2_200_000, "note": "음향 장비 잔금"}
        self.assertEqual(payreq.attach([light], [sound]), 0)
        self.assertNotIn("detail", light)
        two = [dict(sound, key="2", amount=1_100_000), dict(sound, key="3", vendor="가상무대", amount=1_100_000)]
        self.assertEqual(payreq.attach([light], two), 0)   # 다른 거래처 둘의 합이 같아도 붙이지 않음


# ───────────── 2차 P6-10: 반쯤 만든 백업이 보관 개수에 끼어 멀쩡한 백업을 지우지 않음 ─────────────
class TestPartialBackupNotCounted(unittest.TestCase):
    def test_failed_copy_is_removed_and_good_backups_stay(self):
        import shutil
        import tempfile
        from unittest import mock
        from ceo_report import app
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        inp = os.path.join(tmp, "입력")
        os.makedirs(inp)
        with open(os.path.join(inp, "설정.csv"), "w", encoding="utf-8") as f:
            f.write("항목,값\n")
        paths = mock.Mock(input=inp, root=tmp)
        for i in range(3):
            self.assertTrue(app.backup_input(paths, keep=3, now=dt.datetime(2026, 11, 1 + i, 9, 0, 0)))
        real = shutil.copytree

        def half(src, dst, **kw):
            os.makedirs(dst)
            raise OSError(28, "No space left on device")
        lines = []
        with mock.patch.object(app.shutil, "copytree", side_effect=half):
            self.assertIsNone(app.backup_input(paths, lines.append, keep=3, now=dt.datetime(2026, 11, 5, 9, 0, 0)))
        base = os.path.join(tmp, app.BACKUP_DIR)
        self.assertEqual(sorted(os.listdir(base)), ["20261101_090000", "20261102_090000", "20261103_090000"])
        self.assertTrue(app.backup_input(paths, keep=3, now=dt.datetime(2026, 11, 6, 9, 0, 0)))
        self.assertEqual(sorted(os.listdir(base)), ["20261102_090000", "20261103_090000", "20261106_090000"])
        self.assertIs(shutil.copytree, real)


# ───────────── 2차 P4-4·P4-8: 새 HTML·PDF 를 다 만든 뒤에 바꿔 넣음 (이전 파일을 먼저 잃지 않음, 반쯤 쓴 PDF 없음) ─────────────
class TestReportFilesSwappedWhenComplete(unittest.TestCase):
    def _cli(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("report_cli_p44", os.path.join(ROOT, "보고서.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_failed_html_write_keeps_the_old_page(self):
        import shutil
        import tempfile
        from unittest import mock
        cli = self._cli()
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "a_대표보고.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write("<html>예전 보고</html>")
        with mock.patch.object(cli.os, "replace", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(OSError):
                cli._write_page(path, "<html>새 보고</html>")
        self.assertEqual(_read(path), "<html>예전 보고</html>")
        self.assertEqual(os.listdir(tmp), ["a_대표보고.html"])

    def test_timeout_leaves_no_half_pdf_and_keeps_the_old_one(self):
        import shutil
        import subprocess
        import tempfile
        from unittest import mock
        cli = self._cli()
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        html, pdf = os.path.join(tmp, "a_수정.html"), os.path.join(tmp, "a_수정.pdf")
        for p, b in ((html, b"<html></html>"), (pdf, b"%PDF-old\n%%EOF\n")):
            with open(p, "wb") as f:
                f.write(b)

        def slow(cmd, **kw):
            with open([a for a in cmd if a.startswith("--print-to-pdf=")][0].split("=", 1)[1], "wb") as f:
                f.write(b"%PDF-1.4\n1 0 obj")   # 반쯤 쓰다 시간 초과
            raise subprocess.TimeoutExpired(cmd, 120)
        with mock.patch.object(cli.subprocess, "run", side_effect=slow):
            self.assertIn("120초", cli.to_pdf("b", html, pdf))
        with open(pdf, "rb") as f:
            self.assertEqual(f.read(), b"%PDF-old\n%%EOF\n")
        self.assertEqual(sorted(os.listdir(tmp)), ["a_수정.html", "a_수정.pdf"])


# ───────────── 2차 C8: 자금일정 자동 정리 때 사용자가 더한 열을 지우지 않음 ─────────────
class TestScheduleTidyKeepsUserColumns(unittest.TestCase):
    def test_extra_column_stays_on_kept_and_moved_lines(self):
        import csv
        import shutil
        import tempfile
        from ceo_report import review_checks as RC
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with open(os.path.join(tmp, RC.SCHEDULE), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["예정일", "입출금", "금액", "확정여부", "분류", "프로젝트번호", "거래처", "근거", "비고", "담당자 메모"])
            w.writerow(["2026-11-06", "출금", "500000", "확정", "급한 지급", "", "가상", "금요일 급한 출금", "", "김 대리 확인"])
            w.writerow(["2026-11-20", "출금", "300000", "확정", "예정", "", "", "앞으로", "", "다음 주 다시 볼 것"])
        J = [{"date": D(2026, 11, 7), "no": "1", "account_code": "10300", "debit": None, "credit": 500000, "vendor": "가상",
              "vendor_norm": "가상", "type": "일반"}]
        out = RC.archive_paid_schedule(tmp, J, D(2026, 11, 10))
        self.assertIn("1줄", out[0])

        def rows(name):
            with open(os.path.join(tmp, name), encoding="utf-8-sig") as f:
                return list(csv.DictReader(f))
        self.assertEqual([r["담당자 메모"] for r in rows(RC.SCHEDULE)], ["다음 주 다시 볼 것"])
        self.assertEqual([r["담당자 메모"] for r in rows(RC.ARCHIVE)], ["김 대리 확인"])


# ───────────── 2차 P2-7: 이전 누적 CSV 를 못 읽으면 덮어쓰지 않음 (지난 달을 잃지 않게) ─────────────
class TestUnreadableCumulativeKept(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_convert
        test_convert.setUpModule()

    def test_broken_previous_file_is_left_as_is_and_said(self):
        from ceo_report import data
        from test_convert_review_fixes import company, run_convert_core
        tmp, input_dir, collect, wehago_dir = company(self)
        res = run_convert_core(input_dir, collect, wehago_dir)
        self.assertEqual(res.code, 0, res.lines)
        done = [n for n in (data.DEPT_FILE, data.STAFF_FILE, data.ACCOUNT_FILE, data.EVID_FILE)
                if any(ln.startswith("%s 만듦" % n) for ln in res.lines)]   # 이번 가상 장부로 만든 누적 파일
        self.assertTrue(done)
        for n in done:   # 머리글이 깨진 파일 (필수 열 없음)
            with open(os.path.join(input_dir, n), "w", encoding="utf-8-sig") as f:
                f.write("깨진,머리글\n2026-01,1\n")
        res = run_convert_core(input_dir, collect, wehago_dir)
        for n in done:
            self.assertEqual(_read(os.path.join(input_dir, n), "utf-8-sig"), "깨진,머리글\n2026-01,1\n", n)
            self.assertTrue([ln for ln in res.lines if ln.startswith("[%s] 만들지 않음" % n) and "읽지 못해 그대로 둠" in ln],
                            (n, res.lines))


# ───────────── 2차 C22·P3-5: 확인할 것 결정을 거의 동시에 두 번 저장해도 둘 다 남음 ─────────────
class TestDecisionsSavedTogether(unittest.TestCase):
    def test_two_quick_saves_both_stay(self):
        import shutil
        import tempfile
        import threading
        import time
        from unittest import mock
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        real = checklist.read_decisions

        def slow(input_dir):
            got = real(input_dir)
            time.sleep(0.2)   # 읽고 쓰는 사이에 다른 저장이 끼어들 틈
            return got
        with mock.patch.object(checklist, "read_decisions", side_effect=slow):
            ts = [threading.Thread(target=checklist.save_decision, args=(tmp, "항목%d" % i, "확인함", "", ""))
                  for i in (1, 2)]
            for t in ts:
                t.start()
            for t in ts:
                t.join(5)
        self.assertEqual(sorted(real(tmp)), ["항목1", "항목2"])


# ───────────── 2차 C9 묶음: 정합성 점검의 입력 사본은 프로그램 폴더 안에, 계정·계좌 파일은 베끼지 않음 ─────────────
class TestIntegrityCopyStaysOnTheDrive(unittest.TestCase):
    def test_copy_is_inside_the_program_folder_without_secrets_and_is_cleaned(self):
        import shutil
        import tempfile
        from unittest import mock
        from ceo_report import convert, credstore, integrity, transfer
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(os.path.join(ROOT, "입력양식", "샘플"), os.path.join(tmp, "입력"))
        os.makedirs(os.path.join(tmp, "수집", "위하고"))
        for n in (credstore.CRED_FILE, transfer.ACCOUNT_FILE, transfer.LOG_FILE):
            with open(os.path.join(tmp, "입력", n), "w", encoding="utf-8") as f:
                f.write("가상")
        os.makedirs(os.path.join(tmp, integrity.WORK_DIR, "점검_지난번끊김", "입력"))   # 지난번에 끊겨 남은 사본
        seen = {}
        real = convert.run

        def spy(input_dir, *a, **kw):
            seen["dir"], seen["files"] = input_dir, sorted(os.listdir(input_dir))
            return real(input_dir, *a, **kw)
        with mock.patch.object(convert, "run", side_effect=spy):
            integrity.run(tmp, os.path.join(tmp, "정합성.txt"), D(2026, 10, 31))
        self.assertTrue(os.path.abspath(seen["dir"]).startswith(os.path.join(os.path.abspath(tmp), integrity.WORK_DIR)))
        for n in (credstore.CRED_FILE, transfer.ACCOUNT_FILE, transfer.LOG_FILE):
            self.assertNotIn(n, seen["files"])
        self.assertFalse(os.path.exists(os.path.join(tmp, integrity.WORK_DIR)))   # 지난 것·이번 것 모두 치움


# ───────────── 2차 P1-17: 기억 지우기는 실패한 저장의 임시 계정 파일도 지움 ─────────────
class TestForgetRemovesLeftoverCredentials(unittest.TestCase):
    def test_clear_removes_tmp_and_failed_save_leaves_none(self):
        import shutil
        import tempfile
        from unittest import mock
        from ceo_report import credstore
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.object(credstore.os, "replace", side_effect=OSError(13, "denied")):
            with self.assertRaises(OSError):
                credstore.save(tmp, "가상아이디", "가상비번")
        self.assertEqual(os.listdir(tmp), [])
        credstore.save(tmp, "가상아이디", "가상비번")
        with open(credstore.path_of(tmp) + ".tmp", "wb") as f:   # 예전 판이 남긴 것
            f.write(b"x")
        self.assertTrue(credstore.clear(tmp))
        self.assertEqual(os.listdir(tmp), [])


# ───────────── 2차 P4-6·P4-7·P4-11: 열기·수정 모드·확인 화면이 같은 보고를 고름 ─────────────
class TestReportPickingAgrees(unittest.TestCase):
    def _out(self):
        import shutil
        import tempfile
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        return out

    def _touch(self, path, when, text="<html></html>"):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        os.utime(path, (when, when))

    def test_saved_edit_opens_instead_of_the_original(self):
        from ceo_report import winstate
        out = self._out()
        base = os.path.join(out, "2026-11-13_주간")
        self._touch(base + "_대표보고.html", 1000)
        self._touch(base + "_대표보고 (11-13 09시00분 만듦).pdf", 1000, "%PDF")
        self.assertTrue(winstate.latest_reports(out)["대표"].endswith("만듦).pdf"))
        self._touch(base + "_대표보고_수정.pdf", 2000, "%PDF")
        self.assertEqual(winstate.latest_reports(out)["대표"], base + "_대표보고_수정.pdf")

    def test_edit_mode_takes_the_report_made_last(self):
        from ceo_report import editmode, winstate
        out = self._out()
        self._touch(os.path.join(out, "2026-11-15_주간_대표보고.html"), 1000)
        self._touch(os.path.join(out, "2026-11-08_주간_대표보고.html"), 2000)   # 지난 기준일을 방금 다시 만듦
        self.assertEqual(winstate.latest_reports(out)["name"], "2026-11-08_주간")
        orig, _ = editmode.latest_report(out, "주간")
        self.assertEqual(os.path.basename(orig), "2026-11-08_주간_대표보고.html")

    def test_check_screen_has_weekly_and_monthly_todos_of_the_same_day(self):
        import json
        from ceo_report import mgmt_topics
        out = self._out()
        folder = os.path.join(out, mgmt_topics.RECORD_DIR)
        os.makedirs(folder)
        for kind, k in (("weekly", "주간할일"), ("monthly", "월간할일")):
            with open(os.path.join(folder, "할일_%s_2026-11-15.json" % kind), "w", encoding="utf-8") as f:
                json.dump({"items": {k: {"text": k, "topic": "cash", "owner": "경영관리", "n": 1}}}, f, ensure_ascii=False)
        self.assertEqual(sorted(i["id"] for i in mgmt_topics.check_items(out)), ["월간할일", "주간할일"])


# ───────────── 2차 P2-1: 새 CSV 를 놓은 뒤 예상 못 한 오류가 나면 모두 되돌림 ─────────────
class TestConvertRollsBackOnLateError(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_convert
        test_convert.setUpModule()

    def test_late_error_restores_csvs_and_says_so(self):
        from unittest import mock
        from ceo_report import hometax
        from test_convert_review_fixes import company, result_text, run_convert_core
        tmp, input_dir, collect, wehago_dir = company(self)
        self.assertEqual(run_convert_core(input_dir, collect, wehago_dir).code, 0)
        marker = "예정일,세목\n2026-01-01,지난 변환\n"
        with open(os.path.join(input_dir, "세금예상.csv"), "w", encoding="utf-8-sig") as f:
            f.write(marker)
        with mock.patch.object(hometax, "compare", side_effect=RuntimeError("가상 오류")):
            res = run_convert_core(input_dir, collect, wehago_dir)
        self.assertEqual(res.code, 7)
        self.assertIn("되돌림", res.lines[0])
        self.assertIn("RuntimeError", res.lines[0])
        self.assertEqual(_read(os.path.join(input_dir, "세금예상.csv"), "utf-8-sig"), marker)
        self.assertIn("변환 실패", result_text(input_dir))


# ───────────── 2차 P1-8: 확장이 저장하는 위하고 원본의 주민번호는 어느 칸에 있든 가림 ─────────────
class TestExtensionMasksIdNumbersEverywhere(unittest.TestCase):
    def test_scrub_masks_free_text_and_numbers(self):
        import json
        import shutil
        import subprocess
        if shutil.which("node") is None:
            self.skipTest("node 없음")
        js = (
            'const src=require("fs").readFileSync(process.argv[1],"utf8");'
            'const m=src.match(/const DROP_KEY[\\s\\S]*?\\nfunction scrub[\\s\\S]*?\\n}\\n/);'
            'eval(m[0].replace(/const /g,"var ").replace("function scrub","global.scrub=function"));'
            'console.log(JSON.stringify(scrub(JSON.parse(process.argv[2]))));')
        fake = {"nm_remark": "급여 가상인 900101-1234567 지급", "no_res": "9001011234567", "x": 9001011234567,
                "mn_bungae1": 1500000, "rows": [{"note": "주민 9001012345678"}], "slip": "20261115-0000123"}
        out = subprocess.run(["node", "-e", js, os.path.join(ROOT, "chrome_extension", "bridge.js"), json.dumps(fake)],
                             check=True, stdout=subprocess.PIPE).stdout.decode("utf-8")
        got = json.loads(out)
        self.assertEqual(got["nm_remark"], "급여 가상인 900101-1****** 지급")
        self.assertEqual(got["no_res"], "900101-1")
        self.assertEqual(got["x"], "900101-1******")
        self.assertEqual(got["rows"][0]["note"], "주민 900101-2******")
        self.assertEqual((got["mn_bungae1"], got["slip"]), (1500000, "20261115-0000123"))
        src = _read(os.path.join(ROOT, "chrome_extension", "bridge.js"))
        self.assertIn("scrub(r[k], k)", src)      # 분개장 줄
        self.assertIn("rows: scrub(j)", src)      # 자금계획 줄


# ───────────── 2차 P2-6·P1-13·P2-15: 위하고 원본이 깨졌거나 0줄이면 그렇게 알리고, [확인] 알림은 진행 상황·확인할 것에도 ─────────────
class TestRawScreensSaidHonestly(unittest.TestCase):
    def _dir(self):
        import shutil
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def _emp_file(self, d, name, emps):
        import json
        body = {"종류": "인사원본", "화면": "사원등록", "연도": "", "수집시각": "2026-11-1%s 09:00:00" % name[5],
                "응답": [{"path": "/humanresource/hrm0110/condition", "data": {"emp": emps, "rank": [], "position": []}}]}
        with open(os.path.join(d, "%s 인사_사원등록 자동수집.json" % name), "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False)

    def test_broken_newer_file_is_said_when_older_is_used(self):
        from ceo_report import wehago_raw
        d = self._dir()
        self._emp_file(d, "261112", [{"nm_krname": "가상일", "cd_emp": "1"}, {"nm_krname": "가상이", "cd_emp": "2"}])
        with open(os.path.join(d, "261113 인사_사원등록 자동수집.json"), "w", encoding="utf-8") as f:
            f.write("{깨진")
        emp = [t for t in wehago_raw.build_tables(d) if t.name.startswith("사원")][0]
        self.assertTrue(emp.written)
        self.assertTrue(any(n.startswith("[확인] 위하고 인사_사원등록") and "261113" in n and "그 전(261112)" in n for n in emp.notes),
                        emp.notes)

    def test_zero_rows_is_not_called_missing(self):
        from ceo_report import wehago_raw
        d = self._dir()
        self._emp_file(d, "261113", [])
        emp = [t for t in wehago_raw.build_tables(d) if t.name.startswith("사원")][0]
        self.assertFalse(emp.written)
        self.assertIn("읽은 줄 0건", emp.reason)
        self.assertNotIn("원본 없음", emp.reason)

    def test_every_check_note_becomes_an_item(self):
        items = checklist.convert_items([], [], ["[확인] 분개장 2026-03-01~2026-03-31 전표가 어느 파일에도 없음 — 그 기간 분개장을 받아 넣으세요"])
        self.assertEqual([i["kind"] for i in items], ["변환 알림"])
        self.assertTrue(items[0]["title"].startswith("분개장 2026-03-01"))


class TestCheckNotesReachProgress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import test_convert
        test_convert.setUpModule()

    def test_book_check_note_is_in_progress_lines_once(self):
        from test_convert_review_fixes import company, result_text, run_convert_core
        tmp, input_dir, collect, wehago_dir = company(self)
        res = run_convert_core(input_dir, collect, wehago_dir)
        got = [ln for ln in res.lines if ln.startswith("[확인] 분개장이")]
        self.assertEqual(len(got), 1, res.lines)
        self.assertEqual(result_text(input_dir).count("  알림 " + got[0]), 1)   # 변환결과.txt 에는 예전처럼 한 번


# ───────────── 2차 P5-24·P6-15: 창 없는 실행의 결과 파일은 늘 이번 실행 것 ─────────────
class TestHeadlessResultIsThisRun(unittest.TestCase):
    def test_setup_failure_replaces_an_old_success(self):
        import shutil
        import tempfile
        from unittest import mock
        from ceo_report import app, winstate
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, "입력"))
        log = os.path.join(tmp, "자동결과.txt")
        with open(log, "w", encoding="utf-8") as f:
            f.write("판: 예전\n만든 파일: 예전.pdf\nrc=0\n")
        with mock.patch.object(winstate, "start_values", side_effect=RuntimeError("창 상태 깨짐")):
            rc = app.headless(app.Paths(tmp), log, asof="2026-10-31")
        self.assertEqual(rc, 7)
        text = _read(log)
        self.assertIn("예상하지 못한 오류 (RuntimeError)", text)
        self.assertNotIn("예전.pdf", text)
        self.assertTrue(text.rstrip().endswith("rc=7"))

    def test_unwritable_result_is_printed_and_fails(self):
        import contextlib
        import shutil
        import tempfile
        from unittest import mock
        from ceo_report import app
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        buf = io.StringIO()
        with mock.patch.object(app, "_write_log", side_effect=OSError(28, "No space")), contextlib.redirect_stdout(buf):
            rc = app.headless(app.Paths(tmp), os.path.join(tmp, "없는폴더", "r.txt"), asof="2026-13-40")
        self.assertEqual(rc, 2)
        self.assertIn("결과 파일을 쓰지 못함", buf.getvalue())
        self.assertIn("rc=2", buf.getvalue())


# ───────────── 2차 P3-14: 깨진 대조 원본도 '쓰지 않음'으로 자료 대조에 남김 ─────────────
class TestBrokenReconcileRawIsListed(unittest.TestCase):
    def test_broken_file_is_in_skipped(self):
        import shutil
        import tempfile
        from ceo_report import reconcile
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with open(os.path.join(d, "261113 결산_합계잔액시산표(2기) 자동수집.json"), "w", encoding="utf-8") as f:
            f.write("{깨진")
        skipped = []
        reconcile.raw_files(d, skipped)
        self.assertEqual(skipped, ["261113 결산_합계잔액시산표(2기) 자동수집.json"])
        rows = reconcile.build_tables(type("B", (), {"journal": [], "state": "없음"})(), d, d, D(2026, 11, 13))[0].rows
        hit = [r for r in rows if r.get("항목") == "261113 결산_합계잔액시산표(2기) 자동수집.json"]
        self.assertEqual(len(hit), 1, rows)
        self.assertIn("깨졌거나", hit[0]["할일"])


# ───────────── 2차 P3-17: 근거자료로 떼어도 맨 위 자료 경고가 모두 따라감 ─────────────
class TestEvidenceKeepsAllWarnings(unittest.TestCase):
    def _page(self, top):
        return ("<html><head><title>주간 경영관리 보고</title></head><body><div class='wrap'>" + top +
                "<table><tr><td><b>근거 1-1</b></td><td>여유 자금</td><td><a href='#ev-1-1'>보기</a></td></tr></table>"
                "<div class='evb' id='ev-1-1'>근거 표<ul><li>x</li></ul></div><!-- /ev-1-1 --></div></body></html>")

    def test_alerts_follow(self):
        from ceo_report import evidence
        top = ("<div class='gate-lag' style='border:2px'>장부의 통장 거래 입력이 늦음</div>"
               "<style>.gate{}</style><div class='gate'>자금계획서가 빠진 달: 12월</div>"
               "<div class='ins-alert'>자료 대조 경고 · 장부와 비교 자료가 다름: 통장 12,000,000원</div>"
               "<div class='ins-alert'>자동 분석을 못 했습니다 · 빠져 있습니다<div class='mgonly'>오류: KeyError</div><!-- /mgonly --></div>"
               "<div class='ins-alert'>경보 · 여유 자금 부족</div>")
        doc = evidence.build(self._page(top), ["1-1"])
        for t in ("장부의 통장 거래 입력이 늦음", "자금계획서가 빠진 달: 12월", "자료 대조 경고", "자동 분석을 못 했습니다", "오류: KeyError"):
            self.assertIn(t, doc)
        self.assertNotIn("여유 자금 부족", doc)   # 경보(사업 판단)는 근거 문서에 붙이지 않는다 — 자료 경고만
        self.assertEqual(doc.count("자료 대조 경고"), 1)

    def test_gap_note_does_not_swallow_the_page(self):
        """목록 없는 '빠진 달' 경고 뒤 먼 곳의 </ul></div> 까지 한 덩어리로 잡지 않는다 (예전 정규식은 그랬음)."""
        from ceo_report import evidence
        doc = evidence.build(self._page("<style>.gate{}</style><div class='gate'>자금계획서가 빠진 달: 12월</div>"), ["1-1"])
        self.assertEqual(doc.count("근거 표"), 1, doc)
        self.assertEqual(evidence.warnings(self._page("")), [])


# ───────────── 2차 C20·P1-16: 지급 요청서를 못 쓰면 스냅숏도 완성되지 않음 ─────────────
class TestSnapshotWithRequestsAllOrNothing(unittest.TestCase):
    def test_failed_request_file_leaves_previous_snapshot(self):
        import shutil
        import tempfile
        from unittest import mock
        from ceo_report import payreq, snapshot
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        rows = [{"key": "k1", "project": "26001", "vendor": "가나", "amount": 1000, "note": "첫 줄"}]
        old = snapshot.write_snapshot(root, dt.datetime(2026, 11, 14, 9), [], [], extra=lambda f: payreq.write(f, rows))
        self.assertTrue(os.path.exists(os.path.join(old, payreq.FILE)))
        with mock.patch.object(payreq, "write", side_effect=OSError(28, "No space")):
            with self.assertRaises(OSError):
                snapshot.write_snapshot(root, dt.datetime(2026, 11, 15, 9), [], [], extra=lambda f: payreq.write(f, rows))
        self.assertEqual(snapshot.latest_snapshot(root), old)   # 요청서 없는 '완성' 스냅숏이 생기지 않는다
        self.assertEqual(sorted(os.listdir(root)), [os.path.basename(old)])   # 작성중 폴더도 남지 않음


# ───────────── 2차 P1-10·P2-3: 깨진 자동수집 파일은 가져오지 않음 ─────────────
class TestBrokenDownloadNotImported(unittest.TestCase):
    def test_good_file_stays(self):
        import shutil
        import tempfile
        from ceo_report import app
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        paths = app.Paths(tmp)
        down = os.path.join(tmp, "dl")
        os.makedirs(os.path.join(down, app.AUTO_DIR))
        os.makedirs(paths.wehago, exist_ok=True)
        name = "261115 분개장_2026 자동수집.json"
        with open(os.path.join(paths.wehago, name), "w", encoding="utf-8") as f:
            f.write('{"rows": [1, 2, 3]}')
        with open(os.path.join(down, app.AUTO_DIR, name), "w", encoding="utf-8") as f:
            f.write('{"rows": [1, 2')   # 받다 끊김
        said = []
        n = app.import_auto(paths, said.append, dirs=[down])
        self.assertEqual(n, 0)
        with open(os.path.join(paths.wehago, name), encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"rows": [1, 2, 3]}')
        self.assertTrue(any("깨져" in x for x in said), said)
        self.assertEqual(os.listdir(os.path.join(down, app.AUTO_DIR)), [])   # 개인정보가 다운로드 폴더에 남지 않음
        self.assertEqual(os.listdir(os.path.join(paths.wehago, app.ARCHIVE)), [name])


# ───────────── 2차 P4-1: 같은 기준일 보고를 여러 번 만들면 근거자료가 어느 판인지 알림 ─────────────
class TestEvidenceSaysWhichVersion(unittest.TestCase):
    def test_versions_named(self):
        import shutil
        import tempfile
        from ceo_report import app
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        P = app.Paths(tmp)
        os.makedirs(P.output, exist_ok=True)
        page = ("<html><head><title>주간 경영관리 보고</title></head><body><table class='dinfo'><tr><th>작성</th><td>2026-11-15 10:05</td></tr></table>"
                "<table><tr><td><b>근거 1-1</b></td><td>여유 자금</td><td><a href='#ev-1-1'>보기</a></td></tr></table>"
                "<div class='evb' id='ev-1-1'>근거 표</div><!-- /ev-1-1 --></body></html>")
        with open(os.path.join(P.output, "2026-11-13_주간_경영관리보고.html"), "w", encoding="utf-8") as f:
            f.write(page)
        for i, stamp in enumerate(("11-15 09시00분", "11-15 10시05분")):
            p = os.path.join(P.output, "2026-11-13_주간_대표보고 (%s 만듦).pdf" % stamp)
            open(p, "wb").close()
            os.utime(p, (1_763_000_000 + i * 3900, 1_763_000_000 + i * 3900))
        lines = []
        rc, files = app.run_task("근거주간", P, lines.append, asof="2026-11-13", nums="1-1")
        self.assertEqual(rc, 0, lines)
        with open([f for f in files if f.endswith("_근거자료_1-1.html")][0], encoding="utf-8") as f:
            doc = f.read()
        self.assertIn("보고 작성 2026-11-15 10:05", doc)
        self.assertIn("2번 만들었습니다", doc)
        self.assertTrue(any("2번 만들었습니다" in x for x in lines), lines)

    def test_single_version_has_no_note(self):
        from ceo_report import evidence
        page = ("<html><head><title>t</title></head><body><table><tr><td><b>근거 1-1</b></td><td>x</td><td><a href='#ev-1-1'>보기</a></td></tr></table>"
                "<div class='evb' id='ev-1-1'>근거 표</div><!-- /ev-1-1 --></body></html>")
        doc = evidence.build(page, ["1-1"])
        self.assertNotIn("번 만들었습니다", doc)
        self.assertNotIn("보고 작성", doc)


# ───────────── 2차 P4-2: 손으로 고친 대표 보고와 근거자료가 다르면 근거자료에 알림 ─────────────
class TestEvidenceNamesHandEdits(unittest.TestCase):
    def test_edit_listed(self):
        import shutil
        import tempfile
        import time
        from ceo_report import app, editmode
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        P = app.Paths(tmp)
        os.makedirs(P.output, exist_ok=True)
        mg = ("<html><head><title>주간 경영관리 보고</title></head><body>"
              "<table><tr><td><b>근거 1-1</b></td><td>여유 자금</td><td><a href='#ev-1-1'>보기</a></td></tr></table>"
              "<div class='evb' id='ev-1-1'>여유 자금 100</div><!-- /ev-1-1 --></body></html>")
        ceo = "<html><head><style>p{}</style></head><body><div>여유 자금</div><td>100</td></body></html>"
        with open(os.path.join(P.output, "2026-11-13_주간_경영관리보고.html"), "w", encoding="utf-8") as f:
            f.write(mg)
        orig = os.path.join(P.output, "2026-11-13_주간_대표보고.html")
        with open(orig, "w", encoding="utf-8") as f:
            f.write(ceo)
        ed = editmode.edited_path(orig)
        with open(ed, "w", encoding="utf-8") as f:
            f.write("<!doctype html>" + ceo.replace("<td>100</td>", "<td>120</td>"))
        t = time.time()
        os.utime(orig, (t - 60, t - 60))
        lines = []
        rc, files = app.run_task("근거주간", P, lines.append, asof="2026-11-13", nums="1-1")
        self.assertEqual(rc, 0, lines)
        with open([f for f in files if f.endswith("_근거자료_1-1.html")][0], encoding="utf-8") as f:
            doc = f.read()
        self.assertIn("손으로 고친 판", doc)
        self.assertIn("‘100’ → ‘120’", doc)
        # 원래 보고를 다시 만들어 _수정 이 더 오래되면 (쓰이지 않으니) 알리지 않는다
        os.utime(ed, (t - 120, t - 120))
        self.assertIsNone(editmode.edits_for(orig))


# ───────────── 2차 P1-19·P1-20: 홈택스 계산서 — 못 읽은 줄 수를 알리고, 같은 파일 안 중복·빈 승인번호를 바르게 ─────────────
class TestHometaxRowsCounted(unittest.TestCase):
    HEAD = ["작성일자", "승인번호", "공급자사업자등록번호", "상호", "공급받는자사업자등록번호", "상호", "합계금액", "공급가액", "세액"]

    def _rows(self):
        r = lambda day, no, buyer, total: [day, no, "111", "우리", buyer, "가상%s" % buyer, total, total // 11 * 10, total // 11]
        return [["목록"], self.HEAD,
                r("2026-10-01", "A-1", "21", 1100),
                r("2026-10-02", "A-1", "21", 1100),        # 같은 파일 안 같은 승인번호
                r("2026-10-03", "", "22", 2200),           # 승인번호 빈 계산서 둘은 서로 다른 것
                r("2026-10-04", "", "23", 3300),
                r("날짜아님", "A-9", "24", 4400),           # 날짜를 읽지 못한 줄
                ["", "", "", "", "", "합계", 12100, 0, 0],   # 합계 줄은 세지 않음
                []]

    def test_parse_counts_bad(self):
        from ceo_report import hometax
        info = {}
        side, rows = hometax.parse_rows(self._rows(), "매출.xlsx", info)
        self.assertEqual((side, len(rows), info["bad"]), ("매출", 4, 1))

    def test_load_dedupes_inside_file_keeps_blank_numbers(self):
        import shutil
        import tempfile
        from unittest import mock
        from ceo_report import hometax
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, hometax.FOLDER))
        for n in ("1 매출.xlsx", "2 매출.xlsx"):
            open(os.path.join(tmp, hometax.FOLDER, n), "wb").close()
        with mock.patch.object(hometax, "_read", return_value=self._rows()):
            got, notes = hometax.load(tmp)
        # 첫 파일: A-1 한 번 + 빈 번호 2건(서로 다른 계산서) = 3건 · 둘째 파일(겹치게 받음): 모두 이미 있음
        self.assertEqual(len(got["매출"]), 3)
        self.assertIn("같은 승인번호 1건은 한 번만", notes[0])
        self.assertIn("매출 0건", notes[1])
        self.assertIn("읽지 못한 줄 1건", notes[0])


# ───────────── 2차 P3-16: 새 시산표·급여·카드 자료도 '다시 변환' 판단에 ─────────────
class TestOtherWehagoDataAsksReconvert(unittest.TestCase):
    def test_new_trial_balance(self):
        import shutil
        import tempfile
        from ceo_report import app, checklist, winstate
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        P = app.Paths(tmp)
        os.makedirs(P.wehago, exist_ok=True)
        os.makedirs(P.input, exist_ok=True)

        def touch(name, when):
            p = os.path.join(P.wehago, name)
            with open(p, "w", encoding="utf-8") as f:
                f.write("{}")
            t = when.timestamp()
            os.utime(p, (t, t))
        touch("261105 분개장 자동수집.json", dt.datetime(2026, 11, 5, 10, 0))
        checklist.save_convert_items(P.input, [], now=dt.datetime(2026, 11, 5, 18, 0))
        self.assertEqual(winstate.steps(P)["new_since"], [])
        touch("261106 결산_합계잔액시산표(2기) 자동수집.json", dt.datetime(2026, 11, 6, 9, 0))
        S = winstate.steps(P)
        self.assertEqual((S["now"], S["new_since"]), (2, [winstate.OTHER_WEHAGO]))
        touch("261106 메모.txt", dt.datetime(2026, 11, 7, 9, 0))   # 자료 아닌 파일은 세지 않음
        self.assertEqual(winstate.steps(P)["collect"], dt.datetime(2026, 11, 6, 9, 0))


# ───────────── 2차 P3-11: 열어 둔 확인 화면도 새 변환 뒤 새로고침하면 새 항목 ─────────────
class TestCheckScreenFollowsNewConvert(unittest.TestCase):
    def test_plain_reload_regathers(self):
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        it = lambda i, t: {"id": i, "kind": "카드 전표", "date": "", "amount": None, "vendor": "", "title": t, "detail": "",
                           "choices": ["확인함"]}
        checklist.save_convert_items(tmp, [it("x1", "옛 항목")], now=dt.datetime(2026, 11, 14, 9, 0))
        s = checklist.Session(tmp, tmp, D(2026, 11, 14))
        self.assertIn("옛 항목", s.page())
        checklist.save_decision(tmp, "x1", "확인함")
        self.assertIn("옛 항목", s.page())   # 결정만 바뀌면 그대로 (다시 계산하지 않음)
        checklist.save_convert_items(tmp, [it("x2", "새 항목")], now=dt.datetime(2026, 11, 15, 9, 0))
        st = os.stat(os.path.join(tmp, checklist.CONVERT_FILE))
        os.utime(os.path.join(tmp, checklist.CONVERT_FILE), ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        page = s.page()
        self.assertIn("새 항목", page)
        self.assertNotIn("옛 항목", page)


# ───────────── 2차 P1-9·P6-6: 다운로드 가져오기는 파일 시각이 아니라 확장의 수집시각으로 새것을 고름 ─────────────
class TestImportByCollectedAt(unittest.TestCase):
    def _setup(self):
        import shutil
        import tempfile
        from ceo_report import app
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        paths = app.Paths(tmp)
        down = os.path.join(tmp, "dl")
        os.makedirs(os.path.join(down, app.AUTO_DIR))
        os.makedirs(paths.wehago, exist_ok=True)
        return app, paths, down

    def _put(self, path, at, mtime):
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"종류": "분개장", "수집시각": at, "줄": []}, f, ensure_ascii=False)
        os.utime(path, (mtime, mtime))

    def test_older_collection_with_newer_mtime_is_not_imported(self):
        app, paths, down = self._setup()
        name = "261115 분개장 자동수집.json"
        self._put(os.path.join(paths.wehago, name), "2026-11-15 10:00:00", 1_763_000_000)
        self._put(os.path.join(down, app.AUTO_DIR, name), "2026-11-15 08:00:00", 1_763_100_000)   # 늦게 복사된 옛 수집
        said = []
        self.assertEqual(app.import_auto(paths, said.append, dirs=[down]), 0)
        with open(os.path.join(paths.wehago, name), encoding="utf-8") as f:
            self.assertIn("10:00:00", f.read())
        self.assertTrue(any("수집시각" in x for x in said), said)

    def test_newer_collection_replaces(self):
        app, paths, down = self._setup()
        name = "261115 분개장 자동수집.json"
        self._put(os.path.join(paths.wehago, name), "2026-11-15 08:00:00", 1_763_100_000)
        self._put(os.path.join(down, app.AUTO_DIR, name), "2026-11-15 10:00:00", 1_763_000_000)
        self.assertEqual(app.import_auto(paths, [].append, dirs=[down]), 1)
        with open(os.path.join(paths.wehago, name), encoding="utf-8") as f:
            self.assertIn("10:00:00", f.read())
        self.assertEqual(len(os.listdir(os.path.join(paths.wehago, app.ARCHIVE))), 1)   # 예전 것은 지난자료로


# ───────────── 2차 P1-11: 다운로드 폴더에 받아 둔 자료도 '새 자료'로 ─────────────
class TestPendingDownloadsAreNew(unittest.TestCase):
    def test_steps_lists_pending(self):
        import shutil
        import tempfile
        from ceo_report import app, checklist, winstate
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        P = app.Paths(tmp)
        os.makedirs(P.input, exist_ok=True)
        checklist.save_convert_items(P.input, [], now=dt.datetime(2026, 11, 5, 18, 0))
        dl = os.path.join(tmp, "dl")
        os.makedirs(os.path.join(dl, app.AUTO_DIR))
        self.assertEqual(winstate.steps(P, dirs=[dl])["new_since"], [])
        p = os.path.join(dl, app.AUTO_DIR, "261106 결산_합계잔액시산표(2기) 자동수집.json")
        open(p, "w").close()
        t = dt.datetime(2026, 11, 6, 9, 0).timestamp()
        os.utime(p, (t, t))
        S = winstate.steps(P, dirs=[dl])
        self.assertEqual((S["now"], S["new_since"]), (2, [winstate.PENDING]))


# ───────────── 2차 P5-15: 창 상태 파일 값 모양이 틀려도 멈추지 않음 ─────────────
class TestWindowStateBadValues(unittest.TestCase):
    def test_bad_values_dropped(self):
        import json
        import shutil
        import tempfile
        from ceo_report import winstate
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with open(os.path.join(tmp, winstate.STATE_FILE), "w", encoding="utf-8") as f:
            json.dump({"payday": 20261113, "pick": None, "auto": "예", "runs": "어제", "other": 1}, f)
        st = winstate.load(tmp)
        self.assertEqual(st, {"runs": {}, "other": 1})
        self.assertEqual(winstate.start_values(tmp, D(2026, 11, 5))["payday"], "")
        winstate.remember_run(tmp, "변환", True, now=dt.datetime(2026, 11, 5, 18, 40))
        self.assertEqual(winstate.load(tmp)["runs"], {"변환": {"at": "2026-11-05 18:40", "ok": True}})
        with open(os.path.join(tmp, winstate.STATE_FILE), "w", encoding="utf-8") as f:
            json.dump({"runs": {"변환": {"at": 5, "ok": "y"}, "주간": {"at": "2026-11-05 10:00", "ok": False}}}, f)
        self.assertEqual(list(winstate.load(tmp)["runs"]), ["주간"])


# ───────────── 2차 P5-14: 진행 처리 한 건이 실패해도 다음 처리 예약은 남음 ─────────────
class TestPumpKeepsGoing(unittest.TestCase):
    def test_error_in_one_item(self):
        import queue
        try:
            from ceo_report import gui
        except ImportError:
            self.skipTest("tkinter 없음")
        logged, after = [], []

        class Log(object):
            def configure(self, **k):
                pass

            def insert(self, where, text):
                logged.append(text)

            def see(self, where):
                pass

        class Root(object):
            def after(self, ms, fn):
                after.append(ms)

        done = []

        class Fake(object):
            q = queue.Queue()
            log = Log()
            root = Root()

            def _pump_one(self, kind, val):
                if kind == "bad":
                    raise OSError(5, "열 수 없음")
                done.append(kind)

            def pump(self):
                pass
        f = Fake()
        f.q.put(("bad", None))
        f.q.put(("line", "다음"))
        gui.Window.pump(f)
        self.assertEqual(done, ["line"])
        self.assertTrue(any("화면 처리 중 오류" in x for x in logged), logged)
        self.assertEqual(after, [100])


# ───────────── 2차 P1-21·P1-23: 법령 일부 실패면 받은 날을 남기지 않고, 받는 동안 바꾼 아이디를 되돌리지 않음 ─────────────
class TestLawPartialAndOverlap(unittest.TestCase):
    def test_partial_failure_keeps_auto_check(self):
        import shutil
        import tempfile
        from ceo_report import lawwatch
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from test_lawwatch import fake
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        lawwatch.save_oc(d, "me")
        class Any(dict):
            def get(self, k, default=None):
                return "조문 … 100분의 7"
        good = fake(Any())
        calls = []

        def half(url, timeout=0):
            calls.append(url)
            if len(calls) % 3 == 0:
                raise OSError("끊김")
            return good(url, timeout)
        rows = lawwatch.check(d, 2026, D(2026, 7, 2), half)
        self.assertTrue(any(r[2] == "실패" for r in rows) and any(r[2] not in ("실패", "못 찾음") for r in rows))
        self.assertEqual(lawwatch.load(d).get("last", ""), "")
        self.assertTrue(lawwatch.due(d, D(2026, 7, 3)))   # 그달 안에 다시 해 봄

    def test_oc_saved_during_check_survives(self):
        import shutil
        import tempfile
        from ceo_report import lawwatch
        from test_lawwatch import fake
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        lawwatch.save_oc(d, "old")
        good = fake({})
        state = {"done": False}

        def opener(url, timeout=0):
            if not state["done"]:   # 받는 중에 사용자가 아이디를 바꿈
                state["done"] = True
                lawwatch.save_oc(d, "new")
            return good(url, timeout)
        lawwatch.check(d, 2026, D(2026, 7, 2), opener)
        self.assertEqual(lawwatch.load(d)["oc"], "new")


# ───────────── 2차 P2-18: 구형 엑셀의 칸 좌표가 비정상으로 크면 멈추지 않고 읽기 오류 ─────────────
class TestXlsHugeGridRefused(unittest.TestCase):
    def test_far_cells(self):
        import shutil
        import tempfile
        from ceo_report import xls
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import xls_fixture as X
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        p = X.write_xls(os.path.join(d, "a.xls"), [X.number(0, 0, 1.0), X.number(0, 60000, 2.0)], [])
        with self.assertRaises(xls.XlsError) as cm:
            xls.read_xls(p)
        self.assertIn("지나치게 큼", str(cm.exception))
        p = X.write_xls(os.path.join(d, "b.xls"), [X.number(0, 0, 1.0), X.number(65000, 200, 2.0)], [])
        with self.assertRaises(xls.XlsError):
            xls.read_xls(p)
        p = X.write_xls(os.path.join(d, "c.xls"), [X.number(0, 0, 1.0), X.number(3, 2, 2.0)], [])
        self.assertEqual(len(xls.read_xls(p)), 4)


# ───────────── 2차 P5-10: 작업 중에는 Enter 로 저장하지 않음 ─────────────
class TestEnterBlockedWhileBusy(unittest.TestCase):
    def test_enter(self):
        try:
            from ceo_report import gui
        except ImportError:
            self.skipTest("tkinter 없음")
        said, ran, bound = [], [], {}

        class W(object):
            def bind(self, ev, fn):
                bound[ev] = fn

        class Fake(object):
            busy = True

            def say(self, t):
                said.append(t)
        f = Fake()
        gui.Window._enter(f, [W()], lambda: ran.append(1))
        self.assertEqual(bound["<Return>"](None), "break")
        self.assertEqual(ran, [])
        self.assertTrue(said)
        f.busy = False
        bound["<Return>"](None)
        self.assertEqual(ran, [1])


# ───────────── 2차 P1-15: 인트라넷 쪽 이동을 못 알아보면 일부만 읽고 '완료'하지 않음 ─────────────
class TestIntranetPagingNotSilentlyPartial(unittest.TestCase):
    def test_script_only_page_numbers_stop(self):
        from test_intranet import collect_raises, intranet, payment_page, prow, site_routes
        routes = site_routes(extra={("GET", "/payment/index"): (200, {}, payment_page(
            [prow(5101), prow(5102)], links=[("javascript:goPage(2)", "2"), ("#", "3")]))})
        exc, _ = collect_raises(self, routes)
        self.assertIsInstance(exc, intranet().StructureMismatch)
        self.assertIn("스크립트", str(exc))

    def test_new_page_name_on_second_page_stops(self):
        from test_intranet import collect_raises, intranet, payment_page, prow, site_routes
        routes = site_routes(extra={
            ("GET", "/payment/index"): (200, {}, payment_page([prow(5101)], links=[("/payment/index?page=2", "2")])),
            ("GET", "/payment/index?page=2"): (200, {}, payment_page(
                [prow(5102)], links=[("/payment/index?page=1", "1"), ("/payment/index?blockno=3", "3")])),
        })
        exc, _ = collect_raises(self, routes)
        self.assertIsInstance(exc, intranet().StructureMismatch)
        self.assertIn("2쪽에서 처음 보는", str(exc))

    def test_script_next_link_is_flagged(self):
        from test_intranet import PASSWORD, USER, intranet, make_fake_opener, payment_page, prow, site_routes
        routes = site_routes(extra={
            ("GET", "/payment/index"): (200, {}, payment_page(
                [prow(5101)], links=[("/payment/index?page=2", "2"), ("javascript:nextBlock()", "다음")])),
            ("GET", "/payment/index?page=2"): (200, {}, payment_page([prow(5102)], links=[("/payment/index?page=1", "1")])),
        })
        opener, _ = make_fake_opener(routes)
        diag = []
        res = intranet().collect(opener, USER, PASSWORD, diag=diag)
        self.assertEqual(len(res.payments), 2)
        self.assertTrue(any(x.startswith("[확인]") and "다음" in x for x in diag), diag)


# ───────────── 2차 P1-18: 로그인 성공이 확인된 계정만 기억 ─────────────
class TestRememberOnlyVerifiedLogin(unittest.TestCase):
    def test_codes(self):
        try:
            from ceo_report import gui
        except ImportError:
            self.skipTest("tkinter 없음")
        from unittest import mock
        from ceo_report import credstore

        class V(object):
            def __init__(self, v):
                self.v = v

            def get(self):
                return self.v

            def set(self, v):
                self.v = v

        class Fake(object):
            remember, uid, pw = V(True), V("가상"), V("비번")
            paths = type("P", (), {"input": "/없는곳"})()
            said = []

            def say(self, t):
                self.said.append(t)
        for rc, saved in ((5, False), (3, False), (6, False), (0, True), (7, True)):
            with mock.patch.object(credstore, "save") as sv:
                gui.Window.after_collect(Fake(), rc)
                self.assertEqual(sv.called, saved, rc)


# ───────────── 2차 P2-11: 반복 지급은 날짜가 가장 가까운 일정 줄과 짝지음 ─────────────
class TestRecurringScheduleNearestPair(unittest.TestCase):
    def test_unpaid_earlier_week_stays(self):
        import csv
        import shutil
        import tempfile
        from ceo_report import review_checks as RC
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with open(os.path.join(tmp, RC.SCHEDULE), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["예정일", "입출금", "금액", "확정여부", "분류", "프로젝트번호", "거래처", "근거", "비고"])
            w.writerow(["2026-11-05", "출금", "200000", "확정", "기타지급", "", "가상렌탈", "매주", "첫 주"])
            w.writerow(["2026-11-12", "출금", "200000", "확정", "기타지급", "", "가상렌탈", "매주", "둘째 주"])
        J = [{"date": D(2026, 11, 12), "no": "7", "account_code": "10300", "debit": None, "credit": 200000, "vendor": "가상렌탈",
              "vendor_norm": "가상렌탈", "type": "일반"}]
        RC.archive_paid_schedule(tmp, J, D(2026, 11, 13))

        def notes(name):
            with open(os.path.join(tmp, name), encoding="utf-8-sig") as f:
                return [r["비고"] for r in csv.DictReader(f)]
        self.assertEqual(notes(RC.SCHEDULE), ["첫 주"])     # 아직 안 나간 첫 주는 남는다 (예전엔 첫 주가 둘째 주 출금을 가져갔음)
        self.assertEqual(notes(RC.ARCHIVE), ["둘째 주"])


# ───────────── 2차 P5-12: 변환 도중 들어온 자료는 다음에 '새 자료' ─────────────
class TestDataDuringConvertIsNew(unittest.TestCase):
    def test_seconds(self):
        import shutil
        import tempfile
        from ceo_report import app, checklist, winstate
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        P = app.Paths(tmp)
        os.makedirs(P.input, exist_ok=True)
        os.makedirs(P.wehago, exist_ok=True)
        start = dt.datetime(2026, 11, 15, 10, 0, 50)
        checklist.save_convert_items(P.input, [], now=start)
        p = os.path.join(P.convert_file if hasattr(P, "convert_file") else P.input, checklist.CONVERT_FILE)
        t = (start + dt.timedelta(seconds=40)).timestamp()   # 변환이 같은 분 안에 끝남
        os.utime(p, (t, t))

        def put(name, when):
            q = os.path.join(P.wehago, name)
            with open(q, "w", encoding="utf-8") as f:
                f.write("{}")
            os.utime(q, (when.timestamp(), when.timestamp()))
        put("261115 분개장 자동수집.json", dt.datetime(2026, 11, 15, 10, 0, 30))   # 변환 전에 받음
        self.assertEqual(winstate.steps(P, dirs=[])["new_since"], [])
        put("261115 자금계획 자동수집.json", dt.datetime(2026, 11, 15, 10, 0, 55))   # 변환 도중 받음
        self.assertEqual(winstate.steps(P, dirs=[])["new_since"], ["자금계획서"])


# ───────────── 2차 P2-2·P6-5: 다른 곳에서 변환 중이면 손으로 저장하지 않음 ─────────────
class TestManualSaveWaitsForConvert(unittest.TestCase):
    def test_locked(self):
        import shutil
        import tempfile
        try:
            from ceo_report import gui
        except ImportError:
            self.skipTest("tkinter 없음")
        from ceo_report import convert
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        said, ran = [], []

        class Fake(object):
            paths = type("P", (), {"input": tmp})()

            def say(self, t):
                said.append(t)
        f = Fake()
        save = gui._while_converting_wait(lambda self: ran.append(1))
        save(f)
        self.assertEqual(ran, [1])
        open(os.path.join(tmp, convert.LOCK_FILE), "w").close()
        save(f)
        self.assertEqual(ran, [1])
        self.assertIn("변환이 아직 끝나지 않았습니다", said[-1])
        self.assertIs(gui.Window.save_bank.__wrapped__.__name__, "save_bank")


# ───────────── 2차 P1-7: 저장 창이 쓰는 동안 들어온 파일을 대기열에서 잃지 않음 ─────────────
class TestSaverQueueKeepsNewFiles(unittest.TestCase):
    def test_flush_race(self):
        import json
        import shutil
        import subprocess
        if shutil.which("node") is None:
            self.skipTest("node 없음")
        js = r'''
const src = require("fs").readFileSync(process.argv[1], "utf8");
const m = src.match(/async function pending\(\)[\s\S]*?\n}\n/);
const f = src.match(/async function flush\(ask\)[\s\S]*?\n}\n/);
let store = {pendingSaves: [{name: "a.json", text: "A"}]};
global.chrome = {storage: {local: {get: async (k) => ({[k]: JSON.parse(JSON.stringify(store[k] || []))}),
                                   set: async (o) => { Object.assign(store, JSON.parse(JSON.stringify(o))); }}},
                 runtime: {sendMessage: () => {}}};
global.writeToFolder = async (name) => {   // 앞 파일을 쓰는 동안 배경이 새 파일을 대기열에 넣는다
  store.pendingSaves = store.pendingSaves.concat([{name: "b.json", text: "B"}]);
  return "ok";
};
eval(m[0].replace("async function pending", "global.pending = async function") + f[0].replace("async function flush", "global.flush = async function"));
flush(false).then((r) => console.log(JSON.stringify({r, left: store.pendingSaves})));
'''
        out = subprocess.run(["node", "-e", js, os.path.join(ROOT, "chrome_extension", "saver.js")],
                             check=True, stdout=subprocess.PIPE).stdout.decode("utf-8")
        got = json.loads(out)
        self.assertEqual(got["r"], {"saved": 1, "left": 1})
        self.assertEqual([p["name"] for p in got["left"]], ["b.json"])

    def test_manifest_version(self):
        with open(os.path.join(ROOT, "chrome_extension", "manifest.json"), encoding="utf-8") as f:
            self.assertIn('"version": "0.9.5"', f.read())


# ───────────── 1차 E11: 지금 현황을 새로 못 만들면 예전 화면이 최신처럼 열리지 않음 ─────────────
class TestLiveFailureNotStale(unittest.TestCase):
    def test_failure_moves_old_and_writes_notice(self):
        import tempfile
        from unittest import mock
        from ceo_report import app, live
        tmp = tempfile.mkdtemp()
        out, inp = os.path.join(tmp, "out"), os.path.join(tmp, "in")
        os.makedirs(out)
        os.makedirs(inp)
        with open(os.path.join(out, live.FILE), "w", encoding="utf-8") as f:
            f.write("<title>지금 현황</title>예전 숫자 123")
        paths = app.Paths(tmp) if hasattr(app, "Paths") else type("P", (), {"input": inp, "output": out})()
        paths.input, paths.output = inp, out
        said = []
        with mock.patch.object(live, "build", side_effect=PermissionError("쓰기 막힘")):
            self.assertIsNone(app.build_live(paths, said.append))
        self.assertTrue(any(s.startswith("[확인] 지금 현황 화면을 새로 만들지 못함") for s in said), said)
        with open(os.path.join(out, live.FILE), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("새로 만들지 못했습니다", page)
        self.assertNotIn("예전 숫자", page)
        self.assertTrue(live.is_failed_page(os.path.join(out, live.FILE)))
        with open(os.path.join(out, live.STALE_FILE), encoding="utf-8") as f:
            self.assertIn("예전 숫자 123", f.read())
        # 다시 실패해도 '지난판'을 안내 페이지로 덮지 않는다
        with mock.patch.object(live, "build", side_effect=OSError("또")):
            app.build_live(paths, said.append)
        with open(os.path.join(out, live.STALE_FILE), encoding="utf-8") as f:
            self.assertIn("예전 숫자 123", f.read())

    def test_open_rebuilds_when_older_than_convert(self):
        import tempfile
        import time
        from unittest import mock
        try:
            from ceo_report import gui
        except ImportError:
            self.skipTest("tkinter 없음")
        from ceo_report import app, live, winstate
        tmp = tempfile.mkdtemp()
        out, inp = os.path.join(tmp, "out"), os.path.join(tmp, "in")
        os.makedirs(out)
        os.makedirs(inp)
        path = os.path.join(out, live.FILE)
        with open(path, "w", encoding="utf-8") as f:
            f.write("<title>지금 현황</title>")
        old = time.time() - 3600
        os.utime(path, (old, old))
        built, opened = [], []

        class Fake:
            paths = type("P", (), {"input": inp, "output": out})()
            say = staticmethod(lambda s: None)
            asof = type("V", (), {"get": staticmethod(lambda: "")})()
        with mock.patch.object(winstate, "convert_time", return_value=dt.datetime.now()), \
                mock.patch.object(app, "build_live", side_effect=lambda *a, **k: built.append(1)), \
                mock.patch.object(gui, "open_path", side_effect=opened.append):
            gui.Window.open_live(Fake())
            self.assertEqual(built, [1])
            os.utime(path, None)   # 변환 뒤에 만든 화면이면 그대로 연다
            gui.Window.open_live(Fake())
            self.assertEqual(built, [1])
            live.mark_failed(out, "시험")   # '못 만듦' 안내면 다시 만들어 본다
            gui.Window.open_live(Fake())
            self.assertEqual(built, [1, 1])
        self.assertEqual(len(opened), 3)


# ───────────── 1차 D6: 같은 카드 화면 응답이 두 번 저장돼도 한 번만 셈 ─────────────
class TestCardScreenDuplicateResponse(unittest.TestCase):
    def test_same_response_twice(self):
        import json
        import shutil
        import tempfile
        from ceo_report import screen_tax
        folder = tempfile.mkdtemp()
        try:
            resp = {"path": "/smarta/saac0105/6/", "data": {"data": [
                {"da_sbook": "20261005", "nm_ctrade": "[00501]카드_0001", "cd_ctrade": "00501", "mn_total": 2500000}]}}
            other = {"path": "/smarta/saac0105/6", "data": {"data": [
                {"da_sbook": "20261006", "nm_ctrade": "[00501]카드_0001", "cd_ctrade": "00501", "mn_total": 1000}]}}
            doc = {"종류": "결산", "화면코드": "SAAC0105", "수집시각": "2026-11-13 09:00",
                   "응답": [resp, json.loads(json.dumps(resp)), other]}
            with open(os.path.join(folder, "261113 결산_신용카드 자동수집.json"), "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False)
            real, _ = screen_tax.card_usage(folder)
        finally:
            shutil.rmtree(folder)
        self.assertEqual(real["code:501"], [(dt.date(2026, 10, 5), 2500000), (dt.date(2026, 10, 6), 1000)])


# ───────────── 1차 D3: 이름 같고 코드 다른 거래처 → 입금 배분이 섞일 수 있음을 알림 ─────────────
class TestSameNameDifferentCodeWarned(unittest.TestCase):
    def test_note(self):
        from test_convert_review_fixes import build_inv, receipt, sale
        d1, d2 = dt.date(2026, 9, 1), dt.date(2026, 9, 20)
        a = receipt(d2, 41, 11000000)
        for r in a:
            r["vendor_code"] = "002"
        sales = [sale(d1, "가상고객A", 10000000), sale(d1, "가상고객A", 10000000)]
        from test_convert_review_fixes import jl
        j = [dict(jl(d1, 1, "10800", "수입수수료미수금", 11000000, None, "가상고객A"), vendor_code="001")] + a
        t = build_inv(j, sales)
        hit = [n for n in t.notes if n.startswith("[확인] 이름이 같고 거래처코드가 다른 거래처 1곳")]
        self.assertEqual(len(hit), 1, t.notes)
        self.assertIn("코드 1·2", hit[0])
        t = build_inv(a, sales)   # 코드가 하나면 알림 없음
        self.assertFalse([n for n in t.notes if "거래처코드가 다른" in n])


# ───────────── 1차 D17: 수집 때 건너뛴 프로젝트 줄 수가 변환·확인할 것까지 감 ─────────────
class TestSkippedProjectsCarried(unittest.TestCase):
    def test_snapshot_keeps_count_and_convert_warns(self):
        import shutil
        import tempfile
        from ceo_report import snapshot
        root = tempfile.mkdtemp()
        try:
            at = dt.datetime(2026, 11, 10, 9, 0, 0)
            path = snapshot.write_snapshot(root, at, [], [], skipped=2)
            snap = snapshot.read_snapshot(path)
            self.assertEqual(snapshot.skipped_projects(snap), 2)
            cfg = convert.Config(convert.DEFAULT_CONFIG)
            _, warn = convert.snapshot_lines(snap, "", dt.date(2026, 11, 10), cfg)
            self.assertIn("읽지 못한 줄 2건", warn or "")
            items = checklist.convert_items([], [], [snapshot.SKIP_NOTE % 2])
            self.assertEqual(len(items), 1)
            self.assertIn("읽지 못한 줄 2건", items[0]["detail"])
            path2 = snapshot.write_snapshot(root, at + dt.timedelta(seconds=1), [], [])   # 건너뛴 줄이 없으면 그대로
            snap2 = snapshot.read_snapshot(path2)
            self.assertEqual(snapshot.skipped_projects(snap2), 0)
            self.assertIsNone(convert.snapshot_lines(snap2, "", dt.date(2026, 11, 10), cfg)[1])
        finally:
            shutil.rmtree(root)


# ───────────── 1차 B11: 급여 부서 정정(+·−)으로 0이 된 부서엔 사람을 세지 않음 ─────────────
class TestHeadsIgnoreCorrectedDept(unittest.TestCase):
    def test_correction(self):
        from ceo_report import convert_pl
        from test_dept import CFG, OCT, Books, line
        books = Books([
            line(OCT, "80200", "직원급여(판)", 3_000_000, dept="기획1팀", emp="가"),
            line(OCT, "80200", "직원급여(판)", -3_000_000, dept="기획1팀", emp="가"),   # 정정
            line(OCT, "80200", "직원급여(판)", 3_000_000, dept="기획2팀", emp="가"),
            line(OCT, "80200", "직원급여(판)", 2_000_000, dept="기획1팀", emp="나"),
        ])
        rows = dict((r["부서"], r) for r in convert_pl.build_dept(books, CFG).rows)
        self.assertEqual((rows["기획1팀"]["인원"], rows["기획2팀"]["인원"]), ("1", "1"))
        self.assertEqual(rows["기획1팀"]["급여"], "2000000")
