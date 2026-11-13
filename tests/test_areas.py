"""경영관리 보고 영역별 보기 (사용자 2026-11-11: 보기 불편 → 영역별로 나눠 보고, 필요하면 전체 출력)."""
import datetime as dt
import importlib.util
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report import areas, evidence  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import render  # noqa: E402
from sample_input import SAMPLE, refresh as refresh_sample  # noqa: E402

WEEK = ["one", "docs", "sum", "ev", "risk", "auto", "s1", "s2", "s3", "s4", "s5", "s6", "s7"]   # 1쪽 요약·본문 맨 앞 (2026-11-12)


def area_ids(page):
    return re.findall(r"<section class='area' id='a-([^']+)'", page)


class TestAreas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        refresh_sample()
        d = load(SAMPLE)
        cls.week = compute(d, "weekly", dt.date(2026, 11, 2))
        cls.month = compute(load(SAMPLE), "monthly", dt.date(2026, 10, 31))

    def test_management_report_is_split_into_areas_in_order(self):
        for R, ids in ((self.week, WEEK), (self.month, WEEK + ["s8", "s9"])):
            page = render(R, "mgmt")
            with self.subTest(R["kind"]):
                self.assertEqual(area_ids(page), ids)
                # 영역 목록에 영역마다 링크 하나, 인쇄 단추 셋
                self.assertEqual(re.findall(r"<a href='#a-([^']+)' data-k=", page), ids)
                for b in ("이 영역 인쇄", "골라서 인쇄", "전체 인쇄", "전체 보기"):
                    self.assertIn(">%s</button>" % b, page)
                self.assertEqual(page.count("<section"), page.count("</section>"))
                # 상세 장 제목(근거 번호가 가리키는 자리)은 그대로
                for i in range(1, 8):
                    self.assertIn("<h2 id='s%d'>" % i, page)

    def test_ceo_report_has_no_area_view(self):
        for R in (self.week, self.month):
            page = render(R, "ceo")
            self.assertNotIn("anav", page)
            self.assertNotIn("<section", page)
            self.assertNotIn("<script", page)

    def test_print_shows_everything_unless_areas_are_picked(self):
        """프로그램이 만드는 PDF 는 전체: 영역 숨김은 화면(@media screen)과 '골라서 인쇄'(body.psel)에서만."""
        css = areas.CSS
        screen = css[css.index("@media screen{"):css.index("@media print{")]
        self.assertIn("section.area:not(.on){display:none}", screen)
        printing = css[css.index("@media print{"):]
        self.assertNotIn(":not(.on)", printing)
        self.assertIn("body.psel section.area:not(.apick){display:none!important}", printing)
        # 접힌 표 줄은 화면에서만 숨김
        self.assertIn("table.afold:not(.aopen) tr.afx{display:none}", screen)

    def test_risk_badge_counts_high_risks(self):
        page = render(self.month, "mgmt")
        hi = sum(1 for r in self.month["risks"] if r["level"] == "높음")
        m = re.search(r"data-k='risk'>A-3 위험 분석·해결방안(?: <span class='abg'>(\d+)</span>)?</a>", page)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1) or 0), hi)

    def test_evidence_blocks_stay_whole(self):
        """근거 뽑기: 상세 장을 가리키는 번호도 영역 틀·단추 없이 장 내용만."""
        page = render(self.month, "mgmt")
        nums = [n for n, _, _ in evidence.index_of(page)]
        self.assertTrue(nums)
        doc = evidence.build(page, nums)
        for bad in ("<section", "</section>", "apager", "anav", "<script"):
            self.assertNotIn(bad, doc)
        self.assertEqual(doc.count("<div"), doc.count("</div>"))

    def test_strip_ui_gives_back_the_plain_document(self):
        page = render(self.month, "mgmt")
        plain = areas.strip_ui(page)
        for bad in ("<section", "<script", "<button", "<input", "anav", "apager", areas.SUMMARY_MARK):
            self.assertNotIn(bad, plain)
        self.assertEqual(plain.count("<div"), plain.count("</div>"))


class TestPdfOutline(unittest.TestCase):
    def test_pdf_has_bookmarks_from_headings(self):
        spec = importlib.util.spec_from_file_location("report_cli_areas", os.path.join(ROOT, "보고서.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            raise OSError("시험: 실행 안 함")
        real = mod.subprocess.run
        mod.subprocess.run = fake_run
        try:
            mod.to_pdf("browser", os.path.join(ROOT, "없음.html"), os.path.join(ROOT, "없음_시험.pdf"))
        except Exception:
            pass
        finally:
            mod.subprocess.run = real
        self.assertIn("--generate-pdf-document-outline", seen.get("cmd", []))


if __name__ == "__main__":
    unittest.main()
