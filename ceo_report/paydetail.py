"""금요일 출금 목록의 상세 내역 (사용자 2026-11-03).

입력/출금상세.csv  거래처,금액,상세내역,출처
- 출처 '수기' = 대표보고 창에서 손으로 넣은 것, '지출결의서' = 인트라넷 지출결의서(관리팀 승인까지)에서 가져온 것.
- 지급 일정 줄과 같은 거래처(이름 정규화)·같은 금액이면 그 줄에 상세 내역을 붙인다. 같은 줄에 둘 다 있으면 수기를 먼저 쓴다.
- 금액을 모르는 일정 줄에는 붙이지 않는다 (다른 지급에 잘못 붙지 않게).
"""
import csv
import os

DETAIL_FILE = "출금상세.csv"
DETAIL_COLUMNS = ["거래처", "금액", "상세내역", "출처"]
MANUAL, INTRANET = "수기", "지출결의서"


def _norm(name):
    from .wehago import norm_vendor
    return norm_vendor(name)


def _amount(text):
    t = str(text or "").replace(",", "").replace("원", "").strip()
    return int(t) if t.lstrip("-").isdigit() else None


def read_checked(input_dir):
    """-> (줄 목록, None) 또는 (None, 못 읽은 까닭). 파일이 없으면 ([], None). UTF-8·CP949 모두 읽는다 (C5·P5-22)."""
    path = os.path.join(input_dir, DETAIL_FILE)
    if not os.path.exists(path):
        return [], None
    from .util import Issues, read_csv
    iss, info = Issues(), {}
    rows, ok = read_csv(path, DETAIL_COLUMNS[:3], iss, info)
    if not ok or info.get("missing"):
        return None, "; ".join(m for _, _, m in iss.items) or "읽지 못함"
    out = []
    for r in rows:
        v, a, t = (r.get("거래처") or "").strip(), _amount(r.get("금액")), (r.get("상세내역") or "").strip()
        if v and a is not None and t:
            out.append({"vendor": v, "amount": a, "text": t, "source": (r.get("출처") or MANUAL).strip() or MANUAL})
    return out, None


def read(input_dir):
    """-> [{"vendor", "amount", "text", "source"}]. 파일이 없거나 못 읽으면 [] (까닭은 read_checked)."""
    rows, _ = read_checked(input_dir)
    return rows or []


def save(input_dir, vendor, amount, text, source=MANUAL):
    """한 줄을 넣거나 고친다 (같은 거래처·금액·출처면 바꿈). 상세내역이 비면 그 줄을 지운다. -> 전체 줄 수."""
    vendor, text = (vendor or "").strip(), (text or "").strip()
    a = _amount(amount)
    if not vendor:
        raise ValueError("거래처를 넣으세요")
    if a is None or a <= 0:
        raise ValueError("금액은 원 단위 숫자 (예: 3,300,000)")
    if not os.path.isdir(input_dir):
        raise ValueError("입력 폴더가 없습니다: %s" % input_dir)
    have, why = read_checked(input_dir)
    if have is None:   # 못 읽은 파일을 새 한 줄로 덮어 있던 상세를 지우지 않는다 (P5-22)
        raise ValueError("%s 을 읽지 못해 저장하지 않음 (%s) — 엑셀에서 열려 있으면 닫고 다시 하세요. 파일은 그대로 둠" % (DETAIL_FILE, why))
    rows = [r for r in have
            if not (_norm(r["vendor"]) == _norm(vendor) and r["amount"] == a and r["source"] == source)]
    if text:
        rows.append({"vendor": vendor, "amount": a, "text": text, "source": source})
    path = os.path.join(input_dir, DETAIL_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(DETAIL_COLUMNS)
        for r in rows:
            w.writerow([r["vendor"], r["amount"], r["text"], r["source"]])
    os.replace(tmp, path)
    return len(rows)


def attach(events, details):
    """지급 일정 줄에 e['detail'] 을 붙인다 (같은 거래처·같은 금액, 수기 먼저). 붙인 줄 수.
    2차 P5-21 (2026-11-15): 상세 한 줄은 일정 한 줄에만 — 같은 거래처·금액이 여러 달 있으면 가장 이른 줄에만 붙인다
    (같은 상세가 두 달에 붙었음)."""
    by = {}
    for d in details:
        k = (_norm(d["vendor"]), d["amount"])
        if k not in by or (d["source"] == MANUAL and by[k]["source"] != MANUAL):
            by[k] = d
    n, used = 0, set()
    outs = [e for e in events if e.get("io") == "out" and e.get("amount") is not None]
    for e in sorted(outs, key=lambda e: (e.get("date") is None, e.get("date") or 0)):
        k = (_norm(e.get("desc") or ""), e["amount"])
        d = by.get(k)
        if d and k not in used:
            used.add(k)
            e["detail"], e["detail_source"] = d["text"], d["source"]
            n += 1
    return n
