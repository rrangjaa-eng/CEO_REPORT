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


def inputs(bk):
    return [x for x in bk.sheets if x.name == planbs.S_IN][0]


def set_all(bk, style, value):
    sh = inputs(bk)
    for (r, c), (v, f, s) in list(sh.cells.items()):
        if s == style:
            sh.cells[(r, c)] = (value, None, s)
    bk._memo = {}


def put(bk, label, col, value):
    sh = inputs(bk)
    row = [r for (r, c), (v, f, s) in sh.cells.items() if c == 2 and str(v).lstrip("★ ").startswith(label)][0]
    v, f, s = sh.cells[(row, col)]
    sh.cells[(row, col)] = (value, None, s)
    bk._memo = {}


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
        self.assertEqual(C["tax_in"]["brackets"][0], (200_000_000, 0.10))   # 2026년 세율 (corptax 와 같음)
        self.assertAlmostEqual(C["rate0"], 0.099, places=3)  # 2025년: 9% + 0.9%

    def test_dept_costs_shown_with_pay(self):
        # 사용자 2026-11-18: 경영관리 부서 비용·급여, 플랜트8 부서 비용이 판관비에 들어 있음을 표에 보임 (급여 포함)
        dept = dict((n, (s, o)) for n, s, o in self.C["dept"])
        self.assertEqual(dept["경영관리 부서"], (5_000_000, 3_000_000))
        path, bk = planbs.write(self.C, self.d)
        texts = [v[0] for x in bk.sheets for v in x.cells.values() if isinstance(v[0], str)]
        self.assertTrue(any("그중 경영관리 부서 (급여 5,000,000원" in t for t in texts))
        self.assertTrue(any("그중 플랜트8 부서" in t for t in texts))
        ck = [bk.value(a) for a in self.C["_cells"]["check"]]
        self.assertEqual(ck, [0, 0])   # 보여 주기 줄이 합계를 바꾸지 않음

    def test_overstated_items(self):
        names = [x[0] for x in self.C["over"]]
        self.assertFalse(any("경영관리" in n or "플랜트" in n for n in names))   # 회사 기본 비용 (사용자 2026-11-17)
        self.assertTrue(any("감가상각" in n for n in names))
        self.assertTrue(any("이자비용" in n for n in names))
        self.assertTrue(any("법인세 예상" in n for n in names))
        self.assertFalse(any("정부지원금" in n for n in names))   # 올해 지원금 없음

    def test_workbook_balances_and_reacts(self):
        bk = planbs.build(self.C, "사용한 자료: 시험")
        cells = self.C["_cells"]
        for a in cells["check"]:
            self.assertEqual(bk.value(a), 0)
        tc, te = (bk.value(a) for a in cells["tax"])
        self.assertEqual(tc, self.C["tax_all"])   # 기본값이면 프로그램 법인세 예상과 같음
        self.assertEqual(tc, planbs.tax_total(73_000_000, 2026, self.d))
        self.assertEqual(te, planbs.tax_total(67_000_000, 2026, self.d))
        cn, en = (bk.value(a) for a in cells["net"])
        ce, ee = (bk.value(a) for a in cells["equity"])
        g0 = self.C["X0"] - round(self.C["X0"] * round(self.C["rate0"], 4))
        self.assertEqual(cn - en, 6_000_000 - (tc - te))
        self.assertEqual(ce - ee, 6_000_000 - (tc - te) + g0)
        L = K.load(self.d)
        self.assertEqual(ce, K.balance_sheet(L, "2026-10")["equity"] - tc)   # 결산 비용 0 → 장부 자본 − 세금
        # '뺄까요'를 모두 '아니오'로 → 차이 0
        set_all(bk, "inc", "아니오")
        self.assertEqual(bk.value(cells["equity"][0]), bk.value(cells["equity"][1]))
        for a in cells["check"]:
            self.assertEqual(bk.value(a), 0)

    def test_rate_and_bonus_inputs(self):
        bk = planbs.build(self.C)
        cells = self.C["_cells"]
        cn0 = bk.value(cells["net"][0])
        put(bk, "법인세율 1구간", 4, 0.2)
        tc = bk.value(cells["tax"][0])
        self.assertEqual(tc, int(73_000_000 * 0.2) + int(int(73_000_000 * 0.2) * 0.1))
        put(bk, "연말 직원 상여금", 4, 10_000_000)
        tc2, te2 = (bk.value(a) for a in cells["tax"])
        self.assertEqual(tc2, int(63_000_000 * 0.2) + int(int(63_000_000 * 0.2) * 0.1))
        self.assertEqual(bk.value(cells["net"][0]), 73_000_000 - 10_000_000 - tc2)
        self.assertLess(bk.value(cells["net"][0]), cn0)
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
            # 저장값(<v>)을 지운 파일을 LibreOffice가 처음부터 계산 → 모든 탭의 수식 칸을 프로그램 계산과 대조
            import re as _re
            work = tempfile.mkdtemp()
            bare = os.path.join(work, "bare.xlsx")
            with zipfile.ZipFile(path) as zi, zipfile.ZipFile(bare, "w") as zo:
                for n in zi.namelist():
                    data = zi.read(n)
                    if n.startswith("xl/worksheets/"):
                        data = _re.sub(r"(</f>)<v>[^<]*</v>", r"\1", data.decode()).replace(' t="str"><f>', "><f>").encode()
                    zo.writestr(n, data)
            outd = os.path.join(work, "out")
            subprocess.run([soffice, "--headless", "--convert-to", "xlsx", "--outdir", outd, bare], check=True, capture_output=True, timeout=180)
            with zipfile.ZipFile(os.path.join(outd, "bare.xlsx")) as z:
                sheets = [z.read("xl/worksheets/sheet%d.xml" % i).decode() for i in range(1, len(bk.sheets) + 1)]
            bad, n = [], 0
            for sh, xml in zip(bk.sheets, sheets):
                got = dict(_re.findall(r'<c r="([A-Z]+\d+)"[^>]*>(?:<f[^>]*>[^<]*</f>)?<v>([^<]*)</v>', xml))
                for (r, c), (v, f, s) in sh.cells.items():
                    if not f:
                        continue
                    a = xlsxw.addr(r, c)
                    mine = bk.value("'%s'!%s" % (sh.name, a))
                    if isinstance(mine, (int, float)):
                        n += 1
                        if a not in got or abs(float(got[a]) - mine) > 0.5:
                            bad.append((sh.name, a, f, mine, got.get(a)))
            self.assertEqual(bad, [])
            self.assertGreater(n, 80, n)
            shutil.rmtree(work, ignore_errors=True)
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_easy_layout(self):
        # 사용자 2026-11-18: 무엇을 어떻게 바꾸는지 알기 쉽게 → 요약이 첫 탭, 노란 칸은 '바꿀 값' 탭에만, 나머지는 잠금
        bk = planbs.build(self.C)
        self.assertEqual([x.name for x in bk.sheets], ["요약", "바꿀 값", "손익", "계정별 월별", "재무상태표", "참고"])
        self.assertTrue(all(x.protect for x in bk.sheets))
        unlocked = set(k for k, v in planbs.STYLES.items() if v.get("unlocked"))
        self.assertEqual(unlocked, {"in", "inp", "inc"})
        for x in bk.sheets:
            used = set(s for (v, f, s) in x.cells.values())
            if x.name != "바꿀 값":
                self.assertFalse(used & unlocked, x.name)
            for (v, f, s) in x.cells.values():
                if s in unlocked:
                    self.assertIsNone(f)   # 노란 칸에는 수식이 없음
        sm = bk.sheets[0]
        texts = [v for (v, f, s) in sm.cells.values() if isinstance(v, str)]
        self.assertTrue(any("숫자를 바꿔 보려면" in t for t in texts))
        ok = [xlsxw.addr(r, c) for (r, c), (v, f, s) in sm.cells.items() if f and "맞음" in f][0]
        self.assertEqual(bk.value("'요약'!" + ok), "맞음")
        first = min(r for (r, c), (v, f, s) in inputs(bk).cells.items() if s == "inc")
        self.assertIn("연말 직원 상여금", inputs(bk).cells[(first, 2)][0])   # 상여금이 맨 위
        xml = bk._sheet_xml(sm, dict((k, i) for i, k in enumerate(["_"] + sorted(planbs.STYLES))))
        self.assertIn("<sheetProtection", xml)
        self.assertIn('tabColor rgb="FF1F3864"', xml)

    def test_monthly_accounts_feed_pl(self):
        # 사용자 2026-11-18: 분개장 계정을 세목별·월별로 가져와 그 표로 비용을 만듦
        mon = self.C["monthly"]
        self.assertEqual([x[0] for x in mon["sga"]], ["81100", "81800"])
        self.assertEqual(dict((c, m) for c, n, m in mon["sga"])["81100"], [0, 78_000_000] + [0] * 8)
        self.assertEqual(dict((c, m) for c, n, m in mon["nin"])["93000"], [0, 0, 5_000_000] + [0] * 7)   # 11월 이자는 기준 달 뒤라 없음
        bk = planbs.build(self.C)
        mo = [x for x in bk.sheets if x.name == "계정별 월별"][0]
        pl = [x for x in bk.sheets if x.name == "손익"][0]
        P = self.C["P"]
        got = {}
        for (r, c), (v, f, s) in pl.cells.items():
            if c == 3 and f and "계정별 월별" in f:
                got[pl.cells[(r, 2)][0]] = bk.value("'손익'!" + xlsxw.addr(r, c))
        self.assertEqual(got["매출"], P["rev"])
        self.assertEqual(got["매출원가 (프로젝트 원가)"], P["cogs"])
        self.assertEqual(got["판매비와관리비 (장부)"], P["sga"])
        self.assertEqual(got["영업외비용 (대출 이자 등)"], P["nout"])
        self.assertEqual(got["영업외수익 (이자·정부지원금·잡이익 등)"], P["nin"])
        # 월별 표의 칸 하나를 바꾸면 손익·재무상태표 회사 전체가 따라 바뀜 (자료 기반 계산)
        row = [r for (r, c), (v, f, s) in mo.cells.items() if c == 2 and str(v).strip().startswith("복리후생비")][0]
        mo.cells[(row, 4)] = (78_000_000 + 1_000_000, None, "num")
        bk._memo = {}
        self.assertEqual(bk.value("'손익'!" + [xlsxw.addr(r, 3) for (r, c), (v, f, s) in pl.cells.items() if c == 2 and v == "판매비와관리비 (장부)"][0]), P["sga"] + 1_000_000)

    def test_no_books(self):
        d = tempfile.mkdtemp()
        try:
            self.assertIn("error", planbs.compute(d, D(2026, 11, 17)))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestClosingCosts(unittest.TestCase):
    """사용자 2026-11-17: 진행 중 프로젝트 남은 원가만 빼고 결산 때 들어갈 비용(감가상각·대손충당금·카드·4대보험·퇴직급여)을 넣음."""
    def setUp(self):
        from ceo_report import tax
        self.d = make_input()
        j = journal() + [ln(D(2026, 4, 1), "20", "80200", "직원급여", dr=120_000_000), ln(D(2026, 4, 1), "20", "10300", "보통예금", cr=120_000_000)]
        t = K.build_table(types.SimpleNamespace(state="ok", journal=j))
        with open(os.path.join(self.d, K.FILE), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, K.KEYS)
            w.writeheader()
            w.writerows(t.rows)
        rows = [["법인세", "2026년 (1월~10월 장부 기준)", "2027-03-31", "1", "예상",
                 "세전 이익 1 − 감가상각비 예상 10,000,000 = 과세표준 60,000,000 → 법인세", "60000000", "", "", "4000000", "0"],
                ["카드대금", "신한카드 11월 15일 결제 (전표 입력 전 추정)", "2026-11-15", "1,100,000", "예상", tax.CARD_THIN_MARK + " 신한", "", "", "", "", ""],
                ["카드대금", "롯데카드 12월 15일 결제 (이번 달 사용 추정)", "2026-12-15", "9,900,000", "예상", tax.CARD_OPEN_MARK + " 롯데", "", "", "", "", ""],
                ["4대보험", "2026년 10월분", "2026-11-10", "5,250,000", "예상", "예수금 중 공단 거래처 대변(직원분) 2,500,000원 + 회사분 = 직원분 × 1.10 (x)", "", "", "", "", ""],
                ["4대보험", "2026년 11월분", "2026-12-10", "5,250,000", "예상", "급여 전표 전 → 2026-10 납부액(직원분+회사분)으로 봄", "", "", "", "", ""]]
        with open(os.path.join(self.d, "세금예상.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["세목", "대상기간", "납부예정일", "금액", "상태", "근거", "과세표준", "산출세액", "기납부", "대손충당금", "세무조정"])
            w.writerows(rows)
        self.C = planbs.compute(self.d, D(2026, 11, 17))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_costs(self):
        got = dict((c["key"], (c["amount"], c["in_base"])) for c in self.C["costs"])
        self.assertEqual(got, {"dep": (10_000_000, True), "bad": (4_000_000, False), "card": (1_000_000, False),
                               "ins": (2_750_000, False), "ret": (10_000_000, False), "bonus": (0, False)})
        self.assertEqual(self.C["tax_in"]["base_c"], 60_000_000 - 17_750_000)   # 감가상각은 법인세 예상에 이미 빠짐

    def test_sheet_balances(self):
        bk = planbs.build(self.C)
        cells = self.C["_cells"]
        self.assertEqual(bk.value(cells["K"]), 27_750_000)
        for a in cells["check"]:
            self.assertEqual(bk.value(a), 0)
        tc, te = (bk.value(a) for a in cells["tax"])
        self.assertEqual(tc, planbs.tax_total(60_000_000 - 17_750_000, 2026, self.d))
        cn, en = (bk.value(a) for a in cells["net"])
        self.assertEqual(cn - en, 6_000_000 - (tc - te))   # 결산 비용은 양쪽 모두 → 차이는 영업외수익과 세금뿐
        set_all(bk, "inc", "아니오")
        self.assertEqual(bk.value(cells["net"][0]), bk.value(cells["net"][1]))
        self.assertEqual(bk.value(cells["equity"][0]), bk.value(cells["equity"][1]))
        for a in cells["check"]:
            self.assertEqual(bk.value(a), 0)


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
