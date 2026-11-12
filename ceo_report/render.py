"""HTML 보고서 만들기. mode='ceo'(대표용) 또는 'mgmt'(경영관리용).

두 보고서는 같은 계산 결과 R을 쓴다. 경영관리용에만 '위험 분석·해결방안'이 붙는다.
대표용에는 해석·권고 문구를 넣지 않는다.
"""
import datetime as dt
import math
import re
from collections import OrderedDict

from .util import won, man, pct, d2s, esc, ssum, date as parse_date
from .calc import _event_date
from . import areas

CSS = """
:root{--ink:#1d2433;--sub:#5b6475;--line:#d9dde5;--soft:#f3f5f8;--accent:#1f4e8c;--in:#2f7d5b;--out:#b5523b;
--est:#9aa3b2;--warn:#8a5a00;--bg:#fff}
*{box-sizing:border-box}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.45 "Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif;
word-break:keep-all;overflow-wrap:break-word}
.wrap{max-width:1180px;margin:0 auto;padding:24px 20px 60px}
h1{font-size:22px;margin:0}table.sign{float:right;width:auto!important;border-collapse:separate;border-spacing:0;margin:0 0 4px 12px;font-size:11px;border:1px solid #c5cad3;border-radius:6px;overflow:hidden;-webkit-print-color-adjust:exact;print-color-adjust:exact}table.sign th,table.sign td{border:0;border-left:1px solid #dde1e7;text-align:center;padding:4px 8px;width:70px}table.sign th{background:#f3f5f8;color:#1d2433;font-weight:700;letter-spacing:.08em;border-bottom:1px solid #dde1e7}table.sign th.sv{width:20px;padding:4px 3px;border-left:0;background:#1f4e8c;color:#fff;line-height:1.5;letter-spacing:0}table.sign tr.sg td{height:50px;background:#fff}
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
.kpi,.card,.sec{break-inside:avoid}.prow{break-inside:avoid}.mid svg{max-height:165px}.note{font-size:9.5px;margin:2px 0}.scope{margin:2px 0 4px}
.card{padding:6px 10px}.card h4{margin-bottom:3px}h3{margin:8px 0 4px}.kpi .s{font-size:10px}
a{color:inherit;text-decoration:none}}
"""


# ─────────── 문서 양식 (사용자 2026-11-05: "AI가 만든 문서 말고 진짜 문서처럼") ───────────
# 기준: 사내 보고서 양식. 가운데 제목 + 문서 정보 표 + 결재란, 절 제목은 '1.' 번호와 밑줄, 둥근 카드·그림자·색 상자·배지 없음.
# 표는 위·아래 굵은 선과 안쪽 가는 선, 머리줄은 옅은 회색. 글자색은 검정·회색, 빨강은 모자람·마이너스·경고에만.
# 숫자·배치·쪽 수는 그대로 두고 겉모양만 바꾼다 (덮어쓰는 CSS).
DOC_CSS = """
:root{--ink:#111;--sub:#555;--line:#bfbfbf;--soft:#f2f2f2;--accent:#1a3a6b;--in:#111;--out:#111;--rule:#111}
body{font-family:"Malgun Gothic","맑은 고딕","Apple SD Gothic Neo","Noto Sans KR",sans-serif;color:#111}
.doc-h{position:relative;margin:0 0 6px}
.doc-h h1{text-align:center;font-size:22px;font-weight:700;letter-spacing:.35em;margin:6px 0 10px;padding-bottom:6px}
.doc-h h1 .co{display:block;font-size:12px;letter-spacing:.1em;font-weight:400;color:#333;margin-bottom:2px}
table.dinfo{width:auto;border-collapse:collapse;font-size:11px;margin:0}
table.dinfo th,table.dinfo td{border:1px solid #111;padding:3px 8px;white-space:nowrap}
table.dinfo th{background:#f2f2f2;font-weight:600;text-align:center}
.dsrc{font-size:10px;color:#555;margin:4px 0 0}
table.sign{border:1px solid #111!important;border-radius:0!important;margin:0 0 4px 12px}
table.sign th,table.sign td{border:1px solid #111!important;padding:2px 8px;width:68px}
table.sign th{background:#fff!important;font-weight:600;letter-spacing:.3em}
table.sign th.sv{background:#fff!important;color:#111!important;width:18px;letter-spacing:0;font-weight:600}
table.sign tr.sg td{height:46px}
.badge,.badge.m{background:none;color:#111;border:1px solid #111;border-radius:0;font-size:11px;letter-spacing:.1em;padding:1px 6px}
.q{border-left:0!important;padding-left:0!important;font-size:14px!important;font-weight:700!important;color:#111!important;
border-bottom:1.5px solid #111;padding-bottom:3px!important;margin:16px 0 6px!important;letter-spacing:.02em}
.q .ev{border:0!important;color:#666!important;font-weight:400!important;font-size:10px!important;padding:0!important;margin-left:8px!important}
.pgt{color:#111!important;border-bottom:1px solid #111!important}.pgt span{background:none!important;color:#111!important;border:1px solid #111;border-radius:0!important}
.card,.fs .card,.kpi{border-radius:0!important;box-shadow:none!important}
.fs .card{border:0!important;padding:0!important;background:none!important}
.frimain{border:0!important;background:none!important;padding:0!important}
.fri{border-bottom:0!important;padding-bottom:2px!important}.fri b{color:#111!important;font-size:18px!important}
.four.top{gap:0!important;border:1.5px solid #111;margin:8px 0 4px!important}
.four.top .card{border:0!important;border-left:1px solid #111!important;padding:0!important}
.four.top .card:first-child{border-left:0!important}
.four.top .card .lab{display:block;background:#f2f2f2;border-bottom:1px solid #111;padding:3px 8px;color:#111;font-size:11px;font-weight:600}
.four.top .card .big{padding:4px 8px 0;font-size:17px!important;font-weight:700}
.four.top .card .foot{padding:0 8px 4px}
.four:not(.top){gap:0!important;border:1px solid #111}
.four:not(.top)>.card{border:0!important;border-left:1px solid #111!important;padding:6px 10px!important}
.four:not(.top)>.card:first-child{border-left:0!important}
.fs .big{font-weight:700!important}
.vin,.vout,table.pt.wo td:last-child.vout{color:#111!important}
.neg,table.pt td.av b.neg,table.pt td.av small.firm.neg{color:#c00000!important}
.chip{border-radius:0!important;background:none!important;color:#555!important;border:0!important;font-weight:400!important;padding:0!important}
.chip::before{content:"("}.chip::after{content:")"}
.chip.c-over{color:#c00000!important}
table{font-variant-numeric:tabular-nums}
table.pt,.fs table{border-top:1.5px solid #111;border-bottom:1.5px solid #111}
table.pt th,.fs table th{background:#f2f2f2!important;color:#111;font-weight:600;border-bottom:1px solid #111!important;padding:4px 6px}
table.pt td{border-bottom:1px solid #d0d0d0}
table.pt tr:last-child td{border-bottom:0}
table.pt tr.tot td,tr.tot td{background:#f2f2f2!important;border-top:1px solid #111!important;font-weight:700}
table.pt td.av,table.pt th.av{background:none!important}
table.pt td.av b{color:#111!important;font-size:15px!important}
.avail{border:0!important}
.warnbar{background:none!important;border:1.5px solid #c00000!important;border-radius:0!important;color:#c00000!important}
.overl,.dec{border-radius:0!important}.overl{border-left:3px solid #111!important}
.note,.evid{color:#444}
.note::before{content:"※ "}
.evid{border-top:1px solid #111!important}
.tbar,.tbar i,.bar{border-radius:0!important}
.st{border-radius:0!important}
.doc-end{float:right;font-size:11px;color:#111;letter-spacing:.3em}
@media screen and (max-width:820px){table.dinfo th,table.dinfo td{white-space:normal}table.sign{float:none;margin:0 0 6px}}
@media print{.doc-h h1{font-size:19px;margin:2px 0 8px}.q{margin:10px 0 4px!important;font-size:12.5px!important}}
"""


# 가독성 다듬기 (사용자 2026-11-05 "더 가독성 좋고 예쁘게"): 문서 양식은 그대로, 강조색 하나(남색)로 단계를 만든다.
# 제목 > 절 제목 > 요약 숫자 > 표 순으로 크기·굵기 차이를 두고, 표 줄 간격을 넓히고 옅은 줄무늬로 줄을 따라가기 쉽게.
DOC2_CSS = """
:root{--navy:#2b3a4e;--navy-t:#eef1f4;--navy-l:#c5ccd6;--zebra:#f7f8fa}
.doc-h h1{color:var(--navy);border-bottom:3px double var(--navy);margin-bottom:12px!important}
.doc-h h1 .co{color:#555}
table.dinfo th{background:var(--navy-t)!important;color:var(--navy)}
table.dinfo th,table.dinfo td,table.sign,table.sign th,table.sign td{border-color:var(--navy)!important}
table.sign th{color:var(--navy)!important}
.q{color:var(--navy)!important;border-bottom:2px solid var(--navy)!important;font-size:15px!important}
.four.top{border:0!important;border-top:2px solid var(--navy)!important;border-bottom:1px solid var(--navy)!important}
.four.top .card{border-left:1px solid var(--navy-l)!important}
.four.top .card .lab{background:var(--navy-t)!important;color:var(--navy)!important;border-bottom:1px solid var(--navy-l)!important}
.four.top .card .big{font-size:19px!important;color:#111}
.four:not(.top){border:0!important;border-top:2px solid var(--navy)!important;border-bottom:1px solid var(--navy)!important}
.four:not(.top)>.card{border-left:1px solid var(--navy-l)!important}
.four:not(.top)>.card .lab{color:var(--navy)!important}
.fs .foot{color:#666}
.fri span{color:var(--navy)}.fri b{color:var(--navy)!important;font-size:20px!important}
table.pt,.fs table{border-top:2px solid var(--navy)!important;border-bottom:1px solid var(--navy)!important}
table.pt th,.fs table th{background:var(--navy-t)!important;color:var(--navy)!important;border-bottom:1px solid var(--navy-l)!important}
table.pt td{border-bottom:1px solid #e3e8ef!important;padding-top:5px;padding-bottom:5px}
table.pt tbody tr:nth-child(even) td{background:var(--zebra)}
table.pt tr.tot td,tr.tot td{background:var(--navy-t)!important;color:var(--navy);border-top:1px solid var(--navy)!important}
table.pt td.av b{color:var(--navy)!important}
.wchg{color:#333}.wsub{color:var(--navy)!important}
.q .ev{color:#8a96a8!important}
.dsrc{color:#777}
.legend span{color:#555}
/* 번져 보임 줄이기 (사용자 2026-11-05): 옅은 회색 글자를 진하게, 아주 작은 글자를 키움, 글자 테두리(흰 띠) 없앰 */
body{color:#000;text-rendering:geometricPrecision}
.note,.scope,.evid,.dsrc,.fs .foot,.legend span,.kpi .s,small,.q .ev{color:#3a3a3a!important}
table.pt.wo small.dt.na,table.pt.wo .dt.na,table.pt.wo small.est,.na{color:#6a5200!important}
svg text{stroke:none!important}
svg text[fill="#5b6475"]{fill:#333}
@media print{body{font-size:11px}table{font-size:11px}.note,.evid,.dsrc{font-size:10px!important}
table.pt.wo small.dt,table.pt td small,table.pt.wo small.est{font-size:10px!important}}
@media print{.q{font-size:13px!important}.four.top .card .big{font-size:16.5px!important}.fri b{font-size:17px!important}
table.pt td{padding-top:4px;padding-bottom:4px}
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""


# 덜 딱딱하게 (사용자 2026-11-05 "문서가 너무 딱딱해 보이지 않아?"): 문서 틀(제목·정보 표·결재란·표)은 두고,
# 굵은 검정 선 대신 옅은 남색 선, 넓은 자간 제목 대신 보통 자간, 요약 칸은 옅은 바탕에 살짝 둥근 모서리, 절 제목 앞 남색 막대.
DOC3_CSS = """
.doc-h h1{letter-spacing:.08em!important;border-bottom:1.5px solid var(--navy)!important;font-size:21px!important}
.doc-h h1 .co{letter-spacing:.02em}
table.dinfo th,table.dinfo td{border-color:var(--navy-l)!important}
table.sign,table.sign th,table.sign td{border-color:var(--navy-l)!important}
table.sign th{letter-spacing:.05em!important}
.q{border-bottom:1px solid var(--navy-l)!important;padding-left:9px!important;border-left:4px solid var(--navy)!important;line-height:1.3}
.four.top{border:0!important;gap:8px!important}
.four.top .card{border:1px solid var(--navy-l)!important;border-radius:8px!important;overflow:hidden;background:#fff!important}
.four.top .card:first-child{border:1px solid var(--navy-l)!important}
.four.top .card .lab{border-bottom:0!important}
.four:not(.top){border:0!important;gap:8px!important}
.four:not(.top)>.card{border:1px solid var(--navy-l)!important;border-radius:8px!important;background:var(--zebra)!important}
.four:not(.top)>.card:first-child{border:1px solid var(--navy-l)!important}
table.pt,.fs table{border-top:1.5px solid var(--navy)!important;border-bottom:1px solid var(--navy-l)!important}
table.pt tr.tot td,tr.tot td{border-top:1px solid var(--navy-l)!important}
.evid{border-top:1px solid var(--navy-l)!important}
"""


# 숨 쉴 공간 (사용자 2026-11-05 오후: "여백이 너무 없어서 글자만 빡빡하게 보인다"): 줄 간격·칸 안 여백·절 사이를 넓힌다.
# 쪽 수 상한(주간 2·월간 3)은 그대로, 넘치면 보고서.py fit_pdf 가 인쇄 배율을 줄인다.
AIR_CSS = """
body{line-height:1.6}
@page{size:A4 portrait;margin:13mm 12mm}
.q{margin:22px 0 10px!important;padding-bottom:5px!important}
.pg .sec:first-of-type .q,.fs>.sec:first-of-type .q{margin-top:14px!important}
.sec{margin-bottom:12px}
.doc-h{margin-bottom:12px}
.dsrc{margin-top:6px!important}
.four.top{margin:14px 0 6px!important;gap:10px!important}
.four.top .card .lab{padding:5px 10px!important}
.four.top .card .big{padding:6px 10px 2px!important}
.four.top .card .foot{padding:0 10px 8px!important}
.four:not(.top){gap:10px!important}
.four:not(.top)>.card{padding:10px 14px!important}
table.pt th,.fs table th{padding:6px 8px!important}
table.pt td{padding:6px 8px!important}
table.pt.wo td{padding:5px 8px!important}
.fri{margin:4px 0 8px!important}
.wsub{margin:16px 0 6px!important}
.wchg{margin:8px 0 4px!important}
.note{margin:6px 0!important}
.avail>.lab{margin-bottom:6px}
.sec>div>.card+.card,.avail+.card{margin-top:14px!important}.sec .four>.card.card{margin-top:0!important}.sec .four+.card.card{margin-top:16px!important}.evid{margin-top:18px!important}
@media print{body{line-height:1.55}
.q{margin:18px 0 8px!important}
table.pt th,.fs table th{padding:5px 7px!important}
table.pt td{padding:5px 7px!important}
table.pt.wo td{padding:4px 7px!important}
table.pt.tm td,table.pt.tm th,table.pt.tx td,table.pt.tx th,table.pt.xr td,table.pt.xr th{padding:4px 6px!important}}
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


def _axis(v):
    """세로축 금액: 억·만 단위로 짧게 (사용자 2026-11-04 디자인 검토)."""
    if v == 0:
        return "0"
    if abs(v) >= 100_000_000:
        return "{:g}억".format(round(v / 100_000_000, 2))
    if abs(v) >= 10_000:
        return "{:,.0f}만".format(v / 10_000)
    return "{:,.0f}".format(v)


def chart(s2, H=260, simple=False):
    """기간별 입금(확정/추정)·지급(확정/추정) 막대와 계산 잔액 선. H = 그림 높이 (주간 대표 보고는 빈 곳을 채우게 더 높게).
    simple: 대표용 (2026-11-04 이해도 점검 U5) — 들어올 돈·나갈 돈·예상 잔액 3가지만 (확정·예상을 나누지 않음)."""
    bs = s2["buckets"]
    if not bs:
        return ""
    # 주 막대 이름은 위 자금 표와 같게: 이번 주·다음 주·3주째·4주째 (사용자 2026-11-04 디자인 검토)
    wk_name = {p["end"]: p["label"] for p in s2.get("periods") or [] if not p.get("pick")}
    Wd, pl, pr, pt, pb = 900, 52, 10, 26, 56   # 위·아래는 막대 숫자 자리 (사용자 2026-11-05: 막대마다 실제 숫자)
    n = len(bs)
    gw = (Wd - pl - pr) / n
    has_bal = s2["start"] is not None and not s2["out_missing"]  # 시작 잔액·지급 자료를 모르면 계산 잔액 선을 그리지 않는다 (0에서 시작하지 않음)
    vals = [0] + ([s2["start"]] if has_bal else [])
    for b in bs:
        vals += [b["in_firm"] + b["in_est"], -(b["out_firm"] + b["out_est"])]
        if has_bal:
            vals += [b["bal_firm"], b["bal_all"]]
    # 최소 보유현금 선 (2026-11-05 사용자: 대표 보고 디자인 제안 3) — 예상 잔액이 이 선 밑이면 점을 빨갛게
    mc = s2.get("min_cash") if has_bal else None
    if mc:
        vals.append(mc)
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
        out.append('<text x="%d" y="%.1f" font-size="14" text-anchor="end" fill="#5b6475">%s</text>'
                   % (pl - 5, y(v) + 4, _axis(v)))
    out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#1d2433"/>' % (pl, Wd - pr, y(0), y(0)))
    bw = gw * 0.34
    pts_f, pts_a, vals_txt = [], [], []   # vals_txt: 막대 숫자는 잔액 선 위에 그린다 (선에 가리지 않게)
    for i, b in enumerate(bs):
        x0 = pl + i * gw + gw * 0.14
        # 입금: 확정 아래, 추정 위에 쌓기
        y_f = y(b["in_firm"])
        y_e = y(b["in_firm"] + b["in_est"])
        x1 = x0 + bw + 2
        y_of = y(-b["out_firm"])
        y_oe = y(-(b["out_firm"] + b["out_est"]))
        # 대표용도 확정·예상을 나눠 그린다 (사용자 2026-11-05: 예상 자금은 따로 보게)
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#2f7d5b"/>' % (x0, y_f, bw, y(0) - y_f))
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#9cc9b3"/>' % (x0, y_e, bw, y_f - y_e))
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#b5523b"/>' % (x1, y(0), bw, y_of - y(0)))
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="#e2aa9b"/>' % (x1, y_of, bw, y_oe - y_of))
        # 막대마다 실제 금액 (원 단위, 사용자 2026-11-05). 들어올 돈은 막대 위, 나갈 돈은 막대 아래. 0원 막대는 숫자도 없음
        tin, tout = b["in_firm"] + b["in_est"], b["out_firm"] + b["out_est"]
        lab_style = 'font-size="12.5" text-anchor="middle" fill="#1d2433" stroke="#fff" stroke-width="3" paint-order="stroke"'
        if tin:
            vals_txt.append('<text class="bv" x="%.1f" y="%.1f" %s>%s</text>' % (x0 + bw / 2, y_e - 4, lab_style, won(tin)))
        if tout:
            vals_txt.append('<text class="bv" x="%.1f" y="%.1f" %s>%s</text>' % (x1 + bw / 2, y_oe + 11, lab_style, won(tout)))
        cx = pl + i * gw + gw / 2
        if has_bal:
            pts_f.append("%.1f,%.1f" % (cx, y(b["bal_firm"])))
            pts_a.append("%.1f,%.1f" % (cx, y(b["bal_all"])))
        lab = b["label"].replace(" (일부)", "*")
        if b["type"] == "week" and b.get("to") in wk_name:
            lab = wk_name[b["to"]]
        if b["type"] == "month":
            lab = lab.split(" ")[1]
        out.append('<text x="%.1f" y="%d" font-size="14" text-anchor="middle" fill="#1d2433">%s</text>'
                   % (cx, H - pb + 27, esc(lab)))
    if mc:
        out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#c0392b" stroke-width="1.2" stroke-dasharray="6 4"/>'
                   % (pl, Wd - pr, y(mc), y(mc)))
        out.append('<text x="%d" y="%.1f" font-size="13" text-anchor="end" fill="#c0392b">최소 보유현금 %s</text>'
                   % (Wd - pr - 2, y(mc) - 4, _axis(mc)))
    key = "bal_firm"   # 빨간 점은 확정분 잔액 기준 (사용자 2026-11-05)

    def dots(pts):
        for b, p in zip(bs, pts):
            x_, y_ = p.split(",")
            low = mc and b[key] < mc
            out.append('<circle cx="%s" cy="%s" r="%s" fill="%s"/>' % (x_, y_, "4" if low else "2.5", "#c0392b" if low else "#1f4e8c"))
    if has_bal:
        out.append('<polyline points="%s" fill="none" stroke="#1f4e8c" stroke-width="2"/>' % " ".join(pts_f))
        out.append('<polyline points="%s" fill="none" stroke="#1f4e8c" stroke-width="1.5" stroke-dasharray="4 3"/>'
                   % " ".join(pts_a))
        dots(pts_f)
    else:
        out.append('<text x="%d" y="%d" font-size="13" fill="#8a5a00">%s — 예상 잔액 선은 그리지 않음 (입금·지급 예정만 표시)</text>'
                   % (pl + 6, pt + 12, "지급 자료 없음" if s2["out_missing"] else "잔액 미확인"))
    out += vals_txt
    out.append(('<text x="%d" y="%d" font-size="12" fill="#5b6475">' + ("월별 (첫 달은 1일부터)" if all(b["type"] == "month" for b in bs) else "4주는 주별, 이후는 월별 (* 일부 기간)") + '</text>')
               % (pl, H - 8))
    out.append("</svg>")
    if simple:
        legend = ('<div class="legend"><span><i style="background:#2f7d5b"></i>들어올 돈</span>'
                  '<span><i style="background:#b5523b"></i>나갈 돈</span>'
                  '<span><i style="background:#e2aa9b"></i>예상 지급 (확정 전)</span>'
                  + ('<span><i style="background:#1f4e8c"></i>예상 잔액 (확정분)</span>'
                     '<span><i style="background:repeating-linear-gradient(90deg,#1f4e8c 0 3px,#fff 3px 5px)"></i>예상 지급까지 뺀 잔액</span>'
                     if has_bal else "")
                  + ('<span><i style="background:#c0392b"></i>최소 보유현금 밑 (빨간 점)</span>' if mc else "") + "</div>")
        return "".join(out) + legend
    legend = ('<div class="legend"><span><i style="background:#2f7d5b"></i>입금 확정분</span>'
              '<span><i style="background:#9cc9b3"></i>입금 예상분</span><span><i style="background:#b5523b"></i>지급 확정분</span>'
              '<span><i style="background:#e2aa9b"></i>지급 예상분</span>')
    if has_bal:
        legend += ('<span><i style="background:#1f4e8c"></i>예상 잔액(확정분만)</span>'
                   '<span><i style="background:repeating-linear-gradient(90deg,#1f4e8c 0 3px,#fff 3px 5px)"></i>예상 잔액(예상분 포함)</span>')
    if mc:
        legend += '<span><i style="background:#c0392b"></i>최소 보유현금 밑 (빨간 점)</span>'
    legend += "</div>"
    return "".join(out) + legend


def render(R, mode):
    st = R["settings"]
    p0, p1 = R["period"]
    kind = "주간" if R["kind"] == "weekly" else "월간"
    who = "보고" if mode == "ceo" else "경영관리 보고"   # 대표용 제목은 '주간 보고'·'월간 보고' (사용자 2026-11-04)
    s1, s2, s3, s4, s5, s6, s7 = (R[k] for k in ("s1", "s2", "s3", "s4", "s5", "s6", "s7"))
    per = "이번 주" if R["kind"] == "weekly" else "이번 달"
    h = []
    title = "%s %s %s" % (st.get("회사명", ""), kind, who)
    h.append("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
             "<meta name='viewport' content='width=device-width,initial-scale=1'><title>%s · %s</title><style>%s</style></head>"
             "<body><div class='wrap%s'>" % (esc(title), d2s(R["asof"]), CSS + FS_CSS + DOC_CSS + DOC2_CSS + DOC3_CSS + AIR_CSS + TYPE_CSS,
                                              # 월간은 인쇄 때 80%: 표가 넓어 A4 3쪽에 맞춤 (사용자 2026-11-04)
                                              "" if R["kind"] == "weekly" else " mon"))
    # 문서 머리 (사용자 2026-11-05: 진짜 문서처럼): 가운데 제목, 왼쪽 문서 정보 표, 오른쪽 결재란
    h.append("<div class='doc-h'>")
    # 대표용엔 '대표용' 표시를 붙이지 않음 (사용자 2026-11-04). 경영관리용만 표시
    h.append("<h1><span class='co'>%s</span>%s%s</h1>" % (
        esc(st.get("회사명", "")), esc("%s %s" % (kind, who)), "" if mode == "ceo" else " <span class='badge m'>경영관리용</span>"))
    if mode == "ceo" and R["kind"] == "weekly":   # 결재란: 대표가 서명해 회신 (사용자 2026-11-03)
        # 날짜 줄 없음 (사용자 2026-11-05: 결재란 날짜 삭제하고 더 예쁘게)
        h.append("<table class='sign'><tr><th rowspan='2' class='sv'>결<br>재</th><th>담당</th><th>대표이사</th></tr>"
                 "<tr class='sg'><td></td><td></td></tr></table>")
    h.append("<table class='dinfo'><tr><th>보고 기준일</th><td>%s</td><th>집계 기간</th><td>%s ~ %s</td></tr>"
             "<tr><th>작성</th><td>%s</td><th>금액 단위</th><td>원</td></tr></table>"
             % (d2s(R["asof"]), d2s(p0), d2s(p1), dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
    h.append("<div class='meta dsrc'>%s</div>" % esc(
        "자료 기준일: " + " · ".join("%s %s" % (a["name"], d2s(a["date"])) for a in R["s7"]["asof"])))
    h.append("</div>")

    fs_i = len(h)
    h.append(_first_screen(R, mode, per))
    # 풀이 안내(note mgx)는 경영관리용에만 (사용자 2026-11-05: 대표 월간 보고도 안내 최소). 자료 없음 경고는 남는다
    h = [re.sub(r"<div class='note mgx'>(.*?)</div>",
                (lambda m: _mg(mode, "<div class='note'>%s</div>" % m.group(1))), x) for x in h]
    if mode == "ceo":
        # 대표 보고는 문서로 1~2쪽: 요약 화면만 싣는다. 상세 장(1~8)은 경영관리 보고에만 (사용자 2026-11-03)
        h.append("</div></body></html>")
        return "".join(h)

    # 경영관리용 영역별 보기 (사용자 2026-11-11: 보기 불편 → 영역별로 나눠 보고, 필요하면 전체 출력)
    toc = ["현재 자금·입출금", "입금·지급 일정", "프로젝트 예산·집행", "매출·손익", "계산서·수금", "프로젝트 밖 지급", "변동·자료 범위"]
    chap = [_s1(R, per), _s2(R), _s3(R, per), _s4(R), _s5(R), _s6(R), _s7(R)]
    if R["kind"] == "monthly":
        toc.append(XCHK_TITLE)  # 월간에만 8번 (주간 보고는 바뀌지 않는다, D-44)
        chap.append(_s8(R, mode))
        from . import cashflow   # 9장 현금흐름표 (사용자 2026-11-12: 경영관리 보고에만, 영역 인쇄로 PDF)
        toc.append("현금흐름표")
        chap.append(cashflow.render(R.get("cf")))
    summ, evid = h[fs_i].split(areas.SUMMARY_MARK)
    evid = areas.SUMMARY_MARK + evid   # 표시는 남겨 둔다 (areas.strip_ui 가 예전 한 덩어리로 되돌릴 때 쓴다)
    hi = sum(1 for r in R["risks"] if r["level"] == "높음")
    G1, G2 = "보고 요약", "상세 자료"
    top = [("sum", "요약 (대표 보고 화면)", G1, summ, None), ("ev", "근거자료 · 확인할 것", G1, evid, None)]
    rest = [("risk", "위험 분석·해결방안", G1, _risk_section(R), hi or None)]
    rest += [("s%d" % i, "%d. %s" % (i, t), G2, body, None) for i, (t, body) in enumerate(zip(toc, chap), 1)]
    allk = top + rest

    def sec(i):
        k, lab, g, body, _ = allk[i]
        prev = allk[i - 1][:2] if i else None
        nxt = allk[i + 1][:2] if i + 1 < len(allk) else None
        return areas.section(k, lab, body + areas.pager(prev, nxt), g)
    out = h[:fs_i] + [sec(i) for i in range(len(top))]
    out.append(areas.nav([(k, lab, g, b) for k, lab, g, _, b in allk]))   # 예전 목차 자리 (첫 화면 | 상세 장 경계)
    out += [sec(i) for i in range(len(top), len(allk))]
    out.append("</div>" + areas.JS + "</body></html>")
    return "".join(out)


# 용어 풀이 (2026-11-04 대표 이해도 점검 U2): 첫 화면에 나오는 말만, 한 줄씩. 두 판 같음 (숫자 없음)
GLOSSARY = (
    ("쓸 수 있는 돈", "통장 잔액에서 정기예금·담보처럼 당장 못 꺼내는 돈을 뺀 것"),
    ("가장 적을 때", "오늘부터 그 기간 끝까지 들어오고 나가는 돈을 날마다 셈했을 때 잔액이 가장 적은 날의 잔액"),
    ("여유 자금", "가장 적을 때 잔액 − 늘 남겨 둘 돈(최소 보유현금). 그 기간에 더 쓸 수 있는 돈, 0보다 작으면 모자람"),
    ("예상", "날짜나 금액이 아직 확정되지 않은 돈"),
    ("미지급금", "물건·용역을 받고 아직 주지 않은 돈 (장부에 적힌 갚을 돈)"),
    ("차입금", "은행 등에서 빌린 돈"),
    ("매출총이익", "매출 − 그 일을 하는 데 직접 든 돈(외주·제작비 등). 매출총이익률 = 매출총이익 ÷ 매출"),
    ("영업이익", "매출총이익 − 사무실·인건비 같은 회사 운영비. 본업으로 번 돈"),
)


def _glossary(R):
    return ("<div class='gloss'><b>용어 풀이</b> " + " · ".join(
        "<span><b>%s</b>: %s</span>" % (esc(t), esc(x)) for t, x in GLOSSARY) + "</div>")


# ─────────── 대표 첫 화면 (2026-11-03 사용자: 한눈에, 원 단위, 업무 용어, 기간별 가용자금) ───────────
FS_CSS = """
.gloss{font-size:10.5px;color:#555;margin:8px 0 4px;padding:6px 8px;border-top:1px solid #ddd;line-height:1.5;break-inside:avoid}
.gloss span{white-space:normal}
.lout{margin-top:4px}.lout>b{font-size:11px}
@media print{.fs.mon .mchart svg{max-height:190px}.gloss{font-size:9px;line-height:1.35;padding:3px 6px;margin:4px 0 0}.fs ul.nl{columns:2;column-gap:18px;font-size:9.5px;margin-top:3px}.fs ul.nl li{break-inside:avoid}.lout>b{font-size:10px}}
.q{font-size:15px;font-weight:800;color:var(--ink);margin:18px 0 8px;padding-left:9px;border-left:4px solid var(--accent);line-height:1.25}.pgt{display:flex;align-items:center;gap:10px;font-size:12px;font-weight:700;color:var(--accent);letter-spacing:.04em;border-bottom:2px solid var(--accent);padding:2px 0 4px;margin:14px 0 2px}.pgt span{background:var(--accent);color:#fff;border-radius:9px;padding:0 8px;font-size:11px}.pg.last{page-break-after:auto}.pg .sec:first-of-type .q{margin-top:10px}
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
table.pt.wo td{white-space:normal}table.pt.wo th{text-align:left}table.pt.wo th:nth-child(5){text-align:right}table.pt.wo td:nth-child(2){text-align:left}table.pt.wo td:nth-child(3),table.pt.wo td:nth-child(4),table.pt.wo td:last-child{text-align:left}table.pt.wo tr.od td{color:var(--warn)}.wchg{margin-top:6px;font-weight:700}.frimain{border:2px solid var(--out)!important;background:#fffaf8!important}.fri{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:6px}.fri span{font-weight:700}.fri b{font-size:26px;font-weight:800;color:var(--out);font-variant-numeric:tabular-nums}.fri small{color:var(--sub)}table.pt.wn td:nth-child(2),table.pt.wn td:nth-child(3),table.pt.wn td:last-child{text-align:left}table.pt.wn th{text-align:left}table.pt.wn th:nth-child(4){text-align:right}table.pt.xr td{text-align:right}table.pt.xr td:first-child,table.pt.xr td:nth-child(2){text-align:left;white-space:normal}.card+.xbox{margin-top:6px}.evid{margin-top:10px;padding:6px 10px;border-top:1.5px solid var(--line);font-size:11.5px;color:var(--sub)}table.pt.xr td,table.pt.xr th{padding:2px 4px}table.pt.wn tr.tot td{font-weight:700;border-top:1.5px solid var(--ink)}.frimain{margin-bottom:8px}.wnc .wsub{margin:0 0 2px}table.pt.wn{font-size:12px;margin-top:2px}.wsub{margin:10px 0 4px;font-weight:800;font-size:12.5px;color:var(--ink)}table.pt.wo td:last-child{font-size:11px;color:var(--sub)}table.pt.tg{font-size:11.5px}table.pt.tg td{text-align:right}table.pt.tg td:first-child,table.pt.tg td:last-child{text-align:left}.tbar{position:relative;display:inline-block;width:60px;height:8px;background:#eef0f3;border-radius:4px;margin-right:6px;vertical-align:0}.tbar i{display:block;height:100%;background:var(--accent);border-radius:4px}.tbar s{position:absolute;top:-2px;bottom:-2px;width:2px;background:var(--ink)}table.pt.wo b.vn{font-weight:700}table.pt.wo small.dt{display:block;font-size:11px;color:var(--ink);white-space:normal}table.pt.wo small.dt.na{color:var(--est)}table.pt.wo td:nth-child(4){white-space:nowrap}table.pt.wo td:nth-child(7),table.pt.wo th:nth-child(7){text-align:right}table.pt.wo td:last-child,table.pt.wo th:last-child{text-align:right;white-space:nowrap;font-size:inherit;color:inherit}table.pt.wo td:last-child.vout{color:var(--out)}table.pt.wo .dt.na{color:var(--est);font-size:11px}table.pt.wo small.est{display:block;font-size:10.5px;color:var(--est)}.four.c3{grid-template-columns:repeat(3,minmax(0,1fr))}.four.top{clear:both;margin:10px 0 2px}.four.top .card{border:1.5px solid var(--line)}.four.top .card:first-child{border-color:var(--out)}.four.top .big{font-size:19px}.four.top .foot{font-size:11px}ul.nl{margin:6px 0 0;padding-left:16px;font-size:11px;color:var(--sub)}ul.nl li{margin:1px 0}.card table.pt.tm{font-size:10px}table.pt.tx{font-size:11px}table.pt.tx td,table.pt.tx th{padding:2px 4px}table.pt.tx td{text-align:right}table.pt.tx td:first-child{text-align:left}.card table.pt.tm td,.card table.pt.tm th{padding:3px 3px}.q .ev{display:inline-block;font-size:10px;font-weight:700;color:#6b3fa0;border:1px solid #c9b6e4;border-radius:6px;padding:0 5px;margin-left:6px;vertical-align:2px;letter-spacing:0}.evb{margin-top:10px}.evh{font-size:13px;font-weight:800;color:#6b3fa0;border-bottom:1.5px solid #6b3fa0;padding:2px 0;margin:10px 0 4px}table.pt.evt{font-size:11px}table.pt.evt td,table.pt.evt th{text-align:left;white-space:normal;padding:3px 5px}table.pt.evt td:last-child,table.pt.evt th:last-child{text-align:right;white-space:nowrap}.dec{border:2px solid var(--ink);border-radius:10px;padding:8px 14px;margin:8px 0}.dech{font-weight:800;font-size:13.5px;margin-bottom:4px}.dec ol{margin:0;padding-left:20px}.dec li{margin:2px 0;font-size:12.5px}.warnbar{background:#fbe9e7;border:1.5px solid var(--out);color:var(--out);border-radius:8px;padding:6px 12px;font-weight:700;font-size:12px;margin:8px 0}.overl{margin-top:8px;padding:7px 12px;border:1px solid var(--line);border-left:4px solid var(--out);border-radius:8px;font-size:12.5px}.overl small{color:var(--sub);font-size:11px}
table.pt.tm{font-size:11px;margin-top:2px}table.pt.tm td{padding:3px 4px}table.pt.tm th{padding:3px 4px}table.pt.tm tr.tot td{border-top:1.5px solid var(--ink);font-weight:700}table.pt.tm tr.hq td{font-weight:700;border-top:1px solid var(--line)}table.pt.tm tr.mut td{color:var(--sub)}table.pt.tm td:first-child{text-align:left;white-space:nowrap}table.pt.tm td:first-child small{display:block;font-size:9.5px;color:var(--sub);font-weight:400}
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
.mchart{margin-top:8px}.mchart svg{max-height:300px}.exprow{display:grid;grid-template-columns:1.1fr 1fr 1fr 1fr;gap:2px 10px;align-items:center;margin:0 0 8px;padding:6px 12px}.exprow .exp-b{grid-column:1/-1;border-top:1px solid var(--line);padding-top:3px;font-size:11px;color:var(--sub)}.exprow .exp-b+.exp-b{border-top:0;padding-top:0}.exprow .lab{white-space:nowrap}.exp-h b{display:block;font-size:13.5px;color:var(--accent)}.exp-h span{font-size:10.5px;color:var(--sub)}.exprow .big{font-size:18px}.exprow .big small{font-size:11px;font-weight:400;color:var(--sub)}.four{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.four .big{font-size:20px}
small.nin{display:block;color:var(--in);font-size:10.5px}
.xbox{background:#fff8e6;border:1px solid #f0dca8;border-radius:10px;padding:10px 16px}
.xbox ul{margin:2px 0 0;padding-left:18px;columns:2;column-gap:28px}.xbox li{margin:2px 0;break-inside:avoid}
table.pt.ayt{font-size:9.5px;table-layout:auto}table.pt.ayt th,table.pt.ayt td{padding:3px 2px}table.pt.ayt th{text-align:right}table.pt.ayt th:first-child{text-align:left}
table.pt.ayt td:first-child{white-space:nowrap;max-width:96px;overflow:hidden;text-overflow:ellipsis}table.pt.ayt .fut{background:#f6f7f9}
table.pt.ayt tr.gh td{font-weight:700;text-align:left;background:var(--soft);padding-top:5px}table.pt.ayt tr.sub td{font-weight:700;border-top:1px solid var(--line)}
table.pt.ayt tr.tot td{font-weight:800;border-top:1.5px solid var(--ink)}table.pt.ayt td.yt{font-weight:700;background:#eef3fb}
@media screen and (max-width:820px){.four,.exprow{grid-template-columns:1fr 1fr}.exprow .lab{white-space:normal}.prow{grid-template-columns:minmax(0,1fr) auto}.prow .bw{grid-column:1/-1;order:3}
.xbox ul{columns:1}table.pt{display:block;overflow-x:auto}}
@media print{.sec.brk,.sec.brk .frimain{break-inside:auto}.sec.brk table.pt.wo td{padding:2px 6px}.sec.brk table.pt.wo{font-size:11.5px}.sec.brk table.wo thead{display:table-header-group}.sec.brk .fri{break-after:avoid}.q{break-after:avoid}.fs .big{font-size:20px}.fs table.pt{font-size:11.5px}table.pt td{padding:5px 6px}table.pt.tm td,table.pt.tm th{padding:4px 5px}table.pt.tm{font-size:11px}
.fs svg{max-height:200px}.fs.mon svg{max-height:262px}.fs.mon svg{max-height:262px}.fs .card{padding:10px 14px}.fs .sec{margin-bottom:6px}table.pt.ayt{font-size:9px}table.pt.ayt td,table.pt.ayt th{padding:1.5px 2px}}
@media print{.fs svg{max-height:200px}.fs.mon svg{max-height:262px}.fs.mon svg{max-height:262px}table.pt.ayt td,table.pt.ayt th{padding:2px}.fs .card{padding:8px 12px}.pg{min-height:0}}
@media print{.fs.mon .card table.pt.tm{font-size:11px}.fs.mon .card table.pt.tm td,.fs.mon .card table.pt.tm th{padding:4px 2px}.fs.mon table.pt.tg{font-size:12.5px}.fs.mon table.pt.tg td,.fs.mon table.pt.tg th{padding:5px 6px}.fs.mon .sec.pgb{break-before:page}
@media print{table.pt.wo small.dt{display:inline}table.pt.wo small.dt::before{content:" · "}table.pt.wo td{padding-top:2px!important;padding-bottom:2px!important}}
table.pt.xr th:nth-child(2),table.pt.tg th:last-child{text-align:left}
table.pt.taxq th,table.pt.taxq td{text-align:right!important}table.pt.taxq th:first-child,table.pt.taxq td:first-child{text-align:left!important}table.pt.taxq th:nth-child(2),table.pt.taxq td:nth-child(2){text-align:center!important}
.sec.sflow{break-inside:auto}.sec.sflow>.card,.sec.sflow .avail>.tw,.sec.sflow .avail>.lab{break-inside:avoid}.q{break-after:avoid}.fs:not(.mon) svg{max-height:215px}.evid{margin-top:4px;padding:3px 10px;font-size:10px;break-before:avoid}.fs.mon svg{max-height:300px}.fs.mon .card:not(.mchart) svg{max-height:190px}.fs.mon .four .lab{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.fs.mon table.pt.ayt{font-size:10.5px;zoom:.86}.fs.mon table.pt.ayt td,.fs.mon table.pt.ayt th{padding:2px 2px}.fs.mon table.pt.ayt td:first-child{max-width:150px}}
.fs table.pt.wo tbody td:last-child,.fs table.pt.wn tbody td:nth-child(4){font-size:13px;font-weight:700;font-variant-numeric:tabular-nums}.fs #avail tbody td.vin,.fs #avail tbody td.vout{font-size:13.5px;font-weight:700;font-variant-numeric:tabular-nums}.fs #avail td.av b{font-size:18px}.fs #avail td small,.fs table.pt.wo td small{font-weight:400}.fs ul.nl.one{list-style:none;padding-left:0;columns:1!important}
"""

# 글자 크기·두께 단계 정리 (사용자 2026-11-05: "폰트 크기나 두께는 수정하지 않아도 돼?"): 여러 겹에서 쌓인 9.2~22px·400~800 을
# 6단계(21 제목 · 18 큰 숫자 · 14 절 제목 · 12.5 소제목 · 11.5 본문·표 · 10 보조)와 두께 3단계(400·600·700)로 맞춘다.
TYPE_CSS = """
.doc-h h1{font-size:21px!important;font-weight:700!important}
.fs .big,.four .big,.four.top .card .big,.fri b,.fs #avail td.av b{font-size:18px!important;font-weight:700!important;letter-spacing:-.01em}
.flow .op{font-size:18px!important}
.q{font-size:14px!important;font-weight:700!important}
.wsub,.evh,.dech{font-size:12.5px!important;font-weight:700!important}
.four .card .lab,.flow .lab,.exprow .lab{font-size:12px!important;font-weight:600!important}
.avail>.lab{font-size:12.5px!important}
.exp-h b{font-size:12.5px!important}
.fs table.pt,.fs.mon table.pt.tg,.fs.mon .card table.pt.tm,.sec.brk table.pt.wo{font-size:11.5px!important}
table.pt th,.fs table th{font-size:11px!important;font-weight:600!important}
.fs table.pt.wo tbody td:last-child,.fs table.pt.wn tbody td:nth-child(4){font-size:12px!important;font-weight:600!important}
.fs #avail tbody td.vin,.fs #avail tbody td.vout{font-size:14px!important;font-weight:700!important}
.fs #avail td small{font-size:10.5px!important}
table.pt tr.tot td,table.pt.ayt tr.tot td{font-weight:700!important}
.four .card .foot,.fs .foot{font-size:11px!important}
.wchg{font-size:11px!important;font-weight:600!important}
.note,.meta,.dsrc,.ev,span.ev,.evid,.fs ul.nl,.fs ul.nl li,.exp-b,.exprow .exp-b,.keys,td small,small{font-size:10px!important}
.fs #avail td.av small{font-size:10px!important}
.chip{font-size:10px!important}
.exprow>.mgonly{grid-column:1/-1}
.exp-c.tot .big{text-decoration:underline;text-decoration-thickness:2px;text-underline-offset:4px}
@media print{.fs.mon .card:not(.mchart) svg{max-height:250px!important}.fs.mon .mchart svg{max-height:290px!important}}
"""

CIRCLED = ("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "10.")   # 문서 절 번호 (2026-11-05)


def _ev_span(tags):
    """근거 번호를 한 꼬리표로: 같은 절의 이어진 번호는 '근거 1-1~1-3' (사용자 2026-11-04 디자인 검토)."""
    if not tags:
        return ""
    t = list(tags)
    if len(t) > 1:
        head = {x.split("-")[0] for x in t}
        nums = [int(x.split("-")[1]) for x in t]
        if len(head) == 1 and nums == list(range(nums[0], nums[0] + len(nums))):
            return "<span class='ev'>근거 %s~%s</span>" % (esc(t[0]), esc(t[-1]))
    return "<span class='ev'>근거 %s</span>" % esc(", ".join(t))


def _q(i, text, tags=()):
    ev = _ev_span(tags)
    return "<div class='q'>%s %s%s</div>" % (CIRCLED[i], esc(text), ev)


def evidence_index(R):
    """근거 번호 (사용자 2026-11-03): 대표용 숫자 옆 번호 → 경영관리용 근거 자리.
    번호 앞자리 = 대표용 절 번호. (번호, 대표용 항목, 'block' | 상세 장 id). block = 경영관리용 첫 화면 근거 묶음의 id='ev-번호'."""
    if R["kind"] == "weekly":
        return [("1-1", "출금 목록 · 건별 원자료", "block"), ("1-2", "지난주 대비 · 건별", "block"),
                ("1-3", "다음 주 지급 예정 · 건별", "block"),
                ("2-1", "현재 잔액·사용제한", "s1"), ("2-2", "기간별 가용자금·자금 흐름 (일정 건별)", "s2"),
                ("3-1", "매출·이익", "s4"), ("3-2", "행사 후 세금계산서 미발행", "s5")]
    return [("1-1", "이번 달 자금 흐름 (거래 내역)", "s1"),
            ("2-1", "기간별 가용자금·월별 자금 흐름 (일정 건별)", "s2"),
            ("3-1", "입금일 지난 미수금", "s5"), ("3-2", "지급일 지난 출금", "s2"),
            ("4-1", "부가세·원천세", "s6"),
            ("5-1", "이번 달 매출·이익", "s4"), ("5-2", "팀별 급여·판관비·인원 (팀 표 아래 설명 · 상세 4장)", "s4"),
            ("6-1", "누적 실적·팀 목표", "block"),
            ("7-1", "계정과목별 사용 금액", "s8")]


def _ev_tags(R, sec_no):
    return [n for n, _, _ in evidence_index(R) if n.split("-")[0] == str(sec_no)]


def _flow_card(s1, per):
    """월간: 기간 시작 잔액 + 입금 − 지급 = 기간 말 잔액 (계좌 간 이체 제외)."""
    cells = [("월초 잔액", W(s1["start_calc"]), ""), ("+", None, ""), ("입금", W(s1["in"]), " vin"), ("−", None, ""),
             ("지급", W(s1["out"]), " vout"), ("=", None, ""), ("월말 잔액", W(s1["end"]), "")]
    h = ["<div class='card flow'>"]
    for lab, v, cls in cells:
        h.append("<div class='op'>%s</div>" % lab if v is None else
                 "<div><div class='lab'>%s</div><div class='big%s'>%s</div></div>" % (esc(lab), cls, v))
    h.append("</div><div class='note mgx'>%s</div>" % esc("계좌 간 이체 입금 %s / 출금 %s 제외 · 은행 기준일 %s%s"
                                                  % (won(s1["transfer_in"]), won(s1["transfer_out"]), _bank_dates(s1), _bal_note(s1))))
    return "".join(h)


def _avail_cell(p):
    """여유 자금 칸: 확정분만을 크게, 그 아래 예상분 포함을 작게 (사용자 2026-11-05: 예상 자금을 먼저 빼지 않고 따로 보게)."""
    f = p["firm"]["avail"]
    big = _na("확인 필요") if f is None else "<b class='%s'>%s</b>" % ("neg" if f < 0 else "", esc(won(f)))
    return "<td class='av'>%s%s</td>" % (big, _est_note(p))


def _est_note(p):
    """'예상 포함 시 …' 작은 줄. 확정분과 같으면 적지 않는다."""
    a, f = p["all"]["avail"], p["firm"]["avail"]
    if a is None or a == f:
        return ""
    return "<small class='firm%s'>예상 지급까지 빼면 %s</small>" % (" neg" if a < 0 else "", esc(won(a)))


def _est_extra(p, key):
    """그 기간 예상분(확정 안 된 것)만의 입금·지급 합계."""
    return p["all"].get(key, 0) - p["firm"].get(key, 0)


def _avail_rows_ceo(periods, s2=None):
    """대표용 4칸 (2026-11-04 이해도 점검 U5): 기간 · 들어올 돈 · 나갈 돈 · 여유 자금(가장 적을 때 잔액과 날짜를 작게)."""
    in_tag = "<small class='na'>계산서 자료 없음</small>" if s2 and s2["in_missing"] else ""
    out_tag = "<small class='na'>지급 자료 없음</small>" if s2 and s2["out_missing"] else ""
    rows = []
    for p in periods:
        r = p["firm"]
        a = r["avail"]
        big = _na("확인 필요") if a is None else "<b class='%s'>%s</b>" % ("neg" if a < 0 else "", esc(won(a)))
        # 가장 적을 때 잔액·날짜는 경영관리용 근거 표(avail-mg)에만 (사용자 2026-11-05: 여유 자금 칸의 필요 없는 안내 제외)
        low = _est_note(p)
        xin, xout = _est_extra(p, "pin"), _est_extra(p, "pout")
        rng = ("오늘~" + d2s(p["end"]) if p.get("pick") or not p.get("from")
               else "%s~%s" % (_md(p["from"]), _md(p["end"])))
        rows.append("<tr%s><td><b>%s</b><small>%s</small></td><td class='vin'>%s</td><td class='vout'>%s</td>"
                    "<td class='av'>%s%s</td></tr>"
                    % (" class='pick'" if p.get("pick") else "", esc(p["label"]), esc(rng),
                       esc(won(r.get("pin", r["in"]))) + in_tag + (_xs("예상 +", xin)),
                       esc(won(r.get("pout", r["out"]))) + out_tag + (_xs("예상 −", xout)), big, low))
    return "".join(rows)


def _xs(lab, v):
    return "<small class='firm'>%s%s 별도</small>" % (esc(lab), esc(won(v))) if v else ""


def _left_out_lines(R):
    """여유 자금에 안 들어간 지급·채무 (2026-11-04 누락 점검 A1·A2·A3): 두 판 같은 줄. 사실과 금액만 (해석 없음)."""
    s2, D = R["s2"], R.get("debts")
    out = []
    if s2["undated_out_n"]:
        out.append("날짜 없는 지급 예정 %s" % _amt_n(s2["undated_out"], s2["undated_out_n"], s2["undated_out_unknown"]))
    if s2["past_out_n"]:
        out.append("예정일이 지났는데 안 나간 지급 %s" % _amt_n(s2["past_out"], s2["past_out_n"], s2["past_out_unknown"]))
    if s2["out_unknown_n"]:
        out.append("금액을 모르는 지급 예정 %d건" % s2["out_unknown_n"])
    two = R.get("two_source") or []
    if two:
        g = two[0]
        out.append("같은 거래처·같은 달 출금이 두 출처에 있음 %d곳 (가장 큰 곳 %s %s월: %s) — 같은 돈이면 하나를 지우세요" % (
            len(two), g["vendor"], int(g["month"][5:]), " · ".join("%s %s" % (k, won(v)) for k, v in g["sources"].items())))
    if D is None:
        out.append("장부 미지급금·차입금 대조 안 함 (장부채무.csv 없음 — 자료 변환 필요)")
    else:
        if D["unscheduled"]:
            top = D["unscheduled"][0]
            out.append("장부에 있는 미지급금 중 지급일이 일정에 없는 것 %s (%d곳 · 가장 큰 곳 %s %s · 장부 %s 기준)" % (
                won(D["unscheduled_total"]), len(D["unscheduled"]), top["vendor"], won(top["left"]), D["date"] or "-"))
        if D.get("over"):
            top = D["over"][0]
            out.append("미지급금 지급 예정이 장부 잔액보다 큰 거래처 %s (%d곳 · 가장 큰 곳 %s 예정 %s · 장부 %s) — 이중 계상이거나 장부에 아직 없는 빚" % (
                won(D["over_total"]), len(D["over"]), top["vendor"] or top["vcode"], won(top["scheduled"]), won(top["balance"])))
        if D["unknown_n"]:
            out.append("미지급금 금액 미확인 %d곳" % D["unknown_n"])
        for ln in D["loans"]:
            out.append("차입금 %s %s%s — 상환은 자금계획서·자금일정에 적힌 것만 반영" % (
                ln["vendor"] or ln["account"], won(ln["balance"]), " (만기 %s)" % ln["due"] if ln.get("due") else ""))
        if D["loan_unknown_n"]:
            out.append("차입금 금액 미확인 %d건" % D["loan_unknown_n"])
        for ln in D.get("repaid_loans", []):
            out.append("차입금 %s 올해 갚은 원금 %s — 남은 원금은 분개장에 없음 (작년 말 잔액 확인 필요)" % (
                ln["vendor"] or ln["account"], won(-ln["balance"])))
        if not D.get("opening", True):
            out.append("미지급금·차입금은 올해 분개장만으로 셈 (분개장에 전기이월 없음) — 작년 말 잔액만큼 더 있을 수 있음")
    return out


def _amt_n(total, n, unk):
    if total is None:
        return "%d건 (금액 미확인)" % n
    return "%s (%d건%s)" % (won(total), n, " · 금액 미확인 %d건" % unk if unk else "")


def _plan_basis(R):
    """자금 일정이 무엇으로 만들어졌는지 한 줄 (2026-11-04 누락 점검 A7)."""
    F = R.get("fundplan")
    if F is None:
        return "자금 일정 기준: 자금계획서 없음 → 손으로 넣은 자금일정과 장부·인트라넷 자료"
    if not F.get("used"):
        return "자금 일정 기준: 자금계획서 안 씀 (%s)" % (F.get("reason") or "-")
    return "자금 일정 기준: WEHAGO 자금계획서 (자료일 %s · %s) + 손으로 넣은 자금일정" % (
        d2s(F["stamp"]), ", ".join("%d월" % int(m[5:]) for m in F["months"]))


def _avail_rows(periods, s2=None):
    """확정분만 기준 한 줄씩 (예상분은 칸 아래 작게). in_missing·out_missing 이면 입금·지급 칸 숫자 옆에 자료 없음을 적는다 (빠진 채 0처럼 보이지 않게)."""
    in_tag = "<small class='na'>계산서 자료 없음</small>" if s2 and s2["in_missing"] else ""
    out_tag = "<small class='na'>지급 자료 없음</small>" if s2 and s2["out_missing"] else ""
    rows = []
    for p in periods:
        r = p["firm"]
        xin, xout = _est_extra(p, "pin"), _est_extra(p, "pout")
        low = _na("확인 필요") if r["low"] is None else "%s<small>(%s)</small>" % (
            esc(won(r["low"])), esc("오늘" if r["low_date"] == p.get("asof") else d2s(r["low_date"])[5:].replace("-", "/")))
        rng = ("오늘~" + d2s(p["end"]) if p.get("pick") or not p.get("from")
               else "%s~%s" % (_md(p["from"]), _md(p["end"])))
        rows.append("<tr%s><td><b>%s</b><small>%s</small></td><td class='vin'>%s</td><td class='vout'>%s</td>"
                    "<td><b>%s</b></td><td>%s</td>%s</tr>"
                    % (" class='pick'" if p.get("pick") else "", esc(p["label"]), esc(rng),
                       esc(won(r.get("pin", r["in"]))) + in_tag + _xs("예상 +", xin),
                       esc(won(r.get("pout", r["out"]))) + out_tag + _xs("예상 −", xout),
                       W(r["bal"], "확인 필요"), low, _avail_cell(p)))
    return "".join(rows)


def _card_thin(R):
    """카드 전표 입력 전 경고 (사용자 2026-11-04: 카드 전표는 한 달에 한 번 전월분을 한꺼번에 넣음 → 3달 평균으로 예상 + 경고)."""
    from .tax import CARD_THIN_MARK
    got = [t for t in (R.get("tax") or []) if str(t.get("basis") or "").startswith(CARD_THIN_MARK) and t.get("matched") is None
           and t.get("due") is not None]
    if not got:
        return ""
    return ("카드 전표 입력 전: %s 은 전표가 덜 들어간 카드의 최근 3달 평균을 예상으로 더 잡은 것. 카드로 쓴 비용은 전표를 넣기 전까지 프로젝트 원가·수익률에 빠져 있음"
            % ", ".join("%s %s %s" % (str(t["period"]).split("카드")[0], _md(t["due"]), won(t["amount"])) for t in got))


def _avail_table(R, mode="mgmt"):
    """기간별 가용자금 표: 주간 1~4주, 월간 1~3개월 + 지정일 줄(보고서를 만들 때 --가용일 로 넣은 날짜) (사용자 2026-11-03).

    보고서는 문서(PDF)로 전달하므로 단추·날짜 입력 칸 없이 모든 값이 그대로 보인다 (사용자 2026-11-03).
    가용자금 = 기간 중 최저 잔액 − 최소 보유현금. 줄은 확정분만 기준이고 (사용자 2026-11-05), 예상분(남은 예산 등)은 칸 아래에 따로 적는다."""
    s1, s2 = R["s1"], R["s2"]
    periods = [dict(p, asof=R["asof"]) for p in s2["periods"]]
    mc = s2["min_cash"]
    # 대표용은 '쓸 수 없는 돈 (담보·전용)', 사용제한금액 빈칸 경고는 경영관리용에만 (사용자 2026-11-04)
    rname = RESTRICT_CEO if mode == "ceo" else "사용제한"
    # 빈칸을 0으로 단정해 보이지 않게 (2026-11-04 누락 점검 A6): 두 판 모두 '확인 안 됨 n계좌'
    runk = " (확인 안 됨 %d계좌)" % s1["restr_unknown"] if s1["restr_unknown"] else ""
    # 제목 줄은 시작 금액만 (사용자 2026-11-05: 여유 자금은 최소한의 안내만). 계좌 합계·쓸 수 없는 돈·은행 기준일 풀이는 경영관리용에만
    h = ["<div class='card avail'><div class='lab'>기간별 여유 자금 <span style='font-weight:400'>%s</span></div>"
         % esc("시작: 오늘 쓸 수 있는 돈 %s%s" % (_won_or_unknown(s2["start"]), runk))]
    h.append(_mg(mode, "<div class='note'>%s</div>" % esc("오늘 쓸 수 있는 돈 = 계좌 합계 %s − %s %s%s · 은행 기준일 %s%s" % (
        _won_or_unknown(s1["total"]), rname, won(s1["restricted"]), runk, _bank_dates(s1), _bal_note(s1)))))
    if s1["restr_unknown"]:
        names = [a["account"] for a in s1["accounts"] if a["restricted"] is None]
        h.append(_mg(mode, "<div class='warnbar'>%s</div>" % esc(
            "사용제한금액 빈칸 %d계좌 (%s): 0으로 계산함. 담보·전용 자금이면 계좌잔액.csv에 금액을 적으세요."
            % (s1["restr_unknown"], ", ".join(names)))))
    mc_txt_plain = won(mc) if mc is not None else "설정 오류"
    mc_txt = esc(mc_txt_plain)
    # 두 판 같은 4칸 (2026-11-04 이해도 점검 U5). 확정분만·기간 끝 잔액은 경영관리용 근거 표에만 (두 판 숫자 비교는 mgonly 를 뺀다)
    head = ("<thead><tr><th>기간</th><th>들어올 돈</th><th>나갈 돈</th>"
            "<th class='av'>여유 자금</th></tr></thead>")
    h.append("<div class='tw'><table class='pt' id='avail'>%s<tbody>%s</tbody></table></div>" % (head, _avail_rows_ceo(periods, s2)))
    head_mg = ("<thead><tr><th>기간</th><th>그 기간 들어올 돈</th><th>그 기간 나갈 돈</th><th>기간 끝 예상 잔액</th><th>오늘부터 가장 적을 때 잔액</th>"
               "<th class='av'>여유 자금<br><small>최소 보유현금 %s 남김</small></th></tr></thead>" % mc_txt)
    h.append(_mg(mode, "<div class='tw'><div class='lab'>근거: 기간 끝 잔액 · 확정분만 (예상분은 작게)</div><table class='pt' id='avail-mg'>%s<tbody>%s</tbody></table></div>"
                 % (head_mg, _avail_rows(periods, s2))))
    notes = ["들어올 돈·나갈 돈은 그 기간에 들어오고 나가는 금액" + (" (한 주 = 출금일 다음 날부터 다음 출금일까지: 출금 목록·다음 주 지급 예정과 같은 기간)"
                                                    if R["kind"] == "weekly" else " (달별: 아래 월별 자금 흐름과 같은 기간)"),
             "여유 자금 = 오늘부터 그 기간 끝까지 잔액이 가장 적을 때 − 최소 보유현금. 기간 끝 잔액이 넉넉해도 그 사이 가장 적을 때를 넘겨 쓰면 자금이 모자람.",
             "여유 자금은 확정된 돈만으로 계산. 확정 안 된 예상 금액은 '별도'·'예상 지급까지 빼면'으로 따로 적음"]
    if R["kind"] == "monthly":   # 월간은 정의 한 줄만 (두 판 같은 숫자) (사용자 2026-11-04: 글자 키우고 3쪽)
        notes = ["여유 자금 = 그 기간 잔액이 가장 적을 때 − 최소 보유현금 · 확정된 돈만 (예상 금액은 따로 적음)"]
    notes.append(_plan_basis(R))
    if s2.get("pick_beyond"):
        notes.append("지정일이 일정 자료 범위(%s)보다 뒤라 그 뒤 일정은 반영 안 됨" % d2s(s2["horizon"]))
    if s2["out_missing"]:
        notes.append("지급 자료 없음: %s — 잔액·여유 자금은 계산하지 않음" % ", ".join(s2["out_missing"]))
    if s2["in_missing"]:
        notes.append("계산서 입금 예정 미반영 (자료 없음: %s)" % _inv_files(s2))
    if s2["vat_unknown_n"]:
        notes.append("부가세 미확인 %d건 (공급가액만 반영)" % s2["vat_unknown_n"])
    thin = _card_thin(R)
    if thin:
        notes.append(thin)
    # 두 판 모두 안내 한 줄만 (사용자 2026-11-05: 최소만 남기고 전부 삭제). 나머지 설명은 경영관리용에만
    h.append("<ul class='nl one'><li>%s</li></ul>" % esc(
        "여유 자금 = 기간 중 잔액이 가장 적을 때 − 최소 보유현금 %s · 확정된 돈만 (예상은 '별도'로 따로 적음)" % mc_txt_plain))
    warn = [t for t in notes if t.startswith(WARN_NOTES)]   # 자료 없음·미반영 경고는 두 판 모두 (0으로 보이지 않게)
    if warn:
        h.append("<ul class='nl'>%s</ul>" % "".join("<li>%s</li>" % esc(t) for t in warn))
    h.append(_mg(mode, "<ul class='nl'>%s</ul>" % "".join("<li>%s</li>" % esc(t) for t in notes if t not in warn)))
    left = _left_out_lines(R)   # 여유 자금에 안 들어간 것 (2026-11-04 누락 점검 A1·A2·A3) — 2026-11-05 부터 경영관리용에만
    if left:
        h.append(_mg(mode, "<div class='lout'><b>여유 자금에 안 들어간 것</b><ul class='nl'>%s</ul></div>"
                     % "".join("<li>%s</li>" % esc(t) for t in left)))
    D = R.get("debts")
    if D and D["unscheduled"]:   # 목록 (사용자 2026-11-05: 지급일이 일정에 없는 미지급금은 어디서 보나) — 경영관리용에만
        rows = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            esc("%s [%s]" % (r["vendor"], r["vcode"]) if r.get("vcode") else r["vendor"]), esc(won(r["balance"])),
            esc(won(r["scheduled"])), esc(won(r["left"]))) for r in D["unscheduled"])
        h.append(_mg(mode, "<div class='wsub'>장부 미지급금 중 지급일이 일정에 없는 것 (장부 %s 기준 · %d곳 · %s)</div>"
                     "<table class='pt xr'><thead><tr><th>거래처</th><th>장부 미지급금</th><th>일정에 있는 지급</th><th>일정에 없는 금액</th></tr></thead>"
                     "<tbody>%s</tbody></table>" % (esc(D["date"] or "-"), len(D["unscheduled"]), esc(won(D["unscheduled_total"])), rows)))
    h.append("</div>")
    return "".join(h)


WARN_NOTES = ("지정일이 일정 자료 범위", "지급 자료 없음", "계산서 입금 예정 미반영", "부가세 미확인", "카드 전표 입력 전")
RESTRICT_CEO = "쓸 수 없는 돈 (담보·전용)"   # 대표용 '사용제한' 이름 (사용자 2026-11-04)


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


def _active_by_event(s3, n_show):
    """주간: 지금 지급이 진행 중인 프로젝트 (사용자 2026-11-03) = 남은 지급(지급요청·카드 미결제·미요청 계획)이 있거나,
    완료 전인데 이미 지급이 시작된 것. 행사일 순 (행사일 없는 것은 맨 뒤). -> (보일 것, 나머지)."""
    def active(P):
        pending = P["requested"] + P["card_unpaid"] + P["planned"]
        unknown = sum(P["line_unknown"].get(st, 0) for st in UNPAID_STATES + PLAN_STATES)   # 금액 모르는 남은 지급도 진행 중
        done = (P.get("state") or "").strip() == "완료"
        return pending > 0 or unknown > 0 or (not done and P["paid_total"] > 0)
    def key(P):
        d = _event_date(P.get("event_date"))
        return (d is None, d.isoformat() if d else "", P["id"])
    act = sorted([P for P in s3["projects"] if active(P)], key=key)
    shown = act[:n_show]   # 첫화면_프로젝트_표시수 설정을 그대로 따른다
    return shown, [P for P in s3["ranked"] if P not in shown]


def _project_bars(R, per, flagged_only=False, active_only=False):
    """프로젝트 원가 예산 막대: 집행액(지급 완료) · 집행 예정액(요청·카드 미결제·미요청 계획) · 예산선.

    flagged_only: 월간 대표 보고는 '예산 내'가 아닌 프로젝트만 막대로 보이고 나머지는 '외 n건' 한 줄로 묶는다 (A4 세로 2쪽)."""
    s3 = R["s3"]
    tot = s3["total"]
    shown = s3["shown"]
    rest = s3["rest"]
    if active_only:
        shown, rest = _active_by_event(s3, len(s3["shown"]))
    if flagged_only:
        ok = [P for P in shown if "c-ok" in _proj_chip(P)]
        shown = [P for P in shown if P not in ok]
        rest = ok + list(rest)
    scale = max([max(P["budget"] or 0, P["paid_total"] + P["requested"] + P["card_unpaid"] + P["planned"]) for P in shown] or [0]) or 1
    h = ["<div class='card brk'><div class='keys'><span><i style='background:var(--accent)'></i>집행액 (지급 완료)</span>"
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
    if rest:
        r = rest
        ra = _agg_lines(r)
        h.append("<div class='prow sub'><div class='pn'>%s</div><div class='bn'>원가 예산 %s · 집행액 %s · 집행 예정액 %s</div><div></div></div>"
                 % (esc(("예산 내 등 외 %d건" if flagged_only else "그 밖의 프로젝트 %d건" if active_only else "외 %d건") % len(r)), W(_sum_opt(x["budget"] for x in r)),
                    _amt_lines(W, sum(x["paid_total"] for x in r), ra, *PAID_STATES),
                    _amt_lines(W, sum(x["requested"] + x["card_unpaid"] + x["planned"] for x in r), ra, *(UNPAID_STATES + PLAN_STATES))))
    nb = _no_budget_note(s3)
    rem = tot["remain"]
    rem_txt = _na("확인 필요") if rem is None else (
        "<b class='neg'>%s 초과</b>" % esc(won(-rem)) if rem < 0 else "<b>%s</b>" % esc(won(rem)))
    h.append("<div class='ptot'><span>%s%s</span><span>전체 원가 예산 %s · 집행액 %s · 집행 예정액 %s · 잔여 예산 %s%s</span></div>"
             % (esc("표시 %d건 / 전체 %d건 (%s)" % (len(shown), len(s3["projects"]),
                                               "지급 진행 중, 행사일 순" if active_only else "원가 예산 큰 순")), esc(" · " + nb) if nb else "",
                W(tot["budget"], "확인 필요"), _amt_lines(W, tot["paid_total"], tot, *PAID_STATES),
                _amt_lines(W, tot["requested"] + tot["card_unpaid"] + tot["planned"], tot, *(UNPAID_STATES + PLAN_STATES)),
                rem_txt, _na(_remain_excluded_text(tot))))
    h.append("<div class='note'>잔여 예산 = 원가 예산 − (집행액 + 집행 예정액). 예산이 지정된 프로젝트만 합계. 미확인 원가가 있는 프로젝트는 ‘확인 필요’로 두고 합계에서 뺌. "
             "진행 중 프로젝트의 잔여 예산은 부가세 10%를 더해 행사일 다음 달 말 금요일 지급 예정으로 자금 일정에 넣음 "
             "(그 날이 지났으면 기준일 다음 금요일, 행사일 없으면 날짜 없는 지급 예정). 완료 프로젝트는 넣지 않음.</div></div>")
    return "".join(h)


def _results(R, cum=True):
    """실적 칸 4개: 매출 · 이익(마감 전) · 미수금 · 행사 후 세금계산서 미발행. cum=False(월간)면 누적은 따로 보이므로 빼고 그 달 숫자만."""
    s4, s5 = R["s4"], R["s5"]
    cards = []
    src = s4["sources"].get("WEHAGO")
    co = [r for r in src["table"] if r["unit"] == "회사"] if src else []
    c, y = (co[0]["cur"], co[0]["ytd"]) if co else (None, None)
    ym = _ym_text(s4["ym"])
    if c:
        tag = " <span class='chip c-q'>마감 전</span>" if c["provisional"] else ""
        if cum:
            cards.append(("%s 매출" % ym, W(c["revenue"]), "올해 누적 %s" % (W(y["revenue"]) if y else _na("자료 없음"))))
            prev = _prev_month_pl(R, src) if R["asof"].day <= EARLY_MONTH_DAYS else None
            if prev is not None:
                # 달 초에는 이번 달 비용만 먼저 잡혀 이익이 크게 마이너스로 보인다 → 지난달 영업이익 (2026-11-04 이해도 점검 U4)
                pm, pc = prev
                ptag = " <span class='chip c-q'>마감 전</span>" if pc["provisional"] else ""
                cards.append(("%s 영업이익 (지난달)%s" % (esc(_ym_text(pm)), ptag), W(pc["np"], "확인 필요"),
                              "영업이익률 %s · 올해 누적 %s · %s은 %d일 지나 이익은 다음 보고부터" % (
                                  esc(pct(pc["np"], pc["revenue"])), W(y["np"], "확인 필요") if y else _na("자료 없음"),
                                  esc(ym), R["asof"].day)))
            else:
                cards.append(("%s 영업이익%s" % (esc(ym), tag), W(c["np"], "확인 필요"),
                              "영업이익률 %s · 올해 누적 %s" % (esc(pct(c["np"], c["revenue"])), W(y["np"], "확인 필요") if y else _na("자료 없음"))))
        else:
            cards.append(("%s 매출" % ym, W(c["revenue"]), "매출총이익 %s (매출총이익률 %s)" % (W(c["gp"]), esc(pct(c["gp"], c["revenue"])))))
            np_, foot = c["np"], ""
            if src and s4.get("dept") is not None:   # 월간 이익 = 팀 표 회사 영업이익 (사용자 2026-11-04)
                from .teamprofit import build as _tp_build
                T = _tp_build(src["table"], s4["dept"], s4["ym"], False)
                if T is not None and T["company"]["net"] is not None:
                    np_ = T["company"]["net"]   # 월간 이익 = 팀 표 회사 영업이익 (본부 영업외 비용은 영업외 비용 줄, 사용자 2026-11-04)
            cards.append(("%s 영업이익%s" % (esc(ym), tag), W(np_, "확인 필요"), "영업이익률 %s%s" % (esc(pct(np_, c["revenue"])), esc(foot))))
    else:
        why = "자료 없음" if not src else "자료 없음 (최근 %s)" % (src["latest"] or "-")
        cards.append(("%s 매출" % ym, _na(why), ""))
        cards.append(("%s 영업이익" % ym, _na(why), ""))
    na = s5["in_missing"]
    if cum:
        pass   # 주간에는 미수금을 싣지 않는다 (사용자 2026-11-03: 미수금·예정 지난 미지급은 월간에만)
    elif na:
        cards.append(("미수금 (세금계산서 발행 후)", _inv_na(s5), ""))
    else:
        ar = _na("미확인 %d건" % s5["ar_unknown_n"]) if s5["ar"] is None else W(s5["ar"]) + (
            _na(" 외 미확인 %d건" % s5["ar_unknown_n"]) if s5["ar_unknown_n"] else "")
        # '그중 입금예정일 지남'은 맨 위 칸·④와 겹쳐 뺌 (사용자 2026-11-05)
        cards.append(("미수금 (세금계산서 발행 후)", ar, ""))
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
    h = ["<div class='four%s'>" % (" c3" if len(cards) == 3 else "")]
    for lab, v, foot in cards:
        lab_html = lab if "<span" in lab else esc(lab)
        h.append("<div class='card'><div class='lab'>%s</div><div class='big'>%s</div><div class='foot'>%s</div></div>"
                 % (lab_html, v, foot))
    h.append("</div>")
    return "".join(h)


EARLY_MONTH_DAYS = 10   # 주간: 달 초 이날까지는 지난달 영업이익을 보인다 (2026-11-04 이해도 점검 U4)


def _prev_month_pl(R, src):
    """(지난달 'YYYY-MM', 회사 손익 합) 또는 None. 올해 달마다 표(by_month)에 지난달이 있을 때만 (1월은 작년이라 없음)."""
    ym = R["s4"]["ym"]
    y, m = int(ym[:4]), int(ym[5:])
    pm = "%d-%02d" % ((y, m - 1) if m > 1 else (y - 1, 12))
    for month, rows in (src or {}).get("by_month", []):
        if month == pm:
            co = [r for r in rows if r["unit"] == "회사"]
            if co and co[0]["cur"]:
                return pm, co[0]["cur"]
    return None


def _ym_text(ym):
    """'2026-10' → '10월' (첫 화면 실적 제목)."""
    m = re.match(r"^\d{4}-(\d{2})$", ym or "")
    return "%d월" % int(m.group(1)) if m else ym


def _check_items(R):
    """확인할 것 목록 (D-04: 조용히 빼지 않음). 지난 미수금·지급·세금은 _excluded_box 의 표로 옮겨 여기서는 뺀다."""
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
        names = [a["account"] for a in s1["accounts"] if a["restricted"] is None]
        items.append("사용제한금액 빈칸 %d계좌 (0으로 계산 · 담보·전용 자금이면 계좌잔액.csv에 금액 적기): %s"
                     % (s1["restr_unknown"], ", ".join(names)))
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
    for t in R.get("tax") or []:   # 세금 납부 예상: 날짜 있는 것은 위 정기 지출 표에 (사용자 2026-11-03)
        if t["due"] is None:
            amt = "금액 미확인" if t["amount"] is None else won(t["amount"])
            items.append("%s %s %s (%s) → 일정에 넣지 않음" % (t["kind"], t["period"], amt, t["state"]))
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
    return items


REGULAR_KINDS = (("부가세", ("부가",)), ("원천세", ("원천", "소득세", "지방소득")),
                 ("4대보험", ("4대보험", "사대보험", "국민연금", "건강보험", "고용보험", "산재", "근로복지", "공단")),
                 ("카드대금", ("카드",)), ("이자비용", ("이자",)), ("차입금 상환", ("차입금", "원금", "상환", "대출")),
                 ("기타 세금", ("세금", "세무서", "법인세", "지방세")))


def _pname(R, pid):
    """프로젝트 번호 → '[번호] 이름' (사용자 2026-11-05: 번호를 맨 앞에 대괄호로). 이름을 모르면 '[번호]'."""
    if not pid:
        return ""
    for P in R["s3"]["projects"]:
        if P["id"] == pid:
            name = (P["name"] or "").replace(pid, "").replace("[]", "").strip()
            return "[%s] %s" % (pid, name) if name else "[%s]" % pid
    return "[%s]" % pid


def regular_kind(e, tax_of=None):
    """일정 한 줄이 정기 지출(세금·카드·4대보험·이자·차입금 상환) 중 무엇인지. 아니면 None."""
    if tax_of and id(e) in tax_of:
        k = tax_of[id(e)]
    else:
        k = (e.get("cat") or "").replace(" (장부 계산)", "")
    text = "%s %s %s" % (k, e.get("cat") or "", e.get("desc") or "")
    for kind, words in REGULAR_KINDS:
        if k == kind or any(w in text for w in words):
            return kind
    return None


def _quarters(asof, n=3):
    y, q = asof.year, (asof.month - 1) // 3
    out = []
    for i in range(n):
        qq = q + i
        yy, qq = y + qq // 4, qq % 4
        out.append((yy, qq + 1, dt.date(yy, qq * 3 + 1, 1), dt.date(yy + (qq == 3), (qq * 3 + 3) % 12 + 1, 1)))
    return out


def _regular_table(R):
    """일정에 들어 있는 정기 지출을 항목 × 분기로 (사용자 2026-11-03)."""
    asof = R["asof"]
    tax_of = {id(t["matched"]): t["kind"] for t in (R.get("tax") or []) if t.get("matched") is not None}
    qs = _quarters(asof)
    # 분기·반기로 내는 세금만 (사용자 2026-11-03: 카드·4대보험·이자 등 월 비용은 주간 지급 목록에 그 주에 나옴)
    rows = OrderedDict((k, {"q": [0] * len(qs), "unk": [0] * len(qs), "next": None}) for k in ("부가세", "원천세"))
    for e in R["events"]:
        if e["io"] != "out" or e["date"] is None or e["date"] <= asof:
            continue
        k = regular_kind(e, tax_of)
        if k not in rows:
            continue
        r = rows[k]
        for i, (_, _, q0, q1) in enumerate(qs):
            if q0 <= e["date"] < q1:
                if e["amount"] is None:
                    r["unk"][i] += 1
                else:
                    r["q"][i] += e["amount"]
                if r["next"] is None or e["date"] < r["next"]["date"]:
                    r["next"] = e
    head = "".join("<th>%s</th>" % ("%d년 %d분기%s" % (y, q, " (남은 기간)" if i == 0 else "")) for i, (y, q, _, _) in enumerate(qs))
    h = ["<table class='pt xr taxq'><thead><tr><th>항목</th><th>다음 출금일</th><th>다음 출금액</th>%s</tr></thead><tbody>" % head]
    for k, r in rows.items():
        if r["next"] is None and not any(r["q"]) and not any(r["unk"]):
            continue
        n = r["next"]
        amt = ("금액 미확인" if n["amount"] is None else won(n["amount"])) + ("" if n["firm"] else " (예상)")
        cells = "".join("<td>%s%s</td>" % (won(v) if v else "—", (" + 미확인 %d건" % u) if u else "") for v, u in zip(r["q"], r["unk"]))
        h.append("<tr><td>%s</td><td>%s</td><td>%s</td>%s</tr>" % (esc(k), esc(d2s(n["date"])), esc(amt), cells))   # 다음 출금일은 연도까지 (사용자 2026-11-05)
    if len(h) == 1:
        h.append("<tr><td colspan='%d'>일정에 부가세·원천세 없음</td></tr>" % (3 + len(qs)))
    h.append("</tbody></table>")
    # 일정 금액이 장부 계산보다 작은 세금: 차액도 일정에 넣었다고 적는다 (2026-11-04 누락 점검 A5)
    gaps = [t for t in (R.get("tax") or []) if t.get("diff") is not None and t["diff"] < 0 and t.get("kind") in ("부가세", "원천세")]
    if gaps:
        h.append("<div class='note mgx'>%s</div>" % esc("장부 계산이 일정보다 커서 차액을 더함: " + " · ".join(
            "%s %s 일정 %s → 장부 계산 %s" % (t["kind"], t["period"], won(t["matched"]["amount"]), won(t["amount"])) for t in gaps)))
    return "".join(h)


def _excluded_box(R):
    """지난 미수금 · 지난 지급 · 일정에 든 정기 지출(분기별) + 확인할 것 (사용자 2026-11-03)."""
    asof, s5 = R["asof"], R["s5"]
    po = sorted([e for e in R["events"] if e["io"] == "out" and e["date"] is not None and e["date"] <= asof],
                key=lambda e: e["date"])
    if not s5["in_missing"] and not s5["overdue"] and not po:   # 둘 다 없으면 한 줄로 (사용자 2026-11-04: 월간 3쪽)
        return "<div class='card'><div class='note'>입금일 지난 미수금 없음 · 지급일 지난 출금 없음</div></div>"
    h = ["<div class='card'>"]
    # 1) 입금일 지난 미수금
    if s5["in_missing"]:
        h.append("<div class='wsub'>입금일 지난 미수금</div><div class='note'>계산서 자료 없음</div>")
    else:
        od = s5["overdue"]
        h.append("<div class='wsub'>입금일 지난 미수금</div>")
        if not od:
            h.append("<div class='note'>없음</div>")
        else:
            h.append("<table class='pt xr'><thead><tr><th>거래처</th><th>프로젝트</th><th>입금예정일</th><th>지난 날</th><th>미수금</th></tr></thead><tbody>")
            for v in od[:6]:
                h.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%d일</td><td class='vin'>%s</td></tr>"
                         % (esc(v["client"] or ""), esc(_pname(R, v["project"])), esc(_md(v["due"])), v["overdue_days"],
                            esc(won(v["outstanding"]))))
            if len(od) > 6:
                h.append("<tr><td colspan='5'>외 %d건 %s</td></tr>" % (len(od) - 6, esc(won(sum(v["outstanding"] for v in od[6:])))))
            h.append("</tbody></table>")
    # 2) 지급일 지난 출금 (아직 처리 안 됨)
    h.append("<div class='wsub'>지급일 지난 출금 (아직 처리 안 됨)</div>")
    if not po:
        h.append("<div class='note'>없음</div>")
    else:
        h.append("<table class='pt xr'><thead><tr><th>예정일</th><th>거래처 · 내용</th><th>프로젝트</th><th>구분</th><th>금액</th></tr></thead><tbody>")
        for e in po[:6]:
            h.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class='vout'>%s</td></tr>"
                     % (esc(_md(e["date"])), esc(e.get("desc") or ""), esc(_pname(R, e.get("project"))), esc(e.get("cat") or ""),
                        _na("금액 미확인") if e["amount"] is None else esc(won(e["amount"]))))
        if len(po) > 6:   # 나머지도 금액을 보인다 (2026-11-04 누락 점검 A3)
            rest, rest_unk = ssum(e["amount"] for e in po[6:])
            h.append("<tr><td colspan='5'>외 %d건 %s%s</td></tr>" % (len(po) - 6, esc(won(rest)),
                                                                   esc(" (금액 미확인 %d건)" % rest_unk) if rest_unk else ""))
        h.append("</tbody></table>")
    h.append("</div>")
    return "".join(h)


def _regular_box(R):
    """일정에 든 세금·카드대금·4대보험·이자·차입금 상환을 분기별로 (사용자 2026-11-03)."""
    return "<div class='card'>%s</div>" % _regular_table(R)


def _check_box(R, project_line=False):
    """위 숫자에 안 들어간 것 · 확인할 것 (D-04: 조용히 빼지 않음). 마지막 쪽 끝에.
    project_line: 대표용 월간은 프로젝트 칸이 없으므로 예산 초과·확인 건수를 한 줄로 (사용자 2026-11-03)."""
    items = _check_items(R)
    if project_line:
        chips = [_proj_chip(P) for P in R["s3"]["projects"]]
        over = sum(1 for c in chips if "c-over" in c)
        q = sum(1 for c in chips if "c-q" in c)
        items.insert(0, "프로젝트 예산 초과 %d건 · 확인 필요 %d건 (전체 %d건) — 자세한 내용은 경영관리 보고 3장" % (over, q, len(chips)))
    return "<div class='xbox'><ul>%s</ul></div>" % "".join("<li>%s</li>" % esc(t) for t in items)


from .calc import PAY_WEEKDAY  # noqa: E402  금요일 출금 (사용자 2026-11-03)


def week_outflows(R):
    """주간 대표 보고의 지급 목록 (사용자 2026-11-03: 매주 금요일 출금).

    fri  = 기준일 뒤 첫 금요일까지 나갈 것 → 금요일 출금 목록. 기준일이 금요일이면 그날 것은 이미 나간 것으로 보고(자금 표와 같은 규칙)
           다음 금요일 목록을 보인다 (2026-11-03 검토: 목록과 자금 표가 어긋나 가용자금이 커 보이던 것 고침)
    next = 그 금요일 다음 날(토)부터 다음 금요일까지 → 다음 주 지급 예정
    날짜 순, 같은 날은 금액 큰 순. 금액을 모르는 줄은 0으로 치지 않고 따로 센다."""
    from .calc import pay_friday
    asof = R["asof"]
    fri = R.get("payday") or pay_friday(asof)   # 출금일 (사용자 2026-11-04: 창에서 따로 넣은 날짜, 비우면 기준일 뒤 첫 금요일)
    end = fri + dt.timedelta(days=7)   # 다음 주 = 출금일 다음 날부터 7일 (사용자 2026-11-03)
    rows = []
    for e in R["events"]:
        if e["io"] != "out" or e["date"] is None or e["date"] > end:
            continue
        if e["date"] <= asof and e["date"] < fri:
            continue   # 예정일 지난 미처리는 주간에 싣지 않는다 (사용자 2026-11-03: 월간 '지난 미수금·지급'에만)
        rows.append(dict(e, overdue=False))
    # 남은 예산을 매주 금요일로 나눈 줄은 날짜마다 한 줄로 합친다 (사용자 2026-11-03: 목록 합계 = 자금 표 금액, 줄은 늘리지 않음)
    plan = OrderedDict()
    for e in [e for e in rows if e.get("source") == "남은 예산"]:
        plan.setdefault(e["date"], []).append(e)
    if plan:
        rows = [e for e in rows if e.get("source") != "남은 예산"]
        for day, es in plan.items():
            rows.append({"date": day, "io": "out", "amount": sum(e["amount"] for e in es), "firm": False, "overdue": False,
                         "cat": "프로젝트 남은 예산", "desc": "진행 프로젝트 %d개" % len(es), "project": "",
                         "detail": "아직 요청 전 금액을 매주 나눠 잡은 예상", "source": "남은 예산", "merged": es})
    rows.sort(key=lambda e: (e["date"], -(e["amount"] or 0)))

    def sums(rs):
        known = [e for e in rs if e["amount"] is not None]
        return {"rows": rs, "firm": sum(e["amount"] for e in known if e["firm"] and not e["overdue"]),
                "est": sum(e["amount"] for e in known if not e["firm"] and not e["overdue"]),
                "overdue": sum(e["amount"] for e in known if e["overdue"]),
                "total": sum(e["amount"] for e in known), "unknown_n": len(rs) - len(known)}
    # 금요일 출금 목록은 확정된 건만 (사용자 2026-11-04 재지적: 예상은 넣지 않는다). 예상 건은 pay_est 로 따로 두어
    # 자금 표(예상분 포함)와 맞출 수 있게 목록 아래 한 줄로만 알린다.
    # 예정일이 지났는데 장부·통장 자료가 그날 전까지만 있어 나갔는지 모르는 지급: 출금일 목록에 싣지 않고 한 줄로 알린다
    # (사용자 2026-11-05: 11/5 에 나간 급여가 11/6 출금 목록에 나옴). 자금 표에는 아직 나갈 돈으로 남는다.
    gap = [e for e in rows if e.get("gap")]
    rows = [e for e in rows if not e.get("gap")]
    upto = [e for e in rows if e["date"] <= fri]
    return {"fri": fri, "start": asof, "end": end, "rows": rows, "gap": sums(gap),
            # 금액이 확정된 건만 (사용자 2026-11-04 세 번째 지적: '금액 미확인'도 넣지 않는다). 나머지는 pay_est 로 한 줄 알림
            "pay": sums([e for e in upto if e["firm"] and e["amount"] is not None]),
            "pay_est": sums([e for e in upto if not (e["firm"] and e["amount"] is not None)]),
            "next": sums([e for e in rows if e["date"] > fri])}


def _prev_firm(R):
    """지난주 기록도 확정 건만 비교한다 (금요일 출금 목록이 확정 건만이므로)."""
    prev = R.get("week_prev")
    return dict(prev, rows=[r for r in prev["rows"] if r.get("firm") and r.get("amount") is not None]) if prev else None


def _md(d):
    return d2s(d)[5:].replace("-", "/")


def _day(d):
    """출금일 표시 '11/06(금)' (사용자 2026-11-04: 금요일 고정이 아니라 넣은 날짜)."""
    return "%s(%s)" % (_md(d), "월화수목금토일"[d.weekday()])


def _vs(c):
    if c is None:
        return ""
    k = c["kind"]
    if k == "같음":
        return "같음"
    if k == "새로 생김":
        return "새로 생김"
    if k == "날짜 바뀜":
        return "날짜 %s에서 옮김" % _md(c["prev_date"])
    if k in ("금액 확인됨", "금액 미확인"):
        return "지난주 %s" % ("미확인" if c["prev"] is None else won(c["prev"]))
    d = (c["cur"] or 0) - (c["prev"] or 0)
    return "%s%s (지난주 %s)" % ("+" if d > 0 else "", won(d), won(c["prev"]))


CAT_SHOW = {"프로젝트 남은 예산": "프로젝트 지급 예정 (미요청·예상)"}   # 대표용엔 예산 언급 없음 (사용자 2026-11-03)


# 출금 구분을 쓰임새로 (2026-11-04 이해도 점검 U3): 프로그램·자금계획서 안 이름 대신 대표가 아는 말. 순서대로 처음 맞는 것
USE_WORDS = (("대출 상환", ("차입금", "원금", "상환", "대출")), ("이자", ("이자",)),
             ("세금", ("부가세", "원천세", "법인세", "지방소득세", "세금")), ("4대보험", ("4대보험", "회사부담금", "사대보험")),
             ("급여", ("인건비", "급여", "상여")), ("카드값", ("카드",)), ("직원 복리후생", ("복리후생",)),
             ("사무실·운영비", ("임차", "관리비", "구독", "일반경비", "통신", "소모품")),
             ("행사 외주·제작비", ("프로젝트", "남은 예산")), ("거래처 대금", ("미지급", "거래처")))


def plain_use(cat):
    """구분 글자 -> 쓰임새 이름. 맞는 것이 없으면 원래 글자."""
    for name, words in USE_WORDS:
        if any(w in cat for w in words):
            return name
    return cat


def _cat_name(e, default=""):
    cat = (e.get("cat") or default).replace(" (장부 계산)", "")
    return CAT_SHOW.get(cat, cat)


def _use_name(e, default="기타"):
    """출금 목록·다음 주 요약의 구분 칸: 쓰임새 (예상 지급은 이름 끝에 '예상'을 그대로 둔다)."""
    return plain_use(_cat_name(e, default)) + (" (미요청·예상)" if (e.get("cat") or "") == "프로젝트 남은 예산" else "")


def _cat_cell(e):
    """구분 칸: 프로젝트 지급요청이면 구분 대신 상세 내역 (없으면 '상세 미입력'), 그 밖은 구분 + 상세가 있으면 아래 줄에."""
    cat = _cat_name(e)
    d = e.get("detail")
    if "지급요청" in cat:
        return esc(plain_use(cat)) + ("<small class='dt'>%s</small>" % esc(d) if d else "<small class='dt na'>상세 미입력</small>")
    return esc(_use_name(e, "")) + ("<small class='dt'>%s</small>" % esc(d) if d else "")


def _merge_this(name, only):
    """합칠 거래처 목록(only)이 비면 전부, 있으면 이름(정규화)이 서로 들어 있는 거래처만."""
    if not only:
        return True
    k = _vkey(name)
    return any(o and (o in k or k in o) for o in (_vkey(x) for x in only))


def _each_row(rows, group="건별", only=None):
    """출금 표에 보일 줄. 기본은 건마다 한 줄 (사용자 2026-11-05). 날짜 → 큰 금액 순.
    group='거래처별': 같은 날·같은 거래처 여러 건을 한 줄로 합침 (사용자 2026-11-05: 창에서 고름). 합친 줄은 금액 합계,
    프로젝트·쓰임새·상세는 서로 다른 것을 이어 적고 'n건'을 붙인다. only = 합칠 거래처 이름 목록 (비면 전부, 사용자 2026-11-05)."""
    rows = sorted(rows, key=lambda e: (e["date"], -(e["amount"] or 0)))
    if group != "거래처별":
        return rows
    out, at = [], {}
    for i, e in enumerate(rows):
        k = (e["date"], _vkey(e.get("desc") or "")) if _merge_this(e.get("desc") or "", only) else i
        if k not in at:
            at[k] = len(out)
            out.append([e])
        else:
            out[at[k]].append(e)
    merged = []
    for g in out:
        if len(g) == 1:
            merged.append(g[0])
            continue
        m = dict(g[0])
        amts = [x["amount"] for x in g]
        m["amount"] = None if any(a is None for a in amts) else sum(amts)
        m["firm"] = all(x["firm"] for x in g)
        m["projects"] = list(dict.fromkeys(x.get("project") for x in g if x.get("project")))
        dets = list(dict.fromkeys(x.get("detail") for x in g if x.get("detail")))
        m["detail"] = " · ".join(dets) if dets else None
        m["merged_n"] = len(g)
        merged.append(m)
    return sorted(merged, key=lambda e: (e["date"], -(e["amount"] or 0)))


def _proj_cell(R, e):
    pids = e.get("projects") if e.get("projects") is not None else [e.get("project")]
    names = [(_pname(R, p) if R else (p or "")) for p in pids if p]
    return "<br>".join(esc(n) for n in names)


def _out_rows_table(G, C, empty, R=None):
    """금요일 출금 표 (사용자 2026-11-03: 지난주 대비·상태 칸 없음, 프로젝트 지급요청은 구분 자리에 상세 내역).
    지난주 대비는 표 아래 한 줄로만. C는 받아 두되 표에는 쓰지 않는다."""
    h = ["<table class='pt wo'><thead><tr><th>예정일</th><th>거래처</th><th>프로젝트</th><th>내역</th>"
         "<th>금액</th></tr></thead><tbody>"]
    if not G["rows"]:
        h.append("<tr><td colspan='5'>%s</td></tr>" % empty)
    for e in _each_row(G["rows"], (R or {}).get("out_group", "건별"), (R or {}).get("out_merge_only")):
        amt = _na("금액 미확인") if e["amount"] is None else esc(won(e["amount"]))
        if not e["firm"]:
            amt += " <small class='est'>예상</small>"
        vn = esc(e.get("desc") or "") + (" <small>%d건</small>" % e["merged_n"] if e.get("merged_n") else "")
        h.append("<tr><td>%s</td><td><b class='vn'>%s</b></td><td>%s</td><td>%s</td><td class='vout'>%s</td></tr>"
                 % (esc(_md(e["date"])), vn, _proj_cell(R, e), _cat_cell(e), amt))
    h.append("</tbody></table>")
    tail = ("합계 %s" % won(G["total"])) if not G["est"] else "합계 %s · 확정 %s · 예상 %s" % (won(G["total"]), won(G["firm"]), won(G["est"]))
    if G["overdue"]:
        tail += " · 이 중 예정일 지난 미처리 %s" % won(G["overdue"])
    if G["unknown_n"]:
        tail += " · 금액 미확인 %d건" % G["unknown_n"]
    h.append("<div class='note'>%d건 · %s</div>" % (len(G["rows"]), esc(tail)))
    return "".join(h)


def _next_week_summary(G):
    """다음 주 지급 예정을 항목(구분)별로 줄여 보인다 (사용자 2026-11-03: 항목별로 축약해서 다른 표로)."""
    groups = OrderedDict()
    for e in G["rows"]:
        groups.setdefault(_use_name(e), []).append(e)
    h = ["<table class='pt wn'><thead><tr><th>구분</th><th>건수</th><th>예정일</th><th>금액</th><th>상태</th></tr></thead><tbody>"]
    if not groups:
        h.append("<tr><td colspan='5'>다음 주 지급 예정 없음</td></tr>")
    for cat, rs in sorted(groups.items(), key=lambda kv: -sum(e["amount"] or 0 for e in kv[1])):
        ds = sorted(e["date"] for e in rs)
        days = _md(ds[0]) if ds[0] == ds[-1] else "%s~%s" % (_md(ds[0]), _md(ds[-1]))
        known = [e["amount"] for e in rs if e["amount"] is not None]
        unk = len(rs) - len(known)
        amt = esc(won(sum(known))) + (" " + _na("미확인 %d건" % unk) if unk else "")
        firm = sum(1 for e in rs if e["firm"])
        state = "확정" if firm == len(rs) else ("예상" if not firm else "확정 %d · 예상 %d" % (firm, len(rs) - firm))
        h.append("<tr><td>%s</td><td>%d건</td><td>%s</td><td class='vout'>%s</td><td>%s</td></tr>"
                 % (esc(cat), len(rs), esc(days), amt, esc(state)))
    h.append("<tr class='tot'><td>합계</td><td>%d건</td><td></td><td class='vout'>%s</td><td></td></tr></tbody></table>"
             % (len(G["rows"]), esc(won(G["total"]))))
    return "".join(h)


def _week_out_table(R, mode="ceo"):
    """금요일 출금 목록(가장 눈에 띄게, 지난주 대비 포함) + 다음 주 지급 예정(항목별 요약 표) (사용자 2026-11-03).

    지난주 대비 = 지난주 기록이 이번 금요일까지 나간다고 본 금액 vs 이번 금요일 출금 금액.
    줄마다 '지난주 대비' 칸, 아래 한 줄엔 두 합계와 빠진 것·추가된 것·변동된 것만 짧게."""
    W_ = week_outflows(R)
    P = W_["pay"]
    C = None
    md = _md
    head = "<div class='fri'><span>%s 출금 합계</span><b>%s원</b><small>%d건%s</small></div>" % (
        esc(_day(W_["fri"])), esc(won(P["total"])), len(P["rows"]),
        esc(" · 금액 미확인 %d건 별도" % P["unknown_n"]) if P["unknown_n"] else "")
    h = ["<div class='card frimain'>", head, _out_rows_table(P, C, "이 날 출금 없음", R)]
    E = W_["pay_est"]
    if E["rows"]:   # 목록 밖: 예상 지급과 금액 미확인 (사용자 2026-11-04: 금요일 목록은 금액 확정 건만)
        parts = []
        n_est = len(E["rows"]) - E["unknown_n"]
        if n_est:
            parts.append("확정 안 된 예상 지급 %d건 %s원" % (n_est, won(E["total"])))
        if E["unknown_n"]:
            parts.append("금액 미확인 %d건" % E["unknown_n"])
        # 사용자 2026-11-05: 대표용엔 이 안내 없음 (경영관리용만)
        h.append(_mg(mode, "<div class='note'>%s</div>" % esc("%s은 목록에서 뺌 (③ 자금 표에는 예상분으로 포함)" % " · ".join(parts))))
    G = W_["gap"]
    if G["rows"]:
        days = sorted(set(e["gap"] for e in G["rows"]))
        if mode != "mgmt":   # 대표용 한 줄 (사용자 2026-11-05 점검: 출금 합계와 자금 표 '이번 주 나갈 돈'이 왜 다른지)
            h.append("<div class='note'>%s</div>" % esc("예정일 지난 장부 미확인 지급 %d건 %s원은 목록에서 빼고 자금 표에만 포함"
                                                      % (len(G["rows"]), won(G["total"]))))
        h.append(_mg(mode, "<div class='note'>%s</div>" % esc(
            "예정일(%s)이 지났지만 장부·통장 자료에 아직 없는 지급 %d건 %s원은 목록에서 뺌 — 이미 나간 돈이면 계좌잔액(통장 입출금내역)을 "
            "새로 넣으면 ③ 자금 표에서도 빠짐 (지금은 아직 나갈 돈으로 포함)" % (", ".join(_md(x) for x in days), len(G["rows"]), won(G["total"])))))
    h.append(_vs_last_week(R, P, mode))
    h.append("</div>")
    h += ["<div class='card wnc'><div class='wsub'>다음 주 지급 예정 (%s ~ %s) · 항목별 요약</div>"
          % (_day(W_["fri"] + dt.timedelta(days=1)), _day(W_["end"])), _next_week_summary(W_["next"]), "</div>"]
    return "".join(h)


def _vkey(name):
    """거래처 이름 맞추기: NFKC('㈜'→'(주)'), 공백·'(주)'·'주식회사' 제거 (변환의 거래처 정규화와 같은 규칙)."""
    import unicodedata
    k = re.sub(r"\s+", "", unicodedata.normalize("NFKC", name or ""))
    return k.replace("(주)", "").replace("주식회사", "")


def _vs_last_week(R, P, mode="ceo"):
    """지난주 대비 한 줄 (사용자 2026-11-05): 지난주 출금일(이번 출금일 − 7일)에 통장에서 실제로 나간 돈 vs 이번 출금 목록.
    거래처로 짝지어 빠진 것·추가된 것·변동된 것의 건수와 금액만. 건별 표는 경영관리용에만."""
    L = R.get("last_pay")
    if L is None:
        day = (R.get("payday") or R["asof"]) - dt.timedelta(days=7)
        return "<div class='wchg'>%s</div>" % esc("지난주 대비: 지난주(%s) 출금 자료 없음 — 장부가 그날까지 들어오면 비교함" % _md(day))
    prev, cur = OrderedDict(), OrderedDict()
    for r in L["rows"]:
        prev.setdefault(_vkey(r["vendor"]), [r["vendor"], 0, 0])
        prev[_vkey(r["vendor"])][1] += r["amount"]
        prev[_vkey(r["vendor"])][2] += 1
    for e in P["rows"]:
        k = _vkey(e.get("desc"))
        cur.setdefault(k, [e.get("desc") or "", 0, 0])
        cur[k][1] += e["amount"] or 0
        cur[k][2] += 1
    rows = []
    for k, (name, a, n) in prev.items():
        if k not in cur:
            rows.append(("빠진 것", name, a, None, n))
    for k, (name, b, n) in cur.items():
        if k not in prev:
            rows.append(("추가된 것", name, None, b, n))
        elif prev[k][1] != b:
            rows.append(("변동된 것", name, prev[k][1], b, n))

    def sgn(v):
        return ("+" if v > 0 else "−" if v < 0 else "") + won(abs(v))
    parts = []
    for kind in ("빠진 것", "추가된 것", "변동된 것"):
        rs = [r for r in rows if r[0] == kind]
        if rs:
            parts.append("%s %d건 %s" % (kind, sum(r[4] for r in rs), sgn(sum((r[3] or 0) - (r[2] or 0) for r in rs))))
    cur_total = sum(v[1] for v in cur.values())
    top = "지난주(%s) 출금 %s → 이번 출금 %s (%s)" % (_md(L["date"]), won(L["total"]), won(cur_total),
                                                 sgn(cur_total - L["total"]) if cur_total != L["total"] else "변동 없음")
    h = "<div class='wchg'>지난주 대비: %s%s</div>" % (esc(top), esc(" · " + " · ".join(parts)) if parts else "")
    if rows:
        body = "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            esc(k), esc(nm), "" if a is None else esc(won(a)), "" if b is None else esc(won(b)), esc(sgn((b or 0) - (a or 0))))
            for k, nm, a, b, n in rows)
        h += _mg(mode, "<div class='wsub'>지난주(%s 통장 출금) 대비 건별</div>"
                 "<table class='pt xr'><thead><tr><th>구분</th><th>거래처</th><th>지난주</th><th>이번</th><th>차이</th></tr></thead>"
                 "<tbody>%s</tbody></table>" % (esc(_md(L["date"])), body))
    return h


def _acct_year_block(R, mode="mgmt"):
    """(제목, 본문) — 계정과목별 사용 금액 연간표."""
    A = R.get("acct_year") or {"state": "자료 없음", "year": R["asof"].strftime("%Y"), "upto": R["asof"].month}
    return ("계정과목별 사용 금액 (%s년 1월~%d월)" % (A["year"], A["upto"]), _acct_year_page(R, mode))


ACCT_SMALL = 0.01   # 대표용: 연간 합계가 그 묶음 소계의 1% 미만인 계정은 '기타'로 묶음 (사용자 2026-11-04: 월간 3쪽)


def _merge_small(accounts, subtotal, up):
    """작은 계정들을 '기타 (n개)' 한 줄로. 묶을 것이 2개 미만이면 그대로."""
    if not subtotal:
        return accounts
    small = [a for a in accounts if abs(a["total"] or 0) < abs(subtotal) * ACCT_SMALL]
    if len(small) < 2:
        return accounts
    months = []
    for m in range(max(len(a["months"]) for a in small)):
        vals = [a["months"][m] if m < len(a["months"]) else 0 for a in small]
        months.append(None if any(v is None for v in vals) else sum(vals))
    other = {"name": "기타 (%d개 계정)" % len(small), "code": "", "months": months,
             "total": sum(a["total"] or 0 for a in small), "partial": any(a["partial"] for a in small)}
    return [a for a in accounts if a not in small] + [other]


def _acct_year_page(R, mode="mgmt"):
    """계정과목별 사용 금액 연간표 본문. 보고월까지 칸을 채우고 뒤 달은 비운다. 월간 보고 때마다 한 달씩 늘어난다."""
    A = R.get("acct_year") or {"state": "자료 없음", "year": R["asof"].strftime("%Y"), "upto": R["asof"].month}
    h = ["<div class='card ay'>"]
    if A["state"] != "ok":
        h.append("%s</div>" % _na("%s (계정별비용.csv — 대표보고 창의 '자료 변환'으로 만듦)" % A["state"]))
        return "".join(h)
    up = A["upto"]

    def cells(months, total, partial):
        out = []
        for m, v in enumerate(months[:up]):   # 아직 안 온 달 칸은 싣지 않는다 (사용자 2026-11-04 디자인 검토)
            out.append("<td>%s</td>" % (_na("미확인") if v is None else esc(won(v))))
        out.append("<td class='yt'>%s%s</td>" % (esc(won(total)), "*" if partial else ""))
        return "".join(out)
    head = "".join("<th>%d월</th>" % (m + 1) for m in range(up))
    h.append("<table class='pt ayt'><thead><tr><th>계정과목</th>%s<th>합계</th></tr></thead><tbody>" % head)
    merged = []
    for g in A["groups"]:
        h.append("<tr class='gh'><td colspan='%d'>%s</td></tr>" % (up + 2, esc(g["name"])))
        accts = _merge_small(g["accounts"], g["total"], up)   # 두 판 같게 묶고, 묶인 계정 목록은 경영관리용에만
        merged += [(g["name"], a) for a in g["accounts"] if a not in accts]
        for a in accts:
            h.append("<tr><td>%s</td>%s</tr>" % (esc(a["name"] or a["code"]), cells(a["months"], a["total"], a["partial"])))
        h.append("<tr class='sub'><td>%s 소계</td>%s</tr>" % (esc(g["name"]), cells(g["months"], g["total"], g["partial"])))
    h.append("<tr class='tot'><td>합계</td>%s</tr></tbody></table>" % cells(A["months"], A["total"], A["partial"]))
    note = "분개장 차변−대변 · 원가 = 프로젝트 직접비, 판매비와관리비 = 공통비, 영업외비용 = 설정 계정 · 월간 보고를 만들 때마다 그 달 칸이 채워짐"
    if A["partial"]:
        note += " · * 금액 미확인 칸 빼고 더함"
    if merged:
        note += " · 묶음 소계의 1% 미만 계정은 '기타'로 합침"
    h.append("<div class='note'>%s</div>" % esc(note))
    if merged:
        h.append(_mg(mode, "<div class='note'>%s</div>" % esc("기타에 묶인 계정: " + " · ".join(
            "%s %s" % (a["name"] or a["code"], won(a["total"])) for _, a in merged))))
    h.append("</div>")
    return "".join(h)


def _nonop_rows(N, before, after):
    """회사 영업이익 아래 결산, 위하고 결산자료 순서 (사용자 2026-11-04): + 영업외 수익, − 영업외 비용 = 세전 이익.
    어느 부서에서 났는지 이름을 붙인다. before/after = 금액 칸 앞뒤의 빈 칸 수."""
    def who(i):   # 어느 부서가 가져온 것인지 금액과 함께 (사용자 2026-11-03: 경영관리의 영업외 수익을 그 부서 실적으로 보이게)
        parts = ["%s %s" % (d, won(a if i == 1 else b)) for d, a, b in N["by_dept"] if (a if i == 1 else b)]
        return " (%s)" % " · ".join(parts) if parts else ""
    # 줄 이름은 빈 칸들을 합친 넓은 칸에 쓴다: 첫 칸이 넓어져 숫자 칸이 좁아지지 않게 (사용자 2026-11-04)
    rows = [("+ 영업외 수익%s" % who(1), N["in"], "mut"), ("− 영업외 비용%s" % who(2), N["out"], "mut")]
    if N.get("dep") is not None:   # 감가상각비 예상: 연말에 한 번에 들어가므로 작년 금액으로 먼저 뺀다 (사용자 2026-11-04)
        rows.append(("− 감가상각비 (예상%s)" % N.get("dep_note", ""), N["dep"], "mut"))
    rows.append(("세전 이익", N["pretax"], "tot"))
    if "tax" in N:   # 누적만: 법인세 예상(지방소득세 포함)을 빼 당기순이익 예상 (사용자 2026-11-04)
        rows.append(("− 법인세 예상 (지방소득세 포함)", N["tax"], "mut"))
        rows.append(("당기순이익 (예상)", N["net_income"], "tot"))
    return "".join("<tr class='%s nonop'><td colspan='%d'>%s</td><td>%s</td>%s</tr>"
                   % (c, before + 1, esc(label), W(v), "<td colspan='%d'></td>" % after if after else "") for label, v, c in rows)


def _team_table(R, part="month", mode="mgmt"):
    """월간 대표 보고: 팀별 매출 · 매출총이익 · 급여 · 판관비 · 순수익 (이번 달, 올해 누적). 사용자 2026-11-03.

    매출총이익은 WEHAGO 분개장 매출·(도)원가를 인트라넷 프로젝트의 팀으로 묶은 값(상세 4번과 같은 숫자).
    급여·판관비는 분개장 관리항목 부서명 기준(부서비용.csv). 본부 비용은 팀에 나누지 않고 본부 합계에서 뺀다 (사용자 결정).
    모르는 칸은 0이 아니라 미확인."""
    from .teamprofit import _add, allocate, build, build_ytd_alloc
    src = R["s4"]["sources"].get("WEHAGO")
    if not src or not [r for r in src["table"] if r["unit"] != "회사"]:
        return "<div class='card'>%s</div>" % _na("팀별 자료 없음 (인트라넷 프로젝트 목록이 있어야 팀으로 묶음)")
    ym, dept = R["s4"]["ym"], R["s4"].get("dept")
    basis = "heads"   # 본부·공통 비용을 기획팀에 나누는 기준: 인원 비율 (사용자 2026-11-03 제안안)
    out, last = ["<div class='card brk'>"], None   # 쪽이 넘어가면 표 사이·줄 사이에서 나뉜다 (A4 세로 2쪽)
    T = build(src["table"], dept, ym, False)
    if T is not None:
        _dep_into(R, T, False)
        last = allocate(T, basis)
        # 표 위 '10월' 작은 제목은 절 제목과 겹쳐 뺌 (사용자 2026-11-05)
        out.append("<table class='pt tm'><thead><tr><th>구분</th><th>매출</th><th>매출총이익</th><th>매출총이익률</th><th>급여</th>"
                   "<th>판관비</th><th>영업이익</th><th>인원</th><th>1인당 영업이익</th><th>급여 대비</th><th>공통비 나눈 뒤 1인당</th>"
                   "</tr></thead><tbody>")
        # 경영관리 등 매출 없는 부서는 실적 줄로 따로 두지 않는다: 영업외 수익 줄에만 부서 이름이 나온다 (사용자 2026-11-03)
        rows = [x for x in T["rows"] if x["kind"] != "other"
                and not (x["kind"] == "unlinked" and not x["revenue"] and not x["gp"])]   # 0뿐인 '팀 미지정' 줄은 뺌
        for r in rows + [T["company"]]:
            cls = {"company": " class='tot'", "hq_total": " class='hq'", "hq_self": " class='mut'", "other": " class='mut'",
                   "unlinked": " class='mut'"}.get(r["kind"], "")
            costly = r["kind"] != "unlinked"
            rev = (W(r["revenue"]), W(r["gp"]), esc(pct(r["gp"], r["revenue"]))) if r["has_rev"] else ("", "", "")
            ratio = "" if not costly or not r["has_rev"] else (
                "미확인" if r["net"] is None or not r["salary"] else "%.1f배" % (r["net"] / r["salary"]))
            h = r["heads"]
            per = "" if not costly or not r["has_rev"] else ("미확인" if h is None or r["net"] is None or not h else W(round(r["net"] / h)))
            alloc = ""
            if r["kind"] == "team":
                alloc = "미확인" if r.get("alloc") is None or not h else W(round(r["alloc"] / h))
            # 회사 전체 줄에는 '공통비 나눈 뒤 1인당'을 넣지 않는다 (1인당 순수익과 같은 숫자, 사용자 2026-11-04)
            label = esc(r["label"])
            if r["kind"] == "company":   # 인원은 기획본부(팀+본부)만 (사용자 2026-11-03: 명시)
                label += "<small>인원 = 기획본부만</small>"
            cells = [label] + list(rev) + [W(r["salary"]) if costly else "", W(r["sga"]) if costly else "", W(r["net"]),
                                                     ("미확인" if h is None else "%d명" % h) if costly else "", per, esc(ratio), alloc]
            out.append("<tr%s>%s</tr>" % (cls, "".join("<td>%s</td>" % c for c in cells)))
        out.append(_nonop_rows(T["nonop"], 5, 4))
        out.append("</tbody></table>")
    notes_html = _team_notes(R, basis, dept, last, ym)   # 표 설명은 누적 표 아래에 한 번 (이번 달 절을 1쪽에 담기 위해)
    out.append("</div>")
    if part == "month":
        return "".join(out)
    # 누적도 이번 달과 같은 모양: 위에 큰 숫자 칸, 아래 흰 카드에 기간 이름과 표 (사용자 2026-11-04)
    Y = build(src["table"], dept, ym, True)
    if Y is not None:
        _dep_into(R, Y, True)
        _tax_into(Y, ym)
        out = [_expected_strip(R, mode, Y), _ytd_strip(Y, ym), "<div class='card brk'><div class='lab'>1월~%s</div>" % esc(_ym_text(ym))]
    else:
        out = [_expected_strip(R, mode), "<div class='card brk'>"]
    if Y is not None:   # 누적은 줄인 표: 팀 · 본부 합계 · 회사 · 세전 이익. 공통비 나눈 뒤는 달마다 나눠 더한 값
        allocate(Y, basis)
        per_month = build_ytd_alloc(src.get("by_month", []), dept, ym, basis)
        out.append("<table class='pt tm'><thead><tr><th>구분</th><th>매출</th><th>매출총이익</th><th>매출총이익률</th>"
                   "<th>급여</th><th>판관비</th><th>영업이익</th><th>평균 인원</th><th>1인당 영업이익</th><th>급여 대비</th><th>공통비 나눈 뒤 1인당</th>"
                   "</tr></thead><tbody>")   # 이번 달 표와 같은 칸 (사용자 2026-11-03)
        for r in [x for x in Y["rows"] if x["kind"] in ("team", "hq_total")] + [Y["company"]]:
            cls = {"company": " class='tot'", "hq_total": " class='hq'"}.get(r["kind"], "")
            h = r["heads"]
            per = "미확인" if h is None or r["net"] is None or not h else W(round(r["net"] / h))
            alloc = ""
            if r["kind"] == "team":
                a = per_month.get(r["label"])
                alloc = "미확인" if a is None or not h else W(round(a / h))
            ratio = "미확인" if r["net"] is None or not r["salary"] else "%.1f배" % (r["net"] / r["salary"])
            cells = [esc(r["label"]) + ("<small>인원 = 기획본부만</small>" if r["kind"] == "company" else ""),
                     W(r["revenue"]), W(r["gp"]), esc(pct(r["gp"], r["revenue"])),
                     W(r["salary"]), W(r["sga"]), W(r["net"]), "미확인" if h is None else "%.1f명" % h, per, esc(ratio), alloc]
            out.append("<tr%s>%s</tr>" % (cls, "".join("<td>%s</td>" % c for c in cells)))
        out.append(_nonop_rows(Y["nonop"], 5, 4))
        out.append("</tbody></table>")
        out.append(_corptax_line(R, Y, ym) + _mg(mode, _corptax_table(R, Y, ym, mode)))   # 두 판 같은 한 줄, 표는 경영관리용에만
        out.append(_target_table(R, Y, ym))
        out.append(_budget_table(R, Y, ym, mode))
        out.append(_mg(mode, _person_table(R, src, dept, ym, basis)))   # 사람별 급여가 드러나므로 경영관리용에만 (2026-11-04)
    else:
        out.append(_na("올해 누적 자료 없음"))
    out.append("%s</div>" % _mg(mode, "<div class='note'>%s</div>%s" % (esc("1월~%s 합계. 평균 인원 = 달마다 인원의 평균 · 공통비 나눈 뒤 = 달마다 나눈 값의 합"
                                                                       % _ym_text(ym)), notes_html)))
    return "".join(out)


def _tax_into(Y, ym):
    """누적 결산 줄 끝: 세전 이익 − 법인세 예상(지방소득세 포함) = 당기순이익 예상 (사용자 2026-11-04).
    법인세 예상 표와 같은 계산 (중간예납은 미리 낸 세금이라 빼지 않음)."""
    from .corptax import LOCAL_RATE, corp_tax
    N = Y["nonop"]
    corp = corp_tax(N["pretax"], ym[:4])
    if corp is None:
        return
    N["tax"] = corp + int(corp * LOCAL_RATE)
    N["net_income"] = N["pretax"] - N["tax"]


def _dep_into(R, T, ytd):
    """감가상각비 예상을 결산 줄에 넣고 세전 이익에서 뺀다 (사용자 2026-11-04). 작년 금액을 모르면 줄을 넣지 않는다."""
    from .corptax import apply
    dep = R.get("dep") or {}
    amount = dep.get("extra" if ytd else "cur")
    if amount is None:
        return
    apply(T["nonop"], amount)
    src = "작년" if dep.get("source") == "작년 장부" else "입력"
    if ytd:
        T["nonop"]["dep_note"] = ", %s %s × %d/12" % (src, won(dep["annual"]), dep["months"]) if dep.get("mode") == "prorate" \
            else ", %s 연간 %s" % (src, won(dep["annual"]))
    else:
        T["nonop"]["dep_note"] = ", %s %s ÷ 12" % (src, won(dep["annual"]))
    if dep.get("booked"):
        T["nonop"]["dep_note"] += " − 장부 반영 %s" % won(dep["booked"])


def _corptax_table(R, Y, ym, mode="mgmt"):
    """법인세 예상 (사용자 2026-11-04): 최종 세전 이익(감가상각비 예상 뺀 값) 하나로만. 중간예납 등 선납세금을 빼고 납부할 금액,
    지방소득세. 선납세금은 변환이 분개장으로 만든 세금예상.csv 법인세 줄에서 읽고, 그 줄이 자금 일정에 들어간다."""
    from .corptax import LOCAL_RATE, brackets, corp_tax
    N = Y["nonop"]
    base = N["pretax"]
    corp = corp_tax(base, ym[:4])
    local = None if corp is None else int(corp * LOCAL_RATE)
    row = next((t for t in (R.get("tax") or []) if t.get("kind") == "법인세"), None)
    prepaid = row.get("prepaid") if row else None
    pay = None if corp is None or prepaid is None else max(corp - prepaid, 0)
    total = None if pay is None else pay + local
    due = row["due"] if row and row.get("due") else None
    h = ["<div class='wsub'>법인세 예상 (1월~%s 누적 세전 이익 기준)</div>" % esc(_ym_text(ym)),
         "<table class='pt tx'><thead><tr><th>세전 이익</th><th>법인세</th><th>− 중간예납 등 기납부</th><th>납부할 법인세</th>"
         "<th>지방소득세</th><th>납부 합계</th></tr></thead><tbody>",
         "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><b>%s</b></td></tr></tbody></table>"
         % (W(base), W(corp), W(prepaid, "미확인"), W(pay), W(local), W(total))]
    d_txt = "감가상각비 예상 뺀 세전 이익" if N.get("dep") is not None else "세전 이익 (감가상각비 모름, 창 ⑨에 연간 금액 입력)"
    rate = "·".join("%g%%" % (r * 100) for _, r in brackets(ym[:4])[:2])
    pay_txt = "자금 일정에 %s 납부 예상으로 넣음" % d2s(due) if due else "자금 일정에 넣지 못함 (자료 변환 필요)"
    h.append("<div class='note'>%s</div>" % esc(
        "과세표준 = %s · 세율 %s, 지방세 10%% · 기납부 = 장부 선납세금 · 세무조정·공제 미반영 · %s" % (d_txt, rate, pay_txt)))
    if row and row.get("base") is not None and base is not None and row["base"] != base:
        h.append(_mg(mode, "<div class='note'>%s</div>" % esc("자금 일정의 법인세는 변환 때 장부로 계산한 과세표준 %s 기준 (이 표 %s와 다름 — 기간·자료 확인)"
                                                                % (won(row["base"]), won(base)))))
    return "".join(h)


def _corptax_line(R, Y, ym):
    """대표용 법인세 예상 한 줄 (사용자 2026-11-04: 월간 3쪽). 계산은 경영관리용 표와 같다."""
    from .corptax import LOCAL_RATE, corp_tax
    corp = corp_tax(Y["nonop"]["pretax"], ym[:4])
    if corp is None:
        return ""
    local = int(corp * LOCAL_RATE)
    row = next((t for t in (R.get("tax") or []) if t.get("kind") == "법인세"), None)
    prepaid = row.get("prepaid") if row else None
    due = row["due"] if row and row.get("due") else None
    if prepaid is None:
        txt = "법인세 예상 %s + 지방소득세 %s (기납부 미확인)" % (won(corp), won(local))
    else:
        txt = "법인세 예상 %s + 지방소득세 %s − 중간예납 등 기납부 %s = 납부 %s%s" % (
            won(corp), won(local), won(prepaid), won(max(corp - prepaid, 0) + local), " (%s 예상)" % d2s(due) if due else "")
    return "<div class='note'>%s</div>" % esc(txt)


def _person_table(R, src, dept, ym, basis):
    """팀원별 순이익 몫 (사용자 2026-11-04: 1인당 순이익을 본인 급여 비율로만 나눔). 사원급여.csv 가 있어야 한다."""
    from .teamprofit import per_person
    P = per_person(src.get("by_month", []), dept, R["s4"].get("staff"), ym, basis)
    head = "<div class='wsub'>팀원별 순이익 몫 (본인 급여 비율)</div>"
    if P is None or not P["people"]:
        return head + "<div class='note'>%s</div>" % esc(
            "사원급여.csv 없음 — 대표보고 창의 '자료 변환'이 분개장 사원명으로 만듦" if R["s4"].get("staff") is None
            else "팀 사원 급여 자료 없음")
    h = [head, "<table class='pt tm pp'><thead><tr><th>팀</th><th>사원</th><th>%s 급여</th><th>%s 몫</th>"
               "<th>누적 급여</th><th>누적 몫</th><th>급여 달수</th></tr></thead><tbody>" % (esc(_ym_text(ym)), esc(_ym_text(ym)))]
    team = None
    for p in P["people"] + [None]:
        if team is not None and (p is None or p["team"] != team):
            t = P["teams"][team]
            h.append("<tr class='hq'><td>%s 합계</td><td></td><td></td><td>%s</td><td>%s</td><td></td></tr>"
                     % (esc(team), W(None if t["cur"] is None else round(t["cur"])), W(None if t["ytd"] is None else round(t["ytd"]))))
        if p is None:
            break
        team = p["team"]
        h.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%d달</td></tr>"
                 % (esc(p["team"]), esc(p["name"]), W(p["salary"], "—"), W(None if p["share"] is None else round(p["share"]), "미확인" if p["salary"] is not None else "—"),
                    W(p["salary_ytd"]), W(None if p["share_ytd"] is None else round(p["share_ytd"])), p["months"]))
    h.append("</tbody></table><div class='note'>%s</div>" % esc(
        "몫 = 그 달 팀의 공통비 나눈 뒤 순수익 × 본인 급여 ÷ 팀 급여 합, 누적은 달마다 나눈 몫의 합 (팀 몫 합계 = 팀 공통비 나눈 뒤 순수익). "
        "같은 팀이면 급여 1원당 몫이 같아 개인 성과 차이는 나타나지 않음. 본부·경영관리 인원은 팀이 아니어서 넣지 않음"))
    return "".join(h)


def _target_table(R, Y, ym):
    """팀별 연간 목표 대비 누적 실적 (사용자 2026-11-03). 목표는 창 '⑧ 팀 목표'로 넣은 팀목표.csv.

    달성률 = 누적 매출 ÷ 연간 매출 목표, 진도 기준 = 지난 달 수 ÷ 12. 달성률이 진도 기준 이상이면 '목표 이상'."""
    T = R.get("targets") or {}
    teams = [r for r in Y["rows"] if r["kind"] == "team"]
    pace = int(ym[5:7]) / 12.0
    h = ["<div class='wsub'>목표 대비 (진도 기준 %d월/12 = %.0f%%)</div>" % (int(ym[5:7]), pace * 100),
         "<table class='pt tg'><thead><tr><th>팀</th><th>연간 매출 목표</th><th>누적 매출</th><th>달성률</th>"
         "<th>누적 수익금<br><small>매출총이익</small></th><th>수익률<br><small>실제 / 목표</small></th>"
         "<th>판정</th></tr></thead><tbody>"]
    sum_t, sum_r, all_t = 0, 0, True
    sum_g, g_known = 0, True   # 팀별 달성 수익금 = 누적 매출총이익 (사용자 2026-11-05)
    for r in teams:
        t = T.get(r["label"]) or {}
        tr, rate = t.get("revenue"), t.get("rate")
        rev, gp = r["revenue"], r["gp"]
        act_rate = None if not rev or gp is None else gp * 100.0 / rev
        if gp is None:
            g_known = False
        else:
            sum_g += gp
        if tr and rev is not None:
            ach = rev / tr
            bar = "<span class='tbar'><i style='width:%d%%'></i><s style='left:%d%%'></s></span>" % (min(ach, 1) * 100, pace * 100)
            ach_txt = "%s%.1f%%" % (bar, ach * 100)
            sum_t += tr
            sum_r += rev
        else:
            ach, ach_txt, all_t = None, _na("목표 없음" if not tr else "미확인"), False
        verdict = []
        if ach is not None:
            verdict.append(("목표 이상", "c-ok") if ach >= pace else ("목표 미달", "c-over"))
        if rate is not None and act_rate is not None:
            verdict.append(("수익률 달성", "c-ok") if act_rate >= rate else ("수익률 미달", "c-over"))
        chips = "".join("<span class='chip %s'>%s</span>" % (c, esc(v)) for v, c in verdict) or "—"
        h.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s / %s</td><td>%s</td></tr>"
                 % (esc(r["label"]), W(tr, "목표 없음"), W(rev), ach_txt, W(gp),
                    "—" if act_rate is None else "%.1f%%" % act_rate, "—" if rate is None else "%g%%" % rate, chips))
    if teams and all_t and sum_t:
        h.append("<tr class='tot'><td>팀 합계</td><td>%s</td><td>%s</td><td>%.1f%%</td><td>%s</td><td>%s</td><td></td></tr>"
                 % (W(sum_t), W(sum_r), sum_r * 100.0 / sum_t, W(sum_g if g_known else None),
                    "%.1f%%" % (sum_g * 100.0 / sum_r) if g_known and sum_r else ""))
    h.append("</tbody></table>")
    if not T:
        h.append("<div class='note'>팀 목표 없음 — 대표보고 창 '⑧ 팀 목표'에 연간 매출 목표와 목표 수익률을 넣으면 보입니다</div>")
    return "".join(h)


def _budget_table(R, Y, ym, mode="ceo"):
    """예산 대비 (사용자 2026-11-10: 내년 예산 확정 후 월간 보고에). 확정 예산이 없으면 아무것도 넣지 않는다.
    팀 줄 = 이번 달·누적 매출 대 예산. 경영관리용에만 누적 손익(매출총이익·급여·판관비·영업이익) 대 예산."""
    B = R.get("budget_cmp")
    if not B:
        return ""
    m = B["month"]

    def diff(a, b):
        if a is None or b is None:
            return "—"
        return "<span%s>%s%s</span>" % (" style='color:#c00000'" if a < b else "", "+" if a >= b else "−", "{:,}".format(abs(a - b)))

    def rate(a, b):
        if a is None or not b:
            return "—"
        return "<span%s>%.1f%%</span>" % (" style='color:#c00000'" if a < b else "", a * 100.0 / b)
    h = ["<div class='wsub'>예산 대비 (%s 확정 예산)</div>" % esc(B["date"] or ""),
         "<table class='pt tg'><thead><tr><th>팀</th><th>%d월 매출</th><th>%d월 예산</th><th>차이</th><th>1~%d월 누적</th><th>누적 예산</th>"
         "<th>예산 대비</th><th>누적 매출총이익<br><small>실적 / 예산</small></th></tr></thead><tbody>" % (m, m, m)]
    for r in B["rows"] + [dict(B["tot"], team="팀 합계")]:
        h.append("<tr%s><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s / %s</td></tr>"
                 % (" class='tot'" if r["team"] == "팀 합계" else "", esc(r["team"]), W(r["cur"]), W(r["cur_b"]), diff(r["cur"], r["cur_b"]),
                    W(r["ytd"]), W(r["ytd_b"]), rate(r["ytd"], r["ytd_b"]), W(r["gp"]), W(r["gp_b"])))
    h.append("</tbody></table>")
    if mode != "ceo":
        from .budget import COMPANY
        conf = (R.get("budget_conf_rows") or {})
        c = Y["company"]
        def cb(k):
            return sum((conf.get((mm, COMPANY), {}).get(k) or 0) for mm in range(1, m + 1)) if conf else None
        sal_b, sga_b = cb("급여"), cb("판관비")
        gp_b = B["tot"]["gp_b"]
        op_b = None if None in (sal_b, sga_b) else gp_b - sal_b - sga_b
        op_a = c.get("net")
        h.append("<table class='pt tg'><thead><tr><th>1~%d월 누적 (회사)</th><th>실적</th><th>예산</th><th>차이</th><th>예산 대비</th></tr></thead><tbody>" % m)
        for nm, a, b in (("매출", c.get("revenue"), B["tot"]["ytd_b"]), ("매출총이익", c.get("gp"), gp_b), ("급여", c.get("salary"), sal_b),
                         ("판관비 (급여 뺀 것)", c.get("sga"), sga_b), ("영업이익 (감가상각비 예상 빼기 전)", op_a, op_b)):
            h.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (nm, W(a), W(b), "—" if a is None or b is None else ("+" if a >= b else "−") + "{:,}".format(abs(a - b)),
                                                                                    "—" if a is None or not b else "%.1f%%" % (a * 100.0 / b)))
        h.append("</tbody></table><div class='note'>%s</div>" % esc("급여·판관비는 예산보다 많으면 나쁜 쪽. 영업이익은 위 누적 표와 같은 값(감가상각비 예상은 결산 줄에서 따로 뺌)"))
    return "".join(h)


def _ytd_strip(Y, ym):
    """올해 누적 큰 숫자 칸: 매출 · 영업이익 · 세전 이익 · 당기순이익(예상). 이번 달 실적 칸과 같은 모양 (사용자 2026-11-04: 보기 편하게)."""
    c, N = Y["company"], Y["nonop"]
    per = "1월~%s" % _ym_text(ym)
    nn = (N["in"] or 0) - (N["out"] or 0)
    parts = ["영업외 손익 %s%s" % ("+" if nn >= 0 else "", won(nn))]
    if N.get("dep") is not None:
        parts.append("감가상각비 −%s" % won(N["dep"]))
    cards = [("%s 매출" % per, W(c["revenue"]), "매출총이익 %s (매출총이익률 %s)" % (W(c["gp"]), esc(pct(c["gp"], c["revenue"])))),
             ("%s 영업이익" % per, W(c["net"], "확인 필요"), "영업이익률 %s" % esc(pct(c["net"], c["revenue"]))),
             ("%s 세전 이익" % per, W(N["pretax"], "확인 필요"), esc(" · ".join(parts)))]
    if "net_income" in N:   # 당기순이익 예상도 큰 숫자로 (사용자 2026-11-04)
        cards.append(("%s 당기순이익 (예상)" % per, W(N["net_income"]), esc("법인세 예상 −%s" % won(N["tax"]))))
    return "<div class='four%s'>%s</div>" % ("" if len(cards) == 4 else " c3", "".join(
        "<div class='card'><div class='lab'>%s</div><div class='big'>%s</div><div class='foot'>%s</div></div>"
        % (esc(a), b, f) for a, b, f in cards))


def _ytd_revenue(R):
    src = R["s4"]["sources"].get("WEHAGO")
    co = [r for r in src["table"] if r["unit"] == "회사"] if src else []
    y = co[0]["ytd"] if co else None
    return y.get("revenue") if y else None


def _expected_strip(R, mode="ceo", Y=None):
    """앞으로 들어올 매출 한 줄 칸 (사용자 2026-11-04: ⑥ 맨 위, 표가 아니라 큰 숫자 칸).

    앞으로 들어올 매출 = 누적 매출 외에 더 들어올 매출 = 사전견적 − 발행 계산서(공급가액, 프로젝트마다 0 밑은 0):
    행사 끝남(⑤ '행사 후 세금계산서 미발행'과 같은 수) + 올해 남은 행사. 다음 해 이후 행사는 내년 보고로.
    누적 매출 + 앞으로 들어올 매출 = 올해 매출 예상. 팀별 금액은 E['by_team'] (경영관리용 근거용)."""
    E = R["s5"].get("expected")
    y = R["asof"].year
    head = ("<div class='exp-h'><b>앞으로 들어올 매출</b><span>인트라넷 예상 매출(사전견적) 기준 · %d년 이후 행사 제외</span></div>"
            % (y + 1))
    if not E or E["missing"]:
        return "<div class='card exprow'>%s<div class='exp-c'>%s</div></div>" % (head, esc("계산서 자료가 없어 판단 불가"))
    if not E["est_n"]:
        return "<div class='card exprow'>%s<div class='exp-c'>%s</div></div>" % (head, esc("인트라넷 예상 매출(사전견적) 자료 없음"))
    ymt = _ym_text(R["s4"]["ym"])
    rev = _ytd_revenue(R)
    add = E["past"] + E["this_year"]
    total = None if rev is None else rev + add

    def cell(lab, val, sub="", cls=""):
        return ("<div class='exp-c%s'><div class='lab'>%s</div><div class='big'>%s%s</div></div>"
                % (cls, esc(lab), val, " <small>%s</small>" % esc(sub) if sub else ""))
    top = [cell("1월~%s 누적 매출" % ymt, W(rev, "확인 필요")),
           cell("+ 앞으로 들어올 매출", W(add), "%d건" % (E["past_n"] + E["this_year_n"])),
           cell("= %d년 매출 예상" % y, W(total, "확인 필요"), cls=" tot")]   # 결론 숫자에 밑줄 하나 (사용자 2026-11-05)
    bot = "앞으로 들어올 매출 = 사전견적 − 이미 발행한 계산서 · 행사 끝남(미발행) %s (%d건) + %d년 남은 행사 %s (%d건)" % (
        won(E["past"]), E["past_n"], y, won(E["this_year"]), E["this_year_n"])
    if E.get("quoted_n"):
        bot += " · 대표이사 승인 끝난 %d건은 사전견적 대신 확정 견적금액" % E["quoted_n"]
    # 풀이 줄(계산식·뺀 것)은 경영관리용에만 (사용자 2026-11-05: 월간 대표 보고 안내 최소)
    h = "<div class='card exprow'>%s%s" % (head, "".join(top)) + _mg(mode, "<div class='exp-b'>%s</div>" % esc(bot))
    left = []
    if E["no_date_n"]:
        left.append("행사일 없는 %d건" % E["no_date_n"])
    if E["unknown_n"]:
        left.append("발행금액 미확인 %d건" % E["unknown_n"])
    if E["later_n"]:
        left.append("%d년 이후 행사 %d건은 내년 보고에" % (y + 1, E["later_n"]))
    if left:
        h += _mg(mode, "<div class='exp-b'>%s</div>" % esc("금액에서 뺀 것: " + " · ".join(left)))
    h += "</div>"
    return h + _mg(mode, "<div class='note'>%s</div>" % esc(
        "사전견적·발행 모두 공급가액, 프로젝트마다 0 밑은 0. 누적 매출은 회사 전체(프로젝트에 안 붙은 매출 포함)"))


def _month_series(R):
    """1월~보고 달 (연월, 매출, 매입, 영업이익).

    매출·매입 = 증빙(세금계산서 등) 작성일자 기준 공급가액 (증빙월별.csv, 사용자 2026-11-04). 그 파일이 없으면 매출은 손익 기준,
    매입은 None. 영업이익 = ⑤ 이번 달 칸과 같은 기준 (부서 비용이 있으면 그 달 팀 표 회사 영업이익, 공통비까지 뺀 값)."""
    s4 = R["s4"]
    src = s4["sources"].get("WEHAGO") or {}
    year = s4["ym"][:4]
    ev = R.get("evid_month")
    pl = {}
    from .teamprofit import build as _tp_build
    for m, table in src.get("by_month", []):
        if m[:4] != year or m > s4["ym"]:
            continue
        co = [r for r in table if r["unit"] == "회사"]
        if not co or not co[0]["cur"]:
            continue
        c = co[0]["cur"]
        np_ = c["np"]
        if s4.get("dept") is not None:
            T = _tp_build(table, s4["dept"], m, False)
            if T is not None and T["company"]["net"] is not None:
                np_ = T["company"]["net"]
        pl[m] = (c["revenue"], np_)
    months = set(pl)
    if ev is not None:
        months |= set(m for m in ev if m[:4] == year and m <= s4["ym"])
    out = []
    for m in sorted(months):
        rev, np_ = pl.get(m, (None, None))
        if ev is not None:
            sale, buy = ev.get(m, (0, 0))
        else:
            sale, buy = rev, None
        out.append((m, sale, buy, np_))
    return out


def _month_chart(R, H=250):
    """월별 매출·매입(막대 두 개)·영업이익(선) 흐름 (사용자 2026-11-04: 2쪽 빈 곳에, 매입 추가).
    매출·매입 = 증빙 작성일자 기준 공급가액, 영업이익 = 월별 실적 기준. 같은 원 단위라 축 하나."""
    ser = _month_series(R)
    if len(ser) < 2:
        return ""
    ev_on = R.get("evid_month") is not None
    # 달마다 숫자 줄 (사용자 2026-11-05: "차트에 숫자가 안 보인다") — 막대 위에 원 단위 숫자를 다 넣으면 겹쳐서, 그림 밑에 표처럼 줄로 둔다
    rows = [("매출", 1)] + ([("매입", 2)] if ev_on else []) + [("영업이익", 3)]
    RH = 18
    Wd, pl, pr, pt, pb = 900, 74, 10, 22, 30 + RH * len(rows) + 6
    H = H + RH * len(rows) + 6
    vals = [0] + [v for _, r, k, p in ser for v in (r, k, p) if v is not None]
    step = _nice_step((max(vals) - min(vals)) / 4 or 1)
    hi = step * math.ceil(max(vals) / step)
    lo = step * math.floor(min(vals) / step)
    if hi == lo:
        hi = lo + step
    span = hi - lo
    n = len(ser)
    gw = (Wd - pl - pr) / n

    def y(v):
        return pt + (hi - v) * (H - pt - pb) / span
    out = ['<svg viewBox="0 0 %d %d" width="100%%" role="img" aria-label="월별 매출·매입과 영업이익">' % (Wd, H)]
    for k in range(int(round(span / step)) + 1):
        v = lo + step * k
        out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#e6e9ef"/>' % (pl, Wd - pr, y(v), y(v)))
        out.append('<text x="%d" y="%.1f" font-size="14" text-anchor="end" fill="#5b6475">%s</text>' % (pl - 5, y(v) + 4, _axis(v)))
    out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#1d2433"/>' % (pl, Wd - pr, y(0), y(0)))
    bw = gw * 0.3
    pts = []

    def bar(x0, v, color, what, m):
        if v is None or v <= 0:
            return
        top = y(v)
        r = min(4, (y(0) - top) / 2)
        out.append('<path d="M%.1f %.1f V%.1f Q%.1f %.1f %.1f %.1f H%.1f Q%.1f %.1f %.1f %.1f V%.1f Z" fill="%s">'
                   '<title>%s %s %s</title></path>'
                   % (x0, y(0), top + r, x0, top, x0 + r, top, x0 + bw - r, x0 + bw, top, x0 + bw, top + r, y(0),
                      color, esc(_ym_text(m)), what, esc(won(v))))
    for i, (m, rev, cost, np_) in enumerate(ser):
        cx = pl + i * gw + gw / 2
        bar(cx - bw - 1, rev, "#6b98dc", "매출", m)       # 막대 사이 2px
        bar(cx + 1, cost, "#d8964a", "매입", m)
        base = y(lo) + 20
        out.append('<text x="%.1f" y="%.1f" font-size="14" text-anchor="middle" fill="#5b6475">%s</text>'
                   % (cx, base, esc(_ym_text(m))))
        rec = (m, rev, cost, np_)
        for j, (_, k) in enumerate(rows):
            v = rec[k]
            out.append('<text x="%.1f" y="%.1f" font-size="12.5" text-anchor="middle" fill="%s">%s</text>'
                       % (cx, base + 8 + RH * (j + 1), "#a8432f" if (v or 0) < 0 else "#1d2433", esc(won(v, "-")) if v is not None else "-"))
        if np_ is not None:
            pts.append((cx, y(np_), m, np_))
    if pts:
        out.append('<polyline points="%s" fill="none" stroke="#1f4e8c" stroke-width="2"/>'
                   % " ".join("%.1f,%.1f" % (x, yy) for x, yy, _, _ in pts))
        for x, yy, m, v in pts:
            out.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s" stroke="#fff" stroke-width="2"><title>%s 영업이익 %s</title></circle>'
                       % (x, yy, "#b5523b" if v < 0 else "#1f4e8c", esc(_ym_text(m)), esc(won(v))))
    base = y(lo) + 20
    out.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#e6e9ef"/>' % (8, Wd - pr, base + 7, base + 7))
    for j, (lab, _) in enumerate(rows):
        out.append('<text x="%d" y="%.1f" font-size="12.5" fill="#5b6475" font-weight="600">%s</text>' % (8, base + 8 + RH * (j + 1), lab))
    out.append("</svg>")
    ev = R.get("evid_month") is not None
    leg = ("<div class='legend'><span><i style='background:#6b98dc'></i>%s</span>%s"
           "<span><i style='background:#1f4e8c;height:2px;margin-bottom:4px'></i>영업이익 (빨간 점 = 손실 달)</span></div>"
           % ("매출" if ev else "매출 (손익 기준)", "<span><i style='background:#d8964a'></i>매입</span>" if ev else ""))
    foot = ("매출·매입 = 세금계산서 등 증빙 작성일자 기준 공급가액 · 영업이익 = 월별 실적과 같은 기준 (공통비까지 뺀 값)" if ev else
            "증빙월별.csv 없음: 매입 막대 없이 손익 기준 매출만 (대표보고 창의 '자료 변환'이 분개장으로 만듦)")
    return ("<div class='card mchart'><div class='lab'>월별 매출·매입·영업이익 흐름 (%s~%s)</div>%s%s<div class='note%s'>%s</div></div>"
            % (esc(_ym_text(ser[0][0])), esc(_ym_text(ser[-1][0])), "".join(out), leg, " mgx", esc(foot)))   # 풀이·자료 없음 안내는 경영관리용에만 (사용자 2026-11-05)


def _team_notes(R, basis, dept, last, ym):
    notes = ["순수익 = 매출총이익 − 그 팀 급여·판관비 (분개장 부서명 기준). 본부 비용은 본부 합계에서, 다른 부서 비용은 회사 전체에서 뺌",
             "공통비 나눈 뒤 = 본부·경영관리 등 비용을 팀 %s 비율로 나눠 뺀 값 (팀 합계 = 회사 영업이익)" % ("인원" if basis == "heads" else "매출"),
             "급여 대비 = 순수익 ÷ 급여", "영업이익 줄의 인원 = 기획본부(팀+본부) 인원만, 경영관리 등은 빼고 비용만 회사 전체에서 뺌"]
    if dept is None:
        notes.append("급여·판관비 미확인: %s (대표보고 창의 '자료 변환'이 분개장 부서명으로 만듦)" % (
            "부서비용.csv " + R["s4"].get("dept_problem") if R["s4"].get("dept_problem") else "부서비용.csv 없음"))
    elif last and not last["dept_ok"]:
        notes.append("급여·판관비 미확인: 부서비용.csv에 %s 자료가 없음" % _ym_text(ym))
    for hq, v in (last or {}).get("hq_nonop", []):
        notes.append("%s 영업외 비용(이자 등) %s은 %s 판관비에 넣어 영업이익에서 뺌 (결산 영업외 비용 줄에는 넣지 않음)" % (hq, won(v), hq))
    if last and last["check"]:
        got, want = last["check"]
        notes.append("부서별 급여+판관비 %s %s 장부 공통비 %s" % (won(got), "=" if got == want else "≠ (확인 필요)", won(want)))
    return "<div class='note'>%s</div>" % esc(" · ".join(notes))


def month_flow(R):
    """월간 보고 자금 흐름 그림 (사용자 2026-11-03: 그 달 1일부터 시작).

    첫 막대 = 보고 달: 1일~기준일 실제 입출금(통장) + 기준일 다음 날~말일 예정. 그다음은 달마다 예정 (s2 일정 그대로).
    선의 시작 = 1일 가용액 (오늘 가용액 − 이번 달 입금 + 이번 달 출금). 계산 일정(s2)은 바꾸지 않는다."""
    s1, s2, asof = R["s1"], R["s2"], R["asof"]
    first = asof.replace(day=1)
    months = []
    m = first
    while m <= s2["horizon"]:
        months.append(m)
        m = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    bs = [{"label": "%d년 %d월" % (m.year, m.month), "type": "month", "ym": (m.year, m.month),
           "in_firm": 0, "in_est": 0, "out_firm": 0, "out_est": 0} for m in months]
    bs[0]["in_firm"], bs[0]["out_firm"] = s1["in"], s1["out"]
    bs[0]["label"] += "(실적)" if asof.month != (asof + dt.timedelta(days=1)).month else "(실적+예정)"
    idx = {b["ym"]: b for b in bs}
    for ev in s2["dated"]:
        b = idx.get((ev["date"].year, ev["date"].month))
        if b is not None:
            b[("in_" if ev["io"] == "in" else "out_") + ("firm" if ev["firm"] else "est")] += ev["amount"]
    # 월초 가용액 = 지금 가용액 − 이번 달 입금 + 출금. 잔액을 모르는(가용액에 안 든) 계좌의 이번 달 입출금은 되돌리지 않는다 (2026-11-03 검토)
    known = set(a["account"] for a in s1["accounts"] if a["balance"] is not None)
    ext = [t for t in s1.get("txns", []) if t["account"] in known and t["cat"] != "계좌간이체"]
    k_in = sum(t["amount"] for t in ext if t["io"] == "입금")
    k_out = sum(t["amount"] for t in ext if t["io"] == "출금")
    start = None if s2["start"] is None else s2["start"] - k_in + k_out
    bf = ba = start
    for b in bs:
        if start is None:
            b["bal_firm"] = b["bal_all"] = None
            continue
        bf += b["in_firm"] - b["out_firm"]
        ba += b["in_firm"] + b["in_est"] - b["out_firm"] - b["out_est"]
        b["bal_firm"], b["bal_all"] = bf, ba
    return {"buckets": bs, "start": start, "out_missing": s2["out_missing"], "first": first,
            "min_cash": s2.get("min_cash")}


def _over_line(R):
    """프로젝트 예산 초과만 한 줄 (사용자 2026-11-03: 집행 예정·잔여 예산은 이미 지급 예정 일정에 들어가 있어 금액은 겹침,
    대표가 따로 알아야 할 것은 '어느 프로젝트가 예산을 넘었나'뿐). 막대·상세는 경영관리 보고 3장."""
    ps = R["s3"]["projects"]
    over = sorted([P for P in ps if P["budget"] is not None and not P["unknown_cost"] and P["remain"] is not None and P["remain"] < 0],
                  key=lambda P: P["remain"])
    q = sum(1 for P in ps if P["budget"] is not None and P["unknown_cost"])
    if over:
        body = "<b class='neg'>예산 초과 %d건</b> · %s" % (len(over), " · ".join(
            "%s <b class='neg'>%s 초과</b>" % (esc(_short(P["name"], 20)), esc(won(-P["remain"]))) for P in over))
    else:
        body = "<b>예산 초과 없음</b>"
    if q:
        body += " · 원가 확인 필요 %d건" % q
    return ("<div class='overl'>%s <small>(프로젝트 전체 %d건 · 집행 예정액·잔여 예산은 자금 일정에 이미 포함)</small></div>"
            % (body, len(ps)))


def _mg(mode, body):
    """경영관리용에만 싣는 근거 묶음 (사용자 2026-11-03: 대표용엔 꼭 알아야 할 것만, 근거는 경영관리가 요청 때 제출).
    두 판의 숫자 비교(테스트)는 이 묶음을 뺀다."""
    return "<div class='mgonly'>%s</div><!-- /mgonly -->" % body if mode == "mgmt" else ""


def _decide_lines(R):
    """경영관리용 맨 위 '이번 주(달) 판단할 것' 3줄 (사용자 2026-11-03: 대표용엔 넣지 않고 경영관리용에만)."""
    lines = []
    if R["kind"] == "weekly":
        P = week_outflows(R)["pay"]
        lines.append("%s 출금 <b>%s원</b> 승인 · %d건%s" % (
            esc(_day(week_outflows(R)["fri"])), esc(won(P["total"])), len(P["rows"]),
            esc(", 금액 미확인 %d건 확인 후" % P["unknown_n"]) if P["unknown_n"] else ""))
    else:
        nxt = [e for e in R["events"] if e["io"] == "out" and e["amount"] is not None and e["date"]
               and (e["date"].year, e["date"].month) == ((R["asof"].year + R["asof"].month // 12), R["asof"].month % 12 + 1)]
        lines.append("다음 달 지급 예정 <b>%s원</b> · %d건 (금액 큰 것 %s)" % (
            esc(won(sum(e["amount"] for e in nxt))), len(nxt),
            esc(", ".join("%s %s" % (e["desc"], won(e["amount"])) for e in sorted(nxt, key=lambda e: -e["amount"])[:2])) or "없음"))
    per = [p for p in R["s2"]["periods"] if p["firm"].get("avail") is not None]
    if per:
        lo = min(per, key=lambda p: p["firm"]["avail"])
        lines.append("%s 안 가용자금(확정분)이 가장 낮을 때 <b>%s원</b> (%s) · 최소 보유현금 %s원 남김" % (
            esc(per[-1]["label"]), esc(won(lo["firm"]["avail"])), esc(_md(lo["firm"]["low_date"])) if lo["firm"].get("low_date") else "",
            esc(won(R["settings_num"].get("위험_최소보유현금") or 0))))
    else:
        lines.append("가용자금 판단 불가 (잔액 또는 지급 자료 확인 필요)")
    top = sorted(R["risks"], key=lambda r: r["level"] != "높음")[:1]
    lines.append(("가장 큰 위험: %s" % esc(top[0]["fact"])) if top else "높음 위험 없음")
    return ("<div class='dec'><div class='dech'>%s 판단할 것 (경영관리용)</div><ol>%s</ol></div>"
            % ("이번 주" if R["kind"] == "weekly" else "이번 달", "".join("<li>%s</li>" % x for x in lines)))


def _fresh_warn(R):
    """자료 신선도 경고 (사용자 2026-11-03 추천 M4): 자료 기준일이 기준일보다 '위험_자료경과일' 이상 오래되면 맨 위에."""
    days = int(R["settings_num"].get("위험_자료경과일") or 7)
    old = [a for a in R["s7"]["asof"] if a.get("date") and a.get("age") is not None and a["age"] >= days]
    if not old:
        return ""
    return "<div class='warnbar'>오래된 자료 %d건: %s — 빠진 지급·입금이 있을 수 있음 (기준 %d일)</div>" % (
        len(old), esc(" · ".join("%s %s (기준일보다 %d일 전)" % (a["name"], d2s(a["date"]), a["age"]) for a in old)), days)


def _ev_block(num, title, body):
    return "<div class='evb' id='ev-%s'><div class='evh'>근거 %s · %s</div>%s</div><!-- /ev-%s -->" % (num, num, esc(title), body, num)


def _ev_rows(rows, R):
    h = ["<table class='pt evt'><thead><tr><th>예정일</th><th>거래처</th><th>프로젝트</th><th>구분</th><th>원자료</th><th>근거</th><th>상세 출처</th><th>금액</th></tr></thead><tbody>"]
    if not rows:
        h.append("<tr><td colspan='8'>없음</td></tr>")
    for e in rows:
        h.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            esc(_md(e["date"])), esc(e.get("desc") or ""), esc(_pname(R, e.get("project"))), esc(_cat_name(e)),
            esc(e.get("source") or ""), esc(e.get("basis") or ""), esc(e.get("detail_source") or ""),
            _na("금액 미확인") if e["amount"] is None else esc(won(e["amount"])) + ("" if e["firm"] else " (예상)")))
    h.append("</tbody></table>")
    return "".join(h)


def _ev_change_table(R):
    """근거 1-2 지난주 대비 · 건별: 첫 화면 한 줄과 같은 기준 (지난 출금일 통장 출금 vs 이번 출금 목록, 사용자 2026-11-05)."""
    h = _vs_last_week(R, week_outflows(R)["pay"], "mgmt")
    a, b = "<div class='mgonly'>", "</div><!-- /mgonly -->"
    if a in h and b in h:   # 건별 표만 (근거 묶음은 이미 경영관리용 안이라 한 번 더 감싸지 않음)
        return h[h.index(a) + len(a):h.rindex(b)]
    return "<div class='note'>지난주 대비 건별 차이 없음 (또는 지난주 출금 자료 없음)</div>"


def _ev_targets(R):
    T = R.get("targets") or {}
    h = ["<div class='note'>입력/팀목표.csv (창 ⑧). 달성률 = 누적 매출 ÷ 연간 매출 목표, 진도 = 보고 달 ÷ 12. 수익률 = 누적 매출총이익 ÷ 누적 매출.</div>",
         "<table class='pt evt'><thead><tr><th>팀</th><th>연간 매출 목표</th><th>목표 수익률</th></tr></thead><tbody>"]
    for team, t in sorted(T.items()):
        h.append("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (esc(team), W(t.get("revenue")),
                                                               esc("" if t.get("rate") is None else "%g%%" % t["rate"])))
    if not T:
        h.append("<tr><td colspan='3'>입력된 목표 없음</td></tr>")
    h.append("</tbody></table>")
    return "".join(h)


def _evidence(R, base_no):
    """경영관리용 근거자료 묶음: 번호표 + 첫 화면에 따로 만든 근거 (상세 장에 있는 근거는 그 장을 가리킨다)."""
    titles = {"s1": "상세 1장", "s2": "상세 2장", "s3": "상세 3장", "s4": "상세 4장", "s5": "상세 5장", "s6": "상세 6장",
              "s7": "상세 7장", "s8": "상세 8장"}
    idx = evidence_index(R)
    rows = "".join("<tr><td><b>근거 %s</b></td><td>%s</td><td>%s</td></tr>" % (
        esc(n), esc(t), "<a href='#ev-%s'>아래</a>" % esc(n) if w == "block" else "<a href='#%s'>%s</a>" % (w, titles.get(w, w)))
        for n, t, w in idx)
    h = ["<div class='sec'>%s<div class='note'>대표가 번호로 요청하면 이 번호의 근거를 제출합니다. "
         "창 ②의 '근거자료 PDF'에 번호를 넣으면 그 근거만 PDF로 만듭니다.</div>"
         "<table class='pt evt'><thead><tr><th>번호</th><th>대표용 항목</th><th>근거 위치</th></tr></thead><tbody>%s</tbody></table></div>"
         % (_q(base_no, "근거자료 (대표 요청 때 제출)"), rows)]
    blocks = []
    if R["kind"] == "weekly":
        W_ = week_outflows(R)
        blocks += [_ev_block("1-1", "%s 출금 목록 · 건별 원자료" % _day(W_["fri"]), _ev_rows(W_["pay"]["rows"], R)),
                   _ev_block("1-2", "지난주 대비 · 건별", _ev_change_table(R)),
                   _ev_block("1-3", "다음 주 지급 예정 · 건별", _ev_rows(W_["next"]["rows"], R))]
    else:
        blocks.append(_ev_block("6-1", "누적 실적·팀 목표 (입력값과 계산)", _ev_targets(R)))
    h.append("<div class='sec evs'>%s</div>" % "".join(blocks))
    return "".join(h)


def _first_screen(R, mode, per):
    """대표 보고 본문 (사용자 2026-11-03: 대표가 꼭 알아야 할 것만, 주간 2쪽 · 월간 3쪽, 빈 곳 없이).

    주간  ① 금요일 출금 목록(합계·지난주 대비·상세 내역) + 다음 주 요약 ② 이번 주 실적 ③ 자금. 미수금·예정 지난 미지급은 월간에만
    월간  ① 이번 달 자금 흐름 ② 앞으로 자금(월별 그림은 그 달 1일부터) ③ 부가세·원천세 ④ 지난 미수금·지급 ⑤ 이번 달 실적·팀 ⑥ 누적 실적·목표 대비 ⑦ 계정과목별 연간표
    대표용엔 예산 언급 없음, 숫자 옆 근거 번호만 (사용자 2026-11-03). 경영관리용엔 근거 묶음(mgonly): 판단할 것 3줄, 자료 신선도 경고,
    예산 초과 줄, 근거 번호별 근거자료, 프로젝트별 예산·집행, 확인할 것."""
    s1, s2 = R["s1"], R["s2"]
    monthly = R["kind"] == "monthly"
    ymt = _ym_text(R["s4"]["ym"])
    if monthly:
        mf = month_flow(R)
        flow = (esc("월별 자금 흐름 (%d월 1일 쓸 수 있는 돈 %s에서 시작 · %d월은 통장 실적%s%s)"
                    % (mf["first"].month, _won_or_unknown(mf["start"]), mf["first"].month,
                       "" if "(실적)" in mf["buckets"][0]["label"] else "+남은 예정", _bal_note(s1))), chart(mf, H=310, simple=True))
    else:
        flow = (esc("기간별 자금 흐름 (시작: 오늘 쓸 수 있는 돈 %s%s)" % (_won_or_unknown(s2["start"]), _bal_note(s1))), chart(s2, H=270, simple=True))
    funds = [("향후 자금 전망" if monthly else "자금 현황", _avail_table(R, mode) + "<div class='card' style='margin-top:8px'><div class='lab'>%s</div>%s</div>" % flow)]
    past = [("지난 미수금 · 지급 (아직 처리 안 됨)", _excluded_box(R))]
    over = _mg(mode, _over_line(R))   # 예산 초과는 경영관리용에만 (사용자 2026-11-03: 대표용엔 예산 언급 없음)
    if monthly:
        # 1쪽 자금(흐름·앞으로) · 2쪽 ③ 지난 미처리 · ④ 세금 · ⑤ 이번 달 실적(월별 흐름 그림 포함) · 3쪽 누적(이번 달 · 앞으로 들어올 매출 · 누적·목표). ⑦ 계정과목별 표는 경영관리용에만
        blocks = ([("이번 달 자금 흐름", _flow_card(s1, per))] + funds + past + [("부가세·원천세 (분기·반기별)", _regular_box(R))]   # 밀린 돈 → 앞으로 낼 세금 (사용자 2026-11-05)
                  + [("%s 실적 (이번 달)" % ymt, _results(R, cum=False) + over + _team_table(R, mode=mode) + _month_chart(R)),
                     ("올해 누적 실적 (1월~%s) · 목표 대비" % ymt, _team_table(R, "ytd", mode=mode))]
                  + [_acct_year_block(R, mode)])
    else:
        wo = week_outflows(R)
        # 1쪽 = 이번 주 지급(출금 목록·다음 주 예정), 2쪽 = 자금 현황 → 실적 (사용자 2026-11-05: 맥락에 맞게, 빈 곳 최소)
        blocks = ([("%s 출금 목록" % _day(wo["fri"]), _week_out_table(R, mode))] + funds
                  + [("%s 실적" % ymt, _results(R, cum=True) + over)])
    h = ["<div class='page fs%s'>" % (" mon" if monthly else "")]
    h.append(_mg(mode, _fresh_warn(R) + _decide_lines(R)))
    h.append(_mon_strip(R) if monthly else _top_strip(R))
    for i, (title, body) in enumerate(blocks):
        # 주간 ① 출금 목록은 길면 쪽을 넘어 이어진다 (사용자 2026-11-04: 통째로 다음 쪽에 밀려 1쪽이 비던 것)
        cls = "sec brk" if (not monthly and i == 0) else "sec"
        if not monthly and i == 1:
            cls = "sec sflow pgb"   # 자금 현황은 2쪽 첫머리에서   # 주간 ③ 자금: 표와 그림 사이에서 쪽을 나눌 수 있게 (사용자 2026-11-05: 빈 곳 최소)
        if monthly and i in (2, 5):
            cls += " pgb"   # 월간 2쪽 = ③ 지난 미처리 · ④ 세금 · ⑤ 실적(그림 포함)을 빡빡하게 (사용자 2026-11-05 최종), 3쪽 = ⑥   # 월간 ⑥ 누적 실적은 3쪽에 통째로 (사용자 2026-11-04: 6번이 쪽에 걸치면 안 됨)
        sec = "<div class='%s'>%s%s</div>" % (cls, _q(i, title, _ev_tags(R, i + 1)), body)
        if monthly and i == 6:
            sec = _mg(mode, sec)   # 계정과목별 사용 금액은 경영관리용에만 (사용자 2026-11-04: 대표 보고에서 없앰)
        h.append(sec)
    h.append("<div class='evid'>숫자 옆 ‘근거’ 번호로 요청하시면 경영관리가 해당 근거자료를 제출합니다.%s</div>"
             % ("<span class='doc-end'>끝.</span>" if mode == "ceo" else ""))
    h.append(_mg(mode, _glossary(R)))   # 용어 풀이는 경영관리용에만 (2026-11-05 사용자: 대표 보고 디자인 제안 4). 첫 화면 쪽 안에 (쪽 나눔 뒤로 밀려 빈 쪽이 생기지 않게)
    n = len(blocks)
    if mode == "mgmt":   # 경영관리용: 근거·프로젝트 예산·확인할 것은 '근거자료' 영역으로 나눈다 (사용자 2026-11-11 영역별 보기)
        h.append("</div>" + areas.SUMMARY_MARK + "<div class='page fs%s'>" % (" mon" if monthly else ""))
    h.append(_mg(mode, _evidence(R, n) + "<div class='sec'>%s%s</div><div class='sec'>%s%s</div>" % (
        _q(n + 1, "프로젝트별 원가 예산·집행"), _project_bars(R, per, active_only=not monthly),
        _q(n + 2, "위 숫자에 안 들어간 것 · 확인할 것"), _check_box(R))))
    if mode == "mgmt":
        hi = sum(1 for r in R["risks"] if r["level"] == "높음")
        h.append("<div class='note' style='margin-top:10px'>위험 항목 %d건 (높음 %d건) — <a href='#risk'>‘위험 분석·해결방안’ 보기</a></div>"
                 % (len(R["risks"]), hi))
    h.append("</div>")
    return "".join(h)


def _top_strip(R):
    """주간 첫 줄 (사용자 2026-11-04 결정): 금요일 출금 · 이번 주 가용자금 · 4주 가용자금 · 입금일 지난 미수금.
    값은 아래 표와 같은 숫자를 그대로 옮긴다 (따로 계산하지 않음)."""
    wo, s5 = week_outflows(R), R["s5"]
    ps = [p for p in R["s2"]["periods"] if not p.get("pick")]
    if not ps:
        return ""

    def av(p):
        a = p["firm"]["avail"]
        return _na("확인 필요") if a is None else "<span class='%s'>%s</span>" % ("neg" if a < 0 else "", esc(won(a)))

    def low_day(p):
        d0 = p["firm"]["low_date"]
        return "" if d0 is None else ("오늘" if d0 == R["asof"] else _md(d0))
    pay = wo["pay"]
    # 카드 아래 글은 한 마디만 (사용자 2026-11-05: 최소한의 안내만 넣고 나머지는 삭제)
    cells = [("%s 출금" % _day(wo["fri"]), W(pay["total"]), "%d건" % len(pay["rows"])),
             # '가장 적을 때' 날짜는 빼고 칸만 (사용자 2026-11-05: 여유 자금은 최소한의 안내만)
             ("이번 주 여유 자금", av(ps[0]), ""),
             ("%s까지 여유 자금" % ps[-1]["label"], av(ps[-1]), "")]
    od = _overdue_cell(s5)
    cells.append((od[0], od[1], "%d건" % len(s5["overdue"]) if not s5["in_missing"] and s5["overdue"] else ""))
    return _strip(cells)


def _strip(cells):
    return "<div class='four top'>%s</div>" % "".join(
        "<div class='card'><div class='lab'>%s</div><div class='big'>%s</div><div class='foot'>%s</div></div>"
        % (esc(a), b, esc(c)) for a, b, c in cells)


def _overdue_cell(s5):
    if s5["in_missing"]:
        return ("입금일 지난 미수금", _na("계산서 자료 없음"), "")
    if not s5["overdue"]:
        return ("입금일 지난 미수금", "없음", "")
    top = max(s5["overdue"], key=lambda v: v["outstanding"] or 0)
    return ("입금일 지난 미수금", "<span class='neg'>%s</span>" % esc(won(s5["overdue_total"])),
            "%d건 · 가장 큰 건 %s %s (%d일 지남)" % (len(s5["overdue"]), top["client"] or "", won(top["outstanding"]),
                                             top["overdue_days"]))


def _mon_strip(R):
    """월간 첫 줄 '한눈에' (사용자 2026-11-04: 월간 쪽 디자인 다시): 월말 잔액 · 앞으로 가용자금 · 이번 달 영업이익 · 입금일 지난 미수금.
    값은 아래 절과 같은 숫자를 옮긴다 (따로 계산하지 않음)."""
    s1, s5 = R["s1"], R["s5"]
    ym = _ym_text(R["s4"]["ym"])
    ps = [p for p in R["s2"]["periods"] if not p.get("pick")]
    # 통장 잔액·영업이익 칸 아래 풀이는 ①·⑤와 겹쳐 뺌 (사용자 2026-11-05)
    cells = [("%s말 통장 잔액" % ym, W(s1["end"]), "")]
    if ps:
        a = ps[-1]["firm"]["avail"]
        d0 = ps[-1]["firm"]["low_date"]
        ea = ps[-1]["all"]["avail"]
        cells.append(("%s까지 여유 자금" % ps[-1]["label"], _na("확인 필요") if a is None else
                      "<span class='%s'>%s</span>" % ("neg" if a < 0 else "", esc(won(a))),
                      "" if ea is None or ea == a else "예상 지급까지 빼면 %s" % won(ea)))
    rev, np_ = _month_rev_np(R)
    cells.append(("%s 영업이익" % ym, W(np_, "확인 필요"), ""))
    cells.append(_overdue_cell(s5))
    return _strip(cells)


def _month_rev_np(R):
    """이번 달 회사 매출과 영업이익 (⑤ 실적 칸과 같은 값: 팀 표 회사 영업이익이 있으면 그것)."""
    s4 = R["s4"]
    src = s4["sources"].get("WEHAGO")
    co = [r for r in src["table"] if r["unit"] == "회사"] if src else []
    if not co or not co[0]["cur"]:
        return None, None
    c = co[0]["cur"]
    np_ = c["np"]
    if s4.get("dept") is not None:
        from .teamprofit import build as _tp_build
        T = _tp_build(src["table"], s4["dept"], s4["ym"], False)
        if T is not None and T["company"]["net"] is not None:
            np_ = T["company"]["net"]
    return c["revenue"], np_


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
    ds = sorted(set(a.get("bank_date") or a["date"] for a in s1["accounts"]))
    if not ds:
        return "자료 없음"
    txt = d2s(ds[0]) if len(ds) == 1 else "%s~%s" % (d2s(ds[0]), d2s(ds[-1]))
    if s1.get("rolled"):   # 그 뒤 입출금내역을 반영해 오늘 잔액으로 계산함 (사용자 2026-11-04)
        txt += " + 입출금 %s까지 반영" % d2s(s1["txn_cover"])
    return txt


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
    if rate is None:
        return "설정 오류"
    text = "%g%%" % round(rate * 100, 6)
    if s3.get("team_rate_n"):   # 팀 목표 수익률이 있는 팀은 원가율 = 1 − 목표 수익률 (사용자 2026-11-05)
        text += " (팀 목표 수익률이 있는 팀은 100% − 목표 수익률)"
    return text


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
        bd = d2s(a["date"]) if not a.get("bank_date") else "%s (은행 %s %s %s건)" % (
            d2s(a["date"]), d2s(a["bank_date"]), "%+d" % a["roll"] if a["roll"] else "±0", a["roll_n"])
        rows.append([esc(a["account"]), esc(a["bank"]), esc(bd), W(a["balance"]), W(a["restricted"]),
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
        rows.append([esc(P["id"]), esc(P["name"]), esc(P["team"]), esc(_state_text(P)), W(P["estimate"], "-"),
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


def _state_text(P):
    """프로젝트 표 상태 칸: 손으로 적은 상태가 없고 인트라넷에서 대표이사 승인까지 끝났으면 '종결(대표 승인)' (사용자 2026-11-11)."""
    st = (P.get("state") or "").strip()
    if not st and (P.get("approval") or "").strip() == "대표이사":
        return "종결(대표 승인)"
    return st


def _event_unissued_table(s5):
    """행사일이 지났는데 계산서가 덜 나간 프로젝트 (사전견적 − 발행, 오래된 행사 순). 모르는 것은 까닭과 함께 건수로."""
    E = s5["event_unissued"]
    h = ["<h3>%s</h3>" % esc("행사 끝난 뒤 계산서 미발행 (%d건)" % len(E["rows"]))]
    if E["missing"]:
        h.append("<div class='note na'>%s</div>" % esc("계산서 자료 없음 — 행사 후 미발행은 ‘자료 없음’"))
        return "".join(h)
    rows = [[esc(y["P"]["id"]), esc(y["P"]["name"]), esc(d2s(y["event"])), esc("%d일" % y["days"]),
             W(y["estimate"]) + ("<small> 견적금액</small>" if y.get("quoted") else ""), W(y["issued"], "0"), W(y["unissued"])] for y in E["rows"]]
    h.append(table(["번호", "프로젝트", "행사일", "행사 후", "사전견적(공급가)", "발행금액(공급가)", "미발행금액"], rows,
                   num_cols=(3, 4, 5, 6), total=["합계", "", "", "", "", "", W(E["total"])]))
    note = ("미발행금액 = 사전견적 − 발행금액(공급가). 행사일이 기준일 전인 프로젝트만. "
            "인트라넷에서 대표이사 승인까지 끝난 프로젝트는 사전견적 대신 확정 견적금액 기준.")
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


def _xk_final_why(p, b, c, v, d0, used):
    """실행가 차이 한 줄의 설명 (사용자 2026-11-11). d0 = 장부 원가 − 실행가, used = 그중 카드 부가세로 설명되는 금액.
    장부에서 알 수 있는 까닭만 적는다."""
    why = []
    if p.get("out_of_period"):
        why.append("분개장 기간 밖 원가가 있어 장부 원가를 다 알 수 없음")
    elif c is None:
        why.append("금액 모르는 원가 줄이 있어 차이 판단 불가")
    if b is None:
        why.append("인트라넷 실행가 빈칸")
    if d0 is None:
        return " · ".join(why)
    if d0 == 0:
        why.append("일치")
        return " · ".join(why)
    if used:
        if used == v:
            why.append("인트라넷 실행가에 법인카드 사용분 부가세 %s 포함 (%d건 전부) → 그만큼 실행가가 큼" % (won(used), p.get("card_n") or 0))
        else:
            why.append("인트라넷 실행가에 법인카드 사용분 부가세 포함 → %s은 카드 부가세로 설명됨 (카드 부가세 모두 %s 중 일부만 인트라넷에 부가세 포함으로 올라감)"
                       % (won(used), won(v)))
    rest = d0 + used
    if rest == 0:
        why.append("카드 부가세를 빼면 일치")
    elif rest > 0:
        why.append("장부 원가가 실행가보다 %s 많음 → 실행가에 없는 지출이거나 다른 프로젝트 원가가 이 번호로 들어갔을 수 있음" % won(rest))
    else:
        rq = p.get("requested")
        head = "카드 부가세를 빼고도 " if used else ""
        if rq is not None and c is not None and rq > c + (v or 0):
            why.append("%s장부 원가가 실행가보다 %s 적음 · 지급요청 누계 %s가 장부 원가보다 많음 → 증빙이 아직 장부에 없거나 전표에 프로젝트 번호가 안 붙었을 수 있음"
                       % (head, won(-rest), won(rq)))
        else:
            why.append("%s장부 원가가 실행가보다 %s 적음 → 아직 안 들어온 증빙, 프로젝트 번호 안 붙은 전표, 또는 실행가보다 덜 쓴 금액" % (head, won(-rest)))
    return " · ".join(why)


def _xk_final_table(X, R):
    """최종 실행가 차이 (사용자 2026-11-11): 인트라넷에서 팀장 승인 이상(~대표이사 승인) 진행된 프로젝트만,
    인트라넷 실행가 대 위하고 장부 (도)원가. 장부 원가는 회계자료 기준 = 부가세 뺀 금액 (카드 결제분도).
    인트라넷 실행가는 법인카드 사용분 일부가 부가세 포함이라, 실행가가 장부 원가보다 큰 만큼은 카드 부가세 범위 안에서 '설명됨'으로 본다.
    차이는 두 값을 모두 알 때만."""
    from .linking import APPROVAL_STAGES, APPROVAL_TEAM_UP
    ps = dict((P["id"], P) for P in ((R or {}).get("s3") or {}).get("projects", []))
    if not any((P.get("approval") or "") for P in ps.values()):
        return "<div class='note'>%s</div>" % esc("승인 단계 자료 없음 — 인트라넷 자료를 받은 뒤 '자료 변환'을 하면 채워짐 (승인된 프로젝트가 하나도 없을 때도 이 글)")
    rows, s_b, s_c, s_v, n_both, s_d, s_used, s_rest, n_vat = [], 0, 0, 0, 0, 0, 0, 0, 0
    order = dict((n, i) for i, n in enumerate(APPROVAL_STAGES))
    picked = [p for p in X["projects"] if (ps.get(p["key"], {}).get("approval") or "") in APPROVAL_TEAM_UP]
    picked.sort(key=lambda p: (-order[ps[p["key"]]["approval"]], p["key"]))
    for p in picked:
        stage = ps[p["key"]]["approval"]
        b = p["budget"] if p["has_budget"] else None
        c = None if p.get("out_of_period") else p["cost"]
        v = p.get("card_vat") or 0
        d0 = None if b is None or c is None else c - b
        # 실행가가 장부 원가보다 큰 만큼을 카드 부가세(있는 만큼)로 설명한다
        used = 0 if d0 is None else max(0, min(v, -d0))
        rest = None if d0 is None else d0 + used
        if d0 is not None:
            s_b, s_c, s_v, n_both = s_b + b, s_c + c, s_v + v, n_both + 1
            s_d, s_used, s_rest, n_vat = s_d + d0, s_used + used, s_rest + rest, n_vat + (1 if used else 0)
        why = _xk_final_why(p, b, c, v, d0, used)
        if d0 is None:
            verdict = ("na", "판단 불가")
        elif d0 == 0:
            verdict = ("ok", "일치")
        elif rest == 0:
            verdict = ("ok", "카드 부가세로 설명")
        elif rest > 0:
            verdict = ("hi", "장부 원가 많음")
        else:
            verdict = ("lo", "장부 원가 적음")
        rows.append(([esc(p["key"]), esc(p["name"]), esc(stage + " 승인"), _xk_none() if b is None else esc(won(b)),
                      _xk_period_cell(p["cost"], p["cost_note"], p.get("out_of_period"), p.get("cost_period")),
                      _xk_diff(d0), esc(won(v)) if v else _xk_none(), esc(won(used)) if used else _xk_none(), _xk_diff(rest),
                      _na("판단 불가") if d0 is None or not b else esc("%.1f%%" % (c * 100.0 / b)),
                      "<span class='xv %s'>%s</span>" % verdict], why if why and why != "일치" else ""))
    if not rows:
        return "<div class='note'>%s</div>" % esc("팀장 승인 이상 진행된 프로젝트 없음")
    # 사용자 2026-11-12: '차이 설명' 칸이 좁아 읽을 수 없음 → 숫자 줄 밑에 표 너비 전체로 설명 줄을 붙이고, 끝 칸은 짧은 판정만
    head = ["번호", "프로젝트", "승인 단계", "인트라넷 실행가", "장부 원가", "차이 (장부 원가−실행가)",
            "카드 부가세", "카드 부가세로 설명", "남는 차이", "실행가 대비", "판정"]
    nums = (3, 4, 5, 6, 7, 8, 9)
    td = lambda i, c: '<td class="n">%s</td>' % c if i in nums else "<td>%s</td>" % c
    body = []
    for cells, why in rows:
        body.append("<tr class='xmain%s'>%s</tr>" % ("" if why else " xnowhy", "".join(td(i, c) for i, c in enumerate(cells))))
        if why:
            body.append("<tr class='xsub'><td></td><td colspan='%d'>%s</td></tr>" % (len(head) - 1, esc(why)))
    total = ["합계 (두 값을 모두 아는 %d건)" % n_both, "", "", esc(won(s_b)), esc(won(s_c)), esc(won(s_d)), esc(won(s_v)),
             esc(won(s_used)), esc(won(s_rest)), esc("%.1f%%" % (s_c * 100.0 / s_b)) if s_b else "",
             esc("카드 부가세로 설명되는 프로젝트 %d건" % n_vat) if n_vat else ""]
    body.append('<tr class="tot">%s</tr>' % "".join(td(i, c) for i, c in enumerate(total)))
    style = ("<style>#xchk-final tr.xsub td{border-top:0;padding-top:0;color:#444;font-size:.92em;line-height:1.45;white-space:normal}"
             "#xchk-final tr.xmain:not(.xnowhy) td{border-bottom:0}"
             "#xchk-final tr.xmain td:nth-child(3){white-space:nowrap}#xchk-final .xv{white-space:nowrap;font-weight:600}#xchk-final .xv.hi,#xchk-final .xv.lo{color:#b42318}"
             "#xchk-final .xv.ok{color:#1f6f43}#xchk-final .xv.na{color:#666}</style>")
    out = style + '<div class="tw"><table id="xchk-final" class=""><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (
        "".join('<th class="n">%s</th>' % esc(c) if i in nums else "<th>%s</th>" % esc(c) for i, c in enumerate(head)), "".join(body))
    per = _xk_period(X)
    return out + "<div class='note'>%s</div>" % esc(
        "대상 = 인트라넷에서 팀장 승인이 끝난 프로젝트부터 대표이사 승인까지 끝난 프로젝트 (%d건). "
        "장부 원가 = 회계자료 기준 (도)원가, 부가세 뺀 금액 (법인카드 결제분도)%s. 인트라넷 실행가는 법인카드 사용분 일부가 부가세 포함으로 올라가 있어, "
        "실행가가 장부 원가보다 큰 만큼은 그 프로젝트 카드 부가세 범위 안에서 '카드 부가세로 설명'에 넣고 나머지만 '남는 차이'로 둠. "
        "차이가 +면 장부 원가가 실행가보다 큼. 장부 원가는 프로젝트 번호가 붙은 전표만 (미연결 원가는 빠짐). 증빙이 늦게 들어오면 바뀜. "
        "판정 밑 줄은 장부에서 알 수 있는 차이 까닭." % (len(rows), (", " + per) if per else ""))


def _xk_detail(X, R=None):
    """경영관리용에만 붙는 상세 묶음. 시험의 numbers_of 가 이 표지 사이를 뺀다 (REP-02: 요약 숫자는 두 판이 같다)."""
    h = ["<div id='xchk-detail'>",
         "<div class='note'>상세 (경영관리용). 값은 위하고대조.csv의 사실이며, 차이는 두 값을 모두 알 때만 계산 (모르면 ‘판단 불가’).</div>",
         "<h3>지급요청 대조 (상태별)</h3>", _xk_status_table(X),
         "<h3>상태 확인 필요 지급요청 (사장님승인 빈칸·알 수 없는 값, 요청 누계·프로젝트밖요청에 포함)</h3>", _xk_status_check_table(X),
         "<h3>최종 실행가 차이 (팀장 승인 ~ 대표이사 승인 프로젝트)</h3>", _xk_final_table(X, R),
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
        h.append("<div class='note'>%s</div>" % _na("자료 없음 (%s — 대표보고 창의 '자료 변환'으로 만듦)" % XCHK_FILE_NAME))
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
        h.append(_xk_detail(X, R))
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
