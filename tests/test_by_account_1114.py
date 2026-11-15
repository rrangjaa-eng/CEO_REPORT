"""적요 대신 계정·거래처로 판단 (2026-11-14 사용자 "적요에 품목명으로 넣지 않고 계정과목으로 판단할 게 있으면 그렇게 해").

정기예금(10500 계정·같은 전표 통장 입금으로 해지 판단), 원천세 종류(같은 전표 급여 계정·'사업소득' 거래처),
통장 줄만 있는 전표(확인할 것), 중복 의심(관리항목 프로젝트로 먼저). 합성 자료만.
"""
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from ceo_report import cashflow, checklist, filing, tax  # noqa: E402
from ceo_report import review_checks as RC  # noqa: E402

D = dt.date


def ln(day, no, code, debit=None, credit=None, vendor="", memo="", account="", **kw):
    x = {"date": day, "no": no, "account_code": code, "account": account, "debit": debit, "credit": credit,
         "vendor": vendor, "vendor_code": "", "memo": memo}
    x.update(kw)
    return x


class TestDepositByAccount(unittest.TestCase):
    def test_deposit_without_memo_word_is_found_and_maturity_by_bank_line(self):
        j = [ln(D(2026, 5, 1), "1", "10500", debit=50_000_000, vendor="가상은행"),
             ln(D(2026, 5, 1), "1", "10300", credit=50_000_000, vendor="가상은행"),
             # 해지: 적요에 '만기' 없음, 같은 전표 통장 입금
             ln(D(2026, 8, 1), "2", "10500", credit=50_000_000, vendor="가상은행"),
             ln(D(2026, 8, 1), "2", "10300", debit=50_000_000, vendor="가상은행"),
             ln(D(2026, 9, 1), "3", "10500", debit=30_000_000, vendor="가상은행"),
             ln(D(2026, 9, 1), "3", "10300", credit=30_000_000, vendor="가상은행")]
        rows = [r for r in tax.deposits(j, D(2026, 10, 1)) if r["세목"] == tax.DEPOSIT_IN]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["금액"], "30000000")
        self.assertEqual(rows[0]["납부예정일"], "2026-12-01")   # 지난 예금 3개월 간격을 씀
        self.assertIn("지난 예금 1건", rows[0]["근거"])

    def test_savings_words_in_same_account_are_left_out(self):
        j = [ln(D(2026, 9, 1), "1", "10500", debit=1_000_000, vendor="가상공제회", memo="노란우산공제"),
             ln(D(2026, 9, 1), "1", "10300", credit=1_000_000)]
        self.assertEqual(tax.deposits(j, D(2026, 10, 1)), [])


class TestWithholdingKindBySlip(unittest.TestCase):
    def test_kind_from_salary_account_and_vendor_not_memo(self):
        j = [ln(D(2026, 10, 25), "1", "80200", debit=3_000_000, account="급여"),
             ln(D(2026, 10, 25), "1", "25400", credit=90_000, account="예수금", vendor="가상세무서", memo="10월분"),
             ln(D(2026, 10, 25), "1", "10300", credit=2_910_000),
             ln(D(2026, 10, 26), "2", "83100", debit=1_000_000, account="지급수수료", vendor="사업소득"),
             ln(D(2026, 10, 26), "2", "25400", credit=33_000, account="예수금", vendor="가상세무서", memo="강사료"),
             ln(D(2026, 10, 26), "2", "10300", credit=967_000)]
        ev, _ = filing.scan(j)
        self.assertEqual(ev[(2026, 10)]["근로"], 90_000)
        self.assertEqual(ev[(2026, 10)]["사업"], 33_000)

    def test_memo_still_used_when_slip_says_nothing(self):
        j = [ln(D(2026, 10, 26), "2", "25400", credit=8_800, account="예수금", vendor="가상세무서", memo="기타소득 원천세"),
             ln(D(2026, 10, 26), "2", "10300", credit=-8_800)]
        ev, _ = filing.scan(j)
        self.assertEqual(ev[(2026, 10)]["기타"], 8_800)

    def test_prize_by_account_name(self):
        j = [ln(D(2026, 10, 5), "3", "83900", debit=500_000, account="경품비", memo="행사 추첨"),
             ln(D(2026, 10, 5), "3", "10300", credit=500_000)]
        ev, _ = filing.scan(j)
        self.assertEqual(ev[(2026, 10)]["경품"], 500_000)


class TestCashOnlySlips(unittest.TestCase):
    def test_bank_only_slip_is_listed_and_goes_to_checklist(self):
        j = [ln(D(2026, 10, 10), "1", "10300", credit=1_200_000, vendor="가상카드"),
             ln(D(2026, 10, 11), "2", "10300", credit=500_000),
             ln(D(2026, 10, 11), "2", "25300", debit=500_000, vendor="가상거래처")]
        self.assertEqual(cashflow.cash_only_slips(j, ["10300"]), [(D(2026, 10, 10), "1", -1_200_000)])
        rows = cashflow.build_rows(j, ["10300"])
        self.assertTrue(any(r[1] == "현금" and r[2] == "카드" for r in rows), rows)   # 적요 없이 거래처로 카드
        note = "[확인] 통장 줄만 있는 전표 1건 (상대 계정 줄 없음): 2026-10-10 전표 1 -1,200,000원"
        items = checklist.convert_items({}, [], [note])
        self.assertEqual([i["kind"] for i in items], ["전표 입력"])


def dup(day, no, project, memo):
    return [ln(day, no, "82600", debit=1_100_000, vendor="가상업체", memo=memo, project_name=project, type="매입전표"),
            ln(day, no, "25300", credit=1_100_000, vendor="가상업체", memo=memo, project_name=project, type="매입전표")]


class TestDuplicateByProject(unittest.TestCase):
    def test_same_project_different_memo_stays_suspect(self):
        j = dup(D(2026, 10, 1), "1", "[26222] 가상행사", "현수막") + dup(D(2026, 10, 1), "2", "[26222] 가상행사", "배너")
        (_, _, _, why, ok), = RC.classify_duplicates(j)
        self.assertFalse(ok)
        self.assertIn("프로젝트 같음", why)

    def test_different_project_is_normal(self):
        j = dup(D(2026, 10, 1), "1", "[26222] 가상행사", "현수막") + dup(D(2026, 10, 1), "2", "[26223] 다른행사", "현수막")
        (_, _, _, why, ok), = RC.classify_duplicates(j)
        self.assertTrue(ok)
        self.assertIn("관리항목 프로젝트", why)

    def test_no_project_falls_back_to_memo(self):
        j = dup(D(2026, 10, 1), "1", "", "현수막") + dup(D(2026, 10, 1), "2", "", "배너")
        (_, _, _, why, ok), = RC.classify_duplicates(j)
        self.assertTrue(ok)
        self.assertIn("적요로 판단", why)


if __name__ == "__main__":
    unittest.main()
