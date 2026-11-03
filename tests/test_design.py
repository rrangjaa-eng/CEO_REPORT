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
  b.setAttribute('data-toth',String(tot.getBoundingClientRect().height));
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
            self.assertEqual(labels, ["1주", "2주", "3주", "4주"] if kind == "weekly" else ["1개월", "2개월", "3개월"])
            for edition in ("ceo", "mgmt"):
                html = render(R, edition)
                with self.subTest(kind=kind, edition=edition):
                    got = self.rows(html)
                    self.assertEqual(len(got), len(R["s2"]["periods"]))
                    for p, cells in zip(R["s2"]["periods"], got):
                        r = p["all"]
                        self.assertEqual(cells[0][0], p["label"])
                        self.assertEqual(cells[3][0], "{:,}".format(r["bal"]))
                        self.assertEqual(cells[4][0], "{:,}".format(r["low"]))
                        self.assertEqual(cells[5], ["{:,}".format(r["avail"]), "확정분만", "{:,}".format(p["firm"]["avail"])])

    def test_negative_available_is_red(self):
        import copy
        R = copy.deepcopy(self.R["weekly"])
        R["s2"]["periods"][0]["all"]["avail"] = -5_000_000
        html = first_screen(render(R, "ceo"))
        self.assertRegex(html, r"<b class='neg'>[^<0-9]?5,000,000</b>")

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
            self.assertEqual(cells[5], ["확인", "필요", "확정분만", "확인", "필요"])
        self.assertNotIn("neg", first_screen(html).split("id='avail'>")[1].split("</table>")[0])


class TestReportIsADocument(unittest.TestCase):
    """보고서는 프로그램이 아니라 문서(PDF)로 전달한다 (사용자 2026-11-03): 누르거나 입력하는 것이 없고 모든 값이 그대로 보인다."""

    def test_no_buttons_inputs_or_scripts(self):
        for kind in ("weekly", "monthly"):
            R = compute(load(SAMPLE), kind, ASOF)
            for edition in ("ceo", "mgmt"):
                with self.subTest(kind=kind, edition=edition):
                    html = render(R, edition)
                    for tag in ("<script", "<button", "<input"):
                        self.assertNotIn(tag, html)

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
        self.assertIn("{:,}".format(last["all"]["avail"]), rows[-1][5])
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


if __name__ == "__main__":
    unittest.main()
