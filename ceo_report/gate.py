"""자금계획서·분개장이 반영됐는지 확인 (사용자 2026-11-12: 자금계획서 없이 계산한 보고가 다시는 나오면 안 됨).

· 자금계획서가 없거나, 줄이 없거나, 자료일이 기준일보다 '위험_자료경과일'(기본 7일) 넘게 오래됐으면 막는다.
· 분개장(회계 반영) 자료일을 모르거나 오래됐어도 막는다.
막히면 대표·팀장 보고는 만들지 않고(같은 이름 파일은 '만들지 않음' 안내로 덮음), 경영관리 보고·지금 현황 맨 위에 큰 경고를 띄운다.
"""
import datetime as dt
import html
import os

TEST_OFF = "CEO_REPORT_TEST_GATE_OFF"   # 예전 시험(자금계획서 없는 예시 자료)만 쓰는 끄개. 프로그램(exe)·창에는 끄는 방법이 없다


def _test_off():
    """시험용 끄개. 배포 exe(묶은 프로그램)는 이 환경변수를 읽지 않는다 (안전-04·P2-1, 2026-11-15)."""
    import sys
    return os.environ.get(TEST_OFF) == "1" and not getattr(sys, "frozen", False)


def problems(R):
    """-> 막는 까닭 목록 (없으면 [])."""
    if _test_off():
        return []
    out = []
    days = max_days(R)
    fp = R.get("fundplan")
    if fp is None:
        out.append("자금계획서 없음 (수집\\위하고에 자금계획 파일이 없음 — 확장에서 '모두 받기' 또는 '바뀐 것 확인')")
    elif not fp.get("used"):
        out.append(fp.get("reason") or "자금계획서를 쓰지 못함")
    bd = book_date(R)
    if bd is None:
        out.append("분개장 자료일을 모름 (자료 변환을 다시 하세요)")
    elif (R["asof"] - bd).days > days:
        out.append("분개장 자료일 %s — 기준일보다 %d일 전 (허용 %d일)" % (bd.isoformat(), (R["asof"] - bd).days, days))
    if R.get("tax_missing"):
        out.append("세금예상.csv 가 없거나 읽지 못함 — 급여·4대보험·원천세·부가세·법인세·카드 예상이 빠져 여유 자금이 크게 보임 "
                   "(자료 변환을 다시 하세요)")
    out.extend(company_problems(R))
    if R.get("targets_problem"):   # 2차 전수조사 P6: 팀 목표를 못 읽은 채 만든 추정 예산·목표 대비를 내보내지 않는다
        out.append(R["targets_problem"])
    if R.get("sched_dropped"):     # 2차 전수조사 P13: 자금일정의 입출금 칸이 틀려 빠진 줄 — 지급이 빠지면 여유 자금이 크게 보인다
        dr = R["sched_dropped"]
        known = [a for _, _, a in dr if a is not None]
        out.append("자금일정.csv %d줄이 '입출금' 칸 값이 틀려 일정에서 빠짐 (줄 %s%s) — '입금' 또는 '지급'으로 고치세요"
                   % (len(dr), ", ".join(str(l) for l, _, _ in dr[:8]),
                      " · 금액 합 %s원" % "{:,}".format(int(sum(abs(a) for a in known))) if known else ""))
    # 2차 전수조사 P1 (사용자 2026-11-18 결정 카드, 권장안 '막음'): 새로 받고 아직 변환하지 않은 분개장·자금계획서가 있으면
    # 예전 변환 자료로 만든 대표·팀장 보고를 내지 않는다 (이체 파일은 이미 같은 경우를 막고 있었음)
    out.extend(unconverted(R.get("input_dir")))
    out.extend(asof_mismatch(R.get("input_dir"), R.get("asof")))
    return out


def conv_asof(input_dir):
    """자료 변환의 기준일과 '지난 기준일로 자른 변환'인지 (변환결과.txt). -> (날짜 또는 None, 자름 여부)."""
    import re
    from .wehago import CUT_MARK
    try:
        with open(os.path.join(input_dir, "변환결과.txt"), encoding="utf-8-sig") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError, TypeError):
        return None, False
    m = re.match(r"변환 시각 [^·]*· 기준일 (\d{4})-(\d{2})-(\d{2})", text)
    day = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    return day, CUT_MARK in text


def asof_mismatch(input_dir, asof):
    """2차 전수조사 D1 (2026-11-18): 보고 기준일과 자료 변환 기준일이 어긋나 장부 값이 다른 날 것이 되는 경우 -> 막는 까닭 목록.
    ① 보고 기준일이 변환 기준일보다 앞: 통장만 그 날로 잘리고 미수금·미지급금·차입금·세금은 변환한 날 장부 값이 들어감
    ② 변환이 지난 기준일로 잘려 있는데 보고 기준일이 그 뒤: 그 사이 전표가 빠진 숫자가 나감"""
    if not input_dir or asof is None:
        return []
    day, cut = conv_asof(input_dir)
    if day is None:
        return []
    if asof < day:
        return ["보고 기준일 %s 이 자료 변환 기준일 %s 보다 앞 — 미수금·미지급금·세금 예상이 변환한 날 장부 값으로 들어감 "
                "(창의 기준일을 %s 로 두고 '자료 변환'을 다시 한 뒤 만드세요)" % (asof.isoformat(), day.isoformat(), asof.isoformat())]
    if cut and asof > day:
        return ["자료 변환이 지난 기준일 %s 까지만 자른 장부로 되어 있음 — 그 뒤 전표가 빠진 숫자가 나감 "
                "(기준일 %s 로 '자료 변환'을 다시 한 뒤 만드세요)" % (day.isoformat(), asof.isoformat())]
    return []


def conv_time(input_dir):
    """마지막 자료 변환 시각과 실패 여부 (변환결과.txt 첫 줄 '변환 시각 …'). -> (datetime 또는 None, 실패 글 또는 '')."""
    import re
    try:
        with open(os.path.join(input_dir, "변환결과.txt"), encoding="utf-8-sig") as f:
            head = [f.readline() for _ in range(3)]
    except (OSError, UnicodeDecodeError, TypeError):
        return None, "자료 변환 기록(변환결과.txt)이 없거나 읽지 못함 — 자료 변환을 먼저 하세요"
    m = re.match(r"변환 시각 (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", head[0].strip())
    when = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") if m else None
    failed = next((ln.strip() for ln in head[1:] if ln.startswith("변환 실패")), "")
    return when, failed


NEW_SLACK = 60   # 변환 시각보다 이만큼(초) 넘게 뒤에 받은 파일만 '새 자료'


def _is_book_or_plan(name):
    return "분개장" in name or "자금계획" in name


def unconverted(input_dir, collect_dir=None, downloads=None, why="예전 자료로 만든 숫자가 나감"):
    """변환 뒤에 새로 받은 분개장·자금계획 파일 -> 막는 까닭 목록 (없으면 []).
    collect_dir: 수집\\위하고 (None 이면 입력 폴더 옆 수집\\위하고). downloads: 크롬 다운로드 폴더 목록 (None 이면 이 PC 크롬에서 찾음).
    변환 시각을 모르면(변환결과.txt 없음 — 예시 자료) 판단하지 않는다."""
    if not input_dir:
        return []
    when, _ = conv_time(input_dir)
    if when is None:
        return []
    if collect_dir is None:
        collect_dir = os.path.join(os.path.dirname(os.path.abspath(input_dir)), "수집", "위하고")
    out = []
    limit = when + dt.timedelta(seconds=NEW_SLACK)

    def text(names):
        return ", ".join(names[:3]) + (" 외 %d개" % (len(names) - 3) if len(names) > 3 else "")
    if os.path.isdir(collect_dir):
        newer = []
        for n in sorted(os.listdir(collect_dir)):
            if _is_book_or_plan(n) and n.lower().endswith((".json", ".xls", ".xlsx")):
                try:
                    t = dt.datetime.fromtimestamp(os.path.getmtime(os.path.join(collect_dir, n)))
                except (OSError, ValueError, OverflowError):
                    continue
                if t > limit:
                    newer.append(n)
        if newer:
            out.append("자료 변환(%s) 뒤에 새로 받은 파일이 있음: %s — 자료 변환을 먼저 하세요 (%s)" % (when.strftime("%m-%d %H:%M"), text(newer), why))
    try:
        from . import app as _app
        pend = _app.pending_downloads(downloads)
    except Exception:   # 다운로드 폴더를 못 읽어도 확인은 계속
        pend = []
    waiting = sorted(os.path.basename(p) for p, t in pend if _is_book_or_plan(os.path.basename(p)) and t > limit)
    if waiting:
        out.append("자료 변환(%s) 뒤에 크롬 다운로드 폴더에 받아 둔 새 파일이 있음: %s — 자료 변환을 먼저 하세요 (%s)"
                   % (when.strftime("%m-%d %H:%M"), text(waiting), why))
    return out


def unconverted_intranet(input_dir, collect_root=None):
    """변환 뒤에 새로 받은 인트라넷 자료(수집\\인트라넷_YYYYMMDD_HHMMSS) -> 막는 까닭 목록 (2차 전수조사 P19, 2026-11-18).
    지급요청 승인 상태가 바뀐 자료를 받고 변환하지 않은 채 이체 파일을 만들면 예전 승인 상태로 담긴다. 변환 시각을 모르면 판단하지 않는다."""
    import re
    if not input_dir:
        return []
    when, _ = conv_time(input_dir)
    if when is None:
        return []
    root = collect_root or os.path.join(os.path.dirname(os.path.abspath(input_dir)), "수집")
    try:
        from . import snapshot
        path = snapshot.latest_snapshot(root)
    except Exception:
        path = None
    m = re.search(r"(\d{8})_(\d{6})$", os.path.basename(path or ""))
    if not m:
        return []
    try:
        got = dt.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return []
    if got <= when + dt.timedelta(seconds=NEW_SLACK):
        return []
    return ["자료 변환(%s) 뒤에 새로 받은 인트라넷 자료가 있음: %s — 자료 변환을 먼저 하세요 (지급요청 승인 상태가 예전 것으로 담길 수 있음)"
            % (when.strftime("%m-%d %H:%M"), os.path.basename(path))]


def company_problems(R):
    """P1-1·P2-4 (2026-11-15): 위하고 SmartA 탭이 여러 회사로 열려 있으면 확장이 다른 회사 자료를 받을 수 있었다.
    받은 분개장·자금계획서에 적힌 회사가 설정 회사명이나 서로와 다르면 막는다. 회사 이름을 모르면(예전 파일·빈 설정) 막지 않는다."""
    from .wehago import same_company
    facts = R.get("auto_facts") or {}
    mine = str((R.get("settings") or {}).get("회사명") or "").strip()
    if mine in ("", "회사명"):   # 설정 기본값(빈 칸 '회사명')은 이름을 모르는 것
        mine = ""
    book = str(facts.get("book_company") or "").strip()
    plans = [str(c).strip() for c in facts.get("plan_companies") or [] if str(c).strip()]
    out = []
    if mine and book and not same_company(mine, book):
        out.append("분개장이 다른 회사(%s) 장부임 — 설정 회사명은 %s. 위하고에서 이 회사 SmartA 화면을 앞에 띄우고 다시 받으세요 "
                   "(이름만 다르게 적은 것이면 설정.csv 회사명을 위하고 회사 이름과 같게 고치세요)" % (book, mine))
    for c in plans:
        ref = book or mine
        if ref and not same_company(ref, c):
            out.append("자금계획서가 다른 회사(%s) 자료임 — %s %s. 위하고에서 이 회사 SmartA 화면을 앞에 띄우고 다시 받으세요"
                       % (c, "분개장은" if book else "설정 회사명은", ref))
    return out


MAX_DAYS = 7   # 규칙: 7일 넘게 오래된 자료로는 만들지 않는다. 설정(위험_자료경과일)은 더 짧게만 쓸 수 있다 (2026-11-14 코덱스 검토)


def max_days(R):
    try:
        v = int((R.get("settings_num") or {}).get("위험_자료경과일") or MAX_DAYS)
    except (TypeError, ValueError):
        v = MAX_DAYS
    return min(max(v, 0), MAX_DAYS)


def blank_funds(R):
    """자료가 막히면 경영관리 보고·지금 현황에서도 자금 숫자(통장 합계·여유 자금·예상 잔액·최저 잔액)를 비운다
    (사용자 2026-11-14 결정: 경고만 남김). 계산한 값은 R['_gate_hidden'] 에 옮겨 둔다(보고에는 쓰지 않음). -> 막는 까닭 목록."""
    probs = problems(R)
    if not probs or R.get("_gate_hidden") is not None:
        return probs
    hidden = {}
    s1, s2 = R.get("s1") or {}, R.get("s2") or {}
    for k in ("total", "available", "end", "start_calc", "start_bank"):
        if k in s1:
            hidden["s1." + k], s1[k] = s1[k], None
    for a in s1.get("accounts") or []:
        for k in ("balance", "available"):
            if isinstance(a, dict) and k in a:
                a[k] = None
    if "start" in s2:
        hidden["s2.start"], s2["start"] = s2["start"], None
    if isinstance(s2.get("min"), dict):
        s2["min"] = dict((m, (None, None)) for m in s2["min"])
    for p in s2.get("periods") or []:
        for mode in ("firm", "spend", "all"):   # spend = '프로젝트 지급 예상 등까지 빼면' (2026-11-14 F7)
            r = p.get(mode) or {}
            for k in ("bal", "low", "low_date", "avail", "plow", "plow_date", "pavail"):
                if k in r:
                    r[k] = None
    # 1차 점검 자금-1·E6 (2026-11-15): 구간별 계산 잔액 표·위험표의 '최저 계산 잔액 …원' 줄에도 숫자가 남았다 (예시 5.43억·5,175만)
    for b in s2.get("buckets") or []:
        if isinstance(b, dict):
            for k in ("bal_firm", "bal_all"):
                if k in b:
                    b[k] = None
    rs = R.get("risks")
    if isinstance(rs, list):
        kept = [r for r in rs if not (isinstance(r, dict) and r.get("area") == "자금" and "최저 계산 잔액" in str(r.get("fact") or ""))]
        kept.insert(0, {"level": "높음", "area": "자금", "fact": "자료 확인에서 막혀 앞으로의 잔액·여유 자금을 판단하지 않음: %s" % probs[0],
                        "action": "맨 위 경고의 자료를 받아 넣고 다시 만드세요."})
        R["risks"] = kept
    R["_gate_hidden"] = hidden
    R["_gate_probs"] = probs
    return probs


def plan_gaps(R):
    """F8 (2026-11-14): 보고 기간 안에 자금계획서를 받지 못한 달이 있는 기간 -> [(기간 이름, [빠진 달 'YYYY-MM'])].
    자금계획서를 쓰지 않은 보고(없음·오래됨)는 problems() 가 막으므로 여기선 빈 목록."""
    fp = R.get("fundplan")
    if not fp or not fp.get("used"):
        return []
    have = set(fp.get("months") or []) | set(fp.get("received") or [])   # 받았지만 줄 없는 달도 받은 달 (2026-11-15)
    out = []
    for p in (R.get("s2") or {}).get("periods") or []:
        end = p.get("end")
        if end is None:
            continue
        y, m = R["asof"].year, R["asof"].month
        lack = []
        while (y, m) <= (end.year, end.month):
            if "%d-%02d" % (y, m) not in have:
                lack.append("%d-%02d" % (y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        if lack:
            out.append((p.get("label") or "", lack))
    return out


def blank_plan_gaps(R):
    """자금계획서가 빠진 달까지 걸친 기간의 잔액·최저 잔액·여유 자금을 비운다 (그 달 지급이 빠진 채 크게 나오지 않게,
    11/12 절대 규칙과 같은 방식). 여러 번 불러도 같다. -> 경고 한 줄 ('' 이면 없음)."""
    gaps = plan_gaps(R)
    if not gaps:
        return ""
    labels = set(l for l, _ in gaps)
    for p in (R.get("s2") or {}).get("periods") or []:
        if (p.get("label") or "") in labels:
            p["plan_gap"] = True
            for mode in ("firm", "spend", "all"):
                r = p.get(mode) or {}
                for k in ("bal", "low", "low_date", "avail", "plow", "plow_date", "pavail"):
                    if k in r:
                        r[k] = None
    months = sorted(set(m for _, ms in gaps for m in ms))
    return ("자금계획서를 받지 못한 달(%s)이 있어 %s 여유 자금은 비웠습니다 — 위하고 확장에서 '모두 받기'로 그 달을 받은 뒤 다시 만드세요"
            % (", ".join(months), "·".join(l for l, _ in gaps)))


def book_date(R):
    """분개장(위하고 장부) 기준일. 변환이 입력\\자동분석.json 에 적은 것 → 없으면 자료기준일.csv 의 '회계' 줄."""
    v = (R.get("auto_facts") or {}).get("book_date")
    if v:
        try:
            return dt.date.fromisoformat(str(v)[:10])
        except ValueError:
            pass
    book = [a for a in (R.get("s7") or {}).get("asof") or [] if "회계" in (a.get("name") or "")]
    return book[0]["date"] if book and book[0].get("date") else None


WRONG_TERM_DAYS = 45   # 이보다 오래 통장 거래가 없으면 지난 기수 장부를 받은 것으로 의심 (실제 입력 지연은 90%가 17일 안)
BANK_LAG_DAYS = 7   # 계산-06 (N1): 장부의 마지막 통장 거래일이 기준일보다 이만큼 넘게 앞서면 경고 (실제: 통장→장부 중간 3일, 90%는 17일 안)


def last_bank_date(R):
    """장부에 들어간 마지막 통장 거래일 (변환이 입력\\자동분석.json 에 적은 것). 모르면 None."""
    v = (R.get("auto_facts") or {}).get("last_bank")
    try:
        return dt.date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def bank_lag_note(R):
    """계산-06 (N1, 2026-11-15): 받은 날만 보면 장부가 최신처럼 보여도 통장 거래 입력이 늦을 수 있다 (R6).
    마지막 통장 거래일이 기준일보다 7일 넘게 앞서면 대표·팀장 보고에 한 줄 (막지는 않음). 모르면 빈 글."""
    lb = last_bank_date(R)
    if lb is None:
        return ""
    gap = (R["asof"] - lb).days
    if gap <= BANK_LAG_DAYS:
        return ""
    if gap > WRONG_TERM_DAYS:   # 2차 C14 (2026-11-15): 지난 기수 화면을 오늘 받으면 받은 날만 보고 최신으로 통과했다 — 막지는 않되 크게 알림
        return ("장부의 마지막 통장 거래가 %s (기준일보다 %d일 전)입니다 — 지난 기수(작년) 분개장을 받았거나 장부 입력이 크게 밀렸습니다. "
                "위하고에서 올해 기수 분개장을 다시 받기 전에는 이 보고의 실적·잔액을 믿지 마세요." % (lb.isoformat(), gap))
    return ("장부에 들어간 마지막 통장 거래가 %s (기준일보다 %d일 전)입니다 — 그 뒤 통장 입출금은 아직 장부에 없어 실적·지급에 빠졌을 수 있습니다."
            % (lb.isoformat(), gap))


def sources_line(R):
    """보고에 쓴 자료와 날짜 한 줄."""
    parts = []
    bd = book_date(R)
    lb = last_bank_date(R)
    # 1차 점검 N13 (2026-11-15): 분개장 날짜는 위하고에서 받은 날이라 입력이 밀려도 최신처럼 보였다 — 마지막 통장 거래일도 함께
    parts.append(("분개장 %s" % bd.isoformat() + (" (통장 거래 %s까지 입력)" % lb.isoformat() if lb and lb < bd else ""))
                 if bd else "분개장 날짜 모름")
    fp = R.get("fundplan")
    if fp and fp.get("used"):
        months = fp.get("months") or []
        from .fundplan import old_note   # 2026-11-25: 지난 달만 예전 파일이면 '(2026-09은 11-19 자료)'
        note = old_note(fp, ", ", "")
        parts.append("자금계획서 %s 받음%s" % (fp["stamp"].isoformat(), (" (%s~%s%s)" % (min(months), max(months), note)) if months
                                           else old_note(fp)))
    else:
        parts.append("자금계획서 미반영")
    return "사용한 자료: " + " · ".join(parts)


BANNER_CSS = (".gate{border:3px solid #c62828;background:#fdecea;color:#8e1b1b;border-radius:10px;padding:12px 16px;margin:10px 0;"
              "font-size:15px;font-weight:700}.gate ul{margin:6px 0 0;padding-left:20px;font-size:13px;font-weight:600}")


def banner(probs, what="이 보고의 자금 숫자", blanked=True):
    """blanked: 숫자를 비웠으면 True (주간·월간 경영관리·지금 현황). 연간·예산 경영관리처럼 지난 실적이 중심이라 남겨 둔 곳은 False."""
    if not probs:
        return ""
    head = ("최신 자금계획서·장부(분개장)가 없어 %s를 비웠습니다 — 틀린 숫자를 보이지 않으려는 것입니다. 위하고 자료를 받아 다시 만드세요"
            if blanked else "최신 자금계획서·장부(분개장)가 없습니다 — %s는 믿으면 안 됩니다. 위하고 자료를 받아 다시 만드세요")
    return ("<style>%s</style><div class='gate'>%s<ul>%s</ul></div>"
            % (BANNER_CSS, head % html.escape(what), "".join("<li>%s</li>" % html.escape(p) for p in probs)))


def stop_page(title, probs):
    """대표·팀장 보고 대신 쓰는 '만들지 않음' 안내 (예전 파일이 최신처럼 남지 않게)."""
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>%s — 만들지 않음</title><style>"
            "body{font-family:sans-serif;margin:40px;color:#1d2433}%s</style></head><body><h1>%s</h1>"
            "<div class='gate'>자금계획서·분개장이 반영되지 않아 이 보고를 만들지 않았습니다<ul>%s</ul></div>"
            "<p>위하고 확장으로 분개장과 자금계획서를 받은 뒤 주간·월간 보고 단추를 누르면(자동 반영을 켜 두었으면 저절로) 만들어집니다.</p></body></html>"
            % (html.escape(title), BANNER_CSS, html.escape(title), "".join("<li>%s</li>" % html.escape(p) for p in probs)))


def short(problem):
    """막는 까닭의 짧은 이름 (창의 칩·한 줄 안내용): '자금계획서 없음 (수집…' -> '자금계획서 없음'."""
    t = str(problem or "")
    for cut in (" (", " — ", " - "):
        if cut in t:
            t = t.split(cut)[0]
    return t.strip()[:40]


def stop_reasons(page_path):
    """'만들지 않음' 안내 화면에 적힌 까닭 목록 (없거나 안내 화면이 아니면 [])."""
    import re
    try:
        with open(page_path, encoding="utf-8") as f:
            text = f.read(20000)
    except (OSError, UnicodeDecodeError):
        return []
    if "— 만들지 않음</title>" not in text:
        return []
    return [html.unescape(x) for x in re.findall(r"<li>(.*?)</li>", text, re.S)]


def status_dir(input_dir, asof):
    """창이 '대표 보고를 만들 수 있는가'를 누르기 전에 보이려고 (편의성 1·2, 2026-11-16): 보고와 같은 판단(problems)과
    장부·자금계획서 자료일. -> {'problems': [까닭], 'book_date': 날짜 또는 None, 'plan_date': 날짜 또는 None}.
    막는 조건은 여기서 정하지 않는다 — problems() 그대로다."""
    from .calc import compute
    from .data import load
    from . import insights
    try:
        R = compute(load(input_dir), "weekly", asof)
    except Exception as e:   # 계산이 안 되면 대표 보고도 만들지 않는다
        return {"problems": [] if _test_off() else ["자료를 읽지 못함 (%s)" % type(e).__name__], "book_date": None, "plan_date": None}
    R["auto_facts"] = insights.read_facts(input_dir)
    fp = R.get("fundplan") if isinstance(R.get("fundplan"), dict) else None
    return {"problems": problems(R), "book_date": book_date(R),
            "plan_date": fp.get("stamp") if fp and fp.get("used") else None}


def check_dir(input_dir, asof):
    """연간·예산처럼 주간 계산을 따로 하지 않는 보고용: 입력 폴더로 자금계획서·분개장 확인만 한다 -> 막는 까닭 목록.
    (2026-11-14 코덱스 검토: 연간·예산 대표용은 이 확인 없이 만들어졌음)"""
    if _test_off():
        return []
    return status_dir(input_dir, asof)["problems"]
