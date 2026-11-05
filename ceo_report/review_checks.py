"""변환 때 하는 추가 점검 (사용자 2026-11-04 '이렇게 진행해'·금요일 급한 출금 질문).

· 중복 입력 의심 전표: 같은 날짜, 같은 계정·거래처·차변·대변 줄 묶음인데 전표번호만 다른 매입·매출 전표.
  (실제 자료: 같은 고객·같은 금액 1.4억 매출전표 2건) — 지우지 않고 목록만.
· 장부에 들어온 수동 출금 정리: 자금일정.csv 의 지난 출금 줄이 분개장 보통예금 출금(같은 금액, 예정일 ±3일, 거래처를
  적었으면 같은 거래처)과 맞으면 자금일정_지난기록.csv 로 옮긴다 (지우지 않고 옮김 → 기록이 남는다).
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
      · 적요나 프로젝트가 전표마다 다름 → 다른 물건·다른 행사
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
        if len(memos) > 1 or len(projs) > 1:
            why, ok = "적요·프로젝트가 전표마다 다름 → 다른 거래로 봄", True
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
            if cancel:
                why, ok = "취소(−) 전표 %s 있음 → 취소 후 다시 발행으로 봄" % ", ".join(sorted(str(c.get("no") or "") for c in cancel)), True
            elif len(settled) >= len(nos):
                why, ok = "같은 금액 %s %d번 → 각각 실제로 오간 돈으로 봄" % ("지급" if sort == "매입전표" else "입금", len(settled)), True
            else:
                why = "적요·프로젝트 같음 · 같은 금액 %s %d번 (전표 %d건) → 이중 입력 가능성 높음" % (
                    "지급" if sort == "매입전표" else "입금", len(settled), len(nos))
        else:
            why = "적요·프로젝트 같음 → 이중 입력 가능성"
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
        vend = ""
        for ln in journal:
            if ln.get("date") == day and str(ln.get("no") or "") == nos[0] and ln.get("vendor"):
                vend = ln["vendor"]
                break
        out.append({"id": "중복|%s|%s" % (day.isoformat(), ",".join(nos)), "kind": "중복 의심 전표", "date": day.isoformat(),
                    "amount": total, "vendor": vend,
                    "title": "같은 날·같은 계정·거래처·금액 전표 %d건 (전표번호만 다름)" % len(nos),
                    "detail": "전표 %s · 전표 금액 %s원 · %s" % (", ".join(nos), util.won(total), why),
                    "choices": ["이중 입력 — 위하고에서 고칠 것", "정상 (별개 거래)"]})
    return out


def _bank_out(journal, cash_codes):
    """보통예금 출금 줄: [(날짜, 금액, 거래처 정규화, 전표번호)]."""
    codes = set(_sq(c) for c in cash_codes)
    out = []
    for ln in journal:
        if _sq(ln.get("account_code")) in codes and (ln.get("credit") or 0) > 0 and ln.get("date") is not None:
            out.append((ln["date"], ln["credit"], ln.get("vendor_norm") or norm_vendor(ln.get("vendor")), str(ln.get("no") or "")))
    return out


def archive_paid_schedule(input_dir, journal, book_date, cash_codes=("10300",)):
    """자금일정.csv 의 지난 출금 줄 중 장부에 들어온 것을 자금일정_지난기록.csv 로 옮긴다 -> 결과 글자 줄 목록.

    예정일이 장부 기준일(book_date) 이후인 줄은 보지 않는다 (아직 장부가 모름). 출금 하나는 일정 줄 하나에만 쓴다.
    파일을 읽거나 쓸 수 없으면 아무것도 바꾸지 않고 그렇게 적는다.
    """
    path = os.path.join(input_dir, SCHEDULE)
    if not os.path.exists(path) or book_date is None:
        return []
    info = {}
    rows, ok = util.read_csv(path, data.SCHEMA[SCHEDULE], util.Issues(), info)
    if not ok or info.get("missing"):
        return ["자금일정 정리: %s를 읽지 못해 그대로 둠" % SCHEDULE]
    bank = _bank_out(journal, cash_codes)
    used = set()
    keep, moved = [], []
    for r in rows:
        day = util.date(r.get("예정일"), util.Issues(), r, "예정일")
        amount = util.num(r.get("금액"))
        io_kind = (r.get("입출금") or "").strip()
        hit = None
        if io_kind in ("출금", "지급") and day is not None and amount is not None and day <= book_date:
            vn = norm_vendor(r.get("거래처") or "")
            for k, (bday, bamt, bvn, bno) in enumerate(bank):
                if k in used or bamt != abs(amount) or abs((bday - day).days) > MATCH_DAYS:
                    continue
                if vn and bvn and vn != bvn:
                    continue
                hit = k
                break
        if hit is None:
            keep.append(r)
            continue
        used.add(hit)
        bday, _, _, bno = bank[hit]
        moved.append((r, "분개장 %s 전표 %s 보통예금 출금과 맞음" % (bday.isoformat(), bno)))
    if not moved:
        return ["자금일정 정리: 장부에 들어온 지난 출금 줄 없음"]
    cols = data.SCHEMA[SCHEDULE]
    arc_path = os.path.join(input_dir, ARCHIVE)
    try:
        new_arc = not os.path.exists(arc_path)
        with open(arc_path, "a", encoding="utf-8-sig" if new_arc else "utf-8", newline="") as f:
            w = csv.writer(f)
            if new_arc:
                w.writerow(cols + ["정리일", "정리 근거"])
            for r, why in moved:
                w.writerow([r.get(c, "") for c in cols] + [dt.date.today().isoformat(), why])
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        for r in keep:
            w.writerow([r.get(c, "") for c in cols])
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            f.write(buf.getvalue())
        os.replace(tmp, path)
    except OSError as e:
        return ["자금일정 정리: 파일을 고치지 못해 그대로 둠 (%s — 엑셀에서 열려 있으면 닫고 다시 변환)" % type(e).__name__]
    out = ["자금일정 정리: 장부에 들어온 지난 출금 %d줄 %s → %s 로 옮김" % (
        len(moved), util.won(sum(abs(util.num(r.get("금액")) or 0) for r, _ in moved)), ARCHIVE)]
    for r, why in moved:
        out.append("  옮김 %s %s원 — %s" % (r.get("예정일", ""), util.won(abs(util.num(r.get("금액")) or 0)), why))
    return out
