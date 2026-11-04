"""법인세 예상 (사용자 2026-11-04): 올해 누적 세전 이익으로 법인세·지방소득세를 어림한다.

- 두 가지를 따로 낸다: 영업외 수익을 뺀 세전 이익 기준, 영업외 수익을 넣은 세전 이익 기준.
- 감가상각비는 장부에 12월 결산 때 한 번에 들어가므로(2025년 실제), 연간 예상을 결산 줄에서 비용으로 먼저 빼고 남은 것이 세전 이익.
  연간 감가상각비 = 대표보고 창 '⑨ 감가상각비'로 넣은 값(입력/감가상각비.csv), 없으면 작년 계정별비용의 감가상각비 합계.
  올해 이미 장부에 들어간 감가상각비는 세전 이익에 빠져 있으므로 그만큼은 다시 빼지 않는다.
- 세무조정(접대비 한도 등)·세액공제·감면·이월결손금·중간예납과 원천징수 선납세금은 반영하지 않는다 (어림값).
"""
import csv
import os

DEP_FILE = "감가상각비.csv"
DEP_COLUMNS = ["연도", "연간감가상각비"]

# 과세표준 구간 상한(원)과 세율. 2026년 1월 1일 이후 시작 사업연도부터 1%p 인상 (2025-12 국회 통과)
BRACKETS_2026 = ((200_000_000, 0.10), (20_000_000_000, 0.20), (300_000_000_000, 0.22), (None, 0.25))
BRACKETS_2023 = ((200_000_000, 0.09), (20_000_000_000, 0.19), (300_000_000_000, 0.21), (None, 0.24))
LOCAL_RATE = 0.10   # 법인지방소득세 = 법인세의 10%


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


def _int(text):
    t = str(text or "").replace(",", "").replace("원", "").strip()
    return int(t) if t.isdigit() else None


def read(input_dir):
    """-> {연도: 연간 감가상각비}. 없거나 읽지 못하면 {}."""
    path = os.path.join(input_dir, DEP_FILE)
    out = {}
    if not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                y, v = (r.get("연도") or "").strip(), _int(r.get("연간감가상각비"))
                if y.isdigit() and v is not None:
                    out[y] = v
    except (OSError, UnicodeDecodeError, csv.Error):
        return {}
    return out


def save(input_dir, year, amount):
    """한 해의 연간 감가상각비를 넣거나 고친다. 금액을 비우면 그 해 줄을 지운다 (작년 장부 값으로 돌아감). -> 줄 수."""
    y = str(year or "").strip()
    if not (y.isdigit() and len(y) == 4):
        raise ValueError("연도는 4자리 (예: 2026)")
    if not os.path.isdir(input_dir):
        raise ValueError("입력 폴더가 없습니다: %s" % input_dir)
    cur = read(input_dir)
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


# 누적에서 미리 뺄 감가상각비: 'prorate' = 연간 × 지난 달 수 ÷ 12, 'full' = 연간 전액 (사용자 2026-11-04 결정: full. 이번 달 표에는 넣지 않음)
DEP_MODE = "full"


def depreciation(accounts, manual, ym, mode=None):
    """-> {"annual", "source", "booked", "extra"(누적), "cur"(이번 달), "months"}. annual None = 모름 (extra·cur 도 None).

    감가상각비는 연말 결산 때 한 번에 들어가므로 작년 금액을 올해 예상으로 보고 비용으로 먼저 뺀다 (사용자 2026-11-04).
    올해 이미 장부에 들어간 감가상각비는 세전 이익에 빠져 있으므로 그만큼은 다시 빼지 않는다."""
    mode = mode or DEP_MODE
    year, months = ym[:4], int(ym[5:7])
    booked_rows = [r for r in _dep_rows(accounts, year) if r["ym"] <= ym]
    booked = sum(r["amount"] or 0 for r in booked_rows)
    booked_cur = sum(r["amount"] or 0 for r in booked_rows if r["ym"] == ym)
    if manual.get(year) is not None:
        annual, source = manual[year], "직접 입력"
    else:
        last = _dep_rows(accounts, int(year) - 1)
        annual = sum(r["amount"] or 0 for r in last) if last else None
        source = "작년 장부" if last else ""
    share = months if mode == "prorate" else 12
    extra = None if annual is None else max(int(round(annual * share / 12.0)) - booked, 0)
    cur = None if annual is None else max(int(round(annual / 12.0)) - booked_cur, 0) if mode == "prorate" else None
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
