"""2026-11-14 오후 점검 C 갈래 (팀장용·연간·예산) — 점검 문서 '숫자오차·오해소지·코드점검_20261114.md' 번호.

사용자 결정(11/14): 높음·중간 전부 + 7절 빼기 (규칙 바꾸는 T1·T5 포함). 경영관리 보고 내용은 빼지 않는다.
가상(샘플) 자료만 쓴다."""
import csv
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ceo_report import budget, calc, insights  # noqa: E402
from ceo_report.budget_render import render_budget  # noqa: E402
from ceo_report.corptax import corp_tax  # noqa: E402
from ceo_report.data import load  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
ASOF = dt.date(2026, 11, 6)


def rows_of(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f)
        return r.fieldnames, list(r)


def write_rows(path, cols, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\r\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in cols})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inp = os.path.join(self.tmp, "입력")
        shutil.copytree(SAMPLE, self.inp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def edit(self, name, fn):
        p = os.path.join(self.inp, name)
        cols, rows = rows_of(p)
        out = fn(rows)
        write_rows(p, cols, rows if out is None else out)

    def B(self, asof=ASOF):
        d = load(self.inp)
        return budget.compute(d, budget.read_values(self.inp), 2027, asof, d.settings)


# ───────────── 예산 ─────────────
class G1SalaryBaseMonth(Base):
    def test_month_without_salary_is_skipped(self):
        """11월 급여 전표가 아직 없으면(급여 0) 10월 급여로 잡는다 — 예전엔 내년 급여 0원."""
        base = self.B()

        def no_nov_salary(rows):
            for r in rows:
                if r["연월"] == "2026-11":
                    r["급여"] = "0"
        self.edit("부서비용.csv", no_nov_salary)
        B = self.B()
        self.assertEqual(B["last_ym"], "2026-10")
        self.assertEqual(B["sal_last"], base["sal_last"])
        self.assertEqual(B["Y"]["sal"], base["Y"]["sal"])
        self.assertEqual(sum(B["heads0"].values()), 8)
        self.assertTrue(any("2026-11" in n and "급여" in n for n in B["notes"]), B["notes"])

    def test_month_with_one_department_only_is_skipped(self):
        """11월에 경영관리 한 부서 줄만 있으면 그 달은 기준으로 쓰지 않는다 (예전: 급여 300만·인원 1명)."""
        base = self.B()
        self.edit("부서비용.csv", lambda rows: [r for r in rows if r["연월"] != "2026-11" or r["부서"] == "경영관리"])
        B = self.B()
        self.assertEqual(B["last_ym"], "2026-10")
        self.assertEqual(B["sal_last"], base["sal_last"])
        self.assertEqual(sum(B["heads0"].values()), 8)


class G2FixedPayments(Base):
    def test_loan_principal_in_cash_plan(self):
        """자금일정의 2027-03-31 차입금 원금 1억이 예산 자금 계획 3월 지급에 들어간다."""
        B = self.B()
        self.assertEqual(B["cash"]["fixed"][2], 100000000)
        self.assertTrue(any("차입금" in f["name"] and f["amount"] == 100000000 and f["month"] == 3 for f in B["fix"]))
        self.edit("자금일정.csv", lambda rows: [r for r in rows if r["분류"] != "차입금원금"])
        B2 = self.B()
        self.assertEqual(B2["cash"]["fixed"][2], 0)
        self.assertEqual(B2["cash"]["bal"][2] - B["cash"]["bal"][2], 100000000)

    def test_regular_costs_are_not_counted_twice(self):
        """급여·4대보험·세금·임차료·이자·카드는 예산 숫자에 이미 있어 정해진 지급에 다시 넣지 않는다."""
        B = self.B()
        for f in B["fix"]:
            if f.get("kind") == "fixed":
                self.assertFalse(any(w in f["name"] for w in ("급여", "4대보험", "임차료", "이자", "카드")), f)


class G3CorpTaxOneBasis(Base):
    def test_schedule_uses_same_profit_as_pl(self):
        B = self.B()
        L = B["L"]
        corp = corp_tax(L["pre"], 2026)
        fx = dict((f["day"], f) for f in B["fix"] if f.get("kind") != "fixed")
        self.assertEqual(fx["3/31"]["amount"], corp - 4000000)          # 기납부(중간예납) 400만 뺌
        self.assertEqual(fx["4/30"]["amount"], int(corp * 0.1))
        self.assertEqual(L["tax"], corp + int(corp * 0.1))             # 손익표와 같은 이익 기준
        self.assertNotIn("결산 후 확정", " ".join(f["src"] + f["how"] for f in B["fix"]))

    def test_card_says_split_payment(self):
        h = render_budget(self.B(), "ceo")
        self.assertNotIn("2028-03 납부", h)
        self.assertIn("2028년 3월", h)


class G4StartBalance(Base):
    def test_actual_flows_after_bank_date_counted(self):
        """잔액 날짜(11/2) 뒤 통장에서 나간 2,000만이 연초 잔액에 빠지지 않는다."""
        base = self.B()

        def add(rows):
            rows.append({"일자": "2026-11-04", "계좌명": "운영계좌", "입출금": "출금", "금액": "20,000,000", "분류": "회사공통지출",
                         "프로젝트번호": "", "거래처": "시험", "적요": "시험 출금"})
        self.edit("입출금내역.csv", add)
        B = self.B()
        self.assertEqual(base["cash"]["start"] - B["cash"]["start"], 20000000)


class G5InProgressMonth(Base):
    def test_current_month_booked_revenue_kept(self):
        """진행 중인 11월에 이미 잡힌 매출(장부)이 올해 매출에서 빠지지 않는다."""
        base = self.B()

        def more(rows):
            for r in rows:
                if r["연월"] == "2026-11" and r["대상"] == "기획1팀":
                    r["매출"] = "{:,}".format(16500000 + 10000000)
        self.edit("손익.csv", more)
        B = self.B()
        self.assertEqual(B["T"]["기획1팀"]["base_rev"] - base["T"]["기획1팀"]["base_rev"], 10000000)

    def test_left_is_estimate_minus_booked(self):
        """프로젝트 남은 매출 = 사전견적 − 매출반영누계 (같은 계산 calc.revenue_left)."""
        def rec(rows):
            for r in rows:
                if r["프로젝트번호"] == "P26201":
                    r["매출반영누계"] = "100,000,000"
        base = self.B()
        self.edit("프로젝트.csv", rec)
        B = self.B()
        self.assertEqual(base["T"]["기획1팀"]["base_rev"] - B["T"]["기획1팀"]["base_rev"], 100000000)


class G6G7CashWords(Base):
    def test_month_end_wording(self):
        for mode in ("ceo", "mgmt"):
            h = render_budget(self.B(), mode)
            self.assertNotIn("1년 내내", h)
        h = render_budget(self.B(), "ceo")
        self.assertIn("매달 말 잔액", h)

    def test_collect_days_default_60_with_few_invoices(self):
        B = self.B()
        self.assertEqual(B["cash"]["days_used"], 60)
        self.assertIn("60일", render_budget(B, "mgmt"))


class Sec7Budget(Base):
    def test_depreciation_not_in_ceo_payment_list(self):
        B = self.B()
        self.assertNotIn("감가상각비 (비용만", render_budget(B, "ceo"))
        self.assertIn("감가상각비 (비용만", render_budget(B, "mgmt"))   # 경영관리는 그대로


# ───────────── T1 이익 흐름·경보 ─────────────
class T1ProfitFlow(Base):
    def R(self):
        d = load(self.inp)
        return calc.compute(d, "monthly", dt.date(2026, 10, 31))

    def test_intranet_request_counts_for_profit_not_funds(self):
        R = self.R()
        P = [p for p in R["s3"]["projects"] if p["id"] == "P26201"][0]
        self.assertEqual(P["intranet_req"], 40000000)
        self.assertEqual(P["committed"], P["expected"] + 40000000)
        self.assertEqual(P["remain"], P["budget"] - P["expected"])          # 자금(남은 예산) 규칙은 그대로
        self.assertEqual(P["profit_now"], P["contract"] - max(P["committed"], P["budget"]))

    def test_over_budget_alert_uses_committed(self):
        R = self.R()
        al = [t for lv, t in insights.alerts(R) if t.startswith("[P26201]")]
        self.assertTrue(any("추정 예산" in t and "넘음" in t for t in al), al)

    def test_in_progress_never_shows_improvement(self):
        R = self.R()
        for f in insights.profit_flow(R):
            if not f["closed"]:
                self.assertLessEqual(f["diff"], 0, f)


class RevenueLeft(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(calc.revenue_left({"estimate": 100, "recognized": 40}), 60)
        self.assertEqual(calc.revenue_left({"estimate": 100, "recognized": 140}), 0)
        self.assertIsNone(calc.revenue_left({"estimate": 100, "recognized": None}))
        self.assertIsNone(calc.revenue_left({"estimate": None, "recognized": 0}))
        self.assertEqual(calc.revenue_left({"estimate": 100, "quote": 90, "approval": "대표이사", "recognized": 40}), 50)


# ───────────── 팀장용 T2·T3·T5 ─────────────
from test_teamreport import TeamReportCase, _append, text  # noqa: E402


class TeamLeaderExpectation(TeamReportCase):
    def _rec(self, pid, amount):
        p = os.path.join(self.folder, "프로젝트.csv")
        cols, rows = rows_of(p)
        for r in rows:
            if r["프로젝트번호"] == pid:
                r["매출반영누계"] = "{:,}".format(amount)
        write_rows(p, cols, rows)

    def test_t2_cost_booked_before_event_not_subtracted_twice(self):
        """행사 전에 원가 2,000만이 먼저 잡혀도 이익 예상은 사전견적 − 추정 예산 그대로 (예전엔 2,000만 더 빠짐)."""
        _, _, before, _ = self.make()
        _append(os.path.join(self.folder, "손익.csv"), [
            {"출처": "WEHAGO", "연월": "2026-10", "단위": "프로젝트", "대상": "P26201 A사 연례 컨퍼런스", "매출": "0", "직접비": "20,000,000"}])
        p = os.path.join(self.folder, "손익.csv")
        cols, rows = rows_of(p)
        for r in rows:   # 팀 줄에도 같은 원가 (장부는 팀 합계에도 잡힘)
            if r["연월"] == "2026-10" and r["단위"] == "팀" and r["대상"] == "기획1팀":
                r["직접비"] = "{:,}".format(67320000 + 20000000)
        write_rows(p, cols, rows)
        _, _, after, _ = self.make()
        self.assertEqual(after["tot"]["gp"], before["tot"]["gp"] - 20000000)
        self.assertEqual(after["exp_gp"], before["exp_gp"])

    def test_t3_partly_booked_project_keeps_rest(self):
        """A사 3억 중 1억이 매출로 잡혀도 남은 2억은 올해 매출 예상에 남는다 (예전엔 통째로 빠짐)."""
        _, _, before, _ = self.make()
        self._rec("P26201", 100000000)
        p = os.path.join(self.folder, "손익.csv")
        cols, rows = rows_of(p)
        for r in rows:
            if r["연월"] == "2026-10" and r["단위"] == "팀" and r["대상"] == "기획1팀":
                r["매출"] = "{:,}".format(99000000 + 100000000)
        write_rows(p, cols, rows)
        _append(p, [{"출처": "WEHAGO", "연월": "2026-10", "단위": "프로젝트", "대상": "P26201 A사 연례 컨퍼런스",
                     "매출": "100,000,000", "직접비": "0"}])
        _, _, after, page = self.make()
        self.assertEqual(after["exp_rev"], before["exp_rev"])
        self.assertIn("P26201", [r["id"] for r in after["up"]])   # 끝나지 않았으니 진행 표에 남음

    def test_t5_usable_budget_column(self):
        _, R, T, page = self.make()
        a = [r for r in T["up"] if r["id"] == "P26201"][0]
        P = [p for p in R["s3"]["projects"] if p["id"] == "P26201"][0]
        self.assertEqual(a["left"], a["budget"] - a["paid"])          # 11/9 정의 그대로
        self.assertEqual(a["avail"], a["budget"] - P["committed"])     # 요청(장부 전 지급요청 포함)·계획까지 뺀 것
        self.assertLess(a["avail"], 0)
        self.assertIn("쓸 수 있는 남은 예산", text(page))
        self.assertNotIn("70%", page)


# ───────────── 연간 Y1·Y2 ─────────────
from ceo_report import annual  # noqa: E402


class AnnualProjects(unittest.TestCase):
    PROJS = {"P1": {"프로젝트명": "가", "팀": "기획1팀", "행사일": "2026-05-01"},
             "P2": {"프로젝트명": "나", "팀": "기획1팀", "행사일": "2026-06-01"},
             "P3": {"프로젝트명": "다", "팀": "기획1팀", "행사일": "2026-07-01"}}

    def row(self, pid, rev, cost, src="WEHAGO"):
        return {"출처": src, "연월": "2026-05", "단위": "프로젝트", "대상": "%s x" % pid, "매출": rev, "직접비": cost}

    def test_y1_blank_cost_is_unknown_not_100pct(self):
        pl = [self.row("P1", "100", "40"), self.row("P2", "300", "180"), self.row("P3", "50", "")]
        PR = annual._projects(pl, self.PROJS, "2026", "2025", {})
        P3 = [x for x in PR["list"] if x["id"] == "P3"][0]
        self.assertIsNone(P3["rate"])
        st = annual.proj_stats(PR["list"])
        self.assertEqual((st["known"], st["unknown"]), (2, 1))
        self.assertAlmostEqual(st["avg"], (60 + 120) / 400.0)   # 매출 가중 45%, 예전 단순 평균 (60+40+100)/3

    def test_y2_old_intranet_row_not_added_to_ledger(self):
        pl = [self.row("P1", "100", "80"), self.row("P1", "100", "60", "인트라넷완료보고")]
        PR = annual._projects(pl, self.PROJS, "2026", "2025", {})
        self.assertAlmostEqual(PR["list"][0]["rate"], 0.2)

    def test_ceo_line_counts_instead_of_average(self):
        import annual_sample
        tmp = tempfile.mkdtemp()
        try:
            inp = os.path.join(tmp, "입력")
            shutil.copytree(SAMPLE, inp)
            annual_sample.extend(inp)
            A = annual.compute(inp, 2026, {})
            ceo, mg = annual.render(A, "ceo"), annual.render(A, "mgmt")
            self.assertIn("원가 확인", ceo)
            self.assertNotIn("1분기 → 4분기", ceo)
            self.assertIn("1분기 → 4분기", mg)     # 경영관리는 그대로
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ───────────── K7 자료가 막히면 경영관리도 자금 숫자만 비움 ─────────────
class K7Blank(Base):
    def test_budget_mgmt_keeps_items_blanks_cash(self):
        B = self.B()
        h = render_budget(budget.blank_cash(B), "mgmt")
        self.assertIn("월별 통장 잔액 숫자를 비웠습니다", h)
        self.assertIn("2. 손익 예산", h)                      # 손익 예산은 그대로
        lo = B["cash"]["bal"][B["cash"]["lo"]]
        self.assertNotIn("{:,}".format(lo), h)

    def test_annual_mgmt_keeps_items_blanks_cash(self):
        import annual_sample
        annual_sample.extend(self.inp)
        A = annual.compute(self.inp, 2026, {})
        h = annual.render(annual.blank_cash(A), "mgmt")
        self.assertIn("통장 숫자를 비웠습니다", h)
        self.assertIn("현금흐름표 숫자를 비웠습니다", h)
        if A["bal_end"]:
            self.assertNotIn("{:,}".format(A["bal_end"]), h)

    def test_cli_uses_blank(self):
        import subprocess
        out = os.path.join(self.tmp, "출력")
        r = subprocess.run([sys.executable, os.path.join(ROOT, "예산.py"), "--입력", self.inp, "--출력", out, "--연도", "2027", "--pdf", "안함"],
                           capture_output=True, text=True,
                           env=dict([(k, v) for k, v in os.environ.items() if k != "CEO_REPORT_TEST_GATE_OFF"], PYTHONUTF8="1"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        mg = [f for f in os.listdir(os.path.join(out, "예산")) if "경영관리" in f and f.endswith(".html")][0]
        with open(os.path.join(out, "예산", mg), encoding="utf-8") as f:
            h = f.read()
        self.assertIn("월별 통장 잔액 숫자를 비웠습니다", h)   # 샘플엔 자금계획서가 없어 막힘


if __name__ == "__main__":
    unittest.main()
