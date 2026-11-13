"""기업신용평가 미리보기 (사용자 2026-11-12): 장부 잔액·비율·판정·등급 범위·결산 전 할 일·작년 평가 보정."""
import csv
import datetime as dt
import os
import shutil
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import credit as K  # noqa: E402

D = dt.date


def ln(day, no, code, name, dr=0, cr=0, memo="", sort="일반전표"):
    return {"date": day, "no": no, "sort": sort, "account_code": code, "account": name,
            "debit": dr or None, "credit": cr or None, "vendor": "", "memo": memo}


def journal(start=True):
    j = []
    if start:   # 2025-03 설립: 자본금 납입 (처음부터인 분개장)
        j += [ln(D(2025, 3, 2), "1", "10300", "보통예금", dr=100_000_000), ln(D(2025, 3, 2), "1", "33100", "자본금", cr=100_000_000)]
    # 2026: 매출 10억 (미수금), 원가 7억 (미지급금), 판관 2억, 이자 1천만, 장기대출 3억, 가수금 5천만, 보증금 1천만
    j += [ln(D(2026, 1, 10), "2", "10800", "수입수수료미수금", dr=1_000_000_000), ln(D(2026, 1, 10), "2", "41200", "수입수수료", cr=1_000_000_000),
          ln(D(2026, 1, 11), "3", "63300", "행사외주비(도)", dr=700_000_000), ln(D(2026, 1, 11), "3", "25300", "미지급금", cr=700_000_000),
          ln(D(2026, 1, 12), "4", "80200", "직원급여(판)", dr=200_000_000), ln(D(2026, 1, 12), "4", "10300", "보통예금", cr=200_000_000),
          ln(D(2026, 1, 13), "5", "10300", "보통예금", dr=300_000_000), ln(D(2026, 1, 13), "5", "29300", "장기차입금", cr=300_000_000),
          ln(D(2026, 1, 14), "6", "93100", "이자비용", dr=10_000_000), ln(D(2026, 1, 14), "6", "10300", "보통예금", cr=10_000_000),
          ln(D(2026, 1, 15), "7", "10300", "보통예금", dr=50_000_000), ln(D(2026, 1, 15), "7", "25700", "가수금", cr=50_000_000),
          ln(D(2026, 1, 16), "8", "96200", "임차보증금", dr=10_000_000), ln(D(2026, 1, 16), "8", "10300", "보통예금", cr=10_000_000)]
    return j


def make_input(start=True, inputs=None):
    d = tempfile.mkdtemp()
    books = types.SimpleNamespace(state="ok", journal=journal(start))
    t = K.build_table(books)
    with open(os.path.join(d, K.FILE), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, K.KEYS)
        w.writeheader()
        w.writerows(t.rows)
    if inputs:
        K.save_inputs(d, inputs)
    return d


class TestCredit(unittest.TestCase):
    def tearDown(self):
        for d in getattr(self, "dirs", []):
            shutil.rmtree(d, ignore_errors=True)

    def mk(self, *a, **k):
        d = make_input(*a, **k)
        self.dirs = getattr(self, "dirs", []) + [d]
        return d

    def test_balance_sheet_from_start(self):
        L = K.load(self.mk())
        self.assertTrue(L["start"])
        B = K.balance_sheet(L, "2026-12")
        # 현금 1억 −2억 +3억 −0.1억 +0.5억 −0.1억 = 2.3억, 미수금 10억 → 유동 12.3억, 보증금 0.1억 비유동
        self.assertEqual(B["ca"], 1_230_000_000)
        self.assertEqual(B["na"], 10_000_000)
        self.assertEqual(B["cl"], 750_000_000)   # 미지급금 7억 + 가수금 0.5억
        self.assertEqual(B["nl"], 300_000_000)
        self.assertEqual(B["equity"], 1_240_000_000 - 1_050_000_000)   # 자본금 1억 + 올해 이익 0.9억
        self.assertEqual(B["loan"], 350_000_000)   # 장기차입금 + 대표 가수금 (평가사 기준)
        self.assertEqual(B["suspense"], 50_000_000)

    def test_ratios_and_judge(self):
        C = K.compute(self.mk(inputs={"설립일": "2025-03-02"}), D(2026, 12, 31), annual=True)
        V = C["V"]
        self.assertAlmostEqual(V["opm"], 10.0)                    # (10억 − 7억 − 2억) ÷ 10억
        self.assertAlmostEqual(V["icr"], 10.0)                    # 1억 ÷ 0.1억
        self.assertAlmostEqual(V["debt"], 100.0 * 1_050_000_000 / 190_000_000)
        self.assertAlmostEqual(V["current"], 100.0 * 1_230_000_000 / 750_000_000)
        self.assertEqual(K.judge("opm", V["opm"]), "좋음")
        self.assertEqual(K.judge("debt", V["debt"]), "나쁨")       # 553% > 400%
        self.assertEqual(K.judge("ocf", -1), "나쁨")
        self.assertEqual(K.judge("collect", 64), "보통")

    def test_not_from_start_leaves_balance_items_empty(self):
        C = K.compute(self.mk(start=False), D(2026, 12, 31), annual=True)
        for k in ("debt", "equity", "borrow", "current", "turn"):
            self.assertIsNone(C["V"][k])
        self.assertIsNotNone(C["V"]["opm"])
        self.assertIn("작년 분개장 필요", K.render(C))

    def test_loan_due_within_year_moves_to_current(self):
        d = self.mk(inputs={"대출만기일": "2027-04-21"})
        C = K.compute(d, D(2026, 12, 31), annual=True)
        self.assertEqual(C["E"]["moved"], 300_000_000)
        self.assertAlmostEqual(C["V"]["current"], 100.0 * 1_230_000_000 / 1_050_000_000)
        self.assertTrue(any(t[0] == "1년 안 만기 대출 정리" for t in C["todo"]))
        far = K.compute(self.mk(inputs={"대출만기일": "2029-01-01"}), D(2026, 12, 31), annual=True)
        self.assertIsNone(far["E"].get("moved"))

    def test_suspense_todo_with_effect(self):
        C = K.compute(self.mk(), D(2026, 12, 31), annual=True)
        t = [x for x in C["todo"] if x[0] == "대표 가수금 정리"][0]
        self.assertIn("50,000,000", t[1])
        self.assertIn("출자전환하면 부채비율", t[2])

    def test_arrears_cap(self):
        C = K.compute(self.mk(inputs={"체납": "있음"}), D(2026, 12, 31), annual=True)
        for g in C["grade"]:
            self.assertGreaterEqual(K.NOTCHES.index(g), K.NOTCHES.index(K.CAP_DEFAULT))

    def test_young_company_lowers_bottom(self):
        a = K.compute(self.mk(inputs={"설립일": "2025-03-02"}), D(2026, 12, 31), annual=True)
        lo_raw = K.grade_of(a["score"][0])
        self.assertEqual(a["grade"][0], K.shift(lo_raw, -1))

    def test_last_year_calibration(self):
        base = K.compute(self.mk(inputs={"설립일": "2025-03-02"}), D(2026, 12, 31), annual=True)
        mine = K.compute(self.mk(inputs={"설립일": "2025-03-02", "작년_결산연도": "2025"}), D(2026, 12, 31), annual=True)["last"]["mine"]
        actual = K.shift(mine, 2)   # 실제가 2칸 위
        C = K.compute(self.mk(inputs={"설립일": "2025-03-02", "작년_결산연도": "2025", "작년_등급": actual, "작년_부채비율": "150"}),
                      D(2026, 12, 31), annual=True)
        self.assertEqual(C["last"]["src"]["debt"], "평가서")
        self.assertEqual(C["last"]["V"]["debt"], 150.0)
        n = C["last"]["adj"]
        self.assertEqual(C["grade"], tuple(K.shift(g, n) for g in C["grade_raw"]))
        self.assertIn("작년에 받은 평가와 비교", K.render(C))
        self.assertTrue(base["last"] is None)

    def test_grade_helpers(self):
        self.assertEqual(K.grade_of(100), "AA-")
        self.assertEqual(K.grade_of(62), "BBB-")
        self.assertEqual(K.grade_of(0), "CCC+")
        self.assertEqual(K.shift("BBB-", 1), "BBB0")
        self.assertEqual(K.notch_diff("BB+", "BB-"), 2)

    def test_inputs_roundtrip(self):
        d = self.mk(inputs={"설립일": "2025-03-02", "체납": "없음"})
        K.save_inputs(d, {"체납": ""})
        v = K.read_inputs(d)
        self.assertEqual(v.get("설립일"), "2025-03-02")
        self.assertNotIn("체납", v)

    def test_balance_from_last_year_report_when_journal_is_partial(self):
        # 사용자 2026-11-13: 2025 분개장 없이 평가서 총자산·자기자본 + 올해 장부 증감
        d = self.mk(start=False, inputs={"작년_결산연도": "2025", "작년_총자산": "1000000000", "작년_자기자본": "100000000",
                                         "작년_차입금": "200000000", "작년_매출액": "1100000000", "설립일": "2025-02-01"})
        C = K.compute(d, D(2026, 12, 31), annual=True)
        B = C["E"]["B"]
        self.assertTrue(B["approx"])
        # 올해 자산 증감: 현금(−2+3−0.1+0.5−0.1=1.3억) + 미수금 10억 + 보증금 0.1억, 부채 증감: 7억 + 0.5억 + 3억
        self.assertEqual(B["assets"], 1_000_000_000 + 1_140_000_000)
        self.assertEqual(B["liab"], 900_000_000 + 1_050_000_000)
        self.assertEqual(B["equity"], 100_000_000 + 90_000_000)
        self.assertEqual(B["loan"], 200_000_000 + 300_000_000 + 50_000_000)   # 장기차입금 + 가수금
        self.assertAlmostEqual(C["V"]["debt"], 100.0 * 1_950_000_000 / 190_000_000)
        self.assertIsNone(C["V"]["current"])
        # 설립 해 11개월 매출 11억 → 연 12억 환산과 비교 (올해는 1월 장부뿐 → 1월 31일치로 연 환산)
        size = 1_000_000_000 / (31 / 365.0)
        self.assertAlmostEqual(C["V"]["growth"], 100.0 * (size - 1_200_000_000) / 1_200_000_000)
        self.assertIn("추정", K.render(C))
        self.assertTrue(any(t[0] == "부채비율 낮추기" for t in C["todo"]))

    def test_explain_names_last_grade_and_biggest_weakness(self):
        d = self.mk(inputs={"작년_결산연도": "2025", "작년_등급": "B+", "작년_평가사": "NICE D&B", "작년_부채비율": "586.4"})
        C = K.compute(d, D(2026, 12, 31), annual=True)
        lines = K.explain(C)
        self.assertIn("B+", lines[0])
        self.assertIn("투자 적격(BBB- 이상)보다 4칸 아래", lines[0])
        self.assertIn("부채비율 586.4%", lines[1])
        self.assertIn("B+", K.brief(C))

    def test_loan_maturity_from_memo_and_overdue(self):
        # 적요 '[만기일자:YYYY.MM.DD]'에서 대출별 만기를 읽음 (사용자 2026-11-13 실제 2025 분개장)
        d = tempfile.mkdtemp()
        self.dirs = getattr(self, "dirs", []) + [d]
        j = journal() + [ln(D(2026, 1, 20), "9", "10300", "보통예금", dr=200_000_000),
                         ln(D(2026, 1, 20), "9", "29300", "장기차입금", cr=200_000_000, memo="기보 대출 [만기일자:2026.04.17]"),
                         ln(D(2026, 6, 30), "10", "80200", "직원급여(판)", dr=1), ln(D(2026, 6, 30), "10", "10300", "보통예금", cr=1)]   # 장부가 만기 뒤까지
        j[13]["memo"] = "[만기일자:2027.04.21]"
        t = K.build_table(types.SimpleNamespace(state="ok", journal=j))
        with open(os.path.join(d, K.FILE), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, K.KEYS)
            w.writeheader()
            w.writerows(t.rows)
        C = K.compute(d, D(2026, 12, 31), annual=True)
        self.assertEqual(C["E"]["moved"], 500_000_000)
        self.assertTrue(any(t[0] == "만기 지난 대출 확인" for t in C["todo"]))

    def test_render_none(self):
        self.assertIn("계정잔액.csv", K.render(None))


if __name__ == "__main__":
    unittest.main()
