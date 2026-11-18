"""2차 전수조사 제안 25 (2026-11-18): 작은 계산 고침 — 항목마다 예전 동작과 새 동작을 적는다."""
import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from ceo_report import cashflow as C  # noqa: E402

D = dt.date


def ln(day, no, code, name, dr=0, cr=0, vendor="", memo=""):
    return {"date": day, "no": no, "sort": "일반전표", "account_code": code, "account": name,
            "debit": dr or None, "credit": cr or None, "vendor": vendor, "memo": memo}


class TestDepositTerms(unittest.TestCase):
    """V17·J15: 만기 전 정기예금은 위하고 예적금현황의 가입일~만기일이 있으면 그것으로, 없을 때만 지난 예금으로 추정."""

    def journal(self):
        return [ln(D(2026, 1, 13), "1", "10500", "정기예.적금", dr=100, vendor="신한260113", memo="정기예금 가입"),
                ln(D(2026, 2, 13), "2", "10500", "정기예.적금", cr=100, vendor="신한260113", memo="정기예금 만기"),
                ln(D(2026, 11, 1), "3", "10500", "정기예.적금", dr=500, vendor="신한261101", memo="정기예금 가입")]

    def test_guess_without_registry(self):
        t = C.deposit_terms(self.journal())
        self.assertTrue(t["신한261101"][1])          # 지난 예금이 한 달짜리 → 현금성으로 추정 (예전 그대로)
        self.assertIn("추정", t["신한261101"][2])

    def test_registry_dates_win(self):
        t = C.deposit_terms(self.journal(), {"신한261101": (D(2026, 11, 1), D(2027, 11, 1))})
        self.assertEqual(t["신한261101"][:2], (365, False))   # 1년짜리 → 현금성 아님 (예전: 현금성으로 추정)
        self.assertIn("예적금현황", t["신한261101"][2])
        t = C.deposit_terms(self.journal(), {"신한261101": (D(2026, 11, 1), D(2026, 12, 1))})
        self.assertTrue(t["신한261101"][1])


class TestRunway(unittest.TestCase):
    """J14: 버틸 달 수는 끝난 달만으로 평균 (예전: 이번 달을 하루만 지나도 한 달로 셈)."""

    def cf(self, asof):
        rows = []
        for m in (8, 9, 10):
            rows.append((D(2026, m, 15), "현금", "업체", -30_000_000))
        rows.append((D(2026, 11, 2), "현금", "업체", -3_000_000))
        return {"M": {"rec": {"이익": 1, "받을돈": 0}, "op": 1}, "Y": {"rec": {"이익": 1, "받을돈": 0}, "op": 1},
                "end": 60_000_000, "_rows": rows, "p1": asof, "annual": False}

    def answer(self, asof):
        return [a for q, a, _ in C.health(self.cf(asof))[2] if q.startswith("버틸")][0]

    def test_mid_month_uses_finished_months(self):
        a = self.answer(D(2026, 11, 3))
        self.assertIn("8~10월", a)
        self.assertIn("2.0달 치", a)     # 6천만 ÷ 월 3천만 (예전: (3천+3천+3백)÷3 = 2,100만 → 2.9달)

    def test_month_end_includes_that_month(self):
        self.assertIn("9~11월", self.answer(D(2026, 11, 30)))


class TestWeekAgoRecord(unittest.TestCase):
    """P14: '지난주 대비'는 7일 전에 가장 가까운 기록과 (예전: 가장 최근 기록 → 매일 만들면 어제와 비교)."""

    def test_picks_the_record_nearest_to_seven_days_ago(self):
        import json
        import tempfile
        from ceo_report import insights
        with tempfile.TemporaryDirectory() as out:
            folder = os.path.join(out, insights.RECORD_DIR)
            os.makedirs(folder)
            for day in ("2026-11-10", "2026-11-11", "2026-11-16", "2026-11-17"):
                with open(os.path.join(folder, "일정_%s.json" % day), "w", encoding="utf-8") as f:
                    json.dump([day], f)
            self.assertEqual(insights.load_previous(out, D(2026, 11, 18)), ["2026-11-11"])
            os.remove(os.path.join(folder, "일정_2026-11-11.json"))
            os.remove(os.path.join(folder, "일정_2026-11-10.json"))
            self.assertEqual(insights.load_previous(out, D(2026, 11, 18)), ["2026-11-16"])   # 그 주 기록이 없으면 있는 것 중 가까운 것


class TestTaxPaidKind(unittest.TestCase):
    """P18: '지방소득세' 계정으로 낸 전표는 법인세 납부로 보지 않는다 (예전: 금액 0.5~1.5배만 봄)."""

    def test_local_tax_slip_is_not_corporate_tax(self):
        from ceo_report import corptax
        j = [ln(D(2026, 3, 20), "7", "26100", "미지급지방소득세", dr=9_000_000), ln(D(2026, 3, 20), "7", "10300", "보통예금", cr=9_000_000)]
        slips = corptax._bank_tax_slips(j, D(2026, 1, 1), D(2026, 4, 1), set(["13600"]))
        self.assertEqual([(s[1], s.kind) for s in slips], [(9_000_000, "지방")])
        self.assertFalse(corptax._paid(slips, 10_000_000, kind="법인세"))
        self.assertTrue(corptax._paid(slips, 10_000_000, kind="법인지방소득세"))

    def test_shared_account_still_decided_by_amount(self):
        from ceo_report import corptax
        j = [ln(D(2026, 3, 20), "7", "26100", "미지급법인세", dr=9_000_000), ln(D(2026, 3, 20), "7", "10300", "보통예금", cr=9_000_000)]
        slips = corptax._bank_tax_slips(j, D(2026, 1, 1), D(2026, 4, 1), set(["13600"]))
        self.assertTrue(corptax._paid(slips, 10_000_000, kind="법인세"))


class TestJournalMonths(unittest.TestCase):
    """P7: 분개장 기간 안의 달은 그 달 전표가 없어도 누적 파일의 예전 줄을 지운다 (빈 기간에 통째로 든 달은 남김)."""

    def test_span_minus_gap_months(self):
        from ceo_report import convert_pl

        class B:
            journal = [{"date": D(2026, 1, 5)}, {"date": D(2026, 6, 20)}]
            journal_gaps = [(D(2026, 2, 10), D(2026, 4, 30))]
        self.assertEqual(convert_pl.journal_months(B), {"2026-01", "2026-02", "2026-05", "2026-06"})   # 3·4월은 받은 자료가 없어 남김


class TestGasuEstimatedIncome(unittest.TestCase):
    """J24: 가수금 '예상 포함' 잔액은 예상 입금도 넣는 값이라 이름을 '예상 입금·지급 포함'으로. 끄개를 끄면 예상 입금을 뺀다."""

    def test_label_and_switch(self):
        from ceo_report import gasu
        self.assertEqual(gasu.ALL_LABEL, "예상 입금·지급 포함")
        self.addCleanup(setattr, gasu, "EST_IN_OUT", gasu.EST_IN_OUT)
        R = {"asof": D(2026, 11, 18), "s2": {"start": 100, "dated": [
            {"date": D(2026, 11, 19), "io": "in", "amount": 50, "firm": False},
            {"date": D(2026, 11, 19), "io": "in", "amount": 7, "firm": True},
            {"date": D(2026, 11, 19), "io": "out", "amount": 30, "firm": False}]}}
        self.assertEqual(gasu.path(R, False, D(2026, 11, 19))[-1][1], 127)
        gasu.EST_IN_OUT = False
        self.assertEqual(gasu.path(R, False, D(2026, 11, 19))[-1][1], 100 + 7 - 30)
        self.assertEqual(gasu.path(R, True, D(2026, 11, 19))[-1][1], 107)


class TestIntegrityDrift(unittest.TestCase):
    """P17: 정합성 점검에서 입력 파일 ↔ 새 변환 결과가 다르면 성공(0)으로 끝나지 않는다."""

    def test_drift_code_and_window_line(self):
        from ceo_report import integrity, winstate
        self.assertEqual(integrity.DRIFT_RC, 4)
        ok, line = winstate.rc_message("정합성", 4)
        self.assertFalse(ok)
        self.assertIn("새로 변환한 결과와 다릅니다", line)


class TestIntranetUnconverted(unittest.TestCase):
    """P19: 변환 뒤에 새로 받은 인트라넷 자료가 있으면 이체 파일 확인에서 막는다."""

    def test_newer_snapshot_blocks(self):
        import tempfile
        from ceo_report import gate, snapshot
        with tempfile.TemporaryDirectory() as root:
            inp = os.path.join(root, "입력")
            os.makedirs(inp)
            with open(os.path.join(inp, "변환결과.txt"), "w", encoding="utf-8") as f:
                f.write("변환 시각 2026-11-18 10:00:00\\n")
            self.assertEqual(gate.unconverted_intranet(inp), [])
            for name in ("인트라넷_20261118_093000", "인트라넷_20261118_113000"):
                os.makedirs(os.path.join(root, "수집", name))
                open(os.path.join(root, "수집", name, snapshot.INFO_FILE), "w").close()
            got = gate.unconverted_intranet(inp)
            self.assertEqual(len(got), 1)
            self.assertIn("인트라넷_20261118_113000", got[0])
            os.rename(os.path.join(root, "수집", "인트라넷_20261118_113000"), os.path.join(root, "수집", "인트라넷_20261118_095900"))
            self.assertEqual(gate.unconverted_intranet(inp), [])


if __name__ == "__main__":
    unittest.main()
