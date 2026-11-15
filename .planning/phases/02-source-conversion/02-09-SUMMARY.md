---
phase: 02-source-conversion
plan: 09
subsystem: source-conversion
tags: [monthly-report, section-8, wehago, 위하고대조, xchk, d-44, d-48, d-49, rep-02, tdd, python-stdlib]
status: complete

requires:
  - phase: 02-source-conversion
    provides: "02-06 convert_xchk.load_xchk (state / reason / meta / status / projects / outside / unlinked / vendors / revenue / cash / totals) and the 위하고대조.csv fixture helpers"
provides:
  - "ceo_report/render.py: _s8(R, mode) monthly section 8 'WEHAGO 기준 대조' (h2 id s8, TOC link for monthly only); summary in both editions, <div id='xchk-detail'> ... <!-- /xchk-detail --> detail tables in 경영관리용 only"
  - "보고서.py: R['xchk'] = load_xchk(입력) for monthly runs only (import inside the monthly branch) and one console line when the facts file is missing or unreadable"
  - "tests/test_monthly_xchk.py: weekly_baseline(test, input_dir) via git archive cbc5497, pages_for / table_cells / summary_rows helpers; tests/test_report.py: rep02_probes(test), numbers_of drops the xchk-detail block"
affects: [02-10]

plan_head_before: 9ae46a42b083ac71a7b536f028fa1c4e51636a57
actuals:
  tokens: 16965
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - "Summary = one table (id xchk-summary) of text rows, label + value; label and value together read as the plan's truth lines ('프로젝트 미연결 원가 2줄 1,100,000')"
    - "Unknowns: '판단 불가' (+ '(미확인 N건)' parsed from 비고) for amounts, '미등록' for blank 계약금액; a known empty set reads '0건' / '-' (never a guess)"
    - "Detail block markers are the contract with tests/test_report.numbers_of (REP-02 stays true for the summary numbers)"
    - "No CSS change: section 8 uses existing classes plus inline style on its own elements, so the weekly HTML stays byte-identical to cbc5497"

key-files:
  created:
    - tests/test_monthly_xchk.py
  modified:
    - ceo_report/render.py
    - 보고서.py
    - tests/test_report.py

key-decisions:
  - "Summary labels follow the truth lines literally: '거래처 미지급' (not R-1's '거래처 미지급 대조') so label + value reads '거래처 미지급 비교 9곳 · 차이 5곳 13,176,000 · 판단 불가 2곳'; the 보통예금 label is the fixed text '보통예금 (WEHAGO 10300)'"
  - "A project cost total with an unknown project reads '판단 불가 (금액 미확인 N개 프로젝트) 확인된 합계 X' (the same for the revenue total), never a bare partial sum"
  - "Only the two line lists (미연결 원가 줄, 미연결 매출 줄) are capped at 20; projects, vendors, revenue and cash tables always show every row"
  - "Missing facts attached to R (R has no 'xchk' key, e.g. a direct render call) reads like a missing file: '자료 없음 (위하고대조.csv — 실행_변환.bat으로 만듦)'"

requirements-completed: []

duration: ~1h30
completed: 2026-11-02
---

# Phase 2 Plan 09: Monthly section 8 'WEHAGO 기준 대조' (D-44, D-48, D-49) Summary

**The monthly report now carries section 8 in both editions: a meta line (장부 기준일 with days-before note, 인트라넷 스냅숏, 변환 시각) and a six-row summary (지급요청 대조 9건 by status, 프로젝트 (도)원가 with 실행가 counts, 미연결 원가, 거래처 미지급, 매출 with '계약금액 (수동 입력)' and '미등록' counts, 보통예금 증감 / 장부 잔액 / 계좌잔액.csv 합계 / 차이), with the detail tables only inside the 경영관리용 `xchk-detail` block; the weekly HTML equals the cbc5497 output.**

## What was built

- `render._s8(R, mode)` after `_s7`, called only when `R['kind'] == 'monthly'`; the TOC gets '8. WEHAGO 기준 대조' only for monthly. Summary numbers on the 02-06 fixture (both editions identical): 지급요청 9건 (계산서 있음 3건 51,700,000 · 금액 차이 1건 160,500,000 · 계산서 없음 1건 264,000 · 이미 지급 1건 49,500,000 · 연결 불가 3건 금액 판단 불가 (미확인 1건) · 판단 불가 0건); (도)원가 258,400,000 (4개 프로젝트 · 실행가 입력 3건 합계 610,000,000 · 실행가 빈칸 1건 · 원가가 실행가보다 큰 프로젝트 0건); 미연결 2줄 1,100,000; 거래처 비교 9곳 · 차이 5곳 13,176,000 · 판단 불가 2곳 · 기초잔액 미반영; 매출 194,000,000 · 프로젝트 연결 175,000,000 · 미연결 2줄 19,000,000 · 계약금액 (수동 입력) 합계 530,000,000 (미등록 2건); 보통예금 증감 45,000,000 · 장부 잔액 판단 불가 (기초 잔액 줄 없음) · 계좌잔액.csv 합계 판단 불가 (계좌잔액.csv 없음). With OPENING_CASH and BANK_BALANCES: '장부 잔액 345,000,000 · 계좌잔액.csv 합계 345,000,000 · 차이 0'.
- 경영관리용 detail block (ids inside `<div id='xchk-detail'>`): xchk-status, xchk-projects, xchk-outside, xchk-unlinked, xchk-vendors-m, xchk-revenue, xchk-revenue-unlinked, xchk-cash (+ xchk-cash-months for the month rows). The 대표용 page contains no 'xchk-detail' and none of these ids. Unlinked cost / revenue lines show the first 20 with '전체 N줄 중 20줄 표시' ('전체 N줄 모두 표시' otherwise).
- Unknown display: unreadable 요청 누계 of 26221 and the 연결 불가 amount read '판단 불가 (미확인 1건)'; blank 계약금액 reads '미등록' and the label is always '계약금액 (수동 입력)'; no registered contract at all reads '등록된 값 없음 (미등록 N건)', never a 0 total; differences come from load_xchk only. Every text cell goes through `esc()` (which masks RRN-shaped text first); tests write the CSV raw (no writer masking) with RRN and HTML in names, memos and the snapshot meta value.
- Missing / unreadable file: '자료 없음 (위하고대조.csv — 실행_변환.bat으로 만듦)' and '읽을 수 없음 (<reason>)' in both editions, no summary and no detail; `보고서.py` prints '위하고 대조 자료 없음 — 실행_변환.bat을 먼저 실행하면 월간 보고 8번에 들어갑니다.' (missing) or '위하고 대조 읽을 수 없음 — <reason>. 월간 보고 8번에는 ‘읽을 수 없음’으로 적었습니다.' (the second wording is mine; the plan fixed only the first), exit code 0. Stale book date: asof 2026-11-30 with book date 2026-10-31 reads '장부 기준일 2026-10-31 (보고 기준일보다 30일 이전)'; also '(… N일 이후)' when later than the report date and '(날짜 형식 확인 불가)' when unparseable.
- `tests/test_report.py`: `numbers_of` also removes the detail block; the REP-02 probe list moved into module function `rep02_probes(test)` (the old test uses it unchanged).
- Weekly: no import and no call of anything new (`import` of `load_xchk` lives in the monthly branch; a subprocess test checks `ceo_report.convert_xchk` is not in `sys.modules` after a weekly run). `calc.py` and `data.py` are identical to cbc5497.

## Commits

| Task | RED | GREEN |
|---|---|---|
| 1 tracer (summary in both editions, weekly unchanged) | 3b64f90 test(02-09): RED Task 1 tracer | b57d9ce feat(02-09): GREEN Task 1 tracer |
| 2 (detail tables, unknown / 미등록, 보통예금) | f9b1f01 test(02-09): RED Task 2 | c70b77f feat(02-09): GREEN Task 2 |
| 3 (missing / unreadable, stale date, console line, probes) | b141a95 test(02-09): RED Task 3 | 2f05d34 feat(02-09): GREEN Task 3 |

(`commits: 6` measured with `git rev-list --count 9ae46a4..HEAD` before this summary's docs commit; the base is the persisted ledger `.git/gsd-plan-head-before-02-09`, written before the first commit.)

## Tests

Full suite 913 -> 973 (+60), all OK (`python3 -m unittest discover -s tests`). New in tests/test_monthly_xchk.py: TestMonthlySection 18, TestWeeklyUnchanged 3, TestMonthlyDetail 16, TestMonthlyDetailLists 3, TestMonthlyTextCells 1, TestMonthlyUnknowns 12, TestMonthlyMissing 8, TestReportProbesMonthlyXchk 2 (each also run alone with `-k`, ran >= 1; `-k TestMonthlyDetail` also matches TestMonthlyDetailLists). `git diff --quiet cbc5497 -- ceo_report/calc.py ceo_report/data.py` exits 0; `convert_xchk.py`, `approval.py`, `approval_render.py` untouched in this plan; render.py, 보고서.py and both test files parse with `ast.parse(..., feature_version=(3, 8))`.

### RED evidence and not-a-real-RED tests

- Task 1: TestMonthlySection `FAILED (failures=2, errors=18)` (counting subtests) before the code. **Not a real RED (they pass on the old code and pin it):** TestWeeklyUnchanged (all 3: the weekly path did not change), and in TestMonthlySection the guard tests (CEO page has no detail block / no forbidden word, numbers_of equal, check_editions with facts attached, weekly has no section 8, source never touches 수집 / xlsx / wehago, calc and data unchanged).
- Task 2: TestMonthlyDetail `FAILED (failures=1, errors=13)` of 16, TestMonthlyUnknowns `FAILED (errors=7)` of 12, TestMonthlyTextCells `FAILED (failures=1)`. **Not a real RED:** five TestMonthlyUnknowns tests on summary values that Task 1 already produced (bank balance without opening line, real difference with sign, no registered contract is not a 0 total, unknown project cost makes the total unknown, unknown unlinked total), plus the CEO-page-has-no-detail tests.
- Task 3: TestMonthlyMissing `FAILED (failures=8)` (8 failure entries counting subtests = 4 of its 8 tests: missing file, other header, bad number, no attached facts; wrong texts, no console line). **Not a real RED:** TestReportProbesMonthlyXchk (both tests pass on the Task 1/2 code; it pins REP-02 for the new variants) and, inside TestMonthlyMissing, the empty-file, stale-date, book-date-after / unreadable-date and weekly-silent tests (4 of 8), which Task 1's code already satisfied.

## Deviations from Plan

**1. [Process] A broken GREEN Task 1 commit was amended.** I added `style="width:100%"` to a `%`-formatted HTML string (needs `100%%`), ran the full suite behind `| tail`, which hid the failing exit code, and committed. I noticed from the lower test count, fixed it, re-ran the suite (934 OK) and amended that one local, unpushed commit (b57d9ce is the amended hash; nothing else was affected).

**2. [Wording] Summary label '거래처 미지급'** instead of R-1's '거래처 미지급 대조' (truth 1 reads '거래처 미지급 비교 9곳 · ...'); `지급요청 대조` and the other labels as in R-1.

**3. [Rule 2 - additions the plan did not name]**
- A scope note under the summary ('금액은 장부 기준일까지 분개장 전체 기간 합계 (월별 매출·손익은 4번) ...') because the facts file holds whole-journal totals, not month totals; no interpretation words.
- Partial totals are labelled, not bare: '판단 불가 (금액 미확인 N개 프로젝트) 확인된 합계 X' for 원가 and the same for 매출; '(원가 판단 불가 N개 프로젝트는 제외)' next to the over-budget count; '프로젝트번호 겹침 N건 (실행가 판단 불가)' and '프로젝트 목록에 없음 N개 포함' when they occur.
- Cash line adds '계좌잔액.csv 합계 ...' and '차이 ...' (a difference is shown only when both sides are known; '차이 판단 불가' when exactly one is).
- Console line for an unreadable file (wording above), and '(보고 기준일보다 N일 이후)' / '(날짜 형식 확인 불가)' for odd book dates.
- Summary table gets inline `style="width:100%"` and `white-space:normal` cells so it wraps on a 390px screen (the existing phone rule would make it `max-content` wide); no CSS change.

**4. [Test structure]** Existing monthly tests needed no adjustment (none relied on section 7 running to the end of a monthly document). The REP-02 probe list was moved from the test method into module function `rep02_probes(test)`, and the monthly-with-facts probe loop lives in tests/test_monthly_xchk.py (TestReportProbesMonthlyXchk) rather than inside test_report.py, so test_report does not import the 02-06 fixture; probes run with the facts file ok / missing / other header / hostile.

**5. [Commit trailer]** Commits end with `Co-Authored-By: Claude Sonnet 5.5` (the attribution the harness gave this session, as in 02-04 .. 02-08) instead of the `Opus 5.5` line in the task template; the `Claude-Session` line is the same.

## Notes on overstating / understating

- Cash outflow: section 8 shows facts only and builds no schedule rows; the 02-04 '중복 가능' overstatement does not reach this plan (위하고대조 does not read 프로젝트집행.csv).
- **Understate risk (noted):** 요청 누계 and 프로젝트밖요청 leave out requests whose status cannot be read (02-06 / approval rule). That Table note is in 변환결과.txt, not in the facts file, so section 8 does not name those requests.
- The cost and revenue totals with an unknown contributor are shown as '확인된 합계', labelled; they are lower bounds, not complete totals.
- '보통예금 (WEHAGO 10300)' is a fixed label: the cash account code is a 설정 value (`변환_현금계정`) and the facts file does not carry it, so a changed code would still print 10300.

## Not verified

- Python 3.8 runtime (only `ast.parse(..., feature_version=(3, 8))`; runtime was 3.13).
- Visual check: one headless Chrome screenshot of the 경영관리용 section 8 in a 390px-wide iframe (summary wraps without letter-by-letter Korean breaking, detail tables scroll inside `.tw`); the 대표용 page, A4 print layout and a real phone were not viewed.
- Real WEHAGO data, a real 위하고대조.csv from 변환.py on the user's PC, Excel-saved variants of the file, and Windows runs: not tested. No real company data was opened (`입력/`, `수집/`, realbooks untouched); the weekly baseline compares against a `git archive cbc5497` extract in a temp folder (the test is skipped with a reason when git or the commit is missing; here it ran).
- REQUIREMENTS.md checkboxes not ticked (orchestrator does it); ROADMAP.md not edited.

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model: T-02-28 (detail only inside the mgmt block; FORBIDDEN and numbers_of checks on sample, fixture, hostile file and all REP-02 probes), T-02-37 and T-02-38 (esc() on every cell, RRN and HTML written raw into the CSV and checked in both editions and in stdout).

## Self-Check: PASSED

- Files exist: tests/test_monthly_xchk.py, ceo_report/render.py, 보고서.py, tests/test_report.py (all FOUND).
- Commits exist: 3b64f90, b57d9ce, f9b1f01, c70b77f, b141a95, 2f05d34 (all FOUND in git log).
- `python3 -m unittest discover -s tests` -> Ran 973 tests, OK.
