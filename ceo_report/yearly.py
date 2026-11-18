"""해가 바뀔 때 손볼 것 (2차 전수조사 P9·P10·D5·V10, 2026-11-18).

세법 기준·공휴일·오차범위 표처럼 해마다 다시 봐야 하는 값과, 1~3월에만 필요한 일(지난해 분개장 다시 받기, 인트라넷 지난해
자료 확인)을 12월 1일 ~ 3월 31일 사이 경영관리 '할 일'에 띄운다. 이미 끝난 일(새 해 세법 기준을 다 확인함, 새 해 팀 목표를
넣음)은 띄우지 않는다. 대표·팀장 보고에는 싣지 않는다.

items(R) -> [{"level", "area", "fact", "action", "due"}] (calc.risks 와 같은 모양).
"""
import datetime as dt
import os


def window(asof):
    """(새 해, 철) — 12월이면 (내년, '준비'), 1~3월이면 (올해, '새 해'). 그 밖은 None."""
    if asof.month == 12:
        return asof.year + 1, "준비"
    if asof.month <= 3:
        return asof.year, "새 해"
    return None


def _last_year_projects(R, year):
    """프로젝트 자료에 든 지난해 프로젝트 수 (번호 앞 두 자리 또는 행사일이 지난해). 자료가 없으면 None."""
    ps = (R.get("s3") or {}).get("projects")
    if ps is None:
        return None
    from .calc import _event_date
    yy = "%02d" % ((year - 1) % 100)
    n = 0
    for P in ps:
        ev = _event_date(P.get("event_date"))
        if str(P.get("id") or "").startswith(yy) or (ev is not None and ev.year == year - 1):
            n += 1
    return n


def items(R):
    asof = R.get("asof")
    w = window(asof) if isinstance(asof, dt.date) else None
    if not w:
        return []
    year, season = w
    input_dir = R.get("input_dir")
    out = []

    def add(fact, action, due, level="중간"):
        out.append({"level": level, "area": "자료", "fact": "해 바뀜 준비 — " + fact, "action": action, "due": due})

    jan_end, mar_end = dt.date(year, 1, 31), dt.date(year, 3, 31)
    # ① 세법 기준: 새 해 값이 프로그램에 없거나 확인 안 한 항목이 있으면
    try:
        from . import taxlaw
        if input_dir:
            st = taxlaw.status(input_dir, year)
            if st["todo"] or not st["known"]:
                add("%d년 세법 기준 %s." % (year, "값이 프로그램에 아직 없음 (%d년 값까지 있음)" % taxlaw.LATEST if not st["known"]
                                       else "미확인 %d개" % len(st["todo"])),
                    "창 '가끔 넣는 값 → 세법 기준'에서 %d년 값을 확인해 넣으세요 (최신 법령 확인 단추 먼저). 확인 전에는 세금·급여 계산에 "
                    "%d년 값을 그대로 쓰지 않고 '미확인'으로 둡니다." % (year, year), jan_end)
    except Exception:
        pass
    # ② 공휴일: 정부 발표(월력요항)와 대조한 해가 새 해보다 앞이면
    from . import tax
    if tax.HOLIDAY_CHECKED < year:
        add("%d년 공휴일을 정부 발표와 아직 대조하지 않음 (%d년까지 대조함)." % (year, tax.HOLIDAY_CHECKED),
            "급여일·카드 결제일·신고 기한이 하루씩 어긋날 수 있습니다. 프로그램을 새로 받으세요 (공휴일 표는 프로그램 안에 있음).", jan_end, "낮음")
    # ③ 새 해 팀 목표
    try:
        from . import targets
        if input_dir and not any(y == str(year) and (v.get("revenue") or v.get("rate") is not None)
                                 for (y, _), v in targets.read(input_dir).items()):
            add("%d년 팀 목표(매출·수익률)가 아직 없음." % year,
                "창 '가끔 넣는 값 → 팀 목표'에 %d년 목표를 넣으세요. 없으면 추정 예산·목표 대비가 기본값으로 계산됩니다." % year, jan_end)
    except Exception:
        pass
    if season == "새 해":
        # ④ 지난해 분개장: 결산 전표가 1~3월에 들어가므로 다시 받아야 한다 (D5)
        add("%d년 결산 전표는 1~3월에 들어갑니다 — 위하고 확장은 열려 있는 해의 분개장만 받습니다." % (year - 1),
            "위하고에서 회계연도를 %d년으로 바꿔 분개장을 다시 받고 '자료 변환'을 하세요 (결산이 끝날 때까지 받을 때마다). "
            "받지 않으면 %d년 감가상각비·법인세·이익잉여금이 결산 전 값으로 남습니다." % (year - 1, year - 1), mar_end)
        # ⑤ 인트라넷: 목록이 '올해'만 보여 주면 지난해 프로젝트·지급요청이 빠진다 (P9)
        n = _last_year_projects(R, year)
        if n is not None:
            add("프로젝트 자료에 %d년 프로젝트 %d건%s." % (year - 1, n, " — 지난해 것이 하나도 없음" if n == 0 else ""),
                "인트라넷 수집이 %d년 프로젝트·지급요청도 받았는지 확인하세요 (목록의 연도를 %d년으로 바꿔 한 번 더 수집). "
                "빠지면 남은 예산·아직 안 준 요청이 보고에서 사라집니다." % (year - 1, year - 1), jan_end, "높음" if n == 0 else "중간")
        # ⑥ 오차범위 표: 잰 날이 지난해면
        from . import guides
        measured = getattr(guides, "MEASURED", None)
        if measured is not None and measured.year < year:
            add("'보고 숫자를 얼마나 믿나(오차범위)' 표는 %s에 잰 값." % measured.isoformat(),
                "새 해 장부가 두세 달 쌓이면 다시 재야 합니다 (프로그램 업데이트 때 함께).", mar_end, "낮음")
    return out
