"""세무조정 예상 (사용자 2026-11-12: 2번 세무조정도 프로그램으로).

장부 이익과 세법 이익의 차이 중 장부로 셀 수 있는 것만 어림한다 (1월~보고 달 누적, 한도는 달 수만큼 나눠 비교):
  · 접대비(기업업무추진비) 한도 초과 → 비용 인정 안 함 (+)
  · 벌금·과태료·가산세·과징금·범칙금 (적요로 찾음) → 비용 인정 안 함 (+)
  · 업무용 승용차 비용: 운행기록부 없으면 감가상각비까지 넣은 관련비용이 1대 연 1,500만 원 넘는 몫 (+, 사용자 2026-11-17: 1대·기록부 없음으로 보고 넣음)
    이때 감가상각비 한도(연 800만)는 감가상각비 × 업무사용비율로 비교 (시행령 50조의2 ⑦⑩)
  · 업무용 승용차 감가상각비: 작년 신고서의 승용차 상각비로 올해 1년 치 한도(연 800만) 조정 (±)
  · 대표·임직원 가지급금 인정이자 → 수익으로 더함 (+)
  · 기부금 → 한도 계산은 세무사 (확인 필요)
'넣음' 항목만 법인세 예상 과세표준에 더하고, '확인 필요'는 보여 주기만 한다. 세율·한도는 taxlaw 연도별 기준표.
업무와 관련 없는 비용·증빙 없는 비용은 전표마다 사람이 판단해야 해 다루지 않는다.
"""
import re
from .util import open_text as _open_text  # UTF-8·CP949 모두 읽음 (C5)

FILE = "세무조정.csv"
COLUMNS = ["연도", "항목", "금액", "반영", "근거"]
PENALTY = re.compile(r"벌금|벌과금|과태료|가산세|과징금|범칙금|교통위반|주정차")


def _sq(t):
    return re.sub(r"\s+", "", str(t or ""))


def adjust(journal, cfg, ym, input_dir=None, revenue=None, answers=None, wehago_dir=None):
    """-> {"items": [(이름, 금액, 넣음, 근거)], "total": 넣은 합}."""
    from . import taxlaw
    year, months = int(ym[:4]), int(ym[5:7])

    def law(k):
        return taxlaw.value(input_dir, year, k)
    ent = car = gift = 0
    pen, pen_n, pen_acct, pen_memo = 0, 0, 0, []
    loan_bal, loan_months, opening = 0, [], False
    by_month = {}
    for ln in journal or []:
        d = ln.get("date")
        if d is None or d.strftime("%Y-%m") > ym:
            continue
        name, code = _sq(ln.get("account")), _sq(ln.get("account_code"))
        dr, cr = ln.get("debit") or 0, ln.get("credit") or 0
        if "가지급금" in name or "대여금" in name and ("주임종" in name or "임원" in name):
            by_month[d.strftime("%Y-%m")] = by_month.get(d.strftime("%Y-%m"), 0) + dr - cr
            if "전기이월" in _sq(ln.get("sort")) + _sq(ln.get("memo")):
                opening = True
            continue
        if d.year != year:
            continue
        if "접대비" in name or "기업업무추진비" in name:
            ent += dr - cr
        elif "차량" in name and code[:1] in ("5", "8") or ("차량" in name and "유지" in name):
            car += dr - cr
        elif "기부금" in name:
            gift += dr - cr
        if dr and code[:1] in ("5", "8", "9") and PENALTY.search(name):
            pen += dr   # E3 (2026-11-17, 계산-11): 계정과목(벌과금·가산세 등)으로 먼저
            pen_acct += 1
        elif dr and code[:1] in ("5", "8", "9") and PENALTY.search(_sq(ln.get("memo"))):
            pen += dr   # 계정에 없으면 적요 낱말로 — 근거에 줄을 보여 확인받는다
            pen_n += 1
            pen_memo.append("%s %s %s원" % (d.isoformat(), ln.get("vendor") or ln.get("account") or "", "{:,}".format(int(dr))))
    items = []
    # 접대비
    base_lim, ok1, _ = law("접대비기본한도")
    rate, ok2, _ = law("접대비수입비율")
    if ent:
        if revenue is not None and base_lim and rate:
            lim = int((base_lim + revenue * 12.0 / months * rate) * months / 12.0)
            over = max(ent - lim, 0)
            items.append(("접대비 한도 초과", over, ok1 and ok2 and over > 0,
                          "1~%d월 접대비 %s원 vs 한도 %s원 (기본 %s + 매출 × %g%%, %d달 몫)"
                          % (months, "{:,}".format(int(ent)), "{:,}".format(lim), "{:,}".format(base_lim), rate * 100, months)))
        else:
            items.append(("접대비 한도 초과", None, False, "매출이나 세법 기준을 몰라 계산 못 함"))
    # 벌금·과태료
    why = []
    if pen_acct:
        why.append("벌과금·가산세 등 계정 %d건" % pen_acct)
    if pen_n:
        why.append("적요 낱말로 찾은 비용 %d건 (확인: %s%s)" % (pen_n, ", ".join(pen_memo[:5]), " 외" if pen_n > 5 else ""))
    items.append(("벌금·과태료·가산세", pen, pen > 0,
                  " · ".join(why) if why else "계정·적요에서 찾은 건 없음 (적요가 없는 건은 못 찾음)"))
    # 업무용 승용차
    lim_car, ok3, _ = law("승용차기록없음한도")
    rec = (answers or {}).get("승용차기록")
    if car and lim_car:
        part = int(lim_car * months / 12.0)
        over = max(int(car) - part, 0)
        why = "1~%d월 차량 비용 %s원 vs 운행기록부 없을 때 1대 한도 %s원 (%d달 몫)" % (months, "{:,}".format(int(car)), "{:,}".format(part), months)
        if rec == "씀" or rec == "승용차 없음":
            items.append(("업무용 승용차 비용", 0, False, why + " — 운행기록부를 쓰거나 승용차가 아니라 조정 없음"))
        else:
            # 사용자 2026-11-17 (카드): 세무사 답을 기다리지 않고 운행기록부 없음·승용차 1대로 보고 넘는 몫을 바로 더한다
            items.append(("업무용 승용차 비용", over, over > 0 and ok3,
                          why + " — 운행기록부 없음·승용차 1대로 보고 넣음 (기록부를 쓰거나 차가 여러 대면 창에서 고치면 줄어듦)"))
    # 업무용 승용차 감가상각비 한도 (사용자 2026-11-13: 작년 상세 신고서의 업무용승용차 관련비용 명세서)
    car_dep = _car_dep(input_dir, year, law("승용차상각한도"), wehago_dir, months)
    if car_dep and lim_car and rec not in ("씀", "승용차 없음"):
        car_dep = _no_log(items, car_dep, car, lim_car, law("승용차상각한도"), input_dir, year, wehago_dir, months)
    if car_dep:
        items.append(car_dep)
    # 가지급금 인정이자
    irate, ok4, _ = law("인정이자율")
    if by_month:
        bal, tot, n = 0, 0, 0
        for m in range(1, months + 1):
            key = "%d-%02d" % (year, m)
            prev = [v for k, v in sorted(by_month.items()) if k < key]
            bal = sum(prev) + by_month.get(key, 0)
            tot += max(bal, 0)
            n += 1
        avg = tot / float(n or 1)
        interest = int(avg * irate * months / 12.0) if irate else None
        # 2차 전수조사 V20 (2026-11-18): 예전 조건 'opening is not None'은 늘 참이라 효과가 없었다 (opening 은 참/거짓).
        # 작년 말 잔액 줄(전기이월)이 없어도 올해 빌려준 돈의 이자는 더해야 하므로 넣고, 작게 잡힐 수 있음은 근거에 적는다
        items.append(("가지급금 인정이자", interest, bool(interest) and ok4,
                      "가지급금 월평균 %s원 × %g%% × %d/12%s" % ("{:,}".format(int(avg)), (irate or 0) * 100, months,
                                                          "" if opening else " · 장부에 작년 말 잔액(전기이월) 줄이 없음 — 작년에서 넘어온 가지급금이 있으면 작게 잡힘")))
    if gift:
        items.append(("기부금 한도", None, False, "1~%d월 기부금 %s원 — 종류별 한도는 세무사 계산" % (months, "{:,}".format(int(gift)))))
    total = sum(int(v) for _, v, on, _ in items if on and v)
    return {"items": items, "total": total}


def _car_dep(input_dir, year, lim_info, wehago_dir=None, months=12):
    """작년 신고서의 승용차 감가상각비로 올해 조정 -> (이름, 금액, 넣음, 근거) 또는 None.

    법인세 예상의 감가상각비는 작년 장부 금액(이 차는 산 달부터 몇 달 치만)으로 먼저 잡는다. 올해는 1년 치를 상각하지만
    세법은 1대 연 800만 원까지만 비용으로 인정하므로, 실제 비용 인정액 = min(1년 치, 한도). 조정 = 작년 상각비 − 올해 인정액
    (보통 음수: 작년보다 비용 인정이 늘어 과세표준이 줄어듦). 창에 올해 감가상각비를 직접 넣었거나 위하고 고정자산대장 금액을 쓰는 해는 1년 치가 들어 있다고 보고 한도 넘는 몫을 더한다."""
    import datetime as dt
    if not input_dir:
        return None
    from . import taxreturn
    filed = taxreturn.load(input_dir).get((year - 1, "확정"))
    if not filed or not filed.get("승용차상각비"):
        return None
    lim, ok, _ = lim_info
    if not lim:
        return None
    try:
        acq = dt.date.fromisoformat((filed.get("승용차취득일") or "").strip()[:10])
    except ValueError:
        acq = None
    owned = (12 - acq.month + 1) if acq and acq.year == year - 1 else 12
    last_dep = filed["승용차상각비"]
    annual = int(last_dep * 12 / float(owned))
    allowed = min(annual, int(lim))
    from .corptax import read as read_dep, read_ledger
    manual = read_dep(input_dir).get(str(year)) is not None
    ledger = read_ledger(input_dir, wehago_dir).get(str(year)) is not None
    car_now = _ledger_car(input_dir, year, wehago_dir)
    if car_now:
        annual = car_now   # 위하고 고정자산관리대장의 올해 상각 예정액 (사용자 2026-11-13)
        allowed = min(annual, int(lim))
    head = ("%d년 신고서: 승용차(%s 취득) 감가상각비 %s원(%d달 치) 중 한도 넘은 %s원은 비용 인정 안 됨. "
            % (year - 1, acq.isoformat() if acq else "작년", "{:,}".format(last_dep), owned, "{:,}".format(filed.get("승용차상각초과") or 0)))
    if manual or ledger:   # 창 ⑨ 직접 입력이나 위하고 고정자산대장 금액이면 이 차 1년 치가 들어 있다고 본다
        adj = annual - allowed
        why = head + ("올해 감가상각비 예상은 %s(이 차 1년 치 %s원) → 한도 %s원 넘는 %s원을 과세표준에 더함%s"
                      % ("창에 직접 넣은 금액" if manual else "위하고 고정자산대장 금액", "{:,}".format(annual), "{:,}".format(allowed), "{:,}".format(adj),
                         " (직접 넣은 금액에 이 차가 빠져 있으면 세무사 확인)" if manual else ""))
    else:
        adj = last_dep - allowed
        why = head + ("올해 감가상각비 예상은 작년 금액이라 이 차는 %s원만 들어 있지만, 올해 1년 치 약 %s원 중 세법이 인정하는 건 한도 %s원 → 과세표준 %s원 %s. "
                      "장부 감가상각비 예상은 1년 치보다 약 %s원 적게 잡혀 있음 (창 ‘가끔 넣는 값 › 감가상각비’에 올해 감가상각비를 넣으면 장부 이익도 맞춰짐)"
                      % ("{:,}".format(last_dep), "{:,}".format(annual), "{:,}".format(allowed), "{:,}".format(abs(adj)),
                         "줄어듦" if adj < 0 else "늘어남", "{:,}".format(max(annual - last_dep, 0))))
    from .corptax import DEP_MODE
    if DEP_MODE == "prorate" and months < 12:   # 사용자 2026-11-17 (카드): 감가상각비 예상처럼 지난 달 수만큼만 (결정 M5와 같은 기준)
        full = adj
        adj = int(round(full * months / 12.0))
        why += " · 1~%d월 몫 %s원 = 1년 치 %s원 × %d/12 (감가상각비 예상과 같은 기준)" % (months, "{:,}".format(adj), "{:,}".format(full), months)
    return ("업무용 승용차 감가상각비 한도", adj, bool(ok), why)


def _no_log(items, car_dep, car, lim_car, lim_info, input_dir, year, wehago_dir, months):
    """운행기록부 없음 (사용자 2026-11-17 카드)일 때 법인세법 시행령 50조의2를 그대로 따른다 (11/17 최종 점검에서 고침):
    ② 관련비용 = 감가상각비 + 유류비·보험료·수선비 등 → 감가상각비도 넣어 1,500만 원(달 수만큼)과 비교
    ⑦ 넘으면 업무사용비율 = 1,500만 ÷ 관련비용, 넘는 몫은 비용 인정 안 함
    ⑩ 감가상각비 한도 초과 = 감가상각비 × 업무사용비율 − 800만 (달 수만큼).
    올해 1년 치 감가상각비를 대장에서 모르면 예전 계산 그대로 둔다."""
    from .corptax import DEP_MODE
    annual = _ledger_car(input_dir, year, wehago_dir)
    lim8 = lim_info[0]
    if not annual or not lim8 or DEP_MODE != "prorate":
        return car_dep
    dep = int(round(annual * min(months, 12) / 12.0))
    total = int(car or 0) + dep
    cap = int(lim_car * months / 12.0)
    cap8 = int(lim8 * months / 12.0)
    ratio = 1.0 if total <= cap else cap / float(total)
    private = max(total - cap, 0)
    over = max(int(round(dep * ratio)) - cap8, 0)
    for i, it in enumerate(items):
        if it[0] == "업무용 승용차 비용":
            items[i] = ("업무용 승용차 비용", private, private > 0 and it[2] is not None,
                        "1~%d월 승용차 관련비용 %s원 (차량 비용 %s + 감가상각비 %s) vs 운행기록부 없을 때 한도 %s원 (연 %s, %d달 몫) → 넘는 %s원은 비용 인정 안 됨 "
                        "(업무사용비율 %.1f%%, 법인세법 시행령 50조의2 ②⑦) — 운행기록부 없음·승용차 1대로 보고 넣음 (기록부를 쓰면 창에서 고치면 줄어듦)"
                        % (months, "{:,}".format(total), "{:,}".format(int(car or 0)), "{:,}".format(dep), "{:,}".format(cap),
                           "{:,}".format(int(lim_car)), months, "{:,}".format(private), ratio * 100))
            if private > 0:
                items[i] = (items[i][0], items[i][1], True, items[i][3])
    name, _, ok, why = car_dep
    why = why.split(" → 한도")[0] if " → 한도" in why else why
    why += (" → 1~%d월 감가상각비 %s원 × 업무사용비율 %.1f%% = %s원 중 한도 %s원(연 %s, %d달 몫) 넘는 %s원을 과세표준에 더함 (시행령 50조의2 ⑩)"
            % (months, "{:,}".format(dep), ratio * 100, "{:,}".format(int(round(dep * ratio))), "{:,}".format(cap8),
               "{:,}".format(int(lim8)), months, "{:,}".format(over)))
    return (name, over, ok, why)


def _ledger_car(input_dir, year, wehago_dir=None):
    """고정자산 대장에서 올해 승용차(차량운반구) 상각 예정액 합. 없으면 None."""
    import csv
    import os
    rows = []
    if wehago_dir:
        from . import wehago_raw
        rows = wehago_raw.asset_rows(wehago_raw.files(wehago_dir))
    if not rows and input_dir and os.path.exists(os.path.join(input_dir, "고정자산.csv")):
        with _open_text(os.path.join(input_dir, "고정자산.csv")) as f:
            rows = list(csv.DictReader(f))
    v = sum(int(r.get("당기상각") or 0) for r in rows if str(r.get("기준연도")) == str(year) and "차량" in (r.get("계정") or ""))
    return v or None


def build_table(books, cfg, asof, input_dir=None, wehago_dir=None):
    """세무조정.csv: 법인세 예상과 같은 기간·같은 계산."""
    from .convert import Table
    from . import corptax
    if books.state != "ok" or not books.journal:
        return Table(FILE, COLUMNS, [], written=False, reason="분개장 없음 (기존 파일 그대로)")
    ym = corptax._last_full_month(asof)
    A = corptax.adjust_for(books.journal, cfg, asof, input_dir, wehago_dir)
    rows = [dict(zip(COLUMNS, [ym[:4], n, "" if v is None else str(int(v)), "넣음" if on else ("조정 없음" if v == 0 and "확인 필요" not in why else "확인 필요"), why]))
            for n, v, on, why in A["items"]]
    return Table(FILE, COLUMNS, rows, notes=["세무조정 예상 (1~%d월): 법인세 예상에 +%s원 넣음, 확인 필요 %d건"
                                             % (int(ym[5:]), "{:,}".format(A["total"]), sum(1 for r in rows if r["반영"] != "넣음"))])


def load(input_dir):
    import csv
    import os
    path = os.path.join(input_dir, FILE)
    if not os.path.exists(path):
        return None
    with _open_text(path) as f:
        rows = list(csv.DictReader(f))
    return rows or None


def render(rows, esc):
    if not rows:
        return ""
    tot = sum(int(r["금액"]) for r in rows if r.get("반영") == "넣음" and (r.get("금액") or "").strip())
    h = ["<div class='wsub'>세무조정 예상 (장부로 셀 수 있는 것만)</div>",
         "<table class='pt tx'><thead><tr><th>항목</th><th>금액</th><th>법인세 예상에</th><th>근거</th></tr></thead><tbody>%s</tbody></table>"
         % "".join("<tr><td>%s</td><td>%s</td><td>%s</td><td style='text-align:left'>%s</td></tr>"
                   % (esc(r["항목"]), "{:,}".format(int(r["금액"])) if (r.get("금액") or "").strip() else "–",
                      "<b>확인 필요</b>" if r["반영"] == "확인 필요" else esc(r["반영"]), esc(r["근거"])) for r in rows),
         "<div class='note'>%s</div>" % esc("넣은 조정 합 +%s원은 과세표준에 더함. 업무 무관·증빙 없는 비용은 전표마다 사람이 판단해야 해 빠져 있음 · 세무사 확인 필요" % "{:,}".format(tot))]
    return "".join(h)
