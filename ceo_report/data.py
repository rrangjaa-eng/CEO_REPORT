import datetime as dt
"""입력 폴더의 CSV를 읽어 정리된 자료로 만든다."""
import os

from .util import Issues, read_csv, num, date

# 파일 이름 → 필수 열. 입력양식 폴더의 빈 양식도 이 목록으로 만든다.
SCHEMA = {
    "설정.csv": ["항목", "값"],
    "계좌잔액.csv": ["기준일", "계좌명", "은행", "잔액", "사용제한금액", "제한사유"],
    "입출금내역.csv": ["일자", "계좌명", "입출금", "금액", "분류", "프로젝트번호", "거래처", "적요"],
    "자금일정.csv": ["예정일", "입출금", "금액", "확정여부", "분류", "프로젝트번호", "거래처", "근거", "비고"],
    "프로젝트.csv": ["프로젝트번호", "프로젝트명", "팀", "클라이언트", "상태", "사전견적예산", "예산수정일",
                   "계약금액", "매출반영누계", "행사일", "완료일"],
    "프로젝트집행.csv": ["프로젝트번호", "항목", "거래처", "상태", "공급가액", "부가세", "일자", "확정여부", "근거"],
    "계산서.csv": ["프로젝트번호", "거래처", "발행일", "구분", "공급가액", "부가세", "입금예정일", "예정일확정",
                "입금일", "입금액"],
    "손익.csv": ["출처", "연월", "단위", "대상", "매출", "직접비", "공통비", "잠정"],
    "지급계획.csv": ["주시작일", "프로젝트번호", "거래처", "계획금액"],
    "변경내역.csv": ["변경일", "항목", "대상", "변경전", "변경후", "사유"],
    "자료기준일.csv": ["자료", "기준일", "비고"],
    "자료차이.csv": ["항목", "자료A", "금액A", "자료B", "금액B", "상태"],
}

# 변환.py 가 자금계획서(지출입금현황)에서 만드는 선택 파일 (D-55). 없으면 기존 일정만 쓴다. SCHEMA 에 넣지 않는다 (빈 양식 없음).
FUNDPLAN_FILE = "자금계획.csv"
FUNDPLAN_KEYS = ["예정일", "입출금", "거래처", "금액", "대상월", "자료일", "상태"]

# 변환.py 가 분개장 관리항목(부서명·사원명)에서 만드는 선택 파일 (사용자 2026-11-03). 없으면 팀 순수익은 '미확인'.
DEPT_FILE = "부서비용.csv"
DEPT_KEYS = ["연월", "부서", "급여", "판관비", "인원"]
ACCOUNT_FILE = "계정별비용.csv"   # 계정과목별 달별 사용 금액 (사용자 2026-11-03: 월간 연간표)
ACCOUNT_KEYS = ["연월", "구분", "계정코드", "계정과목", "금액"]
# 증빙(세금계산서 등) 작성일자 기준 달별 매출·매입 공급가액 (사용자 2026-11-04: 월간 2쪽 흐름 그림 막대)
EVID_FILE = "증빙월별.csv"
EVID_KEYS = ["연월", "매출", "매입"]
DEPT_OPTIONAL = ["영업외수익", "영업외비용"]   # 없는 예전 파일은 '미확인' (사용자 2026-11-03: 정부지원금 등은 팀에 넣지 않고 따로)
NO_DEPT = "부서 없음"
# 사원별 달별 급여 (분개장 급여 줄의 관리항목 사원명, 사용자 2026-11-04: 1인당 순이익을 본인 급여 비율로 나눔). 경영관리용에만 씀
STAFF_FILE = "사원급여.csv"
STAFF_KEYS = ["연월", "부서", "사원명", "급여"]

# 변환.py 가 분개장 보통예금으로 만드는 계좌 잔액·입출금 (사용자 2026-11-04: 분개장 합계 = 실제 통장 합계).
# 있으면 계좌잔액.csv 는 사용제한(담보·전용 등)만 쓰고, 입출금내역.csv 대신 장부입출금.csv 를 쓴다.
BOOK_BAL_FILE = "장부잔액.csv"
BOOK_BAL_KEYS = ["기준일", "계좌명", "은행", "잔액"]
BOOK_TXN_FILE = "장부입출금.csv"

# 변환.py 가 분개장으로 만드는 세금 납부 예상 (사용자 2026-11-03). 없으면 세금 예상은 일정에 넣지 않는다.
TAX_FILE = "세금예상.csv"
TAX_KEYS = ["세목", "대상기간", "납부예정일", "금액", "상태"]

# 지급 일정의 출처 파일과, 없으면 지급 금액·날짜를 알 수 없는 열. 이 파일이 없거나 이 열이 없으면
# 지급예정이 빠진 채 최저 잔액이 계산되므로 계산하지 않는다 (지급을 줄이지 않음).
OUTFLOW_KEYS = {
    "자금일정.csv": ["예정일", "입출금", "금액"],
    "프로젝트집행.csv": ["상태", "공급가액", "일자"],  # 부가세 열이 없으면 기존처럼 부가세 미확인(공급가액만)으로 알린다
}

# 수금(발행 후 미수·발행금액·입금예정)의 출처 파일과, 없으면 그 금액·날짜를 알 수 없는 열. 이 파일이 없거나 이 열이 없으면
# 발행 후 미수·발행금액·미발행금액·입금예정을 0이 아니라 '자료 없음'으로 두고 계산서 입금을 일정에 넣지 않는다.
# 입금액이 없으면 전부 미수로 보여 입금예정이 부풀려지고, 프로젝트번호가 없으면 프로젝트별 발행금액이 모두 0이 된다.
INFLOW_KEYS = {
    "계산서.csv": ["프로젝트번호", "공급가액", "부가세", "입금예정일", "입금액"],
}

# 허용 값
EXEC_STATES = ["지급완료", "요청미지급", "카드사용미결제", "카드결제완료", "집행계획미요청"]
INVOICE_KINDS = ["발행", "선수금", "수정", "취소", "환불"]
TRANSFER = "계좌간이체"

DEFAULT_SETTINGS = {
    "회사명": "회사명",
    "첫화면_프로젝트_표시수": "10",
    "위험_최소보유현금": "50000000",
    "위험_미수경과일": "30",
    "위험_미발행경과일": "30",
    "위험_자료경과일": "7",
    "위험_예산초과율": "100",
    "예산_원가율": "0.70",
}


class Data:
    pass


def _check(issues, row, col, value, allowed):
    if value not in allowed:
        issues.add(row["_file"], row["_line"], "%s 값 '%s'은(는) 허용 값이 아님 (%s)" % (col, value, "/".join(allowed)))
        return False
    return True


def _outflow(iss, row, col, value):
    """지급(출금) 금액이 음수·괄호면 절댓값을 쓰고 입력 확인 목록에 남긴다: 지급을 입금으로 바꾸지 않는다 (지급을 줄이지 않음)."""
    if value is not None and value < 0:
        iss.add(row["_file"], row["_line"], "%s 값이 음수: '%s' → 지급 금액 %s원으로 처리 (지급을 줄이지 않음)"
                % (col, row.get(col, ""), "{:,}".format(-value)))
        return -value
    return value


def _unusable(folder, fname, ok, lost):
    """핵심 자료 파일을 쓸 수 없는 이유 ('자금일정.csv (파일 없음)' 꼴). 쓸 수 있으면 None."""
    if not os.path.exists(os.path.join(folder, fname)):
        return "%s (파일 없음)" % fname
    if not ok:
        return "%s (읽지 못함)" % fname
    if lost:
        return "%s (필수 열 없음: %s)" % (fname, ", ".join(lost))
    return None


def load(folder):
    iss = Issues()
    d = Data()
    d.issues = iss
    d.present = {}
    d.out_missing = []  # 지급 일정을 다 알 수 없게 만드는 파일: '자금일정.csv (파일 없음)' 꼴
    d.in_missing = []  # 수금(계산서) 금액·입금예정을 알 수 없게 만드는 파일: '계산서.csv (파일 없음)' 꼴
    raw = {}
    for fname, cols in SCHEMA.items():
        info = {}
        rows, ok = read_csv(os.path.join(folder, fname), cols, iss, info)
        raw[fname] = rows
        d.present[fname] = ok
        for keys, missing in ((OUTFLOW_KEYS, d.out_missing), (INFLOW_KEYS, d.in_missing)):
            if fname in keys:
                why = _unusable(folder, fname, ok, [c for c in keys[fname] if c in info["missing"]])
                if why:
                    missing.append(why)

    # 설정
    d.settings = dict(DEFAULT_SETTINGS)
    d.settings_line = {}  # 항목 → 줄 번호. 여기 없는 항목은 설정.csv에 행이 없는 것
    for r in raw["설정.csv"]:
        if r.get("항목"):
            d.settings[r["항목"]] = r.get("값", "")
            d.settings_line[r["항목"]] = r["_line"]

    # 장부잔액·장부입출금 (변환.py, 사용자 2026-11-04): 있으면 잔액·입출금은 분개장 보통예금, 계좌잔액.csv 는 사용제한만
    d.book_bank = False
    bpath, tpath = os.path.join(folder, BOOK_BAL_FILE), os.path.join(folder, BOOK_TXN_FILE)
    if os.path.exists(bpath) and os.path.exists(tpath):
        brows, bok = read_csv(bpath, BOOK_BAL_KEYS, iss, {})
        trows, tok = read_csv(tpath, SCHEMA["입출금내역.csv"], iss, {})
        if bok and tok and brows:
            d.book_bank = True
            for r in raw["계좌잔액.csv"]:
                if (r.get("잔액") or "").strip():
                    iss.add(r["_file"], r["_line"], "잔액은 분개장 보통예금(장부잔액.csv)으로 계산 → 이 줄은 사용제한만 씀")
                r["잔액"] = "0"
                r["계좌명"] = "사용제한: " + (r.get("계좌명") or r.get("제한사유") or "")
            if raw["입출금내역.csv"]:
                iss.add("입출금내역.csv", "-", "입출금은 분개장 보통예금(장부입출금.csv)으로 계산 → 이 파일은 쓰지 않음")
            raw["계좌잔액.csv"] = brows + raw["계좌잔액.csv"]
            raw["입출금내역.csv"] = trows
            d.present["계좌잔액.csv"] = d.present["입출금내역.csv"] = True

    # 계좌잔액
    d.balances = []
    for r in raw["계좌잔액.csv"]:
        b = {"date": date(r.get("기준일"), iss, r, "기준일"), "account": r.get("계좌명", ""), "bank": r.get("은행", ""),
             "balance": num(r.get("잔액"), iss, r, "잔액"), "restricted": num(r.get("사용제한금액"), iss, r, "사용제한금액"),
             "reason": r.get("제한사유", ""), "row": r,
             # 제한해제일 (선택 칸, 사용자 2026-11-03): 정기예금 만기일 등. 그날부터 쓸 수 있는 돈으로 자금 일정에 들어간다
             "release": date(r.get("제한해제일"), iss, r, "제한해제일") if (r.get("제한해제일") or "").strip() else None}
        if b["date"] is None:
            iss.add(r["_file"], r["_line"], "기준일 없음 → 제외")
            continue
        d.balances.append(b)

    # 입출금내역
    d.txns = []
    for r in raw["입출금내역.csv"]:
        t = {"date": date(r.get("일자"), iss, r, "일자"), "account": r.get("계좌명", ""), "io": r.get("입출금", ""),
             "amount": num(r.get("금액"), iss, r, "금액"), "cat": r.get("분류", "") or "미분류",
             "project": r.get("프로젝트번호", ""), "vendor": r.get("거래처", ""), "memo": r.get("적요", ""), "row": r}
        if not _check(iss, r, "입출금", t["io"], ["입금", "출금"]) or t["date"] is None or t["amount"] is None:
            iss.add(r["_file"], r["_line"], "일자·입출금·금액 중 확인 불가 → 합계에서 제외")
            continue
        if t["io"] == "출금":
            t["amount"] = _outflow(iss, r, "금액", t["amount"])
        d.txns.append(t)

    # 자금일정 (프로젝트 밖 지급, 기타 입금)
    d.schedule = []
    for r in raw["자금일정.csv"]:
        io = r.get("입출금", "")
        s = {"date": date(r.get("예정일"), iss, r, "예정일"), "io": "지급" if io == "출금" else io,  # '출금'도 지급으로 읽는다
             "amount": num(r.get("금액"), iss, r, "금액"), "firm": r.get("확정여부", "") == "확정",
             "cat": r.get("분류", "") or "미분류", "project": r.get("프로젝트번호", ""), "vendor": r.get("거래처", ""),
             "basis": r.get("근거", ""), "memo": r.get("비고", ""), "source": "자금일정", "row": r}
        if not _check(iss, r, "입출금", s["io"], ["입금", "지급"]):
            continue
        if s["io"] == "지급":
            s["amount"] = _outflow(iss, r, "금액", s["amount"])
        _check(iss, r, "확정여부", r.get("확정여부", ""), ["확정", "추정"])
        if s["amount"] is None:
            iss.add(r["_file"], r["_line"], "금액 미확인 → 일정 합계에서 제외, 건수만 표시")
        d.schedule.append(s)

    # 자금계획 (선택, D-55): 읽지 못한 줄이 하나라도 있으면 통째로 쓰지 않는다 (틀린 일정으로 기존 일정을 지우지 않음)
    d.fundplan, d.fundplan_problem = None, ""
    path = os.path.join(folder, FUNDPLAN_FILE)
    if os.path.exists(path):
        info = {}
        rows, ok = read_csv(path, FUNDPLAN_KEYS, iss, info)
        if not ok or info["missing"]:
            d.fundplan_problem = "읽지 못함" if not ok else "필수 열 없음: " + ", ".join(info["missing"])
        else:
            d.fundplan, bad = [], 0
            for r in rows:
                f = {"date": date(r.get("예정일"), iss, r, "예정일"), "io": r.get("입출금", ""), "cat": r.get("분류", ""),
                     "vendor": r.get("거래처", ""), "vendor_code": (r.get("거래처코드") or "").strip(),
                     "amount": num(r.get("금액"), iss, r, "금액"), "ym": r.get("대상월", ""),
                     "stamp": date(r.get("자료일"), iss, r, "자료일"), "state": r.get("상태", "") or "예정",
                     "basis": r.get("근거", ""), "file": r.get("파일", ""), "row": r}
                if f["date"] is None or f["amount"] is None or f["stamp"] is None or f["io"] not in ("지급", "입금"):
                    iss.add(r["_file"], r["_line"], "예정일·입출금·금액·자료일 중 확인 불가 → 자금계획 전체를 쓰지 않음")
                    bad += 1
                d.fundplan.append(f)
            if bad:
                d.fundplan, d.fundplan_problem = None, "확인 못한 줄 %d개" % bad

    # 부서비용 (선택, 사용자 2026-11-03): 읽지 못하면 통째로 쓰지 않는다. 금액·인원 빈칸은 None (모름)
    d.dept, d.dept_problem = None, ""
    path = os.path.join(folder, DEPT_FILE)
    if os.path.exists(path):
        info = {}
        rows, ok = read_csv(path, DEPT_KEYS, iss, info)
        if not ok or info["missing"]:
            d.dept_problem = "읽지 못함" if not ok else "필수 열 없음: " + ", ".join(info["missing"])
        else:
            d.dept = [{"ym": (r.get("연월") or "").strip(), "dept": (r.get("부서") or "").strip(),
                       "salary": num(r.get("급여"), iss, r, "급여"), "sga": num(r.get("판관비"), iss, r, "판관비"),
                       "heads": num(r.get("인원"), iss, r, "인원"),
                       "nonop_in": num(r.get("영업외수익"), iss, r, "영업외수익") if "영업외수익" in r else None,
                       "nonop_out": num(r.get("영업외비용"), iss, r, "영업외비용") if "영업외비용" in r else None,
                       "has_nonop": "영업외수익" in r and "영업외비용" in r} for r in rows]

    # 사원별 급여 (선택, 사용자 2026-11-04): 읽지 못하면 쓰지 않는다. 급여 빈칸은 None (모름)
    d.staff = None
    path = os.path.join(folder, STAFF_FILE)
    if os.path.exists(path):
        info = {}
        rows, ok = read_csv(path, STAFF_KEYS, iss, info)
        if ok and not info["missing"]:
            d.staff = [{"ym": (r.get("연월") or "").strip(), "dept": (r.get("부서") or "").strip(),
                        "name": (r.get("사원명") or "").strip(), "salary": num(r.get("급여"), iss, r, "급여")} for r in rows]

    # 증빙 작성일자 기준 달별 매출·매입 (선택). 빈칸은 None (모름)
    d.evid_month = None
    path = os.path.join(folder, EVID_FILE)
    if os.path.exists(path):
        info = {}
        rows, ok = read_csv(path, EVID_KEYS, iss, info)
        if ok and not info["missing"]:
            d.evid_month = dict(((r.get("연월") or "").strip(), (num(r.get("매출"), iss, r, "매출"), num(r.get("매입"), iss, r, "매입")))
                                for r in rows if (r.get("연월") or "").strip())

    # 계정과목별 달별 사용 금액 (선택). 금액 빈칸은 None (모름)
    d.accounts, d.accounts_problem = None, ""
    path = os.path.join(folder, ACCOUNT_FILE)
    if os.path.exists(path):
        info = {}
        rows, ok = read_csv(path, ACCOUNT_KEYS, iss, info)
        if not ok or info["missing"]:
            d.accounts_problem = "읽지 못함" if not ok else "필수 열 없음: " + ", ".join(info["missing"])
        else:
            d.accounts = [{"ym": (r.get("연월") or "").strip(), "group": (r.get("구분") or "").strip(),
                           "code": (r.get("계정코드") or "").strip(), "name": (r.get("계정과목") or "").strip(),
                           "amount": num(r.get("금액"), iss, r, "금액")} for r in rows]

    # 출금 상세 내역 (선택, 사용자 2026-11-03): 창에서 손으로 넣거나 인트라넷 지출결의서에서 가져옴
    from .paydetail import read as read_details
    d.pay_details = read_details(folder)
    from .targets import read as read_targets   # 팀별 연간 목표 (사용자 2026-11-03)
    d.team_targets = read_targets(folder)
    from .corptax import read as read_dep   # 연간 감가상각비 직접 입력 (사용자 2026-11-04: 법인세 예상)
    d.dep_manual = read_dep(folder)

    # 세금 예상 (선택): 날짜를 못 읽은 줄은 넣지 않고 입력 확인에 남긴다
    d.tax = None
    path = os.path.join(folder, TAX_FILE)
    if os.path.exists(path):
        info = {}
        rows, ok = read_csv(path, TAX_KEYS, iss, info)
        if ok and not info["missing"]:
            d.tax = []
            for r in rows:
                blank = not (r.get("납부예정일") or "").strip()   # 카드 결제일 모름 등: 날짜 없이 알리기만 한다
                due = None if blank else date(r.get("납부예정일"), iss, r, "납부예정일")
                if due is None and not blank:
                    continue
                d.tax.append({"kind": r.get("세목", ""), "period": r.get("대상기간", ""), "due": due,
                              "amount": num(r.get("금액"), iss, r, "금액"), "state": r.get("상태", "") or "예상",
                              "basis": r.get("근거", ""),
                              # 법인세 줄만 (2026-11-04): 과세표준·산출세액·기납부(중간예납 등 선납세금)
                              "base": num(r.get("과세표준"), iss, r, "과세표준") if (r.get("과세표준") or "").strip() else None,
                              "calc": num(r.get("산출세액"), iss, r, "산출세액") if (r.get("산출세액") or "").strip() else None,
                              "prepaid": num(r.get("기납부"), iss, r, "기납부") if (r.get("기납부") or "").strip() else None})

    # 장부 채무 (변환.py 장부채무.csv, 2026-11-04 점검 A1·A2): 없으면 None
    from .debts import load as load_debts
    d.debts = load_debts(folder, iss)
    # 분개장 정기예금 (사용자 2026-11-04): 계좌 합계에 넣고 같은 금액을 만기일까지 쓸 수 없는 돈으로 뺀다. 만기일에 들어올 돈.
    # 계좌잔액.csv 에 정기예금을 손으로 적은 줄이 있으면 겹치지 않게 장부 정기예금은 넣지 않는다.
    manual_dep = any("정기예금" in "%s %s" % (b["account"], b["reason"]) for b in d.balances)
    for k, x in enumerate([x for x in (d.debts or []) if x["kind"] == "정기예금" and x["balance"]]):
        row = {"_file": "장부채무.csv", "_line": "정기예금 %d" % (k + 1)}
        if x["balance"] < 0:
            iss.add(row["_file"], row["_line"], "정기예금 %s 이 올해 %s원 줄었는데 분개장에 전기이월이 없어 남은 금액을 모름 → 계좌잔액.csv 확인"
                    % (x["vendor"] or x["account"], "{:,}".format(-x["balance"])))
            continue
        if manual_dep:
            iss.add(row["_file"], row["_line"], "계좌잔액.csv 에 정기예금 줄이 있어 장부 정기예금 %s원은 넣지 않음" % "{:,}".format(x["balance"]))
            continue
        due = None
        if x["due"]:
            try:
                due = dt.date(*[int(v) for v in x["due"].split("-")])
            except ValueError:
                due = None
        if due is None:
            iss.add(row["_file"], row["_line"], "정기예금 %s 만기일을 분개장 적요에서 찾지 못함 → 만기일 확인 필요 (쓸 수 없는 돈으로만 둠)"
                    % (x["vendor"] or x["account"]))
        try:
            bdate = dt.date(*[int(v) for v in x["date"].split("-")])
        except ValueError:
            continue
        d.balances.append({"date": bdate, "account": "정기예금 " + (x["vendor"] or x["account"]), "bank": x["vendor"],
                           "balance": x["balance"], "restricted": x["balance"],
                           "reason": "정기예금 (만기 %s%s)" % (due.isoformat() if due else "확인 필요",
                                                           " 추정" if due and "추정" in x.get("due_basis", "") else ""), "row": row, "release": due})

    # 프로젝트
    d.projects = {}
    d.project_order = []
    for r in raw["프로젝트.csv"]:
        pid = r.get("프로젝트번호", "")
        if not pid:
            iss.add(r["_file"], r["_line"], "프로젝트번호 없음 → 제외")
            continue
        if pid in d.projects:
            iss.add(r["_file"], r["_line"], "프로젝트번호 %s 중복 → 뒤의 줄은 제외" % pid)
            continue
        d.projects[pid] = {
            "id": pid, "name": r.get("프로젝트명", ""), "team": r.get("팀", "") or "팀 미지정",
            "client": r.get("클라이언트", ""), "state": r.get("상태", ""),
            "estimate": num(r.get("사전견적예산"), iss, r, "사전견적예산"),
            "estimate_raw": r.get("사전견적예산", ""),
            "budget_date": date(r.get("예산수정일"), iss, r, "예산수정일"),
            "contract": num(r.get("계약금액"), iss, r, "계약금액"),
            "recognized": num(r.get("매출반영누계"), iss, r, "매출반영누계"),
            "event_date": r.get("행사일", ""),
            "done_date": date(r.get("완료일"), iss, r, "완료일"), "row": r}
        d.project_order.append(pid)

    # 프로젝트집행
    d.execs = []
    blank_project = []
    for r in raw["프로젝트집행.csv"]:
        e = {"project": r.get("프로젝트번호", ""), "item": r.get("항목", ""), "vendor": r.get("거래처", ""),
             "state": r.get("상태", ""), "supply": num(r.get("공급가액"), iss, r, "공급가액"),
             "vat": num(r.get("부가세"), iss, r, "부가세"), "date": date(r.get("일자"), iss, r, "일자"),
             "firm": r.get("확정여부", "") == "확정", "basis": r.get("근거", ""), "row": r}
        if e["state"] not in EXEC_STATES:
            # 상태를 모르는 줄도 지급이다: 버리지 않고 지급 전(요청미지급)으로 일정에 넣어 현금을 많게 보이지 않는다
            iss.add(r["_file"], r["_line"], "상태 값 '%s'은(는) 허용 값이 아님 (%s) → 지급 전(요청미지급)으로 보고 지급 일정에 넣음"
                    % (e["state"], "/".join(EXEC_STATES)))
            e["state"] = "요청미지급"
        from . import calc   # 순환 import 를 피해 여기서
        if calc.INTRANET_IN_FUNDS or not str(e["basis"]).startswith("지급요청"):
            # 인트라넷 지급요청 줄은 비교로만 쓰므로 취소·수정(음수) 금액을 그대로 둔다 (2026-11-04 '비교만')
            e["supply"] = _outflow(iss, r, "공급가액", e["supply"])
            e["vat"] = _outflow(iss, r, "부가세", e["vat"])
        if not str(e["project"]).strip():
            blank_project.append(r)   # 줄마다 알리지 않고 아래에서 한 줄로 (실제 자료 2천 줄 넘음, 2026-11-04)
        elif e["project"] not in d.projects:
            iss.add(r["_file"], r["_line"], "프로젝트번호 '%s'가 프로젝트.csv에 없음 (프로젝트 미연결로 집계)" % e["project"])
        if e["state"] == "집행계획미요청" and not e["basis"]:
            iss.add(r["_file"], r["_line"], "집행계획미요청 줄에 근거(계약·발주·집행계획) 없음")
        d.execs.append(e)
    if blank_project:
        iss.add(blank_project[0]["_file"], "-", "프로젝트번호 빈칸 줄 %d건 → 프로젝트 미연결로 집계 (어느 줄인지는 변환결과.txt [연결])"
                % len(blank_project))

    # 계산서
    d.invoices = []
    for r in raw["계산서.csv"]:
        v = {"project": r.get("프로젝트번호", ""), "client": r.get("거래처", ""),
             "date": date(r.get("발행일"), iss, r, "발행일"), "kind": r.get("구분", "") or "발행",
             "supply": num(r.get("공급가액"), iss, r, "공급가액"), "vat": num(r.get("부가세"), iss, r, "부가세"),
             "due": date(r.get("입금예정일"), iss, r, "입금예정일"), "due_firm": r.get("예정일확정", "") in ("Y", "확정"),
             "paid_date": date(r.get("입금일"), iss, r, "입금일"), "paid": num(r.get("입금액"), iss, r, "입금액"),
             "row": r}
        if not _check(iss, r, "구분", v["kind"], INVOICE_KINDS):
            continue
        if v["project"] and v["project"] not in d.projects:
            iss.add(r["_file"], r["_line"], "프로젝트번호 '%s'가 프로젝트.csv에 없음" % v["project"])
        d.invoices.append(v)

    # 손익
    d.pl = []
    for r in raw["손익.csv"]:
        p = {"source": r.get("출처", ""), "ym": r.get("연월", "").replace(".", "-").replace("/", "-")[:7],
             "unit": r.get("단위", ""), "target": r.get("대상", ""),
             "revenue": num(r.get("매출"), iss, r, "매출"), "direct": num(r.get("직접비"), iss, r, "직접비"),
             "common": num(r.get("공통비"), iss, r, "공통비"), "provisional": r.get("잠정", "") in ("Y", "잠정"),
             "row": r}
        _check(iss, r, "단위", p["unit"], ["회사", "팀", "프로젝트"])
        d.pl.append(p)

    # 지급계획
    d.plans = []
    for r in raw["지급계획.csv"]:
        d.plans.append({"week": date(r.get("주시작일"), iss, r, "주시작일"), "project": r.get("프로젝트번호", ""),
                        "vendor": r.get("거래처", ""), "amount": num(r.get("계획금액"), iss, r, "계획금액"), "row": r})

    d.changes = []
    for r in raw["변경내역.csv"]:
        d.changes.append({"date": date(r.get("변경일"), iss, r, "변경일"), "field": r.get("항목", ""),
                          "target": r.get("대상", ""), "before": r.get("변경전", ""), "after": r.get("변경후", ""),
                          "reason": r.get("사유", "")})

    d.asof = []
    for r in raw["자료기준일.csv"]:
        d.asof.append({"name": r.get("자료", ""), "date": date(r.get("기준일"), iss, r, "기준일"), "memo": r.get("비고", "")})

    d.diffs = []
    for r in raw["자료차이.csv"]:
        d.diffs.append({"item": r.get("항목", ""), "a": r.get("자료A", ""), "a_amt": num(r.get("금액A"), iss, r, "금액A"),
                        "b": r.get("자료B", ""), "b_amt": num(r.get("금액B"), iss, r, "금액B"), "state": r.get("상태", "")})
    return d
