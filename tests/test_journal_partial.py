"""분개장 부분 내려받기 (사용자 2026-11-05: 한두 건 고칠 때마다 전체를 다시 받기 번거로움). 합성 자료만 쓴다.

가장 새 분개장의 '기 간' 안 날짜는 그 파일만, 그 밖의 같은 해 날짜는 이전 파일에서 가져온다.
"""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from ceo_report import app, wehago  # noqa: E402
import xls_fixture as X  # noqa: E402
from test_journal_only import FULL_HEAD  # noqa: E402

ASOF = dt.date(2026, 11, 6)


def line(day, no, amount, memo, vendor="가상거래처"):
    return [(day, no, "81300", "접대비(판)", memo, float(amount), "", vendor, "", "매입전표"),
            (day, no, "25300", "미지급금", memo, "", float(amount), vendor, "", "매입전표")]


def write(folder, name, period, lines):
    width = len(FULL_HEAD)
    col = dict((h.replace("\n", "").replace(" ", ""), i) for i, h in enumerate(FULL_HEAD))
    rows = [["분개장"] + [""] * (width - 1), ["회사명  :  가상회사", "기 간  : %s" % period] + [""] * (width - 2), FULL_HEAD]
    for day, no, code, acct, memo, dr, cr, vendor, proj, kind in lines:
        r = [""] * width
        r[col["일자"]], r[col["전표번호"]], r[col["계정코드"]], r[col["계정과목"]], r[col["적요"]] = day, no, code, acct, memo
        r[col["차변"]], r[col["대변"]], r[col["거래처명"]], r[col["프로젝트명"]], r[col["유형"]] = dr, cr, vendor, proj, kind
        r[col["거래처코드"]] = "00001"
        rows.append(r)
    rows.append(["합 계"] + [""] * (width - 1))
    strings = []
    X.write_xls(os.path.join(folder, name), X.grid_records(rows, strings), strings)


FULL = "2026년 01월 01일 ~ 2026년 11월 04일"
NOV = "2026년 11월 01일 ~ 2026년 11월 05일"


class TestPartial(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def memos(self, b):
        return sorted((r["date"].isoformat(), r["memo"]) for r in b.journal if r["account_code"] == "81300")

    def test_new_period_replaces_only_its_dates(self):
        write(self.dir, "261104 분개장.xls", FULL, line("10/10", "1", 100, "시월") + line("11/02", "2", 200, "고치기 전")
              + line("11/03", "3", 300, "지운 전표"))
        write(self.dir, "261105 분개장_11월.xls", NOV, line("11/02", "2", 250, "고친 뒤") + line("11/05", "4", 400, "새 전표"))
        b = wehago.load_books(self.dir, ASOF, None)
        self.assertEqual(b.state, "ok", b.reason)
        self.assertEqual(self.memos(b), [("2026-10-10", "시월"), ("2026-11-02", "고친 뒤"), ("2026-11-05", "새 전표")])
        self.assertEqual(b.files["분개장"]["layers"], ["261104 분개장.xls"])
        self.assertTrue(any("이전 파일" in n for n in b.notes), b.notes)
        self.assertEqual(b.unused, [])

    def test_full_newest_file_ignores_older(self):
        write(self.dir, "261103 분개장.xls", "2026년 01월 01일 ~ 2026년 11월 03일", line("10/10", "1", 100, "옛"))
        write(self.dir, "261104 분개장.xls", FULL, line("10/11", "1", 100, "새"))
        b = wehago.load_books(self.dir, ASOF, None)
        self.assertEqual(self.memos(b), [("2026-10-11", "새")])
        self.assertEqual(b.files["분개장"]["layers"], [])
        self.assertEqual(b.unused, ["261103 분개장.xls"])

    def test_gap_between_files_is_flagged(self):
        write(self.dir, "261020 분개장.xls", "2026년 01월 01일 ~ 2026년 10월 20일", line("10/10", "1", 100, "시월"))
        write(self.dir, "261105 분개장_11월.xls", NOV, line("11/02", "2", 200, "십일월"))
        b = wehago.load_books(self.dir, ASOF, None)
        self.assertEqual(self.memos(b), [("2026-10-10", "시월"), ("2026-11-02", "십일월")])
        self.assertTrue(any("2026-10-21~2026-10-31" in n and n.startswith("[확인]") for n in b.notes), b.notes)

    def test_old_files_keeps_layer_base(self):
        write(self.dir, "261103 분개장.xls", "2026년 01월 01일 ~ 2026년 11월 03일", line("10/10", "1", 100, "옛"))
        write(self.dir, "261104 분개장.xls", FULL, line("10/10", "1", 100, "시월"))
        write(self.dir, "261105 분개장_11월.xls", NOV, line("11/02", "2", 250, "고친 뒤"))
        moved = [n for n, _ in app.old_files(self.dir, ASOF)]
        self.assertEqual(moved, ["261103 분개장.xls"])


if __name__ == "__main__":
    unittest.main()
