"""자금계획서·분개장이 반영됐는지 확인 (사용자 2026-11-12: 자금계획서 없이 계산한 보고가 다시는 나오면 안 됨).

· 자금계획서가 없거나, 줄이 없거나, 자료일이 기준일보다 '위험_자료경과일'(기본 7일) 넘게 오래됐으면 막는다.
· 분개장(회계 반영) 자료일을 모르거나 오래됐어도 막는다.
막히면 대표·팀장 보고는 만들지 않고(같은 이름 파일은 '만들지 않음' 안내로 덮음), 경영관리 보고·지금 현황 맨 위에 큰 경고를 띄운다.
"""
import datetime as dt
import html
import os

TEST_OFF = "CEO_REPORT_TEST_GATE_OFF"   # 예전 시험(자금계획서 없는 예시 자료)만 쓰는 끄개. 프로그램(exe)·창에는 끄는 방법이 없다


def problems(R):
    """-> 막는 까닭 목록 (없으면 [])."""
    if os.environ.get(TEST_OFF) == "1":
        return []
    out = []
    days = int((R.get("settings_num") or {}).get("위험_자료경과일") or 7)
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
    return out


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


def sources_line(R):
    """보고에 쓴 자료와 날짜 한 줄."""
    parts = []
    bd = book_date(R)
    parts.append("분개장 %s" % bd.isoformat() if bd else "분개장 날짜 모름")
    fp = R.get("fundplan")
    if fp and fp.get("used"):
        months = fp.get("months") or []
        parts.append("자금계획서 %s 받음%s" % (fp["stamp"].isoformat(), (" (%s~%s)" % (min(months), max(months))) if months else ""))
    else:
        parts.append("자금계획서 미반영")
    return "사용한 자료: " + " · ".join(parts)


BANNER_CSS = (".gate{border:3px solid #c62828;background:#fdecea;color:#8e1b1b;border-radius:10px;padding:12px 16px;margin:10px 0;"
              "font-size:15px;font-weight:700}.gate ul{margin:6px 0 0;padding-left:20px;font-size:13px;font-weight:600}")


def banner(probs, what="이 보고의 자금 숫자"):
    if not probs:
        return ""
    return ("<style>%s</style><div class='gate'>자금계획서·분개장 미반영 — %s는 믿으면 안 됩니다<ul>%s</ul></div>"
            % (BANNER_CSS, html.escape(what), "".join("<li>%s</li>" % html.escape(p) for p in probs)))


def stop_page(title, probs):
    """대표·팀장 보고 대신 쓰는 '만들지 않음' 안내 (예전 파일이 최신처럼 남지 않게)."""
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'><title>%s — 만들지 않음</title><style>"
            "body{font-family:sans-serif;margin:40px;color:#1d2433}%s</style></head><body><h1>%s</h1>"
            "<div class='gate'>자금계획서·분개장이 반영되지 않아 이 보고를 만들지 않았습니다<ul>%s</ul></div>"
            "<p>위하고 확장으로 분개장과 자금계획서를 받은 뒤 자료 변환을 다시 하면 만들어집니다.</p></body></html>"
            % (html.escape(title), BANNER_CSS, html.escape(title), "".join("<li>%s</li>" % html.escape(p) for p in probs)))
