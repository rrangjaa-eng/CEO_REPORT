"""내년 예산 (사용자 2026-11-10: 목업 승인 후 '이 방식으로 프로그램에 넣어').

올해 장부·인트라넷 자료로 초안을 자동으로 만들고, 사람이 정하는 값(노란 칸)만 창에서 넣는다.
- 입력/예산값.csv  연도,구분,대상,값   구분 = 성장률(%)·늘릴인원(명)·입사월(1~12)·급여인상률(%)·물가인상률(%)
  성장률·늘릴인원·입사월은 대상 = 팀 이름, 급여인상률·물가인상률은 대상 = 회사 전체.
- 목표 수익률은 팀 목표(입력/팀목표.csv, 창 '팀 목표')의 그 해 값. 없으면 1 − 예산_원가율(기본 70%) (추정 예산과 같은 기준).
- 입력/예산확정.csv  예산을 확정하면 달별 숫자를 남긴다. 월간 보고의 '예산 대비'가 읽는다.

계산 (목업 mockups/예산 과 같음):
- 매출 = 팀별 올해 매출 × (1 + 성장률). 올해 매출 = 장부(손익.csv 팀 줄) 실적 달 + 남은 달은 그 달 행사 프로젝트 사전견적(예상).
- 달별 = 지난 해들 달별 매출 비중 평균 (증빙월별 → 없으면 손익 회사 줄). 내년 행사로 이미 받은 일(사전견적)보다 작지 않게.
- 매출원가 = 매출 × (1 − 목표 수익률). 급여 = 지금 1달 급여 × (1 + 인상률) + 늘릴 인원 × 1인 평균 × (1 + 인상률) (입사 월부터).
- 그 밖의 판관비 = 계정별 올해 실적(1년으로 늘림) × 기준(인원·물가·그대로). 감가상각비 = 올해 예상(직접 입력 또는 작년 장부).
- 영업외 수익 = 이자수익만 (지원금 등은 확정 전이라 넣지 않음). 영업외 비용 = 올해 실적을 1년으로 늘림.
- 자금: 자금계획서·계산서에 이미 있는 예산 연도 입금·지급은 그 날짜·금액 그대로 (받은 자료 먼저, 사용자 2026-11-17). 아직 장부에 안 잡힌
  매출·매입만 매출 입금은 계산서 작성일 뒤 60일 (가용자금과 같게, 결정 e), 매입 지급은 행사 달 40%·다음 달 60%. 부가세·법인세 일정 = 세금예상(있으면) + 예산 숫자.
"""
import collections
import csv
import datetime as dt
import os
import re
from collections import OrderedDict

from .calc import year_revenue_left
from .corptax import corp_tax, depreciation
from . import corptax as _corptax
from .util import open_text as _open_text  # UTF-8·CP949 모두 읽음 (C5)

VALUES_FILE = "예산값.csv"
VALUES_COLUMNS = ["연도", "구분", "대상", "값"]
CONFIRM_FILE = "예산확정.csv"
CONFIRM_COLUMNS = ["연도", "월", "대상", "매출", "매출총이익", "급여", "판관비", "감가상각비", "영업외수익", "영업외비용", "확정일"]
COMPANY = "회사 전체"
TEAM_KINDS = ("성장률", "늘릴인원", "입사월")
CO_KINDS = ("급여인상률", "물가인상률")
KINDS = TEAM_KINDS + CO_KINDS
HEAD_ACCOUNTS = ("복리후생비", "여비교통비", "통신비", "교육훈련비", "도서인쇄비")   # 인원에 비례
FLAT_ACCOUNTS = ("임차료", "보험료", "리스료")                                     # 계약 금액 그대로
SALARY_WORDS = ("급여", "상여", "퇴직", "임금", "제수당")
AP_SPLIT = (0.4, 0.6)       # 매입 지급: 행사 달, 다음 달
DEFAULT_COST = 0.70
COLLECT_DAYS = 60       # 매출 입금: 계산서 작성일 뒤 약 60일 (사용자 2026-11-12)
# 예산 숫자(매입·급여·판관비·세금·영업외)에 없는 정해진 지급: 자금일정·자금계획서에서 그대로 가져온다 (G2)
FIXED_WORDS = ("원금", "상환", "보증금", "설비", "이전", "대여", "투자", "자산")
FIXED_SKIP = ("이자", "급여", "보험", "세금", "카드", "임차료", "구독")
VAT = 0.10
LOCAL = 0.10


# ───────────── 사람이 정하는 값 ─────────────
def _num(text):
    t = str(text if text is not None else "").replace(",", "").replace("%", "").replace("원", "").replace("명", "").replace("월", "").strip()
    if t.startswith("+"):
        t = t[1:]
    try:
        return float(t)
    except ValueError:
        return None


def read_values(input_dir):
    """-> {(연도, 구분, 대상): 숫자}. 없거나 읽지 못하면 {}."""
    path = os.path.join(input_dir, VALUES_FILE)
    out = {}
    if not os.path.exists(path):
        return out
    try:
        with _open_text(path) as f:
            for r in csv.DictReader(f):
                y, k, who = (r.get("연도") or "").strip(), (r.get("구분") or "").strip(), (r.get("대상") or "").strip()
                v = _num(r.get("값"))
                if y.isdigit() and k in KINDS and v is not None:
                    out[(y, k, who or COMPANY)] = v
    except (OSError, UnicodeDecodeError, csv.Error):
        return {}
    return out


def _check(kind, v):
    if kind == "성장률" and not -100 < v <= 500:
        raise ValueError("성장률은 −100 ~ 500 사이 % (예: 10)")
    if kind in CO_KINDS and not -50 <= v <= 100:
        raise ValueError("%s은 −50 ~ 100 사이 %% (예: 5)" % ("급여 인상률" if kind == "급여인상률" else "물가 인상률"))
    if kind == "늘릴인원" and (v != int(v) or not -50 <= v <= 50):
        raise ValueError("늘릴 인원은 정수 (줄이면 음수, 예: 1)")
    if kind == "입사월" and (v != int(v) or not 1 <= v <= 12):
        raise ValueError("입사 월은 1~12")


def save_values(input_dir, year, items):
    """items = [(구분, 대상, 값 글자)]. 값이 비면 그 줄을 지운다. -> 그 해 저장된 줄 수."""
    y = str(year or "").strip()
    if not (y.isdigit() and len(y) == 4):
        raise ValueError("연도는 4자리 (예: 2027)")
    if not os.path.isdir(input_dir):
        raise ValueError("입력 폴더가 없습니다: %s" % input_dir)
    from .util import guard_save
    guard_save(os.path.join(input_dir, VALUES_FILE))   # 못 읽은 파일을 새 줄만으로 덮지 않음 (C5)
    cur = read_values(input_dir)
    for kind, who, text in items:
        if kind not in KINDS:
            raise ValueError("모르는 구분: %s" % kind)
        who = (who or "").strip() or COMPANY
        if kind in TEAM_KINDS and who == COMPANY:
            raise ValueError("팀을 고르세요 (예: 기획1팀)")
        if str(text or "").strip() == "":
            cur.pop((y, kind, who), None)
            continue
        v = _num(text)
        if v is None:
            raise ValueError("숫자로 넣으세요: %s" % text)
        _check(kind, v)
        cur[(y, kind, who)] = v
    path = os.path.join(input_dir, VALUES_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(VALUES_COLUMNS)
        for (yy, k, who), v in sorted(cur.items(), key=lambda kv: (kv[0][0], KINDS.index(kv[0][1]), kv[0][2])):
            w.writerow([yy, k, who, "%g" % v])
    os.replace(tmp, path)
    return sum(1 for (yy, _, _) in cur if yy == y)


def values_text(input_dir, year):
    """창에 보일 저장된 값 한 줄."""
    V = read_values(input_dir)
    y = str(year)
    teams = sorted(set(w for (yy, k, w) in V if yy == y and k in TEAM_KINDS))
    parts = []
    for t in teams:
        g, n, m = V.get((y, "성장률", t)), V.get((y, "늘릴인원", t)), V.get((y, "입사월", t))
        s = "%s %s" % (t, "성장 %+g%%" % g if g is not None else "성장 입력 전")
        if n:
            s += " · %+d명%s" % (n, " %d월" % m if m else "")
        parts.append(s)
    for k, lab in (("급여인상률", "급여 인상"), ("물가인상률", "물가")):
        v = V.get((y, k, COMPANY))
        parts.append("%s %s" % (lab, "%+g%%" % v if v is not None else "입력 전"))
    return "%s년: %s" % (y, " / ".join(parts))


# ───────────── 계산 ─────────────
def _r4(v):
    return int(round(v / 10000.0)) * 10000


def _event(text):
    from .calc import _event_date
    return _event_date(text)


def _ym(y, m):
    return "%04d-%02d" % (y, m)


def _spread(total, floor, seas):
    """계절 비중대로 나누되 floor(이미 받은 일)보다 작지 않게, 나머지 달을 비율대로 줄여 합계를 맞춘다."""
    fixed = [False] * 12
    a = [0.0] * 12
    for _ in range(13):
        rest = total - sum(floor[i] for i in range(12) if fixed[i])
        w = sum(seas[i] for i in range(12) if not fixed[i])
        a = [floor[i] if fixed[i] else (rest * seas[i] / w if w > 0 else 0) for i in range(12)]
        bad = [i for i in range(12) if not fixed[i] and a[i] < floor[i]]
        if not bad:
            break
        for i in bad:
            fixed[i] = True
    a = [_r4(v) for v in a]
    if any(a):
        k = max(range(12), key=lambda i: (not fixed[i], a[i]))
        a[k] += total - sum(a)
    return a


def _seasonality(d, base, base_months=None):
    """지난 해들 달별 매출 비중 평균. 올해(base)는 base_months(실적 + 남은 달 예상)를 쓴다. -> (비중 12개, 설명)."""
    years = OrderedDict()
    ev = getattr(d, "evid_month", None) or {}
    src = "증빙 작성일자 기준 달별 매출"
    for ym, (rev, _) in ev.items():
        if re.match(r"^\d{4}-\d{2}$", ym or "") and rev is not None and int(ym[:4]) < base:
            years.setdefault(int(ym[:4]), [0] * 12)[int(ym[5:7]) - 1] += rev
    if not years:
        src = "장부 손익 회사 줄"
        for p in d.pl:
            if p["unit"] == "회사" and p["revenue"] is not None and re.match(r"^\d{4}-\d{2}$", p["ym"] or "") and int(p["ym"][:4]) < base:
                years.setdefault(int(p["ym"][:4]), [0] * 12)[int(p["ym"][5:7]) - 1] += p["revenue"]
    if base_months and sum(base_months) > 0:
        years[base] = list(base_months)
        src = (src + " + " if len(years) > 1 else "") + "%d년 팀 매출(실적+예상)" % base
    shares, used = [], []
    for y, ms in sorted(years.items()):
        tot = sum(ms)
        if tot > 0 and sum(1 for v in ms if v) >= 6:
            shares.append([v / float(tot) for v in ms])
            used.append(y)
    if not shares:
        return [1 / 12.0] * 12, "자료 없음 — 12달 똑같이"
    avg = [sum(s[i] for s in shares) / len(shares) for i in range(12)]
    avg = [max(v, 0.01) for v in avg]
    t = sum(avg)
    return [v / t for v in avg], "%s, %s년 평균" % (src, "·".join(str(y) for y in used))


def _collect_days(d, base):
    """올해 계산서(발행) 발행일→입금일 평균 일수. 모르면 None."""
    days = [(i["paid_date"] - i["date"]).days for i in getattr(d, "invoices", [])
            if i.get("kind") == "발행" and i.get("date") and i.get("paid_date") and i["paid_date"] >= i["date"]
            and i["date"].year >= base - 1]
    return (sum(days) / float(len(days)), len(days)) if days else (None, 0)


def _salary_month(dept):
    """급여 기준 달 = 급여가 다 들어간 마지막 달 -> (연월, 바꿨으면 알림 글).

    급여 전표는 월말에 들어가므로 11~12월 중순에 예산을 만들면 가장 최근 달은 급여가 0이거나 일부 부서만 있다
    (2026-11-14 오후 점검 G1: 그 달을 기준으로 잡아 내년 급여 0원·인원 0명이 되던 것). 급여가 있는 부서 수가 그 해 가장
    많았던 달보다 적은 달은 '덜 들어간 달'로 보고 건너뛴다."""
    months = sorted(set(x["ym"] for x in dept))
    if not months:
        return None, ""
    paid = {m: sum(1 for x in dept if x["ym"] == m and (x["salary"] or 0) > 0) for m in months}
    full = max(paid.values())
    if not full:
        return months[-1], ""
    ok = [m for m in months if paid[m] >= full]
    pick = ok[-1]
    if pick != months[-1]:
        skip = [m for m in months if m > pick]
        return pick, "급여 기준 달을 %s로 잡음 — %s 급여 전표가 아직 다 들어가지 않음" % (pick, "·".join(skip))
    return pick, ""


def _wehago_pay(input_dir, base, done_ym, asof):
    """위하고 급여 화면(급여명세.csv 지급합계)·사원등록(사원.csv 부서·입사·퇴사)으로 급여 기준 달·부서별 인원·급여.

    전수조사 제안 3-①⑤ (2026-11-14 사용자 '제안 전부'): 장부 급여 전표는 월말에 들어가 늦지만 급여 화면은 급여를 돌리면 바로
    다 있다. 장부 직원급여와 원 단위로 같음을 11/14 확인. 이 파일이 없거나 그 해 지급이 없으면 None (장부 부서비용으로).
    -> {"ym", "heads"{부서: 명}, "sal"(그 달 합계), "months"{연월: 합계}, "notes"}. 사원 이름은 돌려주지 않는다."""
    if not input_dir:
        return None
    from . import payroll
    try:
        emps, slips, detail = payroll.load(input_dir)
    except Exception:   # 급여 자료가 깨져도 예산은 장부 기준으로 만든다
        return None
    if not detail:
        return None
    pay = {}
    for (ym, name), sl in slips.items():
        v = sl["pay"].get("지급합계")
        if v and ym[:4] == str(base) and ym <= done_ym:
            pay.setdefault(ym, {})[name] = v
    if not pay:
        return None
    ym = max(pay)
    day = lambda t: payroll._d(t) if t else None
    gone = lambda e: e is not None and day(e.get("퇴사일")) is not None and day(e["퇴사일"]) <= asof
    heads, sal, notes, left = OrderedDict(), 0, [], 0
    for name, v in pay[ym].items():
        e = emps.get(name)
        if gone(e):
            left += 1
            continue
        dept = ((e or {}).get("부서") or "").strip() or "부서 없음"
        heads[dept] = heads.get(dept, 0) + 1
        sal += v
    if left:
        notes.append("%s 급여를 받은 %d명은 %s까지 퇴사해 인원·급여에서 뺌" % (ym, left, asof.isoformat()))
    new = 0
    for name, e in emps.items():   # 기준 달 뒤 입사해 아직 급여가 없는 사람: 인원에 넣고 급여는 1인 평균으로
        j = day(e.get("입사일"))
        if name in pay[ym] or gone(e) or j is None or j > asof or "%04d-%02d" % (j.year, j.month) <= ym:
            continue
        dept = (e.get("부서") or "").strip() or "부서 없음"
        heads[dept] = heads.get(dept, 0) + 1
        new += 1
    if new and sum(heads.values()) > new:
        sal += int(round(sal / float(sum(heads.values()) - new))) * new
        notes.append("%s 뒤 입사해 아직 급여가 없는 %d명은 1인 평균 급여로 넣음" % (ym, new))
    # 2차 전수조사 V13 (2026-11-18): 급여 예산이 '마지막 달 × 12'라 그 달에 상여가 있으면 1년 내내 크고, 없으면 명절·연말 상여가
    # 빠졌음 → 지금 있는 사람마다 [보통 달 급여(최근 3달의 가운데 값) × 12 + 그 해 보통 달보다 더 받은 금액(상여)의 1년 환산].
    # 연중에 급여가 오른 사람은 오른 급여가 보통 달이 되고, 달 중간 입사처럼 덜 받은 달은 세지 않는다.
    annual, annual_exec, n_exec, cur_n = 0, 0, 0, 0
    for name in pay[ym]:
        e = emps.get(name)
        if gone(e):
            continue
        vals = [pay[m][name] for m in sorted(pay) if name in pay[m]]
        reg = sorted(vals[-3:])[len(vals[-3:]) // 2]
        a = int(round(reg * 12 + sum(max(0, v - reg) for v in vals) * 12.0 / len(vals)))
        annual += a
        cur_n += 1
        if str((e or {}).get("임원") or "").strip() not in ("", "0", "N", "n", "아니오", "False") or str((e or {}).get("직급") or "").strip() == "대표":
            annual_exec += a
            n_exec += 1
    staff_n = cur_n - n_exec
    per_staff = int(round((annual - annual_exec) / 12.0 / staff_n)) if staff_n > 0 else None   # 임원 뺀 1인 평균 월 급여
    if new and per_staff:
        annual += per_staff * 12 * new
    return {"ym": ym, "heads": heads, "sal": sal, "months": dict((m, sum(v.values())) for m, v in pay.items()), "notes": notes,
            "annual": annual, "per_staff": per_staff}


LOAN_FILE = "차입금.csv"   # 위하고 차입금현황(SAFM0109)을 변환이 만든 것 (H 스레드, 2026-11-14 열 합의)
LOAN_WORDS = ("차입", "원금", "대출")   # 차입금.csv 가 있으면 자금일정의 이런 줄은 겹치므로 쓰지 않는다


def _loan_plan(input_dir, debts, asof, until):
    """차입금현황의 만기일·상환 방식 + 장부 잔액(장부채무.csv 차입금, 거래처코드별)으로 원금 갚을 날짜·금액 (전수조사 G2).

    위하고 등록 잔액은 쓰지 않는다 (하나캐피탈처럼 상환이 갱신되지 않은 곳이 있음, 11/14 F 확인). 만기가 기준일보다 지난 대출은
    갚을 돈으로 잡지 않고 '연장 확인 필요'로만 (신한 기보 2억: 사용자 11/14 연장함, 위하고 만기일은 옛 날짜).
    일시상환 = 만기 달에 장부 잔액 전부. 분할상환 = 기준일 다음 달부터 만기 달까지 월상환액(없으면 장부 잔액 ÷ 남은 달), 잔액까지만.
    -> (None, []) 파일 없음 / ([{date, amount, name, how}], 알림 글 목록). until 날짜까지만."""
    if not input_dir:
        return None, []
    path = os.path.join(input_dir, LOAN_FILE)
    if not os.path.exists(path):
        return None, []
    from .wehago import norm_code, norm_vendor
    from .util import date as parse_date
    with _open_text(path) as f:
        rows = list(csv.DictReader(f))
    led_code, led_name = {}, {}
    for x in debts or []:
        if x["kind"] != "차입금" or x["balance"] is None:
            continue
        if x["vcode"]:
            led_code[norm_code(x["vcode"])] = led_code.get(norm_code(x["vcode"]), 0) + x["balance"]
        led_name[norm_vendor(x["vendor"])] = led_name.get(norm_vendor(x["vendor"]), 0) + x["balance"]
    pays, notes = [], []

    def _key(r):
        c = norm_code(r.get("거래처코드"))
        return ("code", c) if c and c != "0" and c in led_code else ("name", norm_vendor((r.get("차입처") or "").strip()))
    # 1차 C4 (2026-11-15): 같은 은행(거래처코드) 대출이 여럿이면 장부 잔액(은행 전체)을 대출마다 통째로 붙여 두 번 갚는 것으로 셌다
    # → 같은 은행 대출끼리 원금 비율로 나눈다 (원금을 모르면 똑같이)
    share = collections.defaultdict(list)
    for r in rows:
        share[_key(r)].append(int(_num(r.get("원금")) or 0))
    for r in rows:
        name = (r.get("차입처") or "").strip() or "차입처 없음"
        code = norm_code(r.get("거래처코드"))
        bal = led_code.get(code) if code and code != "0" else None
        if bal is None:
            bal = led_name.get(norm_vendor(name))
        group = share[_key(r)]
        if bal is not None and len(group) > 1:
            mine, tot = int(_num(r.get("원금")) or 0), sum(group)
            bal = int(round(bal * mine / float(tot))) if tot > 0 and mine > 0 else int(round(bal / float(len(group))))
            notes.append("대출 %s: 같은 은행 대출 %d건 — 장부 잔액을 원금 비율로 나눠 이 대출 몫 %s원으로 봄"
                         % (name, len(group), format(bal, ",")))
        due = parse_date(r.get("만기일"))
        how = (r.get("상환방식") or "").strip()
        src = (r.get("만기근거") or "").strip() or "차입금현황"   # H 변환: 사용자가 직접 넣은 새 만기일이면 '직접 입력' (11/14 신한 연장)
        if bal is None:
            notes.append("대출 %s: 장부 차입금 잔액을 찾지 못해 원금 상환을 넣지 못함 (거래처코드 확인)" % name)
            continue
        if bal <= 0:
            continue
        if due is None:
            notes.append("대출 %s: 만기일이 없어 원금 상환을 넣지 못함" % name)
            continue
        roll = (r.get("매년연장") or "").strip() in ("예", "Y", "y", "yes")   # 매년 연장하는 대출 (사용자 11/14: 신한 기보 2억)
        if roll:
            if due < asof:
                notes.append("대출 %s: 매년 연장 대출인데 만기일 %s이 지남 → 연장 뒤 새 만기일 입력 필요 (장부 잔액 %s원, 갚을 돈으로 안 잡음)"
                             % (name, due.isoformat(), format(bal, ",")))
            else:
                notes.append("대출 %s: 매년 연장 예정(만기 %s) — 원금 상환으로 잡지 않음 (장부 잔액 %s원)" % (name, due.isoformat(), format(bal, ",")))
            continue
        if due < asof:
            notes.append("대출 %s: 만기일 %s이 지남 → 연장했으면 새 만기일을 직접 입력 (지금은 갚을 돈으로 안 잡음, 장부 잔액 %s원)"
                         % (name, due.isoformat(), format(bal, ",")))
            continue
        if how == "분할":
            mon = int(_num(r.get("월상환액")) or 0) or None
            n_left = (due.year - asof.year) * 12 + due.month - asof.month
            if not mon:
                mon = int(round(bal / float(max(n_left, 1))))
            left = bal
            y_, m_ = asof.year, asof.month
            for _ in range(max(n_left, 1)):
                m_ += 1
                if m_ > 12:
                    y_, m_ = y_ + 1, 1
                day = dt.date(y_, m_, min(due.day, 28))
                amt = min(mon, left)
                if amt <= 0 or day > until:
                    break
                pays.append({"date": day, "amount": amt, "name": "대출 원금 · %s (분할)" % name, "how": "%s 만기 %s · 장부 잔액" % (src, due.isoformat())})
                left -= amt
        else:   # 일시 (상환방식이 비어 있어도 일시로 본다)
            if due <= until:
                pays.append({"date": due, "amount": bal, "name": "대출 원금 · %s (만기 일시)" % name, "how": "%s 만기 %s · 장부 잔액" % (src, due.isoformat())})
            if not how:
                notes.append("대출 %s: 상환 방식이 비어 만기 일시상환으로 봄" % name)
    return pays, notes


def _input_vat_rate(input_dir, base, done_ym, cogs_done, sga_done, sga_share):
    """올해 끝난 달의 매입 부가세 비율 -> {"rate"(없으면 None), "vat", "buy", "sga_share", "why"}.
    계정잔액.csv 의 부가세대급금(13500) 차변 합 ÷ (프로젝트 원가 + 인원 비용이 아닌 판관비)."""
    import csv
    import os
    out = {"rate": None, "vat": 0, "buy": 0, "sga_share": sga_share, "why": "계정잔액.csv 없음"}
    if not input_dir:
        out["why"] = "입력 폴더 모름"
        return out
    path = os.path.join(input_dir, "계정잔액.csv")
    if not os.path.exists(path):
        return out
    vat = 0
    try:
        from .util import open_text
        with open_text(path) as f:
            for r in csv.DictReader(f):
                ym = (r.get("연월") or "").strip()
                if ym[:4] == str(base) and ym <= done_ym and (r.get("계정코드") or "").strip() == "13500":
                    vat += int(float(r.get("차변") or 0))
    except (OSError, UnicodeDecodeError, ValueError, csv.Error):
        out["why"] = "계정잔액.csv 읽지 못함"
        return out
    buy = int(cogs_done + sga_done)
    if vat <= 0 or buy <= 0:
        out["why"] = "부가세대급금 또는 매입 금액 없음"
        return out
    rate = vat / float(buy)
    if not 0.01 <= rate <= VAT:   # 10%를 넘거나 너무 낮으면 자료가 안 맞는 것 → 쓰지 않음
        out["why"] = "계산한 비율 %.1f%%가 범위(1~10%%) 밖" % (rate * 100)
        return out
    out.update(rate=rate, vat=vat, buy=buy, why="")
    return out


def _tax_book(taxrows, base):
    """N2 (2026-11-17 밤): 세금예상.csv 의 올해 법인세 본 줄('YYYY년 (1월~M월 장부 기준)')에서 월간 법인세 예상과 같은 재료를 꺼낸다.
    -> {'m': 장부 달 수, 'adj': 세무조정, 'bad_debt': 대손충당금, 'prepaid': 선납 법인세, 'local_prepaid': 원천징수된 지방소득세} 또는 None."""
    head = "%d년 (1월~" % base
    main = next((t for t in taxrows if t.get("kind") == "법인세" and str(t.get("period") or "").startswith(head)), None)
    if not main:
        return None
    m = re.search(r"\(1월~(\d+)월", str(main.get("period") or ""))
    local = next((t for t in taxrows if t.get("kind") == "법인지방소득세" and str(t.get("period") or "").startswith(head)), None)
    local_prepaid = 0
    if main.get("calc") is not None and local and local.get("amount") is not None:
        local_prepaid = max(int(main["calc"] * LOCAL) - local["amount"], 0)
    if local and local.get("prepaid") is not None:   # 숫자 칸이 있으면 그 값 (2차 전수조사 P3)
        local_prepaid = int(local["prepaid"])
    # 2차 전수조사 제안 3: 올해 연말 예상 과세표준은 변환이 한 번 계산한 값 (지금까지 + 남은 달 예상, 주간·월간 자금 일정과 같은 값)
    rest = next((t for t in taxrows if t.get("kind") == "법인세" and str(t.get("period") or "").startswith("%d년 " % base)
                 and t.get("base_ye") is not None), None)
    # 남은 달 예상 줄이 없으면(12월이거나 남은 달 이익이 0 이하) 지금까지 과세표준이 곧 연말 예상.
    # 옛 파일(감가상각 숫자 칸이 없는 파일)은 연말 값이 없으므로 예전처럼 예산이 계산한다
    new_file = main.get("dep") is not None
    base_ye = None if not new_file else (int(rest["base_ye"]) if rest else (int(main["base"]) if main.get("base") is not None else None))
    return {"m": int(m.group(1)) if m else 12, "adj": main.get("adj") or 0, "bad_debt": main.get("bad_debt") or 0,
            "prepaid": main.get("prepaid"), "local_prepaid": local_prepaid, "base_ye": base_ye}


def _tax_calc(pre, year, input_dir, adj=0, bad_debt=0):
    """세전 이익 -> 월간 법인세 예상과 같은 계산 (corptax.national: 작년 신고서 감면·'받음' 공제·최저한세·농특세).
    과세표준 = 세전 이익 − 대손충당금 예상 + 세무조정. -> dict 또는 None.
    total = 낼 법인세(감면 뒤 + 농특세) + 지방소득세(산출세액 × 10%%), final = 감면 뒤 법인세(농특세 전, 중간예납 기준)."""
    if pre is None:
        return None
    tb = max(int(pre) - int(bad_debt or 0) + int(adj or 0), 0)
    nat, corp, C = _corptax.national(tb, str(year), input_dir)
    local = int(corp * LOCAL)
    return {"base": tb, "corp": corp, "nat": nat, "final": C["final"] if C else corp, "local": local, "total": nat + local,
            "credits": bool(C), "adj": int(adj or 0), "bad_debt": int(bad_debt or 0)}


def compute(d, values, year, asof, settings=None, input_dir=None):
    """-> 예산 dict B. values = read_values(). year = 예산 연도(정수).
    input_dir 가 있으면 급여·인원은 위하고 급여 화면·사원등록 기준 (_wehago_pay), 없으면 장부 부서비용."""
    year = int(year)
    base = year - 1
    y = str(year)
    S = settings or {}
    notes = []
    # 팀 목표 수익률
    tg = {t: v for (yy, t), v in (getattr(d, "team_targets", None) or {}).items() if yy == y}
    cost_rate = DEFAULT_COST
    try:
        cost_rate = float(str(S.get("예산_원가율", DEFAULT_COST)).strip() or DEFAULT_COST)
    except ValueError:
        pass
    # 올해 팀 실적 (손익.csv 팀 줄, WEHAGO 우선)
    srcs = sorted(set(p["source"] for p in d.pl), key=lambda x: (x != "WEHAGO", x))
    src = srcs[0] if srcs else None
    rows = [p for p in d.pl if p["source"] == src and p["unit"] == "팀" and p["ym"][:4] == str(base)
            and p["target"] and p["target"] != "팀 미지정"]
    last_m = max([int(p["ym"][5:7]) for p in rows] + [0])
    done_ym = "%d-12" % base   # 1년 환산(급여·판관비·영업외)에 쓰는 마지막 '끝난 달'
    if asof.year == base:   # 끝난 달만 실적 (기준일이 그 달 말일이면 그 달까지), 남은 달은 예상
        done = asof.month if (asof + dt.timedelta(days=1)).month != asof.month else asof.month - 1
        last_m = min(last_m, done)
        done_ym = "%d-%02d" % (base, done)
        if done < 12:   # 연중에 만든 예산 (사용자 2026-11-14: 그 일자 기준으로 맞아야 함)
            notes.append("%s 기준으로 만든 예산 — %d년 실적은 끝난 달(1~%d월)까지, 남은 달은 이미 받은 일(사전견적)만 넣음. "
                         "급여·판관비·영업외는 끝난 달 평균으로 1년 환산" % (asof.isoformat(), base, done))
    all_rows = rows
    rows = [p for p in rows if int(p["ym"][5:7]) <= last_m]
    left_unknown, prior_unknown, prior_add = [], [], [0, 0]
    teams = sorted(set(p["target"] for p in all_rows))
    # 내년에 행사가 있는 프로젝트의 팀도 넣는다
    got = []
    for p in d.projects.values():
        e = _event(p.get("event_date"))
        if e and e.year == year and p.get("estimate") and p.get("team") and p["team"] != "팀 미지정":
            got.append({"id": p["id"], "name": p["name"], "team": p["team"], "month": e.month, "estimate": p["estimate"]})
            if p["team"] not in teams:
                teams.append(p["team"])
    got.sort(key=lambda g: (g["team"], g["month"], g["id"]))
    T = OrderedDict()
    for t in teams:
        rv = [0] * 12
        gp = [0] * 12
        fc = [False] * 12
        lf = [0] * 12   # 그중 아직 장부에 안 잡힌 매출·그 이익 (자금표: 장부에 잡힌 매출의 입금은 자금계획서·계산서 일정이 잡는다)
        lg = [0] * 12
        # 장부에 잡힌 매출은 모두 (진행 중인 달에 이미 잡힌 것 포함 — 2026-11-14 오후 점검 G5: 예전엔 진행 중 달 매출을
        # 실적에서도 예상에서도 빼서 줄었음)
        for p in all_rows:
            if p["target"] == t:
                i = int(p["ym"][5:7]) - 1
                rv[i] += p["revenue"] or 0
                gp[i] += (p["revenue"] or 0) - (p["direct"] or 0)
                if i + 1 > last_m:
                    fc[i] = True
        # + 아직 매출로 안 잡힌 금액 (사전견적 − 매출반영누계, 대표 월간·팀장용과 같은 계산 calc.revenue_left).
        # 행사가 끝난 달이 이미 '실적 달'이면 다음 달(실적 달 바로 뒤)에 넣는다 (행사가 지났는데 아직 안 잡힌 매출도 빼지 않음)
        rr = ((getattr(d, "team_targets", None) or {}).get((str(base), t)) or {}).get("rate")
        for x in year_revenue_left(d.projects.values(), base, t):
            if not x["left"]:
                if x["left"] is None:
                    (prior_unknown if x["prior"] else left_unknown).append(x["P"].get("id"))
                continue
            # 결정 ③ (2026-11-16): 그 전 해 행사의 아직 안 잡힌 매출은 행사 달이 이미 지났으므로 실적 달 바로 뒤 달에
            i = (min(last_m + 1, 12) if x["prior"] else max(x["event"].month, min(last_m + 1, 12))) - 1
            rv[i] += x["left"]
            gp[i] += x["left"] * ((rr / 100.0) if rr is not None else (1 - cost_rate))
            lf[i] += x["left"]
            lg[i] += x["left"] * ((rr / 100.0) if rr is not None else (1 - cost_rate))
            fc[i] = True
            if x["prior"]:
                prior_add[0] += 1
                prior_add[1] += x["left"]
        T[t] = {"rev26": rv, "gp26": [int(v) for v in gp], "fc": fc, "left26": lf, "leftgp26": [int(v) for v in lg]}
    if left_unknown:
        notes.append("%d년 행사 %d건은 장부 매출(매출반영누계)을 몰라 남은 매출을 넣지 못함: %s" % (base, len(left_unknown), ", ".join(sorted(left_unknown))))
    if prior_add[0]:
        notes.append("%d년까지 행사 %d건의 아직 장부에 안 잡힌 매출 %s원도 %d년 매출 예상에 넣음 (실적 달 바로 뒤 달)"
                     % (base - 1, prior_add[0], format(prior_add[1], ","), base))
    if prior_unknown:
        notes.append("%d년까지 행사 %d건은 장부 매출(매출반영누계)을 몰라 남은 매출을 넣지 못함: %s"
                     % (base - 1, len(prior_unknown), ", ".join(sorted(prior_unknown))))
    # 사람이 정하는 값
    def val(kind, who=COMPANY):
        return values.get((y, kind, who))
    seas, seas_src = _seasonality(d, base, [sum(T[t]["rev26"][i] for t in teams) for i in range(12)])
    got_m = {t: [0] * 12 for t in teams}
    for g in got:
        got_m[g["team"]][g["month"] - 1] += g["estimate"]
    for t in teams:
        R = T[t]
        g = val("성장률", t)
        R["growth"], R["growth_set"] = (g if g is not None else 0.0), g is not None
        rt = (tg.get(t) or {}).get("rate")
        R["base_rev"] = sum(R["rev26"])
        R["base_gp"] = sum(R["gp26"])
        # 2차 전수조사 B6 (2026-11-18): 내년 목표 수익률을 안 넣었을 때 기본 30%(1 − 예산_원가율)를 써서 영업이익이 70% 늘어난
        # 것처럼 나왔음 (실제 26.9%·24.1%, 올해 목표 28.5%·28%). 받은 값 먼저: 내년 목표 → 올해 목표 → 올해 실제 → 기본값
        rt0 = ((getattr(d, "team_targets", None) or {}).get((str(base), t)) or {}).get("rate")
        if rt is not None:
            R["rate"], R["rate_src"] = rt / 100.0, "%d년 팀 목표" % year
        elif rt0 is not None:
            R["rate"], R["rate_src"] = rt0 / 100.0, "%d년 팀 목표 (내년 목표 입력 전)" % base
        elif R["base_rev"] > 0 and R["base_gp"] > 0:
            R["rate"], R["rate_src"] = R["base_gp"] / float(R["base_rev"]), "%d년 실제 수익률 (목표 입력 전)" % base
        else:
            R["rate"], R["rate_src"] = 1 - cost_rate, "기본 원가율 (목표·실적 없음)"
        R["rate_set"] = rt is not None
        if rt is None:
            notes.append("%s: %d년 목표 수익률을 넣지 않아 %s %.1f%%로 계산" % (t, year, R["rate_src"].split(" (")[0], R["rate"] * 100))
        R["budget"] = _r4(R["base_rev"] * (1 + R["growth"] / 100.0))
        R["got"] = got_m[t]
        R["got_sum"] = sum(got_m[t])
        if R["got_sum"] > R["budget"]:
            notes.append("%s: 이미 받은 일 %s가 매출 예산보다 커서 매출 예산을 받은 일 금액으로 올림" % (t, format(R["got_sum"], ",")))
            R["budget"] = R["got_sum"]
        R["rev"] = _spread(R["budget"], got_m[t], seas)
        R["gp"] = [_r4(v * R["rate"]) for v in R["rev"]]
        R["cogs"] = [R["rev"][i] - R["gp"][i] for i in range(12)]
    rev = [sum(T[t]["rev"][i] for t in teams) for i in range(12)]
    gp = [sum(T[t]["gp"][i] for t in teams) for i in range(12)]
    cogs = [rev[i] - gp[i] for i in range(12)]
    base_rev = sum(T[t]["base_rev"] for t in teams)
    base_gp = sum(T[t]["base_gp"] for t in teams)

    # 급여·인원 (부서비용.csv)
    dept = [x for x in (getattr(d, "dept", None) or []) if x["ym"][:4] == str(base) and x["ym"] <= done_ym]
    last_ym, sal_note = _salary_month(dept)
    heads0 = OrderedDict()
    sal_last = None
    sal_base = None
    WP = _wehago_pay(input_dir, base, done_ym, asof)
    sal_src = "부서비용.csv (장부 급여 전표)"
    if WP:
        sal_src = "위하고 급여 화면·사원등록"
        last_ym = WP["ym"]
        heads0.update(WP["heads"])
        sal_last = WP["sal"]
        sal_base = int(sum(WP["months"].values()) * 12.0 / len(WP["months"]))
        notes.extend(WP["notes"])
        # 장부 급여와 대조: 같은 달 장부 급여 합이 급여 화면과 다르면 전표가 빠졌거나 덜 들어간 것
        diff = []
        for m, v in sorted(WP["months"].items()):
            led = [x["salary"] or 0 for x in dept if x["ym"] == m]
            if led and abs(sum(led) - v) >= 1000:
                diff.append("%s 장부 %s / 급여 화면 %s" % (m, format(sum(led), ","), format(v, ",")))
            elif not led:
                diff.append("%s 장부 급여 전표 없음 (급여 화면 %s)" % (m, format(v, ",")))
        if diff:
            notes.append("장부 급여가 위하고 급여 화면과 다른 달: " + " · ".join(diff[-3:]) + (" 외 %d달" % (len(diff) - 3) if len(diff) > 3 else ""))
    elif sal_note:
        notes.append(sal_note)
    if last_ym and not WP:
        for x in dept:
            if x["ym"] == last_ym:
                heads0[x["dept"]] = int(x["heads"] or 0)
        sal_last = sum(x["salary"] or 0 for x in dept if x["ym"] == last_ym)
        used = [x for x in dept if x["ym"] <= last_ym]   # 급여 전표가 덜 들어간 뒤 달은 1년 환산에서도 뺀다
        n_m = len(set(x["ym"] for x in used))
        sal_base = int(sum(x["salary"] or 0 for x in used) * 12.0 / n_m)
    raise_ = val("급여인상률")
    infl = val("물가인상률")
    rz, fl = (raise_ or 0) / 100.0, (infl or 0) / 100.0
    h0 = sum(heads0.values())
    per = (sal_last / float(h0)) if sal_last is not None and h0 else None
    sal_month = sal_last     # 지금 인원의 한 달 급여 (예산 계산용)
    sal_how = "기준 달 급여 그대로"
    if WP and WP.get("annual"):   # V13: 사람마다 올해 실제 받은 급여의 1년 환산 (상여 포함)
        sal_month = WP["annual"] / 12.0
        sal_how = "지금 인원의 보통 달 급여 + %d년에 받은 상여의 한 달 치" % base
        if WP.get("per_staff"):
            per = float(WP["per_staff"])   # 새 인원 급여는 임원을 뺀 1인 평균 (예전엔 대표 포함 평균이라 크게 잡혔음)
    hires = OrderedDict()
    for t in teams:
        n = val("늘릴인원", t)
        m = val("입사월", t)
        if n:
            hires[t] = (int(n), int(m) if m else 1)
            heads0.setdefault(t, 0)
    heads = [h0 + sum(n for (n, m) in hires.values() if i + 1 >= m) for i in range(12)]
    if sal_last is None:
        sal = [None] * 12
        notes.append("부서비용(급여) 자료가 없어 급여 예산을 만들지 못함")
    else:
        sal = [_r4(sal_month * (1 + rz) + sum(n * per * (1 + rz) for (n, m) in hires.values() if i + 1 >= m and per)) for i in range(12)]
    havg = sum(heads) / 12.0

    # 그 밖의 판관비 (계정별비용.csv, 판매비와관리비 중 급여·감가상각비 뺀 것)
    # 진행 중인 달은 비용이 덜 들어와 1년 환산을 낮추므로 끝난 달까지만 (연중에 만든 예산)
    acc = [a for a in (getattr(d, "accounts", None) or []) if a["ym"][:4] == str(base) and a["ym"] <= done_ym and a["amount"] is not None]
    acc_months = sorted(set(a["ym"] for a in acc))
    n_acc = len(acc_months) or 1
    sal_codes = set(str(S.get("변환_급여계정", "80200")).replace(" ", "").split(",")) | {"80200"}
    sga = OrderedDict()
    nin_base = nout_base = 0
    interest_in = 0
    nonop = {}   # (수익/비용, 계정) -> {달: 금액}
    for a in acc:
        g, nm = a.get("group") or "", a.get("name") or ""
        if "판매비" in g or "관리비" in g:
            if a["code"] in sal_codes or "감가상각비" in nm:
                continue
            sga.setdefault(nm, 0)
            sga[nm] += a["amount"]
        elif "영업외수익" in g:
            nin_base += a["amount"]
            nonop.setdefault(("in", nm), {}).setdefault(a["ym"], 0)
            nonop[("in", nm)][a["ym"]] += a["amount"]
            if "이자수익" in nm:
                interest_in += a["amount"]
        elif "영업외비용" in g:
            nout_base += a["amount"]
            nonop.setdefault(("out", nm), {}).setdefault(a["ym"], 0)
            nonop[("out", nm)][a["ym"]] += a["amount"]
    k = 12.0 / n_acc
    # 2차 전수조사 V4 (2026-11-18): 영업외를 끝난 달 합 × 12 ÷ 달수로 늘려 정부지원금 같은 한 번뿐인 돈도 같이 늘어났음
    # (영업외수익 28,808,416 → 34,570,099). 끝난 달의 절반 넘게 생긴 계정(이자처럼 매달 생기는 것)만 1년으로 늘리고,
    # 나머지(지원금·처분손익 등)는 실제 금액 그대로 둔다.
    def _yearly(io):
        rec = once = 0
        for (io_, nm), ms in nonop.items():
            if io_ != io:
                continue
            tot = sum(ms.values())
            if sum(1 for v in ms.values() if v) * 2 > n_acc:
                rec += tot
            else:
                once += tot
        return rec, once
    nin_rec, nin_once = _yearly("in")
    nout_rec, nout_once = _yearly("out")
    if n_acc < 12 and (nin_once or nout_once):
        notes.append("영업외: 매달 생기는 계정만 1년으로 늘림 — 한 번씩 생긴 수익 %s원·비용 %s원은 실제 금액 그대로"
                     % (format(nin_once, ","), format(nout_once, ",")))
    SGA = []
    for nm, v in sorted(sga.items(), key=lambda kv: -kv[1]):
        yv = int(v * k)
        if any(w in nm for w in SALARY_WORDS) or any(w in nm for w in HEAD_ACCOUNTS):
            nv, how = yv * (havg / h0 if h0 else 1) * (1 + (rz if any(w in nm for w in SALARY_WORDS) else fl)), "인원 %d→평균 %.2f명 × %s" % (
                h0, havg, "급여 인상률" if any(w in nm for w in SALARY_WORDS) else "물가")
            basis = "인원"
        elif any(w in nm for w in FLAT_ACCOUNTS):
            nv, how, basis = yv, "계약 금액 그대로", "그대로"
        else:
            nv, how, basis = yv * (1 + fl), "물가", "물가"
        SGA.append({"name": nm, "base": yv, "budget": _r4(nv), "how": how, "basis": basis})
    sga_y = sum(x["budget"] for x in SGA)
    sga_base = sum(x["base"] for x in SGA)
    sga_m = [_r4(sga_y / 12.0)] * 12
    sga_m[11] += sga_y - sum(sga_m)
    # 감가상각비
    D = depreciation(getattr(d, "accounts", None), getattr(d, "dep_manual", None) or {}, "%s-12" % base)
    dep_y = D["annual"]
    if D["source"] == "고정자산대장":   # V21: 내년 값은 대장의 자산별 남은 금액으로 (상각이 끝나는 자산은 빠짐)
        nxt, ended = _corptax.next_year_ledger(input_dir, base)
        if nxt is not None and nxt != dep_y:
            notes.append("%d년 감가상각비 %s원 = 고정자산대장 자산별 남은 금액 기준 (%d년 %s원, 상각이 끝나는 자산 %d개 · 내년에 새로 살 자산은 모름)"
                         % (year, format(nxt, ","), base, format(dep_y, ","), ended))
            dep_y = nxt
    dep_m = [None] * 12 if dep_y is None else [int(dep_y // 12)] * 12
    if dep_y is not None:
        dep_m[11] += dep_y - sum(dep_m)
    else:
        notes.append("감가상각비를 모름 — 창 '감가상각비'에 %d년 금액을 넣으면 들어감" % base)
    nin_y = int(interest_in * k)
    nout_y = int(nout_rec * k)   # 내년: 매달 생기는 비용(이자 등)만
    nin_base_y, nout_base_y = int(nin_rec * k) + nin_once, int(nout_rec * k) + nout_once
    nin_m = [_r4(nin_y / 12.0)] * 12
    nout_m = [_r4(nout_y / 12.0)] * 12
    sal_y = None if sal[0] is None else sum(sal)
    known = sal_y is not None and dep_y is not None
    op_m = [None if not known else gp[i] - sal[i] - sga_m[i] - dep_m[i] for i in range(12)]
    Y = {"rev": sum(rev), "cogs": sum(cogs), "gp": sum(gp), "sal": sal_y, "dep": dep_y, "sga": sga_y,
         "nin": sum(nin_m), "nout": sum(nout_m)}
    Y["op"] = None if not known else Y["gp"] - Y["sal"] - Y["dep"] - Y["sga"]
    Y["pre"] = None if Y["op"] is None else Y["op"] + Y["nin"] - Y["nout"]
    # N2 (2026-11-17 밤): 예산 법인세도 월간·연간·배당·기획본부와 같은 계산 (예전: 세전 이익에 세율표만 — 세무조정·감면·최저한세 없음)
    TB = _tax_book(getattr(d, "tax", None) or [], base)
    adj_y = 0 if not TB else int(round(TB["adj"] * 12.0 / max(TB["m"], 1)))   # 세무조정(승용차 한도 초과 등)은 달마다 쌓여 1년으로 늘림
    YT = _tax_calc(Y["pre"], year, input_dir, adj_y, 0)   # 내년 대손충당금은 모름 → 빼지 않음 (세금이 적게 보이지 않게)
    Y["tax"] = None if YT is None else YT["total"]
    # 올해 (실적 + 예상)
    base_dep = D["annual"]
    L = {"rev": base_rev, "gp": base_gp, "cogs": base_rev - base_gp, "sal": sal_base, "dep": base_dep, "sga": sga_base,
         "nin": nin_base_y, "nout": nout_base_y}
    L["op"] = None if None in (sal_base, base_dep) else L["gp"] - L["sal"] - L["dep"] - L["sga"]
    L["pre"] = None if L["op"] is None else L["op"] + L["nin"] - L["nout"]
    LT = _tax_calc(L["pre"], base, input_dir, adj_y, TB["bad_debt"] if TB else 0)
    if TB and TB.get("base_ye") is not None:
        # 제안 3 (2026-11-18): 올해분 법인세는 예산이 따로 계산하지 않고 변환의 '연말 예상 과세표준' 하나로 (주간·월간 자금 일정의
        # 법인세 줄 합계와 같은 금액). 예전: 예산이 1년 환산 이익으로 따로 계산해 같은 날 보고와 달랐음 (16,452,031 vs 13,676,883)
        LT = _tax_calc(TB["base_ye"], base, input_dir, 0, 0)
        LT["shared"] = True
    L["tax"] = None if LT is None else LT["total"]

    # ───── 자금 ─────
    bals = [b for b in getattr(d, "balances", []) if b.get("balance") is not None and b.get("date")]
    bal_date = max((b["date"] for b in bals), default=None)
    bal0 = sum(b["balance"] for b in bals if b["date"] == bal_date) if bal_date else None
    restricted = sum(b.get("restricted") or 0 for b in bals if b["date"] == bal_date) if bal_date else 0
    days, n_days = _collect_days(d, base)
    # 수금 기간: 가용자금과 같은 '작성일 뒤 60일' 하나로 (계산-13·사용자 결정 e, 2026-11-15). 장부 평균은 입금이 끝난 계산서만
    # 세어 빨리 들어온 쪽으로 치우치므로(못 받은 건은 빠짐) 계산에 쓰지 않고 참고로만 보인다 (1차 C15·C10)
    days_used = COLLECT_DAYS
    lag = max(0.0, days_used / 30.0)
    l0 = int(lag)
    frac = lag - l0
    split = {l0: 1 - frac, l0 + 1: frac}
    # 올해 11~12월 등 남은 매출은 내년 초 입금 (올해 예상 매출)
    base_rev_m = [sum(T[t]["rev26"][i] for t in teams) for i in range(12)]
    base_gp_m = [sum(T[t]["gp26"][i] for t in teams) for i in range(12)]
    ext_rev = base_rev_m + rev
    cin = []
    for i in range(12):
        j = 12 + i
        cin.append(_r4((1 + VAT) * sum(w * ext_rev[j - l] for l, w in split.items() if j - l >= 0)))
    base_cogs_dec = base_rev_m[11] - base_gp_m[11]
    # 2차 전수조사 V14 (2026-11-18): 매출원가 전부에 부가세 10%, 판관비는 절반에만 부가세라고 보던 것을 올해 실제 비율로.
    # 실제 비율 = 올해 끝난 달 부가세대급금(13500 차변) ÷ (프로젝트 원가 + 인원 비용이 아닌 판관비). 프리랜서(3.3%)·면세 매입이
    # 섞여 10%보다 낮다. 자료가 없으면 예전 가정(원가 10%, 판관비 절반) 그대로.
    vat_in = _input_vat_rate(input_dir, base, done_ym,
                             sum((p["direct"] or 0) for p in rows),
                             sum(x["base"] for x in SGA if x["basis"] != "인원") / k,
                             (sum(x["budget"] for x in SGA if x["basis"] != "인원") / float(sga_y)) if sga_y else 0.0)
    rv = vat_in["rate"] if vat_in["rate"] is not None else VAT
    if vat_in["rate"] is not None:
        notes.append("매입 부가세: %d년 실제 비율 %.1f%% (부가세대급금 %s원 ÷ 매입 %s원)로 지급·부가세 예산을 계산 — 프리랜서·면세 매입이 있어 10%%보다 낮음"
                     % (base, vat_in["rate"] * 100, format(vat_in["vat"], ","), format(vat_in["buy"], ",")))
    else:
        notes.append("매입 부가세: 올해 실제 비율을 몰라(%s) 매출원가 전부에 10%%, 판관비 절반에 10%%가 붙는다고 봄 — 프리랜서·면세 매입만큼 지급이 크게 잡힘" % vat_in["why"])
    cpay = [_r4((1 + rv) * (AP_SPLIT[0] * cogs[i] + AP_SPLIT[1] * (cogs[i - 1] if i else base_cogs_dec))) for i in range(12)]
    # 세금 일정
    FIX = []
    tax_m = [0] * 12
    taxrows = getattr(d, "tax", None) or []

    def add_tax(m, day, name, amt, how, srcname):
        if amt is None:
            return
        tax_m[m - 1] += amt
        FIX.append({"month": m, "day": day, "name": name, "amount": amt, "how": how, "src": srcname})
    # 올해 4분기 부가세·법인세·지방세: 세금예상.csv (있으면)
    base_vat = [t for t in taxrows if t["kind"] == "부가세" and t.get("due") and t["due"].year == year and t["due"].month == 1]
    if base_vat:
        # E1 (2026-11-17): 진행 중 분기면 '남은 기간 예상' 줄도 함께 (쌓인 금액 + 남은 기간). 금액 모르는 줄이 있으면 모름
        amts = [t["amount"] for t in base_vat]
        add_tax(1, "1/25", "부가세 (%d년 10~12월)" % base, None if any(a is None for a in amts) else sum(amts),
                "세금예상 (%s)" % " + ".join(str(t.get("basis", "")) for t in base_vat), "분개장")
    else:
        add_tax(1, "1/25", "부가세 (%d년 10~12월)" % base, _r4(VAT * sum(base_gp_m[9:12])), "올해 10~12월 매출총이익 × 10% (예상)", "올해 예상")
    # 올해분 법인세·지방세: 손익표와 같은 '올해 연말 예상 세전 이익' 하나로 계산 (2026-11-14 오후 점검 G3: 예전엔 손익표는
    # 연말 예상 이익, 지급 일정은 세금예상.csv 의 지금까지 이익이라 같은 예산 안에서 1,001만 달랐음). 기납부(중간예납)는
    # 세금예상.csv 의 값이 있으면 뺀다. 결산·세무조정 뒤 바뀔 수 있으므로 '예상'으로 적는다.
    corp_rows = [t for t in taxrows if t["kind"] == "법인세" and t.get("due") and t["due"].year == year]
    prepaid = TB["prepaid"] if TB and TB["prepaid"] is not None else (corp_rows[0].get("prepaid") if corp_rows else None)
    if LT is not None:
        corp_pay = max(LT["nat"] - (prepaid or 0), 0)
        from . import choices, corptax as _ct   # A4 (2026-11-17): 회사가 분납을 골랐으면 3/31 과 5/31 로 나눔
        inst = _ct.installable(corp_pay) if input_dir and choices.installment(input_dir) else 0
        add_tax(3, "3/31", "법인세 (%d년분)" % base, corp_pay - inst,
                "%d년 연말 예상 과세표준 %s → 낼 법인세 %s%s%s%s" % (base, format(LT["base"], ","), format(LT["nat"], ","),
                                                     (" (감면·공제 뒤, " if LT["credits"] else " (") + ("자금 일정의 법인세 예상과 같은 값)" if LT.get("shared") else "월간과 같은 계산)"),
                                                     " − 기납부 %s" % format(prepaid, ",") if prepaid else " (기납부 모름 — 빼지 않음)",
                                                     " − 분납 %s (5/31)" % format(inst, ",") if inst else ""),
                "예산 계산 (예상)")
        if inst:
            add_tax(5, "5/31", "법인세 분납분 (%d년분)" % base, inst, "분납함(회사 선택): 법인세법 64조 중소기업 2개월", "예산 계산 (예상)")
        lp = TB["local_prepaid"] if TB else 0
        add_tax(4, "4/30", "지방소득세 (%d년분)" % base, max(LT["local"] - lp, 0),
                "법인세 산출세액 %s × 10%%%s" % (format(LT["corp"], ","), " − 원천징수된 지방소득세 %s" % format(lp, ",") if lp else ""),
                "예산 계산 (예상)")
    sga_vat_q = _r4(rv * sum(x["budget"] for x in SGA if x["basis"] != "인원") / 4.0)
    for q in range(3):
        s_ = slice(q * 3, q * 3 + 3)
        amt = max(_r4(VAT * sum(rev[s_]) - rv * sum(cogs[s_]) - sga_vat_q), 0)
        add_tax(q * 3 + 4, "%d/25" % (q * 3 + 4), "부가세 (%d년 %d~%d월)" % (year, q * 3 + 1, q * 3 + 3), amt,
                ("매출 예산 × 10%% − 매입 예산 × %.1f%%(올해 실제 매입 부가세 비율) − 판관비 매입세액" % (rv * 100)) if vat_in["rate"] is not None
                else "(매출 − 매입) 예산 × 10% − 판관비 매입세액", "예산 계산")
    # 중간예납 = (작년 감면 뒤 법인세 − 원천징수 등) × 6/12, 50만 원 미만이면 안 냄 (법인세법 63조·63조의2, 월간 일정과 같은 계산 corptax.carry_rows)
    if LT is not None:
        w = 0   # 올해 이자 원천징수 법인세는 예산에서 따로 모름 → 빼지 않음 (중간예납이 조금 크게 잡힘 — 돈이 적게 보이는 쪽)
        mid_amt = int(max(LT["final"] - w, 0) * 6 / 12)
        if mid_amt >= _corptax.INTERIM_MIN:
            add_tax(8, "8/31", "법인세 중간예납 (%d년분)" % year, _r4(mid_amt),
                    "(%d년 감면 뒤 법인세 %s%s) × 6/12 (50만 원 미만이면 안 냄)" % (base, format(LT["final"], ","),
                                                                    " − 원천징수 등 %s" % format(w, ",") if w else " · 이자 원천징수분은 안 뺌"), "예산 계산")
    FIX.sort(key=lambda f: (f["month"], int(f["day"].split("/")[1])))
    min_cash = None
    try:
        min_cash = int(float(str(S.get("위험_최소보유현금", "100000000")).replace(",", "")))
    except ValueError:
        min_cash = 100000000
    nio = [nin_m[i] - nout_m[i] for i in range(12)]
    sga_pay = [_r4(v * (1 + (vat_in["rate"] * vat_in["sga_share"] if vat_in["rate"] is not None else VAT * 0.5))) for v in sga_m]
    y0 = dt.date(year, 1, 1)
    # 주간 보고와 같은 일정 계산 (자금계획서·자금일정·세금 예상). 못 하면 무엇을 못 했는지 남긴다 (K2)
    W = None
    try:
        from .calc import compute as _calc
        W = _calc(d, "weekly", asof)
    except Exception as e:   # 보고는 만들되 연초 잔액·정해진 지급은 '모름'
        notes.append("주간 자금 일정을 계산하지 못해(%s) 연초 잔액과 대출 원금 등 정해진 지급을 넣지 못함" % type(e).__name__)
    # 정해진 지급 (2026-11-14 오후 점검 G2): 예산 연도 안 대출 원금·보증금·설비 같은 지급. 매입·급여·판관비·세금·이자·카드는
    # 예산 숫자에 이미 있어 넣지 않는다 (같은 돈 두 번 빼지 않게)
    fixed = [0] * 12
    loans, loan_notes = _loan_plan(input_dir, getattr(d, "debts", None), asof, dt.date(year, 12, 31))
    notes.extend(loan_notes)
    def is_loan(e):   # 대출 원금 줄 (이자 줄은 아님)
        c = str(e.get("cat") or "")
        return loans is not None and ("원금" in c or (any(w in c for w in LOAN_WORDS) and "이자" not in c))
    for x in loans or []:
        if x["date"].year == year:
            fixed[x["date"].month - 1] += x["amount"]
            FIX.append({"month": x["date"].month, "day": "%d/%d" % (x["date"].month, x["date"].day), "name": x["name"], "amount": x["amount"],
                        "how": x["how"], "src": "차입금현황 + 장부", "kind": "fixed"})
    if W is not None:
        for e in W.get("events") or []:
            cat = str(e.get("cat") or "")
            if is_loan(e) or (e.get("io") != "out" or e.get("amount") is None or not e.get("date") or e["date"].year != year
                    or not any(w in cat for w in FIXED_WORDS) or any(w in cat for w in FIXED_SKIP)):
                continue
            fixed[e["date"].month - 1] += e["amount"]
            FIX.append({"month": e["date"].month, "day": "%d/%d" % (e["date"].month, e["date"].day),
                        "name": "%s%s" % (cat.replace("자금계획서 ", ""), " · %s" % e["desc"] if e.get("desc") else ""),
                        "amount": e["amount"], "how": "%s%s" % ("확정" if e.get("firm") else "예상", " · %s" % e["basis"] if e.get("basis") else ""),
                        "src": e.get("source") or "자금일정", "kind": "fixed"})
    FIX.sort(key=lambda f: (f["month"], int(f["day"].split("/")[1])))
    # 받은 자료 먼저 (사용자 2026-11-17 결정 카드 '고치기'): 자금계획서(없으면 계산서 입금예정일)에 이미 있는 예산 연도 입금·지급은
    # 그 날짜·금액 그대로 넣고, 공식(입금 = 작성일 뒤 60일, 매입 지급 = 행사 달 40%·다음 달 60%)은 아직 장부에 안 잡힌 매출·매입에만 쓴다.
    # 예전엔 올해 11~12월 매출 전체를 공식으로 내년 초 입금에 넣고(이미 발행한 계산서의 실제 예정일을 안 봄), 이미 장부에 잡힌
    # 매입 중 내년에 나갈 미지급금은 어디에도 없었다. 연말 전 줄은 연초 잔액(roll)이 이미 쓴다. 예산 연도 전에 만든 예산만.
    known = {"in": [0] * 12, "out": [0] * 12, "in_n": 0, "out_n": 0, "used": False}
    if W is not None and asof < y0:
        known["used"] = True
        for e in W.get("events") or []:
            if e.get("amount") is None or not e.get("date") or e["date"].year != year:
                continue
            cat = str(e.get("cat") or "")
            if e.get("io") == "in" and e.get("source") in ("자금계획서", "계산서"):
                known["in"][e["date"].month - 1] += e["amount"]
                known["in_n"] += 1
            elif (e.get("io") == "out" and e.get("source") == "자금계획서" and not is_loan(e)
                    and not any(w in cat for w in FIXED_WORDS)):   # FIXED_WORDS 줄은 위 '정해진 지급'이 이미 넣음
                known["out"][e["date"].month - 1] += e["amount"]
                known["out_n"] += 1
        left_rev_m = [sum(T[t]["left26"][i] for t in teams) for i in range(12)]
        left_gp_m = [sum(T[t]["leftgp26"][i] for t in teams) for i in range(12)]
        ext_left = left_rev_m + rev
        cin = [_r4((1 + VAT) * sum(w * ext_left[12 + i - l] for l, w in split.items() if 12 + i - l >= 0) + known["in"][i])
               for i in range(12)]
        left_cogs_dec = left_rev_m[11] - left_gp_m[11]
        cpay = [_r4((1 + rv) * (AP_SPLIT[0] * cogs[i] + AP_SPLIT[1] * (cogs[i - 1] if i else left_cogs_dec)) + known["out"][i])
                for i in range(12)]
        if known["in_n"] or known["out_n"]:
            notes.append("자금계획서·계산서에 이미 있는 %d년 입금 %d건 %s원, 지급 %d건 %s원은 그 날짜·금액 그대로 넣음. "
                         "아직 장부에 안 잡힌 매출·매입만 공식(입금 60일, 지급 행사 달 40%%·다음 달 60%%)으로 계산"
                         % (year, known["in_n"], format(sum(known["in"]), ","), known["out_n"], format(sum(known["out"]), ",")))
    cout = [None if sal[i] is None else cpay[i] + sal[i] + sga_pay[i] + tax_m[i] + fixed[i] for i in range(12)]
    bal = []
    # 연초 잔액 = 오늘 쓸 수 있는 돈(주간 보고와 같은 값: 은행 잔액 날짜 뒤 통장 입출금까지 반영, 사용 제한 뺌)
    #           + 오늘 뒤 ~ 연말 들어오고 나갈 돈 (2026-11-14 오후 점검 G4: 예전엔 은행 잔액 날짜~오늘 실제 입출금이 빠짐)
    roll, roll_n, roll_ok = 0, 0, True
    avail0 = None
    if asof < y0 - dt.timedelta(days=1):
        if W is None or W["s2"].get("start") is None:
            roll_ok = False
            if W is not None:
                notes.append("오늘 쓸 수 있는 돈을 몰라(통장 잔액·지급 자료 확인) 연초 잔액을 모름")
        else:
            avail0 = W["s2"]["start"]
            evs = [e for e in W["s2"].get("dated") or [] if asof < e["date"] < y0 and e.get("amount") is not None and not is_loan(e)]
            roll = sum(e["amount"] if e["io"] == "in" else -e["amount"] for e in evs)
            pre = [x for x in loans or [] if asof < x["date"] < y0]   # 연말 전 대출 원금 (차입금현황)
            roll -= sum(x["amount"] for x in pre)
            roll_n = len(evs) + len(pre)
            if (W["s2"].get("horizon") or y0) < y0 - dt.timedelta(days=1):
                notes.append("연말까지 일정이 %s까지만 있어 그 뒤 입출금은 연초 잔액에 넣지 못함" % W["s2"]["horizon"].isoformat())
        start = None if not roll_ok else avail0 + roll
    else:   # 예산 연도에 들어와 만들면 장부 잔액 그대로
        start = None if bal0 is None else bal0 - restricted
    b = start
    for i in range(12):
        if b is None or cout[i] is None:
            b = None
        else:
            b = b + cin[i] - cout[i] + nio[i]
        bal.append(b)
    lo = None if None in bal else min(range(12), key=lambda i: bal[i])
    if bal0 is None:
        notes.append("통장 잔액 자료가 없어 월별 자금 계획을 만들지 못함")
    return {
        "year": year, "base": base, "asof": asof, "teams": teams, "T": T, "last_m": last_m, "src": src,
        "rev": rev, "gp": gp, "cogs": cogs, "sal": sal, "sga": sga_m, "dep": dep_m, "nin": nin_m, "nout": nout_m, "op": op_m,
        "tax_shared": bool(LT and LT.get("shared")), "Y": Y, "L": L, "got": got, "seas": seas, "seas_src": seas_src, "SGA": SGA, "dep_src": D["source"],
        "sal_src": sal_src, "heads0": heads0, "hires": hires, "heads": heads, "havg": havg, "per": per, "sal_last": sal_last, "last_ym": last_ym,
        "sal_month": sal_month, "sal_how": sal_how, "vat_in": vat_in,
        "raise": raise_, "infl": infl, "cost_rate": cost_rate,
        "cash": {"bal0": bal0, "bal_date": bal_date, "restricted": restricted, "roll": roll, "roll_n": roll_n, "start": start, "cin": cin, "cpay": cpay, "sga_pay": sga_pay,
                 "tax": tax_m, "fixed": fixed, "nio": nio, "bal": bal, "lo": lo, "min_cash": min_cash, "days": days, "n_days": n_days,
                 "days_used": days_used, "split": split, "avail0": avail0, "known": known},
        "fix": FIX, "notes": notes,
        "missing": [k for k, v in (("성장률", any(not T[t]["growth_set"] for t in teams)), ("목표 수익률", any(not T[t]["rate_set"] for t in teams)),
                                   ("급여 인상률", raise_ is None), ("물가 인상률", infl is None)) if v],
    }


def blank_cash(B):
    """자금계획서·분개장이 최신이 아닐 때 경영관리용: 항목은 남기고 자금 전망 숫자(월초·월말·가장 적은 달)만 비운다
    (2026-11-14 오후 점검 K7, 11/12 절대 규칙 '자료가 없거나 오래되면 자금 숫자는 비움'). 손익 예산은 그대로."""
    B = dict(B)
    c = dict(B["cash"])
    c.update({"start": None, "bal": [None] * 12, "lo": None, "avail0": None, "roll": 0, "roll_n": 0})
    B["cash"] = c
    B["blocked"] = True
    return B


# ───────────── 확정 ─────────────
def confirm(input_dir, B, today=None):
    """달별 예산을 입력/예산확정.csv 에 남긴다 (그 해 줄은 바꿈). -> 줄 수."""
    today = today or dt.date.today()
    y = str(B["year"])
    keep = []
    path = os.path.join(input_dir, CONFIRM_FILE)
    if os.path.exists(path):
        try:
            with _open_text(path) as f:
                keep = [r for r in csv.DictReader(f) if (r.get("연도") or "").strip() != y]
        except (OSError, UnicodeDecodeError, csv.Error):
            keep = []
    rows = []
    for i in range(12):
        for t in B["teams"]:
            R = B["T"][t]
            rows.append({"연도": y, "월": i + 1, "대상": t, "매출": R["rev"][i], "매출총이익": R["gp"][i], "확정일": today.isoformat()})
        rows.append({"연도": y, "월": i + 1, "대상": COMPANY, "매출": B["rev"][i], "매출총이익": B["gp"][i],
                     "급여": B["sal"][i], "판관비": B["sga"][i], "감가상각비": B["dep"][i],
                     "영업외수익": B["nin"][i], "영업외비용": B["nout"][i], "확정일": today.isoformat()})
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CONFIRM_COLUMNS, lineterminator="\r\n", extrasaction="ignore")
        w.writeheader()
        for r in keep + rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in CONFIRM_COLUMNS})
    os.replace(tmp, path)
    return len(rows)


def read_confirmed(input_dir):
    """-> {연도(글자): {"date": 확정일, "rows": {(월, 대상): {매출, 매출총이익, 급여, 판관비, 감가상각비, 영업외수익, 영업외비용}}}}."""
    path = os.path.join(input_dir, CONFIRM_FILE)
    out = {}
    if not os.path.exists(path):
        return out
    try:
        with _open_text(path) as f:
            for r in csv.DictReader(f):
                y, m, who = (r.get("연도") or "").strip(), (r.get("월") or "").strip(), (r.get("대상") or "").strip()
                if not (y.isdigit() and m.isdigit() and who):
                    continue
                Y = out.setdefault(y, {"date": (r.get("확정일") or "").strip(), "rows": {}})
                v = {}
                for k in CONFIRM_COLUMNS[3:10]:
                    t = (r.get(k) or "").replace(",", "").strip()
                    v[k] = int(float(t)) if re.match(r"^-?\d+(\.\d+)?$", t) else None
                Y["rows"][(int(m), who)] = v
    except (OSError, UnicodeDecodeError, csv.Error):
        return {}
    return out


def compare(confirmed, ym, actual_team, actual_co=None):
    """월간 보고 '예산 대비'. actual_team = {팀: [(월, 매출, 매출총이익) ...]} (올해 1월~이번 달).
    -> None (그 해 확정 예산 없음) 또는 {"date", "month", "rows": [{team, cur, cur_b, ytd, ytd_b, gp, gp_b}], "tot": {...}}."""
    y, m = ym[:4], int(ym[5:7])
    C = (confirmed or {}).get(y)
    if not C:
        return None
    teams = sorted(set(w for (_, w) in C["rows"] if w != COMPANY))
    rows = []
    for t in teams:
        act = {mm: (rv, g) for mm, rv, g in actual_team.get(t, [])}
        def b(mm, k):
            v = C["rows"].get((mm, t), {}).get(k)
            return v or 0
        rows.append({"team": t,
                     "cur": act.get(m, (None, None))[0], "cur_b": b(m, "매출"),
                     "ytd": sum((act.get(mm, (0, 0))[0] or 0) for mm in range(1, m + 1)),
                     "ytd_b": sum(b(mm, "매출") for mm in range(1, m + 1)),
                     "gp": sum((act.get(mm, (0, 0))[1] or 0) for mm in range(1, m + 1)),
                     "gp_b": sum(b(mm, "매출총이익") for mm in range(1, m + 1))})
    tot = {k: sum((r[k] or 0) for r in rows) for k in ("cur", "cur_b", "ytd", "ytd_b", "gp", "gp_b")}
    co = None
    if actual_co:
        def cb(k):
            return sum((C["rows"].get((mm, COMPANY), {}).get(k) or 0) for mm in range(1, m + 1))
        co = {"sal_b": cb("급여"), "sga_b": cb("판관비"), "dep_b": cb("감가상각비")}
        co["op_b"] = tot["gp_b"] - co["sal_b"] - co["sga_b"] - co["dep_b"]
        co.update(actual_co)
    return {"date": C["date"], "month": m, "rows": rows, "tot": tot, "co": co}
