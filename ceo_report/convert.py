"""원천자료(WEHAGO 장부 엑셀 등) → 보고서 입력 CSV 변환 (Phase 2, D-37..D-45).

변환 한 번의 흐름: 설정 읽기 → 장부 읽기 → 표(Table) 만들기 → 입력 폴더에 쓰기 → 변환결과.txt.
사람이 직접 관리하는 파일(MANUAL)은 만들지도 덮지도 않는다 (D-43). 모든 글자는 util.mask_rrn 을 거쳐 나간다 (D-45).
"""
import collections
import csv
import io
import os

from . import data, util, wehago
from .util import won

# 변환이 만드는 파일. 이 이름들만 입력 폴더에 쓸 수 있다.
GENERATED = ("손익.csv", "계산서.csv", "프로젝트.csv", "프로젝트집행.csv", "위하고대조.csv", "변환결과.txt")
# 사람이 직접 관리하는 파일: 만들지도, 쓰지도, 옮기지도 않는다.
MANUAL = ("계좌잔액.csv", "설정.csv", "지급계획.csv", "변경내역.csv", "자료기준일.csv", "프로젝트연결.csv")

# 설정.csv '변환_*' 항목과 기본값 (D-39). 계정 코드와 표시 낱말은 여기에만 있고 만드는 쪽은 cfg 로만 읽는다.
DEFAULT_CONFIG = collections.OrderedDict([
    ("revenue_codes", ("41200",)),
    ("receivable_codes", ("10800",)),
    ("direct_prefixes", ("6",)),
    ("direct_mark", "(도)"),
    ("common_prefixes", ("8",)),
    ("common_mark", "(판)"),
    ("payable_codes", ("25300", "26200")),
    ("cash_codes", ("10300",)),
    ("vat_codes", ("13500",)),
    ("closing_sorts", ("결차", "결대")),
    ("link_days", 90),
    ("card_words", ("카드",)),
])


class Config(dict):
    """read_config 결과. 일반 dict 처럼 비교된다."""
    from_file = False


Check = collections.namedtuple("Check", "label source csv")


def check_result(c):
    """원본 합계 대 CSV 합계: 둘 다 알면 같을 때 '일치', 다르면 '불일치'. 하나라도 모르면 '판단 불가'."""
    if c.source is None or c.csv is None:
        return "판단 불가"
    return "일치" if c.source == c.csv else "불일치"


class Table(object):
    """만들 CSV 한 개. written=False 는 '이 파일은 만들지 않음' (reason 에 한 줄 이유)."""

    def __init__(self, name, columns, rows, checks=(), notes=(), written=True, reason="", extra=None):
        self.name = name
        self.columns = list(columns)
        self.rows = rows
        self.checks = list(checks)
        self.notes = list(notes)
        self.written = written
        self.reason = reason
        self.extra = {} if extra is None else extra


class Result(object):
    """run 결과: code (종료 코드), lines (콘솔에 찍을 줄), tables, backup (이전 파일 폴더 또는 None)."""

    def __init__(self):
        self.code = 0
        self.lines = []
        self.tables = []
        self.backup = None


def cell_amount(v):
    """금액 칸 글자: 모르면 '' (0 아님), 아니면 쉼표 없는 정수 ('-'는 음수)."""
    return "" if v is None else str(int(v))


def cell_date(d):
    return "" if d is None else d.isoformat()


def table_bytes(table):
    """CSV 내용 (UTF-8 BOM, csv.writer). 모든 칸은 주민번호 모양을 가린다 (D-45)."""
    buf = io.StringIO(newline="")
    w = csv.writer(buf)
    w.writerow([util.mask_rrn(c) for c in table.columns])
    for row in table.rows:
        w.writerow([util.mask_rrn(row.get(c, "")) for c in table.columns])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def write_table(path, table):
    with open(path, "wb") as f:
        f.write(table_bytes(table))


def read_config(input_dir):
    """설정.csv 의 변환 항목 → (cfg, notes). 설정.csv 는 읽기만 한다."""
    return Config(DEFAULT_CONFIG), []


def read_prev(input_dir, name):
    """만들어 둔 CSV 의 이전 줄 (글자 그대로의 dict 목록, _line/_file 키 없음). 없거나 읽을 수 없으면 []."""
    cols = data.SCHEMA.get(name)
    path = os.path.join(input_dir, name)
    if cols is None or not os.path.exists(path):
        return []
    info = {}
    rows, ok = util.read_csv(path, cols, util.Issues(), info)
    if not ok or info.get("missing"):
        return []
    for r in rows:
        r.pop("_line", None)
        r.pop("_file", None)
    return rows


def _text_bytes(lines):
    return ("﻿" + "\r\n".join(util.mask_rrn(ln) for ln in lines) + "\r\n").encode("utf-8")


def _books_line(books, asof):
    if books.state != "ok":
        reason = books.reason if books.reason.startswith(books.state) else "%s — %s" % (books.state, books.reason)
        return "WEHAGO 장부: " + reason
    parts = ["WEHAGO 장부: %s" % books.state, "장부 기준일 %s" % books.book_date.isoformat()]
    late = (asof - books.book_date).days
    if late > 0:
        parts.append("기준일보다 %d일 이전" % late)
    if books.after_ref:
        parts.append("장부 기준일 이후 전표 %d건" % books.after_ref)
    for kind in wehago.KINDS:
        if kind in books.files:
            parts.append("%s %s" % (kind, books.files[kind]["name"]))
    return " · ".join(parts)


def _mismatches(tables):
    return sum(1 for t in tables if t.written for c in t.checks if check_result(c) == "불일치")


def result_lines(now, asof, books, cfg, cfg_notes, tables, backup_line, kept):
    """변환결과.txt 한 줄씩 (PATTERNS §6)."""
    out = ["변환 시각 %s · 기준일 %s" % (now.strftime("%Y-%m-%d %H:%M:%S"), asof.isoformat()),
           _books_line(books, asof),
           "인트라넷 스냅숏: 없음"]
    if cfg_notes:
        out.append("설정: 변환 항목 확인 필요 %d건" % len(cfg_notes))
        out.extend("  알림 " + n for n in cfg_notes)
    else:
        out.append("설정: 설정.csv 변환 항목 반영" if getattr(cfg, "from_file", False) else "설정: 변환 설정 기본값 사용")
    for t in tables:
        if not t.written:
            out.append("[%s] 만들지 않음 — %s" % (t.name, t.reason))
            continue
        out.append("[%s] 만듦 %d줄" % (t.name, len(t.rows)))
        for c in t.checks:
            out.append("  대조 %s: 원본 %s · CSV %s → %s" % (c.label, won(c.source), won(c.csv), check_result(c)))
        for n in t.notes:
            out.append("  알림 " + n)
    out.append(backup_line)
    out.append("손대지 않은 파일: " + (", ".join(kept) if kept else "없음"))
    missing = [m for m in MANUAL if m not in kept]
    if missing:
        out.append("없는 수동 파일 (사람이 관리, 만들지 않음): " + ", ".join(missing))
    out.append("대조 불일치 %d건" % _mismatches(tables))
    return out


def run(input_dir, collect_dir, wehago_dir, asof, now, stamp=None):
    """변환 한 번. 장부·스냅숏·파일 문제로 예외를 내지 않고 Result.code 로 알린다."""
    from . import convert_pl
    res = Result()
    os.makedirs(input_dir, exist_ok=True)
    cfg, cfg_notes = read_config(input_dir)
    books = wehago.load_books(wehago_dir, asof, None)  # None: 장부가 오래됐다고 멈추지 않는다
    if books.state != "ok":
        res.code = 3
        res.lines = ["변환하지 않음 — WEHAGO 장부를 쓸 수 없음: " + books.reason]
        return res
    tables = [convert_pl.build_pl(books, cfg, read_prev(input_dir, "손익.csv"))]
    res.tables = tables
    for t in tables:
        if t.written:
            write_table(os.path.join(input_dir, t.name), t)
    kept = [m for m in MANUAL if os.path.exists(os.path.join(input_dir, m))]
    lines = result_lines(now, asof, books, cfg, cfg_notes, tables, "이전 파일: 없음", kept)
    with open(os.path.join(input_dir, "변환결과.txt"), "wb") as f:
        f.write(_text_bytes(lines))
    late = (asof - books.book_date).days
    res.lines = ["WEHAGO 장부 기준일 %s%s" % (books.book_date.isoformat(), " · 기준일보다 %d일 이전" % late if late > 0 else "")]
    for t in tables:
        res.lines.append("%s 만듦 %d줄" % (t.name, len(t.rows)) if t.written else "%s 만들지 않음 — %s" % (t.name, t.reason))
    res.lines.append("대조 불일치 %d건" % _mismatches(tables))
    res.lines.append("대조 내용: " + os.path.join(input_dir, "변환결과.txt"))
    return res
