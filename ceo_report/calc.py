"""보고 숫자 계산. 대표용과 경영관리용은 이 결과 하나를 함께 쓴다."""
import calendar
import datetime as dt
from collections import OrderedDict, defaultdict

from . import fundplan
from .data import DEFAULT_SETTINGS, EXEC_STATES, TRANSFER, is_prior
from .util import Issues, is_blank, setting_num, ssum, ssum_or_none, won, d2s
from .util import date as parse_date

INTRANET_IN_FUNDS = False   # 인트라넷 지급요청·집행계획을 가용자금 일정에 넣을지 (사용자 2026-11-04: 넣지 않음, 비교만)
BUDGET_IN_FUNDS = True      # 프로젝트 남은 예산(사전견적×원가율 − 쓴 돈)을 예상 지출로 넣을지 (2026-11-04 결정 카드 대기, 권장 넣음)

DAY = dt.timedelta(days=1)


def from_intranet(e):
    """변환이 인트라넷 지급요청으로 만든 프로젝트집행 줄 (근거 '지급요청 …', 아직 장부에 없는 요청).
    사용자 2026-11-04: 인트라넷에서는 사전견적만 쓰고, 쓴 돈·남은 예산은 위하고 자료로 본다 → 이 줄은 비교로만."""
    return e["state"] == "요청미지급" and str(e.get("basis") or "").startswith("지급요청")

# 숫자로 읽는 설정 항목과 입력 확인 목록에 쓰는 이름 (이름에 해석·권고 낱말을 넣지 않는다)
NUM_SETTINGS = ("첫화면_프로젝트_표시수", "위험_최소보유현금", "위험_미수경과일", "위험_미발행경과일", "위험_자료경과일",
                "위험_예산초과율", "예산_원가율")
BUDGET_REASONS = ("사전견적 없음", "사전견적 0원 또는 음수", "사전견적 금액 해석 불가", "원가율 설정 오류")
SETTING_LABELS = {
    "첫화면_프로젝트_표시수": "첫화면_프로젝트_표시수", "위험_최소보유현금": "최소 보유현금",
    "위험_미수경과일": "미수 경과일 기준", "위험_미발행경과일": "미발행 경과일 기준",
    "위험_자료경과일": "자료 경과일 기준", "위험_예산초과율": "예산 초과율 기준", "예산_원가율": "예산_원가율",
}


def _add_months(d, n):
    y, m = d.year + (d.month - 1 + n) // 12, (d.month - 1 + n) % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def budget_due(event_date, asof):
    """남은 예산의 지급 예정일 (D-54): 행사일 다음 달 마지막 금요일. 그 날이 기준일 이전·당일이면 기준일 다음 금요일.

    행사일을 모르면 None (날짜 없는 지급 예정). 12월 행사는 다음 해 1월 말로 이어진다.
    """
    if event_date is None:
        return None
    nxt = _add_months(dt.date(event_date.year, event_date.month, 1), 1)
    due = _month_end(nxt)
    due -= (due.weekday() - 4) % 7 * DAY
    if due <= asof:
        # 기한이 지난 남은 예산은 다음 금요일 한 주에 몰지 않고 그달 남은 금요일에 나눈다 (사용자 2026-11-05 결정 카드 권장안:
        # 11월 출금 예상에는 그대로 두되 한 주에 1.1억이 몰려 가용자금이 마이너스로 보이던 것). 남은 금요일이 하나뿐이면 다음 달 말까지.
        first = asof + ((4 - asof.weekday()) % 7 or 7) * DAY
        due = _last_friday(first)
        if due <= first:
            due = _last_friday(_add_months(dt.date(first.year, first.month, 1), 1))
    return due


def _last_friday(d):
    e = _month_end(d)
    return e - (e.weekday() - 4) % 7 * DAY


def _event_date(text):
    if isinstance(text, dt.date):
        return text
    import re
    # 기간으로 적힌 행사일 '2026.04.06-2026.04.08'·'…~…' 은 끝난 날로 본다 (사용자 2026-11-05 미발행 '확인 필요 1건')
    m = re.match(r"^\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})\s*[~\-–]\s*(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})\s*$", str(text or ""))
    if m:
        text = m.group(2)
    try:
        return parse_date(text)
    except Exception:  # 해석할 수 없는 행사일은 날짜 없는 지급 예정으로 둔다
        return None


BUDGET_VAT = 0.1      # 남은 예산은 공급가 기준이므로 지급(현금)은 부가세 10%를 더한다 (적게 보이지 않게)
DONE_STATES = ("완료", "완료(예전 인트라넷)")
OLD_STATE = "완료(예전 인트라넷)"   # old_intranet.OLD_STATE: 원가·매출 줄 연결에만 쓰고 프로젝트 표·미발행·예상 매출에서 뺀다


def _month_end(d):
    return dt.date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def period_of(kind, asof, start=None):
    if start:
        return start, asof
    if kind == "weekly":
        return asof - 6 * DAY, asof
    return asof.replace(day=1), asof


def _fmt_setting(v):
    return "{:,}".format(v) if isinstance(v, int) else "%g" % v


def _add(a, b):
    return None if a is None or b is None else a + b


TWO_SOURCE_KINDS = ("자금계획서", "자금일정", "프로젝트집행")


def two_sources(events, asof):
    """출금 출처 하나 원칙 점검 (사용자 2026-11-04): 기준일 뒤 같은 거래처·같은 달 출금이 두 출처 이상에 있으면 목록.
    거래처는 거래처코드, 없으면 이름으로 맞춘다. 같은 돈일 수 있다는 신호일 뿐 빼지는 않는다.
    -> [{vendor, month, sources: {출처: 금액}}] 금액 큰 순."""
    from .wehago import norm_code, norm_vendor
    groups = OrderedDict()
    for ev in events:
        if ev["io"] != "out" or ev["amount"] is None or ev["date"] is None or ev["date"] <= asof:
            continue
        src = ev.get("source")
        if src not in TWO_SOURCE_KINDS:
            continue
        key = norm_code(ev.get("vendor_code")) or norm_vendor(ev.get("desc") or "")
        if not key:
            continue
        g = groups.setdefault((key, ev["date"].strftime("%Y-%m")), {"vendor": ev.get("desc") or key, "vcode": norm_code(ev.get("vendor_code")),
                                                                     "month": ev["date"].strftime("%Y-%m"), "sources": OrderedDict()})
        g["sources"][src] = g["sources"].get(src, 0) + ev["amount"]
    out = [g for g in groups.values() if len(g["sources"]) > 1]
    out.sort(key=lambda g: -sum(g["sources"].values()))
    return out


def compute(d, kind, asof, start=None, pick=None, payday=None):
    # compute()는 읽어 온 Data를 바꾸지 않는다: 입력 확인 목록과 계산서 줄은 복사본에서 다룬다 (두 번 계산해도 같은 결과).
    issues = Issues()
    issues.items = list(d.issues.items)
    # 계산서 자료를 쓸 수 없으면(파일 없음·읽지 못함·금액/날짜 열 없음) 발행·미수·입금예정은 0이 아니라 '자료 없음'이고,
    # 계산서 입금은 일정에 넣지 않는다 (입금이 빠지면 계산 잔액은 낮아지는 쪽이므로 최저 잔액은 그대로 계산한다).
    in_missing = list(getattr(d, "in_missing", []))
    invs = [] if in_missing else [dict(v) for v in d.invoices]
    R = {"kind": kind, "asof": asof}
    # 주간 출금 목록의 출금일 (사용자 2026-11-04: 날짜를 따로 넣으면 그 날 기준). 비우면 기준일 뒤 첫 금요일
    R["payday"] = payday if payday is not None and payday > asof else pay_friday(asof)
    p0, p1 = period_of(kind, asof, start)
    R["period"] = (p0, p1)
    R["settings"] = dict(d.settings)
    # 설정 숫자는 여기서 한 번만 읽는다. 비었거나 틀리면 기본값을 쓰고 입력 확인 목록에 남긴다.
    R["settings_num"], R["settings_default"] = {}, {}
    for key in NUM_SETTINGS:
        default = setting_num(DEFAULT_SETTINGS, key, None)[0]
        if key not in d.settings_line:
            value, reason = default, "설정 비어 있음"
        else:
            value, reason = setting_num(d.settings, key, default)
        if key == "첫화면_프로젝트_표시수" and reason is None and (not isinstance(value, int) or value < 0):
            value, reason = default, "0 이상 정수 아님"
        if key == "예산_원가율" and reason != "설정 비어 있음":
            # 원가율은 틀린 값을 기본값으로 바꾸지 않는다: 오류로 알리고 어느 프로젝트도 원가 예산을 계산하지 않는다 (D-16)
            raw = d.settings.get(key)
            if reason is None and "%" in str(raw):
                value = value / 100.0
            if reason is not None or not (0 < value <= 1):
                R["settings_num"][key] = None
                issues.add("설정.csv", d.settings_line.get(key, "-"),
                             "예산_원가율 값 오류: '%s' (0 초과 1 이하 숫자, 예: 0.70) → 모든 프로젝트 원가 예산 계산 안 함" % raw)
                continue
            R["settings_num"][key] = value
            continue
        if reason is not None:
            label, raw = SETTING_LABELS[key], d.settings.get(key)
            tail = "→ 기본값 %s 사용" % _fmt_setting(default)
            if key == "예산_원가율":
                msg = "예산_원가율 설정 비어 있음 → 기본값 사용(0.70)"
            elif reason == "설정 비어 있음":
                msg = "%s 설정 비어 있음 %s" % (label, tail)
            elif reason == "숫자 아님":
                msg = "%s 값이 숫자가 아님: '%s' %s" % (label, raw, tail)
            else:
                msg = "%s 값은 0 이상 정수여야 함: '%s' %s" % (label, raw, tail)
            R["settings_default"][key] = reason
            issues.add("설정.csv", d.settings_line.get(key, "-"), msg)
        R["settings_num"][key] = value
    R["present"] = d.present
    checks = []  # 대조표: (항목, 값A, 값B, 일치여부)

    # ───────────── 1. 현재 자금과 기간 입출금 ─────────────
    latest = OrderedDict()
    for b in sorted(d.balances, key=lambda x: x["date"]):
        if b["date"] <= p1:
            latest[b["account"]] = b
    accounts = list(latest.values())
    # 은행 잔액 기준일 뒤 입출금내역을 더하고 빼서 입출금내역이 있는 마지막 날의 잔액으로 본다 (사용자 2026-11-04).
    # 입출금내역 마지막 날 = 그 파일이 채워진 날로 보고, 그날을 그 계좌의 잔액 기준일로 바꾼다 (원래 은행 날짜는 bank_date).
    cover = max((t["date"] for t in d.txns if t["date"] <= p1), default=None)
    rolled = []
    for i, a in enumerate(accounts):
        if a["balance"] is None or cover is None or a["date"] >= cover:
            continue
        mv = [t for t in d.txns if t["account"] == a["account"] and a["date"] < t["date"] <= cover]
        adj = sum(t["amount"] if t["io"] == "입금" else -t["amount"] for t in mv)
        accounts[i] = dict(a, balance=a["balance"] + adj, date=cover, bank_date=a["date"], bank_balance=a["balance"],
                           roll=adj, roll_n=len(mv))
        rolled.append(accounts[i])
    total_bal, bal_unknown = ssum(a["balance"] for a in accounts)
    # 제한해제일이 기준일 이전이면 이미 풀린 돈: 빼지 않는다 (사용자 2026-11-03)
    released = [a for a in accounts if a.get("release") and a["release"] <= asof and a["restricted"]]
    for a in released:
        issues.add(a["row"]["_file"], a["row"]["_line"], "제한해제일 %s 지남 (%s) → 사용제한 %s 빼지 않음. 계좌잔액.csv 정리 필요"
                   % (a["release"], a["account"], won(a["restricted"])))
    restricted, restr_unknown = ssum(0 if a in released else a["restricted"] for a in accounts)
    if not accounts or bal_unknown == len(accounts):
        # 알려진 잔액이 하나도 없으면 현재 현금은 0이 아니라 미확인 (D-02). 시작 잔액이 없으므로 일정·최저 잔액도 계산하지 않는다.
        total_bal = None
    if not accounts:
        restricted = None
    stale_accounts = [a for a in accounts if a["date"] < p1]
    in_p = [t for t in d.txns if p0 <= t["date"] <= p1]
    ext = [t for t in in_p if t["cat"] != TRANSFER]
    tin = sum(t["amount"] for t in ext if t["io"] == "입금")
    tout = sum(t["amount"] for t in ext if t["io"] == "출금")
    tr_in = sum(t["amount"] for t in in_p if t["cat"] == TRANSFER and t["io"] == "입금")
    tr_out = sum(t["amount"] for t in in_p if t["cat"] == TRANSFER and t["io"] == "출금")
    by_cat = defaultdict(lambda: [0, 0])
    for t in ext:
        by_cat[t["cat"]][0 if t["io"] == "입금" else 1] += t["amount"]
    acct_flow = defaultdict(lambda: [0, 0])
    for t in in_p:
        acct_flow[t["account"]][0 if t["io"] == "입금" else 1] += t["amount"]
    # 잔액이 빈칸인 계좌: 합계에서 빼고(0으로 두지 않음), 그 사실을 보고서 곳곳에 보인다. 사용제한금액은 그대로 차감.
    unknown_bal = [a for a in accounts if a["balance"] is None]
    unknown_names = [a["account"] for a in unknown_bal]
    bal_unknown_restricted, _ = ssum(a["restricted"] for a in unknown_bal)
    for a in unknown_bal:
        issues.add(a["row"]["_file"], a["row"]["_line"],
                     "잔액 미확인 (" + a["account"] + ") → 현재 현금·사용 가능액 합계에서 제외")
    # 기간 시작 잔액: 은행 잔액이 있으면 그것, 없으면 기말 잔액에서 거꾸로 계산 (잔액 확인된 계좌만)
    start_snap = OrderedDict()
    for b in sorted(d.balances, key=lambda x: x["date"]):
        if b["date"] == p0 - DAY:
            start_snap[b["account"]] = b
    start_calc = None
    if total_bal is not None:
        start_calc = total_bal - tin + tout - tr_in + tr_out
        for a in unknown_bal:
            fin, fout = acct_flow.get(a["account"], [0, 0])
            start_calc += fin - fout
    start_bank = None
    if total_bal is not None and start_snap and set(start_snap) == set(latest):
        start_bank, start_bank_unknown = ssum(b["balance"] for n, b in start_snap.items() if n not in unknown_names)
        if start_bank_unknown:
            start_bank = None
    R["s1"] = {
        "accounts": accounts, "total": total_bal, "bal_unknown": bal_unknown, "restricted": restricted,
        "restr_unknown": restr_unknown, "available": None if total_bal is None else total_bal - restricted,
        "stale": stale_accounts, "rolled": rolled, "txn_cover": cover,
        "bal_unknown_names": unknown_names, "bal_unknown_restricted": bal_unknown_restricted,
        "in": tin, "out": tout, "start_calc": start_calc, "start_bank": start_bank,
        "end": total_bal, "by_cat": dict(by_cat), "transfer_in": tr_in, "transfer_out": tr_out,
        "acct_flow": dict(acct_flow), "txns": sorted(in_p, key=lambda t: t["date"]),
    }
    checks.append(("이번 기간 회사 계좌 간 이체 (입금 = 출금)", tr_in, tr_out, tr_in == tr_out))
    checks.append(("분류별 입금 합 = 입금 합계", sum(v[0] for v in by_cat.values()), tin,
                   sum(v[0] for v in by_cat.values()) == tin))
    checks.append(("분류별 출금 합 = 출금 합계", sum(v[1] for v in by_cat.values()), tout,
                   sum(v[1] for v in by_cat.values()) == tout))
    if start_bank is not None and start_calc is not None:
        label = "기간 시작 잔액 (은행 잔액 = 거래로 계산한 값)"
        if bal_unknown:
            label += " · 잔액 미확인 %d계좌 제외" % bal_unknown
        checks.append((label, start_bank, start_calc, start_bank == start_calc))

    # ───────────── 3. 프로젝트별 예산·지급 ─────────────
    proj = OrderedDict()
    for pid in d.project_order:
        proj[pid] = _blank_proj(d.projects[pid], R["settings_num"]["예산_원가율"])
    unlinked_exec = []
    prior_exec = []
    for e in d.execs:
        if from_intranet(e) and not INTRANET_IN_FUNDS:
            continue   # 쓴 돈(예상총집행)에 넣지 않는다 — 아래 일정에서도 빼고 intranet_only 로 센다
        if is_prior(e):
            prior_exec.append(e)   # 지난해 프로젝트: 참고로만 (미연결로 세지 않음)
            continue
        if e["project"] not in proj:
            unlinked_exec.append(e)
            continue
        P = proj[e["project"]]
        P["lines"].append(e)
        P["line_n"][e["state"]] += 1
        amt = e["supply"]
        if amt is None:
            P["unknown_cost"] += 1
            P["line_unknown"][e["state"]] += 1
            if e["state"] == "지급완료":
                P["paid_cash"] = None  # 공급가액을 모르면 실제 출금액도 알 수 없다
                P["paid_cash_reason"] = "금액 미확인"  # 부가세 빈칸보다 먼저 보인다
            continue
        st = e["state"]
        if st == "지급완료":
            P["paid"] += amt
            P["paid_cash"] = _add(P["paid_cash"], amt + (e["vat"] or 0)) if e["vat"] is not None else None
            if e["vat"] is None:
                P["vat_unknown"] += 1
                P["paid_cash_reason"] = P["paid_cash_reason"] or "부가세 미확인"
            if e["date"] and p0 <= e["date"] <= p1:
                P["paid_period"] += amt
        elif st == "카드결제완료":
            P["card_paid"] += amt
            if e["date"] and p0 <= e["date"] <= p1:
                P["paid_period"] += amt
        elif st == "요청미지급":
            P["requested"] += amt
        elif st == "카드사용미결제":
            P["card_unpaid"] += amt
        elif st == "집행계획미요청":
            P["planned"] += amt
    for P in proj.values():
        P["paid_total"] = P["paid"] + P["card_paid"]
        P["expected"] = P["paid_total"] + P["requested"] + P["card_unpaid"] + P["planned"]
        b = P["budget"]
        # 금액 미확인 원가 줄이 있으면 예상총집행이 모자라므로 잔여예산을 정확한 숫자로 보이지 않는다 (D-02)
        P["remain"] = None if (b is None or P["unknown_cost"]) else b - P["expected"]
        P["profit_end"] = None if (P["contract"] is None or P["unknown_cost"]) else P["contract"] - P["expected"]
        P["unrecognized"] = None if (P["contract"] is None or P["recognized"] is None) else P["contract"] - P["recognized"]
    plist = [P for P in proj.values() if (P.get("state") or "").strip() != OLD_STATE]   # 예전 인트라넷 끝난 행사 (사용자 2026-11-05)
    tot = {k: sum(P[k] for P in plist) for k in
           ["paid_period", "paid_total", "paid", "card_paid", "requested", "card_unpaid", "planned", "expected"]}
    tot["budget"], tot["budget_missing"] = ssum(P["budget"] for P in plist)
    tot["estimate"], tot["estimate_missing"] = ssum_or_none(P["estimate"] for P in plist)  # 전부 미등록이면 0이 아니라 None
    remain_known = [P["remain"] for P in plist if P["remain"] is not None]
    tot["remain"] = sum(remain_known)
    tot["remain_excluded"] = sum(1 for P in plist if P["budget"] is not None and P["remain"] is None)
    if (plist and tot["budget_missing"] == len(plist)) or not remain_known:
        tot["remain"] = None  # 계산할 수 있는 프로젝트가 하나도 없으면 합계는 0이 아니라 판단 불가 (D-02)
    if plist and tot["budget_missing"] == len(plist):
        tot["budget"] = None  # 원가 예산이 하나도 없으면 합계는 0이 아니라 판단 불가 (D-02)
    tot["line_n"] = {st: sum(P["line_n"][st] for P in plist) for st in EXEC_STATES}
    tot["line_unknown"] = {st: sum(P["line_unknown"][st] for P in plist) for st in EXEC_STATES}
    # 지급완료 줄이 있는 프로젝트만 대상: 부가세·공급가액을 모르는 프로젝트가 전부면 0이 아니라 미확인 (D-02)
    tot["paid_cash"], tot["paid_cash_unknown"] = ssum_or_none(
        P["paid_cash"] for P in plist if P["line_n"]["지급완료"] > 0)
    # 실출금 미확인 이유: 공급가액 빈칸('금액 미확인')과 부가세 빈칸('부가세 미확인')을 섞어 쓰지 않는다
    reasons = set(P["paid_cash_reason"] for P in plist if P["paid_cash"] is None and P["line_n"]["지급완료"] > 0)
    tot["paid_cash_reason"] = ("금액·부가세 미확인" if len(reasons) > 1 else
                               (reasons.pop() if reasons else "부가세 미확인"))
    tot["unknown_cost"] = sum(P["unknown_cost"] for P in plist)
    budgeted = [P for P in plist if P["budget"] is not None]
    tot["expected_budgeted"] = sum(P["expected"] for P in budgeted)
    tot["paid_budgeted"] = sum(P["paid_total"] for P in budgeted)
    n_show = R["settings_num"]["첫화면_프로젝트_표시수"]
    ranked = sorted(plist, key=lambda P: (-(P["budget"] if P["budget"] is not None else -1), -P["expected"]))
    shown = ranked[:n_show]
    rest = ranked[n_show:]
    ue_tot, ue_unknown = ssum(e["supply"] for e in unlinked_exec)
    reason_n = OrderedDict()
    for reason in BUDGET_REASONS:
        n = sum(1 for P in plist if P["budget_reason"] == reason)
        if n:
            reason_n[reason] = n
    # D-54: 남은 예산 → 지급 예정 (완료 프로젝트 제외). 금액 미확인 원가가 있어 남은 예산을 모르면 0으로 넣지 않고 목록으로
    for P in plist:
        P["remain_due"], P["remain_cash"] = None, None
        if (P.get("state") or "").strip() in DONE_STATES or P["budget"] is None:
            continue
        if P["remain"] is not None and P["remain"] > 0:
            P["remain_cash"] = int(round(P["remain"] * (1 + BUDGET_VAT)))
            P["remain_due"] = budget_due(_event_date(P.get("event_date")), asof)
    remain_unknown = [P for P in plist if P["budget"] is not None and P["remain"] is None
                      and (P.get("state") or "").strip() not in DONE_STATES]
    by_team = OrderedDict()
    for P in sorted(plist, key=lambda P: P["team"]):
        t = by_team.setdefault(P["team"], {"team": P["team"], "n": 0, "budget": 0, "no_budget": 0, "expected": 0,
                                           "remain": 0, "remain_unknown": 0, "planned_pay": 0})
        t["n"] += 1
        t["expected"] += P["expected"]
        if P["budget"] is None:
            t["no_budget"] += 1
            continue
        t["budget"] += P["budget"]
        if P["remain"] is None:
            t["remain_unknown"] += 1
        else:
            t["remain"] += P["remain"]
        t["planned_pay"] += P["remain_cash"] or 0
    for t in by_team.values():
        if t["n"] == t["no_budget"]:
            t["budget"] = t["remain"] = None   # 예산 지정 프로젝트가 없으면 0이 아니라 판단 불가 (D-02)
        elif t["remain_unknown"] == t["n"] - t["no_budget"]:
            t["remain"] = None
    R["s3"] = {"projects": plist, "ranked": ranked, "shown": shown, "rest": rest, "total": tot,
               "remain_unknown": remain_unknown, "by_team": list(by_team.values()),
               "unlinked": unlinked_exec, "unlinked_total": ue_tot,
               "prior": prior_exec, "prior_total": ssum(e["supply"] for e in prior_exec)[0],
               "cost_rate": R["settings_num"]["예산_원가율"], "no_budget_reasons": reason_n}
    linked_lines = sum(len(P["lines"]) for P in plist)
    compare_only = 0 if INTRANET_IN_FUNDS else sum(1 for e in d.execs if from_intranet(e))
    counted = linked_lines + len(unlinked_exec) + compare_only + len(prior_exec)
    checks.append(("프로젝트집행 줄 수 = 프로젝트 반영 줄 + 미연결 줄" + (" + 인트라넷 비교만 줄" if compare_only else "")
                   + (" + 지난해 참고 줄" if prior_exec else ""),
                   len(d.execs), counted, len(d.execs) == counted))
    shown_exp = sum(P["expected"] for P in shown) + sum(P["expected"] for P in rest)
    checks.append(("첫 화면 표시 + 나머지 프로젝트 예상총집행 = 전체 합계", shown_exp, tot["expected"],
                   shown_exp == tot["expected"]))

    # ───────────── 5. 계산서·수금 ─────────────
    inv_by = defaultdict(list)
    for v in invs:
        inv_by[v["project"]].append(v)
    ar_rows, overdue, specials = [], [], []
    for v in invs:
        total = None if v["supply"] is None or v["vat"] is None else v["supply"] + v["vat"]
        v["total"] = total
        if total is None or (v["paid"] is None and v["paid_date"]):
            v["outstanding"] = None  # 입금일은 있는데 입금액이 빈칸이면 미수액을 알 수 없다 (전액 미수로 단정하지 않음)
        else:
            v["outstanding"] = total - (v["paid"] or 0)
    _net_credits(invs)
    for v in invs:
        if v["kind"] in ("선수금", "취소", "환불", "수정"):
            specials.append(v)
        if v["outstanding"] and v["outstanding"] > 0 and v["kind"] != "환불":
            ar_rows.append(v)
            if v["due"] and v["due"] < asof:
                v["overdue_days"] = (asof - v["due"]).days
                overdue.append(v)
    inv_proj = []
    for P in plist:
        rows = inv_by.get(P["id"], [])
        rows_i = [v for v in rows if v["kind"] != "환불"]
        issued, issued_unknown = ssum(v["supply"] for v in rows_i)
        if rows_i and issued_unknown == len(rows_i):
            issued = None  # 발행 줄이 모두 금액 미확인이면 0이 아니라 미확인
        # 미수: 금액을 알 수 없는 줄(None)도 버리지 않고 건수로 센다
        rows_a = [v for v in rows_i if v["outstanding"] is None or v["outstanding"] > 0]
        out, out_unknown = ssum(v["outstanding"] for v in rows_a)
        if rows_a and out_unknown == len(rows_a):
            out = None
        # 발행금액 일부가 미확인이면 미발행금액을 부풀리지 않고 판단 불가로 둔다
        unissued = None if (P["contract"] is None or issued_unknown > 0) else P["contract"] - issued
        if in_missing:
            issued = out = unissued = None  # 계산서 자료 없음: 미확인 건수가 아니라 자료 자체가 없다
        days = None
        if unissued and unissued > 0 and P["done_date"]:
            days = (asof - P["done_date"]).days
        inv_proj.append({"P": P, "issued": issued, "issued_unknown": issued_unknown, "unissued": unissued,
                         "ar": out, "ar_unknown": out_unknown, "unissued_days": days,
                         "unknown": issued_unknown + out_unknown})
    no_proj_inv = [v for v in invs if v["project"] not in proj]
    c_tot, c_missing = ssum_or_none(P["contract"] for P in plist)
    unissued_tot, _ = ssum_or_none(x["unissued"] for x in inv_proj)
    issued_tot, _ = ssum_or_none(x["issued"] for x in inv_proj)
    ar_unknown_n = sum(1 for v in invs if v["kind"] != "환불" and v["outstanding"] is None)
    ar_tot = sum(v["outstanding"] for v in ar_rows)
    if not ar_rows and ar_unknown_n:
        ar_tot = None  # 미수 줄이 금액 미확인뿐이면 0이 아니라 미확인
    overdue_tot = sum(v["outstanding"] for v in overdue)
    if in_missing:
        issued_tot = unissued_tot = ar_tot = overdue_tot = None  # 계산서 자료 없음 (0 아님)
    R["s5"] = {
        "in_missing": in_missing,
        "by_project": inv_proj, "ar_rows": ar_rows, "overdue": sorted(overdue, key=lambda v: -v["overdue_days"]),
        "specials": specials, "no_project": no_proj_inv,
        "contract": c_tot, "contract_missing": c_missing,
        "issued": issued_tot,
        "issued_unknown_n": sum(x["issued_unknown"] for x in inv_proj),
        "unissued_unknown_n": sum(1 for x in inv_proj if x["unissued"] is None),
        "ar_unknown_n": ar_unknown_n,
        "unissued": unissued_tot,
        "ar": ar_tot,
        "overdue_total": overdue_tot,
        "unissued_aged": [x for x in inv_proj if x["unissued_days"] is not None],
        "event_unissued": event_unissued(inv_proj, asof, in_missing),
        "expected": expected_revenue(inv_proj, asof, in_missing),
    }

    # ───────────── 2. 앞으로의 입금·지급 일정 ─────────────
    events = []
    for s in d.schedule:
        events.append({"date": s["date"], "io": "in" if s["io"] == "입금" else "out", "amount": s["amount"],
                       "firm": s["firm"], "cat": s["cat"], "desc": s["vendor"] or s["memo"], "basis": s["basis"],
                       "project": s["project"], "source": "자금일정"})
    for v in ar_rows:
        events.append({"date": v["due"], "io": "in", "amount": v["outstanding"], "firm": v["due_firm"],
                       "cat": "수금(발행 계산서)", "desc": v["client"], "basis": "계산서 %s" % (v["date"] or ""),
                       "project": v["project"], "source": "계산서"})
    for v in invs:
        if v["kind"] == "환불" and v["outstanding"] is not None and v["outstanding"] < 0 and not v["paid_date"]:
            events.append({"date": v["due"], "io": "out", "amount": -v["outstanding"], "firm": v["due_firm"],
                           "cat": "환불", "desc": v["client"], "basis": "계산서 환불", "project": v["project"],
                           "source": "계산서"})
    # 사용자 결정 (2026-11-04 카드 '비교만'): 인트라넷에서 온 지급요청·집행계획과 남은 예산은 가용자금 일정에 더하지 않는다.
    # 돈의 기준은 위하고 분개장·자금계획서. 빼는 줄은 R["intranet_only"] 에 건수·합계로 남겨 비교로만 보인다.
    skipped_requests, skipped_budget = [], []
    for e in d.execs:
        if is_prior(e):
            continue   # 지난해 프로젝트는 입금·지급 모두 끝남 (사용자 2026-11-04) — 일정에 넣지 않는다
        # 요청미지급 줄(인트라넷 요청, 또는 장부 원가에 요청을 붙인 줄)의 지급은 위하고 자금계획서·장부채무가 잡는다
        # (실제 자료 2026-11-04: 같은 미지급이 자금계획서와 겹쳐 11월 출금이 0.8억 커짐). 예상총집행에는 위에서 그대로 들어간다.
        if e["state"] == "요청미지급" and not INTRANET_IN_FUNDS:
            skipped_requests.append(None if e["supply"] is None else e["supply"] + (e["vat"] or 0))
            continue
        if e["state"] in ("요청미지급", "집행계획미요청"):
            amt = None if e["supply"] is None else e["supply"] + (e["vat"] or 0)
            events.append({"date": e["date"], "io": "out", "amount": amt,
                           "firm": e["firm"] and e["state"] == "요청미지급",
                           "cat": "프로젝트 " + ("지급요청" if e["state"] == "요청미지급" else "집행계획"),
                           "desc": e["vendor"] or e["item"], "basis": e["basis"], "project": e["project"],
                           "source": "프로젝트집행", "vat_unknown": e["vat"] is None})
    for a in R["s1"]["accounts"]:   # 사용제한 해제 (정기예금 만기 등): 그날 쓸 수 있는 돈이 된다 (사용자 2026-11-03)
        if a.get("release") and a["release"] > asof and a["restricted"]:
            events.append({"date": a["release"], "io": "in", "amount": a["restricted"], "firm": True,
                           "cat": "사용제한 해제", "desc": a["account"] + (" · " + a["reason"] if a["reason"] else ""),
                           "basis": "계좌잔액.csv 제한해제일", "project": "", "source": "계좌잔액"})
    for P in R["s3"]["projects"]:
        if P["remain_cash"] and not (INTRANET_IN_FUNDS or BUDGET_IN_FUNDS):
            skipped_budget.append(P["remain_cash"])
            continue
        if P["remain_cash"]:
            # 매주 금요일로 나눠 잡는다 (사용자 2026-11-03): 다음 지급 금요일부터 행사일 다음 달 말 금요일까지 같은 금액.
            # 진행 중 계속 쓰는 예산이 한 날짜에 몰려 그 전 기간 가용자금이 커 보이지 않게. 행사일을 모르면 날짜 없는 한 줄.
            days = [P["remain_due"]]
            if P["remain_due"] is not None:
                days, f = [], pay_friday(asof)
                while f <= P["remain_due"]:
                    days.append(f)
                    f += 7 * DAY
                days = days or [P["remain_due"]]
            n = len(days)
            each = P["remain_cash"] // n
            for k, day in enumerate(days):
                amt = each if k < n - 1 else P["remain_cash"] - each * (n - 1)
                events.append({"date": day, "io": "out", "amount": amt, "firm": False,
                               "cat": "프로젝트 남은 예산", "desc": P["name"],
                               "basis": "남은 예산 %s원 + 부가세 10%%%s" % (won(P["remain"]), (
                                   ", %s~%s 매주 금요일 나눔 (%d/%d)" % (d2s(days[0]), d2s(days[-1]), k + 1, n) if n > 1
                                   else ", 행사일 다음 달 말 금요일" if day else "")),
                               "project": P["id"], "source": "남은 예산", "split": (k + 1, n)})
    R["intranet_only"] = {"requests": (len(skipped_requests), sum(x for x in skipped_requests if x)),
                          "budget": (len(skipped_budget), sum(skipped_budget))}
    known = [a["date"] for a in R["s1"]["accounts"] if a["balance"] is not None]
    events, R["fundplan"] = fundplan.apply(events, getattr(d, "fundplan", None), asof,
                                           int(R["settings_num"].get("위험_자료경과일") or 7), getattr(d, "fundplan_problem", ""),
                                           cash_date=min(known) if known else None, txns=d.txns)
    fundplan.fill_projects(events, getattr(d, "execs", None))
    # 세금 납부 예상 (사용자 2026-11-03): 자금계획서·자금일정에 이미 있으면 넣지 않고 비교만
    from .tax import merge as merge_tax
    events, R["tax"] = merge_tax(events, getattr(d, "tax", None))
    from .paydetail import attach   # 금요일 출금 목록 상세 내역 (사용자 2026-11-03)
    attach(events, getattr(d, "pay_details", None) or [])
    R["events"] = events
    from .debts import compare as compare_debts   # 장부 미지급금·차입금 대 일정 (2026-11-04 점검 A1·A2)
    R["debts"] = compare_debts(getattr(d, "debts", None), events, asof)
    R["two_source"] = two_sources(events, asof)

    week_ends = [R["payday"] + 7 * i * DAY for i in range(4)]   # 출금일 단위 한 주 (기본 금요일, 토~금)
    buckets = []
    s = asof + DAY
    for i, we in enumerate(week_ends):
        buckets.append({"label": "%d주차" % (i + 1), "from": s, "to": we, "type": "week"})
        s = we + DAY
    horizon = _month_end(_add_months(asof, 6))
    cut3 = _month_end(_add_months(asof, 3))
    while s <= horizon:
        e_ = min(_month_end(s), horizon)
        buckets.append({"label": "%d년 %d월" % (s.year, s.month) + (" (일부)" if s.day != 1 else ""),
                        "from": s, "to": e_, "type": "month", "within3": e_ <= cut3})
        s = e_ + DAY
    for b in buckets:
        for k in ("in_firm", "in_est", "out_firm", "out_est"):
            b[k] = 0
    undated, past, beyond, amount_unknown = [], [], [], []
    for ev in events:
        if ev["amount"] is None:
            amount_unknown.append(ev)
            continue
        if ev["date"] is None:
            undated.append(ev)
            continue
        if ev["date"] <= asof:
            past.append(ev)
            continue
        if ev["date"] > horizon:
            beyond.append(ev)
            continue
        for b in buckets:
            if b["from"] <= ev["date"] <= b["to"]:
                b[("in_" if ev["io"] == "in" else "out_") + ("firm" if ev["firm"] else "est")] += ev["amount"]
                break
    start_cash = R["s1"]["available"]
    out_missing = list(getattr(d, "out_missing", []))
    if out_missing:
        start_cash = None  # 지급 자료가 빠졌으면 계산 잔액·최저 잔액을 만들지 않는다 (지급 0원으로 보지 않음)
    bal_f = bal_a = start_cash
    for b in buckets:
        if start_cash is None:
            b["bal_firm"] = b["bal_all"] = None  # 시작 잔액을 모르면 0에서 시작해 계산하지 않는다
            continue
        bal_f += b["in_firm"] - b["out_firm"]
        bal_a += b["in_firm"] + b["in_est"] - b["out_firm"] - b["out_est"]
        b["bal_firm"], b["bal_all"] = bal_f, bal_a
    # 날짜 단위 최저 잔액
    dated = sorted([ev for ev in events if ev["amount"] is not None and ev["date"] and asof < ev["date"] <= horizon],
                   key=lambda x: x["date"])
    mins = {}
    for mode in ("firm", "all"):
        if start_cash is None:
            mins[mode] = (None, None)
            continue
        bal, low, low_d = start_cash, start_cash, asof
        daily = defaultdict(int)
        for ev in dated:
            if mode == "firm" and not ev["firm"]:
                continue
            daily[ev["date"]] += ev["amount"] if ev["io"] == "in" else -ev["amount"]
        for day in sorted(daily):
            bal += daily[day]
            if bal < low:
                low, low_d = bal, day
        mins[mode] = (low, low_d)
    four = buckets[:4]
    min_cash = R["settings_num"].get("위험_최소보유현금")
    ends = period_ends(R["kind"], asof, R["payday"])
    if pick is not None:   # 보고서를 만들 때 정한 날짜 (--가용일): 문서라 읽는 사람이 날짜를 바꿀 수 없다 (사용자 2026-11-03)
        ends.append(("지정일", pick))
    periods = available_periods(start_cash, dated, ends, min_cash, asof)
    if pick is not None:
        periods[-1]["pick"] = True
    # 예정일이 지난 미처리: 확인된 금액만 합산하고, 건수는 금액 미확인 건도 센다. 일정·최저 잔액에는 넣지 않는다.
    past_all = past + [ev for ev in amount_unknown if ev["date"] is not None and ev["date"] <= asof]
    past_sum = {}
    for io in ("in", "out"):
        evs = [ev for ev in past_all if ev["io"] == io]
        total, unknown = ssum(ev["amount"] for ev in evs)
        past_sum[io] = (None if evs and unknown == len(evs) else total, len(evs), unknown)
    # 날짜 없는 예정금액: 첫 화면에도 건수와 확인된 금액을 보인다 (D-04). 금액 미확인 건도 건수에는 센다.
    undated_all = undated + [ev for ev in amount_unknown if ev["date"] is None]
    undated_sum = {}
    for io in ("in", "out"):
        evs = [ev for ev in undated_all if ev["io"] == io]
        total, unknown = ssum(ev["amount"] for ev in evs)
        undated_sum[io] = (None if evs and unknown == len(evs) else total, len(evs), unknown)
    # 부가세가 비어 있는 예정 지급은 공급가액만 반영된다. 일정에 들어간 건수를 센다.
    sched_vat = [ev for ev in dated if ev.get("vat_unknown")]
    # 날짜는 기간 안인데 금액을 모르는 지급예정: 합계·최저 잔액에 넣지 못하므로 건수를 함께 보인다 (D-02)
    out_unk = [ev for ev in amount_unknown if ev["io"] == "out" and ev["date"] is not None and asof < ev["date"] <= horizon]
    R["s2"] = {
        "start": R["s1"]["available"], "out_missing": out_missing, "in_missing": in_missing, "start_unknown": R["s1"]["bal_unknown"], "buckets": buckets, "undated": undated, "past": past, "beyond": beyond,
        "amount_unknown": amount_unknown, "min": mins, "horizon": horizon, "pick_beyond": pick is not None and pick > horizon,
        "periods": periods, "min_cash": min_cash, "dated": dated,
        "in4_firm": sum(b["in_firm"] for b in four), "in4_est": sum(b["in_est"] for b in four),
        "out4_firm": sum(b["out_firm"] for b in four), "out4_est": sum(b["out_est"] for b in four),
        "undated_in": undated_sum["in"][0], "undated_in_n": undated_sum["in"][1], "undated_in_unknown": undated_sum["in"][2],
        "undated_out": undated_sum["out"][0], "undated_out_n": undated_sum["out"][1],
        "undated_out_unknown": undated_sum["out"][2],
        "past_in": past_sum["in"][0], "past_in_n": past_sum["in"][1], "past_in_unknown": past_sum["in"][2],
        "past_out": past_sum["out"][0], "past_out_n": past_sum["out"][1], "past_out_unknown": past_sum["out"][2],
        "vat_unknown_n": len(sched_vat),
        "vat_unknown_n4": sum(1 for ev in sched_vat if ev["date"] <= four[-1]["to"]),
        "vat_unknown_firm_n": sum(1 for ev in sched_vat if ev["firm"]),
        "out_unknown_n": len(out_unk), "out_unknown_firm_n": sum(1 for ev in out_unk if ev["firm"]),
        "out_unknown_n4": sum(1 for ev in out_unk if ev["date"] <= four[-1]["to"]),
    }
    all_amt = sum(e["amount"] for e in events if e["amount"] is not None)
    parts = (sum(b[k] for b in buckets for k in ("in_firm", "in_est", "out_firm", "out_est"))
             + sum(e["amount"] for e in undated + past + beyond))
    checks.append(("예정 일정 합계 = 기간별 + 날짜 없음 + 지난 날짜 + 기간 밖", parts, all_amt, parts == all_amt))

    # ───────────── 4. 매출·손익 ─────────────
    ym = asof.strftime("%Y-%m")
    year = asof.strftime("%Y")
    pl_out = OrderedDict()
    for src in sorted(set(p["source"] for p in d.pl), key=lambda x: (x != "WEHAGO", x)):
        rows = [p for p in d.pl if p["source"] == src]
        months = sorted(set(p["ym"] for p in rows))
        units = OrderedDict()
        for p in rows:
            units.setdefault((p["unit"], p["target"]), []).append(p)
        table = []
        for (unit, target), ps in units.items():
            cur = [p for p in ps if p["ym"] == ym]
            ytd = [p for p in ps if p["ym"][:4] == year and p["ym"] <= ym]
            table.append({"unit": unit, "target": target, "cur": _pl_sum(cur), "ytd": _pl_sum(ytd)})
        # 올해 달마다의 표 (팀 순수익의 '비용 나눈 뒤' 누적: 달마다 인원이 달라 달마다 나눠 더함, 사용자 2026-11-03)
        by_month = [(m, [{"unit": unit, "target": target, "cur": _pl_sum([p for p in ps if p["ym"] == m]), "ytd": None}
                         for (unit, target), ps in units.items()])
                    for m in months if m[:4] == year and m <= ym]
        pl_out[src] = {"table": table, "latest": months[-1] if months else None, "has_cur": ym in months, "by_month": by_month}
    R["s4"] = {"ym": ym, "sources": pl_out, "projects": plist,
               "unrecognized": ssum_or_none(P["unrecognized"] for P in plist)[0],
               "unrecognized_missing": sum(1 for P in plist if P["unrecognized"] is None),
               # 부서별 급여·판관비 (선택 파일 부서비용.csv, 사용자 2026-11-03). None = 파일 없음, 팀 순수익은 미확인
               "dept": getattr(d, "dept", None), "dept_problem": getattr(d, "dept_problem", ""),
               "staff": getattr(d, "staff", None)}   # 사원별 급여 (사원급여.csv, 사용자 2026-11-04)

    # ───────────── 6. 프로젝트 밖 지급과 지급의무 ─────────────
    nonproj = [s for s in d.schedule if s["io"] == "지급"]
    by_cat6 = OrderedDict()
    for s in sorted(nonproj, key=lambda x: (x["cat"], x["date"] or dt.date.max)):
        g = by_cat6.setdefault(s["cat"], {"rows": [], "total": 0, "unknown": 0, "undated": 0})
        g["rows"].append(s)
        if s["amount"] is None:
            g["unknown"] += 1
        else:
            g["total"] += s["amount"]
        if s["date"] is None:
            g["undated"] += 1
    for g in by_cat6.values():
        if g["unknown"] == len(g["rows"]):
            g["total"] = None  # 분류 안의 모든 줄이 금액 미확인이면 합계는 0이 아니라 미확인
    vendors = OrderedDict()

    def _vendor(name):
        return vendors.setdefault(name, {"total": 0, "next": None, "n": 0, "unknown": 0, "vat_unknown": 0})

    for s in nonproj:
        if not s["vendor"]:
            continue
        v = _vendor(s["vendor"])
        if s["amount"] is None:
            v["unknown"] += 1
        else:
            v["total"] += s["amount"]
        v["n"] += 1
        if s["date"] and (v["next"] is None or s["date"] < v["next"]):
            v["next"] = s["date"]
    for e in d.execs:
        if e["state"] == "요청미지급" and e["vendor"] and not is_prior(e):   # 지난해 건은 지급 끝남 (사용자 2026-11-04)
            v = _vendor(e["vendor"])
            if e["supply"] is None:
                v["unknown"] += 1
            else:
                v["total"] += e["supply"]
                if e["vat"] is None:
                    v["vat_unknown"] += 1
                else:
                    v["total"] += e["vat"]
            v["n"] += 1
            if e["date"] and (v["next"] is None or e["date"] < v["next"]):
                v["next"] = e["date"]
    for v in vendors.values():
        if v["unknown"] == v["n"]:
            v["total"] = None  # 모든 줄이 금액 미확인이면 합계는 0이 아니라 미확인
    dup = [s for s in d.schedule if "프로젝트" in s["cat"]]
    for s in dup:
        issues.add(s["row"]["_file"], s["row"]["_line"],
                     "자금일정에 프로젝트 지급(%s)이 있음 — 프로젝트집행.csv와 중복일 수 있음" % s["cat"])
    R["s6"] = {"by_cat": by_cat6,
               "vendors": sorted(vendors.items(), key=lambda kv: (kv[1]["total"] is None, -(kv[1]["total"] or 0))),
               "total": ssum_or_none(g["total"] for g in by_cat6.values())[0],
               "undated_n": sum(g["undated"] for g in by_cat6.values()),
               "unknown_n": sum(g["unknown"] for g in by_cat6.values())}

    # ───────────── 7. 변동과 자료 반영 범위 ─────────────
    changes = [c for c in d.changes if c["date"] and p0 <= c["date"] <= p1]
    undated_changes = [c for c in d.changes if not c["date"]]
    # 지급계획 대비 실제
    plan_rows = [p for p in d.plans if p["week"] and p0 - 6 * DAY <= p["week"] <= p1]
    actual_out = [t for t in in_p if t["io"] == "출금" and t["cat"] != TRANSFER]
    plan_amounts = defaultdict(list)
    for p in plan_rows:
        plan_amounts[(p["project"], p["vendor"])].append(p["amount"])
    plan_keys = {}
    plan_key_unknown = {}
    for k, amts in plan_amounts.items():
        total_k, unk_k = ssum(amts)
        plan_keys[k] = None if unk_k == len(amts) else total_k  # 계획 금액이 모두 빈칸이면 0이 아니라 미확인
        plan_key_unknown[k] = unk_k
    act_keys = defaultdict(int)
    for t in actual_out:
        act_keys[(t["project"], t["vendor"])] += t["amount"]
    pva = []
    for k in sorted(set(plan_keys) | set(act_keys)):
        pva.append({"project": k[0], "vendor": k[1], "plan": plan_keys.get(k), "actual": act_keys.get(k, 0),
                    "plan_unknown": plan_key_unknown.get(k, 0), "unplanned": k not in plan_keys})
    no_budget = [P for P in plist if P["budget"] is None]
    unlinked_txn = [t for t in in_p if t["io"] == "출금" and t["cat"] == "프로젝트지급"
                    and (not t["project"] or t["project"] not in proj)]
    plan_total, plan_unknown_n = ssum(p["amount"] for p in plan_rows)
    nb_contract, nb_contract_missing = ssum_or_none(P["contract"] for P in no_budget)  # 전부 미등록이면 0이 아니라 None
    asof_rows = []
    for a in d.asof:
        asof_rows.append(dict(a, age=None if a["date"] is None else (asof - a["date"]).days))
    R["s7"] = {
        "changes": changes, "undated_changes": undated_changes, "pva": pva, "plan_rows": plan_rows,
        "plan_total": plan_total, "plan_unknown_n": plan_unknown_n, "actual_total": sum(t["amount"] for t in actual_out),
        "unplanned_total": sum(x["actual"] for x in pva if x["unplanned"]),
        "no_budget": no_budget, "no_budget_expected": sum(P["expected"] for P in no_budget),
        "no_budget_contract": nb_contract, "no_budget_contract_missing": nb_contract_missing,
        "unlinked_txn": unlinked_txn, "unlinked_txn_total": sum(t["amount"] for t in unlinked_txn),
        "undated_out": R["s2"]["undated_out"], "undated_out_n": R["s2"]["undated_out_n"],
        "undated_out_unknown": R["s2"]["undated_out_unknown"],
        "asof": asof_rows, "diffs": d.diffs, "issues": issues.items, "checks": checks,
        "stale": stale_accounts,
    }
    R["targets"] = {t: v for (y, t), v in (getattr(d, "team_targets", None) or {}).items() if y == ym[:4]}
    from .corptax import depreciation   # 법인세 예상용 감가상각비 (사용자 2026-11-04)
    R["evid_month"] = getattr(d, "evid_month", None)   # 증빙 작성일자 기준 달별 매출·매입 (월간 흐름 그림)
    R["dep"] = depreciation(getattr(d, "accounts", None), getattr(d, "dep_manual", None) or {}, ym)
    R["acct_year"] = account_year(getattr(d, "accounts", None), ym, getattr(d, "accounts_problem", ""))
    R["last_pay"] = last_payday_out(d.txns, R["payday"])
    R["risks"] = risks(R)
    return R


def last_payday_out(txns, payday):
    """지난주 출금일(이번 출금일 − 7일)에 통장에서 실제로 나간 돈 (사용자 2026-11-05: 지난주 대비는 진짜 지난주 금요일과 비교).

    장부입출금(분개장 보통예금) 또는 입출금내역의 그날 출금, 계좌 간 이체는 뺀다. 입출금 자료가 그날까지 오지 않았으면 None."""
    day = payday - 7 * DAY
    if not txns or max(t["date"] for t in txns) < day:
        return None
    rows = [{"vendor": (t.get("vendor") or "").strip() or (t.get("memo") or "").strip() or "(거래처 없음)",
             "amount": t["amount"], "memo": t.get("memo") or ""}
            for t in txns if t["date"] == day and t["io"] == "출금" and t["cat"] != TRANSFER]
    return {"date": day, "rows": rows, "total": sum(r["amount"] for r in rows)}


ACCOUNT_GROUP_ORDER = ("원가", "판매비와관리비", "영업외비용")


def account_year(rows, ym, problem=""):
    """계정과목별 연간표 (사용자 2026-11-03: 월간 보고 때마다 해당 월 칸이 채워지며 누적).

    올해 1월~보고월 칸만 채우고 그 뒤 달은 비운다. 칸에 금액 빈 줄이 하나라도 있으면 그 칸은 None(미확인).
    구분 순서: 원가 → 판매비와관리비 → 영업외비용 (모르는 구분은 뒤에). 구분마다 소계, 맨 아래 합계."""
    if rows is None:
        return {"state": problem or "자료 없음", "year": ym[:4], "upto": int(ym[5:7]), "groups": []}
    year, upto = ym[:4], int(ym[5:7])
    cells = OrderedDict()
    names = {}
    for r in rows:
        if r["ym"][:4] != year or not r["ym"][5:7].isdigit() or int(r["ym"][5:7]) > upto:
            continue
        k = (r["group"] or "구분 없음", r["code"])
        names.setdefault(k, r["name"])
        m = int(r["ym"][5:7]) - 1
        c = cells.setdefault(k, [0] * 12 + [set()])
        if r["amount"] is None:
            c[12].add(m)
        else:
            c[m] += r["amount"]
    groups = []
    order = list(ACCOUNT_GROUP_ORDER) + sorted(set(g for g, _ in cells) - set(ACCOUNT_GROUP_ORDER))
    for g in order:
        accs = []
        for (gg, code), c in sorted(cells.items(), key=lambda kv: kv[0][1]):
            if gg != g:
                continue
            months = [None if (m in c[12] or m >= upto) else c[m] for m in range(12)]
            known = [v for v in months[:upto] if v is not None]
            accs.append({"code": code, "name": names[(gg, code)], "months": months,
                         "unknown": sorted(c[12]), "total": sum(known), "partial": bool(c[12])})
        if not accs:
            continue
        sub = [None if any(m in a["unknown"] for a in accs) or m >= upto else sum(a["months"][m] or 0 for a in accs)
               for m in range(12)]
        groups.append({"name": g, "accounts": accs, "months": sub, "total": sum(a["total"] for a in accs),
                       "partial": any(a["partial"] for a in accs)})
    tot = [None if m >= upto or any(g["months"][m] is None for g in groups) else sum(g["months"][m] for g in groups)
           for m in range(12)]
    return {"state": "ok" if groups else "올해 자료 없음", "year": year, "upto": upto, "groups": groups, "months": tot,
            "total": sum(g["total"] for g in groups), "partial": any(g["partial"] for g in groups)}


PAY_WEEKDAY = 4   # 금요일: 회사는 매주 금요일에 출금 (사용자 2026-11-03)


def pay_friday(asof):
    """자금 표·그림의 첫 주 끝 = 기준일 뒤 첫 금요일. 기준일이 금요일이면 그날 지급은 이미 지난 것으로 보므로 다음 금요일."""
    return asof + ((PAY_WEEKDAY - asof.weekday() - 1) % 7 + 1) * DAY


def period_ends(kind, asof, payday=None):
    """기간별 가용자금의 기간 (사용자 2026-11-03): 주간 = 기준일부터 1~4주, 월간 = 다음 1~3개월 말일.
    주간 첫 주 끝 = 출금일 (사용자 2026-11-04: 따로 넣은 날짜, 비우면 기준일 뒤 첫 금요일)."""
    if kind == "weekly":   # 출금일 단위 주 (사용자 2026-11-03: 다음 주 지급 목록과 같은 기간·같은 금액)
        f = payday or pay_friday(asof)
        labs = ("이번 주", "다음 주", "3주째", "4주째", "5주째")[1 if (f - asof).days >= 7 else 0:]
        return [(lab, f + 7 * i * DAY) for i, lab in enumerate(labs[:4])]
    # 기간 이름은 달 이름으로 (2026-11-04 이해도 점검 U6: '1개월' 대신 '11월')
    return [("%d월" % _month_end(_add_months(asof, i)).month, _month_end(_add_months(asof, i))) for i in range(1, 4)]


def available_periods(start, dated, ends, min_cash, asof):
    """기간마다 확정분만(firm)·예상분 포함(all)으로 입금·지급 예정, 예상 잔액, 기간 중 최저 잔액(날짜), 가용자금.

    같은 날 입출금은 합쳐서 본다. 시작 가용액을 모르면 잔액·가용자금은 None, 최소 보유현금을 모르면 가용자금만 None."""
    out = []
    prev = asof
    for label, end in ends:
        frm = prev if label != "지정일" else asof   # 그 기간 = 앞 기간 끝 다음 날부터 (지정일은 오늘부터)
        if label != "지정일":
            prev = end
        row = {"label": label, "end": end, "from": frm + DAY}
        for mode in ("firm", "all"):
            daily = defaultdict(int)
            tin = tout = 0
            for e in dated:
                if not (asof < e["date"] <= end) or (mode == "firm" and not e["firm"]):
                    continue
                if e["io"] == "in":
                    tin += e["amount"]
                    daily[e["date"]] += e["amount"]
                else:
                    tout += e["amount"]
                    daily[e["date"]] -= e["amount"]
            pin = sum(e["amount"] for e in dated if frm < e["date"] <= end and e["io"] == "in" and (mode == "all" or e["firm"]))
            pout = sum(e["amount"] for e in dated if frm < e["date"] <= end and e["io"] == "out" and (mode == "all" or e["firm"]))
            r = {"in": tin, "out": tout, "pin": pin, "pout": pout, "bal": None, "low": None, "low_date": None, "avail": None}
            if start is not None:
                bal, low, low_d = start, start, asof
                for day in sorted(daily):
                    bal += daily[day]
                    if bal < low:
                        low, low_d = bal, day
                r.update(bal=bal, low=low, low_date=low_d, avail=None if min_cash is None else low - min_cash)
            row[mode] = r
        out.append(row)
    return out


def event_unissued(inv_proj, asof, in_missing):
    """행사일이 기준일보다 앞선 프로젝트 중 매출 계산서가 덜 나간 것 (사용자 2026-11-03).

    미발행 = 사전견적금액(공급가액, 사용자 선택 2026-11-03) − 발행 공급가액. 오래된 행사 순. 사전견적·행사일·발행금액을 모르면
    0으로 치지 않고 unknown 에 까닭과 함께 둔다. 계산서 자료가 없으면 합계는 None (0 아님)."""
    rows, unknown = [], []
    for x in inv_proj:
        P = x["P"]
        ev = _event_date(P.get("event_date"))
        if ev is None:
            if (P.get("event_date") or "").strip():
                unknown.append({"P": P, "why": "행사일 해석 불가"})
            else:
                unknown.append({"P": P, "why": "행사일 없음"})
            continue
        if ev >= asof:
            continue
        if P.get("estimate") is None:
            unknown.append({"P": P, "why": "사전견적 없음"})
            continue
        if in_missing or x["issued"] is None:
            unknown.append({"P": P, "why": "발행금액 미확인"})
            continue
        left = P["estimate"] - x["issued"]
        if left > 0:
            rows.append({"P": P, "event": ev, "days": (asof - ev).days, "estimate": P["estimate"],
                         "issued": x["issued"], "unissued": left})
    rows.sort(key=lambda y: (-y["days"], y["P"]["id"]))
    return {"rows": rows, "unknown": unknown, "missing": bool(in_missing),
            "total": None if in_missing else sum(y["unissued"] for y in rows)}


def expected_revenue(inv_proj, asof, in_missing):
    """인트라넷 사전견적(예상 매출) 중 아직 계산서가 안 나간 금액을 행사일로 나눈다 (사용자 2026-11-04: 대표 보고에도).

    남은 예상 매출 = 사전견적(공급가액) − 발행 공급가액, 0 밑은 0. 묶음: 행사 끝남(= 행사 끝난 뒤 미발행과 같은 수),
    올해 남은 행사, 다음 해 이후. 사전견적이 있는 프로젝트만 센다. 행사일·발행금액을 모르면 금액에 넣지 않고 건수로만."""
    groups = {"past": [0, 0], "this_year": [0, 0], "later": [0, 0]}
    est_total = est_n = 0
    no_date = unknown_issued = year_est = year_n = 0
    by_team = {}
    for x in inv_proj:
        P = x["P"]
        if P.get("estimate") is None:
            continue
        est_total += P["estimate"]
        est_n += 1
        ev = _event_date(P.get("event_date"))
        if ev is None:
            no_date += 1
            continue
        if ev.year == asof.year:   # 올해 행사의 예상 매출 합계: 누적 매출과 견줘 보인다 (사용자 2026-11-04)
            year_est += P["estimate"]
            year_n += 1
        if in_missing or x["issued"] is None:
            unknown_issued += 1
            continue
        left = P["estimate"] - x["issued"]
        if left <= 0:
            continue
        g = "past" if ev < asof else ("this_year" if ev.year == asof.year else "later")
        groups[g][0] += left
        groups[g][1] += 1
        if g != "later":   # 팀별 (누적 매출 표와 견주기, 사용자 2026-11-04)
            t = by_team.setdefault((P.get("team") or "").strip(), {"past": 0, "this_year": 0, "n": 0})
            t[g] += left
            t["n"] += 1
    return {"missing": bool(in_missing), "est_total": est_total, "est_n": est_n,
            "past": groups["past"][0], "past_n": groups["past"][1],
            "this_year": groups["this_year"][0], "this_year_n": groups["this_year"][1],
            "later": groups["later"][0], "later_n": groups["later"][1],
            "no_date_n": no_date, "unknown_n": unknown_issued, "year_est": year_est, "year_n": year_n, "by_team": by_team}


def _net_credits(invs):
    """취소·수정 계산서의 음수 미수를 같은 프로젝트(거래처를 둘 다 알면 같은 거래처)의 남은 미수에서 뺀다.

    계산서와 그 취소를 함께 넣어도 입금예정이 남지 않게 한다. 금액이 같은 미수 한 건을 먼저, 그다음 발행일 순으로 뺀다.
    프로젝트 미수는 0 밑으로 내려가지 않는다: 뺄 미수가 없는 음수는 버리고(입금예정·환급을 만들지 않음) 'credit_left'로 남긴다.
    """
    for c in invs:
        c.setdefault("netted", 0)
    for c in invs:
        if c["kind"] not in ("취소", "수정") or c["outstanding"] is None or c["outstanding"] >= 0:
            continue
        credit = -c["outstanding"]
        if not c["project"] and not c["client"]:
            c["credit_applied"], c["credit_left"] = 0, credit  # 프로젝트·거래처를 모두 모르면 어디서도 빼지 않는다
            continue
        cands = [v for v in invs if v is not c and v["kind"] != "환불" and v["project"] == c["project"]
                 and v["outstanding"] is not None and v["outstanding"] > 0
                 and (c["project"] or c["client"] == v["client"])
                 and (not c["client"] or not v["client"] or c["client"] == v["client"])]
        exact = [v for v in cands if v["outstanding"] == credit][:1]
        rest = sorted((v for v in cands if not any(v is x for x in exact)),
                      key=lambda v: (v["date"] is None, v["date"] or dt.date.min))
        left = credit
        for v in exact + rest:
            if left <= 0:
                break
            take = min(left, v["outstanding"])
            v["outstanding"] -= take
            v["netted"] += take
            left -= take
        if left > 0 and c["client"]:
            # 같은 프로젝트에서 다 못 뺀 감액은 같은 거래처의 다른 미수에서 오래된 것부터 뺀다 (2026-11-04: 수정 계산서가
            # 다른 프로젝트로 붙어 거래처 미수가 1억여 원 부풀던 것. 장부 매출채권은 거래처 단위로 줄어든다)
            more = sorted((v for v in invs if v is not c and v["kind"] != "환불" and v["client"] == c["client"]
                           and v["outstanding"] is not None and v["outstanding"] > 0),
                          key=lambda v: (v["date"] is None, v["date"] or dt.date.min))
            for v in more:
                if left <= 0:
                    break
                take = min(left, v["outstanding"])
                v["outstanding"] -= take
                v["netted"] += take
                left -= take
        c["credit_applied"], c["credit_left"] = credit - left, left


def _blank_proj(p, rate):
    """프로젝트 한 건의 빈 집계 틀. 원가 예산 = 사전견적 x 원가율. 만들 수 없으면 예산은 None, 이유를 남긴다 (D-16)."""
    P = dict(p)
    P.update({"lines": [], "paid": 0, "paid_cash": 0, "paid_cash_reason": None, "vat_unknown": 0, "paid_period": 0, "card_paid": 0,
              "requested": 0, "card_unpaid": 0, "planned": 0, "unknown_cost": 0,
              # 상태별 줄 수와 금액 미확인 줄 수: 합계는 확인된 금액만이고, 첫 화면은 이 건수를 함께 보인다
              "line_n": dict.fromkeys(EXEC_STATES, 0), "line_unknown": dict.fromkeys(EXEC_STATES, 0)})
    est = P["estimate"]
    P["budget"], P["budget_reason"] = None, None
    if est is None:
        P["budget_reason"] = "사전견적 없음" if is_blank(P["estimate_raw"]) else "사전견적 금액 해석 불가"
    elif est <= 0:
        P["budget_reason"] = "사전견적 0원 또는 음수"
    elif rate is None:
        P["budget_reason"] = "원가율 설정 오류"
    else:
        P["budget"] = int(round(est * rate))
    return P


def _pl_sum(rows):
    if not rows:
        return None
    rev, ru = ssum(p["revenue"] for p in rows)
    dc, du = ssum(p["direct"] for p in rows)
    cc, cu = ssum(p["common"] for p in rows)
    has_common = any(p["common"] is not None for p in rows)
    gp = None if (ru or du) else rev - dc
    np_ = None if (gp is None or cu or not has_common) else gp - cc
    return {"revenue": None if ru else rev, "direct": None if du else dc, "common": cc if has_common and not cu else None,
            "gp": gp, "np": np_, "provisional": any(p["provisional"] for p in rows),
            "months": sorted(set(p["ym"] for p in rows))}


def risks(R):
    """경영관리용에만 싣는 위험 분석과 해결방안. 기준값은 설정.csv에서 바꾼다."""
    sn = R["settings_num"]
    out = []

    def add(level, area, fact, action):
        out.append({"level": level, "area": area, "fact": fact, "action": action})

    min_cash = sn["위험_최소보유현금"]
    ar_days = sn["위험_미수경과일"]
    ui_days = sn["위험_미발행경과일"]
    data_days = sn["위험_자료경과일"]
    over_pct = sn["위험_예산초과율"]
    s2 = R["s2"]
    for mode, label in (("firm", "확정 일정만"), ("all", "확정+추정")):
        low, low_d = s2["min"][mode]
        if low is None:
            continue  # 시작 잔액을 모르면 자금 위험을 만들지 않는다 (아래 자료 항목에서 알림)
        if low < min_cash:
            add("높음" if low < 0 else "중간", "자금",
                "%s 기준 최저 계산 잔액 %s원 (%s). 최소 보유 기준 %s원." % (label, won(low), d2s(low_d), won(min_cash)),
                "%s 이전 입금예정 건의 입금일 확인·앞당김 요청, 같은 기간 지급 중 조정 가능한 건의 지급일 협의, "
                "필요 시 단기 자금(한도대출 등) 사전 확보." % d2s(low_d))
    if s2["out_missing"]:
        add("높음", "자료", "지급 자료를 읽지 못해 지급예정이 빠졌으므로 기간별 계산 잔액과 최저 잔액을 계산하지 않음: %s."
            % ", ".join(s2["out_missing"]),
            "입력 폴더에 해당 CSV를 양식(입력양식 폴더)의 머리글 그대로 'CSV UTF-8' 또는 'CSV'로 저장.")
    if s2["in_missing"]:
        add("중간", "자료", "계산서 자료를 읽지 못해 발행 후 미수·발행금액·미발행금액과 계산서 입금예정을 알 수 없음: %s. "
            "기간별 계산 잔액과 최저 잔액은 계산서 입금 없이 계산함 (실제보다 낮을 수 있음)." % ", ".join(s2["in_missing"]),
            "입력 폴더에 계산서.csv를 양식(입력양식 폴더)의 머리글 그대로 'CSV UTF-8' 또는 'CSV'로 저장.")
    if R["s1"]["total"] is None:
        add("중간", "자료", "현재 계좌 잔액을 확인할 수 없어 기간별 계산 잔액과 최저 잔액을 계산하지 않음.",
            "계좌잔액.csv에 보고 기준일 잔액을 입력.")
    if s2["undated_out_n"]:
        add("중간", "자금", "지급일이 없는 지급예정 %s (%d건%s)이 일정 그래프에 들어가지 않음."
            % ("금액 미확인" if s2["undated_out"] is None else won(s2["undated_out"]) + "원", s2["undated_out_n"],
               ", 금액 미확인 %d건 포함" % s2["undated_out_unknown"] if s2["undated_out_unknown"] else ""),
            "담당자에게 지급일 확정을 요청하고, 확정 전까지는 가장 이른 날짜로 가정한 잔액도 함께 검토.")
    if s2["undated_in_n"]:
        add("중간", "자금", "입금일이 없는 입금예정 %s (%d건%s)이 일정에 들어가지 않음."
            % ("금액 미확인" if s2["undated_in"] is None else won(s2["undated_in"]) + "원", s2["undated_in_n"],
               ", 금액 미확인 %d건 포함" % s2["undated_in_unknown"] if s2["undated_in_unknown"] else ""),
            "거래처와 입금일을 확정해 일정에 반영.")
    for P in R["s3"]["projects"]:
        if P["budget"] is not None and P["budget"] > 0 and P["expected"] * 100.0 / P["budget"] > over_pct:
            add("높음", "프로젝트", "%s %s: 예상총집행 %s원이 예산 %s원의 %.1f%%."
                % (P["id"], P["name"], won(P["expected"]), won(P["budget"]), P["expected"] * 100.0 / P["budget"]),
                "남은 지급요청·집행계획 중 줄일 수 있는 항목 확인, 추가 범위는 고객과 변경계약 협의, 예산 수정 등록.")
        if P["profit_end"] is not None and P["profit_end"] < 0:
            add("높음", "프로젝트", "%s %s: 종료 시점 예상이익 %s원." % (P["id"], P["name"], won(P["profit_end"])),
                "원가 절감 가능 항목과 추가 청구 가능 범위 검토.")
        if P["unknown_cost"]:
            add("중간", "프로젝트", "%s %s: 금액 미확인 원가 %d건 — 예상이익 판단 불가." % (P["id"], P["name"], P["unknown_cost"]),
                "담당자에게 견적·발주 금액 확정을 요청.")
    nb = R["s7"]["no_budget"]
    if nb:
        add("중간", "프로젝트", "예산 미지정 프로젝트 %d건, 예상총집행 %s원." % (len(nb), won(R["s7"]["no_budget_expected"])),
            "인트라넷 사전 견적을 등록해 예산 대비 집행을 관리.")
    for v in R["s5"]["overdue"]:
        if v["overdue_days"] >= ar_days:
            add("높음" if v["overdue_days"] >= ar_days * 2 else "중간", "수금",
                "%s %s: 입금예정일 %s에서 %d일 경과, 미수 %s원." % (v["project"], v["client"], d2s(v["due"]),
                                                       v["overdue_days"], won(v["outstanding"])),
                "거래처 담당자에게 지급 일정 확인, 필요 시 공문 발송.")
    for x in R["s5"]["unissued_aged"]:
        if x["unissued_days"] >= ui_days:
            add("중간", "수금", "%s %s: 완료 후 %d일, 미발행 %s원." % (x["P"]["id"], x["P"]["name"], x["unissued_days"],
                                                          won(x["unissued"])),
                "발행 조건(검수·정산) 확인 후 계산서 발행.")
    s7 = R["s7"]
    if s7["unlinked_txn_total"] or R["s3"]["unlinked_total"]:
        add("중간", "자료", "프로젝트 미연결 지급 %s원 (출금내역) / %s원 (집행자료)."
            % (won(s7["unlinked_txn_total"]), won(R["s3"]["unlinked_total"])),
            "지급마다 프로젝트번호를 연결해 프로젝트 원가에 반영.")
    if s7["unplanned_total"]:
        add("중간", "지급 관리", "주간 지급계획에 없던 지급 %s원." % won(s7["unplanned_total"]),
            "계획 외 지급의 승인 경로 확인, 다음 주 계획에 미리 등록.")
    for a in s7["asof"]:
        if a["age"] is None or a["age"] > data_days:
            add("중간", "자료", "%s 기준일 %s (%s)." % (a["name"], d2s(a["date"]),
                                                  "날짜 없음" if a["age"] is None else "%d일 전" % a["age"]),
                "보고 전 해당 자료를 최신으로 갱신.")
    for x in s7["diffs"]:
        if x["state"] != "확인완료":
            add("중간", "자료", "%s: %s %s원 / %s %s원." % (x["item"], x["a"], won(x["a_amt"]), x["b"], won(x["b_amt"])),
                "두 자료를 건별로 대조해 차이 원인 확정.")
    for c in s7["checks"]:
        if not c[3]:
            add("높음", "자료", "대조 불일치: %s (%s / %s)." % (c[0], won(c[1]), won(c[2])), "입력 자료를 다시 확인.")
    order = {"높음": 0, "중간": 1}
    out.sort(key=lambda r: order.get(r["level"], 2))
    return out
