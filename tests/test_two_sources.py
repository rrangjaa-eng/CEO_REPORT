"""출금 출처 하나 원칙 점검 (사용자 2026-11-04): 같은 거래처·같은 달 출금이 두 출처에 있으면 목록."""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ceo_report import calc  # noqa: E402

D = dt.date


def ev(day, amount, source, desc="가상", code=""):
    return {"io": "out", "date": day, "amount": amount, "source": source, "desc": desc, "vendor_code": code}


class TestTwoSources(unittest.TestCase):
    def test_same_vendor_two_sources(self):
        evs = [ev(D(2026, 11, 10), 1000, "자금계획서", code="000101"), ev(D(2026, 11, 20), 500, "프로젝트집행", code="101"),
               ev(D(2026, 12, 10), 700, "자금일정"),                       # 다른 달
               ev(D(2026, 11, 3), 900, "자금일정", code="101"),             # 기준일 이전
               ev(D(2026, 11, 12), 300, "남은 예산", code="101")]           # 비교 대상 출처 아님
        got = calc.two_sources(evs, D(2026, 11, 4))
        self.assertEqual(len(got), 1)
        self.assertEqual(dict(got[0]["sources"]), {"자금계획서": 1000, "프로젝트집행": 500})
        self.assertEqual(got[0]["month"], "2026-11")

    def test_one_source_is_fine(self):
        evs = [ev(D(2026, 11, 10), 1000, "자금계획서"), ev(D(2026, 11, 20), 500, "자금계획서")]
        self.assertEqual(calc.two_sources(evs, D(2026, 11, 4)), [])


if __name__ == "__main__":
    unittest.main()
