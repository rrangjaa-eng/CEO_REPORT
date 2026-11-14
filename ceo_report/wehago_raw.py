"""위하고 결산·인사·연말정산 화면 원본 읽기 (사용자 2026-11-13: 확장 0.8.2 가 수집\\위하고 에 자동 저장).

파일 이름: 'YYMMDD <종류>_<화면>[_연도] 자동수집.json'. 최상위 키: 종류, 형식, 수집시각, 연도, 화면, 화면코드, 자동, 응답수, 응답.
응답 = [{path, data}]. 같은 화면·연도 파일이 여럿이면 수집시각이 가장 늦은 것을 쓴다.

자료 변환 때 만드는 파일 (입력 폴더):
  사원.csv      인사_사원등록: 사원명, 생년월일(주민번호 앞 6자리+성별 자리로), 입사일, 퇴사일, 임원, 부서
  급여명세.csv   인사_월별급상여수당지급현황(올해·작년): 사원별 달별 지급 합계·공제 합계 (항목별 명세는 이 화면에 없음)
               + 인사_소득자별근로소득원천징수부: 사원별 달별 소득세·지방소득세 (공제 합계 안에 든 몫, 환급 예상용)
  연말정산.csv   연말정산_연말정산현황: 사원별 총급여·공제 인원·공제 금액·결정세액
  고정자산.csv   결산_고정자산관리대장: 자산별 취득일·취득가·상각률·전기말 누계·당기 상각 예정
개인정보: 주민번호는 생년월일로만 바꾸고 성별·뒷자리는 저장하지 않는다. 전화·메일·주소·계좌는 원본에도 없음.
"""
import datetime as dt
import json
import os
import re

from .payroll import YE_COLUMNS

EMP_COLUMNS = ["사원명", "생년월일", "입사일", "퇴사일", "고용형태", "주소정근로시간", "임원", "부양가족수", "자녀수", "부서", "사번", "직급"]
PAY_COLUMNS = ["연월", "사원명", "구분", "항목", "금액"]
ASSET_FILE = "고정자산.csv"
ASSET_COLUMNS = ["기준연도", "자산", "계정", "취득일", "취득가", "상각률", "전기말상각누계", "당기상각", "당기말상각누계"]
OFFICER_WORDS = ("대표", "이사", "감사", "회장", "사장", "전무", "상무")   # 직급·직책 이름에 들어가면 임원
TOTAL_PAY, TOTAL_DED = "지급합계", "공제합계"   # 월별 급상여 화면은 사원별 합계만 준다
WH_TAX, WH_LOCAL = "소득세(공제합계 안)", "지방소득세(공제합계 안)"   # 원천징수부에서 — 공제합계에 이미 들어 있음


def _num(v):
    try:
        return int(float(str(v).replace(",", "").strip() or 0))
    except (TypeError, ValueError):
        return 0


def _date(t):
    t = re.sub(r"\D", "", str(t or ""))
    if len(t) != 8:
        return ""
    try:
        return dt.date(int(t[:4]), int(t[4:6]), int(t[6:])).isoformat()
    except ValueError:
        return ""


def birth_from_social(no):
    """'YYMMDD-G' -> 'YYYY-MM-DD' (G 1·2·5·6 = 1900년대, 3·4·7·8 = 2000년대, 9·0 = 1800년대). 모르면 ''."""
    m = re.match(r"\s*(\d{2})(\d{2})(\d{2})-?(\d)", str(no or ""))
    if not m:
        return ""
    yy, mm, dd, g = m.groups()
    century = {"1": 1900, "2": 1900, "5": 1900, "6": 1900, "3": 2000, "4": 2000, "7": 2000, "8": 2000, "9": 1800, "0": 1800}[g]
    try:
        return dt.date(century + int(yy), int(mm), int(dd)).isoformat()
    except ValueError:
        return ""


YEARLESS = ("인사_사원등록",)


def files(wehago_dir):
    """-> {(종류_화면, 연도): (수집시각, 경로, dict)} 화면·연도마다 가장 늦게 받은 것."""
    out = {}
    try:
        names = os.listdir(wehago_dir)
    except (OSError, TypeError):
        return out
    for n in names:
        if not n.endswith("자동수집.json") or "분개장" in n or "자금계획" in n:
            continue
        path = os.path.join(wehago_dir, n)
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or "응답" not in d:
            continue
        kind = (d.get("종류") or "").replace("원본", "")
        screen = "%s_%s" % (kind, d.get("화면") or "")
        try:
            year = int(str(d.get("연도") or 0).strip()[:4] or 0)
        except ValueError:
            year = 0
        # 연도가 없는 파일('지금 열린 화면' 수동 저장)은 어느 해 자료인지 몰라 쓰지 않는다 (2026-11-14 코덱스 검토: 급여가 '0-01'
        # 같은 달로, 고정자산이 0년으로 들어갔음). 사원등록은 해가 상관없어 그대로 쓴다. '모두 받기(자동)'는 연도를 적는다
        if year < 2000 and screen not in YEARLESS:
            continue
        key = (screen, year)
        stamp = str(d.get("수집시각") or "") + n
        if key not in out or out[key][0] < stamp:
            out[key] = (stamp, path, d)
    return out


def _resp(d, tail):
    for r in d.get("응답") or []:
        if str(r.get("path") or "").rstrip("/").endswith(tail.rstrip("/")):
            return r.get("data")
    return None


def _pick(F, screen, year=None):
    """화면 이름으로 (연도, dict) 목록, 연도 내림차순."""
    got = [(y, v[2]) for (s, y), v in F.items() if s == screen and (year is None or y == year)]
    return sorted(got, key=lambda t: -t[0])


def employees(F):
    """인사_사원등록(직급 rank·직책 position 표로 이름을 이음) + 월별 급상여 화면 info(직책) -> 사원.csv 줄."""
    got = _pick(F, "인사_사원등록")
    if not got:
        return []
    data = _resp(got[0][1], "/condition") or {}
    officers = set()
    for _, d in _pick(F, "인사_월별급상여수당지급현황"):
        for i in _resp(d, "/info") or []:
            if any(w in str(i.get("nm_offpos") or "") for w in OFFICER_WORDS):
                officers.add(str(i.get("cd_emp") or ""))
    wh_emps = _withholding(F)[0]   # 원천징수부 사원 목록: 공제대상 가족 수 (배우자·자녀·60세 이상)
    names = dict((x.get("position_rank_no"), str(x.get("position_rank_name") or ""))
                 for x in (data.get("rank") or []) + (data.get("position") or []))   # 직급(rank)·직책(position) 번호 → 이름
    rows = []
    for e in data.get("emp") or []:
        name = str(e.get("nm_krname") or "").strip()
        if not name:
            continue
        code = str(e.get("cd_emp") or "")
        titles = [names.get(e.get(k)) or "" for k in ("rank_no", "position_rank_no")]
        if any(w in t for t in titles for w in OFFICER_WORDS):
            officers.add(code)
        w = wh_emps.get(code) or {}
        deps = sum(_num(w.get(k)) for k in ("num_wife", "num_childs", "num_60over")) if w else None
        rows.append({"사원명": name, "생년월일": birth_from_social(e.get("no_social")), "입사일": _date(e.get("da_enter")),
                     "퇴사일": _date(e.get("da_retire")), "고용형태": "", "주소정근로시간": "",
                     "임원": "예" if code in officers else "", "부양가족수": "" if deps is None else str(deps),
                     "자녀수": str(_num(w.get("num_childs"))) if w else "",
                     "부서": str(e.get("nm_dept") or ""), "사번": code, "직급": " ".join(t for t in titles if t)})
    return rows


def pay_rows(F):
    """월별 급상여 화면(연도마다) -> 급여명세.csv 줄 (지급합계·공제합계)."""
    rows = []
    for year, d in sorted(_pick(F, "인사_월별급상여수당지급현황"), key=lambda t: t[0]):
        for r in _resp(d, "/total") or []:
            name = str(r.get("nm_krname") or "").strip()
            if not name or (r.get("cd_code") and r.get("cd_emp") and r["cd_code"] != r["cd_emp"]):
                continue   # 사원별 합계 줄만 (cd_code = cd_emp)
            for m in range(1, 13):
                ym = "%d-%02d" % (year, m)
                ji, gong = _num(r.get("mon_%02d_ji" % m)), _num(r.get("mon_%02d_gong" % m))
                if ji:
                    rows.append({"연월": ym, "사원명": name, "구분": "지급", "항목": TOTAL_PAY, "금액": str(ji)})
                if gong:
                    rows.append({"연월": ym, "사원명": name, "구분": "공제", "항목": TOTAL_DED, "금액": str(gong)})
    # 원천징수부의 사원별 소득세·지방소득세 (공제합계 안에 들어 있는 몫 — 따로 적어 환급 예상에 씀)
    emps, wh = _withholding(F)
    names = dict((c, str(e.get("nm_krname") or "").strip()) for c, e in emps.items())
    for e in (_resp(_pick(F, "인사_사원등록")[0][1], "/condition") or {}).get("emp", []) if _pick(F, "인사_사원등록") else []:
        names.setdefault(str(e.get("cd_emp") or ""), str(e.get("nm_krname") or "").strip())
    for _, code, ym, inc, loc in wh:
        if not names.get(code):
            continue
        if inc:
            rows.append({"연월": ym, "사원명": names[code], "구분": "공제", "항목": WH_TAX, "금액": str(inc)})
        if loc:
            rows.append({"연월": ym, "사원명": names[code], "구분": "공제", "항목": WH_LOCAL, "금액": str(loc)})
    return rows


def _find(x, key, depth=0):
    """dict/list 안에서 key 를 처음 찾는 값 (응답 감싸기가 조금 달라도 읽게)."""
    if depth > 4:
        return None
    if isinstance(x, dict):
        if key in x:
            return x[key]
        for v in x.values():
            got = _find(v, key, depth + 1)
            if got is not None:
                return got
    elif isinstance(x, list):
        for v in x[:3]:
            got = _find(v, key, depth + 1)
            if got is not None:
                return got
    return None


def _withholding(F):
    """인사_소득자별근로소득원천징수부 (확장 0.8.3) -> ({사번: 사원 dict}, [(연도, 사번, 연월, 소득세, 지방소득세)])."""
    emps, out = {}, []
    for year, d in _pick(F, "인사_소득자별근로소득원천징수부"):
        seen = set()
        for r in d.get("응답") or []:
            path = str(r.get("path") or "").rstrip("/")
            data = r.get("data")
            # 같은 내용의 응답이 두 번 저장되기도 한다 (실제 2026-11-14: 첫 사원 소득 응답이 두 번 → 원천세가 매달 부풀려짐)
            # 사번은 응답 안 값을 먼저 본다 (밖의 사번이 잘못 붙은 중복도 같은 것으로), 없으면 밖의 사번 (다른 사원이 금액만 같은 경우는 남김)
            key = (path, str(_find(data, "cd_emp") or r.get("cd_emp") or ""),
                   json.dumps(data, sort_keys=True, ensure_ascii=False, default=str))
            if key in seen:
                continue
            seen.add(key)
            if path.endswith("/emp"):
                for e in data if isinstance(data, list) else (_find(data, "data") or []):
                    if isinstance(e, dict) and e.get("cd_emp"):
                        emps.setdefault(str(e["cd_emp"]), e)   # 최근 해 것이 먼저 온다: 작년 값으로 덮지 않음 (코덱스 검토)
            elif path.endswith("/emp/income"):
                code = r.get("cd_emp") or _find(data, "cd_emp")
                rows = _find(data, "group1") or []
                for g in rows if isinstance(rows, list) else []:
                    ym = re.sub(r"\D", "", str(g.get("ym_rvrs") or g.get("ym_pay") or ""))
                    if len(ym) != 6 or not code:
                        continue
                    out.append((year, str(code), "%s-%s" % (ym[:4], ym[4:]), _num(g.get("am_income1")), _num(g.get("am_inhabit1"))))
    return emps, out


def _child_count(amount):
    if amount <= 0:
        return 0
    if amount <= 250_000:
        return 1
    if amount <= 550_000:
        return 2
    return 2 + int(round((amount - 550_000) / 400_000.0))


def yearend_rows(F):
    """연말정산현황 -> 연말정산.csv 줄.

    위하고 칸: am_totpay 총급여, am_mydedt·am_wifededt·am_famdedt 본인·배우자·부양가족 기본공제(1명 150만),
    am_oldfamdedt 경로우대(100만), am_womandedt 부녀자(50만), am_childsdedt 자녀세액공제, am_adopt 출산입양,
    sum_specdedt 특별소득공제(건강·고용보험료 premium 포함 — 보험료는 올해 급여로 따로 계산하므로 뺌), am_etcdedt 그 밖의 소득공제, am_calctax 산출세액, am_unempincom 근로소득세액공제,
    am_deciincom 결정세액. 특별세액공제 등(보험료·의료비·교육비·기부금·월세 등 mn_* 칸) = 산출 − 결정 − 근로소득세액공제 − 자녀
    (2025 실제 자료로 mn_* 합과 같음 확인. am_incomtax 중소기업 취업자 감면 등도 여기에 들어감 — 올해도 이어진다고 봄). 장애인·한부모는 이 화면에 칸이 없어 0."""
    rows = []
    for year, d in _pick(F, "연말정산_연말정산현황"):
        data = (d.get("응답") or [{}])[0].get("data") or []
        for r in data if isinstance(data, list) else []:
            name = str(r.get("nm_krname") or "").strip()
            if not name:
                continue
            basic = (_num(r.get("am_mydedt")) + _num(r.get("am_wifededt")) + _num(r.get("am_famdedt"))) // 1_500_000
            child = _num(r.get("am_childsdedt"))
            credit = max(_num(r.get("am_calctax")) - _num(r.get("am_deciincom")) - _num(r.get("am_unempincom")) - child, 0)
            v = {"귀속연도": str(year), "사원명": name, "총급여": _num(r.get("am_totpay")), "기본공제인원": basic,
                 "경로우대": _num(r.get("am_oldfamdedt")) // 1_000_000, "장애인": 0, "부녀자": 1 if _num(r.get("am_womandedt")) else 0,
                 "한부모": 0, "자녀세액공제인원": _child_count(child), "출산입양": 1 if _num(r.get("am_adopt")) else 0,
                 "특별소득공제": max(_num(r.get("sum_specdedt")) - _num(r.get("premium")), 0), "그밖소득공제": _num(r.get("am_etcdedt")),
                 "특별세액공제": credit, "연금계좌세액공제": 0, "월세세액공제": 0, "결정세액": _num(r.get("am_deciincom"))}
            rows.append(dict((k, str(v[k])) for k in YE_COLUMNS))
    return rows


def asset_rows(F):
    rows = []
    for year, d in _pick(F, "결산_고정자산관리대장")[:1]:
        for a in _resp(d, "/allfixlist") or []:
            if not a.get("cd_fixast"):
                continue   # 소계 줄
            start = _num(a.get("mn_ftdepsum"))
            cur = _num(a.get("mn_ctdepre1"))
            rows.append({"기준연도": str(year), "자산": str(a.get("nm_fixast") or "").strip(), "계정": str(a.get("nm_acctit") or ""),
                         "취득일": _date(a.get("da_acquire")), "취득가": str(_num(a.get("mn_base")) + _num(a.get("mn_new"))),
                         "상각률": str(a.get("rt_depre") or ""), "전기말상각누계": str(start), "당기상각": str(cur),
                         "당기말상각누계": str(_num(a.get("mn_ctdepsum")))})
    return rows


def closing(F):
    """결산 화면 -> {연도: {"차기이월": n, "당기순이익": n, "미처분": n, "자본금": n, "이익준비금": n, "차입금": n, "자산총계": n,
    "부채총계": n}}. 처분계산서는 화면 기간(g_date)의 끝 연도, 재무상태표는 파일 연도 기준."""
    out = {}

    def put(y, k, v):
        out.setdefault(y, {})[k] = v
    for _, d in _pick(F, "결산_이익잉여금처분계산서"):
        for r in d.get("응답") or []:
            data = r.get("data") or {}
            gd = (data.get("g_date") or [{}])[0]
            try:
                y = int(gd.get("da_tdatey"))
            except (TypeError, ValueError):
                continue
            vals = {}
            sect = ""
            for g in data.get("g_list") or []:
                nm = re.sub(r"\s+", "", str(g.get("nm_sq") or ""))
                if g.get("ty_depth") == "1":
                    sect = nm
                v = _num(g.get("mn_cal")) or _num(g.get("mn_sq"))
                if "차기이월" in nm:
                    vals["차기이월"] = v
                elif nm.startswith("Ⅰ.미처분"):
                    vals["미처분"] = v
                elif "당기순이익" in nm and "미처분" in sect:
                    vals["당기순이익"] = v
            if any(vals.values()):
                for k, v in vals.items():
                    put(y, "처분_" + k, v)
    for y, d in _pick(F, "결산_재무상태표"):
        data = _resp(d, "/main") or {}
        for r in data.get("main") or []:
            code, nm = str(r.get("cd_acctit") or "").strip(), re.sub(r"\s+", "", str(r.get("nm_acctit") or ""))
            v = _num(r.get("mn_bungae_right") or r.get("mn_bungae"))
            if code == "33100":
                put(y, "자본금", v)
            elif code == "37700" or "미처분이익잉여금" in nm:
                put(y, "미처분잔액", v)
            elif "이익준비금" in nm:
                put(y, "이익준비금", v)
            elif "차입금" in nm and code:
                out.setdefault(y, {})["차입금"] = out.get(y, {}).get("차입금", 0) + v
            elif nm in ("자산총계", "부채총계", "자본총계"):
                put(y, nm, v)
    return out


def build_tables(wehago_dir):
    """자료 변환에 붙는 표 (원본이 없으면 '만들지 않음' — 기존 파일 그대로)."""
    from .convert import Table
    from .payroll import EMP_FILE, PAY_FILE, YE_FILE
    F = files(wehago_dir)
    out = []
    for name, cols, rows, what in ((EMP_FILE, EMP_COLUMNS, employees(F), "인사_사원등록"),
                                   (PAY_FILE, PAY_COLUMNS, pay_rows(F), "인사_월별급상여수당지급현황"),
                                   (YE_FILE, YE_COLUMNS, yearend_rows(F), "연말정산_연말정산현황"),
                                   (ASSET_FILE, ASSET_COLUMNS, asset_rows(F), "결산_고정자산관리대장")):
        if rows:
            out.append(Table(name, cols, rows, notes=["위하고 %s 원본으로 %d줄" % (what, len(rows))]))
        else:
            out.append(Table(name, cols, [], written=False, reason="위하고 %s 원본 없음 (기존 파일 그대로)" % what))
    return out
