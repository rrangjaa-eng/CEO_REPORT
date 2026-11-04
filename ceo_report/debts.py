"""장부 채무: 미지급금·차입금 잔액 (2026-11-04 점검 A1·A2).

자금 일정은 자금계획서·자금일정·프로젝트집행에 적힌 지급만 안다. 장부에 갚을 돈(미지급금)이 있는데 지급예정일이 없거나,
차입금이 있는데 상환 일정이 없으면 가용자금이 실제보다 커 보이고 대표 보고에도 나오지 않았다. 그래서
  · 변환: 분개장 미지급금(cfg payable_codes)·차입금(cfg loan_codes) 계정을 거래처코드별로 대변 − 차변 누적 → 장부채무.csv
  · 보고: 미지급금 거래처마다 '잔액 − 일정에 든 그 거래처 지급 예정'이 남으면 '지급일이 일정에 없는 미지급금'으로 알린다.
    거래처는 거래처코드로 맞춘다 (사용자 2026-11-04: 글자 말고 코드로). 코드가 없는 줄만 거래처 이름으로 맞추고 그렇게 적는다.
  · 차입금은 잔액을 알리고, 상환 일정은 자금계획서·자금일정에 있는 것만 가용자금에 들어간다고 적는다.
모르는 값은 0으로 두지 않는다: 금액 칸이 모두 빈 계정 줄은 잔액 미확인.
"""
import datetime as dt
import os
import re

from .util import read_csv

FILE = "장부채무.csv"
KEYS = ["구분", "계정코드", "계정과목", "거래처코드", "거래처", "잔액", "기준일", "만기일", "만기근거", "전기이월"]
REQUIRED = KEYS[:7]   # 만기일·만기근거·전기이월 칸이 없는 예전 파일도 읽는다
PAYABLE, LOAN, DEPOSIT = "미지급금", "차입금", "정기예금"
# 적요 속 날짜 (정기예금 만기일, 사용자 2026-11-04: 분개장 정기예금은 만기일까지 쓸 수 없는 돈)
DATE_RE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")


def _memo_date(memo):
    """적요에서 '만기' 뒤 날짜, 없으면 마지막 날짜. 없으면 None."""
    text = str(memo or "")
    pos = text.find("만기")
    cands = list(DATE_RE.finditer(text[pos:] if pos >= 0 else text))
    for m in (cands if pos >= 0 else reversed(cands)):
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
    return None


def _is_opening(ln):
    memo = _sq(ln.get("memo"))
    return "전기이월" in memo or "기초잔액" in memo


def _sq(text):
    return "".join(str(text or "").split())


def build(books, cfg):
    """분개장 -> (줄 목록, 설명 한 줄). 줄은 KEYS 열의 dict, 잔액이 0인 거래처는 넣지 않는다."""
    from . import wehago
    # 분개장에 전기이월 줄이 없으면 잔액은 '올해 늘고 준 금액'뿐이다 (실제 분개장 2026-11-04: 이월 줄 없음).
    # 미지급금·차입금은 작년 말 잔액만큼 더 클 수 있고, 마이너스는 작년 말 잔액을 올해 갚은 것이다.
    # 작년 분개장을 함께 넣어 회사 처음(설립 자본금)부터 있으면 잔액은 실제 잔액이다 (2026-11-04 정합성 점검)
    opening = any(_is_opening(ln) for ln in books.journal) or (
        bool(books.journal) and wehago.journal_from_start(books.journal))
    kinds = [(PAYABLE, set(_sq(c) for c in cfg["payable_codes"])), (LOAN, set(_sq(c) for c in cfg["loan_codes"])),
             (DEPOSIT, set(_sq(c) for c in cfg["deposit_codes"]))]
    ref = books.book_date
    acc = {}
    for ln in books.journal:
        code = _sq(ln.get("account_code"))
        kind = next((k for k, codes in kinds if code in codes), None)
        if kind is None or (ref is not None and ln["date"] is not None and ln["date"] > ref):
            continue
        vcode = wehago.norm_code(ln.get("vendor_code"))
        key = (kind, code, vcode or "이름:" + wehago.norm_vendor(ln.get("vendor") or ""))
        e = acc.setdefault(key, {"account": ln.get("account") or "", "vendor": (ln.get("vendor") or "").strip(),
                                 "vcode": vcode, "sum": 0, "unknown": False, "due": None})
        if ln["debit"] is None and ln["credit"] is None:
            e["unknown"] = True
        else:
            sign = 1 if kind == DEPOSIT else -1   # 정기예금은 자산: 차변 − 대변, 채무는 대변 − 차변
            e["sum"] += sign * ((ln["debit"] or 0) - (ln["credit"] or 0))
        if kind in (DEPOSIT, LOAN):
            # 만기일: 적요 속 날짜 (실제 분개장 차입금 적요 '…[만기일자:2027.04.21]', 정기예금 적요에는 없음)
            md = _memo_date(ln.get("memo"))
            if md is not None and (e["due"] is None or md > e["due"]):
                e["due"] = md
        if kind == DEPOSIT:
            if ln["date"] is not None:
                if ln["debit"]:
                    e.setdefault("joins", []).append(ln["date"])    # 가입: 정기예금 차변
                if ln["credit"]:
                    e.setdefault("mats", []).append(ln["date"])     # 만기 받음: 정기예금 대변
    # 적요에 만기일이 없으면 지난 정기예금의 가입→만기 기간으로 추정 (사용자 2026-11-04).
    # 실제 분개장: 정기예금 하나마다 거래처가 따로 있다 ('신한260113' 처럼 가입일). 가입 1번 → 해지(만기·중도) 몇 번.
    # 기간 = 같은 계정에서 다 해지된 상품 중 가장 최근 것의 '마지막 해지일 − 가입일'. 가입이 여러 번인 것(공제부금처럼
    # 매달 넣는 것)은 만기를 추정하지 않는다: 만기일 확인 필요로 남겨 쓸 수 없는 돈으로만 둔다.
    terms = {}
    for (kind, code, _), e in acc.items():
        joins, mats = e.get("joins", []), e.get("mats", [])
        if kind == DEPOSIT and e["sum"] == 0 and len(joins) == 1 and mats and max(mats) > joins[0]:
            if code not in terms or max(mats) > terms[code][0]:
                terms[code] = (max(mats), max(mats) - joins[0])
    for (kind, code, _), e in acc.items():
        if kind != DEPOSIT or e["due"] is not None or e["sum"] <= 0:
            continue
        joins = e.get("joins", [])
        if len(joins) == 1 and not e.get("mats") and code in terms:
            e["due"], e["guess"] = joins[0] + terms[code][1], terms[code][1].days
    rows = []
    day = ref.isoformat() if ref else ""
    for (kind, code, _), e in sorted(acc.items(), key=lambda kv: (kv[0][0] != PAYABLE, kv[0][1], -kv[1]["sum"])):
        if not e["unknown"] and e["sum"] == 0:
            continue
        rows.append(dict(zip(KEYS, [kind, code, e["account"], e["vcode"], e["vendor"],
                                    "" if e["unknown"] else str(e["sum"]), day, e["due"].isoformat() if e["due"] else "",
                                    "" if not e["due"] else ("지난 정기예금 기간 %d일로 추정" % e["guess"] if e.get("guess") else "적요"),
                                    "있음" if opening else "없음"])))
    tot = {k: sum(int(r["잔액"]) for r in rows if r["구분"] == k and r["잔액"]) for k in (PAYABLE, LOAN, DEPOSIT)}
    note = "장부 채무·정기예금 (%s 기준%s): 미지급금 %d곳 %s원 · 차입금 %d줄 %s원 · 정기예금 %d줄 %s원 (만기일 모름 %d줄)" % (
        day or "날짜 없음", "" if opening else ", 분개장에 전기이월 없음: 올해 늘고 준 금액만", sum(1 for r in rows if r["구분"] == PAYABLE), "{:,}".format(tot[PAYABLE]),
        sum(1 for r in rows if r["구분"] == LOAN), "{:,}".format(tot[LOAN]),
        sum(1 for r in rows if r["구분"] == DEPOSIT), "{:,}".format(tot[DEPOSIT]),
        sum(1 for r in rows if r["구분"] == DEPOSIT and not r["만기일"]))
    return rows, note


def load(folder, iss):
    """장부채무.csv -> 줄 목록 또는 None (파일 없음·읽지 못함)."""
    from .util import num
    path = os.path.join(folder, FILE)
    if not os.path.exists(path):
        return None
    info = {}
    rows, ok = read_csv(path, REQUIRED, iss, info)
    if not ok or info.get("missing"):
        return None
    out = []
    for r in rows:
        out.append({"kind": (r.get("구분") or "").strip(), "code": (r.get("계정코드") or "").strip(),
                    "account": r.get("계정과목") or "", "vcode": (r.get("거래처코드") or "").strip(),
                    "vendor": (r.get("거래처") or "").strip(),
                    "balance": num(r.get("잔액")) if (r.get("잔액") or "").strip() else None,
                    "date": (r.get("기준일") or "").strip(), "due": (r.get("만기일") or "").strip(),
                    "due_basis": (r.get("만기근거") or "").strip(),
                    "opening": (r.get("전기이월") or "").strip() != "없음"})
    return out


def compare(debts, events, asof):
    """장부 채무 대 자금 일정. debts 가 None 이면 None.

    미지급금: 거래처마다 잔액에서 일정에 든 그 거래처 지급(기준일 뒤, 또는 날짜 없음)을 빼고 남는 금액.
    일정 줄은 거래처코드(vendor_code)가 있으면 코드로, 없으면 거래처 이름으로 맞춘다.
    -> dict(unscheduled=[{vendor, balance, scheduled, left, by_name}], unscheduled_total, unknown_n, payable_total,
            loans=[...], loan_total, loan_unknown_n, date)
    """
    if debts is None:
        return None
    from .wehago import norm_vendor, norm_code
    by_code, by_name = {}, {}
    for ev in events:
        if ev["io"] != "out" or ev["amount"] is None or (ev["date"] is not None and ev["date"] <= asof):
            continue
        vc = norm_code(ev.get("vendor_code"))
        if vc:
            by_code[vc] = by_code.get(vc, 0) + ev["amount"]
        nm = norm_vendor(ev.get("desc") or "")
        if nm:
            by_name[nm] = by_name.get(nm, 0) + ev["amount"]
    pays = [d for d in debts if d["kind"] == PAYABLE]   # 정기예금은 data.load 가 계좌(사용제한·만기일)로 넣는다
    loans = [d for d in debts if d["kind"] == LOAN]
    left_rows, unknown_n = [], 0
    for d in pays:
        if d["balance"] is None:
            unknown_n += 1
            continue
        if d["balance"] <= 0:
            continue
        vc = norm_code(d["vcode"])
        if vc and vc in by_code:
            sched, name_match = by_code[vc], False
        else:
            sched, name_match = by_name.get(norm_vendor(d["vendor"]), 0), True
        left = d["balance"] - sched
        if left > 0:
            left_rows.append({"vendor": d["vendor"] or "(거래처 없음)", "vcode": d["vcode"], "balance": d["balance"],
                              "scheduled": sched, "left": left, "by_name": name_match and sched > 0})
    left_rows.sort(key=lambda r: -r["left"])
    # 차입금: 잔액이 양수인 것만 잔액으로 더한다. 마이너스는 전기이월이 없어 '올해 갚은 원금'만 보이는 것.
    known_loans = [d for d in loans if d["balance"] is not None and d["balance"] > 0]
    repaid = [d for d in loans if d["balance"] is not None and d["balance"] < 0]
    return {"opening": all(d.get("opening", True) for d in debts), "repaid_loans": repaid,"unscheduled": left_rows, "unscheduled_total": sum(r["left"] for r in left_rows), "unknown_n": unknown_n,
            "payable_total": sum(d["balance"] for d in pays if d["balance"] is not None),
            "loans": known_loans, "loan_total": sum(d["balance"] for d in known_loans),
            "loan_unknown_n": sum(1 for d in loans if d["balance"] is None), "date": next((d["date"] for d in debts if d["date"]), "")}
