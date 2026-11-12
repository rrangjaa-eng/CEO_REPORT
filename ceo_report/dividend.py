"""배당 권장액 (사용자 2026-11-12: 대표 근로소득을 고려해 얼마나 배당하는 게 좋은지 계산해 권장).

AI 없이 규칙 계산만 한다: 배당 총액을 바꿔 가며 주주마다(지분율대로 균등배당) 늘어나는 개인 세금을 계산하고,
'배당에 붙는 세금이 15.4%를 넘지 않는 가장 큰 금액'을 권장한다. 미성년자는 1인 금융소득 2천만 원 이하로 묶는다.

- 주주.csv (창 '가끔 넣는 값' → 주주): 이름, 지분율(%), 미성년자(예/아니오), 회사급여(예/아니오: 사원급여.csv 최근 12달 합을 근로소득으로),
  다른금융소득(연, 원), 그밖소득(연 소득금액, 원). 비운 칸은 0으로 보고 그렇다고 적는다.
- 세법 값은 2026년 기준(아래 상수). 해마다 바뀔 수 있어 결과에 '세무사 확인 필요'를 붙인다.
- 간이 계산: 본인 기본공제 150만 원만 빼고 다른 공제·감면·세액공제는 넣지 않는다(배당 있을 때와 없을 때 차이만 보므로 영향이 작음).
"""
import csv
import datetime as dt
import os

FILE = "주주.csv"
COLUMNS = ["이름", "지분율", "미성년자", "회사급여", "다른금융소득", "그밖소득", "공제인원"]

# 2026년 기준 (세무사 확인 필요)
FIN_LIMIT = 20_000_000          # 금융소득 종합과세 기준 (이자+배당, 1인 연)
WITHHOLD = 0.14                 # 배당·이자 원천징수 소득세율 (지방소득세 10% 별도 → 15.4%)
GROSS_UP = 0.10                 # 배당 가산율 (Gross-up)
LOCAL = 0.10
PERSONAL = 1_500_000            # 본인 기본공제
RATES = [(14_000_000, 0.06, 0), (50_000_000, 0.15, 1_260_000), (88_000_000, 0.24, 5_760_000),
         (150_000_000, 0.35, 15_440_000), (300_000_000, 0.38, 19_940_000), (500_000_000, 0.40, 25_940_000),
         (1_000_000_000, 0.42, 35_940_000), (None, 0.45, 65_940_000)]
STEP = 1_000_000
HEALTH_LIMIT = 20_000_000       # 직장가입자 보수 외 소득(배당·이자·임대 등) 연 2천만 넘으면 건강보험료 추가 (소득월액보험료)
HEALTH_RATE = 0.0719            # 건강보험료율 (2026년, 확인 필요) — 넘는 금액에 매김 (장기요양보험료는 넣지 않음)


def basic_tax(base):
    """종합소득 기본세율 산출세액."""
    base = max(int(base), 0)
    for top, rate, minus in RATES:
        if top is None or base <= top:
            return max(int(base * rate - minus), 0)
    return 0


def wage_deduction(gross):
    """근로소득공제 (한도 2천만)."""
    g = max(int(gross), 0)
    if g <= 5_000_000:
        d = g * 0.7
    elif g <= 15_000_000:
        d = 3_500_000 + (g - 5_000_000) * 0.4
    elif g <= 45_000_000:
        d = 7_500_000 + (g - 15_000_000) * 0.15
    elif g <= 100_000_000:
        d = 12_000_000 + (g - 45_000_000) * 0.05
    else:
        d = 14_750_000 + (g - 100_000_000) * 0.02
    return int(min(d, 20_000_000))


def health_extra(nonwage, salaried):
    """직장가입자(회사 급여 받는 사람)의 보수 외 소득이 2천만 넘으면 넘는 금액 × 건강보험료율 (간이)."""
    if not salaried:
        return 0
    return int(max(nonwage - HEALTH_LIMIT, 0) * HEALTH_RATE)


def person_tax(other_base, interest, div):
    """소득세(지방소득세 포함) 합. other_base = 금융소득 뺀 종합소득 과세표준."""
    F = interest + div
    if F <= FIN_LIMIT:
        t = basic_tax(other_base) + F * WITHHOLD
    else:
        excess = F - FIN_LIMIT
        g = min(div, excess) * GROSS_UP   # 2천만은 이자부터 채우고, 넘는 배당에 가산
        general = FIN_LIMIT * WITHHOLD + basic_tax(other_base + excess + g)
        compare = F * WITHHOLD + basic_tax(other_base)
        credit = min(g, general - compare) if general > compare else 0
        t = max(general, compare) - credit
    return int(round(t * (1 + LOCAL)))


def read(input_dir):
    path = os.path.join(input_dir, FILE)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if (r.get("이름") or "").strip()]


def _num(text, what):
    t = str(text or "").replace(",", "").replace("원", "").replace("%", "").strip()
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        raise ValueError("%s 숫자 형식 오류: %s" % (what, text))


def save(input_dir, name, share, minor, salaried, interest, other, delete=False, dependents=""):
    """주주 한 명 저장(같은 이름이면 바꿈) 또는 지우기. -> (동작, 주주 수, 지분율 합)."""
    name = (name or "").strip()
    if not name:
        raise ValueError("이름을 넣으세요")
    rows = [r for r in read(input_dir) if r["이름"].strip() != name]
    action = "지움" if delete else "저장"
    if not delete:
        s = _num(share, "지분율")
        if s is None or not 0 < s <= 100:
            raise ValueError("지분율은 0보다 크고 100 이하 (예: 50)")
        for v, w in ((interest, "다른 금융소득"), (other, "그 밖의 소득")):
            if (_num(v, w) or 0) < 0:
                raise ValueError("%s은 0 이상" % w)
        rows.append({"이름": name, "지분율": ("%g" % s), "미성년자": "예" if minor else "아니오",
                     "회사급여": "예" if salaried else "아니오",
                     "다른금융소득": "" if _num(interest, "") is None else str(int(_num(interest, ""))),
                     "그밖소득": "" if _num(other, "") is None else str(int(_num(other, ""))),
                     "공제인원": "" if _num(dependents, "공제인원") is None else str(max(int(_num(dependents, "공제인원")), 1))})
    total = sum(float(r["지분율"] or 0) for r in rows)
    if total > 100.0001:
        raise ValueError("지분율 합이 %.4g%% — 100%%를 넘음" % total)
    os.makedirs(input_dir, exist_ok=True)
    tmp = os.path.join(input_dir, FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(dict((k, r.get(k, "")) for k in COLUMNS))
    os.replace(tmp, os.path.join(input_dir, FILE))
    return action, len(rows), total


def text(input_dir):
    """창에 보일 한 줄."""
    try:
        rows = read(input_dir)
    except Exception:
        return ""
    if not rows:
        return "아직 없음 — 주주마다 이름·지분율을 넣으면 월간 경영관리 보고에 배당 권장액이 나옵니다"
    s = sum(float(r.get("지분율") or 0) for r in rows)
    return " · ".join("%s %s%%%s" % (r["이름"], r["지분율"], " (미성년)" if r.get("미성년자") == "예" else "") for r in rows) + \
        ("  (지분율 합 %g%%)" % s if abs(s - 100) > 0.001 else "")


def wages(input_dir, name, asof):
    """사원급여.csv 에서 그 사람의 최근 12달 급여 합 -> (금액, 달 수) 또는 (None, 0)."""
    path = os.path.join(input_dir, "사원급여.csv")
    if not os.path.exists(path):
        return None, 0
    lo = (asof.replace(day=1) - dt.timedelta(days=365)).strftime("%Y-%m")
    hi = asof.strftime("%Y-%m")
    tot, months = 0, set()
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("사원명") or "").strip() != name or not (lo < (r.get("연월") or "") <= hi):
                continue
            try:
                tot += int(float(r.get("급여") or 0))
            except ValueError:
                continue
            months.add(r["연월"])
    return (tot, len(months)) if months else (None, 0)


def people(input_dir, asof, interim=0):
    """주주 -> [{name, share, minor, other_base, interest, wage, salaried, other, notes}]. interim = 올해 이미 한 중간배당 총액."""
    out = []
    for r in read(input_dir):
        name = r["이름"].strip()
        notes = []
        wage, n = (None, 0)
        if r.get("회사급여") == "예":
            wage, n = wages(input_dir, name, asof)
            if wage is None:
                notes.append("분개장 급여에서 이름을 못 찾아 근로소득 0으로 봄")
            elif n < 12:
                wage = int(wage * 12 / n)
                notes.append("급여 %d달치를 12달로 늘려 봄" % n)
        other = int(float(r.get("그밖소득") or 0))
        interest = int(float(r.get("다른금융소득") or 0))
        if not (r.get("그밖소득") or "").strip():
            notes.append("그 밖의 소득 0으로 봄")
        if not (r.get("다른금융소득") or "").strip():
            notes.append("다른 금융소득 0으로 봄")
        n_dep = int(float(r.get("공제인원") or 1))
        share = float(r.get("지분율") or 0) / 100
        if interim:
            interest += int(interim * share)
            notes.append("올해 중간배당 %s원을 금융소득에 넣음" % W(int(interim * share)))
        income = (wage or 0) - wage_deduction(wage or 0) + other
        out.append({"name": name, "share": share, "minor": r.get("미성년자") == "예", "salaried": r.get("회사급여") == "예",
                    "wage": wage, "interest": interest, "other": other,
                    "other_base": max(income - PERSONAL * max(n_dep, 1), 0), "notes": notes})
    return out


def taxes_at(P, total):
    """배당 총액 total 일 때 사람마다 (배당, 늘어난 세금)."""
    out = []
    for p in P:
        d = int(total * p["share"])
        add = person_tax(p["other_base"], p["interest"], d) - person_tax(p["other_base"], p["interest"], 0)
        base_nw = p["interest"] + p.get("other", 0)
        add += health_extra(base_nw + d, p.get("salaried")) - health_extra(base_nw, p.get("salaried"))
        out.append((d, add))
    return out


def plan(input_dir, asof, limit, interim=0):
    """배당 권장 -> dict 또는 None (주주 없음). limit = 배당 한도(미처분이익잉여금 ÷ 1.1, 이익준비금 10% 몫) 또는 None."""
    P = people(input_dir, asof, interim)
    if not P:
        return None
    cap = limit if limit and limit > 0 else 300_000_000
    best, steps = 0, []
    t = STEP
    while t <= cap:
        rows = taxes_at(P, t)
        ok = all(add <= d * WITHHOLD * (1 + LOCAL) + 1 for d, add in rows) and \
            all(not p["minor"] or p["interest"] + d <= FIN_LIMIT for p, (d, _) in zip(P, rows))
        if ok:
            best = t
        else:
            break
        t += STEP
    levels = sorted(set(x for x in (best, best + 10_000_000, best + 30_000_000, best * 2) if 0 < x <= cap))
    table = []
    for lv in levels:
        rows = taxes_at(P, lv)
        tax = sum(a for _, a in rows)
        table.append({"total": lv, "tax": tax, "rate": tax / lv if lv else 0, "rows": rows, "best": lv == best})
    share_sum = sum(p["share"] for p in P)
    return {"people": P, "best": best, "limit": limit, "table": table, "share_sum": share_sum,
            "best_rows": taxes_at(P, best) if best else []}


def W(v):
    return "–" if v is None else "{:,}".format(int(v))


def render(D, esc):
    """처분계산서 장 안의 '배당 권장' 조각."""
    if D is None:
        return ("<div class='q'>배당 권장액</div><div class='note'>주주가 입력되지 않음 — 창 '가끔 넣는 값'의 '주주'에 이름·지분율을 넣으면 "
                "대표 근로소득을 고려한 배당 권장액이 나옵니다.</div>")
    h = ["<div class='q'>배당 권장액 <span class='z'>(지분율대로 똑같이 나누는 배당 · 개인 세금 기준)</span></div>"]
    if D["best"]:
        h.append("<div class='say'>배당에 붙는 세금이 15.4%%를 넘지 않는 가장 큰 배당 총액은 <b>%s원</b>입니다. "
                 "이보다 많이 배당하면 한 사람 이상이 금융소득 2천만 원을 넘어 세금·건강보험료가 더 붙거나%s.</div>"
                 % (W(D["best"]), ", 미성년 주주가 2천만 원 기준을 넘습니다" if any(p["minor"] for p in D["people"]) else " 높은 세율이 적용됩니다"))
    else:
        h.append("<div class='say'>지금 조건으로는 15.4%를 넘지 않는 배당 금액이 없습니다 (아래 표 참고).</div>")
    if D["limit"] is not None:
        h.append("<div class='note'>배당 한도(미처분이익잉여금 ÷ 1.1, 이익준비금 10%% 몫 뺌): %s원 · 실제 배당은 통장 여유 자금(대출 만기·법인세 납부 뒤)도 함께 보고 정하세요.</div>"
                 % W(D["limit"]))
    else:
        h.append("<div class='note'>미처분이익잉여금을 아직 몰라 배당 한도를 확인하지 못함 — 작년 분개장이나 재무상태표가 들어오면 채워집니다.</div>")
    h.append("<table class='re'><tr><th class='l'>주주</th><th>지분율</th><th>근로소득(연)</th><th>권장 배당</th><th>늘어나는 세금·건보료</th><th class='l'>메모</th></tr>")
    for p, (d, add) in zip(D["people"], D["best_rows"] or [(0, 0)] * len(D["people"])):
        h.append("<tr><td class='l'>%s%s</td><td>%g%%</td><td>%s</td><td>%s</td><td>%s</td><td class='l'><span class='ex'>%s</span></td></tr>"
                 % (esc(p["name"]), " <span class='tag'>미성년</span>" if p["minor"] else "", p["share"] * 100, W(p["wage"]),
                    W(d), W(add), esc(" · ".join(p["notes"]))))
    h.append("</table>")
    if D["table"]:
        h.append("<table class='re'><tr><th>배당 총액</th><th>세금 합</th><th>세금 비율</th>%s</tr>"
                 % "".join("<th>%s</th>" % esc(p["name"]) for p in D["people"]))
        for t in D["table"]:
            h.append("<tr%s><td>%s%s</td><td>%s</td><td>%.1f%%</td>%s</tr>"
                     % (" class='g'" if t["best"] else "", W(t["total"]), " (권장)" if t["best"] else "", W(t["tax"]), t["rate"] * 100,
                        "".join("<td>%s<span class='ex'>세금 %s</span></td>" % (W(d), W(a)) for d, a in t["rows"])))
        h.append("</table>")
    if abs(D["share_sum"] - 1) > 0.00001:
        h.append("<div class='note'>지분율 합이 %g%% — 100%%가 아니라 나머지 주주 몫은 계산에 없습니다.</div>" % (D["share_sum"] * 100))
    h.append("<div class='warn'>미성년 주주: 받은 배당은 자녀 명의 통장에서 자녀 돈으로 관리해야 합니다(부모가 쓰면 증여 문제). "
             "건강보험 피부양자 기준도 확인하세요. 지분율과 다르게 나누는 배당(차등배당)은 증여로 볼 수 있어 계산하지 않습니다. "
             "세율·공제는 2026년 기준 간이 계산(본인 기본공제만)이며 세무사 확인이 필요합니다.</div>")
    return "".join(h)


# ───────────── 판단 전 확인 질문 (사용자 2026-11-12: 필요한 값은 체크리스트로 먼저 넣게, 오차가 크지 않게 꼼꼼히) ─────────────
SET_FILE = "배당설정.csv"
# (키, 묶음, 질문, 종류 'choice'|'amount'|'date', 고를 값, 기본값, 꼭 필요)
# (키, 묶음, 질문, 종류, 고를 값, 기본값, 꼭 넣을 값). 사용자 2026-11-12: 꼭 넣을 값은 비면 저장·판단하지 않음.
# 고를 값에 '모름'이 있는 질문은 '모름'도 답으로 받는다 (그 항목은 '확인 필요'로 남김).
QUESTIONS = [
    ("큰지출", "회사", "1년 안에 장부·자금계획에 없는 큰 지출(장비·이사·투자·차량 등)이 있나요?", "choice", ("없음", "있음"), None, True),
    ("큰지출금액", "회사", "  있으면 금액 (원)", "amount", (), None, False),
    ("큰지출시기", "회사", "  있으면 시기 (YYYY-MM-DD)", "date", (), None, False),
    ("대출연장", "회사", "대출 만기 때 연장된다고 볼까요?", "choice", ("예", "아니오"), "예", False),   # 사용자 2026-11-12: 연장 가정
    ("최소보유현금", "회사", "최소 보유 현금 (원, 비우면 설정값 그대로)", "amount", (), None, False),
    ("예상순이익", "회사", "세무사에게 받은 올해 예상 당기순이익 (원, 있으면 장부 예상 대신 씀)", "amount", (), None, False),
    ("자본금", "회사", "자본금 (원, 비우면 장부에서 읽음)", "amount", (), None, False),
    ("이익준비금", "회사", "지금 이익준비금 잔액 (원, 비우면 장부에서 읽음)", "amount", (), None, False),
    ("주총일", "회사", "정기 주총 예정일 (비우면 3월 31일)", "date", (), None, False),
    ("지급일", "회사", "배당 지급 예정일 (비우면 4월 30일)", "date", (), None, False),
    ("중간배당규정", "회사", "정관에 중간배당 규정이 있나요?", "choice", ("모름", "있음", "없음"), "모름", False),
    ("급여변경", "계획", "대표 급여·상여를 바꿀 계획이 있나요?", "choice", ("없음", "올림", "내림"), None, True),
    ("주식증여", "계획", "몇 년 안에 자녀에게 주식을 더 넘길(증여) 계획이 있나요?", "choice", ("없음", "있음", "모름"), None, True),
    ("퇴직금계획", "계획", "대표 퇴직금으로 회사에 남겨 둘 돈이 있나요?", "choice", ("없음", "있음"), None, True),
    ("퇴직금유보", "계획", "  있으면 금액 (원)", "amount", (), None, False),
    # 법인세 감면·공제 후보 판단 (사용자 2026-11-12) — taxbreak.py
    ("과밀억제", "법인세 감면", "본점이 수도권 과밀억제권역(서울 전역, 인천·경기 일부 시)에 있나요?", "choice", ("예", "아니오", "모름"), None, True),
    ("수도권", "법인세 감면", "본점이 서울·인천·경기 안에 있나요?", "choice", ("예", "아니오"), None, True),
    ("청년창업", "법인세 감면", "2025년 창업 때 대표가 만 15~34세였나요? (군 복무 기간은 최대 6년 빼고 셈)", "choice", ("예", "아니오"), None, True),
    ("신규창업", "법인세 감면", "완전히 새로 시작한 사업인가요? (개인사업 법인 전환·사업 인수·같은 일 폐업 뒤 재개가 아님)", "choice", ("예", "아니오", "모름"), None, True),
    ("감면업종", "법인세 감면", "세무사가 우리 업종이 창업 감면 업종이라고 확인했나요?", "choice", ("예", "아니오", "모름"), None, True),
    ("작년감면", "법인세 감면", "2025년 법인세 신고 때 받은 감면·공제는?", "choice", ("창업감면", "고용공제", "둘 다", "없음", "모름"), None, True),
    ("연구전담", "법인세 감면", "기업부설연구소나 연구개발 전담부서를 인정받았나요?", "choice", ("예", "아니오"), None, True),
    ("승용차기록", "법인세 감면", "회사 차량이 승용차라면 운행기록부를 쓰나요?", "choice", ("모름", "씀", "안 씀", "승용차 없음"), "모름", False),
    ("벤처", "법인세 감면", "벤처기업·이노비즈 인증이 있나요?", "choice", ("예", "아니오", "모름"), "모름", False),
    ("법인세감면", "법인세 감면", "세무사가 알려준 올해 감면·공제 예상액 (원, 있으면 프로그램 계산 대신 씀)", "amount", (), None, False),
]
# 답에 따라 꼭 넣어야 하는 칸: (키, 그 값일 때) -> 함께 넣을 키
NEEDS_IF = {("큰지출", "있음"): ("큰지출금액", "큰지출시기"), ("퇴직금계획", "있음"): ("퇴직금유보",)}
LABEL = dict((k, q) for k, _, q, _, _, _, _ in QUESTIONS)


def read_settings(input_dir):
    path = os.path.join(input_dir, SET_FILE)
    out = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                k, v = (r.get("항목") or "").strip(), (r.get("값") or "").strip()
                if k and v:
                    out[k] = v
    return out


def missing_required(st):
    """꼭 넣을 값 중 빈 것 -> [질문]. 답에 따라 함께 넣어야 하는 칸(큰 지출 금액·시기 등)도 본다."""
    out = [q.strip() for k, _, q, _, _, dflt, need in QUESTIONS if need and not st.get(k) and not dflt]
    for (k, v), more in NEEDS_IF.items():
        if st.get(k) == v:
            out += ["%s → %s" % (LABEL[k].strip(), LABEL[m].strip().replace("있으면 ", "")) for m in more if not st.get(m)]
    return out


def save_settings(input_dir, values, strict=False):
    """values = {키: 값}. 빈 값은 지운다. strict=True(창에서 저장)면 꼭 넣을 값이 비었을 때 저장하지 않는다. -> 저장된 값 dict."""
    cur = read_settings(input_dir)
    spec = dict((k, (kind, opts)) for k, _, _, kind, opts, _, _ in QUESTIONS)
    for k, v in values.items():
        v = (str(v) if v is not None else "").strip()
        if k not in spec:
            continue
        kind, opts = spec[k]
        if not v:
            cur.pop(k, None)
            continue
        if kind == "choice" and v not in opts:
            raise ValueError("%s: '%s' 는 고를 수 있는 값이 아님" % (LABEL[k].strip(), v))
        if kind == "amount":
            n = _num(v, LABEL[k].strip())
            if n is None or n < 0:
                raise ValueError("%s: 0 이상 숫자" % LABEL[k].strip())
            v = str(int(n))
        if kind == "date" and _d(v) is None:
            raise ValueError("%s: 날짜 형식 YYYY-MM-DD" % LABEL[k].strip())
        cur[k] = v
    if strict:
        miss = missing_required(cur)
        if miss:
            raise ValueError("꼭 넣을 값 %d개가 비어 있어 저장하지 않았습니다: %s" % (len(miss), " / ".join(miss)))
    if cur.get("큰지출") == "있음" and not cur.get("큰지출금액"):
        raise ValueError("큰 지출이 있으면 금액도 넣어 주세요")
    if cur.get("퇴직금계획") == "있음" and not cur.get("퇴직금유보"):
        raise ValueError("퇴직금으로 남겨 둘 돈이 있으면 금액도 넣어 주세요")
    os.makedirs(input_dir, exist_ok=True)
    tmp = os.path.join(input_dir, SET_FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["항목", "값"])
        for k, _, _, _, _, _, _ in QUESTIONS:
            if k in cur:
                w.writerow([k, cur[k]])
    os.replace(tmp, os.path.join(input_dir, SET_FILE))
    return cur


def checklist(input_dir):
    """-> [(키, 질문, 넣은 값 또는 None, 꼭 필요, 쓰는 값)] (+ 주주 줄). 쓰는 값 = 넣은 값 또는 기본값."""
    st = read_settings(input_dir) if input_dir else {}
    out = []
    cond = set(m for (k, v), more in NEEDS_IF.items() if st.get(k) == v for m in more)
    for k, _, q, _, _, dflt, need in QUESTIONS:
        v = st.get(k)
        out.append((k, q.strip(), v, need or k in cond, v or dflt))
    rows = read(input_dir) if input_dir else []
    tot = sum(float(r.get("지분율") or 0) for r in rows)
    out.append(("주주", "주주 이름·지분율 (합 100%)", ("%d명, 합 %g%%" % (len(rows), tot)) if rows else None, True,
                "ok" if rows and abs(tot - 100) < 0.001 else None))
    return out


# ───────────── 이번 시기에 배당할까, 넘길까 (사용자 2026-11-12) ─────────────
LOOK_DAYS = 183   # 앞으로 6달 안에 나갈 큰돈(법인세·대출 만기)을 미리 빼고 본다


def _d(text):
    try:
        return dt.date(*[int(x) for x in str(text).strip()[:10].split("-")])
    except (ValueError, TypeError):
        return None


def _ym_add(ym, k):
    y, m = int(ym[:4]), int(ym[5:7]) + k
    while m <= 0:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return "%04d-%02d" % (y, m)


def _sum3(E, last, i):
    vals = [E.get(_ym_add(last, -k)) for k in range(3)]
    if any(v is None or v[i] is None for v in vals):
        return None
    return sum(v[i] for v in vals)


def signals(R, input_dir=None):
    """매출·매입 흐름, 예산, 예상 포함 자금 -> [(수준 'warn'|'info'|'ok', 이름, 설명)]. 숫자로만 판단 (사용자 2026-11-12)."""
    out = []
    asof = R["asof"]
    # 1) 예상 포함 여유 자금 (남은 예산 지급 예정·예상 입금까지)
    per = ((R.get("s2") or {}).get("periods") or [])
    if per and per[-1].get("all") and per[-1]["all"].get("avail") is not None:
        a = per[-1]["all"]["avail"]
        out.append(("warn" if a < 0 else "ok", "예상 포함 여유 자금",
                    "%s까지 예상 지급(남은 예산 등)까지 넣으면 %s원%s" % (per[-1]["end"].isoformat(), W(a), " — 모자랄 수 있음" if a < 0 else "")))
    # 2) 매출·매입 (증빙 작성일자 기준, 공급가액): 최근 3달 vs 그 앞 3달, 작년 같은 3달
    E = R.get("evid_month") or {}
    last = _ym_add(asof.strftime("%Y-%m"), -1)
    r_now, r_prev, r_ly = _sum3(E, last, 0), _sum3(E, _ym_add(last, -3), 0), _sum3(E, _ym_add(last, -12), 0)
    b_now, b_prev = _sum3(E, last, 1), _sum3(E, _ym_add(last, -3), 1)
    if r_now is not None and r_prev:
        ch = r_now / r_prev - 1
        lv = "warn" if ch <= -0.3 else ("info" if ch <= -0.1 else "ok")
        txt = "최근 3달(%s~%s) 매출 %s원, 그 앞 3달보다 %+.0f%%" % (_ym_add(last, -2), last, W(r_now), ch * 100)
        if r_ly:
            txt += ", 작년 같은 때보다 %+.0f%%" % ((r_now / r_ly - 1) * 100)
        out.append((lv, "매출 흐름", txt))
    if r_now and b_now is not None and r_prev and b_prev is not None:
        g_now, g_prev = r_now - b_now, r_prev - b_prev
        lv = "warn" if g_now < 0 else ("info" if g_prev > 0 and g_now < g_prev * 0.7 else "ok")
        out.append((lv, "매출 − 매입", "최근 3달 %s원 (그 앞 3달 %s원)" % (W(g_now), W(g_prev))))
    # 3) 올해 예산 대비 (확정 예산 있을 때)
    bc = R.get("budget_cmp")
    if bc and bc["tot"].get("ytd_b"):
        rate = bc["tot"]["ytd"] / float(bc["tot"]["ytd_b"])
        out.append(("info" if rate < 0.8 else "ok", "올해 예산 대비 매출", "1~%d월 %.0f%% 달성" % (bc["month"], rate * 100)))
    # 4) 내년 예산 (확정했으면): 영업이익 계획이 마이너스거나 급여가 크게 늘면 현금을 남긴다
    if input_dir:
        from . import budget
        C = budget.read_confirmed(input_dir).get(str(asof.year + 1))
        if C:
            rows = C["rows"]
            gp = sum((v.get("매출총이익") or 0) for (m, w), v in rows.items() if w != budget.COMPANY)
            cost = sum((v.get("급여") or 0) + (v.get("판관비") or 0) + (v.get("감가상각비") or 0)
                       for (m, w), v in rows.items() if w == budget.COMPANY)
            op = gp - cost
            out.append(("warn" if op < 0 else "ok", "%d년 확정 예산" % (asof.year + 1),
                        "계획 영업이익 %s원 (매출총이익 %s − 급여·판관비·감가상각비 %s)" % (W(op), W(gp), W(cost))))
        else:
            out.append(("info", "%d년 예산" % (asof.year + 1), "아직 확정 전 — 내년 인원·비용 계획이 정해지면 다시 판단"))
    return out


def div_limit(first, capital=None, reserve=None):
    """배당 한도: 배당 D 와 이익준비금 적립(D 의 10%, 자본금 절반까지 다 쌓였으면 0)이 미처분이익잉여금 안에 들어가야 함."""
    if first is None or first <= 0:
        return 0
    if capital is not None and reserve is not None:
        room = max(capital // 2 - reserve, 0)   # 더 쌓아야 하는 이익준비금
        d = first * 10 // 11
        if d // 10 > room:
            d = first - room
        return int(d)
    return int(first * 10 // 11)


def advise(R, S, D, input_dir=None):
    """월간 보고 R · 처분계산서 S · 배당 계산 D → 제안 dict {verdict: '배당'|'이월'|'보류', amount, reasons[], timing}.

    규칙 (AI 없이):
      0. 판단 전 질문(★)이 비어 있으면 보류.
      1. 배당 한도(미처분이익잉여금에서 이익준비금 적립 몫·퇴직금 유보를 뺀 것)를 모르면 보류.
      2. 여유 자금(보고서 마지막 기간, 최소 보유현금 뺀 확정분)에서 배당 지급일까지 낼 법인세·지방세(감면 뺌),
         1년 안 장부에 없는 큰 지출, 퇴직금 유보, (연장 안 된다고 하면) 대출 만기를 빼고 남는 돈이 배당할 수 있는 현금.
      3. 현금흐름표 회사 상태가 '주의'(빌린 돈 의존형·버티기형 등)이면 이월.
      4. 남는 현금·한도·세금 권장액(15.4% 선) 중 가장 작은 값이 100만 원 이상이면 배당, 아니면 이월."""
    asof = R["asof"]
    reasons, facts = [], []
    CL = checklist(input_dir)
    use = dict((k, u) for k, _, _, _, u in CL)
    timing = ("%d년 3월 정기 주주총회 (%d년 이익 처분)" % (asof.year, asof.year - 1)) if asof.month <= 3 else \
        ("%d년 3월 정기 주주총회 (%d년 이익 처분) — 지금은 미리 보기" % (asof.year + 1, asof.year))
    if use.get("중간배당규정") == "있음":
        timing += " · 정관에 중간배당 규정 있음: 이사회 결의로 연 1회 중간배당도 가능"
    missing = [q for k, q, v, need, u in CL if need and (u is None or str(u).endswith("아직 입력 안 함"))]
    if missing:
        return {"verdict": "보류", "amount": 0, "timing": timing, "facts": facts, "checklist": CL,
                "reasons": ["판단에 필요한 값이 비어 있습니다 — 창 '가끔 넣는 값' → '주주 (배당 계산)'에서 넣어 주세요: " + " / ".join(missing)]}
    cur = (S or {}).get("cur") or {}
    year = (S or {}).get("year") or (asof.year if asof.month > 3 else asof.year - 1)
    first = cur.get("미처분", (None,))[0]
    ni = cur.get("당기순이익", (None, "모름", ""))
    if first is not None and use.get("예상순이익") and ni[0] is not None and ni[1] == "예상":
        first = first - ni[0] + int(use["예상순이익"])
        facts.append(("당기순이익: 세무사 예상으로 바꿈 (장부 예상 %s원)" % W(ni[0]), int(use["예상순이익"])))
    if first is None:
        return {"verdict": "보류", "amount": 0, "timing": timing, "facts": facts, "checklist": CL,
                "reasons": ["미처분이익잉여금(작년까지 쌓인 금액)을 아직 몰라 배당 한도를 확인할 수 없음 — 작년 분개장이나 재무상태표가 들어오면 판단합니다."]}
    cap = int(use["자본금"]) if use.get("자본금") else cur.get("자본금", (None,))[0]
    res = int(use["이익준비금"]) if use.get("이익준비금") else cur.get("이익준비금잔액", (None,))[0]
    limit = div_limit(first, cap, res)
    keep = int(use.get("퇴직금유보") or 0) if use.get("퇴직금계획") == "있음" else 0
    if keep:
        limit = max(limit - keep, 0)
    facts.append(("미처분이익잉여금", first))
    facts.append(("배당 한도 (이익준비금 적립 몫%s 뺌)" % (", 퇴직금 유보" if keep else ""), limit))
    per = ((R.get("s2") or {}).get("periods") or [])
    last = per[-1] if per else None
    avail = last["firm"]["avail"] if last and last.get("firm") else None
    pay_day = _d(use.get("지급일")) or dt.date(year + 1, 4, 30)
    meet = _d(use.get("주총일")) or dt.date(year + 1, 3, 31)
    timing = timing.split(" — ")[0] if asof <= meet else timing
    facts.append(("주총 %s · 배당 지급 %s" % (meet.isoformat(), pay_day.isoformat()), None))
    cash = None
    if avail is not None:
        facts.append(("여유 자금 (%s까지, 확정분·최소 보유현금 뺀 것)" % last["end"].isoformat(), avail))
        if use.get("최소보유현금") and (R.get("s2") or {}).get("min_cash") is not None:
            d_ = R["s2"]["min_cash"] - int(use["최소보유현금"])
            if d_:
                facts.append(("최소 보유 현금 %s원으로 바꿔 봄" % W(int(use["최소보유현금"])), d_))
                avail += d_
        end = last["end"]
        big = []
        tb = (S or {}).get("tb")
        if use.get("법인세감면"):
            cut = int(use["법인세감면"])
        else:   # 감면·공제 후보 중 '해당'만 (사용자 2026-11-12)
            cut = (tb or {}).get("total") or 0
            if cut:
                facts.append(("법인세 감면·공제 '해당' 후보 반영 (아래 표)", cut))
        for t in R.get("tax") or []:
            due = t.get("due")
            if due and end < due <= pay_day and t.get("amount") and t.get("kind") in ("법인세", "법인지방소득세"):
                v = t["amount"]
                c = cut if t["kind"] == "법인세" else int(cut * 0.1)   # 지방소득세는 법인세의 10%라 같이 줄어듦
                if c:
                    v = max(v - c, 0)
                big.append(("%s (%s)%s" % (t["kind"], due.isoformat(), " — 감면·공제 %s원 뺌" % W(c) if c else ""), v))
        extend = use.get("대출연장") != "아니오"
        for ln in ((R.get("debts") or {}).get("loans") or []):
            due = _d(ln.get("due"))
            if due and asof < due <= pay_day + dt.timedelta(days=LOOK_DAYS) and ln.get("balance"):
                name = "%s 만기 %s" % (ln.get("vendor") or ln.get("account") or "차입금", due.isoformat())
                if extend:
                    reasons.append("%s(%s원)은 연장된다고 보고 빼지 않았습니다." % (name, W(ln["balance"])))
                else:
                    big.append((name + " (갚는다고 봄)", ln["balance"]))
        if use.get("큰지출") == "있음" and use.get("큰지출금액"):
            when = _d(use.get("큰지출시기"))
            if when is None or when <= asof + dt.timedelta(days=365):
                big.append(("장부에 없는 큰 지출%s" % (" (%s)" % when.isoformat() if when else ""), int(use["큰지출금액"])))
        if keep:
            big.append(("대표 퇴직금으로 남겨 둘 돈", keep))
        for name, v in big:
            facts.append(("− " + name, v))
        cash = avail - sum(v for _, v in big)
        facts.append(("= 배당에 쓸 수 있는 현금", cash))
    else:
        reasons.append("여유 자금을 계산하지 못함 (통장 시작 잔액이나 최소 보유현금 설정 없음)")
    CF = R.get("cf")
    state = None
    if CF:
        from . import cashflow
        try:
            dg = cashflow.diagnose(CF)
            hv, hl, _ = cashflow.health(CF)
            state = (dg["name"], dg["level"], hl)
            facts.append(("회사 상태 (현금흐름표, %s)" % dg["basis"], None))
        except Exception:
            state = None
    sig = signals(R, input_dir)
    best = (D or {}).get("best") or 0
    if D is None:
        reasons.append("주주·지분율이 입력되지 않아 세금 기준 권장액은 계산하지 않음 (한도·현금만 봄)")
    cands = [x for x in (limit, cash, best if D else None) if x is not None]
    amount = max(min(cands), 0) if cands else 0
    amount = amount // 1_000_000 * 1_000_000
    if state and (state[1] == "warn" or state[2] == "warn"):
        reasons.insert(0, "회사 상태가 '%s'입니다 — 본업에서 들어오는 현금이 모자라 빌린 돈·통장 잔액으로 버티는 중이라, 이익을 밖으로 내보내기보다 회사에 남기는 편이 안전합니다." % state[0])
        verdict = "이월"
    elif any(lv == "warn" for lv, _, _ in sig):
        bad = [n for lv, n, _ in sig if lv == "warn"]
        reasons.insert(0, "%s에서 주의 신호가 있어 이번엔 회사에 남기는 편이 안전합니다." % "·".join(bad))
        verdict = "이월"
    elif cash is not None and cash < 1_000_000:
        reasons.insert(0, "배당 지급일까지 나갈 큰돈(법인세·큰 지출 등)을 빼면 배당에 쓸 현금이 남지 않습니다.")
        verdict = "이월"
    elif amount >= 1_000_000:
        verdict = "배당"
        why = "세금이 15.4%로 끝나는 선" if D and amount == best else ("배당에 쓸 수 있는 현금" if cash is not None and amount == cash // 1_000_000 * 1_000_000 else "배당 한도")
        reasons.insert(0, "한도·현금·회사 상태 모두 괜찮습니다. 금액은 %s에 맞췄습니다." % why)
    else:
        verdict = "이월"
        reasons.insert(0, "배당할 수 있는 금액이 100만 원보다 작습니다.")
    if verdict == "이월" and D and best and (cash or 0) >= best and not (state and (state[1] == "warn" or state[2] == "warn")):
        reasons.append("참고: 주주별 금융소득 2천만 원 기준은 해마다 새로 생겨, 배당하지 않은 해의 15.4% 한도는 다음 해로 넘어가지 않습니다.")
    if use.get("주식증여") == "있음":
        reasons.append("자녀에게 주식을 넘길 계획이 있으면, 잉여금이 쌓일수록 주식 가치가 올라 증여세가 커질 수 있습니다 — 해마다 한도 안에서 배당하는 쪽이 유리할 수 있습니다.")
    if use.get("급여변경") in ("올림", "내림"):
        reasons.append("대표 급여를 %s 계획이면 근로소득이 바뀌어 배당 세금도 달라집니다 — 바뀐 급여가 장부에 들어간 뒤 다시 보세요." % ("올릴" if use["급여변경"] == "올림" else "내릴"))
    if verdict == "배당" and any(lv == "info" for lv, _, _ in sig):
        reasons.append("살펴볼 점: " + " · ".join(n for lv, n, _ in sig if lv == "info"))
    return {"verdict": verdict, "amount": amount if verdict == "배당" else 0, "timing": timing, "facts": facts, "reasons": reasons,
            "state": state, "signals": sig, "checklist": CL}


def advice_html(A, esc):
    if not A:
        return ""
    color = {"배당": "#1b7f3b", "이월": "#2656c5", "보류": "#8a5a00"}[A["verdict"]]
    head = "배당 %s원 권장" % W(A["amount"]) if A["verdict"] == "배당" else ("이번엔 이월(다음 해로 넘김) 권장" if A["verdict"] == "이월" else "판단 보류")
    h = []
    if A.get("checklist"):
        def mark(v, need, u):
            if v or (need and u):
                return "✓", v or u
            if need:
                return "<b style='color:#c62828'>✗</b>", "비어 있음 — 꼭 넣어 주세요"
            return "·", ("기본값: %s" % u) if u else "비움 (기본값·장부 값 씀)"
        h.append("<div class='q'>판단 전에 넣은 값 <span class='tag'>★ 꼭 넣을 값</span></div><table class='re'>%s</table>" % "".join(
            "<tr><td class='l'>%s %s%s</td><td class='l'>%s</td></tr>"
            % (mark(v, need, u)[0], "★ " if need else "", esc(q), esc(mark(v, need, u)[1]))
            for k, q, v, need, u in A["checklist"]))
    h += ["<div class='q'>이번 시기 제안 · %s</div>" % esc(A["timing"]),
         "<div class='say' style='border-left:4px solid %s;padding-left:10px'><b style='color:%s;font-size:15px'>%s</b><br>%s</div>"
         % (color, color, esc(head), "<br>".join(esc(r) for r in A["reasons"]))]
    if A["facts"]:
        rows = []
        for k, v in A["facts"]:
            if v is None:
                rows.append("<tr><td class='l'>%s</td><td>%s</td></tr>"
                            % (esc(k), esc(A["state"][0]) if k.startswith("회사 상태") and A.get("state") else ""))
            elif v is not None:
                rows.append("<tr><td class='l'>%s</td><td>%s</td></tr>" % (esc(k), W(v)))
        h.append("<table class='re'><tr><th class='l'>판단 근거</th><th>금액(원)</th></tr>%s</table>" % "".join(rows))
    if A.get("signals"):
        mark = {"warn": "<span class='tag u'>주의</span>", "info": "<span class='tag e'>살펴봄</span>", "ok": "<span class='tag'>괜찮음</span>"}
        h.append("<table class='re'><tr><th class='l'>함께 본 것</th><th class='l'>숫자</th><th>판단</th></tr>%s</table>"
                 % "".join("<tr><td class='l'>%s</td><td class='l'>%s</td><td>%s</td></tr>" % (esc(n), esc(t), mark[lv])
                           for lv, n, t in A["signals"]))
    h.append("<div class='note'>매달 월간 보고를 만들 때 다시 계산합니다. 중간배당은 정관에 규정이 있을 때만 할 수 있습니다.</div>")
    return "".join(h)
