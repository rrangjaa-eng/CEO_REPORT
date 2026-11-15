"""홈택스 전자(세금)계산서 목록 ↔ 장부(분개장 매입·매출 전표) 대조 (사용자 2026-11-05: 편의 기능 7).

홈택스 → 조회/발급 → 전자(세금)계산서 → 목록조회 에서 매출·매입 목록을 엑셀로 내려받아
수집\\홈택스 폴더에 넣으면 '자료 변환' 때 장부와 맞춰 본다 (홈택스에 있는데 장부에 없는 계산서, 장부 매출에만 있는 계산서).
· 매출·매입 구분: 파일 안에서 공급자 사업자번호가 모든 줄에 같으면 우리 회사가 공급자 = 매출, 공급받는자가 같으면 매입.
  (파일 이름에 '매출'·'매입'이 있으면 그것을 먼저 따른다)
· 맞추기: 작성일자·합계금액·거래처(이름) 같은 전표 → 없으면 합계금액·거래처가 같고 날짜가 31일 안 → 없으면 같은 날·같은 합계.
· 장부를 바꾸지 않는다. 결과 글에는 건수·금액·날짜·승인번호 끝 8자리만 쓴다 (화면 목록에는 거래처 이름을 보인다).
"""
import datetime as dt
import os
import re

from .wehago import WehagoError, invoices_from_journal, norm_vendor, read_xlsx
from .xls import XlsError, read_xls

FOLDER = "홈택스"
NEED = ("작성일자", "승인번호", "합계금액", "공급가액", "세액")
NEAR_DAYS = 31


def _cell(v):
    return re.sub(r"\s+", "", str(v if v is not None else ""))


def _num(v):
    if isinstance(v, (int, float)):
        return int(round(v))
    t = str(v or "").replace(",", "").replace("원", "").strip()
    try:
        return int(round(float(t)))
    except ValueError:
        return None


def _day(v):
    if isinstance(v, (int, float)) and 20000 < v < 80000:   # 엑셀 날짜 숫자
        return dt.date(1899, 12, 30) + dt.timedelta(days=int(v))
    t = re.sub(r"[^0-9]", "", str(v or ""))
    if len(t) >= 8:
        try:
            return dt.date(int(t[:4]), int(t[4:6]), int(t[6:8]))
        except ValueError:
            return None
    return None


def _read(path):
    if path.lower().endswith(".xlsx"):
        return read_xlsx(path)
    return read_xls(path)


def parse_rows(rows, name="", info=None):
    """엑셀 행 목록 -> (방향 '매출'/'매입'/None, [계산서 dict]). 머리글 줄은 '승인번호'·'합계금액'이 있는 첫 줄.
    info(dict)를 주면 info['bad'] = 날짜·합계금액을 읽지 못해 뺀 줄 수 (2차 P1-19: 예전엔 말없이 버렸음 — 빈 줄·합계 줄은 세지 않음)."""
    head_i = None
    for i, r in enumerate(rows[:40]):
        cells = [_cell(c) for c in r]
        if "승인번호" in cells and "합계금액" in cells:
            head_i = i
            break
    if head_i is None:
        raise ValueError("머리글(승인번호·합계금액)을 찾지 못함")
    head = [_cell(c) for c in rows[head_i]]
    missing = [h for h in NEED if h not in head]
    if missing:
        raise ValueError("열이 없음: %s" % ", ".join(missing))
    col = {h: head.index(h) for h in NEED}
    regs = [i for i, h in enumerate(head) if h.endswith("사업자등록번호") or h == "등록번호"]
    names = [i for i, h in enumerate(head) if h == "상호"]
    sup_reg, buy_reg = (regs + [None, None])[:2]
    sup_name, buy_name = (names + [None, None])[:2]
    out, bad = [], 0
    for r in rows[head_i + 1:]:
        get = lambda i: r[i] if i is not None and i < len(r) else ""
        day, total = _day(get(col["작성일자"])), _num(get(col["합계금액"]))
        if day is None or total is None:
            cells = [_cell(c) for c in r]
            if any(cells) and not any(re.sub(r"\s", "", c) in ("합계", "소계", "총계", "총합계") for c in cells):
                bad += 1
            continue
        out.append({"date": day, "no": _cell(get(col["승인번호"])), "total": total, "supply": _num(get(col["공급가액"])) or 0,
                    "vat": _num(get(col["세액"])) or 0, "sup_reg": _cell(get(sup_reg)), "buy_reg": _cell(get(buy_reg)),
                    "sup_name": str(get(sup_name)).strip(), "buy_name": str(get(buy_name)).strip()})
    side = "매출" if "매출" in name else ("매입" if "매입" in name else None)
    if side is None and out:
        if len(set(x["sup_reg"] for x in out)) == 1 and len(set(x["buy_reg"] for x in out)) > 1:
            side = "매출"
        elif len(set(x["buy_reg"] for x in out)) == 1 and len(set(x["sup_reg"] for x in out)) > 1:
            side = "매입"
        elif len(out) == 1:
            side = None
    for x in out:
        x["vendor"] = x["buy_name"] if side == "매출" else x["sup_name"]
        x["vendor_norm"] = norm_vendor(x["vendor"])
    if info is not None:
        info["bad"] = bad
    return side, out


def load(collect_dir):
    """수집\\홈택스 의 엑셀을 모두 읽는다 -> ({'매출': [...], '매입': [...]}, 알림 줄). 같은 승인번호는 한 번만."""
    folder = os.path.join(collect_dir, FOLDER)
    got, notes, seen = {"매출": [], "매입": []}, [], set()
    try:
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith((".xls", ".xlsx")) and not n.startswith("~$"))
    except OSError:
        return got, notes
    for n in names:
        info = {}
        try:
            side, rows = parse_rows(_read(os.path.join(folder, n)), n, info)
        except (XlsError, WehagoError, ValueError, OSError) as e:
            notes.append("홈택스 %s 읽지 못함: %s" % (n, e if isinstance(e, ValueError) else type(e).__name__))
            continue
        if side is None:
            notes.append("홈택스 %s: 매출·매입을 알 수 없음 — 파일 이름에 '매출' 또는 '매입'을 넣어 주세요" % n)
            continue
        # 2차 P1-20: 같은 파일 안의 같은 승인번호도 한 번만 · 승인번호가 빈 계산서는 서로 다른 것으로 둔다 (예전엔 둘째부터 빠졌음)
        #   빈 승인번호는 (날짜·금액·두 사업자번호)로 다른 파일과만 맞춰 본다 (겹치게 받은 파일에서 두 번 세지 않게)
        new, dup, blank = [], 0, set()
        for r in rows:
            if r["no"]:
                if r["no"] in seen:
                    dup += 1
                    continue
                seen.add(r["no"])
            else:
                k = ("", r["date"], r["total"], r["sup_reg"], r["buy_reg"])
                if k in seen:
                    dup += 1
                    continue
                blank.add(k)
            new.append(r)
        seen.update(blank)
        got[side].extend(new)
        extra = []
        if dup:
            extra.append("같은 승인번호 %d건은 한 번만" % dup)
        if info.get("bad"):
            extra.append("날짜·합계금액을 읽지 못한 줄 %d건 뺌 — 엑셀에서 확인하세요" % info["bad"])
        notes.append("홈택스 %s: %s %d건 %s원%s" % (n, side, len(new), "{:,}".format(sum(r["total"] for r in new)),
                                                 (" (%s)" % " · ".join(extra)) if extra else ""))
    return got, notes


def _match(ht, books_rows):
    """홈택스 계산서마다 장부 전표 하나를 짝짓는다 -> (홈택스만, 장부만(기간 안), 짝 수)."""
    used = set()
    left = []
    by_total = {}
    for k, b in enumerate(books_rows):
        by_total.setdefault(b["total"], []).append(k)
    passes = (lambda h, b: b["date"] == h["date"] and b["vendor_norm"] == h["vendor_norm"],
              lambda h, b: abs((b["date"] - h["date"]).days) <= NEAR_DAYS and b["vendor_norm"] == h["vendor_norm"],
              lambda h, b: b["date"] == h["date"])
    todo = list(ht)
    for test in passes:
        rest = []
        for h in todo:
            hit = next((k for k in by_total.get(h["total"], []) if k not in used and test(h, books_rows[k])), None)
            if hit is None:
                rest.append(h)
            else:
                used.add(hit)
        todo = rest
    left = todo
    if ht:
        lo, hi = min(h["date"] for h in ht), max(h["date"] for h in ht)
        only_books = [b for k, b in enumerate(books_rows) if k not in used and lo <= b["date"] <= hi]
    else:
        only_books = []
    return left, only_books, len(ht) - len(left)


def compare(collect_dir, journal):
    """-> {'notes': [글], 'items': [확인할 것 dict]}. 홈택스 폴더가 없거나 비었으면 notes 만 빈 목록."""
    got, notes = load(collect_dir)
    items = []
    if not got["매출"] and not got["매입"]:
        return {"notes": notes, "items": items}
    buys, sales = invoices_from_journal(journal)
    codes = {}   # 거래처 이름 -> 분개장 거래처코드 (화면에 '이름 [코드]'로 보이려고, 사용자 2026-11-05)
    for ln in journal:
        c = (ln.get("vendor_code") or "").strip()
        if c and ln.get("vendor"):
            codes.setdefault(norm_vendor(ln["vendor"]), c)
    for side, ht, rows in (("매출", got["매출"], sales), ("매입", got["매입"], buys)):
        if not ht:
            continue
        only_ht, only_books, ok = _match(ht, rows)
        if side == "매입":
            only_books = []   # 장부 매입에는 카드·현금영수증 매입도 있어 홈택스 계산서와 1:1 이 아니다 → 홈택스 쪽만 본다
        notes.append("홈택스 %s 대조: 홈택스 %d건 중 장부와 맞음 %d건 · 홈택스에만 %d건 %s원%s" % (
            side, len(ht), ok, len(only_ht), "{:,}".format(sum(h["total"] for h in only_ht)),
            " · 장부에만(같은 기간) %d건 %s원" % (len(only_books), "{:,}".format(sum(b["total"] for b in only_books)))
            if side == "매출" else ""))
        for h in only_ht:
            notes.append("  홈택스에만 %s %s 승인번호 …%s %s원" % (side, h["date"].isoformat(), h["no"][-8:], "{:,}".format(h["total"])))
            items.append({"id": "홈택스|%s" % h["no"], "kind": "홈택스 대조", "date": h["date"].isoformat(), "amount": h["total"],
                          "title": "홈택스에는 있는데 장부에 없는 %s 계산서" % side, "vendor": h["vendor"],
                          "vcode": codes.get(h["vendor_norm"], ""),
                          "detail": "작성일자 %s · 승인번호 %s · 공급가액 %s원 · 세액 %s원" % (
                              h["date"].isoformat(), h["no"], "{:,}".format(h["supply"]), "{:,}".format(h["vat"])),
                          "choices": ["위하고에 넣을 것", "장부에 다른 날짜·금액으로 있음", "취소·수정된 계산서"]})
        for b in only_books:
            items.append({"id": "홈택스장부|%s|%s" % (b["date"].isoformat(), b["no"]), "kind": "홈택스 대조",
                          "date": b["date"].isoformat(), "amount": b["total"], "title": "장부 매출에만 있는 계산서 (홈택스 목록에 없음)",
                          "vendor": b["vendor"], "vcode": codes.get(b.get("vendor_norm") or norm_vendor(b["vendor"]), ""), "detail": "전표 %s %s · 합계 %s원" % (b["date"].isoformat(), b["no"], "{:,}".format(b["total"])),
                          "choices": ["카드·현금 매출이라 정상", "발급 누락 — 계산서 발급할 것", "장부 잘못 — 고칠 것"]})
    return {"notes": notes, "items": items}
