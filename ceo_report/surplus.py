"""이익잉여금처분계산서 (사용자 2026-11-12: 미처분이익잉여금을 쉽게 설명하고 결산 처리 방법을 양식으로, 자료가 오면 바로 반영).

경영관리 보고에만 싣는다 (월간 10장, 연간 8장). 대표 보고에는 없음. 세무·법률 판단은 세무사 확인이 필요하다고 함께 적는다.

- 변환 쪽: build_table(books, cfg, asof) → 잉여금.csv (연도·항목·금액·상태·근거).
  · 끝난 해: 분개장 결산 전표(잉여금관련전표 등)에서 미처분이익잉여금으로 옮겨진 금액 = 그 해 당기순이익 (확정).
  · 아직 결산 안 한 해: 법인세 예상(corptax.from_journal)과 같은 계산 = 과세표준 − 법인세 − 지방소득세 (예상).
  · 처분: 결산 전표가 아닌 전표에서 이익준비금·미지급배당금·적립금으로 옮긴 금액 (주총일 전표).
  · 전기이월: 분개장에 전기이월 줄이 있으면 그것, 없으면 회사 첫해(FOUNDED)부터 분개장이 있을 때만 앞 해들로 계산.
    첫해 분개장이 없고 전기이월 줄도 없으면 '모름'으로 둔다 (지어내지 않음).
- 위하고 결산 화면 원본(확장 '결산 자료 받기', 수집\\위하고\\*결산_*.json)은 아직 응답 모양 확인 전이라 목록만 알린다.
- 보고 쪽: load(input_dir) → 줄, for_report(input_dir, year) → 숫자, render(S) → 경영관리 보고 한 영역.
"""
import collections
import csv
import datetime as dt
import os
import re

from .util import esc

FILE = "잉여금.csv"
KEYS = ["연도", "항목", "금액", "상태", "근거"]
FOUNDED = 2025   # 회사 첫 사업연도 (사용자 2026-11-12 "2025년부터 시작했어")
RAW_PREFIX = "결산_"   # 확장이 저장하는 결산 화면 원본 파일 이름에 들어가는 말

# 줄 항목 (양식 순서)
ITEMS = ["전기이월", "중간배당", "당기순이익", "이입액", "이익준비금", "배당금", "임의적립금"]


def _sq(text):
    return re.sub(r"\s+", "", str(text or ""))


def group_of(name):
    """계정 이름 → 잉여금 묶음: 'retained'(미처분·이월이익잉여금·미처리결손금) · 'legal'(이익준비금) · 'voluntary'(적립금)
    · 'dividend'(미지급배당금) · 'interim'(중간배당) · None."""
    n = _sq(name)
    if "중간배당" in n:
        return "interim"
    if "미지급배당" in n:
        return "dividend"
    if "이익준비금" in n:
        return "legal"
    if "적립금" in n:
        return "voluntary"
    if "이익잉여금" in n or "결손금" in n:
        return "retained"
    return None


def _amt(ln):
    return (ln.get("credit") or 0) - (ln.get("debit") or 0)   # 대변 − 차변 (잉여금이 늘면 +)


def _is_opening(ln):
    return any(w in _sq(ln.get("sort")) + _sq(ln.get("memo")) for w in ("전기이월", "기초잔액"))


def collect(journal, closing_sorts):
    """분개장 → {연도: {항목: 금액}}, 처음 연도. 잉여금 계정 줄만 본다."""
    closing = set(_sq(s) for s in closing_sorts)
    years = collections.defaultdict(lambda: collections.defaultdict(int))
    seen_years = set()
    for ln in journal:
        d = ln.get("date")
        if d is None:
            continue
        seen_years.add(d.year)
        g = group_of(ln.get("account"))
        if g is None:
            continue
        y, a = years[d.year], _amt(ln)
        if _is_opening(ln):
            if g == "retained":
                y["전기이월줄"] += a
            continue
        if _sq(ln.get("sort")) in closing or (g == "retained" and (d.month, d.day) == (12, 31)):
            # 결산 전표 (유형 글자가 없어도 12/31 미처분이익잉여금 줄은 손익 대체로 본다: 처분은 주총일에 기록됨)
            if g == "retained":
                y["결산이익"] += a
                y["결산있음"] = 1
            continue
        if g == "legal":
            y["이익준비금"] += a
        elif g == "voluntary":
            if a >= 0:
                y["임의적립금"] += a
            else:
                y["이입액"] += -a
        elif g == "dividend" and a > 0:
            y["배당금"] += a
        elif g == "interim":
            y["중간배당"] += -a
    return years, (min(seen_years) if seen_years else None)


def balances(journal, first_year):
    """연말 자본금·이익준비금 잔액 -> {연도: {"자본금": v, "이익준비금잔액": v}}.
    분개장이 회사 첫해(FOUNDED)부터 있을 때만 (전기이월 줄로 시작 잔액이 있으면 그 해부터) 계산. 모르면 빈 dict."""
    per = collections.defaultdict(lambda: [0, 0, False])   # 연도 -> [자본금 변동, 이익준비금 변동, 전기이월 줄 있음]
    for ln in journal:
        d = ln.get("date")
        if d is None:
            continue
        n = _sq(ln.get("account"))
        k = 0 if n == "자본금" else (1 if group_of(n) == "legal" else None)
        if k is None:
            continue
        per[d.year][k] += _amt(ln)
        if _is_opening(ln):
            per[d.year][2] = True
    ys = sorted(set(per) | ({first_year} if first_year else set()))
    if not ys:
        return {}
    start = None
    if first_year is not None and first_year <= FOUNDED:
        start = ys[0]
    else:
        start = next((y for y in ys if per[y][2]), None)   # 전기이월 줄이 있는 해부터
    if start is None:
        return {}
    out, cap, res = {}, 0, 0
    for y in range(start, ys[-1] + 1):
        cap, res = cap + per[y][0], res + per[y][1]
        out[y] = {"자본금": cap, "이익준비금잔액": res}
    return out


def estimate(journal, cfg, asof):
    """아직 결산 안 한 해의 당기순이익 예상 -> (연도, 금액, 근거) 또는 None. 법인세 예상과 같은 계산."""
    from . import corptax
    try:
        rows, _ = corptax.from_journal(journal, cfg, asof)
    except Exception:   # 장부가 모자라면 예상하지 않는다
        return None
    corp = [r for r in rows if r.get("세목") == "법인세"]
    if not corp or not corp[0].get("과세표준"):
        return None
    r = corp[0]
    base, tax = int(r["과세표준"]), int(r.get("산출세액") or 0)
    local = int(tax * corptax.LOCAL_RATE)
    ym = corptax._last_full_month(asof)
    why = ("%s년 1~%d월 장부: %s → 당기순이익 = 과세표준 − 법인세 %s − 지방소득세 %s"
           % (ym[:4], int(ym[5:]), (r.get("근거") or "").split(" → ")[0], "{:,}".format(tax), "{:,}".format(local)))
    return int(ym[:4]), base - tax - local, why


def statements(years, first_year, est):
    """연도별 처분계산서 -> [{year, 상태, 항목...}] (오래된 해부터). est = estimate() 결과."""
    ys = set(y for y, v in years.items() if v)
    if est:
        ys.add(est[0])
    if not ys:
        return []
    out, carry, carry_known = [], 0, True
    # 처분은 다음 해 주총에 기록된다: Y 해 계산서의 처분 = Y+1 해에 기록된 처분 전표
    for y in range(min(ys), max(ys) + 1):
        v = years.get(y, {})
        st = {"year": y, "why": {}}
        if v.get("전기이월줄"):
            open_, open_known = v["전기이월줄"], True
            st["why"]["전기이월"] = "분개장 전기이월 줄"
        elif y == min(ys) and first_year is not None and first_year <= FOUNDED:
            open_, open_known = 0, True
            st["why"]["전기이월"] = "회사 첫해 (%d년)" % FOUNDED
        elif y == min(ys):
            open_, open_known = None, False
            st["why"]["전기이월"] = "%d년 이전 분개장·재무상태표 없음" % y
        else:
            open_, open_known = (carry if carry_known else None), carry_known
            st["why"]["전기이월"] = "%d년 계산서의 차기이월" % (y - 1) if carry_known else "앞 해 금액 모름"
        if v.get("결산있음"):
            ni, ni_state = v["결산이익"], "확정"
            st["why"]["당기순이익"] = "%d년 12월 결산 전표에서 미처분이익잉여금으로 옮긴 금액" % y
        elif est and est[0] == y:
            ni, ni_state = est[1], "예상"
            st["why"]["당기순이익"] = est[2]
        else:
            ni, ni_state = None, "모름"
            st["why"]["당기순이익"] = "결산 전표 없음"
        nxt = years.get(y + 1, {})
        disp = dict((k, nxt.get(k, 0)) for k in ("이익준비금", "배당금", "임의적립금", "이입액"))
        decided = any(disp.values())
        st.update(전기이월=open_, 중간배당=v.get("중간배당", 0), 당기순이익=ni, 상태=ni_state, **disp)
        st["처분결정"] = decided
        st["why"]["처분"] = ("%d년 주총 처분 전표" % (y + 1)) if decided else "아직 처분 전표 없음 (전액 이월로 표시)"
        first = None if open_ is None or ni is None else open_ - st["중간배당"] + ni
        st["미처분"] = first
        used = disp["이익준비금"] + disp["배당금"] + disp["임의적립금"]
        st["처분액"] = used
        st["차기이월"] = None if first is None else first + disp["이입액"] - used
        carry, carry_known = (st["차기이월"] or 0), st["차기이월"] is not None
        out.append(st)
    return out


def raw_files(wehago_dir):
    """확장이 받은 결산 화면 원본 파일 이름 목록 (응답 모양 확인 전이라 읽지는 않는다)."""
    try:
        return sorted(n for n in os.listdir(wehago_dir) if RAW_PREFIX in n and n.lower().endswith(".json"))
    except OSError:
        return []


def build_table(books, cfg, asof, wehago_dir=None):
    from .convert import Table
    if books.state != "ok" or not books.journal:
        return Table(FILE, KEYS, [], written=False, reason="분개장 없음 (기존 파일 그대로)")
    years, first = collect(books.journal, cfg.get("closing_sorts", ()))
    est = estimate(books.journal, cfg, asof)
    rows, notes = [], []
    bal = balances(books.journal, first)
    from . import taxbreak
    sig = taxbreak.assets_by_year(books.journal)
    EXTRA = ("자본금", "이익준비금잔액", "장비구입", "연구개발비")
    for st in statements(years, first, est):
        st.update(bal.get(st["year"], {}))
        eq, rd = sig.get(st["year"], (0, 0))
        st.update(장비구입=eq, 연구개발비=rd)
        for k in ITEMS + ["미처분", "처분액", "차기이월"] + list(EXTRA):
            if k in EXTRA and k not in st:
                continue
            v = st.get(k)
            state = "모름" if v is None else (st["상태"] if k in ("당기순이익", "미처분", "차기이월") else "확정")
            why = ("%d년 말 잔액 (분개장 누계)" % st["year"]) if k in ("자본금", "이익준비금잔액") else \
                ("%d년 분개장 차변 합 (법인세 공제 후보 판단용)" % st["year"]) if k in ("장비구입", "연구개발비") else st["why"].get(k) or (st["why"]["처분"] if k in ("이익준비금", "배당금", "임의적립금", "이입액", "처분액") else "")
            rows.append(dict(zip(KEYS, [str(st["year"]), k, "" if v is None else str(int(v)), state, why])))
        notes.append("%d년 처분계산서: 당기순이익 %s(%s), 차기이월 %s" % (
            st["year"], "모름" if st["당기순이익"] is None else "{:,}".format(st["당기순이익"]), st["상태"],
            "모름" if st["차기이월"] is None else "{:,}".format(st["차기이월"])))
    raws = raw_files(wehago_dir) if wehago_dir else []
    if raws:
        notes.append("위하고 결산 화면 원본 %d개 (%s) — 응답 모양 확인 뒤 대조에 씀" % (len(raws), ", ".join(raws[:5])))
    if not rows:
        return Table(FILE, KEYS, [], written=False, reason="잉여금 계산할 장부 없음 (기존 파일 그대로)")
    return Table(FILE, KEYS, rows, notes=notes)


# ───────────── 보고 쪽 ─────────────
def load(input_dir):
    """잉여금.csv → {연도: {항목: (금액|None, 상태, 근거)}}."""
    path = os.path.join(input_dir, FILE)
    if not os.path.exists(path):
        return None
    out = collections.defaultdict(dict)
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            try:
                y = int(r.get("연도") or "")
            except ValueError:
                continue
            t = (r.get("금액") or "").strip()
            try:
                v = int(float(t)) if t else None
            except ValueError:
                v = None
            out[y][(r.get("항목") or "").strip()] = (v, (r.get("상태") or "").strip(), (r.get("근거") or "").strip())
    return dict(out) or None


def for_report(input_dir, year, R=None):
    """보고서용: 그 해(없으면 가장 최근 해) 계산서 + 앞 해들 + 배당 계산(주주 있을 때) + 이번 시기 제안(월간 보고 R 있을 때).
    -> dict 또는 None."""
    S = load(input_dir)
    if not S:
        return None
    ys = sorted(S)
    y = year if year in S else ys[-1]
    out = {"year": y, "cur": S[y], "years": [(k, S[k]) for k in ys if k <= y], "input_dir": input_dir}
    from . import dividend
    first = S[y].get("미처분", (None,))[0]
    asof = R["asof"] if R else dt.date(y, 12, 31)
    try:
        cap, res = S[y].get("자본금", (None,))[0], S[y].get("이익준비금잔액", (None,))[0]
        out["div"] = dividend.plan(input_dir, asof, None if first is None else dividend.div_limit(first, cap, res),
                                   interim=(S.get(y + 1) or {}).get("중간배당", (0,))[0] or 0)   # 같은 해(지급 연도) 중간배당만 금융소득에 더함
    except (ValueError, OSError):
        out["div"] = None
    from . import taxbreak
    try:
        eq, rd = S[y].get("장비구입", (None,))[0], S[y].get("연구개발비", (None,))[0]
        out["tb"] = taxbreak.check(input_dir, y, dividend.read_settings(input_dir), [r["이름"] for r in dividend.read(input_dir)],
                                   None if eq is None else (eq, rd or 0))
    except (ValueError, OSError):
        out["tb"] = None
    from . import taxlaw
    out["law"] = taxlaw.status(input_dir, (R["asof"].year if R else y))
    if R is not None:
        out["advice"] = dividend.advise(R, out, out["div"], input_dir)
    return out


def W(v):
    return "모름" if v is None else "{:,}".format(int(v))


CSS = """<style>
.rex table.re{width:100%;border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums}
.rex table.re th{font-size:11.5px;color:var(--sub);font-weight:700;text-align:right;padding:4px 8px;border-bottom:1.5px solid var(--ink)}
.rex table.re th:first-child,.rex table.re th.l{text-align:left}
.rex table.re tr{break-inside:avoid}
.rex table.re td{padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top;text-align:right;white-space:nowrap}
.rex table.re td.l{text-align:left;white-space:normal}
.rex table.re tr.g td{font-weight:700;background:var(--soft,#f5f7fa)}
.rex table.re td .ex{display:block;font-size:10.8px;color:var(--sub);font-weight:400;line-height:1.45}
.rex .tag{display:inline-block;font-size:10.5px;padding:0 5px;border-radius:4px;border:1px solid var(--line);color:var(--sub);margin-left:4px}
.rex .tag.e{color:#8a5a00;border-color:#e0b860}.rex .tag.u{color:#c62828;border-color:#e8a0a0}
.rex .say{margin:6px 0 10px;line-height:1.6}
.rex ol.steps{margin:4px 0 10px 18px;line-height:1.6}
.rex .warn{font-size:11.5px;color:var(--sub);margin-top:8px}
</style>"""

# (항목, 양식 이름, 쉬운 뜻)
FORM = [("미처분", "Ⅰ. 미처분이익잉여금", "이번 주총에서 처리할 돈 전체", True),
        ("전기이월", "  1. 전기이월미처분이익잉여금", "작년까지 남긴 돈", False),
        ("중간배당", "  2. 중간배당액", "올해 중간에 미리 나눈 돈", False),
        ("당기순이익", "  3. 당기순이익", "올해 번 돈 (법인세까지 뺀 것)", False),
        ("이입액", "Ⅱ. 임의적립금 등의 이입액", "예전에 따로 둔 돈을 다시 푼 것", True),
        ("처분액", "Ⅲ. 이익잉여금처분액", "이번에 쓰기로 정한 돈", True),
        ("이익준비금", "  1. 이익준비금", "배당하면 법으로 꼭 쌓는 돈 (배당의 10% 이상)", False),
        ("배당금", "  2. 현금배당", "주주에게 줄 돈 (통장에서 나감)", False),
        ("임의적립금", "  3. 임의적립금", "‘사업 확장용’처럼 이름표를 붙여 둔 돈", False),
        ("차기이월", "Ⅳ. 차기이월미처분이익잉여금", "내년으로 넘어가는 돈 (Ⅰ + Ⅱ − Ⅲ)", True)]

CHOICES = [("이월 (그대로 둠)", "그대로", "현금이 회사에 남아 대출 만기·세금에 대비. 절차가 가장 간단",
            "오래 쌓이면 회사 주식 가치가 올라 나중에 주식을 넘길 때(증여·상속·양도) 세금이 커질 수 있음"),
           ("현금 배당", "줄어듦", "주주(대표) 개인 소득. 잉여금이 지나치게 쌓이는 것을 막음",
            "배당소득세 15.4% 원천징수, 연 금융소득 2천만 원 넘으면 종합과세. 배당의 10% 이상을 이익준비금으로 쌓아야 함(자본금의 절반까지)"),
           ("임의적립금", "그대로", "배당 대신 회사에 쓸 돈이라는 뜻을 장부에 남김", "세금 효과는 없고 장부 이름만 바뀜"),
           ("일부 배당 + 나머지 이월", "조금 줄어듦", "해마다 조금씩 나눠 세금과 주식 가치를 고르게 관리",
            "주주별 다른 소득과 함께 보고 금액을 정해야 함")]

STEPS = [("12월 31일", "장부 마감 — 올해 손익을 미처분이익잉여금으로 옮김 (위하고 잉여금관련전표)"),
         ("1월~2월 중순", "결산과 처분안 작성 — 세무사와 재무제표·이익잉여금처분계산서(안)를 만들고 처리 방법을 고름 (정관 39조: 주총 6주 전까지)"),
         ("3월 31일까지", "정기 주주총회 (정관 22조, 주주 전원 서면 동의로 갈음 가능) — 재무제표 승인, 이월·배당·적립·임원 보수 한도 확정. 이날 장부에 처분 전표를 넣음"),
         ("3월 31일", "법인세 신고·납부 (지방소득세는 4월 30일까지)"),
         ("주총 뒤 1달 안", "배당금 지급 (배당을 정한 경우만) — 15.4%를 떼고 지급, 다음 달 10일까지 원천세 신고·납부")]


def _tag(state):
    if state == "예상":
        return "<span class='tag e'>예상</span>"
    if state == "모름":
        return "<span class='tag u'>모름</span>"
    return ""


def render(S, brief=False):
    """경영관리 보고 한 영역 (HTML 조각). brief=True 면 감면 후보·세법 기준표를 뺀다 (따로 내는 설명 양식용)."""
    if not S:
        return ("<div class='note'>이익잉여금 자료 없음 — 위하고 분개장을 받아 '자료 변환'을 다시 하면 잉여금.csv 가 생깁니다.</div>")
    y, cur = S["year"], S["cur"]
    get = lambda k: cur.get(k, (None, "모름", ""))
    ni, first, carry, opening = get("당기순이익"), get("미처분"), get("차기이월"), get("전기이월")
    h = [CSS, "<div class='rex'>"]
    say = ["<b>미처분이익잉여금</b>은 회사가 지금까지 벌어서 아직 주주에게 나눠 주지도, 용도를 정해 두지도 않은 이익의 누적 금액입니다. "
           "통장에 있는 현금과는 다릅니다(번 돈 일부는 못 받은 매출 대금·선급금·대출 상환 등으로 나가 있음)."]
    say.append("<br><b>%d년</b> 당기순이익 <b>%s원</b>%s, 작년까지 남긴 돈 <b>%s원</b>%s → 이번 주총에서 처리할 돈 <b>%s원</b>%s."
               % (y, W(ni[0]), _tag(ni[1]), W(opening[0]), _tag(opening[1] if opening[0] is not None else "모름"),
                  W(first[0]), _tag(first[1])))
    h.append("<div class='say'>%s</div>" % "".join(say))
    # 양식
    h.append("<div class='q'>%d년 이익잉여금처분계산서%s <span class='z'>(처분 확정일: %d년 3월 정기 주주총회일 · 단위 원)</span></div>"
             % (y, "" if get("처분액")[0] else " (안: 전액 이월)", y + 1))
    h.append("<table class='re'><tr><th>항목</th><th class='l'>쉬운 뜻</th><th>금액</th><th class='l'>근거</th></tr>")
    for k, name, easy, bold in FORM:
        v, st, why = get(k)
        if k == "차기이월" and v is None and first[0] is not None and not get("처분액")[0]:
            v, st, why = first[0], first[1], "처분 전이라 전액 이월로 봄 (주총에서 처분을 정하면 바뀜)"
        h.append("<tr%s><td class='l'>%s</td><td class='l'>%s</td><td>%s%s</td><td class='l'><span class='ex'>%s</span></td></tr>"
                 % (" class='g'" if bold else "", esc(name.strip()), esc(easy), W(v), _tag(st if v is None or st == "예상" else ""),
                    esc(why)))
    h.append("</table>")
    # 지난 해들
    past = [(yy, d) for yy, d in S["years"] if yy < y]
    if past:
        h.append("<div class='q'>지난 해 처리</div><table class='re'><tr><th>연도</th><th>당기순이익</th><th>처분액(배당·적립)</th>"
                 "<th>차기이월</th></tr>")
        for yy, d in past:
            g = lambda k: d.get(k, (None, "", ""))
            h.append("<tr><td class='l'>%d년</td><td>%s%s</td><td>%s</td><td>%s</td></tr>"
                     % (yy, W(g("당기순이익")[0]), _tag(g("당기순이익")[1]), W(g("처분액")[0]), W(g("차기이월")[0])))
        h.append("</table>")
    # 이번 시기 제안 · 배당 권장액 (사용자 2026-11-12)
    from . import dividend
    from . import taxbreak
    h.append(dividend.advice_html(S.get("advice"), esc))
    if not brief:
        h.append(taxbreak.render(S.get("tb"), esc))
        from . import taxlaw
        h.append(taxlaw.render(S.get("law"), esc))
    h.append(dividend.render(S.get("div"), esc))
    # 정관 규칙 (사용자 2026-11-13: 정관 제공)
    from . import articles
    h.append(articles.render(dividend.read_settings(S["input_dir"]) if S.get("input_dir") else {}, esc))
    # 처리 순서
    h.append("<div class='q'>결산 때 처리 순서</div><ol class='steps'>")
    for when, what in STEPS:
        h.append("<li><b>%s</b> · %s</li>" % (esc(when), esc(what)))
    h.append("</ol>")
    # 처리 방법
    h.append("<div class='q'>처리 방법 4가지 (섞어서 쓸 수 있음)</div><table class='re'><tr><th>방법</th><th class='l'>통장 돈</th>"
             "<th class='l'>좋은 점</th><th class='l'>조심할 점</th></tr>")
    for a, b, c, d in CHOICES:
        h.append("<tr><td class='l'><b>%s</b></td><td class='l'>%s</td><td class='l'>%s</td><td class='l'>%s</td></tr>"
                 % (esc(a), esc(b), esc(c), esc(d)))
    h.append("</table>")
    h.append("<div class='warn'>배당은 법에서 정한 한도(배당가능이익) 안에서만 할 수 있습니다. 세율·한도·이익준비금·주총 절차는 세무사 확인이 필요합니다. "
             "‘예상’은 아직 결산 전 장부로 계산한 값이고, 12월 결산 전표가 들어오면 ‘확정’으로 바뀝니다.</div>")
    h.append("</div>")
    return "".join(h)


def live_line(S):
    """지금 현황 화면용 한 줄 (HTML) 또는 ''."""
    if not S:
        return ""
    cur = S["cur"]
    ni, first = cur.get("당기순이익", (None, "모름", "")), cur.get("미처분", (None, "모름", ""))
    return ("<div class='note'>이익잉여금: %d년 당기순이익 %s원%s · 이번 주총에서 처리할 미처분이익잉여금 %s원%s</div>"
            % (S["year"], W(ni[0]), _tag(ni[1]), W(first[0]), _tag(first[1])))


PAGE_CSS = """<style>
:root{--ink:#1d2433;--sub:#5b6577;--line:#dfe3ea;--soft:#f5f7fa}
@page{size:A4;margin:14mm 13mm}
body{background:#fff;color:var(--ink);font-family:'Malgun Gothic','맑은 고딕','Apple SD Gothic Neo',sans-serif;font-size:13px;line-height:1.55;margin:0 auto;max-width:860px;padding:18px 16px}
h1{font-size:20px;margin:0 0 2px}.meta{color:var(--sub);font-size:12px;margin-bottom:12px}
.big{display:flex;gap:10px;margin:10px 0 6px;flex-wrap:wrap}.big div{flex:1 1 180px;border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.big b{display:block;font-size:18px;font-variant-numeric:tabular-nums}.big span{font-size:11.5px;color:var(--sub)}
.verdict{border-left:4px solid #2656c5;background:var(--soft);padding:8px 12px;margin:10px 0}
.q{font-weight:700;font-size:14px;margin:16px 0 6px;break-after:avoid}.z{font-weight:400;color:var(--sub);font-size:11.5px}
.note{color:var(--sub);font-size:12px}
@media print{body{padding:0}.q{break-after:avoid}}
</style>"""


def page(S, asof, company=""):
    """이익잉여금 쉬운 설명·처분계산서·결산 처리 제안 한 장짜리 양식 (사용자 2026-11-13: 문서를 양식으로).
    -> 완성된 HTML 글 또는 None (잉여금 자료 없음)."""
    if not S:
        return None
    y, cur = S["year"], S["cur"]
    get = lambda k: cur.get(k, (None, "모름", ""))
    ni, opening, first = get("당기순이익"), get("전기이월"), get("미처분")
    A = S.get("advice")
    if A:
        head = ("배당 %s원 권장" % W(A["amount"]) if A["verdict"] == "배당" else
                ("이번엔 이월(다음 해로 넘김) 권장" if A["verdict"] == "이월" else "판단 보류 — 아래 '확인할 것'을 채우면 판단합니다"))
        why = " · ".join(esc(r) for r in (A.get("reasons") or [])[:3])
    else:
        head, why = "판단 전 — 월간 보고를 만들면 그때 자금 사정으로 제안합니다", ""
    h = ["<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
         "<title>%d년 이익잉여금 설명·처분안</title>" % y, PAGE_CSS, "</head><body>",
         "<h1>%d년 미처분이익잉여금 쉬운 설명과 결산 처리 제안</h1>" % y,
         "<div class='meta'>%s기준일 %s · 분개장으로 자동 계산 · 세무사 확인 필요</div>" % (esc(company) + " · " if company else "", asof.isoformat()),
         "<div class='big'><div><span>작년까지 남긴 돈 (전기이월)</span><b>%s원</b></div>"
         "<div><span>%d년 번 돈 (당기순이익)%s</span><b>%s원</b></div>"
         "<div><span>이번 주총에서 처리할 돈</span><b>%s원</b></div></div>"
         % (W(opening[0]), y, " · 예상" if ni[1] == "예상" else "", W(ni[0]), W(first[0])),
         "<div class='verdict'><b>제안:</b> %s%s</div>" % (esc(head), ("<br><span class='note'>%s</span>" % why) if why else ""),
         render(S, brief=True), "</body></html>"]
    return "".join(h)


def write_page(S, out_dir, asof, company=""):
    """출력/결산/<연도>_이익잉여금_설명.html 저장 -> 경로 또는 None."""
    html = page(S, asof, company)
    if not html:
        return None
    import os
    folder = os.path.join(out_dir, "결산")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "%d_이익잉여금_설명.html" % S["year"])
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path
