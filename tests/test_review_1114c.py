"""2026-11-14 오후 점검 C 갈래 (팀장용·연간·예산) — 점검 문서 '숫자오차·오해소지·코드점검_20261114.md' 번호.

사용자 결정(11/14): 높음·중간 전부 + 7절 빼기 (규칙 바꾸는 T1·T5 포함). 경영관리 보고 내용은 빼지 않는다.
가상(샘플) 자료만 쓴다."""
import csv
import datetime as dt
import os
import shutil
import subprocess
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
MEND = dt.date(2026, 11, 30)


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
    # 11월 말일 기준 = 11월이 '끝난 달'. 11월 6일 기준이면 11월은 진행 중이라 처음부터 1년 환산에서 빠진다 (MidYearBudget)
    def test_month_without_salary_is_skipped(self):
        """11월 급여 전표가 아직 없으면(급여 0) 10월 급여로 잡는다 — 예전엔 내년 급여 0원."""
        base = self.B(MEND)

        def no_nov_salary(rows):
            for r in rows:
                if r["연월"] == "2026-11":
                    r["급여"] = "0"
        self.edit("부서비용.csv", no_nov_salary)
        B = self.B(MEND)
        self.assertEqual(B["last_ym"], "2026-10")
        self.assertEqual(B["sal_last"], base["sal_last"])
        self.assertEqual(B["Y"]["sal"], base["Y"]["sal"])
        self.assertEqual(sum(B["heads0"].values()), 8)
        self.assertTrue(any("급여 기준 달" in n and "2026-11" in n for n in B["notes"]), B["notes"])

    def test_month_with_one_department_only_is_skipped(self):
        """11월에 경영관리 한 부서 줄만 있으면 그 달은 기준으로 쓰지 않는다 (예전: 급여 300만·인원 1명)."""
        base = self.B(MEND)
        self.edit("부서비용.csv", lambda rows: [r for r in rows if r["연월"] != "2026-11" or r["부서"] == "경영관리"])
        B = self.B(MEND)
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


# ───────────── 연중 기준일 (사용자 2026-11-14: 연간·예산을 연말이 아닌 중도에 받아도 그 일자 기준으로 맞아야 함) ─────────────
def _annual_input():
    import annual_sample
    tmp = tempfile.mkdtemp()
    inp = os.path.join(tmp, "입력")
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_sample.py"), inp], check=True, stdout=subprocess.DEVNULL)
    annual_sample.extend(inp)
    return tmp, inp


def _csum(inp, year, upto, key):
    """손익.csv 회사 줄(WEHAGO)을 직접 더한 값 — 프로그램 계산과 따로 맞춰 보는 용도."""
    n = lambda v: int(str(v).replace(",", "") or 0)
    _, rows = rows_of(os.path.join(inp, "손익.csv"))
    return sum(n(r[key]) for r in rows if r["출처"] == "WEHAGO" and r["단위"] == "회사" and r["연월"][:4] == str(year) and int(r["연월"][5:7]) <= upto)


class MidYearAnnual(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.inp = _annual_input()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_period_rule(self):
        self.assertEqual(annual.period(2026, None), (12, dt.date(2026, 12, 31)))
        self.assertEqual(annual.period(2026, dt.date(2027, 2, 1)), (12, dt.date(2026, 12, 31)))
        self.assertEqual(annual.period(2026, dt.date(2026, 11, 14)), (10, dt.date(2026, 11, 14)))
        self.assertEqual(annual.period(2026, dt.date(2026, 6, 30)), (6, dt.date(2026, 6, 30)))   # 말일이면 그 달까지

    def test_nov14_uses_completed_months_and_same_period_last_year(self):
        A = annual.compute(self.inp, 2026, {}, None, dt.date(2026, 11, 14))
        Y, L = A["Y"], A["L"]
        self.assertEqual(max(Y["months"]), 10)
        self.assertEqual(max(L["months"]), 10)
        self.assertEqual(Y["rev"], _csum(self.inp, 2026, 10, "매출"))
        self.assertEqual(L["rev"], _csum(self.inp, 2025, 10, "매출"))   # 작년도 1~10월 (예전: 작년 한 해와 비교)
        # 통장: 기준일(11/14)까지의 마지막 잔액 = 10/28, 11월 뒤 칸은 비움
        self.assertEqual(A["bal_end"], A["bal_m"][9])
        self.assertTrue(all(v is None for v in A["bal_m"][10:]))
        # 결산 확정치(한 해 것)는 쓰지 않고 예상, 감가상각비는 월간처럼 한 해 예상을 먼저 뺌 — 작년 같은 기간도 같은 방식
        self.assertFalse(A["tax_fixed"])
        self.assertEqual(Y["dep_pending"], A["dep_est"])
        self.assertEqual(L["dep_pending"], A["Lfull"]["dep"])
        self.assertEqual(A["tax"], A["tax_est"])   # 1~10월 세전 이익 기준 예상

    def test_nov14_render_labels(self):
        A = annual.compute(self.inp, 2026, {}, None, dt.date(2026, 11, 14))
        for mode in ("ceo", "mgmt"):
            h = annual.render(A, mode)
            self.assertIn("2026-11-14", h)
            self.assertIn("2026-10-31", h)            # 손익 집계 기간 끝
            self.assertIn("2026년 1~10월 매출", h)
            self.assertNotIn("연말 통장 잔액", h)
            self.assertIn("기간 비례", h)
            self.assertNotIn("<td>2026-12-31</td>", h)
        mg = annual.render(A, "mgmt")
        self.assertIn("1~10월 이익 기준 예상", mg)
        self.assertNotIn("12월 결산 전표가 아직 없음", mg)   # 연중엔 '높음' 위험이 아님

    def test_june_blanks_months_not_ended(self):
        A = annual.compute(self.inp, 2026, {}, None, dt.date(2026, 6, 15))
        self.assertEqual(A["cut"], 5)
        self.assertEqual(A["Y"]["rev"], _csum(self.inp, 2026, 5, "매출"))
        self.assertEqual(A["L"]["rev"], _csum(self.inp, 2025, 5, "매출"))
        self.assertTrue(all(v is None for v in A["bal_m"][5:]))
        for T in A["teams"]:
            self.assertEqual(T["q"][2], (None, None))   # 3분기는 아직 시작 전 (0원으로 보이지 않게)
            self.assertEqual(T["q"][3], (None, None))
        self.assertTrue(all(v is None for v in A["Y"]["buy_m"][5:]))
        h = annual.render(A, "mgmt")
        self.assertIn("6월부터는 아직 끝나지 않은 달", h)

    def test_after_year_end_is_unchanged(self):
        a, b = annual.compute(self.inp, 2026, {}), annual.compute(self.inp, 2026, {}, None, dt.date(2027, 2, 1))
        for k in ("rev", "op", "pre"):
            self.assertEqual(a["Y"][k], b["Y"][k])
            self.assertEqual(a["L"][k], b["L"][k])
        self.assertEqual((a["tax"], a["bal_end"], a["cut"]), (b["tax"], b["bal_end"], 12))
        self.assertIn("연말 통장 잔액", annual.render(b, "ceo"))

    def test_projects_after_cut_not_counted(self):
        projs = {"P1": {"프로젝트명": "가", "팀": "기획1팀", "행사일": "2026-05-01"},
                 "P2": {"프로젝트명": "나", "팀": "기획1팀", "행사일": "2026-11-05"}}
        pl = [{"출처": "WEHAGO", "연월": "2026-05", "단위": "프로젝트", "대상": "P1 x", "매출": "100", "직접비": "60"},
              {"출처": "WEHAGO", "연월": "2026-11", "단위": "프로젝트", "대상": "P2 x", "매출": "100", "직접비": "60"}]
        self.assertEqual(len(annual._projects(pl, projs, "2026", "2025", {})["list"]), 2)
        self.assertEqual([x["id"] for x in annual._projects(pl, projs, "2026", "2025", {}, 10)["list"]], ["P1"])

    def test_cli_passes_today(self):
        out = os.path.join(self.tmp, "출력")
        env = dict(os.environ)
        env["CEO_REPORT_TEST_GATE_OFF"] = "1"
        r = subprocess.run([sys.executable, os.path.join(ROOT, "보고서.py"), "연간", "--기준일", "2026-11-14", "--입력", self.inp, "--출력", out,
                            "--pdf", "안함"], capture_output=True, text=True, env=env, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(os.path.join(out, "2026_연간_경영관리보고.html"), encoding="utf-8") as f:
            self.assertIn("2026-01-01 ~ 2026-10-31", f.read())


class MidYearBudget(Base):
    def test_partial_month_costs_not_annualized(self):
        """11월 6일에 만든 예산: 진행 중인 11월(비용 일부만 들어옴)은 판관비 1년 환산에서 뺀다."""
        base = self.B()

        def add_partial_nov(rows):
            extra = [dict(r, 연월="2026-11", 금액="1000") for r in rows if r["연월"] == "2026-10"]
            return rows + extra
        self.edit("계정별비용.csv", add_partial_nov)
        B = self.B()
        self.assertEqual(B["sga"], base["sga"])
        self.assertEqual(B["Y"]["nout"], base["Y"]["nout"])
        self.assertTrue(any("끝난 달(1~10월)" in n for n in B["notes"]), B["notes"])
        # 11월 말일에 만들면 11월이 끝난 달이라 들어간다 (그만큼 1년 환산이 바뀜)
        self.assertNotEqual(self.B(MEND)["sga"], base["sga"])

    def test_partial_month_salary_not_used(self):
        """11월 6일 기준: 11월 급여 줄이 있어도 진행 중인 달이라 급여 기준 달은 10월."""
        B = self.B()
        self.assertEqual(B["last_ym"], "2026-10")


# ───────────── 예산 급여·인원을 위하고 급여 화면·사원등록으로 (전수조사 제안 3-①⑤, 사용자 2026-11-14 '제안 전부') ─────────────
class WehagoPayBudget(Base):
    # 가상 사원 8명: 장부 부서비용(2026-10)과 같은 부서·급여 합계 (기획1팀 3명 900만, 기획2팀 3명 750만, 기획본부 1명 400만, 경영관리 1명 300만)
    STAFF = [("가", "기획1팀", 3000000), ("나", "기획1팀", 3000000), ("다", "기획1팀", 3000000),
             ("라", "기획2팀", 2500000), ("마", "기획2팀", 2500000), ("바", "기획2팀", 2500000),
             ("사", "기획본부", 4000000), ("아", "경영관리", 3000000)]

    def put(self, staff=None, extra_emps=(), months=range(1, 11)):
        staff = staff or self.STAFF
        with open(os.path.join(self.inp, "사원.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["사원명", "생년월일", "입사일", "퇴사일", "부서"])
            for n, dpt, _ in staff:
                w.writerow(["사원" + n, "", "2025-03-01", "", dpt])
            for row in extra_emps:
                w.writerow(row)
        with open(os.path.join(self.inp, "급여명세.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["연월", "사원명", "구분", "항목", "금액"])
            for m in months:
                for n, _, v in staff:
                    w.writerow(["2026-%02d" % m, "사원" + n, "지급", "지급합계", v])

    def WB(self, asof=ASOF):
        d = load(self.inp)
        return budget.compute(d, budget.read_values(self.inp), 2027, asof, d.settings, self.inp)

    def test_same_as_ledger_when_they_match(self):
        old = self.B()
        self.put()
        B = self.WB()
        self.assertEqual(B["sal_src"], "위하고 급여 화면·사원등록")
        self.assertEqual(B["last_ym"], "2026-10")
        self.assertEqual(B["sal_last"], 23500000)
        self.assertEqual(dict(B["heads0"]), {"기획1팀": 3, "기획2팀": 3, "기획본부": 1, "경영관리": 1})
        self.assertEqual(B["sal_last"], old["sal_last"])
        self.assertEqual(sum(B["heads0"].values()), sum(old["heads0"].values()))
        self.assertFalse(any("급여 화면과 다른 달" in n for n in B["notes"]), B["notes"])

    def test_payroll_screen_fills_month_before_ledger(self):
        """장부에 10월 급여 전표가 아직 없어도 급여 화면 10월로 잡고, 다른 달로 알림."""
        self.put()
        self.edit("부서비용.csv", lambda rows: [r for r in rows if r["연월"] != "2026-10"])
        B = self.WB()
        self.assertEqual(B["last_ym"], "2026-10")
        self.assertEqual(B["sal_last"], 23500000)
        self.assertTrue(any("2026-10 장부 급여 전표 없음" in n for n in B["notes"]), B["notes"])

    def test_left_and_joined_by_asof(self):
        """기준일까지 퇴사한 사람은 빼고, 기준 달 뒤 입사해 급여가 아직 없는 사람은 1인 평균으로 넣는다."""
        staff = self.STAFF[:]
        self.put(staff, extra_emps=[("사원자", "", "2026-11-02", "", "기획2팀")])
        with open(os.path.join(self.inp, "사원.csv"), encoding="utf-8-sig") as f:
            body = f.read().replace("사원가,,2025-03-01,,기획1팀", "사원가,,2025-03-01,2026-11-03,기획1팀")
        with open(os.path.join(self.inp, "사원.csv"), "w", encoding="utf-8-sig") as f:
            f.write(body)
        B = self.WB()
        self.assertEqual(B["heads0"]["기획1팀"], 2)
        self.assertEqual(B["heads0"]["기획2팀"], 4)
        self.assertEqual(B["sal_last"], 20500000 + int(round(20500000 / 7.0)))
        self.assertTrue(any("퇴사" in n for n in B["notes"]) and any("1인 평균" in n for n in B["notes"]), B["notes"])

    def test_no_names_in_documents(self):
        self.put()
        B = self.WB()
        for mode in ("ceo", "mgmt"):
            h = render_budget(B, mode, "")
            self.assertNotIn("사원가", h)
            if mode == "mgmt":
                self.assertIn("위하고 급여 화면·사원등록", h)

    def test_without_files_uses_ledger(self):
        B = self.WB()
        self.assertTrue(B["sal_src"].startswith("부서비용"))


# ───────────── 대출 원금 상환: 차입금현황 만기·상환 방식 + 장부 잔액 (전수조사 G2, 사용자 2026-11-14 '제안 전부') ─────────────
class LoanPlanBudget(Base):
    def put(self):
        from ceo_report import debts
        rows = [("차입금", "29300", "장기차입금", "301", "기업은행", "100,000,000"),
                ("차입금", "29300", "장기차입금", "302", "캐피탈갑", "12,000,000"),
                ("차입금", "26000", "단기차입금", "303", "은행을", "200,000,000"),
                ("차입금", "29300", "장기차입금", "304", "은행병", "50,000,000"),
                ("차입금", "26000", "단기차입금", "305", "은행정", "30,000,000"),
                ("차입금", "26000", "단기차입금", "306", "은행무", "40,000,000"),
                ("차입금", "26000", "단기차입금", "307", "은행기", "10,000,000")]
        with open(os.path.join(self.inp, debts.FILE), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(debts.KEYS)
            for r in rows:
                w.writerow(list(r) + ["2026-11-05", "", "", ""])
        with open(os.path.join(self.inp, budget.LOAN_FILE), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["차입처", "거래처코드", "계정코드", "차입일", "만기일", "상환방식", "원금", "월상환액", "자금용도", "만기근거", "매년연장"])
            w.writerow(["기업은행", "000301", "29300", "2025-03-31", "2027-03-31", "일시", "100,000,000", "", "운전자금"])
            # 위하고 원금·잔액은 쓰지 않는다 (상환 미갱신) — 장부 잔액 12,000,000 기준
            w.writerow(["캐피탈갑", "302", "29300", "2025-12-15", "2027-12-15", "분할", "20,000,000", "1,000,000", "차량"])
            w.writerow(["은행을", "303", "26000", "2025-04-17", "2026-04-17", "일시", "200,000,000", "", "운전자금"])   # 만기 지남(연장)
            w.writerow(["은행병", "304", "29300", "2026-01-10", "2029-01-10", "일시", "50,000,000", "", "시설"])
            # 연장한 대출: 사용자가 새 만기일을 직접 입력 (H 변환이 만기일에 넣고 만기근거='직접 입력')
            w.writerow(["은행정", "305", "26000", "2025-06-30", "2027-06-30", "일시", "30,000,000", "", "운전자금", "직접 입력"])
            # 매년 연장하는 대출 (사용자 11/14: 신한 기보 새 만기 2027-04-17, 매년 연장) — 만기 달에도 원금으로 안 잡음
            w.writerow(["은행무", "306", "26000", "2025-04-17", "2027-04-17", "일시", "40,000,000", "", "운전자금", "직접 입력", "예"])
            w.writerow(["은행기", "307", "26000", "2025-04-17", "2026-04-17", "일시", "10,000,000", "", "운전자금", "", "예"])

    def WB(self):
        d = load(self.inp)
        return budget.compute(d, budget.read_values(self.inp), 2027, ASOF, d.settings, self.inp)

    def test_lump_installment_and_overdue(self):
        before = self.B()
        self.put()
        B = self.WB()
        fx = B["cash"]["fixed"]
        self.assertEqual(fx[2], 100000000 + 1000000)        # 3월: 기업은행 만기 일시 (자금일정 차입금원금 1억과 겹치지 않음) + 분할 1백만
        self.assertEqual(fx[:11], [1000000, 1000000, 101000000, 1000000, 1000000, 31000000] + [1000000] * 5)   # 6월: 직접 입력 만기 3천만
        self.assertEqual(fx[11], 0)                         # 장부 잔액 12백만 = 2026-12 1번 + 2027-01~11 11번
        self.assertEqual(sum(fx), 100000000 + 30000000 + 11000000)
        self.assertTrue(any("은행정" in f["name"] and "직접 입력" in f["how"] for f in B["fix"]))
        self.assertFalse(any(x in f["name"] for f in B["fix"] for x in ("은행무", "은행기")))   # 매년 연장 → 원금 없음
        self.assertTrue(any("은행무" in n and "매년 연장 예정(만기 2027-04-17)" in n for n in B["notes"]), B["notes"])
        self.assertTrue(any("은행기" in n and "새 만기일 입력 필요" in n for n in B["notes"]), B["notes"])
        self.assertFalse(any("은행을" in f["name"] for f in B["fix"]))
        self.assertTrue(any("은행을" in n and "새 만기일을 직접 입력" in n for n in B["notes"]), B["notes"])
        self.assertFalse(any("은행병" in f["name"] for f in B["fix"]))   # 만기 2029 → 예산 연도엔 없음
        # 2026-12 분할 1백만은 연초 잔액에서 뺀다
        self.assertEqual(B["cash"]["start"], before["cash"]["start"] - 1000000)

    def test_without_file_keeps_schedule_rows(self):
        B = self.WB()
        self.assertEqual(B["cash"]["fixed"][2], 100000000)   # 자금일정.csv 차입금원금 그대로

    def test_interest_rows_not_dropped_from_start(self):
        """차입금.csv 가 있어도 자금일정의 차입금이자 줄은 연초 잔액 계산에 그대로 남는다."""
        before = self.B()
        self.put()
        B = self.WB()
        self.assertEqual(B["cash"]["roll_n"], before["cash"]["roll_n"] + 1)


class TeamLeaderPeriodEnd(TeamReportCase):
    """월 중간에 만든 팀장용: 기간 끝 = 기준일 (점검 P6). 말일에 만들면 말일."""
    def test_mid_month_end_is_asof(self):
        from ceo_report import teamreport
        _, R, T, _ = self.make()
        y, m = int(T["ym"][:4]), int(T["ym"][5:7])
        T = dict(T, asof=dt.date(y, m, 14))
        self.assertIn("%02d.14" % m, teamreport.render(T))
        last = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day
        T2 = dict(T, asof=dt.date(y + (m == 12), m % 12 + 1, 3))
        self.assertIn("~ %02d.%02d" % (m, last), teamreport.render(T2))
