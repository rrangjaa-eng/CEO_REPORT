"""내년 예산 문서 (대표용·경영관리용). 목업 mockups/예산 과 같은 모양 (사용자 2026-11-10 승인).

노란 칸 ✎ = 사람이 정하는 값 (창 '내년 예산'·'팀 목표'에서 넣음). 넣지 않은 값은 '입력 전'으로 보이고 0%·기본값으로 계산한다.
대표용 = 요약·정할 값·손익·팀별·달별 그림·지급 일정·월별 자금 그림. 경영관리용 = 같은 숫자 + 계산 근거·상세 표·자료 확인.
"""
import re
from . import render as RD
from .util import esc, won

MON = ["%d월" % (i + 1) for i in range(12)]

EXTRA = (".pl td{text-align:right}.pl td:first-child{text-align:left}.pl tr.ind td:first-child{padding-left:16px;color:var(--sub)}"
         "table.pt.r td,table.pt.r th{text-align:right}table.pt.r td:first-child,table.pt.r th:first-child,table.pt.r td.l,table.pt.r th.l{text-align:left}"
         "table.pt.lft td,table.pt.lft th{text-align:left}"
         "td.inp{background:#fff4c2!important;box-shadow:inset 0 0 0 1px #d8b13a;font-weight:700}td.inp::after{content:' ✎';font-weight:400;color:#9a7a10;font-size:10px}"
         "td.inp.none{color:#9a7a10;font-weight:400}"
         "span.inp{background:#fff4c2;box-shadow:inset 0 0 0 1px #d8b13a;padding:0 4px;font-size:11px}"
         ".src{display:inline-block;font-size:10.5px;font-weight:400;color:#5b6475;border:1px solid #c9d0db;border-radius:3px;padding:0 5px;margin-left:8px;vertical-align:middle}"
         ".src.ok{color:#1f6b3a;border-color:#9cc8ab}.src.new{color:#9a5a00;border-color:#e0b878}.src.in{color:#9a7a10;border-color:#d8b13a;background:#fff4c2}"
         ".yl{font-size:12.5px;padding:6px 12px;margin:6px 0 0;border-left:4px solid var(--accent);background:var(--soft);border-radius:4px}"
         "td.neg{color:#c00000}td.lowc{background:#fde8e4!important}.small td,.small th{font-size:11px!important;padding:3px 3px!important}"
         ".legend{font-size:11px;color:#5b6475;margin-top:2px}.legend i{display:inline-block;width:10px;height:10px;margin:0 4px 0 10px;vertical-align:middle}"
         ".note{font-size:11px;color:#5b6475;margin-top:4px}.how{text-align:left!important;font-size:11px;color:#5b6475}"
         "@media print{.fs.mon table.pt{font-size:11.5px}}")


def _pct(a, b):
    return "—" if a is None or not b else "%.1f%%" % (100.0 * a / b)


def _chg(a, b):
    if a is None or not b:
        return "—"
    v = (a - b) * 100.0 / abs(b)
    return ("+" if v >= 0 else "−") + "%.1f%%" % abs(v)


def _sgn(v):
    return "—" if v is None else ("+" if v >= 0 else "−") + "{:,}".format(abs(int(v)))


def _sub(a, b):
    return None if a is None or b is None else a - b


def _card(lab, big, foot):
    return "<div class='card'><div class='lab'>%s</div><div class='big'>%s</div><div class='foot'>%s</div></div>" % (lab, big, foot)


def _inp(text, is_set):
    return "<td class='inp%s'>%s</td>" % ("" if is_set else " none", text if is_set else "입력 전")


def _bars(B):
    rev, teams, T = B["rev"], B["teams"], B["T"]
    got = [sum(T[t]["got"][i] for t in teams) for i in range(12)]
    last = [sum(T[t]["rev26"][i] for t in teams) for i in range(12)]
    Wd, Hc, pl, base = 1100, 210, 62, 170
    mx = max(max(rev), max(last), 1) * 1.1
    step = _step(mx)
    bw = (Wd - pl - 20) / 12.0
    s = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (Wd, Hc + 30)]
    k = 0
    while k * step <= mx:
        y = base - k * step / mx * (base - 20)
        s.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#eef0f4"/><text x="%d" y="%.1f" font-size="11" text-anchor="end" fill="#8a93a3">%s백만</text>'
                 % (pl, Wd - 10, y, y, pl - 4, y + 4, "{:,}".format(int(k * step / 1e6))))
        k += 1
    for i in range(12):
        x = pl + i * bw + bw * .18
        w = bw * .64
        ht = rev[i] / mx * (base - 20)
        hg = got[i] / mx * (base - 20)
        s.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#c9d8ee"/>' % (x, base - ht, w, ht))
        if got[i]:
            s.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#1f4e8c"/>' % (x, base - hg, w, hg))
        ly = base - last[i] / mx * (base - 20)
        s.append('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="#b5523b" stroke-width="2"/>' % (x - 3, x + w + 3, ly, ly))
        s.append('<text x="%.1f" y="%d" font-size="12" text-anchor="middle" fill="#5b6475">%s</text>' % (x + w / 2, base + 16, MON[i]))
        s.append('<text x="%.1f" y="%d" font-size="11" text-anchor="middle" fill="#1d2433">%s</text>' % (x + w / 2, base + 32, "{:,.0f}".format(rev[i] / 1e6)))
    s.append('<text x="0" y="%d" font-size="11" fill="#5b6475">예산(백만)</text></svg>' % (base + 32))
    return "".join(s)


def _step(mx):
    for st in (5e6, 1e7, 2e7, 5e7, 1e8, 2e8, 5e8, 1e9, 2e9, 5e9):
        if mx / st <= 6:
            return st
    return 1e10


def _cash_svg(B):
    c = B["cash"]
    bal, lo, mc = c["bal"], c["lo"], c["min_cash"]
    Wd, Hc, base, pl = 1100, 200, 160, 62
    mx = max(max(bal), mc, 1) * 1.1
    mn = min(min(bal), 0)
    rng = mx - mn
    step = _step(rng)

    def Y(v):
        return base - (v - mn) / rng * (base - 15)
    s = ['<svg viewBox="0 0 %d %d" width="100%%" style="display:block">' % (Wd, Hc)]
    k = int(mn // step)
    while k * step <= mx:
        y = Y(k * step)
        s.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#eef0f4"/><text x="%d" y="%.1f" font-size="11" text-anchor="end" fill="#8a93a3">%s백만</text>'
                 % (pl, Wd - 10, y, y, pl - 4, y + 4, "{:,}".format(int(k * step / 1e6))))
        k += 1
    ym = Y(mc)
    s.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#c00000" stroke-dasharray="5 4"/><text x="%d" y="%.1f" font-size="11" text-anchor="end" fill="#c00000">최소 보유현금 %s</text>'
             % (pl, Wd - 10, ym, ym, Wd - 12, ym - 4, won(mc)))
    bw = (Wd - pl - 20) / 12.0
    pts = []
    for i in range(12):
        cx = pl + i * bw + bw / 2
        pts.append((cx, Y(bal[i])))
        red = i == lo or bal[i] < mc
        s.append('<text x="%.1f" y="%d" font-size="12" text-anchor="middle" fill="#5b6475">%s</text>' % (cx, base + 16, MON[i]))
        s.append('<text x="%.1f" y="%d" font-size="11" text-anchor="middle" fill="%s">%s</text>' % (cx, base + 32, "#c00000" if red else "#1d2433", "{:,.0f}".format(bal[i] / 1e6)))
    s.append('<polyline points="%s" fill="none" stroke="#1f4e8c" stroke-width="2"/>' % " ".join("%.1f,%.1f" % p for p in pts))
    for i, (a, b) in enumerate(pts):
        s.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s" stroke="#fff" stroke-width="2"/>' % (a, b, "#c00000" if (i == lo or bal[i] < mc) else "#1f4e8c"))
    s.append('<text x="0" y="%d" font-size="11" fill="#5b6475">월말(백만)</text></svg>' % (base + 32))
    return "".join(s)


def render_budget(B, mode="ceo", company="", confirmed=None):
    """B = budget.compute(). mode = 'ceo' | 'mgmt'. confirmed = 확정일 글자 (없으면 초안)."""
    mg = mode == "mgmt"
    y, base, T, teams, Y, L, c = B["year"], B["base"], B["T"], B["teams"], B["Y"], B["L"], B["cash"]

    def S(kind, text):
        return " <span class='src %s'>%s</span>" % (kind, text) if mg else ""
    state = "확정 %s" % confirmed if confirmed else "초안"
    h = ["<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>%d년 예산 계획</title><style>%s%s</style></head>"
         % (y, RD.CSS + RD.FS_CSS + RD.DOC_CSS + RD.DOC2_CSS + RD.DOC3_CSS + RD.AIR_CSS + RD.TYPE_CSS, EXTRA)]
    h.append("<body><div class='wrap mon'><div class='doc-h'><h1>%s%d년 예산 계획 (%s)%s</h1>"
             % ("<span class='co'>%s</span>" % esc(company) if company else "", y, state, " · 경영관리용" if mg else ""))
    act = "1~%d월 실적%s" % (B["last_m"], " + %d~12월 예상" % (B["last_m"] + 1) if B["last_m"] < 12 else "") if B["last_m"] else "실적 없음"
    h.append("<table class='dinfo'><tr><th>작성일</th><td>%s</td><th>예산 기간</th><td>%d-01-01 ~ %d-12-31</td></tr>"
             "<tr><th>%d년 숫자</th><td>%s</td><th>금액 단위</th><td>원</td></tr></table>" % (B["asof"].isoformat(), y, y, base, act))
    h.append("<div class='meta dsrc'><span class='inp'>노란 칸 ✎</span> = 사람이 정하는 값 (창 '가끔 넣는 값' → 내년 예산·팀 목표). 나머지는 %d년 장부·인트라넷에서 자동으로 채웠습니다.%s</div></div>"
             % (base, " 절 제목 옆: <span class='src ok'>장부·인트라넷 자료</span><span class='src new'>가정 포함</span><span class='src in'>입력값</span>" if mg else ""))
    h.append("<div class='page fs mon'>")
    # 요약
    h.append("<div class='four top'>")
    h.append(_card("%d년 매출 예산" % y, won(Y["rev"]), "%d년 %s 대비 %s" % (base, won(L["rev"]), _chg(Y["rev"], L["rev"]))))
    h.append(_card("영업이익 예산", won(Y["op"]), "영업이익률 %s · %d년 %s" % (_pct(Y["op"], Y["rev"]), base, won(L["op"]))))
    # 법인세는 다음 해 3월, 지방세는 4월에 낸다. 8월 중간예납은 이미 낸 몫이라 빼고 보인다 (2026-11-14 오후 점검 G3)
    mid = sum(f["amount"] for f in B["fix"] if f["day"] == "8/31" and "중간예납" in f["name"])
    tax_foot = "법인세·지방세 예상 %s" % won(Y["tax"])
    if Y["tax"] is not None:
        tax_foot += " → %d년 3월·4월에 %s 납부%s" % (y + 1, won(max(Y["tax"] - mid, 0)), " (8월 중간예납 %s 뺌)" % won(mid) if mid else "")
    h.append(_card("세전 이익 예산", won(Y["pre"]), tax_foot))
    if c["lo"] is not None:
        lo, mc = c["lo"], c["min_cash"]
        diff = c["bal"][lo] - mc
        h.append(_card("가장 적은 월말 통장", won(c["bal"][lo]), "%d월 · 최소 보유현금보다 %s" % (lo + 1, ("%s 많음" % won(diff)) if diff >= 0 else "<b style='color:#c00000'>%s 모자람</b>" % won(-diff))))
    else:
        h.append(_card("가장 적은 월말 통장", "미확인", "최신 자금계획서·분개장이 없어 비움" if B.get("blocked") else "통장 잔액·급여 자료 필요"))
    h.append("</div>")
    gt = sum(T[t]["got_sum"] for t in teams)
    cash_line = ""
    if c["lo"] is not None:
        below = [i + 1 for i in range(12) if c["bal"][i] < c["min_cash"]]
        # 월말 잔액 12개만 보므로 '매달 말 잔액 기준'으로 한정한다 (2026-11-14 오후 점검 G6: 월 중간에 급여·세금이 먼저 나가면
        # 그사이엔 모자랄 수 있고, 새로 받아야 할 매출도 들어온다고 본 숫자)
        cash_line = ("계획한 매출이 들어오면 매달 말 잔액 기준으로 통장이 최소 보유현금 위에 있습니다." if not below else
                     "<b style='color:#c00000'>매달 말 잔액 기준 %s 통장이 최소 보유현금 아래로 내려갑니다.</b>" % ", ".join("%d월" % m for m in below))
    h.append("<div class='yl'>매출 예산 중 <b>%s (%s)</b>는 이미 받은 일입니다. 나머지 <b>%s</b>를 새로 받아야 합니다. %s</div>"
             % (won(gt), _pct(gt, Y["rev"]), won(Y["rev"] - gt), cash_line))
    if B["missing"]:
        h.append("<div class='note' style='color:#9a5a00'>입력 전: %s — 넣기 전에는 성장률 0%%, 목표 수익률은 기본 원가율 설정으로 계산했습니다.</div>"
                 % ", ".join(B["missing"]))
    # 1. 정할 값
    h.append("<div class='sec'><div class='q'>1. 정해야 할 값%s</div>" % S("in", "입력값"))
    cols = "".join("<th>%s</th>" % esc(t) for t in teams)
    h.append("<div class='card'><table class='pt r'><thead><tr><th>항목</th>%s<th>회사 전체</th>%s</tr></thead><tbody>"
             % (cols, "<th class='l'>근거</th>" if mg else ""))
    blank = "<td></td>" * len(teams)
    h.append("<tr><td>매출 성장률</td>%s<td>%s</td>%s</tr>" % ("".join(_inp("%+g%%" % T[t]["growth"], T[t]["growth_set"]) for t in teams),
             _chg(Y["rev"], L["rev"]), "<td class='how'>%d년 팀 매출 %s 기준</td>" % (base, act) if mg else ""))
    h.append("<tr><td>목표 수익률</td>%s<td>%s</td>%s</tr>" % ("".join(_inp("%g%%" % round(T[t]["rate"] * 100, 1), T[t]["rate_set"]) for t in teams),
             _pct(Y["gp"], Y["rev"]), "<td class='how'>%d년 실제 %s (창 '팀 목표'의 %d년 값)</td>" % (base, " / ".join(_pct(T[t]["base_gp"], T[t]["base_rev"]) for t in teams), y) if mg else ""))
    hire_cells = []
    for t in teams:
        n0 = B["heads0"].get(t, 0)
        n, m = B["hires"].get(t, (0, None))
        hire_cells.append(_inp("%d → %d명%s" % (n0, n0 + n, " (%d월 입사)" % m if n else ""), True))
    h.append("<tr><td>인원 (%d년 말 → %d년 말)</td>%s<td>%d → %d명</td>%s</tr>" % (base, y, "".join(hire_cells), sum(B["heads0"].values()) - sum(n for n, _ in B["hires"].values()),
             B["heads"][-1], "<td class='how'>팀 아닌 부서 포함 (%s 급여 기준)</td>" % (B["last_ym"] or "자료 없음") if mg else ""))
    h.append("<tr><td>급여 인상률</td>%s%s%s</tr>" % (blank, _inp("%+g%% (1월부터)" % (B["raise"] or 0), B["raise"] is not None),
             "<td class='how'>새 사람 급여 = 지금 1인 평균 × 인상률</td>" if mg else ""))
    h.append("<tr><td>판관비 물가 인상률</td>%s%s%s</tr>" % (blank, _inp("%+g%%" % (B["infl"] or 0), B["infl"] is not None),
             "<td class='how'>임차료·보험료는 그대로, 나머지 판관비에 적용</td>" if mg else ""))
    h.append("</tbody></table></div></div>")
    # 2. 손익 예산
    h.append("<div class='sec'><div class='q'>2. 손익 예산 (위하고 손익계산서 순서)%s</div>" % S("ok", "분개장"))
    h.append("<div class='card'><table class='pt pl'><thead><tr><th>항목</th><th>%d년 (실적+예상)</th><th>%d년 예산</th><th>증감</th><th>증감률</th>%s</tr></thead><tbody>"
             % (base, y, "<th style='text-align:left'>%d년 예산 계산</th>" % y if mg else ""))
    PL = [("매출", "rev", "", "팀별 %d년 매출 × (1 + 성장률)" % base), ("매출원가", "cogs", "ind", "팀별 매출 × (1 − 목표 수익률)"),
          ("매출총이익", "gp", "tot", "매출 − 매출원가"), ("급여", "sal", "ind", "지금 1달 급여 × (1 + 인상률) × 12 + 새 인원"),
          ("감가상각비", "dep", "ind", "%d년 예상 (%s)" % (base, B["dep_src"] or "모름")), ("그 밖의 판관비", "sga", "ind", "계정별 %d년 실적 × 인원·물가" % base),
          ("영업이익", "op", "tot", ""), ("영업외 수익", "nin", "ind", "이자수익만 (지원금 등은 확정 전이라 뺌)"),
          ("영업외 비용", "nout", "ind", "%d년 실적을 1년으로 늘림" % base), ("세전 이익", "pre", "tot", ""),
          ("법인세 (지방세 포함, 예상)", "tax", "ind", "세전 이익 기준 세율표, 세무조정 없음")]
    for nm, k, cls, how in PL:
        a, b = L[k], Y[k]
        h.append("<tr class='%s'><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>%s</tr>"
                 % (cls, nm, won(a), won(b), _sgn(_sub(b, a)), _chg(b, a), "<td class='how'>%s</td>" % how if mg else ""))
    h.append("</tbody></table></div></div>")
    # 3. 팀별 매출·원가
    h.append("<div class='sec pgb'><div class='q'>3. 팀별 매출·원가 예산%s</div>" % S("ok", "손익 팀 줄 + 인트라넷 사전견적"))
    h.append("<div class='card'><table class='pt r'><thead><tr><th>팀</th><th>%d년 매출</th><th>성장률</th><th>%d년 매출 예산</th><th>이미 받은 일</th><th>새로 받을 일</th><th>목표 수익률</th><th>매출총이익</th><th>매출원가 (추정 예산)</th></tr></thead><tbody>" % (base, y))
    for t in teams:
        R = T[t]
        h.append("<tr><td>%s</td><td>%s</td>%s<td>%s</td><td>%s</td><td>%s</td>%s<td>%s</td><td>%s</td></tr>"
                 % (esc(t), won(R["base_rev"]), _inp("%+g%%" % R["growth"], R["growth_set"]), won(R["budget"]), won(R["got_sum"]),
                    won(R["budget"] - R["got_sum"]), _inp("%g%%" % round(R["rate"] * 100, 1), R["rate_set"]), won(sum(R["gp"])), won(sum(R["cogs"]))))
    h.append("<tr class='tot'><td>합계</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr></tbody></table>"
             % (won(L["rev"]), _chg(Y["rev"], L["rev"]), won(Y["rev"]), won(gt), won(Y["rev"] - gt), _pct(Y["gp"], Y["rev"]), won(Y["gp"]), won(Y["cogs"])))
    h.append("<div class='note'>매출원가 = 매출 × (1 − 팀 목표 수익률). 프로젝트 '추정 예산'과 같은 기준입니다.</div>")
    h.append("<div class='wsub'>달별 매출 예산</div>%s<div class='legend'><i style='background:#1f4e8c'></i>이미 받은 일<i style='background:#c9d8ee'></i>새로 받을 일"
             "<i style='background:#b5523b;height:2px'></i>%d년 같은 달 매출</div>" % (_bars(B), base))
    h.append("<div class='note'>달별 나눔 = %s. 이미 받은 일이 그보다 큰 달은 받은 일 금액으로 올리고 다른 달을 줄였습니다.</div></div>" % esc(B["seas_src"]))
    if mg:
        mt = ["<div class='card' style='margin-top:8px'><div class='wsub' style='margin-top:0'>팀별·달별 매출 예산 (백만 원)</div><table class='pt r small'><thead><tr><th>팀</th>%s<th>합계</th></tr></thead><tbody>"
              % "".join("<th>%s</th>" % m for m in MON)]
        for t in teams:
            R = T[t]
            mt.append("<tr><td>%s</td>%s<td>%s</td></tr>" % (esc(t), "".join("<td>%s</td>" % (("<b>%.0f</b>" if R["got"][i] else "%.0f") % (v / 1e6)) for i, v in enumerate(R["rev"])),
                                                         "{:,.0f}".format(R["budget"] / 1e6)))
            mt.append("<tr><td style='padding-left:14px;color:#5b6475'>└ 이미 받은 일</td>%s<td>%s</td></tr>"
                      % ("".join("<td style='color:#5b6475'>%s</td>" % ("%.0f" % (v / 1e6) if v else "") for v in R["got"]), "{:,.0f}".format(R["got_sum"] / 1e6)))
        mt.append("<tr class='tot'><td>합계</td>%s<td>%s</td></tr><tr><td style='color:#5b6475'>계절 비중</td>%s<td>100%%</td></tr></tbody></table>"
                  % ("".join("<td>%.0f</td>" % (v / 1e6) for v in B["rev"]), "{:,.0f}".format(Y["rev"] / 1e6), "".join("<td style='color:#5b6475'>%.1f%%</td>" % (v * 100) for v in B["seas"])))
        mt.append("<div class='wsub'>이미 받은 %d년 행사 (인트라넷 사전견적)</div><table class='pt r'><thead><tr><th>팀</th><th class='l'>프로젝트</th><th>행사 월</th><th>사전견적</th><th>추정 예산</th></tr></thead><tbody>" % y)
        for g in B["got"]:
            mt.append("<tr><td>%s</td><td class='l'>[%s] %s</td><td>%d월</td><td>%s</td><td>%s</td></tr>"
                      % (esc(g["team"]), esc(g["id"]), esc(g["name"]), g["month"], won(g["estimate"]), won(int(g["estimate"] * (1 - T[g["team"]]["rate"])))))
        if not B["got"]:
            mt.append("<tr><td colspan='5' class='l'>아직 없음</td></tr>")
        mt.append("<tr class='tot'><td>합계</td><td class='l'>%d건</td><td></td><td>%s</td><td>%s</td></tr></tbody></table></div>"
                  % (len(B["got"]), won(gt), won(sum(int(g["estimate"] * (1 - T[g["team"]]["rate"])) for g in B["got"]))))
        h.append("".join(mt))
    h.append("</div>")
    # 4. 급여·판관비 (경영관리용)
    n = 4
    if mg:
        h.append("<div class='sec pgb'><div class='q'>%d. 급여·판관비 예산%s</div>" % (n, S("ok", "%s·계정별비용" % ("위하고 급여 화면" if B.get("sal_src", "").startswith("위하고") else "부서비용"))))
        h.append("<div class='card'><div class='wsub' style='margin-top:0'>인원 계획 (%s 급여, %s)</div><table class='pt r'><thead><tr><th>부서</th><th>%d년 말</th><th>%d년 늘림</th><th>입사 월</th><th>%d년 말</th><th>1년 평균</th></tr></thead><tbody>"
                 % (B["last_ym"] or "자료 없음", "위하고 사원등록 부서 기준" if B.get("sal_src", "").startswith("위하고") else "급여 전표 부서명 기준", base, y, y))
        for dname, n0 in B["heads0"].items():
            add, mo = B["hires"].get(dname, (0, None))
            avg = n0 + (add * (13 - mo) / 12.0 if add else 0)
            is_team = dname in teams
            h.append("<tr><td>%s</td><td>%d명</td>%s%s<td>%d명</td><td>%.2f명</td></tr>"
                     % (esc(dname), n0, _inp("%+d명" % add, True) if is_team else "<td>0명</td>",
                        _inp("%d월" % mo, True) if add else "<td>—</td>", n0 + add, avg))
        h0 = sum(B["heads0"].values())
        h.append("<tr class='tot'><td>합계</td><td>%d명</td><td>%+d명</td><td></td><td>%d명</td><td>%.2f명</td></tr></tbody></table>" % (h0, B["heads"][-1] - h0, B["heads"][-1], B["havg"]))
        rz = (B["raise"] or 0) / 100.0
        if B["sal_last"] is not None:
            now_sal = int(round(B["sal_last"] * (1 + rz))) * 12
            h.append("<div class='wsub'>급여</div><table class='pt r'><thead><tr><th>구분</th><th>%d년</th><th>%d년 예산</th><th class='l'>계산</th></tr></thead><tbody>"
                     "<tr><td>지금 인원 급여</td><td>%s</td><td>%s</td><td class='l'>월 %s (%s) × (1 + %g%%) × 12</td></tr>"
                     "<tr><td>새 인원 급여</td><td>—</td><td>%s</td><td class='l'>1인 평균 월 %s × (1 + %g%%) × 입사 월부터</td></tr>"
                     "<tr class='tot'><td>급여 합계</td><td>%s</td><td>%s</td><td class='l'>%s</td></tr></tbody></table>"
                     % (base, y, won(L["sal"]), won(now_sal), won(B["sal_last"]), B["last_ym"], B["raise"] or 0,
                        won(Y["sal"] - now_sal), won(int(B["per"] or 0)), B["raise"] or 0, won(L["sal"]), won(Y["sal"]), _chg(Y["sal"], L["sal"])))
        h.append("<div class='wsub'>그 밖의 판관비 (계정별, 급여·감가상각비 뺌)</div><table class='pt r'><thead><tr><th>계정</th><th>%d년 (1년으로)</th><th class='l'>잡는 기준</th><th>%d년 예산</th><th>증감</th></tr></thead><tbody>" % (base, y))
        for x in B["SGA"]:
            h.append("<tr><td>%s</td><td>%s</td><td class='l'>%s</td><td>%s</td><td>%s</td></tr>" % (esc(x["name"]), won(x["base"]), esc(x["how"]), won(x["budget"]), _chg(x["budget"], x["base"])))
        if not B["SGA"]:
            h.append("<tr><td colspan='5' class='l'>계정별비용 자료 없음</td></tr>")
        h.append("<tr class='tot'><td>합계</td><td>%s</td><td></td><td>%s</td><td>%s</td></tr></tbody></table>" % (won(L["sga"]), won(Y["sga"]), _chg(Y["sga"], L["sga"])))
        h.append("<div class='note'>%d년 실적이 1년이 안 되면 달 수로 나눠 12달로 늘렸습니다. 인원 비례 = 복리후생비·여비교통비·통신비 등.</div></div></div>" % base)
        n += 1
    # 정해진 지급 일정
    h.append("<div class='sec'><div class='q'>%d. 정해진 지급 일정%s</div>" % (n, S("ok", "세금예상 + 자금일정·자금계획서%s + 예산 숫자" % (" + 차입금현황" if any(f.get("src") == "차입금현황 + 장부" for f in B["fix"]) else ""))))
    h.append("<div class='card'><table class='pt r'><thead><tr><th class='l'>날짜</th><th class='l'>항목</th><th>금액</th>%s</tr></thead><tbody>"
             % ("<th class='l'>계산</th><th class='l'>자료</th>" if mg else ""))
    for f in B["fix"]:
        h.append("<tr><td class='l'>%s</td><td class='l'>%s</td><td>%s</td>%s</tr>" % (f["day"], esc(f["name"]), won(f["amount"]),
                 ("<td class='how'>%s</td><td class='how'>%s</td>" % (esc(f["how"]), esc(f["src"]))) if mg else ""))
    if B["Y"]["dep"] is not None and mg:   # 돈이 안 나가는 비용이라 대표용 지급 목록에선 뺌 (7절), 경영관리는 그대로
        h.append("<tr><td class='l'>매달</td><td class='l'>감가상각비 (비용만, 돈은 안 나감)</td><td>%s</td>%s</tr>"
                 % (won(B["dep"][0]), "<td class='how'>연 %s ÷ 12</td><td class='how'>%s</td>" % (won(B["Y"]["dep"]), esc(B["dep_src"])) if mg else ""))
    h.append("</tbody></table></div></div>")
    n += 1
    # 월별 자금
    h.append("<div class='sec pgb'><div class='q'>%d. 월별 자금 계획 (최소 보유현금 확인)%s</div>" % (n, S("new", "회수·지급 시점 가정")))
    if c["lo"] is None:
        h.append("<div class='card'><div class='note'>%s</div></div></div>" % (
            "최신 자금계획서·분개장이 없어 월별 통장 잔액 숫자를 비웠습니다 (틀린 숫자를 보이지 않으려는 것)." if B.get("blocked")
            else "통장 잔액 또는 급여 자료가 없어 만들지 못했습니다."))
    else:
        h.append("<div class='card'><div class='wsub' style='margin-top:0'>월말 통장 잔액 예상 (사용할 수 있는 돈)</div>%s" % _cash_svg(B))
        if mg:
            ct = ["<table class='pt r small' style='margin-top:6px'><thead><tr><th>월</th><th>월초</th><th>매출 입금</th><th>매입 지급</th><th>급여</th><th>판관비</th><th>세금</th><th>대출 원금 등</th><th>영업외</th><th>월말</th><th>최소 보유현금 위</th></tr></thead><tbody>"]
            bb = c["start"]
            for i in range(12):
                ct.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>−%s</td><td>−%s</td><td>−%s</td><td>%s</td><td>%s</td><td>%s</td><td><b>%s</b></td><td class='%s'>%s</td></tr>"
                          % (MON[i], won(bb), won(c["cin"][i]), won(c["cpay"][i]), won(B["sal"][i]), won(c["sga_pay"][i]),
                             ("−" + won(c["tax"][i])) if c["tax"][i] else "—", ("−" + won(c["fixed"][i])) if c["fixed"][i] else "—",
                             _sgn(c["nio"][i]) if c["nio"][i] else "—", won(c["bal"][i]),
                             "lowc" if (i == c["lo"] or c["bal"][i] < c["min_cash"]) else "", _sgn(c["bal"][i] - c["min_cash"])))
                bb = c["bal"][i]
            ct.append("<tr class='tot'><td>1년</td><td>%s</td><td>%s</td><td>−%s</td><td>−%s</td><td>−%s</td><td>−%s</td><td>−%s</td><td>%s</td><td>%s</td><td></td></tr></tbody></table>"
                      % (won(c["start"]), won(sum(c["cin"])), won(sum(c["cpay"])), won(Y["sal"]), won(sum(c["sga_pay"])), won(sum(c["tax"])), won(sum(c["fixed"])),
                         _sgn(sum(c["nio"])) if sum(c["nio"]) else "—", won(c["bal"][-1])))
            if c["days_used"] == c["days"]:
                dtext = "%d년 계산서 %d건 평균 %.0f일" % (base, c["n_days"], c["days"])
            else:
                dtext = "회사 기준 작성일 뒤 %d일%s" % (c["days_used"], (" (입금된 계산서 %d건 평균 %.0f일은 건수가 적어 쓰지 않음)" % (c["n_days"], c["days"]))
                                                   if c["days"] is not None else " (입금된 계산서 자료 없음)")
            if c.get("avail0") is not None:
                start_text = "%s 쓸 수 있는 돈 %s (은행 잔액 날짜 뒤 통장 입출금 반영, 사용 제한 뺌, 주간 보고와 같은 값)" % (B["asof"].isoformat(), won(c["avail0"]))
            else:
                start_text = "%s 장부 통장 잔액 %s − 사용 제한 %s" % (c["bal_date"].isoformat() if c["bal_date"] else "-", won(c["bal0"]), won(c["restricted"]))
            ct.append("<div class='note'>1월 월초 = %s%s (1월에 실제 잔액으로 바꿈). 매출 입금 = 매출 × 1.1을 회수 기간(%s)만큼 늦춰 받음. "
                      "매입 지급 = 매출원가 × 1.1을 행사 달 40%%·다음 달 60%% (가정). 1~2월 입금에는 %d년 말 매출, 1월 지급에는 %d년 12월 매입이 들어 있습니다. 판관비 지급 = 판관비 × 1.05. "
                      "대출 원금 등 = 자금일정·자금계획서의 %d년 대출 원금·보증금·설비 지급.</div>"
                      % (start_text,
                         (" %s 연말까지 들어오고 나갈 돈 예상 %d건 %s" % ("+" if c.get("roll", 0) >= 0 else "−", c.get("roll_n", 0), won(abs(c.get("roll", 0)))))
                         if c.get("roll_n") else "", dtext, base, base, y))
            h.append("".join(ct))
        else:
            lo = c["lo"]
            h.append("<div class='note'>연초 %s → 연말 %s. 가장 적은 달 %d월 %s%s.</div>"
                     % (won(c["start"]), won(c["bal"][-1]), lo + 1, won(c["bal"][lo]),
                        (" (그달 세금 %s)" % won(c["tax"][lo])) if c["tax"][lo] else ""))
        h.append("</div></div>")
    # 자료 확인 (경영관리용)
    if mg:
        n += 1
        h.append("<div class='sec'><div class='q'>%d. 쓴 자료 · 확인할 것</div><div class='card'><table class='pt lft'><thead><tr><th>항목</th><th>쓴 자료</th><th>상태</th></tr></thead><tbody>" % n)
        rows = [("%d년 팀 매출·원가" % base, "손익.csv 팀 줄 (%s)" % (B["src"] or "없음"), act),
                ("남은 달 매출", "인트라넷 프로젝트 사전견적 − 매출 반영 (행사 월)", "예상"),
                ("달별 나눔", B["seas_src"], ""),
                ("이미 받은 %d년 일" % y, "인트라넷 프로젝트 (행사일이 %d년)" % y, "%d건" % len(B["got"])),
                ("목표 수익률", "팀목표.csv %d년" % y, "입력 전 팀 있음" if any(not T[t]["rate_set"] for t in teams) else "입력됨"),
                ("성장률·인원·인상률", "예산값.csv %d년" % y, "입력 전: " + ", ".join(B["missing"]) if B["missing"] else "입력됨"),
                ("급여·인원", "%s (%s)" % (B.get("sal_src") or "부서비용.csv", B["last_ym"] or "없음"), ""),
                ("판관비 계정별", "계정별비용.csv", "%d개 계정" % len(B["SGA"])),
                ("감가상각비", B["dep_src"] or "모름", ""),
                ("세금 일정", "세금예상.csv + 예산 숫자", ""),
                ("통장 잔액", "장부잔액 (%s)" % (c["bal_date"].isoformat() if c["bal_date"] else "없음"), "1월에 실제로 바꿈")]
        for a, b, s in rows:
            h.append("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (esc(a), esc(b), esc(s)))
        h.append("</tbody></table>")
        for x in B["notes"]:
            h.append("<div class='note' style='color:#9a5a00'>· %s</div>" % esc(x))
        h.append("</div></div>")
    h.append("<div class='evid'>%s<span class='doc-end'>끝.</span></div></div></div></body></html>"
             % ("확정 %s — 월간 보고 '예산 대비'에 쓰입니다." % confirmed if confirmed else "초안 — 창에서 '예산 확정'을 누르면 월간 보고 '예산 대비'에 쓰입니다."))
    page = "".join(h)
    return _areas(page) if mg else page


def _areas(page):
    """경영관리용 영역별 보기 (사용자 2026-11-11: 예산 문서도 주간·월간 경영관리 보고처럼).
    요약 카드 + 1절 = 첫 영역, 나머지 절마다 한 영역. 절(div.sec)은 서로 형제라 그 앞에서 자르면 덩어리마다 닫힌 HTML."""
    from . import areas
    start = "<div class='page fs mon'>"
    i = page.index(start) + len(start)
    j = page.rindex("<div class='evid'>")
    head, body, tail = page[:i], page[i:j], page[j:]
    cuts = [m.start() for m in re.finditer(r"<div class='sec[ '\"]", body)]
    if len(cuts) < 2:
        return page
    chunks = [body[:cuts[1]]] + [body[a:b] for a, b in zip(cuts[1:], cuts[2:] + [len(body)])]
    chunks[-1] += tail[:tail.rindex("</div></div></body></html>")]   # 끝. 표시는 마지막 영역에
    labels = []
    for n, c in enumerate(chunks):
        q = re.search(r"<div class='q'>(.*?)</div>", c, re.S)
        t = re.sub(r"<span class='src.*?</span>|<[^>]+>|\s*\(.*?\)", "", q.group(1)).strip() if q else "%d" % n   # 목록엔 괄호 풀이 뺌
        labels.append("요약 · " + t if n == 0 else t)
    keys = ["b%d" % n for n in range(len(chunks))]
    parts = []
    for n, c in enumerate(chunks):
        prev = (keys[n - 1], labels[n - 1]) if n else None
        nxt = (keys[n + 1], labels[n + 1]) if n + 1 < len(chunks) else None
        from . import digest   # 쉬운 설명 · 제안 상자 (사용자 2026-11-13)
        parts.append(areas.section(keys[n], labels[n], digest.budget_box(labels[n]) + "<div class='fs mon'>%s</div>" % c + areas.pager(prev, nxt), "예산"))
        if n == 0:
            parts.append(areas.nav([(k, l, "예산", None) for k, l in zip(keys, labels)]))
    # 요약 영역을 담던 div.page.fs 는 비워 닫는다 (쪽 나눔은 절의 pgb 가 그대로 맡음)
    return head[:-len(start)] + "".join(parts) + "</div>" + areas.JS + "</body></html>"
