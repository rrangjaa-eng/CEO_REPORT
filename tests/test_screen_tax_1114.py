"""위하고 급여·원천징수 화면 ↔ 장부 원천세·4대보험 (제안 3, 2026-11-14). 칸 이름은 PC 실제 파일로 확인한 것, 값은 합성."""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from ceo_report import checklist, screen_tax, tax, wehago_raw  # noqa: E402

D = dt.date


def save(folder, name, screen, year, responses):
    doc = {"종류": "인사", "화면": screen, "연도": year, "수집시각": "2026-11-13 11:40", "응답": responses}
    with open(os.path.join(folder, "261113 인사_%s_%d 자동수집.json" % (screen, year)), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)


def ln(day, code, credit=None, debit=None, vendor=""):
    return {"date": day, "no": "1", "account_code": code, "account": "", "debit": debit, "credit": credit,
            "vendor": vendor, "vendor_code": "", "memo": ""}


class TestScreenTax(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        emp = lambda code, inc: {"path": "/smarta/swym0107/emp/income", "cd_emp": code,
                                 "data": {"group1": [{"ym_rvrs": "202609", "am_income1": inc, "am_inhabit1": inc // 10},
                                                     {"ym_rvrs": "202610", "am_income1": inc, "am_inhabit1": inc // 10}]}}
        # 첫 사원 응답이 두 번 들어간 실제 모양 (한 번만 센다)
        save(self.dir, "", "소득자별근로소득원천징수부", 2026, [emp("1", 100000), emp("1", 100000), emp("2", 50000)])
        save(self.dir, "", "사업소득조회", 2026, [{"path": "/smarta/swbu0103/tab1/", "data": {
            "tab1_up": [{"ym_pay": "202610", "am_pay": 1000000, "am_income": 30000, "am_inhabit": 3000}],
            "tab1_down": [{"am_income": 30000, "am_inhabit": 3000}]}}])
        save(self.dir, "", "기타소득조회", 2026, [{"path": "/smarta/swet0107/other/tab01", "data": {
            "data": [{"ym_pay": "202609", "am_soduk": 400000, "am_income": 80000, "am_inhabit": 8000}], "footer": []}}])
        self.F = wehago_raw.files(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_monthly_totals_count_each_employee_once(self):
        got = screen_tax.income_tax(self.F)
        self.assertEqual(got[(2026, 9)], {"근로": 165000, "사업": 0, "기타": 88000})
        self.assertEqual(got[(2026, 10)], {"근로": 165000, "사업": 33000, "기타": 0})

    def test_compare_flags_months_over_100k_and_goes_to_checklist(self):
        j = [ln(D(2026, 9, 25), "25400", credit=253000, vendor="가상세무서"),
             ln(D(2026, 10, 25), "25400", credit=48000, vendor="가상세무서")]   # 10월 장부가 15만 적음
        notes, totals = screen_tax.compare(j, self.F, D(2026, 10, 31))
        self.assertEqual(totals[(2026, 10)], 198000)
        self.assertIn("장부 301,000 · 화면 451,000", notes[0])
        warn = [n for n in notes if n.startswith("[확인] 원천세")]
        self.assertEqual(len(warn), 1)
        self.assertIn("10월 장부 48,000", warn[0])
        self.assertNotIn("9월", warn[0])
        items = checklist.convert_items({}, [], warn)
        self.assertEqual([i["kind"] for i in items], ["세금 대조"])

    def test_screen_value_fills_month_before_salary_slip(self):
        j = [ln(D(2026, 9, 25), "25400", credit=253000, vendor="가상세무서"),
             ln(D(2026, 9, 26), "25400", debit=999, vendor="가상세무서")]
        rows = tax.withholding(j, D(2026, 10, 31), mode="매월", screen={(2026, 10): 198000})
        oct_ = [r for r in rows if r["대상기간"] == "2026년 10월분"]
        self.assertEqual(oct_[0]["금액"], "198000")
        self.assertIn("위하고 급여·사업·기타소득 화면 값 198,000원", oct_[0]["근거"])
        nov = [r for r in rows if r["대상기간"] == "2026년 11월분"]
        self.assertEqual(nov[0]["금액"], "253000")   # 화면 값이 없는 달은 예전처럼 최근 장부 달 금액

    def test_employee_insurance_is_deductions_minus_wage_tax(self):
        save(self.dir, "", "월별급상여수당지급현황", 2026, [{"path": "/smarta/swsa0105/total", "data": [
            {"nm_krname": "가상1", "cd_emp": "1", "cd_code": "1", "mon_10_gong": 400000},
            {"nm_krname": "가상2", "cd_emp": "2", "cd_code": "2", "mon_10_gong": 200000}]}])
        F = wehago_raw.files(self.dir)
        ins = screen_tax.employee_insurance(F, screen_tax.income_tax(F))
        self.assertEqual(ins[(2026, 10)], 600000 - 165000)
        j = [ln(D(2026, 10, 25), "25400", credit=200000, vendor="가상국민연금공단")]
        notes, _ = screen_tax.compare(j, F, D(2026, 10, 31))
        self.assertTrue(any(n.startswith("[확인] 4대보험 직원분") and "장부 200,000 · 화면 435,000" in n for n in notes), notes)


if __name__ == "__main__":
    unittest.main()


class TestCardActual(unittest.TestCase):
    """카드 전표 입력 전 달: 위하고 자동전표처리 '신용카드' 화면(SAAC0105)의 실제 사용으로 채움 (평균 대신). 합성 값."""

    def journal(self):
        K, j = 10000, []
        for m in (7, 8, 9):
            c = dict(ln(D(2026, m, 10), "26200", credit=300 * K, vendor="신한_5860"), vendor_code="00501", no="u%d" % m)
            p = dict(ln(D(2026, m + 1, 14), "26200", debit=300 * K, vendor="신한_5860"), vendor_code="00501", no="p%d" % m)
            b = dict(ln(D(2026, m + 1, 14), "10300", credit=300 * K), no="p%d" % m)
            j += [c, p, b]
        return j

    def test_real_usage_replaces_average(self):
        folder = tempfile.mkdtemp()
        try:
            doc = {"종류": "결산", "화면코드": "SAAC0105", "수집시각": "2026-11-13 09:00", "응답": [
                {"path": "/smarta/saac0105/6/", "data": {"data": [
                    {"da_sbook": "20261005", "nm_ctrade": "[00501]신한_5860", "cd_ctrade": "00501", "mn_mnam": 2272727,
                     "mn_vat": 227273, "mn_total": 2500000, "ty_jungstat": "0"}]}}]}
            with open(os.path.join(folder, "261113 결산_신용카드 자동수집.json"), "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False)
            real, upto = screen_tax.card_usage(folder)
        finally:
            shutil.rmtree(folder)
        self.assertEqual(upto, D(2026, 11, 13))
        self.assertEqual(real["code:501"], [(D(2026, 10, 5), 2500000)])
        rows = tax.cards(self.journal(), D(2026, 11, 10), {"신한": (14, 1)}, actual=real, actual_upto=upto)
        nov = [r for r in rows if "11월" in r["대상기간"]]
        self.assertEqual([r["금액"] for r in nov], ["2500000"], [r["근거"] for r in rows])
        self.assertIn("위하고 카드 사용 기준", nov[0]["대상기간"])
        rows = tax.cards(self.journal(), D(2026, 11, 10), {"신한": (14, 1)})   # 화면 자료가 없으면 예전처럼 평균
        self.assertEqual([r["금액"] for r in rows if "11월" in r["대상기간"]], ["3000000"])
