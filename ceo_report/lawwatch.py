"""세법 개정 확인 받기 (사용자 2026-11-12: 프로그램이 인터넷에서 읽어 오게).

국가법령정보센터 Open API(공식, 무료 — open.law.go.kr 이용 신청 후 받은 OC 아이디 필요)에서 우리가 쓰는 조문만 받아
  1) 지난번 받은 조문과 비교해 바뀌었으면 '개정됨'으로 표시하고,
  2) 조문 속 금액·비율(예: '1천450만원', '100분의 7')을 읽어 지금 값이 그대로 있는지 본다.
바뀐 값은 자동으로 쓰지 않는다: 창 '세법 기준 확인'에서 확인(또는 세무사 값 입력)해야 계산에 들어간다(taxlaw.value 가 막음).
뉴스·블로그는 숫자가 엇갈려 읽지 않는다. 조문 번호는 2026-11 기준이며, 법이 조문을 옮기면 '못 찾음'으로 알린다.
※ 2026-11-12 작성 때 작업 환경에서 law.go.kr 접속이 막혀 실제 응답 모양은 PC에서 확인 예정 — 응답 읽기는 너그럽게 짰다.
"""
import datetime as dt
import hashlib
import json
import os
import re
import urllib.parse
import threading
import urllib.request

FILE = "세법조문.json"
BASE = "https://www.law.go.kr/DRF/"
# (taxlaw 키들, 법령 이름, 조, 가지)
WATCH = [
    (("법인세율",), "법인세법", 55, 0),
    (("접대비기본한도", "접대비수입비율"), "법인세법", 25, 0),
    (("대손충당금률",), "법인세법 시행령", 61, 0),
    (("승용차상각한도", "승용차기록없음한도"), "법인세법 시행령", 50, 2),
    (("인정이자율",), "법인세법 시행규칙", 43, 0),
    (("최저한세율",), "조세특례제한법", 132, 0),
    (("창업감면_과밀밖", "창업감면_과밀밖청년", "창업감면_과밀안청년"), "조세특례제한법", 6, 0),
    (("고용공제_수도권", "고용공제_지방", "고용공제_수도권청년", "고용공제_지방청년"), "조세특례제한법", 29, 8),
    (("금융소득기준",), "소득세법", 14, 0),
    (("배당원천세율",), "소득세법", 129, 0),
    (("건강보험료율",), "국민건강보험법 시행령", 44, 0),
    # 노동·급여 (사용자 2026-11-12)
    (("가산율",), "근로기준법", 56, 0),
    (("국민연금요율",), "국민연금법", 88, 0),
    (("장기요양비율",), "노인장기요양보험법 시행령", 4, 0),
    (("고용보험요율",), "고용보험 및 산업재해보상보험의 보험료징수 등에 관한 법률 시행령", 12, 0),
    (("식대비과세",), "소득세법", 12, 0),   # 2026-11-17: 시행령 17조의2는 이제 출산지원금 → 법 12조 3호 러목 '월 20만원 이하의 식사대'
    (("최저시급",), "최저임금 고시", 0, 0),   # 행정규칙(고시): 이름이 해마다 바뀌어 '최저임금'으로 찾아 가장 최근 것
]
ADMRUL = {"최저임금 고시": "최저임금"}   # 법령이 아니라 고시(행정규칙)로 찾는 것


def _jo(n, sub):
    return "%04d%02d" % (n, sub)


def jo_name(n, sub):
    return "%d조%s" % (n, "의%d" % sub if sub else "")


# ───────────── 조문 속 숫자 읽기 ─────────────
_UNITS = (("조", 10 ** 12), ("억", 10 ** 8), ("만", 10 ** 4))


def kor_amount(text):
    """'1천450만원' '3천600만원' '800만원' '2억원' → 원 (int). 못 읽으면 None."""
    t = re.sub(r"[\s,]", "", text).replace("원", "")
    total, rest = 0, t
    for u, mul in _UNITS:
        if u in rest:
            head, rest = rest.split(u, 1)
            total += _small(head) * mul
    if rest:
        total += _small(rest)
    return total or None


def _small(t):
    """'1천450' → 1450, '800' → 800, '3천' → 3000, '1천5백' → 1500 (2026-11-17: 시행령 50조의2 '1천5백만원')."""
    if not t:
        return 1
    m = re.match(r"^(?:(\d*)천)?(?:(\d*)백)?(?:(\d*)십)?(\d*)$", t)
    if not m:
        return 0
    v = 0
    for g, unit, mark in ((m.group(1), 1000, "천"), (m.group(2), 100, "백"), (m.group(3), 10, "십")):
        if g is not None and (g or mark in t):
            v += int(g or 1) * unit
    return v + int(m.group(4) or 0)


def numbers(text):
    """조문 글 → {'원': [금액...], '비율': [비율...]}."""
    amounts = [kor_amount(m) for m in re.findall(r"[\d,]*(?:\d+[조억만천백]|[조억만천백]\d)[\d조억만천백,]*원", text)]
    amounts += [int(m.replace(",", "")) for m in re.findall(r"(\d{1,3}(?:,\d{3})+)원", text)]
    ratios = []
    for den, num in re.findall(r"(100|1천|1만|1,000|10,000)분의\s*(\d+(?:\.\d+)?)", text):
        d = {"100": 100, "1천": 1000, "1,000": 1000, "1만": 10000, "10,000": 10000}[den]
        ratios.append(float(num) / d)
    ratios += [float(p) / 100 for p in re.findall(r"(\d+(?:\.\d+)?)\s*퍼센트", text)]
    return {"원": sorted(set(a for a in amounts if a)), "비율": sorted(set(round(r, 6) for r in ratios))}


# ───────────── 받기 ─────────────
# 2026-11-17: 브라우저와 같은 머리글로 묻는다 (기본 'Python-urllib' 은 사이트가 막는 일이 있음)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept": "application/json, text/plain, */*", "Referer": "https://www.law.go.kr/"}


def _get(url, opener=None, timeout=20):
    """JSON 응답 -> dict. 사이트가 JSON 대신 안내 화면(HTML)을 주면 그 글 앞부분을 넣어 오류로 알린다 (2026-11-17)."""
    if opener is None:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    else:
        with opener(url, timeout=timeout) as r:
            raw = r.read()
    text = raw.decode("utf-8", "replace").lstrip("\ufeff").strip()
    try:
        data = json.loads(text)
    except ValueError:
        plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))[:150]
        raise ValueError("JSON이 아닌 응답: %s" % plain)
    # 2026-11-17 PC 확인: Referer 가 없으면 HTTP 200 에 {"result": "사용자 정보 검증에 실패하였습니다.", "msg": …} 를 준다.
    # 예전엔 이걸 '법령 이름으로 찾지 못함'으로 넘겨 원인이 안 보였음 → 실패로 알린다
    if isinstance(data, dict) and isinstance(data.get("result"), str) and "실패" in data["result"]:
        raise ValueError("법령 사이트가 거절: %s %s" % (data["result"], data.get("msg") or ""))
    return data


def _walk(o):
    """응답 JSON 안의 모든 dict."""
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def _flat(v):
    """목내용처럼 글 목록 안에 목록이 든 것 → 글 목록 (2026-11-17 PC: 조특법 6조·29조의8, 소득세법 129조가 TypeError 로 실패)."""
    for x in v:
        if isinstance(x, list):
            yield from _flat(x)
        elif isinstance(x, str):
            yield x


def _texts(o):
    """'…내용' 키의 글을 모두 이어 붙임 (조문내용·항내용·호내용·목내용)."""
    out = []
    for d in _walk(o):
        for k, v in d.items():
            if "내용" in k and isinstance(v, (str, list)):
                out.append(" ".join(_flat(v)) if isinstance(v, list) else v)
    return "\n".join(x.strip() for x in out if x and x.strip())


def _in_force(cands, ref):
    """2차 P1-22 (2026-11-15): 여러 시행본 중 ref(YYYYMMDD) 에 시행 중인 것 = 시행일자 ≤ ref 중 가장 늦은 것. 없으면 가장 이른 것.
    예전엔 검색 결과의 첫 번째(또는 가장 늦은) 시행본을 골라, 아직 시행 전인 미래 시행본 조문과 올해 값을 맞춰 보았다."""
    if not cands:
        return None
    ok = [c for c in cands if c["시행일자"] and c["시행일자"] <= ref]
    if ok:
        return max(ok, key=lambda c: c["시행일자"])
    return min(cands, key=lambda c: c["시행일자"] or "99999999")


def find_admrul(oc, query, opener=None, ref=None):
    """고시(행정규칙) 중 이름에 query 가 든 것 → {mst(ID), 시행일자, 공포일자, kind} 또는 None.
    ref(YYYYMMDD)가 있으면 그날 시행 중인 것, 없으면 가장 최근 것."""
    q = urllib.parse.urlencode({"OC": oc, "target": "admrul", "type": "JSON", "query": query, "display": 20})
    data = _get(BASE + "lawSearch.do?" + q, opener)
    cands = []
    for d in _walk(data):
        nm = (d.get("행정규칙명") or "").strip()
        rid = d.get("행정규칙일련번호") or d.get("행정규칙ID") or d.get("ID")
        if query in nm and rid:
            day = str(d.get("시행일자") or d.get("발령일자") or "")
            cands.append({"mst": str(rid), "시행일자": day, "공포일자": str(d.get("발령일자") or ""), "kind": "admrul", "name": nm})
    # 2026-11-17 PC: '최저임금'으로 찾으면 통계 고시 등도 걸림 → 'YYYY년 적용 최저임금 고시'(안 고시 제외)를 그해 것으로
    year = (ref or dt.date.today().strftime("%Y%m%d"))[:4]
    exact = [c for c in cands if re.search(r"%s년\s*적용\s*%s\s*고시$" % (year, re.escape(query)), c.get("name", ""))]
    if exact:
        return exact[0]
    if ref:
        return _in_force(cands, ref)
    return max(cands, key=lambda c: c["시행일자"]) if cands else None


def find_law(oc, name, opener=None, ref=None):
    """법령 이름 → {mst, 시행일자, 공포일자} 또는 None. ref(YYYYMMDD)가 있으면 그날 시행 중인 시행본, 없으면 첫 번째."""
    q = urllib.parse.urlencode({"OC": oc, "target": "law", "type": "JSON", "query": name, "display": 20})
    data = _get(BASE + "lawSearch.do?" + q, opener)
    cands = []
    for d in _walk(data):
        nm = (d.get("법령명한글") or d.get("법령명") or "").strip()
        if nm.replace(" ", "") == name.replace(" ", "") and (d.get("법령일련번호") or d.get("MST")):
            c = {"mst": str(d.get("법령일련번호") or d.get("MST")), "시행일자": str(d.get("시행일자") or ""),
                 "공포일자": str(d.get("공포일자") or "")}
            if not ref:
                return c
            if c not in cands:
                cands.append(c)
    return _in_force(cands, ref) if ref else None


def fetch_article(oc, mst, n, sub, opener=None, kind="law"):
    if kind == "admrul":
        q = urllib.parse.urlencode({"OC": oc, "target": "admrul", "type": "JSON", "ID": mst})
        return _texts(_get(BASE + "lawService.do?" + q, opener))
    q = urllib.parse.urlencode({"OC": oc, "target": "law", "type": "JSON", "MST": mst, "JO": _jo(n, sub)})
    return _texts(_get(BASE + "lawService.do?" + q, opener))


def load(input_dir):
    path = os.path.join(input_dir, FILE)
    if not os.path.exists(path):
        return {"oc": "", "last": "", "items": {}}
    with open(path, encoding="utf-8") as f:
        S = json.load(f)
    S.setdefault("items", {})
    return S


_LOCK = threading.Lock()   # 2차 P1-23: 아이디 저장과 법령 받기 결과 저장이 서로 덮지 않게 (읽고-고치고-쓰기를 하나씩)


def save_oc(input_dir, oc):
    with _LOCK:
        S = load(input_dir)
        S["oc"] = (oc or "").strip()
        _write(input_dir, S)


def _write(input_dir, S):
    os.makedirs(input_dir, exist_ok=True)
    tmp = os.path.join(input_dir, FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(S, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(input_dir, FILE))


def check(input_dir, year, today=None, opener=None):
    """조문을 받아 비교 -> [(키들, 법령·조문, 상태 '같음'|'개정됨'|'처음 받음'|'못 찾음'|'실패', 시행일자, 값 확인 글)].
    상태가 '개정됨'이거나 지금 값이 조문에 안 보이면 taxlaw 가 그 키들을 '미확인'으로 본다."""
    from . import taxlaw
    today = today or dt.date.today()
    S = load(input_dir)
    if not S.get("oc"):
        raise ValueError("국가법령정보 Open API 아이디(OC)를 먼저 넣어 주세요 (open.law.go.kr 무료 신청)")
    out, laws, got = [], {}, {}
    ref = max(today, dt.date(int(year), 1, 1)).strftime("%Y%m%d") if str(year).isdigit() else today.strftime("%Y%m%d")
    for keys, name, n, sub in WATCH:
        tag = name if name in ADMRUL else "%s %s" % (name, jo_name(n, sub))
        try:
            if name not in laws:   # P1-22: 값을 쓰는 해(year)에 시행 중인 시행본 — 올해면 오늘, 다음 해면 그해 1월 1일
                laws[name] = (find_admrul(S["oc"], ADMRUL[name], opener, ref) if name in ADMRUL
                              else find_law(S["oc"], name, opener, ref))
            info = laws[name]
            if not info:
                out.append((keys, tag, "못 찾음", "", "법령 이름으로 찾지 못함"))
                continue
            text = fetch_article(S["oc"], info["mst"], n, sub, opener, info.get("kind", "law"))
        except Exception as e:   # 네트워크·응답 모양: 멈추지 않고 알림
            out.append((keys, tag, "실패", "", "%s: %s" % (type(e).__name__, e)))
            continue
        if not text:
            out.append((keys, tag, "못 찾음", info["시행일자"], "조문 글이 비어 있음 (조문 번호가 바뀌었을 수 있음)"))
            continue
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        old = S["items"].get(tag)
        state = "처음 받음" if not old else ("같음" if old.get("hash") == h else "개정됨")
        nums = numbers(text)
        miss = []
        for k in keys:
            v = taxlaw.value(input_dir, year, k)[0]
            if isinstance(v, (int, float)) and v and taxlaw.UNIT[k] in ("원", "비율"):
                pool = nums["원"] if taxlaw.UNIT[k] == "원" else nums["비율"]
                if not any(abs(p - v) < 1e-6 * max(1, abs(v)) for p in pool):
                    miss.append(taxlaw.LABEL[k])
        note = ("지금 값이 조문에 안 보임: %s · 조문 숫자 %s" % (", ".join(miss), _short(nums))) if miss else "지금 값이 조문에 있음"
        got[tag] = {"hash": h, "text": text[:4000], "시행일자": info["시행일자"], "공포일자": info["공포일자"],
                    "keys": list(keys), "seen": today.isoformat() if state != "같음" else (old or {}).get("seen", today.isoformat()),
                    "flag": bool(miss) or state == "개정됨" or bool((old or {}).get("flag")),
                    # 2026-11-17: '값이 조문에 안 보임'(표기 차이·부칙에 있는 값)과 실제 개정을 나눔. 확인한 값은 개정됐을 때만 다시 확인
                    "changed": today.isoformat() if state == "개정됨" else (old or {}).get("changed", ""),
                    "miss": miss}
        out.append((keys, tag, state, info["시행일자"], note))
    with _LOCK:   # P1-23: 받는 동안 바꾼 아이디를 되돌리지 않게, 저장 직전에 다시 읽어 받은 조문만 넣는다
        cur = load(input_dir)
        cur.setdefault("items", {}).update(got)
        # R11 (2026-11-15): 하나도 못 받았으면 '받은 날'을 남기지 않는다. 2차 P1-21: 통신·응답 실패가 하나라도 있으면 남기지 않는다
        # (예전엔 일부만 받아도 '받은 날'이 남아 1월·7월 자동 확인이 그달에 다시 하지 않았음). 이유는 파일로 남김
        if out and not any(st == "실패" for _, _, st, _, _ in out) and any(st != "못 찾음" for _, _, st, _, _ in out):
            cur["last"] = today.isoformat()
        cur["last_try"] = {"날": today.isoformat(), "받음": sum(1 for r in out if r[2] not in ("실패", "못 찾음")), "전체": len(out),
                           "실패": [("%s: %s" % (r[1], r[4]))[:300] for r in out if r[2] in ("실패", "못 찾음")][:20]}
        _write(input_dir, cur)
    return out


def _short(nums):
    a = ["{:,}원".format(x) for x in nums["원"][:6]]
    r = ["%g%%" % round(x * 100, 4) for x in nums["비율"][:6]]
    return ", ".join(a + r) or "없음"


def flags(input_dir):
    """개정됐거나 값이 안 보인 키 -> {키: (조문, 시행일자, 받은 날)}. taxlaw.value 가 확인일과 비교한다."""
    try:
        S = load(input_dir)
    except (OSError, ValueError):
        return {}
    out = {}
    for tag, it in S.get("items", {}).items():
        if it.get("flag"):
            for k in it.get("keys", []):
                out[k] = (tag, it.get("시행일자", ""), it.get("seen", ""), it.get("changed", ""))
    return out


def due(input_dir, today=None):
    """자동 확인할 때인가: 1월·7월이고 이번 달에 아직 안 받았으면 True (OC 있을 때만)."""
    today = today or dt.date.today()
    try:
        S = load(input_dir)
    except (OSError, ValueError):
        return False
    return bool(S.get("oc")) and today.month in (1, 7) and not str(S.get("last", "")).startswith(today.strftime("%Y-%m"))
