"""내년 예산 (사용자 2026-11-10: 목업 승인 후 '이 방식으로 프로그램에 넣어').

올해 장부·인트라넷 자료로 초안을 자동으로 만들고, 사람이 정하는 값(노란 칸)만 창에서 넣는다.
- 입력/예산값.csv  연도,구분,대상,값   구분 = 성장률(%)·늘릴인원(명)·입사월(1~12)·급여인상률(%)·물가인상률(%)
  성장률·늘릴인원·입사월은 대상 = 팀 이름, 급여인상률·물가인상률은 대상 = 회사 전체.
- 목표 수익률은 팀 목표(입력/팀목표.csv, 창 '팀 목표')의 그 해 값. 없으면 1 − 예산_원가율(기본 70%) (추정 예산과 같은 기준).
- 입력/예산확정.csv  예산을 확정하면 달별 숫자를 남긴다. 월간 보고의 '예산 대비'가 읽는다.

계산 (목업 mockups/예산 과 같음):
- 매출 = 팀별 올해 매출 × (1 + 성장률). 올해 매출 = 장부(손익.csv 팀 줄) 실적 달 + 남은 달은 그 달 행사 프로젝트 사전견적(예상).
- 달별 = 지난 해들 달별 매출 비중 평균 (증빙월별 → 없으면 손익 회사 줄). 내년 행사로 이미 받은 일(사전견적)보다 작지 않게.
- 매출원가 = 매출 × (1 − 목표 수익률). 급여 = 지금 1달 급여 × (1 + 인상률) + 늘릴 인원 × 1인 평균 × (1 + 인상률) (입사 월부터).
- 그 밖의 판관비 = 계정별 올해 실적(1년으로 늘림) × 기준(인원·물가·그대로). 감가상각비 = 올해 예상(직접 입력 또는 작년 장부).
- 영업외 수익 = 이자수익만 (지원금 등은 확정 전이라 넣지 않음). 영업외 비용 = 올해 실적을 1년으로 늘림.
- 자금: 매출 입금은 올해 계산서 평균 회수 기간, 매입 지급은 행사 달 40%·다음 달 60%. 부가세·법인세 일정 = 세금예상(있으면) + 예산 숫자.
"""
import csv
import datetime as dt
import os
import re
from collections import OrderedDict

from .calc import year_revenue_left
from .corptax import corp_tax, depreciation

VALUES_FILE = "예산값.csv"
VALUES_COLUMNS = ["연도", "구분", "대상", "값"]
CONFIRM_FILE = "예산확정.csv"
CONFIRM_COLUMNS = ["연도", "월", "대상", "매출", "매출총이익", "급여", "판관비", "감가상각비", "영업외수익", "영업외비용", "확정일"]
COMPANY = "회사 전체"
TEAM_KINDS = ("성장률", "늘릴인원", "입사월")
CO_KINDS = ("급여인상률", "물가인상률")
KINDS = TEAM_KINDS + CO_KINDS
HEAD_ACCOUNTS = ("복리후생비", "여비교통비", "통신비", "교육훈련비", "도서인쇄비")   # 인원에 비례
FLAT_ACCOUNTS = ("임차료", "보험료", "리스료")                                     # 계약 금액 그대로
SALARY_WORDS = ("급여", "상여", "퇴직", "임금", "제수당")
AP_SPLIT = (0.4, 0.6)       # 매입 지급: 행사 달, 다음 달
DEFAULT_COST = 0.70
COLLECT_DAYS = 60       # 매출 입금: 계산서 작성일 뒤 약 60일 (사용자 2026-11-12)
MIN_COLLECT_N = 10      # 입금된 계산서가 이만큼 넘어야 장부 평균 수금 기간을 쓴다
# 예산 숫자(매입·급여·판관비·세금·영업외)에 없는 정해진 지급: 자금일정·자금계획서에서 그대로 가져온다 (G2)
FIXED_WORDS = ("원금", "상환", "보증금", "설비", "이전", "대여", "투자", "자산")
FIXED_SKIP = ("이자", "급여", "보험", "세금", "카드", "임차료", "구독")
VAT = 0.10
LOCAL = 0.10


# ───────────── 사람이 정하는 값 ─────────────
def _num(text):
    t = str(text if text is not None else "").replace(",", "").replace("%", "").replace("원", "").replace("명", "").replace("월", "").strip()
    if t.startswith("+"):
        t = t[1:]
    try:
        return float(t)
    except ValueError:
        return None


def read_values(input_dir):
    """-> {(연도, 구분, 대상): 숫자}. 없거나 읽지 못하면 {}."""
    path = os.path.join(input_dir, VALUES_FILE)
    out = {}
    if not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                y, k, who = (r.get("연도") or "").strip(), (r.get("구분") or "").strip(), (r.get("대상") or "").strip()
                v = _num(r.get("값"))
                if y.isdigit() and k in KINDS and v is not None:
                    out[(y, k, who or COMPANY)] = v
    except (OSError, UnicodeDecodeError, csv.Error):
        return {}
    return out


def _check(kind, v):
    if kind == "성장률" and not -100 < v <= 500:
        raise ValueError("성장률은 −100 ~ 500 사이 % (예: 10)")
    if kind in CO_KINDS and not -50 <= v <= 100:
        raise ValueError("%s은 −50 ~ 100 사이 %% (예: 5)" % ("급여 인상률" if kind == "급여인상률" else "물가 인상률"))
    if kind == "늘릴인원" and (v != int(v) or not -50 <= v <= 50):
        raise ValueError("늘릴 인원은 정수 (줄이면 음수, 예: 1)")
    if kind == "입사월" and (v != int(v) or not 1 <= v <= 12):
        raise ValueError("입사 월은 1~12")


def save_values(input_dir, year, items):
    """items = [(구분, 대상, 값 글자)]. 값이 비면 그 줄을 지운다. -> 그 해 저장된 줄 수."""
    y = str(year or "").strip()
    if not (y.isdigit() and len(y) == 4):
        raise ValueError("연도는 4자리 (예: 2027)")
    if not os.path.isdir(input_dir):
        raise ValueError("입력 폴더가 없습니다: %s" % input_dir)
    cur = read_values(input_dir)
    for kind, who, text in items:
        if kind not in KINDS:
            raise ValueError("모르는 구분: %s" % kind)
        who = (who or "").strip() or COMPANY
        if kind in TEAM_KINDS and who == COMPANY:
            raise ValueError("팀을 고르세요 (예: 기획1팀)")
        if str(text or "").strip() == "":
            cur.pop((y, kind, who), None)
            continue
        v = _num(text)
        if v is None:
            raise ValueError("숫자로 넣으세요: %s" % text)
        _check(kind, v)
        cur[(y, kind, who)] = v
    path = os.path.join(input_dir, VALUES_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(VALUES_COLUMNS)
        for (yy, k, who), v in sorted(cur.items(), key=lambda kv: (kv[0][0], KINDS.index(kv[0][1]), kv[0][2])):
            w.writerow([yy, k, who, "%g" % v])
    os.replace(tmp, path)
    return sum(1 for (yy, _, _) in cur if yy == y)


def values_text(input_dir, year):
    """창에 보일 저장된 값 한 줄."""
    V = read_values(input_dir)
    y = str(year)
    teams = sorted(set(w for (yy, k, w) in V if yy == y and k in TEAM_KINDS))
    parts = []
    for t in teams:
        g, n, m = V.get((y, "성장률", t)), V.get((y, "늘릴인원", t)), V.get((y, "입사월", t))
        s = "%s %s" % (t, "성장 %+g%%" % g if g is not None else "성장 입력 전")
        if n:
            s += " · %+d명%s" % (n, " %d월" % m if m else "")
        parts.append(s)
    for k, lab in (("급여인상률", "급여 인상"), ("물가인상률", "물가")):
        v = V.get((y, k, COMPANY))
        parts.append("%s %s" % (lab, "%+g%%" % v if v is not None else "입력 전"))
    return "%s년: %s" % (y, " / ".join(parts))


# ───────────── 계산 ─────────────
def _r4(v):
    return int(round(v / 10000.0)) * 10000


def _event(text):
    from .calc import _event_date
    return _event_date(text)


def _ym(y, m):
    return "%04d-%02d" % (y, m)


def _spread(total, floor, seas):
    """계절 비중대로 나누되 floor(이미 받은 일)보다 작지 않게, 나머지 달을 비율대로 줄여 합계를 맞춘다."""
    fixed = [False] * 12
    a = [0.0] * 12
    for _ in range(13):
        rest = total - sum(floor[i] for i in range(12) if fixed[i])
        w = sum(seas[i] for i in range(12) if not fixed[i])
        a = [floor[i] if fixed[i] else (rest * seas[i] / w if w > 0 else 0) for i in range(12)]
        bad = [i for i in range(12) if not fixed[i] and a[i] < floor[i]]
        if not bad:
            break
        for i in bad:
            fixed[i] = True
    a = [_r4(v) for v in a]
    if any(a):
        k = max(range(12), key=lambda i: (not fixed[i], a[i]))
        a[k] += total - sum(a)
    return a


def _seasonality(d, base, base_months=None):
    """지난 해들 달별 매출 비중 평균. 올해(base)는 base_months(실적 + 남은 달 예상)를 쓴다. -> (비중 12개, 설명)."""
    years = OrderedDict()
    ev = getattr(d, "evid_month", None) or {}
    src = "증빙 작성일자 기준 달별 매출"
    for ym, (rev, _) in ev.items():
        if re.match(r"^\d{4}-\d{2}$", ym or "") and rev is not None and int(ym[:4]) < base:
            years.setdefault(int(ym[:4]), [0] * 12)[int(ym[5:7]) - 1] += rev
    if not years:
        src = "장부 손익 회사 줄"
        for p in d.pl:
            if p["unit"] == "회사" and p["revenue"] is not None and re.match(r"^\d{4}-\d{2}$", p["ym"] or "") and int(p["ym"][:4]) < base:
                years.setdefault(int(p["ym"][:4]), [0] * 12)[int(p["ym"][5:7]) - 1] += p["revenue"]
    if base_months and sum(base_months) > 0:
        years[base] = list(base_months)
        src = (src + " + " if len(years) > 1 else "") + "%d년 팀 매출(실적+예상)" % base
    shares, used = [], []
    for y, ms in sorted(years.items()):
        tot = sum(ms)
        if tot > 0 and sum(1 for v in ms if v) >= 6:
            shares.append([v / float(tot) for v in ms])
            used.append(y)
    if not shares:
        return [1 / 12.0] * 12, "자료 없음 — 12달 똑같이"
    avg = [sum(s[i] for s in shares) / len(shares) for i in range(12)]
    avg = [max(v, 0.01) for v in avg]
    t = sum(avg)
    return [v / t for v in avg], "%s, %s년 평균" % (src, "·".join(str(y) for y in used))


def _collect_days(d, base):
    """올해 계산서(발행) 발행일→입금일 평균 일수. 모르면 None."""
    days = [(i["paid_date"] - i["date"]).days for i in getattr(d, "invoices", [])
            if i.get("kind") == "발행" and i.get("date") and i.get("paid_date") and i["paid_date"] >= i["date"]
            and i["date"].year >= base - 1]
    return (sum(days) / float(len(days)), len(days)) if days else (None, 0)


def _salary_month(dept):
    """급여 기준 달 = 급여가 다 들어간 마지막 달 -> (연월, 바꿨으면 알림 글).

    급여 전표는 월말에 들어가므로 11~12월 중순에 예산을 만들면 가장 최근 달은 급여가 0이거나 일부 부서만 있다
    (2026-11-14 오후 점검 G1: 그 달을 기준으로 잡아 내년 급여 0원·인원 0명이 되던 것). 급여가 있는 부서 수가 그 해 가장
    많았던 달보다 적은 달은 '덜 들어간 달'로 보고 건너뛴다."""
    months = sorted(set(x["ym"] for x in dept))
    if not months:
        return None, ""
    paid = {m: sum(1 for x in dept if x["ym"] == m and (x["salary"] or 0) > 0) for m in months}
    full = max(paid.values())
    if not full:
        return months[-1], ""
    ok = [m for m in months if paid[m] >= full]
    pick = ok[-1]
    if pick != months[-1]:
        skip = [m for m in months if m > pick]
        return pick, "급여 기준 달을 %s로 잡음 — %s 급여 전표가 아직 다 들어가지 않음" % (pick, "·".join(skip))
    return pick, ""


def compute(d, values, year, asof, settings=None):
    """-> 예산 dict B. values = read_values(). year = 예산 연도(정수)."""
    year = int(year)
    base = year - 1
    y = str(year)
    S = settings or {}
    notes = []
    # 팀 목표 수익률
    tg = {t: v for (yy, t), v in (getattr(d, "team_targets", None) or {}).items() if yy == y}
    cost_rate = DEFAULT_COST
    try:
        cost_rate = float(str(S.get("예산_원가율", DEFAULT_COST)).strip() or DEFAULT_COST)
    except ValueError:
        pass
    # 올해 팀 실적 (손익.csv 팀 줄, WEHAGO 우선)
    srcs = sorted(set(p["source"] for p in d.pl), key=lambda x: (x != "WEHAGO", x))
    src = srcs[0] if srcs else None
    rows = [p for p in d.pl if p["source"] == src and p["unit"] == "팀" and p["ym"][:4] == str(base)
            and p["target"] and p["target"] != "팀 미지정"]
    last_m = max([int(p["ym"][5:7]) for p in rows] + [0])
    if asof.year == base:   # 끝난 달만 실적 (기준일이 그 달 말일이면 그 달까지), 남은 달은 예상
        done = asof.month if (asof + dt.timedelta(days=1)).month != asof.month else asof.month - 1
        last_m = min(last_m, done)
    all_rows = rows
    rows = [p for p in rows if int(p["ym"][5:7]) <= last_m]
    left_unknown = []
    teams = sorted(set(p["target"] for p in all_rows))
    # 내년에 행사가 있는 프로젝트의 팀도 넣는다
    got = []
    for p in d.projects.values():
        e = _event(p.get("event_date"))
        if e and e.year == year and p.get("estimate") and p.get("team") and p["team"] != "팀 미지정":
            got.append({"id": p["id"], "name": p["name"], "team": p["team"], "month": e.month, "estimate": p["estimate"]})
            if p["team"] not in teams:
                teams.append(p["team"])
    got.sort(key=lambda g: (g["team"], g["month"], g["id"]))
    T = OrderedDict()
    for t in teams:
        rv = [0] * 12
        gp = [0] * 12
        fc = [False] * 12
        # 장부에 잡힌 매출은 모두 (진행 중인 달에 이미 잡힌 것 포함 — 2026-11-14 오후 점검 G5: 예전엔 진행 중 달 매출을
        # 실적에서도 예상에서도 빼서 줄었음)
        for p in all_rows:
            if p["target"] == t:
                i = int(p["ym"][5:7]) - 1
                rv[i] += p["revenue"] or 0
                gp[i] += (p["revenue"] or 0) - (p["direct"] or 0)
                if i + 1 > last_m:
                    fc[i] = True
        # + 아직 매출로 안 잡힌 금액 (사전견적 − 매출반영누계, 대표 월간·팀장용과 같은 계산 calc.revenue_left).
        # 행사가 끝난 달이 이미 '실적 달'이면 다음 달(실적 달 바로 뒤)에 넣는다 (행사가 지났는데 아직 안 잡힌 매출도 빼지 않음)
        rr = ((getattr(d, "team_targets", None) or {}).get((str(base), t)) or {}).get("rate")
        for x in year_revenue_left(d.projects.values(), base, t):
            if not x["left"]:
                if x["left"] is None:
                    left_unknown.append(x["P"].get("id"))
                continue
            i = max(x["event"].month, min(last_m + 1, 12)) - 1
            rv[i] += x["left"]
            gp[i] += x["left"] * ((rr / 100.0) if rr is not None else (1 - cost_rate))
            fc[i] = True
        T[t] = {"rev26": rv, "gp26": [int(v) for v in gp], "fc": fc}
    if left_unknown:
        notes.append("%d년 행사 %d건은 장부 매출(매출반영누계)을 몰라 남은 매출을 넣지 못함: %s" % (base, len(left_unknown), ", ".join(sorted(left_unknown))))
    # 사람이 정하는 값
    def val(kind, who=COMPANY):
        return values.get((y, kind, who))
    seas, seas_src = _seasonality(d, base, [sum(T[t]["rev26"][i] for t in teams) for i in range(12)])
    got_m = {t: [0] * 12 for t in teams}
    for g in got:
        got_m[g["team"]][g["month"] - 1] += g["estimate"]
    for t in teams:
        R = T[t]
        g = val("성장률", t)
        R["growth"], R["growth_set"] = (g if g is not None else 0.0), g is not None
        rt = (tg.get(t) or {}).get("rate")
        R["rate"], R["rate_set"] = ((rt / 100.0) if rt is not None else (1 - cost_rate)), rt is not None
        R["base_rev"] = sum(R["rev26"])
        R["base_gp"] = sum(R["gp26"])
        R["budget"] = _r4(R["base_rev"] * (1 + R["growth"] / 100.0))
        R["got"] = got_m[t]
        R["got_sum"] = sum(got_m[t])
        if R["got_sum"] > R["budget"]:
            notes.append("%s: 이미 받은 일 %s가 매출 예산보다 커서 매출 예산을 받은 일 금액으로 올림" % (t, format(R["got_sum"], ",")))
            R["budget"] = R["got_sum"]
        R["rev"] = _spread(R["budget"], got_m[t], seas)
        R["gp"] = [_r4(v * R["rate"]) for v in R["rev"]]
        R["cogs"] = [R["rev"][i] - R["gp"][i] for i in range(12)]
    rev = [sum(T[t]["rev"][i] for t in teams) for i in range(12)]
    gp = [sum(T[t]["gp"][i] for t in teams) for i in range(12)]
    cogs = [rev[i] - gp[i] for i in range(12)]
    base_rev = sum(T[t]["base_rev"] for t in teams)
    base_gp = sum(T[t]["base_gp"] for t in teams)

    # 급여·인원 (부서비용.csv)
    dept = [x for x in (getattr(d, "dept", None) or []) if x["ym"][:4] == str(base)]
    last_ym, sal_note = _salary_month(dept)
    if sal_note:
        notes.append(sal_note)
    heads0 = OrderedDict()
    sal_last = None
    sal_base = None
    if last_ym:
        for x in dept:
            if x["ym"] == last_ym:
                heads0[x["dept"]] = int(x["heads"] or 0)
        sal_last = sum(x["salary"] or 0 for x in dept if x["ym"] == last_ym)
        used = [x for x in dept if x["ym"] <= last_ym]   # 급여 전표가 덜 들어간 뒤 달은 1년 환산에서도 뺀다
        n_m = len(set(x["ym"] for x in used))
        sal_base = int(sum(x["salary"] or 0 for x in used) * 12.0 / n_m)
    raise_ = val("급여인상률")
    infl = val("물가인상률")
    rz, fl = (raise_ or 0) / 100.0, (infl or 0) / 100.0
    h0 = sum(heads0.values())
    per = (sal_last / float(h0)) if sal_last is not None and h0 else None
    hires = OrderedDict()
    for t in teams:
        n = val("늘릴인원", t)
        m = val("입사월", t)
        if n:
            hires[t] = (int(n), int(m) if m else 1)
            heads0.setdefault(t, 0)
    heads = [h0 + sum(n for (n, m) in hires.values() if i + 1 >= m) for i in range(12)]
    if sal_last is None:
        sal = [None] * 12
        notes.append("부서비용(급여) 자료가 없어 급여 예산을 만들지 못함")
    else:
        sal = [_r4(sal_last * (1 + rz) + sum(n * per * (1 + rz) for (n, m) in hires.values() if i + 1 >= m and per)) for i in range(12)]
    havg = sum(heads) / 12.0

    # 그 밖의 판관비 (계정별비용.csv, 판매비와관리비 중 급여·감가상각비 뺀 것)
    acc = [a for a in (getattr(d, "accounts", None) or []) if a["ym"][:4] == str(base) and a["amount"] is not None]
    acc_months = sorted(set(a["ym"] for a in acc))
    n_acc = len(acc_months) or 1
    sal_codes = set(str(S.get("변환_급여계정", "80200")).replace(" ", "").split(",")) | {"80200"}
    sga = OrderedDict()
    nin_base = nout_base = 0
    interest_in = 0
    for a in acc:
        g, nm = a.get("group") or "", a.get("name") or ""
        if "판매비" in g or "관리비" in g:
            if a["code"] in sal_codes or "감가상각비" in nm:
                continue
            sga.setdefault(nm, 0)
            sga[nm] += a["amount"]
        elif "영업외수익" in g:
            nin_base += a["amount"]
            if "이자수익" in nm:
                interest_in += a["amount"]
        elif "영업외비용" in g:
            nout_base += a["amount"]
    k = 12.0 / n_acc
    SGA = []
    for nm, v in sorted(sga.items(), key=lambda kv: -kv[1]):
        yv = int(v * k)
        if any(w in nm for w in SALARY_WORDS) or any(w in nm for w in HEAD_ACCOUNTS):
            nv, how = yv * (havg / h0 if h0 else 1) * (1 + (rz if any(w in nm for w in SALARY_WORDS) else fl)), "인원 %d→평균 %.2f명 × %s" % (
                h0, havg, "급여 인상률" if any(w in nm for w in SALARY_WORDS) else "물가")
            basis = "인원"
        elif any(w in nm for w in FLAT_ACCOUNTS):
            nv, how, basis = yv, "계약 금액 그대로", "그대로"
        else:
            nv, how, basis = yv * (1 + fl), "물가", "물가"
        SGA.append({"name": nm, "base": yv, "budget": _r4(nv), "how": how, "basis": basis})
    sga_y = sum(x["budget"] for x in SGA)
    sga_base = sum(x["base"] for x in SGA)
    sga_m = [_r4(sga_y / 12.0)] * 12
    sga_m[11] += sga_y - sum(sga_m)
    # 감가상각비
    D = depreciation(getattr(d, "accounts", None), getattr(d, "dep_manual", None) or {}, "%s-12" % base)
    dep_y = D["annual"]
    dep_m = [None] * 12 if dep_y is None else [int(dep_y // 12)] * 12
    if dep_y is not None:
        dep_m[11] += dep_y - sum(dep_m)
    else:
        notes.append("감가상각비를 모름 — 창 '감가상각비'에 %d년 금액을 넣으면 들어감" % base)
    nin_y = int(interest_in * k)
    nout_y = int(nout_base * k)
    nin_base_y, nout_base_y = int(nin_base * k), int(nout_base * k)
    nin_m = [_r4(nin_y / 12.0)] * 12
    nout_m = [_r4(nout_y / 12.0)] * 12
    sal_y = None if sal[0] is None else sum(sal)
    known = sal_y is not None and dep_y is not None
    op_m = [None if not known else gp[i] - sal[i] - sga_m[i] - dep_m[i] for i in range(12)]
    Y = {"rev": sum(rev), "cogs": sum(cogs), "gp": sum(gp), "sal": sal_y, "dep": dep_y, "sga": sga_y,
         "nin": sum(nin_m), "nout": sum(nout_m)}
    Y["op"] = None if not known else Y["gp"] - Y["sal"] - Y["dep"] - Y["sga"]
    Y["pre"] = None if Y["op"] is None else Y["op"] + Y["nin"] - Y["nout"]
    ct = corp_tax(Y["pre"], year)
    Y["tax"] = None if ct is None else ct + int(ct * LOCAL)
    # 올해 (실적 + 예상)
    base_dep = D["annual"]
    L = {"rev": base_rev, "gp": base_gp, "cogs": base_rev - base_gp, "sal": sal_base, "dep": base_dep, "sga": sga_base,
         "nin": nin_base_y, "nout": nout_base_y}
    L["op"] = None if None in (sal_base, base_dep) else L["gp"] - L["sal"] - L["dep"] - L["sga"]
    L["pre"] = None if L["op"] is None else L["op"] + L["nin"] - L["nout"]
    lc = corp_tax(L["pre"], base)
    L["tax"] = None if lc is None else lc + int(lc * LOCAL)

    # ───── 자금 ─────
    bals = [b for b in getattr(d, "balances", []) if b.get("balance") is not None and b.get("date")]
    bal_date = max((b["date"] for b in bals), default=None)
    bal0 = sum(b["balance"] for b in bals if b["date"] == bal_date) if bal_date else None
    restricted = sum(b.get("restricted") or 0 for b in bals if b["date"] == bal_date) if bal_date else 0
    days, n_days = _collect_days(d, base)
    # 수금 기간: 회사 기준 작성일 뒤 약 60일 (사용자 2026-11-12). 입금된 계산서가 적으면 평균이 짧게 나와(못 받은 건은 빠짐)
    # 입금이 앞당겨 보이므로 MIN_COLLECT_N 건 넘을 때만 장부 평균을 쓴다 (2026-11-14 오후 점검 G7)
    days_used = days if (days is not None and n_days >= MIN_COLLECT_N) else COLLECT_DAYS
    lag = max(0.0, days_used / 30.0)
    l0 = int(lag)
    frac = lag - l0
    split = {l0: 1 - frac, l0 + 1: frac}
    # 올해 11~12월 등 남은 매출은 내년 초 입금 (올해 예상 매출)
    base_rev_m = [sum(T[t]["rev26"][i] for t in teams) for i in range(12)]
    base_gp_m = [sum(T[t]["gp26"][i] for t in teams) for i in range(12)]
    ext_rev = base_rev_m + rev
    cin = []
    for i in range(12):
        j = 12 + i
        cin.append(_r4((1 + VAT) * sum(w * ext_rev[j - l] for l, w in split.items() if j - l >= 0)))
    base_cogs_dec = base_rev_m[11] - base_gp_m[11]
    cpay = [_r4((1 + VAT) * (AP_SPLIT[0] * cogs[i] + AP_SPLIT[1] * (cogs[i - 1] if i else base_cogs_dec))) for i in range(12)]
    # 세금 일정
    FIX = []
    tax_m = [0] * 12
    taxrows = getattr(d, "tax", None) or []

    def add_tax(m, day, name, amt, how, srcname):
        if amt is None:
            return
        tax_m[m - 1] += amt
        FIX.append({"month": m, "day": day, "name": name, "amount": amt, "how": how, "src": srcname})
    # 올해 4분기 부가세·법인세·지방세: 세금예상.csv (있으면)
    base_vat = [t for t in taxrows if t["kind"] == "부가세" and t.get("due") and t["due"].year == year and t["due"].month == 1]
    if base_vat:
        add_tax(1, "1/25", "부가세 (%d년 10~12월)" % base, base_vat[0]["amount"], "세금예상 (%s)" % base_vat[0].get("basis", ""), "분개장")
    else:
        add_tax(1, "1/25", "부가세 (%d년 10~12월)" % base, _r4(VAT * sum(base_gp_m[9:12])), "올해 10~12월 매출총이익 × 10% (예상)", "올해 예상")
    # 올해분 법인세·지방세: 손익표와 같은 '올해 연말 예상 세전 이익' 하나로 계산 (2026-11-14 오후 점검 G3: 예전엔 손익표는
    # 연말 예상 이익, 지급 일정은 세금예상.csv 의 지금까지 이익이라 같은 예산 안에서 1,001만 달랐음). 기납부(중간예납)는
    # 세금예상.csv 의 값이 있으면 뺀다. 결산·세무조정 뒤 바뀔 수 있으므로 '예상'으로 적는다.
    corp_rows = [t for t in taxrows if t["kind"] == "법인세" and t.get("due") and t["due"].year == year]
    prepaid = corp_rows[0].get("prepaid") if corp_rows else None
    calc_tax = lc
    if lc is not None:
        add_tax(3, "3/31", "법인세 (%d년분)" % base, max(lc - (prepaid or 0), 0),
                "%d년 연말 예상 세전 이익 기준 산출세액 %s%s" % (base, format(lc, ","),
                                                   " − 기납부 %s" % format(prepaid, ",") if prepaid else " (기납부 모름 — 빼지 않음)"),
                "예산 계산 (예상)")
        add_tax(4, "4/30", "지방소득세 (%d년분)" % base, int(lc * LOCAL), "법인세 산출세액 × 10%", "예산 계산 (예상)")
    sga_vat_q = _r4(VAT * sum(x["budget"] for x in SGA if x["basis"] != "인원") / 4.0)
    for q in range(3):
        s_ = slice(q * 3, q * 3 + 3)
        amt = max(_r4(VAT * sum(gp[s_]) - sga_vat_q), 0)
        add_tax(q * 3 + 4, "%d/25" % (q * 3 + 4), "부가세 (%d년 %d~%d월)" % (year, q * 3 + 1, q * 3 + 3), amt,
                "(매출 − 매입) 예산 × 10% − 판관비 매입세액", "예산 계산")
    if calc_tax:
        add_tax(8, "8/31", "법인세 중간예납 (%d년분)" % year, _r4(calc_tax / 2.0), "%d년 산출세액 ÷ 2" % base, "예산 계산")
    FIX.sort(key=lambda f: (f["month"], int(f["day"].split("/")[1])))
    min_cash = None
    try:
        min_cash = int(float(str(S.get("위험_최소보유현금", "100000000")).replace(",", "")))
    except ValueError:
        min_cash = 100000000
    nio = [nin_m[i] - nout_m[i] for i in range(12)]
    sga_pay = [_r4(v * (1 + VAT * 0.5)) for v in sga_m]
    y0 = dt.date(year, 1, 1)
    # 주간 보고와 같은 일정 계산 (자금계획서·자금일정·세금 예상). 못 하면 무엇을 못 했는지 남긴다 (K2)
    W = None
    try:
        from .calc import compute as _calc
        W = _calc(d, "weekly", asof)
    except Exception as e:   # 보고는 만들되 연초 잔액·정해진 지급은 '모름'
        notes.append("주간 자금 일정을 계산하지 못해(%s) 연초 잔액과 대출 원금 등 정해진 지급을 넣지 못함" % type(e).__name__)
    # 정해진 지급 (2026-11-14 오후 점검 G2): 예산 연도 안 대출 원금·보증금·설비 같은 지급. 매입·급여·판관비·세금·이자·카드는
    # 예산 숫자에 이미 있어 넣지 않는다 (같은 돈 두 번 빼지 않게)
    fixed = [0] * 12
    if W is not None:
        for e in W.get("events") or []:
            cat = str(e.get("cat") or "")
            if (e.get("io") != "out" or e.get("amount") is None or not e.get("date") or e["date"].year != year
                    or not any(w in cat for w in FIXED_WORDS) or any(w in cat for w in FIXED_SKIP)):
                continue
            fixed[e["date"].month - 1] += e["amount"]
            FIX.append({"month": e["date"].month, "day": "%d/%d" % (e["date"].month, e["date"].day),
                        "name": "%s%s" % (cat.replace("자금계획서 ", ""), " · %s" % e["desc"] if e.get("desc") else ""),
                        "amount": e["amount"], "how": "%s%s" % ("확정" if e.get("firm") else "예상", " · %s" % e["basis"] if e.get("basis") else ""),
                        "src": e.get("source") or "자금일정", "kind": "fixed"})
        FIX.sort(key=lambda f: (f["month"], int(f["day"].split("/")[1])))
    cout = [None if sal[i] is None else cpay[i] + sal[i] + sga_pay[i] + tax_m[i] + fixed[i] for i in range(12)]
    bal = []
    # 연초 잔액 = 오늘 쓸 수 있는 돈(주간 보고와 같은 값: 은행 잔액 날짜 뒤 통장 입출금까지 반영, 사용 제한 뺌)
    #           + 오늘 뒤 ~ 연말 들어오고 나갈 돈 (2026-11-14 오후 점검 G4: 예전엔 은행 잔액 날짜~오늘 실제 입출금이 빠짐)
    roll, roll_n, roll_ok = 0, 0, True
    avail0 = None
    if asof < y0 - dt.timedelta(days=1):
        if W is None or W["s2"].get("start") is None:
            roll_ok = False
            if W is not None:
                notes.append("오늘 쓸 수 있는 돈을 몰라(통장 잔액·지급 자료 확인) 연초 잔액을 모름")
        else:
            avail0 = W["s2"]["start"]
            evs = [e for e in W["s2"].get("dated") or [] if asof < e["date"] < y0 and e.get("amount") is not None]
            roll = sum(e["amount"] if e["io"] == "in" else -e["amount"] for e in evs)
            roll_n = len(evs)
            if (W["s2"].get("horizon") or y0) < y0 - dt.timedelta(days=1):
                notes.append("연말까지 일정이 %s까지만 있어 그 뒤 입출금은 연초 잔액에 넣지 못함" % W["s2"]["horizon"].isoformat())
        start = None if not roll_ok else avail0 + roll
    else:   # 예산 연도에 들어와 만들면 장부 잔액 그대로
        start = None if bal0 is None else bal0 - restricted
    b = start
    for i in range(12):
        if b is None or cout[i] is None:
            b = None
        else:
            b = b + cin[i] - cout[i] + nio[i]
        bal.append(b)
    lo = None if None in bal else min(range(12), key=lambda i: bal[i])
    if bal0 is None:
        notes.append("통장 잔액 자료가 없어 월별 자금 계획을 만들지 못함")
    return {
        "year": year, "base": base, "asof": asof, "teams": teams, "T": T, "last_m": last_m, "src": src,
        "rev": rev, "gp": gp, "cogs": cogs, "sal": sal, "sga": sga_m, "dep": dep_m, "nin": nin_m, "nout": nout_m, "op": op_m,
        "Y": Y, "L": L, "got": got, "seas": seas, "seas_src": seas_src, "SGA": SGA, "dep_src": D["source"],
        "heads0": heads0, "hires": hires, "heads": heads, "havg": havg, "per": per, "sal_last": sal_last, "last_ym": last_ym,
        "raise": raise_, "infl": infl, "cost_rate": cost_rate,
        "cash": {"bal0": bal0, "bal_date": bal_date, "restricted": restricted, "roll": roll, "roll_n": roll_n, "start": start, "cin": cin, "cpay": cpay, "sga_pay": sga_pay,
                 "tax": tax_m, "fixed": fixed, "nio": nio, "bal": bal, "lo": lo, "min_cash": min_cash, "days": days, "n_days": n_days,
                 "days_used": days_used, "split": split, "avail0": avail0},
        "fix": FIX, "notes": notes,
        "missing": [k for k, v in (("성장률", any(not T[t]["growth_set"] for t in teams)), ("목표 수익률", any(not T[t]["rate_set"] for t in teams)),
                                   ("급여 인상률", raise_ is None), ("물가 인상률", infl is None)) if v],
    }


def blank_cash(B):
    """자금계획서·분개장이 최신이 아닐 때 경영관리용: 항목은 남기고 자금 전망 숫자(월초·월말·가장 적은 달)만 비운다
    (2026-11-14 오후 점검 K7, 11/12 절대 규칙 '자료가 없거나 오래되면 자금 숫자는 비움'). 손익 예산은 그대로."""
    B = dict(B)
    c = dict(B["cash"])
    c.update({"start": None, "bal": [None] * 12, "lo": None, "avail0": None, "roll": 0, "roll_n": 0})
    B["cash"] = c
    B["blocked"] = True
    return B


# ───────────── 확정 ─────────────
def confirm(input_dir, B, today=None):
    """달별 예산을 입력/예산확정.csv 에 남긴다 (그 해 줄은 바꿈). -> 줄 수."""
    today = today or dt.date.today()
    y = str(B["year"])
    keep = []
    path = os.path.join(input_dir, CONFIRM_FILE)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                keep = [r for r in csv.DictReader(f) if (r.get("연도") or "").strip() != y]
        except (OSError, UnicodeDecodeError, csv.Error):
            keep = []
    rows = []
    for i in range(12):
        for t in B["teams"]:
            R = B["T"][t]
            rows.append({"연도": y, "월": i + 1, "대상": t, "매출": R["rev"][i], "매출총이익": R["gp"][i], "확정일": today.isoformat()})
        rows.append({"연도": y, "월": i + 1, "대상": COMPANY, "매출": B["rev"][i], "매출총이익": B["gp"][i],
                     "급여": B["sal"][i], "판관비": B["sga"][i], "감가상각비": B["dep"][i],
                     "영업외수익": B["nin"][i], "영업외비용": B["nout"][i], "확정일": today.isoformat()})
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CONFIRM_COLUMNS, lineterminator="\r\n", extrasaction="ignore")
        w.writeheader()
        for r in keep + rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in CONFIRM_COLUMNS})
    os.replace(tmp, path)
    return len(rows)


def read_confirmed(input_dir):
    """-> {연도(글자): {"date": 확정일, "rows": {(월, 대상): {매출, 매출총이익, 급여, 판관비, 감가상각비, 영업외수익, 영업외비용}}}}."""
    path = os.path.join(input_dir, CONFIRM_FILE)
    out = {}
    if not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                y, m, who = (r.get("연도") or "").strip(), (r.get("월") or "").strip(), (r.get("대상") or "").strip()
                if not (y.isdigit() and m.isdigit() and who):
                    continue
                Y = out.setdefault(y, {"date": (r.get("확정일") or "").strip(), "rows": {}})
                v = {}
                for k in CONFIRM_COLUMNS[3:10]:
                    t = (r.get(k) or "").replace(",", "").strip()
                    v[k] = int(float(t)) if re.match(r"^-?\d+(\.\d+)?$", t) else None
                Y["rows"][(int(m), who)] = v
    except (OSError, UnicodeDecodeError, csv.Error):
        return {}
    return out


def compare(confirmed, ym, actual_team, actual_co=None):
    """월간 보고 '예산 대비'. actual_team = {팀: [(월, 매출, 매출총이익) ...]} (올해 1월~이번 달).
    -> None (그 해 확정 예산 없음) 또는 {"date", "month", "rows": [{team, cur, cur_b, ytd, ytd_b, gp, gp_b}], "tot": {...}}."""
    y, m = ym[:4], int(ym[5:7])
    C = (confirmed or {}).get(y)
    if not C:
        return None
    teams = sorted(set(w for (_, w) in C["rows"] if w != COMPANY))
    rows = []
    for t in teams:
        act = {mm: (rv, g) for mm, rv, g in actual_team.get(t, [])}
        def b(mm, k):
            v = C["rows"].get((mm, t), {}).get(k)
            return v or 0
        rows.append({"team": t,
                     "cur": act.get(m, (None, None))[0], "cur_b": b(m, "매출"),
                     "ytd": sum((act.get(mm, (0, 0))[0] or 0) for mm in range(1, m + 1)),
                     "ytd_b": sum(b(mm, "매출") for mm in range(1, m + 1)),
                     "gp": sum((act.get(mm, (0, 0))[1] or 0) for mm in range(1, m + 1)),
                     "gp_b": sum(b(mm, "매출총이익") for mm in range(1, m + 1))})
    tot = {k: sum((r[k] or 0) for r in rows) for k in ("cur", "cur_b", "ytd", "ytd_b", "gp", "gp_b")}
    co = None
    if actual_co:
        def cb(k):
            return sum((C["rows"].get((mm, COMPANY), {}).get(k) or 0) for mm in range(1, m + 1))
        co = {"sal_b": cb("급여"), "sga_b": cb("판관비"), "dep_b": cb("감가상각비")}
        co["op_b"] = tot["gp_b"] - co["sal_b"] - co["sga_b"] - co["dep_b"]
        co.update(actual_co)
    return {"date": C["date"], "month": m, "rows": rows, "tot": tot, "co": co}
