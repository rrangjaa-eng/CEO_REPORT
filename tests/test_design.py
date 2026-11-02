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
  var tw=document.querySelector('.mid .tw');
  b.setAttribute('data-twsw',String(tw.scrollWidth));
  b.setAttribute('data-twcw',String(tw.clientWidth));
  var tot=tw.querySelector('tr.tot');
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


LOW_LABEL = "최저 계산 잔액 (확정 일정만)"


def kpi_parts(html, label):
    """첫 화면 KPI 칸 (값 HTML, 아래 줄 HTML, 칸 class). 없으면 None."""
    m = re.search(r"<div class='(kpi[^']*)'><div class='l'>" + re.escape(label) +
                  r"</div><div class='v'>(.*?)</div><div class='s'>(.*?)</div></div>", html, re.S)
    return (m.group(2), m.group(3), m.group(1)) if m else None


def first_screen(html):
    return html.split("<div class='toc'>")[0]


class TestLowestBalanceCard(unittest.TestCase):
    """첫 화면의 질문 '앞으로 잔액이 가장 낮을 때 얼마인가'를 첫 줄 카드가 답한다 (값은 기존 계산 그대로)."""

    @classmethod
    def setUpClass(cls):
        cls.R = compute(load(SAMPLE), "weekly", ASOF)

    def test_card_shows_lowest_firm_balance_date_and_reserve(self):
        for mode in ("ceo", "mgmt"):
            with self.subTest(mode=mode):
                v, s, cls_ = kpi_parts(first_screen(render(self.R, mode)), LOW_LABEL)
                self.assertIn("19.8", v)
                self.assertIn("백만원", v)
                self.assertIn("2027-04-25", s)
                self.assertIn("최소 보유현금 100.0 미만", s)
                self.assertIn("금액 미확인 1건 (미반영)", s)
                self.assertIn("lv-reserve", cls_)

    def test_card_is_in_the_kpi_row(self):
        fs = first_screen(render(self.R, "ceo"))
        kpis = fs.split("<div class='kpis'>")[1].split("<div class='mid'>")[0]
        self.assertIn(LOW_LABEL, kpis)

    def test_unknown_balance_says_so(self):
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        folder = os.path.join(tmp, "입력")
        shutil.copytree(SAMPLE, folder)
        os.remove(os.path.join(folder, "계좌잔액.csv"))
        v, s, cls_ = kpi_parts(first_screen(render(compute(load(folder), "weekly", ASOF), "ceo")), LOW_LABEL)
        self.assertIn("잔액 미확인", v)
        self.assertNotIn("백만원", v)
        self.assertNotIn("lv-", cls_)


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
