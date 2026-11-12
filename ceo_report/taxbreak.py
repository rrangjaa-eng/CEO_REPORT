"""법인세 감면·공제 후보 점검 (사용자 2026-11-12: 현재 회사 기준으로 받을 수 있는 감면·공제 추천).

AI 없이 규칙으로만 본다:
  · 회사 자료: 설립 연도(2025), 사원급여.csv 월별 인원(상시근로자 근사), 세금예상.csv 법인세 과세표준·산출세액,
    장부에 장비(유형자산)·연구개발비 계정이 있는지.
  · 사용자 답: 배당설정.csv 의 '법인세 감면' 묶음 질문 (dividend.QUESTIONS).
각 후보는 '해당'(조건이 모두 '예') · '확인 필요'(모름이 섞임) · '해당 없음' · '나중'(지금은 조건이 안 됨)으로 나눈다.
예상 금액은 '해당'만 더해 배당 판단에 쓰고(법인세감면 칸을 비웠을 때), 나머지는 보여 주기만 한다.
세율·금액은 2025년 창업 당시 조세특례제한법 기준 간이 계산이며, 실제 적용은 세무사 확인이 필요하다.
"""
import collections
import csv
import os

from .surplus import FOUNDED

MIN_TAX = 0.07          # 중소기업 최저한세율 (과세표준의 7%)
LOCAL_RATE = 0.10       # 법인지방소득세도 같은 비율로 줄어든다
SME_START_YEARS = 5     # 창업중소기업 감면: 창업 후 처음 소득 난 해부터 5년
# 통합고용세액공제 (중소기업, 상시근로자 1명 늘 때 1년 공제액, 3년간): 청년 등 / 그 밖
HIRE = {"수도권": (14_500_000, 8_500_000), "지방": (15_500_000, 9_500_000)}


def W(v):
    return "{:,}".format(int(round(v)))


def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def corp_base(input_dir, year):
    """세금예상.csv 법인세 줄 -> (과세표준, 산출세액, 근거) 또는 None."""
    for r in _read_csv(os.path.join(input_dir, "세금예상.csv")):
        if (r.get("세목") or "").strip() == "법인세" and str(year) in (r.get("대상기간") or ""):
            try:
                return int(float(r.get("과세표준") or 0)), int(float(r.get("산출세액") or 0)), (r.get("대상기간") or "").strip()
            except ValueError:
                return None
    return None


def headcount(input_dir, exclude=()):
    """사원급여.csv -> {연도: (월평균 인원, 들어온 달 수)}. 주주(대표·가족)는 상시근로자가 아니라 뺀다."""
    ex = set(n.strip() for n in exclude if n)
    per = collections.defaultdict(set)
    for r in _read_csv(os.path.join(input_dir, "사원급여.csv")):
        ym, name = (r.get("연월") or "").strip(), (r.get("사원명") or "").strip()
        if len(ym) >= 7 and name and name not in ex:
            per[ym[:7]].add(name)
    years = collections.defaultdict(list)
    for ym, names in per.items():
        years[int(ym[:4])].append(len(names))
    return dict((y, (sum(v) / float(len(v)), len(v))) for y, v in years.items())


def assets_by_year(journal):
    """장부 신호 -> {연도: (장비·비품 산 금액, 연구개발비)}. 변환 때 잉여금.csv 에 같이 적는다."""
    out = collections.defaultdict(lambda: [0, 0])
    for ln in journal or []:
        d = ln.get("date")
        if d is None:
            continue
        code, name = str(ln.get("account_code") or ""), str(ln.get("account") or "")
        dr = ln.get("debit") or 0
        if code[:3] in ("206", "207", "208", "209", "210", "212", "213") or any(w in name for w in ("기계장치", "비품", "공구", "시설장치")):
            out[d.year][0] += dr
        if "연구" in name and "개발" in name:
            out[d.year][1] += dr
    return dict((y, tuple(v)) for y, v in out.items())


def check(input_dir, year, answers, holders=(), assets=None):
    """assets = (장비 산 금액, 연구개발비) 또는 None(장부 신호 모름).
    -> {year, rows:[(이름, 상태, 예상 금액|None, 근거, 할 일)], total(해당만, 최저한세 반영), local, base, tax, note}."""
    a = answers or {}
    cb = corp_base(input_dir, year)
    base, tax, period = cb if cb else (None, None, "")
    rows = []
    young, dense, metro = a.get("청년창업"), a.get("과밀억제"), a.get("수도권")
    # 1) 창업중소기업 세액감면 (조특법 6조)
    rate = None
    if dense in ("예", "아니오") and young in ("예", "아니오"):
        rate = {("아니오", "예"): 1.0, ("아니오", "아니오"): 0.5, ("예", "예"): 0.5, ("예", "아니오"): 0.0}[(dense, young)]
    last = FOUNDED + SME_START_YEARS - 1
    if year > last:
        rows.append(("창업중소기업 세액감면", "해당 없음", None, "감면 기간(%d~%d년)이 지남" % (FOUNDED, last), ""))
    elif rate == 0.0:
        rows.append(("창업중소기업 세액감면", "해당 없음", None, "과밀억제권역 안에서 만 35세 이상 창업은 감면 대상이 아님",
                     "본점을 과밀억제권역 밖으로 옮기는 경우는 세무사와 따로 검토"))
    else:
        amt = int(tax * rate) if tax is not None and rate is not None else None
        bad = [k for k in ("신규창업", "감면업종") if a.get(k) == "아니오"]
        unk = [k for k in ("신규창업", "감면업종", "과밀억제") if a.get(k) in (None, "", "모름")]
        why = "%d년 창업, %d~%d년 감면. 지역·나이 기준 감면율 %s" % (
            FOUNDED, FOUNDED, last, "%d%%" % (rate * 100) if rate is not None else "모름")
        if bad:
            rows.append(("창업중소기업 세액감면", "해당 없음", None, why + " — 새 창업 또는 감면 업종이 아님", ""))
        elif unk:
            rows.append(("창업중소기업 세액감면", "확인 필요", amt, why,
                         "세무사에게 '행사 대행 등 우리 업종이 창업 감면 업종인지, 새 창업으로 보는지' 확인"))
        else:
            rows.append(("창업중소기업 세액감면", "해당", amt, why + " · 법인세 산출세액 × 감면율", "법인세 신고 때 세액감면신청서 제출"))
    # 2) 중소기업 특별세액감면 (조특법 7조) — 창업 감면과 같은 해 함께 못 받음
    st1 = rows[0][1]
    rows.append(("중소기업 특별세액감면", "나중" if st1 in ("해당", "확인 필요") else "확인 필요", None,
                 "창업 감면과 한 해에 같이 받지 못함 — 창업 감면이 안 되는 해의 대안. 감면율은 업종·회사 크기·지역에 따라 5~30%",
                 "창업 감면이 안 되면 세무사에게 업종·소기업 여부 확인"))
    # 3) 통합고용세액공제 (조특법 29조의8) — 상시근로자 증가 1명당, 3년간
    hc = headcount(input_dir, holders)
    zone = "수도권" if metro == "예" else ("지방" if metro == "아니오" else None)
    per_other = HIRE[zone][1] if zone else None
    cur = hc.get(year)
    prev = hc.get(year - 1) if year - 1 >= FOUNDED else (0.0, 12)
    if cur is None:
        rows.append(("통합고용세액공제", "확인 필요", None, "%d년 급여 자료 없음" % year, ""))
    elif prev is None:
        rows.append(("통합고용세액공제", "확인 필요", None,
                     "%d년 월평균 직원 %.1f명 (주주 뺌, %d달). %d년 인원을 몰라 늘어난 인원을 아직 못 셈" % (year, cur[0], cur[1], year - 1),
                     "%d년 분개장이 들어오면 자동 계산" % (year - 1)))
    else:
        inc = []
        for y in range(max(year - 2, FOUNDED), year + 1):   # 공제는 늘어난 해부터 3년 (인원 유지 시)
            c, p = hc.get(y), (hc.get(y - 1) if y - 1 >= FOUNDED else (0.0, 12))
            if c and p is not None and c[0] > p[0] and cur[0] >= c[0] - 1e-9:
                inc.append((y, c[0] - p[0]))
        n = sum(v for _, v in inc)
        amt = int(n * per_other) if per_other and n > 0 else (0 if n <= 0 else None)
        why = "월평균 직원(주주 뺌) %d년 %.1f명 ← %d년 %.1f명%s. %s" % (
            year, cur[0], year - 1, prev[0], " (%d달만 있음)" % cur[1] if cur[1] < 12 else "",
            " · ".join("%d년 +%.1f명" % (y, v) for y, v in inc) if inc else "늘어난 인원 없음")
        if n <= 0:
            rows.append(("통합고용세액공제", "해당 없음", None, why, "직원이 늘면 1명당 연 %s원 이상 (3년)" % W(per_other or HIRE["수도권"][1])))
        else:
            rows.append(("통합고용세액공제", "해당" if zone and cur[1] >= 12 else "확인 필요", amt,
                         why + " × 1명당 %s원 (청년·60세 이상 등은 %s원으로 더 큼)" % (W(per_other), W(HIRE[zone][0])) if zone else why,
                         "임원·주주 가족·단시간 근로자는 빼고 세무사가 다시 셈. 인원이 줄면 받은 공제를 토해 냄"))
    # 4) 작년(2025)분 놓친 감면·공제 — 5년 안 경정청구
    if year - 1 >= FOUNDED:
        got = a.get("작년감면")
        miss = []
        if got in ("없음", "고용공제", "모름") and rows[0][1] in ("해당", "확인 필요"):
            miss.append("창업 감면")
        if got in ("없음", "창업감면", "모름"):
            miss.append("고용 공제(%d년은 직원 0명에서 시작이라 늘어난 인원 = 그해 월평균 직원)" % FOUNDED)
        if miss:
            rows.append(("%d년분 경정청구" % (year - 1), "확인 필요", None,
                         "작년 신고 때 받지 않았다면 5년 안에 돌려받을 수 있음: " + " · ".join(miss),
                         "세무사에게 %d년 신고서의 감면·공제 내역 확인" % (year - 1)))
    # 5) 연구·인력개발비 세액공제 (조특법 10조)
    eq, rd = assets if assets else (None, None)
    if a.get("연구전담") == "예":
        rows.append(("연구·인력개발비 세액공제", "확인 필요", int(rd * 0.25) if rd else None,
                     "연구소·전담부서 있음. 중소기업은 연구개발비(연구원 인건비 등)의 25%%%s" % (
                         " — 장부 연구개발비 %s원" % W(rd) if rd else " — 장부에 연구개발비 계정이 없어 금액 못 셈"),
                     "연구원 인건비를 연구개발비로 나눠 적는지 세무사 확인"))
    else:
        rows.append(("연구·인력개발비 세액공제", "나중", None, "연구소·전담부서가 있어야 함 (중소기업은 연구개발비의 25%)",
                     "새 서비스 개발 인력이 있으면 전담부서 인정 검토"))
    # 6) 통합투자세액공제 (조특법 24조)
    if eq is None:
        rows.append(("통합투자세액공제", "나중", None, "장비 산 내역은 다음 자료 변환 때 장부에서 읽음 — 사업용 장비를 사면 중소기업 기본 10%", ""))
    elif eq:
        rows.append(("통합투자세액공제", "확인 필요", int(eq * 0.10), "장부 장비·비품 산 금액 %s원 × 중소기업 기본 10%%" % W(eq),
                     "사업용 자산인지(승용차·건물 제외) 세무사 확인"))
    else:
        rows.append(("통합투자세액공제", "나중", None, "장부에 장비 산 내역 없음 — 사업용 장비를 사면 중소기업 기본 10%",
                     "큰 장비를 살 계획이 있으면 산 해에 공제"))
    # 7) 근로소득증대세액공제 (조특법 29조의4) — 직전 3년 평균임금이 있어야 함
    rows.append(("근로소득을 늘린 기업 세액공제", "나중", None,
                 "직전 3년 평균임금 증가율이 필요해 %d년 이후 가능" % (FOUNDED + 3), ""))
    if a.get("벤처") == "예":
        rows.append(("벤처기업 관련 감면", "확인 필요", None, "벤처 확인을 받았으면 창업 감면 기간·감면율이 달라질 수 있음", "세무사 확인"))
    total = sum(r[2] for r in rows if r[1] == "해당" and r[2])
    note = ""
    if base is not None and tax is not None and total:
        floor = int(base * MIN_TAX)
        cap = max(tax - floor, 0)
        full_start = rows[0][1] == "해당" and rate == 1.0
        if total > cap and not full_start:
            note = "최저한세(과세표준의 7%% = %s원) 때문에 줄일 수 있는 세금은 %s원까지" % (W(floor), W(cap))
            total = cap
        total = min(total, tax)
    return {"year": year, "rows": rows, "total": total, "local": int(total * LOCAL_RATE), "base": base, "tax": tax,
            "period": period, "note": note}


def render(T, esc):
    if not T:
        return ""
    tag = {"해당": "<span class='tag'>해당</span>", "확인 필요": "<span class='tag e'>확인 필요</span>",
           "해당 없음": "<span class='tag' style='opacity:.5'>해당 없음</span>", "나중": "<span class='tag' style='opacity:.7'>나중</span>"}
    h = ["<div class='q'>법인세를 줄일 수 있는 감면·공제 (%d년)</div>" % T["year"]]
    if T["tax"] is not None:
        h.append("<div class='say'>%s 법인세 산출세액 %s원 (과세표준 %s원). '해당'만 더하면 법인세 %s원 + 지방소득세 %s원이 줄어듭니다.%s</div>"
                 % (esc(T["period"]), W(T["tax"]), W(T["base"]), W(T["total"]), W(T["local"]),
                    " " + esc(T["note"]) + "." if T["note"] else ""))
    h.append("<table class='re'><tr><th class='l'>감면·공제</th><th>판단</th><th>예상 금액(원)</th><th class='l'>근거</th><th class='l'>할 일</th></tr>%s</table>"
             % "".join("<tr><td class='l'>%s</td><td>%s</td><td>%s</td><td class='l'>%s</td><td class='l'>%s</td></tr>"
                       % (esc(n), tag[s], W(v) if v else "–", esc(why), esc(todo)) for n, s, v, why, todo in T["rows"]))
    h.append("<div class='note'>조세특례제한법 간이 계산 (2025년 창업 당시 기준). 창업 감면과 고용 공제는 함께 받을 수 있지만 "
             "창업 감면과 중소기업 특별감면은 한 해에 하나만 됩니다. 실제 적용 여부·금액은 세무사 확인이 필요합니다.</div>")
    return "".join(h)
