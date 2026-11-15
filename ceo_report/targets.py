"""팀별 연간 목표 (사용자 2026-11-03: 월간 누적 실적에 목표 대비).

입력/팀목표.csv  연도,팀,매출목표,목표수익률
- 매출목표 = 그 해 팀 매출 목표(원), 목표수익률 = 매출총이익률 목표(%). 대표보고 창 '⑧ 팀 목표'로 넣는다.
"""
import csv
import os

TARGET_FILE = "팀목표.csv"
TARGET_COLUMNS = ["연도", "팀", "매출목표", "목표수익률"]


def _int(text):
    t = str(text or "").replace(",", "").replace("원", "").strip()
    return int(t) if t.isdigit() else None


def _rate(text):
    t = str(text or "").replace("%", "").strip()
    try:
        v = float(t)
    except ValueError:
        return None
    return v if 0 <= v <= 100 else None


def read(input_dir):
    """-> {(연도, 팀): {"revenue": 원 또는 None, "rate": % 또는 None}}."""
    path = os.path.join(input_dir, TARGET_FILE)
    out = {}
    if not os.path.exists(path):
        return out
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                y, team = (r.get("연도") or "").strip(), (r.get("팀") or "").strip()
                if y.isdigit() and team:
                    out[(y, team)] = {"revenue": _int(r.get("매출목표")), "rate": _rate(r.get("목표수익률"))}
    except (OSError, UnicodeDecodeError, csv.Error):
        return {}
    return out


def save(input_dir, year, team, revenue, rate):
    """한 팀의 목표를 넣거나 고친다. -> 그 해 목표 줄 수."""
    y, team = str(year or "").strip(), (team or "").strip()
    if not (y.isdigit() and len(y) == 4):
        raise ValueError("연도는 4자리 (예: 2026)")
    if not team:
        raise ValueError("팀 이름을 넣으세요 (예: 기획1팀)")
    rev, rt = _int(revenue), _rate(rate)
    if rev is None or rev <= 0:
        raise ValueError("연간 매출 목표는 원 단위 숫자 (예: 1,200,000,000)")
    if rt is None:
        raise ValueError("목표 수익률은 0~100 사이 숫자 (예: 32)")
    if not os.path.isdir(input_dir):
        raise ValueError("입력 폴더가 없습니다: %s" % input_dir)
    cur = read(input_dir)
    cur[(y, team)] = {"revenue": rev, "rate": rt}
    path = os.path.join(input_dir, TARGET_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(TARGET_COLUMNS)
        for (yy, tt), v in sorted(cur.items()):
            w.writerow([yy, tt, "" if v["revenue"] is None else v["revenue"], "" if v["rate"] is None else ("%g" % v["rate"])])
    os.replace(tmp, path)
    return sum(1 for (yy, _) in cur if yy == y)
