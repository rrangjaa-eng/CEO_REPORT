---
phase: 02-source-conversion
plan: 04
subsystem: source-conversion
tags: [wehago, snapshot, 프로젝트, 프로젝트집행, d-42, d-49, d-50, dedup, tdd, python-stdlib]
status: complete

requires:
  - phase: 02-source-conversion
    provides: "02-01: Table / Check / cell_amount / cell_date / read_prev / read_config; 02-02/02-03: linking.projects_of / link_costs / link_revenue / requests_of and convert.build_links (Result.links)"
provides:
  - "ceo_report/convert_projects.py: build_projects(projects, revenue, prev_rows) -> Table('프로젝트.csv'); build_execs(books, costs, requests, match, prev_rows, cfg, projects=None) -> Table('프로젝트집행.csv') with extra['cost_portions']"
  - "linking.projects_of entries also carry estimate_text / budget_text / event_text (additive keys)"
  - "tests/test_convert_projects.py: CARD_EXTRA, CARD_PAID_EXTRA, OPENING_EXTRA, make_inputs, exec_inputs, exec_table, full_table, project_table, write_and_load, check_lines, cell_rows"
affects: [02-07 (wires build_projects / build_execs into convert.run; must pass projects=links['projects']), 02-06 (xchk reads the 프로젝트 rows), 02-10]

plan_head_before: 478fb362829d1ede1ba5a18c7d15511b8362d0c3
actuals:
  tokens: 20100
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - "Builders are pure: rows in, convert.Table out; no file access (a test greps the source for 'open(')"
    - "A request disappears only on 이미 지급 or one exact unpaid-then-paid WEHAGO row; anything doubtful becomes a request row plus a '중복 가능' note"
    - "Rows naming one 지급요청 번호 sum to max(invoice total, request amount); the missing part is a positive 차액 row (D-50)"

key-files:
  created:
    - ceo_report/convert_projects.py
    - tests/test_convert_projects.py
  modified:
    - ceo_report/linking.py

key-decisions:
  - "Previous 집행계획미요청 rows are ALL carried (E-5 literal, never understate); the project number is rewritten only when exactly one new key has the same digits. The sample's P26207 row (key 26207 not in the snapshot) is therefore carried as 'P26207' and shows up as a data.load '프로젝트 미연결' line"
  - "A slip credited to BOTH cash and 미지급금 is 요청미지급 (suffix ' · 현금·미지급 대변 함께 있음'), not 지급완료: the cash-first rule of E-2 would drop the unpaid part from the schedule"
  - "build_execs takes an optional projects= (linking.projects_of) to know the new keys for the carried rows; without it the keys of linked cost lines and request codes are used"
  - "Count checks print without the unit '건' (convert.result_lines formats every Check with won(); changing that is outside this plan)"

requirements-completed: []

duration: ~1h
completed: 2026-11-02
---

# Phase 2 Plan 04: 프로젝트.csv and 프로젝트집행.csv builders (D-42, D-49, D-50) Summary

**build_projects gives one row per intranet project with WEHAGO 매출반영누계 and the human-entered 상태 / 예산수정일 / 계약금액 / 완료일 carried from the previous file (never from 매출); build_execs writes every WEHAGO (도) cost line (cash / payable / card, settled by exact payment or oldest-first) plus the intranet requests not yet in the books, each payment exactly once, with source-vs-CSV checks for counts, VAT, payments and request money.**

## What was built

- `build_projects` (E-0): rows in snapshot order, columns `data.SCHEMA['프로젝트.csv'] + ['실행가']`. 사전견적예산 / 실행가 are `cell_amount` of the parsed value; unreadable text ('abc', '협의중') is '' with the note `<key> 사전견적 숫자 아님 → 빈칸` (the unread text now comes from `linking.projects_of`). 매출반영누계 = Σ revenue lines linked to the key ('' if any is unknown, 0 when none). 상태 / 예산수정일 / 계약금액 / 완료일 are carried from the one previous row with the same digits in 프로젝트번호; amounts and dates are normalised, unreadable ones become '' with a note; several matching rows carry nothing and say so; previous-only projects are listed (`이전 프로젝트.csv에만 있는 프로젝트 6건 (옮기지 않음): P26202, ...`). Checks: 프로젝트 수, 사전견적 / 실행가 totals (blanks excluded) and blank counts, `매출 줄 합계 = 매출반영누계 합계 + 미연결 매출` (194,000,000 on the fixture).
- `build_execs` WEHAGO part (E-1..E-3, E-6): cost lines grouped by (전표일자, 전표번호, 거래처, 프로젝트 or [코드]); VAT goes on the largest group of the same slip and vendor (0 on the others, '' when a VAT line is unknown); state from cash / payable credits; card words give 카드결제완료 / 카드사용미결제 with 공급가액 = 총액 and 부가세 ''; settlement per payable vendor (exact payment first, oldest-first only when the books carry a 전기이월 / 기초잔액 line, partial payments stay unpaid with `· 일부 지급 <won>`, `미배분 지급 N건 <won>` always noted). Unlinked cost lines are written (전표 22 with '', 전표 23 with '26999').
- `build_execs` request part (E-4, E-5, D-50): only 승인 / 대기 requests. `이미 지급` -> no row (note names the payment). `계산서 있음` / `금액 차이` with exactly one unpaid group of the same vendor, project and total -> the group row gets the request date, 확정여부 and `· 지급요청 <번호>`; the same group already paid -> no row + note; none, several or a group wanted by two requests -> request row + `(중복 가능)` note. Other statuses -> request row (+ `중복 가능` note when the vendor has unpaid WEHAGO rows). Rows naming a request sum to max(invoice, request): positive 차액 row in both directions. 5107 (status unreadable) is skipped with `상태 확인 필요 1건 → 프로젝트집행에 넣지 않음` and a second note listing number, vendor and amount. Previous 집행계획미요청 rows are carried; every other previous row is counted in one note (plus a note with the not-yet-paid amount among them).
- On FAKE_PL_JOURNAL + FAKE snapshot: 4 project rows; 11 WEHAGO rows + 4 request rows (5102, 5105, 5106, 5108) + 4 carried rows; every check 일치 (건수 8 = 3 + 4 + 1, 금액 265,264,000, 미확인 1, 원가 259,500,000, 부가세 24,840,000, 줄 수 11, 지급 49,500,000, 큰 쪽 반영 216,700,000). calc weekly events naming 5103 sum 165,000,000 and name each request at most once; `approval.build` replaces the five rows that name a scheduled request and its schedule totals equal those of the same input without those rows.

## Commits

| Task | RED | GREEN |
|---|---|---|
| 1 tracer (build_projects) | 41e0842 test(02-04): RED Task 1 tracer | 02524ce feat(02-04): GREEN Task 1 tracer |
| 2 (WEHAGO rows) | d57c9c8 test(02-04): RED Task 2 | 8dbb85a feat(02-04): GREEN Task 2 |
| 3 (requests, D-50, carried rows) | 0df310a test(02-04): RED Task 3 | fa66fde feat(02-04): GREEN Task 3 |

## Tests

Full suite 657 -> 715 (+58), all OK (`python3 -m unittest discover -s tests`). New: TestBuildProjects 16, TestBuildExecsBooks 21, TestBuildExecsRequests 19, TestBuildExecsNoDouble 2 (each also run alone with `-k`, ran >= 1). `git diff --quiet cbc5497 -- ceo_report/calc.py ceo_report/data.py ceo_report/approval.py` exits 0; `git log cbc5497..HEAD -- ceo_report/wehago.py` lists only `feat(02-01): GREEN Task 1 tracer`; `grep -c "open(" ceo_report/convert_projects.py` is 0; convert_projects.py, linking.py and the test file parse with `feature_version=(3, 8)`.

### RED evidence (last line of each failing run)

- Task 1: `FAILED (errors=15)` of 15 (ModuleNotFoundError for convert_projects). One test (`test_projects_of_keeps_the_unread_text...`) was added after the RED commit, together with the GREEN code it pins (so that one test has no RED of its own).
- Task 2: `FAILED (errors=21)` of 21 (no `build_execs`).
- Task 3: TestBuildExecsRequests `FAILED (failures=16, errors=1)` of 19 and TestBuildExecsNoDouble `FAILED (failures=2)` of 2. **Two request tests passed on the Task 2 code and are guards, not a proof that they drive the code:** `test_result_does_not_depend_on_the_order_of_requests_or_journal` (no request rows existed yet) and `test_second_run_on_its_own_output_gives_the_same_rows` (compared two identical tables). The RED run for Task 3 used the Task 2 module (the Task 3 code had been written before the tests; I restored the committed Task 2 file for the RED run and put the code back for GREEN, no `git stash`). The 5109 note assertion was added in the GREEN commit.

## Deviations from Plan

**1. [Plan vs repo] Truth 8 numbers cannot hold on the sample.** The sample 프로젝트집행.csv has 24 rows, 4 of them 집행계획미요청 (P26201 x2, P26203, P26207); the plan says 3 carried and 16 not carried (19 rows). I followed E-5 literally and the never-understate rule: all 4 plan rows are carried, the project number is rewritten only when exactly one new key has the same digits (P26201 -> 26201, P26203 -> 26203, P26207 stays 'P26207' with a note), 20 other rows are counted in `이전 프로젝트집행.csv 줄 20건 옮기지 않음 (WEHAGO·인트라넷으로 다시 만듦)`. data.load therefore shows four '프로젝트 미연결' lines (전표 22, 전표 23, request 5108 and the carried P26207), not three. If the orchestrator prefers to drop plan rows of projects that are not in the snapshot, it is one condition in `_carry_plan_rows`.

**2. [Interface addition] `build_execs(..., cfg, projects=None)`.** The plan signature has no project list, but E-5 needs the new keys to rewrite P26201. Without `projects` the keys of linked cost lines and request codes are used (works on the fixture, but a project with no cost line and no request would not be recognised). **Plan 02-07 must pass `projects=links['projects']`.**

**3. [Rule 3 - needed for a plan truth] `linking.projects_of` got three additive keys** (`estimate_text`, `budget_text`, `event_text`), because the 'abc' -> '' + note behaviour and 행사일 = intranet text need the unread text and `projects_of` only had parsed values. No existing key changed; the linking and approval tests still pass. linking.py is not in this plan's files_modified.

**4. [Format] Count checks print without '건'** (`원본 0 · CSV 0 → 일치`, not `원본 0건`): `convert.result_lines` formats every Check with `won()`. The numbers and results are those of the truths.

**5. [Order] WEHAGO rows are ordered by date, then 전표 number, then vendor (E-6)**, so 전표 37 (09-20) and 4 (10-15) come first. Truth 3 lists the rows by 전표 number; its own sentence says "ordered by date and 전표", and tests find rows by 전표 number so they do not depend on this.

**6. [Rule 2 - never understate] Slip credited to cash AND 미지급금 is 요청미지급**, not 지급완료 (E-2 says cash first). Note `현금·미지급 대변이 함께 있는 전표의 원가 줄 N건 → 지급 전(요청미지급)으로 둠` and the 근거 suffix. This can overstate by the cash part.

**7. [Rule 2 - additions not named in the plan]**
- Check `계산서·요청 금액이 다르면 큰 쪽: 지급요청을 가리키는 줄 합계 = max(계산서, 요청)` (reads the written rows; 216,700,000 on the fixture).
- Notes: `지급요청 5109: 이미 지급 (분개장 2026-10-30 전표 20) → 넣지 않음`; `상태 확인 필요 지급요청: 5107 가상케이터링 1,100,000`; `부가세대급금 ... 같은 거래처의 원가 줄이 없어 부가세에 넣지 못함` (that VAT then makes the VAT check 불일치, visible); `날짜 없는 미지급금 차변 줄 ... 지급으로 보지 않음`; the not-yet-paid amount among the not-carried previous rows (`6건, 공급가액+부가세 108,050,000원 (금액 미확인 1건 제외)` on the sample).
- A card group (카드사용미결제) is never annotated by a request: it becomes a request row with the 중복 가능 note (overstate).
- A group wanted by two requests is given to neither (both become request rows with the note).
- An already-paid invoice row with a request amount above the invoice: no row (spec) but the note names the difference (`요청 금액이 계산서보다 N원 큼 — 차액은 넣지 않았으니 확인`).

**8. [Choices the plan left open]** unpaid card rows have 일자 '' and 확정여부 '확정'; unpaid non-card WEHAGO rows 추정; paid rows 확정; cash rows carry only the base 근거 (`WEHAGO <일자> 전표 <번호>`); carried plan rows keep their text exactly as in the old file (commas included).

**9. [Commit trailer]** Commits end with `Co-Authored-By: Claude Sonnet 5.5` (the attribution the harness gave this session) instead of the `Opus 5.5` line in the task template; the `Claude-Session` line is the same.

## Notes on overstating / understating

- **Overstate (noted, counted):** ambiguous or contested invoice groups, card-unpaid groups and any request next to unpaid rows of the same vendor become request rows with `중복 가능` (5102, 5105, 5108 on the fixture); mixed cash / payable slips stay unpaid; VAT credits on 13500 are not netted (only 차변 is summed, as the plan says).
- **Understate risks that remain (visible in 변환결과):** a status-unreadable request (5107) is not in the schedule (listed with amount); previous-file rows that are not 집행계획미요청 are dropped (their unpaid amount is printed); a request that is `이미 지급` is trusted from wehago.match_requests; an already-paid invoice row hides a larger request amount (note only).
- `rq['date']` (the 일자 of request rows and annotated rows) depends on the `now` given to `linking.requests_of` (the Friday rule for requests without 지급요청일), as in the approval screen.

## Not verified

- Python 3.8 runtime (only `ast.parse(..., feature_version=(3, 8))`; runtime was 3.13).
- Integration through `convert.run` / 변환.py: the builders are not wired yet (plan 02-07); only the builders, `write_table` and `data.load` / `calc.compute` / `approval.build` on a copied sample were exercised.
- Real WEHAGO downloads and a real snapshot: only synthetic fixtures; no real company data was opened (`입력/`, `수집/`, realbooks untouched).
- 행사일 is the intranet text as read by the snapshot reader; a text that is not a date is written as is (data.load keeps it as text, no issue).
- REQUIREMENTS.md checkboxes not ticked (orchestrator does it).

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model: T-02-17 (a request disappears only on 이미 지급 or one exact paid row; tests for contested / ambiguous / card cases and the calc + approval no-double test), T-02-18 (exact pass first, oldest-first only with an opening line, partial and leftover payments shown), T-02-19 (texts pass `write_table` masking; test with a 주민번호-shaped 프로젝트명 and the 전표 22 적요), T-02-20 (only 집행계획미요청 rows and four 프로젝트 columns are carried, every drop is counted).

## Self-Check: PASSED

- Files exist: ceo_report/convert_projects.py, tests/test_convert_projects.py, ceo_report/linking.py (all FOUND).
- Commits exist: 41e0842, 02524ce, d57c9c8, 8dbb85a, 0df310a, fa66fde (all FOUND in git log).
- `python3 -m unittest discover -s tests` -> Ran 715 tests, OK; `git diff --quiet cbc5497 -- ceo_report/calc.py ceo_report/data.py ceo_report/approval.py` exit 0; no 02-04 commit touches ceo_report/wehago.py.
