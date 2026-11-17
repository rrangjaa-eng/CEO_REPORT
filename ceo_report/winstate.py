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
    """이체 파일 기간 = 주간 보고의 출금 목록 기간: 기준일 다음 날 ~ 출금일.
    2차 P5-7 (2026-11-15): 출금일을 한 주보다 멀리 잡으면 보고 목록은 기준일 다음 날부터인데 이체 파일은 출금일 앞 7일만이라
    그 사이 지급이 이체 파일에서 빠졌다. 기준일을 모르면 출금일이 끝인 한 주 (출금일-6일 ~ 출금일)."""
    if asof is None:
        return payday - dt.timedelta(days=6), payday
    return min(asof + dt.timedelta(days=1), payday), payday


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
def _clean(data):
    """2차 P5-15 (2026-11-15): 값 모양이 틀린 칸(날짜 칸에 숫자, 기록 칸에 글자 등)은 버린다 — 예전엔 창이 오류로 멈췄다."""
    out = dict(data)
    for k in ("payday", "pick"):
        if k in out and not isinstance(out[k], str):
            del out[k]
    if "auto" in out and not isinstance(out["auto"], bool):
        del out["auto"]
    if "runs" in out:
        runs = out["runs"] if isinstance(out["runs"], dict) else {}
        out["runs"] = {t: r for t, r in runs.items()
                       if isinstance(r, dict) and isinstance(r.get("at"), str) and isinstance(r.get("ok"), bool)}
    return out


def load(input_dir):
    try:
        with open(os.path.join(input_dir, STATE_FILE), encoding="utf-8") as f:
            data = json.load(f)
        return _clean(data) if isinstance(data, dict) else {}
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


_READ_OK = {}   # (경로, 바뀐 시각, 크기) -> 읽히는가 (창이 자주 다시 그려도 같은 파일은 한 번만 읽음)


def _readable(path, kind):
    """2차 P1-14 (2026-11-15): 받은 시각이 최신이어도 파일이 깨졌으면 초록으로 두지 않는다. kind: 'json'(위하고 자동수집)·'snapshot'."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    key = (path, st.st_mtime, st.st_size)
    if key not in _READ_OK:
        ok = True
        try:
            if kind == "snapshot":
                from . import snapshot
                snapshot.read_snapshot(path)
            elif path.lower().endswith(".json"):
                with open(path, encoding="utf-8-sig") as f:
                    ok = isinstance(json.load(f), dict)
        except Exception:
            ok = False
        if len(_READ_OK) > 50:
            _READ_OK.clear()
        _READ_OK[key] = ok
    return _READ_OK[key]


def _broken_newest(paths, name):
    """분개장·인트라넷 중 가장 최근 파일이 읽히지 않으면 True."""
    from . import snapshot, wehago
    try:
        if name == "분개장":
            wf = [p for p in _files(paths.wehago) if wehago._kind_of(os.path.basename(p))[0] == "분개장"]
            newest = max(wf, key=lambda p: _mtime(p) or dt.datetime.min) if wf else None
            return bool(newest) and not _readable(newest, "json")
        if name.startswith("인트라넷"):
            newest = snapshot.latest_snapshot(paths.collect)
            return bool(newest) and not _readable(newest, "snapshot")
    except Exception:
        return False
    return False


def freshness(paths, asof, gate=None):
    """[{name, when, text, level, note}] — 창 오른쪽 '자료가 얼마나 최신인가' 표.
    gate (편의성 2, 2026-11-16): gate.status_dir 결과를 주면 분개장·자금계획서 줄에 장부 자료일을 같이 보이고, 대표 보고를 막는
    자료는 빨강 — 받은 시각만 보면 분개장이 '오늘'로 초록이어도 장부 자료일은 오래됐을 수 있고, 자금계획서 '없음'은 회색이었다."""
    out = []
    probs = (gate or {}).get("problems") or []
    for n, w, note in sources(paths):
        row = {"name": n, "when": w, "text": when_text(w, asof), "level": level(w, asof), "note": note}
        if w is not None and _broken_newest(paths, n):
            row["text"] += " · 파일 깨짐(읽지 못함)"
            row["level"] = "r"
            row["note"] = "가장 최근 파일을 읽지 못합니다 — 다시 받으세요"
        if gate is not None and n in ("분개장", "자금계획서"):
            d = gate.get("book_date" if n == "분개장" else "plan_date")
            if d is not None:
                row["text"] += " · 자료일 %d/%d" % (d.month, d.day)
            word = "분개장" if n == "분개장" else "자금계획"
            if any(word in p for p in probs):
                row["level"] = "r"
                row["note"] = "이 자료 때문에 대표 보고가 막힙니다"
                if "막힘" not in row["text"]:
                    row["text"] += " · 보고 막힘"
        out.append(row)
    return out


def convert_time(input_dir):
    from . import checklist
    try:   # 2차 P5-12 (2026-11-15): 초까지 적은 시작 시각이 있으면 그것 — 변환 도중 들어온 자료를 다음 자동 실행이 놓치지 않게
        with open(os.path.join(input_dir, checklist.CONVERT_FILE), encoding="utf-8") as f:
            started = (json.load(f) or {}).get("_시작") or ""
        return dt.datetime.strptime(started, "%Y-%m-%d %H:%M:%S")
    except (OSError, ValueError, TypeError, AttributeError):
        pass
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


def _edited_or(path, stem, ext):
    """2차 P4-6 (2026-11-15): 수정 모드로 저장한 '_수정' 보고가 원래 것보다 새것이면 그것 — 예전엔 수정본을 저장한 뒤
    '대표 보고 열기'를 누르면 원본이 열렸다."""
    from .editmode import SUFFIX
    ed = stem + SUFFIX + ext
    try:
        if os.path.isfile(ed) and os.path.getmtime(ed) >= os.path.getmtime(path):
            return ed
    except OSError:
        pass
    return path


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
                return _edited_or(p, "%s_%s" % (base, who), ext)
        return None
    # 경영관리용은 HTML 을 먼저: 브라우저에서 영역별로 나눠 보고 골라 인쇄 (사용자 2026-11-11). 전체 PDF 는 같은 폴더에 그대로
    return {"대표": best("대표보고"), "경영관리": best("경영관리보고", (".html", ".pdf")), "at": at, "kind": kind,
            "name": os.path.basename(base)}


# ───────────── 대표 보고를 만들 수 있는가 · 보낼 파일 (편의성 1·2·6·7, 2026-11-16) ─────────────
def _next_step(problem):
    """막는 까닭 -> 다음에 할 일 한마디."""
    p = str(problem or "")
    if "다른 회사" in p:
        return "위하고에서 이 회사 SmartA 화면을 앞에 띄우고 다시 받기"
    if "세금예상" in p or "자료 변환을 다시" in p:
        return "자료 변환 다시"
    if "자금계획" in p or "분개장" in p:
        return "위하고 화면에서 크롬 확장 '모두 받기' 뒤 자료 변환"
    return "'까닭 보기'의 안내대로"


def gate_line(G):
    """주간 보고 단추 위 한 줄 -> (글, 만들 수 있는가 · 아직 모르면 None). 판단은 보고와 같은 gate.problems."""
    from . import gate
    if G is None:
        return "대표 보고: 확인 중…", None
    probs = G.get("problems") or []
    if probs:
        more = " 외 %d가지" % (len(probs) - 1) if len(probs) > 1 else ""
        return "대표 보고: 막힘 — %s%s → %s" % (gate.short(probs[0]), more, _next_step(probs[0])), False
    days = [("분개장", G.get("book_date")), ("자금계획서", G.get("plan_date"))]
    used = " · ".join("%s %d/%d" % (n, d.month, d.day) for n, d in days if d is not None)
    return "대표 보고: 만들 수 있음" + (" (%s)" % used if used else ""), True


def reports_for(output_dir, asof):
    """이번 기준일의 '보낼 파일' -> [{label, state, at, path, why}] (주간 대표·월간 대표·팀장용·주간/월간 경영관리 순, 연간 보고를 만든 적이 있으면 연간 대표·연간 팀장용·연간 경영관리도).
    state: '만듦' · '막힘'(자료 확인에서 막혀 만들지 않음) · 'PDF 못 만듦'(HTML 만 새로 생김) · '없음'.
    막힌 보고는 예전 PDF 를 넣지 않고 '만들지 않음' 안내를 가리킨다 (path)."""
    from . import gate, pdfname
    day = asof.isoformat()
    out = []

    def one(label, base, want_pdf=True):
        page = base + ".html"
        row = {"label": label, "state": "없음", "at": None, "path": None, "why": ""}
        made = _mtime(page)
        if made is None:
            return row
        why = gate.stop_reasons(page)
        if why:
            return dict(row, state="막힘", at=made, path=page, why=gate.short(why[0]))
        if not want_pdf:
            return dict(row, state="만듦", at=made, path=page)
        pdf = pdfname.newest(base)
        pdf = _edited_or(pdf, base, ".pdf") if pdf else None
        pdf_at = _mtime(pdf) if pdf else None
        if pdf_at is None or pdf_at < made - dt.timedelta(seconds=5):   # PDF 는 HTML 바로 뒤에 만든다 — 더 오래됐으면 이번엔 못 만든 것
            return dict(row, state="PDF 못 만듦", at=made, path=page, why="HTML을 열고 인쇄 → PDF로 저장")
        return dict(row, state="만듦", at=pdf_at, path=pdf)

    out.append(one("주간 대표", os.path.join(output_dir, "%s_주간_대표보고" % day)))
    out.append(one("월간 대표", os.path.join(output_dir, "%s_월간_대표보고" % day)))
    folder = os.path.join(output_dir, "팀장용")
    def teams(label, pages):
        team = {"label": label, "state": "없음", "at": None, "path": None, "why": ""}
        if pages:
            ones = [one("", p[:-5]) for p in pages]
            at = max(r["at"] for r in ones if r["at"] is not None)
            if any(r["state"] == "막힘" for r in ones):
                team.update(state="막힘", at=at, path=pages[0], why=next(r["why"] for r in ones if r["state"] == "막힘"))
            elif all(r["state"] == "만듦" for r in ones):
                team.update(state="만듦", at=at, path=folder, why="%d팀" % len(ones))
            else:
                team.update(state="PDF 못 만듦", at=at, path=folder, why="%d팀 중 %d팀" % (len(ones), sum(1 for r in ones if r["state"] != "만듦")))
        return team
    team = teams("팀장용 (월간)", sorted(glob.glob(os.path.join(folder, "%s_월간_팀장_*.html" % day))))
    out.append(team)
    out.append(one("주간 경영관리", os.path.join(output_dir, "%s_주간_경영관리보고" % day), want_pdf=False))
    out.append(one("월간 경영관리", os.path.join(output_dir, "%s_월간_경영관리보고" % day), want_pdf=False))
    # 연간 보고도 대표용·경영관리용 두 가지 (사용자 2026-11-17 "연간보고는 왜 경영관리용과 대표용이 없어": 만들고 있었지만 이 목록에 안 보였다).
    # 만든 해가 있을 때만, 가장 최근 해 것
    years = sorted(set(os.path.basename(f)[:4] for f in glob.glob(os.path.join(output_dir, "[0-9][0-9][0-9][0-9]_연간_*보고.html"))))
    if years:
        y = years[-1]
        out.append(one("%s년 연간 대표" % y, os.path.join(output_dir, "%s_연간_대표보고" % y)))
        out.append(teams("%s년 연간 팀장용" % y, sorted(glob.glob(os.path.join(folder, "%s_연간_팀장_*.html" % y)))))
        out.append(one("%s년 연간 경영관리" % y, os.path.join(output_dir, "%s_연간_경영관리보고" % y), want_pdf=False))
    return out


def report_line(row):
    """보낼 파일 목록 한 줄: '주간 대표 — 만듦 11/16 09:12' · '월간 대표 — 막힘 (자금계획서 없음)' · '팀장용 (월간) — 없음'."""
    at = row.get("at")
    when = " %d/%d %s" % (at.month, at.day, at.strftime("%H:%M")) if at else ""
    why = " (%s)" % row["why"] if row.get("why") else ""
    return "%s — %s%s%s" % (row["label"], row["state"], when if row["state"] != "없음" else "", why)


def report_chip(S, rows, G):
    """3단계 칩 -> (글, 종류 'ok'·'now'·'wait'·'bad').
    '완료'는 이번 기준일의 대표 PDF 가 마지막 변환 뒤에 실제로 생겼을 때만. 막혔으면 빨강 '보고 만들지 않음 — 까닭'.
    예전엔 보고 파일 시각만 봐서, 막혀 '만들지 않음' 안내만 쓴 주에도 초록 '완료'였다 (편의성 1)."""
    from . import gate
    if S.get("now") != 3:
        return "변환 뒤", "wait"
    conv = S.get("convert")
    ceo = [r for r in rows or [] if r["label"] in ("주간 대표", "월간 대표") and r.get("at") is not None
           and (conv is None or r["at"] >= conv)]
    blocked = [r for r in ceo if r["state"] == "막힘"]
    if blocked:
        return "보고 만들지 않음 — %s" % (blocked[0]["why"] or "자료 확인에서 막힘"), "bad"
    done = [r for r in ceo if r["state"] == "만듦"]
    if done:
        at = max(r["at"] for r in done)
        return "완료 %d/%d %s" % (at.month, at.day, at.strftime("%H:%M")), "ok"
    if G and G.get("problems"):
        return "막힘 — %s" % gate.short(G["problems"][0]), "bad"
    return "지금 할 차례", "now"


def open_label(path):
    """대표용 열기 단추 글: 막힌 보고('만들지 않음' 안내)면 '까닭 보기'."""
    return "까닭 보기" if path and _is_stop_page(path) else "대표용 열기"


def primary_action(S, G):
    """지금 할 한 동작만 파랑 (편의성 6) -> 'collect'(인트라넷 자료 가져오기) · 'convert'(자료 변환) · 'report'(주간 보고) · None.
    대표 보고가 막히면 보고 단추도 파랗게 두지 않는다 (할 일은 위하고에서 자료 받기)."""
    now = (S or {}).get("now")
    if now == 1:
        return "collect"
    if now == 2:
        return "convert"
    if now == 3 and not (G and G.get("problems")):
        return "report"
    return None


# ───────────── 출금일 표시 · 기준일 따라가기 (운영-03 · 편의성 3·4) ─────────────
def pay_line(asof, payday_text):
    """주간 보고 단추 옆 한 줄: 실제로 쓰일 출금일과 이체 기간. 기준일이 틀리면 ''."""
    if asof is None:
        return ""
    pay = parse_day(payday_text) or next_friday(asof)
    if pay <= asof:
        return ""
    a, b = transfer_range(pay, asof)
    return "출금 %d/%d(%s) · 이체 %d/%d~%d/%d" % (pay.month, pay.day, WEEKDAYS[pay.weekday()], a.month, a.day, b.month, b.day)


def today_pay_asof(today, asof_text, payday_text):
    """금요일에 창을 켜면 기본 출금일이 다음 주 금요일이다 (결정 카드 ②: 기본은 그대로). 오늘 출금분을 만들 때 누르는
    '오늘 출금용' 단추가 넣을 기준일(어제) -> 날짜, 단추를 보일 때가 아니면 None (금요일 · 기준일=오늘 · 출금일 빈칸일 때만)."""
    if today.weekday() != 4 or (payday_text or "").strip() or parse_day(asof_text) != today:
        return None
    return today - dt.timedelta(days=1)


def roll_asof(asof_text, was_today, today):
    """창을 켜 둔 채 날이 바뀌었을 때 (편의성 4): 손대지 않은 기준일(= 창이 알던 오늘)만 새 오늘로 -> (기준일 글, 알림 한 줄 또는 '')."""
    if today != was_today and parse_day(asof_text) == was_today:
        return today.isoformat(), "날짜가 바뀌어 기준일을 오늘(%s)로 바꿨습니다" % today.isoformat()
    return asof_text, ""


def asof_note(asof_text, today):
    d = parse_day(asof_text)
    return "오늘과 다름" if d is not None and d != today else ""


# ───────────── 진행 글 (편의성 8) ─────────────
_IMPORTANT = ("[확인]", "[주의]", "없음", "못 ", "못함", "못했", "실패", "오류", "빠짐", "빠졌", "막힘", "막혀", "만들지 않",
              "확인 필요", "불일치", "──")


def important(line):
    """작업이 내는 글 중 접어 두지 않고 늘 보일 줄인가 (경고·못 한 일·구분 줄). 파일마다 'n줄 만듦'·경로는 접어 둔다."""
    t = str(line or "")
    return any(w in t for w in _IMPORTANT)


OTHER_WEHAGO = "위하고 결산·인사·카드 등 자료"
_DATA_EXT = (".json", ".xls", ".xlsx", ".csv")


def other_wehago_time(paths):
    """분개장·자금계획서 말고 수집\위하고 에 받은 자료(시산표·재무상태표·급여·원천징수·카드·차입금 등) 중 가장 새로 받은 때.
    2차 P3-16 (2026-11-15): 이것들도 변환에 쓰이는데 '다시 변환' 판단에서 빠져, 새로 받아도 다시 변환하라는 말이 없었다."""
    from . import fundplan, wehago
    out = []
    for p in _files(paths.wehago):
        n = os.path.basename(p)
        if not n.lower().endswith(_DATA_EXT):
            continue
        if wehago._kind_of(n)[0] == "분개장" or fundplan.is_fundplan_name(p) or fundplan.is_auto_plan_name(p):
            continue
        out.append(p)
    return _newest(out)


PENDING = "다운로드 폴더에 받아 둔 위하고 자료"


def steps(paths, dirs=None):
    """세 단계 상태. -> {'collect': 시각, 'convert': 시각, 'new_since': 변환 뒤 새로 받은 자료 이름들, 'report': latest_reports,
    'now': 지금 할 차례 단계 번호 (1~3)}. dirs: 크롬 다운로드 폴더 (시험용, 없으면 이 PC 크롬에서 찾음)."""
    from . import app as _app   # 2차 P1-11: 다운로드 폴더에 받아만 둔 자동수집 파일도 (변환 때 가져온다)
    pend = [w for _, w in _app.pending_downloads(dirs)]
    src = sources(paths)[:4] + [(OTHER_WEHAGO, other_wehago_time(paths), ""), (PENDING, max(pend) if pend else None, "")]
    collected = [w for n, w, _ in src if isinstance(w, dt.datetime)]
    last_collect = max(collected) if collected else None
    conv = convert_time(paths.input)
    new_since = [n for n, w, _ in src if isinstance(w, dt.datetime) and (conv is None or w > conv)]
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


# ───────────── 이체 파일 결과 (편의성 11, 2026-11-16) ─────────────
def transfer_summary(result):
    """이체 파일을 만든 결과를 이체 칸에 남길 한 줄로 -> (글, 빨강인가).
    중복 의심(전에 만든 파일에 같은 계좌·금액)이 있으면 빨강 + 그 예금주. 막혔거나 기록을 못 남겨 만들지 않았으면 그 까닭."""
    result = result or {}
    s = result.get("summary")
    if not s:
        if result.get("log_failed"):
            return "만들지 않음 — 이체기록.csv 를 닫고 다시 만드세요", True
        if result.get("blocked"):
            return "만들지 않음 — %s" % str(result["blocked"][0])[:60], True
        return "만들지 않음 — 넣을 지급 0건 (진행 상황 참고)", True
    parts = ["넣음 %d건 %s원" % (s["n"], "{:,}".format(s["total"]))]
    if s.get("blocked"):
        parts.append("못 넣음 %d건 (%s)" % (len(s["blocked"]), ", ".join(str(b[0] or "-") for b in s["blocked"][:3])
                                         + (" 외" if len(s["blocked"]) > 3 else "")))
    rep = s.get("repeats") or []
    if rep:
        parts.append("중복 의심 %d건 — %s: 전에 만든 파일에 같은 계좌·금액, 두 번 보내지 않게 확인"
                     % (len(rep), ", ".join("%s %s원" % (h, "{:,}".format(a)) for h, a, _, _ in rep[:3]) + (" 외" if len(rep) > 3 else "")))
    return " · ".join(parts), bool(rep)


# ───────────── 종료 코드를 말로 ─────────────
def blocked_reports(files):
    """만든 파일 중 자료 확인(게이트)에 막혀 '만들지 않음' 안내만 쓴 대표·팀장 보고 HTML (gate.stop_page)."""
    return [f for f in files or [] if f.lower().endswith(".html") and _is_stop_page(f)]


def pdf_states(files, kinds=("주간", "월간")):
    """만든 파일 목록 -> {'주간': 'PDF 만듦'|'PDF 못 만듦'|'막힘 (까닭)', '월간': …} — 대표 보고 기준."""
    from . import gate
    out = {}
    for k in kinds:
        mine = [f for f in files or [] if ("_%s_대표보고" % k) in os.path.basename(f)]
        stop = [f for f in mine if f.lower().endswith(".html") and _is_stop_page(f)]
        if stop:
            why = gate.stop_reasons(stop[0])
            out[k] = "막힘 (%s)" % gate.short(why[0]) if why else "막힘"
        elif any(f.lower().endswith(".pdf") for f in mine):
            out[k] = "PDF 만듦"
        else:
            out[k] = "PDF 못 만듦"
    return out


def failed_kinds(files, kinds=("주간", "월간")):
    """PDF 를 못 만든 보고 종류 (막힌 것은 뺀다 — 다시 눌러도 자료를 받기 전엔 같다)."""
    return [k for k, v in pdf_states(files, kinds).items() if v == "PDF 못 만듦"]


def outcome(task, rc, files, locked=False):
    """-> (완료인가, 한 줄). 2차 C11·C12·P5-23, 1차 E10 (2026-11-15): 종료 코드가 0이어도 대표 보고가 자료 확인에서 막혔거나
    PDF가 하나도 없으면 'PDF를 열었습니다'·'자동 완료, 다시 만들었습니다' 대신 그 사실을 말한다."""
    ok, line = rc_message(task, rc, locked)
    if rc != 0 or task not in ("주간", "월간", "연간", "예산", "자동"):
        return ok, line
    if task == "자동":   # 편의성 29: 주간·월간을 따로 — 하나만 못 만들어도 '다시 만들었습니다'로 뭉치지 않는다
        st = pdf_states(files)
        line = "자동 반영 끝 — " + " · ".join("%s %s" % (k, v) for k, v in st.items())
        bad = failed_kinds(files)
        stopped = [k for k, v in st.items() if v.startswith("막힘")]
        if bad:
            line += " → %s 보고를 다시 누르세요" % "·".join(bad)
        elif stopped:
            line += " → 맨 위 '대표 보고' 안내의 자료를 받은 뒤 다시"
        return not (bad or stopped), line
    stops = blocked_reports(files)
    pdfs = [f for f in files or [] if f.lower().endswith(".pdf")
            and ("대표" in os.path.basename(f) or "근거자료" in os.path.basename(f))]
    if stops:
        return False, ("%s 끝 — 자료 확인에서 막혀 대표 보고는 만들지 않았습니다 (%d개). 연 안내 화면의 까닭을 확인하세요"
                       % (task, len(stops)))
    if not pdfs:
        return False, "%s 끝 — 대표 보고 PDF를 찾지 못했습니다. 아래 글을 확인하세요" % task
    return ok, line


def rc_message(task, rc, locked=False):
    """-> (완료인가, 한 줄). 진행 글 맨 위에 크게 보인다.
    편의성 8 (2026-11-16): 원인별로 다음 행동을 말한다 — 인트라넷 연결 실패(5)가 '오류가 있습니다 (코드 5)'였고,
    자료 변환이 도는 중이라 못 한 것(locked)에 '출력 PDF가 열려 있으면 닫으세요'가 나왔다."""
    if rc == 0:
        nxt = {"인트라넷": "다음: 2단계 자료 변환", "변환": "다음: 확인할 것을 보고 3단계 보고 만들기",
               "주간": "PDF를 열었습니다", "월간": "PDF를 열었습니다", "연간": "PDF를 열었습니다", "정합성": "확인할 것 화면을 엽니다",
               "예산": "대표용 PDF를 열었습니다", "예산확정": "다음 월간 경영관리 보고부터 '예산 대비'가 붙습니다",
               "자동": "새 자료로 지금 현황·주간·월간 보고를 다시 만들었습니다"}
        return True, ("%s 완료. %s" % (task, nxt.get(task, ""))).strip()
    if locked:
        return False, ("%s 못 함. 자료 변환이 아직 끝나지 않았습니다 — 변환이 끝난 뒤 다시 누르세요 "
                       "(변환이 중간에 끊긴 것이면 '자료 변환'을 다시 하거나 15분 뒤 저절로 풀립니다)" % task)
    if rc == 5:
        why = "인트라넷에 연결하지 못했습니다. 인터넷(사내망) 연결을 확인한 뒤 다시 누르세요"
    elif rc == 2:
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


# ───────────── 자동 반영 표시 (편의성 27·28, 2026-11-16) ─────────────
def auto_line(state, failed="", running=False):
    """자동 반영 옆 한 줄 -> (글, 종류 idle|wait|now|bad, '다시 하기' 단추를 보일지).
    state = app.auto_state(...) 결과. failed = 지난 자동 반영이 실패한 까닭(없으면 '')."""
    if running:
        return "자동 반영: 반영 중", "now", False
    if failed:
        return "자동 반영: 실패 — %s" % failed, "bad", True
    st = state or {"state": "none", "text": "새 자료 없음"}
    kind = {"none": "idle", "collecting": "wait", "wait": "wait", "ready": "now"}.get(st.get("state"), "idle")
    if st.get("fail"):   # '위하고에서 받기'가 못 받음 (2026-11-17)
        kind = "bad"
    return "자동 반영: %s" % st.get("text", ""), kind, False


LIVE_INPUTS = ("자금일정.csv", "통장잔액.csv", "카드결제일.csv")   # 창에서 넣는 값 중 지금 현황의 숫자를 바꾸는 것


def live_stale(paths, asof=None):
    """'지금 현황' 화면을 새로 만들어야 하는가: 없거나, 못 만듦 안내이거나, 마지막 변환·창에서 넣은 값보다 오래됐을 때.
    편의성 33 (2026-11-16): 예전엔 변환 시각만 봐서, 지급·입금 예정을 넣은 뒤에도 예전 화면을 열었다."""
    from . import live
    path = os.path.join(paths.output, live.FILE)
    made = _mtime(path)
    if made is None or live.is_failed_page(path):
        return True
    if asof and live.page_asof(path) not in (None, str(asof)):   # 편의성 36: 창 기준일을 바꿨으면 그 날짜로 새로
        return True
    conv = convert_time(paths.input)
    if conv is not None and made < conv:
        return True
    return any(w is not None and w > made for w in (_mtime(os.path.join(paths.input, n)) for n in LIVE_INPUTS))


def caret_after_money(old, new, at):
    """쉼표를 다시 붙인 뒤 커서 자리 (편의성 45): 커서 왼쪽 숫자 개수가 같은 자리."""
    k = sum(1 for ch in old[:at] if ch.isdigit())
    if k == 0:
        return 0 if at == 0 else len(new) - len(new.lstrip("-"))
    seen = 0
    for i, ch in enumerate(new):
        if ch.isdigit():
            seen += 1
            if seen == k:
                return i + 1
    return len(new)
