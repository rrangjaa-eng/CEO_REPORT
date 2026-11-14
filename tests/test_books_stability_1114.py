"""변환·장부 읽기 안정성 (점검 문서 2026-11-14 8절 K2·K3·K4). 합성 자료만 쓴다.

K3: 지난 기수 분개장을 일부 기간(예: 12월)만 다시 받아도 1년치 파일을 밀어내지 않는다. 해마다 파일들의 기간을 합치고
    (같은 날짜는 더 새 파일 것만 = 같은 전표 한 번), 어느 파일에도 없는 기간이 있으면 '[확인]' + 통장 잔액을 분개장으로 만들지 않는다.
K2: 지난 기수 파일을 읽지 못하면 조용히 건너뛰지 않고 변환결과·경영관리('입력 자료 확인 필요')에 한 줄.
K4: 변환결과.txt 를 못 쓰면 CSV 와 함께 자동분석.json·확인할것.json·자금일정·지급요청서도 되돌린다. 동시에 두 변환이 돌지 않게 입력 폴더 잠금.
"""
import datetime as dt
import os
import shutil
import sys
import tempfile
import time
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from ceo_report import app, convert, data, wehago  # noqa: E402
from test_journal_partial import line, write  # noqa: E402
from test_convert import setUpModule  # noqa: E402,F401  (샘플을 임시 폴더에 새로 쓴다)

ASOF = dt.date(2026, 11, 14)
Y25_FULL = "2025년 02월 01일 ~ 2025년 12월 31일"
Y25_DEC = "2025년 12월 01일 ~ 2025년 12월 31일"
Y25_TO_SEP = "2025년 02월 01일 ~ 2025년 09월 30일"
Y26 = "2026년 01월 01일 ~ 2026년 11월 13일"


def bank(day, no, amount, memo, vendor="가상은행"):
    """보통예금 입금 (대변 = 매출채권)."""
    return [(day, no, "10300", "보통예금", memo, float(amount), "", vendor, "", "일반전표"),
            (day, no, "10800", "외상매출금", memo, "", float(amount), "가상고객", "", "일반전표")]


def capital(day="02/01", no="1", amount=20000000):
    return [(day, no, "10300", "보통예금", "설립 자본금", float(amount), "", "가상은행", "", "일반전표"),
            (day, no, "33100", "자본금", "설립 자본금", "", float(amount), "", "", "일반전표")]


def months_2025(last=12, skip_dec=False):
    rows = capital()
    for m in range(2, last + 1):
        if skip_dec and m == 12:
            continue
        rows += bank("%02d/15" % m, str(m + 10), 1000000, "%d월 입금" % m)
    return rows


def cash(b):
    return sum((r["debit"] or 0) - (r["credit"] or 0) for r in b.journal if r["account_code"] == "10300")


class TestPriorYearMerge(unittest.TestCase):
    """K3."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def load(self):
        b = wehago.load_books(self.dir, ASOF, None)
        self.assertEqual(b.state, "ok", b.reason)
        return b

    def test_december_redownload_does_not_push_out_the_full_year(self):
        write(self.dir, "261103 분개장_2025.xls", Y25_FULL, months_2025())
        # 12월만 다시 받음: 12월 입금이 고쳐짐 (100만 → 150만), 더 새 파일
        write(self.dir, "261113 분개장_2025.xls", Y25_DEC, bank("12/15", "22", 1500000, "12월 입금 고침"))
        write(self.dir, "261114 분개장.xls", Y26, bank("01/15", "1", 3000000, "1월 입금") + line("02/10", "2", 100, "매입"))
        b = self.load()
        self.assertEqual(b.files["분개장"]["name"], "261114 분개장.xls")
        self.assertEqual(b.files["분개장"]["prior"], ["261103 분개장_2025.xls", "261113 분개장_2025.xls"])
        memos = sorted((r["date"].isoformat(), r["memo"]) for r in b.journal if r["account_code"] == "10300")
        self.assertIn(("2025-03-15", "3월 입금"), memos)          # 1년치 파일이 밀려나지 않음
        self.assertIn(("2025-12-15", "12월 입금 고침"), memos)     # 12월은 더 새 파일 것
        self.assertNotIn(("2025-12-15", "12월 입금"), memos)       # 같은 날짜는 한 번만
        # 자본금 2천만 + 2~11월 10개월 × 100만 + 12월 150만 + 2026년 1월 300만
        self.assertEqual(cash(b), 20000000 + 10 * 1000000 + 1500000 + 3000000)
        self.assertTrue(b.from_start)
        self.assertEqual(b.journal_gaps, [])
        self.assertFalse(any("어느 파일에도 없음" in n for n in b.notes), b.notes)
        self.assertEqual(b.unused, [])

    def test_old_files_keeps_every_prior_year_file_still_used(self):
        write(self.dir, "261103 분개장_2025.xls", Y25_FULL, months_2025())
        write(self.dir, "261113 분개장_2025.xls", Y25_DEC, bank("12/15", "22", 1500000, "12월 입금 고침"))
        write(self.dir, "261114 분개장.xls", Y26, bank("01/15", "1", 3000000, "1월 입금") + line("02/10", "2", 100, "매입"))
        moved = [n for n, _ in app.old_files(self.dir, ASOF)]
        self.assertNotIn("261103 분개장_2025.xls", moved)
        self.assertNotIn("261113 분개장_2025.xls", moved)

    def test_newer_full_year_still_wins_and_older_is_unused(self):
        write(self.dir, "261103 분개장_2025.xls", Y25_FULL, months_2025())
        write(self.dir, "261113 분개장_2025.xls", Y25_FULL, months_2025()[:-2] + bank("12/15", "22", 1500000, "12월 입금 고침"))
        write(self.dir, "261114 분개장.xls", Y26, bank("01/15", "1", 3000000, "1월 입금") + line("02/10", "2", 100, "매입"))
        b = self.load()
        self.assertEqual(b.files["분개장"]["prior"], ["261113 분개장_2025.xls"])
        self.assertEqual(b.unused, ["261103 분개장_2025.xls"])
        self.assertEqual(cash(b), 20000000 + 10 * 1000000 + 1500000 + 3000000)

    def test_missing_months_are_flagged_and_balance_not_built_from_journal(self):
        """2~9월 파일 + 12월만 받은 파일: 10~11월이 어느 파일에도 없다 → 확인 + 통장 잔액은 분개장으로 만들지 않는다."""
        write(self.dir, "261103 분개장_2025.xls", Y25_TO_SEP, months_2025(last=9))
        write(self.dir, "261113 분개장_2025.xls", Y25_DEC, bank("12/15", "22", 1500000, "12월 입금"))
        write(self.dir, "261114 분개장.xls", Y26, bank("01/15", "1", 3000000, "1월 입금") + line("02/10", "2", 100, "매입"))
        b = self.load()
        self.assertEqual(b.journal_gaps, [(dt.date(2025, 10, 1), dt.date(2025, 11, 30))])
        self.assertTrue(any(n.startswith("[확인] 분개장 2025-10-01~2025-11-30") for n in b.notes), b.notes)
        self.assertFalse(b.from_start)
        self.assertIn("2025-10-01~2025-11-30", b.start_gap)
        cfg = dict(convert.DEFAULT_CONFIG)
        bal, txn = convert.build_bank(b, cfg)
        self.assertEqual(bal.rows, [])
        self.assertTrue(any("빈 기간" in n for n in bal.notes), bal.notes)

    def test_missing_current_year_months_between_prior_and_current(self):
        write(self.dir, "261103 분개장_2025.xls", Y25_FULL, months_2025())
        write(self.dir, "261114 분개장.xls", "2026년 03월 01일 ~ 2026년 11월 13일", bank("03/15", "1", 3000000, "3월 입금") + line("04/10", "2", 100, "매입"))
        b = self.load()
        self.assertEqual(b.journal_gaps, [(dt.date(2026, 1, 1), dt.date(2026, 2, 28))])
        self.assertFalse(b.from_start)

    def test_unreadable_prior_file_is_said_not_silently_skipped(self):
        write(self.dir, "261103 분개장_2025.xls", Y25_FULL, months_2025())
        with open(os.path.join(self.dir, "261113 분개장_2025.json"), "w", encoding="utf-8") as f:
            f.write("{깨진")
        write(self.dir, "261114 분개장.xls", Y26, bank("01/15", "1", 3000000, "1월 입금") + line("02/10", "2", 100, "매입"))
        b = self.load()
        self.assertEqual(b.files["분개장"]["prior"], ["261103 분개장_2025.xls"])
        hit = [n for n in b.notes if "261113 분개장_2025.json" in n]
        self.assertTrue(hit and hit[0].startswith("[확인]") and "읽지 못해" in hit[0], b.notes)


if __name__ == "__main__":
    unittest.main()


# ───────────── K2·K4: 변환 한 번 단위 ─────────────
def _company(test):
    from test_approval import write_fake_snapshot
    from test_convert import convert_input, write_convert_books
    tmp, input_dir, collect, wehago_dir = convert_input(test)
    write_convert_books(wehago_dir)
    write_fake_snapshot(collect)
    return input_dir, collect, wehago_dir


def _run(input_dir, collect, wehago_dir):
    return convert.run(input_dir, collect, wehago_dir, dt.date(2026, 11, 2), dt.datetime(2026, 11, 2, 0, 0))


def _bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


class TestBookNotesReachReports(unittest.TestCase):
    """K2: 지난 기수 파일을 못 읽으면 변환결과.txt 와 경영관리 '입력 자료 확인 필요'에 한 줄."""

    def test_unreadable_prior_file_is_in_result_and_in_report_issues(self):
        input_dir, collect, wehago_dir = _company(self)
        with open(os.path.join(wehago_dir, "분개장_2025.json"), "w", encoding="utf-8") as f:
            f.write("{깨진")
        res = _run(input_dir, collect, wehago_dir)
        self.assertEqual(res.code, 0, res.lines)
        with open(os.path.join(input_dir, "변환결과.txt"), encoding="utf-8-sig") as f:
            text = f.read()
        self.assertIn("분개장_2025.json", text)
        d = data.load(input_dir)
        hit = [m for f, _, m in d.issues.items if f == data.BOOK_NOTE_FILE and "분개장_2025.json" in m]
        self.assertTrue(hit and "읽지 못해" in hit[0], d.issues.items)

    def test_no_notes_writes_header_only_and_clears_old_notes(self):
        input_dir, collect, wehago_dir = _company(self)
        with open(os.path.join(input_dir, data.BOOK_NOTE_FILE), "w", encoding="utf-8-sig") as f:
            f.write("알림\n[확인] 지난 변환의 알림\n")
        _run(input_dir, collect, wehago_dir)
        d = data.load(input_dir)
        self.assertFalse([m for f, _, m in d.issues.items if "지난 변환의 알림" in m])


class TestConvertLock(unittest.TestCase):
    """K4: 같은 입력 폴더에 두 변환이 동시에 돌지 않는다."""

    def test_second_run_while_locked_changes_nothing(self):
        input_dir, collect, wehago_dir = _company(self)
        lock = os.path.join(input_dir, convert.LOCK_FILE)
        with open(lock, "w") as f:
            f.write("1 다른 창")
        before = sorted(os.listdir(input_dir))
        res = _run(input_dir, collect, wehago_dir)
        self.assertEqual(res.code, 7)
        self.assertIn("이미 돌고 있어", res.lines[0])
        self.assertEqual(sorted(os.listdir(input_dir)), before)
        self.assertTrue(os.path.exists(lock))   # 남의 잠금은 지우지 않는다

    def test_stale_lock_is_cleared_and_own_lock_removed_after(self):
        input_dir, collect, wehago_dir = _company(self)
        lock = os.path.join(input_dir, convert.LOCK_FILE)
        with open(lock, "w") as f:
            f.write("1 꺼진 창")
        old = time.time() - convert.LOCK_STALE_SECONDS - 60
        os.utime(lock, (old, old))
        res = _run(input_dir, collect, wehago_dir)
        self.assertEqual(res.code, 0, res.lines)
        self.assertFalse(os.path.exists(lock))

    def test_lock_removed_even_when_conversion_raises(self):
        input_dir, collect, wehago_dir = _company(self)
        with unittest.mock.patch.object(convert, "_run", side_effect=RuntimeError("뜻밖")):
            with self.assertRaises(RuntimeError):
                _run(input_dir, collect, wehago_dir)
        self.assertFalse(os.path.exists(os.path.join(input_dir, convert.LOCK_FILE)))


class TestSideFilesRollBack(unittest.TestCase):
    """K4: 변환결과.txt 를 못 쓰면 자동분석.json·확인할것.json·자금일정·지급요청서도 변환 전으로."""

    def test_side_files_restored_when_result_write_fails(self):
        from ceo_report import checklist, insights, payreq, review_checks
        input_dir, collect, wehago_dir = _company(self)
        self.assertEqual(_run(input_dir, collect, wehago_dir).code, 0)   # 한 번 변환해 2단계 파일들을 만들어 둔다
        side = [payreq.FILE, review_checks.SCHEDULE, review_checks.ARCHIVE, insights.FILE, checklist.CONVERT_FILE]
        with open(os.path.join(input_dir, insights.FILE), "w", encoding="utf-8") as f:
            f.write('{"옛": "분개장 날짜"}')   # 지난 변환의 내용이라고 치자
        with open(os.path.join(input_dir, checklist.CONVERT_FILE), "w", encoding="utf-8") as f:
            f.write('{"items": []}')
        if os.path.exists(os.path.join(input_dir, payreq.FILE)):
            os.remove(os.path.join(input_dir, payreq.FILE))
        before = dict((n, _bytes(os.path.join(input_dir, n))) for n in side)
        real = convert.write_files

        def fail_result(input_dir_, payloads, stamp, backup=None):
            if [n for n, _ in payloads] == ["변환결과.txt"]:
                raise convert.WriteFailed("변환결과.txt", PermissionError(13, "sharing violation"))
            return real(input_dir_, payloads, stamp, backup)
        with unittest.mock.patch.object(convert, "write_files", fail_result):
            res = _run(input_dir, collect, wehago_dir)
        self.assertEqual(res.code, 7, res.lines)
        for n in side:
            self.assertEqual(_bytes(os.path.join(input_dir, n)), before[n], n)
        self.assertTrue([ln for ln in res.lines if ln.startswith("함께 바뀐 파일도 변환 전으로 되돌림")], res.lines)
