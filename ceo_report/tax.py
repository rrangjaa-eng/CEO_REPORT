"""세금 납부 예상 (사용자 2026-11-03): 분개장으로 부가세·원천세 납부액을 미리 계산한다.

사용자 규칙: 세금은 금액이 확정되면 일반전표에 넣고 자금계획(서)에 넣는다. 그래서
  · 확정 전에는 이 계산값을 자금 일정에 '예상'으로 넣고,
  · 자금계획서·자금일정에 그 세금이 이미 있으면(납부일 근처·이름) 계산값은 넣지 않고 비교만 한다 (두 번 빼지 않음).

부가세: 분기(1~3·4~6·7~9·10~12월)마다 부가세예수금(대변−차변) − 부가세대급금(차변−대변). 앞 분기분 납부 전표
       (예수금 차변 / 보통예금·미지급비용 대변)는 빼고, 그 전표가 생기면 확정 금액으로 쓴다. 납부일 = 분기 다음 달 25일.
4대보험: social() 참고 (직원분 예수금 + 회사분, 다음 달 10일).
원천세: 예수금 중 거래처가 세무서·구청(소득세·지방소득세)인 줄의 대변 합계 (차변은 앞 기간분 납부). 납부 방식은 지난 납부 달로 정한다
       (납부가 1월·7월에만 있으면 반기납부: 1~6월분 7/10, 7~12월분 다음 해 1/10. 아니면 매월: 다음 달 10일).
납부일이 쉬는 날(토·일·공휴일)이면 다음 영업일로 미룬다 (2026-11-14 F17, 공휴일 표 없는 해는 근거에 적음). 모르는 금액은 None 이고 0으로 치지 않는다.
"""
import calendar
import os
import datetime as dt
import re

COLUMNS = ["세목", "대상기간", "납부예정일", "금액", "상태", "근거", "과세표준", "산출세액", "기납부", "대손충당금", "세무조정",
           "거래처코드", "장부기준일"]
# 과세표준~세무조정 다섯 칸은 법인세 줄만 (2026-11-04, 대손충당금 11-12, 세무조정 11-14).
# 거래처코드 (2026-11-14 사용자 "이름으로 맞추지 말고 코드로"): 이 줄을 계산한 장부 줄의 거래처코드(앞 0 뗌, 여럿이면 띄어 씀).
#   보고서는 자금계획서·자금일정 줄과 이 코드가 같아야 같은 지급으로 본다 (코드가 없는 옛 줄만 이름·금액으로, '이름으로 맞춤' 표시).
# 장부기준일 (2026-11-14 F3): 계산에 쓴 분개장의 마지막 날짜. 납부일이 지났는데 장부에 납부가 없으면, 장부가 납부일을 덮을 때만
#   '안 냄'으로 보고 다음 금요일에 넣는다 (덮지 못하면 통장 잔액 기준일로 판단 — 자금계획서 줄과 같은 규칙).
LOOKBACK_DAYS = 45      # 납부일이 이만큼 안에 지난 줄은 장부에 납부가 없으면 지우지 않고 남긴다 (F3)
AHEAD_MONTHS = 7        # 급여·4대보험·원천세 예상 줄을 기준일 달부터 이만큼 앞까지 만든다 (월간 보고 6달 + 그 뒤 떼는 달, F4)
FILE = "세금예상.csv"


def _sq(text):
    return re.sub(r"\s+", "", str(text or ""))


def _workday(d):
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d


def _net(ln, credit_side):
    d, c = ln.get("debit"), ln.get("credit")
    if d is None and c is None:
        return None
    return (c or 0) - (d or 0) if credit_side else (d or 0) - (c or 0)


def _quarter(d):
    q = (d.month - 1) // 3
    start = dt.date(d.year, q * 3 + 1, 1)
    end = (dt.date(d.year + (1 if q == 3 else 0), 1 if q == 3 else q * 3 + 4, 1) - dt.timedelta(days=1))
    return start, end


def _code(c):
    from .wehago import norm_code
    return norm_code(c)


def _codes(lines):
    """장부 줄들의 거래처코드 (앞 0 뗌, 빈 것 뺌) -> 정렬된 튜플."""
    return tuple(sorted(set(_code(x.get("vendor_code")) for x in lines if _code(x.get("vendor_code")))))


def _last(journal):
    dated = [ln["date"] for ln in journal if ln.get("date") is not None]
    return max(dated) if dated else None


def _stamp(rows, journal):
    """줄마다 계산에 쓴 장부의 마지막 날짜 (F3: 지난 납부일을 장부가 덮었나 보고서가 판단)."""
    last = _last(journal)
    for r in rows:
        r["장부기준일"] = last.isoformat() if last else ""
        y = int(r["납부예정일"][:4]) if r.get("납부예정일") else None
        if y and y not in HOLIDAY_YEARS:   # F17: 공휴일 표가 없는 해는 주말만 보고 날짜를 정했다고 알린다
            r["근거"] += " · 공휴일 표에 %d년 없음 (주말만 봄)" % y
    return rows


def _recent(due, asof):
    """납부일이 기준일 뒤이거나, 지났어도 LOOKBACK_DAYS 안이면 줄을 만든다 (지난 줄은 장부에 납부가 없을 때만 남는다, F3)."""
    return due > asof - dt.timedelta(days=LOOKBACK_DAYS)


def vat(journal, asof, out_codes=("25500",), in_codes=("13500",)):
    """기준일에 아직 납부일이 오지 않은 분기의 부가세 -> [{세목, 대상기간, 납부예정일, 금액, 상태, 근거}].

    분기 금액 = 그 분기 줄의 부가세예수금(대변−차변) − 부가세대급금(차변−대변). 분기말 상계 전표(예수금 차변·대급금 대변)는
    둘이 같이 빠져 결과가 같다. 납부 전표(예수금 차변인데 같은 전표에 대급금도 매출 계정도 없는 것: 보통예금·미지급비용 대변)는
    앞 분기분 납부라 빼고, 분기말 뒤 ~ 납부일 사이에 있으면 그 분기 확정 금액으로 쓴다."""
    out_codes, in_codes = set(map(_sq, out_codes)), set(map(_sq, in_codes))
    slips = {}
    for ln in journal:
        slips.setdefault((ln["date"], ln.get("no")), []).append(ln)

    def is_payment(lines):
        codes = [_sq(x["account_code"]) for x in lines]
        return (any(_sq(x["account_code"]) in out_codes and (x.get("debit") or 0) for x in lines)
                and not any(c in in_codes for c in codes) and not any(c.startswith("4") for c in codes))
    payments = set(k for k, lines in slips.items() if k[0] is not None and is_payment(lines))

    def is_offset_settle(lines):   # 한 전표 정리: 예수금 차변 / 대급금 대변 / 미지급세금(또는 통장) 대변 (2026-11-03 검토)
        return (any(_sq(x["account_code"]) in out_codes and (x.get("debit") or 0) for x in lines)
                and any(_sq(x["account_code"]) in in_codes and (x.get("credit") or 0) for x in lines)
                and any(_sq(x["account_code"]) not in out_codes | in_codes and (x.get("credit") or 0) for x in lines)
                and not any(_sq(x["account_code"]).startswith("4") for x in lines))
    for k, lines in slips.items():
        if k[0] is not None and k not in payments and is_offset_settle(lines):
            payments.add(k)
    cash = set(k for k in payments if _from_bank(slips[k]))   # 통장에서 바로 낸 것 (미지급비용으로 잡은 것은 아직 안 나감)

    def payable_of(lines):   # 납부 금액 = 예수금·대급금이 아닌 계정 대변 (미지급세금·통장)
        return sum((x.get("credit") or 0) for x in lines if _sq(x["account_code"]) not in out_codes | in_codes)

    def cleared(key):   # 미지급으로 잡은 납부액을 그 뒤 기준일까지 통장에서 갚았나 (2026-11-03 검토: 두 번 빠지지 않게)
        acc = set(_sq(x["account_code"]) for x in slips[key]
                  if _sq(x["account_code"]) not in out_codes | in_codes and (x.get("credit") or 0))
        mine = _codes([x for x in slips[key] if _sq(x["account_code"]) in acc])
        amt = payable_of(slips[key])
        for k2, lines in slips.items():
            if k2[0] is None or k2 == key or not (key[0] <= k2[0] <= asof) or not _from_bank(lines):
                continue
            # 거래처코드가 양쪽에 있으면 같은 거래처(세무서)를 갚은 것만 (F18 ④: 금액만 보고 다른 미지급 지급을 부가세 납부로 보지 않게)
            hit = [x for x in lines if _sq(x["account_code"]) in acc and (x.get("debit") or 0)
                   and not (mine and _code(x.get("vendor_code")) and _code(x.get("vendor_code")) not in mine)]
            if sum(x["debit"] for x in hit) >= amt > 0:
                return True
        return False
    # 부가세 줄의 거래처코드 = 납부·미지급 전표의 통장 아닌 줄과 세무서 거래처 줄의 코드 (자금계획서 세무서 줄과 코드로 맞춘다)
    codes = _codes([x for k in payments for x in slips[k] if not _sq(x["account_code"]).startswith(BANK_PREFIX)]
                   + [x for x in journal if "세무서" in _sq(x.get("vendor"))])
    dated = [ln["date"] for ln in journal if ln["date"] is not None]
    if not dated:
        return []
    last = max(dated)
    starts = sorted(set(_quarter(ln["date"])[0] for ln in journal
                        if ln["date"] is not None and _sq(ln["account_code"]) in out_codes | in_codes))
    rows = []
    for start in starts:
        q_start, q_end = _quarter(start)
        due = _after(dt.date(q_end.year + (1 if q_end.month == 12 else 0), 1 if q_end.month == 12 else q_end.month + 1, 25))
        if not _recent(due, asof):
            continue
        total, unknown, settled, paid = 0, 0, None, False
        for key, lines in slips.items():
            day = key[0]
            if day is None:
                continue
            if key in payments:
                inside = q_start <= day <= q_end and is_offset_settle(lines)   # 분기 안 한 전표 정리
                if q_end < day <= max(due, asof) or inside:   # 이 분기분 납부(또는 미지급 계상) 전표: 확정 금액 (납부일 뒤 늦은 납부 포함, F3)
                    settled = (settled or 0) + payable_of(lines)
                    paid = paid or (day <= asof and (key in cash or cleared(key)))
                continue
            if not q_start <= day <= q_end:
                continue
            for x in lines:
                code = _sq(x["account_code"])
                if code not in out_codes | in_codes:
                    continue
                v = _net(x, credit_side=code in out_codes)
                if v is None:
                    unknown += 1
                    continue
                total += v if code in out_codes else -v
        period = "%d년 %d분기 (%d~%d월)" % (q_start.year, (q_start.month - 1) // 3 + 1, q_start.month, q_end.month)
        if paid:   # 납부일 전에 이미 통장에서 나감: 잔액에 반영돼 있으니 다시 넣지 않는다
            continue
        if settled is not None:
            rows.append(_row("부가세", period, due, settled, "확정(전표)", "납부·미지급 전표 (부가세예수금 차변)", codes))
            continue
        basis = "부가세예수금 − 부가세대급금 (앞 분기 납부 전표 제외)"
        if last < q_end:
            basis += ", %s까지 쌓인 금액 (남은 기간분은 더 늘어남)" % last.isoformat()
        rows.append(_row("부가세", period, due, None if unknown else total, "예상",
                         basis + (" · 금액 없는 줄 %d건" % unknown if unknown else ""), codes))
    return _stamp(rows, journal)


def withholding(journal, asof, codes=("25400",), vendors=("세무서", "구청", "시청", "군청"), mode="자동"):
    """원천세(소득세·지방소득세) 납부 예상 -> 행 목록. mode: 자동 | 반기 | 매월."""
    codes = set(map(_sq, codes))
    mine = [ln for ln in journal if ln["date"] is not None and _sq(ln["account_code"]) in codes
            and any(v in _sq(ln.get("vendor")) for v in vendors)]
    if not mine:
        return []
    paid = sorted(set(ln["date"] for ln in mine if (ln.get("debit") or 0) > 0))
    if mode == "자동":
        latest = [d for d in paid if d.year == max(p.year for p in paid)] if paid else []
        mode = "반기" if latest and all(d.month in (1, 7) for d in latest) else "매월"
    last = max(ln["date"] for ln in mine)
    vcodes = _codes(mine)
    until = dt.date(*_next_month(asof.year, asof.month, AHEAD_MONTHS), 1)   # 이 달 전까지의 기간을 만든다 (F4)
    periods = []
    if mode == "반기":
        for year in range(min(ln["date"].year for ln in mine), until.year + 1):
            for h in (1, 2):
                start = dt.date(year, 1 if h == 1 else 7, 1)
                end = dt.date(year, 6, 30) if h == 1 else dt.date(year, 12, 31)
                due = _after(dt.date(year + (1 if h == 2 else 0), 1 if h == 2 else 7, 10))
                if start < until:
                    periods.append(("%d년 %s반기 (%d~%d월)" % (year, "상" if h == 1 else "하", start.month, end.month), start, end, due))
    else:
        y, m = min((ln["date"].year, ln["date"].month) for ln in mine)
        while dt.date(y, m, 1) < until:
            start = dt.date(y, m, 1)
            end = (dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1) - dt.timedelta(days=1))
            due = _after(dt.date(end.year + (end.month == 12), 1 if end.month == 12 else end.month + 1, 10))
            periods.append(("%d년 %d월분" % (y, m), start, end, due))
            y, m = _next_month(y, m)
    # 달마다 뗀 금액 (대변) — 아직 급여 전표가 없는 달은 최근 달 금액으로 예상 (F4: 전표 전 달의 원천세 줄이 없던 것)
    by_month = {}
    for ln in mine:
        if ln.get("credit") is not None:
            k = (ln["date"].year, ln["date"].month)
            by_month[k] = by_month.get(k, 0) + ln["credit"]
    filled = sorted(k for k, v in by_month.items() if v)
    recent = by_month[filled[-1]] if filled else None
    rows = []
    for label, start, end, due in periods:
        if not _recent(due, asof):
            continue
        if any(end < ln["date"] <= asof and (ln.get("debit") or 0) > 0 for ln in mine):
            continue   # 이 기간분을 이미 냄 (납부일 뒤 늦게 낸 것도 포함 — 잔액에 반영됨)
        lines = [ln for ln in mine if start <= ln["date"] <= end]
        # 떼어 둔 금액(대변)만 더한다. 차변은 앞 기간분 납부라 이 기간에 넣지 않는다 (반기납부 7월 납부가 하반기에 섞이지 않게)
        vals = [ln.get("credit") for ln in lines if ln.get("credit") is not None or ln.get("debit") is None]
        unknown = sum(1 for v in vals if v is None)
        got = sum(v for v in vals if v is not None)
        basis = "예수금 중 %s 거래처 대변 합계, %s납부" % ("·".join(vendors[:2]), "반기" if mode == "반기" else "매월 ")
        # 기간 안에서 아직 급여 전표가 없는 달 (마지막으로 뗀 달 뒤): 최근 달 금액으로 채운다
        ahead = [(yy, mm) for (yy, mm) in _months(start, end) if filled and (yy, mm) > filled[-1]]
        if not got and not unknown and not ahead:
            continue   # 이 기간에 뗀 금액도, 앞으로 뗄 달도 없음 (앞 기간분 납부 줄만 있음)
        if ahead and recent:
            got += recent * len(ahead)
            basis += ("%s 급여 전표 전 %d달은 %d-%02d 금액 %s원으로 봄"
                      % (", " if vals else " — ", len(ahead), filled[-1][0], filled[-1][1], "{:,}".format(recent)))
        elif last < end:
            basis += ", %s까지 쌓인 금액" % last.isoformat()
        rows.append(_row("원천세", label, due, None if unknown else got, "예상", basis, vcodes))
    return _stamp(rows, journal)


def _months(start, end):
    y, m = start.year, start.month
    out = []
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        y, m = _next_month(y, m)
    return out


BANK_PREFIX = ("101", "102", "103")   # 현금·당좌예금·보통예금


def _from_bank(lines):
    return any(_sq(x["account_code"]).startswith(BANK_PREFIX) and (x.get("credit") or 0) for x in lines)


ACCRUED = ("262", "253")   # 미지급비용·미지급금
INSURERS = ("국민연금", "건강보험", "근로복지", "고용보험")


def social(journal, asof, codes=("25400",), vendors=INSURERS):
    """4대보험 납부 예상 (사용자 2026-11-03). 달마다 급여에서 뗀 직원분(예수금 대변, 공단 거래처)과 회사 부담분을 다음 달 10일에 낸다.

    회사분은 장부에 미리 잡지 않고 납부일에 비용(복리후생비·세금과공과·보험료)으로 처리하므로, 직전 납부 전표의
    회사분(비용 차변) ÷ 직원분(예수금 차변) 비율로 추정한다. 지난 납부가 없으면 회사분 = 직원분.
    월말에 회사분을 일반전표(비용 / 미지급비용, 공단 거래처)로 넣었으면 추정 대신 그 금액을 쓰고 '확정(전표)'로 둔다.
    납부일 전에 그 달분 납부 전표(공단 거래처 예수금 차변)가 기준일까지 있으면 이미 나간 것이라 넣지 않는다."""
    codes = set(map(_sq, codes))
    ins = lambda ln: any(v in _sq(ln.get("vendor")) for v in vendors)
    mine = [ln for ln in journal if ln["date"] is not None and ins(ln)]
    withheld = [ln for ln in mine if _sq(ln["account_code"]) in codes]
    if not withheld:
        return []
    slips = {}
    for ln in journal:
        if ln["date"] is not None:
            slips.setdefault((ln["date"], ln.get("no")), []).append(ln)
    pays = []      # 납부 전표: (일자, 직원분, 회사분). 회사분 = 비용 차변 + 미지급비용·미지급금 차변 (월말에 미리 잡은 것을 지움)
    accrued = {}   # 월말 회사분 전표 (비용 차변, 통장 출금 없음, 예수금 차변 없음): (연, 월) -> 금액
    for (day, _), lines in sorted(slips.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        emp = sum((x.get("debit") or 0) for x in lines if ins(x) and _sq(x["account_code"]) in codes)
        cost = sum((x.get("debit") or 0) for x in lines if ins(x) and _sq(x["account_code"]).startswith("8"))
        if emp:
            accr = sum((x.get("debit") or 0) for x in lines if ins(x) and _sq(x["account_code"]).startswith(ACCRUED))
            pays.append((day, emp, cost + accr))
        elif cost and not _from_bank(lines):
            accrued[(day.year, day.month)] = accrued.get((day.year, day.month), 0) + cost
    rows = []
    vcodes = _codes(mine)
    recent = None   # 가장 최근 달 납부액 (직원분 + 회사분): 급여 전표 전 달을 채운다 (F4)
    for (y, m) in sorted(set((ln["date"].year, ln["date"].month) for ln in withheld)):
        start = dt.date(y, m, 1)
        end = dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1) - dt.timedelta(days=1)
        due = _after(dt.date(end.year + (end.month == 12), 1 if end.month == 12 else end.month + 1, 10))
        vals = [ln.get("credit") for ln in withheld if start <= ln["date"] <= end
                and (ln.get("credit") is not None or ln.get("debit") is None)]
        if not vals:
            continue
        before = [p for p in pays if p[0] <= asof]
        last = before[-1] if before else None
        state = "예상"
        if accrued.get((y, m)):
            ratio = None
            note = "회사분 %s원 (월말 전표)" % "{:,}".format(accrued[(y, m)])
            state = "확정(전표)"
        elif last and last[1]:
            ratio = last[2] / last[1]
            note = "회사분 = 직원분 × %.2f (%s 납부 비율)" % (ratio, last[0].isoformat())
        else:
            ratio, note = 1.0, "회사분은 직원분과 같게 봄 (지난 납부 없음)"
        unknown = any(v is None for v in vals)
        emp = sum(v for v in vals if v is not None)
        company = accrued[(y, m)] if ratio is None else int(round(emp * ratio))
        amount = None if unknown else emp + company
        if emp:
            recent = ((y, m), amount)
        if not _recent(due, asof):
            continue
        if any(end < day <= asof for day, _, _ in pays):
            continue   # 이 달분을 이미 냄 (납부일 뒤 늦게 낸 것 포함)
        rows.append(_row("4대보험", "%d년 %d월분" % (y, m), due, amount, state,
                         "예수금 중 공단 거래처 대변(직원분) %s원 + %s" % ("{:,}".format(emp), note), vcodes))
    # 급여 전표가 아직 없는 달: 최근 달 금액으로 예상 (F4: 12/10 4대보험 줄이 없던 것)
    credited = [ln["date"] for ln in withheld if ln.get("credit")]
    first = max(credited) if credited else max(ln["date"] for ln in withheld)
    y, m = _next_month(first.year, first.month)
    until = _next_month(asof.year, asof.month, AHEAD_MONTHS)
    while recent and recent[1] is not None and (y, m) < until:
        due = _after(dt.date(*_next_month(y, m), 10))
        end = dt.date(*_next_month(y, m), 1) - dt.timedelta(days=1)
        if _recent(due, asof) and not any(end < day <= asof for day, _, _ in pays):
            rows.append(_row("4대보험", "%d년 %d월분" % (y, m), due, recent[1], "예상",
                             "급여 전표 전 → %d-%02d 납부액(직원분+회사분)으로 봄" % recent[0], vcodes))
        y, m = _next_month(y, m)
    return _stamp(rows, journal)


# 공휴일 (대체공휴일 포함). 급여일을 앞당기고 카드 납부일을 미룰 때 쓴다. 해마다 달력을 보고 더한다 (주말은 따로 봄)
KR_HOLIDAYS = frozenset(dt.date(*d) for d in (
    (2026, 1, 1), (2026, 2, 16), (2026, 2, 17), (2026, 2, 18), (2026, 3, 2), (2026, 5, 5), (2026, 5, 25), (2026, 6, 3),
    (2026, 8, 17), (2026, 9, 24), (2026, 9, 25), (2026, 9, 28), (2026, 10, 5), (2026, 10, 9), (2026, 12, 25),
    (2027, 1, 1), (2027, 2, 8), (2027, 2, 9), (2027, 3, 1), (2027, 5, 5), (2027, 5, 13), (2027, 8, 16),
    (2027, 9, 14), (2027, 9, 15), (2027, 9, 16), (2027, 10, 4), (2027, 10, 11), (2027, 12, 27)))


HOLIDAY_YEARS = frozenset(d.year for d in KR_HOLIDAYS)


def _off(d):
    return d.weekday() >= 5 or d in KR_HOLIDAYS


def _before(d):
    """쉬는 날이면 그 전 영업일 (급여)."""
    while _off(d):
        d -= dt.timedelta(days=1)
    return d


def _after(d):
    """쉬는 날이면 다음 영업일 (카드 결제일)."""
    while _off(d):
        d += dt.timedelta(days=1)
    return d


def _next_month(y, m, k=1):
    m += k
    return y + (m - 1) // 12, (m - 1) % 12 + 1


def _day_in(y, m, day):
    return dt.date(y, m, min(day, calendar.monthrange(y, m)[1]))


def salary(journal, asof, salary_codes=("80200",), accrued_codes=("26200",), pay_day=5, months_ahead=AHEAD_MONTHS):
    """급여 지급 예상 (사용자 2026-11-03: 급여일은 다음 달 5일, 공휴일·주말이면 그 전 영업일).

    월말 급여 전표(급여 차변 / 예수금·미지급비용 대변)의 미지급비용 대변 = 통장으로 나가는 실지급액(세후). 원천세·4대보험은
    따로 들어가므로 겹치지 않는다. 전표가 있는 달은 '확정(전표)', 아직 없는 달은 직전 달 실지급액으로 '예상'
    (마지막 급여 전표 다음 달부터 기준일 달 + months_ahead 달까지, F4). 그 금액이 미지급비용 차변·통장 출금으로 이미 나갔으면 넣지 않는다.
    이미 나갔는지는 급여 전표 미지급비용 줄의 거래처코드로 본다 (F18 ④: 카드대금 등 다른 미지급비용 지급을 급여로 보지 않게).
    급여일이 지났는데 장부에 지급이 없으면 지우지 않고 남긴다 (F3, 보고서가 장부 기준일을 보고 다음 금요일로 옮김)."""
    salary_codes, accrued_codes = set(map(_sq, salary_codes)), set(map(_sq, accrued_codes))
    slips = {}
    for ln in journal:
        if ln["date"] is not None:
            slips.setdefault((ln["date"], ln.get("no")), []).append(ln)
    accr = {}   # (연, 월) -> (전표일, 실지급액)
    paid = []   # (일자, 금액, 거래처코드): 미지급비용 차변 + 통장 출금
    pay_lines = []
    for (day, _), lines in slips.items():
        codes = set(_sq(x["account_code"]) for x in lines)
        if codes & salary_codes and any((x.get("debit") or 0) for x in lines if _sq(x["account_code"]) in salary_codes):
            net = sum((x.get("credit") or 0) for x in lines if _sq(x["account_code"]) in accrued_codes)
            if net:
                k = (day.year, day.month)
                accr[k] = (max(day, accr[k][0]) if k in accr else day, (accr[k][1] if k in accr else 0) + net)
                pay_lines.extend(x for x in lines if _sq(x["account_code"]) in accrued_codes and (x.get("credit") or 0))
        elif _from_bank(lines):
            for x in lines:
                if _sq(x["account_code"]) in accrued_codes and (x.get("debit") or 0):
                    paid.append((day, x["debit"], _code(x.get("vendor_code"))))
    if not accr:
        return []
    scodes = _codes(pay_lines)

    def gone(after, amt):
        """after 뒤 기준일까지 이 급여를 낸 기록이 있나. 거래처코드를 알면 그 코드 줄의 합, 모르면 같은 금액 한 줄 (예전 규칙)."""
        lines = [(d, a, c) for d, a, c in paid if after < d <= asof]
        mine = [a for d, a, c in lines if scodes and c in scodes]
        if mine and (amt is None or sum(mine) >= amt):
            return True
        return amt is not None and any(a == amt for _, a, c in lines if not (scodes and c))   # 코드 없는 옛 줄만 금액으로
    rows = []
    last_amt = accr[max(accr)][1]
    until = _next_month(asof.year, asof.month, months_ahead)
    months, ym = set(accr), _next_month(*max(accr))
    while ym <= until:
        months.add(ym)
        ym = _next_month(*ym)
    for (y, m) in sorted(months):
        due = _before(_day_in(*_next_month(y, m), pay_day))
        if not _recent(due, asof):
            continue
        end = dt.date(*_next_month(y, m), 1) - dt.timedelta(days=1)
        if (y, m) in accr:
            day, amt = accr[(y, m)]
            if gone(day, amt):
                continue   # 이미 나감
            rows.append(_row("급여", "%d년 %d월분" % (y, m), due, amt, "확정(전표)", "월말 급여 전표 미지급비용(실지급액, 세후)", scodes))
        elif (y, m) > max(accr):
            if due <= asof and gone(end, None):
                continue   # 급여 전표는 아직인데 지급은 이미 나감
            rows.append(_row("급여", "%d년 %d월분" % (y, m), due, last_amt, "예상",
                             "직전 급여 전표(%d-%02d) 실지급액으로 봄" % max(accr), scodes))
    return _stamp(rows, journal)


CARD_PREFIX = re.compile(r"^(신한|롯데|비씨|BC|삼성|현대|국민|KB|하나|우리|농협|NH|씨티)[_\s-]")


CARD_FILE = "카드결제일.csv"
CARD_COLUMNS = ["카드사", "납부일", "기산일"]
# 사용자 2026-11-03: 신한 15일 · 롯데 14일 · 비씨 25일. 기산일(이용기간 시작일)은 모르니 1일(전월 1일~말일)로 두고 창에서 고친다
DEFAULT_CARDS = (("신한", 15, 1), ("롯데", 14, 1), ("비씨", 25, 1))


def _card_name(text):
    text = str(text or "").strip().replace("카드", "")
    return {"BC": "비씨", "KB": "국민", "NH": "농협"}.get(text.upper(), text)


def read_card_days(input_dir):
    """입력/카드결제일.csv -> ({카드사: (납부일, 기산일)}, 알림). 파일이 없으면 기본값. 틀린 줄은 빼고 알린다."""
    path = os.path.join(input_dir, CARD_FILE)
    if not os.path.exists(path):
        return dict((c, (p, s)) for c, p, s in DEFAULT_CARDS), [
            "%s 없음 → 기본값 %s (기산일 1일)" % (CARD_FILE, " · ".join("%s %d일" % (c, p) for c, p, _ in DEFAULT_CARDS))]
    from .util import Issues, read_csv
    info = {}
    rows, ok = read_csv(path, CARD_COLUMNS, Issues(), info)
    if not ok or info.get("missing"):
        return {}, ["%s 를 읽지 못함 (머리글: 카드사,납부일,기산일) → 카드대금은 날짜 없이 알리기만 함" % CARD_FILE]
    out, notes = {}, []
    for r in rows:
        co = _card_name(r.get("카드사"))
        pay, start = str(r.get("납부일") or "").strip().rstrip("일"), str(r.get("기산일") or "1").strip().rstrip("일") or "1"
        if not co:
            continue
        if not (pay.isdigit() and start.isdigit() and 1 <= int(pay) <= 31 and 1 <= int(start) <= 31):
            notes.append("%s %s 줄 날짜를 읽지 못함 (납부일·기산일은 1~31)" % (CARD_FILE, co))
            continue
        out[co] = (int(pay), int(start))
    return out, notes


def card_due(day, pay, start):
    """사용일 day 의 결제일. 이용기간은 기산일부터 다음 기산일 전날까지, 결제는 그 기간이 끝난 뒤 처음 오는 납부일
    (쉬는 날이면 다음 영업일). 예: 기산일 1일·납부일 15일 → 10월 사용은 11월 15일. 기산일 12일·납부일 25일 → 10/12~11/11 사용은 11월 25일."""
    nxt = _day_in(day.year, day.month, start)
    if nxt <= day:
        nxt = _day_in(*_next_month(day.year, day.month), start)
    end = nxt - dt.timedelta(days=1)
    due = _day_in(end.year, end.month, pay)
    if due <= end:
        due = _day_in(*_next_month(end.year, end.month), pay)
    return _after(due)


def cards(journal, asof, card_days, accrued_codes=("26200",)):
    """카드대금 납부 예상 (사용자 2026-11-03: 카드별 납부일과 기산일을 넣어 계산).

    미지급비용 중 거래처가 '카드사_끝번호'인 줄: 대변 = 사용, 차변 = 결제. 사용을 결제일별로 모으고 결제를 오래된 것부터 지운 뒤,
    남은 금액은 그 결제일에 나간다고 본다 (결제일이 이미 지났으면 다음 결제일로). card_days = {카드사: (납부일, 기산일)}.
    납부일을 모르는 카드사는 '납부일 확인 필요'(날짜 없음)로 돌려준다.

    사용자 2026-11-12 결정: 전표로 들어간 사용 − 결제는 갚을 금액이 정해진 것이므로 '확정(전표)' (여유 자금에서 뺌).
    전표 입력 전 판단은 카드 번호별로 한다: 그 카드의 아직 안 나간 결제분 사용이 그 카드 최근 3달 평균의 절반 미만이면
    평균과의 차이를 따로 '예상' 줄로 둔다 (일부 카드만 전표가 들어간 달도 빠진 카드만 채움)."""
    accrued_codes = set(map(_sq, accrued_codes))
    bank_slips = {(ln["date"], ln.get("no")) for ln in journal
                  if ln["date"] is not None and _sq(ln.get("account_code")).startswith(BANK_PREFIX)}
    use, pay, use_card, pay_card = {}, {}, {}, {}
    co_lines = {}   # 카드사 -> 그 카드사 미지급비용 줄 (거래처코드로 자금계획서 카드 줄과 맞춘다)
    for ln in journal:
        if ln["date"] is None or _sq(ln["account_code"]) not in accrued_codes:
            continue
        vendor = str(ln.get("vendor") or "").strip()
        m = CARD_PREFIX.match(vendor)
        if not m:
            continue
        co = _card_name(m.group(1))
        co_lines.setdefault(co, []).append(ln)
        if ln.get("credit"):
            use.setdefault(co, []).append((ln["date"], ln["credit"]))
            use_card.setdefault(co, {}).setdefault(vendor, []).append((ln["date"], ln["credit"]))
        if ln.get("debit"):
            if ln.get("no") and (ln["date"], ln.get("no")) not in bank_slips:
                # 통장이 없는 차변 = 결제가 아니라 앞서 넣은 임시 사용을 되돌린 대체 전표 (사용자 2026-11-12: 한도 증액 카드는
                # 은행 출금을 먼저 일반전표로 넣고 나중에 대체) → 그날 사용에서 뺀다
                use.setdefault(co, []).append((ln["date"], -ln["debit"]))
                use_card.setdefault(co, {}).setdefault(vendor, []).append((ln["date"], -ln["debit"]))
            else:
                pay[co] = pay.get(co, 0) + ln["debit"]
                pay_card.setdefault(co, {}).setdefault(vendor, []).append((ln["date"], ln["debit"]))
    rows = []
    for co in sorted(use):
        days = card_days.get(co)
        vcodes = _codes(co_lines.get(co, []))
        if not days:
            bal = sum(a for _, a in use[co]) - pay.get(co, 0)
            if bal > 0:
                rows.append(_row("카드대금", "%s카드 미결제 잔액" % co, None, bal, "납부일 확인 필요",
                                 "창의 '카드 납부일'에 %s 납부일·기산일을 넣으면 자금 일정에 들어감" % co, vcodes))
            continue
        # 바꾼 카드 (F15 ①, 실제 롯데_7344 → 7972): 같은 카드사의 다른 카드가 이 카드 마지막 사용 뒤에 처음 쓰이기 시작했으면
        # 이 카드는 더 쓰지 않는 카드다 → 평균으로 채우지 않는다 (새 카드 쪽이 같은 돈을 잡음)
        span = {}
        for card, items in use_card.get(co, {}).items():
            got_days = [d for d, a in items if a > 0]
            if got_days:
                span[card] = (min(got_days), max(got_days))
        retired = set(c for c, (_, last_use) in span.items()
                      if any(c2 != c and first > last_use for c2, (first, _) in span.items()))
        p, s = days
        by_bill = {}
        for d, a in use[co]:
            k = card_due(d, p, s)
            by_bill[k] = by_bill.get(k, 0) + a
        # 카드 전표는 한 달에 한 번 전월분을 한꺼번에 넣음 (사용자 2026-11-04) → 입력 전 카드는 최근 3달 평균으로 예상
        past_keys = [k for k in sorted(by_bill) if k < asof][-CARD_AVG_MONTHS:]
        fill = {}   # 결제일 -> [(카드, 입력된 것, 평균)]
        if len(past_keys) >= CARD_AVG_MONTHS:
            opens = _open_bills(asof, p, s)
            for card in sorted(use_card.get(co, {})):
                if card in retired:
                    continue
                cb = {}
                for d, a in use_card[co][card]:
                    k = card_due(d, p, s)
                    cb[k] = cb.get(k, 0) + a
                # 그 카드가 결제일에 실제로 갚아야 했던 금액 = 그 결제분까지 사용 − 이용기간 안에 미리 낸 것까지의 결제
                # (사용하는 대로 바로 갚는 한도 증액 카드는 0에 가까워 평균으로 채우지 않는다)
                dues = []
                for k in past_keys:
                    end = _period_end(k, s)
                    used = sum(a for kk, a in cb.items() if kk <= k)
                    paid = sum(a for d, a in pay_card.get(co, {}).get(card, []) if d <= end)
                    dues.append(max(0, used - paid))
                avg = sum(dues) // CARD_AVG_MONTHS
                if avg < CARD_MIN_AVG:   # 거의 안 쓰는 카드는 채우지 않는다 (사용자 2026-11-13: 다 넣었는데 경고)
                    continue
                for k in opens:
                    got = max(0, cb.get(k, 0))
                    # 이용기간이 끝난 결제분: 그 카드 사용 전표가 한 줄이라도 들어갔으면 그달 묶음은 넣은 것 (카드 전표는 전월분을
                    # 한꺼번에 넣음). 적게 쓴 달·카드를 바꾼 달을 '덜 들어감'으로 보지 않는다 (사용자 2026-11-13)
                    if _period_end(k, s) < asof and any(card_due(d, p, s) == k and a > 0 for d, a in use_card[co][card]):
                        continue
                    if got < avg * CARD_THIN_RATE:
                        fill.setdefault(k, []).append((card, got, avg))
        left = pay.get(co, 0)
        by_due = {}
        for k in sorted(by_bill):
            take = min(by_bill[k], left)
            left -= take
            if by_bill[k] - take <= 0:
                continue
            # 결제일이 지났는데 장부에 결제가 없는 금액은 그 결제일 그대로 둔다 (F3: 예전엔 다음 결제일로 미뤄 그 사이 돈이
            # 남아 보였다). 보고서가 장부 기준일을 보고 다음 금요일로 옮기거나 통장 잔액에 반영된 것으로 본다 (자금계획서 줄과 같은 규칙)
            due = k
            by_due[due] = by_due.get(due, 0) + by_bill[k] - take
        for due in sorted(set(by_due) | set(fill)):
            if by_due.get(due):
                rows.append(_row("카드대금", "%s카드 %d월 %d일 결제" % (co, due.month, due.day), due, by_due[due], "확정(전표)",
                                 "미지급비용 %s카드 사용 − 결제 (납부일 %d일, 기산일 %d일)" % (co, p, s), vcodes))
            if fill.get(due):
                extra = sum(a - g for _, g, a in fill[due])
                cards_txt = ", ".join("%s(입력 %s / 평균 %s)" % (c, "{:,}".format(g), "{:,}".format(a)) for c, g, a in fill[due])
                if _period_end(due, s) >= asof:
                    # 지금 쓰고 있는 이용기간: 전표는 다음 달 초에 넣는 것이 정상 → 경고가 아니라 미리 잡는 예상 (사용자 2026-11-13)
                    rows.append(_row("카드대금", "%s카드 %d월 %d일 결제 (이번 달 사용 추정)" % (co, due.month, due.day), due, extra, "예상",
                                     "%s %s카드 %s — 이용기간이 아직 끝나지 않아 전표는 다음 달 초에 들어옴. 그 카드 최근 %d달 평균과의 차이 %s원을 미리 잡음"
                                     % (CARD_OPEN_MARK, co, cards_txt, CARD_AVG_MONTHS, "{:,}".format(extra)), vcodes))
                    continue
                rows.append(_row("카드대금", "%s카드 %d월 %d일 결제 (전표 입력 전 추정)" % (co, due.month, due.day), due, extra, "예상",
                                 "%s %s카드 %s 사용 전표가 하나도 없음 → 그 카드 최근 %d달 평균과의 차이 %s원을 더 잡음 (전표를 넣으면 실제 금액으로 바뀜)"
                                 % (CARD_THIN_MARK, co, cards_txt, CARD_AVG_MONTHS, "{:,}".format(extra)), vcodes))
    return _stamp(rows, journal)


CARD_AVG_MONTHS = 3      # 입력 전 달을 채울 때 보는 지난 결제 수
CARD_THIN_RATE = 0.5     # 입력된 사용이 평균의 이 비율보다 적으면 '아직 입력 전'으로 봄
CARD_THIN_MARK = "카드 전표 입력 전:"
CARD_OPEN_MARK = "카드 이번 달 사용 추정:"   # 이용기간이 안 끝난 결제분 (경고 아님)
CARD_MIN_AVG = 100000    # 최근 3달 평균이 이보다 적은 카드는 평균으로 채우지 않음


def _period_end(bill, start):
    """결제일 bill 에 나가는 이용기간의 마지막 날 = bill 이전(같은 날 포함) 마지막 기산일의 전날."""
    b = _day_in(bill.year, bill.month, start)
    if b > bill:
        b = _day_in(*_next_month(bill.year, bill.month, -1), start)
    return b - dt.timedelta(days=1)


def _open_bills(asof, pay, start):
    """기준일에 이미 시작했지만 아직 안 나간 결제 (지난 이용기간 결제가 아직이면 그것, 그리고 지금 이용기간 결제)."""
    cur = card_due(asof, pay, start)
    begin = _day_in(asof.year, asof.month, start)
    if begin > asof:
        begin = _day_in(*_next_month(asof.year, asof.month, -1), start)
    prev = card_due(begin - dt.timedelta(days=1), pay, start)
    return [k for k in sorted({prev, cur}) if k >= asof]


DEPOSIT_IN = "정기예금 만기"
DEPOSIT_OUT = "정기예금 가입"


def _add_months(d, k):
    y, m = _next_month(d.year, d.month, k)
    return _day_in(y, m, d.day)


def deposits(journal, asof, codes=("10500",), words=("정기예금",)):
    """정기예금 가입·만기 (사용자 2026-11-03: 여유 자금으로 정기예금을 들고 일반전표에 넣음).

    가입 = 정기예금 계정 차변 + 통장 출금, 해지 = 정기예금 계정 대변 (적요·거래처에 '정기예금'이 있는 줄만: 공제부금 등은 뺀다).
    같은 금액의 해지가 뒤에 있으면 끝난 예금. 남은 예금의 만기 = 가입일 + 기간(달), 쉬는 날이면 다음 영업일.
    기간은 지난 예금의 가입→만기해지 간격(같은 금액 짝)에서 가장 흔한 달 수, 없으면 1개월.
    기준일 뒤 가입 전표는 그날 지급, 만기는 원금 입금으로 본다 (이자는 모르니 넣지 않음)."""
    codes = set(map(_sq, codes))

    def mine(x):
        return _sq(x["account_code"]) in codes and any(w in str(x.get("memo") or "") + str(x.get("vendor") or "") for w in words)
    put = sorted((x["date"], x["debit"]) for x in journal if x["date"] is not None and mine(x) and (x.get("debit") or 0) > 0)
    took = sorted((x["date"], x["credit"], "만기" in str(x.get("memo") or "")) for x in journal
                  if x["date"] is not None and mine(x) and (x.get("credit") or 0) > 0)
    open_, terms = [], []
    used = set()
    for d, a in put:
        hit = next((i for i, (d2, a2, _) in enumerate(took) if i not in used and d2 >= d and a2 == a), None)
        if hit is None:
            open_.append((d, a))
            continue
        used.add(hit)
        d2, _, matured = took[hit]
        if matured:
            terms.append(max(1, int(round((d2 - d).days / 30.4))))
    left = sum(a for i, (_, a, _) in enumerate(took) if i not in used)   # 짝 없는 해지: 오래된 예금부터 지운다
    still = []
    for d, a in open_:
        take = min(a, left)
        left -= take
        if a - take > 0:
            still.append((d, a - take))
    term = max(set(terms), key=lambda k: (terms.count(k), -k)) if terms else 1
    why = "지난 예금 %d건의 가입→만기 간격" % len(terms) if terms else "지난 만기 기록 없음 → 1개월로 봄"
    vcodes = _codes([x for x in journal if x["date"] is not None and mine(x)])
    rows = []
    for d, a in still:
        if d > asof:
            rows.append(_row(DEPOSIT_OUT, "%s 가입" % d.isoformat(), d, a, "확정(전표)", "정기예금 가입 전표 (통장에서 나감)", vcodes))
        due = _after(_add_months(d, term))
        note = "가입 %s + %d개월 (%s)" % (d.isoformat(), term, why)
        if due < asof:
            due, note = _after(asof), note + " — 만기가 지났는데 해지 전표 없음"
        rows.append(_row(DEPOSIT_IN, "%s 가입분" % d.isoformat(), due, a, "예상", "원금만 (이자 제외). " + note, vcodes))
    return _stamp(rows, journal)


def _row(kind, period, due, amount, state, basis, codes=()):
    return {"세목": kind, "대상기간": period, "납부예정일": due.isoformat() if due else "", "금액": "" if amount is None else str(amount),
            "상태": state, "근거": basis, "과세표준": "", "산출세액": "", "기납부": "", "대손충당금": "", "세무조정": "",
            "거래처코드": " ".join(codes or ()), "장부기준일": ""}


# ───────────── 보고서 쪽: 자금 일정에 넣기 ─────────────
KEYWORDS = {"부가세": ("부가",), "원천세": ("원천", "소득세", "지방소득"),
            "4대보험": ("4대보험", "사대보험", "국민연금", "건강보험", "고용보험", "산재", "근로복지", "공단"),
            "급여": ("급여", "월급", "임금", "인건비"), "카드대금": ("카드",), DEPOSIT_IN: ("정기예금", "예금"),
            DEPOSIT_OUT: ("정기예금", "예금"), "법인세": ("법인세",), "법인지방소득세": ("법인지방소득세", "법인지방")}
OFFICE = {"부가세": ("세무서",), "원천세": ("세무서", "구청", "시청", "군청"), "법인세": ("세무서",), "법인지방소득세": ("구청", "시청", "군청")}
NEAR_DAYS = 7


def _io(t):
    return "in" if t["kind"] == DEPOSIT_IN else "out"


NOT_TAX = ("남은 예산", "프로젝트집행", "계산서")


GAP_KINDS = ("부가세", "원천세", "법인세", "법인지방소득세")   # 장부 계산보다 작은 일정이면 차액을 넣는 세금 (카드는 명세서·결제 금액, 4대보험은 고지액이 우선)


def _next_friday(asof):
    return asof + dt.timedelta(days=(4 - asof.weekday()) % 7 or 7)


def _ev_code(ev):
    return _code(ev.get("vendor_code"))


def merge(events, taxes, asof=None, cash_date=None):
    """세금 예상을 일정에 넣는다. 이미 일정(자금계획서·자금일정 등)에 같은 세금이 있으면 넣지 않고 그 금액과 비교만 한다.

    같은 세금 = 지급, 납부일 ±7일, 그리고
      ⓪ 거래처코드: 세금 줄(장부 줄의 코드)과 일정 줄 코드가 같으면 같은 지급 (사용자 2026-11-14 "이름으로 맞추지 말고 코드로").
         코드가 같은 일정 줄이 여럿이면(소득세·지방소득세, 공단별 4대보험) 모두 이 세금으로 보고 합계를 비교한다.
      코드가 양쪽에 있는데 다르면 다른 지급이다 — 아래 이름·금액으로도 맞추지 않는다 (F18: 같은 날짜·금액 임차료가 세금에 흡수되던 것).
      코드가 한쪽이라도 없는 옛 줄만 ① 이름(분류·거래처·근거)에 세목 낱말 ② 거래처가 그 세목의 기관(세무서·구청) ③ 금액이 계산값과 같음
      순으로 맞추고 '이름으로 맞춤'(by_name)으로 표시한다. 세목마다 ①을 먼저 모두 찾고 ②·③은 남은 것에서 찾는다.

    asof 를 주면 (F3, 2026-11-14) 납부일이 기준일 이전인데 일정에 없는 줄(장부에 납부가 없어 tax.py 가 남긴 것)은
      · 장부가 납부일을 덮으면(장부기준일 ≥ 납부일) 안 낸 것 → 다음 금요일 지급,
      · 덮지 못하고 통장 잔액 기준일(cash_date)이 납부일 이후면 잔액에 이미 반영된 것 → 넣지 않음,
      · 둘 다 아니면 다음 금요일로 넣되 주간 출금 목록에는 싣지 않는다(gap) — 자금계획서 '예정일 지남' 줄과 같은 규칙.
    -> (새 일정, [세금 행 + {"matched": 일정 또는 None, "matched_all": [일정...], "diff": 일정 금액 − 계산값 또는 None,
                              "by_name": 이름·금액으로 맞췄으면 True, "moved": 옮긴 날짜 설명 또는 ""}])."""
    out = list(events)
    taxes = list(taxes or [])
    found = [None] * len(taxes)
    by_name = [False] * len(taxes)
    taken = set()

    def near(ev, t):
        if t["due"] is None:
            return False
        day = ev.get("orig_date") or ev["date"]   # 다음 금요일로 옮긴 자금계획서 줄은 원래 예정일로 견준다
        return ev["io"] == _io(t) and day is not None and abs((day - t["due"]).days) <= NEAR_DAYS

    def codes(t):
        return set(t.get("codes") or ())

    def conflict(ev, t):   # 코드가 양쪽에 있는데 다르면 다른 지급
        c = _ev_code(ev)
        return bool(c) and bool(codes(t)) and c not in codes(t)

    def text(ev):
        return _sq(" ".join(str(ev.get(k) or "") for k in ("cat", "desc", "basis")))

    def words(t):
        if t["kind"] == "카드대금":   # 카드사가 같아야 같은 카드대금 (롯데 결제를 신한 일정이 가져가지 않게)
            co = str(t.get("period") or "").split("카드")[0].strip()
            return (co,) if co else ()
        return KEYWORDS.get(t["kind"], ())

    def usable(i, ev):
        return i not in taken and ev.get("source") not in NOT_TAX   # 프로젝트 원가·남은 예산 줄은 세금이 아니다

    # ⓪ 거래처코드 (여러 줄이면 모두)
    for n, t in enumerate(taxes):
        if not codes(t):
            continue
        hit = [i for i, ev in enumerate(events) if usable(i, ev) and near(ev, t) and _ev_code(ev) in codes(t)]
        if hit:
            found[n] = [events[i] for i in hit]
            taken.update(hit)
    tests = (lambda ev, t: any(w in text(ev) for w in words(t)),
             lambda ev, t: any(w in text(ev) for w in OFFICE.get(t["kind"], ())),
             lambda ev, t: t["amount"] is not None and ev["amount"] == t["amount"])
    for test in tests:
        for n, t in enumerate(taxes):
            if found[n] is not None:
                continue
            for i, ev in enumerate(events):
                if usable(i, ev) and near(ev, t) and not conflict(ev, t) and test(ev, t):
                    found[n] = [ev]
                    by_name[n] = True
                    taken.add(i)
                    break
    # 같은 카드사·같은 결제일의 확정분과 전표 입력 전 추정분은 한 결제다: 하나가 일정(명세서 금액 등)과 맞으면 다른 것도 넣지 않는다
    card_hit = {(str(t.get("period") or "").split("카드")[0].strip(), t["due"]) for t, m in zip(taxes, found)
                if m is not None and t["kind"] == "카드대금"}
    info = []
    for t, hits, named in zip(taxes, found, by_name):
        if hits is None and t["kind"] == "카드대금" and (str(t.get("period") or "").split("카드")[0].strip(), t["due"]) in card_hit:
            info.append(dict(t, matched={"merged_card": True, "amount": None}, matched_all=[], diff=None, by_name=False, moved=""))
            continue
        match = hits[0] if hits else None
        amounts = [ev["amount"] for ev in hits or []]
        got = None if not hits or any(a is None for a in amounts) else sum(amounts)
        diff = None if got is None or t["amount"] is None else got - t["amount"]
        row = dict(t, matched=match, matched_all=list(hits or []), diff=diff, by_name=named, moved="")
        info.append(row)
        if diff is not None and diff < 0 and t["due"] is not None and t["kind"] in GAP_KINDS:
            # 일정 금액이 장부 계산보다 작으면 모자란 만큼도 일정에 넣는다 (2026-11-04 점검: 작은 일정 금액만 쓰고 차이가 안 보이던 것).
            # 지급을 줄이지 않는 쪽. ③ 부가세·원천세 표에 '장부 계산' 금액을 함께 보인다.
            out.append({"date": match["date"], "io": _io(t), "amount": -diff, "firm": False,
                        "cat": "%s (장부 계산 차액)" % t["kind"], "desc": "%s %s" % (t["kind"], t["period"]),
                        "basis": "장부 계산 %s원 − 일정 %s원" % ("{:,}".format(t["amount"]), "{:,}".format(got)),
                        "project": "", "source": "세금예상", "tax_gap": True})
        if match is None and t["due"] is not None and (t["amount"] is None or t["amount"] > 0):
            ev = {"date": t["due"], "io": _io(t), "amount": t["amount"], "firm": t["state"].startswith("확정"),
                  "cat": "%s (장부 계산)" % t["kind"], "desc": "%s %s" % (t["kind"], t["period"]), "basis": t["basis"],
                  "project": "", "source": "세금예상", "vendor_code": " ".join(sorted(codes(t)))}
            if asof is not None and t["due"] <= asof:
                book = t.get("book")
                if book is not None and book >= t["due"]:
                    why = "납부일 %s 지남, 장부(%s까지)에 %s 없음 → 다음 금요일" % (
                        t["due"].isoformat(), book.isoformat(), "입금" if _io(t) == "in" else "납부")
                elif cash_date is not None and cash_date >= t["due"]:
                    row["moved"] = "납부일 %s이 통장 잔액 기준일 %s 이전 → 잔액에 이미 반영된 것으로 봄 (장부는 %s까지)" % (
                        t["due"].isoformat(), cash_date.isoformat(), book.isoformat() if book else "날짜 모름")
                    continue
                else:
                    why = "납부일 %s 지남, 장부가 %s까지만 있어 냈는지 모름 → 다음 금요일 (이미 나갔으면 빼도 됨)" % (
                        t["due"].isoformat(), book.isoformat() if book else "언제")
                    ev["gap"] = t["due"]   # 주간 출금 목록에는 싣지 않고 따로 알린다 (자금계획서 줄과 같은 규칙)
                ev["date"] = _next_friday(asof)
                ev["orig_date"] = t["due"]
                ev["basis"] = (ev["basis"] + ", " if ev["basis"] else "") + why
                row["moved"] = why
            out.append(ev)
    return out, info
