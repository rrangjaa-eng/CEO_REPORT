"""보고 규칙 테스트. 실행: python -m unittest discover -s tests"""
import contextlib
import csv
import datetime as dt
import importlib.util
import io
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import render  # noqa: E402
from ceo_report.util import num, date, read_csv, Issues, is_blank, setting_num, pct  # noqa: E402

from sample_input import SAMPLE, refresh as refresh_sample  # noqa: E402

ASOF = dt.date(2026, 11, 2)
FORBIDDEN = ("위험", "해결방안", "권고", "우려", "추천")


def numbers_of(html):
    """HTML 속 숫자 나열. 위험 분석 묶음, 월간 8번 상세 묶음(경영관리용에만 있음)과 작성 시각은 뺀다.

    대표 보고는 요약 화면만 싣는다 (문서 1~2쪽, 사용자 2026-11-03). 그래서 상세 목차부터 끝까지(경영관리용에만 있음)도 뺀다."""
    html = html.split("<div class='toc'>")[0]
    html = re.sub(r"<h2 id='risk'>.*?</table>", "", html, flags=re.S)
    html = re.sub(r"<div id='xchk-detail'>.*?<!-- /xchk-detail -->", "", html, flags=re.S)
    html = re.sub(r"<div class='note' style='margin-top:10px'>위험 항목.*?</div>", "", html, flags=re.S)
    html = re.sub(r"작성 \d{4}-\d{2}-\d{2} \d{2}:\d{2}", "", html)
    html = re.sub(r"<table class='sign'>.*?</table>", "", html, flags=re.S)   # 결재란은 대표용 주간에만
    html = re.sub(r"<div class='mgonly'>.*?<!-- /mgonly -->", "", html, flags=re.S)   # 근거 묶음은 경영관리용에만 (2026-11-03)
    return re.findall(r"−?\d[\d,.]*", html)


def edit_csv(folder, filename, mutate):
    """폴더 안의 CSV 한 개를 읽어 mutate(rows)로 고쳐 다시 쓴다."""
    path = os.path.join(folder, filename)
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    mutate(rows)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)


def probe_folder(test, filename, mutate):
    """샘플 입력을 임시 폴더에 복사하고 CSV 한 개를 고쳐 쓴다. 고친 폴더 경로를 돌려준다."""
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp)
    folder = os.path.join(tmp, "입력")
    shutil.copytree(SAMPLE, folder)
    edit_csv(folder, filename, mutate)
    return folder


def first_screen(html):
    return html.split("<div class='toc'>")[0]


def section(html, n):
    """상세자료 n번 묶음 HTML (7번은 문서 끝까지)."""
    start = html.index("<h2 id='s%d'>" % n)
    nxt = "<h2 id='s%d'>" % (n + 1)
    end = html.index(nxt, start) if nxt in html[start:] else len(html)
    return html[start:end]


def setUpModule():
    refresh_sample()  # 샘플은 임시 폴더에 쓴다 (실제 입력 폴더를 건드리지 않음)


def box_items(html):
    """첫 화면 '위 숫자에 안 들어간 것 · 확인할 것' 상자의 줄 글자들."""
    part = html.split("<div class='xbox'>")[1].split("</div>")[0]
    return re.findall(r"<li>(.*?)</li>", part, re.S)


def box_item(html, prefix):
    """상자에서 prefix 로 시작하는 줄. 없으면 None."""
    return next((t for t in box_items(html) if t.startswith(prefix)), None)


def avail_rows(html):
    """첫 화면 기간별 가용자금 표(예상분 포함 기준, 가용자금 칸 아래 확정분만)의 줄마다 칸 HTML 목록."""
    body = html.split("<table class='pt' id='avail'>")[1].split("<tbody>")[1].split("</tbody>")[0]
    return [re.findall(r"<td[^>]*>(.*?)</td>", r, re.S) for r in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S)]


def firm_avail(cell):
    """가용자금 칸 아래 '확정분만 …' 글자."""
    return re.search(r"<small class='firm[^']*'>(.*?)</small>", cell).group(1)


def project_block(html, pid):
    """첫 화면 프로젝트 예산 막대 한 줄 HTML."""
    return re.search(r"<div class='prow' id='pj-%s'>.*?</div></div>(?=<div class='prow|<div class='ptot')" % re.escape(pid),
                     first_screen(html), re.S).group(0)


def kv_value(html, label):
    """render.kv()가 쓰는 '이름 / 값' 줄에서 값 부분만 꺼낸다. 없으면 None."""
    m = re.search('<div class="kv"><span>' + re.escape(label) + '</span><span>(.*?)</span></div>', html, re.S)
    return m.group(1) if m else None


_CLI = None


def load_cli():
    """보고서.py는 이름이 한글이라 import 할 수 없다. 경로로 읽어 한 번만 만든다."""
    global _CLI
    if _CLI is None:
        spec = importlib.util.spec_from_file_location("report_cli", os.path.join(ROOT, "보고서.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.PDF_WAIT = 0.5  # 시험: PDF 가 안 생기는 경우를 오래 기다리지 않게
        _CLI = mod
    return _CLI


def check_editions(test, R):
    """두 판을 만들어 대표용 규칙을 확인한다: 금지어 없음, 숫자 동일, 보고 대조 전부 일치."""
    ceo, mgmt = render(R, "ceo"), render(R, "mgmt")
    for word in FORBIDDEN:
        test.assertNotIn(word, ceo, word)
    test.assertEqual(numbers_of(ceo), numbers_of(mgmt))
    for c in R["s7"]["checks"]:
        test.assertTrue(c[3], c[0])


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = load(SAMPLE)
        cls.R = compute(cls.d, "weekly", ASOF)


class TestParsing(unittest.TestCase):
    def test_blank_is_unknown_not_zero(self):
        self.assertIsNone(num(""))
        self.assertIsNone(num("미확인"))
        self.assertEqual(num("0"), 0)
        self.assertEqual(num("1,234,000"), 1234000)
        self.assertEqual(num("(500)"), -500)

    def test_dates(self):
        self.assertEqual(date("2026.11.02"), ASOF)
        self.assertEqual(date("20261102"), ASOF)
        self.assertEqual(date("2026/11/2"), ASOF)
        self.assertIsNone(date(""))

    def test_cp949_csv(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        p = os.path.join(tmp, "a.csv")
        with open(p, "w", encoding="cp949") as f:
            f.write("항목,값\n회사명,한글회사\n")
        rows, ok = read_csv(p, ["항목", "값"], Issues())
        self.assertTrue(ok)
        self.assertEqual(rows[0]["값"], "한글회사")

    def test_setting_num(self):
        self.assertTrue(is_blank(""))
        self.assertTrue(is_blank(" - "))
        self.assertTrue(is_blank("미확인"))
        self.assertFalse(is_blank("0"))
        self.assertEqual(setting_num({"a": "50,000,000"}, "a", 0), (50_000_000, None))
        self.assertEqual(setting_num({"a": "110.5"}, "a", 0), (110.5, None))
        self.assertEqual(setting_num({"a": "100%"}, "a", 0), (100, None))
        self.assertEqual(setting_num({"a": " 7 "}, "a", 0), (7, None))
        self.assertEqual(setting_num({"a": ""}, "a", 9), (9, "설정 비어 있음"))
        self.assertEqual(setting_num({}, "a", 9), (9, "설정 비어 있음"))
        self.assertEqual(setting_num({"a": "abc"}, "a", 9), (9, "숫자 아님"))
        self.assertIsNone(num(""))

    def test_bad_number_is_reported(self):
        iss = Issues()
        self.assertIsNone(num("12a", iss, {"_file": "x.csv", "_line": 3}, "금액"))
        self.assertEqual(len(iss.items), 1)


class TestCash(Base):
    def test_transfer_excluded_from_company_totals(self):
        s1 = self.R["s1"]
        self.assertEqual(s1["transfer_in"], 20_000_000)
        self.assertNotIn("계좌간이체", s1["by_cat"])
        self.assertEqual(s1["in"], 55_000_000)
        self.assertEqual(s1["out"], 40_600_000)

    def test_available_excludes_restricted(self):
        s1 = self.R["s1"]
        self.assertEqual(s1["available"], s1["total"] - 30_000_000)

    def test_start_balance_matches_bank(self):
        self.assertEqual(self.R["s1"]["start_bank"], self.R["s1"]["start_calc"])


class TestSchedule(Base):
    def test_undated_not_in_buckets(self):
        s2 = self.R["s2"]
        self.assertEqual(s2["undated_out"], 15_000_000 + 2_000_000 + 77_000_000 + 11_000_000)
        self.assertEqual(s2["undated_in"], 30_000_000)  # 검토 3: P26204 D사 취소 −11,000,000이 수정 8,800,000 미수를 상계

    def test_overdue_receivable_not_forecast(self):
        dated = [e for e in self.R["events"] if e["date"] and e["date"] > ASOF]
        self.assertFalse(any(e["project"] == "P26202" for e in dated))
        self.assertEqual(self.R["s5"]["overdue_total"], 110_000_000)

    def test_card_unpaid_not_added_to_schedule(self):
        self.assertFalse(any("카드" in e["cat"] and e["source"] == "프로젝트집행" for e in self.R["events"]))

    def test_unconfirmed_receipt_is_estimate(self):
        g = [e for e in self.R["events"] if e["project"] == "P26207" and e["io"] == "in"]
        self.assertTrue(g and not g[0]["firm"])

    def test_buckets_4_weeks_then_months_to_6(self):
        b = self.R["s2"]["buckets"]
        self.assertEqual([x["type"] for x in b[:4]], ["week"] * 4)
        self.assertEqual(b[-1]["to"], dt.date(2027, 5, 31))

    def test_min_balance_reported(self):
        low, day = self.R["s2"]["min"]["firm"]
        self.assertIsNotNone(day)
        self.assertLessEqual(low, self.R["s2"]["start"])


class TestProjects(Base):
    def P(self, pid):
        return next(p for p in self.R["s3"]["projects"] if p["id"] == pid)

    def test_no_budget_is_undeterminable(self):
        p = self.P("P26204")
        self.assertIsNone(p["budget"])
        self.assertIsNone(p["remain"])

    def test_unknown_cost_blocks_profit(self):
        p = self.P("P26206")
        self.assertEqual(p["unknown_cost"], 1)
        self.assertIsNone(p["profit_end"])

    def test_supply_vs_cash(self):
        p = self.P("P26201")
        self.assertEqual(p["paid"], 70_000_000)
        self.assertEqual(p["paid_cash"], 77_000_000)
        self.assertEqual(p["paid_period"], 10_000_000)

    def test_remaining_budget_turned_into_payment(self):
        # D-54 (2026-11-03 사용자 결정, D-06 뒤집음): 남은 예산은 지급 예정. 2027-01-20 행사 → 2027-02-26, 부가세 10% 더함
        # 2026-11-03 사용자 결정: 다음 금요일부터 그날까지 매주 금요일로 나눠 잡는다
        p = self.P("P26208")
        self.assertEqual(p["remain"], round(20_000_000 * 0.70) - 350_000)
        ev = [e for e in self.R["events"] if e["project"] == "P26208"]
        self.assertTrue(all(e["source"] == "남은 예산" and e["date"].weekday() == 4 for e in ev))
        self.assertEqual((ev[0]["date"], ev[-1]["date"], len(ev)), (dt.date(2026, 11, 6), dt.date(2027, 2, 26), 17))
        self.assertEqual(sum(e["amount"] for e in ev), 15_015_000)

    def test_unlinked_exec(self):
        self.assertEqual(self.R["s3"]["unlinked_total"], 300_000)


class TestReceivables(Base):
    def test_unissued_days_only_with_done_date(self):
        by = {x["P"]["id"]: x for x in self.R["s5"]["by_project"]}
        self.assertEqual(by["P26205"]["unissued_days"], (ASOF - dt.date(2026, 9, 20)).days)
        self.assertIsNone(by["P26201"]["unissued_days"])

    def test_cancel_reduces_issued(self):
        by = {x["P"]["id"]: x for x in self.R["s5"]["by_project"]}
        self.assertEqual(by["P26204"]["issued"], 8_000_000)
        self.assertEqual(by["P26204"]["unissued"], 42_000_000)


class TestChecksAndOutput(Base):
    def test_all_reconciliations_match(self):
        for c in self.R["s7"]["checks"]:
            self.assertTrue(c[3], c[0])

    def test_scope_shows_shown_and_total(self):
        html = render(self.R, "mgmt")
        self.assertIn("표시 6건 / 전체 8건", html)

    def test_ceo_has_no_interpretation(self):
        html = render(self.R, "ceo")
        for word in FORBIDDEN:
            self.assertNotIn(word, html, word)

    def test_same_numbers_in_both_versions(self):
        self.assertEqual(numbers_of(render(self.R, "mgmt")), numbers_of(render(self.R, "mgmt")))

    def test_mgmt_has_risks(self):
        self.assertIn("위험 분석·해결방안", render(self.R, "mgmt"))
        self.assertTrue(any(r["level"] == "높음" for r in self.R["risks"]))

    def test_monthly_period(self):
        R = compute(self.d, "monthly", dt.date(2026, 10, 31))
        self.assertEqual(R["period"], (dt.date(2026, 10, 1), dt.date(2026, 10, 31)))

    def test_missing_file_reported_not_crash(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy(os.path.join(SAMPLE, "프로젝트.csv"), tmp)
        d = load(tmp)
        R = compute(d, "weekly", ASOF)
        render(R, "mgmt")
        self.assertTrue(any("파일 없음" in m for _, _, m in R["s7"]["issues"]))

    def test_cli_writes_files(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "보고서.py"), "주간", "--기준일", "2026-11-02",
                            "--입력", SAMPLE, "--출력", out, "--pdf", "안함"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(os.listdir(out)),
                         ["2026-11-02_주간_경영관리보고.html", "2026-11-02_주간_대표보고.html", "지급예정기록"])


class TestUnknownBalance(unittest.TestCase):
    """잔액 빈칸 계좌는 합계에서 빼고, 그 사실을 합계가 쓰이는 모든 곳에 보인다 (R1, D-02)."""
    NOTE = "잔액 미확인 1계좌 (합계 제외)"

    def blank_balance(self, account):
        def mutate(rows):
            for r in rows[1:]:
                if r[0] == "2026-11-02" and r[1] == account:
                    r[3] = ""
        return probe_folder(self, "계좌잔액.csv", mutate)

    def run_probe(self, account):
        R = compute(load(self.blank_balance(account)), "weekly", ASOF)
        return R, render(R, "mgmt")

    def test_blank_balance_excluded_and_shown(self):
        R, html = self.run_probe("운영계좌")
        s1 = R["s1"]
        self.assertEqual(s1["total"], 212_300_000)
        self.assertEqual(s1["bal_unknown"], 1)
        self.assertEqual(s1["bal_unknown_names"], ["운영계좌"])
        self.assertEqual(s1["available"], 182_300_000)
        self.assertEqual(R["s2"]["start_unknown"], 1)
        self.assertGreaterEqual(first_screen(html).count(self.NOTE), 3)
        self.assertIn(self.NOTE, section(html, 1))
        self.assertIn(self.NOTE, section(html, 2))

    def test_blank_balance_listed_in_input_issues(self):
        R, _ = self.run_probe("운영계좌")
        self.assertTrue(any(f == "계좌잔액.csv" and "잔액 미확인" in m and "운영계좌" in m
                            for f, _, m in R["s7"]["issues"]), R["s7"]["issues"])

    def test_blank_balance_no_false_reconciliation_mismatch(self):
        R, _ = self.run_probe("운영계좌")
        checks = R["s7"]["checks"]
        for c in checks:
            self.assertTrue(c[3], c[0])
        start = [c for c in checks if c[0].startswith("기간 시작 잔액")]
        self.assertEqual(len(start), 1)
        self.assertEqual((start[0][1], start[0][2]), (156_000_000, 156_000_000))
        tr = [c for c in checks if "계좌 간 이체" in c[0]][0]
        self.assertEqual((tr[1], tr[2]), (20_000_000, 20_000_000))

    def test_unknown_balance_known_restriction_still_subtracted(self):
        R, html = self.run_probe("프로젝트계좌")
        s1 = R["s1"]
        self.assertEqual(s1["total"], 386_100_000)
        self.assertEqual(s1["restricted"], 30_000_000)
        self.assertEqual(s1["restr_unknown"], 1)
        self.assertEqual(s1["available"], 356_100_000)
        self.assertEqual(s1["available"], s1["total"] - s1["restricted"])
        self.assertEqual(s1["bal_unknown_restricted"], 30_000_000)
        self.assertEqual(R["s2"]["start"], 356_100_000)
        self.assertIn("사용제한 30,000,000 (확인 안 됨 1계좌) · 은행 기준일", first_screen(html))   # 빈칸을 0으로 단정하지 않음 (A6)
        self.assertIn("사용제한금액 빈칸 1계좌", first_screen(html))   # 0으로 계산, 경영관리용에 경고 (사용자 2026-11-04)
        self.assertIn(self.NOTE, first_screen(html))
        self.assertTrue(box_item(first_screen(html), "사용제한금액 빈칸").startswith("사용제한금액 빈칸 1계좌 (0으로 계산"))
        self.assertIn("사용제한 30,000,000원은 사용 가능액에서 차감", section(html, 1))
        for c in R["s7"]["checks"]:
            self.assertTrue(c[3], c[0])
        start = [c for c in R["s7"]["checks"] if c[0].startswith("기간 시작 잔액")][0]
        self.assertEqual((start[1], start[2]), (408_000_000, 408_000_000))

    def test_cli_end_to_end_shows_unknown_balance(self):
        folder = self.blank_balance("운영계좌")
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "보고서.py"), "주간", "--기준일", "2026-11-02",
                            "--입력", folder, "--출력", out, "--pdf", "안함"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(out, "2026-11-02_주간_대표보고.html"), encoding="utf-8") as f:
            self.assertIn(self.NOTE, f.read())


class TestUnknownAmountsAndPastDue(Base):
    """미확인 금액은 0이 아니다 (R2), 예정일 지난 미처리는 첫 화면에 (R3), 부가세 미확인 표시 (D-07)."""
    PAST_ROW = ["2026-10-30", "지급", "5,000,000", "확정", "거래처미지급", "", "인쇄소", "청구서", "기한 경과"]
    BLANK_PAST_ROW = ["2026-10-31", "지급", "", "확정", "거래처미지급", "", "현수막", "청구서", "금액 미정"]

    def add_schedule_rows(self, *new_rows):
        return probe_folder(self, "자금일정.csv", lambda rows: rows.extend([list(r) for r in new_rows]))

    def probe(self, folder):
        R = compute(load(folder), "weekly", ASOF)
        return R, render(R, "mgmt")

    def vendor_row(self, html, name):
        m = re.search(r"<tr[^>]*><td>" + re.escape(name) + r"</td>.*?</tr>", section(html, 6), re.S)
        self.assertIsNotNone(m, name)
        return m.group(0)

    def test_vendor_unknown_amount_not_zero(self):
        v = dict(self.R["s6"]["vendors"])["진행팀"]
        self.assertIsNone(v["total"])
        self.assertEqual((v["unknown"], v["n"]), (1, 1))
        row = self.vendor_row(render(self.R, "mgmt"), "진행팀")
        self.assertIn("미확인 1건", row)
        self.assertNotIn('<td class="n">0</td>', row)

    def test_vendor_partial_unknown_counted(self):
        R, html = self.probe(self.add_schedule_rows(
            ["2026-11-20", "지급", "", "추정", "거래처미지급", "", "디자인스튜디오", "청구서", "추가 청구 금액 미정"]))
        v = dict(R["s6"]["vendors"])["디자인스튜디오"]
        self.assertEqual((v["total"], v["unknown"], v["n"]), (3_300_000, 1, 2))
        row = self.vendor_row(html, "디자인스튜디오")
        self.assertIn("3,300,000", row)
        self.assertIn("미확인 1건", row)

    def test_nonproject_payments_not_double_counted(self):
        s6 = self.R["s6"]
        self.assertEqual(s6["total"], 584_100_000)
        vendors = dict(s6["vendors"])
        self.assertEqual((vendors["사운드랩"]["total"], vendors["사운드랩"]["n"]), (44_000_000, 1))
        in_cats = set(s["vendor"] for g in s6["by_cat"].values() for s in g["rows"])
        for name in ("사운드랩", "전시제작사", "공연장"):
            self.assertNotIn(name, in_cats)
        self.assertNotIn("법인카드 5860", vendors)

    def test_past_due_on_first_screen(self):
        s2 = self.R["s2"]
        self.assertEqual((s2["past_in"], s2["past_in_n"], s2["past_in_unknown"]), (110_000_000, 1, 0))
        self.assertEqual((s2["past_out"], s2["past_out_n"], s2["past_out_unknown"]), (0, 0, 0))
        fs = first_screen(render(self.R, "mgmt"))
        self.assertEqual(box_item(fs, "예정일 지난 미처리"), "예정일 지난 미처리 입금 1건 110,000,000 / 지급 0건 0 (일정에 넣지 않음)")

    def test_past_due_payment_not_in_schedule(self):
        R, html = self.probe(self.add_schedule_rows(self.PAST_ROW))
        s2 = R["s2"]
        self.assertEqual((s2["past_out"], s2["past_out_n"], s2["past_out_unknown"]), (5_000_000, 1, 0))
        self.assertEqual([b["out_firm"] for b in s2["buckets"]], [b["out_firm"] for b in self.R["s2"]["buckets"]])
        self.assertEqual(s2["min"], self.R["s2"]["min"])
        for c in R["s7"]["checks"]:
            self.assertTrue(c[3], c[0])
        self.assertIn("/ 지급 1건 5,000,000 (일정에", first_screen(html))

    def test_nonproject_scope_and_undated_on_first_screen(self):
        s6 = self.R["s6"]
        self.assertEqual((s6["undated_n"], s6["unknown_n"]), (2, 0))
        fs = first_screen(render(self.R, "mgmt"))
        self.assertEqual(box_item(fs, "프로젝트 밖 지급 예정"), "프로젝트 밖 지급 예정 (등록분 전체) 584,100,000 · 날짜 없음 2건")

    def test_past_due_unknown_amount_counted_not_zero(self):
        label = "예정일 지난 미처리"
        with self.subTest("A: known + blank"):
            R, html = self.probe(self.add_schedule_rows(self.PAST_ROW, self.BLANK_PAST_ROW))
            s2 = R["s2"]
            self.assertEqual((s2["past_out"], s2["past_out_n"], s2["past_out_unknown"]), (5_000_000, 2, 1))
            self.assertEqual((s2["past_in"], s2["past_in_n"], s2["past_in_unknown"]), (110_000_000, 1, 0))
            val = box_item(first_screen(html), label)
            self.assertIn("입금 1건 110,000,000 / 지급 2건 5,000,000 (금액 미확인 1건)", val)
            self.assertIn("금액 미확인 1건", val)
            self.assertEqual([b["out_firm"] for b in s2["buckets"]], [b["out_firm"] for b in self.R["s2"]["buckets"]])
            self.assertEqual(s2["min"], self.R["s2"]["min"])
            for c in R["s7"]["checks"]:
                self.assertTrue(c[3], c[0])
        with self.subTest("B: only blank"):
            R, html = self.probe(self.add_schedule_rows(self.BLANK_PAST_ROW))
            s2 = R["s2"]
            self.assertIsNone(s2["past_out"])
            self.assertEqual((s2["past_out_n"], s2["past_out_unknown"]), (1, 1))
            val = box_item(first_screen(html), label)
            self.assertIn("지급 1건 금액 미확인", val)
            self.assertNotIn("1건 0 ", val)

    def test_blank_vat_on_scheduled_outflow_marked(self):
        def mutate(rows):
            for r in rows[1:]:
                if r[2] == "사운드랩":
                    r[5] = ""
        R, html = self.probe(probe_folder(self, "프로젝트집행.csv", mutate))
        s2 = R["s2"]
        self.assertEqual((s2["vat_unknown_n"], s2["vat_unknown_n4"], s2["vat_unknown_firm_n"]), (1, 1, 1))
        self.assertEqual(s2["out4_firm"], 170_100_000)
        self.assertEqual(s2["min"]["firm"], (23_800_000, dt.date(2027, 4, 25)))
        self.assertEqual(s2["min"]["all"], (126_685_000, dt.date(2027, 4, 25)))  # D-54 + 원천세 장부 계산 차액 2,900,000 (A5)
        fs = first_screen(html)
        self.assertIn("부가세 미확인 1건 (공급가액만 반영)", fs)  # 가용자금 표 아래
        self.assertEqual(box_item(fs, "부가세 미확인"), "부가세 미확인 지급 예정 1건 (공급가액만 반영)")
        s2h = section(html, 2)
        self.assertIn("부가세 미확인 1건은 공급가액만 반영", s2h)
        for lab in ("기간 중 최저 계산 잔액 · 확정 일정만", "기간 중 최저 계산 잔액 · 확정+추정"):
            self.assertIn("부가세 미확인 1건", kv_value(s2h, lab), lab)
        row = re.search(r"<tr[^>]*><td>2026-11-13</td><td>지급</td>.*?</tr>", s2h, re.S).group(0)
        self.assertIn("40,000,000", row)
        self.assertIn("부가세 미확인", row)
        vrow = self.vendor_row(html, "사운드랩")
        self.assertIn("40,000,000", vrow)
        self.assertIn("부가세 미확인 1건", vrow)
        for c in R["s7"]["checks"]:
            self.assertTrue(c[3], c[0])
        self.assertEqual(self.R["s2"]["vat_unknown_n"], 0)
        self.assertNotIn("부가세 미확인", first_screen(render(self.R, "mgmt")))


def _risk_part(html):
    """경영관리용 위험 분석 묶음 (제목부터 1번 상세자료 앞까지)."""
    return html[html.index("<h2 id='risk'>"):html.index("<h2 id='s1'>")]


class TestSettingsAndKpi(Base):
    """설정.csv 숫자는 쉼표·% 를 받고, 비거나 틀리면 기본값을 쓰되 숨기지 않는다 (R4, DR1)."""

    def set_value(self, key, value):
        def mutate(rows):
            for r in rows[1:]:
                if r[0] == key:
                    r[1] = value
        return probe_folder(self, "설정.csv", mutate)

    def delete_row(self, key):
        def mutate(rows):
            rows[:] = [r for i, r in enumerate(rows) if i == 0 or r[0] != key]
        return probe_folder(self, "설정.csv", mutate)

    def test_settings_with_commas_do_not_crash(self):
        def mutate(rows):
            for r in rows[1:]:
                if r[0] == "위험_최소보유현금":
                    r[1] = "50,000,000"
                if r[0] == "위험_예산초과율":
                    r[1] = "abc"
        R = compute(load(probe_folder(self, "설정.csv", mutate)), "weekly", ASOF)
        mgmt = render(R, "mgmt")
        render(R, "mgmt")
        self.assertEqual(R["settings_num"]["위험_최소보유현금"], 50_000_000)
        self.assertEqual(R["settings_num"]["위험_예산초과율"], 100)
        self.assertEqual(R["settings_default"], {"위험_예산초과율": "숫자 아님"})
        issues = R["s7"]["issues"]
        self.assertIn(("설정.csv", 8, "예산 초과율 기준 값이 숫자가 아님: 'abc' → 기본값 100 사용"), issues)
        for _, _, m in issues:
            self.assertNotIn("위험", m)
        risk = _risk_part(mgmt)
        self.assertIn("최소 보유현금 50,000,000원", risk)
        self.assertIn("예산 초과율 100% · 기본값 사용(숫자 아님)", risk)
        check_editions(self, R)

    def test_blank_threshold_uses_default_visibly(self):
        cases = (("blank", lambda: self.set_value("위험_최소보유현금", ""), 4),
                 ("row deleted", lambda: self.delete_row("위험_최소보유현금"), "-"))
        for name, make, line in cases:
            with self.subTest(name):
                R = compute(load(make()), "weekly", ASOF)
                self.assertEqual(R["settings_num"]["위험_최소보유현금"], 50_000_000)
                self.assertEqual(R["settings_default"], {"위험_최소보유현금": "설정 비어 있음"})
                self.assertIn(("설정.csv", line, "최소 보유현금 설정 비어 있음 → 기본값 50,000,000 사용"),
                              R["s7"]["issues"])
                self.assertIn("최소 보유현금 50,000,000원 · 기본값 사용(설정 비어 있음)",
                              _risk_part(render(R, "mgmt")))
                self.assertIn("최소 보유현금 설정 비어 있음", section(render(R, "mgmt"), 7))
                check_editions(self, R)

    def test_project_show_count_setting(self):
        R = compute(load(self.set_value("첫화면_프로젝트_표시수", "4")), "weekly", ASOF)
        self.assertIn("표시 4건 / 전체 8건", render(R, "mgmt"))
        R = compute(load(self.set_value("첫화면_프로젝트_표시수", "-1")), "weekly", ASOF)
        self.assertIn("표시 6건 / 전체 8건 (지급 진행 중, 행사일 순)", render(R, "mgmt"))   # 주간은 지급 진행 중인 6건이 전부
        self.assertEqual(R["settings_default"]["첫화면_프로젝트_표시수"], "0 이상 정수 아님")
        self.assertTrue(any("첫화면_프로젝트_표시수 값은 0 이상 정수여야 함" in m for _, _, m in R["s7"]["issues"]))

    def test_amounts_in_won_not_million(self):
        # 사용자 2026-11-03: 금액 단위는 백만원이 아니라 원 (첫 화면·그래프 포함)
        html = render(self.R, "mgmt")
        self.assertNotIn("백만원", html)
        self.assertIn("금액 단위: 원", html)
        self.assertIn("{:,}".format(self.R["s1"]["available"]), first_screen(html))


def rep02_probes(test):
    """REP-02 탐침 입력 목록: (이름, 만드는 함수 -> (입력 폴더, 종류, 기준일)). 월간 8번 시험도 같은 목록을 쓴다."""
    def blank_balance(account):
        def mutate(rows):
            for r in rows[1:]:
                if r[0] == "2026-11-02" and r[1] == account:
                    r[3] = ""
        return probe_folder(test, "계좌잔액.csv", mutate)

    def setting(edit):
        def mutate(rows):
            for r in rows[1:]:
                if r[0] in edit:
                    r[1] = edit[r[0]]
        return probe_folder(test, "설정.csv", mutate)

    def blank_vat(rows):
        for r in rows[1:]:
            if r[2] == "사운드랩":
                r[5] = ""
    extra = [["2026-11-20", "지급", "", "추정", "거래처미지급", "", "디자인스튜디오", "청구서", "추가 청구 금액 미정"],
             ["2026-10-30", "지급", "5,000,000", "확정", "거래처미지급", "", "인쇄소", "청구서", "기한 경과"],
             ["2026-10-31", "지급", "", "확정", "거래처미지급", "", "현수막", "청구서", "금액 미정"]]
    return (
        ("sample weekly", lambda: (SAMPLE, "weekly", ASOF)),
        ("sample monthly", lambda: (SAMPLE, "monthly", dt.date(2026, 10, 31))),
        ("blank 운영계좌", lambda: (blank_balance("운영계좌"), "weekly", ASOF)),
        ("blank 프로젝트계좌", lambda: (blank_balance("프로젝트계좌"), "weekly", ASOF)),
        ("unknown and past-due rows", lambda: (
            probe_folder(test, "자금일정.csv", lambda rows: rows.extend(extra)), "weekly", ASOF)),
        ("blank 사운드랩 부가세", lambda: (probe_folder(test, "프로젝트집행.csv", blank_vat), "weekly", ASOF)),
        ("settings commas and abc", lambda: (
            setting({"위험_최소보유현금": "50,000,000", "위험_예산초과율": "abc"}), "weekly", ASOF)),
        ("blank threshold", lambda: (setting({"위험_최소보유현금": ""}), "weekly", ASOF)),
    )


class TestCeoRulesEverywhere(unittest.TestCase):
    """대표용 규칙(금지어 없음·숫자 동일·대조 일치)을 샘플과 이 계획의 모든 탐침 입력에서 확인한다 (REP-02)."""

    def test_no_interpretation_and_same_numbers_across_inputs(self):
        for name, make in rep02_probes(self):
            with self.subTest(name):
                folder, kind, asof = make()
                check_editions(self, compute(load(folder), kind, asof))


class TestProjectBudget(Base):
    """원가 예산 = 사전견적 x 원가율 (D-16). 예산이 없으면 이유가 보이고 첫 화면에 건수가 나온다 (PROJ-01, PROJ-03)."""

    def P(self, R, pid):
        return next(p for p in R["s3"]["projects"] if p["id"] == pid)

    def edit_projects(self, edits):
        """edits: {프로젝트번호: 사전견적예산 새 값}. 샘플을 임시 폴더에 복사해 계산한 결과 R."""
        def mutate(rows):
            for r in rows[1:]:
                if r[0] in edits:
                    r[5] = edits[r[0]]
        return compute(load(probe_folder(self, "프로젝트.csv", mutate)), "weekly", ASOF)

    def set_rate(self, value):
        """value가 None이면 예산_원가율 행을 지운다. 행이 없으면 실패한다 (make_sample에 행이 있어야 함)."""
        def mutate(rows):
            idx = [i for i, r in enumerate(rows) if r and r[0] == "예산_원가율"]
            assert idx, "설정.csv에 예산_원가율 행이 없음"
            if value is None:
                del rows[idx[0]]
            else:
                rows[idx[0]][1] = value
        return compute(load(probe_folder(self, "설정.csv", mutate)), "weekly", ASOF)

    def row(self, html_part, pid):
        rows = re.findall(r"<tr[^>]*><td>" + pid + r"</td>.*?</tr>", html_part, re.S)
        self.assertTrue(rows, pid)
        return rows

    def test_budget_is_estimate_times_cost_rate(self):
        s3 = self.R["s3"]
        self.assertEqual(s3["cost_rate"], 0.7)
        p = self.P(self.R, "P26201")
        self.assertEqual(p["estimate"], 300_000_000)
        self.assertEqual(p["budget"], round(300_000_000 * 0.70))
        self.assertEqual(p["budget"], 210_000_000)
        self.assertIsNone(p["budget_reason"])
        self.assertEqual(p["remain"], -28_200_000)
        self.assertEqual(pct(p["paid_total"], p["budget"]), "33.3%")
        q = self.P(self.R, "P26204")
        self.assertIsNone(q["estimate"])
        self.assertIsNone(q["budget"])
        self.assertEqual(q["budget_reason"], "사전견적 없음")
        self.assertEqual(s3["total"]["budget"], 465_500_000)
        self.assertEqual(s3["total"]["budget_missing"], 1)
        fs = first_screen(render(self.R, "mgmt"))
        self.assertIn("원가 예산 = 사전견적 × 원가율 70%", fs)
        self.assertIn("표시 6건 / 전체 8건", fs)

    def test_no_budget_reason_blank_estimate(self):
        self.assertEqual(dict(self.R["s3"]["no_budget_reasons"]), {"사전견적 없음": 1})
        html = render(self.R, "mgmt")
        self.assertIn("예산 미책정 1건 (사전견적 없음 1건)", first_screen(html))
        r3 = self.row(section(html, 3), "P26204")[0]
        for needle in ("예산 미지정", "판단 불가", "사전견적 없음"):
            self.assertIn(needle, r3)
        self.assertIn("사전견적 없음", self.row(section(html, 7), "P26204")[-1])

    def test_no_budget_reason_zero_or_negative(self):
        R = self.edit_projects({"P26208": "0", "P26207": "-5,000,000"})
        for pid in ("P26208", "P26207"):
            P = self.P(R, pid)
            self.assertIsNone(P["budget"], pid)
            self.assertIsNone(P["remain"], pid)
            self.assertEqual(P["budget_reason"], "사전견적 0원 또는 음수", pid)
            self.assertEqual(pct(P["paid_total"], P["budget"]), "판단 불가", pid)
        html = render(R, "mgmt")
        for pid in ("P26208", "P26207"):
            r3 = self.row(section(html, 3), pid)[0]
            for needle in ("예산 미지정", "판단 불가", "사전견적 0원 또는 음수"):
                self.assertIn(needle, r3, pid)
        self.assertIn("예산 미책정 3건 (사전견적 없음 1건, 사전견적 0원 또는 음수 2건)", first_screen(html))
        check_editions(self, R)

    def test_no_budget_reason_unparseable_estimate(self):
        R = self.edit_projects({"P26205": "약 4500만"})
        P = self.P(R, "P26205")
        self.assertIsNone(P["budget"])
        self.assertIsNone(P["remain"])
        self.assertEqual(P["budget_reason"], "사전견적 금액 해석 불가")
        self.assertEqual(pct(P["paid_total"], P["budget"]), "판단 불가")
        html = render(R, "mgmt")
        self.assertIn("사전견적 금액 해석 불가", self.row(section(html, 3), "P26205")[0])
        self.assertTrue(any(f == "프로젝트.csv" and "사전견적예산 값이 숫자가 아님" in m for f, _, m in R["s7"]["issues"]))
        self.assertIn("예산 미책정 2건 (사전견적 없음 1건, 사전견적 금액 해석 불가 1건)", first_screen(html))
        check_editions(self, R)

    def test_cost_rate_setting_error(self):
        for bad in ("abc", "1.5", "0"):
            with self.subTest(bad):
                R = self.set_rate(bad)
                self.assertIsNone(R["s3"]["cost_rate"])
                for P in R["s3"]["projects"]:
                    self.assertIsNone(P["budget"], P["id"])
                    self.assertIsNone(P["remain"], P["id"])
                    self.assertEqual(P["budget_reason"], "사전견적 없음" if P["id"] == "P26204" else "원가율 설정 오류", P["id"])
                tot = R["s3"]["total"]
                self.assertIsNone(tot["budget"])
                self.assertIsNone(tot["remain"])
                self.assertEqual(tot["budget_missing"], 8)
                self.assertTrue(any(f == "설정.csv" and str(l) == "9" and "예산_원가율 값 오류" in m and bad in m
                                    for f, l, m in R["s7"]["issues"]), R["s7"]["issues"])
                self.assertNotIn("예산_원가율", R["settings_default"])
                fs = first_screen(render(R, "mgmt"))
                self.assertIn("예산 미책정 8건 (사전견적 없음 1건, 원가율 설정 오류 7건)", fs)
                self.assertIn("예산 미지정 (원가율 설정 오류)", fs)
                for ed in ("ceo", "mgmt"):
                    self.assertNotIn("원가율 원가율", render(R, ed))
                check_editions(self, R)

    def test_cost_rate_blank_uses_default_and_listed(self):
        for name, value, line in (("blank", "", 9), ("row deleted", None, "-")):
            with self.subTest(name):
                R = self.set_rate(value)
                self.assertEqual(R["s3"]["cost_rate"], 0.7)
                self.assertEqual(self.P(R, "P26201")["budget"], 210_000_000)
                self.assertEqual(R["settings_default"]["예산_원가율"], "설정 비어 있음")
                self.assertIn(("설정.csv", line, "예산_원가율 설정 비어 있음 → 기본값 사용(0.70)"),
                              [(f, int(l) if str(l).isdigit() else l, m) for f, l, m in R["s7"]["issues"]])
        with self.subTest("70%"):
            R = self.set_rate("70%")
            self.assertEqual(R["s3"]["cost_rate"], 0.7)
            self.assertEqual(self.P(R, "P26201")["budget"], 210_000_000)
            self.assertFalse(any("예산_원가율" in m for _, _, m in R["s7"]["issues"]))

    def test_project_table_columns(self):
        html = render(self.R, "mgmt")
        s3 = section(html, 3)
        for col in ("사전견적", "원가 예산", "예산 사유", "예산 수정일", "이번 주 지급", "누적 지급", "요청 미지급",
                    "카드 미결제", "미요청 계획", "지급률", "예상 잔여예산"):
            self.assertIn(col, s3, col)
        self.assertIn("원가 예산 210,000,000", project_block(html, "P26201"))

    def test_no_budget_row_labels(self):
        html = render(self.R, "mgmt")
        r3 = self.row(section(html, 3), "P26204")[0]
        self.assertIn("예산 미지정", r3)
        self.assertIn("판단 불가", r3)
        self.assertIn("행사일 다음 달 말 금요일 지급 예정", section(html, 3))   # D-54 (D-06 뒤집음)
        self.assertIn("행사일 다음 달 말 금요일 지급 예정", first_screen(html))


class TestCliOutputs(unittest.TestCase):
    """한 번의 명령으로 두 판의 HTML과 PDF가 나오고, 옛 PDF가 새 것으로 보고되지 않는다 (REP-01, REP-03)."""

    def outdir(self):
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        return out

    def test_cli_monthly_writes_both_editions(self):
        out = self.outdir()
        r = subprocess.run([sys.executable, os.path.join(ROOT, "보고서.py"), "월간", "--기준일", "2026-10-31",
                            "--입력", SAMPLE, "--출력", out, "--pdf", "안함"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("집계 기간 2026-10-01 ~ 2026-10-31", r.stdout)
        self.assertEqual(sorted(os.listdir(out)),
                         ["2026-10-31_월간_경영관리보고.html", "2026-10-31_월간_대표보고.html"])

    def test_cli_without_browser_still_writes_html(self):
        cli = load_cli()
        out = self.outdir()
        buf = io.StringIO()
        with mock.patch.object(cli, "find_browser", return_value=None), contextlib.redirect_stdout(buf):
            rc = cli.main(["주간", "--기준일", "2026-11-02", "--입력", SAMPLE, "--출력", out])
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(os.listdir(out)),
                         ["2026-11-02_주간_경영관리보고.html", "2026-11-02_주간_대표보고.html", "지급예정기록"])
        self.assertIn("Edge/Chrome을 찾지 못해", buf.getvalue())

    def test_cli_pdf_when_browser_available(self):
        if load_cli().find_browser() is None:
            self.skipTest("Edge/Chrome 없음")
        out = self.outdir()
        r = subprocess.run([sys.executable, os.path.join(ROOT, "보고서.py"), "주간", "--기준일", "2026-11-02",
                            "--입력", SAMPLE, "--출력", out], capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(os.listdir(out)), [
            "2026-11-02_주간_경영관리보고.html", "2026-11-02_주간_경영관리보고.pdf",
            "2026-11-02_주간_대표보고.html", "2026-11-02_주간_대표보고.pdf", "지급예정기록"])
        for name in os.listdir(out):
            if name.endswith(".pdf"):
                with open(os.path.join(out, name), "rb") as f:
                    self.assertEqual(f.read(5), b"%PDF-", name)

    def stale_setup(self):
        out = self.outdir()
        html_path = os.path.join(out, "a.html")
        pdf_path = os.path.join(out, "a.pdf")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write("<html></html>")
        with open(pdf_path, "wb") as f:
            f.write(b"old")
        return html_path, pdf_path

    def test_stale_pdf_not_reported_as_new(self):
        cli = load_cli()
        html_path, pdf_path = self.stale_setup()
        with mock.patch.object(cli.subprocess, "run", return_value=None):
            err = cli.to_pdf("dummy-browser", html_path, pdf_path)
        self.assertIsNotNone(err)
        self.assertFalse(os.path.exists(pdf_path))

    def test_locked_old_pdf_reported(self):
        cli = load_cli()
        html_path, pdf_path = self.stale_setup()
        with mock.patch.object(cli.os, "remove", side_effect=PermissionError("locked")), \
                mock.patch.object(cli.subprocess, "run", return_value=None) as run_mock:
            err = cli.to_pdf("dummy-browser", html_path, pdf_path)
        self.assertIsNotNone(err)
        self.assertIn("이전 PDF", err)
        self.assertEqual(run_mock.call_count, 0)


class TestUserRulesLocked(Base):
    """남은 Phase 1 요구를 샘플의 정확한 값으로 못 박는다. 앞 10개는 지금 동작을 고정하는 잠금 테스트다 (A-09)."""

    def edit(self, filename, mutate):
        return compute(load(probe_folder(self, filename, mutate)), "weekly", ASOF)

    def test_outflows_split_by_category(self):
        self.assertEqual(self.R["s1"]["by_cat"], {"프로젝트지급": [0, 20_200_000], "회사공통지출": [0, 8_000_000],
                                                  "고객입금": [55_000_000, 0], "카드대금": [0, 12_400_000]})
        self.assertNotIn("계좌간이체", self.R["s1"]["by_cat"])

    def test_min_balance_firm_and_estimate(self):
        mn = self.R["s2"]["min"]
        self.assertEqual(mn["firm"], (19_800_000, dt.date(2027, 4, 25)))
        self.assertEqual(mn["all"], (122_685_000, dt.date(2027, 4, 25)))  # D-54 + 원천세 장부 계산 차액 2,900,000 (2026-11-04 A5)
        fs = first_screen(render(self.R, "mgmt"))
        self.assertIn("오늘부터 가장 적을 때 잔액", fs)
        self.assertIn("확정분만", fs)
        self.assertIn("확정 안 된 예상 금액도 포함", fs)

    def test_profit_and_cash_kept_apart(self):
        rows = {x["target"]: x for x in self.R["s4"]["sources"]["WEHAGO"]["table"]}
        co = rows["회사 전체"]
        self.assertEqual((co["cur"]["revenue"], co["cur"]["direct"], co["cur"]["gp"], co["cur"]["common"], co["cur"]["np"]),
                         (30_000_000, 20_400_000, 9_600_000, 30_000_000, -20_400_000))
        self.assertTrue(co["cur"]["provisional"])
        self.assertEqual(co["ytd"]["revenue"], 1_380_000_000)
        self.assertEqual(co["ytd"]["np"], 111_600_000)
        team = rows["기획1팀"]
        self.assertEqual(team["cur"]["gp"], 5_280_000)
        self.assertIsNone(team["cur"]["np"])
        fs = first_screen(render(self.R, "mgmt"))
        cash = fs.split("<div class='card avail'>")[1].split("</table>")[0]
        self.assertIn("계좌 합계", cash)
        self.assertNotIn("이익", cash)   # 이익은 자금 칸에 섞지 않고 실적 칸에 따로
        self.assertIn("11월 실적", fs)
        self.assertIn("10월 영업이익 (지난달)", fs)   # 달 초(11/2)는 지난달 영업이익 (2026-11-04 이해도 점검 U4)

    def test_pl_sources_separate(self):
        self.assertEqual(list(self.R["s4"]["sources"]), ["WEHAGO", "인트라넷완료보고"])
        s4 = section(render(self.R, "mgmt"), 4)
        self.assertIn("WEHAGO 손익 (최근 반영월 2026-11)", s4)
        self.assertIn("인트라넷완료보고 손익 (최근 반영월 2026-10)", s4)

    def test_unrecognized_and_unknown_cost(self):
        projects = {p["id"]: p for p in self.R["s3"]["projects"]}
        self.assertEqual(projects["P26201"]["unrecognized"], 360_000_000)
        self.assertEqual(self.R["s4"]["unrecognized"], 618_000_000)
        self.assertEqual(self.R["s4"]["unrecognized_missing"], 1)
        self.assertIsNone(projects["P26206"]["profit_end"])
        row = re.findall(r"<tr[^>]*><td>P26206</td>.*?</tr>", section(render(self.R, "mgmt"), 4), re.S)[0]
        self.assertIn("판단 불가", row)
        self.assertIn("미확인 원가 1건", row)
        intra = {x["target"].split(" ")[0]: x for x in self.R["s4"]["sources"]["인트라넷완료보고"]["table"]}
        self.assertIsNone(intra["P26206"]["ytd"]["gp"])

    def test_receivable_amounts_and_overdue_days(self):
        s5 = self.R["s5"]
        self.assertEqual((s5["contract"], s5["issued"], s5["unissued"], s5["ar"]),
                         (828_000_000, 358_000_000, 470_000_000, 220_000_000))  # 검토 3: P26204 D사 취소 −11,000,000이 수정 8,800,000 미수를 상계
        self.assertEqual([(v["project"], v["overdue_days"], v["outstanding"]) for v in s5["overdue"]],
                         [("P26202", 33, 110_000_000)])

    def test_specials_listed_separately(self):
        self.assertEqual(sorted(v["kind"] for v in self.R["s5"]["specials"]), ["선수금", "선수금", "수정", "취소"])
        self.assertIn("선수금·취소·환불·수정 (4건)", section(render(self.R, "mgmt"), 5))

    def test_nonproject_obligations_by_category(self):
        by_cat = self.R["s6"]["by_cat"]
        want = {"급여", "회사부담금", "임차료", "구독료", "세금", "카드대금", "차입금원금", "차입금이자", "보증금", "설비·이전"}
        self.assertTrue(want <= set(by_cat), want - set(by_cat))
        self.assertEqual(by_cat["급여"]["total"], 270_000_000)

    def test_changes_and_plan_vs_actual(self):
        s7 = self.R["s7"]
        self.assertEqual([c["field"] for c in s7["changes"]], ["예산", "입금예정일", "지급예정액"])
        self.assertEqual(s7["unplanned_total"], 3_700_000)
        self.assertEqual({x["vendor"] for x in s7["pva"] if x["unplanned"]}, {"케이터링", "꽃장식"})

    def test_unreflected_scope_items(self):
        s7 = self.R["s7"]
        self.assertEqual([p["id"] for p in s7["no_budget"]], ["P26204"])
        self.assertEqual(s7["unlinked_txn_total"], 1_500_000)
        self.assertEqual(s7["undated_out"], 105_000_000)
        self.assertEqual(s7["undated_out_n"], 4)
        self.assertEqual([a["name"] for a in s7["asof"]], ["은행 잔액 확인", "회계 반영 (WEHAGO)", "인트라넷 갱신"])
        self.assertEqual(len(s7["diffs"]), 2)
        self.assertEqual(sum(1 for x in s7["diffs"] if x["state"] == "미확인"), 1)

    def test_invoice_unknown_counts_shown(self):
        def mutate(rows):
            for r in rows[1:]:
                if r[0] == "P26203" and r[3] == "발행":
                    r[5] = ""
                if r[0] == "P26204" and r[3] == "수정":
                    r[4] = ""
        R = self.edit("계산서.csv", mutate)
        by = {x["P"]["id"]: x for x in R["s5"]["by_project"]}
        a = by["P26203"]
        self.assertEqual((a["issued"], a["issued_unknown"], a["ar"], a["ar_unknown"]), (80_000_000, 0, None, 1))
        b = by["P26204"]
        self.assertEqual((b["issued"], b["issued_unknown"], b["unissued"], b["ar"], b["ar_unknown"]),
                         (0, 1, None, None, 1))
        s5 = R["s5"]
        self.assertEqual((s5["ar"], s5["ar_unknown_n"]), (132_000_000, 2))
        self.assertEqual((s5["issued"], s5["issued_unknown_n"]), (350_000_000, 1))
        self.assertEqual((s5["unissued"], s5["unissued_unknown_n"]), (428_000_000, 2))
        html = render(R, "mgmt")
        sec5 = section(html, 5)
        row_a = re.findall(r"<tr[^>]*><td>P26203</td>.*?</tr>", sec5, re.S)[0]
        self.assertIn("미확인 1건", row_a)
        self.assertNotIn('<td class="n">0</td>', row_a)
        row_b = re.findall(r"<tr[^>]*><td>P26204</td>.*?</tr>", sec5, re.S)[0]
        self.assertIn("외 미확인 1건", row_b)
        self.assertIn("판단 불가", row_b)
        tot = re.findall(r'<tr class="tot">.*?</tr>', sec5, re.S)[0]
        for needle in ("132,000,000", "외 미확인 2건", "350,000,000", "외 미확인 1건", "외 판단 불가 2건"):
            self.assertIn(needle, tot, needle)
        self.assertNotIn("미수금 (세금계산서 발행 후)", first_screen(html))   # 주간엔 미수금 칸 없음 (사용자 2026-11-03)
        RM = compute(load(probe_folder(self, "계산서.csv", mutate)), "monthly", ASOF)
        value = first_screen(render(RM, "mgmt")).split("미수금 (세금계산서 발행 후)</div><div class='big'>")[1].split("</div>")[0]
        self.assertIn("132,000,000", value)
        self.assertIn("미확인 2건", value)
        check_editions(self, R)
        self.assertEqual((self.R["s5"]["ar_unknown_n"], self.R["s5"]["issued_unknown_n"],
                          self.R["s5"]["unissued_unknown_n"]), (0, 0, 1))

    def test_blank_plan_amount_not_zero(self):
        def mutate(rows):
            for r in rows[1:]:
                if r[1] == "P26203" and r[2] == "전시제작사":
                    r[3] = ""
        R = self.edit("지급계획.csv", mutate)
        item = next(x for x in R["s7"]["pva"] if x["vendor"] == "전시제작사")
        self.assertIsNone(item["plan"])
        self.assertEqual(item["plan_unknown"], 1)
        self.assertFalse(item["unplanned"])
        self.assertEqual(R["s7"]["plan_total"], 36_900_000)
        self.assertEqual(R["s7"]["plan_unknown_n"], 1)
        s7 = section(render(R, "mgmt"), 7)
        row = re.findall(r"<tr[^>]*><td>P26203</td><td>전시제작사</td>.*?</tr>", s7, re.S)[0]
        self.assertIn("미확인", row)
        self.assertNotIn("계획 없음", row)
        self.assertIn("계획 금액 미확인 1건", s7)

    def test_blank_contract_not_zero(self):
        def mutate(rows):
            for r in rows[1:]:
                if r[0] == "P26204":
                    r[7] = ""
        R = self.edit("프로젝트.csv", mutate)
        self.assertIsNone(R["s7"]["no_budget_contract"])  # 검토 6: 전부 미등록이면 0이 아니라 None
        self.assertEqual(R["s7"]["no_budget_contract_missing"], 1)
        self.assertIn("계약 미등록 1건", re.sub(r"<[^>]+>", "", section(render(R, "mgmt"), 7)))


_BASE_R = None


def sample_result():
    global _BASE_R
    if _BASE_R is None:
        _BASE_R = compute(load(SAMPLE), "weekly", ASOF)
    return _BASE_R


def sample_copy(test):
    """샘플 입력 전체를 임시 폴더에 복사해 폴더 경로를 돌려준다 (파일 지우기·여러 칸 고치기용)."""
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp, True)
    folder = os.path.join(tmp, "입력")
    shutil.copytree(SAMPLE, folder)
    return folder


def kpi_value(html, label):
    """첫 화면 KPI 칸의 값 부분 HTML. 없으면 None."""
    m = re.search(r"<div class='l'>" + re.escape(label) + r"</div><div class='v'>(.*?)</div>", html, re.S)
    return m.group(1) if m else None


class TestNoBalanceKnown(unittest.TestCase):
    """CR-01: 알려진 계좌 잔액이 하나도 없으면 현재 현금은 0이 아니라 미확인이다. 그래프·최저 잔액도 0에서 시작하지 않는다."""

    def no_file(self):
        folder = sample_copy(self)
        os.remove(os.path.join(folder, "계좌잔액.csv"))
        return folder

    def all_blank(self):
        def mutate(rows):
            for r in rows[1:]:
                r[3] = ""
        return probe_folder(self, "계좌잔액.csv", mutate)

    def cases(self):
        return (("계좌잔액.csv 없음", self.no_file()), ("모든 잔액 칸 빈칸", self.all_blank()))

    def test_total_and_available_are_unknown_not_zero(self):
        for name, folder in self.cases():
            with self.subTest(name):
                R = compute(load(folder), "weekly", ASOF)
                self.assertIsNone(R["s1"]["total"])
                self.assertIsNone(R["s1"]["available"])
                self.assertIsNone(R["s1"]["start_calc"])
                self.assertIsNone(R["s1"]["start_bank"])
                self.assertIsNone(R["s2"]["start"])

    def test_schedule_and_minimum_do_not_start_from_zero(self):
        for name, folder in self.cases():
            with self.subTest(name):
                R = compute(load(folder), "weekly", ASOF)
                s2 = R["s2"]
                for b in s2["buckets"]:
                    self.assertIsNone(b["bal_firm"])
                    self.assertIsNone(b["bal_all"])
                self.assertEqual(s2["min"]["firm"], (None, None))
                self.assertEqual(s2["min"]["all"], (None, None))
                # 입금·지급 금액 자체는 그대로 계산된다
                self.assertGreater(sum(b["out_firm"] for b in s2["buckets"]), 0)

    def test_first_screen_shows_unknown_balance(self):
        for name, folder in self.cases():
            with self.subTest(name):
                R = compute(load(folder), "weekly", ASOF)
                html = render(R, "mgmt")
                fs = first_screen(html)
                self.assertIn("오늘 쓸 수 있는 돈 잔액 미확인", fs)
                self.assertIn("잔액 미확인", fs)
                self.assertNotIn("<polyline", fs)
                for cells in avail_rows(fs):
                    for val in cells[3:]:   # 예상 잔액 · 기간 중 최저 잔액 · 가용자금(확정분만 포함): 0에서 시작하지 않는다
                        self.assertIn("확인 필요", val)
                        self.assertNotRegex(val, r"\d")
                    self.assertEqual(len(cells), 4)
                s2h = section(html, 2)
                self.assertIn("잔액 미확인", s2h)
                self.assertNotIn("미확인원", s2h)

    def test_management_risk_has_no_fund_risk_from_fabricated_zero(self):
        for name, folder in self.cases():
            with self.subTest(name):
                R = compute(load(folder), "weekly", ASOF)
                for r in R["risks"]:
                    self.assertNotIn("최저 계산 잔액", r["fact"], r)
                html = render(R, "mgmt")
                self.assertIn("위험 분석·해결방안", html)
                check_editions(self, R)

    def test_balance_known_sample_unchanged(self):
        self.assertEqual(sample_result()["s2"]["min"]["firm"], (19_800_000, dt.date(2027, 4, 25)))


def table_cells(row_html):
    """<tr> 한 줄 HTML에서 칸 내용(HTML)만 순서대로 꺼낸다."""
    return re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)


def first_screen_project_row(html, pid):
    return table_cells(re.findall(r"<tr[^>]*><td>" + pid + r"</td>.*?</tr>", first_screen(html), re.S)[0])


def first_screen_total_row(html):
    return table_cells(re.findall(r'<tr class="tot">.*?</tr>', first_screen(html), re.S)[0])


class TestProjectUnknownOnFirstScreen(unittest.TestCase):
    """CR-02 + 검증 gap: 금액 미확인 프로젝트 집행 줄이 첫 화면에서 0으로 보이면 안 된다. 건수를 함께 보인다 (D-02)."""
    COL_REQ, COL_CARD = 11, 12   # 상세 3번 표의 '요청 미지급' · '카드 미결제' 칸

    def test_unknown_request_line_marked_on_first_screen(self):
        R = sample_result()
        html = render(R, "mgmt")
        P = next(p for p in R["s3"]["projects"] if p["id"] == "P26206")
        self.assertEqual(P["unknown_cost"], 1)
        self.assertEqual(P["line_unknown"]["요청미지급"], 1)
        self.assertIsNone(P["remain"])
        block = project_block(html, "P26206")
        self.assertIn('집행 예정액 <span class="na">미확인 1건</span>', block)
        self.assertIn("확인 필요 (미확인 원가 1건)", block)
        self.assertIn("c-q'>확인 필요", block)
        # 미확인 줄이 없는 프로젝트는 표시가 바뀌지 않는다
        self.assertNotIn("미확인", project_block(html, "P26201"))

    def test_total_row_and_card_carry_unknown_count(self):
        R = sample_result()
        html = render(R, "mgmt")
        tot = first_screen(html).split("<div class='ptot'>")[1].split("</div>")[0]
        self.assertIn('집행 예정액 253,550,000<span class="na"> 외 미확인 1건</span>', tot)
        self.assertIn("미확인 원가 1개 프로젝트 제외", tot)
        self.assertIn("95,000,000", table_cells(re.findall(r'<tr class="tot">.*?</tr>', section(html, 3), re.S)[0])[self.COL_REQ])
        self.assertEqual(R["s3"]["total"]["line_unknown"]["요청미지급"], 1)
        check_editions(self, R)

    def test_total_remaining_excludes_unknown_cost_projects(self):
        R = sample_result()
        tot = R["s3"]["total"]
        known = [P["remain"] for P in R["s3"]["projects"] if P["remain"] is not None]
        self.assertEqual(tot["remain"], sum(known))
        self.assertEqual(tot["remain_excluded"], 1)

    def test_all_request_lines_unknown_is_not_zero(self):
        def mutate(rows):
            for r in rows[1:]:
                if r[3] == "요청미지급":
                    r[4] = ""
        R = compute(load(probe_folder(self, "프로젝트집행.csv", mutate)), "weekly", ASOF)
        html = render(R, "mgmt")
        tot = first_screen(html).split("<div class='ptot'>")[1].split("</div>")[0]
        self.assertIn("외 미확인 4건", tot)
        self.assertIn("미확인 1건", project_block(html, "P26203"))
        check_editions(self, R)

    def test_unknown_card_unpaid_marked(self):
        def mutate(rows):
            for r in rows[1:]:
                if r[0] == "P26208":
                    r[4] = ""
        R = compute(load(probe_folder(self, "프로젝트집행.csv", mutate)), "weekly", ASOF)
        html = render(R, "mgmt")
        P = next(p for p in R["s3"]["projects"] if p["id"] == "P26208")
        self.assertEqual(P["line_unknown"]["카드사용미결제"], 1)
        self.assertIsNone(P["remain"])
        self.assertIn("외 미확인 2건", first_screen(html).split("<div class='ptot'>")[1].split("</div>")[0])  # 표본의 미확인 요청 1건 + 카드 1건
        self.assertEqual(sample_result()["s3"]["total"]["line_unknown"]["카드사용미결제"], 0)
        check_editions(self, R)


class TestAllUnknownTotals(unittest.TestCase):
    """CR-03: 값이 모두 미확인인 합계는 0이 아니라 판단 불가·미확인이고, 일부 미확인이면 합계 옆에 건수가 붙는다 (D-02)."""

    def test_ssum_or_none(self):
        from ceo_report import util
        ssum_or_none = util.ssum_or_none
        self.assertEqual(ssum_or_none([]), (0, 0))
        self.assertEqual(ssum_or_none([1, 2]), (3, 0))
        self.assertEqual(ssum_or_none([1, None]), (1, 1))
        self.assertEqual(ssum_or_none([None, None]), (None, 2))
        self.assertEqual(ssum_or_none(iter([0, None])), (0, 1))

    def edit(self, filename, mutate):
        R = compute(load(probe_folder(self, filename, mutate)), "weekly", ASOF)
        return R, render(R, "mgmt")

    def tot_row(self, html, n):
        return table_cells(re.findall(r'<tr class="tot">.*?</tr>', section(html, n), re.S)[0])

    def test_paid_cash_total_unknown_when_all_vat_blank(self):
        def mutate(rows):
            for r in rows[1:]:
                if r[3] == "지급완료":
                    r[5] = ""
        R, html = self.edit("프로젝트집행.csv", mutate)
        tot = R["s3"]["total"]
        self.assertIsNone(tot["paid_cash"])
        self.assertEqual(tot["paid_cash_unknown"], 7)
        cell = self.tot_row(html, 3)[10]
        self.assertEqual(re.sub(r"<[^>]+>", "", cell), "부가세 미확인 7건")
        self.assertIsNotNone(sample_result()["s3"]["total"]["paid_cash"])
        check_editions(self, R)

    def test_partial_paid_cash_shows_count(self):
        def mutate(rows):
            for r in rows[1:]:
                if r[2] == "무대제작사" and r[1] == "무대·구조물 2차":
                    r[5] = ""
        R, html = self.edit("프로젝트집행.csv", mutate)
        tot = R["s3"]["total"]
        self.assertEqual(tot["paid_cash_unknown"], 1)
        self.assertIsNotNone(tot["paid_cash"])
        self.assertIn("외 부가세 미확인 1건", self.tot_row(html, 3)[10])

    def test_all_contracts_blank(self):
        def mutate(rows):
            for r in rows[1:]:
                r[7] = ""
        R, html = self.edit("프로젝트.csv", mutate)
        s5, s4 = R["s5"], R["s4"]
        self.assertIsNone(s5["contract"])
        self.assertEqual(s5["contract_missing"], 8)
        self.assertIsNone(s5["unissued"])
        self.assertEqual(s5["unissued_unknown_n"], 8)
        self.assertIsNone(s4["unrecognized"])
        self.assertEqual(s4["unrecognized_missing"], 8)
        # 첫 화면은 2026-11-03부터 계약금액 대신 '행사 후 세금계산서 미발행'(사전견적 기준)을 보인다. 계약금액 칸은 상세 4·5번에.
        self.assertIn("미확인 8건", self.tot_row(html, 4)[4])
        self.assertIn("미등록 8건", self.tot_row(html, 4)[2])
        self.assertNotIn(">0<", self.tot_row(html, 4)[4])
        check_editions(self, R)

    def test_partial_unknown_counts_beside_first_screen_totals(self):
        R = sample_result()
        self.assertEqual(R["s4"]["unrecognized_missing"], 1)
        self.assertIn("미확인 1건", self.tot_row(render(R, "mgmt"), 4)[4])

    def test_category_total_unknown_when_every_row_unknown(self):
        def mutate(rows):
            rows.extend([["2026-11-20", "지급", "", "추정", "시험분류", "", "가나다", "청구서", ""],
                         ["2026-11-21", "지급", "", "추정", "시험분류", "", "라마바", "청구서", ""]])
        R, html = self.edit("자금일정.csv", mutate)
        g = R["s6"]["by_cat"]["시험분류"]
        self.assertIsNone(g["total"])
        self.assertEqual(g["unknown"], 2)
        self.assertEqual(R["s6"]["total"], 584_100_000)
        row = re.findall(r"<tr[^>]*><td>시험분류</td>.*?</tr>", section(html, 6), re.S)[0]
        cells = table_cells(row)
        self.assertIn("미확인", cells[2])
        self.assertNotRegex(cells[2], r"\d")
        self.assertEqual(cells[4], "2건")
        check_editions(self, R)

    def test_all_nonproject_amounts_unknown_total_is_unknown(self):
        def mutate(rows):
            for r in rows[1:]:
                if r[1] == "지급":
                    r[2] = ""
        R, html = self.edit("자금일정.csv", mutate)
        self.assertIsNone(R["s6"]["total"])
        val = box_item(first_screen(html), "프로젝트 밖 지급 예정")
        self.assertTrue(val.startswith("프로젝트 밖 지급 예정 (등록분 전체) 금액 미확인"), val)
        self.assertIn("· 금액 미확인", val)


class TestFirstScreenCountsD04(unittest.TestCase):
    """D-04: 날짜 없는 예정금액과 입금예정일이 지난 미수는 첫 화면에도 건수와 금액이 함께 보인다."""
    UNDATED = "날짜 없는 입금 예정"
    OVERDUE = "입금예정일 지난 미수금"

    def test_undated_line_has_counts_and_amounts(self):
        fs = first_screen(render(sample_result(), "mgmt"))
        self.assertEqual(box_item(fs, self.UNDATED), "날짜 없는 입금 예정 1건 30,000,000 / 지급 예정 4건 105,000,000")  # 검토 3: P26204 D사 취소 −11,000,000이 수정 8,800,000 미수를 상계

    def test_overdue_receivable_line_has_count(self):
        fs = first_screen(render(sample_result(), "mgmt"))
        self.assertEqual(box_item(fs, self.OVERDUE), "입금예정일 지난 미수금 1건 110,000,000 (일정에 넣지 않음)")

    def add_rows(self, *new_rows):
        return probe_folder(self, "자금일정.csv", lambda rows: rows.extend([list(r) for r in new_rows]))

    def test_undated_unknown_amount_counted_not_zero(self):
        blank_out = ["", "지급", "", "추정", "미정산비용", "", "간식업체", "청구서", "금액 미정"]
        with self.subTest("A: known + blank"):
            R = compute(load(self.add_rows(blank_out)), "weekly", ASOF)
            s2 = R["s2"]
            self.assertEqual((s2["undated_out"], s2["undated_out_n"], s2["undated_out_unknown"]), (105_000_000, 5, 1))
            self.assertEqual((s2["undated_in"], s2["undated_in_n"], s2["undated_in_unknown"]), (30_000_000, 1, 0))  # 검토 3: P26204 D사 취소 −11,000,000이 수정 8,800,000 미수를 상계
            html = render(R, "mgmt")
            val = box_item(first_screen(html), self.UNDATED)
            self.assertEqual(val, "날짜 없는 입금 예정 1건 30,000,000 / 지급 예정 5건 105,000,000 (금액 미확인 1건)")
            self.assertEqual(R["s7"]["undated_out_n"], 5)
            check_editions(self, R)
        with self.subTest("B: only blank on the incoming side"):
            folder = self.add_rows()

            def blank_sched(rows):
                for r in rows[1:]:
                    if r[0] == "" and r[1] == "입금":
                        r[2] = ""
            edit_csv(folder, "자금일정.csv", blank_sched)

            def drop_correction(rows):
                rows[:] = [r for r in rows if r[3] != "수정"]
            edit_csv(folder, "계산서.csv", drop_correction)
            R = compute(load(folder), "weekly", ASOF)
            s2 = R["s2"]
            self.assertIsNone(s2["undated_in"])
            self.assertEqual((s2["undated_in_n"], s2["undated_in_unknown"]), (1, 1))
            val = box_item(first_screen(render(R, "mgmt")), self.UNDATED)
            self.assertTrue(val.startswith("날짜 없는 입금 예정 1건 금액 미확인 /"), val)
            self.assertNotIn("1건 0.0", val)
            self.assertIn("지급 예정 4건 105,000,000", val)
            check_editions(self, R)


class TestCliArguments(unittest.TestCase):
    """WR-01: 잘못된 --시작일을 조용히 무시하지 않는다."""

    def run_cli(self, *extra):
        cli = load_cli()
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out, True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["주간", "--기준일", "2026-11-02", "--입력", SAMPLE, "--출력", out, "--pdf", "안함"] + list(extra))
        return rc, buf.getvalue(), os.listdir(out)

    def test_bad_start_date_is_an_error(self):
        rc, text, files = self.run_cli("--시작일", "2026-13-45")
        self.assertEqual(rc, 2)
        self.assertIn("시작일", text)
        self.assertIn("2026-13-45", text)
        self.assertEqual(files, [])

    def test_start_date_after_reference_date_is_an_error(self):
        rc, text, files = self.run_cli("--시작일", "2026-11-03")
        self.assertEqual(rc, 2)
        self.assertIn("시작일", text)
        self.assertEqual(files, [])

    def test_pick_date_option_adds_row(self):
        rc, text, files = self.run_cli("--가용일", "2026-12-15")
        self.assertEqual(rc, 0, text)
        out = [f for f in files if f.endswith("대표보고.html")][0]
        self.assertTrue(out)

    def test_bad_pick_date_is_an_error(self):
        for bad in ("2026-13-45", "2026-11-02", "2026-10-01"):
            with self.subTest(bad):
                rc, text, files = self.run_cli("--가용일", bad)
                self.assertEqual(rc, 2)
                self.assertIn("가용일", text)
                self.assertEqual(files, [])

    def test_valid_start_date_sets_period(self):
        rc, text, files = self.run_cli("--시작일", "2026-10-20")
        self.assertEqual(rc, 0)
        self.assertIn("집계 기간 2026-10-20 ~ 2026-11-02", text)
        self.assertEqual(len(files), 3)   # 보고서 2개 + 지급예정기록 폴더 (주간)


class TestPdfLaunch(unittest.TestCase):
    """WR-02: 이미 열려 있는 Edge/Chrome에 일을 넘기지 않고, 파일 주소를 바르게 만들고, 빈 PDF를 성공으로 치지 않는다."""

    def setUp(self):
        self.cli = load_cli()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def make_html(self, folder_name="out"):
        folder = os.path.join(self.tmp, folder_name)
        os.makedirs(folder)
        html_path = os.path.join(folder, "a.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write("<html></html>")
        return html_path, os.path.join(folder, "a.pdf")

    def fake_browser(self, calls, size=5):
        def run(cmd, **kwargs):
            calls.append((list(cmd), kwargs, [d for d in cmd if d.startswith("--user-data-dir=")]))
            for arg in cmd:
                if arg.startswith("--user-data-dir="):
                    calls[-1] += (os.path.isdir(arg.split("=", 1)[1]),)
                if arg.startswith("--print-to-pdf="):
                    with open(arg.split("=", 1)[1], "wb") as f:
                        f.write(b"%PDF-1.4\n%%EOF\n" if size else b"")
            return None
        return run

    def test_pdf_written_after_browser_returns_is_success(self):
        """사용자 PC 2026-11-04: Edge 명령이 먼저 끝나고 PDF 는 1~3초 뒤에 써짐 → 실패로 적으면 안 됨."""
        import threading
        html_path, pdf_path = self.make_html()

        def late(cmd, **kwargs):
            def write():
                with open(pdf_path, "wb") as f:
                    f.write(b"%PDF-1.4\n%%EOF\n")
            threading.Timer(0.3, write).start()
            return None
        with mock.patch.object(self.cli.subprocess, "run", side_effect=late), \
                mock.patch.object(self.cli, "PDF_WAIT", 5):
            self.assertIsNone(self.cli.to_pdf("b", html_path, pdf_path))

    def test_half_written_pdf_is_not_success(self):
        html_path, pdf_path = self.make_html()

        def half(cmd, **kwargs):
            with open(pdf_path, "wb") as f:
                f.write(b"%PDF-1.4\n1 0 obj")
            return None
        with mock.patch.object(self.cli.subprocess, "run", side_effect=half):
            self.assertIsNotNone(self.cli.to_pdf("b", html_path, pdf_path))

    def test_dedicated_profile_dir_used_and_removed(self):
        html_path, pdf_path = self.make_html()
        calls = []
        with mock.patch.object(self.cli.subprocess, "run", side_effect=self.fake_browser(calls)):
            self.assertIsNone(self.cli.to_pdf("b", html_path, pdf_path))
        cmd, kwargs, profile, existed = calls[0]
        self.assertEqual(len(profile), 1)
        pdir = profile[0].split("=", 1)[1]
        self.assertTrue(existed)
        self.assertFalse(os.path.exists(pdir), "임시 프로필 폴더가 남음")
        self.assertIsInstance(cmd, list)
        self.assertFalse(kwargs.get("shell"))
        self.assertIn("--disable-field-trial-config", cmd)  # 새 프로필에서 PDF 출력이 멈추지 않게

    def test_each_call_uses_its_own_profile_dir(self):
        html_path, pdf_path = self.make_html()
        calls = []
        with mock.patch.object(self.cli.subprocess, "run", side_effect=self.fake_browser(calls)):
            self.cli.to_pdf("b", html_path, pdf_path)
            self.cli.to_pdf("b", html_path, pdf_path)
        self.assertNotEqual(calls[0][2], calls[1][2])

    def test_profile_dir_removed_when_browser_fails(self):
        html_path, pdf_path = self.make_html()
        seen = []

        def boom(cmd, **kwargs):
            seen.extend(a.split("=", 1)[1] for a in cmd if a.startswith("--user-data-dir="))
            raise OSError("cannot start")
        with mock.patch.object(self.cli.subprocess, "run", side_effect=boom):
            err = self.cli.to_pdf("b", html_path, pdf_path)
        self.assertIsNotNone(err)
        self.assertTrue(seen)
        self.assertFalse(os.path.exists(seen[0]))

    def test_file_url_is_percent_encoded_uri(self):
        html_path, pdf_path = self.make_html("폴더 #1 100%")
        calls = []
        with mock.patch.object(self.cli.subprocess, "run", side_effect=self.fake_browser(calls)):
            self.cli.to_pdf("b", html_path, pdf_path)
        url = calls[0][0][-1]
        self.assertEqual(url, pathlib.Path(html_path).resolve().as_uri())
        self.assertIn("%23", url)
        self.assertNotIn(" ", url)
        self.assertTrue(url.startswith("file:///"))

    def test_no_sandbox_only_outside_windows(self):
        html_path, pdf_path = self.make_html()
        for is_win in (True, False):
            with self.subTest(windows=is_win):
                calls = []
                with mock.patch.object(self.cli, "_is_windows", return_value=is_win), \
                        mock.patch.object(self.cli.subprocess, "run", side_effect=self.fake_browser(calls)):
                    self.cli.to_pdf("b", html_path, pdf_path)
                self.assertEqual("--no-sandbox" in calls[0][0], not is_win)

    def test_empty_pdf_is_a_failure(self):
        html_path, pdf_path = self.make_html()
        calls = []
        with mock.patch.object(self.cli.subprocess, "run", side_effect=self.fake_browser(calls, size=0)):
            err = self.cli.to_pdf("b", html_path, pdf_path)
        self.assertIsNotNone(err)
        self.assertFalse(os.path.exists(pdf_path), "빈 PDF를 남기지 않음")


class TestPaidDateWithoutAmount(unittest.TestCase):
    """WR-03: 입금일은 있는데 입금액이 빈칸이면 미수를 전액으로 단정하지 않고 미확인으로 센다 (D-02)."""

    def compute_with(self, paid_date, paid_amount):
        def mutate(rows):
            for r in rows[1:]:
                if r[0] == "P26202":
                    r[8], r[9] = paid_date, paid_amount
        R = compute(load(probe_folder(self, "계산서.csv", mutate)), "weekly", ASOF)
        return R, render(R, "mgmt")

    def test_paid_date_without_amount_is_unknown_outstanding(self):
        R, html = self.compute_with("2026-10-20", "")
        inv = [x for x in R["s5"]["by_project"] if x["P"]["id"] == "P26202"][0]
        self.assertIsNone(inv["ar"])
        self.assertEqual(inv["ar_unknown"], 1)
        self.assertEqual(R["s5"]["ar_unknown_n"], 1)
        self.assertFalse(any(x["project"] == "P26202" for x in R["s5"]["ar_rows"]))
        self.assertEqual(R["s5"]["overdue"], [])
        self.assertEqual(R["s5"]["overdue_total"], 0)
        self.assertFalse(any(e["project"] == "P26202" and e["io"] == "in" for e in R["events"]))
        self.assertEqual(R["s2"]["past_in_n"], 0)
        RM = compute(load(probe_folder(self, "계산서.csv", lambda rows: [r.__setitem__(slice(8, 10), ["2026-10-20", ""]) for r in rows[1:] if r[0] == "P26202"])), "monthly", ASOF)
        self.assertIn("미확인 1건", first_screen(render(RM, "mgmt")).split("미수금 (세금계산서 발행 후)</div><div class='big'>")[1].split("</div>")[0])
        row = re.findall(r"<tr[^>]*><td>P26202</td>.*?</tr>", section(html, 5), re.S)[0]
        self.assertIn("미확인 1건", row)
        check_editions(self, R)

    def test_blank_paid_date_and_amount_is_still_fully_outstanding(self):
        R, _ = self.compute_with("", "")
        self.assertEqual([x["outstanding"] for x in R["s5"]["ar_rows"] if x["project"] == "P26202"], [110_000_000])
        self.assertEqual(R["s5"]["overdue_total"], 110_000_000)
        self.assertEqual(R["s5"]["ar_unknown_n"], 0)

    def test_paid_amount_without_date_still_reduces_outstanding(self):
        R, _ = self.compute_with("", "50,000,000")
        self.assertEqual([x["outstanding"] for x in R["s5"]["ar_rows"] if x["project"] == "P26202"], [60_000_000])


class TestReadCsvLines(unittest.TestCase):
    """WR-04: 칸 안의 줄바꿈과 유니코드 줄 구분 문자는 그대로 두고, 보고하는 줄 번호는 실제 파일 줄이다."""

    def write(self, text, encoding="utf-8-sig"):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "a.csv")
        with open(path, "w", encoding=encoding, newline="") as f:
            f.write(text)
        return path

    def test_multiline_and_unicode_separators_kept(self):
        text = 'a,b\r\n1,"줄1\n줄2"\r\n2,"x\u2028y"\r\n3,"p\x0bq\x85r\x1cs"\r\n'
        rows, ok = read_csv(self.write(text), ["a", "b"], Issues())
        self.assertTrue(ok)
        self.assertEqual([r["b"] for r in rows], ["줄1\n줄2", "x\u2028y", "p\x0bq\x85r\x1cs"])

    def test_line_numbers_are_file_lines(self):
        text = 'a,b\n1,"줄1\n줄2"\n\n3,x\n\n\n6,y\n'
        rows, _ = read_csv(self.write(text), ["a", "b"], Issues())
        self.assertEqual([(r["a"], r["_line"]) for r in rows], [("1", 2), ("3", 5), ("6", 8)])

    def test_line_numbers_with_crlf_and_blank_lines(self):
        text = "a,b\r\n\r\n1,x\r\n2,y\r\n"
        rows, _ = read_csv(self.write(text), ["a", "b"], Issues())
        self.assertEqual([(r["a"], r["_line"]) for r in rows], [("1", 3), ("2", 4)])

    def test_blank_rows_skipped_and_header_checked(self):
        iss = Issues()
        rows, ok = read_csv(self.write("a,b\n,\n\n"), ["a", "b", "c"], iss)
        self.assertTrue(ok)
        self.assertEqual(rows, [])
        self.assertTrue(any("필수 열 없음" in m and "c" in m for _, _, m in iss.items))

    def test_cp949_multiline(self):
        rows, ok = read_csv(self.write('항목,값\n회사명,"한글\n회사"\n', "cp949"), ["항목", "값"], Issues())
        self.assertTrue(ok)
        self.assertEqual(rows[0]["값"], "한글\n회사")

    def test_bad_number_reports_real_file_line(self):
        text = 'a,b\n1,"줄1\n줄2"\n\n3,12x\n'
        rows, _ = read_csv(self.write(text), ["a", "b"], Issues())
        iss = Issues()
        self.assertIsNone(num(rows[1]["b"], iss, rows[1], "b"))
        self.assertEqual(iss.items[0][:2], ("a.csv", 5))


class TestComputeIsPure(unittest.TestCase):
    """WR-06: compute()는 읽어 온 Data를 바꾸지 않는다. 같은 Data로 여러 번 계산해도 결과가 같고 이전 상태가 남지 않는다."""

    def setUp(self):
        self.d = load(SAMPLE)

    def test_two_calls_give_identical_results(self):
        def blank_balance(rows):  # 계산 중에 입력 확인 항목을 만드는 입력
            for r in rows[1:]:
                if r[0] == "2026-11-02" and r[1] == "운영계좌":
                    r[3] = ""
        self.d = load(probe_folder(self, "계좌잔액.csv", blank_balance))
        r1 = compute(self.d, "weekly", ASOF)
        self.assertTrue(any("잔액 미확인" in m for _, _, m in r1["s7"]["issues"]))
        issues1 = list(r1["s7"]["issues"])
        r2 = compute(self.d, "weekly", ASOF)
        self.assertEqual(r1["s7"]["issues"], issues1, "두 번째 계산이 첫 결과의 입력 확인 목록을 바꿈")
        self.assertEqual(r1, r2)
        self.assertEqual(len(r2["s7"]["issues"]), len(issues1))

    def test_data_is_not_modified(self):
        before_issues = list(self.d.issues.items)
        before_inv = [dict(v) for v in self.d.invoices]
        compute(self.d, "weekly", ASOF)
        self.assertEqual(self.d.issues.items, before_issues)
        self.assertEqual(self.d.invoices, before_inv)
        for v in self.d.invoices:
            for key in ("total", "outstanding", "overdue_days"):
                self.assertNotIn(key, v)

    def test_no_overdue_state_left_between_calls(self):
        r1 = compute(self.d, "weekly", ASOF)
        self.assertEqual([v["project"] for v in r1["s5"]["overdue"]], ["P26202"])
        early = dt.date(2026, 9, 25)  # P26202의 입금예정일(09-30) 전
        r2 = compute(self.d, "weekly", early)
        row = [v for v in r2["s5"]["ar_rows"] if v["project"] == "P26202"][0]
        self.assertNotIn("overdue_days", row)
        self.assertEqual(r2["s5"]["overdue"], [])
        html = render(r2, "mgmt")
        cells = table_cells(re.findall(r"<tr[^>]*><td>P26202</td><td>B사</td>.*?</tr>", section(html, 5), re.S)[0])
        self.assertEqual(cells[-1], "")

    def test_weekly_then_monthly_same_as_fresh_data(self):
        compute(self.d, "weekly", ASOF)
        monthly = compute(self.d, "monthly", dt.date(2026, 10, 31))
        fresh = compute(load(SAMPLE), "monthly", dt.date(2026, 10, 31))
        self.assertEqual(monthly, fresh)


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
