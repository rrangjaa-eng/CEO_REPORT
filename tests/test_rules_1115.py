"""2026-11-15 규칙(안전·계산·보고·운영)을 번호대로 고정하는 시험. 프로젝트 메모리의 규칙 줄마다 '확인: 같은 번호'.

모두 가상 자료다 (실제 입력/·수집/ 폴더는 열지 않는다). 실제 자료에서 찾은 오류(R1·R2·R10 …)를 다시 만드는 모양을
가상 자료로 옮겼다: 고친 뒤에 다시 생기면 실패한다. 통과는 '이미 알고 막은 것'만 보증한다 (점검 방법 4).
"""
import datetime as dt
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
