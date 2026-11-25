"""경영관리 보고의 개발 용어를 쉬운 말로 (2차 전수조사 J12, 2026-11-18).

계산·표 만드는 코드는 '잠정'·'판단 불가'·'미연결'을 값으로 쓰고 서로 견준다. 그 값은 그대로 두고, 경영관리 보고를 파일로 쓰기
직전에 보이는 글자만 바꾼다 (태그·속성·script·style 안은 건드리지 않음). 대표·팀장 보고에는 이 낱말이 나오지 않는다.
"""
import os
import re
import sys

TEST_OFF = "CEO_REPORT_TEST_PLAIN_OFF"   # 예전 낱말로 값을 확인하는 시험만 쓰는 끄개 (gate.TEST_OFF 와 같은 방식). exe 에서는 듣지 않는다

# 순서대로 바꾼다 (긴 것 먼저)
WORDS = (
    ("프로젝트 미연결", "프로젝트를 못 찾은"),
    ("미연결", "못 찾음"),
    ("판단 불가", "알 수 없음"),
    ("‘잠정’", "‘마감 전’"),
    ("(잠정)", "(마감 전)"),
    ("잠정", "마감 전"),
)
_SKIP = re.compile(r"(<script\b.*?</script>|<style\b.*?</style>|<[^>]+>)", re.S | re.I)


def plain(page):
    """HTML 글에서 보이는 글자만 쉬운 말로 바꾼다."""
    if os.environ.get(TEST_OFF) == "1" and not getattr(sys, "frozen", False):
        return page
    out = []
    for part in _SKIP.split(page or ""):
        if part and not part.startswith("<"):
            for a, b in WORDS:
                if a in part:
                    part = part.replace(a, b)
        out.append(part)
    return "".join(out)
