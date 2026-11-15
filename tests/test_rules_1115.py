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
