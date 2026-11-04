"""장부채무.csv (2026-11-04 점검 A1·A2): 실제 분개장 모양(가짜 이름·금액)으로 만든 줄만 쓴다.

실제 분개장에서 확인한 모양 (2026-11-04, PC 파일 읽기만):
  · 거래처Code 는 숫자 5자리, 자금계획서 [코드] 는 앞에 0을 하나 더 붙인 6자리 (뒤 5자리가 같음)
  · 정기예금(10500)은 상품마다 거래처가 따로 있고 적요에 만기일이 없음 ('입금시 보통대체' / '만기해지' / '중도해지')
  · 차입금(29300) 적요에 '[만기일자:YYYY.MM.DD]', 할부는 회차만
  · 전기이월 줄이 없음
"""
import datetime as dt
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import debts, fundplan, convert  # noqa: E402
from ceo_report.wehago import norm_code  # noqa: E402

D = dt.date


def ln(date, code, debit, credit, vendor, vcode, memo, account="계정"):
    return {"date": date, "account_code": code, "account": account, "debit": debit, "credit": credit,
            "vendor": vendor, "vendor_code": vcode, "memo": memo, "no": "00001"}


def books(lines, ref=D(2026, 11, 4)):
    return types.SimpleNamespace(journal=lines, book_date=ref, state="ok")


CFG = dict(convert.DEFAULT_CONFIG)


class TestNormCode(unittest.TestCase):
    def test_plan_code_equals_journal_code(self):
        self.assertEqual(norm_code("000101"), norm_code("00101"))
        self.assertNotEqual(norm_code("000101"), norm_code("01101"))
        self.assertEqual(norm_code(" 00000 "), "0")
        self.assertEqual(norm_code(""), "")
        self.assertEqual(norm_code("V001"), "V001")


class TestBuild(unittest.TestCase):
    def rows(self, lines):
        rows, note = debts.build(books(lines), CFG)
        return {(r["구분"], r["거래처"]): r for r in rows}, note

    def test_deposit_without_memo_date_uses_last_closed_term(self):
        got, _ = self.rows([
            ln(D(2026, 1, 13), "10500", 200000000, None, "가상은행260113", "00922", "정기예금입금시 보통대체"),
            ln(D(2026, 2, 5), "10500", None, 50000000, "가상은행260113", "00922", "정기예금중도해지"),
            ln(D(2026, 2, 13), "10500", None, 150000000, "가상은행260113", "00922", "정기예금만기해지"),
            ln(D(2026, 8, 28), "10500", 200000000, None, "가상은행260828", "01317", "정기예금입금시 보통대체"),
            ln(D(2026, 9, 28), "10500", None, 200000000, "가상은행260828", "01317", "정기예금만기해지"),
            ln(D(2026, 10, 20), "10500", 100000000, None, "가상은행261020", "01400", "정기예금입금시 보통대체"),
        ])
        r = got[("정기예금", "가상은행261020")]
        self.assertEqual(r["잔액"], "100000000")
        self.assertEqual(r["만기일"], "2026-11-20")        # 가장 최근 해지된 상품 기간 31일
        self.assertIn("31일로 추정", r["만기근거"])
        self.assertNotIn(("정기예금", "가상은행260113"), got)  # 다 해지된 것은 0이라 빠짐

    def test_monthly_installment_gets_no_guessed_due(self):
        got, _ = self.rows([
            ln(D(2026, 8, 28), "10500", 200000000, None, "가상은행260828", "01317", "정기예금입금시 보통대체"),
            ln(D(2026, 9, 28), "10500", None, 200000000, "가상은행260828", "01317", "정기예금만기해지"),
            ln(D(2026, 9, 28), "10500", 300000, None, "가상공제부금", "00257", "가상공제부금_18회차"),
            ln(D(2026, 10, 26), "10500", 300000, None, "가상공제부금", "00257", "가상공제부금_19회차"),
        ])
        r = got[("정기예금", "가상공제부금")]
        self.assertEqual((r["잔액"], r["만기일"]), ("600000", ""))   # 만기 모름: 쓸 수 없는 돈으로만

    def test_loan_due_from_memo_and_installment_repaid(self):
        got, note = self.rows([
            ln(D(2026, 5, 11), "29300", None, 300000000, "가상대출_보증", "01107", "003-일시-[만기일자:2027.04.21]"),
            ln(D(2026, 9, 21), "29300", 1226380, None, "가상캐피탈", "00679", "차량오토할부_원리금납부12/60"),
            ln(D(2026, 10, 21), "29300", 1232000, None, "가상캐피탈", "00679", "차량오토할부_원리금납부13/60"),
        ])
        loan = got[("차입금", "가상대출_보증")]
        self.assertEqual((loan["잔액"], loan["만기일"], loan["만기근거"]), ("300000000", "2027-04-21", "적요"))
        self.assertEqual(got[("차입금", "가상캐피탈")]["잔액"], "-2458380")
        self.assertEqual(loan["전기이월"], "없음")
        self.assertIn("전기이월 없음", note)

    def test_opening_lines_mark_balance_complete(self):
        got, note = self.rows([ln(D(2026, 1, 1), "25300", None, 5000000, "가상상사", "00001", "전기이월")])
        self.assertEqual(got[("미지급금", "가상상사")]["전기이월"], "있음")
        self.assertNotIn("전기이월 없음", note)


class TestCompare(unittest.TestCase):
    def debts(self, opening=False):
        base = {"code": "", "account": "", "date": "2026-11-04", "due": "", "due_basis": "", "opening": opening}
        return [dict(base, kind="미지급금", vcode="00101", vendor="가상상사", balance=5000000),
                dict(base, kind="미지급금", vcode="00224", vendor="가상스튜디오", balance=-2000000),
                dict(base, kind="차입금", vcode="01107", vendor="가상대출", balance=300000000, due="2027-04-21"),
                dict(base, kind="차입금", vcode="00679", vendor="가상캐피탈", balance=-2458380)]

    def test_plan_code_with_extra_zero_matches(self):
        ev = {"io": "out", "amount": 3000000, "date": D(2026, 11, 20), "desc": "다른 이름", "vendor_code": "000101"}
        got = debts.compare(self.debts(), [ev], D(2026, 11, 4))
        self.assertEqual([(r["vendor"], r["left"], r["by_name"]) for r in got["unscheduled"]], [("가상상사", 2000000, False)])
        self.assertEqual(got["loan_total"], 300000000)
        self.assertEqual([d["vendor"] for d in got["repaid_loans"]], ["가상캐피탈"])
        self.assertFalse(got["opening"])


    def test_plan_bigger_than_book_is_flagged(self):
        """자금계획서 미지급금 지급 예정 > 장부 잔액 = 이중 계상 신호 (실제 자료 2026-11-04: 예정이 잔액의 정확히 2배)."""
        evs = [{"io": "out", "amount": 6000000, "date": D(2026, 11, 20), "desc": "가상상사", "vendor_code": "00101",
                "cat": "자금계획서 미지급금 지급"},
               {"io": "out", "amount": 700000, "date": D(2026, 11, 21), "desc": "가상스튜디오", "vendor_code": "00224",
                "cat": "자금계획서 미지급금 지급"},
               {"io": "out", "amount": 900000, "date": D(2026, 11, 22), "desc": "급여", "vendor_code": "00999",
                "cat": "자금계획서 인건비"}]   # 미지급금 지급이 아닌 줄은 보지 않는다
        got = debts.compare(self.debts(), evs, D(2026, 11, 4))
        self.assertEqual([(r["vcode"], r["over"]) for r in got["over"]], [("101", 1000000), ("224", 700000)])
        self.assertEqual(got["over_total"], 1700000)
        old = [dict(e, date=D(2026, 11, 1)) for e in evs]   # 기준일 이전 줄은 지난 것
        self.assertEqual(debts.compare(self.debts(), old, D(2026, 11, 4))["over"], [])


class TestSettleByCode(unittest.TestCase):
    def test_code_decides_even_when_names_differ(self):
        j = [ln(D(2026, 11, 3), "25300", 990000, None, "가상상사 본점", "00001", "지급", account="미지급금")]
        rows = [{"예정일": "2026-11-06", "입출금": "지급", "거래처": "가상상사", "거래처코드": "000001", "금액": 990000}]
        fundplan.settle(rows, books(j, D(2026, 11, 4)), D(2026, 11, 4))
        self.assertEqual(rows[0]["상태"], "이미 지급")

    def test_different_code_same_name_does_not_match(self):
        j = [ln(D(2026, 11, 3), "25300", 990000, None, "가상상사", "00002", "지급", account="미지급금")]
        rows = [{"예정일": "2026-11-06", "입출금": "지급", "거래처": "가상상사", "거래처코드": "000001", "금액": 990000}]
        fundplan.settle(rows, books(j, D(2026, 11, 4)), D(2026, 11, 4))
        self.assertEqual(rows[0]["상태"], "예정")


if __name__ == "__main__":
    unittest.main()
