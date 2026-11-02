# Roadmap: CEO_REPORT

## Phases

- [ ] **Phase 1: 보고 엔진 검증** — 7개 묶음 계산·화면을 테스트로 고정
- [ ] **Phase 2: 원천자료 변환** — WEHAGO·인트라넷 자료를 입력 CSV로
- [ ] **Phase 3: 배포** — 외장하드 실행, Drive 업로드, GitHub

### Phase 1: 보고 엔진 검증
**Goal:** 샘플 자료로 주간·월간, 대표용·경영관리용 보고가 사용자 규칙대로 나온다
**Mode:** mvp
**Requirements:** CASH-01..03, PLAN-01..03, PROJ-01..04, PL-01..03, AR-01..03, AP-01..02, DATA-01..03, REP-01..03
**Success Criteria:**
1. 규칙별 단위 테스트(이체 제외, 날짜 없음 분리, 미확인≠0, 예산 미지정 판단 불가, 카드 중복 없음) 통과
2. 대표용·경영관리용에서 위험 절을 뺀 숫자가 같다(자동 테스트)
3. 대표용 HTML에 위험·권고 문구가 없다(자동 테스트)
4. 보고 대조표 전부 일치, 첫 화면 표시/전체 건수/합계가 보인다
**UI hint:** yes (HTML 보고서)
**Plans:** 2 plans

Plans:
- [ ] 01-01-PLAN.md — 엔진 결함 수정(R1~R4, DR1~DR4) 테스트 먼저: 잔액 미확인(알려진 사용제한은 유지)·미확인 금액·예정일 지난 미처리(확인분 합계+미확인 건수)·부가세 미확인 일정 표시, 설정값 해석(빈칸은 기본값+입력 확인), 대표용 규칙 전수 확인 (wave 1)
- [ ] 01-02-PLAN.md — 월간·PDF·실행.bat(R5), 이전 PDF 재사용 방지, D-16 원가 예산(사전견적×원가율)·예산 사유·예산 미책정 표시, 남은 요구사항 전부 테스트 고정 + D-06 표기·5번/7번 미확인 0 처리 수정 (wave 2)

### Phase 2: 원천자료 변환
**Goal:** 실제 WEHAGO 내려받기와 인트라넷 보관자료로 보고서를 만든다
**Requirements:** SRC-01, SRC-02
**Success Criteria:**
1. WEHAGO 엑셀 → 손익·계산서 CSV 변환, 원본 합계와 일치
2. 인트라넷 jsonl → 프로젝트·집행 CSV, 수집기록 검산값(117건 등)과 일치

### Phase 3: 배포
**Goal:** 사용자가 외장하드에서 실행하고 결과를 Drive에서 본다
**Requirements:** DEP-01, DEP-02, DEP-03
**Success Criteria:**
1. F:\CLAUDE\CEO_REPORT 에 프로그램·결과물만 있다
2. Drive에 결과 HTML/PDF가 있다
3. GitHub PR이 열려 있다

## Progress

| Phase | Plans | Status |
|-------|-------|--------|
| 1 | 0/2 | Planned |
| 2 | 0/1 | Not started |
| 3 | 0/1 | Not started |
