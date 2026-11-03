"""세금 납부 예상 (사용자 2026-11-03): 분개장으로 부가세·원천세 납부액을 미리 계산한다.

사용자 규칙: 세금은 금액이 확정되면 일반전표에 넣고 자금계획(서)에 넣는다. 그래서
  · 확정 전에는 이 계산값을 자금 일정에 '예상'으로 넣고,
  · 자금계획서·자금일정에 그 세금이 이미 있으면(납부일 근처·이름) 계산값은 넣지 않고 비교만 한다 (두 번 빼지 않음).

부가세: 분기(1~3·4~6·7~9·10~12월)마다 부가세예수금(대변−차변) − 부가세대급금(차변−대변). 앞 분기분 납부 전표
       (예수금 차변 / 보통예금·미지급비용 대변)는 빼고, 그 전표가 생기면 확정 금액으로 쓴다. 납부일 = 분기 다음 달 25일.
4대보험: social() 참고 (직원분 예수금 + 회사분, 다음 달 10일).
원천세: 예수금 중 거래처가 세무서·구청(소득세·지방소득세)인 줄의 대변 합계 (차변은 앞 기간분 납부). 납부 방식은 지난 납부 달로 정한다
       (납부가 1월·7월에만 있으면 반기납부: 1~6월분 7/10, 7~12월분 다음 해 1/10. 아니면 매월: 다음 달 10일).
납부일이 토·일이면 월요일로 미룬다 (공휴일은 보지 않음). 모르는 금액은 None 이고 0으로 치지 않는다.
"""
import datetime as dt
import re

COLUMNS = ["세목", "대상기간", "납부예정일", "금액", "상태", "근거"]
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
    cash = set(k for k in payments if _from_bank(slips[k]))   # 통장에서 바로 낸 것 (미지급비용으로 잡은 것은 아직 안 나감)
    dated = [ln["date"] for ln in journal if ln["date"] is not None]
    if not dated:
        return []
    last = max(dated)
    starts = sorted(set(_quarter(ln["date"])[0] for ln in journal
                        if ln["date"] is not None and _sq(ln["account_code"]) in out_codes | in_codes))
    rows = []
    for start in starts:
        q_start, q_end = _quarter(start)
        due = _workday(dt.date(q_end.year + (1 if q_end.month == 12 else 0), 1 if q_end.month == 12 else q_end.month + 1, 25))
        if due <= asof:
            continue
        total, unknown, settled, paid = 0, 0, None, False
        for key, lines in slips.items():
            day = key[0]
            if day is None:
                continue
            if key in payments:
                if q_end < day <= due:   # 이 분기분 납부(또는 미지급 계상) 전표: 확정 금액
                    settled = (settled or 0) + sum((x.get("debit") or 0) for x in lines if _sq(x["account_code"]) in out_codes)
                    paid = paid or (key in cash and day <= asof)
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
            rows.append(_row("부가세", period, due, settled, "확정(전표)", "납부·미지급 전표 (부가세예수금 차변)"))
            continue
        basis = "부가세예수금 − 부가세대급금 (앞 분기 납부 전표 제외)"
        if last < q_end:
            basis += ", %s까지 쌓인 금액 (남은 기간분은 더 늘어남)" % last.isoformat()
        rows.append(_row("부가세", period, due, None if unknown else total, "예상",
                         basis + (" · 금액 없는 줄 %d건" % unknown if unknown else "")))
    return rows


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
    periods = []
    if mode == "반기":
        for year in sorted(set(ln["date"].year for ln in mine)):
            for h in (1, 2):
                start = dt.date(year, 1 if h == 1 else 7, 1)
                end = dt.date(year, 6, 30) if h == 1 else dt.date(year, 12, 31)
                due = _workday(dt.date(year + (1 if h == 2 else 0), 1 if h == 2 else 7, 10))
                periods.append(("%d년 %s반기 (%d~%d월)" % (year, "상" if h == 1 else "하", start.month, end.month), start, end, due))
    else:
        for (y, m) in sorted(set((ln["date"].year, ln["date"].month) for ln in mine)):
            start = dt.date(y, m, 1)
            end = (dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1) - dt.timedelta(days=1))
            due = _workday(dt.date(end.year + (end.month == 12), 1 if end.month == 12 else end.month + 1, 10))
            periods.append(("%d년 %d월분" % (y, m), start, end, due))
    rows = []
    for label, start, end, due in periods:
        if due <= asof:
            continue
        lines = [ln for ln in mine if start <= ln["date"] <= end]
        if not lines:
            continue
        if any(end < ln["date"] <= min(due, asof) and (ln.get("debit") or 0) > 0 for ln in mine):
            continue   # 이 기간분을 납부일 전에 이미 냄 (잔액에 반영됨)
        # 떼어 둔 금액(대변)만 더한다. 차변은 앞 기간분 납부라 이 기간에 넣지 않는다 (반기납부 7월 납부가 하반기에 섞이지 않게)
        vals = [ln.get("credit") for ln in lines if ln.get("credit") is not None or ln.get("debit") is None]
        if not vals:
            continue   # 이 기간에 뗀 금액이 없음 (앞 기간분 납부 줄만 있음)
        unknown = sum(1 for v in vals if v is None)
        basis = "예수금 중 %s 거래처 대변 합계, %s납부" % ("·".join(vendors[:2]), "반기" if mode == "반기" else "매월 ")
        if last < end:
            basis += ", %s까지 쌓인 금액" % last.isoformat()
        rows.append(_row("원천세", label, due, None if unknown else sum(v for v in vals if v is not None), "예상", basis))
    return rows


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
    for (y, m) in sorted(set((ln["date"].year, ln["date"].month) for ln in withheld)):
        start = dt.date(y, m, 1)
        end = dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1) - dt.timedelta(days=1)
        due = _workday(dt.date(end.year + (end.month == 12), 1 if end.month == 12 else end.month + 1, 10))
        if due <= asof:
            continue
        if any(end < day <= asof for day, _, _ in pays):
            continue   # 이 달분을 이미 냄
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
        rows.append(_row("4대보험", "%d년 %d월분" % (y, m), due, amount, state,
                         "예수금 중 공단 거래처 대변(직원분) %s원 + %s" % ("{:,}".format(emp), note)))
    return rows


def _row(kind, period, due, amount, state, basis):
    return {"세목": kind, "대상기간": period, "납부예정일": due.isoformat(), "금액": "" if amount is None else str(amount),
            "상태": state, "근거": basis}


# ───────────── 보고서 쪽: 자금 일정에 넣기 ─────────────
KEYWORDS = {"부가세": ("부가",), "원천세": ("원천", "소득세", "지방소득"),
            "4대보험": ("4대보험", "사대보험", "국민연금", "건강보험", "고용보험", "산재", "근로복지", "공단")}
OFFICE = {"부가세": ("세무서",), "원천세": ("세무서", "구청", "시청", "군청")}
NEAR_DAYS = 7


def merge(events, taxes):
    """세금 예상을 일정에 넣는다. 이미 일정(자금계획서·자금일정 등)에 같은 세금이 있으면 넣지 않고 그 금액과 비교만 한다.

    같은 세금 = 지급, 납부일 ±7일, 그리고 ① 이름(분류·거래처·근거)에 세목 낱말이 있거나 ② 거래처가 그 세목의 기관(세무서·구청)이거나
    ③ 금액이 계산값과 같음. 세목마다 ①을 먼저 모두 찾고 ②·③은 남은 것에서 찾는다 (원천세 일정을 부가세가 가져가지 않게).
    -> (새 일정, [세금 행 + {"matched": 일정 또는 None, "diff": 일정 금액 − 계산값 또는 None}])."""
    out = list(events)
    taxes = list(taxes or [])
    found = [None] * len(taxes)
    taken = set()

    def near(ev, t):
        return ev["io"] == "out" and ev["date"] is not None and abs((ev["date"] - t["due"]).days) <= NEAR_DAYS

    def text(ev):
        return _sq(" ".join(str(ev.get(k) or "") for k in ("cat", "desc", "basis")))
    tests = (lambda ev, t: any(w in text(ev) for w in KEYWORDS.get(t["kind"], ())),
             lambda ev, t: any(w in text(ev) for w in OFFICE.get(t["kind"], ())),
             lambda ev, t: t["amount"] is not None and ev["amount"] == t["amount"])
    for test in tests:
        for n, t in enumerate(taxes):
            if found[n] is not None:
                continue
            for i, ev in enumerate(events):
                if i not in taken and near(ev, t) and test(ev, t):
                    found[n] = ev
                    taken.add(i)
                    break
    info = []
    for t, match in zip(taxes, found):
        diff = None if match is None or match["amount"] is None or t["amount"] is None else match["amount"] - t["amount"]
        info.append(dict(t, matched=match, diff=diff))
        if match is None and (t["amount"] is None or t["amount"] > 0):
            out.append({"date": t["due"], "io": "out", "amount": t["amount"], "firm": t["state"].startswith("확정"),
                        "cat": "세금·4대보험 예상 (장부 계산)", "desc": "%s %s" % (t["kind"], t["period"]), "basis": t["basis"],
                        "project": "", "source": "세금예상"})
    return out, info
