"""연도별 세법 기준표와 '먼저 확인' 절차 (사용자 2026-11-12: 해마다 세법을 확인해서 적용, 개정 내용부터 먼저 확인하는 절차).

· 프로그램에 든 기본값(DEFAULTS): 값마다 상태가 있다.
    '자료확인' = 공개 자료로 확인한 값 (세무사 확인 전)
    '미확인'   = 개정이 있었거나 자료가 엇갈려 아직 못 정한 값 → 그 값을 쓰는 계산은 '확인 필요'로만 보여 주고 합계에 넣지 않는다.
· 사용자(세무사) 확인: 입력/세법기준.csv (연도, 항목, 값, 확인일, 출처). 창 '세법 기준 확인'에서 값을 고치거나 '확인함'을 누르면 적힌다.
· 그해 기본값이 없으면 가장 가까운 앞 해 값을 그대로 쓰되 '미확인'으로 본다 (새해가 되면 먼저 확인하라고 띄움).
· 한 해 중간에 시행되는 개정(시행일)이 있으면, 그 날 전에 확인했어도 시행일이 지나면 다시 확인하라고 띄운다.
· 프로그램은 인터넷에서 개정 내용을 읽어 오지 않는다(AI 없이 동작). 해마다 1월에 기본값을 갱신해 새 exe 로 넣는다.
법인세율 구간은 corptax.BRACKETS_* 에 있어 이 표에서는 보여 주기·확인만 한다(바뀌면 프로그램을 고쳐야 함).
"""
import csv
import datetime as dt
import os

FILE = "세법기준.csv"
COLUMNS = ["연도", "항목", "값", "확인일", "출처"]

# (키, 쉬운 이름, 단위, 어디에 쓰나)
ITEMS = [
    ("법인세율", "법인세율 구간 (과세표준)", "글", "법인세 예상 — 바뀌면 프로그램 수정 필요"),
    ("최저한세율", "중소기업 최저한세율", "비율", "감면·공제 뒤 최소한 내야 하는 세금"),
    ("대손충당금률", "대손충당금 한도율 (받을 돈 잔액 대비)", "비율", "결산 대손충당금 예상"),
    ("접대비기본한도", "중소기업 접대비(기업업무추진비) 기본 한도 (연)", "원", "세무조정 예상"),
    ("접대비수입비율", "접대비 수입금액 한도 비율 (매출 100억 이하)", "비율", "세무조정 예상"),
    ("인정이자율", "가지급금 인정이자율 (당좌대출이자율)", "비율", "세무조정 예상"),
    ("승용차상각한도", "업무용 승용차 감가상각비 한도 (1대 연)", "원", "세무조정 예상"),
    ("승용차기록없음한도", "운행기록부 없을 때 승용차 비용 한도 (1대 연)", "원", "세무조정 예상"),
    ("창업감면_과밀밖", "창업 감면율 — 과밀억제권역 밖 창업", "비율", "감면 후보"),
    ("창업감면_과밀밖청년", "창업 감면율 — 과밀억제권역 밖 청년 창업", "비율", "감면 후보"),
    ("창업감면_과밀안청년", "창업 감면율 — 과밀억제권역 안 청년 창업", "비율", "감면 후보"),
    ("고용공제_수도권", "통합고용 공제 1명당 (중소기업·수도권·청년 외)", "원", "감면 후보"),
    ("고용공제_지방", "통합고용 공제 1명당 (중소기업·수도권 밖·청년 외)", "원", "감면 후보"),
    ("고용공제_수도권청년", "통합고용 공제 1명당 (중소기업·수도권·청년 등)", "원", "감면 후보"),
    ("고용공제_지방청년", "통합고용 공제 1명당 (중소기업·수도권 밖·청년 등)", "원", "감면 후보"),
    ("금융소득기준", "금융소득 종합과세 기준 (1인 연)", "원", "배당 권장액"),
    ("배당원천세율", "배당 원천징수 소득세율 (지방세 별도)", "비율", "배당 권장액"),
    ("건강보험료율", "건강보험료율 (전체, 근로자는 절반)", "비율", "배당 권장액·급여 점검"),
    # 노동·급여 (사용자 2026-11-12: 고용·근로기준 법령을 받아 급여 처리 점검)
    ("최저시급", "최저임금 (시급)", "원", "급여 점검"),
    ("월소정시간", "주 40시간 월 환산 시간 (주휴 포함)", "시간", "급여 점검"),
    ("가산율", "연장·야간·휴일 근로 가산율", "비율", "급여 점검"),
    ("국민연금요율", "국민연금 보험료율 (전체, 근로자는 절반)", "비율", "급여 점검"),
    ("국민연금상한", "국민연금 기준소득월액 상한", "원", "급여 점검"),
    ("장기요양비율", "장기요양보험료 (건강보험료 대비)", "비율", "급여 점검"),
    ("고용보험요율", "고용보험 실업급여 요율 (전체, 근로자는 절반)", "비율", "급여 점검"),
    ("식대비과세", "식대 비과세 한도 (월)", "원", "급여 점검·연말정산"),
    # 신고 규칙 (사용자 2026-11-12: 신고 도우미)
    ("근로간이지급주기", "근로소득 간이지급명세서 제출 주기", "글", "신고 도우미"),
    ("사업기타간이지급주기", "사업·기타소득 간이지급명세서 제출 주기", "글", "신고 도우미"),
]
LABEL = dict((k, n) for k, n, _, _ in ITEMS)
UNIT = dict((k, u) for k, _, u, _ in ITEMS)
for _k in ("월소정시간",):
    UNIT[_k] = "시간"

SRC = "공개 세법 자료 (2026-11-12 확인)"
# {연도: {키: (값, 상태, 근거, 시행일 또는 None)}}
DEFAULTS = {
    2025: {
        "법인세율": ("2억 9% · 200억 19% · 3천억 21% · 초과 24%", "자료확인", SRC, None),
        "최저한세율": (0.07, "자료확인", SRC, None),
        "대손충당금률": (0.01, "자료확인", SRC, None),
        "접대비기본한도": (36_000_000, "자료확인", SRC, None),
        "접대비수입비율": (0.003, "자료확인", SRC, None),
        "인정이자율": (0.046, "자료확인", SRC, None),
        "승용차상각한도": (8_000_000, "자료확인", SRC, None),
        "승용차기록없음한도": (15_000_000, "자료확인", SRC, None),
        "창업감면_과밀밖": (0.5, "자료확인", "조특법 6조 (2025년 창업 당시)", None),
        "창업감면_과밀밖청년": (1.0, "자료확인", "조특법 6조 (2025년 창업 당시)", None),
        "창업감면_과밀안청년": (0.5, "자료확인", "조특법 6조 (2025년 창업 당시)", None),
        "고용공제_수도권": (8_500_000, "자료확인", "조특법 29조의8 (3년 같은 금액)", None),
        "고용공제_지방": (9_500_000, "자료확인", "조특법 29조의8 (3년 같은 금액)", None),
        "고용공제_수도권청년": (14_500_000, "자료확인", "조특법 29조의8 (3년 같은 금액)", None),
        "고용공제_지방청년": (15_500_000, "자료확인", "조특법 29조의8 (3년 같은 금액)", None),
        "금융소득기준": (20_000_000, "자료확인", SRC, None),
        "배당원천세율": (0.14, "자료확인", SRC, None),
        "건강보험료율": (0.0709, "자료확인", SRC, None),
        "최저시급": (10_030, "자료확인", "2025년 적용 최저임금 고시", None),
        "월소정시간": (209, "자료확인", "근로기준법 (주 40시간 + 주휴 8시간) × 4.345주", None),
        "가산율": (0.5, "자료확인", "근로기준법 56조", None),
        "국민연금요율": (0.09, "자료확인", "국민연금법 88조", None),
        "국민연금상한": (6_170_000, "자료확인", "2024-07 ~ 2025-06 기준소득월액 상한", None),
        "장기요양비율": (0.1295, "자료확인", SRC, None),
        "고용보험요율": (0.018, "자료확인", "고용보험료징수법 시행령 12조", None),
        "식대비과세": (200_000, "자료확인", "소득세법 시행령 17조의2", None),
        "근로간이지급주기": ("반기 (1~6월분 7월 말, 7~12월분 다음 해 1월 말)", "자료확인", "국세청 — 매월 제출은 2027년 1월 지급분부터", None),
        "사업기타간이지급주기": ("매월 (지급한 달의 다음 달 말일)", "자료확인", SRC, None),
    },
    2026: {
        "법인세율": ("2억 10% · 200억 20% · 3천억 22% · 초과 25%", "자료확인", "2025-12 국회 통과, 2026년 시작 사업연도부터 1%p 인상", None),
        "건강보험료율": (0.0719, "자료확인", SRC, None),
        "최저시급": (10_320, "자료확인", "2026년 적용 최저임금 고시", None),
        "국민연금요율": (0.095, "자료확인", "2025 연금개혁, 2026년부터 해마다 0.5%p 인상", None),
        "국민연금상한": (6_370_000, "자료확인", "2025-07 ~ 2026-06 기준소득월액 상한 (7월마다 바뀜)", dt.date(2026, 7, 1)),
        "장기요양비율": (0.1314, "자료확인", SRC, None),
        # 2026 개편: 근속 1·2·3년차별로 금액이 다르고 인원 감소 추징 삭제. 연차별 금액은 자료가 엇갈려 미확인 (2026-11-12)
        "고용공제_수도권": (None, "미확인", "조특법 29조의8 개정 (시행 2026-07-01): 1·2·3년차 금액 다름 — 세무사 확인", dt.date(2026, 7, 1)),
        "고용공제_지방": (None, "미확인", "조특법 29조의8 개정 (시행 2026-07-01): 1·2·3년차 금액 다름 — 세무사 확인", dt.date(2026, 7, 1)),
        "고용공제_수도권청년": (None, "미확인", "조특법 29조의8 개정 (시행 2026-07-01): 1·2·3년차 금액 다름 — 세무사 확인", dt.date(2026, 7, 1)),
        "고용공제_지방청년": (None, "미확인", "조특법 29조의8 개정 (시행 2026-07-01): 1·2·3년차 금액 다름 — 세무사 확인", dt.date(2026, 7, 1)),
    },
}
LATEST = max(DEFAULTS)


def _parse(key, text):
    t = str(text or "").strip().replace(",", "").replace("원", "")
    if not t:
        return None
    if UNIT.get(key) == "글":
        return str(text).strip()
    pct = t.endswith("%")
    v = float(t.rstrip("%"))
    if pct or (UNIT.get(key) == "비율" and v > 1):   # '9.5'처럼 % 없이 넣어도 퍼센트로 봄
        v /= 100.0
    return int(v) if UNIT.get(key) in ("원", "시간") else v


def read(input_dir):
    """사용자 확인 -> {(연도, 키): (값, 확인일, 출처)}."""
    out = {}
    path = os.path.join(input_dir, FILE) if input_dir else None
    if not path or not os.path.exists(path):
        return out
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            try:
                y, k = int(r.get("연도") or ""), (r.get("항목") or "").strip()
            except ValueError:
                continue
            if k not in LABEL:
                continue
            try:
                v = _parse(k, r.get("값"))
            except ValueError:
                continue
            out[(y, k)] = (v, (r.get("확인일") or "").strip(), (r.get("출처") or "").strip())
    return out


def _default(year, key):
    """그해 기본값, 없으면 가장 가까운 앞 해 값(상태 '미확인'으로) -> (값, 상태, 근거, 시행일)."""
    for y in sorted(DEFAULTS, reverse=True):
        if y <= year and key in DEFAULTS[y]:
            v, st, why, eff = DEFAULTS[y][key]
            if y == year:
                return v, st, why, eff
            if year > LATEST:   # 프로그램에 그해 기준이 아예 없음 → 먼저 확인
                return v, "미확인", "%d년 값을 그대로 씀 — %d년 개정 확인 필요" % (y, year), None
            return v, st, why + (" (%d년 값 그대로)" % y), eff
    return None, "미확인", "기준값 없음", None


def value(input_dir, year, key, today=None):
    """-> (값, 쓸 수 있나, 설명). 쓸 수 있나 = 사용자가 확인했거나 기본값 상태가 '자료확인'이고 값이 있음."""
    mine = read(input_dir).get((year, key))
    v, st, why, eff = _default(year, key)
    fl = None
    if input_dir:
        from . import lawwatch   # 법령 조문을 받아 개정·값 차이가 보였으면 (사용자 2026-11-12)
        fl = lawwatch.flags(input_dir).get(key)
    if mine is not None and mine[0] is not None:
        day = _day(mine[1])
        if eff and day and day < eff <= (today or dt.date.today()):
            return mine[0], False, "%s 확인 뒤 %s 시행 개정이 있어 다시 확인 필요" % (mine[1], eff.isoformat())
        if fl and day and _day(fl[2]) and day < _day(fl[2]):
            return mine[0], False, "%s 확인 뒤 %s 조문이 바뀜 (%s 받음) — 다시 확인 필요" % (mine[1], fl[0], fl[2])
        return mine[0], True, "확인함 %s%s" % (mine[1], " · " + mine[2] if mine[2] else "")
    if fl:
        return v, False, "법령 조문 확인 필요: %s (시행 %s, %s 받음)" % (fl[0], fl[1] or "?", fl[2])
    return v, v is not None and st == "자료확인", "%s · %s" % (st, why)


def _day(text):
    try:
        return dt.date.fromisoformat(str(text).strip()[:10])
    except ValueError:
        return None


def status(input_dir, year, today=None):
    """그해 기준표 -> {year, rows:[(키, 이름, 값, 쓸 수 있나, 설명, 사용자 확인 여부)], confirmed(모두 사용자 확인), todo(미확인 키들)}."""
    mine = read(input_dir)
    rows, todo = [], []
    for k, name, _, _ in ITEMS:
        v, ok, why = value(input_dir, year, k, today)
        rows.append((k, name, v, ok, why, (year, k) in mine and ok))
        if not ok:
            todo.append(k)
    return {"year": year, "rows": rows, "todo": todo, "confirmed": all(r[5] for r in rows), "known": year <= LATEST}


def show(key, v):
    if v is None:
        return "모름"
    u = UNIT.get(key)
    if u == "원":
        return "{:,}원".format(int(v))
    if u == "비율":
        return "%g%%" % round(v * 100, 4)
    if u == "시간":
        return "%g시간" % v
    return str(v)


def confirm(input_dir, year, values, source="", today=None):
    """사용자 확인 저장. values = {키: 값 글 또는 None(=지금 보이는 값 그대로 확인)}. -> 저장한 항목 수."""
    day = (today or dt.date.today()).isoformat()
    cur = read(input_dir)
    n = 0
    for k, text in values.items():
        if k not in LABEL:
            continue
        v = _parse(k, text) if text not in (None, "") else value(input_dir, year, k)[0]
        if v is None:
            raise ValueError("%s: 값이 없어 확인할 수 없음 — 세무사에게 받은 값을 넣어 주세요" % LABEL[k])
        cur[(year, k)] = (v, day, source)
        n += 1
    os.makedirs(input_dir, exist_ok=True)
    tmp = os.path.join(input_dir, FILE + ".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for (y, k), (v, d, s) in sorted(cur.items(), key=lambda x: (x[0][0], [i[0] for i in ITEMS].index(x[0][1]))):
            w.writerow([y, k, v if UNIT[k] != "비율" else ("%g%%" % round(v * 100, 4)), d, s])
    os.replace(tmp, os.path.join(input_dir, FILE))
    return n


def banner(T):
    """보고서 맨 위에 띄울 한 줄 (모두 확인했으면 빈 글)."""
    if not T or not T["todo"]:
        return ""
    names = [LABEL[k] for k in T["todo"]]
    head = ("%d년 세법 기준이 프로그램에 아직 없습니다 — 작년 값으로 계산 중. " % T["year"]) if not T["known"] else ""
    return head + "%d년 세법 기준 중 %d개 미확인: %s — 창 '세법 기준 확인'에서 세무사 확인 값을 넣으면 반영됩니다." % (
        T["year"], len(names), " · ".join(names[:4]) + (" 외" if len(names) > 4 else ""))


def render(T, esc):
    if not T:
        return ""
    h = ["<div class='q'>%d년 적용한 세법 기준</div>" % T["year"]]
    b = banner(T)
    if b:
        h.append("<div class='warn'>%s</div>" % esc(b))
    h.append("<table class='re'><tr><th class='l'>항목</th><th>값</th><th>상태</th><th class='l'>근거</th></tr>%s</table>" % "".join(
        "<tr><td class='l'>%s</td><td>%s</td><td>%s</td><td class='l'>%s</td></tr>"
        % (esc(n), esc(show(k, v)), "<span class='tag'>확인함</span>" if mine else ("<span class='tag e'>자료확인</span>" if ok else "<b style='color:#c62828'>미확인</b>"),
           esc(why)) for k, n, v, ok, why, mine in T["rows"]))
    h.append("<div class='note'>프로그램은 인터넷에서 세법 개정을 스스로 읽지 않습니다. 해마다 1월에 기본값을 갱신하고, "
             "세무사 확인 값은 창에서 넣습니다. '미확인' 값을 쓰는 계산은 '확인 필요'로만 보여 주고 합계에 넣지 않습니다.</div>")
    return "".join(h)
