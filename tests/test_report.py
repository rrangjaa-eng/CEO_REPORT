"""보고 규칙 테스트. 실행: python -m unittest discover -s tests"""
import csv
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.render import render  # noqa: E402
from ceo_report.util import num, date, read_csv, Issues, is_blank, setting_num  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력")
ASOF = dt.date(2026, 11, 2)
FORBIDDEN = ("위험", "해결방안", "권고", "우려", "추천")


def numbers_of(html):
    """HTML 속 숫자 나열. 위험 분석 묶음과 작성 시각은 뺀다."""
    html = re.sub(r"<h2 id='risk'>.*?</table>", "", html, flags=re.S)
    html = re.sub(r"<div class='note' style='margin-top:10px'>위험 항목.*?</div>", "", html, flags=re.S)
    html = re.sub(r"작성 \d{4}-\d{2}-\d{2} \d{2}:\d{2}", "", html)
    return re.findall(r"−?\d[\d,.]*", html)


def probe_folder(test, filename, mutate):
    """샘플 입력을 임시 폴더에 복사하고 CSV 한 개를 고쳐 쓴다. 고친 폴더 경로를 돌려준다."""
    tmp = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, tmp)
    folder = os.path.join(tmp, "입력")
    shutil.copytree(SAMPLE, folder)
    path = os.path.join(folder, filename)
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    mutate(rows)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)
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
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_sample.py")], check=True,
                   stdout=subprocess.DEVNULL)


def kv_value(html, label):
    """render.kv()가 쓰는 '이름 / 값' 줄에서 값 부분만 꺼낸다. 없으면 None."""
    m = re.search('<div class="kv"><span>' + re.escape(label) + '</span><span>(.*?)</span></div>', html, re.S)
    return m.group(1) if m else None


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
        p = os.path.join(tmp, "a.csv")
        with open(p, "w", encoding="cp949") as f:
            f.write("항목,값\n회사명,한글회사\n")
        rows, ok = read_csv(p, ["항목", "값"], Issues())
        self.assertTrue(ok)
        self.assertEqual(rows[0]["값"], "한글회사")
        shutil.rmtree(tmp)

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
        self.assertEqual(s2["undated_in"], 30_000_000 + 8_800_000)

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

    def test_remaining_budget_not_turned_into_payment(self):
        p = self.P("P26208")
        self.assertEqual(p["remain"], 20_000_000 - 350_000)
        self.assertFalse(any(e["project"] == "P26208" for e in self.R["events"]))

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
        html = render(self.R, "ceo")
        self.assertIn("표시 6건 / 전체 8건", html)

    def test_ceo_has_no_interpretation(self):
        html = render(self.R, "ceo")
        for word in FORBIDDEN:
            self.assertNotIn(word, html, word)

    def test_same_numbers_in_both_versions(self):
        self.assertEqual(numbers_of(render(self.R, "ceo")), numbers_of(render(self.R, "mgmt")))

    def test_mgmt_has_risks(self):
        self.assertIn("위험 분석·해결방안", render(self.R, "mgmt"))
        self.assertTrue(any(r["level"] == "높음" for r in self.R["risks"]))

    def test_monthly_period(self):
        R = compute(self.d, "monthly", dt.date(2026, 10, 31))
        self.assertEqual(R["period"], (dt.date(2026, 10, 1), dt.date(2026, 10, 31)))

    def test_missing_file_reported_not_crash(self):
        tmp = tempfile.mkdtemp()
        shutil.copy(os.path.join(SAMPLE, "프로젝트.csv"), tmp)
        d = load(tmp)
        R = compute(d, "weekly", ASOF)
        render(R, "ceo")
        self.assertTrue(any("파일 없음" in m for _, _, m in R["s7"]["issues"]))
        shutil.rmtree(tmp)

    def test_cli_writes_files(self):
        out = tempfile.mkdtemp()
        r = subprocess.run([sys.executable, os.path.join(ROOT, "보고서.py"), "주간", "--기준일", "2026-11-02",
                            "--출력", out, "--pdf", "안함"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(os.listdir(out)),
                         ["2026-11-02_주간_경영관리보고.html", "2026-11-02_주간_대표보고.html"])
        shutil.rmtree(out)


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
        return R, render(R, "ceo")

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
        self.assertIn("사용제한 30.0 · 제한금액 미확인 1계좌 · " + self.NOTE, first_screen(html))
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
        return R, render(R, "ceo")

    def vendor_row(self, html, name):
        m = re.search(r"<tr[^>]*><td>" + re.escape(name) + r"</td>.*?</tr>", section(html, 6), re.S)
        self.assertIsNotNone(m, name)
        return m.group(0)

    def test_vendor_unknown_amount_not_zero(self):
        v = dict(self.R["s6"]["vendors"])["진행팀"]
        self.assertIsNone(v["total"])
        self.assertEqual((v["unknown"], v["n"]), (1, 1))
        row = self.vendor_row(render(self.R, "ceo"), "진행팀")
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
        fs = first_screen(render(self.R, "ceo"))
        self.assertEqual(kv_value(fs, "예정일 지난 미처리 입금 / 지급 (일정 미포함)"), "1건 110.0 / 0건 0.0")

    def test_past_due_payment_not_in_schedule(self):
        R, html = self.probe(self.add_schedule_rows(self.PAST_ROW))
        s2 = R["s2"]
        self.assertEqual((s2["past_out"], s2["past_out_n"], s2["past_out_unknown"]), (5_000_000, 1, 0))
        self.assertEqual([b["out_firm"] for b in s2["buckets"]], [b["out_firm"] for b in self.R["s2"]["buckets"]])
        self.assertEqual(s2["min"], self.R["s2"]["min"])
        for c in R["s7"]["checks"]:
            self.assertTrue(c[3], c[0])
        self.assertIn("/ 1건 5.0", first_screen(html))

    def test_nonproject_scope_and_undated_on_first_screen(self):
        s6 = self.R["s6"]
        self.assertEqual((s6["undated_n"], s6["unknown_n"]), (2, 0))
        fs = first_screen(render(self.R, "ceo"))
        self.assertIn("프로젝트 밖 지급예정 (등록분 전체)", fs)
        self.assertIn("584.1 · 날짜 없음 2건", fs)

    def test_past_due_unknown_amount_counted_not_zero(self):
        label = "예정일 지난 미처리 입금 / 지급 (일정 미포함)"
        with self.subTest("A: known + blank"):
            R, html = self.probe(self.add_schedule_rows(self.PAST_ROW, self.BLANK_PAST_ROW))
            s2 = R["s2"]
            self.assertEqual((s2["past_out"], s2["past_out_n"], s2["past_out_unknown"]), (5_000_000, 2, 1))
            self.assertEqual((s2["past_in"], s2["past_in_n"], s2["past_in_unknown"]), (110_000_000, 1, 0))
            val = kv_value(first_screen(html), label)
            self.assertTrue(val.startswith("1건 110.0 / 2건 5.0"), val)
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
            val = kv_value(first_screen(html), label)
            self.assertIn("금액 미확인 1건", val)
            self.assertNotIn("1건 0.0", val)

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
        self.assertEqual(s2["min"]["all"], (152_300_000, dt.date(2027, 4, 25)))
        fs = first_screen(html)
        self.assertIn("부가세 미확인 1건 (공급가액만 반영)", fs)
        for lab in ("최저 계산 잔액 · 확정 일정만", "최저 계산 잔액 · 확정+추정"):
            self.assertIn("부가세 미확인 1건", kv_value(fs, lab), lab)
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
        self.assertNotIn("부가세 미확인", first_screen(render(self.R, "ceo")))


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
        render(R, "ceo")
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
                self.assertIn("최소 보유현금 설정 비어 있음", section(render(R, "ceo"), 7))
                check_editions(self, R)

    def test_project_show_count_setting(self):
        R = compute(load(self.set_value("첫화면_프로젝트_표시수", "4")), "weekly", ASOF)
        self.assertIn("표시 4건 / 전체 8건", render(R, "ceo"))
        R = compute(load(self.set_value("첫화면_프로젝트_표시수", "-1")), "weekly", ASOF)
        self.assertIn("표시 8건 / 전체 8건", render(R, "ceo"))
        self.assertEqual(R["settings_default"]["첫화면_프로젝트_표시수"], "0 이상 정수 아님")
        self.assertTrue(any("첫화면_프로젝트_표시수 값은 0 이상 정수여야 함" in m for _, _, m in R["s7"]["issues"]))

    def test_kpi_values_show_unit(self):
        vals = re.findall(r"<div class='v'>(.*?)</div>", first_screen(render(self.R, "ceo")))
        self.assertEqual(len(vals), 4)
        for v in vals:
            self.assertIn("백만원", v)


class TestCeoRulesEverywhere(unittest.TestCase):
    """대표용 규칙(금지어 없음·숫자 동일·대조 일치)을 샘플과 이 계획의 모든 탐침 입력에서 확인한다 (REP-02)."""

    def blank_balance(self, account):
        def mutate(rows):
            for r in rows[1:]:
                if r[0] == "2026-11-02" and r[1] == account:
                    r[3] = ""
        return probe_folder(self, "계좌잔액.csv", mutate)

    def setting(self, edit):
        def mutate(rows):
            for r in rows[1:]:
                if r[0] in edit:
                    r[1] = edit[r[0]]
        return probe_folder(self, "설정.csv", mutate)

    def test_no_interpretation_and_same_numbers_across_inputs(self):
        def blank_vat(rows):
            for r in rows[1:]:
                if r[2] == "사운드랩":
                    r[5] = ""
        extra = [["2026-11-20", "지급", "", "추정", "거래처미지급", "", "디자인스튜디오", "청구서", "추가 청구 금액 미정"],
                 ["2026-10-30", "지급", "5,000,000", "확정", "거래처미지급", "", "인쇄소", "청구서", "기한 경과"],
                 ["2026-10-31", "지급", "", "확정", "거래처미지급", "", "현수막", "청구서", "금액 미정"]]
        inputs = (
            ("sample weekly", lambda: (SAMPLE, "weekly", ASOF)),
            ("sample monthly", lambda: (SAMPLE, "monthly", dt.date(2026, 10, 31))),
            ("blank 운영계좌", lambda: (self.blank_balance("운영계좌"), "weekly", ASOF)),
            ("blank 프로젝트계좌", lambda: (self.blank_balance("프로젝트계좌"), "weekly", ASOF)),
            ("unknown and past-due rows", lambda: (
                probe_folder(self, "자금일정.csv", lambda rows: rows.extend(extra)), "weekly", ASOF)),
            ("blank 사운드랩 부가세", lambda: (probe_folder(self, "프로젝트집행.csv", blank_vat), "weekly", ASOF)),
            ("settings commas and abc", lambda: (
                self.setting({"위험_최소보유현금": "50,000,000", "위험_예산초과율": "abc"}), "weekly", ASOF)),
            ("blank threshold", lambda: (self.setting({"위험_최소보유현금": ""}), "weekly", ASOF)),
        )
        for name, make in inputs:
            with self.subTest(name):
                folder, kind, asof = make()
                check_editions(self, compute(load(folder), kind, asof))


if __name__ == "__main__":
    unittest.main()
