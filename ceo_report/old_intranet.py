"""예전 인트라넷 (2025년 ~ 2026년 3월 사용, 사용자 2026-11-05) 자료 읽기.

수집\\예전인트라넷\\ 의 CSV (사용자 PC에서 화면을 읽어 저장한 것, 회사 자료라 저장소에 올리지 않는다):
    old_projects_YYYY.csv  완료보고서 목록 (번호·클라이언트·행사일·행사명·국·팀·등록자·발행일·계산서·사전견적·견적금액·실행가·수익율 …)
    old_payments_YYYY.csv  페이먼트 목록 (번호·행사명·파트너·등록일·행사일·금액·지급요청일·등록자·팀장·관리팀·사장님 승인·지불)
지금 인트라넷 스냅숏과 같은 열 이름(snapshot.PROJECT_COLUMNS / PAYMENT_COLUMNS)으로 바꿔 돌려준다.

쓰는 곳 (사용자 2026-11-05 '프로그램에 연결', 계좌 연결은 하지 않음):
· 프로젝트 목록: 지금 인트라넷에 같은 번호가 없을 때만 더한다 (지금 인트라넷이 우선). 2026-03-31 까지 행사는 상태 '완료'로
  두어 남은 예산을 지급 예정으로 만들지 않는다 (끝난 행사).
· 지급요청: 원가 전표를 프로젝트에 잇는 데만 쓴다 (거래처·금액·날짜). 아직 나갈 돈(요청미지급)으로는 넣지 않는다 — 예전 요청은
  모두 끝난 건이다 (사용자 2026-11-04: 2025년 건은 입금·지급 모두 끝남).
· 업체(계좌)·클라이언트·법인카드·견적/완료보고 항목 파일은 읽지 않는다.
"""
import csv
import datetime as dt
import os
import re

from .snapshot import PAYMENT_COLUMNS, PROJECT_COLUMNS

FOLDER = "예전인트라넷"
OLD_LAST_DAY = dt.date(2026, 3, 31)   # 예전 인트라넷을 쓴 마지막 날 (사용자 2026-11-05: 2026년 3월까지)
OLD_STATE = "완료(예전 인트라넷)"   # 예전 인트라넷 끝난 행사: 보고서 프로젝트·미발행·예상 매출에서 뺀다 (사용자 2026-11-05)
NO_PREFIX = "구"                       # 지급요청 번호가 지금 인트라넷 번호와 겹치지 않게 앞에 붙인다
_PROJECT_RE = re.compile(r"^old_projects_\d{4}\.csv$", re.I)
_PAYMENT_RE = re.compile(r"^old_payments_\d{4}\.csv$", re.I)

# 예전 화면의 머리글 -> 지금 스냅숏 열 이름 (공백은 빼고 비교)
PROJECT_ALIASES = {"내부번호": "내부번호", "클라이언트": "클라이언트", "담당자": "담당자", "행사일": "행사일",
                   "행사명": "행사명", "국": "국", "팀": "팀", "등록자": "등록자", "계산서": "계산서", "사전견적": "사전견적",
                   "견적금액": "견적금액", "실행가": "실행가", "수익율": "수익률", "수익률": "수익률"}
PAYMENT_ALIASES = {"내부번호": "내부번호", "번호": "번호", "파트너(페이먼트)": "파트너", "행사명": "행사명", "파트너": "파트너", "업체": "파트너", "업체명": "파트너", "등록일": "등록일",
                   "행사일": "행사일", "금액": "금액", "지급요청일": "지급요청일", "등록자": "등록자", "팀장승인": "팀장승인",
                   "팀장": "팀장승인", "관리팀승인": "관리팀승인", "관리팀": "관리팀승인", "사장님승인": "사장님승인",
                   "사장님": "사장님승인", "대표이사승인": "사장님승인", "지불": "지불"}


class OldData:
    def __init__(self, projects, payments, notes, files):
        self.projects, self.payments, self.notes, self.files = projects, payments, notes, files


def _key(text):
    return re.sub(r"[\s▲▼]+", "", str(text or ""))


_AMPM = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*(오전|오후)\s*(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_RANGE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})\s*$")


def registered_text(text):
    """'2025-03-14 오후 3:12:45' -> '2025-03-14 15:12:45' (지금 인트라넷 등록일 모양). 모양이 다르면 그대로."""
    t = (text or "").strip()
    m = _AMPM.match(t)
    if not m:
        return t
    h = int(m.group(3)) % 12 + (12 if m.group(2) == "오후" else 0)
    return "%s %02d:%s:%s" % (m.group(1), h, m.group(4), m.group(5) or "00")


def event_text(text):
    """'시작~끝' -> 끝 날짜 (끝난 행사인지 보는 날). 하루짜리는 그대로."""
    t = (text or "").strip()
    m = _RANGE.match(t)
    return m.group(2) if m else t


def approval_text(text):
    """예전 승인 칸 '수락완료(2025-03-14)' -> '승인', '진행중' -> '미승인' (지금 인트라넷 낱말). 나머지는 그대로."""
    t = (text or "").strip()
    if t.startswith("수락완료"):
        return "승인"
    if t.startswith("진행중"):
        return "미승인"
    return t


def _read(path, aliases, columns):
    """CSV 한 파일 -> [열 이름 -> 값] (모르는 열은 버린다). 머리글에 '번호'·'행사명'이 없으면 ValueError."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    head = [aliases.get(_key(h)) for h in rows[0]]
    if "행사명" not in head:
        raise ValueError("머리글에 행사명이 없음")
    out = []
    for r in rows[1:]:
        if not any(c.strip() for c in r):
            continue
        d = {c: "" for c in columns}
        for i, name in enumerate(head):
            if name and i < len(r) and not d.get(name):
                d[name] = r[i].strip()
        if not d.get("행사명"):
            continue
        out.append(d)
    return out


def _year(name):
    m = re.search(r"(\d{4})", name)
    return m.group(1) if m else ""


def load(collect_dir):
    """-> OldData (폴더가 없으면 빈 목록).

    · 프로젝트 '번호' 칸은 화면 순번이라 버린다: 프로젝트 번호는 행사명 앞 [코드] (실제 자료 2026-11-05).
      같은 3자리 코드가 두 해에 있으면 뒤 해(새 것)를 먼저 둔다 → 해 내림차순으로 읽는다.
    · 지급요청 번호도 해마다 다시 세는 순번이라 '구<해>-<번호>' 로 바꾼다. 등록일 오전/오후, 승인 '수락완료(날짜)'는 지금 모양으로.
    """
    folder = os.path.join(collect_dir or "", FOLDER)
    projects, payments, notes, files = [], [], [], []
    try:
        names = sorted(os.listdir(folder), key=lambda n: (_year(n), n), reverse=True)
    except OSError:
        return OldData(projects, payments, notes, files)
    seen_pay = set()
    for n in names:
        kind = "프로젝트" if _PROJECT_RE.match(n) else ("지급요청" if _PAYMENT_RE.match(n) else None)
        if kind is None:
            continue
        year = _year(n)
        try:
            rows = _read(os.path.join(folder, n), PROJECT_ALIASES if kind == "프로젝트" else PAYMENT_ALIASES,
                         (PROJECT_COLUMNS if kind == "프로젝트" else PAYMENT_COLUMNS + ["지불"]) + ["내부번호"])
        except (OSError, ValueError, csv.Error) as e:
            notes.append("예전 인트라넷 %s 읽지 못함: %s" % (n, e if isinstance(e, ValueError) else type(e).__name__))
            continue
        kept = 0
        for d in rows:
            if kind == "프로젝트":
                d["번호"], d["pro_num"] = "", d.pop("내부번호", "")
                d["행사일"] = event_text(d["행사일"])
                projects.append(d)
            else:
                no = "%s%s-%s" % (NO_PREFIX, year, d["번호"] or d.get("내부번호", ""))
                if no in seen_pay:
                    no = "%s-%d" % (no, kept)
                seen_pay.add(no)
                d["번호"] = no
                d.pop("내부번호", None)
                d["등록일"] = registered_text(d["등록일"])
                for c in ("팀장승인", "관리팀승인", "사장님승인"):
                    d[c] = approval_text(d[c])
                payments.append(d)
            kept += 1
        files.append(n)
        notes.append("예전 인트라넷 %s: %s %d건" % (n, kind, kept))
    return OldData(projects, payments, notes, files)


class _Snap:
    """linking.requests_of / projects_of 가 읽는 모양 (payments·projects 만)."""
    def __init__(self, payments=(), projects=()):
        self.payments, self.projects = list(payments), list(projects)


def as_snapshot(old):
    return _Snap(old.payments, old.projects)
