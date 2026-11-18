"""기획본부용 재무상태표 (사용자 2026-11-17).

사용자 말:
- "기획본부에서 볼 재무상태표를 따로 만들 수 있게 해. 영업외 수익은 기획본부가 발생시킨 이익이 아니니까 해당 값은 제외한 재무상태표."
- "특정 값을 바꾸면 자동으로 모든 항목이 계산되는 양식으로."
- "경영관리본부의 비용도 들어가야 해. 영업외 수익만 제외하는 거야." → 회사 전체 장부에서 영업외수익만 뺀다 (영업외비용·경영관리·플랜트8 비용은 그대로).
- "기획본부는 알 수 없으나 비용이 과대계상될 수 있는 항목들도 표시하고 설명을 추가해."

만드는 것: 엑셀(xlsx) 탭 다섯 장 (사용자 2026-11-18 '일반인도 알아보기 쉬운 양식'): 요약 · 바꿀 값(노란 칸만 바뀜, 나머지 잠금) · 손익 · 재무상태표 · 참고.
노란 칸(결산 비용·연말 상여금·뺄 영업외수익·세율 등)을 바꾸면 모든 탭이 수식으로 다시 계산된다.

계산
- 재산·빚: 계정잔액.csv(분개장을 처음부터 더한 것, credit.load)로 기준 달 말 계정별 잔액. 자본 합계 = 자산 − 부채(+ 장부에 아직 없는 올해 법인세 예상).
- 영업외수익(X): 설정의 영업외수익 계정 + 장부 계정 901~930. 올해(1월~기준 달)와 지난해까지(장부에 있는 지난 해들)로 나눔.
- 세금: 영업외수익을 빼면 이익이 줄어 세금(법인세+지방소득세)도 줄어든다. 줄어드는 비율 = (세금(과세표준) − 세금(과세표준 − X)) ÷ X.
  올해는 프로그램 법인세 예상(세금예상.csv 과세표준, corptax.national: 감면·최저한세 포함)과 같은 계산, 지난해는 신고서(법인세신고.csv)가 있으면
  그 해 실제 부담률(총부담세액 ÷ 산출세액)로, 없으면 장부 세전 이익으로 같은 계산.
- 기획본부 기준: 이익잉여금(지난해까지) −(X0 − 세금0), 올해 이익 −X1, 올해 법인세 예상 −세금1. 자산 쪽은 영업외수익으로 들어온 돈
  −(X1 + X0 − 세금0), 부채 쪽은 올해 법인세 예상 −세금1. 그래서 자산 = 부채 + 자본이 그대로 맞는다.
- 비용이 크게 잡혔을 수 있는 항목 (경영관리·플랜트8 비용은 회사 기본 비용이라 넣지 않음, 사용자 2026-11-17): 장부(계정잔액)와 법인세 예상(세무조정)에서 실제 금액이 있는 것만. 급여 금액은 넣지 않는다 (팀장용과 같은 규칙).
"""
import collections
import csv
import datetime as dt
import os
import re

from . import credit, corptax, xlsxw
from .util import open_text as _open_text

OUT_SUB = "기획본부"
NAME_RE = r"^\d{4}-\d{2}-\d{2}_기획본부_재무상태표(_\d+)?\.xlsx$"


def _int(t):
    t = str(t or "").replace(",", "").replace("원", "").strip()
    try:
        return int(float(t)) if t else None
    except ValueError:
        return None


def _rows(path):
    if not os.path.exists(path):
        return []
    with _open_text(path) as f:
        return list(csv.DictReader(f))


def tax_total(base, year, input_dir):
    """과세표준 → 낼 세금 전체 (법인세: 감면·최저한세·농특세 반영 + 지방소득세 = 산출세액 × 10%). 프로그램 법인세 예상과 같은 계산."""
    if base is None:
        return None
    nat, corp, _ = corptax.national(max(int(base), 0), str(year), input_dir)
    return int(nat or 0) + int((corp or 0) * corptax.LOCAL_RATE)


def _tax_row(input_dir, year):
    """세금예상.csv 의 올해 법인세 줄 -> (과세표준, 세무조정, 대상기간 글) 또는 (None, None, '')."""
    for r in _rows(os.path.join(input_dir, "세금예상.csv")):
        if (r.get("세목") or "").strip() == "법인세" and (r.get("대상기간") or "").startswith("%d년 (1월~" % year):
            return _int(r.get("과세표준")), _int(r.get("세무조정")), (r.get("대상기간") or "").strip()
    return None, None, ""


def excel_tax(base, TI, year):
    """엑셀 '세금 계산' 수식과 똑같은 계산 (파이썬). -> 법인세(감면·공제 뒤 + 농특세) + 지방소득세."""
    base = max(int(base), 0)
    cp = corptax.corp_tax(base, year)
    floor = int(base * TI["min"])
    sp = min(int(cp * TI["sp_rate"]), max(cp - floor, 0))
    used = min(TI["pool"], max(cp - sp - floor, 0))
    left = cp - sp - used
    out = min(TI["out"], max(left, 0))
    nong = int(used * TI["nong_share"] * TI["nong"]) // 10 * 10
    return left - out + nong + int(cp * TI["local"])


def _tax_rows(input_dir):
    return _rows(os.path.join(input_dir, "세금예상.csv"))


def dept_costs(input_dir, Y, M):
    """판관비 중 경영관리 부서·회사 공통 몫 (급여 포함, 사용자 2026-11-18: '경영관리 부서 비용·급여, 플랜트8 부서 비용도 다 넣어',
    '플랜트8은 부서가 아니라 회사 공통을 말하는 거야' — 장부 부서명 '플랜트8' = 회사 공통 비용, 부서명이 없는 줄도 회사 공통으로 같이).
    판관비(장부)에 이미 들어 있는 금액을 따로 보여 주기만 한다 (더하지 않음). -> [(이름, 급여, 그 밖 판관비)]"""
    acc = collections.OrderedDict()
    for word, label in (("경영관리", "경영관리 부서"), ("플랜트", "회사 공통 비용 (장부 부서명 '플랜트8')"), ("부서 없음", "회사 공통 비용 (장부에 부서명 없음)")):
        acc[word] = [label, 0, 0, False]
    for r in _rows(os.path.join(input_dir, "부서비용.csv")):
        ym = (r.get("연월") or "").strip()
        if ym[:4] != str(Y) or ym > "%04d-%02d" % (Y, M):
            continue
        d = (r.get("부서") or "").strip()
        for word, a in acc.items():
            if word in d:
                a[1] += _int(r.get("급여")) or 0
                a[2] += _int(r.get("판관비")) or 0
                a[3] = True
    return [(a[0], a[1], a[2]) for a in acc.values() if a[3]]


def closing_costs(input_dir, kinds, names, ytd, Y, M):
    """결산 때 들어갈 비용 예상 (사용자 2026-11-17: 진행 중 프로젝트 남은 원가만 빼고 전부 넣어).
    -> [{key, name, amount, in_base(법인세 예상 과세표준에 이미 빠짐), side('asset' 자산 줄임 | 'liab' 갚을 돈), why}]. 모두 실제 자료로 계산한 값."""
    from . import tax as _tax
    rows = _tax_rows(input_dir)
    ct = [r for r in rows if (r.get("세목") or "").strip() == "법인세" and (r.get("대상기간") or "").startswith("%d년 (1월~" % Y)]
    basis = (ct[0].get("근거") or "") if ct else ""
    out = []
    dep = _int(ct[0].get("감가상각")) if ct and (ct[0].get("감가상각") or "").strip() else None   # 숫자 칸 먼저 (2차 전수조사 P3)
    m = dep is not None
    if not m:   # 옛 파일만 근거 글에서
        m = re.search(r"감가상각비 예상 ([\d,]+)", basis)
        dep = _int(m.group(1)) if m else 0
    out.append({"key": "dep", "name": "감가상각비 (결산 전 몫)", "amount": dep or 0, "in_base": bool(m), "side": "asset",
                "why": "연말 결산 때 한 번에 들어가 지금 장부엔 없는 감가상각비 중 1~%d월 몫 (프로그램 법인세 예상과 같은 값%s). 통장 돈은 줄지 않고 장비 값이 줄어듭니다."
                       % (M, "" if m else ", 값 없음")})
    bad = _int(ct[0].get("대손충당금")) if ct else None
    bad_in = bool(re.search(r"−\s*대손충당금", basis)) or bool(ct and (ct[0].get("감가상각") or "").strip() and bad is not None)   # 새 파일: 숫자 칸이 있으면 과세표준에 이미 빠진 것
    out.append({"key": "bad", "name": "대손충당금 (못 받을 수 있는 돈)", "amount": bad or 0, "in_base": bad_in, "side": "asset",
                "why": "아직 못 받은 돈의 일부를 결산 때 '못 받을 수도 있다'고 미리 비용으로 잡는 값 (프로그램 계산%s). 받으면 다시 이익으로 돌아옵니다."
                       % ("" if bad is not None else ", 값 없음")})
    card, card_n = 0, 0
    for r in rows:
        if (r.get("세목") or "").strip() == "카드대금" and (r.get("상태") or "").strip() == "예상" and \
                any((r.get("근거") or "").startswith(k) for k in (_tax.CARD_THIN_MARK, _tax.CARD_REAL_MARK)):
            card += _int(r.get("금액")) or 0
            card_n += 1
    out.append({"key": "card", "name": "장부에 아직 안 넣은 카드값", "amount": int(round(card / 1.1)), "in_base": False, "side": "liab",
                "why": "이용기간이 끝났는데 카드 전표를 아직 넣지 않은 사용분 %d건 (위하고 카드 사용 또는 그 카드 최근 3달 평균). 부가세를 뺀 금액(÷1.1)입니다." % card_n})
    ins, ins_n = 0, 0
    for r in rows:
        mm = re.match(r"^(\d{4})년 (\d{1,2})월분$", (r.get("대상기간") or "").strip())
        if (r.get("세목") or "").strip() == "4대보험" and (r.get("상태") or "").strip() == "예상" and mm and \
                (int(mm.group(1)), int(mm.group(2))) <= (Y, M) and int(mm.group(1)) == Y:
            e = re.search(r"직원분\) ([\d,]+)원", r.get("근거") or "")
            if e and _int(r.get("금액")) is not None:
                ins += max(_int(r.get("금액")) - _int(e.group(1)), 0)
                ins_n += 1
    out.append({"key": "ins", "name": "4대보험 회사 부담분 (아직 장부 전)", "amount": ins, "in_base": False, "side": "liab",
                "why": "급여에서 뗀 직원분은 장부에 있지만 회사가 낼 몫은 내는 날에 비용으로 들어가 아직 없는 달 %d개월 (지난 납부의 회사분 비율로 계산)." % ins_n})
    pay = sum(v for c, v in ytd.items() if kinds.get(c) in ("cogs", "sga") and any(w in names.get(c, "") for w in ("급여", "임금", "상여", "제수당"))
              and "퇴직" not in names.get(c, ""))
    paid = sum(v for c, v in ytd.items() if kinds.get(c) in ("cogs", "sga") and "퇴직" in names.get(c, ""))
    out.append({"key": "ret", "name": "퇴직급여 (올해 쌓일 몫)", "amount": max(int(round(pay / 12.0)) - paid, 0), "in_base": False, "side": "liab", "no_deduct": True,
                "why": "1년 일하면 한 달 치 급여만큼 퇴직금이 쌓입니다. 올해 1~%d월 급여 ÷ 12 − 장부에 이미 넣은 퇴직급여 %s원 (어림). "
                       "이익에서는 빼지만 세금 계산에서는 빼지 않습니다 (세법은 쌓아 둔 퇴직급여를 비용으로 인정하지 않고, 실제로 준 퇴직금·퇴직연금에 낸 돈만 인정)."
                       % (M, "{:,}".format(paid))})
    out.append({"key": "bonus", "name": "연말 직원 상여금", "amount": 0, "in_base": False, "side": "liab",
                "why": "연말 상여금이 정해지면 금액을 넣으세요 (아직 안 준 돈이라 빚으로 잡고, 이익·세금이 그만큼 줄어듭니다)."})
    return out


def _names(L):
    nm = {}
    for m, code, name, d, c in L["rows"]:
        nm[code] = name
    return nm


MON_KINDS = ("rev", "cogs", "sga", "nin", "nout", "tax")
MON_NAMES = {"rev": "매출", "cogs": "매출원가 (프로젝트 원가)", "sga": "판매비와관리비", "nin": "영업외수익", "nout": "영업외비용", "tax": "법인세등 (장부)"}


def compute(input_dir, asof):
    """-> dict (엑셀·경영관리 한 줄에 쓰는 숫자). 장부를 처음부터 못 셀 때는 {'error': 까닭}."""
    from .convert import read_config
    L = credit.load(input_dir)
    if not L:
        return {"error": "계정잔액.csv 가 없습니다 — 위하고 분개장을 받아 '자료 변환'을 먼저 하세요."}
    if not L["start"]:
        return {"error": "분개장이 처음(설립·전기이월)부터가 아니라 재산·빚 잔액을 셀 수 없습니다 — 작년 분개장까지 받아 변환하세요."}
    ym = corptax._last_full_month(asof)
    Y, M = int(ym[:4]), int(ym[5:])
    cfg, _ = read_config(input_dir)
    nin_codes = set(re.sub(r"\s+", "", c) for c in cfg["nonop_in_codes"])
    names = _names(L)

    bal = collections.defaultdict(int)          # 계정별 기준 달 말 잔액 (자산·비용 = 차변 − 대변 쪽 +)
    ytd = collections.defaultdict(int)          # 올해 1~M월 손익 계정 (수익은 대변 − 차변, 비용은 차변 − 대변)
    prev = collections.defaultdict(lambda: collections.defaultdict(int))   # 지난해들 영업외수익 [연도][계정]
    prev_pl = collections.defaultdict(lambda: collections.defaultdict(int))  # 지난해들 손익 종류별
    kinds = {}
    monthly = collections.defaultdict(lambda: [0] * 13)   # 올해 손익 계정별 달별 (사용자 2026-11-18: 계정을 세목별·월별로 가져와 비용을 만듦)
    for m, code, name, d, c in L["rows"]:
        if m > ym:
            continue
        k = credit._kind(code, name)
        if code in nin_codes:
            k = "nin"
        kinds[code] = k
        y = int(m[:4])
        if k in ("ca", "na", "cl", "nl", "eq"):
            bal[code] += d - c
        elif k in ("rev", "nin"):
            if y == Y:
                ytd[code] += c - d
                monthly[code][int(m[5:7])] += c - d
            else:
                prev_pl[y][k] += c - d
                if k == "nin":
                    prev[y][code] += c - d
        elif k in ("cogs", "sga", "nout", "tax"):
            if y == Y:
                ytd[code] += d - c
                monthly[code][int(m[5:7])] += d - c
            else:
                prev_pl[y][k] += d - c
        else:
            bal["?" + code] += d - c   # 종류를 모르는 계정 (맞춤 확인에 보임)

    def sum_kind(kind):
        return sum(v for c, v in ytd.items() if kinds.get(c) == kind)

    P = {"rev": sum_kind("rev"), "cogs": sum_kind("cogs"), "sga": sum_kind("sga"), "nin": sum_kind("nin"),
         "nout": sum_kind("nout"), "tax_booked": sum_kind("tax")}
    P["op"] = P["rev"] - P["cogs"] - P["sga"]
    P["pre"] = P["op"] + P["nin"] - P["nout"]

    # 영업외수익 계정 (올해·지난해까지)
    codes = sorted(set([c for c, v in ytd.items() if kinds.get(c) == "nin"] + [c for y in prev for c in prev[y]]))
    nin_rows = []
    for c in codes:
        nin_rows.append({"code": c, "name": names.get(c, c), "cur": ytd.get(c, 0), "prev": sum(prev[y].get(c, 0) for y in prev)})
    X1 = sum(r["cur"] for r in nin_rows)
    X0 = sum(r["prev"] for r in nin_rows)

    # 올해 세금 (프로그램 법인세 예상과 같은 과세표준)
    base, adj, tax_period = _tax_row(input_dir, Y)
    tax_src = "프로그램 법인세 예상 (%s, 과세표준 %s원)" % (tax_period, "{:,}".format(base)) if base is not None else ""
    if base is None:   # 변환이 법인세 예상을 아직 못 만든 때: 장부 세전 이익을 과세표준으로 어림
        base = P["pre"] - P["tax_booked"]
        tax_src = "장부 세전 이익 %s원을 과세표준으로 어림 (프로그램 법인세 예상 없음)" % "{:,}".format(base)
    costs = closing_costs(input_dir, kinds, names, ytd, Y, M)
    # 결산 비용은 회사 전체(진짜 재무상태표)에도 들어간다 (사용자 2026-11-17). 법인세 예상 과세표준에 이미 빠진 것(감가상각)은 빼고 줄인다
    K_new = sum(c["amount"] for c in costs if not c["in_base"])
    adj_fill = base - (P["pre"] - sum(c["amount"] for c in costs if c["in_base"]))   # 세법 조정(세무조정 등): 프로그램 과세표준과 맞춤
    # 2차 전수조사 V1 (2026-11-18): 퇴직급여 쌓는 몫은 이익에서는 빼되 과세표준에서는 빼지 않는다
    # (법인세법 시행령 60조: 퇴직급여충당금 손금 한도 0 — 실제로 준 퇴직금·퇴직연금 부담금만 비용)
    K_ded = sum(c["amount"] for c in costs if not c["in_base"] and not c.get("no_deduct"))
    base_c = base - K_ded
    corp_c = corptax.corp_tax(max(base_c, 0), Y)
    nat_c, _, CR = corptax.national(max(base_c, 0), str(Y), input_dir)
    nat_c = nat_c or 0
    from . import taxreturn as _tr
    try:
        min_rate = _tr._min_rate(input_dir, Y)
    except Exception:
        min_rate = _tr.MIN_RATE
    T_all = nat_c + int(corp_c * corptax.LOCAL_RATE)
    tax_in = {"brackets": [(top, rate) for top, rate in corptax.brackets(Y)], "local": corptax.LOCAL_RATE, "min": min_rate,
              "credit": corp_c - nat_c, "adj": adj_fill, "base_c": base_c}
    # V16: 감면·공제를 고정 금액이 아니라 계산 방식 그대로 (특별세액감면은 산출세액의 비율, 공제는 최저한세까지만, 쓴 공제의 농특세)
    from . import taxlaw
    if CR:
        mt = [x for x in CR.get("extra") or [] if x.get("mt")]
        out = [x for x in CR.get("extra") or [] if not x.get("mt")]
        pool = (CR["avail"] if CR["take_carry"] else 0) + sum(int(x["amount"]) for x in mt)
        pool_nong = (CR["avail"] if CR["take_carry"] else 0) + sum(int(x["amount"]) for x in mt if x.get("nong"))
        tax_in.update({"sp_rate": CR["sp_rate"] if CR["take_sp"] else 0.0, "pool": pool,
                       "nong_share": (pool_nong / float(pool)) if pool else 0.0,
                       "out": sum(int(x["amount"]) for x in out),
                       "nong": taxlaw.checked(input_dir, Y, "농특세율", _tr.NONG_RATE)[0]})
    else:
        tax_in.update({"sp_rate": 0.0, "pool": 0, "nong_share": 0.0, "out": 0, "nong": 0.0})
    tax_in["same"] = excel_tax(base_c, tax_in, Y) == T_all   # '처음 값 그대로면 프로그램 예상과 같다'를 사실일 때만 적는다

    # 지난해까지 세금 (해마다)
    from . import taxreturn
    D = taxreturn.load(input_dir)
    T0, how0 = 0, []
    for y in sorted(prev):
        x = sum(prev[y].values())
        if not x:
            continue
        ret = D.get((y, "확정"))
        if ret and ret.get("과세표준") is not None:
            b = ret["과세표준"]
            corp = corptax.corp_tax(b, y)
            r = (ret["총부담세액"] / corp) if ret.get("총부담세액") is not None and corp else 1.0

            def tt(v, y=y, r=r):
                cp = corptax.corp_tax(max(v, 0), y)
                return int(cp * r) + int(cp * corptax.LOCAL_RATE)
            t = tt(b) - tt(b - x)
            how0.append("%d년 신고서 과세표준 %s원 기준 (실제 부담률 반영)" % (y, "{:,}".format(b)))
        else:
            pl = prev_pl[y]
            b = pl["rev"] + pl["nin"] - pl["cogs"] - pl["sga"] - pl["nout"]
            t = tax_total(b, y, None) - tax_total(b - x, y, None)
            how0.append("%d년 장부 세전 이익 %s원 기준 (신고서 없음)" % (y, "{:,}".format(b)))
        T0 += t
    rate0 = (T0 / X0) if X0 else 0.0

    # 재무상태표 계정
    groups = collections.OrderedDict((k, []) for k in ("ca", "na", "cl", "nl"))
    capital = []
    for code in sorted(bal):
        if code.startswith("?"):
            continue
        k = kinds.get(code)
        v = bal[code]
        if not v:
            continue
        if k in ("ca", "na"):
            groups[k].append((code, names.get(code, code), v))
        elif k in ("cl", "nl"):
            groups[k].append((code, names.get(code, code), -v))
        elif k == "eq" and int(code[:3]) < 370:   # 자본금·자본잉여금 (370~ 이익잉여금·자본조정은 아래 한 줄로)
            capital.append((code, names.get(code, code), -v))
    unknown = sum(v for c, v in bal.items() if c.startswith("?"))
    A = sum(v for k in ("ca", "na") for _, _, v in groups[k]) + unknown   # 모르는 계정은 자산 쪽에 둔다 (확인 줄에 보임)
    Lb = sum(v for k in ("cl", "nl") for _, _, v in groups[k])
    cap = sum(v for _, _, v in capital)
    cur_profit = P["pre"] - P["tax_booked"]
    retained = A - Lb - cap - cur_profit      # 지난해까지 쌓인 이익 등 (장부 결산 대체 여부와 상관없이 맞음)

    over = overstated(input_dir, L, kinds, names, ytd, Y, M, adj, T_all, nin_rows)
    mon = collections.OrderedDict((k, []) for k in MON_KINDS)
    for code in sorted(monthly):
        if any(monthly[code][1:M + 1]):
            mon[kinds[code]].append((code, names.get(code, code), monthly[code][1:M + 1]))
    return {"monthly": mon, "dept": dept_costs(input_dir, Y, M), "costs": costs, "asof": asof, "ym": ym, "Y": Y, "M": M, "P": P, "nin_rows": nin_rows, "X1": X1, "X0": X0, "T0": T0,
            "tax_in": tax_in, "rate0": rate0, "tax_all": T_all, "base": base, "tax_src": tax_src, "how0": how0,
            "prev_years": sorted(y for y in prev if sum(prev[y].values())),
            "groups": groups, "capital": capital, "unknown": unknown, "retained": retained, "cur_profit": cur_profit,
            "over": over, "first_year": min(int(m[:4]) for m, *_ in L["rows"]) if L["rows"] else Y}




def overstated(input_dir, L, kinds, names, ytd, Y, M, adj, T_all, nin_rows):
    """기획본부가 알기 어려운데 비용이 크게 잡혔을 수 있는 항목 (실제 금액이 있는 것만). -> [(이름, 금액, 어디에 들었나, 설명)]"""
    out = []
    # 경영관리·플랜트8 비용은 회사 기본 비용이라 넣지 않는다 (사용자 2026-11-17)
    def acct(pred):
        return sum(v for c, v in ytd.items() if pred(c, names.get(c, "")))
    v = acct(lambda c, n: kinds.get(c) in ("cogs", "sga") and "상각비" in n and "대손" not in n)
    if v:
        out.append(("감가상각비", v, "판관비·원가",
                    "실제로 돈이 나간 게 아니라, 예전에 산 물건값을 몇 해에 나눠 비용으로 잡은 것입니다. 통장 돈은 줄지 않습니다."))
    v = acct(lambda c, n: kinds.get(c) in ("cogs", "sga") and ("대손" in n or "충당금전입" in n))
    if v:
        out.append(("대손상각비 (못 받을 수 있는 돈)", v, "판관비",
                    "아직 못 받은 돈 중 일부를 '못 받을 수도 있다'고 미리 비용으로 잡은 것입니다. 나중에 받으면 다시 이익으로 돌아옵니다."))
    gov = sum(r["cur"] for r in nin_rows if "지원" in r["name"] or "보조" in r["name"])
    if gov:
        out.append(("정부지원금으로 메운 비용", gov, "원가·판관비 (주로 인건비)",
                    "정부지원금 수익은 영업외수익이라 이 표에서 뺐지만, 그 지원금으로 낸 비용(인건비 등)은 비용에 그대로 남아 있습니다. "
                    "그래서 기획본부 기준 이익은 지원금만큼 작게 보일 수 있습니다 (금액은 올해 받은 지원금)."))
    for c in sorted(ytd):
        if kinds.get(c) == "nout" and ytd[c]:
            n = names.get(c, c)
            why = ("회사 대출 이자입니다. 대출은 회사 전체 결정이라 기획본부가 정하지 않지만, 이자수익은 뺐고 이자비용은 그대로 남겼습니다."
                   if "이자" in n else "본업과 상관없이 생긴 손실(잡손실 등)입니다. 영업외수익은 뺐지만 영업외비용은 그대로 남겼습니다.")
            out.append(("%s [%s]" % (n, c), ytd[c], "영업외비용", why))
    if adj:
        out.append(("법인세 예상 중 세법이 비용으로 안 쳐 주는 몫 (세무조정)", adj, "법인세 예상",
                    "접대비 한도 초과·승용차 비용 한도 초과처럼 세법이 비용으로 인정하지 않는 금액입니다. 이만큼 이익에 다시 더해 세금을 매겨 세금이 커집니다 (금액은 더해진 이익)."))
    if T_all:
        out.append(("올해 법인세 예상 (어림값)", T_all, "법인세 예상",
                    "아직 신고 전이라 장부 이익으로 미리 계산한 값입니다. 감면·공제·세무조정이 결산과 신고 때 바뀌면 실제 세금은 이보다 적을 수 있습니다."))
    return out


# ───────────── 엑셀 ─────────────
# 사용자 2026-11-18: "뭘 어떻게 수정해야 하는지 모르겠고 보기 불편하니까 일반인도 알아보기 쉬운 양식으로 다시 만들어"
# → 탭 다섯 장: 요약(한눈에) · 바꿀 값(노란 칸만 바뀜, 결과 미리 보기) · 손익 · 재무상태표 · 참고. 노란 칸 말고는 잠금(암호 없음).
YEL, GREY, HEAD, BLUE, LBLUE, GREEN = "FFF2CC", "F2F2F2", "1F3864", "DDEBF7", "EEF4FB", "2E7D32"
DIF = '+#,##0;[Red]-#,##0;"-"'
STYLES = {
    "title": {"bold": True, "size": 16, "color": HEAD},
    "sub": {"size": 10, "color": "404040"},
    "sec": {"bold": True, "size": 11, "color": "FFFFFF", "fill": HEAD},
    "th": {"bold": True, "fill": BLUE, "border": True, "align": "center", "wrap": True},
    "td": {"border": True, "wrap": True},
    "tdb": {"border": True, "bold": True, "wrap": True},
    "tds": {"border": True, "wrap": True, "color": "595959"},
    "grp": {"bold": True, "fill": GREY, "border": True},
    "num": {"border": True, "num": "int"},
    "nums": {"border": True, "num": "int", "color": "595959"},
    "numb": {"border": True, "num": "int", "bold": True},
    "numt": {"border": True, "num": "int", "bold": True, "fill": GREY},
    "kpi": {"border": True, "num": "int", "bold": True, "size": 12},
    "kpil": {"border": True, "bold": True, "size": 11, "wrap": True},
    "dif": {"border": True, "num": DIF},
    "difb": {"border": True, "num": DIF, "bold": True},
    "dift": {"border": True, "num": DIF, "bold": True, "fill": GREY},
    "difk": {"border": True, "num": DIF, "bold": True, "size": 12},
    "in": {"border": True, "num": "int", "fill": YEL, "unlocked": True, "bold": True},
    "inp": {"border": True, "num": "0.0%", "fill": YEL, "unlocked": True, "bold": True},
    "inc": {"border": True, "fill": YEL, "align": "center", "unlocked": True, "bold": True},
    "orig": {"border": True, "num": "int", "color": "7F7F7F"},
    "origp": {"border": True, "num": "0.0%", "color": "7F7F7F"},
    "calc": {"border": True, "num": "int", "bold": True, "fill": GREY},
    "note": {"border": True, "wrap": True, "size": 9, "color": "404040"},
    "txt": {"wrap": True, "valign": "top"},
    "box": {"wrap": True, "valign": "top", "fill": LBLUE},
    "boxb": {"wrap": True, "valign": "top", "fill": LBLUE, "bold": True, "color": HEAD},
    "yel": {"wrap": True, "valign": "top", "fill": YEL, "bold": True},
    "ok": {"border": True, "num": "int", "bold": True, "color": GREEN},
    "okt": {"border": True, "bold": True, "color": GREEN, "wrap": True},
}
for _v in STYLES.values():   # 여러 줄 설명 옆 숫자도 가운데 높이에
    if _v.get("border"):
        _v.setdefault("valign", "center")
S_SUM, S_IN, S_PL, S_MO, S_BS, S_REF = "요약", "바꿀 값", "손익", "계정별 월별", "재무상태표", "참고"


def q(sheet, a):
    """다른 탭 칸 주소."""
    return "'%s'!%s" % (sheet, a)


def _won(v):
    return "{:,}".format(int(v))


def _eok(v):
    """2억 원·200억 원처럼 (억 단위로 딱 떨어질 때)."""
    return ("{:,}억 원".format(v // 100_000_000)) if v and v % 100_000_000 == 0 else "%s원" % _won(v)


def build(C, sources=""):
    """-> xlsxw.Book. 탭 다섯 장, 노란 칸('바꿀 값' 탭)만 바꿀 수 있고 나머지는 수식으로 다시 계산."""
    bk = xlsxw.Book()
    sm = bk.sheet(S_SUM)
    ip = bk.sheet(S_IN)
    pl_ = bk.sheet(S_PL)
    mo = bk.sheet(S_MO)
    bs_ = bk.sheet(S_BS)
    rf = bk.sheet(S_REF)
    for sh_, tab in ((sm, "1F3864"), (ip, "FFC000"), (pl_, "5B9BD5"), (mo, "70AD47"), (bs_, "5B9BD5"), (rf, "A5A5A5")):
        sh_.protect, sh_.tab = True, tab
    B, Cc, Dd, Ee, F = 2, 3, 4, 5, 6
    for sh_ in (sm, pl_, bs_):
        for col, w in ((1, 2), (2, 40), (3, 18), (4, 18), (5, 16), (6, 62)):
            sh_.widths[col] = w
    for col, w in ((1, 2), (2, 44), (3, 12), (4, 18), (5, 18), (6, 62)):
        ip.widths[col] = w
    for col, w in ((1, 2), (2, 44), (3, 18), (4, 22), (5, 2), (6, 70)):
        rf.widths[col] = w
    period = "%d년 1~%d월" % (C["Y"], C["M"])
    asof_txt = "%d년 %d월 말" % (C["Y"], C["M"])
    made = (sources + " · " if sources else "") + "법인세: " + C["tax_src"] + " · 만든 날 %s" % dt.date.today().isoformat()

    def head(sh_, r, title, cols):
        sh_.set(r, B, title, s="sec")
        for c in range(Cc, F + 1):
            sh_.set(r, c, "", s="sec")
        r += 1
        for c, t in zip(range(B, F + 1), cols):
            sh_.set(r, c, t, s="th")
        return r + 1

    def para(sh_, r, text, s="txt", h=None):
        sh_.set(r, B, text, s=s)
        for c in range(Cc, F + 1):
            sh_.set(r, c, "", s=s)
        sh_.merge(r, B, r, F)
        if h:
            sh_.heights[r] = h
        return r + 1

    # ══════════ 계정별 월별 (분개장 계정을 세목별·달별로, 사용자 2026-11-18) ══════════
    TOT = monthly_sheet(mo, C, para)

    # ══════════ 바꿀 값 (노란 칸) ══════════
    r = 1
    ip.set(r, B, "바꿀 값 — 노란 칸만 바꾸세요", s="title")
    ip.heights[r] = 26
    r += 1
    r = para(ip, r, "노란 칸의 금액·비율·'예/아니오'를 바꾸면 요약·손익·재무상태표 탭이 모두 바로 다시 계산됩니다. 노란 칸이 아닌 칸은 잠겨 있어 바뀌지 않습니다. "
                    "처음 값으로 되돌리려면 '처음 값' 칸의 숫자를 노란 칸에 그대로 적으세요.", s="box", h=34)
    r += 1
    prev_row = r   # 결과 미리 보기 (아래에서 칸을 채움)
    r += 6

    # 1. 결산 비용
    r = head(ip, r, "1. 결산 때 들어갈 비용 — 회사 전체·기획본부 모두에 들어갑니다",
             ("항목", "넣을까요", "금액 (원)", "처음 값", "설명 · 바꾸면 어떻게 되나요"))
    costs = sorted(C["costs"], key=lambda x: x["key"] != "bonus")   # 연말 상여금을 맨 위로
    k0 = r
    K_rows = {}
    for x in costs:
        bonus = x["key"] == "bonus"
        ip.set(r, B, ("★ " if bonus else "") + x["name"], s="tdb" if bonus else "td")
        e_ = ip.set(r, Cc, "예", s="inc")
        a_ = ip.set(r, Dd, x["amount"], s="in")
        ip.set(r, Ee, x["amount"], s="orig")
        ip.set(r, F, ("연말 직원 상여금이 정해지면 금액을 적으세요. 비용이 늘어 이익·세금·자본이 줄고, 줄 돈(부채)이 늘어납니다. " if bonus else "")
               + x["why"] + " '아니오'로 바꾸면 이 비용을 빼고 봅니다.", s="note")
        K_rows[x["key"]] = (q(S_IN, a_), q(S_IN, e_), x["side"])
        r += 1
    k1 = r - 1
    ip.choice("%s:%s" % (xlsxw.addr(k0, Cc), xlsxw.addr(k1, Cc)), ["예", "아니오"])
    ip.set(r, B, "넣을 결산 비용 합계", s="tdb")
    ip.set(r, Cc, "", s="td")
    K = q(S_IN, ip.set(r, Dd, f='SUMIF(%s:%s,"예",%s:%s)' % (xlsxw.addr(k0, Cc), xlsxw.addr(k1, Cc), xlsxw.addr(k0, Dd), xlsxw.addr(k1, Dd)), s="calc"))
    ip.set(r, Ee, "", s="td")
    ip.set(r, F, "'예'로 둔 비용만 더합니다 (계산 칸).", s="note")
    r += 2

    def side_sum(side):
        parts = ['IF(%s="예",%s,0)' % (e_, a_) for a_, e_, sd in K_rows.values() if sd == side]
        return "+".join(parts) if parts else "0"

    # 2. 영업외수익
    r = head(ip, r, "2. 뺄 영업외수익 — 기획본부 기준에서만 뺍니다",
             ("영업외수익 계정", "뺄까요", "금액 (원)", "처음 값", "설명 · 바꾸면 어떻게 되나요"))

    def nin_block(key, label, title):
        nonlocal r
        ip.set(r, B, title, s="grp")
        for c in range(Cc, F + 1):
            ip.set(r, c, "", s="grp")
        r += 1
        a0 = r
        rows = [x for x in C["nin_rows"] if x[key]]
        for x in rows:
            ip.set(r, B, "%s [%s]" % (x["name"], x["code"]), s="td")
            ip.set(r, Cc, "예", s="inc")
            ip.set(r, Dd, x[key], s="in")
            ip.set(r, Ee, x[key], s="orig")
            ip.set(r, F, "%s 장부 금액. '아니오'면 이 계정은 빼지 않고 기획본부 이익에 남깁니다." % label, s="note")
            r += 1
        if not rows:
            ip.set(r, B, "(장부에 없음)", s="tds")
            ip.set(r, Cc, "예", s="inc")
            ip.set(r, Dd, 0, s="in")
            ip.set(r, Ee, 0, s="orig")
            ip.set(r, F, "", s="note")
            r += 1
        a1 = r - 1
        ip.choice("%s:%s" % (xlsxw.addr(a0, Cc), xlsxw.addr(a1, Cc)), ["예", "아니오"])
        return a0, a1

    a0, a1 = nin_block("cur", "올해(%s)" % period, "올해 (%s)" % period)
    ip.set(r, B, "올해 뺄 영업외수익 합계", s="tdb")
    ip.set(r, Cc, "", s="td")
    X1 = q(S_IN, ip.set(r, Dd, f='SUMIF(%s:%s,"예",%s:%s)' % (xlsxw.addr(a0, Cc), xlsxw.addr(a1, Cc), xlsxw.addr(a0, Dd), xlsxw.addr(a1, Dd)), s="calc"))
    ip.set(r, Ee, C["X1"], s="orig")
    ip.set(r, F, "기획본부 올해 이익이 이만큼 작아지고, 그만큼 세금도 줄어듭니다.", s="note")
    r += 1
    b0, b1 = nin_block("prev", "지난해까지", "지난해까지 (%d년~%d년, 이미 이익잉여금에 쌓인 몫)" % (C["first_year"], C["Y"] - 1) if C["first_year"] < C["Y"] else "지난해까지")
    ip.set(r, B, "지난해까지 뺄 영업외수익 합계", s="tdb")
    ip.set(r, Cc, "", s="td")
    X0 = q(S_IN, ip.set(r, Dd, f='SUMIF(%s:%s,"예",%s:%s)' % (xlsxw.addr(b0, Cc), xlsxw.addr(b1, Cc), xlsxw.addr(b0, Dd), xlsxw.addr(b1, Dd)), s="calc"))
    ip.set(r, Ee, C["X0"], s="orig")
    ip.set(r, F, "기획본부 기준 이익잉여금(지난해까지 쌓인 이익)이 이만큼(세금 뺀 뒤) 작아집니다.", s="note")
    r += 2

    # 3. 세금
    TI = C["tax_in"]
    r = head(ip, r, "3. 세금 계산 값 — 세법이 바뀌거나 세무사 답을 받았을 때만 바꾸세요",
             ("항목", "", "값", "처음 값", "설명"))
    BR = []
    low_txt = 0
    for i, (top, rate) in enumerate(TI["brackets"]):
        rng_txt = ("%s 초과 ~ %s" % (_eok(low_txt), _eok(top))) if top is not None else ("%s 초과 전부" % _eok(low_txt))
        if low_txt == 0 and top is not None:
            rng_txt = "%s까지" % _eok(top)
        ip.set(r, B, "법인세율 %d구간 세율 (%s)" % (i + 1, rng_txt), s="td")
        ip.set(r, Cc, "", s="td")
        rt = q(S_IN, ip.set(r, Dd, rate, s="inp"))
        ip.set(r, Ee, rate, s="origp")
        ip.set(r, F, "세금 매기는 이익(과세표준) 중 이 구간에 드는 몫에 곱하는 비율.", s="note")
        r += 1
        u = None
        if top is not None:
            ip.set(r, B, "법인세율 %d구간 끝 금액" % (i + 1), s="td")
            ip.set(r, Cc, "", s="td")
            u = q(S_IN, ip.set(r, Dd, top, s="in"))
            ip.set(r, Ee, top, s="orig")
            ip.set(r, F, "이 금액까지 %d구간 세율, 넘는 몫은 다음 구간 세율." % (i + 1), s="note")
            r += 1
            low_txt = top
        BR.append((u, rt))

    def tax_row(label, val, style, ostyle, note):
        nonlocal r
        ip.set(r, B, label, s="td")
        ip.set(r, Cc, "", s="td")
        a = q(S_IN, ip.set(r, Dd, val, s=style))
        ip.set(r, Ee, val, s=ostyle)
        ip.set(r, F, note, s="note")
        r += 1
        return a
    LOC = tax_row("지방소득세율 (법인세의 몇 %)", TI["local"], "inp", "origp", "법인지방소득세 = 법인세 산출세액 × 이 비율.")
    MINR = tax_row("최저한세율", TI["min"], "inp", "origp", "감면·공제를 받아도 법인세는 '세금 매기는 이익 × 이 비율' 밑으로는 안 줄어듭니다 (중소기업).")
    SPR = tax_row("중소기업 특별세액감면 비율", TI["sp_rate"], "inp", "origp",
                  "감면 전 법인세 × 이 비율만큼 깎아 줍니다 (작년 신고서의 감면 ÷ 산출세액). 이익이 줄면 감면도 같이 줄어듭니다.")
    POOL = tax_row("쓸 수 있는 세액공제 (넘어온 것 + 올해 '받음')", TI["pool"], "in", "orig",
                   "세금에서 바로 빼 주는 금액. 최저한세 밑으로는 못 줄여서, 남는 몫은 내년으로 넘어갑니다.")
    NSH = tax_row("그 공제 중 농어촌특별세 대상 비율", TI["nong_share"], "inp", "origp", "고용·투자 공제처럼 쓴 만큼 농어촌특별세를 따로 내는 공제의 몫.")
    NONG = tax_row("농어촌특별세율", TI["nong"], "inp", "origp", "쓴 공제(농특세 대상) × 이 비율을 농어촌특별세로 냅니다.")
    OUTC = tax_row("최저한세와 상관없이 빼는 공제", TI["out"], "in", "orig", "연구·인력개발비 공제처럼 최저한세 밑으로도 줄여 주는 공제 ('받음' 표시한 것).")
    ADJ = tax_row("세법 조정 금액 (세무조정)", TI["adj"], "in", "orig",
                  "세법이 비용으로 안 쳐 주는 금액(접대비 한도 초과 등)을 이익에 더하는 값. 프로그램 법인세 예상과 맞춘 값입니다.")
    R0 = tax_row("지난해까지 영업외수익에 낸 세금 비율", round(C["rate0"], 4), "inp", "origp",
                 "지난해까지 영업외수익을 빼면 그때 낸 세금도 덜 낸 것으로 봅니다: %s." % (" · ".join(C["how0"]) or "지난해 영업외수익 없음"))
    ip.set(r, B, "지난해까지 빼는 이익 (세금 뺀 뒤)", s="tdb")
    ip.set(r, Cc, "", s="td")
    G0 = q(S_IN, ip.set(r, Dd, f="%s-ROUND(%s*%s,0)" % (X0, X0, R0), s="calc"))
    ip.set(r, Ee, "", s="td")
    ip.set(r, F, "= 지난해까지 뺄 영업외수익 − 그 세금 (계산 칸).", s="note")
    r += 1

    def corp_f(x):
        """과세표준 칸 x → 법인세 산출세액 수식 (구간별 누진)."""
        terms, low = [], "0"
        for u, rt in BR:
            if u is None:
                terms.append("MAX(0,%s-%s)*%s" % (x, low, rt))
            else:
                terms.append("MAX(0,MIN(%s,%s)-%s)*%s" % (x, u, low, rt))
                low = u
        return "INT(%s)" % "+".join(terms)

    over_where = collections.defaultdict(list)
    for i, (nm, v, where, why) in enumerate(C["over"]):
        for w in ("판관비", "원가", "영업외비용", "법인세"):
            if w in where:
                over_where[w].append(_circ(i))

    # ══════════ 손익 ══════════
    P = C["P"]
    sh = pl_
    r = 1
    sh.set(r, B, "손익 — %s (결산 비용 넣은 모습)" % period, s="title")
    sh.heights[r] = 26
    r += 1
    r = para(sh, r, "회사 전체 = 장부 값 + 결산 때 들어갈 비용. 기획본부 기준 = 회사 전체에서 영업외수익만 빼고 세금을 다시 계산한 값. "
                    "차이 = 기획본부 기준 − 회사 전체 (빨간 숫자는 기획본부 기준이 더 작다는 뜻).", s="box", h=34)
    r += 1
    r = head(sh, r, "이익 계산", ("항목", "회사 전체", "기획본부 기준", "차이", "설명"))

    def pl(label, val=None, f=None, fe=None, note="", bold=False, small=False):
        """회사 전체(C), 기획본부(D, 없으면 같음), 차이(E) = D − C."""
        nonlocal r
        ns = "numb" if bold else ("nums" if small else "num")
        sh.set(r, B, label, s="tdb" if bold else ("tds" if small else "td"))
        c_ = sh.set(r, Cc, val, f=f, s=ns)
        d_ = sh.set(r, Dd, None, f=fe or c_, s=ns)
        sh.set(r, Ee, None, f="%s-%s" % (d_, c_), s="difb" if bold else "dif")
        sh.set(r, F, note, s="note")
        r += 1
        return r - 1
    A_ = lambda row: xlsxw.addr(row, Cc)
    E_ = lambda row: xlsxw.addr(row, Dd)
    mo_note = "'계정별 월별' 탭 %s 합계. "
    rv = pl("매출", f=TOT["rev"], note=mo_note % "매출")
    cg = pl("매출원가 (프로젝트 원가)", f=TOT["cogs"], note=mo_note % "매출원가" + _mark(over_where["원가"]))
    sg = pl("판매비와관리비 (장부)", f=TOT["sga"], note=mo_note % "판매비와관리비" + ("경영관리 부서 비용·급여와 회사 공통 비용(플랜트8)이 모두 들어 있습니다 (아래 줄). " if C.get("dept") else "")
            + _mark(over_where["판관비"]))
    for nm_, sal_, oth_ in C.get("dept") or []:   # 판관비에 이미 든 몫을 보여 주기만 (합계에 다시 더하지 않음)
        # 급여와 그 밖을 합친 한 금액만 (사용자 2026-11-18 결정 '합쳐서 한 금액으로': 부서 인원이 적으면 급여 금액이 곧 개인 급여)
        sh.set(r, B, "   └ 그중 %s (급여 포함)" % nm_, s="tds")
        sh.set(r, Cc, sal_ + oth_, s="nums")
        sh.set(r, Dd, sal_ + oth_, s="nums")
        sh.set(r, Ee, 0, s="dif")
        sh.set(r, F, "위 판관비에 이미 들어 있음 (보여 주기만, 다시 더하지 않음). 회사 기본 비용이라 기획본부 기준에도 그대로.", s="note")
        r += 1
    kc = pl("결산 때 들어갈 비용", f=K, note="'바꿀 값' 탭 1번에서 '예'로 둔 것 (감가상각·대손충당금·퇴직급여·상여금 등).")
    op = pl("영업이익", f="%s-%s-%s-%s" % (A_(rv), A_(cg), A_(sg), A_(kc)), fe="%s-%s-%s-%s" % (E_(rv), E_(cg), E_(sg), E_(kc)), bold=True,
            note="매출 − 매출원가 − 판관비 − 결산 비용. 본업으로 번 돈.")
    ni = pl("영업외수익 (이자·정부지원금·잡이익 등)", f=TOT["nin"], fe="%s-%s" % (A_(r), X1),
            note=mo_note % "영업외수익" + "본업이 아닌 데서 들어온 돈. 기획본부 기준에서는 '바꿀 값' 탭 2번에서 '예'로 둔 만큼 뺍니다.")
    no = pl("영업외비용 (대출 이자 등)", f=TOT["nout"], note=mo_note % "영업외비용" + "빼지 않고 그대로 둡니다. " + _mark(over_where["영업외비용"]))
    pre = pl("세금 내기 전 이익", f="%s+%s-%s" % (A_(op), A_(ni), A_(no)), fe="%s+%s-%s" % (E_(op), E_(ni), E_(no)), bold=True,
             note="영업이익 + 영업외수익 − 영업외비용.")
    r += 1
    r = head(sh, r, "세금 계산 (올해 법인세 예상)", ("항목", "회사 전체", "기획본부 기준", "차이", "설명"))
    nd_f = "+".join('IF(%s="예",%s,0)' % (K_rows[x["key"]][1], K_rows[x["key"]][0]) for x in costs if x.get("no_deduct")) or "0"
    nd = pl("세금 계산에서는 안 빼는 결산 비용 (퇴직급여 쌓는 몫)", f=nd_f, small=True,
            note="이익에서는 뺐지만 세법이 비용으로 인정하지 않아 세금 매기는 이익에는 다시 더합니다 (실제로 준 퇴직금·퇴직연금에 낸 돈만 인정).")
    bs = pl("세금 매기는 이익 (과세표준)", f="MAX(0,%s+%s+%s)" % (A_(pre), ADJ, A_(nd)), fe="MAX(0,%s+%s+%s)" % (E_(pre), ADJ, E_(nd)), small=True,
            note="세금 내기 전 이익 + 세법 조정 금액 ('바꿀 값' 탭 3번) + 위 줄.")
    cp = pl("법인세 (감면 전)", f=corp_f(A_(bs)), fe=corp_f(E_(bs)), small=True, note="세금 매기는 이익 × 구간별 법인세율.")
    def cred_f(cp_, bs_):
        fl = "INT(%s*%s)" % (bs_, MINR)
        sp = "MIN(INT(%s*%s),MAX(%s-%s,0))" % (cp_, SPR, cp_, fl)
        return sp, "MIN(%s,MAX(%s-%s-%s,0))" % (POOL, cp_, sp, fl)
    spA, usA = cred_f(A_(cp), A_(bs))
    spE, usE = cred_f(E_(cp), E_(bs))
    sp_r = pl("   − 중소기업 특별세액감면", f=spA, fe=spE, small=True, note="감면 전 법인세 × 감면 비율. 최저한세 밑으로는 못 줄입니다.")
    us_r = pl("   − 세액공제 쓴 금액", f=usA, fe=usE, small=True, note="쓸 수 있는 공제 중 최저한세까지 줄이는 데 쓴 금액.")
    nt = pl("법인세 (감면·공제 뒤, 농어촌특별세 포함)",
            f="%s-%s-%s-MIN(%s,MAX(%s-%s-%s,0))+INT(%s*%s*%s/10)*10" % (A_(cp), A_(sp_r), A_(us_r), OUTC, A_(cp), A_(sp_r), A_(us_r), A_(us_r), NSH, NONG),
            fe="%s-%s-%s-MIN(%s,MAX(%s-%s-%s,0))+INT(%s*%s*%s/10)*10" % (E_(cp), E_(sp_r), E_(us_r), OUTC, E_(cp), E_(sp_r), E_(us_r), E_(us_r), NSH, NONG), small=True,
            note="감면 전 법인세 − 감면 − 공제 + 쓴 공제의 농어촌특별세.")
    lc = pl("법인지방소득세", f="INT(%s*%s)" % (A_(cp), LOC), fe="INT(%s*%s)" % (E_(cp), LOC), small=True, note="감면 전 법인세 × 지방소득세율.")
    tx = pl("올해 세금 예상 합계", f="%s+%s" % (A_(nt), A_(lc)), fe="%s+%s" % (E_(nt), E_(lc)), bold=True,
            note=("처음 값 그대로면 프로그램 법인세 예상과 같은 계산입니다 (결산 비용을 더 넣은 만큼 이익이 줄어 세금은 그보다 적습니다). "
                  if TI.get("same") else "프로그램 법인세 예상과 계산이 조금 다릅니다 (감면·공제 순서). ") + _mark(over_where["법인세"]))
    TAX, TAXE = q(S_PL, A_(tx)), q(S_PL, E_(tx))
    tb = None
    if P["tax_booked"]:
        tb = pl("장부에 이미 넣은 법인세등", f=TOT["tax"], note="올해 장부의 법인세등 계정. 위 예상과 겹칠 수 있으니 확인하세요.")
    r += 1
    net = pl("올해 순이익 (세금 뺀 뒤)", f="%s-%s%s" % (A_(pre), A_(tx), ("-" + A_(tb)) if tb else ""),
             fe="%s-%s%s" % (E_(pre), E_(tx), ("-" + E_(tb)) if tb else ""), bold=True,
             note="세금 내기 전 이익 − 세금. 회사에 남는 올해 이익.")
    PL = dict((k, (q(S_PL, A_(v)), q(S_PL, E_(v)))) for k, v in
              (("rev", rv), ("op", op), ("nin", ni), ("pre", pre), ("tax", tx), ("net", net)))
    PRE_C, PRE_D = PL["pre"]
    PRE_DIF = q(S_PL, xlsxw.addr(pre, Ee))
    TB = (q(S_PL, A_(tb)), q(S_PL, xlsxw.addr(tb, Ee))) if tb else None

    # ══════════ 재무상태표 ══════════
    sh = bs_
    r = 1
    sh.set(r, B, "재무상태표 — %s (결산 비용 넣은 모습)" % asof_txt, s="title")
    sh.heights[r] = 26
    r += 1
    r = para(sh, r, "자산(가진 것) = 부채(갚을 것) + 자본(회사 몫). 기획본부 기준은 영업외수익으로 들어온 돈을 통장에서 빼고, 그만큼 이익(자본)과 세금(부채)도 줄인 모습입니다. "
                    "차이 = 기획본부 기준 − 회사 전체.", s="box", h=34)
    r += 1
    sh.set(r, B, "항목", s="th")
    for c, t in ((Cc, "회사 전체"), (Dd, "기획본부 기준"), (Ee, "차이"), (F, "설명")):
        sh.set(r, c, t, s="th")
    r += 1

    def line(label, val=None, f=None, adj=None, note="", style="td"):
        """회사 전체(C) · 차이(E, adj 수식) · 기획본부(D) = C + E."""
        nonlocal r
        sh.set(r, B, label, s=style)
        sh.set(r, Cc, val, f=f, s="num")
        if adj:
            sh.set(r, Ee, f=adj, s="dif")
        else:
            sh.set(r, Ee, 0, s="dif")
        sh.set(r, Dd, f="%s+%s" % (xlsxw.addr(r, Cc), xlsxw.addr(r, Ee)), s="num")
        sh.set(r, F, note, s="note")
        r += 1
        return r - 1

    def group(title, items, extra=None, note=""):
        nonlocal r
        sh.set(r, B, title, s="grp")
        for c in (Cc, Dd, Ee, F):
            sh.set(r, c, note if c == F else "", s="grp")
        r += 1
        first = r
        for code, name, v in items:
            line("  %s [%s]" % (name, code), v)
        if extra:
            extra()
        last = r - 1
        if last < first:
            line("  (없음)", 0)
            last = r - 1
        tot = r
        sh.set(r, B, title + " 합계", s="tdb")
        for c in (Cc, Dd):
            sh.set(r, c, f="SUM(%s:%s)" % (xlsxw.addr(first, c), xlsxw.addr(last, c)), s="numt")
        sh.set(r, Ee, f="SUM(%s:%s)" % (xlsxw.addr(first, Ee), xlsxw.addr(last, Ee)), s="dift")
        sh.set(r, F, "", s="note")
        r += 1
        return tot

    def total(label, a, b):
        nonlocal r
        sh.set(r, B, label, s="tdb")
        for c in (Cc, Dd):
            sh.set(r, c, f="%s+%s" % (xlsxw.addr(a, c), xlsxw.addr(b, c)), s="numt")
        sh.set(r, Ee, f="%s+%s" % (xlsxw.addr(a, Ee), xlsxw.addr(b, Ee)), s="dift")
        sh.set(r, F, "", s="note")
        r += 1
        return r - 1

    G = C["groups"]
    ca = group("유동자산 (1년 안에 돈이 되는 것)", G["ca"], lambda: line("  영업외수익으로 들어온 돈 빼기", 0, adj="-(%s+%s)" % (X1, G0),
                                                  note="영업외수익으로 들어온 돈을 통장 돈에서 뺍니다. 올해 몫은 전부, 지난해 몫은 그때 낸 세금을 뺀 만큼."))

    def na_extra():
        line("  감가상각·대손충당금 (결산 예상, 자산 줄임)", f="-(%s)" % side_sum("asset"),
             note="'바꿀 값' 탭 1번의 감가상각비·대손충당금 중 '예'인 것. 장비 값과 받을 돈을 그만큼 줄여 봅니다.")
    na = group("비유동자산 (장비·보증금 등)", G["na"] + ([("?", "종류를 모르는 계정 (확인 필요)", C["unknown"])] if C["unknown"] else []), na_extra)
    ta = total("자산 총계 (가진 것)", ca, na)

    def cl_extra():
        line("  올해 세금 예상 (아직 장부에 없음)", f=TAX, adj="%s-%s" % (TAXE, TAX),
             note="결산 때 장부에 들어갈 올해 세금을 미리 빚으로 잡습니다. 기획본부 기준은 줄어드는 세금만큼 작습니다.")
        line("  결산 비용 중 낼 돈 (퇴직급여·상여금·카드·4대보험, 예상)", f=side_sum("liab"),
             note="'바꿀 값' 탭 1번의 퇴직급여·상여금·카드값·4대보험 회사분 중 '예'인 것. 아직 안 낸 돈이라 빚으로 잡습니다.")
    cl = group("유동부채 (1년 안에 갚을 것)", G["cl"], cl_extra)
    # 2차 전수조사 J23: 만기가 1년 안에 오는 대출이 '1년 뒤 갚을 것'에 있어 헷갈림 → 장부 분류 그대로인 까닭을 적음
    nl = group("비유동부채 (1년 뒤 갚을 것)", G["nl"],
               note="위하고 장부 분류 그대로입니다. 대출은 만기가 1년 안에 와도 매년 연장할 예정이라 여기에 둡니다 (만기일은 경영관리 보고 ‘자금’)." if G["nl"] else "")
    tl = total("부채 총계 (갚을 것)", cl, nl)

    def eq_extra():
        line("  이익잉여금 (지난해까지 쌓인 이익)", C["retained"], adj="-%s" % G0,
             note="기획본부 기준은 지난해까지 영업외수익(세금 뺀 뒤)만큼 작습니다. %d년 전 이월 이익에 든 영업외수익은 장부에 없어 빼지 못했습니다." % C["first_year"])
        line("  올해 이익 (세금 전)", f=PRE_C + (("-" + TB[0]) if TB else ""), adj=PRE_DIF + (("-" + TB[1]) if TB else ""),
             note="'손익' 탭의 세금 내기 전 이익%s. 기획본부 기준은 올해 영업외수익만큼 작습니다." % (" − 장부 법인세등" if TB else ""))
        line("  올해 세금 예상", f="-" + TAX, adj="%s-%s" % (TAX, TAXE), note="부채의 '올해 세금 예상'과 같은 금액을 이익에서 뺍니다.")
    eq = group("자본 (회사 몫 = 자산 − 부채)", C["capital"], eq_extra)
    tle = total("부채와 자본 총계", tl, eq)
    sh.set(r, B, "맞춤 확인 (자산 총계 − 부채와 자본 총계)", s="td")
    for c in (Cc, Dd, Ee):
        sh.set(r, c, f="%s-%s" % (xlsxw.addr(ta, c), xlsxw.addr(tle, c)), s="ok")
    sh.set(r, F, "0이면 자산 = 부채 + 자본이 맞습니다.", s="note")
    chk = r
    BSX = dict((k, (q(S_BS, xlsxw.addr(v, Cc)), q(S_BS, xlsxw.addr(v, Dd)))) for k, v in
               (("assets", ta), ("liab", tl), ("equity", eq), ("check", chk)))

    # ══════════ 바꿀 값: 결과 미리 보기 ══════════
    r = prev_row
    for c, t in ((B, "결과 미리 보기 (노란 칸을 바꾸면 바로 바뀜)"), (Cc, ""), (Dd, "회사 전체"), (Ee, "기획본부 기준"), (F, "")):
        ip.set(r, c, t, s="th")
    ip.merge(r, B, r, Cc)
    r += 1
    for label, (a, b), note in (("올해 세금 예상", PL["tax"], "법인세 + 지방소득세"),
                                ("올해 순이익 (세금 뺀 뒤)", PL["net"], "회사에 남는 올해 이익"),
                                ("자본 총계 (회사 몫)", BSX["equity"], "자산 − 부채"),
                                ("부채 총계 (갚을 것)", BSX["liab"], "결산 비용 중 낼 돈·세금 포함")):
        ip.set(r, B, label, s="tdb")
        ip.set(r, Cc, "", s="td")
        ip.merge(r, B, r, Cc)
        ip.set(r, Dd, f=a, s="numb")
        ip.set(r, Ee, f=b, s="numb")
        ip.set(r, F, note, s="note")
        r += 1

    # ══════════ 요약 ══════════
    sh = sm
    r = 1
    sh.set(r, B, "기획본부용 재무상태표", s="title")
    sh.heights[r] = 28
    r += 1
    sh.set(r, B, "%s 기준 · 회사 전체 숫자에서 영업외수익(이자·정부지원금·잡이익 등)만 뺀 모습 · 손익은 %s" % (asof_txt, period), s="sub")
    r += 1
    sh.set(r, B, made, s="sub")
    r += 2
    r = head(sh, r, "한눈에 보기", ("항목", "회사 전체", "기획본부 기준", "차이", "뜻"))
    for label, (a, b), note in (
            ("매출", PL["rev"], "같음 — 영업외수익만 빼므로 매출은 그대로입니다."),
            ("영업이익 (본업으로 번 돈)", PL["op"], "같음 — 결산 비용(감가상각·퇴직급여·상여금 등)을 넣은 값입니다."),
            ("영업외수익 (이자·지원금 등)", PL["nin"], "기획본부가 만든 이익이 아니라서 기획본부 기준에서 뺍니다."),
            ("올해 세금 예상", PL["tax"], "이익이 줄어든 만큼 세금도 줄어듭니다."),
            ("올해 순이익 (세금 뺀 뒤)", PL["net"], "회사에 남는 올해 이익."),
            ("자산 총계 (가진 것)", BSX["assets"], "영업외수익으로 들어온 돈만큼 작습니다."),
            ("부채 총계 (갚을 것)", BSX["liab"], "세금 예상이 줄어든 만큼 작습니다."),
            ("자본 총계 (회사 몫)", BSX["equity"], "기획본부가 만든 이익으로만 쌓인 회사 몫.")):
        big = label.startswith(("올해 순이익", "자본 총계"))
        sh.set(r, B, label, s="kpil" if big else "td")
        sh.set(r, Cc, f=a, s="kpi" if big else "num")
        sh.set(r, Dd, f=b, s="kpi" if big else "num")
        sh.set(r, Ee, f="%s-%s" % (xlsxw.addr(r, Dd), xlsxw.addr(r, Cc)), s="difk" if big else "dif")
        sh.set(r, F, note, s="note")
        if big:
            sh.heights[r] = 22
        r += 1
    sh.set(r, B, "표 맞춤 (자산 = 부채 + 자본)", s="td")
    sh.set(r, Cc, f='IF(ABS(%s)+ABS(%s)<1,"맞음","안 맞음")' % BSX["check"], s="okt")
    sh.set(r, Dd, "", s="td")
    sh.set(r, Ee, "", s="td")
    sh.merge(r, Cc, r, Ee)
    sh.set(r, F, "'안 맞음'이면 파일을 프로그램에서 다시 만드세요.", s="note")
    r += 2
    r = para(sh, r, "기획본부 기준은 이렇게 만들었습니다", s="boxb")
    for t in ("① 회사 전체 장부 값 그대로에 결산 때 들어갈 비용(감가상각·대손충당금·퇴직급여·카드값·4대보험 회사분, 정해지면 연말 상여금)을 넣었습니다. "
              "경영관리 부서 비용·급여, 회사 공통 비용(플랜트8)과 영업외비용(대출 이자 등)도 그대로 둡니다.",
              "② 영업외수익(이자·정부지원금·잡이익 등)만 뺐습니다. 기획본부가 만든 이익이 아니기 때문입니다.",
              "③ 이익이 줄어든 만큼 세금도 다시 계산했습니다 (법인세 + 지방소득세)."):
        r = para(sh, r, t, s="box", h=30)
    r += 1
    r = para(sh, r, "숫자를 바꿔 보려면", s="boxb")
    for t in ("① 아래 '바꿀 값' 탭(노란색)을 엽니다.",
              "② 노란 칸만 바꾸세요. 연말 상여금이 정해지면 금액을, 빼지 않을 영업외수익은 '아니오'를 고릅니다. 다른 칸은 잠겨 있어 바뀌지 않습니다.",
              "③ 바꾸면 이 요약과 '손익'·'재무상태표' 탭이 바로 다시 계산됩니다. 되돌리려면 '처음 값' 칸 숫자를 다시 적으세요."):
        r = para(sh, r, t, s="yel", h=30)
    r += 1
    r = para(sh, r, "탭 안내: 요약(이 장) · 바꿀 값(노란 칸) · 손익(이익과 세금 계산) · 계정별 월별(분개장 계정을 달마다, 손익의 근거) · 재무상태표(계정별) · 참고(크게 잡혔을 수 있는 비용·낱말 풀이)", s="sub")

    # ══════════ 참고 ══════════
    sh = rf
    r = 1
    sh.set(r, B, "참고", s="title")
    sh.heights[r] = 26
    r += 1
    sh.set(r, B, "1. 기획본부가 알기 어려운, 비용이 크게 잡혔을 수 있는 항목", s="sec")
    for c in (Cc, Dd, Ee, F):
        sh.set(r, c, "", s="sec")
    r += 1
    for c, t in ((B, "항목"), (Cc, "올해 금액"), (Dd, "어디에 들었나"), (Ee, ""), (F, "왜 크게 보일 수 있나")):
        sh.set(r, c, t, s="th")
    r += 1
    for i, (nm, v, where, why) in enumerate(C["over"]):
        sh.set(r, B, "%s %s" % (_circ(i), nm), s="td")
        sh.set(r, Cc, v, s="num")
        sh.set(r, Dd, where, s="td")
        sh.set(r, Ee, "", s="td")
        sh.set(r, F, why, s="note")
        r += 1
    if not C["over"]:
        sh.set(r, B, "올해 장부에 해당 항목 없음", s="td")
        r += 1
    r = para(sh, r, "이 항목들은 표에서 빼지 않았습니다 (회사 전체 비용 그대로). '이만큼은 기획본부가 직접 만든 비용이 아닐 수 있다'고 보고 읽으세요.", h=30)
    r += 1
    sh.set(r, B, "2. 낱말 풀이", s="sec")
    for c in (Cc, Dd, Ee, F):
        sh.set(r, c, "", s="sec")
    r += 1
    for w, t in (("영업외수익", "본업(행사·프로젝트)이 아닌 데서 들어온 돈. 예금 이자, 정부지원금, 잡이익 등."),
                 ("결산 비용", "연말 결산 때 장부에 한꺼번에 넣는 비용. 감가상각비(장비 값 줄어듦), 대손충당금(못 받을 수 있는 돈), 퇴직급여, 상여금 등."),
                 ("세금 매기는 이익 (과세표준)", "세금 내기 전 이익에 세법 조정을 더한 금액. 여기에 법인세율을 곱합니다."),
                 ("최저한세", "감면·공제를 받아도 최소한 내야 하는 법인세."),
                 ("이익잉여금", "지난해까지 회사에 쌓인 이익 (배당 등으로 나가지 않은 몫)."),
                 ("자본", "자산 − 부채. 회사가 빚을 다 갚고 남는 회사 몫.")):
        sh.set(r, B, w, s="tdb")
        sh.set(r, Cc, t, s="td")
        for c in (Dd, Ee, F):
            sh.set(r, c, "", s="td")
        sh.merge(r, Cc, r, F)
        r += 1
    r += 1
    sh.set(r, B, "3. 사용한 자료", s="sec")
    for c in (Cc, Dd, Ee, F):
        sh.set(r, c, "", s="sec")
    r += 1
    r = para(sh, r, made, h=30)
    r = para(sh, r, "회사 전체 칸은 위하고 분개장(계정별·달별 합계, '계정별 월별' 탭)과 프로그램 예상(결산 비용·법인세)입니다. 진행 중 프로젝트의 남은 원가는 넣지 않았습니다.", h=30)

    C["_cells"] = {"check": [q(S_BS, xlsxw.addr(chk, c)) for c in (Cc, Dd)], "net": PL["net"], "K": K, "tax": (TAX, TAXE),
                   "equity": BSX["equity"], "assets": BSX["assets"]}
    return bk


def monthly_sheet(sh, C, para):
    """'계정별 월별' 탭: 올해 손익 계정을 계정(세목)마다 1~M월로. -> {종류: 합계 칸 주소(다른 탭에서 쓰는 꼴)}."""
    M = C["M"]
    B, c1 = 2, 3
    tc = c1 + M          # 합계 열
    sh.widths[1], sh.widths[B] = 2, 36
    for c in range(c1, tc):
        sh.widths[c] = 13
    sh.widths[tc] = 15
    r = 1
    sh.set(r, B, "계정별 월별 — %d년 1~%d월 (분개장)" % (C["Y"], M), s="title")
    sh.heights[r] = 26
    r += 1
    sh.set(r, B, "위하고 분개장의 손익 계정을 계정과목(세목)마다 달별로 더한 표입니다. '손익' 탭의 매출·원가·판관비·영업외수익·영업외비용은 이 표의 합계에서 계산합니다. "
                 "수익은 대변 − 차변, 비용은 차변 − 대변. 결산 때 들어갈 비용(감가상각 예상 등)은 장부에 아직 없어 여기 없고 '바꿀 값' 탭에 있습니다.", s="box")
    for c in range(B + 1, tc + 1):
        sh.set(r, c, "", s="box")
    sh.merge(r, B, r, tc)
    sh.heights[r] = 34
    r += 2
    sh.set(r, B, "계정 [코드]", s="th")
    for i in range(M):
        sh.set(r, c1 + i, "%d월" % (i + 1), s="th")
    sh.set(r, tc, "합계 (1~%d월)" % M, s="th")
    r += 1
    tot, sub = {}, {}
    for k in MON_KINDS:
        items = C["monthly"].get(k) or []
        if k == "tax" and not items:
            continue
        sh.set(r, B, MON_NAMES[k], s="grp")
        for c in range(c1, tc + 1):
            sh.set(r, c, "", s="grp")
        r += 1
        first = r
        for code, name, months in items:
            sh.set(r, B, "  %s [%s]" % (name, code), s="td")
            for i, v in enumerate(months):
                sh.set(r, c1 + i, v, s="num")
            sh.set(r, tc, f="SUM(%s:%s)" % (xlsxw.addr(r, c1), xlsxw.addr(r, tc - 1)), s="numb")
            r += 1
        if not items:
            sh.set(r, B, "  (없음)", s="tds")
            for c in range(c1, tc):
                sh.set(r, c, 0, s="num")
            sh.set(r, tc, f="SUM(%s:%s)" % (xlsxw.addr(r, c1), xlsxw.addr(r, tc - 1)), s="numb")
            r += 1
        sh.set(r, B, MON_NAMES[k] + " 합계", s="tdb")
        for c in range(c1, tc + 1):
            sh.set(r, c, f="SUM(%s:%s)" % (xlsxw.addr(first, c), xlsxw.addr(r - 1, c)), s="numt")
        sub[k] = r
        tot[k] = q(S_MO, xlsxw.addr(r, tc))
        r += 1
    r += 1
    sh.set(r, B, "달별 이익 (결산 비용 넣기 전)", s="grp")
    for c in range(c1, tc + 1):
        sh.set(r, c, "", s="grp")
    r += 1
    for label, f in (("영업이익", "{rev}-{cogs}-{sga}"), ("세금 내기 전 이익", "{rev}-{cogs}-{sga}+{nin}-{nout}")):
        sh.set(r, B, label, s="tdb")
        for c in range(c1, tc + 1):
            sh.set(r, c, f=f.format(**dict((k, xlsxw.addr(v, c)) for k, v in sub.items())), s="numb")
        r += 1
    sh.protect, sh.tab = True, "70AD47"
    tot.setdefault("tax", "0")
    return tot


def _circ(i):
    return "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"[i] if i < 15 else "(%d)" % (i + 1)


def _mark(items):
    return ("※ '참고' 탭 1번 %s 들어 있음" % "·".join(items)) if items else ""


def write(C, out_dir, sources=""):
    """출력\\기획본부\\YYYY-MM-DD_기획본부_재무상태표.xlsx 로 쓴다 (엑셀에서 열려 있으면 _2, _3 …). -> (경로, Book)."""
    folder = os.path.join(out_dir, OUT_SUB)
    os.makedirs(folder, exist_ok=True)
    bk = build(C, sources)
    base = os.path.join(folder, "%s_기획본부_재무상태표" % C["asof"].isoformat())
    path, n = base + ".xlsx", 1
    while True:
        try:
            bk.save(path, STYLES)
            return path, bk
        except PermissionError:
            n += 1
            if n > 20:
                raise
            path = "%s_%d.xlsx" % (base, n)


def summary(C, bk):
    """한 줄 (창·경영관리)."""
    cn, en = (bk.value(a) for a in C["_cells"]["net"])
    ce, ee = (bk.value(a) for a in C["_cells"]["equity"])
    return ("기획본부 기준 (%d년 1~%d월): 뺀 영업외수익 올해 %s원·지난해까지 %s원 → 당기순이익 %s원 (회사 전체 %s원), 자본 %s원 (회사 전체 %s원)"
            % (C["Y"], C["M"], "{:,}".format(C["X1"]), "{:,}".format(C["X0"]), "{:,}".format(int(en)), "{:,}".format(int(cn)),
               "{:,}".format(int(ee)), "{:,}".format(int(ce))))
