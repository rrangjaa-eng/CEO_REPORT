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
        변환.main(["--기준일", "2026-01-02", "--입력", os.path.join(t, "입력"), "--수집폴더", os.path.join(t, "수집")])
        with open(os.path.join(t, "입력", "변환결과.txt"), encoding="utf-8-sig") as f:
            first = f.readline()
        m = re.match(r"변환 시각 (\S+ \S+) · 기준일 2026-01-02", first)
        self.assertIsNotNone(m, first)
        when = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        self.assertGreaterEqual(when, before)
        self.assertLessEqual(when, dt.datetime.now())


if __name__ == "__main__":
    unittest.main()
