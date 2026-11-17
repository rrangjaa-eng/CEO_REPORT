# -*- coding: utf-8 -*-
"""연간 보고 세 가지 (사용자 2026-11-17 '연간보고에 넣어야 할 항목들을 전부 넣고 대표용과 경영관리용, 팀장용으로 구분해서 만들어').
- 법인세·당기순이익은 월간 보고와 같은 계산 (감가상각 달 수만큼·대손충당금·세무조정·기납부)
- 대표용: 7. 기업신용평가 미리보기, 사용한 자료 한 줄, 쪽 아래 글. 안내 문구(쉬운 설명·제안) 없음
- 경영관리용: 10~14장 (법인세·세무조정, 감면·공제, 신고, 급여·연말정산, 예산 대비)
- 팀장용: 팀마다 한 부, 급여 금액 없음"""
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report import annual, calc, render as RD, teamreport  # noqa: E402
from ceo_report.data import load  # noqa: E402
import 보고서  # noqa: E402

ASOF = dt.date(2026, 10, 31)


def text(page):
    page = re.sub(r"<style.*?</style>|<script.*?</script>", "", page, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="annual3_")
        cls.inp, cls.out = os.path.join(cls.tmp, "입력"), os.path.join(cls.tmp, "출력")
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_sample.py"), cls.inp], check=True, stdout=subprocess.DEVNULL)
        from unittest import mock
        with mock.patch.dict(os.environ, {"CEO_REPORT_TEST_GATE_OFF": "1"}):   # 자금계획서·분개장 확인은 test_blocked 에서 따로
            cls.rc = 보고서.main(["연간", "--연도", "2026", "--기준일", ASOF.isoformat(), "--입력", cls.inp, "--출력", cls.out, "--pdf", "안함"])
        rd = lambda *n: open(os.path.join(cls.out, *n), encoding="utf-8").read()
        cls.ceo, cls.mg = rd("2026_연간_대표보고.html"), rd("2026_연간_경영관리보고.html")
        cls.teams = dict((n, rd("팀장용", n)) for n in sorted(os.listdir(os.path.join(cls.out, "팀장용"))))
        cls.D = load(cls.inp)
        cls.M = calc.compute(cls.D, "monthly", ASOF)
        cls.pack = RD.annual_pack(cls.M)
        cls.A = annual.compute(cls.inp, 2026, cls.D.settings, cls.D, ASOF)
        annual.apply_monthly(cls.A, cls.M, cls.pack)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)


class TestSameAsMonthly(Base):
    def test_made_three_kinds(self):
        self.assertEqual(self.rc, 0)
        self.assertTrue(self.teams)
        self.assertTrue(all(re.match(r"2026_연간_팀장_.+\.html$", n) for n in self.teams))
        self.assertEqual(len(self.teams), len(teamreport.team_names(self.D)))

    def test_tax_and_net_income_equal_monthly(self):
        """연간 손익의 세전 이익·법인세·당기순이익 = 그 달까지 월간 누적 결산 줄 (같은 계산)."""
        N, E, Y = self.pack["N"], self.pack["E"], self.A["Y"]
        self.assertTrue(self.A["tax_same"])
        self.assertEqual(Y["pre"], N["pretax"])
        self.assertEqual(self.A["tax"], N["tax"])
        self.assertEqual(Y["net"], N["net_income"])
        self.assertEqual(self.A["corp"], E["nat"])
        self.assertEqual(self.A["local"], E["local"])
        if E["prepaid"] is not None:
            self.assertEqual(self.A["prepaid"], E["prepaid"])
            self.assertEqual(max(self.A["corp"] - self.A["prepaid"], 0), E["pay"])
        self.assertEqual(Y.get("dep_pending") or 0, N.get("dep") or 0)       # 감가상각비 예상: 달 수만큼
        self.assertEqual(Y.get("bad_pending") or 0, N.get("bad") or 0)       # 대손충당금 예상

    def test_numbers_shown(self):
        for page in (self.ceo, self.mg):
            t = text(page)
            self.assertIn("당기순이익 {:,}".format(self.A["Y"]["net"]), t)
            self.assertIn("월간 보고와 같은 계산", t)
            self.assertNotIn("세무조정 없음", t)
            self.assertNotIn("None", t)

    def test_fixed_closing_tax_is_kept(self):
        """결산 법인세가 장부에 들어왔으면 월간 예상으로 덮지 않는다."""
        A = {"Y": {"pre": 100, "net": 90}, "tax_fixed": True, "tax": 10, "cut": 12, "year": 2026}
        annual.apply_monthly(A, self.M, self.pack)
        self.assertEqual((A["tax"], A["Y"]["pre"], A["Y"]["net"]), (10, 100, 90))

    def test_without_monthly_keeps_simple_estimate(self):
        A = annual.compute(self.inp, 2026, self.D.settings, self.D, ASOF)
        tax = A["tax"]
        annual.apply_monthly(A, None, None)
        self.assertEqual(A["tax"], tax)
        self.assertIn("세무조정 없음", text(annual.render(A, "mgmt")))
        # 연중이면 감가상각비 예상은 지난 달 수만큼 (결정 M5)
        if A.get("dep_est") and not A["closed"]:
            self.assertEqual(A["Y"]["dep_pending"], max(A["dep_est"] * 10 // 12 - A["Y"]["dep"], 0))


class TestCeo(Base):
    def test_credit_preview_and_sources(self):
        t = text(self.ceo)
        self.assertIn("7. 기업신용평가 미리보기", t)
        self.assertIn("사용한 자료: 분개장", t)
        self.assertIn("class='rd'", self.ceo)                      # 보는 사람 기준 양식
        self.assertIn("2026년 연간 보고 · 기준일 2026-10-31", self.ceo)   # 쪽 아래 글

    def test_no_guidance_text(self):
        """대표 보고에는 판단을 돕는 안내 문구를 넣지 않는다 (사용자 2026-11-17)."""
        t = text(self.ceo)
        for w in ("쉬운 설명", "제안", "해결방안", "결산 전에 할 일", "가장 걸리는 점", "예산 대비", "세무조정 예상 자료"):
            self.assertNotIn(w, t)
        self.assertNotIn("<script", self.ceo)

    def test_credit_brief_has_no_judgement(self):
        from ceo_report import credit
        C = credit.compute(self.inp, ASOF, annual=True)
        h = credit.render_brief(C)
        self.assertNotIn("쉬운 설명", h)
        self.assertNotIn("class='tg", h)
        if C is not None:
            self.assertIn("추정 등급 범위", h)
            self.assertIn(credit.grade_text(C["grade"]), h)


class TestMgmt(Base):
    def test_new_chapters(self):
        ids = re.findall(r"<section class='area[^']*' id='a-([^']+)'", self.mg)
        self.assertEqual(ids[-5:], ["d10", "d11", "d12", "d13", "d14"])
        t = text(self.mg)
        for w in ("10. 법인세 예상 · 세무조정 예상", "11. 법인세 감면·공제 전체 검토", "12. 신고 일정 · 신고 도우미",
                  "13. 급여 점검 · 연말정산 예상", "14. 예산 대비", "7. 기업신용평가 미리보기", "9. 기업신용평가 미리보기"):
            self.assertIn(w, t)
        self.assertEqual(self.mg.count("<div"), self.mg.count("</div>"))

    def test_tax_table_is_the_monthly_one(self):
        self.assertTrue(self.pack["tax_table"])
        self.assertIn(self.pack["tax_table"], self.mg)

    def test_every_new_chapter_has_easy_box(self):
        for k in ("d10", "d11", "d12", "d13", "d14"):
            i = self.mg.index("id='a-%s'" % k)
            self.assertIn("쉬운 설명", self.mg[i:i + 3000], k)


class TestTeam(Base):
    def test_same_numbers_as_monthly_team_report(self):
        for team in teamreport.team_names(self.D):
            T = teamreport.build(self.D, self.M, team)
            page = self.teams["2026_연간_팀장_%s.html" % team]
            t = text(page)
            self.assertIn("2026년 연간 %s 실적 보고" % team, t)
            self.assertIn("{:,}".format(T["tot"]["revenue"]), t)
            self.assertIn("{:,}".format(T["tot"]["gp"]), t)
            self.assertIn("사용한 자료: 분개장", t)
            self.assertIn("팀 급여가 제외", t)
            for w in ("1. 2026년 실적 요약", "2. 달별 실적", "3. 분기별 실적", "4. 프로젝트별 실적", "팀 판관비 내역", "2027년 준비"):
                self.assertIn(w, t)

    def test_no_salary_amount_and_no_guidance(self):
        staff = [r for r in (getattr(self.D, "staff", None) or [])]
        for page in self.teams.values():
            t = text(page)
            for w in ("쉬운 설명", "제안", "해결방안"):
                self.assertNotIn(w, t)
            T_sal = [x for x in re.findall(r"급여[^<]{0,6}</t[hd]>", page) if "제외" not in x and "반영" not in x]
            self.assertEqual(T_sal, [])   # '급여' 칸은 없다 (급여 제외·급여 반영 손익(흑자/적자)만)
        self.assertIsNotNone(staff)

    def test_quarters_add_up(self):
        team = teamreport.team_names(self.D)[0]
        T = teamreport.build(self.D, self.M, team)
        page = teamreport.render_annual(T, annual.team_extra(self.A, team))
        i = page.index("3. 분기별 실적")
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", page[i:page.index("4. 프로젝트별 실적", i)], re.S)
        nums = lambda r: [int(x.replace(",", "")) for x in re.findall(r">(-?[\d,]+)<", r)]
        qs = [nums(r)[0] for r in rows[1:5] if nums(r)]
        self.assertEqual(sum(qs), T["tot"]["revenue"])

    def test_blocked_writes_stop_page(self):
        """자금계획서·분개장이 막히면 팀장용 연간도 만들지 않고 안내만 (대표용과 같게)."""
        out2 = os.path.join(self.tmp, "출력2")   # 샘플에는 자금계획서가 없다 → 확인을 켜면 막힌다
        보고서.main(["연간", "--연도", "2026", "--기준일", ASOF.isoformat(), "--입력", self.inp, "--출력", out2, "--pdf", "안함"])
        self.assertIn("만들지 않았습니다", open(os.path.join(out2, "2026_연간_대표보고.html"), encoding="utf-8").read())
        folder = os.path.join(out2, "팀장용")
        names = os.listdir(folder)
        self.assertEqual(len(names), len(teamreport.team_names(self.D)))
        for n in names:
            self.assertIn("만들지 않았습니다", open(os.path.join(folder, n), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
