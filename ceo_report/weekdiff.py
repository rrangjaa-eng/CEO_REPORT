"""주간 보고: 지난주 예상 대비 이번 주 지급 변동 (사용자 2026-11-03).

주간 보고서를 만들 때마다 기준일 다음 날부터 14일 안의 지급 예정을 출력 폴더의 지급예정기록/지급예정_<기준일>.csv 로 남긴다.
다음 주 보고는 1~14일 전 기록 중 가장 최근 것을 읽어, 그 기록이 '이번 주(기준일 다음 날부터 7일)'에 나간다고 예상한 지급과
지금의 이번 주 지급 예정을 비교한다. 금액을 모르는 줄은 0으로 치지 않는다 (합계 변동은 '미확인').
"""
import csv
import datetime as dt
import os
import re

from .util import mask_rrn

RECORD_DIR = "지급예정기록"
COLUMNS = ["기준일", "예정일", "거래처·내용", "프로젝트", "구분", "금액", "확정여부"]
HORIZON = 14
LOOKBACK = 14


def _rows_ahead(R):
    asof, end = R["asof"], R["asof"] + dt.timedelta(days=HORIZON)
    rows = [e for e in R["events"] if e["io"] == "out" and e["date"] is not None and asof < e["date"] <= end]
    return sorted(rows, key=lambda e: (e["date"], -(e["amount"] or 0)))


def write_record(out_dir, R):
    folder = os.path.join(out_dir, RECORD_DIR)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "지급예정_%s.csv" % R["asof"].isoformat())
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for e in _rows_ahead(R):
            w.writerow([R["asof"].isoformat(), e["date"].isoformat(), mask_rrn(e.get("desc") or ""),   # 주민번호 모양은 가림 (D-36)
                        mask_rrn(e.get("project") or ""), mask_rrn(e.get("cat") or ""), "" if e["amount"] is None else str(e["amount"]), "확정" if e["firm"] else "예상"])
    return path


def load_previous(out_dir, asof):
    """1~14일 전 기록 중 가장 최근 것 -> {"asof", "rows"} 또는 None. 읽을 수 없는 기록은 없는 것으로 본다."""
    folder = os.path.join(out_dir, RECORD_DIR)
    if not os.path.isdir(folder):
        return None
    found = []
    for name in os.listdir(folder):
        m = re.match(r"^지급예정_(\d{4}-\d{2}-\d{2})\.csv$", name)
        if not m:
            continue
        try:
            day = dt.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if asof - dt.timedelta(days=LOOKBACK) <= day < asof:
            found.append((day, os.path.join(folder, name)))
    if not found:
        return None
    day, path = max(found)
    rows = []
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                amt = (r.get("금액") or "").strip()
                rows.append({"date": dt.date.fromisoformat(r["예정일"]), "io": "out",
                             "amount": int(amt) if amt else None, "desc": r.get("거래처·내용", ""),
                             "project": r.get("프로젝트", ""), "cat": r.get("구분", ""), "firm": r.get("확정여부") == "확정"})
    except (OSError, ValueError, KeyError, csv.Error):
        return None
    return {"asof": day, "rows": rows}


def _key(e):
    return (e.get("desc") or "", e.get("project") or "", e.get("cat") or "")


def compare(prev, cur_rows, start, end):
    """지난주 기록 prev 의 [start, end] 지급 vs 지금 목록 cur_rows 의 [start, end] 지급 (예정일 지난 미처리는 뺀다).

    같은 (거래처·내용, 프로젝트, 구분)끼리 금액 순으로 짝짓는다. 바뀐 것만 changes 에 싣는다."""
    def within(rows):
        return [e for e in rows if e["date"] is not None and start <= e["date"] <= end]
    old, new = within(prev["rows"]), within(cur_rows)
    groups = {}
    for side, rows in ((0, old), (1, new)):
        for e in rows:
            groups.setdefault(_key(e), ([], []))[side].append(e)
    changes, by_cur = [], {}
    for key, (a, b) in groups.items():
        a = sorted(a, key=lambda e: (e["amount"] is None, e["amount"] or 0, e["date"]))
        b = sorted(b, key=lambda e: (e["amount"] is None, e["amount"] or 0, e["date"]))
        for i in range(max(len(a), len(b))):
            p = a[i] if i < len(a) else None
            c = b[i] if i < len(b) else None
            if p is None:
                kind = "새로 생김"
            elif c is None:
                kind = "빠짐"
            elif p["amount"] != c["amount"]:
                kind = "금액 확인됨" if p["amount"] is None else ("금액 미확인" if c["amount"] is None else "금액 바뀜")
            elif p["date"] != c["date"]:
                kind = "날짜 바뀜"
            else:
                by_cur[id(c)] = {"kind": "같음", "prev": p["amount"], "cur": c["amount"], "prev_date": p["date"]}
                continue
            ref = c or p
            changes.append({"kind": kind, "desc": key[0], "project": key[1], "cat": key[2],
                            "prev": p["amount"] if p else None, "cur": c["amount"] if c else None,
                            "prev_date": p["date"] if p else None, "cur_date": c["date"] if c else None, "date": ref["date"]})
            if c is not None:
                by_cur[id(c)] = changes[-1]
    changes.sort(key=lambda c: (c["date"], c["desc"]))

    def total(rows):
        known = [e["amount"] for e in rows if e["amount"] is not None]
        return sum(known), len(rows) - len(known)
    pt, pu = total(old)
    ct, cu = total(new)
    return {"asof": prev["asof"], "prev_total": pt, "cur_total": ct, "prev_unknown": pu, "cur_unknown": cu,
            "prev_n": len(old), "cur_n": len(new), "diff": None if (pu or cu) else ct - pt, "changes": changes,
            "by_cur": by_cur}   # id(지금 줄) -> 그 줄의 변동 (같음 포함). 빠진 것은 changes 에서 kind == "빠짐"
