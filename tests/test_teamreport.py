"""팀장용 월간 실적 문서 (사용자 2026-11-05 목업, 2026-11-09 승인). 가상 자료만 쓴다."""
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
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from ceo_report import convert, convert_pl, teamreport  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from test_dept import Books, line  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
ASOF = dt.date(2026, 10, 31)
TODAY = dt.date(2026, 11, 5)


def _append(path, rows):
    with open(path, encoding="utf-8-sig", newline="") as f:
        head = next(csv.reader(f))
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        for r in rows:
            w.writerow([r.get(h, "") for h in head])


def text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def has_amount(body, n):
    """숫자 n 이 다른 숫자의 일부(예: 99,000,000 안의 9,000,000)가 아니라 그 자체로 있는지."""
    return re.search(r"(?<![\d,])%s(?![\d,])" % re.escape("{:,}".format(n)), body) is not None


class TeamReportCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.folder = os.path.join(self.tmp, "입력")
        shutil.copytree(SAMPLE, self.folder)
        # 기획1팀 프로젝트 줄 (가상): 9월 P26205 매출·원가, 10월 P26205 원가 일부. 10월 팀 합계 99,000,000 중 프로젝트로 나눈 것은 일부뿐
        _append(os.path.join(self.folder, "손익.csv"), [
            {"출처": "WEHAGO", "연월": "2026-09", "단위": "프로젝트", "대상": "P26205 E사 파트너 포럼", "매출": "60,000,000",
             "직접비": "45,000,000"},
            {"출처": "WEHAGO", "연월": "2026-10", "단위": "프로젝트", "대상": "P26205 E사 파트너 포럼", "매출": "0",
             "직접비": "1,000,000"},
            {"출처": "WEHAGO", "연월": "2026-10", "단위": "프로젝트", "대상": "프로젝트 미연결", "매출": "99,000,000",
             "직접비": "66,320,000"},
            {"출처": "WEHAGO", "연월": "2026-10", "단위": "프로젝트", "대상": "P26203 C사 전시 부스", "매출": "5,000,000",
             "직접비": "1,000,000"},   # 기획2팀
        ])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, team="기획1팀"):
        d = load(self.folder)
        R = compute(d, "monthly", ASOF)
        T = teamreport.build(d, R, team)
        return d, R, T, teamreport.render(T, TODAY)


class TestNumbers(TeamReportCase):
    def test_months_totals_and_target(self):
        d, R, T, page = self.make()
        self.assertEqual(teamreport.team_names(d), ["기획1팀", "기획2팀"])
        cur = T["months"][-1]
        self.assertEqual((cur["revenue"], cur["cost"], cur["gp"], cur["sga"], cur["op"]),
                         (99_000_000, 67_320_000, 31_680_000, 2_000_000, 29_680_000))
        self.assertEqual(T["tot"]["revenue"], sum(x["revenue"] for x in T["months"]))
        self.assertEqual(T["tot"]["sga"], 20_000_000)
        self.assertEqual((T["t_rev"], T["t_rate"], T["t_gp"]), (900_000_000, 30.0, 270_000_000))
        # 팀 판관비 계정별 합계 = 부서비용 판관비
        self.assertEqual(sum(a["total"] for a in T["acc"]), T["tot"]["sga"])

    def test_projects_split_with_gap_row(self):
        d, R, T, page = self.make()
        self.assertEqual([r["id"] for r in T["ytd"]], ["P26205"])   # 다른 팀(P26203)·미연결 줄은 넣지 않음
        p = T["ytd"][0]
        self.assertEqual((p["revenue"], p["cost"], p["months"]), (60_000_000, 46_000_000, "9월~10월"))
        self.assertEqual(T["cur"][0]["cost"], 1_000_000)
        # 차이 줄 + 프로젝트 = 팀 합계
        self.assertEqual(T["cur_gap"]["revenue"] + T["cur"][0]["revenue"], 99_000_000)
        self.assertEqual(T["ytd_gap"]["cost"] + p["cost"], T["tot"]["cost"])
        self.assertIn("프로젝트로 나누지 못한 금액", page)
        self.assertIn("[P26205] E사 파트너 포럼", page)

    def test_low_margin_underlined(self):
        d, R, T, page = self.make()
        self.assertIn("class='low'>23.3%", page)   # 14,000,000 ÷ 60,000,000 < 목표 30% − 4%p

    def test_upcoming_uses_team_target_budget(self):
        d, R, T, page = self.make()
        ids = [r["id"] for r in T["up"]]
        self.assertIn("P26201", ids)
        self.assertNotIn("P26208", ids)   # 2027 행사
        a = [r for r in T["up"] if r["id"] == "P26201"][0]
        self.assertEqual(a["budget"], round(300_000_000 * 0.70))   # 기획1팀 목표 수익률 30%
        self.assertEqual(a["left"], a["budget"] - a["paid"])
        self.assertEqual(T["up_missing"], 1)   # P26204 사전견적 없음
        self.assertIn("사전견적 또는 추정 예산이 없는 1건", page)
        self.assertEqual(T["exp_rev"], T["tot"]["revenue"] + 300_000_000)


class TestDocumentRules(TeamReportCase):
    def test_no_salary_amounts_and_exclusion_notice(self):
        d, R, T, page = self.make()
        body = text(page)
        for r in d.dept:
            if r["dept"] == "기획1팀" and r["salary"]:
                self.assertFalse(has_amount(body, r["salary"]), r["salary"])
        self.assertNotIn("급여 반영", body)   # 기본 숨김
        self.assertEqual(body.count("팀 급여가 제외"), 2)   # 위 상자 + 작성 기준
        self.assertIn("6. 팀 판관비 내역 (급여 제외)", body)

    def test_no_source_names_or_cost_rate(self):
        d, R, T, page = self.make()
        body = text(page)
        for word in ("위하고", "WEHAGO", "분개장", "내려받", "70%", "원가율"):
            self.assertNotIn(word, body, word)

    def test_net_switch_shows_only_surplus_or_deficit(self):
        with open(os.path.join(self.folder, "설정.csv"), "a", encoding="utf-8-sig", newline="") as f:
            f.write("%s,표시,\r\n" % teamreport.NET_SETTING)
        d, R, T, page = self.make()
        body = text(page)
        self.assertIn("급여 반영 손익", body)
        self.assertTrue("흑자" in body or "적자" in body)
        for r in d.dept:
            if r["dept"] == "기획1팀" and r["salary"]:
                self.assertFalse(has_amount(body, r["salary"]), r["salary"])

    def test_title_and_meta(self):
        d, R, T, page = self.make()
        self.assertIn("2026년 10월 기획1팀 실적 보고", page)
        self.assertIn("기획1팀장", page)
        self.assertIn("2026.11.05", page)
        self.assertIn("- 끝 -", page)

    def test_write_all_one_file_per_team(self):
        d = load(self.folder)
        R = compute(d, "monthly", ASOF)
        out = os.path.join(self.tmp, "출력")
        paths = teamreport.write_all(d, R, out, TODAY)
        self.assertEqual([os.path.basename(p) for p in paths],
                         ["2026-10-31_월간_팀장_기획1팀.html", "2026-10-31_월간_팀장_기획2팀.html"])

    def test_without_dept_accounts_falls_back_to_total(self):
        os.remove(os.path.join(self.folder, "부서계정비용.csv"))
        d, R, T, page = self.make()
        self.assertIsNone(T["acc"])
        self.assertIn("계정별 내역은 다음 자료 변환부터", page)


class TestBuildDeptAccounts(unittest.TestCase):
    def test_split_by_dept_and_account_without_salary(self):
        oct_ = dt.date(2026, 10, 25)
        books = Books([
            line(oct_, "80200", "직원급여(판)", 3_000_000, dept="기획1팀", emp="가"),
            line(oct_, "81201", "여비교통비(판)", 50_000, dept="기획1팀"),
            line(oct_, "81201", "여비교통비(판)", 20_000, dept="기획1팀"),
            line(oct_, "81100", "복리후생비(판)", 30_000, dept="기획2팀"),
            line(oct_, "61000", "외주비(도)", 9_999_999, dept="기획1팀"),
        ])
        T = convert_pl.build_dept_accounts(books, dict(convert.DEFAULT_CONFIG))
        self.assertTrue(T.written)
        got = [(r["부서"], r["계정코드"], r["금액"]) for r in T.rows]
        self.assertEqual(got, [("기획1팀", "81201", "70000"), ("기획2팀", "81100", "30000")])
        self.assertEqual(convert.check_result(T.checks[0]), "일치")
        # 부서비용.csv 판관비와 같은 금액
        D = dict((r["부서"], r["판관비"]) for r in convert_pl.build_dept(books, dict(convert.DEFAULT_CONFIG)).rows)
        self.assertEqual(D["기획1팀"], "70000")

    def test_no_dept_column_not_written(self):
        T = convert_pl.build_dept_accounts(Books([line(dt.date(2026, 10, 1), "81201", "여비교통비(판)", 1)]),
                                           dict(convert.DEFAULT_CONFIG))
        self.assertFalse(T.written)


if __name__ == "__main__":
    unittest.main()
