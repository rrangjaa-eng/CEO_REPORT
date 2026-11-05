import json
import os
import tempfile
import unittest

from ceo_report import fundplan

COLS = ["date", "yn_inout", "cd_fitem", "nm_fitem", "cd_trade", "nm_trade", "mn_fplan", "rmk_fplan", "str_refer", "da_fplan"]


def doc(rows, done, frm="20261101", to="20261231", taken="2026-11-05 10:00:00"):
    return {"종류": "자금계획", "형식": 1, "수집시각": taken, "회사": "주식회사 플랜트8",
            "기간": {"from": frm, "to": to, "months": 2}, "조회한달": done, "오류": [], "줄수": len(rows), "열": COLS, "줄": rows}


def days(y, m, n):
    return ["%d%02d" % (y, m)]


ROWS = [["20261120", "지급", "102", "미지급금 지급", "0000001425", "주식회사 스탯트라", 8141040, "매입 - ...", "매입매출", "20"],
        ["20261120", "입금", "601", "외상대금 회수", "0000000125", "버카다코리아 유한회사", 32711800, "매출 - ...", "매입매출", "20"],
        ["20261204", "지급", "102", "미지급금 지급", "0000000236", "주식회사 펀미디어", 4015000, "매입 - ...", "매입매출", "4"]]


class AutoPlanTest(unittest.TestCase):
    def write(self, folder, name, d):
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)

    def test_full_months(self):
        with tempfile.TemporaryDirectory() as t:
            self.write(t, "261105 자금계획 자동수집.json", doc(ROWS, days(2026, 11, 30) + days(2026, 12, 31)))
            res = fundplan.load(t)
        self.assertEqual([m[0] for m in res["months"]], ["2026-11", "2026-12"])
        self.assertEqual(len(res["rows"]), 3)
        r = res["rows"][0]
        self.assertEqual((r["예정일"], r["입출금"], r["거래처코드"], r["금액"], r["자료일"]), ("2026-11-20", "입금", "000125", 32711800, "2026-11-05"))
        self.assertEqual(res["unused"], [])

    def test_partial_month_not_used(self):
        with tempfile.TemporaryDirectory() as t:
            self.write(t, "261105 자금계획 자동수집.json", doc(ROWS, days(2026, 11, 30)))
            res = fundplan.load(t)
        self.assertEqual([m[0] for m in res["months"]], ["2026-11"])
        self.assertTrue(any("2026-12" in n and "받지 못함" in n for n in res["notes"]))

    def test_newer_auto_beats_older(self):
        with tempfile.TemporaryDirectory() as t:
            self.write(t, "261103 자금계획 자동수집.json", doc(ROWS[:1], days(2026, 11, 30), to="20261130", taken="2026-11-03 09:00:00"))
            self.write(t, "261105 자금계획 자동수집.json", doc(ROWS[:2], days(2026, 11, 30), to="20261130"))
            res = fundplan.load(t)
        self.assertEqual(len(res["rows"]), 2)
        self.assertEqual(res["unused"], ["261103 자금계획 자동수집.json"])

    def test_bad_file(self):
        with tempfile.TemporaryDirectory() as t:
            self.write(t, "261105 자금계획 자동수집.json", {"종류": "분개장"})
            res = fundplan.load(t)
        self.assertEqual(res["rows"], [])
        self.assertEqual(res["unused"], ["261105 자금계획 자동수집.json"])


if __name__ == "__main__":
    unittest.main()
