"""변환 때 하는 추가 점검 (사용자 2026-11-04 '이렇게 진행해'·금요일 급한 출금 질문).

· 중복 입력 의심 전표: 같은 날짜, 같은 계정·거래처·차변·대변 줄 묶음인데 전표번호만 다른 매입·매출 전표.
  (실제 자료: 같은 고객·같은 금액 1.4억 매출전표 2건) — 지우지 않고 목록만.
· 장부에 들어온 수동 일정 정리: 자금일정.csv 의 지급·입금 줄이 분개장 보통예금 출금·입금(같은 금액, 예정일 ±3일이면 거래처를
  적었을 때 같은 거래처, 미리(지급 14일·입금 45일 전까지)·늦게 움직였으면 거래처가 꼭 같음)과 맞으면 자금일정_지난기록.csv 로
  옮긴다 (지우지 않고 옮김 → 기록이 남는다, 사용자 2026-11-04·11-12).
결과 글자에는 건수·금액·날짜·전표번호만 쓴다 (거래처 이름은 쓰지 않음).
"""
import collections
import csv
import datetime as dt
import io
import os
import re

from . import data, util
from .wehago import norm_vendor

SCHEDULE = "자금일정.csv"
ARCHIVE = "자금일정_지난기록.csv"
MATCH_DAYS = 3
DUP_SORTS = ("매입전표", "매출전표")
DUP_MIN = 100000   # 이 금액(전표 차변 합) 미만은 중복 의심 목록에 올리지 않는다


def _sq(text):
    return re.sub(r"\s+", "", str(text or ""))


def duplicate_slips(journal):
    """-> [(날짜, [전표번호…], 전표 차변 합)] 금액 큰 순."""
    slips = collections.OrderedDict()
    from .linking import PRIOR_LAST_YEAR
    for ln in journal:
        if ln.get("date") is None or ln["date"].year <= PRIOR_LAST_YEAR:   # 지난해는 끝난 건 (사용자 2026-11-04)
            continue
        slips.setdefault((ln["date"], str(ln.get("no") or "")), []).append(ln)
    sig = collections.defaultdict(list)
    for (day, no), lines in slips.items():
        if not any((ln.get("type") or ln.get("sort") or "").strip() in DUP_SORTS for ln in lines):
            continue
        if any(ln.get("debit") is None and ln.get("credit") is None for ln in lines):
            continue
        total = sum(ln.get("debit") or 0 for ln in lines)
        if total < DUP_MIN:
            continue
        key = (day, tuple(sorted((_sq(ln.get("account_code")), ln.get("vendor_norm") or norm_vendor(ln.get("vendor")),
                                  ln.get("debit") or 0, ln.get("credit") or 0) for ln in lines)))
        sig[key].append((no, total))
    out = [(key[0], sorted(n for n, _ in v), v[0][1]) for key, v in sig.items() if len(v) > 1]
    out.sort(key=lambda x: (-x[2], x[0]))
    return out


CONTROL = {"매입전표": ("25300", "debit"), "매출전표": ("10800", "credit")}   # 거래처 상대 계정, 정산 쪽
CANCEL_DAYS = 31


def classify_duplicates(journal):
    """중복 의심 묶음을 장부로 더 따져 본다 (사용자 2026-11-05: 확인할 것이 최소한으로).

    정상으로 보는 것 (확인할 것에 올리지 않음):
      · 관리항목 프로젝트가 전표마다 다름 → 다른 행사 (프로젝트 빈 전표가 있으면 적요로)
      · 같은 거래처 같은 금액의 취소(−) 전표가 앞뒤 31일 안에 있음 → 취소 후 다시 발행
      · 전표 수만큼 같은 금액이 정산됨(미지급금 지급·외상매출금 입금) → 각각 실제로 오간 돈
    -> [(날짜, [전표번호], 금액, 판단 글, 정상 여부)] 금액 큰 순."""
    slips = collections.defaultdict(list)
    for ln in journal:
        if ln.get("date") is not None:
            slips[(ln["date"], str(ln.get("no") or ""))].append(ln)
    out = []
    for day, nos, total in duplicate_slips(journal):
        lines = slips[(day, nos[0])]
        sort = next(((ln.get("type") or ln.get("sort") or "").strip() for ln in lines
                     if (ln.get("type") or ln.get("sort") or "").strip() in CONTROL), "")
        memos = set(tuple(sorted(set(_sq(ln.get("memo")) for ln in slips[(day, n)]))) for n in nos)
        projs = set(tuple(sorted(set(_sq(ln.get("project_name")) for ln in slips[(day, n)]))) for n in nos)
        why, ok = "", False
        # 관리항목 프로젝트로 먼저 가림, 프로젝트 빈 전표가 있을 때만 적요로 (2026-11-14 사용자 "적요 대신 계정과목으로")
        # 장부 줄에 증빙(계산서) 번호 칸은 없어 쓰지 않음
        has_proj = bool(projs) and all(any(p) for p in projs)
        if len(projs) > 1 and has_proj:
            why, ok = "관리항목 프로젝트가 전표마다 다름 → 다른 거래로 봄", True
        elif not has_proj and len(memos) > 1:
            why, ok = "프로젝트 없음 · 적요가 전표마다 다름 → 다른 거래로 봄 (적요로 판단)", True
        elif sort:
            code, side = CONTROL[sort]
            other = "credit" if side == "debit" else "debit"
            party = [ln for ln in lines if _sq(ln.get("account_code")) == code]
            amt = (party[0].get(other) or 0) if party else 0
            vn = (party[0].get("vendor_norm") or norm_vendor(party[0].get("vendor"))) if party else ""
            same_v = [ln for ln in journal if ln.get("date") is not None and _sq(ln.get("account_code")) == code
                      and (ln.get("vendor_norm") or norm_vendor(ln.get("vendor"))) == vn]
            cancel = [ln for ln in same_v if (ln.get(other) or 0) == -amt and amt and abs((ln["date"] - day).days) <= CANCEL_DAYS]
            settled = [ln for ln in same_v if (ln.get(side) or 0) == amt and amt and ln["date"] >= day]
            if cancel and len(cancel) >= len(nos) - 1:   # 취소 1건은 한 번 다시 발행한 것만 설명 (코덱스 검토 2026-11-14)
                why, ok = "취소(−) 전표 %s 있음 → 취소 후 다시 발행으로 봄" % ", ".join(sorted(str(c.get("no") or "") for c in cancel)), True
            elif len(settled) >= len(nos):
                why, ok = "같은 금액 %s %d번 → 각각 실제로 오간 돈으로 봄" % ("지급" if sort == "매입전표" else "입금", len(settled)), True
            else:
                why = "%s 같음 · 같은 금액 %s %d번 (전표 %d건) → 이중 입력 가능성 높음" % (
                    "프로젝트" if has_proj else "적요", "지급" if sort == "매입전표" else "입금", len(settled), len(nos))
        else:
            why = ("프로젝트 같음" if has_proj else "적요 같음") + " → 이중 입력 가능성"
        out.append((day, nos, total, why, ok))
    return out


def duplicate_lines(journal, limit=20):
    cls = classify_duplicates(journal)
    sus = [c for c in cls if not c[4]]
    out = ["중복 입력 의심 전표 %d묶음 (같은 날짜·계정·거래처·금액, 전표번호만 다름 · 장부로 따져 정상으로 본 %d묶음은 뺌 — 남은 것은 확인할 것 화면)"
           % (len(sus), len(cls) - len(sus))]
    for day, nos, total, why, ok in sus[:limit]:
        out.append("  중복 의심 %s 전표 %s · 전표 금액 %s · %s" % (day.isoformat(), ", ".join(nos), util.won(total), why))
    if len(sus) > limit:
        out.append("  … 그 밖 %d묶음" % (len(sus) - limit))
    for day, nos, total, why, ok in [c for c in cls if c[4]][:limit]:
        out.append("  정상으로 봄 %s 전표 %s · %s · %s" % (day.isoformat(), ", ".join(nos), util.won(total), why))
    return out


def duplicate_items(journal):
    """확인할 것 화면용 (사용자 2026-11-05: 화면에서 보고 결정 입력)."""
    out = []
    for day, nos, total, why, ok in classify_duplicates(journal):
        if ok:
            continue
        vend, vcode = "", ""
        for ln in journal:
            if ln.get("date") == day and str(ln.get("no") or "") == nos[0] and ln.get("vendor"):
                vend, vcode = ln["vendor"], (ln.get("vendor_code") or "").strip()
                break
        out.append({"id": "중복|%s|%s" % (day.isoformat(), ",".join(nos)), "kind": "중복 의심 전표", "date": day.isoformat(),
                    "amount": total, "vendor": vend, "vcode": vcode,
                    "title": "같은 날·같은 계정·거래처·금액 전표 %d건 (전표번호만 다름)" % len(nos),
                    "detail": "전표 %s · 전표 금액 %s원 · %s" % (", ".join(nos), util.won(total), why),
                    "choices": ["이중 입력 — 위하고에서 고칠 것", "정상 (별개 거래)"]})
    return out


def _bank_lines(journal, cash_codes):
    """보통예금 줄: [(날짜, 금액, 거래처 정규화, 전표번호, '지급'|'입금', 거래처 이름들, 거래처코드들)]. 대변은 출금(지급), 차변은 입금.

    거래처 이름들·코드들 = 그 전표 모든 줄(통장 줄 포함, 계정 무관)의 거래처 (2026-11-14 사용자 "적요·이름 대신 계정·거래처로"):
    통장 줄에는 은행 이름만 있고 상대 줄(미지급금·선급금·선수금 등)에 진짜 거래처가 있는 전표도 맞춘다."""
    from .wehago import norm_code
    codes = set(_sq(c) for c in cash_codes)
    slips = collections.defaultdict(list)
    for ln in journal:
        if ln.get("date") is not None:
            slips[(ln["date"], str(ln.get("no") or ""))].append(ln)
    out = []
    for ln in journal:
        if _sq(ln.get("account_code")) not in codes or ln.get("date") is None:
            continue
        vn = ln.get("vendor_norm") or norm_vendor(ln.get("vendor"))
        mates = slips.get((ln["date"], str(ln.get("no") or ""))) or [ln]
        names = frozenset(n for n in ((x.get("vendor_norm") or norm_vendor(x.get("vendor"))) for x in mates) if n)
        vcodes = frozenset(c for c in (norm_code(x.get("vendor_code")) for x in mates if str(x.get("vendor_code") or "").strip()) if c)
        if (ln.get("credit") or 0) > 0:
            out.append((ln["date"], ln["credit"], vn, str(ln.get("no") or ""), "지급", names, vcodes))
        if (ln.get("debit") or 0) > 0:
            out.append((ln["date"], ln["debit"], vn, str(ln.get("no") or ""), "입금", names, vcodes))
    return out


EARLY_DAYS = {"지급": 14, "입금": 45}   # 예정일보다 이만큼 먼저 나간·들어온 돈까지 맞춘다 (자금계획서 규칙과 같음)
_USED_RE = re.compile(r"분개장 (\d{4}-\d{2}-\d{2}) 전표 (\S+) 보통예금")


def _used_before(arc_path):
    """지난기록에 이미 쓴 통장 줄 {(날짜 글자, 전표번호, 금액)} — 다시 돌릴 때 같은 출금·입금을 다른 줄에 또 쓰지 않게."""
    used = set()
    if not os.path.exists(arc_path):
        return used
    try:
        with open(arc_path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                m = _USED_RE.search(r.get("정리 근거") or "")
                if m:
                    used.add((m.group(1), m.group(2), abs(util.num(r.get("금액")) or 0)))
    except (OSError, UnicodeDecodeError, csv.Error):
        pass
    return used


def archive_paid_schedule(input_dir, journal, book_date, cash_codes=("10300",)):
    """자금일정.csv 줄 중 통장(분개장 보통예금)에서 이미 나가거나 들어온 것을 자금일정_지난기록.csv 로 옮긴다 -> 결과 글자 줄 목록.

    사용자 2026-11-12: 직접 넣은 지급·입금 예정은 실제로 돈이 움직이면 자동으로 빠져야 한다. 같은 입출금·같은 금액이고
      · 예정일 ±3일: 두 쪽에 거래처가 있으면 같아야 함 (예전 규칙),
      · 그보다 먼저(지급 14일·입금 45일 전까지) 또는 늦게(장부 기준일까지): 거래처가 꼭 같아야 함 (다른 지급을 잘못 맞추지 않게).
    예정일이 아직 오지 않은 줄도 미리 나간·들어온 돈이 있으면 옮긴다. 통장 줄 하나는 일정 줄 하나에만 쓰고, 지난기록에 이미
    쓴 통장 줄은 다시 쓰지 않는다. 파일을 읽거나 쓸 수 없으면 아무것도 바꾸지 않고 그렇게 적는다.
    """
    path = os.path.join(input_dir, SCHEDULE)
    if not os.path.exists(path) or book_date is None:
        return []
    info = {}
    rows, ok = util.read_csv(path, data.SCHEMA[SCHEDULE], util.Issues(), info)
    if not ok or info.get("missing"):
        return ["자금일정 정리: %s를 읽지 못해 그대로 둠" % SCHEDULE]
    from .wehago import norm_code
    has_code = any("거래처코드" in r for r in rows)   # 2026-11-14 선택 칸: 있으면 다시 쓸 때도 남긴다
    arc_path = os.path.join(input_dir, ARCHIVE)
    before = _used_before(arc_path)
    bank = [b for b in _bank_lines(journal, cash_codes) if b[0] <= book_date
            and (b[0].isoformat(), b[3], b[1]) not in before]
    used = set()
    hits = {}
    order = sorted(range(len(rows)), key=lambda i: (util.date(rows[i].get("예정일"), util.Issues(), rows[i], "예정일") or dt.date.max, i))
    for i in order:
        r = rows[i]
        day = util.date(r.get("예정일"), util.Issues(), r, "예정일")
        amount = util.num(r.get("금액"))
        io_kind = (r.get("입출금") or "").strip()
        io_kind = "지급" if io_kind == "출금" else io_kind
        if io_kind not in EARLY_DAYS or day is None or not amount:
            continue
        vn = norm_vendor(r.get("거래처") or "")
        vc = norm_code(r.get("거래처코드")) if str(r.get("거래처코드") or "").strip() else ""
        best = None
        for k, (bday, bamt, bvn, bno, bio, bnames, bcodes) in enumerate(bank):
            if k in used or bio != io_kind or bamt != abs(amount):
                continue
            gap = (bday - day).days
            if gap < -EARLY_DAYS[io_kind]:
                continue   # 너무 일찍 움직인 돈은 다른 지급 (늦은 것은 장부 기준일까지 본다)
            if vc and bcodes:   # 두 쪽에 거래처코드: 코드로만 (2026-11-14 사용자 "이름 말고 코드로")
                same = vc in bcodes
                if not same:
                    continue
            else:               # 코드 없는 옛 줄: 전표 어느 줄이든 거래처 이름이 같으면 같은 거래처
                same = bool(vn) and (vn == bvn or vn in bnames)
                if abs(gap) <= MATCH_DAYS:
                    if vn and bnames and not same:
                        continue
                elif not same:
                    continue
            rank = (0 if same else 1, abs(gap))
            if best is None or rank < best[0]:
                best = (rank, k)
        if best is not None:
            used.add(best[1])
            hits[i] = best[1]
    keep, moved = [], []
    for i, r in enumerate(rows):
        if i not in hits:
            keep.append(r)
            continue
        bday, _, _, bno, bio, _, _ = bank[hits[i]]
        day = util.date(r.get("예정일"), util.Issues(), r, "예정일")
        when = "예정일 %d일 전" % (day - bday).days if bday < day - dt.timedelta(days=MATCH_DAYS) else (
            "예정일 %d일 뒤" % (bday - day).days if bday > day + dt.timedelta(days=MATCH_DAYS) else "")
        moved.append((r, "분개장 %s 전표 %s 보통예금 %s과 맞음%s" % (
            bday.isoformat(), bno, "출금" if bio == "지급" else "입금", " (%s)" % when if when else "")))
    if not moved:
        return ["자금일정 정리: 통장에서 이미 나가거나 들어온 줄 없음"]
    cols = data.SCHEMA[SCHEDULE] + (data.SCHED_OPTIONAL if has_code else [])
    # 두 파일을 임시 파일로 다 만든 뒤 바꾼다: 한쪽만 바뀌어 줄이 사라지거나 두 번 옮겨지지 않게 (코덱스 검토 2026-11-14)
    tmp, arc_tmp = path + ".tmp", arc_path + ".tmp"
    try:
        with open(path, "rb") as f:
            before = f.read()
        old_arc = b""
        if os.path.exists(arc_path):
            with open(arc_path, "rb") as f:
                old_arc = f.read()
        buf = io.StringIO()
        w = csv.writer(buf)
        if not old_arc:
            w.writerow(cols + ["정리일", "정리 근거"])
        for r, why in moved:
            w.writerow([r.get(c, "") for c in cols] + [dt.date.today().isoformat(), why])
        with open(arc_tmp, "wb") as f:
            f.write(old_arc or b"\xef\xbb\xbf")
            f.write(buf.getvalue().encode("utf-8"))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        for r in keep:
            w.writerow([r.get(c, "") for c in cols])
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            f.write(buf.getvalue())
        os.replace(tmp, path)
        try:
            os.replace(arc_tmp, arc_path)
        except OSError:
            with open(path, "wb") as f:   # 보관 파일을 못 바꾸면 자금일정도 되돌린다
                f.write(before)
            raise
    except OSError as e:
        for t in (tmp, arc_tmp):
            try:
                os.remove(t)
            except OSError:
                pass
        return ["자금일정 정리: 파일을 고치지 못해 그대로 둠 (%s — 엑셀에서 열려 있으면 닫고 다시 변환)" % type(e).__name__]
    out = ["자금일정 정리: 통장에서 이미 나가거나 들어온 %d줄 %s → %s 로 옮김" % (
        len(moved), util.won(sum(abs(util.num(r.get("금액")) or 0) for r, _ in moved)), ARCHIVE)]
    for r, why in moved:
        out.append("  옮김 %s %s원 — %s" % (r.get("예정일", ""), util.won(abs(util.num(r.get("금액")) or 0)), why))
    return out


def payable_trace(journal, payable_codes, ref=None):
    """거래처별 미지급금 장부 내역 풀이 (사용자 2026-11-05: 채팅에서 따진 만큼 프로그램이 스스로 따진다).

    미지급금 계정의 대변(+발생)·대변 음수(취소)·차변(지급)을 거래처코드별로 센다. 취소(−금액)는 31일 안의 같은 금액 발생과 짝지어 지운다.
    -> {거래처코드: {"issued": [(날짜, 금액, 전표)], "cancelled": [...], "paid": 합, "balance": 합, "text": 풀이 글}}
    """
    from .wehago import norm_code
    codes = set(_sq(c) for c in payable_codes)
    per = collections.OrderedDict()
    for ln in journal:
        if _sq(ln.get("account_code")) not in codes or ln.get("date") is None:
            continue
        if ref is not None and ln["date"] > ref:
            continue
        vc = norm_code(ln.get("vendor_code"))
        if not vc:
            continue
        e = per.setdefault(vc, {"plus": [], "minus": [], "paid": 0})
        cr, dr = ln.get("credit") or 0, ln.get("debit") or 0
        no = str(ln.get("no") or "")
        if cr > 0:
            e["plus"].append((ln["date"], cr, no))
        elif cr < 0:
            e["minus"].append((ln["date"], -cr, no))
        if dr > 0:
            e["paid"] += dr
        elif dr < 0:
            e["paid"] += dr
    out = {}
    for vc, e in per.items():
        left, cancelled = list(e["plus"]), []
        for d, amt, no in e["minus"]:
            hit = next((x for x in left if x[1] == amt and abs((x[0] - d).days) <= CANCEL_DAYS), None)
            if hit is not None:
                left.remove(hit)
                cancelled.append((hit, (d, amt, no)))
        bal = sum(x[1] for x in e["plus"]) - sum(x[1] for x in e["minus"]) - e["paid"]
        text = ""
        if cancelled:
            c = cancelled[-1]
            again = any(x[1] == c[0][1] for x in left)
            text = ("장부: %s 발생 %s원(전표 %s)을 %s 취소(전표 %s)%s → 취소분은 지워져 장부 잔액에 한 번만 잡힘 (장부는 맞음)"
                    % (c[0][0].isoformat(), util.won(c[0][1]), c[0][2], c[1][0].isoformat(), c[1][2],
                       "하고 다시 발행" if again else ""))
            if len(cancelled) > 1:
                text += " · 취소 후 재발행 %d번" % len(cancelled)
        out[vc] = {"issued": left, "cancelled": cancelled, "paid": e["paid"], "balance": bal, "text": text}
    return out
