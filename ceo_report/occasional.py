"""'가끔 넣는 값' 탭이 쓰는 읽기·고치기·지우기 (편의성 22~26, 2026-11-16). tkinter 없이 시험한다.

· 저장된 값을 칸에 채우기 (saved_…): 예전엔 칸이 비어 있어 아래 '저장된 값' 글을 보고 다시 쳐야 했다.
· 빈칸은 어디서나 '그대로', 지울 땐 '지우기' (delete_…): 예전엔 카드마다 달랐다 (내년 예산=그대로, 감가상각비=지움, 팀 목표=오류).
· 지급·입금 예정(자금일정.csv)을 창 안 목록에서 고치고 지우기 — 화면에 보인 줄과 파일의 줄이 다르면 바꾸지 않는다.
· 대출 새 만기일(대출만기.csv) — 신용평가 체크리스트의 '대출만기일'(가장 이른 만기)과는 다른 값이라 합치지 않는다.
"""
import csv
import io
import os

from . import util


def _won(v):
    return "" if v is None else "{:,}".format(int(v))


def _g(v):
    return "" if v is None else ("%g" % v)


# ───────────── 저장된 값 채우기 ─────────────
def saved_target(input_dir, year, team):
    """-> (매출 목표 글, 수익률 글). 없으면 ('', '')."""
    from . import targets
    v = targets.read(input_dir).get((str(year or "").strip(), (team or "").strip()))
    return (_won(v["revenue"]), _g(v["rate"])) if v else ("", "")


def delete_target(input_dir, year, team):
    """한 팀의 그 해 목표를 지운다 -> 그 해 남은 줄 수. 없으면 ValueError."""
    from . import targets
    y, team = str(year or "").strip(), (team or "").strip()
    util.guard_save(os.path.join(input_dir, targets.TARGET_FILE))
    cur = targets.read(input_dir)
    if (y, team) not in cur:
        raise ValueError("지울 목표가 없습니다 (%s년 %s)" % (y, team or "-"))
    del cur[(y, team)]
    path = os.path.join(input_dir, targets.TARGET_FILE)
    with open(path + ".tmp", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(targets.TARGET_COLUMNS)
        for (yy, tt), v in sorted(cur.items()):
            w.writerow([yy, tt, "" if v["revenue"] is None else v["revenue"], "" if v["rate"] is None else ("%g" % v["rate"])])
    os.replace(path + ".tmp", path)
    return sum(1 for (yy, _) in cur if yy == y)


def saved_dep(input_dir, year):
    """직접 넣은 그 해 연간 감가상각비 글 (없으면 '')."""
    from . import corptax
    return _won(corptax.read(input_dir).get(str(year or "").strip()))


def saved_card(input_dir, company):
    """-> (납부일 글, 기산일 글). 저장된 카드사가 아니면 ('', '')."""
    from . import tax
    try:
        cur, _ = tax.read_card_days(input_dir)
    except Exception:
        return "", ""
    v = cur.get(tax._card_name(company))
    return (str(v[0]), str(v[1])) if v else ("", "")


def delete_card(input_dir, company):
    """카드사 한 줄을 지운다 -> 남은 [(카드사, 납부일, 기산일)]. 없으면 ValueError."""
    from . import tax
    co = tax._card_name(company)
    cur, notes = tax.read_card_days(input_dir)
    if co not in cur:
        raise ValueError("지울 카드사가 없습니다 (%s)" % (company or "-"))
    bad = [n for n in notes if "줄 날짜를 읽지 못함" in n]
    if bad:
        raise ValueError("%s 에 날짜를 못 읽은 줄이 있어 저장하면 그 줄이 사라집니다 — 그 줄부터 고치세요: %s" % (tax.CARD_FILE, "; ".join(bad)))
    del cur[co]
    rows = sorted((c, p, s) for c, (p, s) in cur.items())
    path = os.path.join(input_dir, tax.CARD_FILE)
    with open(path + ".tmp", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(tax.CARD_COLUMNS)
        for r in rows:
            w.writerow(r)
    os.replace(path + ".tmp", path)
    return rows


def saved_budget(input_dir, year, team):
    """내년 예산 칸에 채울 값 -> {'성장률','늘릴인원','입사월','급여인상률','물가인상률': 글}."""
    from . import budget
    V = budget.read_values(input_dir)
    y, team = str(year or "").strip(), (team or "").strip()
    out = {}
    for k in budget.TEAM_KINDS:
        out[k] = _g(V.get((y, k, team)))
    for k in budget.CO_KINDS:
        out[k] = _g(V.get((y, k, budget.COMPANY)))
    return out


def holder_names(input_dir):
    from . import dividend
    try:
        return [r["이름"].strip() for r in dividend.read(input_dir)]
    except Exception:
        return []


def saved_holder(input_dir, name):
    """저장된 주주 한 명 -> {'지분율','미성년자'(bool),'회사급여'(bool),'다른금융소득','그밖소득','공제인원'} 또는 None."""
    from . import dividend
    try:
        rows = dividend.read(input_dir)
    except Exception:
        return None
    r = next((r for r in rows if r["이름"].strip() == (name or "").strip()), None)
    if r is None:
        return None

    def money(t):
        t = str(t or "").replace(",", "").strip()
        return "{:,}".format(int(t)) if t.lstrip("-").isdigit() else t
    return {"지분율": (r.get("지분율") or "").strip(), "미성년자": (r.get("미성년자") or "").strip() == "예",
            "회사급여": (r.get("회사급여") or "").strip() == "예", "다른금융소득": money(r.get("다른금융소득")),
            "그밖소득": money(r.get("그밖소득")), "공제인원": (r.get("공제인원") or "").strip()}


def remember_text(input_dir):
    """'계정 기억' 옆 글: 지금 기억 중인지 (편의성 26). 비밀번호는 보이지 않는다."""
    from . import credstore
    got = credstore.load(input_dir)
    return "기억 중: %s" % got[0] if got else "기억한 계정 없음"


# ───────────── 지급·입금 예정 목록 (자금일정.csv) ─────────────
SCHED_SHOW = ("예정일", "입출금", "금액", "확정여부", "거래처", "비고")


def _sched_read(input_dir):
    """-> (머리글, 줄 목록(list of list), 인코딩, 줄바꿈). 파일이 없으면 ([], [], …)."""
    from .app import SCHED_FILE, _encoding
    path = os.path.join(input_dir, SCHED_FILE)
    if not os.path.exists(path):
        return [], [], "utf-8-sig", "\r\n"
    enc, raw = _encoding(path)
    text = raw.decode(enc)
    nl = "\r\n" if "\r\n" in text else "\n"
    rows = [r for r in csv.reader(io.StringIO(text)) if r]
    if not rows:
        return [], [], enc, nl
    return [c.strip() for c in rows[0]], rows[1:], enc, nl


def schedule_rows(input_dir):
    """자금일정.csv 줄 -> [{'_n': 줄 번호(0부터), 머리글: 값 …}] (파일 순서 그대로)."""
    cols, rows, _, _ = _sched_read(input_dir)
    out = []
    for i, r in enumerate(rows):
        d = dict((c, (r[j].strip() if j < len(r) else "")) for j, c in enumerate(cols))
        d["_n"] = i
        out.append(d)
    return out


def schedule_label(row):
    """목록 한 줄: '2026-11-30 지급 3,300,000원 예상 · 가상업체 · 메모'."""
    amt = str(row.get("금액") or "").replace(",", "").strip()
    amt = "{:,}".format(int(amt)) if amt.isdigit() else row.get("금액") or ""
    return "%s %s %s원 %s · %s%s" % (row.get("예정일") or "", row.get("입출금") or "", amt, row.get("확정여부") or "",
                                     row.get("거래처") or "", (" · " + row["비고"]) if row.get("비고") else "")


def _sched_write(input_dir, cols, rows, enc, nl):
    from .app import SCHED_FILE
    path = os.path.join(input_dir, SCHED_FILE)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator=nl)
    w.writerow(cols)
    for r in rows:
        w.writerow(r)
    with open(path + ".tmp", "wb") as f:
        f.write(buf.getvalue().encode(enc))
    os.replace(path + ".tmp", path)


def _same_row(cols, raw, shown):
    return all((raw[j].strip() if j < len(raw) else "") == str(shown.get(c) or "").strip() for j, c in enumerate(cols))


def _find(input_dir, shown):
    cols, rows, enc, nl = _sched_read(input_dir)
    n = shown.get("_n")
    if not isinstance(n, int) or not 0 <= n < len(rows) or not _same_row(cols, rows[n], shown):
        raise ValueError("목록이 그사이 바뀌었습니다 — 목록을 다시 열어 주세요 (아무것도 바꾸지 않음)")
    return cols, rows, enc, nl, n


def update_schedule(input_dir, shown, changes):
    """목록에서 고른 줄(shown = schedule_rows 의 한 줄)의 값을 바꾼다. changes: {머리글: 새 값} (예정일·입출금·금액·확정여부·거래처·비고).
    화면에 보인 줄과 파일의 줄이 다르면 바꾸지 않는다. -> 바뀐 줄 dict."""
    from .app import _check_day
    cols, rows, enc, nl, n = _find(input_dir, shown)
    new = dict(shown)
    for k, v in changes.items():
        if k not in SCHED_SHOW:
            raise ValueError("바꿀 수 없는 칸: %s" % k)
        new[k] = str(v or "").strip()
    d = _check_day(new.get("예정일") or "", "예정일")
    if d is None:
        raise ValueError("예정일을 넣으세요 (예: 2026-11-30)")
    new["예정일"] = d.isoformat()
    if new.get("입출금") not in ("지급", "입금"):
        raise ValueError("입출금은 지급 또는 입금")
    if "확정여부" in cols and new.get("확정여부") not in ("확정", "예상"):
        raise ValueError("확정여부는 확정 또는 예상")
    amt = str(new.get("금액") or "").replace(",", "").replace("원", "").strip()
    if not amt.isdigit() or int(amt) <= 0:
        raise ValueError("금액은 0보다 큰 숫자 (예: 3,300,000)")
    new["금액"] = "{:,}".format(int(amt))
    if "거래처" in cols and not new.get("거래처"):
        raise ValueError("거래처를 넣으세요")
    rows[n] = [new.get(c, "") for c in cols]
    _sched_write(input_dir, cols, rows, enc, nl)
    return new


def delete_schedule(input_dir, shown):
    """목록에서 고른 줄을 지운다 (화면에 보인 줄과 파일의 줄이 같을 때만). -> 남은 줄 수."""
    cols, rows, enc, nl, n = _find(input_dir, shown)
    del rows[n]
    _sched_write(input_dir, cols, rows, enc, nl)
    return len(rows)


# ───────────── 대출 새 만기일 (대출만기.csv) ─────────────
def maturity_rows(input_dir):
    """-> [{거래처코드, 차입처, 새만기일, 매년연장, 메모, 위하고만기}] — 대출만기.csv (없으면 알려 주신 기본 두 줄) + 차입금.csv 의 대출."""
    from . import reconcile
    M = reconcile.read_maturity(input_dir)
    out = [dict(v, 위하고만기="") for v in M.values()]
    try:
        with util.open_text(os.path.join(input_dir, reconcile.LOAN_FILE)) as f:
            loans = list(csv.DictReader(f))
    except (OSError, UnicodeDecodeError, csv.Error):
        loans = []
    by = dict((reconcile._code(r["거래처코드"]), r) for r in out)
    for ln in loans:
        k = reconcile._code(ln.get("거래처코드"))
        if not k:
            continue
        if k in by:
            by[k]["위하고만기"] = (ln.get("만기일") or "").strip()
        else:
            row = {"거래처코드": (ln.get("거래처코드") or "").strip(), "차입처": (ln.get("차입처") or "").strip(), "새만기일": "",
                   "매년연장": "", "메모": "", "위하고만기": (ln.get("만기일") or "").strip()}
            by[k] = row
            out.append(row)
    return out


def maturity_label(r):
    return "%s [%s] · 새 만기 %s%s" % (r.get("차입처") or "-", r.get("거래처코드") or "", r.get("새만기일") or "없음",
                                     " · 매년 연장" if r.get("매년연장") == "예" else "")


def save_maturity(input_dir, code, name, new_date, yearly, memo):
    """대출 한 건의 새 만기일·매년 연장·근거 메모를 넣거나 고친다 -> 전체 줄 수.
    새 만기일은 비울 수 있다 (위하고 만기일 그대로). 새 만기일을 넣으면 근거 메모(언제·누가 확인했는지)가 있어야 한다."""
    from . import reconcile
    code, name, memo = str(code or "").strip(), (name or "").strip(), (memo or "").strip()
    if not reconcile._code(code):
        raise ValueError("거래처코드를 넣으세요 (위하고 차입처 코드)")
    t = str(new_date or "").strip()
    d = None
    if t:
        d = util.date(t)
        if d is None:
            raise ValueError("새 만기일 형식 오류: %s (예: 2027-04-17)" % t)
        if not memo:
            raise ValueError("새 만기일의 근거를 메모에 적어 주세요 (예: 2027-04 은행 연장 확인)")
    if not os.path.isdir(input_dir):
        raise ValueError("입력 폴더가 없습니다: %s" % input_dir)
    path = os.path.join(input_dir, reconcile.MATURITY_FILE)
    if os.path.exists(path):
        util.guard_save(path)
    cur = reconcile.read_maturity(input_dir)   # 파일이 없으면 기본 두 줄에서 시작
    k = reconcile._code(code)
    old = cur.get(k) or {}
    cur[k] = {"거래처코드": old.get("거래처코드") or code, "차입처": name or old.get("차입처") or "",
              "새만기일": d.isoformat() if d else "", "매년연장": "예" if yearly else "아니오", "메모": memo}
    with open(path + ".tmp", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, reconcile.MATURITY_KEYS)
        w.writeheader()
        for r in cur.values():
            w.writerow(dict((c, r.get(c, "")) for c in reconcile.MATURITY_KEYS))
    os.replace(path + ".tmp", path)
    return len(cur)
