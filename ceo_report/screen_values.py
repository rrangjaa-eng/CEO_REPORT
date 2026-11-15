"""인트라넷 화면에서 읽는 승인 글자와 그 뜻을 한 곳에 둔다 (규칙 안전-07, 2026-11-15).

여기에는 실제 화면이나 실제 스냅숏에서 본 글자만 둔다. 처음 보는 글자는 숫자에 넣지 않고 경영관리에 경고한다
(빈칸은 수집이 칸을 놓친 것일 수 있어 D-52대로 '상태 확인 필요'로 넣는다). 글자를 더할 때는 본 날짜와 건수를 적고
tests/test_rules_1115.py 의 목록 시험도 같이 고친다.

왜: '수락완료'(대표 승인 끝)를 한 곳은 끝남, 다른 곳은 모름으로 읽어 팀장 보고 예산 넘음 경보 107건 중 34건이 거짓이었다
(2026-11-15 실제 자료 R1). 같은 글자를 곳마다 따로 적지 않게 모두 이 모듈을 쓴다.
"""

# 지급요청 목록 '사장님승인' 칸.
# 실제: 2026-11-05 화면 100건(관리팀 계정), 2026-11-13 스냅숏 684건 = '수락완료' 555 · '미승인' 129.
CEO_APPROVED = ("수락완료", "승인")   # 수락완료 = 대표 승인까지 끝 (사용자 결정 a, 2026-11-15). '승인'은 처음 규칙(A-1)의 글자
CEO_PENDING = ("미승인", "수락요청중")

# 지급요청 목록 '관리팀승인' 칸: 상태가 아니라 버튼 글자다 (2026-11-05 실제 화면).
# '승인' 버튼 = 관리팀 아직 안 함 · '반려' 버튼 = 관리팀 승인 끝, 사장님 전 · '수락완료' = 모두 끝
ADMIN_DONE_WAITING = ("반려",)

# 프로젝트 목록 승인 네 칸(담당자·팀장·관리팀·대표이사). 지급요청 목록과 같게 읽는다:
# '수락완료'·'완료'·'승인완료' = 끝남, '반려'(반려 버튼) = 그 단계 승인이 끝남, '승인'(승인 버튼)·'미승인'·빈칸 = 아직.
PROJECT_STAGE_DONE = ("완료", "수락완료", "승인완료", "반려")
PROJECT_STAGE_ALL_DONE = ("완료", "수락완료", "승인완료")   # 네 칸을 합친 한 칸에 이 글자면 모두 끝
PROJECT_STAGE_WAITING = ("승인", "미승인", "")


def ceo_status(text):
    """'사장님승인' 글자 -> 'approved' | 'pending' | 'status_unknown'.

    빈칸과 처음 보는 글자는 둘 다 'status_unknown'(승인·대기로 세지 않음). 둘을 가르는 것은 is_new_ceo_value."""
    t = (text or "").strip()
    if t in CEO_APPROVED:
        return "approved"
    if t in CEO_PENDING:
        return "pending"
    return "status_unknown"


def is_new_ceo_value(text):
    """'사장님승인' 칸에 처음 보는 글자인가 (빈칸은 아님). 이런 요청은 숫자에 넣지 않고 경영관리에 경고한다 (안전-07)."""
    t = (text or "").strip()
    return bool(t) and t not in CEO_APPROVED and t not in CEO_PENDING


def is_new_project_value(text):
    """프로젝트 목록 승인 칸에 처음 보는 글자인가 (빈칸은 아님)."""
    t = (text or "").strip()
    return bool(t) and t not in PROJECT_STAGE_DONE and t not in PROJECT_STAGE_WAITING
