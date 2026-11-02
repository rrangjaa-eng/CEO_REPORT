"""원천자료(WEHAGO 장부 엑셀 등) → 보고서 입력 CSV 변환 (Phase 2, D-37..D-45).

변환 한 번의 흐름: 설정 읽기 → 장부 읽기 → 표(Table) 만들기 → 입력 폴더에 쓰기 → 변환결과.txt.
사람이 직접 관리하는 파일(MANUAL)은 만들지도 덮지도 않는다 (D-43). 모든 글자는 util.mask_rrn 을 거쳐 나간다 (D-45).
"""
import collections
import csv
import io
import os
import shutil

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


def _read_prev_state(input_dir, name):
    """(이전 줄 목록, 상태): 상태는 '없음' | 'ok' | '읽지 못함'."""
    cols = data.SCHEMA.get(name)
    path = os.path.join(input_dir, name)
    if cols is None or not os.path.exists(path):
        return [], "없음"
    info = {}
    rows, ok = util.read_csv(path, cols, util.Issues(), info)
    if not ok or info.get("missing"):
        return [], "읽지 못함"
    for r in rows:
        r.pop("_line", None)
        r.pop("_file", None)
    return rows, "ok"


def read_prev(input_dir, name):
    """만들어 둔 CSV 의 이전 줄 (글자 그대로의 dict 목록, _line/_file 키 없음). 없거나 읽을 수 없으면 []."""
    return _read_prev_state(input_dir, name)[0]


# ───────────── 안전하게 쓰기 (D-43): 잠금 확인 → 임시 파일 → 이전 파일 복사 → 바꿔치기 ─────────────
class WriteFailed(Exception):
    """파일을 쓸 수 없음. name 은 입력 폴더 안 파일 이름, replaced 는 이미 바꾼 파일 이름들."""

    def __init__(self, name, error, replaced=()):
        Exception.__init__(self, "%s: %s" % (name, error))
        self.name, self.error, self.replaced = name, error, list(replaced)


def _check_writable(path):
    """이미 있는 파일을 쓰기로 열었다 닫는다 (엑셀이 열어 둔 파일은 여기서 OSError)."""
    with open(path, "r+b"):
        pass


def _write_temp(path, payload):
    with open(path, "wb") as f:
        f.write(payload)


def _backup_name(input_dir, stamp):
    base = os.path.join(input_dir, "이전")
    name, n = stamp, 1
    while os.path.exists(os.path.join(base, name)):
        n += 1
        name = "%s_%d" % (stamp, n)
    return name


def plan_backup(input_dir, names, stamp):
    """(이전 파일 폴더 이름 또는 None, 이미 있어서 옮길 파일 이름들)."""
    existing = [n for n in names if os.path.exists(os.path.join(input_dir, n))]
    return (_backup_name(input_dir, stamp) if existing else None), existing


def write_files(input_dir, payloads, stamp, backup=None):
    """[(이름, 바이트)]를 입력 폴더에 쓴다. 이름은 GENERATED 안에 있어야 한다 (아니면 ValueError, 아무것도 건드리지 않음).

    1) 이미 있는 대상을 모두 쓰기로 열어 본다 2) 새 내용을 '<이름>.변환중' 임시 파일로 쓴다 3) 이미 있던 파일을
    이전/<backup>/ 에 복사한다 4) 임시 파일을 os.replace 로 대상에 바꾼다. 3) 이전에 실패하면 아무것도 바뀌지 않는다
    (WriteFailed). backup 을 주면 그 이름의 폴더를 쓴다 (같은 실행의 두 번째 쓰기가 같은 폴더를 쓰도록).
    """
    for name, _ in payloads:
        if name not in GENERATED:
            raise ValueError("변환이 쓸 수 없는 파일 이름: %s" % name)
    targets = [(name, os.path.join(input_dir, name)) for name, _ in payloads]
    for name, path in targets:
        if os.path.exists(path):
            try:
                _check_writable(path)
            except OSError as e:
                raise WriteFailed(name, e)
    temps = []
    try:
        for (name, path), (_, payload) in zip(targets, payloads):
            tmp = path + ".변환중"
            temps.append(tmp)
            try:
                _write_temp(tmp, payload)
            except OSError as e:
                raise WriteFailed(name, e)
        folder = None
        existing = [(n, p) for n, p in targets if os.path.exists(p)]
        if existing:
            folder = os.path.join(input_dir, "이전", backup or _backup_name(input_dir, stamp))
            fresh = not os.path.exists(folder)
            try:
                os.makedirs(folder, exist_ok=True)
                for name, path in existing:
                    shutil.copy2(path, os.path.join(folder, name))
            except OSError as e:
                if fresh:
                    shutil.rmtree(folder, ignore_errors=True)
                raise WriteFailed(name, e)
        done = []
        for (name, path), tmp in zip(targets, temps):
            try:
                os.replace(tmp, path)
            except OSError as e:
                raise WriteFailed(name, e, done)
            done.append(name)
    finally:
        for tmp in temps:
            try:
                os.remove(tmp)
            except OSError:
                pass


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


def _write_failed_lines(e):
    out = ["입력/%s을(를) 쓸 수 없음 (엑셀에서 열려 있으면 닫고 다시 실행)" % e.name]
    if e.replaced:
        out.append("이미 바뀐 파일: " + ", ".join(e.replaced))
    return out


def run(input_dir, collect_dir, wehago_dir, asof, now, stamp=None):
    """변환 한 번. 장부·스냅숏·파일 문제로 예외를 내지 않고 Result.code 로 알린다."""
    from . import convert_pl
    res = Result()
    stamp = stamp or now.strftime("%Y%m%d_%H%M%S")
    try:
        os.makedirs(input_dir, exist_ok=True)
    except OSError:
        res.code = 7
        res.lines = ["입력 폴더를 만들 수 없음: %s" % input_dir]
        return res
    cfg, cfg_notes = read_config(input_dir)
    books = wehago.load_books(wehago_dir, asof, None)  # None: 장부가 오래됐다고 멈추지 않는다
    if books.state != "ok":
        res.code = 3
        tables = [Table("손익.csv", data.SCHEMA["손익.csv"], [], written=False, reason="WEHAGO 장부를 쓸 수 없음")]
    else:
        prev, prev_state = _read_prev_state(input_dir, "손익.csv")
        tables = [convert_pl.build_pl(books, cfg, prev)]
    res.tables = tables
    names = [t.name for t in tables if t.written] + ["변환결과.txt"]
    backup, moved = plan_backup(input_dir, names, stamp)
    where = "입력/이전/%s/" % backup if backup else ""
    if books.state == "ok" and prev_state == "읽지 못함":
        tables[0].notes.append("이전 손익.csv를 읽지 못해 WEHAGO 외 출처 줄을 옮기지 못함 (%s 에 원본 보관)" % where)
    kept = [m for m in MANUAL if os.path.exists(os.path.join(input_dir, m))]
    backup_line = "이전 파일: %s (%s)" % (where, ", ".join(moved)) if backup else "이전 파일: 없음"
    lines = result_lines(now, asof, books, cfg, cfg_notes, tables, backup_line, kept)
    payloads = [(t.name, table_bytes(t)) for t in tables if t.written] + [("변환결과.txt", _text_bytes(lines))]
    try:
        write_files(input_dir, payloads, stamp, backup)
    except WriteFailed as e:
        res.code = 7
        res.lines = _write_failed_lines(e)
        return res
    res.backup = os.path.join(input_dir, "이전", backup) if backup else None
    out = []
    if books.state != "ok":
        out.append("변환하지 않음 — WEHAGO 장부를 쓸 수 없음: " + books.reason)
    else:
        late = (asof - books.book_date).days
        out.append("WEHAGO 장부 기준일 %s%s" % (books.book_date.isoformat(),
                                             " · 기준일보다 %d일 이전" % late if late > 0 else ""))
    for t in tables:
        out.append("%s 만듦 %d줄" % (t.name, len(t.rows)) if t.written else "%s 만들지 않음 — %s" % (t.name, t.reason))
    if backup:
        out.append(backup_line)
    out.append("대조 불일치 %d건" % _mismatches(tables))
    out.append("대조 내용: " + os.path.join(input_dir, "변환결과.txt"))
    res.lines = out
    return res
