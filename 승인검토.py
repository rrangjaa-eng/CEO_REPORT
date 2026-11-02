"""지급 승인 검토 화면 만들기.

사용법 (명령 창):
    python 승인검토.py                                  ← 마지막 인트라넷 스냅숏으로 오늘 기준 화면 만들기
    python 승인검토.py --기준일 2026-11-02 --열기 안함
    python 승인검토.py --수집폴더 수집 --출력 출력

수집 폴더의 가장 최근 인트라넷 스냅숏과 입력 폴더의 CSV를 읽어, 앞으로 8주 잔액을 보는 HTML 한 장을
출력 폴더에 만든다. 네트워크를 쓰지 않는다. 주간·월간 보고서는 바꾸지 않는다.
"""
import argparse
import datetime as dt
import os
import pathlib
import sys
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from ceo_report.approval import build, fmt_man, man_unit, scenario  # noqa: E402
from ceo_report.approval_render import render_approval  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.snapshot import SnapshotError, latest_snapshot, read_snapshot  # noqa: E402
from ceo_report.util import date as parse_date  # noqa: E402


def build_parser():
    ap = argparse.ArgumentParser(description="지급 승인 검토 화면")
    ap.add_argument("--기준일", default=None, help="YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--입력", default=os.path.join(HERE, "입력"))
    ap.add_argument("--출력", default=os.path.join(HERE, "출력"))
    ap.add_argument("--수집폴더", default=os.path.join(HERE, "수집"))
    ap.add_argument("--열기", default="열기", choices=["열기", "안함"])
    return ap


def make_screen(input_dir, out_dir, snap_path, asof, now, collected_now):
    """입력 CSV와 스냅숏 폴더로 화면 파일을 만든다. (HTML 경로, 계산 결과 A)를 돌려준다."""
    d = load(input_dir)
    snap = read_snapshot(snap_path)
    A = build(d, snap, asof, now)
    page = render_approval(A, collected_now)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "승인검토_%s.html" % dt.datetime.now().strftime("%Y%m%d_%H%M"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    return path, A


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.기준일:
        asof = parse_date(a.기준일)
        if asof is None:
            print("기준일 형식 오류: %s (YYYY-MM-DD)" % a.기준일)
            return 2
        now = dt.datetime.combine(asof, dt.time(0, 0))
    else:
        now = dt.datetime.now()
        asof = now.date()
    if not os.path.isdir(a.입력):
        print("입력 폴더가 없습니다: %s" % a.입력)
        return 2
    snap_path = latest_snapshot(a.수집폴더)
    if snap_path is None:
        print("인트라넷 수집 스냅숏이 없습니다: %s" % a.수집폴더)
        return 2
    try:
        path, A = make_screen(a.입력, a.출력, snap_path, asof, now, False)
    except SnapshotError as e:
        print("스냅숏을 읽지 못했습니다: %s" % e)
        return 2
    S = scenario(A, [r["id"] for r in A["data"]["requests"]])
    low = fmt_man(S["low"])
    print("승인 검토 화면: %s" % path)
    print("인트라넷 수집 시각 %s (마지막 스냅숏)" % A["collected_at"].strftime("%Y-%m-%d %H:%M:%S"))
    print("전부 승인 시 최저 잔액 %s%s · %s" % (low, man_unit(low), S["low_day"] or "-"))
    if a.열기 == "열기":
        webbrowser.open(pathlib.Path(path).resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
