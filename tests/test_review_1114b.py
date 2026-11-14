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


# ───────────── K1: 같은 개념은 한 곳에서 (꼭 나갈 돈 판정 · 미발행) ─────────────
class TestK1OnePlace(unittest.TestCase):
    def test_must_pay_words_are_shared(self):
        """'꼭 나갈 돈' 판정이 큰 숫자(calc.must_pay)와 기간 뒤 떼어 보는 줄(insights._is_must)에서 낱말이 달라
        '부가가치세'·'국민건강보험공단'을 한쪽만 알아보던 것 → 한 함수. 다른 점은 둘뿐: 카드는 큰 숫자에만(D1), 대출은 떼어 보는 줄에만(사용자 2026-11-12)."""
        from ceo_report import insights
        def ev(cat, desc=""):
            return dict(_ev(D(2026, 12, 10), "out", 100, cat=cat), desc=desc)
        for e in (ev("부가가치세"), ev("기타", "국민건강보험공단"), ev("인건비"), ev("급여"), ev("세금")):
            with self.subTest(cat=e["cat"], desc=e["desc"]):
                self.assertTrue(_calc.must_pay(e))
                self.assertTrue(insights._is_must(e))
        card, loan = ev("카드대금", "신한카드"), ev("차입금 상환")
        self.assertTrue(_calc.must_pay(card))
        self.assertFalse(insights._is_must(card))
        self.assertFalse(_calc.must_pay(loan))
        self.assertTrue(insights._is_must(loan))
        for e in (ev("프로젝트 남은 예산"), dict(ev("임차료"), io="in")):
            self.assertFalse(_calc.must_pay(e))
            self.assertFalse(insights._is_must(e))

    def test_unissued_risk_uses_the_same_basis_as_the_ceo_card(self):
        """미발행이 위험 분석에선 계약금액 기준 6,000만, 대표 칸·발행 기한에선 사전견적 기준 4,500만(받을 돈 4,950만)으로 달랐던 것
        → 위험 분석도 행사 후 미발행(사전견적·확정 견적 기준) 하나로."""
        R = compute(load(SAMPLE_DIR), "weekly", D(2026, 11, 6))
        facts = [r["fact"] for r in R["risks"] if r["area"] == "수금" and "미발행" in r["fact"]]
        self.assertEqual(facts, ["P26205 E사 파트너 포럼: 행사 후 48일, 미발행 45,000,000원 (받을 돈 49,500,000원, 부가세 포함)."])


# ───────────── 자료 대조 경고 자리 (사용자 2026-11-14 F 스레드 결정: 1천만 원 넘게 어긋나면 대표 보고에 경고 한 줄, 숫자 그대로·막지 않음) ─────────────
class TestReconWarnSlot(unittest.TestCase):
    """대조 계산은 reconcile.py(H 스레드)가 R['recon'] 에 넣는다: [{'what': '통장', 'diff': 장부 − 비교 자료(원) 또는 None}]."""

    def test_line_on_top_only_over_ten_million(self):
        from ceo_report.render import render
        from test_report import numbers_of
        for kind, day in (("weekly", D(2026, 11, 6)), ("monthly", D(2026, 10, 31))):
            R = compute(load(SAMPLE_DIR), kind, day)
            R["recon"] = [{"what": "통장", "diff": 12_345_678}, {"what": "미지급금", "diff": -10_000_000},
                          {"what": "차입금", "diff": None}, {"what": "카드", "diff": -23_456_789}]
            ceo, mgmt = render(R, "ceo"), render(R, "mgmt")
            for page in (ceo, mgmt):
                self.assertIn("자료 대조 경고", page, kind)
                self.assertIn("통장 12,345,678원", page, kind)
                self.assertIn("카드 23,456,789원", page, kind)
                self.assertNotIn("미지급금 10,000,000", page, kind)   # 1천만 원 '넘게'만
            self.assertEqual(numbers_of(ceo), numbers_of(mgmt), kind)
            top = ceo[ceo.index("<div class='page fs"):]
            self.assertLess(top.index("자료 대조 경고"), top.index("<div class='sec"), kind)   # 첫 절보다 위

    def test_no_line_when_within_or_not_computed(self):
        from ceo_report.render import render
        R = compute(load(SAMPLE_DIR), "weekly", D(2026, 11, 6))
        self.assertNotIn("자료 대조 경고", render(R, "ceo"))
        R["recon"] = [{"what": "통장", "diff": 10_000_000}, {"what": "차입금", "diff": None}]
        self.assertNotIn("자료 대조 경고", render(R, "ceo"))


# ───────────── F5·P3: 법인세 (작년분 4/30까지 유지, 8/31 중간예납, 한 계산, '지금까지 이익 기준', 3/31·4/30 나눔) ─────────────
def _tax_journal(extra=()):
    """2026년: 매출 3억 − 원가 1억 = 세전 2억 → 법인세 2,000만(10%), 8/25 중간예납 400만(선납세금, 통장)."""
    from test_dept import line
    j = [line(D(2026, 3, 5), "41200", "용역매출", credit=300_000_000),
         line(D(2026, 3, 5), "61000", "외주비(도)", 100_000_000),
         line(D(2026, 8, 25), "13600", "선납세금", 4_000_000),
         line(D(2026, 8, 25), "10300", "보통예금", credit=4_000_000)]
    return j + list(extra)


def _carry(asof, journal=None, input_dir=None):
    from ceo_report import convert, corptax
    rows = corptax.carry_rows(journal if journal is not None else _tax_journal(), dict(convert.DEFAULT_CONFIG), asof, {}, input_dir)
    return dict(((r["세목"], r["대상기간"]), r) for r in rows)


class TestF5CorpTaxCarry(unittest.TestCase):
    """F5: 1/31부터 작년 법인세(3/31)·지방소득세(4/30) 줄이 사라지고, 8/31 중간예납이 자금 일정에 없던 것."""

    def test_last_year_rows_stay_until_paid_dates(self):
        R = _carry(D(2027, 2, 15))
        self.assertEqual(R["법인세", "2026년 (1월~12월 장부 기준)"]["금액"], "16000000")        # 2,000만 − 중간예납 400만
        self.assertEqual(R["법인세", "2026년 (1월~12월 장부 기준)"]["납부예정일"], "2027-03-31")
        self.assertEqual(R["법인지방소득세", "2026년 (1월~12월 장부 기준)"]["금액"], "2000000")
        self.assertEqual(R["법인지방소득세", "2026년 (1월~12월 장부 기준)"]["납부예정일"], "2027-04-30")
        self.assertEqual(set(k[0] for k in _carry(D(2027, 4, 10))), {"법인지방소득세", "법인세"})   # 법인세는 중간예납 줄만
        self.assertNotIn(("법인세", "2026년 (1월~12월 장부 기준)"), _carry(D(2027, 4, 10)))
        self.assertFalse([k for k in _carry(D(2027, 5, 3)) if "2026년" in k[1]])
        # 1월 30일까지는 원래 계산(from_journal)이 작년분을 낸다: 겹치지 않게 여기서는 안 냄
        self.assertFalse([k for k in _carry(D(2027, 1, 20)) if "2026년" in k[1]])

    def test_paid_early_is_dropped(self):
        from test_dept import line
        paid = [dict(line(D(2027, 3, 20), "26100", "미지급법인세", 16_000_000), no="7"),
                dict(line(D(2027, 3, 20), "10300", "보통예금", credit=16_000_000), no="7")]
        R = _carry(D(2027, 3, 25), _tax_journal(paid))
        self.assertNotIn(("법인세", "2026년 (1월~12월 장부 기준)"), R)
        self.assertIn(("법인지방소득세", "2026년 (1월~12월 장부 기준)"), R)

    def test_interim_prepayment_row(self):
        R = _carry(D(2027, 5, 10))
        mid = R["법인세", "2027년 중간예납"]
        self.assertEqual((mid["납부예정일"], mid["금액"], mid["상태"]), ("2027-08-31", "10000000", "예상"))   # 2,000만 × 6/12
        self.assertNotIn(("법인세", "2027년 중간예납"), _carry(D(2027, 9, 1)))
        from test_dept import line
        paid = [dict(line(D(2027, 8, 25), "13600", "선납세금", 10_000_000), no="8"),
                dict(line(D(2027, 8, 25), "10300", "보통예금", credit=10_000_000), no="8")]
        self.assertNotIn(("법인세", "2027년 중간예납"), _carry(D(2027, 8, 27), _tax_journal(paid)))

    def test_small_interim_is_not_due(self):
        """중소기업은 중간예납세액 50만 원 미만이면 내지 않는다."""
        from test_dept import line
        j = [line(D(2026, 3, 5), "41200", "용역매출", credit=8_000_000)]
        self.assertNotIn(("법인세", "2027년 중간예납"), _carry(D(2027, 5, 10), j))   # 80만 × 6/12 = 40만

    def test_filed_return_amounts_win(self):
        import csv
        import tempfile
        from ceo_report import taxreturn
        with tempfile.TemporaryDirectory() as d:
            def write(rows):
                with open(os.path.join(d, taxreturn.FILE), "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=taxreturn.COLUMNS)
                    w.writeheader()
                    for r in rows:
                        w.writerow(r)
            final = {"연도": "2026", "구분": "확정", "총부담세액": "18000000", "기납부세액": "4000000", "차감납부세액": "14000000",
                     "지방소득세": "1900000", "농특세": "50000"}
            write([final, {"연도": "2026", "구분": "중간예납", "차감납부세액": "4000000"}])
            R = _carry(D(2027, 3, 25), input_dir=d)
            ct = [r for k, r in R.items() if k[0] == "법인세" and "2026년" in k[1]][0]
            self.assertEqual(ct["금액"], "14050000")   # 차감납부세액 + 농어촌특별세
            self.assertEqual([r for k, r in R.items() if k[0] == "법인지방소득세"][0]["금액"], "1900000")
            self.assertEqual(R["법인세", "2027년 중간예납"]["금액"], "9000000")   # (총부담 1,800만 − 원천징수 0) × 6/12
            write([dict(final, 실제납부="14050000")])
            self.assertFalse([k for k in _carry(D(2027, 3, 25), input_dir=d) if k[0] == "법인세" and "2026년" in k[1]])

    def test_conversion_writes_them(self):
        """자료 변환(세금예상.csv)에 들어가야 자금 일정·큰 숫자에 반영된다."""
        from ceo_report import convert
        from test_dept import Books
        t = convert.build_tax(Books(_tax_journal()), dict(convert.DEFAULT_CONFIG), D(2027, 2, 15))
        kinds = [(r["세목"], r["납부예정일"]) for r in t.rows if r["세목"].startswith("법인")]
        self.assertIn(("법인세", "2027-03-31"), kinds)
        self.assertIn(("법인지방소득세", "2027-04-30"), kinds)
        self.assertIn(("법인세", "2027-08-31"), kinds)


class TestP3CorpTaxLine(unittest.TestCase):
    """P3: 대표 월간 법인세가 자금 일정과 다른 계산(세무조정 빠짐)이고, 지금까지 이익 기준인데 지방세까지 3/31 납부처럼 보이던 것."""

    @classmethod
    def setUpClass(cls):
        cls.M = compute(load(SAMPLE_DIR), "monthly", D(2026, 10, 31))

    def test_line_says_so_far_and_splits_dates(self):
        from ceo_report.render import render
        for mode in ("ceo", "mgmt"):
            h = render(self.M, mode)
            self.assertIn("1월~10월 이익 기준 세금 예상 (연말 이익에 따라 바뀜) · 법인세 13,500,000 − 중간예납 등 기납부 4,000,000"
                          " = 9,500,000 (2027-03-31) · 지방소득세 1,350,000 (2027-04-30)", h, mode)
            self.assertNotIn("= 납부 10,850,000 (2027-03-31 예상)", h, mode)
            self.assertIn("지금까지 이익 기준 법인세·지방소득세 −14,850,000", h, mode)

    def test_same_base_as_the_fund_schedule(self):
        """세무조정으로 과세표준이 세전 이익과 다르면 자금 일정(변환 때 계산)과 같은 과세표준으로."""
        import copy
        from ceo_report.render import render
        R = copy.deepcopy(self.M)
        row = [t for t in R["tax"] if t["kind"] == "법인세"][0]
        row["base"] = 150_000_000   # 세무조정 +1,500만
        h = render(R, "ceo")
        self.assertIn("법인세 15,000,000 − 중간예납 등 기납부 4,000,000 = 11,000,000 (2027-03-31) · 지방소득세 1,500,000", h)
        self.assertIn("118,500,000", h)   # 당기순이익 예상 = 세전 1.35억 − 1,650만
        row["period"] = "2026년 (1월~9월 장부 기준)"   # 기간이 다르면 이 표의 세전 이익으로 (세무조정 미반영이라고 적음)
        R.pop("_ins", None)
        m = render(R, "mgmt")
        self.assertIn("법인세 13,500,000 − 중간예납 등 기납부 4,000,000", m)
        self.assertIn("세무조정 미반영", m)



class TestP5P6MonthStrip(unittest.TestCase):
    """P5: 월간 첫 칸 '통장 잔액'에 쓸 수 없는 돈(샘플 행사 전용 3,000만)이 들어 있어 여유 자금 계산과 출발점이 달랐던 것.
    P6: 월 중간(11/14)에 만든 월간 보고가 '11월말 통장 잔액'·'월말 잔액'으로 적히던 것 (실제는 11/14 잔액)."""

    @classmethod
    def setUpClass(cls):
        from ceo_report.render import render
        S = load(SAMPLE_DIR)
        cls.end = dict((m, render(compute(S, "monthly", D(2026, 10, 31)), m)) for m in ("ceo", "mgmt"))
        cls.mid = dict((m, render(compute(S, "monthly", D(2026, 11, 14)), m)) for m in ("ceo", "mgmt"))

    @staticmethod
    def first_cell(h):
        top = h[h.index("<div class='four top'>"):]
        return top[:top.index("</div></div>") + 12]

    def test_p5_first_cell_is_usable_money(self):
        for m, h in self.end.items():
            c = self.first_cell(h)
            self.assertIn("<div class='lab'>10월말 쓸 수 있는 돈</div>", c, m)
            self.assertIn("544,600,000", c, m)   # 통장 574,600,000 − 행사 전용 30,000,000
            self.assertIn("통장 잔액 574,600,000 − %s 30,000,000" % ("쓸 수 없는 돈 (담보·전용)" if m == "ceo" else "사용제한"), c, m)
            self.assertNotIn("10월말 통장 잔액", h, m)

    def test_p6_mid_month_says_the_date(self):
        for m, h in self.mid.items():
            self.assertIn("<div class='lab'>11/14 현재 쓸 수 있는 돈</div>", self.first_cell(h), m)
            self.assertNotIn("11월말", h, m)
            self.assertNotIn("월말 잔액", h, m)
            self.assertIn("11/14 잔액", h, m)
            self.assertIn("11월 영업이익 (11/14까지)", h, m)
        for m, h in self.end.items():   # 말일에 만든 월간은 그대로
            self.assertIn("월말 잔액", h, m)
            self.assertNotIn("(10/31까지)", h, m)


def _bt(day, amount, vendor="가", memo="", io="출금", cat=""):
    return {"date": day, "io": io, "amount": amount, "cat": cat, "vendor": vendor, "memo": memo}


class TestLastWeekSameScope(unittest.TestCase):
    """지난주 대비 (사용자 2026-11-14 '같은 범위로 바꾸기'): 지난주 출금 목록에 있던 거래처가 그 주 통장에서 실제로 나간 금액과
    이번 목록을 견준다. 카드·세금 자동 출금은 비교에서 뺀다. 전에는 지난 금요일 하루의 통장 출금 전체(카드대금 포함)와 견줘
    카드대금이 '빠진 것'으로 나오고, 목요일에 낸 주는 '지난주 0원'처럼 보였다."""

    def test_auto_debits(self):
        from ceo_report.calc import auto_debit
        out = lambda vendor="", memo="": {"io": "out", "desc": vendor, "cat": memo}
        for ev in (out("신한_5860"), out("롯데 1842"), out("신한카드", "10월 카드대금"), out("", "부가세 납부"),
                   out("강남세무서"), out("국민건강보험공단"), out("", "4대보험"), out("", "회사부담금"),
                   {"io": "out", "source": "세금예상", "kind": "카드대금", "cat": "카드대금 (신한)", "desc": ""},
                   {"io": "out", "source": "세금예상", "kind": "원천세", "cat": "원천세", "desc": ""}):
            self.assertTrue(auto_debit(ev), ev)
        for ev in (out("(주)가상음향", "행사 음향 용역"), out("홍길동", "10월 급여"), out("건물관리", "10월 임차료"),
                   {"io": "out", "source": "세금예상", "kind": "급여", "cat": "급여", "desc": ""},
                   {"io": "in", "desc": "신한_5860", "cat": ""}):
            self.assertFalse(auto_debit(ev), ev)   # 급여는 출금 목록에도 오르는 지급이라 비교에 남긴다

    def test_whole_week_without_transfers_and_auto_debits(self):
        from ceo_report.calc import last_payday_out
        txns = [_bt(D(2026, 11, 6), 100, "가상음향"),   # 지난주 목요일 (금요일 대신 낸 주)
                _bt(D(2026, 11, 7), 50, "나무조명"),
                _bt(D(2026, 10, 31), 9, "지지난주"),
                _bt(D(2026, 11, 7), 30, "", "", cat="계좌간이체"),
                _bt(D(2026, 11, 7), 70, "신한_5860", "카드대금"),
                _bt(D(2026, 11, 3), 20, "강남세무서", "원천세"),
                _bt(D(2026, 11, 5), 8, "가상음향", io="입금"),
                _bt(D(2026, 11, 13), 1, "이번주")]
        L = last_payday_out(txns, D(2026, 11, 14))
        self.assertEqual((L["start"], L["date"], L["listed"]), (D(2026, 11, 1), D(2026, 11, 7), False))
        self.assertEqual(sorted(r["vendor"] for r in L["rows"]), ["가상음향", "나무조명"])
        self.assertEqual(L["total"], 150)
        self.assertIsNone(last_payday_out(txns[2:3], D(2026, 11, 14)))   # 통장 자료가 지난 출금일까지 오지 않음

    def _prev(self, asof):
        row = lambda day, desc, amount, firm=True: {"date": day, "io": "out", "desc": desc, "amount": amount, "firm": firm,
                                                    "project": "", "cat": "미지급금"}
        return {"asof": asof, "rows": [row(D(2026, 11, 7), "㈜ 가상음향", 100),
                                       row(D(2026, 11, 7), "예상업체", 5, firm=False),     # 예상은 출금 목록에 없었음
                                       row(D(2026, 11, 7), "미확인업체", None),           # 금액 미확인도 목록에 없었음
                                       row(D(2026, 11, 12), "다음주업체", 5)]}           # 지난 출금일 뒤 = 그 주 목록 아님

    def test_only_vendors_that_were_on_last_weeks_list(self):
        from ceo_report.calc import last_payday_out
        txns = [_bt(D(2026, 11, 6), 100, "(주)가상음향"), _bt(D(2026, 11, 4), 40, "급한지급"),
                _bt(D(2026, 11, 7), 5, "예상업체"), _bt(D(2026, 11, 7), 3, "미확인업체"), _bt(D(2026, 11, 7), 5, "다음주업체")]
        L = last_payday_out(txns, D(2026, 11, 14), self._prev(D(2026, 11, 6)))
        self.assertEqual((L["listed"], L["prev_asof"]), (True, D(2026, 11, 6)))
        self.assertEqual([r["vendor"] for r in L["rows"]], ["(주)가상음향"])
        self.assertEqual(L["total"], 100)
        # 금요일(10/31)에 만든 보고는 다음 금요일(11/7) 목록이라 지난주 목록이다
        self.assertTrue(last_payday_out(txns, D(2026, 11, 14), self._prev(D(2026, 10, 31)))["listed"])
        # 지지난주(10/30, 출금일 10/31)에 만든 기록이면 지난주 목록이 아니다 → 그 주 통장 출금 전체 (자동 출금만 뺌)
        L = last_payday_out(txns, D(2026, 11, 14), self._prev(D(2026, 10, 30)))
        self.assertFalse(L["listed"])
        self.assertEqual(L["total"], 153)

    def test_line_names_the_week_and_leaves_out_auto_debits(self):
        import re
        from ceo_report.render import _vs_last_week
        R = {"asof": D(2026, 11, 13), "payday": D(2026, 11, 14),
             "last_pay": {"start": D(2026, 11, 1), "date": D(2026, 11, 7), "listed": True, "prev_asof": D(2026, 11, 6),
                          "rows": [{"vendor": "가상음향", "amount": 100, "memo": ""}], "total": 100}}
        P = {"rows": [{"desc": "가상음향", "amount": 120, "cat": "미지급금", "io": "out", "source": "자금계획서"},
                      {"desc": "강남세무서", "amount": 70, "cat": "원천세", "io": "out", "source": "자금계획서"},
                      {"desc": "", "amount": 30, "cat": "카드대금 (신한)", "io": "out", "source": "세금예상", "kind": "카드대금"}]}
        text = lambda h: re.sub(r"<[^>]+>", " ", h)
        ceo = text(_vs_last_week(R, P, "ceo"))
        self.assertIn("지난주 대비: 지난주(11/01~11/07) 출금 100 → 이번 출금 120 (+20) · 변동된 것 1건 +20 · 카드·세금 자동 출금은 빼고 비교", ceo)
        self.assertNotIn("추가된 것", ceo)
        mg = text(_vs_last_week(R, P, "mgmt"))
        self.assertIn("지난주 = 11/01~11/07 통장 출금 중 11/06 보고 출금 목록에 있던 거래처 것", mg)
        self.assertIn("이번 목록의 카드대금·세금·4대보험 2건 100은 비교에서 뺌", mg)
        R["last_pay"] = dict(R["last_pay"], listed=False, prev_asof=None)
        mg = text(_vs_last_week(R, P, "mgmt"))
        self.assertIn("지난주 보고 기록이 없어 그 주 통장 출금 전체와 비교", mg)
        R["last_pay"] = None
        self.assertIn("지난주(11/01~11/07) 출금 자료 없음", text(_vs_last_week(R, P, "ceo")))

    def test_report_uses_last_weeks_record(self):
        """보고서를 만들 때 지난주 보고가 남긴 지급 예정 기록(출력\\지급예정기록)으로 지난주 목록 거래처를 고른다."""
        import shutil
        import tempfile
        import 보고서
        from ceo_report import weekdiff
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        inp, out = os.path.join(tmp, "입력"), os.path.join(tmp, "출력")
        shutil.copytree(SAMPLE_DIR, inp)
        R0 = {"asof": D(2026, 10, 23), "events": [
            {"date": D(2026, 10, 27), "io": "out", "desc": "무대제작사", "project": "", "cat": "프로젝트지급", "amount": 11_000_000,
             "firm": True}]}
        weekdiff.write_record(out, R0)
        rc = 보고서.main(["주간", "--기준일", "2026-10-31", "--입력", inp, "--출력", out, "--pdf", "안함"])
        self.assertEqual(rc, 0)
        with open(os.path.join(out, "2026-10-31_주간_경영관리보고.html"), encoding="utf-8") as f:
            h = f.read()
        self.assertIn("지난주(10/24~10/30) 출금 11,000,000", h)
        self.assertIn("10/23 보고 출금 목록에 있던 거래처 것", h)


if __name__ == "__main__":
    unittest.main()
