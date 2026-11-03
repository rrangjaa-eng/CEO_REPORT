"""월간 대표 보고: 팀별 순수익 (사용자 2026-11-03).

팀 순수익 = 팀 매출총이익(프로젝트 → 팀, 손익.csv 팀 줄) − 그 팀 부서명으로 잡힌 급여 − 그 팀 판관비(급여 뺀 공통비).
급여·판관비는 분개장 관리항목 부서명 기준 (부서비용.csv). 'XX본부'는 이름이 'XX'로 시작하고 '팀'으로 끝나는 부서의 상위 부서다
(기획본부 → 기획1팀·기획2팀·기획3팀). 본부 자체 비용은 팀에 나누지 않고 본부 합계 줄에서 뺀다.
팀이 아닌 부서(경영관리·플랜트8·부서 없음)는 비용 줄로 두고, 맨 아래 회사 전체 = 매출총이익 − 모든 급여·판관비.
모르는 값은 None 이고 0으로 치지 않는다.
"""
from collections import OrderedDict

from .data import NO_DEPT

SPECIAL = ("미연결", "팀 미확인", "팀 미지정")


def _add(*vals):
    return None if any(v is None for v in vals) else sum(vals)


def _dept_costs(dept_rows, months):
    """부서 -> {salary, sga, heads(마지막 달만)}. months 의 달이 하나라도 부서비용에 없으면 None (모름)."""
    have = set(r["ym"] for r in dept_rows)
    if not months or any(m not in have for m in months):
        return None
    out = OrderedDict()
    for r in dept_rows:
        if r["ym"] not in months:
            continue
        c = out.setdefault(r["dept"], {"salary": 0, "sga": 0, "heads": None, "nonop_in": 0, "nonop_out": 0})
        c["salary"] = _add(c["salary"], r["salary"])
        c["sga"] = _add(c["sga"], r["sga"])
        ok = r.get("has_nonop", False)
        c["nonop_in"] = _add(c["nonop_in"], r.get("nonop_in") if ok else None)
        c["nonop_out"] = _add(c["nonop_out"], r.get("nonop_out") if ok else None)
        if r["ym"] == months[-1]:
            c["heads"] = r["heads"]
    return out


def _months(ym, ytd):
    if not ytd:
        return [ym]
    year, m = ym[:4], int(ym[5:])
    return ["%s-%02d" % (year, i) for i in range(1, m + 1)]


def _row(label, kind, revenue=None, gp=None, salary=None, sga=None, heads=None, has_rev=True):
    net = _add(gp, -salary if salary is not None else None, -sga if sga is not None else None) if has_rev else (
        None if salary is None or sga is None else -(salary + sga))
    return {"label": label, "kind": kind, "revenue": revenue, "gp": gp, "salary": salary, "sga": sga, "net": net,
            "heads": heads, "has_rev": has_rev}


def build(pl_table, dept_rows, ym, ytd=False):
    """pl_table: R['s4']['sources']['WEHAGO']['table']. -> {"rows", "company", "dept_ok", "check"} 또는 None (팀 손익 없음)."""
    key = "ytd" if ytd else "cur"
    teams = OrderedDict()
    special, company = [], None
    for r in pl_table:
        v = r[key] or {"revenue": None, "gp": None, "common": None}
        if r["unit"] == "회사":
            company = v
        elif r["unit"] == "팀":
            if r["target"] in SPECIAL:
                special.append((r["target"], v))
            else:
                teams[r["target"]] = v
    if company is None and not teams:
        return None
    costs = _dept_costs(dept_rows or [], _months(ym, ytd)) if dept_rows is not None else None
    dept_ok = costs is not None
    names = list(teams) + [d for d in (costs or {}) if d.endswith("팀") and d not in teams]
    zero = {"revenue": 0, "gp": 0} if company is not None and company.get("revenue") is not None else {"revenue": None, "gp": None}

    def cost(d):
        if costs is None:
            return None, None, None
        c = costs.get(d, {"salary": 0, "sga": 0, "heads": None})
        return c["salary"], c["sga"], c["heads"]

    def team_row(t):
        v = teams.get(t, zero)
        s, g, h = cost(t)
        return _row(t, "team", v.get("revenue"), v.get("gp"), s, g, h)
    rows, used = [], set()
    hqs = [d for d in (costs or {}) if d.endswith("본부")]
    for hq in hqs:
        prefix = hq[:-2]
        kids = [t for t in names if t.startswith(prefix) and t.endswith("팀")]
        group = [team_row(t) for t in kids]
        s, g, h = cost(hq)
        own = _row("%s 자체 비용" % hq, "hq_self", salary=s, sga=g, heads=h, has_rev=False)
        tot = _row("%s 합계" % hq, "hq_total", _add(*[x["revenue"] for x in group]) if group else 0,
                   _add(*[x["gp"] for x in group]) if group else 0,
                   _add(*([x["salary"] for x in group] + [s])), _add(*([x["sga"] for x in group] + [g])),
                   _add(*([x["heads"] for x in group] + [h])))
        rows.extend(group + [own, tot])
        used.update(kids + [hq])
    rest = [team_row(t) for t in names if t not in used]
    rows = rest + rows
    for d in (costs or {}):
        if d in used or d in names:
            continue
        s, g, h = cost(d)
        rows.append(_row(d if d != NO_DEPT else "부서 없음 (분개장 부서명 빈칸)", "other", salary=s, sga=g, heads=h, has_rev=False))
    for name, v in special:
        rows.append(_row("프로젝트 %s" % name if name == "미연결" else name, "unlinked", v.get("revenue"), v.get("gp"), 0, 0))
    total_s = _add(*[c["salary"] for c in costs.values()]) if costs else None
    total_g = _add(*[c["sga"] for c in costs.values()]) if costs else None
    comp = _row("회사 전체 (영업이익)", "company", company and company.get("revenue"), company and company.get("gp"), total_s, total_g,
                _add(*[c["heads"] for c in costs.values()]) if costs else None)
    if costs:   # 영업외 (정부지원금·이자 등): 팀에 넣지 않고 회사 영업이익 아래에서 더하고 뺀다 (사용자 2026-11-03)
        nin = _add(*[c["nonop_in"] for c in costs.values()])
        nout = _add(*[c["nonop_out"] for c in costs.values()])
        by_dept = [(d, c["nonop_in"], c["nonop_out"]) for d, c in costs.items() if c["nonop_in"] or c["nonop_out"]]
    else:
        nin = nout = None
        by_dept = []
    before_in = _add(comp["net"], -nout if nout is not None else None)   # 영업외 수익 없이 본 이익 (사용자 2026-11-03)
    nonop = {"in": nin, "out": nout, "by_dept": by_dept, "before_in": before_in, "pretax": _add(before_in, nin)}
    common = company.get("common") if company else None
    check = None if (common is None or total_s is None or total_g is None) else (total_s + total_g, common)
    return {"rows": rows, "company": comp, "dept_ok": dept_ok, "check": check, "nonop": nonop}


def allocate(T, basis="heads"):
    """팀 줄마다 'alloc' = 팀 순수익 + (회사 영업이익 − 팀 순수익 합) × 팀 몫 (사용자 2026-11-03: 기획팀 1인당이 과장되지 않게).

    몫 = 인원(basis='heads') 또는 매출(basis='revenue') 비율. 팀 alloc 합 = 회사 영업이익. 모르는 값이 있으면 None."""
    teams = [r for r in T["rows"] if r["kind"] == "team"]
    for r in teams:
        r["alloc"] = None
    key = "heads" if basis == "heads" else "revenue"
    comp = T["company"]["net"]
    if not teams or comp is None or any(r["net"] is None or r[key] is None for r in teams):
        return T
    weight = sum(r[key] for r in teams)
    if not weight:
        return T
    rest = comp - sum(r["net"] for r in teams)
    for r in teams:
        r["alloc"] = r["net"] + rest * r[key] / weight
    return T


def build_ytd_alloc(pl_month_tables, dept_rows, ym, basis="heads"):
    """올해 누적 '비용 나눈 뒤 순수익': 달마다 나눈 값을 더한다 (인원이 달마다 다르므로). 팀 이름 -> 금액 또는 None."""
    out = OrderedDict()
    for m, table in pl_month_tables:
        T = build(table, dept_rows, m, False)
        if T is None:
            return {}
        allocate(T, basis)
        for r in T["rows"]:
            if r["kind"] == "team":
                out[r["label"]] = _add(out.get(r["label"], 0), r["alloc"])
    return out
