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
from ceo_report import pdfname  # noqa: E402

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
           "--generate-pdf-document-outline",   # PDF 왼쪽 책갈피 = 장 제목 (사용자 2026-11-11 영역별 보기). 모르는 브라우저는 무시
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
        pdf = pdfname.stamped(base)   # 만든 시각을 이름에 (사용자 2026-11-12)
        err = to_pdf(browser, base + ".html", pdf)
        if err:
            _say("%s — %s" % (err, os.path.basename(pdf)))
        else:
            made.append(pdf)
            for gone in pdfname.prune(base):
                _say("같은 보고 PDF가 %d개 넘게 쌓여 예전 것을 지움: %s" % (pdfname.KEEP_FROM - 1, os.path.basename(gone)))
    _say("근거 %s · %s %s 경영관리 보고에서 뽑음" % (", ".join(nums), asof, label))
    _say("만든 파일:")
    for m in made:
        _say("  " + m)
    return 0


def _annual(a):
    """연간 보고 (사용자 2026-11-10 목업 승인): 대표용·경영관리용 HTML·PDF. 숫자는 변환이 만든 CSV에서 (월간과 같은 기준)."""
    from ceo_report import annual
    today = parse_date(a.기준일) if a.기준일 else dt.date.today()
    if today is None:
        _say("기준일 형식 오류: %s" % a.기준일)
        return 2
    year = today.year - 1 if today.month <= 3 else today.year
    if a.연도:
        if not (a.연도.strip().isdigit() and len(a.연도.strip()) == 4):
            _say("연도 형식 오류: %s (예: 2026)" % a.연도)
            return 2
        year = int(a.연도)
    if not os.path.isdir(a.입력):
        _say(_input_help(a.입력))
        return 2
    try:
        os.makedirs(a.출력, exist_ok=True)
    except OSError as e:
        _say(_write_help(a.출력, e))
        return 7
    D = load(a.입력)
    from ceo_report import gate
    stop = gate.check_dir(a.입력, today)   # 연간 대표 보고도 자금계획서·분개장 확인 (2026-11-14 코덱스 검토)
    if stop:
        _say("연간 대표 보고를 만들지 않습니다 — 자금계획서·분개장 미반영: " + " / ".join(stop))
    A = annual.compute(a.입력, year, D.settings, D, today)   # 연중이면 기준일까지 (끝난 달·작년 같은 기간)
    if A["Y"] is None:
        _say("%d년 손익 자료가 없습니다 — 위하고 분개장을 받아 '자료 변환'을 먼저 하세요." % year)
        return 2
    browser = find_browser() if a.pdf == "만듦" else None
    made, pdf_failed = [], False
    for mode, who in (("ceo", "대표보고"), ("mgmt", "경영관리보고")):
        base = os.path.join(a.출력, "%d_연간_%s" % (year, who))
        if mode == "ceo" and stop:
            try:
                with open(base + ".html", "w", encoding="utf-8") as f:
                    f.write(gate.stop_page("%d년 연간 대표보고" % year, stop))
            except OSError as e:
                _say(_write_help(a.출력, e))
                return 7
            continue
        page = annual.render(annual.blank_cash(A) if stop else A, mode)
        if stop:   # 항목은 남기고 통장 숫자만 비운다 (2026-11-14 오후 점검 K7)
            page = page.replace("<body>", "<body>" + gate.banner(stop, "이 보고의 통장 숫자", blanked=True), 1)
        try:
            with open(base + ".html", "w", encoding="utf-8") as f:
                f.write(page)
        except OSError as e:
            _say(_write_help(a.출력, e))
            return 7
        made.append(base + ".html")
        if browser:
            pdf = pdfname.stamped(base)
            err = to_pdf(browser, base + ".html", pdf)
            if err:
                _say("%s — %s" % (err, os.path.basename(pdf)))
                pdf_failed = True
            else:
                made.append(pdf)
                for gone in pdfname.prune(base):
                    _say("같은 보고 PDF가 %d개 넘게 쌓여 예전 것을 지움: %s" % (pdfname.KEEP_FROM - 1, os.path.basename(gone)))
    _say("%d년 연간 보고 · 손익 %d개월 · 결산 전표 %s" % (year, len(A["Y"]["months"]), "반영" if A["closed"] else "없음 (감가상각비·법인세 예상)"))
    if not A.get("has_annual"):
        _say("연간자료.csv 없음 — '자료 변환'을 다시 하면 거래처·통장 흐름·결산 법인세가 들어갑니다.")
    _say("만든 파일:")
    for m in made:
        _say("  " + m)
    if pdf_failed:
        _say("PDF: 만들지 못한 것은 HTML을 열고 인쇄 → 'PDF로 저장'을 쓰세요.")
    if a.pdf == "만듦" and not browser:
        _say("PDF: Edge/Chrome을 찾지 못해 HTML만 만들었습니다. HTML을 열고 인쇄 → 'PDF로 저장'을 쓰세요.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="대표 주간·월간 보고서")
    ap.add_argument("유형", choices=["주간", "월간", "연간", "weekly", "monthly"])
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
    ap.add_argument("--연도", default=None, help="연간: 보고할 해 (기본: 기준일의 해, 1~3월이면 지난해)")
    a = ap.parse_args(argv)
    if a.유형 == "연간":
        return _annual(a)
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
        # 현금흐름표 (사용자 2026-11-12): 경영관리 보고 9장. 끝 잔액은 1장 통장 잔액(장부 정기예금 뺌)
        from ceo_report import cashflow
        R["cf"] = cashflow.for_report(a.입력, R)
        try:   # 자료 안내: 신용평가 최근 결과 한 줄은 달마다 (사용자 2026-11-13)
            from ceo_report import credit as _cr
            R["credit_brief"] = _cr.brief(_cr.compute(a.입력, R["period"][1]))
        except Exception as e:   # 한 줄 때문에 보고서를 못 만들면 안 된다
            R["credit_brief"] = "기업신용평가 미리보기: 계산하지 못함 (%s)" % type(e).__name__
        if R["period"][1].month == 9:   # 기업신용평가 미리보기: 9월분 '결산 준비' 부록 C-5 (사용자 2026-11-12 카드, 예전 11·12월) + 연간 보고
            from ceo_report import credit
            R["credit"] = credit.compute(a.입력, R["period"][1])
        # 이익잉여금처분계산서 (사용자 2026-11-12): 경영관리 보고 10장. 보고 기준 해(1~3월이면 아직 처분 전인 작년)
        from ceo_report import surplus
        R["re"] = surplus.for_report(a.입력, asof.year if asof.month > 3 else asof.year - 1, R)
        # 세무조정 예상·세법 기준 확인 (사용자 2026-11-12)
        from ceo_report import taxadj, filing
        R["taxadj"] = taxadj.load(a.입력)
        from ceo_report import taxreturn   # 실제 법인세 신고서 (사용자 2026-11-13)
        R["taxret_dir"] = a.입력 if taxreturn.load(a.입력) else None
        R["filing"] = filing.load(a.입력)   # 신고 일정 (장부 기준, 사용자 2026-11-12)
        from ceo_report import filehelp
        from ceo_report.util import esc as _esc
        R["filing_help"] = filehelp.render(filehelp.load(a.입력), _esc)
        from ceo_report import payroll   # 급여 점검·연말정산 예상 (사용자 2026-11-12) — 위하고 인사·급여 자료가 있을 때만
        R["payroll"] = payroll.for_report(a.입력, asof)
    # 자동 분석 (사용자 2026-11-12): 변환이 남긴 장부 분석, 계산서 입금 기록, 지난 보고 때 일정
    from ceo_report import insights
    R["auto_facts"] = insights.read_facts(a.입력)
    from ceo_report import gate as _gate   # 자료가 막히면 경영관리·현황에서도 자금 숫자를 비운다 (사용자 2026-11-14)
    _gate.blank_funds(R)
    R["_invoices"] = data.invoices
    R["auto_prev"] = insights.load_previous(a.출력, asof)
    R["auto_records"] = insights.load_records(a.출력)
    R["auto_profits"] = insights.load_profit_forecasts(a.출력)
    R["_txns"] = data.txns   # 예측 입금 vs 실제 입금
    from ceo_report import digest   # 경영관리 1쪽 요약 '바뀜' 비교용 지난 보고 신호 (사용자 2026-11-12)
    R["lights_prev"] = digest.load_previous(a.출력, kind, asof)
    R["docs_files"] = digest.find_docs(a.출력, asof)   # 자료 안내: 따로 만드는 자료의 마지막 파일 (사용자 2026-11-13)
    from ceo_report import gasu   # 가수금 갚을 시기 (사용자 2026-11-13: 전부 갚아도 자금에 영향 없는지) — 경영관리 B-2-1
    R["gasu"] = gasu.for_report(a.입력, R)
    if kind == "weekly":
        # 지난주 보고가 남긴 지급 예정 기록과 비교 (사용자 2026-11-03). 이번 기록은 보고서를 다 쓴 뒤 남긴다.
        from ceo_report.weekdiff import load_previous
        R["week_prev"] = load_previous(a.출력, asof)
    label = "주간" if kind == "weekly" else "월간"
    browser = find_browser() if a.pdf == "만듦" else None
    made = []
    pdf_failed = False
    # 자금계획서·분개장 미반영이면 대표·팀장 보고를 만들지 않는다 (사용자 2026-11-12: 다시는 이런 실수가 없어야 함)
    from ceo_report import gate
    stop = gate.problems(R)
    if stop:
        _say("대표·팀장 보고를 만들지 않습니다 — 자금계획서·분개장 미반영: " + " / ".join(stop))
        _say("경영관리 보고는 맨 위에 경고를 달고 만듭니다.")
    for mode, who in (("ceo", "대표보고"), ("mgmt", "경영관리보고")):
        base = os.path.join(a.출력, "%s_%s_%s" % (asof.isoformat(), label, who))
        if mode == "ceo" and stop:
            try:   # 같은 이름의 예전 보고가 최신처럼 남지 않게 '만들지 않음' 안내로 덮는다. PDF 는 만들지 않는다
                with open(base + ".html", "w", encoding="utf-8") as f:
                    f.write(gate.stop_page("%s %s" % (label, who), stop))
            except OSError as e:
                _say(_write_help(a.출력, e))
                return 7
            continue
        page = render(R, mode)   # 먼저 다 만든 뒤 연다: 만들다 실패해도 이전 보고 파일이 빈 파일로 덮이지 않게
        try:
            with open(base + ".html", "w", encoding="utf-8") as f:
                f.write(page)
        except OSError as e:
            _say(_write_help(a.출력, e))
            return 7
        made.append(base + ".html")
        if browser:
            pdf = pdfname.stamped(base)   # 만든 시각을 이름에 (사용자 2026-11-12)
            limit = ceo_pages(base + ".html")
            err = fit_pdf(browser, base + ".html", pdf, limit)
            if not err and limit and (pdf_pages(pdf) or 0) > limit and not R.get("_issue_compact"):
                # 출금 목록이 길어 글자를 줄여도 넘치면 '계산서 발행 기한' 표를 두어 줄로 줄여 다시 만든다 (2026-11-13 실제 21건에서 주간 4쪽)
                R["_issue_compact"] = True
                try:
                    with open(base + ".html", "w", encoding="utf-8") as f:
                        f.write(render(R, mode))
                    err = fit_pdf(browser, base + ".html", pdf, limit)
                finally:
                    R.pop("_issue_compact", None)
            if err:
                _say("%s — %s" % (err, os.path.basename(pdf)))
                pdf_failed = True
            else:
                made.append(pdf)
                for gone in pdfname.prune(base):
                    _say("같은 보고 PDF가 %d개 넘게 쌓여 예전 것을 지움: %s" % (pdfname.KEEP_FROM - 1, os.path.basename(gone)))
    if kind == "monthly" and a.팀장용 == "만듦" and stop:
        from ceo_report.teamreport import team_names
        folder = os.path.join(a.출력, "팀장용")
        try:
            os.makedirs(folder, exist_ok=True)
            for team in team_names(data):
                with open(os.path.join(folder, "%s_월간_팀장_%s.html" % (asof.isoformat(), team)), "w", encoding="utf-8") as f:
                    f.write(gate.stop_page("월간 팀장 보고 · %s" % team, stop))
        except OSError as e:
            _say(_write_help(folder, e))
    elif kind == "monthly" and a.팀장용 == "만듦":
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
                pdf_path = pdfname.stamped(page_path[:-5])
                err = to_pdf(browser, page_path, pdf_path)
                if err:
                    _say("%s — %s" % (err, os.path.basename(pdf_path)))
                    pdf_failed = True
                else:
                    made.append(pdf_path)
                    for gone in pdfname.prune(page_path[:-5]):
                        _say("같은 보고 PDF가 %d개 넘게 쌓여 예전 것을 지움: %s" % (pdfname.KEEP_FROM - 1, os.path.basename(gone)))
    if kind == "monthly" and R.get("re"):
        # 이익잉여금 쉬운 설명·처분계산서·결산 처리 제안 양식 (사용자 2026-11-13): 출력/결산/ 에 따로 한 부
        from ceo_report import surplus
        try:
            re_page = surplus.write_page(R["re"], a.출력, asof)
        except OSError as e:
            _say(_write_help(os.path.join(a.출력, "결산"), e))
            re_page = None
        if re_page:
            made.append(re_page)
            if browser:
                pdf_path = pdfname.stamped(re_page[:-5])
                err = to_pdf(browser, re_page, pdf_path)
                if err:
                    _say("%s — %s" % (err, os.path.basename(pdf_path)))
                    pdf_failed = True
                else:
                    made.append(pdf_path)
                    pdfname.prune(re_page[:-5])
    try:
        digest.write_record(a.출력, R)
    except OSError as e:
        _say("경영관리 신호등 기록을 남기지 못했습니다 (다음 보고 '바뀜' 표시에 쓰임): %s" % e)
    try:
        insights.write_record(a.출력, R)
    except OSError as e:
        _say("자동 분석 일정 기록을 남기지 못했습니다 (다음 보고 '바뀐 이유'에 쓰임): %s" % e)
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
        _say("입력 자료 확인 필요 %d건 — 경영관리보고 '부록 B-7 변동·자료 범위' 안의 '입력 자료 확인 필요' 표에 있습니다 (대표보고에는 없음)." % n)
    bad = [c for c in R["s7"]["checks"] if not c[3]]
    if bad:
        _say("대조 불일치 %d건 — 경영관리보고 '부록 B-7 변동·자료 범위' 안의 '보고 대조' 표를 확인하세요 (대표보고에는 없음)." % len(bad))
    if kind == "monthly" and R["xchk"]["state"] != "ok":
        if R["xchk"]["state"] == "자료 없음":
            _say("위하고 대조 자료 없음 — 대표보고 창에서 '자료 변환'을 먼저 하면 월간 경영관리보고 '부록 B-8 WEHAGO 기준 대조'에 들어갑니다.")
        else:
            _say("위하고 대조 읽을 수 없음 — %s. 월간 경영관리보고 '부록 B-8 WEHAGO 기준 대조'에는 ‘읽을 수 없음’으로 적었습니다." % R["xchk"]["reason"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
