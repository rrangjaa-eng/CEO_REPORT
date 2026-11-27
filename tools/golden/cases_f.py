"""묶음 F: 자금 규칙 (자금계획 맞추기·일정) 사례. 모두 가상 자료.

공통: build.base_books 의 가상 회사 (장부 기준일 2026-10-31, 기준일 2026-11-02) 에 규칙이 필요한 것만 더한다.
자금계획서는 확장 자동수집 JSON. 장부(분개장)와 맞추는 규칙(F1·F3·F4·F5)은 자료일(수집시각)을 2026-10-26 으로 둔다:
자동수집 자금계획은 자료일 전 전표를 보지 않으므로(fundplan.settle window) 자료일 뒤·장부 기준일(10-31) 앞의 전표가 있어야
'이미 지급'이 생긴다. 10-26 은 기준일보다 7일 전이라 아직 쓰인다(F7: 8일이면 안 쓰임).
"""
import csv
import json
import datetime as dt
import os

from build import case, base_books, write_json, plan_doc, plan_row, BASE_PLAN  # noqa: F401

MONTHS = ["202610", "202611", "202612"]
EARLY = "2026-10-26 09:00:00"   # 기준일 2026-11-02 보다 7일 전 (아직 쓰임)


def _jl(date, no, code, account, debit, credit, vendor, memo, vcode=""):
    from test_wehago import _jl as jl
    return jl(date, no, code, account, debit, credit, vendor, memo, vcode)


def _journal(extra):
    from test_convert import FAKE_PL_JOURNAL
    return FAKE_PL_JOURNAL + extra


def _plan(wehago_dir, rows, taken=EARLY, name=None):
    name = name or "%s 자금계획 자동수집.json" % (taken[2:4] + taken[5:7] + taken[8:10])
    write_json(wehago_dir, name, plan_doc(rows, MONTHS, "20261001", "20261231", taken))


def _bought(day, no, vendor, vcode, amount, memo):
    """매입 원전표: 비용(수수료) 차변 / 미지급금 대변."""
    return [_jl(day, no, "83100", "지급수수료", amount, None, vendor, memo, vcode),
            _jl(day, no, "25300", "미지급금", None, amount, vendor, memo, vcode)]


def _paid(day, no, vendor, vcode, amount, memo, credit=("10300", "보통예금")):
    """지급 전표: 미지급금 차변 / (기본) 보통예금 대변."""
    return [_jl(day, no, "25300", "미지급금", amount, None, vendor, memo, vcode),
            _jl(day, no, credit[0], credit[1], None, amount, vendor, memo, vcode)]


def _sold(day, no, vendor, vcode, amount, memo):
    """매출 원전표: 외상매출금(수입수수료미수금) 차변 / 수입수수료 대변."""
    return [_jl(day, no, "10800", "수입수수료미수금", amount, None, vendor, memo, vcode),
            _jl(day, no, "41200", "수입수수료", None, amount, vendor, memo, vcode)]


def _received(day, no, vendor, vcode, amount, memo):
    """입금 전표: 보통예금 차변 / 외상매출금 대변."""
    return [_jl(day, no, "10300", "보통예금", amount, None, vendor, memo, vcode),
            _jl(day, no, "10800", "수입수수료미수금", None, amount, vendor, memo, vcode)]


def _schedule_add(input_dir, rows, with_code=False):
    """입력/자금일정.csv 에 줄을 더한다. rows: dict(예정일, 입출금, 금액, 확정여부, 분류, 거래처, 근거[, 거래처코드])."""
    path = os.path.join(input_dir, "자금일정.csv")
    with open(path, encoding="utf-8-sig", newline="") as f:
        old = list(csv.reader(f))
    head = old[0] + (["거래처코드"] if with_code and "거래처코드" not in old[0] else [])
    body = [r + [""] * (len(head) - len(r)) for r in old[1:]]
    for r in rows:
        body.append([str(r.get(c, "")) for c in head])
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(body)


def D(y, m, d):
    return dt.date(y, m, d)


# ───────────── F1 대체(재분류) 전표는 지급이 아님 ─────────────
@case
def case_f_reclass_not_paid(input_dir, collect, wehago_dir):
    """가상재분류: 미지급금 차변 / 미지급비용 대변 (통장 출금 없음) → '예정'으로 남음.
    가상실지급: 같은 모양인데 대변이 보통예금 → '이미 지급'. 두 줄 모두 자금계획 예정일 11-06."""
    extra = (_bought(D(2026, 10, 10), 601, "가상재분류", "00701", 5500000, "가상 재분류 원전표")
             + [_jl(D(2026, 10, 28), 602, "25300", "미지급금", 5500000, None, "가상재분류", "미지급금→미지급비용 대체", "00701"),
                _jl(D(2026, 10, 28), 602, "26200", "미지급비용", None, 5500000, "가상재분류", "미지급금→미지급비용 대체", "00701")]
             + _bought(D(2026, 10, 10), 603, "가상실지급", "00702", 6600000, "가상 실지급 원전표")
             + _paid(D(2026, 10, 28), 604, "가상실지급", "00702", 6600000, "가상 실지급 지급"))
    base_books(input_dir, collect, wehago_dir, journal=_journal(extra))
    _plan(wehago_dir, BASE_PLAN + [
        plan_row("20261106", "지급", "0000000701", "가상재분류", 5500000, "매입 - 가상 재분류"),
        plan_row("20261106", "지급", "0000000702", "가상실지급", 6600000, "매입 - 가상 실지급"),
    ])
    return {"title": "대체(재분류) 전표는 지급이 아님: 미지급금→미지급비용 대체는 '예정', 통장 출금은 '이미 지급'",
            "rules": ["F1"], "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── F2 100원 끝전 ─────────────
@case
def case_f_cents_match(input_dir, collect, wehago_dir):
    """계산서 미수 가상고객D 82,500,000 ↔ 자금계획 입금 82,500,080 (80원 차이) → 같은 입금으로 맞춤.
    계산서 미수 가상고객X 20,900,000 ↔ 자금계획 입금 20,900,200 (200원 차이) → 다른 건 (추가 + '자금계획서에 없음')."""
    base_books(input_dir, collect, wehago_dir)
    rows = [r for r in BASE_PLAN if r[5] != "가상고객D"] + [
        plan_row("20261120", "입금", "C202", "가상고객D", 82500080, "매출 - 가상 전시부스 잔금 (끝전 80원)"),
        plan_row("20261127", "입금", "C203", "가상고객X", 20900200, "매출 - 기타 용역 (끝전 200원)"),
    ]
    _plan(wehago_dir, rows, taken="2026-11-01 09:00:00")
    return {"title": "100원 끝전: 계산서 미수와 80원 다른 자금계획 입금은 같은 건, 200원 다르면 다른 건",
            "rules": ["F2"], "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── F3 '이미 지급' 확인 창 -31 ~ +15일 ─────────────
@case
def case_f_done_window(input_dir, collect, wehago_dir):
    """자금계획 예정일 11-06 줄 넷이 모두 10-28 통장 출금으로 '이미 지급'. 같은 거래처·같은 금액 자금일정 줄은
    예정일 기준 +15일(11-21)·-31일(10-06)이면 지워지고, +16일(11-22)·-32일(10-05)이면 남는다.
    (장부 거래처 이름은 '…상사'로 달리 둠: 자금계획↔장부는 거래처코드로 맞고, 자금일정 자동 보관(F10)은 이름이 달라 건드리지 않게)"""
    spec = [("가상창A", "00721", 1100000, "2026-11-21"), ("가상창B", "00722", 1200000, "2026-11-22"),
            ("가상창C", "00723", 1300000, "2026-10-06"), ("가상창D", "00724", 1400000, "2026-10-05")]
    extra, plan, sched = [], list(BASE_PLAN), []
    for k, (name, code, amt, day) in enumerate(spec):
        extra += _bought(D(2026, 9, 25), 610 + 2 * k, name + "상사", code, amt, "가상 원전표")
        extra += _paid(D(2026, 10, 28), 611 + 2 * k, name + "상사", code, amt, "가상 지급")
        plan.append(plan_row("20261106", "지급", "0000000" + code[2:], name, amt, "매입 - " + name))
        sched.append({"예정일": day, "입출금": "지급", "금액": amt, "확정여부": "확정", "분류": "거래처미지급",
                      "거래처": name, "근거": "청구서", "비고": "예정일 11-06 기준 %+d일" % (dt.date.fromisoformat(day) - D(2026, 11, 6)).days})
    base_books(input_dir, collect, wehago_dir, journal=_journal(extra))
    _schedule_add(input_dir, sched)
    _plan(wehago_dir, plan)
    return {"title": "이미 지급 줄이 지우는 기존 일정: 계획일 31일 전 ~ 15일 뒤만 (+16일·-32일은 남음)",
            "rules": ["F3"], "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── F4 전표 하나는 계획 하나에만 ─────────────
@case
def case_f_one_slip_one_plan(input_dir, collect, wehago_dir):
    """같은 거래처·같은 금액 자금계획 줄 둘(11-06, 11-13)에 통장 출금 전표는 하나(10-28) → 앞 줄만 '이미 지급', 뒤 줄은 '예정'."""
    extra = (_bought(D(2026, 10, 5), 630, "가상중복", "00731", 2200000, "가상 원전표 1")
             + _bought(D(2026, 10, 6), 631, "가상중복", "00731", 2200000, "가상 원전표 2")
             + _paid(D(2026, 10, 28), 632, "가상중복", "00731", 2200000, "가상 지급 1회"))
    base_books(input_dir, collect, wehago_dir, journal=_journal(extra))
    _plan(wehago_dir, BASE_PLAN + [
        plan_row("20261106", "지급", "0000000731", "가상중복", 2200000, "매입 - 가상중복 1"),
        plan_row("20261113", "지급", "0000000731", "가상중복", 2200000, "매입 - 가상중복 2"),
    ])
    return {"title": "전표 하나는 계획 하나에만: 같은 거래처·금액 두 줄에 지급 전표 하나 → 한 줄만 이미 지급",
            "rules": ["F4"], "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── F5 맞추기 창 지급 14일·입금 45일 ─────────────
@case
def case_f_early_window(input_dir, collect, wehago_dir):
    """예정일보다 먼저 움직인 돈: 지급은 14일 전까지, 입금은 45일 전까지만 그 줄의 것으로 본다.
    가상창14 지급 11-10 ← 10-27 출금(14일 전) = 이미 지급 / 가상창15 지급 11-11 ← 10-27 출금(15일 전) = 예정
    가상입45 입금 12-10 ← 10-26 입금(45일 전) = 이미 입금 / 가상입46 입금 12-11 ← 10-26 입금(46일 전) = 예정"""
    extra = (_bought(D(2026, 10, 1), 640, "가상창14", "00741", 1410000, "가상 원전표")
             + _paid(D(2026, 10, 27), 641, "가상창14", "00741", 1410000, "가상 조기 지급")
             + _bought(D(2026, 10, 1), 642, "가상창15", "00742", 1510000, "가상 원전표")
             + _paid(D(2026, 10, 27), 643, "가상창15", "00742", 1510000, "가상 조기 지급")
             + _sold(D(2026, 9, 1), 644, "가상입45", "00743", 4500000, "가상 매출")
             + _received(D(2026, 10, 26), 645, "가상입45", "00743", 4500000, "가상 조기 입금")
             + _sold(D(2026, 9, 1), 646, "가상입46", "00744", 4600000, "가상 매출")
             + _received(D(2026, 10, 26), 647, "가상입46", "00744", 4600000, "가상 조기 입금"))
    base_books(input_dir, collect, wehago_dir, journal=_journal(extra))
    _plan(wehago_dir, BASE_PLAN + [
        plan_row("20261110", "지급", "0000000741", "가상창14", 1410000, "매입 - 가상창14"),
        plan_row("20261111", "지급", "0000000742", "가상창15", 1510000, "매입 - 가상창15"),
        plan_row("20261210", "입금", "0000000743", "가상입45", 4500000, "매출 - 가상입45"),
        plan_row("20261211", "입금", "0000000744", "가상입46", 4600000, "매출 - 가상입46"),
    ])
    return {"title": "맞추기 창: 지급은 예정일 14일 전, 입금은 45일 전 전표까지만 '이미' (하루 더 이르면 예정)",
            "rules": ["F5"], "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── F6 같은 금액 7일 안 다른 거래처 ─────────────
@case
def case_f_other_vendor_near(input_dir, collect, wehago_dir):
    """자금계획 예정 줄 셋(11-13)과 같은 금액 자금일정 줄 (거래처가 다름):
      ① 가상코드갑[761] ↔ 가상코드을[762] 11-11 (2일, 코드 둘 다 있고 다름) → 다른 건 (둘 다 일정에 남음)
      ② 가상이름갑[763] ↔ 가상이름을 (코드 없음) 11-11 (2일) → 같은 건으로 바꿈 (MATCH_DAYS 7일 안, 이름 달라도)
      ③ 가상이름병[764] ↔ 가상이름정 (코드 없음) 11-21 (8일) → 다른 건"""
    base_books(input_dir, collect, wehago_dir)
    _schedule_add(input_dir, [
        {"예정일": "2026-11-11", "입출금": "지급", "금액": 3310000, "확정여부": "확정", "분류": "거래처미지급",
         "거래처": "가상코드을", "근거": "청구서", "거래처코드": "762"},
        {"예정일": "2026-11-11", "입출금": "지급", "금액": 4410000, "확정여부": "확정", "분류": "거래처미지급",
         "거래처": "가상이름을", "근거": "청구서"},
        {"예정일": "2026-11-21", "입출금": "지급", "금액": 5510000, "확정여부": "확정", "분류": "거래처미지급",
         "거래처": "가상이름정", "근거": "청구서"},
    ], with_code=True)
    _plan(wehago_dir, BASE_PLAN + [
        plan_row("20261113", "지급", "0000000761", "가상코드갑", 3310000, "매입 - 가상코드갑"),
        plan_row("20261113", "지급", "0000000763", "가상이름갑", 4410000, "매입 - 가상이름갑"),
        plan_row("20261113", "지급", "0000000764", "가상이름병", 5510000, "매입 - 가상이름병"),
    ], taken="2026-11-01 09:00:00")
    return {"title": "같은 금액·7일 안이라도 거래처코드가 다르면 다른 건 (코드 없는 옛 줄은 7일 안이면 같은 건, 8일이면 다른 건)",
            "rules": ["F6"], "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── F7 7일 넘게 묵은 자금계획 ─────────────
@case
def case_f_stale_plan(input_dir, collect, wehago_dir):
    """기본 회사와 같은 자금계획인데 수집시각이 2026-10-25 (기준일 2026-11-02 보다 8일 전) → 쓰지 않음, 대표 보고 막힘."""
    base_books(input_dir, collect, wehago_dir)
    _plan(wehago_dir, BASE_PLAN, taken="2026-10-25 09:00:00")
    return {"title": "기준일보다 8일 묵은 자금계획서는 쓰지 않음 (기존 일정 사용 + 대표 보고 막힘)",
            "rules": ["F7"], "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── F8 자금계획이 같은 방향·금액·거래처코드의 기존 일정을 대신함 ─────────────
@case
def case_f_plan_replaces(input_dir, collect, wehago_dir):
    """자금일정 가상대체[751] 지급 7,710,000 11-30 ↔ 자금계획 가상대체[0000000751] 지급 7,710,000 11-13 (17일 차이):
    거래처코드가 같아 자금계획 줄로 바뀜 (날짜는 자금계획 11-13). 같은 코드·금액의 자금일정 '입금' 줄은 방향이 달라 그대로 남음."""
    base_books(input_dir, collect, wehago_dir)
    _schedule_add(input_dir, [
        {"예정일": "2026-11-30", "입출금": "지급", "금액": 7710000, "확정여부": "확정", "분류": "거래처미지급",
         "거래처": "가상대체(일정)", "근거": "청구서", "거래처코드": "751"},
        {"예정일": "2026-11-13", "입출금": "입금", "금액": 7710000, "확정여부": "추정", "분류": "기타입금",
         "거래처": "가상대체(일정)", "근거": "환급 예상", "거래처코드": "751"},
    ], with_code=True)
    _plan(wehago_dir, BASE_PLAN + [
        plan_row("20261113", "지급", "0000000751", "가상대체", 7710000, "매입 - 가상대체"),
    ], taken="2026-11-01 09:00:00")
    return {"title": "자금계획 줄은 같은 방향·금액·거래처코드의 기존 일정을 대신함 (날짜가 17일 달라도, 방향이 다르면 아님)",
            "rules": ["F8"], "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── F9 인트라넷 지급요청·남은 예산은 자금 일정에서 뺌 ─────────────
@case
def case_f_intranet_excluded(input_dir, collect, wehago_dir):
    """기본 회사 그대로 (인트라넷 스냅숏 지급요청 13건): 요청은 일정에 넣지 않고 intranet_only 에 건수·합계로만 남김."""
    base_books(input_dir, collect, wehago_dir)
    _plan(wehago_dir, BASE_PLAN, taken="2026-11-01 09:00:00", name="261101 자금계획 자동수집.json")
    return {"title": "인트라넷 지급요청·남은 예산은 자금 일정에 넣지 않고 비교로만 (건수·합계)",
            "rules": ["F9"], "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── F11 사용자가 넣은 출금일 ─────────────
@case
def case_f_user_payday(input_dir, collect, wehago_dir):
    base_books(input_dir, collect, wehago_dir)
    _plan(wehago_dir, BASE_PLAN, taken="2026-11-01 09:00:00")
    return {"title": "사용자가 넣은 출금일(2026-11-05 목요일)을 주간 출금일로 씀",
            "rules": ["F11"], "asof": "2026-11-02", "kinds": ["weekly"], "payday": "2026-11-05"}


# ───────────── F12 넣은 출금일이 기준일과 같거나 앞 ─────────────
@case
def case_f_payday_not_after(input_dir, collect, wehago_dir):
    base_books(input_dir, collect, wehago_dir)
    _plan(wehago_dir, BASE_PLAN, taken="2026-11-01 09:00:00")
    return {"title": "넣은 출금일(2026-11-02)이 기준일과 같으면 다음 금요일(2026-11-06)로 잡고 입력 확인에 안내",
            "rules": ["F12"], "asof": "2026-11-02", "kinds": ["weekly"], "payday": "2026-11-02"}


# ───────────── F13 꼭 나갈 정기 지출 ─────────────
@case
def case_f_must_pay(input_dir, collect, wehago_dir):
    """같은 날(11-26) 자금일정 '추정' 지급 둘: 급여 9,990,000 은 꼭 나갈 돈(확정 쪽 합계에 들어감),
    소모품 8,880,000 은 예상 쪽 합계에만."""
    base_books(input_dir, collect, wehago_dir)
    _schedule_add(input_dir, [
        {"예정일": "2026-11-26", "입출금": "지급", "금액": 9990000, "확정여부": "추정", "분류": "급여",
         "거래처": "가상상여", "근거": "지난달 평균"},
        {"예정일": "2026-11-26", "입출금": "지급", "금액": 8880000, "확정여부": "추정", "분류": "소모품",
         "거래처": "가상문구", "근거": "지난달 평균"},
    ])
    _plan(wehago_dir, BASE_PLAN, taken="2026-11-01 09:00:00")
    return {"title": "꼭 나갈 정기 지출(급여 등)은 '추정'이어도 확정 쪽(여유 자금)에서 뺌, 소모품 추정은 예상 쪽에만",
            "rules": ["F13"], "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── F14 세금 예상 합치기 ─────────────
@case
def case_f_tax_merge(input_dir, collect, wehago_dir):
    """장부로 계산한 부가세 3분기 10,000,000 (납부일 10-26) ↔ 자금일정 '부가세 3분기' 세무서 9,500,000 (10-30):
    납부일 ±7일·세목 낱말로 같은 세금 → 세금 줄은 넣지 않고 비교만 (차이 -500,000). 기본 회사는 맞는 줄이 없어 다음 금요일로 넣음."""
    base_books(input_dir, collect, wehago_dir)
    _schedule_add(input_dir, [
        {"예정일": "2026-10-30", "입출금": "지급", "금액": 9500000, "확정여부": "확정", "분류": "세금",
         "거래처": "세무서", "근거": "부가세 3분기 신고"},
    ])
    _plan(wehago_dir, BASE_PLAN, taken="2026-11-01 09:00:00")
    return {"title": "세금 예상(세금예상.csv)은 같은 세금 일정이 있으면 넣지 않고 비교만, 없으면 일정에 넣음",
            "rules": ["F14"], "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── F15 날짜 지난 미입금 계산서 ─────────────
@case
def case_f_late_invoice(input_dir, collect, wehago_dir):
    """매출 계산서 가상고객L 2026-08-25 발행 5,500,000, 입금예정일 비어 발행+60일 = 10-24 (기준일 앞), 아직 안 들어옴
    → 일정의 원래 줄은 그대로 두고, 출금일(11-06)로 옮긴 사본을 '이번 주 예상 입금'(late_in)으로."""
    from test_convert_invoices import SALES_EINVOICE, _ACC
    sales = SALES_EINVOICE + [["08-25", "C209", "가상고객L", "일반", "가상 지연 용역", 5000000, 500000, 5500000] + list(_ACC)]
    base_books(input_dir, collect, wehago_dir, sales=sales)
    _plan(wehago_dir, BASE_PLAN, taken="2026-11-01 09:00:00")
    return {"title": "예정일 지난 미입금 계산서는 출금일로 옮긴 사본으로 이번 주 예상 입금에 둠 (확정 잔액엔 안 넣음)",
            "rules": ["F15"], "asof": "2026-11-02", "kinds": ["weekly"]}


# ───────────── F10 지급된 자금일정 자동 보관 ─────────────
# 변환이 자금일정_지난기록.csv 의 '정리일' 칸에 오늘(dt.date.today())을 적는다: extract.py 가 오늘을 기준일로 묶어 고정됨.
@case
def case_f_archive_paid(input_dir, collect, wehago_dir):
    """자금일정 지급 줄과 장부 보통예금 출금 (같은 금액):
      가상보관A 11-03 ↔ 10-31 출금 (3일 전, 거래처 같음) → 보관
      가상보관B 11-14 ↔ 10-31 출금 (14일 전, 거래처 같음) → 보관 / 가상보관C 11-15 ↔ 10-31 (15일 전) → 남음
      가상보관D 11-03 ↔ 10-31 출금 거래처 '가상다른곳' (3일 전이지만 이름이 둘 다 있고 다름) → 남음"""
    extra = []
    for k, (vendor, amt) in enumerate([("가상보관A", 2710000), ("가상보관B", 2720000), ("가상보관C", 2730000),
                                       ("가상다른곳", 2740000)]):
        extra += _bought(D(2026, 10, 1), 680 + 2 * k, vendor, "", amt, "가상 원전표")
        extra += _paid(D(2026, 10, 31), 681 + 2 * k, vendor, "", amt, "가상 지급")
    base_books(input_dir, collect, wehago_dir, journal=_journal(extra))
    _schedule_add(input_dir, [
        {"예정일": "2026-11-03", "입출금": "지급", "금액": 2710000, "확정여부": "확정", "분류": "거래처미지급", "거래처": "가상보관A", "근거": "청구서"},
        {"예정일": "2026-11-14", "입출금": "지급", "금액": 2720000, "확정여부": "확정", "분류": "거래처미지급", "거래처": "가상보관B", "근거": "청구서"},
        {"예정일": "2026-11-15", "입출금": "지급", "금액": 2730000, "확정여부": "확정", "분류": "거래처미지급", "거래처": "가상보관C", "근거": "청구서"},
        {"예정일": "2026-11-03", "입출금": "지급", "금액": 2740000, "확정여부": "확정", "분류": "거래처미지급", "거래처": "가상보관D", "근거": "청구서"},
    ])
    _plan(wehago_dir, BASE_PLAN, taken="2026-11-01 09:00:00")
    return {"title": "통장에서 이미 나간 자금일정 줄은 자동 보관 (±3일, 같은 거래처면 지급 14일 전까지)",
            "rules": ["F10"], "asof": "2026-11-02", "kinds": ["weekly"]}


@case
def case_f_tax_missing(input_dir, collect, wehago_dir):
    """세금예상.csv 가 없으면 대표 보고를 막는다. 변환은 장부를 읽으면 늘 세금예상.csv 를 만들므로, 전체 흐름에서 이 파일이 없는
    경우는 변환이 거부될 때뿐: 받다 만 분개장 JSON(줄수 3줄 모자람)으로 변환을 막고 샘플 세금예상.csv 를 지운다.
    (그래서 자금계획.csv 도 없어 '자금계획서 없음'이 함께 나온다.)"""
    base_books(input_dir, collect, wehago_dir)
    p = os.path.join(wehago_dir, "261031 분개장 자동수집.json")
    with open(p, encoding="utf-8") as f:
        doc = json.load(f)
    doc["줄"] = doc["줄"][:-3]
    write_json(wehago_dir, "261031 분개장 자동수집.json", doc)
    os.remove(os.path.join(input_dir, "세금예상.csv"))
    _plan(wehago_dir, BASE_PLAN, taken="2026-11-01 09:00:00")
    return {"title": "세금예상.csv 가 없으면 대표 보고를 막음 (변환 거부로 자금계획.csv 도 없음)",
            "rules": ["F14"], "asof": "2026-11-02", "kinds": ["weekly"]}
