"""손익.csv 만들기 (D-40): WEHAGO 분개장 줄 → 달별 회사 줄 (매출·직접비·공통비).

계정 코드와 표시 낱말은 모두 설정(cfg, convert.read_config)에서 온다 (D-39). 이 파일에는 계정 코드를 쓰지 않는다.
모르는 값은 0이 아니라 빈칸이다 (D-02): 금액 칸이 비어 있는 줄이 있는 달은 그 칸을 비우고 알린다.
"""
import re
from collections import OrderedDict

from . import data
from .convert import Check, Table, cell_amount
from .util import num, won

CATEGORIES = (("revenue", "매출", "매출"), ("direct", "직접비", "직접비"), ("common", "공통비", "공통비"))


def _squash(text):
    return re.sub(r"\s+", "", text or "")


def _classify(line, cfg):
    """분개장 줄 하나의 종류: revenue | direct | common | common_unmarked | excluded | None (대차대조표 줄 등)."""
    code = _squash(line["account_code"])
    name = _squash(line["account"])
    if code in cfg["revenue_codes"]:
        return "revenue"
    if re.match(r"^[0-9]{5}$", code):
        if code.startswith(tuple(cfg["direct_prefixes"])) and _squash(cfg["direct_mark"]) in name:
            return "direct"
        if code.startswith(tuple(cfg["common_prefixes"])):
            return "common" if _squash(cfg["common_mark"]) in name else "common_unmarked"
    if re.match(r"^[4-9][0-9]*$", code):
        return "excluded"
    return None


def _net(line, kind):
    """줄의 금액: 매출은 대변−차변, 그 밖의 손익 줄은 차변−대변. 차변·대변이 모두 비면 None."""
    d, c = line["debit"], line["credit"]
    if d is None and c is None:
        return None
    return (c or 0) - (d or 0) if kind == "revenue" else (d or 0) - (c or 0)


def _prefix_text(prefixes):
    return ",".join(p + "x" * max(0, 5 - len(p)) for p in prefixes)


def _labels(cfg):
    return {"revenue": "매출 (%s 대변−차변)" % ",".join(cfg["revenue_codes"]),
            "direct": "직접비 (%s %s 차변−대변)" % (_prefix_text(cfg["direct_prefixes"]), cfg["direct_mark"]),
            "common": "공통비 (%s 차변−대변)" % _prefix_text(cfg["common_prefixes"])}


def _pl_rows(books, cfg):
    """(월 → 종류 → [합계, 금액 없는 줄 수]), 날짜 없는 줄, 종류별 원본 합계, 넣지 않은 계정, 표시 없는 공통비, 결산한 해."""
    months = set()
    closed = set()
    closing = set(_squash(s) for s in cfg["closing_sorts"])
    for line in books.journal:
        if line["date"] is not None:
            months.add(line["date"].strftime("%Y-%m"))
            if _squash(line.get("sort", "")) in closing:
                closed.add(line["date"].year)
    per = OrderedDict((m, dict((k, [0, 0]) for k, _, _ in CATEGORIES)) for m in sorted(months))
    undated = dict((k, [0, 0, 0]) for k, _, _ in CATEGORIES)  # 줄 수, 알려진 금액 합, 금액 없는 줄 수
    source = dict((k, 0) for k, _, _ in CATEGORIES)
    excluded = OrderedDict()
    unmarked = OrderedDict()
    for line in books.journal:
        kind = _classify(line, cfg)
        if kind is None:
            continue
        if kind == "excluded":
            key = (_squash(line["account_code"]), line["account"])
            g = excluded.setdefault(key, [0, 0, 0])
            g[0] += 1
            amount = _net(line, "excluded")
            if amount is None:
                g[2] += 1
            else:
                g[1] += amount
            continue
        cat = "common" if kind == "common_unmarked" else kind
        amount = _net(line, cat)
        if kind == "common_unmarked":
            g = unmarked.setdefault((_squash(line["account_code"]), line["account"]), [0, 0, 0])
            g[0] += 1
            if amount is None:
                g[2] += 1
            else:
                g[1] += amount
        if amount is not None:
            source[cat] += amount
        if line["date"] is None:
            u = undated[cat]
            u[0] += 1
            if amount is None:
                u[2] += 1
            else:
                u[1] += amount
            continue
        cell = per[line["date"].strftime("%Y-%m")][cat]
        if amount is None:
            cell[1] += 1
        else:
            cell[0] += amount
    return per, undated, source, excluded, unmarked, closed


def _listing(groups):
    parts = []
    for (code, name), (n, total, unknown) in sorted(groups.items()):
        text = "%s %s %d줄 %s" % (code, name, n, won(total))
        if unknown:
            text += " (금액 없음 %d줄 제외)" % unknown
        parts.append(text)
    return " · ".join(parts)


UNLINKED_PROJECT = "프로젝트 미연결"
UNLINKED_TEAM = "미연결"
MEASURES = (("revenue", "매출"), ("direct", "직접비"))   # 팀·프로젝트 줄에 싣는 값 (공통비는 배분 규칙이 없어 비움)


def _unit_totals(links):
    """달 → 프로젝트 키(미연결은 None) → {revenue, direct: [합계, 금액 모르는 줄 수]}. 날짜 없는 줄은 어느 달에도 없다."""
    acc = OrderedDict()
    for measure, result in (("direct", links["costs"]), ("revenue", links["revenue"])):
        for ln in result["lines"]:
            if ln["date"] is None:
                continue
            units = acc.setdefault(ln["date"].strftime("%Y-%m"), OrderedDict())
            cell = units.setdefault(ln["project"], {"revenue": [0, 0], "direct": [0, 0]})[measure]
            if ln["amount"] is None:
                cell[1] += 1
            else:
                cell[0] += ln["amount"]
    return acc


def _project_order(keys, projects):
    """프로젝트 줄 순서: 스냅숏 프로젝트 목록 순서, 목록에 없는 열쇠(수동 지정)는 열쇠순, 미연결(None)은 맨 뒤. 스냅숏이 없으면 열쇠순."""
    real = [k for k in keys if k is not None]
    listed = [k for k in projects if k in real]
    rest = sorted((k for k in real if k not in projects), key=str)
    return listed + rest + ([None] if None in keys else [])


def _cell(pair):
    return None if pair[1] else pair[0]


def _team_of(key, projects):
    if key is None:
        return UNLINKED_TEAM
    if key not in projects:
        return "팀 미확인"
    return (projects[key]["team"] or "").strip() or "팀 미지정"


def _team_totals(units, projects):
    """프로젝트 열쇠별 합계 → 팀별 합계 (순서: 팀 이름순, 미연결 맨 뒤). 모르는 금액은 팀 칸도 모른다."""
    teams = {}
    for key, cells in units.items():
        t = teams.setdefault(_team_of(key, projects), {"revenue": [0, 0], "direct": [0, 0]})
        for measure, _ in MEASURES:
            t[measure][0] += cells[measure][0]
            t[measure][1] += cells[measure][1]
    names = sorted(n for n in teams if n != UNLINKED_TEAM) + ([UNLINKED_TEAM] if UNLINKED_TEAM in teams else [])
    return OrderedDict((n, teams[n]) for n in names)


def _team_row(columns, ym, name, cells, final):
    values = ["WEHAGO", ym, "팀", name, cell_amount(_cell(cells["revenue"])), cell_amount(_cell(cells["direct"])),
              "", "" if final else "Y"]
    return dict(zip(columns, values))


def _unit_checks(ym, company, kind, groups):
    """달·종류(매출/직접비)마다 한 줄: 회사 칸 = 팀(또는 프로젝트) 칸 합계 (미연결 포함). 모르는 칸이 하나라도 있으면 '판단 불가'."""
    out = []
    for measure, label in MEASURES:
        unknown = any(g[measure][1] for g in groups)
        out.append(Check("%s %s %s 합계(미연결 포함) = 회사" % (label, ym, kind), company[measure],
                         None if unknown else sum(g[measure][0] for g in groups)))
    return out


def _project_row(columns, ym, key, cells, projects, snapshot, final):
    if key is None:
        target = UNLINKED_PROJECT
    elif not snapshot:
        target = key
    elif key in projects:
        target = ("%s %s" % (key, projects[key]["name"])).strip()
    else:
        target = "%s (프로젝트 목록에 없음)" % key
    values = ["WEHAGO", ym, "프로젝트", target, cell_amount(_cell(cells["revenue"])), cell_amount(_cell(cells["direct"])),
              "", "" if final else "Y"]
    return dict(zip(columns, values))


def _month_span(months):
    """['2026-09', '2026-10'] -> 처음 달부터 마지막 달까지 모든 달 (빈 목록이면 빈 집합)."""
    if not months:
        return set()
    first, last = min(months), max(months)
    y, m = int(first[:4]), int(first[5:7])
    out = set()
    while "%04d-%02d" % (y, m) <= last:
        out.add("%04d-%02d" % (y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _ranges(months):
    """달 목록 -> '2026-01~2026-08, 2026-11' (이어지는 달은 묶는다; 달 모양이 아닌 글자는 그대로)."""
    good = sorted(m for m in set(months) if re.match(r"^\d{4}-\d{2}$", m))
    odd = sorted(m for m in set(months) if not re.match(r"^\d{4}-\d{2}$", m))
    parts, start, prev = [], None, None
    for m in good:
        if prev is not None and _month_span([prev, m]) == {prev, m}:
            prev = m
            continue
        if start is not None:
            parts.append(start if start == prev else "%s~%s" % (start, prev))
        start = prev = m
    if start is not None:
        parts.append(start if start == prev else "%s~%s" % (start, prev))
    return ", ".join(parts + [o or "(연월 없음)" for o in odd])


def _ym(row):
    return (row.get("연월") or "").strip()[:7]


def _company_sum(rows, year, measure):
    """WEHAGO 회사 줄 중 그 해 줄의 칸 합계. 모르는 칸이 하나라도 있으면 None."""
    total = 0
    for r in rows:
        if r.get("출처", "") == "WEHAGO" and r.get("단위", "") == "회사" and _ym(r).startswith(year + "-"):
            v = num(r.get(measure))
            if v is None:
                return None
            total += v
    return total


def _kept_row(columns, r):
    """이전 변환에서 유지하는 WEHAGO 줄: 금액 칸은 이 파일의 모양(쉼표 없는 정수)으로, 읽을 수 없는 글자는 그대로 둔다."""
    out = dict((c, (r.get(c) or "").strip()) for c in columns)
    for c in ("매출", "직접비", "공통비"):
        v = num(out[c])
        if v is not None:
            out[c] = cell_amount(v)
    return out


def ytd_checks(per_company, prev_rows, rows):
    """올해 누계 대조 (CR-04): CSV 회사 줄의 올해 합 = 새 분개장의 올해 합 + 새 분개장 기간 밖이라 이전 변환에서 유지한 달의 합.

    per_company: 새 분개장 달 -> {revenue, direct, common} 회사 칸 (모르면 None). 올해 = 새 분개장 마지막 달의 해.
    기대값은 이전 손익.csv 와 분개장 기간에서 바로 구한다: 기간 밖 달을 버리면 CSV 쪽이 모자라 '불일치' (CSV 누계 ≥ 새 분개장 누계).
    """
    months = sorted(per_company)
    if not months:
        return []
    covered = _month_span(months)
    year = months[-1][:4]
    kept = [r for r in prev_rows if r.get("출처", "") == "WEHAGO" and _ym(r) not in covered]
    out = []
    for key, label, measure in CATEGORIES:
        new = 0
        for ym in months:
            if ym.startswith(year + "-"):
                v = per_company[ym][key]
                new = None if v is None or new is None else new + v
        old = _company_sum(kept, year, measure)
        source = None if new is None or old is None else new + old
        out.append(Check("올해(%s) 누계 %s: 새 분개장 + 이전 변환 유지 달 = CSV 회사 줄" % (year, label), source,
                         _company_sum(rows, year, measure)))
    return out


def build_pl(books, cfg, prev_rows, links=None):
    """손익.csv Table: 달마다 회사 줄, 프로젝트 줄 순서로 WEHAGO 줄을 쓰고, 이전 손익.csv 의 WEHAGO 외 출처 줄을 그대로 잇는다 (P1-2).

    links 가 None 이면 회사 줄만 만든다. 아니면 {"costs", "revenue", "projects", "snapshot"} (linking 결과)이고
    연결 안 된 금액도 '프로젝트 미연결' 줄에 싣는다 (D-40). 팀·프로젝트 줄의 공통비는 늘 빈칸이다 (배분 규칙 없음).
    """
    columns = data.SCHEMA["손익.csv"]
    per, undated, source, excluded, unmarked, closed = _pl_rows(books, cfg)
    rows, notes = [], []
    csv_sum = dict((k, 0) for k, _, _ in CATEGORIES)
    csv_unknown = dict((k, False) for k, _, _ in CATEGORIES)
    unit_totals = _unit_totals(links) if links is not None else {}
    unit_checks = []
    per_company = OrderedDict()
    for ym, cats in per.items():
        cells = {}
        for key, label, _ in CATEGORIES:
            total, unknown = cats[key]
            if unknown:
                cells[key] = None
                csv_unknown[key] = True
                notes.append("금액 없는 손익 줄 %d건 (%s %s) → 그 달 칸 비움" % (unknown, ym, label))
            else:
                cells[key] = total
                csv_sum[key] += total
        per_company[ym] = dict(cells)
        values = ["WEHAGO", ym, "회사", "회사 전체", cell_amount(cells["revenue"]), cell_amount(cells["direct"]),
                  cell_amount(cells["common"]), "" if int(ym[:4]) in closed else "Y"]
        rows.append(dict(zip(columns, values)))
        if links is not None:
            final = int(ym[:4]) in closed
            units = unit_totals.get(ym, OrderedDict())
            company = {"revenue": cells["revenue"], "direct": cells["direct"]}
            if links["snapshot"]:   # 팀 이름은 인트라넷 프로젝트 목록에서만 온다 (P3-2)
                teams = _team_totals(units, links["projects"])
                rows.extend(_team_row(columns, ym, n, c, final) for n, c in teams.items())
                unit_checks.extend(_unit_checks(ym, company, "팀별", list(teams.values())))
            keys = _project_order(list(units), links["projects"])
            rows.extend(_project_row(columns, ym, k, units[k], links["projects"], links["snapshot"], final) for k in keys)
            unit_checks.extend(_unit_checks(ym, company, "프로젝트별", [units[k] for k in keys]))
    labels = _labels(cfg)
    checks = [Check(labels[k], source[k], None if csv_unknown[k] else csv_sum[k]) for k, _, _ in CATEGORIES]
    checks.extend(unit_checks)
    if links is not None:
        if not links["snapshot"]:
            notes.append("팀별 손익 없음 (인트라넷 스냅숏 없음)")
        notes.append("팀·프로젝트 줄의 공통비는 비워 둠 (배분 규칙 없음)")
    for key, label, _ in CATEGORIES:
        n, total, unknown = undated[key]
        if n:
            notes.append("날짜 없는 손익 줄 %d건 (%s) %s" % (n, label, won(total)) + (
                " · 금액 없음 %d건" % unknown if unknown else ""))
    if excluded:
        notes.append("손익.csv에 넣지 않은 손익 계정: " + _listing(excluded))
    if unmarked:
        notes.append("공통비 중 %s 표시 없음: %s (공통비에 넣음)" % (cfg["common_mark"], _listing(unmarked)))
    # CR-04: 이전 WEHAGO 줄은 새 분개장이 덮는 달(처음 전표 달 ~ 마지막 전표 달)만 바꾼다. 그 밖의 달은 그대로 둔다 (누계가 줄지 않게)
    dated = [line["date"] for line in books.journal if line["date"] is not None]
    if dated:
        notes.append("분개장 기간 %s~%s" % (min(dated).isoformat(), max(dated).isoformat()))
    covered = _month_span(list(per))
    carried = [r for r in prev_rows if r.get("출처", "") != "WEHAGO"]
    replaced = [r for r in prev_rows if r.get("출처", "") == "WEHAGO" and _ym(r) in covered]
    kept = [r for r in prev_rows if r.get("출처", "") == "WEHAGO" and _ym(r) not in covered]

    def unit_text(group):
        units = OrderedDict()
        for r in group:
            units[r.get("단위", "") or "(단위 없음)"] = units.get(r.get("단위", "") or "(단위 없음)", 0) + 1
        return " · ".join("%s %d" % (u, n) for u, n in units.items())
    if replaced:
        notes.append("이전 손익.csv의 WEHAGO 줄 %d건(%s)은 새로 만든 줄로 바꿈" % (len(replaced), unit_text(replaced)))
    if kept:
        span = ("%s~%s" % (min(covered), max(covered))) if covered else "전표 없음"
        notes.append("이전 변환 유지 %s (WEHAGO 줄 %d건: %s) — 새 분개장(%s)에 없는 달"
                     % (_ranges([_ym(r) for r in kept]), len(kept), unit_text(kept), span))
        first = min(covered) if covered else ""
        before = [_kept_row(columns, r) for r in kept if covered and _ym(r) < first]
        after = [_kept_row(columns, r) for r in kept if not (covered and _ym(r) < first)]
        rows = before + rows + after
    checks.extend(ytd_checks(per_company, prev_rows, rows))
    if carried:
        notes.append("이전 손익.csv의 WEHAGO 외 출처 줄 %d건 그대로 옮김" % len(carried))
        rows.extend(dict((c, r.get(c, "")) for c in columns) for r in carried)
    return Table("손익.csv", columns, rows, checks=checks, notes=notes)


# ───────────── 부서별 급여·판관비 (사용자 2026-11-03) ─────────────
DEPT_FILE = data.DEPT_FILE
DEPT_COLUMNS = data.DEPT_KEYS + data.DEPT_OPTIONAL
NO_DEPT = data.NO_DEPT


def build_dept(books, cfg, prev_rows=()):
    """부서비용.csv Table: 달·부서(분개장 관리항목 부서명)마다 급여·판관비(급여 뺀 나머지)·인원.

    공통비(판) 줄만 쓴다 (손익.csv 공통비와 같은 줄). 급여 = 계정코드가 cfg['salary_codes'] 인 줄. 부서명이 빈 줄은 '부서 없음'.
    인원 = 그 달 그 부서 급여 줄의 사원명 수. 사원명이 빈 급여 줄이 하나라도 있으면 인원 칸을 비운다 (모름).
    금액 없는 줄이 있는 칸도 비운다 (0으로 치지 않음). 분개장에 부서명 칸이 없으면 만들지 않고 기존 파일을 그대로 둔다.
    새 분개장에 없는 달의 이전 줄은 그대로 잇는다.
    """
    lines = [ln for ln in books.journal if _classify(ln, cfg) in ("common", "common_unmarked")]
    nin, nout = set(_squash(c) for c in cfg["nonop_in_codes"]), set(_squash(c) for c in cfg["nonop_out_codes"])
    nonop = [ln for ln in books.journal if _squash(ln["account_code"]) in nin | nout]
    if not any("dept" in ln for ln in books.journal):
        return Table(DEPT_FILE, DEPT_COLUMNS, [], written=False,
                     reason="분개장에 부서명(관리항목) 칸 없음 (기존 파일 그대로)")
    salary = set(_squash(c) for c in cfg["salary_codes"])
    cells = OrderedDict()
    source, undated, unknown_lines = 0, 0, 0
    for ln in lines:
        if ln["date"] is None:
            undated += 1
            continue
        key = (ln["date"].strftime("%Y-%m"), ln.get("dept") or NO_DEPT)
        c = cells.setdefault(key, _dept_cell())
        is_salary = _squash(ln["account_code"]) in salary
        amount = _net(ln, "common")
        cell = c["salary" if is_salary else "sga"]
        if amount is None:
            cell[1] += 1
            unknown_lines += 1
        else:
            cell[0] += amount
            source += amount
        if is_salary:
            if ln.get("employee"):
                c["names"].add(ln["employee"])
            else:
                c["nameless"] += 1
    for ln in nonop:   # 영업외: 수익 = 대변−차변, 비용 = 차변−대변. 팀 순수익에는 넣지 않는다 (사용자 2026-11-03)
        if ln["date"] is None:
            undated += 1
            continue
        c = cells.setdefault((ln["date"].strftime("%Y-%m"), ln.get("dept") or NO_DEPT), _dept_cell())
        is_in = _squash(ln["account_code"]) in nin
        amount = _net(ln, "revenue" if is_in else "common")
        cell = c["nonop_in" if is_in else "nonop_out"]
        if amount is None:
            cell[1] += 1
            unknown_lines += 1
        else:
            cell[0] += amount
    months = set(k[0] for k in cells)
    rows = [r for r in prev_rows if r.get("연월") not in months]
    for (ym, dept), c in sorted(cells.items()):
        heads = "" if c["nameless"] or not c["names"] else str(len(c["names"]))
        rows.append(dict(zip(DEPT_COLUMNS, [ym, dept, cell_amount(_cell(c["salary"])), cell_amount(_cell(c["sga"])), heads,
                                            cell_amount(_cell(c["nonop_in"])), cell_amount(_cell(c["nonop_out"]))])))
    csv_sum = 0
    for (ym, _), c in cells.items():
        csv_sum += c["salary"][0] + c["sga"][0]
    notes = ["급여 = 계정 %s · 판관비 = 그 밖의 공통비(판) · 영업외 수익 = 계정 %s · 영업외 비용 = 계정 %s · 부서는 분개장 관리항목 부서명"
             % (",".join(cfg["salary_codes"]), ",".join(cfg["nonop_in_codes"]), ",".join(cfg["nonop_out_codes"]))]
    other9 = OrderedDict()
    for ln in books.journal:
        code = _squash(ln["account_code"])
        if re.match(r"^9[0-9]{4}$", code) and code not in nin | nout:
            other9[(code, ln["account"])] = other9.get((code, ln["account"]), 0) + 1
    if other9:
        notes.append("영업외로 넣지 않은 9로 시작하는 계정: " + " · ".join("%s %s %d줄" % (k[0], k[1], n) for k, n in other9.items()))
    nodept = sum(1 for ln in lines if ln["date"] is not None and not ln.get("dept"))
    if nodept:
        notes.append("부서명 없는 공통비 줄 %d건 → '%s'" % (nodept, NO_DEPT))
    nameless = sum(c["nameless"] for c in cells.values())
    if nameless:
        notes.append("사원명 없는 급여 줄 %d건 → 그 부서·달 인원 칸 비움" % nameless)
    if undated:
        notes.append("날짜 없는 공통비 줄 %d건 → 넣지 않음" % undated)
    if unknown_lines:
        notes.append("금액 없는 공통비 줄 %d건 → 그 칸 비움" % unknown_lines)
    checks = [Check("부서별 급여+판관비 합계 = 분개장 공통비 합계 (날짜 있는 줄)", source, csv_sum)]
    return Table(DEPT_FILE, DEPT_COLUMNS, rows, checks=checks, notes=notes)


def _dept_cell():
    return {"salary": [0, 0], "sga": [0, 0], "nonop_in": [0, 0], "nonop_out": [0, 0], "names": set(), "nameless": 0}
