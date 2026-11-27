"""정답 예시(골든): 지금 프로그램이 golden/cases 의 기대값과 같은 숫자를 내는지, 규칙 표에 빈 칸이 없는지 확인한다.

기대값을 일부러 바꿨을 때만: python tools/golden/build.py <id> && python tools/golden/extract.py write <id>
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "golden"))
import extract  # noqa: E402

RRN = re.compile(r"\d{6}-?[1-4]\d{6}")
RULES = os.path.join(ROOT, "golden", "RULES.md")


def rule_rows():
    """RULES.md 표 줄 -> [(번호, 사례)]"""
    out = []
    with open(RULES, encoding="utf-8") as f:
        for ln in f:
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) >= 4 and re.match(r"^[DFU]\d+$", cells[0]):
                out.append((cells[0], cells[2]))
    return out


class TestGolden(unittest.TestCase):
    def test_there_are_cases(self):
        self.assertTrue(extract.case_dirs(), "golden/cases 에 사례가 없음")

    def test_every_case_matches(self):
        for d in extract.case_dirs():
            with self.subTest(case=os.path.basename(d)):
                self.assertEqual(extract.check(d), [])

    def test_expected_has_no_resident_number(self):
        for d in extract.case_dirs():
            for name in os.listdir(os.path.join(d, "expected")):
                with open(os.path.join(d, "expected", name), encoding="utf-8") as f:
                    self.assertIsNone(RRN.search(f.read()), "%s/%s" % (os.path.basename(d), name))

    def test_every_rule_has_a_case(self):
        ids = {os.path.basename(d) for d in extract.case_dirs()}
        rows = rule_rows()
        self.assertGreaterEqual(len(rows), 38)
        for rid, cases in rows:
            with self.subTest(rule=rid):
                named = [c.strip("` ") for c in cases.split(",") if c.strip("` ")]
                self.assertTrue(named, "%s: 사례 없음" % rid)
                for c in named:
                    self.assertIn(c, ids, "%s: 없는 사례 %s" % (rid, c))

    def test_every_case_names_its_rules(self):
        rows = dict(rule_rows())
        for d in extract.case_dirs():
            for rid in extract.load_case(d).get("rules", []):
                self.assertIn(rid, rows, "%s: RULES.md 에 없는 규칙 %s" % (os.path.basename(d), rid))


if __name__ == "__main__":
    unittest.main()
