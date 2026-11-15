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
BASIS = ("세전 이익 147,000,000 − 감가상각비 예상 12,000,000 − 대손충당금 예상 5,000,000 + 세무조정 예상 3,000,000"
         " = 과세표준 133,000,000 → 법인세 13,300,000 − 중간예납 등 선납세금 4,000,000 · 대손충당금 = 외상 매출 1%")


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
        row["basis"], row["base"] = BASIS, 133_000_000
        cls.M = M

    def _render(self, mode):
        from ceo_report.render import render
        R = copy.deepcopy(self.M)
        return _text(render(R, mode))

    def test_bad_debt_row_in_both(self):
        for mode in ("ceo", "mgmt"):
            self.assertIn("대손충당금 (예상", self._render(mode), mode)

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


if __name__ == "__main__":
    unittest.main()
