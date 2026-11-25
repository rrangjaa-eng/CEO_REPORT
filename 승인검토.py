"""인트라넷 자료 가져오기 (예전 이름: 지급 승인 검토).

'지급 승인 검토' 화면은 뺐다 (사용자 2026-11-04 불필요, 2026-11-18 결정 '화면을 뺌'). 이 파일은 인트라넷에서
지급요청·프로젝트 자료를 새로 읽어 수집 폴더에 저장하는 일만 한다 (대표보고 창 ③ '인트라넷 자료 가져오기').

사용법 (명령 창):
    python 승인검토.py --수집 함                         ← 인트라넷에서 새로 읽어 저장
    python 승인검토.py --구조점검                        ← 목록 첫 쪽만 읽어 화면 구조 점검 (파일을 만들지 않음)

--수집 함은 ID와 비밀번호를 화면에서 물어(비밀번호는 보이지 않게) 인트라넷의 허용된 쪽만 읽는다.
ID·비밀번호는 옵션·환경 변수·파일로 받지 않고 이 스크립트는 저장하지 않는다.
(2차 전수조사 P23: 대표보고 창에서 '계정 기억'을 켜면 창이 로그인에 성공한 계정을 프로그램 폴더의 입력 폴더 파일에 둔다 — 끄거나 '기억 지우기'로 지움.)

종료 코드: 0 완료 · 2 입력 문제(날짜, 폴더, 빈 ID·비밀번호, 입력 취소, 비밀번호를 가릴 수 없는 창)
· 3 로그인 실패·화면 구조 변경 · 4 허용 목록 밖 요청을 막음 · 5 인트라넷 연결 실패
· 6 예상하지 못한 오류·중단 · 7 파일 저장 실패(수집한 뒤)
"""
import argparse
import datetime as dt
import getpass
import http.client
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from ceo_report import intranet  # noqa: E402
from ceo_report.approval import parse_registered, project_code  # noqa: E402
from ceo_report.snapshot import SnapshotError, write_snapshot  # noqa: E402
from ceo_report.util import date as parse_date  # noqa: E402
from ceo_report.util import mask_rrn, num  # noqa: E402


def _say(text):
    """표준 출력 한 줄. 주민번호 모양 글자는 가린다 (D-36: 입력 확인·오류 글에 섞여 나올 수 있음)."""
    print(mask_rrn(text))


def _input_help(folder):
    """입력 폴더가 없을 때의 안내 (트레이스백 대신)."""
    return ("입력 폴더가 없습니다: %s\n"
            "  입력양식 폴더의 CSV 양식(빈 양식)을 이 폴더에 복사하고 자료를 넣으세요. 예시 자료: %s\n"
            "  다른 폴더를 쓰려면 --입력 <폴더> 로 지정합니다." % (folder, os.path.join("입력양식", "샘플")))


def _positive_int(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("1 이상의 정수여야 합니다: %s" % text)
    if value < 1:
        raise argparse.ArgumentTypeError("1 이상의 정수여야 합니다: %s" % text)
    return value


def build_parser():
    ap = argparse.ArgumentParser(description="인트라넷 자료 가져오기")
    ap.add_argument("--기준일", default=None, help="YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--입력", default=os.path.join(HERE, "입력"))
    ap.add_argument("--출력", default=os.path.join(HERE, "출력"))
    ap.add_argument("--수집폴더", default=os.path.join(HERE, "수집"))
    ap.add_argument("--위하고폴더", default=None,
                    help="WEHAGO 엑셀(분개장·매입매출장·전자세금계산서(매입)) 폴더 (기본: <수집폴더>/위하고)")
    ap.add_argument("--열기", default="안함", choices=["열기", "안함"], help=argparse.SUPPRESS)   # 예전 옵션 (화면을 빼서 쓰지 않음)
    ap.add_argument("--수집", default="안함", choices=["함", "안함"],
                    help="함: 인트라넷에서 새로 읽기 (ID·비밀번호를 화면에서 물음). 기본: 안함")
    ap.add_argument("--화면", default="안함", choices=["만듦", "안함"], help=argparse.SUPPRESS)   # 예전 옵션 (화면을 빼서 쓰지 않음)
    ap.add_argument("--구조점검", action="store_true",
                    help="로그인 후 각 목록의 첫 쪽만 읽어 화면 구조를 점검 (파일을 만들지 않음)")
    ap.add_argument("--최대페이지", type=_positive_int, default=300, help="목록마다 읽을 최대 쪽 수 (기본 300)")
    return ap


def make_collector_opener(delay=0.3):
    """인트라넷으로 나가는 유일한 길: 허용 목록 검사가 들어 있는 읽기 전용 opener. 시험에서 바꿔 끼운다."""
    return intranet.make_opener(delay=delay)


NO_FILE = "파일을 만들지 않았습니다"
NO_HIDE_MESSAGE = "비밀번호를 가리고 입력할 수 없는 창입니다 — 대표보고 창에서 실행하거나 명령 프롬프트에서 실행하세요"


CREDENTIALS = None   # 한 화면 프로그램이 넣는다: () -> (ID, 비밀번호). 창의 가린 입력칸에서 받음 (사용자 2026-11-03)


def ask_credentials():
    """(ID, 비밀번호, 종료코드). 종료코드가 None이 아니면 멈춘다. 비밀번호는 화면에 나타나지 않는다."""
    if CREDENTIALS is not None:
        user_id, password = CREDENTIALS()
        return (user_id or "").strip(), password or "", None
    try:
        user_id = input("인트라넷 ID: ").strip()
        with warnings.catch_warnings():
            # 입력이 보이는 방식으로 물러나려 하면 한 글자도 읽기 전에 멈춘다
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("인트라넷 비밀번호 (입력해도 화면에 보이지 않음): ")
    except getpass.GetPassWarning:
        _say(NO_HIDE_MESSAGE)
        return None, None, 2
    except (KeyboardInterrupt, EOFError):
        _say("입력을 취소했습니다 (%s)" % NO_FILE)
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
    _say(_scrub(text, secrets))
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
        return None, _fail(6, "중단했습니다 (%s)" % NO_FILE, secrets)
    except Exception as e:
        return None, _fail(6, "수집 중 예상하지 못한 오류: %s: %s" % (type(e).__name__, e), secrets)


def _progress(label, page, total):
    _say("%s 목록 %d쪽 읽음 (누계 %d건)" % (label, page, total))


def _unexpected(e):
    """저장하다 난 예상하지 못한 오류: 한 줄 (주민번호 가림), 종료 코드 6."""
    _say("인트라넷 자료를 저장하던 중 예상하지 못한 오류 (%s): %s — 다시 실행하세요"
         % (type(e).__name__, str(e)[:200]))
    return 6


def main(argv=None):
    a = build_parser().parse_args(argv)
    if a.구조점검:
        return run_structure(a)
    if a.기준일:
        asof = parse_date(a.기준일)
        if asof is None:
            _say("기준일 형식 오류: %s (YYYY-MM-DD)" % a.기준일)
            return 2
        now = dt.datetime.combine(asof, dt.time(0, 0))
    else:
        now = dt.datetime.now()
        asof = now.date()
    if not os.path.isdir(a.입력):
        _say(_input_help(a.입력))
        return 2
    if a.수집 == "함":
        return run_collect(a, asof, now)
    _say(NO_SCREEN)
    return 0


NO_SCREEN = ("'지급 승인 검토' 화면은 뺐습니다 (2026-11-18). 인트라넷 자료를 새로 가져오려면 대표보고 창 ③ '인트라넷 자료 가져오기'"
             "를 누르거나 --수집 함 으로 실행하세요. " + "파일을 만들지 않았습니다")


def run_structure(a):
    """구조 점검: 로그인 → 목록마다 첫 쪽만 → 머리글·줄 수·쪽 링크·해석 불가 건수만 출력. 파일은 만들지 않는다."""
    user_id, password, rc = ask_credentials()
    if rc is not None:
        return rc
    if not user_id or not password:
        _say("ID와 비밀번호를 모두 입력해야 합니다")
        return 2
    secrets = [user_id, password]
    try:
        rep, rc = _guarded(
            lambda: intranet.structure_report(make_collector_opener(), user_id, password), secrets)
    finally:
        user_id = password = None
        del secrets[:]
    if rc is not None:
        return rc
    return print_structure(rep, a.최대페이지)


def print_structure(rep, max_pages):
    """점검 결과를 출력한다. 머리글 이름과 건수만 나오고 줄의 값은 나오지 않는다."""
    login = rep["login"]
    # 이동 위치에는 ID가 들어 있을 수 있어 있음/없음만 보인다 (IN-09)
    _say("로그인: 성공 (응답 %s, 이동 위치 %s)" % (login["status"], "있음" if login["redirect_path"] else "없음"))
    for key, label in (("payment", "지급요청"), ("project", "프로젝트")):
        r = rep[key]
        if not r["table_found"]:
            _say("%s 목록 머리글: 다름 (머리글 표를 찾지 못함)" % label)
        elif r["header_ok"]:
            _say("%s 목록 머리글: 일치" % label)
        else:
            _say("%s 목록 머리글: 다름" % label)
            _say("  없음: %s" % (", ".join(r["missing"]) or "(없음)"))
            _say("  새로 생김: %s" % (", ".join(r["extra"]) or "(없음)"))
            if r["first_difference"]:
                _say("  첫 차이: %s" % r["first_difference"])
        line = "%s 1쪽: %d건" % (label, r["rows"])
        if key == "project":
            line += " · Total 줄 %s · 프로젝트 보기 링크 %d개" % ("있음" if r["total_row"] else "없음", r["pro_num_links"])
        if r["bad_rows"]:
            line += " · 칸 수가 머리글과 다른 줄 %d건" % r["bad_rows"]
        _say(line)
        links = r["page_links"]
        if links["query"] or links["path_number"]:
            forms = ["조회 이름 %s %d개" % (name, count) for name, count in sorted(links["query"].items())]
            if links["path_number"]:
                forms.append("경로 숫자 %d개" % links["path_number"])
            _say("  쪽 링크 형태: %s" % " · ".join(forms))
        else:
            _say("  쪽 링크 형태: 찾지 못함")
        if links["max_number"] is not None:
            _say("%s 쪽 링크 최대 번호 %d (수집 상한 --최대페이지 %d)" % (label, links["max_number"], max_pages))
        if r["unfollowed_query_names"]:
            _say("  따라가지 않을 같은 목록 링크의 조회 이름: %s" % ", ".join(r["unfollowed_query_names"]))
        if r["paging_stop"]:
            _say("  이대로면 수집이 멈춥니다: %s" % r["paging_stop"])
    pay = rep["payment"]
    if pay["header_ok"]:
        rows = pay["rows_data"]
        _say("금액 미확인 %d건" % sum(1 for r in rows if num(r.get("금액")) is None))
        _say("등록일 해석 불가 %d건" % sum(1 for r in rows if parse_registered(r.get("등록일")) is None))
        _say("프로젝트 코드 없음 %d건" % sum(1 for r in rows if project_code(r.get("행사명")) is None))
    else:
        _say("값 검사(금액·등록일·프로젝트 코드): 지급요청 머리글이 달라 건너뜀")
    _say("구조 점검 결과: %s" % ("예상과 일치" if rep["ok"] else "예상과 다름"))
    _say(NO_FILE)
    return 0 if rep["ok"] else 3


def write_structure_log(out_dir, when, diag, rc):
    """인트라넷 화면 구조 기록 (출력\\인트라넷_구조점검.txt, 매번 덮어씀). 값은 없고 줄 수·칸 수·링크 모양만 있다."""
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "인트라넷_구조점검.txt"), "w", encoding="utf-8") as f:
            f.write("인트라넷 구조 점검 %s · 결과 %s\n" % (when.strftime("%Y-%m-%d %H:%M:%S"),
                                                 "완료" if rc is None else "멈춤 (코드 %s)" % rc))
            f.write("\n".join(diag) + "\n")
    except OSError:
        pass


TEAM_OK = ("수락완료", "승인")   # 인트라넷 팀장승인 칸: 실제 값은 수락완료·수락요청중 (2026-11-04 수집)


def gathered_summary(result):
    """가져온 자료 요약 (값 없이 건수·합계만): 팀장 승인 요청, 사전견적이 있는 프로젝트 (사용자 2026-11-04)."""
    from ceo_report.util import num
    team_ok = sum(1 for r in result.payments if (r.get("팀장승인") or "").strip() in TEAM_OK)
    est = [num(p.get("사전견적")) for p in result.projects]
    est = [e for e in est if e]
    _say("지급요청 %d건 중 팀장 승인 %d건 (비교용 — 가용자금에는 넣지 않음)" % (len(result.payments), team_ok))
    _say("프로젝트 %d건 중 사전견적 있음 %d건 · 사전견적 합계 %s원 (예산 = 사전견적 × 원가율)"
         % (len(result.projects), len(est), "{:,}".format(sum(est))))


def run_collect(a, asof, now):
    """ID·비밀번호를 묻고 → 인트라넷 전 쪽 수집 → 스냅숏 저장."""
    user_id, password, rc = ask_credentials()
    if rc is not None:
        return rc
    if not user_id or not password:
        _say("ID와 비밀번호를 모두 입력해야 합니다")
        return 2
    secrets = [user_id, password]
    collected_at = dt.datetime.now().replace(microsecond=0)  # 수집을 시작하는 순간 (P-13)
    started = time.monotonic()
    diag = []
    try:
        result, rc = _guarded(
            lambda: intranet.collect(make_collector_opener(), user_id, password, a.최대페이지, _progress, diag),
            secrets)
    finally:
        user_id = password = None
        del secrets[:]
    write_structure_log(a.출력, collected_at, diag, rc)
    if rc is not None:
        return rc
    for x in diag:   # 2차 P1-15: 수집은 끝났지만 놓친 쪽이 있을 수 있다는 알림은 화면에도
        if str(x).startswith("[확인]"):
            _say(x)
    if result.project_skipped:
        _say("[확인] 프로젝트 목록에서 칸 수가 다른 줄 %d건은 읽지 않고 건너뜀 — 그 프로젝트의 계산서는 미연결로 남습니다 "
             "(모양: 출력\\인트라넷_구조점검.txt)" % result.project_skipped)
    _say("수집 완료: 지급요청 %d쪽 %d건 · 프로젝트 %d쪽 %d건 · %.1f초" % (
        result.payment_pages, len(result.payments), result.project_pages, len(result.projects),
        time.monotonic() - started))
    where = a.수집폴더
    try:
        put_requests = None
        if result.requests is not None:   # 지급 요청서 세부사항 첫 줄 (사용자 2026-11-05)
            from ceo_report import payreq
            put_requests = lambda folder: payreq.write(folder, result.requests)   # noqa: E731 — 완성 표시 전에 함께 씀 (C20·P1-16)
        write_snapshot(a.수집폴더, collected_at, result.payments, result.projects,
                                   pages={"지급요청": result.payment_pages, "프로젝트": result.project_pages},
                                   extra=put_requests, skipped=result.project_skipped)
        if result.requests is not None:
            _say("지급 요청서(관리팀 승인·사장님 승인 전) %d건 읽음 · 세부사항 있음 %d건"
                 % (len(result.requests), sum(1 for r in result.requests if r["note"])))
        else:
            _say("[확인] 지급 요청서 화면 구조가 예상과 달라 세부사항은 가져오지 못함 (목록 자료는 정상 저장)")
        gathered_summary(result)
        _say("다음: ① '자료 변환'을 누르면 이 자료로 프로젝트 예산·비교가 새로 만들어집니다")
        return 0
    except (OSError, SnapshotError) as e:
        _say("저장 실패: 인트라넷 자료는 읽었지만 파일을 쓰지 못했습니다 (%s): %s" % (where, type(e).__name__))
        return 7
    except Exception as e:   # 트레이스백을 보이지 않는다 (02-REVIEW WR-02)
        return _unexpected(e)


if __name__ == "__main__":
    sys.exit(main())
