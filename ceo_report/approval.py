"""지급 승인 검토 계산: 인트라넷 대기 요청을 넣고 빼며 앞으로 N주 잔액을 본다.

주간·월간 보고(calc.compute)는 바꾸지 않는다. compute 결과의 일정(events)과 시작 잔액을 읽어 쓰고,
Data는 바꾸지 않는다. 미확인 금액·날짜·상태는 0으로 합산하지 않고 목록으로 따로 둔다 (D-02, D-04, APPR-04).
"""
import datetime as dt
import re

from .calc import compute
from .util import Issues, num
from .util import date as parse_date

WEEKS = 8
DAY = dt.timedelta(days=1)
_NO_RE = re.compile(r"지급요청\s*(\d+)")


# ───────────── 표시 글자 (JS의 fmtMan/fmtWon과 같은 결과) ─────────────
def fmt_won(v, empty="미확인"):
    if v is None:
        return empty
    return ("−" if v < 0 else "") + "{:,}".format(abs(int(v)))


def fmt_man(v, empty="미확인"):
    """백만원 단위 소수 1자리, 반올림은 정수 계산(0.05 이상 올림). 0이 아닌데 0.0으로 보이면 원 단위로 쓴다 (P-9)."""
    if v is None:
        return empty
    a = abs(int(v))
    tenths = (a + 50000) // 100000
    sign = "−" if v < 0 else ""
    if tenths == 0 and a != 0:
        return sign + "{:,}".format(a) + "원"
    return sign + "{:,}.{}".format(tenths // 10, tenths % 10)


def man_unit(text):
    """fmt_man 결과 뒤에 '백만원'을 붙일지: 원 단위 글자나 '미확인'에는 붙이지 않는다."""
    return "" if (text.endswith("원") or text == "미확인") else " 백만원"


# ───────────── 계산 엔진 (JS approvalCalc와 한 줄씩 같다) ─────────────
def _walk(data, sel, with_est, want_weeks):
    start, n = data["start"], len(data["days"])
    rq = [0] * n
    for r in data["requests"]:
        if r["id"] in sel:
            rq[r["day"]] += r["amount"]
    bal = start
    low, low_day = start, data["asof"]
    weeks = []
    for a, b in data["weeks"]:
        w_in = w_out = w_est = 0
        mn = bal
        for i in range(a, b + 1):
            d_in, d_out, d_est = data["base_in"][i], data["base_out"][i] + rq[i], data["est_in"][i]
            w_in += d_in
            w_out += d_out
            w_est += d_est
            if bal is not None:
                bal += d_in - d_out + (d_est if with_est else 0)
                if bal < mn:
                    mn = bal
                if bal < low:
                    low, low_day = bal, data["days"][i]
        if want_weeks:
            if bal is None:
                level = ""
            elif mn < 0:
                level = "부족"
            elif mn < data["reserve"]:
                level = "최소보유현금 미만"
            else:
                level = ""
            weeks.append({"in": w_in, "out": w_out, "est_in": w_est, "min": mn, "end": bal, "level": level})
    if bal is None:
        low, low_day = None, None
    return low, low_day, weeks


def scenario(A, checked):
    """체크한 요청 번호(id) 집합으로 주별 일정·최저 잔액·요청별 '빼면/넣으면 최저 잔액'을 계산한다."""
    data = A if "days" in A else A["data"]
    ids = [r["id"] for r in data["requests"]]
    sel = set(checked) & set(ids)
    low, low_day, weeks = _walk(data, sel, False, True)
    est_low, est_day, _ = _walk(data, sel, True, False)
    toggle = {}
    for i in ids:
        t_low, t_day, _ = _walk(data, sel ^ {i}, False, False)
        toggle[i] = [t_low, t_day]
    amount = {r["id"]: r["amount"] for r in data["requests"]}
    return {"low": low, "low_day": low_day, "est_low": est_low, "est_low_day": est_day, "weeks": weeks,
            "toggle": toggle, "checked_n": len(sel), "checked_sum": sum(amount[i] for i in sel)}


# ───────────── 화면 자료 만들기 ─────────────
def _day_index(date, monday):
    return (max(date, monday) - monday).days


def _status(text):
    if text == "승인":
        return "approved"
    if text in ("미승인", "수락요청중"):
        return "pending"
    return "status_unknown"


def build(d, snap, asof, now):
    """승인 검토 화면의 모든 숫자를 한 번에 만든다. d(Data)는 바꾸지 않는다."""
    R = compute(d, "weekly", asof)
    issues = Issues()
    issues.items = list(R["s7"]["issues"])
    start = R["s1"]["available"]
    reserve = R["settings_num"]["위험_최소보유현금"]
    dates = [a["date"] for a in R["s1"]["accounts"]]
    balance_date = max(dates) if dates else None
    cutoff = balance_date or asof
    monday = asof - dt.timedelta(days=asof.weekday())
    n_days = 7 * WEEKS
    horizon = monday + dt.timedelta(days=n_days - 1)
    days = [(monday + dt.timedelta(days=i)).isoformat() for i in range(n_days)]
    base_in, base_out, est_in = [0] * n_days, [0] * n_days, [0] * n_days

    # 요청 읽기 (A-1, A-4)
    req_all, numbers = [], set()
    for k, row in enumerate(snap.payments):
        status = _status(row.get("사장님승인", ""))
        request_date = parse_date(row.get("지급요청일"))
        date = request_date if request_date and request_date > asof else None
        rq = {"id": "r%d" % k, "번호": row.get("번호", ""), "name": row.get("행사명", ""), "vendor": row.get("파트너", ""),
              "code": None, "registered": None, "status": status, "amount": num(row.get("금액")),
              "request_date": request_date, "date": date, "rule": "지급요청일" if date else "", "reason": "",
              "toggle": False,
              "stages": (row.get("팀장승인", ""), row.get("관리팀승인", ""), row.get("사장님승인", ""))}
        numbers.add(rq["번호"])
        req_all.append(rq)

    # 프로젝트집행 요청미지급 줄 중 스냅숏 요청 번호를 근거로 가진 것은 스냅숏으로 대체 (A-3)
    replaced, unmatched_exec, kept = [], [], []
    for ev0 in R["events"]:
        ev = dict(ev0)
        if ev["source"] == "프로젝트집행" and ev["cat"] == "프로젝트 지급요청":
            m = _NO_RE.search(ev["basis"] or "")
            if m and m.group(1) in numbers:
                replaced.append(ev)
                continue
            unmatched_exec.append(ev)
        kept.append(ev)

    # 남은 일정 분류 (A-4: 미확인은 합계에 넣지 않는다)
    undated, past, beyond, amount_unknown_events, rolled = [], [], [], [], []
    for ev in kept:
        if ev["amount"] is None:
            amount_unknown_events.append(ev)
        elif ev["date"] is None:
            undated.append(ev)
        elif ev["date"] <= cutoff:
            past.append(ev)
        elif ev["date"] > horizon:
            beyond.append(ev)
        else:
            i = _day_index(ev["date"], monday)
            if ev["date"] < monday:
                rolled.append(ev)
            if ev["io"] == "in":
                (base_in if ev["firm"] else est_in)[i] += ev["amount"]
            else:
                base_out[i] += ev["amount"]

    # 요청 분류 (대기 → 체크 가능, 승인 완료는 이번 단계에서는 세기만)
    data_requests = []
    amount_unknown, date_unknown, status_unknown, beyond_requests = [], [], [], []
    approved_paid, approved_future = [], []
    for rq in req_all:
        if rq["status"] == "status_unknown":
            rq["reason"] = "상태 확인 필요"
            status_unknown.append(rq)
        elif rq["amount"] is None:
            rq["reason"] = "금액 미확인"
            amount_unknown.append(rq)
        elif rq["date"] is None:
            rq["reason"] = "예상 지급일 미확인"
            date_unknown.append(rq)
        elif rq["status"] == "approved":
            rq["reason"] = "승인 완료"
        elif rq["date"] > horizon:
            rq["reason"] = "기간 밖"
            beyond_requests.append(rq)
        else:
            rq["toggle"] = True
            data_requests.append({"id": rq["id"], "day": _day_index(rq["date"], monday), "amount": rq["amount"]})

    data = {"asof": asof.isoformat(), "start": start, "reserve": reserve, "days": days,
            "weeks": [[7 * i, 7 * i + 6] for i in range(WEEKS)], "base_in": base_in, "base_out": base_out,
            "est_in": est_in, "requests": data_requests}
    return {"data": data, "R": R, "asof": asof, "now": now, "start": start, "reserve": reserve,
            "balance_date": balance_date, "cutoff": cutoff, "monday": monday, "horizon": horizon,
            "collected_at": snap.collected_at, "snapshot_path": snap.path, "requests_all": req_all,
            "replaced": replaced, "unmatched_exec": unmatched_exec, "duplicates": [], "possible_duplicates": [],
            "rolled": rolled, "past": past, "undated": undated, "beyond": beyond,
            "amount_unknown": amount_unknown, "amount_unknown_events": amount_unknown_events,
            "approved_paid": approved_paid, "approved_future": approved_future, "status_unknown": status_unknown,
            "date_unknown": date_unknown, "beyond_requests": beyond_requests, "notes": [],
            "issues": list(issues.items)}
