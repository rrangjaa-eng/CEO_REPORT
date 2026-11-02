"""지급 승인 검토 화면 만들기.

사용법 (명령 창):
    python 승인검토.py                                  ← 마지막 인트라넷 스냅숏으로 오늘 기준 화면 만들기
    python 승인검토.py --기준일 2026-11-02 --열기 안함
    python 승인검토.py --수집폴더 수집 --출력 출력
    python 승인검토.py --수집 함                         ← 인트라넷에서 새로 읽어 화면 만들기 (실행_승인검토.bat)

기본(--수집 안함)은 수집 폴더의 가장 최근 인트라넷 스냅숏과 입력 폴더의 CSV를 읽어, 앞으로 8주 잔액을 보는
HTML 한 장을 출력 폴더에 만든다. 네트워크를 쓰지 않는다. 주간·월간 보고서는 바꾸지 않는다.
--수집 함은 ID와 비밀번호를 화면에서 물어(비밀번호는 보이지 않게) 인트라넷의 허용된 쪽만 읽는다.
ID·비밀번호는 옵션·환경 변수·파일로 받지 않고 어디에도 저장하지 않는다.

종료 코드: 0 완료 · 2 입력 문제(날짜, 폴더, 빈 ID·비밀번호, 입력 취소, 비밀번호를 가릴 수 없는 창)
· 3 로그인 실패·화면 구조 변경 · 4 허용 목록 밖 요청을 막음 · 5 인트라넷 연결 실패
· 6 예상하지 못한 오류·중단 · 7 읽은 뒤 파일 저장 실패
"""
import argparse
import datetime as dt
import getpass
import http.client
import os
import pathlib
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import warnings
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from ceo_report import intranet  # noqa: E402
from ceo_report.approval import build, fmt_man, man_unit, scenario  # noqa: E402
from ceo_report.approval_render import render_approval  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.snapshot import SnapshotError, latest_snapshot, read_snapshot, write_snapshot  # noqa: E402
from ceo_report.util import date as parse_date  # noqa: E402


def _positive_int(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("1 이상의 정수여야 합니다: %s" % text)
    if value < 1:
        raise argparse.ArgumentTypeError("1 이상의 정수여야 합니다: %s" % text)
    return value


def build_parser():
    ap = argparse.ArgumentParser(description="지급 승인 검토 화면")
    ap.add_argument("--기준일", default=None, help="YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--입력", default=os.path.join(HERE, "입력"))
    ap.add_argument("--출력", default=os.path.join(HERE, "출력"))
    ap.add_argument("--수집폴더", default=os.path.join(HERE, "수집"))
    ap.add_argument("--열기", default="열기", choices=["열기", "안함"])
    ap.add_argument("--수집", default="안함", choices=["함", "안함"],
                    help="함: 인트라넷에서 새로 읽기 (ID·비밀번호를 화면에서 물음). 기본: 안함")
    ap.add_argument("--최대페이지", type=_positive_int, default=300, help="목록마다 읽을 최대 쪽 수 (기본 300)")
    return ap


def make_collector_opener(delay=0.3):
    """인트라넷으로 나가는 유일한 길: 허용 목록 검사가 들어 있는 읽기 전용 opener. 시험에서 바꿔 끼운다."""
    return intranet.make_opener(delay=delay)


NO_HIDE_MESSAGE = "비밀번호를 가리고 입력할 수 없는 창입니다 — 실행_승인검토.bat을 더블클릭하거나 명령 프롬프트에서 실행하세요"


def ask_credentials():
    """(ID, 비밀번호, 종료코드). 종료코드가 None이 아니면 멈춘다. 비밀번호는 화면에 나타나지 않는다."""
    try:
        user_id = input("인트라넷 ID: ").strip()
        with warnings.catch_warnings():
            # 입력이 보이는 방식으로 물러나려 하면 한 글자도 읽기 전에 멈춘다
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("인트라넷 비밀번호 (입력해도 화면에 보이지 않음): ")
    except getpass.GetPassWarning:
        print(NO_HIDE_MESSAGE)
        return None, None, 2
    except (KeyboardInterrupt, EOFError):
        print("입력을 취소했습니다 (파일을 만들지 않았습니다)")
        return None, None, 2
    return user_id, password, None


def _scrub(text, secrets):
    """글에 들어 있는 ID·비밀번호(원문·주소 인코딩)를 *** 로 바꾼다."""
    text = str(text)
    forms = set()
    for secret in secrets:
        if secret:
            forms.update([secret, urllib.parse.quote(secret), urllib.parse.quote_plus(secret)])
    for form in sorted(forms, key=len, reverse=True):
        text = text.replace(form, "***")
    return text


def _fail(code, text, secrets):
    print(_scrub(text, secrets))
    return code


def _guarded(func, secrets):
    """func()를 실행해 (결과, None)을 돌려준다. 예외는 한 줄 글로 바꿔 (None, 종료코드).

    트레이스백은 출력하지 않는다: 지역 변수에 있는 ID·비밀번호가 새어 나갈 길을 막는다.
    """
    try:
        return func(), None
    except intranet.BlockedRequest as e:
        return None, _fail(4, "허용 목록 밖 요청을 막고 멈췄습니다: %s" % e, secrets)
    except intranet.LoginFailed:
        return None, _fail(3, "로그인 실패: ID 또는 비밀번호를 확인하세요", secrets)
    except (intranet.StructureMismatch, SnapshotError) as e:
        return None, _fail(3, "인트라넷 화면 구조가 예상과 다릅니다: %s" % e, secrets)
    except (urllib.error.URLError, ssl.SSLError, socket.timeout, OSError, http.client.HTTPException) as e:
        reason = e.reason if isinstance(e, urllib.error.URLError) and e.reason else "%s: %s" % (type(e).__name__, e)
        return None, _fail(5, "인트라넷 연결 실패: %s" % reason, secrets)
    except KeyboardInterrupt:
        return None, _fail(6, "중단했습니다 (파일을 만들지 않았습니다)", secrets)
    except Exception as e:
        return None, _fail(6, "수집 중 예상하지 못한 오류: %s: %s" % (type(e).__name__, e), secrets)


def _progress(label, page, total):
    print("%s 목록 %d쪽 읽음 (누계 %d건)" % (label, page, total))


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
    if a.수집 == "함":
        return run_collect(a, asof, now)
    snap_path = latest_snapshot(a.수집폴더)
    if snap_path is None:
        print("인트라넷 수집 스냅숏이 없습니다: %s" % a.수집폴더)
        return 2
    try:
        path, A = make_screen(a.입력, a.출력, snap_path, asof, now, False)
    except SnapshotError as e:
        print("스냅숏을 읽지 못했습니다: %s" % e)
        return 2
    report(path, A, "(마지막 스냅숏)")
    if a.열기 == "열기":
        webbrowser.open(pathlib.Path(path).resolve().as_uri())
    return 0


def report(path, A, how):
    S = scenario(A, [r["id"] for r in A["data"]["requests"]])
    low = fmt_man(S["low"])
    print("승인 검토 화면: %s" % path)
    print("인트라넷 수집 시각 %s %s" % (A["collected_at"].strftime("%Y-%m-%d %H:%M:%S"), how))
    print("전부 승인 시 최저 잔액 %s%s · %s" % (low, man_unit(low), S["low_day"] or "-"))


def run_collect(a, asof, now):
    """ID·비밀번호를 묻고 → 인트라넷 전 쪽 수집 → 스냅숏 저장 → 화면 만들기 → 브라우저."""
    user_id, password, rc = ask_credentials()
    if rc is not None:
        return rc
    if not user_id or not password:
        print("ID와 비밀번호를 모두 입력해야 합니다")
        return 2
    secrets = [user_id, password]
    collected_at = dt.datetime.now().replace(microsecond=0)  # 수집을 시작하는 순간 (P-13)
    started = time.monotonic()
    try:
        result, rc = _guarded(
            lambda: intranet.collect(make_collector_opener(), user_id, password, a.최대페이지, _progress),
            secrets)
    finally:
        user_id = password = None
        del secrets[:]
    if rc is not None:
        return rc
    print("수집 완료: 지급요청 %d쪽 %d건 · 프로젝트 %d쪽 %d건 · %.1f초" % (
        result.payment_pages, len(result.payments), result.project_pages, len(result.projects),
        time.monotonic() - started))
    where = a.수집폴더
    try:
        snap_path = write_snapshot(a.수집폴더, collected_at, result.payments, result.projects,
                                   pages={"지급요청": result.payment_pages, "프로젝트": result.project_pages})
        where = a.출력
        path, A = make_screen(a.입력, a.출력, snap_path, asof, now, True)
    except (OSError, SnapshotError) as e:
        print("저장 실패: 인트라넷 자료는 읽었지만 파일을 쓰지 못했습니다 (%s): %s" % (where, type(e).__name__))
        return 7
    report(path, A, "(이번 실행에서 수집)")
    if a.열기 == "열기":
        webbrowser.open(pathlib.Path(path).resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
