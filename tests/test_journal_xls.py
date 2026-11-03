"""WEHAGO SmartA 분개장 인쇄 저장 파일(.xls)도 읽는다 (D-56). 합성 자료만 쓴다.

인쇄 모양: 제목·'회사명'·'기 간 : YYYY년 MM월 DD일 ~ …' 줄, 머리글 '일자 | 전표번호 | 계정코드 | 계정과목 | 적요 | 차변 | 대변 | 구분 |
거래처코드 | 거래처명 | …', 일자는 'MM/DD'. 쪽마다 회사명·머리글이 되풀이되고 끝에 '합 계' 줄.
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

from ceo_report import wehago  # noqa: E402
import xls_fixture as X  # noqa: E402
from test_wehago import FAKE_JOURNAL, write_fake_books  # noqa: E402

HEAD = ["일자", "전표\n번호", "계정\n코드", "계정과목", "적요", "차변", "대변", "구분", "거래처\n코드", "거래처명",
        "부서\n코드", "부서 명", "프로\n젝트", "프로젝트명", "유형"]


def print_journal(journal, start=dt.date(2026, 1, 1), end=dt.date(2026, 10, 31), per_page=4):
    """FAKE_JOURNAL 꼴(첫 칸 엑셀 일련번호) 장부 -> 인쇄 모양 행 목록."""
    width = len(HEAD)
    period = "기 간  : %d년 %02d월 %02d일 ~ %d년 %02d월 %02d일" % (start.year, start.month, start.day,
                                                          end.year, end.month, end.day)
    rows = [[""] * 11 + ["분개장"] + [""] * (width - 12), [""] * width]
    body = []
    for r in journal:
        d = dt.date(1899, 12, 30) + dt.timedelta(days=int(r[0]))
        debit = float(r[5]) if r[5] not in (None, "") else ""
        credit = float(r[6]) if r[6] not in (None, "") else ""
        body.append(["%02d/%02d" % (d.month, d.day), str(r[1]).zfill(5), r[3], r[4], r[9], debit, credit,
                     "차변" if debit != "" else "대변", r[8], r[7], "", "", "", "", "일반전표"])
    for i in range(0, len(body), per_page):
        rows.append(["회사명  :  가상회사", period] + [""] * (width - 2))
        rows.append(HEAD)
        rows.extend(body[i:i + per_page])
        rows.append([""] * width)
    total_d = sum(r[5] for r in body if r[5] != "")
    total_c = sum(r[6] for r in body if r[6] != "")
    rows.append(["합 계", "", "", "", "", total_d, total_c] + [""] * (width - 7))
    return rows


def write_print_journal(folder, name, journal=FAKE_JOURNAL, **kw):
    strings = []
    return X.write_xls(os.path.join(folder, name), X.grid_records(print_journal(journal, **kw), strings), strings)


def keyed(lines):
    return [(x["date"], x["no"].lstrip("0"), x["account_code"], x["account"], x["debit"], x["credit"], x["vendor"], x["memo"])
            for x in lines]


class TestJournalXls(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def test_print_file_reads_like_xlsx(self):
        ref = os.path.join(self.dir, "ref")
        write_fake_books(ref)
        want = wehago.load_books(ref, dt.date(2026, 11, 2), None)
        got_dir = os.path.join(self.dir, "got")
        write_fake_books(got_dir, drop=("분개장",))
        write_print_journal(got_dir, "261031 분개장.xls")
        got = wehago.load_books(got_dir, dt.date(2026, 11, 2), None)
        self.assertEqual(got.state, "ok", got.reason)
        self.assertEqual(keyed(got.journal), keyed(want.journal))
        self.assertEqual(got.files["분개장"]["name"], "261031 분개장.xls")
        self.assertEqual(got.files["분개장"]["file_date"], dt.date(2026, 10, 31))

    def test_newer_xls_beats_older_xlsx(self):
        write_fake_books(self.dir, stamp="20261013")
        write_print_journal(self.dir, "261103 분개장.xls")
        books = wehago.load_books(self.dir, dt.date(2026, 11, 3), None)
        self.assertEqual(books.files["분개장"]["name"], "261103 분개장.xls")

    def test_year_from_period_and_crossing(self):
        rows = [[dt.date(2026, 12, 30), 1, "대체", "83100", "지급수수료(판)", 1000, None, "가", "V1", "a"],
                [dt.date(2027, 1, 2), 2, "대체", "83100", "지급수수료(판)", 2000, None, "나", "V2", "b"]]
        journal = [[(r[0] - dt.date(1899, 12, 30)).days] + r[1:] for r in rows]
        path = write_print_journal(self.dir, "270105 분개장.xls", journal, start=dt.date(2026, 7, 1),
                                   end=dt.date(2027, 1, 5))
        lines, info = wehago.read_book(path, "분개장", dt.date(2027, 1, 5))
        self.assertEqual([x["date"] for x in lines], [dt.date(2026, 12, 30), dt.date(2027, 1, 2)])
        self.assertEqual(info["undated"], 0)

    def test_not_a_journal_print(self):
        strings = []
        path = X.write_xls(os.path.join(self.dir, "261103 분개장.xls"),
                           X.grid_records([["아무 표"], ["가", 1.0]], strings), strings)
        books = wehago.load_books(self.dir, dt.date(2026, 11, 3), None)
        self.assertNotEqual(books.state, "ok")
        self.assertIn("261103 분개장.xls", books.files["분개장"].get("error", "") + books.reason)
        self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
