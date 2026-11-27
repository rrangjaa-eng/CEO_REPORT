"""묶음 D: 자료 규칙 (실제 WEHAGO 자료에서 배운 것) 사례. 모두 가상 자료.

각 사례는 기본 가상 회사(build.base_books)에서 규칙에 필요한 것만 바꾼다.
"""
import datetime as dt

from build import case, base_books, write_json, plan_doc, plan_row, BASE_PLAN  # noqa: F401


def _jl(day, no, code, account, debit, credit, vendor, memo, vcode=""):
    from test_wehago import _jl as jl
    return jl(day, no, code, account, debit, credit, vendor, memo, vcode)


def journal_doc(journal, sorts=None, start="20260101", end="20261031", sq=None, project=None):
    """확장 분개장 JSON. sorts: {전표번호: '매출전표'|'매입전표'} (나머지는 일반전표), sq: {줄 순번(0부터): sq_acttax2},
    project: {줄 순번: 프로젝트 칸}."""
    from test_journal_json import auto_json
    doc = auto_json(journal, start=start, end=end)
    doc["회사"] = "(샘플) 플랜트에이트"
    for i, row in enumerate(doc["줄"]):
        no = int(row[1])
        if sorts and no in sorts:
            row[2] = sorts[no]
        if sq and i in sq:
            row[15] = sq[i]
        if project and i in project:
            row[11] = project[i]
    return doc


def write_journal(wehago_dir, journal, name="261031 분개장 자동수집.json", **kw):
    write_json(wehago_dir, name, journal_doc(journal, **kw))


def base_plan(wehago_dir, rows=None, name="261101 자금계획 자동수집.json"):
    write_json(wehago_dir, name, plan_doc(BASE_PLAN if rows is None else rows, ["202610", "202611", "202612"],
                                          "20261001", "20261231", "2026-11-01 09:00:00"))


# 분개장 매입·매출 전표 (D-57): 매입 1~8 은 매입전표, 매출 30·31·32 는 매출전표로 적힌 분개장
PURCHASE_SLIPS = dict((n, "매입전표") for n in range(1, 9))


def sales_sorts(*nos):
    out = dict(PURCHASE_SLIPS)
    out.update((n, "매출전표") for n in nos)
    return out


def pl_journal(drop_slips=(), extra=()):
    from test_convert import FAKE_PL_JOURNAL
    return [r for r in FAKE_PL_JOURNAL if r[1] not in drop_slips] + list(extra)


# ───────────── D1 나눈 계산서 ─────────────
@case
def case_d_split_invoice(input_dir, collect, wehago_dir):
    """가상고객D 8,250만 계산서(전표 31)의 매출 줄을 26203 4,500만 + 26201 3,000만으로 나눔 → 계산서.csv 두 줄
    (부가세 450만·300만), 자금계획 입금 8,250만 한 줄과는 다시 합쳐 맞춤."""
    d = dt.date(2026, 10, 27)
    memo = "가상 전시부스 잔금"
    split = [
        _jl(d, 31, "10800", "수입수수료미수금", 82500000, None, "가상고객D", memo),
        _jl(d, 31, "41200", "수입수수료", None, 45000000, "가상고객D", "[26203] " + memo),
        _jl(d, 31, "41200", "수입수수료", None, 30000000, "가상고객D", "[26201] 가상 컨퍼런스 추가"),
        _jl(d, 31, "25500", "부가세예수금", None, 7500000, "가상고객D", memo),
    ]
    jr = pl_journal(drop_slips=(31,), extra=split)
    base_books(input_dir, collect, wehago_dir, journal=jr)
    write_journal(wehago_dir, jr, sorts=sales_sorts(30, 31, 32))
    base_plan(wehago_dir)
    return {"title": "한 계산서를 두 프로젝트로 나눔: 공급가 비례로 두 줄, 자금계획 입금과는 합쳐 맞춤", "rules": ["D1"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── D2·D3 거래처코드 ─────────────
BOOKS_1101 = {"journal_stamp": "261101", "journal_end": "20261101"}


def restamp(wehago_dir, old="20261031", new="20261101"):
    """매입매출장·전자세금계산서 엑셀 이름의 날짜를 바꾼다 (장부 기준일 = 원천 파일 날짜 중 가장 이른 날)."""
    import os
    for n in os.listdir(wehago_dir):
        if n.endswith("_%s.xlsx" % old):
            os.rename(os.path.join(wehago_dir, n), os.path.join(wehago_dir, n.replace(old, new)))


def _code_plan():
    """기본 자금계획에서 (주)가상음향 줄만 거래처코드 [000101] 로 (위하고 자금계획서 꼴)."""
    rows = [list(r) for r in BASE_PLAN]
    rows[1][4] = "000101"
    return rows


def _paid_to_sound(vcode):
    """11/1 (주)가상음향에 4,400만 지급 전표 (미지급금 차변·보통예금 대변, 분개장 거래처Code = vcode).
    자동수집 자금계획은 받은 날(11/1) 뒤 전표만 보므로 분개장도 11/1 까지 받은 것으로 한다."""
    d = dt.date(2026, 11, 1)
    return [_jl(d, 40, "25300", "미지급금", 44000000, None, "(주)가상음향", "가상 컨퍼런스 음향 지급", vcode),
            _jl(d, 40, "10300", "보통예금", None, 44000000, "(주)가상음향", "가상 컨퍼런스 음향 지급", vcode)]


@case
def case_d_code_zeros(input_dir, collect, wehago_dir):
    """자금계획서 거래처코드 [000101] 과 분개장 거래처Code 00101 은 앞 0 을 떼면 같은 거래처 → 11/13 지급 계획이 '이미 지급'."""
    jr = pl_journal(extra=_paid_to_sound("00101"))
    base_books(input_dir, collect, wehago_dir, journal=jr, **BOOKS_1101)
    restamp(wehago_dir)
    base_plan(wehago_dir, _code_plan())
    return {"title": "거래처코드 앞자리 0 무시: 자금계획 [000101] = 분개장 00101 → 이미 지급", "rules": ["D3"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


@case
def case_d_same_name_other_code(input_dir, collect, wehago_dir):
    """이름은 같은 (주)가상음향인데 분개장 지급 줄 코드가 00102 → 자금계획 [000101] 줄은 '예정' 그대로 (다른 지급).
    매출채권도 가상고객A 가 코드 00201(계산서)·00202(입금) 두 개 → 이름 같고 코드 다른 거래처 경고."""
    jr = []
    for r in pl_journal(extra=_paid_to_sound("00102")):
        r = list(r)
        if r[1] in (30, 33) and r[3] == "10800":
            r[8] = "00201" if r[1] == 30 else "00202"
        jr.append(r)
    base_books(input_dir, collect, wehago_dir, journal=jr, **BOOKS_1101)
    restamp(wehago_dir)
    base_plan(wehago_dir, _code_plan())
    return {"title": "같은 이름 다른 거래처코드: 다른 거래처로 보고 지급을 맞추지 않음(경고)", "rules": ["D2"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── D4 지난해 프로젝트 ─────────────
@case
def case_d_prior_year(input_dir, collect, wehago_dir):
    """옛 번호 [093](5자리 미만) 원가 줄과 2025년 분개장의 원가 줄은 지난해 프로젝트 → 프로젝트집행.csv 근거 '참고(지난해 프로젝트)'.
    같은 달 [26201] 줄은 그대로 26201 에 연결 (견줄 짝)."""
    extra = [
        _jl(dt.date(2026, 3, 10), 41, "61101", "행사외주비(도)", 2000000, None, "가상옛업체", "[093] 가상 옛 행사 잔금"),
        _jl(dt.date(2026, 3, 10), 41, "10300", "보통예금", None, 2000000, "가상옛업체", "[093] 가상 옛 행사 잔금"),
        _jl(dt.date(2026, 3, 11), 42, "61101", "행사외주비(도)", 1500000, None, "가상답사", "[26201] 가상 컨퍼런스 사전답사"),
        _jl(dt.date(2026, 3, 11), 42, "10300", "보통예금", None, 1500000, "가상답사", "[26201] 가상 컨퍼런스 사전답사"),
    ]
    jr = pl_journal(extra=extra)
    base_books(input_dir, collect, wehago_dir, journal=jr)
    y25 = [
        _jl(dt.date(2025, 12, 15), 9, "61101", "행사외주비(도)", 3000000, None, "가상작년업체", "가상 작년 송년행사 외주"),
        _jl(dt.date(2025, 12, 15), 9, "25300", "미지급금", None, 3000000, "가상작년업체", "가상 작년 송년행사 외주"),
    ]
    write_journal(wehago_dir, y25, name="261031 분개장_2025 자동수집.json", start="20250101", end="20251231")
    base_plan(wehago_dir)
    return {"title": "옛 번호 [093]·2025년 원가 줄은 지난해 프로젝트(참고)로만", "rules": ["D4"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── D5·D15 예전 인트라넷 ─────────────
OLD_PROJ_HEAD = ["내부번호", "", "번호", "클라이언트", "행사일 ▲", "행사명", "국", "팀", "등록자", "발행일", "계산서", "사전견적",
                 "견적금액", "실행가", "수익율", "커미션", "할인", "담당자", "관리팀", "대표이사", "견적", "삭제", "개인정보"]


def old_intranet(collect, rows, year="2026"):
    """수집/예전인트라넷/old_projects_<해>.csv (예전 인트라넷 완료보고서 목록, 가상). rows: (코드, 행사명, 행사일, 사전견적, 실행가)."""
    import csv
    import os
    d = os.path.join(collect, "예전인트라넷")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "old_projects_%s.csv" % year), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(OLD_PROJ_HEAD)
        for i, (code, name, day, est, bud) in enumerate(rows):
            w.writerow([str(i + 1), "", str(i + 1), "가상옛고객", day, "[%s] %s" % (code, name), "본부", "기획1팀", "가상직원",
                        "2026-01-01", "0", est, "0", bud, "10.00%", "0", "Quotation 완료보고", "승인완료", "승인완료",
                        "승인완료", "페이먼트보기", "", ""])


@case
def case_d_old_intranet_done(input_dir, collect, wehago_dir):
    """예전 인트라넷 프로젝트: 행사일 2026-02-03(3/31 이전) [093] 은 상태 '완료(예전 인트라넷)', 2026-05-02 [26001] 은 상태 빈칸."""
    base_books(input_dir, collect, wehago_dir)
    base_plan(wehago_dir)
    old_intranet(collect, [("093", "가상 옛 봄행사", "2026-02-01~2026-02-03", "3,000,000", "2,100,000"),
                           ("26001", "가상 옛 여름행사", "2026-05-01~2026-05-02", "4,000,000", "2,800,000")])
    return {"title": "예전 인트라넷 프로젝트는 2026-03-31까지 행사면 완료로 봄", "rules": ["D5"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


@case
def case_d_old_intranet_cost(input_dir, collect, wehago_dir):
    """예전 인트라넷 [26037](실행가 900만)은 올해 장부 [26037] 원가 줄이 있어 '장부 원가 0원' 확인 항목이 없고,
    원가 줄이 없는 [26038] 만 '작년원가0' 항목으로 나옴."""
    extra = [_jl(dt.date(2026, 3, 20), 43, "61101", "행사외주비(도)", 9000000, None, "가상옛외주", "[26037] 가상 옛 신년행사 외주"),
             _jl(dt.date(2026, 3, 20), 43, "10300", "보통예금", None, 9000000, "가상옛외주", "[26037] 가상 옛 신년행사 외주")]
    base_books(input_dir, collect, wehago_dir, journal=pl_journal(extra=extra))
    base_plan(wehago_dir)
    old_intranet(collect, [("26037", "가상 옛 신년행사", "2026-03-19~2026-03-20", "12,000,000", "9,000,000"),
                           ("26038", "가상 옛 설행사", "2026-02-09~2026-02-10", "1,500,000", "1,000,000")])
    return {"title": "예전 인트라넷 프로젝트의 '장부 원가 0원' 오탐 없음: 올해 장부에 이어진 원가도 원가", "rules": ["D15"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── D6 분개장 중복 줄 (sq_acttax2) ─────────────
@case
def case_d_journal_line_id(input_dir, collect, wehago_dir):
    """10/28 임차료 300만 전표(21)를 위하고에서 11/1 로 고친 뒤 11월만 다시 받음 (줄 번호 sq_acttax2 같음).
    예전 파일(1/1~10/31)의 10/28 줄은 날짜가 달라도 빼고 11/1 줄 한 번만 → 임차료 10월 0 · 11월 300만 (두 번 세면 600만)."""
    from test_convert import FAKE_PL_JOURNAL
    base_books(input_dir, collect, wehago_dir)
    restamp(wehago_dir, new="20261102")
    full = journal_doc(FAKE_PL_JOURNAL)
    moved = [list(r) for r in full["줄"] if r[1] == "00021"]
    for r in moved:
        r[0], r[1], r[10] = "20261101", "00001", "10월 임차료 (날짜 고침)"
    # 수집시각이 예전 파일과 같으면 어느 것이 '나중 파일'인지 폴더 읽는 순서에 따라 바뀜 → 한 시간 뒤로 둠
    new = dict(full, 수집시각="2026-11-05 11:00:00",
               기간={"start_date": "20261101", "end_date": "20261102", "gisu": "2"}, 줄=moved, 줄수=len(moved), 전표수=1)
    write_json(wehago_dir, "261102 분개장 자동수집.json", new)
    base_plan(wehago_dir)
    return {"title": "분개장 중복 줄: 줄 번호(sq_acttax2)가 같으면 날짜를 고쳐 다시 받아도 한 번만", "rules": ["D6"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── D7 받다 만 분개장 JSON ─────────────
@case
def case_d_partial_journal(input_dir, collect, wehago_dir):
    """더 새 분개장 자동수집(261101, 1/1~11/1)의 '줄수'가 실제 줄보다 2 많음 (받다 만 파일) → 그 파일은 쓰지 않음.
    지금 프로그램은 예전 파일로 돌아가지 않고 변환 전체를 멈춤 (코드 3, 장부로 만드는 CSV 를 쓰지 않음)."""
    from test_convert import FAKE_PL_JOURNAL
    base_books(input_dir, collect, wehago_dir)
    extra = [_jl(dt.date(2026, 11, 1), 50, "81300", "접대비(판)", 5000000, None, "가상식당", "받다 만 파일의 줄"),
             _jl(dt.date(2026, 11, 1), 50, "10300", "보통예금", None, 5000000, "가상식당", "받다 만 파일의 줄")]
    doc = journal_doc(list(FAKE_PL_JOURNAL) + extra, end="20261101")
    doc["줄수"] = len(doc["줄"]) + 2
    write_json(wehago_dir, "261101 분개장 자동수집.json", doc)
    base_plan(wehago_dir)
    return {"title": "받다 만 확장 분개장 JSON(줄 수 불일치)은 쓰지 않음", "rules": ["D7"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── D8 새 해 전기이월 없음 ─────────────
JAN = [_jl(dt.date(2026, 1, 5), 60, "81100", "복리후생비(판)", 1000000, None, "가상식당", "1월 식대"),
       _jl(dt.date(2026, 1, 5), 60, "10300", "보통예금", None, 1000000, "가상은행", "1월 식대")]
OPENING = [_jl(dt.date(2026, 1, 1), 59, "10300", "보통예금", 500000000, None, "가상은행", "전기이월"),
           _jl(dt.date(2026, 1, 1), 59, "37500", "이월이익잉여금", None, 500000000, "", "전기이월")]


@case
def case_d_no_opening(input_dir, collect, wehago_dir):
    """2026 분개장(1/5 부터)에 전기이월 줄이 없음 → 분개장으로 통장 잔액을 만들지 않음: 장부잔액.csv·장부입출금.csv 머리글만,
    주간 보고 통장 잔액은 계좌잔액.csv (짝: d_opening_present)."""
    base_books(input_dir, collect, wehago_dir, journal=pl_journal(extra=JAN))
    base_plan(wehago_dir)
    return {"title": "새 해 분개장에 전기이월이 없으면 통장 잔액은 계좌잔액.csv", "rules": ["D8"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


@case
def case_d_opening_present(input_dir, collect, wehago_dir):
    """d_no_opening 과 같고 1/1 전기이월(보통예금 5억) 줄만 더함 → 장부잔액.csv 가 분개장 누적으로 채워짐 (견줄 짝)."""
    base_books(input_dir, collect, wehago_dir, journal=pl_journal(extra=OPENING + JAN))
    base_plan(wehago_dir)
    return {"title": "전기이월이 있으면 통장 잔액을 분개장으로 만듦 (D8 의 짝)", "rules": ["D8"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── D9 결산 분개 ─────────────
@case
def case_d_closing_entries(input_dir, collect, wehago_dir):
    """10/31 결산전표(유형 '결산전표'): 행사외주비(도) 1,000만 대변(진행중행사로 대체)은 손익에서 빼고,
    감가상각비 200만 차변은 남김 → 10월 원가는 그대로, 감가상각비 200만이 10월 비용에 들어감."""
    d = dt.date(2026, 10, 31)
    closing = [_jl(d, 70, "14900", "진행중행사", 10000000, None, "", "결산 원가 대체"),
               _jl(d, 70, "61101", "행사외주비(도)", None, 10000000, "", "결산 원가 대체"),
               _jl(d, 70, "81800", "감가상각비", 2000000, None, "", "결산 감가상각"),
               _jl(d, 70, "20900", "감가상각누계액", None, 2000000, "", "결산 감가상각")]
    jr = pl_journal(extra=closing)
    base_books(input_dir, collect, wehago_dir, journal=jr)
    write_journal(wehago_dir, jr, sorts={70: "결산전표"})
    base_plan(wehago_dir)
    return {"title": "결산 분개는 손익에서 빼되 감가상각비 차변은 남김", "rules": ["D9"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── D10 선수금 계산서 = 계정 25900 ─────────────
@case
def case_d_advance_by_account(input_dir, collect, wehago_dir):
    """분개장 매출전표가 계산서 원천일 때: 가상고객A 1억1,000만(전표 30)은 적요에 선금 낱말이 없어도 대변이 선수금(25900) → '선수금',
    가상고객X 2,200만(전표 32)은 적요에 '계약금'이 있어도 대변이 수입수수료(41200) → '발행'."""
    jr = []
    for r in pl_journal():
        r = list(r)
        if r[1] == 30:
            r[9] = "[26201] 가상 컨퍼런스 1차"
            if r[3] == "41200":
                r[3], r[4] = "25900", "선수금"
        if r[1] == 32:
            r[9] = "기타 용역 계약금"
        jr.append(r)
    base_books(input_dir, collect, wehago_dir, journal=jr)
    write_journal(wehago_dir, jr, sorts=sales_sorts(30, 31, 32))
    base_plan(wehago_dir)
    return {"title": "선수금 계산서는 적요 낱말이 아니라 대변 계정 25900(선수금)으로 판단", "rules": ["D10"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── D11 카드 거래처 '카드사_1234' ─────────────
def _card_slip(no, vendor, memo):
    d = dt.date(2026, 10, 29)
    return [_jl(d, no, "61101", "행사외주비(도)", 1000000, None, "가상다과", memo),
            _jl(d, no, "13500", "부가세대급금", 100000, None, "가상다과", memo),
            _jl(d, no, "25300", "미지급금", None, 1100000, vendor, memo)]


@case
def case_d_card_vendor(input_dir, collect, wehago_dir):
    """원가 전표의 미지급금 거래처가 '가상은_1234'(카드사_끝 4자리 모양, '카드' 낱말 없음) → 법인카드: '카드사용미결제'·확정.
    같은 금액의 '가상은1234'(밑줄 없음) 전표는 보통 미지급 '요청미지급'·추정 (견줄 짝)."""
    extra = _card_slip(44, "가상은_1234", "[26201] 가상 컨퍼런스 다과 (카드)") + \
        _card_slip(45, "가상은1234", "[26201] 가상 컨퍼런스 다과 (외상)")
    base_books(input_dir, collect, wehago_dir, journal=pl_journal(extra=extra))
    base_plan(wehago_dir)
    return {"title": "법인카드 거래처 이름 '카드사_1234' 모양이면 카드 사용으로 봄", "rules": ["D11"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── D12 빈 입금예정일 = 발행일 + 60일 ─────────────
@case
def case_d_due_guess(input_dir, collect, wehago_dir):
    """이전 계산서.csv 에 가상고객X 10/28 계산서만 입금예정일 2026-11-30(확정 Y)을 손으로 넣어 둠 → 그대로 옮김.
    입금예정일이 빈 가상고객D 10/27 계산서는 발행일 + 60일 = 2026-12-26, 예정일확정 N."""
    import csv
    import os
    base_books(input_dir, collect, wehago_dir)
    base_plan(wehago_dir)
    with open(os.path.join(input_dir, "계산서.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["프로젝트번호", "거래처", "발행일", "구분", "공급가액", "부가세", "입금예정일", "예정일확정", "입금일", "입금액"])
        w.writerow(["", "가상고객X", "2026-10-28", "발행", "20,000,000", "2,000,000", "2026-11-30", "Y", "", ""])
        w.writerow(["26203", "가상고객D", "2026-10-27", "발행", "75,000,000", "7,500,000", "", "", "", ""])
    return {"title": "입금예정일이 빈 계산서는 발행일 + 60일(예상 N), 손으로 넣은 날짜는 그대로", "rules": ["D12"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── D13 정기예금: 계좌잔액.csv 손으로 넣은 줄 우선 ─────────────
DEPOSIT = [_jl(dt.date(2026, 10, 15), 46, "10500", "정기예금", 100000000, None, "가상은행", "정기예금 가입 만기 2027.04.15"),
           _jl(dt.date(2026, 10, 15), 46, "10300", "보통예금", None, 100000000, "가상은행", "정기예금 가입 만기 2027.04.15")]


def _add_balance_row(input_dir, row):
    import os
    with open(os.path.join(input_dir, "계좌잔액.csv"), "a", encoding="utf-8", newline="") as f:
        f.write(row + "\n")


@case
def case_d_deposit_manual(input_dir, collect, wehago_dir):
    """분개장에 정기예금 1억(만기 2027-04-15) 가입이 있고, 계좌잔액.csv 에도 손으로 '정기예금' 9,000만 줄을 넣음
    → 손으로 넣은 줄만 계좌로 씀 (장부 정기예금 1억은 넣지 않고 입력 확인에 알림). 짝: d_deposit_book."""
    base_books(input_dir, collect, wehago_dir, journal=pl_journal(extra=DEPOSIT))
    base_plan(wehago_dir)
    _add_balance_row(input_dir, '2026-11-02,정기예금,가상은행,"90,000,000","90,000,000",정기예금 만기 2027-04-15')
    return {"title": "계좌잔액.csv 에 손으로 넣은 정기예금 줄이 장부 정기예금보다 우선", "rules": ["D13"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


@case
def case_d_deposit_book(input_dir, collect, wehago_dir):
    """d_deposit_manual 과 같고 계좌잔액.csv 정기예금 줄만 없음 → 장부 정기예금 1억이 계좌(사용제한 1억, 만기 2027-04-15)로 들어감."""
    base_books(input_dir, collect, wehago_dir, journal=pl_journal(extra=DEPOSIT))
    base_plan(wehago_dir)
    return {"title": "계좌잔액.csv 에 정기예금 줄이 없으면 장부 정기예금을 계좌로 넣음 (D13 의 짝)", "rules": ["D13"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── D14·D16 프로젝트 연결 ─────────────
def write_links(input_dir, header, rows):
    import csv
    import os
    with open(os.path.join(input_dir, "프로젝트연결.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


@case
def case_d_link_recheck(input_dir, collect, wehago_dir):
    """프로젝트연결.csv 에 거래처코드·금액을 적은 수동 지정 두 줄 (강사료 전표 22 의 원가 줄 거래처Code 00501, 통장 줄 00900).
    ① 22번 전표 2번째 줄·코드 501·80만 → 26201: 2번째 줄(통장, 코드 900)과 안 맞고 같은 전표에 맞는 줄이 1번째 하나 → 그 줄로 옮겨 연결.
    ② 23번 전표 1번째 줄·코드 777·30만 → 26220: 그 줄 코드가 없어 맞지 않고 옮길 줄도 없음 → 연결하지 않음 (적요 [26999] 그대로 미연결)."""
    jr = []
    for r in pl_journal():
        r = list(r)
        if r[1] == 22:
            r[8] = "00501" if r[3] == "61101" else "00900"
        jr.append(r)
    base_books(input_dir, collect, wehago_dir, journal=jr)
    base_plan(wehago_dir)
    write_links(input_dir, ["전표일자", "전표번호", "줄", "거래처코드", "금액", "프로젝트번호"],
                [["2026-10-29", "00022", "2", "501", "800,000", "26201"],
                 ["2026-10-29", "00023", "1", "777", "300,000", "26220"]])
    return {"title": "수동 연결 파일도 거래처코드·금액으로 다시 확인 (맞는 줄로 옮기거나 쓰지 않음)", "rules": ["D14"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


@case
def case_d_link_order(input_dir, collect, wehago_dir):
    """원가 줄 연결 순서 (전표 51~55, 10/31):
    51 적요 [26201] + 수동 지정 26203 → 26203 (수동이 먼저) · 52 적요 [26201] + 분개장 프로젝트 칸 [26220] → 26220 (프로젝트 칸이 적요보다 먼저)
    · 53 적요 [26221] → 26221 · 54 코드 없음, 가상케이터링 100만+부가세 10만 = 인트라넷 요청 5107(110만, [26201]) 하나 → 자동 26201
    · 55 코드도 후보도 없음 → 미연결."""
    d = dt.date(2026, 10, 31)
    extra = []
    for no, amount, vendor, memo in ((51, 1000000, "가상수동업체", "[26201] 가상 수동 지정 줄"),
                                     (52, 1200000, "가상칸업체", "[26201] 가상 프로젝트 칸 줄"),
                                     (53, 1300000, "가상적요업체", "[26221] 가상 적요 코드 줄"),
                                     (54, 1000000, "가상케이터링", "가상 케이터링 (코드 없음)"),
                                     (55, 700000, "가상무명업체", "가상 미연결 비용")):
        extra += [_jl(d, no, "61101", "행사외주비(도)", amount, None, vendor, memo),
                  _jl(d, no, "13500", "부가세대급금", amount // 10, None, vendor, memo),
                  _jl(d, no, "25300", "미지급금", None, amount + amount // 10, vendor, memo)]
    jr = pl_journal(extra=extra)
    base_books(input_dir, collect, wehago_dir, journal=jr)
    proj = dict((i, "[00001][26220] 가상 전시") for i, r in enumerate(jr) if r[1] == 52)
    write_journal(wehago_dir, jr, project=proj)
    base_plan(wehago_dir)
    write_links(input_dir, ["전표일자", "전표번호", "줄", "프로젝트번호"], [["2026-10-31", "00051", "1", "26203"]])
    return {"title": "프로젝트 연결 순서: 수동 → 프로젝트 칸 → 적요 [코드] → 유일한 자동 후보 → 미연결", "rules": ["D16"],
            "asof": "2026-11-02", "kinds": ["weekly"]}
