"""신고 일정 (사용자 2026-11-12: 제출기한도 장부를 보고 프로그램이 알려 줘야).

장부(분개장)에서 실제로 생긴 일을 보고 그에 따른 신고·제출 기한을 만든다:
  · 예수금 적요 '사업소득지급시' → 사업소득 간이지급명세서 (지급한 달의 다음 달 말일), 지급명세서 (다음 해 3/10)
  · '기타소득' + 경품 구입(선급금_기타소득) → 경품 기타소득은 연 1회 지급명세서 (다음 해 2월 말).
    경품이 아닌 기타소득(강연료 등 인적용역)은 매월 간이지급명세서 — 적요만으로 못 가려 '확인 필요'로 같이 알림
  · '급여지급시' → 근로소득 간이지급명세서 (주기는 세법 기준표), 지급명세서 3/10, 연말정산(2월 급여), 4대보험 보수총액(3/10·3/15)
  · 원천세: 반기 납부(1·7월에만 냈으면) 7/10·1/10, 아니면 매달 10일
  · 부가세: 법인 1·2기 예정(4/25·10/25)·확정(7/25·1/25)
  · 법인세 3/31, 지방소득세 4/30, 중간예납 8/31 (설립 첫해 다음 해부터)
기한이 토·일이면 월요일. 공휴일은 따지지 않음(홈택스 안내 확인). 신고를 했는지는 장부에 납부 전표가 있는 것만 알 수 있다.
"""
import collections
import datetime as dt
import re

from .surplus import FOUNDED

FILE = "신고일정.csv"
COLUMNS = ["기한", "신고", "대상", "장부 근거", "어디서", "상태"]
HOMETAX = {
    "부가세": "홈택스 › 세금신고 › 부가가치세 신고 › 일반과세자",
    "원천세": "홈택스 › 세금신고 › 원천세 신고 › 일반신고",
    "간이지급": "홈택스 › 지급명세·자료제출 › 간이지급명세서",
    "지급명세서": "홈택스 › 지급명세·자료제출 › 지급명세서 제출",
    "법인세": "홈택스 › 세금신고 › 법인세 신고 (세무사)",
    "지방소득세": "위택스 › 신고하기 › 법인지방소득세",
    "보수총액": "건강보험 EDI (3/10) · 근로복지공단 고용·산재 토탈서비스 (3/15)",
}


def _sq(t):
    return re.sub(r"\s+", "", str(t or ""))


def _workday(d):
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def _month_end(y, m):
    nxt = dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return nxt - dt.timedelta(days=1)


def _next_month_end(y, m):
    return _month_end(y + (m == 12), 1 if m == 12 else m + 1)


def scan(journal):
    """장부 → 달별로 생긴 일 {(y, m): {"사업": 세액, "기타": 세액, "근로": 세액, "경품": 금액}} 와 원천세 낸 날."""
    ev = collections.defaultdict(lambda: collections.defaultdict(int))
    paid = []
    for ln in journal or []:
        d = ln.get("date")
        if d is None:
            continue
        name, memo, vendor = _sq(ln.get("account")), _sq(ln.get("memo")), _sq(ln.get("vendor"))
        cr, dr = ln.get("credit") or 0, ln.get("debit") or 0
        key = (d.year, d.month)
        if name == "예수금" and "세무서" in vendor:
            if cr:
                if "사업소득" in memo:
                    ev[key]["사업"] += cr
                elif "기타소득" in memo:
                    ev[key]["기타"] += cr
                elif "급여" in memo:
                    ev[key]["근로"] += cr
            elif dr:
                paid.append(d)
        if "기타소득" in name and dr and ("경품" in memo or "상품권" in memo):
            ev[key]["경품"] += dr
    return ev, paid


def calendar(journal, asof, input_dir=None, ahead_days=100, back_days=40):
    """-> [{기한, 신고, 대상, 장부 근거, 어디서, 상태}] 기한 순. asof 앞 back_days ~ 뒤 ahead_days."""
    from . import taxlaw
    ev, paid = scan(journal)
    rows = []

    def add(due, what, target, basis, where, warn=""):
        due = _workday(due)
        if asof - dt.timedelta(days=back_days) <= due <= asof + dt.timedelta(days=ahead_days):
            done = what.startswith("원천세") and any(due - dt.timedelta(days=15) <= p <= due for p in paid)
            st = "냄 (장부 납부 전표 있음)" if done else ("지남 — 했는지 확인" if due < asof else
                                                  ("이번 주" if (due - asof).days <= 7 else "%d일 남음" % (due - asof).days))
            rows.append({"기한": due.isoformat(), "신고": what, "대상": target, "장부 근거": basis + (" · " + warn if warn else ""),
                         "어디서": where, "상태": st})
    years = sorted(set(y for y, _ in ev) | {asof.year})
    # 원천세: 반기 납부 판단 (가장 최근 해에 1·7월에만 냈으면 반기)
    recent = [p for p in paid if paid and p.year == max(x.year for x in paid)]
    half = bool(recent) and all(p.month in (1, 7) for p in recent)
    for (y, m), v in sorted(ev.items()):
        if v["사업"]:
            add(_next_month_end(y, m), "사업소득 간이지급명세서", "%d년 %d월 지급분" % (y, m),
                "적요 '사업소득지급시' 소득세 %s원 → 지급액 약 %s원 (3%%)" % (format(v["사업"], ","), format(int(v["사업"] / 0.03), ",")),
                HOMETAX["간이지급"])
        if v["기타"] and v["기타"] > 0:
            add(_next_month_end(y, m), "기타소득 간이지급명세서 (인적용역만)", "%d년 %d월 지급분" % (y, m),
                "적요 '기타소득' 소득세 %s원" % format(v["기타"], ","), HOMETAX["간이지급"],
                "경품 기타소득이면 대상 아님(연 1회 지급명세서) — 강연료 등 사람에게 준 용역 대가만 매월 제출" if v["경품"] else "")
        if not half and (v["사업"] or v["기타"] or v["근로"]):
            add(dt.date(y + (m == 12), 1 if m == 12 else m + 1, 10), "원천세 신고·납부", "%d년 %d월분" % (y, m),
                "근로 %s · 사업 %s · 기타 %s원 (소득세)" % (format(v["근로"], ","), format(v["사업"], ","), format(v["기타"], ",")), HOMETAX["원천세"])
    for y in years:
        tot = lambda k, months: sum(ev.get((y, m), {}).get(k, 0) for m in months)
        if half:
            for h, months, due in ((1, range(1, 7), dt.date(y, 7, 10)), (2, range(7, 13), dt.date(y + 1, 1, 10))):
                if any(tot(k, months) for k in ("근로", "사업", "기타")):
                    add(due, "원천세 신고·납부 (반기)", "%d년 %s반기" % (y, "상" if h == 1 else "하"),
                        "근로 %s · 사업 %s · 기타 %s원 (소득세, 1·7월에만 내 반기 납부로 봄)" % tuple(format(tot(k, months), ",") for k in ("근로", "사업", "기타")),
                        HOMETAX["원천세"])
        wage_months = [m for m in range(1, 13) if ev.get((y, m), {}).get("근로")]
        if wage_months:
            cyc = taxlaw.checked(input_dir, y, "근로간이지급주기", "")[0] or ""
            if str(cyc).startswith("매월"):
                for m in wage_months:
                    add(_next_month_end(y, m), "근로소득 간이지급명세서", "%d년 %d월 지급분" % (y, m), "급여 전표 있음", HOMETAX["간이지급"])
            else:
                if any(m <= 6 for m in wage_months):
                    add(dt.date(y, 7, 31), "근로소득 간이지급명세서 (반기)", "%d년 1~6월 지급분" % y, "급여 전표 %d달" % sum(1 for m in wage_months if m <= 6), HOMETAX["간이지급"])
                if any(m > 6 for m in wage_months):
                    add(dt.date(y + 1, 1, 31), "근로소득 간이지급명세서 (반기)", "%d년 7~12월 지급분" % y, "급여 전표 %d달" % sum(1 for m in wage_months if m > 6), HOMETAX["간이지급"])
            add(dt.date(y + 1, 3, 10), "근로·퇴직소득 지급명세서 (연말정산 결과)", "%d년 지급분" % y, "2월 급여 때 연말정산, 결과를 3/10까지 제출", HOMETAX["지급명세서"])
            add(dt.date(y + 1, 3, 10), "4대보험 보수총액 신고", "%d년 보수" % y, "건강보험 3/10, 고용·산재 3/15", HOMETAX["보수총액"])
        if any(ev.get((y, m), {}).get("사업") for m in range(1, 13)):
            add(dt.date(y + 1, 3, 10), "사업소득 지급명세서", "%d년 지급분" % y, "사업소득 지급 %d달" % sum(1 for m in range(1, 13) if ev.get((y, m), {}).get("사업")), HOMETAX["지급명세서"])
        if any(ev.get((y, m), {}).get("기타") for m in range(1, 13)):
            gift = sum(ev.get((y, m), {}).get("경품", 0) for m in range(1, 13))
            add(_month_end(y + 1, 2), "기타소득 지급명세서", "%d년 지급분" % y,
                "기타소득 원천징수 %d달%s" % (sum(1 for m in range(1, 13) if ev.get((y, m), {}).get("기타")), " · 경품 구입 %s원" % format(gift, ",") if gift else ""),
                HOMETAX["지급명세서"])
        # 부가세 (법인: 예정·확정 모두 신고)
        for due, what, target in ((dt.date(y, 4, 25), "부가세 1기 예정신고", "%d년 1~3월" % y), (dt.date(y, 7, 25), "부가세 1기 확정신고", "%d년 4~6월" % y),
                                  (dt.date(y, 10, 25), "부가세 2기 예정신고", "%d년 7~9월" % y), (dt.date(y + 1, 1, 25), "부가세 2기 확정신고", "%d년 10~12월" % y)):
            add(due, what, target, "매출·매입 세금계산서 (신고 도우미 참고)", HOMETAX["부가세"])
        if y >= FOUNDED:
            add(dt.date(y + 1, 3, 31), "법인세 신고·납부", "%d년" % y, "결산 뒤 세무사", HOMETAX["법인세"])
            add(dt.date(y + 1, 4, 30), "법인지방소득세 신고·납부", "%d년" % y, "법인세의 10%", HOMETAX["지방소득세"])
        if y > FOUNDED:
            add(dt.date(y, 8, 31), "법인세 중간예납", "%d년 상반기" % y, "작년 법인세의 절반 또는 상반기 가결산 (설립 첫해 다음 해부터)", HOMETAX["법인세"])
    rows.sort(key=lambda r: (r["기한"], r["신고"]))
    seen, out = set(), []
    for r in rows:
        k = (r["기한"], r["신고"], r["대상"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def build_table(books, cfg, asof, input_dir=None):
    from .convert import Table
    if books.state != "ok" or not books.journal:
        return Table(FILE, COLUMNS, [], written=False, reason="분개장 없음 (기존 파일 그대로)")
    rows = calendar(books.journal, asof, input_dir)
    soon = [r for r in rows if r["상태"] in ("이번 주",) or r["상태"].startswith("지남")]
    return Table(FILE, COLUMNS, rows, notes=["신고 일정 %d건 (이번 주·지난 것 %d건)" % (len(rows), len(soon))])


def load(input_dir):
    import csv
    import os
    path = os.path.join(input_dir, FILE)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f)) or None


def render(rows, esc, asof=None, limit=None):
    if not rows:
        return ""
    show = rows if limit is None else rows[:limit]
    h = ["<table class='re'><tr><th>기한</th><th class='l'>신고</th><th class='l'>대상</th><th>상태</th><th class='l'>장부 근거</th><th class='l'>어디서</th></tr>%s</table>"
         % "".join("<tr><td>%s</td><td class='l'><b>%s</b></td><td class='l'>%s</td><td>%s</td><td class='l'>%s</td><td class='l'>%s</td></tr>"
                   % (esc(r["기한"]), esc(r["신고"]), esc(r["대상"]),
                      ("<b style='color:#c62828'>%s</b>" % esc(r["상태"])) if r["상태"].startswith("지남") or r["상태"] == "이번 주" else esc(r["상태"]),
                      esc(r["장부 근거"]), esc(r["어디서"])) for r in show),
         "<div class='note'>장부에서 생긴 일(급여·사업소득·기타소득 원천징수, 원천세 납부 날)로 만든 일정입니다. 토·일이면 월요일로 미룸, 공휴일은 따지지 않음. "
         "제출 주기는 세법 기준표에서 읽으며 홈택스 메뉴 이름은 바뀔 수 있습니다.</div>"]
    return "".join(h)


def live_lines(rows, asof):
    """지금현황 맨 위: 2주 안 기한과 지난 것."""
    if not rows:
        return []
    out = []
    for r in rows:
        d = dt.date.fromisoformat(r["기한"])
        if r["상태"].startswith("냄"):
            continue
        if d < asof or (d - asof).days <= 14:
            out.append("%s %s (%s) — %s" % (r["기한"], r["신고"], r["대상"], r["상태"]))
    return out
