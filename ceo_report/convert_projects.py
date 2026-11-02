"""프로젝트.csv · 프로젝트집행.csv 만들기 (Phase 2, D-42, D-49, D-50).

두 함수는 줄 목록을 받아 convert.Table 을 돌려주는 순수 함수다. 파일을 읽거나 쓰지 않는다 (연결은 02-07 의 convert.run).
- build_projects: 인트라넷 프로젝트 목록 + WEHAGO 매출 연결분 (+ 이전 프로젝트.csv 에서 옮기는 수동 칸).
- build_execs: WEHAGO (도) 원가 줄 + 아직 장부에 없는 인트라넷 지급요청 (같은 지출을 두 번 넣지 않는다).
모르는 값은 '' 이고 0이 아니다 (D-02). 지출을 적게 잡지 않는다: 애매하면 요청 줄로 두고 '중복 가능'으로 알린다.
"""
import collections
import datetime as dt
import re

from . import data, linking
from .convert import Check, Table, cell_amount, cell_date
from .util import date as parse_date
from .util import is_blank, num, won

PROJECT_EXTRA = ["실행가"]
CARRIED = ("상태", "예산수정일", "계약금액", "완료일")   # 이전 프로젝트.csv 에서 옮기는 칸 (D-49)


def _digits(text):
    return "".join(ch for ch in (text or "") if ch.isdigit())


def _sum_or_none(values):
    """모르는 값이 하나라도 있으면 None (B5)."""
    total = 0
    for v in values:
        if v is None:
            return None
        total += v
    return total


def _carry_cell(column, raw, key, notes):
    """이전 프로젝트.csv 칸 하나를 새 파일 모양으로. 읽을 수 없으면 빈칸이고 notes 에 남긴다."""
    text = (raw or "").strip()
    if column == "상태":
        return text
    if is_blank(text):
        return ""
    if column == "계약금액":
        value = num(text)
        if value is None:
            notes.append("%s 계약금액 이전 값 '%s' 숫자 아님 → 빈칸" % (key, text))
            return ""
        return cell_amount(value)
    day = parse_date(text)
    if day is None:
        notes.append("%s %s 이전 값 '%s' 날짜 아님 → 빈칸" % (key, column, text))
        return ""
    return cell_date(day)


def build_projects(projects, revenue, prev_rows):
    """프로젝트.csv: 스냅숏 프로젝트 한 건당 한 줄 (스냅숏 순서).

    projects: linking.projects_of 결과, revenue: linking.link_revenue 결과, prev_rows: convert.read_prev(..., "프로젝트.csv").
    상태·예산수정일·계약금액·완료일은 이전 파일에서 프로젝트번호의 숫자가 같은 줄이 정확히 하나일 때만 옮긴다 (D-49).
    """
    notes = []
    by_digits = {}
    for r in prev_rows:
        by_digits.setdefault(_digits(r.get("프로젝트번호")), []).append(r)
    by_digits.pop("", None)
    keys = list(projects)
    key_digits = set(_digits(k) for k in keys)
    amounts = {}      # 프로젝트번호 -> [매출 줄 금액들]
    linked_elsewhere, unlinked = [], []
    for ln in revenue["lines"]:
        if ln["project"] is None:
            unlinked.append(ln["amount"])
        elif ln["project"] in projects:
            amounts.setdefault(ln["project"], []).append(ln["amount"])
        else:
            linked_elsewhere.append(ln["amount"])
    rows = []
    for key in keys:
        p = projects[key]
        if p.get("dup"):
            notes.append("프로젝트번호 %s 겹침 → 첫 줄만" % key)
        row = {"프로젝트번호": key, "프로젝트명": p["name"], "팀": p["team"], "클라이언트": p["client"]}
        for column, field, text in (("사전견적예산", "estimate", "estimate_text"), ("실행가", "budget", "budget_text")):
            row[column] = cell_amount(p[field])
            if p[field] is None and not is_blank(p.get(text)):
                notes.append("%s %s 숫자 아님 → 빈칸" % (key, "사전견적" if field == "estimate" else "실행가"))
        row["행사일"] = p.get("event_text") if p.get("event_text") is not None else cell_date(p["event_date"])
        total = _sum_or_none(amounts.get(key, []))
        row["매출반영누계"] = cell_amount(total)
        same = by_digits.get(_digits(key), []) if _digits(key) else []
        old = same[0] if len(same) == 1 else {}
        if len(same) > 1:
            notes.append("이전 프로젝트.csv에 %s와 숫자가 같은 프로젝트번호가 여러 줄 (%s) → 상태·예산수정일·계약금액·완료일 옮기지 않음"
                         % (key, ", ".join(x.get("프로젝트번호", "") for x in same)))
        for column in CARRIED:
            row[column] = _carry_cell(column, old.get(column), key, notes)
        rows.append(row)
    only_prev = [r.get("프로젝트번호", "") for r in prev_rows
                 if (r.get("프로젝트번호") or "").strip() and _digits(r.get("프로젝트번호")) not in key_digits]
    if only_prev:
        notes.append("이전 프로젝트.csv에만 있는 프로젝트 %d건 (옮기지 않음): %s" % (len(only_prev), ", ".join(only_prev)))

    checks = [Check("프로젝트 수 (스냅숏 → CSV)", len(keys), len(rows))]
    for column, field, label in (("사전견적예산", "estimate", "사전견적"), ("실행가", "budget", "실행가")):
        source = [projects[k][field] for k in keys]
        cells = [num(r[column]) for r in rows]
        checks.append(Check("%s 합계 (빈칸 제외)" % label, sum(v for v in source if v is not None),
                            sum(v for v in cells if v is not None)))
        checks.append(Check("%s 빈칸" % label, sum(1 for v in source if v is None), sum(1 for c in rows if c[column] == "")))
    csv_total = _sum_or_none([num(r["매출반영누계"]) for r in rows] + linked_elsewhere + unlinked)
    source_total = _sum_or_none([ln["amount"] for ln in revenue["lines"]])
    checks.append(Check("매출 줄 합계 = 매출반영누계 합계 + 미연결 매출", source_total, csv_total))
    return Table("프로젝트.csv", data.SCHEMA["프로젝트.csv"] + PROJECT_EXTRA, rows, checks, notes)


# ───────────── 프로젝트집행.csv: WEHAGO 원가 줄 ─────────────
def _squash(text):
    return re.sub(r"\s+", "", text or "")


def _code_set(values):
    return set(_squash(v) for v in values)


def _slip_of(keys, i):
    return keys[i][0], keys[i][1]


def _is_opening(row):
    memo = _squash(row.get("memo"))
    return "전기이월" in memo or "기초잔액" in memo


def _line_part(row, field):
    """줄의 차변(또는 대변) 금액. 차변·대변이 모두 비면 금액을 모른다 (None)."""
    if row.get("debit") is None and row.get("credit") is None:
        return None
    return row.get(field) or 0


def _group_cost_lines(costs):
    """원가 줄을 (전표일자, 전표번호, 거래처, 프로젝트 또는 코드)로 묶는다. 줄 순서는 분개장 순서."""
    groups = collections.OrderedDict()
    for ln in costs["lines"]:
        project = ln["project"] or ln["code"] or ""
        gkey = (ln["key"][0], ln["key"][1], ln["vendor_norm"], project)
        g = groups.get(gkey)
        if g is None:
            g = groups[gkey] = {"day": ln["date"], "no": ln["no"], "vendor_norm": ln["vendor_norm"], "project": project,
                                "lines": [], "vat": 0, "kind": "wehago", "request": None}
        g["lines"].append(ln)
    for g in groups.values():
        amounts = [ln["amount"] for ln in g["lines"]]
        g["supply"] = None if any(a is None for a in amounts) else sum(amounts)
    return groups


def _place_vat(groups, books, keys, vat_codes):
    """부가세대급금 차변을 같은 전표·같은 거래처 묶음 중 공급가액이 가장 큰 묶음에 얹는다 (동점은 앞 묶음).

    돌려주는 값: (원본 합계 또는 None, 놓지 못한 [(전표일자, 전표번호, 거래처, 금액 또는 None)]).
    원본 합계 = 원가 줄이 있는 전표의 부가세대급금 차변 합. 모르는 줄이 있으면 None.
    """
    slips = set((g["day"].isoformat() if g["day"] else "", g["no"]) for g in groups.values())
    sums = collections.OrderedDict()
    for i, row in enumerate(books.journal):
        if _squash(row.get("account_code")) not in vat_codes or _slip_of(keys, i) not in slips:
            continue
        k = (_slip_of(keys, i), row.get("vendor_norm") or "")
        part = _line_part(row, "debit")
        sums[k] = None if (part is None or sums.get(k, 0) is None) else sums.get(k, 0) + part
    unplaced = []
    for (slip, vendor_norm), amount in sums.items():
        mine = [g for gk, g in groups.items() if (gk[0], gk[1]) == slip and gk[2] == vendor_norm]
        if not mine:
            unplaced.append((slip[0], slip[1], vendor_norm, amount))
            continue
        target = mine[0]
        for g in mine[1:]:
            if g["supply"] is not None and (target["supply"] is None or g["supply"] > target["supply"]):
                target = g
        target["vat"] = amount
    total = _sum_or_none(sums.values())
    return total, unplaced


def _settle(books, keys, payable_codes):
    """미지급 계정을 거래처별로 맞춘다 (E-3). 돌려주는 값: (item 열쇠 -> 항목, 지급 합계 검증값, 미배분 [(금액)], 알림).

    항목 = 미지급 대변 줄 하나 (전기이월·기초잔액 줄은 거래처별로 묶은 이월 항목 하나), 지급 = 장부 기준일 이전·당일의 차변 줄.
    1회전: 항목마다 같은 금액 지급을 하나 찾는다. 2회전(분개장에 이월·기초잔액 줄이 있을 때만): 남은 지급을 오래된 항목부터 채운다.
    """
    notes = []
    ref = books.book_date
    by_vendor = {}
    opening_any = False
    for i, row in enumerate(books.journal):
        if _squash(row.get("account_code")) not in payable_codes:
            continue
        v = by_vendor.setdefault(row.get("vendor_norm") or "", {"items": [], "pays": [], "open": []})
        if _is_opening(row):
            opening_any = True
            v["open"].append(i)
            continue
        credit, debit = row.get("credit"), row.get("debit")
        if credit is not None and credit > 0:
            v["items"].append({"idx": i, "date": row.get("date"), "amount": credit, "remaining": credit, "applied": 0,
                               "done": None})
        if debit is not None and debit > 0:
            if row.get("date") is None:
                notes.append("날짜 없는 미지급금 차변 줄 (전표 %s, %s원)은 지급으로 보지 않음" % (keys[i][1], won(debit)))
            elif ref is None or row["date"] <= ref:
                v["pays"].append({"idx": i, "date": row["date"], "amount": debit, "left": debit, "used": False})
    unknown_pay = False
    for i, row in enumerate(books.journal):
        if (_squash(row.get("account_code")) in payable_codes and not _is_opening(row) and row.get("debit") is None
                and row.get("credit") is None and (ref is None or row.get("date") is None or row["date"] <= ref)):
            unknown_pay = True
    items_by_idx = {}
    leftovers = []
    pay_total = 0
    for vendor_norm, v in by_vendor.items():
        if v["open"]:
            net = sum((books.journal[i].get("credit") or 0) - (books.journal[i].get("debit") or 0) for i in v["open"])
            if net > 0:
                days = [books.journal[i]["date"] for i in v["open"] if books.journal[i].get("date") is not None]
                v["items"].append({"idx": None, "date": min(days) if days else None, "amount": net, "remaining": net,
                                   "applied": 0, "done": None})
        far = dt.date.max
        v["items"].sort(key=lambda it: (it["date"] or far, -1 if it["idx"] is None else it["idx"]))
        v["pays"].sort(key=lambda p: (p["date"], p["idx"]))
        for it in v["items"]:   # 1회전: 같은 금액 지급 (항목 날짜 이후)
            if it["date"] is None:
                continue
            for p in v["pays"]:
                if not p["used"] and p["amount"] == it["amount"] and p["date"] >= it["date"]:
                    p["used"], p["left"] = True, 0
                    it["remaining"], it["applied"], it["done"] = 0, it["amount"], p
                    break
        if opening_any:   # 2회전: 남은 지급으로 오래된 항목부터
            for p in v["pays"]:
                if p["used"]:
                    continue
                for it in v["items"]:
                    if p["left"] <= 0:
                        break
                    if it["remaining"] <= 0 or it["date"] is None or it["date"] > p["date"]:
                        continue
                    take = min(p["left"], it["remaining"])
                    it["remaining"] -= take
                    it["applied"] += take
                    p["left"] -= take
                    if it["remaining"] == 0:
                        it["done"] = p
        for p in v["pays"]:
            pay_total += p["amount"]
            if p["left"] > 0:
                leftovers.append(p["left"])
        for it in v["items"]:
            if it["idx"] is not None:
                items_by_idx[it["idx"]] = it
    allocated = sum(it["applied"] for v in by_vendor.values() for it in v["items"])
    note = "미배분 지급 %d건 %s" % (len(leftovers), won(sum(leftovers)))
    return items_by_idx, (None if unknown_pay else pay_total), allocated + sum(leftovers), note, notes


def _first_line(g):
    return g["lines"][0]


def _row_order(g):
    no = g["no"]
    return (g["day"] or dt.date.max, (0, int(no), "") if no.isdigit() else (1, 0, no), _first_line(g)["vendor"])


def _wehago_rows(books, costs, cfg):
    """원가 묶음마다 줄 하나. 돌려주는 값: (정렬된 묶음 목록, 대조 목록, 알림 목록)."""
    keys = linking.line_keys(books.journal)
    payable, cash, vat = _code_set(cfg["payable_codes"]), _code_set(cfg["cash_codes"]), _code_set(cfg["vat_codes"])
    groups = _group_cost_lines(costs)
    vat_source, unplaced = _place_vat(groups, books, keys, vat)
    items, pay_source, pay_csv, leftover_note, notes = _settle(books, keys, payable)
    notes.append(leftover_note)
    slips = {}
    for i in range(len(books.journal)):
        slips.setdefault(_slip_of(keys, i), []).append(i)
    words = tuple(cfg["card_words"])
    mixed = 0
    for g in groups.values():
        slip = (g["day"].isoformat() if g["day"] else "", g["no"])
        idxs = slips.get(slip, [])
        cash_paid = any(_squash(books.journal[i].get("account_code")) in cash and (books.journal[i].get("credit") or 0) > 0
                        for i in idxs)
        pay_idx = [i for i in idxs if _squash(books.journal[i].get("account_code")) in payable
                   and (books.journal[i].get("credit") or 0) > 0 and not _is_opening(books.journal[i])]
        base = "WEHAGO %s 전표 %s" % (g["day"].isoformat() if g["day"] else "날짜 없음", g["no"])
        g["basis"] = base
        g["card"] = False
        g["paid_day"] = None
        g["firm"] = False
        if cash_paid and not pay_idx:
            g["state"], g["paid_day"], g["firm"] = "지급완료", g["day"], True
            continue
        if not pay_idx:
            g["state"] = "요청미지급"
            g["basis"] = base + " · 지급 여부 확인 불가 (현금·미지급 대변 없음)"
            continue
        same = [i for i in pay_idx if books.journal[i].get("vendor_norm") == g["vendor_norm"]] or pay_idx
        pick = max(same, key=lambda i: (books.journal[i]["credit"], -i))
        g["card"] = any(w and w in (books.journal[pick].get("vendor") or "") for w in words)
        it = items.get(pick)
        if it is not None and it["remaining"] == 0 and it["done"] is not None:
            g["state"] = "카드결제완료" if g["card"] else "지급완료"
            g["paid_day"], g["firm"] = it["done"]["date"], True
            g["basis"] = base + " · 지급 %s 전표 %s" % (it["done"]["date"].isoformat(), keys[it["done"]["idx"]][1])
            continue
        g["state"] = "카드사용미결제" if g["card"] else "요청미지급"
        g["firm"] = g["card"]
        extra = ""
        if it is not None and it["applied"] > 0:
            extra = " · 일부 지급 %s" % won(it["applied"])
        if cash_paid:
            mixed += 1
            extra += " · 현금·미지급 대변 함께 있음"
        g["basis"] = base + extra
    if mixed:
        notes.append("현금·미지급 대변이 함께 있는 전표의 원가 줄 %d건 → 지급 전(요청미지급)으로 둠 (일부 현금 지급일 수 있음)" % mixed)
    for day, no, vendor_norm, amount in unplaced:
        notes.append("부가세대급금 %s원 (전표 %s %s, 거래처 %s)은 같은 거래처의 원가 줄이 없어 부가세에 넣지 못함"
                     % (won(amount), no, day or "날짜 없음", vendor_norm or "(거래처 없음)"))
    ordered = sorted(groups.values(), key=_row_order)
    for g in ordered:
        first = _first_line(g)
        g["item"] = first["memo"] or first["account"]
        g["vendor_text"] = first["vendor"]
        vat_value = g["vat"]
        if g["card"]:
            g["supply_cell"] = cell_amount(None if g["supply"] is None or vat_value is None else g["supply"] + vat_value)
            g["vat_cell"] = ""
        else:
            g["supply_cell"] = cell_amount(g["supply"])
            g["vat_cell"] = cell_amount(vat_value)
    cost_source = _sum_or_none([ln["amount"] for ln in costs["lines"]])
    checks = [
        Check("원가 줄 합계 ((도) 차변−대변)", cost_source, _sum_or_none([g["supply"] for g in ordered])),
        Check("원가 전표 부가세대급금", vat_source, _sum_or_none([g["vat"] for g in ordered])),
        Check("원가 줄 수", len(costs["lines"]), sum(len(g["lines"]) for g in ordered)),
        Check("미지급 지급 줄 배분", pay_source, pay_csv if pay_source is not None else None),
    ]
    return ordered, checks, notes


def _row_of(g):
    return {"프로젝트번호": g["project"], "항목": g["item"], "거래처": g["vendor_text"], "상태": g["state"],
            "공급가액": g["supply_cell"], "부가세": g["vat_cell"], "일자": cell_date(g["paid_day"]),
            "확정여부": "확정" if g["firm"] else "추정", "근거": g["basis"]}


def build_execs(books, costs, requests, match, prev_rows, cfg, projects=None):
    """프로젝트집행.csv: WEHAGO 원가 줄(묶음마다 한 줄, 날짜순) + 아직 장부에 없는 지급요청 + 옮겨 온 집행계획 줄.

    books: wehago.load_books 결과(state ok), costs: linking.link_costs 결과, requests: linking.requests_of,
    match: wehago.match_requests(books, requests), prev_rows: convert.read_prev(..., "프로젝트집행.csv"), cfg: convert.read_config.
    projects: linking.projects_of 결과 (옮겨 온 줄의 프로젝트번호를 새 번호로 바꿀 때 쓴다; 없으면 연결된 번호와 요청 코드).
    extra['cost_portions']: 줄과 같은 순서의 목록. WEHAGO 줄은 원가 부분(카드 줄은 공급가액 칸의 총액이 아니라 원가), 나머지 줄은 None.
    """
    groups, checks, notes = _wehago_rows(books, costs, cfg)
    rows = [_row_of(g) for g in groups]
    portions = [g["supply"] for g in groups]
    return Table("프로젝트집행.csv", data.SCHEMA["프로젝트집행.csv"], rows, checks, notes,
                 extra={"cost_portions": portions})
