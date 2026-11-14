import csv
import json
import os
import tempfile
import unittest
import unittest.mock

from ceo_report import wehago_raw as w

# 가짜 사람·숫자
EMP = {"rank": [{"position_rank_no": 1, "position_rank_name": "사원"}, {"position_rank_no": 9, "position_rank_name": "상무"}],
       "position": [{"position_rank_no": 5, "position_rank_name": "팀원"}],
       "emp": [{"cd_emp": "00001", "nm_krname": "가대표", "no_social": "800101-1", "nm_dept": "본부", "da_enter": "20250201", "da_retire": None},
               {"cd_emp": "00003", "nm_krname": "다상무", "no_social": "700101-1", "nm_dept": "본부", "da_enter": "20250201", "da_retire": None,
                "rank_no": 9},
               {"cd_emp": "00002", "rank_no": 1, "position_rank_no": 5, "nm_krname": "나직원", "no_social": "010203-4", "nm_dept": "1팀", "da_enter": "20250401", "da_retire": "20260331"}]}
PAY = [{"cd_emp": "00001", "nm_krname": "가대표", "cd_code": "00001", "total_ji": 0, "total_gong": 0,
        **dict(("mon_%02d_ji" % m, 5000000 if m <= 2 else 0) for m in range(1, 13)),
        **dict(("mon_%02d_gong" % m, 700000 if m <= 2 else 0) for m in range(1, 13))}]
INFO = [{"cd_emp": "00001", "nm_offpos": "대표"}]
YE = [{"nm_krname": "나직원", "am_totpay": 40000000, "am_mydedt": 1500000, "am_wifededt": 0, "am_famdedt": 3000000,
       "am_oldfamdedt": 0, "am_womandedt": 500000, "am_childsdedt": 550000, "am_adopt": 0, "sum_specdedt": 2000000, "premium": 1500000,
       "am_etcdedt": 1000000, "am_calctax": 3000000, "am_unempincom": 660000, "am_deciincom": 1500000}]
PLUS = {"g_date": [{"da_tdatey": "2025"}], "g_list": [
    {"nm_sq": "Ⅰ.미처분이익잉여금", "ty_depth": "1", "mn_sq": "0", "mn_cal": "100"},
    {"nm_sq": "6.당기순이익", "ty_depth": "2", "mn_sq": "100", "mn_cal": "0"},
    {"nm_sq": "Ⅳ.차기이월 미처분이익잉여금", "ty_depth": "1", "mn_sq": "0", "mn_cal": "100"}]}
BS = {"main": [{"cd_acctit": "33100", "nm_acctit": "자본금", "mn_bungae_right": 10},
               {"cd_acctit": "29300", "nm_acctit": "장기차입금", "mn_bungae_right": 50}]}
FIX = [{"cd_fixast": "000001", "nm_fixast": "차", "nm_acctit": "차량운반구", "da_acquire": "20251001", "mn_base": 1000, "mn_new": 0,
        "rt_depre": 0.2, "mn_ftdepsum": 50, "mn_ctdepre1": 200, "mn_ctdepsum": 250}, {"cd_fixast": None, "nm_fixast": "소계"}]


def save(d, name, kind, screen, year, resp):
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        json.dump({"종류": kind, "형식": 1, "수집시각": "2026-11-13 11:00:00", "연도": year, "화면": screen, "응답": resp}, f, ensure_ascii=False)


def folder():
    d = tempfile.mkdtemp()
    save(d, "261113 인사_사원등록 자동수집.json", "인사원본", "사원등록", 2026, [{"path": "/smarta/swpm0108/condition/", "data": EMP}])
    save(d, "261113 인사_월별급상여수당지급현황 자동수집.json", "인사원본", "월별급상여수당지급현황", 2026,
         [{"path": "/smarta/swsa0105/total/", "data": PAY}, {"path": "/smarta/swsa0105/info/", "data": INFO}])
    save(d, "261113 연말정산_연말정산현황_2025 자동수집.json", "연말정산원본", "연말정산현황", 2025, [{"path": "/smarta/swym0102/", "data": YE}])
    save(d, "261113 결산_이익잉여금처분계산서 자동수집.json", "결산원본", "이익잉여금처분계산서", 2026, [{"path": "/smarta/sacl0108/plusforw/", "data": PLUS}])
    save(d, "261113 결산_재무상태표_2025 자동수집.json", "결산원본", "재무상태표", 2025, [{"path": "/smarta/sacl0105/main/", "data": BS}])
    save(d, "261113 결산_고정자산관리대장 자동수집.json", "결산원본", "고정자산관리대장", 2026, [{"path": "/smarta/saas0107/allfixlist/", "data": FIX}])
    wh = [{"path": "/smarta/swym0107/emp/", "data": [{"cd_emp": "00002", "nm_krname": "나직원", "num_wife": 1, "num_childs": 2, "num_60over": 0}]},
          {"path": "/smarta/swym0107/emp/income/", "cd_emp": "00001",
           "data": {"group1": [{"ym_pay": "202601", "am_income1": 300000, "am_inhabit1": 30000}, {"ym_pay": "", "am_income1": 0}]}}]
    save(d, "261113 인사_소득자별근로소득원천징수부 자동수집.json", "인사원본", "소득자별근로소득원천징수부", 2026, wh)
    return d


class Raw(unittest.TestCase):
    def setUp(self):
        self.F = w.files(folder())

    def test_birth(self):
        self.assertEqual(w.birth_from_social("800101-1"), "1980-01-01")
        self.assertEqual(w.birth_from_social("010203-4"), "2001-02-03")
        self.assertEqual(w.birth_from_social(""), "")

    def test_duplicate_withholding_response_counted_once(self):
        """실제 원천징수부 수집(2026-11-14): 첫 사원 소득 응답이 같은 내용으로 두 번 들어 있다 → 한 번만."""
        from ceo_report import wehago_raw
        inc = {"path": "/smarta/swym0107/emp/income/", "cd_emp": "00001",
               "data": {"group1": [{"ym_pay": "202601", "am_income1": 300000, "am_inhabit1": 30000}]}}
        other = {"path": "/smarta/swym0107/emp/income/", "cd_emp": "00003",
                 "data": {"group1": [{"ym_pay": "202601", "am_income1": 300000, "am_inhabit1": 30000}]}}
        F = {"인사_소득자별근로소득원천징수부": None}
        with unittest.mock.patch.object(wehago_raw, "_pick", lambda F_, kind: [(2026, {"응답": [inc, dict(inc), other]})]):
            _, out = wehago_raw._withholding(F)
        self.assertEqual(sorted(out), [(2026, "00001", "2026-01", 300000, 30000), (2026, "00003", "2026-01", 300000, 30000)])

    def test_employees(self):
        e = w.employees(self.F)
        self.assertEqual([r["임원"] for r in e], ["예", "예", ""])
        self.assertEqual(e[2]["직급"], "사원 팀원")
        self.assertEqual(e[2]["퇴사일"], "2026-03-31")
        self.assertEqual((e[2]["부양가족수"], e[2]["자녀수"]), ("3", "2"))
        e = e[1:]
        self.assertNotIn("no_social", " ".join(e[1].values()))
        self.assertFalse(any("-4" in v for v in e[1].values() if v))   # 성별 자리 저장 안 함

    def test_pay(self):
        p = w.pay_rows(self.F)
        self.assertEqual(len(p), 6)
        self.assertIn({"연월": "2026-01", "사원명": "가대표", "구분": "공제", "항목": w.WH_TAX, "금액": "300000"}, p)
        self.assertEqual(p[0], {"연월": "2026-01", "사원명": "가대표", "구분": "지급", "항목": "지급합계", "금액": "5000000"})

    def test_yearend(self):
        r = w.yearend_rows(self.F)[0]
        self.assertEqual((r["귀속연도"], r["기본공제인원"], r["부녀자"], r["자녀세액공제인원"]), ("2025", "3", "1", "2"))
        self.assertEqual(r["특별세액공제"], str(3000000 - 1500000 - 660000 - 550000))
        self.assertEqual(r["특별소득공제"], "500000")   # 보험료 뺀 몫

    def test_assets_and_closing(self):
        a = w.asset_rows(self.F)
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["당기상각"], "200")
        C = w.closing(self.F)
        self.assertEqual(C[2025]["처분_차기이월"], 100)
        self.assertEqual(C[2025]["자본금"], 10)
        self.assertEqual(C[2025]["차입금"], 50)

    def test_tables(self):
        T = dict((t.name, t) for t in w.build_tables(folder()))
        self.assertTrue(all(t.written for t in T.values()))
        T = w.build_tables(tempfile.mkdtemp())
        self.assertFalse(any(t.written for t in T))

    def test_payroll_totals_only(self):
        from ceo_report import payroll
        d = tempfile.mkdtemp()
        for t in w.build_tables(folder()):
            with open(os.path.join(d, t.name), "w", encoding="utf-8-sig", newline="") as f:
                c = csv.DictWriter(f, t.columns)
                c.writeheader()
                c.writerows(t.rows)
        out = payroll.check(d, "2026-01")
        self.assertFalse(any(r[1] == "4대보험" and r[2] == "warn" for r in out))
        Y = payroll.yearend(d, 2026, __import__("datetime").date(2026, 2, 28))
        self.assertIsNotNone(Y[0]["paid"])        # 원천징수부 소득세가 있으면 낸 세금을 셈


if __name__ == "__main__":
    unittest.main()
