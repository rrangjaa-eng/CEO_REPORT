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
import re
import shutil
import subprocess
import sys
import tempfile
import time

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


PDF_WAIT = 20  # 초. Windows Edge 는 명령이 먼저 끝나고 PDF 는 조금 뒤에 써지는 일이 있다 (사용자 PC 2026-11-04: 1~3초 뒤 생김)


def _pdf_ready(pdf_path):
    """끝까지 써진 PDF 인가 (%EOF 로 끝남)."""
    try:
        if os.path.getsize(pdf_path) <= 0:
            return False
        with open(pdf_path, "rb") as f:
            f.seek(max(0, os.path.getsize(pdf_path) - 1024))
            return b"%EOF" in f.read()
    except OSError:
        return False


def _wait_pdf(pdf_path, limit=None):
    """브라우저가 끝난 뒤에도 PDF 가 다 써질 때까지 잠깐 기다린다."""
    end = time.time() + (PDF_WAIT if limit is None else limit)
    while True:
        if _pdf_ready(pdf_path):
            return True
        if time.time() >= end:
            return False
        time.sleep(0.3)


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
    else:
        _wait_pdf(pdf_path)
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    if _pdf_ready(pdf_path):
        return None
    if os.path.exists(pdf_path):  # 0바이트 파일은 성공이 아니다
        try:
            os.remove(pdf_path)
        except OSError:
            pass
    return "PDF 실패 (브라우저가 파일을 만들지 않음)"


CEO_PAGES = {"주간": 2, "월간": 3}   # 대표 보고 쪽 수 상한 (사용자 2026-11-03)
FIT_ZOOMS = (0.97, 0.94, 0.91, 0.88, 0.85)


def pdf_pages(pdf_path):
    """PDF 쪽 수 (Edge·Chrome 이 만든 PDF 의 쪽 객체 수). 읽지 못하면 None."""
    try:
        with open(pdf_path, "rb") as f:
            return len(re.findall(rb"/Type\s*/Page[^s]", f.read()))
    except OSError:
        return None


def ceo_pages(html_path):
    """대표 보고 파일 이름으로 쪽 수 상한. 대표 보고가 아니면 None."""
    name = os.path.basename(html_path)
    if "대표보고" not in name:
        return None
    for k, n in CEO_PAGES.items():
        if "_%s_" % k in name:
            return n
    return None


def fit_pdf(browser, html_path, pdf_path, max_pages=None):
    """PDF 를 만들고, 쪽 수가 상한을 넘으면 인쇄 글자를 조금씩 줄여 다시 만든다 (사용자 2026-11-05:
    수정해서 줄이 늘면 맨 끝 안내 한 줄만 다음 쪽으로 넘어감). HTML 은 그대로 두고 PDF 만 바꾼다.
    끝까지 안 맞으면 처음 PDF 를 그대로 둔다."""
    err = to_pdf(browser, html_path, pdf_path)
    if err or not max_pages:
        return err
    n = pdf_pages(pdf_path)
    if n is None or n <= max_pages:
        return None
    try:
        with open(html_path, encoding="utf-8") as f:
            page = f.read()
    except OSError:
        return None
    base = os.path.splitext(html_path)[0] + "_쪽맞춤"
    tmp_html, tmp_pdf = base + ".html", base + ".pdf"
    try:
        for z in FIT_ZOOMS:
            style = "<style>@media print{body{zoom:%s}}</style>" % z
            i = page.lower().rfind("</head>")
            with open(tmp_html, "w", encoding="utf-8") as f:
                f.write(page[:i] + style + page[i:] if i >= 0 else style + page)
            if to_pdf(browser, tmp_html, tmp_pdf):
                break
            m = pdf_pages(tmp_pdf)
            if m is not None and m <= max_pages:
                try:
                    os.replace(tmp_pdf, pdf_path)
                except OSError:
                    pass
                break
    finally:
        for t in (tmp_html, tmp_pdf):
            try:
                os.remove(t)
            except OSError:
                pass
    return None


def _evidence(a, kind, asof):
    """근거자료만 따로 (사용자 2026-11-03): 보고서를 다시 만들지 않고, 대표에게 낸 그 경영관리 보고에서 뽑는다 (같은 숫자)."""
    from ceo_report import evidence
    label = "주간" if kind == "weekly" else "월간"
    try:
        nums = evidence.parse_nums(a.근거)
    except ValueError as e:
        _say(str(e))
        return 2
    src = os.path.join(a.출력, "%s_%s_경영관리보고.html" % (asof.isoformat(), label))
    if not os.path.isfile(src):
        _say("%s 경영관리 보고가 없습니다: %s — 먼저 그 날짜의 %s 보고를 만드세요." % (asof, src, label))
        return 2
    with open(src, encoding="utf-8") as f:
        mg = f.read()
    try:
        doc = evidence.build(mg, nums, when="%s %s 보고" % (asof.isoformat(), label))
    except ValueError as e:
        _say(str(e))
        return 2
    base = os.path.join(a.출력, "%s_%s_근거자료_%s" % (asof.isoformat(), label, "_".join(nums)))
    try:
        with open(base + ".html", "w", encoding="utf-8") as f:
            f.write(doc)
    except OSError as e:
        _say(_write_help(a.출력, e))
        return 7
    made = [base + ".html"]
    browser = find_browser() if a.pdf == "만듦" else None
    if browser:
        err = to_pdf(browser, base + ".html", base + ".pdf")
        if err:
            _say("%s — %s" % (err, os.path.basename(base + ".pdf")))
        else:
            made.append(base + ".pdf")
    _say("근거 %s · %s %s 경영관리 보고에서 뽑음" % (", ".join(nums), asof, label))
    _say("만든 파일:")
    for m in made:
        _say("  " + m)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="대표 주간·월간 보고서")
    ap.add_argument("유형", choices=["주간", "월간", "weekly", "monthly"])
    ap.add_argument("--기준일", default=None, help="YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--시작일", default=None, help="집계 시작일 (기본: 주간=기준일-6일, 월간=그 달 1일)")
    ap.add_argument("--가용일", default=None, help="이 날짜까지의 가용자금 줄을 더함 YYYY-MM-DD (기준일 뒤)")
    ap.add_argument("--출금일", default=None, help="주간 출금 목록을 만들 날짜 YYYY-MM-DD (기준일 뒤, 기본: 기준일 뒤 첫 금요일)")
    ap.add_argument("--출금목록", default="건별", choices=["건별", "거래처별"],
                    help="주간 출금 목록: 건별(기본) 또는 같은 날 같은 거래처를 한 줄로 합침")
    ap.add_argument("--합칠거래처", default="", help="거래처별일 때 합칠 거래처만 (쉼표로 구분, 비우면 전부)")
    ap.add_argument("--입력", default=os.path.join(HERE, "입력"))
    ap.add_argument("--출력", default=os.path.join(HERE, "출력"))
    ap.add_argument("--pdf", default="만듦", choices=["만듦", "안함"])
    ap.add_argument("--팀장용", default="만듦", choices=["만듦", "안함"], help="월간: 팀마다 팀장용 실적 문서 (출력/팀장용/)")
    ap.add_argument("--근거", default=None, help="대표가 요청한 근거 번호 (예: 1-1,3-2). 이미 만든 경영관리 보고에서 그 근거만 따로 만듦")
    a = ap.parse_args(argv)
    kind = "weekly" if a.유형 in ("주간", "weekly") else "monthly"
    asof = parse_date(a.기준일) if a.기준일 else dt.date.today()
    if asof is None:
        _say("기준일 형식 오류: %s" % a.기준일)
        return 2
    if a.근거 is not None:
        return _evidence(a, kind, asof)
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
    payday = None
    if a.출금일:   # 사용자 2026-11-04: 금요일 고정이 아니라 넣은 날짜의 출금 목록
        payday = parse_date(a.출금일)
        if payday is None or payday <= asof:
            _say("출금일 형식 오류 또는 기준일보다 빠름: %s (YYYY-MM-DD, 기준일 %s 뒤). "
                 "출금하는 날 아침에 만들면 기준일을 그 전날로 넣으세요." % (a.출금일, asof))
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
    R = compute(data, kind, asof, start, pick, payday)
    R["out_group"] = a.출금목록   # 사용자 2026-11-05: 출금 목록 건별 / 거래처별 합침을 창에서 고름
    R["out_merge_only"] = [x.strip() for x in a.합칠거래처.split(",") if x.strip()]   # 특정 거래처만 합침 (사용자 2026-11-05)
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
        page = render(R, mode)   # 먼저 다 만든 뒤 연다: 만들다 실패해도 이전 보고 파일이 빈 파일로 덮이지 않게
        try:
            with open(base + ".html", "w", encoding="utf-8") as f:
                f.write(page)
        except OSError as e:
            _say(_write_help(a.출력, e))
            return 7
        made.append(base + ".html")
        if browser:
            err = fit_pdf(browser, base + ".html", base + ".pdf", ceo_pages(base + ".html"))
            if err:
                _say("%s — %s" % (err, os.path.basename(base + ".pdf")))
                pdf_failed = True
            else:
                made.append(base + ".pdf")
    if kind == "monthly" and a.팀장용 == "만듦":
        # 팀장용 월간 실적 (사용자 2026-11-09 목업 승인): 팀마다 출력/팀장용/ 에 HTML·PDF. 급여 금액은 넣지 않는다
        from ceo_report.teamreport import write_all as write_team_reports
        try:
            team_pages = write_team_reports(data, R, a.출력)
        except OSError as e:
            _say(_write_help(os.path.join(a.출력, "팀장용"), e))
            team_pages = []
        for page_path in team_pages:
            made.append(page_path)
            if browser:
                pdf_path = page_path[:-5] + ".pdf"
                err = to_pdf(browser, page_path, pdf_path)
                if err:
                    _say("%s — %s" % (err, os.path.basename(pdf_path)))
                    pdf_failed = True
                else:
                    made.append(pdf_path)
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
        _say("입력 자료 확인 필요 %d건 — 경영관리보고 맨 끝 '7. 지난 보고 이후 변동과 자료 반영 범위' 안의 '입력 자료 확인 필요' 표에 있습니다 (대표보고에는 없음)." % n)
    bad = [c for c in R["s7"]["checks"] if not c[3]]
    if bad:
        _say("대조 불일치 %d건 — 경영관리보고 맨 끝 '7. …' 안의 '보고 대조' 표를 확인하세요 (대표보고에는 없음)." % len(bad))
    if kind == "monthly" and R["xchk"]["state"] != "ok":
        if R["xchk"]["state"] == "자료 없음":
            _say("위하고 대조 자료 없음 — 대표보고 창에서 '자료 변환'을 먼저 하면 월간 경영관리보고 '8. WEHAGO 기준 대조'에 들어갑니다.")
        else:
            _say("위하고 대조 읽을 수 없음 — %s. 월간 경영관리보고 '8. WEHAGO 기준 대조'에는 ‘읽을 수 없음’으로 적었습니다." % R["xchk"]["reason"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
