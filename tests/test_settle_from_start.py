"""미지급 지급 배분 (실제 자료 2026-11-11).

· 분개장이 회사 설립 달부터 있으면 전기이월 줄이 없어도 남은 지급을 오래된 항목부터 채운다 (법인카드: 여러 건을 한 번에 갚음).
· 먼저 낸 돈(선결제)은 그 뒤에 생긴 항목에 붙인다.
· 올해 분개장만 있으면 (설립 줄·전기이월 줄 없음) 예전처럼 같은 금액 지급만 짝짓는다.
"""
import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ceo_report import convert_projects as cp  # noqa: E402
from ceo_report import linking  # noqa: E402


class Books(object):
    def __init__(self, journal):
        self.journal = journal
        self.book_date = dt.date(2026, 11, 10)


def jl(day, no, code, debit, credit, vendor="신한_5860", memo=""):
    return {"date": day, "no": no, "account_code": code, "debit": debit, "credit": credit, "vendor": vendor,
            "vendor_norm": vendor, "memo": memo, "sort": "일반전표"}


CAPITAL = [jl(dt.date(2025, 2, 3), "00001", "10300", 10000000, None, "주주"), jl(dt.date(2025, 2, 3), "00001", "33100", None, 10000000, "주주")]
CARD = [   # 카드 사용 두 건(30만·20만)을 한 번에 50만 갚음
    jl(dt.date(2026, 3, 5), "00010", "26200", None, 300000),
    jl(dt.date(2026, 3, 9), "00011", "26200", None, 200000),
    jl(dt.date(2026, 4, 15), "00020", "26200", 500000, None),
]


def settle(journal):
    books = Books(journal)
    items, _, _, leftover_note, _ = cp._settle(books, linking.line_keys(journal), cp._code_set(("25300", "26200")))
    return sorted((it["amount"], it["remaining"]) for it in items.values()), leftover_note


class TestSettleFromStart(unittest.TestCase):
    def test_lump_payment_fills_old_items_when_journal_starts_at_founding(self):
        items, note = settle(CAPITAL + CARD)
        self.assertEqual(items, [(200000, 0), (300000, 0)])
        self.assertIn("미배분 지급 0건", note)

    def test_this_year_only_journal_keeps_exact_match_only(self):
        items, note = settle(CARD)
        self.assertEqual(items, [(200000, 200000), (300000, 300000)])
        self.assertIn("미배분 지급 1건 500,000", note)

    def test_prepayment_is_applied_to_later_items(self):
        pre = [jl(dt.date(2026, 5, 1), "00030", "26200", 700000, None),      # 선결제 70만
               jl(dt.date(2026, 5, 20), "00031", "26200", None, 450000),    # 그 뒤 카드 사용
               jl(dt.date(2026, 5, 25), "00032", "26200", None, 400000)]
        items, note = settle(CAPITAL + pre)
        self.assertEqual(items, [(400000, 150000), (450000, 0)])
        self.assertIn("미배분 지급 0건", note)


if __name__ == "__main__":
    unittest.main()
