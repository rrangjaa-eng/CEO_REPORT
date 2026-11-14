"""자료 대조 (사용자 2026-11-14 결정: 정합성 제안 전부, 대조가 1천만 원 넘게 어긋나면 대표 보고에 경고 줄만 · 막지 않음).

장부(분개장을 처음부터 더한 값)를 위하고가 직접 계산한 화면 값·다른 자료와 맞춰 본다. 숫자는 바꾸지 않고 '같음/다름'만 남긴다.

변환 쪽 build_tables(...) -> 입력 폴더에
  자료대조.csv   구분·항목·비교 자료·비교 값·장부 값·차이·기준·판정·할 일·대표 경고
  차입금.csv     대출별 만기·상환 방식 (위하고 차입금현황 + 직접 넣은 새 만기일 '대출만기.csv' 우선). 예산(budget.py)이 읽는다.
  카드사용.csv   위하고 자동전표처리 '신용카드' 화면을 받아 두었으면 달·카드별 실제 사용액 (세금예상 카드대금이 쓸 수 있게)
보고 쪽 for_report(input_dir) -> R['recon'] (대표 경고 줄: render._recon_line) 과 경영관리 '자료 대조' 표.

비교하는 것 (자료전수조사·정합성제안_20261114.md 제안 번호):
  1  위하고 합계잔액시산표·재무상태표 ↔ 장부 계정 잔액. **같은 때 받은 것끼리만 '다름'으로 본다** (11/13 실제: 재무상태표를 받은 뒤
     7분 사이 들어간 지급 전표 11건 때문에 통장·미지급금이 3,561만 달라 보였음). 계정은 앞 세 자리로 묶는다 (재무상태표는
     선급금_기타소득 13101 을 선급금 13100 에 합쳐 보여 준다).
  4  분개장 '입력 시각'(dt_insert): 장부에 마지막으로 전표를 넣은 때, 통장 마지막 전표 날짜.
  5  지난 수집과 줄 번호(sq_acttax2)로 비교: 늦게 들어온 지난 날짜 전표·지워진 줄·바뀐 줄.
  6  인트라넷 프로젝트 '계산서' 칸 ↔ 장부 프로젝트별 매출.
  7  고정자산관리대장 ↔ 장부 유형자산.
  9  위하고 차입금현황(만기·상환 방식만, 잔액은 장부), 손익계산서, 예적금현황(정기예금 만기), 전자세금계산서(매출) ↔ 장부 매출전표,
     신용카드(실제 사용액), 거래처원장(거래처별 미지급금).
  0.9.1 (사용자 2026-11-15 카드): 원천징수이행상황신고서 소득세 ↔ 장부 예수금(세무서), 거래처별초기이월 ↔ 작년 말 장부,
     자료수집현황(은행·카드·홈택스 자료가 언제까지·오류), 부가세 예정고지, 차입금스케줄관리(이자율·상환 시작일 → 차입금.csv).
개인정보: 위하고 원본의 계좌번호·카드번호·담당자 이름은 쓰지 않는다 (확장이 저장할 때도 지운다).
"""
import collections
import csv
import datetime as dt
import json
import os
import re

FILE = "자료대조.csv"
KEYS = ["구분", "항목", "비교자료", "비교값", "장부값", "차이", "기준", "판정", "할일", "대표경고"]
LOAN_FILE = "차입금.csv"
LOAN_KEYS = ["차입처", "거래처코드", "계정코드", "차입일", "만기일", "상환방식", "원금", "월상환액", "자금용도", "만기근거", "매년연장",
             "이자율", "상환시작일"]   # 이자율·상환시작일: 위하고 차입금스케줄관리 (0.9.1)
MATURITY_FILE = "대출만기.csv"   # 사용자가 직접 넣는 새 만기일 (위하고 차입금현황·차입금스케줄관리에서는 만기일이 안 고쳐짐, 11/14)
MATURITY_KEYS = ["거래처코드", "차입처", "새만기일", "매년연장", "메모"]
# 사용자 2026-11-14: 신한 기술보증기금 2억 새 만기 2027-04-17, 기보 3억(만기 2027-04-21) 둘 다 매년 연장. 파일이 없을 때 처음 만들 줄
MATURITY_DEFAULT = [{"거래처코드": "256", "차입처": "신한 기술보증기금 2억", "새만기일": "2027-04-17", "매년연장": "예",
                     "메모": "2026-11-14 사용자: 연장함, 매년 연장"},
                    {"거래처코드": "1107", "차입처": "신한 기술보증기금 3억", "새만기일": "", "매년연장": "예",
                     "메모": "2026-11-14 사용자: 매년 연장 (만기일은 위하고 값 그대로)"}]
CARD_FILE = "카드사용.csv"
CARD_KEYS = ["연월", "카드", "카드코드", "공급가", "부가세", "합계", "건수", "전표처리"]

WARN = 10_000_000          # 대표 경고 기준 (render.RECON_WARN 과 같음)
SAME_TIME_MIN = 30         # 분개장과 비교 화면을 이 분 안에 받았으면 '같은 때'
STALE_DAYS = 7             # 통장 마지막 전표가 이만큼 넘게 앞서면 알림
CEO_WHAT = {"103": "통장", "253": "미지급금", "260": "차입금", "293": "차입금"}   # 대표 경고에 올리는 계정 (앞 세 자리)
NAMES = {"101": "현금", "103": "보통예금", "105": "정기예금", "108": "외상매출금", "208": "차량운반구", "209": "감가상각누계액",
         "212": "비품", "962": "임차보증금", "257": "가수금", "133": "선급비용", "136": "선납세금", "131": "선급금", "135": "부가세대급금",
         "253": "미지급금", "254": "예수금", "255": "부가세예수금", "260": "단기차입금", "262": "미지급비용", "293": "장기차입금"}


# ───────────── 공통 ─────────────
def _num(v):
    try:
        return int(round(float(str(v).replace(",", "").strip() or 0)))
    except (TypeError, ValueError):
        return 0


def _code(v):
    s = "".join(str(v or "").split())
    return (s.lstrip("0") or "0") if s.isdigit() else s


def _grp(acct):
    """계정코드 앞 세 자리 (하위 계정 묶기: 13101 → 131)."""
    s = re.sub(r"\D", "", str(acct or ""))
    return s[:3] if len(s) >= 3 else ""


def _day(t):
    t = re.sub(r"\D", "", str(t or ""))[:8]
    try:
        return dt.date(int(t[:4]), int(t[4:6]), int(t[6:8])) if len(t) == 8 else None
    except ValueError:
        return None


def _stamp(t):
    """'2026-11-13 12:10:05' 또는 '20261113121005' -> datetime."""
    s = re.sub(r"\D", "", str(t or ""))
    try:
        if len(s) >= 12:
            return dt.datetime(int(s[:4]), int(s[4:6]), int(s[6:8]), int(s[8:10]), int(s[10:12]), int(s[12:14] or 0))
        if len(s) == 8:
            return dt.datetime(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None
    return None


def _won(v):
    return "" if v is None else "{:,}".format(int(v))


def _row(kind, item, src, other, book, basis, verdict, todo="", ceo=""):
    diff = None if other is None or book is None else book - other
    return {"구분": kind, "항목": item, "비교자료": src, "비교값": "" if other is None else str(int(other)),
            "장부값": "" if book is None else str(int(book)), "차이": "" if diff is None else str(int(diff)), "기준": basis,
            "판정": verdict, "할일": todo, "대표경고": ceo}


# ───────────── 위하고 원본 파일 ─────────────
def raw_files(wehago_dir):
    """수집\\위하고 의 결산·인사·대조 원본 -> {화면코드: [(수집시각 datetime, 연도, dict)] 늦게 받은 것 먼저}.

    '지금 열린 화면 받기'로 받은 파일(연도 없음)도 화면코드로 찾는다 (카드·거래처원장·국세청 비교는 조회 조건을 사용자가 고름)."""
    out = collections.defaultdict(list)
    try:
        names = os.listdir(wehago_dir)
    except (OSError, TypeError):
        return out
    for n in names:
        if not n.endswith(".json") or "분개장" in n or "자금계획" in n:
            continue
        try:
            with open(os.path.join(wehago_dir, n), encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or "응답" not in d:
            continue
        code = str(d.get("화면코드") or "").upper()
        if not code:
            continue
        try:
            year = int(str(d.get("연도") or 0)[:4] or 0)
        except ValueError:
            year = 0
        out[code].append((_stamp(d.get("수집시각")) or dt.datetime.min, year, d))
    for code in out:
        out[code].sort(key=lambda t: t[0], reverse=True)
    return out


def _resp(d, tail):
    for r in d.get("응답") or []:
        if str(r.get("path") or "").rstrip("/").lower().endswith(tail.rstrip("/").lower()):
            return r.get("data")
    return None


def journal_files(wehago_dir):
    """확장이 받은 분개장 원본 -> [(수집시각, 기간 시작 연도, 열, 줄)] 늦게 받은 것 먼저 (dt_insert·sq_acttax2 를 보려고 직접 읽음)."""
    out = []
    try:
        names = os.listdir(wehago_dir)
    except (OSError, TypeError):
        return out
    for n in names:
        if "분개장" not in n or not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(wehago_dir, n), encoding="utf-8-sig") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or d.get("종류") != "분개장" or not isinstance(d.get("줄"), list):
            continue
        y = str((d.get("기간") or {}).get("start_date") or "")[:4]
        out.append((_stamp(d.get("수집시각")) or dt.datetime.min, int(y) if y.isdigit() else 0, d.get("열") or [], d["줄"]))
    out.sort(key=lambda t: t[0], reverse=True)
    return out


# ───────────── 장부 잔액 ─────────────
def book_balances(journal, upto=None):
    """장부(books.journal) -> {계정 앞 세 자리: 차변 − 대변} (upto 날짜까지). 손익 계정(4~9)은 빼지 않지만 비교에는 1·2·3만 쓴다."""
    bal = collections.defaultdict(int)
    for ln in journal or []:
        d = ln.get("date")
        if d is None or (upto is not None and d > upto):
            continue
        g = _grp(ln.get("account_code"))
        if g:
            bal[g] += int(ln.get("debit") or 0) - int(ln.get("credit") or 0)
    return bal


def _sign(g):
    """자산은 차변 잔액, 부채·자본은 대변 잔액으로 보인다. 더존 계정: 101~250 자산(208 차량운반구도 자산), 251~ 부채·자본,
    962 임차보증금은 자산 (2026-11-15 실제 시산표)."""
    g = str(g)[:3]
    return 1 if (g < "251" or g in BS_EXTRA) else -1


BS_EXTRA = ("962",)   # 9로 시작하지만 재무상태표 계정 (임차보증금)


def _is_bs(g):
    return g[:1] in "12" or g in BS_EXTRA


def trial_balances(d):
    """위하고 합계잔액시산표 원본 -> ({앞 세 자리: 차변 − 대변}, 조회 끝 날짜)."""
    data = _resp(d, "/sacl0104/account") or {}
    rows = data.get("main_rows") if isinstance(data, dict) else None
    bal = collections.defaultdict(int)
    for r in rows or []:
        code = re.sub(r"\D", "", str(r.get("cd_acctit") or ""))
        if len(code) != 5:
            continue   # 묶음 제목 줄
        bal[code[:3]] += _num(r.get("llp")) - _num(r.get("rrp"))
    return bal, None


def bs_balances(d):
    """위하고 재무상태표 원본 -> {앞 세 자리: 차변 − 대변 꼴}. 재무상태표 금액은 부호 없이 보이므로 계정 성격으로 부호를 붙인다."""
    data = _resp(d, "/main") or {}
    bal = collections.defaultdict(int)
    for r in (data.get("main") if isinstance(data, dict) else None) or []:
        code = re.sub(r"\D", "", str(r.get("cd_acctit") or ""))
        if len(code) != 5 or not (code[0] in "123" or code[:3] in BS_EXTRA):
            continue
        # 화면 두 칸: 왼쪽 = 계정 금액(차감 계정은 차감 금액), 오른쪽 = 소계·순액 (2026-11-15 실제: 차량운반구 왼쪽 취득가·오른쪽 0,
        # 감가상각누계액 왼쪽 누계·오른쪽 장부가액). 왼쪽이 있으면 왼쪽을 쓴다
        left = str(r.get("mn_bungae_left") or "").strip()
        v = _num(left) if left else _num(r.get("mn_bungae_right") or r.get("mn_bungae"))
        nm = str(r.get("nm_acctit") or "")
        contra = "누계" in nm or "충당금" in nm   # 감가상각누계액·대손충당금: 자산 쪽 차감
        bal[code[:3]] += (-v if contra else v) * _sign(code)
    return bal


def _compare_balances(rows, src, other, book, same_time, basis):
    keys = sorted(set(k for k in other if _is_bs(k)) | set(k for k in CEO_WHAT))
    n_same = n_diff = 0
    for g in keys:
        o, b = other.get(g, 0), book.get(g, 0)
        if o == 0 and b == 0:
            continue
        s = _sign(g)
        name = NAMES.get(g, "계정 %s" % g)
        if o == b:
            n_same += 1
            continue
        n_diff += 1
        big = abs(b - o) > WARN
        if same_time:
            verdict, todo = "다름", "위하고 %s 와 장부 %s 잔액이 다릅니다. 분개장을 다시 받아 같은 때 비교하고, 그래도 다르면 빠진·겹친 전표를 찾으세요." % (src, name)
        else:
            verdict, todo = "참고", "받은 시각이 달라 그 사이 들어간 전표 때문일 수 있습니다. '모두 받기'로 함께 다시 받으면 정확히 비교됩니다."
        rows.append(_row("잔액", name, src, o * s, b * s, basis, verdict, todo,
                         "예" if (same_time and big and g in CEO_WHAT) else ""))
    rows.append(_row("잔액", "계정 잔액 요약", src, None, None, basis,
                     "같음" if not n_diff else ("다름" if same_time else "참고"),
                     "" if not n_diff else "같은 계정 %d개, 다른 계정 %d개" % (n_same, n_diff)))


# ───────────── 제안 1·9 시산표·재무상태표·손익 ─────────────
def balances_rows(journal, raw, jstamp):
    rows = []
    tb = (raw.get("SACL0104") or [None])[0]
    if tb:
        when, year, d = tb
        other, _ = trial_balances(d)
        if other:
            same = bool(jstamp and when and abs((when - jstamp).total_seconds()) <= SAME_TIME_MIN * 60)
            upto = when.date() if when != dt.datetime.min else None
            basis = "시산표 %s · 분개장 %s 받음%s" % (_hm(when), _hm(jstamp), "" if same else " (받은 시각 다름)")
            _compare_balances(rows, "합계잔액시산표", other, book_balances(journal, upto), same, basis)
    for when, year, d in raw.get("SACL0105") or []:
        if not year:
            continue
        other = bs_balances(d)
        if not other:
            continue
        this_year = year >= (jstamp.year if jstamp else dt.date.today().year)
        same = (not this_year) or bool(jstamp and abs((when - jstamp).total_seconds()) <= SAME_TIME_MIN * 60)
        upto = dt.date(year, 12, 31) if not this_year else (when.date() if when != dt.datetime.min else None)
        basis = ("%d년 말 (결산 끝난 해)" % year) if not this_year else ("재무상태표 %s · 분개장 %s 받음" % (_hm(when), _hm(jstamp)))
        _compare_balances(rows, "재무상태표 %d" % year, other, book_balances(journal, upto), same, basis)
    pl = (raw.get("SACL0106") or [None])[0]
    if pl:
        when, year, d = pl
        rows.extend(pl_rows(journal, d, when, jstamp))
    return rows


def _hm(t):
    return t.strftime("%m-%d %H:%M") if t and t != dt.datetime.min else "모름"


PL_GROUPS = {"61000": ("매출액", "4"), "65000": ("판매비와 관리비", "8")}


def pl_rows(journal, d, when, jstamp):
    """위하고 손익계산서(당기 mn_total2) ↔ 장부 같은 해 매출(4…)·판관비(8…)."""
    rows = []
    data = d.get("응답") or []
    lines = None
    for r in data:
        if "/sacl0106/0" in str(r.get("path") or ""):
            lines = r.get("data")
    if not isinstance(lines, list) or when == dt.datetime.min:
        return rows
    year = when.year
    same = bool(jstamp and abs((when - jstamp).total_seconds()) <= SAME_TIME_MIN * 60)
    for ln in lines:
        gr = str(ln.get("cd_gr") or "")
        if gr not in PL_GROUPS or str(ln.get("cd_acctit") or "0") not in ("0", ""):
            continue
        name, first = PL_GROUPS[gr]
        other = _num(ln.get("mn_total2"))
        book = 0
        for j in journal or []:
            dd = j.get("date")
            c = re.sub(r"\D", "", str(j.get("account_code") or ""))
            if dd is None or dd.year != year or dd > when.date() or not c.startswith(first):
                continue
            book += (int(j.get("credit") or 0) - int(j.get("debit") or 0)) * (1 if first == "4" else -1)
        small = abs(other - book) < 100_000   # 2026-11-15 실제: 위하고 손익계산서 판관비가 같은 때 시산표 합보다 1,200원 큼(끝전)
        verdict = "같음" if other == book else ("다름" if same and not small else "참고")
        rows.append(_row("손익", "%d년 %s" % (year, name), "손익계산서", other, book,
                         "손익계산서 %s · 분개장 %s 받음" % (_hm(when), _hm(jstamp)), verdict,
                         "" if verdict == "같음" else ("10만 원 안쪽 끝전 차이입니다 (위하고 손익계산서 표시 차이)." if small
                                                      else "결산 대체 전표(매출원가 대체 등)나 받은 시각 차이일 수 있습니다.")))
    return rows


# ───────────── 제안 4·5 분개장 입력 시각·지난 수집 비교 ─────────────
def journal_rows(jfiles, asof):
    rows = []
    cur = [f for f in jfiles if f[1] == (asof.year if asof else 0)] or jfiles[:1]
    if not cur:
        return rows
    when, year, cols, lines = cur[0]
    ix = {c: i for i, c in enumerate(cols)}
    if "dt_insert" in ix:
        last = max((_stamp(r[ix["dt_insert"]]) for r in lines if len(r) > ix["dt_insert"]), default=None, key=lambda x: x or dt.datetime.min)
        rows.append(_row("장부 입력", "마지막 전표 입력 시각", "분개장 입력 시각", None, None,
                         "분개장 %s 받음" % _hm(when), "참고", "장부에 마지막으로 전표를 넣은 때: %s" % _hm(last)))
    if "da_date" in ix and "cd_acctit" in ix and asof:
        bank = [_day(r[ix["da_date"]]) for r in lines if _grp(r[ix["cd_acctit"]]) == "103"]
        bank = [b for b in bank if b and b <= asof]
        lb = max(bank) if bank else None
        late = lb is None or (asof - lb).days > STALE_DAYS
        rows.append(_row("장부 입력", "통장(보통예금) 마지막 전표 날짜", "분개장", None, None, "기준일 %s" % asof.isoformat(),
                         "다름" if late else "같음",
                         ("통장 전표가 %s 까지만 들어 있습니다. 보고 숫자가 그 뒤 입출금을 모를 수 있으니 회계 입력을 확인하세요."
                          % (lb.isoformat() if lb else "없음")) if late else "통장 전표가 %s 까지 들어 있음" % lb.isoformat()))
    prev = [f for f in jfiles if f[1] == year and f[0] < when]
    if prev and "sq_acttax2" in ix:
        rows.extend(diff_rows(prev[0], cur[0]))
    return rows


def _key_rows(cols, lines):
    ix = {c: i for i, c in enumerate(cols)}
    out = {}
    for r in lines:
        if len(r) <= ix.get("sq_acttax2", 10 ** 6):
            continue
        k = str(r[ix["sq_acttax2"]])
        if k:
            out[k] = (_day(r[ix["da_date"]]) if "da_date" in ix else None, str(r[ix.get("cd_acctit", 0)]),
                      _num(r[ix["mn_bungae1"]]) if "mn_bungae1" in ix else 0, _num(r[ix["mn_bungae2"]]) if "mn_bungae2" in ix else 0)
    return out


def diff_rows(prev, cur):
    """지난 수집 ↔ 이번 수집, 줄 번호로: 지난 날짜에 새로 들어온 줄(달별), 지워진 줄, 금액·계정이 바뀐 줄."""
    pw, _, pc, pl = prev
    cw, _, cc, cl = cur
    a, b = _key_rows(pc, pl), _key_rows(cc, cl)
    cut = pw.date()
    late = collections.defaultdict(lambda: [0, 0])
    for k in set(b) - set(a):
        d = b[k][0]
        if d and d < cut:
            late[d.strftime("%Y-%m")][0] += 1
            late[d.strftime("%Y-%m")][1] += b[k][2]
    gone = [k for k in set(a) - set(b)]
    changed = [k for k in set(a) & set(b) if a[k][1:] != b[k][1:]]
    rows = []
    basis = "지난 수집 %s → 이번 %s" % (_hm(pw), _hm(cw))
    for ym in sorted(late):
        n, amt = late[ym]
        rows.append(_row("늦게 들어온 전표", "%s 전표 %d줄" % (ym, n), "지난 수집과 비교", None, amt, basis, "참고",
                         "지난 수집 뒤 %s 날짜 전표가 %d줄(차변 %s원) 새로 들어왔습니다. 지난 보고 숫자와 달라진 이유입니다."
                         % (ym, n, _won(amt))))
    if gone or changed:
        rows.append(_row("늦게 들어온 전표", "지워진 줄 %d · 바뀐 줄 %d" % (len(gone), len(changed)), "지난 수집과 비교", None, None,
                         basis, "참고", "지난 수집 뒤 지워지거나 금액·계정이 바뀐 장부 줄입니다."))
    if not late and not gone and not changed:
        rows.append(_row("늦게 들어온 전표", "지난 수집 뒤 바뀐 지난 날짜 전표 없음", "지난 수집과 비교", None, None, basis, "같음"))
    return rows


# ───────────── 제안 6 인트라넷 계산서 칸 ─────────────
PCODE = re.compile(r"\[(\d{5})\]")


def intranet_rows(journal, projects):
    """인트라넷 프로젝트 '계산서'(발행액) ↔ 장부 매출(4…) 프로젝트별. 부가세 포함으로 적은 것(×1.1)도 같다고 본다."""
    if not projects:
        return []
    book = collections.defaultdict(int)
    for ln in journal or []:
        c = re.sub(r"\D", "", str(ln.get("account_code") or ""))
        if not c.startswith("4"):
            continue
        m = PCODE.search(str(ln.get("project_name") or "")) or PCODE.search(str(ln.get("memo") or ""))
        if m:
            book[m.group(1)] += int(ln.get("credit") or 0) - int(ln.get("debit") or 0)
    rows, n_same, n_both0 = [], 0, 0
    for p in projects:
        m = PCODE.search(str(p.get("행사명") or ""))
        if not m:
            continue
        code = m.group(1)
        inv = _num(p.get("계산서"))
        b = book.get(code, 0)
        if not inv and not b:
            n_both0 += 1
            continue
        if abs(inv - b) <= 1000 or abs(inv - round(b * 1.1)) <= 1000:
            n_same += 1
            continue
        rows.append(_row("인트라넷 계산서", "[%s] %s" % (code, re.sub(r"^\s*\[\d{5}\]\s*", "", str(p.get("행사명") or ""))[:30]),
                         "인트라넷 '계산서' 칸", inv, b, "프로젝트 번호로 맞춤", "다름",
                         "인트라넷 발행액과 장부 매출이 다릅니다. 인트라넷 칸이 늦게 고쳐졌거나 장부 매출 프로젝트가 다를 수 있습니다."))
    rows.append(_row("인트라넷 계산서", "프로젝트 요약", "인트라넷 '계산서' 칸", None, None, "프로젝트 번호로 맞춤",
                     "같음" if len(rows) == 0 else "다름", "같음 %d건 · 다름 %d건 · 둘 다 없음 %d건" % (n_same, len(rows), n_both0)))
    return rows


# ───────────── 제안 7 고정자산 ─────────────
def asset_rows(journal, raw):
    got = (raw.get("SAAS0107") or [None])[0]
    if not got:
        return []
    when, year, d = got
    items = _resp(d, "/allfixlist") or []
    by_acct = collections.defaultdict(int)
    for a in items if isinstance(items, list) else []:
        if a.get("cd_fixast"):
            by_acct[str(a.get("nm_acctit") or "").strip()] += _num(a.get("mn_base")) + _num(a.get("mn_new"))
    if not by_acct:
        return []
    names = {}
    for ln in journal or []:
        names.setdefault(str(ln.get("account") or "").strip(), _grp(ln.get("account_code")))
    bal = book_balances(journal, dt.date(year, 12, 31) if year else None)
    rows = []
    for nm, cost in sorted(by_acct.items()):
        g = names.get(nm)
        b = bal.get(g) if g else None
        rows.append(_row("고정자산", nm, "고정자산관리대장 취득가", cost, b, "%d년" % year if year else "",
                         "같음" if b == cost else "다름",
                         "" if b == cost else "대장에 없는 자산을 장부로 샀거나(비품 구입 전표) 대장이 늦게 고쳐졌을 수 있습니다."))
    return rows


# ───────────── 제안 9 차입금현황 → 차입금.csv ─────────────
def read_maturity(input_dir):
    """대출만기.csv -> {거래처코드: {...}}. 파일이 없으면 사용자가 알려 준 기본 두 줄(MATURITY_DEFAULT)을 쓴다.
    변환은 사용자 파일을 만들거나 고치지 않는다 (입력양식\대출만기.csv 를 입력 폴더에 복사해 고쳐 쓴다)."""
    path = os.path.join(input_dir or "", MATURITY_FILE)
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        rows = [dict(r) for r in MATURITY_DEFAULT]
    out = {}
    for r in rows:
        k = _code(r.get("거래처코드"))
        if k:
            out[k] = {kk: (r.get(kk) or "").strip() for kk in MATURITY_KEYS}
    return out


def write_maturity_default(input_dir):
    """대출만기.csv 가 없으면 사용자가 알려 준 두 줄로 처음 만든다 (이미 있으면 건드리지 않음)."""
    path = os.path.join(input_dir or "", MATURITY_FILE)
    if not input_dir or os.path.exists(path):
        return False
    try:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, MATURITY_KEYS)
            w.writeheader()
            w.writerows(MATURITY_DEFAULT)
        return True
    except OSError:
        return False


def _iso(t):
    d = _day(t)
    return d.isoformat() if d else ""


def loan_rows(journal, raw, input_dir, asof):
    """-> (차입금.csv 줄, 자료대조 줄). 잔액은 장부, 만기·상환 방식은 위하고 차입금현황, 새 만기일은 대출만기.csv 우선."""
    got = (raw.get("SAFM0109") or [None])[0]
    over = read_maturity(input_dir)
    loans, rows = [], []
    acct = {}
    bal = collections.defaultdict(int)
    for ln in journal or []:
        g = _grp(ln.get("account_code"))
        if g in ("260", "293"):
            k = _code(ln.get("vendor_code"))
            acct.setdefault(k, re.sub(r"\D", "", str(ln.get("account_code") or "")))
            if ln.get("date") is None or asof is None or ln["date"] <= asof:
                bal[k] += int(ln.get("credit") or 0) - int(ln.get("debit") or 0)
    data = _resp(got[2], "/safm0109") if got else None
    items = (data or {}).get("group01") if isinstance(data, dict) else None
    sched = {}   # 차입금스케줄관리: 거래처코드 -> (이자율, 상환 시작일)
    sg = (raw.get("SAFM0108") or [None])[0]
    for r in (sg[2].get("응답") or []) if sg else []:
        if re.search(r"/safm0108/\d+/?$", str(r.get("path") or "")) and isinstance(r.get("data"), list):
            for it in r["data"]:
                sched[_code(it.get("cd_trade"))] = (str(it.get("rt_int") or "").strip(), _iso(it.get("da_frefund")))
    for it in items or []:
        k = _code(it.get("cd_trade"))
        name = re.sub(r"_\d{6,}", "", str(it.get("nm_trade") or "")).strip()   # 이름 끝 계좌번호는 뺀다
        wmat = _iso(it.get("da_expire"))
        o = over.get(k) or {}
        mat = _iso(o.get("새만기일")) or wmat
        kind = "분할" if "분할" in str(it.get("ty_refund2") or "") else "일시"
        yearly = "예" if str(o.get("매년연장") or "").strip() in ("예", "Y", "y", "O", "o", "1") else ""
        loans.append({"차입처": name, "거래처코드": k, "계정코드": acct.get(k, ""), "차입일": _iso(it.get("da_floan")),
                      "만기일": mat, "상환방식": kind, "원금": str(_num(it.get("mn_prin"))), "월상환액": "",
                      "자금용도": str(it.get("ty_funduse2") or ""), "만기근거": "직접 입력" if _iso(o.get("새만기일")) else "차입금현황",
                      "매년연장": yearly, "이자율": (sched.get(k) or ("", ""))[0], "상환시작일": (sched.get(k) or ("", ""))[1]})
        w = _num(it.get("mn_janac"))
        b = bal.get(k)
        if b is not None and w != b:
            rows.append(_row("차입금", name, "차입금현황 잔액", w, b, "잔액은 장부를 씀", "참고",
                             "위하고 차입금 등록의 상환 기록이 장부보다 늦습니다. 보고는 장부 잔액을 씁니다."))
        md = _day(mat)
        if md and asof and md < asof:
            rows.append(_row("차입금", name, "만기일", None, None, "만기 %s" % mat, "다름",
                             "만기일이 지났습니다. 연장했으면 입력 폴더 '%s' 에 새 만기일을 넣어 주세요 (위하고에서는 안 고쳐짐)." % MATURITY_FILE))
        elif md and asof and (md - asof).days <= 92 and not yearly:
            rows.append(_row("차입금", name, "만기일", None, None, "만기 %s" % mat, "참고", "3개월 안에 만기가 옵니다. 갚을지 연장할지 정하세요."))
    for k, o in over.items():
        if not any(l["거래처코드"] == k for l in loans) and _iso(o.get("새만기일")):
            rows.append(_row("차입금", o.get("차입처") or k, "대출만기.csv", None, None, "", "참고",
                             "직접 넣은 만기일의 거래처코드가 위하고 차입금현황에 없습니다. 코드를 확인하세요."))
    return loans, rows


# ───────────── 제안 9 예적금·전자세금계산서·카드·거래처원장 ─────────────
def deposit_rows(journal, raw, asof):
    got = (raw.get("SAFM0107") or [None])[0]
    if not got:
        return []
    when, year, d = got
    items = _resp(d, "/safm0107/balance/statement")
    if not isinstance(items, list):
        return []
    tot, soon, n = 0, 0, 0
    for it in items:
        amt = _num(it.get("js_janack"))
        if not amt:
            continue
        n += 1
        tot += amt
        end = _day(it.get("js_end"))
        if end and asof and (end - asof).days <= 92:
            soon += amt
    bal = book_balances(journal, when.date() if when != dt.datetime.min else None)
    book = sum(v for g, v in bal.items() if g in ("103", "105", "106"))
    return [_row("예적금", "예적금 %d개 잔액 합" % n, "예적금현황", tot, book, "보통·정기예금 등 (장부 103·105·106)",
                 "같음" if tot == book else "참고",
                 "만기 3개월 안 정기예금 %s원 (이것만 현금성으로 봄)." % _won(soon) + ("" if tot == book else " 위하고 예적금 등록이 장부와 다릅니다(등록 안 한 통장일 수 있음)."))]


def etax_rows(journal, raw):
    """위하고 자동전표처리 '전자세금계산서'(홈택스에서 받은 매출 계산서) ↔ 장부 매출전표 (날짜·거래처코드·공급가)."""
    got = (raw.get("SAAC0103") or [None])[0]
    if not got:
        return []
    when, year, d = got
    data = _resp(d, "/saac0103/jungsang")
    items = (data or {}).get("result1") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return []
    book = collections.Counter()
    for ln in journal or []:
        c = re.sub(r"\D", "", str(ln.get("account_code") or ""))
        if c.startswith("4") and ln.get("date") is not None:
            book[(ln["date"], _code(ln.get("vendor_code")), int(ln.get("credit") or 0) - int(ln.get("debit") or 0))] += 1
    miss, miss_amt, n = 0, 0, 0
    for it in items:
        d0 = _day(it.get("da_sbook"))
        if not d0:
            continue
        n += 1
        k = (d0, _code(it.get("cd_trade")), _num(it.get("mn_mnam")))
        if book[k] > 0:
            book[k] -= 1
        else:
            miss += 1
            miss_amt += k[2]
    return [_row("계산서", "홈택스 전자세금계산서 %d건" % n, "위하고 전자세금계산서", n - miss, n, "날짜·거래처코드·공급가로 맞춤",
                 "같음" if not miss else "다름",
                 "" if not miss else "장부 매출전표와 날짜·거래처·공급가가 딱 맞지 않는 계산서 %d건(공급가 %s원). 수정 계산서·날짜 다름일 수 있습니다."
                 % (miss, _won(miss_amt)))]


def card_table(raw):
    """위하고 자동전표처리 '신용카드'(매입) 화면을 받아 두었으면 -> 카드사용.csv 줄 (달·카드별). 화면 칸은 0.9 확장에서 처음 받음."""
    out = collections.OrderedDict()
    for when, year, d in (raw.get("SAAC0105") or [])[:1]:
        for r in d.get("응답") or []:
            p = str(r.get("path") or "")
            data = r.get("data")
            if not re.search(r"/saac0105/\d+/?$", p) or not isinstance(data, dict):
                continue
            for it in data.get("data") or []:
                day = _day(it.get("da_sbook"))
                if not day:
                    continue
                card = re.sub(r"^\[[^\]]*\]", "", str(it.get("nm_ctrade") or "")).strip()
                k = (day.strftime("%Y-%m"), card, _code(it.get("cd_ctrade")))
                a = out.setdefault(k, [0, 0, 0, 0, set()])
                a[0] += _num(it.get("mn_mnam"))
                a[1] += _num(it.get("mn_vat"))
                a[2] += _num(it.get("mn_total"))
                a[3] += 1
                a[4].add(str(it.get("ty_jungstat") or ""))
    return [dict(zip(CARD_KEYS, [ym, c, cc, str(s), str(v), str(t), str(n), "·".join(sorted(st))]))
            for (ym, c, cc), (s, v, t, n, st) in sorted(out.items())]


def ledger_rows(journal, raw):
    """위하고 거래처원장(잔액) ↔ 장부 거래처별 잔액 (사용자가 계정을 골라 '지금 화면 받기'로 받은 것)."""
    rows = []
    for when, year, d in (raw.get("SABK0109") or [])[:1]:
        items = _resp(d, "/sabk0109/rmnlist")
        if not isinstance(items, list) or not items:
            continue
        acct = str(((d.get("조건") or {}).get("계정")) or "")
        book = collections.defaultdict(int)
        upto = when.date() if when != dt.datetime.min else None
        target = None
        for ln in journal or []:
            if ln.get("date") is None or (upto and ln["date"] > upto):
                continue
            book[(_grp(ln.get("account_code")), _code(ln.get("vendor_code")))] += int(ln.get("debit") or 0) - int(ln.get("credit") or 0)
        # 어느 계정 원장인지: 원장 잔액과 가장 많이 맞는 계정
        best, best_n = None, -1
        for g in set(k[0] for k in book):
            n = sum(1 for it in items if abs(book.get((g, _code(it.get("cd_trade"))), 0)) == abs(_num(it.get("mn_tr_remain"))))
            if n > best_n:
                best, best_n = g, n
        target = acct[:3] or best
        diff = [it for it in items if abs(book.get((target, _code(it.get("cd_trade"))), 0)) != abs(_num(it.get("mn_tr_remain")))]
        amt = sum(abs(abs(book.get((target, _code(it.get("cd_trade"))), 0)) - abs(_num(it.get("mn_tr_remain")))) for it in diff)
        rows.append(_row("거래처원장", "%s 거래처 %d곳" % (NAMES.get(target, "계정 %s" % target), len(items)), "거래처원장",
                         None, None, "거래처원장 %s 받음" % _hm(when), "같음" if not diff else "참고",
                         "" if not diff else "거래처별 잔액이 다른 곳 %d곳(차이 합 %s원). 받은 시각 차이일 수 있습니다." % (len(diff), _won(amt))))
    return rows


# ───────────── 0.9.1 원천세 신고·초기이월·자료수집현황·부가세 예정고지 ─────────────
def _ym(v):
    t = re.sub(r"\D", "", str(v or ""))[:6]
    return (int(t[:4]), int(t[4:6])) if len(t) == 6 and 1 <= int(t[4:6]) <= 12 else None


def withholding_rows(journal, raw):
    """위하고에 저장된 원천징수이행상황신고서(신고리스트) 소득세 ↔ 장부 예수금(254) 세무서 대변 (지급 달 기준)."""
    got = (raw.get("SWTA0101") or [None])[0]
    items = _resp(got[2], "/swta0101/sglist") if got else None
    if not isinstance(items, list):
        return []
    rows = []
    for it in items:
        a, b = _ym(it.get("ym_payfrom")), _ym(it.get("ym_payto"))
        if not a or not b:
            continue
        tax = _num(it.get("am_incomrtntax"))
        book = 0
        for ln in journal or []:
            d = ln.get("date")
            if d is None or _grp(ln.get("account_code")) != "254" or "세무서" not in str(ln.get("vendor") or ""):
                continue
            if a <= (d.year, d.month) <= b:
                book += int(ln.get("credit") or 0)
        period = "%d-%02d~%d-%02d" % (a + b)
        kind = str(it.get("mon_gu") or it.get("singo_gu") or "").strip()
        if not book:
            verdict, todo = "참고", "장부에 이 기간 세무서 예수금 줄이 없습니다 (계정·거래처를 다르게 넣었을 수 있음)."
        elif abs(book - tax) <= 1000:
            verdict, todo = "같음", ""
        else:
            verdict, todo = "다름", ("신고한 소득세와 장부 예수금(세무서)이 다릅니다. 급여·사업소득 전표의 원천세 줄이 빠졌거나 "
                                     "금액이 다른지 확인하세요 (연말정산 환급·추가 납부가 신고서에 섞였을 수도 있음). 원천세 납부 예상은 장부 기준입니다.")
        rows.append(_row("원천세", "%s 신고%s" % (period, " (%s)" % kind if kind else ""), "원천징수이행상황신고서 소득세",
                         tax, book or None, "지급 달 기준, 장부 예수금(254) 세무서 대변 합", verdict, todo))
    return rows


def opening_rows(journal, raw):
    """위하고 거래처별초기이월(올해 첫날로 넘어온 계정 잔액) ↔ 작년 말 장부 잔액."""
    rows = []
    got = (raw.get("SABM0109") or [None])[0]
    if not got:
        return rows
    when, year, d = got
    items = None
    for r in d.get("응답") or []:
        if "/sabm0109/bsflist" in str(r.get("path") or "").lower() and isinstance(r.get("data"), list):
            items = r["data"]
    if not items:
        return rows
    dates = [ln["date"] for ln in journal or [] if ln.get("date") is not None]
    y = year or (when.year if when != dt.datetime.min else None)
    if not y or not dates or min(dates) >= dt.date(y, 1, 1):
        return [_row("초기이월", "거래처별 초기이월 %d개 계정" % len(items), "거래처별초기이월", None, None, "",
                     "참고", "작년 장부가 없어 맞춰 보지 못했습니다. 작년 분개장도 받아 두면 비교합니다.")]
    book = book_balances(journal, dt.date(y - 1, 12, 31))
    other = collections.defaultdict(int)
    for it in items:
        g = _grp(it.get("cd_acctit"))
        if g:
            other[g] += _num(it.get("mn_amt"))
    n_diff = 0
    for g in sorted(other):
        o, b = other[g], book.get(g, 0) * _sign(g)
        if o == b or abs(o) == abs(b):
            continue
        n_diff += 1
        rows.append(_row("초기이월", NAMES.get(g, "계정 %s" % g), "거래처별초기이월", o, b, "%d년 말 장부 → %d년 첫날" % (y - 1, y), "다름",
                         "작년 말 장부 잔액과 올해 위하고에 넘어온 금액이 다릅니다. 이월을 다시 하거나 작년 결산 뒤 고친 전표를 확인하세요."))
    rows.append(_row("초기이월", "계정 %d개" % len(other), "거래처별초기이월", None, None, "%d년 말 장부 → %d년 첫날" % (y - 1, y),
                     "같음" if not n_diff else "다름", "" if not n_diff else "다른 계정 %d개" % n_diff))
    return rows


def collect_rows(raw, asof):
    """위하고 자료수집현황: 은행·카드·홈택스 자료가 언제까지 들어왔는지·오류."""
    got = (raw.get("SAAC0110") or [None])[0]
    if not got:
        return []
    when, year, d = got
    items = None
    for r in d.get("응답") or []:
        data = r.get("data")
        if "bottom_select" in str(r.get("path") or "") and isinstance(data, dict) and isinstance(data.get("data"), list):
            items = data["data"]
    if not items:
        return []
    rows, late, bad = [], 0, 0
    for it in items:
        name = " ".join(x for x in (str(it.get("nm_type") or "").strip(), str(it.get("nm_bank") or it.get("nm_card") or "").strip()) if x)
        end = _day(it.get("da_end"))
        err = str(it.get("error_yn") or "").upper() == "Y"
        if err:
            bad += 1
            rows.append(_row("위하고 수집", name or "자료", "자료수집현황", None, None, "마지막 %s" % (end.isoformat() if end else "?"), "다름",
                             "위하고가 이 자료를 받지 못하고 있습니다%s. 위하고에서 연결(인증서·비밀번호)을 다시 해 주세요."
                             % (" (%s)" % str(it.get("nm_errview")).strip() if it.get("nm_errview") else "")))
        elif end and asof and (asof - end).days > STALE_DAYS:
            late += 1
            rows.append(_row("위하고 수집", name or "자료", "자료수집현황", None, None, "마지막 %s" % end.isoformat(), "참고",
                             "위하고에 %s까지만 들어와 있습니다. 그 뒤 거래는 자동전표로 아직 안 올라옵니다." % end.isoformat()))
    rows.append(_row("위하고 수집", "자료 %d곳" % len(items), "자료수집현황", None, None, "%s 받음" % _hm(when),
                     "다름" if bad else ("참고" if late else "같음"), "오류 %d곳 · 늦음 %d곳" % (bad, late) if bad or late else ""))
    return rows


def vat_notice_rows(raw):
    """위하고 부가가치세 예정고지세액: 세무서가 고지한 부가세가 있으면 알림 (없으면 줄 없음)."""
    got = (raw.get("SAVF0119") or [None])[0]
    items = _resp(got[2], "/savf0119/top") if got else None
    if not isinstance(items, list) or not items:
        return []
    amt = 0
    for it in items:
        for k, v in it.items():
            if k.startswith("mn_") or k.startswith("am_"):
                amt = max(amt, _num(v))
    return [_row("부가세", "예정고지 %d건" % len(items), "부가가치세예정고지세액", amt or None, None, "", "참고",
                 "세무서가 부가세를 미리 고지했습니다. 부가세 납부 예상(장부 기준)과 다르면 고지 금액이 먼저 나갑니다.")]


# ───────────── 변환 쪽 ─────────────
def build_tables(books, input_dir, wehago_dir, asof, snap=None):
    from .convert import Table
    journal = books.journal if getattr(books, "state", "") == "ok" else []
    raw = raw_files(wehago_dir)
    jfiles = journal_files(wehago_dir)
    jstamp = jfiles[0][0] if jfiles else None
    rows, notes = [], []
    if not os.path.exists(os.path.join(input_dir or "", MATURITY_FILE)):
        notes.append("대출만기.csv 없음 — 기본값(신한 기술보증기금 2건 매년 연장, 2억은 새 만기 2027-04-17, 2026-11-14 사용자)으로 계산")
    if journal:
        rows += balances_rows(journal, raw, jstamp)
        rows += journal_rows(jfiles, asof)
        rows += intranet_rows(journal, getattr(snap, "projects", None))
        rows += asset_rows(journal, raw)
        rows += deposit_rows(journal, raw, asof)
        rows += etax_rows(journal, raw)
        rows += ledger_rows(journal, raw)
        rows += withholding_rows(journal, raw)
        rows += opening_rows(journal, raw)
    rows += collect_rows(raw, asof)
    rows += vat_notice_rows(raw)
    loans, lrows = loan_rows(journal, raw, input_dir, asof)
    rows += lrows
    cards = card_table(raw)
    n_diff = sum(1 for r in rows if r["판정"] == "다름")
    notes.append("자료 대조 %d줄 (다름 %d, 대표 경고 %d)" % (len(rows), n_diff, sum(1 for r in rows if r["대표경고"])))
    out = [Table(FILE, KEYS, rows, notes=notes) if rows else Table(FILE, KEYS, [], written=False, reason="비교할 위하고 자료 없음")]
    out.append(Table(LOAN_FILE, LOAN_KEYS, loans, notes=["위하고 차입금현황 %d건 (만기는 대출만기.csv 우선)" % len(loans)])
               if loans else Table(LOAN_FILE, LOAN_KEYS, [], written=False, reason="위하고 차입금현황 원본 없음 (기존 파일 그대로)"))
    out.append(Table(CARD_FILE, CARD_KEYS, cards, notes=["위하고 신용카드 화면 %d줄" % len(cards)])
               if cards else Table(CARD_FILE, CARD_KEYS, [], written=False, reason="위하고 신용카드 화면 원본 없음"))
    return out


# ───────────── 보고 쪽 ─────────────
def load(input_dir):
    try:
        with open(os.path.join(input_dir, FILE), encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def for_report(input_dir):
    """-> (R['recon'] 대표 경고 목록, 경영관리 표 줄). 경고는 같은 때 받은 자료끼리 1천만 원 넘게 다를 때만."""
    rows = load(input_dir)
    warn = collections.OrderedDict()
    for r in rows:
        if r.get("대표경고") != "예":
            continue
        what = CEO_WHAT.get(_grp_name(r.get("항목")), r.get("항목") or "")
        try:
            diff = int(r.get("차이") or 0)
        except ValueError:
            continue
        warn[what] = warn.get(what, 0) + diff
    return [{"what": k, "diff": v} for k, v in warn.items()], rows


def _grp_name(name):
    for g, n in NAMES.items():
        if n == name:
            return g
    return ""


def check_items(input_dir):
    """확인할 것 화면 항목: '다름' 줄마다 하나."""
    out = []
    for r in load(input_dir):
        if r.get("판정") != "다름":
            continue
        try:
            amt = int(r.get("차이") or 0) or None
        except ValueError:
            amt = None
        out.append({"id": "자료대조|%s|%s|%s" % (r.get("구분"), r.get("항목"), r.get("비교자료")), "kind": "자료 대조", "date": "",
                    "amount": amt, "vendor": "", "title": "자료 대조: %s %s (%s)" % (r.get("구분"), r.get("항목"), r.get("비교자료")),
                    "detail": "%s · %s" % (r.get("기준") or "", r.get("할일") or ""), "choices": ["원인 앎 — 그대로 둠", "고칠 것"]})
    return out


def render(rows, esc):
    """경영관리 '자료 대조' 표 (상세는 하나도 빼지 않음)."""
    if not rows:
        return ("<h2>자료 대조</h2><div class='note'>비교할 위하고 자료가 아직 없습니다. 확장에서 '모두 받기'를 누르면 시산표·차입금현황 등이 함께 "
                "받아지고, 다음 '자료 변환' 때 장부와 맞춰 봅니다.</div>")
    n = collections.Counter(r.get("판정") for r in rows)
    h = ["<h2>자료 대조</h2>",
         "<div class='note'>장부(분개장을 처음부터 더한 값)를 위하고가 계산한 화면·인트라넷과 맞춰 본 결과입니다. 보고 숫자는 장부 그대로이고, "
         "같은 때 받은 자료끼리 1천만 원 넘게 다르면 대표 보고 맨 위에 경고 한 줄이 나옵니다. "
         "같음 %d · 다름 %d · 참고 %d</div>" % (n.get("같음", 0), n.get("다름", 0), n.get("참고", 0)),
         "<table class='t'><tr><th>구분</th><th>항목</th><th>비교 자료</th><th>비교 값</th><th>장부 값</th><th>차이</th><th>판정</th><th>할 일 · 기준</th></tr>"]
    order = {"다름": 0, "참고": 1, "같음": 2}
    for r in sorted(rows, key=lambda r: order.get(r.get("판정"), 3)):
        def w(k):
            v = r.get(k)
            return _won(int(v)) if v not in ("", None) else ""
        h.append("<tr><td>%s</td><td>%s</td><td>%s</td><td class='num'>%s</td><td class='num'>%s</td><td class='num'>%s</td>"
                 "<td>%s</td><td>%s<br><span class='note'>%s</span></td></tr>"
                 % (esc(r.get("구분")), esc(r.get("항목")), esc(r.get("비교자료")), w("비교값"), w("장부값"), w("차이"),
                    esc(r.get("판정")), esc(r.get("할일")), esc(r.get("기준"))))
    h.append("</table>")
    return "".join(h)
