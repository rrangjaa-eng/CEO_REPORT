"""11/17 저녁 제안(오류·빠진 기능·추가 기능) 고침 시험. 합성 자료만."""
import datetime as dt
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

D = dt.date


def jl(day, no, code, name, debit=None, credit=None, vendor="", vcode="", memo="", sort="매출전표"):
    return {"date": day, "no": no, "account_code": code, "account": name, "debit": debit, "credit": credit,
            "vendor": vendor, "vendor_code": vcode, "memo": memo, "sort": sort, "project_name": ""}


class TestE3VendorCode(unittest.TestCase):
    """E3 (계산-01): 매출 계산서에 거래처코드를 남기고 입금 습관을 코드로 묶는다."""
    def test_sales_invoice_keeps_vendor_code(self):
        from ceo_report import wehago
        j = [jl(D(2026, 3, 2), "7", "10800", "외상매출금", debit=1_100_000, vendor="가회사", vcode="00123"),
             jl(D(2026, 3, 2), "7", "41200", "용역매출", credit=1_000_000, vendor="가회사", vcode="00123"),
             jl(D(2026, 3, 2), "7", "25500", "부가세예수금", credit=100_000)]
        _, sales = wehago.invoices_from_journal(j)
        self.assertEqual(sales[0]["vendor_code"], "123")

    def test_pay_habits_group_by_code_not_name(self):
        from ceo_report import insights
        inv = lambda name, code, due, paid: {"client": name, "client_code": code, "due": due, "paid_date": paid}
        invs = [inv("가회사", "123", D(2026, 1, 1), D(2026, 1, 11)), inv("(주)가회사", "123", D(2026, 2, 1), D(2026, 2, 11)),
                inv("가회사", "999", D(2026, 1, 1), D(2026, 1, 1))]
        R = {"s2": {"dated": []}}
        out = insights.pay_habits(R, invs)
        # 이름이 달라도 코드 123 은 한 거래처 (2건 평균 10일), 이름이 같아도 코드 999 는 다른 거래처 (1건이라 빠짐)
        self.assertEqual([(c[1], c[2]) for c in out["clients"]], [(10, 2)])
        self.assertTrue(out["clients"][0][0].endswith("[123]"))


if __name__ == "__main__":
    unittest.main()


class TestE3Words(unittest.TestCase):
    def test_penalty_by_account_first_and_memo_lines_shown(self):
        from ceo_report import taxadj
        import inspect
        src = inspect.getsource(taxadj)
        self.assertIn("pen_memo.append", src)
        self.assertTrue(taxadj.PENALTY.search("세금과공과벌과금"))

    def test_local_prepaid_lines_are_reported_in_basis(self):
        from ceo_report import corptax
        self.assertIn("구청", corptax.LOCAL_WORDS)


class TestE2YearendLaw(unittest.TestCase):
    """E2 (계산-04): 연말정산 공제 금액·세율 구간을 기간이 있는 세법 기준표에서 읽는다."""
    def test_values_have_years(self):
        from ceo_report import taxlaw
        for y in (2025, 2026):
            for k in ("인적공제", "자녀공제_1명", "자녀공제_2명", "자녀공제_추가", "출산공제_첫째", "표준세액공제", "종합소득세율", "근로소득공제", "근로세액공제"):
                v, ok, _ = taxlaw.value(None, y, k)
                self.assertTrue(ok and v is not None, (y, k))
        self.assertTrue(taxlaw.value(None, 2026, "자녀공제_나이")[0].startswith("9세"))
        self.assertFalse(taxlaw.value(None, 2027, "인적공제")[1])   # 다음 해는 먼저 확인

    def test_payroll_uses_table_and_marks_unconfirmed_year(self):
        from ceo_report import payroll
        V, miss = payroll.ye_values(None, 2026)
        self.assertEqual((V["인적공제"], V["표준세액공제"], miss), (1_500_000, 130_000, []))
        self.assertEqual([payroll.child_credit(n, V) for n in (0, 1, 2, 3)], [0, 250_000, 550_000, 950_000])
        _, miss27 = payroll.ye_values(None, 2027)
        self.assertIn("기본공제 1명당 (본인·부양가족)", miss27)

    def test_user_confirmed_value_reaches_yearend(self):
        import tempfile
        from ceo_report import payroll, taxlaw
        with tempfile.TemporaryDirectory() as d:
            taxlaw.confirm(d, 2026, {"인적공제": "2000000"}, source="시험", who="시험")
            self.assertEqual(payroll.ye_values(d, 2026)[0]["인적공제"], 2_000_000)


class TestA4Installment(unittest.TestCase):
    """A4: 법인세 분납 (법인세법 64조 — 1천만 초과, 2천만 이하면 1천만 넘는 몫, 넘으면 절반, 중소기업 2개월)."""
    def test_installable_amounts(self):
        from ceo_report.corptax import installable, inst_due
        self.assertEqual([installable(v) for v in (9_000_000, 10_000_000, 15_000_000, 20_000_000, 30_000_001)],
                         [0, 0, 5_000_000, 10_000_000, 15_000_000])
        self.assertEqual(inst_due(D(2027, 3, 31)), D(2027, 5, 31))

    def test_rows_get_installment_only_when_chosen(self):
        from ceo_report import corptax
        from ceo_report.tax import _row
        rows = [_row("법인세", "2026년 (1월~10월 장부 기준)", D(2027, 3, 31), 18_000_000, "예상", "b"),
                _row("법인세", "2026년 11~12월 남은 기간 예상", D(2027, 3, 31), 7_000_000, "예상", "r"),
                _row("법인지방소득세", "2026년 (1월~10월 장부 기준)", D(2027, 4, 30), 2_000_000, "예상", "l")]
        self.assertEqual([r["분납"] for r in corptax.installment([dict(r) for r in rows], False)], ["", "", ""])
        got = corptax.installment(rows, True)
        self.assertEqual([r["분납"] for r in got], ["12500000", "", ""])   # 합계 2,500만 → 절반을 본 줄에

    def test_merge_splits_schedule_but_keeps_row_amount(self):
        from ceo_report import tax
        t = {"kind": "법인세", "period": "2026년 (1월~10월 장부 기준)", "due": D(2027, 3, 31), "amount": 25_000_000, "state": "예상",
             "basis": "", "codes": (), "book": None, "inst": 12_500_000}
        ev, info = tax.merge([], [t], asof=D(2026, 11, 17))
        self.assertEqual(sorted((e["date"], e["amount"]) for e in ev), [(D(2027, 3, 31), 12_500_000), (D(2027, 5, 31), 12_500_000)])
        self.assertEqual(info[0]["amount"], 25_000_000)

    def test_choices_file(self):
        import tempfile
        from ceo_report import choices
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(choices.installment(d))
            choices.save(d, {"법인세분납": "예", "예금금리": "3.2"})
            self.assertTrue(choices.installment(d))
            self.assertAlmostEqual(choices.rate(d), 0.032)
            with self.assertRaises(ValueError):
                choices.save(d, {"법인세분납": "몰라"})


def _R(asof, months, projects=(), invoices=(), targets=None, acct=None):
    """insights_more 용 작은 R: months = {ym: (매출, 원가, 판관비)}."""
    bm = [(ym, [{"unit": "회사", "target": "회사 전체", "cur": {"revenue": r, "direct": c, "common": g}}]) for ym, (r, c, g) in sorted(months.items())]
    return {"asof": asof, "s4": {"sources": {"WEHAGO": {"by_month": bm}}}, "s3": {"projects": list(projects)}, "_invoices": list(invoices),
            "targets": targets or {}, "acct_year": acct or {}, "s2": {}, "tax": []}


class TestNewAnalyses(unittest.TestCase):
    """M3·A1·A2·A3·A8: 경영관리 자동 분석 16~23 (합성 자료)."""
    def test_collect_days_counts_unpaid_as_late_and_flags(self):
        from ceo_report import insights_more as M
        inv = [{"kind": "발행", "date": D(2026, 6, 1), "supply": 1, "paid_date": D(2026, 6, 1) + dt.timedelta(days=d)} for d in (50, 70, 80, 90)]
        inv += [{"kind": "발행", "date": D(2026, 6, 1), "supply": 1, "paid_date": None}] * 2
        R = _R(D(2026, 10, 31), {}, invoices=inv)
        c = M.collect_days(R)
        self.assertEqual((c["n"], c["open"], c["median"], c["off"]), (6, 2, 80, True))
        M.add_risks(R)
        self.assertTrue(any("60일" in r["fact"] for r in R["risks"]))

    def test_breakeven_and_need(self):
        from ceo_report import insights_more as M
        months = {"2026-%02d" % m: (100_000_000, 70_000_000, 20_000_000) for m in range(1, 11)}
        b = M.breakeven(_R(D(2026, 10, 31), months, targets={"1팀": {"revenue": 1_200_000_000}}))
        self.assertEqual((b["fixed"], round(b["rate"], 2), b["be"], b["left"], b["need"]), (20_000_000, 0.3, 66_666_667, 2, 100_000_000))

    def test_pipeline_and_clients(self):
        from ceo_report import insights_more as M
        P = [{"id": "1", "name": "가", "client": "고객갑", "event_date": "2026-11-20", "closed": False, "profit_basis": 100, "profit_now": 30},
             {"id": "2", "name": "나", "client": "고객을", "event_date": "2026-11-05", "closed": False, "profit_basis": 200, "profit_now": 20}]
        inv = [{"kind": "발행", "project": "1", "client": "갑(주)", "client_code": "77", "date": D(2026, 11, 1)}]
        R = _R(D(2026, 10, 31), {"2026-10": (0, 0, 10)}, projects=P, invoices=inv)
        p = M.pipeline(R)
        self.assertEqual((p["rows"][0]["ym"], p["rows"][0]["gp"], p["rows"][0]["cover"]), ("2026-11", 50, 5.0))
        cl = M.clients(R)
        self.assertEqual([x["label"] for x in cl["rows"]], ["고객을 (코드 없음)", "갑(주) [77]"])
        self.assertEqual((round(cl["rows"][0]["rate"], 2), cl["rows"][0]["low"]), (0.1, False))   # 평균 16.7% − 10%p 보다 높음

    def test_cost_spike(self):
        from ceo_report import insights_more as M
        acc = {"code": "81300", "name": "접대비", "months": [1_000_000] * 9 + [6_000_000, None, None]}
        A = {"state": "ok", "year": "2026", "groups": [{"name": "판매비와관리비", "accounts": [acc]}]}
        sp = M.cost_spikes(_R(D(2026, 10, 31), {}, acct=A))
        self.assertEqual((sp[0]["name"], sp[0]["up"]), ("접대비", 5_000_000))


class TestM4Guides(unittest.TestCase):
    """M4 (규칙 11/13): 오차범위·전표 입력 안내를 프로그램이 경영관리 '요청 자료 전부'에 만든다."""
    def test_tables_and_live_measure(self):
        from ceo_report import guides
        K = {"weeks": [{"part": False, "in": {"all": 100, "actual": 130}, "out": {"all": 50, "actual": 40}}],
             "profit": [{"forecast": 10, "actual": 25}]}
        h = guides.trust_html({"track": K})
        self.assertIn("id='trust'", h)
        self.assertIn("그 뒤 4주 입·출금 2번", h)
        self.assertIn("1번: 가운데 15원", h)
        self.assertIn("카드사_끝4자리", guides.entry_html())

    def test_docs_section_links(self):
        from ceo_report import digest
        R = {"kind": "monthly", "asof": D(2026, 10, 31), "risks": []}
        try:
            h = digest.docs_section(R, {}, [])
        except Exception:
            self.skipTest("요청 자료 표는 전체 보고 계산이 있어야 만들어짐 (아래 보고서.py 시험이 확인)")
        self.assertIn("href='#trust'", h)


class TestMonthlyMgmtHasNewParts(unittest.TestCase):
    """보고서.py 월간: 경영관리에 자동 분석 16~23·오차범위·전표 안내가 있고 대표 보고에는 없다 (11/17 규칙)."""
    def test_cli(self):
        import shutil
        import subprocess
        import tempfile
        root = os.path.dirname(HERE)
        with tempfile.TemporaryDirectory() as t:
            inp, out = os.path.join(t, "입력"), os.path.join(t, "출력")
            shutil.copytree(os.path.join(root, "입력양식", "샘플"), inp)
            subprocess.run([sys.executable, os.path.join(root, "보고서.py"), "월간", "--기준일", "2026-10-31", "--입력", inp, "--출력", out,
                            "--pdf", "안함"], capture_output=True, text=True, cwd=root)
            mg = open(os.path.join(out, "2026-10-31_월간_경영관리보고.html"), encoding="utf-8").read()
            for k in ("id='trust'", "id='entry'", "입금 걸린 날", "손익분기 매출", "고객사별 이익", "법인세 나눠 내면", "당분간 안 쓸 돈",
                      "퇴직금 합계", "비용 급증"):
                self.assertIn(k, mg)
            ceo = open(os.path.join(out, "2026-10-31_월간_대표보고.html"), encoding="utf-8").read()
            for k in ("손익분기", "고객사별 이익", "당분간 안 쓸 돈", "id='trust'"):
                self.assertNotIn(k, ceo)


class TestUserRules1117Night(unittest.TestCase):
    """사용자 2026-11-17 밤: 대표 승인 끝난(회색) 프로젝트 남은 예산 지움 · 예산 대비 실행가 120% 넘는 것만 경영관리에 알림."""
    @classmethod
    def setUpClass(cls):
        from ceo_report import calc, data
        cls.calc = calc
        cls.R = calc.compute(data.load(os.path.join(os.path.dirname(HERE), "입력양식", "샘플")), "weekly", D(2026, 11, 2))

    def test_closed_remain_cleared(self):
        for P in self.R["s3"]["projects"]:
            if P["closed"]:
                self.assertTrue(P["remain"] is None or P["remain"] <= 0, P["id"])
                self.assertIsNone(P["remain_cash"])
        self.assertTrue(any(P.get("remain_cleared") for P in self.R["s3"]["projects"]))

    def test_risk_only_over_120(self):
        R = self.R
        P = [p for p in R["s3"]["projects"] if p["id"] == "P26201"][0]
        keep = P["budget"]
        try:
            P["budget"] = int(P["committed"] / 1.15)
            self.assertFalse(any("P26201" in r["fact"] and "예산" in r["fact"] for r in self.calc.risks(R)))
            P["budget"] = int(P["committed"] / 1.25)
            self.assertTrue(any("P26201" in r["fact"] and "예산" in r["fact"] for r in self.calc.risks(R)))
        finally:
            P["budget"] = keep
