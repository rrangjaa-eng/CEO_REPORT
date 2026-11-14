"""지금 현황 화면 (사용자 2026-11-12: 분개장·자금계획서를 가져오면 자금 현황·프로젝트 수익·비용·납부할 세금이 바로 바뀌게).

자료 변환이 끝날 때마다 출력\\지금현황.html 을 새로 쓴다. 보고서와 같은 계산(calc.compute 주간)을 쓰므로 숫자가 보고서와 같다.
브라우저에 열어 두면 1분마다 스스로 다시 읽는다. 지난 현황과 비교한 '바뀐 것'을 위에 보인다 (출력\\현황기록.json, 최근 30번).
PDF 는 만들지 않는다 (대표 보고는 지금처럼 버튼으로).
"""
import datetime as dt
import html
import json
import os

FILE = "지금현황.html"
HISTORY = "현황기록.json"
KEEP = 30
REFRESH_SEC = 60
TAX_DAYS = 120   # 이 날수 안에 낼 세금·카드·4대보험·급여만 보인다


def _won(v):
    return "–" if v is None else "{:,}".format(int(round(v)))


def _e(t):
    from .util import esc   # 주민번호 모양은 가린다 (2026-11-14 코덱스 검토)
    return esc(str(t if t is not None else ""))


def _eok(v):
    """큰 숫자를 '2.3억'·'4,500만' 꼴로 (바뀐 것 줄)."""
    if v is None:
        return "–"
    a = abs(v)
    s = "%.1f억" % (a / 1e8) if a >= 1e8 else ("{:,}만".format(int(round(a / 1e4))) if a >= 1e4 else "{:,}".format(int(a)))
    return ("−" if v < 0 else "") + s


def snapshot(R):
    """현황에서 비교할 숫자만 뽑는다 -> dict (json 으로 저장)."""
    s1, s2 = R.get("s1") or {}, R.get("s2") or {}
    per = s2.get("periods") or []
    last = per[-1] if per else None
    asof = R["asof"]
    taxes = [t for t in (R.get("tax") or []) if t.get("due") and asof < t["due"] <= asof + dt.timedelta(days=TAX_DAYS)]
    projects = {}
    for p in (R.get("s3") or {}).get("projects") or []:
        projects[p.get("id") or p.get("name")] = {"name": p.get("name"), "profit": p.get("profit_end"),
                                                    "paid": p.get("paid_total"), "remain": p.get("remain")}
    return {
        "asof": asof.isoformat(),
        "bank": s1.get("total"),
        "avail_firm": last["firm"]["avail"] if last else None,
        "avail_all": last["all"]["avail"] if last else None,
        "avail_label": last["label"] if last else "",
        "tax_total": sum(t["amount"] for t in taxes if t.get("amount") is not None),
        "projects": projects,
    }


def changes(prev, now):
    """지난 현황과 달라진 것 -> [(이름, 전, 후)] (같으면 뺌)."""
    if not prev:
        return []
    out = []
    for key, name in (("bank", "통장 잔액"), ("avail_firm", "여유 자금 (%s)" % now.get("avail_label")),
                      ("avail_all", "여유 자금 (%s, 예상 입출금 모두 넣으면)" % now.get("avail_label")), ("tax_total", "곧 낼 세금·카드·보험·급여"),
                      ("re_first", "미처분이익잉여금 (이번 주총에서 처리할 돈)")):
        a, b = prev.get(key), now.get(key)
        if a != b:
            out.append((name, a, b))
    pp, np_ = prev.get("projects") or {}, now.get("projects") or {}
    for k, p in np_.items():
        o = pp.get(k)
        if o is None:
            out.append(("새 프로젝트 %s" % p["name"], None, p["profit"]))
        elif o.get("profit") != p.get("profit"):
            out.append(("%s 예상 이익" % p["name"], o.get("profit"), p.get("profit")))
    return out


def _read_history(path):
    try:
        with open(path, encoding="utf-8") as f:
            h = json.load(f)
        return h if isinstance(h, list) else []
    except (OSError, ValueError):
        return []


CSS = """
*{box-sizing:border-box}body{margin:0;font:14px/1.5 'Malgun Gothic','Apple SD Gothic Neo',sans-serif;color:#1d2433;background:#f4f6f9}
header{background:#1f4e8c;color:#fff;padding:12px 20px;display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
header h1{font-size:18px;margin:0}header .m{font-size:12.5px;opacity:.85}
main{max-width:1180px;margin:0 auto;padding:16px 20px 40px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin-bottom:14px}
.card{background:#fff;border:1px solid #dde3ec;border-radius:8px;padding:10px 14px}
.card .k{font-size:12.5px;color:#5b6577}.card .v{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums}
.card .s{font-size:12px;color:#5b6577}.card.main{border-color:#1f4e8c;border-width:2px}
.neg{color:#c62828}
section{background:#fff;border:1px solid #dde3ec;border-radius:8px;padding:12px 16px;margin-bottom:14px}
section h2{font-size:15px;margin:0 0 8px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:4px 8px;border-bottom:1px solid #edf0f5;text-align:left;font-size:13px}
th{color:#5b6577;font-weight:600;background:#f8f9fb}td.n,th.n{text-align:right;white-space:nowrap}
section.auto h2{font-size:16px;margin:0 0 6px}section.auto h3{font-size:14px;margin:14px 0 6px}section.auto .note{font-size:12px;color:#5b6577}
section.auto table{margin-bottom:6px}
.est{color:#8a6d00}.muted{color:#8a93a3;font-size:12px}
.chg{background:#fff8e1;border-color:#f2d27a}.chg li{margin:2px 0}
.up{color:#1b7f3b}.down{color:#c62828}
"""


def _ins_css():
    from . import insights_render
    return insights_render.CEO_CSS


def render(R, now_snap, diff, meta, auto_html=""):
    asof = R["asof"]
    s1, s2 = R.get("s1") or {}, R.get("s2") or {}
    h = ["<!doctype html><html lang='ko'><head><meta charset='utf-8'>",
         "<meta http-equiv='refresh' content='%d'>" % REFRESH_SEC,
         "<meta name='viewport' content='width=device-width,initial-scale=1'>",
         "<title>지금 현황</title><style>%s</style></head><body>" % (CSS + _ins_css())]
    h.append("<header><h1>지금 현황 · %s 기준</h1><span class='m'>%s</span></header><main>"
             % (_e(asof.isoformat()), _e(meta)))
    from . import gate   # 자금계획서·분개장 미반영이면 맨 위에 큰 경고 (사용자 2026-11-12)
    h.append(gate.banner(gate.problems(R), "지금 현황의 자금 숫자"))
    # 바뀐 것
    if diff:
        h.append("<section class='chg'><h2>지난 현황 뒤 바뀐 것</h2><ul>")
        for name, a, b in diff[:15]:
            d = None if a is None or b is None else b - a
            cls = "" if d is None else ("up" if d > 0 else "down")
            h.append("<li>%s: %s → <b>%s</b> %s</li>" % (_e(name), _won(a), _won(b),
                                                          "" if d is None else "<span class='%s'>(%s%s)</span>" % (cls, "+" if d > 0 else "", _eok(d))))
        if len(diff) > 15:
            h.append("<li class='muted'>그 밖 %d건</li>" % (len(diff) - 15))
        h.append("</ul></section>")
    # 자금
    per = s2.get("periods") or []
    last = per[-1] if per else None
    cards = [("통장 잔액", s1.get("total"), "쓸 수 없는 돈 %s원 포함" % _won(s1.get("restricted")), False)]
    if last:
        cards.append(("여유 자금 (%s까지)" % last["label"], last["firm"]["avail"],
                      "확정된 돈과 급여·세금·카드 예상 · 최소 보유현금 %s원 뺌" % _won(s2.get("min_cash")), True))
        cards.append(("프로젝트 지급 예상 등까지 빼면", last["spend"]["avail"], "확정 안 된 지급까지 (예상 입금은 넣지 않음)", False))
    cards.append(("곧 낼 세금·카드·보험·급여", now_snap.get("tax_total"), "%d일 안" % TAX_DAYS, False))
    h.append("<div class='cards'>")
    for k, v, s, main in cards:
        h.append("<div class='card%s'><div class='k'>%s</div><div class='v%s'>%s</div><div class='s'>%s</div></div>"
                 % (" main" if main else "", _e(k), " neg" if (v or 0) < 0 else "", _won(v), _e(s)))
    h.append("</div>")
    if per:
        h.append("<section><h2>주별 여유 자금</h2><table><tr><th>기간</th><th>끝나는 날</th><th class='n'>들어올 돈</th>"
                 "<th class='n'>나갈 돈</th><th class='n'>여유 자금</th><th class='n'>프로젝트 지급 예상 등까지 빼면</th></tr>")
        for p in per:
            f, a = p["firm"], p["spend"]
            h.append("<tr><td>%s</td><td>%s</td><td class='n'>%s</td><td class='n'>%s</td><td class='n%s'><b>%s</b></td>"
                     "<td class='n est'>%s</td></tr>" % (_e(p["label"]), _e(p["end"]), _won(f["in"]), _won(f["out"]),
                                                       " neg" if f["avail"] is not None and f["avail"] < 0 else "", _won(f["avail"]), _won(a["avail"])))
        h.append("</table></section>")
    # 세금 등
    taxes = sorted([t for t in (R.get("tax") or []) if t.get("due") and asof < t["due"] <= asof + dt.timedelta(days=TAX_DAYS)],
                   key=lambda t: t["due"])
    h.append("<section><h2>낼 세금·카드·4대보험·급여 (장부로 계산)</h2>")
    if taxes:
        h.append("<table><tr><th>납부일</th><th>구분</th><th>대상</th><th class='n'>금액</th><th>상태</th></tr>")
        for t in taxes:
            st = t.get("state") or ""
            h.append("<tr><td>%s</td><td>%s</td><td>%s</td><td class='n'>%s</td><td class='%s'>%s</td></tr>"
                     % (_e(t["due"]), _e(t.get("kind")), _e(t.get("period")), _won(t.get("amount")),
                        "" if st.startswith("확정") else "est", _e(st)))
        h.append("</table>")
    else:
        h.append("<p class='muted'>%d일 안에 낼 것이 없습니다.</p>" % TAX_DAYS)
    h.append("</section>")
    # 프로젝트
    projects = (R.get("s3") or {}).get("projects") or []
    h.append("<section><h2>프로젝트 수익·비용</h2>")
    if projects:
        h.append("<table><tr><th>프로젝트</th><th>팀</th><th>행사일</th><th class='n'>계약(매출)</th><th class='n'>쓴 돈</th>"
                 "<th class='n'>예상 총비용</th><th class='n'>예상 이익</th><th class='n'>이익률</th></tr>")
        for p in sorted(projects, key=lambda p: (p.get("event_date") or "9999", p.get("id") or "")):
            sales, profit = p.get("contract"), p.get("profit_end")
            rate = "–" if not sales or profit is None else "%.0f%%" % (100.0 * profit / sales)
            h.append("<tr><td>[%s] %s</td><td>%s</td><td>%s</td><td class='n'>%s</td><td class='n'>%s</td><td class='n'>%s</td>"
                     "<td class='n%s'>%s</td><td class='n'>%s</td></tr>"
                     % (_e(p.get("id")), _e(p.get("name")), _e(p.get("team")), _e(p.get("event_date") or ""), _won(sales),
                        _won(p.get("paid_total")), _won(p.get("expected")), " neg" if (profit or 0) < 0 else "",
                        _won(profit), rate))
        h.append("</table><p class='muted'>쓴 돈 = 이미 지급·카드 결제. 예상 총비용 = 쓴 돈 + 요청·카드 미결제·집행 계획·남은 예산. 예상 이익 = 계약 − 예상 총비용 (부가세 뺀 금액)</p>")
    else:
        h.append("<p class='muted'>프로젝트 자료가 없습니다 (인트라넷 자료를 가져온 뒤 변환하면 보입니다).</p>")
    h.append("</section>")
    # 올해 달별 매출·매입
    ev = getattr(R.get("_data"), "evid_month", None) or R.get("evid_month") or {}
    year = str(asof.year)
    months = sorted(k for k in ev if k.startswith(year))
    if months:
        h.append("<section><h2>%s년 달별 매출·매입 (증빙 작성일 기준, 공급가액)</h2><table><tr><th>달</th>"
                 "<th class='n'>매출</th><th class='n'>매입</th><th class='n'>차이</th></tr>" % year)
        ts, tb = 0, 0
        for k in months:
            s, b = ev[k]
            ts, tb = ts + (s or 0), tb + (b or 0)
            h.append("<tr><td>%s</td><td class='n'>%s</td><td class='n'>%s</td><td class='n'>%s</td></tr>"
                     % (_e(k), _won(s), _won(b), _won((s or 0) - (b or 0))))
        h.append("<tr><th>합계</th><th class='n'>%s</th><th class='n'>%s</th><th class='n'>%s</th></tr></table></section>"
                 % (_won(ts), _won(tb), _won(ts - tb)))
    if auto_html:
        h.append("<section class='auto'>%s</section>" % auto_html)
    h.append("<p class='muted'>이 화면은 자료 변환이 끝날 때마다 새로 써지고, 열어 두면 %d초마다 다시 읽습니다. "
             "숫자는 주간 보고와 같은 계산입니다.</p></main></body></html>" % REFRESH_SEC)
    return "".join(h)


def build(input_dir, output_dir, asof=None, now=None):
    """지금현황.html 을 쓴다 -> (경로, 바뀐 것 목록)."""
    from .calc import compute
    from .data import load
    now = now or dt.datetime.now()
    asof = asof or now.date()
    d = load(input_dir)
    R = compute(d, "weekly", asof)
    R["evid_month"] = getattr(d, "evid_month", None)
    from . import insights as _ins, gate   # 자료가 막히면 자금 숫자를 비우고 경고만 (사용자 2026-11-14): 기록·화면 모두
    R["auto_facts"] = _ins.read_facts(input_dir)
    gate.blank_funds(R)
    snap = snapshot(R)
    # 이익잉여금 (사용자 2026-11-12: 분개장이 오면 자금·매입매출처럼 바로 반영)
    from . import surplus
    RE = surplus.for_report(input_dir, asof.year if asof.month > 3 else asof.year - 1)
    snap["re_first"] = ((RE or {}).get("cur") or {}).get("미처분", (None,))[0]
    snap["at"] = now.strftime("%Y-%m-%d %H:%M")
    os.makedirs(output_dir, exist_ok=True)
    hist_path = os.path.join(output_dir, HISTORY)
    hist = _read_history(hist_path)
    diff = changes(hist[-1] if hist else None, snap)
    fp = R.get("fundplan") or {}
    meta = "만든 때 %s" % snap["at"]
    if (R.get("s1") or {}).get("txn_cover"):
        meta += " · 통장(분개장) %s까지" % R["s1"]["txn_cover"].isoformat()
    if fp.get("stamp"):
        meta += " · 자금계획서 %s 받음" % fp["stamp"].isoformat()
    if hist:
        meta += " · 지난 현황 %s" % hist[-1].get("at", "")
    # 자동 분석 13가지 (사용자 2026-11-12) — 지난 현황 때 일정과 비교해 '바뀐 이유'
    from . import insights, insights_render
    R["_invoices"] = d.invoices
    R["auto_prev"] = hist[-1].get("events") if hist else None
    R["auto_records"] = insights.load_records(output_dir)
    R["auto_profits"] = insights.load_profit_forecasts(output_dir)
    R["_txns"] = d.txns
    I, why = insights.for_report(R)
    auto_html = insights_render.mgmt_section(I, R) if I is not None else "<h2>자동 분석</h2><p class='muted'>계산하지 못함 (%s)</p>" % _e(why)
    auto_html = surplus.live_line(RE) + auto_html
    from . import filing   # 2주 안 신고 기한·지난 것 (사용자 2026-11-12)
    fl = filing.live_lines(filing.load(input_dir), asof)
    if fl:
        auto_html = "<div class='note'><b>신고 기한</b><br>%s</div>" % "<br>".join(_e(x) for x in fl) + auto_html
    snap["events"] = insights.events_for_record(R)
    page = render(R, snap, diff, meta, auto_html)
    path = os.path.join(output_dir, FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(page)
    os.replace(tmp, path)
    if not hist or {k: v for k, v in hist[-1].items() if k != "at"} != {k: v for k, v in snap.items() if k != "at"}:   # 일정까지 같으면 새로 쌓지 않음
        hist.append(snap)
    try:
        with open(hist_path, "w", encoding="utf-8") as f:
            json.dump(hist[-KEEP:], f, ensure_ascii=False)
    except OSError:
        pass
    return path, diff
