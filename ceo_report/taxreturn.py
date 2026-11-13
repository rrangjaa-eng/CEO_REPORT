"""실제 법인세 신고서 값 (사용자 2026-11-13: 2025 법인세 신고서·2026 중간예납 신고서 제공).

입력/법인세신고.csv 한 줄 = 신고서 한 장. 프로그램 예상(장부로 어림)과 나란히 보여 주고,
작년 신고에서 배운 것(세무조정 크기, 감면이 최저한세에 걸렸는지)을 올해 예상에 참고로 붙인다.
"""
import csv
import os

FILE = "법인세신고.csv"
COLUMNS = ["연도", "구분", "사업연도", "수입금액", "장부세전이익", "과세표준", "산출세액", "공제감면세액", "총부담세액",
           "기납부세액", "차감납부세액", "지방소득세", "실제납부", "결산확정일", "신고일", "조정"]
MIN_RATE = 0.07   # 중소기업 최저한세율 (taxlaw 값이 있으면 그것)


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
            for k in COLUMNS[3:13]:
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


def for_report(input_dir, asof, base_now=None, tax_now=None):
    """경영관리 법인세 장에 붙일 dict 또는 None (신고서 파일 없음)."""
    D = load(input_dir)
    if not D:
        return None
    last = D.get((asof.year - 1, "확정"))
    mid = D.get((asof.year, "중간예납"))
    out = {"last": last, "last_year": asof.year - 1, "mid": mid, "year": asof.year, "notes": []}
    if last:
        if last.get("장부세전이익") is not None and last.get("과세표준") is not None:
            out["adj"] = last["과세표준"] - last["장부세전이익"]
        if at_min_tax(last):
            out["notes"].append("작년에는 감면·공제를 받고도 세금이 최저한세(과세표준의 7%%)까지만 줄었습니다 — 감면 %s원이 다 쓰이지 못하고 잘렸을 수 있습니다."
                                % W(last["공제감면세액"]))
            if base_now and tax_now:
                floor = int(base_now * MIN_RATE)
                if floor < tax_now:
                    out["floor_now"] = floor
                    out["notes"].append("같은 감면이 올해도 이어지면 올해 법인세는 감면 전 %s원이 아니라 최저한세 %s원 안팎이 됩니다 (약 %s원 덜 냄, 지방소득세는 감면 없이 과세표준의 1%%·0.9%% 구간)."
                                        % (W(tax_now), W(floor), W(tax_now - floor)))
        if last.get("실제납부") is not None and last.get("차감납부세액") is not None and last["실제납부"] != last["차감납부세액"]:
            out["notes"].append("작년 법인세 실제 납부 %s원이 신고서 차감납부세액 %s원과 %s원 다릅니다 — 납부서(가산세·수정신고 여부) 확인 필요."
                                % (W(last["실제납부"]), W(last["차감납부세액"]), W(last["실제납부"] - last["차감납부세액"])))
        if out.get("adj") is not None:
            out["notes"].append("작년 세무조정으로 과세표준이 장부 세전 이익보다 %s원 %s습니다. 올해 프로그램의 세무조정 예상과 크기를 견주어 보세요."
                                % (W(abs(out["adj"])), "많았" if out["adj"] >= 0 else "적었"))
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
                ("− 공제·감면", W(last.get("공제감면세액")), "창업 감면·고용 공제 등으로 줄인 세금"),
                ("= 총부담세액", W(last.get("총부담세액")), "실제로 내야 할 법인세" + (" (최저한세 7%에 걸림)" if at_min_tax(last) else "")),
                ("− 기납부세액", W(last.get("기납부세액")), "이자에서 미리 떼인 세금·중간예납"),
                ("= 차감납부세액", W(last.get("차감납부세액")), "3월에 낸 법인세"),
                ("지방소득세", W(last.get("지방소득세")), "구청에 4월에 낸 세금 (감면 없이 따로 계산)")]
        h.append("<table class='pt tx'><thead><tr><th>%d년 신고 (%s 신고)</th><th>금액</th><th>쉬운 뜻</th></tr></thead><tbody>%s</tbody></table>"
                 % (T["last_year"], esc(last.get("신고일") or ""),
                    "".join("<tr><td style='text-align:left'>%s</td><td>%s</td><td style='text-align:left'>%s</td></tr>" % (esc(a), esc(b), esc(c))
                            for a, b, c in rows)))
    mid = T.get("mid")
    if mid:
        h.append("<div class='note'>%s</div>" % esc("%d년 중간예납 (%s 신고): 작년 법인세 %s원 × 6/12 = %s원 납부"
                                                     % (T["year"], mid.get("신고일") or "", W((last or {}).get("차감납부세액")), W(mid.get("차감납부세액")))))
    if T["notes"]:
        h.append("<div class='note'><b>올해 예상에 주는 뜻</b><br>%s</div>" % "<br>".join("· " + esc(x) for x in T["notes"]))
    return "".join(h)
