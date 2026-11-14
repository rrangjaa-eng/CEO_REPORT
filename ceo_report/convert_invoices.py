"""계산서.csv 만들기 (Phase 2, D-41, D-51): 매출 계산서 원천 + 분개장 매출채권 수금 -> convert.Table.

순수 함수다: 파일을 읽거나 쓰지 않는다 (원천 읽기는 wehago.load_sales, 파일 쓰기는 02-07 의 convert.run).
- 프로젝트: 계산서 자기 [코드] -> 같은 거래처·날짜·공급가액의 분개장 매출 줄(수동 연결 포함) -> 클라이언트·견적금액 -> 미연결 (버리지 않음).
- 입금: 매출채권(cfg receivable_codes) 대변 중 같은 전표에 자산 계정 차변이 있는 줄이 입금이다. 자산 계정은 cfg cash_codes 와
  10xxx 계정(매출채권 계정 제외: 다른 보통예금 세목·현금·예금 등)이다 (02-REVIEW CR-05). 자산 차변이 없는 대변은
  '수정(계산서 감액)' 줄로 따로 보이고 계산서에 입금으로 붙이지 않는다 (D-51). 금액이 같은 입금을 먼저 짝짓고, 남은 입금은
  거래처마다 (기초 미수가 있으면 그것 먼저) 오래된 계산서부터 채운다. 계산서 발행일 이후 입금만, 나눠 받은 입금도 붙인다
  (입금액 = 붙인 금액, 나머지는 미수). 수수료 차감 같은 작은 차이도 지우지 않고 '부분 입금'으로 보인다. 붙지 않은 입금은 '미배분 수금'.
- 대조 '매출채권 잔액': 분개장 매출채권 잔액 = 계산서.csv 미수 (합계 − 입금액) + 기초 미수 남음.
- 모르는 금액은 '' 이고 0이 아니다 (D-02). 합계를 모르는 계산서에는 입금을 붙이지 않는다.
계정 번호는 cfg(설정.csv 변환_*) 에서만 읽는다.
"""
import collections
import datetime as dt
import re

from . import data, linking
from .convert import Check, Table, cell_amount, cell_date
from .util import date as parse_date
from .util import mask_rrn, num, won
from .wehago import norm_vendor

BASES = ("코드", "분개장 매출 줄", "자동", "미연결", "참고")   # 참고 = 지난해 계산서 (연결하지 않음, 사용자 2026-11-04)
_NONE_REASON = "자료 없음 (매출 계산서 엑셀)"
_FIRM = ("Y", "N", "확정", "")
DUE_GUESS_DAYS = 60   # 입금예정일 빈칸 = 작성일 + 이 날수 (사용자 2026-11-12, F9)
_FAR = dt.date.max
BALANCE_LABEL = "매출채권 잔액: 분개장 (차변−대변) = 계산서.csv 미수 (합계−입금액) + 기초 미수 남음"
_ASSET = re.compile(r"^10\d{3}$")


def _squash(text):
    return re.sub(r"\s+", "", text or "")


def _norm_no(text):
    s = ("" if text is None else str(text)).strip()
    return re.sub(r"^(\d+)\.0+$", r"\1", s)


def _no_key(no):
    return (0, int(no), no) if no.isdigit() else (1, 0, no)


def _is_opening(row):
    memo = _squash(row.get("memo"))
    return "전기이월" in memo or "기초잔액" in memo


def _sum_or_none(values):
    """모르는 값이 하나라도 있으면 None (B5)."""
    total = 0
    for v in values:
        if v is None:
            return None
        total += v
    return total


def _day(d):
    return d.isoformat() if d else "날짜 없음"


# ───────────── 계산서 하나하나: 프로젝트(I-1)·구분(I-2) ─────────────
def _kind_of(inv):
    kind = inv["type"]
    if "취소" in kind:
        return "취소"
    if "수정" in kind or (inv["supply"] is not None and inv["supply"] < 0):
        return "수정"
    if inv.get("advance") is not None:   # 분개장 매출전표: 대변 선수금 계정 줄로 판단 (사용자 2026-11-14, 품명 낱말은 보지 않음)
        return "선수금" if inv["advance"] else "발행"
    if any(w in inv["item"] for w in ("선금", "선수", "계약금")):   # 계정을 모르는 원천(매출 계산서 엑셀)만 품명 낱말로
        return "선수금"
    return "발행"


def _project_of(inv, rev_lines, projects):
    """(프로젝트번호, 근거, 미연결 이유). 근거는 BASES 중 하나."""
    reasons = []
    code = inv["code"]
    if code:
        if not projects or code in projects:
            return code, "코드", ""
        reasons.append("코드 %s 프로젝트 목록에 없음" % code)
    if inv["supply"] is None:
        reasons.append("공급가액 미확인")
    elif inv["date"] is None:
        reasons.append("발행일 없음")
    else:
        same = [ln for ln in rev_lines if inv["vendor_norm"] and ln["vendor_norm"] == inv["vendor_norm"]
                and ln["date"] == inv["date"] and ln["amount"] == inv["supply"]]
        linked = sorted(set(ln["project"] for ln in same if ln["project"] is not None))
        if len(linked) == 1:
            return linked[0], "분개장 매출 줄", ""
        if not same:
            reasons.append("분개장 매출 줄 없음")
        elif not linked:
            reasons.append("분개장 매출 줄 미연결")
        else:
            reasons.append("분개장 매출 줄이 서로 다른 프로젝트 %d건" % len(linked))
    if not projects:
        reasons.append("프로젝트 목록 없음")
    else:
        found = sorted(k for k, p in projects.items() if not p["dup"] and inv["vendor_norm"] and inv["supply"] is not None
                       and p["client_norm"] == inv["vendor_norm"] and p["quote"] == inv["supply"])
        if len(found) == 1:
            return found[0], "자동", ""
        reasons.append("클라이언트·견적금액 후보 %d건" % len(found))
    return "", "미연결", " · ".join(reasons)


def _portions(inv, rev_lines):
    """계산서 한 장(매출전표)의 매출 줄이 여러 프로젝트로 나뉘어 있으면 [(프로젝트번호 또는 '', 공급가액)] (사용자 2026-11-11).

    한 프로젝트에 통째로 붙이면 나머지 프로젝트가 '발행 0원'으로 보인다 (실제 자료: 매출전표 232장 중 27장).
    같은 전표(전표일자·전표번호)의 매출 줄 합이 계산서 공급가액과 같을 때만 나눈다. 아니면 None (나누지 않음)."""
    if not inv["no"] or inv["date"] is None or not inv["supply"]:
        return None
    mine = [ln for ln in rev_lines if ln["date"] == inv["date"] and _norm_no(ln["no"]) == _norm_no(inv["no"])]
    if len(mine) < 2 or any(ln["amount"] is None for ln in mine) or sum(ln["amount"] for ln in mine) != inv["supply"]:
        return None
    parts = collections.OrderedDict()
    for ln in mine:
        key = "" if ln.get("prior") else (ln["project"] or "")
        parts[key] = parts.get(key, 0) + ln["amount"]
    if len(parts) < 2:
        return None
    return [(k, v) for k, v in parts.items() if v]


def _share(total, parts):
    """total 을 parts(공급가액들) 비율로 나눈다. 원 단위 끝전은 마지막 줄에 (합은 그대로)."""
    base = sum(parts)
    out = [int(round(total * float(a) / base)) for a in parts[:-1]]
    return out + [total - sum(out)]


def _invoices(rows):
    out = []
    for i, r in enumerate(rows):
        supply, vat = r.get("supply"), r.get("vat")
        out.append({"idx": i, "date": r.get("date"), "vendor": mask_rrn(r.get("vendor")),
                    "vendor_norm": r.get("vendor_norm") or norm_vendor(r.get("vendor")), "item": mask_rrn(r.get("item")),
                    "supply": supply, "vat": vat, "source_total": r.get("total"),
                    "total": None if supply is None or vat is None else supply + vat,
                    "code": r.get("code"), "type": r.get("type") or "", "no": r.get("no") or "",
                    "applied": 0, "paid_date": None, "project": "", "basis": "미연결", "why": "",
                    "deducted": r.get("deducted") or 0,   # 매출 때 바로 차감된 금액 (카드 수수료): 입금액에 넣는다
                    "advance": r.get("advance")})   # 분개장 매출전표에 선수금 계정 줄이 있는가 (모르면 None)
    return out


# ───────────── 분개장 매출채권 줄: 입금·수정·이월 (I-3) ─────────────
class _Journal(object):
    """매출채권 줄을 입금 / 수정(계산서 감액) / 기초 미수로 나눈다. 입금 합계·대변 합계·거래처별 잔액을 같이 센다."""

    def __init__(self, books, cfg):
        rec = set(_squash(c) for c in cfg["receivable_codes"])
        cash = set(_squash(c) for c in cfg["cash_codes"])

        def asset(code):   # 받은 돈이 들어가는 계정: 설정 현금 계정 + 10xxx 자산 계정 (매출채권 계정 제외) — CR-05
            return code in cash or (bool(_ASSET.match(code)) and code not in rec)
        journal = books.journal
        groups = collections.defaultdict(list)
        for i, row in enumerate(journal):
            groups[(row.get("date"), _norm_no(row.get("no")))].append(i)
        self.receipts, self.credits = [], []
        self.opening = collections.defaultdict(lambda: {"net": 0, "days": [], "applied": 0})
        self.opening_any = False
        self.balance = {}      # 거래처 -> 매출채권 차변-대변 (모르는 줄이 있으면 None)
        self.names = {}        # 거래처 -> 보이는 이름
        self.unknown = False   # 입금인지 아닌지 판단할 수 없는 줄이 있음
        self.credit_all = 0    # 매출채권 대변(차변을 뺀 값이 양수인 줄)의 합 -- 입금·수정을 나누기 전에 따로 센다
        for i, row in enumerate(journal):
            if _squash(row.get("account_code")) not in rec:
                continue
            vn = row.get("vendor_norm") or norm_vendor(row.get("vendor"))
            self.names.setdefault(vn, mask_rrn(row.get("vendor")))
            d, c = row.get("debit"), row.get("credit")
            if d is None and c is None:
                self.unknown = True
                self.balance[vn] = None
                continue
            if self.balance.get(vn, 0) is not None:
                self.balance[vn] = self.balance.get(vn, 0) + (d or 0) - (c or 0)
            if _is_opening(row):
                self.opening_any = True
                o = self.opening[vn]
                o["net"] += (d or 0) - (c or 0)
                if row.get("date") is not None:
                    o["days"].append(row["date"])
            net_credit = (c or 0) - (d or 0)
            if net_credit <= 0:
                continue
            self.credit_all += net_credit
            day, no = row.get("date"), _norm_no(row.get("no"))
            cash_debit = False
            for j in groups[(day, no)]:
                other = journal[j]
                if asset(_squash(other.get("account_code"))):
                    if other.get("debit") is None and other.get("credit") is None:
                        self.unknown = True
                    elif (other.get("debit") or 0) > 0:
                        cash_debit = True
            item = {"date": day, "no": no, "vn": vn, "vendor": mask_rrn(row.get("vendor")), "amount": net_credit,
                    "left": net_credit, "fifo": False}
            (self.receipts if cash_debit else self.credits).append(item)
        self.receipts.sort(key=lambda r: (r["date"] or _FAR, _no_key(r["no"]), r["vn"], r["amount"]))
        self.credits.sort(key=lambda r: (r["date"] or _FAR, _no_key(r["no"]), r["vn"], r["amount"]))


def _prior(inv):
    """지난해 계산서: linking.is_prior 와 같은 규칙 (발행일·코드)."""
    return linking.is_prior(inv["date"], (inv.get("code"),))


def _settle_prior(invoices):
    """지난해 계산서는 입금이 끝난 것으로 보고, 거래처마다 지난해 계산서에 남은 순 미수(수정 계산서 감액 포함)를
    같은 거래처 올해 계산서로 옮긴다 -> [(거래처, 옮긴 금액 (+ 올해 미수 늘어남 / − 줄어듦))].

    거래처 미수 합계(= 분개장 잔액)는 그대로이고, 어느 계산서에 붙느냐만 바뀐다 (사용자 2026-11-04).
    · 남은 순 미수가 + 이면: 올해 계산서 입금을 최근 발행분부터 뗀다 (같은 금액 입금으로 맞춘 계산서는 건드리지 않음).
    · − 이면 (지난해에 더 받은 돈): 올해 미수 계산서에 오래된 것부터 입금으로 붙인다.
    옮길 곳이 모자라면 모자란 만큼은 지난해 계산서에 그대로 남긴다.
    """
    by_vendor = collections.defaultdict(list)
    for inv in invoices:
        if inv["total"] is not None and inv["date"] is not None:
            by_vendor[inv["vendor_norm"]].append(inv)
    moved = []
    for vn, invs in by_vendor.items():
        old = [i for i in invs if i["basis"] == "참고"]
        if not old:
            continue
        rest = lambda i: i["total"] - i["deducted"] - i["applied"]
        net = sum(rest(i) for i in old)
        for o in old:   # 지난해 계산서는 모두 끝난 것으로
            if rest(o):
                o["applied"] += rest(o)
                o["paid_date"] = o["paid_date"] or o["date"]
        left = abs(net)
        if net == 0:
            continue
        if net > 0:
            pool = sorted((i for i in invs if i["basis"] != "참고" and i["total"] > 0 and i["applied"] > 0 and not i.get("exact")),
                          key=lambda i: (i["date"], i["idx"]), reverse=True)
            for n in pool:
                take = min(left, n["applied"])
                n["applied"] -= take
                if n["applied"] == 0:
                    n["paid_date"] = None
                left -= take
                if not left:
                    break
        else:
            pool = sorted((i for i in invs if i["basis"] != "참고" and i["total"] > 0 and rest(i) > 0),
                          key=lambda i: (i["date"], i["idx"]))
            for n in pool:
                give = min(left, rest(n))
                n["applied"] += give
                n["paid_date"] = n["paid_date"] or max(o["paid_date"] for o in old)
                left -= give
                if not left:
                    break
        if left:   # 옮길 곳이 모자란 만큼은 지난해 계산서에 남긴다
            back = max(old, key=lambda i: (i["date"], i["idx"]))
            back["applied"] -= left if net > 0 else -left
        if abs(net) - left:
            moved.append((vn, (abs(net) - left) * (1 if net > 0 else -1)))
    return moved


def _allocate(invoices, jr):
    """입금을 계산서에 붙인다 -> 거래처별 기초 미수 항목 {거래처: 항목}. 입금 항목의 left 가 남은 금액이다."""
    items = collections.defaultdict(list)
    skip_fifo = set()
    for inv in sorted(invoices, key=lambda x: (x["date"] or _FAR, x["idx"])):
        if inv["total"] is None:
            skip_fifo.add(inv["vendor_norm"])
        if inv["total"] is not None and inv["total"] > 0 and inv["date"] is not None:
            items[inv["vendor_norm"]].append({"inv": inv, "date": inv["date"], "remaining": inv["total"] - inv["deducted"]})
    opening = {}
    if jr.opening_any:
        for vn, o in jr.opening.items():
            if o["net"] > 0:
                opening[vn] = {"inv": None, "date": min(o["days"]) if o["days"] else None, "remaining": o["net"]}

    def apply(item, receipt, take):
        item["remaining"] -= take
        receipt["left"] -= take
        if item["inv"] is not None:
            item["inv"]["applied"] += take
            last = item["inv"]["paid_date"]
            item["inv"]["paid_date"] = receipt["date"] if last is None or receipt["date"] > last else last
        else:
            jr.opening[receipt["vn"]]["applied"] += take

    for r in jr.receipts:   # 1회전: 같은 금액 (발행일 이후)
        if r["date"] is None:
            continue
        for it in items.get(r["vn"], []):
            if it["remaining"] == it["inv"]["total"] - it["inv"]["deducted"] and it["remaining"] == r["amount"] and it["date"] <= r["date"]:
                apply(it, r, r["amount"])
                it["inv"]["exact"] = True
                break
    # 2회전 (CR-05: 기초 줄이 없어도 돈다): 거래처마다 기초 미수 먼저, 그다음 오래된 계산서부터. 발행일 이후 입금만, 나눠 붙일 수 있다
    for r in jr.receipts:
        if r["left"] <= 0 or r["date"] is None or r["vn"] in skip_fifo:
            continue
        queue = ([opening[r["vn"]]] if r["vn"] in opening else []) + items.get(r["vn"], [])
        for it in queue:
            if r["left"] <= 0:
                break
            if it["remaining"] <= 0 or (it["date"] is not None and it["date"] > r["date"]):
                continue
            apply(it, r, min(r["left"], it["remaining"]))
            r["fifo"] = True
    return skip_fifo


def balance_check(book_total, rows, opening_left, why):
    """대조 '매출채권 잔액' (CR-05): 분개장 매출채권 잔액 = 계산서.csv 줄의 (공급가액+부가세−입금액) 합 + 기초 미수 남음.

    rows 는 계산서.csv 줄(dict). 공급가액·부가세를 모르는 줄이 있으면 CSV 쪽을 모른다 (B5). why 가 있으면(분개장이 기간 앞
    잔액을 몰라 비교할 수 없음) 원본 쪽을 모르는 것으로 두어 '판단 불가'.
    """
    owed = []
    for r in rows:
        supply, vat = num(r.get("공급가액")), num(r.get("부가세"))
        text = (r.get("입금액") or "").strip()
        got = 0 if not text else num(text)
        owed.append(None if supply is None or vat is None or got is None else supply + vat - got)
    csv_side = _sum_or_none(owed)
    if csv_side is not None and opening_left is not None:
        csv_side += opening_left
    elif opening_left is None:
        csv_side = None
    return Check(BALANCE_LABEL, None if why else book_total, csv_side)


# ───────────── 이전 계산서.csv (I-5) ─────────────
def _carry(rows, prev_rows, notes):
    """새 줄마다 이전 줄 하나가 (거래처, 발행일, 공급가액)으로 정확히 맞으면 입금예정일·예정일확정을 옮긴다 -> {새 줄 번호: 이전 줄}."""
    index = collections.defaultdict(list)
    for p in prev_rows:
        key = (norm_vendor(p.get("거래처", "")), parse_date(p.get("발행일")), num(p.get("공급가액")))
        index[key].append(p)
    mine = collections.Counter((r["vendor_norm"], r["date"], r["supply"]) for r in rows)
    picked, used, said = {}, 0, set()
    for r in rows:
        key = (r["vendor_norm"], r["date"], r["supply"])
        if not key[0] or key[1] is None or key[2] is None or key not in index:
            continue
        if len(index[key]) > 1 or mine[key] > 1:
            if key not in said:
                said.add(key)
                notes.append("이전 계산서.csv와 새 계산서에 같은 거래처·발행일·공급가액 줄이 여러 건 (%s %s %s원) → 입금예정일 옮기지 않음"
                             % (r["vendor"], _day(key[1]), won(key[2])))
            continue
        picked[r["idx"]] = index[key][0]
        used += 1
    return picked, len(prev_rows) - used


def build_invoices(sales, books, revenue, projects, prev_rows, cfg):
    """sales(wehago.load_sales) + 분개장 입금 -> Table('계산서.csv'). 매출 원천이 없거나 틀리면 written=False (0으로 채우지 않음)."""
    columns = data.SCHEMA["계산서.csv"]
    if sales["state"] != "ok":
        return Table("계산서.csv", columns, [], written=False, reason=sales.get("reason") or _NONE_REASON)
    notes = list(sales["notes"])
    invoices = _invoices(sales["rows"])
    rev_lines = revenue["lines"] if revenue else []
    for inv in invoices:
        if _prior(inv):
            inv["project"], inv["basis"], inv["why"] = "", "참고", "지난해 계산서"
        else:
            inv["project"], inv["basis"], inv["why"] = _project_of(inv, rev_lines, projects)
        inv["kind"] = _kind_of(inv)
        inv["parts"] = _portions(inv, rev_lines)   # 지난해 프로젝트와 올해 프로젝트가 한 장에 섞인 계산서도 나눈다 (지난해 몫은 번호 없이)
    order = sorted(invoices, key=lambda x: (x["date"] or _FAR, x["idx"]))
    jr = _Journal(books, cfg)
    skip_fifo = _allocate(invoices, jr)
    moved = _settle_prior(invoices)
    if moved:
        notes.append("지난해 계산서는 입금 끝난 것으로 봄 (사용자 2026-11-04): 남은 순 미수를 같은 거래처 올해 계산서로 옮김 %d곳 "
                     "(올해 미수 늘어남 %s · 줄어듦 %s)" % (len(moved), won(sum(m[1] for m in moved if m[1] > 0)),
                                                won(-sum(m[1] for m in moved if m[1] < 0))))

    # 이전 계산서.csv: 입금예정일·예정일확정만 옮긴다. 입금은 WEHAGO 가 정한다 (D-37).
    carry_notes = []
    picked, not_carried = _carry(order, prev_rows, carry_notes)
    rows, bases = [], []
    mismatch = []
    split_n = split_rows = 0
    guessed = []   # 입금예정일을 작성일 + 60일로 채운 계산서 (F9)
    split_prev = {}   # 이전 계산서.csv 줄 (거래처, 발행일, 공급가액) -> 줄 (하나뿐일 때만)
    seen_prev = collections.Counter((norm_vendor(p.get("거래처", "")), parse_date(p.get("발행일")), num(p.get("공급가액"))) for p in prev_rows)
    for p in prev_rows:
        k = (norm_vendor(p.get("거래처", "")), parse_date(p.get("발행일")), num(p.get("공급가액")))
        if seen_prev[k] == 1:
            split_prev[k] = p
    for inv in order:
        old = picked.get(inv["idx"])
        due, firm = "", ""
        if old is not None:
            due = cell_date(parse_date(old.get("입금예정일")))
            firm = (old.get("예정일확정") or "").strip()
            firm = firm if firm in _FIRM else ""
            prev_paid = num(old.get("입금액"))
            now_paid = inv["applied"] + inv["deducted"] if inv["total"] is not None else None
            if prev_paid is not None and prev_paid != now_paid:
                mismatch.append("이전 계산서.csv와 입금 기록 다름: %s %s 이전 %s · WEHAGO %s" % (
                    inv["vendor"], _day(inv["date"]), won(prev_paid), won(now_paid)))
        paid = inv["applied"] + inv["deducted"] != 0   # 지난해 수정 계산서(−)를 끝낸 것은 입금액이 − (사용자 2026-11-04)
        if not due and inv["date"] is not None and inv["total"] is not None and inv["total"] > 0 \
                and inv["applied"] + inv["deducted"] < inv["total"] and not _prior(inv):
            # F9 (2026-11-14): 입금예정일을 손으로 넣지 않은 계산서도 입금 일정·'입금일 지난 미수금'에 나오게 작성일 + 60일
            # (사용자 2026-11-12: 대부분 작성일 기준 60일 뒤 입금). 확정이 아니라 예상(N)이고 손으로 고치면 그 날짜가 이어진다
            due, firm = cell_date(inv["date"] + dt.timedelta(days=DUE_GUESS_DAYS)), "N"
            guessed.append(inv)
        parts = inv["parts"] if inv["vat"] is not None else None
        if not parts:
            rows.append({"프로젝트번호": inv["project"], "거래처": inv["vendor"], "발행일": cell_date(inv["date"]),
                         "구분": inv["kind"], "공급가액": cell_amount(inv["supply"]), "부가세": cell_amount(inv["vat"]),
                         "입금예정일": due, "예정일확정": firm, "입금일": cell_date(inv["paid_date"]) if paid else "",
                         "입금액": cell_amount(inv["applied"] + inv["deducted"]) if paid else ""})
            bases.append(inv["basis"])
            continue
        # 여러 프로젝트로 나뉜 계산서: 프로젝트마다 한 줄. 부가세·입금액은 공급가액 비율로 (합은 계산서 한 장과 같다)
        split_n += 1
        amounts = [a for _, a in parts]
        vats = _share(inv["vat"], amounts)
        gots = _share(inv["applied"] + inv["deducted"], amounts)
        for (pid, amount), v, got in zip(parts, vats, gots):
            mine_old = split_prev.get((inv["vendor_norm"], inv["date"], amount))
            d2, f2 = due, firm
            if old is None and mine_old is not None:   # 지난번에 이미 나눠 적힌 줄: 그 줄의 입금예정일을 옮긴다
                d2 = cell_date(parse_date(mine_old.get("입금예정일")))
                f2 = (mine_old.get("예정일확정") or "").strip()
                f2 = f2 if f2 in _FIRM else ""
            rows.append({"프로젝트번호": pid, "거래처": inv["vendor"], "발행일": cell_date(inv["date"]),
                         "구분": inv["kind"], "공급가액": cell_amount(amount), "부가세": cell_amount(v),
                         "입금예정일": d2, "예정일확정": f2, "입금일": cell_date(inv["paid_date"]) if paid else "",
                         "입금액": cell_amount(got) if paid else ""})
            bases.append("분개장 매출 줄" if pid else ("참고" if inv["basis"] == "참고" else "미연결"))
            split_rows += 1

    # 대조 (원본 합계 대 CSV 합계)
    csv_supply = _sum_or_none(int(r["공급가액"]) if r["공급가액"] else None for r in rows)
    csv_vat = _sum_or_none(int(r["부가세"]) if r["부가세"] else None for r in rows)
    cash = _sum_or_none([None] if jr.unknown else (r["amount"] for r in jr.receipts))
    credit_total = None if jr.unknown else jr.credit_all
    paid_csv = sum(inv["applied"] for inv in invoices)
    opening_applied = sum(o["applied"] for o in jr.opening.values())
    leftover = [r for r in jr.receipts if r["left"] > 0]
    left_sum = sum(r["left"] for r in leftover)
    credit_sum = sum(r["amount"] for r in jr.credits)
    checks = [
        Check("계산서 줄 수", len(sales["rows"]), len(rows) - (split_rows - split_n)),
        Check("공급가액 합계", _sum_or_none(r.get("supply") for r in sales["rows"]), csv_supply),
        Check("부가세 합계", _sum_or_none(r.get("vat") for r in sales["rows"]), csv_vat),
        Check("수금 (매출채권 대변 · 같은 전표 자산 계정(현금 계정·10xxx) 차변) = 입금액 합계 + 기초 미수 배분 + 미배분", cash,
              paid_csv + opening_applied + left_sum),
        Check("매출채권 대변 합계 = 입금 + 수정(계산서 감액)", credit_total,
              sum(r["amount"] for r in jr.receipts) + credit_sum),
    ]

    # 알림
    stat = collections.OrderedDict((b, [0, 0, 0]) for b in BASES)   # 건수, 공급가액 합계(아는 것), 금액 모르는 건수
    for inv in invoices:
        s = stat[inv["basis"]]
        s[0] += 1
        if inv["supply"] is None:
            s[2] += 1
        else:
            s[1] += inv["supply"]
    parts = []
    for b, (n, total, unknown) in stat.items():
        if b == "참고" and not n:
            continue
        text = "%s %d건 %s" % (b, n, "미확인" if n and n == unknown else won(total))
        parts.append(text + (" (금액 미확인 %d건)" % unknown if unknown and n != unknown else ""))
    notes.append("프로젝트 연결: " + " · ".join(parts))
    if split_n:
        notes.append("여러 프로젝트로 나뉜 계산서 %d장 → 프로젝트마다 한 줄씩 %d줄로 적음 (부가세·입금액은 공급가액 비율)" % (split_n, split_rows))
    for inv in order:
        if inv["basis"] == "미연결":
            notes.append("  미연결 계산서 %s %s %s — %s" % (_day(inv["date"]), inv["vendor"], won(inv["supply"]), inv["why"]))
    revenue_sum = None
    if revenue and not any(s["unknown"] for s in revenue["summary"].values()):
        revenue_sum = sum(s["sum"] for s in revenue["summary"].values())
    notes.append("참고 매출 계산서 공급가액 %s · 분개장 매출 %s" % (won(checks[1].source), won(revenue_sum)))
    names = dict(jr.names)
    inv_total, inv_unknown = collections.defaultdict(int), set()
    inv_applied = collections.defaultdict(int)
    for inv in invoices:
        names.setdefault(inv["vendor_norm"], inv["vendor"])
        if inv["total"] is None:
            inv_unknown.add(inv["vendor_norm"])
        else:
            inv_total[inv["vendor_norm"]] += inv["total"]
        inv_applied[inv["vendor_norm"]] += inv["applied"] + inv["deducted"]
    left_by = collections.defaultdict(int)
    for r in leftover:
        left_by[r["vn"]] += r["left"]
    credit_by = collections.defaultdict(int)
    for r in jr.credits:
        credit_by[r["vn"]] += r["amount"]
    # 계산서 기준 = 계산서.csv 가 말하는 미수 (합계 − 입금액) + 기초 미수 남음. 미배분 수금은 빼지 않는다 (CR-05: 빼면 늘 차이 0)
    book_side, sheet_side, diffs = {}, {}, []
    opening_left_all = 0
    for vn in names:
        book_side[vn] = jr.balance.get(vn, 0)
        o = jr.opening.get(vn) if jr.opening_any else None
        opening_left = (o["net"] - o["applied"]) if o and o["net"] > 0 else 0
        opening_left_all += opening_left
        if vn in inv_unknown:
            sheet_side[vn] = None
        else:
            sheet_side[vn] = inv_total[vn] - inv_applied[vn] + opening_left
    for vn in sorted(names, key=lambda k: (names[k], k)):
        c, d = book_side[vn], sheet_side[vn]
        if c is None or d is None or c != d:
            why = ["차이 %s" % (won(c - d) if c is not None and d is not None else "미확인")]
            if left_by[vn]:
                why.append("미배분 수금 %s" % won(left_by[vn]))
            if credit_by[vn]:
                why.append("수정(계산서 감액) %s" % won(credit_by[vn]))
            diffs.append("매출채권 잔액 차이 %s: 분개장 %s · 계산서 기준 %s (%s)" % (names[vn], won(c), won(d), " · ".join(why)))
    c_all, d_all = _sum_or_none(book_side.values()), _sum_or_none(sheet_side.values())
    notes.append("참고 매출채권 잔액: 분개장 %s · 계산서 기준 %s (차이 %s)" % (
        won(c_all), won(d_all), won(c_all - d_all) if c_all is not None and d_all is not None else "미확인"))
    notes.extend(diffs)
    # 분개장에 기초 줄이 없으면 기간 앞 계산서의 미수를 모른다: 미배분 수금이나 분개장 시작 전 계산서가 있으면 비교할 수 없다
    starts = [ln["date"] for ln in books.journal if ln.get("date") is not None]
    early = [inv for inv in invoices if starts and inv["date"] is not None and inv["date"] < min(starts)]
    blind = ""
    if not jr.opening_any and (leftover or early):
        parts = []
        if leftover:
            parts.append("미배분 수금 %d건 %s" % (len(leftover), won(left_sum)))
        if early:
            parts.append("분개장 시작(%s) 전 계산서 %d건" % (min(starts).isoformat(), len(early)))
        blind = "분개장에 전기이월·기초잔액 줄이 없고 %s — 기간 앞 미수의 입금인지 선입금인지 알 수 없음" % " · ".join(parts)
        notes.append("매출채권 잔액 대조 판단 불가: " + blind)
    checks.append(balance_check(c_all, rows, opening_left_all, blind))
    ded = [inv for inv in invoices if inv["deducted"]]
    if ded:
        notes.append("매출 때 바로 차감된 금액(카드 수수료 등) %d건 %s → 입금액에 포함 (분개장 매출채권은 차감 뒤 금액)"
                     % (len(ded), won(sum(inv["deducted"] for inv in ded))))
    notes.append("미배분 수금 %d건 %s" % (len(leftover), won(left_sum)))
    for r in leftover:
        notes.append("  미배분 수금 %s %s %s (전표 %s)" % (_day(r["date"]), r["vendor"], won(r["left"]), r["no"]))
    fifo = [r for r in jr.receipts if r["fifo"]]
    if fifo:
        notes.append("오래된 것부터(기초 미수 → 계산서) 배분한 입금 %d건 %s (금액이 계산서 하나와 같지 않은 입금: 분할·합산·수수료 차감 등)"
                     % (len(fifo), won(sum(r["amount"] for r in fifo))))
    part = [inv for inv in order if inv["total"] is not None and 0 < inv["applied"] < inv["total"] - inv["deducted"]]
    if part:
        notes.append("부분 입금 계산서 %d건 남은 금액 %s (수수료 차감 등도 자동으로 지우지 않음 — 미수로 둠)"
                     % (len(part), won(sum(inv["total"] - inv["deducted"] - inv["applied"] for inv in part))))
    for inv in part:
        notes.append("  부분 입금 %s %s 합계 %s · 입금 %s · 남음 %s" % (
            _day(inv["date"]), inv["vendor"], won(inv["total"]), won(inv["applied"]), won(inv["total"] - inv["deducted"] - inv["applied"])))
    if jr.credits:
        notes.append("수정(계산서 감액) %d건 %s" % (len(jr.credits), won(credit_sum)))
    for r in jr.credits:
        twin = [inv for inv in order if inv["kind"] == "수정" and inv["vendor_norm"] == r["vn"] and inv["total"] == -r["amount"]]
        notes.append("  수정(계산서 감액) %s %s %s (전표 %s%s)" % (
            _day(r["date"]), r["vendor"], won(r["amount"]), r["no"],
            " · 같은 금액의 수정 계산서 %s 있음" % _day(twin[0]["date"]) if twin else ""))
    undated = sum(1 for inv in invoices if inv["date"] is None)
    if undated:
        notes.append("발행일 없는 계산서 %d건 (입금과 짝짓지 않음)" % undated)
    if skip_fifo:
        notes.append("합계를 모르는 계산서가 있는 거래처는 오래된 것부터 배분하지 않음: " + ", ".join(
            sorted(names.get(vn, vn) for vn in skip_fifo)))
    differ = sum(1 for inv in invoices if inv["total"] is not None and inv["source_total"] is not None
                 and inv["total"] != inv["source_total"])
    if differ:
        notes.append("합계가 공급가액+부가세와 다른 계산서 %d건 (공급가액+부가세로 처리)" % differ)
    notes.extend(carry_notes)
    if guessed:
        notes.append("입금예정일 빈칸 계산서 %d건 %s → 작성일 + %d일로 채움 (예상, 확정 아님). 실제 날짜를 알면 계산서.csv 입금예정일을 고치세요"
                     % (len(guessed), won(sum(v["total"] - v["applied"] - v["deducted"] for v in guessed)), DUE_GUESS_DAYS))
    notes.extend(mismatch)
    if not_carried:
        notes.append("이전 계산서.csv 줄 %d건 옮기지 않음 (매출 계산서 엑셀로 다시 만듦)" % not_carried)
    return Table("계산서.csv", columns, rows, checks, notes, extra={"basis": bases})
