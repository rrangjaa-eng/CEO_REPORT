"""법인세 예상 (사용자 2026-11-04): 올해 누적 세전 이익으로 법인세·지방소득세를 어림한다.

- 두 가지를 따로 낸다: 영업외 수익을 뺀 세전 이익 기준, 영업외 수익을 넣은 세전 이익 기준.
- 감가상각비는 장부에 12월 결산 때 한 번에 들어가므로(2025년 실제), 연간 예상을 결산 줄에서 비용으로 먼저 빼고 남은 것이 세전 이익.
  연간 감가상각비 = 대표보고 창 '⑨ 감가상각비'로 넣은 값(입력/감가상각비.csv), 없으면 작년 계정별비용의 감가상각비 합계.
  누적에는 지난 달 수만큼만 뺀다 (결정 M5, 2026-11-15: 연간 × 달 수 ÷ 12). 올해 이미 장부에 들어간 감가상각비는 다시 빼지 않는다.
- 세무조정(접대비 한도 등)·세액공제·감면·이월결손금·중간예납과 원천징수 선납세금은 반영하지 않는다 (어림값).
"""
import csv
import os
from .util import open_text as _open_text  # UTF-8·CP949 모두 읽음 (C5)

DEP_FILE = "감가상각비.csv"
DEP_COLUMNS = ["연도", "연간감가상각비"]

# 과세표준 구간 상한(원)과 세율. 2026년 1월 1일 이후 시작 사업연도부터 1%p 인상 (2025-12 국회 통과)
BRACKETS_2026 = ((200_000_000, 0.10), (20_000_000_000, 0.20), (300_000_000_000, 0.22), (None, 0.25))
BRACKETS_2023 = ((200_000_000, 0.09), (20_000_000_000, 0.19), (300_000_000_000, 0.21), (None, 0.24))
LOCAL_RATE = 0.10   # 법인지방소득세 = 법인세의 10%
LOCAL_WORDS = ("지방", "구청", "시청", "군청")   # 선납세금 중 지방소득세 줄 (코드가 없어 낱말, 근거에 건수를 보임 — E3)


def brackets(year):
    return BRACKETS_2026 if int(year) >= 2026 else BRACKETS_2023


def corp_tax(base, year):
    """과세표준 -> 법인세 산출세액 (원, 내림). 0 이하면 0."""
    if base is None:
        return None
    if base <= 0:
        return 0
    tax, low = 0.0, 0
    for top, rate in brackets(year):
        hi = base if top is None else min(base, top)
        if hi > low:
            tax += (hi - low) * rate
        if top is None or base <= top:
            break
        low = top
    return int(tax)


def national(base, year, input_dir=None):
    """-> (낼 법인세: 감면·이월공제 뒤 + 농어촌특별세, 산출세액, credits dict 또는 None).
    작년 상세 신고서(입력/법인세신고.csv 특별감면·공제이월)가 있으면 그 감면을 적용 (사용자 2026-11-13). 없으면 산출세액 그대로.
    지방소득세는 감면 없이 산출세액 × 10% 그대로."""
    corp = corp_tax(base, year)
    if corp is None or not input_dir:
        return corp, corp, None
    from . import taxreturn
    C = taxreturn.credits(input_dir, int(year), base, corp)
    return (C["national"] if C else corp), corp, C


def _int(text):
    t = str(text or "").replace(",", "").replace("원", "").strip()
    return int(t) if t.isdigit() else None


LEDGER_FILE = "고정자산.csv"   # 위하고 고정자산관리대장 (wehago_raw 가 자료 변환 때 만듦)


def read_ledger(input_dir, wehago_dir=None):
    """위하고 고정자산관리대장의 당기 상각 예정액 -> {연도: 합계} (사용자 2026-11-13: 올해 감가상각비 예상은 대장 금액).
    wehago_dir 가 있으면 원본을 바로 읽는다 (같은 변환 안에서 고정자산.csv 가 아직 안 써졌을 때)."""
    rows = []
    if wehago_dir:
        from . import wehago_raw
        rows = wehago_raw.asset_rows(wehago_raw.files(wehago_dir))
    if not rows and input_dir and os.path.exists(os.path.join(input_dir, LEDGER_FILE)):
        try:
            with _open_text(os.path.join(input_dir, LEDGER_FILE)) as f:
                rows = list(csv.DictReader(f))
        except (OSError, UnicodeDecodeError, csv.Error):
            rows = []
    out = {}
    for r in rows:
        y, v = (r.get("기준연도") or "").strip(), _int(r.get("당기상각"))
        if y.isdigit() and v is not None:
            out[y] = out.get(y, 0) + v
    return out


def read(input_dir):
    """-> {연도: 연간 감가상각비 직접 입력, ("대장", 연도): 위하고 고정자산대장 당기 상각}. 없거나 읽지 못하면 {}."""
    path = os.path.join(input_dir, DEP_FILE)
    out = {}
    try:
        with _open_text(path) as f:
            for r in csv.DictReader(f):
                y, v = (r.get("연도") or "").strip(), _int(r.get("연간감가상각비"))
                if y.isdigit() and v is not None:
                    out[y] = v
    except (OSError, UnicodeDecodeError, csv.Error):
        out = {}
    for y, v in read_ledger(input_dir).items():   # 위하고 고정자산대장 (사용자 2026-11-13): 직접 입력이 없는 해에 씀
        out[("대장", y)] = v
    return out


def save(input_dir, year, amount):
    """한 해의 연간 감가상각비를 넣거나 고친다. 금액을 비우면 그 해 줄을 지운다 (작년 장부 값으로 돌아감). -> 줄 수."""
    y = str(year or "").strip()
    if not (y.isdigit() and len(y) == 4):
        raise ValueError("연도는 4자리 (예: 2026)")
    if not os.path.isdir(input_dir):
        raise ValueError("입력 폴더가 없습니다: %s" % input_dir)
    from .util import guard_save
    guard_save(os.path.join(input_dir, DEP_FILE))   # 못 읽은 파일을 새 줄만으로 덮지 않음 (C5)
    cur = dict((k, v) for k, v in read(input_dir).items() if isinstance(k, str))   # 대장 값은 파일에 쓰지 않음
    if str(amount or "").strip():
        v = _int(amount)
        if v is None:
            raise ValueError("연간 감가상각비는 원 단위 숫자 (예: 12,000,000)")
        cur[y] = v
    else:
        cur.pop(y, None)
    path = os.path.join(input_dir, DEP_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(DEP_COLUMNS)
        for k in sorted(cur):
            w.writerow([k, cur[k]])
    os.replace(tmp, path)
    return len(cur)


def _dep_rows(accounts, year):
    return [r for r in (accounts or []) if r["ym"][:4] == str(year) and "감가상각비" in (r.get("name") or "")]


# 누적에서 미리 뺄 감가상각비: 'prorate' = 연간 × 지난 달 수 ÷ 12, 'full' = 연간 전액.
# 결정 M5 (2026-11-15, 계산-14): 월할(prorate). 11/4 '연간 전액을 먼저 뺀다'를 바꿈 — 1~10월 이익에서 12달 치를 빼면 이익·법인세가 작게 나옴.
# 이번 달 표에는 넣지 않는다 (11/4 그대로, M5는 누적만).
DEP_MODE = "prorate"


def depreciation(accounts, manual, ym, mode=None, ledger=None):
    """-> {"annual", "source", "booked", "extra"(누적), "cur"(이번 달), "months"}. annual None = 모름 (extra·cur 도 None).

    감가상각비는 연말 결산 때 한 번에 들어가므로 연간 예상(직접 입력·고정자산대장·작년 장부)을 비용으로 먼저 뺀다 (사용자 2026-11-04).
    결정 M5 (2026-11-15): 누적에는 지난 달 수만큼만 (연간 × 달 수 ÷ 12).
    올해 이미 장부에 들어간 감가상각비는 세전 이익에 빠져 있으므로 그만큼은 다시 빼지 않는다."""
    mode = mode or DEP_MODE
    year, months = ym[:4], int(ym[5:7])
    booked_rows = [r for r in _dep_rows(accounts, year) if r["ym"] <= ym]
    booked = sum(r["amount"] or 0 for r in booked_rows)
    if manual.get(year) is not None:
        annual, source = manual[year], "직접 입력"
    elif (ledger or {}).get(year) is not None or manual.get(("대장", year)) is not None:
        annual, source = (ledger or {}).get(year, manual.get(("대장", year))), "고정자산대장"
    else:
        last = _dep_rows(accounts, int(year) - 1)
        annual = sum(r["amount"] or 0 for r in last) if last else None
        source = "작년 장부" if last else ""
    share = months if mode == "prorate" else 12
    extra = None if annual is None else max(int(round(annual * share / 12.0)) - booked, 0)
    cur = None   # 이번 달 표에는 넣지 않음 (11/4, 결정 M5도 누적만)
    return {"annual": annual, "source": source, "booked": booked, "extra": extra, "cur": cur, "months": months, "mode": mode}


def apply(N, amount):
    """결산 dict(teamprofit nonop)에 감가상각비 예상을 넣는다: N['dep'] = 금액, 세전 이익 = 그만큼 뺀 값. 모르면 빼지 않는다."""
    N["dep"] = amount
    if amount and N.get("pretax") is not None:
        N["pretax"] = N["pretax"] - amount
    return N


def estimate(pretax, nonop_in, ym):
    """누적 세전 이익(감가상각비 예상 뺀 값)·영업외 수익 -> 두 줄 [{label, base, corp, local, total}]. 모르는 값은 None."""
    year = ym[:4]
    rows = []
    for label, base in (("영업외 수익 뺀 세전 이익 기준", None if pretax is None or nonop_in is None else pretax - nonop_in),
                        ("영업외 수익 넣은 세전 이익 기준", pretax)):
        corp = corp_tax(base, year)
        local = None if corp is None else int(corp * LOCAL_RATE)
        rows.append({"label": label, "base": base, "corp": corp, "local": local,
                     "total": None if corp is None else corp + local})
    return rows


# ───────────── 대손충당금 (사용자 2026-11-12: 프로그램에 넣어) ─────────────
RECEIVABLE_CODES = ("10800", "11000", "12000")   # 외상매출금(수입수수료미수금)·받을어음·미수금
BAD_DEBT_RATE = 0.01   # 세법 한도: 채권 잔액의 1% (실제 대손실적률이 더 높으면 그 비율 — 세무사 확인)


def bad_debt(journal, cfg, ym, input_dir=None):
    """결산 때 넣을 대손충당금 예상 -> {"receivable", "allowance", "amount", "partial", "note"}.

    채권 잔액(외상매출금·받을어음·미수금, ym 말까지 장부 누계) × 1% − 이미 쌓인 대손충당금 잔액 = 올해 더 쌓을 금액(0 밑으로 안 감).
    결산조정 항목이라 장부에 넣어야 비용 인정 → 법인세 예상에서 감가상각비처럼 미리 뺀다.
    분개장이 회사 첫해부터 없고 전기이월 줄도 없으면 작년 말 잔액을 몰라 올해 움직임만 본다(partial: 작게 잡힘)."""
    from .convert_pl import _squash
    from .surplus import FOUNDED
    codes = set(_squash(c) for c in cfg.get("receivable_codes", RECEIVABLE_CODES))
    rec = allow = 0
    years, opening = set(), False
    for ln in journal:
        d = ln.get("date")
        if d is None or d.strftime("%Y-%m") > ym:
            continue
        years.add(d.year)
        code, name = _squash(ln.get("account_code")), _squash(ln.get("account"))
        dr, cr = ln.get("debit") or 0, ln.get("credit") or 0
        if code in codes:
            rec += dr - cr
        elif "대손충당금" in name:
            allow += cr - dr
        else:
            continue
        if "전기이월" in _squash(ln.get("sort")) + _squash(ln.get("memo")):
            opening = True
    partial = bool(years) and min(years) > FOUNDED and not opening
    rec = max(rec, 0)
    from . import taxlaw
    rate, rate_ok = taxlaw.checked(input_dir, int(ym[:4]), "대손충당금률", BAD_DEBT_RATE)
    amount = max(int(rec * rate) - allow, 0)
    note = "받을 돈 %s × %g%% − 쌓인 충당금 %s" % ("{:,}".format(rec), rate * 100, "{:,}".format(allow))
    if partial:
        note += " (작년 말 잔액 없어 올해 늘어난 몫만 — 작게 잡힘)"
    if not rate_ok:
        note += " (한도율이 '세법 기준 확인'에서 확인되지 않아 기본 %g%%로 봄)" % (BAD_DEBT_RATE * 100)
    return {"receivable": rec, "allowance": allow, "amount": amount, "partial": partial, "note": note}


def bad_debt_saving(base, amount, year, input_dir=None):
    """대손충당금 amount 를 결산에 넣으면 줄어드는 법인세·지방소득세 (과세표준 base 기준) -> 원. 모르면 None."""
    nat, corp, _ = national(base, year, input_dir)
    nat2, corp2, _ = national(base - amount, year, input_dir)
    if None in (nat, corp, nat2, corp2):
        return None
    return (nat + int(corp * LOCAL_RATE)) - (nat2 + int(corp2 * LOCAL_RATE))


# 11/15~11/17 변환 파일의 근거 글 (그때는 빼지 않고 이 글만 적었음) — 보고서가 예전 파일을 읽을 때만 쓴다
BAD_DEBT_HINT = "대손충당금 예상 %s원은 세무사 확인 전이라 빼지 않음 (쌓으면 세금 −%s원)"
BAD_DEBT_HINT_RE = r"대손충당금 예상 ([\d,]+)원은 세무사 확인 전이라 빼지 않음 \(쌓으면 세금 −([\d,]+|모름)원\)"


def bad_debt_hint(amount, saving):
    """11/15~11/17 판이 세금예상.csv 법인세 줄 근거에 붙였던 글 (시험·예전 파일 읽기용)."""
    return BAD_DEBT_HINT % ("{:,}".format(amount), "모름" if saving is None else "{:,}".format(saving))


# ───────────── 변환 쪽: 분개장으로 법인세 납부 예상 (사용자 2026-11-04: 지급 예상에 넣고, 중간예납 등 선납세금은 뺀다) ─────────────
PREPAID_CODES = ("13600",)   # 선납세금: 8월 중간예납 + 이자 원천징수 법인세


def _last_full_month(asof):
    """보고 대상 마지막 달: 기준일이 그 달 말일이면 그 달, 아니면 앞 달. -> 'YYYY-MM' (1월 초면 작년 12월)."""
    import calendar
    import datetime as dt
    if asof.day == calendar.monthrange(asof.year, asof.month)[1]:
        return asof.strftime("%Y-%m")
    prev = asof.replace(day=1) - dt.timedelta(days=1)
    return prev.strftime("%Y-%m")


def adjust_for(journal, cfg, asof, input_dir=None, wehago_dir=None):
    """세무조정 예상 (taxadj) — 법인세 예상과 같은 기간·같은 매출 기준."""
    from .convert_pl import _classify, _net
    from . import taxadj, dividend
    ym = _last_full_month(asof)
    rev = 0
    for ln in journal:
        d = ln.get("date")
        if d is None or d.strftime("%Y-%m") > ym or d.year != int(ym[:4]):
            continue
        if _classify(ln, cfg) == "revenue":
            rev += _net(ln, "revenue") or 0
    try:
        ans = dividend.read_settings(input_dir) if input_dir else {}
    except OSError:
        ans = {}
    return taxadj.adjust(journal, cfg, ym, input_dir, rev, ans, wehago_dir)


def from_journal(journal, cfg, asof, manual=None, input_dir=None, wehago_dir=None):
    """-> (세금예상 줄 목록, 메모). 올해 1월~마지막 달 장부로 세전 이익(감가상각비 예상 뺀) → 법인세 − 선납세금, 지방소득세.

    납부일 = 다음 해 3월 31일(법인세), 4월 30일(지방소득세), 토·일이면 월요일. 상태는 '예상'."""
    import datetime as dt
    from .convert_pl import _classify, _net, _squash
    from .tax import _row, _workday
    ym = _last_full_month(asof)
    year = ym[:4]
    nin, nout = set(_squash(c) for c in cfg["nonop_in_codes"]), set(_squash(c) for c in cfg["nonop_out_codes"])
    from .convert import closing_pl_line
    closing = cfg.get("closing_sorts", ())
    prepaid_codes = set(_squash(c) for c in cfg.get("prepaid_tax_codes", PREPAID_CODES))
    pretax, unknown, prepaid, local_prepaid, dep_lines = 0, 0, 0, 0, []
    by_month = {}   # E1: 달마다 세전 이익 (남은 달 예상에 씀)
    local_lines = []
    for ln in journal:
        ln = closing_pl_line(ln, closing)   # 결산 전표: 원가·손익 대체는 빼고 감가상각비 차변만 (변환과 같게)
        if ln is None or ln["date"] is None:
            continue
        lym = ln["date"].strftime("%Y-%m")
        code = _squash(ln["account_code"])
        if "감가상각비" in _squash(ln["account"]) and lym[:4] in (year, str(int(year) - 1)):
            dep_lines.append({"ym": lym, "name": ln["account"], "amount": _net(ln, "common")})
        if lym[:4] != year or lym > ym:
            continue
        if code in prepaid_codes:
            # 11/17 최종 점검: 원천징수된 지방소득세(거래처·적요에 '지방')는 법인세가 아니라 지방소득세에서 뺀다
            # E3 (2026-11-17, 계산-11): 선납세금 계정 안에서 지방소득세를 가르는 코드가 없어 거래처·적요 낱말로 가른다 →
            # 낱말로 가른 줄은 근거에 건수·금액을 보여 확인받는다 (거래처가 구청·시청·군청이어도 지방세)
            if any(w in _squash(ln.get("vendor")) + _squash(ln.get("memo")) for w in LOCAL_WORDS):
                local_prepaid += (ln["debit"] or 0) - (ln["credit"] or 0)
                local_lines.append(ln)
            else:
                prepaid += (ln["debit"] or 0) - (ln["credit"] or 0)
            continue
        kind = _classify(ln, cfg)
        if code in nin:
            v, sign = _net(ln, "revenue"), 1
        elif code in nout:
            v, sign = _net(ln, "common"), -1
        elif kind == "revenue":
            v, sign = _net(ln, "revenue"), 1
        elif kind in ("direct", "common", "common_unmarked"):
            v, sign = _net(ln, "common"), -1
        else:
            continue
        if v is None:
            unknown += 1
        else:
            pretax += sign * v
            by_month[lym] = by_month.get(lym, 0) + sign * v
    dep = depreciation(dep_lines, manual or {}, ym, ledger=read_ledger(input_dir, wehago_dir))
    bd = bad_debt(journal, cfg, ym, input_dir)
    adj = adjust_for(journal, cfg, asof, input_dir, wehago_dir)
    # 규칙 계산-08 (사용자 2026-11-17, 11/15 결정 d를 바꿈): 대손충당금은 세무사 답과 상관없이 프로그램이 계산한 예상 금액을
    # 감가상각비처럼 과세표준에서 먼저 뺀다 (받을 돈 × 한도율 − 쌓인 충당금)
    base = pretax - (dep["extra"] or 0) - bd["amount"] + adj["total"]
    nat, corp, C = national(base, year, input_dir)
    local_tax = int(corp * LOCAL_RATE)
    local = max(local_tax - local_prepaid, 0)
    pay = max(nat - prepaid, 0)
    nxt = int(year) + 1
    period = "%s년 (1월~%d월 장부 기준)" % (year, int(ym[5:]))
    basis = ("세전 이익 %s − 감가상각비 예상 %s − 대손충당금 예상 %s = 과세표준 %s → 법인세 %s − 중간예납 등 선납세금 %s"
             % ("{:,}".format(pretax), "{:,}".format(dep["extra"] or 0), "{:,}".format(bd["amount"]), "{:,}".format(base),
                "{:,}".format(corp), "{:,}".format(prepaid)))
    if C:
        newc = [x for x in C.get("extra") or [] if x["used"] or x["carry"]]
        basis = basis.replace(" − 중간예납 등", " → 감면·공제 뒤 %s + 농어촌특별세 %s (작년 신고서: 중소기업 특별세액감면, 넘어온 고용 공제%s) − 중간예납 등"
                              % ("{:,}".format(C["final"]), "{:,}".format(C["nong"]),
                                 "".join(" · 받음: %s %s원 중 %s원 사용" % (x["name"], "{:,}".format(x["amount"]), "{:,}".format(x["used"])) for x in newc)), 1)
        if C.get("carries"):
            basis += " · 내년으로 넘어갈 공제 %s원 (%s)" % ("{:,}".format(C["carry_next"]),
                                                     ", ".join("%d년분 %d년까지" % (c["from"], c["until"]) for c in C["carries"]))
    if adj["total"]:
        basis = basis.replace(" = 과세표준", " + 세무조정 예상 %s = 과세표준" % "{:,}".format(adj["total"]), 1)
    basis += " · 대손충당금 = " + bd["note"]
    if unknown:
        basis += " · 금액 없는 손익 줄 %d건 뺌" % unknown
    if local_lines:
        basis += " · 선납세금 중 지방소득세로 가른 줄 %d건 %s원 (거래처·적요에 '지방'·구청 등 — 한 줄에 국세·지방세를 함께 넣었으면 확인)" % (
            len(local_lines), "{:,}".format(local_prepaid))
    rows = [dict(_row("법인세", period, _workday(dt.date(nxt, 3, 31)), None if unknown else pay, "예상", basis),
                 과세표준=str(base), 산출세액=str(corp), 기납부=str(prepaid), 대손충당금=str(bd["amount"]), 세무조정=str(adj["total"])),
            dict(_row("법인지방소득세", period, _workday(dt.date(nxt, 4, 30)), None if unknown else local, "예상",
                      "법인세 산출세액 %s × 10%%%s" % ("{:,}".format(corp), (" = %s − 원천징수된 지방소득세 %s" % ("{:,}".format(local_tax), "{:,}".format(local_prepaid))) if local_prepaid else "")), 과세표준="", 산출세액="", 기납부="", 대손충당금="", 세무조정="")]
    rest = None if unknown else rest_rows(by_month, ym, dep, base, nat, corp, year, input_dir, prepaid, local_prepaid)
    if rest:
        rows += rest
    return rows, "법인세 %s → %s원 (%s %s − 선납 %s), 지방소득세 %s원" % (period, "{:,}".format(pay), "감면 뒤" if C else "산출", "{:,}".format(nat),
                                                                 "{:,}".format(prepaid), "{:,}".format(local))


def rest_rows(by_month, ym, dep, base, nat, corp, year, input_dir, prepaid=0, local_prepaid=0):
    """E1 (결정 카드 2026-11-17 '더하기(따로 한 줄)'): 올해 남은 달(ym 다음 달~12월) 이익으로 더 낼 법인세·지방소득세 예상 줄.
    남은 달 이익 = 최근 끝난 3달 세전 이익 평균 × 남은 달 수 − 감가상각비 예상(연간 × 남은 달 ÷ 12). 0 이하이면 없음(세금을 줄이지 않음).
    더 낼 세금 = (지금까지 + 남은 달) 과세표준의 세금 − 지금까지 과세표준의 세금. 대상기간은 '(1월~' 으로 시작하지 않아 본 줄과 섞이지 않는다."""
    import datetime as dt
    from .tax import _row, _workday, REST_MARK
    m = int(ym[5:])
    left = 12 - m
    if left <= 0:
        return None
    recent = []
    for k in range(3):
        mm = m - k
        if mm >= 1 and "%s-%02d" % (year, mm) in by_month:
            recent.append(by_month["%s-%02d" % (year, mm)])
    if not recent:
        return None
    avg = sum(recent) / float(len(recent))
    dep_rest = int(round((dep.get("annual") or 0) * left / 12.0))
    extra = int(round(avg * left)) - dep_rest
    if extra <= 0:
        return None
    nat2, corp2, _ = national(base + extra, year, input_dir)
    more_nat = max(nat2 - prepaid, 0) - max(nat - prepaid, 0)
    more_local = max(int(corp2 * LOCAL_RATE) - local_prepaid, 0) - max(int(corp * LOCAL_RATE) - local_prepaid, 0)
    nxt = int(year) + 1
    period = "%s년 %d~12월%s" % (year, m + 1, REST_MARK)
    why = ("남은 %d달 이익 %s = 최근 %d달 세전 이익 평균 %s × %d − 감가상각비 예상 %s → 과세표준 %s → %s (지금까지 기준과의 차이). 12월 결산 전 어림"
           % (left, "{:,}".format(extra), len(recent), "{:,}".format(int(avg)), left, "{:,}".format(dep_rest),
              "{:,}".format(base + extra), "{:,}".format(nat2)))
    out = []
    if more_nat > 0:
        out.append(_row("법인세", period, _workday(dt.date(nxt, 3, 31)), more_nat, "예상", why))
    if more_local > 0:
        out.append(_row("법인지방소득세", period, _workday(dt.date(nxt, 4, 30)), more_local, "예상",
                        "남은 달 이익으로 늘어나는 법인세 산출세액 %s × 10%%" % "{:,}".format(corp2 - corp)))
    return out or None


# ───────────── 분납 (A4, 2026-11-17 사용자 '추가 기능은 전부') ─────────────
INST_MIN, INST_HALF = 10_000_000, 20_000_000   # 법인세법 64조②·시행령 101조②: 1천만 넘으면 분납, 2천만 이하면 1천만 넘는 몫, 넘으면 절반까지
INST_MONTHS = 2                                 # 중소기업은 납부기한 지난 날부터 2개월 (일반 1개월)


def installable(total):
    """낼 법인세 total 중 분납할 수 있는 가장 큰 금액 (없으면 0)."""
    if total is None or total <= INST_MIN:
        return 0
    return total - INST_MIN if total <= INST_HALF else total // 2


def inst_due(due):
    """분납 기한: 납부기한 + 2개월 (주말이면 다음 평일)."""
    import datetime as dt
    from .tax import _workday
    y, m = due.year, due.month + INST_MONTHS
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    last = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day
    return _workday(dt.date(y, m, min(due.day if due.day < 28 else last, last)))


def installment(rows, on):
    """회사가 분납을 골랐으면(on) 같은 날 낼 법인세 줄(본 줄 + 남은 달 예상 줄)을 합쳐 분납할 몫을 본 줄 '분납' 칸에 적는다.
    금액 칸은 그대로(전체 세금) — 자금 일정(tax.merge)만 본 줄을 두 번(기한·2달 뒤)으로 나눈다. 지방소득세·중간예납은 나누지 않음."""
    for r in rows:
        r.setdefault("분납", "")
    if not on:
        return rows
    by_due = {}
    for r in rows:
        if r.get("세목") == "법인세" and r.get("납부예정일") and str(r.get("납부예정일"))[5:7] in ("03", "04") and r.get("금액") not in ("", None):
            by_due.setdefault(r["납부예정일"], []).append(r)
    for due, rs in by_due.items():
        total = sum(int(r["금액"]) for r in rs)
        s = installable(total)
        main = next((r for r in rs if "(1월~" in str(r.get("대상기간")) or "(신고서)" in str(r.get("대상기간"))), rs[0])
        if s:
            main["분납"] = str(s)
            main["근거"] = (main.get("근거") or "") + " · 분납함(회사 선택): %s원은 %s에 (법인세법 64조, 중소기업 2개월)" % (
                "{:,}".format(s), inst_due(__import__("datetime").date.fromisoformat(due)).isoformat())
    return rows


# ───────────── 작년분 법인세·지방소득세, 8/31 중간예납 (2026-11-14 F5) ─────────────
INTERIM_MIN = 500_000   # 중소기업은 중간예납세액이 50만 원 미만이면 내지 않는다 (법인세법 63조)


def _bank_tax_slips(journal, start, end, prepaid_codes):
    """start~end 사이 통장에서 낸 법인세 쪽 전표 -> [(선납세금인가, 금액)].
    선납세금 코드 차변, 또는 계정 이름에 '법인세'·'지방소득세'가 있는 차변(미지급법인세·법인세등)의 합. 같은 전표에 통장 대변이 있을 때만."""
    from .convert_pl import _squash
    from .tax import _from_bank
    slips = {}
    for ln in journal:
        if ln.get("date") is not None and start <= ln["date"] <= end:
            slips.setdefault((ln["date"], ln.get("no")), []).append(ln)
    out = []
    for lines in slips.values():
        if not _from_bank(lines):
            continue
        pre = sum((x.get("debit") or 0) for x in lines if _squash(x["account_code"]) in prepaid_codes)
        tax = sum((x.get("debit") or 0) for x in lines if _squash(x["account_code"]) not in prepaid_codes
                  and ("법인세" in _squash(x["account"]) or "지방소득세" in _squash(x["account"])))
        out += [(True, pre)] * bool(pre) + [(False, tax)] * bool(tax)
    return out


def _paid(slips, amount, prepaid=False):
    """금액이 거의 같은 납부 전표가 있나 (반~1.5배: 법인세와 지방소득세(약 1/10)를 금액으로 가른다)."""
    return bool(amount) and any(p == prepaid and 0.5 * amount <= v <= 1.5 * amount for p, v in slips)


def carry_rows(journal, cfg, asof, manual=None, input_dir=None, wehago_dir=None):
    """-> 세금예상 줄 목록 (2026-11-14 F5: 1/31부터 작년 법인세·지방소득세 줄이 사라지고 8/31 중간예납이 일정에 없던 것).

    · 작년분: from_journal 이 올해를 계산하기 시작하는 1월 말부터 납부일(법인세 3/31·지방소득세 4/30)까지 남긴다.
      작년 신고서(법인세신고.csv '확정')가 있으면 그 금액(차감납부세액 + 농어촌특별세, 지방소득세), 없으면 작년 1~12월 장부로 같은 계산.
      신고서에 실제납부가 적혔거나 올해 통장에서 거의 같은 금액을 낸 전표가 있으면 뺀다.
    · 중간예납: 올해 8/31(토·일이면 월요일)까지. (작년 총부담세액 − 원천징수 등) × 6/12, 50만 원 미만이면 없음.
      올해 7/1 뒤 통장에서 선납세금으로 거의 같은 금액을 냈으면 뺀다."""
    import datetime as dt
    from .convert_pl import _squash
    from .tax import _row, _workday
    from . import taxreturn
    Y = asof.year
    prepaid_codes = set(_squash(c) for c in cfg.get("prepaid_tax_codes", PREPAID_CODES))
    paid = _bank_tax_slips(journal, dt.date(Y, 1, 1), asof, prepaid_codes)
    D = taxreturn.load(input_dir) if input_dir else {}
    last, last_mid = D.get((Y - 1, "확정")), D.get((Y - 1, "중간예납"))
    prev = None   # 작년 1~12월 장부로 한 계산 (신고서가 없을 때)
    if any(ln.get("date") is not None and ln["date"].year == Y - 1 for ln in journal):
        prev, _ = from_journal(journal, cfg, dt.date(Y - 1, 12, 31), manual, input_dir, wehago_dir)
    rows = []
    if int(_last_full_month(asof)[:4]) == Y:   # 1월 30일까지는 from_journal 이 작년분을 낸다
        if last and last.get("차감납부세액") is not None:
            period = "%d년 (신고서)" % (Y - 1)
            nat_amt = last["차감납부세액"] + (last.get("농특세") or 0)
            items = [("법인세", 3, 31, None if last.get("실제납부") is not None else nat_amt,
                      "%d년 법인세 신고서: 차감납부세액 %s + 농어촌특별세 %s" % (Y - 1, "{:,}".format(last["차감납부세액"]),
                                                                    "{:,}".format(last.get("농특세") or 0)), "확정(신고서)"),
                     ("법인지방소득세", 4, 30, last.get("지방소득세"), "%d년 법인세 신고서 지방소득세" % (Y - 1), "확정(신고서)")]
        elif prev:
            period = prev[0]["대상기간"]
            items = [(r["세목"], 3 if r["세목"] == "법인세" else 4, 31 if r["세목"] == "법인세" else 30,
                      None if r["금액"] == "" else int(r["금액"]), r["근거"], r["상태"]) for r in prev]
        else:
            items = []
        for kind, m, day, amount, basis, state in items:
            due = _workday(dt.date(Y, m, day))
            if due < asof or amount is None or _paid(paid, amount):
                continue
            row = _row(kind, period, due, amount, state, basis)
            if kind == "법인세" and prev and not last:
                row.update(dict((k, prev[0].get(k, "")) for k in ("과세표준", "산출세액", "기납부", "대손충당금", "세무조정")))
            rows.append(row)
    # 중간예납 (설립 다음 해부터, 작년 법인세의 절반)
    due = _workday(dt.date(Y, 8, 31))
    if asof <= due:
        base_tax = how = None
        if last and last.get("총부담세액") is not None:
            w = max((last.get("기납부세액") or 0) - ((last_mid or {}).get("차감납부세액") or 0), 0)
            base_tax = last["총부담세액"] - w
            how = "%d년 신고서 총부담세액 %s − 원천징수 등 %s" % (Y - 1, "{:,}".format(last["총부담세액"]), "{:,}".format(w))
        elif prev and prev[0].get("과세표준"):
            nat, corp, C = national(int(prev[0]["과세표준"]), str(Y - 1), input_dir)
            total = C["final"] if C else corp
            mid_prev = sum(v for p, v in _bank_tax_slips(journal, dt.date(Y - 1, 7, 1), dt.date(Y - 1, 12, 31), prepaid_codes) if p)
            w = max(int(prev[0].get("기납부") or 0) - mid_prev, 0)
            base_tax = total - w
            how = "%d년 장부로 계산한 법인세 %s − 원천징수 등 %s" % (Y - 1, "{:,}".format(total), "{:,}".format(w))
        amount = None if base_tax is None else int(base_tax * 6 / 12)
        if amount and amount >= INTERIM_MIN and not _paid(_bank_tax_slips(journal, dt.date(Y, 7, 1), asof, prepaid_codes), amount, True):
            rows.append(_row("법인세", "%d년 중간예납" % Y, due, amount, "예상", how + " × 6/12 (50만 원 미만이면 안 냄)"))
    return rows
