---
phase: 02-source-conversion
plan: 06
subsystem: source-conversion
tags: [wehago, 위하고대조, xchk, 보통예금, d-44, d-48, d-49, b5, tdd, python-stdlib]
status: complete

requires:
  - phase: 02-source-conversion
    provides: "02-01 Table / Check / cell_amount / write_table / read_config; 02-02 linking.link_costs / link_revenue / projects_of / requests_of; 02-04 build_projects rows (계약금액 text, D-49)"
provides:
  - "ceo_report/convert_xchk.py: XCHK_FILE, XCHK_COLUMNS, build_xchk(books, costs, revenue, projects, requests, match, project_rows, meta, cfg, bank) -> Table('위하고대조.csv'), load_xchk(input_dir) -> dict"
  - "tests/test_convert_xchk.py: xchk_inputs(test, journal=None, bank=None, extra_requests=None, projects=None), xchk_table, write_xchk, shared_inputs, OPENING_CASH, BANK_BALANCES, BANK_TX, META, NO_BANK"
affects: [02-07 (writes the Table from convert.run and passes bank rows), 02-09 (monthly section 8 reads load_xchk), 02-10]

plan_head_before: dffe4a8fba0d63923bc5144bc01063225a385c3e
actuals:
  tokens: 20400
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - "One fact per row (구분, 대상, 이름, 항목, 금액, 건수, 비고); the CSV stores facts only and load_xchk derives every difference by subtraction of two known values (None otherwise)"
    - "B5: any unknown contributor makes the 금액 cell '' and the count of unknown contributors goes to 비고 only; 건수 still counts every contributor"
    - "Source side of every Check is computed from the journal / link results, CSV side is read back from the rows just built"

key-files:
  created:
    - ceo_report/convert_xchk.py
    - tests/test_convert_xchk.py
  modified: []

key-decisions:
  - "The 기초 잔액 row's 항목 is exactly '기초 잔액' (truth 3 wording); the X-1 long form '기초 잔액 (전기이월·기초잔액 줄)' is explained in the Table notes instead"
  - "WEHAGO 잔액 (장부 기준일) = 기초 잔액 + 증감 of cash lines dated on or before 장부 기준일; later lines are in 증감 (전체 기간) and the 월별 rows but not in the balance (비고 '장부 기준일 이후 N줄 제외'); an undated cash line blanks the balance"
  - "Duplicated project keys (linking dup=True): 실행가 비고 '프로젝트번호 겹침 (첫 줄의 실행가)', load_xchk gives no cost-vs-budget difference and counts the project in totals.budget_dup (same 판단 불가 as the approval screen)"

requirements-completed: []

duration: ~1h30
completed: 2026-11-02
---

# Phase 2 Plan 06: 위하고대조.csv facts and reader (D-44, D-48, D-49) Summary

**build_xchk turns the converted books, request matching and link results into 위하고대조.csv (one fact per row: 기준, 요청상태, 프로젝트원가 with 요청 누계, 프로젝트밖요청, 미연결원가, 거래처미지급, 매출계약 with 'WEHAGO 매출' and '계약금액 (수동 입력)', 매출미연결, 보통예금 and 보통예금월) with five source-vs-CSV checks; load_xchk reads it back with differences derived only from known values, totals of registered 계약금액 / known 실행가 with their blank counts, and never raises.**

## What was built

- `build_xchk` (pure, no file access; a test greps the source for `open(` / `'w'`): rows in the order 기준 -> 요청상태 -> 프로젝트원가 (WEHAGO 원가, 실행가, 요청 누계 per project in snapshot order, then keys reached only by manual links with 이름 '(프로젝트 목록에 없음)' and only a 원가 row) -> 프로젝트밖요청 -> 미연결원가 + 줄 -> 거래처미지급 (+ 요약) -> 매출계약 -> 매출미연결 + 줄 -> 보통예금 -> 보통예금월. 요청상태 numbers are `wehago.match_requests` summary as is; 거래처미지급 rows are `wehago.vendor_payables` as is (7 vendors on the fixture, summary 9 / 5 / 13,176,000 / 2, 비고 '기초잔액 미반영'); 요청 누계 uses the approval `_projects` rule (code = project key, status != 'status_unknown').
- Fixture numbers: 원가 26201 50,000,000 (2줄), 26220 158,000,000 (4줄), 26221 5,400,000 (2줄), 26203 45,000,000 (1줄); 실행가 300 / 250 / '' ('실행가 빈칸') / 60 million; 요청 누계 44,264,000 / 166,000,000 / '' (2건, '금액 미확인 1건') / 49,500,000; 프로젝트밖요청 2,200,000; 미연결원가 1,100,000 (2줄, 전표 22 and 23); 매출 100,000,000 / 0 / 0 / 75,000,000 against 계약금액 (수동 입력) 360,000,000 / '' / '' / 170,000,000 ('미등록'); 매출미연결 19,000,000 (2줄: 32-2, 38-1).
- 보통예금 (D-48): no opening line -> 기초 잔액 '' and WEHAGO 잔액 '' with '판단 불가 — 기초 잔액 줄 없음'; with OPENING_CASH 300,000,000 and 345,000,000, the opening line in no month; 증감 45,000,000 (2026-09 -12,000,000, 2026-10 57,000,000); 계좌잔액.csv 잔액 합계 345,000,000 (비고 '기준일 2026-10-31', latest row per 계좌명); 입출금내역 증감 2026-10 57,000,000, 2026-09 '' ('입출금내역 없음'); missing files read '' with '계좌잔액.csv 없음' / '입출금내역.csv 없음'.
- Checks (label: 원본 · CSV): `(도) 원가 = 프로젝트원가 + 미연결원가` 259,500,000; `매출 = 매출계약 WEHAGO 매출 + 매출미연결` 194,000,000; `지급요청 건수 = 요청상태 건수 합계` 9; `미연결 원가 줄` 2; `현금계정 증감 = 보통예금월 WEHAGO 증감 합계` 45,000,000 — all 일치 on the fixture. 원본 sides come from the journal (via `convert_pl._classify` / `_net`) or the link results, not from the rows being checked.
- `load_xchk` result keys: state, reason, meta, status, projects, outside, unlinked, unlinked_lines, vendors, vendor_summary, revenue, revenue_unlinked, revenue_unlinked_lines, cash, cash_months, totals. Derived: project `cost_vs_budget` (cost - 실행가), `request_vs_cost` (요청 누계 - cost), vendor `diff` (WEHAGO 미지급 - 인트라넷 요청), `cash.balance_diff` (only when the opening balance exists), month `diff`; totals `contract_sum` 530,000,000 / `contract_registered` 2 / `contract_unregistered` 2, `budget_sum` 610,000,000 / `budget_known` 3 / `budget_blank` 1, `over_budget` 0. Missing file -> '자료 없음' ('위하고대조.csv 없음'); other header -> '읽을 수 없음' ('위하고대조.csv 머리글 다름'); a non-numeric 금액 or 건수 -> '읽을 수 없음' naming `위하고대조.csv N번째 줄`; garbage bytes, a folder in the file's place and `None` never raise. Every key is present in every state (no KeyError for 02-09).

## Commits

| Task | RED | GREEN |
|---|---|---|
| 1 tracer (기준, 원가, 미연결원가, round trip) | 0933802 test(02-06): RED Task 1 tracer | 2b0a287 feat(02-06): GREEN Task 1 tracer |
| 2 (요청, 거래처, 매출 대 계약금액, B5) | c29bdca test(02-06): RED Task 2 | 0db3f82 feat(02-06): GREEN Task 2 |
| 3 (보통예금, load_xchk derivations) | dcff7f9 test(02-06): RED Task 3 | 86ee9f1 feat(02-06): GREEN Task 3 |

(`commits: 6` is measured with `git rev-list --count dffe4a8..HEAD` before this summary's own docs commit.)

## Tests

Full suite 771 -> 854 (+83), all OK (`python3 -m unittest discover -s tests`). New: TestXchkTracer 14, TestXchkFacts 20, TestXchkUnknown 10, TestXchkCash 21, TestXchkLoad 18 (each also run alone with `-k`, ran >= 1). `git diff --quiet cbc5497 -- ceo_report/calc.py ceo_report/data.py ceo_report/approval.py` exits 0 (also approval_render.py, 승인검토.py, snapshot.py, intranet.py); no 02-06 commit touches `ceo_report/wehago.py`, `linking.py` or `convert.py`; `grep -c "'w'\|\"w\"" ceo_report/convert_xchk.py` is 0; both files parse with `ast.parse(..., feature_version=(3, 8))`.

### RED evidence (last line of each failing run)

- Task 1: `FAILED (errors=14)` of 14 (ModuleNotFoundError: ceo_report.convert_xchk).
- Task 2: TestXchkFacts `FAILED (failures=18, errors=1)` of 20; TestXchkUnknown `FAILED (failures=6)` of 10. **Five tests were not a real RED** (they passed on the Task 1 code and pin behaviour Task 2 must not break): `test_manual_link_to_a_project_not_in_the_list_adds_a_row_and_keeps_the_check`, `test_cost_line_without_amount_blanks_the_project_cost_and_counts_the_line`, `test_unlinked_cost_line_without_amount_blanks_the_unlinked_total`, `test_social_security_number_in_a_memo_is_masked_in_the_table_and_the_file`, `test_a_social_security_number_shaped_meta_value_is_masked` (the plan put the cost B5 and masking behaviour into the tracer's cost rows).
- Task 3: TestXchkCash `FAILED (failures=21)` of 21; TestXchkLoad `FAILED (failures=2, errors=8)` of 18. **Eight TestXchkLoad tests were not a real RED** (they passed on the Task 1/2 loader and pin it): missing file, bad 금액, bad 건수, masking in a bad cell, garbage / folder / None never raise, no writes, comma-formatted values, all keys present in the unusable result.

## Deviations from Plan

**1. [Name] 기초 잔액 항목 is '기초 잔액'** (truth 3), not X-1's '기초 잔액 (전기이월·기초잔액 줄)'. The truths quote the other three 보통예금 items in full but this one short, so I followed the truth; the explanation sits in the Table note (`보통예금 기초 잔액(전기이월·기초잔액) 줄이 없어 장부 잔액은 판단 불가`).

**2. [Rule 2 - additions the plan did not name]**
- Balance 'at 장부 기준일' excludes cash lines dated after the book date (they stay in 증감 전체 기간 and in their month, so the cash Check still ties out) and is blank with '현금 줄 날짜 없음 N줄 — 장부 기준일 이전인지 알 수 없음' when a cash line has no date (the Check then reads 불일치 on purpose: 46,000,000 vs 45,000,000, visible instead of hidden).
- 계좌잔액 합계: a row with no readable 기준일 blanks the sum ('기준일 확인 불가 N건'); two different rows for one 계좌명 on its latest date blank it ('금액 미확인 N건'); an empty file reads '계좌잔액.csv 줄 없음'.
- 입출금내역: a row without a readable 일자 blanks every month ('일자 확인 불가 N건'); an unreadable 금액 or 입출금 value blanks that month ('금액 미확인 N건' / '입출금 구분 확인 불가 N건'); a negative 출금 amount is still an outflow (abs, same as `data.load`); months that have bank rows but no cash line in the books are not listed in 보통예금월 but named in a Table note.
- 거래처미지급 인트라넷 요청 rows carry the request count (computed with the same filter as `vendor_payables`); 요약 rows are 비교 거래처 / 차이 있는 거래처 / 판단 불가 거래처 (the 차이 row notes '판단 불가 N곳 제외').
- A Table note lists requests whose status could not be read (5107, 1,100,000 on the fixture) because they are not in 요청 누계 (approval rule).
- Duplicated project key handling (see key-decisions), and `build_xchk` returns `written=False, reason='WEHAGO 장부를 쓸 수 없음'` when `books.state != 'ok'`; `bank=None` is tolerated.

**3. [Interface wording]** `xchk_inputs(test, journal=None, bank=None)` got two more keyword parameters (`extra_requests`, `projects`); `journal`, when given, is the full journal (default FAKE_PL_JOURNAL), so cash tests pass `FAKE_PL_JOURNAL + OPENING_CASH`. `project_rows` in the helper is the real `build_projects` output over the sample, so 계약금액 360,000,000 / '' / '' / 170,000,000 comes from plan 02-04's carry rule, not a literal.

**4. [Test fixes during GREEN]** Two Task 3 expectations used wrong cash line counts (my arithmetic: 2026-09 has 2 lines, 2026-10 has 7, total 9) and the Task 2 row-kind order test did not yet list 보통예금 / 보통예금월; fixed in the Task 3 GREEN commit (the code was right).

**5. [Commit trailer]** Commits end with `Co-Authored-By: Claude Sonnet 5.5` (the attribution the harness gave this session, as in 02-04 / 02-05) instead of the `Opus 5.5` line in the task template; the `Claude-Session` line is the same.

**6. [Process]** The plan commit ledger `.git/gsd-plan-head-before-02-06` was written right after the first (RED) commit, with the value of that commit's parent (`dffe4a8`), not before it. Same value, so the measured count is right.

## Notes on overstating / understating

- This file holds no schedule rows and no 중복 가능 rows: the ambiguous-group overstatement of 02-04 (프로젝트집행.csv) is not repeated here and 위하고대조 does not read 프로젝트집행.csv.
- **Understate risk (noted):** 요청 누계 and 프로젝트밖요청 leave out requests whose status cannot be read (the approval rule, same numbers as the 승인 screen); the Table note names them with amounts.
- 거래처 차이 합계 is the sum of the vendors whose difference is known (wehago rule); vendors with an unknown side are counted next to it ('판단 불가 N곳 제외'), never added as 0.
- 계좌잔액 합계 may include accounts outside the WEHAGO cash accounts (Table note), so a 잔액 차이 can be a scope difference, not an error.
- 현금계정 증감 uses every cash line (including those after 장부 기준일); the 잔액 uses only lines up to 장부 기준일.

## Not verified

- Python 3.8 runtime (only `ast.parse(..., feature_version=(3, 8))`; runtime was 3.13).
- Not wired into `convert.run` / 변환.py (plan 02-07) and not rendered (plan 02-09): only `build_xchk`, `write_table` and `load_xchk` were exercised. Plan 02-07 must pass `project_rows=<build_projects(...).rows>`, a `meta` OrderedDict, `match=wehago.match_requests(books, requests)` and `bank` rows from `util.read_csv` (the `_line` / `_file` keys are tolerated; tested).
- Real WEHAGO downloads, real 계좌잔액.csv / 입출금내역.csv, Excel-saved variants of 위하고대조.csv beyond comma-formatted numbers: not tested. No real company data was opened (`입력/`, `수집/`, realbooks untouched).
- REQUIREMENTS.md checkboxes not ticked (orchestrator does it); ROADMAP.md not edited (the 02-05 line is also still unticked).

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model: T-02-25 (header and numeric validation -> '읽을 수 없음', never raises; Task 3 tests), T-02-26 (masked 적요 / 이름 / 기준 values, RRN tests on the table and the written file), T-02-27 (B5 tests for cost, revenue, request, bank and cash cases).

## Self-Check: PASSED

- Files exist: ceo_report/convert_xchk.py, tests/test_convert_xchk.py (both FOUND).
- Commits exist: 0933802, 2b0a287, c29bdca, 0db3f82, dcff7f9, 86ee9f1 (all FOUND in git log).
- `python3 -m unittest discover -s tests` -> Ran 854 tests, OK.
