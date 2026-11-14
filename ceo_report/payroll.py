"""급여 점검·연말정산 예상 (사용자 2026-11-12: 고용·근로기준 법령으로 급여 처리 이상 확인, 직원 연말정산 예상).

읽는 자료 (위하고 '인사·급여 자료 받기' 원본을 변환이 풀어 만드는 파일 — 읽기는 PC에서 화면 확인 뒤 완성):
  사원.csv     사원명, 생년월일, 입사일, 퇴사일, 고용형태, 주소정근로시간, 임원, 부양가족수, 자녀수
  급여명세.csv  연월, 사원명, 구분(지급/공제), 항목, 금액
없으면 장부로 만든 사원급여.csv(달별 급여 총액)만으로 할 수 있는 점검만 한다.
법정 값(최저임금·요율·가산율 등)은 taxlaw 연도별 기준표 — 미확인이면 그 점검은 '기준 확인 필요'.
개인정보: 생년월일·입퇴사일·급여 항목만 쓴다(주민번호 뒷자리·주소는 읽지 않음). 결과는 경영관리 보고에만.
"""
import collections
import csv
import datetime as dt
import os

EMP_FILE, PAY_FILE = "사원.csv", "급여명세.csv"
EXTRA_WORDS = ("연장", "야간", "휴일", "상여", "성과", "인센티브", "특근")
DED = {"국민연금": "국민연금", "건강보험": "건강", "장기요양": "장기요양", "고용보험": "고용", "소득세": "소득세", "지방소득세": "지방"}
# 연말정산 간이 계산 상수 (2025년 귀속 기준 — 세무사 확인 필요)
PERSONAL = 1_500_000
CHILD = {1: 250_000, 2: 550_000}
CHILD_MORE = 400_000
STANDARD_CREDIT = 130_000


def _read(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _d(t):
    try:
        return dt.date.fromisoformat(str(t).strip()[:10])
    except ValueError:
        return None


def _n(t):
    try:
        return int(float(str(t).replace(",", "").strip() or 0))
    except ValueError:
        return 0


def load(input_dir):
    """-> (사원 {이름: dict}, 명세 {(연월, 이름): {"pay": {항목: 금액}, "ded": {항목: 금액}}}, 명세 있음?)."""
    emps = dict((r["사원명"].strip(), r) for r in _read(os.path.join(input_dir, EMP_FILE)) if (r.get("사원명") or "").strip())
    slips = collections.defaultdict(lambda: {"pay": {}, "ded": {}})
    detail = False
    for r in _read(os.path.join(input_dir, PAY_FILE)):
        k = ((r.get("연월") or "")[:7], (r.get("사원명") or "").strip())
        side = "ded" if (r.get("구분") or "").strip() == "공제" else "pay"
        slips[k][side][(r.get("항목") or "").strip()] = slips[k][side].get((r.get("항목") or "").strip(), 0) + _n(r.get("금액"))
        detail = True
    if not detail:   # 장부 사원급여.csv: 달별 총액만
        for r in _read(os.path.join(input_dir, "사원급여.csv")):
            k = ((r.get("연월") or "")[:7], (r.get("사원명") or "").strip())
            slips[k]["pay"]["급여(총액)"] = slips[k]["pay"].get("급여(총액)", 0) + _n(r.get("급여"))
    return emps, dict(slips), detail


def _ded(slip, key):
    return sum(v for k, v in slip["ded"].items() if key in k and not (key == "소득세" and "지방" in k))


def check(input_dir, ym, holders=()):
    """ym 달 급여 점검 -> [(사원, 점검, 상태 'ok'|'warn'|'info'|'law', 근거)]."""
    from . import taxlaw
    year = int(ym[:4])
    law = lambda k: taxlaw.value(input_dir, year, k)
    emps, slips, detail = load(input_dir)
    out = []
    officers = set(n for n, e in emps.items() if (e.get("임원") or "").strip() in ("예", "Y", "y", "1", "임원"))
    holders = set(holders) | officers   # 임원은 근로기준법 근로자가 아님 (최저임금·연차 점검 제외)
    names = sorted(n for (m, n) in slips if m == ym and n not in holders)
    mw, mw_ok, _ = law("최저시급")
    hours, _, _ = law("월소정시간")
    rates = dict((k, law(k)) for k in ("국민연금요율", "건강보험료율", "장기요양비율", "고용보험요율", "국민연금상한", "식대비과세"))
    for n in names:
        s = slips[(ym, n)]
        e = emps.get(n, {})
        total = sum(s["pay"].values())
        base = sum(v for k, v in s["pay"].items() if not any(w in k for w in EXTRA_WORDS))
        week = _n(e.get("주소정근로시간")) or 40
        h = (hours or 209) * week / 40.0
        # 1) 최저임금
        if not mw_ok:
            out.append((n, "최저임금", "law", "최저임금 기준 확인 필요"))
        elif base and base / h < mw:
            out.append((n, "최저임금", "warn", "시급 환산 %s원 < 최저임금 %s원 (기본·고정 %s원 ÷ %g시간)" % (format(int(base / h), ","), format(mw, ","), format(base, ","), h)))
        else:
            out.append((n, "최저임금", "ok" if detail else "info", "시급 환산 %s원%s" % (format(int(base / h), ",") if base else "–", "" if detail else " (명세 없어 총액 기준)")))
        if not detail:
            continue
        # 2) 4대보험 근로자 몫
        meal = sum(v for k, v in s["pay"].items() if "식대" in k)
        taxable = total - min(meal, rates["식대비과세"][0] or 0)
        birth = _d(e.get("생년월일"))
        age = (dt.date(year, int(ym[5:]), 1) - birth).days // 365 if birth else None
        exp = {}
        if rates["국민연금요율"][1] and (age is None or age < 60):
            cap = rates["국민연금상한"][0] or taxable
            exp["국민연금"] = int(min(taxable, cap) * rates["국민연금요율"][0] / 2) // 10 * 10
        if rates["건강보험료율"][1]:
            exp["건강"] = int(taxable * rates["건강보험료율"][0] / 2) // 10 * 10
            if rates["장기요양비율"][1]:
                exp["장기요양"] = int(exp["건강"] * rates["장기요양비율"][0]) // 10 * 10
        if rates["고용보험요율"][1]:
            exp["고용"] = int(taxable * rates["고용보험요율"][0] / 2) // 10 * 10
        got = dict((k, _ded(s, k)) for k in ("국민연금", "건강", "장기요양", "고용"))
        if not any(got.values()) and week >= 15:
            out.append((n, "4대보험", "warn", "공제된 4대보험이 없음 (주 %g시간 근무) — 가입 여부 확인" % week))
        else:
            off = [(k, got[k], v) for k, v in exp.items() if v and abs(got[k] - v) > max(1000, v * 0.1)]
            out.append((n, "4대보험", "info" if off else "ok",
                        ("요율대로면 " + ", ".join("%s %s원(공제 %s원)" % (k, format(v, ","), format(g, ",")) for k, g, v in off) +
                         " — 보수월액 신고 기준이라 차이 날 수 있음") if off else "요율대로 공제됨"))
        # 3) 연장·야간·휴일 수당 (시간 자료가 있을 때만: 항목 이름에 '시간' 들어간 지급 줄은 아직 없음)
        # 4) 퇴직금·연차
        join = _d(e.get("입사일"))
        if join:
            yrs = (dt.date(year, int(ym[5:]), 28) - join).days / 365.0
            if yrs >= 1 and week >= 15:
                avg3 = _avg3(slips, n, ym)
                out.append((n, "퇴직금", "info", "근속 %.1f년 — 지금 퇴사하면 약 %s원 (최근 3달 평균 %s × 근속)" % (yrs, format(int(avg3 * yrs), ","), format(int(avg3), ","))))
            leave = min(11, int(yrs * 12)) if yrs < 1 else 15 + int((yrs - 1) // 2)
            out.append((n, "연차", "info", "근속 %.1f년 → 연차 %d일 발생 (1년 미만은 달마다 1일)" % (yrs, min(leave, 25))))
            if join.year == year and join.strftime("%Y-%m") == ym and join.day > 1:
                nxt = slips.get((_next(ym), n))
                if nxt and total >= sum(nxt["pay"].values()) * 0.95:
                    out.append((n, "입사 달 일할", "warn", "%s 입사인데 그 달 급여가 다음 달과 같음 — 일할 계산 확인" % join.isoformat()))
    return out


def _next(ym):
    y, m = int(ym[:4]), int(ym[5:]) + 1
    return "%04d-%02d" % (y + (m > 12), 1 if m > 12 else m)


def _avg3(slips, n, ym):
    ms = sorted((m for (m, x) in slips if x == n and m <= ym), reverse=True)[:3]
    return sum(sum(slips[(m, n)]["pay"].values()) for m in ms) / float(len(ms) or 1)


def wage_credit(calc, gross):
    """근로소득세액공제 (한도 포함)."""
    c = calc * 0.55 if calc <= 1_300_000 else 715_000 + (calc - 1_300_000) * 0.30
    if gross <= 33_000_000:
        lim = 740_000
    elif gross <= 70_000_000:
        lim = max(740_000 - (gross - 33_000_000) * 0.008, 660_000)
    else:
        lim = max(660_000 - (gross - 70_000_000) / 2, 500_000)
    return int(min(c, lim))


def yearend(input_dir, year, asof, holders=()):
    """직원별 연말정산 예상 -> [{name, months, gross, tax, paid, diff, notes}]. 1~asof 달 실적 × 12/달 수 (기본 공제만 넣은 보수적 값)."""
    from .dividend import basic_tax, wage_deduction
    from . import taxlaw
    emps, slips, detail = load(input_dir)
    meal_lim = taxlaw.value(input_dir, year, "식대비과세")[0] or 0
    by = collections.defaultdict(list)
    for (m, n), s in slips.items():
        if m[:4] == str(year) and m <= asof.strftime("%Y-%m") and n not in holders:
            by[n].append(s)
    out = []
    for n, ss in sorted(by.items()):
        k = len(ss)
        e = emps.get(n, {})
        left = _d(e.get("퇴사일"))
        scale = 1.0 if (left and left.year == year) else 12.0 / k
        pay = sum(sum(s["pay"].values()) for s in ss)
        meal = sum(min(sum(v for kk, v in s["pay"].items() if "식대" in kk), meal_lim) for s in ss)
        gross = int((pay - meal) * scale)
        ins = lambda key: int(sum(_ded(s, key) for s in ss) * scale)
        pension, health = ins("국민연금"), ins("건강") + ins("장기요양") + ins("고용")
        deps = _n(e.get("부양가족수"))
        base = max(gross - wage_deduction(gross) - PERSONAL * (1 + deps) - pension - health, 0)
        calc = basic_tax(base)
        kids = _n(e.get("자녀수"))
        child = CHILD.get(kids, 0) if kids <= 2 else CHILD[2] + CHILD_MORE * (kids - 2)
        tax = max(calc - wage_credit(calc, gross) - child - STANDARD_CREDIT, 0)
        paid = int(sum(_ded(s, "소득세") for s in ss) * scale) if detail else None
        notes = []
        if not detail:
            notes.append("급여 명세 없음 — 장부 총액으로 어림, 기납부 세액 모름")
        if not e:
            notes.append("사원 정보 없음 — 부양가족 0명으로 봄")
        out.append({"name": n, "months": k, "gross": gross, "tax": int(tax * 1.1), "paid": None if paid is None else int(paid * 1.1),
                    "diff": None if paid is None else int((paid - tax) * 1.1), "notes": notes})
    return out


def for_report(input_dir, asof):
    """월간 경영관리 보고용 HTML 또는 None (사원.csv·급여명세.csv 가 없으면 장(章)을 만들지 않음)."""
    if not any(os.path.exists(os.path.join(input_dir, f)) for f in (EMP_FILE, PAY_FILE)):
        return None
    from .util import esc
    emps, slips, _ = load(input_dir)
    months = sorted(m for (m, _n) in slips if m <= asof.strftime("%Y-%m"))
    if not months:
        return None
    ym = months[-1]
    officers = tuple(n for n, e in emps.items() if (e.get("임원") or "").strip() in ("예", "Y", "y", "1", "임원"))
    return render(check(input_dir, ym), yearend(input_dir, asof.year, asof, officers), esc, ym, asof.year)


def render(C, Y, esc, ym, year):
    mark = {"ok": "<span class='tag'>이상 없음</span>", "warn": "<b style='color:#c62828'>확인 필요</b>",
            "info": "<span class='tag e'>참고</span>", "law": "<b style='color:#8a5a00'>기준 확인 필요</b>"}
    h = ["<h2>급여 점검 · 연말정산 예상</h2>"]
    if C:
        warn = [c for c in C if c[2] == "warn"]
        h.append("<div class='q'>%s 급여 점검 — 확인 필요 %d건</div>" % (esc(ym), len(warn)))
        h.append("<table class='re'><tr><th class='l'>사원</th><th class='l'>점검</th><th>결과</th><th class='l'>근거</th></tr>%s</table>"
                 % "".join("<tr><td class='l'>%s</td><td class='l'>%s</td><td>%s</td><td class='l'>%s</td></tr>" % (esc(a), esc(b), mark[c], esc(d))
                           for a, b, c, d in sorted(C, key=lambda x: ({"warn": 0, "law": 1, "info": 2, "ok": 3}[x[2]], x[0]))))
    if Y:
        h.append("<div class='q'>%d년 연말정산 예상 (기본 공제만 — 카드·의료비 등 넣으면 환급이 더 커짐)</div>" % year)
        h.append("<table class='re'><tr><th class='l'>사원</th><th>달 수</th><th>총급여(연)</th><th>결정세액(지방세 포함)</th><th>낸 세금</th><th>예상</th><th class='l'>메모</th></tr>%s</table>"
                 % "".join("<tr><td class='l'>%s</td><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class='l'>%s</td></tr>"
                           % (esc(y["name"]), y["months"], format(y["gross"], ","), format(y["tax"], ","),
                              "–" if y["paid"] is None else format(y["paid"], ","),
                              "–" if y["diff"] is None else ("환급 %s" % format(y["diff"], ",") if y["diff"] >= 0 else "추가 납부 %s" % format(-y["diff"], ",")),
                              esc(" · ".join(y["notes"]))) for y in Y))
    h.append("<div class='note'>법정 기준값은 세법·노동법 기준표에서 읽음 (미확인이면 '기준 확인 필요'). 급여 명세·사원 정보는 확장의 '인사·급여 자료 받기'로 들어옵니다. "
             "연말정산 공제 규칙은 2025년 귀속 기준 간이 계산 — 세무사 확인 필요.</div>")
    return "".join(h)
