"""신고 도우미 (사용자 2026-11-12: 부가세·간이지급명세서·원천세 신고 때 어떤 칸에 어떤 값을 넣는지 양식, 위하고에서 신고할 때 양식도).

부가세: 분개장 매입·매출 전표(유형 '매입전표'·'매출전표')를 전표 한 장씩 묶어 신고서 칸으로 나눈다.
  · 매출: 카드사 거래처·카드 수수료가 있으면 (3) 신용카드·현금영수증, 부가세 0원이면 영세율·면세 확인, 나머지 (1) 세금계산서
  · 매입: 대변 거래처가 법인카드('신한_5860' 꼴)면 (14) 신용카드 수취분, 아니면 (10) 세금계산서 일반 / (11) 고정자산(유형자산 계정)
    접대비·승용차 관련 매입세액은 (16) 공제받지 못할 매입세액 후보 (확인 필요), 부가세 0원 매입은 계산서(면세) 또는 불공 — 확인 필요
  장부에는 증빙 종류(세금계산서·카드·현금영수증)가 없어 거래처·계정으로 어림한다 → 위하고 부가세신고서 화면 숫자와 대조해서 쓴다.
원천세·간이지급명세서: 예수금 적요(급여·사업소득·기타소득)로 칸별 세액. 인원·지급액은 위하고 급여·사업소득·기타소득 자료가 들어오면 채운다.
칸 번호는 2026년 홈택스 일반과세자 신고서 기준. 위하고 화면 메뉴·칸 순서는 PC에서 확인해 맞춘다(WEHAGO_STEPS).
"""
import collections
import datetime as dt
import re

from .filing import HOMETAX, _sq

CARD = re.compile(r"^[^\s_]+_\d{4}$")
ASSET = ("206", "207", "208", "209", "210", "212", "213")
NONDEDUCT = ("접대비", "기업업무추진비")

# 위하고에서 신고할 때 순서 (2026-11-12 일반 안내 — 메뉴 이름은 PC 화면 확인 뒤 고침)
WEHAGO_STEPS = {
    "부가세": ["위하고 SmartA › 부가가치세 › 부가가치세신고서: 신고 구분(예정/확정)·기간을 고르고 [불러오기]로 매입매출전표를 모음",
              "아래 '신고서 칸별 값'과 위하고 화면의 같은 칸 숫자를 맞춰 봄 (다르면 그 칸의 전표를 확인)",
              "부속서류: 세금계산서합계표, 신용카드매출전표등수령명세서, 공제받지못할매입세액명세서 확인",
              "위하고 › 전자신고 › 부가가치세 전자신고 파일 만들기 → 홈택스 › 세금신고 › 신고서 변환(교차검증)으로 제출",
              "납부: 홈택스 납부서 또는 가상계좌, 기한은 신고 일정 표"],
    "원천세": ["위하고 SmartA › 원천징수 › 원천징수이행상황신고서: 귀속·지급 기간(반기면 6달)을 고르고 [불러오기]",
               "아래 '칸별 값'과 A01(근로)·A25(사업)·A42(기타) 줄의 인원·총지급액·소득세를 맞춰 봄",
               "위하고 › 전자신고 › 원천세 전자신고 파일 → 홈택스 › 신고서 변환으로 제출, 지방소득세는 위택스",
               ],
    "간이지급": ["위하고 SmartA › 원천징수 › 간이지급명세서(사업소득·기타소득·근로소득): 지급 달을 고르고 [불러오기]",
                "소득자별 지급액·세액이 아래 표와 맞는지 확인",
                "위하고 › 전자신고 › 간이지급명세서 파일 → 홈택스 › 지급명세·자료제출 › 변환 제출"],
}


def _quarter(asof):
    """도우미를 만들 분기: 기준일이 속한 분기의 바로 앞 분기(신고할 차례). -> (시작, 끝, 이름, 기한)."""
    q = (asof.month - 1) // 3   # 0..3 이번 분기
    y, pq = (asof.year, q - 1) if q else (asof.year - 1, 3)
    start = dt.date(y, pq * 3 + 1, 1)
    end = (dt.date(y + (pq == 3), 1 if pq == 3 else pq * 3 + 4, 1) - dt.timedelta(days=1))
    name = "%d년 %d기 %s (%d~%d월)" % (y, 1 if pq < 2 else 2, "예정" if pq in (0, 2) else "확정", start.month, end.month)
    due = dt.date(end.year + (end.month == 12), 1 if end.month == 12 else end.month + 1, 25)
    return start, end, name, due


def vat(journal, start, end):
    """-> {"rows": [(칸, 이름, 공급가액, 세액, 근거)], "check": [확인 필요 글], "pay": 납부세액}."""
    slips = collections.OrderedDict()
    for ln in journal or []:
        d = ln.get("date")
        s = (ln.get("sort") or "").strip()
        if d is None or not (start <= d <= end) or s not in ("매입전표", "매출전표"):
            continue
        slips.setdefault((s, d, ln.get("no")), []).append(ln)
    box = collections.defaultdict(lambda: [0, 0, 0])   # 칸 -> [공급가액, 세액, 장수]
    check = []
    for (s, d, no), lines in slips.items():
        codes = [_sq(x.get("account_code")) for x in lines]
        if s == "매출전표":
            vat_ = sum((x.get("credit") or 0) - (x.get("debit") or 0) for x in lines if _sq(x.get("account_code")) == "25500")
            sup = sum((x.get("credit") or 0) for x in lines if _sq(x.get("account_code")).startswith("4"))
            # 카드 매출: 카드사 거래처 차변 또는 같은 전표의 카드 수수료(지급수수료 비용) 차변 (수입수수료미수금은 매출채권이라 아님)
            card = any(CARD.match(_sq(x.get("vendor"))) or "카드" in _sq(x.get("vendor")) for x in lines if x.get("debit")) or \
                any(_sq(x.get("account")).startswith("지급수수료") and x.get("debit") for x in lines)
            if not vat_:
                k = "5"
                check.append("%s 매출 %s원 부가세 0원 — 영세율·면세 매출인지 확인" % (d.isoformat(), format(sup, ",")))
            else:
                k = "3" if card else "1"
        else:
            vat_ = sum((x.get("debit") or 0) - (x.get("credit") or 0) for x in lines if _sq(x.get("account_code")) == "13500")
            sup = sum((x.get("debit") or 0) for x in lines if _sq(x.get("account_code")) != "13500")
            card = any(CARD.match(_sq(x.get("vendor"))) for x in lines if x.get("credit"))
            asset = any(c[:3] in ASSET for c in codes)
            if not vat_:
                check.append("%s 매입 %s원 부가세 0원 — 계산서(면세) 또는 공제 안 되는 매입" % (d.isoformat(), format(sup, ",")))
                continue
            k = ("14" if card else "10") + ("고정" if asset else "")
            if any(w in _sq(x.get("account")) for x in lines for w in NONDEDUCT):
                box["16"][0] += sup
                box["16"][1] += vat_
                box["16"][2] += 1
        box[k][0] += sup
        box[k][1] += vat_
        box[k][2] += 1
    names = [("1", "세금계산서 발급분 (매출)"), ("3", "신용카드·현금영수증 발행분 (매출)"), ("5", "영세율·면세 (확인 필요)"),
             ("10", "세금계산서 수취분 — 일반 매입"), ("10고정", "세금계산서 수취분 — 고정자산 (칸 11)"),
             ("14", "그 밖의 공제 — 신용카드 수취분 일반 (칸 14, 명세서 41)"), ("14고정", "그 밖의 공제 — 신용카드 수취분 고정자산 (명세서 42)"),
             ("16", "공제받지 못할 매입세액 후보 (접대비 관련, 확인 필요)")]
    box_no = {"10고정": "11", "14고정": "14"}   # 고정자산 매입은 신고서 칸 11 (2026-11-14 코덱스 검토: 10으로 나갔음)
    rows = [(box_no.get(k, k), n, box[k][0], box[k][1], "%d장" % box[k][2]) for k, n in names if box[k][2]]
    out_tax = box["1"][1] + box["3"][1]
    in_tax = box["10"][1] + box["10고정"][1] + box["14"][1] + box["14고정"][1] - box["16"][1]
    return {"rows": rows, "check": check, "out": out_tax, "in": in_tax, "pay": out_tax - in_tax}


def withholding(journal, start, end):
    """예수금 적요로 원천세 칸별 소득세·지방소득세 -> [(코드, 이름, 소득세, 지방소득세)]."""
    s = collections.defaultdict(lambda: [0, 0])
    for ln in journal or []:
        d = ln.get("date")
        if d is None or not (start <= d <= end) or _sq(ln.get("account")) != "예수금" or not ln.get("credit"):
            continue
        memo, vendor = _sq(ln.get("memo")), _sq(ln.get("vendor"))
        kind = "A25" if "사업소득" in memo else ("A42" if "기타소득" in memo else ("A01" if "급여" in memo else None))
        if kind is None or "기타예수금" in memo:
            continue
        if "세무서" in vendor:
            s[kind][0] += ln["credit"]
        elif any(w in vendor for w in ("구청", "시청", "군청")):
            s[kind][1] += ln["credit"]
    names = {"A01": "근로소득 간이세액", "A25": "사업소득 매월징수", "A42": "기타소득"}
    return [(k, names[k], s[k][0], s[k][1]) for k in ("A01", "A25", "A42") if s[k][0] or s[k][1]]


FILE = "신고도우미.csv"
COLUMNS = ["신고", "기간", "기한", "칸", "이름", "공급가액", "세액", "지방소득세", "근거"]


def build_table(books, cfg, asof, input_dir=None):
    """변환 때 장부로 신고 도우미 숫자를 만든다 (보고서는 이 파일만 읽음)."""
    from .convert import Table
    from . import filing
    if books.state != "ok" or not books.journal:
        return Table(FILE, COLUMNS, [], written=False, reason="분개장 없음 (기존 파일 그대로)")
    J = books.journal
    start, end, name, due = _quarter(asof)
    V = vat(J, start, end)
    rows = []
    per, dd = name, filing._workday(due).isoformat()
    for k, n, a, b, c in V["rows"]:
        rows.append(["부가세", per, dd, k, n, a, b, "", c])
    rows.append(["부가세", per, dd, "=", "납부(환급) 세액 = 매출세액 %s − 매입세액 %s" % (format(V["out"], ","), format(V["in"], ",")), "", V["pay"], "", ""])
    for c in V["check"]:
        rows.append(["부가세", per, dd, "확인", c, "", "", "", ""])
    if asof.month == 1:
        ws, we = dt.date(asof.year - 1, 7, 1), dt.date(asof.year - 1, 12, 31)
    elif asof.month <= 6:
        ws, we = dt.date(asof.year, 1, 1), dt.date(asof.year, 6, 30)
    else:
        ws, we = dt.date(asof.year, 7, 1), dt.date(asof.year, 12, 31)
    wd = filing._workday(dt.date(we.year + (we.month == 12), 1 if we.month == 12 else 7, 10)).isoformat()
    for k, n, a, b in withholding(J, ws, we):
        rows.append(["원천세", "%s~%s" % (ws.isoformat(), we.isoformat()), wd, k, n, ("약 %d" % int(a / 0.03)) if k == "A25" else "", a, b,
                     "예수금 적요 기준 (반기 납부면 이 기간 전체)"])
    out = [dict(zip(COLUMNS, [str(x) for x in r])) for r in rows]
    return Table(FILE, COLUMNS, out, notes=["신고 도우미: 부가세 %s 납부 예상 %s원, 원천세 칸 %d줄" % (name, format(V["pay"], ","), sum(1 for r in rows if r[0] == "원천세"))])


def load(input_dir):
    import csv
    import os
    path = os.path.join(input_dir, FILE)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f)) or None


def render(rows, esc):
    if not rows:
        return ""
    def W(t):
        t = (t or "").strip()
        try:
            return format(int(float(t.replace("약 ", ""))), ",") if t and not t.startswith("약") else ("약 " + format(int(float(t[2:])), ",") if t else "")
        except ValueError:
            return esc(t)
    h = ["<h2>신고 도우미</h2>"]
    for kind, title in (("부가세", "부가세"), ("원천세", "원천세 이행상황신고서")):
        R = [r for r in rows if r["신고"] == kind]
        if not R:
            continue
        h.append("<div class='q'>%s · %s · 기한 %s</div>" % (esc(title), esc(R[0]["기간"]), esc(R[0]["기한"])))
        main = [r for r in R if r["칸"] not in ("확인",)]
        if kind == "부가세":
            h.append("<table class='re'><tr><th>칸</th><th class='l'>이름</th><th>공급가액</th><th>세액</th><th class='l'>근거</th></tr>%s</table>"
                     % "".join("<tr><td>%s</td><td class='l'>%s</td><td>%s</td><td>%s</td><td class='l'>%s</td></tr>"
                               % ("" if r["칸"] == "=" else "(%s)" % esc(r["칸"]), ("<b>%s</b>" if r["칸"] == "=" else "%s") % esc(r["이름"]),
                                  W(r["공급가액"]), W(r["세액"]), esc(r["근거"])) for r in main))
            chk = [r["이름"] for r in R if r["칸"] == "확인"]
            if chk:
                h.append("<div class='note'><b>확인 필요 %d건</b><br>%s</div>" % (len(chk), "<br>".join(esc(x) for x in chk[:15])))
            h.append("<div class='note'>홈택스: %s · 확정신고면 전자신고세액공제 1만 원(칸 18), 예정고지 세액은 칸 22에서 뺌. 장부에는 증빙 종류가 없어 거래처·계정으로 나눈 어림값 — 위하고 신고서 숫자와 대조.</div>" % esc(HOMETAX["부가세"]))
            h.append(_steps("위하고에서 신고할 때 (부가세)", WEHAGO_STEPS["부가세"], esc))
        else:
            h.append("<table class='re'><tr><th>코드</th><th class='l'>소득</th><th>인원</th><th>총지급액</th><th>소득세</th><th>지방소득세 (위택스)</th></tr>%s</table>"
                     % "".join("<tr><td>%s</td><td class='l'>%s</td><td>급여 자료 받은 뒤</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                               % (esc(r["칸"]), esc(r["이름"]), W(r["공급가액"]) or "급여 자료 받은 뒤", W(r["세액"]), W(r["지방소득세"])) for r in main))
            h.append(_steps("위하고에서 신고할 때 (원천세)", WEHAGO_STEPS["원천세"], esc))
    h.append(_steps("위하고에서 제출할 때 (간이지급명세서)", WEHAGO_STEPS["간이지급"], esc))
    h.append("<div class='note'>칸 번호는 2026년 홈택스 일반과세자 신고서 기준. 인원·총지급액·소득자별 지급액은 '인사·급여 자료 받기'로 위하고 자료가 들어오면 채웁니다. 위하고 메뉴 이름은 PC 화면 확인 뒤 맞춤. 세무사 확인 필요.</div>")
    return "".join(h)


def _steps(title, steps, esc):
    return "<div class='q'>%s</div><ol>%s</ol>" % (esc(title), "".join("<li>%s</li>" % esc(s) for s in steps))
