---
phase: 01-report-engine
plan: 01
subsystem: report-engine
tags: [python-stdlib, unittest, tdd, unknown-as-none, reconciliation]
status: complete

requires: []
provides:
  - "Blank account balances are left out of 현재 현금 / 사용 가능액 and announced as '잔액 미확인 N계좌 (합계 제외)' on the first screen, in section 1 and in section 2; known restrictions stay subtracted"
  - "Start-balance reconciliation compares confirmed accounts only (no false 불일치)"
  - "Vendor table never shows an unknown amount as 0 ('미확인 N건', '부가세 미확인 N건')"
  - "Past-due unprocessed 입금/지급 on the first screen (confirmed sums + unknown counts), kept out of the schedule and the minimum balance"
  - "Scheduled outflows with blank 부가세 counted at 공급가액 only and marked wherever their totals appear"
  - "Tolerant 설정.csv number parsing (util.is_blank, util.setting_num); blank/missing/junk settings use the default visibly (입력 확인 + risk-note mark)"
  - "KPI unit 백만원; 프로젝트 밖 지급예정 (등록분 전체) with 날짜 없음 count"
  - "REP-02 sweep: 대표용 rules proven on sample weekly/monthly and 6 probe inputs"
affects: [01-02, phase-01.1-payment-approval-screen]

plan_head_before: 316ac24566eea877afffb9faf0c04d6115ba8597

estimate:
  tokens: 92000
actuals:
  tokens: 8144      # chars/4 over the realized code and test diff (ceo_report/ + tests/)
  tasks: 3
  commits: 6        # MEASURED: git rev-list --count 316ac24..HEAD (RED + GREEN per task)

tech-stack:
  added: []
  patterns:
    - "RED test commit then GREEN feature commit per task"
    - "probe_folder: copy sample 입력 to a temp dir, change one cell, load/compute/render"
    - "unknown = None; totals carry an unknown count next to the confirmed sum"
    - "settings parsed once in compute() into R['settings_num'] / R['settings_default']"

key-files:
  created: []
  modified:
    - ceo_report/calc.py
    - ceo_report/render.py
    - ceo_report/util.py
    - ceo_report/data.py
    - tests/test_report.py

key-decisions:
  - "A known 사용제한금액 of a balance-unknown account is still subtracted (A-11): 사용 가능액 never exceeds confirmed total minus known restrictions"
  - "Past-due totals are confirmed-only ssum; counts include amount-unknown events; all-unknown side is None (shown 미확인), not 0"
  - "Blank 부가세 on a scheduled outflow is scheduled at 공급가액 only and marked (nothing invented)"
  - "Setting problems go to the one shared 입력 자료 확인 필요 list with labels free of the word 위험, so both editions stay identical (D-13)"

requirements-completed: [CASH-01, CASH-02, PLAN-02, PLAN-03, PROJ-02, PROJ-04, AP-02, DATA-03, REP-02]

coverage:
  - id: D1
    description: "Blank balance excluded and noted everywhere the total is used; restriction kept; no false reconciliation mismatch"
    requirement: "CASH-01"
    verification:
      - kind: unit
        ref: "tests/test_report.py#TestUnknownBalance"
        status: pass
  - id: D2
    description: "Start-balance check compares confirmed accounts only; transfer check unchanged"
    requirement: "CASH-02"
    verification:
      - kind: unit
        ref: "tests/test_report.py#TestUnknownBalance.test_blank_balance_no_false_reconciliation_mismatch"
        status: pass
  - id: D3
    description: "Vendor unknown amounts never 0; no double counting of 프로젝트 밖 지급"
    requirement: "AP-02"
    verification:
      - kind: unit
        ref: "tests/test_report.py#TestUnknownAmountsAndPastDue (a)(b)(c)"
        status: pass
  - id: D4
    description: "Past-due unprocessed items on first screen, not in schedule or minimum balance, unknown counted"
    requirement: "PLAN-03"
    verification:
      - kind: unit
        ref: "tests/test_report.py#TestUnknownAmountsAndPastDue (d)(e)(g)"
        status: pass
  - id: D5
    description: "Blank 부가세 on scheduled outflow marked beside 4주 지급예정, both minimum lines, section 2 rows and vendor rows"
    requirement: "PLAN-02, PROJ-02"
    verification:
      - kind: unit
        ref: "tests/test_report.py#TestUnknownAmountsAndPastDue.test_blank_vat_on_scheduled_outflow_marked"
        status: pass
  - id: D6
    description: "표시/전체/합계 together; 등록분 전체 scope; show-count setting fallback"
    requirement: "PROJ-04"
    verification:
      - kind: unit
        ref: "tests/test_report.py#TestUnknownAmountsAndPastDue.test_nonproject_scope_and_undated_on_first_screen, TestSettingsAndKpi.test_project_show_count_setting"
        status: pass
  - id: D7
    description: "Every setting fallback listed in 입력 자료 확인 필요 and marked in the risk note; commas accepted; KPI unit"
    requirement: "DATA-03"
    verification:
      - kind: unit
        ref: "tests/test_report.py#TestParsing.test_setting_num, TestSettingsAndKpi"
        status: pass
  - id: D8
    description: "대표용 has no interpretation words, same digits as 경영관리용, all reconciliations 일치 across 8 inputs"
    requirement: "REP-02"
    verification:
      - kind: unit
        ref: "tests/test_report.py#TestCeoRulesEverywhere.test_no_interpretation_and_same_numbers_across_inputs"
        status: pass
---

# Phase 1 Plan 01: Report Engine Fixes Summary

Unknown values stay unknown across the report: blank balances, vendor amounts, past-due amounts, 부가세 and numeric settings are each left out of totals (never 0), counted next to the total, and the 대표용 edition carries only factual wording.

## Accomplishments

- **Task 1 (tracer, R1/DR3):** A blank 계좌잔액 is excluded from 현재 현금 and 사용 가능액. The known 사용제한금액 stays subtracted (blank 프로젝트계좌: 386,100,000 / 30,000,000 / 356,100,000). Schedule start, start-balance reconciliation (156,000,000 = 156,000,000 and 408,000,000 = 408,000,000), the KPI sub-lines, the 기간별 자금 heading, section 1 and section 2 all say so. CLI end to end writes the note into the HTML file.
- **Task 2 (R2/R3/DR2/DR4, plan-check BLOCKER 2 and WARNING 3):** 진행팀 shows `미확인`, never 0. Partly unknown vendors show the known total plus `미확인 N건`. First screen shows `예정일 지난 미처리 입금 / 지급 (일정 미포함)` = `1건 110.0 / 0건 0.0` for the sample; known and blank-amount past-due rows are summed and counted separately. Blank 부가세 (사운드랩): 향후 4주 지급예정 확정 170,100,000, minimum 23,800,000 / 152,300,000 on 2027-04-25, marked in all required places. Bottom card reads `프로젝트 밖 지급예정 (등록분 전체)` with `584.1 · 날짜 없음 2건`.
- **Task 3 (R4/DR1, plan-check WARNING 4, REP-02):** `util.is_blank` and `util.setting_num`; `d.settings_line`; six settings parsed once in `compute()`. `"50,000,000"` no longer crashes; `'abc'` falls back to 100 with an 입력 확인 row; blank or deleted 위험_최소보유현금 uses 50,000,000 visibly. KPI values show 백만원. Sweep over 8 inputs passes.

## RED evidence (captured before each fix)

**Task 1** (`9f429ba`), `python3 -m unittest discover -s tests -k TestUnknownBalance`:
```
ERROR: test_blank_balance_excluded_and_shown            KeyError: 'bal_unknown_names'
ERROR: test_unknown_balance_known_restriction_still_subtracted   KeyError: 'bal_unknown_restricted'
FAIL:  test_blank_balance_listed_in_input_issues        (issues held only the P26999 row)
FAIL:  test_blank_balance_no_false_reconciliation_mismatch   AssertionError: 기간 시작 잔액 (은행 잔액 = 거래로 계산한 값)
FAIL:  test_cli_end_to_end_shows_unknown_balance        '잔액 미확인 1계좌 (합계 제외)' not found in HTML
Ran 5 tests ... FAILED (failures=3, errors=2)
```

**Task 2** (`ad9f514`), `-k TestUnknownAmountsAndPastDue`: 7 of 8 failed (KeyError `vat_unknown_n`, `undated_n`, `past_in`, `past_out` x3, `unknown`; `AssertionError: 0 is not None` for 진행팀). The lock test `test_nonproject_payments_not_double_counted` passed on first run, as planned. `Ran 8 tests ... FAILED (failures=1, errors=7)`.

**Task 3** (`ca09c1d`): the test module failed to import (`ImportError: cannot import name 'is_blank' from 'ceo_report.util'`), as the plan describes. To see the per-test reasons I ran the new tests against the old code with `is_blank` / `setting_num` stubbed in from a scratch script (not committed):
```
ERROR test_blank_threshold_uses_default_visibly [blank] / [row deleted]   KeyError: 'settings_num'
ERROR test_settings_with_commas_do_not_crash                              ValueError: invalid literal for int() with base 10: '50,000,000'
ERROR sweep [settings commas and abc]                                     ValueError (same)
FAIL  test_kpi_values_show_unit             '백만원' not found in '572.4'
FAIL  test_project_show_count_setting       '표시 8건 / 전체 8건' not found
FAIL  test_setting_num                      AssertionError: None is not true
Ran 6 tests ... FAILED (failures=3, errors=4)
```
The other 7 sweep inputs passed on the old code (the sweep is a lock, not a RED driver, apart from the settings probe).

## Final test run

```
Ran 47 tests in 0.427s

OK
```
28 at phase start + 5 + 8 + 6 = 47.

## Task Commits

| Task | RED | GREEN |
| ---- | --- | ----- |
| 1 blank balance (tracer) | `9f429ba` test(01-01) | `4d2a3fd` feat(01-01) |
| 2 unknown amounts / past-due / VAT | `ad9f514` test(01-01) | `e2d74d2` feat(01-01) |
| 3 settings / KPI unit / sweep | `ca09c1d` test(01-01) | `d852ca3` feat(01-01) |

## Tracer gate

Task 1 is `type="tracer"`. Auto mode is off and the task has no `gate="blocking-human"`. `HUMAN_VERIFY_MODE` is the default `end-of-phase` and `<verify>` is automated-only. The gate therefore re-ran `<verify>` end to end (TestUnknownBalance 5/5, full suite green, CLI test writes the HTML file) before Task 2 expanded. No checkpoint was needed.

## Deviations from Plan

None - plan executed as written. Notes:

- Task 3 RED is an import failure of the whole test module (plan-specified); per-test RED reasons were confirmed with a scratch shim (see above).
- The first-screen 4주 입금예정 KPI sub-line is now passed through `esc()` like the others (numbers only, no behavior change).

## Verification of plan checks

- Acceptance greps: `or 0` patterns in calc.py = 0; `int(st.get`/`float(st.get`/`settings"].get("위험_` = 0; `settings_issues` = 0; `def setting_num` and `def is_blank` once each; `settings_line`, `settings_default`, `settings_num`, `class='u'` present.
- Python 3.8 grammar check (`ast.parse(..., feature_version=(3,8))`) passes for all five files.
- `python3 보고서.py 주간 --기준일 2026-11-02 --출력 <tmp> --pdf 안함` exits 0 and writes both HTML files.
- `입력/` regenerated byte-identically; `git status` shows only the five planned source/test files modified.

## Known Stubs

None.

## Threat Flags

None. All new CSV-derived strings go through `esc()` / `_na()` / `W()` / `M()`; the risk note no longer writes raw 설정.csv strings (T-01-01, T-01-02, T-01-03, T-01-12 mitigations in place and tested).

## Self-Check: PASSED

- FOUND: ceo_report/calc.py, ceo_report/render.py, ceo_report/util.py, ceo_report/data.py, tests/test_report.py
- FOUND commits: 9f429ba, 4d2a3fd, ad9f514, e2d74d2, ca09c1d, d852ca3
- Full suite: Ran 47 tests, OK
