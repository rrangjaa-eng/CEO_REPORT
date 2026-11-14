"""WEHAGO SmartA 자금계획서 '지출입금현황' 인쇄 저장 파일(.xls, 한 달씩) 읽기 (D-55, 2026-11-03 사용자 결정 '자금계획서 기준').

인쇄 모양: 7일씩 한 쪽, 쪽마다 같은 줄 목록이 되풀이되고 줄이 많으면 다음 '1일' 쪽부터 이어진다. 줄은
'▶지급계획'/'▶입금계획' 구분, 분류 줄(미지급금 지급·인건비…, 그 날짜 칸에 분류 합계), 상세 줄
'예정일:YYYY.MM.DD-거래처[코드]'(그 날짜 칸에 금액), '계'(구분 합계). 상세 줄 금액을 읽고, 분류 합계·'계'와 원 단위로 맞는지
확인한다. 맞지 않는 달은 쓰지 않는다 (모르는 것을 0으로 넣지 않음, 틀린 일정도 넣지 않음).
"""
import collections
import datetime as dt
import itertools
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
            and ("지출입금" in base or "현금대비" in base))


# 인쇄형태 '현금대비잔액' (2026-11-05 사용자 선택): 원전표 한 건씩, 이미 반제된 건은 금액 없는 줄, '전월이월' = 전월말 보통예금.
CASH_DETAIL_RE = re.compile(r"^예정일\s*:\s*(\d{4})\.(\d{1,2})\.(\d{8})\s*-\s*(.*?)\s*\[(\d+)\]\s*$")
CASH_HEAD = ("일자", "항목명", "입금액", "지출액", "현금잔액")


# 크롬 확장 '대표보고 위하고 수집'이 자금계획입력(SAFM0102) 화면 '계획월' 보기에서 달마다 받은 자금계획 (2026-11-05 사용자 결정).
# 현금대비잔액과 같은 원전표 단위·미반제 건만 (11월 74줄 원 단위 일치 확인). 반제 0원 줄과 전월이월은 없다.
AUTO_PLAN_SUFFIX = "자금계획 자동수집.json"


def is_auto_plan_name(name):
    base = os.path.basename(name)
    return not base.startswith("~$") and base.endswith(AUTO_PLAN_SUFFIX)


# 자금계획 비고(rmk_fplan): '구분 - 거래처코드(10자리)-원전표일자(8자리)+순번(2자리)-[지급예정일:YYYY.MM.DD]-…'
# (2026-11-14 PC 실제 파일 152줄 모두 이 모양, 코드는 늘 cd_trade 와 같음. 순번은 분개장 전표번호와 다름 → 날짜만 씀)
RMK_ORIGIN_RE = re.compile(r"-\s*(\d{10})\s*-\s*(\d{8})\d{2}\s*-")


def origin_of(remark, vendor_code):
    """비고에서 원전표 일자 (거래처코드가 이 줄과 같을 때만) -> date | None."""
    m = RMK_ORIGIN_RE.search(str(remark or ""))
    if not m or m.group(1).lstrip("0") != str(vendor_code or "").lstrip("0"):
        return None
    s = m.group(2)
    try:
        return dt.date(int(s[:4]), int(s[4:6]), int(s[6:]))
    except ValueError:
        return None


def parse_auto(path):
    """자동수집 자금계획(.json) -> [(달 res, 자료일)] (달마다 parse_cash 와 같은 모양, form '자동수집').
    받은 달(조회한달)만 ok (못 받은 달은 쓰지 않음 — 빠진 달을 0원으로 보지 않는다)."""
    import json
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    if not isinstance(doc, dict) or doc.get("종류") != "자금계획" or not isinstance(doc.get("줄"), list):
        raise XlsError("자금계획 자동수집 파일 모양이 아님")
    cols = doc.get("열") or []
    need = ("date", "yn_inout", "nm_fitem", "cd_trade", "nm_trade", "mn_fplan")
    if any(c not in cols for c in need):
        raise XlsError("자금계획 자동수집 파일에 필요한 칸이 없음")
    ix = dict((c, cols.index(c)) for c in need)
    taken = str(doc.get("수집시각") or "")[:10]
    try:
        stamp = dt.date(*[int(x) for x in taken.split("-")])
    except (TypeError, ValueError):
        stamp = None
    done = set(str(d) for d in doc.get("조회한달") or [])
    period = doc.get("기간") or {}
    months = []
    try:
        y, m = int(str(period["from"])[:4]), int(str(period["from"])[4:6])
        ey, em = int(str(period["to"])[:4]), int(str(period["to"])[4:6])
    except (KeyError, TypeError, ValueError):
        raise XlsError("자금계획 자동수집 파일에 기간이 없음")
    while (y, m) <= (ey, em):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    items = dict((mo, []) for mo in months)
    bad = 0
    for row in doc["줄"]:
        try:
            d = str(row[ix["date"]])
            day = dt.date(int(d[:4]), int(d[4:6]), int(d[6:8]))
            io = {"입금": "in", "지급": "out"}[row[ix["yn_inout"]]]
            amount = int(round(float(row[ix["mn_fplan"]])))
        except (IndexError, KeyError, TypeError, ValueError):
            bad += 1
            continue
        if (day.year, day.month) not in items:
            bad += 1
            continue
        code = str(row[ix["cd_trade"]] or "").lstrip("0")
        rmk = row[cols.index("rmk_fplan")] if "rmk_fplan" in cols and cols.index("rmk_fplan") < len(row) else ""
        items[(day.year, day.month)].append({"date": day, "cat": str(row[ix["nm_fitem"]] or ""),
                                             "vendor": str(row[ix["nm_trade"]] or ""),
                                             "vendor_code": code.zfill(6) if code else "", "io": io, "amount": amount,
                                             "origin": origin_of(rmk, code)})
    out = []
    for mo in months:
        reason = ""
        if "%d%02d" % mo not in done:
            reason = "이 달은 받지 못함"
        elif bad:
            reason = "읽지 못한 줄 %d개" % bad
        out.append(({"month": mo, "items": items[mo], "checks": [], "ok": not reason, "reason": reason,
                     "opening": None, "settled": [], "form": "자동수집"}, stamp))
    return out


def is_cash_form(rows):
    for row in rows[:20]:
        if tuple(_squash(v) if isinstance(v, str) else "" for v in row[:5]) == CASH_HEAD:
            return True
    return False


def parse_cash(rows):
    """현금대비잔액 인쇄 저장 파일 -> parse 와 같은 dict + opening(전월이월), settled(금액 없는 줄 = 위하고가 이미 반제).

    줄: '[전월이월]' 잔액, 'DD | 항목명 | 입금 합 | 지출 합'(분류 줄), '예정일:YYYY.MM.YYYYMMDD-거래처[코드] | 입금 | 지출 | (분류 끝 줄의 잔액)',
    '[합계]'. 쪽마다 회사명·머리글이 되풀이된다. 분류 합·합계와 상세 합이 원 단위로 맞아야 쓴다."""
    month, opening, total = None, None, None
    cat, cat_day, items, settled = None, None, [], []
    cats, dets, bad = OrderedDict(), {}, 0
    for row in rows:
        row = list(row) + [""] * (5 - len(row))
        a = row[0].strip() if isinstance(row[0], str) else ""
        b = row[1].strip() if isinstance(row[1], str) else ""
        num = lambda v: v if isinstance(v, float) else 0.0
        for v in row:
            m = PERIOD_RE.search(v) if isinstance(v, str) else None
            if m and month is None:
                month = (int(m.group(1)), int(m.group(2)))
        sb = _squash(b)
        if "전월이월" in sb:
            opening = num(row[2]) - num(row[3])
            continue
        if "합계" in sb and not a:
            total = (num(row[2]), num(row[3]))
            continue
        if a.isdigit() and b:
            cat, cat_day = b, int(a)
            key = (cat_day, cat)
            prev = cats.get(key, (0.0, 0.0))
            cats[key] = (prev[0] + num(row[2]), prev[1] + num(row[3]))
            continue
        m = CASH_DETAIL_RE.match(b)
        if not m:
            continue
        s = m.group(3)
        try:
            day = dt.date(int(s[:4]), int(s[4:6]), int(s[6:]))
        except ValueError:
            bad += 1
            continue
        if cat is None or day.day != cat_day:
            bad += 1
        inn, out = num(row[2]), num(row[3])
        key = (cat_day, cat)
        prev = dets.get(key, (0.0, 0.0))
        dets[key] = (prev[0] + inn, prev[1] + out)
        base = {"date": day, "cat": cat or "", "vendor": m.group(4), "vendor_code": m.group(5)}
        if not inn and not out:
            settled.append(base)
            continue
        if inn:
            items.append(dict(base, io="in", amount=inn))
        if out:
            items.append(dict(base, io="out", amount=out))
    checks = []
    for key, (ci, co) in cats.items():
        gi, go = dets.get(key, (0.0, 0.0))
        checks.append(("%d일 %s 소계" % key, ci + co, gi + go, round(ci) == round(gi) and round(co) == round(go)))
    if total is not None:
        si = sum(it["amount"] for it in items if it["io"] == "in")
        so = sum(it["amount"] for it in items if it["io"] == "out")
        checks.append(("합계", total[0] + total[1], si + so, round(total[0]) == round(si) and round(total[1]) == round(so)))
    reason = ""
    if month is None:
        reason = "계획기간(연월)을 찾지 못함"
    elif bad:
        reason = "날짜를 읽지 못했거나 분류 날짜와 다른 줄 %d개" % bad
    elif total is None:
        reason = "[합계] 줄을 찾지 못함"
    elif not all(c[3] for c in checks):
        reason = "소계·합계와 상세 합이 다름"
    elif any((it["date"].year, it["date"].month) != month for it in items + settled):
        reason = "계획기간 밖 날짜의 줄이 있음"
    for it in items:
        it["amount"] = int(round(it["amount"]))
    return {"month": month, "items": items, "checks": checks, "ok": not reason, "reason": reason,
            "opening": None if opening is None else int(round(opening)), "settled": settled, "form": "현금대비잔액"}


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
        names = sorted(n for n in os.listdir(folder) if (is_fundplan_name(n) or is_auto_plan_name(n))
                       and os.path.isfile(os.path.join(folder, n)))
    except OSError:
        names = []
    parsed = []
    for n in names:
        path = os.path.join(folder, n)
        try:
            if is_auto_plan_name(n):
                found = parse_auto(path)
            else:
                grid = read_xls(path)
                found = [(parse_cash(grid) if is_cash_form(grid) else dict(parse(grid), form="지출입금현황"), None)]
        except (XlsError, OSError, ValueError) as e:
            out["notes"].append("%s 읽지 못함 — %s" % (n, e))
            out["unused"].append(n)
            continue
        used_any = False
        for res, stamp in found:
            label = n if len(found) == 1 else "%s %d-%02d" % ((n,) + tuple(res["month"]))
            if not res["ok"]:
                out["notes"].append("%s 쓰지 않음 — %s" % (label, res["reason"]))
                continue
            used_any = True
            stamp = stamp or file_date(n) or dt.date.fromtimestamp(os.path.getmtime(path))
            # 같은 자료일이면 자동수집 > 현금대비잔액 > 지출입금현황 (원전표 단위·반제 반영, 2026-11-05)
            rank = {"자동수집": 2, "현금대비잔액": 1}.get(res["form"], 0)
            parsed.append((res["month"], stamp, rank, os.path.getmtime(path), n, res))
        if not used_any:
            out["unused"].append(n)
    best = {}
    for p in parsed:
        if p[0] not in best or p[1:4] > best[p[0]][1:4]:
            best[p[0]] = p
    for p in parsed:
        if best[p[0]] is not p:
            out["unused"].append(p[4])
            out["notes"].append("%s 쓰지 않음 — 같은 달(%d-%02d)의 더 새 파일 있음" % ((p[4],) + p[0]))
    for month in sorted(best):
        _, stamp, _, _, n, res = best[month]
        ym = "%d-%02d" % month
        out["months"].append((ym, n, stamp))
        if res.get("opening") is not None:
            out.setdefault("openings", []).append((month, res["opening"], n))
        if res.get("settled"):
            out.setdefault("settled", []).extend(dict(s, file=n) for s in res["settled"])
        for it in sorted(res["items"], key=lambda x: (x["date"], x["io"], x["cat"], x["vendor"])):
            out["rows"].append({"예정일": it["date"].isoformat(), "입출금": "지급" if it["io"] == "out" else "입금",
                                "분류": it["cat"], "거래처": it["vendor"], "거래처코드": it["vendor_code"],
                                "금액": it["amount"], "대상월": ym, "자료일": stamp.isoformat(), "파일": n,
                                "상태": "", "근거": ""})
            if it.get("origin"):   # 원전표일: 자금계획.csv 칸에는 쓰지 않고 이번 대조에만 씀 (②, 2026-11-14)
                out["rows"][-1]["원전표일"] = it["origin"].isoformat()
        sums = dict((io, sum(it["amount"] for it in res["items"] if it["io"] == io)) for io in ("out", "in"))
        out["notes"].append("%s %s: 지급 %d줄 %s원 · 입금 %d줄 %s원 (%s)" % (
            ym, n, sum(1 for it in res["items"] if it["io"] == "out"), "{:,}".format(sums["out"]),
            sum(1 for it in res["items"] if it["io"] == "in"), "{:,}".format(sums["in"]),
            "위하고 자금계획입력 계획월 조회" if res["form"] == "자동수집" else "소계·계와 맞음"))
        if res.get("settled"):
            out["notes"].append("%s %s: 위하고가 이미 반제한 줄 %d건 (금액 없음, 일정에 넣지 않음)" % (ym, n, len(res["settled"])))
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
    대변 또는 예금 차변이 같은 금액·같은 거래처이고 전표일자가 예정일 EARLY_DAYS(지급 14일, 입금 45일) 전부터 장부 기준일까지면
    '이미 지급'/'이미 입금' (분개장 한 줄은 한 번만 쓴다, 채무·채권 줄 먼저). 못 찾았고 예정일이 기준일 이전·당일이면
    '예정일 지남', 아니면 '예정'. 분개장이 없으면 확인하지 못했다고 근거에 적는다 (지급을 빼지 않는다).
    rows 를 고쳐 쓰고 상태별 건수를 돌려준다.
    """
    from .wehago import norm_vendor, norm_code
    journal = books.journal if books is not None and books.state == "ok" else None
    ref = books.book_date if journal is not None else None
    used = set()
    counts = dict((k, 0) for k in STATES)
    from .tax import CARD_PREFIX
    by_slip_lines = collections.defaultdict(list)   # 같은 전표의 다른 줄 (상대 계정·거래처를 본다, 2026-11-14)
    for ln in journal or []:
        by_slip_lines[(ln["date"], str(ln.get("no") or ""))].append(ln)

    def mates(line):
        return by_slip_lines.get((line["date"], str(line.get("no") or ""))) or [line]

    def paid_out(line):
        """미지급 계정 차변이 정말 돈이 나간 지급인가 (F11, 2026-11-14): 같은 전표에 통장 출금 없이 다른 미지급 계정 대변
        (미지급금 → 미지급비용 재분류 같은 대체)만 있으면 지급이 아니다. 카드 미지급(카드사_번호 거래처)으로 옮긴 것은 카드로 낸 것."""
        bank_out, moved = False, False
        for x in mates(line):
            c = _squash(x.get("account_code"))
            if x is line or not (x.get("credit") or 0):
                continue
            if c in cash or c.startswith(("101", "102", "103")):
                bank_out = True
            elif c in payable and not CARD_PREFIX.match(str(x.get("vendor") or "").strip()):
                moved = True
        return bank_out or not moved

    def kind(line, io):
        code = _squash(line.get("account_code"))
        debit, credit = line.get("debit") or 0, line.get("credit") or 0
        if io == "지급":
            if code in payable and debit and paid_out(line):
                return debit, True
            if code in cash and credit:
                return credit, False
        else:
            if code in receivable and credit:
                return credit, True
            if code in cash and debit:
                return debit, False
        return None, False

    def window(r):
        due = dt.date(*[int(x) for x in r["예정일"].split("-")])
        lo = due - dt.timedelta(days=EARLY_DAYS[r["입출금"]])
        if any(k in (r.get("파일") or "") for k in ("현금대비", AUTO_PLAN_SUFFIX)) and r.get("자료일"):
            # 현금대비잔액은 위하고가 반제한 건을 이미 0원으로 뺐다: 남은 줄은 받은 날까지 안 나간 것. 그 뒤 전표만 본다
            # (실제 2026-11-05: 10/19 계산서를 10/30에 지급, 11/3 같은 금액 새 계산서(11/13 예정)를 추정 규칙이 '이미 지급'으로 봄)
            lo = max(lo, dt.date(*[int(x) for x in r["자료일"].split("-")]))
        if r.get("원전표일"):
            # 이 돈을 만든 원전표(계산서·비용 전표) 날짜 전의 지급·입금은 이 줄의 것이 아니다 (비고의 원전표 일자, ②)
            lo = max(lo, dt.date(*[int(x) for x in r["원전표일"].split("-")]))
        return due, lo

    def same_vendor(r, line):
        # 거래처가 같아야 한다: 예금 줄만 금액이 같은 것은 다른 거래처 지급일 수 있다 (실제 분개장에서 확인).
        # 두 쪽에 거래처코드가 있으면 코드로만 본다 (사용자 2026-11-04: 글자 말고 코드로). 자금계획서 [000101] 의
        # 앞 0을 떼면 분개장 거래처Code 00101 과 같다 (실제 파일 3개월 515줄 모두 같은 거래처). 한쪽이라도 코드가 없을 때만 이름으로.
        # 통장 줄은 거래처가 은행인 경우가 많다: 같은 전표 다른 줄(선급금·선수금·미지급금 등, 계정 무관)의 거래처로도 본다
        # (2026-11-14 사용자 "적요 대신 계정·거래처로" ①: 선급금·선수금을 통장으로 바로 주고받은 전표도 짝을 찾게)
        vcode, key = norm_code(r.get("거래처코드")), norm_vendor(r["거래처"])
        pool = [line] if _squash(line.get("account_code")) not in cash else mates(line)
        for x in pool:
            lcode = norm_code(x.get("vendor_code"))
            if vcode and lcode:
                if lcode == vcode:
                    return True
                continue
            if key and norm_vendor(x.get("vendor")) == key:
                return True
        return False

    def candidates(r):
        """이 줄과 같은 거래처·기간의 아직 안 쓴 분개장 돈 줄 -> [(i, 금액, 채무·채권 줄인가)] (전표 하나에서는 한 줄만: 채무·채권 줄 먼저)."""
        due, lo = window(r)
        by_slip = {}
        for i, line in enumerate(journal):
            if i in used or line["date"] is None or line["date"] < lo or (ref is not None and line["date"] > ref):
                continue
            amount, named = kind(line, r["입출금"])
            if not amount or not same_vendor(r, line):
                continue
            k = (line["date"], str(line.get("no") or i))
            if k not in by_slip or (named and not by_slip[k][2]):
                by_slip[k] = (i, amount, named)
        return sorted(by_slip.values(), key=lambda c: (journal[c[0]]["date"], c[0]))

    found = {}
    slips = collections.defaultdict(list)   # 전표(일자·번호) -> 분개장 줄 번호들
    for i, line in enumerate(journal or []):
        slips[(line["date"], str(line.get("no") or i))].append(i)

    def take(idx, r):
        """분개장 줄을 이 계획 줄에 쓴다. 같은 전표에서 같은 거래처의 '다른 쪽' 줄(채무 줄을 썼으면 예금 줄, 예금 줄을 썼으면
        채무 줄)도 함께 막는다: 한 지급을 채무 줄·예금 줄 두 번으로 세지 않게 (2026-11-14 코덱스 검토).
        전표 전체를 막지는 않는다: 한 이체 전표로 여러 거래처에 준 돈, 같은 거래처 계산서 여러 장을 한 번에 준 돈은
        다른 계획 줄이 그 전표의 다른 채무 줄을 쓸 수 있어야 한다 (2026-11-14 오후 점검 F1: 둘째 거래처가 '안 준 돈'으로 남아
        다음 금요일 출금 목록에 다시 올라갔음)."""
        for i in idx:
            used.add(i)
            named_i = kind(journal[i], r["입출금"])[1]
            for j in slips[(journal[i]["date"], str(journal[i].get("no") or i))]:
                if j in used:
                    continue
                amount_j, named_j = kind(journal[j], r["입출금"])
                if amount_j and named_j != named_i and same_vendor(r, journal[j]):
                    used.add(j)
    if journal is not None:
        # ① 같은 금액 한 줄 (예전 규칙)
        for n, r in enumerate(rows):
            due, _ = window(r)
            best = None
            for i, amount, named in candidates(r):
                if amount != r["금액"]:
                    continue
                rank = (0 if named else 1, abs((journal[i]["date"] - due).days))
                if best is None or rank < best[0]:
                    best = (rank, i)
            if best is not None:
                take([best[1]], r)
                found[n] = [best[1]]
        # ② 나눠서 나가거나 들어온 돈 (사용자 2026-11-12): 같은 거래처 2~4건의 합이 원 단위로 같으면
        for n, r in enumerate(rows):
            if n in found:
                continue
            every = [c for c in candidates(r) if c[1] < r["금액"]]
            cands = every[:12]
            hit = None
            for size in (2, 3, 4):
                for combo in itertools.combinations(cands, size):
                    if sum(c[1] for c in combo) == r["금액"]:
                        hit = [c[0] for c in combo]
                        break
                if hit:
                    break
            if hit is None and len(every) >= 5 and sum(c[1] for c in every) == r["금액"]:
                # 다섯 번 넘게 나눠 낸 돈: 그 거래처의 기간 안 돈 줄을 모두 더한 것이 원 단위로 같을 때만 (2026-11-14 오후 점검 F1).
                # 일부만 골라 맞추면 다른 지급끼리 우연히 맞을 수 있어 '전부의 합'만 본다
                hit = [c[0] for c in every]
            if hit:
                take(hit, r)
                found[n] = hit
        # ③ 한 번에 여러 줄을 함께 낸(받은) 돈: 같은 거래처·같은 입출금의 남은 줄 2~4개 합이 분개장 한 줄과 같으면
        rest = collections.OrderedDict()
        for n, r in enumerate(rows):
            if n not in found:
                rest.setdefault((r["입출금"], norm_code(r.get("거래처코드")) or norm_vendor(r["거래처"])), []).append(n)
        for group in rest.values():
            if len(group) < 2:
                continue
            cache = {}   # 거래처 줄이 9건 이상이면 앞 8건 밖의 줄도 후보가 된다 (2026-11-14: KeyError 로 멈추던 것)

            def cand(n):
                if n not in cache:
                    cache[n] = set(candidates(rows[n]))
                return cache[n]
            for size in (4, 3, 2):
                for combo in itertools.combinations([n for n in group if n not in found][:8], size):
                    if any(n in found for n in combo):
                        continue
                    total = sum(rows[n]["금액"] for n in combo)
                    hit = sorted(c for c in cand(combo[0]) if c[1] == total and c[0] not in used
                                 and all(c in cand(n) for n in combo[1:]))
                    if hit:
                        take([hit[0][0]], rows[combo[0]])
                        for n in combo:
                            found[n] = [hit[0][0]]
    for n, r in enumerate(rows):
        due, _ = window(r)
        if n in found:
            lines = [journal[i] for i in found[n]]
            r["상태"] = "이미 지급" if r["입출금"] == "지급" else "이미 입금"
            if len(lines) == 1 and kind(lines[0], r["입출금"])[0] != r["금액"]:
                r["근거"] = "분개장 %s 전표 %s %s (같은 거래처 여러 줄을 한 번에 %s)" % (
                    lines[0]["date"].isoformat(), lines[0]["no"], lines[0]["account"], "지급" if r["입출금"] == "지급" else "입금")
            elif len(lines) == 1:
                r["근거"] = "분개장 %s 전표 %s %s" % (lines[0]["date"].isoformat(), lines[0]["no"], lines[0]["account"])
            else:
                r["근거"] = "분개장 %d건 합계로 나눠 %s: %s" % (len(lines), "지급" if r["입출금"] == "지급" else "입금", ", ".join(
                    "%s 전표 %s" % (x["date"].isoformat(), x["no"]) for x in lines))
        elif due <= asof and journal is not None and ref is not None and due > ref:
            # 분개장이 예정일 전까지만 있으면 '안 나감'이라 단정하지 않는다 (사용자 2026-11-05: 11/5 급여가 11/6 목록에 나옴)
            r["상태"] = "예정"
            r["근거"] = "장부 기준일 %s 뒤 예정일: 분개장으로 %s 확인 못함" % (ref.isoformat(), "출금" if r["입출금"] == "지급" else "입금")
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
DONE_DAYS = 31               # 이미 지급·입금 줄이 지우는 기존 일정은 예정일이 이 날수 안인 것만 (F18 ②, 2026-11-14)
FLAG_SOURCES = ("자금일정", "계산서", "프로젝트집행")   # 자금계획서에 없으면 알리는 기존 일정 (남은 예산은 원래 추정이라 알리지 않음)


def _next_friday(asof):
    return asof + dt.timedelta(days=(4 - asof.weekday()) % 7 or 7)


_REF = re.compile(r"장부 기준일 (\d{4}-\d{2}-\d{2})")


def _unverified(p):
    """분개장이 예정일을 덮지 못해 나갔는지(들어왔는지) 모르는 줄: '예정' 이거나, 예전 변환의 '예정일 지남' 중 근거의 장부 기준일이 예정일 앞."""
    if p["state"] == "예정":
        return True
    m = _REF.search(p.get("basis") or "")
    return p["state"] == "예정일 지남" and bool(m) and dt.date(*[int(x) for x in m.group(1).split("-")]) < p["date"]


def _in_balance(p, cash_date, txns):
    """예정일이 지났고 장부로 확인 못한 줄이 통장 잔액에 이미 들어 있으면 그 근거 글자, 아니면 None.

    계좌 잔액은 입출금내역으로 cash_date 까지 굴린 값이라 그날까지 나간·들어온 돈은 이미 빠져(더해져) 있다.
    같은 금액 거래가 통장내역에 있으면 그 날짜를, 없으면 (급여처럼 여러 건으로 나뉘어 나감) 잔액 기준일을 근거로 적는다.
    """
    if cash_date is None or p["date"] > cash_date:
        return None
    io = "출금" if p["io"] == "지급" else "입금"
    lo = p["date"] - dt.timedelta(days=3)
    hit = [t for t in (txns or []) if t.get("io") == io and t.get("amount") == p["amount"]
           and t.get("date") is not None and lo <= t["date"] <= cash_date]
    if hit:
        return "통장 %s %s 같은 금액 → 이미 %s (분개장 미반영)" % (min(t["date"] for t in hit).isoformat(), io, "지급" if io == "출금" else "입금")
    return "예정일이 통장 잔액 기준일 %s 이전 → 잔액에 이미 반영된 것으로 봄 (분개장은 그 전까지만 있음)" % cash_date.isoformat()


def apply(events, plan, asof, stale_days, problem="", cash_date=None, txns=None):
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
    from .wehago import norm_vendor, norm_code
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
        p.pop("_by_name", None)
        p.pop("_split", None)
        io = "out" if p["io"] == "지급" else "in"
        key = norm_vendor(p["vendor"])
        # 이미 지급·입금 줄은 맞는 기존 일정을 지운다: 거래처가 같을 때만 (2026-11-04 점검: 금액·날짜만 같은 다른 거래처
        # 지급요청이 일정에서 사라지던 것). 예정 줄은 기존 일정을 바꿔 넣을 뿐이라 금액·날짜로도 맞춘다.
        done = p["state"] in ("이미 지급", "이미 입금")
        best = None
        for i, ev in enumerate(events):
            if i in taken or ev["io"] != io or ev["amount"] != p["amount"] or ev.get("source") not in FLAG_SOURCES:
                continue
            pc, ec = norm_code(p.get("vendor_code")), norm_code(ev.get("vendor_code"))
            if pc and ec and pc != ec:
                continue   # 거래처코드가 다르면 금액·날짜가 같아도 다른 지급이다 (사용자 2026-11-04 '거래처는 코드로', 2026-11-14 검토)
            same = (pc == ec) if (pc and ec) else (bool(key) and norm_vendor(ev.get("desc") or "") == key)
            near = ev["date"] is not None and abs((ev["date"] - p["date"]).days) <= MATCH_DAYS
            if not (same or (near and not done)):
                continue
            if done and (ev["date"] is None or abs((ev["date"] - p["date"]).days) > DONE_DAYS):
                continue   # F18 ②: 이미 낸 지난달 줄이 같은 거래처·같은 금액의 몇 달 뒤 일정(다음 달 급여 등)을 지우지 않게
            rank = (0 if same else 1, abs((ev["date"] - p["date"]).days) if ev["date"] else 999)
            if best is None or rank < best[0]:
                best = (rank, i)
        if best is None:
            return split_invoice(p, io, key)
        taken.add(best[1])
        p["_by_name"] = not (norm_code(p.get("vendor_code")) and norm_code(events[best[1]].get("vendor_code")))
        return events[best[1]]

    def split_invoice(p, io, key):
        """F10: 한 계산서를 여러 프로젝트로 나눈 줄(계산서 한 장 = 일정 여러 줄)은 합쳐서 자금계획서 한 줄과 맞춘다.
        같은 계산서 = 같은 거래처·같은 발행일(inv_key). 합이 원 단위로 같을 때만. -> 첫 줄 (나머지도 taken 으로 뺀다)."""
        groups = collections.OrderedDict()
        for i, ev in enumerate(events):
            if i in taken or ev["io"] != io or ev.get("source") != "계산서" or not ev.get("inv_key") or ev["amount"] is None:
                continue
            groups.setdefault(ev["inv_key"], []).append(i)
        for k, idx in groups.items():
            if len(idx) < 2 or sum(events[i]["amount"] for i in idx) != p["amount"]:
                continue
            first = events[idx[0]]
            same = bool(key) and norm_vendor(first.get("desc") or "") == key
            near = first["date"] is not None and abs((first["date"] - p["date"]).days) <= MATCH_DAYS
            if not (same or (near and p["state"] not in ("이미 지급", "이미 입금"))):
                continue
            taken.update(idx)
            p["_by_name"] = True
            p["_split"] = [events[i] for i in idx]
            return first
        return None

    new = []
    for p in sorted(plan, key=lambda x: (x["date"], x["io"], x["vendor"])):
        old = find(p)
        if p["state"] in ("이미 지급", "이미 입금"):
            info["done"].append({"plan": p, "old": old})
            continue
        if p["date"] <= asof and _unverified(p):
            why = _in_balance(p, cash_date, txns)
            if why is not None:   # 장부 기준일 뒤·통장 잔액 기준일 이전 예정일: 다음 금요일 목록에 다시 넣지 않는다 (사용자 2026-11-05)
                info["done"].append({"plan": dict(p, state="통장 잔액에 반영", basis=why), "old": old})
                continue
        io = "out" if p["io"] == "지급" else "in"
        ev = {"date": p["date"], "io": io, "amount": p["amount"], "firm": True,
              "cat": "자금계획서 " + (p["cat"] or p["io"]), "desc": p["vendor"],
              "basis": "자금계획서 예정일 %s (%s)" % (p["date"].isoformat(), p["file"] or "자료일 %s" % p["stamp"]),
              "project": old["project"] if old else "", "source": "자금계획서", "plan_state": p["state"],
              "vendor_code": p.get("vendor_code") or ""}
        # 변환 때 '예정'이었어도 보고 기준일에 날짜가 지났으면 같은 규칙 (2026-11-03 검토: 그대로 두면 일정에서 빠져 자금이 커 보임)
        if p["state"] == "예정일 지남" or (p["state"] == "예정" and p["date"] <= asof):
            if io == "out":
                ev["orig_date"] = p["date"]   # 원래 예정일 (세금 줄과 맞출 때 씀, 2026-11-14)
                ev["date"] = _next_friday(asof)
                ev["basis"] += ", 예정일 지난 미지급 → 다음 금요일"
                if _unverified(p):
                    ev["basis"] += " (장부·통장 자료가 예정일 전까지만 있음: 이미 나갔으면 빼도 됨)"
                    ev["gap"] = p["date"]   # 주간 출금 목록에는 싣지 않고 따로 알린다 (사용자 2026-11-05: 11/5 급여가 11/6 목록에)
                info["moved"].append(ev)
            else:
                ev["firm"] = False
                ev["basis"] += ", 입금 지연"
                info["late_in"].append(ev)
        new.append(ev)
        if old is not None:
            info["matched"].append({"plan": ev, "old": old, "by_name": bool(p.get("_by_name")), "split": p.get("_split") or []})
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


def fill_projects(events, execs):
    """자금계획서 지급 줄에 프로젝트를 채운다 (사용자 2026-11-05: 주간 출금 목록에 프로젝트명이 비어 있음).

    자금계획서에는 프로젝트 칸이 없다. 장부에서 아직 안 나간 원가 줄(프로젝트집행.csv 의 근거 'WEHAGO …', 상태 요청미지급·
    카드사용미결제)은 프로젝트에 이어져 있으므로 같은 거래처 줄로 찾는다.
      1) 부가세 포함 금액이 같은 줄이 하나의 프로젝트면 그 프로젝트
      2) 아니면 그 거래처의 안 나간 줄이 모두 한 프로젝트면 그 프로젝트
      3) 여러 프로젝트에 걸치면 짐작하지 않고 비워 둔다 (근거에 '여러 프로젝트' 적음)
    급여·세금처럼 장부 원가 줄이 없는 거래처는 그대로 빈칸. 채운 건수를 돌려준다."""
    from .wehago import norm_vendor, norm_code
    by_vendor = {}
    for e in execs or []:
        if not str(e.get("basis") or "").startswith("WEHAGO ") or e.get("state") not in ("요청미지급", "카드사용미결제"):
            continue
        if not str(e.get("project") or "").strip():
            continue
        k = norm_vendor(e.get("vendor") or "")
        if k:
            by_vendor.setdefault(k, []).append(e)
    n = 0
    for ev in events:
        if ev.get("io") != "out" or ev.get("source") != "자금계획서" or ev.get("project"):
            continue
        cand = by_vendor.get(norm_vendor(ev.get("desc") or ""), [])
        if not cand:
            continue
        total = lambda e: (e.get("supply") or 0) + (e.get("vat") or 0)
        same = set(e["project"] for e in cand if total(e) == ev["amount"])
        pool = same or set(e["project"] for e in cand)
        if len(pool) == 1:
            ev["project"] = pool.pop()
            ev["basis"] = (ev.get("basis") or "") + ", 프로젝트는 장부 미지급 원가 줄로 찾음"
            n += 1
        else:
            ev["basis"] = (ev.get("basis") or "") + ", 거래처 미지급이 여러 프로젝트 (%d개)" % len(pool)
    return n
