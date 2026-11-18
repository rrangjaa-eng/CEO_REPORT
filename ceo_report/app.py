"""한 화면 프로그램의 일 (사용자 2026-11-03: 실행 파일 여러 개 말고 창 하나에서 버튼·입력으로).

창(gui.py)은 이 함수들만 부른다. 창 없이도 시험할 수 있게 tkinter 를 쓰지 않는다.
  · run_task: 변환 · 주간 · 월간 · 인트라넷 가져오기를 같은 프로세스에서 돌리고 화면에 찍을 글을 넘긴다
  · add_schedule: 아직 장부에 없는 지출·입금 예정을 입력/자금일정.csv 에 한 줄 더한다 (가용자금에 바로 반영)
  · archive_old: 변환에 쓰지 않는 예전 WEHAGO 엑셀·자금계획서를 수집/위하고/지난자료 로 옮긴다
"""
import contextlib
import csv
import datetime as dt
import io
import os
import re
import shutil
import sys
import time

from . import fundplan, wehago
from .data import SCHEMA
from .util import date as parse_date
from .util import open_text as _open_text  # UTF-8·CP949 모두 읽음 (C5)

ARCHIVE = "지난자료"
SCHED_FILE = "자금일정.csv"
TASKS = ("변환", "주간", "월간", "인트라넷", "자동")   # 지급 승인 검토 화면은 뺌 (사용자 2026-11-04 불필요, 2026-11-14 확정)


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


def task_argv(task, paths, asof="", pick="", nums="", payday="", group="", only="", year=""):
    """작업 이름 -> (모듈 이름, argv). 날짜는 비우면 오늘. 근거주간·근거월간은 nums(근거 번호, 예: 1-1,3-2)가 있어야 한다."""
    _check_day(asof, "기준일")
    _check_day(pick, "가용자금 볼 날짜")
    _check_day(payday, "출금일")
    day = ["--기준일", asof] if asof else []
    if task == "변환":
        return "변환", day + ["--입력", paths.input, "--수집폴더", paths.collect]
    if task in ("주간", "월간"):
        group, only = merge_args(group, only) if group else (group, only)
        return "보고서", ([task] + day + (["--가용일", pick] if pick else [])
                        + (["--출금일", payday] if payday and task == "주간" else [])
                        + (["--출금목록", group] if group and task == "주간" else [])
                        + (["--합칠거래처", only] if only and group == "거래처별" and task == "주간" else [])
                        + ["--입력", paths.input, "--출력", paths.output])
    if task == "연간":   # 연간 보고 (사용자 2026-11-10): 연도를 비우면 기준일의 해 (1~3월이면 지난해)
        y = (year or "").strip()
        if y and not (y.isdigit() and len(y) == 4):
            raise ValueError("연도 형식 오류: %s (예: 2026)" % y)
        return "보고서", ["연간"] + day + (["--연도", y] if y else []) + ["--입력", paths.input, "--출력", paths.output]
    if task == "기획본부":   # 기획본부용 재무상태표 엑셀 (사용자 2026-11-17)
        return "보고서", ["기획본부"] + day + ["--입력", paths.input, "--출력", paths.output]
    if task in ("근거주간", "근거월간"):   # 대표가 요청한 근거만 따로 (사용자 2026-11-03)
        from .evidence import parse_nums
        return "보고서", [task[2:]] + day + ["--근거", ",".join(parse_nums(nums)), "--출력", paths.output]
    if task in ("예산", "예산확정"):   # 내년 예산 초안·확정 (사용자 2026-11-10)
        y = str(year or "").strip()
        if y and not (y.isdigit() and len(y) == 4):
            raise ValueError("예산 연도는 4자리 (예: 2027)")
        return "예산", (day + (["--연도", y] if y else []) + ["--입력", paths.input, "--출력", paths.output]
                      + (["--확정", "함"] if task == "예산확정" else []))
    if task == "인트라넷":   # 가져오기만 (사용자 2026-11-04: 승인 검토 화면은 만들지 않음)
        return "승인검토", day + ["--입력", paths.input, "--출력", paths.output, "--수집폴더", paths.collect, "--화면", "안함"]
    raise ValueError("모르는 작업: %s" % task)


def _module(name):
    # PyInstaller 가 찾을 수 있게 이름을 그대로 적는다
    if name == "변환":
        import 변환 as m
    elif name == "보고서":
        import 보고서 as m
    elif name == "예산":
        import 예산 as m
    else:
        import 승인검토 as m
    return m


BACKUP_DIR = "입력_백업"
BACKUP_KEEP = 10
_BACKUP_NAME = re.compile(r"^\d{8}_\d{6}(_\d+)?$")   # 다 만든 백업만 (반쯤 만든 '_실패'는 세지도 지우지도 않음)


def backup_input(paths, say=None, keep=BACKUP_KEEP, now=None):
    """변환 전에 입력 폴더를 통째로 입력_백업\날짜_시각 에 복사하고 최근 keep 개만 남긴다 (사용자 2026-11-05: 편의 기능 6).
    입력\이전(변환이 바꾼 파일 보관)과 인트라넷 계정 파일은 복사하지 않는다. -> 만든 폴더 또는 None."""
    from . import credstore
    if not os.path.isdir(paths.input):
        return None
    base = os.path.join(paths.root, BACKUP_DIR)
    stamp = (now or dt.datetime.now()).strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(base, stamp)
    k = 2
    while os.path.exists(dest):
        dest = os.path.join(base, "%s_%d" % (stamp, k))
        k += 1
    try:
        os.makedirs(base, exist_ok=True)
        shutil.copytree(paths.input, dest, ignore=shutil.ignore_patterns("이전", credstore.CRED_FILE, "*.tmp", "~$*"))
    except OSError as e:
        # 2차 P6-10 (2026-11-15): 반쯤 만든 백업이 남아 다음 번 '최근 10개'에 끼면 멀쩡한 옛 백업이 지워졌다 — 치우거나 '_실패'로
        shutil.rmtree(dest, ignore_errors=True)
        if os.path.exists(dest):
            try:
                os.replace(dest, dest + "_실패")
            except OSError:
                pass
        if say:
            say("입력 폴더 백업을 못 함 (%s) — 변환은 계속합니다" % (e.strerror or type(e).__name__))
        return None
    olds = sorted(n for n in os.listdir(base) if os.path.isdir(os.path.join(base, n)) and _BACKUP_NAME.match(n))
    for n in olds[:-keep] if keep and len(olds) > keep else []:
        shutil.rmtree(os.path.join(base, n), ignore_errors=True)
    if say:
        say("입력 폴더 백업: %s (최근 %d개만 남김)" % (os.path.join(BACKUP_DIR, os.path.basename(dest)), keep))
    return dest


def run_integrity(paths, say, asof=""):
    """정합성 점검 (사용자 2026-11-05: 창에 버튼). 입력 폴더는 바꾸지 않는다. -> (종료코드, 결과 파일)."""
    from . import integrity
    try:
        day = _check_day(asof, "기준일")
    except ValueError as e:
        say(str(e))
        return 2, None
    out = os.path.join(paths.root, "정합성점검.txt")
    rc = integrity.run(paths.root, out, day)
    try:
        with open(out, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    keep = [ln for ln in lines if ln.startswith("#") or "← 바뀜" in ln or "바뀐 숫자" in ln or "확인 필요" in ln or "대조 " in ln
            or "점검 오류" in ln]
    for ln in keep[:60]:
        say(ln)
    return rc, out


# ───────────── 크롬 확장 자동수집 파일 가져오기 (2026-11-05) ─────────────
AUTO_DIR = "위하고자동수집"   # 확장 '대표보고 위하고 수집'이 크롬 다운로드 폴더 안에 만드는 폴더
AUTO_SUFFIX = "자동수집.json"


def chrome_download_dirs(env=None):
    """크롬 다운로드 폴더 후보: 각 크롬 프로필 설정의 download.default_directory, 그리고 사용자 '다운로드' 폴더.
    외장하드의 프로그램을 어느 PC에서 열어도 그 PC 크롬의 폴더를 찾는다."""
    import json
    env = os.environ if env is None else env
    out = []
    local = env.get("LOCALAPPDATA")
    if local:
        base = os.path.join(local, "Google", "Chrome", "User Data")
        try:
            profiles = [n for n in os.listdir(base) if n == "Default" or n.startswith("Profile ")]
        except OSError:
            profiles = []
        for prof in sorted(profiles):
            try:
                with open(os.path.join(base, prof, "Preferences"), encoding="utf-8") as f:
                    d = (json.load(f).get("download") or {}).get("default_directory")
            except (OSError, ValueError, AttributeError):
                d = None
            if d and d not in out:
                out.append(d)
    home = env.get("USERPROFILE") or env.get("HOME")
    if home:
        d = os.path.join(home, "Downloads")
        if d not in out:
            out.append(d)
    return out


def _same_file(a, b):
    """두 파일 내용이 같은가 (크기가 같을 때만 바이트 비교)."""
    import filecmp
    try:
        return os.path.getsize(a) == os.path.getsize(b) and filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def _json_info(path):
    """자동수집 파일 -> (끝까지 읽히는 JSON 인가, 확장이 적은 '수집시각' 또는 '')."""
    import json
    try:
        with open(path, encoding="utf-8-sig") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return False, ""
    return True, (str(d.get("수집시각") or "").strip() if isinstance(d, dict) else "")


def _json_ok(path):
    """자동수집 파일이 끝까지 읽히는 JSON 인가 (받다 끊긴 파일·깨진 파일은 False)."""
    return _json_info(path)[0]


def _in_archive(paths, name, src):
    """수집/위하고/지난자료 에 src 와 내용이 같은 같은 이름(또는 이름_2 꼴) 파일이 있으면 그 경로."""
    arch = os.path.join(paths.wehago, ARCHIVE)
    base, ext = os.path.splitext(name)
    try:
        cands = [n for n in os.listdir(arch) if n == name or (n.startswith(base + "_") and n.endswith(ext))]
    except OSError:
        return None
    for n in sorted(cands):
        if _same_file(src, os.path.join(arch, n)):
            return os.path.join(arch, n)
    return None


def _to_archive(paths, src, name):
    """src 를 수집/위하고/지난자료 로 옮긴다 (같은 이름이 있으면 이름_2 …). -> 옮긴 경로."""
    dest = os.path.join(paths.wehago, ARCHIVE)
    os.makedirs(dest, exist_ok=True)
    target = os.path.join(dest, name)
    base, ext = os.path.splitext(name)
    k = 2
    while os.path.exists(target):
        target = os.path.join(dest, "%s_%d%s" % (base, k, ext))
        k += 1
    shutil.move(src, target)
    return target


def import_auto(paths, say, dirs=None):
    """크롬 다운로드 폴더의 위하고자동수집/*자동수집.json 을 수집/위하고 로 옮긴다. -> 새로 가져온 파일 수.

    안전-05 (2026-11-15, R4·C10): 장부에는 급여 같은 개인정보가 있어 PC 다운로드 폴더에 남기지 않는다. 외장하드로 복사해
    내용이 같은 것을 확인한 뒤에만 다운로드 쪽을 지운다. 예전엔 복사만 해서, 지난자료로 옮긴 옛 파일이 다음 변환 때 다시
    들어왔다 — 이제 지난자료에 같은 내용이 있으면 다시 가져오지 않는다. 지우는 것은 외장하드에 같은 내용이 있을 때뿐이고,
    그 밖의 옛 파일(같은 이름의 더 새 파일이 이미 있음)은 지난자료로 옮긴다. 같은 이름의 예전 파일을 새 파일로 바꿀 때는
    예전 파일을 지난자료로 먼저 옮긴다 (덮어써 잃지 않게)."""
    n = 0
    for base in (chrome_download_dirs() if dirs is None else dirs):
        src_dir = os.path.join(base, AUTO_DIR)
        try:
            names = sorted(x for x in os.listdir(src_dir) if x.endswith(AUTO_SUFFIX))
        except OSError:
            continue
        for name in names:
            src, dst = os.path.join(src_dir, name), os.path.join(paths.wehago, name)
            try:
                kept = _in_archive(paths, name, src)
                if kept or (os.path.exists(dst) and _same_file(src, dst)):
                    os.remove(src)   # 외장하드에 같은 내용이 이미 있음 → 다운로드 쪽만 지움
                    say("다운로드 폴더의 자동수집 파일 정리: %s (이미 %s에 있음 — 다시 가져오지 않음)"
                        % (name, "수집\\위하고\\" + ARCHIVE if kept else "수집\\위하고"))
                    continue
                s_ok, s_at = _json_info(src)
                if not s_ok:   # 2차 P1-10·P2-3: 깨진 파일이 '가져옴'으로 들어와 멀쩡한 같은 이름 원본을 밀어냈다
                    moved = _to_archive(paths, src, name)
                    say("[확인] 다운로드 폴더의 자동수집 파일이 깨져(받다 끊김 등) 가져오지 않고 지난자료로 옮김: %s — "
                        "지금 쓰는 원본은 그대로 둠, 위하고 확장에서 다시 받으세요" % os.path.basename(moved))
                    continue
                d_ok, d_at = _json_info(dst) if os.path.exists(dst) else (False, "")
                # 2차 P1-9·P6-6: 어느 쪽이 새것인지는 확장이 적은 수집시각으로 (다른 크롬 프로필에서 늦게 복사돼 파일 시각만 새로운
                # 옛 수집이 새 수집을 밀어냈다). 수집시각이 없을 때만 파일 시각. 지금 것이 깨졌으면 새 파일로 바꾼다
                if d_ok and ((s_at <= d_at) if (s_at and d_at) else os.path.getmtime(dst) >= os.path.getmtime(src)):
                    moved = _to_archive(paths, src, name)
                    say("다운로드 폴더의 옛 자동수집 파일을 지난자료로 옮김: %s (같은 이름의 더 새 수집이 이미 있음%s)"
                        % (os.path.basename(moved), " — 수집시각 %s ≤ %s" % (s_at, d_at) if (s_at and d_at) else ""))
                    continue
                os.makedirs(paths.wehago, exist_ok=True)
                tmp = dst + ".가져오는중"
                shutil.copy2(src, tmp)
                if not _same_file(src, tmp):
                    os.remove(tmp)
                    raise OSError(0, "복사한 내용이 원본과 다름")
                if os.path.exists(dst):
                    old = _to_archive(paths, dst, name)   # 같은 이름의 예전 파일은 잃지 않게 지난자료로
                    say("같은 이름의 예전 파일을 지난자료로 옮김: %s" % os.path.basename(old))
                os.replace(tmp, dst)
                os.remove(src)
            except OSError as e:
                say("자동수집 파일을 가져오지 못함: %s (%s)" % (name, e.strerror or type(e).__name__))
                continue
            n += 1
            say("크롬 자동수집 파일 가져옴: %s (다운로드 폴더에서 옮김)" % name)
    return n


def run_task(task, paths, say, asof="", pick="", collect=False, credentials=None, nums="", payday="", group="", only="", year=""):
    """작업 하나를 돌리고 (종료코드, 새로 생긴 출력 파일 목록)을 돌려준다. 글은 say(한 줄)로 넘긴다.

    승인검토에서 collect=True 면 인트라넷에서 새로 읽는다. credentials() -> (ID, 비밀번호): 창의 입력칸에서 받는다.
    비밀번호는 글로 찍지 않는다 (승인검토가 오류 글에서도 가림)."""
    if task != "변환":   # C6 (2026-11-15): 변환이 도는 중(또는 끊겨 잠금이 남은 15분 안)에는 반쯤 바뀐 자료로 보고를 만들지 않는다
        from .convert import LOCK_FILE, lock_age
        age = lock_age(paths.input)
        if age is not None:
            say("자료 변환이 아직 끝나지 않았습니다 (입력\\%s, %d분 전부터) — 변환이 끝난 뒤 다시 하세요. 창을 모두 닫았는데도 "
                "이 글이 나오면 변환이 중간에 끊긴 것이니 '자료 변환'을 다시 하세요 (15분 뒤 저절로 풀림)" % (LOCK_FILE, int(age // 60)))
            return 7, []
    if task == "자동":
        return run_auto(paths, say, asof, pick, payday, group, only)
    try:
        name, argv = task_argv(task, paths, asof, pick, nums, payday, group, only, year)
    except ValueError as e:
        say(str(e))
        return 2, []
    if task in ("승인검토", "인트라넷") and collect:
        argv += ["--수집", "함"]
    if task == "변환":
        import_auto(paths, say)
        backup_input(paths, say)
    started = time.time() - 1
    out = _Lines(say)
    mod = _module(name)
    old_cred = getattr(mod, "CREDENTIALS", None)
    try:
        if name == "승인검토":
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
        if name == "승인검토":
            mod.CREDENTIALS = old_cred
    if task == "변환" and rc == 0:
        build_live(paths, say, asof)
    return rc, new_files(paths.output, started)


def build_live(paths, say, asof=""):
    """변환 뒤 지금 현황 화면을 새로 쓴다 (사용자 2026-11-12). 실패해도 변환 결과는 그대로 (글로만 알림). -> 경로 또는 None."""
    from . import live
    try:
        path, diff = live.build(paths.input, paths.output, parse_date(asof) if asof else None)
    except Exception as e:   # 현황 화면 때문에 변환을 실패로 만들지 않는다
        why = "%s: %s" % (type(e).__name__, str(e)[:150])
        # 1차 E11 (2026-11-15): 예전엔 실패해도 다시 만들지 않은 예전 화면이 그대로 열렸다 — 예전 화면은 옮기고 '못 만듦' 안내로 바꾼다
        live.mark_failed(paths.output, why)
        say("[확인] 지금 현황 화면을 새로 만들지 못함 (%s) — 예전 현황 화면은 '%s'로 옮김(최신 자료 아님). "
            "자료 변환은 끝났으니 숫자는 보고서에서 확인하세요" % (why, live.STALE_FILE))
        return None
    say("지금 현황 화면 새로 씀 (%s) · 지난 현황 뒤 바뀐 것 %d건" % (os.path.basename(path), len(diff)))
    for name, a, b in diff[:8]:
        say("  %s: %s → %s" % (name, "–" if a is None else "{:,}".format(a), "–" if b is None else "{:,}".format(b)))
    return path


AUTO_KINDS = ("분개장", "자금계획서")   # 이 자료가 새로 들어오면 자동으로 변환·보고 (사용자 2026-11-12)
AUTO_SETTLE_SEC = 20                    # 파일을 다 쓴 뒤 이만큼 지나야 읽는다 (쓰는 중인 파일을 읽지 않게)
AUTO_QUIET_SEC = 90                     # 2차 C13: 마지막으로 어떤 위하고 자료든 들어온 뒤 이만큼 조용해야 자동으로 돈다


def pending_downloads(dirs=None):
    """크롬 다운로드 폴더(위하고자동수집)에 아직 가져오지 않은 자동수집 파일 -> [(경로, 받은 시각)].
    2차 P1-11·P5-13·P6-9 (2026-11-15): 예전엔 수집\위하고 만 봐서, 확장이 다운로드 폴더에 받은 새 자료를 자동 실행·새 자료 목록이 놓쳤다."""
    out = []
    for base in (chrome_download_dirs() if dirs is None else dirs):
        folder = os.path.join(base, AUTO_DIR)
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for n in names:
            if not n.endswith(AUTO_SUFFIX):
                continue
            try:
                out.append((os.path.join(folder, n), dt.datetime.fromtimestamp(os.path.getmtime(os.path.join(folder, n)))))
            except OSError:
                continue
    return out


MARK_FILE = "받기상태.txt"     # 위하고 확장 '모두 받기'가 시작·끝에 남기는 표시 (편의성 27, 2026-11-16). 자료가 아니다
MARK_FRESH_SEC = 20 * 60       # '받는 중' 표시를 이만큼만 믿는다 (크롬이 꺼져 표시가 남아도 영영 멈추지 않게)
MARK_SLACK_SEC = 5             # '끝' 표시와 마지막 파일의 시각 차이 허용


def collect_mark(paths, dirs=None):
    """확장이 남긴 받기 표시 중 가장 새것 -> {'state': '받는 중'|'끝', 'at': 시각, 'fail': 못 받은 수} 또는 None.
    저장 폴더(수집\\위하고)와 크롬 다운로드 폴더의 위하고자동수집 둘 다 본다. 시각은 파일을 쓴 때."""
    import json
    best = None
    folders = [paths.wehago] + [os.path.join(b, AUTO_DIR) for b in (chrome_download_dirs() if dirs is None else dirs)]
    for folder in folders:
        p = os.path.join(folder, MARK_FILE)
        try:
            at = dt.datetime.fromtimestamp(os.path.getmtime(p))
            with open(p, encoding="utf-8-sig") as f:
                d = json.load(f)
            state = str(d.get("상태") or "")
        except (OSError, ValueError, AttributeError):
            continue
        if state in ("받는 중", "끝") and (best is None or at > best["at"]):
            try:
                fail = int(d.get("못받음") or 0)
            except (TypeError, ValueError):
                fail = 0
            best = {"state": state, "at": at, "fail": fail, "error": str(d.get("오류") or "").strip()}
    return best


WEHAGO_TRIGGER = "https://smarta.wehago.com/ceo-report-collect"   # 확장 0.9.7 이 이 주소가 열리면 탭을 닫고 '모두 받기' (background.js TRIGGER)


def find_chrome(env=None, exists=os.path.exists, which=shutil.which):
    """크롬 경로 또는 None. 위하고 확장은 크롬에만 깔려 있어 엣지는 찾지 않는다."""
    env = os.environ if env is None else env
    cands = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
             r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]
    for base in (env.get("LOCALAPPDATA"), env.get("ProgramFiles"), env.get("ProgramFiles(x86)"), env.get("ProgramW6432")):
        if base:
            cands.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    for p in cands:
        if exists(p):
            return p
    for name in ("chrome", "google-chrome"):
        p = which(name)
        if p:
            return p
    return None


def start_wehago_collect(chrome=None, popen=None):
    """'위하고에서 받기' 단추 (사용자 2026-11-17 결정 카드 A): 크롬에 표시 주소를 열어 확장이 '모두 받기'를 하게 한다.
    프로그램은 위하고에 직접 접속하지 않는다. 받은 파일·받기상태.txt 는 지금처럼 자동 반영이 읽는다. -> (성공 여부, 글)."""
    import subprocess
    chrome = chrome or find_chrome()
    if not chrome:
        return False, "크롬을 찾지 못함 — 크롬에서 위하고 확장의 '모두 받기'를 직접 누르세요"
    try:
        (popen or subprocess.Popen)([chrome, WEHAGO_TRIGGER])
    except OSError as e:
        return False, "크롬을 열지 못함 (%s) — 크롬에서 위하고 확장의 '모두 받기'를 직접 누르세요" % (e.strerror or type(e).__name__)
    return True, ("크롬에 받기 요청을 보냄 — 분개장·대조·자금계획에 이어 결산·인사급여·연말정산까지 받으며 위하고 화면이 앞에 떴다 닫힙니다(3~5분, 그동안 다른 탭으로 옮기지 마세요). 다 받으면 자동 반영이 이어갑니다. "
                  "위하고에 로그인돼 있지 않으면 크롬에 위하고가 열립니다: 로그인해 회사 [회계]를 연 뒤 다시 누르세요. "
                  "10분이 지나도 그대로면 크롬 오른쪽 위 확장 그림을 눌러 '저장 허용' 단추가 있는지 보세요")


def auto_state(paths, now=None, dirs=None):
    """자동 반영이 지금 무엇을 기다리는지 -> {'state': none|collecting|wait|ready, 'sig': 표시 또는 None, 'text': 창에 보일 글}.

    마지막 변환 뒤 받은 것만 보고, 받은 지 AUTO_SETTLE_SEC 초가 안 됐으면 아직 기다린다.
    2차 C13 (2026-11-15): '모두 받기'는 분개장을 먼저, 자금계획서를 나중에 받는다. 예전엔 분개장만 들어온 20초 뒤에 자동 보고가
    끼어들어 새 분개장 + 옛 자금계획서로 PDF 가 먼저 나왔다 → 수집\위하고·다운로드 폴더 어디든 마지막 자료가 들어온 뒤
    AUTO_QUIET_SEC 초 동안 새 파일이 없을 때만 돈다. 다운로드 폴더에 받아만 둔 분개장·자금계획서도 새 자료로 본다 (P1-11).
    편의성 27 (2026-11-16): 받기 중간에 90초 넘게 멈추면(저장 허용 대기 등) 그 규칙으로도 반쪽 자료로 PDF 가 먼저 나올 수 있다
    → 확장이 '받는 중'이라고 적어 둔 동안(20분까지)은 기다리고, '끝' 표시가 마지막 파일 뒤에 있으면 90초를 기다리지 않는다.
    표시가 없거나 지난번 것이면(분개장만 따로 받기·예전 확장) 지금처럼 90초 조용할 때."""
    from . import winstate
    now = now or dt.datetime.now()
    src = dict((n, w) for n, w, _ in winstate.sources(paths) if n in AUTO_KINDS)
    conv = winstate.convert_time(paths.input)
    new = dict((n, w) for n, w in src.items() if isinstance(w, dt.datetime) and (conv is None or w > conv))
    pend = pending_downloads(dirs)
    for p, w in pend:
        kind = "분개장" if "분개장" in os.path.basename(p) else ("자금계획서" if "자금계획" in os.path.basename(p) else None)
        if kind and (conv is None or w > conv):
            k = "%s(다운로드 폴더)" % kind
            new[k] = max(new.get(k, w), w)
    mark = collect_mark(paths, dirs)
    collecting = bool(mark and mark["state"] == "받는 중" and 0 <= (now - mark["at"]).total_seconds() < MARK_FRESH_SEC)
    if collecting:
        return {"state": "collecting", "sig": None,
                "text": "위하고 확장이 받는 중 (%s 시작) — 다 받으면 반영" % mark["at"].strftime("%H:%M")}
    if not new:
        # 2026-11-17: '위하고에서 받기'로 시작했는데 못 받았으면 그 까닭을 보인다 (20분까지)
        if mark and mark["state"] == "끝" and mark.get("error") and 0 <= (now - mark["at"]).total_seconds() < MARK_FRESH_SEC:
            return {"state": "none", "sig": None, "fail": True, "text": "새 자료 없음 · 위하고 받기 못 함 (%s) — %s"
                    % (mark["at"].strftime("%H:%M"), mark["error"])}
        return {"state": "none", "sig": None, "text": "새 자료 없음"}
    latest = [w for w in new.values()] + [w for _, w in pend]
    other = winstate.other_wehago_time(paths)
    if other:
        latest.append(other)
    last = max(latest)
    ended = bool(mark and mark["state"] == "끝" and (mark["at"] - last).total_seconds() >= -MARK_SLACK_SEC)
    settle = AUTO_SETTLE_SEC - min((now - w).total_seconds() for w in new.values())
    quiet = 0 if ended else AUTO_QUIET_SEC - (now - last).total_seconds()
    left = max(settle, quiet)
    if left > 0:
        return {"state": "wait", "sig": None,
                "text": "새 자료 받음 — %s %d초 기다림" % ("파일을 다 쓰는지" if ended else "다른 자료가 더 오는지", int(left) + 1)}
    sig = "|".join("%s %s" % (n, w.strftime("%Y-%m-%d %H:%M:%S")) for n, w in sorted(new.items()))
    return {"state": "ready", "sig": sig, "text": "새 자료 받음 — 반영 시작"}


def auto_signature(paths, now=None, dirs=None):
    """새 분개장·자금계획서가 들어와 자동으로 돌릴 차례면 그 자료의 표시(받은 시각 글자), 아니면 None. (판단은 auto_state)"""
    return auto_state(paths, now, dirs)["sig"]


def run_auto(paths, say, asof="", pick="", payday="", group="", only=""):
    """새 자료 → 변환 → 지금 현황 → 주간·월간 보고 PDF (사용자 2026-11-12 'PDF까지 자동'). -> (종료코드, 새 출력 파일).

    변환이 실패하면 보고는 만들지 않는다. 보고 하나가 실패해도 다른 보고는 만든다 (가장 나쁜 종료코드를 돌려줌)."""
    say("새 자료가 들어와 자동으로 변환하고 보고를 다시 만듭니다")
    rc, files = run_task("변환", paths, say, asof=asof)
    if rc != 0:
        say("변환이 끝나지 않아 보고는 만들지 않았습니다")
        return rc, files
    worst = 0
    for kind in ("주간", "월간"):
        say("──── 자동: %s 보고 ────" % kind)
        r, f = run_task(kind, paths, say, asof=asof, pick=pick, payday=payday, group=group, only=only)
        files += f
        if r != 0:
            say("%s 보고를 만들지 못함 (코드 %s)" % (kind, r))
            worst = worst or r
    return worst, list(dict.fromkeys(files))


def headless(paths, log_path, asof="", today=None):
    """창 없이 '자동'(변환 → 지금 현황 → 주간·월간 보고)을 한 번 돌리고 글을 log_path 에 남긴다. -> 종료코드.

    2026-11-14 밤 통합: 사용자가 자는 동안 새 exe 로 실제 자료 보고를 만들어 보려고 (대표보고.exe --자동 결과.txt [기준일]).
    창에서 '자동'을 누른 것과 같게: 기준일은 비우면 오늘, 출금일·가용자금 날짜·출금 목록 합침은 창을 열 때 칸 값 그대로."""
    from . import winstate
    from .version import build
    lines = ["판: %s" % build()]
    # 2차 P5-24·P6-15 (2026-11-15): 지난번 결과 파일이 이번 결과처럼 남지 않게 먼저 '돌고 있음'으로 바꾸고, 준비 단계 오류도 결과에 남긴다
    try:
        _write_log(log_path, lines + ["돌고 있음 (이 줄이 남아 있으면 끝나지 못한 것)"], "진행 중")
    except OSError:
        pass
    day, rc = None, 7
    try:
        day = parse_date(asof) if asof else (today or dt.date.today())
        if day is None:   # 창에서처럼 날짜 오류(2)로 끝낸다
            lines.append("기준일 형식 오류: %s (예: 2026-11-13)" % asof)
            rc = 2
            raise _Stop()
        vals = winstate.start_values(paths.input, day)
        group, only = load_merge(paths)
        rc, files = run_auto(paths, lines.append, asof=asof or day.isoformat(), pick=vals["pick"], payday=vals["payday"],
                             group=group, only=only)
        if files:
            lines.append("만든 파일: %s" % ", ".join(os.path.basename(f) for f in files))
        stops = winstate.blocked_reports(files)
        if stops:   # 2차 C12 (2026-11-15): 막혀도 '자동 완료'처럼 보였다 → 결과 글에 남긴다
            lines.append("대표 보고: 자료 확인에서 막혀 만들지 않음 (%s)" % ", ".join(os.path.basename(f) for f in stops))
    except _Stop:
        pass
    except Exception as e:   # 트레이스백 대신 한 줄
        lines.append("예상하지 못한 오류 (%s): %s" % (type(e).__name__, str(e)[:200]))
        rc = 7
    if day:   # 창도 날짜가 틀리면 돌리지 않아 기록을 남기지 않는다
        try:
            winstate.remember_run(paths.input, "자동", rc == 0)
        except OSError:
            lines.append("창 상태(마지막 자동 실행)를 남기지 못함")
    try:
        _write_log(log_path, lines, rc)
    except OSError as e:   # 결과 파일을 못 쓰면 표준 출력으로라도 (원격 실행이 받아 봄)
        print("\n".join(lines + ["결과 파일을 쓰지 못함 (%s): %s" % (type(e).__name__, log_path), "rc=%s" % rc]))
        return rc or 7
    return rc


class _Stop(Exception):
    """headless 를 더 돌리지 않고 결과만 남긴다."""


def _write_log(log_path, lines, rc):
    tmp = log_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\nrc=%s\n" % rc)
    os.replace(tmp, log_path)


CHECK_ASOF = "2026-10-31"   # 점검 기준일 (샘플 자료일)
# 주간 다음에 한 번씩 만들어 보는 보고 (P22): (작업, 꼭 생겨야 하는 파일 이름 끝). 못 만들면 종료 코드 11~14
CHECK_MORE = (("월간", "_월간_대표보고.html"), ("연간", "_연간_대표보고.html"), ("예산", "_예산_대표용.html"), ("기획본부", ".xlsx"))


def _check_plan(input_dir, stamp):
    """점검용 자금계획.csv: 샘플에는 자금계획서가 없어 자료 확인(게이트)이 대표 보고를 막는다 (2026-11-15 빌드 점검 rc=10).
    점검은 대표 보고가 끝까지 만들어지는지만 보므로, 보고 기간 달(11·12월)에 작은 지급 예정 한 줄씩만 넣는다."""
    rows = [("2026-11-06", 1000000), ("2026-12-04", 1000000)]
    with open(os.path.join(input_dir, "자금계획.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(fundplan.COLUMNS)
        for due, amount in rows:
            w.writerow([due, "지급", "미지급금 지급", "점검용 지급처", "", amount, due[:7], stamp, "점검", "예정", "", "", ""])


def self_check(log_path, base=None):
    """exe 점검: 창 없이 샘플로 주간·월간·연간·예산 보고를 한 번씩 만들고 기획본부도 돌려 본다 (빌드 확인용). 0 이면 정상.
    gui 에서 옮김 (2026-11-15, tkinter 없이 시험하려고). base = 입력양식 이 있는 곳 (exe 는 풀린 임시 폴더)."""
    import tempfile
    from . import winstate
    base = base or getattr(sys, "_MEIPASS", program_dir())
    sample = os.path.join(base, "입력양식", "샘플")
    tmp = tempfile.mkdtemp()
    from .version import build
    lines = ["판: %s" % build()]
    try:
        shutil.copytree(sample, os.path.join(tmp, "입력"))
        os.makedirs(os.path.join(tmp, "수집", "위하고"))
        _check_plan(os.path.join(tmp, "입력"), CHECK_ASOF)
        P = Paths(tmp)
        rc, files = run_task("주간", P, lines.append, asof=CHECK_ASOF)
        lines.append("파일: %s" % ", ".join(os.path.basename(f) for f in files))
        if rc == 0 and not any(f.endswith("_주간_대표보고.html") for f in files):
            rc = 9
        # '만들지 않음' 안내만 나왔으면 실패 (코덱스 검토 2026-11-14)
        if rc == 0 and any(f.endswith("_주간_대표보고.html") and winstate._is_stop_page(f) for f in files):
            lines.append("대표 보고가 '만들지 않음' 안내로 나옴 — 자료 확인에서 막힘")
            rc = 10
        # 2차 P6-13 (2026-11-15): PDF 를 못 만들어도 점검이 통과로만 끝났다 — 결과에 한 줄 남긴다 (CI 처럼 화면 없는 곳에선 못 만들 수 있어 실패로는 보지 않음)
        pdfs = [os.path.basename(f) for f in files if f.lower().endswith(".pdf")]
        lines.append("PDF: %s" % (", ".join(pdfs) if pdfs else "못 만듦 (보고 HTML 은 있음 — 이 PC 에서 PDF 만들기를 확인하세요)"))
        # 2차 전수조사 P22 (2026-11-18): 예전엔 주간만 만들어 봐서 월간·연간·예산·기획본부가 깨져도 설치 점검은 통과했다
        for n, (task, tail) in enumerate(CHECK_MORE):
            if rc:
                break
            say = []
            rc2, more = run_task(task, P, say.append, asof=CHECK_ASOF, year=CHECK_ASOF[:4] if task == "연간" else "")
            made = [f for f in more if f.endswith(tail)]
            if task == "기획본부" and rc2 == 2 and not made:
                # 예시 자료에는 장부(계정잔액.csv)가 없어 엑셀까지는 못 만든다 — 프로그램이 돌아 자료 확인까지 간 것만 본다
                lines.append("기획본부: 예시 자료에 장부가 없어 엑셀은 건너뜀 (실행만 확인) — %s" % (say[-1] if say else ""))
                continue
            if rc2 or not made:
                lines.extend(say[-8:])
                lines.append("%s 보고를 만들지 못함 (코드 %s)" % (task, rc2))
                rc = 11 + n
            elif tail.endswith(".html") and winstate._is_stop_page(made[0]):
                lines.append("%s 대표 보고가 '만들지 않음' 안내로 나옴 — 자료 확인에서 막힘" % task)
                rc = 11 + n
            else:
                lines.append("%s: %s" % (task, os.path.basename(made[0])))
    except Exception as e:
        lines.append("점검 오류 (%s): %s" % (type(e).__name__, e))
        rc = 8
    finally:
        shutil.rmtree(tmp, True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\nrc=%s\n" % rc)
    return rc


MERGE_FILE = "출금목록_합칠거래처.txt"   # 창의 '합칠 거래처' 칸 값 (다음에 열 때 그대로, 사용자 2026-11-05)


MERGE_MODES = ("건별", "거래처별", "고른곳만")   # 건마다 한 줄 / 모두 합침 / 고른 곳만 합침 (편의성 9, 2026-11-16)


def merge_args(group, only):
    """창의 출금 목록 설정 -> 보고서에 넘길 (--출금목록, --합칠거래처).
    예전엔 '거래처별'에 고른 곳이 0곳이면 '모두 합침'으로 읽어, 합칠 거래처 창에서 '모두 해제 → 확인'하면 전부 합쳐졌다.
    이제 '고른 곳만 합침'에 0곳이면 합치지 않는다 (건별), '모두 합침'은 고른 목록을 쓰지 않는다."""
    only = (only or "").strip()
    if group == "거래처별":
        return "거래처별", ""
    if group == "고른곳만" and only:
        return "거래처별", only
    return "건별", ""


def load_merge(paths):
    try:
        with _open_text(os.path.join(paths.input, MERGE_FILE)) as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return "건별", ""
    group = lines[0].strip() if lines and lines[0].strip() in MERGE_MODES else "건별"
    only = lines[1].strip() if len(lines) > 1 else ""
    if group == "거래처별" and only and (len(lines) < 3 or lines[2].strip() != "v2"):
        group = "고른곳만"   # 예전 판이 저장한 파일: 거래처별 + 고른 곳 = 그 곳만 합침 (뜻을 그대로)
    return group, only


def save_merge(paths, group, only):
    try:
        with open(os.path.join(paths.input, MERGE_FILE), "w", encoding="utf-8") as f:
            f.write("%s\n%s\nv2\n" % (group, only))
    except OSError:
        pass


def new_files(folder, since, depth=1):
    """since 뒤에 바뀐 파일. 1차 E10 (2026-11-15): 예산(출력/예산)·팀장(출력/팀장용) 보고는 한 단계 아래 폴더에 있어
    예전엔 찾지 못한 채 '대표용 PDF를 열었습니다'라고 했다 → 한 단계 아래 폴더까지 본다."""
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    for n in names:
        p = os.path.join(folder, n)
        try:
            if os.path.isfile(p) and os.path.getmtime(p) >= since:
                out.append(p)
            elif depth > 0 and os.path.isdir(p):
                out += new_files(p, since, depth - 1)
        except OSError:
            continue
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


def add_schedule(input_dir, day, io_kind, amount, firm, vendor, cat="", basis="", memo="", project="", vendor_code=""):
    """입력/자금일정.csv 에 한 줄을 더한다. 잘못된 값은 ValueError (글은 그대로 화면에 보인다). -> 더한 줄 dict.

    vendor_code (2026-11-14 사용자 "이름 말고 코드로"): 창에서 위하고 거래처를 고르면 그 거래처코드. 자금계획서·장부와 코드로 맞춘다.
    옛 파일에 거래처코드 칸이 없으면 머리글 끝에 칸을 더한다 (앞 줄은 빈칸 = 코드 없음, 이름으로 맞춤)."""
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
    from .data import SCHED_OPTIONAL
    header = SCHEMA[SCHED_FILE] + SCHED_OPTIONAL
    row = {"거래처코드": str(vendor_code or "").strip(), "예정일": d.isoformat(), "입출금": io_kind, "금액": "{:,}".format(int(text)), "확정여부": firm,
           "분류": cat.strip() or ("기타지급" if io_kind == "지급" else "기타입금"), "프로젝트번호": project.strip(),
           "거래처": vendor.strip(), "근거": basis.strip() or "직접 입력", "비고": memo.strip()}
    path = os.path.join(input_dir, SCHED_FILE)
    if not os.path.isdir(input_dir):
        raise ValueError("입력 폴더가 없습니다: %s" % input_dir)
    empty = False
    if os.path.exists(path):
        enc, raw = _encoding(path)
        empty = not raw.decode(enc).strip()   # 2차 P5-19 (2026-11-15): 빈 파일에 머리글 없이 더해 다음에 0줄로 읽혔다 → 새 파일처럼 씀
    if os.path.exists(path) and not empty:
        text_now = raw.decode(enc)
        first = next(csv.reader([text_now.splitlines()[0]])) if text_now.strip() else []
        cols = [c.strip() for c in first] or header
        if not set(["예정일", "입출금", "금액"]) <= set(cols):
            raise ValueError("자금일정.csv 머리글이 양식과 다릅니다 — 파일을 확인하세요")
        lack = [c for c in ("확정여부", "거래처") if c not in cols]
        if lack:   # 옛 파일에 넣으면 '확정'이 사라져 예상으로 읽힌다 (코덱스 검토 2026-11-14)
            raise ValueError("자금일정.csv 머리글에 %s 칸이 없어 넣지 않았습니다 — 첫 줄을 양식(%s)대로 맞추세요"
                             % ("·".join("'%s'" % c for c in lack), ",".join(header)))
        nl = "\r\n" if "\r\n" in text_now else "\n"
        if row["거래처코드"] and "거래처코드" not in cols:   # 옛 파일: 머리글 끝에 칸을 더해 다시 쓴다 (앞 줄은 빈칸)
            lines = text_now.splitlines()
            lines[0] = lines[0] + ",거래처코드"
            text_now = nl.join(lines) + nl
            cols = cols + ["거래처코드"]
            # 2차 전수조사 P5 (2026-11-18): 바로 덮어쓰다 끊기면 일정이 반만 남음 → 임시 파일에 다 쓴 뒤 바꾼다
            with open(path + ".tmp", "wb") as f:
                f.write(text_now.encode("utf-8-sig" if enc == "utf-8-sig" else enc))
            os.replace(path + ".tmp", path)
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
    자금계획서: 같은 달을 더 새 파일이 맡아 쓰이지 않는 파일만 옮긴다. 읽지 못한 파일은 옮기지 않는다 (확인하도록).

    2차 P1-12·P2-16 (2026-11-15): ① 변환이 읽지 않는 모양(PDF 등)이 '가장 새 파일'로 잡혀 멀쩡한 장부를 옮겼다 → 변환과 같은
    확장자 규칙으로만 고른다. ② 가장 새 장부가 깨졌으면 그 종류는 아무것도 옮기지 않는다 (예전엔 깨진 것만 남기고 멀쩡한 것을 옮겼음).
    ③ 지난달만 맡은 자금계획서도 변환이 '예정일 지남'(아직 안 나간 지급)을 찾는 데 쓰므로 옮기지 않는다 (예전엔 옮겨 그 줄이 사라졌음)."""
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
        ext = os.path.splitext(n)[1].lower()
        if not (ext == ".xlsx" or (ext in (".xls", ".json") and kind == "분개장")):   # 변환(wehago.load)이 읽는 모양만 (①)
            continue
        groups.setdefault(kind, []).append(n)
    for kind, files in groups.items():
        ranked = sorted(files, key=lambda n: (wehago._rank_date(n) or dt.date.min, wehago._mtime(os.path.join(wehago_dir, n)), n))
        newest = ranked[-1]
        try:   # ② 가장 새 파일을 변환처럼 읽어 본다 — 못 읽으면 이 종류는 그대로 둔다
            wehago.read_book(os.path.join(wehago_dir, newest), kind, wehago._file_date(newest), None)
        except Exception:
            continue
        top = (wehago._rank_date(newest) or dt.date.min).year
        keep_year = {}
        for n in ranked:
            y = (wehago._rank_date(n) or dt.date.min).year
            if y < top:
                keep_year[y] = n   # 지난해 장부: 그 해 가장 새 파일
        keep = set([newest] + list(keep_year.values()))
        if kind == "분개장":   # 부분 기간만 새로 받은 분개장이면 함께 쓰는 이전 파일도 남긴다 (2026-11-05)
            keep.update(wehago.journal_layers(wehago_dir, ranked))
        for n in ranked:
            if n not in keep:
                out.append((n, "%s 더 새 파일이 있음" % kind))
    res = fundplan.load(wehago_dir)
    month_names = set(name for _, name, _ in res["months"])   # ③ 어느 달이든 맡은 파일은 쓰인다 (지난달 '예정일 지남' 포함)
    for n in res["unused"]:
        if n in month_names:
            continue
        note = " ".join(x for x in res["notes"] if x.startswith(n))
        if "더 새 파일 있음" not in note:
            continue   # 읽지 못한 파일은 사람이 확인하도록 그대로 둔다
        out.append((n, "자금계획서 같은 달 더 새 파일이 있음"))
    return list(dict.fromkeys(out))   # 같은 파일을 두 번 옮기려 하지 않게


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


# ───────────── 카드별 납부일·기산일 ─────────────
def save_card(input_dir, company, pay_day, start_day=1):
    """입력/카드결제일.csv 에 카드사 한 줄을 넣거나 고친다 (사용자 2026-11-03). -> [(카드사, 납부일, 기산일)] 전체.

    납부일 = 카드대금이 통장에서 나가는 날, 기산일 = 이용기간 시작일. 다음 '자료 변환'부터 카드대금 예상에 쓰인다."""
    from . import tax
    co = tax._card_name(company)
    if not co:
        raise ValueError("카드사를 넣으세요 (예: 신한)")
    days = []
    for label, v in (("납부일", pay_day), ("기산일", start_day)):
        t = str(v if v not in (None, "") else ("1" if label == "기산일" else "")).strip().rstrip("일")
        if not t.isdigit() or not 1 <= int(t) <= 31:
            raise ValueError("%s은 1~31 사이 숫자 (예: 15)" % label)
        days.append(int(t))
    if not os.path.isdir(input_dir):
        raise ValueError("입력 폴더가 없습니다: %s" % input_dir)
    current, notes = tax.read_card_days(input_dir)
    if notes and os.path.exists(os.path.join(input_dir, tax.CARD_FILE)) and not current:
        raise ValueError("%s 머리글이 양식과 다릅니다 — 파일을 확인하세요" % tax.CARD_FILE)
    # 2차 P2-9·P5-18·P6-2 (2026-11-15): 날짜를 못 읽은 다른 카드 줄이 저장 때 조용히 사라졌다 → 먼저 고치게 하고 저장하지 않음
    bad = [n for n in notes if "줄 날짜를 읽지 못함" in n and (" %s 줄" % co) not in n]
    if bad:
        raise ValueError("%s 에 날짜를 못 읽은 다른 카드 줄이 있어 저장하면 그 줄이 사라집니다 — 그 줄부터 고치세요: %s"
                         % (tax.CARD_FILE, "; ".join(bad)))
    current[co] = tuple(days)
    rows = sorted((c, p, s) for c, (p, s) in current.items())
    path = os.path.join(input_dir, tax.CARD_FILE)
    with open(path + ".tmp", "w", encoding="utf-8-sig", newline="") as f:   # 쓰다 실패해도 원래 파일은 그대로 (머리글만 남지 않게)
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(tax.CARD_COLUMNS)
        for r in rows:
            w.writerow(r)
    os.replace(path + ".tmp", path)
    return rows


def save_pay_detail(input_dir, vendor, amount, text):
    """금요일 출금 목록 상세 내역 한 줄 저장 (사용자 2026-11-03). 같은 거래처·금액 지급 줄에 붙는다. 내용을 비우면 지운다."""
    from . import paydetail
    return paydetail.save(input_dir, vendor, amount, text)


def save_team_target(input_dir, year, team, revenue, rate):
    """팀 연간 매출 목표·목표 수익률 저장 (사용자 2026-11-03). 월간 누적 실적의 목표 대비에 쓰인다."""
    from . import targets
    return targets.save(input_dir, year, team, revenue, rate)


def save_depreciation(input_dir, year, amount):
    """법인세 예상에 쓸 연간 감가상각비 저장 (사용자 2026-11-04). 비우면 작년 장부 값을 씀."""
    from . import corptax
    return corptax.save(input_dir, year, amount)


def save_holder(input_dir, name, share, minor, salaried, interest, other, delete=False, dependents=""):
    """주주 저장·지우기 (사용자 2026-11-12: 배당 권장). -> (동작, 주주 수, 지분율 합)."""
    from . import dividend
    return dividend.save(input_dir, name, share, minor, salaried, interest, other, delete, dependents)


def question_text(input_dir):
    """배당 판단 질문 상태 한 줄: 꼭 넣을 값 중 비어 있는 것."""
    from . import dividend
    try:
        CL = dividend.checklist(input_dir)
    except Exception:
        return ""
    tax = set(k for k, g in dividend.GROUP_OF.items() if g == dividend.TAX_GROUP)   # 감면·공제는 창 '법인세 감면·공제'에서 (2026-11-17)
    miss = [k for k, q, v, need, u in CL if need and u is None and k not in tax]
    done = sum(1 for k, q, v, need, u in CL if v and k != "주주" and k not in tax)
    return ("★ 꼭 넣을 값 %d개 비어 있음 — 질문 창에서 넣어야 배당 판단을 합니다" % len(miss)) if miss else "판단할 준비 됨 (질문 %d개 답함)" % done


def holder_settings(input_dir):
    from . import dividend
    try:
        return dividend.read_settings(input_dir)
    except Exception:
        return {}


def save_holder_settings(input_dir, values, group=None, exclude=None):
    """창에서 저장: 꼭 넣을 값이 비면 저장하지 않는다 (사용자 2026-11-12). group/exclude = 그 창이 맡은 묶음만 막음."""
    from . import dividend
    return dividend.save_settings(input_dir, values, strict=True, group=group, exclude=exclude)


def taxbreak_text(input_dir):
    """창 '법인세 감면·공제' 상태 (사용자 2026-11-17: 공제·감면 '받음' 체크를 목록에 따로) -> 여러 줄 글."""
    from . import dividend, taxbreak
    try:
        a = dividend.read_settings(input_dir)
        rows = taxbreak.pick_states(a)
        miss = dividend.missing_required(a, group=dividend.TAX_GROUP)
    except Exception:
        return ""
    on = [n for n, ok, _ in rows if ok]
    off = [n for n, ok, _ in rows if not ok]
    out = ["법인세 예상에 넣는 것 %d개: %s" % (len(on), " · ".join(on) if on else "없음"),
           "안 넣는 것 %d개: %s" % (len(off), " · ".join(off) if off else "없음")]
    if miss:
        out.append("★ 꼭 넣을 값 %d개 비어 있음 — 감면 후보를 판단하지 못합니다" % len(miss))
    return "\n".join(out)


def taxbreak_count(input_dir):
    """목록 옆 짧은 글: '넣는 것 n개'."""
    from . import dividend, taxbreak
    try:
        rows = taxbreak.pick_states(dividend.read_settings(input_dir))
    except Exception:
        return ""
    return "넣는 것 %d개" % sum(1 for _, ok, _ in rows if ok)


def holder_text(input_dir):
    from . import dividend
    try:
        return dividend.text(input_dir)
    except Exception:   # 창이 멈추지 않게
        return ""


def save_budget_values(input_dir, year, items):
    """내년 예산 값 저장 (사용자 2026-11-10). items = [(구분, 대상, 값)]."""
    from . import budget
    return budget.save_values(input_dir, year, items)


def budget_text(input_dir, year):
    from . import budget
    try:
        return budget.values_text(input_dir, year)
    except Exception:   # 창이 멈추지 않게
        return ""


def card_list(input_dir):
    """창에 보일 글: '신한 15일(기산 1일) · 롯데 …'."""
    from . import tax
    current, _ = tax.read_card_days(input_dir)
    return " · ".join("%s %d일(기산 %d일)" % (c, p, s) for c, (p, s) in sorted(current.items())) or "없음"


def law_text(input_dir, year):
    """세법·노동법 기준표 상태 한 줄 (창 '세법 기준 확인' 옆)."""
    from . import taxlaw
    try:
        T = taxlaw.status(input_dir, year)
    except Exception:
        return ""
    if not T["todo"]:
        return "%d년 기준 모두 확인됨" % year
    return "%d년 기준 %d개 미확인 — 확인 전에는 그 계산을 합계에 넣지 않습니다" % (year, len(T["todo"]))


def law_check(input_dir, year):
    """법령 조문 받아 개정 확인 -> 결과 글 줄들 (네트워크: 창에서 따로 돌림)."""
    from . import lawwatch
    rows = lawwatch.check(input_dir, year)
    bad = [r for r in rows if r[2] in ("개정됨", "못 찾음", "실패") or "안 보임" in r[4]]
    got = [r for r in rows if r[2] not in ("못 찾음", "실패")]
    if not got:   # R11 (2026-11-15): 모두 실패해도 'N개 받음'으로 보였음 — 받은 수 그대로, 못 받으면 '못 받음'
        why = next((r[4] for r in rows if r[4]), "")
        head = ("법령 조문을 하나도 받지 못함 (%d개 모두 실패) — 인터넷 연결과 아이디(OC)를 확인하고 다시 받아 주세요%s"
                % (len(rows), (". 이유: " + why[:120]) if why else ""))
    else:
        head = "법령 조문 %d개 중 %d개 받음 — 다시 볼 것 %d개" % (len(rows), len(got), len(bad))
    return [head] + ["%s: %s%s · %s" % (tag, st, (" (시행 %s)" % eff) if eff else "", note) for _, tag, st, eff, note in rows]
