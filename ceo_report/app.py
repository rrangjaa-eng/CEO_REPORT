"""한 화면 프로그램의 일 (사용자 2026-11-03: 실행 파일 여러 개 말고 창 하나에서 버튼·입력으로).

창(gui.py)은 이 함수들만 부른다. 창 없이도 시험할 수 있게 tkinter 를 쓰지 않는다.
  · run_task: 변환 · 주간 · 월간 · 승인검토를 같은 프로세스에서 돌리고 화면에 찍을 글을 넘긴다
  · add_schedule: 아직 장부에 없는 지출·입금 예정을 입력/자금일정.csv 에 한 줄 더한다 (가용자금에 바로 반영)
  · archive_old: 변환에 쓰지 않는 예전 WEHAGO 엑셀·자금계획서를 수집/위하고/지난자료 로 옮긴다
"""
import contextlib
import csv
import datetime as dt
import io
import os
import shutil
import sys
import time

from . import fundplan, wehago
from .data import SCHEMA
from .util import date as parse_date

ARCHIVE = "지난자료"
SCHED_FILE = "자금일정.csv"
TASKS = ("변환", "주간", "월간", "승인검토")


def program_dir():
    """프로그램 폴더 (입력·수집·출력이 있는 곳). exe 로 묶였으면 exe 가 있는 폴더."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Paths(object):
    def __init__(self, root=None):
        self.root = root or program_dir()
        self.input = os.path.join(self.root, "입력")
        self.collect = os.path.join(self.root, "수집")
        self.wehago = os.path.join(self.collect, "위하고")
        self.output = os.path.join(self.root, "출력")


class _Lines(io.TextIOBase):
    """print 글을 한 줄씩 say 로 넘긴다."""

    def __init__(self, say):
        self.say, self.buf = say, ""

    def writable(self):
        return True

    def write(self, text):
        self.buf += text
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            self.say(line)
        return len(text)

    def flush(self):
        if self.buf:
            self.say(self.buf)
            self.buf = ""


def _check_day(text, label):
    if not text:
        return None
    d = parse_date(text)
    if d is None:
        raise ValueError("%s 형식 오류: %s (예: 2026-11-30)" % (label, text))
    return d


def task_argv(task, paths, asof="", pick=""):
    """작업 이름 -> (모듈 이름, argv). 날짜는 비우면 오늘."""
    _check_day(asof, "기준일")
    _check_day(pick, "가용자금 볼 날짜")
    day = ["--기준일", asof] if asof else []
    if task == "변환":
        return "변환", day + ["--입력", paths.input, "--수집폴더", paths.collect]
    if task in ("주간", "월간"):
        return "보고서", [task] + day + (["--가용일", pick] if pick else []) + ["--입력", paths.input, "--출력", paths.output]
    if task == "승인검토":
        return "승인검토", day + ["--입력", paths.input, "--출력", paths.output, "--수집폴더", paths.collect]
    raise ValueError("모르는 작업: %s" % task)


def _module(name):
    # PyInstaller 가 찾을 수 있게 이름을 그대로 적는다
    if name == "변환":
        import 변환 as m
    elif name == "보고서":
        import 보고서 as m
    else:
        import 승인검토 as m
    return m


def run_task(task, paths, say, asof="", pick="", collect=False, credentials=None):
    """작업 하나를 돌리고 (종료코드, 새로 생긴 출력 파일 목록)을 돌려준다. 글은 say(한 줄)로 넘긴다.

    승인검토에서 collect=True 면 인트라넷에서 새로 읽는다. credentials() -> (ID, 비밀번호): 창의 입력칸에서 받는다.
    비밀번호는 글로 찍지 않는다 (승인검토가 오류 글에서도 가림)."""
    try:
        name, argv = task_argv(task, paths, asof, pick)
    except ValueError as e:
        say(str(e))
        return 2, []
    if task == "승인검토" and collect:
        argv += ["--수집", "함"]
    started = time.time() - 1
    out = _Lines(say)
    mod = _module(name)
    old_cred = getattr(mod, "CREDENTIALS", None)
    try:
        if task == "승인검토":
            mod.CREDENTIALS = credentials
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                rc = mod.main(argv)
            except SystemExit as e:   # argparse 오류 등
                rc = e.code if isinstance(e.code, int) else 2
            except Exception as e:   # 트레이스백을 보이지 않는다
                say("예상하지 못한 오류 (%s): %s" % (type(e).__name__, str(e)[:200]))
                rc = 7
    finally:
        out.flush()
        if task == "승인검토":
            mod.CREDENTIALS = old_cred
    return rc, new_files(paths.output, started)


def new_files(folder, since):
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    for n in names:
        p = os.path.join(folder, n)
        if os.path.isfile(p) and os.path.getmtime(p) >= since:
            out.append(p)
    return sorted(out, key=os.path.getmtime)


# ───────────── 아직 장부에 없는 지출·입금 예정 넣기 ─────────────
def _encoding(path):
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", raw
    try:
        raw.decode("utf-8")
        return "utf-8", raw
    except UnicodeDecodeError:
        return "cp949", raw


def add_schedule(input_dir, day, io_kind, amount, firm, vendor, cat="", basis="", memo="", project=""):
    """입력/자금일정.csv 에 한 줄을 더한다. 잘못된 값은 ValueError (글은 그대로 화면에 보인다). -> 더한 줄 dict."""
    d = _check_day((day or "").strip(), "예정일")
    if d is None:
        raise ValueError("예정일을 넣으세요 (예: 2026-11-30)")
    if io_kind not in ("지급", "입금"):
        raise ValueError("입출금은 지급 또는 입금")
    if firm not in ("확정", "예상"):
        raise ValueError("확정여부는 확정 또는 예상")
    text = str(amount or "").replace(",", "").replace("원", "").strip()
    if not text.isdigit() or int(text) <= 0:
        raise ValueError("금액은 0보다 큰 숫자 (예: 3,300,000)")
    if not (vendor or "").strip():
        raise ValueError("거래처를 넣으세요")
    header = SCHEMA[SCHED_FILE]
    row = {"예정일": d.isoformat(), "입출금": io_kind, "금액": "{:,}".format(int(text)), "확정여부": firm,
           "분류": cat.strip() or ("기타지급" if io_kind == "지급" else "기타입금"), "프로젝트번호": project.strip(),
           "거래처": vendor.strip(), "근거": basis.strip() or "직접 입력", "비고": memo.strip()}
    path = os.path.join(input_dir, SCHED_FILE)
    if not os.path.isdir(input_dir):
        raise ValueError("입력 폴더가 없습니다: %s" % input_dir)
    if os.path.exists(path):
        enc, raw = _encoding(path)
        text_now = raw.decode(enc)
        first = next(csv.reader([text_now.splitlines()[0]])) if text_now.strip() else []
        cols = [c.strip() for c in first] or header
        if not set(["예정일", "입출금", "금액"]) <= set(cols):
            raise ValueError("자금일정.csv 머리글이 양식과 다릅니다 — 파일을 확인하세요")
        nl = "\r\n" if "\r\n" in text_now else "\n"
        buf = io.StringIO()
        csv.writer(buf, lineterminator=nl).writerow([row.get(c, "") for c in cols])
        add = ("" if not text_now or text_now.endswith(("\n", "\r")) else nl) + buf.getvalue()
        with open(path, "ab") as f:
            f.write(add.encode("utf-8" if enc == "utf-8-sig" else enc))
    else:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, lineterminator="\r\n")
            w.writerow(header)
            w.writerow([row[c] for c in header])
    return row


# ───────────── 쓰지 않는 예전 파일을 지난자료로 ─────────────
def old_files(wehago_dir, asof):
    """[(파일 이름, 까닭)] — 변환이 쓰지 않는 예전 파일.

    WEHAGO 장부(분개장·매입매출장·전자세금계산서(매입)): 종류마다 가장 새 파일과, 지난해 장부는 해마다 가장 새 파일 하나만 남긴다.
    자금계획서: 이번 달 이후 달만 쓴다. 같은 달 파일이 여럿이면 가장 새 것만 남긴다. 읽지 못한 파일은 옮기지 않는다 (확인하도록)."""
    try:
        names = sorted(n for n in os.listdir(wehago_dir) if os.path.isfile(os.path.join(wehago_dir, n)) and not n.startswith("~$"))
    except OSError:
        return []
    out = []
    groups = {}
    for n in names:
        kind, readable = wehago._kind_of(n)
        if kind is None or not readable or fundplan.is_fundplan_name(n):
            continue
        groups.setdefault(kind, []).append(n)
    for kind, files in groups.items():
        ranked = sorted(files, key=lambda n: (wehago._rank_date(n) or dt.date.min, wehago._mtime(os.path.join(wehago_dir, n)), n))
        newest = ranked[-1]
        top = (wehago._rank_date(newest) or dt.date.min).year
        keep_year = {}
        for n in ranked:
            y = (wehago._rank_date(n) or dt.date.min).year
            if y < top:
                keep_year[y] = n   # 지난해 장부: 그 해 가장 새 파일
        keep = set([newest] + list(keep_year.values()))
        for n in ranked:
            if n not in keep:
                out.append((n, "%s 더 새 파일이 있음" % kind))
    res = fundplan.load(wehago_dir)
    month_now = (asof.year, asof.month)
    used = set()
    for ym, name, _ in res["months"]:
        y, m = int(str(ym)[:4]), int(str(ym)[5:7])
        if (y, m) < month_now:
            out.append((name, "자금계획서 지난 달 (%s)" % ym))
        else:
            used.add(name)
    month_names = set(name for _, name, _ in res["months"])
    for n in res["unused"]:
        if n in month_names or n in used:
            continue
        note = " ".join(x for x in res["notes"] if x.startswith(n))
        if "더 새 파일 있음" not in note:
            continue   # 읽지 못한 파일은 사람이 확인하도록 그대로 둔다
        out.append((n, "자금계획서 같은 달 더 새 파일이 있음"))
    return out


def archive_old(wehago_dir, asof, say):
    """old_files 를 wehago_dir/지난자료 로 옮긴다 (지우지 않음). -> 옮긴 파일 수."""
    todo = old_files(wehago_dir, asof)
    if not todo:
        say("옮길 예전 파일이 없습니다 (%s)" % wehago_dir)
        return 0
    dest = os.path.join(wehago_dir, ARCHIVE)
    os.makedirs(dest, exist_ok=True)
    n = 0
    for name, why in todo:
        target = os.path.join(dest, name)
        base, ext = os.path.splitext(name)
        k = 2
        while os.path.exists(target):
            target = os.path.join(dest, "%s_%d%s" % (base, k, ext))
            k += 1
        try:
            shutil.move(os.path.join(wehago_dir, name), target)
        except OSError as e:
            say("옮기지 못함: %s (%s) — 엑셀에서 열려 있으면 닫고 다시 하세요" % (name, e.strerror or type(e).__name__))
            continue
        n += 1
        say("지난자료로 옮김: %s — %s" % (name, why))
    say("예전 파일 %d건을 %s 폴더로 옮겼습니다 (지우지 않음)" % (n, os.path.join("수집", "위하고", ARCHIVE)))
    return n
