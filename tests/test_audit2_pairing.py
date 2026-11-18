"""2차 전수조사 A1 (2026-11-18): 나눠 올린 지급요청·원천세 뗀 요청·법인카드 요청·금액이 조금 다른 지급을 장부 원가 줄과 짝짓기."""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ceo_report.convert_projects import _pair_bundles, _subset  # noqa: E402


def G(project, vendor, supply, vat, state="지급완료", paid=dt.date(2026, 10, 30), no="50001", card=False):
    line = {"vendor": vendor, "memo": "", "account": ""}
    return {"project": project, "vendor_norm": vendor, "supply": supply, "vat": vat, "state": state, "paid_day": paid,
            "day": dt.date(2026, 8, 31), "no": no, "basis": "WEHAGO", "lines": [line], "card": card, "firm": True,
            "vendor_text": vendor}


def R(no, project, vendor, amount, status="approved", reg=dt.datetime(2026, 9, 1), day=dt.date(2026, 9, 25)):
    return {"번호": str(no), "code": project, "vendor": vendor, "amount": amount, "status": status, "registered": reg,
            "date": day, "request_date": day, "name": "", "status_text": ""}


def run(groups, rqs):
    return _pair_bundles([(r, False, None) for r in rqs], groups, set(), {}, {})


class Bundles(unittest.TestCase):
    def test_split_requests_equal_one_book_line(self):
        g = G("26220", "인하모니네트워크", 10560000, 1056000)
        out, notes = run([g], [R(481, "26220", "인하모니네트워크", 1958000), R(482, "26220", "인하모니네트워크", 9570000),
                               R(609, "26220", "인하모니네트워크", 88000), R(700, "26220", "인하모니네트워크", 500000)])
        self.assertEqual(sorted(out), ["481", "482", "609"])
        self.assertTrue(all(v["paid"] for v in out.values()))
        self.assertIn("지급요청 481 · 지급요청 482 · 지급요청 609 (나눠 올린 요청 합계로 짝지음)", g["basis"])

    def test_unapproved_request_is_not_paired_with_a_paid_line(self):
        g = G("26220", "가", 3000, 300)
        out, _ = run([g], [R(1, "26220", "가", 1100), R(2, "26220", "가", 2200, status="pending")])
        self.assertEqual(out, {})

    def test_paid_before_registration_is_another_payment(self):
        g = G("26220", "가", 3000, 300, paid=dt.date(2026, 8, 1))
        out, _ = run([g], [R(1, "26220", "가", 1100), R(2, "26220", "가", 2200)])
        self.assertEqual(out, {})

    def test_withholding_requests_under_one_income_line(self):
        g = G("26223", "사업소득", 1434120, 0)
        out, _ = run([g], [R(567, "26223", "어반레스트_강인선", 386800), R(575, "26223", "아나운서_최미영", 1000000)])
        self.assertEqual(sorted(out), ["567", "575"])
        self.assertIn("원천세 3.3% 떼기 전 금액 합계로 짝지음", g["basis"])

    def test_withholding_bundle_needs_a_single_candidate_line(self):
        a, b = G("26223", "사업소득", 2000000, 0), G("26223", "사업소득", 2000000, 0, no="50002")
        out, _ = run([a, b], [R(1, "26223", "김", 967000), R(2, "26223", "배", 967000)])
        self.assertEqual(out, {})

    def test_card_request_ignores_the_registration_date(self):
        g = G("26036", "호텔롯데", 9090910, 909090, state="카드결제완료", paid=dt.date(2026, 4, 24), card=True)
        out, _ = run([g], [R(83, "26036", "법인카드(1842)", 10000000, reg=dt.datetime(2026, 5, 2))])
        self.assertEqual(sorted(out), ["83"])

    def test_same_vendor_small_difference_is_flagged(self):
        g = G("26102", "펀미디어", 5730000, 573000)
        out, notes = run([g], [R(474, "26102", "펀미디어", 6306000)])
        self.assertEqual(sorted(out), ["474"])
        self.assertTrue(any(n.startswith("[확인] 지급요청 474") for n in notes))

    def test_small_difference_with_two_candidates_is_left(self):
        a, b = G("26102", "펀미디어", 5730000, 573000), G("26102", "펀미디어", 5731000, 573100, no="50002")
        out, _ = run([a, b], [R(474, "26102", "펀미디어", 6306000)])
        self.assertEqual(out, {})

    def test_same_day_payment_with_a_rate_difference(self):
        g = G("26047", "해외매입", 18730410, 0, paid=dt.date(2026, 4, 3))
        out, notes = run([g], [R(5, "26047", "HSKC", 18581090, reg=dt.datetime(2026, 4, 1), day=dt.date(2026, 4, 3))])
        self.assertEqual(sorted(out), ["5"])
        self.assertTrue(any("환율" in n for n in notes))

    def test_far_amount_or_day_is_left(self):
        g = G("26047", "해외매입", 18730410, 0, paid=dt.date(2026, 4, 20))
        out, _ = run([g], [R(5, "26047", "HSKC", 18581090, reg=dt.datetime(2026, 4, 1), day=dt.date(2026, 4, 3))])
        self.assertEqual(out, {})

    def test_one_request_over_two_book_lines(self):
        a, b = G("26001", "가", 1000, 100), G("26001", "가", 2000, 200, no="50002")
        out, _ = run([a, b], [R(9, "26001", "가", 3300)])
        self.assertEqual(sorted(out), ["9"])
        self.assertIn("원가 줄 2개 합계로 짝지음", a["basis"])

    def test_subset_reports_more_than_one_combination(self):
        self.assertEqual(_subset([1, 2, 3], 3), ([0, 1], False))
        self.assertEqual(_subset([1, 2, 1, 2], 3), ([0, 1], True))
        self.assertEqual(_subset([5], 5), (None, False))


if __name__ == "__main__":
    unittest.main()
