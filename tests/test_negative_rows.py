"""장부 원가 줄의 음수(취소·감액 전표)는 부호 그대로 (실제 자료 2026-11-04: 음수 104줄이 지급으로 바뀌어 원가가 커짐).

손으로 넣은 줄의 음수는 예전처럼 절댓값 + 입력 확인 알림 (지급을 줄이지 않음).
"""
import csv
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report.data import load  # noqa: E402
from sample_input import SAMPLE, refresh  # noqa: E402


class TestNegativeRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        refresh()
        path = os.path.join(SAMPLE, "프로젝트집행.csv")
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        head = rows[0]

        def add(basis, supply):
            row = dict((h, "") for h in head)
            row.update({"항목": "취소", "거래처": "가상거래처", "상태": "지급완료", "공급가액": supply, "부가세": "-10000",
                        "일자": "2026-10-15", "확정여부": "확정", "근거": basis})
            rows.append([row[h] for h in head])
        add("WEHAGO 2026-10-15 전표 50077", "-100000")
        add("손으로 넣은 감액", "-200000")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(rows)
        cls.d = load(SAMPLE)

    def test_book_row_keeps_sign(self):
        e = [x for x in self.d.execs if x["basis"].startswith("WEHAGO 2026-10-15 전표 50077")][0]
        self.assertEqual((e["supply"], e["vat"]), (-100000, -10000))

    def test_hand_row_still_positive(self):
        e = [x for x in self.d.execs if x["basis"] == "손으로 넣은 감액"][0]
        self.assertEqual(e["supply"], 200000)


if __name__ == "__main__":
    unittest.main()
