"""'확인할 것' 화면 (사용자 2026-11-05: 확인이 필요한 것을 따로 화면으로, 건마다 화면에서 보고 결정을 입력).

모으는 것
  · 변환 때 만든 것 (입력\\확인할것.json): 중복 의심 전표, 홈택스 대조, 변환 대조 불일치, 카드 전표 입력 전
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
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import util

CONVERT_FILE = "확인할것.json"
STORE = "확인결정.csv"
STORE_COLS = ["항목ID", "결정", "메모", "결정일", "내용"]
BANK_FILE = "통장잔액.csv"
BANK_COLS = ["날짜", "통장잔액", "메모"]
FIX_WORDS = ("고칠 것", "넣을 것", "지울 것", "발급할 것", "확인 필요")
ORDER = ("중복 의심 전표", "미지급금 예정 > 장부", "두 출처 출금", "통장 잔액 대조", "홈택스 대조", "계좌 없는 이체 거래처",
         "변환 대조", "카드 전표", "정합성 점검", "입력 자료")


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
    return out


def save_convert_items(input_dir, items, now=None, trace=None):
    """trace: 거래처코드별 미지급금 장부 풀이 글 (review_checks.payable_trace 의 text, 보고 때 '미지급금 예정 > 장부' 판단에 씀)."""
    data = {"_시각": (now or dt.datetime.now()).strftime("%Y-%m-%d %H:%M"), "items": items, "trace": trace or {}}
    path = os.path.join(input_dir, CONVERT_FILE)
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, default=str)
        os.replace(path + ".tmp", path)
    except OSError:
        pass


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
        with open(path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("항목ID"):
                    out[r["항목ID"]] = r
    except (OSError, UnicodeDecodeError, csv.Error):
        pass
    return out


def save_decision(input_dir, item_id, choice, memo="", content=""):
    """결정 한 줄을 넣거나 고친다. choice 를 비우면 결정을 지운다 (다시 '결정할 것'으로)."""
    if not item_id:
        raise ValueError("항목이 없음")
    cur = read_decisions(input_dir)
    if choice:
        cur[item_id] = {"항목ID": item_id, "결정": choice.strip(), "메모": (memo or "").strip()[:500],
                        "결정일": dt.date.today().isoformat(), "내용": (content or "")[:300]}
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
        with open(path, encoding="utf-8-sig", newline="") as f:
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
        with open(bal_path, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                d, v = util.date(r.get("기준일")), util.num(r.get("잔액"))
                if d is not None and v is not None:
                    snaps.setdefault(d, 0)
                    snaps[d] += int(v)
    except (OSError, UnicodeDecodeError, csv.Error):
        return None, None
    moves = []
    try:
        with open(mov_path, encoding="utf-8-sig", newline="") as f:
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
                                  + " — ⑥ 이체 파일 만들기를 누르면 뜨는 창에서 바로 넣을 수 있음",
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
        out.append({"id": "입력|%s|%s|%s" % (f, _h(msg), _h(",".join(sorted(vals)))), "kind": "입력 자료", "date": "", "amount": None,
                    "vendor": "", "title": "%s: %s%s" % (f, msg[:120], " (%d건)" % len(lines) if len(lines) > 1 else ""),
                    "detail": detail, "choices": ["고칠 것", "그대로 둠 (괜찮음)"]})
    return out


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
        if "← 바뀜" in s or (("확인 필요" in s or "불일치" in s) and "0건" not in s and "0개" not in s and "OK" not in s):
            out.append({"id": "정합성|%s" % _h(s), "kind": "정합성 점검", "date": when[:10], "amount": None, "vendor": "",
                        "title": "정합성 점검 (%s): %s" % (when, s[:140]), "detail": s,
                        "choices": ["이유 앎 — 괜찮음", "확인 필요"]})
    return out


def gather(app_dir, input_dir, asof):
    """-> {'items': [항목 + decision], 'convert_at': 변환 시각, 'counts': {...}}."""
    conv, when = _load_convert_items(input_dir)
    items = conv + _report_items(input_dir, asof) + bank_items(input_dir) + _integrity_items(app_dir)
    seen, uniq = set(), []
    for it in items:
        if it["id"] in seen:
            continue
        seen.add(it["id"])
        uniq.append(it)
    dec = read_decisions(input_dir)
    for it in uniq:
        it["decision"] = dec.get(it["id"])
        ch = (it["decision"] or {}).get("결정", "")
        it["state"] = "open" if not ch else ("fix" if any(w in ch for w in FIX_WORDS) else "done")
    rank = {k: i for i, k in enumerate(ORDER)}
    uniq.sort(key=lambda it: (rank.get(it["kind"], 99), -(abs(it["amount"] or 0)), it["date"] or ""))
    counts = {s: sum(1 for it in uniq if it["state"] == s) for s in ("open", "fix", "done")}
    return {"items": uniq, "convert_at": when, "counts": counts}


def summary_line(G):
    c = G["counts"]
    return "확인할 것: 결정할 것 %d건 · 고치기 기다림 %d건 · 결정함 %d건" % (c["open"], c["fix"], c["done"])


# ───────────── 화면 ─────────────
CSS = """
*{box-sizing:border-box}body{margin:0;font:14px/1.5 'Malgun Gothic','Apple SD Gothic Neo',sans-serif;color:#1d2433;background:#f4f6f9}
header{position:sticky;top:0;z-index:5;background:#1f4e8c;color:#fff;padding:12px 20px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
header h1{font-size:18px;margin:0}header .c{display:flex;gap:8px}header .c span{background:#ffffff22;border-radius:12px;padding:2px 10px;font-size:13px}
header .c b{font-size:15px}header label{font-size:13px;cursor:pointer}header .sp{flex:1}
header button{font:13px 'Malgun Gothic',sans-serif;padding:5px 12px;border:1px solid #fff;border-radius:4px;background:transparent;color:#fff;cursor:pointer}
main{max-width:980px;margin:0 auto;padding:14px 16px 60px}.meta{color:#5b6475;font-size:12px;margin:0 0 10px}
h2{font-size:15px;margin:22px 0 8px;padding-left:8px;border-left:4px solid #1f4e8c}h2 small{font-weight:400;color:#5b6475}
.it{background:#fff;border:1px solid #dde2ea;border-radius:8px;padding:10px 14px;margin:8px 0}
.it.fix{border-left:5px solid #c0392b}.it.done{opacity:.75;border-left:5px solid #2f7d5b}.it.open{border-left:5px solid #e0a100}
.top{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap}.top .t{font-weight:700;flex:1;min-width:240px}
.top .a{font-weight:800;font-size:15px;white-space:nowrap}.v{color:#1f4e8c;font-weight:700}.d{color:#5b6475;font-size:13px;margin:2px 0 6px}
.ch{display:flex;gap:6px;flex-wrap:wrap;align-items:center}.ch label{border:1px solid #c9d1de;border-radius:16px;padding:3px 10px;font-size:13px;cursor:pointer;background:#f7f8fa}
.ch input[type=radio]{margin:0 4px 0 0}.ch label.on{background:#1f4e8c;color:#fff;border-color:#1f4e8c}
.ch input.memo{flex:1;min-width:180px;font:13px 'Malgun Gothic',sans-serif;padding:4px 8px;border:1px solid #c9d1de;border-radius:4px}
.ch button{font:13px 'Malgun Gothic',sans-serif;padding:4px 12px;border:0;border-radius:4px;background:#1f4e8c;color:#fff;cursor:pointer}
.ch button.clr{background:#eef1f5;color:#1d2433}.st{font-size:12px;color:#2f7d5b;margin-left:4px}.dec{font-size:12px;color:#5b6475;margin-top:4px}
.empty{color:#5b6475;padding:20px;text-align:center;background:#fff;border-radius:8px}
body:not(.all) .it.done{display:none}
@media (max-width:640px){header{padding:10px 12px}main{padding:10px 10px 40px}}
"""

JS = """
(function(){
  var KEY=%(key)s;
  document.getElementById('all').onchange=function(){document.body.classList.toggle('all',this.checked);};
  document.querySelectorAll('.ch input[type=radio]').forEach(function(r){r.onchange=function(){
    var box=r.closest('.ch'); box.querySelectorAll('label').forEach(function(l){l.classList.toggle('on',l.contains(r)&&r.checked);});};});
  function send(it,choice){
    var memo=it.querySelector('input.memo').value, st=it.querySelector('.st');
    st.textContent='저장 중…';
    var x=new XMLHttpRequest(); x.open('POST','/decide?k='+KEY); x.setRequestHeader('Content-Type','application/json; charset=utf-8');
    x.onload=function(){var r={};try{r=JSON.parse(x.responseText);}catch(e){}
      if(x.status===200&&r.ok){st.textContent=choice?'저장함 ('+r.word+')':'결정 지움'; it.className='it '+r.state;}
      else st.textContent='저장 못함: '+(r.msg||'프로그램 창이 닫혔는지 확인');};
    x.onerror=function(){st.textContent='저장 못함: 프로그램 창이 닫혔는지 확인';};
    x.send(JSON.stringify({id:it.dataset.id,choice:choice,memo:memo,content:it.dataset.c}));
  }
  document.querySelectorAll('.it').forEach(function(it){
    it.querySelector('button.ok').onclick=function(){var r=it.querySelector('input[type=radio]:checked');
      if(!r){it.querySelector('.st').textContent='결정을 하나 고르세요';return;} send(it,r.value);};
    it.querySelector('button.clr').onclick=function(){it.querySelectorAll('input[type=radio]').forEach(function(r){r.checked=false;});
      it.querySelectorAll('label').forEach(function(l){l.classList.remove('on');}); send(it,'');};
  });
  document.getElementById('reload').onclick=function(){location.href='/'+KEY+'?fresh=1';};
})();
"""

STATE_WORD = {"open": "결정할 것", "fix": "고치기 기다림", "done": "결정함"}


def render(G, key="", mask=False):
    """확인할 것 화면 HTML. mask=True 면 거래처 이름을 가린다 (자료 밖으로 보일 미리보기용)."""
    e = html.escape
    c = G["counts"]
    h = ["<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         "<title>확인할 것</title><style>%s</style></head><body>" % CSS]
    h.append("<header><h1>확인할 것</h1><div class='c'><span>결정할 것 <b>%d</b></span><span>고치기 기다림 <b>%d</b></span>"
             "<span>결정함 <b>%d</b></span></div><span class='sp'></span><label><input type='checkbox' id='all'> 결정한 것도 보기</label>"
             "<button id='reload'>다시 모으기</button></header><main>" % (c["open"], c["fix"], c["done"]))
    h.append("<p class='meta'>마지막 자료 변환 %s · 결정은 입력\\%s 에 저장되어 다음 변환 뒤에도 그대로 붙습니다. "
             "'고칠 것'으로 고른 건은 자료에서 고쳐져 사라질 때까지 빨간 줄로 남습니다.</p>" % (e(G["convert_at"] or "기록 없음"), STORE))
    kinds = []
    for it in G["items"]:
        if it["kind"] not in kinds:
            kinds.append(it["kind"])
    if not G["items"]:
        h.append("<div class='empty'>확인할 것이 없습니다.</div>")
    for k in kinds:
        its = [it for it in G["items"] if it["kind"] == k]
        n_open = sum(1 for it in its if it["state"] == "open")
        h.append("<h2>%s <small>%d건 · 결정할 것 %d건</small></h2>" % (e(k), len(its), n_open))
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
            h.append("<div class='it %s' data-id='%s' data-c='%s'><div class='top'><span class='t'>%s</span>%s<span class='a'>%s</span></div>"
                     % (it["state"], e(it["id"], True), e("%s %s %s" % (it["title"], vend, amt), True), e(it["title"]),
                        ("<span class='v'>%s</span>" % e(vend)) if vend else "", e(amt)))
            h.append("<div class='d'>%s%s</div>" % ((e(it["date"]) + " · ") if it.get("date") else "", e(it.get("detail") or "")))
            h.append("<div class='ch'>%s<input class='memo' placeholder='메모 (선택)' value='%s'><button class='ok'>저장</button>"
                     "<button class='clr'>결정 지우기</button><span class='st'></span></div>" % ("".join(ch), e(dec.get("메모", ""), True)))
            if dec:
                h.append("<div class='dec'>%s 결정: %s%s</div>" % (e(dec.get("결정일", "")), e(dec.get("결정", "")),
                                                                ("  · 메모: " + e(dec["메모"])) if dec.get("메모") else ""))
            h.append("</div>")
    h.append("</main><script>%s</script></body></html>" % (JS % {"key": json.dumps(key)}))
    return "".join(h)


class Session(object):
    """확인할 것 화면 한 번. start() -> 주소. 결정을 저장할 때마다 on_saved(글)."""

    def __init__(self, app_dir, input_dir, asof, on_saved=None):
        self.app_dir, self.input_dir, self.asof = app_dir, input_dir, asof
        self.on_saved = on_saved or (lambda text: None)
        self.key = secrets.token_urlsafe(16)
        self.server = None
        self.lock = threading.Lock()
        self.G = None

    @property
    def url(self):
        return "http://127.0.0.1:%d/%s" % (self.server.server_address[1], self.key)

    def page(self, fresh=False):
        with self.lock:
            if self.G is None or fresh:
                self.G = gather(self.app_dir, self.input_dir, self.asof)
            else:   # 결정만 다시 붙인다 (계산은 다시 안 함)
                dec = read_decisions(self.input_dir)
                for it in self.G["items"]:
                    it["decision"] = dec.get(it["id"])
                    ch = (it["decision"] or {}).get("결정", "")
                    it["state"] = "open" if not ch else ("fix" if any(w in ch for w in FIX_WORDS) else "done")
                self.G["counts"] = {s: sum(1 for it in self.G["items"] if it["state"] == s) for s in ("open", "fix", "done")}
            return render(self.G, self.key)

    def decide(self, item_id, choice, memo, content):
        ids = set(it["id"] for it in (self.G or {}).get("items", []))
        if item_id not in ids:
            raise ValueError("화면에 없는 항목 — '다시 모으기'를 누르세요")
        save_decision(self.input_dir, item_id, choice, memo, content)
        state = "open" if not choice else ("fix" if any(w in choice for w in FIX_WORDS) else "done")
        self.on_saved("확인할 것 %s: %s" % ("결정 지움" if not choice else "결정 저장", (content or item_id)[:60] + (" → " + choice if choice else "")))
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
                if u.path != "/" + sess.key:
                    return self._send(404, "{}")
                return self._send(200, sess.page(fresh="fresh=1" in u.query), "text/html; charset=utf-8")

            def do_POST(self):
                u = urlparse(self.path)
                q = dict(p.split("=", 1) for p in u.query.split("&") if "=" in p)
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
                return self._send(200, json.dumps({"ok": True, "state": state, "word": STATE_WORD[state]}, ensure_ascii=False))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self.url

    def stop(self):
        if self.server:
            srv, self.server = self.server, None
            srv.shutdown()
            srv.server_close()
