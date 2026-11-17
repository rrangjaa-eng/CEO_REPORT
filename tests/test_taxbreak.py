import csv
import os
import tempfile
import unittest

from ceo_report import taxbreak as tb


def folder(pay, base=200_000_000, tax=20_000_000, year=2026):
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "사원급여.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["연월", "부서", "사원명", "급여"])
        for ym, names in pay.items():
            for n in names:
                w.writerow([ym, "팀", n, "3000000"])
    with open(os.path.join(d, "세금예상.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["세목", "대상기간", "납부예정일", "금액", "상태", "근거", "과세표준", "산출세액", "기납부"])
        w.writerow(["법인세", "%d년 (1월~10월 장부 기준)" % year, "%d-03-31" % (year + 1), tax, "예상", "", base, tax, 0])
    return d


YES = {"과밀억제": "아니오", "수도권": "예", "청년창업": "아니오", "신규창업": "예", "감면업종": "예", "작년감면": "둘 다", "연구전담": "아니오"}


def row(T, name):
    return [r for r in T["rows"] if r[0].startswith(name)][0]


class Startup(unittest.TestCase):
    def test_rate_by_region_and_age(self):
        d = folder({})
        T = tb.check(d, 2026, YES)
        self.assertEqual(row(T, "창업중소기업")[1:3], ("해당", 10_000_000))   # 과밀 밖, 35세 이상 → 50%
        T = tb.check(d, 2026, dict(YES, 과밀억제="예"))
        self.assertEqual(row(T, "창업중소기업")[1], "해당 없음")
        T = tb.check(d, 2026, dict(YES, 과밀억제="예", 청년창업="예"))
        self.assertEqual(row(T, "창업중소기업")[2], 10_000_000)

    def test_unknown_industry_needs_check_not_counted(self):
        T = tb.check(folder({}), 2026, dict(YES, 감면업종="모름"))
        self.assertEqual(row(T, "창업중소기업")[1], "확인 필요")
        self.assertEqual(T["total"], 0)

    def test_min_tax_caps_total(self):
        T = tb.check(folder({}, base=200_000_000, tax=20_000_000), 2026, YES)
        self.assertEqual(T["total"], 6_000_000)   # 2천만 − 최저한세 1,400만
        self.assertIn("최저한세", T["note"])

    def test_period_over(self):
        self.assertEqual(row(tb.check(folder({}, year=2030), 2030, YES), "창업중소기업")[1], "해당 없음")


class Hiring(unittest.TestCase):
    def test_increase_counts_and_shareholders_excluded(self):
        pay = dict(("2025-%02d" % m, ["대표", "a", "b"]) for m in range(1, 13))
        pay.update(("2026-%02d" % m, ["대표", "a", "b", "c", "d"]) for m in range(1, 13))
        d = folder(pay)
        r = row(tb.check(d, 2026, YES, holders=["대표"]), "통합고용")
        # 2026-11-17 법령 확인 (조특법 29조의8 개정 + 부칙 34조): 2026년 +2명은 새 규정 직전 해 대비 1명당 400만(수도권, 청년 외),
        # 2025년 +2명(0명에서)은 옛 규정 850만을 2027년까지 → 800만 + 1,700만
        self.assertEqual(r[1], "해당")
        self.assertEqual(r[2], 2 * 4_000_000 + 2 * 8_500_000)
        self.assertIn("부칙 34조", r[3])

    def test_young_and_officer_from_staff_file(self):
        pay = dict(("2025-%02d" % m, ["대표", "임원", "a", "b"]) for m in range(1, 13))
        pay.update(("2026-%02d" % m, ["대표", "임원", "a", "b", "c", "d"]) for m in range(1, 13))
        d = folder(pay)
        with open(os.path.join(d, "사원.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["사원명", "생년월일", "임원"])
            w.writerows([["임원", "1970-01-01", "예"], ["a", "1980-01-01", ""], ["b", "1980-01-01", ""],
                         ["c", "2000-01-01", ""], ["d", "1980-01-01", ""]])
        r = row(tb.check(d, 2026, YES, holders=["대표"]), "통합고용")
        # 2026 +2명(c 청년 26세, d): 청년 등 1명 700만 + 그 외 1명 400만 (새 규정) · 2025 +2명(a,b) 옛 규정 850만씩
        self.assertEqual(r[2], 7_000_000 + 4_000_000 + 2 * 8_500_000)
        self.assertIn("청년 등 직전 해 대비 1.0명", r[3])

    def test_tiers_2027(self):
        from ceo_report.taxbreak import _tier_incs
        # 2025 2명 → 2026 4명 → 2027 5명: 직전 대비 +1, 전전(2025) 대비 min(5,4)−2 = +2, 전전전(2024)은 비교 안 함
        self.assertEqual(_tier_incs({2025: 2.0, 2026: 4.0, 2027: 5.0}, 2027), [1.0, 2.0, 0.0])

    def test_prev_year_unknown(self):
        pay = dict(("2026-%02d" % m, ["a"]) for m in range(1, 11))
        r = row(tb.check(folder(pay), 2026, YES), "통합고용")
        self.assertEqual(r[1], "확인 필요")
        self.assertIn("2025년 인원을 몰라", r[3])

    def test_missed_last_year_claim(self):
        T = tb.check(folder({}), 2026, dict(YES, 작년감면="없음"))
        self.assertIn("경정청구", row(T, "2025년분")[0])

    def test_render(self):
        from ceo_report.util import esc
        h = tb.render(tb.check(folder({}), 2026, YES), esc)
        self.assertIn("세무사 확인", h)
        self.assertIn("창업중소기업", h)


if __name__ == "__main__":
    unittest.main()


class FullReview1117(unittest.TestCase):
    """2026-11-17 사용자: 법인세 감면·공제를 모두 최신 법령 기준으로 찾아 적용할 게 있는지 검토 (보여 주기만). 숫자는 모두 가짜."""

    def _write(self, d, name, head, rows):
        with open(os.path.join(d, name), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(head)
            w.writerows(rows)

    def test_missing_year_from_wehago_pay_screen_and_owner_only_month_is_zero(self):
        d = folder(dict(("2026-%02d" % m, ["대표", "a", "b", "c"]) for m in range(1, 11)))
        rows = [["2025-02", "대표", "지급", "지급합계", "100"], ["2025-03", "대표", "지급", "지급합계", "100"]]
        rows += [["2025-%02d" % m, n, "지급", "지급합계", "100"] for m in range(4, 13) for n in ("대표", "a", "b")]
        self._write(d, "급여명세.csv", ["연월", "사원명", "구분", "항목", "금액"], rows)
        hc = tb.headcount(d, ["대표"])
        self.assertAlmostEqual(hc[2025][0], 18 / 11.0)   # 2~3월 0명 + 4~12월 2명 = 18 ÷ 11달
        self.assertEqual(hc[2026], (3.0, 10))            # 올해는 장부 사원급여 그대로

    def test_training_cost_and_pay_based_rows(self):
        d = folder({})
        self._write(d, "계정별비용.csv", ["연월", "구분", "계정코드", "계정과목", "금액"],
                    [["2026-03", "판매비와관리비", "82500", "교육훈련비(판)", "400000"]])
        pay = [["2025-%02d" % m, "a", "지급", "지급합계", "1000"] for m in range(1, 13)]
        pay += [["2026-%02d" % m, "a", "지급", "지급합계", "1200"] for m in range(1, 11)]
        self._write(d, "급여명세.csv", ["연월", "사원명", "구분", "항목", "금액"], pay)
        T = tb.check(d, 2026, YES)
        r = row(T, "인력개발비")
        self.assertEqual(r[1:3], ("확인 필요", 100_000))
        self.assertIn("최저한세 안 걸림", r[5])
        self.assertEqual(row(T, "고용유지")[1], "해당 없음")        # 1인당 급여가 늘었음
        self.assertEqual(row(T, "근로소득을 늘린")[1], "해당 없음")  # 2025 창업 → 직전 3년 증가율 2029년부터, 법 기한 2028
        self.assertEqual(row(T, "영상콘텐츠")[1], "해당 없음")
        self.assertEqual(T["total"], tb.check(folder({}), 2026, YES)["total"])   # 새 후보는 합계(배당 판단)를 바꾸지 않음
        names = [x[0] for x in T["rows"]]
        for want in ("상생결제", "상생협력 출연금", "성과공유", "전자신고", "외국납부", "재해손실", "중소기업 사회보험료", "고용을 늘린 기업"):
            self.assertTrue(any(n.startswith(want) for n in names), want)

    def test_deadline_read_from_downloaded_article(self):
        import json
        d = folder({})
        items = {"조세특례제한법 30조의3": {"text": "① 고용유지중소기업은 … 2025년 12월 31일이 속하는 과세연도까지 공제한다.",
                                         "시행일자": "20260918", "seen": "2026-11-17", "keys": []}}
        with open(os.path.join(d, "세법조문.json"), "w", encoding="utf-8") as f:
            json.dump({"oc": "", "items": items}, f, ensure_ascii=False)
        r = row(tb.check(d, 2026, YES), "고용유지")
        self.assertEqual(r[1], "해당 없음")
        self.assertIn("법 기한(2025년)이 지남", r[3])
        self.assertIn("시행 2026-09-18", r[5])

    def test_agent_filing_means_no_e_filing_credit(self):
        rows = tb.review_more(folder({}), 2026, YES, {"조정": "외부 (세무법인)"})
        r = [x for x in rows if x[0] == "전자신고 세액공제"][0]
        self.assertEqual(r[1], "해당 없음")

    def test_render_has_law_column(self):
        h = tb.render(tb.check(folder({}), 2026, YES), lambda x: x)
        self.assertIn("근거 조문", h)
        self.assertIn("조특법 10조", h)
        self.assertIn("보여 주기만", h)


class ResearchDeclined1117(unittest.TestCase):
    def test_company_decided_not_to_claim(self):
        T = tb.check(folder({}), 2026, dict(YES, 연구전담="예", 연구공제="안 받음"))
        r = row(T, "연구·인력개발비")
        self.assertEqual(r[1], "해당 없음")
        self.assertIn("회사가 공제를 받지 않기로", r[3])
        self.assertEqual(row(tb.check(folder({}), 2026, dict(YES, 연구전담="예")), "연구·인력개발비")[1], "확인 필요")
