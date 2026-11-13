"""원천자료(WEHAGO 장부 엑셀 등) → 보고서 입력 CSV 변환 (Phase 2, D-37..D-45).

변환 한 번의 흐름: 설정 읽기 → 장부 읽기 → 최신 인트라넷 스냅숏 읽기 → 프로젝트 연결(linking) → 표(Table) 만들기
→ 입력 폴더에 쓰기 → 변환결과.txt. 스냅숏이 없거나 읽을 수 없으면 [코드]·수동 지정으로만 잇고 손익.csv 는 그대로 만든다
(장부만 변환을 막는다). 연결 입력은 Result.links 에 남겨 다른 표 만들기가 다시 계산하지 않고 쓴다.
사람이 직접 관리하는 파일(MANUAL)은 만들지도 덮지도 않는다 (D-43). 모든 글자는 util.mask_rrn 을 거쳐 나간다 (D-45).
"""
import collections
import csv
import datetime as dt
import io
import os
import re
import shutil

from . import old_intranet, data, linking, snapshot, util, wehago
from .util import won

# 변환이 만드는 파일. 이 이름들만 입력 폴더에 쓸 수 있다.
GENERATED = ("손익.csv", "계산서.csv", "프로젝트.csv", "프로젝트집행.csv", "위하고대조.csv", "자금계획.csv", "부서비용.csv", "사원급여.csv", "부서계정비용.csv", "세금예상.csv", "계정별비용.csv", "증빙월별.csv", "장부잔액.csv", "장부입출금.csv", "장부채무.csv", "연간자료.csv", "현금흐름.csv", "계정잔액.csv", "변환결과.txt", "확인할것.json", "자동분석.json")
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
    ("loan_codes", ("26000", "29300")),   # 단기차입금·장기차입금 (장부채무.csv, 2026-11-04 점검 A2)
    ("deposit_codes", ("10500",)),        # 정기예금 (장부채무.csv: 만기일까지 쓸 수 없는 돈, 사용자 2026-11-04)
    ("vat_codes", ("13500",)),
    ("closing_sorts", ("결차", "결대", "결산전표", "잉여금관련전표")),   # 인쇄 분개장 유형: 결산전표(원가 대체·감가상각) · 잉여금관련전표(손익 대체), 2025 분개장 12/31
    ("link_days", 90),
    ("card_words", ("카드",)),
    ("snapshot_days", 7),
    ("salary_codes", ("80200",)),   # 급여 계정 (부서비용.csv 의 급여 칸, 사용자 2026-11-03)
    ("nonop_in_codes", ("90100", "92200", "93000")),   # 영업외 수익: 이자수익·정부지원금수익·잡이익 (부서비용.csv)
    ("nonop_out_codes", ("93100", "96000")),           # 영업외 비용: 이자비용·잡손실
    ("vat_payable_codes", ("25500",)),                 # 부가세예수금 (세금예상.csv, 사용자 2026-11-03)
    ("withholding_codes", ("25400",)),                 # 예수금
    ("withholding_vendors", ("세무서", "구청", "시청", "군청")),   # 원천세(소득세·지방소득세) 거래처 낱말
    ("insurance_vendors", ("국민연금", "건강보험", "근로복지", "고용보험")),   # 4대보험 거래처 낱말 (사용자 2026-11-03)
    ("salary_pay_day", 5),                             # 급여일: 다음 달 이 날, 쉬는 날이면 그 전 영업일
    ("withholding_mode", "자동"),                      # 원천세 납부: 자동 | 반기 | 매월   # 스냅숏이 기준일보다 이만큼 넘게 오래되면 경고 (02-REVIEW WR-06)
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
        self.links = None   # 연결 입력과 결과 (build_links). 다른 표 만들기가 다시 계산하지 않고 쓴다.


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


# 설정.csv 항목 이름 → (cfg 키, 값 종류). 종류: 숫자목록(쉼표로 나눈 숫자) | 낱말 | 낱말목록 | 정수(0 이상)
# | 일수(0 이상 정수, DAY_RANGE 밖이면 가까운 끝으로 바꾸고 알림 — 02-REVIEW WR-02: 큰 값이 날짜 계산을 넘치게 했다)
CONFIG_ITEMS = (
    ("변환_매출계정", "revenue_codes", "숫자목록"),
    ("변환_매출채권계정", "receivable_codes", "숫자목록"),
    ("변환_직접비코드", "direct_prefixes", "숫자목록"),
    ("변환_직접비표시", "direct_mark", "낱말"),
    ("변환_공통비코드", "common_prefixes", "숫자목록"),
    ("변환_공통비표시", "common_mark", "낱말"),
    ("변환_미지급계정", "payable_codes", "숫자목록"),
    ("변환_현금계정", "cash_codes", "숫자목록"),
    ("변환_차입금계정", "loan_codes", "숫자목록"),
    ("변환_정기예금계정", "deposit_codes", "숫자목록"),
    ("변환_부가세대급금계정", "vat_codes", "숫자목록"),
    ("변환_결산구분", "closing_sorts", "낱말목록"),
    ("변환_자동연결일수", "link_days", "일수"),
    ("변환_카드거래처", "card_words", "낱말목록"),
    ("변환_스냅숏경과일", "snapshot_days", "일수"),
    ("변환_급여계정", "salary_codes", "숫자목록"),
    ("변환_영업외수익계정", "nonop_in_codes", "숫자목록"),
    ("변환_영업외비용계정", "nonop_out_codes", "숫자목록"),
    ("변환_부가세예수금계정", "vat_payable_codes", "숫자목록"),
    ("변환_예수금계정", "withholding_codes", "숫자목록"),
    ("변환_원천세거래처", "withholding_vendors", "낱말목록"),
    ("변환_원천세납부", "withholding_mode", "낱말"),
    ("변환_4대보험거래처", "insurance_vendors", "낱말목록"),
    ("변환_급여일", "salary_pay_day", "정수"),
)


DAY_RANGE = (1, 3650)


def _split(raw):
    return tuple(x.strip() for x in str(raw).split(",") if x.strip())


def _parse_config_value(kind, raw):
    """설정 글자 → 값. 쓸 수 없으면 None."""
    text = str(raw).strip()
    if kind == "낱말":
        return text or None
    if kind in ("정수", "일수"):
        return int(text) if re.match(r"^[0-9]+$", text) else None
    items = _split(text)
    if not items:
        return None
    if kind == "숫자목록" and not all(re.match(r"^[0-9]+$", x) for x in items):
        return None
    return items


def _config_text(value):
    return ",".join(value) if isinstance(value, tuple) else str(value)


def read_config(input_dir):
    """설정.csv 의 '변환_*' 항목 → (cfg, notes). 설정.csv 는 읽기만 한다 (D-39).

    없거나 비었거나 쓸 수 없는 값은 기본값을 쓰고 notes 에 이유를 남긴다. 행이 없는 항목은 조용히 기본값이다.
    """
    cfg = Config(DEFAULT_CONFIG)
    notes = []
    path = os.path.join(input_dir, "설정.csv")
    if not os.path.exists(path):
        return cfg, ["설정.csv 없음 → 변환 설정 기본값 사용"]
    info = {}
    rows, ok = util.read_csv(path, ["항목", "값"], util.Issues(), info)
    if not ok or info.get("missing"):
        return cfg, ["설정.csv를 읽지 못함 → 변환 설정 기본값 사용"]
    found = collections.OrderedDict()
    for r in rows:
        item = r.get("항목", "")
        if item.startswith("변환_"):
            found[item] = r.get("값", "")  # 같은 항목이 또 나오면 뒤의 줄이 이긴다 (data.load 와 같음)
    known = dict((item, (key, kind)) for item, key, kind in CONFIG_ITEMS)
    for item, raw in found.items():
        if item not in known:
            notes.append("설정 %s 알 수 없는 변환 항목 → 무시" % item)
            continue
        key, kind = known[item]
        default = _config_text(DEFAULT_CONFIG[key])
        if util.is_blank(raw):
            notes.append("설정 %s 비어 있음 → 기본값 %s" % (item, default))
            continue
        value = _parse_config_value(kind, raw)
        if value is None:
            notes.append("설정 %s 값 '%s' 사용할 수 없음 → 기본값 %s" % (item, raw, default))
            continue
        if kind == "일수" and not DAY_RANGE[0] <= value <= DAY_RANGE[1]:
            fixed = min(max(value, DAY_RANGE[0]), DAY_RANGE[1])
            notes.append("설정 %s 값 %d 범위 밖 (%d~%d) → %d 사용" % (item, value, DAY_RANGE[0], DAY_RANGE[1], fixed))
            value = fixed
        cfg[key] = value
    cfg.from_file = bool(found)
    return cfg, notes


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
    """파일을 쓸 수 없음. name 은 입력 폴더 안 파일 이름, replaced 는 실패 전에 이미 바꾼 파일 이름들.

    바꿔치기 중에 실패하면 (02-REVIEW WR-01) replaced 를 이전/<backup>/ 의 복사본으로 되돌린다: restored 는 되돌린 파일,
    lost 는 되돌리지 못해 새 내용이 남은 파일, backup 은 이전 파일 폴더 이름, stage 는 실패한 단계('replace' 면 바꾸는 중).
    """

    def __init__(self, name, error, replaced=(), restored=(), lost=(), backup=None, stage=""):
        Exception.__init__(self, "%s: %s" % (name, error))
        self.name, self.error, self.replaced = name, error, list(replaced)
        self.restored, self.lost, self.backup, self.stage = list(restored), list(lost), backup, stage


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


def roll_back(input_dir, names, existed, backup):
    """이미 바꾼 파일을 되돌린다 (WR-01): 전에 있던 파일은 이전/<backup>/ 복사본으로, 없던 파일은 지운다 -> (되돌림, 못 함)."""
    restored, lost = [], []
    for name in names:
        path = os.path.join(input_dir, name)
        try:
            if name in existed:
                if not backup:
                    raise OSError("이전 파일 폴더 없음")
                shutil.copy2(os.path.join(input_dir, "이전", backup, name), path)
            elif os.path.exists(path):
                os.remove(path)
            restored.append(name)
        except OSError:
            lost.append(name)
    return restored, lost


def write_files(input_dir, payloads, stamp, backup=None):
    """[(이름, 바이트)]를 입력 폴더에 쓴다. 이름은 GENERATED 안에 있어야 한다 (아니면 ValueError, 아무것도 건드리지 않음).

    1) 이미 있는 대상을 모두 쓰기로 열어 본다 2) 새 내용을 '<이름>.변환중' 임시 파일로 쓴다 3) 이미 있던 파일을
    이전/<backup>/ 에 복사한다 4) 임시 파일을 os.replace 로 대상에 바꾼다. 3) 이전에 실패하면 아무것도 바뀌지 않는다
    (WriteFailed). backup 을 주면 그 이름의 폴더를 쓴다 (같은 실행의 두 번째 쓰기가 같은 폴더를 쓰도록).
    4) 중간에 실패하면 이미 바꾼 파일을 3) 의 복사본으로 되돌린 뒤 WriteFailed (stage 'replace', 02-REVIEW WR-01).
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
        folder, used = None, None
        existing = [(n, p) for n, p in targets if os.path.exists(p)]
        if existing:
            used = backup or _backup_name(input_dir, stamp)
            folder = os.path.join(input_dir, "이전", used)
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
                restored, lost = roll_back(input_dir, done, set(n for n, _ in existing), used)
                raise WriteFailed(name, e, done, restored, lost, used, "replace")
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


_COUNT_LABEL = re.compile(r"^(프로젝트 수|지급요청 건수|지급요청 금액 미확인|지급요청마다)|건수|(빈칸|줄 수|원가 줄)$")


def check_text(c):
    """변환결과.txt 의 대조 한 줄 본문. 건수를 세는 대조는 숫자 뒤에 '건'을 붙인다 (금액은 그대로, 모르면 '미확인')."""
    unit = "건" if _COUNT_LABEL.search(c.label) else ""
    side = lambda v: won(v) + (unit if v is not None else "")
    return "%s: 원본 %s · CSV %s → %s" % (c.label, side(c.source), side(c.csv), check_result(c))


def _all_checks(tables, cross=()):
    return [c for t in tables if t.written for c in t.checks] + list(cross)


def _mismatches(tables, cross=()):
    return sum(1 for c in _all_checks(tables, cross) if check_result(c) == "불일치")


def _undecided(tables, cross=()):
    return sum(1 for c in _all_checks(tables, cross) if check_result(c) == "판단 불가")


def read_latest_snapshot(collect_dir):
    """(스냅숏 또는 None, 변환결과.txt 한 줄). 스냅숏이 없거나 읽을 수 없어도 멈추지 않는다 (장부만 변환을 막는다)."""
    try:
        path = snapshot.latest_snapshot(collect_dir)
        if path is None:
            return None, "인트라넷 스냅숏: 없음 — 자동 연결 안 함"
        snap = snapshot.read_snapshot(path)
    except (snapshot.SnapshotError, OSError) as e:
        return None, "인트라넷 스냅숏: 읽지 못함 — %s" % e
    snap.old = old_intranet.load(collect_dir)   # 예전 인트라넷 (2025~2026.3, 사용자 2026-11-05)
    line = "인트라넷 스냅숏: %s (수집 %s) · 지급요청 %d건 · 프로젝트 %d건" % (
        os.path.basename(snap.path), snap.collected_at.strftime(snapshot.TIME_FORMAT), len(snap.payments), len(snap.projects))
    if snap.old.files:
        line += " · 예전 인트라넷 지급요청 %d건 · 프로젝트 %d건 (연결 참고용)" % (len(snap.old.payments), len(snap.old.projects))
    return snap, line


def snapshot_lines(snap, snap_line, asof, cfg):
    """(화면 한 줄, 경고 또는 None) (02-REVIEW WR-06): 어떤 스냅숏을 썼는지와 기준일 대비 나이.

    기준일보다 설정 변환_스냅숏경과일(기본 7일)을 넘게 오래됐거나, 기준일 뒤에 수집된 스냅숏이면 경고한다.
    """
    if snap is None:
        return snap_line, None
    taken = snap.collected_at
    stamp = taken.strftime(snapshot.TIME_FORMAT)
    days = (asof - taken.date()).days
    age = "기준일보다 %d일 이전" % days if days > 0 else ("기준일과 같은 날" if days == 0 else "기준일보다 %d일 뒤" % -days)
    line = "인트라넷 스냅숏 %s (수집 %s, %s)" % (os.path.basename(snap.path), stamp, age)
    limit = cfg["snapshot_days"]
    if days < 0:
        return line, ("경고: 인트라넷 스냅숏이 기준일(%s)보다 %d일 뒤에 수집됨 (수집 %s) — 기준일 시점의 지급요청·프로젝트가 아닐 수 있음"
                      % (asof.isoformat(), -days, stamp))
    if days > limit:
        return line, ("경고: 인트라넷 스냅숏이 기준일보다 %d일 이전 (수집 %s) — 설정 변환_스냅숏경과일 %d일을 넘음: "
                      "지급요청·프로젝트가 오래됐을 수 있음 (승인검토.py로 새로 수집한 뒤 다시 변환)" % (days, stamp, limit))
    return line, None


def build_links(books, cfg, snap, input_dir, asof, now):
    """D-38 연결 한 번: 요청·프로젝트·수동 지정을 읽고 원가·매출 줄을 잇는다. build_pl 이 받는 links 딕셔너리 (+ 다른 만들기가 쓸 입력)."""
    requests = linking.requests_of(snap, asof, now)
    projects = linking.projects_of(snap)
    overrides, notes = linking.read_links(input_dir)
    old = getattr(snap, "old", None)
    if old is not None:
        notes = list(notes) + old.notes
    # 예전 인트라넷 지급요청은 원가 줄 연결에만 (requests 에는 넣지 않음: 요청미지급·요청 누계는 지금 인트라넷만)
    costs = linking.link_costs(books, requests + linking.old_requests(old, asof, now), projects, overrides, cfg["link_days"],
                               cfg["direct_prefixes"], cfg["direct_mark"], cfg["vat_codes"])
    revenue = linking.link_revenue(books, projects, overrides, cfg["revenue_codes"])
    unused = linking.unused_links(books, overrides, costs["used"] | revenue["used"])
    return {"costs": costs, "revenue": revenue, "projects": projects, "snapshot": snap is not None,
            "requests": requests, "overrides": overrides, "notes": notes, "unused": unused}


LINK_HINT = "프로젝트연결.csv에 전표일자·전표번호·줄·프로젝트번호를 적으면 다음 변환부터 그 프로젝트로 연결됩니다"


def _basis_text(summary):
    """'수동 0건 0 · 코드 9건 258,400,000 · 자동 0건 0 · 미연결 2건 1,100,000' (금액 모르는 줄은 건수를 덧붙인다)."""
    parts = []
    for basis, s in summary.items():
        text = "%s %d건 %s" % (basis, s["count"], won(s["sum"]))
        if s["unknown"]:
            text += " (금액 미확인 %d건)" % s["unknown"]
        parts.append(text)
    return " · ".join(parts)


def _unlinked_total(summary):
    s = summary["미연결"]
    return "%d건 %s%s" % (s["count"], won(s["sum"]), " (금액 미확인 %d건)" % s["unknown"] if s["unknown"] else "")


def _list_order(ln):
    no = ln["no"]
    return (ln["date"].isoformat() if ln["date"] else "9999-99-99", (0, int(no), no) if no.isdigit() else (1, 0, no), ln["line"])


def link_lines(links):
    """변환결과.txt 의 연결 구역: 기준별 요약, 미연결 줄 목록 (원가 다음 매출, 날짜·전표번호·줄 순), 수동 지정 알림."""
    out = ["[연결] 프로젝트 연결",
           "  원가 줄: " + _basis_text(links["costs"]["summary"]),
           "  매출 줄: " + _basis_text(links["revenue"]["summary"])]
    listed = 0
    for kind, result in (("원가", links["costs"]), ("매출", links["revenue"])):
        for ln in sorted((x for x in result["lines"] if x["basis"] == "미연결" and not x.get("prior")), key=_list_order):
            parts = ["미연결", kind, ln["date"].isoformat() if ln["date"] else "날짜 없음", "%s-%d" % (ln["no"], ln["line"]),
                     ln["vendor"], won(ln["amount"]), ln["memo"]]
            out.append("  " + " ".join(p for p in parts if p != "") + " — " + ln["label"])
            listed += 1
    if listed:
        out.append("  " + LINK_HINT)
    for note in links["notes"]:
        if not note.startswith("%s 없음" % linking.LINK_FILE):
            out.append("  알림 " + note)
    for key, project, why in links["unused"]:
        out.append("  알림 %s %s %s-%d → %s: %s" % (linking.LINK_FILE, key[0], key[1], key[2], project, why))
    return out


def link_stdout_line(links):
    return "프로젝트 연결: 원가 미연결 %s · 매출 미연결 %s (변환결과.txt 목록)" % (
        _unlinked_total(links["costs"]["summary"]), _unlinked_total(links["revenue"]["summary"]))


# ───────────── 파일 사이 대조 (W-4): 한 번의 변환이 만든 파일끼리 합계가 같은지 ─────────────
def _sum_known(values):
    """합계. 하나라도 모르면(None) None."""
    total = 0
    for v in values:
        if v is None:
            return None
        total += v
    return total


def _first_csv(table, prefix):
    """표의 대조 중 이름이 prefix 로 시작하는 첫 번째의 CSV 쪽 합계 (없으면 None)."""
    for c in table.checks:
        if c.label.startswith(prefix):
            return c.csv
    return None


def _kind_rows(table, kind, item=None):
    return [r for r in table.rows if r["구분"] == kind and (item is None or r["항목"] == item)]


def cross_checks(tables):
    """[파일 사이 대조]: 쓴 파일끼리의 합계. 두 파일이 모두 만들어졌을 때만 한다. 원본 쪽 = 손익.csv, CSV 쪽 = 다른 파일."""
    from . import convert_pl
    by = dict((t.name, t) for t in tables if t.written)
    pl, execs, xchk, projects = (by.get(n) for n in ("손익.csv", "프로젝트집행.csv", "위하고대조.csv", "프로젝트.csv"))
    out = []
    if pl is None or len(pl.checks) < 3:
        return out
    pl_revenue, pl_direct = pl.checks[0].csv, pl.checks[1].csv
    unlinked = [r for r in pl.rows if r.get("출처") == "WEHAGO" and r.get("단위") == "프로젝트"
                and r.get("대상") == convert_pl.UNLINKED_PROJECT]
    pl_unlinked = _sum_known(util.num(r.get("직접비")) for r in unlinked)
    if execs is not None and projects is not None:
        out.append(Check("손익 직접비 = 프로젝트집행 원가 줄 합계", pl_direct, _first_csv(execs, "원가 줄 합계")))
        keys = set((r.get("프로젝트번호") or "").strip() for r in projects.rows)
        portions = execs.extra.get("cost_portions", [])
        # WEHAGO 원가 줄 = 근거가 'WEHAGO ' 로 시작하는 줄 (요청 줄은 '지급요청', 옮겨 온 줄은 상태가 집행계획미요청)
        mine = [p for r, p in zip(execs.rows, portions) if r.get("상태") != "집행계획미요청"
                and (r.get("근거") or "").startswith("WEHAGO ") and (r.get("프로젝트번호") or "").strip() not in keys]
        out.append(Check("손익 프로젝트 미연결 직접비 = 프로젝트집행 프로젝트.csv에 없는 번호의 원가 부분", pl_unlinked, _sum_known(mine)))
    if xchk is not None:
        cost_cells = _kind_rows(xchk, "프로젝트원가", "WEHAGO 원가")
        unlinked_cost = _kind_rows(xchk, "미연결원가")[:1]
        sales_cells = _kind_rows(xchk, "매출계약", "WEHAGO 매출")
        unlinked_sales = _kind_rows(xchk, "매출미연결")[:1]
        cell = lambda rows: _sum_known(util.num(r["금액"]) for r in rows) if rows else None
        out.append(Check("손익 직접비 = 위하고대조 (도) 원가", pl_direct, cell(cost_cells + unlinked_cost) if unlinked_cost else None))
        out.append(Check("손익 매출 = 위하고대조 매출", pl_revenue, cell(sales_cells + unlinked_sales) if unlinked_sales else None))
        out.append(Check("손익 프로젝트 미연결 직접비 = 위하고대조 미연결원가", pl_unlinked, cell(unlinked_cost)))
    return out


def read_bank(input_dir):
    """위하고대조의 보통예금 사실에 쓰는 은행 줄: {"balances": 계좌잔액.csv 줄, "transactions": 입출금내역.csv 줄}. 읽기만 한다 (D-48).
    파일이 없거나 읽을 수 없으면 None (0줄과 다르다)."""
    out = {}
    for key, name in (("balances", "계좌잔액.csv"), ("transactions", "입출금내역.csv")):
        path = os.path.join(input_dir, name)
        info = {}
        rows, ok = util.read_csv(path, data.SCHEMA[name], util.Issues(), info) if os.path.exists(path) else ([], False)
        out[key] = rows if ok and not info.get("missing") else None
    return out


def xchk_meta(books, snap, now):
    """위하고대조.csv 맨 위 '기준' 줄들: 어느 장부·스냅숏으로 만들었는지."""
    meta = collections.OrderedDict()
    meta["장부 기준일"] = books.book_date.isoformat() if books.book_date else ""
    for kind in wehago.KINDS:
        if kind in books.files:
            meta[kind] = books.files[kind]["name"]
    if snap is None:
        meta["인트라넷 스냅숏"] = "없음"
    else:
        meta["인트라넷 스냅숏"] = "%s (수집 %s)" % (os.path.basename(snap.path).replace("인트라넷_", "", 1),
                                              snap.collected_at.strftime(snapshot.TIME_FORMAT))
    meta["변환 시각"] = now.strftime("%Y-%m-%d %H:%M:%S")
    return meta


def status_warning(links):
    """스냅숏의 지급요청이 모두 사장님승인 빈칸이면 한 줄 경고 (D-52: 수집이 그 칸을 놓친 것일 수 있다). 아니면 None."""
    requests = (links or {}).get("requests") or []
    if not requests or any(rq.get("status_text") for rq in requests):
        return None
    return ("경고: 인트라넷 지급요청 %d건 모두 사장님승인 빈칸 — 스냅숏 수집 확인 필요 "
            "(모두 '상태 확인 필요'로 요청미지급(추정)·요청 누계에 넣음)" % len(requests))


def result_lines(now, asof, books, cfg, cfg_notes, tables, backup_line, kept,
                 snap_line="인트라넷 스냅숏: 없음 — 자동 연결 안 함", links=None, cross=(), listings=(), snap_warning=None):
    """변환결과.txt 한 줄씩 (PATTERNS §6)."""
    out = ["변환 시각 %s · 기준일 %s" % (now.strftime("%Y-%m-%d %H:%M:%S"), asof.isoformat()),
           _books_line(books, asof)]
    out.extend(n if n.startswith("  ") else "  알림 " + n for n in getattr(books, "notes", []))
    out.append(snap_line)
    if snap_warning:
        out.append(snap_warning)
    warning = status_warning(links)
    if warning:
        out.append(warning)
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
            out.append("  대조 " + check_text(c))
        for n in t.notes:
            # 목록 줄('  미배분 수금 …')은 이미 들여쓰기가 있다: 접두어 없이 그대로 쓴다
            out.append(n if n.startswith("  ") else "  알림 " + n)
    if links is not None:
        out.extend(link_lines(links))
    if cross:
        out.append("[파일 사이 대조]")
        out.extend("  대조 " + check_text(c) for c in cross)
    out.extend(listings)
    out.append(backup_line)
    out.append("손대지 않은 파일: " + (", ".join(kept) if kept else "없음"))
    missing = [m for m in MANUAL if m not in kept]
    if missing:
        out.append("없는 수동 파일 (사람이 관리, 만들지 않음): " + ", ".join(missing))
    if _undecided(tables, cross):
        out.append("대조 판단 불가 %d건" % _undecided(tables, cross))
    out.append("대조 불일치 %d건" % _mismatches(tables, cross))
    return out


def _write_failed_lines(e):
    out = ["입력/%s을(를) 쓸 수 없음 (엑셀에서 열려 있으면 닫고 다시 실행)" % e.name]
    where = "입력/이전/%s/" % e.backup if e.backup else "입력/이전/"
    if e.restored:
        out.append("이미 바꾼 파일을 이전 내용으로 되돌림: %s (%s 에서)" % (", ".join(e.restored), where))
    if e.lost:
        out.append("되돌리지 못한 파일 (새 내용 그대로): %s — %s 의 같은 이름 파일로 직접 바꾸세요" % (", ".join(e.lost), where))
    unsaid = [n for n in e.replaced if n not in e.restored and n not in e.lost]
    if unsaid:
        out.append("이미 바뀐 파일: " + ", ".join(unsaid))
    return out


FAILED_HEAD = "변환 실패 — 파일을 바꾸는 중 멈춤 (종료 코드 7): 입력의 CSV는 이전 변환 그대로입니다"


def _failure_result(input_dir, now, asof, e, stamp, backup):
    """바꾸는 중 실패 (WR-01): 변환결과.txt 를 실패 내용으로 다시 쓴다 -> 화면 줄. 쓸 수 없으면 그것도 알린다."""
    head = FAILED_HEAD if not e.lost else "변환 실패 — 파일을 바꾸는 중 멈춤 (종료 코드 7): 되돌리지 못한 파일이 있습니다"
    body = [head] + _write_failed_lines(e)
    text = ["변환 시각 %s · 기준일 %s" % (now.strftime("%Y-%m-%d %H:%M:%S"), asof.isoformat())] + body
    text.append("엑셀 등에서 연 파일을 닫고 다시 변환하세요. 이 변환의 대조 결과는 없습니다.")
    try:
        write_files(input_dir, [("변환결과.txt", _text_bytes(text))], stamp, e.backup or backup)
    except WriteFailed:
        body.append("변환결과.txt도 쓰지 못함 (이전 변환의 결과가 남아 있음)")
    return body


def _kept_invoice_reason(input_dir, sales):
    """계산서.csv 를 만들지 못한 이유 한 줄 (D-46). 기존 계산서.csv 는 건드리지 않고 작성일을 함께 알린다."""
    reason = sales.get("reason") or "자료 없음 (매출 계산서 엑셀)"
    path = os.path.join(input_dir, "계산서.csv")
    if not os.path.exists(path):
        return reason
    none = "자료 없음 (매출 계산서 엑셀)"
    if sales.get("state") == "자료 없음" and reason.startswith(none):
        reason = "매출 계산서 엑셀 없음" + reason[len(none):]
    try:
        day = dt.date.fromtimestamp(os.path.getmtime(path)).isoformat()
    except (OSError, ValueError, OverflowError):
        day = "알 수 없음"
    return "%s → 기존 계산서.csv 유지 (갱신 안 됨, 작성일 %s)" % (reason, day)


SCHEDULE_NOTE = "(자금일정.csv는 바꾸지 않음)"
_UNPAID = ("요청미지급", "카드사용미결제")


def _digits(text):
    return re.sub(r"\D", "", text or "")


def schedule_overlaps(input_dir, tables):
    """(쌍 목록 또는 None, 사유): 자금일정.csv 출금 줄과 아직 나가지 않은 프로젝트집행 줄이 겹칠 수 있는 쌍. 읽기만 한다 (D-37, D-44).

    겹침 = 금액이 같고(집행 줄의 공급가액, 또는 공급가액+부가세) 프로젝트번호의 숫자가 같거나 거래처 이름이 같음.
    프로젝트집행.csv 를 이번에 만들지 못했으면 입력 폴더의 기존 파일을 읽는다. 읽을 수 없으면 None (0건과 다르다).
    """
    path = os.path.join(input_dir, "자금일정.csv")
    if not os.path.exists(path):
        return None, "자금일정.csv 없음"
    info = {}
    sched, ok = util.read_csv(path, data.SCHEMA["자금일정.csv"], util.Issues(), info)
    if not ok or info.get("missing"):
        return None, "자금일정.csv를 읽지 못함"
    made = [t for t in tables if t.name == "프로젝트집행.csv" and t.written]
    if made:
        execs = made[0].rows
    else:
        execs, state = _read_prev_state(input_dir, "프로젝트집행.csv")
        if state == "읽지 못함":
            return None, "프로젝트집행.csv를 읽지 못함"
    unpaid = [e for e in execs if (e.get("상태") or "").strip() in _UNPAID and data.PRIOR_TAG not in (e.get("근거") or "")]
    pairs = []
    for sr in sched:
        if (sr.get("입출금") or "").strip() not in ("출금", "지급"):
            continue
        amount = util.num(sr.get("금액"))
        if amount is None:
            continue
        for e in unpaid:
            supply, vat = util.num(e.get("공급가액")), util.num(e.get("부가세"))
            if supply is None or amount not in ((supply,) if vat is None else (supply, supply + vat)):
                continue
            same_project = _digits(sr.get("프로젝트번호")) and _digits(sr.get("프로젝트번호")) == _digits(e.get("프로젝트번호"))
            same_vendor = wehago.norm_vendor(sr.get("거래처")) and wehago.norm_vendor(sr.get("거래처")) == wehago.norm_vendor(e.get("거래처"))
            if same_project or same_vendor:
                pairs.append((sr, e, amount))
    return pairs, ""


def overlap_lines(input_dir, tables):
    pairs, why = schedule_overlaps(input_dir, tables)
    if pairs is None:
        return ["자금일정.csv와 겹칠 수 있는 줄 판단 불가 (%s) %s" % (why, SCHEDULE_NOTE)]
    out = ["자금일정.csv와 겹칠 수 있는 줄 %d건 %s" % (len(pairs), SCHEDULE_NOTE)]
    for sr, e, amount in pairs:
        parts = [(sr.get("예정일") or "").strip() or "날짜 없음", (sr.get("입출금") or "").strip(), won(amount),
                 (sr.get("프로젝트번호") or "").strip(), (sr.get("거래처") or "").strip()]
        vat = util.num(e.get("부가세"))
        mine = [(e.get("상태") or "").strip(), (e.get("프로젝트번호") or "").strip(), (e.get("거래처") or "").strip(),
                "공급가액 " + won(util.num(e.get("공급가액"))) + (" + 부가세 " + won(vat) if vat is not None else "")]
        out.append("  겹침 자금일정 " + " ".join(x for x in parts if x) + " ↔ 프로젝트집행 " + " ".join(x for x in mine if x))
    return out


def input_check_lines(input_dir):
    """data.load(입력 폴더)가 보고서 7번에 올릴 입력 확인 항목 (읽기만 한다, W-6). 변환이 끝난 폴더를 읽는다."""
    items = data.load(input_dir).issues.items
    out = ["보고서 입력 확인 필요 %d건" % len(items)]
    for name, line, msg in items:
        where = "%s번째 줄" % line if str(line).isdigit() else "전체"
        out.append("  확인 %s %s: %s" % (name, where, msg))
    return out


def precheck_writable(input_dir, names):
    """쓰기 전에 이미 있는 대상을 모두 쓰기로 열어 본다. 하나라도 안 되면 WriteFailed (아무것도 바뀌지 않음)."""
    for name in names:
        path = os.path.join(input_dir, name)
        if os.path.exists(path):
            try:
                _check_writable(path)
            except OSError as e:
                raise WriteFailed(name, e)


def _unwritten(reason):
    from . import convert_xchk
    columns = dict((n, data.SCHEMA[n]) for n in GENERATED[:5] if n in data.SCHEMA)
    columns["위하고대조.csv"] = convert_xchk.XCHK_COLUMNS
    return [Table(n, columns[n], [], written=False, reason=reason) for n in GENERATED[:5]]


def closing_pl_line(ln, closing_sorts):
    """결산 전표 손익 줄 처리 (drop_closing_pl 설명). -> 그대로 쓸 줄, 감가상각비면 대변을 비운 줄, 뺄 줄이면 None."""
    sq = wehago._squash
    if sq(ln.get("sort")) not in set(sq(s) for s in closing_sorts) or not re.match(r"^[4-9]", sq(ln.get("account_code"))):
        return ln
    if "감가상각비" in sq(ln.get("account")) and ln.get("debit"):
        return dict(ln, credit=None)
    return None


def drop_closing_pl(books, cfg):
    """결산 전표의 손익 줄(계정코드 4~9로 시작)을 뺀다 (2026-11-04 실제 2025 분개장).

    결산전표는 원가(도)를 진행중행사·행사매출원가로 옮기고, 잉여금관련전표는 손익 계정을 0으로 돌린다. 둘 다 넣으면 12월 원가·판관비가
    마이너스로 바뀌고 감가상각비도 0이 된다. 감가상각비는 결산 때만 들어가므로 결산 줄의 차변만 남긴다 (대변 = 손익 대체).
    대차대조표 줄(1~3)은 그대로 둔다 (세금·자금 계산이 쓰는 계정은 결산 줄에 없고, 결산한 해 판단에 쓴다). -> 뺀 줄 수."""
    keep, dropped = [], 0
    for ln in books.journal:
        v = closing_pl_line(ln, cfg["closing_sorts"])
        if v is None:
            dropped += 1
        else:
            keep.append(v)
    books.journal = keep
    if dropped:
        books.notes.append("결산 전표 손익 줄 %d건 뺌 (원가 대체·손익 대체, 감가상각비 차변은 남김)" % dropped)
    return dropped


def _build_tables(books, cfg, snap, input_dir, wehago_dir, asof, now, res):
    """모든 표를 한 번에 만든다: 같은 장부·스냅숏·연결·요청 대조에서. -> (표 목록, 이전 줄 읽기 상태)."""
    from . import convert_invoices, convert_pl, convert_projects, convert_xchk
    prev, states = {}, {}
    for name in GENERATED[:4]:
        prev[name], states[name] = _read_prev_state(input_dir, name)
    res.links = links = build_links(books, cfg, snap, input_dir, asof, now)
    sales = wehago.load_sales(wehago_dir, asof, books)
    invoices = convert_invoices.build_invoices(sales, books, links["revenue"], links["projects"], prev["계산서.csv"], cfg)
    if not invoices.written:
        invoices.reason = _kept_invoice_reason(input_dir, sales)   # 쓸 매출 원천이 없으면 기존 계산서.csv 를 그대로 둔다 (D-46)
    tables = [convert_pl.build_pl(books, cfg, prev["손익.csv"], links), invoices]
    if snap is None:
        tables.extend(_unwritten("인트라넷 스냅숏 없음 (기존 파일 그대로)")[2:])
    else:
        match = wehago.match_requests(books, links["requests"])
        history = convert_projects.out_of_period(books, links["projects"], links["requests"])   # WR-05
        project_table = convert_projects.build_projects(links["projects"], links["revenue"], prev["프로젝트.csv"], history,
                                                        convert_projects.period_text(books))
        if getattr(snap, "projects", None):   # 승인 칸 글자가 실제 화면과 맞는지 볼 수 있게 (대표이사 승인 = 종결, 사용자 2026-11-11)
            project_table.notes.append("인트라넷 승인 칸 글자 — %s (끝남으로 읽는 글자: %s)"
                                       % (linking.approval_words(snap.projects), "·".join(linking.APPROVAL_DONE)))
        execs = convert_projects.build_execs(books, links["costs"], links["requests"], match, prev["프로젝트집행.csv"], cfg,
                                             links["projects"])
        xchk = convert_xchk.build_xchk(books, links["costs"], links["revenue"], links["projects"], links["requests"], match,
                                       project_table.rows, xchk_meta(books, snap, now), cfg, read_bank(input_dir),
                                       card_vat=(execs.extra or {}).get("card_vat"))
        tables.extend([project_table, execs, xchk])
    tables.append(build_fundplan(books, cfg, wehago_dir, asof))
    tables.append(convert_pl.build_dept(books, cfg, _read_dept_prev(input_dir)))
    tables.append(convert_pl.build_staff(books, cfg, _read_prev_rows(input_dir, data.STAFF_FILE, data.STAFF_KEYS)))
    tables.append(convert_pl.build_dept_accounts(books, cfg, _read_prev_rows(input_dir, data.DEPT_ACCOUNT_FILE,
                                                                             data.DEPT_ACCOUNT_KEYS)))
    tables.append(build_tax(books, cfg, asof, input_dir))
    tables.extend(build_bank(books, cfg))
    tables.append(build_debts(books, cfg))
    tables.append(convert_pl.build_accounts(books, cfg, _read_prev_rows(input_dir, data.ACCOUNT_FILE, data.ACCOUNT_KEYS)))
    tables.append(build_evidence(books, sales, _read_prev_rows(input_dir, data.EVID_FILE, data.EVID_KEYS)))
    from . import annual   # 연간 보고용 (사용자 2026-11-10): 거래처별 매출·매입, 통장 흐름 분류, 결산 법인세
    tables.append(annual.build_table(books, cfg, sales, _read_prev_rows(input_dir, annual.FILE, annual.KEYS)))
    from . import cashflow   # 현금흐름표 (사용자 2026-11-12): 경영관리 보고에만
    tables.append(cashflow.build_table(books, cfg))
    from . import credit   # 기업신용평가 미리보기 (사용자 2026-11-12): 계정별 연월 합 → 재무상태표·손익
    tables.append(credit.build_table(books))
    return tables, states


def build_evidence(books, sales, prev_rows=()):
    """증빙월별.csv (사용자 2026-11-04: 매출·매입은 증빙 작성일자 기준). 달마다 공급가액 합.

    매출 = 매출 계산서 원천(분개장 매출전표 또는 매입매출장 매출 줄), 매입 = 분개장 매입전표 또는 매입매출장 매입 줄.
    전표일자 = 증빙 작성일자. 금액 모르는 줄이 있는 달은 빈칸. 새 자료에 없는 달의 이전 줄은 그대로 잇는다 (누적)."""
    cells = collections.OrderedDict()

    def add(rows, i):
        for r in rows:
            if r.get("date") is None:
                continue
            c = cells.setdefault(r["date"].strftime("%Y-%m"), [[0, 0], [0, 0]])[i]
            if r.get("supply") is None:
                c[1] += 1
            else:
                c[0] += r["supply"]
    have_sales = sales.get("state") == "ok"
    have_buys = books.state == "ok"
    if have_sales:
        add(sales["rows"], 0)
    if have_buys:
        add(books.ledger or [], 1)
    if not cells:
        return Table(data.EVID_FILE, data.EVID_KEYS, [], written=False, reason="매출·매입 증빙 자료 없음 (기존 파일 그대로)")
    cell = lambda c, ok: "" if not ok or c[1] else str(int(c[0]))
    rows = [r for r in prev_rows if r.get("연월") not in cells]
    for ym, (sv, bv) in cells.items():
        rows.append(dict(zip(data.EVID_KEYS, [ym, cell(sv, have_sales), cell(bv, have_buys)])))
    rows.sort(key=lambda r: r.get("연월", ""))
    note = "매출 %s · 매입 %s · 작성일자(전표일자) 달별 공급가액" % (
        sales.get("source") or "자료 없음" if have_sales else "자료 없음",
        ("분개장 매입전표" if getattr(books, "from_journal", False) else "매입매출장 매입") if have_buys else "자료 없음")
    return Table(data.EVID_FILE, data.EVID_KEYS, rows, notes=[note])


def build_debts(books, cfg):
    """장부채무.csv (2026-11-04 점검 A1·A2): 분개장 미지급금·차입금 거래처코드별 잔액. 보고서가 자금 일정과 맞춰 본다."""
    from . import debts
    rows, note = debts.build(books, cfg)
    return Table(debts.FILE, debts.KEYS, rows, notes=[note])


def build_bank(books, cfg):
    """분개장 보통예금(cfg cash_codes) 줄로 계좌별 잔액·입출금 (사용자 2026-11-04: 분개장 합계가 실제 통장 합계와 같음).

    잔액 = 분개장 처음부터 차변 − 대변 누적 (회사 설립 2025-02-01부터 장부가 있어 기초 잔액 0). 계좌 = 거래처(은행).
    장부잔액.csv: 달마다 말일과 장부 마지막 날의 계좌별 잔액. 장부입출금.csv: 입출금내역.csv 와 같은 열, 같은 전표에
    보통예금 차변·대변이 함께 있으면 계좌간이체. 보고서는 이 두 파일이 있으면 계좌잔액.csv 에서 사용제한만 쓴다."""
    import calendar
    cash = set(wehago._squash(c) for c in cfg["cash_codes"])
    lines = [ln for ln in books.journal if wehago._squash(ln.get("account_code")) in cash and ln["date"] is not None]
    if not lines:
        why = "분개장에 보통예금(%s) 줄 없음" % ",".join(cfg["cash_codes"])
        return [Table(data.BOOK_BAL_FILE, data.BOOK_BAL_KEYS, [], written=False, reason=why),
                Table(data.BOOK_TXN_FILE, data.SCHEMA["입출금내역.csv"], [], written=False, reason=why)]
    if not getattr(books, "from_start", True):
        # 작년 분개장이 빠지면 잔액이 '올해 증감'뿐이다: 머리글만 쓴다 (예전 파일이 남아 낡은 잔액을 쓰지 않게) → 보고서는 계좌잔액.csv
        why = "작년 분개장 없음 (분개장 %s부터, 전기이월·설립 자본금 줄 없음) → 통장 잔액은 계좌잔액.csv 사용" % min(
            ln["date"] for ln in lines).isoformat()
        return [Table(data.BOOK_BAL_FILE, data.BOOK_BAL_KEYS, [], notes=[why]),
                Table(data.BOOK_TXN_FILE, data.SCHEMA["입출금내역.csv"], [], notes=[why])]
    lines.sort(key=lambda ln: (ln["date"], str(ln.get("no") or "")))
    slips = collections.defaultdict(lambda: [False, False])
    for ln in lines:
        k = (ln["date"], ln.get("no"))
        slips[k][0] |= bool(ln["debit"])
        slips[k][1] |= bool(ln["credit"])
    acct = lambda ln: (ln.get("vendor") or "").strip() or "보통예금 (거래처 없음)"
    others = collections.defaultdict(list)   # 전표별 보통예금 아닌 줄 (상대 거래처)
    for o in books.journal:
        if o.get("date") is not None and wehago._squash(o.get("account_code")) not in cash:
            others[(o["date"], o.get("no"))].append(o)
    txns, bal, snaps = [], collections.OrderedDict(), []
    last = lines[-1]["date"]

    def snap(day):
        for a, v in bal.items():
            snaps.append(dict(zip(data.BOOK_BAL_KEYS, [day.isoformat(), a, "", str(v)])))
    month_end = None
    for ln in lines:
        d = ln["date"]
        while month_end is not None and d > month_end:
            snap(month_end)
            nxt = month_end + dt.timedelta(days=1)
            month_end = nxt.replace(day=calendar.monthrange(nxt.year, nxt.month)[1])
        if month_end is None:
            month_end = d.replace(day=calendar.monthrange(d.year, d.month)[1])
        a = acct(ln)
        v = (ln["debit"] or 0) - (ln["credit"] or 0)
        bal[a] = bal.get(a, 0) + v
        if v:
            both = slips[(d, ln.get("no"))]
            cat = data.TRANSFER if both[0] and both[1] else ""
            memo = (ln.get("memo") or "").strip()
            # 거래처 칸 (사용자 2026-11-05 지난주 대비): 같은 전표의 상대 줄 거래처. 상대 거래처가 여럿이고 금액 합이 맞으면 거래처별로 나눈다
            side = "debit" if v < 0 else "credit"
            party = [o for o in others.get((d, ln.get("no")), []) if o[side] and (o.get("vendor") or "").strip()]
            if not cat and len(party) > 1 and sum(o[side] for o in party) == abs(v):
                parts = [((o.get("vendor") or "").strip(), o[side]) for o in party]
            else:
                names = sorted(set((o.get("vendor") or "").strip() for o in party))
                parts = [(names[0] if len(names) == 1 else "", abs(v))]
            for vend, amt in parts:
                txns.append(dict(zip(data.SCHEMA["입출금내역.csv"],
                                     [d.isoformat(), a, "입금" if v > 0 else "출금", str(amt), cat, "", vend, memo])))
    if month_end is not None and month_end < last:
        snap(month_end)
    snap(last)
    note = ("보통예금 잔액 = 분개장 %s부터 차변−대변 누적 (기초 잔액 0) · 계좌 %d개 · %s 합계 %s"
            % (lines[0]["date"].isoformat(), len(bal), last.isoformat(), won(sum(bal.values()))))
    return [Table(data.BOOK_BAL_FILE, data.BOOK_BAL_KEYS, snaps, notes=[note]),
            Table(data.BOOK_TXN_FILE, data.SCHEMA["입출금내역.csv"], txns,
                  notes=["보통예금 입출금 %d줄 (같은 전표에 차변·대변 모두 있으면 계좌간이체)" % len(txns)])]


def build_tax(books, cfg, asof, input_dir=None):
    """세금예상.csv 표 (사용자 2026-11-03): 분개장으로 부가세(분기)·원천세·4대보험(회사분 포함) 납부 예상. 계산할 줄이 없으면 빈 표를 쓴다."""
    from . import tax
    mode = cfg["withholding_mode"] if cfg["withholding_mode"] in ("자동", "반기", "매월") else "자동"
    card_days, card_notes = tax.read_card_days(input_dir) if input_dir else ({}, [])
    rows = tax.vat(books.journal, asof, cfg["vat_payable_codes"], cfg["vat_codes"]) + \
        tax.withholding(books.journal, asof, cfg["withholding_codes"], cfg["withholding_vendors"], mode) + \
        tax.social(books.journal, asof, cfg["withholding_codes"], cfg["insurance_vendors"]) + \
        tax.salary(books.journal, asof, cfg["salary_codes"], pay_day=cfg["salary_pay_day"]) + \
        tax.cards(books.journal, asof, card_days) + tax.deposits(books.journal, asof)
    from . import corptax   # 법인세 예상 (사용자 2026-11-04): 지급 예상에 넣고 중간예납 등 선납세금은 뺀다
    ct_rows, ct_note = corptax.from_journal(books.journal, cfg, asof, corptax.read(input_dir) if input_dir else {})
    rows += ct_rows
    rows.sort(key=lambda r: r["납부예정일"] or "9999")
    notes = ["%s %s → %s %s %s원 (%s)" % (r["세목"], r["대상기간"], r["납부예정일"] or "날짜 미정",
                                       "입금" if r["세목"] == tax.DEPOSIT_IN else "납부", "{:,}".format(int(r["금액"])) if r["금액"] else "미확인", r["상태"]) for r in rows]
    if cfg["withholding_mode"] not in ("자동", "반기", "매월"):
        notes.append("설정 변환_원천세납부 값 '%s' 사용할 수 없음 → 자동" % cfg["withholding_mode"])
    notes.extend(card_notes)
    thin = [r for r in rows if r["세목"] == "카드대금" and r["근거"].startswith(tax.CARD_THIN_MARK)]
    if thin:   # 사용자 2026-11-04: 카드 전표 입력 전이면 진행 상황에 경고
        notes.append("[확인] 카드 전표 입력 전으로 보임: %s — 전표가 덜 들어간 카드는 최근 3달 평균을 예상으로 더 잡음. 카드 비용은 전표를 넣기 전까지 프로젝트 원가·수익률에 빠져 있음"
                     % ", ".join(r["대상기간"].replace(" (전표 입력 전 추정)", "") for r in thin))
    notes.append(ct_note)
    notes.append("확정된 세금·4대보험이 자금계획서·자금일정에 있으면 보고서는 계산값 대신 그 금액을 씀. 이미 통장에서 낸 것은 넣지 않음")
    return Table(tax.FILE, tax.COLUMNS, rows, notes=notes)


def _read_prev_rows(input_dir, name, keys):
    """이전 파일의 줄 (새 분개장에 없는 달을 잇는 데 씀). 없거나 읽지 못하면 빈 목록."""
    path = os.path.join(input_dir, name)
    if not os.path.exists(path):
        return []
    info = {}
    rows, ok = util.read_csv(path, keys, util.Issues(), info)
    if not ok or info.get("missing"):
        return []
    return [dict((k, r.get(k, "")) for k in keys) for r in rows]


def _read_dept_prev(input_dir):
    """이전 부서비용.csv 줄 (새 분개장에 없는 달을 잇는 데 씀). 없거나 읽지 못하면 빈 목록."""
    path = os.path.join(input_dir, data.DEPT_FILE)
    if not os.path.exists(path):
        return []
    info = {}
    rows, ok = util.read_csv(path, data.DEPT_KEYS, util.Issues(), info)
    if not ok or info.get("missing"):
        return []
    return [dict((k, r.get(k, "")) for k in data.DEPT_KEYS + data.DEPT_OPTIONAL) for r in rows]


def fundplan_opening_checks(openings, books, cfg):
    """현금대비잔액의 '전월이월'(전월말 보통예금)과 분개장 보통예금 잔액 대조 (2026-11-05: 실제 10/31 원 단위 일치 확인).
    분개장이 처음부터 있지 않으면(작년 분개장 없음) 잔액을 셀 수 없어 대조하지 않는다."""
    if not openings:
        return []
    if not getattr(books, "from_start", True):
        return ["자금계획서 전월이월 대조 안 함: 작년 분개장이 없어 보통예금 잔액을 셀 수 없음"]
    cash = set(wehago._squash(c) for c in cfg["cash_codes"])
    out = []
    for (y, m), amount, name in openings:
        first = dt.date(y, m, 1)
        if books.book_date is not None and books.book_date < first - dt.timedelta(days=1):
            out.append("%s 전월이월 대조 안 함: 분개장이 %s까지라 전월말 잔액을 모름" % (name, books.book_date.isoformat()))
            continue
        bal = sum((ln.get("debit") or 0) - (ln.get("credit") or 0) for ln in books.journal
                  if ln.get("date") is not None and ln["date"] < first and wehago._squash(ln.get("account_code")) in cash)
        if bal == amount:
            out.append("%s 전월이월 %s원 = 분개장 %s 보통예금 잔액 (일치)" % (name, "{:,}".format(amount),
                                                                 (first - dt.timedelta(days=1)).isoformat()))
        else:
            out.append("[확인] %s 전월이월 %s원 ≠ 분개장 %s 보통예금 잔액 %s원 (차이 %s원) — 자금계획서와 분개장 받은 시점이 다르거나 "
                       "장부가 바뀜" % (name, "{:,}".format(amount), (first - dt.timedelta(days=1)).isoformat(),
                                    "{:,}".format(bal), "{:,}".format(amount - bal)))
    return out


def build_fundplan(books, cfg, wehago_dir, asof):
    """자금계획서 현금대비잔액·지출입금현황(.xls) -> 자금계획.csv 표 (D-55, 현금대비잔액 2026-11-05). 쓸 파일이 없으면 만들지 않고 기존 파일을 그대로 둔다."""
    from . import fundplan
    res = fundplan.load(wehago_dir)
    notes = list(res["notes"])
    if not res["rows"]:
        reason = ("자금계획서(현금대비잔액·지출입금현황) 파일 없음 (기존 파일 그대로)" if not notes
                  else "쓸 수 있는 자금계획서 없음 (기존 파일 그대로): " + " / ".join(notes))
        return Table("자금계획.csv", fundplan.COLUMNS, [], written=False, reason=reason)
    counts = fundplan.settle(res["rows"], books, asof, cfg["payable_codes"], cfg["receivable_codes"], cfg["cash_codes"])
    stamps = sorted(set(m[2] for m in res["months"]))
    gap = (stamps[-1] - books.book_date).days
    notes.append("자료일 %s · 장부 기준일 %s%s" % (
        ", ".join(d.isoformat() for d in stamps), books.book_date.isoformat(),
        " — 그 사이 %d일의 지급·입금은 분개장으로 확인 못함" % gap if gap > 0 else ""))
    notes.append("분개장 대조: " + " · ".join("%s %d" % (k, counts[k]) for k in fundplan.STATES))
    notes.extend(fundplan_opening_checks(res.get("openings") or [], books, cfg))
    for r in res["rows"]:
        if r["상태"] != "예정":
            notes.append("  %s %s %s %s %s원 — %s" % (r["상태"], r["예정일"], r["입출금"], r["거래처"],
                                                   "{:,}".format(r["금액"]), r["근거"]))
    return Table("자금계획.csv", fundplan.COLUMNS, res["rows"], notes=notes)


def run(input_dir, collect_dir, wehago_dir, asof, now, stamp=None):
    """변환 한 번. 장부·스냅숏·파일 문제로 예외를 내지 않고 Result.code 로 알린다."""
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
    snap, snap_line = read_latest_snapshot(collect_dir)
    states, cross = {}, []
    if books.state != "ok":
        res.code = 3
        tables = _unwritten("WEHAGO 장부를 쓸 수 없음")
    else:
        drop_closing_pl(books, cfg)
        tables, states = _build_tables(books, cfg, snap, input_dir, wehago_dir, asof, now, res)
        cross = cross_checks(tables)
    res.tables = tables
    names = [t.name for t in tables if t.written] + ["변환결과.txt"]
    backup, moved = plan_backup(input_dir, names, stamp)
    where = "입력/이전/%s/" % backup if backup else ""
    for t in tables:
        if t.written and states.get(t.name) == "읽지 못함":
            if t.name == "손익.csv":
                t.notes.append("이전 손익.csv를 읽지 못해 WEHAGO 외 출처 줄을 옮기지 못함 (%s 에 원본 보관)" % where)
            else:
                t.notes.append("이전 %s를 읽지 못해 옮길 줄을 옮기지 못함 (%s 에 원본 보관)" % (t.name, where))
    kept = [m for m in MANUAL if os.path.exists(os.path.join(input_dir, m))]
    backup_line = "이전 파일: %s (%s)" % (where, ", ".join(moved)) if backup else "이전 파일: 없음"
    csv_payloads = [(t.name, table_bytes(t)) for t in tables if t.written]
    try:
        precheck_writable(input_dir, [n for n, _ in csv_payloads] + ["변환결과.txt"])   # 하나라도 잠겼으면 아무것도 바꾸지 않는다
        if csv_payloads:
            write_files(input_dir, csv_payloads, stamp, backup)
    except WriteFailed as e:
        res.code = 7
        # 바꾸는 중 실패: 이미 바꾼 CSV 는 되돌렸다. 변환결과.txt 를 실패로 다시 써서 이전 결과가 새 실행을 말하지 않게 한다 (WR-01)
        res.lines = _failure_result(input_dir, now, asof, e, stamp, backup) if e.stage == "replace" else _write_failed_lines(e)
        return res
    # 2단계: 새 CSV 가 놓인 폴더를 읽기만 해서 목록을 만들고 변환결과.txt 를 쓴다
    listings, summary = [], []
    if snap is not None:   # 지급 요청서 세부사항 첫 줄 (사용자 2026-11-05): 최근 스냅숏 것을 입력 폴더로
        from . import payreq
        if os.path.exists(os.path.join(snap.path, payreq.FILE)):
            reqs = payreq.read(snap.path)
            try:
                payreq.write(input_dir, reqs)
                summary.append("지급 요청서(관리팀 승인·사장님 승인 전) %d건 · 세부사항 있음 %d건 → 주간 출금 목록 상세 내역에 맞춰 붙임"
                               % (len(reqs), sum(1 for r in reqs if r["note"])))
            except OSError:
                summary.append("지급 요청서 파일을 입력 폴더에 쓰지 못함 (%s)" % payreq.FILE)
        else:   # 최근 수집에 지급 요청서가 없으면 예전 것을 남기지 않는다 (지난 세부사항이 새 출금에 붙지 않게)
            try:
                os.remove(os.path.join(input_dir, payreq.FILE))
            except OSError:
                pass
    if books.state == "ok":
        from . import review_checks
        tidy = review_checks.archive_paid_schedule(input_dir, books.journal, books.book_date, cfg["cash_codes"])
        from . import insights   # 자동 분석용 장부 풀이: 고정비·매달 있어야 할 전표 (사용자 2026-11-12)
        insights.write_facts(input_dir, insights.book_facts(books.journal, asof, books.book_date, cfg["cash_codes"]))
        dups = review_checks.duplicate_lines(books.journal)
        overlap, checks = overlap_lines(input_dir, tables), input_check_lines(input_dir)
        from . import checklist, hometax
        ht = hometax.compare(collect_dir, books.journal)   # 홈택스 전자세금계산서 대조 (사용자 2026-11-05)
        listings = tidy + overlap + dups + ht["notes"] + checks
        summary = summary + ([tidy[0]] if tidy else []) + [overlap[0], dups[0]] + [n for n in ht["notes"] if n.startswith("홈택스 ") and "대조" in n] + [checks[0]]
        items = (review_checks.duplicate_items(books.journal) + ht["items"]
                 + checklist.convert_items(tables, cross, [n for t in tables for n in (t.notes or [])]))
        trace = {k: v["text"] for k, v in review_checks.payable_trace(books.journal, cfg["payable_codes"], books.book_date).items()
                 if v["text"]}
        checklist.save_convert_items(input_dir, items, now, trace)
    snap_console, snap_warning = snapshot_lines(snap, snap_line, asof, cfg)
    lines = result_lines(now, asof, books, cfg, cfg_notes, tables, backup_line, kept, snap_line, res.links, cross, listings,
                         snap_warning)
    try:
        write_files(input_dir, [("변환결과.txt", _text_bytes(lines))], stamp, backup)
    except WriteFailed as e:
        res.code = 7
        # 새 CSV 와 맞는 변환결과.txt 를 쓰지 못했다: CSV 도 되돌려 폴더가 한 실행의 결과만 담게 한다 (WR-01)
        restored, lost = roll_back(input_dir, [n for n, _ in csv_payloads], set(moved), backup)
        e.replaced, e.restored, e.lost, e.backup = [n for n, _ in csv_payloads], restored, lost, backup
        res.lines = _write_failed_lines(e)
        return res
    res.backup = os.path.join(input_dir, "이전", backup) if backup else None
    out = []
    if books.state == "ok":   # 이체 파일용 거래처 계좌 목록에 보통예금으로 지급한 매입 거래처를 코드·이름만 더함 (사용자 2026-11-04)
        from . import transfer
        try:
            added = transfer.register_vendors(input_dir, transfer.paid_vendors(books.journal))
            if added:
                out.append("거래처 계좌 목록에 새 거래처 %d곳 등록 (코드·이름만 — 계좌는 창 ⑦에서)" % added)
        except (OSError, ValueError) as e:
            out.append("거래처 계좌 목록을 고치지 못함: %s" % (e if isinstance(e, ValueError) else type(e).__name__))
    if books.state != "ok":
        out.append("변환하지 않음 — WEHAGO 장부를 쓸 수 없음: " + books.reason)
    else:
        late = (asof - books.book_date).days
        out.append("WEHAGO 장부 기준일 %s%s" % (books.book_date.isoformat(),
                                             " · 기준일보다 %d일 이전" % late if late > 0 else ""))
    out.append(snap_console)   # 어떤 스냅숏을 썼는지 (WR-06)
    if snap_warning:
        out.append(snap_warning)
    warning = status_warning(res.links)
    if warning:
        out.append(warning)
    for t in tables:
        out.append("%s 만듦 %d줄" % (t.name, len(t.rows)) if t.written else "[%s] 만들지 않음 — %s" % (t.name, t.reason))
    if res.links is not None:
        out.append(util.mask_rrn(link_stdout_line(res.links)))
    if backup:
        out.append(backup_line)
    if _undecided(tables, cross):
        out.append("대조 판단 불가 %d건" % _undecided(tables, cross))
    out.append("대조 불일치 %d건" % _mismatches(tables, cross))
    out.extend(n for t in tables for n in (t.notes or []) if str(n).startswith("[확인] 카드 전표 입력 전"))   # 진행 상황 칸에도 (사용자 2026-11-04)
    out.extend(summary)
    out.append("대조 내용: " + os.path.join(input_dir, "변환결과.txt"))
    res.lines = out
    return res
