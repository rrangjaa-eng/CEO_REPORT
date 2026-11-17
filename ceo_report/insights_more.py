"""자동 분석 16~23 (2026-11-17 저녁 제안 M3·A1~A8, 사용자 '추가 기능은 전부'·'전부 고치기').

경영관리 보고에만 싣는다 (11/17 규칙: 대표·팀장 PDF 항목은 그대로). 숫자는 이미 계산된 R(보고서 계산 결과)에서만 가져오고,
보고의 여유 자금·세금·이익 계산은 바꾸지 않는다 (A6 가정 계산도 저장하지 않음).
  16 M3  계산서 → 입금 걸린 날 (60일 가정 다시 재기)        20 A4 법인세 분납하면
  17 A1  앞으로 6달 확보한 일감 vs 고정비                     21 A5 당분간 안 쓸 돈과 예금 이자
  18 A2  손익분기 매출 · 목표까지 매달 필요한 매출            22 A7 퇴직금 합계
  19 A3  고객사별 이익                                        23 A8 비용 급증 알림
가정은 표마다 쓰고(11/15 가정 표시 규칙), 자료가 모자라면 숫자를 지어내지 않고 '모름'으로 둔다.
"""
import collections
import datetime as dt
import math

DAY = dt.timedelta(days=1)
COLLECT_DAYS = 60           # 사용자 2026-11-12: 매출 계산서는 대부분 작성일 뒤 60일쯤 입금 (insights.PAY_AFTER_ISSUE 와 같음)
COLLECT_GAP = 10            # 가운데 값이 60일과 이만큼 넘게 벌어지면 할 일 (제안 M3)
COHORT = (91, 182)          # 석 달 전~여섯 달 전에 발행한 계산서: 모두 90일 넘게 지나 들어왔는지가 거의 정해진 것
COHORT_MIN = 5              # 이보다 적으면 재지 않음
PIPE_MONTHS = 6             # A1
SPIKE_RATE, SPIKE_MIN = 1.5, 3_000_000   # A8: 최근 3달 평균의 1.5배 넘고 300만 원 넘게 늘어남
IDLE_WINDOWS = (3, 6)       # A5: 달


# ───────────── 공통 ─────────────
def _month_end(d):
    return (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - DAY


def _last_full(asof):
    """끝난 마지막 달 'YYYY-MM' (기준일이 말일이면 그 달)."""
    if asof == _month_end(asof):
        return asof.strftime("%Y-%m")
    p = asof.replace(day=1) - DAY
    return p.strftime("%Y-%m")


def _add_months(ym, k):
    y, m = int(ym[:4]), int(ym[5:7]) + k
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return "%04d-%02d" % (y, m)


def _day(v):
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v or "").strip()[:10])
    except ValueError:
        return None


def company_months(R):
    """회사 전체 달별 손익 {ym: {revenue, direct, common}} (보고서 실적 칸과 같은 손익.csv 회사 줄)."""
    src = ((R.get("s4") or {}).get("sources") or {}).get("WEHAGO") or {}
    out = {}
    for ym, rows in src.get("by_month") or []:
        for r in rows:
            if r.get("unit") == "회사" and r.get("cur"):
                out[ym] = r["cur"]
    return out


def fixed_cost(R):
    """월 고정비 어림 = 끝난 최근 3달 판관비(공통비) 평균 -> (금액, [달]) 또는 (None, [])."""
    cm = company_months(R)
    last = _last_full(R["asof"])
    ms = [m for m in sorted(cm) if m <= last and cm[m].get("common") is not None][-3:]
    if not ms:
        return None, []
    return int(round(sum(cm[m]["common"] for m in ms) / float(len(ms)))), ms


def gp_rate(R):
    """매출총이익률 = 끝난 최근 3달 (매출 − 원가) ÷ 매출. 매출이 없거나 0 이하면 올해 누적 -> (비율, 설명) 또는 (None, 까닭)."""
    cm = company_months(R)
    last = _last_full(R["asof"])
    ok = [m for m in sorted(cm) if m <= last and cm[m].get("revenue") is not None and cm[m].get("direct") is not None]
    for ms, lab in ((ok[-3:], "최근 %d달"), ([m for m in ok if m[:4] == last[:4]], "올해 %d달 누적")):
        rev = sum(cm[m]["revenue"] for m in ms)
        gp = rev - sum(cm[m]["direct"] for m in ms)
        if rev > 0 and gp > 0:
            return gp / float(rev), (lab % len(ms)) + " (%s~%s)" % (ms[0], ms[-1])
    return None, "끝난 달 매출총이익이 0 이하이거나 매출 자료 없음"


# ───────────── 16 M3 계산서 → 입금 걸린 날 ─────────────
def _pct(sorted_vals, p):
    if not sorted_vals:
        return None
    i = max(int(math.ceil(p * len(sorted_vals))) - 1, 0)
    return sorted_vals[i]


def collect_days(R):
    """석 달 전~여섯 달 전에 발행한 매출 계산서가 들어오기까지 걸린 날 -> dict 또는 None (계산서가 적음).
    아직 못 받은 계산서는 '아주 늦음'으로 세어(빼면 빨리 들어온 쪽으로 치우침, 1차 C15) 가운데·75%·90% 값을 잰다."""
    asof = R["asof"]
    lo, hi = asof - dt.timedelta(days=COHORT[1]), asof - dt.timedelta(days=COHORT[0])
    vals, open_n, rows = [], 0, []
    for r in R.get("_invoices") or []:
        d = r.get("date")
        if r.get("kind", "발행") != "발행" or not d or not (lo <= d <= hi) or (r.get("supply") or 0) <= 0:
            continue
        p = r.get("paid_date")
        if p and d <= p <= asof:
            vals.append((p - d).days)
        else:
            vals.append(float("inf"))
            open_n += 1
        rows.append(r)
    if len(vals) < COHORT_MIN:
        return {"n": len(vals), "from": lo, "to": hi, "enough": False}
    vals.sort()
    med, p75, p90 = _pct(vals, 0.5), _pct(vals, 0.75), _pct(vals, 0.9)
    gap = None if med == float("inf") else med - COLLECT_DAYS
    off = med == float("inf") or abs(gap) > COLLECT_GAP
    return {"n": len(vals), "from": lo, "to": hi, "enough": True, "median": med, "p75": p75, "p90": p90, "open": open_n,
            "gap": gap, "off": off}


def _days(v):
    return "아직 못 받음" if v == float("inf") else "%d일" % v


# ───────────── 17 A1 6달 일감 vs 고정비 / 18 A2 손익분기 ─────────────
def _proj_profit(p):
    """프로젝트 예상 매출총이익: 지금 예상 이익(끝난 건 쓴 돈, 진행 중은 추정 예산까지 나갈 돈 뺌) -> (매출 기준, 이익) 또는 (None, None)."""
    pb = p.get("profit_basis")
    pr = p.get("profit_now") if p.get("profit_now") is not None else p.get("profit_end")
    return pb, pr


def pipeline(R):
    """앞으로 6달 행사 달별 이미 받은 일의 매출·예상 이익과 월 고정비 -> dict."""
    asof = R["asof"]
    start = asof.strftime("%Y-%m") if asof != _month_end(asof) else _add_months(asof.strftime("%Y-%m"), 1)
    months = [_add_months(start, k) for k in range(PIPE_MONTHS)]
    fixed, fms = fixed_cost(R)
    by = collections.OrderedDict((m, {"ym": m, "n": 0, "sales": 0, "gp": 0, "unknown": 0, "names": []}) for m in months)
    for p in (R.get("s3") or {}).get("projects") or []:
        if p.get("closed"):
            continue
        d = _day(p.get("event_date"))
        if not d or d.strftime("%Y-%m") not in by:
            continue
        b = by[d.strftime("%Y-%m")]
        pb, pr = _proj_profit(p)
        b["n"] += 1
        b["names"].append("[%s] %s" % (p.get("id"), p.get("name")))
        if pb is None or pr is None:
            b["unknown"] += 1
            continue
        b["sales"] += pb
        b["gp"] += pr
    rows = list(by.values())
    for b in rows:
        b["cover"] = None if not fixed else b["gp"] / float(fixed)
    return {"rows": rows, "fixed": fixed, "fixed_months": fms}


def breakeven(R):
    """손익분기 월 매출 = 월 고정비 ÷ 매출총이익률, 올해 목표까지 남은 달 매달 필요한 매출 -> dict."""
    asof = R["asof"]
    fixed, fms = fixed_cost(R)
    rate, how = gp_rate(R)
    be = None if not fixed or not rate else int(round(fixed / rate))
    cm = company_months(R)
    ytd = sum((cm[m].get("revenue") or 0) for m in cm if m[:4] == str(asof.year) and m <= asof.strftime("%Y-%m"))
    tg = R.get("targets") or {}
    target = sum((v or {}).get("revenue") or 0 for v in tg.values()) or None
    done_month = asof == _month_end(asof)
    left = 12 - asof.month + (0 if done_month else 1)
    need = None if not target or left <= 0 else max(int(round((target - ytd) / float(left))), 0)
    last3 = [cm[m]["revenue"] for m in sorted(cm) if m <= _last_full(asof) and cm[m].get("revenue") is not None][-3:]
    avg3 = int(round(sum(last3) / float(len(last3)))) if last3 else None
    return {"fixed": fixed, "fixed_months": fms, "rate": rate, "rate_how": how, "be": be, "target": target, "ytd": ytd,
            "left": left, "need": need, "avg3": avg3}


# ───────────── 19 A3 고객사별 이익 ─────────────
def clients(R, top=12):
    """올해 행사 프로젝트를 고객사별로 묶은 매출 기준·예상 이익 -> {'rows': [...], 'rate': 회사 평균}.
    고객은 매출 계산서 거래처코드로 묶고(E3, 계산-01), 코드가 없는 프로젝트만 인트라넷 고객 이름으로."""
    asof = R["asof"]
    code_of = collections.defaultdict(collections.Counter)
    name_of = {}
    for r in R.get("_invoices") or []:
        c = (r.get("client_code") or "").strip()
        if r.get("project") and c and r.get("kind", "발행") == "발행":
            code_of[r["project"]][c] += 1
            name_of[c] = r.get("client") or name_of.get(c, "")
    g = collections.OrderedDict()
    for p in (R.get("s3") or {}).get("projects") or []:
        d = _day(p.get("event_date"))
        if not d or d.year != asof.year:
            continue
        pb, pr = _proj_profit(p)
        if pb is None or pr is None:
            continue
        cc = code_of.get(p.get("id"))
        if cc:
            c = cc.most_common(1)[0][0]
            key, lab = ("c", c), "%s [%s]" % (name_of.get(c) or p.get("client") or "", c)
        else:
            key, lab = ("n", p.get("client") or "(고객 모름)"), (p.get("client") or "(고객 모름)") + " (코드 없음)"
        x = g.setdefault(key, {"label": lab, "n": 0, "sales": 0, "gp": 0})
        x["n"] += 1
        x["sales"] += pb
        x["gp"] += pr
    rows = sorted(g.values(), key=lambda x: -x["sales"])
    tot_s, tot_g = sum(x["sales"] for x in rows), sum(x["gp"] for x in rows)
    avg = tot_g / float(tot_s) if tot_s > 0 else None
    for x in rows:
        x["rate"] = x["gp"] / float(x["sales"]) if x["sales"] > 0 else None
        # 매출이 큰 쪽(위 절반)인데 수익률이 회사 평균보다 10%p 넘게 낮으면 표시
        x["low"] = bool(avg is not None and x["rate"] is not None and x["rate"] < avg - 0.10)
    return {"rows": rows[:top], "more": max(len(rows) - top, 0), "rate": avg, "sales": tot_s, "gp": tot_g}


# ───────────── 20 A4 법인세 분납 ─────────────
def installment(R):
    """올해 법인세(본 줄 + 남은 달 예상) 3월 말 합계와 분납하면 나뉘는 금액 -> dict 또는 None."""
    from .corptax import installable, inst_due
    y = R["asof"].year
    rows = [t for t in R.get("tax") or [] if t.get("kind") == "법인세" and t.get("due") and t.get("amount")
            and str(t.get("period") or "").startswith("%d년 " % y) and t["due"].month in (3, 4)]
    if not rows:
        return None
    total = sum(t["amount"] for t in rows)
    due = min(t["due"] for t in rows)
    s = installable(total)
    chosen = any(t.get("inst") for t in rows)
    return {"total": total, "due": due, "inst": s, "inst_due": inst_due(due) if s else None, "first": total - s, "chosen": chosen,
            "planned": any(t.get("matched") and not (isinstance(t["matched"], dict) and t["matched"].get("rest_in_plan")) for t in rows)}


# ───────────── 21 A5 당분간 안 쓸 돈 ─────────────
def idle_cash(R, rate=None):
    """앞으로 3·6달 날마다 잔액 중 가장 낮은 값 − 최소 보유현금 = 그 기간 안 쓸 돈 (자금계획서가 닿는 데까지만).
    잔액은 확정분 선과 예상 포함 선 중 낮은 쪽 (보수적). rate(연 금리)가 있으면 그 기간 이자 어림."""
    from .insights import calendar, _plan_end
    asof = R["asof"]
    s2 = R["s2"]
    if s2.get("start") is None or s2.get("out_missing") or s2.get("min_cash") is None:
        return None
    pend = _plan_end(R)
    if pend is None:   # 자금계획서를 안 썼으면 보고의 가장 긴 기간 끝까지만 (그 뒤 일정은 없어 잔액이 부풀려짐)
        ends = [p["end"] for p in s2.get("periods") or [] if p.get("label") != "지정일"]
        pend = max(ends) if ends else asof
    out = []
    for mo in IDLE_WINDOWS:
        ym = _add_months(asof.strftime("%Y-%m"), mo)
        end = _month_end(dt.date(int(ym[:4]), int(ym[5:]), 1))
        if asof != _month_end(asof):   # 달 중간이면 오늘부터 mo달 뒤 같은 날까지
            end = min(end, asof + dt.timedelta(days=31 * mo))
        short = pend < end
        upto = pend if short else end
        days = (upto - asof).days
        if days <= 0:
            out.append({"months": mo, "upto": upto, "short": True, "idle": None})
            continue
        cal = calendar(R, days)
        low = min(min(c["firm"], c["all"]) for c in cal) if cal else None
        low_day = min(cal, key=lambda c: min(c["firm"], c["all"]))["date"] if cal else None
        idle = None if low is None else max(low - s2["min_cash"], 0)
        interest = None if idle is None or not rate else int(idle * rate * days / 365.0)
        out.append({"months": mo, "upto": upto, "short": short, "low": low, "low_day": low_day, "idle": idle, "interest": interest})
    return {"rows": out, "rate": rate, "min_cash": s2["min_cash"], "plan_end": pend}


# ───────────── 23 A8 비용 급증 ─────────────
def cost_spikes(R):
    """판관비·영업외비용 계정 중 끝난 마지막 달이 앞 3달 평균의 1.5배 넘고 300만 원 넘게 늘어난 것 -> [dict]."""
    A = R.get("acct_year") or {}
    last = _last_full(R["asof"])
    if A.get("state") != "ok" or str(A.get("year")) != last[:4]:
        return None
    mi = int(last[5:]) - 1
    if mi < 1:
        return []
    out = []
    for g in A.get("groups") or []:
        if g["name"] not in ("판매비와관리비", "영업외비용"):
            continue   # 원가는 행사마다 크게 달라 급증이 정상 (프로젝트 이익 흐름으로 봄)
        for a in g["accounts"]:
            cur = a["months"][mi]
            prev = [v for v in a["months"][max(mi - 3, 0):mi] if v is not None]
            if cur is None or not prev:
                continue
            avg = sum(prev) / float(len(prev))
            if cur - avg >= SPIKE_MIN and (avg <= 0 or cur > SPIKE_RATE * avg):
                out.append({"group": g["name"], "code": a["code"], "name": a["name"], "ym": last, "cur": cur, "avg": int(round(avg)),
                            "up": int(round(cur - avg)), "times": None if avg <= 0 else cur / avg})
    return sorted(out, key=lambda x: -x["up"])


# ───────────── 모음 · 할 일 ─────────────
def compute(R):
    ch = R.get("fund_choices") or {}
    rate = None
    try:
        v = float(str(ch.get("예금금리") or "").replace("%", ""))
        rate = v / 100.0 if 0 < v <= 30 else None
    except ValueError:
        rate = None
    out = {}
    for k, fn in (("collect", lambda: collect_days(R)), ("pipeline", lambda: pipeline(R)), ("breakeven", lambda: breakeven(R)),
                  ("clients", lambda: clients(R)), ("inst", lambda: installment(R)), ("idle", lambda: idle_cash(R, rate)),
                  ("spikes", lambda: cost_spikes(R))):
        try:
            out[k] = fn()
        except Exception as e:   # 한 분석이 실패해도 다른 분석·보고서는 만든다
            out[k] = {"error": "%s: %s" % (type(e).__name__, str(e)[:100])}
    out["severance"] = R.get("severance")
    return out


def add_risks(R):
    """경영관리 '할 일'(위험 분석)에 줄을 더한다 — M3 (11/15 가정 규칙 '분기마다 다시 재기'), A8. 대표 보고 숫자는 바꾸지 않음."""
    rs = R.setdefault("risks", [])
    try:
        c = collect_days(R)
    except Exception:
        c = None
    if c and c.get("enough") and c["off"]:
        rs.append({"level": "중간", "area": "수금",
                   "fact": "매출 계산서 입금이 '작성일 뒤 %d일' 가정과 다름: %s~%s 발행 %d건의 가운데 값 %s (75%% %s, 90%% %s, 아직 못 받은 %d건)."
                           % (COLLECT_DAYS, c["from"].isoformat(), c["to"].isoformat(), c["n"], _days(c["median"]), _days(c["p75"]),
                              _days(c["p90"]), c["open"]),
                   "action": "가운데 값이 60일과 %d일 넘게 벌어졌습니다. 늦게 주는 거래처를 확인하고(자동 분석 '거래처별 입금 습관'), "
                             "60일 가정을 바꿀지 정해 주세요. 바꾸기 전까지 입금 예상은 60일 그대로입니다." % COLLECT_GAP})
    try:
        sp = cost_spikes(R) or []
    except Exception:
        sp = []
    if sp:
        rs.append({"level": "중간", "area": "자료",
                   "fact": "%s 비용이 최근 3달 평균보다 크게 늘어난 계정 %d개: %s." % (sp[0]["ym"], len(sp), ", ".join(
                       "%s %s원(평균 %s원)" % (x["name"], "{:,}".format(x["cur"]), "{:,}".format(x["avg"])) for x in sp[:3])),
                   "action": "위하고 계정별원장에서 그 달 전표를 보고 한 번만 나간 돈인지, 잘못 넣은 계정인지 확인해 주세요."})
    return R


# ───────────── A6 '이렇게 하면?' 가정 계산 (저장 안 함) ─────────────
WHATIF_KINDS = ("매달 지출", "한 번 지출", "한 번 입금", "입금 늦춤(일)")


def whatif(R, kind, amount, start):
    """가정 하나를 일정에 넣어 본 여유 자금 -> [(기간, 지금 확정분, 바뀐 확정분, 지금 예상 포함, 바뀐 예상 포함)] 또는 까닭(글).
    보고의 일정·숫자는 바꾸지 않는다 (승인 검토와 같은 available_periods 계산)."""
    from .calc import available_periods
    from .insights import _ends
    s2 = R["s2"]
    ends = _ends(R)
    if not ends or s2.get("start") is None or s2.get("out_missing"):
        return "잔액 또는 지급 자료가 없어 계산하지 못함"
    if kind not in WHATIF_KINDS:
        return "종류를 고르세요"
    if not amount or amount <= 0:
        return "금액(늦춤은 일 수)을 0보다 크게 넣으세요"
    start = start or R["asof"] + DAY
    dated = list(s2.get("dated") or [])
    last = max(e for _, e in ends)
    if kind == "매달 지출":
        d = start
        while d <= last:
            dated.append({"date": d, "io": "out", "amount": int(amount), "firm": True, "desc": "가정: 매달 지출", "cat": "가정"})
            y, m = d.year + (d.month == 12), d.month % 12 + 1
            d = dt.date(y, m, min(start.day, (dt.date(y + (m == 12), m % 12 + 1, 1) - DAY).day))
    elif kind in ("한 번 지출", "한 번 입금"):
        dated.append({"date": start, "io": "out" if kind == "한 번 지출" else "in", "amount": int(amount), "firm": True,
                      "desc": "가정: " + kind, "cat": "가정"})
    else:
        n = int(amount)
        dated = [dict(e, date=e["date"] + dt.timedelta(days=n)) if e["io"] == "in" and e["date"] >= start else e for e in dated]
    base = available_periods(s2["start"], s2.get("dated") or [], ends, s2.get("min_cash"), R["asof"])
    new = available_periods(s2["start"], dated, ends, s2.get("min_cash"), R["asof"])
    return [(b["label"], b["firm"]["avail"], n_["firm"]["avail"], b["all"]["avail"], n_["all"]["avail"]) for b, n_ in zip(base, new)]


# ───────────── 그리기 ─────────────
def render(X, R, sub):
    """mgmt_section 의 sub(번호, 제목, 본문)으로 16~23을 더한다."""
    from .insights_render import _tbl, _none, W, S, esc

    def P(v):
        return "-" if v is None else "%.1f%%" % (v * 100)

    def err(x):
        return isinstance(x, dict) and x.get("error")
    # 16 M3
    c = X.get("collect")
    if err(c):
        body = _none("계산하지 못함 (%s)" % c["error"])
    elif not c or not c.get("enough"):
        body = _none("%s~%s에 발행한 매출 계산서가 %d건뿐이라 재지 않음 (%d건 이상일 때)" % (
            (c or {}).get("from", "-"), (c or {}).get("to", "-"), (c or {}).get("n", 0), COHORT_MIN))
    else:
        body = _tbl(["발행한 때", "건수", "가운데 값", "75%", "90%", "아직 못 받음", "60일 가정"],
                    [["%s~%s" % (c["from"].strftime("%m/%d"), c["to"].strftime("%m/%d")), "%d건" % c["n"], _days(c["median"]),
                      _days(c["p75"]), _days(c["p90"]), "%d건" % c["open"],
                      ("<b style='color:#c62828'>다시 정할 때</b>" if c["off"] else "맞음 (±%d일 안)" % COLLECT_GAP)]], nums=(1, 2, 3, 4, 5))
        body += _none("석 달 전~여섯 달 전에 발행한 계산서만 셉니다(90일 넘게 지나 들어왔는지가 거의 정해진 것). 아직 못 받은 건은 아주 늦은 것으로 셉니다. "
                      "가운데 값이 60일과 %d일 넘게 벌어지면 할 일에 올립니다. 입금 예상(여유 자금)은 계속 60일로 계산합니다." % COLLECT_GAP)
    sub(16, "계산서 → 입금 걸린 날 (60일 가정 다시 재기)", body)
    # 17 A1
    pl = X.get("pipeline")
    if err(pl):
        body = _none("계산하지 못함 (%s)" % pl["error"])
    else:
        rows = [[esc(b["ym"]), "%d개%s" % (b["n"], " (이익 모름 %d)" % b["unknown"] if b["unknown"] else ""), W(b["sales"]), W(b["gp"]),
                 W(pl["fixed"]), P(b["cover"])] for b in pl["rows"]]
        body = _tbl(["행사 달", "받은 프로젝트", "매출 기준", "예상 이익", "월 고정비", "덮는 비율"], rows, nums=(2, 3, 4, 5))
        body += _none("예상 이익 = 인트라넷 프로젝트의 매출 기준(계약·견적) − 추정 예산까지 나갈 돈(진행 중) · 행사 달에 모두 넣음. "
                      "월 고정비 = 끝난 최근 %d달 판관비 평균(%s). 덮는 비율이 100%% 밑인 달은 그 달 일감 이익으로 고정비를 못 덮는다는 뜻 — 영업·채용·큰 지출 판단에 씀."
                      % (len(pl["fixed_months"]), "·".join(pl["fixed_months"]) or "자료 없음"))
    sub(17, "앞으로 6달 확보한 일감 vs 고정비", body)
    # 18 A2
    b = X.get("breakeven")
    if err(b):
        body = _none("계산하지 못함 (%s)" % b["error"])
    else:
        rows = [["월 고정비 (판관비 최근 평균)", W(b["fixed"])], ["매출총이익률 (%s)" % esc(b["rate_how"]), P(b["rate"])],
                ["<b>손익분기 월 매출</b> = 고정비 ÷ 이익률", "<b>%s</b>" % W(b["be"])],
                ["최근 3달 평균 월 매출", W(b["avg3"])], ["올해 매출 목표 (팀 목표 합)", W(b["target"])], ["올해 지금까지 매출", W(b["ytd"])],
                ["<b>목표까지 남은 %d달 매달 필요한 매출</b>" % b["left"], "<b>%s</b>" % W(b["need"])]]
        body = _tbl(["구분", "금액"], rows, nums=(1,)) + _none(
            "손익분기 = 그 매출을 넘어야 영업이익이 남는 선입니다(이익률이 그대로라는 가정). 목표가 없으면 '-'.")
    sub(18, "손익분기 매출 · 목표까지 매달 필요한 매출", body)
    # 19 A3
    cl = X.get("clients")
    if err(cl):
        body = _none("계산하지 못함 (%s)" % cl["error"])
    elif not cl["rows"]:
        body = _none("올해 행사 중 매출 기준·예상 이익이 있는 프로젝트 없음")
    else:
        body = _tbl(["고객사", "프로젝트", "매출 기준", "예상 이익", "수익률", ""],
                    [[esc(x["label"]), "%d개" % x["n"], W(x["sales"]), W(x["gp"]), P(x["rate"]),
                      "<b style='color:#c62828'>평균보다 10%p 넘게 낮음</b>" if x["low"] else ""] for x in cl["rows"]], nums=(1, 2, 3, 4))
        body += _none("올해 행사 프로젝트를 고객사별로 더함 (회사 평균 수익률 %s%s). 고객은 매출 계산서 거래처코드로 묶고, 계산서가 아직 없는 프로젝트만 인트라넷 고객 이름으로. "
                      "예상 이익은 끝난 건 쓴 돈, 진행 중은 추정 예산까지 나갈 돈을 뺀 값." % (P(cl["rate"]), " · 나머지 %d곳 생략" % cl["more"] if cl["more"] else ""))
    sub(19, "고객사별 이익 (매출 큰 순)", body)
    # 20 A4
    it = X.get("inst")
    if err(it):
        body = _none("계산하지 못함 (%s)" % it["error"])
    elif not it:
        body = _none("올해분 법인세 예상 줄 없음")
    elif not it["inst"]:
        body = _none("내년 %s 낼 올해분 법인세 예상 %s원 — 1천만 원 이하라 나눠 낼 수 없음" % (it["due"].isoformat(), W(it["total"])))
    else:
        body = _tbl(["", "%s" % it["due"].isoformat(), "%s" % it["inst_due"].isoformat(), "합계"],
                    [["나눠 내면", W(it["first"]), W(it["inst"]), W(it["total"])], ["한 번에 내면", W(it["total"]), "0", W(it["total"])]], nums=(1, 2, 3))
        body += _none("법인세는 낼 세금이 1천만 원을 넘으면 나눠 낼 수 있고, 중소기업은 2달 뒤까지입니다(2천만 원 이하면 1천만 넘는 몫, 넘으면 절반까지 · 법인세법 64조). "
                      "지금 자금 일정은 %s. 창 '자금 선택'에서 '법인세 분납'을 고르면 다음 변환부터 일정이 나뉩니다. 지방소득세는 나누지 않음."
                      % ("나눠 내는 것으로 잡혀 있음" if it["chosen"] else "한 번에 내는 것으로 잡혀 있음"))
    sub(20, "법인세 나눠 내면 (분납)", body)
    # 21 A5
    ic = X.get("idle")
    if err(ic):
        body = _none("계산하지 못함 (%s)" % ic["error"])
    elif not ic:
        body = _none("잔액·지급 자료가 없어 계산하지 못함")
    else:
        rows = []
        for r in ic["rows"]:
            if r.get("idle") is None:
                rows.append(["앞으로 %d달" % r["months"], "-", "-", "-", "자금계획서가 없어 모름"])
                continue
            rows.append(["앞으로 %d달%s" % (r["months"], " (%s까지만)" % r["upto"].isoformat() if r["short"] else ""),
                         "%s (%s)" % (W(r["low"]), r["low_day"].strftime("%m/%d") if r["low_day"] else "-"), W(r["idle"]),
                         W(r["interest"]) if r["interest"] is not None else "금리 넣으면 나옴",
                         "자금 일정이 %s까지라 그 뒤는 모름" % ic["plan_end"].isoformat() if r["short"] else ""])
        body = _tbl(["기간", "가장 낮은 잔액 (날)", "안 쓸 돈 (최소 보유 %s 뺌)" % W(ic["min_cash"]), "예금 이자 어림", "메모"], rows, nums=(1, 2, 3))
        body += _none("잔액은 날마다 '확정분'과 '예상 포함' 중 낮은 쪽(보수적). 이 기간 안 꺼내도 되는 돈이라 예금에 넣어 볼 수 있음 — 프로젝트 지급이 늦게 잡히면 줄어듦. "
                      "금리는 창 '자금 선택'에서 넣음 (%s)." % ("연 %.2f%%" % (ic["rate"] * 100) if ic["rate"] else "아직 없음"))
    sub(21, "당분간 안 쓸 돈과 예금 이자", body)
    # 22 A7
    sv = X.get("severance")
    if not sv:
        body = _none("급여 명세(위하고 인사·급여 자료)가 없어 계산하지 못함")
    else:
        body = _tbl(["구분", "내용"], [["1년 넘은 직원 퇴직금 합계 (%s 기준)" % esc(sv["ym"]), "<b>%s원</b> (%d명)" % (W(sv["total"]), len(sv["people"]))],
                                      ["앞으로 12달 안에 1년 되는 사람", ", ".join("%s %s" % (esc(n), d.strftime("%Y-%m")) for n, d, _ in sv["soon"]) or "없음"]])
        body += _none("사람마다 최근 3달 평균 급여 × 근속 연수 (급여 점검과 같은 어림, 퇴직연금 적립·평균임금 계산과 다를 수 있음). 임원·입사일 모르는 사람 %d명은 뺌." % len(sv["skipped"]))
    sub(22, "퇴직금 합계 (회사가 줄 돈)", body)
    # 23 A8
    sp = X.get("spikes")
    if err(sp):
        body = _none("계산하지 못함 (%s)" % sp["error"])
    elif sp is None:
        body = _none("올해 계정별 비용 자료 없음")
    elif not sp:
        body = _none("크게 늘어난 판관비·영업외비용 계정 없음 (최근 3달 평균의 1.5배·300만 원 기준)")
    else:
        body = _tbl(["달", "계정", "그 달", "앞 3달 평균", "늘어난 돈", "배"],
                    [[esc(x["ym"]), "%s %s" % (esc(x["code"]), esc(x["name"])), W(x["cur"]), W(x["avg"]), S(x["up"]),
                      "-" if x["times"] is None else "%.1f배" % x["times"]] for x in sp], nums=(2, 3, 4, 5))
        body += _none("원가는 행사마다 크게 달라 빼고 판관비·영업외비용만 봅니다. 위하고 계정별원장에서 그 달 전표를 확인하세요.")
    sub(23, "비용 급증 알림 (판관비·영업외비용)", body)
