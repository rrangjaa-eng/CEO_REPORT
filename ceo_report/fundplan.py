"""WEHAGO SmartA 자금계획서 '지출입금현황' 인쇄 저장 파일(.xls, 한 달씩) 읽기 (D-55, 2026-11-03 사용자 결정 '자금계획서 기준').

인쇄 모양: 7일씩 한 쪽, 쪽마다 같은 줄 목록이 되풀이되고 줄이 많으면 다음 '1일' 쪽부터 이어진다. 줄은
'▶지급계획'/'▶입금계획' 구분, 분류 줄(미지급금 지급·인건비…, 그 날짜 칸에 분류 합계), 상세 줄
'예정일:YYYY.MM.DD-거래처[코드]'(그 날짜 칸에 금액), '계'(구분 합계). 상세 줄 금액을 읽고, 분류 합계·'계'와 원 단위로 맞는지
확인한다. 맞지 않는 달은 쓰지 않는다 (모르는 것을 0으로 넣지 않음, 틀린 일정도 넣지 않음).
"""
import datetime as dt
import os
import re
from collections import OrderedDict

from .xls import XlsError, read_xls

DETAIL_RE = re.compile(r"^예정일\s*:\s*(\d{4})\.(\d{1,2})\.(\d{1,2})\s*-\s*(.*?)\s*\[(\d+)\]\s*$")
PERIOD_RE = re.compile(r"계획기간\s*:\s*(\d{4})\s*년\s*(\d{1,2})\s*월")
SECTIONS = {"지급계획": "out", "입금계획": "in"}
COLUMNS = ["예정일", "입출금", "분류", "거래처", "거래처코드", "금액", "대상월", "자료일", "파일", "상태", "근거"]
# 예정일보다 이만큼 앞선 전표까지 그 줄을 미리 지급·입금한 것으로 본다. 지급은 짧게: 매달 같은 금액을 내는 지급(복리후생비 등)의
# 지난달 전표를 이번 달 지급으로 잘못 보면 지급이 빠진다 (실제 파일에서 확인). 입금은 잘못 맞아도 입금이 빠지는 쪽이라 길게 둔다.
EARLY_DAYS = {"지급": 14, "입금": 45}
STATES = ("예정", "예정일 지남", "이미 지급", "이미 입금")


def is_fundplan_name(name):
    base = os.path.basename(name)
    return (not base.startswith("~$") and base.lower().endswith(".xls") and "자금계획서" in base
            and "지출입금" in base)


def file_date(name):
    """파일 이름 앞 'YYMMDD ' 또는 '_YYYYMMDD' 의 날짜. 없으면 None."""
    base = os.path.basename(name)
    m = re.match(r"^(\d{2})(\d{2})(\d{2})\D", base)
    cands = []
    if m:
        cands.append((2000 + int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in re.finditer(r"_(\d{8})(?!\d)", base):
        s = m.group(1)
        cands.append((int(s[:4]), int(s[4:6]), int(s[6:])))
    for y, mo, d in cands:
        try:
            return dt.date(y, mo, d)
        except ValueError:
            continue
    return None


def _num(v):
    return v if isinstance(v, float) else None


def parse(rows):
    """행 목록 -> dict(month=(y, m) 또는 None, items, checks=[(이름, 소계, 상세 합, 맞음)], ok, reason)."""
    month = None
    for row in rows:
        for v in row:
            m = PERIOD_RE.search(v) if isinstance(v, str) else None
            if m:
                month = (int(m.group(1)), int(m.group(2)))
                break
        if month:
            break
    state, start, first_end, on_first, days = (None, None), (None, None), None, False, None
    cats, dets, totals, items = OrderedDict(), {}, {}, []
    bad_dates = 0
    for row in rows:
        if not row:
            continue
        a = row[0].strip() if isinstance(row[0], str) else ""
        cells = [(i, v) for i, v in enumerate(row[1:], 1) if isinstance(v, float) and v]
        if a == "자금구분":
            # 새 쪽: 같은 줄 세트면 그 세트 시작 때의 구분·분류로 돌아간다. '1일' 쪽은 새 줄 세트(앞 세트 끝 상태에서 이어짐)
            if on_first:
                first_end = state
            if isinstance(row[1], str) and row[1].strip() == "1일":
                start, on_first = (first_end or (None, None)), True
            else:
                on_first = False
            state, days = start, row[1:]
            continue
        if a.startswith("▶"):
            state = (SECTIONS.get(a[1:].strip()), None)
            continue
        m = DETAIL_RE.match(a)
        if m:
            key = (state[0], state[1])
            for i, v in cells:
                day = days[i - 1] if days and i - 1 < len(days) else ""
                if not (isinstance(day, str) and day.strip().rstrip("일").isdigit()) or int(day.strip().rstrip("일")) != int(m.group(3)):
                    bad_dates += 1
                dets[key] = dets.get(key, 0) + v
            amount = sum(v for _, v in cells)
            if amount:
                items.append({"date": dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), "io": state[0],
                              "cat": state[1] or "", "vendor": m.group(4), "vendor_code": m.group(5), "amount": amount})
            continue
        if a == "계":
            totals[state[0]] = totals.get(state[0], 0) + sum(v for _, v in cells)
            continue
        if not a or a.startswith("회사명") or "자 금" in a or "계획기간" in a:
            continue
        state = (state[0], a)
        cats[state] = cats.get(state, 0) + sum(v for _, v in cells)
    checks = []
    for key, sub in cats.items():
        got = dets.get(key, 0)
        checks.append(("%s %s 소계" % ({"out": "지급", "in": "입금"}.get(key[0], "?"), key[1]), sub, got, round(sub) == round(got)))
    for io in ("out", "in"):
        if io in totals:
            got = sum(v for k, v in cats.items() if k[0] == io)
            checks.append(("%s 계" % {"out": "지급", "in": "입금"}[io], totals[io], got, round(totals[io]) == round(got)))
    reason = ""
    if month is None:
        reason = "계획기간(연월)을 찾지 못함"
    elif any(it["io"] is None for it in items):
        reason = "지급/입금 구분을 알 수 없는 줄이 있음"
    elif bad_dates:
        reason = "예정일과 금액 칸 날짜가 다른 줄 %d개" % bad_dates
    elif not all(c[3] for c in checks):
        reason = "소계와 상세 합이 다름"
    elif any((it["date"].year, it["date"].month) != month for it in items):
        reason = "계획기간 밖 날짜의 줄이 있음"
    for it in items:
        it["amount"] = int(round(it["amount"]))
    return {"month": month, "items": items, "checks": checks, "ok": not reason, "reason": reason}


def load(folder):
    """폴더의 지출입금현황 파일을 모두 읽는다. 같은 달 파일이 여럿이면 가장 새 것(파일 이름 날짜, 같으면 수정 시각)만.

    -> dict(rows: 자금계획.csv 줄 목록, months: [(연월 글자, 파일, 자료일)], notes: [한 줄 설명], unused: [파일]).
    """
    out = {"rows": [], "months": [], "notes": [], "unused": []}
    try:
        names = sorted(n for n in os.listdir(folder) if is_fundplan_name(n) and os.path.isfile(os.path.join(folder, n)))
    except OSError:
        names = []
    parsed = []
    for n in names:
        path = os.path.join(folder, n)
        try:
            res = parse(read_xls(path))
        except XlsError as e:
            out["notes"].append("%s 읽지 못함 — %s" % (n, e))
            out["unused"].append(n)
            continue
        if not res["ok"]:
            out["notes"].append("%s 쓰지 않음 — %s" % (n, res["reason"]))
            out["unused"].append(n)
            continue
        stamp = file_date(n) or dt.date.fromtimestamp(os.path.getmtime(path))
        parsed.append((res["month"], stamp, os.path.getmtime(path), n, res))
    best = {}
    for p in parsed:
        if p[0] not in best or p[1:3] > best[p[0]][1:3]:
            best[p[0]] = p
    for p in parsed:
        if best[p[0]] is not p:
            out["unused"].append(p[3])
            out["notes"].append("%s 쓰지 않음 — 같은 달(%d-%02d)의 더 새 파일 있음" % ((p[3],) + p[0]))
    for month in sorted(best):
        _, stamp, _, n, res = best[month]
        ym = "%d-%02d" % month
        out["months"].append((ym, n, stamp))
        for it in sorted(res["items"], key=lambda x: (x["date"], x["io"], x["cat"], x["vendor"])):
            out["rows"].append({"예정일": it["date"].isoformat(), "입출금": "지급" if it["io"] == "out" else "입금",
                                "분류": it["cat"], "거래처": it["vendor"], "거래처코드": it["vendor_code"],
                                "금액": it["amount"], "대상월": ym, "자료일": stamp.isoformat(), "파일": n,
                                "상태": "", "근거": ""})
        sums = dict((io, sum(it["amount"] for it in res["items"] if it["io"] == io)) for io in ("out", "in"))
        out["notes"].append("%s %s: 지급 %d줄 %s원 · 입금 %d줄 %s원 (소계·계와 맞음)" % (
            ym, n, sum(1 for it in res["items"] if it["io"] == "out"), "{:,}".format(sums["out"]),
            sum(1 for it in res["items"] if it["io"] == "in"), "{:,}".format(sums["in"])))
    out["unused"].sort()
    return out


def _squash(text):
    return re.sub(r"\s+", "", text or "")


PAYABLE_CODES = ("25300", "26200")   # 미지급금·미지급비용 (설정.csv 변환_payable_codes 와 같은 기본값)
RECEIVABLE_CODES = ("10800",)        # 외상매출금(수입수수료미수금)
CASH_CODES = ("10300",)              # 보통예금


def settle(rows, books, asof, payable=PAYABLE_CODES, receivable=RECEIVABLE_CODES, cash=CASH_CODES):
    """자금계획 줄마다 상태를 정한다 (2026-11-03 사용자 질문: 예정일보다 빠르거나 늦게 지급·입금된 건).

    분개장에서 실제로 움직인 돈을 찾는다. 지급: 미지급 계정(payable) 차변 또는 예금(cash) 대변, 입금: 매출채권(receivable)
    대변 또는 예금 차변이 같은 금액(채무·채권 줄은 같은 거래처)이고 전표일자가 예정일 EARLY_DAYS(지급 14일, 입금 45일) 전부터 장부 기준일까지면
    '이미 지급'/'이미 입금' (분개장 한 줄은 한 번만 쓴다, 거래처가 맞는 줄 먼저). 못 찾았고 예정일이 기준일 이전·당일이면
    '예정일 지남', 아니면 '예정'. 분개장이 없으면 확인하지 못했다고 근거에 적는다 (지급을 빼지 않는다).
    rows 를 고쳐 쓰고 상태별 건수를 돌려준다.
    """
    from .wehago import norm_vendor
    journal = books.journal if books is not None and books.state == "ok" else None
    ref = books.book_date if journal is not None else None
    used = set()
    counts = dict((k, 0) for k in STATES)

    def kind(line, io):
        code = _squash(line.get("account_code"))
        debit, credit = line.get("debit") or 0, line.get("credit") or 0
        if io == "지급":
            if code in payable and debit:
                return debit, True
            if code in cash and credit:
                return credit, False
        else:
            if code in receivable and credit:
                return credit, True
            if code in cash and debit:
                return debit, False
        return None, False

    for r in rows:
        due = dt.date(*[int(x) for x in r["예정일"].split("-")])
        found = None
        if journal is not None:
            key = norm_vendor(r["거래처"])
            lo = due - dt.timedelta(days=EARLY_DAYS[r["입출금"]])
            best = None
            for i, line in enumerate(journal):
                if i in used or line["date"] is None or line["date"] < lo or (ref is not None and line["date"] > ref):
                    continue
                amount, named = kind(line, r["입출금"])
                if amount != r["금액"]:
                    continue
                same = norm_vendor(line["vendor"]) == key
                if named and not same:
                    continue
                rank = (0 if same else 1, abs((line["date"] - due).days))
                if best is None or rank < best[0]:
                    best = (rank, i)
            found = best[1] if best else None
        if found is not None:
            used.add(found)
            line = journal[found]
            r["상태"] = "이미 지급" if r["입출금"] == "지급" else "이미 입금"
            r["근거"] = "분개장 %s 전표 %s %s" % (line["date"].isoformat(), line["no"], line["account"])
        elif due <= asof:
            r["상태"] = "예정일 지남"
            r["근거"] = ("분개장에 %s 없음 (장부 기준일 %s)" % ("출금" if r["입출금"] == "지급" else "입금", ref.isoformat())
                       if journal is not None else "분개장 없음: 지급·입금 여부 확인 못함")
        else:
            r["상태"] = "예정"
            r["근거"] = "" if journal is not None else "분개장 없음: 미리 지급·입금했는지 확인 못함"
        counts[r["상태"]] += 1
    return counts


# ───────────── 보고서 계산에 반영 (calc) ─────────────
MATCH_DAYS = 7               # 거래처가 달라도 같은 금액·이 날수 안이면 같은 건으로 본다
FLAG_SOURCES = ("자금일정", "계산서", "프로젝트집행")   # 자금계획서에 없으면 알리는 기존 일정 (남은 예산은 원래 추정이라 알리지 않음)


def _next_friday(asof):
    return asof + dt.timedelta(days=(4 - asof.weekday()) % 7 or 7)


def apply(events, plan, asof, stale_days, problem=""):
    """자금계획서 줄로 일정을 바꾼다 (D-55 '자금계획서 기준'). -> (새 일정 목록, 설명 dict 또는 None).

    plan: data.load 의 d.fundplan (없으면 None -> 기존 일정 그대로, 설명 None).
    자료일이 기준일보다 stale_days 일 넘게 오래됐으면 쓰지 않는다. 쓸 때는
      · '예정'·'예정일 지남' 줄을 확정 일정으로 넣는다. 지급 '예정일 지남'은 기준일 다음 금요일로 옮기고,
        입금 '예정일 지남'은 추정으로 두어(날짜 그대로, 지난 날짜 묶음) 잔액 계산에 넣지 않는다.
      · '이미 지급'·'이미 입금' 줄은 넣지 않고 목록에만 보인다.
      · 기존 일정 중 같은 입출금·같은 금액이고 거래처가 같거나 예정일이 MATCH_DAYS 일 안인 건은 자금계획서 줄로 바꾼다
        (한 건은 한 줄에만, 거래처가 맞는 것 먼저). 이미 지급·입금 줄과 맞는 기존 일정은 빼낸다.
      · 자금계획서가 다루는 달에 있는데 맞는 줄이 없는 기존 일정은 그대로 두고 '자금계획서에 없음'으로 알린다.
    """
    if plan is None:
        if problem:
            return events, {"used": False, "reason": "자금계획.csv " + problem + " → 기존 일정 사용"}
        return events, None
    from .wehago import norm_vendor
    if not plan:
        return events, {"used": False, "reason": "자금계획.csv 에 줄이 없음 → 기존 일정 사용"}
    stamp = min(p["stamp"] for p in plan)
    months = sorted(set(p["ym"] for p in plan))
    info = {"used": False, "stamp": stamp, "months": months, "reason": "", "matched": [], "missing": [], "done": [],
            "moved": [], "late_in": [], "added": []}
    if (asof - stamp).days > stale_days:
        info["reason"] = "자금계획서 자료일 %s이 기준일보다 %d일 이전 (허용 %d일) → 기존 일정 사용" % (
            stamp.isoformat(), (asof - stamp).days, stale_days)
        return events, info
    info["used"] = True
    taken = set()

    def find(p):
        io = "out" if p["io"] == "지급" else "in"
        key = norm_vendor(p["vendor"])
        best = None
        for i, ev in enumerate(events):
            if i in taken or ev["io"] != io or ev["amount"] != p["amount"] or ev.get("source") not in FLAG_SOURCES:
                continue
            same = bool(key) and norm_vendor(ev.get("desc") or "") == key
            near = ev["date"] is not None and abs((ev["date"] - p["date"]).days) <= MATCH_DAYS
            if not (same or near):
                continue
            rank = (0 if same else 1, abs((ev["date"] - p["date"]).days) if ev["date"] else 999)
            if best is None or rank < best[0]:
                best = (rank, i)
        if best is None:
            return None
        taken.add(best[1])
        return events[best[1]]

    new = []
    for p in sorted(plan, key=lambda x: (x["date"], x["io"], x["vendor"])):
        old = find(p)
        if p["state"] in ("이미 지급", "이미 입금"):
            info["done"].append({"plan": p, "old": old})
            continue
        io = "out" if p["io"] == "지급" else "in"
        ev = {"date": p["date"], "io": io, "amount": p["amount"], "firm": True,
              "cat": "자금계획서 " + (p["cat"] or p["io"]), "desc": p["vendor"],
              "basis": "자금계획서 예정일 %s (%s)" % (p["date"].isoformat(), p["file"] or "자료일 %s" % p["stamp"]),
              "project": old["project"] if old else "", "source": "자금계획서", "plan_state": p["state"]}
        if p["state"] == "예정일 지남":
            if io == "out":
                ev["date"] = _next_friday(asof)
                ev["basis"] += ", 예정일 지난 미지급 → 다음 금요일"
                info["moved"].append(ev)
            else:
                ev["firm"] = False
                ev["basis"] += ", 입금 지연"
                info["late_in"].append(ev)
        new.append(ev)
        if old is not None:
            info["matched"].append({"plan": ev, "old": old})
        else:
            info["added"].append(ev)
    for i, ev in enumerate(events):
        if i in taken:
            continue
        if ev.get("source") in FLAG_SOURCES and ev["date"] is not None and ev["date"].strftime("%Y-%m") in months:
            ev = dict(ev, plan_note="자금계획서에 없음")
            info["missing"].append(ev)
        new.append(ev)
    return new, info
