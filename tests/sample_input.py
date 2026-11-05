"""테스트용 샘플 입력 폴더.

tools/make_sample.py 로 임시 폴더에 샘플 CSV를 만든다. 실제 입력 폴더(<프로그램 폴더>/입력)는 사용자의 회사 자료가
들어가는 곳이므로 테스트가 쓰거나 읽지 않는다. 명령 줄 도구를 부르는 테스트는 이 폴더를 --입력 으로 넘긴다.
"""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAKE_SAMPLE = os.path.join(ROOT, "tools", "make_sample.py")

_TMP = tempfile.mkdtemp(prefix="ceo_report_sample_")
atexit.register(shutil.rmtree, _TMP, True)
SAMPLE = os.path.join(_TMP, "입력")


def refresh():
    """샘플 폴더를 지우고 make_sample.py 로 새로 쓴다 (테스트 모듈 시작마다: 앞 모듈이 바꾼 것이 남지 않게)."""
    shutil.rmtree(SAMPLE, ignore_errors=True)
    subprocess.run([sys.executable, MAKE_SAMPLE, SAMPLE], check=True, stdout=subprocess.DEVNULL)
