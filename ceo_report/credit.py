"""기업신용평가 미리보기 (사용자 2026-11-12: 결산 뒤 받는 기업신용평가를 프로그램으로 미리 해 보기).

평가 회사(NICE·한국기업데이터·이크레더블 등)의 모형은 공개되지 않아 등급은 '추정 범위'로만 보인다.
판정·점수·문구는 모두 아래 표의 규칙으로 만든다 (AI 없음). 기준값은 재무분석에서 널리 쓰이는 값 (사용자 2026-11-12: '보통 널리 쓰이는 값으로').

- 변환 쪽: build_table(books) → 계정잔액.csv (연월·계정마다 차변·대변 합, 맨 앞 '처음부터' 줄 = 잔액을 셀 수 있는가).
- 입력: 입력/신용평가.csv (항목,값) — 비재무 체크리스트, 대출 만기일, 작년에 받은 평가 결과. 창 '가끔 넣는 값' → '신용평가 체크리스트'.
- 보고 쪽: compute(input_dir, p1) → 숫자·판정·등급 범위·결산 전 할 일, render(C) → 경영관리 보고의 한 장.
  월간 경영관리 보고는 9월분 '결산 준비' 부록 C-5 로(사용자 2026-11-12 카드, 예전 11·12월), 연간 경영관리 보고에는 늘 싣는다.

잔액(재무상태표)은 분개장을 처음(설립·전기이월)부터 더해 계산한다. 자본 = 자산 − 부채 (결산 손익 대체 여부와 상관없이 맞는다).
"""
import collections
import csv
import datetime as dt
import os
import re

from .util import esc

FILE = "계정잔액.csv"
KEYS = ["연월", "계정코드", "계정", "차변", "대변"]
INPUT_FILE = "신용평가.csv"
INPUT_KEYS = ["항목", "값"]
FROM_START = "처음부터"

# ───────────── 기준 (널리 쓰이는 값) ─────────────
# (키, 영역, 이름, 계산, 방향 hi=클수록 좋음/lo=작을수록 좋음, (좋음, 보통, 주의) 경계, 단위, 무슨 뜻)
FIN = [
    ("debt", "안정성", "부채비율", "부채 ÷ 자본", "lo", (100, 200, 400), "%", "빌린 돈(부채)이 내 돈(자본)의 몇 %인지"),
    ("equity", "안정성", "자기자본비율", "자본 ÷ 총자산", "hi", (50, 30, 20), "%", "회사 재산 중 갚지 않아도 되는 내 돈의 비율"),
    ("borrow", "안정성", "차입금의존도", "차입금 ÷ 총자산", "lo", (20, 30, 50), "%", "은행 대출 등 이자 내는 빚에 얼마나 기대는지"),
    ("current", "안정성", "유동비율", "유동자산 ÷ 유동부채", "hi", (200, 120, 100), "%", "1년 안에 갚을 빚을 1년 안에 돈이 될 재산으로 낼 수 있는지"),
    ("opm", "수익성", "매출액영업이익률", "영업이익 ÷ 매출", "hi", (10, 5, 0), "%", "본업으로 매출의 몇 %를 남기는지"),
    ("icr", "수익성", "이자보상배율", "영업이익 ÷ 이자비용", "hi", (3, 1.5, 1), "배", "번 돈으로 이자를 몇 번 낼 수 있는지 (1배 미만이면 이자도 못 냄)"),
    ("fin", "수익성", "금융비용 대 매출", "이자비용 ÷ 매출", "lo", (2, 3, 5), "%", "매출 중 이자로 나가는 몫"),
    ("growth", "성장성", "매출액증가율", "올해 ÷ 작년 같은 기간 − 1", "hi", (10, 0, -10), "%", "매출이 작년보다 얼마나 늘었는지"),
    ("size", "성장성", "매출 규모 (연 환산)", "올해 매출 ÷ 한 해 중 지난 날 비율", "hi", (10_000_000_000, 3_000_000_000, 1_000_000_000), "원", "규모가 클수록 버티는 힘이 크다고 봄"),
    ("collect", "활동성", "대금 회수 날수", "계산서 발행 → 입금 (최근 3달 평균)", "lo", (60, 90, 120), "일", "매출 대금을 며칠 만에 받는지"),
    ("turn", "활동성", "총자산회전율", "매출(연 환산) ÷ 총자산", "hi", (1.5, 1.0, 0.5), "회", "가진 재산으로 매출을 얼마나 일으키는지"),
    ("ocf", "현금흐름", "본업 현금흐름", "현금흐름표 ① 본업 합계 (올해 누적)", "hi", None, "원", "이익이 실제 현금으로 들어오는지"),
]
AREA_W = collections.OrderedDict([("안정성", 30), ("수익성", 25), ("현금흐름", 20), ("활동성", 15), ("성장성", 10)])
FIN_W, NONFIN_W = 70, 30
LEVELS = ["좋음", "보통", "주의", "나쁨"]
PTS = {"좋음": 100, "보통": 60, "주의": 30, "나쁨": 0}
UNK_LO, UNK_MID, UNK_HI = 30, 60, 80   # 모르는 칸: 범위 아래·가운데·위로 볼 점수

# 등급 (위 → 아래). 점수 → 등급은 프로그램 기본값
NOTCHES = ["AAA", "AA+", "AA0", "AA-", "A+", "A0", "A-", "BBB+", "BBB0", "BBB-", "BB+", "BB0", "BB-",
           "B+", "B0", "B-", "CCC+", "CCC0", "CCC-", "CC", "C", "D"]
CUTS = [(95, "AA-"), (90, "A+"), (85, "A0"), (80, "A-"), (74, "BBB+"), (68, "BBB0"), (62, "BBB-"), (56, "BB+"),
        (50, "BB0"), (44, "BB-"), (38, "B+"), (32, "B0"), (26, "B-"), (0, "CCC+")]
CAP_DEFAULT = "B+"   # 연체·체납이 있으면 이 등급보다 높게 보지 않는다

# 비재무 체크리스트: (키, 이름, 선택지 또는 None(자유 입력), 왜 보나)
NONFIN = [
    ("age", "업력", None, "설립 뒤 햇수. 짧으면 쌓인 실적이 적어 불리"),
    ("ceo", "대표자 개인 신용점수", ("900 이상", "800~899", "800 미만"), "작은 회사는 대표 개인 신용이 크게 반영됨"),
    ("delinq", "최근 1년 금융 연체 (회사·대표)", ("없음", "있음"), "있으면 등급이 크게 깎임"),
    ("tax", "국세·지방세·4대보험 체납", ("없음", "있음"), "체납은 바로 감점"),
    ("suit", "소송·압류·가압류", ("없음", "있음"), "우발 위험"),
    ("exp", "대표자 동종업계 경력", None, "경영진 경험. 업력이 짧은 회사는 대표 경력을 크게 봄"),
    ("conc", "매출 거래처 쏠림", None, "한 곳에 쏠리면 그곳과 거래가 끊길 때 위험"),
    ("staff", "상시 직원 수", None, "규모·고용 안정"),
    ("cert", "인증 (벤처·이노비즈·메인비즈·여성기업 등)", None, "가점 요소"),
    ("audit", "결산 방식", ("세무사 결산", "외부감사"), "제출 자료의 신뢰도"),
    ("site", "사업장", ("임차", "자가"), "자가면 담보·안정성 가점"),
]
# 체크리스트 입력 항목 (입력/신용평가.csv 의 '항목' 칸)
INPUT_ITEMS = [
    ("설립일", "YYYY-MM-DD"), ("대표신용점수", "900 이상 / 800~899 / 800 미만"), ("금융연체", "없음 / 있음"),
    ("대표동종경력", "년 (예: 18.5)"), ("체납", "없음 / 있음"), ("소송압류", "없음 / 있음"), ("인증", "있으면 종류 (예: 벤처), 없으면 '없음'"),
    ("결산방식", "세무사 결산 / 외부감사"), ("사업장", "임차 / 자가 (비우면 장부의 보증금으로 판단)"),
    ("대출만기일", "가장 이른 장기 대출 만기 YYYY-MM-DD"),
    ("작년_평가사", "예: 이크레더블"), ("작년_평가일", "YYYY-MM-DD"), ("작년_결산연도", "예: 2025"),
    ("작년_등급", "예: BB+"), ("작년_현금흐름등급", "예: CR-3"),
    ("작년_부채비율", "%"), ("작년_자기자본비율", "%"), ("작년_차입금의존도", "%"), ("작년_유동비율", "%"),
    ("작년_영업이익률", "%"), ("작년_이자보상배율", "배"), ("작년_매출액", "원"),
    ("작년_총자산", "원 (평가서 요약 재무)"), ("작년_자기자본", "원 (평가서 요약 재무)"), ("작년_차입금", "원 (모르면 비움)"),
    ("작년_지적사항", "평가서에 적힌 약점 한 줄"),
]
LAST_KEYS = {"debt": "작년_부채비율", "equity": "작년_자기자본비율", "borrow": "작년_차입금의존도", "current": "작년_유동비율",
             "opm": "작년_영업이익률", "icr": "작년_이자보상배율"}


# ───────────── 변환 쪽 ─────────────
def _sq(text):
    return re.sub(r"\s+", "", str(text or ""))


def build_table(books):
    """계정잔액.csv: 분개장(지난 기수 포함, 결산 손익 줄 뺀 뒤)을 연월·계정마다 차변·대변 합으로. 맨 앞 줄 = 처음부터 여부."""
    from .convert import Table
    from .wehago import journal_from_start
    if books.state != "ok" or not books.journal:
        return Table(FILE, KEYS, [], written=False, reason="분개장 없음 (기존 파일 그대로)")
    agg = collections.OrderedDict()
    for ln in books.journal:
        if ln.get("date") is None:
            continue
        k = (ln["date"].strftime("%Y-%m"), _sq(ln.get("account_code")), _sq(ln.get("account")))
        a = agg.setdefault(k, [0, 0])
        a[0] += ln.get("debit") or 0
        a[1] += ln.get("credit") or 0
    start = journal_from_start(books.journal)
    out = [dict(zip(KEYS, [FROM_START, "", "예" if start else "아니오", "", ""]))]
    out += [dict(zip(KEYS, [ym, c, n, str(int(d)), str(int(cr))])) for (ym, c, n), (d, cr) in sorted(agg.items())]
    # 대출 줄 (2026-11-13 실제 2025 분개장: 적요 '[만기일자:YYYY.MM.DD]'): 결산일부터 1년 안 만기 금액을 대출별로 계산
    for ln in books.journal:
        code = _sq(ln.get("account_code"))
        if ln.get("date") is None or not code.startswith(LOAN_DETAIL_PREFIX):
            continue
        m = MATURITY.search(ln.get("memo") or "")
        mat = "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3))) if m else ""
        kind = "분할" if "분할" in (ln.get("memo") or "") or "할부" in (ln.get("memo") or "") else ("일시" if "일시" in (ln.get("memo") or "") else "")
        out.append(dict(zip(KEYS, [LOAN_ROW + ln["date"].isoformat(), code, "|".join([_sq(ln.get("vendor")), mat, kind]),
                                   str(int(ln.get("debit") or 0)), str(int(ln.get("credit") or 0))])))
    # 대출 연장 (2026-11-13 실제: 4/3 '대출연장보증료_기술보증기금대출_123456789012'): 적요의 대출 계좌번호로 대출을 찾아 연장 줄
    loan_vendors = set(_sq(ln.get("vendor")) for ln in books.journal if _sq(ln.get("account_code")).startswith(LOAN_DETAIL_PREFIX))
    acct = {}
    for ln in books.journal:
        if _sq(ln.get("vendor")) in loan_vendors:
            for n_ in re.findall(r"\d{9,}", ln.get("memo") or ""):
                acct.setdefault(n_, _sq(ln.get("vendor")))
    seen = set()
    for ln in books.journal:
        memo = ln.get("memo") or ""
        if ln.get("date") is None or "연장" not in memo:
            continue
        hit = [acct[n_] for n_ in re.findall(r"\d{9,}", memo) if n_ in acct]
        if hit and (ln["date"], hit[0]) not in seen:
            seen.add((ln["date"], hit[0]))
            out.append(dict(zip(KEYS, [LOAN_ROW + ln["date"].isoformat(), EXTEND, "|".join([hit[0], "", EXTEND]), "0", "0"])))
    yms = sorted(set(k[0] for k in agg))
    note = "계정잔액 %d줄 (%s ~ %s, %s)" % (len(out) - 1, yms[0] if yms else "", yms[-1] if yms else "",
                                         "처음부터 있음 — 재무상태표 계산 가능" if start else "처음부터가 아님 — 잔액 항목은 작년 분개장이 있어야 계산")
    return Table(FILE, KEYS, out, notes=[note])


# ───────────── 입력 ─────────────
def _read(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_inputs(input_dir):
    return dict(((r.get("항목") or "").strip(), (r.get("값") or "").strip()) for r in _read(os.path.join(input_dir, INPUT_FILE))
                if (r.get("항목") or "").strip())


def save_inputs(input_dir, values):
    """입력/신용평가.csv 를 values(dict) 로 바꾼다 (빈 값은 지움). INPUT_ITEMS 순서, 모르는 항목은 뒤에 그대로."""
    cur = read_inputs(input_dir)
    cur.update(dict((k, (v or "").strip()) for k, v in values.items()))
    order = [k for k, _ in INPUT_ITEMS] + sorted(k for k in cur if k not in dict(INPUT_ITEMS))
    path = os.path.join(input_dir, INPUT_FILE)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(INPUT_KEYS)
        for k in order:
            if cur.get(k):
                w.writerow([k, cur[k]])
    return path


def _num(text):
    t = str(text or "").replace(",", "").replace("%", "").replace("원", "").replace("배", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def _date(text):
    m = re.match(r"^\s*(\d{4})[-./](\d{1,2})[-./](\d{1,2})", str(text or ""))
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    except ValueError:
        return None


# ───────────── 장부 → 재무상태표·손익 ─────────────
def load(input_dir):
    rows = _read(os.path.join(input_dir, FILE))
    if not rows:
        return None
    start = any(r.get("연월") == FROM_START and r.get("계정") == "예" for r in rows)
    out, loans = [], []
    for r in rows:
        ym = r.get("연월") or ""
        if ym.startswith(LOAN_ROW):
            d_ = _date(ym[len(LOAN_ROW):])
            v, mat, kind = ((r.get("계정") or "") + "||").split("|")[:3]
            try:
                loans.append((d_, _sq(r.get("계정코드")), v, _date(mat), kind, int(float(r.get("차변") or 0)), int(float(r.get("대변") or 0))))
            except ValueError:
                pass
            continue
        if not re.match(r"^\d{4}-\d{2}$", r.get("연월") or ""):
            continue
        try:
            out.append((r["연월"], _sq(r.get("계정코드")), _sq(r.get("계정")), int(float(r.get("차변") or 0)), int(float(r.get("대변") or 0))))
        except ValueError:
            continue
    return {"start": start, "rows": out, "loans": loans}


def loans_at(L, asof, close):
    """asof 날 대출별 잔액과 결산일(close)부터 1년 안에 갚을 몫. -> [(거래처, 잔액, 만기, 방식, 1년 안 몫, 상태)].
    상태: '만기 지남'(만기가 asof 전인데 잔액 남음) · '1년 안' · '분할 일부' · '1년 넘음' · '만기 모름'."""
    by = collections.OrderedDict()
    for d_, code, v, mat, kind, dr, cr in (L or {}).get("loans", []):
        if d_ is None or d_ > asof:
            continue
        if code == EXTEND:   # 연장 보증료 등: 만기 앞뒤 3달 안이면 1년 연장으로 봄 (새 만기를 적요에 넣으면 그 날짜가 우선)
            x = by.get(v)
            if x and x["mat"] and abs((d_ - x["mat"]).days) <= 92:
                x["mat"], x["ext"] = dt.date(x["mat"].year + 1, x["mat"].month, min(x["mat"].day, 28 if x["mat"].month == 2 else x["mat"].day)), d_
            continue
        x = by.setdefault(v, {"bal": 0, "mat": None, "kind": "", "paid": [], "ext": None})
        x["bal"] += cr - dr
        if mat:
            x["mat"], x["ext"] = mat, None
        x["kind"] = kind or x["kind"]
        if dr > 0:
            x["paid"].append((d_, dr))
    out = []
    edge = dt.date(close.year + 1, close.month, close.day)
    for v, x in by.items():
        if x["bal"] <= 0:
            continue
        mat = x["mat"]
        if mat is None:
            cur, st = 0, "만기 모름"
        elif mat < asof:
            cur, st = x["bal"], "만기 지남"
        elif mat <= edge:
            cur, st = x["bal"], ("1년 안, %s 연장해 1년 늘었다고 봄" % x["ext"].isoformat() if x.get("ext") else "1년 안")
        elif x["kind"] == "분할":
            last = sorted(x["paid"])[-1][1] if x["paid"] else 0
            cur, st = min(x["bal"], last * 12), "분할 일부"   # 최근 한 달 원금 × 12 (다음 1년 낼 원금 근사)
        else:
            cur, st = 0, "1년 넘음"
        out.append((v, x["bal"], mat, x["kind"], cur, st))
    return out


def _kind(code, name):
    """계정 종류 (더존 코드 앞 3자리). ca 유동자산 · na 비유동자산 · cl 유동부채 · nl 비유동부채 · eq 자본 · 손익 rev/cogs/sga/nin/nout/tax."""
    m = re.match(r"^(\d{3})", code or "")
    if not m:
        return None
    n = int(m.group(1))
    if n >= 400 and "보증금" in name:   # 96200 임차보증금 (9로 시작해도 자산, 2026-11-12 확인)
        return "na"
    for lo, hi, k in ((101, 175, "ca"), (176, 250, "na"), (251, 290, "cl"), (291, 330, "nl"), (331, 399, "eq"),
                      (400, 450, "rev"), (451, 799, "cogs"), (800, 900, "sga"), (901, 930, "nin"), (931, 997, "nout"), (998, 999, "tax")):
        if lo <= n <= hi:
            return k
    return None


# 단기차입금·유동성장기부채·사채·장기차입금·가수금. 가수금(대표에게 빌린 돈)도 넣는다 (2026-11-13: 2025 NICE 평가서 차입금의존도 36.4% = 약 4억인데
# 이자보상배율 2,497배로 이자가 거의 없음 → 대표 가수금을 차입금으로 본 것으로 추정)
LOAN_PREFIX = ("257", "260", "264", "291", "293")
LOAN_DETAIL_PREFIX = ("260", "264", "291", "293")   # 대출별 만기를 보는 계정 (가수금 뺌)
LOAN_ROW = "대출:"
EXTEND = "연장"
MATURITY = re.compile(r"만기\s*일자?\s*[:：]\s*(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})")
LONG_LOAN_PREFIX = ("293",)
AR_PREFIX = ("108", "110")                   # 외상매출금(이 회사 '수입수수료미수금')·받을어음
SUSPENSE_PREFIX = ("257",)                   # 가수금
INTEREST_PREFIX = ("931",)


def balance_sheet(L, ym):
    """ym(YYYY-MM) 말 잔액. 처음부터가 아니면 None."""
    if not L or not L["start"]:
        return None
    b = collections.defaultdict(int)
    named = collections.defaultdict(int)
    for m, code, name, d, c in L["rows"]:
        if m > ym:
            continue
        k = _kind(code, name)
        if k in ("ca", "na"):
            b[k] += d - c
        elif k in ("cl", "nl"):
            b[k] += c - d
        for p, key in ((LOAN_PREFIX, "loan"), (LONG_LOAN_PREFIX, "long_loan"), (AR_PREFIX, "ar"), (SUSPENSE_PREFIX, "suspense")):
            if code.startswith(p):
                named[key] += c - d if key in ("loan", "long_loan", "suspense") else d - c
        if "보증금" in name and k == "na":
            named["deposit"] += d - c
    B = {"ca": b["ca"], "na": b["na"], "cl": b["cl"], "nl": b["nl"]}
    B["assets"] = B["ca"] + B["na"]
    B["liab"] = B["cl"] + B["nl"]
    B["equity"] = B["assets"] - B["liab"]
    B.update(named)
    return B


def moves(L, y, m_to, prefixes=None, name_word=None):
    """y년 1~m_to월 계정 증감 (차변 − 대변). 잔액을 몰라도 올해 늘고 준 것은 안다."""
    lo, hi = "%04d-01" % y, "%04d-%02d" % (y, m_to)
    return sum(d - c for m, code, name, d, c in (L or {}).get("rows", [])
               if lo <= m <= hi and ((prefixes and code.startswith(prefixes)) or (name_word and name_word in name)))


def balance_from_report(L, inp, y, mon):
    """분개장이 처음부터가 아닐 때 (사용자 2026-11-13: 작년 평가서): 작년 말 총자산·자기자본(평가서) + 올해 장부 증감.
    유동/비유동 나눔은 모름 → 유동비율은 계산하지 않는다. 차입금은 작년_차입금을 넣었을 때만."""
    ta, eq = _num(inp.get("작년_총자산")), _num(inp.get("작년_자기자본"))
    ly = int(_num(inp.get("작년_결산연도")) or 0)
    if not L or ta is None or eq is None or ly != y - 1:
        return None
    lo, hi = "%04d-01" % y, "%04d-%02d" % (y, mon)
    da = dl = 0
    loan = 0
    for m, code, name, d, c in L["rows"]:
        if not (lo <= m <= hi):
            continue
        k = _kind(code, name)
        if k in ("ca", "na"):
            da += d - c
        elif k in ("cl", "nl"):
            dl += c - d
        if code.startswith(LOAN_PREFIX):
            loan += c - d
    B = {"ca": None, "na": None, "cl": None, "nl": None, "assets": int(ta) + da, "liab": int(ta - eq) + dl, "approx": True,
         "open_assets": int(ta), "open_equity": int(eq), "d_assets": da, "d_liab": dl}
    B["equity"] = B["assets"] - B["liab"]
    lo_ = _num(inp.get("작년_차입금"))
    if lo_ is not None:
        B["loan"] = int(lo_) + loan
    return B


def income(L, y, m_from, m_to):
    """y년 m_from~m_to 월 손익. 그 달들 자료가 하나도 없으면 None."""
    if not L:
        return None
    lo, hi = "%04d-%02d" % (y, m_from), "%04d-%02d" % (y, m_to)
    s = collections.defaultdict(int)
    months = set()
    for m, code, name, d, c in L["rows"]:
        if not (lo <= m <= hi):
            continue
        k = _kind(code, name)
        if k in ("rev", "nin"):
            s[k] += c - d
        elif k in ("cogs", "sga", "nout", "tax"):
            s[k] += d - c
        if code.startswith(INTEREST_PREFIX):
            s["interest"] += d - c
        if k:
            months.add(m)
    if not months:
        return None
    P = dict(s)
    for k in ("rev", "cogs", "sga", "nin", "nout", "tax", "interest"):
        P.setdefault(k, 0)
    P["op"] = P["rev"] - P["cogs"] - P["sga"]
    P["pre"] = P["op"] + P["nin"] - P["nout"]
    P["months"] = sorted(months)
    return P


# ───────────── 판정 ─────────────
def judge(key, v):
    spec = dict((f[0], f) for f in FIN)[key]
    if v is None:
        return None
    if key == "ocf":
        return "좋음" if v > 0 else "나쁨"
    g, o, w = spec[5]
    if spec[4] == "hi":
        return "좋음" if v >= g else ("보통" if v >= o else ("주의" if v >= w else "나쁨"))
    return "좋음" if v <= g else ("보통" if v <= o else ("주의" if v <= w else "나쁨"))


def fmt(key, v):
    if v is None:
        return "—"
    unit = dict((f[0], f) for f in FIN)[key][6]
    if unit == "원":
        return eok(int(v))
    if unit == "%":
        return "%.1f%%" % v
    if unit == "배":
        return "%.1f배" % v
    if unit == "회":
        return "%.2f회" % v
    return "%d%s" % (round(v), unit)


def eok(v):
    a, s = abs(v), "−" if v < 0 else ""
    if a >= 100_000_000:
        return s + ("%.2f" % (a / 1e8)).rstrip("0").rstrip(".") + "억"
    if a >= 10_000:
        return s + "{:,}만".format(int(round(a / 10000)))
    return s + "{:,}".format(a)


def threshold_text(key):
    spec = dict((f[0], f) for f in FIN)[key]
    if key == "ocf":
        return "플러스 좋음 / 마이너스 나쁨"
    g, o, w = spec[5]
    u = spec[6]
    f = (lambda x: eok(int(x))) if u == "원" else (lambda x: ("%g" % x) + u)
    if spec[4] == "hi":
        return "%s 이상 좋음 · %s 미만 주의 · %s 미만 나쁨" % (f(g), f(o), f(w))
    return "%s 이하 좋음 · %s 넘음 주의 · %s 넘음 나쁨" % (f(g), f(o), f(w))


def grade_of(score):
    for cut, g in CUTS:
        if score >= cut:
            return g
    return CUTS[-1][1]


def shift(g, n):
    """등급 g 를 n 칸 (−: 아래로) 옮긴다."""
    i = NOTCHES.index(g) - n
    return NOTCHES[max(0, min(len(NOTCHES) - 1, i))]


def notch_diff(a, b):
    """a 가 b 보다 몇 칸 위인가."""
    return NOTCHES.index(b) - NOTCHES.index(a)


def _fin_values(L, y, mon, cf_op=None, collect_days=None, inp=None, maturity_shift=True, frac=None):
    """y년 1~mon월 기준 재무 값 (frac = 한 해 중 지난 비율, 연 환산에 씀). -> (값 dict, 근거 dict)."""
    frac = frac or mon / 12.0
    P = income(L, y, 1, mon)
    B = balance_sheet(L, "%04d-%02d" % (y, mon))
    if B is None and inp:
        B = balance_from_report(L, inp, y, mon)
    V, E = dict((f[0], None) for f in FIN), {"P": P, "B": B}
    if P and P["rev"]:
        n = len([m for m in P["months"]])
        n = max(n, 1)
        V["opm"] = 100.0 * P["op"] / P["rev"]
        V["fin"] = 100.0 * P["interest"] / P["rev"]
        V["icr"] = (P["op"] / float(P["interest"])) if P["interest"] > 0 else None
        E["icr_none"] = P["interest"] <= 0
        V["size"] = P["rev"] / frac
        E["annual_rev"] = V["size"]
        Q = income(L, y - 1, 1, mon)
        lrev = _num((inp or {}).get("작년_매출액"))
        if Q and Q["rev"] > 0 and len(Q["months"]) == mon:
            V["growth"] = 100.0 * (P["rev"] - Q["rev"]) / Q["rev"]
        elif lrev and int(_num((inp or {}).get("작년_결산연도")) or 0) == y - 1:
            # 작년 평가서 매출 (사용자 2026-11-13). 설립 해는 영업한 달 수로 연 환산해 비교
            est = _date((inp or {}).get("설립일"))
            lm = 12 - (est.month - 1) if est and est.year == y - 1 else 12
            V["growth"] = 100.0 * (V["size"] - lrev * 12.0 / lm) / (lrev * 12.0 / lm)
            E["growth_src"] = "작년 평가서 매출 %s원%s 대비 올해 연 환산" % (W(int(lrev)), (" (%d개월 → 12개월 환산)" % lm) if lm != 12 else "")
        else:
            E["growth_why"] = "작년 같은 달(1~%d월) 장부가 다 있지 않음" % mon if Q else "작년 장부 없음"
    if B and B.get("approx") and B["assets"] > 0:
        if B["equity"] > 0:
            V["debt"] = 100.0 * B["liab"] / B["equity"]
        else:
            E["neg_equity"] = True
        V["equity"] = 100.0 * B["equity"] / B["assets"]
        if B.get("loan") is not None:
            V["borrow"] = 100.0 * max(B["loan"], 0) / B["assets"]
        if P and P["rev"]:
            V["turn"] = (P["rev"] / frac) / B["assets"]
    elif B and B["assets"] > 0:
        cl = B["cl"]
        mat = _date((inp or {}).get("대출만기일"))
        E["mat"] = mat
        asof = min(dt.date(y, 12, 31), dt.date(y + (mon == 12), mon % 12 + 1, 1) - dt.timedelta(days=1))
        LD = loans_at(L, asof, dt.date(y, 12, 31)) if L.get("loans") else []
        if mat:   # 적요에 만기가 없는 대출은 체크리스트의 대출 만기일로 본다
            LD = [(v, bal, mat, k, bal if mat <= dt.date(y + 1, 12, 31) else 0, "1년 안 (입력 만기)" if mat <= dt.date(y + 1, 12, 31) else "1년 넘음 (입력 만기)")
                  if st == "만기 모름" else (v, bal, m_, k, cur, st) for v, bal, m_, k, cur, st in LD]
        E["loans"] = LD
        if maturity_shift and LD:
            # 단기차입금(260)·유동성장기부채(264)는 이미 유동부채라 장기 대출(291·293)만 옮긴다 (코덱스 검토 2026-11-14)
            long_v = set(x[2] for x in L.get("loans", []) if str(x[1]).startswith(("291", "293")))
            mv = sum(cur for v, bal, m_, k, cur, st in LD if v in long_v and not v.startswith(("가수", "대표")))
            if mv:
                cl += mv   # 결산일부터 1년 안에 갚을 장기 대출 → 결산 재무상태표에서 유동부채(유동성장기부채)
                E["moved"] = mv
        elif maturity_shift and mat and B.get("long_loan", 0) > 0 and mat <= dt.date(y + 1, 12, 31):
            cl += B["long_loan"]   # 결산일(12/31)부터 1년 안 만기 → 결산 재무상태표에서 유동부채(유동성장기부채)
            E["moved"] = B["long_loan"]
        E["cl_adj"] = cl
        if B["equity"] > 0:
            V["debt"] = 100.0 * B["liab"] / B["equity"]
        else:
            V["debt"] = None
            E["neg_equity"] = True
        V["equity"] = 100.0 * B["equity"] / B["assets"]
        V["borrow"] = 100.0 * max(B.get("loan", 0), 0) / B["assets"]
        V["current"] = (100.0 * B["ca"] / cl) if cl > 0 else None
        if P and P["rev"]:
            V["turn"] = (P["rev"] / frac) / B["assets"]
    V["ocf"] = cf_op
    V["collect"] = collect_days
    return V, E


def _nonfin(L, inp, asof, P, input_dir):
    """비재무 판정 [(키, 이름, 값 글, 어디서, 판정 또는 None, 왜)] + 상한 등급."""
    out, cap = [], None
    est = _date(inp.get("설립일"))
    if est is None and L and L["rows"] and L["start"]:
        first = min(r[0] for r in L["rows"])
        est = dt.date(int(first[:4]), int(first[5:7]), 1)
        est_src = "장부 첫 달"
    else:
        est_src = "입력"
    if est:
        yrs = (asof - est).days / 365.25
        lv = "좋음" if yrs >= 10 else ("보통" if yrs >= 5 else ("주의" if yrs >= 3 else "나쁨"))
        out.append(("age", "%d년 설립 · %.1f년" % (est.year, yrs), est_src, lv))
    else:
        out.append(("age", "설립일 입력 필요", "입력", None))
    v = inp.get("대표신용점수", "")
    out.append(("ceo", v or "입력 필요", "입력", {"900 이상": "좋음", "800~899": "보통", "800 미만": "나쁨"}.get(v)))
    for key, item in (("delinq", "금융연체"), ("tax", "체납"), ("suit", "소송압류")):
        v = inp.get(item, "")
        lv = {"없음": "좋음", "있음": "나쁨"}.get(v)
        out.append((key, v or "입력 필요", "입력", lv))
        if v == "있음" and key in ("delinq", "tax"):
            cap = CAP_DEFAULT
    ex = _num(inp.get("대표동종경력"))
    if ex is not None:
        lv = "좋음" if ex >= 10 else ("보통" if ex >= 5 else ("주의" if ex >= 3 else "나쁨"))
        out.append(("exp", "%g년" % ex, "입력", lv))
    else:
        out.append(("exp", "입력 필요", "입력", None))
    # 거래처 쏠림: 매출 거래처 (연간자료.csv 매출거래처, 올해)
    conc = _concentration(input_dir, asof.year)
    if conc:
        n, t1, t3 = conc
        lv = "좋음" if t1 < 20 else ("보통" if t1 < 30 else ("주의" if t1 < 50 else "나쁨"))
        out.append(("conc", "%d곳 · 상위 1곳 %.1f%% · 상위 3곳 %.1f%%" % (n, t1, t3), "장부", lv))
    else:
        out.append(("conc", "매출 거래처 자료 없음", "장부", None))
    st = _staff(input_dir, asof)
    if st:
        lv = "좋음" if st[0] >= 50 else ("보통" if st[0] >= 10 else ("주의" if st[0] >= 5 else "나쁨"))
        out.append(("staff", "%d명 (%s 급여 기준)" % st, "장부", lv))
    else:
        out.append(("staff", "급여 사원 자료 없음", "장부", None))
    v = inp.get("인증", "")
    out.append(("cert", v or "입력 필요", "입력", None if not v else ("보통" if v in ("없음", "아니오") else "좋음")))
    v = inp.get("결산방식", "")
    out.append(("audit", v or "입력 필요", "입력", {"세무사 결산": "보통", "외부감사": "좋음"}.get(v)))
    v = inp.get("사업장", "")
    src = "입력"
    if not v and L and any("보증금" in name and d > 0 for m, code, name, d, c in L["rows"]):
        v, src = "임차", "장부 (보증금 있음)"
    out.append(("site", v or "입력 필요", src, {"임차": "보통", "자가": "좋음"}.get(v)))
    names = dict((k, (n, why)) for k, n, _, why in NONFIN)
    return [(k, names[k][0], val, src_, lv, names[k][1]) for k, val, src_, lv in out], cap


def _concentration(input_dir, year):
    tot = collections.defaultdict(int)
    for r in _read(os.path.join(input_dir, "연간자료.csv")):
        if (r.get("연도") or "").strip() == str(year) and (r.get("구분") or "").strip() == "매출거래처":
            try:
                tot[(r.get("항목") or "").strip()] += int(float(r.get("금액") or 0))
            except ValueError:
                pass
    vals = sorted((v for v in tot.values() if v > 0), reverse=True)
    s = sum(vals)
    if not s:
        return None
    return len(vals), 100.0 * vals[0] / s, 100.0 * sum(vals[:3]) / s


def _staff(input_dir, asof):
    by = collections.defaultdict(set)
    for r in _read(os.path.join(input_dir, "사원급여.csv")):
        ym, nm = (r.get("연월") or "").strip(), (r.get("사원명") or "").strip()
        if ym and nm and ym <= asof.strftime("%Y-%m"):
            by[ym].add(nm)
    if not by:
        return None
    last = max(by)
    return len(by[last]), last


def _score(fin_lv, non_lv):
    """판정 → (아래, 가운데, 위) 점수. 모르는 칸은 UNK_*."""
    def area_avg(unk):
        tot, w = 0.0, 0
        for area, aw in AREA_W.items():
            vals = [PTS[lv] if lv else unk for k, a, lv in fin_lv if a == area]
            if vals:
                tot += aw * sum(vals) / len(vals)
                w += aw
        return tot / w if w else unk
    def non_avg(unk):
        vals = [PTS[lv] if lv else unk for lv in non_lv]
        return sum(vals) / len(vals) if vals else unk
    return tuple((FIN_W * area_avg(u) + NONFIN_W * non_avg(u)) / 100.0 for u in (UNK_LO, UNK_MID, UNK_HI))


def _range(sc, age_years, cap):
    lo, mid, hi = (grade_of(s) for s in sc)
    if age_years is not None and age_years < 3:
        lo = shift(lo, -1)   # 업력 3년 미만: 아래쪽을 한 칸 더 (보수적으로)
    if cap:
        lo, mid, hi = [g if NOTCHES.index(g) >= NOTCHES.index(cap) else cap for g in (lo, mid, hi)]
    return lo, mid, hi


def compute(input_dir, p1, annual=False):
    """p1(기간 끝) 기준 신용평가 미리보기. 분개장 자료(계정잔액.csv)가 없으면 None."""
    L = load(input_dir)
    if not L or not L["rows"]:
        return None
    y = p1.year
    last_ym = max(r[0] for r in L["rows"] if r[0].startswith("%04d-" % y)) if any(r[0].startswith("%04d-" % y) for r in L["rows"]) else None
    if last_ym is None:
        return None
    mon = min(p1.month, int(last_ym[5:7]))
    inp = read_inputs(input_dir)
    # 현금흐름표 ① 본업 (올해 누적), 회수 날수 (최근 3달)
    cf_op, collect_days = None, None
    y0 = dt.date(y, 1, 1)
    last_day = min(p1, dt.date(y + (mon == 12), mon % 12 + 1, 1) - dt.timedelta(days=1))   # 장부가 있는 마지막 달 끝
    try:
        from . import cashflow
        rows = cashflow.load(input_dir)
        if rows:
            cf_op = cashflow.period(rows, y0, last_day)["op"]
        C_ = cashflow.collection(input_dir, y0, last_day)
        if C_ and C_.get("recent"):
            collect_days = C_["recent"][0]
    except Exception:   # 현금흐름 자료가 없거나 깨져도 나머지는 보인다
        pass
    frac = ((last_day - y0).days + 1) / float((dt.date(y + 1, 1, 1) - y0).days)
    V, E = _fin_values(L, y, mon, cf_op, collect_days, inp, frac=frac)
    spec = dict((f[0], f) for f in FIN)
    fin = [(k, spec[k][1], judge(k, V[k])) for k in V]
    nonfin, cap = _nonfin(L, inp, p1, E, input_dir)
    age = None
    m = re.search(r"·\s*([\d.]+)년", nonfin[0][2])
    if m:
        age = float(m.group(1))
    sc = _score(fin, [lv for k, n, val, s_, lv, why in nonfin])
    lo, mid, hi = _range(sc, age, cap)
    C = {"p1": p1, "year": y, "mon": mon, "annual": annual, "V": V, "E": E, "fin": fin, "nonfin": nonfin, "cap": cap,
         "score": sc, "grade": (lo, mid, hi), "inputs": inp, "start": L["start"], "age": age, "_L": L}
    C["last"] = _last_year(L, inp, y, nonfin, age, cap, input_dir)
    if C["last"] and C["last"].get("adj"):
        n = C["last"]["adj"]
        C["grade_raw"] = (lo, mid, hi)
        C["grade"] = tuple(shift(g, n) for g in (lo, mid, hi))
        if cap:
            C["grade"] = tuple(g if NOTCHES.index(g) >= NOTCHES.index(cap) else cap for g in C["grade"])
    C["todo"] = todo(C)
    C["best"], C["worst"] = _best_worst(C)
    return C


def _last_year(L, inp, y, nonfin, age, cap, input_dir):
    """작년에 받은 평가 (사용자 2026-11-12: 작년 평가 내용을 넣고 비교). 작년 결산 값을 같은 규칙으로 점수 내 실제 등급과 비교해 보정 칸 수."""
    g = (inp.get("작년_등급") or "").strip().upper().replace("０", "0")
    g = re.sub(r"^([A-D]+)$", r"\g<1>0", g) if g and g not in ("AAA", "D", "CC", "C") else g
    if not any(inp.get(k) for k, _ in INPUT_ITEMS if k.startswith("작년_")):
        return None
    ly = int(_num(inp.get("작년_결산연도")) or (y - 1))
    V, E = _fin_values(L, ly, 12, None, None, inp, maturity_shift=False)
    src = {}
    for k, item in LAST_KEYS.items():
        v = _num(inp.get(item))
        if v is not None:
            V[k], src[k] = v, "평가서"
        elif V.get(k) is not None:
            src[k] = "장부"
    rev = _num(inp.get("작년_매출액"))
    if rev:
        V["size"], src["size"] = rev, "평가서"
    elif V.get("size") is not None:
        src["size"] = "장부"
    spec = dict((f[0], f) for f in FIN)
    fin = [(k, spec[k][1], judge(k, V[k])) for k in V]
    non = [lv for k, n, val, s_, lv, why in nonfin]
    if age is not None:
        a = age - 1
        non[0] = "좋음" if a >= 10 else ("보통" if a >= 5 else ("주의" if a >= 3 else "나쁨"))
    sc = _score(fin, non)
    mine = _range(sc, (age - 1) if age is not None else None, cap)[1]
    out = {"year": ly, "agency": inp.get("작년_평가사", ""), "date": inp.get("작년_평가일", ""), "grade": g if g in NOTCHES else (g or None),
           "cr": inp.get("작년_현금흐름등급", ""), "note": inp.get("작년_지적사항", ""), "V": V, "src": src, "mine": mine}
    if out["grade"] in NOTCHES:
        out["adj"] = notch_diff(out["grade"], mine)   # 실제가 프로그램보다 몇 칸 위인가 → 올해 범위를 같은 만큼 옮김
    return out


def todo(C):
    """결산 전에 하면 유리한 것 — 정해진 규칙에 해당할 때만, 효과는 이 장의 계산식으로만."""
    V, E, inp, y = C["V"], C["E"], C["inputs"], C["year"]
    out = []
    B, P = E.get("B"), E.get("P")
    ocf = V.get("ocf")
    if ocf is not None and ocf < 0:
        ar = B.get("ar") if B else None
        t = "올해 본업 현금이 %s원입니다 (현금흐름 '나쁨')." % W(ocf)
        if ar:
            t += " 결산일 미수금(현재 %s원)을 12/31 전에 회수하면 회수한 만큼 본업 현금이 늘고 유동자산 안에서 미수금이 현금으로 바뀝니다." % W(ar)
            eff = "예: %s원 회수 시 본업 현금 %s원 → %s원" % (W(min(ar, -ocf)), W(ocf), W(ocf + min(ar, -ocf)))
        else:
            inc = moves(C["_L"], y, C["mon"], AR_PREFIX)
            if inc > 0:
                t += " 올해 미수금이 %s원 늘었습니다." % W(inc)
            t += " 12/31 전에 받을 돈을 당겨 받으면 그만큼 본업 현금이 늘어납니다."
            eff = "예: %s원 회수 시 본업 현금 %s원 → %s원" % (W(min(inc, -ocf)), W(ocf), W(ocf + min(inc, -ocf))) if inc > 0 else ""
        out.append(("미수금 회수를 결산일 전으로 당기기", t, eff))
    for v, bal, m_, k, cur, st in E.get("loans") or []:
        if st == "만기 지남":
            out.append(("만기 지난 대출 확인", "%s 대출 %s원은 만기(%s)가 지났는데 장부에 갚은 전표가 없습니다. 연장했으면 새 만기를 적요에 넣고, "
                        "갚았으면 상환 전표를 넣어야 결산 재무상태표의 부채가 맞습니다. 그대로면 1년 안에 갚을 빚으로 잡혀 유동비율이 낮아집니다."
                        % (v, W(bal), m_.isoformat()), ""))
    if E.get("moved"):
        before = 100.0 * B["ca"] / B["cl"] if B and B["cl"] > 0 else None
        after = V.get("current")
        if E.get("loans"):
            parts = ", ".join("%s %s원(%s)" % (v, W(cur), st) for v, bal, m_, k, cur, st in E["loans"] if cur)
            t = ("결산일(%d-12-31)부터 1년 안에 갚을 장기 대출 %s원(%s)이 결산 재무상태표에서 '1년 안에 갚을 빚(유동부채)'으로 옮겨집니다."
                 " 연장·대환을 결산 전에 정해 두면 유동비율 하락을 피할 수 있습니다." % (y, W(E["moved"]), parts))
        else:
            t = ("장기 대출 %s원의 만기(%s)가 결산일(%d-12-31)부터 1년 안이라 결산 재무상태표에서 '1년 안에 갚을 빚(유동부채)'으로 옮겨집니다."
                 " 연장·대환을 결산 전에 정해 두면 유동비율 하락을 피할 수 있습니다." % (W(E["moved"]), E["mat"].isoformat(), y))
        eff = "유동비율 %s → %s (옮기기 전 → 후)" % (fmt("current", before), fmt("current", after)) if before is not None and after is not None else ""
        out.append(("1년 안 만기 대출 정리", t, eff))
    elif (not B or B.get("approx")) and E.get("mat") is None and _date(inp.get("대출만기일")) and _date(inp.get("대출만기일")) <= dt.date(y + 1, 12, 31) \
            and moves(C["_L"], y, C["mon"], LONG_LOAN_PREFIX) != 0:
        mat = _date(inp.get("대출만기일"))
        out.append(("1년 안 만기 대출 정리", "장기 대출의 만기(%s)가 결산일(%d-12-31)부터 1년 안이라 결산 재무상태표에서 '1년 안에 갚을 빚(유동부채)'으로 옮겨져 "
                    "유동비율이 낮아집니다. 연장·대환을 결산 전에 정해 두는 것이 유리합니다." % (mat.isoformat(), y), ""))
    elif not inp.get("대출만기일") and B and B.get("long_loan", 0) > 0:
        out.append(("대출 만기일 넣기", "장기 대출 %s원이 있습니다. 만기일을 체크리스트에 넣으면 결산 때 유동부채로 옮겨지는지 계산합니다." % W(B["long_loan"]), ""))
    if B and B.get("suspense", 0) > 0:
        out.append(("대표 가수금 정리", "장부에 남은 가수금 %s원은 부채로 잡혀 부채비율을 높입니다. 갚거나 자본금으로 바꿀지(출자전환) 세무사와 정합니다." % W(B["suspense"]),
                    _debt_effect(B, B["suspense"])))
    for key, item in (("delinq", "금융연체"), ("tax", "체납")):
        if inp.get(item) == "있음":
            out.append(("%s 해소" % item, "%s이 있으면 재무 점수와 상관없이 등급이 %s 아래로 묶입니다. 평가 전에 해소하고 완납 증명을 준비합니다." % (item, CAP_DEFAULT), ""))
    if V.get("debt") is not None and V["debt"] > 200:
        need = int(B["liab"] / 2.0 - B["equity"]) if B and B["equity"] > 0 else None
        t = ("부채비율 %s로 기준(200%%)을 넘습니다. 올해 이익을 배당하지 않고 남겨 두면 자본이 그만큼 커져 비율이 낮아집니다. "
             "결산 전 갚을 수 있는 미지급금·차입금을 먼저 갚으면 부채와 자산이 같이 줄어 비율이 더 낮아집니다." % fmt("debt", V["debt"]))
        eff = ("200%%까지 낮추려면 자본이 %s원 더 필요 (증자·가수금 출자전환 등). 배당하면 그만큼 비율이 다시 올라감" % W(need)) if need and need > 0 else ""
        out.append(("부채비율 낮추기", t, eff))
    miss = [n for k, n, val, s_, lv, why in C["nonfin"] if lv is None and s_ == "입력"]
    if miss:
        out.append(("체크리스트 채우기", "아직 입력하지 않은 항목: %s. 채우면 등급 범위가 좁아집니다." % ", ".join(miss), ""))
    return out


def explain(C):
    """쉬운 설명 (사용자 2026-11-13: 모든 자료에 쉬운 설명과 제안). 정해진 문장틀에 이 장의 숫자만 넣는다."""
    out, V, LY = [], C["V"], C.get("last")
    names = dict((f[0], f[2]) for f in FIN)
    plain = {"debt": "빚이 내 돈의 %.1f배", "equity": "회사 재산 중 내 돈이 %.0f%%", "borrow": "재산 중 이자 내는 빚이 %.0f%%",
             "current": "1년 안 갚을 빚 대비 1년 안 돈이 될 재산 %.0f%%"}
    def say_v(k, v):
        if k == "debt":
            return plain[k] % (v / 100.0)
        return plain[k] % v if k in plain else fmt(k, v)
    if LY and LY.get("grade") in NOTCHES:
        g = LY["grade"]
        n = NOTCHES.index(g) - NOTCHES.index("BBB-")
        pos = ("투자 적격(BBB- 이상)보다 %d칸 아래" % n) if n > 0 else "투자 적격(BBB- 이상) 안"
        out.append("작년(%d년 결산) %s 평가는 %s입니다. 22칸 등급 중 %d번째로, %s입니다." % (LY["year"], LY["agency"] or "평가사", g, NOTCHES.index(g) + 1, pos))
        bad = [(k, LY["V"][k]) for k in ("debt", "equity", "borrow", "current") if LY["V"].get(k) is not None and judge(k, LY["V"][k]) in ("나쁨", "주의")]
        if bad:
            k, v = bad[0]
            line = "작년 등급을 가장 끌어내린 것은 %s %s(%s)입니다." % (names[k], fmt(k, v), say_v(k, v))
            if V.get(k) is not None:
                better = (V[k] < v) if k in ("debt", "borrow") else (V[k] > v)
                line += " 올해는 %s(%s)로 %s." % (fmt(k, V[k]), say_v(k, V[k]), "좋아졌습니다" if better else "나빠졌습니다")
            out.append(line)
    out.append("올해 추정 범위는 %s입니다%s. 모르는 칸(%d개)을 채울수록 범위가 좁아집니다." % (
        grade_text(C["grade"]), " (작년 실제 등급에 맞춰 보정)" if LY and LY.get("adj") else "",
        sum(1 for _, _, lv in C["fin"] if lv is None) + sum(1 for x in C["nonfin"] if x[4] is None)))
    if C["worst"]:
        k = C["worst"][0]
        out.append("올해 가장 걸리는 것은 %s %s입니다 — %s." % (names[k], fmt(k, V[k]), dict((f[0], f[7]) for f in FIN)[k]))
    return out


def _debt_effect(B, x):
    if not B or B["equity"] <= 0:
        return ""
    a = 100.0 * B["liab"] / B["equity"]
    b = 100.0 * (B["liab"] - x) / (B["equity"] + x)
    return "출자전환하면 부채비율 %.1f%% → %.1f%%" % (a, b)


def _best_worst(C):
    order = {"좋음": 0, "보통": 1, "주의": 2, "나쁨": 3}
    known = [(k, n, lv) for k, n, lv in [(k, dict((f[0], f[2]) for f in FIN)[k], lv) for k, _, lv in C["fin"]] if lv]
    if not known:
        return None, None
    best = min(known, key=lambda x: (order[x[2]], [f[0] for f in FIN].index(x[0])))
    worst = max(known, key=lambda x: (order[x[2]], -[f[0] for f in FIN].index(x[0])))
    return best, (worst if order[worst[2]] >= 2 else None)


def W(v):
    return "—" if v is None else ("{:,}".format(int(v)) if v >= 0 else "−{:,}".format(-int(v)))


def brief(C):
    """경영관리 '자료 안내'용 한 줄 (사용자 2026-11-13: 정기 자료도 최근 결과를 경영관리에서)."""
    if C is None:
        return "기업신용평가 미리보기: 계산 자료 없음"
    LY = C.get("last") or {}
    t = "기업신용평가 미리보기 (%d년 결산 기준): 추정 %s" % (C["year"], grade_text(C["grade"]))
    if LY.get("grade"):
        t += " · 작년 %s %s" % (LY.get("agency") or "", LY["grade"])
    if C["worst"]:
        t += " · 가장 걸리는 점 %s" % dict((f[0], f[2]) for f in FIN)[C["worst"][0]]
    return t + " · 결산 전 할 일 %d가지" % len(C["todo"])


def grade_text(g):
    lo, mid, hi = g
    return lo if lo == hi else "%s ~ %s" % (lo, hi)


# ───────────── 그리기 ─────────────
CSS = """<style>
.crx .top{display:flex;border-top:2px solid var(--ink,#2b3a4e);border-bottom:1px solid var(--ink,#2b3a4e);margin:8px 0}
.crx .top .c{flex:1;padding:8px 10px;border-left:1px solid var(--line,#c5ccd6)}.crx .top .c:first-child{border-left:0;flex:1.4}
.crx .lab{font-size:11px;font-weight:700;color:var(--sub,#555)}.crx .big{font-size:22px;font-weight:800;margin:3px 0}.crx .foot{font-size:11px;color:var(--sub,#555);line-height:1.5}
.crx table.cr{width:100%;border-collapse:collapse;font-size:11.6px}
.crx table.cr th{text-align:left;font-size:11px;color:var(--sub,#555);padding:4px 6px;border-bottom:1.5px solid var(--ink,#2b3a4e)}
.crx table.cr td{padding:5px 6px;border-bottom:1px solid var(--line,#e3e6ea);vertical-align:top}
.crx table.cr tr{break-inside:avoid}.crx td.n{text-align:right;white-space:nowrap;font-weight:700}.crx td.a{font-weight:700;white-space:nowrap}
.crx .sub{display:block;font-size:10.5px;color:var(--sub,#666);font-weight:400}
.crx .tg{display:inline-block;min-width:34px;text-align:center;color:#fff;border-radius:3px;padding:1px 4px;font-size:10.5px;font-weight:700}
.crx .t좋음{background:#2e8b57}.crx .t보통{background:#8a8f98}.crx .t주의{background:#d08a1e}.crx .t나쁨{background:#c0392b}.crx .tx{background:#fff;color:#888;border:1px dashed #aaa}
.crx .bar{position:relative;height:14px;border-radius:3px;margin:6px 0 2px;background:linear-gradient(90deg,#c0392b 0 44%,#d08a1e 44% 62%,#8a8f98 62% 80%,#2e8b57 80% 100%)}
.crx .bar .rng{position:absolute;top:-2px;height:18px;border:2px solid #111;box-sizing:border-box;border-radius:3px}.crx .bar .pin{position:absolute;top:-5px;width:3px;height:24px;background:#111}
.crx .scale{position:relative;height:14px;font-size:10px;color:var(--sub,#555)}.crx .scale span{position:absolute;transform:translateX(-50%)}
.crx ol.todo{margin:4px 0;padding-left:20px;font-size:12px;line-height:1.6}.crx ol.todo li{margin:4px 0;break-inside:avoid}.crx .eff{display:block;font-size:11px;color:#2e8b57;font-weight:700}
.crx .say{font-size:12.4px;line-height:1.6;padding:8px 12px;border-left:4px solid var(--accent,#2b3a4e);background:var(--soft,#f4f6f8);border-radius:4px;margin:8px 0}
</style>"""


def _tag(lv):
    return "<span class='tg t%s'>%s</span>" % (lv, lv) if lv else "<span class='tg tx'>—</span>"


def _bar(sc):
    lo, mid, hi = sc
    lab = "".join("<span style='left:%d%%'>%s</span>" % (x, t) for x, t in ((22, "B 이하"), (53, "BB"), (71, "BBB"), (90, "A 이상")))
    return ("<div class='bar'><div class='rng' style='left:%.1f%%;width:%.1f%%'></div><div class='pin' style='left:%.1f%%'></div></div>"
            "<div class='scale'>%s</div>" % (lo, max(hi - lo, 1), mid, lab))


def render(C):
    if C is None:
        return CSS + "<div class='crx'><div class='note'>분개장 계정 자료(계정잔액.csv)가 없어 계산하지 못했습니다. '자료 변환'을 다시 하면 생깁니다.</div></div>"
    V, E = C["V"], C["E"]
    spec = dict((f[0], f) for f in FIN)
    h = [CSS, "<div class='crx'>"]
    when = "%d년 결산 기준 (%d월까지 장부 반영)" % (C["year"], C["mon"]) if not C["annual"] else "%d년 결산 기준" % C["year"]
    h.append("<div class='note'>%s. 평가 회사(NICE·한국기업데이터·이크레더블 등)의 실제 모형은 공개되지 않아 <b>등급은 추정 범위</b>로만 보입니다. "
             "판정 기준은 재무분석에서 널리 쓰이는 값이고, 모든 문구는 정해진 규칙으로 만듭니다.</div>" % when)
    easy = explain(C)
    if easy:
        h.append("<div class='say'><b>쉬운 설명</b><br>%s</div>" % "<br>".join(esc(x) for x in easy))
    best, worst = C["best"], C["worst"]
    adj = (C.get("last") or {}).get("adj")
    foot = "점수 %.0f점 (모르는 칸에 따라 %.0f~%.0f점)." % (C["score"][1], C["score"][0], C["score"][2])
    if C["age"] is not None and C["age"] < 3:
        foot += " 업력 3년 미만이라 아래쪽을 한 칸 더 봅니다."
    if adj:
        foot += " 작년 실제 등급에 맞춰 %d칸 %s 보정." % (abs(adj), "올려" if adj > 0 else "내려")
    if C["cap"]:
        foot += " 연체·체납 '있음'이라 %s 위로는 보지 않습니다." % C["cap"]
    cards = [("추정 등급 범위", grade_text(C["grade"]), foot)]
    cards.append(("가장 좋은 점", esc(best[1]) if best else "—", "%s (%s)" % (fmt(best[0], V[best[0]]), best[2]) if best else ""))
    cards.append(("가장 걸리는 점", esc(worst[1]) if worst else "없음", "%s (%s)" % (fmt(worst[0], V[worst[0]]), worst[2]) if worst else "주의·나쁨 판정 없음"))
    cards.append(("결산 전에 할 일", "%d가지" % len(C["todo"]), "아래 ‘결산 전에 하면 유리한 것’"))
    h.append("<div class='top'>%s</div>" % "".join(
        "<div class='c'><div class='lab'>%s</div><div class='big'%s>%s</div><div class='foot'>%s</div></div>"
        % (esc(l), " style='color:#c0392b'" if i == 2 and worst else "", b, esc(f)) for i, (l, b, f) in enumerate(cards)))
    h.append("<div class='lab'>점수 위치 (0~100점, 상자 = 모르는 칸 때문에 생기는 폭)</div>" + _bar(C["score"]))

    # ① 재무
    h.append("<div class='q'>① 재무 항목 (장부로 자동 계산)</div><table class='cr'><thead><tr><th>영역</th><th>항목 · 계산</th>"
             "<th style='text-align:right'>우리 회사</th><th>기준</th><th>판정</th><th>무슨 뜻</th></tr></thead><tbody>")
    for area in AREA_W:
        ks = [f[0] for f in FIN if f[1] == area]
        for i, k in enumerate(ks):
            s = spec[k]
            v = V[k]
            if v is None:
                why = {"growth": E.get("growth_why", "작년 장부 필요"), "icr": "이자비용 없음" if E.get("icr_none") else "장부 필요",
                       "ocf": "현금흐름 자료 없음", "collect": "계산서·입금 자료 없음"}.get(k)
                if why is None:
                    why = "자본이 마이너스" if (k == "debt" and E.get("neg_equity")) else ("작년 분개장 필요 (잔액)" if not C["start"] else "계산 불가")
                val = "<span style='font-weight:400;color:#888'>%s</span>" % esc(why)
            else:
                val = esc(fmt(k, v))
            lv = judge(k, v) if v is not None else ("좋음" if k == "icr" and E.get("icr_none") else None)
            area_td = "<td class='a' rowspan='%d'>%s</td>" % (len(ks), area) if i == 0 else ""
            h.append("<tr>%s<td>%s<span class='sub'>%s</span></td><td class='n'>%s</td><td style='font-size:10.8px'>%s</td><td>%s</td><td>%s</td></tr>"
                     % (area_td, esc(s[2]), esc(s[3]), val, esc(threshold_text(k)), _tag(lv), esc(s[7])))
    h.append("</tbody></table>")
    B = E.get("B")
    if E.get("growth_src") and V.get("growth") is not None:
        h.append("<div class='note'>매출액증가율: %s.</div>" % esc(E["growth_src"]))
    if B and B.get("approx"):
        h.append("<div class='note'>잔액은 <b>추정</b>입니다: 작년 평가서의 %d년 말 총자산 %s원·자기자본 %s원에 올해 1~%d월 장부 증감(자산 %s원, 부채 %s원)을 더함 → "
                 "총자산 %s원, 부채 %s원, 자본 %s원. 법인세는 아직 빼지 않은 금액이라 결산 뒤 자본은 조금 줄어듭니다. "
                 "유동비율은 유동·비유동을 나눈 작년 잔액이 있어야 하고%s, 작년 분개장을 넣으면 정확한 장부 잔액으로 바뀝니다.</div>"
                 % (C["year"] - 1, W(B["open_assets"]), W(B["open_equity"]), C["mon"], W(B["d_assets"]), W(B["d_liab"]),
                    W(B["assets"]), W(B["liab"]), W(B["equity"]), "" if B.get("loan") is not None else ", 차입금의존도는 작년 말 차입금을 넣어야 계산됩니다"))
    elif B:
        h.append("<div class='note'>%d월 말 장부 잔액: 총자산 %s원 (유동 %s · 비유동 %s), 부채 %s원 (유동 %s%s · 비유동 %s), 자본 %s원 (= 자산 − 부채)."
                 " 차입금 %s원. 영업이익·매출은 1~%d월 장부.</div>"
                 % (C["mon"], W(B["assets"]), W(B["ca"]), W(B["na"]), W(B["liab"]), W(B["cl"]),
                    (" → 결산 때 %s" % W(E["cl_adj"])) if E.get("moved") else "", W(B["nl"]), W(B["equity"]), W(B.get("loan", 0)), C["mon"]))
    if E.get("loans"):
        h.append("<div class='note'>대출별 (적요의 만기일자): %s. 차입금에는 대표 가수금 %s원도 넣었습니다 (평가사 기준과 같게).</div>" % (
            esc(" · ".join("%s %s원 만기 %s → %s%s" % (v, W(bal), m_.isoformat() if m_ else "모름", st, (" %s원" % W(cur)) if cur and cur != bal else "")
                           for v, bal, m_, k, cur, st in E["loans"])), W((B or {}).get("suspense", 0))))
    if not B:
        h.append("<div class='note'>부채비율·자기자본비율·차입금의존도·유동비율·총자산회전율은 회사 처음부터의 잔액이 필요합니다. "
                 "작년(설립 해) 분개장을 수집\\위하고에 넣고 '자료 변환'을 하면 채워집니다.</div>")

    # ② 비재무
    h.append("<div class='q'>② 비재무 항목 (체크리스트 — 창 '가끔 넣는 값' → '신용평가 체크리스트')</div><table class='cr'><thead><tr>"
             "<th>항목</th><th>값</th><th>어디서</th><th>판정</th><th>왜 보나</th></tr></thead><tbody>")
    for k, n, val, src, lv, why in C["nonfin"]:
        h.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (esc(n), esc(val), esc(src), _tag(lv), esc(why)))
    h.append("</tbody></table><div class='note'>'있음/없음'처럼 정해진 규칙으로만 점수를 냅니다. 금융 연체·체납이 '있음'이면 재무 점수와 상관없이 %s 위로는 보지 않습니다.</div>" % CAP_DEFAULT)

    # ③ 작년 평가와 비교
    LY = C.get("last")
    h.append("<div class='q'>③ 작년에 받은 평가와 비교</div>")
    if not LY:
        h.append("<div class='note'>작년 평가 결과를 체크리스트의 '작년 평가' 칸(등급·현금흐름등급·평가서의 재무비율)에 넣으면, 같은 규칙으로 작년을 계산해 "
                 "실제 등급과의 차이만큼 올해 범위를 보정하고 항목별로 비교합니다.</div>")
    else:
        head = "%s %s 평가 (%d년 결산): 등급 %s%s" % (esc(LY["agency"] or "평가사"), esc(LY["date"]), LY["year"], esc(LY["grade"] or "—"),
                                                 (" · 현금흐름등급 %s" % esc(LY["cr"])) if LY["cr"] else "")
        line = "같은 규칙으로 작년을 계산하면 %s" % LY["mine"]
        if LY.get("adj") is not None:
            line += " → %s" % ("실제와 같아 보정 없음" if LY["adj"] == 0 else "실제가 %d칸 %s → 올해 범위도 %d칸 %s 보정 (보정 전 %s)"
                                % (abs(LY["adj"]), "위" if LY["adj"] > 0 else "아래", abs(LY["adj"]), "올려" if LY["adj"] > 0 else "내려",
                                   grade_text(C.get("grade_raw", C["grade"]))))
        h.append("<div class='say'>%s<br>%s%s</div>" % (head, esc(line), ("<br>평가서 지적 사항: %s" % esc(LY["note"])) if LY["note"] else ""))
        h.append("<table class='cr'><thead><tr><th>항목</th><th style='text-align:right'>작년</th><th>작년 출처</th><th style='text-align:right'>올해</th><th>변화</th></tr></thead><tbody>")
        for f in FIN:
            k = f[0]
            a, b = LY["V"].get(k), V.get(k)
            if a is None and b is None:
                continue
            ja, jb = judge(k, a) if a is not None else None, judge(k, b) if b is not None else None
            ch = "—"
            if ja and jb:
                d = LEVELS.index(ja) - LEVELS.index(jb)
                ch = "좋아짐" if d > 0 else ("나빠짐" if d < 0 else "같음")
            h.append("<tr><td>%s</td><td class='n'>%s %s</td><td>%s</td><td class='n'>%s %s</td><td>%s</td></tr>"
                     % (esc(f[2]), esc(fmt(k, a)), _tag(ja) if a is not None else "", esc(LY["src"].get(k, "")),
                        esc(fmt(k, b)), _tag(jb) if b is not None else "", ch))
        h.append("</tbody></table>")

    # ④ 결산 전 할 일
    h.append("<div class='q'>④ 결산 전에 하면 유리한 것</div>")
    if C["todo"]:
        h.append("<ol class='todo'>%s</ol>" % "".join("<li><b>%s</b> — %s%s</li>" % (esc(t), esc(b), ("<span class='eff'>%s</span>" % esc(e)) if e else "")
                                                      for t, b, e in C["todo"]))
    else:
        h.append("<div class='note'>해당하는 규칙이 없습니다.</div>")
    h.append("<div class='note'>할 일은 정해진 규칙(본업 현금 마이너스·1년 안 만기 대출·가수금 잔액·연체/체납·부채비율 200% 넘음·체크리스트 빈칸)에 해당할 때만 나오고, "
             "효과는 이 장의 계산식으로만 냅니다. 세무·회계 처리는 세무사 확인이 필요합니다.</div>")

    # ⑤ 계산 방법
    h.append("<div class='q'>⑤ 점수 계산 방법</div><table class='cr'><tbody>"
             "<tr><td class='a'>재무 %d%%</td><td>항목마다 좋음 100 · 보통 60 · 주의 30 · 나쁨 0, 영역 평균에 영역 무게(%s)</td></tr>"
             "<tr><td class='a'>비재무 %d%%</td><td>항목 판정 평균 (같은 점수표)</td></tr>"
             "<tr><td class='a'>모르는 칸</td><td>범위 아래 %d점 · 가운데 %d점 · 위 %d점으로 보고 등급 범위를 넓힘</td></tr>"
             "<tr><td class='a'>점수 → 등급</td><td>%s</td></tr></tbody></table></div>"
             % (FIN_W, " · ".join("%s %d" % (a, w) for a, w in AREA_W.items()), NONFIN_W, UNK_LO, UNK_MID, UNK_HI,
                " · ".join("%d점 %s" % (c, g) for c, g in CUTS)))
    return "".join(h)
