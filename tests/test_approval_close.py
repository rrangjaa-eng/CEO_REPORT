"""인트라넷 승인 단계 (사용자 2026-11-11).

· 대표이사 승인까지 끝난 프로젝트 = 종결: 남은 예산을 지급 예정으로 잡지 않는다.
· 대표이사 승인까지 끝난 프로젝트의 앞으로 들어올 매출·행사 후 미발행 = 확정 견적금액 − 발행 (사전견적 대신).
· 최종 실행가 차이 표 = 팀장 승인 ~ 대표이사 승인 프로젝트만, 장부 원가에 법인카드 부가세를 더해 견주고 차이마다 설명.
"""
import csv
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import calc, convert_xchk, data, linking, render  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력양식", "샘플")
ASOF = dt.date(2026, 11, 2)


def folder_with(test, changes):
    """샘플 입력 폴더를 복사하고 프로젝트.csv 에 견적금액·승인단계 칸을 더한다. changes = {번호: (견적금액, 승인단계)}."""
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    dst = os.path.join(tmp, "입력")
    shutil.copytree(SAMPLE, dst)
    path = os.path.join(dst, "프로젝트.csv")
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    rows[0] += ["견적금액", "승인단계"]
    for r in rows[1:]:
        r += list(changes.get(r[0], ("", "")))
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)
    return dst


def weekly(folder):
    return calc.compute(data.load(folder), "weekly", ASOF)


def budget_events(R, pid):
    return [e for e in R["events"] if e.get("source") == "남은 예산" and e["project"] == pid]


class TestApprovalStage(unittest.TestCase):
    def stage(self, *cells):
        return linking.approval_stage(dict(zip(["승인_담당자", "승인_팀장", "승인_관리팀", "승인_대표이사"], cells)))

    def test_highest_finished_stage(self):
        self.assertEqual(self.stage("수락완료", "수락완료", "미승인", "미승인"), "팀장")
        self.assertEqual(self.stage("수락완료", "수락완료", "수락완료", "미승인"), "관리팀")
        self.assertEqual(self.stage("수락완료", "수락완료", "수락완료", "수락완료"), "대표이사")

    def test_merged_done_cell_means_all_finished(self):
        self.assertEqual(self.stage("완료", "", "", ""), "대표이사")

    def test_reject_button_means_that_stage_is_finished(self):
        self.assertEqual(self.stage("수락완료", "반려", "승인", "미승인"), "팀장")

    def test_approve_button_blank_and_unknown_words_are_not_finished(self):
        self.assertEqual(self.stage("승인", "승인", "승인", "승인"), "")
        self.assertEqual(self.stage("", "", "", ""), "")
        self.assertEqual(self.stage("검토중", "?", "", ""), "")

    def test_words_summary_counts_each_text(self):
        text = linking.approval_words([{"승인_담당자": "완료"}, {"승인_담당자": "승인", "승인_대표이사": "미승인"}])
        self.assertIn("담당자 '완료' 1, '승인' 1", text)
        self.assertIn("대표이사 '(빈칸)' 1, '미승인' 1", text)


class TestClosedByCeoApproval(unittest.TestCase):
    def test_remaining_budget_is_not_scheduled_once_the_ceo_approved(self):
        before = weekly(folder_with(self, {}))
        self.assertTrue(budget_events(before, "P26207"))
        after = weekly(folder_with(self, {"P26207": ("", "대표이사")}))
        self.assertEqual(budget_events(after, "P26207"), [])
        # 다른 프로젝트는 그대로
        self.assertEqual([e["amount"] for e in budget_events(after, "P26201")],
                         [e["amount"] for e in budget_events(before, "P26201")])

    def test_lower_stages_do_not_close_the_project(self):
        before = weekly(folder_with(self, {}))
        for stage in ("담당자", "팀장", "관리팀"):
            after = weekly(folder_with(self, {"P26207": ("", stage)}))
            self.assertEqual(len(budget_events(after, "P26207")), len(budget_events(before, "P26207")), stage)

    def test_old_file_without_the_columns_reads_as_not_approved(self):
        R = weekly(SAMPLE)
        self.assertTrue(all(not P.get("approval") and P.get("quote") is None for P in R["s3"]["projects"]))


class TestRevenueBasis(unittest.TestCase):
    def test_quote_replaces_estimate_only_after_ceo_approval(self):
        P = {"estimate": 100, "quote": 90, "approval": "대표이사"}
        self.assertEqual(calc.revenue_basis(P), 90)
        self.assertEqual(calc.revenue_basis(dict(P, approval="관리팀")), 100)
        self.assertEqual(calc.revenue_basis(dict(P, quote=None)), 100)

    def test_expected_revenue_and_unissued_shrink_to_the_quote(self):
        before = weekly(folder_with(self, {}))
        x = [y for y in before["s5"]["by_project"] if y["P"]["id"] == "P26205"][0]
        est, issued = x["P"]["estimate"], x["issued"]
        self.assertGreater(est - issued, 0)   # 샘플: 행사 끝남, 사전견적보다 덜 발행
        quote = issued + 1000000
        after = weekly(folder_with(self, {"P26205": (str(quote), "대표이사")}))
        E0, E1 = before["s5"]["expected"], after["s5"]["expected"]
        self.assertEqual(E1["past"], E0["past"] - (est - issued) + 1000000)
        self.assertEqual(E1["quoted_n"], 1)
        row = [r for r in after["s5"]["event_unissued"]["rows"] if r["P"]["id"] == "P26205"][0]
        self.assertEqual((row["estimate"], row["unissued"], row["quoted"]), (quote, 1000000, True))
        # 승인이 관리팀까지면 사전견적 그대로
        mid = weekly(folder_with(self, {"P26205": (str(quote), "관리팀")}))
        self.assertEqual(mid["s5"]["expected"]["past"], E0["past"])


def xproject(key, cost, budget, card_vat=None, requested=None, out=False):
    return {"key": key, "name": "가상 " + key, "cost": cost, "cost_lines": 3, "cost_note": "", "cost_period": None,
            "out_of_period": out, "budget": budget, "budget_note": "", "has_budget": budget is not None,
            "requested": requested, "requested_count": None, "requested_note": "", "cost_vs_budget": None,
            "request_vs_cost": None, "card_vat": card_vat, "card_n": 2 if card_vat else None}


def final_table(projects, stages):
    X = {"projects": projects, "meta": {}}
    R = {"s3": {"projects": [{"id": k, "approval": v} for k, v in stages.items()]}}
    return render._xk_final_table(X, R)


class TestFinalExecutionTable(unittest.TestCase):
    def test_only_team_leader_approval_and_above_are_listed(self):
        html = final_table([xproject(k, 100, 100) for k in ("A", "B", "C", "D", "E")],
                           {"A": "", "B": "담당자", "C": "팀장", "D": "관리팀", "E": "대표이사"})
        for key, shown in (("가상 A", False), ("가상 B", False), ("가상 C", True), ("가상 D", True), ("가상 E", True)):
            self.assertEqual(key in html, shown, key)
        self.assertLess(html.index("가상 E"), html.index("가상 C"))   # 승인이 많이 진행된 것부터

    def test_card_vat_is_added_to_the_book_cost_before_comparing(self):
        html = final_table([xproject("A", 9000000, 10000000, card_vat=1000000)], {"A": "대표이사"})
        self.assertIn("일치", html)
        self.assertIn("카드 부가세 1,000,000 더함 (2건", html)
        self.assertIn("100.0%", html)

    def test_difference_rows_carry_an_explanation(self):
        html = final_table([xproject("A", 12000000, 10000000), xproject("B", 6000000, 10000000, requested=9000000),
                            xproject("C", 6000000, 10000000)], {"A": "팀장", "B": "팀장", "C": "팀장"})
        self.assertIn("장부 원가가 실행가보다 2,000,000 많음", html)
        self.assertIn("지급요청 누계 9,000,000가 장부 원가보다 많음", html)
        self.assertIn("장부 원가가 실행가보다 4,000,000 적음 → 아직 안 들어온 증빙", html)

    def test_budget_between_cost_and_cost_plus_card_vat_is_explained(self):
        html = final_table([xproject("A", 9000000, 9400000, card_vat=1000000)], {"A": "대표이사"})
        self.assertIn("실행가가 장부 원가와 카드 부가세 더한 원가 사이", html)
        self.assertIn("400,000어치 부가세만", html)
        self.assertIn("나머지 600,000은 공급가액으로", html)
        self.assertNotIn("실행가에 없는 지출", html)

    def test_unknown_values_are_not_turned_into_a_difference(self):
        html = final_table([xproject("A", 5000000, None), xproject("B", 5000000, 10000000, out=True)], {"A": "팀장", "B": "팀장"})
        self.assertIn("인트라넷 실행가 빈칸", html)
        self.assertIn("분개장 기간 밖 원가", html)
        self.assertIn("합계 (두 값을 모두 아는 0건)", html)

    def test_no_approval_data_says_so(self):
        self.assertIn("승인 단계 자료 없음", final_table([xproject("A", 1, 1)], {"A": ""}))


class TestCardVendorName(unittest.TestCase):
    def test_card_company_and_last_four_digits_is_a_card(self):
        from ceo_report import convert_projects
        for name, card in (("신한_5860", True), ("롯데_1842", True), ("(주) 인하모니네트워크", False), ("신한_58601", False), ("A B_1234", False)):
            self.assertEqual(bool(convert_projects._CARD_NO.match(name)), card, name)


class TestCardVatFact(unittest.TestCase):
    def test_card_vat_row_is_written_and_read_back(self):
        projects = {"26201": {"name": "가상", "budget": 100, "dup": False}}
        costs = {"lines": [{"project": "26201", "amount": 70}]}
        rows = convert_xchk._cost_rows(projects, costs, [], None, {"26201": [7, 2]})
        got = [r for r in rows if r["항목"] == convert_xchk.CARD_VAT_ITEM]
        self.assertEqual([(r["대상"], r["금액"], r["건수"]) for r in got], [("26201", "7", "2")])
        self.assertEqual([r for r in convert_xchk._cost_rows(projects, costs, [], None, None)
                          if r["항목"] == convert_xchk.CARD_VAT_ITEM], [])


if __name__ == "__main__":
    unittest.main()
