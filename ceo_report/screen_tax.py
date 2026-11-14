"""위하고 급여·원천징수 화면과 장부 원천세·4대보험 대조 (제안 3-②③④, 2026-11-14 사용자 '정합성 제안 전부').

화면 (확장 '결산·인사급여·연말정산 모두 받기'가 수집\\위하고 에 저장, 칸 이름은 11/14 PC 실제 파일로 확인):
  근로: 인사_소득자별근로소득원천징수부 …/emp/income → group1 의 ym_rvrs·am_income1(소득세)·am_inhabit1(지방소득세)
        (같은 사원 응답이 두 번 들어간 파일이 있어 사원·달마다 한 번만 센다)
  사업: 인사_사업소득조회 /smarta/swbu0103/tab1 → data.tab1_up 의 ym_pay·am_income·am_inhabit (합계 줄 tab1_down 은 안 씀)
  기타: 인사_기타소득조회 /smarta/swet0107/other/tab01 → data.data 의 ym_pay·am_income·am_inhabit (am_soduk 은 소득금액이라 안 씀)
  4대보험 직원분: 인사_월별급상여수당지급현황 사원별 공제합계 − 그 달 근로 소득세·지방소득세 (그 밖 공제가 있으면 그만큼 큼)
개인정보: 사원 이름·번호는 세지 않고 달별 합계만 쓴다.
"""
import re

from . import wehago_raw as WR

KINDS = ("근로", "사업", "기타")
GAP_WARN = 100000   # 달마다 이만큼 넘게 다르면 확인할 것


def _ym(v):
    t = re.sub(r"\D", "", str(v or ""))
    return (int(t[:4]), int(t[4:6])) if len(t) >= 6 else None


def _rows(data, key):
    got = WR._find(data, key) if isinstance(data, (dict, list)) else None
    return [r for r in got if isinstance(r, dict)] if isinstance(got, list) else []


def income_tax(F):
    """-> {(연, 월): {"근로": 원, "사업": 원, "기타": 원}} 소득세+지방소득세 (근로는 귀속월, 사업·기타는 지급월)."""
    out = {}

    def add(ym, kind, v):
        if ym and v:
            out.setdefault(ym, dict((k, 0) for k in KINDS))[kind] += v
    seen = set()
    for _, d in WR._pick(F, "인사_소득자별근로소득원천징수부"):
        for r in d.get("응답") or []:
            if not str(r.get("path") or "").rstrip("/").endswith("/emp/income"):
                continue
            data = r.get("data")
            code = r.get("cd_emp") or WR._find(data, "cd_emp")
            for g in _rows(data, "group1"):
                ym = _ym(g.get("ym_rvrs") or g.get("ym_pay"))
                key = (str(code), ym)
                if not code or ym is None or key in seen:
                    continue
                seen.add(key)
                add(ym, "근로", WR._num(g.get("am_income1")) + WR._num(g.get("am_inhabit1")))
    for screen, tail, key, kind in (("인사_사업소득조회", "/swbu0103/tab1", "tab1_up", "사업"),
                                    ("인사_기타소득조회", "/swet0107/other/tab01", "data", "기타")):
        got = WR._pick(F, screen)
        years = set()
        for year, d in got:   # 올해·작년 파일: 같은 해를 두 번 세지 않는다 (해마다 가장 늦게 받은 것만 — WR.files 가 이미 고름)
            if year in years:
                continue
            years.add(year)
            data = WR._resp(d, tail)
            for r in _rows(data, key):
                add(_ym(r.get("ym_pay") or r.get("ym_rvrs")), kind, WR._num(r.get("am_income")) + WR._num(r.get("am_inhabit")))
    return out


def employee_insurance(F, wage_tax):
    """-> {(연, 월): 4대보험 직원분 추정} = 사원 공제합계 합 − 그 달 근로 소득세·지방소득세."""
    ded = {}
    for year, d in WR._pick(F, "인사_월별급상여수당지급현황"):
        for r in WR._resp(d, "/total") or []:
            if not str(r.get("nm_krname") or "").strip() or (r.get("cd_code") and r.get("cd_emp") and r["cd_code"] != r["cd_emp"]):
                continue
            for m in range(1, 13):
                v = WR._num(r.get("mon_%02d_gong" % m))
                if v:
                    ded[(year, m)] = ded.get((year, m), 0) + v
    return dict((k, v - (wage_tax.get(k) or {}).get("근로", 0)) for k, v in ded.items())


def _book(journal, codes, vendors):
    codes = set(re.sub(r"\s+", "", str(c)) for c in codes)
    out = {}
    for ln in journal or []:
        if ln.get("date") is None or re.sub(r"\s+", "", str(ln.get("account_code") or "")) not in codes:
            continue
        if not any(v in re.sub(r"\s+", "", str(ln.get("vendor") or "")) for v in vendors):
            continue
        k = (ln["date"].year, ln["date"].month)
        out[k] = out.get(k, 0) + (ln.get("credit") or 0)
    return out


def compare(journal, F, asof, wh_codes=("25400",), wh_vendors=("세무서", "구청", "시청", "군청"),
            ins_vendors=("국민연금", "건강보험", "근로복지", "고용보험")):
    """올해 1월~기준일 달, 장부 예수금 대변(원천세·4대보험) ↔ 화면. -> (notes, 원천세 화면 달별 합 {(연,월): 원})."""
    tax = income_tax(F)
    if not tax:
        return [], {}
    totals = dict((k, sum(v.values())) for k, v in tax.items())
    book_wh = _book(journal, wh_codes, wh_vendors)
    book_ins = _book(journal, wh_codes, ins_vendors)
    ins = employee_insurance(F, tax)
    months = [(asof.year, m) for m in range(1, asof.month + 1)]
    gaps, igaps = [], []
    for ym in months:
        if ym in totals and ym in book_wh and abs(book_wh[ym] - totals[ym]) > GAP_WARN:
            gaps.append("%d월 장부 %s · 화면 %s (근로 %s·사업 %s·기타 %s)" % (
                ym[1], "{:,}".format(book_wh[ym]), "{:,}".format(totals[ym]),
                *("{:,}".format(tax[ym][k]) for k in KINDS)))
        if ym in ins and ym in book_ins and abs(book_ins[ym] - ins[ym]) > GAP_WARN:
            igaps.append("%d월 장부 %s · 화면 %s" % (ym[1], "{:,}".format(book_ins[ym]), "{:,}".format(ins[ym])))
    have = [ym for ym in months if ym in totals and ym in book_wh]
    sb = sum(book_wh[k] for k in have)
    sw = sum(totals[k] for k in have)
    notes = ["원천세 장부↔위하고 화면(근로 원천징수부+사업소득+기타소득) %d년 %d개월: 장부 %s · 화면 %s (차이 %s)"
             % (asof.year, len(have), "{:,}".format(sb), "{:,}".format(sw), "{:+,}".format(sb - sw))]
    if gaps:
        notes.append("[확인] 원천세 장부·위하고 화면이 10만 원 넘게 다른 달: %s — 연말정산 정산분·퇴직소득세·지급월 차이인지 확인"
                     % " / ".join(gaps))
    if igaps:
        notes.append("[확인] 4대보험 직원분 장부·위하고 급여 화면(공제합계−소득세·지방소득세)이 10만 원 넘게 다른 달: %s"
                     " — 화면 쪽에 다른 공제(가불 등)가 있으면 그만큼 큼" % " / ".join(igaps))
    return notes, totals
