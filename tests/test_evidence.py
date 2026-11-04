"""근거 번호 · 근거자료만 따로 · 대표용엔 예산·판단할 것 없음 · 자금 표 기간 · 사용제한 해제일 (사용자 2026-11-03). 가상 자료만."""
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

from ceo_report import app, evidence  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import evidence_index, render, week_outflows  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
D = dt.date
ASOF = D(2026, 10, 31)


def ev_tags(html):
    """숫자 옆 근거 꼬리표의 번호들. '근거 1-1~1-3' 은 1-1, 1-2, 1-3 (사용자 2026-11-04 디자인 검토)."""
    out = set()
    for t in re.findall(r"<span class='ev'>근거 ([^<]+)</span>", html):
        for part in t.split(", "):
            if "~" in part:
                a, b = part.split("~")
                h, i, j = a.split("-")[0], int(a.split("-")[1]), int(b.split("-")[1])
                out.update("%s-%d" % (h, k) for k in range(i, j + 1))
            else:
                out.add(part)
    return out


def text(html):
    body = html[html.index("<body"):].split("<div class='toc'>")[0]
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


class TestCeoHasNoBudgetNoDecisions(unittest.TestCase):
    """대표용엔 예산 언급·판단할 것 없음. 근거 번호는 두 판 모두 남긴다."""

    def test_ceo_first_screen(self):
        for kind in ("weekly", "monthly"):
            R = compute(load(SAMPLE), kind, ASOF)
            ceo, mgmt = render(R, "ceo"), render(R, "mgmt")
            with self.subTest(kind=kind):
                self.assertNotIn("예산", text(ceo))
                self.assertNotIn("판단할 것", ceo)
                self.assertIn("판단할 것 (경영관리용)", mgmt)
                for n, _, _ in evidence_index(R):
                    self.assertIn(n, ev_tags(ceo))
                    self.assertIn(n, ev_tags(mgmt))
                    self.assertIn("<td><b>근거 %s</b></td>" % n, mgmt)
                    self.assertNotIn("<td><b>근거 %s</b></td>" % n, ceo)
                self.assertNotIn("class='evb'", ceo)

    def test_remaining_budget_rows_are_named_as_payments(self):
        R = compute(load(SAMPLE), "weekly", ASOF)
        self.assertNotIn("프로젝트 남은 예산", text(render(R, "ceo")))


class TestEvidenceDocument(unittest.TestCase):
    def test_parse_nums(self):
        self.assertEqual(evidence.parse_nums("근거 1-1, 3-2 1-1"), ["1-1", "3-2"])
        for bad in ("", "1", "가-1"):
            with self.assertRaises(ValueError):
                evidence.parse_nums(bad)

    def test_build_takes_blocks_and_chapters_from_the_management_report(self):
        for kind in ("weekly", "monthly"):
            R = compute(load(SAMPLE), kind, ASOF)
            mg = render(R, "mgmt")
            idx = evidence.index_of(mg)
            self.assertEqual([n for n, _, _ in idx], [n for n, _, _ in evidence_index(R)])
            doc = evidence.build(mg, [n for n, _, _ in idx])
            with self.subTest(kind=kind):
                body = doc[doc.index("<body>"):]
                self.assertEqual(body.count("<div"), body.count("</div>"))
                for n, _, w in idx:
                    self.assertIn("근거 %s" % n, body)
                    self.assertIn("id='%s'" % w, body)
                self.assertIn("근거자료", doc[:doc.index("<body>")])
        with self.assertRaises(ValueError) as cm:
            evidence.build(mg, ["9-9"])
        self.assertIn("있는 번호", str(cm.exception))

    def test_cli_and_window_task(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(SAMPLE, os.path.join(tmp, "입력"))
        os.makedirs(os.path.join(tmp, "수집", "위하고"))
        P = app.Paths(tmp)
        lines = []
        rc, _ = app.run_task("근거주간", P, lines.append, asof="2026-10-31", nums="1-1")
        self.assertEqual(rc, 2)   # 경영관리 보고를 먼저 만들어야 한다
        self.assertIn("경영관리 보고가 없습니다", " ".join(lines))
        self.assertEqual(app.run_task("주간", P, lines.append, asof="2026-10-31")[0], 0)
        lines = []
        rc, files = app.run_task("근거주간", P, lines.append, asof="2026-10-31", nums="1-1, 3-2")
        self.assertEqual(rc, 0, lines)
        self.assertTrue(any(f.endswith("_주간_근거자료_1-1_3-2.html") for f in files), files)
        lines = []
        self.assertEqual(app.run_task("근거주간", P, lines.append, asof="2026-10-31", nums="")[0], 2)
        self.assertIn("근거 번호를 넣으세요", lines[0])


class TestCashTableMatchesPayLists(unittest.TestCase):
    """주간 자금 표: 토~금 한 주, 그 주 금액 → 금요일 출금 합계·다음 주 지급 예정 합계와 같다."""

    def test_this_and_next_week_equal_the_lists(self):
        R = compute(load(SAMPLE), "weekly", ASOF)
        W = week_outflows(R)
        p = R["s2"]["periods"]
        self.assertEqual((p[0]["end"], p[1]["end"]), (W["fri"], W["end"]))
        self.assertEqual(p[0]["all"]["pout"], W["pay"]["total"] + W["pay_est"]["total"])   # 목록은 확정만, 자금 표는 예상분 포함
        self.assertEqual(p[0]["firm"]["pout"], W["pay"]["total"])
        self.assertEqual(p[1]["all"]["pout"], W["next"]["total"])
        b = R["s2"]["buckets"]   # 그림의 주도 같은 주
        self.assertEqual((b[0]["to"], b[1]["to"]), (W["fri"], W["end"]))


class TestRestrictionReleaseDate(unittest.TestCase):
    """계좌잔액.csv 제한해제일 (선택 칸): 그날 쓸 수 있는 돈으로 자금 일정에 들어가고, 지난 날짜면 빼지 않는다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(SAMPLE, os.path.join(self.tmp, "in"))
        self.inp = os.path.join(self.tmp, "in")
        p = os.path.join(self.inp, "계좌잔액.csv")
        with open(p, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
        lines = [lines[0] + ",제한해제일"] + [l + (",2026-11-10" if "프로젝트계좌" in l else ",") for l in lines[1:]]
        with open(p, "w", encoding="utf-8-sig") as f:
            f.write("\n".join(lines) + "\n")

    def test_release_becomes_money_on_that_day(self):
        base = compute(load(SAMPLE), "weekly", ASOF)
        R = compute(load(self.inp), "weekly", ASOF)
        self.assertEqual(R["s1"]["available"], base["s1"]["available"])
        rel = [e for e in R["s2"]["dated"] if e["cat"] == "사용제한 해제"]
        self.assertEqual([(e["date"], e["amount"], e["io"], e["firm"]) for e in rel], [(D(2026, 11, 10), 30_000_000, "in", True)])
        self.assertEqual(R["s2"]["periods"][1]["all"]["pin"], base["s2"]["periods"][1]["all"]["pin"] + 30_000_000)

    def test_past_release_is_not_subtracted(self):
        R = compute(load(self.inp), "weekly", D(2026, 11, 12))
        self.assertEqual(R["s1"]["restricted"], 0)
        self.assertFalse([e for e in R["s2"]["dated"] if e["cat"] == "사용제한 해제"])

    def test_old_files_without_the_column_still_work(self):
        self.assertEqual(compute(load(SAMPLE), "weekly", ASOF)["s1"]["restricted"], 30_000_000)


if __name__ == "__main__":
    unittest.main()
