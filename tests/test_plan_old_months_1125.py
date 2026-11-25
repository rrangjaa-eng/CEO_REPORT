"""2026-11-25: 지난 달만 예전 자금계획 파일에서 온 경우 받은 날짜·7일 검사는 이번 달 이후 줄 날짜 (사용자 결정 카드)."""
import datetime as dt

from ceo_report import fundplan

D = dt.date


def row(ym, stamp, day=10):
    y, m = int(ym[:4]), int(ym[5:])
    return {"date": D(y, m, day), "io": "입금", "vendor": "가", "vendor_code": "", "amount": 1000, "ym": ym,
            "stamp": stamp, "state": "예정", "file": "f", "cat": "외상대금 회수", "project": "", "origin": ""}


def test_old_past_month_noted_and_not_stale():
    plan = [row("2026-09", D(2026, 11, 19)), row("2026-11", D(2026, 11, 25)), row("2026-12", D(2026, 11, 25))]
    stamp, old = fundplan.split_stamps(plan, D(2026, 11, 28))
    assert stamp == D(2026, 11, 25)
    assert old == [("2026-09", D(2026, 11, 19))]
    _, info = fundplan.apply([], plan, D(2026, 11, 28), 7)
    assert info["used"] and info["stamp"] == D(2026, 11, 25)
    assert fundplan.old_note(info) == " (2026-09은 11-19 자료)" and fundplan.old_note(info, ", ", "") == ", 2026-09은 11-19 자료"


def test_old_future_month_still_blocks():
    plan = [row("2026-11", D(2026, 11, 25)), row("2026-12", D(2026, 11, 10))]
    stamp, old = fundplan.split_stamps(plan, D(2026, 11, 25))
    assert stamp == D(2026, 11, 10) and old == []
    _, info = fundplan.apply([], plan, D(2026, 11, 25), 7)
    assert not info["used"]


def test_all_same_file_no_note():
    plan = [row("2026-10", D(2026, 11, 25)), row("2026-11", D(2026, 11, 25))]
    _, info = fundplan.apply([], plan, D(2026, 11, 25), 7)
    assert info["stamp"] == D(2026, 11, 25) and fundplan.old_note(info) == ""
