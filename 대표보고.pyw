"""대표 보고 프로그램 (창 하나). 두 번 누르면 창이 열립니다. exe 로 묶을 때의 시작점이기도 합니다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceo_report.gui import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
