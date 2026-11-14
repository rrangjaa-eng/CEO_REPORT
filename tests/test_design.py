"""화면 배치 테스트 (디자인 검토). 실행: python3 -m unittest discover -s tests

숫자는 바꾸지 않고 배치만 본다: 첫 화면 표가 잘리지 않는지, 한글이 글자 단위로 끊기지 않는지,
가장 중요한 값(최저 계산 잔액)이 첫 줄 카드에 있는지. 시험 자료는 전부 가상이다.
"""
import datetime as dt
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report.calc import compute  # noqa: E402
from ceo_report.areas import strip_ui  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import render  # noqa: E402
from sample_input import SAMPLE, refresh as refresh_sample  # noqa: E402
from test_approval import body_attr, browser_dom  # noqa: E402

ASOF = dt.date(2026, 11, 2)


def setUpModule():
    refresh_sample()


FIRST_TABLE = """
(function(){
  var b=document.body;
  var tw=document.getElementById('avail').parentNode;
  b.setAttribute('data-twsw',String(tw.scrollWidth));
  b.setAttribute('data-twcw',String(tw.clientWidth));
  var tot=document.querySelector('.ptot');
  b.setAttribute('data-toth',String(tot?tot.getBoundingClientRect().height:0));   // 월간 대표용엔 프로젝트 칸이 없다
  var hmax=0;[].forEach.call(document.querySelectorAll('table'),function(t){
    [].forEach.call(t.querySelectorAll('tbody tr:not(.tot)'),function(r){var h=r.getBoundingClientRect().height;if(h>hmax)hmax=h;});});
  b.setAttribute('data-rowmax',String(hmax));
  b.setAttribute('data-sw',String(document.documentElement.scrollWidth));
})();
"""


class TestReportFirstScreenLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.R = {k: compute(load(SAMPLE), k, ASOF) for k in ("weekly", "monthly")}

    def test_first_screen_table_is_not_clipped_at_desk_width(self):
        for kind, R in self.R.items():
            for mode in ("ceo", "mgmt"):
                with self.subTest(kind=kind, mode=mode):
                    dom = browser_dom(self, render(R, mode), FIRST_TABLE, size=(1280, 900))
                    self.assertLessEqual(float(body_attr(dom, "data-twsw")), float(body_attr(dom, "data-twcw")))
                    self.assertLessEqual(float(body_attr(dom, "data-sw")), 1280)

    def test_korean_words_do_not_break_letter_by_letter(self):
        # '8건 · 예산 미책정 1건 (사전견적 없음 1건)' 이 한 글자씩 세로로 쌓이면 합계 줄이 6줄을 넘는다.
        # 어느 표의 어느 줄도 (프로젝트 상세표의 '기획1팀' 이 '기/획/1/팀' 으로) 4줄을 넘지 않는다.
        dom = browser_dom(self, render(self.R["weekly"], "ceo"), FIRST_TABLE, size=(1280, 900))
        self.assertLess(float(body_attr(dom, "data-toth")), 80)
        self.assertLess(float(body_attr(dom, "data-rowmax")), 80)


def first_screen(html):
    return html.split("<div class='toc'>")[0]


class TestAvailableFundsTable(unittest.TestCase):
    """첫 화면 맨 위 질문 '이 기간까지 쓸 수 있는 돈은?'을 기간별 가용자금 표가 답한다 (사용자 2026-11-03).

    주간 1~4주, 월간 1~3개월. 값은 calc 의 s2['periods'] 그대로. 문서(PDF)로 전달하므로 단추 없이
    줄은 예상분 포함, 가용자금 칸 아래에 확정분만을 함께 적는다 (사용자 2026-11-03)."""

    @classmethod
    def setUpClass(cls):
        cls.R = {k: compute(load(SAMPLE), k, ASOF) for k in ("weekly", "monthly")}

    def rows(self, html):
        import test_report
        return [[re.sub(r"<[^>]+>", " ", c).split() for c in r] for r in test_report.avail_rows(first_screen(html))]

    def test_rows_follow_calc_for_both_editions_and_modes(self):
        for kind, R in self.R.items():
            labels = [p["label"] for p in R["s2"]["periods"]]
            self.assertEqual(labels, ["이번 주", "다음 주", "3주째", "4주째"] if kind == "weekly" else ["12월", "1월", "2월"])
            for edition in ("ceo", "mgmt"):
                html = render(R, edition)
                with self.subTest(kind=kind, edition=edition):
                    got = self.rows(html)
                    self.assertEqual(len(got), len(R["s2"]["periods"]))
                    for p, cells in zip(R["s2"]["periods"], got):
                        r = p["firm"]   # 큰 숫자는 확정분만 (사용자 2026-11-05: 예상 자금은 따로 보게)
                        self.assertEqual(" ".join(cells[0][:len(p["label"].split())]), p["label"])
                        self.assertEqual(cells[1][0], "{:,}".format(r["pin"]))    # 그 기간 금액 (누적 아님)
                        self.assertEqual(cells[2][0], "{:,}".format(r["pout"]))
                        # 두 판 같은 4칸. 여유 자금 칸엔 큰 숫자만 (사용자 2026-11-05: '가장 적을 때' 안내는 경영관리용 근거 표에만)
                        self.assertEqual(cells[3][0], "{:,}".format(r["avail"]))
                        self.assertNotIn("가장", cells[3])
                        self.assertEqual(len(cells), 4)

    def test_negative_available_is_red(self):
        import copy
        R = copy.deepcopy(self.R["weekly"])
        R["s2"]["periods"][0]["firm"]["avail"] = -5_000_000
        html = first_screen(render(R, "ceo"))
        self.assertRegex(html, r"<b class='neg'>[^<0-9]?5,000,000</b>")

    def test_estimate_shown_apart_not_in_big_number(self):
        """예상 지급(확정 전)은 큰 숫자에서 빼지 않고 칸 아래 '프로젝트 지급 예상 등까지 빼면'·'예상 − … 별도'로 따로 적는다 (사용자 2026-11-05).
        2026-11-14 D1·F7: 급여·세금·카드 같은 정기 지출 예상은 큰 숫자에 넣고, 작은 줄엔 예상 입금을 넣지 않는다."""
        R = self.R["weekly"]
        html = first_screen(render(R, "ceo"))
        for p in R["s2"]["periods"]:
            f, a = p["firm"]["avail"], p["spend"]["avail"]
            self.assertIn("<b class='%s'>%s</b>" % ("neg" if f < 0 else "", "{:,}".format(f)), html)
            if a != f:
                self.assertIn("프로젝트 지급 예상 등까지 빼면 %s" % "{:,}".format(a).replace("-", "−") if a < 0
                              else "프로젝트 지급 예상 등까지 빼면 {:,}".format(a), html)

    def test_unknown_balance_says_so(self):
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        folder = os.path.join(tmp, "입력")
        shutil.copytree(SAMPLE, folder)
        os.remove(os.path.join(folder, "계좌잔액.csv"))
        html = render(compute(load(folder), "weekly", ASOF), "ceo")
        for cells in self.rows(html):
            self.assertEqual(cells[3], ["확인", "필요"])
        self.assertNotIn("neg", first_screen(html).split("id='avail'>")[1].split("</table>")[0])


class TestReportIsADocument(unittest.TestCase):
    """보고서는 프로그램이 아니라 문서(PDF)로 전달한다 (사용자 2026-11-03): 누르거나 입력하는 것이 없고 모든 값이 그대로 보인다."""

    def test_no_buttons_inputs_or_scripts(self):
        for kind in ("weekly", "monthly"):
            R = compute(load(SAMPLE), kind, ASOF)
            for edition in ("ceo", "mgmt"):
                with self.subTest(kind=kind, edition=edition):
                    html = render(R, edition)
                    if edition == "mgmt":
                        # 경영관리용은 영역별 보기 목록·인쇄 단추만 있다 (사용자 2026-11-11). 그것을 빼면 문서 그대로
                        self.assertIn("id='anav'", html)
                        html = strip_ui(html)
                    for tag in ("<script", "<button", "<input"):
                        self.assertNotIn(tag, html)

    def test_ceo_edition_is_summary_only_and_prints_portrait(self):
        """대표 보고는 1~2쪽: 요약 화면만, 상세 장(1~8)·목차는 경영관리 보고에만. A4 세로 (사용자 2026-11-03)."""
        for kind in ("weekly", "monthly"):
            R = compute(load(SAMPLE), kind, ASOF)
            ceo, mgmt = render(R, "ceo"), render(R, "mgmt")
            with self.subTest(kind):
                self.assertNotIn("<h2 id='s", ceo)
                self.assertNotIn("class='toc'", ceo)
                self.assertIn("<h2 id='s1'>", mgmt)
                for html in (ceo, mgmt):
                    self.assertIn("@page{size:A4 portrait", html)
                    self.assertNotIn("landscape", html)

    def test_ceo_title_is_plain_weekly_or_monthly_report_without_badge(self):
        """사용자 2026-11-04: 대표용 제목은 '주간 보고'·'월간 보고', '대표용' 표시 없음. 경영관리용은 그대로."""
        src = os.path.join(ROOT, "입력양식", "샘플")
        for kind, word in (("weekly", "주간"), ("monthly", "월간")):
            R = compute(load(src), kind, dt.date(2026, 10, 31))
            ceo, mgmt = render(R, "ceo"), render(R, "mgmt")
            h1 = re.search(r"<h1>(.*?)</h1>", ceo).group(1)
            self.assertTrue(h1.endswith("%s 보고" % word), h1)
            self.assertNotIn("대표용", h1)
            self.assertNotIn("badge", h1)
            self.assertIn("<span class='badge m'>경영관리용</span>", mgmt)

    def test_payday_entered_makes_the_list_for_that_day(self):
        """출금일을 따로 넣으면 그 날 기준 (사용자 2026-11-04). 자금 표 첫 주 끝도 그 날, 다음 주 = 그 다음 날부터 7일."""
        from ceo_report.render import week_outflows
        R = compute(load(os.path.join(ROOT, "입력양식", "샘플")), "weekly", dt.date(2026, 10, 31), payday=dt.date(2026, 11, 5))
        W = week_outflows(R)
        self.assertEqual(W["fri"], dt.date(2026, 11, 5))
        self.assertEqual([(e["date"].isoformat(), e["amount"]) for e in W["pay"]["rows"]], [("2026-11-05", 1_200_000)])
        self.assertTrue(all(dt.date(2026, 11, 6) <= e["date"] <= dt.date(2026, 11, 12) for e in W["next"]["rows"]))
        self.assertEqual(R["s2"]["periods"][0]["end"], dt.date(2026, 11, 5))
        fs = first_screen(render(R, "ceo"))
        self.assertIn("11/05(목) 출금 목록", fs)
        self.assertIn("11/05(목) 출금 합계", fs)
        # 기준일 이전·당일 출금일은 쓰지 않고 기본(기준일 뒤 첫 금요일)
        R2 = compute(load(os.path.join(ROOT, "입력양식", "샘플")), "weekly", dt.date(2026, 10, 31), payday=dt.date(2026, 10, 31))
        self.assertEqual(R2["payday"], dt.date(2026, 11, 6))

    def test_weekly_lists_friday_payments_then_next_week(self):
        """매주 금요일 출금 (사용자 2026-11-03): ① 금요일 출금 목록, 그 아래 다음 주(토~다음 금) 지급 예정.
        금요일 목록은 금액이 확정된 건만 (사용자 2026-11-04 세 번 지적: 예상·금액 미확인 모두 뺌)."""
        from ceo_report import calc
        from ceo_report.render import week_outflows
        # 목록 모양을 보는 시험이라 인트라넷 요청·남은 예산이 일정에 들어가던 규칙으로 본다 (기본은 '비교만', 2026-11-04)
        old, calc.INTRANET_IN_FUNDS = calc.INTRANET_IN_FUNDS, True
        try:
            R = compute(load(os.path.join(ROOT, "입력양식", "샘플")), "weekly", dt.date(2026, 10, 31))
        finally:
            calc.INTRANET_IN_FUNDS = old
        W = week_outflows(R)
        self.assertEqual(W["fri"], dt.date(2026, 11, 6))
        self.assertEqual([(e["date"].isoformat(), e["amount"]) for e in W["pay"]["rows"]],
                         [("2026-11-05", 1_200_000), ("2026-11-06", 49_500_000)])
        self.assertTrue(all(e["amount"] is not None for e in W["pay"]["rows"]))
        self.assertEqual(W["pay_est"]["unknown_n"], 1)   # 금액 미확인은 목록 밖 (한 줄 알림)
        # 금요일 출금 목록은 확정 건만 (사용자 2026-11-04). 남은 예산 매주 나눔(예상)은 pay_est 로 따로: P26207 962,500 + P26208 883,235
        self.assertTrue(all(e["firm"] for e in W["pay"]["rows"]))
        merged = W["pay_est"]["rows"][-1]
        self.assertEqual((merged["source"], len(merged["merged"]), merged["firm"]), ("남은 예산", 2, False))
        self.assertTrue(all(dt.date(2026, 11, 7) <= e["date"] <= dt.date(2026, 11, 13) for e in W["next"]["rows"]))
        self.assertTrue(W["next"]["rows"])
        self.assertEqual(W["pay"]["unknown_n"], 0)
        for edition in ("ceo", "mgmt"):
            fs = first_screen(render(R, edition))
            self.assertIn("11/06(금) 출금 목록", fs)
            self.assertIn("다음 주 지급 예정 (11/07(토) ~ 11/13(금))", fs)
            self.assertLess(fs.index("11/06(금) 출금 목록"), fs.index("다음 주 지급 예정"))
            table = fs.split("<table class='pt wo'>")[1].split("</table>")[0]
            self.assertEqual(table.count("<tr>") + table.count("<tr class='od'>"), 1 + 2)   # 금액 확정 건만 (사용자 2026-11-04)
            self.assertNotIn("예상", table)
            self.assertIn("전시제작사", table)
            self.assertNotIn("금액 미확인", table)
            self.assertNotIn("상세 미입력", table)
            self.assertIn("2건 · 합계 50,700,000</div>", fs)
            # 사용자 2026-11-05: 이 안내는 경영관리용에만
            (self.assertIn if edition == "mgmt" else self.assertNotIn)("확정 안 된 예상 지급 1건 1,845,735원 · 금액 미확인 1건은 목록에서 뺌", fs)
            self.assertIn("<div class='lab'>11/06(금) 출금</div><div class='big'>50,700,000</div><div class='foot'>2건</div>", fs)
        self.assertNotIn("출금 목록", render(compute(load(os.path.join(ROOT, "입력양식", "샘플")), "monthly",
                                                    dt.date(2026, 10, 31)), "ceo"))

    def test_weekly_ceo_report_has_a_sign_box(self):
        """결재란: 대표가 서명해 회신 (사용자 2026-11-03). 대표용 주간에만."""
        R = compute(load(os.path.join(ROOT, "입력양식", "샘플")), "weekly", dt.date(2026, 10, 31))
        html = render(R, "ceo")
        box = html.split("<table class='sign'>")[1].split("</table>")[0]
        self.assertIn("결<br>재", box)
        self.assertIn("담당", box)
        self.assertIn("대표이사", box)
        self.assertNotIn("class='sd'", box)   # 날짜 줄 없음 (사용자 2026-11-05)
        self.assertNotIn("<table class='sign'>", render(R, "mgmt"))
        self.assertNotIn("<table class='sign'>", render(compute(load(os.path.join(ROOT, "입력양식", "샘플")), "monthly",
                                                                dt.date(2026, 10, 31)), "ceo"))

    def test_friday_report_lists_next_friday_like_the_cash_table(self):
        from ceo_report.render import week_outflows
        R = compute(load(os.path.join(ROOT, "입력양식", "샘플")), "weekly", dt.date(2026, 11, 5))
        self.assertEqual(week_outflows(R)["fri"], dt.date(2026, 11, 6))   # 목요일 보고 → 다음 날 금요일
        R = compute(load(os.path.join(ROOT, "입력양식", "샘플")), "weekly", dt.date(2026, 11, 6))
        # 금요일 보고: 그날 것은 자금 표처럼 이미 나간 것 → 다음 금요일 목록 (2026-11-03 검토, 목록 = 자금 표)
        self.assertEqual(week_outflows(R)["fri"], dt.date(2026, 11, 13))
        self.assertEqual(R["s2"]["periods"][0]["end"], dt.date(2026, 11, 13))

    def test_monthly_shows_team_sales_and_margin(self):
        """월간 대표 보고 팀별 표 (사용자 2026-11-03): 매출·매출총이익·수익률은 상세 4번(s4)과 같고, 급여·판관비는 부서비용.csv
        (분개장 관리항목 부서명). 팀 순수익 = 매출총이익 − 그 팀 급여·판관비. 기획본부 비용은 본부 합계에서만, 경영관리는 회사 전체에서 뺀다."""
        R = compute(load(os.path.join(ROOT, "입력양식", "샘플")), "monthly", dt.date(2026, 10, 31))
        for edition in ("ceo", "mgmt"):
            fs = first_screen(render(R, edition))
            tables = [t.split("</table>")[0] for t in fs.split("<table class='pt tm'>")[1:]]
            self.assertEqual(len(tables), 2)   # 이번 달, 올해 누적
            rows = [re.findall(r"<td[^>]*>(.*?)</td>", r) for r in re.findall(r"<tr[^>]*>(.*?)</tr>", tables[0].split("<tbody>")[1])]
            # 결산, 위하고 결산자료 순서 (사용자 2026-11-04): 영업이익 + 영업외 수익 − 영업외 비용 = 세전 이익
            self.assertEqual([[c for c in r if c] for r in rows[5:]], [
                ["+ 영업외 수익 (경영관리 2,000,000)", "2,000,000"], ["− 영업외 비용 (기획본부 500,000)", "500,000"],
                ["세전 이익", "29,100,000"]])
            # 기획본부 영업외 비용도 결산자료처럼 영업외 비용 줄에 둔다 (사용자 2026-11-04 정정)
            hq = [r for r in rows if r and r[0].startswith("기획본부 자체 비용")][0]
            self.assertEqual(hq[0], "기획본부 자체 비용")   # '판관비에 영업외 비용' 문구 없이 (사용자 2026-11-04)
            self.assertNotIn("지원금", fs)
            self.assertEqual(rows[:5], [   # 경영관리는 실적 줄 없이 영업외 수익 줄에만 (사용자 2026-11-03)
                ["기획1팀", "99,000,000", "31,680,000", "32.0%", "9,000,000", "2,000,000", "20,680,000", "3명", "6,893,333", "2.3배", "5,226,667"],
                ["기획2팀", "81,000,000", "25,920,000", "32.0%", "7,500,000", "1,500,000", "16,920,000", "3명", "5,640,000", "2.3배", "3,973,333"],
                ["기획본부 자체 비용", "", "", "", "4,000,000", "1,000,000", "−5,000,000", "1명", "", "", ""],
                ["기획본부 합계", "180,000,000", "57,600,000", "32.0%", "20,500,000", "4,500,000", "32,600,000", "7명", "4,657,143", "1.6배", ""],
                ["회사 전체 (영업이익)<small>인원 = 기획본부만</small>", "180,000,000", "57,600,000", "32.0%", "23,500,000", "6,500,000", "27,600,000", "7명", "3,942,857", "1.2배", ""]])   # 회사 줄엔 공통비 나눈 뒤 칸 없음 (사용자 2026-11-04)
            ytd = [re.findall(r"<td[^>]*>(.*?)</td>", r) for r in re.findall(r"<tr[^>]*>(.*?)</tr>", tables[1].split("<tbody>")[1])]
            # 누적 1인당 = 누적 순수익 ÷ 1~10월 평균 인원 (사용자 2026-11-03)
            self.assertEqual(ytd[0], ["기획1팀", "742,500,000", "237,600,000", "32.0%", "90,000,000", "20,000,000", "127,600,000", "3.0명",
                                      "42,533,333", "1.4배", "25,866,667"])   # 급여·판관비 따로, 급여 대비 (사용자 2026-11-03)
            self.assertEqual(ytd[3][:2], ["회사 전체 (영업이익)<small>인원 = 기획본부만</small>", "1,350,000,000"])
            self.assertEqual(ytd[3][6], "132,000,000")   # 기획본부 영업외 비용은 영업이익에 넣지 않음 (사용자 2026-11-04 정정)
            self.assertEqual(ytd[3][7:11], ["7.0명", "18,857,143", "0.6배", ""])   # 회사 줄엔 공통비 나눈 뒤 칸 없음 (사용자 2026-11-04)   # 회사 영업이익은 공통비 뺀 값 (사용자 2026-11-03)   # 회사 인원은 팀·본부만 (경영관리 제외, 사용자 2026-11-03)
            # 누적 결산 끝: 세전 이익 − 법인세 예상(지방세 포함) = 당기순이익 예상 (사용자 2026-11-04). 2026-11-14 P3: '지금까지 이익 기준'
            self.assertEqual([[c for c in r if c] for r in ytd[-3:]], [
                ["세전 이익", "135,000,000"], ["− 법인세·지방소득세 (지금까지 이익 기준 예상)", "14,850,000"], ["당기순이익 (예상)", "120,150,000"]])
            self.assertNotIn("당기순이익", tables[0])   # 이번 달 표에는 넣지 않음
            # 본부·공통 비용을 인원 비율로 나눈 뒤: 팀 합계 = 회사 영업이익 (기획팀 1인당이 과장되지 않게, 사용자 2026-11-03)
            self.assertEqual(round(5_226_667 * 3 + 3_973_333 * 3, -2), 27_600_000)
            self.assertEqual(round((25_866_667 + 18_133_333) * 3, -2), 132_000_000)
            if edition == "mgmt":   # 표 설명(근거)은 경영관리용에만 (사용자 2026-11-03)
                self.assertIn("부서별 급여+판관비 30,000,000 = 장부 공통비 30,000,000", fs)
            else:
                self.assertNotIn("부서별 급여+판관비", fs)
            self.assertIn("27,600,000", fs.split("10월 실적")[1].split("<table")[0])   # 회사 순수익 = 실적 카드의 10월 이익
            self.assertNotIn("프로젝트 예산은 남나?", fs)   # 대표용 첫 화면엔 프로젝트 막대 없음, 예산 초과만 한 줄 (사용자 2026-11-03)
            if edition == "mgmt":   # 대표용엔 예산 언급 없음, 예산 초과 줄은 경영관리용에만 (사용자 2026-11-03)
                self.assertIn("<div class='overl'><b class='neg'>예산 초과 2건</b>", fs)
            else:
                self.assertNotIn("예산", re.sub(r"<[^>]+>", "", fs[fs.index("<body"):]))
        self.assertNotIn("pt tm", render(compute(load(os.path.join(ROOT, "입력양식", "샘플")), "weekly", dt.date(2026, 10, 31)), "ceo"))

    def test_team_profit_unknown_without_dept_file(self):
        """부서비용.csv 가 없으면 급여·판관비·순수익을 0이 아니라 미확인으로 둔다."""
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        folder = os.path.join(tmp, "in")
        shutil.copytree(os.path.join(ROOT, "입력양식", "샘플"), folder)
        os.remove(os.path.join(folder, "부서비용.csv"))
        fs = first_screen(render(compute(load(folder), "monthly", dt.date(2026, 10, 31)), "mgmt"))
        table = fs.split("<table class='pt tm'>")[1].split("</table>")[0]
        first = re.findall(r"<td>(.*?)</td>", re.findall(r"<tr[^>]*>(.*?)</tr>", table.split("<tbody>")[1])[0])
        self.assertEqual(first[:4], ["기획1팀", "99,000,000", "31,680,000", "32.0%"])
        self.assertNotIn("0", [c for c in first[4:7]])
        self.assertTrue(all("미확인" in c for c in first[4:7]), first)
        self.assertIn("부서비용.csv 없음", fs)

    def test_pick_date_row_is_fixed_when_report_is_made(self):
        import test_report
        pick = ASOF + dt.timedelta(days=40)
        R = compute(load(SAMPLE), "weekly", ASOF, pick=pick)
        last = R["s2"]["periods"][-1]
        self.assertEqual((last["label"], last["end"]), ("지정일", pick))
        same = [p for p in compute(load(SAMPLE), "monthly", ASOF)["s2"]["periods"]]
        self.assertEqual(len(R["s2"]["periods"]), 5)
        rows = test_report.avail_rows(first_screen(render(R, "ceo")))
        self.assertEqual(len(rows), 5)
        self.assertIn("지정일", rows[-1][0])
        self.assertIn(pick.isoformat(), rows[-1][0])
        self.assertIn("{:,}".format(last["spend"]["avail"]), rows[-1][3])   # 예상 입금은 넣지 않은 작은 줄 (2026-11-14 F7)
        self.assertEqual(len(same), 3)

    def test_no_pick_date_no_row(self):
        R = compute(load(SAMPLE), "weekly", ASOF)
        self.assertNotIn("지정일", first_screen(render(R, "ceo")))

    def test_pick_date_beyond_schedule_says_so(self):
        R = compute(load(SAMPLE), "weekly", ASOF, pick=ASOF + dt.timedelta(days=400))
        self.assertIn("지정일이 일정 자료 범위", first_screen(render(R, "ceo")))


REQ_MEASURE = """
(function(){
  var b=document.body,tw=document.getElementById('requests').parentNode,h=0;
  [].forEach.call(document.querySelectorAll('#requests tbody tr'),function(r){var x=r.getBoundingClientRect().height;if(x>h)h=x;});
  b.setAttribute('data-twsw',String(tw.scrollWidth));
  b.setAttribute('data-twcw',String(tw.clientWidth));
  b.setAttribute('data-rowmax',String(h));
  b.setAttribute('data-sw',String(document.documentElement.scrollWidth));
})();
"""


class TestApprovalTableWithBooks(unittest.TestCase):
    """WEHAGO 장부가 있을 때(대조 글·금액 차이 글이 길 때)도 요청 표가 읽히는가."""

    @classmethod
    def setUpClass(cls):
        import shutil
        import tempfile
        from test_approval import NOW, load_approval_cli, write_fake_snapshot
        from test_wehago import write_fake_books
        tmp = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, tmp, True)
        snap = write_fake_snapshot(os.path.join(tmp, "수집"))
        write_fake_books(os.path.join(tmp, "위하고"))
        path, _ = load_approval_cli().make_screen(SAMPLE, os.path.join(tmp, "출력"), snap, ASOF, NOW, False,
                                                  wehago_dir=os.path.join(tmp, "위하고"))
        with open(path, encoding="utf-8") as f:
            cls.page = f.read()

    def test_desk_width_shows_every_column_without_tall_rows(self):
        dom = browser_dom(self, self.page, REQ_MEASURE, size=(1280, 900))
        self.assertLessEqual(float(body_attr(dom, "data-twsw")), float(body_attr(dom, "data-twcw")))
        self.assertLess(float(body_attr(dom, "data-rowmax")), 130)

    def test_phone_rows_stay_short_and_table_scrolls_sideways(self):
        dom = browser_dom(self, self.page, REQ_MEASURE, size=(390, 844))
        self.assertLessEqual(float(body_attr(dom, "data-sw")), 390)
        self.assertLess(float(body_attr(dom, "data-rowmax")), 130)


UNCHECK_BIGGEST = """
(function(){
  var box=document.querySelector('tr[data-no="5103"] input.req');
  box.checked=false;box.dispatchEvent(new Event('change',{bubbles:true}));
  document.body.setAttribute('data-hl',document.getElementById('headline').className);
  document.body.setAttribute('data-low-cls',document.getElementById('h-low').className);
})();
"""


class TestApprovalHeadlineFeedback(unittest.TestCase):
    """머리 줄: '부족·최소보유현금 미만 주 없음'도 상태로 보이고(글자 그대로), 다시 계산하면 바뀐 값이 잠깐 강조된다."""

    @classmethod
    def setUpClass(cls):
        TestApprovalTableWithBooks.setUpClass.__func__(cls)

    def test_no_short_week_is_marked_ok_in_the_file(self):
        open_tag = re.search(r'<div[^>]*id="headline"[^>]*>', self.page).group(0)
        self.assertIn("lv-ok", open_tag)

    def test_recompute_marks_the_changed_value(self):
        dom = browser_dom(self, self.page, UNCHECK_BIGGEST)
        self.assertIn("lv-ok", body_attr(dom, "data-hl"))
        self.assertIn("chg", body_attr(dom, "data-low-cls"))

    def test_focus_ring_and_reduced_motion_rules_exist(self):
        self.assertIn(":focus-visible{outline:2px solid", self.page)
        self.assertIn("prefers-reduced-motion", self.page)


PHONE_ROWS = """
(function(){
  var b=document.body,hmax=0,who='';
  [].forEach.call(document.querySelectorAll('table:not(.risk) tbody tr'),function(r){
    var h=r.getBoundingClientRect().height;if(h>hmax){hmax=h;who=r.textContent.slice(0,40);}});
  b.setAttribute('data-rowmax',String(hmax));b.setAttribute('data-who',who);
  b.setAttribute('data-sw',String(document.documentElement.scrollWidth));
})();
"""


class TestReportPhoneTables(unittest.TestCase):
    """폰 폭에서 표는 옆으로 밀어 보고, 날짜·금액이 글자 단위로 쌓이지 않는다 (위험 표는 글이 길어 줄바꿈 그대로)."""

    def test_detail_rows_stay_short_on_a_phone(self):
        R = compute(load(SAMPLE), "monthly", ASOF)
        for mode in ("ceo", "mgmt"):
            with self.subTest(mode=mode):
                dom = browser_dom(self, render(R, mode), PHONE_ROWS, size=(390, 844))
                self.assertLessEqual(float(body_attr(dom, "data-sw")), 390)
                self.assertLess(float(body_attr(dom, "data-rowmax")), 80, body_attr(dom, "data-who"))


class TestWeeklyOrderAndActiveProjects(unittest.TestCase):
    """주간 대표 보고 (사용자 2026-11-03): ① 금요일 출금 ② 실적 ③ 자금. 프로젝트 예산 막대는 경영관리용 근거에만,
    지금 지급이 진행 중인 프로젝트만 행사일 순. 대표용은 예산 초과 프로젝트 한 줄."""

    def test_ceo_order_and_projects_only_in_management_evidence(self):
        R = compute(load(os.path.join(ROOT, "입력양식", "샘플")), "weekly", dt.date(2026, 10, 31))
        ceo = render(R, "ceo")
        heads = [re.sub("<[^>]+>", "", h) for h in re.findall(r"<div class='q'>.*?</div>", ceo)]
        self.assertEqual([h.split(" ", 1)[1].strip().split(" ")[0] for h in heads], ["11/06(금)", "자금", "10월"])   # 주간: 출금 → 자금 → 실적 (사용자 2026-11-05 맥락 배치)
        self.assertNotIn("class='prow'", ceo)
        self.assertNotIn("예산 초과", ceo)   # 대표용엔 예산 언급 없음 (사용자 2026-11-03)
        self.assertIn("<b class='neg'>예산 초과 2건</b> · C사 전시 부스 <b class='neg'>53,000,000 초과</b>", render(R, "mgmt"))
        mgmt = render(R, "mgmt")
        fs = mgmt.split("<div class='toc'>")[0]
        ids = re.findall(r"<div class='prow' id='pj-(P\d+)'>", fs)
        # 완료 P26202·05는 남은 지급이 없어 빠진다. 완료 P26206은 금액 모르는 요청 줄이 남아 들어가고,
        # 준비 중이어도 카드 미결제가 있는 P26208은 들어간다
        self.assertEqual(ids, ["P26206", "P26203", "P26201", "P26207", "P26204", "P26208"])
        self.assertIn("행사일 순", fs)
        self.assertLess(fs.index("자금 현황"), fs.index("프로젝트별 원가 예산·집행"))

class TestMonthlyMonthAndYearApart(unittest.TestCase):
    """월간 (사용자 2026-11-03): 이번 달 실적과 올해 누적 실적을 따로 나누고, 경영관리의 영업외 수익을 그 부서 실적으로 보인다."""

    def test_sections_and_management_income(self):
        R = compute(load(os.path.join(ROOT, "입력양식", "샘플")), "monthly", dt.date(2026, 10, 31))
        fs = first_screen(render(R, "ceo"))
        heads = re.findall(r"<div class='q'>(.*?)</div>", fs)
        month = next(i for i, h in enumerate(heads) if "10월 실적 (이번 달)" in h)
        year = next(i for i, h in enumerate(heads) if "올해 누적 실적 (1월~10월)" in h)
        self.assertEqual(year, month + 1)
        part_month = fs.split(heads[month])[1].split(heads[year])[0]
        self.assertNotIn("올해 누적", part_month)   # 이번 달 칸에는 누적 숫자를 섞지 않는다
        part_year = fs.split(heads[year])[1]
        # 누적도 이번 달처럼 큰 숫자 칸 + 흰 카드 표 (사용자 2026-11-04)
        self.assertIn("<div class='lab'>1월~10월 당기순이익 (예상)</div><div class='big'>120,150,000</div>", part_year)
        self.assertIn("<div class='lab'>1월~10월 세전 이익</div><div class='big'>135,000,000</div>", part_year)
        self.assertIn("<div class='card brk'><div class='lab'>1월~10월</div>", part_year)   # 작년 감가상각비 12,000,000 먼저 뺌 (사용자 2026-11-04)
        self.assertIn("+ 영업외 수익 (경영관리 2,000,000)", part_month)
        self.assertNotIn("<td>경영관리", part_month)

    def test_monthly_prints_at_full_size_on_three_themed_pages(self):
        """월간은 주간과 같은 100% (사용자 2026-11-04: ⑦ 계정표를 대표용에서 빼고 쪽 디자인 다시).
        1쪽 한눈에·자금(①②) · 2쪽 ③④⑤ · 3쪽 ⑥(누적 큰 숫자 · 앞으로 들어올 매출 · 누적·목표) 통째로."""
        S = load(os.path.join(ROOT, "입력양식", "샘플"))
        mon = render(compute(S, "monthly", dt.date(2026, 10, 31)), "ceo")
        wk = render(compute(S, "weekly", dt.date(2026, 10, 31)), "ceo")
        self.assertIn("<div class='wrap mon'>", mon)
        self.assertIn("<div class='wrap'>", wk)
        self.assertNotIn("zoom:.95", mon)
        # ⑥ 누적 실적(앞으로 들어올 매출 포함)은 3쪽에 통째로 (사용자 2026-11-04: 6번이 쪽에 걸치면 안 됨)
        self.assertIn(".fs.mon .sec.pgb{break-before:page}", mon)
        self.assertEqual(mon.count("<div class='sec pgb'><div class='q'>6."), 1)
        self.assertIn("10월말 통장 잔액", mon)   # 1쪽 맨 위 한눈에 칸
        # 결산 줄 이름은 빈 칸을 합친 칸에 써서 첫 칸(팀 이름)이 넓어지지 않는다
        self.assertIn("<tr class='mut nonop'><td colspan='6'>+ 영업외 수익", mon)

    def test_small_accounts_are_merged_into_other(self):
        """⑦ 계정표: 묶음 소계의 1% 미만 계정이 2개 이상이면 '기타 (n개 계정)' 한 줄로 (사용자 2026-11-04: 월간 3쪽)."""
        from ceo_report.render import _merge_small
        acc = [{"name": "큰", "code": "1", "months": [900, 100], "total": 1000, "partial": False},
               {"name": "작1", "code": "2", "months": [3, 2], "total": 5, "partial": False},
               {"name": "작2", "code": "3", "months": [None, 4], "total": 4, "partial": True}]
        out = _merge_small(acc, 1009, 2)
        self.assertEqual([a["name"] for a in out], ["큰", "기타 (2개 계정)"])
        self.assertEqual((out[1]["months"], out[1]["total"], out[1]["partial"]), ([None, 6], 9, True))
        self.assertEqual(_merge_small(acc[:2], 1005, 2), acc[:2])   # 하나뿐이면 그대로



class TestSectionsDoNotSplit(unittest.TestCase):
    """주간·월간 (사용자 2026-11-03): 표·내용이 쪽 사이에서 끊기지 않게 절(제목+내용)을 한 덩어리로 묶는다."""

    def test_every_heading_is_in_an_unbreakable_section(self):
        for kind in ("weekly", "monthly"):
            html = render(compute(load(os.path.join(ROOT, "입력양식", "샘플")), kind, dt.date(2026, 10, 31)), "ceo")
            with self.subTest(kind):
                # 주간 ① 출금 목록만 쪽을 넘어 이어질 수 있다 (사용자 2026-11-04: 길면 통째로 밀려 1쪽이 비던 것)
                brk = html.count("<div class='sec brk'><div class='q'>")
                self.assertEqual(brk, 1 if kind == "weekly" else 0)
                pgb = html.count("<div class='sec pgb'><div class='q'>")   # 월간 ⑥: 새 쪽에서 통째로
                self.assertEqual(pgb, 0 if kind == "weekly" else 2)   # 월간 ③(2쪽 첫머리)·⑥
                # 주간 ② 자금은 2쪽 첫머리에서, 표와 그림 사이에서만 나뉠 수 있다 (사용자 2026-11-05: 빈 곳 최소)
                flow = html.count("<div class='sec sflow pgb'><div class='q'>")
                self.assertEqual(flow, 1 if kind == "weekly" else 0)
                self.assertEqual(html.count("<div class='q'>"), html.count("<div class='sec'><div class='q'>") + brk + pgb + flow)
                self.assertIn(".sec{break-inside:avoid}", html.replace(".kpi,.card,.sec{break-inside:avoid}", ".sec{break-inside:avoid}"))
                self.assertEqual(html.count("break-inside:auto"), 2)
                self.assertIn(".sec.brk,.sec.brk .frimain{break-inside:auto}", html)


# ───── 인트라넷을 가용자금 일정에 넣던 규칙 (calc.INTRANET_IN_FUNDS=True) 으로 시험 ─────
# 사용자 결정(2026-11-04 '비교만') 뒤 기본은 False. 이 파일은 그 규칙이 켜졌을 때의 일정 계산을 그대로 지킨다.
import ceo_report.calc as _calc_for_flag  # noqa: E402
_setup_before_flag = globals().get("setUpModule")
_teardown_before_flag = globals().get("tearDownModule")


def setUpModule():  # noqa: F811
    _calc_for_flag.INTRANET_IN_FUNDS = True
    if _setup_before_flag:
        _setup_before_flag()


def tearDownModule():  # noqa: F811
    _calc_for_flag.INTRANET_IN_FUNDS = False
    if _teardown_before_flag:
        _teardown_before_flag()


if __name__ == "__main__":
    unittest.main()
