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


def self_chap(page, n):
    """예전 번호 n 장의 조각을 차례로 이은 것."""
    return "".join(m.group(2) for m in re.finditer(r"<!--o:(%s(?:\.\d\d)?)-->(.*?)<!--/o:\1-->" % n, page, re.S))


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
            for k in ("cash", "proj", "pl", "ar", "other", "data"):
                with self.subTest(kind=kind, topic=k):
                    a = area(page, k)
                    pos = [a.index("%s %s" % (c, n)) for c, n in zip(mgmt_topics.CIRCLE, mgmt_topics.LAYERS)]
                    self.assertEqual(pos, sorted(pos))

    def test_topic_without_data_is_short(self):
        """자료가 없어 못 만든 주제(샘플 월간 7·8)는 결론 한 줄과 받을 자료 안내만: 빈 층(③④⑥)을 늘어놓지 않는다 (2026-11-17 목업)."""
        page = self.pages["monthly"]
        for k in ("xchk", "cf"):
            a = area(page, k)
            self.assertIn("① 결론", a)
            self.assertIn("⑤ 상세 표", a)
            for gone in ("③ 지난 보고 뒤 바뀐 것", "④ 자동 분석 · 위험", "tq-tiles"):
                self.assertNotIn(gone, a)
        self.assertIn("#a-xchk{page:mgna}", page)
        self.assertIn("#a-cf{page:mgna}", page)   # 같은 쪽 이름 → 두 주제 사이에 쪽을 넘기지 않음

    def test_long_tables_move_to_appendix_and_come_back_in_old_order(self):
        """긴 표(LONG_ROWS 줄 넘음)는 부록 '긴 표'로, 주제 ⑤에는 가는 곳 한 줄. 예전 순서로 되돌리면 장 안 순서 그대로."""
        for kind, page in self.pages.items():
            with self.subTest(kind):
                tb = area(page, "tbl")
                n = tb.count("<div class='tb ly5'>")
                self.assertGreaterEqual(n, 3)
                self.assertIn("기간 내 예정 전체", tb)
                self.assertNotIn("<h3>기간 내 예정 전체", area(page, "cash"))
                for i in range(1, n + 1):
                    self.assertIn("id='tb-%d'" % i, tb)
                    self.assertEqual(page.count("href='#tb-%d'" % i), 1)
                old = areas.old_view(page)
                s2 = old[old.index("<h2 id='s2'>"):old.index("<h2 id='s3'>")]
                heads = re.findall(r"<h3>(.*?)</h3>", s2)
                self.assertTrue(heads[-1].startswith("기간 내 예정 전체"))
                self.assertLess(s2.index("<h3>날짜 없는 예정금액"), s2.index("<h3>기간 내 예정 전체"))
                for piece in mgmt_topics.split_long(self_chap(page, "042")):
                    self.assertEqual(piece[0].count("<div"), piece[0].count("</div>"))

    def test_split_long_keeps_everything(self):
        body = "<h2 id='s9'>머리</h2><p>앞</p><h3>짧은 표</h3><table><tbody><tr><td>1</td></tr></tbody></table>" \
               "<h3>긴 표 (20건)</h3><div class='tw'><table><tbody>%s</tbody></table></div><div class='note'>뒤</div>" % ("<tr><td>1</td></tr>" * 20)
        ps = mgmt_topics.split_long(body)
        self.assertEqual("".join(p for p, _, _ in ps), body)
        self.assertEqual([(t, lg) for _, t, lg in ps], [(None, False), ("짧은 표", False), ("긴 표 (20건)", True)])
        odd = "<h2>x</h2><div><h3>a</h3></div>"   # h3 가 div 안에 있으면 나누지 않는다
        self.assertEqual(mgmt_topics.split_long(odd), [(odd, None, False)])
        self.assertEqual(mgmt_topics.restore("<!--/head--><!--o:042.01-->B<!--/o:042.01--><!--o:041-->A<!--/o:041--><!--o:042.00-->Z<!--/o:042.00-->"),
                         "AZB</div></body></html>")

    def test_schedule_has_a_subtotal_per_bucket_that_adds_up(self):
        """기간 내 예정 전체: 구간(주·월)마다 소계 줄. 소계의 입금·지급 합은 위 구간 표의 그 구간 합과 같다."""
        from ceo_report.render import _with_subtotals
        for R in (self.week, self.month):
            s2 = R["s2"]
            dated = sorted(s2["dated"], key=lambda e: (e["date"], e["io"]))
            rows = _with_subtotals(dated, s2["buckets"], lambda evs: [[e] for e in evs])
            subs = [r for r in rows if isinstance(r, tuple)]
            self.assertEqual(len(rows) - len(subs), len(dated))
            self.assertTrue(subs)
            self.assertTrue(all(c == "tot wsub" for _, c in subs))
            by = dict((b["label"] + " 소계", b) for b in s2["buckets"])
            for cells, _ in subs:
                b = by[cells[0]]
                tin, tout = (int(x.replace(",", "").replace("−", "-")) for x in re.sub(r"<[^b][^>]*>|</[^>]+>", "", cells[2]).split("<br>"))
                self.assertEqual(tin, b["in_firm"] + b["in_est"], cells[0])
                self.assertEqual(tout, b["out_firm"] + b["out_est"], cells[0])

    def test_print_footer_names_the_report_and_topic(self):
        page = self.pages["monthly"]
        self.assertIn('content:"월간 경영관리 보고 · 기준일 2026-10-31 · 1. 자금"', page)
        self.assertIn('counter(page) " / " counter(pages)', page)
        self.assertIn("body>.wrap{page:mg}", page)
        self.assertNotIn("@page mg", render(self.month, "ceo"))

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
            for bad in ("<!--o:", "tq-", "<section", "<script", "주제별 상태"):
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

    def test_budget_over_not_in_todos_or_check_screen(self):
        """사용자 2026-11-17: 확인할 것에서 예산초과 빼기. 경영관리 위험 분석 표에는 남는다."""
        R = compute(load(SAMPLE), "monthly", dt.date(2026, 10, 31))
        over = [r for r in R["risks"] if mgmt_topics.is_budget_over(r["fact"])]
        self.assertTrue(over, "샘플에 예산 초과 위험이 있어야 시험이 뜻이 있음")
        page = render(R, "mgmt")
        self.assertFalse(any(mgmt_topics.is_budget_over(it["fact"], it["text"]) for it in R["_topics"]["todos"]))
        self.assertIn(over[0]["fact"].split(":")[0], page)   # 경영관리에는 그대로
        out = os.path.join(self.out, "출력")
        path = mgmt_topics.write_record(out, R)
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
        # 예전 판이 남긴 기록의 예산 초과 할 일도 확인할 것 화면에 안 나오고, 다음 보고에서 '처리'로도 안 보인다
        rec["items"]["할일|프로젝트|옛예산"] = {"n": 2, "first": "2026-10-01", "topic": "proj", "owner": "기획1팀",
                                           "text": "남은 지급요청·집행계획 중 줄일 수 있는 항목 확인",
                                           "fact": "26245 A: 등록 지출(장부 전 지급요청 포함) 9,518,819원이 예산 6,022,800원의 158.0%."}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        self.assertNotIn("할일|프로젝트|옛예산", [it["id"] for it in mgmt_topics.check_items(out)])
        R2 = compute(load(SAMPLE), "monthly", dt.date(2026, 11, 30))
        R2["todo_prev"] = mgmt_topics.load_previous(out, "monthly", R2["asof"])
        render(R2, "mgmt")
        self.assertNotIn("할일|프로젝트|옛예산", [d["id"] for d in R2["_topics"].get("done") or []])

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
