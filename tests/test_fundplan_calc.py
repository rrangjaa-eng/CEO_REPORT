"""자금계획서 기준 일정 (D-55): 자금계획.csv 가 있으면 그 달의 일정은 자금계획서 줄로 바꾼다. 샘플 입력 복사본만 쓴다."""
import csv
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report import fundplan  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.data import load  # noqa: E402
from sample_input import SAMPLE, refresh  # noqa: E402

ASOF = dt.date(2026, 11, 2)
# (예정일, 입출금, 분류, 거래처, 금액, 상태)
PLAN = [
    ("2026-11-06", "지급", "미지급금 지급", "전시제작사", 49500000, "예정"),        # 프로젝트집행 P26203 11/06 과 같은 건
    ("2026-11-20", "지급", "미지급금 지급", "(주)사운드랩", 44000000, "예정"),     # 프로젝트집행 P26201 11/13 → 11/20
    ("2026-11-02", "지급", "미지급금 지급", "가상상사", 990000, "예정일 지남"),     # 다음 금요일 11/06 로
    ("2026-11-01", "입금", "외상대금 회수", "가상고객", 5000000, "예정일 지남"),    # 입금 지연: 추정, 지난 날짜
    ("2026-11-09", "지급", "일반경비", "디자인스튜디오", 3300000, "이미 지급"),    # 자금일정 11/10 과 같은 건, 이미 나감
    ("2026-11-27", "지급", "미지급금 지급", "신규업체", 7000000, "예정"),
]


def write_plan_csv(folder, rows=PLAN, stamp="2026-11-02"):
    with open(os.path.join(folder, "자금계획.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(fundplan.COLUMNS)
        for due, io, cat, vendor, amount, state in rows:
            w.writerow([due, io, cat, vendor, "", amount, due[:7], stamp, "f.xls", state, ""])


class TestPlanInCalc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        refresh()

    def folder(self, **kw):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        folder = os.path.join(tmp, "입력")
        shutil.copytree(SAMPLE, folder)
        write_plan_csv(folder, **kw)
        return folder

    def test_without_file_nothing_changes(self):
        R = compute(load(SAMPLE), "weekly", ASOF)
        self.assertIsNone(R["fundplan"])
        self.assertFalse(any(e["source"] == "자금계획서" for e in R["events"]))

    def test_plan_replaces_matching_events(self):
        R = compute(load(self.folder()), "weekly", ASOF)
        F, ev = R["fundplan"], R["events"]
        self.assertTrue(F["used"])
        plan = [e for e in ev if e["source"] == "자금계획서"]
        self.assertEqual(sorted((e["date"], e["desc"], e["amount"], e["firm"]) for e in plan), [
            (dt.date(2026, 11, 1), "가상고객", 5000000, False),
            (dt.date(2026, 11, 6), "가상상사", 990000, True),
            (dt.date(2026, 11, 6), "전시제작사", 49500000, True),
            (dt.date(2026, 11, 20), "(주)사운드랩", 44000000, True),
            (dt.date(2026, 11, 27), "신규업체", 7000000, True)])
        # 같은 건의 기존 일정은 빠지고, 프로젝트 번호는 이어받는다
        execs = [(e["desc"], e["amount"]) for e in ev if e["source"] == "프로젝트집행"]
        self.assertNotIn(("전시제작사", 49500000), execs)
        self.assertNotIn(("사운드랩", 44000000), execs)
        self.assertEqual(dict((e["desc"], e["project"]) for e in plan)["(주)사운드랩"], "P26201")
        # 이미 지급: 일정에 없고, 맞는 기존 자금일정도 빠진다
        self.assertFalse(any(e["desc"] == "디자인스튜디오" for e in ev))
        self.assertEqual([x["plan"]["vendor"] for x in F["done"]], ["디자인스튜디오"])
        self.assertEqual(len(F["matched"]), 2)
        self.assertEqual([e["desc"] for e in F["moved"]], ["가상상사"])
        self.assertEqual([e["desc"] for e in F["late_in"]], ["가상고객"])

    def test_unmatched_in_covered_month_is_kept_and_flagged(self):
        R = compute(load(self.folder()), "weekly", ASOF)
        missing = R["fundplan"]["missing"]
        names = set(e["desc"] for e in missing)
        self.assertIn("소프트웨어", names)          # 11월 자금일정
        self.assertIn("케이터링", names)            # 11월 프로젝트집행
        self.assertTrue(all(e["date"].month == 11 for e in missing))
        self.assertTrue(any(e["desc"] == "소프트웨어" and e["date"] == dt.date(2026, 11, 5) for e in R["events"]))
        # 12월 일정은 자금계획서가 없는 달: 알리지 않는다
        self.assertFalse(any(e["desc"] == "새 사무실 임대인" for e in missing))

    def test_week_totals_follow_the_plan(self):
        base = compute(load(SAMPLE), "weekly", ASOF)["s2"]["buckets"][0]
        got = compute(load(self.folder()), "weekly", ASOF)["s2"]["buckets"][0]
        # 1주차(11/3~11/9): 가상상사 990,000 더함. 전시제작사는 같은 날 같은 금액이라 그대로
        self.assertEqual(got["out_firm"] - base["out_firm"], 990000)

    def test_stale_plan_is_not_used(self):
        R = compute(load(self.folder(stamp="2026-10-20")), "weekly", ASOF)
        self.assertFalse(R["fundplan"]["used"])
        self.assertIn("기존 일정", R["fundplan"]["reason"])
        self.assertFalse(any(e["source"] == "자금계획서" for e in R["events"]))

    def test_bad_row_disables_plan(self):
        rows = PLAN + [("2026-11-30", "지급", "", "모름", "미확인", "예정")]
        R = compute(load(self.folder(rows=rows)), "weekly", ASOF)
        self.assertFalse(R["fundplan"]["used"])
        self.assertFalse(any(e["source"] == "자금계획서" for e in R["events"]))


if __name__ == "__main__":
    unittest.main()
