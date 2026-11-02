# CEO_REPORT — 대표 주간·월간 보고 프로그램

## What This Is

회사 자금·프로젝트 예산·손익·수금·지급의무 자료(CSV)를 읽어 대표에게 올리는 주간·월간 보고서(HTML/PDF)를 만드는 Python 프로그램. 대표용은 숫자와 사실만, 경영관리용은 같은 숫자에 위험 분석·해결방안을 더한다. 사용자의 외장하드(F:\CLAUDE\CEO_REPORT)에서 실행하고 결과물은 Google Workspace(Drive)로 옮긴다.

## Core Value

'얼마를 벌었는가 / 실제 돈은 얼마인가 / 앞으로 얼마가 들어오고 나가는가 / 프로젝트 예산이 어디까지 집행됐는가'를 섞지 않고, 미확인 값을 0으로 넣지 않으며, 표시 범위·전체 건수·합계를 함께 보여 준다.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] 7개 묶음 보고(현재 자금, 입출금 일정, 프로젝트 예산·집행, 손익, 계산서·수금, 프로젝트 밖 지급, 변동·자료 범위)
- [ ] 한 페이지 요약(상단 KPI 4, 중앙 프로젝트 요약+자금 그래프, 하단 4칸) + 상세자료
- [ ] 주간·월간 두 유형, 대표용·경영관리용 두 판
- [ ] WEHAGO·인트라넷 원천자료를 입력 CSV로 바꾸기
- [ ] 외장하드 실행, Drive 업로드, GitHub 저장

### Out of Scope

- 자동 연동(API·스케줄 수집) — 사용자 결정(1차 스레드): CSV 입력, 자동 연동 없음
- 대표용 해석·권고 문구 — 사용자 결정: 대표용은 사실만
- WEHAGO 비밀번호 보관 — 사용자가 직접 로그인한 브라우저를 Claude가 조작

## Context

- 원천: 구 인트라넷 보관자료 `F:\CLAUDE\인트라넷-보관\`(jsonl: projects·quotes·payments·payment_requests·cards·reports, 열쇠 pro_num/quo_num, 사전견적 = pre_quotation). 인트라넷에는 실제 이체·수금 자료가 없다(수집기록.md 5절).
- WEHAGO(회계): 손익·세금계산서·채권채무·계좌 자료.
- 작업 방식: 260917 환경과 같은 순서(GSD + Superpowers, gstack 게이트). gstack은 이 세션에서 설치 거부됨.

## Constraints

- **실행 환경**: 사용자 Windows PC 외장하드, Python 3.8+ 표준 라이브러리만 — 설치 부담 없이 외장하드에서 실행
- **PDF**: Edge/Chrome headless 인쇄 — 별도 라이브러리 없이
- **입력**: 엑셀 저장 CSV(UTF-8/CP949 모두)
- **보안**: 계정 정보는 채팅·저장소에 두지 않는다

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| CSV 입력 → HTML/PDF, 자동 연동 없음 | 1차 스레드 사용자 결정 | — Pending |
| 대표용·경영관리용 같은 계산 결과 사용 | 숫자 불일치 방지(사용자 요구) | — Pending |
| 미확인 값은 None, 0으로 대체 금지 | 사용자 요구 | — Pending |
| 날짜 없는 예정금액·경과 미수는 일정 밖 별도 표 | 사용자 요구 | — Pending |
| 카드 미결제는 카드대금 일정에만 반영(중복 방지) | 사용자 요구 "다시 더하지 않음" | — Pending |
| 연구(research) 단계 생략 | 사용자가 구성안을 상세히 제시, 1차 코드 있음 | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

---
*Last updated: 2026-11-02 after initialization*
