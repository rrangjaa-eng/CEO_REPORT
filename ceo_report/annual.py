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
CF_ORDER = ("자본금 납입", "영업 입금", "영업 지급", "세금", "세금·4대보험", "투자", "대출 받음", "대출 갚음", "대표이사 돈", "3개월 이내 정기예금")
CF_TAX = ("세금", "세금·4대보험")


# ───────────── 변환 쪽 ─────────────

def _tpct(r):
    """목표 수익률 표시 (11/17 전수 점검 F7: 28.5% 가 '28%' 로 반올림되던 것). 정수면 '28%', 아니면 '28.5%'."""
    v = round(r * 100, 1)
    return "%d%%" % v if v == int(v) else "%.1f%%" % v

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
    pre_day = collections.defaultdict(int)   # 1차 C7 (2026-11-15): 연중 보고가 기준일까지 낸 선납세금만 쓰게 날짜별로도 남긴다
    for ln in journal:
        if ln.get("date") is None:
            continue
        y, code = str(ln["date"].year), _sq(ln.get("account_code"))
        if "법인세" in _sq(ln.get("account")) and code[:1] == "9":
            tax[y] += (ln["debit"] or 0) - (ln["credit"] or 0)
        elif code in prepaid:
            pre[y] += ln["debit"] or 0
            if ln["debit"]:
                pre_day[(y, ln["date"].isoformat())] += ln["debit"]
    for y in sorted(set(tax) | set(pre)):
        if tax.get(y):
            add(y, "결산", "법인세등", "", tax[y])
        if pre.get(y):
            add(y, "결산", "선납세금", "", pre[y])
    for (y, day), v in sorted(pre_day.items()):
        add(y, "선납세금일", day, "", v)
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
def period(year, asof=None):
    """연중에 만든 연간 보고의 집계 범위 -> (끝난 달 cut, 기준일).

    기준일이 그 해 말일 이후거나 없으면 (12, 12/31). 연중이면 기준일까지 '끝난 달'만 손익에 넣는다
    (기준일이 그 달 말일이면 그 달까지). 진행 중인 달은 급여·카드 등 비용이 아직 덜 들어와 이익이 부풀기 때문
    (사용자 2026-11-14: 연간·예산을 연중에 받아도 그 일자 기준으로 맞아야 함)."""
    end = dt.date(year, 12, 31)
    if asof is None or asof >= end:
        return 12, end
    if asof.year < year:
        return 0, asof
    done = asof.month if (asof + dt.timedelta(days=1)).month != asof.month else asof.month - 1
    return done, asof


def _month_end(year, m):
    return dt.date(year + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)


def _year_pl(rows, dept, accts, year, cut=12):
    """한 해 회사 손익 (1월~cut월). 없으면 None."""
    inm = lambda ym: ym[:4] == year and 1 <= int(ym[5:7] or 0) <= cut
    co = [r for r in rows if inm(r["연월"]) and r["단위"] == "회사"]
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
    dr = [r for r in dept if r.get("연월", "")[:4] == year and inm(r["연월"])]
    P["sal"] = sum(_n(r.get("급여")) or 0 for r in dr)
    P["nin"] = sum(_n(r.get("영업외수익")) or 0 for r in dr)
    P["nout"] = sum(_n(r.get("영업외비용")) or 0 for r in dr)
    ar = [r for r in accts if r.get("연월", "")[:4] == year and inm(r["연월"]) and "판매" in r.get("구분", "")]
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


def compute(input_dir, year, settings=None, D=None, asof=None):
    """asof = 보고 기준일. 연중이면 손익은 끝난 달까지, 작년은 같은 기간, 통장은 기준일까지 (period)."""
    from .corptax import corp_tax, read as read_dep
    Y, LY, NY = str(year), str(year - 1), str(year + 1)
    cut, asof = period(year, asof)
    pl = [r for r in _read(os.path.join(input_dir, "손익.csv")) if r.get("연월")]
    co_rows = [r for r in pl if r.get("출처") == "WEHAGO"] or pl
    dept = _read(os.path.join(input_dir, "부서비용.csv"))
    accts = _read(os.path.join(input_dir, "계정별비용.csv"))
    A = {"year": year, "settings": settings or {}, "notes": [], "cut": cut, "asof": asof, "mid": cut < 12}
    A["Y"] = _year_pl(co_rows, dept, accts, Y, cut)
    A["L"] = _year_pl(co_rows, dept, accts, LY, cut)   # 작년도 같은 기간 (1월~cut월)
    A["Lfull"] = _year_pl(co_rows, dept, accts, LY) if cut < 12 else A["L"]   # 달별 그림의 작년 막대용
    if A["Y"] is None:
        return A
    Yp, Lp = A["Y"], A["L"]
    ev = dict((r["연월"], _n(r.get("매입"))) for r in _read(os.path.join(input_dir, "증빙월별.csv")) if r.get("연월"))
    Yp["buy_m"] = [ev.get("%s-%02d" % (Y, i + 1)) if i < cut else None for i in range(12)]
    Yp["buy"] = sum(v or 0 for v in Yp["buy_m"])
    ann = _read(os.path.join(input_dir, FILE))
    A["has_annual"] = bool(ann)
    get = lambda y, kind: [(r["항목"], r.get("코드", ""), _n(r["금액"]) or 0) for r in ann if r.get("연도") == y and r.get("구분") == kind]

    # 결산 확정치: 감가상각비·법인세 (사용자 2026-11-10: 결산 확정치와 연중 예상 차이 한 줄)
    manual = read_dep(input_dir)
    dep_est = manual.get(Y)
    dep_src = "직접 입력"
    if dep_est is None:
        from .corptax import read_ledger   # 위하고 고정자산관리대장 (사용자 2026-11-13)
        dep_est = read_ledger(input_dir).get(Y)
        dep_src = "고정자산대장"
    if dep_est is None:
        Lf = A["Lfull"]   # 작년 한 해 장부 (연중 보고여도 같은 기간이 아니라 한 해 금액)
        dep_est, dep_src = (Lf["dep"] if Lf else None), "작년 장부"
    A["dep_est"], A["dep_src"] = dep_est, dep_src
    ann_y = dict((n, v) for n, _, v in get(Y, "결산"))
    if cut < 12:   # 연중 보고: 결산 확정치(법인세등)는 한 해 것이라 쓰지 않는다. 선납세금은 기준일까지 낸 것이라 그대로
        ann_y = dict((k, v) for k, v in ann_y.items() if k == "선납세금")
    # 결산 끝 = 감가상각비가 들어왔고, 결산 법인세도 들어왔거나 감가상각비가 올해 예상만큼 다 들어옴 (2026-11-14 코덱스 검토: 1원만 있어도 끝으로 봤음)
    A["closed"] = Yp["dep"] > 0 and (bool(ann_y.get("법인세등")) or not dep_est or Yp["dep"] >= dep_est)
    if not A["closed"] and dep_est:
        # 결정 M5 (2026-11-15, 계산-14): 연중이면 한 해 예상 × 지난 달 수 ÷ 12 (월간과 같게 — 예전엔 한 해 금액을 다 뺐다)
        pend = max(dep_est * cut // 12 - Yp["dep"], 0)   # 일부만 들어왔으면 나머지만 예상으로
        Yp["dep_pending"] = pend
        Yp["pre"] -= pend   # 결산 전: 월간과 같게 감가상각비 예상을 먼저 비용으로
    pre_est = Yp["pre"] + (Yp["dep"] - (dep_est or 0) if A["closed"] else 0)
    from .corptax import national   # 작년 신고서 감면·넘어온 공제 (사용자 2026-11-13). 지방소득세는 감면 없이 산출세액 10%
    n_est, c_est, _ = national(pre_est, Y, input_dir)
    A["tax_est"] = n_est + c_est // 10
    booked = ann_y
    A["prepaid"] = booked.get("선납세금", 0)
    days = get(Y, "선납세금일")
    if cut < 12 and days:   # 1차 C7: 연중 보고는 기준일까지 낸 선납세금만 (예전엔 8월 중간예납이 6/30 보고에도 빠졌다)
        A["prepaid"] = sum(v for d, _, v in days if d <= asof.isoformat())
    if booked.get("법인세등"):
        A["tax"], A["tax_fixed"] = booked["법인세등"], True
        # 지방소득세 = 산출세액 × 10% (감면 없음). 법인세 = 장부 법인세등 − 지방소득세
        # (2026-11-14 코덱스 검토: 10:1로 나누면 감면이 있을 때 3/31·4/30 납부액이 틀림)
        c_now = national(Yp["pre"], Y, input_dir)[1]
        local = c_now // 10 if c_now is not None else int(round(A["tax"] / 11.0))
        A["corp"] = A["tax"] - min(local, A["tax"])
    else:
        n_now, c_now, _ = national(Yp["pre"], Y, input_dir)
        A["corp"] = n_now
        A["tax"], A["tax_fixed"] = n_now + c_now // 10, False
    A["local"] = A["tax"] - A["corp"]
    Yp["net"] = Yp["pre"] - A["tax"]
    if Lp and cut < 12:
        # 연중 보고: 작년도 같은 기간으로 맞춘다. 월간·올해와 같이 작년 연간 감가상각비를 먼저 비용으로 빼고
        # (작년 결산 감가상각비는 12월에 들어가 같은 기간엔 0원), 법인세는 그 기간 세전 이익 × 세율
        lfull = A["Lfull"]["dep"] if A["Lfull"] else 0
        if lfull and lfull * cut // 12 > Lp["dep"]:
            Lp["dep_pending"] = lfull * cut // 12 - Lp["dep"]   # 작년도 같은 달 수만큼 (결정 M5)
            Lp["pre"] -= Lp["dep_pending"]
        lc = corp_tax(Lp["pre"], LY)
        Lp["tax"] = lc + lc // 10
        Lp["net"] = Lp["pre"] - Lp["tax"]
    elif Lp:
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
        if d is not None and d <= asof:   # 기준일 뒤 스냅숏은 넣지 않는다
            bal[d] += _n(r.get("잔액")) or 0
    ends = {}
    for d in sorted(bal):
        ends[(d.year, d.month)] = bal[d]   # 그 달 마지막 스냅숏
    A["bal_m"] = [ends.get((year, m)) for m in range(1, 13)]
    first = min(bal) if bal else None
    A["bal0"] = ends.get((year - 1, 12), 0 if first and first.year >= year else None)
    A["bal_end"] = next((v for v in reversed(A["bal_m"]) if v is not None), None)
    from . import cashflow   # 연간 현금흐름표 (사용자 2026-11-12): 1월 1일 잔액은 장부(작년 분개장 있을 때)
    # 11/17 전수 점검 F8: 연중이면 현금흐름표(장부상 이익에서 시작)와 신용평가도 1절 손익과 같은 '끝난 달 말일'까지.
    # 예전엔 기준일(11/17)까지라 11월 급여 전 장부 이익 3.08억이 1절 1~10월 손익과 섞여 보였음. 3절 통장 흐름은 기준일까지 그대로
    p_end = _month_end(year, cut) if cut < 12 else None
    cf_end_bal = A["bal_m"][cut - 1] if (p_end and A["bal_m"][cut - 1] is not None) else A["bal_end"]
    A["cfs"] = cashflow.annual(cashflow.load(input_dir), year, cf_end_bal, A["bal0"], upto=p_end)
    if A["cfs"]:
        A["cfs"]["collect"] = cashflow.collection(input_dir, dt.date(year, 1, 1), A["cfs"]["p1"])
    from . import credit   # 기업신용평가 미리보기 (사용자 2026-11-12): 결산 기준
    A["credit"] = credit.compute(input_dir, p_end or asof, annual=True)
    from . import surplus   # 이익잉여금처분계산서 (사용자 2026-11-12): 연간 경영관리용 8장
    # 사용자 2026-11-17: 배당 한도·권장은 올해 이익(기준일까지 예상)과 작년에서 넘어온 이익잉여금을 합쳐 봐야 한다 → 연중이어도 올해 것.
    # 1차 C7(기준일 뒤 자료 금지): 올해 당기순이익 예상이 기준일 달보다 뒤 달까지의 장부로 만든 것이면 지난해 결산 것을 쓴다.
    y_re = year
    if cut < 12:
        ni = ((surplus.load(input_dir) or {}).get(year) or {}).get("당기순이익")
        mm = re.search(r"1~(\d+)월", ni[2]) if ni else None
        if not ni or ni[0] is None or (mm and int(mm.group(1)) > asof.month):
            y_re = year - 1
    A["re_year"] = y_re   # 보고서.py 가 월간 계산을 붙여 다시 부를 때 같은 해를 쓴다 (11/18: 거기서 작년으로 덮어써 배당이 2025년 기준이던 것)
    A["re"] = surplus.for_report(input_dir, y_re, strict=True, asof=asof)
    A["cf"] = [(n, v) for n, _, v in get(Y, "현금흐름")]
    A["cf"].sort(key=lambda x: CF_ORDER.index(x[0]) if x[0] in CF_ORDER else 99)
    if A["cf"] and A["bal0"] is not None and A["bal_end"] is not None:
        A["cf_gap"] = A["bal_end"] - A["bal0"] - sum(v for _, v in A["cf"])
        # 2차 전수조사 J10 (2026-11-18): 같은 보고의 현금흐름표와 분류를 하나로 — 현금흐름표 자료로 다시 묶는다.
        # 통장 잔액 증감과 더 잘 맞을 때만 바꾼다 (자료 날짜가 달라 안 맞으면 예전 분류 그대로)
        uni = cashflow.flow_summary(cashflow.load(input_dir), dt.date(year, 1, 1), asof if cut < 12 else dt.date(year, 12, 31))
        if uni:
            gap = A["bal_end"] - A["bal0"] - sum(v for _, v in uni)
            if abs(gap) <= abs(A["cf_gap"]):
                A["cf"], A["cf_gap"], A["cf_same"] = uni, gap, True

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
    inv = _read(os.path.join(input_dir, "계산서.csv"))
    A["speed"], A["lspeed"] = _speed(inv, projs, year, asof), _speed(inv, projs, year - 1, _same_day(asof, year - 1))

    # 팀
    goals = dict(((r.get("연도", "").strip(), r.get("팀", "").strip()), (_n(r.get("매출목표")), _rate(r.get("목표수익률"))))
                 for r in _read(os.path.join(input_dir, "팀목표.csv")))
    A["goals"], A["goals_next"] = goals, dict((t, v) for (y, t), v in goals.items() if y == NY)
    A["teams"] = _teams(co_rows, dept, Y, LY, goals, cut)
    A["team_none"] = _team_none(co_rows, Y, LY, cut)
    A["proj"] = _projects(pl, projs, Y, LY, goals, cut)
    MR = _monthly_calc(input_dir, year, D, asof)
    A["next"] = _next_projects(input_dir, year, D, asof, MR)
    # 2차 전수조사 J2 (2026-11-18): 연중 목표 판정은 '잡힌 매출 + 앞으로 잡힐 매출'(월간 대표 '올해 매출 예상'과 같은 계산)로 한다.
    # 예전: 연 목표 × 지난 달 ÷ 12 — 행사 매출은 달마다 크게 달라 앞으로 잡힐 매출이 넉넉한 팀도 '미달'로 보였음
    E = ((MR or {}).get("s5") or {}).get("expected")
    A["exp_team"] = None if (not E or E.get("missing")) else dict((t, v["past"] + v["this_year"]) for t, v in E["by_team"].items())
    for T in A["teams"]:
        T["left"] = None if A["exp_team"] is None else A["exp_team"].get(T["name"], 0)
    return A


def _fold_dep(P):
    """보여 주기용 사본: 결산 전 감가상각비 예상(dep_pending)을 장부 감가상각비 줄에 합친다 (판관비·영업이익도 같이).
    세전 이익·법인세는 이미 예상을 뺀 값이라 그대로. 원본(P)은 달별 표·분기 합계가 쓰므로 바꾸지 않는다."""
    if not P:
        return P
    V = dict(P)
    p = P.get("dep_pending") or 0
    if p:
        V["dep_book"], V["dep"] = P["dep"], P["dep"] + p
        V["common"], V["op"] = P["common"] + p, P["op"] - p
        V["dep_pending"], V["dep_folded"] = None, True
    return V


def _with_dep(P, cut):
    """달별·분기·판관비 항목 표용 사본 (11/18): 결산 전 감가상각비 예상을 끝난 달에 고르게 나눠(월할) 판관비·영업이익에 넣는다.
    1절 요약(_fold_dep)은 예상을 넣고 달별 표·분기 합계는 빼서 영업이익이 129백만·150백만 두 개로 보이던 것."""
    p = (P or {}).get("dep_pending") or 0
    if not P or not p or not cut:
        return P
    per = [p * (i + 1) // cut - p * i // cut for i in range(cut)] + [0] * (12 - cut)
    V = dict(P)
    V["common_m"] = [P["common_m"][i] + per[i] for i in range(12)]
    V["op_m"] = [P["op_m"][i] - per[i] for i in range(12)]
    V["common"], V["op"] = P["common"] + p, P["op"] - p
    if P.get("acct"):
        acc = dict(P["acct"])
        k = next((k for k in acc if "감가상각" in k), "감가상각비")
        acc[k] = acc.get(k, 0) + p
        V["acct"] = acc
    V["dep_spread"] = p
    return V


def apply_monthly(A, M, pack):
    """월간 보고와 같은 계산으로 맞춘다 (사용자 2026-11-17: 연간 보고에 넣어야 할 항목 전부, 법인세는 월간과 같은 계산).
    M = 끝난 달 말일 기준 월간 계산(R), pack = render.annual_pack(M). 결산 법인세가 장부에 들어왔으면(tax_fixed) 그대로 둔다.
    감가상각비 예상(달 수만큼)·대손충당금 예상을 세전 이익에서 빼고, 법인세는 자금 일정과 같은 과세표준(세무조정 예상)·작년 신고서 감면·기납부."""
    A["M"], A["pack"] = M, pack
    Yp = A.get("Y")
    md = (M or {}).get("dep") or {}
    if A.get("dep_est") is None and md.get("annual"):   # 6장 '내년 감가상각비 예상'도 월간이 쓴 연간 금액으로
        A["dep_est"], A["dep_src"] = md["annual"], md.get("source") or "월간 보고"
    if not pack or Yp is None or A.get("tax_fixed") or not A.get("cut"):
        return
    if pack["ym"] != "%d-%02d" % (A["year"], A["cut"]) or pack.get("E") is None:
        return
    from .corptax import LOCAL_RATE, national
    N, E = pack["N"], pack["E"]
    booked = Yp["pre"] + (Yp.get("dep_pending") or 0)   # 예상을 빼기 전 장부 세전 이익
    dep = N.get("dep") if N.get("dep") is not None else (Yp.get("dep_pending") or 0)
    bad = N.get("bad") or 0
    Yp["dep_pending"], Yp["bad_pending"] = dep or None, bad or None
    Yp["dep_note"], Yp["bad_note"] = (N.get("dep_note") or "").lstrip(", "), (N.get("bad_note") or "").lstrip(", ")
    Yp["pre"] = booked - dep - bad
    adj = E["base"] - N["pretax"]   # 세무조정 예상 (자금 일정의 법인세 줄과 같은 값)
    nat, corp, C = national(Yp["pre"] + adj, str(A["year"]), M.get("taxret_dir"))
    if corp is None:
        return
    A["corp"], A["local"] = nat, int(corp * LOCAL_RATE)
    A["tax"] = A["tax_est"] = A["corp"] + A["local"]
    if E.get("prepaid") is not None:
        A["prepaid"] = E["prepaid"]
    A["pay_corp_day"], A["pay_local_day"] = E["due"], E["local_due"]
    A["local_paid"] = E.get("local_paid") or 0   # 원천징수된 지방소득세 — 4/30 납부액에서 뺌 (월간·자금 일정과 같게)
    A["tax_same"], A["tax_base"], A["tax_adj"], A["tax_credit"] = True, Yp["pre"] + adj, adj, bool(C)
    Yp["net"] = Yp["pre"] - A["tax"]


def team_extra(A, team):
    """연간 팀장 보고에 붙일 것 (teamreport.render_annual): 작년 같은 기간 매출, 내년 받은 일·목표, 기간."""
    T = next((t for t in A.get("teams") or [] if t["name"] == team), None)
    cut = A.get("cut", 12)
    return {"year": A["year"], "cut": cut, "mid": bool(A.get("mid")), "asof": A.get("asof") or dt.date(A["year"], 12, 31),
            "end": _month_end(A["year"], cut) if cut else dt.date(A["year"], 1, 1),
            "lrev": T["lrev"] if T else None, "goal_next": (A.get("goals_next") or {}).get(team),
            "next": [p for p in (A.get("next") or []) if p["team"] == team]}


def blank_cash(A):
    """자금계획서·분개장이 최신이 아닐 때 경영관리용: 항목은 남기고 통장 숫자(연초·연말·월말 잔액, 현금 흐름)만 비운다
    (2026-11-14 오후 점검 K7). 손익·거래처·팀 숫자는 그대로."""
    A = dict(A)
    A.update({"bal0": None, "bal_end": None, "bal_m": [None] * 12, "cf": [], "cf_gap": None, "cfs": None, "blocked": True})
    return A


def _same_day(d, year):
    """작년 같은 날 (2/29 → 2/28)."""
    try:
        return d.replace(year=year)
    except ValueError:
        return d.replace(year=year, day=28)


def _workday(d):
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def _speed(invoices, projs, year, upto=None):
    """행사 끝난 날 → 입금일 (그 해 upto 까지 입금된 계산서). 선입금(행사 전 입금)은 따로 센다."""
    rows = []
    for r in invoices:
        paid = parse_date(r.get("입금일"))
        if paid is None or paid.year != year or (upto is not None and paid > upto):
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


def _team_none(rows, Y, LY, cut=12):
    """팀이 없는 장부 줄 (손익.csv '팀 미지정': 부서가 팀이 아닌 매출·원가, 예전 인트라넷 팀 '0' 프로젝트 등).
    11/17 전수 점검 F6: 팀 표 합계가 회사 합계와 1.8억 어긋나 보이던 것 — 한 줄로 보이고 합계에 넣는다. 없으면 None."""
    def tot(y):
        rv = dc = 0
        for r in rows:
            if r["단위"] == "팀" and not r["대상"].endswith("팀") and r["연월"][:4] == y and 1 <= int(r["연월"][5:7] or 0) <= cut:
                rv += _n(r["매출"]) or 0
                dc += _n(r["직접비"]) or 0
        return rv, dc
    (rv, dc), (lrv, ldc) = tot(Y), tot(LY)
    if not (rv or dc or lrv or ldc):
        return None
    return {"name": "팀 미지정", "rev": rv, "gp": rv - dc, "lrev": lrv}


def _teams(rows, dept, Y, LY, goals, cut=12):
    rows = [r for r in rows if 1 <= int(r["연월"][5:7] or 0) <= cut]   # 올해·작년 모두 1월~cut월 (연중 보고)
    dept = [r for r in dept if r.get("연월") and 1 <= int(r["연월"][5:7] or 0) <= cut]
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
            if k < 4 and k * 3 + 1 > cut:   # 아직 시작 안 한 분기는 빈칸 (0원으로 보이지 않게)
                q.append((None, None))
                continue
            q.append((g_ / float(r_) if r_ else None, int(round((g_ - c_) / n)) if n else None))
        out.append({"name": t, "rev": sum(rv), "gp": sum(gp), "lrev": sum(lrv) if any(lrv) else None, "goal": goals.get((Y, t)),
                    "heads": n, "q": q})
    return out


def _projects(pl, projs, Y, LY, goals, cut=12):
    """행사가 그 해 1월~cut월 말에 끝난 프로젝트: 팀별 건수·평균 수익률·목표 수익률 미달·적자.
    연중 보고면 손익 줄도 cut월까지만 (회사 손익과 같은 기간), 작년도 같은 기간."""
    # 같은 프로젝트에 장부(WEHAGO) 줄이 있으면 예전 '인트라넷완료보고' 등 다른 출처 줄은 더하지 않는다
    # (2026-11-14 오후 점검 Y2: 둘 다 더해 수익률이 20% → 40%처럼 부풀었음)
    has_wehago = set((r.get("대상") or "").split(" ")[0] for r in pl if r.get("단위") == "프로젝트" and r.get("출처") == "WEHAGO")

    def agg(y):
        P = collections.OrderedDict()
        for r in pl:
            if r.get("단위") != "프로젝트":
                continue
            pid = (r.get("대상") or "").split(" ")[0]
            p = projs.get(pid)
            if not p:
                continue
            if pid in has_wehago and r.get("출처") != "WEHAGO":
                continue
            end = _end_day(p)
            if end is None or str(end.year) != y or end > _month_end(int(y), cut):
                continue
            if cut < 12 and (r.get("연월") or "") > "%s-%02d" % (y, cut):
                continue
            x = P.setdefault(pid, {"id": pid, "name": p.get("프로젝트명", ""), "team": p.get("팀", ""), "rev": 0, "cost": 0, "cost_known": True})
            x["rev"] += _n(r.get("매출")) or 0
            c = _n(r.get("직접비"))
            if c is None:   # 원가 빈칸·미확인은 0원이 아니라 모름 (Y1: 예전엔 수익률 100%로 셈)
                x["cost_known"] = False
            else:
                x["cost"] += c
        return [x for x in P.values() if x["rev"] > 0]
    cur, last = agg(Y), agg(LY)
    teams = collections.OrderedDict()
    for x in cur:
        x["rate"] = (x["rev"] - x["cost"]) / float(x["rev"]) if x["cost_known"] else None
        g = goals.get((Y, x["team"]))
        x["target"] = g[1] if g else None
        teams.setdefault(x["team"], []).append(x)
    lcount = collections.Counter(x["team"] for x in last)
    return {"list": cur, "teams": teams, "lcount": lcount, "lall": len(last)}


def proj_stats(ps):
    """프로젝트 묶음 요약: 원가 확인된 것만 평균(매출 가중)·미달·적자에 쓴다 (Y1). -> dict."""
    known = [x for x in ps if x["rate"] is not None]
    rev = sum(x["rev"] for x in known)
    return {"n": len(ps), "known": len(known), "unknown": len(ps) - len(known),
            "avg": (sum(x["rev"] - x["cost"] for x in known) / float(rev)) if rev else None,
            "under": sum(1 for x in known if x["target"] is not None and x["rate"] < x["target"]),
            "loss": sum(1 for x in known if x["rate"] < 0)}


def _monthly_calc(input_dir, year, D=None, asof=None):
    """월간과 같은 계산 한 번 (다음 해 프로젝트·팀별 앞으로 잡힐 매출이 함께 씀). 못 읽으면 None."""
    from .calc import compute as calc_compute
    from .data import load
    try:
        return calc_compute(D if D is not None else load(input_dir), "monthly", asof or dt.date(year, 12, 31), None, None, None)
    except Exception:   # 프로젝트 자료가 없거나 읽지 못하면 이 칸만 비운다
        return None


_UNSET = object()


def _next_projects(input_dir, year, D=None, asof=None, R=_UNSET):
    """다음 해 행사 프로젝트: 사전견적·추정 예산·집행액·잔여 (월간과 같은 계산, 기준일 asof)."""
    from .calc import _event_date
    if R is _UNSET:
        R = _monthly_calc(input_dir, year, D, asof)
    if R is None:
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
    if v > TINY_BASE_PCT and abs(b) < TINY_BASE_WON:
        return "작년 거의 없음"   # 2차 전수조사 J7: 작년이 아주 작아 '+41898.4%' 같은 값이 그대로 나왔음
    return ("+" if v >= 0 else "−") + "%.1f%%" % abs(v)


TINY_BASE_PCT = 1000.0   # 증감률이 이보다 크고(작년의 11배 넘음)
TINY_BASE_WON = 1000000   # 작년 금액이 이보다 작으면 비율 대신 '작년 거의 없음'


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
    cut = A.get("cut", 12)
    Yp, Lp = _with_dep(A["Y"], cut), A.get("Lfull") or A["L"]   # 작년 막대는 한 해 전체 (달별 비교라 기간을 줄이지 않음). 올해 영업이익은 요약과 같게 (11/18)
    rev = [v if i < cut else None for i, v in enumerate(Yp["rev_m"])]   # 연중이면 아직 안 끝난 달은 '-'
    op = [v if i < cut else None for i, v in enumerate(Yp["op_m"])]
    lrev = [None] * 12
    if Lp:
        lrev = [Lp["rev_m"][i] if (i + 1) in Lp["months"] else None for i in range(12)]
    rows = [("올해 매출", rev)] + ([("작년 매출", lrev)] if Lp else []) + [("올해 영업이익", op)]
    Wd, pl_, pr, pt_, H, RH = 900, 74, 10, 18, 280, 18
    pb = 30 + RH * len(rows) + 6
    H2 = H + RH * len(rows) + 6
    vals = [0] + [v for v in rev if v is not None] + [v for v in lrev if v] + [v for v in op if v is not None]
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
    top2 = sorted(range(cut), key=lambda i: -(rev[i] or 0))[:2]
    low2 = sorted([i for i in range(cut) if (i + 1) in Yp["months"]], key=lambda i: rev[i] or 0)[:2]
    line = "매출 많은 달: 올해 %s" % "·".join("%d월" % (i + 1) for i in sorted(top2))
    both = [i for i in range(cut) if lrev[i]]
    if both:
        ltop = sorted(both, key=lambda i: -lrev[i])[:2]
        odd = max(both, key=lambda i: abs(rev[i] - lrev[i]))
        line += ", 작년 %s · 적은 달 %s · 유난한 달 %d월: 작년 같은 달보다 %s (%s)" % (
            "·".join("%d월" % (i + 1) for i in sorted(ltop)), "·".join("%d월" % (i + 1) for i in sorted(low2)), odd + 1,
            sgn(rev[odd] - lrev[odd]), chg(rev[odd], lrev[odd]))
    return ("<div class='card mchart'><div class='lab'>달별 매출: 올해%s, 올해 영업이익</div>%s%s<div class='yl' style='font-size:12px'>%s</div></div>"
            % (" 대 작년" if Lp else "", "".join(s), leg, esc(line)))


def _waterfall(A):
    items = [("연초 잔액", A["bal0"], "s")] + [(n, v, "d") for n, v in A["cf"]] + [("기준일 잔액" if A.get("mid") else "연말 잔액", A["bal_end"], "s")]
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
         "<title>%s %d년 연간 %s</title><style>%s%s%s</style></head><body%s><div class='wrap mon'>"
         % (esc(st.get("회사명", "")), year, who, RD.CSS + RD.FS_CSS + RD.DOC_CSS + RD.DOC2_CSS + RD.DOC3_CSS + RD.AIR_CSS + RD.TYPE_CSS, EXTRA_CSS,
            # 대표용만 보는 사람 기준 양식 + 쪽 아래 글 (주간·월간 대표용과 같게, 사용자 2026-11-17)
            (RD._reader_css({"asof": A.get("asof") or dt.date(year, 12, 31)}, "%d년 연간 보고" % year)
             # 연간 '돈 받는 속도' 줄은 마지막 칸이 합계가 아니라 거래처 이름이라 짙은 칸으로 두지 않는다
             + ".rd .flow>div:last-child{background:#F4F5F7!important}.rd .flow>div:last-child .lab{color:#3A4452!important}"
               ".rd .flow>div:last-child .big{color:#17202B!important}") if mode == "ceo" else "",
            " class='rd'" if mode == "ceo" else "")]
    h.append("<div class='doc-h'><h1><span class='co'>%s</span>%d년 연간 %s%s</h1>" % (
        esc(st.get("회사명", "")), year, who, "" if mode == "ceo" else " <span class='badge m'>경영관리용</span>"))
    cut, mid = A.get("cut", 12), A.get("mid")
    asof = A.get("asof") or dt.date(year, 12, 31)
    h.append("<table class='dinfo'><tr><th>보고 기준일</th><td>%s</td><th>손익 집계 기간</th><td>%d-01-01 ~ %s</td></tr>"
             "<tr><th>작성</th><td>%s</td><th>금액 단위</th><td>원</td></tr></table>"
             % (asof.isoformat(), year, _month_end(year, cut).isoformat() if cut else "—", dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
    if Yp is None:
        h.append("<div class='warnbar'>%d년 손익 자료가 없습니다. 위하고 분개장을 받아 '자료 변환'을 먼저 하세요.</div></div></body></html>" % year)
        return "".join(h)
    meta = ["결산 전표 %s" % ("반영됨" if A["closed"] else "아직 없음 (감가상각비·법인세는 예상)")]
    if mid:   # 연중 보고 (사용자 2026-11-14): 끝난 달까지만, 작년도 같은 기간, 통장은 기준일
        meta.append("연중 보고 — 손익은 끝난 달(1~%d월)까지, 작년도 같은 1~%d월과 비교, 통장은 %s 기준%s"
                    % (cut, cut, asof.isoformat(), " (진행 중인 %d월은 비용이 덜 들어와 뺌)" % (cut + 1) if cut < 12 and asof.month == cut + 1 else ""))
    if len(Yp["months"]) < cut:
        meta.append("%d년 손익 %d개월치 (%d월까지)" % (year, len(Yp["months"]), Yp["months"][-1]))
    meta.append("작년 = %d년%s" % (year - 1, (" 1~%d월" % cut if mid else "") + (" (%d개월)" % len(Lp["months"]) if Lp and len(Lp["months"]) < cut else "") if Lp else " 자료 없음"))
    if A.get("M"):   # 사용한 자료와 날짜 (사용자 2026-11-12·14: 숫자를 보일 때 무슨 자료·언제 것인지)
        from . import gate
        meta.append(gate.sources_line(A["M"]))
    h.append("<div class='meta dsrc'>%s</div></div>" % esc(" · ".join(meta)))
    sum_i = len(h)
    h.append("<div class='page fs mon'>")
    goal_all = sum((A["goals"].get((str(year), t["name"])) or (0, 0))[0] or 0 for t in A["teams"])
    lm = ("1~%d월" % cut if mid else "") + (" (%d개월)" % len(Lp["months"]) if Lp and len(Lp["months"]) < cut else "")
    ym = " 1~%d월" % cut if mid else ""   # 올해 숫자 이름 뒤에 붙이는 기간
    # 11/18: 주간 대표 보고와 같은 이름 (같은 숫자를 다른 이름으로 부르던 것)
    bal_lab = "오늘 쓸 수 있는 돈 (%s)" % asof.strftime("%m-%d").lstrip("0") if mid else "연말 통장 잔액"

    # ── 1쪽: 한 해 요약 ──
    h.append("<div class='four top'>")
    h.append(_card("%d년%s 매출" % (year, ym), W(Yp["rev"]), ("작년 %s · %s" % (W(Lp["rev"]), chg(Yp["rev"], Lp["rev"])) if Lp else "")
                   + ("<br>연 목표 %s의 %s%s" % (W(goal_all), pct(Yp["rev"], goal_all), " (기간 %d/12)" % cut if mid else "") if goal_all else "")))
    # 사용자 2026-11-18 '감가상각비가 2번': 장부 감가상각비와 결산 전 예상을 한 줄로 (결산 때처럼 판관비 안에서 영업이익에 반영)
    V, VL = _fold_dep(Yp), _fold_dep(Lp)
    h.append(_card("영업이익", W(V["op"]), "영업이익률 %s%s" % (pct(V["op"], V["rev"]), " · 작년 %s" % W(VL["op"]) if VL else "")
                   + ("<br>결산 전 감가상각비 예상 포함" if V.get("dep_folded") else "")))
    h.append(_card("세전 이익", W(Yp["pre"]), "작년 %s · %s" % (W(Lp["pre"]), chg(Yp["pre"], Lp["pre"])) if Lp else ""))
    h.append(_card(bal_lab, W(A["bal_end"]), "연초 %s · %s" % (W(A["bal0"]), sgn(A["bal_end"] - A["bal0"]))
                   if A["bal0"] is not None and A["bal_end"] is not None else ""))
    h.append("</div>")
    if Lp:
        h.append("<div class='yl'><b>작년 대비</b> 매출 %s, 영업이익 %s, 세전 이익 %s, 영업이익률 %s → %s%s</div>"
                 % (chg(Yp["rev"], Lp["rev"]), chg(V["op"], VL["op"]), chg(Yp["pre"], Lp["pre"]), pct(VL["op"], VL["rev"]),
                    pct(V["op"], V["rev"]), " (작년 같은 1~%d월)" % cut if mid else (" (작년은 %d개월)" % len(Lp["months"]) if not Lp["full"] else "")))
        nm, nl = (cut if mid else 12), len(Lp["months"])
        if 0 < nl < nm and Lp["rev"]:
            # 2차 전수조사 J8: 작년은 달 수가 적어(회사 시작 첫해) 합계 비교가 성장률로 읽힘 → 월평균도 같이
            h.append("<div class='yl'><b>월평균으로 보면</b> 올해 %d개월 · 작년 %d개월이라, 월평균 매출 %s → %s (%s)</div>"
                     % (nm, nl, W(round(Lp["rev"] / float(nl))), W(round(Yp["rev"] / float(nm))), chg(Yp["rev"] / float(nm), Lp["rev"] / float(nl))))
    h.append("<div class='sec'>" + _q("1. %d년%s 손익 (%s)" % (year, ym, "결산 확정" if A["closed"] and A["tax_fixed"] else "결산 전"), "근거 1-1~1-2"))
    rows = [("매출", "rev", ""), ("− 매출원가", "cogs", ""), ("매출총이익", "gp", "hq"), ("− 판매비와관리비", "common", ""),
            ("급여", "sal", "ind"),
            ("감가상각비" + (" (결산 전 예상 포함)" if V.get("dep_folded") or (VL and VL.get("dep_folded")) else ""), "dep", "ind"),
            ("그 밖의 판관비", "other", "ind"), ("영업이익", "op", "tot"),
            ("+ 영업외 수익", "nin", ""), ("− 영업외 비용", "nout", "")]
    if Yp.get("bad_pending"):   # 계산-08 (사용자 2026-11-17): 대손충당금 예상도 먼저 뺌 (월간과 같게)
        rows.append(("− 대손충당금 예상 (결산 전)", "bad_pending", ""))
    rows += [("세전 이익", "pre", "tot"), ("− 법인세 등 (지방소득세 포함)", "tax", ""), ("당기순이익", "net", "tot")]
    Yp["tax"] = A["tax"]
    t = ["<div class='card'><table class='pt pl'><thead><tr><th>구분</th><th>%d년%s</th><th>매출 대비</th>%s</tr></thead><tbody>"
         % (year, ym, "<th>%d년 %s</th><th>증감</th><th>증감률</th>" % (year - 1, lm) if Lp else "")]
    V["tax"] = A["tax"]
    for lab, k, cls in rows:
        a = V.get(k)
        b = VL.get(k) if VL else None
        t.append("<tr class='%s'><td>%s</td><td>%s</td><td>%s</td>%s</tr>" % (
            cls, lab, W(a), pct(a, Yp["rev"]) if a is not None else "",
            "<td>%s</td><td>%s</td><td>%s</td>" % (W(b), sgn(a - b) if a is not None and b is not None else "—", chg(a, b)) if Lp else ""))
    t.append("</tbody></table>")
    fix = []
    if A["closed"]:
        if A["dep_est"]:
            fix.append("· 감가상각비 확정 <b>%s</b> — 연중 예상 %s(%s)보다 %s" % (W(Yp["dep"]), W(A["dep_est"]), A["dep_src"], sgn(Yp["dep"] - A["dep_est"])))
    else:
        if Yp.get("dep_note"):   # 월간과 같은 계산 (apply_monthly)
            fix.append("· %s 감가상각비 = 장부 %s + 결산 전 예상 %s (%s · 월간 보고와 같은 계산) — 한 줄로 합쳐 판관비·영업이익에 넣었습니다" % (
                "연중 보고라 결산 전 —" if mid else "12월 결산 전표가 아직 없어", W(Yp["dep"]), W(Yp.get("dep_pending") or 0), esc(Yp["dep_note"])))
        else:
            fix.append("· %s 감가상각비는 한 해 예상 %s(%s)%s를 먼저 뺐습니다 (월간 보고와 같은 방식)" % (
                "연중 보고라 결산 전 —" if mid else "12월 결산 전표가 아직 없어", W(A["dep_est"]), A["dep_src"],
                " 중 지난 달 수만큼(%d/12) %s" % (cut, W(Yp.get("dep_pending") or 0)) if mid else "") if A["dep_est"]
                       else "· 12월 결산 전표가 아직 없고 감가상각비 예상도 없습니다")
        if Yp.get("bad_pending"):
            fix.append("· 대손충당금 예상 %s도 먼저 뺐습니다%s" % (W(Yp["bad_pending"]), " (%s)" % esc(Yp["bad_note"]) if Yp.get("bad_note") else ""))
            if Lp and not Lp.get("bad_pending"):
                # 2차 전수조사 J9: 올해만 대손충당금 예상을 빼고 작년 같은 기간은 안 빼 같은 기준 비교가 아니었음 → 같은 기준 값도 적음
                same = Yp["pre"] + Yp["bad_pending"]
                fix.append("· 작년%s 세전 이익에는 대손충당금이 없습니다 (작년 장부에 쌓지 않음). 같은 기준(대손충당금 예상 빼기 전)으로 보면 "
                           "올해 세전 이익 %s, 작년 대비 %s" % (" 같은 기간" if mid else "", W(same), chg(same, Lp["pre"])))
        if mid and Lp and Lp.get("dep_pending"):
            fix.append("· 작년 1~%d월도 같은 방식으로 작년 감가상각비 %s를 먼저 뺐습니다 (작년 결산 감가상각비는 12월에 들어가 같은 기간엔 0원)"
                       % (cut, W(Lp["dep_pending"])))
    if A["tax_fixed"]:
        fix.append("· 법인세 등 확정 <b>%s</b> — 결산 전 예상 %s보다 %s" % (W(A["tax"]), W(A["tax_est"]), sgn(A["tax"] - A["tax_est"])))
    else:
        if A.get("tax_same"):
            fix.append("· 법인세 등은 결산 전 예상 — 월간 보고와 같은 계산 (%s과세표준 %s%s%s)%s" % (
                "1~%d월 " % cut if mid else "", W(A["tax_base"]), " = 세전 이익 + 세무조정 예상 %s" % sgn(A["tax_adj"]) if A["tax_adj"] else "",
                " · 작년 신고서의 감면·넘어온 공제 반영" if A.get("tax_credit") else "", " — 한 해 이익이 정해지면 바뀜" if mid else ""))
        else:
            fix.append("· 법인세 등은 결산 전 예상 (%s세전 이익 × 세율, 세무조정 없음%s)" % (
                "1~%d월 " % cut if mid else "", " — 한 해 이익이 정해지면 바뀜" if mid else ""))
    t.append("<div class='wsub'>결산 확정치와 연중 예상 차이</div><div class='fix'>%s</div></div></div>" % "<br>".join(fix))
    h.append("".join(t))

    # ── 2쪽: 계절 흐름 · 현금 흐름 ──
    h.append("<div class='sec pgb'>" + _q("2. 계절 흐름 (달별 매출%s)" % (" · 작년 같은 달" if Lp else ""), "근거 2-1") + _season_chart(A) + "</div>")
    if A["cf"] and A["bal0"] is not None:
        lo = [(i, v) for i, v in enumerate(A["bal_m"]) if v is not None]
        low = min(lo, key=lambda x: x[1]) if lo else None
        op_net = sum(v for n, v in A["cf"] if n in ("영업 입금", "영업 지급"))
        taxv = sum(v for n, v in A["cf"] if n in CF_TAX)
        note = "영업으로 남긴 돈 %s · %s %s" % (sgn(op_net), next((n for n, _ in A["cf"] if n in CF_TAX), "세금"), W(-taxv))
        if low:
            note += " · 월말 잔액이 가장 적었던 달 %d월 %s" % (low[0] + 1, W(low[1]))
        if A.get("cf_gap"):
            note += " · 분류 못 한 차이 %s" % sgn(A["cf_gap"])
        h.append("<div class='sec'>" + _q("3. %s 현금 흐름" % ("1/1~%s" % asof.strftime("%m/%d").lstrip("0") if mid else "한 해"), "근거 3-1~3-2")
                 + "<div class='card'><div class='lab'>연초 잔액 → 영업 · 세금 · 투자 · 대출 → %s</div>" % ("기준일 잔액" if mid else "연말 잔액")
                 + _waterfall(A) + "<div class='note'>%s</div></div></div>" % esc(note))
    else:
        h.append("<div class='sec'>" + _q("3. %s 현금 흐름" % ("1/1~%s" % asof.strftime("%m/%d").lstrip("0") if mid else "한 해"), "근거 3-1~3-2") + "<div class='note'>%s</div></div>" % (
            "최신 자금계획서·분개장이 없어 통장 숫자를 비웠습니다 (틀린 숫자를 보이지 않으려는 것)." if A.get("blocked")
            else "통장 흐름 자료 없음 — '자료 변환'을 다시 하면 연간자료.csv 가 생깁니다."))

    # ── 3쪽: 거래처 · 팀 ──
    h.append("<div class='sec pgb'>" + _q("4. 거래처: 쏠림 · 변화 · 돈 받는 속도%s" % (" (올해는 기준일까지, 작년은 한 해)" if mid else ""), "근거 4-1~4-3"))
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
        h.append(_card("끊긴 거래처" if not mid else "올해 아직 거래 없는 곳", "%d곳" % len(A["lost"]),
                       "작년 매출 %s · 올해 %s거래 없음" % (W(sum(v for _, _, v in A["lost"])), "기준일까지 " if mid else "")))
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
    h.append("<div class='sec'>" + _q("5. 팀별 %s 실적 · 연 목표 대비" % ("1~%d월" % cut if mid else "한 해"), "근거 5-1~5-3"))
    tt = ["<div class='card'><table class='pt tgy jg'><thead><tr><th>팀</th><th>연 매출 목표</th><th>매출</th><th>달성률%s</th><th>작년 매출%s</th><th>작년 대비</th>"
          % ("<br><small>기간 %d/12 = %s</small>" % (cut, pct(cut, 12)) if mid else "", "<br><small>같은 1~%d월</small>" % cut if mid else "")
          + ("<th>올해 매출 예상<br><small>매출 + 앞으로 잡힐 매출</small></th>" if mid else "") + "<th>매출총이익</th><th>수익률<br><small>실제 / 목표</small></th><th>판정</th></tr></thead><tbody>"]
    for T in A["teams"]:
        g = T["goal"] or (None, None)
        a = T["rev"] * 100.0 / g[0] if g[0] else None
        rate = T["gp"] / float(T["rev"]) if T["rev"] else None
        chip = ""
        exp = None if T.get("left") is None else T["rev"] + T["left"]
        if a is not None:   # 연중이면 매출 + 앞으로 잡힐 매출(올해 매출 예상)을 연 목표와 비교 (J2). 모르면 판정하지 않음
            if mid and a < 100:
                if exp is not None:
                    chip += "<span class='chip c-ok'>올해 예상 달성</span>" if exp >= g[0] else "<span class='chip c-over'>올해 예상 미달</span>"
            else:
                chip += "<span class='chip c-ok'>목표 이상</span>" if a >= 100 else "<span class='chip c-over'>목표 미달</span>"
        if g[1] is not None and rate is not None:
            chip += "<span class='chip c-ok'>수익률 달성</span>" if rate >= g[1] else "<span class='chip c-over'>수익률 미달</span>"
        tt.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>%s<td>%s</td><td>%s / %s</td><td>%s</td></tr>" % (
            esc(T["name"]), W(g[0]), W(T["rev"]),
            ("<span class='tbar'><i style='width:%d%%'></i><s style='left:%d%%'></s></span>%.1f%%" % (min(a, 100), round(100.0 * cut / 12), a)) if a is not None else "목표 없음",
            W(T["lrev"]), chg(T["rev"], T["lrev"]),
            ("<td>%s</td>" % ("미확인" if exp is None else W(exp) + ("<br><small>목표의 %s</small>" % pct(exp, g[0]) if g[0] else ""))) if mid else "",
            W(T["gp"]), pct(T["gp"], T["rev"]), _tpct(g[1]) if g[1] is not None else "—", chip))
    TN = A.get("team_none")
    if TN:   # F6: 팀 없는 장부 줄 (대표 직접 프로젝트 등) — 팀 합계가 회사와 맞게
        tt.append("<tr><td>%s</td><td></td><td>%s</td><td></td><td>%s</td><td>%s</td>%s<td>%s</td><td>%s</td><td></td></tr>" % (
            "팀 미지정<br><small>팀 없는 장부 줄</small>", W(TN["rev"]), W(TN["lrev"]), chg(TN["rev"], TN["lrev"]), "<td></td>" if mid else "", W(TN["gp"]), pct(TN["gp"], TN["rev"]) if TN["rev"] else ""))
    allT = list(A["teams"]) + ([TN] if TN else [])
    trev, tgp = sum(T["rev"] for T in allT), sum(T["gp"] for T in allT)
    tl = sum(T["lrev"] or 0 for T in allT) or None
    tt.append("<tr class='tot'><td>팀 합계</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>%s<td>%s</td><td>%s</td><td></td></tr></tbody></table>"
              % (W(goal_all or None), W(trev), pct(trev, goal_all) if goal_all else "", W(tl), chg(trev, tl),
                 ("<td>%s</td>" % ("" if any(T.get("left") is None for T in A["teams"]) else W(trev + sum(T["left"] for T in A["teams"])))) if mid else "",
                 W(tgp), pct(tgp, trev)))
    lines = []
    mg = mode != "ceo"
    lq = min(3, (cut - 1) // 3) if cut else 0   # 연중이면 마지막(진행) 분기까지
    qs = [(T["name"], T["q"][0][1], T["q"][lq][1]) for T in A["teams"] if T["q"][0][1] is not None]
    if qs and mg:   # 연평균 인원으로 나눠 인원이 늘면 생산성이 오른 것처럼 보여 대표용에선 뺌 (7절·Y4), 경영관리는 그대로
        lines.append("<li><b>분기 추이</b> 1인당 영업이익 %s (1분기 → %d분기%s)</li>" % (
            ", ".join("%s %s → %s" % (esc(n), W(a), W(b)) for n, a, b in qs), lq + 1, " · %d월까지" % cut if cut % 3 else ""))
    PR = A["proj"]
    if PR["list"]:
        st_ = proj_stats(PR["list"])
        # 평균 수익률은 원가 확인된 것만 매출 가중으로 (Y1). 대표용은 평균 줄 대신 원가 확인 건수 (7절)
        avg = (" · 평균 수익률 %.1f%% (원가 확인된 %d건, 매출 가중)" % (100.0 * st_["avg"], st_["known"])) if (mg and st_["avg"] is not None) else ""
        lines.append("<li><b>프로젝트</b>%s %d건%s · 원가 확인 %d건·미확인 %d건%s · 목표 수익률 미달 %d건 · 적자 %d건</li>"
                     % (" (1~%d월에 행사 끝남)" % cut if mid else "", st_["n"], " (작년 같은 기간 %d건)" % PR["lall"] if PR["lall"] and mid else (" (작년 %d건)" % PR["lall"] if PR["lall"] else ""), st_["known"], st_["unknown"], avg, st_["under"], st_["loss"]))
    if Lp and Lp["acct"]:
        # 1차 C7 (2026-11-18): 설명 줄은 +67.9%, 표는 +71.1% 였음 — 표와 같은 값(결산 전 감가상각비 예상 포함)을 쓴다.
        # '많이 늘어난 항목'은 비율 순이라 1만 원짜리 항목(+50279.8%)이 맨 앞에 왔음 → 늘어난 금액 순
        Yf, Lf = _with_dep(Yp, cut), _with_dep(Lp, cut)
        ups = sorted([(k, v, Lf["acct"].get(k, 0)) for k, v in Yf["acct"].items() if v > Lf["acct"].get(k, 0)],
                     key=lambda x: -(x[1] - x[2]))[:3]
        lines.append("<li><b>판관비</b> %s (매출 대비 %s → %s) · 많이 늘어난 항목: %s</li>" % (
            chg(Yf["common"], Lf["common"]), pct(Lf["common"], Lf["rev"]), pct(Yf["common"], Yf["rev"]),
            ", ".join("%s %s%s" % (esc(k), sgn(a - b), " (%s)" % chg(a, b) if b else "") for k, a, b in ups) or "없음"))
    if lines:
        tt.append("<ul class='nl' style='font-size:12px;color:var(--ink)'>%s</ul>" % "".join(lines))
    tt.append("</div></div>")
    h.append("".join(tt))

    # ── 4쪽: 다음 해 준비 ──
    h.append("<div class='sec pgb'>" + _q("6. %d년 준비" % (year + 1), "근거 6-1~6-2"))
    h.append("<div class='four c3'>")
    h.append(_card("법인세 납부 (%s)" % "%d/%d" % (A["pay_corp_day"].month, A["pay_corp_day"].day), W(max(A["corp"] - A["prepaid"], 0)),
                   "법인세 %s − 중간예납 등 %s%s" % (W(A["corp"]), W(A["prepaid"]), "" if A["tax_fixed"] else (" · 1~%d월 이익 기준 예상" % cut if mid else " · 예상"))))
    lp = A.get("local_paid") or 0
    h.append(_card("지방소득세 납부 (%s)" % "%d/%d" % (A["pay_local_day"].month, A["pay_local_day"].day), W(max(A["local"] - lp, 0)),
                   "법인세 산출세액 × 10%%%s" % ((" − 원천징수된 지방소득세 %s" % W(lp)) if lp else "")))
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
    h.append("<div class='wsub'>%d년 목표</div>" % (year + 1))   # 11/18: 대표용엔 안내 문구를 넣지 않는다 (사용자 2026-11-17)
    rows_ = []
    for T in A["teams"]:
        g = A["goals_next"].get(T["name"])
        got = sum(p["est"] or 0 for p in NX if p["team"] == T["name"])
        rows_.append([esc(T["name"]), W(T["rev"]), pct(T["gp"], T["rev"]),
                      W(g[0]) if g and g[0] else "<span class='blank'>입력 전</span>",
                      _tpct(g[1]) if g and g[1] is not None else "<span class='blank'>입력 전</span>",
                      W(got) + (" (%s)" % pct(got, g[0]) if g and g[0] else "")])
    h.append(_tab(["팀", "%d년%s 매출" % (year, ym), "%d년%s 수익률" % (year, ym), "%d년 매출 목표" % (year + 1), "%d년 목표 수익률" % (year + 1), "목표 중 이미 받은 일"], rows_, "pt tgy"))
    h.append("</div></div>")
    # 기업신용평가 미리보기는 대표 보고에서 뺌 (사용자 2026-11-18 결정 '대표 보고에서 뺌': 결산 전 장부로 어림한 등급이라 오해 소지). 전체는 경영관리 9장
    if mode == "ceo":
        h.append("<div class='evid'>숫자 옆 ‘근거’ 번호로 요청하시면 경영관리가 해당 근거자료를 제출합니다.<span class='doc-end'>끝.</span></div></div></div></body></html>")
    else:
        # 영역별 보기 (사용자 2026-11-11): 요약 · 위험 분석 · 상세 1~6 을 한 영역씩 (주간·월간 경영관리 보고와 같은 방식)
        from . import areas
        parts = [("sum", "요약 (대표 보고 화면)", "보고 요약", "".join(h[sum_i:]) + "</div>")] + _detail(A)
        parts[-1] = parts[-1][:3] + (parts[-1][3] + "<div class='evid'><span class='doc-end'>끝.</span></div>",)
        from . import digest   # 쉬운 설명 · 제안 상자 (사용자 2026-11-13: 요청한 자료는 전부 쉬운 설명과 제안을 붙여 경영관리에서)
        rk = _risks(A)
        parts = [(k, lab, g, digest.annual_box(k, A, rk) + body) for k, lab, g, body in parts]
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
    mid_ = A.get("cut", 12) < 12   # 연중이면 매출 + 앞으로 잡힐 매출을 연 목표와 비교 (J2). 앞으로 잡힐 매출을 모르면 올리지 않음
    for T in A["teams"]:
        g = T["goal"] or (None, None)
        if not g[0] or T["rev"] >= g[0]:
            continue
        if mid_:
            if T.get("left") is None or T["rev"] + T["left"] >= g[0]:
                continue
            out.append(("중간", "팀", "%s 매출 목표 %s, 앞으로 잡힐 매출까지 더하면 %s, 수익률 %s." % (
                esc(T["name"]), pct(T["rev"], g[0]), pct(T["rev"] + T["left"], g[0]), pct(T["gp"], T["rev"])),
                "모자라는 매출 %s 을 올해 안에 더 받을 수 있는지 확인." % W(g[0] - T["rev"] - T["left"])))
        else:
            out.append(("중간", "팀", "%s 매출 목표 %s, 수익률 %s." % (esc(T["name"]), pct(T["rev"], g[0]), pct(T["gp"], T["rev"])),
                        "미달 원인 확인 후 다음 해 목표에 반영."))
    loss = [x for x in A["proj"]["list"] if x["rate"] is not None and x["rate"] < 0]
    if loss:
        out.append(("중간", "프로젝트", "적자 프로젝트 %d건 (%s)." % (len(loss), ", ".join(esc(x["id"]) for x in loss[:5])), "추가 원가·견적 누락 여부 확인."))
    Yp, Lp = A["Y"], A["L"]
    if Lp and Lp["rev"]:
        g = Yp["rev"] / float(Lp["rev"])
        for k, v in Yp["acct"].items():
            b = Lp["acct"].get(k)
            if b and v / float(b) > g * 1.2 and v - b > 1000000:
                c_ = chg(v, b)
                out.append(("낮음", "비용", "%s %s (매출 %s보다 빠르게 늘어남)." % (
                    esc(k), "%s원 (작년 %s원)" % (W(v), W(b)) if c_ == "작년 거의 없음" else c_, chg(Yp["rev"], Lp["rev"])), "늘어난 이유 확인, 다음 해 예산에 반영."))
    if not A["closed"] and A.get("mid"):
        out.append(("낮음", "자료", "연중(%s 기준) 보고 — 감가상각비·법인세는 예상, 손익은 1~%d월." % (A["asof"].isoformat(), A["cut"]),
                    "결산 뒤 위하고에서 분개장을 다시 받아 '자료 변환' 후 다시 만듦."))
    elif not A["closed"]:
        out.append(("높음", "자료", "12월 결산 전표가 아직 없음 (감가상각비·법인세가 예상).", "결산 뒤 위하고에서 분개장을 다시 받아 '자료 변환' 후 다시 만듦."))
    return out


def _detail(A):
    year = A["year"]
    Yp, Lp = _with_dep(A["Y"], A.get("cut", 12)), _with_dep(A["L"], A.get("cut", 12))   # 1절 요약과 같은 영업이익 (11/18)
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
    cm = A.get("cut", 12)
    d.append("<div class='tw'>" + _tab(["구분"] + ["%d월" % (i + 1) for i in range(12)] + ["합계"],
                                      [[n] + [W(v) if i < cm else "—" for i, v in enumerate(vs)] + [W(sum(vs))] for n, vs in rows], "pt tx m12") + "</div>")
    if cm < 12:
        d.append("<div class='note'>연중 보고: %d월부터는 아직 끝나지 않은 달이라 비움 (기준일 %s)</div>" % (cm + 1, A["asof"].isoformat()))
    if Yp.get("dep_spread"):
        d.append("<div class='note'>판관비·영업이익에 결산 전 감가상각비 예상 %s원을 1~%d월에 고르게 나눠 넣음 (요약의 영업이익과 같은 금액)</div>"
                 % (W(Yp["dep_spread"]), cm))
    d.append("<div class='note'>영업외 수익 %s · 영업외 비용 %s 는 연 합계로 손익표에 반영 (부서비용 기준)</div>" % (W(Yp["nin"]), W(Yp["nout"])))
    d.append("<div class='evh'>근거 1-2 · 결산 확정치와 연중 예상</div>")
    d.append(_tab(["항목", "연중 예상", "결산", "차이", "예상 근거"], [
        ["감가상각비 (한 해 전체)", W(A["dep_est"]), W(Yp["dep"]) if A["closed"] else "결산 전", sgn(Yp["dep"] - A["dep_est"]) if A["closed"] and A["dep_est"] else "—", esc(A["dep_src"] or "")],
        ["법인세 등", W(A["tax_est"]), W(A["tax"]) if A["tax_fixed"] else "결산 전", sgn(A["tax"] - A["tax_est"]) if A["tax_fixed"] else "—", "월간 보고와 같은 계산 (10장)" if A.get("tax_same") else "세전 이익 × 세율, 세무조정 없음"]], "pt evt"))
    cut("d1", "1. " + names[0])
    d.append("<h2 id='d2'>2. 분기별 실적</h2><div class='evh'>근거 2-1 · 분기 합계%s</div>" % ("와 작년 같은 분기" if Lp else ""))
    qr = []
    for k in range(4):
        sl = slice(k * 3, k * 3 + 3)
        r_ = sum(Yp["rev_m"][sl])
        lr = sum(Lp["rev_m"][sl]) if Lp else None
        buy = [v for v in Yp["buy_m"][sl] if v is not None]
        if k * 3 + 1 > cm:
            qr.append(["%d분기" % (k + 1)] + ["—"] * 6)
            continue
        qr.append(["%d분기" % (k + 1) + (" (%d월까지)" % cm if k * 3 + 3 > cm else ""), W(r_), W(sum(buy)) if buy else "—", W(r_ - sum(Yp["cogs_m"][sl])), W(sum(Yp["op_m"][sl])), W(lr), chg(r_, lr)])
    d.append(_tab(["분기", "매출", "매입", "매출총이익", "영업이익", "작년 같은 분기 매출", "매출 증감률"], qr, "pt pl",
                  ["합계", W(Yp["rev"]), W(Yp["buy"]), W(Yp["gp"]), W(Yp["op"]), W(Lp["rev"] if Lp else None), chg(Yp["rev"], Lp["rev"] if Lp else None)]))
    cut("d2", "2. " + names[1])
    d.append("<h2 id='d3'>3. 통장 흐름</h2><div class='evh'>근거 3-1 · 한 해 현금 흐름 분류 (%s)</div>"
             % ("현금흐름표와 같은 분류" if A.get("cf_same") else "보통예금 상대 계정"))
    why = {"영업 입금": "고객 대금·지원금·예금 이자 등 본업으로 들어온 돈", "영업 지급": "업체·법인카드·급여·프리랜서·대출 이자 등 본업으로 나간 돈",
           "세금·4대보험": "부가세·법인세·원천세·4대보험 납부", "투자": "3개월 넘는 예금·보증금·장비 등", "대출 받음": "은행 대출 받음",
           "대출 갚음": "대출 원금 갚음 (이자는 영업 지급)", "자본금 납입": "주주가 넣은 돈", "대표이사 돈": "대표이사에게 받거나 돌려드린 돈 (가수금)",
           "3개월 이내 정기예금": "통장에서 현금성 정기예금으로 옮긴 돈 (찾으면 +)"} if A.get("cf_same") else {"영업 입금": "외상매출금·선수금 등 (아래 분류가 아닌 계정)", "영업 지급": "외상매입금·미지급금·급여·판관비 등", "세금": "부가세·예수금·선납세금·법인세 계정",
           "투자": "유형·무형자산 계정", "대출 받음": "차입금 대변", "대출 갚음": "차입금 차변", "자본금 납입": "자본금 계정"}
    d.append(_tab(["구분", "금액", "나눈 기준"], [["연초 잔액", W(A["bal0"]), ""]] + [[esc(n), sgn(v), why.get(n, "")] for n, v in A["cf"]]
                  + [["%s 잔액" % (A["asof"].isoformat() if A.get("mid") else "연말"), W(A["bal_end"]), "분류 못 한 차이 %s" % sgn(A["cf_gap"]) if A.get("cf_gap") else ""]], "pt evt"))
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
        lost_lab = "올해 아직 거래 없는 곳" if A.get("mid") else "끊긴 거래처"   # 2차 전수조사 J12: 연중엔 요약과 같은 이름
        d.append("<div class='evh'>근거 4-2 · 새로 생긴 거래처 %d곳 · %s %d곳</div><div class='cf'><div>%s</div><div>%s</div></div>" % (
            len(A["new"]), lost_lab, len(A["lost"]),
            _tab(["새 거래처", "올해 매출"], [[_vname(n, c), W(v)] for n, c, v in A["new"]], "pt", ["합계", W(sum(v for _, _, v in A["new"]))]),
            _tab([lost_lab, "작년 매출"], [[_vname(n, c), W(v)] for n, c, v in A["lost"]], "pt", ["합계", W(sum(v for _, _, v in A["lost"]))])))
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
            st_ = proj_stats(ps)
            rows.append([esc(tm), "%d건" % len(ps), W(int(round(sum(x["rev"] for x in ps) / float(len(ps))))),
                         ("%.1f%%" % (100.0 * st_["avg"]) if st_["avg"] is not None else "—") + (" (원가 미확인 %d건 뺌)" % st_["unknown"] if st_["unknown"] else ""),
                         "%d건" % st_["under"], "%d건" % st_["loss"], "%d건" % PR["lcount"].get(tm, 0)])
        d.append(_tab(["팀", "프로젝트 수", "건당 평균 매출", "평균 수익률 (매출 가중)", "목표 수익률 미달", "적자", "작년 프로젝트 수"], rows, "pt tgy"))
        under = sorted([x for x in PR["list"] if x["rate"] is not None and x["target"] is not None and x["rate"] < x["target"]], key=lambda x: x["rate"])
        if under:
            d.append("<div class='wsub'>목표 수익률 미달 프로젝트 %d건</div>" % len(under))
            d.append(_tab(["팀", "프로젝트", "매출", "수익률", "목표"], [[esc(x["team"]), esc("%s %s" % (x["id"], x["name"])), W(x["rev"]),
                                                                       "<span class='%s'>%.1f%%</span>" % ("up" if x["rate"] < 0 else "", x["rate"] * 100), _tpct(x["target"])] for x in under], "pt evt"))
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
    d.append(_tab(["단계", "금액"], [["세전 이익", W(Yp["pre"])], ] + ([["과세표준 (세전 이익%s)" % (" + 세무조정 예상 %s" % sgn(A["tax_adj"]) if A["tax_adj"] else ""), W(A["tax_base"])]] if A.get("tax_same") else []) + [
                                   ["법인세 등 %s" % ("확정 (결산 전표)" if A["tax_fixed"] else ("예상 (월간 보고와 같은 계산, 10장)" if A.get("tax_same") else "예상 (세무조정 없음)")), W(A["tax"])],
                                   ["법인세 (지방소득세 뺀 것)", W(A["corp"])], ["− 중간예납 등 선납세금", W(A["prepaid"])],
                                   ["= %s 납부" % A["pay_corp_day"].isoformat(), W(max(A["corp"] - A["prepaid"], 0))],
                                   ["지방소득세 (%s 납부%s)" % (A["pay_local_day"].isoformat(), " · 원천징수된 지방소득세 %s 뺌" % W(A.get("local_paid") or 0) if A.get("local_paid") else ""), W(max(A["local"] - (A.get("local_paid") or 0), 0))]], "pt pl"))
    NX = A["next"] or []
    if NX:
        d.append("<div class='evh'>근거 6-2 · %d년 행사 프로젝트 %d건</div>" % (year + 1, len(NX)))
        d.append(_tab(["팀", "프로젝트", "행사일", "사전견적", "추정 예산", "집행액", "잔여"],
                      [[esc(p["team"]), esc("%s %s" % (p["id"], p["name"])), p["day"].isoformat(), W(p["est"]), W(p["budget"]), W(p["paid"]),
                        W((p["budget"] or 0) - p["paid"])] for p in NX], "pt evt"))
        d.append("<div class='note'>추정 예산 = 사전견적 × (1 − 그 팀 목표 수익률)</div>")
    loans = ((A.get("credit") or {}).get("E") or {}).get("loans")
    if loans:   # 대출 만기 (사용자 2026-11-14: 기술보증기금 대출은 매년 연장 예정 → 원금 상환으로 잡지 않고 표시)
        d.append("<div class='evh'>근거 6-3 · 대출 잔액과 만기</div>")
        d.append(_tab(["대출", "잔액", "만기", "상태"], [[esc(v), W(bal), m_.isoformat() if m_ else "모름", esc(st_)]
                                                  for v, bal, m_, k_, cur_, st_ in loans], "pt evt"))
        d.append("<div class='note'>만기는 장부 적요·창에 넣은 날짜 기준. 매년 연장하는 대출은 원금 상환으로 잡지 않습니다 (연장이 안 되면 만기에 원금 상환).</div>")
    cut("d6", "6. " + names[5])
    from . import cashflow   # 연간 현금흐름표 (사용자 2026-11-12: 연간 누적으로도). 경영관리용에만
    d.append("<h2 id='d7'>7. 현금흐름표</h2>" + ("<div class='note'>최신 자금계획서·분개장이 없어 현금흐름표 숫자를 비웠습니다.</div>"
                                                 if A.get("blocked") else cashflow.render(A.get("cfs"))))
    cut("d7", "7. 현금흐름표")
    from . import surplus
    d.append("<h2 id='d8'>8. 이익잉여금처분계산서</h2>" + surplus.render(A.get("re"), tb_at="11장" if ((A.get("M") or {}).get("re") or {}).get("tb") else None))
    cut("d8", "8. 이익잉여금처분계산서")
    from . import credit   # 기업신용평가 미리보기 (사용자 2026-11-12): 연간 경영관리 보고에 늘
    d.append("<h2 id='d9'>9. 기업신용평가 미리보기</h2>" + credit.render(A.get("credit")))
    cut("d9", "9. 기업신용평가 미리보기")
    # 10~14 (사용자 2026-11-17 '연간 보고에 넣어야 할 항목 전부'): 월간 경영관리의 분기·반기 절과 같은 계산·같은 표
    M, pack = A.get("M"), A.get("pack")
    none = "<div class='note'>월간 보고 계산 자료가 없어 만들지 못했습니다 (자료 변환 뒤 다시 만들면 생김).</div>"
    d.append("<h2 id='d10'>10. 법인세 예상 · 세무조정 예상</h2>")
    if A["tax_fixed"]:
        d.append("<div class='note'>결산 법인세가 장부에 들어와 6장의 확정 금액을 씁니다. 아래는 결산 전 계산(참고)입니다.</div>")
    d.append((pack or {}).get("tax_table") or none)
    if M and M.get("taxadj"):
        from . import taxadj
        d.append("<div class='evh'>세무조정 예상</div>" + taxadj.render(M["taxadj"], esc))
    elif M:
        d.append("<div class='note'>세무조정 예상 자료 없음 (자료 변환을 하면 세무조정.csv 가 생김)</div>")
    cut("d10", "10. 법인세·세무조정", "결산·세무")
    from . import taxbreak
    tb = ((M or {}).get("re") or {}).get("tb")
    d.append("<h2 id='d11'>11. 법인세 감면·공제 전체 검토</h2>" + (taxbreak.render(tb, esc) if tb else none))
    cut("d11", "11. 감면·공제 검토", "결산·세무")
    d.append("<h2 id='d12'>12. 신고 일정 · 신고 도우미</h2>")
    if M and (M.get("filing") or M.get("filing_help")):
        from . import filing
        d.append("<h3>신고 일정 (장부 기준)</h3>" + filing.render(M.get("filing"), esc) + (M.get("filing_help") or ""))
    else:
        d.append("<div class='note'>신고 일정 자료 없음</div>")
    cut("d12", "12. 신고 일정·도우미", "결산·세무")
    d.append("<h2 id='d13'>13. 급여 점검 · 연말정산 예상</h2>"
             + ((M or {}).get("payroll") or "<div class='note'>위하고 인사·급여 자료가 없어 만들지 않음</div>"))
    cut("d13", "13. 급여 점검·연말정산", "결산·세무")
    d.append("<h2 id='d14'>14. 예산 대비</h2>"
             + ((pack or {}).get("budget") or "<div class='note'>확정한 %d년 예산이 없어 만들지 않음 (창 ‘내년 예산’에서 ‘예산 확정’을 누르면 생김)</div>" % year))
    cut("d14", "14. 예산 대비", "결산·세무")
    return out
