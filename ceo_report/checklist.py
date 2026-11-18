"""'확인할 것' 화면 (사용자 2026-11-05: 확인이 필요한 것을 따로 화면으로, 건마다 화면에서 보고 결정을 입력).

모으는 것
  · 변환 때 만든 것 (입력\\확인할것.json): 중복 의심 전표, 변환 대조 불일치, 카드 전표 입력 전
  · 화면을 열 때 계산하는 것: 미지급금 지급 예정 > 장부 잔액, 같은 거래처·같은 달 두 출처 출금, 통장 잔액 ↔ 장부 보통예금,
    다음 7일 이체할 거래처 중 계좌 없는 곳, 마지막 정합성 점검에서 바뀐 숫자·확인 필요, 보고서 입력 확인 필요
결정은 입력\\확인결정.csv 에 쌓인다 (항목ID·결정·메모·결정일). 같은 항목이 다음 변환에 또 나오면 결정이 그대로 붙는다.
'고칠 것' 결정은 자료에서 사라질 때까지 '고치기 기다림'으로 남고, 그 밖의 결정은 '결정함'으로 접어 둔다.
화면은 이 컴퓨터 안(127.0.0.1)에서만 열리고, 실행마다 바뀌는 열쇠가 있어야 저장된다.
"""
import csv
import datetime as dt
import hashlib
import html
import io
import json
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import util
from .util import open_text as _open_text  # UTF-8·CP949 모두 읽음 (C5)

CONVERT_FILE = "확인할것.json"
STORE = "확인결정.csv"
STORE_COLS = ["항목ID", "결정", "메모", "결정일", "내용", "금액"]   # 금액: 결정할 때의 차이 금액 (편의성 20)
BANK_FILE = "통장잔액.csv"
BANK_COLS = ["날짜", "통장잔액", "메모"]
FIX_WORDS = ("고칠 것", "넣을 것", "지울 것", "발급할 것", "확인 필요")   # 표에 없는 예전 결정 글에만 쓴다
# 편의성 19 (2026-11-16): 선택지마다 '고치기 기다림(fix) / 결정함(done)'을 정해 둔다. 예전엔 선택지 글에 '고칠 것' 같은 낱말이
# 있는지로 정해, '명세서 오면 확정 금액 넣음'·'통장 잔액 잘못 넣음'처럼 할 일이 남은 선택이 '결정함'으로 숨었다.
# 새 선택지를 만들면 여기에 넣는다 (시험이 코드의 모든 선택지가 표에 있는지 본다).
CHOICE_STATE = {
    "원인 앎 — 그대로 둠": "done", "고칠 것": "fix",
    "명세서 오면 확정 금액 넣음": "fix", "확인함": "done",
    "전표 고침": "done", "차이 원인 확인함": "done", "다시 받음·고침": "done",
    "장부 반영 전 거래 있음": "done", "위하고에서 고칠 것": "fix", "통장 잔액 잘못 넣음": "fix",
    "두 번 적힘 — 자금계획서에서 지울 것 (프로그램 판단)": "fix", "예정이 맞음 (장부 반영 전)": "done",
    "장부가 맞음 — 자금계획서 고칠 것": "fix", "두 번 적힘 — 자금계획서에서 지울 것": "fix",
    "같은 돈 — 한 곳에서 지울 것": "fix", "다른 돈 (둘 다 나감)": "done",
    "계좌 넣음": "done", "이번엔 은행에서 직접 이체": "done",
    "그대로 둠 (괜찮음)": "done", "이유 앎 — 괜찮음": "done", "확인 필요": "fix",
    "이중 입력 — 위하고에서 고칠 것": "fix", "정상 (별개 거래)": "done",
    "위하고에 넣을 것": "fix", "장부에 다른 날짜·금액으로 있음": "done", "취소·수정된 계산서": "done",
    "카드·현금 매출이라 정상": "done", "발급 누락 — 계산서 발급할 것": "fix", "장부 잘못 — 고칠 것": "fix",
    "처리함": "done", "진행 중 — 확인 필요": "fix", "안 해도 됨 (이유를 메모에)": "done",
    "일부러 둠 (리저브 등)": "done", "원가 없는 게 맞음": "done",   # 전표 프로젝트 번호 (2026-11-16)
    "인트라넷 자료에서 고칠 것": "fix", "같은 행사 — 그대로 둠": "done",   # 예전 인트라넷 빠진 프로젝트 (2026-11-17)
}
TODO_KIND = "보고 할 일"          # 경영관리 보고에서 넘어온 할 일 — '할 일 기록'으로 따로 센다 (운영-04, 결정 카드 ③)
TRACK_AMOUNT = ("자료 대조",)     # 항목 이름에 금액이 없는 종류: 결정할 때 금액을 같이 적고 달라지면 다시 묻는다 (편의성 20)


def choice_state(choice):
    """결정 글 -> 'open'(결정 없음) · 'fix'(고치기 기다림) · 'done'(결정함)."""
    ch = (choice or "").strip()
    if not ch:
        return "open"
    if ch in CHOICE_STATE:
        return CHOICE_STATE[ch]
    return "fix" if any(w in ch for w in FIX_WORDS) else "done"


def _amount_changed(it, dec):
    """편의성 20: 금액을 따라가는 종류에서 결정 때 금액과 지금 금액이 다르면 다시 물을 글, 아니면 ''."""
    if it.get("kind") not in TRACK_AMOUNT or not dec or not dec.get("결정"):
        return ""
    head = "전에 결정함 (%s %s)" % (dec.get("결정일") or "", dec.get("결정") or "")
    old = (dec.get("금액") or "").strip()
    if not old:
        return head + " — 그때 금액을 적어 두지 않아 다시 확인합니다"
    now = "" if it.get("amount") is None else str(int(it["amount"]))
    if old == now:
        return ""
    return head + " — 금액 바뀜: %s원 → %s원" % (won(int(old)) if old.lstrip("-").isdigit() else old, won(it.get("amount")))


def apply_decisions(items, dec):
    """항목마다 결정을 붙이고 상태를 정한다 -> counts.
    counts: open·fix·done = '보고 전에 볼 것'(자료 점검), todo·todo_fix·todo_done = '할 일 기록'(보고 할 일)."""
    counts = dict((k, 0) for k in ("open", "fix", "done", "todo", "todo_fix", "todo_done"))
    for it in items:
        d = dec.get(it["id"])
        it["decision"] = d
        it["changed"] = _amount_changed(it, d)
        it["state"] = "open" if it["changed"] else choice_state((d or {}).get("결정", ""))
        if it.get("kind") == TODO_KIND:
            counts[{"open": "todo", "fix": "todo_fix", "done": "todo_done"}[it["state"]]] += 1
        else:
            counts[it["state"]] += 1
    return counts


def drop_same_cause(items):
    """같은 원인이 두 묶음에 나오면 한 건으로 (편의성 17): 장부 읽기 알림은 '변환 알림'에 있으면 '입력 자료' 쪽을 뺀다."""
    told = set(re.sub(r"\s+", " ", str(it.get("detail") or "")).strip() for it in items if it.get("kind") == "변환 알림")
    return [it for it in items
            if not (it.get("same_as") and re.sub(r"\s+", " ", str(it["same_as"])).strip() in told)]


def window_count(G):
    """창 2단계 '확인할 것' 칸 -> (큰 글자, 옆 글). 큰 글자는 '보고 전에 볼 것'만 센다 (운영-04)."""
    c = G["counts"]
    text = "보고 전에 볼 것"
    if c["fix"]:
        text += " · 고치기 기다림 %d건" % c["fix"]
    if c["todo"] or c["todo_fix"]:
        text += " · 할 일 기록 %d건" % (c["todo"] + c["todo_fix"])
    return "%d건" % c["open"], text
ORDER = ("중복 의심 전표", "미지급금 예정 > 장부", "두 출처 출금", "통장 잔액 대조", "자료 대조", "홈택스 대조", "계좌 없는 이체 거래처",
         "신고 기한", "변환 대조", "전표 프로젝트 번호", "카드 전표", "정합성 점검", "입력 자료")


def _h(text):
    return hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:12]


def won(v):
    return "-" if v is None else "{:,}".format(int(v))


# ───────────── 변환 때 만드는 항목 ─────────────
def vendor_label(name, code):
    """거래처명 [코드] (사용자 2026-11-05: 코드만으로는 모르니 둘 다). 하나만 있으면 있는 것만."""
    name, code = (name or "").strip(), str(code or "").strip()
    if name and code and code not in name:
        return "%s [%s]" % (name, code)
    return name or ("[%s]" % code if code else "")


def convert_items(tables, cross, notes):
    """변환 대조 불일치 · 카드 전표 입력 전 알림 -> 항목."""
    from .convert import check_result
    out = []
    checks = [c for t in tables if t.written for c in t.checks] + list(cross)
    for c in checks:
        if check_result(c) != "불일치":
            continue
        out.append({"id": "대조|%s|%s|%s" % (c.label, c.source, c.csv), "kind": "변환 대조", "date": "", "amount": None,
                    "vendor": "", "title": "변환 대조 불일치: %s" % c.label,
                    "detail": "원본 %s · 변환 결과 %s (차이 %s)" % (won(c.source), won(c.csv), won((c.csv or 0) - (c.source or 0))),
                    "choices": ["원인 앎 — 그대로 둠", "고칠 것"]})
    for n in notes:
        n = str(n)
        if n.startswith("[확인] 카드 전표 입력 전"):
            out.append({"id": "카드|%s" % _h(n), "kind": "카드 전표", "date": "", "amount": None, "vendor": "",
                        "title": "카드 전표를 아직 넣지 않은 달이 있음 (빠진 카드는 최근 3달 평균으로 예상)",
                        "detail": n.replace("[확인] ", ""), "choices": ["명세서 오면 확정 금액 넣음", "확인함"]})
        if n.startswith("[확인] 카드 장부 끝전"):   # 결정 카드 2026-11-17
            out.append({"id": "카드끝전|%s" % _h(n), "kind": "카드 전표", "date": "", "amount": None, "vendor": "",
                        "title": "카드별로 장부에 오래 남은 끝전이 있음 (출금에는 안 넣음)",
                        "detail": n.replace("[확인] ", ""), "choices": ["전표 고침", "확인함"]})
        if n.startswith("[확인] 원천세 장부·위하고") or n.startswith("[확인] 4대보험 직원분 장부·위하고"):   # 제안 3 (2026-11-14)
            out.append({"id": "원천대조|%s" % _h(n), "kind": "세금 대조", "date": "", "amount": None, "vendor": "",
                        "title": "장부 %s가 위하고 화면과 다름" % ("원천세" if "원천세" in n[:12] else "4대보험 직원분"),
                        "detail": n.replace("[확인] ", ""), "choices": ["전표 고침", "차이 원인 확인함"]})
        if n.startswith("[확인] 지급요청 짝짓기"):   # 계산-01·계산-15 (2026-11-15): 후보가 둘 이상이면 확인할 것에
            out.append({"id": "요청짝|%s" % _h(n), "kind": "변환 대조", "date": "", "amount": None, "vendor": "",
                        "title": "지급요청을 장부 원가 줄과 짝지을 때 후보가 둘 이상이던 요청이 있음 (합계는 같음)",
                        "detail": n.replace("[확인] ", ""), "choices": ["확인함", "고칠 것"]})
        if n.startswith("[확인] 통장 줄만 있는 전표"):   # 2026-11-14: 적요 대신 계정으로 판단하려면 상대 계정 줄이 필요
            out.append({"id": "통장만|%s" % _h(n), "kind": "전표 입력", "date": "", "amount": None, "vendor": "",
                        "title": "통장 줄만 있는 전표가 있음 (상대 계정 줄을 넣어 주세요)",
                        "detail": n.replace("[확인] ", ""), "choices": ["전표 고침", "확인함"]})
        elif n.startswith("[확인] ") and not n.startswith(_HANDLED):
            # 2차 P2-15 (2026-11-15): 그 밖의 [확인] 알림(장부 빈 기간·다른 회사 장부·깨진 위하고 원본 등)도 확인할 것에
            body = n.replace("[확인] ", "", 1)
            out.append({"id": "변환알림|%s" % _h(n), "kind": "변환 알림", "date": "", "amount": None, "vendor": "",
                        "title": body.split(" — ")[0], "detail": body, "choices": ["다시 받음·고침", "확인함"]})
    return out


_HANDLED = ("[확인] 카드 전표 입력 전", "[확인] 원천세 장부·위하고", "[확인] 4대보험 직원분 장부·위하고", "[확인] 지급요청 짝짓기",
            "[확인] 통장 줄만 있는 전표", "[확인] 카드 장부 끝전")


def save_convert_items(input_dir, items, now=None, trace=None):
    """trace: 거래처코드별 미지급금 장부 풀이 글 (review_checks.payable_trace 의 text, 보고 때 '미지급금 예정 > 장부' 판단에 씀).
    -> 썼는가."""
    when = now or dt.datetime.now()
    # "_시작": 변환을 시작한 시각(초) — 2차 P5-12: 이것보다 뒤에 받은 자료는 이번 변환에 없을 수 있으니 '새 자료'로 본다
    data = {"_시각": when.strftime("%Y-%m-%d %H:%M"), "_시작": when.strftime("%Y-%m-%d %H:%M:%S"), "items": items, "trace": trace or {}}
    path = os.path.join(input_dir, CONVERT_FILE)
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, default=str)
        os.replace(path + ".tmp", path)
        return True
    except OSError:   # 2차 P2-14: 실패를 알리게 돌려준다 (변환이 알림)
        return False


def _load_trace(input_dir):
    try:
        with open(os.path.join(input_dir, CONVERT_FILE), encoding="utf-8") as f:
            return json.load(f).get("trace") or {}
    except (OSError, ValueError, AttributeError):
        return {}


def _load_convert_items(input_dir):
    try:
        with open(os.path.join(input_dir, CONVERT_FILE), encoding="utf-8") as f:
            data = json.load(f)
        return data.get("items") or [], data.get("_시각") or ""
    except (OSError, ValueError):
        return [], ""


# ───────────── 결정 저장 ─────────────
def read_decisions(input_dir):
    """-> {항목ID: {결정, 메모, 결정일, 내용}} (같은 ID 는 마지막 줄)."""
    path = os.path.join(input_dir, STORE)
    out = {}
    if not os.path.exists(path):
        return out
    try:
        with _open_text(path) as f:
            for r in csv.DictReader(f):
                if r.get("항목ID"):
                    out[r["항목ID"]] = r
    except (OSError, UnicodeDecodeError, csv.Error):
        pass
    return out


_DECISION_LOCK = threading.Lock()   # 2차 C22·P3-5 (2026-11-15): 거의 동시에 두 번 저장하면 먼저 한 결정이 사라졌다


def save_decision(input_dir, item_id, choice, memo="", content="", amount=None):
    """결정 한 줄을 넣거나 고친다. choice 를 비우면 결정을 지운다 (다시 '결정할 것'으로).
    읽고-고치고-쓰기를 한 번에 하나씩 (확인할 것 화면은 요청마다 따로 돈다).
    amount: 결정할 때의 차이 금액 (편의성 20 — 달라지면 다시 묻는다)."""
    if not item_id:
        raise ValueError("항목이 없음")
    with _DECISION_LOCK:
        return _save_decision(input_dir, item_id, choice, memo, content, amount)


def _save_decision(input_dir, item_id, choice, memo, content, amount=None):
    from .util import guard_save
    guard_save(os.path.join(input_dir, STORE))   # 못 읽은 파일을 새 줄만으로 덮지 않음 (C5)
    cur = read_decisions(input_dir)
    if choice:
        cur[item_id] = {"항목ID": item_id, "결정": choice.strip(), "메모": (memo or "").strip()[:500],
                        "결정일": dt.date.today().isoformat(), "내용": (content or "")[:300],
                        "금액": "" if amount is None else str(int(amount))}
    else:
        cur.pop(item_id, None)
    path = os.path.join(input_dir, STORE)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(STORE_COLS)
    for r in cur.values():
        w.writerow([r.get(c, "") for c in STORE_COLS])
    with open(path + ".tmp", "w", encoding="utf-8-sig", newline="") as f:
        f.write(buf.getvalue())
    os.replace(path + ".tmp", path)
    return cur.get(item_id)


# ───────────── 통장 잔액 (편의 기능 4) ─────────────
def save_bank(input_dir, day, amount, memo=""):
    """입력\\통장잔액.csv 에 그날 통장 잔액 합계를 넣거나 고친다 -> (날짜, 금액)."""
    d = util.date(str(day or "").strip())
    if d is None:
        raise ValueError("날짜 형식 오류 (예: 2026-11-06)")
    t = str(amount or "").replace(",", "").replace("원", "").strip()
    if not t.lstrip("-").isdigit():
        raise ValueError("통장 잔액은 숫자 (예: 364,912,852)")
    from .util import guard_save
    guard_save(os.path.join(input_dir, BANK_FILE))   # 못 읽은 파일을 새 줄만으로 덮지 않음 (C5)
    rows = read_bank(input_dir)
    rows[d] = (int(t), (memo or "").strip())
    path = os.path.join(input_dir, BANK_FILE)
    with open(path + ".tmp", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(BANK_COLS)
        for k in sorted(rows):
            w.writerow([k.isoformat(), rows[k][0], rows[k][1]])
    os.replace(path + ".tmp", path)
    return d, int(t)


def read_bank(input_dir):
    out = {}
    path = os.path.join(input_dir, BANK_FILE)
    if not os.path.exists(path):
        return out
    try:
        with _open_text(path) as f:
            for r in csv.DictReader(f):
                d = util.date((r.get("날짜") or "").strip())
                v = util.num(r.get("통장잔액"))
                if d is not None and v is not None:
                    out[d] = (int(v), r.get("메모") or "")
    except (OSError, UnicodeDecodeError, csv.Error):
        pass
    return out


def book_balance(input_dir, day):
    """장부 보통예금 잔액 합계 (그날 끝). 장부잔액.csv 의 그날 이전 가장 가까운 날 + 장부입출금.csv 그 뒤 입출금.
    -> (금액 또는 None, 장부 마지막 날)."""
    bal_path, mov_path = os.path.join(input_dir, "장부잔액.csv"), os.path.join(input_dir, "장부입출금.csv")
    snaps = {}
    try:
        with _open_text(bal_path) as f:
            for r in csv.DictReader(f):
                d, v = util.date(r.get("기준일")), util.num(r.get("잔액"))
                if d is not None and v is not None:
                    snaps.setdefault(d, 0)
                    snaps[d] += int(v)
    except (OSError, UnicodeDecodeError, csv.Error):
        return None, None
    moves = []
    try:
        with _open_text(mov_path) as f:
            for r in csv.DictReader(f):
                d, v = util.date(r.get("일자")), util.num(r.get("금액"))
                if d is not None and v is not None:
                    moves.append((d, int(v) if (r.get("입출금") or "").strip() == "입금" else -int(v)))
    except (OSError, UnicodeDecodeError, csv.Error):
        pass
    last = max(list(snaps) + [m[0] for m in moves]) if (snaps or moves) else None
    base_days = [d for d in snaps if d <= day]
    if base_days:
        b = max(base_days)
        return snaps[b] + sum(v for d, v in moves if b < d <= day), last
    if moves:
        return sum(v for d, v in moves if d <= day), last
    return None, last


def bank_items(input_dir):
    out = []
    for day, (amt, memo) in sorted(read_bank(input_dir).items()):
        book, last = book_balance(input_dir, day)
        if book is None or last is None or day > last:
            continue   # 장부가 아직 그날까지 오지 않음 → 다음 변환 뒤에 본다
        diff = amt - book
        if diff == 0:
            continue
        out.append({"id": "통장|%s|%s|%s" % (day.isoformat(), amt, book), "kind": "통장 잔액 대조", "date": day.isoformat(),
                    "amount": diff, "vendor": "", "title": "통장 잔액과 장부 보통예금 잔액이 다름",
                    "detail": "통장 %s원 · 장부 %s원 · 차이 %s원%s" % (won(amt), won(book), won(diff), (" · 메모: " + memo) if memo else ""),
                    "choices": ["장부 반영 전 거래 있음", "위하고에서 고칠 것", "통장 잔액 잘못 넣음"]})
    return out


def bank_line(input_dir, day):
    """창에 보일 한 줄: 그날 통장과 장부 비교."""
    rows = read_bank(input_dir)
    if day not in rows:
        return ""
    book, last = book_balance(input_dir, day)
    if book is None or last is None or day > last:
        return "장부가 %s까지라 아직 비교 못함 — 다음 '자료 변환' 뒤 확인할 것 화면에서 봅니다" % (last.isoformat() if last else "없음")
    diff = rows[day][0] - book
    return "장부 보통예금 %s원 · %s" % (won(book), "일치" if diff == 0 else "차이 %s원 — 확인할 것 화면에 올림" % won(diff))


# ───────────── 화면을 열 때 계산하는 항목 ─────────────
def _report_items(input_dir, asof):
    from .calc import compute
    from .data import load
    from . import transfer
    out = []
    try:
        d = load(input_dir)
        R = compute(d, "weekly", asof)
    except Exception as e:   # 화면은 열리게
        return [{"id": "오류|계산", "kind": "입력 자료", "date": "", "amount": None, "vendor": "",
                 "title": "보고서 계산을 하지 못해 일부 항목을 못 모음", "detail": type(e).__name__, "choices": ["확인함"]}]
    from .data import BOOK_NOTE_FILE
    from .wehago import norm_code, norm_vendor
    trace = _load_trace(input_dir)
    for r in (R.get("debts") or {}).get("over", []):
        plans = [ev for ev in R["events"] if ev["io"] == "out" and "미지급금" in str(ev.get("cat") or "")
                 and ((r["vcode"] and norm_code(ev.get("vendor_code")) == norm_code(r["vcode"]))
                      or (not r["vcode"] and norm_vendor(ev.get("desc") or "") == norm_vendor(r["vendor"])))]
        same = [ev for ev in plans if r["balance"] and ev["amount"] == r["balance"]]
        why = ""
        if len(same) > 1:
            why = " · 자금계획서에 장부 잔액과 같은 금액이 %d번 (예정일 %s) → 한 번은 중복으로 적혔을 가능성 높음" % (
                len(same), ", ".join(ev["date"].isoformat() for ev in same if ev["date"]))
        elif plans:
            why = " · 자금계획서 예정 %d줄 (예정일 %s)" % (len(plans), ", ".join(ev["date"].isoformat() for ev in plans if ev["date"]))
        tr = trace.get(norm_code(r["vcode"]) or "", "") if r["vcode"] else ""
        if tr:
            why += " · " + tr
        r = dict(r, why=why)
        out.append({"id": "미지급금예정|%s|%s|%s" % (r["vcode"] or r["vendor"], r["scheduled"], r["balance"]),
                    "kind": "미지급금 예정 > 장부", "date": "", "amount": r["over"], "vendor": r["vendor"], "vcode": r["vcode"],
                    "title": "미지급금 지급 예정이 장부 잔액보다 큼%s" % (" (정확히 2배)" if r["balance"] and r["scheduled"] == 2 * r["balance"] else ""),
                    "detail": "지급 예정(자금계획서) %s원 · 장부 미지급금 %s원 · 더 큰 금액 %s원%s%s" % (
                        won(r["scheduled"]), won(r["balance"]), won(r["over"]), "",
                        r["why"]),
                    "choices": (["두 번 적힘 — 자금계획서에서 지울 것 (프로그램 판단)", "예정이 맞음 (장부 반영 전)", "장부가 맞음 — 자금계획서 고칠 것"]
                                if len(same) > 1 else
                                ["예정이 맞음 (장부 반영 전)", "장부가 맞음 — 자금계획서 고칠 것", "두 번 적힘 — 자금계획서에서 지울 것"])})
    for g in R.get("two_source") or []:
        out.append({"id": "두출처|%s|%s|%s" % (g["vendor"], g["month"], sum(g["sources"].values())), "kind": "두 출처 출금",
                    "date": g["month"], "amount": sum(g["sources"].values()), "vendor": g["vendor"], "vcode": g.get("vcode") or "",
                    "title": "같은 거래처·같은 달 출금이 두 곳에 적힘 (같은 돈이면 두 번 빠짐)",
                    "detail": " · ".join("%s %s원" % (k, won(v)) for k, v in g["sources"].items()),
                    "choices": ["같은 돈 — 한 곳에서 지울 것", "다른 돈 (둘 다 나감)"]})
    try:
        accounts, _ = transfer.read_accounts(input_dir)
        miss = transfer.missing_accounts(R["events"], accounts, asof + dt.timedelta(days=1), asof + dt.timedelta(days=7))
        if miss:   # 한 건으로 묶는다: 계좌는 창 ⑦ 또는 이체 파일 만들 때 뜨는 창에서 넣는다
            out.append({"id": "계좌|%s" % _h(",".join(sorted(m["code"] or m["vendor"] for m in miss))), "kind": "계좌 없는 이체 거래처",
                        "date": "", "amount": sum(m["amount"] for m in miss), "vendor": "",
                        "title": "다음 7일 지급할 거래처 %d곳에 계좌가 없음 (이체 파일에 못 넣음)" % len(miss),
                        "detail": " · ".join("%s %s원" % (vendor_label(m["vendor"], m["code"]), won(m["amount"])) for m in miss)
                                  + " — 4단계 ‘보내기’의 ‘이체 파일 만들기’를 누르면 뜨는 창에서 바로 넣을 수 있음",
                        "choices": ["계좌 넣음", "이번엔 은행에서 직접 이체"]})
    except Exception:
        pass
    import re
    groups = {}
    for f, line, msg in R["s7"]["issues"]:
        msg = util.mask_rrn(str(msg))
        vals = re.findall(r"'([^']*)'", msg)
        if "기본값" in msg and "비어 있음" in msg:
            continue   # 설정을 비워 기본값을 쓰는 것은 결정할 일이 아님 (보고서 7번에는 그대로 있음)
        key = (f, re.sub(r"'[^']*'", "'…'", msg))   # 같은 종류 알림(번호만 다름)은 한 건으로
        g = groups.setdefault(key, {"lines": [], "vals": [], "first": msg})
        g["lines"].append(str(line))
        g["vals"].extend(v for v in vals if v not in g["vals"])
    for (f, msg), g in groups.items():
        lines, vals = g["lines"], g["vals"]
        if len(vals) <= 1:
            msg = g["first"]
        detail = "줄 %s%s" % (", ".join(lines[:12]), " 외 %d줄" % (len(lines) - 12) if len(lines) > 12 else "")
        if len(vals) > 1:
            detail = "%d개: %s%s · %s" % (len(vals), ", ".join(vals[:20]), " …" if len(vals) > 20 else "", detail)
        # 편의성 17 (2026-11-16): 제목을 120자에서 자르지 않는다 — 제목은 첫 마디, 나머지 글은 아래 설명에 모두
        head = msg.split(" — ")[0]
        out.append({"id": "입력|%s|%s|%s" % (f, _h(msg), _h(",".join(sorted(vals)))), "kind": "입력 자료", "date": "", "amount": None,
                    "vendor": "", "title": "%s: %s%s" % (f, head, " (%d건)" % len(lines) if len(lines) > 1 else ""),
                    "detail": (msg[len(head):].lstrip(" —") + " · " if len(msg) > len(head) else "") + detail,
                    "same_as": g["first"] if f == BOOK_NOTE_FILE else "", "choices": ["고칠 것", "그대로 둠 (괜찮음)"]})
    return out


def _integrity_warn(s):
    """정합성 점검 줄이 결정할 경고인가. 2차 P3-12 (2026-11-15): 예전엔 줄 어디에든 '0건'·'0개'가 있으면 버려
    '확인 필요 10건'·'차변≠대변 3개 확인 필요, 금액 빈 줄 0개' 같은 실제 경고도 사라졌다. 이제 '확인 필요·불일치' 바로 뒤 건수만 본다."""
    if "← 바뀜" in s:
        return True
    if "확인 필요" not in s and "불일치" not in s:
        return False
    m = re.search(r"(?:확인 필요|불일치)\s*:?\s*([\d,]+)\s*(?:건|개)", s)
    if m:
        return int(m.group(1).replace(",", "")) > 0
    return not re.search(r"(?:확인 필요|불일치)\s*(?:없음|0(?![\d,]))", s)


def _integrity_items(app_dir):
    path = os.path.join(app_dir, "정합성점검.txt")
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read().splitlines()
        when = dt.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return out
    for ln in text:
        s = ln.strip().lstrip("-·").strip()
        if _integrity_warn(s):
            out.append({"id": "정합성|%s" % _h(s), "kind": "정합성 점검", "date": when[:10], "amount": None, "vendor": "",
                        "title": "정합성 점검 (%s): %s" % (when, s[:140]), "detail": s,
                        "choices": ["이유 앎 — 괜찮음", "확인 필요"]})
    return out


def gather(app_dir, input_dir, asof):
    """-> {'items': [항목 + decision], 'convert_at': 변환 시각, 'counts': {...}}."""
    conv, when = _load_convert_items(input_dir)
    items = conv + _report_items(input_dir, asof) + bank_items(input_dir) + _integrity_items(app_dir)
    from . import reconcile   # 자료 대조 '다름' 줄 (사용자 2026-11-14)
    items += reconcile.check_items(input_dir)
    try:   # 2차 전수조사 J16: 기한이 지났는데 했는지 모르는 신고 — '처리함'을 고르면 지금 현황·신고 일정에서 '했음'
        from . import filing
        items += filing.check_items(input_dir)
    except Exception:
        pass
    try:   # 경영관리 보고 할 일 (사용자 2026-11-14 주제별 묶기): 결정·메모가 다음 보고 할 일 표에 붙는다
        from . import mgmt_topics
        items += mgmt_topics.check_items(os.path.join(app_dir, "출력"))
    except Exception:
        pass
    seen, uniq = set(), []
    for it in drop_same_cause(items):
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        uniq.append(it)
    counts = apply_decisions(uniq, read_decisions(input_dir))
    rank = {k: i for i, k in enumerate(ORDER)}
    uniq.sort(key=lambda it: (it["kind"] == TODO_KIND, rank.get(it["kind"], 99), -(abs(it["amount"] or 0)), it["date"] or ""))
    return {"items": uniq, "convert_at": when, "counts": counts, "asof": asof}


def summary_line(G):
    c = G["counts"]
    return ("확인할 것: 보고 전에 볼 것 %d건 · 고치기 기다림 %d건 · 결정함 %d건 / 할 일 기록 %d건"
            % (c["open"], c["fix"], c["done"], c["todo"] + c["todo_fix"]))


# ───────────── 화면 ─────────────
# 2026-11-17 보는 사람 기준 디자인 (사용자가 고른 시안): 어두운 머리 + 진행 줄, 왼쪽 상태·종류 고르기, 건마다 흰 칸, 아래 고정 줄
CSS = """
*{box-sizing:border-box}body{margin:0;font:14px/1.5 'IBM Plex Sans KR','Noto Sans KR','Malgun Gothic','Apple SD Gothic Neo',sans-serif;color:#141B26;background:#F5F3EF}
header{position:sticky;top:0;z-index:5;background:#0F1B2D;color:#fff;padding:14px max(20px,calc(50vw - 562px));display:flex;gap:28px;align-items:center;flex-wrap:wrap}
header .ttl small{display:block;font-size:12px;color:#9FB0C6}header h1{font-size:24px;margin:0;line-height:1.3}
header .pg{flex:1;min-width:260px;max-width:420px}header .c{display:flex;gap:6px;flex-wrap:wrap;font-size:14px;font-weight:700}
header .c span+span::before{content:"· ";font-weight:400;color:#9FB0C6}header .c .sm{font-weight:400;color:#C9D4E3;font-size:12.5px}
header .bar{height:7px;border-radius:4px;background:#33435A;margin-top:7px;overflow:hidden}header .bar i{display:block;height:100%;width:0;background:#7C9BFF;border-radius:4px}
header .sp{flex:1}
header button{font:600 14px 'IBM Plex Sans KR','Malgun Gothic',sans-serif;padding:9px 16px;border:1px solid #5B6B82;border-radius:8px;background:transparent;color:#fff;cursor:pointer}
.lay{max-width:1124px;margin:0 auto;padding:22px 20px 110px;display:grid;grid-template-columns:232px minmax(0,1fr);gap:22px;align-items:start}
nav{position:sticky;top:100px;background:#fff;border-radius:14px;padding:14px 12px;box-shadow:0 1px 3px #141B2614}
nav h3{font-size:12px;font-weight:500;color:#5B6475;margin:6px 12px 4px}nav hr{border:0;border-top:1px solid #E7E4DD;margin:10px 0}
nav a{display:flex;justify-content:space-between;padding:8px 12px;border-radius:8px;cursor:pointer;font-size:14px}
nav a.on{background:#E6ECFF;color:#1F3FBF;font-weight:700}nav a b{font-weight:500}nav a.on b{font-weight:800}
nav label{display:block;font-size:12.5px;color:#3A4452;margin:8px 12px 0;cursor:pointer}nav p{font-size:12px;color:#5B6475;margin:10px 12px 2px}
main{min-width:0}.meta{color:#5B6475;font-size:12px;margin:0 0 10px}
h2{font-size:17px;margin:20px 0 8px}h2 small{font-weight:400;color:#5B6475;font-size:13px}
.it{background:#fff;border-radius:14px;padding:16px 20px;margin:10px 0;box-shadow:0 1px 3px #141B2614;border-left:5px solid transparent}
.it.fix{border-left-color:#C0392B}.it.done{opacity:.8;border-left-color:#2F7D5B}
.top{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}.top .k{font-size:11.5px;font-weight:700;background:#FFF1D6;color:#8A4B00;border-radius:10px;padding:1px 9px;white-space:nowrap}
.top .t{font-weight:700;font-size:15px;flex:1;min-width:240px}
.top .a{font-weight:800;font-size:16px;white-space:nowrap;color:#8A4B00}.v{color:#1F3FBF;font-weight:700}.d{color:#5B6475;font-size:13px;margin:4px 0 10px}
.ch{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.ch label{border:1px solid #C9CED8;border-radius:8px;padding:7px 13px;font-size:14px;cursor:pointer;background:#fff}
.ch input[type=radio]{margin:0 7px 0 0;vertical-align:-1px}.ch label.on{background:#E6ECFF;color:#1F3FBF;border-color:#2952E3;font-weight:700}
.ch input.memo{flex:1;min-width:180px;font:14px 'IBM Plex Sans KR','Malgun Gothic',sans-serif;padding:8px 10px;border:1px solid #C9CED8;border-radius:8px}
.ch button{font:13px 'IBM Plex Sans KR','Malgun Gothic',sans-serif;padding:7px 12px;border:1px solid #C9CED8;border-radius:8px;background:#fff;color:#141B26;cursor:pointer}
.ch button.clr{color:#5B6475}.st{font-size:12px;color:#2F7D5B;margin-left:4px;flex-basis:100%}.st:empty{display:none}.dec{font-size:12px;color:#5B6475;margin-top:6px}
.empty{color:#5B6475;padding:24px;text-align:center;background:#fff;border-radius:14px}
body:not(.all) .it.done{display:none}body:not(.all) .it.done.just{display:block}
body[data-f=open] .it:not(.open),body[data-f=fix] .it:not(.fix),body[data-f=done] .it:not(.done){display:none!important}
body[data-f=done] .it.done{display:block!important}
section.kd.off,.grp.off{display:none}
.grp{font-size:13px;margin:18px 0 0;color:#5B6475;font-weight:700}.grp small{font-weight:400;font-size:12px}
.chg{color:#C0392B;font-weight:700;font-size:13px;margin:2px 0}.st a{color:#1F3FBF;cursor:pointer;text-decoration:underline;margin-left:6px}
footer{position:fixed;left:0;right:0;bottom:0;z-index:6;pointer-events:none;padding:0 20px 14px}
footer div{pointer-events:auto;max-width:860px;margin:0 auto;background:#fff;border-radius:14px;box-shadow:0 6px 24px #141B2630;padding:12px 20px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
footer span{flex:1;min-width:200px;color:#3A4452}
footer button{font:700 15px 'IBM Plex Sans KR','Malgun Gothic',sans-serif;padding:12px 22px;border:0;border-radius:10px;background:#2952E3;color:#fff;cursor:pointer}
@media (max-width:820px){.lay{grid-template-columns:1fr;padding:12px 10px 120px}nav{position:static}header{padding:10px 12px;gap:10px}}
"""

JS = """
(function(){
  var KEY=%(key)s;
  document.getElementById('all').onchange=function(){document.body.classList.toggle('all',this.checked);};
  document.querySelectorAll('.ch input[type=radio]').forEach(function(r){r.onchange=function(){
    var box=r.closest('.ch'); box.querySelectorAll('label').forEach(function(l){l.classList.toggle('on',l.contains(r)&&r.checked);});
    if(r.checked) send(r.closest('.it'),r.value);};});   // 고르면 바로 저장 (메모는 '메모 저장')
  function bar(){var o=+document.getElementById('n_open').textContent,d=+document.getElementById('n_done').textContent,
    f=+document.getElementById('n_fix').textContent,t=o+d+f; document.getElementById('bar').style.width=(t?Math.round((d+f)*100/t):100)+'%%';
    ['open','fix','done'].forEach(function(k){var el=document.getElementById('s_'+k); if(el) el.textContent=document.getElementById('n_'+k).textContent;});}
  document.querySelectorAll('nav a[data-f]').forEach(function(a){a.onclick=function(){
    var on=a.classList.contains('on'); document.querySelectorAll('nav a[data-f]').forEach(function(x){x.classList.remove('on');});
    if(on){document.body.removeAttribute('data-f');}else{a.classList.add('on');document.body.setAttribute('data-f',a.dataset.f);}};});
  document.querySelectorAll('nav a[data-k]').forEach(function(a){a.onclick=function(){
    var on=a.classList.contains('on'); document.querySelectorAll('nav a[data-k]').forEach(function(x){x.classList.remove('on');});
    if(!on) a.classList.add('on');
    document.querySelectorAll('section.kd').forEach(function(s){s.classList.toggle('off',!on&&s.dataset.k!==a.dataset.k);});
    document.querySelectorAll('.grp').forEach(function(g){g.classList.toggle('off',!on);});};});
  document.getElementById('seen').onclick=function(){var b=this,x=new XMLHttpRequest(); x.open('POST','/seen?k='+KEY);
    x.onloadend=function(){document.getElementById('seenmsg').textContent='프로그램 창으로 돌아가 보고를 만드세요. 이 화면은 닫아도 됩니다.'; window.close();};
    x.send('{}');};
  bar();
  function send(it,choice){
    var memo=it.querySelector('input.memo').value, st=it.querySelector('.st');
    st.textContent='저장 중…';
    var x=new XMLHttpRequest(); x.open('POST','/decide?k='+KEY); x.setRequestHeader('Content-Type','application/json; charset=utf-8');
    x.onload=function(){var r={};try{r=JSON.parse(x.responseText);}catch(e){}
      if(x.status===200&&r.ok){
        it.className='it '+r.state; counts(r.counts);
        if(choice){st.textContent='저장함 ('+r.word+') — ';
          var u=document.createElement('a'); u.textContent='되돌리기'; u.onclick=function(){clearTimeout(it._t); it.classList.remove('just'); undo(it);};
          st.appendChild(u);
          if(r.state==='done'){it.classList.add('just'); it._t=setTimeout(function(){it.classList.remove('just');},8000);}}
        else st.textContent='결정 지움';}
      else st.textContent='저장 못함: '+(r.msg||'프로그램 창이 닫혔는지 확인');};
    x.onerror=function(){st.textContent='저장 못함: 이 화면은 닫힌 예전 화면입니다'; gone();};
    x.send(JSON.stringify({id:it.dataset.id,choice:choice,memo:memo,content:it.dataset.c}));
  }
  function counts(c){ if(!c) return;
    ['open','fix','done','todo','todo_done'].forEach(function(k){var el=document.getElementById('n_'+k); if(el) el.textContent=c[k];}); bar(); }
  function undo(it){it.querySelectorAll('input[type=radio]').forEach(function(r){r.checked=false;});
    it.querySelectorAll('label').forEach(function(l){l.classList.remove('on');}); send(it,'');}
  document.querySelectorAll('.it').forEach(function(it){
    it.querySelector('button.ok').onclick=function(){var r=it.querySelector('input[type=radio]:checked');
      if(!r){it.querySelector('.st').textContent='결정을 하나 고르세요';return;} send(it,r.value);};
    it.querySelector('button.clr').onclick=function(){undo(it);};
  });
  document.getElementById('reload').onclick=function(){location.href='/'+KEY+'?fresh=1';};
  // 편의성 21 (2026-11-17): 새 화면을 열었거나 창이 닫혔으면 이 탭에, 열어 둔 사이 새 자료가 오면 위에 알린다
  function note(html,color){var d=document.getElementById('stale-note');
    if(!d){d=document.createElement('div'); d.id='stale-note';
      d.style.cssText='position:sticky;top:0;z-index:999;padding:10px 16px;font-weight:700;border-radius:6px;margin:0 0 8px';
      document.body.insertBefore(d,document.body.firstChild);}
    d.style.background=color; d.innerHTML=html;}
  var dead=false;
  function gone(){ if(dead) return; dead=true;
    note('새 확인할 것 화면이 열렸거나 프로그램 창이 닫혔습니다 — 이 탭은 닫으세요 (여기서 고른 결정은 저장되지 않음)','#fde2e2');
    document.querySelectorAll('button.ok,button.clr').forEach(function(b){b.disabled=true;});}
  setInterval(function(){ if(dead) return;
    var x=new XMLHttpRequest(); x.open('GET','/state?k='+KEY);
    x.onload=function(){ if(x.status!==200){gone();return;}
      try{ if(JSON.parse(x.responseText).changed)
        note('새 자료가 들어왔습니다 — <a href="/'+KEY+'?fresh=1">다시 모으기</a>','#fff4d6'); }catch(e){} };
    x.onerror=gone; x.send();
  },15000);
})();
"""

STATE_WORD = {"open": "결정할 것", "fix": "고치기 기다림", "done": "결정함"}


def _shown_counts(G):
    """화면 위 숫자 칸(id='n_…')에 넣을 값."""
    c = (G or {}).get("counts") or {}
    return {"open": c.get("open", 0), "fix": c.get("fix", 0), "done": c.get("done", 0),
            "todo": c.get("todo", 0) + c.get("todo_fix", 0), "todo_done": c.get("todo_done", 0)}


def render(G, key="", mask=False):
    """확인할 것 화면 HTML. mask=True 면 거래처 이름을 가린다 (자료 밖으로 보일 미리보기용)."""
    e = html.escape
    c = G["counts"]
    h = ["<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         "<title>확인할 것</title><style>%s</style></head><body>" % CSS]
    # 운영-04 (결정 카드 ③ 2026-11-16): '보고 전에 볼 것'(자료 점검)과 '할 일 기록'(경영관리 보고 할 일)을 따로 센다.
    # 저장하면 위 숫자를 바로 다시 센다 (편의성 18: id='n_…' 를 저장 응답의 counts 로 바꿈)
    todo_n = c.get("todo", 0) + c.get("todo_fix", 0)
    h.append("<header><div class='ttl'><small>대표 보고%s</small><h1>확인할 것</h1></div>"
             "<div class='pg'><div class='c'><span>보고 전에 볼 것 <b id='n_open'>%d</b>건</span><span>결정함 <b id='n_done'>%d</b>건</span>"
             "<span class='sm'>고치기 기다림 <b id='n_fix'>%d</b></span><span class='sm'>할 일 기록 <b id='n_todo'>%d</b> · 끝냄 <b id='n_todo_done'>%d</b></span></div>"
             "<div class='bar'><i id='bar'></i></div></div><span class='sp'></span>"
             "<button id='reload'>다시 모으기</button></header><div class='lay'>"
             % (e(" · 기준일 %s" % G["asof"]) if G.get("asof") else "", c["open"], c["done"], c["fix"], todo_n, c.get("todo_done", 0)))
    kinds = []
    for it in G["items"]:
        if it["kind"] not in kinds:
            kinds.append(it["kind"])
    # 왼쪽: 상태·종류 고르기 (누르면 그것만, 다시 누르면 전체)
    nav = ["<nav><h3>상태</h3><a data-f='open'>결정할 것 <b id='s_open'>%d</b></a><a data-f='fix'>고치기 기다림 <b id='s_fix'>%d</b></a>"
           "<a data-f='done'>결정함 <b id='s_done'>%d</b></a><hr><h3>종류</h3>" % (c["open"], c["fix"], c["done"])]
    for i, k in enumerate(kinds):
        nav.append("<a data-k='%d'>%s <b>%d</b></a>" % (i, e(k), sum(1 for it in G["items"] if it["kind"] == k)))
    nav.append("<hr><label><input type='checkbox' id='all'> 결정한 것도 보기</label>"
               "<p>결정은 다음 변환 때 같은 항목에 그대로 붙습니다. '고칠 것'을 고르면 자료에서 사라질 때까지 남습니다.</p></nav>")
    h.append("".join(nav) + "<main>")
    h.append("<p class='meta'>마지막 자료 변환 %s · 결정은 입력\\%s 에 저장되어 다음 변환 뒤에도 그대로 붙습니다. "
             "할 일이 남은 결정(고칠 것·넣을 것 등)은 자료에서 풀려 사라질 때까지 빨간 줄로 남습니다. "
             "저장한 뒤 잠깐 보이는 '되돌리기'로 바로 물릴 수 있습니다.</p>" % (e(G["convert_at"] or "기록 없음"), STORE))
    if not G["items"]:
        h.append("<div class='empty'>확인할 것이 없습니다.</div>")
    shown_grp = set()
    for k in kinds:
        its = [it for it in G["items"] if it["kind"] == k]
        n_open = sum(1 for it in its if it["state"] == "open")
        grp = "todo" if k == TODO_KIND else "data"
        if grp not in shown_grp:
            shown_grp.add(grp)
            h.append("<div class='grp'>%s</div>" % ("할 일 기록 <small>경영관리 보고에서 넘어온 할 일입니다 — 보고를 막지 않고, 결정·메모는 다음 보고의 할 일 표에 붙습니다</small>"
                                                   if grp == "todo" else
                                                   "보고 전에 볼 것 <small>자료가 맞는지 보는 것입니다 — 보고를 만들기 전에 결정하세요</small>"))
        h.append("<section class='kd' data-k='%d'><h2>%s <small>%d건 · 결정할 것 %d건</small></h2>" % (kinds.index(k), e(k), len(its), n_open))
        for it in its:
            dec = it.get("decision") or {}
            vend = it.get("vendor") or ""
            if mask and vend:
                vend = vend[:1] + "○" * max(1, len(vend) - 1)
            vend = vendor_label(vend, it.get("vcode"))
            amt = "" if it.get("amount") is None else "%s원" % won(it["amount"])
            ch = []
            for i, choice in enumerate(it.get("choices") or ["확인함"]):
                on = dec.get("결정") == choice
                ch.append("<label class='%s'><input type='radio' name='r%s' value='%s'%s>%s</label>"
                          % ("on" if on else "", _h(it["id"]), e(choice, True), " checked" if on else "", e(choice)))
            h.append("<div class='it %s' data-id='%s' data-c='%s'><div class='top'><span class='k'>%s</span><span class='t'>%s</span>%s<span class='a'>%s</span></div>"
                     % (it["state"], e(it["id"], True), e("%s %s %s" % (it["title"], vend, amt), True), e(k), e(it["title"]),
                        ("<span class='v'>%s</span>" % e(vend)) if vend else "", e(amt)))
            if it.get("changed"):
                h.append("<div class='chg'>%s</div>" % e(it["changed"]))
            h.append("<div class='d'>%s%s</div>" % ((e(it["date"]) + " · ") if it.get("date") else "", e(it.get("detail") or "")))
            h.append("<div class='ch'>%s<input class='memo' placeholder='메모 (선택)' value='%s'><button class='ok'>메모 저장</button>"
                     "<button class='clr'>결정 지우기</button><span class='st'></span></div>" % ("".join(ch), e(dec.get("메모", ""), True)))
            if dec:
                h.append("<div class='dec'>%s 결정: %s%s</div>" % (e(dec.get("결정일", "")), e(dec.get("결정", "")),
                                                                ("  · 메모: " + e(dec["메모"])) if dec.get("메모") else ""))
            h.append("</div>")
        h.append("</section>")
    h.append("</main></div><footer><div><span id='seenmsg'>고른 결정은 바로 저장됩니다. 이 화면은 이 컴퓨터 안에서만 열립니다.</span>"
             "<button id='seen'>다 봤음 · 보고 만들러 가기 →</button></div></footer>"
             "<script>%s</script></body></html>" % (JS % {"key": json.dumps(key)}))
    return "".join(h)


def _sources_sig(app_dir, input_dir):
    """확인할 것을 모으는 자료 파일들의 (이름·바뀐 시각·크기) — 결정 파일은 뺀다 (이 화면이 쓰므로).
    2차 P3-11 (2026-11-15): 열어 둔 화면은 새 변환 뒤에도 옛 항목을 보였다 → 자료가 바뀌었으면 일반 새로고침에도 다시 모은다."""
    import stat as _st
    sig = []
    for folder in (input_dir, os.path.join(app_dir, "출력"), app_dir):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for n in names:
            if n == STORE or n.endswith(".tmp"):
                continue
            try:
                st = os.stat(os.path.join(folder, n))
            except OSError:
                continue
            if _st.S_ISREG(st.st_mode):
                sig.append((folder, n, st.st_mtime_ns, st.st_size))
    return tuple(sig)


class Session(object):
    """확인할 것 화면 한 번. start() -> 주소. 결정을 저장할 때마다 on_saved(글)."""

    def __init__(self, app_dir, input_dir, asof, on_saved=None, on_counts=None, on_seen=None):
        self.app_dir, self.input_dir, self.asof = app_dir, input_dir, asof
        self.on_saved = on_saved or (lambda text: None)
        self.on_counts = on_counts or (lambda counts: None)   # 편의성 18: 저장할 때마다 새 건수 (창이 바로 다시 보이게)
        self.on_seen = on_seen or (lambda: None)   # '다 봤음 · 보고 만들러 가기' (2026-11-17): 창이 보고 만들기 단계로 넘어가게
        self.key = secrets.token_urlsafe(16)
        self.server = None
        self.lock = threading.Lock()
        self.G = None
        self.G_sig = None

    @property
    def url(self):
        return "http://127.0.0.1:%d/%s" % (self.server.server_address[1], self.key)

    def page(self, fresh=False):
        with self.lock:
            sig = _sources_sig(self.app_dir, self.input_dir)
            if self.G is None or fresh or sig != self.G_sig:   # P3-11: 새 변환 등으로 자료가 바뀌었으면 다시 모은다
                self.G = gather(self.app_dir, self.input_dir, self.asof)
                self.G_sig = sig
            else:   # 결정만 다시 붙인다 (계산은 다시 안 함)
                self.G["counts"] = apply_decisions(self.G["items"], read_decisions(self.input_dir))
            return render(self.G, self.key)

    def changed(self):
        """화면을 모은 뒤 자료(변환 결과 등)가 바뀌었는가."""
        return self.G_sig is not None and _sources_sig(self.app_dir, self.input_dir) != self.G_sig

    def counts(self):
        """지금 결정으로 다시 센 건수 (계산은 다시 안 함)."""
        with self.lock:
            if self.G is None:
                return {}
            self.G["counts"] = apply_decisions(self.G["items"], read_decisions(self.input_dir))
            return dict(self.G["counts"])

    def decide(self, item_id, choice, memo, content):
        by_id = dict((it["id"], it) for it in (self.G or {}).get("items", []))
        if item_id not in by_id:
            raise ValueError("화면에 없는 항목 — '다시 모으기'를 누르세요")
        it = by_id[item_id]
        amount = it.get("amount") if it.get("kind") in TRACK_AMOUNT else None
        save_decision(self.input_dir, item_id, choice, memo, content, amount)
        state = choice_state(choice)
        self.on_saved("확인할 것 %s: %s" % ("결정 지움" if not choice else "결정 저장", (content or item_id)[:60] + (" → " + choice if choice else "")))
        try:
            self.on_counts(self.counts())
        except Exception:   # 창에 알리지 못해도 저장은 됐다
            pass
        return state

    def start(self):
        sess = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json; charset=utf-8"):
                data = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                u = urlparse(self.path)
                if u.path == "/state":   # 편의성 21: 열어 둔 화면이 새 자료가 왔는지 묻는다
                    q = dict(p.split("=", 1) for p in u.query.split("&") if "=" in p)
                    if not secrets.compare_digest(q.get("k", ""), sess.key):
                        return self._send(403, "{}")
                    return self._send(200, json.dumps({"changed": sess.changed()}))
                if u.path != "/" + sess.key:
                    return self._send(404, "{}")
                return self._send(200, sess.page(fresh="fresh=1" in u.query), "text/html; charset=utf-8")

            def do_POST(self):
                u = urlparse(self.path)
                q = dict(p.split("=", 1) for p in u.query.split("&") if "=" in p)
                if u.path == "/seen" and secrets.compare_digest(q.get("k", ""), sess.key):
                    try:
                        sess.on_seen()
                    except Exception:   # 창에 알리지 못해도 화면은 그대로
                        pass
                    return self._send(200, json.dumps({"ok": True}))
                if u.path != "/decide" or not secrets.compare_digest(q.get("k", ""), sess.key):
                    return self._send(403, json.dumps({"ok": False, "msg": "열쇠가 맞지 않음"}, ensure_ascii=False))
                n = int(self.headers.get("Content-Length") or 0)
                if n > 100000:
                    return self._send(413, json.dumps({"ok": False, "msg": "너무 큼"}, ensure_ascii=False))
                try:
                    body = json.loads(self.rfile.read(n).decode("utf-8"))
                    state = sess.decide(str(body.get("id") or ""), str(body.get("choice") or ""), str(body.get("memo") or ""),
                                        str(body.get("content") or ""))
                except (ValueError, OSError) as e:
                    return self._send(400, json.dumps({"ok": False, "msg": str(e) if isinstance(e, ValueError) else type(e).__name__},
                                                      ensure_ascii=False))
                return self._send(200, json.dumps({"ok": True, "state": state, "word": STATE_WORD[state], "counts": _shown_counts(sess.G)},
                                                  ensure_ascii=False))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self.url

    def stop(self):
        if self.server:
            srv, self.server = self.server, None
            srv.shutdown()
            srv.server_close()
