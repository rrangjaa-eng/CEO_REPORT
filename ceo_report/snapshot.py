"""인트라넷 수집 스냅숏의 디스크 형식.

회사 자료이므로 저장소에 올리지 않는다; 값은 화면 글자 그대로 둔다 (해석은 approval.py가 한다).

폴더: <root>/인트라넷_YYYYMMDD_HHMMSS/
    지급요청.csv   수집시각 + PAYMENT_COLUMNS
    프로젝트목록.csv 수집시각 + PROJECT_COLUMNS
    수집정보.csv   항목,값 (형식, 수집시각, 건수, 페이지 수)
모두 UTF-8(BOM), 한 번에 완성된 폴더만 보이도록 '.작성중' 폴더에 쓰고 이름을 바꾼다.
"""
import csv
import datetime as dt
import os
import re
import shutil

from .util import Issues, read_csv

PAYMENT_COLUMNS = ["번호", "행사명", "파트너", "등록일", "행사일", "금액", "지급요청일", "등록자",
                   "팀장승인", "관리팀승인", "사장님승인"]
PROJECT_COLUMNS = ["번호", "클라이언트", "담당자", "PO번호", "행사일", "행사명", "국", "팀", "등록자", "계산서",
                   "사전견적", "견적금액", "실행가", "수익률", "승인_담당자", "승인_팀장", "승인_관리팀", "승인_대표이사",
                   "pro_num"]
FORMAT = "1"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_FOLDER_RE = re.compile(r"^인트라넷_\d{8}_\d{6}$")
PAYMENT_FILE, PROJECT_FILE, INFO_FILE = "지급요청.csv", "프로젝트목록.csv", "수집정보.csv"


class SnapshotError(Exception):
    """스냅숏을 쓰거나 읽을 수 없다. 틀린 값을 조용히 만들지 않고 멈춘다."""


class Snapshot:
    def __init__(self, path, collected_at, payments, projects, info):
        self.path, self.collected_at = path, collected_at
        self.payments, self.projects, self.info = payments, projects, info


def _write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def _page_counts(pages):
    if pages is None:
        return "", ""
    if isinstance(pages, dict):
        return str(pages.get("지급요청", "")), str(pages.get("프로젝트", ""))
    pay, proj = pages
    return str(pay), str(proj)


def write_snapshot(root, collected_at, payments, projects, pages=None):
    """스냅숏 폴더를 쓰고 최종 폴더 경로를 돌려준다. 실패하면 이 함수가 만든 '.작성중' 폴더만 지우고 오류를 다시 낸다."""
    stamp = collected_at.strftime(TIME_FORMAT)
    final = os.path.join(root, "인트라넷_" + collected_at.strftime("%Y%m%d_%H%M%S"))
    work = final + ".작성중"
    os.makedirs(root, exist_ok=True)
    if os.path.exists(final):
        raise SnapshotError("같은 수집 시각의 스냅숏 폴더가 이미 있습니다: %s" % final)
    if os.path.exists(work):
        raise SnapshotError("끝나지 않은 스냅숏 폴더가 남아 있습니다(확인 후 지워 주세요): %s" % work)
    created = False
    try:
        os.mkdir(work)
        created = True
        _write_csv(os.path.join(work, PAYMENT_FILE), ["수집시각"] + PAYMENT_COLUMNS,
                   [[stamp] + [("" if p.get(c) is None else p.get(c)) for c in PAYMENT_COLUMNS] for p in payments])
        _write_csv(os.path.join(work, PROJECT_FILE), ["수집시각"] + PROJECT_COLUMNS,
                   [[stamp] + [("" if p.get(c) is None else p.get(c)) for c in PROJECT_COLUMNS] for p in projects])
        pp, jp = _page_counts(pages)
        _write_csv(os.path.join(work, INFO_FILE), ["항목", "값"],
                   [["형식", FORMAT], ["수집시각", stamp], ["지급요청_건수", len(payments)], ["프로젝트_건수", len(projects)],
                    ["지급요청_페이지수", pp], ["프로젝트_페이지수", jp]])
        os.rename(work, final)
    except OSError:
        if created:
            shutil.rmtree(work, ignore_errors=True)
        raise
    return final


def latest_snapshot(root):
    """가장 최근 스냅숏 폴더 경로. 없으면 None. '.작성중' 폴더와 수집정보.csv 없는 폴더는 무시한다."""
    if not root or not os.path.isdir(root):
        return None
    names = [n for n in os.listdir(root)
             if _FOLDER_RE.match(n) and os.path.isfile(os.path.join(root, n, INFO_FILE))]
    return os.path.join(root, max(names)) if names else None


def _read_table(path, columns):
    issues = Issues()
    rows, ok = read_csv(path, ["수집시각"] + columns, issues)
    name = os.path.basename(path)
    if issues.items:
        raise SnapshotError("%s: %s" % (name, "; ".join(m for _, _, m in issues.items)))
    if not ok:
        raise SnapshotError("%s을(를) 읽지 못했습니다" % name)
    return [{c: r.get(c, "") for c in columns} for r in rows]


def read_snapshot(path):
    """스냅숏 폴더를 읽는다. 열이 빠졌거나 건수가 수집정보와 다르면 SnapshotError."""
    issues = Issues()  # 수집정보는 항목,값 형식이라 표 읽기와 따로 읽는다
    rows, ok = read_csv(os.path.join(path, INFO_FILE), ["항목", "값"], issues)
    if issues.items or not ok:
        raise SnapshotError("%s: %s" % (INFO_FILE, "; ".join(m for _, _, m in issues.items) or "읽지 못했습니다"))
    info = {r["항목"]: r["값"] for r in rows}
    if info.get("형식") != FORMAT:
        raise SnapshotError("%s: 알 수 없는 형식 '%s' (필요: %s)" % (INFO_FILE, info.get("형식", ""), FORMAT))
    try:
        collected = dt.datetime.strptime(info.get("수집시각", ""), TIME_FORMAT)
    except ValueError:
        raise SnapshotError("%s: 수집시각을 읽지 못했습니다: '%s'" % (INFO_FILE, info.get("수집시각", "")))
    payments = _read_table(os.path.join(path, PAYMENT_FILE), PAYMENT_COLUMNS)
    projects = _read_table(os.path.join(path, PROJECT_FILE), PROJECT_COLUMNS)
    for label, got, key in (("지급요청", payments, "지급요청_건수"), ("프로젝트", projects, "프로젝트_건수")):
        want = info.get(key, "")
        if not want.isdigit() or int(want) != len(got):
            raise SnapshotError("%s 건수가 수집정보와 다릅니다: 수집정보 %s건, 파일 %d건" % (label, want or "없음", len(got)))
    return Snapshot(path, collected, payments, projects, info)
