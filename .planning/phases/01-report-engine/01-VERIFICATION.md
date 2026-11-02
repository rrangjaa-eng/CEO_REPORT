---
phase: 01-report-engine
verified: 2026-11-02T08:20:00Z
status: human_needed
score: 8/8 must-haves verified
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
covered_digest: "v1:sha256:9e430a5557ff2609db4d8e88c3a97c49b0a313a1a5966dbd75c4cc96c5b0731d"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 6/8
  gaps_closed:
    - "D-02 / SC1: first-screen project table, 전체 total and 프로젝트 요청 미지급 card now show an unknown 진행팀 request as '미확인 1건' / '외 미확인 1건' (not 0)"
    - "D-04: first-screen undated 입금/지급 and 입금예정일 경과 미수 lines now carry counts as well as amounts"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Windows PC with Python 3.8+: double-click 실행_주간.bat, then 실행_월간.bat"
    expected: "Console shows '만든 파일:' with 출력\\...주간/월간_대표보고.html and _경영관리보고.html (plus .pdf with Edge), Korean text readable (chcp 65001), final line '결과 파일은 출력 폴더에 있습니다.', window waits for a key. After a forced failure (for example a missing 입력 folder) it shows '오류가 발생했습니다' and NOT the success line."
    why_human: "cmd.exe cannot run on this Linux host. Only the file bytes and the static launcher test were checked (UTF-8 no BOM, CRLF, chcp 65001 first, %~dp0, python/py -3 lookup with a 3.8 version check, %*, success line only when RC is 0, pause)."
  - test: "Windows PC with no python/py on PATH, and one with only Python older than 3.8 (if available): double-click either .bat"
    expected: "Korean install guidance with the python.org link (or the 'lower than 3.8' message) appears and the window pauses."
    why_human: "Needs a Windows machine in that state."
  - test: "User's PC with Edge installed, Edge possibly already open: run the weekly report with PDF enabled"
    expected: "Two PDFs are written (first screen on one page, Korean fonts correct). An open old PDF produces the '이전 PDF' message, not a stale file. A browser that is already running does not swallow the headless print (dedicated temp profile)."
    why_human: "PDF output was proven only with Chrome on Linux (test_cli_pdf_when_browser_available ran and passed). Edge paths, fonts, print layout and the already-running-browser case on the user's PC cannot be tested here."
  - test: "Open the 대표용 first screen at desk width and at phone width"
    expected: "Layout matches the D-14 order (KPI, project table + chart, four bottom blocks, 상세자료 1-7); the 6-row project table and the long 미확인 / 판단 불가 notes in cells stay readable; no text reads like interpretation."
    why_human: "Visual quality and tone. The repo-root desk_*.png / phone_*.png screenshots predate the review fixes and were not regenerated here."
  - test: "Judgment-tier prohibition PL-01: profit, cash balance, schedule and budget are never merged into one figure"
    expected: "Reviewer agrees the first-screen blocks (현금 KPI, 프로젝트 예산·지급, 매출·이익, 미수·미지급) stay separate."
    why_human: "Judgment-tier prohibition. Non-authoritative LLM-judge verdict: PASS (separate blocks, S4 states 이익과 현금잔액은 별개 지표). Flagged unverified-prohibition, human review recommended."
---

# Phase 1: 보고 엔진 검증 Verification Report

**Phase Goal:** 샘플 자료로 주간·월간, 대표용·경영관리용 보고가 사용자 규칙대로 나온다 (7개 묶음 계산·화면을 테스트로 고정)
**Verified:** 2026-11-02
**Status:** human_needed
**Re-verification:** Yes, after the review fixes CR-01..03, WR-01..06, the first-screen unknown-cost gap fix and the D-04 first-screen counts

## Summary

The previous gap (an unknown 진행팀 request amount shown as 0.0 on the first screen) is closed, and no new gap was found. No source file was changed by this verification, and `git status` was clean after all runs.

- 118 of 118 unit tests pass (74 at the previous verification).
- Both CLI runs exit 0, and both editions carry identical numbers.
- The 대표용 edition has none of the five forbidden words.
- Every 보고 대조 row reads 일치.
- Every unknown value I probed stays unknown on the first screen (counts or 미확인 / 판단 불가), never 0.

The status is `human_needed` because the Windows-only and user-PC checks listed in the frontmatter cannot be run here. There are no failing truths.

## Commands run by the verifier

| Command | Result |
| --- | --- |
| `python3 -m unittest discover -s tests` | Ran 118 tests, OK, 0 skipped (the Chrome PDF test ran) |
| `python3 보고서.py 주간 --기준일 2026-11-02 --pdf 안함` (output to scratchpad) | exit 0, 집계 기간 2026-10-27 ~ 2026-11-02, 2 HTML written |
| `python3 보고서.py 월간 --기준일 2026-10-31 --pdf 안함` | exit 0, 집계 기간 2026-10-01 ~ 2026-10-31, 2 HTML written |
| forbidden-word count in both 대표보고.html (위험/해결방안/권고/우려/추천) | 0 / 0 / 0 / 0 / 0 (경영관리 edition: 위험 x4, 해결방안 x3, only in the risk parts) |
| digit sequence of 대표 vs 경영관리 (risk section and 위험 항목 note removed, same rule as `numbers_of`) | equal: weekly 2321 numbers, monthly 2318 numbers |
| 9 probes run through the CLI on copies of 입력/ (see below) | all exit 0; each probe: no forbidden word in 대표용, numbers equal across editions, 0 '불일치' |
| `ast.parse(..., feature_version=(3, 8))` on engine, CLI, tools, tests | OK (D-15) |

Probes (scratchpad copies, one cell changed each; the probe files were closed before the CLI ran):

| Probe | First-screen result |
| --- | --- |
| blank 2026-11-02 운영계좌 잔액 | 현재 현금 212.3, 사용 가능액 182.3; '잔액 미확인 1계좌 (합계 제외)' 3 times on the first screen (KPI x2, chart heading); input issue '잔액 미확인 (운영계좌)' |
| all three balances blank | 현재 현금 / 사용 가능액 '미확인'; chart says '잔액 미확인 — 계산 잔액 선은 그리지 않음'; both minimum-balance lines '잔액 미확인'; no fabricated 0 |
| 예산_원가율 = 'abc' / '0' / '1.5' | '예산 미책정 8건 (사전견적 없음 1건, 원가율 설정 오류 7건)'; every row '예산 미지정 (원가율 설정 오류)' and 판단 불가; 전체 원가 예산 판단 불가; input issue '예산_원가율 값 오류' on 설정.csv line 9 |
| 예산_원가율 blank | default 70% used; 465.5; input issue '예산_원가율 설정 비어 있음 → 기본값 사용(0.70)' |
| 사전견적 P26208 = 0, P26207 = −5,000,000, P26205 = '약 4500만' | '예산 미책정 4건 (사전견적 없음 1건, 사전견적 0원 또는 음수 2건, 사전견적 금액 해석 불가 1건)'; per-row reason shown |
| all 요청미지급 amounts blank | card '프로젝트 요청 미지급 미확인 4건', not 0; 전체 row '3.5 외 미확인 4건', '미확인 원가 3개 프로젝트 제외' |
| all 지급완료 부가세 blank | section 3 '지급 실출금(VAT포함)' column reads '부가세 미확인' per project and '부가세 미확인 7건' in the total, not 0 |

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | SC1: rule tests pass (transfer excluded, undated separated, unknown not 0, budget unspecified = 판단 불가, no card double count) | VERIFIED | 118 tests OK, including TestCash, TestSchedule, TestProjects, TestUnknownBalance, TestUnknownAmountsAndPastDue, TestProjectBudget, TestUserRulesLocked and the CR-01..03 / WR tests. In the output, 계좌간이체 is not a category (분류별: 프로젝트지급 20.2, 카드대금 12.4, 회사공통지출 8.0 = 40.6 출금 합계). The 584.1 프로젝트 밖 지급 has no 프로젝트집행 line. |
| 2 | SC2: digits equal between editions after removing the risk section | VERIFIED | Independent regex on the real weekly and monthly files: True / True. Also True on all 9 probe outputs. |
| 3 | SC3: no 위험/해결방안/권고/우려/추천 in the 대표용 HTML | VERIFIED | 0 hits in weekly, monthly and all 9 probe outputs (including the new 잔액 미확인, 부가세 미확인, 예산 미책정 and 원가율 설정 오류 wording). |
| 4 | SC4: all 보고 대조 rows 일치; first screen shows 표시 / 전체 / 합계 | VERIFIED | Weekly: 7 rows all 일치 (이체 20,000,000 = 20,000,000, 기간 시작 잔액 558,000,000 = 558,000,000, 표시 + 나머지 = 전체 529,950,000, 예정 일정 합계 1,367,900,000). Monthly: 6 rows all 일치 (no opening snapshot at month start, so the start-balance check is skipped by design). First screen: '표시 6건 / 전체 8건 ... 전체 원가 예산 465.5' plus the 전체 8건 row. |
| 5 | D-02: unknown values never shown as 0; totals carry '미확인 N건' | VERIFIED | The previous gap is closed. Sample first screen: P26206 row reads 요청·카드 미결제 '미확인 1건', 지급률 '92.9% (미확인 원가 1건)', 예상 잔여예산 '판단 불가 (미확인 원가 1건)'. 전체 row: '98.5 외 미확인 1건' and '−48.5 · 미확인 원가 1개 프로젝트 제외'. Card: '프로젝트 요청 미지급 95.0 외 미확인 1건'. Also holds for 계약 중 매출 미반영 ('618.0 외 미확인 1건'), 계약금액 ('828.0 외 미등록 1건'), 미발행금액 ('470.0 외 판단 불가 1건'), account balances, VAT, and all the all-unknown probes above. Tests test_unknown_request_line_marked_on_first_screen, test_total_remaining_excludes_unknown_cost_projects and test_partial_unknown_counts_beside_first_screen_totals pin it. |
| 6 | D-16: 원가 예산 = 사전견적 × 원가율, visible 예산 사유, first screen '예산 미책정 N건 (사유별 건수)' | VERIFIED | P26201 210.0 = 300 × 0.70; 전체 원가 예산 465.5; '예산 미책정 1건 (사전견적 없음 1건)'; rate text '원가율 70%'; P26204 '예산 미지정 (사전견적 없음)' with 지급률 and 잔여 '판단 불가'; the four reasons and the rate-error case proven by probes above; section 3 has the 예산 사유 column. The 남은 예산 is labelled '집행계획 미등록 금액' and creates no schedule event (P26208 13,650,000). |
| 7 | REP-01 / REP-03: one command or .bat writes weekly and monthly HTML; PDF when a browser exists; stale PDF guarded | VERIFIED on Linux; Windows pending (human) | Both CLI runs exit 0. test_cli_pdf_when_browser_available ran and passed with Chrome. test_stale_pdf and test_locked_old_pdf pass. Launchers: UTF-8 without BOM, CRLF, `.gitattributes` has `*.bat text eol=crlf`, chcp 65001 on line 2 before any Korean text, `cd /d "%~dp0"`, python or `py -3` lookup with a Python 3.8 version check, `%PY% 보고서.py 주간 %*`, success line only when RC is 0, `pause`. No `shell=True` in 보고서.py. |
| 8 | D-04: undated, past-due and unprocessed amounts stay out of the graph and period totals and show count and amount on the first screen | VERIFIED | First screen: '날짜 없는 입금예정 / 지급예정 2건 38.8 / 4건 105.0', '입금예정일 경과 미수 (일정 미포함) 1건 110.0', '예정일 지난 미처리 입금 / 지급 (일정 미포함) 1건 110.0 / 0건 0.0', '프로젝트 밖 지급예정 (등록분 전체) 584.1 · 날짜 없음 2건'. The old D-04 question (counts for undated items) is resolved by f913e7c. Out of the graph and minimum balance: 최저 계산 잔액 19.8 (확정) / 148.3 (확정+추정), both 2027-04-25, unchanged. |

**Score:** 8/8 truths verified (0 present-but-behavior-unverified). The Windows and user-PC parts of truth 7 are in the human list.

### Review findings re-checked against the code

| Finding | Check | Result |
| --- | --- | --- |
| CR-01 no known balance is not 0 cash | allbal probe (all three balances blank) | 현재 현금 / 사용 가능액 '미확인', no balance line in the chart, minimum '잔액 미확인' |
| CR-02 unknown cost lines vs remaining budget | sample first screen | P26206 잔여 '판단 불가 (미확인 원가 1건)'; 전체 row leaves it out and says so |
| CR-03 all-unknown totals | allvat and allreq probes | '부가세 미확인 7건', '미확인 4건', never 0 |
| WR-01 invalid --시작일 | tests (test suite) | covered by RED/GREEN pair aa2ed15; passes |
| WR-02 PDF profile, file URI, no Windows --no-sandbox, empty-file reject | Chrome PDF test passes; Windows/Edge case is human | |
| WR-03 blank 입금액 with 입금일 | calc.py lines 257-261: outstanding is None, not full amount | fixed |
| WR-04 read_csv line breaks | tests pass | fixed |
| WR-05 launcher success line and Python 3.8 check | file read | fixed (static); Windows run is human |
| WR-06 compute() does not mutate Data | tests pass | fixed |
| IN-01, IN-02, IN-03 | not attempted (optional); IN-04 partial | see Info below |

### Locked Decisions D-01..D-16

| Decision | Status | Evidence |
| --- | --- | --- |
| D-01 profit / cash / schedule / budget kept apart | VERIFIED (judgment item PL-01 listed for human review) | Separate first-screen blocks; S4 states '이익과 현금잔액은 별개 지표'. |
| D-02 unknown is None, shown with count | VERIFIED | Truth 5. |
| D-03 inter-account transfer excluded and matched | VERIFIED | '계좌 간 이체 20,000,000 / 20,000,000', 대조 row 일치. |
| D-04 undated, past-due, unprocessed shown separately with count and amount | VERIFIED | Truth 8. |
| D-05 unconfirmed receipts are estimates | VERIFIED | test_unconfirmed_receipt_is_estimate and S2 확정/추정 split (확정 88.0 · 추정 22.0). |
| D-06 budget unspecified = 미지정 / 판단 불가; remaining = '집행계획 미등록 금액' | VERIFIED | Truth 6; first-screen note ① and section 3. |
| D-07 supply value vs actual outflow with VAT; cards at total | VERIFIED | Section 3 '지급 실출금(VAT포함)' 77,000,000 vs 70,000,000 for P26201. |
| D-08 no double count of card or project payments | VERIFIED | 584.1 has no 프로젝트집행 line; card unpaid 3.5 shown once; test_nonproject_payments_not_double_counted. |
| D-09 unknown cost not zeroed in profit | VERIFIED | P26206 예상이익 '판단 불가 (미확인 원가 1건)' (tests pass). |
| D-10 WEHAGO and 인트라넷 완료보고 profit separate | VERIFIED | Two tables in S4 (test_pl_sources_separate). |
| D-11 unissued days only with a completion date | VERIFIED | P26205 43일; P26201 '완료일 미확인' (test passes). |
| D-12 shown / total / sum together; summary vs detail 대조 | VERIFIED | Truth 4. |
| D-13 CEO edition has no interpretation; both editions share one compute | VERIFIED | Truths 2 and 3. 경영관리 adds only the '위험 분석·해결방안' section (13 items, 2 high) and one summary line. |
| D-14 one-page layout | VERIFIED (visual check is human) | First-screen text order: KPI, project table, chart, schedule lines, 매출·이익, 미수·미지급, 계산서 미발행, 자료 기준일; then 상세자료 1-7. |
| D-15 Python 3.8+ stdlib only, CSV in, HTML + PDF out, weekly and monthly | VERIFIED | Imports are stdlib only (argparse, datetime, os, pathlib, shutil, subprocess, sys, tempfile, csv, io, re, html, math, calendar, collections). All sources parse with feature_version 3.8. |
| D-16 budget = estimate × rate, with reasons | VERIFIED | Truth 6. |

### Edition split (CEO facts only vs 경영관리 with risks)

The 대표용 and 경영관리용 first screens differ by exactly two things: the title line, and the added summary line '위험 항목 13건 (높음 2건) — ...' plus the '위험 분석·해결방안 (경영관리 전용)' table (13 rows, each with 등급 / 영역 / 근거 / 해결방안). Everything else, including all unknown-value wording, is identical text. The 대표용 file contains no risk, recommendation or concern wording.

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `ceo_report/util.py` | is_blank, setting_num, tolerant CSV reading | VERIFIED | Used by calc and data; tests pass. |
| `ceo_report/data.py` | settings_line, estimate / estimate_raw, DEFAULT_SETTINGS 예산_원가율 | VERIFIED | Used by calc. |
| `ceo_report/calc.py` | confirmed-only balances, unknown counts, budget_reason, no_budget_reasons, plan_unknown | VERIFIED | All rendered. |
| `ceo_report/render.py` | fact lines for unknowns, 등록분 전체, 백만원 unit, 예산 미책정, first-screen project unknown counts | VERIFIED | The previous omission is fixed. |
| `보고서.py` | to_pdf removes old PDF, temp profile, URI, size check; --시작일 validation | VERIFIED | Tests pass; no `shell=True`. |
| `실행_주간.bat`, `실행_월간.bat` | launchers | VERIFIED (static) | `file`: UTF-8 text with CRLF; first bytes `40 65 63` (no BOM). |
| `.gitattributes` | `*.bat text eol=crlf` | VERIFIED | Present. |
| `tests/test_report.py` | rule tests | VERIFIED | 118 tests OK. |

### Key Link Verification

| From | To | Via | Status |
| --- | --- | --- | --- |
| calc s1 bal_unknown | render KPI, chart heading, S1, S2 | `_bal_note` | WIRED (3 first-screen hits in the blank-balance probe) |
| calc s2 past_*_unknown | render first-screen lines | `_past_side` | WIRED |
| calc s2 vat_unknown_n* | render KPI, minimum-balance lines | | WIRED |
| calc s3 per-project and total unknown_cost / requested unknown | render first-screen project table and 요청 미지급 card | | WIRED (previously NOT_WIRED) |
| calc settings_num / settings_default | render risk section, 입력 확인 | | WIRED |
| calc s3 no_budget_reasons / cost_rate | render first-screen total row, S3, S7 | | WIRED |
| 실행_*.bat | 보고서.py | `%PY% 보고서.py 주간/월간 %*` | WIRED (static) |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
| --- | --- | --- | --- | --- |
| First-screen KPIs and tables | R["s1".."s7"] | calc.compute from the CSVs | Yes (every probe changed the output as expected) | FLOWING |
| First-screen project 요청·카드 미결제 / 잔여 | P["requested"], P["unknown_cost"] | calc | Yes, unknown count now passed to render | FLOWING |

### Requirements Coverage

All 24 IDs are claimed by the PLAN frontmatter of 01-01 and 01-02 and mapped to Phase 1 in REQUIREMENTS.md. No orphans.

| Req | Status | Evidence |
| --- | --- | --- |
| CASH-01, CASH-02 | SATISFIED | Balances 572.4 / 542.4; blank-balance probes; transfer and start-balance 대조 일치. |
| CASH-03 | SATISFIED | 프로젝트지급 20.2 / 회사공통지출 8.0 / 카드대금 12.4 = 40.6. |
| PLAN-01, PLAN-02, PLAN-03 | SATISFIED | 4 weekly buckets then monthly; minimum 19.8 / 148.3 on 2027-04-25; separate tables plus first-screen lines with counts. |
| PROJ-01..04 | SATISFIED | Columns present; 70.0 vs 77.0; P26204 reasons; 표시 6건 / 전체 8건. |
| PL-01..03 | SATISFIED | Two source tables, 618.0 미반영 외 미확인 1건, P26206 판단 불가. |
| AR-01..03 | SATISFIED | 828.0 외 미등록 1건 / 358.0 / 470.0 외 판단 불가 1건 / 228.8; P26205 43일; specials listed. |
| AP-01, AP-02 | SATISFIED | Category totals; vendor table with unknown counts. |
| DATA-01..03 | SATISFIED | Changes, 예산 미지정, 날짜 없음 105.0 (4건), 대조 rows all 일치, input issue list. |
| REP-01, REP-03 | SATISFIED on Linux | Windows and Edge are human items. |
| REP-02 | SATISFIED | Truths 2 and 3. |

### Prohibitions (ADR-550)

| Prohibition | Tier | Status |
| --- | --- | --- |
| REP-02 no interpretation words in 대표용 | test | VERIFIED. Wired in `check_editions` and the 8-input sweep; re-confirmed on 11 output files. |
| CASH-01 no unknown shown or summed as 0 | test | VERIFIED, including the first-screen case that failed before. |
| PROJ-04 no top-N presented as all | test | VERIFIED. |
| PLAN-03 no invented date for undated or past-due amounts | test | VERIFIED. |
| PROJ-03 no budget from blank, zero, negative or unreadable estimate or invalid rate | test | VERIFIED (4 reasons + 3 invalid-rate probes). |
| PL-01 profit, cash, schedule and budget not merged | judgment | unverified-prohibition: human review recommended. Non-authoritative LLM-judge verdict: PASS. Listed in human_verification. |

### Behavioral Spot-Checks

See "Commands run by the verifier". No server is needed; all checks ran against the CLI and the generated HTML.

### Probe Execution

Step 7c: SKIPPED. No `scripts/*/tests/probe-*.sh` exists and the plans declare none. The CLI probes above are ad-hoc input probes, not declared project probes.

### Anti-Patterns Found

Scanned the engine, CLI, tools, tests and launchers.

| File | Pattern | Severity | Impact |
| --- | --- | --- | --- |
| all modified files | TBD / FIXME / XXX | none found | clean |
| `ceo_report/calc.py` 186, 261, 328, 507 | `or 0` | Info | Each is guarded (the VAT or paid value is only defaulted after a None check, or is a sort key). Not a stub. |

### Info (non-blocking)

- IN-01 (reported by the code review, not fixed): several 보고 대조 rows compare values built from the same list, so they can never read 불일치 ('분류별 입금 합', '프로젝트집행 줄 수', '표시 + 나머지', parts of '예정 일정 합계'). Only the transfer and start-balance checks catch real input problems. SC4 ("all 대조 일치") is met, but 일치 on those rows is weaker assurance than it looks.
- IN-02 (dead `/opt/pw-browsers` path in find_browser) and IN-03 (U+2212 minus not read back by `num()`) not fixed. Harmless on the target.
- IN-04 partial: tests clean up temp folders with `addCleanup`, but `setUpModule` still rewrites the committed `입력/` (deterministic, so `git status` stays clean).
- The first-screen scope line reads '원가율 원가율 설정 오류' when the rate is invalid (cosmetic repeat).
- MVP mode: ROADMAP marks Phase 1 `Mode: mvp` but the goal line is not in `As a ..., I want to ..., so that ...` form (the planner noted this and did not invent a story). This verification used the plain goal-backward method. Run `/gsd mvp-phase 1` if a user-story goal is wanted.

### Deferred Items

None. The previous gap is closed in this phase. Phase 01.1 (payment approval screen) reuses `calc.compute` and now inherits the corrected unknown handling.

### Human Verification Required

See the `human_verification` frontmatter:

1. Windows double-click of both .bat files, including a forced failure to confirm the failure message.
2. Windows without Python, and with Python older than 3.8.
3. Edge PDF on the user's PC, with Edge already open.
4. Visual and tone check of the first screen at desk and phone width.
5. Judgment-tier prohibition PL-01.

### Gaps Summary

No gaps. The phase goal is achieved in the codebase for the sample data on this host. What remains is confirmation on the user's own Windows PC (launchers, Edge PDF) and a visual read of the first screen.

---

_Verified: 2026-11-02_
_Verifier: Claude (gsd-verifier)_
