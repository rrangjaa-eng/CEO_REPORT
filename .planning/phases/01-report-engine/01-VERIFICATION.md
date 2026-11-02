---
phase: 01-report-engine
verified: 2026-11-02T08:05:00Z
status: gaps_found
score: 6/8 must-haves verified
covered_files:
  - .gitattributes
  - .planning/REQUIREMENTS.md
  - .planning/phases/01-report-engine/01-01-PLAN.md
  - .planning/phases/01-report-engine/01-01-SUMMARY.md
  - .planning/phases/01-report-engine/01-02-PLAN.md
  - .planning/phases/01-report-engine/01-02-SUMMARY.md
  - ceo_report/calc.py
  - ceo_report/data.py
  - ceo_report/render.py
  - ceo_report/util.py
  - tests/test_report.py
  - tools/make_sample.py
  - 보고서.py
  - 실행_월간.bat
  - 실행_주간.bat
covered_digest: "v1:sha256:76dde37b4e73102dfc6eecbdc2b22a0092b708b7d03e77ff5aa0c0de909be61c"
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "D-02 / ROADMAP SC1 '미확인 ≠ 0' holds on the first screen: an unknown project request amount is not shown as 0 and a total that leaves it out carries an unknown count"
    status: failed
    reason: "Sample project P26206 has a 요청미지급 line (진행팀, 프로젝트집행.csv line 21) with blank 공급가액. Section 3 shows it correctly ('금액 미확인 1건'), but the first screen drops the count. The first-screen project table row P26206 reads 요청·카드 미결제 0.0 and 예상 잔여예산 2.0 (which treats the unknown as 0, so the remaining budget looks larger). The total row (요청·카드 미결제 98.5, 예상 잔여예산 -46.5) and the card '프로젝트 요청 미지급 95.0' also carry no unknown count. Tests pass because no test checks the first-screen project table or card for project-level unknown counts."
    artifacts:
      - path: "ceo_report/render.py"
        issue: "first-screen project table (about lines 207-229) renders M(P['requested'] + P['card_unpaid']) and M(P['remain']) with no unknown marker; the 미수·미지급 card (about line 248-251) renders 프로젝트 요청 미지급 without an unknown count. calc already holds the data (R['s3']['total']['unknown_cost'], per-project unknown counts); render.py _s3 (line 475) uses it, the first screen does not."
    missing:
      - "On the first screen, show '미확인 N건' next to 요청·카드 미결제 / 예상 잔여예산 for a project that has an unknown request line, and next to the 전체 total and the '프로젝트 요청 미지급' card value"
      - "A test that blanks one 요청미지급 amount and asserts the count on the first screen (the sample already contains such a line)"
deferred: []
advisory: []
human_verification:
  - test: "Windows PC with Python 3.8+: double-click 실행_주간.bat, then 실행_월간.bat"
    expected: "The console shows '만든 파일:' with 출력\\...주간/월간_대표보고.html and _경영관리보고.html (plus .pdf with Edge). Korean text is readable (chcp 65001) and the window waits for a key."
    why_human: "cmd.exe behaviour cannot run on this Linux host. Only file bytes were checked here: UTF-8 without BOM, CRLF, chcp 65001 first, %~dp0, python/py -3 fallback, %*, pause."
  - test: "Windows PC with no python and no py on PATH: double-click either .bat"
    expected: "The Korean install guidance with the python.org link appears and the window pauses."
    why_human: "Needs a Windows machine without Python."
  - test: "User's PC with Edge installed: run the weekly report with PDF enabled"
    expected: "Two PDFs are written (open them: first screen on one page, Korean fonts correct). An open old PDF produces the message about 이전 PDF, not a stale file."
    why_human: "PDF output was proven only with Chrome on Linux (/usr/bin/google-chrome). Edge paths, fonts and print layout on the user's PC are not testable here."
  - test: "Read the first screen of the 대표용 HTML (desk and phone widths)"
    expected: "Layout matches the D-14 order; units and notes are readable; no text feels like interpretation."
    why_human: "Visual quality and tone."
  - test: "Decide whether D-04 requires a count (not only an amount) for the undated schedule items on the first screen"
    expected: "The first-screen line '날짜 없는 입금예정 / 지급예정 38.8 / 105.0' shows amounts only. The counts (입금 2건, 지급 4건) appear only in section 2 and section 7."
    why_human: "D-04 says '첫 화면에도 건수·금액이 보여야 함'. The other three D-04 items (past-due receivable, past-due unprocessed, 프로젝트 밖 지급 날짜 없음) do show counts. If the count is required, this is a small second gap; if the amount alone is enough, accept."
  - test: "Judgment-tier prohibition PL-01: profit, cash balance, schedule and budget are never merged into one figure"
    expected: "Reviewer agrees the first-screen blocks stay separate."
    why_human: "Judgment-tier prohibition (non-authoritative verdict below)."
---

# Phase 1: 보고 엔진 검증 Verification Report

**Phase Goal:** 샘플 자료로 주간·월간, 대표용·경영관리용 보고가 사용자 규칙대로 나온다 (7개 묶음 계산·화면을 테스트로 고정)
**Verified:** 2026-11-02
**Status:** gaps_found
**Re-verification:** No, initial verification

## Summary

Engine, tests and outputs are in good shape. 74 of 74 unit tests pass, both CLI runs exit 0, and the CEO edition is free of the forbidden words. The two editions carry identical numbers, and all 보고 대조 rows read 일치.

One real gap remains against locked decision D-02. On the first screen, an unknown project request amount shows as 0.0, with no unknown count, in the project table, the 전체 total and the 프로젝트 요청 미지급 card. The detail section 3 shows the count correctly. Per the decision tree this makes the status `gaps_found`. The Windows-only checks are also still open for human verification.

## Commands run by the verifier

| Command | Result |
| --- | --- |
| `python3 -m unittest discover -s tests` | Ran 74 tests, OK, 0 skipped (the Chrome PDF test ran) |
| `python3 보고서.py 주간 --기준일 2026-11-02 --pdf 안함` | exit 0, 집계 기간 2026-10-27 ~ 2026-11-02, 2 HTML written |
| `python3 보고서.py 월간 --기준일 2026-10-31 --pdf 안함` | exit 0, 집계 기간 2026-10-01 ~ 2026-10-31, 2 HTML written |
| count of 위험/해결방안/권고/우려/추천 in both 대표보고.html | 0 / 0 / 0 / 0 / 0 (경영관리 edition has 위험 x4 and 해결방안 x3, only in the risk parts) |
| digit sequence of 대표 vs 경영관리, with the risk section removed (same rule as `numbers_of`) | equal for weekly (2307 numbers) and monthly (2304 numbers) |
| probe: blank 2026-11-02 운영계좌 잔액 and 예산_원가율 = 'abc' (scratchpad copy, via CLI) | exit 0. 현재 현금 212.3 with '잔액 미확인 1계좌 (합계 제외)' (3 times on the first screen); '예산 미책정 8건 (사전견적 없음 1건, 원가율 설정 오류 7건)'; 3 input issues; no forbidden words |

`git status` was clean after the runs. 출력/ is git-ignored. No source file was modified.

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | SC1: rule tests pass (transfer excluded, undated separated, unknown not 0, budget unspecified = 판단 불가, no card double count) | VERIFIED | 74 tests OK, including TestCash, TestSchedule, TestProjects, TestUnknownBalance, TestUnknownAmountsAndPastDue, TestProjectBudget, TestUserRulesLocked. Output spot-checks: 계좌간이체 is not a category (S1 분류별: 프로젝트지급, 카드대금, 회사공통지출). S6 states card unpaid is not re-added. P26204 shows '예산 미지정 / 판단 불가 / 사전견적 없음'. |
| 2 | SC2: digits equal between editions after removing the risk section | VERIFIED | Checked on the actual weekly and monthly files (True/True). `check_editions` sweep in the tests runs 8 probe inputs. |
| 3 | SC3: no 위험/해결방안/권고/우려/추천 in the 대표용 HTML | VERIFIED | grep on both files: 0 hits. Also 0 hits in the blank-balance and 'abc' rate probe. |
| 4 | SC4: all 보고 대조 rows 일치; first screen shows 표시/전체/합계 | VERIFIED | S7 table: 7 rows, all 일치 (이체 20,000,000 = 20,000,000, 기간 시작 잔액 558,000,000 = 558,000,000, and the rest). First screen: '표시 6건 / 전체 8건 ... 전체 원가 예산 465.5' and the 전체 8건 total row. |
| 5 | D-02: unknown values are not shown as 0; totals carry '미확인 N건' (user criterion: "unknowns shown as counts not 0") | FAILED | See gap. Holds for balances (잔액 미확인), vendors (진행팀 '미확인 1건'), past-due, 부가세, S5 invoices, S7 plan and contract, S4 profit (P26206 '판단 불가 (미확인 원가 1건)'). Fails on the first-screen project table, 전체 total and 프로젝트 요청 미지급 card for the unknown 진행팀 request line. |
| 6 | D-16: 원가 예산 = 사전견적 × 원가율 with visible 예산 사유; first screen '예산 미책정 N건 (사유별 건수)' | VERIFIED | P26201 210.0 = 300 x 0.70; P26204 '예산 미지정 (사전견적 없음)' with 판단 불가; total 465.5 and 1 missing; rate text '원가율 70%'; probe with rate 'abc' gives '예산 미책정 8건 (사전견적 없음 1건, 원가율 설정 오류 7건)'. 9 TestProjectBudget tests are green. |
| 7 | REP-01 / REP-03: one command (or .bat) writes weekly and monthly HTML; PDF when a browser exists; stale PDF guarded | VERIFIED on Linux; Windows pending | Both CLI runs exit 0. test_cli_pdf_when_browser_available ran and passed with Chrome. test_stale_pdf and test_locked_old_pdf pass. The launcher bytes were checked: UTF-8 without BOM, CRLF, chcp 65001 on line 2, `cd /d "%~dp0"`, python then py -3 fallback, `%PY% 보고서.py 주간 %*`, pause. `.gitattributes` has `*.bat text eol=crlf`. Windows execution is a human item. |
| 8 | D-04: undated, past-due and unprocessed amounts stay out of the graph and period totals and are shown with count and amount on the first screen | UNCERTAIN (warning) | Out of graph and totals: verified (S2 separate tables; min balance unchanged by past-due items). First screen shows '예정일 지난 미처리 입금 / 지급 1건 110.0 / 0건 0.0' and '프로젝트 밖 지급예정 584.1 · 날짜 없음 2건'. But '날짜 없는 입금예정 / 지급예정 38.8 / 105.0' and '입금예정일 경과 미수 110.0' have no counts. Human decision requested. |

**Score:** 6/8 truths verified (1 FAILED, 1 UNCERTAIN)

### Locked Decisions D-01..D-16

| Decision | Status | Evidence |
| --- | --- | --- |
| D-01 profit / cash / schedule / budget kept apart | VERIFIED | S4 text: '이익과 현금잔액은 별개 지표'. The first-screen KPI block (cash) has no profit figure; profit is in its own '매출·이익' block. |
| D-02 unknown is None, shown with count | PARTIAL | See gap (first screen, project requests). |
| D-03 inter-account transfer excluded and matched | VERIFIED | S1: '계좌 간 이체 20,000,000 / 20,000,000' and the 대조 row 일치. |
| D-04 undated, past-due and unprocessed shown separately | PARTIAL | See truth 8. |
| D-05 unconfirmed receipts are estimates | VERIFIED | 수금 rows with unconfirmed date are 추정 (S2 rows P26205, P26204, P26207). |
| D-06 budget unspecified = 미지정 / 판단 불가; remaining = '집행계획 미등록 금액' | VERIFIED | Present on the first screen note ① and in S3. P26208 remaining 13,650,000 creates no schedule event. |
| D-07 supply value vs actual outflow with VAT; cards at total | VERIFIED | S3 has '지급 실출금(VAT포함)' (P26201 77,000,000 vs 70,000,000) and 카드 total. |
| D-08 no double count of card or project payments | VERIFIED | S6 keeps 카드사용미결제 out of the vendors (no 법인카드 5860 row); 584.1 contains no 프로젝트집행 line; 사운드랩 counted once at 44.0. |
| D-09 unknown cost not zeroed in profit | VERIFIED | P26206 종료 시점 예상이익 '판단 불가 (미확인 원가 1건)'; 인트라넷 P26206 직접비 '미확인'. |
| D-10 WEHAGO and 인트라넷 완료보고 profit separate | VERIFIED | Two tables in S4, with different 최근 반영월 (2026-11 and 2026-10). |
| D-11 unissued days only with a completion date | VERIFIED | P26205 43일; P26201/03/04/07 '완료일 미확인'. |
| D-12 shown / total / sum together; summary vs detail 대조 | VERIFIED | '표시 6건 / 전체 8건', plus a 대조 row '첫 화면 표시 + 나머지 = 전체 합계 529,950,000'. |
| D-13 CEO edition has no interpretation; both editions share one compute | VERIFIED | Truths 2 and 3. |
| D-14 one-page layout (KPI, project + graph, 4 bottom blocks, details 1-7) | VERIFIED | First screen text order matches; TOC lists 상세자료 1-7. |
| D-15 Python 3.8+ stdlib only, CSV in, HTML + PDF out, weekly and monthly | VERIFIED | Imports are stdlib only (argparse, calendar, csv, datetime, html, math, os, re, shutil, subprocess, sys, collections). No removeprefix, `:=`, match or dict-union in the engine. |
| D-16 budget = estimate x rate, with reasons | VERIFIED | Truth 6. |

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `ceo_report/util.py` | is_blank, setting_num | VERIFIED | Imported by calc.py; tests pass. |
| `ceo_report/data.py` | settings_line, estimate / estimate_raw, DEFAULT_SETTINGS 예산_원가율 | VERIFIED | Used by calc (budget_reason, settings fallback). |
| `ceo_report/calc.py` | bal_unknown, past_*_unknown, vat_unknown_n, budget_reason, no_budget_reasons, plan_unknown | VERIFIED | All are rendered (see key links). |
| `ceo_report/render.py` | fact lines for unknowns, 등록분 전체, 백만원 unit, 예산 미책정 | VERIFIED, with one omission | The first-screen project table and 요청 미지급 card do not render the project unknown count (the gap). |
| `보고서.py` | to_pdf removes old PDF first | VERIFIED | Tests (d) and (e) pass; there is no `shell=True`. |
| `실행_주간.bat`, `실행_월간.bat` | launchers | VERIFIED (static) | `file` reports UTF-8 text with CRLF; first bytes `40 65 63` (no BOM). |
| `.gitattributes` | `*.bat text eol=crlf` | VERIFIED | Present. |
| `tests/test_report.py` | 74 tests | VERIFIED | OK. |

### Key Link Verification

| From | To | Via | Status |
| --- | --- | --- | --- |
| calc s1 bal_unknown | render KPI, heading, S1, S2 | `_bal_note` | WIRED (3 first-screen hits in the probe) |
| calc s2 past_*_unknown | render first-screen kv | `_past_side` | WIRED |
| calc s2 vat_unknown_n* | render KPI, min-balance lines, S2 rows | | WIRED |
| calc settings_num / settings_default | render risk section; 입력 확인 | | WIRED (the probe listed 3 issues) |
| calc s3 no_budget_reasons / cost_rate | render first-screen total row, S3, S7 | | WIRED |
| calc s3 per-project unknown (요청 미지급) | render first-screen project table | | NOT_WIRED (the gap; S3 detail is wired) |
| 실행_*.bat | 보고서.py | `%PY% 보고서.py 주간/월간 %*` | WIRED (static) |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
| --- | --- | --- | --- | --- |
| First screen KPIs and tables | R["s1".."s7"] | calc.compute from the CSVs in 입력/ | Yes (probe changes alter the output) | FLOWING |
| First-screen project 요청 미지급 | P["requested"] | known sum only; unknown count not passed on | Partial | HOLLOW for unknown count |

### Requirements Coverage

All 24 IDs appear in the PLAN frontmatter and all are mapped to Phase 1 in REQUIREMENTS.md. There are no orphans. The 01-01 plan claims CASH-01, CASH-02, PLAN-02, PLAN-03, PROJ-02, PROJ-04, AP-02, DATA-03, REP-02; the 01-02 plan claims CASH-03, PLAN-01, PLAN-02, PROJ-01, PROJ-02, PROJ-03, PL-01, PL-02, PL-03, AR-01, AR-02, AR-03, AP-01, DATA-01, DATA-02, REP-01, REP-03. The union is exactly CASH-01..03, PLAN-01..03, PROJ-01..04, PL-01..03, AR-01..03, AP-01..02, DATA-01..03, REP-01..03.

| Req | Status | Evidence |
| --- | --- | --- |
| CASH-01 | SATISFIED | S1 balances, restriction 30.0, available 542.4; blank-balance probe excludes the account and says so. |
| CASH-02 | SATISFIED | S1 start 558.0 = bank 558.0, transfer excluded and matched. |
| CASH-03 | SATISFIED | 프로젝트지급 20.2 / 회사공통지출 8.0 / 카드대금 12.4 = 40.6. |
| PLAN-01 | SATISFIED | 4 weekly buckets then monthly to 2027-05, 확정 and 추정 separate. |
| PLAN-02 | SATISFIED | 최저 계산 잔액 19.8 (확정) and 148.3 (확정+추정), both 2027-04-25, on the first screen. |
| PLAN-03 | SATISFIED | Separate tables; the first screen shows the past-due line. See truth 8 for the count question. |
| PROJ-01 | SATISFIED | S3 columns checked in the output. |
| PROJ-02 | SATISFIED | 70.0 supply vs 77.0 actual for P26201. |
| PROJ-03 | SATISFIED | P26204 and the four reasons (probe + tests). |
| PROJ-04 | SATISFIED | '표시 6건 / 전체 8건' plus the total row. |
| PL-01 | SATISFIED | 2026-11: 매출 30.0, 직접비 20.4, 이익 9.6, 공통비 30.0, 공통비 차감 −20.4 (잠정); 연누적 1,380.0 / 111.6. |
| PL-02 | SATISFIED | Two source tables. |
| PL-03 | SATISFIED | 미반영 618.0; P26206 판단 불가. |
| AR-01 | SATISFIED | 828.0 / 358.0 / 470.0 / 228.8; P26202 is 33 days late. |
| AR-02 | SATISFIED | P26205 43일; the others show no days. |
| AR-03 | SATISFIED | '선수금·취소·환불·수정 (4건)'. |
| AP-01 | SATISFIED | S6 categories; 급여 270,000,000. |
| AP-02 | SATISFIED | S6 vendor table with nearest date; 584.1 has no 프로젝트집행 line. |
| DATA-01 | SATISFIED | 3 changes; 계획 외 지급 3,700,000. |
| DATA-02 | SATISFIED | 예산 미지정, 미연결 지급, 날짜 없음 105.0 (4건), 자료 기준일 x3, 원천자료 차이 x2. |
| DATA-03 | SATISFIED | 7 대조 rows plus an issue list (P26999). |
| REP-01 | SATISFIED on Linux | Windows double-click is a human item. |
| REP-02 | SATISFIED | Truths 2 and 3. |
| REP-03 | SATISFIED on Linux | Windows, Edge and the PC are human items. |

### Prohibitions (ADR-550)

| Prohibition | Tier | Status |
| --- | --- | --- |
| REP-02 no interpretation words in 대표용 | test | VERIFIED. Wired in `check_editions` and the 8-input sweep; re-confirmed on the output files. |
| CASH-01 no unknown shown or summed as 0 | test | VERIFIED for the covered cases, but the first screen still fails one case (the gap). The test does not cover it. |
| PROJ-04 no top-N presented as all | test | VERIFIED. |
| PLAN-03 no invented date for undated or past-due amounts | test | VERIFIED. |
| PROJ-03 no budget from blank, zero, negative or unreadable estimate or invalid rate | test | VERIFIED (4 reasons + probe). |
| PL-01 profit, cash, schedule and budget not merged | judgment | unverified-prohibition: human review recommended. Non-authoritative LLM-judge verdict: PASS (the blocks are separate and the S4 text states the separation). Listed in human_verification. |

### Behavioral Spot-Checks

Covered under "Commands run by the verifier" above.

### Probe Execution

Step 7c: SKIPPED. No `scripts/*/tests/probe-*.sh` exists and the plans declare none.

### Anti-Patterns Found

Debt-marker grep on the files this phase modified (TBD, FIXME, XXX), on the pass-through `or 0` pattern, and on stubs.

| File | Pattern | Severity | Impact |
| --- | --- | --- | --- |
| `ceo_report/render.py` (about 207-229, 248-251) | known-only sum shown with no unknown count | Blocker (the gap) | A 0.0 on the first screen for an unknown amount |
| `ceo_report/render.py` | `-68.0%` (hyphen) next to `−20.4` (U+2212) | Info | Cosmetic inconsistency in the sign character on 이익률 |
| `ceo_report/render.py` | KPI says '은행 기준일 2026-10-26' in the monthly run while the 자료 기준일 block says '은행 잔액 확인 2026-11-02' | Info | Not wrong (the snapshot on or before the 기준일 is used), but a reader may wonder |

No unreferenced TBD, FIXME or XXX markers were found.

### Deferred Items

None. Phase 2 and Phase 3 do not cover this gap. Phase 01.1 (payment approval) reuses `calc.compute` and would inherit the same first-screen omission only if it renders project totals.

### Human Verification Required

See the `human_verification` frontmatter. Summary:
1. Windows double-click of both .bat files (output, Korean text, pause).
2. Windows without Python: install guidance appears.
3. Edge PDF on the user's PC.
4. Visual and tone read of the first screen.
5. Decision on first-screen counts for undated schedule items (D-04).
6. Judgment-tier prohibition PL-01.

### Gaps Summary

One gap blocks a clean pass. The first screen shows a project with an unknown request amount (P26206, 진행팀) as 요청·카드 미결제 0.0 and 예상 잔여예산 2.0. The 전체 total and the 프로젝트 요청 미지급 card give no unknown count. This conflicts with D-02 and the explicit user criterion "unknowns shown as counts not 0". The detail section 3 does it right, so the fix is rendering only: pass the per-project and total unknown counts that calc already holds to the first screen, and add one test that blanks a 요청미지급 amount and checks the first screen. A closure plan via `/gsd-plan-phase --gaps` should be small.

Everything else in the phase goal is evidenced in the code and in generated output. If the D-04 count question is answered "counts required", add the undated 입금/지급 counts to the same closure plan.

---

_Verified: 2026-11-02_
_Verifier: Claude (gsd-verifier)_
