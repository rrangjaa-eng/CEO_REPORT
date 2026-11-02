"""보고 규칙 테스트. 실행: python -m unittest discover -s tests"""
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
from ceo_report.util import num, date, read_csv, Issues  # noqa: E402

SAMPLE = os.path.join(ROOT, "입력")
ASOF = dt.date(2026, 11, 2)


def setUpModule():
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_sample.py")], check=True,
                   stdout=subprocess.DEVNULL)


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
        for word in ("위험", "해결방안", "권고", "우려", "추천"):
            self.assertNotIn(word, html, word)

    def test_same_numbers_in_both_versions(self):
        def numbers(html):
            html = re.sub(r"<h2 id='risk'>.*?</table>", "", html, flags=re.S)
            html = re.sub(r"<div class='note' style='margin-top:10px'>위험 항목.*?</div>", "", html, flags=re.S)
            html = re.sub(r"작성 \d{4}-\d{2}-\d{2} \d{2}:\d{2}", "", html)
            return re.findall(r"−?\d[\d,.]*", html)
        self.assertEqual(numbers(render(self.R, "ceo")), numbers(render(self.R, "mgmt")))

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


if __name__ == "__main__":
    unittest.main()
