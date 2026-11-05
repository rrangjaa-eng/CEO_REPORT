"""지난해 프로젝트는 참고로만 (사용자 2026-11-04: '2025년 프로젝트는 맞추지 말고 참고 자료로만. 입금·지급 모두 끝남').

- 연결: 장부 마지막 해보다 앞선 날짜, 또는 예전 번호 체계([3자리]) 코드 줄은 코드·자동 연결 없이 참고. 수동 지정만 따른다.
- 프로젝트집행.csv 근거에 data.PRIOR_TAG 가 붙은 줄은 번호 빈칸 알림·미연결 집계·가용자금 일정에 들어가지 않는다.
"""
import csv
import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report import calc, linking  # noqa: E402
from ceo_report.data import PRIOR_TAG, load  # noqa: E402
from sample_input import SAMPLE, refresh  # noqa: E402

ASOF = dt.date(2026, 11, 2)


def _ln(day, code=None, slip=None):
    return {"date": day, "code": code, "slip_code": slip}


class TestPriorRule(unittest.TestCase):
    def test_old_code(self):
        self.assertTrue(linking.is_old_code("93"))
        self.assertTrue(linking.is_old_code("093"))
        self.assertFalse(linking.is_old_code("26053"))
        self.assertFalse(linking.is_old_code(""))
        self.assertFalse(linking.is_old_code("AB1"))

    def test_prior_by_year_or_old_code(self):
        self.assertTrue(linking._prior(_ln(dt.date(2025, 12, 31))))
        self.assertFalse(linking._prior(_ln(dt.date(2026, 1, 1), "26053")))
        self.assertTrue(linking._prior(_ln(dt.date(2026, 1, 1), slip="93")))   # 2026 분개장의 2025_선급금대체
        self.assertFalse(linking._prior(_ln(None)))
        # 작년 날짜라도 지금 체계 5자리 코드면 올해 프로젝트 (작년 말 선금)
        self.assertFalse(linking._prior(_ln(dt.date(2025, 12, 20), "26001")))
        # 해가 바뀌어도 2026 줄이 저절로 '지난해'가 되지 않는다 (기준 해는 설정값)
        self.assertFalse(linking._prior(_ln(dt.date(2026, 6, 1))))


class TestPriorInvoices(unittest.TestCase):
    def test_prior_unpaid_moves_to_this_year(self):
        from ceo_report import convert_invoices as CI

        def inv(i, day, total, applied, basis):
            return {"idx": i, "date": day, "total": total, "deducted": 0, "applied": applied, "vendor_norm": "가",
                    "basis": basis, "paid_date": day if applied else None}
        old = inv(0, dt.date(2025, 12, 1), 1000, 400, "참고")
        a = inv(1, dt.date(2026, 3, 1), 500, 500, "코드")
        b = inv(2, dt.date(2026, 9, 1), 500, 500, "코드")
        c = inv(3, dt.date(2026, 10, 1), 300, 300, "코드")
        c["exact"] = True   # 같은 금액 입금으로 맞춘 계산서는 건드리지 않는다
        moved = CI._settle_prior([old, a, b, c])
        self.assertEqual(c["applied"], 300)
        self.assertEqual(moved, [("가", 600)])
        self.assertEqual(old["applied"], 1000)          # 지난해 계산서는 다 들어온 것으로
        self.assertEqual((a["applied"], b["applied"]), (400, 0))   # 최근 계산서부터 미수로
        self.assertIsNone(b["paid_date"])
        self.assertEqual(sum(x["total"] - x["applied"] for x in (old, a, b, c)), 600)   # 거래처 미수 합계는 그대로

    def test_prior_credit_note_nets_first(self):
        """지난해 수정 계산서(−)는 지난해 미수와 먼저 상계한다 (실제 자료: 지난해 + 미수 1.8억 · − 1.88억)."""
        from ceo_report import convert_invoices as CI

        def inv(i, day, total, applied, basis):
            return {"idx": i, "date": day, "total": total, "deducted": 0, "applied": applied, "vendor_norm": "가",
                    "basis": basis, "paid_date": None}
        pos = inv(0, dt.date(2025, 11, 1), 1000, 0, "참고")
        neg = inv(1, dt.date(2025, 12, 1), -1200, 0, "참고")
        cur = inv(2, dt.date(2026, 3, 1), 500, 0, "코드")
        moved = CI._settle_prior([pos, neg, cur])
        self.assertEqual(moved, [("가", -200)])   # 지난해에 200 더 받음 → 올해 미수 200 줄어듦
        rest = lambda i: i["total"] - i["applied"]
        self.assertEqual((rest(pos), rest(neg), rest(cur)), (0, 0, 300))
        both = [inv(0, dt.date(2025, 11, 1), 1000, 0, "참고"), inv(1, dt.date(2025, 12, 1), -1000, 0, "참고")]
        self.assertEqual(CI._settle_prior(both), [])
        self.assertEqual([rest(i) for i in both], [0, 0])

    def test_prior_invoice_rule(self):
        from ceo_report import convert_invoices as CI
        self.assertTrue(CI._prior({"date": dt.date(2025, 5, 1), "code": None}))
        self.assertTrue(CI._prior({"date": dt.date(2026, 1, 2), "code": "93"}))
        self.assertFalse(CI._prior({"date": dt.date(2026, 1, 2), "code": "26053"}))


class TestPriorRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        refresh()
        path = os.path.join(SAMPLE, "프로젝트집행.csv")
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))
        head = rows[0]
        row = dict((h, "") for h in head)
        row.update({"항목": "작년 원가", "거래처": "가상거래처", "상태": "요청미지급", "공급가액": "1000000", "부가세": "100000",
                    "일자": "2025-12-15", "확정여부": "확정", "근거": "WEHAGO 2025-12-15 전표 50001 · %s [93]" % PRIOR_TAG})
        rows.append([row[h] for h in head])
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(rows)
        cls.d = load(SAMPLE)
        cls.R = calc.compute(load(SAMPLE), "weekly", ASOF)

    def test_no_blank_number_issue(self):
        texts = [str(x) for x in self.d.issues.items] if hasattr(self.d.issues, "items") else [str(self.d.issues)]
        self.assertFalse(any("빈칸 줄" in t for t in texts))

    def test_not_unlinked_and_not_scheduled(self):
        s3 = self.R["s3"]
        self.assertEqual(len(s3["prior"]), 1)
        self.assertEqual(s3["prior_total"], 1000000)
        self.assertFalse([e for e in s3["unlinked"] if PRIOR_TAG in e["basis"]])
        self.assertFalse([e for e in self.R["events"] if PRIOR_TAG in str(e.get("basis") or "")])
        self.assertEqual(self.R["intranet_only"]["requests"][0],
                         calc.compute(self._without(), "weekly", ASOF)["intranet_only"]["requests"][0])

    def _without(self):
        d = load(SAMPLE)
        d.execs = [e for e in d.execs if PRIOR_TAG not in e["basis"]]
        return d

    def test_line_count_check_holds(self):
        bad = [c for c in self.R["s7"]["checks"] if "프로젝트집행 줄 수" in c[0] and not c[3]]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
