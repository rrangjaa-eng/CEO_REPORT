"""자동 분석(insights) 을 보고서 조각으로 (사용자 2026-11-12).

대표 보고: 2 세금 떼고 · 4 경보(자금 부족만, 적자 프로젝트는 뺌 — 사용자 2026-11-12) · 1 바뀐 이유 3건 · 12 입금 지연 위험 3건 · 3 이달 예상 영업이익.
팀장 보고: 그 팀 것만 — 8 이익 흐름 · 4 예산 80%·100%·적자 · 7 계산서 짝 · 6 미수금 나이 · 11 목표 달성률.
경영관리 보고: 13가지 모두.
"""
import html

from . import insights


def esc(t):
    return html.escape(str(t if t is not None else ""))


def W(v, empty="-"):
    if v is None:
        return empty
    return "{:,}".format(int(round(v)))


def S(v):
    """부호 붙은 금액."""
    if v is None:
        return "-"
    return ("+" if v > 0 else ("−" if v < 0 else "")) + "{:,}".format(abs(int(round(v))))


def T(v):
    """팀장 보고 표기: 음수는 △ (회사 문서 모양)."""
    if v is None:
        return "-"
    return ("△" if v < 0 else ("+" if v > 0 else "")) + "{:,}".format(abs(int(round(v))))


def _pct(v):
    return "-" if v is None else "%.0f%%" % v


# ───────────── 대표 보고 조각 ─────────────
CEO_CSS = (".ins-alert{border:2px solid #c62828;background:#fdecea;color:#8e1b1b;border-radius:8px;padding:6px 12px;margin:6px 0;"
           "font-weight:700}.ins-alert li{margin:2px 0}.ins-line{font-size:12.5px;color:#1d2433;margin-top:4px}"
           ".ins-line b{font-variant-numeric:tabular-nums}.ins-card{margin-top:8px}.ins-card table{width:100%}"
           ".ins-why{margin:4px 0 0 0;padding-left:18px;font-size:12.5px}.ins-why li{margin:1px 0}"
           ".ins-pos{color:#1b7f3b}.ins-neg{color:#c62828}")


def ceo_alert(I):
    """여유 자금 부족 경보만 (적자로 바뀐 프로젝트는 대표 보고에 넣지 않음, 사용자 2026-11-12). 없으면 빈 글."""
    rows = [t for lv, t in I["alerts"] if lv == "높음" and "여유 자금" in t]
    if not rows:
        return ""
    return "<div class='ins-alert'>경보 · %s</div>" % " / ".join(esc(t) for t in rows)


def ceo_tax_line(I):
    T = I["tax"]
    if not T["later"] or T["after"] is None:
        return ""
    return ("<div class='ins-line'>그 뒤에 낼 세금 %s원(이미 쌓인 부가세·원천세 등)까지 떼면 <b>%s</b>원</div>"
            % (W(T["later_total"]), W(T["after"])))


def ceo_reasons(I, n=3):
    if not I["reasons"]:
        return ""
    return "<ul class='ins-why'>%s</ul>" % "".join(
        "<li>%s <span class='%s'>(%s)</span></li>" % (esc(t), "ins-pos" if v > 0 else "ins-neg", S(v)) for t, v in I["reasons"][:n])


def ceo_risk_card(I):
    """입금 지연 위험 3건 + 이번 달 예상 영업이익 한 줄."""
    parts = []
    D = I["delay"]
    if D:
        rows = "".join("<tr><td>%s</td><td>%s</td><td class='vin'>%s</td><td class='av'><b>%s</b></td><td class='vout'>%s</td></tr>"
                       % (esc(r["desc"]), r["date"].strftime("%m/%d"), W(r["amount"]), W(r["avail"]), S(r["drop"])) for r in D)
        parts.append("<div class='lab'>큰 입금이 %d일 늦으면</div><table class='pt'><thead><tr><th>입금</th><th>예정일</th>"
                     "<th>금액</th><th>그때 여유 자금</th><th>줄어드는 돈</th></tr></thead><tbody>%s</tbody></table>"
                     % (insights.DELAY_DAYS, rows))
    M = I["month"]
    if M and M["forecast"] is not None:
        adds = " · ".join("%s %s" % (n, W(v)) for n, v in M["adds"])
        parts.append("<div class='ins-line'>이번 달(%s월) 예상 영업이익 <b>%s</b>원 <span style='color:#5b6475'>(지금 장부 %s%s)</span></div>"
                     % (int(M["ym"][5:]), W(M["forecast"]), W(M["booked"]), (" − 아직 안 넣은 " + adds) if adds else ""))
    if not parts:
        return ""
    return "<div class='card ins-card'>%s</div>" % "".join(parts)


# ───────────── 팀장 보고 조각 ─────────────
def _team_projects(R, team):
    return dict((p.get("id"), p) for p in (R.get("s3") or {}).get("projects") or [] if (p.get("team") or "") == team)


def team_section(I, R, team, start_no=7):
    """팀장 보고 끝(작성 기준 앞)에 붙는 절들 -> html (teamreport 의 표 모양 'g')."""
    mine = _team_projects(R, team)
    names = set("[%s] %s" % (k, p.get("name")) for k, p in mine.items())
    out, no = [], start_no

    def sec(title, body):
        out.append("<div class='sec'><h2>%d. %s</h2>%s</div>" % (no, esc(title), body))

    # 11 목표 달성률은 팀장 보고 1절 '실적 요약'에 이미 있어 다시 싣지 않는다
    # 8 이익 흐름
    fl = [f for f in I["flow"] if f["name"] in names]
    if fl:
        rows = "".join("<tr><td class='l'>%s</td><td class='n'>%s</td><td class='n'>%s</td><td class='n'>%s</td><td class='n'><b>%s</b></td></tr>"
                       % (esc(f["name"]), W(f["contract"]), W(f["quote"]), W(f["now"]), T(f["diff"])) for f in fl)
        sec("프로젝트 이익 흐름 (견적 때 → 지금)",
            "<table class='g'><thead><tr><th>프로젝트</th><th>계약</th><th>견적 때 이익</th><th>지금 예상 이익</th><th>차이</th></tr></thead>"
            "<tbody>%s</tbody></table><p class='note'>※ 견적 때 이익 = 계약 − 추정 예산, 지금 예상 이익 = 계약 − (쓴 돈 + 더 나갈 돈)</p>" % rows)
        no += 1
    # 4 경보 (그 팀 프로젝트)
    al = [(lv, t) for lv, t in I["alerts"] if any(t.startswith(n) for n in names)]
    if al:
        sec("주의할 프로젝트", "<table class='g'><tbody>%s</tbody></table>" % "".join(
            "<tr><td class='c'>%s</td><td class='l'>%s</td></tr>" % (esc(lv), esc(t)) for lv, t in al))
        no += 1
    # 7 계산서 짝
    pr = [(n, t) for n, t in I["pairs"] if n in names]
    if pr:
        sec("계산서 확인 필요", "<table class='g'><tbody>%s</tbody></table>" % "".join(
            "<tr><td class='l'>%s</td><td class='l'>%s</td></tr>" % (esc(n), esc(t)) for n, t in pr))
        no += 1
    # 6 미수금 나이 (그 팀 프로젝트의 받을 돈)
    ar = [r for r in (R.get("s5") or {}).get("ar_rows") or [] if r.get("project") in mine and r.get("outstanding")]
    if ar:
        rows = "".join("<tr><td class='l'>%s</td><td class='l'>%s</td><td class='c'>%s</td><td class='n'>%s</td><td class='n'>%d일</td></tr>"
                       % (esc("[%s] %s" % (r["project"], mine[r["project"]].get("name"))), esc(r.get("client")),
                          r["date"].strftime("%Y.%m.%d") if r.get("date") else "", W(r["outstanding"]),
                          (R["asof"] - r["date"]).days if r.get("date") else 0)
                       for r in sorted(ar, key=lambda r: r.get("date") or R["asof"]))
        sec("받을 돈 (발행 뒤 지난 날수)",
            "<table class='g'><thead><tr><th>프로젝트</th><th>거래처</th><th>발행일</th><th>받을 돈</th><th>지난 날</th></tr></thead>"
            "<tbody>%s</tbody></table>" % rows)
        no += 1
    return "".join(out)


# ───────────── 경영관리 보고: 13가지 모두 ─────────────
def _tbl(head, rows, nums=()):
    h = ["<table class='pt'><thead><tr>"]
    h += ["<th%s>%s</th>" % (" class='n'" if i in nums else "", esc(x)) for i, x in enumerate(head)]
    h.append("</tr></thead><tbody>")
    for r in rows:
        h.append("<tr>%s</tr>" % "".join("<td%s>%s</td>" % (" class='n'" if i in nums else "", c) for i, c in enumerate(r)))
    h.append("</tbody></table>")
    return "".join(h)


def _none(t):
    return "<p class='note'>%s</p>" % esc(t)


def _cal_svg(cal, min_cash):
    if not cal:
        return _none("잔액을 몰라 그리지 않음")
    vals = [c["firm"] for c in cal] + [c["all"] for c in cal] + [min_cash or 0, 0]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        hi = lo + 1
    Wd, H, L, B = 900, 220, 70, 30

    def x(i):
        return L + (Wd - L - 10) * i / float(max(len(cal) - 1, 1))

    def y(v):
        return 10 + (H - B - 10) * (hi - v) / float(hi - lo)
    s = ["<svg viewBox='0 0 %d %d' width='100%%' role='img' aria-label='앞으로 %d일 날마다 잔액'>" % (Wd, H, len(cal))]
    for k in range(5):
        v = lo + (hi - lo) * k / 4.0
        s.append("<line x1='%d' x2='%d' y1='%.1f' y2='%.1f' stroke='#e6e9ef'/><text x='%d' y='%.1f' font-size='12' text-anchor='end' "
                 "fill='#5b6475'>%s</text>" % (L, Wd - 10, y(v), y(v), L - 6, y(v) + 4, "%.1f억" % (v / 1e8)))
    if min_cash:
        s.append("<line x1='%d' x2='%d' y1='%.1f' y2='%.1f' stroke='#c62828' stroke-dasharray='5 4'/>" % (L, Wd - 10, y(min_cash), y(min_cash)))
    for key, color, dash in (("all", "#1f4e8c", "4 3"), ("firm", "#1f4e8c", "")):
        pts = " ".join("%.1f,%.1f" % (x(i), y(c[key])) for i, c in enumerate(cal))
        s.append("<polyline points='%s' fill='none' stroke='%s' stroke-width='2' %s/>" % (pts, color, "stroke-dasharray='%s'" % dash if dash else ""))
    low = min(range(len(cal)), key=lambda i: cal[i]["firm"])
    s.append("<circle cx='%.1f' cy='%.1f' r='4' fill='#c62828'/><text x='%.1f' y='%.1f' font-size='12' fill='#c62828' text-anchor='middle'>"
             "가장 낮음 %s</text>" % (x(low), y(cal[low]["firm"]), x(low), y(cal[low]["firm"]) - 8, cal[low]["date"].strftime("%m/%d")))
    for i, c in enumerate(cal):
        if c["date"].weekday() == 0:
            s.append("<text x='%.1f' y='%d' font-size='11' text-anchor='middle' fill='#5b6475'>%s</text>" % (x(i), H - 8, c["date"].strftime("%m/%d")))
    s.append("</svg>")
    return "".join(s) + "<p class='note'>실선 = 확정된 돈만, 점선 = 예상 포함, 빨간 점선 = 최소 보유현금. 가장 낮은 날 %s 확정 잔액 %s원</p>" % (
        cal[low]["date"].isoformat(), W(cal[low]["firm"]))


def mgmt_section(I, R):
    """경영관리 보고 '자동 분석' 영역 -> html."""
    h = ["<h2 id='auto'>자동 분석 (새 자료가 들어올 때마다 다시 계산)</h2>"]

    def sub(no, title, body):
        h.append("<h3>%d. %s</h3>%s" % (no, esc(title), body))

    # 4 경보 (맨 위)
    sub(1, "경보", _tbl(["수준", "내용"], [[esc(lv), esc(t)] for lv, t in I["alerts"]]) if I["alerts"] else _none("경보 없음"))
    # 1 바뀐 이유
    if not I["has_prev"]:
        body = _none("지난 기록이 없어 비교하지 못함 (다음 보고부터)")
    elif not I["reasons"]:
        body = _none("지난 기록 뒤 여유 자금 기간 안의 일정 변화 없음")
    else:
        body = _tbl(["바뀐 일정", "여유 자금에 준 영향"], [[esc(t), S(v)] for t, v in I["reasons"]], nums=(1,))
    sub(2, "지난 기록 뒤 여유 자금을 바꾼 것 (금액 큰 순)", body)
    # 2 세금 떼고
    T = I["tax"]
    body = _tbl(["세금", "대상", "납부일", "금액", "상태"], [[esc(t["kind"]), esc(t.get("period")), esc(t["due"]), W(t["amount"]), esc(t.get("state"))]
                                                   for t in T["rows"]], nums=(3,)) if T["rows"] else _none("앞으로 낼 세금 계산값 없음")
    if T["after"] is not None:
        body += "<p class='note'>%s 여유 자금 %s원 − 그 뒤에 낼 세금 %s원 = <b>%s원</b> (기간 안에 낼 세금은 이미 여유 자금 계산에 들어 있음)</p>" % (
            esc(T["label"]), W(T["avail"]), W(T["later_total"]), W(T["after"]))
    sub(3, "이미 쌓인 세금 (낼 돈으로 떼어 봄)", body)
    # 3 이달 손익 예측
    M = I["month"]
    if not M or M["booked"] is None:
        body = _none("이번 달 실적 자료가 없어 계산하지 못함")
    else:
        rows = [["지금 장부 매출", W(M["sales"])], ["지금 장부 원가", W(M["cost"])], ["지금 장부 판관비", W(M["sga"])],
                ["지금 장부 영업이익", W(M["booked"])]] + [["− " + esc(n), W(v)] for n, v in M["adds"]] + [["<b>월말 예상 영업이익</b>", "<b>%s</b>" % W(M["forecast"])]]
        body = _tbl(["구분", "금액"], rows, nums=(1,)) + "<p class='note'>매출은 지금까지 발행한 것만. 이달 안에 더 발행할 계산서는 넣지 않음</p>"
    sub(4, "이번 달 마감 전 손익 예측", body)
    # 5 자금 달력
    sub(5, "앞으로 %d일 날마다 잔액" % len(I["calendar"]), _cal_svg(I["calendar"], R["s2"].get("min_cash")))
    # 12 입금 지연
    D = I["delay"]
    sub(6, "큰 입금이 %d일 늦으면" % insights.DELAY_DAYS,
        _tbl(["입금", "예정일", "금액", "그때 여유 자금", "줄어드는 돈"], [[esc(r["desc"]), esc(r["date"]), W(r["amount"]), W(r["avail"]), S(r["drop"])]
                                                           for r in D], nums=(2, 3, 4)) if D else _none("기간 안 확정 입금 없음"))
    # 9 입금 습관
    Hb = I["habits"]
    if not Hb["clients"]:
        body = _none("입금 예정일과 실제 입금일이 2번 넘게 있는 거래처 없음")
    else:
        body = _tbl(["거래처", "예정일보다 평균", "건수"], [[esc(c), ("%+.1f일" % v), "%d건" % n] for c, v, n in Hb["clients"]], nums=(1, 2))
        if Hb["avail"][0] is not None and Hb["base"]:
            body += "<p class='note'>늦는 거래처 입금을 그만큼 미뤄 보면 %s 여유 자금 %s원 (지금 %s원). 보고의 여유 자금 계산은 바꾸지 않음</p>" % (
                esc(Hb["base"]["label"]), W(Hb["avail"][0]), W(Hb["base"]["firm"]["avail"]))
    sub(7, "거래처별 입금 습관", body)
    # 10 고정비
    F = I["fixed"]
    if F is None:
        body = _none("장부 분석 자료 없음 (자료 변환을 다시 하면 나옴)")
    elif not F["items"]:
        body = _none("매달 같은 곳에 비슷한 금액이 나가는 지급을 찾지 못함")
    else:
        body = _tbl(["매달 나가는 곳", "금액(가운데 값)", "보통 날"], [[esc(r["name"]), W(r["amount"]), "%d일" % r["day"]] for r in F["items"]], nums=(1,))
        if F["missing"]:
            body += "<p class='note'><b>일정에 없는 앞으로 지급 %d건</b></p>" % len(F["missing"]) + _tbl(
                ["곳", "예상일", "금액"], [[esc(m["name"]), esc(m["date"]), W(m["amount"])] for m in F["missing"]], nums=(2,))
            if F["avail"][0] is not None:
                body += "<p class='note'>이것까지 빼면 마지막 기간 여유 자금 %s원 (예상 포함 %s원). 보고의 여유 자금 계산은 바꾸지 않음</p>" % (
                    W(F["avail"][0]), W(F["avail"][1]))
        else:
            body += _none("앞으로 3달 지급은 모두 일정에 있음")
    sub(8, "고정비 자동 인식", body)
    # 13 입력 누락
    if I["fixed"] is None:
        body = _none("장부 분석 자료 없음 (자료 변환을 다시 하면 나옴)")
    else:
        body = _tbl(["종류", "내용"], [[esc(k), esc(t)] for k, t in I["missing"]]) if I["missing"] else _none("빠진 것 없음")
    sub(9, "장부 입력 누락 의심", body)
    # 6 미수금 나이
    A = I["aging"]
    body = _tbl(["발행 뒤", "받을 돈", "건수"], [[esc(n), W(v), "%d건" % c] for n, v, c in A["buckets"]], nums=(1, 2))
    if A["clients"]:
        body += _tbl(["거래처", "받을 돈", "가장 오래된 것"], [[esc(c), W(v), "%d일" % d] for c, v, d in A["clients"]], nums=(1, 2))
    sub(10, "받을 돈 나이", body)
    # 7 계산서 짝
    sub(11, "계산서 짝 확인 (행사 끝난 프로젝트)",
        _tbl(["프로젝트", "내용"], [[esc(n), esc(t)] for n, t in I["pairs"]]) if I["pairs"] else _none("짝이 안 맞는 프로젝트 없음"))
    # 8 이익 흐름
    fl = I["flow"]
    sub(12, "프로젝트 이익 흐름 (견적 때 → 지금, 줄어든 순)",
        _tbl(["프로젝트", "팀", "계약", "견적 때 이익", "지금 예상 이익", "차이"],
             [[esc(f["name"]), esc(f["team"]), W(f["contract"]), W(f["quote"]), W(f["now"]), S(f["diff"])] for f in fl], nums=(2, 3, 4, 5))
        if fl else _none("계약·추정 예산이 있는 프로젝트 없음"))
    # 11 팀 순위
    tm = I["teams"]
    sub(13, "팀별 올해 누계",
        _tbl(["순위", "팀", "매출", "매출총이익", "수익률", "매출 목표", "달성률"],
             [["%d" % (i + 1), esc(t["team"]), W(t["revenue"]), W(t["gp"]), _pct(t["rate"]), W(t["target"]), _pct(t["achieve"])]
              for i, t in enumerate(tm)], nums=(2, 3, 4, 5, 6)) if tm else _none("팀별 자료 없음"))
    return "".join(h)
