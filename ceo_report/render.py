"""HTML 보고서 만들기. mode='ceo'(대표용) 또는 'mgmt'(경영관리용).

두 보고서는 같은 계산 결과 R을 쓴다. 경영관리용에만 '위험 분석·해결방안'이 붙는다.
대표용에는 해석·권고 문구를 넣지 않는다.
"""
import datetime as dt
import math

from .util import won, man, pct, d2s, esc

CSS = """
:root{--ink:#1d2433;--sub:#5b6475;--line:#d9dde5;--soft:#f3f5f8;--accent:#1f4e8c;--in:#2f7d5b;--out:#b5523b;
--est:#9aa3b2;--warn:#8a5a00;--bg:#fff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.45 "Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 20px 60px}
h1{font-size:22px;margin:0}
h2{font-size:16px;margin:28px 0 8px;padding-bottom:6px;border-bottom:2px solid var(--ink)}
h3{font-size:13.5px;margin:16px 0 6px;color:var(--accent)}
.meta{color:var(--sub);margin-top:4px}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;background:var(--accent);color:#fff;font-size:12px;margin-left:8px;vertical-align:middle}
.badge.m{background:#6b3fa0}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}
.kpi{border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.kpi .l{color:var(--sub);font-size:12px}
.kpi .v{font-size:22px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
.kpi .v .u{font-size:12px;font-weight:400;color:var(--sub);margin-left:2px}
.kpi .s{color:var(--sub);font-size:11.5px;margin-top:2px}
.mid{display:grid;grid-template-columns:1.45fr 1fr;gap:14px}
.mid>div,.low>div,.kpis>div{min-width:0}
.low{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:14px}
.card{border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.card h4{margin:0 0 6px;font-size:13px}
.kv{display:flex;justify-content:space-between;gap:8px;padding:2px 0;border-bottom:1px dotted var(--line)}
.kv:last-child{border-bottom:0}
.kv span:last-child{font-variant-numeric:tabular-nums;text-align:right}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
th{background:var(--soft);font-weight:600;white-space:nowrap}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
tr.tot td{font-weight:700;border-top:2px solid var(--ink);background:var(--soft)}
tr.sub td{color:var(--sub)}
.na{color:var(--warn)}
.note{color:var(--sub);font-size:11.5px;margin:4px 0}
.scope{font-size:12px;color:var(--sub);margin:4px 0 6px}
.ok{color:var(--in);font-weight:700}.ng{color:var(--out);font-weight:700}
.risk td.lv{font-weight:700;white-space:nowrap}
.risk tr.h td.lv{color:var(--out)}
.legend span{display:inline-flex;align-items:center;margin-right:10px;font-size:11.5px;color:var(--sub)}
.legend i{display:inline-block;width:10px;height:10px;margin-right:4px;border-radius:2px}
.page{page-break-after:always}
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch}
.toc{margin-top:14px}
.toc a{color:var(--accent);margin-right:10px}
@media screen and (max-width:820px){.kpis,.low{grid-template-columns:1fr 1fr}.mid{grid-template-columns:1fr}}
@media print{@page{size:A4 landscape;margin:10mm}.wrap{max-width:none;padding:0}h2{break-after:avoid}
tr{break-inside:avoid}.toc{display:none}body{font-size:10.5px}table{font-size:10.5px}.kpi .v{font-size:18px}h2{margin-top:16px}.kpis{margin:8px 0}.kpi{padding:6px 10px}.mid svg{max-height:185px}.low{margin-top:8px}.kv{padding:1px 0}.wrap>.meta{margin-bottom:0}}
"""


def _na(text):
    return '<span class="na">%s</span>' % esc(text)


def W(v, empty="미확인"):
    """금액 칸. 값이 없으면 표시 문구를 눈에 띄게 둔다."""
    return _na(empty) if v is None else esc(won(v))


def M(v, empty="미확인"):
    return _na(empty) if v is None else esc(man(v))


def table(head, rows, num_cols=(), cls="", total=None):
    h = "".join('<th class="n">%s</th>' % esc(c) if i in num_cols else "<th>%s</th>" % esc(c) for i, c in enumerate(head))
    body = []
    for r in rows:
        rc = ""
        if isinstance(r, tuple) and len(r) == 2 and isinstance(r[1], str) and isinstance(r[0], list):
            r, rc = r
        tds = "".join('<td class="n">%s</td>' % c if i in num_cols else "<td>%s</td>" % c for i, c in enumerate(r))
        body.append('<tr class="%s">%s</tr>' % (rc, tds))
    if total:
        tds = "".join('<td class="n">%s</td>' % c if i in num_cols else "<td>%s</td>" % c for i, c in enumerate(total))
        body.append('<tr class="tot">%s</tr>' % tds)
    if not rows and not total:
        body.append('<tr><td colspan="%d" class="note">해당 없음</td></tr>' % len(head))
    return '<div class="tw"><table class="%s"><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (
        cls, h, "".join(body))


def kv(pairs):
    return "".join('<div class="kv"><span>%s</span><span>%s</span></div>' % (esc(k), v) for k, v in pairs)


def _nice_step(raw):
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if m * mag >= raw:
            return m * mag
    return 10 * mag


def chart(s2):
    """기간별 입금(확정/추정)·지급(확정/추정) 막대와 계산 잔액 선."""
    bs = s2["buckets"]
    if not bs:
        return ""
    Wd, H, pl, pr, pt, pb = 470, 250, 54, 10, 14, 52
    n = len(bs)
    gw = (Wd - pl - pr) / n
    has_bal = s2["start"] is not None  # 시작 잔액을 모르면 계산 잔액 선을 그리지 않는다 (0에서 시작하지 않음)
    vals = [0] + ([s2["start"]] if has_bal else [])
    for b in bs:
        vals += [b["in_firm"] + b["in_est"], -(b["out_firm"] + b["out_est"])]
        if has_bal:
            vals += [b["bal_firm"], b["bal_all"]]
    step = _nice_step((max(vals) - min(vals)) / 4 or 1)
    hi = step * math.ceil(max(vals) / step)
    lo = step * math.floor(min(vals) / step)
    if hi == lo:
        hi = lo + step
    span = hi - lo

    def y(v):
        return pt + (hi - v) * (H - pt - pb) / span

    out = ['<svg viewBox="0 0 %d %d" width="100%%" role="img" aria-label="기간별 입금·지급 예정과 계산 잔액">' % (Wd, H)]
    for k in range(int(round(span / step)) + 1):
        v = lo + step * k
        out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#e6e9ef"/>' % (pl, Wd - pr, y(v), y(v)))
        out.append('<text x="%d" y="%.1f" font-size="9.5" text-anchor="end" fill="#5b6475">%s</text>'
                   % (pl - 4, y(v) + 3, "{:,.0f}".format(v / 1e6)))
    out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#1d2433"/>' % (pl, Wd - pr, y(0), y(0)))
    bw = gw * 0.34
    pts_f, pts_a = [], []
    for i, b in enumerate(bs):
        x0 = pl + i * gw + gw * 0.14
        # 입금: 확정 아래, 추정 위에 쌓기
        y_f = y(b["in_firm"])
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#2f7d5b"/>' % (x0, y_f, bw, y(0) - y_f))
        y_e = y(b["in_firm"] + b["in_est"])
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#9cc9b3"/>' % (x0, y_e, bw, y_f - y_e))
        x1 = x0 + bw + 2
        y_of = y(-b["out_firm"])
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#b5523b"/>' % (x1, y(0), bw, y_of - y(0)))
        y_oe = y(-(b["out_firm"] + b["out_est"]))
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#e2aa9b"/>' % (x1, y_of, bw, y_oe - y_of))
        cx = pl + i * gw + gw / 2
        if has_bal:
            pts_f.append("%.1f,%.1f" % (cx, y(b["bal_firm"])))
            pts_a.append("%.1f,%.1f" % (cx, y(b["bal_all"])))
        lab = b["label"].replace(" (일부)", "*")
        if b["type"] == "month":
            lab = lab.split(" ")[1]
        out.append('<text x="%.1f" y="%d" font-size="9.5" text-anchor="middle" fill="#1d2433">%s</text>'
                   % (cx, H - pb + 14, esc(lab)))
    if has_bal:
        out.append('<polyline points="%s" fill="none" stroke="#1f4e8c" stroke-width="2"/>' % " ".join(pts_f))
        out.append('<polyline points="%s" fill="none" stroke="#1f4e8c" stroke-width="1.5" stroke-dasharray="4 3"/>'
                   % " ".join(pts_a))
        for p in pts_f:
            x_, y_ = p.split(",")
            out.append('<circle cx="%s" cy="%s" r="2.5" fill="#1f4e8c"/>' % (x_, y_))
    else:
        out.append('<text x="%d" y="%d" font-size="11" fill="#8a5a00">잔액 미확인 — 계산 잔액 선은 그리지 않음 (입금·지급 예정만 표시)</text>'
                   % (pl + 6, pt + 12))
    out.append('<text x="%d" y="%d" font-size="9.5" fill="#5b6475">단위: 백만원 · 4주는 주별, 이후는 월별 (* 일부 기간)</text>'
               % (pl, H - 8))
    out.append("</svg>")
    legend = ('<div class="legend"><span><i style="background:#2f7d5b"></i>입금 확정</span>'
              '<span><i style="background:#9cc9b3"></i>입금 추정</span><span><i style="background:#b5523b"></i>지급 확정</span>'
              '<span><i style="background:#e2aa9b"></i>지급 추정</span>')
    if has_bal:
        legend += ('<span><i style="background:#1f4e8c"></i>계산 잔액(확정)</span>'
                   '<span><i style="background:repeating-linear-gradient(90deg,#1f4e8c 0 3px,#fff 3px 5px)"></i>계산 잔액(확정+추정)</span>')
    legend += "</div>"
    return "".join(out) + legend


def render(R, mode):
    st = R["settings"]
    p0, p1 = R["period"]
    kind = "주간" if R["kind"] == "weekly" else "월간"
    who = "대표 보고" if mode == "ceo" else "경영관리 보고"
    s1, s2, s3, s4, s5, s6, s7 = (R[k] for k in ("s1", "s2", "s3", "s4", "s5", "s6", "s7"))
    per = "이번 주" if R["kind"] == "weekly" else "이번 달"
    h = []
    title = "%s %s %s" % (st.get("회사명", ""), kind, who)
    h.append("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
             "<meta name='viewport' content='width=device-width,initial-scale=1'><title>%s · %s</title><style>%s</style></head>"
             "<body><div class='wrap'>" % (esc(title), d2s(R["asof"]), CSS))
    h.append("<h1>%s<span class='badge%s'>%s</span></h1>" % (esc(title), "" if mode == "ceo" else " m",
                                                             "대표용" if mode == "ceo" else "경영관리용"))
    h.append("<div class='meta'>보고 기준일 %s · 집계 기간 %s ~ %s · 작성 %s · 금액 단위: 원 (첫 화면은 백만원)</div>"
             % (d2s(R["asof"]), d2s(p0), d2s(p1), dt.datetime.now().strftime("%Y-%m-%d %H:%M")))

    # ─────────── 첫 화면 ───────────
    h.append("<div class='page'>")
    restr_note = "사용제한 %s" % man(s1["restricted"])
    if s1["restr_unknown"]:
        restr_note += " · 제한금액 미확인 %d계좌" % s1["restr_unknown"]
    h.append("<div class='kpis'>")
    h.append(_kpi("현재 현금 (계좌 합계)", M(s1["total"]), esc("%d개 계좌 · 은행 기준일 %s" % (
        len(s1["accounts"]), _bank_dates(s1)) + _bal_note(s1)), unit=s1["total"] is not None))
    h.append(_kpi("사용 가능액", M(s1["available"]), esc(restr_note + _bal_note(s1)), unit=s1["available"] is not None))
    h.append(_kpi("향후 4주 입금예정", M(s2["in4_firm"] + s2["in4_est"]),
                  esc("확정 %s · 추정 %s" % (man(s2["in4_firm"]), man(s2["in4_est"])))))
    out4_sub = "확정 %s · 추정 %s" % (man(s2["out4_firm"]), man(s2["out4_est"]))
    if s2["vat_unknown_n4"]:
        out4_sub += " · 부가세 미확인 %d건 (공급가액만 반영)" % s2["vat_unknown_n4"]
    h.append(_kpi("향후 4주 지급예정", M(s2["out4_firm"] + s2["out4_est"]), esc(out4_sub)))
    h.append("</div>")
    # 중앙: 프로젝트 요약 + 자금 그래프
    h.append("<div class='mid'><div>")
    h.append("<h3 style='margin-top:0'>프로젝트 원가 예산·지급 (공급가액 기준, 카드는 총액)</h3>")
    tot = s3["total"]
    h.append("<div class='scope'>%s</div>"
             % esc("표시 %d건 / 전체 %d건 (원가 예산 큰 순) · 원가 예산 = 사전견적 × 원가율 %s · 전체 원가 예산 %s · 단위 백만원"
                   % (len(s3["shown"]), len(s3["projects"]), _rate_text(s3), man(tot["budget"], "판단 불가"))))
    rows = []
    for P in s3["shown"]:
        unk = _unknown_cost_note(P["unknown_cost"]) if P["budget"] is not None else ""
        rows.append([esc(P["id"]), esc(_short(P["name"], 22)),
                     M(P["budget"], "예산 미지정 (%s)" % P["budget_reason"] if P["budget_reason"] else "예산 미지정"),
                     M(P["paid_period"]),
                     _amt_lines(M, P["paid_total"], P, *PAID_STATES),
                     _amt_lines(M, P["requested"] + P["card_unpaid"], P, *UNPAID_STATES),
                     _amt_lines(M, P["planned"], P, *PLAN_STATES),
                     esc(pct(P["paid_total"], P["budget"])) + unk,
                     M(P["remain"], "판단 불가") if not (P["budget"] is not None and P["unknown_cost"]) else
                     _na("판단 불가" + _unknown_cost_text(P["unknown_cost"]))])
    if s3["rest"]:
        r = s3["rest"]
        ra = _agg_lines(r)
        rows.append(([esc("외 %d건" % len(r)), "", M(_sum_opt(x["budget"] for x in r)),
                      M(sum(x["paid_period"] for x in r)),
                      _amt_lines(M, sum(x["paid_total"] for x in r), ra, *PAID_STATES),
                      _amt_lines(M, sum(x["requested"] + x["card_unpaid"] for x in r), ra, *UNPAID_STATES),
                      _amt_lines(M, sum(x["planned"] for x in r), ra, *PLAN_STATES), "", ""], "sub"))
    note_nb = _no_budget_note(s3)
    total_row = ["전체", esc("%d건" % len(s3["projects"]) + (" · " + note_nb if note_nb else "")),
                 M(tot["budget"], "판단 불가"), M(tot["paid_period"]),
                 _amt_lines(M, tot["paid_total"], tot, *PAID_STATES),
                 _amt_lines(M, tot["requested"] + tot["card_unpaid"], tot, *UNPAID_STATES),
                 _amt_lines(M, tot["planned"], tot, *PLAN_STATES),
                 esc(pct(tot["paid_budgeted"], tot["budget"])) + (_unknown_cost_note(tot["unknown_cost"]) if tot["budget"] is not None else "") + "<sup>①</sup>",
                 M(tot["remain"], "판단 불가") + _na(_remain_excluded_text(tot)) + "<sup>①</sup>"]
    h.append(table(["번호", "프로젝트", "원가 예산", per + " 지급", "누적 지급", "요청·카드 미결제", "미요청 계획", "지급률",
                    "예상 잔여예산"], rows, num_cols=(2, 3, 4, 5, 6, 7, 8), total=total_row))
    h.append("<div class='note'>① 예산이 지정된 프로젝트만 계산. 예상 잔여예산 = 원가 예산 − (누적 지급 + 요청 미지급 + 카드 미결제 + 미요청 계획). "
             "금액 미확인 원가 줄이 있는 프로젝트는 잔여예산을 ‘판단 불가’로 두고 합계에서 뺌. 표의 금액은 확인된 것만의 합계이며 ‘미확인 N건’은 금액을 알 수 없는 줄 수. "
             "남은 예산은 ‘집행계획 미등록 금액’이며 지급예정으로 바꾸지 않음.</div>")
    h.append("</div><div>")
    h.append("<h3 style='margin-top:0'>%s</h3>" % esc("기간별 자금 (시작: 사용 가능액 %s%s)" % (man(s2["start"]), _bal_note(s1))))
    h.append(chart(s2))
    lf, lfd = s2["min"]["firm"]
    la, lad = s2["min"]["all"]
    h.append(kv([("최저 계산 잔액 · 확정 일정만", _min_cell(lf, lfd, s2["vat_unknown_firm_n"])),
                 ("최저 계산 잔액 · 확정+추정", _min_cell(la, lad, s2["vat_unknown_n"])),
                 ("날짜 없는 입금예정 / 지급예정",
                  _past_side(s2["undated_in_n"], s2["undated_in"], s2["undated_in_unknown"]) + " / " +
                  _past_side(s2["undated_out_n"], s2["undated_out"], s2["undated_out_unknown"])),
                 ("입금예정일 경과 미수 (일정 미포함)", "%d건 " % len(s5["overdue"]) + M(s5["overdue_total"])),
                 ("예정일 지난 미처리 입금 / 지급 (일정 미포함)",
                  _past_side(s2["past_in_n"], s2["past_in"], s2["past_in_unknown"]) + " / " +
                  _past_side(s2["past_out_n"], s2["past_out"], s2["past_out_unknown"]))]))
    h.append("</div></div>")
    # 하단 4칸
    h.append("<div class='low'>")
    h.append("<div class='card'><h4>매출·이익 (%s)</h4>%s</div>" % (esc(s4["ym"]), _pl_card(s4)))
    h.append("<div class='card'><h4>미수·미지급</h4>%s</div>" % kv([
        ("발행 후 미수", _na("미확인 %d건" % s5["ar_unknown_n"]) if s5["ar"] is None else
         M(s5["ar"]) + (_na(" · 미확인 %d건" % s5["ar_unknown_n"]) if s5["ar_unknown_n"] else "")), ("그중 입금예정일 경과", M(s5["overdue_total"])),
        ("프로젝트 요청 미지급", _amt_lines(M, tot["requested"], tot, "요청미지급")),
        ("카드 미결제 (프로젝트)", _amt_lines(M, tot["card_unpaid"], tot, "카드사용미결제")),
        ("프로젝트 밖 지급예정 (등록분 전체)", M(s6["total"]) + esc(" · 날짜 없음 %d건" % s6["undated_n"]) +
         (esc(" · 금액 미확인 %d건" % s6["unknown_n"]) if s6["unknown_n"] else ""))]))
    h.append("<div class='card'><h4>계산서 미발행</h4>%s</div>" % kv([
        ("계약금액", _amt_unk(s5["contract"], s5["contract_missing"], "미등록", M)),
        ("발행금액", _amt_unk(s5["issued"], s5["issued_unknown_n"], "미확인", M)),
        ("미발행금액", _amt_unk(s5["unissued"], s5["unissued_unknown_n"], "판단 불가", M)),
        ("완료 후 미발행 프로젝트", "%d건" % len([x for x in s5["unissued_aged"] if x["unissued"] > 0])),
        ("계약금액 미등록 프로젝트", "%d건" % s5["contract_missing"])]))
    h.append("<div class='card'><h4>자료 기준일·미반영</h4>%s</div>" % kv(
        [(a["name"], esc(d2s(a["date"]))) for a in s7["asof"]] +
        [("예산 미지정 프로젝트", "%d건" % len(s7["no_budget"])),
         ("프로젝트 미연결 지급", M(s7["unlinked_txn_total"] + s3["unlinked_total"])),
         ("입력 자료 확인 필요", "%d건" % len(s7["issues"]))]))
    h.append("</div>")
    if mode == "mgmt":
        hi = sum(1 for r in R["risks"] if r["level"] == "높음")
        h.append("<div class='note' style='margin-top:10px'>위험 항목 %d건 (높음 %d건) — 아래 ‘위험 분석·해결방안’ 참조</div>"
                 % (len(R["risks"]), hi))
    h.append("</div>")  # page

    h.append("<div class='toc'>상세자료: " + " ".join(
        '<a href="#s%d">%d. %s</a>' % (i, i, t) for i, t in enumerate(
            ["현재 자금·입출금", "입금·지급 일정", "프로젝트 예산·집행", "매출·손익", "계산서·수금", "프로젝트 밖 지급", "변동·자료 범위"], 1))
             + (' <a href="#risk">위험 분석</a>' if mode == "mgmt" else "") + "</div>")

    if mode == "mgmt":
        h.append(_risk_section(R))

    h.append(_s1(R, per))
    h.append(_s2(R))
    h.append(_s3(R, per))
    h.append(_s4(R))
    h.append(_s5(R))
    h.append(_s6(R))
    h.append(_s7(R))
    h.append("</div></body></html>")
    return "".join(h)


def _kpi(label, value, sub, unit=True):
    if unit:
        value += " <span class='u'>백만원</span>"
    return "<div class='kpi'><div class='l'>%s</div><div class='v'>%s</div><div class='s'>%s</div></div>" % (
        esc(label), value, sub)


def _min_cell(low, day, vat_n):
    """최저 계산 잔액 칸. 시작 잔액을 모르면 숫자를 만들지 않고 '잔액 미확인'만 보인다."""
    if low is None:
        return _na("잔액 미확인")
    return "%s (%s)%s" % (M(low), esc(d2s(day)), _vat_note(vat_n))


def _won_or_unknown(v):
    return "잔액 미확인" if v is None else won(v) + "원"


def _min_cell_won(low, day, vat_n):
    if low is None:
        return _na("잔액 미확인")
    return esc("%s원 (%s)" % (won(low), d2s(day))) + _vat_note(vat_n)


def _vat_note(n):
    """부가세 빈칸으로 공급가액만 반영된 건수 표시 (없으면 빈 문자열)."""
    return _na(" · 부가세 미확인 %d건" % n) if n else ""


def _past_side(n, amt, unk):
    """예정일 지난 미처리 한쪽(입금 또는 지급): 건수와 확인된 금액, 금액 미확인 건수."""
    out = "%d건 " % n + M(amt)
    if unk:
        out += _na(" · 금액 미확인 %d건" % unk)
    return out


def _bal_note(s1):
    """잔액 빈칸 계좌가 합계에서 빠졌음을 알리는 보조 문구 (없으면 빈 문자열)."""
    n = s1["bal_unknown"]
    if n:
        return " · 잔액 미확인 %d계좌 (합계 제외)" % n
    if s1["total"] is None:
        return " · 잔액 미확인 (계좌 자료 없음)"
    return ""


def _bank_dates(s1):
    ds = sorted(set(a["date"] for a in s1["accounts"]))
    if not ds:
        return "자료 없음"
    return d2s(ds[0]) if len(ds) == 1 else "%s~%s" % (d2s(ds[0]), d2s(ds[-1]))


def _amt_unk(v, unk, label="미확인", fmt=W):
    """금액 칸 + 금액을 알 수 없는 건수. 값이 없고 미확인 건만 있으면 '미확인 N건'."""
    if v is None:
        return _na("%s %d건" % (label, unk)) if unk > 0 else fmt(None)
    return fmt(v) + (_na(" 외 %s %d건" % (label, unk)) if unk > 0 else "")


def _no_budget_note(s3):
    """'예산 미책정 N건 (사유별 건수)'. 없으면 빈 글자."""
    reasons = s3["no_budget_reasons"]
    if not reasons:
        return ""
    return "예산 미책정 %d건 (%s)" % (sum(reasons.values()), ", ".join("%s %d건" % (k, n) for k, n in reasons.items()))


def _rate_text(s3):
    rate = s3["cost_rate"]
    return "원가율 설정 오류" if rate is None else "%g%%" % round(rate * 100, 6)


PAID_STATES = ("지급완료", "카드결제완료")
UNPAID_STATES = ("요청미지급", "카드사용미결제")
PLAN_STATES = ("집행계획미요청",)


def _amt_lines(fmt, v, obj, *states):
    """확인된 금액 합계 + 금액을 알 수 없는 줄 수. 해당 줄이 모두 미확인이면 0이 아니라 '미확인 N건'만 보인다 (D-02).

    obj는 프로젝트 한 건 또는 합계(line_n, line_unknown을 가진 dict)."""
    n = sum(obj["line_n"][s] for s in states)
    unk = sum(obj["line_unknown"][s] for s in states)
    if unk and unk >= n:
        return _na("미확인 %d건" % unk)
    return fmt(v) + (_na(" 외 미확인 %d건" % unk) if unk else "")


def _agg_lines(plist):
    states = plist[0]["line_n"].keys() if plist else ()
    return {"line_n": {s: sum(P["line_n"][s] for P in plist) for s in states},
            "line_unknown": {s: sum(P["line_unknown"][s] for P in plist) for s in states}}


def _unknown_cost_text(n):
    return " (미확인 원가 %d건)" % n if n else ""


def _unknown_cost_note(n):
    return _na(_unknown_cost_text(n)) if n else ""


def _remain_excluded_text(tot):
    n = tot["remain_excluded"]
    return " · 미확인 원가 %d개 프로젝트 제외" % n if n else ""


def _short(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"


def _sum_opt(vals):
    vals = list(vals)
    known = [v for v in vals if v is not None]
    return sum(known) if known else None


def _pl_card(s4):
    src = s4["sources"].get("WEHAGO")
    pairs = []
    if not src:
        return kv([("WEHAGO 손익", _na("자료 없음"))])
    co = [r for r in src["table"] if r["unit"] == "회사"]
    if not co:
        return kv([("WEHAGO 회사 손익", _na("자료 없음"))])
    c, y = co[0]["cur"], co[0]["ytd"]
    if c:
        pairs += [("당월 매출", M(c["revenue"])), ("당월 이익 (공통비 차감)", M(c["np"], "판단 불가") +
                                                 (" <span class='na'>잠정</span>" if c["provisional"] else "")),
                  ("당월 이익률", esc(pct(c["np"], c["revenue"])))]
    else:
        pairs.append(("당월", _na("자료 없음 (최근 %s)" % (src["latest"] or "-"))))
    if y:
        pairs += [("연누적 매출", M(y["revenue"])), ("연누적 이익", M(y["np"], "판단 불가"))]
    pairs.append(("계약 중 매출 미반영", _amt_unk(s4["unrecognized"], s4["unrecognized_missing"], "미확인", M)))
    return kv(pairs)


def _h2(i, t, anchor=None):
    return "<h2 id='%s'>%s</h2>" % (anchor or "s%d" % i, ("%d. " % i if i else "") + esc(t))


def _s1(R, per):
    s1 = R["s1"]
    h = [_h2(1, "현재 자금과 %s 입출금" % per)]
    rows = []
    for a in s1["accounts"]:
        fl = s1["acct_flow"].get(a["account"], [0, 0])
        avail = None if a["balance"] is None else a["balance"] - (a["restricted"] or 0)
        rows.append([esc(a["account"]), esc(a["bank"]), esc(d2s(a["date"])), W(a["balance"]), W(a["restricted"]),
                     esc(a["reason"]), W(avail), W(fl[0]), W(fl[1])])
    h.append("<h3>계좌별 잔액</h3>")
    h.append(table(["계좌", "은행", "잔액 기준일", "잔액", "사용제한", "제한 사유", "사용 가능액", per + " 입금", per + " 출금"],
                   rows, num_cols=(3, 4, 6, 7, 8),
                   total=["합계", "", "", W(s1["total"]), W(s1["restricted"]), "", W(s1["available"]), "", ""]))
    if not s1["accounts"]:
        h.append("<div class='note'>%s</div>" % esc("잔액 미확인 — 계좌 잔액 자료가 없어 현재 현금·사용 가능액을 계산하지 않음."))
    if s1["bal_unknown"]:
        txt = "잔액 미확인 %d계좌 (합계 제외): %s" % (s1["bal_unknown"], ", ".join(s1["bal_unknown_names"]))
        if s1["bal_unknown_restricted"]:
            txt += " · 이 계좌의 사용제한 %s원은 사용 가능액에서 차감" % won(s1["bal_unknown_restricted"])
        h.append("<div class='note'>%s</div>" % esc(txt))
    h.append("<div class='note'>계좌별 입금·출금에는 회사 계좌 간 이체가 포함됨. 아래 회사 전체 입출금에서는 제외.</div>")
    h.append("<h3>회사 전체 입출금 (계좌 간 이체 제외)</h3>")
    pairs = [("기간 시작 잔액 (거래로 역산)", W(s1["start_calc"]))]
    if s1["start_bank"] is not None:
        pairs.append(("기간 시작 잔액 (은행 잔액)", W(s1["start_bank"])))
    pairs += [(per + " 실제 입금", W(s1["in"])), (per + " 실제 출금", W(s1["out"])), ("기간 말 잔액", W(s1["end"])),
              ("계좌 간 이체 (참고, 입금/출금)", "%s / %s" % (W(s1["transfer_in"]), W(s1["transfer_out"])))]
    h.append("<div style='max-width:520px'>%s</div>" % kv(pairs))
    rows = [[esc(k), W(v[0]), W(v[1])] for k, v in sorted(s1["by_cat"].items(), key=lambda kv_: -kv_[1][1])]
    h.append("<h3>분류별</h3>")
    h.append(table(["분류", "입금", "출금"], rows, num_cols=(1, 2), total=["합계", W(s1["in"]), W(s1["out"])]))
    h.append("<h3>%s 거래 내역 (%d건)</h3>" % (per, len(s1["txns"])))
    rows = [[esc(d2s(t["date"])), esc(t["account"]), esc(t["io"]), W(t["amount"]), esc(t["cat"]), esc(t["project"]),
             esc(t["vendor"]), esc(t["memo"])] for t in s1["txns"]]
    h.append(table(["일자", "계좌", "구분", "금액", "분류", "프로젝트", "거래처", "적요"], rows, num_cols=(3,)))
    return "".join(h)


def _s2(R):
    s2 = R["s2"]
    h = [_h2(2, "앞으로의 입금·지급 일정과 계산 잔액")]
    h.append("<div class='note'>%s</div>" % esc(
        "시작값은 보고 기준일 사용 가능액 %s%s. 확정·추정을 나누어 표시. 날짜 없는 금액과 입금예정일이 지난 미수는 아래 표로 따로 둠.%s"
        % (_won_or_unknown(s2["start"]), _bal_note(R["s1"]),
           " 부가세 미확인 %d건은 공급가액만 반영." % s2["vat_unknown_n"] if s2["vat_unknown_n"] else "")))
    rows = []
    for b in s2["buckets"]:
        rows.append([esc(b["label"]), esc("%s ~ %s" % (d2s(b["from"]), d2s(b["to"]))), W(b["in_firm"]), W(b["in_est"]),
                     W(b["out_firm"]), W(b["out_est"]), W(b["bal_firm"]), W(b["bal_all"])])
    h.append(table(["구간", "기간", "입금 확정", "입금 추정", "지급 확정", "지급 추정", "계산 잔액 (확정)", "계산 잔액 (확정+추정)"],
                   rows, num_cols=(2, 3, 4, 5, 6, 7)))
    m3 = [b for b in s2["buckets"] if b["type"] == "week" or b.get("within3")]
    if s2["start"] is None:
        h.append("<div class='note'>%s</div>" % esc("시작 잔액 미확인 — 구간별 계산 잔액, 3·6개월 시점 잔액, 최저 계산 잔액은 계산하지 않음."))
    else:
        h.append("<div class='note'>3개월 시점(%s) 계산 잔액: 확정 %s원 / 확정+추정 %s원 · 6개월 시점(%s): 확정 %s원 / 확정+추정 %s원</div>"
                 % (d2s(m3[-1]["to"]), won(m3[-1]["bal_firm"]), won(m3[-1]["bal_all"]), d2s(s2["buckets"][-1]["to"]),
                    won(s2["buckets"][-1]["bal_firm"]), won(s2["buckets"][-1]["bal_all"])))
    lf, lfd = s2["min"]["firm"]
    la, lad = s2["min"]["all"]
    h.append(kv([("기간 중 최저 계산 잔액 · 확정 일정만", _min_cell_won(lf, lfd, s2["vat_unknown_firm_n"])),
                 ("기간 중 최저 계산 잔액 · 확정+추정", _min_cell_won(la, lad, s2["vat_unknown_n"]))]))
    ev_rows = lambda evs: [[esc(d2s(e["date"])), esc("입금" if e["io"] == "in" else "지급"),
                            W(e["amount"]) + (_na(" 부가세 미확인") if e.get("vat_unknown") and e["amount"] is not None else ""),
                            esc("확정" if e["firm"] else "추정"), esc(e["cat"]), esc(e["project"]), esc(e["desc"]),
                            esc(e["basis"]), esc(e["source"])] for e in evs]
    head = ["예정일", "구분", "금액", "확정", "분류", "프로젝트", "거래처·내용", "근거", "원천"]
    h.append("<h3>날짜 없는 예정금액 (일정·그래프 미포함, %d건)</h3>" % len(s2["undated"]))
    h.append(table(head, ev_rows(s2["undated"]), num_cols=(2,)))
    h.append("<h3>예정일이 이미 지난 미처리 예정금액 (일정 미포함, %d건)</h3>" % len(s2["past"]))
    h.append(table(head, ev_rows(sorted(s2["past"], key=lambda e: e["date"])), num_cols=(2,)))
    if s2["amount_unknown"]:
        h.append("<h3>금액 미확인 예정 (%d건)</h3>" % len(s2["amount_unknown"]))
        h.append(table(head, ev_rows(s2["amount_unknown"]), num_cols=(2,)))
    if s2["beyond"]:
        h.append("<h3>6개월 이후 예정 (%d건)</h3>" % len(s2["beyond"]))
        h.append(table(head, ev_rows(sorted(s2["beyond"], key=lambda e: e["date"])), num_cols=(2,)))
    dated = sorted([e for e in R["events"] if e["amount"] is not None and e["date"] and R["asof"] < e["date"] <= s2["horizon"]],
                   key=lambda e: (e["date"], e["io"]))
    h.append("<h3>기간 내 예정 전체 (%d건)</h3>" % len(dated))
    h.append(table(head, ev_rows(dated), num_cols=(2,)))
    h.append("<div class='note'>프로젝트 카드 미결제는 카드대금 일정(자금일정)에 포함되므로 여기서 따로 더하지 않음. "
             "프로젝트 지급요청은 공급가액+부가세(실제 출금액)로 반영. "
             "부가세가 비어 있으면 공급가액만 반영하고 ‘부가세 미확인’으로 표시.</div>")
    return "".join(h)


def _s3(R, per):
    s3 = R["s3"]
    tot = s3["total"]
    h = [_h2(3, "프로젝트별 예산·지급·남은 집행")]
    note_nb = _no_budget_note(s3)
    h.append("<div class='scope'>%s</div>" % esc("전체 %d건 모두 표시 · 원가 예산 = 사전견적 × 원가율 %s" % (len(s3["projects"]), _rate_text(s3))
                                                   + (" · " + note_nb if note_nb else "")))
    rows = []
    for P in s3["ranked"]:
        rows.append([esc(P["id"]), esc(P["name"]), esc(P["team"]), esc(P["state"]), W(P["estimate"], "-"),
                     W(P["budget"], "예산 미지정"), _na(P["budget_reason"]) if P["budget_reason"] else "",
                     esc(d2s(P["budget_date"], "-")), W(P["paid_period"]), W(P["paid_total"]),
                     W(P["paid_cash"], "부가세 미확인"), W(P["requested"]), W(P["card_unpaid"]), W(P["planned"]),
                     W(P["expected"]), esc(pct(P["paid_total"], P["budget"])), W(P["remain"], "판단 불가"),
                     esc("%d건" % P["unknown_cost"]) if P["unknown_cost"] else ""])
    h.append(table(["번호", "프로젝트", "팀", "상태", "사전견적", "원가 예산", "예산 사유", "예산 수정일", per + " 지급", "누적 지급",
                    "지급 실출금(VAT포함)", "요청 미지급", "카드 미결제", "미요청 계획", "예상 총집행", "지급률", "예상 잔여예산",
                    "금액 미확인"], rows, num_cols=(4, 5, 8, 9, 10, 11, 12, 13, 14, 15, 16),
                   total=["전체", "%d건" % len(s3["projects"]), "", "", W(tot["estimate"]), W(tot["budget"], "판단 불가"),
                          esc(note_nb), "", W(tot["paid_period"]),
                          W(tot["paid_total"]), _amt_unk(tot["paid_cash"], tot["paid_cash_unknown"], "부가세 미확인"), W(tot["requested"]), W(tot["card_unpaid"]),
                          W(tot["planned"]), W(tot["expected"]), esc(pct(tot["paid_budgeted"], tot["budget"])),
                          W(tot["remain"], "판단 불가") + _na(_remain_excluded_text(tot)), "%d건" % tot["unknown_cost"]]))
    h.append("<div class='note'>원가 예산 = 사전견적(예상 매출) × 원가율 (설정.csv 예산_원가율, 기본 0.70). "
             "사전견적이 없거나 0원 이하·해석 불가이거나 원가율 설정 오류면 ‘예산 미지정’, 지급률·잔여예산은 ‘판단 불가’, 이유는 ‘예산 사유’ 열. "
             "지급·요청·계획은 공급가액. 카드 사용액은 총액. ‘지급 실출금’은 지급완료분 공급가액+부가세. "
             "누적 지급 = 지급완료 + 카드결제완료. "
             "예상 잔여예산은 ‘집행계획 미등록 금액’이며 지급예정이 아님. 합계의 지급률·잔여예산은 예산 지정 프로젝트만.</div>")
    if s3["unlinked"]:
        h.append("<h3>프로젝트 미연결 집행 (%d건, %s원)</h3>" % (len(s3["unlinked"]), won(s3["unlinked_total"])))
        h.append(_exec_table(s3["unlinked"]))
    h.append("<h3>집행 항목 전체</h3>")
    lines = [e for P in s3["ranked"] for e in P["lines"]]
    h.append(_exec_table(lines))
    return "".join(h)


def _exec_table(lines):
    rows = [[esc(e["project"]), esc(e["item"]), esc(e["vendor"]), esc(e["state"]), W(e["supply"]), W(e["vat"], "-"),
             esc(d2s(e["date"], "-")), esc("확정" if e["firm"] else "추정"), esc(e["basis"])] for e in lines]
    return table(["프로젝트", "항목", "거래처", "상태", "공급가액(카드는 총액)", "부가세", "일자", "확정", "근거"], rows,
                 num_cols=(4, 5))


def _pl_row(label, x, unit, target):
    if not x:
        return [esc(label), esc(unit), esc(target), _na("자료 없음"), "", "", "", "", "", "", ""]
    return [esc(label), esc(unit), esc(target), W(x["revenue"]), W(x["direct"]), W(x["gp"], "판단 불가"),
            esc(pct(x["gp"], x["revenue"])), W(x["common"], "-"), W(x["np"], "-"), esc(pct(x["np"], x["revenue"], "-")),
            esc("잠정" if x["provisional"] else "")]


def _s4(R):
    s4 = R["s4"]
    h = [_h2(4, "회사·팀·프로젝트의 매출과 손익")]
    h.append("<div class='note'>당월 = %s. 직접비 차감 이익과 공통비 차감 손익을 나눔. 회계 미반영 비용이 있는 달은 ‘잠정’. "
             "금액이 비어 있으면 0으로 넣지 않고 ‘판단 불가’. 이익과 현금잔액은 별개 지표.</div>" % esc(s4["ym"]))
    if not s4["sources"]:
        h.append("<div class='note na'>손익 자료 없음</div>")
    for src, v in s4["sources"].items():
        h.append("<h3>%s 손익 (최근 반영월 %s)</h3>" % (esc(src), esc(v["latest"] or "-")))
        rows = []
        for r in v["table"]:
            rows.append(_pl_row("당월", r["cur"], r["unit"], r["target"]))
            rows.append((_pl_row("연누적", r["ytd"], r["unit"], r["target"]), "sub"))
        h.append(table(["구분", "단위", "대상", "매출", "직접비", "직접비 차감 이익", "이익률", "공통비", "공통비 차감 손익",
                        "손익률", "비고"], rows, num_cols=(3, 4, 5, 6, 7, 8, 9)))
    h.append("<h3>프로젝트 계약·매출 반영·종료 시점 예상이익 (인트라넷·집행자료 기준)</h3>")
    rows = []
    for P in s4["projects"]:
        rows.append([esc(P["id"]), esc(P["name"]), W(P["contract"], "계약금액 미등록"), W(P["recognized"]),
                     W(P["unrecognized"], "판단 불가"), W(P["expected"]),
                     W(P["profit_end"], "판단 불가") + (" <span class='na'>(미확인 원가 %d건)</span>" % P["unknown_cost"]
                                                       if P["unknown_cost"] else ""),
                     esc(pct(P["profit_end"], P["contract"]))])
    h.append(table(["번호", "프로젝트", "계약금액", "매출 반영 누계", "계약 중 매출 미반영", "예상 총집행", "종료 시점 예상이익",
                    "예상이익률"], rows, num_cols=(2, 3, 4, 5, 6, 7),
                   total=["전체", "", _amt_unk(R["s5"]["contract"], R["s5"]["contract_missing"], "미등록"), "",
                          _amt_unk(s4["unrecognized"], s4["unrecognized_missing"]), W(R["s3"]["total"]["expected"]),
                          "", ""]))
    h.append("<div class='note'>예상이익 = 계약금액 − 예상 총집행(누적 지급 + 요청 미지급 + 카드 미결제 + 미요청 계획). "
             "금액 미확인 원가가 있으면 ‘판단 불가’.</div>")
    return "".join(h)


def _s5(R):
    s5 = R["s5"]
    h = [_h2(5, "계산서 발행과 수금 현황")]
    rows = []
    for x in s5["by_project"]:
        P = x["P"]
        rows.append([esc(P["id"]), esc(P["name"]), esc(d2s(P["done_date"], "-")), W(P["contract"], "계약금액 미등록"),
                     _amt_unk(x["issued"], x["issued_unknown"]), W(x["unissued"], "판단 불가"), _amt_unk(x["ar"], x["ar_unknown"]),
                     esc("%d일" % x["unissued_days"]) if x["unissued_days"] is not None else
                     ("<span class='note'>완료일 미확인</span>" if x["unissued"] and not P["done_date"] else "")])
    h.append(table(["번호", "프로젝트", "완료일", "계약금액(공급가)", "발행금액(공급가)", "미발행금액", "발행 후 미수(VAT포함)",
                    "완료 후 미발행 경과"], rows, num_cols=(3, 4, 5, 6, 7),
                   total=["전체", "", "", _amt_unk(s5["contract"], s5["contract_missing"], "미등록"),
                          _amt_unk(s5["issued"], s5["issued_unknown_n"]),
                          _amt_unk(s5["unissued"], s5["unissued_unknown_n"], "판단 불가"),
                          _amt_unk(s5["ar"], s5["ar_unknown_n"]), ""]))
    h.append("<div class='note'>미발행금액 = 계약금액 − 발행금액(공급가). 미수 = 발행 합계(VAT포함) − 입금액. "
             "완료일이 없으면 미발행 경과일을 계산하지 않음.</div>")
    h.append("<h3>발행 후 미수 (%d건)</h3>" % len(s5["ar_rows"]))
    rows = [[esc(v["project"]), esc(v["client"]), esc(d2s(v["date"])), esc(v["kind"]), W(v["total"]), W(v["paid"], "0"),
             W(v["outstanding"]), esc(d2s(v["due"])), esc("확정" if v["due_firm"] else "추정"),
             esc("%d일" % v["overdue_days"]) if "overdue_days" in v else ""] for v in s5["ar_rows"]]
    h.append(table(["프로젝트", "거래처", "발행일", "구분", "합계", "입금액", "미수", "입금예정일", "예정일", "예정일 경과"], rows,
                   num_cols=(4, 5, 6, 9), total=["합계", "", "", "", "", "", W(sum(v["outstanding"] for v in s5["ar_rows"])), "", "", ""]))
    h.append("<h3>선수금·취소·환불·수정 (%d건)</h3>" % len(s5["specials"]))
    rows = [[esc(v["project"]), esc(v["client"]), esc(d2s(v["date"])), esc(v["kind"]), W(v["supply"]), W(v["vat"]),
             W(v["paid"], "-"), esc(d2s(v["paid_date"], "-"))] for v in s5["specials"]]
    h.append(table(["프로젝트", "거래처", "발행일", "구분", "공급가액", "부가세", "입금액", "입금일"], rows, num_cols=(4, 5, 6)))
    if s5["no_project"]:
        h.append("<h3>프로젝트 미연결 계산서 (%d건)</h3>" % len(s5["no_project"]))
        rows = [[esc(v["project"] or "-"), esc(v["client"]), esc(d2s(v["date"])), W(v["supply"])] for v in s5["no_project"]]
        h.append(table(["프로젝트", "거래처", "발행일", "공급가액"], rows, num_cols=(3,)))
    return "".join(h)


def _vendor_unknown(v):
    parts = []
    if v["unknown"]:
        parts.append("미확인 %d건" % v["unknown"])
    if v["vat_unknown"]:
        parts.append("부가세 미확인 %d건" % v["vat_unknown"])
    return _na(" · ".join(parts)) if parts else ""


def _s6(R):
    s6 = R["s6"]
    h = [_h2(6, "프로젝트 밖에서 나가는 돈과 남은 지급의무")]
    h.append("<div class='note'>자금일정.csv의 지급 항목. 프로젝트 지급요청과 카드 미결제는 3번에 있으며 여기 다시 더하지 않음 "
             "(카드대금은 카드사 청구 기준으로만 반영).</div>")
    rows = [[esc(k), "%d건" % len(g["rows"]), W(g["total"]), "%d건" % g["undated"] if g["undated"] else "",
             "%d건" % g["unknown"] if g["unknown"] else ""] for k, g in s6["by_cat"].items()]
    h.append(table(["분류", "건수", "금액", "지급일 없음", "금액 미확인"], rows, num_cols=(2,),
                   total=["합계", "", W(s6["total"]), "", ""]))
    h.append("<h3>거래처별 미지급 잔액과 가장 가까운 지급일 (프로젝트 지급요청 포함)</h3>")
    rows = [[esc(k), "%d건" % v["n"], W(v["total"]), _vendor_unknown(v), esc(d2s(v["next"]))] for k, v in s6["vendors"]]
    h.append(table(["거래처", "건수", "미지급 잔액", "금액 미확인", "가장 가까운 지급일"], rows, num_cols=(2,)))
    h.append("<h3>지급 항목 전체</h3>")
    rows = [[esc(s["cat"]), esc(d2s(s["date"])), W(s["amount"]), esc("확정" if s["firm"] else "추정"), esc(s["vendor"]),
             esc(s["basis"]), esc(s["memo"])] for g in s6["by_cat"].values() for s in g["rows"]]
    h.append(table(["분류", "예정일", "금액", "확정", "거래처", "근거", "비고"], rows, num_cols=(2,)))
    return "".join(h)


def _s7(R):
    s7 = R["s7"]
    p0, p1 = R["period"]
    h = [_h2(7, "지난 보고 이후 변동과 자료 반영 범위")]
    h.append("<h3>변경 전후 (%s ~ %s, %d건)</h3>" % (d2s(p0), d2s(p1), len(s7["changes"])))
    rows = [[esc(d2s(c["date"])), esc(c["field"]), esc(c["target"]), esc(c["before"]), esc(c["after"]), esc(c["reason"])]
            for c in s7["changes"]]
    h.append(table(["변경일", "항목", "대상", "변경 전", "변경 후", "사유"], rows))
    h.append("<h3>지급계획 대비 실제 지급</h3>")
    rows = []
    for x in s7["pva"]:
        if x["unplanned"]:
            plan_cell = _na("계획 없음")
        elif x["plan"] is None:
            plan_cell = _na("미확인")
        else:
            plan_cell = W(x["plan"]) + (_na(" 외 미확인 %d건" % x["plan_unknown"]) if x["plan_unknown"] else "")
        rows.append([esc(x["project"] or "-"), esc(x["vendor"]), plan_cell, W(x["actual"]),
                     W(None if x["plan"] is None else x["actual"] - x["plan"], "-")])
    diff_cell = W(s7["actual_total"] - s7["plan_total"]) if not s7["plan_unknown_n"] else _na("판단 불가")
    h.append(table(["프로젝트", "거래처", "계획", "실제 출금", "차이"], rows, num_cols=(2, 3, 4),
                   total=["합계", "", W(s7["plan_total"]), W(s7["actual_total"]), diff_cell]))
    h.append("<div class='note'>계획 외 지급액 %s원. 실제 출금은 계좌 간 이체를 뺀 기간 내 전체 출금.%s</div>"
             % (won(s7["unplanned_total"]),
                esc(" 계획 금액 미확인 %d건 (합계 제외)." % s7["plan_unknown_n"]) if s7["plan_unknown_n"] else ""))
    h.append("<h3>미반영·미연결 현황</h3>")
    h.append("<div style='max-width:620px'>%s</div>" % kv([
        ("예산 미지정 프로젝트", "%d건 · 계약 %s원%s · 예상 총집행 %s원"
         % (len(s7["no_budget"]), won(s7["no_budget_contract"]),
            " (계약금액 미등록 %d건)" % s7["no_budget_contract_missing"] if s7["no_budget_contract_missing"] else "",
            won(s7["no_budget_expected"]))),
        ("프로젝트 미연결 지급 (출금 내역)", "%s원 (%d건)" % (won(s7["unlinked_txn_total"]), len(s7["unlinked_txn"]))),
        ("프로젝트 미연결 집행 (집행 자료)", "%s원 (%d건)" % (won(R["s3"]["unlinked_total"]), len(R["s3"]["unlinked"]))),
        ("지급일 미등록 지급예정", "%s (%d건%s)" % (
            "금액 미확인" if s7["undated_out"] is None else won(s7["undated_out"]) + "원", s7["undated_out_n"],
            " · 금액 미확인 %d건" % s7["undated_out_unknown"] if s7["undated_out_unknown"] else "")),
        ("잔액 기준일이 보고일보다 이른 계좌", "%d개" % len(s7["stale"]))]))
    if s7["no_budget"]:
        rows = [[esc(P["id"]), esc(P["name"]), _na(P["budget_reason"]), W(P["contract"], "미등록"), W(P["expected"])]
                for P in s7["no_budget"]]
        h.append(table(["번호", "예산 미지정 프로젝트", "예산 사유", "계약금액", "예상 총집행"], rows, num_cols=(3, 4)))
    h.append("<h3>자료 기준일</h3>")
    rows = [[esc(a["name"]), esc(d2s(a["date"])), esc("" if a["age"] is None else "%d일 전" % a["age"]), esc(a["memo"])]
            for a in s7["asof"]]
    h.append(table(["자료", "기준일", "보고일 기준", "비고"], rows))
    h.append("<h3>원천자료 간 금액 차이</h3>")
    rows = [[esc(x["item"]), esc(x["a"]), W(x["a_amt"]), esc(x["b"]), W(x["b_amt"]),
             W(None if x["a_amt"] is None or x["b_amt"] is None else x["a_amt"] - x["b_amt"], "-"), esc(x["state"])]
            for x in s7["diffs"]]
    h.append(table(["항목", "자료 A", "금액 A", "자료 B", "금액 B", "차이", "상태"], rows, num_cols=(2, 4, 5)))
    h.append("<h3>보고 대조 (요약과 상세 합계)</h3>")
    rows = [[esc(c[0]), W(c[1]), W(c[2]), "<span class='ok'>일치</span>" if c[3] else "<span class='ng'>불일치</span>"]
            for c in s7["checks"]]
    h.append(table(["대조 항목", "값 A", "값 B", "결과"], rows, num_cols=(1, 2)))
    h.append("<h3>입력 자료 확인 필요 (%d건)</h3>" % len(s7["issues"]))
    rows = [[esc(f), esc(l), esc(m)] for f, l, m in s7["issues"]]
    h.append(table(["파일", "줄", "내용"], rows))
    return "".join(h)


def _num_text(v):
    return "%d" % v if isinstance(v, int) else "%g" % v


def _risk_section(R):
    h = [_h2(0, "위험 분석·해결방안 (경영관리 전용)", "risk")]
    sn, sd = R["settings_num"], R["settings_default"]

    def part(key, fmt):
        mark = " · 기본값 사용(%s)" % sd[key] if key in sd else ""
        return fmt % _num_text(sn[key]) + mark

    h.append("<div class='note'>아래 숫자는 대표 보고와 같은 계산 결과에서 가져옴. 기준값은 설정.csv에서 바꿀 수 있음 (%s).</div>"
             % esc(", ".join([
                 "최소 보유현금 %s원" % won(sn["위험_최소보유현금"]) + (" · 기본값 사용(%s)" % sd["위험_최소보유현금"]
                                                                if "위험_최소보유현금" in sd else ""),
                 part("위험_미수경과일", "미수 경과 %s일"), part("위험_미발행경과일", "미발행 경과 %s일"),
                 part("위험_자료경과일", "자료 경과 %s일"), part("위험_예산초과율", "예산 초과율 %s%%")])))
    body = "".join('<tr class="%s"><td class="lv">%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
        "h" if r["level"] == "높음" else "", esc(r["level"]), esc(r["area"]), esc(r["fact"]), esc(r["action"]))
        for r in R["risks"]) or '<tr><td colspan="4" class="note">해당 없음</td></tr>'
    h.append('<div class="tw"><table class="risk"><thead><tr><th>등급</th><th>영역</th><th>근거 (숫자)</th><th>해결방안</th>'
             '</tr></thead><tbody>%s</tbody></table></div>' % body)
    return "".join(h)
