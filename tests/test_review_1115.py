"""2026-11-15 실제 자료 비교(설치 전후 같은 자료)에서 찾은 오류를 다시 생기지 않게 막는 시험.

① 월 중간(11/14)에 만든 월간 보고: 변환은 다 끝난 달(10월)까지 장부로 법인세 줄을 만드는데, 보고는 11월 줄만 찾아
   대표용에서 대손충당금 예상 줄이 빠지고 경영관리용은 '세무조정 미반영'으로 나왔다.
② 자금계획서를 받았지만 줄이 없는 달(예: 지급 예정이 없는 달)을 '받지 못한 달'로 보아 그 기간 잔액을 비웠다.
"""
import copy
import datetime as dt
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report.calc import compute
from ceo_report.data import load

D = dt.date
SAMPLE_DIR = os.path.join(ROOT, "입력양식", "샘플")
# 규칙 계산-08 (결정 d, 2026-11-15): 대손충당금은 과세표준에서 빼지 않고 '쌓으면 세금 −X'만 근거에 적는다
BASIS = ("세전 이익 147,000,000 − 감가상각비 예상 12,000,000 + 세무조정 예상 3,000,000"
         " = 과세표준 138,000,000 → 법인세 13,800,000 − 중간예납 등 선납세금 4,000,000"
         " · 대손충당금 예상 5,000,000원은 세무사 확인 전이라 빼지 않음 (쌓으면 세금 −550,000원) · 대손충당금 = 외상 매출 1%")


def _text(h):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))


class TestMidMonthCorpTax(unittest.TestCase):
    """①: 11/14 월간 — 10월까지 장부로 만든 법인세 줄의 대손충당금·세무조정을 쓴다."""

    @classmethod
    def setUpClass(cls):
        os.environ["CEO_REPORT_TEST_GATE_OFF"] = "1"
        M = compute(load(SAMPLE_DIR), "monthly", D(2026, 11, 14))
        row = [t for t in M["tax"] if t["kind"] == "법인세"][0]
        assert row["period"].startswith("2026년 (1월~10월"), row["period"]
        row["basis"], row["base"] = BASIS, 138_000_000
        cls.M = M

    def _render(self, mode):
        from ceo_report.render import render
        R = copy.deepcopy(self.M)
        return _text(render(R, mode))

    def test_bad_debt_subtracted_in_both(self):
        # 11/15~11/17 판 파일('빼지 않음' 글)을 읽어도 사용자 2026-11-17대로 세전 이익에서 뺀다 (계산-08)
        for mode in ("ceo", "mgmt"):
            t = self._render(mode)
            self.assertIn("− 대손충당금 (예상", t, mode)
            self.assertNotIn("세무사 확인 전이라 빼지 않음", t, mode)

    def test_mgmt_uses_tax_adjustment_and_says_basis_month(self):
        t = self._render("mgmt")
        self.assertNotIn("세무조정 미반영", t)
        self.assertIn("세무조정·대손충당금은 10월까지 장부로 계산", t)
        m = re.search(r"<th>세전 이익</th>.*?<tbody><tr><td>([−\-\d,]+)</td><td>([−\-\d,]+)</td>",
                      __import__("ceo_report.render", fromlist=["render"]).render(copy.deepcopy(self.M), "mgmt"), re.S)
        self.assertIsNotNone(m)
        pretax, base = (int(x.replace(",", "").replace("−", "-")) for x in m.groups())
        self.assertEqual(base - pretax, 3_000_000)

    def test_month_end_mismatch_still_warns(self):
        """다 끝난 달(10/31) 보고인데 9월 줄이면 예전처럼 '세무조정 미반영' (자료 변환 필요)."""
        from ceo_report.render import render
        M = compute(load(SAMPLE_DIR), "monthly", D(2026, 10, 31))
        row = [t for t in M["tax"] if t["kind"] == "법인세"][0]
        row["period"] = "2026년 (1월~9월 장부 기준)"
        self.assertIn("세무조정 미반영", _text(render(M, "mgmt")))


class TestEmptyPlanMonth(unittest.TestCase):
    """②: 자금계획서를 받았지만 줄이 없는 달 — '받지 못한 달'이 아니다."""

    def R(self, months, received):
        def per(label, end):
            return {"label": label, "end": end, "firm": {"bal": 1, "low": 1, "low_date": end, "avail": 1},
                    "all": {"bal": 1, "low": 1, "low_date": end, "avail": 1}}
        return {"asof": D(2026, 10, 31), "fundplan": {"used": True, "months": months, "received": received},
                "s2": {"periods": [per("11월", D(2026, 11, 30)), per("12월", D(2026, 12, 31))]}}

    def test_received_empty_month_is_not_a_gap(self):
        from ceo_report import gate
        R = self.R(["2026-10", "2026-11"], ["2026-10", "2026-11", "2026-12"])
        self.assertEqual(gate.blank_plan_gaps(R), "")
        self.assertEqual([p["firm"]["avail"] for p in R["s2"]["periods"]], [1, 1])
        self.assertIn("2026-12", gate.blank_plan_gaps(self.R(["2026-10", "2026-11"], ["2026-10", "2026-11"])))

    def test_load_and_compute_carry_received_months(self):
        import shutil
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            shutil.copytree(SAMPLE_DIR, t, dirs_exist_ok=True)
            with open(os.path.join(t, "자금계획.csv"), "w", encoding="utf-8-sig") as f:
                f.write("예정일,입출금,분류,거래처,거래처코드,금액,대상월,자료일,파일,상태,근거,원전표,프로젝트\n"
                        "2026-11-20,지급,미지급금 지급,가상상사,000001,990000,2026-11,2026-10-30,a.json,예정,,,\n")
            with open(os.path.join(t, "자금계획받은달.csv"), "w", encoding="utf-8-sig") as f:
                f.write("대상월,자료일,파일\n2026-11,2026-10-30,a.json\n2026-12,2026-10-30,a.json\n")
            d = load(t)
            self.assertEqual(d.fundplan_received, ["2026-11", "2026-12"])
            R = compute(d, "weekly", D(2026, 10, 31))
            self.assertEqual(R["fundplan"]["received"], ["2026-11", "2026-12"])


class TestConvertWritesReceivedMonths(unittest.TestCase):
    """②: 변환이 자금계획서로 받은 달(줄 없는 달 포함)을 자금계획받은달.csv 에 적는다."""

    def test_empty_collected_month_listed(self):
        import json
        from test_convert import cli_argv, run_convert
        from test_convert import setUpModule as conv_setup
        from test_convert_e2e import full_company, read_csv_rows
        from test_fundplan_auto import COLS
        conv_setup()
        tmp, input_dir, collect, wehago_dir = full_company(self)
        rows = [["20261120", "지급", "102", "미지급금 지급", "0000000001", "가상상사", 990000, "매입", "매입매출", "20"]]
        doc = {"종류": "자금계획", "형식": 1, "수집시각": "2026-11-01 10:00:00", "회사": "가상회사",
               "기간": {"from": "20261101", "to": "20261231", "months": 2}, "조회한달": ["202611", "202612"],
               "오류": [], "줄수": len(rows), "열": COLS, "줄": rows}
        with open(os.path.join(wehago_dir, "261101 자금계획 자동수집.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False)
        run_convert(cli_argv(input_dir, collect, wehago_dir))
        got = read_csv_rows(os.path.join(input_dir, "자금계획받은달.csv"))
        self.assertEqual(got[0], ["대상월", "자료일", "파일"])
        self.assertEqual([r[0] for r in got[1:]], ["2026-11", "2026-12"])


class TestInvoiceCentsMatchPlan(unittest.TestCase):
    """③ (2026-11-15 실제 자료): 지난해 4원 더 받은 것이 올해 계산서에 붙어 미수 9,914,726 — 자금계획서 입금 9,914,730 과
    금액이 4원 달라 맞추지 못하고 같은 입금이 두 줄(계산서 추정 + 자금계획서)로 잡히던 것."""

    def test_same_client_small_diff_is_the_same_receipt(self):
        from ceo_report import fundplan
        from test_code_match_1114 import ev, plan_ev
        inv = dict(ev(D(2026, 11, 9), 9_914_726, "가상고객", source="계산서", io="in"), project="26225")
        new, info = fundplan.apply([inv], [plan_ev("2026-11-10", 9_914_730)], D(2026, 10, 31), 7)
        self.assertEqual([(e["source"], e["amount"]) for e in new], [("자금계획서", 9_914_730)])
        self.assertEqual(new[0]["project"], "26225")

    def test_other_client_small_diff_is_not(self):
        from ceo_report import fundplan
        from test_code_match_1114 import ev, plan_ev
        inv = ev(D(2026, 11, 9), 9_914_726, "다른고객", source="계산서", io="in")
        new, _ = fundplan.apply([inv], [plan_ev("2026-11-10", 9_914_730)], D(2026, 10, 31), 7)
        self.assertEqual(sorted(e["source"] for e in new), ["계산서", "자금계획서"])

    def test_big_diff_is_not(self):
        from ceo_report import fundplan
        from test_code_match_1114 import ev, plan_ev
        inv = ev(D(2026, 11, 9), 9_900_000, "가상고객", source="계산서", io="in")
        new, _ = fundplan.apply([inv], [plan_ev("2026-11-10", 9_914_730)], D(2026, 10, 31), 7)
        self.assertEqual(len(new), 2)


if __name__ == "__main__":
    unittest.main()
