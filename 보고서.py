"""대표 주간·월간 보고서 만들기.

사용법 (명령 창):
    python 보고서.py 주간                      ← 오늘 기준 주간 보고 (대표용·경영관리용)
    python 보고서.py 월간 --기준일 2026-10-31   ← 기준일 지정
    python 보고서.py 주간 --입력 입력 --출력 출력 --pdf 안함

입력 폴더의 CSV(엑셀에서 'CSV UTF-8' 또는 'CSV'로 저장)를 읽어
출력 폴더에 HTML(과 PDF)을 만든다. 대표용과 경영관리용은 같은 숫자를 쓴다.

종료 코드: 0 완료 · 2 입력 문제(날짜, 폴더) · 7 출력 폴더에 파일을 쓰지 못함
"""
import argparse
import datetime as dt
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from ceo_report.data import load  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.render import render  # noqa: E402
from ceo_report.util import date as parse_date  # noqa: E402
from ceo_report.util import mask_rrn  # noqa: E402

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def _say(text):
    """표준 출력 한 줄. 주민번호 모양 글자는 가린다 (D-36: 입력 확인·오류 글에 섞여 나올 수 있음)."""
    print(mask_rrn(text))


def _input_help(folder):
    """입력 폴더가 없을 때의 안내 (트레이스백 대신)."""
    return ("입력 폴더가 없습니다: %s\n"
            "  입력양식 폴더의 CSV 양식(빈 양식)을 이 폴더에 복사하고 자료를 넣으세요. 예시 자료: %s\n"
            "  다른 폴더를 쓰려면 --입력 <폴더> 로 지정합니다." % (folder, os.path.join("입력양식", "샘플")))


def _write_help(folder, e):
    """출력 폴더를 만들거나 쓸 수 없을 때의 안내 (트레이스백 대신)."""
    return ("출력 폴더에 파일을 쓰지 못했습니다: %s (%s)\n"
            "  같은 이름의 파일이 있거나 쓰기 권한이 없는 폴더입니다. --출력 <폴더> 로 다른 폴더를 지정하세요."
            % (folder, e.strerror or type(e).__name__))


def find_browser():
    for p in BROWSERS:
        if os.path.exists(p):
            return p
    for name in ("msedge", "chrome", "chromium", "chromium-browser", "google-chrome"):
        p = shutil.which(name)
        if p:
            return p
    if os.path.exists("/opt/pw-browsers/chromium"):
        for root, _, files in os.walk("/opt/pw-browsers"):
            if "chrome" in files:
                return os.path.join(root, "chrome")
    return None


PDF_TIMEOUT = 120


def _is_windows():
    return os.name == "nt"


def to_pdf(browser, html_path, pdf_path):
    # 이전 실행의 PDF가 남아 있으면 새로 만든 것으로 착각하므로 먼저 지운다.
    # Windows에서 PDF 뷰어가 열려 있으면 지울 수 없다.
    if os.path.exists(pdf_path):
        try:
            os.remove(pdf_path)
        except OSError as e:
            return "PDF 실패: 이전 PDF를 지우지 못함 (PDF 파일을 닫고 다시 실행): %s" % e
    # 이미 열려 있는 Edge/Chrome이 있으면 새 창 요청을 그쪽에 넘기고 끝나 PDF가 안 만들어진다.
    # 이번 실행 전용 프로필 폴더를 따로 주어 독립된 브라우저로 실행하고, 끝나면 지운다.
    url = pathlib.Path(html_path).resolve().as_uri()  # 공백·#·%·UNC 경로도 올바른 file 주소로
    profile = tempfile.mkdtemp(prefix="ceo_report_pdf_")
    # 새 프로필은 첫 실행 상태라 실험 설정(field trial) 때문에 PDF 출력이 멈추는 환경이 있다 → 끄고 첫 실행 화면도 건너뛴다.
    cmd = [browser, "--headless", "--disable-gpu", "--user-data-dir=" + profile, "--no-first-run",
           "--disable-field-trial-config", "--no-pdf-header-footer",
           "--print-to-pdf=" + os.path.abspath(pdf_path), url]
    if not _is_windows():
        cmd.insert(3, "--no-sandbox")  # Windows에서는 필요 없고, 리눅스(루트 실행·시험 환경)에서만 쓴다
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=PDF_TIMEOUT)
    except subprocess.TimeoutExpired:
        return "PDF 실패: 브라우저가 %d초 안에 끝나지 않음" % PDF_TIMEOUT
    except Exception as e:  # noqa: BLE001  명령 줄(임시 프로필 경로)은 보이지 않는다
        return "PDF 실패: 브라우저를 실행하지 못함 (%s)" % (getattr(e, "strerror", None) or type(e).__name__)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
        return None
    if os.path.exists(pdf_path):  # 0바이트 파일은 성공이 아니다
        try:
            os.remove(pdf_path)
        except OSError:
            pass
    return "PDF 실패 (브라우저가 파일을 만들지 않음)"


def main(argv=None):
    ap = argparse.ArgumentParser(description="대표 주간·월간 보고서")
    ap.add_argument("유형", choices=["주간", "월간", "weekly", "monthly"])
    ap.add_argument("--기준일", default=None, help="YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--시작일", default=None, help="집계 시작일 (기본: 주간=기준일-6일, 월간=그 달 1일)")
    ap.add_argument("--가용일", default=None, help="이 날짜까지의 가용자금 줄을 더함 YYYY-MM-DD (기준일 뒤)")
    ap.add_argument("--입력", default=os.path.join(HERE, "입력"))
    ap.add_argument("--출력", default=os.path.join(HERE, "출력"))
    ap.add_argument("--pdf", default="만듦", choices=["만듦", "안함"])
    a = ap.parse_args(argv)
    kind = "weekly" if a.유형 in ("주간", "weekly") else "monthly"
    asof = parse_date(a.기준일) if a.기준일 else dt.date.today()
    if asof is None:
        _say("기준일 형식 오류: %s" % a.기준일)
        return 2
    start = None
    if a.시작일:
        start = parse_date(a.시작일)
        if start is None or start > asof:
            _say("시작일 형식 오류 또는 기준일보다 늦음: %s (YYYY-MM-DD, 기준일 %s 이전)" % (a.시작일, asof))
            return 2
    pick = None
    if a.가용일:
        pick = parse_date(a.가용일)
        if pick is None or pick <= asof:
            _say("가용일 형식 오류 또는 기준일보다 빠름: %s (YYYY-MM-DD, 기준일 %s 뒤)" % (a.가용일, asof))
            return 2
    if not os.path.isdir(a.입력):
        _say(_input_help(a.입력))
        return 2
    try:
        os.makedirs(a.출력, exist_ok=True)
    except OSError as e:
        _say(_write_help(a.출력, e))
        return 7
    data = load(a.입력)
    R = compute(data, kind, asof, start, pick)
    if kind == "monthly":
        # 월간 8번 'WEHAGO 기준 대조'용 사실 (D-44). 주간 보고는 이 파일을 읽지 않는다. calc.compute 뒤에 붙인다.
        from ceo_report.convert_xchk import load_xchk
        R["xchk"] = load_xchk(a.입력)
    if kind == "weekly":
        # 지난주 보고가 남긴 지급 예정 기록과 비교 (사용자 2026-11-03). 이번 기록은 보고서를 다 쓴 뒤 남긴다.
        from ceo_report.weekdiff import load_previous
        R["week_prev"] = load_previous(a.출력, asof)
    label = "주간" if kind == "weekly" else "월간"
    browser = find_browser() if a.pdf == "만듦" else None
    made = []
    pdf_failed = False
    for mode, who in (("ceo", "대표보고"), ("mgmt", "경영관리보고")):
        base = os.path.join(a.출력, "%s_%s_%s" % (asof.isoformat(), label, who))
        try:
            with open(base + ".html", "w", encoding="utf-8") as f:
                f.write(render(R, mode))
        except OSError as e:
            _say(_write_help(a.출력, e))
            return 7
        made.append(base + ".html")
        if browser:
            err = to_pdf(browser, base + ".html", base + ".pdf")
            if err:
                _say("%s — %s" % (err, os.path.basename(base + ".pdf")))
                pdf_failed = True
            else:
                made.append(base + ".pdf")
    if kind == "weekly":
        from ceo_report.weekdiff import write_record
        try:
            made.append(write_record(a.출력, R))
        except OSError as e:
            _say("지급 예정 기록을 남기지 못했습니다 (다음 주 변동 비교에 쓰임): %s" % e)
    _say("보고 기준일 %s · 집계 기간 %s ~ %s" % (asof, R["period"][0], R["period"][1]))
    _say("만든 파일:")
    for m in made:
        _say("  " + m)
    if pdf_failed:
        _say("PDF: 만들지 못한 것은 HTML을 열고 인쇄 → 'PDF로 저장'을 쓰세요.")
    if a.pdf == "만듦" and not browser:
        _say("PDF: Edge/Chrome을 찾지 못해 HTML만 만들었습니다. HTML을 열고 인쇄 → 'PDF로 저장'을 쓰세요.")
    if R["s2"]["out_missing"]:
        _say("지급 자료 없음: %s — 계산 잔액·최저 잔액을 계산하지 않았습니다." % ", ".join(R["s2"]["out_missing"]))
    if R["s2"]["in_missing"]:
        _say("계산서 자료 없음: %s — 발행 후 미수·발행금액·입금예정은 '자료 없음'으로 두고, 계산 잔액은 계산서 입금 없이 "
             "계산했습니다 (실제보다 낮을 수 있음)." % ", ".join(R["s2"]["in_missing"]))
    n = len(R["s7"]["issues"])
    if n:
        _say("입력 자료 확인 필요 %d건 — 보고서 7번 '입력 자료 확인 필요' 표에 있습니다." % n)
    bad = [c for c in R["s7"]["checks"] if not c[3]]
    if bad:
        _say("대조 불일치 %d건 — 보고서 7번 '보고 대조' 표를 확인하세요." % len(bad))
    if kind == "monthly" and R["xchk"]["state"] != "ok":
        if R["xchk"]["state"] == "자료 없음":
            _say("위하고 대조 자료 없음 — 대표보고 창에서 '자료 변환'을 먼저 하면 월간 보고 8번에 들어갑니다.")
        else:
            _say("위하고 대조 읽을 수 없음 — %s. 월간 보고 8번에는 ‘읽을 수 없음’으로 적었습니다." % R["xchk"]["reason"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
