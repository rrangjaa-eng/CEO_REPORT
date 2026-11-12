import datetime as dt
import os
import tempfile
import unittest

from ceo_report import surplus


def L(d, acct, debit=None, credit=None, sort="", memo="", code="37700"):
    return {"date": d, "account": acct, "account_code": code, "debit": debit, "credit": credit, "sort": sort, "memo": memo}


CLOSING = ("결산전표", "잉여금관련전표")


class Collect(unittest.TestCase):
    def test_first_year_closing_then_disposal(self):
        j = [L(dt.date(2025, 12, 31), "미처분이익잉여금", credit=150_000_000, sort="잉여금관련전표"),
             L(dt.date(2026, 3, 20), "미처분이익잉여금", debit=11_000_000),
             L(dt.date(2026, 3, 20), "이익준비금", credit=1_000_000, code="35100"),
             L(dt.date(2026, 3, 20), "미지급배당금", credit=10_000_000, code="26500")]
        years, first = surplus.collect(j, CLOSING)
        S = surplus.statements(years, first, (2026, 185_000_000, "예상 근거"))
        y25, y26 = S
        self.assertEqual(y25["전기이월"], 0)                 # 회사 첫해
        self.assertEqual(y25["당기순이익"], 150_000_000)
        self.assertEqual(y25["상태"], "확정")
        self.assertEqual((y25["이익준비금"], y25["배당금"]), (1_000_000, 10_000_000))   # 다음 해 주총 전표
        self.assertEqual(y25["차기이월"], 139_000_000)
        self.assertEqual(y26["전기이월"], 139_000_000)
        self.assertEqual(y26["당기순이익"], 185_000_000)
        self.assertEqual(y26["상태"], "예상")
        self.assertEqual(y26["미처분"], 324_000_000)
        self.assertEqual(y26["처분액"], 0)
        self.assertEqual(y26["차기이월"], 324_000_000)

    def test_unknown_opening_when_first_year_missing(self):
        j = [L(dt.date(2026, 5, 1), "보통예금", debit=1, code="10300")]
        years, first = surplus.collect(j, CLOSING)
        S = surplus.statements(years, first, (2026, 100, "e"))
        self.assertEqual(len(S), 1)
        self.assertIsNone(S[0]["전기이월"])
        self.assertIsNone(S[0]["미처분"])
        self.assertEqual(S[0]["당기순이익"], 100)

    def test_opening_line_used(self):
        j = [L(dt.date(2026, 1, 1), "미처분이익잉여금", credit=50, sort="전기이월")]
        years, first = surplus.collect(j, CLOSING)
        S = surplus.statements(years, first, (2026, 10, "e"))
        self.assertEqual(S[-1]["전기이월"], 50)
        self.assertEqual(S[-1]["미처분"], 60)

    def test_dec31_without_sort_is_closing(self):
        j = [L(dt.date(2025, 12, 31), "이월이익잉여금", credit=70)]
        years, first = surplus.collect(j, CLOSING)
        S = surplus.statements(years, first, None)
        self.assertEqual(S[0]["당기순이익"], 70)


class Balances(unittest.TestCase):
    def test_capital_and_reserve_from_founding_year(self):
        J = [L(dt.date(2025, 1, 2), "자본금", credit=10_000_000, code="33100"),
             L(dt.date(2026, 3, 31), "이익준비금", credit=1_000_000, code="35100"),
             L(dt.date(2026, 3, 31), "미처분이익잉여금", debit=1_000_000, code="37700")]
        b = surplus.balances(J, 2025)
        self.assertEqual(b[2025], {"자본금": 10_000_000, "이익준비금잔액": 0})
        self.assertEqual(b[2026], {"자본금": 10_000_000, "이익준비금잔액": 1_000_000})

    def test_unknown_without_founding_year_or_opening(self):
        J = [L(dt.date(2026, 3, 31), "이익준비금", credit=1_000_000, code="35100")]
        self.assertEqual(surplus.balances(J, 2026), {})
        J.append(L(dt.date(2026, 1, 1), "자본금", credit=10_000_000, sort="전기이월", code="33100"))
        self.assertEqual(surplus.balances(J, 2026)[2026]["자본금"], 10_000_000)


class ReportSide(unittest.TestCase):
    def test_csv_roundtrip_and_render(self):
        rows = []
        for st in surplus.statements(*surplus.collect(
                [L(dt.date(2025, 12, 31), "미처분이익잉여금", credit=150, sort="잉여금관련전표")], CLOSING), (2026, 30, "e")):
            for k in surplus.ITEMS + ["미처분", "처분액", "차기이월"]:
                v = st.get(k)
                rows.append([str(st["year"]), k, "" if v is None else str(v), "확정", ""])
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, surplus.FILE), "w", encoding="utf-8-sig") as f:
                f.write(",".join(surplus.KEYS) + "\n" + "\n".join(",".join(r) for r in rows))
            S = surplus.for_report(d, 2026)
        self.assertEqual(S["year"], 2026)
        self.assertEqual(S["cur"]["미처분"][0], 180)
        h = surplus.render(S)
        self.assertIn("이익잉여금처분계산서", h)
        self.assertIn("180", h)
        self.assertIn("세무사 확인", h)
        self.assertIn("2025년", h)   # 지난 해 처리 표
        self.assertIn("180", surplus.live_line(S))

    def test_render_none(self):
        self.assertIn("자료 없음", surplus.render(None))
        self.assertEqual(surplus.live_line(None), "")


if __name__ == "__main__":
    unittest.main()
