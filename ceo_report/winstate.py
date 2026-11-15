"""창(gui.py)이 보여 줄 상태를 계산하는 곳 (사용자 2026-11-05: 창을 쓰기 편하게 다시 꾸미기).

tkinter 없이 시험할 수 있게 계산만 여기 둔다.
- 자료가 얼마나 최신인가 (freshness): 분개장·자금계획서·인트라넷·홈택스·통장 잔액이 기준일에서 며칠 지났는지
- 단계 상태 (steps): 1 자료 모으기 → 2 변환하고 확인 → 3 보고 만들기, 변환 뒤 새 자료가 들어왔는지
- 창 입력값 기억 (load/save): 출금일·가용자금 볼 날짜·마지막 작업 시각 → 입력\\창상태.json
- 합칠 거래처 후보 (merge_candidates): 그 출금일 목록에서 2건 이상 나가는 거래처
- 근거 번호 목록 (evidence_choices): 같은 기준일 경영관리 보고의 근거 번호표
- 종료 코드를 말로 (rc_message)
"""
import datetime as dt
import glob
import json
import os
import re

from . import util

STATE_FILE = "창상태.json"
FRESH_DAYS = (7, 30)   # 초록 7일 안, 주황 8~30일, 빨강 30일 넘음 (기준일 기준)
WEEKDAYS = "월화수목금토일"


# ───────────── 날짜 ─────────────
def parse_day(text):
    """'2026-11-06'·'2026.11.6'·'20261106' -> date, 아니면 None."""
    t = (text or "").strip()
    return util.date(t) if t else None


def day_label(text, empty=""):
    """날짜 칸 옆 글: '(금)' · 비면 empty · 틀리면 '형식 오류'. -> (글, 틀렸는가)."""
    if not (text or "").strip():
        return empty, False
    d = parse_day(text)
    if d is None:
        return "형식 오류", True
    return "(%s)" % WEEKDAYS[d.weekday()], False


def next_friday(asof):
    """기준일 뒤 첫 금요일 (출금일 칸을 비웠을 때 보고서가 쓰는 날)."""
    from .calc import pay_friday
    return pay_friday(asof)


def transfer_range(payday, asof=None):
    """이체 파일 기간: 출금일이 끝인 한 주 (출금일-6일 ~ 출금일). 기준일이 그 안이면 기준일 다음 날부터 (이미 지난 날은 뺌)."""
    start = payday - dt.timedelta(days=6)
    if asof is not None and asof >= start:
        start = min(asof + dt.timedelta(days=1), payday)
    return start, payday


def money(text):
    """금액 칸을 쉼표 붙은 글로: '1234000' -> '1,234,000'. 숫자가 아니면 그대로."""
    t = (text or "").replace(",", "").replace("원", "").strip()
    neg = t.startswith("-")
    if neg:
        t = t[1:]
    if not t.isdigit():
        return text
    return ("-" if neg else "") + "{:,}".format(int(t))


# ───────────── 창 입력값 기억 ─────────────
def load(input_dir):
    try:
        with open(os.path.join(input_dir, STATE_FILE), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(input_dir, **changes):
    """창상태.json 에 값을 더하거나 바꾼다. 쓰지 못하면 조용히 넘어간다 (창이 멈추지 않게)."""
    data = load(input_dir)
    data.update(changes)
    try:
        path = os.path.join(input_dir, STATE_FILE)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(path + ".tmp", path)
    except OSError:
        pass
    return data


def remember_run(input_dir, task, ok, now=None):
    runs = load(input_dir).get("runs") or {}
    runs[task] = {"at": (now or dt.datetime.now()).strftime("%Y-%m-%d %H:%M"), "ok": bool(ok)}
    return save(input_dir, runs=runs)


def report_year(day):
    """연간 보고 연도 기본값: 1~3월(결산 철)이면 지난해, 아니면 그 해 (사용자 2026-11-10)."""
    return day.year - 1 if day.month <= 3 else day.year


def start_values(input_dir, today):
    """창을 열 때 칸 값: 기준일 = 오늘, 출금일·가용자금 날짜는 지난번 값이 아직 기준일보다 뒤일 때만."""
    st = load(input_dir)
    out = {"asof": today.isoformat(), "payday": "", "pick": ""}
    for k in ("payday", "pick"):
        d = parse_day(st.get(k) or "")
        if d is not None and d > today:
            out[k] = d.isoformat()
    return out


# ───────────── 자료가 얼마나 최신인가 ─────────────
def _mtime(path):
    try:
        return dt.datetime.fromtimestamp(os.path.getmtime(path))
    except OSError:
        return None


def _newest(paths):
    best = None
    for p in paths:
        t = _mtime(p)
        if t and (best is None or t > best):
            best = t
    return best


def _files(folder):
    try:
        return [os.path.join(folder, n) for n in os.listdir(folder)
                if not n.startswith("~$") and os.path.isfile(os.path.join(folder, n))]
    except OSError:
        return []


def level(when, asof):
    """'g'·'y'·'r'·'none' — 기준일에서 며칠 지났는가."""
    if when is None:
        return "none"
    d = when.date() if isinstance(when, dt.datetime) else when
    days = (asof - d).days
    if days <= FRESH_DAYS[0]:
        return "g"
    return "y" if days <= FRESH_DAYS[1] else "r"


def when_text(when, asof):
    """'오늘 09:12' · '11/5 · 1일 전' · '없음'."""
    if when is None:
        return "없음"
    d = when.date() if isinstance(when, dt.datetime) else when
    days = (asof - d).days
    if days == 0:
        return "오늘" + (when.strftime(" %H:%M") if isinstance(when, dt.datetime) else "")
    if days < 0:
        return "%d/%d (기준일 뒤)" % (d.month, d.day)
    return "%d/%d · %d일 전" % (d.month, d.day, days)


def intranet_time(collect_dir):
    from . import snapshot
    p = snapshot.latest_snapshot(collect_dir)
    if not p:
        return None
    m = re.search(r"(\d{8}_\d{6})", os.path.basename(p))
    try:
        return dt.datetime.strptime(m.group(1), "%Y%m%d_%H%M%S") if m else _mtime(p)
    except ValueError:
        return _mtime(p)


def sources(paths):
    """[(이름, 시각 또는 날짜, 설명)] — 받은 시각은 파일을 받은(저장한) 때."""
    from . import checklist, fundplan, hometax, wehago
    wf = _files(paths.wehago)
    journal = [p for p in wf if wehago._kind_of(os.path.basename(p))[0] == "분개장"]
    plans = [p for p in wf if fundplan.is_fundplan_name(p) or fundplan.is_auto_plan_name(p)]   # 크롬 자동수집 json 도 (2026-11-10)
    bank = checklist.read_bank(paths.input)
    return [
        ("분개장", _newest(journal), "수집\\위하고 에 받은 때"),
        ("자금계획서", _newest(plans), "수집\\위하고 에 받은 때"),
        ("인트라넷 (지급요청·견적)", intranet_time(paths.collect), "인트라넷 자료 가져오기"),
        ("홈택스 세금계산서", _newest(_files(os.path.join(paths.collect, hometax.FOLDER))), "수집\\홈택스 에 받은 때"),
        ("통장 잔액", max(bank) if bank else None, "가끔 넣는 값 › 통장 잔액 대조"),
    ]


def freshness(paths, asof):
    """[{name, when, text, level, note}] — 창 오른쪽 '자료가 얼마나 최신인가' 표."""
    return [{"name": n, "when": w, "text": when_text(w, asof), "level": level(w, asof), "note": note}
            for n, w, note in sources(paths)]


def convert_time(input_dir):
    from . import checklist
    _, when = checklist._load_convert_items(input_dir)
    exact = _mtime(os.path.join(input_dir, checklist.CONVERT_FILE))
    try:
        t = dt.datetime.strptime(when[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return exact
    # 기록은 분 단위라, 같은 분에 받은 자료를 '변환 뒤 새 자료'로 잘못 보지 않게 파일을 쓴 정확한 시각을 쓴다 (2026-11-12)
    if exact is not None and t <= exact < t + dt.timedelta(minutes=1):
        return exact
    return t


def _is_stop_page(path):
    try:
        with open(path, encoding="utf-8") as f:
            return "— 만들지 않음</title>" in f.read(4000)
    except (OSError, UnicodeDecodeError):
        return False


def latest_reports(output_dir):
    """가장 최근에 만든 보고 -> {'대표': pdf 또는 html, '경영관리': html(영역별 보기) 또는 pdf, 'at': 시각, 'kind': '주간'·'월간'}."""
    found = []
    for kind in ("주간", "월간"):
        for p in glob.glob(os.path.join(output_dir, "*_%s_대표보고.html" % kind)):
            found.append((_mtime(p) or dt.datetime.min, kind, p))
    if not found:
        return {}
    at, kind, html = max(found)
    base = html[: -len("_대표보고.html")]

    def best(who, exts=(".pdf", ".html")):
        from . import pdfname
        page = "%s_%s.html" % (base, who)
        if _is_stop_page(page):   # 막힌 보고: 예전 PDF 를 최신처럼 열지 않는다 (2026-11-14 코덱스 검토) → '만들지 않음' 안내
            return page
        for ext in exts:
            # PDF 는 이름에 만든 시각이 붙는다 (사용자 2026-11-12): 같은 보고 중 가장 새로 만든 것
            p = pdfname.newest("%s_%s" % (base, who)) if ext == ".pdf" else "%s_%s%s" % (base, who, ext)
            if p and os.path.isfile(p):
                return p
        return None
    # 경영관리용은 HTML 을 먼저: 브라우저에서 영역별로 나눠 보고 골라 인쇄 (사용자 2026-11-11). 전체 PDF 는 같은 폴더에 그대로
    return {"대표": best("대표보고"), "경영관리": best("경영관리보고", (".html", ".pdf")), "at": at, "kind": kind,
            "name": os.path.basename(base)}


def steps(paths):
    """세 단계 상태. -> {'collect': 시각, 'convert': 시각, 'new_since': 변환 뒤 새로 받은 자료 이름들, 'report': latest_reports,
    'now': 지금 할 차례 단계 번호 (1~3)}."""
    src = sources(paths)
    collected = [w for n, w, _ in src[:4] if isinstance(w, dt.datetime)]
    last_collect = max(collected) if collected else None
    conv = convert_time(paths.input)
    new_since = [n for n, w, _ in src[:4] if isinstance(w, dt.datetime) and (conv is None or w > conv)]
    rep = latest_reports(paths.output)
    if last_collect is None:
        now = 1
    elif conv is None or new_since:
        now = 2
    else:
        now = 3
    return {"collect": last_collect, "convert": conv, "new_since": new_since, "report": rep, "now": now}


# ───────────── 합칠 거래처 후보 ─────────────
def merge_candidates(input_dir, asof, payday=None, rows=None):
    """그 출금일 목록에서 2건 이상 나가는 거래처 -> [{'name', 'code', 'n', 'total'}] (건수 많은 순).

    rows 를 주면 그 줄로만 센다 (시험용). 아니면 보고서와 같은 계산으로 출금 목록을 만든다 (몇 초)."""
    from .render import _vkey
    if rows is None:
        from .calc import compute
        from .data import load as load_data
        from .render import week_outflows
        R = compute(load_data(input_dir), "weekly", asof, None, None, payday)
        rows = week_outflows(R)["pay"]["rows"]
    groups = {}
    for e in rows:
        name = (e.get("desc") or "").strip()
        if not name:
            continue
        g = groups.setdefault(_vkey(name), {"name": name, "n": 0, "total": 0, "unknown": 0})
        g["n"] += 1
        if e.get("amount") is None:
            g["unknown"] += 1
        else:
            g["total"] += e["amount"]
    codes = _codes(input_dir)
    out = []
    for k, g in groups.items():
        if g["n"] >= 2:
            g["code"] = codes.get(k, "")
            out.append(g)
    return sorted(out, key=lambda g: (-g["n"], -g["total"], g["name"]))


def _codes(input_dir):
    from .render import _vkey
    try:
        from . import transfer
        return {_vkey(name): code for _, code, name, _ in transfer.account_choices(input_dir) if name}
    except Exception:   # 거래처계좌 파일이 없거나 깨져도 후보 목록은 보인다
        return {}


def merge_label(g):
    """'(주)에이치앤비 [10234] · 3건 · 4,620,000원'."""
    amt = "{:,}원".format(g["total"]) + (" + 금액 미확인 %d건" % g["unknown"] if g.get("unknown") else "")
    return "%s%s · %d건 · %s" % (g["name"], " [%s]" % g["code"] if g.get("code") else "", g["n"], amt)


# ───────────── 근거 번호 ─────────────
def evidence_choices(output_dir, kind, asof=None):
    """경영관리 보고(같은 기준일, 없으면 가장 최근)의 근거 번호표 -> (파일 이름, [(번호, 항목)])."""
    from . import evidence
    pat = os.path.join(output_dir, "*_%s_경영관리보고.html" % kind)
    found = sorted(glob.glob(pat))
    if asof is not None:
        same = [p for p in found if os.path.basename(p).startswith(asof.isoformat())]
        found = same or found
    if not found:
        return None, []
    try:
        with open(found[-1], encoding="utf-8") as f:
            idx = evidence.index_of(f.read())
    except (OSError, UnicodeDecodeError):
        return None, []
    return os.path.basename(found[-1]), [(n, t) for n, t, _ in idx]


# ───────────── 종료 코드를 말로 ─────────────
def rc_message(task, rc):
    """-> (완료인가, 한 줄). 진행 글 맨 위에 크게 보인다."""
    if rc == 0:
        nxt = {"인트라넷": "다음: 2단계 자료 변환", "변환": "다음: 확인할 것을 보고 3단계 보고 만들기",
               "주간": "PDF를 열었습니다", "월간": "PDF를 열었습니다", "연간": "PDF를 열었습니다", "정합성": "확인할 것 화면을 엽니다",
               "예산": "대표용 PDF를 열었습니다", "예산확정": "다음 월간 보고부터 '예산 대비'가 붙습니다",
               "자동": "새 자료로 지금 현황·주간·월간 보고를 다시 만들었습니다"}
        return True, ("%s 완료. %s" % (task, nxt.get(task, ""))).strip()
    if rc == 2:
        why = "날짜나 입력 파일에 문제가 있습니다. 아래 글의 안내대로 고친 뒤 다시 누르세요"
    elif rc == 3 and task in ("인트라넷", "승인검토"):
        why = "인트라넷 로그인에 실패했거나 인트라넷 화면이 바뀌었습니다. ID·비밀번호를 확인하세요"
    elif rc == 3 and task == "변환":
        why = "위하고 장부를 읽지 못했습니다. 수집\\위하고 폴더에 분개장 파일이 있는지 확인하세요"
    elif rc == 3 and task == "정합성":
        return True, "정합성 점검 끝. 맞지 않는 곳이 있어 확인할 것 화면을 엽니다"
    elif rc == 6:
        why = "예상하지 못한 오류입니다. 설정.csv 값과 입력 파일을 확인하세요"
    elif rc == 7:
        why = "파일을 쓰지 못했거나 예상하지 못한 오류입니다. 출력 PDF가 열려 있으면 닫고, 외장하드 연결을 확인하세요"
    else:
        why = "오류가 있습니다 (코드 %s). 아래 글을 확인하세요" % rc
    return False, "%s 실패. %s" % (task, why)
