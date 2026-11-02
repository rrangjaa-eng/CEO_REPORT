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
}


class Data:
    pass


def _check(issues, row, col, value, allowed):
    if value not in allowed:
        issues.add(row["_file"], row["_line"], "%s 값 '%s'은(는) 허용 값이 아님 (%s)" % (col, value, "/".join(allowed)))
        return False
    return True


def load(folder):
    iss = Issues()
    d = Data()
    d.issues = iss
    d.present = {}
    raw = {}
    for fname, cols in SCHEMA.items():
        rows, ok = read_csv(os.path.join(folder, fname), cols, iss)
        raw[fname] = rows
        d.present[fname] = ok

    # 설정
    d.settings = dict(DEFAULT_SETTINGS)
    d.settings_line = {}  # 항목 → 줄 번호. 여기 없는 항목은 설정.csv에 행이 없는 것
    for r in raw["설정.csv"]:
        if r.get("항목"):
            d.settings[r["항목"]] = r.get("값", "")
            d.settings_line[r["항목"]] = r["_line"]

    # 계좌잔액
    d.balances = []
    for r in raw["계좌잔액.csv"]:
        b = {"date": date(r.get("기준일"), iss, r, "기준일"), "account": r.get("계좌명", ""), "bank": r.get("은행", ""),
             "balance": num(r.get("잔액"), iss, r, "잔액"), "restricted": num(r.get("사용제한금액"), iss, r, "사용제한금액"),
             "reason": r.get("제한사유", ""), "row": r}
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
        d.txns.append(t)

    # 자금일정 (프로젝트 밖 지급, 기타 입금)
    d.schedule = []
    for r in raw["자금일정.csv"]:
        s = {"date": date(r.get("예정일"), iss, r, "예정일"), "io": r.get("입출금", ""),
             "amount": num(r.get("금액"), iss, r, "금액"), "firm": r.get("확정여부", "") == "확정",
             "cat": r.get("분류", "") or "미분류", "project": r.get("프로젝트번호", ""), "vendor": r.get("거래처", ""),
             "basis": r.get("근거", ""), "memo": r.get("비고", ""), "source": "자금일정", "row": r}
        if not _check(iss, r, "입출금", s["io"], ["입금", "지급"]):
            continue
        _check(iss, r, "확정여부", r.get("확정여부", ""), ["확정", "추정"])
        if s["amount"] is None:
            iss.add(r["_file"], r["_line"], "금액 미확인 → 일정 합계에서 제외, 건수만 표시")
        d.schedule.append(s)

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
            "budget": num(r.get("사전견적예산"), iss, r, "사전견적예산"),
            "budget_date": date(r.get("예산수정일"), iss, r, "예산수정일"),
            "contract": num(r.get("계약금액"), iss, r, "계약금액"),
            "recognized": num(r.get("매출반영누계"), iss, r, "매출반영누계"),
            "event_date": r.get("행사일", ""),
            "done_date": date(r.get("완료일"), iss, r, "완료일"), "row": r}
        d.project_order.append(pid)

    # 프로젝트집행
    d.execs = []
    for r in raw["프로젝트집행.csv"]:
        e = {"project": r.get("프로젝트번호", ""), "item": r.get("항목", ""), "vendor": r.get("거래처", ""),
             "state": r.get("상태", ""), "supply": num(r.get("공급가액"), iss, r, "공급가액"),
             "vat": num(r.get("부가세"), iss, r, "부가세"), "date": date(r.get("일자"), iss, r, "일자"),
             "firm": r.get("확정여부", "") == "확정", "basis": r.get("근거", ""), "row": r}
        if not _check(iss, r, "상태", e["state"], EXEC_STATES):
            continue
        if e["project"] not in d.projects:
            iss.add(r["_file"], r["_line"], "프로젝트번호 '%s'가 프로젝트.csv에 없음 (프로젝트 미연결로 집계)" % e["project"])
        if e["state"] == "집행계획미요청" and not e["basis"]:
            iss.add(r["_file"], r["_line"], "집행계획미요청 줄에 근거(계약·발주·집행계획) 없음")
        d.execs.append(e)

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
