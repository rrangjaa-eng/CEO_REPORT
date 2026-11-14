"""실제 법인세 신고서 값 (사용자 2026-11-13: 2025 법인세 신고서·2026 중간예납 신고서 제공).

입력/법인세신고.csv 한 줄 = 신고서 한 장. 프로그램 예상(장부로 어림)과 나란히 보여 주고,
작년 신고에서 배운 것(세무조정 크기, 감면이 최저한세에 걸렸는지)을 올해 예상에 참고로 붙인다.
"""
import csv
import os

FILE = "법인세신고.csv"
COLUMNS = ["연도", "구분", "사업연도", "수입금액", "장부세전이익", "과세표준", "산출세액", "공제감면세액", "총부담세액",
           "기납부세액", "차감납부세액", "지방소득세", "실제납부", "결산확정일", "신고일", "조정",
           # 상세 신고서에서 (사용자 2026-11-13: 공제감면세액합계표·세액공제조정명세서·농어촌특별세·업무용승용차 명세)
           "특별감면", "고용공제", "공제이월", "농특세", "승용차상각비", "승용차상각초과", "승용차취득일"]
NUMS = COLUMNS[3:13] + ["특별감면", "고용공제", "공제이월", "농특세", "승용차상각비", "승용차상각초과"]
MIN_RATE = 0.07   # 중소기업 최저한세율 (taxlaw 값이 있으면 그것)
NONG_RATE = 0.20  # 농어촌특별세: 세액공제(통합고용 등)로 줄인 세금의 20% (중소기업 특별세액감면은 비과세)


def _n(t):
    t = str(t or "").replace(",", "").strip()
    try:
        return int(float(t)) if t else None
    except ValueError:
        return None


def load(input_dir):
    """-> {(연도, 구분): dict} (숫자 칸은 int 또는 None)."""
    path = os.path.join(input_dir, FILE)
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            y = _n(r.get("연도"))
            if not y:
                continue
            d = dict((k, (r.get(k) or "").strip()) for k in COLUMNS)
            for k in NUMS:
                d[k] = _n(r.get(k))
            out[(y, d["구분"] or "확정")] = d
    return out


def at_min_tax(d, rate=MIN_RATE):
    """감면 뒤 세금이 최저한세(과세표준 × 7%)에 딱 걸렸나."""
    if not d or d.get("과세표준") is None or d.get("총부담세액") is None or not d.get("공제감면세액"):
        return False
    return abs(d["총부담세액"] - int(d["과세표준"] * rate)) <= 10


def W(v):
    return "–" if v is None else "{:,}".format(int(v))


def _min_rate(input_dir, year):
    try:
        from . import taxlaw
        return taxlaw.checked(input_dir, year, "최저한세율", MIN_RATE)[0] or MIN_RATE
    except Exception:
        return MIN_RATE


def credits(input_dir, year, base, corp):
    """올해 법인세 = 산출세액 − 중소기업 특별세액감면 − 이월된 통합고용세액공제, 단 최저한세(과세표준 × 7%) 밑으로는 안 줄어듦.
    줄인 공제의 20%는 농어촌특별세로 같이 냄. 작년 상세 신고서(특별감면·공제이월 칸)가 없으면 None.

    특별감면율은 작년 신고서의 실제 비율(감면 ÷ 산출세액: 감면율 × 감면 대상 소득 비율)을 그대로 쓴다.
    올해 새로 생길 통합고용 공제는 넣지 않는다 (이월액만으로도 최저한세까지 줄면 결과가 같음 — 'room' 으로 확인)."""
    if not input_dir or base is None or corp is None:
        return None
    last = load(input_dir).get((int(year) - 1, "확정"))
    if not last or last.get("특별감면") is None or last.get("공제이월") is None:
        return None
    rate = (last["특별감면"] / float(last["산출세액"])) if last.get("산출세액") else 0.0
    floor = int(max(base, 0) * _min_rate(input_dir, int(year)))
    sp = min(int(corp * rate), max(corp - floor, 0))
    after = corp - sp
    avail = last["공제이월"]
    room = max(after - floor, 0)
    used = min(avail, room)
    final = after - used
    nong = int(used * NONG_RATE) // 10 * 10   # 10원 미만 버림 (작년 68,534 → 68,530 납부)
    return {"corp": corp, "sp_rate": rate, "sp": sp, "floor": floor, "avail": avail, "used": used, "room": room,
            "final": final, "nong": nong, "national": final + nong, "carry_next": avail - used, "at_floor": used == room and room > 0,
            "last_year": int(year) - 1}


def for_report(input_dir, asof, base_now=None, tax_now=None):
    """경영관리 법인세 장에 붙일 dict 또는 None (신고서 파일 없음)."""
    D = load(input_dir)
    if not D:
        return None
    last = D.get((asof.year - 1, "확정"))
    mid = D.get((asof.year, "중간예납"))
    out = {"last": last, "last_year": asof.year - 1, "mid": mid, "year": asof.year, "notes": []}
    C = credits(input_dir, asof.year, base_now, tax_now) if base_now is not None and tax_now is not None else None
    out["credit"] = C
    if last:
        if last.get("장부세전이익") is not None and last.get("과세표준") is not None:
            out["adj"] = last["과세표준"] - last["장부세전이익"]
        if last.get("특별감면") is not None:
            out["notes"].append("작년 받은 감면은 '중소기업 특별세액감면' %s원(산출세액의 %.1f%%)과 '통합고용세액공제' %s원입니다. 창업중소기업 감면은 받지 않았습니다."
                                % (W(last["특별감면"]), last["특별감면"] * 100.0 / (last.get("산출세액") or 1), W(last.get("고용공제"))))
        if last.get("공제이월"):
            out["notes"].append("통합고용 공제는 원래 %s원인데 최저한세 때문에 %s원만 쓰고 %s원은 다음 해로 넘어갔습니다 (10년 안에 쓰면 됨)."
                                % (W((last.get("고용공제") or 0) + last["공제이월"]), W(last.get("고용공제")), W(last["공제이월"])))
        if C:
            out["notes"].append("그래서 올해도 법인세는 최저한세(과세표준의 7%%) %s원까지 내려갑니다%s. 감면 전 %s원보다 %s원 덜 냅니다 (농어촌특별세 %s원 포함 계산)."
                                % (W(C["floor"]) if C["at_floor"] else W(C["final"]), "" if C["at_floor"] else " (최저한세보다 높음)",
                                   W(C["corp"]), W(C["corp"] - C["national"]), W(C["nong"])))
            out["notes"].append("넘어온 공제 %s원 중 올해 %s원을 쓰고 %s원이 또 내년으로 넘어갈 예정입니다. 올해 직원이 늘면 공제가 더 생기지만 최저한세 때문에 세금은 더 줄지 않고 이월만 늘어납니다."
                                % (W(C["avail"]), W(C["used"]), W(C["carry_next"])))
        elif at_min_tax(last):
            out["notes"].append("작년에는 감면·공제를 받고도 세금이 최저한세(과세표준의 7%%)까지만 줄었습니다 — 감면 %s원이 다 쓰이지 못하고 잘렸을 수 있습니다."
                                % W(last["공제감면세액"]))
            if base_now and tax_now:
                floor = int(base_now * MIN_RATE)
                if floor < tax_now:
                    out["floor_now"] = floor
                    out["notes"].append("같은 감면이 올해도 이어지면 올해 법인세는 감면 전 %s원이 아니라 최저한세 %s원 안팎이 됩니다 (약 %s원 덜 냄, 지방소득세는 감면 없이 과세표준의 1%%·0.9%% 구간)."
                                        % (W(tax_now), W(floor), W(tax_now - floor)))
        diff = None
        if last.get("실제납부") is not None and last.get("차감납부세액") is not None:
            diff = last["실제납부"] - last["차감납부세액"]
        if diff and last.get("농특세") is not None and abs(diff - last["농특세"]) < 10:
            out["notes"].append("작년 법인세 실제 납부 %s원이 신고서 차감납부세액 %s원보다 %s원 많은 것은 농어촌특별세(통합고용 공제 %s원 × 20%% = %s원)를 법인세와 함께 낸 것입니다 — 가산세 아님."
                                % (W(last["실제납부"]), W(last["차감납부세액"]), W(diff), W(last.get("고용공제")), W(last["농특세"])))
        elif diff:
            out["notes"].append("작년 법인세 실제 납부 %s원이 신고서 차감납부세액 %s원과 %s원 다릅니다 — 납부서(가산세·수정신고 여부) 확인 필요."
                                % (W(last["실제납부"]), W(last["차감납부세액"]), W(diff)))
        if out.get("adj") is not None:
            out["notes"].append("작년 세무조정으로 과세표준이 장부 세전 이익보다 %s원 %s습니다%s."
                                % (W(abs(out["adj"])), "많았" if out["adj"] >= 0 else "적었",
                                   (" (승용차 감가상각비 한도 넘은 %s원%s)" % (W(last["승용차상각초과"]),
                                    " + 그 밖의 조정 %s원" % W(out["adj"] - last["승용차상각초과"]) if out["adj"] != last["승용차상각초과"] else ""))
                                   if last.get("승용차상각초과") else ""))
        if last.get("승용차상각초과"):
            out["notes"].append("업무용 승용차(%s 취득) 감가상각비 %s원 중 1년 800만 원(산 해는 달 수만큼) 한도를 넘은 %s원은 비용으로 인정되지 않았습니다. 이 몫은 버려지는 게 아니라 나중에 한도 안에서 해마다 비용으로 돌아옵니다."
                                % (last.get("승용차취득일") or "작년", W(last.get("승용차상각비")), W(last["승용차상각초과"])))
    if mid:
        out["notes"].append("올해 중간예납 %s원은 이미 냈고(장부 선납세금에 있음), 내년 3월 낼 법인세에서 빠집니다."
                            % W(mid.get("차감납부세액")))
    return out


def render(T, esc):
    if not T:
        return ""
    h = ["<div class='wsub'>실제 법인세 신고서 (세무사 신고 값)</div>"]
    last = T.get("last")
    if last:
        rows = [("사업연도", last.get("사업연도") or "", "회사가 장사한 기간"),
                ("장부 세전 이익", W(last.get("장부세전이익")), "회사 장부로 계산한 이익"),
                ("+ 세무조정", W(T.get("adj")), "세법 기준과 장부의 차이 (비용 인정 안 되는 것 등)"),
                ("= 과세표준", W(last.get("과세표준")), "세금을 매기는 이익"),
                ("산출세액", W(last.get("산출세액")), "세율을 곱한 세금"),
                ("− 공제·감면", W(last.get("공제감면세액")),
                 ("중소기업 특별세액감면 %s + 통합고용세액공제 %s" % (W(last["특별감면"]), W(last.get("고용공제"))))
                 if last.get("특별감면") is not None else "창업 감면·고용 공제 등으로 줄인 세금"),
                ("= 총부담세액", W(last.get("총부담세액")), "실제로 내야 할 법인세" + (" (최저한세 7%에 걸림)" if at_min_tax(last) else "")),
                ("− 기납부세액", W(last.get("기납부세액")), "이자에서 미리 떼인 세금·중간예납"),
                ("= 차감납부세액", W(last.get("차감납부세액")), "3월에 낸 법인세"),
                ("지방소득세", W(last.get("지방소득세")), "구청에 4월에 낸 세금 (감면 없이 따로 계산)")]
        if last.get("농특세"):
            rows.insert(9, ("+ 농어촌특별세", W(last["농특세"]), "고용 공제로 줄인 세금의 20%, 법인세와 같이 냄"))
        h.append("<table class='pt tx'><thead><tr><th>%d년 신고 (%s 신고)</th><th>금액</th><th>쉬운 뜻</th></tr></thead><tbody>%s</tbody></table>"
                 % (T["last_year"], esc(last.get("신고일") or ""),
                    "".join("<tr><td style='text-align:left'>%s</td><td>%s</td><td style='text-align:left'>%s</td></tr>" % (esc(a), esc(b), esc(c))
                            for a, b, c in rows)))
    C = T.get("credit")
    if C:
        rows = [("산출세액", W(C["corp"]), "올해 과세표준에 세율을 곱한 세금"),
                ("− 중소기업 특별세액감면", W(C["sp"]), "작년과 같은 비율(산출세액의 %.1f%%)" % (C["sp_rate"] * 100)),
                ("− 통합고용세액공제 (넘어온 몫)", W(C["used"]), "%d년에서 넘어온 %s원 중 쓸 수 있는 만큼" % (C["last_year"], W(C["avail"]))),
                ("= 법인세", W(C["final"]), "최저한세 %s원%s" % (W(C["floor"]), " 까지 내려감" if C["at_floor"] else "보다 높음")),
                ("+ 농어촌특별세", W(C["nong"]), "고용 공제로 줄인 세금의 20%"),
                ("= 낼 법인세 합", W(C["national"]), "이 금액에서 중간예납을 빼고 내년 3월에 냄"),
                ("내년으로 넘어갈 공제", W(C["carry_next"]), "10년 안에 쓰면 됨")]
        h.append("<table class='pt tx'><thead><tr><th>%d년 법인세 예상 (감면·공제 적용)</th><th>금액</th><th>쉬운 뜻</th></tr></thead><tbody>%s</tbody></table>"
                 % (T["year"], "".join("<tr><td style='text-align:left'>%s</td><td>%s</td><td style='text-align:left'>%s</td></tr>" % (esc(a), esc(b), esc(c))
                                      for a, b, c in rows)))
    mid = T.get("mid")
    if mid:
        h.append("<div class='note'>%s</div>" % esc("%d년 중간예납 (%s 신고): 작년 법인세 %s원 × 6/12 = %s원 납부"
                                                     % (T["year"], mid.get("신고일") or "", W((last or {}).get("차감납부세액")), W(mid.get("차감납부세액")))))
    if T["notes"]:
        h.append("<div class='note'><b>올해 예상에 주는 뜻</b><br>%s</div>" % "<br>".join("· " + esc(x) for x in T["notes"]))
    return "".join(h)
