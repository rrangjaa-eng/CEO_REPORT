"""팀장용 월간 실적 문서 (사용자 2026-11-05 목업, 2026-11-09 승인).

대표가 아니라 그 팀 팀장이 보는 문서: 그 팀 숫자만, 회사 문서 모양(제목·수신/작성 표·격자 표·단위 원·음수 △·- 끝 -).
- 급여 금액은 어디에도 쓰지 않는다. 판관비는 급여를 뺀 팀 판관비만, '팀 급여 제외'를 문서 위·표 제목·작성 기준에 적는다.
- 급여 반영 손익(매출총이익 − 판관비 − 급여)은 금액 없이 흑자/적자로만, 설정.csv '팀장용_급여반영손익' = 표시 일 때만 (기본 숨김).
- 수익률 = 매출총이익 ÷ 매출 (판관비 빼기 전). 매출·매출원가는 손익.csv WEHAGO 팀 줄(분개장 부서명, 전표일자 기준).
- 프로젝트별은 손익.csv WEHAGO 프로젝트 줄을 프로젝트 목록의 팀으로 묶는다. 팀 합계와 다르면 그 차이를 한 줄로 따로 보인다.
- 진행·예정 프로젝트: 사전견적 · 추정 예산(팀 목표 수익률 기준, calc) · 집행액 · 잔여(추정 예산 − 집행액). 원가율 숫자는 쓰지 않는다.
- 문서에 자료 출처(위하고·분개장 등)는 쓰지 않는다 (사용자 2026-11-05).
모르는 값은 0이 아니라 '미확인'.
"""
import datetime as dt
import html
import os
import re

from .calc import DONE_STATES, _event_date

NET_SETTING = "팀장용_급여반영손익"   # '표시' 이면 급여 반영 손익(흑자/적자) 줄·칸을 보인다 (사용자 2026-11-05 보류)
LOW_GAP = 4.0   # 누계 프로젝트 수익률이 팀 목표 수익률보다 이만큼(%p) 이상 낮으면 밑줄


def esc(v):
    return html.escape("" if v is None else str(v))


def W(v):
    """원 단위 금액. None 은 미확인, 음수는 △."""
    if v is None:
        return "미확인"
    s = "{:,}".format(abs(int(round(v))))
    return ("△" + s) if v < 0 else s


def P(a, b):
    if a is None or b is None:
        return "미확인"
    return "-" if not b else "%.1f%%" % (a * 100.0 / b)


def _sub(a, b):
    return None if a is None or b is None else a - b


def _sum(vals):
    vals = list(vals)
    return None if any(v is None for v in vals) else sum(vals)


def _months(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return ["%04d-%02d" % (y, i) for i in range(1, m + 1)]


def _prev(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return "%04d-%02d" % ((y, m - 1) if m > 1 else (y - 1, 12))


def _mlabel(ym):
    return "%d월" % int(ym[5:7])


def _pid(target):
    """손익.csv 프로젝트 줄의 대상 'P26201 A사 연례 컨퍼런스' -> 'P26201'. 미연결 줄은 None."""
    t = (target or "").strip()
    if not t or "미연결" in t:
        return None
    return t.split()[0]


def team_names(d):
    """보고서를 만들 팀: 손익.csv WEHAGO 팀 줄과 부서비용.csv 의 '…팀' 부서 (팀 미지정 등 제외), 이름순."""
    names = set()
    for r in d.pl or []:
        if r["source"] == "WEHAGO" and r["unit"] == "팀":
            names.add((r["target"] or "").strip())
    for r in d.dept or []:
        names.add((r["dept"] or "").strip())
    return sorted(n for n in names if n.endswith("팀") and n not in ("팀 미지정", "팀 미확인"))


def build(d, R, team):
    """팀 하나의 숫자 묶음. R 은 calc.compute(…, 'monthly', …) 결과."""
    ym = R["s4"]["ym"]
    year = ym[:4]
    months = _months(ym)
    pl = [r for r in (d.pl or []) if r["source"] == "WEHAGO" and r["ym"][:4] == year]
    company_months = set(r["ym"] for r in pl if r["unit"] == "회사")

    def team_cell(m, key):
        rows = [r for r in pl if r["unit"] == "팀" and r["ym"] == m and (r["target"] or "").strip() == team]
        if rows:
            return _sum(r[key] for r in rows)
        return 0 if m in company_months else None   # 회사 줄이 있는 달에 팀 줄이 없으면 그 달 팀 전표 없음

    dept = [r for r in (d.dept or []) if r["dept"] == team]
    dept_months = set(r["ym"] for r in (d.dept or []))

    def dept_cell(m, key):
        rows = [r for r in dept if r["ym"] == m]
        if rows:
            return _sum(r[key] for r in rows)
        return 0 if (key != "heads" and m in dept_months) else None

    M = []
    for m in months:
        rev, cost = team_cell(m, "revenue"), team_cell(m, "direct")
        gp = _sub(rev, cost)
        sga = dept_cell(m, "sga") if d.dept is not None else None
        sal = dept_cell(m, "salary") if d.dept is not None else None
        op = _sub(gp, sga)
        M.append({"ym": m, "revenue": rev, "cost": cost, "gp": gp, "sga": sga, "op": op,
                  "net": _sub(op, sal), "heads": dept_cell(m, "heads") if d.dept is not None else None})
    tot = {k: _sum(x[k] for x in M) for k in ("revenue", "cost", "gp", "sga", "op", "net")}
    hs = [x["heads"] for x in M]
    tot["heads"] = None if any(h is None for h in hs) else sum(hs) / float(len(hs))
    cum, run = [], 0
    for x in M:
        run = None if run is None or x["gp"] is None else run + x["gp"]
        cum.append(run)

    tg = (getattr(d, "team_targets", None) or {}).get((year, team)) or {}
    t_rev = tg.get("revenue")
    t_rate = tg.get("rate")
    t_gp = None if t_rev is None or t_rate is None else int(round(t_rev * t_rate / 100.0))

    comp = [r for r in pl if r["unit"] == "회사" and r["ym"] in months]
    c_rev, c_cost = _sum(r["revenue"] for r in comp), _sum(r["direct"] for r in comp)
    company_rate = None if not comp or c_rev in (None, 0) or c_cost is None else (c_rev - c_cost) * 100.0 / c_rev

    projects = d.projects or {}
    per = {}
    for r in pl:
        if r["unit"] != "프로젝트" or r["ym"] not in months:
            continue
        pid = _pid(r["target"])
        if pid is None or (projects.get(pid, {}).get("team") or "").strip() != team:
            continue
        per.setdefault(pid, {}).setdefault(r["ym"], [0, 0])
        c = per[pid][r["ym"]]
        c[0] = None if c[0] is None or r["revenue"] is None else c[0] + r["revenue"]
        c[1] = None if c[1] is None or r["direct"] is None else c[1] + r["direct"]

    def prow(pid, sel):
        p = projects.get(pid, {})
        cells = [v for m, v in per[pid].items() if m in sel]
        rev, cost = _sum(c[0] for c in cells), _sum(c[1] for c in cells)
        used = sorted(m for m, v in per[pid].items() if m in sel and (v[0] or v[1]))
        span = "" if not used else (_mlabel(used[0]) if used[0] == used[-1] else "%s~%s" % (_mlabel(used[0]), _mlabel(used[-1])))
        return {"id": pid, "name": p.get("name", ""), "client": p.get("client", ""), "event": p.get("event_date", ""),
                "months": span, "revenue": rev, "cost": cost, "gp": _sub(rev, cost)}

    def ev_key(r):
        e = _event_date(r["event"])
        return (e or dt.date.max, r["id"])

    cur = sorted([prow(pid, {ym}) for pid in per if ym in per[pid]], key=ev_key)
    cur = [r for r in cur if r["revenue"] or r["cost"]]
    ytd = sorted([prow(pid, set(months)) for pid in per], key=ev_key)
    ytd = [r for r in ytd if r["revenue"] or r["cost"]]

    def gap(rows, rev, cost):
        if rev is None or cost is None:
            return None
        pr, pc = _sum(r["revenue"] for r in rows), _sum(r["cost"] for r in rows)
        if pr is None or pc is None:
            return None
        g = {"revenue": rev - pr, "cost": cost - pc}
        g["gp"] = g["revenue"] - g["cost"]
        return g if (g["revenue"] or g["cost"]) else None

    last = M[-1]
    cur_gap = gap(cur, last["revenue"], last["cost"])
    ytd_gap = gap(ytd, tot["revenue"], tot["cost"])

    recognized = set(pid for pid in per if any(v[0] for v in per[pid].values()))
    up = []
    for P_ in R["s3"]["projects"]:
        if (P_.get("team") or "").strip() != team or (P_.get("state") or "").strip() in DONE_STATES:
            continue
        if P_["id"] in recognized or P_.get("recognized"):
            continue
        e = _event_date(P_.get("event_date"))
        if e is None or str(e.year) != year:
            continue
        paid = P_.get("paid_total")
        up.append({"id": P_["id"], "name": P_.get("name", ""), "client": P_.get("client", ""), "event": P_.get("event_date", ""),
                   "date": e, "estimate": P_.get("estimate"), "budget": P_.get("budget"), "paid": paid,
                   "left": _sub(P_.get("budget"), paid)})
    up.sort(key=lambda r: (r["date"], r["id"]))
    # 사전견적·예산이 없는 건은 합계·예상에서 빼고 건수를 알린다 (그 건 칸은 '미확인')
    known = [r for r in up if r["estimate"] is not None and r["budget"] is not None and r["paid"] is not None]
    up_tot = {k: sum(r[k] for r in known) for k in ("estimate", "budget", "paid", "left")}
    up_missing = len(up) - len(known)
    up_gp = _sub(up_tot["estimate"], up_tot["budget"])
    exp_rev = None if tot["revenue"] is None or up_tot["estimate"] is None else tot["revenue"] + up_tot["estimate"]
    exp_gp = None if tot["gp"] is None or up_gp is None else tot["gp"] + up_gp

    acc = None
    if getattr(d, "dept_accounts", None) is not None:
        rows = [r for r in d.dept_accounts if r["dept"] == team and r["ym"] in months]
        names, order = {}, []
        for r in rows:
            if r["code"] not in names:
                order.append(r["code"])
            names[r["code"]] = r["account"]
        acc = []
        for code in sorted(order):
            by = {}
            for r in rows:
                if r["code"] == code:
                    by[r["ym"]] = None if by.get(r["ym"], 0) is None or r["amount"] is None else by.get(r["ym"], 0) + r["amount"]
            cur_v, prev_v = by.get(ym, 0), by.get(_prev(ym), 0) if _prev(ym)[:4] == year else None
            total = _sum(by.get(m, 0) for m in months)
            acc.append({"code": code, "name": re.sub(r"\((판|제)\)$", "", names[code]), "cur": cur_v, "prev": prev_v,
                        "total": total})
        acc.sort(key=lambda a: -(a["total"] or 0))

    show_net = (d.settings or {}).get(NET_SETTING, "").strip() == "표시"
    return {"team": team, "ym": ym, "year": year, "months": M, "tot": tot, "cum": cum, "t_rev": t_rev, "t_rate": t_rate, "t_gp": t_gp,
            "company_rate": company_rate, "cur": cur, "ytd": ytd, "cur_gap": cur_gap, "ytd_gap": ytd_gap,
            "has_projects": bool(per), "up": up, "up_tot": up_tot, "up_missing": up_missing, "up_gp": up_gp, "exp_rev": exp_rev, "exp_gp": exp_gp,
            "acc": acc, "show_net": show_net, "company": (d.settings or {}).get("회사명", "")}


# ───────────────────────────── HTML ─────────────────────────────

CSS = """
@page { size: A4; margin: 14mm 13mm 14mm 13mm; }
* { box-sizing: border-box; }
body { font-family: 'Malgun Gothic', '맑은 고딕', 'Noto Sans KR', sans-serif; font-size: 8.6pt; color: #111; margin: 0; background: #fff; }
.top { display: flex; justify-content: space-between; font-size: 8pt; color: #333; border-bottom: 1px solid #999; padding-bottom: 3px; }
h1 { text-align: center; font-size: 17pt; font-weight: 700; letter-spacing: 2px; margin: 10px 0 4px; }
h1 + .u { width: 260px; margin: 0 auto 9px; border-top: 3px double #111; }
table { border-collapse: collapse; width: calc(100% - 2px); margin-left: 1px; }
.meta td, .meta th { border: 1px solid #777; padding: 4px 7px; font-size: 8.4pt; }
.meta th { background: #e9e9e9; font-weight: 500; width: 13%; text-align: center; }
.excl { display: flex; justify-content: space-between; font-size: 8pt; margin: 4px 0 0; border: 1px solid #555; padding: 3px 7px; background: #f4f4f4; }
h2 { font-size: 10.4pt; font-weight: 700; margin: 12px 0 4px; break-after: avoid; }
table.g th, table.g td { border: 1px solid #8a8a8a; padding: 2.8px 6px; text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
table.g thead th { background: #e4e4e4; font-weight: 500; text-align: center; }
table.g td.l { text-align: left; white-space: normal; }
table.g td.c { text-align: center; }
table.g tr { break-inside: avoid; }
table.g tr.b td { font-weight: 700; }
table.g tr.tot td { background: #f2f2f2; border-top: 1.5px solid #333; }
table.g tr.gap td { color: #444; font-style: italic; }
.neg { color: #b00; }
table.g td.low { text-decoration: underline; }
table.g.sm td, table.g.sm th { padding: 2.6px 5px; font-size: 8.1pt; }
table.kv { margin-top: 4px; }
table.kv td.th2 { background: #e9e9e9; font-weight: 500; width: 20%; }
td.mut { color: #444; font-size: 7.9pt; }
small { font-size: 7pt; color: #444; }
.note { font-size: 7.8pt; color: #333; margin: 3px 0 0; }
.chbox { width: calc(100% - 2px); margin-left: 1px; border: 1px solid #8a8a8a; padding: 6px 8px 2px; margin-top: 8px; break-inside: avoid; }
.cap { font-size: 8pt; margin-bottom: 2px; }
.pb { break-after: page; }
.basis { width: calc(100% - 2px); margin-left: 1px; break-inside: avoid; border: 1px solid #8a8a8a; padding: 6px 10px; margin-top: 14px; font-size: 7.9pt; }
.basis ol { margin: 3px 0 0 16px; padding: 0; }
.end { text-align: center; margin-top: 12px; font-size: 8.4pt; }
.sec { break-inside: avoid; }
"""


def _td(v, cls=""):
    return "<td%s>%s</td>" % (" class='%s'" % cls if cls else "", v)


def _tr(cells, cls=""):
    return "<tr%s>%s</tr>" % (" class='%s'" % cls if cls else "", "".join(cells))


def _num(v, neg_red=False):
    return _td(esc(W(v)), "neg" if neg_red and v is not None and v < 0 else "")


def _bs(v):
    if v is None:
        return "미확인"
    return "흑자" if v >= 0 else "<span class='neg'>적자</span>"


def _client(c):
    return esc(c) if c else "-"


def _chart(T):
    vals = [v for v in T["cum"] if v is not None]
    top_v = max(vals + [T["t_gp"] or 0, 1])
    step = 10 ** max(0, len(str(int(top_v))) - 1)
    top = ((int(top_v * 1.15) // step) + 1) * step
    Wd, Hd, L = 680, 78, 82
    s = ["<svg viewBox='0 0 %d %d' width='100%%'>" % (Wd, Hd + 26)]
    for k in (0, 0.5, 1):
        v = top * k
        y = Hd - Hd * v / top + 8
        s.append("<line x1='%d' x2='%d' y1='%.1f' y2='%.1f' stroke='#ddd' stroke-width='.6'/>" % (L, Wd - 10, y, y))
        s.append("<text x='%d' y='%.1f' text-anchor='end' font-size='9' fill='#555'>%s</text>" % (L - 6, y + 3, esc(W(v))))
    n = len(T["cum"])
    bw = (Wd - L - 20) / float(max(n, 1))
    for i, v in enumerate(T["cum"]):
        x = L + i * bw + bw * 0.22
        if v is not None and v > 0:
            bh = Hd * v / top
            s.append("<rect x='%.1f' y='%.1f' width='%.1f' height='%.1f' fill='%s'/>"
                     % (x, Hd - bh + 8, bw * .56, bh, "#4a4a4a" if i == n - 1 else "#a9a9a9"))
        s.append("<text x='%.1f' y='%d' text-anchor='middle' font-size='9' fill='#333'>%d월</text>" % (x + bw * .28, Hd + 22, i + 1))
    if T["t_gp"]:
        ty = Hd - Hd * T["t_gp"] / top + 8
        s.append("<line x1='%d' x2='%d' y1='%.1f' y2='%.1f' stroke='#000' stroke-dasharray='4 3' stroke-width='1'/>" % (L, Wd - 10, ty, ty))
        s.append("<text x='%d' y='%.1f' text-anchor='end' font-size='9' fill='#000' style='paint-order:stroke' stroke='#fff' "
                 "stroke-width='3'>연간 목표 %s</text>" % (Wd - 12, ty - 4, esc(W(T["t_gp"]))))
    s.append("</svg>")
    cap = "누계 매출총이익과 연간 목표" if T["t_gp"] else "누계 매출총이익 (연간 목표 없음)"
    return "<div class='chbox'><div class='cap'>[그림] %s</div>%s</div>" % (cap, "".join(s))


def render(T, today=None):
    today = today or dt.date.today()
    ym, M, tot = T["ym"], T["months"], T["tot"]
    mon = int(ym[5:7])
    cur = M[-1]
    prev = M[-2] if len(M) > 1 else None
    pv = (lambda k: prev[k]) if prev else (lambda k: None)
    pl = _mlabel(_prev(ym))
    h = []
    a = h.append

    # 1. 요약
    a("<div class='sec'><h2>1. 실적 요약</h2>")
    a("<table class='g'><colgroup><col style='width:19%'>" + "<col>" * 6 + "</colgroup>")
    a("<thead><tr><th rowspan='2'>구분</th><th colspan='3'>당월</th><th colspan='3'>누계 (1월~%d월)</th></tr>"
      "<tr><th>%d월</th><th>%s</th><th>증감</th><th>실적</th><th>연간 목표</th><th>달성률</th></tr></thead><tbody>" % (mon, mon, pl))
    for name, k, tgt, cls in (("매출", "revenue", T["t_rev"], ""), ("매출원가", "cost", None, ""), ("매출총이익", "gp", T["t_gp"], "b")):
        a(_tr([_td(name, "l"), _num(cur[k]), _num(pv(k)), _num(_sub(cur[k], pv(k))), _num(tot[k]),
               _td(esc(W(tgt)) if tgt else "-", "" if tgt else "c"), _td(esc(P(tot[k], tgt)) if tgt else "-", "" if tgt else "c")], cls))
    rc = None if cur["revenue"] in (None, 0) or cur["gp"] is None else cur["gp"] * 100.0 / cur["revenue"]
    rp = None if not prev or prev["revenue"] in (None, 0) or prev["gp"] is None else prev["gp"] * 100.0 / prev["revenue"]
    a(_tr([_td("수익률", "l"), _td(esc(P(cur["gp"], cur["revenue"]))), _td(esc(P(pv("gp"), pv("revenue")))),
           _td("-" if rc is None or rp is None else "%+.1f%%p" % (rc - rp)), _td(esc(P(tot["gp"], tot["revenue"]))),
           _td("%.1f%%" % T["t_rate"] if T["t_rate"] is not None else "-"), _td("-", "c")]))
    a(_tr([_td("팀 판관비<small> (급여 제외)</small>", "l"), _num(cur["sga"]), _num(pv("sga")), _num(_sub(cur["sga"], pv("sga"))),
           _num(tot["sga"]), _td("-", "c"), _td("-", "c")]))
    a(_tr([_td("판관비 차감 후 이익", "l"), _num(cur["op"], True), _num(pv("op"), True), _num(_sub(cur["op"], pv("op"))),
           _num(tot["op"], True), _td("-", "c"), _td("-", "c")], "b tot"))
    if T["show_net"]:
        a(_tr([_td("급여 반영 손익<small> (금액 비공개)</small>", "l"), _td(_bs(cur["net"]), "c"), _td(_bs(pv("net")) if prev else "-", "c"),
               _td("-", "c"), _td(_bs(tot["net"]), "c"), _td("-", "c"), _td("-", "c")], "b"))
    heads = lambda v: "미확인" if v is None else "%d명" % v
    a(_tr([_td("인원", "l"), _td(heads(cur["heads"])), _td(heads(pv("heads")) if prev else "-"), _td("-", "c"),
           _td("미확인" if tot["heads"] is None else "평균 %.1f명" % tot["heads"]), _td("-", "c"), _td("-", "c")]))
    a("</tbody></table>")
    notes = []
    if T["company_rate"] is not None:
        notes.append("같은 기간 회사 전체 수익률 %.1f%%" % T["company_rate"])
    if T["t_gp"] and tot["gp"] is not None:
        left = T["t_gp"] - tot["gp"]
        notes.append(("연간 목표 매출총이익까지 남은 금액 %s원" % W(left)) if left > 0 else "연간 목표 매출총이익 달성")
    if not T["t_gp"]:
        notes.append("올해 팀 목표가 입력되지 않아 달성률을 계산하지 않음")
    if notes:
        a("<p class='note'>※ 참고: %s</p>" % esc(" · ".join(notes)))
    a("</div>")

    # 2. 월별
    a("<div class='sec'><h2>2. 월별 실적</h2>")
    a("<table class='g'><thead><tr><th>월</th><th>매출</th><th>매출원가</th><th>매출총이익</th><th>수익률</th>"
      "<th>판관비<br><small>(급여 제외)</small></th><th>판관비 차감 후 이익</th>" + ("<th>급여 반영<br>손익</th>" if T["show_net"] else "")
      + "<th>인원</th><th>누계 매출총이익</th></tr></thead><tbody>")
    for i, x in enumerate(M):
        a(_tr([_td(_mlabel(x["ym"]), "c"), _num(x["revenue"]), _num(x["cost"]), _num(x["gp"]), _td(esc(P(x["gp"], x["revenue"]))),
               _num(x["sga"]), _num(x["op"], True)] + ([_td(_bs(x["net"]), "c")] if T["show_net"] else [])
              + [_td("미확인" if x["heads"] is None else "%d" % x["heads"], "c"), _num(T["cum"][i])]))
    a(_tr([_td("합계", "c"), _num(tot["revenue"]), _num(tot["cost"]), _num(tot["gp"]), _td(esc(P(tot["gp"], tot["revenue"]))),
           _num(tot["sga"]), _num(tot["op"], True)] + ([_td(_bs(tot["net"]), "c")] if T["show_net"] else [])
          + [_td("미확인" if tot["heads"] is None else "%.1f" % tot["heads"], "c"), _num(tot["gp"])], "b tot"))
    a("</tbody></table>")
    a(_chart(T))
    a("</div>")

    def project_table(rows, g, label_total, with_months):
        head = ("<th>No</th>" if with_months else "") + "<th>프로젝트</th><th>거래처</th><th>행사일</th>" + \
            ("<th>계상월</th>" if with_months else "") + "<th>매출</th><th>매출원가</th><th>매출총이익</th><th>수익률</th>"
        out = ["<table class='g%s'><thead><tr>%s</tr></thead><tbody>" % (" sm" if with_months else "", head)]
        low = None if T["t_rate"] is None else T["t_rate"] - LOW_GAP
        for k, r in enumerate(rows, 1):
            rate = None if not r["revenue"] or r["gp"] is None else r["gp"] * 100.0 / r["revenue"]
            out.append(_tr(([_td(str(k), "c")] if with_months else []) + [
                _td(esc("[%s] %s" % (r["id"], r["name"])), "l"), _td(_client(r["client"]), "l"), _td(esc(r["event"] or "-"), "c")]
                + ([_td(esc(r["months"] or "-"), "c")] if with_months else [])
                + [_num(r["revenue"]), _num(r["cost"]), _num(r["gp"]),
                   _td(esc(P(r["gp"], r["revenue"])), "low" if with_months and low is not None and rate is not None and rate < low else "")]))
        if g:
            span = 5 if with_months else 3
            out.append(_tr(["<td class='l' colspan='%d'>프로젝트로 나누지 못한 금액 (팀 합계와의 차이)</td>" % span,
                            _num(g["revenue"]), _num(g["cost"]), _num(g["gp"]), _td("-", "c")], "gap"))
        rev, cost = (cur["revenue"], cur["cost"]) if not with_months else (tot["revenue"], tot["cost"])
        span = 5 if with_months else 3
        out.append(_tr(["<td class='c' colspan='%d'>%s (%d건)</td>" % (span, label_total, len(rows)), _num(rev), _num(cost),
                        _num(_sub(rev, cost)), _td(esc(P(_sub(rev, cost), rev)))], "b tot"))
        out.append("</tbody></table>")
        return "".join(out)

    # 3. 당월 프로젝트
    a("<div class='sec'><h2>3. %d월 프로젝트별 실적</h2>" % mon)
    if not T["has_projects"]:
        a("<p class='note'>프로젝트별 자료 없음</p>")
    else:
        a(project_table(T["cur"], T["cur_gap"], "소계", False))
    a("</div>")
    a("<div class='pb'></div>")

    # 4. 누계 프로젝트
    a("<h2>4. 누계 프로젝트별 실적 (1월~%d월)</h2>" % mon)
    if not T["has_projects"]:
        a("<p class='note'>프로젝트별 자료 없음</p>")
    else:
        a(project_table(T["ytd"], T["ytd_gap"], "합계", True))
        if T["t_rate"] is not None:
            a("<p class='note'>※ 수익률 밑줄 = 팀 목표 수익률(%.1f%%)보다 %g%%p 이상 낮은 건</p>" % (T["t_rate"], LOW_GAP))

    # 5. 진행·예정
    a("<div class='sec'><h2>5. 진행·예정 프로젝트 (매출 계상 전)</h2>")
    if not T["up"]:
        a("<p class='note'>올해 행사 중 매출 계상 전 프로젝트 없음</p>")
    else:
        a("<table class='g'><thead><tr><th>프로젝트</th><th>거래처</th><th>행사일</th><th>사전견적</th><th>추정 예산</th>"
          "<th>집행액</th><th>잔여<br><small>(추정 예산 − 집행액)</small></th></tr></thead><tbody>")
        for r in T["up"]:
            a(_tr([_td(esc("[%s] %s" % (r["id"], r["name"])), "l"), _td(_client(r["client"]), "l"), _td(esc(r["event"]), "c"),
                   _num(r["estimate"]), _num(r["budget"]), _num(r["paid"]), _num(r["left"], True)]))
        u = T["up_tot"]
        a(_tr(["<td class='c' colspan='3'>합계 (%d건)</td>" % (len(T["up"]) - T["up_missing"]), _num(u["estimate"]), _num(u["budget"]), _num(u["paid"]),
               _num(u["left"], True)], "b tot"))
        a("</tbody></table>")
        if T["up_missing"]:
            a("<p class='note'>※ 사전견적 또는 추정 예산이 없는 %d건은 합계와 아래 예상에서 뺌</p>" % T["up_missing"])
    a("<table class='g kv'><tbody>")
    tr_, tg_ = T["t_rev"], T["t_gp"]
    a(_tr([_td("올해 매출 예상", "l th2"), _num(T["exp_rev"]),
           _td(esc("= 누계 매출 %s + 예정 사전견적 %s" % (W(tot["revenue"]), W(T["up_tot"]["estimate"] or 0))), "l mut"),
           _td(esc("목표 대비 %s" % P(T["exp_rev"], tr_)) if tr_ else "-", "c")]))
    a(_tr([_td("올해 매출총이익 예상", "l th2"), _num(T["exp_gp"]),
           _td(esc("= 누계 %s + 예정분 예상 이익 %s" % (W(tot["gp"]), W(T["up_gp"] or 0))), "l mut"),
           _td(esc("목표 대비 %s" % P(T["exp_gp"], tg_)) if tg_ else "-", "c")]))
    a("</tbody></table></div>")

    # 6. 판관비
    a("<div class='sec'><h2>6. 팀 판관비 내역 (급여 제외)</h2>")
    if T["acc"] is None:
        a("<table class='g'><thead><tr><th>구분</th><th>%d월</th><th>%s</th><th>증감</th><th>누계 (1월~%d월)</th><th>월평균</th></tr></thead><tbody>"
          % (mon, pl, mon))
        a(_tr([_td("판관비 합계", "c"), _num(cur["sga"]), _num(pv("sga")), _num(_sub(cur["sga"], pv("sga"))), _num(tot["sga"]),
               _num(None if tot["sga"] is None else tot["sga"] / float(len(M)))], "b tot"))
        a("</tbody></table><p class='note'>※ 계정별 내역은 다음 자료 변환부터 나옵니다. 팀 급여는 이 표에 포함하지 않음.</p>")
    else:
        a("<table class='g'><thead><tr><th>계정</th><th>%d월</th><th>%s</th><th>증감</th><th>누계 (1월~%d월)</th><th>월평균</th></tr></thead><tbody>"
          % (mon, pl, mon))
        for r in T["acc"]:
            a(_tr([_td(esc(r["name"]), "l"), _num(r["cur"]), _num(r["prev"]), _num(_sub(r["cur"], r["prev"])), _num(r["total"]),
                   _num(None if r["total"] is None else r["total"] / float(len(M)))]))
        a(_tr([_td("합계", "c"), _num(cur["sga"]), _num(pv("sga")), _num(_sub(cur["sga"], pv("sga"))), _num(tot["sga"]),
               _num(None if tot["sga"] is None else tot["sga"] / float(len(M)))], "b tot"))
        a("</tbody></table><p class='note'>※ 팀 급여는 이 표에 포함하지 않음.</p>")
    a("</div>")

    basis = ["수익률 = 매출총이익 ÷ 매출",
             "<b>이 자료에는 팀 급여가 제외되어 있음.</b> 판관비 차감 후 이익 = 매출총이익 − 팀 판관비(급여 제외)이며, "
             "회사 손익의 영업이익과 다름. 본부·공통 비용은 나누지 않음"]
    if T["show_net"]:
        basis.append("급여 반영 손익 = 매출총이익 − 판관비 − 팀 급여. 금액은 표시하지 않고 0원 이상이면 흑자, 미만이면 적자로만 표시")
    basis.append("진행·예정 금액은 세금계산서 발행 전 사전견적 기준이며 확정 실적이 아님")
    a("<div class='basis'><b>작성 기준</b><ol>%s</ol></div>" % "".join("<li>%s</li>" % b for b in basis))
    a("<div class='end'>- 끝 -</div>")

    y, m = int(ym[:4]), mon
    last_day = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day
    excl = "※ 이 자료의 판관비·이익 금액에는 <b>팀 급여가 제외</b>되어 있습니다." + (
        " 급여 반영 손익은 흑자·적자로만 표시합니다." if T["show_net"] else "")
    head = ("<div class='top'><span>%s · 경영관리</span><span>대외비 · %s 배포용</span></div>"
            "<h1>%d년 %d월 %s 실적 보고</h1><div class='u'></div>"
            "<table class='meta'><tr><th>수 신</th><td>%s장</td><th>작 성</th><td>경영관리</td><th>작성일</th><td>%s</td></tr>"
            "<tr><th>기 간</th><td colspan='5'>당월 %d.%02d.01 ~ %02d.%02d · 누계 %d.01.01 ~ %02d.%02d</td></tr></table>"
            "<div class='excl'><span>%s</span><span>(단위: 원)</span></div>"
            % (esc(T["company"]), esc(T["team"]), y, m, esc(T["team"]), esc(T["team"]), today.strftime("%Y.%m.%d"),
               y, m, m, last_day, y, m, last_day, excl))
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>%d년 %d월 %s 실적 보고</title><style>%s</style></head>"
            "<body>%s%s</body></html>" % (y, m, esc(T["team"]), CSS, head, "\n".join(h)))


def write_all(d, R, out_dir, today=None):
    """팀마다 팀장용 HTML 을 out_dir/팀장용/ 에 쓴다. -> [html 경로]."""
    folder = os.path.join(out_dir, "팀장용")
    os.makedirs(folder, exist_ok=True)
    out = []
    asof = R.get("asof") or today or dt.date.today()
    for team in team_names(d):
        T = build(d, R, team)
        path = os.path.join(folder, "%s_월간_팀장_%s.html" % (asof.isoformat() if hasattr(asof, "isoformat") else asof, team))
        with open(path, "w", encoding="utf-8") as f:
            f.write(render(T, today))
        out.append(path)
    return out
