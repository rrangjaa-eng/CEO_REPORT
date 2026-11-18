"""보고 PDF 이름에 만든 시각을 붙이고, 같은 보고가 쌓이면 정리한다 (사용자 2026-11-12).

· 이름: '<기준일>_<주간>_<대표보고> (11-12 14시05분 만듦).pdf' — 어떤 파일이 가장 새것인지 이름으로 보인다.
  HTML 은 이름을 바꾸지 않는다 (영역별 보기·수정 모드·근거자료가 늘 가장 새 HTML 을 쓴다).
· 정리: 같은 보고(같은 기준일·종류·대상)의 PDF 가 KEEP_FROM 개 이상이면 가장 새로 만든 KEEP 개만 남기고 '지난PDF' 폴더로 옮긴다 (지우지 않음 — 보낸 판이 섞여 있을 수 있음).
  수정 모드로 만든 '_수정' PDF 는 이름이 달라 건드리지 않는다.
"""
import datetime as dt
import os
import re

KEEP_FROM = 5
KEEP = 3
_STAMP = re.compile(r" \((\d{2})-(\d{2}) (\d{2})시(\d{2})분(?:(\d{2})초)? 만듦\)$")


def stamped(base, now=None):
    """base(확장자 없는 경로) -> 만든 시각을 붙인 PDF 경로. 같은 분에 이미 있으면 초까지 붙여 앞 PDF 를 덮지 않는다 (코덱스 검토 2026-11-14)."""
    now = now or dt.datetime.now()
    path = "%s (%s 만듦).pdf" % (base, now.strftime("%m-%d %H시%M분"))
    if os.path.exists(path):
        path = "%s (%s 만듦).pdf" % (base, now.strftime("%m-%d %H시%M분%S초"))
    return path


def same_report(base):
    """base 와 같은 보고의 PDF 경로들 (시각 붙은 것 + 예전 이름 '<base>.pdf')."""
    folder, name = os.path.split(base)
    try:
        names = os.listdir(folder or ".")
    except OSError:
        return []
    out = []
    for n in names:
        if not n.lower().endswith(".pdf"):
            continue
        stem = n[:-4]
        if stem == name or (stem.startswith(name) and _STAMP.fullmatch(stem[len(name):])):
            out.append(os.path.join(folder, n))
    return out


def _made_at(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def newest(base):
    """같은 보고 중 가장 새로 만든 PDF 경로, 없으면 None."""
    found = same_report(base)
    return max(found, key=_made_at) if found else None


OLD_DIR = "지난PDF"


def prune(base, keep_from=KEEP_FROM, keep=KEEP):
    """같은 보고 PDF 가 keep_from 개 이상이면 새것 keep 개만 남기고 '지난PDF' 폴더로 옮긴다 -> 옮긴 경로(옛 자리) 목록.
    2차 전수조사 P15 (2026-11-18, 안전-06): 예전엔 지웠다 — 어느 판을 대표에게 보냈는지 프로그램은 모르므로 지우지 않고 옮긴다.
    옮기지 못한 것(열려 있는 PDF)은 그대로 두고 다음에 다시 정리."""
    found = sorted(same_report(base), key=_made_at, reverse=True)
    if len(found) < keep_from:
        return []
    gone = []
    for p in found[keep:]:
        folder, name = os.path.split(p)
        try:
            os.makedirs(os.path.join(folder, OLD_DIR), exist_ok=True)
            os.replace(p, os.path.join(folder, OLD_DIR, name))
            gone.append(p)
        except OSError:
            pass
    return gone
