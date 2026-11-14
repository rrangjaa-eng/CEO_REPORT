"""현금흐름표 (사용자 2026-11-12 목업: mockups/현금흐름표/). 경영관리 보고에만 싣는다 (대표 보고에는 없음).

- 변환 쪽: build_table(books, cfg) → 현금흐름.csv (날짜마다 ① 통장 돈이 오간 이유별 금액, ② 장부 계정 묶음별 변화).
- 보고 쪽: load(input_dir) → 줄, compute(rows, p0, p1, end_balance) → 숫자, render(CF) → 경영관리 보고의 한 영역.

방식 (직접법): 통장(보통예금, cfg cash_codes) 줄이 있는 전표에서 상대 계정 줄마다 (대변 − 차변)을 그 줄 때문에 오간 현금으로 본다.
전표는 차변 = 대변이라 상대 줄을 다 더하면 통장 증감과 원 단위로 같다. 통장 줄만 있는 전표(급여 일부 등)는 적요로 나누고,
계좌 사이 이체는 들어오고 나간 것이 같아 0이 된다. 전기이월·기초잔액 전표는 넣지 않는다.
이익 → 현금 맞추기 (간접법): 장부상 이익 + 받을 돈·미리 준 돈·줄 돈·맡아 둔 세금의 변화 = ① 본업 합계. 맞지 않으면 '그 밖의 차이'로 보인다.
"""
import collections
import csv
import datetime as dt
import os
import re

from .util import esc

FILE = "현금흐름.csv"
KEYS = ["일자", "구분", "항목", "금액"]
OPENING = ("전기이월", "기초잔액")
CARD = re.compile(r"^(신한|롯데|비씨|BC|국민|KB|삼성|현대|하나|우리|농협|NH|씨티|IBK|기업)[^_]*_.*\d{4}$")

# (키, 쉬운 이름, 설명) — 목업 승인 문구 (사용자 2026-11-12)
OPS = [("고객", "고객에게 받은 행사 대금", "행사를 하고 고객사에게서 실제로 통장에 입금받은 돈입니다. 부가세가 포함된 금액입니다."),
       ("지원금", "정부 지원금", "정부 지원 사업(고용 지원 등)으로 받은 돈입니다."),
       ("업체", "행사 업체에 보낸 돈", "외주·장소·물품·인력 등 행사 업체에 통장에서 이체한 돈입니다(부가세 포함)."),
       ("카드", "법인카드 대금", "법인카드로 쓴 돈을 카드사에 갚은 것입니다. 카드는 쓴 날이 아니라 갚는 날 통장에서 나갑니다."),
       ("급여", "직원 급여", "직원 통장으로 들어간 실수령액입니다. 세금·4대보험을 떼고 남은 금액입니다."),
       ("프리", "프리랜서·강사 보수", "직원이 아닌 사람에게 일의 대가로 준 돈입니다(사업소득·기타소득)."),
       ("원천", "4대보험·원천세 납부", "급여에서 떼어 둔 세금·보험료와 회사 부담 보험료를 공단·세무서에 낸 돈입니다."),
       ("세금", "부가세·법인세 납부", "고객에게 받아 둔 부가세에서 업체에 낸 부가세를 빼고 나라에 낸 돈, 법인세 등입니다."),
       ("이자낸", "대출 이자", "빌린 돈에 대해 은행에 낸 이자입니다."),
       ("이자받", "예금 이자", "정기예금 등에서 받은 이자입니다(이자에서 미리 떼인 세금은 위 세금 줄에 들어감)."),
       ("기타", "그 밖의 작은 금액", "은행 수수료·잡수입 등 작은 금액입니다.")]
INV = [("정기넣음", "단기금융상품에 넣은 돈", "만기가 3개월 넘는 예금·적금·공제부금에 넣은 돈입니다. 통장에서는 빠지지만 회사 돈이 없어진 것은 아닙니다. (만기 3개월 이내 정기예금은 현금으로 보아 여기 없음)"),
       ("정기찾음", "단기금융상품에서 찾은 돈", "만기가 3개월 넘는 예금 등이 끝나 통장으로 돌아온 돈입니다."),
       ("보증금", "보증금 맡김·돌려받음", "사무실 등을 빌리며 맡긴 돈입니다. 나가면 돌려받습니다."),
       ("자산", "장비·시설 등 산 돈", "오래 쓰는 물건(비품·차량·시설 등)을 사거나 판 돈입니다."),
       ("투자기타", "그 밖에 맡기거나 빌려준 돈", "보증금·예금 말고 회사 밖에 맡기거나 빌려준 돈입니다.")]
FIN = [("자본", "주주가 넣은 돈 (자본금)", "회사를 세우거나 키우려고 주주가 넣은 돈입니다. 갚지 않아도 되는 돈입니다."),
       ("대출받음", "은행 대출 받음", "은행에서 빌린 돈입니다. 들어왔지만 갚아야 할 돈입니다."),
       ("대출갚음", "대출 원금 갚음", "빌린 돈 중 원금을 갚은 것입니다. 이자는 위 본업 칸에 있습니다."),
       ("대표", "대표이사와 주고받은 돈", "회사가 대표이사에게서 잠시 받아 쓴 돈(가수금)을 받거나 돌려드린 것입니다.")]
GROUPS = [("이익", "장부상 이익", "매출에서 비용을 뺀 이익입니다. 행사를 끝낸 달에 매출·비용을 잡습니다."),
          ("받을돈", "아직 못 받은 매출 대금", "매출로 잡았지만 고객이 아직 입금하지 않은 돈(미수금)이 늘면 그만큼 통장 돈은 적습니다. 줄면 그만큼 더 들어온 것입니다."),
          ("줄돈", "아직 안 준 업체·카드·급여", "비용으로 잡았지만 아직 업체·카드사·직원에게 주지 않은 돈(미지급금·미지급비용)이 늘면 통장 돈은 그만큼 남아 있습니다."),
          ("선급", "미리 준 돈 정리", "행사 전에 업체에 먼저 준 계약금(선급금)이 늘면 통장 돈이 먼저 나간 것이고, 비용으로 바뀌어 줄면 더해 줍니다."),
          ("세금예수", "부가세·원천세 맡아 둔 돈", "고객에게 받은 부가세, 급여에서 뗀 세금은 나중에 나라에 낼 돈입니다. 내기 전까지는 통장에 있습니다.")]
GLOSSARY = [("현금흐름표", "한 기간 동안 통장에 돈이 어디서 들어오고 어디로 나갔는지 정리한 표. 손익계산서가 ‘얼마 벌었나’라면, 현금흐름표는 ‘돈이 실제로 얼마 있나’를 봅니다."),
            ("장부상 이익", "일을 끝낸 시점에 매출과 비용을 잡아 계산한 이익. 돈이 들어오기 전에도 이익이 생길 수 있습니다."),
            ("미수금 (받을 돈)", "계산서를 발행했거나 일을 끝냈지만 아직 받지 못한 돈."),
            ("미지급금·미지급비용 (줄 돈)", "비용은 생겼지만 아직 주지 않은 돈. 업체 대금, 카드 대금, 다음 달 5일에 줄 급여 등."),
            ("선급금 (미리 준 돈)", "행사 전에 업체에 먼저 준 계약금. 행사가 끝나면 비용으로 바뀝니다."),
            ("부가세", "고객에게 받은 10%는 나라에 낼 돈이고, 업체에 준 10%는 돌려받을 돈. 둘의 차이를 분기마다 냅니다."),
            ("원천세·4대보험", "급여를 줄 때 미리 떼어 두었다가 다음 달 10일에 내는 세금과 보험료."),
            ("현금성자산", "통장 돈과 가입할 때 만기가 3개월 이내인 정기예금. 곧 쓸 수 있는 돈이라 현금으로 봅니다."),
            ("단기금융상품", "만기가 3개월 넘는 정기예금·적금·공제부금. 회사 돈이지만 바로 쓰기 어려워 현금과 따로 봅니다."),
            ("가수금", "회사 통장에 들어왔지만 성격이 정해지지 않은 돈. 이 회사에서는 대표이사가 회사에 잠시 넣어 둔 돈입니다.")]
ALL_CASH = [k for k, _, _ in OPS + INV + FIN]


def _sq(text):
    return re.sub(r"\s+", "", str(text or ""))


def _kind(code, name):
    """계정 → 묶음: 'pl' 손익 · 'cash' · 'inv' · 'fin' · 'ar' · 'ap' · 'pre' · 'tax' · 'other' (그 밖의 영업 자산·부채)."""
    if "보증금" in name:
        return "inv"   # 이 회사 임차보증금 코드는 96200 이라 손익 코드 범위와 겹친다
    if "정기예" in name or "적금" in name:
        return "inv"
    if code[:1] in ("4", "5", "6", "7", "8", "9"):
        return "pl"
    if code[:1] == "3" or "자본금" in name or "잉여금" in name:
        return "fin"
    if "차입금" in name or "가수금" in name or "사채" in name:
        return "fin"
    if code.isdigit() and 17900 <= int(code) < 25000:   # 비유동자산 (투자·유형·무형·기타비유동)
        return "inv"
    if "대여금" in name or "가지급금" in name or "단기매매" in name or "단기투자" in name:
        return "inv"
    if "미수" in name or "외상매출" in name or "받을어음" in name or "선수금" in name:
        return "ar"
    if "선급" in name and "세금" not in name:
        return "pre"
    if "미지급세금" in name or "법인세" in name or "부가세" in name or "예수금" in name or "선납세금" in name:
        return "tax"
    if "미지급" in name or "외상매입" in name or "지급어음" in name:
        return "ap"
    return "other"


def _cash_item(ln, x):
    """통장 전표의 상대 줄 하나 → 현금 항목 키. x = 그 줄의 대변 − 차변 (통장에 들어온 돈이면 +)."""
    code, name, vend = _sq(ln.get("account_code")), _sq(ln.get("account")), _sq(ln.get("vendor"))
    k = _kind(code, name)
    if k == "inv":
        if "정기예" in name or "적금" in name:
            return "정기넣음" if x < 0 else "정기찾음"
        if "보증금" in name:
            return "보증금"
        if code.isdigit() and 20000 <= int(code) < 24000:
            return "자산"
        return "투자기타"
    if k == "fin":
        if code[:1] == "3" or "자본금" in name:
            return "자본"
        if "가수금" in name:
            return "대표"
        return "대출받음" if x > 0 else "대출갚음"
    if k == "ar" or "수입수수료" in name or "매출" in name:
        return "고객"
    if "지원금" in name or "보조금" in name:
        return "지원금"
    if "이자비용" in name:
        return "이자낸"
    if "이자수익" in name:
        return "이자받"
    if "미지급비용" in name or "미지급금" in name:
        if CARD.match(vend) or "카드" in vend:
            return "카드"
        if vend == "직원급여" or "급여" in vend:
            return "급여"
        if vend in ("사업소득", "기타소득", "해외연사") or "소득" in vend:
            return "프리"
        if "세무서" in vend or "공단" in vend or "구청" in vend or "시청" in vend:
            return "원천" if "미지급비용" in name else "세금"
        return "업체"
    if k == "pre" or k == "ap":
        return "업체"
    if "급여" in name or "상여" in name or "퇴직" in name:
        return "급여"
    if "부가세" in name or "법인세" in name or "미지급세금" in name or "선납세금" in name:
        return "세금"
    if "예수금" in name or "복리후생비_건강" in name or "세금과공과금_연금" in name or "보험료_근로" in name or "보험료_고용" in name:
        return "원천"
    if k == "tax":
        return "세금"
    if code[:2] in ("61", "62", "63", "64") or "행사" in name or "외주" in name:
        return "업체"
    return "기타"


SHORT_DAYS = 92   # 가입할 때 만기 3개월 이내 = 현금성자산 (사용자 2026-11-12, 회계기준)


def _is_deposit(ln):
    n = _sq(ln.get("account"))
    return "정기예" in n or "적금" in n


def deposit_terms(journal):
    """정기예금 하나(거래처 = '신한260113' 처럼 가입일)마다 가입 → 만기 날수와 현금성 여부.
    -> {거래처: (날수 또는 None, 현금성 True/False, 근거)}. 적요에 '정기예금'이 없는 것(공제부금·적금)은 현금성이 아님.
    아직 만기 전이면 지난 정기예금들이 모두 3개월 이내였을 때만 현금성으로 본다 (추정)."""
    info = collections.defaultdict(lambda: {"join": None, "end": None, "memo": "", "vendor": ""})
    for ln in journal:
        if ln.get("date") is None or not _is_deposit(ln):
            continue
        v = (ln.get("vendor") or "").strip()
        e = info[v]
        e["memo"] += " " + (ln.get("memo") or "")
        opening = any(w in (ln.get("memo") or "") for w in OPENING)
        if ln.get("debit") and not opening and (e["join"] is None or ln["date"] < e["join"]):
            e["join"] = ln["date"]
        if ln.get("credit") and "만기" in (ln.get("memo") or ""):
            e["end"] = ln["date"] if e["end"] is None or ln["date"] > e["end"] else e["end"]
    out = {}
    for v, e in info.items():
        if "정기예금" not in e["memo"]:
            out[v] = (None, False, "정기예금 아님 (공제부금·적금 등)")
            continue
        join = e["join"]
        m = re.search(r"(\d{2})(\d{2})(\d{2})$", v)
        if join is None and m:   # 작년에 가입한 것: 거래처 이름의 가입일
            try:
                join = dt.date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                join = None
        if join and e["end"]:
            days = (e["end"] - join).days
            out[v] = (days, days <= SHORT_DAYS, "가입 %s → 만기 %s" % (join.isoformat(), e["end"].isoformat()))
        else:
            out[v] = (None, None, "만기 전")
    known = [x[1] for x in out.values() if x[0] is not None]
    guess = bool(known) and all(known)
    for v, x in list(out.items()):
        if x[1] is None:
            out[v] = (None, guess, "만기 전 · 지난 정기예금이 %s" % ("모두 3개월 이내라 현금성으로 추정" if guess else "3개월 넘은 적이 있어 단기금융상품으로 봄"))
    return out


def _memo_item(memo):
    if "카드" in memo:
        return "카드"
    if "급여" in memo or "교통통신비" in memo:
        return "급여"
    if "계좌이체" in memo or "대체" in memo:
        return None   # 계좌 사이 이체: 합하면 0
    return "기타"


def build_rows(journal, cash_codes):
    """분개장 줄 → [(일자, 구분, 항목, 금액)] (날짜·항목별 합). 구분 '현금' = 통장 돈이 오간 이유, '변화' = 계정 묶음 증감(대변 − 차변)."""
    codes = set(_sq(c) for c in cash_codes)
    terms = deposit_terms(journal)
    short = set(v for v, x in terms.items() if x[1])

    def is_cash(ln):
        return _sq(ln.get("account_code")) in codes or (_is_deposit(ln) and (ln.get("vendor") or "").strip() in short)
    slips = collections.defaultdict(list)
    for ln in journal:
        if ln.get("date") is not None:
            slips[(ln["date"], ln.get("no"), ln.get("sort", ""))].append(ln)
    agg = collections.defaultdict(int)
    for (d, _, _), lines in slips.items():
        if any(w in (ln.get("memo") or "") for ln in lines for w in OPENING):
            for ln in lines:   # 전기이월이라도 현금성 정기예금 잔액은 이어 받음
                if is_cash(ln) and _sq(ln.get("account_code")) not in codes:
                    agg[(d, "현금성", "정기예금")] += (ln.get("debit") or 0) - (ln.get("credit") or 0)
            continue
        mine = [ln for ln in lines if is_cash(ln)]
        for ln in lines:   # 변화: 통장 아닌 모든 줄 (간접법)
            code = _sq(ln.get("account_code"))
            if is_cash(ln):
                if _sq(ln.get("account_code")) not in codes:   # 현금성 정기예금 잔액 변화 (끝 잔액에 더함)
                    v = (ln.get("debit") or 0) - (ln.get("credit") or 0)
                    if v:
                        agg[(d, "현금성", "정기예금")] += v
                continue
            v = (ln.get("credit") or 0) - (ln.get("debit") or 0)
            if v:
                agg[(d, "변화", {"pl": "이익", "ar": "받을돈", "ap": "줄돈", "pre": "선급", "tax": "세금예수",
                                "other": "그밖", "inv": "투자", "fin": "재무"}[_kind(code, _sq(ln.get("account")))])] += v
        if not mine:
            continue
        c = sum((ln.get("debit") or 0) - (ln.get("credit") or 0) for ln in mine)
        att = 0
        for ln in lines:
            if is_cash(ln):
                continue
            x = (ln.get("credit") or 0) - (ln.get("debit") or 0)
            if x:
                agg[(d, "현금", _cash_item(ln, x))] += x
                att += x
        res = c - att
        if res:
            item = _memo_item(" ".join(ln.get("memo") or "" for ln in mine))
            agg[(d, "현금", item or "이체")] += res
    for v, (days, sh, why) in terms.items():   # 보고서 '만든 기준'에 보일 정기예금 판정 (금액 칸 = 날수, 모르면 −1)
        agg[(dt.date(1900, 1, 1), "예금판정", "%s|%s|%s" % (v, "현금성" if sh else "단기금융상품", why))] = days if days is not None else -1
    return sorted((d, g, k, v) for (d, g, k), v in agg.items() if v or g == "예금판정")


def build_table(books, cfg):
    from .convert import Table
    if books.state != "ok" or not books.journal:
        return Table(FILE, KEYS, [], written=False, reason="분개장 없음 (기존 파일 그대로)")
    rows = build_rows(books.journal, cfg["cash_codes"])
    out = [dict(zip(KEYS, [d.isoformat(), g, k, str(int(v))])) for d, g, k, v in rows]
    days = [r[0] for r in rows if r[1] in FLOW]
    note = "현금흐름표 자료 %d줄 (%s ~ %s)" % (len(out), min(days).isoformat(), max(days).isoformat()) if days else "현금흐름표 자료 없음"
    return Table(FILE, KEYS, out, notes=[note])


# ───────────── 보고 쪽 ─────────────
def load(input_dir):
    path = os.path.join(input_dir, FILE)
    if not os.path.exists(path):
        return None
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            try:
                d = dt.date(*[int(x) for x in (r.get("일자") or "").split("-")])
                v = int(float(r.get("금액") or 0))
            except (ValueError, TypeError):
                continue
            out.append((d, (r.get("구분") or "").strip(), (r.get("항목") or "").strip(), v))
    return out


FLOW = ("현금", "변화")


def _flow_days(rows):
    return [d for d, g, _, _ in rows if g in FLOW]


def short_balance(rows, upto):
    """만기 3개월 이내 정기예금(현금성자산) 잔액: upto 날까지 쌓인 변화."""
    return sum(v for d, g, _, v in rows if g == "현금성" and d <= upto)


def deposit_list(rows):
    """정기예금 판정 [(거래처, 현금성/단기금융상품, 근거, 날수 또는 None)]."""
    out = []
    for _, g, k, v in rows:
        if g == "예금판정":
            a = (k.split("|") + ["", "", ""])[:3]
            out.append((a[0], a[1], a[2], v if v >= 0 else None))
    return out


def _sum(rows, lo, hi, group):
    s = collections.defaultdict(int)
    for d, g, k, v in rows:
        if g == group and lo <= d <= hi:
            s[k] += v
    return s


def period(rows, lo, hi):
    """기간 하나: 현금 항목별 합, 묶음별 합, 맞추기."""
    c, ch = _sum(rows, lo, hi, "현금"), _sum(rows, lo, hi, "변화")
    P = {"cash": dict(c), "total": sum(c.values()),
         "op": sum(c.get(k, 0) for k, _, _ in OPS), "inv": sum(c.get(k, 0) for k, _, _ in INV),
         "fin": sum(c.get(k, 0) for k, _, _ in FIN), "other": sum(v for k, v in c.items() if k not in ALL_CASH)}
    # '기타'·'이체' 처럼 목록 밖 키는 본업 '그 밖' 줄로 (이체는 보통 0)
    P["op"] += P["other"]
    P["cash"]["기타"] = c.get("기타", 0) + sum(v for k, v in c.items() if k not in ALL_CASH)
    rec = dict((k, ch.get(k, 0)) for k, _, _ in GROUPS)
    # 변화 = 대변 − 차변 이라 그대로 현금 쪽 부호다 (자산이 늘면 −, 부채가 늘면 +, 이익이면 +)
    rec["그밖"] = P["op"] - sum(rec[k] for k, _, _ in GROUPS)
    P["rec"] = rec
    return P


def compute(rows, p0, p1, end_balance, start_check=None, label="이번 달"):
    """경영관리 보고의 현금흐름표 숫자. end_balance = 기간 끝 통장 잔액 (보고서 1장과 같은 값, 정기예금 뺌)."""
    if not rows or not _flow_days(rows):
        return None
    y0 = dt.date(p1.year, 1, 1)
    M, Y = period(rows, p0, p1), period(rows, y0, p1)
    have = min(_flow_days(rows))
    short_end = short_balance(rows, p1)   # 현금성 정기예금은 현금에 더함 (통장 ↔ 짧은 예금 이동은 안쪽 이동)
    if end_balance is not None:
        end_balance += short_end
    if start_check is not None:
        start_check = (start_check[0], start_check[1] + short_balance(rows, p0 - dt.timedelta(days=1)))
    CF = {"p0": p0, "p1": p1, "y0": y0, "label": label, "M": M, "Y": Y, "end": end_balance, "_rows": rows,
          "year_partial": have > y0, "first_day": have, "start_check": start_check,
          "short_end": short_end, "deposits": deposit_list(rows)}
    if end_balance is not None:
        CF["start"] = end_balance - M["total"]
        CF["ystart"] = end_balance - Y["total"]
    months = []
    if end_balance is not None:
        b = CF["ystart"]
        for m in range(1, p1.month + 1):
            lo = dt.date(p1.year, m, 1)
            hi = min(p1, (dt.date(p1.year + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)))
            f = period(rows, lo, hi)
            b += f["total"]
            months.append((m, f["op"], f["inv"], f["fin"], b))
    CF["months"] = months
    return CF


def annual(rows, year, end_balance, start_balance=None):
    """연간: 1~12월 (또는 자료 있는 마지막 날까지)."""
    if not rows:
        return None
    mine = [d for d in _flow_days(rows) if d.year == year]
    if not mine:
        return None
    last = max(mine)
    p1 = min(dt.date(year, 12, 31), last) if last.year == year else dt.date(year, 12, 31)
    CF = compute(rows, dt.date(year, 1, 1), p1, end_balance, label="%d년" % year)
    if CF and start_balance is not None and CF.get("ystart") is not None:
        CF["start_check"] = ("장부 1월 1일 잔액", start_balance + short_balance(rows, dt.date(year - 1, 12, 31)))
    CF["annual"] = True
    return CF


# ───────────── 대금 회수 날수 (사용자 2026-11-12) ─────────────
def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _d(text):
    try:
        return dt.date(*[int(x) for x in (text or "").strip().split("-")])
    except (ValueError, TypeError):
        return None


def _i(text):
    try:
        return int(float(str(text or "").replace(",", "").strip() or 0))
    except ValueError:
        return 0


def collection(input_dir, p0, p1):
    """계산서.csv (발행일·입금일·입금액) + 프로젝트.csv (행사 끝난 날) → 대금 회수 날수.

    - 계산서 → 입금: 입금된 계산서마다 (입금일 − 발행일), 입금액으로 가중 평균. 달은 입금한 달 기준.
    - 행사 끝 → 입금: 프로젝트 번호가 있고 행사 끝난 날을 아는 계산서만 (선입금은 따로 셈).
    - 아직 못 받은 계산서: 기간 끝(p1) 기준 발행 뒤 지난 날수로 나눔. 입금일이 p1 뒤면 p1 에는 못 받은 것으로 본다.
    """
    inv = _read_csv(os.path.join(input_dir, "계산서.csv"))
    if not inv:
        return None
    projs = dict((r.get("프로젝트번호", "").strip(), r) for r in _read_csv(os.path.join(input_dir, "프로젝트.csv")) if r.get("프로젝트번호"))

    def end_of(pid):
        p = projs.get((pid or "").strip())
        if not p:
            return None
        from .calc import _event_date
        return _d(p.get("완료일")) or _event_date(p.get("행사일"))
    y0 = dt.date(p1.year, 1, 1)
    by_m = collections.defaultdict(lambda: [0, 0, 0])      # 입금한 달 → [날수×금액, 금액, 건수]
    ev = collections.defaultdict(lambda: [0, 0, 0, 0])     # 기간 → [날수×금액, 금액, 건수, 선입금 건수]
    open_rows = []
    for r in inv:
        iss, paid, amt = _d(r.get("발행일")), _d(r.get("입금일")), _i(r.get("입금액"))
        if iss is None or iss > p1:
            continue
        if paid is not None and paid <= p1 and amt > 0:
            days = max((paid - iss).days, 0)
            k = (paid.year, paid.month)
            by_m[k][0] += days * amt
            by_m[k][1] += amt
            by_m[k][2] += 1
            e = end_of(r.get("프로젝트번호"))
            if e is not None and paid >= y0:
                for key in ("ytd",) + (("cur",) if paid >= p0 else ()):
                    if paid >= e:
                        ev[key][0] += (paid - e).days * amt
                        ev[key][1] += amt
                        ev[key][2] += 1
                    else:
                        ev[key][3] += 1
        total = _i(r.get("공급가액")) + _i(r.get("부가세"))
        got = amt if (paid is not None and paid <= p1 and amt > 0) else 0
        if (total and (paid is None or paid > p1)) or (got and total - got > 0):   # 일부만 받은 계산서는 남은 돈도 못 받은 돈으로 (코덱스 검토 2026-11-14)
            open_rows.append(((r.get("거래처") or "").strip(), iss, total - got, (p1 - iss).days))

    def avg(keys):
        a = sum(by_m[k][0] for k in keys)
        b = sum(by_m[k][1] for k in keys)
        return (round(a / float(b)), b, sum(by_m[k][2] for k in keys)) if b else None
    months = [(m, avg([(p1.year, m)])) for m in range(1, p1.month + 1)]
    cur_keys = [(p1.year, m) for m in range(p0.month, p1.month + 1)] if p0.year == p1.year else [(p1.year, p1.month)]
    recent = [(p1.year, m) for m in range(max(1, p1.month - 2), p1.month + 1)]
    early = [(p1.year, m) for m in range(1, max(1, p1.month - 2))]
    open_rows = _net_open(open_rows)
    buckets = [("30일 안", 0, 30), ("31~60일", 31, 60), ("61~90일", 61, 90), ("90일 넘음", 91, 10 ** 6)]
    bk = []
    for nm, lo, hi in buckets:
        rows = [x for x in open_rows if lo <= x[3] <= hi]
        bk.append((nm, sum(x[2] for x in rows), len(rows)))
    late = collections.defaultdict(lambda: [0, 0])
    for v, iss, amt, days in open_rows:
        if days > 60:
            late[v][0] += amt
            late[v][1] = max(late[v][1], days)
    late = sorted([(v, a, d) for v, (a, d) in late.items() if a > 0], key=lambda x: -x[1])[:5]
    ev_avg = lambda k: (round(ev[k][0] / float(ev[k][1])), ev[k][2], ev[k][3]) if ev[k][1] else None
    return {"months": months, "cur": avg(cur_keys), "recent": avg(recent), "early": avg(early) if early else None,
            "ytd": avg([(p1.year, m) for m in range(1, p1.month + 1)]),
            "open_total": sum(x[2] for x in open_rows), "buckets": bk, "late": late,
            "ev_cur": ev_avg("cur"), "ev_ytd": ev_avg("ytd"), "have_projects": bool(projs)}


def _net_open(rows):
    """못 받은 계산서에서 수정(−) 계산서를 지운다: 같은 거래처·같은 금액 원본과 짝짓고(가까운 날짜 먼저), 남은 −는 가장 오래된 것부터 줄인다."""
    by = collections.defaultdict(list)
    for x in rows:
        by[x[0]].append(list(x))
    out = []
    for v, lst in by.items():
        pos = sorted([x for x in lst if x[2] > 0], key=lambda x: x[1])
        neg = [x for x in lst if x[2] < 0]
        for n in neg:
            same = [p_ for p_ in pos if p_[2] == -n[2]]
            if same:
                pos.remove(min(same, key=lambda p_: abs((p_[1] - n[1]).days)))
                continue
            left = -n[2]
            for p_ in pos:
                take = min(left, p_[2])
                p_[2] -= take
                left -= take
                if not left:
                    break
        out += [tuple(p_) for p_ in pos if p_[2] > 0]
    return out


def _collect_html(CF):
    C_ = CF.get("collect")
    if not C_:
        return ("<div class='q'>대금 회수에 걸리는 날수</div><div class='note'>계산서 자료(계산서.csv)가 없어 계산하지 못했습니다.</div>")
    lab = CF["label"]
    h = ["<div class='q'>대금 회수에 걸리는 날수</div>",
         "<div class='note'>계산서를 낸 날부터 돈이 통장에 들어온 날까지 걸린 날수입니다 (입금액이 큰 건을 더 무겁게 쳐서 평균). "
         "짧을수록 번 돈이 빨리 현금이 됩니다. 이 날수가 길어지면 이익이 나도 통장 돈이 모자랍니다.</div>"]
    cards = []
    if CF.get("annual"):
        cards.append(("%s 평균" % lab, C_["ytd"]))
    else:
        cards.append(("%s 받은 돈" % lab, C_["cur"]))
        cards.append(("최근 3달", C_["recent"]))
        cards.append(("올해 누적", C_["ytd"]))
    h.append("<div class='four c3'>")
    for nm, v in cards:
        h.append(_card(nm, ("%d일" % v[0]) if v else "—", ("입금 %s원 · %d건" % (W(v[1]), v[2])) if v else "이 기간 입금 없음"))
    h.append("</div>")
    tr = _collect_trend(C_)
    if tr:
        h.append("<div class='say'>%s</div>" % esc(tr[0]))
    if C_.get("ev_ytd"):
        e = C_["ev_ytd"]
        h.append("<div class='note'>행사가 끝난 날부터 따지면 올해 평균 %d일입니다 (%d건%s).</div>"
                 % (e[0], e[1], ", 행사 전에 먼저 받은 것 %d건은 뺌" % e[2] if e[2] else ""))
    ms = [m for m in C_["months"] if m[1]]
    if ms:
        h.append("<div class='tw'><table class='mo' style='margin-top:6px'><thead><tr><th>입금한 달</th>%s</tr></thead><tbody>"
                 % "".join("<th>%d월</th>" % m for m, _ in C_["months"]))
        h.append("<tr class='bl'><td>회수 날수</td>%s</tr>" % "".join("<td>%s</td>" % ("%d일" % v[0] if v else "—") for _, v in C_["months"]))
        h.append("<tr><td>받은 금액</td>%s</tr></tbody></table></div>" % "".join("<td>%s</td>" % (eok(v[1]) if v else "—") for _, v in C_["months"]))
    h.append("<div class='wsub'>%s 기준 아직 못 받은 계산서 %s원 — 낸 지 며칠 됐나</div>" % (_md(CF["p1"]), W(C_["open_total"])))
    h.append("<div class='tw'><table class='cf'><thead><tr><th>지난 날수</th><th>금액</th><th>건수</th></tr></thead><tbody>%s</tbody></table></div>"
             % "".join("<tr><td>%s</td><td>%s</td><td>%d건</td></tr>" % (nm, W(a), n) for nm, a, n in C_["buckets"]))
    if C_["late"]:
        h.append("<div class='note'>60일 넘게 못 받은 곳: %s</div>"
                 % esc(" · ".join("%s %s원(%d일)" % (v, W(a), d) for v, a, d in C_["late"])))
    return "".join(h)


def _collect_trend(C_):
    """회수 날수 추세 한 줄 + 수준('ok'/'warn'/'info'). 최근 3달 vs 그 전 달들."""
    r, e = C_.get("recent"), C_.get("early")
    if not r or not e:
        return None
    d = r[0] - e[0]
    if d >= 10:
        return ("최근 3달 회수 날수가 %d일로, 그 전 달들(%d일)보다 %d일 길어졌습니다. 같은 매출이라도 통장에 돈이 늦게 들어오고 있다는 신호입니다." % (r[0], e[0], d), "warn")
    if d <= -10:
        return ("최근 3달 회수 날수가 %d일로, 그 전 달들(%d일)보다 %d일 짧아졌습니다. 번 돈이 더 빨리 들어오고 있습니다." % (r[0], e[0], -d), "ok")
    return ("최근 3달 회수 날수는 %d일로 그 전 달들(%d일)과 비슷합니다. 돈이 묶이는 이유는 회수가 늦어져서라기보다 일이 늘어서입니다." % (r[0], e[0]), "info")


def for_report(input_dir, R):
    """월간 보고 R → 현금흐름표 숫자. 끝 잔액 = 1장 계좌 잔액 합(정기예금 줄 뺌, 잔액 모르는 계좌가 있으면 None)."""
    rows = load(input_dir)
    if not rows:
        return None
    p0, p1 = R["period"]
    s1 = R.get("s1") or {}
    accts = [a for a in s1.get("accounts") or [] if not str(a.get("account", "")).startswith("정기예금")]
    end = None
    if accts and all(a.get("balance") is not None for a in accts):
        end = sum(a["balance"] for a in accts)
    chk = None
    if s1.get("start_bank") is not None and not any(str(a.get("account", "")).startswith("정기예금") for a in s1.get("accounts") or []):
        chk = ("%s 은행 잔액" % _md(p0), s1["start_bank"])
    label = "%d월" % p1.month if p0.day == 1 and p0.month == p1.month else "이번 기간"
    CF = compute(rows, p0, p1, end, chk, label)
    if CF is not None:
        CF["collect"] = collection(input_dir, p0, p1)
    return CF


# ───────────── 그리기 ─────────────
CSS = """<style>
.cfx .pin{color:var(--in);font-weight:700}.cfx .pout{color:var(--out);font-weight:700}.cfx .z{color:var(--sub)}
.cfx table.cf{width:100%;border-collapse:collapse;font-size:12.5px;font-variant-numeric:tabular-nums}
.cfx table.cf th{font-size:11.5px;color:var(--sub);font-weight:700;text-align:right;padding:4px 8px;border-bottom:1.5px solid var(--ink)}
.cfx table.cf th:first-child{text-align:left}
.cfx table.cf tr{break-inside:avoid}
.cfx table.cf td{padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top;text-align:right;white-space:nowrap}
.cfx table.cf td:first-child{text-align:left;white-space:normal}
.cfx table.cf td .ex{display:block;font-size:10.8px;color:var(--sub);font-weight:400;line-height:1.45;margin-top:1px}
.cfx table.cf td .nm{font-weight:700}
.cfx table.cf tr.xgh td{background:var(--soft);border-top:2px solid var(--ink);border-bottom:1px solid var(--ink);padding-top:7px}
.cfx table.cf tr.xgh td .gt{font-size:13.5px;font-weight:800}
.cfx table.cf tr.xgh td .acc{font-size:10.5px;color:var(--sub);font-weight:600;margin-left:6px}
.cfx table.cf tr.xst td{font-weight:800;border-bottom:1.5px solid var(--ink)}
.cfx table.cf tr.xbal td{font-weight:800;font-size:13.5px;background:var(--soft);border-top:2px solid var(--ink)}
.cfx table.cf tr.xchk td{font-size:11px;color:var(--sub);border-bottom:none}
.cfx .how{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:6px 0 2px}
.cfx .how .card{padding:8px 10px}.cfx .how .t{font-weight:800;font-size:13px;margin-bottom:3px}.cfx .how .d{font-size:11.2px;color:var(--sub);line-height:1.5}
.cfx .how .k{display:inline-block;width:20px;height:20px;border-radius:50%;background:var(--accent);color:#fff;text-align:center;font-size:12px;line-height:20px;margin-right:6px}
.cfx .say{font-size:12.6px;line-height:1.65;padding:8px 12px;border-left:4px solid var(--accent);background:var(--soft);border-radius:4px;margin:8px 0}
.cfx .gl{display:grid;grid-template-columns:1fr 1fr;gap:6px 14px;font-size:11.6px;line-height:1.55}
.cfx .gl div b{display:block;font-size:12.4px}
.cfx .lim{font-size:11px;color:var(--sub);line-height:1.6;margin:0;padding-left:18px}.cfx .lim li{margin:2px 0}
.cfx table.mo{width:100%;border-collapse:collapse;font-size:10.6px;font-variant-numeric:tabular-nums;table-layout:fixed}
.cfx table.mo th,.cfx table.mo td{padding:3px 2px;text-align:right;border-bottom:1px solid var(--line)}
.cfx table.mo th:first-child,.cfx table.mo td:first-child{text-align:left;width:92px}
.cfx table.mo th{color:var(--sub);border-bottom:1.5px solid var(--ink)}.cfx table.mo tr.bl td{font-weight:800;border-top:1.5px solid var(--ink)}
.cfx .dg{padding:10px 12px}.cfx .dh{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}.cfx .dn{font-size:17px;font-weight:800}.cfx .db{font-size:11px;color:var(--sub)}
.cfx .sgs{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:8px 0}.cfx .sg{border:1px solid var(--line);border-radius:6px;padding:6px 8px;text-align:center}
.cfx .sg .l{font-size:11.5px;color:var(--sub);font-weight:700}.cfx .sg .v{font-size:22px;font-weight:800;line-height:1.2}.cfx .sg .w{font-size:11px;color:var(--sub)}
.cfx .dw{font-size:13px;font-weight:700;margin:4px 0}.cfx .dy{font-size:11.8px;line-height:1.6;margin:4px 0;padding-left:18px}
.cfx .il{font-size:11.6px;line-height:1.55}.cfx .q{break-after:avoid}
.cfx table.hc td:first-child{width:34%;font-weight:700}.cfx table.hc .ik{display:inline-block;width:18px;height:18px;border-radius:50%;color:#fff;text-align:center;font-size:11px;line-height:18px;margin-right:6px}
.cfx .imp{display:grid;grid-template-columns:1fr;gap:6px}.cfx .imp .card{padding:8px 10px;break-inside:avoid}
.cfx .imp .it{font-weight:800;font-size:12.8px;margin-bottom:3px}.cfx .imp .ik{display:inline-block;width:18px;height:18px;border-radius:50%;color:#fff;text-align:center;font-size:11px;line-height:18px;margin-right:6px}.cfx .imp .ib{font-size:11.6px;line-height:1.55}
.cfx .ins{display:grid;grid-template-columns:1fr 1fr;gap:8px}.cfx .ins .card{padding:8px 10px;break-inside:avoid}
.cfx .ins .it{font-weight:800;font-size:12.8px;margin-bottom:3px}.cfx .ins .ik{display:inline-block;width:18px;height:18px;border-radius:50%;color:#fff;text-align:center;font-size:11px;line-height:18px;margin-right:6px}
.cfx .ins .ib{font-size:11.6px;line-height:1.55}.cfx .ins .il{font-size:11px;color:var(--sub);margin-top:3px;line-height:1.5}
@media (max-width:700px){.cfx .how,.cfx .gl,.cfx .ins{grid-template-columns:1fr}}
@media print{.cfx .cfpg{break-before:page}}
</style>"""


def W(v):
    return "—" if v is None else ("{:,}".format(v) if v >= 0 else "−{:,}".format(-v))


def SW(v):
    if not v:
        return "<span class='z'>—</span>"
    return "<span class='%s'>%s%s</span>" % ("pin" if v > 0 else "pout", "+" if v > 0 else "−", "{:,}".format(abs(v)))


def eok(v):
    a, s = abs(v), "−" if v < 0 else ""
    if a >= 100_000_000:
        return s + ("%.1f억" % (a / 1e8)).replace(".0억", "억")
    if a >= 10_000:
        return s + "{:,}만".format(int(round(a / 10000)))
    return s + "{:,}".format(a)


def _md(d):
    return "%d월 %d일" % (d.month, d.day)


def _waterfall(steps, end_label, W_=1000, H=300):
    vals, run = [], 0
    for lab, v, kind in steps:
        if kind == "start":
            vals.append((lab, 0, v, "start"))
            run = v
        else:
            vals.append((lab, run, run + v, "up" if v >= 0 else "down"))
            run += v
    vals.append((end_label, 0, run, "end"))
    lo = min(0, min(min(a, b) for _, a, b, _ in vals))
    hi = max(0, max(max(a, b) for _, a, b, _ in vals))
    if hi == lo:
        hi = lo + 1
    pt, pb, pl = 26, 70, 10
    y = lambda v: pt + (hi - v) * (H - pt - pb) / float(hi - lo)
    n = len(vals)
    bw = (W_ - 2 * pl) / float(n)
    col = {"start": "#1f3a5f", "end": "#1f3a5f", "up": "#2e8b57", "down": "#c0392b"}
    s = ['<svg viewBox="0 0 %d %d" width="100%%" role="img" aria-label="이익에서 현금까지">' % (W_, H),
         '<line x1="0" x2="%d" y1="%.1f" y2="%.1f" stroke="#9aa3b2"/>' % (W_, y(0), y(0))]
    for i, (lab, a, b2, k) in enumerate(vals):
        x, ww = pl + i * bw + bw * 0.16, bw * 0.68
        top, bot = y(max(a, b2)), y(min(a, b2))
        s.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" rx="2"/>' % (x, top, ww, max(bot - top, 1.5), col[k]))
        v = b2 - a if k in ("up", "down") else b2
        txt = ("+" if k == "up" else "") + eok(v)
        ty = bot + 14 if (k == "down" or (k in ("start", "end") and v < 0)) else top - 6
        s.append('<text x="%.1f" y="%.1f" font-size="15" font-weight="700" text-anchor="middle" fill="%s">%s</text>' % (x + ww / 2, ty, col[k], txt))
        if i < n - 1:
            s.append('<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="#9aa3b2" stroke-dasharray="3 3"/>'
                     % (x + ww, pl + (i + 1) * bw + bw * 0.16, y(b2), y(b2)))
        for j, part in enumerate(lab.split("|")):
            s.append('<text x="%.1f" y="%.1f" font-size="13" text-anchor="middle" fill="#2b3240">%s</text>' % (x + ww / 2, H - pb + 36 + j * 16, esc(part)))
    s.append("</svg>")
    return "".join(s)


def _month_bars(months, W_=1000, H=210):
    vals = [m[1] for m in months]
    lo, hi = min([0] + vals), max([0] + vals)
    if hi == lo:
        hi = lo + 1
    pt, pb = 22, 44
    y = lambda v: pt + (hi - v) * (H - pt - pb) / float(hi - lo)
    bw = W_ / float(max(len(months), 1))
    s = ['<svg viewBox="0 0 %d %d" width="100%%" role="img" aria-label="달마다 본업 현금">' % (W_, H),
         '<line x1="0" x2="%d" y1="%.1f" y2="%.1f" stroke="#9aa3b2"/>' % (W_, y(0), y(0))]
    for i, (m, op, _, _, _) in enumerate(months):
        x, ww = i * bw + bw * .2, bw * .6
        top, bot = y(max(op, 0)), y(min(op, 0))
        c = "#2e8b57" if op >= 0 else "#c0392b"
        s.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" rx="2"/>' % (x, top, ww, max(bot - top, 1.5), c))
        s.append('<text x="%.1f" y="%.1f" font-size="13" font-weight="700" text-anchor="middle" fill="%s">%s</text>'
                 % (x + ww / 2, top - 5 if op >= 0 else bot + 14, c, ("+" if op > 0 else "") + eok(op)))
        s.append('<text x="%.1f" y="%d" font-size="13" text-anchor="middle" fill="#2b3240">%d월</text>' % (x + ww / 2, H - 6, m))
    s.append("</svg>")
    return "".join(s)


def render(CF):
    """경영관리 보고 한 영역 (HTML 조각). CF = compute()/annual() 결과."""
    if CF is None:
        return ("<div class='note'>현금흐름표 자료 없음 — 위하고 분개장을 받아 '자료 변환'을 다시 하면 현금흐름.csv 가 생깁니다.</div>")
    M, Y, ann = CF["M"], CF["Y"], CF.get("annual")
    lab = CF["label"]
    ylab = "%d월~%d월 누적" % (CF["y0"].month, CF["p1"].month)
    cols = [(lab, M)] if ann else [(lab, M), (ylab, Y)]
    h = [CSS, "<div class='cfx'>"]
    end, start, ystart = CF.get("end"), CF.get("start"), CF.get("ystart")
    # 카드 4개
    h.append("<div class='four top'>")
    if ann:
        h.append(_card("1월 1일 통장 잔액", W(ystart), "한 해가 시작할 때 있던 돈"))
        h.append(_card("한 해 동안 늘어난·줄어든 돈", SW(M["total"]), "들어온 돈 − 나간 돈"))
        h.append(_card("%s 통장 잔액" % _md(CF["p1"]), W(end), "보고서 통장 잔액과 같은 값"))
        h.append(_card("① 본업으로 들어온 현금", SW(M["op"]), "장부상 이익 %s" % W(M["rec"]["이익"])))
    else:
        h.append(_card("%s 통장 잔액" % _md(CF["p0"]), W(start), "기간이 시작할 때 있던 돈"))
        h.append(_card("%s 늘어난·줄어든 돈" % lab, SW(M["total"]), "들어온 돈 − 나간 돈"))
        h.append(_card("%s 통장 잔액" % _md(CF["p1"]), W(end), "보고서 통장 잔액과 같은 값"))
        h.append(_card("올해 %s 통장 변화" % ylab.replace(" 누적", ""), SW(Y["total"]), "1월 1일 %s → %s" % (W(ystart), _md(CF["p1"]))))
    h.append("</div>")
    # 한 줄 요약 (사실만)
    r = M["rec"]
    say = ["<b>%s</b> · 장부상 이익은 <b>%s원</b>, 본업에서 통장으로 들어온 현금은 <b>%s원</b>입니다." % (lab, W(r["이익"]), W(M["op"]))]
    big = max(((k, v) for k, v in r.items() if k not in ("이익", "그밖")), key=lambda kv: abs(kv[1]), default=None)
    if big and big[1]:
        nm = dict((k, n) for k, n, _ in GROUPS)[big[0]]
        say.append(" 차이가 가장 큰 것은 ‘%s’(%s원)입니다." % (nm, SW(big[1])))
    if not ann:
        say.append("<br><b>%s</b> · 장부상 이익 <b>%s원</b>, 본업 현금 <b>%s원</b>, ② 묶어 둔 돈 %s원, ③ 빌리고 갚은 돈 %s원."
                   % (ylab, W(Y["rec"]["이익"]), W(Y["op"]), SW(Y["inv"]), SW(Y["fin"])))
    h.append("<div class='say'>%s</div>" % "".join(say))
    # 읽는 법
    h.append("<div class='q'>현금흐름표 읽는 법</div><div class='how'>"
             "<div class='card'><div class='t'><span class='k'>1</span>본업</div><div class='d'>행사를 해서 받은 돈과 행사·회사 운영에 쓴 돈. 회사가 스스로 돈을 버는 힘을 보여 줍니다. 여러 달을 묶어 보면 <b>+</b>여야 건강합니다.</div></div>"
             "<div class='card'><div class='t'><span class='k'>2</span>묶어 둔 돈</div><div class='d'>만기 3개월 넘는 예금·보증금처럼 잠시 맡겨 둔 돈. 통장에선 빠지지만 회사 재산으로 남아 있습니다.</div></div>"
             "<div class='card'><div class='t'><span class='k'>3</span>빌리고 갚은 돈</div><div class='d'>대출 받기·갚기, 대표이사 돈 받기·돌려드리기. 들어와도 <b>번 돈이 아니라 갚을 돈</b>입니다.</div></div>"
             "</div><div class='note'>세 칸을 더하면 통장 잔액이 늘거나 준 만큼과 정확히 같습니다. <span class='pin'>+초록</span>은 통장에 들어온 돈, <span class='pout'>−빨강</span>은 나간 돈입니다.</div>")
    # 본표
    h.append("<div class='q'>현금흐름표</div><div class='tw'><table class='cf'><thead><tr><th>항목</th>%s</tr></thead><tbody>"
             % "".join("<th>%s</th>" % esc(c) for c, _ in cols))
    for title, acc, desc, items, key, sl in (
            ("① 본업으로 들어오고 나간 돈", "영업활동 현금흐름", "행사 대행이라는 회사 본업에서 생긴 돈의 흐름", OPS, "op", "① 본업 합계"),
            ("② 묶어 두거나 찾은 돈", "투자활동 현금흐름", "남는 돈을 맡기거나, 나중에 돌려받을 돈을 맡긴 흐름", INV, "inv", "② 묶어 둔 돈 합계"),
            ("③ 빌리고 갚은 돈", "재무활동 현금흐름", "회사 밖에서 돈을 빌리거나 갚은 흐름", FIN, "fin", "③ 빌리고 갚은 돈 합계")):
        h.append("<tr class='xgh'><td colspan='%d'><span class='gt'>%s</span><span class='acc'>%s</span><span class='ex'>%s</span></td></tr>"
                 % (len(cols) + 1, title, acc, desc))
        for k, nm, ex in items:
            vs = [P["cash"].get(k, 0) for _, P in cols]
            if not any(vs):
                continue
            h.append("<tr><td><span class='nm'>%s</span><span class='ex'>%s</span></td>%s</tr>" % (nm, ex, "".join("<td>%s</td>" % SW(v) for v in vs)))
        h.append("<tr class='xst'><td>%s</td>%s</tr>" % (sl, "".join("<td>%s</td>" % SW(P[key]) for _, P in cols)))
    h.append("<tr class='xst'><td>통장에 늘어난·줄어든 돈 (① + ② + ③)</td>%s</tr>" % "".join("<td>%s</td>" % SW(P["total"]) for _, P in cols))
    starts = [ystart] if ann else [start, ystart]
    h.append("<tr><td>시작할 때 통장 잔액</td>%s</tr>" % "".join("<td>%s</td>" % W(v) for v in starts))
    h.append("<tr class='xbal'><td>끝날 때 통장 잔액</td>%s</tr>" % "".join("<td>%s</td>" % W(end) for _ in cols))
    h.append("<tr class='xchk'><td colspan='%d'>%s</td></tr>" % (len(cols) + 1, _check_text(CF)))
    h.append("</tbody></table></div>")
    h.append(_health_html(CF))
    h.append(_diag_html(CF))
    h.append(_collect_html(CF))
    h.append(_insight_html(CF))
    h.append(_improve_html(CF))
    # 이익과 현금
    h.append("<div><div class='sec' style='break-inside:avoid'><div class='q'>이익이 났는데 왜 통장 돈은 다른가요? (%s)</div>" % esc(lab))
    h.append("<div class='note' style='font-size:12px'>장부상 이익은 ‘일한 만큼’ 계산하고, 통장은 ‘돈이 실제로 오간 만큼’ 움직입니다. "
             "둘 사이의 차이를 아래처럼 차례로 맞추면 ① 본업 합계와 정확히 같아집니다.</div>")
    steps = [("장부상 이익", r["이익"], "start"), ("아직 못 받은|매출 대금", r["받을돈"], "d"), ("아직 안 준|업체·카드·급여", r["줄돈"], "d"),
             ("미리 준 돈|정리", r["선급"], "d"), ("부가세·원천세|맡아 둔 돈", r["세금예수"], "d")]
    if r["그밖"]:
        steps.append(("그 밖의|차이", r["그밖"], "d"))
    h.append("<div class='card'>%s</div></div>" % _waterfall(steps, "① 본업 현금|(%s)" % lab))
    h.append("<div class='tw'><table class='cf' style='margin-top:8px'><thead><tr><th>맞추는 순서</th>%s</tr></thead><tbody>"
             % "".join("<th>%s</th>" % esc(c) for c, _ in cols))
    grp = list(GROUPS) + ([("그밖", "그 밖의 차이", "위 묶음에 들지 않는 장부 계정의 변화입니다. 크면 장부 확인이 필요합니다.")]
                          if any(P["rec"]["그밖"] for _, P in cols) else [])
    for i, (k, nm, ex) in enumerate(grp):
        h.append("<tr><td><span class='nm'>%s</span><span class='ex'>%s</span></td>%s</tr>"
                 % (nm, ex, "".join("<td>%s</td>" % (W(P["rec"][k]) if i == 0 else SW(P["rec"][k])) for _, P in cols)))
    h.append("<tr class='xst'><td>= ① 본업으로 들어온 현금</td>%s</tr></tbody></table></div>" % "".join("<td>%s</td>" % SW(P["op"]) for _, P in cols))
    # 달마다
    months = CF.get("months") or []
    if len(months) > 1:
        h.append("<div class='sec' style='break-inside:avoid'><div class='q'>달마다 본업 현금 (%d월~%d월)</div><div class='card'>%s</div></div>" % (months[0][0], months[-1][0], _month_bars(months)))
        h.append("<div class='tw'><table class='mo' style='margin-top:6px'><thead><tr><th></th>%s</tr></thead><tbody>"
                 % "".join("<th>%d월</th>" % m[0] for m in months))
        for nm, i in (("① 본업", 1), ("② 묶어 둔 돈", 2), ("③ 빌리고 갚은 돈", 3)):
            h.append("<tr><td>%s</td>%s</tr>" % (nm, "".join("<td>%s</td>" % (eok(m[i]) if m[i] else "—") for m in months)))
        h.append("<tr class='bl'><td>월말 통장 잔액</td>%s</tr></tbody></table></div>" % "".join("<td>%s</td>" % eok(m[4]) for m in months))
        h.append("<div class='note'>행사 대금은 행사가 끝나고 한두 달 뒤에 들어오는 일이 많아 본업 현금은 달마다 크게 오르내립니다. "
                 "여러 달을 묶어 보는 것이 정확합니다. (이 표의 금액은 억·만 원으로 줄여 적음)</div>")
    h.append("</div>")
    # 낱말 풀이 · 기준
    h.append("<div class='cfpg'><div class='q'>낱말 풀이</div><div class='card'><div class='gl'>%s</div></div>"
             % "".join("<div><b>%s</b>%s</div>" % (esc(a), esc(b)) for a, b in GLOSSARY))
    h.append("<div class='q'>이 표를 만든 기준</div><div class='card'><ul class='lim'>"
             "<li><b>통장</b>은 장부의 보통예금 계좌 전체입니다. 계좌끼리 옮긴 돈은 들어오고 나간 것이 같아 0으로 빠집니다.</li>"
             "<li><b>정기예금</b>은 가입할 때 만기가 3개월 이내면 현금(현금성자산)으로 보아 통장 돈에 더했고, 3개월이 넘거나 적금·공제부금이면 ‘단기금융상품’으로 ②에 넣었습니다.%s</li>"
             "<li><b>이자</b>는 일반기업회계기준대로 ① 본업에 넣었습니다(받은 이자·낸 이자 모두).</li>"
             "<li>각 줄은 통장 전표의 상대 계정으로 나눴습니다. 상대 계정이 없는 통장 전표(급여·카드 대금 일부)는 적요로 나눴습니다.</li>"
             "<li>끝날 때 잔액은 이 보고서 1장의 통장 잔액(정기예금 뺀 금액)%s이고, 시작 잔액은 거기서 이 기간 흐름을 거꾸로 빼서 구했습니다.</li>"
             "</ul></div></div>" % (_deposit_text(CF), " + 만기 3개월 이내 정기예금 %s원" % W(CF["short_end"]) if CF.get("short_end") else ""))
    h.append("</div>")
    return "".join(h)


def insights(CF):
    """이 표로 알 수 있는 것 (사용자 2026-11-12: 현금흐름표를 만들 때마다 그 숫자로 쉬운 말 풀이를 아래에 붙임).
    -> [(제목, 풀이, 볼 것, 수준)] 수준 'ok'·'warn'·'info'. 숫자에서 나오는 사실과 그래서 확인할 것만 쓴다."""
    out = []
    M, Y, ann = CF["M"], CF["Y"], CF.get("annual")
    P = M if ann else Y            # 여러 달을 묶어 보는 기준 (월간은 올해 누적)
    plab = CF["label"] if ann else "올해 %d월~%d월" % (CF["y0"].month, CF["p1"].month)
    lab = CF["label"]
    r, pr = M["rec"], P["rec"]
    # 1. 이익이 현금으로 바뀐 정도
    if pr["이익"] > 0:
        ratio = P["op"] / float(pr["이익"])
        if ratio >= 0.8:
            out.append(("이익이 현금으로 잘 들어오고 있습니다",
                        "%s 장부상 이익 %s원 중 본업 현금으로 %s원이 들어왔습니다. 이익 100원당 현금 %d원입니다." % (plab, W(pr["이익"]), W(P["op"]), round(ratio * 100)),
                        "지금처럼 행사 뒤 대금을 제때 받는지 계속 보면 됩니다.", "ok"))
        else:
            out.append(("이익만큼 현금이 들어오지 않았습니다",
                        ("%s 장부상 이익은 %s원인데 본업 현금은 %s원입니다. " % (plab, W(pr["이익"]), W(P["op"])))
                        + ("이익 100원당 현금 %d원입니다. " % round(ratio * 100) if P["op"] > 0 else "이익은 났는데 본업 현금은 오히려 빠져나갔습니다. ")
                        + "돈이 아직 다른 곳(주로 받을 돈)에 묶여 있다는 뜻입니다.",
                        "‘못 받은 매출 대금’ 풀이와 계산서·수금 장의 미수금 목록을 함께 보세요.", "warn"))
    elif pr["이익"] < 0:
        out.append(("장부상 손실입니다",
                    "%s 장부상 이익이 %s원(손실)입니다. 본업 현금은 %s원입니다." % (plab, W(pr["이익"]), W(P["op"])),
                    "손실이 이어지면 통장 돈이 줄어듭니다. 매출·손익 장의 비용 항목을 보세요.", "warn"))
    # 2. 받을 돈
    for nm_, PP in ((lab, M), (plab, P)) if not ann else ((lab, M),):
        v = PP["rec"]["받을돈"]
        if v < 0 and abs(v) >= max(abs(PP["rec"]["이익"]) * 0.3, 10_000_000):
            out.append(("못 받은 매출 대금이 늘었습니다 (%s)" % nm_,
                        "%s 아직 입금되지 않은 매출 대금이 %s원 늘었습니다. 그만큼 이익은 났지만 통장에는 아직 없습니다." % (nm_, W(-v)),
                        "입금일이 지난 고객이 있는지 계산서·수금 장에서 확인하세요.", "warn"))
            break
        if v > 0 and v >= 10_000_000:
            out.append(("밀린 대금을 많이 받았습니다 (%s)" % nm_,
                        "%s 예전에 매출로 잡아 둔 대금 중 %s원이 들어와 받을 돈이 줄었습니다." % (nm_, W(v)),
                        "이번 기간 현금이 이익보다 많은 이유입니다. 다음 기간에도 같은 수준을 기대하긴 어렵습니다.", "info"))
            break
    # 3. 줄 돈이 늘었으면 곧 나갈 돈
    if r["줄돈"] > 0 and r["줄돈"] >= 10_000_000:
        out.append(("곧 나갈 돈이 쌓였습니다",
                    "%s 아직 주지 않은 업체·카드·급여 대금이 %s원 늘었습니다. 이번 통장 잔액에는 이 돈이 아직 남아 있습니다." % (lab, W(r["줄돈"])),
                    "다음 달 지급 일정(입금·지급 일정 장)에 이 금액이 잡혀 있는지 확인하세요.", "info"))
    # 4. 본업 연속 마이너스
    months = CF.get("months") or []
    run = 0
    for m in reversed(months):
        if m[1] < 0:
            run += 1
        else:
            break
    if run >= 2:
        out.append(("본업 현금이 %d달 연속 마이너스입니다" % run,
                    "최근 %d달 동안 본업에서 들어온 돈보다 나간 돈이 많았습니다 (합계 %s원)." % (run, W(sum(m[1] for m in months[-run:]))),
                    "행사가 몰려 비용이 먼저 나간 것인지, 대금 회수가 늦어진 것인지 받을 돈 변화와 같이 보세요.", "warn"))
    # 5. 부족한 돈을 무엇으로 메웠나
    if P["op"] < 0 and P["fin"] > 0:
        out.append(("본업에서 빠진 돈을 빌린 돈으로 메웠습니다",
                    "%s 본업 현금은 %s원인데 빌리고 갚은 돈으로 %s원이 들어왔습니다." % (plab, W(P["op"]), W(P["fin"])),
                    "빌린 돈은 갚을 돈입니다. 대출 만기·상환 일정과 앞으로의 대금 회수를 같이 보세요.", "warn"))
    elif P["op"] < 0 and P["total"] < 0:
        out.append(("본업에서 빠진 만큼 통장 돈이 줄었습니다",
                    "%s 본업 현금 %s원, 통장 잔액은 %s원 줄었습니다." % (plab, W(P["op"]), W(-P["total"])),
                    "남은 잔액으로 몇 달을 버틸 수 있는지 자금 전망 표를 함께 보세요.", "warn"))
    elif P["op"] > 0 and P["fin"] < 0:
        out.append(("번 돈으로 빚을 갚았습니다",
                    "%s 본업 현금 %s원 중 %s원을 대출·대표이사 돈 갚는 데 썼습니다." % (plab, W(P["op"]), W(-P["fin"])),
                    "빚이 줄어 이자 부담이 가벼워집니다.", "ok"))
    # 6. 나간 돈에서 큰 몫
    outs = [(k, nm, -P["cash"].get(k, 0)) for k, nm, _ in OPS if P["cash"].get(k, 0) < 0]
    tot_out = sum(v for _, _, v in outs)
    if tot_out > 0:
        k, nm, v = max(outs, key=lambda x: x[2])
        out.append(("본업에서 가장 많이 나간 곳은 ‘%s’입니다" % nm,
                    "%s 본업으로 나간 돈 %s원 중 %s원(%d%%)이 %s입니다." % (plab, W(tot_out), W(v), round(v * 100.0 / tot_out), nm),
                    "법인카드 대금이 크면 카드로 먼저 쓰고 나중에 갚는 돈이 많다는 뜻이라, 카드 결제일에 통장 돈이 한꺼번에 빠집니다."
                    if k == "카드" else "이 항목이 매출과 같은 비율로 움직이는지 달마다 보세요.", "info"))
    # 7. 정기예금
    dep = P["cash"].get("정기넣음", 0) + P["cash"].get("정기찾음", 0)
    if P["cash"].get("정기넣음") and abs(dep) >= 1_000_000:
        out.append(("단기금융상품(만기 3개월 넘는 예금 등)으로 옮긴 돈이 있습니다",
                    "%s 단기금융상품에 %s원을 넣고 %s원을 찾았습니다 (차이 %s%s원)." % (plab, W(-P["cash"].get("정기넣음", 0)), W(P["cash"].get("정기찾음", 0)), "+" if dep > 0 else "", W(dep)),
                    "단기금융상품은 통장 잔액에서 빠져 있지만 회사 돈입니다. 급할 때 깰 수 있는지(만기) 확인해 두세요.", "info"))
    # 8. 월말 잔액 가장 낮았던 달
    if len(months) > 1:
        low = min(months, key=lambda m: m[4])
        out.append(("월말 통장 잔액이 가장 낮았던 달은 %d월입니다" % low[0],
                    "%d월 말 잔액 %s원. 지금(%s 말) 잔액은 %s원입니다." % (low[0], W(low[4]), "%d월" % months[-1][0], W(months[-1][4])),
                    "행사 대금이 들어오기 전 달에 잔액이 낮아지는지 해마다 같은 때를 비교해 보세요.", "info"))
    return out


# 세 칸 부호 조합 → 회사 상태 (사용자 2026-11-12: 본업·투자·재무를 비교해 지금 상태를 쉬운 말로)
STATES = {
    "+--": ("안정형", "ok", "본업으로 번 돈으로 묶어 둘 돈도 마련하고 빚도 갚고 있습니다.",
            "가장 건강한 모습입니다. 회사가 스스로 번 돈으로 움직입니다."),
    "+-+": ("확장형", "info", "본업으로 돈을 벌면서, 빌린 돈까지 보태 맡기거나 투자하고 있습니다.",
            "본업이 받쳐 주는 동안은 괜찮습니다. 빌린 돈의 쓰임과 갚을 일정을 같이 보세요."),
    "++-": ("정리형", "ok", "본업으로 번 돈에 맡겨 둔 돈까지 찾아 빚을 갚고 있습니다.",
            "빚이 줄어드는 중입니다. 맡겨 둔 돈이 얼마나 남았는지 보세요."),
    "+++": ("현금 쌓기형", "info", "본업으로 번 돈, 찾은 돈, 빌린 돈이 모두 통장에 쌓이고 있습니다.",
            "큰 지출을 앞두고 모으는 것이면 괜찮지만, 이유 없이 빌린 돈이 놀고 있다면 이자만 나갑니다."),
    "--+": ("빌린 돈 의존형", "warn", "본업에서 돈이 빠져나가고, 그 빈자리를 빌린 돈으로 메우고 있습니다.",
            "일이 늘며 대금 회수가 늦어질 때 흔한 모습입니다. 못 받은 돈이 제때 들어오는지, 빌린 돈을 언제 갚는지 꼭 확인하세요."),
    "-++": ("버티기형", "warn", "본업에서 돈이 빠져나가 맡겨 둔 돈을 찾고 돈도 빌려 메우고 있습니다.",
            "이 상태가 길어지면 쓸 수 있는 돈이 빠르게 줄어듭니다. 대금 회수와 지출 시기를 먼저 점검하세요."),
    "-+-": ("주의형", "warn", "본업에서 돈이 빠지는데 맡겨 둔 돈을 찾아 빚까지 갚고 있습니다.",
            "통장 잔액이 빠르게 줄 수 있는 모습입니다. 남은 잔액으로 몇 달을 버틸지 자금 전망과 함께 보세요."),
    "---": ("잔액 소진형", "warn", "본업·묶어 둔 돈·빌리고 갚은 돈이 모두 마이너스라 통장 잔액으로 버티고 있습니다.",
            "잔액이 줄어드는 만큼만 버틸 수 있습니다. 대금 회수 일정과 큰 지출을 먼저 확인하세요."),
}
SIGN_WORD = {"+": "들어옴", "-": "나감", "0": "거의 없음"}


def _sign(v, th):
    return "+" if v > th else ("-" if v < -th else "0")


def diagnose(CF):
    """세 칸 부호로 지금 상태 판정. 월간은 올해 누적(여러 달), 연간은 그해로 판정하고 이번 기간 조합은 참고로."""
    ann = CF.get("annual")
    P = CF["M"] if ann else CF["Y"]
    gross = sum(abs(v) for v in P["cash"].values()) or 1
    th = max(1_000_000, gross * 0.005)   # 오간 돈 전체의 0.5% 또는 100만 원보다 작으면 '거의 없음'

    def key(Q):
        sg = [_sign(Q["op"], th), _sign(Q["inv"], th), _sign(Q["fin"], th)]
        k = sg[0].replace("0", "+") + sg[1].replace("0", "-") + sg[2].replace("0", "-")
        return sg, k
    sg, k = key(P)
    name, lv, what, look = STATES[k]
    why = []
    r = P["rec"]
    if P["op"] < 0 and r["받을돈"] < 0:
        why.append("본업이 마이너스인 가장 큰 이유는 아직 못 받은 매출 대금이 %s원 늘었기 때문입니다. 장부상 이익은 %s원입니다." % (W(-r["받을돈"]), W(r["이익"])))
    elif P["op"] < 0 and r["이익"] < 0:
        why.append("본업이 마이너스인 이유는 장부상 손실(%s원)입니다." % W(r["이익"]))
    elif P["op"] > 0:
        why.append("본업에서 %s원이 들어왔습니다 (장부상 이익 %s원)." % (W(P["op"]), W(r["이익"])))
    fin_in = P["cash"].get("대출받음", 0) + max(P["cash"].get("자본", 0), 0)
    if fin_in > 0:
        why.append("빌리거나 받은 돈 %s원이 들어왔고, 갚은 돈은 %s원입니다." % (W(fin_in), W(-(P["fin"] - fin_in))))
    elif P["fin"] < 0:
        why.append("빚·대표이사 돈으로 %s원을 갚았습니다." % W(-P["fin"]))
    if sg[1] == "0":
        why.append("묶어 두거나 찾은 돈은 크지 않아(%s원) 판단에 영향이 거의 없습니다." % W(P["inv"]))
    out = {"name": name, "level": lv, "what": what, "look": look, "signs": sg, "why": why,
           "basis": CF["label"] if ann else "올해 %d월~%d월 누적" % (CF["y0"].month, CF["p1"].month), "P": P}
    if not ann:
        msg, mk = key(CF["M"])
        out["month"] = (CF["label"], msg, STATES[mk][0])
    return out


def health(CF):
    """건강 점검 3가지 (사용자 2026-11-12: 현금흐름표로 건강한지 알 수 있나) — 돈을 버나 · 번 돈이 들어오나 · 버틸 돈이 있나.
    -> (종합 한 줄, 수준, [(질문, 답, 수준)])."""
    ann = CF.get("annual")
    P = CF["M"] if ann else CF["Y"]
    r = P["rec"]
    out = []
    if r["이익"] > 0:
        out.append(("돈을 버는가 (손익)", "예 — 장부상 이익 %s원" % W(r["이익"]), "ok"))
    else:
        out.append(("돈을 버는가 (손익)", "아니오 — 장부상 손실 %s원" % W(r["이익"]), "warn"))
    C_ = CF.get("collect") or {}
    tr = _collect_trend(C_) if C_ else None
    if P["op"] >= r["이익"] * 0.8 and P["op"] > 0:
        out.append(("번 돈이 들어오는가 (현금)", "예 — 본업 현금 %s원" % W(P["op"]), "ok"))
    else:
        txt = "아직 — 본업 현금 %s원 (받을 돈 %s원 늘어남)" % (W(P["op"]), W(-r["받을돈"]) if r["받을돈"] < 0 else "0")
        lv = "warn" if (tr and tr[1] == "warn") or r["이익"] <= 0 else "info"
        if tr:
            txt += ". 회수 날수: 최근 3달 %d일 / 그 전 %d일" % (C_["recent"][0], C_["early"][0])
        out.append(("번 돈이 들어오는가 (현금)", txt, lv))
    end = CF.get("end")
    run = None
    if end is not None and CF.get("_rows"):
        lo = dt.date(CF["p1"].year, max(1, CF["p1"].month - 2), 1)
        q = period(CF["_rows"], lo, CF["p1"])
        spent = sum(-v for k, v in q["cash"].items() if v < 0 and k in [x for x, _, _ in OPS])
        n = CF["p1"].month - lo.month + 1
        if spent > 0:
            run = end / (spent / float(n))
    if run is not None:
        lv = "ok" if run >= 3 else ("info" if run >= 1.5 else "warn")
        out.append(("버틸 돈이 있는가 (잔액)", "통장 %s원 = 최근 3달 평균으로 본업에 나가는 돈의 %.1f달 치 (들어오는 돈 없이 버틸 수 있는 기간)" % (W(end), run), lv))
    elif end is not None:
        out.append(("버틸 돈이 있는가 (잔액)", "통장 %s원" % W(end), "info"))
    warn = [q for q, a, lv in out if lv == "warn"]
    if not warn and all(lv == "ok" for _, _, lv in out):
        verdict, lv = "건강합니다 — 돈을 벌고, 번 돈이 들어오고, 버틸 돈도 있습니다.", "ok"
    elif not warn:
        verdict, lv = "이익은 나지만 현금이 늦게 도는 상태입니다 — 회수가 늦어지지 않는 한 성장하며 생기는 모습입니다.", "info"
    else:
        verdict, lv = "주의가 필요합니다 — %s 쪽에서 신호가 있습니다." % " · ".join(q.split(" (")[0] for q in warn), "warn"
    return verdict, lv, out


def _health_html(CF):
    v, hl, rows_ = health(CF)
    icon = {"ok": ("✓", "var(--in)"), "warn": ("!", "var(--out)"), "info": ("i", "var(--accent)")}
    return ("<div class='q'>이 회사는 건강한가요?</div><div class='card dg' style='border-left:5px solid %s'>"
            "<div class='dw' style='color:%s;font-size:14px'>%s</div><table class='cf hc'><tbody>%s</tbody></table>"
            "<div class='note'>현금흐름표만으로는 ‘번 돈이 들어오는가’만 보입니다. 손익(돈을 버는가)과 잔액(버틸 돈)을 함께 봐야 건강을 판단할 수 있어 세 가지를 같이 봅니다.</div></div>"
            % (icon[hl][1], icon[hl][1], esc(v), "".join(
                "<tr><td><span class='ik' style='background:%s'>%s</span>%s</td><td style='text-align:left;white-space:normal'>%s</td></tr>"
                % (icon[l][1], icon[l][0], esc(q), esc(a_)) for q, a_, l in rows_)))


def _diag_html(CF):
    D = diagnose(CF)
    col = {"ok": "var(--in)", "warn": "var(--out)", "info": "var(--accent)"}[D["level"]]
    P = D["P"]
    chips = "".join("<div class='sg'><div class='l'>%s</div><div class='v %s'>%s</div><div class='w'>%s · %s원</div></div>"
                    % (t, {"+": "pin", "-": "pout", "0": "z"}[s], {"+": "+", "-": "−", "0": "0"}[s], SIGN_WORD[s], W(v))
                    for t, s, v in zip(("① 본업", "② 묶어 둔 돈", "③ 빌리고 갚은 돈"), D["signs"], (P["op"], P["inv"], P["fin"])))
    h = ["<div class='q'>지금 회사 상태 (세 칸 비교)</div><div class='card dg' style='border-left:5px solid %s'>" % col,
         "<div class='dh'><span class='dn' style='color:%s'>%s</span><span class='db'>판정 기준: %s</span></div>" % (col, esc(D["name"]), esc(D["basis"])),
         "<div class='sgs'>%s</div>" % chips,
         "<div class='dw'>%s</div>" % esc(D["what"])]
    if D["why"]:
        h.append("<ul class='dy'>%s</ul>" % "".join("<li>%s</li>" % esc(x) for x in D["why"]))
    h.append("<div class='il'><b>그래서</b> %s</div>" % esc(D["look"]))
    if D.get("month"):
        lab, sg, nm = D["month"]
        h.append("<div class='note'>참고: %s 한 달만 보면 본업 %s · 묶어 둔 돈 %s · 빌리고 갚은 돈 %s (%s). 행사 대금은 1~2달 늦게 들어와 한 달 조합은 자주 바뀌므로 판정은 누적으로 합니다.</div>"
                 % (esc(lab), SIGN_WORD[sg[0]], SIGN_WORD[sg[1]], SIGN_WORD[sg[2]], esc(nm)))
    h.append("<div class='note'>판정 방법: 세 칸이 각각 들어왔는지(+) 나갔는지(−) 조합으로 봅니다. 본업 +, 묶어 둔 돈 −, 빌리고 갚은 돈 − 가 가장 건강한 조합입니다.</div></div>")
    return "".join(h)


def improve(CF):
    """현금흐름을 좋게 하려면 (사용자 2026-11-12): 이 표의 숫자에서 나온 할 일과 그 근거·기대 효과.
    -> [(할 일, 근거, 기대 효과)]. 효과는 이 표의 숫자로 계산할 수 있는 것만 쓴다."""
    ann = CF.get("annual")
    P = CF["M"] if ann else CF["Y"]
    plab = CF["label"] if ann else "올해 %d월~%d월" % (CF["y0"].month, CF["p1"].month)
    r, c = P["rec"], P["cash"]
    days = max((CF["p1"] - (CF["p0"] if ann else CF["y0"])).days + 1, 1)
    weeks = days / 7.0
    out = []
    if r["받을돈"] < 0 and abs(r["받을돈"]) >= 10_000_000:
        out.append(("행사 대금 받는 날을 앞당기기",
                    "%s 못 받은 매출 대금이 %s원 늘었습니다. 본업 현금이 이익보다 적은 가장 큰 이유입니다." % (plab, W(-r["받을돈"])),
                    "행사가 끝나면 바로 계산서를 내고, 입금일이 지난 건은 주마다 담당자가 고객에게 확인합니다. 받는 만큼 본업 현금이 그대로 늘어납니다 (예: 늘어난 금액의 절반이면 %s원)." % W(-r["받을돈"] // 2)
                    + _faster_text(CF)))
    if P["op"] < 0 or r["선급"] < 0:
        pre = "업체에 먼저 준 계약금이 %s원 늘었습니다. " % W(-r["선급"]) if r["선급"] < 0 else ""
        out.append(("큰 행사는 고객에게서도 계약금 받기",
                    "%s%s 본업 현금은 %s원입니다. 행사 전에 업체 돈은 먼저 나가는데 고객 돈은 행사 뒤에 들어옵니다." % (pre, plab, W(P["op"])),
                    "계약할 때 고객 계약금(선금)을 받으면 업체에 먼저 주는 돈을 회사 돈 대신 고객 돈으로 낼 수 있습니다. 계약서·견적서 조건에 넣는 것이 시작입니다."))
    biz = -c.get("업체", 0)
    if P["op"] < 0 and biz > 0:
        wk = int(biz / weeks)
        out.append(("업체 대금 지급일을 고객 입금일에 맞추기",
                    "%s 행사 업체에 보낸 돈이 %s원, 한 주 평균 %s원입니다." % (plab, W(biz), W(wk)),
                    "업체와 '행사 후 ○일 지급'처럼 기한을 정해 고객 대금이 들어온 뒤에 나가게 하면, 지급을 한 주만 늦춰도 통장에 %s원쯤 더 남습니다 (거래처와의 약속 범위 안에서)." % W(wk)))
    card = -c.get("카드", 0)
    outs = sum(-v for k, v in c.items() if v < 0 and k in dict((x, 1) for x, _, _ in OPS))
    if card > 0 and outs and card * 1.0 / outs >= 0.15:
        out.append(("법인카드 결제일 정리",
                    "%s 법인카드 대금이 %s원으로 본업에서 나간 돈의 %d%%입니다." % (plab, W(card), round(card * 100.0 / outs)),
                    "카드사별 결제일이 고객 대금이 많이 들어오는 날 뒤에 오도록 맞추면 결제일에 통장 잔액이 바닥나는 것을 막을 수 있습니다."))
    paid, got = -c.get("이자낸", 0), c.get("이자받", 0)
    if P["cash"].get("대출받음", 0) > 0 or (paid > 0 and P["fin"] > 0):
        line = "%s 대출로 %s원이 들어왔고, 대출 이자로 %s원을 냈습니다." % (plab, W(c.get("대출받음", 0)), W(paid))
        if c.get("정기넣음") and got:
            line += " 같은 기간 정기예금 이자는 %s원 받았습니다." % W(got)
        out.append(("대출 갚는 계획을 대금 회수에 맞추기",
                    line,
                    "못 받은 대금이 들어오면 그 돈으로 대출 원금을 먼저 갚는 순서를 정해 두면 이자가 줄고 ‘빌린 돈 의존형’에서 벗어납니다. 빌린 돈이 있는데 남는 돈을 정기예금에 넣으면 보통 받는 이자보다 내는 이자가 큽니다."))
    if P["op"] > 0 and P["fin"] >= 0 and P["inv"] >= 0 and P["total"] > 0:
        out.append(("남는 돈 쓰임 정하기",
                    "%s 본업으로 %s원이 들어와 통장 돈이 %s원 늘었습니다." % (plab, W(P["op"]), W(P["total"])),
                    "앞으로 3달 지급 예정만큼은 통장에 두고, 그보다 남는 돈은 대출 상환이나 짧은 정기예금으로 옮기면 놀고 있는 돈이 줄어듭니다."))
    return out


def _faster_text(CF):
    """회수 날수가 길어졌으면: 예전 날수로 돌아갈 때 풀리는 돈 (최근 3달 하루 평균 입금 × 줄어드는 날수)."""
    C_ = CF.get("collect") or {}
    r, e = C_.get("recent"), C_.get("early")
    if not r or not e or r[0] - e[0] < 10:
        return ""
    lo = max(1, CF["p1"].month - 2)
    days = (CF["p1"] - dt.date(CF["p1"].year, lo, 1)).days + 1
    freed = int(r[1] / float(days) * (r[0] - e[0]))
    return " 최근 3달 회수 날수가 %d일로 그 전(%d일)보다 길어졌습니다. 그 전 수준으로 돌아가면 통장에 약 %s원이 더 있게 됩니다 (최근 하루 평균 입금 × %d일)." % (r[0], e[0], W(freed), r[0] - e[0])


def _improve_html(CF):
    items = improve(CF)
    if not items:
        return ""
    h = ["<div class='q'>현금흐름을 좋게 하려면</div><div class='note'>이 표의 숫자에서 나온 할 일입니다. 실제로 할지는 거래처·고객과의 관계를 보고 정하세요.</div><div class='imp'>"]
    for i, (t, why, eff) in enumerate(items, 1):
        h.append("<div class='card'><div class='it'><span class='ik' style='background:var(--accent)'>%d</span>%s</div>"
                 "<div class='ib'>%s</div><div class='il'><b>이렇게 하면</b> %s</div></div>" % (i, esc(t), esc(why), esc(eff)))
    h.append("</div>")
    return "".join(h)


def _insight_html(CF):
    items = insights(CF)
    if not items:
        return ""
    icon = {"ok": ("✓", "var(--in)"), "warn": ("!", "var(--out)"), "info": ("i", "var(--accent)")}
    h = ["<div class='q'>이 표로 알 수 있는 것</div><div class='ins'>"]
    for t, body, look, lv in items:
        mark, col = icon[lv]
        h.append("<div class='card'><div class='it'><span class='ik' style='background:%s'>%s</span>%s</div><div class='ib'>%s</div>"
                 "<div class='il'><b>볼 것</b> %s</div></div>" % (col, mark, esc(t), esc(body), esc(look)))
    h.append("</div>")
    return "".join(h)


def _card(lab, big, foot):
    return "<div class='card'><div class='lab'>%s</div><div class='big'>%s</div><div class='foot'>%s</div></div>" % (esc(lab), big, esc(foot))


def _deposit_text(CF):
    deps = CF.get("deposits") or []
    if not deps:
        return ""
    return "<br>" + " · ".join("%s: %s%s" % (esc(v), kind, " (%d일)" % days if days is not None else " (%s)" % esc(why))
                               for v, kind, why, days in deps)


def _check_text(CF):
    out = []
    sc = CF.get("start_check")
    if CF.get("end") is None:
        return "통장 잔액을 몰라 시작·끝 잔액은 비웠습니다 (계좌 잔액 자료 확인 필요)."
    if sc:
        name, v = sc
        base = CF["ystart"] if CF.get("annual") else CF["start"]
        if v == base:
            out.append("✓ 시작 잔액이 %s(%s원)과 같습니다." % (name, W(v)))
        else:
            out.append("[확인] 시작 잔액 %s원 ≠ %s %s원 (차이 %s원) — 통장 잔액 기준일과 장부 날짜가 다르거나 장부가 바뀜."
                       % (W(base), name, W(v), W(base - v)))
    if CF.get("year_partial"):
        out.append("장부가 %s부터라 그 전 흐름은 없습니다 (1월 1일 잔액은 거꾸로 계산한 값)." % CF["first_day"].isoformat())
    elif not CF.get("annual"):
        out.append("1월 1일 잔액은 끝 잔액에서 올해 흐름을 거꾸로 빼서 구했습니다.")
    return " ".join(out)
