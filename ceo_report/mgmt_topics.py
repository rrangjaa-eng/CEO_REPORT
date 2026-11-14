"""경영관리 보고를 주제별로 묶는다 (사용자 2026-11-14 결정 카드: '구성안대로 바꾸기').

구성안: /mnt/project-files/ceo-report/경영관리보고_구성안_20261114.md (시안 mockups/경영관리_주제별/)

  첫 화면   자료 상태 띠 → 대표에게 나간 숫자('대표 보고' 표시·지난번 대비) → 주제별 신호 8칸 → 할 일 표
  주제 장   1 자금 · 2 프로젝트 예산 · 3 매출·손익 · 4 계산서·수금 · 5 프로젝트 밖 지급 · 6 자료·지급 관리 ·
            7 위하고 대조 · 8 현금흐름 (주간은 1~6). 모두 같은 여섯 층:
            ① 결론 ② 할 일 ③ 지난 보고 뒤 바뀐 것 ④ 자동 분석·위험(걸린 것 먼저) ⑤ 상세 표 ⑥ 근거
  정기 장   분기·반기·결산 준비 (11/12 규칙 그대로)
  부록      대표가 본 화면(근거 묶음 포함) · 요청 자료 전부 · 전체 표 모음(위험 분석 전체 표·옛 번호 찾기)

계산은 하나도 바꾸지 않는다. 지금까지의 장·표(render 가 만든 HTML)를 감싸 자리만 옮긴다.
옮긴 조각은 <!--o:번호--> … <!--/o:번호--> 로 표시해 둔다: 번호 = 예전 보고서 안의 순서.
areas.strip_ui 가 이 표시로 예전 순서의 문서를 다시 맞춰, '예전 보고와 숫자·문구가 같다'는 시험을 그대로 쓴다.
"""
import base64
import datetime as dt
import hashlib
import json
import os
import re

from .util import esc, won

# ─────────── 주제 · 자리 ───────────
TOPIC_KEYS = ("cash", "proj", "pl", "ar", "other", "data", "xchk", "cf")
CHAPTERS = {"cash": ("s1", "s2", "gasu"), "proj": ("s3",), "pl": ("s4",), "ar": ("s5",), "other": ("s6",),
            "data": ("s7", "recon"), "xchk": ("s8",), "cf": ("s9",)}
OLD_NAMES = {"s1": "B-1", "s2": "B-2", "gasu": "B-2-1", "s3": "B-3", "s4": "B-4", "s5": "B-5", "s6": "B-6", "s7": "B-7", "recon": "B-7-1",
             "s8": "B-8", "s9": "B-9"}
RISK_TOPIC = {"자금": "cash", "프로젝트": "proj", "수금": "ar", "자료": "data", "지급 관리": "data"}
# 자동 분석 15가지 (경영관리 '자동 분석' 영역의 번호) → (주제, 층). 1 경보는 줄마다 해당 주제 ④
AUTO_PLACE = {2: ("cash", 3), 15: ("cash", 3), 3: ("cash", 4), 5: ("cash", 4), 6: ("cash", 4),
              4: ("pl", 4), 13: ("pl", 4), 12: ("proj", 4), 7: ("ar", 4), 10: ("ar", 4), 11: ("ar", 4), 14: ("ar", 4),
              8: ("other", 4), 9: ("data", 4)}
WEEKLY_OPEN = ("cash", "other", "data")   # 주간 경영관리: 자금·프로젝트 밖 지급·자료 관리 위주로 펼침 (구성안 5)
RECORD_DIR = "자동분석기록"
LAYERS = ("결론", "할 일", "지난 보고 뒤 바뀐 것", "자동 분석 · 위험", "상세 표", "근거")
CIRCLE = "①②③④⑤⑥"
WORD = {"ok": "양호", "wa": "주의", "bad": "위험", "nod": "자료 없음"}
RANK = {"ok": 0, "wa": 1, "bad": 2}


# ─────────── 옮긴 조각 표시 (예전 순서 번호) ───────────
def frag(n, body):
    return "<!--o:%03d-->%s<!--/o:%03d-->" % (n, body, n)


def hidden(n, body):
    """예전 문서에만 있던 껍데기(여닫는 div 등): 화면에는 안 나오고 strip_ui 가 다시 끼운다."""
    return "<!--o:%03d:%s-->" % (n, base64.b64encode(body.encode("utf-8")).decode("ascii"))


FRAG_RE = re.compile(r"<!--o:(\d{3})-->(.*?)<!--/o:\1-->|<!--o:(\d{3}):([A-Za-z0-9+/=]*)-->", re.S)


def restore(page, toc=False):
    """주제별로 옮긴 조각을 예전 순서로 다시 잇는다 -> 예전 보고서 모양의 HTML (영역 틀 없이).
    toc=True 면 예전 목차 자리(대표 화면·근거 묶음 | 상세 장 경계)에 <div class='toc'></div> 를 끼운다 (숫자 비교 시험용)."""
    parts = []
    for m in FRAG_RE.finditer(page):
        if m.group(1):
            parts.append((int(m.group(1)), m.group(2)))
        else:
            parts.append((int(m.group(3)), base64.b64decode(m.group(4)).decode("utf-8")))
    parts.sort(key=lambda x: x[0])
    parts = [(n, _unlabel(b)) for n, b in parts]
    head = page[:page.index("<!--/head-->")] if "<!--/head-->" in page else ""
    body = []
    for n, b in parts:
        if toc and n >= 30 and (not body or body[-1][0] < 30):
            body.append((29.5, "<div class='toc'></div>"))
        body.append((n, b))
    return head + "".join(b for _, b in body) + "</div></body></html>"


_ONUM = re.compile(r"(<h2 id='s\d+'>)(\d+\. )")


def label_chapter(body, old):
    """상세 장 제목의 예전 번호('3. ')는 화면에서 숨기고 작은 회색 '예전 B-3'을 붙인다 (번호는 주제 1~8 + 층 ①~⑥ 하나로).
    restore 가 그대로 되돌린다 (_unlabel)."""
    m = _ONUM.search(body)
    if not m:
        return body
    end = body.index("</h2>", m.end())
    return (body[:m.start()] + m.group(1) + "<span class='onum'>" + m.group(2) + "</span>" + body[m.end():end]
            + "<small class='oldl'> 예전 %s</small>" % old + body[end:])


def label_q(body):
    """옮긴 첫 화면 조각의 '9. ' 같은 번호도 화면에서 숨김 (restore 가 되돌림)."""
    return re.sub(r"(<div class='q'>)(\d+\. )", r"\1<span class='onum'>\2</span>", body, count=1)


def _unlabel(body):
    body = re.sub(r"<span class='onum'>(\d+\. )</span>", r"\1", body)
    return re.sub(r"<small class='oldl'> 예전 [^<]*</small>", "", body)


# ─────────── HTML 조각 나누기 ───────────
_TAG = re.compile(r"<div\b[^>]*>|</div>")


def _children(s, a=0, b=None):
    """s[a:b] 안 맨 위 div 들 -> [(시작, 여는 태그 끝, 닫는 태그 시작, 끝)]."""
    b = len(s) if b is None else b
    out, depth, start, open_end = [], 0, None, None
    for m in _TAG.finditer(s, a, b):
        if m.group(0).startswith("</"):
            depth -= 1
            if depth == 0 and start is not None:
                out.append((start, open_end, m.start(), m.end()))
                start = None
            if depth < 0:
                return None
        else:
            if depth == 0:
                start, open_end = m.start(), m.end()
            depth += 1
    return out if depth == 0 else None


def split_evidence(evid, mark):
    """경영관리 근거 묶음(예전 A-2) -> [(번호, 'hide'|자리, html)].
    자리: 'appx'(부록 대표가 본 화면) · 'proj5'(프로젝트 예산 ⑤) · 'cash6'(자금 ⑥) · 'all'(전체 표 모음)."""
    def whole():
        return [(20, "appx", evid)]
    if not evid.startswith(mark):
        return whole()
    top = _children(evid, len(mark))
    if not top or len(top) != 1 or evid[top[0][3]:].strip():
        return whole()
    p0, p1, p2, p3 = top[0]
    kids = _children(evid, p1, p2)
    if not kids:
        return whole()
    out, n = [], 20
    out.append((n, "hide", evid[:kids[0][0]]))
    for i, (k0, k1, k2, k3) in enumerate(kids):
        opener = evid[k0:k1]
        if "mgonly" in opener:
            secs = _children(evid, k1, k2)
            if not secs:
                return whole()
            n += 1
            out.append((n, "hide", evid[k0:secs[0][0]]))
            for j, (s0, s1, s2, s3) in enumerate(secs):
                piece = evid[s0:s3]
                txt = re.sub(r"<[^>]+>", "", piece[:400])
                where = "proj5" if "프로젝트별 원가" in txt else ("cash6" if "안 들어간 것" in txt else "appx")
                n += 1
                out.append((n, where, piece))
                gap = evid[s3:secs[j + 1][0]] if j + 1 < len(secs) else evid[s3:k3]
                if gap:
                    n += 1
                    out.append((n, "hide", gap))
        else:
            n += 1
            out.append((n, "all" if "위험 항목" in evid[k0:k3] else "appx", evid[k0:k3]))
        gap = evid[k3:kids[i + 1][0]] if i + 1 < len(kids) else evid[k3:]
        if gap:
            n += 1
            out.append((n, "hide", gap))
    if n >= 30:   # 조각이 너무 많으면 (모양이 바뀜) 통째로
        return whole()
    return out


def split_auto(body):
    """자동 분석 영역 HTML -> {번호: 조각 HTML} (<h3>번호. 제목</h3>…). 나눌 수 없으면 {0: 전체}."""
    marks = list(re.finditer(r"<h3>(\d+)\. ", body))
    if not marks:
        return {0: body}
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        out[int(m.group(1))] = body[m.start():end]
    return out


def relabel_auto(piece):
    """자동 분석 조각 제목 '3. 기간 뒤 …' → '기간 뒤 … (자동 분석 3)': 주제 번호와 헷갈리지 않게."""
    return re.sub(r"^<h3>(\d+)\. (.*?)</h3>", r"<h3>\2 <small class='oldl'>자동 분석 \1</small></h3>", piece, count=1, flags=re.S)


def _is_empty_piece(piece):
    """걸린 것 없는 분석: 제목 밑이 '없음' 한 줄(<p class='note'>)뿐."""
    rest = re.sub(r"^<h3>.*?</h3>", "", piece, flags=re.S).strip()
    return bool(re.fullmatch(r"<p class='note'>[^<]*</p>", rest))


# ─────────── 할 일 ───────────
def _h(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _subject(fact):
    """할 일 이름표: 숫자가 바뀌어도 같은 일이면 같은 이름표 (프로젝트·거래처는 ':' 앞 이름)."""
    head = fact.split(":")[0] if ":" in fact[:80] else fact
    return re.sub(r"[\d,.\-−%]+", "#", head)


def todo_id(area, fact, action):
    return "할일|%s|%s" % (area, _h(_subject(fact) + "|" + re.sub(r"[\d,.\-−%]+", "#", action)))


def _owner(R, fact):
    for P in (R.get("s3") or {}).get("projects") or []:
        if P.get("id") and fact.startswith(str(P["id"])):
            return P.get("team") or "경영관리"
    return "경영관리"


def _next_report(R):
    asof = R["asof"]
    if R.get("kind") == "weekly":
        return asof + dt.timedelta(days=7)
    y, m = asof.year, asof.month + 2   # 다음 달 마지막 날 = 다다음 달 1일 − 1일
    y, m = (y + 1, m - 12) if m > 12 else (y, m)
    return dt.date(y, m, 1) - dt.timedelta(days=1)


def todo_items(R, I, L):
    """할 일 전부: 위험 분석의 해결방안(높음 먼저) + 위험 분석에 없는 자동 분석 경보 '높음' + '자료 없음' 주제의 채울 일."""
    items = []
    for r in R.get("risks") or []:
        items.append({"id": todo_id(r["area"], r["fact"], r["action"]), "topic": RISK_TOPIC.get(r["area"], "data"),
                      "level": r["level"], "text": r["action"], "fact": r["fact"], "owner": _owner(R, r["fact"])})
    facts = " ".join(r["fact"] for r in R.get("risks") or [])
    for lv, t in (I or {}).get("alerts") or []:
        if lv != "높음":
            continue
        m = re.match(r"\[([^\]]+)\]", t)
        if m and m.group(1) in facts:
            continue   # 같은 프로젝트가 위험 분석에 이미 있음
        topic = "cash" if "여유 자금" in t else "proj"
        items.append({"id": "할일|경보|%s" % _h(re.sub(r"[\d,.\-−%]+", "#", t)), "topic": topic, "level": "높음",
                      "text": t, "fact": "자동 분석 경보", "owner": _owner(R, (m.group(1) if m else ""))})
    from . import digest
    for x in L or []:
        if x["key"] in ("xchk", "cf") and _is_na(x):
            sg = digest.suggest(CHAPTERS[x["key"]][0], R, I, L)
            items.append({"id": "할일|자료없음|%s" % x["key"], "topic": "data", "level": "중간",
                          "text": sg[0] if sg else "자료를 받아 자료 변환을 다시 하세요.",
                          "fact": "%s: %s" % (x["name"], (x["facts"] or [x["sub"]])[0]), "owner": "경영관리", "from": x["key"]})
    order = {"높음": 0}
    items.sort(key=lambda it: order.get(it["level"], 1))
    return items


def todo_status(R, items):
    """새로 / 이월 n번째 / 결정(확인할 것 화면) · 메모. 지난번 할 일 중 이번엔 걸리지 않은 것은 '처리'로 돌려준다."""
    prev = (R.get("todo_prev") or {}).get("items") or {}
    dec = R.get("todo_decisions") or {}
    for it in items:
        p = prev.get(it["id"])
        it["n"] = (p.get("n", 1) + 1) if p else 1
        it["first"] = p.get("first") if p else R["asof"].isoformat()
        d = dec.get(it["id"]) or {}
        it["decision"] = d.get("결정") or ""
        it["memo"] = d.get("메모") or ""
        if it["decision"]:
            it["state"], it["st"] = it["decision"], "dec"
        elif it["n"] == 1:
            it["state"], it["st"] = "새로", "new"
        else:
            it["state"], it["st"] = "이월 %d번째" % (it["n"] - 1), "carry"
    now = set(it["id"] for it in items)
    done = []
    for k, p in prev.items():
        if k not in now:
            d = dec.get(k) or {}
            done.append({"id": k, "topic": p.get("topic", "data"), "text": p.get("text", ""), "owner": p.get("owner", ""),
                         "state": "처리", "st": "done", "memo": d.get("메모") or "이번 보고엔 걸리지 않음", "fact": ""})
    return items, done


# ─────────── 기록 (다음 보고의 '이월'·'지난번 대비') ───────────
def record_path(out_dir, R):
    return os.path.join(out_dir, RECORD_DIR, "할일_%s_%s.json" % (R["kind"], R["asof"].isoformat()))


def write_record(out_dir, R):
    T = R.get("_topics")
    if not T:
        return None
    data = {"asof": R["asof"].isoformat(), "kind": R["kind"],
            "items": dict((it["id"], {"n": it["n"], "first": it["first"], "text": it["text"], "topic": it["topic"],
                                      "owner": it["owner"], "fact": it.get("fact", "")}) for it in T["todos"]),
            "ceo": dict((c["label"], c["value"]) for c in T["cards"] if c["value"] is not None)}
    path = record_path(out_dir, R)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)
    return path


def _records(out_dir, kind=None):
    folder = os.path.join(out_dir, RECORD_DIR)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    out = []
    for nm in names:
        m = re.match(r"^할일_(weekly|monthly)_(\d{4}-\d{2}-\d{2})\.json$", nm)
        if m and (kind is None or m.group(1) == kind):
            out.append((dt.date.fromisoformat(m.group(2)), m.group(1), os.path.join(folder, nm)))
    return sorted(out)


def load_previous(out_dir, kind, asof):
    """같은 종류 보고 중 기준일이 이번보다 앞선 마지막 기록 -> dict 또는 None."""
    for d, _, path in reversed(_records(out_dir, kind)):
        if d < asof:
            try:
                with open(path, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, ValueError):
                return None
    return None


def check_items(out_dir):
    """'확인할 것' 화면에 넣을 보고 할 일 (마지막 보고 기록). 결정·메모는 확인결정.csv 에 쌓이고 다음 보고의 할 일 표에 붙는다."""
    recs = _records(out_dir)
    if not recs:
        return []
    d, kind, path = recs[-1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for k, it in (data.get("items") or {}).items():
        out.append({"id": k, "kind": "보고 할 일", "date": d.isoformat(), "amount": None, "vendor": "",
                    "title": "보고 할 일 (%s · %s): %s" % (TOPIC_NAME.get(it.get("topic"), ""), it.get("owner", ""), it.get("text", "")),
                    "detail": "%s%s" % (it.get("fact", ""), (" · %d번째 보고에 걸림" % it["n"]) if it.get("n", 1) > 1 else ""),
                    "choices": ["처리함", "진행 중 — 확인 필요", "안 해도 됨 (이유를 메모에)"]})
    return out


TOPIC_NAME = {"cash": "자금", "proj": "프로젝트 예산", "pl": "매출·손익", "ar": "계산서·수금", "other": "프로젝트 밖 지급",
              "data": "자료·지급 관리", "xchk": "위하고 대조", "cf": "현금흐름"}


# ─────────── 대표에게 나간 숫자 ───────────
def _num(html_):
    t = re.sub(r"<[^>]+>", "", html_ or "").replace("−", "-").strip()
    m = re.match(r"-?\d[\d,]*$", t)
    return int(m.group(0).replace(",", "")) if m else None


def ceo_cards(summ):
    """대표 보고 첫 줄 카드(대표가 본 그대로) -> [{label, big, foot, value, topic, good_up}]."""
    m = re.search(r"<div class='four top'>(.*?)</div></div></div>", summ, re.S)
    if not m:
        return []
    out = []
    for lab, big, foot in re.findall(r"<div class='card'><div class='lab'>(.*?)</div><div class='big'>(.*?)</div>"
                                     r"<div class='foot'>(.*?)</div></div>", m.group(0), re.S):
        plain = re.sub(r"<[^>]+>", "", lab)
        topic, up = "cash", True
        if "영업이익" in plain:
            topic = "pl"
        elif "미수금" in plain:
            topic, up = "ar", False
        elif "출금" in plain:
            up = None
        out.append({"label": plain, "big": big, "foot": foot, "value": _num(big), "topic": topic, "good_up": up})
    return out


def _delta(c, prev):
    pv = (prev or {}).get("ceo") or {}
    if c["value"] is None or c["label"] not in pv:
        return "<div class='tq-cd'>%s</div>" % ("지난 기록 없음" if prev is None else "지난번 칸 없음" if c["value"] is not None else "")
    d = c["value"] - pv[c["label"]]
    if d == 0:
        return "<div class='tq-cd'>지난번과 같음</div>"
    good = None if c["good_up"] is None else ((d > 0) == c["good_up"])
    cls = "" if good is None else (" v-up" if good else " v-dn")
    return "<div class='tq-cd%s'>%s 지난번보다 %s%s</div>" % (cls, "▲" if d > 0 else "▼", "+" if d > 0 else "−", esc(won(abs(d))))


# ─────────── 그리기 ───────────
CSS = """
.tp-band{display:flex;flex-wrap:wrap;gap:6px;align-items:center;border:1px solid #e3c9c4;background:#fdf6f4;border-radius:10px;padding:8px 12px;margin:6px 0 12px}
.tp-band.v-ok{border-color:#cfe0d6;background:#f6fbf8}
.tp-band b{font-size:12.5px;margin-right:4px}
.tq-chip{display:inline-flex;align-items:center;gap:4px;font-size:12px;border-radius:12px;padding:2px 10px;border:1px solid #cfd6df;background:#fff;white-space:nowrap}
.tq-chip.v-ok{border-color:#9fcfb3;color:#246b4a}.tq-chip.v-old{border-color:#e6c77a;color:#8a5d00;background:#fffaf0}
.tq-chip.v-bad{border-color:#d98d80;color:#a3301f;background:#fdeeeb;font-weight:700}
.tp-h{display:flex;align-items:baseline;gap:8px;margin:16px 0 6px;font-size:15px;font-weight:800;border-left:4px solid var(--ink);padding-left:8px}
.tp-h small{font-size:12px;font-weight:400;color:var(--sub)}
.tp-cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.tp-cards a,.tp-sig a{text-decoration:none;color:inherit}
.tp-card{display:block;border:1px solid var(--line);border-radius:10px;padding:9px 12px;break-inside:avoid}
.tp-card .tq-cl{font-size:12px;color:var(--sub);display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.tp-card .tq-cv{font-size:19px;font-weight:800;margin:4px 0 2px;font-variant-numeric:tabular-nums}
.tp-card .tq-cf{font-size:11px;color:var(--sub)}
.tq-tag{font-size:10.5px;border:1px solid var(--ink);border-radius:4px;padding:0 4px;color:var(--ink);white-space:nowrap}
.tq-cd{font-size:11.5px;color:var(--sub);margin-top:2px}.tq-cd.v-up{color:#246b4a}.tq-cd.v-dn{color:#b3261e}
.tp-sig{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
.tq-sg{display:block;border:1.5px solid var(--line);border-radius:10px;padding:8px 11px;break-inside:avoid;background:#fff}
.tq-sg .tq-sn{display:flex;justify-content:space-between;gap:6px;font-size:11.5px;color:var(--sub)}
.tq-sg .tq-st{font-size:13.5px;font-weight:700;margin:4px 0 2px;line-height:1.35}
.tq-sg .tq-sv{font-size:11.5px;color:var(--sub)}
.tq-sg .tq-sf{font-size:11.5px;margin-top:3px;color:var(--sub)}
.tq-sg.v-bad{border-color:#e3a596;background:#fffaf8}.tq-sg.v-wa{border-color:#ecd08a;background:#fffcf3}.tq-sg.v-ok{border-color:#b9dcc9}
.tq-sg.v-nod{border-color:#d5d9df;background:#f5f6f8}.tq-sg.v-nod .tq-st{color:#555}
.tq-sg .tq-sf .v-dn{color:#b3261e;font-weight:700}.tq-sg .tq-sf .v-up{color:#246b4a;font-weight:700}
.tq-lv{font-size:10.5px;font-weight:700;border-radius:8px;padding:0 7px;white-space:nowrap}
.tq-lv.v-ok{background:#e7f3ec;color:#2f7d5b}.tq-lv.v-wa{background:#fff3d6;color:#a86b00}.tq-lv.v-bad{background:#fbe9e7;color:#b5523b}.tq-lv.v-nod{background:#e6e9ee;color:#555}
table.pt.td td,table.pt.td th{text-align:left!important;white-space:normal!important;vertical-align:top}
table.pt.td td.n{white-space:nowrap!important}
.tq-stt{font-size:11px;border-radius:8px;padding:0 7px;white-space:nowrap;font-weight:600}
.tq-stt.v-new{background:#e8eefb;color:#2b4f9e}.tq-stt.v-carry{background:#fff3d6;color:#8a5d00}.tq-stt.v-dec{background:#eef1f4;color:#2b3a4e}
.tq-stt.v-done{background:#e7f3ec;color:#2f7d5b}
tr.tdone td{color:#8a93a0}
.tp-note{font-size:11.5px;color:var(--sub);margin:4px 0}
h1.tp{font-size:20px;margin:6px 0 10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;break-after:avoid}
h1.tp small{font-size:11.5px;font-weight:400;color:#7a8391}
.tq-ly{border:1px solid var(--line);border-radius:10px;margin:10px 0;break-inside:auto}
.tq-ly>.tq-lh{display:flex;justify-content:space-between;align-items:baseline;gap:8px;padding:7px 12px;border-bottom:1px solid var(--line);
background:#f7f8fa;border-radius:10px 10px 0 0;font-weight:700;font-size:13.5px;break-after:avoid}
.tq-ly>.tq-lh small{font-weight:400;color:var(--sub);font-size:11.5px}
.tq-ly>.tq-lb{padding:8px 12px}
.tq-ly.l1{border:1.5px solid var(--line)}.tq-ly.l1.v-bad{border-color:#e3a596;background:#fffaf8}.tq-ly.l1.v-wa{border-color:#ecd08a;background:#fffcf3}
.tq-ly.l1.v-ok{border-color:#b9dcc9}.tq-ly.l1.v-nod{background:#f5f6f8}
.tq-ly.l1 .tq-lb .tq-hl{font-size:15px;font-weight:700;margin:2px 0 4px}
.tq-ly.l1 .tq-lb ul{margin:4px 0;padding-left:18px}
.onum{display:none}small.oldl{font-size:11px;font-weight:400;color:#8a93a0;margin-left:6px}
.ynone .yn{color:var(--sub);font-size:12px}
.tpfold-btn,.ynone-btn{display:none}
@media screen{
body.js-areas section.tfold .tq-ly.lx{display:none}
body.js-areas .tpfold-btn{display:inline-block;font:inherit;font-size:12.5px;padding:5px 12px;border:1px dashed #8a96a8;border-radius:6px;background:#f7f8fa;color:#2b3a4e;cursor:pointer;margin:4px 0}
body.js-areas section.tfold .tpfold-btn{display:inline-block}
body.js-areas section:not(.tfold) .tpfold-btn.on{display:none}
body.js-areas .ynone.yfold .ypiece{display:none}
body.js-areas .ynone-btn{display:inline;font:inherit;font-size:12px;border:0;background:none;color:var(--accent);cursor:pointer;text-decoration:underline;padding:0 4px}
.ttool{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:4px 0 6px;font-size:12px}
.ttool input,.ttool select{font:inherit;font-size:12px;padding:3px 7px;border:1px solid #c5ccd6;border-radius:6px}
.ttool input{min-width:200px}
table.tsort thead th{cursor:pointer}
table.tsort thead th[data-s]:after{content:' ↕';color:#9aa3ae;font-size:10px}
table.tsort thead th[data-s=asc]:after{content:' ▲';color:var(--ink)}
table.tsort thead th[data-s=desc]:after{content:' ▼';color:var(--ink)}
table.afilt tr.afx{display:table-row}
table tr.fno,table.afilt tr.fno{display:none}
.anav .ai a .dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:1px;background:#b9c1cc}
.anav .ai a .dot.bad{background:#c0392b}.anav .ai a .dot.wa{background:#d29a12}.anav .ai a .dot.ok{background:#2f7d5b}
.anav .abg.wa{background:#d29a12}.anav .abg.nod{background:#e6e9ee;color:#555;font-weight:600}
}
@media print{.ttool{display:none}}
@media screen and (max-width:900px){.tp-cards,.tp-sig{grid-template-columns:repeat(2,minmax(0,1fr))}}
"""

JS = r"""
<script>
(function(){
  // 접은 주제: '펼치기'를 누르면 ③~⑥ 이 보인다 (인쇄·PDF 에는 늘 전부)
  [].slice.call(document.querySelectorAll('.tpfold-btn')).forEach(function(b){
    b.addEventListener('click',function(){var s=b.closest('section');var on=s.classList.toggle('tfold');
      b.textContent=on?b.getAttribute('data-c'):'접기';b.classList.toggle('on',!on);});});
  // 걸린 것 없는 분석: 한 줄로 접어 둠
  [].slice.call(document.querySelectorAll('.ynone')).forEach(function(d){
    var b=d.querySelector('.ynone-btn');if(!b)return;d.classList.add('yfold');
    b.addEventListener('click',function(){var on=d.classList.toggle('yfold');b.textContent=on?'펼치기':'접기';});});
  // 상세 표 도구: 찾기 · 거르기 · 머리 칸 눌러 정렬 (10줄 넘는 표)
  function txt(c){return (c.innerText||c.textContent||'').trim();}
  function num(t){var s=t.replace(/[,\s원]/g,'').replace('−','-');var m=s.match(/^-?\d+(\.\d+)?/);return m?parseFloat(m[0]):null;}
  [].slice.call(document.querySelectorAll('.ly5 table')).forEach(function(t){
    if(t.querySelector('[rowspan]')||t.querySelector('[colspan]')&&!t.tHead||!t.tBodies.length||!t.tHead)return;
    var body=t.tBodies[0];
    var rows=[].slice.call(body.rows).filter(function(r){return !r.classList.contains('tot')&&!r.classList.contains('xsub');});
    if(rows.length<=10)return;
    var heads=[].slice.call(t.tHead.rows[t.tHead.rows.length-1].cells);
    if(heads.length!==rows[0].cells.length)return;
    var bar=document.createElement('div');bar.className='ttool';
    var q=document.createElement('input');q.type='search';q.placeholder='찾기 (거래처·프로젝트 번호·내용)';q.setAttribute('aria-label','표에서 찾기');
    bar.appendChild(q);
    var sels=[];
    heads.forEach(function(h,i){
      if(sels.length>=2)return;
      var vals={};rows.forEach(function(r){var c=r.cells[i];if(c){var v=txt(c);if(v)vals[v]=1;}});
      var ks=Object.keys(vals);
      if(ks.length<2||ks.length>8||ks.some(function(k){return num(k)!==null&&k.length>3;}))return;
      var s=document.createElement('select');s.setAttribute('aria-label',txt(h)+' 거르기');s.setAttribute('data-i',i);
      s.innerHTML='<option value="">'+txt(h)+' 모두</option>'+ks.sort().map(function(k){return '<option>'+k.replace(/</g,'&lt;')+'</option>';}).join('');
      bar.appendChild(s);sels.push(s);});
    var n=document.createElement('span');n.style.color='#555';bar.appendChild(n);
    function apply(){
      var w=q.value.trim().toLowerCase();var any=w||sels.some(function(s){return s.value;});var k=0;
      rows.forEach(function(r){
        var ok=(!w||txt(r).toLowerCase().indexOf(w)>=0)&&sels.every(function(s){return !s.value||(r.cells[+s.getAttribute('data-i')]&&txt(r.cells[+s.getAttribute('data-i')])===s.value);});
        r.classList.toggle('fno',!ok);var x=r.nextElementSibling;if(x&&x.classList.contains('xsub'))x.classList.toggle('fno',!ok);if(ok)k++;});
      t.classList.toggle('afilt',!!any);n.textContent=any?(k+'줄 / 전체 '+rows.length+'줄'):'';}
    q.addEventListener('input',apply);sels.forEach(function(s){s.addEventListener('change',apply);});
    t.classList.add('tsort');
    heads.forEach(function(h,i){h.setAttribute('data-s','');h.addEventListener('click',function(){
      var dir=h.getAttribute('data-s')==='asc'?'desc':'asc';heads.forEach(function(o){o.setAttribute('data-s','');});h.setAttribute('data-s',dir);
      var pairs=rows.map(function(r){var x=r.nextElementSibling;return [r,x&&x.classList.contains('xsub')?x:null];});
      pairs.sort(function(a,b){var p=txt(a[0].cells[i]||a[0]),q2=txt(b[0].cells[i]||b[0]);var u=num(p),v=num(q2);
        var c=(u!==null&&v!==null)?u-v:p.localeCompare(q2,'ko');return dir==='asc'?c:-c;});
      var tot=[].slice.call(body.rows).filter(function(r){return r.classList.contains('tot');});
      pairs.forEach(function(p){body.appendChild(p[0]);if(p[1])body.appendChild(p[1]);});
      tot.forEach(function(r){body.appendChild(r);});
      // 접기(앞 10줄)는 정렬한 순서로 다시
      if(t.classList.contains('afold')){var i2=0;[].slice.call(body.rows).forEach(function(r){if(r.classList.contains('tot'))return;
        if(r.classList.contains('xsub')){r.classList.toggle('afx',i2>10);return;}i2++;r.classList.toggle('afx',i2>10);});}
    });});
    var box=t.parentElement&&t.parentElement.classList.contains('tw')?t.parentElement:t;
    box.parentNode.insertBefore(bar,box);
  });
})();
</script>"""


def _lv_badge(lv):
    return "<span class='tq-lv v-%s'>%s</span>" % (lv, WORD.get(lv, lv))


def _is_na(x):
    return x["num"] in ("자료 없음", "판단 불가") or (x["key"] == "xchk" and x["num"] != "대조함")


def _short(t, n=46):
    t = re.sub(r"\s+", " ", t or "").strip()
    return t if len(t) <= n else t[:n - 1] + "…"


def _change(x):
    """(글, 좋아짐/나빠짐 cls)."""
    b = x.get("before")
    if b is None:
        return "지난 기록 없음", ""
    if b == x["lv"]:
        return "지난번과 같음", ""
    worse = RANK.get(x["lv"], 0) > RANK.get(b, 0)
    return "%s %s (%s→%s)" % ("▼" if worse else "▲", "나빠짐" if worse else "좋아짐", WORD.get(b, b), WORD[x["lv"]]), ("v-dn" if worse else "v-up")


def _todo_table(items, done, with_topic, num_of):
    if not items and not done:
        return "<div class='tp-note'>걸린 할 일 없음</div>"
    head = ["#", "할 일"] + (["주제"] if with_topic else []) + ["담당", "기한", "상태", "메모"]
    rows = []
    for i, it in enumerate(items, 1):
        cells = ["<td class='n'>%d</td>" % i,
                 "<td>%s<br><small>%s</small></td>" % (esc(it["text"]), esc(it.get("fact") or ""))]
        if with_topic:
            cells.append("<td class='n'><a href='#a-%s'>%d. %s</a></td>" % (it["topic"], num_of[it["topic"]], esc(TOPIC_NAME[it["topic"]])))
        cells += ["<td class='n'>%s</td>" % esc(it["owner"]), "<td class='n'>%s</td>" % esc(it["due"]),
                  "<td class='n'><span class='tq-stt v-%s'>%s</span></td>" % (it["st"], esc(it["state"])), "<td>%s</td>" % esc(it.get("memo") or "")]
        rows.append("<tr>%s</tr>" % "".join(cells))
    for it in done:
        cells = ["<td class='n'>✓</td>", "<td>%s</td>" % esc(it["text"])]
        if with_topic:
            cells.append("<td class='n'>%s</td>" % ("%d. %s" % (num_of[it["topic"]], esc(TOPIC_NAME[it["topic"]])) if it["topic"] in num_of else ""))
        cells += ["<td class='n'>%s</td>" % esc(it["owner"]), "<td class='n'></td>",
                  "<td class='n'><span class='tq-stt v-done'>처리</span></td>", "<td>%s</td>" % esc(it["memo"])]
        rows.append("<tr class='tdone'>%s</tr>" % "".join(cells))
    return ("<div class='tw'><table class='pt td nofold'><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>"
            % ("".join("<th>%s</th>" % h for h in head), "".join(rows)))


def _band(R):
    """자료 상태 띠: 자료마다 날짜와 ✓/오래됨/없음, 자금계획서·분개장이 막히면 그 영향."""
    from . import gate
    days = gate.max_days(R)
    chips, bad = [], False
    for p in gate.problems(R):
        bad = True
        chips.append("<span class='tq-chip v-bad'>%s → 자금 숫자 비움</span>" % esc(_short(p, 60)))
    bd = gate.book_date(R)
    chips.append("<span class='tq-chip v-%s'>분개장 %s%s</span>" % ("ok" if bd and (R["asof"] - bd).days <= days else "old",
                                                           bd.strftime("%m/%d") if bd else "날짜 모름",
                                                           " ✓" if bd and (R["asof"] - bd).days <= days else ""))
    fp = R.get("fundplan")
    if fp and fp.get("used"):
        chips.append("<span class='tq-chip v-ok'>자금계획서 %s ✓</span>" % fp["stamp"].strftime("%m/%d"))
    elif not bad:
        chips.append("<span class='tq-chip v-bad'>자금계획서 미반영</span>")
    for a in (R.get("s7") or {}).get("asof") or []:
        if a["age"] is None:
            chips.append("<span class='tq-chip v-old'>%s 날짜 없음</span>" % esc(a["name"]))
        elif a["age"] > days:
            chips.append("<span class='tq-chip v-old'>%s %s (%d일 지남)</span>" % (esc(a["name"]), a["date"].strftime("%m/%d"), a["age"]))
        else:
            chips.append("<span class='tq-chip v-ok'>%s %s ✓</span>" % (esc(a["name"]), a["date"].strftime("%m/%d")))
    bad = bad or not (fp and fp.get("used")) or any("v-bad" in c or "v-old" in c for c in chips)
    return "<div class='tp-band%s'><b>자료 상태</b>%s</div>" % ("" if bad else " v-ok", "".join(chips))


def build(R, mode_css_mon, parts):
    """주제별 경영관리 보고 본문 -> [(키, 이름, 묶음, html, 배지, 배지 종류, 점)] 와 머리에 붙일 html.
    parts: header(str) · summ · evid · mark · risk · auto(html|None) · I · L · chap({키: html}) · periodic([(키, 이름, html)]) ·
           docs(html) · guide(함수 key->html) · filing([글])"""
    from . import digest
    I, L = parts["I"], parts["L"]
    weekly = R.get("kind") == "weekly"
    keys = [x["key"] for x in L]
    num_of = dict((k, i) for i, k in enumerate(keys, 1))
    Ld = dict((x["key"], x) for x in L)
    fs = "<div class='fs%s'>%%s</div>" % (" mon" if mode_css_mon else "")

    # 할 일
    items = todo_items(R, I, L)
    items, done = todo_status(R, items)
    due = _next_report(R)
    for it in items:
        it["due"] = due.strftime("%m/%d")
    by_topic = dict((k, [it for it in items if it["topic"] == k]) for k in keys)
    done_by = dict((k, [it for it in done if it["topic"] == k]) for k in keys)

    cards = ceo_cards(parts["summ"])
    prev = R.get("todo_prev")
    R["_topics"] = {"todos": items, "cards": cards}

    # 펼침: 11/12 규칙(digest.decide) 그대로 + 주간은 자금·프로젝트 밖 지급·자료 관리
    for x in L:
        x["open2"] = x.get("open") or (weekly and x["key"] in WEEKLY_OPEN) or bool(by_topic.get(x["key"]))

    # 옮길 조각들
    ev = split_evidence(parts["evid"], parts["mark"])
    place = {"appx": [], "proj5": [], "cash6": [], "all": []}
    hide = []
    for n, where, body in ev:
        if where == "hide":
            hide.append(hidden(n, body))
        else:
            place[where].append(frag(n, label_q(body) if where in ("proj5", "cash6") else body))
    auto = split_auto(parts["auto"]) if parts.get("auto") else {}
    alerts = (I or {}).get("alerts") or []

    # ── 첫 화면 ──
    h = ["<style>%s</style><div class='tpw'>" % CSS]
    h.append("<span id='a-one'></span><h2 id='home' class='tp-h' style='border:0;padding:0;font-size:18px'>첫 화면 · 요약과 할 일</h2>")
    h.append(parts["guide"]("one"))
    h.append(_band(R))
    if cards:
        h.append("<div class='tp-h'>대표에게 나간 숫자 <small>대표 보고 첫 줄과 같은 값 · 누르면 그 주제로</small></div><div class='tp-cards'>")
        for c in cards:
            h.append("<a class='tp-card' href='#a-%s'><div class='tq-cl'>%s <span class='tq-tag'>대표 보고</span></div><div class='tq-cv'>%s</div>"
                     "<div class='tq-cf'>%s</div>%s</a>" % (c["topic"], esc(c["label"]), c["big"], c["foot"], _delta(c, prev)))
        h.append("</div>")
    h.append("<div class='tp-h'>주제별 신호 <small>판단 한 줄 · 숫자 · 지난번 대비 · 노랑은 할 일이 있는 것만 · ‘자료 없음’은 회색</small></div><div class='tp-sig'>")
    for x in L:
        na = _is_na(x)
        nt = len(by_topic.get(x["key"]) or [])
        cls = "nod" if na else ("bad" if x["lv"] == "bad" else ("wa" if x["lv"] == "wa" and nt else ("ok" if x["lv"] == "ok" else "")))
        head = x["facts"][0] if x["facts"] and not na else (x["sub"] if not na else (x["facts"] or [x["sub"]])[0])
        ch, cc = _change(x)
        tail = ("→ 6. 자료 할 일에 1줄" if na else ("할 일 %d" % nt if nt else "할 일 없음"))
        h.append("<a class='tq-sg v-%s' href='#a-%s'><div class='tq-sn'><span>%d. %s</span>%s</div><div class='tq-st'>%s</div>"
                 "<div class='tq-sv'>%s · %s</div><div class='tq-sf'><span class='%s'>%s</span> · %s</div></a>"
                 % (cls, x["key"], num_of[x["key"]], esc(x["name"]), _lv_badge("nod" if na else x["lv"]), esc(_short(head)),
                    esc(x["num"]), esc(x["sub"]), cc, esc(ch), esc(tail)))
    h.append("</div>")
    np_ = (R.get("todo_prev") or {}).get("items") or {}
    carried = sum(1 for it in items if it["id"] in np_)
    h.append("<div class='tp-h'>할 일 <small>%s</small></div>" % esc(
        ("지난번 할 일 %d건 중 %d건 처리 · %d건 이월" % (len(np_), len(done), carried)) if prev else "지난 기록 없음 (다음 보고부터 이월·처리 표시)"))
    h.append(_todo_table(items, done, True, num_of))
    h.append("<div class='tp-note'>할 일 = 위험 분석의 해결방안(높음 먼저) + 위험 분석에 없는 자동 분석 경보 ‘높음’ + 자료 없는 주제의 채울 일. "
             "담당 = 프로젝트 팀(프로젝트 일이면), 아니면 경영관리. 기한 = 다음 보고 날. 상태·메모는 창의 ‘확인할 것’ 화면(보고 할 일)에서 "
             "건마다 넣은 결정이 그대로 붙고, 처리하지 않은 것은 다음 보고에 ‘이월 n번째’로 남습니다.</div>")
    fl = parts.get("filing") or []
    h.append("<div class='tp-note'>이번 달 기한 신고: %s</div>" % (esc(" · ".join(fl)) + " (신고 도우미는 창에서 엶)" if fl else "해당 없음"))
    K = (I or {}).get("track") or {}
    tl = digest._track_line(K)
    h.append("<div class='tp-note'>지난 예상 대비 실제 오차(매번): %s → <a href='#auto15'>1. 자금 ③</a></div>"
             % esc(tl or ("지난 보고 기록이 아직 없어 견줄 수 없음" if not K.get("months") else "기준 안")))
    h.append("</div>")
    home = "".join(h)

    # ── 주제 장 ──
    topics = []
    for x in L:
        k = x["key"]
        na = _is_na(x)
        lv = "nod" if na else x["lv"]
        olds = [OLD_NAMES[c] for c in CHAPTERS[k] if c in parts["chap"]]
        t = []
        t.append("<h1 class='tp' id='t-%s'>%d. %s %s <small>예전 %s</small></h1>" % (k, num_of[k], esc(x["name"]), _lv_badge(lv),
                                                                                 esc("·".join(olds) + (" · A-3·A-4 일부" if k in ("cash", "proj", "pl", "ar", "other", "data") else ""))))
        # ① 결론
        ch, cc = _change(x)
        mine = [c for c in cards if c["topic"] == k]
        body = "<div class='tq-hl'>%s</div>" % esc((x["facts"] or [x["sub"]])[0] if x["facts"] else "%s %s" % (x["sub"], x["num"]))
        body += "<div><b>%s</b> · %s · %s</div>" % (esc(x["num"]), esc(x["sub"]), esc(ch))
        if len(x["facts"]) > 1:
            body += "<ul>%s</ul>" % "".join("<li>%s</li>" % esc(f) for f in x["facts"][1:6])
            if len(x["facts"]) > 6:
                body += "<div class='tp-note'>그 밖 %d건은 ④ 위험 표에</div>" % (len(x["facts"]) - 6)
        if mine:
            body += "<div class='tp-note'>대표 보고 숫자: %s</div>" % " · ".join(
                "%s <b>%s</b>" % (esc(c["label"]), re.sub(r"<[^>]+>", "", c["big"])) for c in mine)
        t.append(_layer(1, body, "신호 기준은 11/12 그대로", extra=" v-" + lv))
        # ② 할 일
        t.append(_layer(2, _todo_table(by_topic[k], done_by[k], False, num_of), "결정·메모는 첫 화면과 같은 칸"))
        if not x["open2"]:
            t.append("<button type='button' class='tpfold-btn' data-c='③~⑥ 펼치기 (지난번과 같고 할 일 없어 접어 둠)'>"
                     "③~⑥ 펼치기 (지난번과 같고 할 일 없어 접어 둠)</button>")
        # ③ 바뀐 것
        body = "<div>신호: %s</div>" % esc(ch)
        for n_ in sorted(i for i, (tk, ly) in AUTO_PLACE.items() if tk == k and ly == 3):
            if n_ in auto:
                body += ("<span id='auto15'></span>" if n_ == 15 else "") + relabel_auto(auto.pop(n_))
        note3 = "예전 자동 분석 2·15번 (예측 오차는 늘 펼침)" if k == "cash" else ""
        t.append(_layer(3, body, note3, lx=True))
        # ④ 자동 분석 · 위험
        rs = [r for r in R.get("risks") or [] if RISK_TOPIC.get(r["area"], "data") == k]
        body = ""
        if rs:
            body += ("<div class='tw'><table class='risk'><thead><tr><th>등급</th><th>영역</th><th>근거 (숫자)</th><th>해결방안</th></tr></thead>"
                     "<tbody>%s</tbody></table></div>" % "".join(
                         '<tr class="%s"><td class="tq-lv">%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                         % ("h" if r["level"] == "높음" else "", esc(r["level"]), esc(r["area"]), esc(r["fact"]), esc(r["action"])) for r in rs))
        al = [(lv_, a) for lv_, a in alerts if ("cash" if "여유 자금" in a else "proj") == k]
        if al:
            body += "<div class='tp-note'><b>자동 분석 경보</b></div><ul>%s</ul>" % "".join("<li>[%s] %s</li>" % (esc(a), esc(b)) for a, b in al)
        hit, empty = [], []
        for n_ in sorted(i for i, (tk, ly) in AUTO_PLACE.items() if tk == k and ly == 4):
            if n_ in auto:
                (empty if _is_empty_piece(auto[n_]) else hit).append((n_, auto.pop(n_)))
        if k == "cash" and 0 in auto:   # 자동 분석을 계산하지 못함
            body += auto.pop(0)
        body += "".join(relabel_auto(p) for _, p in hit)
        if empty:
            names = " · ".join("%d번 %s" % (n_, re.sub(r"<[^>]+>", "", re.search(r"<h3>\d+\. (.*?)</h3>", p).group(1)))
                               for n_, p in empty)
            body += ("<div class='ynone'><span class='yn'>걸린 것 없음: %s</span><button type='button' class='ynone-btn'>펼치기</button>"
                     "<div class='ypiece'>%s</div></div>" % (esc(names), "".join(relabel_auto(p) for _, p in empty)))
        if not body:
            body = "<div class='tp-note'>이 주제에 걸린 위험·자동 분석 없음</div>"
        nums = sorted(i for i, (tk, ly) in AUTO_PLACE.items() if tk == k and ly == 4)
        t.append(_layer(4, body, "예전 A-3 위험 분석%s" % ((" · A-4 자동 분석 " + "·".join(map(str, nums)) + "번") if nums else ""), lx=True))
        # ⑤ 상세 표
        body = ""
        if k == "proj":
            body += "".join(fs % p for p in place["proj5"])
        for c in CHAPTERS[k]:
            if c in parts["chap"]:
                n_ = parts["order"][c]
                body += "<span id='a-%s'></span>%s%s" % (c, parts["guide"](c), frag(n_, label_chapter(parts["chap"][c], OLD_NAMES[c])) if n_ else parts["chap"][c])
        t.append(_layer(5, body, "예전 %s — 표는 지금 그대로" % "·".join(olds), lx=True, cls=" ly5"))
        # ⑥ 근거
        body = _evidence_links(R, k)
        if k == "cash":
            body += "".join(fs % p for p in place["cash6"])
        t.append(_layer(6, body or "<div class='tp-note'>이 주제를 가리키는 근거 번호 없음 (표가 근거)</div>",
                        "대표가 물어볼 때 낼 자료", lx=True))
        nt = len(by_topic[k]) + (parts.get("recon_diff") or 0 if k == "data" else 0)   # 자료 대조 '다름' 줄 수도 목록 숫자에 (예전 B-7-1 목록 숫자)
        badge, bkind = (("자료 없음", "nod") if na else ((nt, "wa" if x["lv"] != "bad" else "") if nt else (None, "")))
        topics.append((k, "%d. %s" % (num_of[k], x["name"]), "주제 (신호등 순서)", "".join(t), badge, bkind, lv, not x["open2"]))
    # 자동 분석 중 남은 것 (번호 표에 없는 새 분석 — 빠지지 않게 자금 ④ 뒤 대신 전체 표 모음에)
    left_auto = "".join(auto[n_] for n_ in sorted(auto))

    # ── 정기 ──
    per = [(k_, lab, "정기 (해당 달에만)", parts["guide"](k_) + b, None, "", None, False) for k_, lab, b in parts["periodic"]]

    # ── 부록 ──
    a1 = (parts["guide"]("sum") + frag(10, parts["summ"]) + "<span id='a-ev'></span>"
          + "".join(fs % p for p in place["appx"]))
    a3 = ("<h2 id='allt'>전체 표 모음</h2>" + parts["guide"]("risk") + "".join(place["all"])
          + "<span id='a-risk'></span>" + frag(30, parts["risk"]) + "<span id='a-auto'></span>" + _old_index(parts, keys, num_of) + left_auto)
    appx = [("sum", "대표가 본 화면", "부록 (지금 내용 빠짐없이)", a1, None, "", None, False),
            ("docs", "요청 자료 전부", "부록 (지금 내용 빠짐없이)", parts["docs"], None, "", None, False),
            ("all", "전체 표 모음", "부록 (지금 내용 빠짐없이)", a3, None, "", None, False)]
    first = [("home", "요약 · 할 일", "첫 화면", home, len(items) or None, "wa" if items else "", None, False)]
    return first + topics + per + appx, "".join(hide)


def _layer(i, body, note="", lx=False, cls="", extra=""):
    return ("<div class='tq-ly l%d%s%s%s'><div class='tq-lh'><span>%s %s</span><small>%s</small></div><div class='tq-lb'>%s</div></div>"
            % (i, " lx" if lx else "", cls, extra, CIRCLE[i - 1], LAYERS[i - 1], esc(note), body))


def _evidence_links(R, k):
    """이 주제를 가리키는 근거 번호 (대표 보고 숫자 옆 번호) -> 링크 목록."""
    try:
        from .render import evidence_index
        idx = evidence_index(R)
    except Exception:
        return ""
    mine = []
    for n, title, where in idx:
        if where == "block":
            topic = "pl" if n.startswith("6") else "cash"
            href = "ev-%s" % n
        else:
            topic = next((t for t, cs in CHAPTERS.items() if where in cs), None)
            href = where
        if topic == k:
            mine.append("<li><a href='#%s'>근거 %s</a> · %s</li>" % (esc(href), esc(n), esc(title)))
    return ("<ul style='margin:2px 0;padding-left:18px'>%s</ul>" % "".join(mine)) if mine else ""


def _old_index(parts, keys, num_of):
    """옛 번호 → 새 자리 (몇 달 동안 같이 적음)."""
    rows = [("1쪽 요약 · 본문", "<a href='#a-home'>첫 화면</a> · 각 주제 ①"),
            ("자료 안내 (요청 자료 전부)", "<a href='#a-docs'>부록 · 요청 자료 전부</a>"),
            ("A-1 대표 보고 화면", "<a href='#a-sum'>부록 · 대표가 본 화면</a>"),
            ("A-2 근거자료 · 확인할 것", "<a href='#a-ev'>대표가 본 화면 아래 근거 묶음</a> · 프로젝트별 원가 → 2 ⑤ · 안 들어간 것 → 1 ⑥ · 할 일 → 첫 화면"),
            ("A-3 위험 분석·해결방안", "<a href='#risk'>이 장의 전체 표</a> · 각 주제 ④"),
            ("A-4 자동 분석 (1~15)", "1 경보 → 해당 주제 ④ · 2·15 → 자금 ③ · 3·5·6 → 자금 ④ · 4·13 → 매출·손익 ④ · 12 → 프로젝트 예산 ④ · "
                                  "7·10·11·14 → 계산서·수금 ④ · 8 → 프로젝트 밖 지급 ④ · 9 → 자료·지급 관리 ④")]
    for t in keys:
        for c in CHAPTERS[t]:
            if c in parts["chap"]:
                rows.append(("%s" % OLD_NAMES[c], "<a href='#a-%s'>%d. %s ⑤</a>" % (c, num_of[t], esc(TOPIC_NAME[t]))))
    rows.append(("부록 C (분기·반기·결산 준비)", "정기 장"))
    return ("<h3 id='oldmap'>옛 번호 찾기 (지난 보고와 맞춰 볼 때)</h3><div class='tw'><table class='pt td nofold'><thead><tr><th>예전 자리</th>"
            "<th>새 자리</th></tr></thead><tbody>%s</tbody></table></div>" % "".join(
                "<tr><td class='n'>%s</td><td>%s</td></tr>" % (esc(a), b) for a, b in rows))
