"""대표 가수금 갚을 시기 (사용자 2026-11-13: "가수금을 전부 갚아도 자금에 영향이 없을지 확인해봐").

요청 자료는 일회성 문서가 아니라 경영관리 보고에 자동 계산으로 (사용자 2026-11-13 규칙).

  · 가수금 잔액: 계정잔액.csv (자료 변환이 분개장으로 만듦) 의 가수금(257…) 대변 − 차변, 보고 기준 달까지.
    분개장이 회사 처음부터가 아니면 잔액을 모르므로 계산하지 않는다.
  · 날마다 통장 잔액: 2장 자금 일정과 같은 숫자 (s2 start + dated). 확정분만 / 예상 지급 포함 두 가지.
  · 갚는 날 후보: 이번 주 금요일, 다음 주 금요일, 이번 달·다음 달·다다음 달 마지막 평일 (자금계획서가 닿는 날까지).
  · '안전' = 그날 전부 갚아도 그 뒤 어느 날도 최소 보유현금(설정, 기본 1억) 아래로 내려가지 않음.
  · 자금계획서·분개장이 빠졌거나 오래됐으면 계산하지 않는다 (사용자 2026-11-12: 자금계획서 없는 숫자 금지).
AI 없이 정해진 규칙과 문장만.
"""
import calendar
import collections
import datetime as dt

from .util import won, esc, d2s

CODE = "257"          # 가수금
MIN_DAYS = 60         # 자금계획서가 짧아도 최소 이만큼은 본다


def balance(input_dir, asof):
    """-> (잔액 또는 None, 못 구한 까닭)."""
    from . import credit
    L = credit.load(input_dir)
    if not L:
        return None, "계정잔액.csv 없음 (자료 변환을 다시 하세요)"
    if not L["start"]:
        return None, "분개장이 회사 처음부터가 아니라 가수금 잔액을 모름 (작년 분개장도 받아야 함)"
    ym = asof.strftime("%Y-%m")
    return sum(c - d for m, code, name, d, c in L["rows"] if m <= ym and code.startswith(CODE)), ""


def _last_weekday(y, m):
    d = dt.date(y, m, calendar.monthrange(y, m)[1])
    while d.weekday() >= 5:
        d -= dt.timedelta(1)
    return d


def candidates(asof, end):
    fri = asof + dt.timedelta((4 - asof.weekday()) % 7)
    out = [("이번 주 금요일", fri), ("다음 주 금요일", fri + dt.timedelta(7))]
    y, m = asof.year, asof.month
    for i, lab in enumerate(("이번 달 말", "다음 달 말", "다다음 달 말")):
        yy, mm = y + (m - 1 + i) // 12, (m - 1 + i) % 12 + 1
        out.append((lab, _last_weekday(yy, mm)))
    seen, res = set(), []
    for lab, d in out:
        if d < asof or d > end or d in seen:
            continue
        seen.add(d)
        res.append((lab, d))
    return sorted(res, key=lambda x: x[1])


def _end(R):
    s2 = R["s2"]
    asof = R["asof"]
    plan = [e["date"] for e in s2.get("dated") or [] if e.get("source") == "자금계획서"]
    end = max(plan) if plan else asof
    if plan:   # 자금계획서 마지막 달의 끝까지
        end = dt.date(end.year, end.month, calendar.monthrange(end.year, end.month)[1])
    end = max(end, asof + dt.timedelta(MIN_DAYS))
    h = s2.get("horizon")
    return min(end, h) if h else end


def _is_gasu(e):
    t = " ".join(str(e.get(k) or "") for k in ("cat", "desc", "basis"))
    return e.get("io") == "out" and "가수금" in t


def path(R, firm_only, end, pay=None):
    """[(날, 잔액)] asof ~ end. pay=(날, 금액) 이면 그날 그만큼 더 나감."""
    s2 = R["s2"]
    days = collections.defaultdict(int)
    for e in s2.get("dated") or []:
        if firm_only and not e.get("firm"):
            continue
        a = e.get("amount")
        if a is None:
            continue
        days[e["date"]] += a if e["io"] == "in" else -a
    if pay:
        days[pay[0]] -= pay[1]
    bal = s2["start"]   # 2장과 같게: 기준일 앞 날짜 일정은 이미 start 에 들어 있음
    out, d = [], R["asof"]
    while d <= end:
        bal += days.get(d, 0)
        out.append((d, bal))
        d += dt.timedelta(1)
    return out


def _ranges(p, floor):
    rs, s, prev = [], None, None
    for d, b in p:
        if b < floor:
            if s is None:
                s = d
            prev = d
        elif s is not None:
            rs.append((s, prev))
            s = None
    if s is not None:
        rs.append((s, prev))
    return rs


def _look(p, floor):
    d, b = min(p, key=lambda x: x[1])
    return {"low": (d, b), "short": max(0, floor - b), "ranges": _ranges(p, floor)}


def _suffix_min(p):
    out, m = [0] * len(p), None
    for i in range(len(p) - 1, -1, -1):
        m = p[i][1] if m is None else min(m, p[i][1])
        out[i] = m
    return out


def compute(input_dir, R):
    from . import gate
    asof = R["asof"]
    stop = gate.problems(R)
    if stop:
        return {"ok": False, "why": "자금계획서·분개장 미반영이라 계산하지 않음: " + " / ".join(stop)}
    amt, why = balance(input_dir, asof)
    if amt is None:
        return {"ok": False, "why": why}
    s2 = R.get("s2") or {}
    if s2.get("start") is None:
        return {"ok": False, "why": "오늘 통장 잔액을 몰라 날마다 잔액을 계산하지 못함"}
    floor = int(s2.get("min_cash") or 0)
    planned = sum(e.get("amount") or 0 for e in s2.get("dated") or [] if _is_gasu(e))
    rest = max(0, amt - planned)
    end = _end(R)
    G = {"ok": True, "amount": amt, "planned": planned, "rest": rest, "floor": floor, "end": end,
         "sources": gate.sources_line(R), "asof": asof}
    if rest <= 0:
        G["cases"] = []
        return G
    base = {k: path(R, k == "firm", end) for k in ("firm", "all")}
    G["base"] = dict((k, _look(p, floor)) for k, p in base.items())
    cases = []
    for lab, d in candidates(asof, end):
        row = {"label": "오늘 (%s)" % lab if d == asof else lab, "date": d}
        for k in ("firm", "all"):
            p = path(R, k == "firm", end, (d, rest))
            lk = _look(p, floor)
            lk["safe"] = min(b for x, b in p if x >= d) >= floor
            lk["more"] = lk["short"] - G["base"][k]["short"]
            row[k] = lk
        cases.append(row)
    G["cases"] = cases
    # 가장 이른 안전한 날 · 지금 갚아도 되는 금액
    for k, p in base.items():
        sm = _suffix_min(p)
        G["now_" + k] = max(0, sm[0] - floor)
        G["first_" + k] = next((p[i][0] for i in range(len(p)) if sm[i] - rest >= floor), None)
    f = G["first_all"]
    if f and f > asof:   # 그 날을 안전하게 만드는 큰 입금 (그날 앞 7일 안 확정 입금)
        big = collections.OrderedDict()
        for e in sorted(s2.get("dated") or [], key=lambda e: -(e.get("amount") or 0)):
            if e["io"] == "in" and e.get("firm") and f - dt.timedelta(7) <= e["date"] <= f and e.get("amount"):
                big[e.get("desc") or e.get("cat") or ""] = big.get(e.get("desc") or e.get("cat") or "", 0) + e["amount"]
        G["driver"] = (f - dt.timedelta(7), f, list(big.items())[:3], sum(big.values()))
    return G


def for_report(input_dir, R):
    try:
        return compute(input_dir, R)
    except Exception as e:   # 이 장 때문에 보고서를 못 만들면 안 된다
        return {"ok": False, "why": "계산하지 못함 (%s)" % type(e).__name__}


def _eok(v):
    s = "−" if v < 0 else ""
    return "%s%.2f억" % (s, abs(v) / 1e8)


def _md(d):
    return "%d/%d" % (d.month, d.day)


def advice(G):
    """제안 문장들 (정해진 규칙)."""
    if not G or not G.get("ok"):
        return ["자금계획서와 분개장을 받아 ‘자료 변환’을 하면 가수금 갚을 시기를 계산합니다."]
    if G["rest"] <= 0:
        if G["amount"] <= 0:
            return ["남은 가수금이 없습니다 — 할 일 없음."]
        return ["가수금 %s원은 자금계획서에 이미 갚을 날이 잡혀 있어 자금 일정에 들어가 있습니다." % won(G["planned"])]
    out = []
    asof, rest, floor = G["asof"], G["rest"], G["floor"]
    fa, ff = G.get("first_all"), G.get("first_firm")
    if fa == asof:
        out.append("지금 %s원을 전부 갚아도 예상 지급까지 넣어 최소 보유현금 %s 아래로 내려가는 날이 없습니다 → 갚아도 됩니다." % (won(rest), _eok(floor)))
        return out
    early = [c for c in G["cases"] if c["date"] < (fa or dt.date.max) and not c["all"]["safe"]]
    if fa:
        s = "%s 이후에 갚으세요." % _md(fa)
        drv = G.get("driver")
        if drv and drv[2]:
            s += " %s 무렵 들어올 확정 입금(%s, 합 %s원)이 실제로 들어온 것을 확인한 뒤 갚는 것이 안전합니다." % (
                _md(drv[1]), ", ".join(n for n, _ in drv[2]), won(drv[3]))
        out.append(s)
    else:
        out.append("%s까지는 전부 갚아도 안전한 날이 없습니다 → 지금은 갚지 말고 다음 보고에서 다시 보세요." % d2s(G["end"]))
    if early:
        c = early[0]
        r = c["all"]["ranges"]
        out.append("%s(%s)에 갚으면 예상 지급 포함 %s 최소 보유현금보다 최대 %s원 모자랍니다 (갚지 않을 때보다 %s원 더)." % (
            c["label"], _md(c["date"]), ("%s~%s" % (_md(r[0][0]), _md(r[-1][1]))) if r else "",
            won(c["all"]["short"]), won(c["all"]["more"])))
    if ff == asof and fa != asof:
        out.append("확정분만 보면 지금 갚아도 되지만, 급여·카드대금·프로젝트 남은 예산 같은 예상 지급을 넣으면 모자랍니다. 예상 지급 쪽이 실제에 더 가깝습니다.")
    b = G["base"]["all"]
    if b["ranges"]:
        r = b["ranges"]
        out.append("갚지 않아도 예상 지급 포함 %s~%s에 최소 보유현금보다 최대 %s원 모자랍니다 (2장 자금 일정 참고)." % (
            _md(r[0][0]), _md(r[-1][1]), won(b["short"])))
    if G.get("now_all"):
        out.append("나눠 갚는다면 지금 %s원까지는 예상 지급을 넣어도 최소 보유현금이 지켜집니다." % won(min(G["now_all"], rest)))
    return out


EXPLAIN = ("대표이사가 회사에 잠시 넣어 둔 돈(가수금)을 돌려드릴 때, 언제 돌려드려야 회사 통장이 늘 남겨 둘 돈(최소 보유현금)보다 "
           "내려가지 않는지 날짜별로 계산한 곳입니다. 돌려드리면 부채가 줄어 신용평가에는 좋지만, 돈이 모자란 때에 갚으면 지급이 막힐 수 있습니다.")


def render(G):
    h = ["<h2 id='gasu'>B-2-1 가수금 갚을 시기</h2>"]
    if not G or not G.get("ok"):
        h.append("<div class='note'>%s</div>" % esc((G or {}).get("why") or "계산하지 못함"))
        return "".join(h)
    h.append("<div class='meta'>%s · 계산 기간 %s ~ %s · 최소 보유현금 %s원</div>" % (
        esc(G["sources"]), d2s(G["asof"]), d2s(G["end"]), won(G["floor"])))
    h.append("<p>가수금 잔액 <b>%s원</b> (장부, %s 기준)%s.</p>" % (
        won(G["amount"]), d2s(G["asof"]),
        (" · 자금계획서에 이미 잡힌 상환 %s원 · 남은 %s원으로 계산" % (won(G["planned"]), won(G["rest"]))) if G["planned"] else ""))
    if not G["cases"]:
        h.append("<div class='note'>%s</div>" % esc(advice(G)[0]))
        return "".join(h)

    def cell(lk):
        if not lk["ranges"]:
            return "부족 없음 <span class='sub'>(가장 적을 때 %s)</span>" % _eok(lk["low"][1])
        r = lk["ranges"]
        return ("%s 최소 보유현금 아래 · 최저 %s %s <b class='neg'>(%s원 부족)</b>"
                % (esc(", ".join("%s~%s" % (_md(a), _md(b)) for a, b in r)), _md(lk["low"][0]), _eok(lk["low"][1]), won(lk["short"])))
    rows = ["<tr><td>갚지 않음</td><td>—</td><td>%s</td><td>%s</td><td>기준</td></tr>" % (cell(G["base"]["firm"]), cell(G["base"]["all"]))]
    for c in G["cases"]:
        ok = c["all"]["safe"]
        pre = ok and c["all"]["ranges"]   # 안전한데 부족 줄이 보이면: 갚기 전부터 있던 부족
        mark = ("<span class='lt ok'><i></i>안전</span>" + ("<br><span class='sub'>부족은 갚지 않아도 생기는 것</span>" if pre else "")) if ok else (
            "<span class='lt wa'><i></i>확정분만 안전</span>" if c["firm"]["safe"] else "<span class='lt bad'><i></i>모자람</span>")
        rows.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                    % (esc(c["label"]), d2s(c["date"]), cell(c["firm"]), cell(c["all"]), mark))
    h.append("<div class='tw'><table class='pt evt dgx nofold'><thead><tr><th>갚는 때</th><th>날짜</th><th>확정분만</th>"
             "<th>예상 지급 포함</th><th>판정</th></tr></thead><tbody>%s</tbody></table></div>" % "".join(rows))
    h.append("<div class='note'>날마다 잔액은 2장 자금 일정과 같은 숫자입니다(오늘 통장 잔액 + 날짜별 입금 − 출금). "
             "‘안전’은 그날 %s원을 전부 갚아도 그 뒤 계산 기간 안에 최소 보유현금 아래로 내려가는 날이 없다는 뜻입니다. "
             "예상 지급 = 급여·카드대금(장부 계산)·프로젝트 남은 예산 등 날짜·금액이 아직 확정되지 않은 돈.</div>" % won(G["rest"]))
    return "".join(h)
