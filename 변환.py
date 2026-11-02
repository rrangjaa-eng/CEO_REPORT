"""원천자료(WEHAGO 엑셀)를 보고서 입력 CSV로 바꾸기.

사용법 (명령 창):
    python 변환.py                                 ← 오늘 기준 변환 (실행_변환.bat)
    python 변환.py --기준일 2026-11-02
    python 변환.py --입력 입력 --수집폴더 수집 --위하고폴더 수집\\위하고

수집 폴더의 위하고 폴더에 있는 WEHAGO 엑셀(분개장·매입매출장·전자세금계산서)과 가장 최근 인트라넷 스냅숏을 읽어 입력 폴더에
손익.csv · 계산서.csv · 프로젝트.csv · 프로젝트집행.csv · 위하고대조.csv 를 쓰고, 원본 합계와 CSV 합계를 맞춰 본 결과를
입력\\변환결과.txt 에 남긴다. 스냅숏이 없으면 프로젝트·프로젝트집행·위하고대조는, 매출 계산서 엑셀이 없으면 계산서는 만들지
않고 기존 파일을 그대로 둔다(변환결과.txt에 이유). 이미 있는 CSV는 입력\\이전\\<시각>\\ 에 먼저 보관한다.
사람이 직접 관리하는 파일(계좌잔액·설정·지급계획·변경내역·자료기준일·프로젝트연결)과 입출금내역·자금일정·자료차이는 읽기만 한다.
화면에는 파일마다 한 줄, 대조 불일치 건수, 자금일정과 겹칠 수 있는 줄 수, 보고서 입력 확인 필요 건수, 변환결과.txt 위치를 보인다.

종료 코드: 0 완료 · 2 입력 문제(기준일 형식) · 3 WEHAGO 장부를 쓸 수 없음(자료 없음·머리글 다름·읽기 실패: CSV를 만들지 않음)
· 7 파일을 쓰지 못함(엑셀에서 열려 있는 파일 등: 아무 파일도 바꾸지 않음)
"""
import argparse
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from ceo_report import convert  # noqa: E402
from ceo_report.util import date as parse_date  # noqa: E402
from ceo_report.util import mask_rrn  # noqa: E402


def _say(text):
    """표준 출력 한 줄. 주민번호 모양 글자는 가린다 (D-45)."""
    print(mask_rrn(text))


def main(argv=None):
    ap = argparse.ArgumentParser(description="WEHAGO 엑셀 → 보고서 입력 CSV 변환")
    ap.add_argument("--기준일", default=None, help="YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--입력", default=os.path.join(HERE, "입력"))
    ap.add_argument("--수집폴더", default=os.path.join(HERE, "수집"))
    ap.add_argument("--위하고폴더", default=None, help="WEHAGO 엑셀 폴더 (기본: <수집폴더>/위하고)")
    a = ap.parse_args(argv)
    if a.기준일:
        asof = parse_date(a.기준일)
        if asof is None:
            _say("기준일 형식 오류: %s (YYYY-MM-DD)" % a.기준일)
            return 2
        now = dt.datetime.combine(asof, dt.time(0, 0))
    else:
        now = dt.datetime.now()
        asof = now.date()
    wehago_dir = a.위하고폴더 or os.path.join(a.수집폴더, "위하고")
    res = convert.run(a.입력, a.수집폴더, wehago_dir, asof, now)
    for line in res.lines:
        _say(line)
    return res.code


if __name__ == "__main__":
    sys.exit(main())
