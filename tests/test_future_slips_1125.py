"""분개장을 12월 31일까지 받기 (사용자 2026-11-25 카드 '분개장을 연말까지 받기').

11/25 실제: 위하고 재무상태표(18:52) 미지급금 431,603,582 · 분개장(18:45, 1/1~11/25)·시산표(18:58) 420,803,582.
재무상태표는 오늘 뒤 날짜로 미리 넣은 전표까지 담아 대표 보고에 거짓 '자료 대조 경고 · 미지급금 10,800,000원'이 났다.
고침: 확장은 분개장을 1/1~12/31로 받고, 보고 계산(변환 장부)은 받은 날까지만, 올해 재무상태표·손익계산서 대조만 12/31까지."""
import datetime as dt
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from ceo_report import reconcile as RC, wehago  # noqa: E402
from test_journal_json import COLS, write_json  # noqa: E402
from test_reconcile import save, raw  # noqa: E402

D = dt.date
ROOT = os.path.dirname(HERE)


def jrow(day, no, side, acct, amt, sq, ins="2026-11-20T10:00:00.000"):
    return [day, no, "일반전표", side, acct, "", amt if side == "차변" else 0, amt if side == "대변" else 0,
            "", "", "", "", "", "", ins, sq]


def jdoc(rows, end="20261231", when="2026-11-25 18:45:13"):
    return {"종류": "분개장", "형식": 1, "수집시각": when, "회사": "가상회사",
            "기간": {"start_date": "20260101", "end_date": end, "gisu": "2"},
            "전표수": len(set((r[0], r[1]) for r in rows)), "줄수": len(rows), "열": COLS, "줄": rows}


TODAY_ROWS = [jrow("20261124", "00001", "차변", "82100", 420_803_582, 1), jrow("20261124", "00001", "대변", "25300", 420_803_582, 2),
              jrow("20261125", "00002", "차변", "10300", 1_000, 3), jrow("20261125", "00002", "대변", "40100", 1_000, 4)]
FUTURE_ROWS = [jrow("20261201", "00001", "차변", "83100", 10_800_000, 5, "2026-11-24T10:00:00.000"),
               jrow("20261201", "00001", "대변", "25300", 10_800_000, 6, "2026-11-24T10:00:00.000")]


def bs_main(bal):
    """{계정코드: 화면 금액(부호 없음)} -> 재무상태표 /main 응답."""
    return {"error_str": "", "main": [{"cd_acctit": c, "nm_acctit": c, "mn_bungae": "{:,}".format(v), "mn_bungae_right": v}
                                      for c, v in bal.items()]}


class TestReportBooksStopAtTakenDay(unittest.TestCase):
    """보고 계산(변환 장부)은 예전처럼 받은 날까지만 — 12/31까지 받아도 숫자가 바뀌지 않는다."""

    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.t)

    def test_future_lines_left_out_and_period_ends_on_taken_day(self):
        p = os.path.join(self.t, "261125 분개장 자동수집.json")
        write_json(self.t, os.path.basename(p), jdoc(TODAY_ROWS + FUTURE_ROWS))
        rows = wehago.read_journal_json(p)
        self.assertEqual(len(rows) - 1, len(TODAY_ROWS))
        self.assertTrue(all(r[0] <= "2026-11-25" for r in rows[1:]))
        self.assertEqual(rows.period, (D(2026, 1, 1), D(2026, 11, 25)))
        self.assertEqual(rows.future_lines, 2)
        self.assertIsNone(wehago.short_period(rows.period, rows.taken))   # 받은 날까지 덮음 → '기간 짧음' 경고 없음

    def test_same_as_old_file_ending_today(self):
        a = os.path.join(self.t, "a.json")
        b = os.path.join(self.t, "b.json")
        write_json(self.t, "a.json", jdoc(TODAY_ROWS + FUTURE_ROWS))
        write_json(self.t, "b.json", jdoc(TODAY_ROWS, end="20261125"))
        ra, rb = wehago.read_journal_json(a), wehago.read_journal_json(b)
        self.assertEqual(list(ra), list(rb))
        self.assertEqual(ra.period, rb.period)

    def test_last_year_file_untouched(self):
        rows = [jrow("20251231", "00001", "차변", "82100", 5, 1), jrow("20251231", "00001", "대변", "25300", 5, 2)]
        d = jdoc(rows, end="20251231", when="2026-01-10 09:00:00")
        d["기간"]["start_date"] = "20250101"
        write_json(self.t, "x.json", d)
        r = wehago.read_journal_json(os.path.join(self.t, "x.json"))
        self.assertEqual((len(r) - 1, r.period, r.future_lines), (2, (D(2025, 1, 1), D(2025, 12, 31)), 0))


class TestBalanceSheetWithFutureSlips(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.t)
        self.journal = [{"date": D(2026, 11, 10), "account_code": "82100", "debit": 420_803_582, "credit": 0},
                        {"date": D(2026, 11, 10), "account_code": "25300", "debit": 0, "credit": 420_803_582}]

    def _bs(self, when, bal, name="261125 결산_재무상태표 자동수집.json"):
        save(self.t, name, raw("SACL0105", when, {"/smarta/sacl0105/main/": bs_main(bal)}))

    def _rows(self):
        jf = RC.journal_files(self.t)
        return RC.balances_rows(self.journal, RC.raw_files(self.t), jf[0][0], RC._insert_times(jf[0]), jf)

    def test_year_end_journal_makes_it_equal(self):
        save(self.t, "261125 분개장 자동수집.json", jdoc(TODAY_ROWS + FUTURE_ROWS))
        self._bs("2026-11-25 18:52:46", {"25300": 431_603_582})
        rows = self._rows()
        self.assertEqual([r["판정"] for r in rows], ["같음"], rows)

    def test_year_end_journal_still_finds_real_gap(self):
        save(self.t, "261125 분개장 자동수집.json", jdoc(TODAY_ROWS + FUTURE_ROWS))
        self._bs("2026-11-25 18:52:46", {"25300": 431_603_582 + 30_000_000})
        r = [x for x in self._rows() if x["항목"] == "미지급금"][0]
        self.assertEqual((r["판정"], r["대표경고"]), ("다름", "예"))

    def test_journal_only_to_today_is_reference_without_ceo_warning(self):
        # 11/25 실제 모양 (예전 확장: 분개장 1/1~11/25) → 대표 경고 없음, 까닭을 적음
        save(self.t, "261125 분개장 자동수집.json", jdoc(TODAY_ROWS, end="20261125"))
        self._bs("2026-11-25 18:52:46", {"25300": 431_603_582})
        r = [x for x in self._rows() if x["항목"] == "미지급금"][0]
        self.assertEqual((r["판정"], r["대표경고"], r["차이"]), ("참고", "", "-10800000"))
        self.assertIn("미리 넣은 전표", r["할일"])

    def test_old_balance_sheet_compared_to_its_own_day(self):
        # 분개장과 따로 받은 지난 재무상태표(11/19)는 예전처럼 그날까지 장부와 견준다 (12/31로 늘리면 거짓 차이가 늘었음)
        save(self.t, "261125 분개장 자동수집.json", jdoc(TODAY_ROWS + FUTURE_ROWS))
        self.journal.append({"date": D(2026, 11, 22), "account_code": "25300", "debit": 0, "credit": 5})
        self.journal.append({"date": D(2026, 11, 22), "account_code": "82100", "debit": 5, "credit": 0})
        self._bs("2026-11-19 16:36:53", {"25300": 420_803_582}, "261119 결산_재무상태표 자동수집.json")
        rows = self._rows()
        self.assertEqual([r["판정"] for r in rows], ["같음"], rows)

    def test_future_row_shown_in_management(self):
        save(self.t, "261125 분개장 자동수집.json", jdoc(TODAY_ROWS + FUTURE_ROWS))
        rows = RC.future_rows(RC.journal_files(self.t), D(2026, 11, 25))
        self.assertEqual(len(rows), 1)
        self.assertIn("2줄 (2026-12-01 ~ 2026-12-01)", rows[0]["할일"])
        save(self.t, "261125 분개장 자동수집.json", jdoc(TODAY_ROWS, end="20261125"))
        self.assertEqual(RC.future_rows(RC.journal_files(self.t), D(2026, 11, 25)), [])

    def test_late_slip_compare_ignores_future_lines(self):
        # 지난 수집 비교(늦게 들어온 전표·지워진 줄)는 받은 날까지만 본다: 미리 넣은 전표가 바뀌어도 '지난 수집 뒤 바뀐 줄'로 안 셈
        save(self.t, "261120 분개장 자동수집.json", jdoc(TODAY_ROWS[:2] + FUTURE_ROWS, when="2026-11-20 10:00:00"))
        changed = [r[:] for r in FUTURE_ROWS]
        changed[0][6] = changed[1][7] = 99
        save(self.t, "261125 분개장 자동수집.json", jdoc(TODAY_ROWS + changed))
        jf = RC.journal_files(self.t)
        rows = RC.diff_rows(jf[1], jf[0])
        self.assertFalse([r for r in rows if r["항목"].startswith("지워진 줄")], rows)


class TestExtensionAsksYearEnd(unittest.TestCase):
    def test_collect_journal_opens_whole_year(self):
        with open(os.path.join(ROOT, "chrome_extension", "background.js"), encoding="utf-8") as f:
            bg = f.read()
        self.assertIn('const url = screenUrl(src.url, SCREEN["분개장"], year) || (lastYear ? null : screenUrl(src.url, SCREEN["분개장"]));', bg)
        self.assertIn(".replace(/([?&]searchData=)\\d+/, `$1${year}0101${year}1231`)", bg)


if __name__ == "__main__":
    unittest.main()
