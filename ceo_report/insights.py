"""자동 분석 13가지 (사용자 2026-11-12: 새 자료가 들어올 때마다 자금·매입·매출·이익·프로젝트 수익·비용을 스스로 풀이).

경영관리 보고 '자동 분석' 영역과 지금 현황 화면에 모두 싣는다. 대표·팀장 보고 배치는 사용자 확인 뒤.
  1 바뀐 이유      지난 보고(현황) 뒤 여유 자금을 바꾼 일정 줄 — 금액 큰 순
  2 세금 떼고      이미 쌓인 부가세·원천세·법인세를 '낼 돈'으로 떼고 남는 돈
  3 이달 손익 예측 지금 장부 + 아직 안 넣은 급여·카드·감가상각 추정 = 월말 예상 영업이익
  4 경보          여유 자금 부족, 추정 예산 80%·100% 넘은 프로젝트, 적자 예상 프로젝트
  5 자금 달력      앞으로 8주 날마다 잔액 (확정·예상 포함), 가장 낮은 날
  6 미수금 나이    발행 뒤 지난 날수별 받을 돈
  7 계산서 짝      행사가 끝났는데 매입만 있고 매출 계산서가 없거나, 매출만 있고 원가가 없는 프로젝트
  8 이익 흐름      견적 때 이익 → 지금 예상 이익 (얼마나 줄었나)
  9 입금 습관      거래처마다 입금 예정일보다 며칠 늦게 들어왔나, 그만큼 늦춰 보면 여유 자금
 10 고정비        장부에서 매달 나가는 돈을 찾아 앞으로 3달 지급, 일정에 없는 것
 11 팀 순위       올해 누적 팀별 매출·매출총이익·목표 달성률
 12 입금 지연 위험  큰 입금이 30일 늦으면 여유 자금이 얼마가 되나
 13 입력 누락     매달 있던 전표(급여·4대보험·원천세·카드·고정비)가 이번 달에 없음

정한 계산 기준(여유 자금 = 확정분 최저 잔액 − 최소 보유현금)은 바꾸지 않는다. 9·10·12 는 '반영하면 X'로 따로만 보인다.
장부(분개장)가 있어야 하는 10·13 은 자료 변환 때 book_facts() 로 계산해 입력\\자동분석.json 에 둔다.
"""
import collections
import datetime as dt
import json
import os
import re
import statistics

FILE = "자동분석.json"
DAY = dt.timedelta(days=1)
TAX_KINDS = ("부가세", "원천세", "법인세", "법인지방소득세")
CAL_DAYS = 56
DELAY_DAYS = 30


def _sq(t):
    return re.sub(r"\s+", "", str(t or ""))


# ───────────── 장부로 계산 (자료 변환 때) ─────────────
CARD_RE = re.compile(r"^(신한|롯데|비씨|BC|삼성|현대|국민|KB|하나|우리|농협|NH)[_\s-]?\d{4}$")
INSURERS = ("국민연금", "건강보험", "근로복지", "고용보험")
TAXOFF = ("세무서", "구청", "시청", "군청")


def _months_back(asof, n):
    y, m = asof.year, asof.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append("%04d-%02d" % (y, m))
    return out[::-1]


def _bank_slips(journal, cash_codes):
    """전표마다 보통예금 출금 합과 상대 줄 -> {(날짜, 번호): {'date', 'out', 'lines'}} (보통예금이 양쪽에 있으면 계좌간 이체라 뺌)."""
    cash = set(_sq(c) for c in cash_codes)
    slips = collections.OrderedDict()
    for ln in journal:
        if ln.get("date") is None:
            continue
        k = (ln["date"], str(ln.get("no") or ""))
        s = slips.setdefault(k, {"date": ln["date"], "out": 0, "in": 0, "lines": []})
        if _sq(ln.get("account_code")) in cash:
            s["out"] += ln.get("credit") or 0
            s["in"] += ln.get("debit") or 0
        else:
            s["lines"].append(ln)
    return {k: s for k, s in slips.items() if s["out"] > 0 and not s["in"]}


def _payee(slip):
    """출금 전표의 받는 쪽 이름: 차변 줄 거래처, 없으면 계정 이름. 카드·세금·보험·급여면 None (다른 계산이 맡음)."""
    names = []
    for ln in slip["lines"]:
        if not (ln.get("debit") or 0):
            continue
        v, acc = (ln.get("vendor") or "").strip(), (ln.get("account") or "").strip()
        code = _sq(ln.get("account_code"))
        if CARD_RE.match(_sq(v)) or any(w in v + acc for w in INSURERS + TAXOFF + ("급여",)) or code in ("80200", "25400", "25500"):
            return None
        names.append(v or acc)
    names = [n for n in names if n]
    return names[0] if names else None


def recurring(journal, asof, cash_codes=("10300",), months=4, need=3, spread=0.10):
    """매달 같은 곳에 비슷한 금액이 나가는 지급 -> [{name, amount, day, months:{ym: 금액}}] (지난 months 달 중 need 달 이상)."""
    window = _months_back(asof, months)
    cur = asof.strftime("%Y-%m")
    by = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, []]))
    for s in _bank_slips(journal, cash_codes).values():
        ym = s["date"].strftime("%Y-%m")
        if ym not in window and ym != cur:
            continue
        name = _payee(s)
        if not name:
            continue
        c = by[name][ym]
        c[0] += s["out"]
        c[1].append(s["date"].day)
    out = []
    for name, per in by.items():
        past = [per[ym][0] for ym in window if ym in per]
        if len(past) < need:
            continue
        mid = statistics.median(past)
        if mid <= 0 or any(abs(v - mid) > spread * mid for v in past):
            continue
        days = [d for ym in window if ym in per for d in per[ym][1]]
        out.append({"name": name, "amount": int(round(mid)), "day": int(statistics.median(days)),
                    "months": dict((ym, per[ym][0]) for ym in window + [cur] if ym in per)})
    return sorted(out, key=lambda r: -r["amount"])


def monthly_presence(journal, asof, cash_codes=("10300",)):
    """매달 있어야 하는 전표 종류의 달별 [금액, 그달 마지막 전표일] -> {종류: {ym: [금액, 날]}} (지난 4달 + 이번 달)."""
    want = _months_back(asof, 4) + [asof.strftime("%Y-%m")]
    out = collections.OrderedDict((k, {}) for k in ("급여", "4대보험", "원천세"))

    def add(kind, ym, amt, day):
        c = out.setdefault(kind, {}).setdefault(ym, [0, 0])
        c[0] += amt
        c[1] = max(c[1], day)
    for ln in journal:
        if ln.get("date") is None:
            continue
        ym = ln["date"].strftime("%Y-%m")
        if ym not in want:
            continue
        code, v = _sq(ln.get("account_code")), (ln.get("vendor") or "")
        amt, day = ln.get("credit") or 0, ln["date"].day
        if code == "80200" and (ln.get("debit") or 0):
            add("급여", ym, ln["debit"], day)
        elif code == "25400" and amt and any(w in v for w in INSURERS):
            add("4대보험", ym, amt, day)
        elif code == "25400" and amt and any(w in v for w in TAXOFF):
            add("원천세", ym, amt, day)
        elif code == "26200" and amt and CARD_RE.match(_sq(v)):
            add("카드 %s 사용" % v.strip(), ym, amt, day)
    return out


def book_facts(journal, asof, book_date, cash_codes=("10300",)):
    return {"asof": asof.isoformat(), "book_date": book_date.isoformat() if book_date else "",
            "recurring": recurring(journal, asof, cash_codes),
            "presence": monthly_presence(journal, asof, cash_codes)}


def write_facts(input_dir, facts):
    path = os.path.join(input_dir, FILE)
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(facts, f, ensure_ascii=False, indent=1)
        os.replace(path + ".tmp", path)
        return True
    except OSError:
        return False


def read_facts(input_dir):
    try:
        with open(os.path.join(input_dir, FILE), encoding="utf-8") as f:
            x = json.load(f)
        return x if isinstance(x, dict) else None
    except (OSError, ValueError):
        return None


# ───────────── 보고 자료로 계산 ─────────────
def _ends(R):
    return [(p["label"], p["end"]) for p in R["s2"].get("periods") or [] if p["label"] != "지정일"]


def _avail_with(R, dated):
    """일정(dated)을 바꿔 넣었을 때 마지막 기간 여유 자금 (확정분, 예상 포함) -> (firm, all) 또는 (None, None)."""
    from .calc import available_periods
    s2 = R["s2"]
    ends = _ends(R)
    if not ends or s2.get("start") is None:
        return None, None
    per = available_periods(s2["start"], dated, ends, s2.get("min_cash"), R["asof"])
    return per[-1]["firm"]["avail"], per[-1]["all"]["avail"]


def _last(R):
    per = [p for p in R["s2"].get("periods") or [] if p["label"] != "지정일"]
    return per[-1] if per else None


MUST_WORDS = ("급여", "회사부담금", "4대보험", "세금", "부가세", "원천세", "법인세", "지방소득세", "차입금", "대출", "이자")


def _is_must(e):
    """꼭 나갈 돈: 급여(4대보험 포함)·세금·대출 원금·이자 (사용자 2026-11-12)."""
    cat = str(e.get("cat") or "")
    return e.get("io") == "out" and any(w in cat for w in MUST_WORDS)


def _next_month_end(d):
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return (dt.date(y + (m == 12), m % 12 + 1, 1) - DAY)


def taxes_set_aside(R):
    """2: 여유 자금 기간 뒤 꼭 나갈 돈까지 떼어 본다 (사용자 2026-11-12 결정 '기간 뒤 필수지출만 더 빼기').

    · must: 기간 끝 다음 날 ~ 다음 달 말일에 나갈 급여(4대보험)·세금·대출 원금·이자 (기간 안 것은 이미 여유 자금에 들어 있음)
    · later: 다음 달 말일 뒤에 낼 세금 계산값 (이미 쌓인 부가세·원천세·법인세)
    after = 마지막 기간 여유 자금(확정분) − must − later."""
    rows = [t for t in R.get("tax") or [] if t.get("kind") in TAX_KINDS and t.get("due") and t["due"] > R["asof"]
            and t.get("amount") is not None]
    total = sum(t["amount"] for t in rows)
    last = _last(R)
    end = last["end"] if last else R["asof"]
    upto = max(_next_month_end(R["asof"]), end)
    must = sorted([e for e in R["s2"].get("dated") or [] if end < e["date"] <= upto and _is_must(e) and e.get("amount")],
                  key=lambda e: e["date"])
    later = [t for t in rows if t["due"] > upto]
    avail = last["firm"]["avail"] if last else None
    later_total = sum(t["amount"] for t in later)
    must_total = sum(e["amount"] for e in must)
    return {"rows": rows, "total": total, "later": later, "later_total": later_total, "label": last["label"] if last else "",
            "must": must, "must_total": must_total, "upto": upto, "end": end,
            "avail": avail, "after": None if avail is None else avail - must_total - later_total}


def month_forecast(R):
    """3: 이번 달 월말 예상 영업이익 = 지금 장부 + 아직 안 넣은 급여·감가상각·카드 추정."""
    asof = R["asof"]
    ym, mi = asof.strftime("%Y-%m"), asof.month - 1
    A = R.get("acct_year") or {}
    grp = dict((g["name"], g) for g in A.get("groups") or []) if A.get("state") == "ok" and str(A.get("year")) == str(asof.year) else {}
    # 이번 달 실적은 보고서 실적 칸과 같은 숫자 (분개장 매출·원가·공통비, 회사 전체 줄). 없으면 증빙 월별·계정별 비용으로
    src = ((R.get("s4") or {}).get("sources") or {}).get("WEHAGO") or {}
    co = [r for r in src.get("table") or [] if r.get("unit") == "회사" and (r.get("cur") or {}).get("months") == [ym]]
    if co and co[0]["cur"].get("revenue") is not None:
        c = co[0]["cur"]
        sales, cost, sga = c["revenue"], c.get("direct") or 0, c.get("common") or 0
    else:
        if not grp:
            return None
        sales = ((R.get("evid_month") or {}).get(ym) or (None, None))[0]
        cost = (grp.get("원가") or {"months": [0] * 12})["months"][mi] or 0
        sga = (grp.get("판매비와관리비") or {"months": [0] * 12})["months"][mi] or 0
    adds = []
    sal = [a for a in (grp.get("판매비와관리비") or {}).get("accounts", []) if str(a["code"]) == "80200"]
    if sal and not (sal[0]["months"][mi] or 0) and mi >= 1 and sal[0]["months"][mi - 1]:
        adds.append(("급여 (전표 전, 지난달 금액)", sal[0]["months"][mi - 1]))
    dep = R.get("dep") or {}
    deps = [a for a in (grp.get("판매비와관리비") or {}).get("accounts", []) if "감가상각" in (a.get("name") or "")]
    if dep.get("annual") and not (deps and deps[0]["months"][mi]):
        adds.append(("감가상각비 (작년 금액 ÷ 12)", int(round(dep["annual"] / 12.0))))
    nxt = (asof.replace(day=28) + dt.timedelta(days=4)).strftime("%Y-%m")
    card = sum(t["amount"] for t in R.get("tax") or [] if t.get("kind") == "카드대금" and t.get("state") == "예상"
               and t.get("due") and t["due"].strftime("%Y-%m") == nxt and t.get("amount"))
    if card:
        adds.append(("카드 전표 전 추정 (부가세 뺀 금액)", int(round(card / 1.1))))
    booked = None if sales is None else sales - cost - sga
    extra = sum(v for _, v in adds)
    return {"ym": ym, "sales": sales, "cost": cost, "sga": sga, "booked": booked, "adds": adds,
            "forecast": None if booked is None else booked - extra}


def alerts(R):
    """4: 경보 목록 -> [(수준, 글)]."""
    out = []
    for p in R["s2"].get("periods") or []:
        if p["firm"]["avail"] is not None and p["firm"]["avail"] < 0:
            out.append(("높음", "%s 여유 자금이 %s원 모자람 (확정분 기준, %s 가장 낮음)" % (
                p["label"], "{:,}".format(-p["firm"]["avail"]), p["firm"]["low_date"])))
            break
    for p in (R.get("s3") or {}).get("projects") or []:
        b, paid = p.get("budget"), p.get("paid_total")
        name = "[%s] %s" % (p.get("id"), p.get("name"))
        if b and paid is not None and paid >= b:
            out.append(("높음", "%s 집행 %s원이 추정 예산 %s원을 넘음 (%.0f%%)" % (name, "{:,}".format(paid), "{:,}".format(b), 100.0 * paid / b)))
        elif b and paid is not None and paid >= 0.8 * b:
            out.append(("주의", "%s 집행이 추정 예산의 %.0f%%" % (name, 100.0 * paid / b)))
        if p.get("profit_end") is not None and p["profit_end"] < 0:
            out.append(("높음", "%s 예상 적자 %s원" % (name, "{:,}".format(-p["profit_end"]))))
    return out


def calendar(R, days=CAL_DAYS):
    """5: 날마다 잔액 -> [{date, firm, all}] (기준일 다음 날부터)."""
    s2 = R["s2"]
    if s2.get("start") is None:
        return []
    asof = R["asof"]
    flow = {"firm": collections.defaultdict(int), "all": collections.defaultdict(int)}
    for e in s2.get("dated") or []:
        if e.get("amount") is None or not (asof < e["date"] <= asof + dt.timedelta(days=days)):
            continue
        v = e["amount"] if e["io"] == "in" else -e["amount"]
        flow["all"][e["date"]] += v
        if e["firm"]:
            flow["firm"][e["date"]] += v
    out, bf, ba = [], s2["start"], s2["start"]
    for i in range(1, days + 1):
        d = asof + dt.timedelta(days=i)
        bf += flow["firm"].get(d, 0)
        ba += flow["all"].get(d, 0)
        out.append({"date": d, "firm": bf, "all": ba})
    return out


def ar_aging(R):
    """6: 받을 돈 나이 -> {'buckets': [(이름, 금액, 건수)], 'clients': [(거래처, 금액, 가장 오래된 날수)]}."""
    asof = R["asof"]
    names = (("30일 안", 0, 30), ("31~60일", 31, 60), ("61~90일", 61, 90), ("90일 넘음", 91, 10 ** 6))
    buckets = [[n, 0, 0] for n, _, _ in names]
    clients = collections.defaultdict(lambda: [0, 0])
    for r in (R.get("s5") or {}).get("ar_rows") or []:
        amt = r.get("outstanding")
        if not amt or r.get("date") is None:
            continue
        age = (asof - r["date"]).days
        for b, (_, lo, hi) in zip(buckets, names):
            if lo <= age <= hi:
                b[1] += amt
                b[2] += 1
        c = clients[r.get("client") or "거래처 없음"]
        c[0] += amt
        c[1] = max(c[1], age)
    top = sorted(((k, v[0], v[1]) for k, v in clients.items()), key=lambda x: -x[1])[:8]
    return {"buckets": [tuple(b) for b in buckets], "clients": top}


def invoice_pairs(R):
    """7: 행사가 끝났는데 매입·매출 짝이 안 맞는 프로젝트 -> [(프로젝트, 글)]."""
    asof = R["asof"]
    issued = collections.defaultdict(int)
    for r in (R.get("s5") or {}).get("ar_rows") or []:
        issued[r.get("project")] += r.get("supply") or 0
    for r in (R.get("s5") or {}).get("by_project") or []:
        if isinstance(r, dict) and r.get("issued"):
            issued[r.get("project") or r.get("id")] = max(issued[r.get("project") or r.get("id")], r["issued"])
    out = []
    for p in (R.get("s3") or {}).get("projects") or []:
        ev = p.get("event_date") or ""
        try:
            end = dt.date(*[int(x) for x in ev[-10:].split("-")]) if ev else None
        except ValueError:
            end = None
        if end is None or end >= asof:
            continue
        sold = max(issued.get(p.get("id"), 0), p.get("recognized") or 0)
        cost = p.get("paid_total") or 0
        name = "[%s] %s" % (p.get("id"), p.get("name"))
        if cost and not sold:
            out.append((name, "행사 %s 끝, 원가 %s원은 나갔는데 매출 계산서 없음" % (ev, "{:,}".format(cost))))
        elif sold and not cost and not p.get("card_unpaid"):
            out.append((name, "행사 %s 끝, 매출 %s원은 있는데 원가 전표 없음 (매입 계산서·카드 확인)" % (ev, "{:,}".format(sold))))
    return out


def profit_flow(R):
    """8: 프로젝트 견적 이익 → 지금 예상 이익 -> [{name, team, quote, now, diff}] (줄어든 순)."""
    out = []
    for p in (R.get("s3") or {}).get("projects") or []:
        c, b, now = p.get("contract"), p.get("budget"), p.get("profit_end")
        if not c or b is None or now is None:
            continue
        q = c - b
        out.append({"name": "[%s] %s" % (p.get("id"), p.get("name")), "team": p.get("team") or "", "quote": q, "now": now,
                    "diff": now - q, "contract": c})
    return sorted(out, key=lambda r: r["diff"])


def pay_habits(R, d_invoices=None):
    """9: 거래처마다 입금이 예정일보다 며칠 늦었나 -> {'clients': [(거래처, 평균 늦은 날, 건수)], 'avail': (firm, all) 늦춰 본 여유 자금}."""
    invs = d_invoices if d_invoices is not None else (R.get("_invoices") or [])
    delay = collections.defaultdict(list)
    for r in invs:
        if r.get("due") and r.get("paid_date"):
            delay[r.get("client") or ""].append((r["paid_date"] - r["due"]).days)
    habit = dict((k, statistics.mean(v)) for k, v in delay.items() if k and len(v) >= 2)
    clients = sorted(((k, round(v, 1), len(delay[k])) for k, v in habit.items()), key=lambda x: -x[1])
    late = dict((k, int(round(v))) for k, v in habit.items() if v > 0)
    moved = []
    for e in R["s2"].get("dated") or []:
        k = (e.get("desc") or "").strip()
        if e["io"] == "in" and k in late:
            moved.append(dict(e, date=e["date"] + dt.timedelta(days=late[k])))
        else:
            moved.append(e)
    avail = _avail_with(R, moved) if late else (None, None)
    return {"clients": clients, "avail": avail, "base": _last(R)}


def fixed_costs(R, facts):
    """10: 장부에서 찾은 매달 나가는 돈의 앞으로 3달 지급 중 일정에 없는 것 -> {'items': [...], 'missing': [...], 'avail': ...}."""
    if not facts:
        return None
    asof = R["asof"]
    outs = [e for e in R["s2"].get("dated") or [] if e["io"] == "out" and e.get("amount")]
    items, missing = [], []
    for r in facts.get("recurring") or []:
        items.append(r)
        for k in range(0, 3):
            y, m = asof.year, asof.month + k
            y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
            ym = "%04d-%02d" % (y, m)
            if ym in (r.get("months") or {}):
                continue   # 이번 달은 이미 나감
            last_day = (dt.date(y + (m == 12), m % 12 + 1, 1) - DAY).day
            day = dt.date(y, m, min(r["day"], last_day))
            if day <= asof:
                continue
            hit = [e for e in outs if abs((e["date"] - day).days) <= 7
                   and (abs(e["amount"] - r["amount"]) <= 0.1 * r["amount"])]
            if not hit:
                missing.append({"name": r["name"], "date": day, "amount": r["amount"]})
    extra = [{"date": x["date"], "io": "out", "amount": x["amount"], "firm": False, "desc": x["name"]} for x in missing]
    avail = _avail_with(R, list(R["s2"].get("dated") or []) + extra) if extra else (None, None)
    return {"items": items, "missing": missing, "avail": avail}


def team_rank(R):
    """11: 올해 누적 팀별 매출·매출총이익·목표 달성률 -> [{team, revenue, gp, rate, target, achieve}] (매출총이익 순)."""
    from .teamprofit import build
    src = (R.get("s4") or {}).get("sources", {}).get("WEHAGO")
    if not src:
        return []
    T = build(src["table"], R["s4"].get("dept"), R["s4"]["ym"], True)
    if T is None:
        return []
    tg = R.get("targets") or {}
    out = []
    for r in T["rows"]:
        if r["kind"] != "team":
            continue
        t = (tg.get(r["label"]) or {}).get("revenue")
        out.append({"team": r["label"], "revenue": r["revenue"], "gp": r["gp"],
                    "rate": None if not r["revenue"] or r["gp"] is None else 100.0 * r["gp"] / r["revenue"],
                    "target": t, "achieve": None if not t or r["revenue"] is None else 100.0 * r["revenue"] / t})
    return sorted(out, key=lambda r: -(r["gp"] or 0))


def delay_risk(R, n=3):
    """12: 확정 입금 중 큰 것이 30일 늦으면 마지막 기간 여유 자금 -> [{desc, date, amount, avail, drop}]."""
    last = _last(R)
    if last is None or last["firm"]["avail"] is None:
        return []
    dated = R["s2"].get("dated") or []
    end = last["end"]
    big = sorted([e for e in dated if e["io"] == "in" and e["firm"] and e.get("amount") and R["asof"] < e["date"] <= end],
                 key=lambda e: -e["amount"])[:8]
    out = []
    for e in big:
        moved = [dict(x, date=x["date"] + dt.timedelta(days=DELAY_DAYS)) if x is e else x for x in dated]
        firm, _ = _avail_with(R, moved)
        if firm is None:
            continue
        out.append({"desc": e.get("desc") or "", "date": e["date"], "amount": e["amount"], "avail": firm,
                    "drop": firm - last["firm"]["avail"]})
    return sorted(out, key=lambda r: r["drop"])[:n]


# ───────────── 계산서 발행 기한 (사용자 2026-11-12: 대표 보고) ─────────────
PAY_AFTER_ISSUE = 60   # 이 회사 매출 계산서는 대부분 작성일 뒤 60일쯤 입금 (사용자 2026-11-12)
ISSUE_SMALL = 10000    # 1만 원 밑 끝전은 자금에 영향 없음


def _first_short(R, mode):
    """일정을 날마다 더해 잔액이 최소 보유현금 밑으로 처음 내려가는 날 -> (날짜, 모자란 돈, 가장 모자란 날, 가장 모자란 돈) 또는 None."""
    s2 = R["s2"]
    start, mc = s2.get("start"), s2.get("min_cash")
    if start is None or mc is None:
        return None
    daily = collections.defaultdict(int)
    for e in s2.get("dated") or []:
        if e["date"] <= R["asof"] or e.get("amount") is None or (mode == "firm" and not e["firm"]):
            continue
        daily[e["date"]] += e["amount"] if e["io"] == "in" else -e["amount"]
    bal, first, worst = start, None, None
    for day in sorted(daily):
        bal += daily[day]
        if bal < mc:
            if first is None:
                first = (day, mc - bal)
            if worst is None or mc - bal > worst[1]:
                worst = (day, mc - bal)
    return None if first is None else (first[0], first[1], worst[0], worst[1])


def issue_deadline(R, days=PAY_AFTER_ISSUE, small=ISSUE_SMALL):
    """행사 끝났는데 계산서를 덜 낸 프로젝트: 오늘 내면 언제 입금되나, 자금이 모자라기 전에 받으려면 언제까지 내야 하나.

    자금이 모자라는 날 = 일정(예상 포함)을 날마다 더한 잔액이 최소 보유현금 밑으로 처음 내려가는 날. 발행 기한 = 그날 − 60일.
    미발행 계산서의 입금은 지금 일정에 들어 있지 않다 (발행 계산서만 입금 예정)."""
    E = (R.get("s5") or {}).get("event_unissued") or {}
    if E.get("missing") or E.get("total") is None:
        return None
    asof = R["asof"]
    rows = []
    for x in E.get("rows") or []:
        if x["unissued"] < small:
            continue
        rows.append({"id": x["P"]["id"], "name": x["P"].get("name") or "", "event": x["event"], "days": x["days"],
                     "amount": int(round(x["unissued"] * 1.1)), "pay_if_today": asof + dt.timedelta(days=days)})
    rows.sort(key=lambda r: (-r["amount"], r["id"]))
    short = _first_short(R, "all")
    firm = _first_short(R, "firm")
    out = {"rows": rows, "total": sum(r["amount"] for r in rows), "days": days, "short": short, "firm_short": firm,
           "deadline": None, "late": False, "small_n": sum(1 for x in E.get("rows") or [] if x["unissued"] < small),
           "horizon": max([e["date"] for e in R["s2"].get("dated") or []] or [asof])}
    if short:
        out["deadline"] = short[0] - dt.timedelta(days=days)
        out["late"] = out["deadline"] < asof
    return out


def missing_entries(R, facts, small=100000, thin=0.3):
    """13: 매달 있던 전표가 빠졌거나 덜 들어감 -> [(종류, 글)].

    · 이번 달: 지난 3달 매달 있었고, 보통 들어오던 날(지난 달들 마지막 전표일의 가운데)+5일이 지났는데 아직 없음
    · 지난달: 그 앞 3달 매달 있었는데 지난달 금액이 그 평균의 30% 밑 (덜 들어감 의심). 평균 10만 원 밑 종류는 보지 않음."""
    if not facts:
        return []
    asof = R["asof"]
    cur = asof.strftime("%Y-%m")
    prev3 = _months_back(asof, 3)
    last = prev3[-1]
    before3 = _months_back(dt.date(int(last[:4]), int(last[5:]), 1), 3)
    out = []
    for kind, per in (facts.get("presence") or {}).items():
        val = dict((k, v[0] if isinstance(v, list) else v) for k, v in per.items())
        days = [v[1] for k, v in per.items() if isinstance(v, list) and k in prev3]
        if all(val.get(ym) for ym in prev3) and not val.get(cur) and days:
            usual = int(statistics.median(days))
            if asof.day > usual + 5:
                out.append((kind, "지난 3달 매달 %d일쯤까지 들어왔는데 이번 달은 아직 없음" % usual))
        base = [val.get(ym) for ym in before3]
        if all(base) and sum(base) / 3.0 >= small and (val.get(last) or 0) < thin * sum(base) / 3.0:
            out.append((kind, "%s월 %s원 — 앞 3달 평균 %s원의 %d%% (덜 들어감 의심)" % (
                last[5:], "{:,}".format(int(val.get(last) or 0)), "{:,}".format(int(sum(base) / 3.0)),
                int(100 * (val.get(last) or 0) / (sum(base) / 3.0)))))
    for r in facts.get("recurring") or []:
        if cur not in (r.get("months") or {}) and asof.day > r["day"] + 5:
            out.append((r["name"], "매달 %d일쯤 %s원 나가던 지급이 이번 달 %d일 지나도록 장부에 없음" % (
                r["day"], "{:,}".format(r["amount"]), r["day"] + 5)))
    return out


def change_reasons(prev_events, R, n=5):
    """1: 지난 기록 일정과 지금 일정 비교 -> [(글, 여유 자금에 준 영향 +/-)] 금액 큰 순.

    prev_events: [{date, io, amount, desc, firm}] (지난 현황·보고 때 저장한 일정)."""
    if prev_events is None:
        return []

    def key(e):
        return (e.get("io"), (e.get("desc") or "").strip(), e.get("amount"))
    asof = R["asof"]
    horizon = (_last(R) or {}).get("end") or asof
    now = [e for e in R["s2"].get("dated") or [] if asof < e["date"] <= horizon and e.get("amount")]
    before = [e for e in prev_events if e.get("amount") and asof < _d(e["date"]) <= horizon]
    left = collections.Counter(key(e) for e in before)
    out = []
    for e in now:
        k = key(e)
        if left[k]:
            left[k] -= 1
            continue
        sign = 1 if e["io"] == "in" else -1
        out.append(("새로 생김: %s %s %s원 (%s)" % (_d(e["date"]).strftime("%m/%d"), e.get("desc") or "", "{:,}".format(e["amount"]),
                                               "확정" if e.get("firm") else "예상"), sign * e["amount"]))
    for e in before:
        k = key(e)
        if left[k] <= 0:
            continue
        left[k] -= 1
        sign = -1 if e["io"] == "in" else 1
        out.append(("빠짐: %s %s %s원" % (_d(e["date"]).strftime("%m/%d"), e.get("desc") or "", "{:,}".format(e["amount"])),
                    sign * e["amount"]))
    return sorted(out, key=lambda x: -abs(x[1]))[:n]


def _d(v):
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v)[:10])


def events_for_record(R):
    """다음 비교(1)에 쓸 일정 줄 -> json 으로 저장할 수 있는 목록."""
    from .util import mask_rrn   # 주민번호 모양은 가림 (D-45)
    return [{"date": e["date"].isoformat(), "io": e["io"], "amount": e.get("amount"), "desc": mask_rrn(e.get("desc") or ""),
             "firm": bool(e.get("firm"))} for e in R["s2"].get("dated") or [] if e.get("amount")]


# ───────────── 예측 입금 vs 실제 입금 (사용자 2026-11-12 "추천대로": 과거 예측과 실제 차이 추적) ─────────────
TRACK_WEEKS = 4      # 보고 때 예측한 뒤 4주 동안 들어온 돈과 견준다
TRACK_ROWS = 8


def _actual(txns, frm, to, io):
    """통장에서 실제로 움직인 돈 (frm 다음 날 ~ to, 계좌 간 이체 뺌). io = '입금' | '출금'."""
    return sum(t["amount"] or 0 for t in txns or [] if frm < t["date"] <= to and t.get("io") == io
               and t.get("cat") != "계좌간이체")


def _pred(events, frm, to, io, firm_only):
    tot = 0
    for e in events:
        if e.get("io") != io or not e.get("amount") or (firm_only and not e.get("firm")):
            continue
        d = e["date"] if isinstance(e["date"], dt.date) else dt.date.fromisoformat(e["date"])
        if frm < d <= to:
            tot += e["amount"]
    return tot


def _cmp(ev, txns, frm, to):
    return {"in": {"firm": _pred(ev, frm, to, "in", True), "all": _pred(ev, frm, to, "in", False),
                   "actual": _actual(txns, frm, to, "입금")},
            "out": {"firm": _pred(ev, frm, to, "out", True), "all": _pred(ev, frm, to, "out", False),
                    "actual": _actual(txns, frm, to, "출금")}}


def booked_profit(R, ym):
    """그 달 장부 영업이익 (지금 장부: 증빙 기준 매출 − 원가 − 판관비) 또는 None."""
    A = R.get("acct_year") or {}
    if A.get("state") != "ok" or str(A.get("year")) != ym[:4]:
        return None
    grp = dict((g["name"], g) for g in A.get("groups") or [])
    mi = int(ym[5:]) - 1
    sales = ((R.get("evid_month") or {}).get(ym) or (None, None))[0]
    if sales is None:
        return None
    cost = (grp.get("원가") or {"months": [0] * 12})["months"][mi] or 0
    sga = (grp.get("판매비와관리비") or {"months": [0] * 12})["months"][mi] or 0
    return sales - cost - sga


def forecast_track(records, txns, R=None, profits=None):
    """지난 보고 때 예측과 그 뒤 실제 (사용자 2026-11-12: 기록을 나중 장부와 맞춰 경영관리 보고에 매번).

    · weeks: 보고마다 그날 뒤 4주(통장 자료가 있는 날까지) 예측 입금·출금(확정분·예상 포함) vs 통장 실제
    · months: 다 끝난 달마다, 그 달 1일 전 가장 늦은 보고의 예측 vs 그 달 통장 실제
    · profit: 지난달들에 보고 때 낸 '이번 달 예상 영업이익' vs 지금 장부의 그 달 영업이익
    차이 = 실제 − 예측 (입금 + 면 더 들어옴, 출금 + 면 더 나감)."""
    last = max([t["date"] for t in txns or []] or [None]) if txns else None
    out = {"weeks": [], "months": [], "profit": [], "last_txn": last}
    if records and last:
        first = min(t["date"] for t in txns)   # 통장 자료가 처음부터 덮는 기간만 견준다 (덜 덮이면 실제가 작게 나옴)
        recs = sorted((d0, ev) for d0, ev in records if first <= d0 < last)
        for d0, ev in recs[-TRACK_ROWS:][::-1]:
            to = min(d0 + dt.timedelta(weeks=TRACK_WEEKS), last)
            out["weeks"].append(dict(_cmp(ev, txns, d0, to), made=d0, to=to, part=to < d0 + dt.timedelta(weeks=TRACK_WEEKS)))
        if recs:
            y, m = recs[0][0].year, recs[0][0].month
            while True:
                m += 1
                if m == 13:
                    y, m = y + 1, 1
                start = dt.date(y, m, 1)
                end = dt.date(y + (m == 12), m % 12 + 1, 1) - DAY
                if end > last:
                    break
                before = [r for r in recs if r[0] < start]
                if before and first < start:
                    d0, ev = before[-1]
                    out["months"].append(dict(_cmp(ev, txns, start - DAY, end), ym="%04d-%02d" % (y, m), made=d0))
        out["months"] = out["months"][::-1][:TRACK_ROWS]
    if R is not None and profits:
        cur = R["asof"].strftime("%Y-%m")
        latest = {}
        for d0, ym, fc in sorted(profits):
            if ym < cur and fc is not None:
                latest[ym] = (d0, fc)
        for ym in sorted(latest, reverse=True)[:TRACK_ROWS]:
            d0, fc = latest[ym]
            out["profit"].append({"ym": ym, "made": d0, "forecast": fc, "actual": booked_profit(R, ym)})
    return out


def load_records(out_dir, keep_days=400):
    """출력\\자동분석기록\\일정_<기준일>.json 전부 -> [(기준일, 일정 목록)] (오래된 순)."""
    folder = os.path.join(out_dir, RECORD_DIR)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    out = []
    for n in names:
        m = re.match(r"^일정_(\d{4}-\d{2}-\d{2})\.json$", n)
        if not m:
            continue
        try:
            with open(os.path.join(folder, n), encoding="utf-8") as f:
                x = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(x, list):
            out.append((dt.date.fromisoformat(m.group(1)), x))
    out.sort()
    if out:
        cut = out[-1][0] - dt.timedelta(days=keep_days)
        out = [r for r in out if r[0] >= cut]
    return out


def compute(R, facts=None, invoices=None, prev_events=None):
    return {
        "reasons": change_reasons(prev_events, R),
        "tax": taxes_set_aside(R),
        "month": month_forecast(R),
        "alerts": alerts(R),
        "calendar": calendar(R),
        "aging": ar_aging(R),
        "pairs": invoice_pairs(R),
        "flow": profit_flow(R),
        "habits": pay_habits(R, invoices),
        "fixed": fixed_costs(R, facts),
        "teams": team_rank(R),
        "delay": delay_risk(R),
        "missing": missing_entries(R, facts),
        "issue": issue_deadline(R),
        "track": forecast_track(R.get("auto_records"), R.get("_txns"), R, R.get("auto_profits")),
        "has_facts": bool(facts),
        "has_prev": prev_events is not None,
    }


# ───────────── 지난 일정 기록 (1 바뀐 이유) ─────────────
RECORD_DIR = "자동분석기록"


def write_record(out_dir, R):
    folder = os.path.join(out_dir, RECORD_DIR)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "일정_%s.json" % R["asof"].isoformat())
    with open(path, "w", encoding="utf-8") as f:
        json.dump(events_for_record(R), f, ensure_ascii=False)
    try:   # 이번 달 예상 영업이익도 남긴다: 나중 장부와 견줌 (사용자 2026-11-12)
        M = month_forecast(R)
    except Exception:
        M = None
    if M and M.get("forecast") is not None:
        with open(os.path.join(folder, "예측_%s.json" % R["asof"].isoformat()), "w", encoding="utf-8") as f:
            json.dump({"ym": M["ym"], "profit": M["forecast"]}, f, ensure_ascii=False)
    return path


def load_profit_forecasts(out_dir):
    """출력\\자동분석기록\\예측_<기준일>.json -> [(기준일, 달, 예상 영업이익)]."""
    folder = os.path.join(out_dir, RECORD_DIR)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    out = []
    for n in names:
        m = re.match(r"^예측_(\d{4}-\d{2}-\d{2})\.json$", n)
        if not m:
            continue
        try:
            with open(os.path.join(folder, n), encoding="utf-8") as f:
                x = json.load(f)
            out.append((dt.date.fromisoformat(m.group(1)), str(x["ym"]), int(x["profit"])))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(out)


def load_previous(out_dir, asof, lookback=14):
    """기준일 전 lookback 일 안의 가장 최근 기록 -> 일정 목록 또는 None."""
    folder = os.path.join(out_dir, RECORD_DIR)
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    found = []
    for n in names:
        m = re.match(r"^일정_(\d{4}-\d{2}-\d{2})\.json$", n)
        if m:
            day = dt.date.fromisoformat(m.group(1))
            if asof - dt.timedelta(days=lookback) <= day < asof:
                found.append((day, n))
    if not found:
        return None
    try:
        with open(os.path.join(folder, max(found)[1]), encoding="utf-8") as f:
            x = json.load(f)
        return x if isinstance(x, list) else None
    except (OSError, ValueError):
        return None


def for_report(R):
    """보고서에서 부르는 곳: 실패해도 보고서는 만든다 -> (I 또는 None, 오류 글)."""
    try:
        return compute(R, R.get("auto_facts"), R.get("_invoices"), R.get("auto_prev")), ""
    except Exception as e:   # 자동 분석 때문에 보고서를 못 만들면 안 된다
        return None, "%s: %s" % (type(e).__name__, str(e)[:120])
