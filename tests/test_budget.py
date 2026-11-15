"""내년 예산 (사용자 2026-11-10): 값 저장·계산·확정·월간 보고 '예산 대비'. 가상 자료만."""
import csv
import datetime as dt
import os
import re
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import app, budget  # noqa: E402
from ceo_report.budget_render import render_budget  # noqa: E402
from ceo_report.areas import strip_ui  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import render  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
ASOF = dt.date(2026, 11, 6)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inp = os.path.join(self.tmp, "입력")
        shutil.copytree(SAMPLE, self.inp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def B(self):
        d = load(self.inp)
        return budget.compute(d, budget.read_values(self.inp), 2027, ASOF, d.settings)


class Values(Base):
    def test_save_read_and_clear(self):
        n = budget.save_values(self.inp, 2027, [("성장률", "기획1팀", "10"), ("급여인상률", "", "5%")])
        self.assertEqual(n, 2)
        V = budget.read_values(self.inp)
        self.assertEqual(V[("2027", "성장률", "기획1팀")], 10)
        self.assertEqual(V[("2027", "급여인상률", budget.COMPANY)], 5)
        budget.save_values(self.inp, 2027, [("성장률", "기획1팀", "")])
        self.assertNotIn(("2027", "성장률", "기획1팀"), budget.read_values(self.inp))

    def test_bad_values(self):
        for items in ([("입사월", "기획1팀", "13")], [("늘릴인원", "기획1팀", "1.5")], [("성장률", "", "10")], [("성장률", "기획1팀", "열")]):
            with self.assertRaises(ValueError):
                budget.save_values(self.inp, 2027, items)
        with self.assertRaises(ValueError):
            budget.save_values(self.inp, "27", [("성장률", "기획1팀", "1")])

    def test_text(self):
        budget.save_values(self.inp, 2027, [("성장률", "기획2팀", "15"), ("늘릴인원", "기획2팀", "1"), ("입사월", "기획2팀", "4")])
        t = budget.values_text(self.inp, 2027)
        self.assertIn("기획2팀 성장 +15%", t)
        self.assertIn("+1명 4월", t)
        self.assertIn("급여 인상 입력 전", t)


class Compute(Base):
    def test_totals_add_up(self):
        budget.save_values(self.inp, 2027, [("성장률", "기획1팀", "10"), ("성장률", "기획2팀", "15"), ("늘릴인원", "기획2팀", "1"),
                                            ("입사월", "기획2팀", "4"), ("급여인상률", "", "5"), ("물가인상률", "", "3")])
        B = self.B()
        self.assertEqual(B["teams"], ["기획1팀", "기획2팀"])
        for t in B["teams"]:
            R = B["T"][t]
            self.assertEqual(sum(R["rev"]), R["budget"])                       # 달별 합 = 연 예산
            self.assertEqual(R["budget"], budget._r4(R["base_rev"] * (1 + R["growth"] / 100.0)))
            self.assertTrue(all(R["rev"][i] >= R["got"][i] for i in range(12)))  # 이미 받은 일보다 작지 않게
        Y = B["Y"]
        self.assertEqual(Y["rev"], sum(B["rev"]))
        self.assertEqual(Y["op"], Y["gp"] - Y["sal"] - Y["dep"] - Y["sga"])
        self.assertEqual(Y["pre"], Y["op"] + Y["nin"] - Y["nout"])
        # 급여: 4월부터 한 명 더
        self.assertGreater(B["sal"][3], B["sal"][2])
        self.assertEqual(B["sal"][0], budget._r4(23_500_000 * 1.05))
        self.assertEqual(B["heads"][-1], B["heads"][0] + 1)
        # 목표 수익률 2027 없음 → 1 − 원가율 0.70
        self.assertAlmostEqual(B["T"]["기획1팀"]["rate"], 0.30)
        self.assertIn("목표 수익률", B["missing"])
        # 자금: 월말 = 월초 + 입금 − 지급 + 영업외
        c = B["cash"]
        b = c["avail0"] + c["roll"]   # 오늘 쓸 수 있는 돈 + 연말까지 입출금 예상 = 1월 월초 (2026-11-14 오후 점검 G4)
        self.assertEqual(c["start"], b)
        for i in range(12):   # 정해진 지급(대출 원금 등, G2)도 뺀다
            b = b + c["cin"][i] - (c["cpay"][i] + B["sal"][i] + c["sga_pay"][i] + c["tax"][i] + c["fixed"][i]) + c["nio"][i]
            self.assertEqual(c["bal"][i], b)

    def test_target_rate_used(self):
        with open(os.path.join(self.inp, "팀목표.csv"), "a", encoding="utf-8") as f:
            f.write("2027,기획1팀,1000000000,35\n")
        B = self.B()
        self.assertAlmostEqual(B["T"]["기획1팀"]["rate"], 0.35)
        self.assertTrue(B["T"]["기획1팀"]["rate_set"])

    def test_tax_schedule_from_tax_file(self):
        B = self.B()
        names = [(f["day"], f["amount"]) for f in B["fix"]]
        self.assertIn(("1/25", 21_000_000), names)   # 세금예상 부가세 4분기
        # 법인세·지방세는 손익표와 같은 연말 예상 세전 이익 기준, 기납부 400만(세금예상)만 빼다 (2026-11-14 오후 점검 G3)
        from ceo_report.corptax import corp_tax
        lc = corp_tax(B["L"]["pre"], 2026)
        self.assertIn(("3/31", lc - 4_000_000), names)
        self.assertIn(("4/30", int(lc * 0.1)), names)
        self.assertIn(("8/31", budget._r4(lc / 2.0)), names)    # 중간예납 = 산출세액 ÷ 2

    def test_render_both(self):
        B = self.B()
        ceo, mg = render_budget(B, "ceo", "샘플"), render_budget(B, "mgmt", "샘플")
        self.assertIn("2027년 예산 계획 (초안)", ceo)
        self.assertNotIn("쓴 자료", ceo)
        self.assertIn("쓴 자료", mg)
        # 경영관리용만 영역별 보기 (사용자 2026-11-11): 요약+1절, 그다음 절마다 한 영역. 대표용은 그대로 문서
        ids = re.findall(r"<section class='area' id='a-(b\d+)' data-label='([^']+)'", mg)
        self.assertEqual(ids[0], ("b0", "요약 · 1. 정해야 할 값"))
        self.assertEqual(ids[-1][1], "%d. 쓴 자료 · 확인할 것" % len(ids))
        self.assertIn(("b1", "2. 손익 예산"), ids)
        self.assertEqual(mg.count("<div"), mg.count("</div>"))
        self.assertNotIn("<script", ceo)
        self.assertNotIn("<script", strip_ui(mg))
        self.assertIn("입력 전", ceo)
        self.assertIn("확정 2026-11-06", render_budget(B, "ceo", "", "2026-11-06"))


class ConfirmAndMonthly(Base):
    def test_confirm_roundtrip(self):
        B = self.B()
        n = budget.confirm(self.inp, B, ASOF)
        self.assertEqual(n, 12 * (len(B["teams"]) + 1))
        C = budget.read_confirmed(self.inp)["2027"]
        self.assertEqual(C["date"], "2026-11-06")
        self.assertEqual(sum(C["rows"][(m, budget.COMPANY)]["매출"] for m in range(1, 13)), B["Y"]["rev"])
        budget.confirm(self.inp, B, ASOF)   # 다시 확정해도 그 해 줄은 바뀌기만
        self.assertEqual(sum(1 for (m, w) in budget.read_confirmed(self.inp)["2027"]["rows"]), n)

    def test_monthly_budget_table(self):
        with open(os.path.join(self.inp, budget.CONFIRM_FILE), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(budget.CONFIRM_COLUMNS)
            for m in range(1, 13):
                w.writerow([2026, m, "기획1팀", 70_000_000, 21_000_000, "", "", "", "", "", "2025-12-20"])
                w.writerow([2026, m, "기획2팀", 60_000_000, 18_000_000, "", "", "", "", "", "2025-12-20"])
                w.writerow([2026, m, budget.COMPANY, 130_000_000, 39_000_000, 23_500_000, 6_000_000, 1_000_000, 0, 500_000, "2025-12-20"])
        R = compute(load(self.inp), "monthly", dt.date(2026, 10, 31))
        B = R["budget_cmp"]
        self.assertEqual(B["month"], 10)
        r1 = [r for r in B["rows"] if r["team"] == "기획1팀"][0]
        self.assertEqual(r1["ytd_b"], 700_000_000)
        self.assertEqual(B["tot"]["ytd_b"], 1_300_000_000)
        ceo, mg = render(R, "ceo"), render(R, "mgmt")
        self.assertIn("예산 대비 (2025-12-20 확정 예산)", ceo)
        self.assertNotIn("1~10월 누적 (회사)", ceo)
        self.assertIn("1~10월 누적 (회사)", mg)

    def test_no_budget_no_table(self):
        R = compute(load(self.inp), "monthly", dt.date(2026, 10, 31))
        self.assertIsNone(R["budget_cmp"])
        self.assertNotIn("확정 예산)", render(R, "ceo"))


class AppTask(Base):
    def test_task_argv(self):
        P = app.Paths(self.tmp) if hasattr(app, "Paths") else None
        if P is None:
            self.skipTest("Paths 없음")
        name, argv = app.task_argv("예산확정", P, "2026-11-06", year="2027")
        self.assertEqual(name, "예산")
        self.assertEqual(argv[:4], ["--기준일", "2026-11-06", "--연도", "2027"])
        self.assertEqual(argv[-2:], ["--확정", "함"])
        with self.assertRaises(ValueError):
            app.task_argv("예산", P, "2026-11-06", year="27")

    def test_cli_makes_files(self):
        import 예산
        out = os.path.join(self.tmp, "출력")
        rc = 예산.main(["--기준일", "2026-11-06", "--입력", self.inp, "--출력", out, "--pdf", "안함"])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(os.path.join(out, "예산", "2027_예산_대표용.html")))
        self.assertTrue(os.path.exists(os.path.join(out, "예산", "2027_예산_경영관리용.html")))
        self.assertFalse(os.path.exists(os.path.join(self.inp, budget.CONFIRM_FILE)))
        rc = 예산.main(["--기준일", "2026-11-06", "--입력", self.inp, "--출력", out, "--pdf", "안함", "--확정", "함"])
        self.assertEqual(rc, 0)
        self.assertIn("2027", budget.read_confirmed(self.inp))


if __name__ == "__main__":
    unittest.main()
