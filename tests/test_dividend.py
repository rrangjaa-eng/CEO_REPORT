import datetime as dt
import os
import tempfile
import unittest

from ceo_report import dividend as dv


class Tax(unittest.TestCase):
    def test_basic_tax_brackets(self):
        self.assertEqual(dv.basic_tax(14_000_000), 840_000)
        self.assertEqual(dv.basic_tax(50_000_000), 6_240_000)
        self.assertEqual(dv.basic_tax(0), 0)

    def test_separate_tax_under_limit_is_15_4(self):
        add = dv.person_tax(50_000_000, 0, 20_000_000) - dv.person_tax(50_000_000, 0, 0)
        self.assertEqual(add, 3_080_000)   # 2천만 × 15.4%

    def test_over_limit_costs_more_for_high_earner(self):
        base = dv.person_tax(150_000_000, 0, 0)
        add = dv.person_tax(150_000_000, 0, 40_000_000) - base
        self.assertGreater(add, 40_000_000 * 0.154)

    def test_over_limit_never_below_withholding(self):   # 비교과세: 낮은 소득이어도 14% 밑으로는 안 내려감
        add = dv.person_tax(0, 0, 40_000_000) - dv.person_tax(0, 0, 0)
        self.assertGreaterEqual(add, int(40_000_000 * 0.154) - 1)


def folder(rows, wages=()):
    d = tempfile.mkdtemp()
    for r in rows:
        dv.save(d, *r)
    if wages:
        with open(os.path.join(d, "사원급여.csv"), "w", encoding="utf-8-sig") as f:
            f.write("연월,부서,사원명,급여\n" + "\n".join("%s,기획본부,%s,%d" % w for w in wages))
    return d


class Plan(unittest.TestCase):
    def test_minors_cap_and_ceo_wage(self):
        d = folder([("대표", "60", False, True, "", ""), ("자녀1", "20", True, False, "", ""), ("자녀2", "20", True, False, "", "")],
                   [("2026-%02d" % m, "대표", 10_000_000) for m in range(1, 11)])
        P = dv.plan(d, dt.date(2026, 11, 12), 500_000_000)
        ceo = P["people"][0]
        self.assertEqual(ceo["wage"], 120_000_000)   # 10달 → 12달로
        # 대표 60%가 2천만에 닿는 총액 = 33,333,333 → 1백만 단위 33,000,000
        self.assertEqual(P["best"], 33_000_000)
        self.assertTrue(any(t["best"] for t in P["table"]))

    def test_share_over_100_refused(self):
        d = folder([("가", "70", False, False, "", "")])
        with self.assertRaises(ValueError):
            dv.save(d, "나", "40", False, False, "", "")

    def test_no_shareholders(self):
        self.assertIsNone(dv.plan(tempfile.mkdtemp(), dt.date(2026, 1, 1), None))


def R(avail, cf_warn=False, tax=(), loans=()):
    asof = dt.date(2026, 11, 30)
    return {"asof": asof, "s2": {"periods": [{"end": dt.date(2026, 12, 31), "firm": {"avail": avail}}]},
            "tax": list(tax), "debts": {"loans": list(loans)}, "cf": None}


S = {"cur": {"미처분": (330_000_000, "예상", "")}}


FULL = {"큰지출": "없음", "급여변경": "없음", "주식증여": "없음", "퇴직금계획": "없음", "과밀억제": "예", "수도권": "예",
        "청년창업": "아니오", "신규창업": "예", "감면업종": "모름", "작년감면": "모름", "연구전담": "아니오"}


def ready(**extra):
    d = folder([("대표", "100", False, False, "", "")])
    vals = dict(FULL)
    vals.update(extra)
    dv.save_settings(d, vals)
    return d


class Advise(unittest.TestCase):
    def test_pay_when_cash_ok(self):
        A = dv.advise(R(200_000_000), S, {"best": 33_000_000}, ready())
        self.assertEqual(A["verdict"], "배당")
        self.assertEqual(A["amount"], 33_000_000)

    def test_carry_when_big_outflows(self):
        A = dv.advise(R(200_000_000, tax=[{"kind": "법인세", "due": dt.date(2027, 3, 31), "amount": 20_000_000}],
                        loans=[{"vendor": "기보", "due": "2027-04-21", "balance": 300_000_000}]), S, {"best": 33_000_000},
                      ready(대출연장="아니오"))
        self.assertEqual(A["verdict"], "이월")
        self.assertIn("배당 지급일까지", A["reasons"][0])

    def test_loan_assumed_extended_by_default(self):   # 사용자 2026-11-12: 대출은 계속 연장된다고 가정
        A = dv.advise(R(200_000_000, loans=[{"vendor": "기보", "due": "2027-04-21", "balance": 300_000_000}]), S,
                      {"best": 33_000_000}, ready())
        self.assertEqual(A["verdict"], "배당")
        self.assertTrue(any("연장된다고" in r for r in A["reasons"]))

    def test_missing_checklist_holds(self):
        A = dv.advise(R(200_000_000), S, {"best": 33_000_000}, folder([("대표", "100", False, False, "", "")]))
        self.assertEqual(A["verdict"], "보류")
        self.assertIn("큰 지출", A["reasons"][0])
        with self.assertRaises(ValueError):   # 큰 지출 '있음'이면 금액 필수
            ready(큰지출="있음")

    def test_bad_setting_value(self):
        with self.assertRaises(ValueError):
            dv.save_settings(tempfile.mkdtemp(), {"대출연장": "몰라"})

    def test_hold_when_surplus_unknown(self):
        A = dv.advise(R(200_000_000), {"cur": {"미처분": (None, "모름", "")}}, None, ready())
        self.assertEqual(A["verdict"], "보류")

    def test_sales_drop_means_carry(self):
        r = R(200_000_000)
        r["evid_month"] = dict(("2026-%02d" % m, (100_000_000 if m <= 7 else 50_000_000, 60_000_000 if m <= 7 else 30_000_000))
                               for m in range(1, 11))
        A = dv.advise(r, S, {"best": 33_000_000}, ready())
        self.assertEqual(A["verdict"], "이월")
        self.assertIn("매출 흐름", A["reasons"][0])

    def test_div_limit_reserve(self):
        self.assertEqual(dv.div_limit(110_000_000), 100_000_000)            # 이익준비금 10% 적립 몫
        self.assertEqual(dv.div_limit(110_000_000, 10_000_000, 5_000_000), 110_000_000)   # 이미 자본금 절반
        self.assertEqual(dv.div_limit(110_000_000, 10_000_000, 4_000_000), 109_000_000)   # 100만만 더 쌓으면 됨
        self.assertEqual(dv.div_limit(None), 0)

    def test_tax_due_after_payday_ignored_and_cut(self):
        tax = [{"kind": "법인세", "due": dt.date(2027, 3, 31), "amount": 50_000_000},
               {"kind": "법인세", "due": dt.date(2027, 8, 31), "amount": 50_000_000}]
        A = dv.advise(R(100_000_000, tax=tax), S, {"best": 90_000_000}, ready(법인세감면="20000000"))
        self.assertEqual(A["verdict"], "배당")
        self.assertEqual(A["amount"], 70_000_000)   # 1억 − (5천만 − 감면 2천만), 8월 중간예납은 지급일 뒤

    def test_big_outflow_within_year(self):
        A = dv.advise(R(100_000_000), S, {"best": 90_000_000}, ready(큰지출="있음", 큰지출금액="60000000", 큰지출시기="2027-06-01"))
        self.assertEqual(A["amount"], 40_000_000)
        A = dv.advise(R(100_000_000), S, {"best": 90_000_000}, ready(큰지출="있음", 큰지출금액="60000000", 큰지출시기="2028-06-01"))
        self.assertEqual(A["amount"], 90_000_000)   # 1년 넘어 뒤라 빼지 않음

    def test_retirement_keep_lowers_limit_and_cash(self):
        A = dv.advise(R(100_000_000), S, {"best": 90_000_000}, ready(퇴직금계획="있음", 퇴직금유보="30000000"))
        self.assertEqual(A["amount"], 70_000_000)
        self.assertTrue(any("퇴직금" in f[0] for f in A["facts"]))

    def test_min_cash_override(self):
        r = R(100_000_000)
        r["s2"]["min_cash"] = 100_000_000
        A = dv.advise(r, S, {"best": 150_000_000}, ready(최소보유현금="50000000"))
        self.assertEqual(A["amount"], 150_000_000)   # 최소 보유현금을 5천만으로 낮추면 여유 1.5억

    def test_expected_profit_override(self):
        s = {"cur": {"미처분": (110_000_000, "예상", ""), "당기순이익": (100_000_000, "예상", "")}}
        A = dv.advise(R(500_000_000), s, {"best": 400_000_000}, ready(예상순이익="45000000"))
        self.assertEqual(A["amount"], 50_000_000)   # 미처분 5,500만 ÷ 1.1
        self.assertTrue(any("세무사 예상" in f[0] for f in A["facts"]))

    def test_health_extra_only_over_20m(self):
        self.assertEqual(dv.health_extra(20_000_000, True), 0)
        self.assertGreater(dv.health_extra(30_000_000, True), 0)
        self.assertEqual(dv.health_extra(30_000_000, False), 0)

    def test_strict_save_lists_blanks(self):
        d = tempfile.mkdtemp()
        with self.assertRaises(ValueError) as e:
            dv.save_settings(d, {"큰지출": "없음"}, strict=True)
        self.assertIn("꼭 넣을 값", str(e.exception))
        self.assertFalse(os.path.exists(os.path.join(d, dv.SET_FILE)))
        with self.assertRaises(ValueError):   # 퇴직금 '있음'이면 금액도
            dv.save_settings(d, dict(FULL, 퇴직금계획="있음"), strict=True)
        dv.save_settings(d, FULL, strict=True)

    def test_partial_answers_hold(self):
        d = folder([("대표", "100", False, False, "", "")])
        dv.save_settings(d, {"큰지출": "없음"})
        A = dv.advise(R(200_000_000), S, None, d)
        self.assertEqual(A["verdict"], "보류")
        self.assertIn("급여", A["reasons"][0])

    def test_taxbreak_total_used_when_no_manual(self):
        tax = [{"kind": "법인세", "due": dt.date(2027, 3, 31), "amount": 50_000_000},
               {"kind": "법인지방소득세", "due": dt.date(2027, 4, 30), "amount": 5_000_000}]
        s = dict(S, tb={"total": 20_000_000})
        A = dv.advise(R(100_000_000, tax=tax), s, {"best": 90_000_000}, ready())
        self.assertEqual(A["amount"], 65_000_000)   # 1억 − (5천만−2천만) − 5백만 (지방소득세는 감면 없음, 코덱스 검토 11/14)

    def test_taxbreak_not_cut_twice(self):
        tax = [{"kind": "법인세", "due": dt.date(2027, 3, 31), "amount": 30_000_000,
                "basis": "과세표준 … → 감면·공제 뒤 30,000,000 + 농어촌특별세 0 − 중간예납 등 0"}]
        s = dict(S, tb={"total": 20_000_000})
        A = dv.advise(R(100_000_000, tax=tax), s, {"best": 90_000_000}, ready())
        self.assertEqual(A["amount"], 70_000_000)   # 법인세 예상이 이미 감면 뒤라 또 빼지 않음

    def test_checklist_requires_shareholders(self):
        d = tempfile.mkdtemp()
        dv.save_settings(d, FULL)
        A = dv.advise(R(200_000_000), S, None, d)
        self.assertEqual(A["verdict"], "보류")
        self.assertIn("주주", A["reasons"][0])

    def test_html(self):
        A = dv.advise(R(200_000_000), S, None, ready())
        from ceo_report.util import esc
        h = dv.advice_html(A, esc)
        self.assertIn("권장", h)
        self.assertIn("판단 전에 넣은 값", h)


if __name__ == "__main__":
    unittest.main()
