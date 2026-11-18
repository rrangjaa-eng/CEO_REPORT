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
        # 11/18 (사용자 2026-11-17 '받음'만 세금 계산에): '받음'(넣음) 표시한 후보만 뺀다
        s = dict(S, tb={"total": 20_000_000, "rows": [("중소기업 특별세액감면", "해당", 20_000_000, "", "", "", "넣음 · 받음")]})
        A = dv.advise(R(100_000_000, tax=tax), s, {"best": 90_000_000}, ready())
        self.assertEqual(A["amount"], 65_000_000)   # 1억 − (5천만−2천만) − 5백만 (지방소득세는 감면 없음, 코덱스 검토 11/14)
        s2 = dict(S, tb={"total": 20_000_000, "rows": [("중소기업 특별세액감면", "해당", 20_000_000, "", "", "", "안 넣음 · 기본")]})
        self.assertEqual(dv.advise(R(100_000_000, tax=tax), s2, {"best": 90_000_000}, ready())["amount"], 45_000_000)

    def test_taxbreak_not_cut_twice(self):
        tax = [{"kind": "법인세", "due": dt.date(2027, 3, 31), "amount": 30_000_000,
                "basis": "과세표준 … → 감면·공제 뒤 30,000,000 + 농어촌특별세 0 − 중간예납 등 0"}]
        s = dict(S, tb={"total": 20_000_000, "rows": [("중소기업 특별세액감면", "해당", 20_000_000, "", "", "", "넣음 · 받음")]})
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


class WageSources1117(unittest.TestCase):
    """사용자 2026-11-17: '대표가 급여를 받는다고 했잖아! 왜 근로소득을 못 찾는데?' — 연중 연간 보고는 지난해를 봐서
    올해 장부만 있는 사원급여.csv 에서 못 찾았다. 원천징수부 → 위하고 급여 → 장부 → 연말정산 순서로 찾는다. (가짜 숫자)"""

    def _dir(self, files):
        import tempfile
        d = tempfile.mkdtemp()
        for name, text in files.items():
            with open(os.path.join(d, name), "w", encoding="utf-8-sig") as f:
                f.write(text)
        return d

    def test_withholding_book_first_last_12_months(self):
        from ceo_report import dividend
        rows = "".join("%s,가대표,%d,위하고\n" % (ym, v) for ym, v in
                       [("2025-%02d" % m, 3000000) for m in range(2, 12)] + [("2025-12", 10000000)] + [("2026-%02d" % m, 4000000) for m in range(1, 11)])
        d = self._dir({"근로소득.csv": "연월,사원명,과세급여,자료\n" + rows,
                       "사원급여.csv": "연월,부서,사원명,급여\n2026-01,본부,가대표,999\n"})
        w = dividend.wage_info(d, "가대표", dt.date(2026, 11, 17))
        self.assertEqual(w["span"], "2025-11~2026-10")
        self.assertEqual(w["wage"], 3000000 + 10000000 + 4000000 * 10)
        self.assertIn("원천징수부", w["src"])

    def test_last_year_window_uses_wehago_not_this_year_book(self):
        from ceo_report import dividend
        d = self._dir({"사원급여.csv": "연월,부서,사원명,급여\n2026-01,본부,가대표,5000000\n",
                       "급여명세.csv": "연월,사원명,구분,항목,금액\n" + "".join("2025-%02d,가대표,지급,지급합계,5000000\n" % m for m in range(7, 13))})
        w = dividend.wage_info(d, "가대표", dt.date(2025, 12, 31))
        self.assertEqual((w["wage"], w["months"]), (60000000, 6))   # 6달치를 12달로

    def test_yearend_then_not_found_lists_what_was_missing(self):
        from ceo_report import dividend
        d = self._dir({"연말정산.csv": "귀속연도,사원명,총급여\n2025,가대표,70000000\n"})
        self.assertEqual(dividend.wage_info(d, "가대표", dt.date(2026, 3, 1))["wage"], 70000000)
        w = dividend.wage_info(d, "없는사람", dt.date(2026, 3, 1))
        self.assertIsNone(w["wage"])
        self.assertIn("근로소득.csv 없음", w["looked"])

    def test_found_wage_counts_even_if_flag_says_no_and_explanation(self):
        from ceo_report import dividend
        d = self._dir({"주주.csv": "이름,지분율,미성년자,회사급여\n가대표,50,아니오,아니오\n자녀,50,예,아니오\n",
                       "근로소득.csv": "연월,사원명,과세급여,자료\n" + "".join("2026-%02d,가대표,7000000,위하고\n" % m for m in range(1, 13))})
        D = dividend.plan(d, dt.date(2026, 12, 31), 200_000_000)
        p = D["people"][0]
        self.assertEqual(p["wage"], 84000000)
        self.assertTrue(p["salaried"])
        self.assertEqual(D["best"], 40_000_000)   # 대표 50% 몫이 2천만에 닿는 선
        h = dividend.why_html(D, None, lambda x: x)
        for word in ("24%", "26.4%", "지분율대로", "가장 작은 값", "84,000,000"):
            self.assertIn(word, h)


class LimitThisYear1117(unittest.TestCase):
    """사용자 2026-11-17: 배당 한도는 올해 이익 + 작년에서 넘어온 이익잉여금으로. 올해 줄에 자본금·이익준비금 잔액이 없으면
    앞 해 잔액을 이어 써서 '÷1.1'로 작게 셈하지 않는다. (가짜 숫자)"""

    def test_limit_uses_this_year_and_carries_capital(self):
        import tempfile
        from ceo_report import surplus
        d = tempfile.mkdtemp()
        rows = [("2025", "미처분", "100000000", "확정"), ("2025", "자본금", "20000000", "확정"), ("2025", "이익준비금잔액", "0", "확정"),
                ("2026", "전기이월", "100000000", "확정"), ("2026", "당기순이익", "120000000", "예상"), ("2026", "미처분", "220000000", "예상")]
        with open(os.path.join(d, surplus.FILE), "w", encoding="utf-8-sig") as f:
            f.write("연도,항목,금액,상태,근거\n" + "".join("%s,%s,%s,%s,\n" % r for r in rows))
        with open(os.path.join(d, "주주.csv"), "w", encoding="utf-8-sig") as f:
            f.write("이름,지분율,미성년자,회사급여\n가대표,100,아니오,예\n")
        S = surplus.for_report(d, 2026, strict=True, asof=dt.date(2026, 11, 17))
        self.assertEqual(S["year"], 2026)
        self.assertEqual(S["div"]["limit"], 210000000)   # 2억2천 − 이익준비금 1천만(자본금 절반) — 예전엔 ÷1.1 = 2억
        self.assertIn("작년까지 벌어", dv.render(S["div"], lambda x: x, S))


class FiledAnswer1117(unittest.TestCase):
    def test_last_year_breaks_filled_from_return(self):
        """11/17 규칙: 작년 신고서(법인세신고.csv)에 답이 있으면 '작년 받은 감면·공제'를 '모름'으로 두지 않는다. (가짜 숫자)"""
        import tempfile
        from ceo_report import taxreturn
        d = tempfile.mkdtemp()
        with open(os.path.join(d, taxreturn.FILE), "w", encoding="utf-8-sig") as f:
            f.write("연도,구분,공제감면세액,특별감면,고용공제,공제이월\n2025,확정,300,200,100,5000\n")
        got = dict((k, v) for k, _, v, _, _ in dv.checklist(d))["작년감면"]
        self.assertIn("중소기업 특별세액감면 200원", got)
        self.assertIn("창업 감면은 받지 않음", got)
