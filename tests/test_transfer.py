"""신한 대량이체 파일 (사용자 2026-11-03). 가상 거래처·가상 계좌만."""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from ceo_report import transfer, wehago  # noqa: E402

D = dt.date


def ev(day, amount, desc, cat="거래처미지급", source="자금일정", project="", firm=True):
    return {"date": day, "io": "out", "amount": amount, "desc": desc, "cat": cat, "source": source, "project": project,
            "firm": firm, "basis": ""}


ACC = {"가상무대": {"거래처": "(주)가상무대", "은행": "신한은행", "계좌번호": "100-000-000001", "예금주": "가상무대"},
       "가상조명": {"거래처": "가상조명", "은행": "농협중앙회", "계좌번호": "3010000000002", "예금주": "가상조명"},
       "가상음향": {"거래처": "가상음향", "은행": "모름은행", "계좌번호": "1", "예금주": "가상음향"}}


class TestBankCode(unittest.TestCase):
    def test_names_and_aliases(self):
        self.assertEqual(transfer.bank_code("신한은행"), "088")
        self.assertEqual(transfer.bank_code("KB국민"), "004")
        self.assertEqual(transfer.bank_code("농협중앙회"), "011")
        self.assertEqual(transfer.bank_code("088"), "088")
        self.assertIsNone(transfer.bank_code("모름은행"))
        self.assertIsNone(transfer.bank_code("999"))


class TestBuild(unittest.TestCase):
    def events(self):
        return [ev(D(2026, 11, 4), 3_000_000, "가상무대", project="P26201"),
                ev(D(2026, 11, 5), 2_000_000, "(주)가상무대", project="P26203"),   # 같은 거래처는 한 줄
                ev(D(2026, 11, 5), 1_500_000, "가상조명"),
                ev(D(2026, 11, 6), 700_000, "가상음향"),                            # 은행 코드 없음
                ev(D(2026, 11, 6), 900_000, "가상없음"),                            # 계좌 정보 없음
                ev(D(2026, 11, 5), 18_000_000, "급여 2026년 10월분", cat="급여 (장부 계산)", source="세금예상"),
                ev(D(2026, 11, 6), 4_000_000, "신한카드", cat="카드대금"),
                ev(D(2026, 11, 6), 800_000, "건물관리", cat="임차료"),
                ev(D(2026, 11, 6), 9_000_000, "가상무대", cat="프로젝트 남은 예산"),
                ev(D(2026, 11, 20), 5_000_000, "가상조명")]                         # 기간 밖

    def test_rows_blocked_and_regular_left_out(self):
        rows, blocked, skipped = transfer.build(self.events(), ACC, D(2026, 11, 1), D(2026, 11, 7))
        self.assertEqual(rows, [["088", "100000000001", "가상무대", "5000000", "가상무대", "", "", "P26201 P26203", "가상무대"],
                                ["011", "3010000000002", "가상조명", "1500000", "가상조명", "", "", "가상조명", "가상조명"]])
        self.assertEqual(blocked, [("가상없음", 900_000, "계좌 정보 없음"), ("가상음향", 700_000, "은행 코드 없음 (모름은행)")])
        self.assertEqual(skipped, 3)

    def test_file_has_the_bank_sheet_and_keeps_leading_zero(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "x.xlsx")
        rows, _, _ = transfer.build(self.events(), ACC, D(2026, 11, 1), D(2026, 11, 7))
        transfer.write_xlsx(path, rows)
        got = wehago.read_xlsx(path)
        grid = got[0] if isinstance(got, tuple) else got
        self.assertEqual([str(c) for c in grid[0]], transfer.HEADER)
        self.assertEqual(str(grid[1][0]), "088")
        import zipfile
        with zipfile.ZipFile(path) as z:
            self.assertIn('name="입력정보"', z.read("xl/workbook.xml").decode("utf-8"))

    def test_cut_by_cp949_bytes(self):
        self.assertEqual(transfer.cut("가나다라마바사아자차", 14), "가나다라마바사")
        self.assertEqual(transfer.nbytes("A가"), 3)


class TestMakeFile(unittest.TestCase):
    def test_sample_input_with_account_file(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        inp = os.path.join(tmp, "입력")
        shutil.copytree(os.path.join(os.path.dirname(HERE), "입력양식", "샘플"), inp)
        with open(os.path.join(inp, transfer.ACCOUNT_FILE), "w", encoding="utf-8-sig") as f:
            f.write("거래처,은행,계좌번호,예금주\n디자인스튜디오,우리은행,1002-000-000003,가상디자인\n")
        lines = []
        path = transfer.make_file(inp, os.path.join(tmp, "출력"), D(2026, 11, 1), D(2026, 11, 30), lines.append, asof=D(2026, 10, 31))
        self.assertTrue(path and os.path.exists(path), lines)
        grid = wehago.read_xlsx(path)
        grid = grid[0] if isinstance(grid, tuple) else grid
        self.assertIn(["020", "1002000000003", "가상디자인", "3300000"], [[str(c) for c in r[:4]] for r in grid[1:]])
        self.assertTrue(any("정기 지급" in ln for ln in lines))

    def test_no_account_file_says_so_and_makes_nothing(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        lines = []
        inp = os.path.join(os.path.dirname(HERE), "입력양식", "샘플")
        self.assertIsNone(transfer.make_file(inp, os.path.join(tmp, "출력"), D(2026, 11, 1), D(2026, 11, 30), lines.append,
                                             asof=D(2026, 10, 31)))
        self.assertIn("거래처계좌.csv 없음", lines[0])
