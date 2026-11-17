"""2026-11-17 '비슷한 계산 오류 위험' 점검에서 사용자가 고치기로 정한 것 시험. 모두 가상 자료 (실제 자료는 열지 않는다)."""
import datetime as dt
import importlib
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def mod(name):
    return importlib.import_module("ceo_report." + name)


class _Books(object):
    def __init__(self, journal, slip_projects=None):
        self.journal = journal
        self.slip_projects = slip_projects or {}


def _row(day, no, code, account, debit, credit, vendor, memo=""):
    return {"date": day, "no": no, "account_code": code, "account": account, "debit": debit, "credit": credit,
            "vendor": vendor, "memo": memo}


D16, D23 = dt.date(2026, 10, 16), dt.date(2026, 10, 23)
PROJECTS = {"26116": {}, "26218": {}, "26243": {}}


class TempSlipOffsetTest(unittest.TestCase):
    """1번: 카드 한도결제 임시 전표(번호 있음)와 번호 없는 되돌림 전표는 서로 지워지므로 프로젝트 원가에서 뺀다."""

    def link(self, journal, slips, overrides=None):
        return mod("linking").link_costs(_Books(journal, slips), [], PROJECTS, overrides or {})

    def by_project(self, out):
        got = {}
        for ln in out["lines"]:
            got[ln["project"]] = got.get(ln["project"], 0) + ln["amount"]
        return got

    def test_group_and_single_reversal_drop_out(self):
        journal = [
            _row(D16, "1", "64500", "행사장임대료(도)", 4800000, None, "미확인거래처", "행사장대관잔금_가"),
            _row(D16, "2", "64500", "행사장임대료(도)", 18000000, None, "미확인거래처", "행사장대관잔금_나"),
            _row(D16, "21", "64500", "행사장임대료(도)", None, 22800000, "미확인거래처", "카드선결제대체"),
            _row(D23, "3", "64500", "행사장임대료(도)", 44000000, None, "미확인거래처", "행사장대관잔금_다"),
            _row(D23, "25", "64500", "행사장임대료(도)", None, 44000000, "미확인거래처", "카드선결제대체"),
            _row(D23, "30", "64500", "행사장임대료(도)", 7000000, None, "가상호텔", "실제 대관료"),
        ]
        slips = {(D16.isoformat(), "1"): "26218", (D16.isoformat(), "2"): "26243", (D23.isoformat(), "3"): "26116",
                 (D23.isoformat(), "30"): "26116"}
        out = self.link(journal, slips)
        self.assertEqual(self.by_project(out), {"26116": 7000000})   # 임시 4,400만은 빠지고 실제 원가만
        self.assertEqual(len(out["offset"]), 5)
        self.assertEqual(sum(x["amount"] for x in out["offset"]), 0)
        self.assertEqual(out["summary"]["미연결"]["count"], 0)

    def test_ambiguous_or_coded_reversal_is_left(self):
        journal = [
            _row(D16, "1", "64500", "행사장임대료(도)", 500000, None, "가상호텔"),
            _row(D16, "2", "64500", "행사장임대료(도)", 500000, None, "가상호텔"),
            _row(D23, "9", "64500", "행사장임대료(도)", None, 500000, "가상호텔", "환불"),          # 같은 금액 둘: 애매 → 그대로
            _row(D23, "10", "64500", "행사장임대료(도)", None, 300000, "가상조명", "[26116] 환불"),   # 번호 있는 환불 → 그대로
            _row(D16, "3", "64500", "행사장임대료(도)", 300000, None, "가상조명"),
        ]
        slips = {(D16.isoformat(), "1"): "26218", (D16.isoformat(), "2"): "26243", (D16.isoformat(), "3"): "26116"}
        out = self.link(journal, slips)
        self.assertEqual(out["offset"], [])
        self.assertEqual(self.by_project(out), {"26218": 500000, "26243": 500000, "26116": 0, None: -500000})

    def test_other_month_or_manual_line_is_left(self):
        nov = dt.date(2026, 11, 2)
        journal = [
            _row(D16, "1", "64500", "행사장임대료(도)", 500000, None, "미확인거래처"),
            _row(nov, "9", "64500", "행사장임대료(도)", None, 500000, "미확인거래처"),   # 다른 달 → 월별 손익이 바뀌므로 그대로
            _row(D23, "3", "64500", "행사장임대료(도)", 700000, None, "미확인거래처"),
            _row(D23, "4", "64500", "행사장임대료(도)", None, 700000, "미확인거래처"),
        ]
        slips = {(D16.isoformat(), "1"): "26218", (D23.isoformat(), "3"): "26116"}
        out = self.link(journal, slips, {(D23.isoformat(), "3", 1): "26243"})   # 수동 지정한 줄은 건드리지 않음
        self.assertEqual(out["offset"], [])


class CardGroupScheduleTest(unittest.TestCase):
    """2번: 카드값 일정(한 줄에 카드 거래처코드 여럿)에 든 카드 잔액은 '지급일이 일정에 없는 미지급금'에 넣지 않는다."""

    def test_card_event_covers_all_cards_once(self):
        asof = dt.date(2026, 11, 17)

        def pay(vcode, vendor, bal):
            return {"kind": "미지급금", "code": "26200", "account": "미지급비용", "vcode": vcode, "vendor": vendor,
                    "balance": bal, "date": "2026-11-16", "due": "", "due_basis": "", "opening": True}
        debts = [pay("137", "가상_1111", 4000000), pay("138", "가상_2222", 3000000), pay("1439", "다른_3333", 2000000),
                 pay("500", "가상업체", 700000)]
        events = [{"io": "out", "amount": 6500000, "date": dt.date(2026, 11, 20), "cat": "카드대금", "desc": "가상카드 11월 결제",
                   "vendor_code": "137 138 141"}]
        D = mod("debts").compare(debts, events, asof)
        left = dict((r["vendor"], r["left"]) for r in D["unscheduled"])
        # 가상카드 두 장 700만 중 650만은 일정에 있음 → 남는 50만만, 다른 카드사·일반 거래처는 그대로
        self.assertEqual(left, {"가상_2222": 500000, "다른_3333": 2000000, "가상업체": 700000})
        self.assertEqual(D["unscheduled_total"], 3200000)


if __name__ == "__main__":
    unittest.main()
