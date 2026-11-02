"""손익.csv 만들기 (D-40): WEHAGO 분개장 줄 → 달별 회사 줄 (매출·직접비·공통비).

계정 코드와 표시 낱말은 모두 설정(cfg, convert.read_config)에서 온다 (D-39). 이 파일에는 계정 코드를 쓰지 않는다.
모르는 값은 0이 아니라 빈칸이다 (D-02): 금액 칸이 비어 있는 줄이 있는 달은 그 칸을 비우고 알린다.
"""
import re
from collections import OrderedDict

from . import data
from .convert import Check, Table, cell_amount
from .util import won

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
        values = ["WEHAGO", ym, "회사", "회사 전체", cell_amount(cells["revenue"]), cell_amount(cells["direct"]),
                  cell_amount(cells["common"]), "" if int(ym[:4]) in closed else "Y"]
        rows.append(dict(zip(columns, values)))
        if links is not None:
            units = unit_totals.get(ym, {})
            for key in _project_order(list(units), links["projects"]):
                rows.append(_project_row(columns, ym, key, units[key], links["projects"], links["snapshot"],
                                         int(ym[:4]) in closed))
    labels = _labels(cfg)
    checks = [Check(labels[k], source[k], None if csv_unknown[k] else csv_sum[k]) for k, _, _ in CATEGORIES]
    for key, label, _ in CATEGORIES:
        n, total, unknown = undated[key]
        if n:
            notes.append("날짜 없는 손익 줄 %d건 (%s) %s" % (n, label, won(total)) + (
                " · 금액 없음 %d건" % unknown if unknown else ""))
    if excluded:
        notes.append("손익.csv에 넣지 않은 손익 계정: " + _listing(excluded))
    if unmarked:
        notes.append("공통비 중 %s 표시 없음: %s (공통비에 넣음)" % (cfg["common_mark"], _listing(unmarked)))
    carried = [r for r in prev_rows if r.get("출처", "") != "WEHAGO"]
    replaced = [r for r in prev_rows if r.get("출처", "") == "WEHAGO"]
    if replaced:
        units = OrderedDict()
        for r in replaced:
            units[r.get("단위", "") or "(단위 없음)"] = units.get(r.get("단위", "") or "(단위 없음)", 0) + 1
        notes.append("이전 손익.csv의 WEHAGO 줄 %d건(%s)은 새로 만든 줄로 바꿈"
                     % (len(replaced), " · ".join("%s %d" % (u, n) for u, n in units.items())))
    if carried:
        notes.append("이전 손익.csv의 WEHAGO 외 출처 줄 %d건 그대로 옮김" % len(carried))
        rows.extend(dict((c, r.get(c, "")) for c in columns) for r in carried)
    return Table("손익.csv", columns, rows, checks=checks, notes=notes)
