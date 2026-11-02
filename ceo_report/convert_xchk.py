"""위하고대조.csv 만들기와 읽기 (Phase 2, D-44 D-48 D-49).

build_xchk 는 변환한 사실(프로젝트별 WEHAGO 원가, 미연결 원가 ...)을 한 줄에 사실 하나씩 담은 표(convert.Table)로 만든다.
순수 함수다: 파일을 읽거나 쓰지 않는다 (쓰기는 convert, 은행 줄은 부르는 쪽이 읽어서 넘긴다).
load_xchk 는 그 파일을 읽어 월간 보고가 쓸 사실과 (두 값을 모두 알 때만 구하는) 차이를 돌려준다. 예외를 내지 않는다.

모르는 값은 '' 이고 0이 아니다 (D-02). 합계에 모르는 값이 하나라도 섞이면 금액 칸은 '' 이고
모르는 개수는 비고에만 적는다 (B5). 건수는 모르는 값을 포함해 센다.
"""
import collections
import os
import re

from . import util
from .convert import Check, Table, cell_amount
from .convert_pl import _classify, _net
from .convert_projects import out_of_period, period_text
from .util import is_blank, mask_rrn, num, won
from .wehago import STATUSES, norm_vendor, vendor_payables

XCHK_FILE = "위하고대조.csv"
XCHK_COLUMNS = ["구분", "대상", "이름", "항목", "금액", "건수", "비고"]
NOT_LISTED = "(프로젝트 목록에 없음)"


# ───────────── 줄 만들기 공통 ─────────────
def _row(kind, target="", name="", item="", amount=None, count=None, note=""):
    return {"구분": kind, "대상": target, "이름": name, "항목": item, "금액": cell_amount(amount),
            "건수": "" if count is None else str(count), "비고": note}


def _known_sum(values):
    """(합계 또는 None, 모르는 값 개수): 모르는 값이 하나라도 있으면 합계는 None (B5)."""
    total, unknown = 0, 0
    for v in values:
        if v is None:
            unknown += 1
        else:
            total += v
    return (None if unknown else total), unknown


def _unknown_note(unknown, unit):
    return "금액 미확인 %d%s" % (unknown, unit) if unknown else ""


def _cell(row):
    """줄의 금액 칸 -> 숫자 또는 None."""
    return num(row["금액"])


def _sum_cells(rows):
    return _known_sum([_cell(r) for r in rows])[0]


# ───────────── build_xchk ─────────────
def _meta_rows(meta):
    return [_row("기준", item=str(k), note=mask_rrn(v)) for k, v in meta.items()]


def _line_target(ln):
    return "%s %s-%d" % (ln["date"].isoformat() if ln["date"] else "날짜 없음", ln["no"], ln["line"])


def _project_keys(projects, lines):
    """프로젝트 목록 순서의 키, 그 뒤에 수동 연결 등으로만 닿는 키 (번호 순)."""
    extra = sorted(set(ln["project"] for ln in lines if ln["project"] is not None and ln["project"] not in projects))
    return list(projects) + extra


def _status_rows(match):
    """요청상태: wehago.match_requests 요약 그대로 (대상 = 상태). 계산서가 있는 두 상태는 WEHAGO 계산서 합계 줄이 하나 더 있다."""
    rows = []
    for status in STATUSES:
        s = match["summary"][status]
        known = None if s["unknown"] or s["sum"] is None else s["sum"]
        rows.append(_row("요청상태", status, "", "인트라넷 요청", known, s["count"], _unknown_note(s["unknown"], "건")))
        if status in ("계산서 있음", "금액 차이"):
            invoices = [r["invoice_total"] for r in match["rows"].values() if r["status"] == status]
            total, unknown = _known_sum(invoices)
            rows.append(_row("요청상태", status, "", "WEHAGO 계산서", total, len(invoices), _unknown_note(unknown, "건")))
    return rows


def _is_unknown(r):
    return r["status"] not in ("approved", "pending")


def _request_note(rows):
    """요청 누계·프로젝트밖요청 비고: 금액 미확인 건수, 그리고 상태 확인 필요(D-52) 요청이 섞였으면 그 건수."""
    unknown = sum(1 for r in rows if r["amount"] is None)
    odd = sum(1 for r in rows if _is_unknown(r))
    return " · ".join(x for x in (_unknown_note(unknown, "건"), "상태 확인 필요 %d건 포함" % odd if odd else "") if x)


def _request_rows(projects, requests):
    """프로젝트밖요청: 프로젝트 목록에 없는 코드의 요청 합계. 상태를 읽지 못한 요청도 넣는다 (D-52, 비고에 건수)."""
    outside = [r for r in requests if r["code"] not in projects]
    total, _ = _known_sum([r["amount"] for r in outside])
    return [_row("프로젝트밖요청", "합계", "", "인트라넷 요청", total, len(outside), _request_note(outside))]


STATUS_CHECK = "요청상태확인필요"


def _status_check_rows(requests):
    """요청상태확인필요 (D-52): 사장님승인이 빈칸이거나 알 수 없는 값인 요청의 합계 줄과 요청마다 한 줄 (번호 순)."""
    bad = sorted((r for r in requests if _is_unknown(r)), key=lambda r: _no_key(r["번호"]))
    total, unknown = _known_sum([r["amount"] for r in bad])
    rows = [_row(STATUS_CHECK, "합계", "", "인트라넷 요청", total, len(bad),
                 " · ".join(x for x in (_unknown_note(unknown, "건"), "요청 누계·프로젝트밖요청·프로젝트집행(요청미지급 추정)에 넣음") if x))]
    for r in bad:
        rows.append(_row(STATUS_CHECK + "줄", r["번호"], r["vendor"], "사장님승인 '%s'" % (r.get("status_text") or ""), r["amount"], 1,
                         " ".join(x for x in (r["code"] or "", r["name"]) if x)))
    return rows


def _no_key(n):
    n = str(n)
    return (0, int(n), n) if n.isdigit() else (1, 0, n)


REQUEST_TOTAL_LABEL = "지급요청 건수 = 요청 누계 건수 합계 + 프로젝트밖요청 건수"


def request_total_check(requests, rows):
    """모든 지급요청(상태를 읽지 못한 것 포함)이 요청 누계(프로젝트 목록 안) 또는 프로젝트밖요청 중 한 곳에 든다 (D-52, CR-03)."""
    counts = [int(r["건수"]) for r in rows if r.get("건수", "").isdigit() and (
        (r["구분"] == "프로젝트원가" and r["항목"] == "요청 누계") or r["구분"] == "프로젝트밖요청")]
    return Check(REQUEST_TOTAL_LABEL, len(requests), sum(counts))


OUT_OF_PERIOD = "판단 불가 (기간 밖"
PERIOD_SUFFIX = " (분개장 기간)"


def _total_rows(kind, key, name, item, total, count, note, history):
    """누계 줄. 기간 밖 이력이 있는 프로젝트(WR-05)는 누계 칸을 비우고 까닭을 적은 뒤, 분개장 기간 합계를 따로 한 줄 더 쓴다."""
    if key not in history:
        return [_row(kind, key, name, item, total, count, note)]
    why = "%s: %s)" % (OUT_OF_PERIOD, history[key])
    return [_row(kind, key, name, item, None, count, " · ".join(x for x in (why, note) if x)),
            _row(kind, key, name, item + PERIOD_SUFFIX, total, count, note)]


def _period_cells(rows, item):
    """대조용: item 줄들, 단 기간 밖 프로젝트는 비운 누계 대신 분개장 기간 합계 줄 (대조는 같은 기간끼리)."""
    period = dict((r["대상"], r) for r in rows if r["항목"] == item + PERIOD_SUFFIX)
    return [period.get(r["대상"], r) if r["대상"] in period else r for r in rows if r["항목"] == item]


def period_checks(history, rows):
    """대조 (WR-05): 기간 밖 이력이 있는 프로젝트 수 = 그 프로젝트의 WEHAGO 원가·매출 누계 칸이 빈칸인 줄 수 (0 이면 '불일치')."""
    out = []
    for kind, item in (("프로젝트원가", "WEHAGO 원가"), ("매출계약", "WEHAGO 매출")):
        cells = [r for r in rows if r["구분"] == kind and r["항목"] == item and r["대상"] in history]
        out.append(Check("분개장 시작 전 이력이 있는 프로젝트 → %s 판단 불가 (빈칸)" % item, len(history),
                         sum(1 for r in cells if is_blank(r["금액"]))))
    return out


def _cost_rows(projects, costs, requests, history=None):
    """프로젝트원가: 프로젝트마다 WEHAGO 원가 (모든 날짜의 줄), 실행가, 요청 누계 (코드가 프로젝트 키이고 상태를 읽은 요청)."""
    rows = []
    history = history or {}
    known = list(requests)   # 상태를 읽지 못한 요청도 든다 (D-52: 버리지 않음, 비고에 건수)
    for key in _project_keys(projects, costs["lines"]):
        p = projects.get(key)
        mine = [ln for ln in costs["lines"] if ln["project"] == key]
        total, unknown = _known_sum([ln["amount"] for ln in mine])
        name = p["name"] if p is not None else NOT_LISTED
        rows.extend(_total_rows("프로젝트원가", key, name, "WEHAGO 원가", total, len(mine), _unknown_note(unknown, "줄"), history))
        if p is not None:
            notes = (["프로젝트번호 겹침 (첫 줄의 실행가)"] if p.get("dup") else []) + (
                ["실행가 빈칸"] if p["budget"] is None else [])
            rows.append(_row("프로젝트원가", key, name, "실행가", p["budget"], None, " · ".join(notes)))
            asked = [r for r in known if r["code"] == key]
            total, _ = _known_sum([r["amount"] for r in asked])
            rows.append(_row("프로젝트원가", key, name, "요청 누계", total, len(asked), _request_note(asked)))
    return rows


def _unlinked_cost_rows(costs):
    lines = [ln for ln in costs["lines"] if ln["project"] is None]
    total, unknown = _known_sum([ln["amount"] for ln in lines])
    rows = [_row("미연결원가", "합계", "", "WEHAGO 원가", total, len(lines), _unknown_note(unknown, "줄"))]
    for ln in lines:
        rows.append(_row("미연결원가줄", _line_target(ln), ln["vendor"], ln["label"], ln["amount"], 1, ln["memo"]))
    return rows


def _vendor_rows(books, requests, match):
    """거래처미지급: wehago.vendor_payables 가 보이는 거래처마다 WEHAGO 미지급과 인트라넷 요청 (X-4), 그리고 요약."""
    vp = vendor_payables(books, requests, match)
    rows = []
    for v in vp["rows"]:
        key = norm_vendor(v["vendor"])
        asked = [r for r in requests if r["status"] in ("pending", "approved") and norm_vendor(r["vendor"]) == key
                 and match["rows"].get(r["번호"], {}).get("status") != "이미 지급"]
        rows.append(_row("거래처미지급", "", v["vendor"], "WEHAGO 미지급", v["payable"], None, v["reason"]))
        rows.append(_row("거래처미지급", "", v["vendor"], "인트라넷 요청", None if v["requested_unknown"] else v["requested"],
                         len(asked), _unknown_note(v["requested_unknown"], "건")))
    absent = "분개장 미지급금 줄 없음 %d곳" % vp["absent_count"] if vp["absent_count"] else ""
    rows.append(_row("거래처미지급요약", "", "", "비교 거래처", None, vp["compared"], vp["note"]))
    rows.append(_row("거래처미지급요약", "", "", "차이 있는 거래처", vp["diff_sum"], vp["diff_count"],
                     "판단 불가 %d곳 제외" % vp["unknown_count"] if vp["unknown_count"] else ""))
    rows.append(_row("거래처미지급요약", "", "", "판단 불가 거래처", None, vp["unknown_count"], absent))
    return rows


def _revenue_rows(projects, revenue, project_rows, history=None):
    """매출계약: 프로젝트마다 WEHAGO 매출, 계약금액 (수동 입력, 빈칸·숫자 아님은 미등록), 견적금액. 계약금액은 매출로 채우지 않는다 (D-49)."""
    typed = dict(((r.get("프로젝트번호") or "").strip(), r.get("계약금액", "")) for r in project_rows)
    history = history or {}
    rows = []
    for key in _project_keys(projects, revenue["lines"]):
        p = projects.get(key)
        mine = [ln for ln in revenue["lines"] if ln["project"] == key]
        total, unknown = _known_sum([ln["amount"] for ln in mine])
        name = p["name"] if p is not None else NOT_LISTED
        rows.extend(_total_rows("매출계약", key, name, "WEHAGO 매출", total, len(mine), _unknown_note(unknown, "줄"), history))
        if p is not None:
            contract = num(typed.get(key, ""))
            rows.append(_row("매출계약", key, name, "계약금액 (수동 입력)", contract, None, "" if contract is not None else "미등록"))
            rows.append(_row("매출계약", key, name, "견적금액", p["quote"], None, "" if p["quote"] is not None else "견적금액 빈칸"))
    return rows


def _unlinked_revenue_rows(revenue):
    lines = [ln for ln in revenue["lines"] if ln["project"] is None]
    total, unknown = _known_sum([ln["amount"] for ln in lines])
    rows = [_row("매출미연결", "합계", "", "WEHAGO 매출", total, len(lines), _unknown_note(unknown, "줄"))]
    for ln in lines:
        rows.append(_row("매출미연결줄", _line_target(ln), ln["vendor"], ln["label"], ln["amount"], 1, ln["memo"]))
    return rows


def _status_note(requests):
    """상태를 읽지 못한 요청(D-52)은 요청 누계·프로젝트밖요청에 넣고 요청상태확인필요 줄로 따로 보인다: 그 사실과 번호·금액."""
    bad = [r for r in requests if _is_unknown(r)]
    if not bad:
        return []
    listing = ", ".join("%s %s %s (%s)" % (r["번호"], r["vendor"], won(r["amount"]), r.get("status_text") or "빈칸") for r in bad)
    return ["상태 확인 필요 지급요청 %d건은 요청 누계·프로젝트밖요청에 넣음 (D-52, 승인 화면은 '확인 필요'로 셈): %s" % (len(bad), listing)]


# ───────────── 보통예금 (D-48) ─────────────
OPENING_WORDS = ("전기이월", "기초잔액")
NO_OPENING = "판단 불가 — 기초 잔액 줄 없음"
CASH_OPENING = "기초 잔액"
CASH_CHANGE = "WEHAGO 증감 (전체 기간)"
CASH_BALANCE = "WEHAGO 잔액 (장부 기준일)"
CASH_BANK = "계좌잔액.csv 잔액 합계"
MONTH_CHANGE = "WEHAGO 증감"
MONTH_BANK = "입출금내역 증감 (입금−출금)"


def _squash(text):
    return re.sub(r"\s+", "", text or "")


def _line_net(line):
    d, c = line.get("debit"), line.get("credit")
    return None if d is None and c is None else (d or 0) - (c or 0)


def _bank_balance(rows):
    """(합계, 계좌 수, 비고): 계좌명마다 기준일이 가장 늦은 줄의 잔액을 더한다. 모르는 것이 하나라도 있으면 합계는 None."""
    if rows is None:
        return None, None, "계좌잔액.csv 없음"
    if not rows:
        return None, None, "계좌잔액.csv 줄 없음"
    latest, undated = {}, 0
    for r in rows:
        day = util.date(r.get("기준일"))
        if day is None:
            undated += 1
            continue
        account, balance = (r.get("계좌명") or "").strip(), num(r.get("잔액"))
        cur = latest.get(account)
        if cur is None or day > cur[0]:
            latest[account] = (day, [balance])
        elif day == cur[0]:
            cur[1].append(balance)
    unknown = sum(1 for _, balances in latest.values() if None in balances or len(set(balances)) > 1)
    parts = (["기준일 확인 불가 %d건" % undated] if undated else []) + (["금액 미확인 %d건" % unknown] if unknown else [])
    if parts:
        return None, len(latest), " · ".join(parts)
    total = sum(balances[0] for _, balances in latest.values())
    return total, len(latest), "기준일 " + ", ".join(sorted(set(d.isoformat() for d, _ in latest.values())))


def _tx_months(rows):
    """입출금내역 줄 -> ({연월: 합계·건수·모르는 줄}, 날짜를 읽지 못한 줄 수). 출금은 부호와 관계없이 나간 돈이다."""
    months, undated = {}, 0
    for r in rows:
        day = util.date(r.get("일자"))
        if day is None:
            undated += 1
            continue
        e = months.setdefault(day.strftime("%Y-%m"), {"sum": 0, "count": 0, "amount_unknown": 0, "io_unknown": 0})
        e["count"] += 1
        io, amount = (r.get("입출금") or "").strip(), num(r.get("금액"))
        if io not in ("입금", "출금"):
            e["io_unknown"] += 1
        elif amount is None:
            e["amount_unknown"] += 1
        else:
            e["sum"] += amount if io == "입금" else -abs(amount)
    return months, undated


def _bank_month_row(ym, ym_rows, undated):
    """보통예금월 입출금내역 줄 하나. ym_rows: None(파일 없음) 또는 _tx_months 결과."""
    if ym_rows is None:
        return _row("보통예금월", ym, "", MONTH_BANK, None, None, "입출금내역.csv 없음")
    if undated:
        return _row("보통예금월", ym, "", MONTH_BANK, None, None, "일자 확인 불가 %d건" % undated)
    e = ym_rows.get(ym)
    if e is None:
        return _row("보통예금월", ym, "", MONTH_BANK, None, None, "입출금내역 없음")
    parts = (["금액 미확인 %d건" % e["amount_unknown"]] if e["amount_unknown"] else []) + (
        ["입출금 구분 확인 불가 %d건" % e["io_unknown"]] if e["io_unknown"] else [])
    return _row("보통예금월", ym, "", MONTH_BANK, None if parts else e["sum"], e["count"], " · ".join(parts))


def _cash_rows(books, cfg, bank):
    """(줄, 알림, 원본 증감 합계). 현금 줄 = 설정 현금계정. 전기이월·기초잔액 줄은 기초 잔액이고 어느 증감에도 넣지 않는다 (X-3)."""
    codes = set(_squash(c) for c in cfg["cash_codes"])
    cash = [ln for ln in books.journal if _squash(ln["account_code"]) in codes]
    opening = [ln for ln in cash if any(w in _squash(ln["memo"]) for w in OPENING_WORDS)]
    moves = [ln for ln in cash if not any(w in _squash(ln["memo"]) for w in OPENING_WORDS)]
    notes = []
    open_total, open_unknown = _known_sum([_line_net(ln) for ln in opening])
    move_total, move_unknown = _known_sum([_line_net(ln) for ln in moves])
    ref = books.book_date
    undated = [ln for ln in moves if ln["date"] is None]
    later = [ln for ln in moves if ln["date"] is not None and ref is not None and ln["date"] > ref]
    upto = [ln for ln in moves if ln["date"] is not None and (ref is None or ln["date"] <= ref)]
    upto_total, upto_unknown = _known_sum([_line_net(ln) for ln in upto])
    if not opening:
        balance, balance_note = None, NO_OPENING
        if moves:
            notes.append("보통예금 기초 잔액(전기이월·기초잔액) 줄이 없어 장부 잔액은 판단 불가")
    elif open_unknown:
        balance, balance_note = None, "기초 잔액 " + _unknown_note(open_unknown, "줄")
    elif undated:
        balance, balance_note = None, "현금 줄 날짜 없음 %d줄 — 장부 기준일 이전인지 알 수 없음" % len(undated)
    elif upto_unknown:
        balance, balance_note = None, _unknown_note(upto_unknown, "줄")
    else:
        balance = open_total + upto_total
        balance_note = "장부 기준일 이후 %d줄 제외" % len(later) if later else ""
    amount, accounts, bank_note = _bank_balance(bank.get("balances"))
    rows = [_row("보통예금", "", "", CASH_OPENING, open_total if opening else None, len(opening),
                 NO_OPENING if not opening else _unknown_note(open_unknown, "줄")),
            _row("보통예금", "", "", CASH_CHANGE, move_total, len(moves), _unknown_note(move_unknown, "줄")),
            _row("보통예금", "", "", CASH_BALANCE, balance, None, balance_note),
            _row("보통예금", "", "", CASH_BANK, amount, accounts, bank_note)]
    if bank.get("balances") is not None:
        notes.append("계좌잔액.csv는 현금계정 밖 계좌도 담을 수 있음")
    tx = bank.get("transactions")
    tx_months, tx_undated = (None, 0) if tx is None else _tx_months(tx)
    by_month = {}
    for ln in moves:
        if ln["date"] is not None:
            by_month.setdefault(ln["date"].strftime("%Y-%m"), []).append(ln)
    for ym in sorted(by_month):
        lines = by_month[ym]
        total, unknown = _known_sum([_line_net(ln) for ln in lines])
        rows.append(_row("보통예금월", ym, "", MONTH_CHANGE, total, len(lines), _unknown_note(unknown, "줄")))
        rows.append(_bank_month_row(ym, tx_months, tx_undated))
    if tx_months:
        only = sorted(set(tx_months) - set(by_month))
        if only:
            notes.append("입출금내역 %s 월은 분개장 현금 줄이 없어 보통예금월에 싣지 않음" % ", ".join(only))
    return rows, notes, move_total


def _source_total(books, cfg, kind):
    """장부 분개장에서 바로 구한 합계 (연결 결과를 거치지 않는다). 금액을 모르는 줄이 있으면 None."""
    return _known_sum([_net(line, kind) for line in books.journal if _classify(line, cfg) == kind])[0]


def build_xchk(books, costs, revenue, projects, requests, match, project_rows, meta, cfg, bank):
    """위하고대조.csv 표. 입력은 바꾸지 않고 파일은 열지 않는다 (bank: {"balances": 줄 또는 None, "transactions": 줄 또는 None})."""
    bank = bank or {}
    if books.state != "ok":
        return Table(XCHK_FILE, XCHK_COLUMNS, [], written=False, reason="WEHAGO 장부를 쓸 수 없음")
    meta = collections.OrderedDict(meta)
    meta["분개장 기간"] = period_text(books) or "날짜 있는 전표 없음"   # 누계 칸이 어느 기간의 합인지 (WR-05)
    history = out_of_period(books, projects, requests)
    rows = _meta_rows(meta)
    status_rows = _status_rows(match)
    cost_rows = _cost_rows(projects, costs, requests, history)
    unlinked_rows = _unlinked_cost_rows(costs)
    revenue_rows = _revenue_rows(projects, revenue, project_rows, history)
    unlinked_revenue = _unlinked_revenue_rows(revenue)
    rows.extend(status_rows)
    rows.extend(_status_check_rows(requests))
    rows.extend(cost_rows)
    rows.extend(_request_rows(projects, requests))
    rows.extend(unlinked_rows)
    rows.extend(_vendor_rows(books, requests, match))
    rows.extend(revenue_rows)
    rows.extend(unlinked_revenue)
    cash_rows, cash_notes, move_total = _cash_rows(books, cfg, bank)
    rows.extend(cash_rows)

    checks = []
    wehago_cells = _period_cells(cost_rows, "WEHAGO 원가")
    total_row = [r for r in unlinked_rows if r["구분"] == "미연결원가"][0]
    checks.append(Check("(도) 원가 = 프로젝트원가 + 미연결원가", _source_total(books, cfg, "direct"),
                        _sum_cells(wehago_cells + [total_row])))
    sales = _period_cells(revenue_rows, "WEHAGO 매출")
    sales_total = [r for r in unlinked_revenue if r["구분"] == "매출미연결"][0]
    checks.append(Check("매출 = 매출계약 WEHAGO 매출 + 매출미연결", _source_total(books, cfg, "revenue"),
                        _sum_cells(sales + [sales_total])))
    checks.append(Check("지급요청 건수 = 요청상태 건수 합계", len(requests),
                        sum(int(r["건수"]) for r in status_rows if r["항목"] == "인트라넷 요청")))
    checks.append(request_total_check(requests, rows))
    source_lines = sum(1 for ln in costs["lines"] if ln["project"] is None)
    checks.append(Check("미연결 원가 줄", source_lines, sum(1 for r in unlinked_rows if r["구분"] == "미연결원가줄")))
    checks.append(Check("현금계정 증감 = 보통예금월 WEHAGO 증감 합계", move_total,
                        _sum_cells([r for r in cash_rows if r["구분"] == "보통예금월" and r["항목"] == MONTH_CHANGE])))
    checks.extend(period_checks(history, rows))
    notes = _status_note(requests) + cash_notes
    if history:
        notes.append("기간 밖 이력이 있는 프로젝트 %d건: WEHAGO 원가·매출 누계 판단 불가 (분개장 기간 합계는 따로 한 줄): %s"
                     % (len(history), "; ".join("%s (%s)" % (k, v) for k, v in history.items())))
    return Table(XCHK_FILE, XCHK_COLUMNS, rows, checks, notes)


# ───────────── load_xchk ─────────────
class _Unreadable(Exception):
    """파일 안 한 줄을 읽을 수 없음. 메시지가 그대로 이유가 된다."""


def _blank_result(state, reason):
    return {"state": state, "reason": reason, "meta": collections.OrderedDict(), "status": collections.OrderedDict(),
            "status_check": _fact(None), "status_check_lines": [], "has_status_check": False,
            "projects": [], "outside": _fact(None), "unlinked": _fact(None), "unlinked_lines": [], "vendors": [],
            "vendor_summary": dict.fromkeys(("compared", "note", "diff_sum", "diff_count", "diff_note", "unknown_count",
                                             "unknown_note")),
            "revenue": [], "revenue_unlinked": _fact(None), "revenue_unlinked_lines": [],
            "cash": _blank_cash(), "cash_months": [], "totals": dict.fromkeys(TOTAL_KEYS)}


TOTAL_KEYS = ("contract_sum", "contract_registered", "contract_unregistered", "budget_sum", "budget_known", "budget_blank",
              "budget_dup", "over_budget")


def _blank_cash():
    return {"opening": None, "opening_lines": None, "opening_note": "", "change": None, "change_lines": None,
            "change_note": "", "balance": None, "balance_note": "", "bank_balance": None, "bank_accounts": None,
            "bank_note": "", "balance_diff": None}


def _fact(row):
    """합계 줄 하나의 사실: 금액(숫자 또는 None), 건수(정수 또는 None), 비고."""
    if row is None:
        return {"amount": None, "count": None, "note": ""}
    return {"amount": row["_amount"], "count": row["_count"], "note": row["비고"]}


def _parse(row):
    """금액·건수 칸을 숫자로 바꿔 줄에 붙인다. 숫자가 아닌 글자가 있으면 _Unreadable (잘못된 숫자를 내지 않음)."""
    where = "%s %s번째 줄" % (XCHK_FILE, row.get("_line", "?"))
    text = row.get("금액", "")
    value = num(text)
    if value is None and not is_blank(text):
        raise _Unreadable("%s 금액 값이 숫자가 아님: '%s'" % (where, mask_rrn(text)))
    row["_amount"] = value
    text = row.get("건수", "")
    count = None
    if not is_blank(text):
        if not re.match(r"^\d+$", str(text).strip()):
            raise _Unreadable("%s 건수 값이 숫자가 아님: '%s'" % (where, mask_rrn(text)))
        count = int(str(text).strip())
    row["_count"] = count
    return row


def _project_of(row):
    return {"key": row["대상"], "name": row["이름"], "cost": None, "cost_lines": None, "cost_note": "", "cost_period": None,
            "out_of_period": False, "budget": None,
            "budget_note": "", "has_budget": False, "requested": None, "requested_count": None,
            "requested_note": "", "cost_vs_budget": None, "request_vs_cost": None}


def _contract_of(row):
    return {"key": row["대상"], "name": row["이름"], "wehago": None, "wehago_lines": None, "wehago_note": "",
            "wehago_period": None, "out_of_period": False,
            "has_contract": False, "contract": None, "contract_note": "", "quote": None, "quote_note": ""}


def _load_rows(rows):
    out = _blank_result("ok", "")
    projects, contracts = collections.OrderedDict(), collections.OrderedDict()
    months = collections.OrderedDict()
    for row in rows:
        kind, item = row.get("구분", ""), row.get("항목", "")
        if kind == "기준":
            out["meta"][item] = row["비고"]
        elif kind == "프로젝트원가":
            p = projects.setdefault(row["대상"], _project_of(row))
            if item == "WEHAGO 원가":
                p["cost"], p["cost_lines"], p["cost_note"] = row["_amount"], row["_count"], row["비고"]
                p["out_of_period"] = row["비고"].startswith(OUT_OF_PERIOD)
            elif item == "WEHAGO 원가" + PERIOD_SUFFIX:
                p["cost_period"] = row["_amount"]
            elif item == "실행가":
                p["budget"], p["budget_note"], p["has_budget"] = row["_amount"], row["비고"], True
            elif item == "요청 누계":
                p["requested"], p["requested_count"], p["requested_note"] = row["_amount"], row["_count"], row["비고"]
        elif kind == "요청상태":
            st = out["status"].setdefault(row["대상"], {"amount": None, "count": None, "note": "", "invoice": None,
                                                      "invoice_count": None, "invoice_note": ""})
            if item == "WEHAGO 계산서":
                st["invoice"], st["invoice_count"], st["invoice_note"] = row["_amount"], row["_count"], row["비고"]
            else:
                st["amount"], st["count"], st["note"] = row["_amount"], row["_count"], row["비고"]
        elif kind == "프로젝트밖요청":
            out["outside"] = _fact(row)
        elif kind == STATUS_CHECK:
            out["status_check"], out["has_status_check"] = _fact(row), True
        elif kind == STATUS_CHECK + "줄":
            out["status_check_lines"].append({"key": row["대상"], "vendor": row["이름"], "label": row["항목"],
                                              "amount": row["_amount"], "memo": row["비고"]})
        elif kind == "거래처미지급":
            if item == "WEHAGO 미지급":
                out["vendors"].append({"vendor": row["이름"], "payable": row["_amount"], "payable_note": row["비고"],
                                       "requested": None, "requested_count": None, "requested_note": ""})
            elif out["vendors"] and out["vendors"][-1]["vendor"] == row["이름"]:
                v = out["vendors"][-1]
                v["requested"], v["requested_count"], v["requested_note"] = row["_amount"], row["_count"], row["비고"]
        elif kind == "거래처미지급요약":
            vs = out["vendor_summary"]
            if item == "비교 거래처":
                vs["compared"], vs["note"] = row["_count"], row["비고"]
            elif item == "차이 있는 거래처":
                vs["diff_sum"], vs["diff_count"], vs["diff_note"] = row["_amount"], row["_count"], row["비고"]
            elif item == "판단 불가 거래처":
                vs["unknown_count"], vs["unknown_note"] = row["_count"], row["비고"]
        elif kind == "매출계약":
            c = contracts.setdefault(row["대상"], _contract_of(row))
            if item == "WEHAGO 매출":
                c["wehago"], c["wehago_lines"], c["wehago_note"] = row["_amount"], row["_count"], row["비고"]
                c["out_of_period"] = row["비고"].startswith(OUT_OF_PERIOD)
            elif item == "WEHAGO 매출" + PERIOD_SUFFIX:
                c["wehago_period"] = row["_amount"]
            elif item == "계약금액 (수동 입력)":
                c["contract"], c["contract_note"], c["has_contract"] = row["_amount"], row["비고"], True
            elif item == "견적금액":
                c["quote"], c["quote_note"] = row["_amount"], row["비고"]
        elif kind == "보통예금":
            _load_cash(out["cash"], row)
        elif kind == "보통예금월":
            m = months.setdefault(row["대상"], {"month": row["대상"], "wehago": None, "wehago_lines": None,
                                              "wehago_note": "", "bank": None, "bank_count": None, "bank_note": "",
                                              "diff": None})
            if item == "WEHAGO 증감":
                m["wehago"], m["wehago_lines"], m["wehago_note"] = row["_amount"], row["_count"], row["비고"]
            else:
                m["bank"], m["bank_count"], m["bank_note"] = row["_amount"], row["_count"], row["비고"]
        elif kind == "매출미연결":
            out["revenue_unlinked"] = _fact(row)
        elif kind == "매출미연결줄":
            out["revenue_unlinked_lines"].append({"key": row["대상"], "vendor": row["이름"], "label": row["항목"],
                                                  "amount": row["_amount"], "memo": row["비고"]})
        elif kind == "미연결원가":
            out["unlinked"] = _fact(row)
        elif kind == "미연결원가줄":
            out["unlinked_lines"].append({"key": row["대상"], "vendor": row["이름"], "label": row["항목"],
                                          "amount": row["_amount"], "memo": row["비고"]})
    out["projects"] = list(projects.values())
    out["revenue"] = list(contracts.values())
    out["cash_months"] = list(months.values())
    _derive(out)
    return out


def _load_cash(cash, row):
    item, amount, count, note = row["항목"], row["_amount"], row["_count"], row["비고"]
    if item == "기초 잔액":
        cash["opening"], cash["opening_lines"], cash["opening_note"] = amount, count, note
    elif item == "WEHAGO 증감 (전체 기간)":
        cash["change"], cash["change_lines"], cash["change_note"] = amount, count, note
    elif item == "WEHAGO 잔액 (장부 기준일)":
        cash["balance"], cash["balance_note"] = amount, note
    elif item == "계좌잔액.csv 잔액 합계":
        cash["bank_balance"], cash["bank_accounts"], cash["bank_note"] = amount, count, note


def _minus(a, b):
    return None if a is None or b is None else a - b


def _derive(out):
    """차이는 파일에 없는 사실이 아니라 두 사실의 뺄셈이다: 두 값을 모두 알 때만 구하고 아니면 None (0 아님)."""
    for p in out["projects"]:
        dup = "프로젝트번호 겹침" in p["budget_note"]
        p["cost_vs_budget"] = None if dup else _minus(p["cost"], p["budget"])
        p["request_vs_cost"] = _minus(p["requested"], p["cost"])
    for v in out["vendors"]:
        v["diff"] = _minus(v["payable"], v["requested"])
    cash = out["cash"]
    if cash["opening"] is not None:
        cash["balance_diff"] = _minus(cash["balance"], cash["bank_balance"])
    for m in out["cash_months"]:
        m["diff"] = _minus(m["wehago"], m["bank"])
    listed = [p for p in out["projects"] if p["has_budget"]]
    dup = [p for p in listed if "프로젝트번호 겹침" in p["budget_note"]]
    known = [p for p in listed if p["budget"] is not None and p not in dup]
    blank = [p for p in listed if p["budget"] is None and p not in dup]
    contracts = [c for c in out["revenue"] if c["has_contract"]]
    registered = [c for c in contracts if c["contract"] is not None]
    out["totals"] = {
        "contract_sum": sum(c["contract"] for c in registered), "contract_registered": len(registered),
        "contract_unregistered": len(contracts) - len(registered),
        "budget_sum": sum(p["budget"] for p in known), "budget_known": len(known), "budget_blank": len(blank),
        "budget_dup": len(dup),
        "over_budget": sum(1 for p in known if p["cost"] is not None and p["cost"] > p["budget"]),
    }


def load_xchk(input_dir):
    """입력/위하고대조.csv -> 월간 보고가 쓰는 사실 묶음. 예외를 내지 않는다.

    state: 'ok' | '자료 없음' (파일 없음) | '읽을 수 없음' (머리글 다름, 숫자 아닌 금액·건수, 열 수 문제 등; reason 에 이유).
    """
    path = os.path.join(str(input_dir), XCHK_FILE)
    try:
        if not os.path.exists(path):
            return _blank_result("자료 없음", "%s 없음" % XCHK_FILE)
        info = {}
        rows, ok = util.read_csv(path, XCHK_COLUMNS, util.Issues(), info)
        if not ok:
            return _blank_result("읽을 수 없음", "%s를 읽지 못함" % XCHK_FILE)
        if info.get("missing"):
            return _blank_result("읽을 수 없음", "%s 머리글 다름" % XCHK_FILE)
        return _load_rows([_parse(r) for r in rows])
    except _Unreadable as e:
        return _blank_result("읽을 수 없음", str(e))
    except Exception as e:  # 월간 보고가 이 파일 때문에 멈추지 않는다
        return _blank_result("읽을 수 없음", "%s를 읽지 못함 (%s)" % (XCHK_FILE, type(e).__name__))
