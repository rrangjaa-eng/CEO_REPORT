"""프로젝트.csv · 프로젝트집행.csv 만들기 (Phase 2, D-42, D-49, D-50).

두 함수는 줄 목록을 받아 convert.Table 을 돌려주는 순수 함수다. 파일을 읽거나 쓰지 않는다 (연결은 02-07 의 convert.run).
- build_projects: 인트라넷 프로젝트 목록 + WEHAGO 매출 연결분 (+ 이전 프로젝트.csv 에서 옮기는 수동 칸).
- build_execs: WEHAGO (도) 원가 줄 + 아직 장부에 없는 인트라넷 지급요청 (같은 지출을 두 번 넣지 않는다).
모르는 값은 '' 이고 0이 아니다 (D-02). 지출을 적게 잡지 않는다: 애매하면 요청 줄로 두고 '중복 가능'으로 알린다.
"""
import re

from . import data
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
