"""연간 보고 (사용자 2026-11-10 목업 승인: mockups/연간/).

- 변환 쪽: build_table(books, cfg, sales, prev_rows) → 연간자료.csv (연도마다 거래처별 매출·매입, 통장 흐름 분류, 결산 법인세·선납세금).
- 보고 쪽: compute(input_dir, year) → 숫자, render(A, mode) → 대표용·경영관리용 HTML. 보고서.py 연간 --연도 가 부른다.

기준 (월간과 같음): 매출·매입은 분개장 전표일자(증빙 작성일자) 기준, 손익 순서는 위하고 양식(영업이익 → 영업외 수익 → 영업외 비용 → 세전 이익),
추정 예산 = 사전견적 × (1 − 그 팀 목표 수익률), 거래처는 '거래처명 [코드]'. 12월 월간과 겹치는 것은 요약만 (사용자 2026-11-10):
연간은 작년 대비·결산 확정치·거래처 쏠림과 변화·돈 받는 속도·비용 구조·한 해 현금 흐름·팀 분기 추이·내년 준비에 무게.
"""
import collections
import csv
import datetime as dt
import math
import os
import re

from .util import won, esc, num, date as parse_date

FILE = "연간자료.csv"
KEYS = ["연도", "구분", "항목", "코드", "금액"]
OPENING = ("전기이월", "기초잔액")
CF_ORDER = ("자본금 납입", "영업 입금", "영업 지급", "세금", "투자", "대출 받음", "대출 갚음")


# ───────────── 변환 쪽 ─────────────
def _sq(text):
    return re.sub(r"\s+", "", text or "")


def _cash_class(line):
    """보통예금 상대 줄 하나 → 분류 (자본·세금·투자·대출·영업)."""
    code, name = _sq(line.get("account_code")), _sq(line.get("account"))
    if code[:1] == "3" or "자본금" in name:
        return "자본"
    if any(w in name for w in ("부가세", "예수금", "선납세금", "법인세", "세금과공과", "부가가치세")):
        return "세금"
    if "차입금" in name:
        return "대출"
    if code.isdigit() and 20000 <= int(code) < 24000:   # 유형·무형자산
        return "투자"
    return "영업"


def cash_flow(journal, cash_codes):
    """분개장 보통예금 줄 → {연도: {분류: 금액}}. 같은 전표에 보통예금 차변·대변이 다 있으면 계좌간이체라 뺀다.
    상대 줄이 여럿이면 금액이 가장 큰 줄의 계정으로 나눈다. 전기이월·기초잔액 줄은 넣지 않는다."""
    cash = set(_sq(c) for c in cash_codes)
    slips = collections.defaultdict(list)
    for ln in journal:
        if ln.get("date") is not None:
            slips[(ln["date"], ln.get("no"))].append(ln)
    out = collections.defaultdict(lambda: collections.defaultdict(int))
    for (d, _), lines in slips.items():
        mine = [ln for ln in lines if _sq(ln.get("account_code")) in cash]
        if not mine:
            continue
        if any(ln["debit"] for ln in mine) and any(ln["credit"] for ln in mine):
            continue
        if any(w in (ln.get("memo") or "") for ln in mine for w in OPENING):
            continue
        others = [ln for ln in lines if _sq(ln.get("account_code")) not in cash]
        main = max(others, key=lambda o: abs((o["debit"] or 0) - (o["credit"] or 0)), default=None)
        kind = _cash_class(main) if main else "영업"
        v = sum((ln["debit"] or 0) - (ln["credit"] or 0) for ln in mine)
        if not v:
            continue
        y = str(d.year)
        if kind == "자본":
            item = "자본금 납입"
        elif kind == "대출":
            item = "대출 받음" if v > 0 else "대출 갚음"
        elif kind in ("세금", "투자"):
            item = kind
        else:
            item = "영업 입금" if v > 0 else "영업 지급"
        out[y][item] += v
    return out


def _codes(journal):
    """거래처명 → 코드 (분개장에서 가장 많이 나온 것)."""
    c = collections.defaultdict(collections.Counter)
    for ln in journal:
        n, k = (ln.get("vendor") or "").strip(), (ln.get("vendor_code") or "").strip().lstrip("0")
        if n and k:
            c[n][k] += 1
    return dict((n, cnt.most_common(1)[0][0]) for n, cnt in c.items())


def build_table(books, cfg, sales, prev_rows=()):
    """연간자료.csv Table. 새 분개장에 없는 해의 이전 줄은 그대로 잇는다 (작년 분개장을 빼고 변환해도 작년 자료가 남게)."""
    from .convert import Table
    if books.state != "ok":
        return Table(FILE, KEYS, [], written=False, reason="분개장 없음 (기존 파일 그대로)")
    journal = books.journal
    codes = _codes(journal)
    rows = []
    years = set()

    def add(y, kind, item, code, amount):
        years.add(y)
        rows.append(dict(zip(KEYS, [y, kind, item, code, str(int(amount))])))
    for kind, src in (("매출거래처", sales.get("rows") if sales.get("state") == "ok" else None), ("매입거래처", books.ledger)):
        agg = collections.defaultdict(int)
        for r in src or []:
            if r.get("date") is None or r.get("supply") is None:
                continue
            agg[(str(r["date"].year), (r.get("vendor") or "").strip() or "(거래처 없음)")] += r["supply"]
        for (y, n), v in sorted(agg.items()):
            add(y, kind, n, codes.get(n, ""), v)
    for y, items in sorted(cash_flow(journal, cfg["cash_codes"]).items()):
        for item in CF_ORDER:
            if item in items:
                add(y, "현금흐름", item, "", items[item])
    prepaid = set(_sq(c) for c in cfg.get("prepaid_tax_codes", ("13600",)))
    tax, pre = collections.defaultdict(int), collections.defaultdict(int)
    for ln in journal:
        if ln.get("date") is None:
            continue
        y, code = str(ln["date"].year), _sq(ln.get("account_code"))
        if "법인세" in _sq(ln.get("account")) and code[:1] == "9":
            tax[y] += (ln["debit"] or 0) - (ln["credit"] or 0)
        elif code in prepaid:
            pre[y] += ln["debit"] or 0
    for y in sorted(set(tax) | set(pre)):
        if tax.get(y):
            add(y, "결산", "법인세등", "", tax[y])
        if pre.get(y):
            add(y, "결산", "선납세금", "", pre[y])
    keep = [r for r in prev_rows if r.get("연도") not in years]
    rows = keep + rows
    rows.sort(key=lambda r: (r["연도"], KEYS.index("구분"), r["구분"]))
    return Table(FILE, KEYS, rows, notes=["연도 %s · 거래처별 매출·매입, 통장 흐름 분류, 결산 법인세" % ", ".join(sorted(years))])


# ───────────── 읽기 ─────────────
def _read(path):
    if not os.path.exists(path):
        return []
    for enc in ("utf-8-sig", "cp949"):
        try:
            with open(path, encoding=enc, newline="") as f:
                return [dict((k.strip(), (v or "").strip()) for k, v in r.items() if k) for r in csv.DictReader(f)]
        except UnicodeDecodeError:
            continue
    return []


def _n(v):
    return num(v) if v not in (None, "") else None


def _rate(text):
    v = str(text or "").replace("%", "").strip()
    try:
        x = float(v)
    except ValueError:
        return None
    return x / 100.0 if x > 1 else x


def _end_day(p):
    """행사 끝난 날: 완료일, 없으면 행사일(기간이면 끝난 날)."""
    from .calc import _event_date
    return parse_date(p.get("완료일")) or _event_date(p.get("행사일"))


# ───────────── 계산 ─────────────
def _year_pl(rows, dept, accts, year):
    """한 해 회사 손익. 없으면 None."""
    co = [r for r in rows if r["연월"][:4] == year and r["단위"] == "회사"]
    if not co:
        return None
    m = dict((int(r["연월"][5:7]), r) for r in co)
    P = {"months": sorted(m), "rev_m": [0] * 12, "cogs_m": [0] * 12, "common_m": [0] * 12}
    for k, r in m.items():
        P["rev_m"][k - 1] = _n(r["매출"]) or 0
        P["cogs_m"][k - 1] = _n(r["직접비"]) or 0
        P["common_m"][k - 1] = _n(r["공통비"]) or 0
    P["op_m"] = [P["rev_m"][i] - P["cogs_m"][i] - P["common_m"][i] for i in range(12)]
    P["rev"], P["cogs"], P["common"] = sum(P["rev_m"]), sum(P["cogs_m"]), sum(P["common_m"])
    P["gp"] = P["rev"] - P["cogs"]
    P["op"] = sum(P["op_m"])
    dr = [r for r in dept if r.get("연월", "")[:4] == year]
    P["sal"] = sum(_n(r.get("급여")) or 0 for r in dr)
    P["nin"] = sum(_n(r.get("영업외수익")) or 0 for r in dr)
    P["nout"] = sum(_n(r.get("영업외비용")) or 0 for r in dr)
    ar = [r for r in accts if r.get("연월", "")[:4] == year and "판매" in r.get("구분", "")]
    P["dep"] = sum(_n(r.get("금액")) or 0 for r in ar if "감가상각비" in r.get("계정과목", ""))
    P["acct"] = collections.OrderedDict()
    for r in ar:
        P["acct"][r["계정과목"]] = P["acct"].get(r["계정과목"], 0) + (_n(r.get("금액")) or 0)
    if not P["sal"] and ar:
        P["sal"] = sum(v for k, v in P["acct"].items() if "급여" in k)
    P["other"] = P["common"] - P["sal"] - P["dep"]
    P["pre"] = P["op"] + P["nin"] - P["nout"]
    P["full"] = len(P["months"]) == 12
    return P


def compute(input_dir, year, settings=None, D=None):
    from .corptax import corp_tax, read as read_dep
    Y, LY, NY = str(year), str(year - 1), str(year + 1)
    pl = [r for r in _read(os.path.join(input_dir, "손익.csv")) if r.get("연월")]
    co_rows = [r for r in pl if r.get("출처") == "WEHAGO"] or pl
    dept = _read(os.path.join(input_dir, "부서비용.csv"))
    accts = _read(os.path.join(input_dir, "계정별비용.csv"))
    A = {"year": year, "settings": settings or {}, "notes": []}
    A["Y"] = _year_pl(co_rows, dept, accts, Y)
    A["L"] = _year_pl(co_rows, dept, accts, LY)
    if A["Y"] is None:
        return A
    Yp, Lp = A["Y"], A["L"]
    ev = dict((r["연월"], _n(r.get("매입"))) for r in _read(os.path.join(input_dir, "증빙월별.csv")) if r.get("연월"))
    Yp["buy_m"] = [ev.get("%s-%02d" % (Y, i + 1)) for i in range(12)]
    Yp["buy"] = sum(v or 0 for v in Yp["buy_m"])
    ann = _read(os.path.join(input_dir, FILE))
    A["has_annual"] = bool(ann)
    get = lambda y, kind: [(r["항목"], r.get("코드", ""), _n(r["금액"]) or 0) for r in ann if r.get("연도") == y and r.get("구분") == kind]

    # 결산 확정치: 감가상각비·법인세 (사용자 2026-11-10: 결산 확정치와 연중 예상 차이 한 줄)
    manual = read_dep(input_dir)
    dep_est = manual.get(Y)
    dep_src = "직접 입력"
    if dep_est is None:
        dep_est, dep_src = (Lp["dep"] if Lp else None), "작년 장부"
    A["dep_est"], A["dep_src"] = dep_est, dep_src
    A["closed"] = Yp["dep"] > 0   # 12월 결산 전표(감가상각비)가 들어왔는지
    if not A["closed"] and dep_est:
        Yp["dep_pending"] = dep_est
        Yp["pre"] -= dep_est   # 결산 전: 월간과 같게 감가상각비 예상을 먼저 비용으로
    pre_est = Yp["pre"] + (Yp["dep"] - (dep_est or 0) if A["closed"] else 0)
    c_est = corp_tax(pre_est, Y)
    A["tax_est"] = c_est + c_est // 10
    booked = dict((n, v) for n, _, v in get(Y, "결산"))
    A["prepaid"] = booked.get("선납세금", 0)
    if booked.get("법인세등"):
        A["tax"], A["tax_fixed"] = booked["법인세등"], True
        A["corp"] = int(round(A["tax"] * 10 / 11.0))
    else:
        A["corp"] = corp_tax(Yp["pre"], Y)
        A["tax"], A["tax_fixed"] = A["corp"] + A["corp"] // 10, False
    A["local"] = A["tax"] - A["corp"]
    Yp["net"] = Yp["pre"] - A["tax"]
    if Lp:
        lb = dict((n, v) for n, _, v in get(LY, "결산"))
        Lp["tax"] = lb.get("법인세등")
        if Lp["tax"] is None:
            lc = corp_tax(Lp["pre"], LY)
            Lp["tax"] = lc + lc // 10
        Lp["net"] = Lp["pre"] - Lp["tax"]
    A["pay_corp_day"] = _workday(dt.date(year + 1, 3, 31))
    A["pay_local_day"] = _workday(dt.date(year + 1, 4, 30))

    # 통장
    bal = collections.defaultdict(int)
    for r in _read(os.path.join(input_dir, "장부잔액.csv")):
        d = parse_date(r.get("기준일"))
        if d is not None:
            bal[d] += _n(r.get("잔액")) or 0
    ends = {}
    for d in sorted(bal):
        ends[(d.year, d.month)] = bal[d]   # 그 달 마지막 스냅숏
    A["bal_m"] = [ends.get((year, m)) for m in range(1, 13)]
    first = min(bal) if bal else None
    A["bal0"] = ends.get((year - 1, 12), 0 if first and first.year >= year else None)
    A["bal_end"] = next((v for v in reversed(A["bal_m"]) if v is not None), None)
    from . import cashflow   # 연간 현금흐름표 (사용자 2026-11-12): 1월 1일 잔액은 장부(작년 분개장 있을 때)
    A["cfs"] = cashflow.annual(cashflow.load(input_dir), year, A["bal_end"], A["bal0"])
    A["cf"] = [(n, v) for n, _, v in get(Y, "현금흐름")]
    A["cf"].sort(key=lambda x: CF_ORDER.index(x[0]) if x[0] in CF_ORDER else 99)
    if A["cf"] and A["bal0"] is not None and A["bal_end"] is not None:
        A["cf_gap"] = A["bal_end"] - A["bal0"] - sum(v for _, v in A["cf"])

    # 거래처
    def vend(y, kind):
        lst = sorted(get(y, kind), key=lambda x: -x[2])
        return [x for x in lst if x[2] > 0]
    A["cust"], A["vend"] = vend(Y, "매출거래처"), vend(Y, "매입거래처")
    A["lcust"] = vend(LY, "매출거래처")
    if A["cust"] and A["lcust"]:
        cy, cl = dict((n, v) for n, _, v in A["cust"]), dict((n, v) for n, _, v in A["lcust"])
        code = dict((n, c) for n, c, _ in A["cust"] + A["lcust"])
        A["new"] = sorted([(n, code[n], cy[n]) for n in cy if n not in cl], key=lambda x: -x[2])
        A["lost"] = sorted([(n, code[n], cl[n]) for n in cl if n not in cy], key=lambda x: -x[2])
        A["kept"] = [n for n in cl if n in cy]

    # 프로젝트·돈 받는 속도
    projs = dict((r.get("프로젝트번호", "").strip(), r) for r in _read(os.path.join(input_dir, "프로젝트.csv")) if r.get("프로젝트번호"))
    A["speed"], A["lspeed"] = _speed(_read(os.path.join(input_dir, "계산서.csv")), projs, year), _speed(_read(os.path.join(input_dir, "계산서.csv")), projs, year - 1)

    # 팀
    goals = dict(((r.get("연도", "").strip(), r.get("팀", "").strip()), (_n(r.get("매출목표")), _rate(r.get("목표수익률"))))
                 for r in _read(os.path.join(input_dir, "팀목표.csv")))
    A["goals"], A["goals_next"] = goals, dict((t, v) for (y, t), v in goals.items() if y == NY)
    A["teams"] = _teams(co_rows, dept, Y, LY, goals)
    A["proj"] = _projects(pl, projs, Y, LY, goals)
    A["next"] = _next_projects(input_dir, year, D)
    return A


def _workday(d):
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def _speed(invoices, projs, year):
    """행사 끝난 날 → 입금일 (그 해 입금된 계산서). 선입금(행사 전 입금)은 따로 센다."""
    rows = []
    for r in invoices:
        paid = parse_date(r.get("입금일"))
        if paid is None or paid.year != year:
            continue
        p = projs.get(r.get("프로젝트번호", "").strip())
        end = _end_day(p) if p else None
        if end is None:
            continue
        rows.append((r.get("거래처", "").strip(), r.get("프로젝트번호", ""), (p.get("프로젝트명") or ""), end, paid, (paid - end).days,
                     _n(r.get("입금액")) or 0))
    after = [x for x in rows if x[5] >= 0]
    if not after:
        return {"n": 0, "pre": len(rows)}
    by = collections.defaultdict(list)
    for x in after:
        by[x[0]].append(x[5])
    late = sorted(((v, sum(d) / float(len(d)), len(d)) for v, d in by.items()), key=lambda x: -x[1])
    return {"n": len(after), "pre": len(rows) - len(after), "avg": sum(x[5] for x in after) / float(len(after)),
            "over60": sorted([x for x in after if x[5] > 60], key=lambda x: -x[5]), "late": late}


def _teams(rows, dept, Y, LY, goals):
    names = []
    for r in rows:
        if r["단위"] == "팀" and r["연월"][:4] == Y and r["대상"] not in names and r["대상"].endswith("팀"):
            names.append(r["대상"])
    out = []
    for t in names:
        def months(y):
            rv, gp = [0] * 12, [0] * 12
            for r in rows:
                if r["단위"] == "팀" and r["대상"] == t and r["연월"][:4] == y:
                    i = int(r["연월"][5:7]) - 1
                    rv[i] += _n(r["매출"]) or 0
                    gp[i] += (_n(r["매출"]) or 0) - (_n(r["직접비"]) or 0)
            return rv, gp
        rv, gp = months(Y)
        lrv, _ = months(LY)
        cost, heads = [0] * 12, []
        for r in dept:
            if r.get("부서", "").strip() == t and r.get("연월", "")[:4] == Y:
                i = int(r["연월"][5:7]) - 1
                cost[i] += (_n(r.get("급여")) or 0) + (_n(r.get("판관비")) or 0)
                if _n(r.get("인원")):
                    heads.append(_n(r.get("인원")))
        n = sum(heads) / float(len(heads)) if heads else None
        q = []
        for k in range(5):
            sl = slice(0, 12) if k == 4 else slice(k * 3, k * 3 + 3)
            r_, g_, c_ = sum(rv[sl]), sum(gp[sl]), sum(cost[sl])
            q.append((g_ / float(r_) if r_ else None, int(round((g_ - c_) / n)) if n else None))
        out.append({"name": t, "rev": sum(rv), "gp": sum(gp), "lrev": sum(lrv) if any(lrv) else None, "goal": goals.get((Y, t)),
                    "heads": n, "q": q})
    return out


def _projects(pl, projs, Y, LY, goals):
    """행사가 그 해에 끝난 프로젝트: 팀별 건수·평균 수익률·목표 수익률 미달·적자."""
    def agg(y):
        P = collections.OrderedDict()
        for r in pl:
            if r.get("단위") != "프로젝트":
                continue
            pid = (r.get("대상") or "").split(" ")[0]
            p = projs.get(pid)
            if not p:
                continue
            end = _end_day(p)
            if end is None or str(end.year) != y:
                continue
            x = P.setdefault(pid, {"id": pid, "name": p.get("프로젝트명", ""), "team": p.get("팀", ""), "rev": 0, "cost": 0})
            x["rev"] += _n(r.get("매출")) or 0
            x["cost"] += _n(r.get("직접비")) or 0
        return [x for x in P.values() if x["rev"] > 0]
    cur, last = agg(Y), agg(LY)
    teams = collections.OrderedDict()
    for x in cur:
        x["rate"] = (x["rev"] - x["cost"]) / float(x["rev"])
        g = goals.get((Y, x["team"]))
        x["target"] = g[1] if g else None
        teams.setdefault(x["team"], []).append(x)
    lcount = collections.Counter(x["team"] for x in last)
    return {"list": cur, "teams": teams, "lcount": lcount, "lall": len(last)}


def _next_projects(input_dir, year, D=None):
    """다음 해 행사 프로젝트: 사전견적·추정 예산·집행액·잔여 (월간과 같은 계산)."""
    from .calc import compute as calc_compute, _event_date
    from .data import load
    try:
        R = calc_compute(D if D is not None else load(input_dir), "monthly", dt.date(year, 12, 31), None, None, None)
    except Exception:   # 프로젝트 자료가 없거나 읽지 못하면 이 칸만 비운다
        return None
    out = []
    for P in R["s3"]["projects"]:
        ev = _end_day(P.get("row") or {}) or _event_date(P.get("event_date"))
        if ev is None or ev.year != year + 1:
            continue
        out.append({"id": P["id"], "name": P["name"], "team": P.get("team") or "", "day": ev, "est": P.get("estimate"),
                    "budget": P.get("budget"), "paid": P.get("paid_total") or 0})
    out.sort(key=lambda x: (x["team"], x["day"]))
    return out


# ───────────── 문서 ─────────────
def pct(a, b):
    return "%.1f%%" % (100.0 * a / b) if b else "—"


def chg(a, b):
    if a is None or not b:
        return "—"
    v = (a - b) * 100.0 / abs(b)
    return ("+" if v >= 0 else "−") + "%.1f%%" % abs(v)


def sgn(v):
    return "—" if v is None else ("+" if v >= 0 else "−") + "{:,}".format(abs(int(v)))


def W(v):
    return won(v, "—")


def _vname(n, c):
    return "%s [%s]" % (esc(n), esc(c)) if c else esc(n)


def _card(lab, big, foot=""):
    return "<div class='card'><div class='lab'>%s</div><div class='big'>%s</div><div class='foot'>%s</div></div>" % (lab, big, foot)


def _q(t, ev=""):
    return "<div class='q'>%s%s</div>" % (t, ("<span class='ev'>%s</span>" % ev) if ev else "")


def _tab(head, rows, cls="pt pl", tot=None):
    o = ["<table class='%s'><thead><tr>%s</tr></thead><tbody>" % (cls, "".join("<th>%s</th>" % x for x in head))]
    for r in rows:
        o.append("<tr>%s</tr>" % "".join("<td>%s</td>" % x for x in r))
    if tot:
        o.append("<tr class='tot'>%s</tr>" % "".join("<td>%s</td>" % x for x in tot))
    return "".join(o) + "</table>"


EXTRA_CSS = (".pl td{text-align:right}.pl td:first-child{text-align:left}.pl tr.ind td:first-child{padding-left:16px;color:var(--sub)}"
             ".cf{display:grid;grid-template-columns:1fr 1fr;gap:10px}.cf table.pt td{text-align:right}.cf table.pt td:first-child,.cf table.pt td:nth-child(2){text-align:left}"
             ".conc{font-size:12px;margin-top:4px}.conc b{font-size:14px}.fix{font-size:12px;line-height:1.6}"
             ".yl{font-size:13px;padding:6px 12px;margin:6px 0 0;border-left:4px solid var(--accent);background:var(--soft);border-radius:4px}"
             "table.pt.tgy td{text-align:right}table.pt.tgy td:first-child,table.pt.tgy.jg td:last-child{text-align:left}table.pt.tgy th{text-align:right}"
             "table.pt.tgy th:first-child,table.pt.tgy.jg th:last-child{text-align:left}.up{color:var(--out);font-weight:700}td.blank{color:var(--est)}"
             "table.pt.m12{font-size:8.6px!important;table-layout:fixed;width:100%}table.pt.m12 td,table.pt.m12 th{padding:2px 1px!important;text-align:right}"
             "table.pt.m12 td:first-child,table.pt.m12 th:first-child{width:62px;text-align:left}@media print{.fs.mon table.pt{font-size:11.5px}}")


def _season_chart(A):
    from .render import _nice_step, _axis
    Yp, Lp = A["Y"], A["L"]
    rev, op = Yp["rev_m"], Yp["op_m"]
    lrev = [None] * 12
    if Lp:
        lrev = [Lp["rev_m"][i] if (i + 1) in Lp["months"] else None for i in range(12)]
    rows = [("올해 매출", rev)] + ([("작년 매출", lrev)] if Lp else []) + [("올해 영업이익", op)]
    Wd, pl_, pr, pt_, H, RH = 900, 74, 10, 18, 280, 18
    pb = 30 + RH * len(rows) + 6
    H2 = H + RH * len(rows) + 6
    vals = [0] + rev + [v for v in lrev if v] + op
    step = _nice_step((max(vals) - min(vals)) / 4.0 or 1)
    hi, lo = step * math.ceil(max(vals) / step), step * math.floor(min(vals) / step)
    if hi == lo:
        hi = lo + step
    y = lambda v: pt_ + (hi - v) * (H2 - pt_ - pb) / float(hi - lo)
    gw = (Wd - pl_ - pr) / 12.0
    bw = gw * 0.3
    s = ['<svg viewBox="0 0 %d %d" width="100%%" role="img" aria-label="달별 매출 올해와 작년">' % (Wd, H2)]
    k = 0
    while lo + step * k <= hi:
        v = lo + step * k
        s.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#e6e9ef"/><text x="%d" y="%.1f" font-size="14" text-anchor="end" fill="#5b6475">%s</text>'
                 % (pl_, Wd - pr, y(v), y(v), pl_ - 5, y(v) + 4, _axis(v)))
        k += 1
    s.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#1d2433"/>' % (pl_, Wd - pr, y(0), y(0)))
    base = y(lo) + 20
    pts = []
    for i in range(12):
        cx = pl_ + i * gw + gw / 2
        for x0, v, col in ((cx - bw - 1, rev[i], "#6b98dc"), (cx + 1, lrev[i], "#c3ccd9")):
            if v and v > 0:
                s.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" fill="%s"/>' % (x0, y(v), bw, y(0) - y(v), col))
        if (i + 1) in Yp["months"]:
            pts.append((cx, y(op[i]), op[i]))
        s.append('<text x="%.1f" y="%.1f" font-size="14" text-anchor="middle" fill="#5b6475">%d월</text>' % (cx, base, i + 1))
        for j, (_, ser) in enumerate(rows):
            v = ser[i]
            s.append('<text x="%.1f" y="%.1f" font-size="11.5" text-anchor="middle" fill="%s">%s</text>'
                     % (cx, base + 8 + RH * (j + 1), "#a8432f" if (v or 0) < 0 else "#1d2433", won(v, "-") if v is not None else "-"))
    if pts:
        s.append('<polyline points="%s" fill="none" stroke="#1f4e8c" stroke-width="2"/>' % " ".join("%.1f,%.1f" % (a, b) for a, b, _ in pts))
        for a, b, v in pts:
            s.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s" stroke="#fff" stroke-width="2"/>' % (a, b, "#b5523b" if v < 0 else "#1f4e8c"))
    s.append('<line x1="8" x2="%d" y1="%.1f" y2="%.1f" stroke="#e6e9ef"/>' % (Wd - pr, base + 7, base + 7))
    for j, (lab, _) in enumerate(rows):
        s.append('<text x="8" y="%.1f" font-size="11.5" fill="#5b6475" font-weight="600">%s</text>' % (base + 8 + RH * (j + 1), lab))
    s.append("</svg>")
    leg = ("<div class='legend'><span><i style='background:#6b98dc'></i>올해 매출</span>%s<span><i style='background:#1f4e8c;height:2px;margin-bottom:4px'></i>"
           "올해 영업이익 (빨간 점 = 손실 달)</span></div>" % ("<span><i style='background:#c3ccd9'></i>작년 매출</span>" if Lp else ""))
    top2 = sorted(range(12), key=lambda i: -rev[i])[:2]
    low2 = sorted([i for i in range(12) if (i + 1) in Yp["months"]], key=lambda i: rev[i])[:2]
    line = "매출 많은 달: 올해 %s" % "·".join("%d월" % (i + 1) for i in sorted(top2))
    both = [i for i in range(12) if lrev[i]]
    if both:
        ltop = sorted(both, key=lambda i: -lrev[i])[:2]
        odd = max(both, key=lambda i: abs(rev[i] - lrev[i]))
        line += ", 작년 %s · 적은 달 %s · 유난한 달 %d월: 작년 같은 달보다 %s (%s)" % (
            "·".join("%d월" % (i + 1) for i in sorted(ltop)), "·".join("%d월" % (i + 1) for i in sorted(low2)), odd + 1,
            sgn(rev[odd] - lrev[odd]), chg(rev[odd], lrev[odd]))
    return ("<div class='card mchart'><div class='lab'>달별 매출: 올해%s, 올해 영업이익</div>%s%s<div class='yl' style='font-size:12px'>%s</div></div>"
            % (" 대 작년" if Lp else "", "".join(s), leg, esc(line)))


def _waterfall(A):
    items = [("연초 잔액", A["bal0"], "s")] + [(n, v, "d") for n, v in A["cf"]] + [("연말 잔액", A["bal_end"], "s")]
    Wd, H, lp, rp, tp, bp = 900, 250, 10, 10, 26, 44
    run, tops = 0, [0]
    for n, v, k in items:
        run = v if k == "s" else run + v
        tops.append(run)
    mx = max(tops) * 1.05 or 1
    mn = min(0, min(tops))
    yy = lambda v: tp + (mx - v) * (H - tp - bp) / float(mx - mn)
    cw = (Wd - lp - rp) / float(len(items))
    s = ['<svg viewBox="0 0 %d %d" width="100%%" role="img" aria-label="한 해 현금 흐름">' % (Wd, H)]
    cur = 0
    for i, (lab, v, kd) in enumerate(items):
        x, w = lp + i * cw + cw * 0.15, cw * 0.7
        if kd == "s":
            a, b, col = 0, v, "#1f4e8c"
            cur = v
        else:
            a, b = cur, cur + v
            col = "#2f7d5b" if v > 0 else "#b5523b"
            cur = b
        top, bot = yy(max(a, b)), yy(min(a, b))
        s.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" rx="2"/>' % (x, top, w, max(bot - top, 1.5), col))
        s.append('<text x="%.1f" y="%.1f" font-size="12.5" text-anchor="middle" fill="#1d2433" font-weight="700">%s</text>'
                 % (x + w / 2, top - 6, won(v) if kd == "s" else sgn(v)))
        s.append('<text x="%.1f" y="%.1f" font-size="13" text-anchor="middle" fill="#5b6475">%s</text>' % (x + w / 2, H - 18, esc(lab)))
        if i < len(items) - 1:
            s.append('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="#9aa3b2" stroke-dasharray="3 3"/>' % (x + w, x + cw, yy(cur), yy(cur)))
    s.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#1d2433"/>' % (lp, Wd - rp, yy(0), yy(0)))
    return "".join(s) + "</svg>"


def _vtab(title, lst, total, extra=""):
    rr = ["<div class='card'><div class='wsub' style='margin-top:0'>%s</div><table class='pt'><thead><tr><th>순위</th><th>거래처</th><th>금액</th><th>비중</th></tr></thead><tbody>" % title]
    for i, (n, c, v) in enumerate(lst[:5], 1):
        rr.append("<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (i, _vname(n, c), W(v), pct(v, total)))
    rest = total - sum(v for _, _, v in lst[:5])
    if len(lst) > 5:
        rr.append("<tr class='mut'><td></td><td>그 밖 %d곳</td><td>%s</td><td>%s</td></tr>" % (len(lst) - 5, W(rest), pct(rest, total)))
    rr.append("</tbody></table><div class='conc'>상위 3곳 <b>%s</b>%s</div></div>" % (pct(sum(v for _, _, v in lst[:3]), total), extra))
    return "".join(rr)


def _top3(lst):
    t = sum(v for _, _, v in lst)
    return (sum(v for _, _, v in lst[:3]) / float(t)) if t else None


def render(A, mode):
    from . import render as RD
    st = A["settings"]
    year = A["year"]
    Yp, Lp = A["Y"], A["L"]
    who = "보고" if mode == "ceo" else "경영관리 보고"
    h = ["<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         "<title>%s %d년 연간 %s</title><style>%s%s</style></head><body><div class='wrap mon'>"
         % (esc(st.get("회사명", "")), year, who, RD.CSS + RD.FS_CSS + RD.DOC_CSS + RD.DOC2_CSS + RD.DOC3_CSS + RD.AIR_CSS + RD.TYPE_CSS, EXTRA_CSS)]
    h.append("<div class='doc-h'><h1><span class='co'>%s</span>%d년 연간 %s%s</h1>" % (
        esc(st.get("회사명", "")), year, who, "" if mode == "ceo" else " <span class='badge m'>경영관리용</span>"))
    h.append("<table class='dinfo'><tr><th>보고 기준일</th><td>%d-12-31</td><th>집계 기간</th><td>%d-01-01 ~ %d-12-31</td></tr>"
             "<tr><th>작성</th><td>%s</td><th>금액 단위</th><td>원</td></tr></table>"
             % (year, year, year, dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
    if Yp is None:
        h.append("<div class='warnbar'>%d년 손익 자료가 없습니다. 위하고 분개장을 받아 '자료 변환'을 먼저 하세요.</div></div></body></html>" % year)
        return "".join(h)
    meta = ["결산 전표 %s" % ("반영됨" if A["closed"] else "아직 없음 (감가상각비·법인세는 예상)")]
    if not Yp["full"]:
        meta.append("%d년 손익 %d개월치 (%d월까지)" % (year, len(Yp["months"]), Yp["months"][-1]))
    meta.append("작년 = %d년%s" % (year - 1, " (%d개월)" % len(Lp["months"]) if Lp and not Lp["full"] else ("" if Lp else " 자료 없음")))
    h.append("<div class='meta dsrc'>%s</div></div>" % esc(" · ".join(meta)))
    sum_i = len(h)
    h.append("<div class='page fs mon'>")
    goal_all = sum((A["goals"].get((str(year), t["name"])) or (0, 0))[0] or 0 for t in A["teams"])
    lm = "(%d개월)" % len(Lp["months"]) if Lp and not Lp["full"] else ""

    # ── 1쪽: 한 해 요약 ──
    h.append("<div class='four top'>")
    h.append(_card("%d년 매출" % year, W(Yp["rev"]), ("작년 %s · %s" % (W(Lp["rev"]), chg(Yp["rev"], Lp["rev"])) if Lp else "")
                   + ("<br>연 목표 %s의 %s" % (W(goal_all), pct(Yp["rev"], goal_all)) if goal_all else "")))
    h.append(_card("영업이익", W(Yp["op"]), "영업이익률 %s%s" % (pct(Yp["op"], Yp["rev"]), " · 작년 %s" % W(Lp["op"]) if Lp else "")))
    h.append(_card("세전 이익", W(Yp["pre"]), "작년 %s · %s" % (W(Lp["pre"]), chg(Yp["pre"], Lp["pre"])) if Lp else ""))
    h.append(_card("연말 통장 잔액", W(A["bal_end"]), "연초 %s · %s" % (W(A["bal0"]), sgn(A["bal_end"] - A["bal0"]))
                   if A["bal0"] is not None and A["bal_end"] is not None else ""))
    h.append("</div>")
    if Lp:
        h.append("<div class='yl'><b>작년 대비</b> 매출 %s, 영업이익 %s, 세전 이익 %s, 영업이익률 %s → %s%s</div>"
                 % (chg(Yp["rev"], Lp["rev"]), chg(Yp["op"], Lp["op"]), chg(Yp["pre"], Lp["pre"]), pct(Lp["op"], Lp["rev"]),
                    pct(Yp["op"], Yp["rev"]), " (작년은 %d개월)" % len(Lp["months"]) if not Lp["full"] else ""))
    h.append("<div class='sec'>" + _q("1. %d년 손익 (%s)" % (year, "결산 확정" if A["closed"] and A["tax_fixed"] else "결산 전"), "근거 1-1~1-2"))
    rows = [("매출", "rev", ""), ("− 매출원가", "cogs", ""), ("매출총이익", "gp", "hq"), ("− 판매비와관리비", "common", ""),
            ("급여", "sal", "ind"), ("감가상각비", "dep", "ind"), ("그 밖의 판관비", "other", "ind"), ("영업이익", "op", "tot"),
            ("+ 영업외 수익", "nin", ""), ("− 영업외 비용", "nout", "")]
    if Yp.get("dep_pending"):
        rows.append(("− 감가상각비 예상 (결산 전)", "dep_pending", ""))
    rows += [("세전 이익", "pre", "tot"), ("− 법인세 등 (지방소득세 포함)", "tax", ""), ("당기순이익", "net", "tot")]
    Yp["tax"] = A["tax"]
    t = ["<div class='card'><table class='pt pl'><thead><tr><th>구분</th><th>%d년</th><th>매출 대비</th>%s</tr></thead><tbody>"
         % (year, "<th>%d년 %s</th><th>증감</th><th>증감률</th>" % (year - 1, lm) if Lp else "")]
    for lab, k, cls in rows:
        a = Yp.get(k)
        b = Lp.get(k) if Lp else None
        t.append("<tr class='%s'><td>%s</td><td>%s</td><td>%s</td>%s</tr>" % (
            cls, lab, W(a), pct(a, Yp["rev"]) if a is not None else "",
            "<td>%s</td><td>%s</td><td>%s</td>" % (W(b), sgn(a - b) if a is not None and b is not None else "—", chg(a, b)) if Lp else ""))
    t.append("</tbody></table>")
    fix = []
    if A["closed"]:
        if A["dep_est"]:
            fix.append("· 감가상각비 확정 <b>%s</b> — 연중 예상 %s(%s)보다 %s" % (W(Yp["dep"]), W(A["dep_est"]), A["dep_src"], sgn(Yp["dep"] - A["dep_est"])))
    else:
        fix.append("· 12월 결산 전표가 아직 없어 감가상각비는 예상 %s(%s)를 먼저 뺐습니다" % (W(A["dep_est"]), A["dep_src"]) if A["dep_est"]
                   else "· 12월 결산 전표가 아직 없고 감가상각비 예상도 없습니다")
    if A["tax_fixed"]:
        fix.append("· 법인세 등 확정 <b>%s</b> — 결산 전 예상 %s보다 %s" % (W(A["tax"]), W(A["tax_est"]), sgn(A["tax"] - A["tax_est"])))
    else:
        fix.append("· 법인세 등은 결산 전 예상 (세전 이익 × 세율, 세무조정 없음)")
    t.append("<div class='wsub'>결산 확정치와 연중 예상 차이</div><div class='fix'>%s</div></div></div>" % "<br>".join(fix))
    h.append("".join(t))

    # ── 2쪽: 계절 흐름 · 현금 흐름 ──
    h.append("<div class='sec pgb'>" + _q("2. 계절 흐름 (달별 매출%s)" % (" · 작년 같은 달" if Lp else ""), "근거 2-1") + _season_chart(A) + "</div>")
    if A["cf"] and A["bal0"] is not None:
        lo = [(i, v) for i, v in enumerate(A["bal_m"]) if v is not None]
        low = min(lo, key=lambda x: x[1]) if lo else None
        op_net = sum(v for n, v in A["cf"] if n in ("영업 입금", "영업 지급"))
        taxv = sum(v for n, v in A["cf"] if n == "세금")
        note = "영업으로 남긴 돈 %s · 세금 %s" % (sgn(op_net), W(-taxv))
        if low:
            note += " · 월말 잔액이 가장 적었던 달 %d월 %s" % (low[0] + 1, W(low[1]))
        if A.get("cf_gap"):
            note += " · 분류 못 한 차이 %s" % sgn(A["cf_gap"])
        h.append("<div class='sec'>" + _q("3. 한 해 현금 흐름", "근거 3-1~3-2") + "<div class='card'><div class='lab'>연초 잔액 → 영업 · 세금 · 투자 · 대출 → 연말 잔액</div>"
                 + _waterfall(A) + "<div class='note'>%s</div></div></div>" % esc(note))
    else:
        h.append("<div class='sec'>" + _q("3. 한 해 현금 흐름", "근거 3-1~3-2") + "<div class='note'>통장 흐름 자료 없음 — '자료 변환'을 다시 하면 연간자료.csv 가 생깁니다.</div></div>")

    # ── 3쪽: 거래처 · 팀 ──
    h.append("<div class='sec pgb'>" + _q("4. 거래처: 쏠림 · 변화 · 돈 받는 속도", "근거 4-1~4-3"))
    if A["cust"] or A["vend"]:
        lt = _top3(A["lcust"]) if A["lcust"] else None
        h.append("<div class='cf'>%s%s</div>" % (
            _vtab("매출 상위 5곳 (전체 %d곳)" % len(A["cust"]), A["cust"], sum(v for _, _, v in A["cust"]), " · 작년 %s" % pct(lt, 1) if lt is not None else ""),
            _vtab("매입 상위 5곳 (전체 %d곳)" % len(A["vend"]), A["vend"], sum(v for _, _, v in A["vend"]))))
    else:
        h.append("<div class='note'>거래처 자료 없음 — '자료 변환'을 다시 하면 연간자료.csv 가 생깁니다.</div>")
    if "new" in A:
        tot = sum(v for _, _, v in A["cust"])
        nrev = sum(v for _, _, v in A["new"])
        h.append("<div class='four c3' style='margin-top:8px'>")
        h.append(_card("다시 맡긴 거래처", "%d곳 / 작년 %d곳" % (len(A["kept"]), len(A["lcust"])), "재의뢰율 %s · 올해 매출의 %s" % (pct(len(A["kept"]), len(A["lcust"])), pct(tot - nrev, tot))))
        h.append(_card("새로 생긴 거래처", "%d곳" % len(A["new"]), "올해 매출 %s (%s)" % (W(nrev), pct(nrev, tot))))
        h.append(_card("끊긴 거래처", "%d곳" % len(A["lost"]), "작년 매출 %s · 올해 거래 없음" % W(sum(v for _, _, v in A["lost"]))))
        h.append("</div>")
    S, LS = A["speed"], A["lspeed"]
    if S["n"]:
        code = dict((n, c) for n, c, _ in A["cust"] + A["lcust"])
        h.append("<div class='card' style='margin-top:8px'><div class='flow' style='justify-content:flex-start;gap:26px'>"
                 "<div><div class='lab'>돈 받는 속도 (행사 끝 → 입금)</div><div class='big'>평균 %d일</div></div>%s"
                 "<div><div class='lab'>60일 넘긴 건</div><div class='big vout'>%d건</div></div>"
                 "<div style='flex:1'><div class='lab'>늦게 주는 거래처</div><div style='font-size:13px'>%s</div></div></div></div>"
                 % (round(S["avg"]), "<div><div class='lab'>작년</div><div class='big' style='color:var(--sub)'>%d일</div></div>" % round(LS["avg"]) if LS["n"] else "",
                    len(S["over60"]), " · ".join("%s <b class='up'>%d일</b>" % (_vname(v, code.get(v, "")), round(d)) for v, d, n in S["late"][:3])))
    h.append("</div>")
    h.append("<div class='sec'>" + _q("5. 팀별 한 해 실적 · 연 목표 대비", "근거 5-1~5-3"))
    tt = ["<div class='card'><table class='pt tgy jg'><thead><tr><th>팀</th><th>연 매출 목표</th><th>매출</th><th>달성률</th><th>작년 매출</th><th>작년 대비</th>"
          "<th>매출총이익</th><th>수익률<br><small>실제 / 목표</small></th><th>판정</th></tr></thead><tbody>"]
    for T in A["teams"]:
        g = T["goal"] or (None, None)
        a = T["rev"] * 100.0 / g[0] if g[0] else None
        rate = T["gp"] / float(T["rev"]) if T["rev"] else None
        chip = ""
        if a is not None:
            chip += "<span class='chip c-ok'>목표 이상</span>" if a >= 100 else "<span class='chip c-over'>목표 미달</span>"
        if g[1] is not None and rate is not None:
            chip += "<span class='chip c-ok'>수익률 달성</span>" if rate >= g[1] else "<span class='chip c-over'>수익률 미달</span>"
        tt.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s / %s</td><td>%s</td></tr>" % (
            esc(T["name"]), W(g[0]), W(T["rev"]),
            ("<span class='tbar'><i style='width:%d%%'></i><s style='left:100%%'></s></span>%.1f%%" % (min(a, 100), a)) if a is not None else "목표 없음",
            W(T["lrev"]), chg(T["rev"], T["lrev"]), W(T["gp"]), pct(T["gp"], T["rev"]), "%d%%" % round(g[1] * 100) if g[1] is not None else "—", chip))
    trev, tgp = sum(T["rev"] for T in A["teams"]), sum(T["gp"] for T in A["teams"])
    tl = sum(T["lrev"] or 0 for T in A["teams"]) or None
    tt.append("<tr class='tot'><td>팀 합계</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td></td></tr></tbody></table>"
              % (W(goal_all or None), W(trev), pct(trev, goal_all) if goal_all else "", W(tl), chg(trev, tl), W(tgp), pct(tgp, trev)))
    lines = []
    qs = [(T["name"], T["q"][0][1], T["q"][3][1]) for T in A["teams"] if T["q"][0][1] is not None]
    if qs:
        lines.append("<li><b>분기 추이</b> 1인당 영업이익 %s (1분기 → 4분기)</li>" % ", ".join("%s %s → %s" % (esc(n), W(a), W(b)) for n, a, b in qs))
    PR = A["proj"]
    if PR["list"]:
        n_ = len(PR["list"])
        under = sum(1 for x in PR["list"] if x["target"] is not None and x["rate"] < x["target"])
        loss = sum(1 for x in PR["list"] if x["rate"] < 0)
        lines.append("<li><b>프로젝트</b> %d건%s · 평균 수익률 %.1f%% · 목표 수익률 미달 %d건 · 적자 %d건</li>"
                     % (n_, " (작년 %d건)" % PR["lall"] if PR["lall"] else "", 100.0 * sum(x["rate"] for x in PR["list"]) / n_, under, loss))
    if Lp and Lp["acct"]:
        ups = sorted([(k, v, Lp["acct"].get(k)) for k, v in Yp["acct"].items() if Lp["acct"].get(k) and v > Lp["acct"][k]],
                     key=lambda x: -(x[1] / float(x[2])))[:3]
        lines.append("<li><b>판관비</b> %s (매출 대비 %s → %s) · 많이 늘어난 항목: %s</li>" % (
            chg(Yp["common"], Lp["common"]), pct(Lp["common"], Lp["rev"]), pct(Yp["common"], Yp["rev"]),
            ", ".join("%s %s" % (esc(k), chg(a, b)) for k, a, b in ups) or "없음"))
    if lines:
        tt.append("<ul class='nl' style='font-size:12px;color:var(--ink)'>%s</ul>" % "".join(lines))
    tt.append("</div></div>")
    h.append("".join(tt))

    # ── 4쪽: 다음 해 준비 ──
    h.append("<div class='sec pgb'>" + _q("6. %d년 준비" % (year + 1), "근거 6-1~6-2"))
    h.append("<div class='four c3'>")
    h.append(_card("법인세 납부 (%s)" % "%d/%d" % (A["pay_corp_day"].month, A["pay_corp_day"].day), W(max(A["corp"] - A["prepaid"], 0)),
                   "산출 %s − 중간예납 등 %s%s" % (W(A["corp"]), W(A["prepaid"]), "" if A["tax_fixed"] else " · 예상")))
    h.append(_card("지방소득세 납부 (%s)" % "%d/%d" % (A["pay_local_day"].month, A["pay_local_day"].day), W(A["local"]), "법인세 산출세액 × 10%"))
    dep_next = Yp["dep"] if A["closed"] else A["dep_est"]
    h.append(_card("%d년 감가상각비 예상" % (year + 1), W(dep_next), "%d년 %s 금액 · 월간 보고가 미리 비용으로 뺌" % (year, "확정" if A["closed"] else "예상")))
    h.append("</div>")
    NX = A["next"] or []
    h.append("<div class='card' style='margin-top:8px'><div class='wsub' style='margin-top:0'>%d년 행사 프로젝트 (이미 받은 일)</div>" % (year + 1))
    by = collections.OrderedDict()
    for p in NX:
        by.setdefault(p["team"] or "팀 없음", []).append(p)
    if by:
        rows_ = []
        for tm, ps in by.items():
            b = sum(p["budget"] or 0 for p in ps)
            pd_ = sum(p["paid"] for p in ps)
            rows_.append([esc(tm), "%d건" % len(ps), W(sum(p["est"] or 0 for p in ps)), W(b), W(pd_), W(b - pd_)])
        b = sum(p["budget"] or 0 for p in NX)
        pd_ = sum(p["paid"] for p in NX)
        h.append(_tab(["팀", "건수", "사전견적", "추정 예산", "집행액", "잔여 (지급 예정)"], rows_, "pt tgy",
                      ["합계", "%d건" % len(NX), W(sum(p["est"] or 0 for p in NX)), W(b), W(pd_), W(b - pd_)]))
    else:
        h.append("<div class='note'>%d년 행사 프로젝트 없음</div>" % (year + 1))
    h.append("<div class='wsub'>%d년 목표 (정해 주실 것)</div>" % (year + 1))
    rows_ = []
    for T in A["teams"]:
        g = A["goals_next"].get(T["name"])
        got = sum(p["est"] or 0 for p in NX if p["team"] == T["name"])
        rows_.append([esc(T["name"]), W(T["rev"]), pct(T["gp"], T["rev"]),
                      W(g[0]) if g and g[0] else "<span class='blank'>입력 전</span>",
                      "%d%%" % round(g[1] * 100) if g and g[1] is not None else "<span class='blank'>입력 전</span>",
                      W(got) + (" (%s)" % pct(got, g[0]) if g and g[0] else "")])
    h.append(_tab(["팀", "%d년 매출" % year, "%d년 수익률" % year, "%d년 매출 목표" % (year + 1), "%d년 목표 수익률" % (year + 1), "목표 중 이미 받은 일"], rows_, "pt tgy"))
    if not A["goals_next"]:
        h.append("<div class='note'>%d년 팀 목표는 대표보고 창 '가끔 넣는 값'의 팀 목표에 넣습니다.</div>" % (year + 1))
    h.append("</div></div>")
    if mode == "ceo":
        h.append("<div class='evid'>숫자 옆 ‘근거’ 번호로 요청하시면 경영관리가 해당 근거자료를 제출합니다.<span class='doc-end'>끝.</span></div></div></div></body></html>")
    else:
        # 영역별 보기 (사용자 2026-11-11): 요약 · 위험 분석 · 상세 1~6 을 한 영역씩 (주간·월간 경영관리 보고와 같은 방식)
        from . import areas
        parts = [("sum", "요약 (대표 보고 화면)", "보고 요약", "".join(h[sum_i:]) + "</div>")] + _detail(A)
        parts[-1] = parts[-1][:3] + (parts[-1][3] + "<div class='evid'><span class='doc-end'>끝.</span></div>",)
        h = h[:sum_i]
        for i, (k, lab, g, body) in enumerate(parts):
            if i == 1:
                h.append(areas.nav([(p[0], p[1], p[2], A.get("_risk_hi") if p[0] == "risk" else None) for p in parts]))
            prev = parts[i - 1][:2] if i else None
            nxt = parts[i + 1][:2] if i + 1 < len(parts) else None
            h.append(areas.section(k, lab, body + areas.pager(prev, nxt), g))
        h.append("</div>" + areas.JS + "</body></html>")
    return "".join(h)


def _risks(A):
    out = []
    t3 = _top3(A["cust"]) if A["cust"] else None
    if t3 is not None and t3 >= 0.5:
        n, c, v = A["cust"][0]
        out.append(("중간", "거래처", "매출 상위 3곳 비중 %s. %s 한 곳이 %s." % (pct(t3, 1), _vname(n, c), pct(v, sum(x[2] for x in A["cust"]))),
                    "큰 거래처 일정이 빠지면 분기 매출이 크게 흔들림 → 새 거래처 목표를 팀 목표에 함께 둠."))
    S = A["speed"]
    for v, d, n in (S.get("late") or [])[:3]:
        if d > 60:
            out.append(("중간", "수금", "%s 행사 뒤 입금까지 평균 %d일 (%d건)." % (esc(v), round(d), n), "계약 때 선금 비율을 올리거나 지급 기일을 계약서에 적음."))
    for T in A["teams"]:
        g = T["goal"] or (None, None)
        if g[0] and T["rev"] < g[0]:
            out.append(("중간", "팀", "%s 매출 목표 %s, 수익률 %s." % (esc(T["name"]), pct(T["rev"], g[0]), pct(T["gp"], T["rev"])), "미달 원인 확인 후 다음 해 목표에 반영."))
    loss = [x for x in A["proj"]["list"] if x["rate"] < 0]
    if loss:
        out.append(("중간", "프로젝트", "적자 프로젝트 %d건 (%s)." % (len(loss), ", ".join(esc(x["id"]) for x in loss[:5])), "추가 원가·견적 누락 여부 확인."))
    Yp, Lp = A["Y"], A["L"]
    if Lp and Lp["rev"]:
        g = Yp["rev"] / float(Lp["rev"])
        for k, v in Yp["acct"].items():
            b = Lp["acct"].get(k)
            if b and v / float(b) > g * 1.2 and v - b > 1000000:
                out.append(("낮음", "비용", "%s %s (매출 %s보다 빠르게 늘어남)." % (esc(k), chg(v, b), chg(Yp["rev"], Lp["rev"])), "늘어난 이유 확인, 다음 해 예산에 반영."))
    if not A["closed"]:
        out.append(("높음", "자료", "12월 결산 전표가 아직 없음 (감가상각비·법인세가 예상).", "결산 뒤 위하고에서 분개장을 다시 받아 '자료 변환' 후 다시 만듦."))
    return out


def _detail(A):
    year, Yp, Lp = A["year"], A["Y"], A["L"]
    # 영역별 보기 (사용자 2026-11-11): [(영역 키, 이름, 묶음, HTML)] — render 가 영역으로 감싸고 목록을 붙인다
    names = ["달별 손익과 결산", "분기별 실적", "통장 흐름", "거래처", "팀·프로젝트·판관비", "%d년 준비 근거" % (year + 1)]
    out, d = [], []

    def cut(key, label, group="상세 자료"):
        out.append((key, label, group, "".join(d)))
        del d[:]
    rk = _risks(A)
    A["_risk_hi"] = sum(1 for r in rk if r[0] == "높음") or None
    d.append("<h2 id='risk'>위험 분석·해결방안 (경영관리 전용)</h2>")
    d.append("<div class='tw'><table class='risk'><thead><tr><th>등급</th><th>영역</th><th>근거 (숫자)</th><th>해결방안</th></tr></thead><tbody>%s</tbody></table></div>"
             % "".join("<tr><td class='lv'>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % r for r in rk) if rk else "<div class='note'>눈에 띄는 위험 없음</div>")
    cut("risk", "위험 분석·해결방안", "보고 요약")
    d.append("<h2 id='d1'>1. 달별 손익과 결산</h2><div class='evh'>근거 1-1 · 달별 손익 (위하고 순서)</div>")
    rows = [("매출", Yp["rev_m"]), ("매출원가", Yp["cogs_m"]), ("매출총이익", [Yp["rev_m"][i] - Yp["cogs_m"][i] for i in range(12)]),
            ("판관비", Yp["common_m"]), ("영업이익", Yp["op_m"])]
    d.append("<div class='tw'>" + _tab(["구분"] + ["%d월" % (i + 1) for i in range(12)] + ["합계"],
                                      [[n] + [W(v) for v in vs] + [W(sum(vs))] for n, vs in rows], "pt tx m12") + "</div>")
    d.append("<div class='note'>영업외 수익 %s · 영업외 비용 %s 는 연 합계로 손익표에 반영 (부서비용 기준)</div>" % (W(Yp["nin"]), W(Yp["nout"])))
    d.append("<div class='evh'>근거 1-2 · 결산 확정치와 연중 예상</div>")
    d.append(_tab(["항목", "연중 예상", "결산", "차이", "예상 근거"], [
        ["감가상각비", W(A["dep_est"]), W(Yp["dep"]) if A["closed"] else "결산 전", sgn(Yp["dep"] - A["dep_est"]) if A["closed"] and A["dep_est"] else "—", esc(A["dep_src"] or "")],
        ["법인세 등", W(A["tax_est"]), W(A["tax"]) if A["tax_fixed"] else "결산 전", sgn(A["tax"] - A["tax_est"]) if A["tax_fixed"] else "—", "세전 이익 × 세율, 세무조정 없음"]], "pt evt"))
    cut("d1", "1. " + names[0])
    d.append("<h2 id='d2'>2. 분기별 실적</h2><div class='evh'>근거 2-1 · 분기 합계%s</div>" % ("와 작년 같은 분기" if Lp else ""))
    qr = []
    for k in range(4):
        sl = slice(k * 3, k * 3 + 3)
        r_ = sum(Yp["rev_m"][sl])
        lr = sum(Lp["rev_m"][sl]) if Lp else None
        buy = [v for v in Yp["buy_m"][sl] if v is not None]
        qr.append(["%d분기" % (k + 1), W(r_), W(sum(buy)) if buy else "—", W(r_ - sum(Yp["cogs_m"][sl])), W(sum(Yp["op_m"][sl])), W(lr), chg(r_, lr)])
    d.append(_tab(["분기", "매출", "매입", "매출총이익", "영업이익", "작년 같은 분기 매출", "매출 증감률"], qr, "pt pl",
                  ["합계", W(Yp["rev"]), W(Yp["buy"]), W(Yp["gp"]), W(Yp["op"]), W(Lp["rev"] if Lp else None), chg(Yp["rev"], Lp["rev"] if Lp else None)]))
    cut("d2", "2. " + names[1])
    d.append("<h2 id='d3'>3. 통장 흐름</h2><div class='evh'>근거 3-1 · 한 해 현금 흐름 분류 (보통예금 상대 계정)</div>")
    why = {"영업 입금": "외상매출금·선수금 등 (아래 분류가 아닌 계정)", "영업 지급": "외상매입금·미지급금·급여·판관비 등", "세금": "부가세·예수금·선납세금·법인세 계정",
           "투자": "유형·무형자산 계정", "대출 받음": "차입금 대변", "대출 갚음": "차입금 차변", "자본금 납입": "자본금 계정"}
    d.append(_tab(["구분", "금액", "나눈 기준"], [["연초 잔액", W(A["bal0"]), ""]] + [[esc(n), sgn(v), why.get(n, "")] for n, v in A["cf"]]
                  + [["연말 잔액", W(A["bal_end"]), "분류 못 한 차이 %s" % sgn(A["cf_gap"]) if A.get("cf_gap") else ""]], "pt evt"))
    d.append("<div class='evh'>근거 3-2 · 달별 월말 잔액</div>")
    minc = num(A["settings"].get("위험_최소보유현금")) or 0
    d.append(_tab(["달", "월말 잔액", "최소 보유현금 위 여유"], [["%d월" % (i + 1), W(v), W(v - minc) if v is not None else "—"] for i, v in enumerate(A["bal_m"])], "pt pl"))
    cut("d3", "3. " + names[2])
    d.append("<h2 id='d4'>4. 거래처</h2><div class='evh'>근거 4-1 · 매출·매입 상위 10곳</div><div class='cf'>")
    for lst in (A["cust"], A["vend"]):
        tot = sum(v for _, _, v in lst)
        d.append("<div>" + _tab(["순위", "거래처", "금액", "비중", "누적 비중"], [[i + 1, _vname(n, c), W(v), pct(v, tot), pct(sum(x[2] for x in lst[:i + 1]), tot)]
                                                                 for i, (n, c, v) in enumerate(lst[:10])], "pt") + "</div>")
    d.append("</div>")
    if "new" in A:
        d.append("<div class='evh'>근거 4-2 · 새로 생긴 거래처 %d곳 · 끊긴 거래처 %d곳</div><div class='cf'><div>%s</div><div>%s</div></div>" % (
            len(A["new"]), len(A["lost"]),
            _tab(["새 거래처", "올해 매출"], [[_vname(n, c), W(v)] for n, c, v in A["new"]], "pt", ["합계", W(sum(v for _, _, v in A["new"]))]),
            _tab(["끊긴 거래처", "작년 매출"], [[_vname(n, c), W(v)] for n, c, v in A["lost"]], "pt", ["합계", W(sum(v for _, _, v in A["lost"]))])))
    S = A["speed"]
    if S["n"]:
        d.append("<div class='evh'>근거 4-3 · 돈 받는 속도 (올해 입금 %d건, 행사 전 입금 %d건 제외)</div>" % (S["n"], S["pre"]))
        d.append(_tab(["거래처", "평균 일수", "건수"], [[esc(v), "%d일" % round(dd), "%d건" % n] for v, dd, n in S["late"]], "pt tgy"))
        if S["over60"]:
            d.append("<div class='wsub'>행사 뒤 60일 넘겨 입금된 %d건</div>" % len(S["over60"]))
            d.append(_tab(["거래처", "프로젝트", "행사 끝난 날", "입금일", "걸린 날", "입금액"],
                          [[esc(x[0]), esc("%s %s" % (x[1], x[2])), x[3].isoformat(), x[4].isoformat(), "%d일" % x[5], W(x[6])] for x in S["over60"]], "pt evt"))
    cut("d4", "4. " + names[3])
    d.append("<h2 id='d5'>5. 팀·프로젝트·판관비</h2><div class='evh'>근거 5-1 · 팀 분기 추이</div>")
    rows = []
    for T in A["teams"]:
        rows.append([esc(T["name"]), "수익률"] + [pct(r, 1) if r is not None else "—" for r, _ in T["q"]])
        rows.append(["", "1인당 영업이익"] + [W(o) for _, o in T["q"]])
    d.append(_tab(["팀", "구분", "1분기", "2분기", "3분기", "4분기", "연간"], rows, "pt tgy"))
    d.append("<div class='note'>1인당 영업이익 = (팀 매출총이익 − 팀 급여·판관비) ÷ 팀 평균 인원 (공통비 나누기 전)</div>")
    PR = A["proj"]
    if PR["list"]:
        d.append("<div class='evh'>근거 5-2 · 프로젝트 (%d년에 행사가 끝난 것)</div>" % year)
        rows = []
        for tm, ps in PR["teams"].items():
            rows.append([esc(tm), "%d건" % len(ps), W(int(round(sum(x["rev"] for x in ps) / float(len(ps))))), "%.1f%%" % (100.0 * sum(x["rate"] for x in ps) / len(ps)),
                         "%d건" % sum(1 for x in ps if x["target"] is not None and x["rate"] < x["target"]), "%d건" % sum(1 for x in ps if x["rate"] < 0),
                         "%d건" % PR["lcount"].get(tm, 0)])
        d.append(_tab(["팀", "프로젝트 수", "건당 평균 매출", "평균 수익률", "목표 수익률 미달", "적자", "작년 프로젝트 수"], rows, "pt tgy"))
        under = sorted([x for x in PR["list"] if x["target"] is not None and x["rate"] < x["target"]], key=lambda x: x["rate"])
        if under:
            d.append("<div class='wsub'>목표 수익률 미달 프로젝트 %d건</div>" % len(under))
            d.append(_tab(["팀", "프로젝트", "매출", "수익률", "목표"], [[esc(x["team"]), esc("%s %s" % (x["id"], x["name"])), W(x["rev"]),
                                                                       "<span class='%s'>%.1f%%</span>" % ("up" if x["rate"] < 0 else "", x["rate"] * 100), "%d%%" % round(x["target"] * 100)] for x in under], "pt evt"))
    if Yp["acct"]:
        d.append("<div class='evh'>근거 5-3 · 판관비 항목별%s</div>" % (" (작년 대비)" if Lp else ""))
        keys = list(Yp["acct"]) + [k for k in (Lp["acct"] if Lp else {}) if k not in Yp["acct"]]
        rows = []
        for k in keys:
            a, b = Yp["acct"].get(k, 0), (Lp["acct"].get(k, 0) if Lp else None)
            rows.append([esc(k), W(a), pct(a, Yp["rev"])] + ([W(b), pct(b, Lp["rev"]), sgn(a - b), chg(a, b)] if Lp else []))
        ta = sum(Yp["acct"].values())
        tb = sum(Lp["acct"].values()) if Lp else None
        d.append(_tab(["항목", "%d년" % year, "매출 대비"] + (["%d년" % (year - 1), "매출 대비", "증감", "증감률"] if Lp else []), rows, "pt pl",
                      ["판관비 합계", W(ta), pct(ta, Yp["rev"])] + ([W(tb), pct(tb, Lp["rev"]), sgn(ta - tb), chg(ta, tb)] if Lp else [])))
    cut("d5", "5. " + names[4])
    d.append("<h2 id='d6'>6. %d년 준비 근거</h2><div class='evh'>근거 6-1 · 법인세 계산</div>" % (year + 1))
    d.append(_tab(["단계", "금액"], [["세전 이익", W(Yp["pre"])], ["법인세 등 %s" % ("확정 (결산 전표)" if A["tax_fixed"] else "예상 (세무조정 없음)"), W(A["tax"])],
                                   ["법인세 (지방소득세 뺀 것)", W(A["corp"])], ["− 중간예납 등 선납세금", W(A["prepaid"])],
                                   ["= %s 납부" % A["pay_corp_day"].isoformat(), W(max(A["corp"] - A["prepaid"], 0))],
                                   ["지방소득세 (%s 납부)" % A["pay_local_day"].isoformat(), W(A["local"])]], "pt pl"))
    NX = A["next"] or []
    if NX:
        d.append("<div class='evh'>근거 6-2 · %d년 행사 프로젝트 %d건</div>" % (year + 1, len(NX)))
        d.append(_tab(["팀", "프로젝트", "행사일", "사전견적", "추정 예산", "집행액", "잔여"],
                      [[esc(p["team"]), esc("%s %s" % (p["id"], p["name"])), p["day"].isoformat(), W(p["est"]), W(p["budget"]), W(p["paid"]),
                        W((p["budget"] or 0) - p["paid"])] for p in NX], "pt evt"))
        d.append("<div class='note'>추정 예산 = 사전견적 × (1 − 그 팀 목표 수익률)</div>")
    cut("d6", "6. " + names[5])
    from . import cashflow   # 연간 현금흐름표 (사용자 2026-11-12: 연간 누적으로도). 경영관리용에만
    d.append("<h2 id='d7'>7. 현금흐름표</h2>" + cashflow.render(A.get("cfs")))
    cut("d7", "7. 현금흐름표")
    return out
