"""묶음 U: 사용자가 정한 규칙 (golden/RULES.md U1~U10). 모두 가상 자료.

각 사례는 기본 가상 회사(build.base_books + BASE_PLAN 자금계획서)에서 규칙에 필요한 것만 바꾼다.
"""
import csv
import os

from build import BASE_PLAN, base_books, case, plan_doc, write_json

MONTHS = ["202610", "202611", "202612"]
TAKEN = "2026-11-01 09:00:00"


def _plan(wehago_dir, rows=None, company="(샘플) 플랜트에이트", stamp="261101", months=MONTHS, frm="20261001", to="20261231",
          taken=TAKEN):
    write_json(wehago_dir, "%s 자금계획 자동수집.json" % stamp,
               plan_doc(BASE_PLAN if rows is None else rows, months, frm, to, taken, company=company))


def _add_rows(input_dir, name, rows):
    """입력 CSV 끝에 줄을 더한다 (머리글 순서대로 dict). 샘플 CSV 는 UTF-8 BOM."""
    path = os.path.join(input_dir, name)
    with open(path, encoding="utf-8-sig", newline="") as f:
        head = next(csv.reader(f))
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        for r in rows:
            w.writerow([r.get(h, "") for h in head])


def _drop_rows(input_dir, name, drop):
    path = os.path.join(input_dir, name)
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    keep = [rows[0]] + [r for r in rows[1:] if not drop(dict(zip(rows[0], r)))]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f, lineterminator="\r\n").writerows(keep)


# ───────────── U2 자금계획서 없음 → 대표 보고 막음 ─────────────
@case
def case_u_no_fundplan(input_dir, collect, wehago_dir):
    base_books(input_dir, collect, wehago_dir)   # 자금계획 자동수집.json 을 넣지 않음 (나머지는 base 와 같음)
    return {"title": "자금계획서가 없으면 대표 보고를 만들지 않음", "rules": ["U2"], "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── U3 분개장 자료일 8일 → 막음, 7일 → 통과 ─────────────
@case
def case_u_journal_8days(input_dir, collect, wehago_dir):
    base_books(input_dir, collect, wehago_dir, journal_stamp="261025")   # 2026-10-25 받음 → 기준일 11-02 보다 8일 전
    _plan(wehago_dir)
    return {"title": "분개장 자료일이 기준일보다 8일 전이면 대표 보고를 만들지 않음", "rules": ["U3"], "asof": "2026-11-02",
            "kinds": ["weekly"]}


@case
def case_u_journal_7days(input_dir, collect, wehago_dir):
    base_books(input_dir, collect, wehago_dir, journal_stamp="261026")   # 7일 전: 허용 끝
    _plan(wehago_dir)
    return {"title": "분개장 자료일이 기준일보다 7일 전이면 아직 만듦 (8일 사례의 짝)", "rules": ["U3"], "asof": "2026-11-02",
            "kinds": ["weekly"]}


# ───────────── U10 다른 회사 분개장 → 막음 ─────────────
@case
def case_u_other_company(input_dir, collect, wehago_dir):
    import json
    base_books(input_dir, collect, wehago_dir)
    p = os.path.join(wehago_dir, "261031 분개장 자동수집.json")
    with open(p, encoding="utf-8") as f:
        doc = json.load(f)
    doc["회사"] = "(샘플) 가상다른회사"   # 확장이 다른 회사 SmartA 탭에서 받은 분개장
    write_json(wehago_dir, "261031 분개장 자동수집.json", doc)
    _plan(wehago_dir)   # 자금계획서는 이 회사 ((샘플) 플랜트에이트)
    return {"title": "분개장이 다른 회사 자료면 대표 보고를 만들지 않음", "rules": ["U10"], "asof": "2026-11-02",
            "kinds": ["weekly"]}


# ───────────── U1 모르는 값은 0 이 아님 ─────────────
@case
def case_u_unknown_not_zero(input_dir, collect, wehago_dir):
    base_books(input_dir, collect, wehago_dir)
    _plan(wehago_dir)
    # 금액을 모르는 지급 일정 한 줄 (날짜는 있음) + 잔액을 모르는 계좌 한 줄
    _add_rows(input_dir, "자금일정.csv", [{"예정일": "2026-11-13", "입출금": "지급", "금액": "", "확정여부": "확정",
                                         "분류": "거래처미지급", "거래처": "가상미정업체", "근거": "청구서 대기", "비고": "금액 미정"}])
    _add_rows(input_dir, "계좌잔액.csv", [{"기준일": "2026-11-02", "계좌명": "가상예비계좌", "은행": "가상은행", "잔액": "",
                                         "사용제한금액": "0", "제한사유": ""}])
    return {"title": "금액·잔액을 모르는 줄은 0으로 넣지 않고 '확인된 합계 + 미확인 N건'", "rules": ["U1"], "asof": "2026-11-02",
            "kinds": ["weekly"]}


# ───────────── U7 날짜 없는 금액은 따로 ─────────────
@case
def case_u_undated(input_dir, collect, wehago_dir):
    base_books(input_dir, collect, wehago_dir)
    _plan(wehago_dir)
    _add_rows(input_dir, "자금일정.csv", [{"예정일": "", "입출금": "지급", "금액": "12,345,000", "확정여부": "확정",
                                         "분류": "거래처미지급", "거래처": "가상날짜미정업체", "근거": "계약서", "비고": "지급일 미정"}])
    return {"title": "날짜 없는 지급 12,345,000원은 구간 표에 넣지 않고 '날짜 없는 금액' 표로", "rules": ["U7"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── U4 장부 잔액이 이김 / U5 계좌 사이 이체 빼기 ─────────────
def _bank_journal(transfer=False):
    """기본 분개장 + 1/2 전기이월(가상은행A 5억·가상은행B 1억). 보통예금 줄 거래처는 은행 이름(장부 계좌 = 거래처).
    transfer: 10/28 가상은행A → 가상은행B 20,000,000 (같은 전표에 보통예금 차변·대변)."""
    import datetime as dt
    from test_convert import FAKE_PL_JOURNAL
    from test_wehago import _jl
    j = [list(r) for r in FAKE_PL_JOURNAL]
    for r in j:
        if str(r[3]) == "10300":
            r[7] = "가상은행A"
    j += [_jl(dt.date(2026, 1, 2), 90, "10300", "보통예금", 500000000, None, "가상은행A", "전기이월"),
          _jl(dt.date(2026, 1, 2), 90, "10300", "보통예금", 100000000, None, "가상은행B", "전기이월")]
    if transfer:
        j += [_jl(dt.date(2026, 10, 28), 91, "10300", "보통예금", 20000000, None, "가상은행B", "가상 계좌간 이체"),
              _jl(dt.date(2026, 10, 28), 91, "10300", "보통예금", None, 20000000, "가상은행A", "가상 계좌간 이체")]
    return j


@case
def case_u_book_balance(input_dir, collect, wehago_dir):
    base_books(input_dir, collect, wehago_dir, journal=_bank_journal())
    _plan(wehago_dir)
    return {"title": "분개장 보통예금 잔액이 있으면 그것이 잔액, 계좌잔액.csv 는 사용제한만", "rules": ["U4"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


@case
def case_u_transfer(input_dir, collect, wehago_dir):
    base_books(input_dir, collect, wehago_dir, journal=_bank_journal(transfer=True))
    _plan(wehago_dir)
    return {"title": "계좌 사이 이체 20,000,000원은 입금·출금에서 뺌 (u_book_balance 의 짝)", "rules": ["U5"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── U6 카드 대금은 한 번만 ─────────────
CARD_AMT = 3456000


def _card_journal():
    """기본 분개장 + 10/10 가상 법인카드 사용 (미지급비용 대변, 거래처 '신한_1234', 거래처코드 09001) → 11/16 결제 예상."""
    import datetime as dt
    from test_convert import FAKE_PL_JOURNAL
    from test_wehago import _jl
    return list(FAKE_PL_JOURNAL) + [
        _jl(dt.date(2026, 10, 10), 92, "81100", "복리후생비(판)", CARD_AMT, None, "신한_1234", "가상 카드 사용", "09001"),
        _jl(dt.date(2026, 10, 10), 92, "26200", "미지급비용", None, CARD_AMT, "신한_1234", "가상 카드 사용", "09001")]


CARD_PLAN_ROW = ["20261116", "지급", "103", "미지급비용 지급", "09001", "신한_1234", CARD_AMT, "카드대금 - 신한카드 10월분", "일반", "16"]


@case
def case_u_card_once(input_dir, collect, wehago_dir):
    base_books(input_dir, collect, wehago_dir, journal=_card_journal())
    _plan(wehago_dir, BASE_PLAN + [CARD_PLAN_ROW])
    _drop_rows(input_dir, "자금일정.csv", lambda r: r.get("분류") == "카드대금")   # 샘플의 손으로 넣은 카드 줄은 빼서 두 곳만 비교
    return {"title": "장부로 계산한 카드대금과 자금계획서 카드 결제 줄은 같은 거래처코드라 한 번만 셈", "rules": ["U6"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── U9 주민번호는 결과에 그대로 나오지 않음 ─────────────
RRN_LIKE = "900101-1234567"   # 가상 (tests/test_wehago.py FAKE_LEDGER·FAKE_JOURNAL 에 이미 있는 주민번호 모양)


@case
def case_u_rrn_masked(input_dir, collect, wehago_dir):
    from test_wehago import FAKE_LEDGER
    # 매입매출장: 매출 줄 사업자번호 칸이 주민번호 모양 (개인 고객) · 분개장: 강사료 적요에 주민번호 모양 (기본과 같음)
    base_books(input_dir, collect, wehago_dir, ledger=FAKE_LEDGER)
    # 자금계획서: 개인 강사 지급 줄 거래처 이름·적요에 주민번호 모양
    _plan(wehago_dir, BASE_PLAN + [["20261110", "지급", "102", "미지급금 지급", "09002", "가상강사 " + RRN_LIKE, 800000,
                                    "강사료 - 가상 개인강사 " + RRN_LIKE, "일반", "10"]])
    return {"title": "주민번호 모양(가상 900101-1234567)은 결과 어디에도 그대로 나오지 않고 ******-******* 로", "rules": ["U9"],
            "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── U8 해 바뀜: 기준일 2027-01-02 ─────────────
def _year_journals():
    """2026 전체(1/1~12/31) = 기본 분개장 + 12월 매출·수금, 2027 일부(1/1~1/2) = 식대 한 전표."""
    import datetime as dt
    from test_convert import FAKE_PL_JOURNAL
    from test_wehago import _jl
    dec = [_jl(dt.date(2026, 12, 15), 80, "10800", "수입수수료미수금", 33000000, None, "가상고객E", "가상 연말 행사"),
           _jl(dt.date(2026, 12, 15), 80, "41200", "수입수수료", None, 30000000, "가상고객E", "가상 연말 행사"),
           _jl(dt.date(2026, 12, 15), 80, "25500", "부가세예수금", None, 3000000, "가상고객E", "가상 연말 행사"),
           _jl(dt.date(2026, 12, 28), 81, "10300", "보통예금", 33000000, None, "가상고객E", "연말 행사 입금"),
           _jl(dt.date(2026, 12, 28), 81, "10800", "수입수수료미수금", None, 33000000, "가상고객E", "연말 행사 입금")]
    jan = [_jl(dt.date(2027, 1, 2), 1, "81100", "복리후생비(판)", 700000, None, "가상식당", "1월 식대"),
           _jl(dt.date(2027, 1, 2), 1, "10300", "보통예금", None, 700000, "가상식당", "1월 식대")]
    return list(FAKE_PL_JOURNAL) + dec, jan


@case
def case_u_year_change(input_dir, collect, wehago_dir):
    from test_journal_json import auto_json
    y2026, y2027 = _year_journals()
    base_books(input_dir, collect, wehago_dir)   # 261031 분개장(2026-01-01~10-31, 같은 해 이전 내려받기)도 그대로 둔다
    for name, rows, start, end, gisu in (("261231 분개장 자동수집.json", y2026, "20260101", "20261231", "2"),
                                         ("270102 분개장 자동수집.json", y2027, "20270101", "20270102", "3")):
        doc = auto_json(rows, start=start, end=end)
        doc["회사"] = "(샘플) 플랜트에이트"
        doc["기간"]["gisu"] = gisu
        write_json(wehago_dir, name, doc)
    for old in os.listdir(wehago_dir):   # 매입매출장·전자세금계산서 엑셀도 1/2 받은 것으로 (장부 기준일 = 가장 이른 파일 날짜)
        if old.endswith("_20261031.xlsx"):
            os.rename(os.path.join(wehago_dir, old), os.path.join(wehago_dir, old.replace("_20261031", "_20270102")))
    plan = [["20270108", "지급", "102", "미지급금 지급", "000-00-00003", "주식회사 가상부스", 49500000, "매입 - 가상 전시부스", "매입매출", "08"],
            ["20270115", "입금", "601", "외상대금 회수", "C202", "가상고객D", 82500000, "매출 - 가상 전시부스 잔금", "매입매출", "15"]]
    _plan(wehago_dir, plan, stamp="270102", months=["202612", "202701", "202702"], frm="20261201", to="20270228",
          taken="2027-01-02 09:00:00")
    return {"title": "기준일 2027-01-02: 2026 분개장(10/31·12/31 받은 두 파일)과 2027 분개장을 겹치지 않게 한 번씩",
            "rules": ["U8"], "asof": "2027-01-02", "kinds": ["weekly", "monthly"]}
