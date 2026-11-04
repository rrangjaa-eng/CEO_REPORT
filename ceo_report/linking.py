"""프로젝트 연결 (D-38, D-40): WEHAGO 원가·매출 줄이 어느 프로젝트의 것인지 정한다.

원가 줄 순서: 수동(입력/프로젝트연결.csv) -> 매입매출장 프로젝트명 칸 -> 적요 [코드] -> 인트라넷 지급요청 하나(자동) -> 미연결.
매출 줄 순서: 수동 -> 매입매출장 프로젝트명 칸 -> 적요 [코드] -> 클라이언트·견적금액이 같은 프로젝트 하나(자동) -> 미연결.
프로젝트명 칸(D-53)은 분개장 줄과 같은 (전표일자, 전표번호)의 매입매출장 줄에서 읽고, 기준은 '코드', 이름은 '프로젝트명 [코드]'.
자동 연결은 후보가 정확히 하나일 때만 한다. 둘 이상이거나 하나의 요청을 여러 줄이 노리면 연결하지 않고 후보 수를 보인다.

이 모듈의 함수는 장부·스냅숏·요청·프로젝트를 바꾸지 않고, 입력 순서가 달라도 같은 결과를 낸다.
모르는 금액은 None 이고 0으로 세지 않는다 (D-02). 글자는 이미 가려진 값(wehago.read_book, approval._masked)을 쓰고
여기서도 한 번 더 가린다 (D-45).
"""
import datetime as dt
import os
import re
from collections import OrderedDict

from .approval import _expected_date, _masked, _status, norm_project, parse_registered, project_code
from .util import Issues, mask_rrn, num, read_csv
from .util import date as parse_date
from .wehago import norm_vendor

LINK_FILE = "프로젝트연결.csv"
LINK_COLUMNS = ["전표일자", "전표번호", "줄", "프로젝트번호"]
BASES = ("수동", "코드", "자동", "미연결")
MANUAL_LABEL = "수동 (프로젝트연결.csv)"
MANUAL_UNKNOWN_LABEL = "수동 (프로젝트연결.csv · 프로젝트 목록에 없는 번호)"
NO_LIST = "프로젝트 목록 없음"


# ───────────── 요청과 프로젝트 (스냅숏) ─────────────
def requests_of(snap, asof, now):
    """스냅숏의 지급요청을 approval.build 의 A['requests_all'] 과 같은 모양으로 (글자는 가린 값)."""
    out = []
    if snap is None:
        return out
    for k, row in enumerate(_masked(snap.payments)):
        rq = {"id": "r%d" % k, "번호": row.get("번호", ""), "name": row.get("행사명", ""), "vendor": row.get("파트너", ""),
              "code": project_code(row.get("행사명", "")), "registered": parse_registered(row.get("등록일", "")),
              "status": _status(row.get("사장님승인", "")), "amount": num(row.get("금액")),
              "request_date": parse_date(row.get("지급요청일")), "date": None, "rule": "",
              "status_text": (row.get("사장님승인") or "").strip()}   # 읽은 그대로 (D-52 '상태 확인 필요 (<값>)')
        rq["date"], rq["rule"] = _expected_date(rq, asof, now)
        out.append(rq)
    return out


def projects_of(snap):
    """스냅숏 프로젝트 목록 -> OrderedDict 키 -> 프로젝트. 키 = 행사명 맨 앞 [코드] 또는 번호. 겹치면 첫 줄만 두고 dup=True."""
    out = OrderedDict()
    if snap is None:
        return out
    for p in _masked(snap.projects):
        title = p.get("행사명", "")
        key = project_code(title) or norm_project(p.get("번호", ""))
        if not key:
            continue
        if key in out:
            out[key]["dup"] = True
            continue
        out[key] = {"key": key, "name": re.sub(r"^\s*\[\d+\]\s*", "", title), "team": p.get("팀", ""),
                    "client": p.get("클라이언트", ""), "client_norm": norm_vendor(p.get("클라이언트", "")),
                    "estimate": num(p.get("사전견적")), "quote": num(p.get("견적금액")), "budget": num(p.get("실행가")),
                    "event_date": parse_date(p.get("행사일")), "dup": False,
                    # 읽기 전 글자 (프로젝트.csv 를 만드는 쪽이 '숫자 아님'과 빈칸을 구별하고 행사일을 글자 그대로 쓴다)
                    "estimate_text": (p.get("사전견적") or "").strip(), "budget_text": (p.get("실행가") or "").strip(),
                    "event_text": (p.get("행사일") or "").strip()}
    return out


# ───────────── 줄 열쇠 ─────────────
def _norm_no(text):
    """전표번호 글자: 앞뒤 공백을 없애고 엑셀이 붙인 '.0' 을 뗀다 ('22.0' -> '22')."""
    s = ("" if text is None else str(text)).strip()
    return re.sub(r"^(\d+)\.0+$", r"\1", s)


def line_keys(journal):
    """분개장 줄마다 (전표일자 ISO 또는 '', 전표번호, 줄) 하나. 줄 = 같은 전표일자·전표번호 안에서 파일 순서의 1부터 번호."""
    seen = {}
    keys = []
    for row in journal:
        day = row["date"].isoformat() if row.get("date") else ""
        no = _norm_no(row.get("no"))
        seen[(day, no)] = seen.get((day, no), 0) + 1
        keys.append((day, no, seen[(day, no)]))
    return keys


# ───────────── 수동 지정 파일 ─────────────
def _issue_notes(issues):
    out = []
    for _, line, msg in issues.items:
        where = "%s번째 줄: " % line if str(line).isdigit() else ""
        out.append("%s %s%s" % (LINK_FILE, where, msg))
    return out


def read_links(input_dir):
    """입력/프로젝트연결.csv -> (줄 열쇠 -> 프로젝트번호, 알림 목록). 틀린 줄은 무시하고 알린다. 파일은 읽기만 한다."""
    path = os.path.join(input_dir, LINK_FILE)
    if not os.path.exists(path):
        return {}, ["%s 없음 (수동 지정 0건)" % LINK_FILE]
    issues = Issues()
    info = {}
    rows, ok = read_csv(path, LINK_COLUMNS, issues, info)
    notes = []
    if not ok or info.get("missing"):
        notes = _issue_notes(issues)
        return {}, notes + ["%s 수동 지정 0건" % LINK_FILE]
    notes = _issue_notes(issues)
    picked = OrderedDict()   # 열쇠 -> 프로젝트번호 집합 (들어온 순서)
    for row in rows:
        line = row["_line"]
        day = parse_date(row.get("전표일자"))
        no = _norm_no(row.get("전표번호"))
        nth = (row.get("줄") or "").strip()
        project = norm_project(row.get("프로젝트번호"))
        m = re.match(r"^\[(.*)\]$", project)
        if m:
            project = m.group(1).strip()
        why = None
        if day is None:
            why = "전표일자를 날짜로 읽지 못함"
        elif not no:
            why = "전표번호가 비어 있음"
        elif not re.match(r"^\d+(\.0+)?$", nth) or int(float(nth)) < 1:
            why = "줄 값이 1 이상 정수가 아님"
        elif not project:
            why = "프로젝트번호가 비어 있음"
        if why:
            notes.append("%s %s번째 줄: %s → 무시" % (LINK_FILE, line, why))
            continue
        picked.setdefault((day.isoformat(), no, int(float(nth))), []).append(project)
    overrides = {}
    for key, projects in picked.items():
        if len(set(projects)) > 1:
            notes.append("%s 같은 줄(%s %s-%d)에 다른 프로젝트 지정 → 둘 다 무시" % (LINK_FILE, key[0], key[1], key[2]))
        else:
            overrides[key] = projects[0]
    return overrides, notes


def unused_links(books, overrides, used):
    """쓰이지 않은 수동 지정 -> [(열쇠, 프로젝트번호, 이유)]. used 는 link_costs 와 link_revenue 의 used 를 합친 집합이어야 한다.

    이유: '지정한 줄 없음' (그 열쇠의 분개장 줄이 없음) 또는 '원가·매출 줄이 아님' (줄은 있으나 원가·매출 줄이 아님).
    """
    exist = set(line_keys(books.journal))
    out = []
    for key in sorted(overrides):
        if key in used:
            continue
        out.append((key, overrides[key], "원가·매출 줄이 아님" if key in exist else "지정한 줄 없음"))
    return out


# ───────────── 공통 도구 ─────────────
def _squash(text):
    return re.sub(r"\s+", "", text or "")


PRIOR = "참고"   # 지난해 프로젝트 줄: 연결하지 않고 참고로만 (사용자 2026-11-04, 2025년 건은 입금·지급 모두 끝남)
PRIOR_LABEL = "참고 (지난해 프로젝트 · 연결하지 않음)"


def is_old_code(code):
    """예전(2025) 프로젝트 번호 체계: 숫자 5자리 미만 ([093] 등). 지금 체계는 [26053] 같은 5자리."""
    s = str(code or "").strip()
    return s.isdigit() and len(s) < 5


def _summary(lines):
    out = OrderedDict((b, {"count": 0, "sum": 0, "unknown": 0}) for b in BASES)
    for ln in lines:
        if ln.get("prior"):
            out.setdefault(PRIOR, {"count": 0, "sum": 0, "unknown": 0})
        s = out[PRIOR if ln.get("prior") else ln["basis"]]
        s["count"] += 1
        if ln["amount"] is None:
            s["unknown"] += 1
        else:
            s["sum"] += ln["amount"]
    return out


def _slips(books):
    """{(전표일자 ISO, 전표번호): 프로젝트명 칸 코드} — 전표번호는 분개장 열쇠와 같은 모양으로 맞춘다."""
    return dict(((d, _norm_no(n)), c) for (d, n), c in (getattr(books, "slip_projects", None) or {}).items())


def _line(index, key, row, amount, slip=None):
    return {"slip_code": slip, "index": index, "key": key, "date": row.get("date"), "no": key[1], "line": key[2],
            "vendor": mask_rrn(row.get("vendor")), "vendor_norm": row.get("vendor_norm") or norm_vendor(row.get("vendor")),
            "memo": mask_rrn(row.get("memo")), "account_code": _squash(row.get("account_code")),
            "account": row.get("account", ""), "amount": amount, "project": None, "basis": "미연결", "request": None,
            "candidates": 0, "label": "", "code": row.get("code") or project_code(row.get("memo")), "reason": ""}


def _fixed(ln, overrides, projects, used):
    """수동 -> 코드 순서로 정해지면 True. 안 정해지면 미연결 이유(ln['reason'])에 코드 사정을 적고 False."""
    manual = overrides.get(ln["key"])
    if manual is not None:
        ln.update(project=manual, basis="수동",
                  label=MANUAL_LABEL if (not projects or manual in projects) else MANUAL_UNKNOWN_LABEL)
        used.add(ln["key"])
        return True
    slip = ln.get("slip_code")
    if slip is not None and (not projects or slip in projects):
        label = "프로젝트명 [%s]" % slip
        if not projects:
            label += " (%s)" % NO_LIST
        elif ln["code"] is not None and ln["code"] != slip:
            label += " (적요 코드 [%s]와 다름)" % ln["code"]
        ln.update(project=slip, basis="코드", label=label)
        return True
    code = ln["code"]
    if code is None:
        ln["reason"] = "코드 없음"
        return False
    if not projects:
        ln.update(project=code, basis="코드", label="코드 [%s] (%s)" % (code, NO_LIST))
        return True
    if code in projects:
        ln.update(project=code, basis="코드", label="코드 [%s]" % code)
        return True
    ln["reason"] = "코드 %s 프로젝트 목록에 없음" % code
    return False


def _unlinked(ln, tail):
    ln.update(project=None, basis="미연결", request=None)
    ln["label"] = "미연결 (%s)" % " · ".join([ln["reason"]] + [tail] if ln["reason"] else [tail])


def _no_key(n):
    return (0, int(n), n) if n.isdigit() else (1, 0, n)


def _prior(ln, year):
    """지난해 프로젝트 줄인가: 장부의 마지막 해보다 앞선 날짜, 또는 예전 번호 체계([3자리]) 코드 (2026 분개장의 '2025_선급금대체' 등)."""
    if ln["date"] is not None and ln["date"].year < year:
        return True
    return any(is_old_code(c) for c in (ln.get("slip_code"), ln.get("code")) if c)


# ───────────── 원가 줄 연결 ─────────────
def _window_end(start, days):
    """start + days 일. 날짜 범위를 넘으면 마지막 날 (설정은 1~3650 으로 막지만 다른 호출도 예외 없이, 02-REVIEW WR-02)."""
    try:
        return start + dt.timedelta(days=days)
    except (OverflowError, ValueError):
        return dt.date.max


def link_costs(books, requests, projects, overrides, link_days=90, direct_prefixes=("6",), direct_mark="(도)",
               vat_codes=("13500",)):
    """(도) 원가 줄을 프로젝트에 잇는다 -> {"lines": [...], "summary": {기준: {count, sum, unknown}}, "used": {수동 열쇠}}.

    자동 연결 후보 요청: 금액·등록일을 읽을 수 있고, 행사명 코드가 프로젝트 목록에 있고, 파트너(norm_vendor)가 줄의
    거래처와 같고, 줄 날짜가 등록일부터 link_days 일 안(양끝 포함), 금액이 줄 금액 A 또는 부가세를 더한 T 와 같다.
    T = A + 같은 전표·같은 거래처 부가세대급금 차변 합 (그 전표에 그 거래처 원가 줄이 하나일 때만).
    후보가 정확히 하나이고 그 요청이 다른 어떤 줄의 후보도 아닐 때만 연결한다 (요청 상태는 가리지 않는다).
    """
    journal = books.journal
    keys = line_keys(journal)
    slips = _slips(books)
    prefixes = tuple(str(p) for p in direct_prefixes)
    mark = _squash(direct_mark)
    vat = set(_squash(c) for c in vat_codes)
    lines = []
    for i, row in enumerate(journal):
        code = _squash(row.get("account_code"))
        if not (re.match(r"^\d{5}$", code) and code.startswith(prefixes) and mark in _squash(row.get("account"))):
            continue
        d, c = row.get("debit"), row.get("credit")
        lines.append(_line(i, keys[i], row, None if d is None and c is None else (d or 0) - (c or 0),
                           row.get("line_project") or slips.get(keys[i][:2])))
    used = set()
    pending = []
    year = max([ln["date"].year for ln in lines if ln["date"] is not None] or [0])
    for ln in lines:
        if ln["key"] not in overrides and _prior(ln, year):
            ln.update(prior=True, label=PRIOR_LABEL)   # 지난해 줄은 코드·자동 연결 모두 하지 않는다 (수동 지정만 따른다)
            continue
        if not _fixed(ln, overrides, projects, used):
            pending.append(ln)

    # 부가세: 같은 (전표일자, 전표번호, 거래처)의 부가세대급금 차변 합. 모르는 줄이 있으면 None
    vat_sum = {}
    for i, row in enumerate(journal):
        if _squash(row.get("account_code")) in vat:
            k = (keys[i][0], keys[i][1], row.get("vendor_norm") or norm_vendor(row.get("vendor")))
            d, c = row.get("debit"), row.get("credit")
            part = None if d is None and c is None else (d or 0)
            vat_sum[k] = None if (part is None or vat_sum.get(k, 0) is None) else vat_sum.get(k, 0) + part
    per_vendor = {}
    for ln in lines:
        k = (ln["key"][0], ln["key"][1], ln["vendor_norm"])
        per_vendor[k] = per_vendor.get(k, 0) + 1

    eligible = {}
    if projects:
        for rq in requests:
            vn = norm_vendor(rq["vendor"])
            if rq["amount"] is not None and rq["registered"] is not None and rq["code"] in projects and vn:
                eligible.setdefault(vn, []).append(rq)
    cand = {}
    for ln in pending:
        found = []
        if ln["amount"] is not None and ln["date"] is not None and ln["vendor_norm"] and projects:
            k = (ln["key"][0], ln["key"][1], ln["vendor_norm"])
            amounts = set([ln["amount"]])
            if per_vendor[k] == 1 and vat_sum.get(k) is not None:
                amounts.add(ln["amount"] + vat_sum[k])
            for rq in eligible.get(ln["vendor_norm"], ()):
                start = rq["registered"].date()
                if start <= ln["date"] <= _window_end(start, link_days) and rq["amount"] in amounts:
                    found.append(rq["번호"])
        cand[ln["index"]] = sorted(set(found), key=_no_key)
    backing = {}   # 요청 번호 -> 그 요청을 후보로 가진 줄 수
    for numbers in cand.values():
        for n in numbers:
            backing[n] = backing.get(n, 0) + 1
    by_no = dict((rq["번호"], rq) for rq in requests)
    for ln in pending:
        numbers = cand[ln["index"]]
        ln["candidates"] = len(numbers)
        if ln["amount"] is None:
            ln["reason"] = ""
            _unlinked(ln, "금액 미확인")
        elif not projects:
            _unlinked(ln, NO_LIST)
        elif len(numbers) == 1 and backing[numbers[0]] == 1:
            n = numbers[0]
            ln.update(project=by_no[n]["code"], basis="자동", request=n, label="자동 (지급요청 %s)" % n)
        elif len(numbers) == 1:
            ln["reason"] = ""
            _unlinked(ln, "자동 연결 후보 공유: 지급요청 %s" % numbers[0])
        elif numbers:
            ln["reason"] = ""
            _unlinked(ln, "자동 연결 후보 %d건: 지급요청 %s" % (len(numbers), ", ".join(numbers)))
        else:
            if ln["date"] is None:
                ln["reason"] = (ln["reason"] + " · " if ln["reason"] else "") + "날짜 없음"
            _unlinked(ln, "자동 연결 후보 0건")
    return {"lines": lines, "summary": _summary(lines), "used": used}


# ───────────── 매출 줄 연결 ─────────────
def link_revenue(books, projects, overrides, revenue_codes=("41200",)):
    """매출 줄(계정 revenue_codes, 금액 = 대변-차변)을 프로젝트에 잇는다 -> {"lines", "summary", "used"}.

    순서: 수동 -> 적요 [코드] -> 클라이언트(norm_vendor)와 견적금액이 줄 금액과 같은 프로젝트가 정확히 하나(키가 겹치는
    프로젝트는 후보가 아님) -> 미연결. 후보가 둘 이상이면 연결하지 않고 후보 수를 보인다.
    """
    journal = books.journal
    keys = line_keys(journal)
    slips = _slips(books)
    codes = set(_squash(c) for c in revenue_codes)
    lines = []
    for i, row in enumerate(journal):
        if _squash(row.get("account_code")) not in codes:
            continue
        d, c = row.get("debit"), row.get("credit")
        lines.append(_line(i, keys[i], row, None if d is None and c is None else (c or 0) - (d or 0),
                           row.get("line_project") or slips.get(keys[i][:2])))
    used = set()
    year = max([ln["date"].year for ln in lines if ln["date"] is not None] or [0])
    for ln in lines:
        if ln["key"] not in overrides and _prior(ln, year):
            ln.update(prior=True, label=PRIOR_LABEL)   # 지난해 프로젝트 매출: 참고로만 (사용자 2026-11-04)
            continue
        if _fixed(ln, overrides, projects, used):
            continue
        if ln["amount"] is None:
            ln["reason"] = ""
            _unlinked(ln, "금액 미확인")
            continue
        if not projects:
            _unlinked(ln, NO_LIST)
            continue
        found = sorted(k for k, p in projects.items() if not p["dup"] and ln["vendor_norm"] and
                       p["client_norm"] == ln["vendor_norm"] and p["quote"] == ln["amount"])
        ln["candidates"] = len(found)
        if len(found) == 1:
            ln.update(project=found[0], basis="자동", label="자동 (클라이언트·견적금액)")
        else:
            if found:
                ln["reason"] = ""
            _unlinked(ln, "클라이언트·견적금액 후보 %d건" % len(found))
    return {"lines": lines, "summary": _summary(lines), "used": used}
