# Phase 1: 보고 엔진 검증 — Context

**Gathered:** 2026-11-02
**Status:** Ready for planning
**Source:** 사용자 구성안(2026-11-02 05:26, 7개 묶음 원문) + /plan-eng-review·/plan-design-review 결과(사용자 부재로 권장안 자동 수용)

<domain>
## Phase Boundary

1차 코드(`보고서.py`, `ceo_report/data.py·calc.py·render.py·util.py`, `tools/make_sample.py`, `tests/test_report.py` 28개 통과)가 이미 있다.
이 페이즈는 새 기능을 만드는 것이 아니라 **사용자 규칙을 코드와 테스트로 고정**하고, 검토에서 찾은 결함 9건을 고친다.
원천자료 변환(WEHAGO·인트라넷 → CSV)은 Phase 2, 외장하드 배포·Drive는 Phase 3. 이 페이즈에서 다루지 않는다.
</domain>

<decisions>
## Implementation Decisions (LOCKED — 사용자 원문 규칙)

- **D-01** '얼마를 벌었는가(손익) / 실제 돈(잔액) / 앞으로 들어오고 나갈 돈(일정) / 예산 집행'을 섞지 않는다. 이익과 현금잔액은 별도 지표.
- **D-02** 미확인 값은 None. 0으로 대체 금지. 합계에 섞일 때는 "확인된 것만의 합계 + 미확인 N건"을 함께 보인다.
- **D-03** 회사 계좌 간 이체는 회사 전체 입출금에서 빼고, 이체 입금 = 이체 출금을 대조한다.
- **D-04** 날짜 없는 예정금액, 입금예정일이 지난 미수, 예정일이 지난 미처리 금액은 그래프·기간 합계에 넣지 않고 별도 표로 보인다(조용히 빼지 않음 — 첫 화면에도 건수·금액이 보여야 함).
- **D-05** 미확인 수금(예정일 미확정)은 추정, 확정과 구분.
- **D-06** 프로젝트 예산: 사전 견적이 없으면 '예산 미지정', 비율·잔여예산은 '판단 불가'. 남은 예산을 지급예정으로 만들지 않는다. 근거 없는 잔액은 '집행계획 미등록 금액'.
- **D-07** 공급가액 기준(예산 비교)과 부가세 포함 실제 출금액을 분리. 카드 사용액은 총액.
- **D-08** 카드 미결제는 카드대금 일정에만 반영(프로젝트 지급과 이중 계산 금지). 프로젝트 지급·카드 청구에 이미 포함된 금액은 프로젝트 밖 지급에 다시 더하지 않는다.
- **D-09** 미확인 원가를 0원으로 넣어 이익을 크게 보이게 하지 않는다 → 예상이익 '판단 불가'. 회계 미반영 비용은 잠정.
- **D-10** WEHAGO 손익과 인트라넷 완료보고 손익을 따로 표시.
- **D-11** 실제 완료일이 없으면 미발행 경과일을 계산하지 않는다. 미발행금액과 미수금은 구분.
- **D-12** 첫 화면은 일부만 보여도 표시 건수 / 전체 건수 / 전체 합계를 함께 보인다. 요약과 상세 합계를 대조해 결과를 싣는다.
- **D-13** 대표용에는 해석·권고·'위험' 문구가 없다. 경영관리용은 같은 숫자 + 위험 분석·해결방안만 추가. 숫자는 한 번 계산(calc.compute)한 결과를 두 판이 공유.
- **D-14** 한 페이지 구성: 상단 현재 현금/사용 가능액/4주 입금예정/4주 지급예정 · 중앙 프로젝트 예산·지급(가장 크게)+기간별 자금 그래프 · 하단 매출·이익/미수·미지급/미발행/자료 기준일·미반영 · 상세자료 1~7.
- **D-15** 실행: Python 3.8+ 표준 라이브러리만, Windows 외장하드에서 실행, 입력 CSV(UTF-8/CP949), 출력 HTML + PDF(Edge/Chrome headless). 주간·월간 두 유형.
- **D-16** (2026-11-02 사용자 추가 결정) 프로젝트 예산(원가 예산) = 사전견적금액 × 원가율. 사전견적 = 그 프로젝트의 예상 매출.
  - 원가율은 설정.csv `예산_원가율`, 기본 0.70. 값이 비어 있으면(행이 없어도) 기본값을 쓰고, 입력 확인 목록에 '기본값 사용'으로 보인다.
  - 사전견적이 없는 프로젝트는 D-06 그대로 '예산 미지정', 비율·잔여예산 '판단 불가'.
  - 예산이 없는 프로젝트는 '예산 미지정'만 쓰지 않고, 보이는 '사유' 열에 이유를 적는다. 최소 사유: '사전견적 없음'(빈칸), '사전견적 0원 또는 음수', '사전견적 금액 해석 불가'(숫자 아님), '원가율 설정 오류'(예산_원가율이 숫자가 아니거나 0 이하 또는 1 초과 → 모든 프로젝트 예산을 계산하지 않음 + 입력 확인 항목).
  - 이 프로젝트들에는 예산·지급률·잔여예산을 만들지 않는다(판단 불가).
  - 첫 화면 프로젝트 표 합계 옆에 '예산 미책정 N건 (사유별 건수)'.

## Review-accepted fixes (이 페이즈에서 반드시 반영)

- **R1 [P1]** `calc.py:47,73` 잔액 빈칸 계좌가 0으로 합산되고 첫 화면에 표시 없음(탐침: 운영계좌 잔액 비움 → 현재 현금 212.3, 경고 없음). → 확인된 계좌 합계를 쓰되 KPI 보조줄·1번 표·2번 일정 시작잔액에 "잔액 미확인 N계좌 (합계 제외)" 표시, 입력 확인 목록에 추가.
- **R2 [P1]** `calc.py:322` 거래처별 미지급 `s["amount"] or 0` — 미확인 금액이 0. → 거래처별 미확인 건수를 세어 표에 표시.
- **R3 [P2]** `calc.py:239` 예정일이 지난 미처리 입출금이 첫 화면에서 빠짐. → 첫 화면 일정 요약에 "예정일 지난 미처리 입금/지급" 줄 추가(일정·최저잔액에는 합산하지 않음: 날짜를 지어내지 않는다).
- **R4 [P2]** `calc.py:136,406-410`·`render.py:572` `int()/float()`로 설정값 해석 → "50,000,000"이면 프로그램이 멈춤. → `util.num` 계열로 해석, 실패 시 기본값 + 입력 확인 목록.
- **R5 [P2]** REP-01 `실행.bat` 없음 → `실행_주간.bat`, `실행_월간.bat` 추가(chcp 65001, python 없으면 안내).
- **DR1** KPI 숫자 옆 단위 "백만원" 표기.
- **DR2** 하단 '프로젝트 밖 지급예정'은 기간이 다른 값 → "(등록분 전체)" 표기, 날짜 없음 건수 함께.
- **DR3** = R1의 첫 화면 표시.
- **DR4** = R3의 첫 화면 표시.

### Claude's Discretion
- 테스트는 기존 `tests/test_report.py`(unittest, 샘플은 `tools/make_sample.py`로 생성) 방식 유지. 새 규칙마다 실패 테스트 먼저(TDD).
- 결함 탐침용 입력은 임시 폴더에 샘플을 복사해 한 칸만 바꾸는 방식.
</decisions>

<canonical_refs>
## Canonical References

- `.planning/REQUIREMENTS.md` — Phase 1 요구사항 CASH/PLAN/PROJ/PL/AR/AP/DATA/REP
- `.planning/ROADMAP.md` — Phase 1 성공 기준 4개
- `~/.gstack/projects/rrangjaa-eng-CEO_REPORT/claude-project-thread-jkflss-eng-review-20261102.md` — 엔지니어링 검토(R1~R5)
- `~/.gstack/projects/rrangjaa-eng-CEO_REPORT/claude-project-thread-jkflss-design-review-20261102.md` — 디자인 검토(DR1~DR4)
- `desk_대표보고.png`, `phone_대표보고.png` — 현재 화면
</canonical_refs>

<code_context>
## Existing Code Insights

- `ceo_report/util.py`: `num()`(빈칸→None), `date()`, `ssum()`(미확인 개수 반환), `won()/man()/pct()`, `Issues`.
- `ceo_report/data.py`: `SCHEMA`(CSV 12종, 필수 열), `load()` → `Data`(검증 문제는 `issues`).
- `ceo_report/calc.py`: `compute(d, kind, asof)` → `R["s1".."s7"]`, `R["risks"]`(경영관리용), 대조표 `checks`.
- `ceo_report/render.py`: `render(R, mode)` mode="ceo"|"mgmt"; 첫 화면(KPI·프로젝트 표·SVG 그래프·하단 4칸) + 상세 1~7.
- `보고서.py`: CLI `주간|월간 --기준일 --시작일 --입력 --출력 --pdf`.
- 테스트: `python3 -m unittest discover -s tests` (28개).
</code_context>

<specifics>
## Specific Ideas
- 대표용 HTML 금지어 테스트(위험·해결방안·권고·우려·추천)가 새 문구에도 걸리지 않게 한다("잔액 미확인", "예정일 지난 미처리"는 사실 표기).
- 두 판 숫자 동일 테스트가 새 숫자에도 통과해야 한다.
</specifics>

<deferred>
## Deferred Ideas
- WEHAGO·인트라넷 원천자료 변환 → Phase 2
- 외장하드 배포·Drive 업로드 → Phase 3
- 자동 수집(API) → v2 (사용자 결정: 없음)
- 지급 요청 승인용 자금 영향 화면(`docs/designs/payment-approval-cash-impact.md`, office-hours 2026-11-02) → 이후 새 페이즈. Phase 1은 엔진 정확성만 다루며, 그 화면은 `calc.compute` 결과를 그대로 재사용한다.
</deferred>

---

*Phase: 01-report-engine*
*Context gathered: 2026-11-02*

## Plan-check acceptance (2026-11-02, iteration 2)
- D-16 원가율 범위 '0~1 밖'은 Claude가 받아 적은 표현이었음 → '0 이하 또는 1 초과'로 명확화(0이면 모든 예산 0원이 되므로 오류). 사용자 원문은 "원가율 70% 정도"뿐.
- 01-02 파일 11개(경고 기준 10) 수락: 세 작업이 서로 다른 섹션이라 나누면 같은 테스트 파일을 두 계획이 고치게 됨.
