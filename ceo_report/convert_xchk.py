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


def _readable(requests):
    """승인 화면과 같은 규칙: 상태를 읽은 요청만 요청 누계에 든다."""
    return [r for r in requests if r["status"] != "status_unknown"]


def _request_rows(projects, requests):
    """프로젝트밖요청: 프로젝트 목록에 없는 코드의 요청 합계 (승인 화면 A-6 과 같은 규칙)."""
    outside = [r for r in _readable(requests) if r["code"] not in projects]
    total, unknown = _known_sum([r["amount"] for r in outside])
    return [_row("프로젝트밖요청", "합계", "", "인트라넷 요청", total, len(outside), _unknown_note(unknown, "건"))]


def _cost_rows(projects, costs, requests):
    """프로젝트원가: 프로젝트마다 WEHAGO 원가 (모든 날짜의 줄), 실행가, 요청 누계 (코드가 프로젝트 키이고 상태를 읽은 요청)."""
    rows = []
    known = _readable(requests)
    for key in _project_keys(projects, costs["lines"]):
        p = projects.get(key)
        mine = [ln for ln in costs["lines"] if ln["project"] == key]
        total, unknown = _known_sum([ln["amount"] for ln in mine])
        name = p["name"] if p is not None else NOT_LISTED
        rows.append(_row("프로젝트원가", key, name, "WEHAGO 원가", total, len(mine), _unknown_note(unknown, "줄")))
        if p is not None:
            rows.append(_row("프로젝트원가", key, name, "실행가", p["budget"], None,
                             "" if p["budget"] is not None else "실행가 빈칸"))
            asked = [r for r in known if r["code"] == key]
            total, unknown = _known_sum([r["amount"] for r in asked])
            rows.append(_row("프로젝트원가", key, name, "요청 누계", total, len(asked), _unknown_note(unknown, "건")))
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


def _revenue_rows(projects, revenue, project_rows):
    """매출계약: 프로젝트마다 WEHAGO 매출, 계약금액 (수동 입력, 빈칸·숫자 아님은 미등록), 견적금액. 계약금액은 매출로 채우지 않는다 (D-49)."""
    typed = dict(((r.get("프로젝트번호") or "").strip(), r.get("계약금액", "")) for r in project_rows)
    rows = []
    for key in _project_keys(projects, revenue["lines"]):
        p = projects.get(key)
        mine = [ln for ln in revenue["lines"] if ln["project"] == key]
        total, unknown = _known_sum([ln["amount"] for ln in mine])
        name = p["name"] if p is not None else NOT_LISTED
        rows.append(_row("매출계약", key, name, "WEHAGO 매출", total, len(mine), _unknown_note(unknown, "줄")))
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
    """상태를 읽지 못한 요청은 누계에 넣지 않는다: 그 사실과 번호·금액을 알린다 (조용히 빼지 않음)."""
    bad = [r for r in requests if r["status"] == "status_unknown"]
    if not bad:
        return []
    listing = ", ".join("%s %s %s" % (r["번호"], r["vendor"], won(r["amount"])) for r in bad)
    return ["상태 확인 필요 지급요청 %d건은 요청 누계·프로젝트밖요청에 넣지 않음 (승인 화면과 같은 규칙): %s" % (len(bad), listing)]


def _source_total(books, cfg, kind):
    """장부 분개장에서 바로 구한 합계 (연결 결과를 거치지 않는다). 금액을 모르는 줄이 있으면 None."""
    return _known_sum([_net(line, kind) for line in books.journal if _classify(line, cfg) == kind])[0]


def build_xchk(books, costs, revenue, projects, requests, match, project_rows, meta, cfg, bank):
    """위하고대조.csv 표. 입력은 바꾸지 않고 파일은 열지 않는다 (bank: {"balances": 줄 또는 None, "transactions": 줄 또는 None})."""
    if books.state != "ok":
        return Table(XCHK_FILE, XCHK_COLUMNS, [], written=False, reason="WEHAGO 장부를 쓸 수 없음")
    rows = _meta_rows(meta)
    status_rows = _status_rows(match)
    cost_rows = _cost_rows(projects, costs, requests)
    unlinked_rows = _unlinked_cost_rows(costs)
    revenue_rows = _revenue_rows(projects, revenue, project_rows)
    unlinked_revenue = _unlinked_revenue_rows(revenue)
    rows.extend(status_rows)
    rows.extend(cost_rows)
    rows.extend(_request_rows(projects, requests))
    rows.extend(unlinked_rows)
    rows.extend(_vendor_rows(books, requests, match))
    rows.extend(revenue_rows)
    rows.extend(unlinked_revenue)

    checks = []
    wehago_cells = [r for r in cost_rows if r["항목"] == "WEHAGO 원가"]
    total_row = [r for r in unlinked_rows if r["구분"] == "미연결원가"][0]
    checks.append(Check("(도) 원가 = 프로젝트원가 + 미연결원가", _source_total(books, cfg, "direct"),
                        _sum_cells(wehago_cells + [total_row])))
    sales = [r for r in revenue_rows if r["항목"] == "WEHAGO 매출"]
    sales_total = [r for r in unlinked_revenue if r["구분"] == "매출미연결"][0]
    checks.append(Check("매출 = 매출계약 WEHAGO 매출 + 매출미연결", _source_total(books, cfg, "revenue"),
                        _sum_cells(sales + [sales_total])))
    checks.append(Check("지급요청 건수 = 요청상태 건수 합계", len(requests),
                        sum(int(r["건수"]) for r in status_rows if r["항목"] == "인트라넷 요청")))
    source_lines = sum(1 for ln in costs["lines"] if ln["project"] is None)
    checks.append(Check("미연결 원가 줄", source_lines, sum(1 for r in unlinked_rows if r["구분"] == "미연결원가줄")))
    return Table(XCHK_FILE, XCHK_COLUMNS, rows, checks, _status_note(requests))


# ───────────── load_xchk ─────────────
class _Unreadable(Exception):
    """파일 안 한 줄을 읽을 수 없음. 메시지가 그대로 이유가 된다."""


def _blank_result(state, reason):
    return {"state": state, "reason": reason, "meta": collections.OrderedDict(), "status": collections.OrderedDict(),
            "projects": [], "outside": _fact(None), "unlinked": _fact(None), "unlinked_lines": [], "vendors": [],
            "vendor_summary": {}, "revenue": [], "revenue_unlinked": _fact(None), "revenue_unlinked_lines": [],
            "cash": {}, "cash_months": [], "totals": {}}


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
    return {"key": row["대상"], "name": row["이름"], "cost": None, "cost_lines": None, "cost_note": "", "budget": None,
            "budget_note": "", "requested": None, "requested_count": None, "requested_note": ""}


def _contract_of(row):
    return {"key": row["대상"], "name": row["이름"], "wehago": None, "wehago_lines": None, "wehago_note": "",
            "contract": None, "contract_note": "", "quote": None, "quote_note": ""}


def _load_rows(rows):
    out = _blank_result("ok", "")
    projects, contracts = collections.OrderedDict(), collections.OrderedDict()
    for row in rows:
        kind, item = row.get("구분", ""), row.get("항목", "")
        if kind == "기준":
            out["meta"][item] = row["비고"]
        elif kind == "프로젝트원가":
            p = projects.setdefault(row["대상"], _project_of(row))
            if item == "WEHAGO 원가":
                p["cost"], p["cost_lines"], p["cost_note"] = row["_amount"], row["_count"], row["비고"]
            elif item == "실행가":
                p["budget"], p["budget_note"] = row["_amount"], row["비고"]
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
            elif item == "계약금액 (수동 입력)":
                c["contract"], c["contract_note"] = row["_amount"], row["비고"]
            elif item == "견적금액":
                c["quote"], c["quote_note"] = row["_amount"], row["비고"]
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
    return out


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
