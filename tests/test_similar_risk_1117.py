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


class StalePayableTest(unittest.TestCase):
    """3번: 6달 동안 한 번도 그 아래로 내려가지 않은 미지급 잔액은 따로 보인다."""

    def test_floor_of_last_180_days(self):
        debts = mod("debts")
        ref = dt.date(2026, 11, 17)
        moves = {dt.date(2025, 12, 31): 9000000, dt.date(2026, 5, 10): -400000}
        for m in range(6, 12):   # 매달 생긴 만큼만 나감
            moves[dt.date(2026, m, 5)] = 1000000
            moves[dt.date(2026, m, 10)] = -1000000
        e = {"unknown": False, "sum": sum(moves.values()), "moves": moves}
        self.assertEqual(debts._stale(e, ref), "8600000")
        fresh = {"unknown": False, "sum": 500000, "moves": {dt.date(2026, 10, 1): 500000}}   # 최근에 생긴 잔액
        self.assertEqual(debts._stale(fresh, ref), "")
        self.assertEqual(debts._stale(dict(e, unknown=True), ref), "")

    def test_compare_marks_stale_part_of_unscheduled(self):
        def pay(vcode, vendor, bal, stale):
            return {"kind": "미지급금", "code": "26200", "account": "미지급비용", "vcode": vcode, "vendor": vendor,
                    "balance": bal, "date": "2026-11-16", "due": "", "due_basis": "", "opening": True, "stale": stale}
        events = [{"io": "out", "amount": 900000, "date": dt.date(2026, 11, 27), "cat": "미지급금 지급", "desc": "가상업체",
                   "vendor_code": "500"}]
        D = mod("debts").compare([pay("147", "가상소득", 8600000, 8600000), pay("500", "가상업체", 1000000, 700000),
                                  pay("501", "새업체", 300000, 0)], events, dt.date(2026, 11, 17))
        got = dict((r["vendor"], r["stale"]) for r in D["unscheduled"])
        self.assertEqual(got, {"가상소득": 8600000, "가상업체": 100000, "새업체": 0})   # 일정에 없는 금액을 넘지 않음
        self.assertEqual((D["stale_total"], D["stale_n"]), (8700000, 2))


class SplitInvoiceAmongOthersTest(unittest.TestCase):
    """4번: 같은 날 같은 거래처 계산서가 여러 장이어도 나눈 계산서 두 줄은 자금계획서 한 줄과 합쳐 맞춘다 (두 번 잡지 않음)."""

    def ev(self, amount, project):
        return {"date": dt.date(2026, 12, 21), "io": "in", "amount": amount, "firm": False, "cat": "", "desc": "가상고객",
                "basis": "", "project": project, "source": "계산서", "vendor_code": "",
                "inv_key": ("가상고객", dt.date(2026, 10, 22))}

    def plan(self, amount):
        return {"date": dt.date(2026, 12, 24), "io": "입금", "cat": "", "vendor": "가상고객", "vendor_code": "", "amount": amount,
                "ym": "2026-12", "stamp": dt.date(2026, 11, 16), "state": "예정", "basis": "", "file": ""}

    def test_subset_of_same_day_invoices(self):
        inv = [self.ev(48000000, "P0"), self.ev(124000000, "P1"), self.ev(15000000, "P2")]
        new, _ = mod("fundplan").apply(inv, [self.plan(139000000), self.plan(48000000)], dt.date(2026, 11, 17), 7)
        self.assertEqual(sorted((e["source"], e["amount"]) for e in new), [("자금계획서", 48000000), ("자금계획서", 139000000)])

    def test_two_possible_subsets_are_left(self):
        inv = [self.ev(70000000, "P1"), self.ev(30000000, "P2"), self.ev(60000000, "P3"), self.ev(40000000, "P4")]
        new, _ = mod("fundplan").apply(inv, [self.plan(100000000)], dt.date(2026, 11, 17), 7)
        self.assertEqual(sum(1 for e in new if e["source"] == "계산서"), 4)   # 어느 묶음인지 몰라 그대로 둠


class CorpLocalTaxKindTest(unittest.TestCase):
    """6번: 법인지방소득세는 원천세가 아니다."""

    def test_regular_kind(self):
        rk = mod("render").regular_kind
        self.assertEqual(rk({"cat": "법인지방소득세 (장부 계산)", "desc": "2026년 귀속"}), "기타 세금")
        self.assertEqual(rk({"cat": "세금", "desc": "법인지방소득세 4월 납부"}), "기타 세금")
        self.assertEqual(rk({"cat": "법인세 (장부 계산)", "desc": ""}), "기타 세금")
        self.assertEqual(rk({"cat": "원천세 (장부 계산)", "desc": "근로소득세·지방소득세"}), "원천세")
        self.assertEqual(rk({"cat": "", "desc": "지방소득세 특별징수"}), "원천세")


class ProjectSgaCostTest(unittest.TestCase):
    """7번: 판관비 계정이라도 프로젝트 번호가 달려 있으면 그 프로젝트 원가 줄로 넣는다 (번호 없거나 목록에 없으면 안 넣음)."""

    def test_only_coded_sga_lines_join(self):
        journal = [
            _row(D16, "1", "64500", "행사장임대료(도)", 1000000, None, "가상호텔"),
            _row(D16, "5", "81201", "여비교통비_택시(판)", 30000, None, "가상택시", "[26116] 행사장 이동"),
            _row(D16, "6", "81201", "여비교통비_택시(판)", 20000, None, "가상택시", "사무실 이동"),
            _row(D16, "7", "81201", "여비교통비_택시(판)", 10000, None, "가상택시", "[99999] 없는 번호"),
            _row(D16, "8", "82600", "운반비(판)", 50000, None, "가상운송"),
        ]
        slips = {(D16.isoformat(), "1"): "26116", (D16.isoformat(), "8"): "26218"}
        out = mod("linking").link_costs(_Books(journal, slips), [], PROJECTS, {})
        got = sorted((ln["project"], ln["amount"], bool(ln.get("sga"))) for ln in out["lines"])
        self.assertEqual(got, [("26116", 30000, True), ("26116", 1000000, False), ("26218", 50000, True)])
        self.assertEqual((out["sga"]["count"], out["sga"]["total"], out["sga"]["months"]), (2, 80000, {"2026-10": 80000}))
        self.assertEqual(out["summary"]["미연결"]["count"], 0)

    def test_no_project_list_means_no_sga_lines(self):
        journal = [_row(D16, "5", "81201", "여비교통비_택시(판)", 30000, None, "가상택시", "[26116] 행사장 이동")]
        out = mod("linking").link_costs(_Books(journal), [], {}, {})
        self.assertEqual(out["lines"], [])


if __name__ == "__main__":
    unittest.main()
