"""지급 승인 검토 계산: 인트라넷 대기 요청을 넣고 빼며 앞으로 N주 잔액을 본다.

주간·월간 보고(calc.compute)는 바꾸지 않는다. compute 결과의 일정(events)과 시작 잔액을 읽어 쓰고,
Data는 바꾸지 않는다. 미확인 금액·날짜·상태는 0으로 합산하지 않고 목록으로 따로 둔다 (D-02, D-04, APPR-04).
"""
import datetime as dt
import re

from .calc import compute
from .util import Issues, is_blank, mask_rrn, num, setting_num, ssum, ssum_or_none, won
from .util import date as parse_date

# 새 설정의 기본값은 여기에 둔다. data.DEFAULT_SETTINGS에 넣으면 주간·월간 보고가 읽는 값이 달라진다 (P-7).
APPROVAL_DEFAULTS = {"승인검토_주수": "8", "승인검토_정기지출": "급여,임차료,카드대금,부가세"}
DAY = dt.timedelta(days=1)
_NO_RE = re.compile(r"지급요청\s*(\d+)")
_CODE_RE = re.compile(r"^\s*\[(\d+)\]")


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


# ───────────── 날짜·글자 해석 ─────────────
def parse_registered(text):
    """인트라넷 등록일 글자 → datetime. 'YYYY-MM-DD HH:MM:SS', 'YYYY-MM-DD HH:MM', 'YYYY-MM-DD'만 받고 나머지는 None."""
    s = (text or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def project_code(text):
    """행사명 맨 앞 [ ] 안의 숫자(프로젝트 코드). 앞 공백은 허용하고, 없으면 None (P-4)."""
    m = _CODE_RE.match(text or "")
    return m.group(1) if m else None


def friday_after(ref):
    """ref 이후(엄격히) 처음 오는 목요일 14:00 마감 → 그 다음 날 금요일 날짜 (A-2, P-2)."""
    day = ref.date() + dt.timedelta(days=(3 - ref.weekday()) % 7)
    cutoff = dt.datetime.combine(day, dt.time(14, 0))
    if cutoff <= ref:
        cutoff += dt.timedelta(days=7)
    return (cutoff + DAY).date()


# ───────────── 화면 자료 만들기 ─────────────
def _day_index(date, monday):
    return (max(date, monday) - monday).days


def _status(text):
    if text == "승인":
        return "approved"
    if text in ("미승인", "수락요청중"):
        return "pending"
    return "status_unknown"


def _read_settings(d, issues):
    """승인검토_주수(1 이상 정수)와 승인검토_정기지출(쉼표 목록). 틀리면 기본값을 쓰고 입력 확인 목록에 남긴다 (D-22)."""
    key, default = "승인검토_주수", int(APPROVAL_DEFAULTS["승인검토_주수"])
    weeks, line = default, d.settings_line.get(key, "-")
    if key not in d.settings_line:
        issues.add("설정.csv", "-", "%s 설정 비어 있음 → 기본값 %d 사용" % (key, default))
    else:
        value, reason = setting_num(d.settings, key, default)
        if reason == "설정 비어 있음":
            issues.add("설정.csv", line, "%s 설정 비어 있음 → 기본값 %d 사용" % (key, default))
        elif reason is not None or not isinstance(value, int) or value < 1:
            issues.add("설정.csv", line, "%s 값이 1 이상 정수가 아님: '%s' → 기본값 %d 사용" % (key, d.settings.get(key), default))
        else:
            weeks = value
    key = "승인검토_정기지출"
    raw = d.settings.get(key)
    cats = []
    if key in d.settings_line and not is_blank(raw):
        cats = [c.strip() for c in str(raw).split(",") if c.strip()]
    if not cats:
        cats = [c.strip() for c in APPROVAL_DEFAULTS[key].split(",")]
        issues.add("설정.csv", d.settings_line.get(key, "-"),
                   "%s 설정 비어 있음 → 기본값 사용(%s)" % (key, APPROVAL_DEFAULTS[key]))
    return weeks, cats


def _expected_date(rq, asof, now):
    """예상 지급일과 근거 규칙 (A-2, P-1, P-2). 날짜를 정할 수 없으면 (None, '')."""
    req = rq["request_date"]
    if req and req > asof:
        return req, "지급요청일"
    if rq["status"] == "pending":
        if req:
            return friday_after(now), "지급요청일 지남·대기 중 → 목요일 14시 승인·금요일 지급 (지금 기준)"
        if rq["registered"] is not None:
            return friday_after(now), "지급요청일 없음 → 목요일 14시 승인·금요일 지급 (지금 기준)"
        return None, ""
    if req:
        return req, "지급요청일"
    if rq["registered"] is not None:
        return friday_after(rq["registered"]), "지급요청일 없음 → 목요일 14시 승인·금요일 지급 (등록 시각 기준)"
    return None, ""


def _as_event(rq, date):
    """승인 요청을 일정 목록(rolled·beyond)에 같이 담을 때의 모양."""
    return {"date": date, "io": "out", "amount": rq["schedule_amount"], "firm": True, "cat": "승인 완료 지급요청",
            "desc": rq["vendor"], "basis": "지급요청 %s" % rq["번호"], "project": rq["code"] or "", "source": "인트라넷 요청",
            "번호": rq["번호"]}


def _count_text(items):
    n = len(items)
    if not n:
        return "0건"
    total, unknown = ssum_or_none(i["amount"] for i in items)
    inner = "확인된 금액 " + ("없음" if total is None else won(total))
    if unknown:
        inner += ", 금액 미확인 %d건" % unknown
    return "%d건 (%s)" % (n, inner)


def _agg(items):
    """건수, 확인된 금액 합계(전부 미확인이면 None), 금액 미확인 건수 (D-02: 미확인은 0이 아니다)."""
    total, unknown = ssum_or_none(i["amount"] for i in items)
    return {"n": len(items), "sum": total, "unknown": unknown}


def _by_io(items):
    return {"in": _agg([i for i in items if i["io"] == "in"]), "out": _agg([i for i in items if i["io"] == "out"]),
            "n": len(items)}


def _panel(L):
    """화면의 '확인 필요' 묶음에 쓰는 건수와 확인된 금액. 위에서 나눈 목록만 읽고 새로 계산하지 않는다."""
    req = L["requests_all"]
    beyond_events = _by_io(L["beyond"])
    return {
        "pending": _agg([r for r in req if r["status"] == "pending"]),
        "amount_unknown": {"n": len(L["amount_unknown"])},
        "date_unknown": {"n": len(L["date_unknown"])},
        "status_unknown": _agg(L["status_unknown"]),
        "rule_no_date": {"n": sum(1 for r in req if r["rule"].startswith("지급요청일 없음"))},
        "rule_past": {"n": sum(1 for r in req if r["rule"].startswith("지급요청일 지남"))},
        "amount_unknown_events": {"n": len(L["amount_unknown_events"])},
        "undated": _by_io(L["undated"]),
        "past": _by_io(L["past"]),
        "beyond": {"in": beyond_events["in"], "out": beyond_events["out"], "requests": {"n": len(L["beyond_requests"])}},
        "balance_unknown": {"n": L["bal_unknown"], "names": list(L["bal_unknown_names"])},
        "vat_unknown": {"n": len(L["vat_unknown_sched"])},
    }


def _regular_missing(events, regular, cutoff, horizon):
    """A-5: 정기 지출 분류 중 잔액 기준일 다음 날부터 마지막 주 일요일까지 자금일정에 한 줄도 없는 것 (설정 순서대로)."""
    present = set(ev["cat"] for ev in events
                  if ev["source"] == "자금일정" and ev["date"] is not None and cutoff < ev["date"] <= horizon)
    return [c for c in regular if c not in present]


def _projects(projects, req_all):
    """A-6: 프로젝트별 실행가와 요청 누계 (P-4, P-5). 미요청 실행가는 참고용이며 일정에 넣지 않는다 (D-04, D-06).

    프로젝트 키 = 행사명 맨 앞 [ ] 안의 숫자, 없으면 번호. 요청 누계 = 연결된 요청 중 사장님승인이 승인·미승인·수락요청중인 것.
    실행가가 비었거나 누계에 금액 미확인이 있거나 키가 겹치면 판단 불가이고, 0으로 두지 않는다.
    """
    keyed = [(project_code(p.get("행사명", "")) or (p.get("번호", "") or "").strip(), p) for p in projects]
    count = {}
    for key, _ in keyed:
        count[key] = count.get(key, 0) + 1
    known = [r for r in req_all if r["status"] != "status_unknown"]
    rows = []
    for key, p in keyed:
        linked = [r for r in known if r["code"] == key]
        total, unknown = ssum(r["amount"] for r in linked)
        requested = None if unknown else total
        budget = num(p.get("실행가"))
        remaining = None if budget is None or requested is None else budget - requested
        state = "판단 불가" if (remaining is None or count[key] > 1) else ""
        rows.append({"code": key, "name": p.get("행사명", ""), "budget": budget, "requested": requested,
                     "requested_unknown": unknown, "remaining": remaining, "state": state})
    keys = set(count)
    unlinked = _agg([r for r in known if r["code"] not in keys])
    unrequested = sorted((r for r in rows if r["state"] == "" and r["remaining"] > 0),
                         key=lambda r: -r["remaining"])
    over = sum(1 for r in rows if r["state"] == "" and r["remaining"] <= 0)
    return rows, unrequested, unlinked, over


def _paid_note(cutoff, paid_after):
    """D-35b: '이미 지급' 중 분개장 지급일이 잔액 기준일 이후인 요청은 잔액에 아직 없으므로 지급일에 확정 지급으로 일정에 둔다."""
    head = "이미 지급 중 지급일이 잔액 기준일(%s) 이후" % cutoff.isoformat()
    if not paid_after:
        return head + " 0건"
    return "%s %d건 %s (잔액에 아직 없음 → 지급일에 확정 지급으로 일정에 넣음)" % (
        head, len(paid_after), won(sum(r["schedule_amount"] for r in paid_after)))


def _notes(cutoff, monday, approved_paid, rolled, replaced, unmatched_exec, duplicates, possible_duplicates,
           paid_note=None):
    lines = []
    if approved_paid:
        lines.append("승인 완료·예상 지급일이 잔액 기준일(%s) 이전 또는 당일 %d건 %s (잔액에 반영된 것으로 봄)" % (
            cutoff.isoformat(), len(approved_paid), won(sum(r["amount"] for r in approved_paid))))
    else:
        lines.append("승인 완료·예상 지급일이 잔액 기준일(%s) 이전 또는 당일 0건" % cutoff.isoformat())
    mmdd = monday.strftime("%m/%d")
    if rolled:
        def piece(io, label):
            items = [e for e in rolled if e["io"] == io]
            return "%s %d건" % (label, len(items)) + (" " + won(sum(e["amount"] for e in items)) if items else "")
        lines.append("잔액 기준일(%s) 이후·1주 시작(%s) 전 일정: %s · %s (1주 첫날 %s에 반영)" % (
            cutoff.isoformat(), mmdd, piece("in", "입금"), piece("out", "지급"), mmdd))
    else:
        lines.append("잔액 기준일(%s) 이후·1주 시작(%s) 전 일정 0건" % (cutoff.isoformat(), mmdd))
    lines.append("프로젝트집행.csv 요청미지급 중 인트라넷 스냅숏으로 대체 " + _count_text(replaced))
    lines.append("스냅숏과 연결 안 된 프로젝트집행 요청미지급 " + _count_text(unmatched_exec)
                 + (" — 일반 일정 규칙대로 반영" if unmatched_exec else ""))
    lines.append("중복 제외 " + _count_text(duplicates))
    lines.append("중복 가능성 " + _count_text(possible_duplicates) + (" — 일정에 그대로 둠, 확인 필요" if possible_duplicates else ""))
    if paid_note:
        lines.append(paid_note)
    return lines


def _project_cost_rows(pc, projects):
    """A['projects']와 WEHAGO (도) 원가를 코드로 잇는다 (D-34). 한쪽이라도 모르면 차이는 None (D-02), 0이 아니다."""
    count = {}
    for p in projects:
        count[p["code"]] = count.get(p["code"], 0) + 1
    rows = []
    for p in projects:
        c = pc["by_code"].get(p["code"])
        if c is None:
            continue
        cost, partial = c["cost"], c["unknown"]
        exact = cost is not None and not partial and count[p["code"]] == 1
        rows.append({"code": p["code"], "name": p["name"], "budget": p["budget"], "requested": p["requested"],
                     "requested_unknown": p["requested_unknown"], "cost": cost, "cost_unknown": partial,
                     "budget_minus_cost": p["budget"] - cost if exact and p["budget"] is not None else None,
                     "requested_minus_cost": p["requested"] - cost if exact and p["requested"] is not None else None})
    return rows


def _xchk(books, match):
    """화면이 읽는 WEHAGO 대조 묶음. 장부가 ok 가 아니면 행은 모두 '판단 불가'이고 금액은 하나도 없다."""
    return {"state": books.state, "reason": books.reason, "book_date": books.book_date, "files": books.files,
            "unused": list(books.unused), "header": books.header, "after_ref": books.after_ref,
            "rows": match["rows"], "summary": match["summary"], "vendors": None, "projects": None, "unlinked": None,
            "projects_without_cost": 0}


def _xchk_full(books, match, req_all, projects, wehago):
    """_xchk + 거래처 미지급금(D-33), 프로젝트 (도) 원가(D-34), 프로젝트 미연결 원가. 장부가 ok 가 아니면 채우지 않는다."""
    x = _xchk(books, match)
    if books.state == "ok":
        x["vendors"] = wehago.vendor_payables(books, req_all, match)
        pc = wehago.project_costs(books, [p["code"] for p in projects])
        x["projects"] = _project_cost_rows(pc, projects)
        x["projects_without_cost"] = len(projects) - len(x["projects"])
        x["unlinked"] = pc["unlinked"]
    return x


def _masked(rows):
    """스냅숏 줄의 글자 칸에서 주민번호 모양 값을 가린 복사본 (D-36, CR-02). 이전 버전이 쓴 스냅숏은 가려져 있지 않다."""
    return [dict((k, mask_rrn(v) if isinstance(v, str) else v) for k, v in row.items()) for row in rows]


def build(d, snap, asof, now, wehago_dir=None):
    """승인 검토 화면의 모든 숫자를 한 번에 만든다. d(Data)는 바꾸지 않는다.

    wehago_dir: WEHAGO 엑셀 폴더. None 이면 장부 없음('자료 없음')이고 일정은 인트라넷 기준이다 (D-35).
    """
    from . import wehago  # wehago 가 이 모듈의 함수를 가져오므로 순환을 피해 안에서 불러온다
    R = compute(d, "weekly", asof)
    issues = Issues()
    issues.items = list(R["s7"]["issues"])
    n_weeks, regular = _read_settings(d, issues)
    start = R["s1"]["available"]
    reserve = R["settings_num"]["위험_최소보유현금"]
    dates = [a["date"] for a in R["s1"]["accounts"]]
    balance_date = max(dates) if dates else None
    cutoff = balance_date or asof  # 이 날짜 이전·당일은 잔액에 이미 반영된 것으로 본다 (P-3)
    monday = asof - dt.timedelta(days=asof.weekday())
    n_days = 7 * n_weeks
    horizon = monday + dt.timedelta(days=n_days - 1)
    days = [(monday + dt.timedelta(days=i)).isoformat() for i in range(n_days)]
    base_in, base_out, est_in = [0] * n_days, [0] * n_days, [0] * n_days

    # WEHAGO 장부 읽기: 읽을 수 없어도 예외 없이 state 로만 알린다 (D-35, D-35a)
    if wehago_dir:
        books = wehago.load_books(wehago_dir, asof, R["settings_num"]["위험_자료경과일"])
    else:
        books = wehago.Books()
        books.reason = "자료 없음: " + ", ".join(wehago.KINDS)

    # 요청 읽기와 예상 지급일 (A-1, A-2, A-4)
    req_all, numbers = [], set()
    for k, row in enumerate(_masked(snap.payments)):
        rq = {"id": "r%d" % k, "번호": row.get("번호", ""), "name": row.get("행사명", ""), "vendor": row.get("파트너", ""),
              "code": project_code(row.get("행사명", "")), "registered": parse_registered(row.get("등록일", "")),
              "status": _status(row.get("사장님승인", "")), "amount": num(row.get("금액")),
              "request_date": parse_date(row.get("지급요청일")), "date": None, "rule": "", "reason": "", "toggle": False,
              "stages": (row.get("팀장승인", ""), row.get("관리팀승인", ""), row.get("사장님승인", ""))}
        rq["schedule_amount"], rq["amount_source"] = rq["amount"], "인트라넷 요청"
        rq["date"], rq["rule"] = _expected_date(rq, asof, now)
        numbers.add(rq["번호"])
        req_all.append(rq)

    # WEHAGO 대조 (D-32): 요청마다 상태 하나. '금액 차이'는 계산서 합계로 일정에 넣는다 (D-30a)
    match = wehago.match_requests(books, req_all)
    for rq in req_all:
        row = match["rows"][rq["번호"]]
        rq["xchk"], rq["xstatus"], rq["xrow"] = row["label"], row["status"], row
        rq["invoice_total"], rq["diff"] = row["invoice_total"], row["diff"]
        if row["status"] == "금액 차이" and row["schedule_amount"] != rq["amount"]:
            # D-30a: 계산서가 더 크면 계산서 합계로. D-30b: 더 적으면 요청 금액 그대로 (지급을 줄이지 않는다)
            rq["schedule_amount"], rq["amount_source"] = row["schedule_amount"], "WEHAGO 계산서"

    # 입력 일정과 스냅숏 요청 맞추기 (A-3, P-6): 번호로 맞거나, 프로젝트·금액·날짜가 같으면 같은 지급으로 본다
    cands = [rq for rq in req_all if rq["status"] != "status_unknown" and rq["amount"] is not None and rq["code"]]

    def key_hit(ev):
        digits = "".join(ch for ch in (ev.get("project") or "") if ch.isdigit())
        if not digits or ev["amount"] is None or ev["date"] is None:
            return False
        return any(rq["code"] == digits and rq["amount"] == ev["amount"]
                   and (rq["request_date"] or rq["date"]) == ev["date"] for rq in cands)

    replaced, unmatched_exec, duplicates, possible_duplicates, kept = [], [], [], [], []
    for ev0 in R["events"]:
        ev = dict(ev0)
        m = _NO_RE.search(ev["basis"] or "")
        by_number = bool(m and m.group(1) in numbers)
        if ev["source"] == "프로젝트집행" and ev["cat"] == "프로젝트 지급요청":
            if by_number or key_hit(ev):
                replaced.append(ev)
                continue
            unmatched_exec.append(ev)
        elif by_number:
            duplicates.append(ev)
            continue
        elif ev["io"] == "out" and key_hit(ev):
            possible_duplicates.append(ev)
        kept.append(ev)

    # 남은 일정 분류 (A-4: 미확인은 합계에 넣지 않는다)
    undated, past, beyond, amount_unknown_events, rolled, vat_unknown_sched = [], [], [], [], [], []
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
                if ev.get("vat_unknown"):
                    vat_unknown_sched.append(ev)  # 부가세 칸이 비어 공급가액만 반영된 일정 (D-07)

    # 요청 분류: 대기 → 체크 가능, 승인 완료 → 잔액 기준일 이후면 고정 지급 (A-3, P-3, P-8)
    data_requests = []
    amount_unknown, date_unknown, status_unknown, beyond_requests = [], [], [], []
    approved_paid, approved_future = [], []
    already_paid, paid_after = [], []
    for rq in req_all:
        if rq["xstatus"] == "이미 지급":
            # 분개장에서 같은 금액으로 이미 출금됨: 일정에 두 번 넣지 않는다 (D-35). 지급일이 잔액 기준일 이후면 잔액에
            # 아직 없으므로 그 날 확정 지급으로 남긴다 (D-35b, A-3과 같은 원칙). 체크 칸은 없다.
            paid = rq["xrow"]["payment"]["date"]
            rq["paid_date"] = paid
            already_paid.append(rq)
            if paid <= cutoff:
                rq["reason"] = "이미 지급·일정에서 뺌"
            else:
                paid_after.append(rq)
                if paid > horizon:
                    rq["reason"] = "이미 지급·기간 밖"
                    beyond.append(_as_event(rq, paid))
                else:
                    rq["reason"] = "이미 지급·지급일에 확정 지급으로 일정에 둠"
                    base_out[_day_index(paid, monday)] += rq["schedule_amount"]
                    if paid < monday:
                        rolled.append(_as_event(rq, paid))
        elif rq["status"] == "status_unknown":
            rq["reason"] = "상태 확인 필요"
            status_unknown.append(rq)
        elif rq["amount"] is None:
            rq["reason"] = "금액 미확인"
            amount_unknown.append(rq)
        elif rq["date"] is None:
            rq["reason"] = "날짜 확인 불가"
            date_unknown.append(rq)
        elif rq["status"] == "approved":
            if rq["date"] <= cutoff:
                rq["reason"] = "승인 완료·잔액에 반영된 것으로 봄"
                approved_paid.append(rq)
            elif rq["date"] > horizon:
                rq["reason"] = "기간 밖"
                beyond.append(_as_event(rq, rq["date"]))
            else:
                rq["reason"] = "승인 완료·고정 지급"
                approved_future.append(rq)
                base_out[_day_index(rq["date"], monday)] += rq["schedule_amount"]
                if rq["date"] < monday:
                    rolled.append(_as_event(rq, rq["date"]))
        elif rq["date"] > horizon:
            rq["reason"] = "기간 밖"
            beyond_requests.append(rq)
        else:
            rq["toggle"] = True
            data_requests.append({"id": rq["id"], "day": _day_index(rq["date"], monday), "amount": rq["schedule_amount"]})

    data = {"asof": asof.isoformat(), "start": start, "reserve": reserve, "days": days,
            "weeks": [[7 * i, 7 * i + 6] for i in range(n_weeks)], "base_in": base_in, "base_out": base_out,
            "est_in": est_in, "requests": data_requests}
    projects, unrequested, unlinked, over_requested = _projects(_masked(snap.projects), req_all)
    lists = {"requests_all": req_all, "amount_unknown": amount_unknown, "date_unknown": date_unknown,
             "status_unknown": status_unknown, "amount_unknown_events": amount_unknown_events, "undated": undated,
             "past": past, "beyond": beyond, "beyond_requests": beyond_requests,
             "bal_unknown": R["s1"]["bal_unknown"], "bal_unknown_names": R["s1"]["bal_unknown_names"],
             "vat_unknown_sched": vat_unknown_sched}
    return {"data": data, "R": R, "asof": asof, "now": now, "start": start, "reserve": reserve, "n_weeks": n_weeks,
            "regular": regular, "balance_date": balance_date, "cutoff": cutoff, "monday": monday, "horizon": horizon,
            "collected_at": snap.collected_at, "snapshot_path": snap.path, "requests_all": req_all,
            "replaced": replaced, "unmatched_exec": unmatched_exec, "duplicates": duplicates,
            "possible_duplicates": possible_duplicates, "rolled": rolled, "past": past, "undated": undated,
            "beyond": beyond, "amount_unknown": amount_unknown, "amount_unknown_events": amount_unknown_events,
            "approved_paid": approved_paid, "approved_future": approved_future, "status_unknown": status_unknown,
            "date_unknown": date_unknown, "beyond_requests": beyond_requests, "panel": _panel(lists),
            "vat_unknown_sched": vat_unknown_sched, "regular_missing": _regular_missing(R["events"], regular, cutoff, horizon),
            "projects": projects, "unrequested": unrequested, "unlinked": unlinked, "over_requested": over_requested,
            "already_paid": already_paid, "paid_after_balance": paid_after,
            "xchk": _xchk_full(books, match, req_all, projects, wehago),
            "notes": _notes(cutoff, monday, approved_paid, rolled, replaced, unmatched_exec, duplicates,
                            possible_duplicates, _paid_note(cutoff, paid_after) if books.state == "ok" else None),
            "issues": list(issues.items)}
