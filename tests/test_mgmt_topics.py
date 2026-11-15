"""경영관리 보고 주제별 묶기 (사용자 2026-11-14 결정 카드 '구성안대로 바꾸기').

약속: 지금 보고의 모든 표·내용이 새 보고 어딘가에 그대로 있다 · 대표용 보고는 바뀌지 않는다 · 계산은 그대로.
(예전 순서로 되돌린 문서가 예전 코드의 문서와 같은지는 test_monthly_xchk·test_convert_reports 의 BASELINE 비교가 본다)
"""
import copy
import datetime as dt
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report import areas, checklist, evidence, mgmt_topics  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import render  # noqa: E402
from sample_input import SAMPLE, refresh as refresh_sample  # noqa: E402


def area(page, key):
    m = re.search(r"<section class='area[^']*' id='a-%s'.*?</section>" % key, page, re.S)
    return m.group(0) if m else ""


def tables(html):
    return re.findall(r"<table\b.*?</table>", html, re.S)


class TestTopics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        refresh_sample()
        cls.week = compute(load(SAMPLE), "weekly", dt.date(2026, 11, 2))
        cls.month = compute(load(SAMPLE), "monthly", dt.date(2026, 10, 31))
        cls.pages = {"weekly": render(cls.week, "mgmt"), "monthly": render(cls.month, "mgmt")}

    def test_every_old_table_is_still_somewhere_in_the_new_report(self):
        """예전 문서(대표 화면·근거 묶음·위험 분석·상세 장)의 표 하나하나가 새 보고 안에 글자 그대로 있다."""
        for kind, page in self.pages.items():
            with self.subTest(kind):
                old = areas.old_view(page)
                shown = mgmt_topics._unlabel(page)   # 화면에서 숨긴 예전 번호만 되살려 견줌
                ts = tables(old)
                self.assertGreater(len(ts), 20)
                for t in ts:
                    self.assertIn(t, shown)

    def test_recon_chapter_sits_in_data_topic_after_chapter_7(self):
        """자료 대조(H, 2026-11-14 '대조 결과를 한곳에')는 6. 자료 확인 ⑤에서 7장 바로 뒤. 표는 한 줄도 빼지 않는다."""
        from ceo_report import reconcile
        from ceo_report.render import esc
        R = copy.deepcopy(self.month)
        R["recon_rows"] = [{"구분": "재무상태표", "항목": "보통예금", "비교자료": "위하고 재무상태표", "비교값": 100, "장부값": 90,
                            "차이": -10, "판정": "다름", "할일": "전표 확인", "기준": "같은 날 자료"},
                           {"구분": "차입금", "항목": "신한", "비교자료": "차입금현황", "비교값": 5, "장부값": 5, "차이": 0, "판정": "같음",
                            "할일": "", "기준": ""}]
        page = render(R, "mgmt")
        d = area(page, "data")
        h = reconcile.render(R["recon_rows"], esc)
        self.assertIn(h, d)
        self.assertLess(d.index("<h2 id='s7'>"), d.index("<span id='a-recon'>"))
        self.assertIn("B-7-1", area(page, "all"))
        self.assertRegex(page, r"href='#a-data'[^>]*>.*?<span class='[^']*'>[1-9]")   # '다름' 1줄이 목록 숫자에   # 옛 번호 찾기에도 있다
        self.assertNotIn(h, areas.strip_ui(page))   # 예전 문서 비교에서는 gasu 처럼 새 내용으로 뺀다

    def test_old_chapters_sit_in_their_topic(self):
        page = self.pages["monthly"]
        where = {"s1": "cash", "s2": "cash", "s3": "proj", "s4": "pl", "s5": "ar", "s6": "other", "s7": "data", "s8": "xchk"}
        for s, t in where.items():
            with self.subTest(s):
                self.assertIn("<h2 id='%s'>" % s, area(page, t))
        self.assertIn("id='a-s9'", area(page, "cf"))
        self.assertIn("id='a-gasu'", area(page, "cash")) if "gasu" in self.month else None
        # 프로젝트별 원가 예산·집행(예전 A-2 9번)은 2 ⑤, 안 들어간 것(10번)은 1 ⑥, 위험 분석 전체 표는 부록
        self.assertIn("프로젝트별 원가 예산·집행", area(page, "proj"))
        self.assertIn("위 숫자에 안 들어간 것", area(page, "cash"))
        self.assertIn("<h2 id='risk'>", area(page, "all"))
        self.assertIn("<div class='four top'>", area(page, "sum"))

    def test_each_topic_has_the_six_layers_in_order(self):
        for kind, page in self.pages.items():
            keys = ("cash", "proj", "pl", "ar", "other", "data") + (("xchk", "cf") if kind == "monthly" else ())
            for k in keys:
                with self.subTest(kind=kind, topic=k):
                    a = area(page, k)
                    pos = [a.index("%s %s" % (c, n)) for c, n in zip(mgmt_topics.CIRCLE, mgmt_topics.LAYERS)]
                    self.assertEqual(pos, sorted(pos))

    def test_every_risk_row_and_auto_analysis_is_in_a_topic(self):
        page = self.month and self.pages["monthly"]
        topics = "".join(area(page, k) for k in mgmt_topics.TOPIC_KEYS)
        for r in self.month["risks"]:
            self.assertIn(r["fact"].replace("'", "&#x27;").replace("&", "&amp;") if False else r["fact"][:20], topics)
        for n in range(2, 16):   # 1 경보는 줄마다 해당 주제 ④
            self.assertIn("<small class='oldl'>자동 분석 %d</small>" % n, topics, n)
        self.assertNotIn("<small class='oldl'>자동 분석", area(page, "all"))   # 남는 분석 없음

    def test_empty_analyses_fold_to_one_line(self):
        page = self.pages["monthly"]
        for m in re.finditer(r"<div class='ynone'>.*?<div class='ypiece'>(.*?)</div></div>", page, re.S):
            for piece in re.split(r"(?=<h3>)", m.group(1)):
                if piece:
                    self.assertRegex(piece, r"^<h3>.*?</h3><p class='note'>[^<]*</p>$")

    def test_ids_are_unique(self):
        for kind, page in self.pages.items():
            ids = re.findall(r"\sid='([^']+)'", page)
            dup = sorted(set(i for i in ids if ids.count(i) > 1))
            with self.subTest(kind):
                self.assertEqual(dup, [])

    def test_links_go_somewhere(self):
        for kind, page in self.pages.items():
            ids = set(re.findall(r"\sid='([^']+)'", page))
            for h in set(re.findall(r"href='#([^']+)'", page)):
                with self.subTest(kind=kind, href=h):
                    self.assertIn(h, ids)

    def test_ceo_edition_is_unchanged(self):
        for R in (self.week, self.month):
            page = render(R, "ceo")
            for bad in ("<!--o:", "tq-", "<section", "<script", "주제별 신호"):
                self.assertNotIn(bad, page)

    def test_first_screen_ceo_numbers_are_the_ceo_cards(self):
        ceo = render(self.month, "ceo")
        strip = re.search(r"<div class='four top'>.*?</div></div></div>", ceo, re.S).group(0)
        bigs = re.findall(r"<div class='big'>(.*?)</div>", strip)
        home = area(self.pages["monthly"], "home")
        self.assertEqual(re.findall(r"<div class='tq-cv'>(.*?)</div>", home), bigs)
        self.assertEqual(home.count("<span class='tq-tag'>대표 보고</span>"), len(bigs))

    def test_weekly_opens_cash_other_and_data(self):
        page = self.pages["weekly"]
        for k in ("cash", "other", "data"):
            self.assertNotRegex(page, r"<section class='area tfold' id='a-%s'" % k)

    def test_folded_topic_hides_only_on_screen(self):
        css = mgmt_topics.CSS
        screen = css[css.index("@media screen{"):css.index("@media print")]
        self.assertIn("section.tfold .tq-ly.lx{display:none}", screen)
        self.assertNotIn("tfold", css[css.index("@media print"):])

    def test_evidence_still_pulls_chapters(self):
        page = self.pages["monthly"]
        nums = [n for n, _, _ in evidence.index_of(page)]
        doc = evidence.build(page, nums)
        self.assertNotIn("class='onum'", doc)
        self.assertNotIn("<!--o:", doc)
        self.assertIn("<h2 id='s2'>2. ", doc)
        self.assertEqual(doc.count("<div"), doc.count("</div>"))


class TestTodoCarry(unittest.TestCase):
    def setUp(self):
        refresh_sample()
        self.out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.out, True)

    def test_new_then_carried_then_done_and_decisions(self):
        R1 = compute(load(SAMPLE), "weekly", dt.date(2026, 10, 26))
        render(R1, "mgmt")
        ids1 = [it["id"] for it in R1["_topics"]["todos"]]
        self.assertTrue(ids1)
        self.assertTrue(all(it["state"] == "새로" for it in R1["_topics"]["todos"]))
        path = mgmt_topics.write_record(self.out, R1)
        self.assertTrue(os.path.exists(path))
        # 지난 기록에 이번엔 없는 할 일 하나를 넣어 '처리'가 되는지
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
        rec["items"]["할일|자금|없어진일"] = {"n": 1, "first": "2026-10-26", "text": "없어진 일", "topic": "cash", "owner": "경영관리"}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)

        R2 = compute(load(SAMPLE), "weekly", dt.date(2026, 11, 2))
        R2["todo_prev"] = mgmt_topics.load_previous(self.out, "weekly", R2["asof"])
        same = [it for it in mgmt_topics.todo_items(R2, None, []) if it["id"] in ids1]
        self.assertTrue(same)
        R2["todo_decisions"] = {same[0]["id"]: {"결정": "처리함", "메모": "11/01 통화"}}
        page = render(R2, "mgmt")
        st = dict((it["id"], it) for it in R2["_topics"]["todos"])
        self.assertEqual(st[same[0]["id"]]["state"], "처리함")
        self.assertEqual(st[same[0]["id"]]["memo"], "11/01 통화")
        if len(same) > 1:
            self.assertEqual(st[same[1]["id"]]["state"], "이월 1번째")
        home = area(page, "home")
        self.assertIn("없어진 일", home)
        self.assertIn("<span class='tq-stt v-done'>처리</span>", home)
        self.assertIn("11/01 통화", home)

    def test_same_task_keeps_its_id_when_numbers_change(self):
        a = mgmt_topics.todo_id("수금", "P26202 B사: 입금예정일 2026-09-30에서 31일 경과, 미수 110,000,000원.", "거래처 담당자에게 지급 일정 확인")
        b = mgmt_topics.todo_id("수금", "P26202 B사: 입금예정일 2026-09-30에서 38일 경과, 미수 90,000,000원.", "거래처 담당자에게 지급 일정 확인")
        c = mgmt_topics.todo_id("수금", "P26203 C사: 입금예정일 2026-09-30에서 31일 경과, 미수 110,000,000원.", "거래처 담당자에게 지급 일정 확인")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_check_screen_lists_report_todos(self):
        R = compute(load(SAMPLE), "monthly", dt.date(2026, 10, 31))
        render(R, "mgmt")
        mgmt_topics.write_record(os.path.join(self.out, "출력"), R)
        items = mgmt_topics.check_items(os.path.join(self.out, "출력"))
        self.assertEqual(len(items), len(R["_topics"]["todos"]))
        self.assertTrue(all(it["kind"] == "보고 할 일" and it["choices"] for it in items))
        # 결정은 확인결정.csv 에 쌓이고 그대로 읽힌다
        inp = os.path.join(self.out, "입력")
        os.makedirs(inp)
        checklist.save_decision(inp, items[0]["id"], "처리함", "메모")
        self.assertEqual(checklist.read_decisions(inp)[items[0]["id"]]["결정"], "처리함")

    def test_ceo_card_delta(self):
        c = {"label": "이번 주 여유 자금", "value": 100, "good_up": True}
        self.assertIn("tq-cd v-up", mgmt_topics._delta(c, {"ceo": {"이번 주 여유 자금": 50}}))
        self.assertIn("tq-cd v-dn", mgmt_topics._delta(dict(c, good_up=False), {"ceo": {"이번 주 여유 자금": 50}}))
        self.assertIn("지난 기록 없음", mgmt_topics._delta(c, None))

    def test_next_report_date(self):
        R = {"kind": "monthly", "asof": dt.date(2026, 11, 30)}
        self.assertEqual(mgmt_topics._next_report(R), dt.date(2026, 12, 31))
        R = {"kind": "monthly", "asof": dt.date(2026, 12, 31)}
        self.assertEqual(mgmt_topics._next_report(R), dt.date(2027, 1, 31))
        self.assertEqual(mgmt_topics._next_report({"kind": "weekly", "asof": dt.date(2026, 11, 2)}), dt.date(2026, 11, 9))


class TestSplitFallback(unittest.TestCase):
    def test_unexpected_evidence_shape_moves_whole(self):
        mark = areas.SUMMARY_MARK
        self.assertEqual(mgmt_topics.split_evidence("<div>x</div>", mark), [(20, "appx", "<div>x</div>")])
        odd = mark + "<div class='page'><div>a</div></div><div>b</div>"
        self.assertEqual(len(mgmt_topics.split_evidence(odd, mark)), 1)

    def test_restore_puts_pieces_back_in_old_order(self):
        page = ("HEAD<!--/head-->" + mgmt_topics.frag(41, "S1") + mgmt_topics.hidden(25, "</div>")
                + mgmt_topics.frag(10, "SUM") + mgmt_topics.frag(30, "RISK"))
        self.assertEqual(mgmt_topics.restore(page), "HEADSUM</div>RISKS1</div></body></html>")
        self.assertIn("</div><div class='toc'></div>RISK", mgmt_topics.restore(page, toc=True))


if __name__ == "__main__":
    unittest.main()
