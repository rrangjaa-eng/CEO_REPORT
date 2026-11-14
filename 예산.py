"""내년 예산 문서 만들기 (사용자 2026-11-10).

사용법 (명령 창):
    python 예산.py                         ← 기준일 오늘, 예산 연도 = 내년. 대표용·경영관리용 초안
    python 예산.py --연도 2027 --확정 함    ← 지금 값으로 확정: 입력/예산확정.csv 저장 (월간 보고 '예산 대비')

사람이 정하는 값은 입력/예산값.csv (창 '가끔 넣는 값' → 내년 예산), 목표 수익률은 입력/팀목표.csv.
결과: 출력/예산/<연도>_예산_대표용.html·pdf, <연도>_예산_경영관리용.html·pdf
종료 코드: 0 완료 · 2 입력 문제 · 7 출력 폴더에 파일을 쓰지 못함
"""
import argparse
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from ceo_report import budget  # noqa: E402
from ceo_report.budget_render import render_budget  # noqa: E402
from ceo_report.data import load  # noqa: E402
from ceo_report.util import date as parse_date  # noqa: E402
from ceo_report.util import mask_rrn  # noqa: E402
from ceo_report import pdfname  # noqa: E402


def _say(text):
    print(mask_rrn(text))


def main(argv=None):
    import 보고서
    ap = argparse.ArgumentParser(description="내년 예산 문서")
    ap.add_argument("--기준일", default=None, help="YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--연도", default=None, help="예산 연도 (기본: 기준일 다음 해)")
    ap.add_argument("--확정", default="안함", choices=["함", "안함"])
    ap.add_argument("--입력", default=os.path.join(HERE, "입력"))
    ap.add_argument("--출력", default=os.path.join(HERE, "출력"))
    ap.add_argument("--pdf", default="만듦", choices=["만듦", "안함"])
    a = ap.parse_args(argv)
    asof = parse_date(a.기준일) if a.기준일 else dt.date.today()
    if asof is None:
        _say("기준일 형식 오류: %s" % a.기준일)
        return 2
    year = a.연도.strip() if a.연도 else str(asof.year + 1)
    if not (year.isdigit() and len(year) == 4):
        _say("연도는 4자리 (예: 2027): %s" % a.연도)
        return 2
    year = int(year)
    if not os.path.isdir(a.입력):
        _say("입력 폴더가 없습니다: %s" % a.입력)
        return 2
    out = os.path.join(a.출력, "예산")
    try:
        os.makedirs(out, exist_ok=True)
    except OSError as e:
        _say("출력 폴더에 파일을 쓰지 못했습니다: %s (%s)" % (out, e.strerror or type(e).__name__))
        return 7
    d = load(a.입력)
    B = budget.compute(d, budget.read_values(a.입력), year, asof, d.settings)
    if not B["teams"]:
        _say("%d년 팀 매출 자료(손익.csv 팀 줄)가 없어 예산을 만들 수 없습니다. 먼저 '자료 변환'을 하세요." % B["base"])
        return 2
    confirmed = None
    if a.확정 == "함":
        try:
            n = budget.confirm(a.입력, B, asof)
        except OSError as e:
            _say("예산확정.csv 를 쓰지 못했습니다: %s" % (e.strerror or type(e).__name__))
            return 7
        confirmed = asof.isoformat()
        _say("%d년 예산 확정: 입력/%s 에 %d줄 저장 — 다음 월간 보고부터 '예산 대비'가 붙습니다." % (year, budget.CONFIRM_FILE, n))
    else:
        old = budget.read_confirmed(a.입력).get(str(year))
        if old:
            _say("참고: %d년 예산은 %s에 확정된 것이 있습니다. 이번 것은 초안이고, 월간 보고는 확정한 예산을 씁니다." % (year, old["date"]))
    browser = 보고서.find_browser() if a.pdf == "만듦" else None
    made = []
    company = (d.settings.get("회사명") or "").strip()
    for mode, who in (("ceo", "대표용"), ("mgmt", "경영관리용")):
        base = os.path.join(out, "%d_예산_%s" % (year, who))
        page = render_budget(B, mode, company, confirmed)
        try:
            with open(base + ".html", "w", encoding="utf-8") as f:
                f.write(page)
        except OSError as e:
            _say("파일을 쓰지 못했습니다: %s (%s)" % (base + ".html", e.strerror or type(e).__name__))
            return 7
        made.append(base + ".html")
        if browser:
            pdf = pdfname.stamped(base)   # 만든 시각을 이름에 (사용자 2026-11-12)
            err = 보고서.to_pdf(browser, base + ".html", pdf)
            if err:
                _say("%s — %s" % (err, os.path.basename(pdf)))
            else:
                made.append(pdf)
                for gone in pdfname.prune(base):
                    _say("같은 보고 PDF가 %d개 넘게 쌓여 예전 것을 지움: %s" % (pdfname.KEEP_FROM - 1, os.path.basename(gone)))
    Y = B["Y"]
    _say("%d년 예산 %s · 매출 %s · 영업이익 %s" % (year, "확정" if confirmed else "초안", "{:,}".format(Y["rev"]),
                                          "미확인" if Y["op"] is None else "{:,}".format(Y["op"])))
    if B["missing"]:
        _say("입력 전 값: %s — 창 '가끔 넣는 값' → 내년 예산·팀 목표에서 넣으면 다시 계산됩니다." % ", ".join(B["missing"]))
    for x in B["notes"]:
        _say("확인: " + x)
    _say("만든 파일:")
    for m in made:
        _say("  " + m)
    if a.pdf == "만듦" and not browser:
        _say("PDF: Edge/Chrome을 찾지 못해 HTML만 만들었습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
