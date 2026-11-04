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
from .wehago import norm_vendor
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


CARRY_LABEL = "이전 프로젝트.csv에만 있는 프로젝트 → 옮긴 줄"
_AMOUNT_COLUMNS = ("사전견적예산", "계약금액", "매출반영누계", "실행가")


def _prev_only(prev_rows, keys):
    """이전 프로젝트.csv 줄 중 스냅숏 프로젝트와 번호의 숫자가 같지 않은 줄 -> {번호: [줄들]} (이전 파일 순서)."""
    key_digits = set(_digits(k) for k in keys)
    out = collections.OrderedDict()
    for r in prev_rows:
        key = (r.get("프로젝트번호") or "").strip()
        if key and _digits(key) not in key_digits:
            out.setdefault(key, []).append(r)
    return out


def carry_check(prev_rows, keys, rows):
    """대조 (WR-03): 이전 프로젝트.csv 에만 있는 프로젝트 번호 수 = 새 프로젝트.csv 에 그 번호로 있는 줄 수."""
    only = _prev_only(prev_rows, keys)
    written = sum(1 for r in rows if (r.get("프로젝트번호") or "").strip() in only)
    return Check(CARRY_LABEL, len(only), written)


def _carried_project(columns, old, key, notes):
    """스냅숏에 없는 이전 줄을 그대로 옮긴다: 금액·날짜 칸은 이 파일 모양으로, 읽을 수 없는 칸은 _carry_cell 처럼 빈칸 + 알림."""
    row = {}
    for column in columns:
        raw = (old.get(column) or "").strip()
        if column in CARRIED:
            row[column] = _carry_cell(column, raw, key, notes)
        elif column in _AMOUNT_COLUMNS:
            value = num(raw)
            if raw and value is None:
                notes.append("%s %s 이전 값 '%s' 숫자 아님 → 빈칸" % (key, column, raw))
            row[column] = cell_amount(value) if raw else ""
        else:
            row[column] = raw
    row["프로젝트번호"] = key
    return row


PERIOD_LABEL = "분개장 시작 전 이력이 있는 프로젝트 → 매출반영누계 판단 불가 (빈칸)"


def journal_span(books):
    """(분개장 첫 전표일, 마지막 전표일). 날짜 있는 줄이 없으면 (None, None)."""
    dated = [ln["date"] for ln in books.journal if ln.get("date") is not None]
    return (min(dated), max(dated)) if dated else (None, None)


def period_text(books):
    """'2026-09-15~2026-10-31' (누계 칸이 어느 장부 기간의 합인지, 02-REVIEW WR-05). 날짜 있는 줄이 없으면 ''."""
    first, last = journal_span(books)
    return "%s~%s" % (first.isoformat(), last.isoformat()) if first else ""


def out_of_period(books, projects, requests):
    """{프로젝트번호: 까닭}: 분개장 첫 전표일보다 이른 이력(행사일, 그 프로젝트 지급요청의 등록일)이 있는 프로젝트 (WR-05).

    그런 프로젝트의 매출·원가 누계는 분개장 기간 밖의 줄을 모르므로 0 이 아니라 판단 불가다 (D-02).
    """
    start, _ = journal_span(books)
    out = collections.OrderedDict()
    if start is None:
        return out
    for key, p in projects.items():
        why = []
        if p.get("event_date") is not None and p["event_date"] < start:
            why.append("행사일 %s" % p["event_date"].isoformat())
        early = sorted(rq["registered"].date() for rq in requests
                       if rq.get("code") == key and rq.get("registered") is not None and rq["registered"].date() < start)
        if early:
            why.append("지급요청 등록 %s" % early[0].isoformat())
        if why:
            out[key] = "분개장 시작 %s 전 %s" % (start.isoformat(), " · ".join(why))
    return out


def period_check(history, rows):
    """대조 (WR-05): 기간 밖 이력이 있는 프로젝트 수 = 프로젝트.csv 에서 그 프로젝트의 매출반영누계가 빈칸인 줄 수."""
    marked = sum(1 for r in rows if (r.get("프로젝트번호") or "").strip() in history and is_blank(r.get("매출반영누계")))
    return Check(PERIOD_LABEL, len(history), marked)


def build_projects(projects, revenue, prev_rows, history=None, period=""):
    """프로젝트.csv: 스냅숏 프로젝트 한 건당 한 줄 (스냅숏 순서), 그다음 이전 파일에만 있는 프로젝트 줄 (이전 파일 순서).

    projects: linking.projects_of 결과, revenue: linking.link_revenue 결과, prev_rows: convert.read_prev(..., "프로젝트.csv").
    상태·예산수정일·계약금액·완료일은 이전 파일에서 프로젝트번호의 숫자가 같은 줄이 정확히 하나일 때만 옮긴다 (D-49).
    스냅숏에 없는 이전 줄(끝난 행사·손으로 넣은 프로젝트)은 수동 칸과 함께 그대로 옮긴다 (02-REVIEW WR-03: 버리면 계약금액이
    합계에서 빠지고 그 번호를 가리키는 집행·계산서 줄이 갈 곳을 잃는다).
    history: out_of_period 결과. 그 프로젝트의 매출반영누계는 0 이 아니라 빈칸 (판단 불가, WR-05). period: 분개장 기간 글.
    """
    notes = []
    by_digits = {}
    for r in prev_rows:
        by_digits.setdefault(_digits(r.get("프로젝트번호")), []).append(r)
    by_digits.pop("", None)
    keys = list(projects)
    amounts = {}      # 프로젝트번호 -> [매출 줄 금액들]
    linked_elsewhere, unlinked = [], []
    for ln in revenue["lines"]:
        if ln["project"] is None:
            unlinked.append(ln["amount"])
        elif ln["project"] in projects:
            amounts.setdefault(ln["project"], []).append(ln["amount"])
        else:
            linked_elsewhere.append(ln["amount"])
    rows, period_total = [], {}
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
        period_total[key] = total
        row["매출반영누계"] = "" if history and key in history else cell_amount(total)
        same = by_digits.get(_digits(key), []) if _digits(key) else []
        old = same[0] if len(same) == 1 else {}
        if len(same) > 1:
            notes.append("이전 프로젝트.csv에 %s와 숫자가 같은 프로젝트번호가 여러 줄 (%s) → 상태·예산수정일·계약금액·완료일 옮기지 않음"
                         % (key, ", ".join(x.get("프로젝트번호", "") for x in same)))
        for column in CARRIED:
            row[column] = _carry_cell(column, old.get(column), key, notes)
        rows.append(row)
    snap_rows = list(rows)
    columns = data.SCHEMA["프로젝트.csv"] + PROJECT_EXTRA
    only_prev = _prev_only(prev_rows, keys)
    order = sorted(only_prev, key=lambda k: (_digits(k) == "", int(_digits(k) or 0), k))   # 이전 파일 줄 순서와 무관하게
    for key in order:
        olds = only_prev[key]
        if len(olds) > 1:
            notes.append("이전 프로젝트.csv에 %s 줄이 여러 줄 → 첫 줄만 옮김" % key)
        rows.append(_carried_project(columns, olds[0], key, notes))
    if only_prev:
        notes.append("이전 프로젝트.csv에만 있는 프로젝트 %d건 → 옮김 (스냅숏에 없음, 이전 줄 그대로): %s"
                     % (len(only_prev), ", ".join(order)))

    checks = [Check("프로젝트 수 (스냅숏 → CSV)", len(keys), len(snap_rows))]
    for column, field, label in (("사전견적예산", "estimate", "사전견적"), ("실행가", "budget", "실행가")):
        source = [projects[k][field] for k in keys]
        cells = [num(r[column]) for r in snap_rows]
        checks.append(Check("%s 합계 (빈칸 제외)" % label, sum(v for v in source if v is not None),
                            sum(v for v in cells if v is not None)))
        checks.append(Check("%s 빈칸" % label, sum(1 for v in source if v is None),
                            sum(1 for c in snap_rows if c[column] == "")))
    # 매출반영누계를 비운 기간 밖 프로젝트도 이 대조에서는 분개장 기간의 합으로 센다 (대조는 같은 기간끼리)
    csv_total = _sum_or_none([num(r["매출반영누계"]) if not (history and r["프로젝트번호"] in history)
                              else period_total[r["프로젝트번호"]] for r in snap_rows] + linked_elsewhere + unlinked)
    source_total = _sum_or_none([ln["amount"] for ln in revenue["lines"]])
    checks.append(Check("매출 줄 합계 = 매출반영누계 합계 + 미연결 매출", source_total, csv_total))
    checks.append(carry_check(prev_rows, keys, rows))
    if history is not None:
        checks.append(period_check(history, rows))
    if period:
        notes.append("매출반영누계는 분개장 기간 %s 합계 (그 앞의 매출은 모름)" % period)
    if history:
        notes.append("매출반영누계 판단 불가 (기간 밖) %d건 — 0이 아니라 빈칸으로 둠: %s"
                     % (len(history), "; ".join("%s (%s)" % (k, v) for k, v in history.items())))
    return Table("프로젝트.csv", columns, rows, checks, notes)


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
        prior = bool(ln.get("prior"))
        old = ln["code"] or ln.get("slip_code") or ""
        project = "" if prior else (ln["project"] or ln["code"] or "")
        gkey = (ln["key"][0], ln["key"][1], ln["vendor_norm"], project, prior)
        g = groups.get(gkey)
        if g is None:
            g = groups[gkey] = {"day": ln["date"], "no": ln["no"], "vendor_norm": ln["vendor_norm"], "project": project,
                                "lines": [], "vat": 0, "kind": "wehago", "request": None, "prior": prior,
                                "old_code": old if prior else ""}
        g["lines"].append(ln)
    for g in groups.values():
        amounts = [ln["amount"] for ln in g["lines"]]
        g["supply"] = None if any(a is None for a in amounts) else sum(amounts)
        # D-38 자동 연결이 이 묶음을 가리키는 요청 번호 (하나일 때만). 그 요청은 이 줄과 같은 빚이다 (CR-01)
        linked = set(ln["request"] for ln in g["lines"] if ln.get("basis") == "자동" and ln.get("request"))
        g["request"] = linked.pop() if len(linked) == 1 else None
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
    for g in groups.values():
        if g.get("prior"):
            g["basis"] += " · " + data.PRIOR_TAG + (" [%s]" % g["old_code"] if g["old_code"] else "")
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


# ───────────── 프로젝트집행.csv: 아직 장부에 없는 지급요청 (D-42, D-50) ─────────────
def _group_total(g):
    """묶음의 합계 (공급가액 + 부가세). 하나라도 모르면 None."""
    return None if g["supply"] is None or g["vat"] is None else g["supply"] + g["vat"]


def _names(text, number):
    """근거 글자가 '지급요청 <번호>'를 담고 있는가 (뒤에 숫자가 이어지면 다른 번호)."""
    return re.search(r"지급요청 %s(?!\d)" % re.escape(number), text or "") is not None


def _no_key(n):
    return (0, int(n), n) if str(n).isdigit() else (1, 0, str(n))


def status_label(rq):
    """사장님승인을 읽지 못한 요청의 근거 글자 (D-52): '상태 확인 필요 (<읽은 값>)', 빈칸이면 '(빈칸)'."""
    return "상태 확인 필요 (%s)" % (rq.get("status_text") or "빈칸")


def _tag(rq):
    """근거의 '지급요청 N' 뒤에 붙일 말: 상태를 읽지 못한 요청이면 ' 상태 확인 필요 (<값>)'."""
    return " " + status_label(rq) if rq["status"] not in ("approved", "pending") else ""


def _request_row(rq, amount, basis):
    return {"프로젝트번호": rq["code"] or "", "항목": rq["name"], "거래처": rq["vendor"], "상태": "요청미지급",
            "공급가액": cell_amount(amount), "부가세": "", "일자": cell_date(rq["date"]),
            "확정여부": "확정" if rq["status"] == "approved" else "추정", "근거": basis}


def _requests_part(groups, requests, match):
    """요청마다 (원가 줄에 표시 | 요청 줄 | 이미 지급 | 넣지 않음)을 정한다. groups 의 묶음에 요청 번호·날짜를 얹기도 한다.

    돌려주는 값: dict(entries=[(번호 열쇠, 0 요청 | 1 차액, 줄)], notes, active, annotated, added, paid, skipped, naming, paid_nos, skipped_nos).
    애매하면 요청 줄로 넣고 '중복 가능'으로 알린다 (지출을 적게 잡지 않음). 요청이 사라지는 것은 '이미 지급'이거나
    계산서의 원가 줄을 정확히 하나 찾았는데 이미 지급완료일 때뿐이다.
    """
    notes = []
    # D-52: 사장님승인이 빈칸이거나 모르는 값인 요청도 버리지 않는다. 승인·대기와 같은 갈래로 넣되 확정여부는 늘 '추정',
    # 근거에 '상태 확인 필요 (<값>)'을 붙인다 (지출을 적게 잡지 않음; 사람이 확인해 지운다)
    active = list(requests)
    unknown = [rq for rq in requests if rq["status"] not in ("approved", "pending")]
    if unknown:
        notes.append("상태 확인 필요 %d건 → 요청미지급(추정)으로 넣음 (D-52: 사장님승인이 빈칸이거나 알 수 없는 값)" % len(unknown))
        notes.append("상태 확인 필요 지급요청: " + ", ".join(
            "%s %s %s (%s)" % (rq["번호"], rq["vendor"], won(rq["amount"], "금액 미확인"), rq.get("status_text") or "빈칸")
            for rq in sorted(unknown, key=lambda r: _no_key(r["번호"]))))
    rows_of = match.get("rows", {})
    fallback = {"status": "판단 불가", "invoice_total": None}
    candidates, via_link = {}, {}
    claims = collections.Counter()
    linked = collections.defaultdict(list)   # 요청 번호 -> D-38 자동 연결로 그 요청을 가리키는 묶음
    for g in groups:
        if g.get("request"):
            linked[g["request"]].append(g)
    for rq in active:
        m = rows_of.get(rq["번호"], fallback)
        found = []
        mine = linked.get(rq["번호"], [])
        if len(mine) == 1 and rq["amount"] is not None and _group_total(mine[0]) is not None:
            # 자동 연결은 이미 이 줄이 이 요청이라고 정했다: 계산서 대조 상태와 관계없이 같은 빚으로 본다 (CR-01, D-38)
            found = mine
            via_link[rq["번호"]] = True
        elif m["status"] in ("계산서 있음", "금액 차이") and rq["amount"] is not None and m.get("invoice_total") is not None:
            found = [g for g in groups if g["vendor_norm"] == norm_vendor(rq["vendor"]) and g["project"] == (rq["code"] or "")
                     and _group_total(g) == m["invoice_total"]]
        candidates[rq["번호"]] = found
        for g in found:
            claims[id(g)] += 1
    unpaid_by_vendor = collections.Counter(g["vendor_norm"] for g in groups if g["state"] in ("요청미지급", "카드사용미결제"))
    entries = []
    # invoice: 번호 -> 큰 쪽(D-50)을 따질 WEHAGO 금액 (계산서 합계 또는 자동 연결된 줄의 합계)
    # covered: 번호 -> 원가 줄이 맡은 요청 금액 (min(요청, WEHAGO)), excess: 번호 -> 요청이 더 커서 넣은 차액 줄 금액
    state = {"annotated": 0, "added": 0, "paid": 0, "skipped": 0, "naming": {}, "paid_nos": [], "skipped_nos": [],
             "invoice": {}, "covered": {}, "excess": {}}
    for rq in sorted(active, key=lambda r: _no_key(r["번호"])):
        no = rq["번호"]
        m = rows_of.get(no, fallback)
        status = m["status"]
        invoice = m.get("invoice_total")
        if status == "이미 지급":
            state["paid"] += 1
            state["paid_nos"].append(no)
            notes.append("지급요청 %s: %s → 넣지 않음" % (no, m.get("label", "이미 지급")))
            continue
        found = candidates[no]
        has_invoice = status in ("계산서 있음", "금액 차이")
        if has_invoice and rq["amount"] is None:
            notes.append("지급요청 %s 금액 미확인 → 차액 판단 불가" % no)
        if (has_invoice or via_link.get(no)) and len(found) == 1 and claims[id(found[0])] == 1:
            g = found[0]
            invoice = _group_total(g)   # 계산서 대조로 찾은 묶음은 합계가 계산서 합계와 같다
            if g["state"] == "요청미지급":
                g["basis"] += " · 지급요청 %s%s" % (no, _tag(rq))
                g["paid_day"] = rq["date"]
                g["firm"] = rq["status"] == "approved"
                state["annotated"] += 1
                state["naming"][no] = "annotated"
                state["invoice"][no] = invoice
                state["covered"][no] = min(rq["amount"], invoice)
                if rq["amount"] > invoice:
                    state["excess"][no] = rq["amount"] - invoice
                    entries.append((_no_key(no), 1, _request_row(
                        rq, rq["amount"] - invoice,
                        "지급요청 %s 차액 (인트라넷 요청 %s − 계산서 %s)" % (no, won(rq["amount"]), won(invoice)))))
                continue
            if g["state"] in ("지급완료", "카드결제완료"):
                # 계산서 몫은 이미 나갔다. 요청이 더 크면 그 차액은 아직 나갈 수 있는 돈이다: 요청미지급(추정) 줄로 둔다 (CR-02, D-50).
                # 그래서 이 요청을 가리키는 줄의 합 = max(계산서, 요청) = 승인 화면의 일정 금액 (D-30b)
                g["basis"] += " · 지급요청 %s%s" % (no, _tag(rq))
                state["skipped"] += 1
                state["skipped_nos"].append(no)
                state["naming"][no] = "skipped"
                state["invoice"][no] = invoice
                state["covered"][no] = min(rq["amount"], invoice)
                if rq["amount"] > invoice:
                    state["excess"][no] = rq["amount"] - invoice
                    row = _request_row(rq, rq["amount"] - invoice, "지급요청 %s 차액 (인트라넷 요청 %s − 계산서 %s, 계산서는 이미 지급)"
                                       % (no, won(rq["amount"]), won(invoice)))
                    row["확정여부"] = "추정"
                    entries.append((_no_key(no), 1, row))
                    notes.append("지급요청 %s: 계산서의 원가 줄이 이미 지급완료 → 요청 금액이 계산서보다 큰 차액 %s원만 요청미지급(추정)으로 넣음 (확인 필요)"
                                 % (no, won(rq["amount"] - invoice)))
                else:
                    notes.append("지급요청 %s: 계산서의 원가 줄이 이미 지급완료 → 요청 줄 넣지 않음 (원가 줄에 번호 표시)" % no)
                continue
        # 요청 줄로 넣는다
        state["added"] += 1
        state["naming"][no] = "added"
        if not has_invoice:
            invoice = _linked_total(linked.get(no, []))
        if rq["amount"] is not None and invoice is not None:
            state["invoice"][no] = invoice
        entries.append((_no_key(no), 0, _request_row(rq, rq["amount"], "지급요청 %s%s (인트라넷 금액, 부가세 포함 여부 미확인)"
                                                     % (no, _tag(rq)))))
        if rq["amount"] is not None and invoice is not None and invoice > rq["amount"]:
            entries.append((_no_key(no), 1, _request_row(
                rq, invoice - rq["amount"],
                "지급요청 %s 차액 (계산서 %s − 인트라넷 요청 %s)" % (no, won(invoice), won(rq["amount"])))))
        if has_invoice:
            notes.append("지급요청 %s: 계산서 있음이나 원가 줄을 하나로 정하지 못함 → 요청으로 넣음 (중복 가능)" % no)
        elif linked.get(no):
            notes.append("지급요청 %s: 자동 연결된 원가 줄을 하나로 정하지 못하거나 합계를 몰라 요청으로 넣음 (중복 가능)" % no)
        elif unpaid_by_vendor.get(norm_vendor(rq["vendor"])):
            notes.append("중복 가능: 지급요청 %s — 같은 거래처의 미지급 원가 줄 %d건" % (no, unpaid_by_vendor[norm_vendor(rq["vendor"])]))
    entries.sort(key=lambda e: (e[0], e[1]))
    state.update(entries=entries, notes=notes, active=active, groups=groups)
    return state


_REQUEST_ROW = re.compile(r"^지급요청 (\d+)(?!\d| 차액)")
_EXCESS_ROW = re.compile(r"^지급요청 (\d+) 차액 \(인트라넷 요청")


def amount_check(known, part, rows):
    """금액 있는 요청의 합 = 원가 줄이 맡은 몫(min(요청, WEHAGO)) + 요청 줄 + 요청이 더 커서 넣은 차액 줄 + 이미 지급.

    요청 줄과 차액 줄은 쓰인 줄(rows)에서 읽는다: 이미 지급된 원가 줄 뒤에 차액이 빠지면 CSV 쪽이 모자라 '불일치' (CR-02).
    part: covered (번호 -> 원가 줄이 맡은 몫), paid_nos (이미 지급 번호).
    """
    by_no = dict((rq["번호"], rq) for rq in known)
    covered = sum(part["covered"].get(n, 0) for n in by_no)
    paid_amount = sum(by_no[n]["amount"] for n in part["paid_nos"] if n in by_no)
    row_amount = 0
    for r in rows:
        text = r.get("근거") or ""
        excess, request = _EXCESS_ROW.match(text), _REQUEST_ROW.match(text)
        if excess and excess.group(1) in by_no:
            row_amount += (num(r["공급가액"]) or 0) + (num(r["부가세"]) or 0)
        elif request and request.group(1) in by_no:
            row_amount += num(r["공급가액"]) or 0
    kinds = "승인·대기·상태 확인 필요" if any(rq["status"] not in ("approved", "pending") for rq in known) else "승인·대기"
    return Check("지급요청 금액 (금액 있는 %s %d건) = 원가 줄 표시 + 요청 줄 + 이미 지급" % (kinds, len(known)),
                 sum(rq["amount"] for rq in known), covered + row_amount + paid_amount)


def _request_checks(part, rows, requests, match):
    """지급요청 건수 · 금액 · 금액 미확인 · 큰 쪽 반영 (B3b). rows 는 만들어진 모든 줄."""
    active = part["active"]
    request_rows = [e[2] for e in part["entries"] if e[1] == 0]
    known = [rq for rq in active if rq["amount"] is not None]
    csv_count = part["annotated"] + part["added"] + part["paid"] + part["skipped"]
    unknown = sum(1 for rq in active if rq["status"] not in ("approved", "pending"))
    label = "지급요청 건수: 승인·대기 %d%s = 원가 줄에 표시 %d + 요청 줄 %d + 이미 지급 %d" % (
        len(active) - unknown, " + 상태 확인 필요 %d" % unknown if unknown else "", part["annotated"], part["added"], part["paid"])
    if part["skipped"]:
        label += " + 이미 지급된 원가 줄 %d" % part["skipped"]
    checks = [
        Check(label, len(active), csv_count),
        amount_check(known, part, rows),
        Check("지급요청 금액 미확인", len(active) - len(known), sum(1 for r in request_rows if r["공급가액"] == "")),
    ]
    checks.append(d50_check(active, match, part["groups"], rows))
    return checks


BASIS_LABEL = "지급요청마다 일정 근거 하나: 근거가 있는 지급요청 수 = 근거(원가 줄·요청 줄) 수"


D50_LABEL = "계산서·요청 금액이 다르면 큰 쪽: 지급요청을 가리키는 줄 합계 = max(계산서, 요청)"


def _linked_total(mine):
    """자동 연결된 묶음이 하나이고 합계를 알면 그 합계, 아니면 None."""
    return _group_total(mine[0]) if len(mine) == 1 else None


def d50_check(active, match, groups, rows):
    """D-50: WEHAGO 금액(계산서 대조 합계 또는 자동 연결된 원가 줄 합계)을 아는 요청마다, 그 요청을 가리키는 줄(근거 '지급요청 N')의
    합 = max(WEHAGO, 요청). 기대값은 요청 대조와 연결 결과에서 바로 구한다 (어느 갈래로 넣었는지와 무관): 이미 지급된 원가 줄 뒤에
    빠진 차액(CR-02)도 '불일치'로 잡힌다. '이미 지급'(분개장에 같은 금액 지급) 요청은 따지지 않는다.
    """
    rows_of = match.get("rows", {})
    linked = collections.defaultdict(list)
    for g in groups:
        if g.get("request"):
            linked[g["request"]].append(g)
    want, got = 0, 0
    for rq in active:
        no, m = rq["번호"], rows_of.get(rq["번호"], {})
        if rq["amount"] is None or m.get("status") == "이미 지급":
            continue
        wehago_amount = _linked_total(linked.get(no, []))
        if wehago_amount is None and m.get("status") in ("계산서 있음", "금액 차이"):
            wehago_amount = m.get("invoice_total")
        if wehago_amount is None:
            continue
        want += max(wehago_amount, rq["amount"])
        got += sum((num(r["공급가액"]) or 0) + (num(r["부가세"]) or 0) for r in rows if _names(r["근거"], no))
    return Check(D50_LABEL, want, got)


def basis_check(groups, request_rows):
    """한 지급요청은 일정 근거 하나에만 있다 (CR-01): WEHAGO 원가 줄(자동 연결 또는 근거의 '지급요청 N') 또는 요청 줄 하나.

    groups: 원가 묶음 (lines 의 request·basis, 묶음 basis), request_rows: 요청 줄(차액 줄 제외). 차액 줄은 같은 근거의
    나머지이므로 따로 세지 않는다. 한 번호가 두 근거에 있으면 원본(번호 수)과 CSV(근거 수)가 달라 '불일치'.
    """
    bases = collections.Counter()
    for g in groups:
        nos = set(ln.get("request") for ln in g["lines"] if ln.get("basis") == "자동" and ln.get("request"))
        nos |= set(re.findall(r"지급요청 (\d+)", g.get("basis") or ""))
        for no in nos:
            bases[no] += 1
    for r in request_rows:
        for no in set(re.findall(r"지급요청 (\d+)", r.get("근거") or "")):
            bases[no] += 1
    return Check(BASIS_LABEL, len(bases), sum(bases.values()))


HAND_LABEL = "이전 프로젝트집행.csv 손으로 넣은 미지급 줄 → 옮긴 줄"
OVERLAP_LABEL = "손으로 넣은 미지급 줄 중 새로 만든 줄과 겹치는 줄 (같은 거래처·금액 또는 같은 지급요청)"
_UNPAID = ("요청미지급", "카드사용미결제")
_GENERATED = ("WEHAGO ", "지급요청")


def is_hand_unpaid(row):
    """사람이 넣은 아직 나가지 않은 돈 줄 (WR-04): 상태가 요청미지급·카드사용미결제이고 근거가 변환이 쓰는 'WEHAGO '·'지급요청'으로
    시작하지 않는다. 지급완료 손 줄은 옮기지 않는다 (D-37: 나간 돈은 WEHAGO 원가 줄이 정한다)."""
    return (row.get("상태") or "").strip() in _UNPAID and not (row.get("근거") or "").strip().startswith(_GENERATED)


def hand_check(prev_rows, rows):
    """대조 (WR-04): 이전 파일의 손으로 넣은 미지급 줄 수 = 새 파일에 있는 그런 줄 수 (버리면 '불일치')."""
    return Check(HAND_LABEL, sum(1 for r in prev_rows if is_hand_unpaid(r)), sum(1 for r in rows if is_hand_unpaid(r)))


def _row_total(row):
    supply = num(row.get("공급가액"))
    return None if supply is None else supply + (num(row.get("부가세")) or 0)


def _overlaps(hand, made):
    """손 줄마다 겹칠 수 있는 새 줄 목록: 거래처(정규화)와 공급가액+부가세가 같거나, 근거가 같은 지급요청 번호를 가리킨다."""
    out = []
    for h in hand:
        vendor, total = norm_vendor(h.get("거래처") or ""), _row_total(h)
        nos = set(re.findall(r"지급요청 (\d+)", h.get("근거") or ""))
        hits = []
        for g in made:
            same = vendor and total is not None and norm_vendor(g.get("거래처") or "") == vendor and _row_total(g) == total
            if same or nos & set(re.findall(r"지급요청 (\d+)", g.get("근거") or "")):
                hits.append(g)
        if hits:
            out.append((h, hits))
    return out


def _carry_plan_rows(prev_rows, key_pool):
    """이전 프로젝트집행.csv 에서 집행계획미요청 줄과 손으로 넣은 미지급 줄(WR-04)을 옮긴다.

    프로젝트번호는 숫자가 같은 새 번호가 정확히 하나일 때 바꾼다. -> (집행계획 줄, 손 줄, 옮기지 않은 줄, 바꾸지 못한 번호).
    """
    by_digits = collections.defaultdict(list)
    for k in key_pool:
        if _digits(k):
            by_digits[_digits(k)].append(k)
    carried, hand, dropped, odd = [], [], [], []
    for r in prev_rows:
        plan = (r.get("상태") or "").strip() == "집행계획미요청"
        if not plan and not is_hand_unpaid(r):
            dropped.append(r)
            continue
        row = dict((c, (r.get(c) or "").strip()) for c in data.SCHEMA["프로젝트집행.csv"])
        same = by_digits.get(_digits(row["프로젝트번호"]), []) if _digits(row["프로젝트번호"]) else []
        if len(same) == 1:
            row["프로젝트번호"] = same[0]
        elif plan:
            odd.append(row["프로젝트번호"])
        if not plan:   # 손 줄 금액은 이 파일 모양(쉼표 없는 정수)으로. 빈칸·읽을 수 없는 글자는 그대로 (0으로 채우지 않음)
            for column in ("공급가액", "부가세"):
                value = num(row[column])
                if value is not None:
                    row[column] = cell_amount(value)
        (carried if plan else hand).append(row)
    return carried, hand, dropped, odd


def build_execs(books, costs, requests, match, prev_rows, cfg, projects=None):
    """프로젝트집행.csv: WEHAGO 원가 줄(묶음마다 한 줄, 날짜순) + 아직 장부에 없는 지급요청 + 옮겨 온 집행계획 줄.

    books: wehago.load_books 결과(state ok), costs: linking.link_costs 결과, requests: linking.requests_of,
    match: wehago.match_requests(books, requests), prev_rows: convert.read_prev(..., "프로젝트집행.csv"), cfg: convert.read_config.
    projects: linking.projects_of 결과 (옮겨 온 줄의 프로젝트번호를 새 번호로 바꿀 때 쓴다; 없으면 연결된 번호와 요청 코드).
    extra['cost_portions']: 줄과 같은 순서의 목록. WEHAGO 줄은 원가 부분(카드 줄은 공급가액 칸의 총액이 아니라 원가), 나머지 줄은 None.
    """
    groups, checks, notes = _wehago_rows(books, costs, cfg)
    part = _requests_part(groups, requests, match)
    wehago_rows = [_row_of(g) for g in groups]
    request_rows = [e[2] for e in part["entries"]]
    key_pool = list(projects) if projects is not None else sorted(
        set(ln["project"] for ln in costs["lines"] if ln["project"]) | set(rq["code"] for rq in requests if rq["code"]))
    carried, hand, dropped, odd = _carry_plan_rows(prev_rows, key_pool)
    rows = wehago_rows + request_rows + carried + hand
    checks = checks + _request_checks(part, wehago_rows + request_rows, requests, match)
    checks.append(basis_check(groups, [e[2] for e in part["entries"] if e[1] == 0]))
    # WR-04: 손으로 넣은 미지급 줄은 옮기고 (지출을 적게 잡지 않음), 새로 만든 줄과 겹치면 '불일치'로 알린다
    overlaps = _overlaps(hand, wehago_rows + request_rows)
    checks.append(hand_check(prev_rows, rows))
    checks.append(Check(OVERLAP_LABEL, 0, len(overlaps)))
    notes = notes + part["notes"]
    if hand:
        totals = [_row_total(r) for r in hand]
        unknown = sum(1 for t in totals if t is None)
        notes.append("이전 프로젝트집행.csv 손으로 넣은 미지급 줄 %d건 옮김 (근거가 'WEHAGO '·'지급요청'으로 시작하지 않는 "
                     "요청미지급·카드사용미결제): 공급가액+부가세 %s원%s"
                     % (len(hand), won(sum(t for t in totals if t is not None)),
                        " (금액 미확인 %d건)" % unknown if unknown else ""))
    for h, hits in overlaps:
        head = " ".join(x for x in (h["프로젝트번호"], h.get("거래처", ""), won(_row_total(h))) if x)
        notes.append("겹칠 수 있음: 손으로 넣은 줄 %s (%s) — 새 줄 %s → 같은 지출이면 이전 줄을 지우세요"
                     % (head, h.get("근거", ""), " / ".join(g.get("근거", "") for g in hits)))
    if carried:
        notes.append("이전 프로젝트집행.csv 집행계획미요청 줄 %d건 옮김" % len(carried))
    if odd:
        notes.append("프로젝트번호를 새 번호로 바꾸지 못한 집행계획미요청 줄 %d건은 번호 그대로 옮김 (%s)" % (len(odd), ", ".join(o or "(빈칸)" for o in odd)))
    if dropped:
        notes.append("이전 프로젝트집행.csv 줄 %d건 옮기지 않음 (WEHAGO·인트라넷으로 다시 만듦)" % len(dropped))
        unpaid = [r for r in dropped if (r.get("상태") or "").strip() in ("요청미지급", "카드사용미결제")]
        if unpaid:
            known = [(num(r.get("공급가액")) or 0) + (num(r.get("부가세")) or 0) for r in unpaid if num(r.get("공급가액")) is not None]
            notes.append("옮기지 않은 줄 중 아직 나가지 않은 돈(요청미지급·카드사용미결제) %d건, 공급가액+부가세 %s원%s — 새 줄에 같은 지출이 있는지 확인"
                         % (len(unpaid), won(sum(known)),
                            " (금액 미확인 %d건 제외)" % (len(unpaid) - len(known)) if len(known) < len(unpaid) else ""))
    portions = [g["supply"] for g in groups] + [None] * (len(request_rows) + len(carried) + len(hand))
    return Table("프로젝트집행.csv", data.SCHEMA["프로젝트집행.csv"], rows, checks, notes, extra={"cost_portions": portions})
