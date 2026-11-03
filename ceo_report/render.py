"""HTML 보고서 만들기. mode='ceo'(대표용) 또는 'mgmt'(경영관리용).

두 보고서는 같은 계산 결과 R을 쓴다. 경영관리용에만 '위험 분석·해결방안'이 붙는다.
대표용에는 해석·권고 문구를 넣지 않는다.
"""
import datetime as dt
import math
import re
from collections import OrderedDict

from .util import won, man, pct, d2s, esc, date as parse_date

CSS = """
:root{--ink:#1d2433;--sub:#5b6475;--line:#d9dde5;--soft:#f3f5f8;--accent:#1f4e8c;--in:#2f7d5b;--out:#b5523b;
--est:#9aa3b2;--warn:#8a5a00;--bg:#fff}
*{box-sizing:border-box}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.45 "Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif;
word-break:keep-all;overflow-wrap:break-word}
.wrap{max-width:1180px;margin:0 auto;padding:24px 20px 60px}
h1{font-size:22px;margin:0}
h2{font-size:16px;margin:28px 0 8px;padding-bottom:6px;border-bottom:2px solid var(--ink)}
h3{font-size:13.5px;margin:16px 0 6px;color:var(--accent)}
.meta{color:var(--sub);margin-top:4px}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;background:var(--accent);color:#fff;font-size:12px;margin-left:8px;vertical-align:middle}
.badge.m{background:#6b3fa0}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:16px 0}
.kpi{border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.kpi .l{color:var(--sub);font-size:12px}
.kpi .v{font-size:22px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
.kpi .v .u{font-size:12px;font-weight:400;color:var(--sub);margin-left:2px}
.kpi .s{color:var(--sub);font-size:11.5px;margin-top:2px}
.kpi.lowbal{border:2px solid var(--accent)}.kpi.lowbal.lv-reserve{border-color:var(--warn)}.kpi.lowbal.lv-short{border-color:var(--out)}
.kpi.lv-reserve .v{color:var(--warn)}.kpi.lv-short .v{color:var(--out)}
.st{display:inline-block;padding:0 6px;border-radius:9px;font-size:11.5px;font-weight:700}
.st.lv-reserve{border:1px solid var(--warn);color:var(--warn)}.st.lv-short{background:var(--out);color:#fff}
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
.mid th{white-space:normal}.mid td.n{white-space:normal}
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
@media screen and (max-width:820px){.kpis,.low{grid-template-columns:1fr 1fr}.mid{grid-template-columns:1fr}
.kpi.lowbal{grid-column:1/-1;order:-1}
.tw table:not(.risk):not(#requests){width:max-content;min-width:100%}
.tw table:not(.risk):not(#requests) td{white-space:nowrap}}
@media print{@page{size:A4 portrait;margin:10mm}.wrap{max-width:none;padding:0}h2{break-after:avoid}
tr{break-inside:avoid}.toc{display:none}body{font-size:10.5px}table{font-size:10.5px}.kpi .v{font-size:18px}h2{margin-top:16px}.kpis{margin:8px 0}.kpi{padding:6px 10px}.mid svg{max-height:185px}.low{margin-top:8px}.kv{padding:1px 0}.wrap>.meta{margin-bottom:0}
.kpi,.card{break-inside:avoid}.mid svg{max-height:165px}.note{font-size:9.5px;margin:2px 0}.scope{margin:2px 0 4px}
.card{padding:6px 10px}.card h4{margin-bottom:3px}h3{margin:8px 0 4px}.kpi .s{font-size:10px}
a{color:inherit;text-decoration:none}}
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
    Wd, H, pl, pr, pt, pb = 900, 260, 90, 10, 14, 44
    n = len(bs)
    gw = (Wd - pl - pr) / n
    has_bal = s2["start"] is not None and not s2["out_missing"]  # 시작 잔액·지급 자료를 모르면 계산 잔액 선을 그리지 않는다 (0에서 시작하지 않음)
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

    out = ['<svg viewBox="0 0 %d %d" width="100%%" role="img" aria-label="기간별 입금·지급 예정과 예상 잔액">' % (Wd, H)]
    for k in range(int(round(span / step)) + 1):
        v = lo + step * k
        out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#e6e9ef"/>' % (pl, Wd - pr, y(v), y(v)))
        out.append('<text x="%d" y="%.1f" font-size="9.5" text-anchor="end" fill="#5b6475">%s</text>'
                   % (pl - 4, y(v) + 3, "{:,.0f}".format(v)))
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
        out.append('<text x="%d" y="%d" font-size="11" fill="#8a5a00">%s — 예상 잔액 선은 그리지 않음 (입금·지급 예정만 표시)</text>'
                   % (pl + 6, pt + 12, "지급 자료 없음" if s2["out_missing"] else "잔액 미확인"))
    out.append('<text x="%d" y="%d" font-size="9.5" fill="#5b6475">단위: 원 · 4주는 주별, 이후는 월별 (* 일부 기간)</text>'
               % (pl, H - 8))
    out.append("</svg>")
    legend = ('<div class="legend"><span><i style="background:#2f7d5b"></i>입금 확정분</span>'
              '<span><i style="background:#9cc9b3"></i>입금 예상분</span><span><i style="background:#b5523b"></i>지급 확정분</span>'
              '<span><i style="background:#e2aa9b"></i>지급 예상분</span>')
    if has_bal:
        legend += ('<span><i style="background:#1f4e8c"></i>예상 잔액(확정분만)</span>'
                   '<span><i style="background:repeating-linear-gradient(90deg,#1f4e8c 0 3px,#fff 3px 5px)"></i>예상 잔액(예상분 포함)</span>')
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
             "<body><div class='wrap'>" % (esc(title), d2s(R["asof"]), CSS + FS_CSS))
    h.append("<h1>%s<span class='badge%s'>%s</span></h1>" % (esc(title), "" if mode == "ceo" else " m",
                                                             "대표용" if mode == "ceo" else "경영관리용"))
    h.append("<div class='meta'>보고 기준일 %s · 집계 기간 %s ~ %s · 작성 %s · 금액 단위: 원</div>"
             % (d2s(R["asof"]), d2s(p0), d2s(p1), dt.datetime.now().strftime("%Y-%m-%d %H:%M")))

    h.append(_first_screen(R, mode, per))
    if mode == "ceo":
        # 대표 보고는 문서로 1~2쪽: 요약 화면만 싣는다. 상세 장(1~8)은 경영관리 보고에만 (사용자 2026-11-03)
        h.append("</div></body></html>")
        return "".join(h)

    toc = ["현재 자금·입출금", "입금·지급 일정", "프로젝트 예산·집행", "매출·손익", "계산서·수금", "프로젝트 밖 지급", "변동·자료 범위"]
    if R["kind"] == "monthly":
        toc.append(XCHK_TITLE)  # 월간에만 8번 (주간 보고는 바뀌지 않는다, D-44)
    h.append("<div class='toc'>상세자료: " + " ".join(
        '<a href="#s%d">%d. %s</a>' % (i, i, t) for i, t in enumerate(toc, 1))
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
    if R["kind"] == "monthly":
        h.append(_s8(R, mode))
    h.append("</div></body></html>")
    return "".join(h)


# ─────────── 대표 첫 화면 (2026-11-03 사용자: 한눈에, 원 단위, 업무 용어, 기간별 가용자금) ───────────
FS_CSS = """
.q{font-size:13px;font-weight:700;color:var(--sub);margin:20px 0 8px}
.fs .card{border-radius:10px;padding:12px 16px;background:#fff}
.fs .big{font-size:24px;font-weight:800;letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.fs .lab{font-size:12.5px;color:var(--sub);font-weight:600}.fs .foot{font-size:12px;color:var(--sub);margin-top:4px}
.flow{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}.flow .op{font-size:22px;color:var(--sub)}
.vin{color:var(--in)}.vout{color:var(--out)}.neg{color:var(--out)!important}
.avail{border:2px solid var(--accent)!important}
table.pt{margin-top:8px;font-size:13px}table.pt th{background:#fff;border-bottom:1.5px solid var(--ink);text-align:right;white-space:normal}
table.pt th:first-child,table.pt td:first-child{text-align:left}table.pt td{text-align:right;padding:7px 6px;font-variant-numeric:tabular-nums;white-space:nowrap}
table.pt td small{display:block;color:var(--sub);font-size:11px}table.pt td.av,table.pt th.av{background:#eef3fb}
table.pt td.av b{font-size:16px;color:var(--accent)}table.pt td.av b.neg{color:var(--out)}
table.pt.wo td{white-space:normal}table.pt.wo th{text-align:left}table.pt.wo th:nth-child(5){text-align:right}table.pt.wo td:nth-child(2){text-align:left}table.pt.wo td:nth-child(3),table.pt.wo td:nth-child(4),table.pt.wo td:last-child{text-align:left}table.pt.wo tr.od td{color:var(--warn)}
table.pt td.av small.firm{color:var(--sub);font-size:11px}table.pt td.av small.firm.neg{color:var(--out)}table.pt tr.pick td{border-top:1.5px dashed var(--line)}
.prow{display:grid;grid-template-columns:220px minmax(0,1fr) 170px;column-gap:14px;padding:9px 0;border-top:1px solid var(--line);align-items:center}
.prow:first-of-type{border-top:0}.pn{font-weight:700}.pn small{display:block;font-weight:400;color:var(--sub)}
.bar{position:relative;height:12px;background:#eef0f3;border-radius:6px;display:flex}.bar i{display:block;height:100%}
.bar .b1{background:var(--accent);border-radius:6px 0 0 6px}.bar .b2{background:#9db6e3}
.bar s{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--ink)}
.bn{font-size:11.5px;color:var(--sub);margin-top:3px;font-variant-numeric:tabular-nums}
.pr{text-align:right;font-variant-numeric:tabular-nums;font-size:15px;font-weight:700}.pr small{display:block;font-size:11px;color:var(--sub);font-weight:400}
.chip{display:inline-block;font-size:11px;font-weight:700;border-radius:10px;padding:0 7px;margin-left:6px;vertical-align:1px}
.c-ok{background:#e7f3ec;color:var(--in)}.c-over{background:#fbe9e7;color:var(--out)}.c-q{background:#fff3d6;color:var(--warn)}.c-n{background:var(--soft);color:var(--sub)}
.keys{font-size:11.5px;color:var(--sub);display:flex;gap:12px;flex-wrap:wrap}.keys i{display:inline-block;width:11px;height:9px;border-radius:2px;margin-right:3px}
.ptot{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;border-top:2px solid var(--ink);padding-top:8px;margin-top:4px;font-size:12px}
.four{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.four .big{font-size:20px}
.xbox{background:#fff8e6;border:1px solid #f0dca8;border-radius:10px;padding:10px 16px}
.xbox ul{margin:2px 0 0;padding-left:18px;columns:2;column-gap:28px}.xbox li{margin:2px 0;break-inside:avoid}
@media screen and (max-width:820px){.four{grid-template-columns:1fr 1fr}.prow{grid-template-columns:minmax(0,1fr) auto}.prow .bw{grid-column:1/-1;order:3}
.xbox ul{columns:1}table.pt{display:block;overflow-x:auto}}
@media print{.prow{padding:4px 0}.fs .big{font-size:18px}.q{margin:10px 0 4px;break-after:avoid}
.fs svg{max-height:210px}table.pt td{padding:3px 6px}table.pt td.av b{font-size:14px}.fs .card{padding:6px 12px}}
"""

CIRCLED = "①②③④⑤⑥⑦⑧"


def _q(i, text):
    return "<div class='q'>%s %s</div>" % (CIRCLED[i], esc(text))


def _flow_card(s1, per):
    """월간: 기간 시작 잔액 + 입금 − 지급 = 기간 말 잔액 (계좌 간 이체 제외)."""
    cells = [("월초 잔액", W(s1["start_calc"]), ""), ("+", None, ""), ("입금", W(s1["in"]), " vin"), ("−", None, ""),
             ("지급", W(s1["out"]), " vout"), ("=", None, ""), ("월말 잔액", W(s1["end"]), "")]
    h = ["<div class='card flow'>"]
    for lab, v, cls in cells:
        h.append("<div class='op'>%s</div>" % lab if v is None else
                 "<div><div class='lab'>%s</div><div class='big%s'>%s</div></div>" % (esc(lab), cls, v))
    h.append("</div><div class='note'>%s</div>" % esc("계좌 간 이체 입금 %s / 출금 %s 제외 · 은행 기준일 %s%s"
                                                  % (won(s1["transfer_in"]), won(s1["transfer_out"]), _bank_dates(s1), _bal_note(s1))))
    return "".join(h)


def _avail_cell(p):
    """가용자금 칸: 예상분 포함을 크게, 그 아래 확정분만을 작게 (문서로 전달하므로 단추 없이 둘 다 보인다)."""
    a, f = p["all"]["avail"], p["firm"]["avail"]
    big = _na("확인 필요") if a is None else "<b class='%s'>%s</b>" % ("neg" if a < 0 else "", esc(won(a)))
    small = "확인 필요" if f is None else won(f)
    return "<td class='av'>%s<small class='firm%s'>확정분만 %s</small></td>" % (big, " neg" if f is not None and f < 0 else "", esc(small))


def _avail_rows(periods, s2=None):
    """예상분 포함 기준 한 줄씩. in_missing·out_missing 이면 입금·지급 칸 숫자 옆에 자료 없음을 적는다 (빠진 채 0처럼 보이지 않게)."""
    in_tag = "<small class='na'>계산서 자료 없음</small>" if s2 and s2["in_missing"] else ""
    out_tag = "<small class='na'>지급 자료 없음</small>" if s2 and s2["out_missing"] else ""
    rows = []
    for p in periods:
        r = p["all"]
        low = _na("확인 필요") if r["low"] is None else "%s<small>(%s)</small>" % (
            esc(won(r["low"])), esc("오늘" if r["low_date"] == p.get("asof") else d2s(r["low_date"])[5:].replace("-", "/")))
        rows.append("<tr%s><td><b>%s</b><small>~ %s</small></td><td class='vin'>%s</td><td class='vout'>%s</td>"
                    "<td><b>%s</b></td><td>%s</td>%s</tr>"
                    % (" class='pick'" if p.get("pick") else "", esc(p["label"]), esc(d2s(p["end"])),
                       esc(won(r["in"])) + in_tag, esc(won(r["out"])) + out_tag, W(r["bal"], "확인 필요"), low, _avail_cell(p)))
    return "".join(rows)


def _avail_table(R):
    """기간별 가용자금 표: 주간 1~4주, 월간 1~3개월 + 지정일 줄(보고서를 만들 때 --가용일 로 넣은 날짜) (사용자 2026-11-03).

    보고서는 문서(PDF)로 전달하므로 단추·날짜 입력 칸 없이 모든 값이 그대로 보인다 (사용자 2026-11-03).
    가용자금 = 기간 중 최저 잔액 − 최소 보유현금. 줄은 예상분 포함 기준이고, 가용자금 칸 아래에 확정분만을 함께 적는다."""
    s1, s2 = R["s1"], R["s2"]
    periods = [dict(p, asof=R["asof"]) for p in s2["periods"]]
    mc = s2["min_cash"]
    h = ["<div class='card avail'><div class='lab'>기간별 가용자금 <span style='font-weight:400'>%s</span></div>"
         % esc("시작: 오늘 가용액 %s = 계좌 합계 %s − 사용제한 %s%s · 은행 기준일 %s%s" % (
             _won_or_unknown(s2["start"]), _won_or_unknown(s1["total"]), won(s1["restricted"]),
             " · 제한금액 미확인 %d계좌" % s1["restr_unknown"] if s1["restr_unknown"] else "", _bank_dates(s1), _bal_note(s1)))]
    head = ("<thead><tr><th>기간</th><th>입금 예정</th><th>지급 예정</th><th>예상 잔액</th><th>기간 중 최저 잔액</th>"
            "<th class='av'>가용자금<br><small>최소 보유현금 %s 남김</small></th></tr></thead>" % esc(won(mc) if mc is not None else "설정 오류"))
    h.append("<div class='tw'><table class='pt' id='avail'>%s<tbody>%s</tbody></table></div>" % (head, _avail_rows(periods, s2)))
    notes = ["가용자금 = 기간 중 최저 잔액 − 최소 보유현금. 예상 잔액이 넉넉해도 기간 중 최저 잔액을 넘겨 쓰면 그 사이에 자금이 모자람.",
             "금액은 예상분 포함 기준 (확정분만은 가용자금 칸 아래)"]
    if s2.get("pick_beyond"):
        notes.append("지정일이 일정 자료 범위(%s)보다 뒤라 그 뒤 일정은 반영 안 됨" % d2s(s2["horizon"]))
    if s2["out_missing"]:
        notes.append("지급 자료 없음: %s — 잔액·가용자금은 계산하지 않음" % ", ".join(s2["out_missing"]))
    if s2["in_missing"]:
        notes.append("계산서 입금 예정 미반영 (자료 없음: %s)" % _inv_files(s2))
    if s2["vat_unknown_n"]:
        notes.append("부가세 미확인 %d건 (공급가액만 반영)" % s2["vat_unknown_n"])
    if s2["out_unknown_n"]:
        notes.append("금액 미확인 지급 예정 %d건 (미반영)" % s2["out_unknown_n"])
    h.append("<div class='note'>%s</div></div>" % esc(" · ".join(notes)))
    return "".join(h)


def _proj_chip(P):
    if P["budget"] is None:
        return "<span class='chip c-n'>예산 미지정</span>"
    if P["unknown_cost"]:
        return "<span class='chip c-q'>확인 필요</span>"
    if P["remain"] is not None and P["remain"] < 0:
        return "<span class='chip c-over'>예산 초과</span>"
    return "<span class='chip c-ok'>예산 내</span>"


def _proj_right(P):
    if P["budget"] is None:
        return "<small>잔여 예산</small>" + _na("예산 미지정" + (" (%s)" % P["budget_reason"] if P["budget_reason"] else ""))
    if P["unknown_cost"]:
        return "<small>잔여 예산</small>" + _na("확인 필요" + _unknown_cost_text(P["unknown_cost"]))
    if P["remain"] is None:
        return "<small>잔여 예산</small>" + _na("확인 필요")
    if P["remain"] < 0:
        return "<small>예산 초과</small><span class='neg'>%s</span>" % esc(won(-P["remain"]))
    return "<small>잔여 예산</small>%s" % esc(won(P["remain"]))


def _project_bars(R, per):
    """프로젝트 원가 예산 막대: 집행액(지급 완료) · 집행 예정액(요청·카드 미결제·미요청 계획) · 예산선."""
    s3 = R["s3"]
    tot = s3["total"]
    shown = s3["shown"]
    scale = max([max(P["budget"] or 0, P["paid_total"] + P["requested"] + P["card_unpaid"] + P["planned"]) for P in shown] or [0]) or 1
    h = ["<div class='card'><div class='keys'><span><i style='background:var(--accent)'></i>집행액 (지급 완료)</span>"
         "<span><i style='background:#9db6e3'></i>집행 예정액 (지급요청·카드 미결제·미요청 계획)</span>"
         "<span><i style='background:var(--ink);width:2px'></i>원가 예산</span><span>%s</span></div>"
         % esc("원가 예산 = 사전견적 × 원가율 %s · 공급가액 기준(카드는 총액)" % _rate_text(s3))]
    for P in shown:
        due = P["requested"] + P["card_unpaid"] + P["planned"]
        w1, w2 = P["paid_total"] / scale * 100, due / scale * 100
        mark = "" if P["budget"] is None else "<s style='left:%.1f%%'></s>" % (P["budget"] / scale * 100)
        h.append("<div class='prow' id='pj-%s'><div class='pn'>%s%s<small>%s</small></div>"
                 "<div class='bw'><div class='bar'><i class='b1' style='width:%.1f%%'></i><i class='b2' style='width:%.1f%%'></i>%s</div>"
                 "<div class='bn'>원가 예산 %s · 집행액 %s · 집행 예정액 %s · %s 지급 %s</div></div>"
                 "<div class='pr'>%s</div></div>"
                 % (esc(P["id"]), esc(_short(P["name"], 20)), _proj_chip(P), esc(P["id"]), w1, w2, mark,
                    W(P["budget"], "예산 미지정"), _amt_lines(W, P["paid_total"], P, *PAID_STATES),
                    _amt_lines(W, due, P, *(UNPAID_STATES + PLAN_STATES)), esc(per), W(P["paid_period"]), _proj_right(P)))
    if s3["rest"]:
        r = s3["rest"]
        ra = _agg_lines(r)
        h.append("<div class='prow sub'><div class='pn'>%s</div><div class='bn'>원가 예산 %s · 집행액 %s · 집행 예정액 %s</div><div></div></div>"
                 % (esc("외 %d건" % len(r)), W(_sum_opt(x["budget"] for x in r)),
                    _amt_lines(W, sum(x["paid_total"] for x in r), ra, *PAID_STATES),
                    _amt_lines(W, sum(x["requested"] + x["card_unpaid"] + x["planned"] for x in r), ra, *(UNPAID_STATES + PLAN_STATES))))
    nb = _no_budget_note(s3)
    rem = tot["remain"]
    rem_txt = _na("확인 필요") if rem is None else (
        "<b class='neg'>%s 초과</b>" % esc(won(-rem)) if rem < 0 else "<b>%s</b>" % esc(won(rem)))
    h.append("<div class='ptot'><span>%s%s</span><span>전체 원가 예산 %s · 집행액 %s · 집행 예정액 %s · 잔여 예산 %s%s</span></div>"
             % (esc("표시 %d건 / 전체 %d건 (원가 예산 큰 순)" % (len(shown), len(s3["projects"]))), esc(" · " + nb) if nb else "",
                W(tot["budget"], "확인 필요"), _amt_lines(W, tot["paid_total"], tot, *PAID_STATES),
                _amt_lines(W, tot["requested"] + tot["card_unpaid"] + tot["planned"], tot, *(UNPAID_STATES + PLAN_STATES)),
                rem_txt, _na(_remain_excluded_text(tot))))
    h.append("<div class='note'>잔여 예산 = 원가 예산 − (집행액 + 집행 예정액). 예산이 지정된 프로젝트만 합계. 미확인 원가가 있는 프로젝트는 ‘확인 필요’로 두고 합계에서 뺌. "
             "진행 중 프로젝트의 잔여 예산은 부가세 10%를 더해 행사일 다음 달 말 금요일 지급 예정으로 자금 일정에 넣음 "
             "(그 날이 지났으면 기준일 다음 금요일, 행사일 없으면 날짜 없는 지급 예정). 완료 프로젝트는 넣지 않음.</div></div>")
    return "".join(h)


def _results(R):
    """실적 칸 4개: 매출 · 이익(마감 전) · 미수금 · 행사 후 세금계산서 미발행."""
    s4, s5 = R["s4"], R["s5"]
    cards = []
    src = s4["sources"].get("WEHAGO")
    co = [r for r in src["table"] if r["unit"] == "회사"] if src else []
    c, y = (co[0]["cur"], co[0]["ytd"]) if co else (None, None)
    ym = _ym_text(s4["ym"])
    if c:
        cards.append(("%s 매출" % ym, W(c["revenue"]), "올해 누적 %s" % (W(y["revenue"]) if y else _na("자료 없음"))))
        tag = " <span class='chip c-q'>마감 전</span>" if c["provisional"] else ""
        cards.append(("%s 이익%s" % (esc(ym), tag), W(c["np"], "확인 필요"),
                      "이익률 %s · 올해 누적 %s" % (esc(pct(c["np"], c["revenue"])), W(y["np"], "확인 필요") if y else _na("자료 없음"))))
    else:
        why = "자료 없음" if not src else "자료 없음 (최근 %s)" % (src["latest"] or "-")
        cards.append(("%s 매출" % ym, _na(why), ""))
        cards.append(("%s 이익" % ym, _na(why), ""))
    na = s5["in_missing"]
    if na:
        cards.append(("미수금 (세금계산서 발행 후)", _inv_na(s5), ""))
    else:
        ar = _na("미확인 %d건" % s5["ar_unknown_n"]) if s5["ar"] is None else W(s5["ar"]) + (
            _na(" 외 미확인 %d건" % s5["ar_unknown_n"]) if s5["ar_unknown_n"] else "")
        cards.append(("미수금 (세금계산서 발행 후)", ar,
                      "그중 입금예정일 지남 <span class='neg'>%s</span> (%d건)" % (esc(won(s5["overdue_total"])), len(s5["overdue"]))))
    E = s5["event_unissued"]
    if E["missing"]:
        cards.append(("행사 후 세금계산서 미발행", _inv_na(s5), ""))
    else:
        foot = "%d건" % len(E["rows"])
        if E["rows"]:
            o = E["rows"][0]
            foot += " · 가장 오래된 것 %s (행사 후 %d일)" % (_short(o["P"]["name"], 14), o["days"])
        foot = esc(foot) + (_na(" · 확인 필요 %d건" % len(E["unknown"])) if E["unknown"] else "")
        cards.append(("행사 후 세금계산서 미발행", W(E["total"]), foot))
    h = ["<div class='four'>"]
    for lab, v, foot in cards:
        lab_html = lab if "<span" in lab else esc(lab)
        h.append("<div class='card'><div class='lab'>%s</div><div class='big'>%s</div><div class='foot'>%s</div></div>"
                 % (lab_html, v, foot))
    h.append("</div>")
    return "".join(h)


def _ym_text(ym):
    """'2026-10' → '10월' (첫 화면 실적 제목)."""
    m = re.match(r"^\d{4}-(\d{2})$", ym or "")
    return "%d월" % int(m.group(1)) if m else ym


def _excluded_box(R):
    """위 숫자(가용자금·일정)에 들어가지 않은 금액과 확인할 것 (D-04: 조용히 빼지 않음, 건수·금액을 첫 화면에)."""
    s2, s3, s5, s7 = R["s2"], R["s3"], R["s5"], R["s7"]
    items = []

    def side(n, amt, unk):
        if amt is None:
            return "%d건 금액 미확인" % n
        return "%d건 %s" % (n, won(amt)) + (" (금액 미확인 %d건)" % unk if unk else "")

    s1, s6 = R["s1"], R["s6"]
    if s1["bal_unknown"]:
        items.append("잔액 미확인 %d계좌 (합계 제외)" % s1["bal_unknown"])
    elif s1["total"] is None:
        items.append("계좌 잔액 미확인 (계좌 자료 없음)")
    if s1["restr_unknown"]:
        items.append("사용제한 금액 미확인 %d계좌" % s1["restr_unknown"])
    inv_na = " (계산서 자료 없음: %s)" % _inv_files(s2) if s2["in_missing"] else ""
    items.append("예정일 지난 미처리 입금 %s%s / 지급 %s (일정에 넣지 않음)" % (
        side(s2["past_in_n"], s2["past_in"], s2["past_in_unknown"]), inv_na,
        side(s2["past_out_n"], s2["past_out"], s2["past_out_unknown"])))
    items.append("날짜 없는 입금 예정 %s%s / 지급 예정 %s" % (
        side(s2["undated_in_n"], s2["undated_in"], s2["undated_in_unknown"]), inv_na,
        side(s2["undated_out_n"], s2["undated_out"], s2["undated_out_unknown"])))
    if s5["in_missing"]:
        items.append("입금예정일 지난 미수금: 계산서 자료 없음 (%s)" % _inv_files(s5))
    else:
        items.append("입금예정일 지난 미수금 %d건 %s (일정에 넣지 않음)" % (len(s5["overdue"]), won(s5["overdue_total"])))
    if s2["out_unknown_n"]:
        items.append("금액 미확인 지급 예정 %d건" % s2["out_unknown_n"])
    if s2["vat_unknown_n"]:
        items.append("부가세 미확인 지급 예정 %d건 (공급가액만 반영)" % s2["vat_unknown_n"])
    if s3.get("remain_unknown"):
        items.append("잔여 예산 확인 필요 프로젝트 %d건 (지급 예정에 넣지 않음)" % len(s3["remain_unknown"]))
    s6_txt = "프로젝트 밖 지급 예정 (등록분 전체) %s · 날짜 없음 %d건" % (
        won(s6["total"]) if s6["total"] is not None else "금액 미확인", s6["undated_n"])
    if s6["unknown_n"]:
        s6_txt += " · 금액 미확인 %d건" % s6["unknown_n"]
    items.append(s6_txt)
    items.append("예산 미지정 프로젝트 %d건" % len(s7["no_budget"]))
    items.append("프로젝트 미연결 지급 %s" % won(s7["unlinked_txn_total"] + s3["unlinked_total"]))
    if s5["event_unissued"]["unknown"]:
        items.append("행사 후 미발행 확인 필요 %d건 (사전견적·행사일 없음 등)" % len(s5["event_unissued"]["unknown"]))
    items.append("입력 자료 확인 필요 %d건" % len(s7["issues"]))
    return "<div class='xbox'><ul>%s</ul></div>" % "".join("<li>%s</li>" % esc(t) for t in items)


def week_outflows(R):
    """주간 대표 보고의 '이번 주 지급 예정' 목록 (사용자 2026-11-03: 이번 주에 나가는 돈은 전부 보여야 함).

    기준일 다음 날부터 7일 안의 지급 예정 전부(금액 미확인 포함) + 예정일이 지났는데 아직 처리되지 않은 지급.
    날짜 순, 같은 날은 금액 큰 순. 금액을 모르는 줄은 0으로 치지 않고 따로 센다."""
    asof, end = R["asof"], R["asof"] + dt.timedelta(days=7)
    rows = []
    for e in R["events"]:
        if e["io"] != "out" or e["date"] is None or e["date"] > end:
            continue
        rows.append(dict(e, overdue=e["date"] <= asof))
    rows.sort(key=lambda e: (e["date"], -(e["amount"] or 0)))
    known = [e for e in rows if e["amount"] is not None]
    return {"start": asof + dt.timedelta(days=1), "end": end, "rows": rows,
            "firm": sum(e["amount"] for e in known if e["firm"] and not e["overdue"]),
            "est": sum(e["amount"] for e in known if not e["firm"] and not e["overdue"]),
            "overdue": sum(e["amount"] for e in known if e["overdue"]),
            "unknown_n": len(rows) - len(known)}


def _week_out_table(R):
    W_ = week_outflows(R)
    h = ["<div class='card'><table class='pt wo'><thead><tr><th>예정일</th><th>거래처 · 내용</th><th>프로젝트</th><th>구분</th>"
         "<th>금액</th><th>상태</th></tr></thead><tbody>"]
    if not W_["rows"]:
        h.append("<tr><td colspan='6'>이번 주 지급 예정 없음</td></tr>")
    for e in W_["rows"]:
        state = "예정일 지남" if e["overdue"] else ("확정" if e["firm"] else "예상")
        amt = _na("금액 미확인") if e["amount"] is None else esc(won(e["amount"]))
        h.append("<tr%s><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class='vout'>%s</td><td>%s</td></tr>"
                 % (" class='od'" if e["overdue"] else "", esc(d2s(e["date"])[5:].replace("-", "/")), esc(e.get("desc") or ""),
                    esc(e.get("project") or ""), esc(e.get("cat") or ""), amt, esc(state)))
    h.append("</tbody></table>")
    tail = "확정 %s · 예상 %s" % (won(W_["firm"]), won(W_["est"]))
    if W_["overdue"]:
        tail += " · 예정일 지난 미처리 %s (위 1주 지급 예정에는 안 들어감)" % won(W_["overdue"])
    if W_["unknown_n"]:
        tail += " · 금액 미확인 %d건" % W_["unknown_n"]
    h.append("<div class='note'>%s건 · 합계 %s</div></div>" % (len(W_["rows"]), esc(tail)))
    return "".join(h)


def _first_screen(R, mode, per):
    s1, s2, s7 = R["s1"], R["s2"], R["s7"]
    monthly = R["kind"] == "monthly"
    h = ["<div class='page fs'>"]
    i = 0
    if monthly:
        h.append(_q(i, "이번 달 자금 흐름"))
        h.append(_flow_card(s1, per))
        i += 1
    h.append(_q(i, "앞으로 자금은?" if monthly else "지금 자금은?"))
    i += 1
    h.append(_avail_table(R))
    h.append("<div class='card' style='margin-top:10px'><div class='lab'>%s</div>%s</div>"
             % (esc("기간별 자금 흐름 (시작: 오늘 가용액 %s%s)" % (_won_or_unknown(s2["start"]), _bal_note(s1))), chart(s2)))
    if not monthly:
        wo = week_outflows(R)
        h.append(_q(i, "이번 주 지급 예정 (%s ~ %s)" % (d2s(wo["start"])[5:].replace("-", "/"), d2s(wo["end"])[5:].replace("-", "/"))))
        i += 1
        h.append(_week_out_table(R))
    h.append(_q(i, "프로젝트 예산은 남나?"))
    i += 1
    h.append(_project_bars(R, per))
    h.append(_q(i, "%s 실적" % _ym_text(R["s4"]["ym"])))
    i += 1
    h.append(_results(R))
    if monthly:
        h.append(_q(i, "장부와 맞춰 본 결과 (WEHAGO 기준)"))
        i += 1
        X = R.get("xchk")
        if X is None or X["state"] == "자료 없음":
            h.append("<div class='card'>%s</div>" % _na("자료 없음 (%s — 실행_변환.bat으로 만듦)" % XCHK_FILE_NAME))
        elif X["state"] != "ok":
            h.append("<div class='card'>%s</div>" % _na("%s (%s)" % (X["state"], X["reason"])))
        else:
            h.append("<div class='card'>%s<div class='note'>자세한 내용은 경영관리 보고 8번</div></div>" % _xk_summary(X))
    h.append(_q(i, "위 숫자에 안 들어간 것 · 확인할 것"))
    h.append(_excluded_box(R))
    h.append("<div class='note' style='margin-top:10px'>%s</div>" % esc(
        "자료 기준일: " + " · ".join("%s %s" % (a["name"], d2s(a["date"])) for a in s7["asof"])))
    if mode == "mgmt":
        hi = sum(1 for r in R["risks"] if r["level"] == "높음")
        h.append("<div class='note' style='margin-top:10px'>위험 항목 %d건 (높음 %d건) — 아래 ‘위험 분석·해결방안’ 참조</div>"
                 % (len(R["risks"]), hi))
    h.append("</div>")
    return "".join(h)


def _kpi(label, value, sub, unit=True, cls=""):
    if unit:
        value += " <span class='u'>백만원</span>"
    return "<div class='kpi%s'><div class='l'>%s</div><div class='v'>%s</div><div class='s'>%s</div></div>" % (
        cls, esc(label), value, sub)


def _low_kpi(R):
    """첫 줄 다섯째 칸: 확정 일정만의 최저 계산 잔액과 그 날짜, 최소 보유현금과의 비교 (값은 s2['min'] 그대로).

    비교는 글자로 적는다 (색은 같은 말을 되풀이할 뿐). 시작 잔액을 모르면 '잔액 미확인'만 보인다."""
    s2 = R["s2"]
    low, day = s2["min"]["firm"]
    if low is None:
        if s2["out_missing"]:
            return _kpi("최저 계산 잔액 (확정 일정만)", _na("판단 불가"),
                        esc("지급 자료 없음: %s — 계산하지 않음" % ", ".join(s2["out_missing"])), unit=False, cls=" lowbal")
        return _kpi("최저 계산 잔액 (확정 일정만)", _na("잔액 미확인"), esc("시작 잔액을 몰라 계산하지 않음"), unit=False,
                    cls=" lowbal")
    reserve = R["settings_num"]["위험_최소보유현금"]
    level = ""
    if low < 0:
        level, text = "lv-short", "부족 (0 미만)"
    elif reserve is not None and low < reserve:
        level, text = "lv-reserve", "최소 보유현금 %s 미만" % man(reserve)
    else:
        text = "최소 보유현금 %s 이상" % man(reserve) if reserve is not None else ""
    sub = esc(d2s(day))
    if text:
        sub += " · " + ("<span class='st %s'>%s</span>" % (level, esc(text)) if level else esc(text))
    sub += _vat_note(s2["vat_unknown_firm_n"]) + _unknown_out_note(s2["out_unknown_firm_n"]) + _in_missing_note(s2)
    return _kpi("최저 계산 잔액 (확정 일정만)", M(low), sub, cls=" lowbal" + (" " + level if level else ""))


def _in_missing_note(s2):
    """계산서 자료가 없어 계산서 입금 없이 계산한 잔액임을 알리는 보조 문구 (없으면 빈 문자열)."""
    if not s2["in_missing"]:
        return ""
    return _na(" · 계산서 입금예정 미반영 (자료 없음: %s)" % ", ".join(s2["in_missing"]))


def _in_side_note(s2):
    """입금 쪽 건수·금액 뒤: 계산서 자료가 없으면 계산서 입금이 빠진 숫자임을 적는다 (없으면 빈 문자열)."""
    if not s2["in_missing"]:
        return ""
    return _na(" · 계산서 자료 없음 (%s)" % _inv_files(s2))


def _inv_files(s):
    """s2 또는 s5의 '계산서.csv (파일 없음)' 꼴 목록에서 파일 이름만."""
    return ", ".join(m.split(" (")[0] for m in s["in_missing"])


def _inv_na(s5):
    """계산서 자료가 없을 때의 금액 칸: 0이 아니라 '자료 없음 (계산서.csv)'."""
    return _na("자료 없음 (%s)" % _inv_files(s5))


def _no_low(s2):
    """최저 계산 잔액을 만들지 않은 이유: 지급 자료가 빠졌으면 '판단 불가', 시작 잔액을 모르면 '잔액 미확인'."""
    return "판단 불가 (지급 자료 없음)" if s2["out_missing"] else "잔액 미확인"


def _min_cell(low, day, vat_n, unk_n=0, none_text="잔액 미확인"):
    """최저 계산 잔액 칸. 시작 잔액을 모르면 숫자를 만들지 않고 '잔액 미확인'만 보인다."""
    if low is None:
        return _na(none_text)
    return "%s (%s)%s%s" % (M(low), esc(d2s(day)), _vat_note(vat_n), _unknown_out_note(unk_n))


def _won_or_unknown(v):
    return "잔액 미확인" if v is None else won(v) + "원"


def _min_cell_won(low, day, vat_n, unk_n=0, none_text="잔액 미확인"):
    if low is None:
        return _na(none_text)
    return esc("%s원 (%s)" % (won(low), d2s(day))) + _vat_note(vat_n) + _unknown_out_note(unk_n)


def _unknown_out_note(n):
    """기간 안 날짜인데 금액을 모르는 지급예정 건수 (최저 잔액에 넣지 못함). 없으면 빈 문자열."""
    return _na(" · 금액 미확인 %d건 (미반영)" % n) if n else ""


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


def _won_unit(v):
    """'1,234원'. 값이 없으면 '미확인'."""
    return _na("미확인") if v is None else esc(won(v) + "원")


def _no_budget_note(s3):
    """'예산 미책정 N건 (사유별 건수)'. 없으면 빈 글자."""
    reasons = s3["no_budget_reasons"]
    if not reasons:
        return ""
    return "예산 미책정 %d건 (%s)" % (sum(reasons.values()), ", ".join("%s %d건" % (k, n) for k, n in reasons.items()))


def _rate_text(s3):
    rate = s3["cost_rate"]
    return "설정 오류" if rate is None else "%g%%" % round(rate * 100, 6)


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
    h.extend(_fundplan_notes(R.get("fundplan")))
    if s2["in_missing"]:
        h.append("<div class='note'>%s</div>" % esc(
            "계산서 자료 없음(%s) — 계산서 입금예정(수금)이 빠진 채 입금 칸과 계산 잔액을 만듦. 입금이 빠졌으므로 "
            "계산 잔액·최저 계산 잔액은 실제보다 낮을 수 있음." % ", ".join(s2["in_missing"])))
    rows = []
    for b in s2["buckets"]:
        rows.append([esc(b["label"]), esc("%s ~ %s" % (d2s(b["from"]), d2s(b["to"]))), W(b["in_firm"]), W(b["in_est"]),
                     W(b["out_firm"]), W(b["out_est"]), W(b["bal_firm"]), W(b["bal_all"])])
    h.append(table(["구간", "기간", "입금 확정", "입금 추정", "지급 확정", "지급 추정", "계산 잔액 (확정)", "계산 잔액 (확정+추정)"],
                   rows, num_cols=(2, 3, 4, 5, 6, 7)))
    m3 = [b for b in s2["buckets"] if b["type"] == "week" or b.get("within3")]
    if s2["out_missing"]:
        h.append("<div class='note'>%s</div>" % esc("지급 자료 없음(%s) — 지급예정이 빠져 구간별 계산 잔액, 3·6개월 시점 잔액, "
                                                     "최저 계산 잔액은 계산하지 않음." % ", ".join(s2["out_missing"])))
    elif s2["start"] is None:
        h.append("<div class='note'>%s</div>" % esc("시작 잔액 미확인 — 구간별 계산 잔액, 3·6개월 시점 잔액, 최저 계산 잔액은 계산하지 않음."))
    else:
        h.append("<div class='note'>3개월 시점(%s) 계산 잔액: 확정 %s원 / 확정+추정 %s원 · 6개월 시점(%s): 확정 %s원 / 확정+추정 %s원</div>"
                 % (d2s(m3[-1]["to"]), won(m3[-1]["bal_firm"]), won(m3[-1]["bal_all"]), d2s(s2["buckets"][-1]["to"]),
                    won(s2["buckets"][-1]["bal_firm"]), won(s2["buckets"][-1]["bal_all"])))
    lf, lfd = s2["min"]["firm"]
    la, lad = s2["min"]["all"]
    h.append(kv([("기간 중 최저 계산 잔액 · 확정 일정만", _min_cell_won(lf, lfd, s2["vat_unknown_firm_n"], s2["out_unknown_firm_n"], _no_low(s2))),
                 ("기간 중 최저 계산 잔액 · 확정+추정", _min_cell_won(la, lad, s2["vat_unknown_n"], s2["out_unknown_n"], _no_low(s2)))]))
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


def _fundplan_notes(F):
    """자금계획서 기준 일정 설명 (D-55). 자금계획.csv 가 없으면 아무것도 쓰지 않는다."""
    if not F:
        return []
    if not F["used"]:
        return ["<div class='note'>%s</div>" % esc("자금계획서 쓰지 않음: " + F["reason"])]
    out = ["<div class='note'>%s</div>" % esc(
        "일정 기준: WEHAGO 자금계획서 (자료일 %s, %s). 기존 일정과 같은 건 %d건은 자금계획서 날짜·금액으로 바꿈, "
        "새로 넣은 줄 %d건, 이미 지급·입금되어 뺀 줄 %d건, 예정일 지난 미지급 %d건은 다음 금요일로 옮김, "
        "입금 지연 %d건은 추정(지난 날짜, 잔액 계산 미포함). 자금계획서가 없는 달은 기존 일정으로 계산."
        % (d2s(F["stamp"]), ", ".join(F["months"]), len(F["matched"]), len(F["added"]), len(F["done"]),
           len(F["moved"]), len(F["late_in"])))]
    if F["missing"]:
        out.append("<h3>자금계획서에 없는 기존 일정 (%d건, 그대로 반영 · 확인 필요)</h3>" % len(F["missing"]))
        out.append("<div class='note'>WEHAGO 자금계획서에 등록되지 않은 예정입니다. 같은 건이면 자금일정.csv 에서 지우고, "
                   "다른 건이면 WEHAGO 에 지급·입금예정일을 넣어 주세요. 지급은 빼지 않고 그대로 계산합니다.</div>")
        out.append(table(["예정일", "구분", "금액", "확정", "분류", "프로젝트", "거래처·내용", "원천"],
                         [[esc(d2s(e["date"])), esc("입금" if e["io"] == "in" else "지급"), W(e["amount"]),
                           esc("확정" if e["firm"] else "추정"), esc(e["cat"]), esc(e["project"]), esc(e["desc"]),
                           esc(e["source"])] for e in sorted(F["missing"], key=lambda e: e["date"])], num_cols=(2,)))
    if F["done"]:
        out.append("<h3>이미 지급·입금되어 일정에서 뺀 자금계획서 줄 (%d건)</h3>" % len(F["done"]))
        out.append(table(["예정일", "상태", "금액", "거래처", "분개장 근거", "함께 뺀 기존 일정"],
                         [[esc(d2s(x["plan"]["date"])), esc(x["plan"]["state"]), W(x["plan"]["amount"]),
                           esc(x["plan"]["vendor"]), esc(x["plan"]["basis"]),
                           esc("%s %s %s" % (x["old"]["source"], d2s(x["old"]["date"]), x["old"]["desc"]) if x["old"] else "-")]
                          for x in F["done"]], num_cols=(2,)))
    moved = [x for x in F["matched"] if x["old"]["date"] != x["plan"]["date"]]
    if moved:
        out.append("<h3>자금계획서로 날짜가 바뀐 일정 (%d건)</h3>" % len(moved))
        out.append(table(["거래처", "금액", "기존 예정일", "자금계획서 예정일", "기존 원천"],
                         [[esc(x["plan"]["desc"]), W(x["plan"]["amount"]), esc(d2s(x["old"]["date"])),
                           esc(d2s(x["plan"]["date"])), esc(x["old"]["source"])] for x in moved], num_cols=(1,)))
    return out


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
                     W(P["paid_cash"], P["paid_cash_reason"] or "미확인"), W(P["requested"]), W(P["card_unpaid"]), W(P["planned"]),
                     W(P["expected"]), esc(pct(P["paid_total"], P["budget"])), W(P["remain"], "판단 불가"),
                     esc("%d건" % P["unknown_cost"]) if P["unknown_cost"] else ""])
    h.append(table(["번호", "프로젝트", "팀", "상태", "사전견적", "원가 예산", "예산 사유", "예산 수정일", per + " 지급", "누적 지급",
                    "지급 실출금(VAT포함)", "요청 미지급", "카드 미결제", "미요청 계획", "예상 총집행", "지급률", "예상 잔여예산",
                    "금액 미확인"], rows, num_cols=(4, 5, 8, 9, 10, 11, 12, 13, 14, 15, 16),
                   total=["전체", "%d건" % len(s3["projects"]), "", "",
                          _amt_unk(tot["estimate"], tot["estimate_missing"], "미등록"), W(tot["budget"], "판단 불가"),
                          esc(note_nb), "", W(tot["paid_period"]),
                          W(tot["paid_total"]), _amt_unk(tot["paid_cash"], tot["paid_cash_unknown"], tot["paid_cash_reason"]), W(tot["requested"]), W(tot["card_unpaid"]),
                          W(tot["planned"]), W(tot["expected"]), esc(pct(tot["paid_budgeted"], tot["budget"])),
                          W(tot["remain"], "판단 불가") + _na(_remain_excluded_text(tot)), "%d건" % tot["unknown_cost"]]))
    h.append("<div class='note'>원가 예산 = 사전견적(예상 매출) × 원가율 (설정.csv 예산_원가율, 기본 0.70). "
             "사전견적이 없거나 0원 이하·해석 불가이거나 원가율 설정 오류면 ‘예산 미지정’, 지급률·잔여예산은 ‘판단 불가’, 이유는 ‘예산 사유’ 열. "
             "지급·요청·계획은 공급가액. 카드 사용액은 총액. ‘지급 실출금’은 지급완료분 공급가액+부가세. "
             "누적 지급 = 지급완료 + 카드결제완료. "
             "남은 예산(진행 중 프로젝트)은 부가세 10%를 더해 행사일 다음 달 말 금요일 지급 예정으로 자금 일정에 넣음(그 날이 지났으면 기준일 다음 금요일, 행사일 없으면 날짜 없는 지급 예정). 완료 프로젝트는 넣지 않음. 합계의 지급률·잔여예산은 예산 지정 프로젝트만.</div>")
    h.append("<h3>팀별 예산·집행</h3>")
    trows = [[esc(t["team"]), esc("%d건" % t["n"]), W(t["budget"], "판단 불가"),
              esc("%d건" % t["no_budget"]) if t["no_budget"] else "", W(t["expected"]),
              W(t["remain"], "판단 불가") + (_na(" (판단 불가 %d건 제외)" % t["remain_unknown"])
                                         if t["remain_unknown"] and t["remain"] is not None else ""),
              W(t["planned_pay"])] for t in s3["by_team"]]
    h.append(table(["팀", "프로젝트", "원가 예산", "예산 미지정", "예상 총집행", "예상 잔여예산", "남은 예산 지급 예정(VAT포함)"],
                   trows, num_cols=(2, 4, 5, 6)))
    h.append("<div class='note'>팀 = 프로젝트.csv 팀(담당 부서). 원가 예산·잔여예산은 예산 지정 프로젝트만 더함. "
             "예상 총집행은 팀의 모든 프로젝트. 남은 예산 지급 예정은 완료 프로젝트 제외.</div>")
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
    na = s5["in_missing"]
    if na:
        h.append("<div class='note na'>%s</div>" % esc(
            "계산서 자료 없음: %s — 발행금액·미발행금액·발행 후 미수는 0이 아니라 ‘자료 없음’. 계산서 입금예정은 일정에 넣지 않음."
            % ", ".join(na)))
    rows = []
    for x in s5["by_project"]:
        P = x["P"]
        rows.append([esc(P["id"]), esc(P["name"]), esc(d2s(P["done_date"], "-")), W(P["contract"], "계약금액 미등록"),
                     _inv_na(s5) if na else _amt_unk(x["issued"], x["issued_unknown"]),
                     _inv_na(s5) if na else W(x["unissued"], "판단 불가"),
                     _inv_na(s5) if na else _amt_unk(x["ar"], x["ar_unknown"]),
                     esc("%d일" % x["unissued_days"]) if x["unissued_days"] is not None else
                     ("<span class='note'>완료일 미확인</span>" if x["unissued"] and not P["done_date"] else "")])
    h.append(table(["번호", "프로젝트", "완료일", "계약금액(공급가)", "발행금액(공급가)", "미발행금액", "발행 후 미수(VAT포함)",
                    "완료 후 미발행 경과"], rows, num_cols=(3, 4, 5, 6, 7),
                   total=["전체", "", "", _amt_unk(s5["contract"], s5["contract_missing"], "미등록"),
                          _inv_na(s5) if na else _amt_unk(s5["issued"], s5["issued_unknown_n"]),
                          _inv_na(s5) if na else _amt_unk(s5["unissued"], s5["unissued_unknown_n"], "판단 불가"),
                          _inv_na(s5) if na else _amt_unk(s5["ar"], s5["ar_unknown_n"]), ""]))
    h.append("<div class='note'>미발행금액 = 계약금액 − 발행금액(공급가). 미수 = 발행 합계(VAT포함) − 입금액 − 같은 프로젝트 취소·수정(음수) 상계. "
             "완료일이 없으면 미발행 경과일을 계산하지 않음.</div>")
    h.append(_event_unissued_table(s5))
    h.append("<h3>발행 후 미수 (%d건)</h3>" % len(s5["ar_rows"]))
    rows = [[esc(v["project"]), esc(v["client"]), esc(d2s(v["date"])), esc(v["kind"]), W(v["total"]), W(v["paid"], "0"),
             W(v["outstanding"]), esc(d2s(v["due"])), esc("확정" if v["due_firm"] else "추정"),
             esc("%d일" % v["overdue_days"]) if "overdue_days" in v else ""] for v in s5["ar_rows"]]
    h.append(table(["프로젝트", "거래처", "발행일", "구분", "합계", "입금액", "미수", "입금예정일", "예정일", "예정일 경과"], rows,
                   num_cols=(4, 5, 6, 9), total=["합계", "", "", "", "", "",
                                                 _inv_na(s5) if na else W(sum(v["outstanding"] for v in s5["ar_rows"])),
                                                 "", "", ""]))
    h.append("<h3>선수금·취소·환불·수정 (%d건)</h3>" % len(s5["specials"]))
    rows = [[esc(v["project"]), esc(v["client"]), esc(d2s(v["date"])), esc(v["kind"]), W(v["supply"]), W(v["vat"]),
             W(v["paid"], "-"), esc(d2s(v["paid_date"], "-")), _credit_cell(v)] for v in s5["specials"]]
    h.append(table(["프로젝트", "거래처", "발행일", "구분", "공급가액", "부가세", "입금액", "입금일", "미수 상계(VAT포함)"], rows,
                   num_cols=(4, 5, 6, 8)))
    h.append("<div class='note'>취소·수정(음수) 계산서는 같은 프로젝트(거래처를 알면 같은 거래처)의 남은 미수에서 빼고, "
             "뺄 미수가 없는 금액은 입금예정으로 만들지 않음.</div>")
    if s5["no_project"]:
        h.append("<h3>프로젝트 미연결 계산서 (%d건)</h3>" % len(s5["no_project"]))
        rows = [[esc(v["project"] or "-"), esc(v["client"]), esc(d2s(v["date"])), W(v["supply"])] for v in s5["no_project"]]
        h.append(table(["프로젝트", "거래처", "발행일", "공급가액"], rows, num_cols=(3,)))
    return "".join(h)


def _event_unissued_table(s5):
    """행사일이 지났는데 계산서가 덜 나간 프로젝트 (사전견적 − 발행, 오래된 행사 순). 모르는 것은 까닭과 함께 건수로."""
    E = s5["event_unissued"]
    h = ["<h3>%s</h3>" % esc("행사 끝난 뒤 계산서 미발행 (%d건)" % len(E["rows"]))]
    if E["missing"]:
        h.append("<div class='note na'>%s</div>" % esc("계산서 자료 없음 — 행사 후 미발행은 ‘자료 없음’"))
        return "".join(h)
    rows = [[esc(y["P"]["id"]), esc(y["P"]["name"]), esc(d2s(y["event"])), esc("%d일" % y["days"]),
             W(y["estimate"]), W(y["issued"], "0"), W(y["unissued"])] for y in E["rows"]]
    h.append(table(["번호", "프로젝트", "행사일", "행사 후", "사전견적(공급가)", "발행금액(공급가)", "미발행금액"], rows,
                   num_cols=(3, 4, 5, 6), total=["합계", "", "", "", "", "", W(E["total"])]))
    note = "미발행금액 = 사전견적 − 발행금액(공급가). 행사일이 기준일 전인 프로젝트만."
    if E["unknown"]:
        by = OrderedDict()
        for u in E["unknown"]:
            by.setdefault(u["why"], []).append(u["P"]["id"])
        note += " 판단 불가 %d건 (%s) — 합계에 없음." % (len(E["unknown"]), " · ".join(
            "%s %d건" % (k, len(v)) for k, v in by.items()))
    h.append("<div class='note'>%s</div>" % esc(note))
    return "".join(h)


def _credit_cell(v):
    """취소·수정 음수 계산서가 미수에서 뺀 금액 (뺄 미수가 없어 남은 금액도 함께)."""
    if "credit_applied" not in v:
        return ""
    out = W(v["credit_applied"])
    if v["credit_left"]:
        out += _na(" · 뺄 미수 없음 %s" % won(v["credit_left"]))
    return out


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
        ("예산 미지정 프로젝트", "%d건 · 계약 %s · 예상 총집행 %s원"
         % (len(s7["no_budget"]),
            _amt_unk(s7["no_budget_contract"], s7["no_budget_contract_missing"], "미등록", _won_unit),
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


# ───────────── 월간 8번: WEHAGO 기준 대조 (D-44, D-48, D-49) ─────────────
XCHK_TITLE = "WEHAGO 기준 대조"
XCHK_FILE_NAME = "위하고대조.csv"


def _xk_why(note):
    """'판단 불가 — 이유' 비고 -> '판단 불가 (이유)'. 이유가 없으면 '판단 불가'."""
    rest = re.sub(r"^판단 불가\s*[—-]*\s*", "", note or "").strip()
    return "판단 불가" + (" (%s)" % rest if rest else "")


def _xk_unknown_n(note):
    """비고의 '금액 미확인 N건/줄/곳' -> '(미확인 N건)' 또는 ''."""
    m = re.search(r"미확인\s*(\d+)\s*(건|줄|곳)", note or "")
    return " (미확인 %s%s)" % m.groups() if m else ""


def _xk_amount(amount, note=""):
    """알면 원 단위 숫자, 모르면 '판단 불가 (미확인 N건)'. 모르는 금액은 0으로 보이지 않는다 (B5)."""
    if amount is not None:
        return esc(won(amount))
    return _na("판단 불가" + _xk_unknown_n(note))


def _xk_money_note(amount, note=""):
    return "금액 " + _xk_amount(amount, note) if amount is None else _xk_amount(amount, note)


def _xk_meta(R, X):
    meta = X["meta"]
    book_text = meta.get("장부 기준일", "")
    out = "장부 기준일 " + (esc(book_text) if book_text else _na("기록 없음"))
    if book_text:
        book = parse_date(book_text)
        if book is None:
            out += _na(" (날짜 형식 확인 불가)")
        else:
            days = (R["asof"] - book).days
            if days > 0:
                out += esc(" (보고 기준일보다 %d일 이전)" % days)
            elif days < 0:
                out += esc(" (보고 기준일보다 %d일 이후)" % -days)
    for key in ("분개장 기간", "인트라넷 스냅숏", "변환 시각"):
        out += " · " + esc(key) + " " + (esc(meta[key]) if meta.get(key) else _na("기록 없음"))
    return out


def _xk_period(X):
    """'2026-09~2026-10 장부 기준': 누계 칸이 어느 분개장 기간의 합인지 (02-REVIEW WR-05). 기록이 없으면 ''."""
    m = re.match(r"^(\d{4}-\d{2})-\d{2}~(\d{4}-\d{2})-\d{2}$", X["meta"].get("분개장 기간", ""))
    return "%s~%s 장부 기준" % m.groups() if m else ""


def _xk_label(text, X):
    per = _xk_period(X)
    return text + (" (" + per + ")" if per else "")


def _xk_period_cell(amount, note, out, period):
    """누계 칸. 기간 밖 이력이 있는 프로젝트는 '판단 불가 (기간 밖)' 과 분개장 기간 합계를 같이 보인다 (0 으로 보이지 않음)."""
    if not out:
        return _xk_amount(amount, note)
    return _na("판단 불가 (기간 밖)") + ("" if period is None else " " + esc("기간 합계 " + won(period)))


def _xk_status(X):
    st = X["status"]
    if not st:
        return _na("판단 불가 (요청상태 줄 없음)")
    counts = [v["count"] for v in st.values()]
    total = _na("건수 판단 불가") if any(c is None for c in counts) else "%d건" % sum(counts)
    parts = []
    for name, v in st.items():
        c = v["count"]
        text = esc(name) + " " + (_na("건수 판단 불가") if c is None else "%d건" % c)
        if c != 0:
            text += " " + _xk_money_note(v["amount"], v["note"])
        parts.append(text)
    return total + " (" + " · ".join(parts) + ")" + " · " + _xk_status_check(X)


def _xk_status_check(X):
    """사장님승인을 읽지 못한 요청 (D-52): '상태 확인 필요 N건 금액'. 사실이므로 두 판 모두 싣는다."""
    if not X.get("has_status_check"):
        return _na("상태 확인 필요 판단 불가 (위하고대조.csv에 줄 없음 — 다시 변환)")
    f = X["status_check"]
    if f["count"] is None:
        return _na("상태 확인 필요 판단 불가")
    text = "상태 확인 필요 %d건" % f["count"]
    return text + (" " + _xk_money_note(f["amount"], f["note"]) if f["count"] else "")


def _xk_projects(X):
    projects, t = X["projects"], X["totals"]
    if not projects:
        return _na("판단 불가 (프로젝트원가 줄 없음)")
    known = [p["cost"] for p in projects if p["cost"] is not None]
    outside = sum(1 for p in projects if p.get("out_of_period"))
    missing = len(projects) - len(known) - outside
    if missing or outside:
        why = " · ".join(x for x in ("금액 미확인 %d개 프로젝트" % missing if missing else "",
                                     "기간 밖 %d개 프로젝트" % outside if outside else "") if x)
        head = _na("판단 불가 (%s)" % why) + " 확인된 합계 " + esc(won(sum(known)))
    else:
        head = esc(won(sum(known)))
    parts = ["%d개 프로젝트" % len(projects)]
    if t["budget_known"]:
        parts.append("실행가 입력 %d건 합계 %s" % (t["budget_known"], won(t["budget_sum"])))
    else:
        parts.append("실행가 입력 0건")
    parts.append("실행가 빈칸 %d건" % t["budget_blank"])
    if t["budget_dup"]:
        parts.append("프로젝트번호 겹침 %d건 (실행가 판단 불가)" % t["budget_dup"])
    parts.append("원가가 실행가보다 큰 프로젝트 %d건" % t["over_budget"])
    skipped = [p for p in projects if p["budget"] is not None and p["cost"] is None]
    if skipped:
        parts[-1] += " (원가 판단 불가 %d개 프로젝트는 제외)" % len(skipped)
    outside = len([p for p in projects if not p["has_budget"]])
    if outside:
        parts.append("프로젝트 목록에 없음 %d개 포함" % outside)
    return head + " (" + esc(" · ".join(parts)) + ")"


def _xk_fact(f, unit):
    """합계 줄 하나: 'N줄 금액'."""
    count = _na("%s 수 판단 불가" % unit) if f["count"] is None else "%d%s" % (f["count"], unit)
    if f["amount"] is None and f["count"] is None:
        return _na("판단 불가")
    return count + " " + _xk_money_note(f["amount"], f["note"])


def _xk_vendors(X):
    vs = X["vendor_summary"]
    if vs["compared"] is None:
        return _na("판단 불가 (거래처미지급요약 줄 없음)")
    diff = (_na("판단 불가") if vs["diff_count"] is None else "%d곳 " % vs["diff_count"] + _xk_amount(vs["diff_sum"], vs["diff_note"]))
    unknown = _na("판단 불가") if vs["unknown_count"] is None else "%d곳" % vs["unknown_count"]
    text = "비교 %d곳 · 차이 %s · 판단 불가 %s" % (vs["compared"], diff, unknown)
    return text + (" · " + esc(vs["note"]) if vs["note"] else "")


def _xk_revenue(X):
    rev, un, t = X["revenue"], X["revenue_unlinked"], X["totals"]
    if rev:
        linked_known = [c["wehago"] for c in rev if c["wehago"] is not None]
        linked_missing = len(rev) - len(linked_known)
        linked_sum = sum(linked_known)
        linked = esc(won(linked_sum)) if not linked_missing else _na("판단 불가 (금액 미확인 %d개)" % linked_missing) + \
            " 확인된 합계 " + esc(won(linked_sum))
        total_known = not linked_missing and un["amount"] is not None
        total = esc(won(linked_sum + un["amount"])) if total_known else _na("판단 불가")
        if not total_known and (un["amount"] is not None or linked_known):
            total += " 확인된 합계 " + esc(won(linked_sum + (un["amount"] or 0)))
    else:
        linked, total = _na("판단 불가 (매출계약 줄 없음)"), _na("판단 불가")
    parts = [total, "프로젝트 연결 " + linked,
             "미연결 " + (_na("판단 불가") if un["count"] is None and un["amount"] is None else _xk_fact(un, "줄"))]
    if t["contract_registered"]:
        contract = "합계 " + esc(won(t["contract_sum"]))
    elif t["contract_unregistered"]:
        contract = "등록된 값 없음"
    else:
        contract = _na("줄 없음")
    if t["contract_registered"] or t["contract_unregistered"]:
        contract += " (미등록 %d건)" % t["contract_unregistered"]
    parts.append("계약금액 (수동 입력) " + contract)
    return " · ".join(parts)


def _xk_cash(X):
    c = X["cash"]
    parts = ["증감 " + (_na(_xk_why(c["change_note"])) if c["change"] is None else esc(won(c["change"])))]
    parts.append("장부 잔액 " + (esc(won(c["balance"])) if c["balance"] is not None else _na(_xk_why(c["balance_note"]))))
    parts.append("계좌잔액.csv 합계 " + (esc(won(c["bank_balance"])) if c["bank_balance"] is not None
                                       else _na(_xk_why(c["bank_note"]))))
    if c["balance_diff"] is not None:
        parts.append("차이 " + esc(won(c["balance_diff"])))
    elif c["balance"] is not None or c["bank_balance"] is not None:
        parts.append("차이 " + _na("판단 불가"))
    return " · ".join(parts)


def _xk_summary(X):
    rows = [("지급요청 대조", _xk_status(X)), (_xk_label("프로젝트 (도)원가", X), _xk_projects(X)),
            ("프로젝트 미연결 원가", _xk_fact(X["unlinked"], "줄")), ("거래처 미지급", _xk_vendors(X)),
            ("매출 (분개장, %s)" % _xk_period(X) if _xk_period(X) else "매출 (분개장)", _xk_revenue(X)),
            ("보통예금 (WEHAGO 10300)", _xk_cash(X))]
    body = "".join('<tr><th>%s</th><td style="white-space:normal">%s</td></tr>' % (esc(k), v) for k, v in rows)
    return '<div class="tw"><table id="xchk-summary" class="xk" style="width:100%%"><tbody>%s</tbody></table></div>' % body


# 경영관리용 상세 표 (D-44). 모든 글자 칸은 esc()를 지난다 (esc 가 주민번호 모양을 먼저 가린다, T-02-37·38).
XCHK_LINE_CAP = 20


def _idt(tid, markup):
    """table() 결과의 <table class=...> 에 id 를 붙인다."""
    return markup.replace('<table class="', '<table id="%s" class="' % tid, 1)


def _xk_none(text="-"):
    return esc(text)


def _xk_count(n, unit):
    return _xk_none() if n is None else esc("%d%s" % (n, unit))


def _xk_diff(v):
    return _na("판단 불가") if v is None else esc(won(v))


def _xk_join(*notes):
    return esc(" · ".join(n for n in notes if n))


def _xk_absent(amount, count, note):
    """이 사실 줄이 파일에 아예 없음 (알 수 없는 것과 구분: 없으면 '-')."""
    return amount is None and count is None and not note


def _xk_status_table(X):
    rows = []
    for name, v in X["status"].items():
        c, ic = v["count"], v["invoice_count"]
        absent = _xk_absent(v["invoice"], ic, v["invoice_note"])
        rows.append([esc(name), _xk_count(c, "건"),
                     _xk_none() if c == 0 else _xk_amount(v["amount"], v["note"]),
                     _xk_none() if absent else _xk_count(ic, "건"),
                     _xk_none() if absent or ic == 0 else _xk_amount(v["invoice"], v["invoice_note"]),
                     _xk_join(v["note"], v["invoice_note"])])
    return _idt("xchk-status", table(["요청 상태", "인트라넷 요청 건수", "인트라넷 요청 금액", "WEHAGO 계산서 건수", "WEHAGO 계산서 금액", "비고"],
                                     rows, num_cols=(1, 2, 3, 4)))


def _xk_status_check_table(X):
    lines = X.get("status_check_lines") or []
    if not lines:
        return "<div class='note'>%s</div>" % esc("상태 확인 필요 지급요청 없음")
    rows = [[esc(ln["key"]), esc(ln["vendor"]), esc(ln["label"]), _xk_amount(ln["amount"], ln["memo"]), esc(ln["memo"])]
            for ln in lines]
    f = X["status_check"]
    total = ["합계", "", "", _xk_amount(f["amount"], f["note"]), esc(f["note"])]
    return _idt("xchk-status-check", table(["번호", "거래처", "사장님승인", "금액", "프로젝트"], rows, num_cols=(3,), total=total))


def _xk_projects_table(X):
    rows = []
    for p in X["projects"]:
        no_budget = not p["has_budget"]
        no_request = _xk_absent(p["requested"], p["requested_count"], p["requested_note"])
        rows.append([esc(p["key"]), esc(p["name"]),
                     _xk_period_cell(p["cost"], p["cost_note"], p.get("out_of_period"), p.get("cost_period")),
                     _xk_count(p["cost_lines"], "줄"),
                     _xk_none() if no_budget else _xk_amount(p["budget"], p["budget_note"]),
                     _xk_none() if no_budget else _xk_diff(p["cost_vs_budget"]),
                     _xk_none() if no_request else _xk_amount(p["requested"], p["requested_note"]),
                     _xk_none() if no_request else _xk_count(p["requested_count"], "건"),
                     _xk_none() if no_request else _xk_diff(p["request_vs_cost"]),
                     _xk_join(p["cost_note"], p["budget_note"], p["requested_note"])])
    return _idt("xchk-projects", table(["번호", "프로젝트", _xk_label("WEHAGO 원가", X), "원가 줄", "실행가", "원가−실행가", "요청 누계", "요청 건수",
                                        "요청 누계−원가", "비고"], rows, num_cols=(2, 3, 4, 5, 6, 7, 8)))


def _xk_outside_table(X):
    o = X["outside"]
    if o["amount"] is None and o["count"] is None:
        rows = [[esc("프로젝트 밖 지급요청 (인트라넷)"), _xk_none(), _na("판단 불가"), esc(o["note"])]]
    else:
        rows = [[esc("프로젝트 밖 지급요청 (인트라넷)"), _xk_count(o["count"], "건"), _xk_amount(o["amount"], o["note"]), esc(o["note"])]]
    return _idt("xchk-outside", table(["구분", "건수", "금액", "비고"], rows, num_cols=(1, 2)))


def _xk_lines_table(tid, lines, fact):
    """줄 목록(첫 20줄만) + 합계 줄. 20줄을 넘으면 몇 줄 중 몇 줄인지 표 위에 적는다."""
    shown = lines[:XCHK_LINE_CAP]
    rows = [[esc(ln["key"]), esc(ln["vendor"]), esc(ln["label"]), _xk_amount(ln["amount"], ln["memo"]), esc(ln["memo"])] for ln in shown]
    total = ["합계", "", "", _xk_amount(fact["amount"], fact["note"]), esc(fact["note"])]
    cut = ("전체 %d줄 중 %d줄 표시" % (len(lines), len(shown)) if len(lines) > len(shown) else "전체 %d줄 모두 표시" % len(lines))
    return "<div class='note'>%s</div>" % esc(cut) + _idt(tid, table(["전표", "거래처", "연결 결과", "금액", "적요"], rows,
                                                                   num_cols=(3,), total=total))


def _xk_vendors_table(X):
    rows = []
    for v in X["vendors"]:
        no_request = _xk_absent(v["requested"], v["requested_count"], v["requested_note"])
        rows.append([esc(v["vendor"]), _xk_amount(v["payable"], v["payable_note"]),
                     _xk_none() if no_request else _xk_count(v["requested_count"], "건"),
                     _xk_none() if no_request else _xk_amount(v["requested"], v["requested_note"]),
                     _xk_diff(v["diff"]), _xk_join(v["payable_note"], v["requested_note"])])
    return _idt("xchk-vendors-m", table(["거래처", "WEHAGO 미지급", "인트라넷 요청 건수", "인트라넷 요청 금액", "차이 (WEHAGO−요청)", "비고"],
                                        rows, num_cols=(1, 2, 3, 4)))


def _xk_revenue_table(X):
    rows = []
    for c in X["revenue"]:
        if not c["has_contract"]:
            contract = _xk_none()
        elif c["contract"] is None:
            contract = _na("미등록")
        else:
            contract = esc(won(c["contract"]))
        rows.append([esc(c["key"]), esc(c["name"]),
                     _xk_period_cell(c["wehago"], c["wehago_note"], c.get("out_of_period"), c.get("wehago_period")),
                     _xk_count(c["wehago_lines"], "줄"), contract,
                     _xk_none() if c["quote"] is None else esc(won(c["quote"])),
                     _xk_join(c["wehago_note"], c["contract_note"], c["quote_note"])])
    t = X["totals"]
    known = [c["wehago"] for c in X["revenue"] if c["wehago"] is not None]
    unknown = len(X["revenue"]) - len(known)
    total = ["합계", "", esc(won(sum(known))) if not unknown else _na("판단 불가") + " " + esc(won(sum(known))),
             _xk_none(), esc(won(t["contract_sum"])) if t["contract_registered"] else _na("등록된 값 없음"), "",
             esc("미등록 %d건" % t["contract_unregistered"])]
    return _idt("xchk-revenue", table(["번호", "프로젝트", _xk_label("WEHAGO 매출", X), "매출 줄", "계약금액 (수동 입력)", "견적금액", "비고"], rows,
                                      num_cols=(2, 3, 4, 5), total=total))


def _xk_cash_tables(X):
    c = X["cash"]
    rows = [[esc("기초 잔액"), _xk_amount(c["opening"], c["opening_note"]),
             _xk_count(c["opening_lines"], "줄"), esc(c["opening_note"])],
            [esc("WEHAGO 증감 (전체 기간)"), _xk_amount(c["change"], c["change_note"]), _xk_count(c["change_lines"], "줄"), esc(c["change_note"])],
            [esc("WEHAGO 잔액 (장부 기준일)"), _xk_amount(c["balance"], c["balance_note"]), _xk_none(), esc(c["balance_note"])],
            [esc("계좌잔액.csv 잔액 합계"), _xk_amount(c["bank_balance"], c["bank_note"]), _xk_count(c["bank_accounts"], "개 계좌"),
             esc(c["bank_note"])],
            [esc("차이 (장부 잔액 − 계좌잔액.csv)"), _xk_diff(c["balance_diff"]), _xk_none(),
             esc("" if c["balance_diff"] is not None else "장부 잔액과 계좌잔액.csv 합계를 모두 알 때만 계산")]]
    out = _idt("xchk-cash", table(["항목", "금액", "건수", "비고"], rows, num_cols=(1, 2)))
    months = []
    for m in X["cash_months"]:
        months.append([esc(m["month"]), _xk_amount(m["wehago"], m["wehago_note"]), _xk_count(m["wehago_lines"], "줄"),
                       _xk_amount(m["bank"], m["bank_note"]), _xk_count(m["bank_count"], "건"), _xk_diff(m["diff"]),
                       _xk_join(m["wehago_note"], m["bank_note"])])
    out += "<h3>월별 보통예금 증감</h3>" + _idt("xchk-cash-months", table(
        ["월", "WEHAGO 증감", "줄", "입출금내역 증감 (입금−출금)", "건수", "차이 (WEHAGO−입출금내역)", "비고"], months, num_cols=(1, 2, 3, 4, 5)))
    return out


def _xk_detail(X):
    """경영관리용에만 붙는 상세 묶음. 시험의 numbers_of 가 이 표지 사이를 뺀다 (REP-02: 요약 숫자는 두 판이 같다)."""
    h = ["<div id='xchk-detail'>",
         "<div class='note'>상세 (경영관리용). 값은 위하고대조.csv의 사실이며, 차이는 두 값을 모두 알 때만 계산 (모르면 ‘판단 불가’).</div>",
         "<h3>지급요청 대조 (상태별)</h3>", _xk_status_table(X),
         "<h3>상태 확인 필요 지급요청 (사장님승인 빈칸·알 수 없는 값, 요청 누계·프로젝트밖요청에 포함)</h3>", _xk_status_check_table(X),
         "<h3>프로젝트별 (도)원가 · 실행가 · 요청 누계</h3>", _xk_projects_table(X),
         "<h3>프로젝트 밖 지급요청</h3>", _xk_outside_table(X),
         "<h3>프로젝트 미연결 원가 줄</h3>", _xk_lines_table("xchk-unlinked", X["unlinked_lines"], X["unlinked"]),
         "<h3>거래처별 미지급 대조</h3>", _xk_vendors_table(X),
         "<h3>프로젝트별 매출 · 계약금액 (수동 입력)</h3>", _xk_revenue_table(X),
         "<h3>프로젝트 미연결 매출 줄</h3>", _xk_lines_table("xchk-revenue-unlinked", X["revenue_unlinked_lines"], X["revenue_unlinked"]),
         "<h3>보통예금 (WEHAGO 10300)</h3>", _xk_cash_tables(X),
         "</div><!-- /xchk-detail -->"]
    return "".join(h)


def _s8(R, mode):
    """월간 8번 WEHAGO 기준 대조. 요약은 두 판 모두 (합계·건수만), 상세 표는 경영관리용에만 (D-44)."""
    X = R.get("xchk")
    h = [_h2(8, XCHK_TITLE)]
    if X is None or X["state"] == "자료 없음":
        h.append("<div class='note'>%s</div>" % _na("자료 없음 (%s — 실행_변환.bat으로 만듦)" % XCHK_FILE_NAME))
        return "".join(h)
    if X["state"] != "ok":
        h.append("<div class='note'>%s</div>" % _na("%s (%s)" % (X["state"], X["reason"])))
        return "".join(h)
    h.append('<div class="meta xchk-meta">%s</div>' % _xk_meta(R, X))
    h.append(_xk_summary(X))
    span = X["meta"].get("분개장 기간", "")
    h.append("<div class='note'>%s (월별 매출·손익은 4번). 알 수 없는 값은 ‘판단 불가’로 표시하고 "
             "0으로 넣지 않음. 분개장 시작 전 이력(행사일·지급요청 등록)이 있는 프로젝트의 누계는 ‘판단 불가 (기간 밖)’. "
             "계약금액은 사람이 입력한 값.</div>"
             % esc("WEHAGO 원가·매출은 분개장 기간 %s 합계" % span if span else "WEHAGO 원가·매출은 분개장 전체 기간 합계 (분개장 기간 기록 없음)"))
    if mode == "mgmt":
        h.append(_xk_detail(X))
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
