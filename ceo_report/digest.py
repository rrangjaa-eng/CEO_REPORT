"""경영관리 보고 1쪽 요약·본문 (사용자 2026-11-12 승인: 경영관리보고 짧게 다시 구성).

  · 1쪽 요약: 영역별 신호등(양호·주의·위험)과 숫자 하나, 지난 예상 대비 실제 오차(매번), 이번 달 해야 할 일 3가지,
    그 달 기한인 신고 한 줄
  · 본문: 신호가 지난 보고보다 나빠졌거나 해야 할 일 3가지에 든 영역만 펼친다. 나머지는 한 줄로 접는다
    (사용자 2026-11-12 카드: '주의'라도 지난번과 같고 할 일이 없으면 접음). '지난 예상 대비 실제 오차'는 늘 펼침
  · 상세(지금까지의 모든 장·표)는 부록 A·B 에 그대로. 결산·세무·신용평가는 3·6·9·12월분 월간 보고의 부록 C (정기 절)

신호등은 새 기준을 만들지 않고 이미 있는 규칙을 쓴다: 위험 분석(설정.csv 기준값)의 영역별 '높음'=위험·'중간'=주의,
현금흐름표 건강 점검, 위하고 대조 상태, 손익표의 회사 줄. AI 없이 정해진 문장만.
"""
import datetime as dt
import json
import os
import re

from .util import won, esc, d2s

OK, WA, BAD = "ok", "wa", "bad"
WORD = {OK: "양호", WA: "주의", BAD: "위험"}
RANK = {OK: 0, WA: 1, BAD: 2}
RECORD_DIR = "자동분석기록"   # insights 와 같은 폴더 (출력\자동분석기록)


def _W(v):
    return "미확인" if v is None else won(v)


def _eok(v):
    """1.12억 / 4,200만 꼴 (타일 큰 숫자)."""
    if v is None:
        return "미확인"
    a = abs(v)
    s = "−" if v < 0 else ""
    if a >= 100000000:
        return "%s%.2f억" % (s, a / 1e8)
    if a >= 10000:
        return "%s%s만" % (s, format(int(round(a / 1e4)), ","))
    return "%s%s원" % (s, format(a, ","))


# ─────────── 부록 이름 (render.py 영역 키와 같게) ───────────
APPX_A = [("sum", "A-1 대표 보고 화면"), ("ev", "A-2 근거자료·확인할 것"), ("risk", "A-3 위험 분석·해결방안"), ("auto", "A-4 자동 분석")]


def periodic(R):
    """정기 절 (사용자 2026-11-12 시안 승인): 월간 보고 기간 끝 달로 정함.
    분기 = 3·6·9·12월분, 반기 = 6·12월분, 결산 준비 = 9월분. 주간 보고에는 없음."""
    if R.get("kind") != "monthly":
        return set()
    m = R["period"][1].month
    out = set()
    if m in (3, 6, 9, 12):
        out.add("q")
    if m in (6, 12):
        out.add("h")
    if m == 9:
        out.add("prep")
    return out


def _risk_level(R, names):
    rs = [r for r in R.get("risks") or [] if r["area"] in names]
    if any(r["level"] == "높음" for r in rs):
        return BAD, rs
    if rs:
        return WA, rs
    return OK, rs


def _company_pl(R):
    for src, v in (R.get("s4") or {}).get("sources", {}).items():
        for r in v["table"]:
            if r["unit"] == "회사":
                return src, r
    return None, None


def lights(R, I=None):
    """영역 목록 -> [{key, name, appx:[(영역키, 부록이름)], lv, num, sub, facts:[글]}]."""
    out = []
    s2 = R.get("s2") or {}

    # ① 자금 — 위험 분석 '자금'
    lv, rs = _risk_level(R, ("자금",))
    per = (s2.get("periods") or [])
    p = per[0] if per else None
    firm = p and p.get("firm", {}).get("avail")
    allv = p and p.get("all", {}).get("avail")
    out.append({"key": "cash", "name": "자금", "appx": [("s1", "B-1"), ("s2", "B-2")], "lv": lv,
                "num": _eok(firm) if p else "미확인",
                "sub": ("%s 여유 자금(확정). 예상 포함 %s" % (p["label"], _eok(allv))) if p else "여유 자금 계산 못 함",
                "facts": [r["fact"] for r in rs]})

    # ② 프로젝트 예산 — 위험 분석 '프로젝트'
    lv, rs = _risk_level(R, ("프로젝트",))
    hi = sum(1 for r in rs if r["level"] == "높음")
    out.append({"key": "proj", "name": "프로젝트 예산", "appx": [("s3", "B-3")], "lv": lv,
                "num": "%d건" % hi, "sub": "예산 넘음·손실 예상 (확인할 것 %d건)" % (len(rs) - hi),
                "facts": [r["fact"] for r in rs]})

    # ③ 매출·손익 — 손익표 회사 줄: 누적 손실 = 위험, 누적은 이익인데 이번 달 손실 = 주의
    src, row = _company_pl(R)
    facts = []
    if row and row.get("ytd"):
        y, c = row["ytd"], row.get("cur")
        yv = y["np"] if y["np"] is not None else y["gp"]
        cv = (c["np"] if c["np"] is not None else c["gp"]) if c else None
        name = "공통비 차감 손익" if y["np"] is not None else "직접비 차감 이익"
        if yv is None:
            lv, num, sub = WA, "판단 불가", "손익 금액 미확인"
        else:
            lv = BAD if yv < 0 else (WA if cv is not None and cv < 0 else OK)
            rate = "%.1f%%" % (yv * 100.0 / y["revenue"]) if y["revenue"] else "-"
            num, sub = rate, "올해 누적 %s률 (%s)" % (name, src)
            facts.append("올해 누적 매출 %s원, %s %s원." % (_W(y["revenue"]), name, _W(yv)))
            if cv is not None:
                facts.append("이번 달 %s %s원%s." % (name, _W(cv), " (잠정)" if c.get("provisional") else ""))
    else:
        lv, num, sub = WA, "자료 없음", "손익.csv 회사 줄 없음"
        facts.append("손익 자료에 회사 줄이 없어 판단하지 못함.")
    out.append({"key": "pl", "name": "매출·손익", "appx": [("s4", "B-4")], "lv": lv, "num": num, "sub": sub, "facts": facts})

    # ④ 계산서·수금 — 위험 분석 '수금'
    lv, rs = _risk_level(R, ("수금",))
    s5 = R.get("s5") or {}
    out.append({"key": "ar", "name": "계산서·수금", "appx": [("s5", "B-5")], "lv": lv,
                "num": _eok(s5.get("overdue_total")) if s5.get("overdue_total") is not None else "미확인",
                "sub": "입금예정일 지난 미수 (%d건)" % len(s5.get("overdue") or []),
                "facts": [r["fact"] for r in rs]})

    # ⑤ 프로젝트 밖 지급 — 지급일·금액 모르는 건이 있으면 주의
    s6 = R.get("s6") or {}
    und, unk = s6.get("undated_n") or 0, s6.get("unknown_n") or 0
    facts = []
    if und:
        facts.append("지급일 없는 프로젝트 밖 지급 %d건." % und)
    if unk:
        facts.append("금액 미확인 프로젝트 밖 지급 %d건." % unk)
    out.append({"key": "other", "name": "프로젝트 밖 지급", "appx": [("s6", "B-6")], "lv": WA if facts else OK,
                "num": _eok(s6.get("total")), "sub": "남은 지급의무 합계", "facts": facts})

    # ⑥ 지급 관리·자료 — 위험 분석 '자료'·'지급 관리'
    lv, rs = _risk_level(R, ("자료", "지급 관리"))
    out.append({"key": "data", "name": "자료·지급 관리", "appx": [("s7", "B-7")], "lv": lv,
                "num": "%d건" % len(rs), "sub": "자료 늦음·대조 차이·계획 밖 지급", "facts": [r["fact"] for r in rs]})

    if R.get("kind") == "monthly":
        # ⑦ 위하고 대조 — 대조 자료 상태
        X = R.get("xchk") or {}
        st = X.get("state")
        if st == "ok":
            lv, num, sub, facts = OK, "대조함", "위하고 원가·계산서와 인트라넷 대조", []
        else:
            lv, num, sub = WA, st or "자료 없음", "대조 자료 확인 필요"
            facts = ["위하고 대조: %s." % (X.get("reason") or st or "자료 없음")]
        out.append({"key": "xchk", "name": "위하고 대조", "appx": [("s8", "B-8")], "lv": lv, "num": num, "sub": sub, "facts": facts})

        # ⑧ 현금흐름 — 건강 점검 (warn = 주의)
        CF = R.get("cf")
        lv, num, sub, facts = WA, "자료 없음", "현금흐름표 만들지 못함", ["현금흐름 자료가 없어 판단하지 못함."]
        if CF and CF.get("ok", True) and (CF.get("M") or CF.get("Y")):
            try:
                from .cashflow import health
                verdict, hl, rows = health(CF)
                lv = WA if hl == "warn" else OK
                run = [a for q, a, _ in rows if q.startswith("버틸")]
                m = re.search(r"([\d.]+)달 치", run[0]) if run else None
                num = "%s달 치" % m.group(1) if m else ("건강" if hl == "ok" else WORD[lv])
                sub = "통장 잔액 ÷ 월평균 본업 지출" if m else verdict.split(" — ")[0]
                facts = [verdict] + ["%s: %s" % (q, a) for q, a, l in rows if l == "warn"]
            except Exception as e:   # 요약 때문에 보고서를 못 만들면 안 된다
                facts = ["현금흐름 판정 못 함 (%s)." % type(e).__name__]
        out.append({"key": "cf", "name": "현금흐름", "appx": [("s9", "B-9")], "lv": lv, "num": num, "sub": sub, "facts": facts})
    return out


def todos(R, I=None, n=3):
    """해야 할 일: 위험 분석 '높음' 먼저(이미 높음→중간 순), 자동 분석 경보 '높음'은 위험 분석에 없는 것만 뒤에. -> [(영역키 또는 None, 할 일, 사실)]."""
    area_key = {"자금": "cash", "프로젝트": "proj", "수금": "ar", "자료": "data", "지급 관리": "data"}
    out = []
    for r in R.get("risks") or []:
        out.append((area_key.get(r["area"]), r["action"], r["fact"], r["level"]))
    hi = [x for x in out if x[3] == "높음"]
    mid = [x for x in out if x[3] != "높음"]
    alerts = [(None, t, "자동 분석 경보", "높음") for lv, t in ((I or {}).get("alerts") or []) if lv == "높음"]
    pick = (hi + alerts + mid)[:n]
    return [(k, a, f) for k, a, f, _ in pick]


def filing_line(R):
    """그 달(보고 기준일 뒤 31일 안) 기한인 신고 한 줄 (사용자 2026-11-12 카드: 월간엔 기한 한 줄만)."""
    rows = R.get("filing") or []
    asof = R["asof"]
    out = []
    for r in rows:
        try:
            d = dt.date.fromisoformat(r["기한"])
        except (KeyError, ValueError):
            continue
        if (r.get("상태") or "").startswith("냄"):
            continue
        if asof < d <= asof + dt.timedelta(days=31) or (r.get("상태") or "").startswith("지남"):
            out.append("%s %s (%s)" % (r["기한"], r["신고"], r.get("대상", "")))
    return out


# ─────────── 지난 보고 신호 기록 ───────────
def record_path(out_dir, R):
    return os.path.join(out_dir, RECORD_DIR, "신호_%s_%s.json" % (R["kind"], R["asof"].isoformat()))


def write_record(out_dir, R):
    L = R.get("_lights")
    if not L:
        return None
    path = record_path(out_dir, R)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict((x["key"], x["lv"]) for x in L), f, ensure_ascii=False)
    return path


def load_previous(out_dir, kind, asof):
    """같은 종류(주간·월간) 보고 중 기준일이 이번보다 앞선 마지막 것 -> (기준일, {영역: 신호}) 또는 None."""
    folder = os.path.join(out_dir, RECORD_DIR)
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    best = None
    for nm in names:
        m = re.match(r"^신호_%s_(\d{4}-\d{2}-\d{2})\.json$" % kind, nm)
        if not m:
            continue
        d = dt.date.fromisoformat(m.group(1))
        if d < asof and (best is None or d > best[0]):
            best = (d, nm)
    if not best:
        return None
    try:
        with open(os.path.join(folder, best[1]), encoding="utf-8") as f:
            return best[0], json.load(f)
    except (OSError, ValueError):
        return None


def decide(L, prev, todo_keys):
    """펼칠 영역: 지난 보고보다 나빠짐 · 해야 할 일에 듦 · (지난 기록 없음 + 양호 아님). 좋아지거나 같으면 접음."""
    pv = (prev or (None, {}))[1]
    for x in L:
        before = pv.get(x["key"]) if prev else None
        x["before"] = before
        x["changed"] = before is not None and before != x["lv"]
        worse = before is not None and RANK.get(x["lv"], 0) > RANK.get(before, 0)
        x["open"] = worse or x["key"] in todo_keys or (prev is None and x["lv"] != OK)
    return L


# ─────────── 그리기 ───────────
CSS = """
.dg1 .grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.dg1 .tile{border:1.5px solid var(--line);border-radius:10px;padding:8px 10px;text-decoration:none;color:inherit;display:block;break-inside:avoid}
.dg1 .tile .nm{font-size:11.5px;font-weight:700;color:var(--sub);display:flex;justify-content:space-between;align-items:center;gap:4px;white-space:nowrap}
.dg1 .tile .v{font-size:17px;font-weight:800;margin:3px 0 1px;font-variant-numeric:tabular-nums}
.dg1 .tile .d{font-size:10.5px;color:var(--sub)}
.dg1 .tile.ok{border-color:#b9dcc9}.dg1 .tile.wa{border-color:#ecd08a;background:#fffcf3}.dg1 .tile.bad{border-color:#e3a596;background:#fffaf8}
.lt{display:inline-flex;align-items:center;gap:4px;font-size:10.5px;font-weight:700;border-radius:9px;padding:0 7px;white-space:nowrap;flex-shrink:0}
.lt i{width:8px;height:8px;border-radius:50%;display:inline-block}
.lt.ok{background:#e7f3ec;color:#2f7d5b}.lt.ok i{background:#2f7d5b}
.lt.wa{background:#fff3d6;color:#a86b00}.lt.wa i{background:#a86b00}
.lt.bad{background:#fbe9e7;color:#b5523b}.lt.bad i{background:#b5523b}
.chg{font-size:10px;font-weight:700;color:#fff;background:var(--accent);border-radius:6px;padding:0 5px;margin-left:4px;white-space:nowrap}
.dg1 .fc{border:1.5px solid var(--accent);border-radius:10px;padding:8px 12px;margin-top:8px;break-inside:avoid}
.dg1 .fch{display:flex;justify-content:space-between;align-items:baseline;gap:8px;font-size:12.5px;margin-bottom:2px;flex-wrap:wrap}
.dg1 .fch span{font-size:11px;color:var(--sub)}
.dg1 .todo{border:2px solid var(--ink);border-radius:10px;padding:8px 14px;break-inside:avoid}
.dg1 .todo ol{margin:2px 0;padding-left:20px}.dg1 .todo li{margin:5px 0}
.dg1 .todo li small{display:block;color:var(--sub);font-size:11px}
.dg1 a.go{color:var(--accent);font-weight:700;text-decoration:none;font-size:11.5px;white-space:nowrap}
.dg1 .strip{display:flex;gap:8px;flex-wrap:wrap;font-size:12px;margin-top:6px}.dg1 .strip span{background:var(--soft);border-radius:6px;padding:3px 8px}
.dg1 .chap{border:1.5px solid var(--line);border-radius:10px;margin:10px 0;overflow:hidden;break-inside:avoid}
.dg1 .chap>.hd{display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--soft);font-weight:800;flex-wrap:wrap}
.dg1 .chap>.hd .r{margin-left:auto;font-weight:400;font-size:11.5px;color:var(--sub)}
.dg1 .chap>.bd{padding:8px 12px}
.dg1 .chap ul{margin:2px 0 6px;padding-left:18px;font-size:12.5px}.dg1 .chap li{margin:2px 0}
.dg1 .fold{display:flex;align-items:center;gap:8px;padding:7px 12px;border-top:1px solid var(--line);font-size:12.5px;flex-wrap:wrap}
.dg1 .fold:first-child{border-top:0}
.dg1 .fold .t{font-weight:700;min-width:130px}.dg1 .fold .s{color:var(--sub);flex:1;min-width:160px}
.dg1 .box{border:1.5px solid var(--line);border-radius:10px}
.dg1 .pgb{break-before:page}
@media screen and (max-width:820px){.dg1 .grid{grid-template-columns:1fr 1fr}}
"""


def _lt(lv, changed=False, before=None):
    c = "<span class='chg'>바뀜%s</span>" % (" (%s→%s)" % (WORD.get(before, before), WORD[lv]) if before else "") if changed else ""
    return "<span class='lt %s'><i></i>%s</span>%s" % (lv, WORD[lv], c)


def _go(key, label):
    return "<a class='go' href='#a-%s'>%s</a>" % (key, esc(label))


def _appx_links(x):
    return " · ".join(_go(k, "부록 %s" % lab) for k, lab in x["appx"])


def _track_table(K, last_only):
    from .insights_render import _tbl, S
    from .render import W
    rows = []
    items = (K.get("months") or [])[-1:] if last_only else (K.get("months") or [])

    def gap(p, a):
        return "%s <small>(%s)</small>" % (S(a - p), "-" if not p else "%+.0f%%" % ((a - p) * 100.0 / p))
    for r in items:
        for io, name in (("in", "입금"), ("out", "출금")):
            c = r[io]
            rows.append([("%s · %s 예측" % (r["ym"], r["made"].strftime("%m/%d"))) if io == "in" else "", name,
                         W(c["firm"]), W(c["all"]), W(c["actual"]), gap(c["firm"], c["actual"]), gap(c["all"], c["actual"])])
    if not rows:
        return ""
    return _tbl(["달 · 예측한 날", "구분", "예측 (확정분)", "예측 (예상 포함)", "실제 (통장)", "실제 − 확정분", "실제 − 예상 포함"],
                rows, nums=(2, 3, 4, 5, 6))


def _track_line(K):
    """1쪽 오차 상자 아래 한 줄 (숫자로만)."""
    ms = K.get("months") or []
    if not ms:
        return ""
    r = ms[-1]
    out = []
    for io, name in (("in", "입금"), ("out", "출금")):
        c = r[io]
        if c["all"]:
            out.append("예상 포함 %s 예측이 실제보다 %s" % (name, "%.0f%% %s" % (abs(c["all"] - c["actual"]) * 100.0 / c["all"],
                                                                  "많음" if c["all"] > c["actual"] else "적음")))
    return " · ".join(out)


def render(R, I, L, todo, filing, prev):
    """1쪽 요약 + 본문 (영역 'one')."""
    per = "%s ~ %s" % (R["period"][0].isoformat(), R["period"][1].isoformat())
    P = periodic(R)
    h = ["<style>%s</style><div class='dg1'>" % CSS]
    h.append("<h2 id='one'>1쪽 요약</h2>")
    cmp_txt = ("지난 보고(%s)와 비교" % prev[0].isoformat()) if prev else "지난 보고 기록 없음 (다음 보고부터 ‘바뀜’ 표시)"
    reg = []
    if "q" in P:
        reg.append("분기")
    if "h" in P:
        reg.append("반기")
    if "prep" in P:
        reg.append("결산 준비")
    h.append("<div class='note'>기간 %s · %s · %s</div>" % (esc(per), esc(cmp_txt),
             esc("이번 보고에 정기 절(%s)이 붙음 → 부록 C" % "·".join(reg)) if reg else
             esc("결산·세무·신용평가는 분기(3·6·9·12월분)·반기·연간 보고에서")))
    # 신호등
    h.append("<div class='q'>영역별 신호등</div><div class='grid'>")
    for x in L:
        h.append("<a class='tile %s' href='#a-%s'><div class='nm'>%s %s</div><div class='v'>%s</div><div class='d'>%s</div></a>"
                 % (x["lv"], x["appx"][0][0], esc(x["name"]), _lt(x["lv"], x["changed"]), esc(x["num"]), esc(x["sub"])))
    h.append("</div><div class='note'>타일을 누르면 그 부록으로 갑니다. 신호 기준: 위험 분석(설정.csv 기준값)의 ‘높음’ = 위험, ‘중간’ = 주의. "
             "손익은 올해 누적 손실 = 위험, 이번 달 손실 = 주의. 현금흐름은 건강 점검.</div>")
    # 예측 오차 (매번)
    K = (I or {}).get("track") or {}
    t = _track_table(K, True)
    h.append("<div class='fc'><div class='fch'><b>지난 예상 대비 실제</b><span>매번 표시 · 보고 기록의 예측 ↔ 나중 장부</span></div>%s%s</div>"
             % (t or "<div class='note'>지난 보고 기록이 아직 없어 견줄 수 없음 (보고를 만들 때마다 쌓임)</div>",
                ("<div class='note'>%s. %s</div>" % (esc(_track_line(K)), _go("auto", "전체 → 부록 A-4 (자동 분석 15)"))) if t else ""))
    # 해야 할 일
    h.append("<div class='q'>해야 할 일 %d가지</div><div class='todo'><ol>" % len(todo) if todo else
             "<div class='q'>해야 할 일</div><div class='todo'><ol>")
    for k, act, fact in todo:
        tgt = next((x for x in L if x["key"] == k), None)
        h.append("<li><b>%s</b> %s<small>%s</small></li>" % (esc(act), _go(tgt["appx"][0][0], "→ " + tgt["name"]) if tgt else _go("auto", "→ 자동 분석"),
                                                          esc(fact)))
    if not todo:
        h.append("<li>위험 분석에 걸린 것 없음</li>")
    h.append("</ol></div>")
    h.append("<div class='note'>이번 달 기한 신고: %s</div>" % (esc(" · ".join(filing)) + " (신고 도우미는 창에서 엶)" if filing else "해당 없음"))
    h.append("<div class='note'>고르는 규칙: 위험 분석 ‘높음’ → 자동 분석 경보 ‘높음’ → 위험 분석 ‘중간’ 순으로 3가지. 나머지 해결방안은 %s.</div>"
             % _go("risk", "부록 A-3"))
    opened = [x for x in L if x["open"]]
    folded = [x for x in L if not x["open"]]
    h.append("<div class='strip'><span>늘 펼침: <b>예측 오차</b></span><span>펼친 영역 <b>%d</b>%s</span><span>접은 영역 <b>%d</b></span>"
             "<span>부록 A·B%s: 지금까지 보고서의 모든 장·표 그대로</span></div>"
             % (len(opened), (": " + " · ".join(esc(x["name"]) for x in opened)) if opened else "", len(folded), "·C" if P else ""))
    h.append("<div class='note'>펼치는 규칙: 지난 보고보다 신호가 나빠졌거나, 해야 할 일에 든 영역. ‘주의’라도 지난번과 같고 할 일이 없으면 접음.</div>")

    # 본문
    h.append("<div class='pgb'></div><h2 id='body'>본문 · 바뀐 것과 할 일 있는 것만</h2>")
    for x in opened:
        facts = x["facts"][:5]
        more = len(x["facts"]) - len(facts)
        h.append("<div class='chap'><div class='hd'>%s %s<span class='r'>%s</span></div><div class='bd'>%s%s<div class='note'>전체 표·근거: %s</div></div></div>"
                 % (esc(x["name"]), _lt(x["lv"], x["changed"], x["before"]), esc(x["sub"] + " · " + x["num"]),
                    ("<ul>%s</ul>" % "".join("<li>%s</li>" % esc(f) for f in facts)) if facts else "<div class='note'>걸린 항목 없음</div>",
                    ("<div class='note'>그 밖 %d건은 부록 A-3</div>" % more) if more > 0 else "", _appx_links(x)))
    full = _track_table(K, False)
    h.append("<div class='chap'><div class='hd'>지난 예상 대비 실제 오차 <span class='lt ok' style='background:#eef3fb;color:var(--accent)'>매번 펼침</span>"
             "<span class='r'>자동 분석 15</span></div><div class='bd'>%s<div class='note'>보고마다 그 뒤 4주·예상 영업이익 오차: %s</div></div></div>"
             % (full or "<div class='note'>지난 보고 기록이 아직 없어 견줄 수 없음</div>", _go("auto", "부록 A-4 (자동 분석 15)")))
    if folded:
        h.append("<div class='q'>접어 둔 영역 (지난번과 같고 할 일 없음)</div><div class='box'>")
        for x in folded:
            h.append("<div class='fold'><span class='t'>%s</span>%s<span class='s'>%s · %s</span>%s</div>"
                     % (esc(x["name"]), _lt(x["lv"], x["changed"], x["before"]), esc(x["num"]), esc(x["sub"]), _appx_links(x)))
        h.append("</div>")
    h.append("</div>")
    return "".join(h)
