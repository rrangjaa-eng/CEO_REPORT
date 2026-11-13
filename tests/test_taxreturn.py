import csv
import datetime as dt
import os
import tempfile
import unittest

from ceo_report import taxreturn as tr

# 가짜 숫자 (과세표준 1억 → 산출 9백만, 최저한세 7백만)
ROWS = [["2025", "확정", "2025.01.01 ~ 2025.12.31", "1000000000", "97000000", "100000000", "9000000", "2000000", "7000000",
         "10000", "6990000", "900000", "7040000", "2026-03-10", "2026-03-31", "외부"],
        ["2026", "중간예납", "2026.01.01 ~ 2026.06.30", "600000000", "", "", "", "", "", "", "3495000", "", "3495000", "", "2026-08-20", ""]]


def folder():
    d = tempfile.mkdtemp()
    with open(os.path.join(d, tr.FILE), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(tr.COLUMNS)
        w.writerows(ROWS)
    return d


class Return(unittest.TestCase):
    def test_min_tax_and_notes(self):
        d = folder()
        last = tr.load(d)[(2025, "확정")]
        self.assertTrue(tr.at_min_tax(last))                 # 1억 × 7% = 7백만
        T = tr.for_report(d, dt.date(2026, 10, 31), 150_000_000, 15_000_000)
        self.assertEqual(T["adj"], 3_000_000)
        self.assertEqual(T["floor_now"], 10_500_000)
        txt = " ".join(T["notes"])
        self.assertIn("50,000원 다릅니다", txt)
        self.assertIn("3,495,000", txt)
        h = tr.render(T, lambda s: s)
        self.assertIn("최저한세 7%에 걸림", h)

    def test_no_file(self):
        self.assertIsNone(tr.for_report(tempfile.mkdtemp(), dt.date(2026, 10, 31)))

    def test_taxbreak_claim_row(self):
        from ceo_report import taxbreak
        d = folder()
        T = taxbreak.check(d, 2026, {"과밀억제": "아니오", "수도권": "예", "청년창업": "아니오", "신규창업": "예", "감면업종": "예",
                                      "작년감면": "없음", "연구전담": "아니오"})
        r = [x for x in T["rows"] if x[0].startswith("2025년분")][0]
        self.assertEqual(r[1], "해당 없음")


# 상세 신고서 칸까지 있는 가짜 숫자 (특별감면 150만·고용공제 50만·이월 2천만·농특세 10만, 승용차 7월 취득 6달 치 4백만)
DETAIL = ["2025", "확정", "2025.01.01 ~ 2025.12.31", "1000000000", "98000000", "100000000", "9000000", "2000000", "7000000",
          "10000", "6990000", "900000", "7090000", "2026-03-10", "2026-03-31", "외부",
          "1500000", "500000", "20000000", "100000", "4000000", "2000000", "2025-07-01"]


def detail_folder(manual_dep=None):
    d = tempfile.mkdtemp()
    with open(os.path.join(d, tr.FILE), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(tr.COLUMNS)
        w.writerow(DETAIL)
    if manual_dep is not None:
        from ceo_report import corptax
        with open(os.path.join(d, corptax.DEP_FILE), "w", encoding="utf-8-sig", newline="") as f:
            f.write("연도,연간감가상각비\n2026,%d\n" % manual_dep)
    return d


class Detail(unittest.TestCase):
    def test_credits_floor_and_nong(self):
        C = tr.credits(detail_folder(), 2026, 150_000_000, 15_000_000)
        self.assertEqual(C["sp"], 2_500_000)          # 15백만 × (150만/9백만)
        self.assertEqual(C["floor"], 10_500_000)
        self.assertEqual(C["used"], 2_000_000)        # 남은 여유만큼만
        self.assertEqual(C["final"], 10_500_000)
        self.assertEqual(C["nong"], 400_000)
        self.assertEqual(C["national"], 10_900_000)
        self.assertEqual(C["carry_next"], 18_000_000)
        self.assertTrue(C["at_floor"])

    def test_no_detail_no_credits(self):
        self.assertIsNone(tr.credits(folder(), 2026, 150_000_000, 15_000_000))

    def test_national_in_corptax(self):
        from ceo_report import corptax
        d = detail_folder()
        self.assertEqual(corptax.national(150_000_000, "2026", d)[:2], (10_900_000, 15_000_000))
        self.assertEqual(corptax.national(150_000_000, "2026", None)[:2], (15_000_000, 15_000_000))

    def test_notes_explain(self):
        T = tr.for_report(detail_folder(), dt.date(2026, 10, 31), 150_000_000, 15_000_000)
        txt = " ".join(T["notes"])
        self.assertIn("중소기업 특별세액감면", txt)
        self.assertIn("농어촌특별세", txt)
        self.assertIn("가산세 아님", txt)            # 실제 납부 − 차감납부 = 농특세
        self.assertIn("승용차 감가상각비 한도 넘은 2,000,000원", txt)
        h = tr.render(T, lambda s: s)
        self.assertIn("감면·공제 적용", h)
        self.assertIn("+ 농어촌특별세", h)

    def test_car_dep_adjust(self):
        from ceo_report import taxadj
        n, v, on, why = taxadj._car_dep(detail_folder(), 2026, (8_000_000, True, ""))
        self.assertEqual(v, -4_000_000)               # 4백만(6달) → 1년 8백만, 한도 8백만 모두 인정
        self.assertTrue(on)
        n, v, on, why = taxadj._car_dep(detail_folder(9_000_000), 2026, (8_000_000, True, ""))
        self.assertEqual(v, 0)                        # 직접 넣은 해: 1년 치 8백만 − 한도 8백만

    def test_car_dep_with_ledger(self):
        from ceo_report import taxadj, corptax
        d = detail_folder()
        with open(os.path.join(d, corptax.LEDGER_FILE), "w", encoding="utf-8-sig", newline="") as f:
            f.write("기준연도,자산,계정,취득일,취득가,상각률,전기말상각누계,당기상각,당기말상각누계\n2026,차,차량운반구,2025-07-01,40000000,0.2,4000000,10000000,14000000\n")
        self.assertEqual(corptax.read_ledger(d), {"2026": 10_000_000})
        n, v, on, why = taxadj._car_dep(d, 2026, (8_000_000, True, ""))
        self.assertEqual(v, 2_000_000)                # 대장 1년 치 1천만 − 한도 8백만
        self.assertIn("고정자산대장", why)
        D = corptax.depreciation([], {}, "2026-10", ledger=corptax.read_ledger(d))
        self.assertEqual((D["annual"], D["source"]), (10_000_000, "고정자산대장"))

    def test_taxbreak_rows(self):
        from ceo_report import taxbreak
        T = taxbreak.check(detail_folder(), 2026, {"과밀억제": "예", "수도권": "예", "청년창업": "아니오"})
        rows = dict((r[0], r) for r in T["rows"])
        self.assertEqual(rows["창업중소기업 세액감면"][1], "해당 없음")
        self.assertEqual(rows["중소기업 특별세액감면"][1], "해당")
        self.assertEqual(rows["통합고용세액공제 (넘어온 몫)"][2], 20_000_000)


if __name__ == "__main__":
    unittest.main()
