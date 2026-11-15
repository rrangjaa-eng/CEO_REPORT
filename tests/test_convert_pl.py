"""손익.csv 팀·프로젝트 줄과 프로젝트 연결 (Phase 2, 계획 02-03).

모든 장부·스냅숏은 시험 때 임시 폴더에 가상 자료로 만든다. 실제 입력/·수집/ 폴더와 실제 WEHAGO 파일은 열지 않는다.
다른 시험 파일에서는 함수와 상수만 가져온다 (TestCase 클래스를 가져오면 시험이 두 번 돈다).
"""
import csv
import datetime as dt
import importlib
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from test_approval import write_fake_snapshot  # noqa: E402
from test_convert import (ASOF, FAKE_PL_JOURNAL, JOURNAL_MONTHS, NOW, cli_argv, convert_input, jl_sort,  # noqa: E402
                          read_result_lines, run_convert, sha, write_convert_books)
from test_convert import setUpModule  # noqa: E402,F401  (샘플을 임시 폴더에 새로 쓴다)
from test_linking import write_links_csv  # noqa: E402


def mod(name):
    return importlib.import_module("ceo_report." + name)


class Ran(object):
    """한 번의 변환: 폴더들과 convert.run 결과."""

    def __init__(self, tmp, input_dir, collect, wehago_dir, res):
        self.tmp, self.input_dir, self.collect, self.wehago_dir, self.res = tmp, input_dir, collect, wehago_dir, res
        self.code = res.code
        self.stdout = "\n".join(res.lines)

    def csv_rows(self, name="손익.csv"):
        with open(os.path.join(self.input_dir, name), encoding="utf-8-sig", newline="") as f:
            return list(csv.reader(f))

    def wehago_rows(self, months=JOURNAL_MONTHS):
        """WEHAGO 줄. months: 이 달들만 (기본: 새 분개장의 달; None 이면 모두).

        02-REVIEW CR-04 부터 샘플 이전 손익.csv 중 새 분개장 밖 달(2026-01~08, 2026-11)의 WEHAGO 줄은 남는다.
        """
        return [tuple(r) for r in self.csv_rows()[1:] if r[0] == "WEHAGO" and (months is None or r[1] in months)]

    def result_lines(self):
        return read_result_lines(self.input_dir)


def convert_with_snapshot(test, links_rows=None, snapshot=True, journal=FAKE_PL_JOURNAL, setup=None):
    """가상 장부 + (가상 스냅숏) + 샘플 입력으로 convert.run 을 한 번 돌린다 (기준일 2026-11-02).

    links_rows 를 주면 입력/프로젝트연결.csv 를 먼저 쓴다. setup(input_dir, collect, wehago_dir) 은 변환 직전에 불린다.
    """
    tmp, input_dir, collect, wehago_dir = convert_input(test)
    write_convert_books(wehago_dir, journal=journal)
    if snapshot:
        write_fake_snapshot(collect)
    if links_rows is not None:
        write_links_csv(input_dir, links_rows)
    if setup:
        setup(input_dir, collect, wehago_dir)
    res = mod("convert").run(input_dir, collect, wehago_dir, ASOF, NOW)
    return Ran(tmp, input_dir, collect, wehago_dir, res)


# ───────────── Task 1 (tracer): 스냅숏 → 연결 → 프로젝트 손익 줄 → 손익.csv → 보고서 s4 ─────────────
class TestConvertPlTracer(unittest.TestCase):
    def test_project_row_of_a_linked_revenue_and_cost_reaches_the_csv(self):
        r = convert_with_snapshot(self)
        self.assertEqual(r.code, 0, r.stdout)
        rows = r.csv_rows()
        want = "WEHAGO,2026-10,프로젝트,26203 가상 전시부스,75000000,45000000,,Y".split(",")
        self.assertIn(want, rows)

    def test_report_s4_has_the_project_row(self):
        r = convert_with_snapshot(self)
        d = mod("data").load(r.input_dir)
        self.assertEqual([it for it in d.issues.items if it[0] == "손익.csv"], [])
        R = mod("calc").compute(d, "monthly", dt.date(2026, 10, 31))
        table = R["s4"]["sources"]["WEHAGO"]["table"]
        row = [t for t in table if t["unit"] == "프로젝트" and t["target"] == "26203 가상 전시부스"]
        self.assertEqual(len(row), 1)
        self.assertEqual((row[0]["cur"]["revenue"], row[0]["cur"]["direct"]), (75000000, 45000000))
        self.assertIn("인트라넷완료보고", R["s4"]["sources"])

    def test_result_file_names_the_snapshot(self):
        r = convert_with_snapshot(self)
        self.assertIn("인트라넷 스냅숏: 인트라넷_20261101_180000 (수집 2026-11-01 18:00:00) · 지급요청 9건 · 프로젝트 4건",
                      r.result_lines())

    def test_unlinked_amount_is_not_dropped(self):
        r = convert_with_snapshot(self)
        rows = r.csv_rows()
        self.assertIn("WEHAGO,2026-10,프로젝트,프로젝트 미연결,19000000,1100000,,Y".split(","), rows)

    def test_common_cost_is_never_given_to_a_project(self):
        r = convert_with_snapshot(self)
        for row in r.wehago_rows():
            if row[2] == "프로젝트":
                self.assertEqual(row[6], "", row)


# ───────────── Task 2: 팀·프로젝트·미연결 줄, 달별 합계 대조, 연결 요약과 미연결 목록, 수동 지정 ─────────────
W = "WEHAGO"
EXPECTED_ROWS = [
    (W, "2026-09", "회사", "회사 전체", "100000000", "10000000", "2000000", "Y"),
    (W, "2026-09", "팀", "1팀", "100000000", "10000000", "", "Y"),
    (W, "2026-09", "프로젝트", "26201 가상 컨퍼런스", "100000000", "10000000", "", "Y"),
    (W, "2026-10", "회사", "회사 전체", "94000000", "249500000", "4500000", "Y"),
    (W, "2026-10", "팀", "1팀", "0", "45400000", "", "Y"),
    (W, "2026-10", "팀", "2팀", "75000000", "203000000", "", "Y"),
    (W, "2026-10", "팀", "미연결", "19000000", "1100000", "", "Y"),
    (W, "2026-10", "프로젝트", "26201 가상 컨퍼런스", "0", "40000000", "", "Y"),
    (W, "2026-10", "프로젝트", "26220 가상 전시", "0", "158000000", "", "Y"),
    (W, "2026-10", "프로젝트", "26221 가상 워크숍", "0", "5400000", "", "Y"),
    (W, "2026-10", "프로젝트", "26203 가상 전시부스", "75000000", "45000000", "", "Y"),
    (W, "2026-10", "프로젝트", "프로젝트 미연결", "19000000", "1100000", "", "Y"),
]
UNIT_CHECK = re.compile(r"^  대조 (매출|직접비) (\d{4}-\d{2}) (팀별|프로젝트별) 합계\(미연결 포함\) = 회사: .* → (일치|불일치|판단 불가)$")


def unit_check_lines(lines):
    return [ln for ln in lines if UNIT_CHECK.match(ln)]


class TestConvertPlProjects(unittest.TestCase):
    def test_full_ordered_row_list_then_the_carried_rows(self):
        r = convert_with_snapshot(self)
        self.assertEqual(r.code, 0, r.stdout)
        rows = r.csv_rows()
        self.assertEqual(r.wehago_rows(), EXPECTED_ROWS)
        # 02-REVIEW CR-04: 새 분개장(2026-09~10) 앞 달의 이전 WEHAGO 줄, 새 줄, 뒤 달(2026-11)의 이전 줄, 옮긴 줄 순서
        before = [tuple(x) for x in rows[1:] if x[0] == "WEHAGO" and x[1] < JOURNAL_MONTHS[0]]
        after = [tuple(x) for x in rows[1:] if x[0] == "WEHAGO" and x[1] > JOURNAL_MONTHS[-1]]
        self.assertEqual(sorted(set(x[1] for x in before)), ["2026-%02d" % m for m in range(1, 9)])
        self.assertEqual(set(x[1] for x in after), {"2026-11"})
        n, k = len(EXPECTED_ROWS), len(before)
        self.assertEqual([tuple(x) for x in rows[1:1 + k]], before)
        self.assertEqual([tuple(x) for x in rows[1 + k:1 + k + n]], EXPECTED_ROWS)
        self.assertEqual([tuple(x) for x in rows[1 + k + n:1 + k + n + len(after)]], after)
        carried = rows[1 + k + n + len(after):]
        self.assertEqual(len(carried), 3)
        self.assertEqual(set(x[0] for x in carried), {"인트라넷완료보고"})

    def test_units_with_unlinked_add_up_to_the_company_cell(self):
        r = convert_with_snapshot(self)
        for ym in ("2026-09", "2026-10"):
            month = [x for x in r.wehago_rows() if x[1] == ym]
            company = [x for x in month if x[2] == "회사"][0]
            for unit in ("팀", "프로젝트"):
                for col in (4, 5):
                    self.assertEqual(sum(int(x[col]) for x in month if x[2] == unit), int(company[col]),
                                     (ym, unit, col))

    def test_common_cost_is_blank_on_every_team_and_project_row(self):
        r = convert_with_snapshot(self)
        rows = [x for x in r.wehago_rows() if x[2] in ("팀", "프로젝트")]
        self.assertTrue(rows)
        self.assertEqual([x for x in rows if x[6] != ""], [])

    def test_report_s4_has_team_and_project_rows(self):
        r = convert_with_snapshot(self)
        d = mod("data").load(r.input_dir)
        self.assertEqual([it for it in d.issues.items if it[0] == "손익.csv"], [])
        table = mod("calc").compute(d, "monthly", dt.date(2026, 10, 31))["s4"]["sources"]["WEHAGO"]["table"]
        team = [t for t in table if t["unit"] == "팀" and t["target"] == "2팀"][0]
        self.assertEqual((team["cur"]["revenue"], team["cur"]["direct"]), (75000000, 203000000))
        project = [t for t in table if t["unit"] == "프로젝트" and t["target"] == "26203 가상 전시부스"][0]
        self.assertEqual((project["cur"]["revenue"], project["cur"]["direct"]), (75000000, 45000000))

    def test_a_manual_link_to_a_project_missing_from_the_list_is_shown_with_unknown_team(self):
        r = convert_with_snapshot(self, links_rows=[["2026-10-29", "22", "1", "29999"]])
        month = [x for x in r.wehago_rows() if x[1] == "2026-10"]
        self.assertIn((W, "2026-10", "프로젝트", "29999 (프로젝트 목록에 없음)", "0", "800000", "", "Y"), month)
        self.assertIn((W, "2026-10", "팀", "팀 미확인", "0", "800000", "", "Y"), month)
        targets = [x[3] for x in month if x[2] == "프로젝트"]
        self.assertEqual(targets[-2:], ["29999 (프로젝트 목록에 없음)", "프로젝트 미연결"])
        teams = [x[3] for x in month if x[2] == "팀"]
        self.assertEqual(teams[-1], "미연결")

    def test_a_project_with_a_blank_team_goes_to_team_unassigned(self):
        def setup(input_dir, collect, wehago_dir):
            sn = mod("snapshot")
            from test_approval import COLLECTED, FAKE_PAYMENTS, FAKE_PROJECTS, as_dicts
            projects = [list(p) for p in FAKE_PROJECTS]
            projects[2][7] = ""   # 26221 팀
            sn.write_snapshot(collect, COLLECTED, as_dicts(FAKE_PAYMENTS, sn.PAYMENT_COLUMNS),
                              as_dicts(projects, sn.PROJECT_COLUMNS))

        r = convert_with_snapshot(self, snapshot=False, setup=setup)
        month = [x for x in r.wehago_rows() if x[1] == "2026-10" and x[2] == "팀"]
        self.assertIn((W, "2026-10", "팀", "1팀", "0", "40000000", "", "Y"), month)
        self.assertIn((W, "2026-10", "팀", "팀 미지정", "0", "5400000", "", "Y"), month)

    def test_unknown_amount_blanks_the_project_cell_and_the_checks_cannot_judge(self):
        blank = jl_sort(dt.date(2026, 10, 5), 95, "대체", "61101", "행사외주비(도)", None, None, "가상기타",
                        "[26221] 금액 없음")
        r = convert_with_snapshot(self, journal=FAKE_PL_JOURNAL + [blank])
        self.assertEqual(r.code, 0, r.stdout)
        month = [x for x in r.wehago_rows() if x[1] == "2026-10"]
        project = [x for x in month if x[3] == "26221 가상 워크숍"][0]
        self.assertEqual(project[5], "")
        self.assertEqual(project[4], "0")
        self.assertEqual([x for x in month if x[3] == "1팀"][0][5], "")
        lines = r.result_lines()
        judged = [ln for ln in unit_check_lines(lines) if "직접비 2026-10" in ln]
        self.assertEqual(len(judged), 2)
        self.assertTrue(all(ln.endswith("→ 판단 불가") for ln in judged), judged)
        self.assertIn("대조 불일치 0건", lines)
        self.assertTrue(any(ln.startswith("대조 판단 불가 ") for ln in lines))
        revenue = [ln for ln in unit_check_lines(lines) if ln.startswith("  대조 매출")]
        self.assertTrue(all(ln.endswith("→ 일치") for ln in revenue), revenue)


class TestConvertPlLinks(unittest.TestCase):
    def test_one_ok_check_per_month_measure_and_unit(self):
        r = convert_with_snapshot(self)
        lines = r.result_lines()
        checks = unit_check_lines(lines)
        self.assertEqual(len(checks), 8)
        self.assertTrue(all(ln.endswith("→ 일치") for ln in checks), checks)
        self.assertIn("  대조 매출 2026-10 프로젝트별 합계(미연결 포함) = 회사: 원본 94,000,000 · CSV 94,000,000 → 일치", lines)
        self.assertIn("  대조 직접비 2026-09 팀별 합계(미연결 포함) = 회사: 원본 10,000,000 · CSV 10,000,000 → 일치", lines)
        self.assertIn("대조 불일치 0건", lines)

    def test_link_summary_and_the_unlinked_work_list(self):
        r = convert_with_snapshot(self)
        lines = r.result_lines()
        for want in ("  원가 줄: 수동 0건 0 · 코드 9건 258,400,000 · 자동 0건 0 · 미연결 2건 1,100,000",
                     "  매출 줄: 수동 0건 0 · 코드 1건 100,000,000 · 자동 1건 75,000,000 · 미연결 2건 19,000,000",
                     "  미연결 원가 2026-10-29 22-1 가상강사 800,000 가상 개인강사 ******-******* 강사료"
                     " — 미연결 (코드 없음 · 자동 연결 후보 0건)",
                     "  미연결 원가 2026-10-29 23-1 가상기타 300,000 [26999] 가상 기타 행사"
                     " — 미연결 (코드 26999 프로젝트 목록에 없음 · 자동 연결 후보 0건)",
                     "  미연결 매출 2026-10-28 32-2 가상고객X 20,000,000 기타 용역"
                     " — 미연결 (코드 없음 · 클라이언트·견적금액 후보 0건)",
                     "  미연결 매출 2026-10-29 38-1 가상고객X −1,000,000 매출 정정"
                     " — 미연결 (코드 없음 · 클라이언트·견적금액 후보 0건)"):
            self.assertIn(want, lines)
        listing = [i for i, ln in enumerate(lines) if ln.startswith("  미연결 ")]
        self.assertEqual(len(listing), 4)
        self.assertEqual(listing, list(range(listing[0], listing[0] + 4)))   # 원가 2줄 다음 매출 2줄
        hint = "프로젝트연결.csv에 전표일자·전표번호·줄·프로젝트번호를 적으면 다음 변환부터 그 프로젝트로 연결됩니다"
        self.assertEqual(sum(1 for ln in lines if hint in ln), 1)

    def test_stdout_line_shows_the_unlinked_totals_next_to_the_list(self):
        r = convert_with_snapshot(self)
        self.assertIn("프로젝트 연결: 원가 미연결 2건 1,100,000 · 매출 미연결 2건 19,000,000 (변환결과.txt 목록)", r.res.lines)

    def test_manual_link_moves_the_amount_and_the_manual_file_is_untouched(self):
        rows = [["2026-10-29", "22", "1", "26221"], ["2026-10-01", "99", "1", "26201"]]

        def setup(input_dir, collect, wehago_dir):
            setup.before = sha(os.path.join(input_dir, "프로젝트연결.csv"))

        r = convert_with_snapshot(self, links_rows=rows, setup=setup)
        self.assertEqual(r.code, 0, r.stdout)
        month = [x for x in r.wehago_rows() if x[1] == "2026-10"]
        self.assertIn((W, "2026-10", "프로젝트", "26221 가상 워크숍", "0", "6200000", "", "Y"), month)
        self.assertIn((W, "2026-10", "팀", "1팀", "0", "46200000", "", "Y"), month)
        self.assertIn((W, "2026-10", "프로젝트", "프로젝트 미연결", "19000000", "300000", "", "Y"), month)
        lines = r.result_lines()
        self.assertTrue(any(ln.startswith("  원가 줄: 수동 1건 800,000 · ") for ln in lines), lines)
        self.assertIn("  알림 프로젝트연결.csv 2026-10-01 99-1 → 26201: 지정한 줄 없음", lines)
        self.assertEqual(sha(os.path.join(r.input_dir, "프로젝트연결.csv")), setup.before)
        self.assertFalse(any("미연결 원가 2026-10-29 22-1" in ln for ln in lines))
        self.assertIn("  대조 직접비 2026-10 프로젝트별 합계(미연결 포함) = 회사: 원본 249,500,000 · CSV 249,500,000 → 일치", lines)

    def test_no_manual_file_is_never_created_by_the_run(self):
        r = convert_with_snapshot(self)
        self.assertFalse(os.path.exists(os.path.join(r.input_dir, "프로젝트연결.csv")))
        self.assertIn("프로젝트연결.csv", "\n".join(r.result_lines()))   # '없는 수동 파일' 줄에 이름이 나온다

    def test_run_keeps_the_link_inputs_for_the_other_builders(self):
        r = convert_with_snapshot(self)
        links = r.res.links
        for key in ("costs", "revenue", "projects", "snapshot", "requests", "overrides"):
            self.assertIn(key, links)
        self.assertTrue(links["snapshot"])
        self.assertEqual(len(links["requests"]), 9)


# ───────────── Task 3: 스냅숏이 없거나 읽을 수 없을 때 (D-38, D-45) ─────────────
RRN = re.compile(r"\d{6}\s*[-.]?\s*\d{7}")
NO_SNAPSHOT_OCT = [
    (W, "2026-10", "회사", "회사 전체", "94000000", "249500000", "4500000", "Y"),
    (W, "2026-10", "프로젝트", "26201", "0", "40000000", "", "Y"),
    (W, "2026-10", "프로젝트", "26203", "0", "45000000", "", "Y"),
    (W, "2026-10", "프로젝트", "26220", "0", "158000000", "", "Y"),
    (W, "2026-10", "프로젝트", "26221", "0", "5400000", "", "Y"),
    (W, "2026-10", "프로젝트", "26999", "0", "300000", "", "Y"),
    (W, "2026-10", "프로젝트", "프로젝트 미연결", "94000000", "800000", "", "Y"),
]


def break_snapshot_count(input_dir, collect, wehago_dir):
    """수집정보.csv 의 지급요청_건수를 10으로 바꾼다 (파일에는 9건)."""
    path = os.path.join(mod("snapshot").latest_snapshot(collect), "수집정보.csv")
    with open(path, encoding="utf-8-sig", newline="") as f:
        text = f.read()
    assert "지급요청_건수,9" in text
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(text.replace("지급요청_건수,9", "지급요청_건수,10"))


class TestConvertPlNoSnapshot(unittest.TestCase):
    def check_code_only(self, r):
        self.assertEqual(r.code, 0, r.stdout)
        rows = r.wehago_rows()
        self.assertEqual([x for x in rows if x[1] == "2026-10"], NO_SNAPSHOT_OCT)
        self.assertEqual([x for x in rows if x[2] == "팀"], [])
        self.assertEqual([x for x in rows if x[1] == "2026-09"],
                         [(W, "2026-09", "회사", "회사 전체", "100000000", "10000000", "2000000", "Y"),
                          (W, "2026-09", "프로젝트", "26201", "100000000", "10000000", "", "Y")])
        lines = r.result_lines()
        self.assertIn("  알림 팀별 손익 없음 (분개장 부서명 칸·인트라넷 스냅숏 없음)", lines)
        self.assertEqual([ln for ln in lines if "팀별 합계" in ln], [])
        self.assertEqual(len(unit_check_lines(lines)), 4)   # 프로젝트별 2달 x 2
        self.assertIn("대조 불일치 0건", lines)

    def test_empty_collect_folder_gives_code_only_project_rows_and_no_team_rows(self):
        r = convert_with_snapshot(self, snapshot=False)
        self.check_code_only(r)
        self.assertIn("인트라넷 스냅숏: 없음 — 자동 연결 안 함", r.result_lines())

    def test_unreadable_snapshot_behaves_the_same_with_the_reason(self):
        r = convert_with_snapshot(self, setup=break_snapshot_count)
        self.check_code_only(r)
        self.assertIn("인트라넷 스냅숏: 읽지 못함 — 지급요청 건수가 수집정보와 다릅니다: 수집정보 10건, 파일 9건",
                      r.result_lines())

    def test_corrupt_snapshot_files_never_stop_the_conversion(self):
        def setup(input_dir, collect, wehago_dir):
            path = os.path.join(mod("snapshot").latest_snapshot(collect), "지급요청.csv")
            with open(path, "wb") as f:
                f.write(b"\xff\xfe\x00garbage\x80\x81")

        r = convert_with_snapshot(self, setup=setup)
        self.check_code_only(r)
        self.assertTrue(any(ln.startswith("인트라넷 스냅숏: 읽지 못함 — 지급요청.csv") for ln in r.result_lines()))

    def test_unfinished_snapshot_folder_is_ignored(self):
        def setup(input_dir, collect, wehago_dir):
            os.makedirs(os.path.join(collect, "인트라넷_20261102_000000.작성중"))

        r = convert_with_snapshot(self, snapshot=False, setup=setup)
        self.check_code_only(r)
        self.assertIn("인트라넷 스냅숏: 없음 — 자동 연결 안 함", r.result_lines())

    def test_unfinished_snapshot_folder_does_not_hide_the_finished_one(self):
        def setup(input_dir, collect, wehago_dir):
            os.makedirs(os.path.join(collect, "인트라넷_20261102_000000.작성중"))

        r = convert_with_snapshot(self, setup=setup)
        self.assertTrue(any(ln.startswith("인트라넷 스냅숏: 인트라넷_20261101_180000 (수집") for ln in r.result_lines()))
        self.assertEqual(len([x for x in r.wehago_rows() if x[2] == "팀"]), 4)

    def test_a_manual_link_works_without_a_snapshot(self):
        r = convert_with_snapshot(self, snapshot=False, links_rows=[["2026-10-29", "22", "1", "26221"]])
        rows = [x for x in r.wehago_rows() if x[1] == "2026-10"]
        self.assertIn((W, "2026-10", "프로젝트", "26221", "0", "6200000", "", "Y"), rows)
        self.assertIn((W, "2026-10", "프로젝트", "프로젝트 미연결", "94000000", "0", "", "Y"), rows)

    def test_work_list_and_stdout_hide_resident_numbers(self):
        r = convert_with_snapshot(self, snapshot=False)
        text = "\n".join(r.result_lines() + r.res.lines)
        self.assertIsNone(RRN.search(text))
        self.assertIn("  미연결 원가 2026-10-29 22-1 가상강사 800,000 가상 개인강사 ******-******* 강사료 — 미연결 "
                      "(코드 없음 · 프로젝트 목록 없음)", r.result_lines())
        with open(os.path.join(r.input_dir, "손익.csv"), encoding="utf-8-sig") as f:
            self.assertIsNone(RRN.search(f.read()))

    def test_work_list_masks_a_resident_number_that_reaches_it_unmasked(self):
        raw = "가상 개인강사 123456-1234567 강사료"
        converted = mod("convert")._text_bytes(["  미연결 원가 2026-10-29 22-1 가상강사 800,000 " + raw]).decode("utf-8")
        self.assertIsNone(RRN.search(converted))
        self.assertIn("******-*******", converted)

    def test_command_line_prints_no_resident_number_either(self):
        tmp, input_dir, collect, wehago_dir = convert_input(self)
        write_convert_books(wehago_dir)
        rc, out = run_convert(cli_argv(input_dir, collect, wehago_dir))
        self.assertEqual(rc, 0, out)
        self.assertIsNone(RRN.search(out))
        self.assertIn("프로젝트 연결: 원가 미연결 1건 800,000 · 매출 미연결 3건 94,000,000 (변환결과.txt 목록)", out)


if __name__ == "__main__":
    unittest.main()
