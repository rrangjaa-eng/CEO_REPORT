"""2026-11-14 오후 '숫자 오차·오해 소지' 점검(Claude+코덱스)에서 확인한 오류를 다시 생기지 않게 막는 시험.

번호(F1·T4 …)는 /mnt/project-files/ceo-report/숫자오차·오해소지·코드점검_20261114.md 의 항목 번호.
"""
import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

D = dt.date


def _books(lines, book_date=D(2026, 11, 12)):
    from ceo_report import wehago
    b = wehago.Books()
    b.state, b.book_date = "ok", book_date
    for no, day, code, account, debit, credit, vendor in lines:
        b.journal.append({"date": day, "no": no, "account_code": code, "account": account, "debit": debit,
                          "credit": credit, "vendor": vendor, "memo": "", "sort": ""})
    return b


class TestF1OneSlipManyVendors(unittest.TestCase):
    """F1: 한 이체 전표로 여러 거래처에 준 돈 — 둘째 거래처를 '안 준 돈'으로 남기면 다음 금요일 출금 목록에 다시 올라간다."""

    def _settle(self, rows, lines):
        from ceo_report import fundplan
        fundplan.settle(rows, _books(lines), D(2026, 11, 12))
        return [r["상태"] for r in rows]

    def test_one_transfer_slip_two_vendors_one_bank_line(self):
        from test_fundplan import plan_row
        rows = [plan_row("2026-11-10", "지급", "가상음향", 10000000), plan_row("2026-11-10", "지급", "나무조명", 20000000)]
        lines = [("8", D(2026, 11, 10), "25300", "미지급금", 10000000, None, "가상음향"),
                 ("8", D(2026, 11, 10), "25300", "미지급금", 20000000, None, "나무조명"),
                 ("8", D(2026, 11, 10), "10300", "보통예금", None, 30000000, "")]
        self.assertEqual(self._settle(rows, lines), ["이미 지급", "이미 지급"])

    def test_one_transfer_slip_two_vendors_bank_line_each(self):
        from test_fundplan import plan_row
        rows = [plan_row("2026-11-10", "지급", "가상음향", 10000000), plan_row("2026-11-10", "지급", "나무조명", 20000000)]
        lines = [("8", D(2026, 11, 10), "25300", "미지급금", 10000000, None, "가상음향"),
                 ("8", D(2026, 11, 10), "10300", "보통예금", None, 10000000, "가상음향"),
                 ("8", D(2026, 11, 10), "25300", "미지급금", 20000000, None, "나무조명"),
                 ("8", D(2026, 11, 10), "10300", "보통예금", None, 20000000, "나무조명")]
        self.assertEqual(self._settle(rows, lines), ["이미 지급", "이미 지급"])

    def test_one_slip_two_invoices_same_vendor(self):
        # 같은 거래처 계산서 두 장을 한 전표로 지급: 채무 줄 두 개 + 예금 줄 하나
        from test_fundplan import plan_row
        rows = [plan_row("2026-11-10", "지급", "가상음향", 10000000), plan_row("2026-11-11", "지급", "가상음향", 10000000)]
        lines = [("8", D(2026, 11, 10), "25300", "미지급금", 10000000, None, "가상음향"),
                 ("8", D(2026, 11, 10), "25300", "미지급금", 10000000, None, "가상음향"),
                 ("8", D(2026, 11, 10), "10300", "보통예금", None, 20000000, "가상음향")]
        self.assertEqual(self._settle(rows, lines), ["이미 지급", "이미 지급"])

    def test_payable_and_bank_line_of_one_payment_still_count_once(self):
        # PR #20 이 막으려던 것: 한 지급의 채무 줄·예금 줄로 같은 금액 계획 두 줄을 모두 '이미 지급'으로 보지 않는다
        from test_fundplan import plan_row
        rows = [plan_row("2026-11-10", "지급", "가상음향", 10000000), plan_row("2026-11-20", "지급", "가상음향", 10000000)]
        lines = [("7", D(2026, 11, 10), "25300", "미지급금", 10000000, None, "가상음향"),
                 ("7", D(2026, 11, 10), "10300", "보통예금", None, 10000000, "가상음향")]
        self.assertEqual(sorted(self._settle(rows, lines)), ["예정", "이미 지급"])

    def test_receipt_slip_two_customers(self):
        from test_fundplan import plan_row
        rows = [plan_row("2026-11-10", "입금", "가상기획", 11000000), plan_row("2026-11-10", "입금", "나무물산", 22000000)]
        lines = [("9", D(2026, 11, 10), "10300", "보통예금", 33000000, None, ""),
                 ("9", D(2026, 11, 10), "10800", "외상매출금", None, 11000000, "가상기획"),
                 ("9", D(2026, 11, 10), "10800", "외상매출금", None, 22000000, "나무물산")]
        self.assertEqual(self._settle(rows, lines), ["이미 입금", "이미 입금"])

    def test_paid_in_five_installments(self):
        # 다섯 번 나눠 낸 지급: 그 거래처의 기간 안 지급을 모두 더한 것이 계획 금액과 같으면 '이미 지급'
        from test_fundplan import plan_row
        rows = [plan_row("2026-11-10", "지급", "가상음향", 15000000)]
        lines = [(str(10 + i), D(2026, 11, 1 + i), "25300", "미지급금", 3000000, None, "가상음향") for i in range(5)]
        self.assertEqual(self._settle(rows, lines), ["이미 지급"])


from test_teamreport import TeamReportCase, _append, text  # noqa: E402


class TestT4UnknownCostKeepsProject(TeamReportCase):
    """T4: 집행 금액 미확인 줄이 한 건 있으면 그 프로젝트 사전견적까지 팀장 '올해 예상'에서 빠지던 것 (PR #20 에서 생김).

    매출 합계는 사전견적만, 이익 예상은 사전견적·추정 예산만 있으면 된다. 집행액을 모르는 것은 집행액·잔여 칸만 '미확인'."""

    def _unknown_cost_row(self):
        _append(os.path.join(self.folder, "프로젝트집행.csv"), [
            {"프로젝트번호": "P26201", "항목": "추가 장비", "거래처": "가상장비", "상태": "요청미지급", "공급가액": "",
             "부가세": "", "일자": "2026-10-28", "확정여부": "확정", "근거": "금액 확인 중"}])

    def test_unknown_cost_does_not_drop_revenue_or_profit_expectation(self):
        _, _, before, _ = self.make()
        self._unknown_cost_row()
        _, _, after, _ = self.make()
        a = [r for r in after["up"] if r["id"] == "P26201"][0]
        self.assertIsNone(a["paid"])   # 집행액은 미확인 그대로
        self.assertEqual(after["exp_rev"], before["exp_rev"])
        self.assertEqual(after["exp_gp"], before["exp_gp"])
        self.assertEqual(after["up_tot"]["estimate"], before["up_tot"]["estimate"])
        self.assertEqual(after["up_missing"], before["up_missing"])   # '사전견적·추정 예산 없음'은 P26204 한 건 그대로

    def test_paid_and_left_totals_are_unknown_with_the_right_reason(self):
        self._unknown_cost_row()
        _, _, T, page = self.make()
        self.assertIsNone(T["up_tot"]["paid"])
        self.assertIsNone(T["up_tot"]["left"])
        self.assertIn("집행 금액 미확인 1건", text(page))
        self.assertIn("사전견적 또는 추정 예산이 없는 1건", text(page))


# ───────────── F2·F6·F7: 대표 큰 숫자 (사용자 2026-11-14 결정 D1 '정기 지출 예상도 빼기') ─────────────
from ceo_report import calc as _calc  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402

SAMPLE_DIR = os.path.join(ROOT, "입력양식", "샘플")


def _ev(day, io, amount, firm=False, source="자금일정", cat=""):
    return {"date": day, "io": io, "amount": amount, "firm": firm, "source": source, "cat": cat, "desc": "", "basis": "",
            "project": ""}


class TestF2MustPay(unittest.TestCase):
    """프로그램이 장부로 계산한 급여·4대보험·원천세·부가세·법인세·카드대금 지급은 '예상'이어도 큰 숫자(여유 자금)에서 뺀다.
    프로젝트 남은 예산·불확실한 입금만 '예상'으로 아래에 따로 (D1)."""

    def test_which_rows_are_must_pay(self):
        day = D(2026, 11, 25)
        for kind in ("급여", "4대보험", "원천세", "부가세", "법인세", "법인지방소득세", "카드대금"):
            self.assertTrue(_calc.must_pay(_ev(day, "out", 1, source="세금예상", cat="%s (장부 계산)" % kind)), kind)
        self.assertTrue(_calc.must_pay(_ev(day, "out", 1, source="세금예상", cat="부가세 (장부 계산 차액)")))
        self.assertFalse(_calc.must_pay(_ev(day, "out", 1, source="남은 예산", cat="프로젝트 남은 예산")))
        self.assertFalse(_calc.must_pay(_ev(day, "out", 1, source="세금예상", cat="정기예금 가입 (장부 계산)")))
        self.assertFalse(_calc.must_pay(_ev(day, "in", 1, source="세금예상", cat="정기예금 만기 (장부 계산)")))

    def test_hand_entered_estimates_of_regular_payments(self):
        """손으로 넣은 자금일정 '추정' 줄도 분류·거래처가 급여·4대보험·세금·카드면 꼭 나갈 돈 (분류 글자 하나에만 기대지 않음)."""
        day = D(2026, 12, 14)
        must = [("카드대금", "신한카드"), ("급여", "직원"), ("인건비", ""), ("회사부담금", "4대보험"), ("세금", "세무서"),
                ("기타", "OO세무서"), ("공과금", "국민건강보험공단"), ("비품", "롯데카드")]
        for cat, vendor in must:
            self.assertTrue(_calc.must_pay(dict(_ev(day, "out", 1, cat=cat), desc=vendor)), (cat, vendor))
        never = [("자금일정", "설비·이전", "인테리어업체"), ("자금일정", "미정산비용", "출장비"), ("자금일정", "카드대금", "신한카드", "in"),
                 ("프로젝트집행", "프로젝트 집행계획", "법인카드"), ("남은 예산", "프로젝트 남은 예산", "")]
        for src, cat, vendor, *io in never:
            self.assertFalse(_calc.must_pay(dict(_ev(day, io[0] if io else "out", 1, source=src, cat=cat), desc=vendor)),
                             (src, cat, vendor))

    def test_schedule_row_matched_to_a_computed_tax_is_must(self):
        """장부 계산 세금 줄 대신 쓰인 일정(금액이 같아 맞춘 '기타' 줄 등)도 꼭 나갈 돈. 정기예금 가입과 맞춘 줄은 아님."""
        a = dict(_ev(D(2026, 12, 10), "out", 700, cat="기타"), desc="")
        b = dict(_ev(D(2026, 12, 10), "out", 900, cat="기타"), desc="")
        _calc.mark_must([a, b], [{"kind": "원천세", "matched": a}, {"kind": "정기예금 가입", "matched": b},
                                 {"kind": "카드대금", "matched": {"merged_card": True, "amount": None}}])
        self.assertTrue(a["must"])
        self.assertFalse(b["must"])

    def test_big_number_then_expected_payments_then_everything(self):
        dated = [_ev(D(2026, 11, 18), "in", 40, source="계산서", cat="수금(발행 계산서)"),   # 불확실한 입금
                 _ev(D(2026, 11, 20), "out", 100, firm=True),
                 dict(_ev(D(2026, 11, 25), "out", 50, source="세금예상", cat="부가세 (장부 계산)"), must=True),
                 _ev(D(2026, 11, 26), "out", 30, source="남은 예산", cat="프로젝트 남은 예산")]
        p = _calc.available_periods(1000, dated, [("11월", D(2026, 11, 30))], 0, D(2026, 11, 14))[0]
        self.assertEqual(p["firm"]["avail"], 850)    # 확정 100 + 꼭 나갈 정기 지출 예상 50
        self.assertEqual(p["spend"]["avail"], 820)   # + 프로젝트 남은 예산 30 (예상 입금 40은 넣지 않음, F7)
        self.assertEqual(p["all"]["avail"], 860)     # 예상 입금까지 모두


class TestF2OnSample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.W = compute(load(SAMPLE_DIR), "weekly", D(2026, 11, 6))
        cls.M = compute(load(SAMPLE_DIR), "monthly", D(2026, 10, 31))

    def test_must_pay_estimates_are_in_the_big_number(self):
        for R in (self.W, self.M):
            p = R["s2"]["periods"][-1]
            win = [e for e in R["s2"]["dated"] if R["asof"] < e["date"] <= p["end"]]
            want = sum(e["amount"] for e in win if e["io"] == "out" and (e["firm"] or e.get("must")))
            self.assertEqual(p["firm"]["out"], want, R["kind"])
        # 월간 샘플(1월까지)엔 정기 지출 예상이 있어야 뜻이 있음: 부가세 3,500만(자금일정 '세금' 추정)·카드 1,500만·원천세 차액 290만
        p = self.M["s2"]["periods"][-1]
        est = sorted((e["cat"], e["amount"]) for e in self.M["s2"]["dated"]
                     if self.M["asof"] < e["date"] <= p["end"] and e.get("must") and not e["firm"])
        self.assertEqual(est, sorted([("세금", 35_000_000), ("카드대금", 15_000_000), ("원천세 (장부 계산 차액)", 2_900_000)]))

    def test_sample_monthly_big_number_drops_by_the_must_estimates(self):
        """점검 문서 F2 크기: 샘플 월간 1월까지 여유 자금 3.05억 → 2.53억 (−5,290만)."""
        R = self.M
        ends = [(q["label"], q["end"]) for q in R["s2"]["periods"]]
        old = [dict(e, must=False) for e in R["s2"]["dated"]]
        before = _calc.available_periods(R["s2"]["start"], old, ends, R["s2"]["min_cash"], R["asof"])[-1]["firm"]["avail"]
        self.assertEqual(before - R["s2"]["periods"][-1]["firm"]["avail"], 52_900_000)

    def test_ceo_shows_one_big_number_and_mgmt_keeps_the_extra_lines(self):
        from ceo_report.render import render
        for R in (self.W, self.M):
            ceo = render(R, "ceo")
            self.assertNotIn("떼면", ceo, R["kind"])
            self.assertNotIn("예상 지급까지 빼면", ceo, R["kind"])
        self.assertIn("떼면", render(self.W, "mgmt"))

    def test_expected_payments_line_leaves_out_expected_income(self):
        from ceo_report.render import render
        html = render(self.W, "ceo")
        shown = 0
        for p in self.W["s2"]["periods"]:
            f, s = p["firm"]["avail"], p["spend"]["avail"]
            if s != f:
                shown += 1
                self.assertIn("프로젝트 지급 예상 등까지 빼면 %s" % "{:,}".format(s), html)
        self.assertTrue(shown)

    def test_monthly_first_line_is_one_number_for_ceo(self):
        from ceo_report import render as RD
        self.assertNotIn("빼면", RD._mon_strip(self.M, "ceo"))
        self.assertIn("빼면", RD._mon_strip(self.M, "mgmt"))


class TestF2SameBaseEverywhere(unittest.TestCase):
    """큰 숫자와 같은 기준으로: 날마다 잔액 그림(실선)·자금이 모자라는 날·경보 글·현황 화면·가수금 갚을 때도 정기 지출 예상을 넣는다."""

    @staticmethod
    def fake():
        ev = [dict(_ev(D(2026, 11, 20), "out", 300, source="세금예상", cat="부가세 (장부 계산)"), must=True),
              _ev(D(2026, 11, 21), "out", 100, source="남은 예산", cat="프로젝트 남은 예산")]
        return {"asof": D(2026, 11, 14), "kind": "weekly",
                "s2": {"start": 1000, "min_cash": 800, "dated": ev, "periods": [], "out_missing": []}}

    def test_daily_balance_line(self):
        from ceo_report import insights
        day = {c["date"]: c for c in insights.calendar(self.fake(), days=10)}
        self.assertEqual(day[D(2026, 11, 20)]["firm"], 700)
        self.assertEqual(day[D(2026, 11, 21)]["firm"], 700)
        self.assertEqual(day[D(2026, 11, 21)]["all"], 600)

    def test_first_short_day(self):
        from ceo_report import insights
        self.assertEqual(insights._first_short(self.fake(), "firm")[:2], (D(2026, 11, 20), 100))

    def test_alert_says_which_money(self):
        from ceo_report import insights
        R = self.fake()
        R["s2"]["periods"] = _calc.available_periods(1000, R["s2"]["dated"], [("이번 주", D(2026, 11, 20))], 800, R["asof"])
        text = " ".join(t for _, t in insights.alerts(R))
        self.assertIn("100원 모자람", text)
        self.assertNotIn("확정분 기준", text)
        self.assertIn("급여·세금·카드 예상", text)

    def test_gasu_firm_path(self):
        from ceo_report import gasu
        days = dict(gasu.path(self.fake(), True, D(2026, 11, 22)))
        self.assertEqual(days[D(2026, 11, 22)], 700)

    def test_live_page(self):
        import tempfile
        from unittest import mock
        from ceo_report import gate, live
        with mock.patch.dict(os.environ, {gate.TEST_OFF: "1"}), tempfile.TemporaryDirectory() as out:
            path, _ = live.build(SAMPLE_DIR, out, D(2026, 10, 31))
            with open(path, encoding="utf-8") as f:
                page = f.read()
        R = compute(load(SAMPLE_DIR), "weekly", D(2026, 10, 31))
        self.assertNotIn("예상 지급까지 빼면", page)
        self.assertNotIn("확정된 돈만", page)
        last = R["s2"]["periods"][-1]
        self.assertIn("{:,}".format(last["spend"]["avail"]), page)
        self.assertIn("프로젝트 지급 예상 등까지 빼면", page)


    def test_blocked_report_blanks_the_new_number_too(self):
        """자금계획서·최신 분개장이 없어 막히면 새로 생긴 '프로젝트 지급 예상 등까지 빼면' 숫자도 비운다 (사용자 절대 규칙 2026-11-12)."""
        from unittest import mock
        from ceo_report import gate
        from ceo_report.render import render
        with mock.patch.dict(os.environ, {gate.TEST_OFF: ""}):
            R = compute(load(SAMPLE_DIR), "weekly", D(2026, 11, 6))   # 예시 자료엔 자금계획서가 없다
            shown = R["s2"]["periods"][-1]["spend"]["avail"]
            self.assertIsNotNone(shown)
            self.assertTrue(gate.blank_funds(R))
            for p in R["s2"]["periods"]:
                for mode in ("firm", "spend", "all"):
                    self.assertIsNone(p[mode]["avail"], mode)
                    self.assertIsNone(p[mode]["low"], mode)
            self.assertNotIn("{:,}".format(shown), render(R, "mgmt"))


# ───────────── P1·F12·F13·F14: 대표용 문구 (사용자 2026-11-14 결정 D2 '높음·중간 전부 + 빼기', 경영관리는 그대로) ─────────────
def _fake_issue_R(start, events, unissued, fundplan=None):
    """계산서 발행 기한 시험용 R: 기준일 2026-11-14, 최소 보유현금 100."""
    asof = D(2026, 11, 14)
    rows = [{"P": {"id": i, "name": "프로젝트 " + i}, "event": asof - dt.timedelta(days=20), "days": 20, "unissued": u}
            for i, u in unissued]
    return {"asof": asof, "kind": "weekly", "fundplan": fundplan,
            "s2": {"start": start, "min_cash": 100, "dated": events, "periods": [], "out_missing": []},
            "s5": {"event_unissued": {"missing": False, "rows": rows, "unknown": [], "total": sum(u for _, u in unissued)}}}


class TestCeoWording(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ceo_report.render import render
        cls.W = compute(load(SAMPLE_DIR), "weekly", D(2026, 11, 6))
        cls.M = compute(load(SAMPLE_DIR), "monthly", D(2026, 10, 31))
        cls.page = dict(((R["kind"], m), render(R, m)) for R in (cls.W, cls.M) for m in ("ceo", "mgmt"))

    def test_p1_month_profit_forecast_is_mgmt_only(self):
        """P1: 월초엔 비용만 먼저 잡혀 큰 적자로 보이는 '이번 달 예상 영업이익'은 대표 주간에서 뺀다."""
        self.assertNotIn("예상 영업이익", self.page["weekly", "ceo"])
        self.assertIn("11월 예상 영업이익", self.page["weekly", "mgmt"])

    def test_f12_change_reasons_are_mgmt_only(self):
        """F12: '지난 보고 뒤 여유 자금을 바꾼 것'은 예상 줄로 채워지고 금액도 큰 숫자에 준 영향이 아니라 대표용에서 뺀다."""
        from ceo_report import insights
        from ceo_report.render import render
        from test_report import numbers_of
        for kind, day in (("weekly", D(2026, 11, 6)), ("monthly", D(2026, 10, 31))):
            R = compute(load(SAMPLE_DIR), kind, day)
            I = insights.compute(R)
            I["reasons"] = [("시험 입금 (예상)", 1234567)]
            R["_ins"] = I
            ceo, mgmt = render(R, "ceo"), render(R, "mgmt")
            self.assertNotIn("지난 보고 뒤 여유 자금을 바꾼 것", ceo, kind)
            self.assertIn("지난 보고 뒤 여유 자금을 바꾼 것", mgmt, kind)
            self.assertEqual(numbers_of(ceo), numbers_of(mgmt), kind)

    def test_f13_no_all_clear_sentence_for_ceo(self):
        """F13: '발행이 늦어도 자금은 모자라지 않습니다'는 대표용에서 뺀다 (모자랄 때만 경고). 경영관리는 범위·기준을 밝혀 남긴다."""
        for kind in ("weekly", "monthly"):
            self.assertNotIn("모자라지 않습니다", self.page[kind, "ceo"], kind)
            self.assertNotIn("발행이 늦어도", self.page[kind, "mgmt"], kind)
        self.assertIn("2027-04-30(일정 끝)까지", self.page["weekly", "mgmt"])
        self.assertIn("예상 입금·지급까지 넣은", self.page["weekly", "mgmt"])

    def test_f13_unissued_is_one_amount_with_vat(self):
        """F13: 같은 미발행이 4,500만(공급가액)과 4,950만(부가세 포함)으로 따로 보이던 것 → '받을 돈(부가세 포함)' 하나."""
        import re
        for kind in ("weekly", "monthly"):
            for mode in ("ceo", "mgmt"):
                card = self.page[kind, mode].split("행사 후 세금계산서 미발행</div><div class='big'>")[1]
                big, foot = re.match(r"(.*?)</div><div class='foot'>(.*?)</div>", card).groups()
                self.assertEqual(big, "49,500,000", (kind, mode))
                self.assertIn("받을 돈 (부가세 포함)", foot, (kind, mode))

    def test_f13_unknown_when_balance_cannot_be_judged(self):
        """F13: 잔액·최소 보유현금을 몰라 계산을 못 해도 '모자라지 않습니다'가 나오던 것 → '확인 필요'."""
        from ceo_report import insights, insights_render as IR
        X = insights.issue_deadline(_fake_issue_R(None, [], [("P1", 1000000)]))
        self.assertTrue(X["unknown"])
        html = IR.ceo_issue(X)
        self.assertIn("확인 필요", html)
        self.assertNotIn("모자라지 않습니다", html)
        self.assertIn("1,100,000", html)

    def test_f13_own_inflow_of_unissued_project_is_not_trusted(self):
        """F13: 미발행 프로젝트의 입금이 자금일정에 이미 있으면 그 돈을 믿고 '괜찮다'고 하던 것 → 그 입금은 빼고 판단 (발행 뒤 60일에야 들어옴)."""
        from ceo_report import insights
        ev = [dict(_ev(D(2026, 11, 20), "in", 500), project="P1"), _ev(D(2026, 11, 27), "out", 300, firm=True)]
        X = insights.issue_deadline(_fake_issue_R(300, ev, [("P1", 1000000)]))
        self.assertEqual(X["short"][:2], (D(2026, 11, 27), 100))
        # 발행한 계산서의 입금(출처 '계산서')은 그대로 믿는다
        ev[0]["source"] = "계산서"
        self.assertIsNone(insights.issue_deadline(_fake_issue_R(300, ev, [("P1", 1000000)]))["short"])

    def test_f13_all_clear_is_limited_to_the_fund_plan(self):
        """F13: 자금계획서 범위를 넘어 6달 뒤까지 '모자라지 않음'이라 하던 것 → 자금계획서 끝까지만."""
        from ceo_report import insights, insights_render as IR
        ev = [_ev(D(2026, 12, 4), "out", 10, firm=True), _ev(D(2027, 3, 5), "out", 10, firm=True)]
        X = insights.issue_deadline(_fake_issue_R(1000, ev, [("P1", 1000000)], fundplan={"used": True, "months": ["2026-11", "2026-12"]}))
        self.assertEqual(X["horizon"], D(2026, 12, 31))
        self.assertIn("2026-12-31(자금계획서 끝)까지", IR.ceo_issue(X))

    def test_f13_small_rows_stay_in_the_total(self):
        """미발행은 끝전도 빼지 않는다 (사용자 2026-11-05): 발행 기한 표에서 1만 원 밑은 '그 밖'으로 묶되 합계는 실적 칸과 같은 숫자."""
        from ceo_report import insights, insights_render as IR
        ev = [_ev(D(2027, 1, 11), "out", 950, firm=True)]
        X = insights.issue_deadline(_fake_issue_R(1000, ev, [("P1", 1000000), ("P2", 500)]))
        self.assertEqual(X["total"], 1100000 + 550)
        html = IR.ceo_issue(X)
        self.assertIn("합계 2건", html)
        self.assertIn("1,100,550", html)

    def test_f13_short_sentence_names_both_expected_sides(self):
        """모자라는 날은 예상 입금·지급을 모두 넣어 판단한다 → 글도 '예상 입금·지급까지 넣으면' (예상 지급만이 아님)."""
        from ceo_report import insights, insights_render as IR
        ev = [_ev(D(2027, 1, 11), "out", 950, firm=True)]
        html = IR.ceo_issue(insights.issue_deadline(_fake_issue_R(1000, ev, [("P1", 1000000)])))
        self.assertIn("예상 입금·지급까지 넣으면", html)

    def test_f14_failed_analysis_is_said_in_both_editions(self):
        """F14: 자동 분석이 실패하면 대표 경보·발행 기한이 조용히 사라져 대표는 '경보 없음'으로 읽는다 → 두 판 모두에 한 줄."""
        from unittest import mock
        from ceo_report import insights
        from ceo_report.render import render
        from test_report import numbers_of
        for kind, day in (("weekly", D(2026, 11, 6)), ("monthly", D(2026, 10, 31))):
            R = compute(load(SAMPLE_DIR), kind, day)
            with mock.patch.object(insights, "compute", side_effect=RuntimeError("시험 실패")):
                ceo, mgmt = render(R, "ceo"), render(R, "mgmt")
            for page in (ceo, mgmt):
                self.assertIn("자동 분석을 못 했습니다", page, kind)
            self.assertNotIn("시험 실패", ceo)
            self.assertEqual(numbers_of(ceo), numbers_of(mgmt), kind)


if __name__ == "__main__":
    unittest.main()
