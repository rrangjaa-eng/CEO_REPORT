"""기획본부용 재무상태표 (사용자 2026-11-17).

사용자 말:
- "기획본부에서 볼 재무상태표를 따로 만들 수 있게 해. 영업외 수익은 기획본부가 발생시킨 이익이 아니니까 해당 값은 제외한 재무상태표."
- "특정 값을 바꾸면 자동으로 모든 항목이 계산되는 양식으로."
- "경영관리본부의 비용도 들어가야 해. 영업외 수익만 제외하는 거야." → 회사 전체 장부에서 영업외수익만 뺀다 (영업외비용·경영관리·플랜트8 비용은 그대로).
- "기획본부는 알 수 없으나 비용이 과대계상될 수 있는 항목들도 표시하고 설명을 추가해."

만드는 것: 엑셀(xlsx) 한 장. 노란 칸(영업외수익 계정별 금액·뺄지·세금 줄어드는 비율·법인세 예상)을 바꾸면
손익 요약·재무상태표·차이가 수식으로 다시 계산된다.

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


def _tax_rows(input_dir):
    return _rows(os.path.join(input_dir, "세금예상.csv"))


def closing_costs(input_dir, kinds, names, ytd, Y, M):
    """결산 때 들어갈 비용 예상 (사용자 2026-11-17: 진행 중 프로젝트 남은 원가만 빼고 전부 넣어).
    -> [{key, name, amount, in_base(법인세 예상 과세표준에 이미 빠짐), side('asset' 자산 줄임 | 'liab' 갚을 돈), why}]. 모두 실제 자료로 계산한 값."""
    from . import tax as _tax
    rows = _tax_rows(input_dir)
    ct = [r for r in rows if (r.get("세목") or "").strip() == "법인세" and (r.get("대상기간") or "").startswith("%d년 (1월~" % Y)]
    basis = (ct[0].get("근거") or "") if ct else ""
    out = []
    m = re.search(r"감가상각비 예상 ([\d,]+)", basis)
    dep = _int(m.group(1)) if m else 0
    out.append({"key": "dep", "name": "감가상각비 (결산 전 몫)", "amount": dep or 0, "in_base": bool(m), "side": "asset",
                "why": "연말 결산 때 한 번에 들어가 지금 장부엔 없는 감가상각비 중 1~%d월 몫 (프로그램 법인세 예상과 같은 값%s). 통장 돈은 줄지 않고 장비 값이 줄어듭니다."
                       % (M, "" if m else ", 값 없음")})
    bad = _int(ct[0].get("대손충당금")) if ct else None
    bad_in = bool(re.search(r"−\s*대손충당금", basis))
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
    out.append({"key": "ret", "name": "퇴직급여 (올해 쌓일 몫)", "amount": max(int(round(pay / 12.0)) - paid, 0), "in_base": False, "side": "liab",
                "why": "1년 일하면 한 달 치 급여만큼 퇴직금이 쌓입니다. 올해 1~%d월 급여 ÷ 12 − 장부에 이미 넣은 퇴직급여 %s원 (어림)." % (M, "{:,}".format(paid))})
    out.append({"key": "bonus", "name": "연말 직원 상여금", "amount": 0, "in_base": False, "side": "liab",
                "why": "연말 상여금이 정해지면 금액을 넣으세요 (아직 안 준 돈이라 빚으로 잡고, 이익·세금이 그만큼 줄어듭니다)."})
    return out


def _names(L):
    nm = {}
    for m, code, name, d, c in L["rows"]:
        nm[code] = name
    return nm


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
            else:
                prev_pl[y][k] += c - d
                if k == "nin":
                    prev[y][code] += c - d
        elif k in ("cogs", "sga", "nout", "tax"):
            if y == Y:
                ytd[code] += d - c
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
    base_c = base - K_new
    corp_c = corptax.corp_tax(max(base_c, 0), Y)
    nat_c = corptax.national(max(base_c, 0), str(Y), input_dir)[0] or 0
    from . import taxreturn as _tr
    try:
        min_rate = _tr._min_rate(input_dir, Y)
    except Exception:
        min_rate = _tr.MIN_RATE
    T_all = nat_c + int(corp_c * corptax.LOCAL_RATE)
    tax_in = {"brackets": [(top, rate) for top, rate in corptax.brackets(Y)], "local": corptax.LOCAL_RATE, "min": min_rate,
              "credit": corp_c - nat_c, "adj": adj_fill, "base_c": base_c}

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
    return {"costs": costs, "asof": asof, "ym": ym, "Y": Y, "M": M, "P": P, "nin_rows": nin_rows, "X1": X1, "X0": X0, "T0": T0,
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
YEL, GREY, HEAD, BLUE = "FFF2CC", "F2F2F2", "1F3864", "DDEBF7"
STYLES = {
    "title": {"bold": True, "size": 15, "color": HEAD},
    "sub": {"size": 9, "color": "595959"},
    "sec": {"bold": True, "size": 11, "color": "FFFFFF", "fill": HEAD},
    "th": {"bold": True, "fill": BLUE, "border": True, "align": "center", "wrap": True},
    "td": {"border": True, "wrap": True},
    "tdb": {"border": True, "bold": True},
    "grp": {"bold": True, "fill": GREY, "border": True},
    "num": {"border": True, "num": "int"},
    "numb": {"border": True, "num": "int", "bold": True},
    "numt": {"border": True, "num": "int", "bold": True, "fill": GREY},
    "in": {"border": True, "num": "int", "fill": YEL},
    "inp": {"border": True, "num": "0.0%", "fill": YEL},
    "inc": {"border": True, "fill": YEL, "align": "center"},
    "pct": {"border": True, "num": "0.0%"},
    "note": {"border": True, "wrap": True, "size": 9, "color": "404040"},
    "txt": {"wrap": True, "valign": "top"},
    "ok": {"border": True, "num": "int", "bold": True, "color": "2E7D32"},
}


def build(C, sources=""):
    """-> xlsxw.Book. 수식은 같은 표 안 칸만 쓴다."""
    bk = xlsxw.Book()
    sh = bk.sheet("기획본부 재무상태표")
    for col, w in ((1, 2), (2, 38), (3, 17), (4, 17), (5, 17), (6, 70)):
        sh.widths[col] = w
    B, Cc, Dd, Ee, F = 2, 3, 4, 5, 6
    r = 1
    sh.set(r, B, "기획본부용 재무상태표 (영업외수익 뺀 기준)", s="title")
    sh.heights[r] = 24
    r += 1
    sh.set(r, B, "재무상태표 %d년 %d월 말 · 손익 %d년 1~%d월 · 회사 전체 장부에서 영업외수익(이자·지원금·잡이익 등)을 빼고 결산 때 들어갈 비용(예상)을 더함, 세금도 그만큼 다시 계산 · 경영관리·플랜트8 비용과 영업외비용은 그대로"
           % (C["Y"], C["M"], C["Y"], C["M"]), s="sub")
    r += 1
    sh.set(r, B, (sources + " · " if sources else "") + "법인세: " + C["tax_src"] + " · 만든 날 %s" % dt.date.today().isoformat(), s="sub")
    r += 1
    sh.set(r, B, "노란 칸을 바꾸면 아래 손익·재무상태표가 모두 다시 계산됩니다. 흰 칸은 장부 값 또는 계산식입니다.", s="sub")
    r += 2

    # ① 바꿀 수 있는 값
    sh.set(r, B, "1. 바꿀 수 있는 값 (노란 칸)", s="sec")
    for c in (Cc, Dd, Ee, F):
        sh.set(r, c, "", s="sec")
    r += 1
    for c, t in ((B, "영업외수익 계정"), (Cc, "올해 (1~%d월)" % C["M"]), (Dd, "지난해까지"), (Ee, "뺄까요"), (F, "설명 (장부 값)")):
        sh.set(r, c, t, s="th")
    r += 1
    n0 = r
    for x in C["nin_rows"]:
        sh.set(r, B, "%s [%s]" % (x["name"], x["code"]), s="td")
        sh.set(r, Cc, x["cur"], s="in")
        sh.set(r, Dd, x["prev"], s="in")
        sh.set(r, Ee, "예", s="inc")
        sh.set(r, F, "장부 값: 올해 %s원 · 지난해까지 %s원. '아니오'로 바꾸면 이 계정은 빼지 않습니다."
               % ("{:,}".format(x["cur"]), "{:,}".format(x["prev"])), s="note")
        r += 1
    if not C["nin_rows"]:
        sh.set(r, B, "(장부에 영업외수익 없음)", s="td")
        sh.set(r, Cc, 0, s="in")
        sh.set(r, Dd, 0, s="in")
        sh.set(r, Ee, "예", s="inc")
        sh.set(r, F, "", s="note")
        r += 1
    n1 = r - 1
    sh.choice("%s:%s" % (xlsxw.addr(n0, Ee), xlsxw.addr(n1, Ee)), ["예", "아니오"])
    rng = lambda c: "%s:%s" % (xlsxw.addr(n0, c), xlsxw.addr(n1, c))
    sh.set(r, B, "뺄 영업외수익 합계", s="tdb")
    X1 = sh.set(r, Cc, f='SUMIF(%s,"예",%s)' % (rng(Ee), rng(Cc)), s="numb")
    X0 = sh.set(r, Dd, f='SUMIF(%s,"예",%s)' % (rng(Ee), rng(Dd)), s="numb")
    sh.set(r, Ee, "", s="td")
    sh.set(r, F, "'예'로 둔 계정만 더합니다.", s="note")
    r += 1
    r += 1

    # 결산 비용 (사용자 2026-11-17: 재무상태표는 결산 때 만드는 것 → 진짜 재무상태표 값에 감가상각·대손충당금·퇴직급여 등이 들어감. 상여금도 넣을 수 있게)
    for c, t in ((B, "결산 때 들어갈 비용 (회사 전체·기획본부 모두)"), (Cc, "올해 (1~%d월)" % C["M"]), (Dd, ""), (Ee, "넣을까요"), (F, "설명 (프로그램 값)")):
        sh.set(r, c, t, s="th")
    r += 1
    k0 = r
    K_rows = {}
    for x in C["costs"]:
        sh.set(r, B, x["name"], s="td")
        a_ = sh.set(r, Cc, x["amount"], s="in")
        sh.set(r, Dd, "", s="td")
        e_ = sh.set(r, Ee, "예", s="inc")
        sh.set(r, F, "%s 프로그램 값 %s원." % (x["why"], "{:,}".format(x["amount"])), s="note")
        K_rows[x["key"]] = (a_, e_, x["side"])
        r += 1
    k1 = r - 1
    sh.choice("%s:%s" % (xlsxw.addr(k0, Ee), xlsxw.addr(k1, Ee)), ["예", "아니오"])
    krng = lambda c: "%s:%s" % (xlsxw.addr(k0, c), xlsxw.addr(k1, c))
    sh.set(r, B, "넣을 비용 합계", s="tdb")
    K = sh.set(r, Cc, f='SUMIF(%s,"예",%s)' % (krng(Ee), krng(Cc)), s="numb")
    sh.set(r, Dd, "", s="td")
    sh.set(r, Ee, "", s="td")
    sh.set(r, F, "'예'로 둔 비용만 더합니다. 회사 전체와 기획본부 기준 모두에 들어갑니다.", s="note")
    r += 2

    def side_sum(side):
        parts = ['IF(%s="예",%s,0)' % (e_, a_) for a_, e_, sd in K_rows.values() if sd == side]
        return "+".join(parts) if parts else "0"

    # 법인세 계산 값 (사용자 2026-11-17: 법인세율도 조정할 수 있게)
    TI = C["tax_in"]
    for c, t in ((B, "법인세 계산 (올해)"), (Cc, "과세표준 구간 상한"), (Dd, "세율"), (Ee, ""), (F, "설명")):
        sh.set(r, c, t, s="th")
    r += 1
    BR = []
    for i, (top, rate) in enumerate(TI["brackets"]):
        sh.set(r, B, "법인세율 %d구간" % (i + 1), s="td")
        u = sh.set(r, Cc, top if top is not None else "", s="in" if top is not None else "td")
        rt = sh.set(r, Dd, rate, s="inp")
        sh.set(r, Ee, "", s="td")
        sh.set(r, F, ("과세표준 %s원까지 %s%%" % ("{:,}".format(top), "{:g}".format(rate * 100))) if top is not None
               else "그 위 전부 %s%%" % "{:g}".format(rate * 100), s="note")
        BR.append((u if top is not None else None, rt))
        r += 1
    sh.set(r, B, "지방소득세율 (법인세 산출세액의)", s="td")
    LOC = sh.set(r, Dd, TI["local"], s="inp")
    sh.set(r, Cc, "", s="td")
    sh.set(r, Ee, "", s="td")
    sh.set(r, F, "법인지방소득세 = 산출세액 × 이 비율 (감면 없이)", s="note")
    r += 1
    sh.set(r, B, "최저한세율", s="td")
    MINR = sh.set(r, Dd, TI["min"], s="inp")
    sh.set(r, Cc, "", s="td")
    sh.set(r, Ee, "", s="td")
    sh.set(r, F, "감면·공제를 받아도 법인세는 과세표준 × 이 비율 밑으로는 안 줄어듭니다 (중소기업).", s="note")
    r += 1
    sh.set(r, B, "감면·공제 금액", s="td")
    CRD = sh.set(r, Cc, TI["credit"], s="in")
    sh.set(r, Dd, "", s="td")
    sh.set(r, Ee, "", s="td")
    sh.set(r, F, "산출세액에서 빼는 감면·공제 (농어촌특별세 뺀 순액). 프로그램 법인세 예상과 같은 값 %s원." % "{:,}".format(TI["credit"]), s="note")
    r += 1
    sh.set(r, B, "세법 조정 (세무조정 등)", s="td")
    ADJ = sh.set(r, Cc, TI["adj"], s="in")
    sh.set(r, Dd, "", s="td")
    sh.set(r, Ee, "", s="td")
    sh.set(r, F, "세전 이익에 더해 과세표준을 만드는 금액 (접대비 한도 초과 등 세무조정 + 장부 분류 차이). 프로그램 법인세 예상의 과세표준과 맞춘 값.", s="note")
    r += 1
    sh.set(r, B, "지난해까지 영업외수익 세금 비율", s="td")
    R0 = sh.set(r, Dd, round(C["rate0"], 4), s="inp")
    sh.set(r, Cc, "", s="td")
    sh.set(r, Ee, "", s="td")
    sh.set(r, F, "지난해까지 영업외수익을 빼면 그때 낸 세금도 그만큼 덜 낸 것으로 봅니다: %s." % (" · ".join(C["how0"]) or "지난해 영업외수익 없음"), s="note")
    r += 1
    sh.set(r, B, "지난해까지 빼는 이익 (세금 뺀 뒤)", s="tdb")
    G0 = sh.set(r, Cc, f="%s-ROUND(%s*%s,0)" % (X0, X0, R0), s="numb")
    sh.set(r, Dd, "", s="td")
    sh.set(r, Ee, "", s="td")
    sh.set(r, F, "기획본부 기준 이익잉여금(지난해까지)이 이만큼 줄어듭니다.", s="note")
    r += 2

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

    # ② 손익 요약
    P = C["P"]
    sh.set(r, B, "2. 손익 요약 (%d년 1~%d월, 결산 비용 반영)" % (C["Y"], C["M"]), s="sec")
    for c in (Cc, Dd, Ee, F):
        sh.set(r, c, "", s="sec")
    r += 1
    for c, t in ((B, "항목"), (Cc, "회사 전체"), (Dd, "차이"), (Ee, "기획본부 기준"), (F, "설명")):
        sh.set(r, c, t, s="th")
    r += 1
    over_where = collections.defaultdict(list)
    for i, (nm, v, where, why) in enumerate(C["over"]):
        for w in ("판관비", "원가", "영업외비용", "법인세"):
            if w in where:
                over_where[w].append(_circ(i))

    def pl(label, val=None, f=None, fe=None, note="", bold=False, nstyle=None):
        """회사 전체 칸(val 또는 f), 기획본부 칸(fe, 없으면 같음), 차이 = 기획본부 − 회사 전체."""
        nonlocal r
        ns = nstyle or ("numb" if bold else "num")
        sh.set(r, B, label, s="tdb" if bold else "td")
        c_ = sh.set(r, Cc, val, f=f, s=ns)
        sh.set(r, Ee, None, f=fe or c_, s=ns)
        sh.set(r, Dd, None, f="%s-%s" % (xlsxw.addr(r, Ee), c_), s=ns)
        sh.set(r, F, note, s="note")
        r += 1
        return r - 1
    A_ = lambda row, col=Cc: xlsxw.addr(row, col)
    E_ = lambda row: xlsxw.addr(row, Ee)
    rv = pl("매출", P["rev"])
    cg = pl("매출원가", P["cogs"], note=_mark(over_where["원가"]))
    sg = pl("판매비와관리비 (장부)", P["sga"], note=_mark(over_where["판관비"]))
    kc = pl("결산 때 들어갈 비용", f=K, note="1번 표 '결산 때 들어갈 비용'에서 '예'로 둔 것 (감가상각·대손충당금·퇴직급여·상여금 등).")
    op = pl("영업이익", f="%s-%s-%s-%s" % (A_(rv), A_(cg), A_(sg), A_(kc)), fe="%s-%s-%s-%s" % (E_(rv), E_(cg), E_(sg), E_(kc)), bold=True,
            note="매출 − 매출원가 − 판관비 − 결산 비용.")
    ni = pl("영업외수익", f="SUM(%s)" % rng(Cc), fe="SUM(%s)-%s" % (rng(Cc), X1),
            note="이자수익·정부지원금·잡이익 등. 기획본부 기준에서는 1번 표에서 '예'로 둔 만큼 뺍니다.")
    no = pl("영업외비용", P["nout"], note="이자비용·잡손실 등. 빼지 않고 그대로 둡니다. " + _mark(over_where["영업외비용"]))
    pre = pl("세전 이익", f="%s+%s-%s" % (A_(op), A_(ni), A_(no)), fe="%s+%s-%s" % (E_(op), E_(ni), E_(no)), bold=True)
    bs = pl("과세표준", f="MAX(0,%s+%s)" % (A_(pre), ADJ), fe="MAX(0,%s+%s)" % (E_(pre), ADJ), note="세전 이익 + 세법 조정 (1번 표).")
    cp = pl("법인세 산출세액", f=corp_f(A_(bs)), fe=corp_f(E_(bs)), note="과세표준 × 1번 표 법인세율 (구간별).")
    nt = pl("법인세 (감면·최저한세 뒤)", f="IF(%s>0,MAX(%s-%s,INT(%s*%s)),%s)" % (CRD, A_(cp), CRD, A_(bs), MINR, A_(cp)),
            fe="IF(%s>0,MAX(%s-%s,INT(%s*%s)),%s)" % (CRD, E_(cp), CRD, E_(bs), MINR, E_(cp)),
            note="산출세액 − 감면·공제, 단 과세표준 × 최저한세율 밑으로는 안 줄어듦.")
    lc = pl("법인지방소득세", f="INT(%s*%s)" % (A_(cp), LOC), fe="INT(%s*%s)" % (E_(cp), LOC), note="산출세액 × 지방소득세율.")
    tx = pl("올해 법인세 예상 합계", f="%s+%s" % (A_(nt), A_(lc)), fe="%s+%s" % (E_(nt), E_(lc)), bold=True,
            note="프로그램 법인세 예상과 같은 계산 (기본값일 때). " + _mark(over_where["법인세"]))
    TAX, TAXE = A_(tx), E_(tx)
    tb = None
    if P["tax_booked"]:
        tb = pl("장부에 이미 넣은 법인세등", P["tax_booked"], note="올해 장부의 법인세등 계정. 위 예상과 겹칠 수 있으니 확인하세요.")
    net = pl("당기순이익 (예상)", f="%s-%s%s" % (A_(pre), A_(tx), ("-" + A_(tb)) if tb else ""),
             fe="%s-%s%s" % (E_(pre), E_(tx), ("-" + E_(tb)) if tb else ""), bold=True,
             note="세전 이익 − 법인세. 아래 재무상태표 '올해 이익'과 '올해 법인세 예상'을 더한 값과 같습니다.")
    r += 1

    # ③ 재무상태표
    sh.set(r, B, "3. 재무상태표 (%d년 %d월 말)" % (C["Y"], C["M"]), s="sec")
    for c in (Cc, Dd, Ee, F):
        sh.set(r, c, "", s="sec")
    r += 1
    for c, t in ((B, "항목"), (Cc, "회사 전체"), (Dd, "조정"), (Ee, "기획본부 기준"), (F, "설명")):
        sh.set(r, c, t, s="th")
    r += 1

    def line(label, val=None, f=None, adj=None, note="", style="td", nstyle="num"):
        nonlocal r
        sh.set(r, B, label, s=style)
        sh.set(r, Cc, val, f=f, s=nstyle)
        if adj:
            sh.set(r, Dd, f=adj, s=nstyle)
        else:
            sh.set(r, Dd, "", s=nstyle)
        sh.set(r, Ee, f="%s+%s" % (xlsxw.addr(r, Cc), xlsxw.addr(r, Dd)), s=nstyle)
        sh.set(r, F, note, s="note")
        r += 1
        return r - 1

    def group(title, items, extra=None):
        nonlocal r
        sh.set(r, B, title, s="grp")
        for c in (Cc, Dd, Ee, F):
            sh.set(r, c, "", s="grp")
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
        for c in (Cc, Dd, Ee):
            sh.set(r, c, f="SUM(%s:%s)" % (xlsxw.addr(first, c), xlsxw.addr(last, c)), s="numt")
        sh.set(r, F, "", s="note")
        r += 1
        return tot

    G = C["groups"]
    ca = group("유동자산", G["ca"], lambda: line("  영업외수익으로 들어온 돈 빼기", 0, adj="-(%s+%s)" % (X1, G0),
                                                  note="영업외수익으로 들어온 돈을 통장 돈에서 뺍니다. 올해 몫은 전부, 지난해 몫은 그 세금을 이미 냈으므로 세금 뺀 만큼."))

    def na_extra():
        line("  감가상각·대손충당금 (결산 예상, 자산 줄임)", f="-(%s)" % side_sum("asset"),
             note="1번 표의 감가상각비·대손충당금 중 '예'인 것. 장비 값과 받을 돈을 그만큼 줄여 봅니다.")
    na = group("비유동자산", G["na"] + ([("?", "종류를 모르는 계정 (확인 필요)", C["unknown"])] if C["unknown"] else []), na_extra)
    ta = r
    sh.set(r, B, "자산 총계", s="tdb")
    for c in (Cc, Dd, Ee):
        sh.set(r, c, f="%s+%s" % (xlsxw.addr(ca, c), xlsxw.addr(na, c)), s="numt")
    sh.set(r, F, "", s="note")
    r += 1
    def cl_extra():
        line("  올해 법인세 예상 (아직 장부에 없음)", f=TAX, adj="%s-%s" % (TAXE, TAX),
             note="결산 때 장부에 들어갈 올해 세금을 미리 빚으로 잡습니다. 기획본부 기준은 줄어드는 세금만큼 작습니다.")
        line("  결산 때 들어갈 비용 중 낼 돈 (퇴직급여·상여금·카드·4대보험, 예상)", f=side_sum("liab"),
             note="1번 표의 퇴직급여·상여금·카드값·4대보험 회사분 중 '예'인 것. 아직 안 낸 돈이라 빚으로 잡습니다.")
    cl = group("유동부채", G["cl"], cl_extra)
    nl = group("비유동부채", G["nl"])
    tl = r
    sh.set(r, B, "부채 총계", s="tdb")
    for c in (Cc, Dd, Ee):
        sh.set(r, c, f="%s+%s" % (xlsxw.addr(cl, c), xlsxw.addr(nl, c)), s="numt")
    sh.set(r, F, "", s="note")
    r += 1

    def eq_extra():
        line("  이익잉여금 (지난해까지 쌓인 이익)", C["retained"], adj="-%s" % G0,
             note="자산 − 부채 − 자본금 − 올해 이익으로 계산 (장부 결산 대체와 상관없이 맞음). 기획본부 기준은 지난해까지 영업외수익(세금 뺀 뒤)만큼 작습니다.%s"
             % (" %d년 전 이월 이익에 든 영업외수익은 장부에 없어 빼지 못했습니다." % C["first_year"]))
        line("  올해 이익 (세금 전)", f=xlsxw.addr(pre, Cc) + (("-" + xlsxw.addr(tb, Cc)) if tb else ""),
             adj="%s%s" % (xlsxw.addr(pre, Dd), ("-" + xlsxw.addr(tb, Dd)) if tb else ""),
             note="2번 표 세전 이익 (결산 비용 반영)%s. 기획본부 기준은 올해 영업외수익만큼 작습니다." % (" − 장부 법인세등" if tb else ""))
        line("  올해 법인세 예상", f="-" + TAX, adj="%s-%s" % (TAX, TAXE), note="부채의 '올해 법인세 예상'과 같은 금액. 기획본부 기준은 세금이 줄어든 만큼 덜 뺍니다.")
    eq = group("자본", C["capital"], eq_extra)
    tle = r
    sh.set(r, B, "부채와 자본 총계", s="tdb")
    for c in (Cc, Dd, Ee):
        sh.set(r, c, f="%s+%s" % (xlsxw.addr(tl, c), xlsxw.addr(eq, c)), s="numt")
    sh.set(r, F, "", s="note")
    r += 1
    sh.set(r, B, "맞춤 확인 (자산 총계 − 부채와 자본 총계)", s="td")
    for c in (Cc, Dd, Ee):
        sh.set(r, c, f="%s-%s" % (xlsxw.addr(ta, c), xlsxw.addr(tle, c)), s="ok")
    sh.set(r, F, "0이면 맞습니다. 0이 아니면 노란 칸 대신 계산식 칸을 고친 것이니 파일을 다시 만드세요.", s="note")
    chk = r
    r += 2

    # ④ 비용이 크게 잡혔을 수 있는 항목
    sh.set(r, B, "4. 기획본부가 알기 어려운, 비용이 크게 잡혔을 수 있는 항목", s="sec")
    for c in (Cc, Dd, Ee, F):
        sh.set(r, c, "", s="sec")
    r += 1
    for c, t in ((B, "항목"), (Cc, "올해 금액"), (Dd, "어디에 들었나"), (F, "왜 크게 보일 수 있나")):
        sh.set(r, c, t, s="th")
    sh.set(r, Ee, "", s="th")
    sh.merge(r, Dd, r, Ee)
    r += 1
    for i, (nm, v, where, why) in enumerate(C["over"]):
        sh.set(r, B, "%s %s" % (_circ(i), nm), s="td")
        sh.set(r, Cc, v, s="num")
        sh.set(r, Dd, where, s="td")
        sh.set(r, Ee, "", s="td")
        sh.merge(r, Dd, r, Ee)
        sh.set(r, F, why, s="note")
        r += 1
    if not C["over"]:
        sh.set(r, B, "올해 장부에 해당 항목 없음", s="td")
        r += 1
    sh.set(r, B, "이 항목들은 표에서 빼지 않았습니다 (회사 전체 비용 그대로). 숫자를 읽을 때 '이만큼은 기획본부가 직접 만든 비용이 아닐 수 있다'고 보세요.", s="txt")
    sh.merge(r, B, r, F)
    sh.heights[r] = 30
    r += 2

    # ⑤ 쓰는 법
    sh.set(r, B, "5. 쓰는 법", s="sec")
    for c in (Cc, Dd, Ee, F):
        sh.set(r, c, "", s="sec")
    r += 1
    for t in ("1. 어떤 영업외수익을 뺄지 1번 표 '뺄까요'에서 예/아니오를 고르면 손익·재무상태표가 바로 바뀝니다.",
              "2. 금액이나 세금 줄어드는 비율, 법인세 예상을 바꿔 '이렇게 되면 어떻게 되나'를 볼 수 있습니다. 원래 값은 1번 표 설명 칸에 있습니다.",
              "3. '조정' 칸 = 기획본부 기준 − 회사 전체. 맨 아래 '맞춤 확인'이 0이면 자산 = 부채 + 자본이 맞습니다.",
              "4. 회사 전체 칸은 위하고 분개장(계정 합계) 그대로입니다. 결산 때 들어갈 비용(감가상각 등)은 1번 표에서 기획본부 기준에만 넣습니다."):
        sh.set(r, B, t, s="txt")
        sh.merge(r, B, r, F)
        r += 1
    C["_cells"] = {"check": [xlsxw.addr(chk, c) for c in (Cc, Ee)], "net": (xlsxw.addr(net, Cc), xlsxw.addr(net, Ee)), "K": K, "tax": (TAX, TAXE),
                   "equity": (xlsxw.addr(eq, Cc), xlsxw.addr(eq, Ee)), "assets": (xlsxw.addr(ta, Cc), xlsxw.addr(ta, Ee))}
    return bk


def _circ(i):
    return "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"[i] if i < 15 else "(%d)" % (i + 1)


def _mark(items):
    return ("※ 아래 4번 표 %s 들어 있음" % "·".join(items)) if items else ""


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
