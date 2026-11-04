"""자료 정합성 점검 (사용자 2026-11-04: 분개장·자금계획서·작년 분개장을 철저히 분석해 데이터 정합성이 흔들리지 않게).

`대표보고.exe --정합성 결과.txt [기준일]` 로 창 없이 돈다. 입력 폴더는 건드리지 않는다: 임시 폴더에 복사해 변환·보고서를 돌린다.
결과 파일에는 건수·합계·대조 결과만 쓴다 (거래처·사람 이름 줄은 쓰지 않음).
"""
import collections
import datetime as dt
import os
import shutil
import tempfile

from . import convert, wehago


def _won(v):
    return "{:,}".format(v) if isinstance(v, int) else str(v)


def _journal_checks(books, out):
    J = books.journal
    dated = [ln for ln in J if ln.get("date") is not None]
    out.append("## 분개장")
    for kind, e in books.files.items():
        if kind == "분개장":
            out.append("- 쓴 파일: %s (+ 지난 기수 %s)" % (e["name"], ", ".join(e.get("prior") or []) or "없음"))
    if books.unused:
        out.append("- 쓰지 않은 파일: %s" % ", ".join(books.unused))
    years = collections.Counter(ln["date"].year for ln in dated)
    out.append("- 줄 %s개 (해별 %s), 날짜 없는 줄 %d개" % (_won(len(J)), dict(sorted(years.items())), len(J) - len(dated)))
    if dated:
        out.append("- 기간 %s ~ %s" % (min(ln["date"] for ln in dated), max(ln["date"] for ln in dated)))
    slips = collections.defaultdict(lambda: [0, 0])
    unknown = 0
    for ln in J:
        if ln.get("debit") is None and ln.get("credit") is None:
            unknown += 1
        k = (ln.get("date"), ln.get("no"))
        slips[k][0] += ln.get("debit") or 0
        slips[k][1] += ln.get("credit") or 0
    bad = [k for k, v in slips.items() if v[0] != v[1]]
    out.append("- 전표 %s개 중 차변≠대변 %d개 %s, 금액 빈 줄 %d개" % (_won(len(slips)), len(bad), "OK" if not bad else "확인 필요", unknown))
    for k in bad[:10]:
        out.append("  · %s 전표 %s 차이 %s" % (k[0], k[1], _won(slips[k][0] - slips[k][1])))
    total = sum((ln.get("debit") or 0) - (ln.get("credit") or 0) for ln in J)
    out.append("- 전체 차변−대변 %s %s" % (_won(total), "OK" if total == 0 else "확인 필요"))
    start = wehago.journal_from_start(J)
    out.append("- 회사 처음(설립 자본금·전기이월)부터 있음: %s" % ("예" if start else "아니오 — 작년 분개장이 빠짐: 통장·채무 잔액을 믿을 수 없음"))
    # 해마다 말일 재무상태표가 맞는지 (자산 = 부채 + 자본 + 그해 아직 마감 안 된 손익)
    for y in sorted(years)[:-1]:
        end = dt.date(y, 12, 31)
        cls = collections.defaultdict(int)
        for ln in dated:
            if ln["date"] <= end:
                cls[str(ln.get("account_code") or "?")[:1]] += (ln.get("debit") or 0) - (ln.get("credit") or 0)
        out.append("- %d년 말 계정 첫자리별 차변−대변 합: %s (합 %s)" % (y, dict(sorted(cls.items())), _won(sum(cls.values()))))
    sorts = collections.Counter((ln.get("sort") or "").strip() for ln in J)
    out.append("- 전표 유형: %s" % dict(sorts.most_common()))
    return start


def _convert_checks(res, temp_input, out):
    out.append("## 변환 (임시 폴더, 입력 폴더는 그대로)")
    out.append("- 종료 코드 %s" % res.code)
    text = []
    p = os.path.join(temp_input, "변환결과.txt")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            text = f.read().splitlines()
    marks = collections.Counter()
    off = []
    for ln in text:
        s = ln.strip()
        if s.startswith("대조 ") and "→" in s:
            r = s.rsplit("→", 1)[-1].strip()
            marks[r] += 1
            if r != "일치":
                off.append(s)
    out.append("- 대조 %d건: %s" % (sum(marks.values()), dict(marks)))
    for s in off[:30]:
        out.append("  · " + s)
    keep = ("[확인]", "자금계획서", "보통예금 잔액", "장부 채무", "계산서 자료", "작년 분개장", "만듦", "쓰지 않음")
    out.append("## 변환 알림 (요약)")
    for ln in text:
        s = ln.strip()
        if s.startswith("알림 "):
            s = s[3:]
        if any(k in s for k in keep) and not s.startswith("미연결"):
            out.append("- " + s[:300])


def _cross_checks(temp_input, out):
    import csv
    out.append("## 파일 사이 대조")

    def rows(name):
        p = os.path.join(temp_input, name)
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    pl, ev = rows("손익.csv"), rows("증빙월별.csv")
    if pl is not None and ev is not None:
        rev = collections.defaultdict(int)
        for r in pl:
            if r.get("단위") == "회사" and (r.get("매출") or "").strip():
                rev[r["연월"]] += int(r["매출"])
        diffs = [(r["연월"], int(r["매출"] or 0) - rev.get(r["연월"], 0)) for r in ev if (r.get("매출") or "").strip()]
        bad = [d for d in diffs if d[1]]
        out.append("- 증빙(매출전표) 매출 = 손익 매출(41200): %d달 중 다른 달 %d개 %s" % (len(diffs), len(bad), bad[:12]))
    bal = rows("장부잔액.csv")
    if bal:
        last = max(r["기준일"] for r in bal)
        out.append("- 분개장 통장 잔액 %s: %s원 (계좌 %d개)" % (last, _won(sum(int(r["잔액"] or 0) for r in bal if r["기준일"] == last)),
                                                       sum(1 for r in bal if r["기준일"] == last)))
    elif bal is not None:
        out.append("- 분개장 통장 잔액: 만들지 않음 (작년 분개장 없음 등) → 계좌잔액.csv 사용")
    debts = rows("장부채무.csv")
    if debts is not None:
        tot = collections.defaultdict(int)
        for r in debts:
            tot[r.get("구분")] += int(r.get("잔액") or 0)
        out.append("- 장부 채무·정기예금 합계: %s (전기이월 %s)" % ({k: _won(v) for k, v in tot.items()},
                                                           ", ".join(sorted(set(r.get("전기이월", "") for r in debts)))))
    fp = rows("자금계획.csv")
    if fp is not None:
        by = collections.defaultdict(lambda: [0, 0])
        for r in fp:
            m = (r.get("지급예정일") or r.get("예정일") or r.get("날짜") or "")[:7]
            by[m][0] += 1
        out.append("- 자금계획.csv %d줄, 달별 줄 수 %s" % (len(fp), dict(sorted((k, v[0]) for k, v in by.items()))))


def _report_checks(tmp, temp_input, asof, out):
    from . import app
    out.append("## 보고서 만들기 (임시 폴더)")
    P = app.Paths(tmp)
    month_end = asof.replace(day=1) - dt.timedelta(days=1)
    for task, day in (("주간", asof), ("월간", month_end)):
        lines = []
        try:
            rc, files = app.run_task(task, P, lines.append, asof=day.isoformat())
        except Exception as e:   # 점검은 멈추지 않는다
            rc, files = "예외 %s" % type(e).__name__, []
        out.append("- %s %s: 종료 코드 %s, 파일 %d개" % (task, day, rc, len(files)))
        for ln in lines:
            if "확인 필요" in ln or "오류" in ln:
                out.append("  · " + ln[:200])


def run(app_dir, out_path, asof=None):
    asof = asof or dt.date.today()
    now = dt.datetime.now()
    out = ["# 자료 정합성 점검 %s (기준일 %s)" % (now.strftime("%Y-%m-%d %H:%M"), asof)]
    input_dir = os.path.join(app_dir, "입력")
    collect = os.path.join(app_dir, "수집")
    wehago_dir = os.path.join(collect, "위하고")
    tmp = tempfile.mkdtemp()
    rc = 0
    try:
        books = wehago.load_books(wehago_dir, asof, None)
        out.append("- 장부 상태: %s %s" % (books.state, books.reason[:200]))
        if books.state == "ok":
            if not _journal_checks(books, out):
                rc = 3
        temp_input = os.path.join(tmp, "입력")
        if os.path.isdir(input_dir):
            shutil.copytree(input_dir, temp_input, ignore=shutil.ignore_patterns("이전"))
        os.makedirs(os.path.join(tmp, "출력"), exist_ok=True)
        res = convert.run(temp_input, collect, wehago_dir, asof, now)
        _convert_checks(res, temp_input, out)
        _cross_checks(temp_input, out)
        if os.path.isdir(os.path.join(tmp, "수집")) is False:
            os.makedirs(os.path.join(tmp, "수집"), exist_ok=True)
        _report_checks(tmp, temp_input, asof, out)
    except Exception as e:
        out.append("점검 오류 (%s): %s" % (type(e).__name__, str(e)[:300]))
        rc = 8
    finally:
        shutil.rmtree(tmp, True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\nrc=%s\n" % rc)
    return rc
