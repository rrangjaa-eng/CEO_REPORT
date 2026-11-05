---
phase: 01-report-engine
plan: 02
subsystem: report-engine
tags: [python-stdlib, unittest, tdd, launchers, pdf, budget-rate, unknown-as-none]
status: complete

requires: ["01-01"]
provides:
  - "to_pdf deletes an earlier PDF before printing and refuses (error mentioning '이전 PDF') when it cannot; an old PDF is never reported as new (REP-03)"
  - "실행_주간.bat / 실행_월간.bat (UTF-8 no BOM, CRLF, chcp 65001 first, cd to own folder, python or py -3 lookup, %* passthrough) and .gitattributes '*.bat text eol=crlf' (REP-01, R5)"
  - "원가 예산 = round(사전견적 x 예산_원가율, default 0.70) with a visible 예산 사유 and first-screen '예산 미책정 N건 (사유별 건수)' (D-16)"
  - "'집행계획 미등록 금액' label on the remaining budget (D-06)"
  - "Section 5 unknown invoice amounts shown as '미확인 N건' / '외 미확인 N건' / '외 판단 불가 N건' next to totals (D-02, plan-check WARNING 5)"
  - "Section 7 blank 계획금액 / 계약금액 no longer 0-filled; counts shown (D-02)"
  - "Named exact-value test for every remaining Phase 1 requirement"
affects: [phase-01.1-payment-approval-screen, phase-3-deployment]

plan_head_before: 87628ec74fcecf63281a8e41aaa2d5cab5c0c07d

estimate:
  tokens: 98000
actuals:
  tokens: 10148     # chars/4 over the realized code and test diff (ceo_report/, tests/, tools/, 보고서.py, launchers)
  tasks: 3
  commits: 6        # MEASURED: git rev-list --count 87628ec..HEAD at SUMMARY write time (RED + GREEN per task)

tech-stack:
  added: []
  patterns:
    - "RED test commit then GREEN feature commit per task"
    - "load_cli(): load 보고서.py by path (Korean file name) for in-process CLI tests"
    - "_blank_proj(p, rate): budget and budget_reason derived in one place; everything downstream keeps reading P['budget']"
    - "unknown = None; totals carry an unknown count next to the confirmed sum (_amt_unk helper)"

key-files:
  created:
    - 실행_주간.bat
    - 실행_월간.bat
    - .gitattributes
  modified:
    - 보고서.py
    - ceo_report/data.py
    - ceo_report/calc.py
    - ceo_report/render.py
    - tools/make_sample.py
    - 입력/설정.csv
    - 입력양식/설정.csv
    - tests/test_report.py

key-decisions:
  - "A-10 (D-16) kept as planned: project-level reason beats 원가율 설정 오류; valid rate 0 < r <= 1; '70%' = 0.70; missing row = blank = default 0.70 plus 입력 확인 line '-'; budget = int(round(est x rate)); all-unknown totals are None"
  - "예산_원가율 is the one setting where an invalid value is an error, not a default: settings_num is None and no settings_default entry"
  - "Unissued (미발행) is 판단 불가 whenever any invoice supply of the project is unknown, so it is never overstated"

requirements-completed: [CASH-03, PLAN-01, PLAN-02, PROJ-01, PROJ-02, PROJ-03, PL-01, PL-02, PL-03, AR-01, AR-02, AR-03, AP-01, DATA-01, DATA-02, REP-01, REP-03]

coverage:
  - id: D1
    description: "Weekly and monthly CLI write both editions; no-browser path writes HTML with guidance; PDFs start with %PDF-"
    requirement: "REP-01, REP-03"
    verification:
      - kind: unit
        ref: "tests/test_report.py#TestCliOutputs (monthly, without_browser, pdf_when_browser_available)"
        status: pass
  - id: D2
    description: "Old PDF removed before printing; locked old PDF reported and browser not started"
    requirement: "REP-03"
    verification:
      - kind: unit
        ref: "tests/test_report.py#TestCliOutputs.test_stale_pdf_not_reported_as_new, test_locked_old_pdf_reported"
        status: pass
  - id: D3
    description: "Launcher files: no BOM, all CRLF, chcp before Korean text, required commands"
    requirement: "REP-01"
    verification:
      - kind: unit
        ref: "tests/test_report.py#TestLaunchers.test_launchers_exist_and_call_cli"
        status: pass
      - kind: manual
        ref: "Windows double-click run (human check, A-E1)"
        status: pending
  - id: D4
    description: "Budget = estimate x rate, reasons, 예산 미책정 summary, default/blank/invalid rate"
    requirement: "PROJ-01, PROJ-03"
    verification:
      - kind: unit
        ref: "tests/test_report.py#TestProjectBudget (8 tests)"
        status: pass
  - id: D5
    description: "Section 5 and section 7 unknown amounts counted, not zero"
    requirement: "AR-01, DATA-01, DATA-02"
    verification:
      - kind: unit
        ref: "tests/test_report.py#TestUserRulesLocked.test_invoice_unknown_counts_shown, test_blank_plan_amount_not_zero, test_blank_contract_not_zero"
        status: pass
---

# Phase 1 Plan 02: Launchers, PDF Guard, Budget Rate and Requirement Locks Summary

One command or one double-click now writes weekly or monthly HTML + PDF for both editions without ever passing off an old PDF, project 원가 예산 means 사전견적 x 원가율 (default 0.70) with its reason always visible, and every remaining Phase 1 requirement is pinned by a named exact-value test.

## Accomplishments

- **Task 1 (tracer, REP-01/REP-03/R5):** `to_pdf` removes an existing PDF first; on `OSError` it returns `PDF 실패: 이전 PDF를 지우지 못함 (PDF 파일을 닫고 다시 실행): ...` without starting the browser. Two launchers and `.gitattributes` added (UTF-8 no BOM, CRLF; verified with `git ls-files --eol`: `attr/text eol=crlf`). No `shell=True` (T-01-07), `cd /d "%~dp0"` (T-01-08), `출력/` still git-ignored (T-01-10).
- **Task 2 (D-16, D-06, PROJ-01, PROJ-03):** `예산_원가율` setting (DEFAULT_SETTINGS, sample and blank 설정.csv line 9). `_blank_proj(p, rate)` sets `budget` and `budget_reason`. Sample: P26201 원가 예산 210,000,000, total 465,500,000, 1 missing; first screen reads `원가 예산 = 사전견적 × 원가율 70%` and `예산 미책정 1건 (사전견적 없음 1건)`. With rate `abc`/`1.5`/`0`: `예산 미책정 8건 (사전견적 없음 1건, 원가율 설정 오류 7건)` and a `설정.csv` line 9 entry. Blank or deleted rate: 0.70 plus `예산_원가율 설정 비어 있음 → 기본값 사용(0.70)`. Section 3 has 사전견적 / 원가 예산 / 예산 사유 columns; section 7 예산 미지정 table has 예산 사유. `입력/` changed only by the one 설정.csv row in the two 설정.csv files.
- **Task 3 (D-02, WARNING 5, locks):** Section 5 per-project `issued_unknown` / `ar_unknown`, totals `issued_unknown_n` / `ar_unknown_n` / `unissued_unknown_n`; the old `(outstanding or 0) > 0` filter that silently dropped an unknown outstanding is gone. Section 7 `plan_total`, `plan_unknown_n`, per-item `plan_unknown`, `no_budget_contract` + `no_budget_contract_missing`. 13 tests in `TestUserRulesLocked`.

## RED evidence (captured before each fix)

**Task 1** (`951a806`), `-k TestCliOutputs -k TestLaunchers`, 3 pass (locks a, b, c), the rest fail:
```
FAIL: test_locked_old_pdf_reported      AssertionError: unexpectedly None
FAIL: test_stale_pdf_not_reported_as_new AssertionError: unexpectedly None
FAIL: test_launchers_exist_and_call_cli [실행_주간.bat]  AssertionError: False is not true : 실행_주간.bat
FAIL: test_launchers_exist_and_call_cli [실행_월간.bat]  AssertionError: False is not true : 실행_월간.bat
Ran 6 tests ... FAILED (failures=4)
```

**Task 2** (`9e7f802`), `-k TestProjectBudget -k test_remaining_budget_not_turned_into_payment` (all 9 tests fail, 10 failures + 3 errors counting subtests):
```
ERROR test_budget_is_estimate_times_cost_rate      KeyError: 'cost_rate'
ERROR test_no_budget_reason_blank_estimate         KeyError: 'no_budget_reasons'
ERROR test_no_budget_reason_unparseable_estimate   KeyError: 'budget_reason'
FAIL  test_cost_rate_blank_uses_default_and_listed [blank] [row deleted] [70%]   설정.csv에 예산_원가율 행이 없음
FAIL  test_cost_rate_setting_error [abc] [1.5] [0]                                설정.csv에 예산_원가율 행이 없음
FAIL  test_no_budget_reason_zero_or_negative       AssertionError: 0 is not None : P26208
FAIL  test_no_budget_row_labels                    '집행계획 미등록 금액' not found in section 3
FAIL  test_project_table_columns                   '원가 예산' not found in section 3
FAIL  test_remaining_budget_not_turned_into_payment AssertionError: 19650000 != 13650000
Ran 9 tests ... FAILED (failures=10, errors=3)
```

**Task 3** (`6907111`), `-k TestUserRulesLocked`: 10 lock tests pass on first run (A-09), 3 RED:
```
ERROR test_blank_contract_not_zero          KeyError: 'no_budget_contract_missing'
ERROR test_invoice_unknown_counts_shown     KeyError: 'issued_unknown'
FAIL  test_blank_plan_amount_not_zero       AssertionError: 0 is not None
Ran 13 tests ... FAILED (failures=1, errors=2)
```

## Mutation checks (lock-test teeth, A-09)

One expected number changed temporarily in each lock test, run, then restored (file compared byte-identical afterwards):
```
FAIL: test_outflows_split_by_category        '회사공통지출': [0, 8000000] != [0, 8000001]
FAIL: test_receivable_amounts_and_overdue_days  (828000000, 358000000, 470000000, 228800000) != (..., 228800001)
Ran 2 tests ... FAILED (failures=2)
```
Note: the restore initially appeared to leave both tests failing. Cause: the mutated and restored file had the same size and the same mtime second, so Python reused the stale `.pyc`. Removing `tests/__pycache__` fixed it; the source was restored correctly.

## Final test run

```
Ran 74 tests in 3.976s

OK
```
47 (after 01-01) + 6 (Task 1) + 8 (Task 2) + 13 (Task 3) = 74. On this host Chrome exists, so `test_cli_pdf_when_browser_available` ran (no skip).

Also run end to end: `python3 보고서.py 월간 --기준일 2026-10-31 --출력 <tmp>` printed `집계 기간 2026-10-01 ~ 2026-10-31`, wrote 2 HTML + 2 PDF (`%PDF-` header), exit 0. `git check-ignore -q 출력/x.html` exits 0.

## Requirement to test map

| Req | Proving test(s) |
|---|---|
| REP-01 | TestCliOutputs.test_cli_monthly_writes_both_editions; TestChecksAndOutput.test_cli_writes_files; TestLaunchers.test_launchers_exist_and_call_cli (Windows run = human check) |
| REP-03 | TestCliOutputs.test_cli_without_browser_still_writes_html, test_cli_pdf_when_browser_available, test_stale_pdf_not_reported_as_new, test_locked_old_pdf_reported |
| CASH-03 | TestUserRulesLocked.test_outflows_split_by_category |
| PLAN-01 | TestSchedule.test_buckets_4_weeks_then_months_to_6, test_unconfirmed_receipt_is_estimate |
| PLAN-02 | TestUserRulesLocked.test_min_balance_firm_and_estimate |
| PROJ-01 | TestProjectBudget.test_budget_is_estimate_times_cost_rate, test_project_table_columns |
| PROJ-02 | TestProjects.test_supply_vs_cash; 01-01 test_blank_vat_on_scheduled_outflow_marked |
| PROJ-03 | TestProjectBudget.test_no_budget_reason_* (4), test_cost_rate_setting_error, test_cost_rate_blank_uses_default_and_listed, test_no_budget_row_labels; TestProjects.test_no_budget_is_undeterminable, test_remaining_budget_not_turned_into_payment |
| PL-01 | TestUserRulesLocked.test_profit_and_cash_kept_apart |
| PL-02 | TestUserRulesLocked.test_pl_sources_separate |
| PL-03 | TestUserRulesLocked.test_unrecognized_and_unknown_cost |
| AR-01 | TestUserRulesLocked.test_receivable_amounts_and_overdue_days, test_invoice_unknown_counts_shown |
| AR-02 | TestReceivables.test_unissued_days_only_with_done_date |
| AR-03 | TestUserRulesLocked.test_specials_listed_separately |
| AP-01 | TestUserRulesLocked.test_nonproject_obligations_by_category |
| DATA-01 | TestUserRulesLocked.test_changes_and_plan_vs_actual, test_blank_plan_amount_not_zero |
| DATA-02 | TestUserRulesLocked.test_unreflected_scope_items, test_blank_contract_not_zero |

## Task Commits

| Task | RED | GREEN |
| ---- | --- | ----- |
| 1 CLI/PDF/launchers (tracer) | `951a806` test(01-02) | `476c160` feat(01-02) |
| 2 원가 예산 D-16 | `9e7f802` test(01-02) | `d0601f4` feat(01-02) |
| 3 locks + section 5/7 unknowns | `6907111` test(01-02) | `29e8b1d` feat(01-02) |

## Tracer gate

Task 1 is `type="tracer"`, no `gate="blocking-human"`, auto mode off, `HUMAN_VERIFY_MODE` default `end-of-phase`, `<verify>` automated-only. The gate re-ran `<verify>` end to end (TestCliOutputs and TestLaunchers 6/6, full suite 53 OK, launchers not git-ignored) before Task 2. No checkpoint was needed.

## Deviations from Plan

None - plan executed as written. Notes:

- The plan's `check-ignore -q` form with two paths errors in git ("--quiet is only valid with a single pathname"); verified with `git check-ignore 실행_주간.bat 실행_월간.bat` (prints nothing, exit 1 = not ignored).
- Test shapes I had to adapt from the plan text to the real data structures (no behavior change): `R["s4"]["sources"][src]["table"]` entries are keyed by `target` (not `unit`); `R["s6"]["by_cat"][cat]` is a dict with `total`.

## Human checks outstanding (cannot run on Linux)

- Windows double-click of 실행_주간.bat and 실행_월간.bat on a PC with Python 3.8+ (Korean text readable, window waits for a key, install guidance when python/py absent). Static checks only here (A-E1); Phase 3 (DEP-01) runs them from F:\CLAUDE\CEO_REPORT.
- PDF output on the user's PC depends on Edge/Chrome at a BROWSERS path (A-E2); proven here with Chrome on Linux only.

## Known Stubs

None.

## Threat Flags

None. New CSV-derived strings (budget reasons are fixed vocabulary; the rate error message echoes the raw 설정 value) go through `esc()` / `_na()` / `W()` before reaching HTML (T-01-11, T-01-13, T-01-14 mitigated and tested; T-01-06, -07, -08, -10 mitigated).

## Self-Check: PASSED

- FOUND: 실행_주간.bat, 실행_월간.bat, .gitattributes, 보고서.py, ceo_report/{data,calc,render}.py, tools/make_sample.py, tests/test_report.py
- FOUND commits: 951a806, 476c160, 9e7f802, d0601f4, 6907111, 29e8b1d
- Full suite: Ran 74 tests, OK
