"""2차 전수조사 제안 24 (2026-11-18): 크롬 확장 보강 — 조회 기간 알림(P24·P25), 자금계획 지난 3달(P26), 사번 수 확인(P28).
확장은 실제 위하고 없이 돌릴 수 없어, 날짜·기간을 정하는 함수만 node 로 돌려 본다."""
import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BG = os.path.join(ROOT, "chrome_extension", "background.js")
JS = r"""
const fs = require('fs'); const src = fs.readFileSync(process.argv[1], 'utf8');
const grab = (name) => { const i = src.indexOf('function ' + name + '('); let d = 0, k = src.indexOf('{', src.indexOf(')', i));
  for (let j = k; ; j++) { if (src[j] == '{') d++; if (src[j] == '}') { d--; if (!d) return src.slice(i, j + 1); } } };
const past = +src.match(/const PAST_MONTHS = (\d+);/)[1];
eval('const pad = (n) => String(n).padStart(2, "0"); const PAST_MONTHS = ' + past + ';' + grab('periodWarn') + grab('planMonths') + `
const d = new Date(2026, 10, 18);
console.log(JSON.stringify({
  ok: periodWarn({start_date: "20260101", end_date: "20261118"}, 2026, d),
  short: periodWarn({start_date: "20260101", end_date: "20261031"}, 2026, d),
  wrongYear: periodWarn({start_date: "20250101", end_date: "20251231"}, 2026, d),
  lastYear: periodWarn({start_date: "20250101", end_date: "20251231"}, 2025, d),
  lastPart: periodWarn({start_date: "20250101", end_date: "20250630"}, 2025, d),
  months: planMonths(3, d), jan: planMonths(3, new Date(2027, 0, 5))}));`);
"""


@unittest.skipUnless(shutil.which("node"), "node 없음")
class TestExtensionDates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run(["node", "-e", JS, BG], check=True, stdout=subprocess.PIPE).stdout.decode("utf-8")
        cls.got = json.loads(out)

    def test_period_warnings(self):
        g = self.got
        self.assertEqual(g["ok"], "")
        self.assertIn("2026-10-31까지", g["short"])
        self.assertIn("2025년 화면 것을 받음", g["wrongYear"])
        self.assertEqual(g["lastYear"], "")
        self.assertIn("1년 전체가 아닙니다", g["lastPart"])

    def test_plan_takes_three_past_months(self):
        self.assertEqual(self.got["months"], {"2026": ["202608", "202609", "202610", "202611", "202612"], "2027": ["202701"]})
        self.assertEqual(self.got["jan"], {"2026": ["202610", "202611", "202612"], "2027": ["202701", "202702", "202703"]})


class TestExtensionText(unittest.TestCase):
    def read(self, name):
        with open(os.path.join(ROOT, "chrome_extension", name), encoding="utf-8") as f:
            return f.read()

    def test_books_use_pc_year_and_last_year_journal_in_q1(self):
        bg = self.read("background.js")
        self.assertNotIn("yminsa=(\\d{4})/) || [])[1]) || new Date().getFullYear()", bg)   # 탭의 해를 '올해'로 보지 않는다 (P25)
        self.assertIn('steps.push(["지난해 분개장", () => collectJournal(true)])', bg)        # 1차 D5

    def test_employee_count_check(self):
        self.assertIn("resp.length !== n || codes.size !== n", self.read("bridge.js"))        # P28


if __name__ == "__main__":
    unittest.main()
