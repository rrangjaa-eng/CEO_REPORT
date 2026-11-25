"""보고끼리 숫자 맞춰 보기 (2차 전수조사 제안 8, 2026-11-18).

같은 값(법인세 예상, 누적 세전 이익·순이익, 오늘 쓸 수 있는 돈, 입금일 지난 미수금)이 보고마다 다르게 나온 일이 가장 많았다.
보고를 만들 때마다 그 보고의 핵심 숫자를 출력\\자동분석기록\\숫자대조_<기준일>.json 에 적고, 같은 기준일·같은 자료 변환으로 만든
다른 보고의 숫자와 다르면 경영관리 보고 맨 위와 창 기록에 알린다. 대표·팀장 보고에는 넣지 않는다.

키 이름에 기간을 넣는다 ('법인세 낼 돈 (1~10월 이익 기준)') — 기간이 다른 값끼리는 견주지 않는다.
"""
import datetime as dt
import html
import json
import os

DIR = "자동분석기록"
KIND_NAME = {"weekly": "주간 보고", "monthly": "월간 보고", "annual": "연간 보고", "budget": "예산", "planbs": "기획본부 재무상태표"}


def _path(output_dir, asof):
    return os.path.join(output_dir, DIR, "숫자대조_%s.json" % asof.isoformat())


def _load(output_dir, asof):
    try:
        with open(_path(output_dir, asof), encoding="utf-8") as f:
            S = json.load(f)
        return S if isinstance(S, dict) else {}
    except (OSError, ValueError):
        return {}


def conv_stamp(input_dir):
    """이 숫자를 만든 자료 변환 시각 (글). 모르면 ''."""
    from . import gate
    try:
        when = gate.conv_time(input_dir)[0]
    except Exception:
        when = None
    return when.strftime("%Y-%m-%d %H:%M:%S") if when else ""


def _tax_rows(R, year):
    from .tax import REST_MARK
    main = local = None
    rest = rest_local = 0
    m = None
    for t in R.get("tax") or []:
        per = str(t.get("period") or "")
        if t.get("kind") not in ("법인세", "법인지방소득세") or not per.startswith("%d년 " % year):
            continue
        if per.startswith("%d년 (1월~" % year):
            if t["kind"] == "법인세":
                main, m = t, per.split("(1월~")[1].split("월")[0]
            else:
                local = t
        elif per.endswith(REST_MARK) and t.get("amount") is not None:
            if t["kind"] == "법인세":
                rest += t["amount"]
            else:
                rest_local += t["amount"]
    return main, local, rest, rest_local, m


def from_calc(R, pack=None):
    """주간·월간 계산(R)과 월간 누적 묶음(pack = render.annual_pack) -> {키: 값}. 자료 확인에서 막혀 비운 값은 넣지 않는다."""
    out = {}
    asof = R["asof"]
    main, local, rest, rest_local, m = _tax_rows(R, asof.year)
    if main is not None and main.get("amount") is not None and m:
        out["법인세 낼 돈 (1~%s월 이익 기준)" % m] = int(main["amount"])
        out["법인세 낼 돈 (%d년 연말 예상)" % asof.year] = int(main["amount"] + rest)
        if local is not None and local.get("amount") is not None:
            out["지방소득세 낼 돈 (1~%s월 이익 기준)" % m] = int(local["amount"])
            out["지방소득세 낼 돈 (%d년 연말 예상)" % asof.year] = int(local["amount"] + rest_local)
    s2 = R.get("s2") or {}
    if s2.get("start") is not None:
        out["오늘 쓸 수 있는 돈"] = int(s2["start"])
    s5 = R.get("s5") or {}
    if s5.get("overdue_total") is not None:   # 대표 보고 첫 줄 '입금일 지난 미수금' 칸과 같은 값
        out["입금일 지난 미수금"] = int(s5["overdue_total"])
    if pack and pack.get("E") and pack["N"].get("pretax") is not None:
        mm = int(pack["ym"][5:])
        E, N = pack["E"], pack["N"]
        out["세전 이익 (1~%d월)" % mm] = int(N["pretax"])
        out["순이익 예상 (1~%d월)" % mm] = int(N["pretax"] - E["nat"] - E["local"])
        if E.get("pay") is not None:
            out["법인세 낼 돈 (1~%d월 이익 기준)" % mm] = int(E["pay"])
        out["지방소득세 낼 돈 (1~%d월 이익 기준)" % mm] = int(E["local_pay"])
    return out


def from_annual(A):
    """연간 계산(A) -> {키: 값}. 결산 법인세가 장부에 들어온 해(tax_fixed)는 예상과 견줄 것이 없다."""
    out = {}
    Yp, cut = A.get("Y"), A.get("cut")
    if not Yp or not cut or not A.get("tax_same"):
        return out
    out["세전 이익 (1~%d월)" % cut] = int(Yp["pre"])
    if Yp.get("net") is not None:
        out["순이익 예상 (1~%d월)" % cut] = int(Yp["net"])
    if A.get("prepaid") is not None and A.get("corp") is not None:
        out["법인세 낼 돈 (1~%d월 이익 기준)" % cut] = int(max(A["corp"] - A["prepaid"], 0))
    if A.get("local") is not None:
        out["지방소득세 낼 돈 (1~%d월 이익 기준)" % cut] = int(max(A["local"] - (A.get("local_paid") or 0), 0))
    return out


def from_budget(B):
    """예산(B) -> {키: 값}: 올해분 법인세·지방소득세 (3/31·5/31 분납·4/30)."""
    out = {}
    base = B.get("base")
    if not B.get("tax_shared"):
        return out
    corp = [f["amount"] for f in B.get("fix") or [] if str(f.get("name") or "").startswith("법인세") and "(%d년분)" % base in str(f.get("name"))
            and "중간예납" not in str(f.get("name"))]
    loc = [f["amount"] for f in B.get("fix") or [] if str(f.get("name") or "").startswith("지방소득세 (%d년분)" % base)]
    if corp and all(v is not None for v in corp):
        out["법인세 낼 돈 (%d년 연말 예상)" % base] = int(sum(corp))
    if loc and all(v is not None for v in loc):
        out["지방소득세 낼 돈 (%d년 연말 예상)" % base] = int(sum(loc))
    return out


def compare(output_dir, asof, kind, values, stamp=""):
    """이 보고의 숫자를 같은 기준일·같은 변환으로 만든 다른 보고의 숫자와 견준다 -> [(키, 이 값, 다른 보고 이름, 그 값)].
    그다음 이 보고의 숫자를 기록한다 (쓰지 못해도 보고는 계속)."""
    S = _load(output_dir, asof)
    diffs = []
    for other, rec in sorted(S.items()):
        if other == kind or not isinstance(rec, dict) or (rec.get("conv") or "") != (stamp or ""):
            continue
        for k, v in sorted((rec.get("values") or {}).items()):
            if k in values and isinstance(v, (int, float)) and abs(values[k] - v) > 1:
                diffs.append((k, values[k], KIND_NAME.get(other, other), int(v)))
    S[kind] = {"conv": stamp or "", "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "values": values}
    try:
        os.makedirs(os.path.join(output_dir, DIR), exist_ok=True)
        tmp = _path(output_dir, asof) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(S, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _path(output_dir, asof))
    except OSError:
        pass
    return diffs


def lines(diffs, kind):
    me = KIND_NAME.get(kind, kind)
    return ["%s: 이 %s %s원 ↔ %s %s원 (차이 %s원)" % (k, me, format(a, ","), other, format(b, ","), format(a - b, ",")) for k, a, other, b in diffs]


def banner(diffs, kind):
    """경영관리 보고 맨 위 경고 (없으면 '')."""
    if not diffs:
        return ""
    return ("<div class='xcheck' style='border:2px solid #c62828;background:#ffebee;color:#7f0000;border-radius:8px;padding:10px 14px;margin:8px 0'>"
            "<b>보고끼리 숫자가 다릅니다 (%d건)</b> — 같은 기준일·같은 자료로 만든 다른 보고와 맞춰 본 결과입니다. 어느 쪽이 맞는지 확인하세요."
            "<ul style='margin:6px 0 0 18px;padding:0'>%s</ul></div>"
            % (len(diffs), "".join("<li>%s</li>" % html.escape(x) for x in lines(diffs, kind))))
