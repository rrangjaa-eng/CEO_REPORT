---
phase: 02-source-conversion
plan: 10
subsystem: source-conversion
tags: [integration, characterization, reports, approval, no-double-count, d-42, d-44, d-45, d-47, d-50, python-stdlib]
status: complete

requires:
  - phase: 02-source-conversion
    provides: "02-07 full_company / run_convert end-to-end conversion; 02-08 approval linking; 02-09 monthly section 8 and weekly_baseline"
provides:
  - "tests/test_convert_reports.py: TestConvertedReports, TestConvertedNoDouble, TestConvertedApprovalEqual, TestConvertedIgnored (27 tests) over the folder written by a real 변환.py run"
  - ".planning/WINDOWS.md: five unrun-verify entries (phase 02) for the end-of-phase human checks on the user's Windows PC"
affects: []

plan_head_before: 07ed1c8c871b88b4b2554db3b3b77b21f805e4f2
actuals:
  tokens: 5100
  tasks: 2
  commits: 3   # measured before this SUMMARY commit: 07ed1c8..HEAD = f96be60, d900a93, ff73595

key-files:
  created:
    - tests/test_convert_reports.py
  modified:
    - .planning/WINDOWS.md

key-decisions:
  - "Pure integration plan: no production code was touched (git diff 07ed1c8..HEAD lists only the two files above); no real bug was found, so there is no fix(02-NN) commit"
  - "Monthly comparison parses the real 보고서.py HTML (xchk-projects, xchk-unlinked, summary table), and the approval side parses the real 승인검토 screen from make_screen(input_dir = converted folder); text cells are compared after reducing '판단 불가 (미확인 1건)' to '판단 불가' because the monthly cell carries a count the screen does not"

requirements-completed: []

duration: ~40min
completed: 2026-11-02
---

# Phase 2 Plan 10: Reports and approval screen on converted output Summary

Integration tests that run the full synthetic company through 변환.py and then feed only the converted folder to 보고서.py (주간, 월간) and the approval screen; plus the five end-of-phase human checks recorded in WINDOWS.md. All 27 tests passed on their first run, so they are **characterization tests** of behaviour finished in 02-07, 02-08 and 02-09.

## Commits

| Commit | Message |
|--------|---------|
| f96be60 | test(02-10): Task 1 converted-folder reports (18 tests) |
| d900a93 | test(02-10): Task 2 approval equality and ignore rules (9 tests) |
| ff73595 | docs(02-10): record Phase 2 human checks |

No RED commit and no `fix(02-NN)` commit: nothing failed (V-1). To show the tests are not vacuous I ran TestConvertedApprovalEqual once with `approval.build` patched to ignore `input_dir` (as before 02-08): 3 of its 7 tests failed, as they should. That patch was a scratch run, not committed.

## Test run (characterization evidence)

- The four per-class `-k` commands of the plan's verify each printed `Ran N` with N >= 1 (the `-k` filter also picks up a module-level id, so its N can be one higher than the class's own test count). The file has 27 tests: 18 from Task 1 (TestConvertedReports, TestConvertedNoDouble) and 9 from Task 2 (TestConvertedApprovalEqual 7, TestConvertedIgnored 2).
- Full suite: `python3 -m unittest discover -s tests` Ran 1000 tests, OK (973 before this plan, +27).
- `git diff --quiet cbc5497 -- ceo_report/calc.py ceo_report/data.py ceo_report/intranet.py ceo_report/snapshot.py 실행_주간.bat 실행_월간.bat 실행_승인검토.bat` exits 0.
- `git diff --name-only 07ed1c8..HEAD -- ceo_report 보고서.py 변환.py 승인검토.py` is empty. `git status --porcelain -- 입력 수집` is empty.

## What the tests establish

Truth 1 (TestConvertedReports): 변환.py exits 0 on the full synthetic company; 보고서.py 월간 (기준일 2026-10-31) and 주간 (2026-11-02) exit 0 with `--pdf 안함`. Section 8 summary row `프로젝트 (도)원가` starts with `258,400,000 (` in both editions and the summary tables are identical. 대표용 has no FORBIDDEN word and no `xchk-detail` block, 경영관리용 has it, `numbers_of` is equal, and `check_editions` passes on `compute(...)` + `load_xchk(converted)`. The weekly HTML equals the cbc5497 code's weekly HTML for the same folder (both editions, 작성 time stripped), and has no section 8.

Truth 2 (TestConvertedNoDouble): `calc.compute` weekly events from 프로젝트집행 name request numbers 1201, 5102, 5103, 5104, 5105, 5106, 5108 once each; 5107 and 5109 (already paid) are not named; the 5103 events sum to 165,000,000. `approval.build` schedules requests 1201, 5102, 5103, 5105, 5108 once each; 5103 at 165,000,000 (request amount 160,500,000); Σ scheduled request amounts is 214,764,000 and equals the build on a copy whose 프로젝트집행.csv has no `지급요청` rows; the whole 8-week outflow (`base_out` plus toggle requests) and both `data` lists are identical with and without those rows; the 5 execution rows naming a scheduled request are in `replaced` and none is also in the kept lists. 5106 (amount unknown) is listed as 금액 미확인 and stays out of every sum (never 0).

Truth 3 (TestConvertedApprovalEqual): for the converted folder (default settings) and again after adding the 프로젝트연결.csv row (2026-10-29, 22, 1, 26221) and `변환_자동연결일수 200` and converting again, the approval screen and the monthly section 8 agree per project on WEHAGO (도) 원가 and 요청 누계 (26221 reads 판단 불가 on both), and on 미연결 원가 count and sum. Default: 2 lines 1,100,000. After the manual link: 26221 cost 6,200,000 (5,400,000 + 800,000), unlinked 1 line 300,000, on both surfaces.

Truth 4 (TestConvertedIgnored): `git check-ignore` confirms 입력/변환결과.txt, 입력/위하고대조.csv, 입력/이전/x.csv and 수집/위하고/전자세금계산서(매출)_20261031.xlsx are ignored; the blank template 입력양식/설정.csv is not. WINDOWS.md has five phase-02 unrun-verify entries (실행_변환.bat, 실행_월간.bat, 실행_승인검토.bat, 02-CONTEXT.md for Q-1/Q-2, .gitignore for the `git status` check).

## Deviations from Plan

None - plan executed as written, with these small choices:

1. **Second conversion via `convert.run`, not the CLI.** After editing 프로젝트연결.csv and 설정.csv the folder is converted again with `test_convert_e2e.run_core(..., stamp="20261102_000001")` (the function 변환.py calls) so the backup folder stamp cannot collide with the first run in the same second. The first conversion is the real 변환.py CLI.
2. **Cell comparison reduces '판단 불가 (…)' to '판단 불가'** (see key-decisions); amounts are compared as the exact display strings.
3. **A `git status` test was not added.** `git status --porcelain -- 입력 수집` is run by hand (empty); inside a test it would scan the real 입력/ and 수집/ directories, which this plan forbids. A test instead asserts every run folder is outside the repo root.

## Things worth knowing (no action needed)

- The '중복 가능' ambiguous-group case does not occur in this fixture (`possible_duplicates` and `duplicates` are empty in both builds); the rule that would overstate is covered by the earlier plans' tests, not re-checked here.
- 5104 (approved, dated 2026-10-30, before the 잔액 기준일) is treated as already in the balance by the approval screen and is not in the 8-week outflow; its execution row stays in `unmatched_exec`. That is existing D-35/A-3 behaviour, unchanged.

## Not verified here

The five human checks recorded in WINDOWS.md (real WEHAGO downloads, the sales invoice download screen name Q-1, Q-2 auto-link days, the Windows .bat launchers, and `git status` on the user's PC). No real company data was opened.

## Known Stubs

None.

## Threat Flags

None - tests and a ledger file only; no new endpoints, auth paths or file access in production code.

## Self-Check: PASSED

- tests/test_convert_reports.py exists; .planning/WINDOWS.md has 5 `02 | unrun-verify` rows.
- Commits f96be60, d900a93, ff73595 exist on claude/project-thread-jkflss.
- Full suite OK (1000 tests).
