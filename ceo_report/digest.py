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
    h.append(guide_box("one", R, I, L))
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
    full = guide_box("track", R, I, L) + _track_table(K, False)
    h.append("<div class='chap'><div class='hd'>지난 예상 대비 실제 오차 <span class='lt ok' style='background:#eef3fb;color:var(--accent)'>매번 펼침</span>"
             "<span class='r'>자동 분석 15</span></div><div class='bd'>%s<div class='note'>보고마다 그 뒤 4주·예상 영업이익 오차: %s</div></div></div>"
             % (full + ("" if _track_table(K, False) else "<div class='note'>지난 보고 기록이 아직 없어 견줄 수 없음</div>"), _go("auto", "부록 A-4 (자동 분석 15)")))
    if folded:
        h.append("<div class='q'>접어 둔 영역 (지난번과 같고 할 일 없음)</div><div class='box'>")
        for x in folded:
            h.append("<div class='fold'><span class='t'>%s</span>%s<span class='s'>%s · %s</span>%s</div>"
                     % (esc(x["name"]), _lt(x["lv"], x["changed"], x["before"]), esc(x["num"]), esc(x["sub"]), _appx_links(x)))
        h.append("</div>")
    h.append("</div>")
    return "".join(h)


# ─────────── 쉬운 설명 · 제안 (사용자 2026-11-13: 요청한 자료는 전부 쉬운 설명과 제안을 붙여 경영관리에서 보이게) ───────────
EXPLAIN = {
    "one": "이 보고서 전체를 한 쪽으로 줄인 곳입니다. 신호등이 노랑·빨강인 곳과 ‘해야 할 일’부터 보면 됩니다.",
    "docs": "지금까지 만들어 달라고 하신 자료가 모두 어디에 있는지 한 표로 모은 곳입니다. 이번 보고에 없는 정기 자료도 마지막 파일로 바로 갈 수 있습니다.",
    "sum": "대표에게 드린 보고 화면을 그대로 둔 곳입니다. 대표가 본 숫자와 똑같은지 확인할 때 봅니다.",
    "ev": "요약 화면의 숫자마다 어디서 나왔는지(근거 번호)와, 사람이 판단해야 할 것(확인할 것)을 모은 곳입니다.",
    "risk": "정해 둔 기준(설정.csv)에 걸린 위험을 ‘높음·중간’으로 나누고, 각각 무엇을 하면 되는지 적은 곳입니다.",
    "auto": "새 자료가 들어올 때마다 프로그램이 장부와 일정을 15가지로 자동 점검한 결과입니다. 맨 위 ‘경보’부터 보면 됩니다.",
    "s1": "지금 통장에 얼마가 있고, 이번 기간에 얼마가 들어오고 나갔는지 보여 줍니다. 정기예금처럼 바로 꺼내 쓸 수 없는 돈은 따로 뺐습니다.",
    "s2": "앞으로 들어올 돈과 나갈 돈을 날짜순으로 놓고 날마다 통장 잔액을 계산한 곳입니다. ‘가장 적을 때’가 늘 남겨 둘 돈(최소 보유현금)보다 낮으면 그때 돈이 모자란다는 뜻입니다.",
    "s3": "프로젝트마다 쓸 수 있는 돈(추정 예산)과 이미 쓴 돈·앞으로 쓸 돈을 견줍니다. 예산을 넘을 것 같은 프로젝트를 일찍 찾는 곳입니다.",
    "s4": "회사·팀·프로젝트가 번 돈(매출)에서 쓴 돈을 빼고 남은 이익입니다. 계산서를 끊어도 돈이 늦게 들어오면 이익과 통장 돈은 다를 수 있습니다.",
    "s5": "계산서를 얼마나 끊었고 그중 아직 못 받은 돈이 얼마인지, 행사가 끝났는데 계산서를 안 끊은 것이 있는지 봅니다.",
    "s6": "프로젝트와 상관없이 나가는 돈(임대료·대출 이자·세금 등)과 아직 갚아야 할 돈을 모은 곳입니다.",
    "s7": "지난 보고 뒤 바뀐 것과, 어떤 자료가 어느 날짜까지 들어갔는지 확인하는 곳입니다. 자료가 오래되면 숫자가 틀릴 수 있습니다.",
    "s8": "위하고 장부와 인트라넷(실행가·지급요청·계산서)을 맞춰 보고 차이를 찾는 곳입니다.",
    "s9": "장부상 이익과 실제 통장 돈이 왜 다른지, 돈이 본업·묶어 둔 돈·빌린 돈 중 어디서 들어오고 나갔는지 보여 줍니다.",
    "c1": "올해 낼 법인세를 장부로 미리 계산하고, 세법상 비용으로 인정되지 않는 것(접대비 한도를 넘은 것 등)을 미리 짚어 봅니다.",
    "c2": "언제 어떤 세금 신고를 해야 하는지(기한)와, 홈택스·위하고에 넣을 값을 장부에서 뽑아 둔 곳입니다.",
    "c3": "급여가 최저임금·4대보험·원천세·수당 규칙에 맞게 처리됐는지 점검하고, 직원 연말정산 결과를 미리 어림합니다.",
    "c4": "지금까지 쌓인 이익(이익잉여금)을 배당할지 회사에 남길지 판단하는 곳입니다. 처분계산서는 그 결정을 적는 양식입니다.",
    "c5": "결산 숫자로 은행·보증기관이 매길 신용등급을 미리 어림하고, 12월 31일 전에 하면 등급에 유리한 일을 알려 줍니다.",
    "gasu": "대표이사가 회사에 잠시 넣어 둔 돈(가수금)을 언제 돌려드려야 통장이 늘 남겨 둘 돈(최소 보유현금) 아래로 내려가지 않는지 날짜별로 계산한 곳입니다.",
    "track": "지난 보고 때 ‘앞으로 이만큼 들어오고 나갈 것’이라고 한 예측이 실제 통장과 얼마나 맞았는지 봅니다. 차이가 크면 자금 예측을 그만큼 덜 믿어야 합니다.",
}
NONE = "이 장에서 걸린 것이 없어 지금 따로 할 일은 없습니다."
GBOX_CSS = ("table.pt.dgx td,table.pt.dgx th{text-align:left!important;white-space:normal!important;vertical-align:top}"
            ".gbox{border:1px solid #c9d6ea;background:#f5f8fd;border-radius:10px;padding:8px 12px;margin:6px 0 10px;font-size:12.5px;break-inside:avoid}"
            ".gbox b.gk{color:var(--accent)}.gbox ul{margin:3px 0 0;padding-left:18px}.gbox li{margin:2px 0}")


def _uniq(xs, n=3):
    out = []
    for x in xs:
        if x and x not in out:
            out.append(x)
    return out[:n]


def track_suggest(K):
    """예측 오차 → 제안 (정해진 기준: 예상 포함 30%, 확정분 10%, 영업이익 30% 넘게 어긋남)."""
    out = []
    ms = (K or {}).get("months") or []
    if ms:
        r = ms[-1]
        i, o = r["in"], r["out"]
        if o["all"] and o["all"] - o["actual"] > o["all"] * 0.3:
            out.append("예상 포함 출금이 실제보다 %.0f%% 많았습니다 → 끝난 프로젝트의 남은 예산·겹친 예상 지급을 정리하면 ‘예상 포함 여유 자금’이 실제에 가까워집니다."
                       % ((o["all"] - o["actual"]) * 100.0 / o["all"]))
        if i["firm"] and i["firm"] - i["actual"] > i["firm"] * 0.1:
            out.append("확정이라던 입금이 %.0f%% 덜 들어왔습니다 → 입금 예정 거래처에 날짜를 다시 확인하고, 늦는 곳은 자금 일정에서 ‘예상’으로 내리세요."
                       % ((i["firm"] - i["actual"]) * 100.0 / i["firm"]))
        if o["firm"] and o["actual"] - o["firm"] > o["firm"] * 0.1:
            out.append("확정 일정에 없던 지급이 %.0f%% 더 나갔습니다 → 지급 요청이 생기면 자금계획서에 바로 넣어 두세요."
                       % ((o["actual"] - o["firm"]) * 100.0 / o["firm"]))
    for p in ((K or {}).get("profit") or [])[-1:]:
        if p.get("actual") is not None and p["forecast"] and abs(p["actual"] - p["forecast"]) > abs(p["forecast"]) * 0.3:
            out.append("%s 예상 영업이익과 지금 장부가 %s원 다릅니다 → 늦게 들어온 전표(카드·매입)가 있는지 확인하세요."
                       % (p["ym"], format(p["actual"] - p["forecast"], ",")))
    if not out and ms:
        out.append("예측과 실제 차이가 기준(예상 포함 30%·확정 10%) 안입니다 → 지금 자금 예측은 믿고 써도 됩니다.")
    return out


def suggest(key, R, I=None, L=None):
    """장마다 제안 (AI 없이 정해진 규칙: 위험 분석의 해결방안·건강 점검·신용평가 할 일·배당 판단 등)."""
    risks = R.get("risks") or []

    def acts(areas_, pred=None):
        return [r["action"] for r in risks if r["area"] in areas_ and (pred is None or pred(r))]
    Ld = dict((x["key"], x) for x in (L or []))
    if key == "one":
        return [a for _, a, _ in todos(R, I)]
    if key == "docs":
        return ["이번 보고에 없는 정기 자료(분기·반기·연간·예산)는 ‘어디서 보나’의 마지막 파일 링크로 열어 보세요."]
    if key == "sum":
        return ["대표 보고에서 질문이 나올 만한 숫자(빨간 글씨·‘예상’)는 근거 번호를 따라 부록 A-2에서 미리 확인해 두세요."]
    if key == "ev":
        return ["‘확인할 것’에 남은 건은 창의 ‘확인할 것’ 화면에서 건마다 결정·메모를 넣으면 다음 보고부터 빠집니다."]
    if key == "risk":
        return _uniq([r["action"] for r in risks], 3)
    if key in ("auto", "track"):
        al = [t for lv, t in ((I or {}).get("alerts") or []) if lv == "높음"] if key == "auto" else []
        return _uniq(al + track_suggest((I or {}).get("track")), 4)
    if key == "s1":
        return _uniq(acts(("자료",), lambda r: "잔액" in r["fact"]))
    if key == "s2":
        return _uniq(acts(("자금",)))
    if key == "gasu":
        from . import gasu
        return gasu.advice(R.get("gasu"))
    if key == "s3":
        return _uniq(acts(("프로젝트",)))
    if key == "s4":
        x = Ld.get("pl")
        if x and x["lv"] == BAD:
            return ["올해 누적이 손실입니다 → 이익률이 가장 낮은 팀·프로젝트부터 원가와 추가 청구 가능 범위를 점검하세요."]
        if x and x["lv"] == WA:
            return ["이번 달이 손실로 보입니다 → 전표가 덜 들어온 ‘잠정’ 달인지 먼저 확인하고, 아니면 큰 비용 항목을 짚어 보세요."]
        return []
    if key == "s5":
        return _uniq(acts(("수금",)))
    if key == "s6":
        x = Ld.get("other")
        return ["지급일·금액이 정해지지 않은 지급은 담당자에게 확정을 요청해 자금 일정에 넣으세요."] if x and x["lv"] != OK else []
    if key == "s7":
        return _uniq(acts(("자료", "지급 관리")))
    if key == "s8":
        X = R.get("xchk") or {}
        if X.get("state") != "ok":
            return ["창에서 ‘자료 변환’을 다시 하면 위하고 대조 자료가 생겨 이 장이 채워집니다."]
        return ["실행가와 장부 원가 차이가 큰 프로젝트는 팀장에게 이유(카드 부가세·늦은 전표·추가 발주)를 확인하세요."]
    if key == "s9":
        CF = R.get("cf")
        if not CF:
            return ["위하고 분개장을 받아 ‘자료 변환’을 하면 현금흐름표가 생깁니다."]
        try:
            from .cashflow import health
            v, hl, rows = health(CF)
        except Exception:
            return []
        out = ["%s: %s" % (q.split(" (")[0], a) for q, a, lv in rows if lv == "warn"]
        return out + ["표 아래 ‘현금흐름을 좋게 하려면’의 할 일을 금액 큰 순서로 하세요."]
    if key == "c1":
        return ["세무조정 예상의 ‘넣음’ 항목은 연말 전에 세무사와 한 번 맞춰 보세요 (법인세 예상이 그만큼 달라집니다)."] if R.get("taxadj") else \
            ["자료 변환을 하면 세무조정 예상(세무조정.csv)이 생깁니다."]
    if key == "c2":
        f = filing_line(R)
        return (["기한이 다가온 신고: %s → 창 ‘신고 도우미’를 열어 칸별 값대로 넣으세요." % " · ".join(f)] if f else
                ["한 달 안에 기한인 신고가 없습니다. 다음 신고는 아래 일정 표의 맨 위 줄입니다."])
    if key == "c3":
        return ["‘이상’ 표시가 있는 직원은 급여 담당과 그달 급여명세를 다시 맞춰 보세요."] if R.get("payroll") else \
            ["위하고 사원등록·급여 자료를 확장으로 받으면 급여 점검이 채워집니다."]
    if key == "c4":
        A = (R.get("re") or {}).get("advice") or {}
        v = A.get("verdict")
        if v == "배당":
            return ["배당 %s원 권장 — 지급일 전에 세무사와 원천세(15.4%%)·이사회 결의 날짜를 정하세요." % format(A.get("amount") or 0, ",")]
        if v == "이월":
            return ["이번엔 이월(회사에 남김) 권장 — 자금 사정이 나아지면 다음 반기에 다시 판단합니다."]
        if v == "보류":
            return ["판단 보류 — 아래 체크리스트의 ‘꼭 넣을 값(✗)’을 창 ‘배당 판단 질문’에서 채우세요."]
        return ["위하고 분개장(작년 포함)을 받아 ‘자료 변환’을 하면 처분계산서가 채워집니다."]
    if key == "c5":
        C = R.get("credit") or {}
        return _uniq(["%s" % t for t, b, e in (C.get("todo") or [])], 4) or ["창 ‘신용평가 체크리스트’를 채우면 등급 범위가 좁아집니다."]
    return []


def guide_box(key, R, I=None, L=None):
    """장 맨 위 ‘쉬운 설명 · 제안’ 상자. 숫자 비교 시험이 뺄 수 있게 gbox 표시로 감싼다."""
    if key not in EXPLAIN:
        return ""
    sg = suggest(key, R, I, L)
    return ("<style>%s</style><div class='gbox'><div><b class='gk'>쉬운 설명</b> %s</div><div style='margin-top:4px'><b class='gk'>제안</b>%s</div></div><!-- /gbox -->"
            % (GBOX_CSS, esc(EXPLAIN[key]),
               ("<ul>%s</ul>" % "".join("<li>%s</li>" % esc(s) for s in sg)) if sg else " " + esc(NONE)))


# ─────────── 자료 안내 (요청한 자료 전부, 사용자 2026-11-13) ───────────
def find_docs(out_dir, asof):
    """출력 폴더에서 따로 만드는 자료의 마지막 파일 -> {이름: 경영관리 보고 기준 상대 경로}."""
    found = {}

    def newest(folder, pat, sub=""):
        try:
            names = [n for n in os.listdir(folder) if re.match(pat, n)]
        except OSError:
            return None
        return (sub + sorted(names)[-1]) if names else None
    found["budget"] = newest(os.path.join(out_dir, "예산"), r"^\d{4}_예산_경영관리용\.html$", "예산/")
    found["annual"] = newest(out_dir, r"^\d{4}_연간_경영관리보고\.html$")
    found["team"] = newest(os.path.join(out_dir, "팀장용"), r"^\d{4}-\d{2}-\d{2}_월간_팀장_.*\.html$", "팀장용/")
    try:
        names = os.listdir(out_dir)
    except OSError:
        names = []
    for k, months in (("q", (3, 6, 9, 12)), ("h", (6, 12)), ("prep", (9,))):
        cand = []
        for n in names:
            m = re.match(r"^(\d{4})-(\d{2})-(\d{2})_월간_경영관리보고\.html$", n)
            if m and int(m.group(2)) in months and dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) < asof:
                cand.append(n)
        found[k] = sorted(cand)[-1] if cand else None
    return found


def docs_section(R, I, L):
    P = periodic(R)
    F = R.get("docs_files") or {}
    mon = R.get("kind") == "monthly"

    def here(k, lab):
        return "<a class='go' href='#a-%s'>%s</a>" % (k, esc(lab))

    def file(k, lab):
        p = F.get(k)
        return ("<a class='go' href='%s'>%s</a>" % (esc(p), esc(lab + " (" + p.split("/")[-1].split("_")[0] + ")"))) if p else None

    def periodic_where(code, key, area, lab, gone_txt):
        if code in P:
            return here(area, lab), "이번 보고에 있음", suggest(area, R, I, L)
        f = file(code, "마지막 %s 보고" % gone_txt)
        return (f or esc("아직 만든 %s 보고 없음" % gone_txt)), esc("%s분 보고에 들어감" % gone_txt), []
    rows = []

    def add(name, where, state, sg, explain):
        rows.append("<tr><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                    % (esc(name), where, state, esc(explain), "<br>".join(esc(x) for x in sg[:2]) if sg else esc("지금 걸린 것 없음 — 할 일 없음")))
    yes = "<span class='lt ok'><i></i>있음</span>"
    add("1쪽 요약·신호등·해야 할 일", here("one", "1쪽 요약"), yes, suggest("one", R, I, L), EXPLAIN["one"])
    add("대표 보고 (주간·월간, 출금 목록)", here("sum", "부록 A-1"), yes, suggest("sum", R, I, L), EXPLAIN["sum"])
    add("자동 분석 15가지 (꼭 나갈 돈·계산서 기한 포함)", here("auto", "부록 A-4"), yes, suggest("auto", R, I, L), EXPLAIN["auto"])
    add("가용금액 예측 오차 (지난 예상 대비 실제)", here("one", "1쪽·본문") + " · " + here("auto", "A-4 15번"), yes,
        track_suggest((I or {}).get("track")), EXPLAIN["track"])
    for i, nm in ((1, "현재 자금·입출금"), (2, "입금·지급 일정"), (3, "프로젝트 예산·집행"), (4, "매출·손익"), (5, "계산서·수금"),
                  (6, "프로젝트 밖 지급"), (7, "변동·자료 범위")):
        add(nm, here("s%d" % i, "부록 B-%d" % i), yes, suggest("s%d" % i, R, I, L), EXPLAIN["s%d" % i])
    if "gasu" in R:   # 사용자 2026-11-13
        add("가수금 갚을 시기 (확정분만·예상 포함)", here("gasu", "부록 B-2-1"), yes, suggest("gasu", R, I, L), EXPLAIN["gasu"])
    if mon:
        add("위하고 대조·실행가 차이", here("s8", "부록 B-8"), yes, suggest("s8", R, I, L), EXPLAIN["s8"])
        add("현금흐름표 (쉬운 풀이·회사 상태·개선 할 일)", here("s9", "부록 B-9"), yes, suggest("s9", R, I, L), EXPLAIN["s9"])
    else:
        add("위하고 대조·현금흐름표", esc("월간 경영관리 보고 부록 B-8·B-9"), esc("월간에만"), [], EXPLAIN["s9"])
    add("법인세 예상", here("sum", "부록 A-1 누적 절") if mon else esc("월간 보고 A-1"), yes if mon else esc("월간에만"), [],
        "올해 장부 이익으로 미리 계산한 법인세입니다 (감가상각비·대손충당금 예상 반영).")
    for code, area, nm, lab, gone in (("q", "c1", "세무조정 예상", "부록 C-1", "분기(3·6·9·12월)"),
                                      ("q", "c2", "신고 일정·신고 도우미", "부록 C-2", "분기(3·6·9·12월)"),
                                      ("q", "c3", "급여 점검·연말정산 예상", "부록 C-3", "분기(3·6·9·12월)"),
                                      ("h", "c4", "이익잉여금처분계산서·배당 판단·감면 후보", "부록 C-4", "반기(6·12월)"),
                                      ("prep", "c5", "기업신용평가 미리보기·결산 전 할 일", "부록 C-5", "결산 준비(9월)")):
        w, st, sg = periodic_where(code, nm, area, lab, gone)
        if area == "c5" and R.get("credit_brief"):   # 신용평가 최근 결과 한 줄 (사용자 2026-11-13)
            sg = ["최근 결과: " + R["credit_brief"]] + list(sg)
        add(nm, w, yes if code in P else st, sg[:1] if area != "c5" else sg[:2], EXPLAIN[area])
    add("신고 도우미 (홈택스·위하고 칸별 값)", esc("창 ‘신고 도우미’"), esc("창에서 늘"), suggest("c2", R, I, L), EXPLAIN["c2"])
    add("연간 보고 (이익잉여금 8장·신용평가 9장 포함)", file("annual", "마지막 연간 경영관리 보고") or esc("창 3단계 ‘연간 보고’로 만듦"),
        esc("따로 만듦 (결산 뒤)"), [], "한 해 손익·현금흐름·처분계산서·신용평가를 결산 숫자로 묶은 보고입니다.")
    add("내년 예산 (대표용·경영관리용)", file("budget", "마지막 예산 경영관리용") or esc("창 ‘예산 초안 만들기’로 만듦"),
        esc("따로 만듦"), ["예산을 확정하면 월간 보고 A-1 누적 절에 ‘예산 대비’ 표가 붙습니다."],
        "팀별 성장률·인원·인상률로 내년 매출·비용·이익을 미리 짠 초안입니다.")
    add("팀장용 팀 실적", file("team", "마지막 팀장용") or esc("월간 보고 때 출력\\팀장용 에 생김"),
        esc("월간 보고 때 함께"), [], "팀마다 이번 달 매출·이익·진행 프로젝트 예산을 보여 주는 팀장 전달용 문서입니다 (급여 금액 없음).")
    add("세법 기준 확인 (해마다)", esc("창 ‘세법 기준 확인’"), esc("1·7월 자동 확인"), [],
        "세율·공제 금액이 바뀌었는지 법령 조문을 받아 확인하고, 확인 안 된 값은 계산에서 ‘확인 필요’로 둡니다.")
    return ("<style>%s</style><div class='dg1'><h2 id='docs'>자료 안내 · 요청하신 자료 전부</h2>%s"
            "<div class='tw'><table class='pt evt dgx nofold'><thead><tr><th>자료</th><th>어디서 보나</th><th>이번 보고</th><th>쉬운 설명</th><th>제안</th></tr></thead>"
            "<tbody>%s</tbody></table></div>"
            "<div class='note'>새 자료를 만들 때마다 이 표에 한 줄씩 더하고, 그 장 맨 위에 ‘쉬운 설명 · 제안’ 상자를 붙입니다 (사용자 2026-11-13).</div></div>"
            % (CSS, guide_box("docs", R, I, L), "".join(rows)))


# ─────────── 연간 경영관리 보고에도 같은 상자 (사용자 2026-11-13) ───────────
ANNUAL_EXPLAIN = {
    "sum": "대표에게 드린 연간 보고 화면 그대로입니다. 한 해 매출·이익·현금과 내년 목표를 한눈에 봅니다.",
    "risk": "한 해 숫자에서 정해 둔 기준에 걸린 것(거래처 쏠림·늦은 입금·목표 미달·적자 프로젝트·빨리 늘어난 비용)과 할 일입니다.",
    "d1": "달마다 번 돈과 쓴 돈, 연말 결산(감가상각비·법인세) 뒤 남는 이익입니다.",
    "d2": "석 달씩 묶어 매출·이익이 어느 분기에 몰렸는지 봅니다.",
    "d3": "통장에 들어오고 나간 돈을 달마다 봅니다. 이익과 통장 돈의 차이를 보는 곳입니다.",
    "d4": "어느 거래처에서 매출이 얼마나 나왔는지, 한두 곳에 너무 몰리지 않았는지 봅니다.",
    "d5": "팀·프로젝트별 실적과 회사 운영비(판관비)가 어디에 쓰였는지 봅니다.",
    "d6": "내년 팀 목표와 이미 받은 일을 견줘, 내년 준비가 얼마나 됐는지 봅니다.",
    "d7": EXPLAIN["s9"],
    "d8": EXPLAIN["c4"],
    "d9": EXPLAIN["c5"],
}
ANNUAL_AREA = {"d4": ("거래처", "수금"), "d5": ("팀", "프로젝트", "비용"), "d1": ("자료",)}


def annual_box(key, A, risks):
    if key not in ANNUAL_EXPLAIN:
        return ""
    if key in ("sum", "risk"):
        sg = _uniq([r[3] for r in risks if r[0] == "높음"] + [r[3] for r in risks], 3)
    elif key == "d7":
        sg = suggest("s9", {"cf": A.get("cfs")})
    elif key == "d8":
        sg = suggest("c4", {"re": A.get("re")})
    elif key == "d9":
        sg = suggest("c5", {"credit": A.get("credit")})
    else:
        sg = _uniq([r[3] for r in risks if r[1] in ANNUAL_AREA.get(key, ())], 3)
    return ("<style>%s</style><div class='gbox'><div><b class='gk'>쉬운 설명</b> %s</div><div style='margin-top:4px'><b class='gk'>제안</b>%s</div></div><!-- /gbox -->"
            % (GBOX_CSS, esc(ANNUAL_EXPLAIN[key]),
               ("<ul>%s</ul>" % "".join("<li>%s</li>" % esc(s) for s in sg)) if sg else " " + esc(NONE)))


# ─────────── 내년 예산 경영관리용에도 같은 상자 (사용자 2026-11-13) ───────────
BUDGET_EXPLAIN = (
    ("요약", "내년 한 해 매출·비용·이익과 통장 돈이 어떻게 될지 미리 짠 초안을 한 쪽으로 줄인 곳입니다.",
     "팀장들과 성장률·늘릴 인원·인상률 가정을 한 번 맞춘 뒤 창에서 ‘예산 확정’을 누르면, 월간 보고에 ‘예산 대비’ 표가 붙습니다."),
    ("정해야 할 값", "예산을 짜는 데 쓴 가정(팀별 성장률·인원·급여·물가 인상률)입니다. 이 값만 바꾸면 아래 숫자가 모두 다시 계산됩니다.",
     "‘입력값’ 표시 칸이 비었거나 작년과 크게 다르면 창 ‘가끔 넣는 값’의 ‘내년 예산’에서 고치세요."),
    ("손익 예산", "위하고 손익계산서와 같은 순서로 내년 매출·원가·판관비·이익을 늘어놓은 표입니다.",
     "영업이익률이 팀 목표 수익률보다 낮으면 판관비 줄 중 가장 크게 늘어난 것부터 다시 보세요."),
    ("팀별 매출", "팀마다 내년에 벌 돈과 그 일을 하는 데 드는 돈(원가)입니다. 이미 받은 사전견적도 함께 봅니다.",
     "사전견적으로 이미 채운 비율이 낮은 팀은 상반기 영업 계획을 팀장과 따로 잡으세요."),
    ("급여", "직원 급여와 회사 운영비(판관비)를 계정마다 얼마로 잡았는지 보여 줍니다.",
     "늘릴 인원의 입사 월이 이르면 비용이 커집니다. 채용 시기를 월간 자금 계획과 같이 보세요."),
    ("정해진 지급", "세금·대출 이자처럼 날짜가 정해진 지급을 달마다 놓은 곳입니다.",
     "큰 세금(법인세 3월, 부가세 1·4·7·10월)이 몰리는 달 앞에는 통장 돈을 넉넉히 남겨 두세요."),
    ("월별 자금", "달마다 들어올 돈과 나갈 돈으로 통장 잔액을 미리 그려, 최소 보유현금 아래로 내려가는 달이 있는지 봅니다.",
     "잔액이 최소 보유현금 아래로 내려가는 달이 있으면, 그 앞달에 대금 회수를 앞당기거나 지급을 미루는 계획을 세우세요."),
    ("쓴 자료", "예산을 만들 때 쓴 자료와, 자료가 모자라 확인이 필요한 것입니다.",
     "‘확인 필요’ 줄의 자료를 넣고 예산 초안을 다시 만들면 숫자가 정확해집니다."),
)


def budget_box(label):
    for k, ex, sg in BUDGET_EXPLAIN:
        if k in label:
            return ("<style>%s</style><div class='gbox'><div><b class='gk'>쉬운 설명</b> %s</div><div style='margin-top:4px'><b class='gk'>제안</b> %s</div></div><!-- /gbox -->"
                    % (GBOX_CSS, esc(ex), esc(sg)))
    return ""
