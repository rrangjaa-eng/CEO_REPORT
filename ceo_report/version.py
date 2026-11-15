"""설치된 프로그램의 판 (커밋·만든 날). 2차 C16·P6-12 (2026-11-15): exe 에 판 표시가 없어 어떤 판이 깔렸는지 알 수 없었다.
exe 를 묶을 때 tools/stamp_build.py 가 _build.py 를 만든다. 개발 폴더에서 돌리면 '개발판'."""


def build():
    try:
        from ._build import BUILD
        return BUILD
    except ImportError:
        return "개발판"
