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
import re

from .surplus import FOUNDED
from .util import open_text as _open_text  # UTF-8·CP949 모두 읽음 (C5)

MIN_TAX = 0.07          # 중소기업 최저한세율 (과세표준의 7%)
LOCAL_RATE = 0.10       # 법인지방소득세도 같은 비율로 줄어든다
SME_START_YEARS = 5     # 창업중소기업 감면: 창업 후 처음 소득 난 해부터 5년
# 통합고용 공제액·창업 감면율·최저한세율은 taxlaw.py 연도별 기준표에서 읽는다 (사용자 2026-11-12)

# 통합고용세액공제 개편 (조특법 29조의8, 2025-12-23 개정, 2026-12-31이 속하는 과세연도부터 — 2026-11-17 법령 조문 확인).
# 중소기업 1명당: (직전 해 대비, 전전 해 대비, 전전전 해 대비) 증가 인원 × 금액. 2024년 이전 시작 연도와는 비교 안 함.
# 2025년에 늘어난 인원은 부칙 34조대로 옛 규정(3년 같은 금액)을 2027년까지 계속 (사용자 2026-11-17 카드: 공개 자료 금액으로 계산)
NEW_HIRE_YEAR = 2026
NEW_HIRE_FIRST_BASE = 2025
TIERS_2026 = {("수도권", True): (7_000_000, 16_000_000, 17_000_000), ("지방", True): (10_000_000, 19_000_000, 20_000_000),
              ("수도권", False): (4_000_000, 9_000_000, 10_000_000), ("지방", False): (7_000_000, 12_000_000, 13_000_000)}


def W(v):
    return "{:,}".format(int(round(v)))


def _read_csv(path):
    if not os.path.exists(path):
        return []
    with _open_text(path) as f:
        return list(csv.DictReader(f))


def corp_base(input_dir, year):
    """세금예상.csv 법인세 줄 -> (과세표준, 산출세액, 근거) 또는 None."""
    for r in _read_csv(os.path.join(input_dir, "세금예상.csv")):
        # 과세표준이 있는 그해 계산 줄만 (작년분 신고서·중간예납 줄은 과세표준이 비어 있음, 2026-11-14 F5)
        if (r.get("세목") or "").strip() == "법인세" and str(year) in (r.get("대상기간") or "") and (r.get("과세표준") or "").strip():
            try:
                return int(float(r.get("과세표준") or 0)), int(float(r.get("산출세액") or 0)), (r.get("대상기간") or "").strip()
            except ValueError:
                return None
    return None


def _staff_info(input_dir):
    """사원.csv(위하고 인사 자료) -> ({임원 이름}, {이름: 생년월일}). 없으면 빈 값."""
    import datetime as dt
    officers, birth = set(), {}
    for r in _read_csv(os.path.join(input_dir, "사원.csv")):
        n = (r.get("사원명") or "").strip()
        if not n:
            continue
        if (r.get("임원") or "").strip() in ("예", "Y", "y", "1", "임원"):
            officers.add(n)
        try:
            birth[n] = dt.date.fromisoformat((r.get("생년월일") or "").strip()[:10])
        except ValueError:
            pass
    return officers, birth


def young_or_old(birth, year):
    """청년(15~34세)·60세 이상이면 True (통합고용 우대 대상, 장애인·경력단절은 사원 정보로 몰라 세무사 확인)."""
    age = year - birth.year
    return 15 <= age <= 34 or age >= 60


def pay_months(input_dir):
    """달마다 급여 받은 사람 -> ({연월: {이름}}, {연도: 자료 이름}).
    장부 사원급여.csv 를 먼저 쓰고, 거기 없는 해는 위하고 급여 화면(급여명세.csv '지급합계')으로 채운다
    (2026-11-17: 사원급여.csv 는 올해 장부만이라 작년 인원을 몰라 고용 공제를 못 셈 → 위하고 2025 급여 화면이 있음)."""
    per, src = collections.defaultdict(set), {}
    for r in _read_csv(os.path.join(input_dir, "사원급여.csv")):
        ym, name = (r.get("연월") or "").strip(), (r.get("사원명") or "").strip()
        if len(ym) >= 7 and name:
            per[ym[:7]].add(name)
            src[int(ym[:4])] = "장부 사원급여"
    have = set(src)
    for r in _read_csv(os.path.join(input_dir, "급여명세.csv")):
        ym, name = (r.get("연월") or "").strip(), (r.get("사원명") or "").strip()
        if len(ym) >= 7 and name and (r.get("구분") or "").strip() == "지급" and ym[:4].isdigit() and int(ym[:4]) not in have:
            per[ym[:7]].add(name)
            src[int(ym[:4])] = "위하고 급여 화면"
    return per, src


def pay_amounts(input_dir):
    """위하고 급여 화면(급여명세.csv) -> {(연월, 이름): 지급합계}. 1인당 임금 비교용."""
    out = {}
    for r in _read_csv(os.path.join(input_dir, "급여명세.csv")):
        if (r.get("구분") or "").strip() == "지급" and (r.get("항목") or "").strip() == "지급합계":
            try:
                out[((r.get("연월") or "").strip()[:7], (r.get("사원명") or "").strip())] = float(r.get("금액") or 0)
            except ValueError:
                pass
    return out


def headcount(input_dir, exclude=(), young=False):
    """사원급여.csv(없는 해는 위하고 급여명세.csv) -> {연도: (월평균 인원, 급여 나간 달 수)}. 주주(대표·가족)·임원(사원.csv)은
    상시근로자가 아니라 뺀다. 대표만 급여를 받은 달도 0명인 달로 평균에 넣는다 (법: 매월 말 인원 합 ÷ 과세연도 달 수).
    young=True 면 사원.csv 생년월일로 청년·60세 이상만 센다 (생년월일 모르는 사원은 안 셈)."""
    officers, birth = _staff_info(input_dir)
    ex = set(n.strip() for n in exclude if n) | officers
    per, _ = pay_months(input_dir)
    years = collections.defaultdict(list)
    for ym, names in per.items():
        y = int(ym[:4])
        n = [x for x in names if x not in ex and (not young or (x in birth and young_or_old(birth[x], y)))]
        years[y].append(len(n))
    return dict((y, (sum(v) / float(len(v)), len(v))) for y, v in years.items())


def _tier_incs(cnt, Y):
    """{연도: 인원} -> (직전 대비, 전전 대비, 전전전 대비) 증가 인원 (조특법 29조의8 개정: 음수는 0, 2024년 이전 시작 연도는 빼고 0)."""
    def c(y):
        return cnt.get(y) if y >= NEW_HIRE_FIRST_BASE else None
    out, low = [], c(Y)
    for k in (1, 2, 3):
        base = c(Y - k)
        if low is None or base is None:
            out.append(0.0)
        else:
            out.append(max(low - base, 0.0))
            low = min(low, base)
    return out


def _hire_2026(input_dir, holders, year, zone, hc, law):
    """2026년부터의 통합고용세액공제 -> 후보 줄 (이름, 상태, 금액, 근거, 할 일).
    새 규정(직전·전전·전전전 해 대비 증가, 청년 등과 그 외 금액 다름) + 2025년 늘어난 인원의 옛 규정 이어받기(부칙 34조)."""
    cur = hc.get(year)
    total = dict((y, v[0]) for y, v in hc.items())
    if FOUNDED - 1 not in total:
        total[FOUNDED - 1] = 0.0   # 설립 전 해는 0명 (옛 규정 2025년 증가 계산용)
    _, births = _staff_info(input_dir)
    young = dict((y, v[0]) for y, v in headcount(input_dir, holders, young=True).items()) if births else {}
    other = dict((y, total[y] - young.get(y, 0.0)) for y in total)
    T = _tier_incs(total, year)
    Yi = [min(a, t) for a, t in zip(_tier_incs(young, year), T)] if births else [0.0, 0.0, 0.0]
    Oi = [min(a, max(t - y, 0.0)) for a, t, y in zip(_tier_incs(other, year), T, Yi)] if births else T
    ty, to = TIERS_2026[(zone, True)], TIERS_2026[(zone, False)]
    first_o, ok_o, why_o = law("고용공제_" + zone)            # 1년차 금액은 창 '세법 기준 확인'에서 고칠 수 있음
    first_y, ok_y, _ = law("고용공제_%s청년" % zone)
    to = ((first_o if ok_o and first_o else to[0]),) + to[1:]
    ty = ((first_y if ok_y and first_y else ty[0]),) + ty[1:]
    new_amt = int(sum(n * v for n, v in zip(Yi, ty)) + sum(n * v for n, v in zip(Oi, to)))
    parts = ["%s %.1f명×%s" % (lab, n, W(v)) for lab, ns, vs in (("청년 등", Yi, ty), ("그 외", Oi, to))
             for n, v, lab in zip(ns, vs, (lab + " 직전 해 대비", lab + " 전전 해 대비", lab + " 전전전 해 대비")) if n > 0]
    # 옛 규정: 2025년(이하)에 늘어난 인원, 늘어난 해부터 3년 (인원 유지 시) — 부칙 34조
    old_amt, old_txt = 0, ""
    for y in range(max(year - 2, FOUNDED), min(year, NEW_HIRE_YEAR)):
        c, p = hc.get(y), (hc.get(y - 1) if y - 1 >= FOUNDED else (0.0, 12))
        if c and p is not None and c[0] > p[0] and cur and cur[0] >= c[0] - 1e-9:
            per, ok, _ = law_old(input_dir, zone)
            if per:
                old_amt += int((c[0] - p[0]) * per)
                old_txt = " · %d년 늘어난 %.1f명은 옛 규정 1명당 %s원 (부칙 34조, %d년까지)" % (y, c[0] - p[0], W(per), y + 2)
    amt = new_amt + old_amt
    why = "월평균 직원(주주 뺌) %d년 %.1f명%s. 새 규정(조특법 29조의8, 2025-12-23 개정): %s%s%s" % (
        year, cur[0], " (%d달만 있음)" % cur[1] if cur[1] < 12 else "",
        " + ".join(parts) if parts else "늘어난 인원 없음", old_txt,
        "" if births else " · 사원 생년월일이 없어 모두 '그 외' 금액으로 셈 (청년 등은 더 큼)")
    if amt <= 0:
        return ("통합고용세액공제", "해당 없음", None, why, "직원이 늘면 1명당 공제 (3년)")
    return ("통합고용세액공제", "해당" if cur[1] >= 12 else "확인 필요", amt, why,
            "임원·주주 가족·단시간 근로자는 빼고 세무사가 다시 셈")


def law_old(input_dir, zone):
    """옛 규정(2025년) 1명당 금액 (청년 외) -> (값, 확인, 설명)."""
    from . import taxlaw
    return taxlaw.value(input_dir, NEW_HIRE_FIRST_BASE, "고용공제_" + zone)


def assets_by_year(journal):
    """장부 신호 -> {연도: (장비·비품 산 금액, 연구개발비)}. 변환 때 잉여금.csv 에 같이 적는다."""
    out = collections.defaultdict(lambda: [0, 0])
    for ln in journal or []:
        d = ln.get("date")
        if d is None:
            continue
        code, name = str(ln.get("account_code") or ""), str(ln.get("account") or "")
        dr = ln.get("debit") or 0
        # 11/17 전수 점검 F5: 차량운반구(208, 승용차 볼보 1.24억)와 감가상각누계액(처분 때 차변)이 통합투자 '확인 필요'로 잡히던 것.
        # 통합투자세액공제 사업용 자산 범위(조특법 24조 위임 시행규칙)에 차량·운반구는 운수업 등만 들어감 → 빼고, 누계액 줄도 뺌
        if "누계" in name or code[:3] == "208" or "차량" in name:
            pass
        elif code[:3] in ("206", "207", "209", "210", "212", "213") or any(w in name for w in ("기계장치", "비품", "공구", "시설장치")):
            out[d.year][0] += dr
        if "연구" in name and "개발" in name:
            out[d.year][1] += dr
    return dict((y, tuple(v)) for y, v in out.items())


def check(input_dir, year, answers, holders=(), assets=None):
    """assets = (장비 산 금액, 연구개발비) 또는 None(장부 신호 모름).
    -> {year, rows:[(이름, 상태, 예상 금액|None, 근거, 할 일)], total(해당만, 최저한세 반영), local, base, tax, note}."""
    a = answers or {}
    from . import taxlaw   # 연도별 세법 기준 (미확인 값을 쓰는 후보는 '확인 필요', 합계에 안 넣음)

    def law(key):
        return taxlaw.value(input_dir, year, key)
    cb = corp_base(input_dir, year)
    base, tax, period = cb if cb else (None, None, "")
    rows = []
    young, dense, metro = a.get("청년창업"), a.get("과밀억제"), a.get("수도권")
    # 1) 창업중소기업 세액감면 (조특법 6조)
    rate, rate_ok = None, True
    if dense in ("예", "아니오") and young in ("예", "아니오"):
        key = {("아니오", "예"): "창업감면_과밀밖청년", ("아니오", "아니오"): "창업감면_과밀밖", ("예", "예"): "창업감면_과밀안청년"}.get((dense, young))
        if key:
            rate, rate_ok, _ = taxlaw.value(input_dir, FOUNDED, key)   # 창업한 해 규정
        else:
            rate = 0.0
    last = FOUNDED + SME_START_YEARS - 1
    from . import taxreturn
    filed = taxreturn.load(input_dir).get((year - 1, "확정"))   # 실제 신고서 (사용자 2026-11-13)
    sp_filed = filed.get("특별감면") if filed else None
    if year > last:
        rows.append(("창업중소기업 세액감면", "해당 없음", None, "감면 기간(%d~%d년)이 지남" % (FOUNDED, last), ""))
    elif sp_filed:
        rows.append(("창업중소기업 세액감면", "해당 없음", None,
                     "%d년 신고서에서 창업 감면이 아니라 중소기업 특별세액감면을 받음 (둘은 한 해에 하나만)" % (year - 1), ""))
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
        elif unk or not rate_ok:
            rows.append(("창업중소기업 세액감면", "확인 필요", amt, why,
                         "세무사에게 '행사 대행 등 우리 업종이 창업 감면 업종인지, 새 창업으로 보는지' 확인"))
        else:
            rows.append(("창업중소기업 세액감면", "해당", amt, why + " · 법인세 산출세액 × 감면율", "법인세 신고 때 세액감면신청서 제출"))
    # 2) 중소기업 특별세액감면 (조특법 7조) — 창업 감면과 같은 해 함께 못 받음
    st1 = rows[0][1]
    if sp_filed:
        sp_rate = sp_filed / float(filed.get("산출세액") or 1)
        rows.append(("중소기업 특별세액감면", "해당", int(tax * sp_rate) if tax is not None else None,
                     "%d년 신고서 실제 감면 %s원 = 산출세액의 %.1f%% (감면율 × 감면 대상 소득 비율). 올해도 같은 비율"
                     % (year - 1, W(sp_filed), sp_rate * 100), "법인세 신고 때 세액감면신청서 제출 (세무사)"))
    else:
        rows.append(("중소기업 특별세액감면", "나중" if st1 in ("해당", "확인 필요") else "확인 필요", None,
                     "창업 감면과 한 해에 같이 받지 못함 — 창업 감면이 안 되는 해의 대안. 감면율은 업종·회사 크기·지역에 따라 5~30%",
                     "창업 감면이 안 되면 세무사에게 업종·소기업 여부 확인"))
    if filed and filed.get("공제이월"):
        rows.append(("통합고용세액공제 (넘어온 몫)", "해당", filed["공제이월"],
                     "%d년 공제 중 최저한세 때문에 못 쓰고 넘어온 금액 (10년 안에 사용)" % (year - 1),
                     "법인세 신고 때 세액공제조정명세서에 이월분으로 (세무사)"))
    # 3) 통합고용세액공제 (조특법 29조의8) — 상시근로자 증가 1명당, 3년간
    hc = headcount(input_dir, holders)
    zone = "수도권" if metro == "예" else ("지방" if metro == "아니오" else None)
    per_other, hire_ok, hire_why = law("고용공제_" + zone) if zone else (None, False, "")
    per_young = law("고용공제_%s청년" % zone)[0] if zone else None
    cur = hc.get(year)
    prev = hc.get(year - 1) if year - 1 >= FOUNDED else (0.0, 12)
    if cur is None:
        rows.append(("통합고용세액공제", "확인 필요", None, "%d년 급여 자료 없음" % year, ""))
    elif prev is None:
        rows.append(("통합고용세액공제", "확인 필요", None,
                     "%d년 월평균 직원 %.1f명 (주주 뺌, %d달). %d년 인원을 몰라 늘어난 인원을 아직 못 셈" % (year, cur[0], cur[1], year - 1),
                     "%d년 분개장이 들어오면 자동 계산" % (year - 1)))
    elif year >= NEW_HIRE_YEAR and zone:
        rows.append(_hire_2026(input_dir, holders, year, zone, hc, law))
    else:
        inc = []
        for y in range(max(year - 2, FOUNDED), year + 1):   # 공제는 늘어난 해부터 3년 (인원 유지 시)
            c, p = hc.get(y), (hc.get(y - 1) if y - 1 >= FOUNDED else (0.0, 12))
            if c and p is not None and c[0] > p[0] and cur[0] >= c[0] - 1e-9:
                inc.append((y, c[0] - p[0]))
        n = sum(v for _, v in inc)
        amt = int(n * per_other) if per_other and n > 0 else (0 if n <= 0 else None)
        _, births = _staff_info(input_dir)
        ny = 0.0
        if births and amt and per_young:   # 사원.csv 가 있으면 청년·60세 이상 증가분은 우대 금액으로
            hy = headcount(input_dir, holders, young=True)
            for y, v in inc:
                c, p = (hy.get(y) or (0.0, 0))[0], (hy.get(y - 1) or (0.0, 0))[0] if y - 1 >= FOUNDED else 0.0
                ny += min(max(c - p, 0.0), v)
            amt = int(ny * per_young + (n - ny) * per_other)
        why = "월평균 직원(주주 뺌) %d년 %.1f명 ← %d년 %.1f명%s. %s" % (
            year, cur[0], year - 1, prev[0], " (%d달만 있음)" % cur[1] if cur[1] < 12 else "",
            " · ".join("%d년 +%.1f명" % (y, v) for y, v in inc) if inc else "늘어난 인원 없음")
        if n <= 0:
            rows.append(("통합고용세액공제", "해당 없음", None, why, "직원이 늘면 1명당 공제 (3년)"))
        elif not hire_ok:
            rows.append(("통합고용세액공제", "확인 필요", None, why + " · 1명당 금액: " + hire_why,
                         "세법 기준 확인 화면에서 %d년 1명당 금액(세무사 확인)을 넣으면 계산" % year))
        else:
            rows.append(("통합고용세액공제", "해당" if cur[1] >= 12 else "확인 필요", amt,
                         why + (" · 청년·60세 이상 늘어난 %.1f명은 1명당 %s원, 나머지 %s원 (사원 생년월일 기준)" % (ny, W(per_young), W(per_other))
                                if births and per_young and n > 0 else
                                " × 1명당 %s원 (청년·60세 이상 등은 %s원으로 더 큼)" % (W(per_other), W(per_young) if per_young else "더 큼")),
                         "임원·주주 가족·단시간 근로자는 빼고 세무사가 다시 셈"))
    # 4) 작년(2025)분 놓친 감면·공제 — 5년 안 경정청구
    if filed and taxreturn.at_min_tax(filed, law("최저한세율")[0] or MIN_TAX):   # 실제 신고서 (사용자 2026-11-13)
        rows.append(("%d년분 경정청구" % (year - 1), "해당 없음", None,
                     "%d년 신고서: 공제·감면 %s원을 받아 세금이 이미 최저한세(과세표준의 7%%)까지 줄었음 — 더 돌려받을 감면 없음"
                     % (year - 1, W(filed["공제감면세액"])), "최저한세와 상관없는 공제(중소기업 연구개발비 등)만 세무사와 확인"))
    elif year - 1 >= FOUNDED:
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
    if a.get("연구전담") == "예" and a.get("연구공제") == "안 받음":   # 사용자 2026-11-17: 대표만 소속, 나중 문제 소지로 2025·2026 안 받음
        rows.append(("연구·인력개발비 세액공제", "해당 없음", None,
                     "연구전담부서는 있지만 회사가 공제를 받지 않기로 함 (설정 '연구공제: 안 받음' — 부서에 대표만 소속, 나중 문제 소지)",
                     "직원 연구원이 생기면 다시 검토"))
    elif a.get("연구전담") == "예":
        rd_filed = filed is not None and not ((filed.get("공제감면세액") or 0) - (filed.get("특별감면") or 0) - (filed.get("고용공제") or 0))
        rows.append(("연구·인력개발비 세액공제", "확인 필요", int(rd * 0.25) if rd else None,
                     "연구소·전담부서 있음(설정 답). 중소기업은 연구개발비(연구 전담 직원 인건비 등)의 25%%, 최저한세에 안 걸려 바로 세금이 줄어듦%s%s" % (
                         " — 장부 연구개발비 %s원" % W(rd) if rd else " — 장부에 연구개발비 계정이 없어 금액 못 셈 (연구 전담 직원 급여를 따로 나눈 계정 없음)",
                         " · %d년 신고서의 공제·감면은 특별감면+고용 공제뿐이라 연구개발 공제는 받지 않았음" % (year - 1) if rd_filed else ""),
                     "세무사에게 연구 전담 직원 인건비 공제(%d년분은 경정청구) 검토 요청" % (year - 1)))
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
    # 29조의4: ①·⑤(평균임금 증가)는 직전 3년 평균임금 증가율을 계산할 수 있어야 함 — 창업으로 못 하면 적용 안 함 (시행령 26조의4 ⑫).
    # 2025년 창업이면 2029년부터 계산되는데 법 기한은 2028년 → ③ 정규직 전환분만 남음 (2026-11-17 조문 확인)
    rows.append(("근로소득을 늘린 기업 세액공제", "해당 없음" if FOUNDED + 4 > 2028 else "나중", None,
                 "평균임금 증가분 공제는 직전 3년 평균임금 증가율이 있어야 하는데 %d년 창업이라 %d년부터 계산됨 (법 기한 2028년, 시행령 26조의4 ⑫). "
                 "남는 길: 계약직·단시간 직원을 정규직으로 바꾸면 그 사람 임금 증가분의 20%% (직원 수가 줄지 않을 때)" % (FOUNDED, FOUNDED + 4),
                 "계약직을 정규직으로 바꿀 때 세무사에게 알림"))
    if a.get("벤처") == "예":
        rows.append(("벤처기업 관련 감면", "확인 필요", None, "벤처 확인을 받았으면 창업 감면 기간·감면율이 달라질 수 있음", "세무사 확인"))
    rows += review_more(input_dir, year, a, filed, holders)
    # 근거 조문 칸 + 받은 조문의 법 기한이 지났으면 '해당 없음' (사용자 2026-11-17)
    items, out = _law_items(input_dir), []
    for r in rows:
        cell, end, _ = law_cell(r[0], items, year)
        if end and end < year and r[1] != "해당 없음":
            r = (r[0], "해당 없음", None, "법 기한(%d년)이 지남 · " % end + r[3], "")
        ok, why_ = chosen(a, r[0], r[1], r[2])
        pk = ("넣음 · " + why_) if ok else (("안 넣음 · " + why_) if why_ else "")
        out.append(tuple(r[:5]) + (cell, pk))
    rows = out
    total = sum(r[2] for r in rows if r[1] == "해당" and r[2])
    note = ""
    if base is not None and tax is not None and total:
        floor = int(base * (law("최저한세율")[0] or MIN_TAX))
        cap = max(tax - floor, 0)
        full_start = rows[0][1] == "해당" and rate == 1.0
        if total > cap and not full_start:
            note = "최저한세(과세표준의 7%% = %s원) 때문에 줄일 수 있는 세금은 %s원까지" % (W(floor), W(cap))
            total = cap
        total = min(total, tax)
    credit = None
    if base is not None and tax is not None:   # '받음'인 공제를 넣은 법인세 계산과 이월 (사용자 2026-11-17)
        ex = [{"name": r[0], "amount": int(r[2]), "mt": _pick_of(r[0])[2], "nong": _pick_of(r[0])[3]}
              for r in rows if len(r) > 6 and r[6].startswith("넣음")]
        try:
            credit = taxreturn.credits(input_dir, year, base, tax, extra=ex)
        except Exception:
            credit = None
    # 체크 전이라도 후보마다 '받으면' 금액을 모두 계산 (사용자 2026-11-17: 법령·회사 기준 계산은 전부 해 두고, 세금엔 체크한 것만)
    calc = {}
    for r in rows:
        calc[r[0]] = _calc_cell(input_dir, year, base, tax, r)
    rows = [tuple(r) + (calc[r[0]],) for r in rows]
    try:   # 최신 법령 확인 상태 (사용자 2026-11-17: 법령 관련 항목은 최신 법령을 먼저 확인하고 만든다)
        from . import lawwatch
        law_state = lawwatch.state(input_dir)
    except Exception:
        law_state = None
    carry = (filed or {}).get("공제이월") or 0
    mt_note = ("%d년 신고 때 최저한세 때문에 못 쓴 공제 %s원이 넘어와 있음 → '최저한세 적용' 공제는 새로 생겨도 올해 세금이 바로 줄지 않고 "
               "다음 해로 넘어갈 가능성이 큼. 바로 줄어드는 것은 '최저한세 안 걸림'(중소기업 연구·인력개발비)뿐" % (year - 1, W(carry))) if carry else ""
    return {"year": year, "rows": rows, "total": total, "mt_note": mt_note, "law_state": law_state, "credit": credit, "local": int(total * LOCAL_RATE), "base": base, "tax": tax,
            "period": period, "note": note}


# ───────────── 후보를 법인세 계산에 넣기 (사용자 2026-11-17 첫 번째 안: '받음' 표시한 것만 계산, 세액공제 남는 몫은 이월) ─────────────
# 후보 이름 앞부분 -> (설정 키, 최저한세 적용, 농어촌특별세 냄, 금액 근거 종류)
# 최저한세: 조특법 132조 ①3호 (10조는 중소기업이 아닌 자만). 농특세 비과세: 농특세법 시행령 4조 ⑦1호(조특법 10조·30조의3) — 2026-11-17 조문 확인
# 금액 근거: 'law' = 법령 금액 × 회사 자료로 계산됨, 'advisor' = 세무사가 인정 범위를 봐야 함
PICK = [
    ("통합고용세액공제", "반영_고용", True, True, "law"),
    ("인력개발비(교육훈련비)", "반영_교육훈련", False, False, "advisor"),
    ("통합투자세액공제", "반영_투자", True, True, "advisor"),
    ("연구·인력개발비", "반영_연구", False, False, "advisor"),
]


def _pick_of(name):
    for p in PICK:
        if name.startswith(p[0]) and not name.startswith("통합고용세액공제 (넘어온"):
            return p
    return None


def chosen(a, name, status, amount):
    """후보 하나를 계산에 넣나 -> (넣음 True/False, 이유 글)."""
    p = _pick_of(name)
    if not p or not amount or status in ("해당 없음", "나중"):
        return False, ""
    own = (a or {}).get(p[1]) or "기본"
    if own == "받음":
        return True, "설정 '받음'"
    if own == "안 받음":
        return False, "설정 '안 받음'"
    rule = (a or {}).get("반영기본") or "모두 안 받음"   # 사용자 2026-11-17: 자동으로 넣지 말고 경영관리가 확인·체크('받음')한 것만
    if rule == "모두 받음":
        return True, "기본 규칙 '모두 받음'"
    if rule == "모두 안 받음":
        return False, "기본 규칙 '모두 안 받음'"
    return (True, "기본: 법령 금액으로 계산됨") if p[4] == "law" else (False, "기본: 세무사 인정 범위 확인 전")


PICK_LABEL = {"반영_특별감면": "중소기업 특별세액감면 (작년 신고서 비율)", "반영_이월공제": "작년에서 넘어온 세액공제",
              "반영_고용": "올해 통합고용 세액공제", "반영_교육훈련": "교육훈련비 세액공제",
              "반영_투자": "통합투자 세액공제", "반영_연구": "연구·인력개발비 세액공제"}


def pick_states(a):
    """창 '법인세 감면·공제' 상태: 항목마다 법인세 예상에 넣나 -> [(이름, 넣음, 이유)] (사용자 2026-11-17: 어디서 무엇이 체크됐는지 한눈에)."""
    from . import taxreturn
    a = a or {}
    out = []
    for k in ("반영_특별감면", "반영_이월공제"):
        v = a.get(k) or "기본"
        on = (taxreturn.LAST_DEFAULT if v == "기본" else v) == "받음"
        out.append((PICK_LABEL[k], on, "직접 고름" if v != "기본" else "기본: 작년 신고서대로 넣음"))
    rule = a.get("반영기본") or "모두 안 받음"
    for name, k, _, _, kind in PICK:
        own = a.get(k) or "기본"
        if own in ("받음", "안 받음"):
            out.append((PICK_LABEL[k], own == "받음", "직접 고름"))
        elif rule == "모두 받음":
            out.append((PICK_LABEL[k], True, "기본 규칙 '모두 받음'"))
        elif rule == "계산된 것만" and kind == "law":
            out.append((PICK_LABEL[k], True, "기본 규칙 '계산된 것만' (금액을 셀 수 있을 때)"))
        else:
            out.append((PICK_LABEL[k], False, "기본 규칙 '%s'" % rule))
    return out


NO_CALC = [   # 금액을 못 셀 때 없는 자료 (사용자 2026-11-17: 계산 못 하는 후보는 무슨 자료가 없어서인지)
    ("상생결제", "은행 상생결제로 준 금액 자료 없음 (상생결제를 쓰면 은행 이용 내역서)"),
    ("상생협력 출연금", "출연한 금액 없음"),
    ("성과공유", "성과공유기업 확인서·경영성과급 지급액 없음"),
    ("연구·인력개발비", "연구 전담 직원 인건비를 따로 나눈 자료 없음"),
    ("통합투자", "올해 장부에 새로 산 사업용 장비 금액 없음"),
    ("통합고용세액공제", "올해·작년 급여 자료(직원 수)가 모자람"),
    ("고용유지", "두 해 급여 화면(위하고 급여명세) 없음"),
    ("전자신고", "직접 신고하면 2만원 — 신고 방법이 정해지지 않음"),
]


def _calc_cell(input_dir, year, base, tax, r):
    """후보 한 줄 -> '받으면' 계산 글: 올해 줄어드는 세금·이월 몫, 이미 들어간 것, 못 센 이유."""
    name, st, amt = r[0], r[1], r[2]
    if name.startswith("중소기업 특별세액감면") and st == "해당" or name.startswith("통합고용세액공제 (넘어온"):
        from . import taxreturn
        sp_, cr_ = taxreturn.last_year_taken(input_dir)
        on = sp_ if name.startswith("중소기업") else cr_
        return ("작년 신고서 기준으로 법인세 예상에 넣음 (설정으로 끌 수 있음)" if on else
                "설정 '안 받음' — 법인세 예상에 안 넣음 (%s원)" % W(amt or 0))
    if not amt:
        if st == "해당 없음":
            return "해당 없음 — 계산 안 함"
        if st == "나중" and not any(name.startswith(k) for k, _ in NO_CALC):
            return "지금 조건이 안 돼 계산 안 함"
        why = next((w for k, w in NO_CALC if name.startswith(k)), "금액을 셀 자료 없음")
        return "계산 못 함: " + why
    p = _pick_of(name)
    if not p:
        return "%s원 (법인세 예상 계산 방식에 없는 항목 — 세무사 확인)" % W(amt)
    if base is None or tax is None:
        return "%s원 · 올해 법인세 예상이 없어 올해 쓸 몫을 못 나눔" % W(amt)
    from . import taxreturn
    try:
        C = taxreturn.credits(input_dir, year, base, tax, extra=[{"name": name, "amount": int(amt), "mt": p[2], "nong": p[3]}])
    except Exception:
        C = None
    if not C or not C.get("extra"):
        return "%s원 · 작년 신고서가 없어 올해 쓸 몫을 못 나눔" % W(amt)
    x = C["extra"][0]
    nong = int(x["used"] * 0.2) if p[3] else 0
    return "받으면: 공제 %s원 → 올해 법인세 %s원 줄어듦%s · %s원은 이월 (%d년까지)%s" % (
        W(amt), W(x["used"]), " (농어촌특별세 %s원 더 냄)" % W(nong) if nong else "", W(x["carry"]), year + 10,
        "" if p[2] else " · 최저한세와 상관없음")


def picked(input_dir, year, answers=None, holders=None, assets=None):
    """'받음'인 세액공제 -> [{name, amount, mt(최저한세), nong(농특세)}]. 법인세 예상(taxreturn.credits)이 쓴다."""
    from . import dividend
    try:
        a = answers if answers is not None else dividend.read_settings(input_dir)
        hd = holders if holders is not None else [r["이름"] for r in dividend.read(input_dir)]
    except (OSError, ValueError):
        return []
    if assets is None:
        for r in _read_csv(os.path.join(input_dir, "잉여금.csv")):
            if (r.get("연도") or "") == str(year) and (r.get("항목") or "") in ("장비구입",):
                try:
                    assets = (int(float(r.get("금액") or 0)), 0)
                except ValueError:
                    pass
    T = check(input_dir, year, a, hd, assets)
    out = []
    for r in T["rows"]:
        ok, _ = chosen(a, r[0], r[1], r[2])
        if ok:
            p = _pick_of(r[0])
            out.append({"name": r[0], "amount": int(r[2]), "mt": p[2], "nong": p[3]})
    return out


# ───────────── 감면·공제 전체 검토 (사용자 2026-11-17: 법인세 감면·공제를 모두 최신 법령 기준으로 찾아 적용할 게 있는지 검토) ─────────────
# 세금 계산에는 넣지 않고 보여 주기만 (11/17 카드 ③). 조문은 '개정 확인 받기'(lawwatch)가 받아 두고, 받은 글에서 법 기한을 다시 읽는다.
# 후보 이름 -> (법령, 조, 의, 최저한세 적용 여부, 받은 글이 없을 때 쓰는 법 기한(해) 또는 None)
# 최저한세: 조특법 132조 ①3·4호 (2026-11-17 조문 확인). 중소기업 연구·인력개발비 공제(10조)만 최저한세 밖.
LAWS = {
    "창업중소기업 세액감면": ("조세특례제한법", 6, 0, True, None),
    "중소기업 특별세액감면": ("조세특례제한법", 7, 0, True, None),
    "통합고용세액공제": ("조세특례제한법", 29, 8, True, None),
    "연구·인력개발비 세액공제": ("조세특례제한법", 10, 0, False, 2029),
    "인력개발비(교육훈련비) 세액공제": ("조세특례제한법", 10, 0, False, 2029),
    "통합투자세액공제": ("조세특례제한법", 24, 0, True, None),
    "근로소득을 늘린 기업 세액공제": ("조세특례제한법", 29, 4, True, 2028),
    "상생결제 지급금액 세액공제": ("조세특례제한법", 7, 4, True, 2028),
    "상생협력 출연금 세액공제": ("조세특례제한법", 8, 3, True, 2028),
    "성과공유 중소기업 경영성과급 세액공제": ("조세특례제한법", 19, 0, True, 2027),
    "영상콘텐츠 제작비용 세액공제": ("조세특례제한법", 25, 6, True, 2028),
    "고용을 늘린 기업 세액공제(옛)": ("조세특례제한법", 29, 7, True, 2024),
    "중소기업 사회보험료 세액공제": ("조세특례제한법", 30, 4, True, 2024),
    "고용유지중소기업 세액공제": ("조세특례제한법", 30, 3, True, 2026),
    "전자신고 세액공제": ("조세특례제한법", 104, 8, True, None),
    "외국납부세액공제": ("법인세법", 57, 0, False, None),
    "재해손실세액공제": ("법인세법", 58, 0, False, None),
}
_END_RE = re.compile(r"(20\d\d)년 12월 31일(?:이 속하는 과세연도)?까지")


def law_tag(name, n, sub):
    return "%s %d조%s" % (name, n, "의%d" % sub if sub else "")


def _law_items(input_dir):
    try:
        from . import lawwatch
        return lawwatch.load(input_dir).get("items", {})
    except (OSError, ValueError):
        return {}


def law_cell(name, items, year):
    """후보 -> (조문 칸 글, 법 기한 해 또는 None, 받은 조문 있음). 받은 조문 글에서 'YYYY년 12월 31일(이 속하는 과세연도)까지'를 읽는다."""
    if name not in LAWS:
        return "", None, False
    law, n, sub, mt, end0 = LAWS[name]
    tag = law_tag(law, n, sub)
    short = tag.replace("조세특례제한법", "조특법")
    it = items.get(tag)
    end = end0
    got = bool(it and it.get("text"))
    if got:
        ys = [int(y) for y in _END_RE.findall(it["text"][:1500])]
        end = max(ys) if ys else end0   # 첫 항의 기한 (여러 개면 가장 늦은 해)
    parts = [short]
    if got:
        sd = str(it.get("시행일자") or "")
        parts.append("시행 %s-%s-%s" % (sd[:4], sd[4:6], sd[6:8]) if len(sd) == 8 else "시행일 모름")
        parts.append("조문 받음 %s" % (it.get("seen") or "")[:10])
        if it.get("changed"):
            parts.append("개정 %s 알림" % it["changed"][:10])
    else:
        parts.append("조문 아직 안 받음 (창 '개정 확인 받기')")
    if end:
        parts.append("법 기한 %d년%s" % (end, " — 지남" if end < year else ""))
    parts.append("최저한세 적용" if mt else "최저한세 안 걸림")
    return " · ".join(parts), end, got


def _acct_sum(input_dir, year, words):
    """계정별비용.csv(장부 비용, 달·계정) 에서 그해 계정과목 이름에 words 중 하나가 든 비용 합 -> (합, [계정들]) 또는 (None, [])."""
    rows = _read_csv(os.path.join(input_dir, "계정별비용.csv"))
    if not rows:
        return None, []
    tot, names = 0, set()
    for r in rows:
        nm = (r.get("계정과목") or "")
        if (r.get("연월") or "")[:4] == str(year) and any(w in nm for w in words):
            try:
                tot += int(float(r.get("금액") or 0))
                names.add(nm)
            except ValueError:
                pass
    return tot, sorted(names)


def _stay_pay(input_dir, year, ex):
    """두 해 모두 급여를 받은 직원(주주·임원 뺌)의 1인당 월평균 지급액 -> (전년, 올해, 인원) 또는 None.
    고용유지 공제 요건은 그해 새로 들어온 사람을 빼고 견준다 (조특법 30조의3 ①1·3호) — 새 직원이 많으면 평균이 내려가 보이는 것을 막음."""
    amt = pay_amounts(input_dir)
    officers, _ = _staff_info(input_dir)
    ex = set(ex) | officers
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for (ym, name), v in amt.items():
        if name and name not in ex and ym[:4] in (str(year - 1), str(year)):
            by[name][int(ym[:4])].append(v)
    both = [n for n, d in by.items() if d.get(year - 1) and d.get(year)]
    if not both:
        return None
    def med(v):
        v = sorted(v)
        return v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2.0
    # 사람마다 '보통 달' 급여(가운데 값)로 견준다: 연말 상여·첫 달 정산이 한 해에만 있어 평균이 흔들리는 것을 막음 (2026-11-17 실제 자료: 12월 상여)
    avg = lambda y: sum(med(by[n][y]) for n in both) / float(len(both))
    return avg(year - 1), avg(year), len(both)


def review_more(input_dir, year, a, filed, holders=()):
    """기존 후보(창업·특별감면·고용·연구·투자·근로소득) 밖의 감면·공제 후보 줄들. 세금 계산·합계에는 넣지 않는다 ('해당' 안 씀)."""
    rows = []
    # 연구·인력개발비 중 인력개발비: 교육훈련비 계정 (중소기업 25%, 최저한세 안 걸림)
    edu, names = _acct_sum(input_dir, year, ("교육훈련",))
    if edu:
        rows.append(("인력개발비(교육훈련비) 세액공제", "확인 필요", int(edu * 0.25),
                     "장부 %s %s원 × 중소기업 25%%. 연구소가 없어도 되는 공제지만, 인정되는 교육(위탁훈련·직업능력개발훈련 등 시행령 별표 6)만 됨"
                     % ("·".join(names), W(edu)),
                     "세무사에게 교육훈련비 중 인력개발비로 인정되는 몫 확인 (최저한세와 상관없이 바로 세금이 줄어듦)"))
    elif edu == 0:
        rows.append(("인력개발비(교육훈련비) 세액공제", "나중", None,
                     "%d년 장부에 교육훈련비 없음. 직원 위탁훈련·직업능력개발훈련 비용의 25%%를 공제 (최저한세 안 걸림)" % year,
                     "직원 교육을 보내면 교육훈련비 계정으로 처리"))
    rows.append(("상생결제 지급금액 세액공제", "나중", None,
                 "중소·중견기업 거래처 대금을 은행 '상생결제'로 15일·30일·60일 안에 주면 지급액의 일정 비율 (법인세의 10% 한도). "
                 "장부로는 결제 방식을 알 수 없어 일반 통장 이체로 봄", "큰 거래처 대금을 상생결제로 주는 방법을 거래 은행에 물어볼 수 있음"))
    don, dn = _acct_sum(input_dir, year, ("기부",))
    rows.append(("상생협력 출연금 세액공제", "나중", None,
                 "기술보증기금·신용보증기금·대중소기업농어업협력재단 등에 상생협력 출연을 하면 출연금의 10%%. %s" %
                 ("장부 기부금 %s원 — 출연처가 위 기관이면 해당" % W(don) if don else "장부에 그런 출연(기부금) 없음"),
                 "출연 계획이 없으면 할 일 없음"))
    bonus, bn = _acct_sum(input_dir, year, ("상여",))
    # 2차 전수조사 V9 (2026-11-18): 웹 자료 다수는 15%라 하지만 국가법령정보에서 받은 조특법 19조 ①(시행 2026-09-18) 원문은
    # '경영성과급의 100분의 10' — 조문 원문대로 10% 유지
    rows.append(("성과공유 중소기업 경영성과급 세액공제", "나중", None,
                 "중소벤처기업부 '성과공유 중소기업' 확인을 받고 경영성과급을 주면 그 10%% (직원 수가 줄지 않을 때, 2027년까지). %s"
                 % ("장부 상여금 %s원은 성과공유 확인 전이라 해당 없음으로 봄" % W(bonus) if bonus else "장부에 상여금 계정 없음"),
                 "연말 성과급을 줄 계획이면 성과공유기업 확인(중소벤처기업부)을 먼저 받는지 세무사와 검토"))
    rows.append(("영상콘텐츠 제작비용 세액공제", "해당 없음", None,
                 "방송사 방송 프로그램·영화·등급분류 받은 OTT 영상의 제작비만 됨 (중소기업 15%+추가 15%). 행사 영상·홍보 영상 제작은 대상이 아님으로 봄", ""))
    rows.append(("고용을 늘린 기업 세액공제(옛)", "해당 없음", None,
                 "2024년까지 늘어난 인원만 대상 (지금은 통합고용세액공제로 바뀜). 회사가 %d년에 세워져 해당 없음" % FOUNDED, ""))
    rows.append(("중소기업 사회보험료 세액공제", "해당 없음", None,
                 "2024년까지 늘어난 인원만 대상 (통합고용세액공제로 바뀜). 회사가 %d년에 세워져 해당 없음" % FOUNDED, ""))
    # 고용유지: 1인당 연간 임금이 줄었는데(근무시간 나눔) 시간당 임금·인원은 유지한 경우 — 2026년까지
    sp = _stay_pay(input_dir, year, holders)
    if sp is None:
        rows.append(("고용유지중소기업 세액공제", "확인 필요", None,
                     "1인당 임금을 견줄 %d·%d년 위하고 급여 화면이 없음" % (year - 1, year), "위하고 '결산·인사급여 모두 받기'로 급여 화면을 받으면 자동 판단"))
    elif sp[1] >= sp[0]:
        rows.append(("고용유지중소기업 세액공제", "해당 없음", None,
                     "두 해 모두 일한 직원 %d명(주주·임원 뺌)의 1인당 보통 달 급여(상여 뺀 가운데 값) %d년 %s원 ≥ %d년 %s원 (위하고 급여 화면). 임금을 줄여 고용을 지킨 회사만 대상"
                     % (sp[2], year, W(sp[1]), year - 1, W(sp[0])), ""))
    else:
        rows.append(("고용유지중소기업 세액공제", "확인 필요", None,
                     "두 해 모두 일한 직원 %d명의 1인당 보통 달 급여(상여 뺀 가운데 값) %d년 %s원 < %d년 %s원. 근무시간을 줄여 고용을 지킨 경우라면 대상일 수 있음 (시간당 임금은 줄면 안 됨)"
                     % (sp[2], year, W(sp[1]), year - 1, W(sp[0])), "세무사에게 고용유지 공제 요건(시간당 임금·인원 유지) 확인"))
    by_agent = bool(filed and "외부" in str(filed.get("조정") or ""))
    rows.append(("전자신고 세액공제", "해당 없음" if by_agent else "확인 필요", None,
                 ("%d년 법인세를 세무법인이 대신 신고 — 이 공제(2만원)는 회사가 직접 전자신고할 때만 됨" % (year - 1)) if by_agent
                 else "회사가 직접 홈택스로 법인세를 신고하면 2만원", ""))
    fx, _ = _acct_sum(input_dir, year, ("외국",))
    rows.append(("외국납부세액공제", "해당 없음" if not fx else "확인 필요", None,
                 "외국에서 번 돈에 외국 세금을 낸 경우만" + ("" if not fx else " — 장부에 외국 관련 비용 %s원" % W(fx)), ""))
    rows.append(("재해손실세액공제", "해당 없음", None, "화재·홍수 등 재해로 사업용 자산의 20% 이상을 잃은 경우만. 그런 기록 없음", ""))
    return rows


# 쉬운 설명 (사용자 2026-11-17: 각 감면·공제 종류와 조건을 일반인도 알기 쉬운 말로) — 후보 이름 앞부분 -> (무엇인가, 받는 조건)
EASY = [
    ("창업중소기업 세액감면", "새로 차린 작은 회사의 법인세를 5년 동안 깎아 줌 (지역·대표 나이에 따라 50~100%)",
     "완전히 새로 시작한 사업 · 정해진 업종 · 서울 등 과밀지역 밖이거나 대표가 만 34세 이하. 특별세액감면과 한 해에 하나만"),
    ("중소기업 특별세액감면", "작은 회사가 번 돈에 붙는 법인세를 일정 비율(5~30%) 깎아 줌",
     "중소기업 · 정해진 업종 · 회사 크기와 지역에 따라 비율이 다름. 창업 감면과 한 해에 하나만"),
    ("통합고용세액공제 (넘어온", "작년에 받을 수 있었지만 세금이 너무 적어 못 쓴 고용 공제를 올해 이후에 씀",
     "10년 안에 쓰면 됨 · 올해도 최저한세까지만 쓸 수 있음"),
    ("통합고용세액공제", "직원 수가 늘면 늘어난 1명마다 법인세를 정해진 금액만큼 깎아 줌 (청년·60세 이상은 더 큼)",
     "1년 평균 직원 수가 전년보다 늘어야 함 · 대표·주주 가족·임원·단시간 근로자는 안 셈 · 다음 해에 줄면 토해 냄"),
    ("%d년분 경정청구", "지난 신고 때 놓친 감면·공제를 5년 안에 다시 신청해 세금을 돌려받는 것", "놓친 감면이 있어야 함 · 최저한세에 걸렸으면 돌려받을 게 거의 없음"),
    ("연구·인력개발비", "연구 전담 직원 인건비 등 연구에 쓴 돈의 25%를 법인세에서 빼 줌 (작은 회사는 최저한세와 상관없이 바로 줄어듦)",
     "기업부설연구소나 연구전담부서 인정서가 있어야 함 · 연구만 하는 직원의 인건비여야 함 (지분 많은 대표 등은 빠짐)"),
    ("인력개발비(교육훈련비)", "직원 교육에 쓴 돈의 25%를 법인세에서 빼 줌 (최저한세와 상관없음)",
     "정해진 교육기관에 맡긴 훈련·직업능력개발훈련 등 인정되는 교육만 · 연구소가 없어도 됨"),
    ("통합투자세액공제", "사업에 쓰는 기계·장비를 사면 산 값의 10%(작은 회사)를 법인세에서 빼 줌",
     "새 사업용 자산이어야 함 · 승용차·건물·중고품·임대용은 안 됨 · 산 해에 공제"),
    ("근로소득을 늘린", "직원 평균 월급을 다른 회사보다 많이 올리면 더 올린 몫의 20%를 깎아 줌",
     "직원 수가 줄지 않아야 함 · 최근 3년 월급 인상률 기록이 있어야 함 (새 회사는 안 됨) · 계약직을 정규직으로 바꾼 경우는 따로 가능"),
    ("상생결제", "작은 거래처에 대금을 은행 '상생결제'로 빨리 주면 준 금액의 일부를 깎아 줌",
     "은행 상생결제 제도로 주어야 함 · 어음 결제 비율이 늘지 않아야 함 · 법인세의 10%까지"),
    ("상생협력 출연금", "작은 협력회사를 돕는 기금(보증기금·협력재단 등)에 돈을 내면 낸 돈의 10%를 깎아 줌",
     "법에 정한 기관에 '상생협력' 목적으로 내야 함 · 특수관계 회사 지원용이면 안 됨"),
    ("성과공유 중소기업", "직원에게 회사 성과를 나누는 성과급을 주면 그 10%를 깎아 줌 (직원도 소득세 절반 감면)",
     "중소벤처기업부 '성과공유 중소기업' 확인 · 미리 정한 성과급 제도로 지급 · 직원 수가 줄지 않아야 함"),
    ("영상콘텐츠", "방송·영화·OTT 영상을 만든 비용의 15%(작은 회사, 조건 맞으면 +15%)를 깎아 줌",
     "방송사에서 방송된 프로그램, 영화, 등급 받은 OTT 영상만 · 행사·홍보 영상은 안 됨"),
    ("고용을 늘린 기업", "예전(2024년까지) 직원을 늘린 회사에 주던 공제 — 지금은 통합고용세액공제로 바뀜", "2024년까지 늘어난 인원만"),
    ("중소기업 사회보험료", "예전(2024년까지) 늘어난 직원의 4대보험 회사 부담분을 깎아 주던 공제 — 지금은 통합고용세액공제로 바뀜", "2024년까지 늘어난 인원만"),
    ("고용유지중소기업", "경기가 어려워 해고 대신 근무시간·월급을 나눠 줄인 회사에 주는 공제",
     "직원 1인당 연봉은 줄었지만 시간당 임금과 직원 수는 유지 · 2026년까지"),
    ("전자신고", "회사가 직접 홈택스로 법인세를 신고하면 2만원을 깎아 줌", "세무사가 대신 신고하면 회사는 못 받음"),
    ("외국납부", "외국에서 번 돈에 외국 세금을 이미 냈으면 그만큼 한국 법인세에서 빼 줌 (이중 과세 방지)", "외국에서 세금을 낸 증빙이 있어야 함"),
    ("재해손실", "화재·홍수 등으로 회사 재산을 크게 잃으면 법인세를 그 비율만큼 깎아 줌", "사업용 자산의 20% 이상을 잃어야 함"),
    ("벤처기업", "벤처 확인을 받으면 창업 감면 기간·비율이 달라질 수 있음", "벤처기업 확인서가 있어야 함"),
]


def easy(name, year=None):
    """후보 이름 -> (무엇인가, 받는 조건) 또는 None."""
    for key, what, cond in EASY:
        k = key % (year - 1) if "%d" in key and year else key
        if name.startswith(k):
            return what, cond
    return None


# 필요한 자료·신청 방법 (사용자 2026-11-17: 공제·감면에 필요한 자료와 조건, 신청 방법도 같이 보이게) — 이름 앞부분 -> (필요한 자료, 신청 방법)
# 신청은 모두 법인세 신고(다음 해 3월 31일까지) 때 신고서에 붙여 내는 방식. 기한 뒤에는 5년 안에 경정청구로 받을 수 있음 (국세기본법 45조의2)
HOW = [
    ("창업중소기업 세액감면", "사업자등록증·법인등기부(설립일), 대표 나이 증빙, 업종이 감면 업종인지 세무사 확인",
     "법인세 신고 때 '세액감면신청서'를 함께 냄 (세무사가 작성)"),
    ("중소기업 특별세액감면", "중소기업 기준 확인(매출·자산), 업종별 매출 구분, 본점·사업장 소재지",
     "법인세 신고 때 '세액감면신청서'를 함께 냄"),
    ("통합고용세액공제 (넘어온", "작년 '세액공제조정명세서'(이월 금액)", "법인세 신고 때 세액공제조정명세서에 이월분으로 적음"),
    ("통합고용세액공제", "매달 말 직원 명단(원천징수이행상황신고서·4대보험 가입 명단), 직원 생년월일(청년·60세 이상), 임원·주주 가족 명단",
     "법인세 신고 때 '세액공제신청서'와 '상시근로자 수 계산서'를 냄"),
    ("%d년분 경정청구", "작년 법인세 신고서, 놓친 공제·감면의 증빙", "법정 신고기한 뒤 5년 안에 홈택스 '경정청구'로 신청 (세무사 대행)"),
    ("연구·인력개발비", "연구소·전담부서 인정서(한국산업기술진흥협회), 연구원 명단·근무 기록, 연구노트, 연구 인건비 지급 내역",
     "법인세 신고 때 '세액공제신청서'와 '연구 및 인력개발비 명세서'를 냄"),
    ("인력개발비(교육훈련비)", "교육 기관·과정 안내, 수료증, 교육비 영수증·세금계산서, 교육받은 직원 명단",
     "법인세 신고 때 '세액공제신청서'와 '연구 및 인력개발비 명세서'를 냄"),
    ("통합투자세액공제", "자산을 산 세금계산서, 고정자산대장, 사업용으로 쓰는 증빙", "법인세 신고 때 '세액공제신청서'를 냄 (투자한 해)"),
    ("근로소득을 늘린", "직원별 연간 급여(원천징수부), 최근 3년 평균 급여, 정규직 전환 근로계약서", "법인세 신고 때 '세액공제신청서'와 증대 명세서를 냄"),
    ("상생결제", "은행 상생결제 이용 내역서, 거래처가 중소·중견기업인지 확인", "법인세 신고 때 '세액공제신청서'와 상생결제 지급명세서를 냄"),
    ("상생협력 출연금", "출연 영수증(기관 발행), 출연 목적 증빙", "법인세 신고 때 '세액공제신청서'를 냄"),
    ("성과공유 중소기업", "중소벤처기업부 성과공유기업 확인서, 성과급 지급 규정·지급 내역", "법인세 신고 때 '세액공제신청서'를 냄 (직원 소득세 감면은 연말정산 때)"),
    ("영상콘텐츠", "방송·상영 확인서, 제작비 명세(국내·국외 구분)", "처음 방송·상영한 해의 법인세 신고 때 '세액공제신청서'를 냄"),
    ("고용을 늘린 기업", "(지금은 신청 대상 아님)", "–"),
    ("중소기업 사회보험료", "(지금은 신청 대상 아님)", "–"),
    ("고용유지중소기업", "직원별 근로시간·시간당 임금·연간 임금 비교표(2년)", "법인세 신고 때 '세액공제신청서'를 냄"),
    ("전자신고", "–", "회사가 홈택스로 직접 신고하면 자동으로 빠짐"),
    ("외국납부", "외국 세금 납부 영수증·원천징수 증명서", "법인세 신고 때 '외국납부세액공제 신청서'를 냄"),
    ("재해손실", "재해 확인서(소방서·지자체), 잃은 자산 목록과 장부 금액", "재해가 난 날부터 3개월 안에 '재해손실세액공제신청서'를 세무서에 냄"),
    ("벤처기업", "벤처기업 확인서", "창업 감면 신청 때 함께 냄"),
]


def how(name, year=None):
    """후보 이름 -> (필요한 자료, 신청 방법) 또는 None."""
    for key, need, apply_ in HOW:
        k = key % (year - 1) if "%d" in key and year else key
        if name.startswith(k):
            return need, apply_
    return None


def _easy_html(name, year, esc):
    e = easy(name, year)
    if not e:
        return ""
    hw = how(name, year)
    return ("<div style='font-size:11px;color:#555;margin-top:3px'><b>무엇:</b> %s<br><b>받는 조건:</b> %s%s</div>" % (
        esc(e[0]), esc(e[1]), ("<br><b>필요한 자료:</b> %s<br><b>신청 방법:</b> %s" % (esc(hw[0]), esc(hw[1]))) if hw else ""))


def render(T, esc):
    if not T:
        return ""
    tag = {"해당": "<span class='tag'>해당</span>", "확인 필요": "<span class='tag e'>확인 필요</span>",
           "해당 없음": "<span class='tag' style='opacity:.5'>해당 없음</span>", "나중": "<span class='tag' style='opacity:.7'>나중</span>"}
    h = ["<div class='q'>법인세를 줄일 수 있는 감면·공제 전체 검토 (%d년)</div>" % T["year"]]
    ls = T.get("law_state")
    if ls:
        h.append("<div class='%s'>%s</div>" % ("note" if ls.get("ok") else "warn", esc(ls["msg"])))
    C = T.get("credit")
    if T["tax"] is not None:
        h.append("<div class='say'>%s 법인세 산출세액 %s원 (과세표준 %s원).</div>" % (esc(T["period"]), W(T["tax"]), W(T["base"])))
    ins = [r for r in T["rows"] if len(r) > 6 and r[6].startswith("넣음")]
    if ins:
        h.append("<div class='say'>법인세 예상에 넣은 공제: %s.%s</div>" % (esc(" · ".join("%s %s원" % (r[0], W(r[2])) for r in ins)), (
            " 최저한세 때문에 올해 %s원만 쓰고 나머지는 이월" % W(C["new_used"]) if C and C.get("new_used") is not None and C["new_used"] < sum(r[2] for r in ins) else "")))
    else:
        h.append("<div class='say'>법인세 예상에 넣은 새 공제는 없습니다 (작년 신고서의 특별감면·넘어온 고용 공제는 원래대로 넣음).</div>")
    if C and C.get("carries"):
        h.append("<div class='say'>%s</div>" % esc("내년으로 넘어갈 공제 %s원: %s. 기한 안에 못 쓰면 없어집니다 (조특법 144조: 세액공제만 10년 이월, 감면은 이월 없음)." % (
            W(C["carry_next"]), " · ".join("%s %s원 (%d년분, %d년까지 사용)" % (c["what"], W(c["amount"]), c["from"], c["until"]) for c in C["carries"]))))
    if T.get("mt_note"):
        h.append("<div class='say'>%s</div>" % esc(T["mt_note"]))
    cnt = dict((k, sum(1 for r in T["rows"] if r[1] == k)) for k in tag)
    h.append("<div class='note'>%s</div>" % esc("후보 %d개: %s" % (len(T["rows"]), " · ".join("%s %d" % (k, v) for k, v in cnt.items() if v))))
    order = {"해당": 0, "확인 필요": 1, "나중": 2, "해당 없음": 3}
    rows = sorted(T["rows"], key=lambda r: order.get(r[1], 9))
    h.append("<table class='re'><tr><th class='l'>감면·공제 (쉬운 설명 · 필요한 자료 · 신청 방법)</th><th>판단</th><th>예상 금액(원)</th><th class='l'>법령·회사 기준 계산 (받으면)</th><th>세금 계산</th>"
             "<th class='l'>우리 회사 확인 (요건·자료)</th><th class='l'>근거 조문</th><th class='l'>할 일</th></tr>%s</table>"
             % "".join("<tr><td class='l'>%s</td><td>%s</td><td>%s</td><td class='l'>%s</td><td>%s</td><td class='l'>%s</td><td class='l'>%s</td><td class='l'>%s</td></tr>"
                       % (esc(r[0]) + _easy_html(r[0], T["year"], esc), tag[r[1]], W(r[2]) if r[2] else "–", esc(r[7] if len(r) > 7 else ""),
                          esc(r[6] if len(r) > 6 and r[6] else "–"),
                          esc(r[3]), esc(r[5] if len(r) > 5 else ""), esc(r[4]))
                       for r in rows))
    h.append("<div class='note'>조세특례제한법·법인세법 최신 조문 기준 (받은 조문의 시행일·법 기한을 표에 씀, 기한이 지난 것은 자동으로 '해당 없음'). "
             "계산은 체크와 상관없이 모두 해 두고, '세금 계산'이 '넣음'(경영관리가 확인하고 '받음'으로 체크)인 공제만 법인세 예상에 들어갑니다 (기본은 모두 안 넣음): 넘어온 공제 → 올해 공제(최저한세까지) → 최저한세 밖 공제 순서로 쓰고, 못 쓴 몫은 이월. "
             "넣을지는 대표보고 창 왼쪽 목록 '법인세 감면·공제' → '감면·공제 고르기 열기'(기본 규칙·항목별 받음/안 받음)에서 바꾸고, 보고를 다시 만들면 반영됩니다. "
             "창업 감면과 중소기업 특별감면은 한 해에 하나만 됩니다. 실제 적용 여부·금액은 세무사 확인이 필요합니다.</div>")
    return "".join(h)
