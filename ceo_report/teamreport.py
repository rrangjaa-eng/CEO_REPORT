"""팀장용 월간 실적 문서 (사용자 2026-11-05 목업, 2026-11-09 승인).

대표가 아니라 그 팀 팀장이 보는 문서: 그 팀 숫자만, 회사 문서 모양(제목·수신/작성 표·격자 표·단위 원·음수 △·- 끝 -).
- 급여 금액은 어디에도 쓰지 않는다. 판관비는 급여를 뺀 팀 판관비만, '팀 급여 제외'를 문서 위·표 제목·작성 기준에 적는다.
- 급여 반영 손익(매출총이익 − 판관비 − 급여)은 금액 없이 흑자/적자로만, 설정.csv '팀장용_급여반영손익' = 표시 일 때만 (기본 숨김).
- 수익률 = 매출총이익 ÷ 매출 (판관비 빼기 전). 매출·매출원가는 손익.csv WEHAGO 팀 줄(분개장 부서명, 전표일자 기준).
- 프로젝트별은 손익.csv WEHAGO 프로젝트 줄을 프로젝트 목록의 팀으로 묶는다. 팀 합계와 다르면 그 차이를 한 줄로 따로 보인다.
- 진행·예정 프로젝트: 사전견적 · 추정 예산(팀 목표 수익률 기준, calc) · 집행액 · 잔여(추정 예산 − 집행액) · 쓸 수 있는 남은 예산
  (추정 예산 − 쓴 돈·요청·계획, 2026-11-14 T5). 원가율 숫자는 쓰지 않는다.
- 문서 머리에 계산에 쓴 자료의 날짜 한 줄 ('사용한 자료: 분개장 날짜 · 자금계획서 날짜', 사용자 2026-11-14 결정. 11/5 '출처 문구 없음'을 바꿈).
모르는 값은 0이 아니라 '미확인'.
"""
import datetime as dt
import html
import os
import re

from .calc import _event_date, is_closed

NET_SETTING = "팀장용_급여반영손익"   # '표시' 이면 급여 반영 손익(흑자/적자) 줄·칸을 보인다 (사용자 2026-11-05 보류)
LOW_GAP = 4.0   # 누계 프로젝트 수익률이 팀 목표 수익률보다 이만큼(%p) 이상 낮으면 밑줄


def esc(v):
    from .util import esc as _esc   # 주민번호 모양은 가린다 (2026-11-14 코덱스 검토)
    return _esc("" if v is None else str(v))


def W(v):
    """원 단위 금액. None 은 미확인, 음수는 △."""
    if v is None:
        return "미확인"
    s = "{:,}".format(abs(int(round(v))))
    return ("△" + s) if v < 0 else s


def P(a, b):
    if a is None or b is None:
        return "미확인"
    if not b:
        return "-"
    v = a * 100.0 / b
    # 1차 C5 (2026-11-18): 금액은 △인데 비율만 '-7.6%' 였음 → 음수는 금액과 같게 △
    return ("△%.1f%%" % abs(v)) if round(v, 1) < 0 else "%.1f%%" % abs(v)


def _dots(text):
    """날짜 글자를 이 문서 머리와 같은 2026.01.10 모양으로 (1차 C5: 2026-01-10 과 2026.04.06 이 섞임)."""
    return re.sub(r"(\d{4})-(\d{1,2})-(\d{1,2})", lambda m: "%s.%02d.%02d" % (m.group(1), int(m.group(2)), int(m.group(3))), str(text or ""))


def _sub(a, b):
    return None if a is None or b is None else a - b


def _sum(vals):
    vals = list(vals)
    return None if any(v is None for v in vals) else sum(vals)


def _months(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return ["%04d-%02d" % (y, i) for i in range(1, m + 1)]


def _prev(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return "%04d-%02d" % ((y, m - 1) if m > 1 else (y - 1, 12))


def _mlabel(ym):
    return "%d월" % int(ym[5:7])


def _pid(target):
    """손익.csv 프로젝트 줄의 대상 'P26201 A사 연례 컨퍼런스' -> 'P26201'. 미연결 줄은 None."""
    t = (target or "").strip()
    if not t or "미연결" in t:
        return None
    return t.split()[0]


def team_names(d):
    """보고서를 만들 팀: 손익.csv WEHAGO 팀 줄과 부서비용.csv 의 '…팀' 부서 (팀 미지정 등 제외), 이름순."""
    names = set()
    for r in d.pl or []:
        if r["source"] == "WEHAGO" and r["unit"] == "팀":
            names.add((r["target"] or "").strip())
    for r in d.dept or []:
        names.add((r["dept"] or "").strip())
    return sorted(n for n in names if n.endswith("팀") and n not in ("팀 미지정", "팀 미확인"))


# 2차 전수조사 P4: '잡급'이 빠져 있어 그 계정 금액이 팀장 보고 판관비에 보일 수 있었음. 낱말은 codes.py 와 같이 둔다
PAY_ACCOUNT_WORDS = ("퇴직급여", "퇴직연금", "상여", "제수당", "임원급여", "급료", "임금", "잡급")


def _is_pay_account(name):
    """급여성 계정 (팀장용에서 금액을 보이지 않는 계정). 급여(80200)는 부서비용에서 이미 따로라 여기 없음."""
    n = "".join(str(name or "").split())
    return any(w in n for w in PAY_ACCOUNT_WORDS)


def build(d, R, team):
    """팀 하나의 숫자 묶음. R 은 calc.compute(…, 'monthly', …) 결과."""
    ym = R["s4"]["ym"]
    year = ym[:4]
    months = _months(ym)
    pl = [r for r in (d.pl or []) if r["source"] == "WEHAGO" and r["ym"][:4] == year]
    company_months = set(r["ym"] for r in pl if r["unit"] == "회사")

    def team_cell(m, key):
        rows = [r for r in pl if r["unit"] == "팀" and r["ym"] == m and (r["target"] or "").strip() == team]
        if rows:
            return _sum(r[key] for r in rows)
        return 0 if m in company_months else None   # 회사 줄이 있는 달에 팀 줄이 없으면 그 달 팀 전표 없음

    dept = [r for r in (d.dept or []) if "".join(str(r["dept"] or "").split()) == "".join(team.split())]   # 띄어쓰기 달라도 같은 부서
    dept_months = set(r["ym"] for r in (d.dept or []))

    def dept_cell(m, key):
        rows = [r for r in dept if r["ym"] == m]
        if rows:
            return _sum(r[key] for r in rows)
        return 0 if (key != "heads" and m in dept_months) else None

    # 11/17 전수 점검 F11: 퇴직급여·상여 같은 급여성 계정은 부서비용 '판관비'에 들어 있지만 팀장용엔 급여 금액을 어디에도 보이지 않는다
    # (사용자 2026-11-05) — 퇴사자 한 사람의 퇴직금이 판관비 표에 그대로 보였음. 판관비·이익·계정 표에서 모두 뺀다
    pay_by = {}
    for r in getattr(d, "dept_accounts", None) or []:
        if "".join(str(r["dept"] or "").split()) == "".join(team.split()) and _is_pay_account(r["account"]) and r["amount"]:
            pay_by[r["ym"]] = pay_by.get(r["ym"], 0) + r["amount"]
    M = []
    for m in months:
        rev, cost = team_cell(m, "revenue"), team_cell(m, "direct")
        gp = _sub(rev, cost)
        sga = _sub(dept_cell(m, "sga"), pay_by.get(m, 0)) if d.dept is not None else None
        sal = dept_cell(m, "salary") if d.dept is not None else None
        op = _sub(gp, sga)
        M.append({"ym": m, "revenue": rev, "cost": cost, "gp": gp, "sga": sga, "op": op,
                  "net": _sub(op, sal), "heads": dept_cell(m, "heads") if d.dept is not None else None})
    # 11/17 전수 점검 F1: 급여 전인 달(달 중간에 만든 이번 달)은 인원 '급여 전'으로, 평균은 급여 들어온 달만
    from .teamprofit import paid_months
    paid = paid_months(d.dept) if d.dept is not None else set()
    # 2차 전수조사 A2 (2026-11-18): 달 중간에 만든 월간이면 이번 달은 '마감 전' — 원가·판관비 전표가 덜 들어와 이익이 좋게 보인다.
    # 이번 달은 매출만 보이고, 누계·달성률·누계 프로젝트·판관비 누계는 다 끝난 달까지 (연간 팀장 보고와 같은 기간).
    # '올해 예상'만 오늘까지 장부(tot_all)에서 이어 간다 (남은 매출·남은 원가가 오늘 기준이라)
    open_ = bool(R["s4"].get("open"))
    for x in M:
        x["unpaid"] = d.dept is not None and x["ym"] not in paid
        x["open"] = open_ and x["ym"] == ym
    Mc = [x for x in M if not x["open"]]
    months_c = [x["ym"] for x in Mc]
    tot_all = {k: _sum(x[k] for x in M) for k in ("revenue", "cost", "gp", "sga", "op", "net")}
    tot = {k: _sum(x[k] for x in Mc) for k in ("revenue", "cost", "gp", "sga", "op", "net")}
    hs = [x["heads"] for x in Mc if not x["unpaid"]]
    tot["heads"] = None if not hs or any(h is None for h in hs) else sum(hs) / float(len(hs))
    cum, run = [], 0
    for x in Mc:
        run = None if run is None or x["gp"] is None else run + x["gp"]
        cum.append(run)

    tg = (getattr(d, "team_targets", None) or {}).get((year, team)) or {}
    t_rev = tg.get("revenue")
    t_rate = tg.get("rate")
    t_gp = None if t_rev is None or t_rate is None else int(round(t_rev * t_rate / 100.0))

    comp = [r for r in pl if r["unit"] == "회사" and r["ym"] in months_c]
    c_rev, c_cost = _sum(r["revenue"] for r in comp), _sum(r["direct"] for r in comp)
    company_rate = None if not comp or c_rev in (None, 0) or c_cost is None else (c_rev - c_cost) * 100.0 / c_rev

    projects = d.projects or {}
    per = {}
    for r in pl:
        if r["unit"] != "프로젝트" or r["ym"] not in months:
            continue
        pid = _pid(r["target"])
        if pid is None or (projects.get(pid, {}).get("team") or "").strip() != team:
            continue
        per.setdefault(pid, {}).setdefault(r["ym"], [0, 0])
        c = per[pid][r["ym"]]
        c[0] = None if c[0] is None or r["revenue"] is None else c[0] + r["revenue"]
        c[1] = None if c[1] is None or r["direct"] is None else c[1] + r["direct"]

    def prow(pid, sel):
        p = projects.get(pid, {})
        cells = [v for m, v in per[pid].items() if m in sel]
        rev, cost = _sum(c[0] for c in cells), _sum(c[1] for c in cells)
        used = sorted(m for m, v in per[pid].items() if m in sel and (v[0] or v[1]))
        span = "" if not used else (_mlabel(used[0]) if used[0] == used[-1] else "%s~%s" % (_mlabel(used[0]), _mlabel(used[-1])))
        return {"id": pid, "name": p.get("name", ""), "client": p.get("client", ""), "event": p.get("event_date", ""),
                "months": span, "revenue": rev, "cost": cost, "gp": _sub(rev, cost)}

    def ev_key(r):
        e = _event_date(r["event"])
        return (e or dt.date.max, r["id"])

    cur = sorted([prow(pid, {ym}) for pid in per if ym in per[pid]], key=ev_key)
    cur = [r for r in cur if r["revenue"] or r["cost"]]
    ytd = sorted([prow(pid, set(months_c)) for pid in per], key=ev_key)
    ytd = [r for r in ytd if r["revenue"] or r["cost"]]

    def gap(rows, rev, cost):
        if rev is None or cost is None:
            return None
        pr, pc = _sum(r["revenue"] for r in rows), _sum(r["cost"] for r in rows)
        if pr is None or pc is None:
            return None
        g = {"revenue": rev - pr, "cost": cost - pc}
        g["gp"] = g["revenue"] - g["cost"]
        return g if (g["revenue"] or g["cost"]) else None

    last = M[-1]
    cur_gap = gap(cur, last["revenue"], last["cost"])
    ytd_gap = gap(ytd, tot["revenue"], tot["cost"])

    # 진행·예정 프로젝트와 올해 매출·이익 예상 (2026-11-14 오후 점검 T2·T3·T5, P2·K1)
    # · 올해 매출 예상 = 누계 매출 + 프로젝트별 '아직 매출로 안 잡힌 금액'(사전견적 − 매출반영누계, calc.revenue_left —
    #   대표 월간·예산과 같은 계산). 예전엔 매출이 조금이라도 잡힌 프로젝트의 남은 매출이 통째로 빠짐 (T3)
    # · 이익 예상에 더하는 몫 = 남은 매출 − 남은 원가. 남은 원가 = 추정 예산(등록 지출이 넘으면 그 금액, 1차 N1) − 올해 이미 장부에 잡힌 원가 (0 밑은 0, T2: 예전엔
    #   먼저 잡힌 계약금·대관료가 누계 원가와 추정 예산 양쪽에서 두 번 빠짐). 끝난 프로젝트(대표 승인)는 남은 원가 0
    # · 진행·예정 표: 끝나지 않은 올해 행사. 잔여 = 추정 예산 − 집행액 (11/9 정의 그대로), 쓸 수 있는 남은 예산 = 추정 예산 −
    #   (쓴 돈 + 요청 + 카드 미결제 + 계획) (T5, 사용자 승인)
    from .calc import revenue_left, left_basis
    booked = {pid: _sum(c[1] for c in per[pid].values()) for pid in per}
    # 11/18: 연간 팀장 보고처럼 손익을 끝난 달까지만 볼 때, 그 뒤 달에 이미 장부에 잡힌 원가(끝난 프로젝트)를 남은 원가로 —
    # 예전엔 끝난 프로젝트 남은 원가를 0으로 봐 11월에 잡힌 원가가 빠져 연간(5.07억)이 월간(5.02억)보다 크게 나왔음
    after = {}
    for r in pl:
        if r["unit"] == "프로젝트" and r["ym"] > ym:
            pid = _pid(r["target"])
            if pid is not None:
                after[pid] = None if (after.get(pid, 0) is None or r["direct"] is None) else after.get(pid, 0) + r["direct"]
    up, add_rev, add_gp, miss_rev, miss_gp, closed_left = [], 0, 0, 0, 0, 0
    prior_rev, prior_n = 0, 0
    for P_ in R["s3"]["projects"]:
        if (P_.get("team") or "").strip() != team or (P_.get("state") or "").strip() == "완료(예전 인트라넷)":
            continue
        e = _event_date(P_.get("event_date"))
        if e is None or e.year > int(year):
            continue
        closed = is_closed(P_)
        left_rev = revenue_left(P_)
        if e.year < int(year):
            # 사용자 결정 ③ (2026-11-16 카드): 작년 이전 행사라도 아직 장부 매출로 안 잡힌 금액은 올해 장부에 잡힐 매출 →
            # 올해 매출 예상에 넣는다 (대표 월간 '앞으로 잡힐 매출'·예산과 같은 계산). 진행·예정 표(올해 행사)엔 넣지 않는다.
            # 이익: 끝난 프로젝트는 남은 원가 0이라 남은 매출 그대로, 안 끝난 것은 작년 원가를 이 표가 몰라 '미확인'
            if left_rev == 0 or (left_rev is None and left_basis(P_) is None):
                continue
            if left_rev is None:
                miss_rev += 1
                miss_gp += 1
                continue
            add_rev += left_rev
            prior_rev += left_rev
            prior_n += 1
            if closed and not P_.get("unknown_cost"):
                add_gp += left_rev
            else:
                miss_gp += 1
            continue
        cost_done = booked.get(P_["id"], 0)
        if closed:
            # 1차 B13 (2026-11-15): 끝난 프로젝트라도 금액 미확인 원가가 있으면 이익을 모른다 — 예전엔 0으로 보고 '이익 미확인 0건'
            rem_cost = None if (P_.get("unknown_cost") or after.get(P_["id"], 0) is None) else max(after.get(P_["id"], 0), 0)
        elif P_.get("budget") is None or cost_done is None:
            rem_cost = None
        else:
            # 1차 점검 N1·B2 (2026-11-15): 예산을 넘은 등록 지출(장부 전 지급요청·카드·계획)도 나갈 원가다 — 지금 예상 이익
            # (profit_now)과 같은 식 '추정 예산과 등록 지출 중 큰 쪽'. 예전엔 예산까지만 빼 예시 A사 이익을 2,820만 크게 보였음.
            # 금액 미확인 줄이 있으면 아는 금액까지만 더한다 (T4: 미확인 한 줄로 이익 예상이 빠지거나 커지지 않게)
            com = P_.get("committed")
            if com is None:
                com = (P_.get("expected") or 0) + (P_.get("intranet_req") or 0)
            rem_cost = max(max(P_["budget"], com) - cost_done, 0)
        if left_rev is None:
            miss_rev += 1
        else:
            add_rev += left_rev
        if left_rev is None or rem_cost is None:
            miss_gp += 1
        else:
            add_gp += left_rev - rem_cost
        if closed:
            closed_left += left_rev or 0
            continue
        paid = None if P_.get("unknown_cost") else P_.get("paid_total")   # 금액 모르는 집행이 있으면 집행액·잔여는 '미확인' (코덱스 검토 2026-11-14)
        committed = P_.get("committed") if "committed" in P_ else None
        up.append({"id": P_["id"], "name": P_.get("name", ""), "client": P_.get("client", ""), "event": P_.get("event_date", ""),
                   "date": e, "estimate": P_.get("estimate"), "budget": P_.get("budget"), "paid": paid,
                   "left": _sub(P_.get("budget"), paid), "avail": _sub(P_.get("budget"), committed),
                   "rev_left": left_rev, "cost_done": cost_done, "rem_cost": rem_cost})
    up.sort(key=lambda r: (r["date"], r["id"]))
    # 사전견적·예산이 없는 건은 표 합계에서 빼고 건수를 알린다 (그 건 칸은 '미확인'). 집행액·요청을 모르는 건은 그 합계만 '미확인'
    known = [r for r in up if r["estimate"] is not None and r["budget"] is not None]
    up_paid_unknown = sum(1 for r in known if r["paid"] is None)
    up_avail_unknown = sum(1 for r in known if r["avail"] is None)
    up_tot = {k: sum(r[k] for r in known) for k in ("estimate", "budget")}
    for k in ("paid", "left"):
        up_tot[k] = None if up_paid_unknown else sum(r[k] for r in known)
    up_tot["avail"] = None if up_avail_unknown else sum(r["avail"] for r in known)
    up_missing = len(up) - len(known)
    up_gp = add_gp
    exp_rev = None if tot_all["revenue"] is None else tot_all["revenue"] + add_rev
    exp_gp = None if tot_all["gp"] is None else tot_all["gp"] + add_gp

    acc = None
    if getattr(d, "dept_accounts", None) is not None:
        rows = [r for r in d.dept_accounts if "".join(str(r["dept"] or "").split()) == "".join(team.split()) and r["ym"] in months
                and not _is_pay_account(r["account"])]
        names, order = {}, []
        for r in rows:
            if r["code"] not in names:
                order.append(r["code"])
            names[r["code"]] = r["account"]
        acc = []
        for code in sorted(order):
            by = {}
            for r in rows:
                if r["code"] == code:
                    by[r["ym"]] = None if by.get(r["ym"], 0) is None or r["amount"] is None else by.get(r["ym"], 0) + r["amount"]
            cur_v, prev_v = by.get(ym, 0), by.get(_prev(ym), 0) if _prev(ym)[:4] == year else None
            total = _sum(by.get(m, 0) for m in months_c)
            acc.append({"code": code, "name": re.sub(r"\((판|제)\)$", "", names[code]), "cur": cur_v, "prev": prev_v,
                        "total": total})
        acc.sort(key=lambda a: -(a["total"] or 0))

    show_net = (d.settings or {}).get(NET_SETTING, "").strip() == "표시"
    return {"asof": R.get("asof"), "team": team, "ym": ym, "year": year, "months": M, "tot": tot, "cum": cum,
            "open": open_, "closed_n": len(Mc), "tot_all": tot_all, "t_rev": t_rev, "t_rate": t_rate, "t_gp": t_gp,
            "company_rate": company_rate, "cur": cur, "ytd": ytd, "cur_gap": cur_gap, "ytd_gap": ytd_gap,
            "has_projects": bool(per), "up": up, "up_tot": up_tot, "up_missing": up_missing, "up_paid_unknown": up_paid_unknown, "up_avail_unknown": up_avail_unknown,
            "up_gp": up_gp, "exp_rev": exp_rev, "exp_gp": exp_gp, "add_rev": add_rev, "miss_rev": miss_rev, "miss_gp": miss_gp, "closed_left": closed_left,
            "prior_rev": prior_rev, "prior_n": prior_n,
            "acc": acc, "show_net": show_net, "company": (d.settings or {}).get("회사명", "")}


# ───────────────────────────── HTML ─────────────────────────────

CSS = """
@page { size: A4; margin: 13mm 12mm 15mm 12mm;
  @bottom-left { content: "__FOOT__"; font-size: 8pt; color: #556070; font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif; }
  @bottom-right { content: counter(page) " / " counter(pages); font-size: 8pt; color: #556070; font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif; } }
* { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: 'Noto Sans KR', 'Malgun Gothic', '맑은 고딕', 'Apple SD Gothic Neo', sans-serif; font-size: 9.2pt; line-height: 1.45; color: #17202B; margin: 0; background: #fff;
  word-break: keep-all; overflow-wrap: break-word; }
@media screen { body { max-width: 794px; margin: 0 auto; padding: 36px 44px 48px; } }
.top { display: flex; justify-content: space-between; font-size: 9pt; color: #556070; }
.top b { color: #17202B; font-weight: 700; }
h1 { font-size: 17pt; font-weight: 700; margin: 6px 0 8px; letter-spacing: -.01em; }
.meta { display: flex; flex-wrap: wrap; gap: 2px 30px; font-size: 9.6pt; }
.meta i { font-style: normal; color: #556070; margin-right: 4px; }
.excl { display: inline-block; font-size: 9pt; font-weight: 700; margin: 6px 0 4px; border: 1px solid #9AA3AF; border-radius: 6px; padding: 3px 10px; background: #F4F5F7; }
.unit, .src { font-size: 8.6pt; color: #556070; }
.lag { font-size: 9pt; color: #8A4B00; background: #FFF9EE; border: 1px solid #E0A04A; border-radius: 6px; padding: 4px 10px; margin: 4px 0; font-weight: 700; }
.hr { border: 0; border-top: 2px solid #17202B; margin: 8px 0 0; }
h2 { font-size: 12.4pt; font-weight: 700; margin: 13px 0 7px; padding-bottom: 4px; border-bottom: 1px solid #17202B; break-after: avoid; }
h2 small { font-size: 9.4pt; font-weight: 400; color: #556070; margin-left: 4px; }
table { border-collapse: collapse; width: 100%; }
table.g th, table.g td { border: 0; border-bottom: 1px solid #ECEEF1; padding: 3.5px 6px; text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
table.g thead th { background: #F4F5F7; font-weight: 500; color: #3A4452; font-size: 8.6pt; border-bottom: 0; white-space: normal; }
table.g thead th.gl { border-left: 1px solid #D9DDE3; text-align: center; }
table.g thead th small { display: block; }
table.g tr.pj td { padding-top: 6px; padding-bottom: 6px; }
table.g thead th:first-child, table.g td.l, table.g th.l { text-align: left; }
table.g td.l { white-space: normal; }
table.g td.c, table.g th.c { text-align: center; }
table.g tr { break-inside: avoid; }
table.g tr.b td { font-weight: 700; }
table.g tr.tot td { border-top: 1px solid #17202B; border-bottom: 0; font-weight: 700; }
table.g tr.sumr td { border-top: 0; }
table.g tr.gap td { color: #556070; }
table.g tr.now td { background: #E9F0FB; font-weight: 700; }
table.g td.k { font-weight: 700; }
table.g td.p { color: #556070; }
table.g td.dn, .dn { color: #8A4B00; }
.neg { color: #8A4B00; }
table.g td.hl { background: #FFF9EE; font-weight: 700; }
table.g td.up { color: #1E4B91; font-weight: 700; }
table.g td.low { text-decoration: underline; }
table.g.sm td, table.g.sm th { padding: 3.4px 5px; font-size: 8.6pt; }
.bar { display: inline-block; width: 86px; height: 7px; background: #E6E9EE; border-radius: 4px; vertical-align: 1px; margin-right: 6px; overflow: hidden; }
.bar i { display: block; height: 100%; background: #1E4B91; border-radius: 4px; }
td.mut { color: #556070; font-size: 8.6pt; }
small { font-size: 8pt; color: #556070; font-weight: 400; }
.note { font-size: 8.8pt; color: #3A4452; margin: 5px 0 0; }
.none { background: #F4F5F7; border-radius: 8px; padding: 8px 14px; font-size: 9.2pt; color: #3A4452; margin: 0; }
.chbox { border: 1px solid #D9DDE3; border-radius: 10px; padding: 8px 12px 4px; margin: 0 0 8px; break-inside: avoid; }
.cap { font-size: 9pt; font-weight: 700; margin-bottom: 2px; }
.cap span { font-weight: 400; color: #556070; }
.two > * { min-width: 0; }
.two > * { flex: 1 1 0; }
.two { display: flex; gap: 12px; margin-top: 8px; break-inside: avoid; }
.card { border: 1px solid #D9DDE3; border-radius: 10px; padding: 9px 14px; }
.card .ct { display: flex; justify-content: space-between; font-size: 9.4pt; }
.card .ct b { color: #1E4B91; }
.card .big { font-size: 15pt; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1.3; }
.card .cf { font-size: 8.6pt; color: #556070; }
.al { display: flex; gap: 12px; align-items: flex-start; border: 1px solid #E0A04A; background: #FFF9EE; border-radius: 8px; padding: 7px 14px; margin: 0 0 7px; break-inside: avoid; font-size: 9.4pt; }
.al .lv { flex: none; font-size: 8.6pt; font-weight: 700; border-radius: 4px; padding: 0 9px; background: #F3C063; color: #5A3200; margin-top: 2px; }
.al.hi { border-color: #D98A8A; background: #FDECEC; }
.al.hi .lv { background: #A3241F; color: #fff; }
.basis { break-inside: avoid; border-top: 1px solid #D9DDE3; padding-top: 10px; margin-top: 18px; font-size: 8.8pt; color: #3A4452; }
.basis b { color: #17202B; }
.basis ol { list-style: none; margin: 2px 0 0; padding: 0; }
.basis li { margin: 2px 0; }
.basis li:first-child { display: inline; margin-left: 4px; }
.end { text-align: center; margin-top: 10px; font-size: 9pt; color: #556070; }
.sec { break-inside: avoid; }
.chbox, .two, .al { margin-right: 1px; }
"""


def _td(v, cls=""):
    return "<td%s>%s</td>" % (" class='%s'" % cls if cls else "", v)


def _tr(cells, cls=""):
    return "<tr%s>%s</tr>" % (" class='%s'" % cls if cls else "", "".join(cells))


def _num(v, neg_red=False, cls=""):
    c = (cls + (" neg" if neg_red and v is not None and v < 0 else "")).strip()
    return _td(esc(W(v)), c)


def _dnum(v):
    """증감 칸: 줄어든 값(△)은 색으로 구분."""
    return _td(esc(W(v)), "dn" if v is not None and v < 0 else "")


def _rate_bar(a, b):
    """달성률 칸: 막대 + 숫자 (목표가 있을 때만)."""
    if not b or a is None:
        return _td(esc(P(a, b)) if b else "-", "l")
    w = max(0.0, min(100.0, a * 100.0 / b))
    return _td("<span class='bar'><i style='width:%.1f%%'></i></span><b>%s</b>" % (w, esc(P(a, b))), "l")


def _bs(v):
    if v is None:
        return "미확인"
    return "흑자" if v >= 0 else "<span class='neg'>적자</span>"


def _client(c):
    return esc(c) if c else "-"


def _chart(T):
    """누계 매출총이익 막대(1~12월 칸, 당월은 진하게)와 연간 목표 점선. 금액은 원 단위 그대로, 막대 밑에 한 줄 (겹치지 않게)."""
    cum = T["cum"]
    n = len(cum)
    vals = [v for v in cum if v is not None]
    top = max(vals + [T["t_gp"] or 0, 1]) * 1.02
    Wd, Hd, L, top_pad = 700, 62, 4, 16
    base = Hd + top_pad
    bw = (Wd - 2 * L) / 12.0
    s = ["<svg viewBox='0 0 %d %d' width='100%%'>" % (Wd, base + 30)]
    s.append("<line x1='%d' x2='%d' y1='%d' y2='%d' stroke='#17202B' stroke-width='.8'/>" % (L, Wd - L, base, base))
    for i in range(12):
        x = L + i * bw
        v = cum[i] if i < n else None
        now = i == n - 1
        if v is not None and v > 0:
            bh = Hd * v / top
            s.append("<rect x='%.1f' y='%.1f' width='%.1f' height='%.1f' fill='%s'/>"
                     % (x + bw * .07, base - bh, bw * .86, bh, "#12306B" if now else "#1E4B91"))
        s.append("<text x='%.1f' y='%d' text-anchor='middle' font-size='9.5' fill='%s'%s>%d월</text>"
                 % (x + bw / 2, base + 13, "#17202B" if now else "#3A4452", " font-weight='700'" if now else "", i + 1))
        if i < n:
            s.append("<text x='%.1f' y='%d' text-anchor='middle' font-size='8.6' fill='%s'%s>%s</text>"
                     % (x + bw / 2, base + 26, "#17202B" if now else "#3A4452", " font-weight='700'" if now else "", esc(W(v))))
    if T["t_gp"]:
        ty = base - Hd * T["t_gp"] / top
        s.append("<line x1='%d' x2='%d' y1='%.1f' y2='%.1f' stroke='#8A4B00' stroke-dasharray='5 3' stroke-width='1.2'/>" % (L, Wd - L, ty, ty))
        s.append("<text x='%d' y='%.1f' text-anchor='end' font-size='9' font-weight='700' fill='#8A4B00' style='paint-order:stroke' stroke='#fff' "
                 "stroke-width='3'>연간 목표 %s</text>" % (Wd - L - 2, ty - 4, esc(W(T["t_gp"]))))
    s.append("</svg>")
    cap = "누계 매출총이익과 연간 목표" if T["t_gp"] else "누계 매출총이익 (연간 목표 없음)"
    return "<div class='chbox'><div class='cap'>%s <span>단위 원</span></div>%s</div>" % (cap, "".join(s))


def _project_table(T, rows, g, label_total, with_months):
    cur, tot = T["months"][-1], T["tot"]
    head = ("<th>No</th>" if with_months else "") + "<th>프로젝트</th><th>거래처</th><th>행사일</th>" + \
        ("<th>계상월</th>" if with_months else "") + "<th>매출</th><th>매출원가</th><th>매출총이익</th><th>수익률</th>"
    out = ["<table class='g%s'><thead><tr>%s</tr></thead><tbody>" % (" sm" if with_months else "", head)]
    low = None if T["t_rate"] is None else T["t_rate"] - LOW_GAP
    for k, r in enumerate(rows, 1):
        rate = None if not r["revenue"] or r["gp"] is None else r["gp"] * 100.0 / r["revenue"]
        out.append(_tr(([_td(str(k), "c")] if with_months else []) + [
            _td(esc("[%s] %s" % (r["id"], r["name"])), "l"), _td(_client(r["client"]), "l"), _td(esc(_dots(r["event"]) or "-"), "c")]
            + ([_td(esc(r["months"] or "-"), "c")] if with_months else [])
            + [_num(r["revenue"]), _num(r["cost"]), _num(r["gp"]),
               _td(esc(P(r["gp"], r["revenue"])), "low" if with_months and low is not None and rate is not None and rate < low else "")]))
    if g:
        span = 5 if with_months else 3
        out.append(_tr(["<td class='l' colspan='%d'>프로젝트로 나누지 못한 금액 (팀 합계와의 차이)</td>" % span,
                        _num(g["revenue"]), _num(g["cost"]), _num(g["gp"]), _td("-", "c")], "gap"))
    rev, cost = (cur["revenue"], cur["cost"]) if not with_months else (tot["revenue"], tot["cost"])
    span = 5 if with_months else 3
    out.append(_tr(["<td class='c' colspan='%d'>%s (%d건)</td>" % (span, label_total, len(rows)), _num(rev), _num(cost),
                    _num(_sub(rev, cost)), _td(esc(P(_sub(rev, cost), rev)))], "b tot"))
    out.append("</tbody></table>")
    return "".join(out)


OPEN_TEXT = "마감 전"   # 달 중간에 만든 월간의 이번 달 이익 칸 (2차 전수조사 A2)


def _months_section(T, title):
    """달별 실적 그림과 표 (월간 2절·연간 2절이 같이 씀)."""
    M, tot = T["months"], T["tot"]
    h = []
    a = h.append
    a("<div class='sec'><h2>%s</h2>" % esc(title) + "")
    a(_chart(T))
    a("<table class='g'><thead><tr><th>월</th><th>매출</th><th>매출원가</th><th>매출총이익</th><th>수익률</th>"
      "<th>판관비<br><small>(급여 제외)</small></th><th>판관비 차감 후 이익</th>" + ("<th>급여 반영<br>손익</th>" if T["show_net"] else "")
      + "<th>인원</th><th>누계 매출총이익</th></tr></thead><tbody>")
    for i, x in enumerate(M):
        if x.get("open"):   # 마감 전인 이번 달: 매출만 (2차 전수조사 A2)
            wait = _td(OPEN_TEXT, "c")
            a(_tr([_td(_mlabel(x["ym"]), "c"), _num(x["revenue"]), wait, wait, wait, wait, wait] + ([wait] if T["show_net"] else [])
                  + [wait, _td("-", "c")], "now"))
            continue
        a(_tr([_td(_mlabel(x["ym"]), "c"), _num(x["revenue"]), _num(x["cost"]), _num(x["gp"]), _td(esc(P(x["gp"], x["revenue"]))),
               _num(x["sga"]), _num(x["op"], True)] + ([_td(_bs(x["net"]), "c")] if T["show_net"] else [])
              + [_td("급여 전" if x.get("unpaid") else ("미확인" if x["heads"] is None else "%d" % x["heads"]), "c"), _num(T["cum"][i])],
              "now" if i == len(M) - 1 else ""))
    a(_tr([_td("합계", "c"), _num(tot["revenue"]), _num(tot["cost"]), _num(tot["gp"]), _td(esc(P(tot["gp"], tot["revenue"]))),
           _num(tot["sga"]), _num(tot["op"], True)] + ([_td(_bs(tot["net"]), "c")] if T["show_net"] else [])
          + [_td("미확인" if tot["heads"] is None else "%.1f" % tot["heads"], "c"), _num(tot["gp"])], "b tot"))
    a("</tbody></table>")
    a("</div>")

    return "".join(h)


def _upcoming_section(T, title):
    """올해 행사 중 끝나지 않은 프로젝트와 올해 예상 (월간 5절·연중 연간 보고가 같이 씀)."""
    tot = T["tot"]
    h = []
    a = h.append
    a("<div class='sec'><h2>%s <small>(올해 행사, 끝나지 않은 것)</small></h2>" % esc(title))
    if not T["up"]:
        a("<p class='none'>올해 행사 중 끝나지 않은 프로젝트 없음</p>")
    else:
        a("<table class='g'><thead><tr><th>프로젝트</th><th>거래처</th><th>행사일</th><th>사전견적</th><th>추정 예산</th>"
          "<th>집행액<br><small>(지급이 끝난 돈)</small></th><th>잔여<br><small>(추정 예산 − 집행액)</small></th>"
          "<th>쓸 수 있는 남은 예산<br><small>(지급 전 장부 비용·요청·계획까지 뺀 것)</small></th></tr></thead><tbody>")
        for r in T["up"]:
            a(_tr([_td(esc("[%s] %s" % (r["id"], r["name"])), "l"), _td(_client(r["client"]), "l"), _td(esc(_dots(r["event"])), "c"),
                   _num(r["estimate"]), _num(r["budget"]), _num(r["paid"]), _num(r["left"], True),
                   _num(r["avail"], True, "hl" if r["avail"] is not None and r["avail"] < 0 else "")], "pj"))
        u = T["up_tot"]
        a(_tr(["<td class='c' colspan='3'>합계 (%d건)</td>" % (len(T["up"]) - T["up_missing"]), _num(u["estimate"]), _num(u["budget"]), _num(u["paid"]),
               _num(u["left"], True), _num(u["avail"], True)], "b tot"))
        a("</tbody></table>")
        over = [r for r in T["up"] if r["avail"] is not None and r["avail"] < 0]
        if over:
            a("<p class='note'>※ 쓸 수 있는 남은 예산이 △인 %d건은 이미 요청·계획한 돈이 추정 예산을 넘었습니다 (지급 전 조정 필요)</p>" % len(over))
        if T["up_missing"]:
            a("<p class='note'>※ 사전견적 또는 추정 예산이 없는 %d건은 표 합계에서 뺌</p>" % T["up_missing"])
        if T.get("up_paid_unknown") or T.get("up_avail_unknown"):
            a("<p class='note'>※ 집행·요청 금액 미확인 %d건: 그 건의 집행액·잔여·남은 예산과 합계는 미확인 (아래 매출·이익 예상에는 넣음)</p>"
              % max(T.get("up_paid_unknown") or 0, T.get("up_avail_unknown") or 0))
    tr_, tg_ = T["t_rev"], T["t_gp"]
    ta = T.get("tot_all") or tot
    upto = "1월~%d월 장부" % int(T["ym"][5:7])

    def card(label, v, how, tgt):
        return ("<div class='card'><div class='ct'><span>%s</span>%s</div><div class='big'>%s</div><div class='cf'>%s</div></div>"
                % (label, "<b>목표 대비 %s</b>" % esc(P(v, tgt)) if tgt else "", esc(W(v)), esc(how)))
    a("<div class='two'>%s%s</div>" % (
        # 11/18: 월간(이번 달까지)과 연간(끝난 달까지) 숫자가 다른 까닭이 보이게 누계 기간을 붙인다 (어느 장부까지로 셈했는지)
        card("올해 매출 예상", T["exp_rev"], "= 누계 매출(%s) %s + 아직 매출로 안 잡힌 금액 %s" % (upto, W(ta["revenue"]), W(T["add_rev"])), tr_),
        card("올해 매출총이익 예상", T["exp_gp"], "= 누계(%s) %s + 남은 매출에서 남은 원가를 뺀 %s" % (upto, W(ta["gp"]), W(T["up_gp"])), tg_)))
    a("<p class='note'>※ 아직 매출로 안 잡힌 금액 = 올해 행사 프로젝트마다 사전견적 − 이미 잡힌 매출. "
      "남은 원가 = 추정 예산(요청·계획이 예산을 넘었으면 그 금액) − 이미 잡힌 원가 (끝난 프로젝트는 0, 다만 표 기간 뒤 달에 이미 장부에 잡힌 원가는 뺌)%s%s%s</p>"
      % (" · 끝난 프로젝트 중 아직 안 잡힌 매출 %s 포함" % W(T["closed_left"]) if T.get("closed_left") else "",
         " · 작년 이전 행사 %d건의 아직 안 잡힌 매출 %s 포함" % (T["prior_n"], W(T["prior_rev"])) if T.get("prior_n") else "",
         " · 금액을 몰라 뺀 프로젝트 %d건" % max(T["miss_rev"], T["miss_gp"]) if (T.get("miss_rev") or T.get("miss_gp")) else ""))
    a("</div>")

    return "".join(h)


def render(T, today=None):
    today = today or dt.date.today()
    ym, M, tot = T["ym"], T["months"], T["tot"]
    mon = int(ym[5:7])
    cur = M[-1]
    prev = M[-2] if len(M) > 1 else None
    pv = (lambda k: prev[k]) if prev else (lambda k: None)
    pl = _mlabel(_prev(ym))
    h = []
    a = h.append

    # 1. 요약
    a("<div class='sec'><h2>1. 실적 요약</h2>")
    a("<table class='g'><colgroup><col style='width:19%'>" + "<col>" * 6 + "</colgroup>")
    cm = T.get("closed_n", mon) if T.get("open") else mon   # 누계를 낸 마지막 달 (달 중간이면 지난달)
    a("<thead><tr><th rowspan='2'>구분</th><th colspan='3' class='gl'>당월</th><th colspan='3' class='gl'>누계 (1월~%d월)</th></tr>"
      "<tr><th><b>%d월</b>%s</th><th>%s</th><th>증감</th><th><b>실적</b></th><th>연간 목표</th><th class='l'>달성률</th></tr></thead><tbody>"
      % (cm, mon, "<br><small>%s</small>" % OPEN_TEXT if T.get("open") else "", pl))
    op_ = bool(T.get("open"))
    wait = _td(OPEN_TEXT, "k")
    for name, k, tgt, cls in (("매출", "revenue", T["t_rev"], ""), ("매출원가", "cost", None, ""), ("매출총이익", "gp", T["t_gp"], "b")):
        hide = op_ and k != "revenue"
        a(_tr([_td(name, "l"), wait if hide else _num(cur[k], cls="k"), _num(pv(k), cls="p"), _td("-") if op_ else _dnum(_sub(cur[k], pv(k))),   # 달 중간 매출을 지난달 한 달과 견주지 않는다
               _num(tot[k], cls="k"), _td(esc(W(tgt)) if tgt else "-", "p"), _rate_bar(tot[k], tgt)], cls))
    rc = None if op_ or cur["revenue"] in (None, 0) or cur["gp"] is None else cur["gp"] * 100.0 / cur["revenue"]
    rp = None if not prev or prev["revenue"] in (None, 0) or prev["gp"] is None else prev["gp"] * 100.0 / prev["revenue"]
    a(_tr([_td("수익률", "l"), wait if op_ else _td(esc(P(cur["gp"], cur["revenue"])), "k"), _td(esc(P(pv("gp"), pv("revenue"))), "p"),
           _td("-" if rc is None or rp is None else "%+.1f%%p" % (rc - rp)), _td(esc(P(tot["gp"], tot["revenue"])), "k"),
           _td("%.1f%%" % T["t_rate"] if T["t_rate"] is not None else "-", "p"), _td("-", "l")], "b"))
    a(_tr([_td("팀 판관비<small> (급여 제외)</small>", "l"), wait if op_ else _num(cur["sga"]), _num(pv("sga"), cls="p"),
           _td("-") if op_ else _dnum(_sub(cur["sga"], pv("sga"))), _num(tot["sga"]), _td("-", "p"), _td("-", "l")]))
    a(_tr([_td("판관비 차감 후 이익", "l"), wait if op_ else _num(cur["op"], True), _num(pv("op"), True, "p"),
           _td("-") if op_ else _dnum(_sub(cur["op"], pv("op"))), _num(tot["op"], True), _td("-", "p"), _td("-", "l")], "b"))
    if T["show_net"]:
        a(_tr([_td("급여 반영 손익<small> (금액 비공개)</small>", "l"), wait if op_ else _td(_bs(cur["net"]), "c"), _td(_bs(pv("net")) if prev else "-", "c"),
               _td("-", "c"), _td(_bs(tot["net"]), "c"), _td("-", "c"), _td("-", "c")], "b"))
    heads = lambda v: "미확인" if v is None else "%d명" % v
    a(_tr([_td("인원", "l"), _td("급여 전" if cur.get("unpaid") else heads(cur["heads"])), _td(heads(pv("heads")) if prev else "-", "p"), _td("-"),
           _td("미확인" if tot["heads"] is None else "평균 %.1f명" % tot["heads"]), _td("-", "p"), _td("-", "l")]))
    a("</tbody></table>")
    notes = []
    if T["company_rate"] is not None:
        notes.append("같은 기간 회사 전체 수익률 %.1f%%" % T["company_rate"])
    if T["t_gp"] and tot["gp"] is not None:
        left = T["t_gp"] - tot["gp"]
        notes.append(("연간 목표 매출총이익까지 남은 금액 %s원" % W(left)) if left > 0 else "연간 목표 매출총이익 달성")
    if not T["t_gp"]:
        notes.append("올해 팀 목표가 입력되지 않아 달성률을 계산하지 않음")
    if notes:
        a("<p class='note'>※ 참고: %s</p>" % esc(" · ".join(notes)))
    a("</div>")

    # 2. 월별
    a(_months_section(T, "2. 월별 실적"))

    project_table = lambda rows, g, label_total, with_months: _project_table(T, rows, g, label_total, with_months)

    # 3. 당월 프로젝트
    a("<div class='sec'><h2>3. %d월 프로젝트별 실적%s</h2>" % (mon, " <small>(%s · 지금까지 장부에 잡힌 것)</small>" % OPEN_TEXT if op_ else ""))
    if not T["has_projects"]:
        a("<p class='none'>프로젝트별 자료 없음</p>")
    else:
        a(project_table(T["cur"], T["cur_gap"], "소계", False))
    a("</div>")

    # 4. 누계 프로젝트
    a("<h2>4. 누계 프로젝트별 실적 (1월~%d월)</h2>" % cm)
    if not T["has_projects"]:
        a("<p class='none'>프로젝트별 자료 없음</p>")
    else:
        a(project_table(T["ytd"], T["ytd_gap"], "합계", True))
        if T["t_rate"] is not None:
            a("<p class='note'>※ 수익률 밑줄 = 팀 목표 수익률(%.1f%%)보다 %g%%p 이상 낮은 건</p>" % (T["t_rate"], LOW_GAP))

    # 5. 진행·예정
    a(_upcoming_section(T, "5. 진행·예정 프로젝트"))

    # 6. 판관비
    mon_h = "%d월<br><small>(마감 전, 지금까지)</small>" % mon if op_ else "%d월" % mon
    a("<div class='sec'><h2>6. 팀 판관비 내역 <small>(급여 제외)</small></h2>")
    if T["acc"] is None:
        a("<table class='g'><thead><tr><th>구분</th><th>%s</th><th>%s</th><th>증감</th><th>누계 (1월~%d월)</th><th>월평균</th></tr></thead><tbody>"
          % (mon_h, pl, cm))
        a(_tr([_td("판관비 합계", "c"), _num(cur["sga"]), _num(pv("sga")), _num(_sub(cur["sga"], pv("sga"))), _num(tot["sga"]),
               _num(None if tot["sga"] is None else tot["sga"] / float(T.get("closed_n") or len(M)))], "b tot"))
        a("</tbody></table><p class='note'>※ 계정별 내역은 다음 자료 변환부터 나옵니다. 팀 급여는 이 표에 포함하지 않음.</p>")
    else:
        a("<table class='g'><thead><tr><th>계정</th><th>%s</th><th>%s</th><th>증감</th><th>누계 (1월~%d월)</th><th>월평균</th></tr></thead><tbody>"
          % (mon_h, pl, cm))
        for r in T["acc"]:
            a(_tr([_td(esc(r["name"]), "l"), _num(r["cur"], cls="k"), _num(r["prev"], cls="p"), _dnum(_sub(r["cur"], r["prev"])), _num(r["total"]),
                   _num(None if r["total"] is None else r["total"] / float(T.get("closed_n") or len(M)))]))
        a(_tr([_td("합계", "c"), _num(cur["sga"]), _num(pv("sga")), _num(_sub(cur["sga"], pv("sga"))), _num(tot["sga"]),
               _num(None if tot["sga"] is None else tot["sga"] / float(T.get("closed_n") or len(M)))], "b tot"))
        a("</tbody></table><p class='note'>※ 팀 급여는 이 표에 포함하지 않음.</p>")
    a("</div>")

    basis = ["수익률 = 매출총이익 ÷ 매출",
             "<b>이 자료에는 팀 급여가 제외되어 있음.</b> 판관비 차감 후 이익 = 매출총이익 − 팀 판관비(급여 제외)이며, "
             "회사 손익의 영업이익과 다름. 본부·공통 비용은 나누지 않음"]
    if T["show_net"]:
        basis.append("급여 반영 손익 = 매출총이익 − 판관비 − 팀 급여. 금액은 표시하지 않고 0원 이상이면 흑자, 미만이면 적자로만 표시")
    basis.append("진행·예정 금액은 세금계산서 발행 전 사전견적 기준이며 확정 실적이 아님")
    a("<div class='basis'><b>작성 기준</b><ol>%s</ol></div>" % "".join("<li>%s</li>" % b for b in basis))
    a("<div class='end'>- 끝 -</div>")

    y, m = int(ym[:4]), mon
    last_day = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day
    ad = T.get("asof")   # 월 중간에 만들면 기간 끝 = 기준일 (2026-11-14 점검 P6: 11/14에 만들어도 11/30로 찍혔음)
    if isinstance(ad, dt.date) and (ad.year, ad.month) == (y, m) and ad.day < last_day:
        last_day = ad.day
    cy = y, m, last_day
    if T.get("open"):   # 달 중간: 누계는 지난달 말까지
        ce = dt.date(y, m, 1) - dt.timedelta(days=1)
        cy = (ce.year, ce.month, ce.day) if T.get("closed_n") else None
    excl = "※ 이 자료의 판관비·이익 금액에는 <b>팀 급여가 제외</b>되어 있습니다." + (
        " 급여 반영 손익은 흑자·적자로만 표시합니다." if T["show_net"] else "")
    title = "%d년 %d월 %s 실적 보고" % (y, m, T["team"])
    head = ("<div class='top'><span>%s · 경영관리</span><b>대외비 · %s 배포용</b></div>"
            "<h1>%s</h1>"
            "<div class='meta'><span><i>수신</i>%s장</span><span><i>작성</i>경영관리 · %s</span>"
            "<span><i>당월</i>%d.%02d.01 ~ %02d.%02d</span><span><i>누계</i>%s</span></div>"
            "<div class='excl'>%s</div><div class='unit'>(단위: 원)</div><hr class='hr'>"
            % (esc(T["company"]), esc(T["team"]), esc(title), esc(T["team"]), today.strftime("%Y.%m.%d"),
               y, m, m, last_day, "%d.01.01 ~ %02d.%02d" % cy if cy else "끝난 달 없음", excl))
    foot = re.sub(r'["\\\n]', " ", "%s · 대외비" % title)   # 쪽 아래 왼쪽 글 (CSS 문자열 안)
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>%s</title><style>%s</style></head>"
            "<body>%s%s</body></html>" % (esc(title), CSS.replace("__FOOT__", foot), head, "\n".join(h)))


def write_all(d, R, out_dir, today=None):
    """팀마다 팀장용 HTML 을 out_dir/팀장용/ 에 쓴다. -> [html 경로]."""
    folder = os.path.join(out_dir, "팀장용")
    os.makedirs(folder, exist_ok=True)
    out = []
    asof = R.get("asof") or today or dt.date.today()
    from . import insights, insights_render
    I, ierr = insights.for_report(R) if R.get("s2") else (None, "")   # 자동 분석 (사용자 2026-11-12: 팀장 보고는 목업대로)
    for team in team_names(d):
        T = build(d, R, team)
        path = os.path.join(folder, "%s_월간_팀장_%s.html" % (asof.isoformat() if hasattr(asof, "isoformat") else asof, team))
        page = render(T, today)
        from . import gate   # 사용한 자료와 날짜 (사용자 2026-11-14)
        lag = gate.bank_lag_note(R)   # 계산-06 (N1): 장부의 통장 거래 입력이 늦으면 한 줄
        page = page.replace("<div class='unit'>(단위: 원)", "<div class='unit src'>(단위: 원) · %s" % esc(gate.sources_line(R)), 1)
        if lag:
            page = page.replace("<div class='excl'>", "<div class='lag'>%s</div><div class='excl'>" % esc(lag), 1)
        if I is None and ierr:   # 2차 P3-19 (2026-11-15): 자동 분석이 실패하면 팀장 보고에서 그 절이 말없이 빠졌다
            page = page.replace("<div class='basis'>", "<p class='note'>※ 자동 분석 절(이익 흐름·주의할 프로젝트 등)을 만들지 못했습니다 (%s). "
                                "경영관리에 알려 주세요.</p><div class='basis'>" % esc(ierr.split(":")[0]), 1)
        if I is not None:
            try:
                page = page.replace("<div class='basis'>", insights_render.team_section(I, R, team) + "<div class='basis'>", 1)
            except Exception as e:   # 자동 분석 때문에 팀장 보고를 못 만들면 안 된다. 다만 빠진 것은 한 줄로 알린다 (K2)
                page = page.replace("<div class='basis'>", "<p class='note'>※ 자동 분석 절(이익 흐름·주의할 프로젝트 등)을 붙이지 못했습니다 (%s). "
                                    "경영관리에 알려 주세요.</p><div class='basis'>" % esc(type(e).__name__), 1)
        try:   # 2차 P4-5 (2026-11-15): 한 팀이 실패하면 나머지 팀도 안 쓰고 월간은 '완료'(0)였다 → 팀마다 쓰고 실패를 모아 알림
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                f.write(page)
            os.replace(path + ".tmp", path)
        except OSError as e:
            R.setdefault("_team_failed", []).append("%s (%s)" % (team, e.strerror or type(e).__name__))
            continue
        out.append(path)
    return out


# ───────────────────────────── 연간 팀장 보고 (사용자 2026-11-17) ─────────────────────────────
def render_annual(T, X, today=None):
    """팀장용 연간 실적 보고 (사용자 2026-11-17 '연간 보고를 대표용·경영관리용·팀장용으로 구분해서').
    T = build(d, 끝난 달 말일 기준 월간 계산, 팀) — 월간 팀장 보고와 같은 숫자. X = annual.team_extra(A, 팀).
    월간 팀장 보고와 같은 양식·같은 규칙: 급여 금액 없음(판관비·이익은 급여 제외), 안내 문구 없음."""
    today = today or dt.date.today()
    M, tot = T["months"], T["tot"]
    year, cut, mid = X["year"], X["cut"], X["mid"]
    per = "1월~%d월" % cut if mid else "한 해"
    h = []
    a = h.append

    # 1. 한 해 요약
    a("<div class='sec'><h2>1. %d년 실적 요약 <small>(%s)</small></h2>" % (year, per))
    a("<table class='g'><colgroup><col style='width:22%'>" + "<col>" * 5 + "</colgroup>")
    a("<thead><tr><th>구분</th><th><b>%d년 실적</b></th><th>연간 목표</th><th class='l'>달성률</th><th>%d년%s</th><th>증감</th></tr></thead><tbody>"
      % (year, year - 1, " 같은 1~%d월" % cut if mid else ""))
    for name, k, tgt, last, cls in (("매출", "revenue", T["t_rev"], X.get("lrev"), ""), ("매출원가", "cost", None, None, ""),
                                    ("매출총이익", "gp", T["t_gp"], None, "b")):
        a(_tr([_td(name, "l"), _num(tot[k], cls="k"), _td(esc(W(tgt)) if tgt else "-", "p"), _rate_bar(tot[k], tgt),
               _num(last, cls="p") if last is not None else _td("-", "p"), _dnum(_sub(tot[k], last)) if last is not None else _td("-")], cls))
    a(_tr([_td("수익률", "l"), _td(esc(P(tot["gp"], tot["revenue"])), "k"), _td("%.1f%%" % T["t_rate"] if T["t_rate"] is not None else "-", "p"),
           _td("-", "l"), _td("-", "p"), _td("-")], "b"))
    a(_tr([_td("팀 판관비<small> (급여 제외)</small>", "l"), _num(tot["sga"]), _td("-", "p"), _td("-", "l"), _td("-", "p"), _td("-")]))
    a(_tr([_td("판관비 차감 후 이익", "l"), _num(tot["op"], True), _td("-", "p"), _td("-", "l"), _td("-", "p"), _td("-")], "b"))
    if T["show_net"]:
        a(_tr([_td("급여 반영 손익<small> (금액 비공개)</small>", "l"), _td(_bs(tot["net"]), "c"), _td("-", "c"), _td("-", "c"), _td("-", "c"), _td("-", "c")], "b"))
    a(_tr([_td("인원", "l"), _td("미확인" if tot["heads"] is None else "평균 %.1f명" % tot["heads"]), _td("-", "p"), _td("-", "l"), _td("-", "p"), _td("-")]))
    a("</tbody></table>")
    notes = []
    if mid and T["t_rev"]:
        notes.append("연간 목표는 한 해 금액 (기간 %d/12 = %.1f%%)" % (cut, cut * 100.0 / 12))
    if T["company_rate"] is not None:
        notes.append("같은 기간 회사 전체 수익률 %.1f%%" % T["company_rate"])
    if not T["t_gp"]:
        notes.append("올해 팀 목표가 입력되지 않아 달성률을 계산하지 않음")
    if notes:
        a("<p class='note'>※ 참고: %s</p>" % esc(" · ".join(notes)))
    a("</div>")

    # 2. 달별
    a(_months_section(T, "2. 달별 실적"))

    # 3. 분기별
    a("<div class='sec'><h2>3. 분기별 실적</h2>")
    a("<table class='g'><thead><tr><th>분기</th><th>매출</th><th>매출원가</th><th>매출총이익</th><th>수익률</th>"
      "<th>판관비<br><small>(급여 제외)</small></th><th>판관비 차감 후 이익</th></tr></thead><tbody>")
    for q in range(4):
        ms = [x for x in M if (int(x["ym"][5:7]) - 1) // 3 == q]
        if not ms:
            a(_tr([_td("%d분기" % (q + 1), "c")] + [_td("-")] * 6))
            continue
        v = dict((k, _sum([x[k] for x in ms])) for k in ("revenue", "cost", "gp", "sga", "op"))
        last = int(ms[-1]["ym"][5:7])
        a(_tr([_td("%d분기%s" % (q + 1, " (%d월까지)" % last if last % 3 else ""), "c"), _num(v["revenue"]), _num(v["cost"]), _num(v["gp"]),
               _td(esc(P(v["gp"], v["revenue"]))), _num(v["sga"]), _num(v["op"], True)]))
    a(_tr([_td("합계", "c"), _num(tot["revenue"]), _num(tot["cost"]), _num(tot["gp"]), _td(esc(P(tot["gp"], tot["revenue"]))),
           _num(tot["sga"]), _num(tot["op"], True)], "b tot"))
    a("</tbody></table></div>")

    # 4. 프로젝트
    a("<h2>4. 프로젝트별 실적 (%s)</h2>" % per)
    if not T["has_projects"]:
        a("<p class='none'>프로젝트별 자료 없음</p>")
    else:
        a(_project_table(T, T["ytd"], T["ytd_gap"], "합계", True))
        if T["t_rate"] is not None:
            a("<p class='note'>※ 수익률 밑줄 = 팀 목표 수익률(%.1f%%)보다 %g%%p 이상 낮은 건</p>" % (T["t_rate"], LOW_GAP))

    # 5. 연중이면 남은 프로젝트와 올해 예상
    n = 5
    if mid:
        a(_upcoming_section(T, "%d. 진행·예정 프로젝트" % n))
        n += 1

    # 판관비
    a("<div class='sec'><h2>%d. 팀 판관비 내역 <small>(급여 제외)</small></h2>" % n)
    a("<table class='g'><thead><tr><th>계정</th><th>%s</th><th>월평균</th></tr></thead><tbody>" % ("누계 (%s)" % per if mid else "%d년" % year))
    for r in T["acc"] or []:
        a(_tr([_td(esc(r["name"]), "l"), _num(r["total"]), _num(None if r["total"] is None else r["total"] / float(len(M)))]))
    a(_tr([_td("합계" if T["acc"] is not None else "판관비 합계", "c"), _num(tot["sga"]),
           _num(None if tot["sga"] is None else tot["sga"] / float(len(M)))], "b tot"))
    a("</tbody></table><p class='note'>※ 팀 급여는 이 표에 포함하지 않음.%s</p></div>" % ("" if T["acc"] is not None else " 계정별 내역은 다음 자료 변환부터 나옵니다."))
    n += 1

    # 내년
    ny = year + 1
    a("<div class='sec'><h2>%d. %d년 준비 <small>(이미 받은 일 · 목표)</small></h2>" % (n, ny))
    NX = X.get("next") or []
    if not NX:
        a("<p class='none'>%d년 행사 프로젝트 없음</p>" % ny)
    else:
        a("<table class='g'><thead><tr><th>프로젝트</th><th>행사일</th><th>사전견적</th><th>추정 예산</th><th>집행액</th>"
          "<th>잔여<br><small>(추정 예산 − 집행액)</small></th></tr></thead><tbody>")
        for p in NX:
            a(_tr([_td(esc("[%s] %s" % (p["id"], p["name"])), "l"), _td(esc(_dots(p["day"].isoformat())), "c"), _num(p["est"]), _num(p["budget"]),
                   _num(p["paid"]), _num(None if p["budget"] is None else p["budget"] - p["paid"], True)], "pj"))
        b = _sum([p["budget"] for p in NX])
        pd_ = _sum([p["paid"] for p in NX])
        a(_tr(["<td class='c' colspan='2'>합계 (%d건)</td>" % len(NX), _num(_sum([p["est"] for p in NX])), _num(b), _num(pd_), _num(_sub(b, pd_), True)], "b tot"))
        a("</tbody></table>")
    g = X.get("goal_next")
    got = _sum([p["est"] for p in NX]) if NX else None
    a("<table class='g' style='margin-top:8px'><thead><tr><th>%d년 매출 목표</th><th>%d년 목표 수익률</th><th>목표 중 이미 받은 일 (사전견적)</th></tr></thead><tbody>" % (ny, ny))
    a(_tr([_td(esc(W(g[0])) if g and g[0] else "입력 전", "c"), _td((("%d%%" if round(g[1] * 100, 1) == int(round(g[1] * 100, 1)) else "%.1f%%") % round(g[1] * 100, 1)) if g and g[1] is not None else "입력 전", "c"),
           _td((esc(W(got)) if got is not None else "-") + (" (%s)" % esc(P(got, g[0])) if g and g[0] and got is not None else ""), "c")]))
    a("</tbody></table></div>")

    basis = ["수익률 = 매출총이익 ÷ 매출",
             "<b>이 자료에는 팀 급여가 제외되어 있음.</b> 판관비 차감 후 이익 = 매출총이익 − 팀 판관비(급여 제외)이며, "
             "회사 손익의 영업이익과 다름. 본부·공통 비용은 나누지 않음"]
    if T["show_net"]:
        basis.append("급여 반영 손익 = 매출총이익 − 판관비 − 팀 급여. 금액은 표시하지 않고 0원 이상이면 흑자, 미만이면 적자로만 표시")
    if mid:
        basis.append("연중 보고: 실적은 끝난 달(1~%d월)까지. 진행·예정 금액은 세금계산서 발행 전 사전견적 기준이며 확정 실적이 아님" % cut)
    basis.append("%d년 사전견적·추정 예산은 확정 실적이 아님 (추정 예산 = 사전견적 × (1 − 팀 목표 수익률))" % ny)
    a("<div class='basis'><b>작성 기준</b><ol>%s</ol></div>" % "".join("<li>%s</li>" % b for b in basis))
    a("<div class='end'>- 끝 -</div>")

    end = X["end"]
    excl = "※ 이 자료의 판관비·이익 금액에는 <b>팀 급여가 제외</b>되어 있습니다." + (
        " 급여 반영 손익은 흑자·적자로만 표시합니다." if T["show_net"] else "")
    title = "%d년 연간 %s 실적 보고" % (year, T["team"])
    head = ("<div class='top'><span>%s · 경영관리</span><b>대외비 · %s 배포용</b></div>"
            "<h1>%s</h1>"
            "<div class='meta'><span><i>수신</i>%s장</span><span><i>작성</i>경영관리 · %s</span>"
            "<span><i>기간</i>%d.01.01 ~ %02d.%02d</span><span><i>기준일</i>%s</span></div>"
            "<div class='excl'>%s</div><div class='unit'>(단위: 원)</div><hr class='hr'>"
            % (esc(T["company"]), esc(T["team"]), esc(title), esc(T["team"]), today.strftime("%Y.%m.%d"),
               year, end.month, end.day, X["asof"].strftime("%Y.%m.%d"), excl))
    foot = re.sub(r'["\\\n]', " ", "%s · 대외비" % title)
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>%s</title><style>%s</style></head>"
            "<body>%s%s</body></html>" % (esc(title), CSS.replace("__FOOT__", foot), head, "\n".join(h)))


def write_annual(d, R, A, out_dir, today=None):
    """팀마다 연간 팀장 보고를 out_dir/팀장용/ 에 쓴다 ('<연도>_연간_팀장_<팀>.html'). -> [html 경로]. R = 끝난 달 말일 기준 월간 계산."""
    from . import annual, gate
    folder = os.path.join(out_dir, "팀장용")
    os.makedirs(folder, exist_ok=True)
    out = []
    for team in team_names(d):
        page = render_annual(build(d, R, team), annual.team_extra(A, team), today)
        page = page.replace("<div class='unit'>(단위: 원)", "<div class='unit src'>(단위: 원) · %s" % esc(gate.sources_line(R)), 1)
        lag = gate.bank_lag_note(R)
        if lag:
            page = page.replace("<div class='excl'>", "<div class='lag'>%s</div><div class='excl'>" % esc(lag), 1)
        path = os.path.join(folder, "%d_연간_팀장_%s.html" % (A["year"], team))
        try:
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                f.write(page)
            os.replace(path + ".tmp", path)
        except OSError as e:
            R.setdefault("_team_failed", []).append("%s (%s)" % (team, e.strerror or type(e).__name__))
            continue
        out.append(path)
    return out
