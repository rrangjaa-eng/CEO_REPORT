"""계정·거래처를 무엇으로 볼지 정하는 낱말·코드를 한곳에 (2차 전수조사 P4, 2026-11-18).

규칙(계산-01): 판단은 계정과목 코드·거래처 코드로 한다. 하지만 '어느 거래처가 세무서인가', '어느 계정이 급여인가'는 회사마다
코드가 달라 처음 한 번은 이름으로 알아볼 수밖에 없다. 그래서
  · 이름으로 알아보는 낱말을 이 파일 하나에 모으고 (여러 파일에 흩어져 서로 달랐음: '잡급'은 팀장 보고 급여 숨김에서 빠져 있었음)
  · 자료 변환 때 '이름으로 이렇게 봤다'를 코드와 함께 변환결과에 적어 (judged_lines) 새 계정·거래처가 생기면 사람이 보게 한다.
코드를 아는 것(위하고 SmartA 표준 계정)은 코드가 먼저다.
"""
import re

# ── 계정 ──
PAY_CODE3 = ("801", "802", "803", "804", "805")       # 판관비 임원급여·직원급여·상여금·제수당·잡급 (SmartA 표준)
PAY_WORDS = ("급여", "상여", "임금", "제수당", "급료", "잡급")
RETIRE_WORDS = ("퇴직",)
DEP_WORDS = ("감가상각",)

# ── 거래처 ──
TAX_OFFICE = ("세무서",)
LOCAL_OFFICE = ("구청", "시청", "군청")
INSURERS = ("국민연금", "건강보험", "근로복지", "공단")
CARD = re.compile(r"^[^\s_]+_\d{4}$")                  # 법인카드 거래처 '신한_5860' 꼴


def _sq(t):
    return re.sub(r"\s+", "", str(t or ""))


def is_retire_account(name):
    return any(w in _sq(name) for w in RETIRE_WORDS)


def is_pay_account(name, code=None):
    """급여성 계정 (급여·상여·수당·잡급·퇴직급여). 코드를 알면 코드가 먼저, 이름은 그다음."""
    c = _sq(code)
    if c[:3] in PAY_CODE3:
        return True
    n = _sq(name)
    return any(w in n for w in PAY_WORDS + RETIRE_WORDS)


def is_dep_account(name):
    return any(w in _sq(name) for w in DEP_WORDS)


def vendor_kind(name):
    """거래처 이름 -> '세무서' · '지자체' · '공단' · '카드' · ''."""
    n = _sq(name)
    if any(w in n for w in TAX_OFFICE):
        return "세무서"
    if any(w in n for w in LOCAL_OFFICE):
        return "지자체"
    if any(w in n for w in INSURERS):
        return "공단"
    if CARD.match(n):
        return "카드"
    return ""


def judged_lines(journal):
    """분개장에서 이름으로 알아본 거래처·계정을 코드와 함께 -> 변환결과에 적을 글 목록.
    새 세무서·공단·카드·급여 계정이 생기거나 이름이 바뀌면 이 줄이 달라져 사람이 알 수 있다."""
    vendors, accounts = {}, {}
    for ln in journal or []:
        k = vendor_kind(ln.get("vendor"))
        if k:
            vendors.setdefault(k, {})[(str(ln.get("vendor_code") or "").strip(), _sq(ln.get("vendor")))] = 1
        code, name = _sq(ln.get("account_code")), _sq(ln.get("account"))
        if code[:1] in ("5", "8"):
            a = "퇴직급여" if is_retire_account(name) else ("급여" if is_pay_account(name, code) else ("감가상각" if is_dep_account(name) else ""))
            if a:
                accounts.setdefault(a, {})[(code, name)] = 1
    out = []
    for k in ("세무서", "지자체", "공단", "카드"):
        if vendors.get(k):
            vs = sorted(vendors[k])
            out.append("이름으로 '%s'(으)로 본 거래처 %d곳: %s%s" % (
                k, len(vs), ", ".join("%s(%s)" % (n, c or "코드 없음") for c, n in vs[:12]), " 외 %d곳" % (len(vs) - 12) if len(vs) > 12 else ""))
    for a in ("급여", "퇴직급여", "감가상각"):
        if accounts.get(a):
            out.append("'%s' 계정으로 본 계정: %s" % (a, ", ".join("%s(%s)" % (n, c) for c, n in sorted(accounts[a]))))
    return out
