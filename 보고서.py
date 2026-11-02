"""대표 주간·월간 보고서 만들기.

사용법 (명령 창):
    python 보고서.py 주간                      ← 오늘 기준 주간 보고 (대표용·경영관리용)
    python 보고서.py 월간 --기준일 2026-10-31   ← 기준일 지정
    python 보고서.py 주간 --입력 입력 --출력 출력 --pdf 안함

입력 폴더의 CSV(엑셀에서 'CSV UTF-8' 또는 'CSV'로 저장)를 읽어
출력 폴더에 HTML(과 PDF)을 만든다. 대표용과 경영관리용은 같은 숫자를 쓴다.
"""
import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from ceo_report.data import load  # noqa: E402
from ceo_report.calc import compute  # noqa: E402
from ceo_report.render import render  # noqa: E402
from ceo_report.util import date as parse_date  # noqa: E402

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


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


def to_pdf(browser, html_path, pdf_path):
    url = "file:///" + os.path.abspath(html_path).replace("\\", "/").lstrip("/")
    cmd = [browser, "--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
           "--print-to-pdf=" + os.path.abspath(pdf_path), url]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    except Exception as e:  # noqa: BLE001
        return "PDF 실패: %s" % e
    return None if os.path.exists(pdf_path) else "PDF 실패 (브라우저가 파일을 만들지 않음)"


def main(argv=None):
    ap = argparse.ArgumentParser(description="대표 주간·월간 보고서")
    ap.add_argument("유형", choices=["주간", "월간", "weekly", "monthly"])
    ap.add_argument("--기준일", default=None, help="YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--시작일", default=None, help="집계 시작일 (기본: 주간=기준일-6일, 월간=그 달 1일)")
    ap.add_argument("--입력", default=os.path.join(HERE, "입력"))
    ap.add_argument("--출력", default=os.path.join(HERE, "출력"))
    ap.add_argument("--pdf", default="만듦", choices=["만듦", "안함"])
    a = ap.parse_args(argv)
    kind = "weekly" if a.유형 in ("주간", "weekly") else "monthly"
    asof = parse_date(a.기준일) if a.기준일 else dt.date.today()
    if asof is None:
        print("기준일 형식 오류: %s" % a.기준일)
        return 2
    start = parse_date(a.시작일) if a.시작일 else None
    if not os.path.isdir(a.입력):
        print("입력 폴더가 없습니다: %s" % a.입력)
        return 2
    os.makedirs(a.출력, exist_ok=True)
    data = load(a.입력)
    R = compute(data, kind, asof, start)
    label = "주간" if kind == "weekly" else "월간"
    browser = find_browser() if a.pdf == "만듦" else None
    made = []
    for mode, who in (("ceo", "대표보고"), ("mgmt", "경영관리보고")):
        base = os.path.join(a.출력, "%s_%s_%s" % (asof.isoformat(), label, who))
        with open(base + ".html", "w", encoding="utf-8") as f:
            f.write(render(R, mode))
        made.append(base + ".html")
        if browser:
            err = to_pdf(browser, base + ".html", base + ".pdf")
            if err:
                print(err)
            else:
                made.append(base + ".pdf")
    print("보고 기준일 %s · 집계 기간 %s ~ %s" % (asof, R["period"][0], R["period"][1]))
    print("만든 파일:")
    for m in made:
        print("  " + m)
    if a.pdf == "만듦" and not browser:
        print("PDF: Edge/Chrome을 찾지 못해 HTML만 만들었습니다. HTML을 열고 인쇄 → 'PDF로 저장'을 쓰세요.")
    n = len(R["s7"]["issues"])
    if n:
        print("입력 자료 확인 필요 %d건 — 보고서 7번 '입력 자료 확인 필요' 표에 있습니다." % n)
    bad = [c for c in R["s7"]["checks"] if not c[3]]
    if bad:
        print("대조 불일치 %d건 — 보고서 7번 '보고 대조' 표를 확인하세요." % len(bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())
