---
phase: 02-source-conversion
plan: 02
subsystem: source-conversion
tags: [linking, d-38, project-link, manual-override, tdd, python-stdlib]
status: complete

requires:
  - phase: 01.1-approval-screen
    provides: "approval.parse_registered / project_code / _status / _expected_date / _masked, wehago.norm_vendor / load_books journal rows, snapshot.read_snapshot"
provides:
  - "ceo_report/linking.py: LINK_FILE, LINK_COLUMNS, requests_of, projects_of, line_keys, read_links, link_costs, link_revenue, unused_links"
  - "입력양식/프로젝트연결.csv (UTF-8 BOM, header only)"
  - "tests/test_linking.py: LINK_EXTRA, LINK_REQUESTS, REV_LINES, write_link_books, link_snapshot, write_links_csv (+ setup_cost, by_no, total, cnt)"
affects: [02-03 (손익 by team/project), 02-04 (프로젝트집행), 02-05 (계산서 project), 02-06 (월간 대조), 02-08 (승인 화면 D-47)]

plan_head_before: 963915010f0d3c37d91f4b85b36ba091ce60498e
actuals:
  tokens: 21000
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - "Link result = {lines, summary, used}; every line has one basis (수동/코드/자동/미연결), a Korean label and the request number; summary basis -> {count, sum, unknown}"
    - "Auto link only when exactly one candidate and that candidate is a candidate of no other line; the rest stays 미연결 with the candidate count"
    - "Pure functions: no input is changed, results do not depend on journal or request order"

key-files:
  created:
    - ceo_report/linking.py
    - tests/test_linking.py
    - 입력양식/프로젝트연결.csv
  modified: []

key-decisions:
  - "Shared-request rule is the conservative reading: a request that is a candidate of two or more lines (even if one of them has several candidates) links none of them; each line with exactly that one candidate reads '미연결 (자동 연결 후보 공유: 지급요청 R)'"
  - "Result key is 'used' (plan interface contract), not 'unused' (PATTERNS 3.4 wording); unused_links(books, overrides, used) derives the unused rows"
  - "Reason prefix ('코드 없음 · ', '코드 N 프로젝트 목록에 없음 · ', '날짜 없음 · ') is only in the zero-candidate label, as in the plan truths; ambiguous and shared labels carry no prefix"
  - "Project dup=True projects are never revenue candidates; a [code] that is a dup key still links by code (the key exists)"

requirements-completed: []

duration: ~25min
completed: 2026-11-02
---

# Phase 2 Plan 02: Project linking engine (D-38) Summary

**linking.py gives every WEHAGO (도) cost line and 41200 revenue line exactly one basis: manual (프로젝트연결.csv) -> [code] in 적요 -> exactly one intranet request / one project by client and 견적금액 -> 미연결 with the candidate count; sums by basis add up to the books (251,800,000 cost, 194,000,000 revenue on the synthetic data).**

## What was built

- `requests_of(snap, asof, now)` builds each request with the same helpers as `approval.build` (a test compares every key with `A['requests_all']`), text masked. `projects_of(snap)` gives key -> {name, team, client, client_norm, estimate, quote, budget, event_date, dup}; `projects_of(None)` is empty.
- `line_keys(journal)` = (date ISO or '', 전표번호, 줄); `전표번호` text '22.0' is normalised to '22'.
- `link_costs` (L-1..L-3, L-5): candidate requests need amount, 등록일, a code that is a project key, equal norm_vendor, line date in [등록일, 등록일 + link_days] (inclusive) and amount equal to the line amount A or A + 13500 debits of the same 전표 and vendor (only when that 전표 has one cost line for the vendor). Two passes: collect candidates per line, then resolve shared requests, so the result does not depend on order.
- `link_revenue` (L-4): revenue lines (credit - debit) by client_norm + 견적금액, non-dup projects only.
- `read_links` / `unused_links` (L-6): bad rows ignored with `프로젝트연결.csv <file line>번째 줄: <이유> → 무시`; conflicting duplicates both ignored; manual project not in a non-empty list still applies with its own label; unused rows reported as '지정한 줄 없음' or '원가·매출 줄이 아님'.
- No snapshot (projects empty): a [code] is accepted as is (`코드 [26999] (프로젝트 목록 없음)`) and nothing is linked automatically.

## Commits

| Task | RED | GREEN |
|---|---|---|
| 1 tracer | 14caa6a test(02-02): RED Task 1 tracer | 7ef1bce feat(02-02): GREEN Task 1 tracer |
| 2 auto + manual | 7eb4827 test(02-02): RED Task 2 | 68883cf feat(02-02): GREEN Task 2 |
| 3 revenue + no snapshot | 755fe89 test(02-02): RED Task 3 | 247e494 feat(02-02): GREEN Task 3 |

## Tests

Full suite 572 -> 630 (+58), all OK: `python3 -m unittest discover -s tests`. New: TestLinkingTracer 12, TestLinkingAuto 16, TestLinkingManual 13, TestLinkingRevenue 11, TestLinkingNoSnapshot 5, TestLinkingScope 1. Each class is also run alone with `-k` and ran >= 1 test. Plan 02-01 and 02-02 both pass together in the suite.

### RED evidence (last line of each failing run)

- Task 1: `FAILED (errors=12)` of 12 (ModuleNotFoundError: ceo_report.linking).
- Task 2: `FAILED (errors=1)` of 13 Manual tests; TestLinkingAuto's 16 tests PASSED already. Not a fake RED, but a plan-ordering effect: the plan told Task 1 to "write the full rule now" for link_costs, and I also wrote `read_links` / `unused_links` in the Task 1 GREEN commit, so the Task 2 tests pin existing behaviour. Only the template-file test (`입력양식/프로젝트연결.csv`) failed for real, and the GREEN commit 68883cf adds just that file. The Task 2 tests are guards, not a proof that they drive the code.
- Task 3: `FAILED (errors=11)` of 11 Revenue tests (no `link_revenue`); of the 5 NoSnapshot tests 4 passed already (cost no-snapshot mode was part of Task 1) and 1 failed (the revenue one).

## Deviations from Plan

**1. [Interpretation] Shared-request rule is conservative.** Plan L-3 says 'R is the single candidate of no other line'. I implemented the stricter 'R is a candidate of no other line': if line B has candidates {R, S} and line A has only {R}, A is also '후보 공유' (not linked). Reason: the prohibition text says 'that request backs no other line'; linking A could attach R to the wrong project while B actually belongs to R. Truth 3 results are identical under both readings; a test (`test_a_request_that_is_candidate_of_two_lines_links_neither`) pins this.

**2. [Interface wording] Result key `used`, not `unused`** (PATTERNS 3.4 says `unused`, the plan's interface contract says `used`; plan contract followed).

**3. [Rule 2 - additions]** Extra labels the plan did not name: `미연결 (금액 미확인)` for cost and revenue lines with no amount (L-5), `미연결 (코드 없음 · 프로젝트 목록 없음)` when there is no snapshot and no code, `날짜 없음` in the zero-candidate reason when a cost line has no date, `프로젝트연결.csv 필수 열 없음 ... / 수동 지정 0건` when the file lacks a column. TestLinkingScope (one extra test) covers the 'must not change approval/wehago' prohibition.

**4. [Test arithmetic]** My first draft of the truth-4 summary assertion had a wrong expected number (2,200,000 instead of 1,900,000: 미연결 after moving 전표 22 and 41 = 23 + 42 + 43 + 44); the code was right, the test was fixed before the RED commit.

## Notes on overstating / understating

- Linking does not change any amount; it only assigns a project. Every cost line and revenue line appears once (test: Σ over all bases = Σ of lines; cost 249,500,000 on FAKE_JOURNAL alone equals `wehago.project_costs` by_code + unlinked).
- Unknown amount (both 차변 and 대변 blank) is counted in `unknown`, never as 0; a coded or manual line with an unknown amount keeps its code/manual basis.
- A line shared between candidates stays 미연결 (visible), so a project's linked cost can be lower than its true cost until a person adds a 프로젝트연결.csv row. The unlinked total is always shown next to it by the callers (plans 02-03/02-04 must print it).

## Not verified

- Python 3.8 compatibility only by `ast.parse(..., feature_version=(3, 8))`; runtime was 3.13.
- 프로젝트연결.csv was only tested with generated files; Excel-saved variants ('22.0', '2026.10.29', quoted numbers) are simulated by text, not by a real Excel save.
- No real company data was opened (`입력/`, `수집/`, realbooks untouched).
- REQUIREMENTS.md checkboxes not ticked (orchestrator does it).

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model: T-02-10 (exactly-one + shared + window tests), T-02-11 (bad/conflicting rows named with the file line), T-02-12 (masking test with a 주민번호-shaped 행사명 and 적요), T-02-13 (basis, label and request number on every line).

## Self-Check: PASSED

- Files exist: ceo_report/linking.py, tests/test_linking.py, 입력양식/프로젝트연결.csv (all FOUND).
- Commits exist: 14caa6a, 7ef1bce, 7eb4827, 68883cf, 755fe89, 247e494 (all FOUND in git log).
- `python3 -m unittest discover -s tests` -> Ran 630 tests, OK; `git diff --quiet cbc5497 -- ceo_report/approval.py ceo_report/calc.py ceo_report/data.py` exit 0; no 02-02 commit touches ceo_report/wehago.py; linking.py parses with feature_version=(3, 8).
