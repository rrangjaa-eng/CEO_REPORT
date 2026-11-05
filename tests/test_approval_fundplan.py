"""승인 검토 화면의 자금계획서 기준 (D-55): 지급요청과 같은 자금계획서 줄이 있으면 그 지급예정일을 쓰고 일정에 두 번 넣지 않는다."""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from ceo_report import approval, data, snapshot  # noqa: E402
from sample_input import SAMPLE, refresh  # noqa: E402
from test_approval import write_fake_snapshot  # noqa: E402
from test_fundplan_calc import write_plan_csv  # noqa: E402

ASOF = dt.date(2026, 11, 2)
NOW = dt.datetime(2026, 11, 2, 0, 0)
PLAN = [
    ("2026-11-20", "지급", "미지급금 지급", "가상음향", 44000000, "예정"),   # 요청 1201 (대기, 11/13) → 11/20
    ("2026-11-06", "지급", "미지급금 지급", "가상부스", 49500000, "예정"),   # 요청 5109 (승인, 11/06)
]


class TestApprovalPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        refresh()

    def build(self, plan=True):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        folder = os.path.join(tmp, "입력")
        shutil.copytree(SAMPLE, folder)
        if plan:
            write_plan_csv(folder, rows=PLAN)
        snap = write_fake_snapshot(os.path.join(tmp, "수집"))
        return approval.build(data.load(folder), snapshot.read_snapshot(snap), ASOF, NOW)

    def req(self, A, no):
        return [rq for rq in A["requests_all"] if rq["번호"] == no][0]

    def test_request_takes_plan_date(self):
        A = self.build()
        rq = self.req(A, "1201")
        self.assertEqual(rq["date"], dt.date(2026, 11, 20))
        self.assertIn("자금계획서", rq["rule"])
        self.assertEqual(sorted(e["desc"] for e in A["plan_dup"]), ["가상부스", "가상음향"])

    def test_requests_not_in_plan_are_marked(self):
        A = self.build()
        absent = sorted(rq["번호"] for rq in A["plan_absent"])
        self.assertIn("5108", absent)
        self.assertNotIn("1201", absent)
        self.assertEqual(self.req(A, "5108")["plan_note"], "WEHAGO 자금계획서에 없음")
        self.assertTrue(any("WEHAGO 자금계획서에 없는 지급요청" in n for n in A["notes"]))

    def test_no_double_count(self):
        plain, A = self.build(plan=False), self.build()
        total = lambda X: sum(X["data"]["base_out"]) + sum(r["amount"] for r in X["data"]["requests"])
        self.assertEqual(total(A), total(plain))

    def test_screen_says_it(self):
        from ceo_report.approval_render import render_approval
        page = render_approval(self.build(), True)
        self.assertIn("일정 기준: WEHAGO 자금계획서 (자료일 2026-11-02, 2026-11)", page)
        self.assertIn("WEHAGO 자금계획서 지급예정일", page)
        self.assertIn("WEHAGO 자금계획서에 없음", page)


if __name__ == "__main__":
    unittest.main()
