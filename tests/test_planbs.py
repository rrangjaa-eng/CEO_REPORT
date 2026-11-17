"""기획본부용 재무상태표 (사용자 2026-11-17): 회사 전체 장부에서 영업외수익만 빼고, 노란 칸을 바꾸면 모두 다시 계산되는 엑셀."""
import csv
import datetime as dt
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import credit as K, planbs, xlsxw, corptax  # noqa: E402

D = dt.date


def ln(day, no, code, name, dr=0, cr=0):
    return {"date": day, "no": no, "sort": "일반전표", "account_code": code, "account": name,
            "debit": dr or None, "credit": cr or None, "vendor": "", "memo": ""}


def journal():
    j = [ln(D(2025, 1, 2), "1", "10300", "보통예금", dr=100_000_000), ln(D(2025, 1, 2), "1", "33100", "자본금", cr=20_000_000),
         ln(D(2025, 1, 2), "1", "37700", "미처분이익잉여금", cr=80_000_000),
         # 2025: 매출 5억, 원가 3억, 판관 1억, 이자수익 2백만, 지원금 1천만
         ln(D(2025, 5, 1), "2", "10300", "보통예금", dr=500_000_000), ln(D(2025, 5, 1), "2", "41200", "수입수수료", cr=500_000_000),
         ln(D(2025, 5, 2), "3", "53300", "외주용역비(도)", dr=300_000_000), ln(D(2025, 5, 2), "3", "10300", "보통예금", cr=300_000_000),
         ln(D(2025, 5, 3), "4", "81100", "복리후생비", dr=100_000_000), ln(D(2025, 5, 3), "4", "10300", "보통예금", cr=100_000_000),
         ln(D(2025, 6, 1), "5", "10300", "보통예금", dr=2_000_000), ln(D(2025, 6, 1), "5", "90100", "이자수익", cr=2_000_000),
         ln(D(2025, 6, 2), "6", "10300", "보통예금", dr=10_000_000), ln(D(2025, 6, 2), "6", "92200", "정부지원금수익", cr=10_000_000),
         # 2026: 매출 4억, 원가 2.5억, 판관 8천만, 이자수익 1백만, 잡이익 5백만, 이자비용 3백만, 감가상각 2백만, 대출 1억
         ln(D(2026, 2, 1), "7", "10800", "수입수수료미수금", dr=400_000_000), ln(D(2026, 2, 1), "7", "41200", "수입수수료", cr=400_000_000),
         ln(D(2026, 2, 2), "8", "53300", "외주용역비(도)", dr=250_000_000), ln(D(2026, 2, 2), "8", "25300", "미지급금", cr=250_000_000),
         ln(D(2026, 2, 3), "9", "81100", "복리후생비", dr=78_000_000), ln(D(2026, 2, 3), "9", "10300", "보통예금", cr=78_000_000),
         ln(D(2026, 3, 1), "10", "10300", "보통예금", dr=1_000_000), ln(D(2026, 3, 1), "10", "90100", "이자수익", cr=1_000_000),
         ln(D(2026, 3, 2), "11", "10300", "보통예금", dr=5_000_000), ln(D(2026, 3, 2), "11", "93000", "잡이익", cr=5_000_000),
         ln(D(2026, 3, 3), "12", "93100", "이자비용", dr=3_000_000), ln(D(2026, 3, 3), "12", "10300", "보통예금", cr=3_000_000),
         ln(D(2026, 3, 4), "13", "81800", "감가상각비", dr=2_000_000), ln(D(2026, 3, 4), "13", "20900", "감가상각누계액", cr=2_000_000),
         ln(D(2026, 3, 5), "14", "10300", "보통예금", dr=100_000_000), ln(D(2026, 3, 5), "14", "29300", "장기차입금", cr=100_000_000),
         ln(D(2026, 11, 3), "15", "10300", "보통예금", dr=7_000_000), ln(D(2026, 11, 3), "15", "90100", "이자수익", cr=7_000_000)]  # 기준 달 뒤 → 빠짐
    return j


def make_input():
    d = tempfile.mkdtemp()
    t = K.build_table(types.SimpleNamespace(state="ok", journal=journal()))
    with open(os.path.join(d, K.FILE), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, K.KEYS)
        w.writeheader()
        w.writerows(t.rows)
    with open(os.path.join(d, "부서비용.csv"), "w", encoding="utf-8-sig", newline="") as f:
        f.write("연월,부서,급여,판관비,인원,영업외수익,영업외비용\n2026-02,경영관리,\"5,000,000\",\"3,000,000\",1,0,0\n"
                "2026-03,플랜트8,\"4,000,000\",\"1,500,000\",1,0,0\n2026-12,경영관리,0,\"9,000,000\",1,0,0\n")
    return d


class TestPlanBS(unittest.TestCase):
    def setUp(self):
        self.d = make_input()
        self.C = planbs.compute(self.d, D(2026, 11, 17))   # 기준 달 = 10월

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_numbers(self):
        C = self.C
        self.assertEqual(C["ym"], "2026-10")
        self.assertEqual(C["X1"], 6_000_000)      # 이자 1백만 + 잡이익 5백만 (11월 7백만 빠짐)
        self.assertEqual(C["X0"], 12_000_000)     # 2025 이자 2백만 + 지원금 1천만
        P = C["P"]
        self.assertEqual((P["rev"], P["cogs"], P["sga"], P["nin"], P["nout"]), (400_000_000, 250_000_000, 80_000_000, 6_000_000, 3_000_000))
        # 세금 줄어드는 비율: 프로그램 법인세 계산과 같게
        base = P["pre"]
        t = planbs.tax_total(base, 2026, self.d) - planbs.tax_total(base - 6_000_000, 2026, self.d)
        self.assertEqual(C["T1"], t)
        self.assertAlmostEqual(C["rate1"], 0.11, places=3)   # 과세표준 2억 이하: 10% + 지방 1%
        self.assertAlmostEqual(C["rate0"], 0.099, places=3)  # 2025년: 9% + 0.9%

    def test_pay_like_accounts_left_out_of_dept_cost(self):
        # 퇴직급여 같은 급여성 계정은 부서 비용에서 뺀다 (팀장용과 같은 기준)
        with open(os.path.join(self.d, "부서계정비용.csv"), "w", encoding="utf-8-sig", newline="") as f:
            f.write("연월,부서,계정코드,계정과목,금액\n2026-02,경영관리,80600,퇴직급여(판),1000000\n2026-02,경영관리,81200,여비교통비,2000000\n")
        C = planbs.compute(self.d, D(2026, 11, 17))
        self.assertEqual(dict((x[0], x[1]) for x in C["over"])["경영관리 부서 비용 (급여 빼고)"], 2_000_000)

    def test_overstated_items(self):
        names = [x[0] for x in self.C["over"]]
        self.assertIn("경영관리 부서 비용 (급여 빼고)", names)
        self.assertEqual(dict((x[0], x[1]) for x in self.C["over"])["경영관리 부서 비용 (급여 빼고)"], 3_000_000)   # 12월·급여 빠짐
        self.assertTrue(any("감가상각" in n for n in names))
        self.assertTrue(any("이자비용" in n for n in names))
        self.assertTrue(any("법인세 예상" in n for n in names))
        self.assertFalse(any("정부지원금" in n for n in names))   # 올해 지원금 없음

    def test_workbook_balances_and_reacts(self):
        bk = planbs.build(self.C, "사용한 자료: 시험")
        cells = self.C["_cells"]
        for a in cells["check"]:
            self.assertEqual(bk.value(a), 0)
        cn, en = (bk.value(a) for a in cells["net"])
        ce, ee = (bk.value(a) for a in cells["equity"])
        g1 = self.C["X1"] - round(self.C["X1"] * round(self.C["rate1"], 4))
        g0 = self.C["X0"] - round(self.C["X0"] * round(self.C["rate0"], 4))
        self.assertEqual(cn - en, g1)
        self.assertEqual(ce - ee, g1 + g0)
        # 회사 전체 자본 = 장부 자산 − 부채 − 올해 법인세 예상
        L = K.load(self.d)
        B = K.balance_sheet(L, "2026-10")
        self.assertEqual(ce, B["equity"] - self.C["tax_all"])
        # 노란 칸 '뺄까요'를 모두 '아니오'로 → 차이 0
        sh = bk.sheets[0]
        for (r, c), (v, f, s) in list(sh.cells.items()):
            if v == "예" and s == "inc":
                sh.cells[(r, c)] = ("아니오", None, s)
        bk._memo = {}
        self.assertEqual(bk.value(cells["equity"][0]), bk.value(cells["equity"][1]))
        for a in cells["check"]:
            self.assertEqual(bk.value(a), 0)

    def test_write_file_and_libreoffice_agrees(self):
        out = tempfile.mkdtemp()
        try:
            path, bk = planbs.write(self.C, out, "사용한 자료: 시험")
            self.assertTrue(path.endswith("2026-11-17_기획본부_재무상태표.xlsx"))
            with zipfile.ZipFile(path) as z:
                self.assertIn("xl/worksheets/sheet1.xml", z.namelist())
                self.assertIn('fullCalcOnLoad="1"', z.read("xl/workbook.xml").decode())
            line = planbs.summary(self.C, bk)
            self.assertIn("기획본부 기준", line)
            soffice = shutil.which("soffice")
            if not soffice:
                self.skipTest("LibreOffice 없음")
            csv_dir = tempfile.mkdtemp()
            subprocess.run([soffice, "--headless", "--convert-to", "csv:Text - txt - csv (StarCalc):44,34,76", "--outdir", csv_dir, path],
                           check=True, capture_output=True, timeout=120)
            with open(os.path.join(csv_dir, os.path.basename(path)[:-5] + ".csv"), encoding="utf-8") as fh:
                rows = list(csv.reader(fh))
            sh = bk.sheets[0]
            bad = []
            for (r, c), (v, f, s) in sh.cells.items():
                if not f:
                    continue
                mine = bk.value(xlsxw.addr(r, c))
                got = rows[r - 1][c - 1].replace(",", "")
                if isinstance(mine, (int, float)) and abs(float(got or 0) - mine) > 0.5:
                    bad.append((xlsxw.addr(r, c), f, mine, got))
            self.assertEqual(bad, [])
            shutil.rmtree(csv_dir, ignore_errors=True)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_no_books(self):
        d = tempfile.mkdtemp()
        try:
            self.assertIn("error", planbs.compute(d, D(2026, 11, 17)))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestRun(unittest.TestCase):
    def test_task_and_cli(self):
        from ceo_report import app, gate
        import types as _t
        paths = _t.SimpleNamespace(input="입력", output="출력")
        self.assertEqual(app.task_argv("기획본부", paths, asof="2026-11-17"),
                         ("보고서", ["기획본부", "--기준일", "2026-11-17", "--입력", "입력", "--출력", "출력"]))
        import 보고서
        d, out = make_input(), tempfile.mkdtemp()
        old = os.environ.get(gate.TEST_OFF)
        try:
            os.environ[gate.TEST_OFF] = "1"
            self.assertEqual(보고서.main(["기획본부", "--기준일", "2026-11-17", "--입력", d, "--출력", out]), 0)
            self.assertTrue(os.path.exists(os.path.join(out, "기획본부", "2026-11-17_기획본부_재무상태표.xlsx")))
            from ceo_report import digest
            self.assertEqual(digest.find_docs(out, D(2026, 11, 30))["planbs"], "기획본부/2026-11-17_기획본부_재무상태표.xlsx")
        finally:
            if old is None:
                os.environ.pop(gate.TEST_OFF, None)
            else:
                os.environ[gate.TEST_OFF] = old
            shutil.rmtree(d, ignore_errors=True)
            shutil.rmtree(out, ignore_errors=True)

    def test_gate_blocks_without_fresh_books(self):
        import 보고서
        from ceo_report import gate
        d, out = make_input(), tempfile.mkdtemp()
        old = os.environ.pop(gate.TEST_OFF, None)
        try:
            self.assertEqual(보고서.main(["기획본부", "--기준일", "2026-11-17", "--입력", d, "--출력", out]), 2)
            self.assertFalse(os.path.exists(os.path.join(out, "기획본부")))
        finally:
            if old is not None:
                os.environ[gate.TEST_OFF] = old
            shutil.rmtree(d, ignore_errors=True)
            shutil.rmtree(out, ignore_errors=True)


class TestFormula(unittest.TestCase):
    def test_eval(self):
        bk = xlsxw.Book()
        sh = bk.sheet("t")
        sh.set(1, 1, 10)
        sh.set(2, 1, 20)
        sh.set(1, 2, "예")
        sh.set(2, 2, "아니오")
        sh.set(3, 1, f='SUMIF(B1:B2,"예",A1:A2)')
        sh.set(4, 1, f="ROUND(A2*0.115,0)-(A1+-A3)")
        sh.set(5, 1, f='IF(A3>5,"큼","작음")')
        self.assertEqual(bk.value("A3"), 10)
        self.assertEqual(bk.value("A4"), 2)
        self.assertEqual(bk.value("A5"), "큼")


if __name__ == "__main__":
    unittest.main()
