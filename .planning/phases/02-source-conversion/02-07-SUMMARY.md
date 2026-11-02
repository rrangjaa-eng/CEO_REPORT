---
phase: 02-source-conversion
plan: 07
subsystem: source-conversion
tags: [convert, e2e, cross-file-checks, d-43, d-46, d-48, d-50, tdd, python-stdlib]
status: complete

requires:
  - phase: 02-source-conversion
    provides: "02-03 build_pl / build_links; 02-04 build_projects / build_execs; 02-05 wehago.load_sales / build_invoices; 02-06 build_xchk"
provides:
  - "ceo_report/convert.py: run() builds 손익, 계산서, 프로젝트, 프로젝트집행, 위하고대조 from one books/snapshot/links/match, cross_checks(), read_bank(), xchk_meta(), schedule_overlaps(), input_check_lines(), precheck_writable(), check_text()"
  - "변환.py: stdout summary (one line per file, 대조 불일치, 자금일정 겹침 count, 입력 확인 count, 변환결과.txt path)"
  - "tests/test_convert_e2e.py: full_company(test, snapshot=True, sales=True) -> (tmp, input_dir, collect_dir, wehago_dir), run_full, TestConvertEndToEnd, TestConvertDegraded, TestConvertRerun, TestConvertListings"
affects: [02-08, 02-09, 02-10]

plan_head_before: 6d19215c23f9ba98fd4f9876f4313ba980cdf924
actuals:
  tokens: 10900
  tasks: 2
  commits: 4

key-files:
  created:
    - tests/test_convert_e2e.py
  modified:
    - ceo_report/convert.py
    - 변환.py
    - tests/test_convert.py

key-decisions:
  - "Count checks print with a 건 suffix in 변환결과.txt ('원본 0건 · CSV 0건'), decided in convert.check_text by label (the plan's truth quotes them that way); builder Table.checks and their own tests are unchanged"
  - "All write targets (five CSVs and 변환결과.txt) are pre-checked for a lock before step A, so a locked 변환결과.txt also replaces nothing"
  - "Files not rebuilt (no snapshot, no sales source) are Table(written=False): not pre-checked, not backed up, not touched"

requirements-completed: []

duration: ~1h
completed: 2026-11-02
---

# Phase 2 Plan 07: End-to-end conversion wiring Summary

**One `변환.py` run now builds 손익, 계산서, 프로젝트, 프로젝트집행 and 위하고대조 from the same books, snapshot, links and request match, writes them in one all-or-nothing step, ties the files to each other in a `[파일 사이 대조]` section, keeps an existing 계산서.csv (with its 작성일) when no usable sales file exists, and lists 자금일정 overlaps and `data.load` input issues read-only.**

## What was built

- `convert.run` order (W-1): config -> books (not ok -> exit 3, all five tables `written=False`) -> snapshot -> `_build_tables` (prev rows, `build_links`, `wehago.load_sales`, then 손익, 계산서, and with a snapshot `match_requests`, 프로젝트, 프로젝트집행 with `projects=links['projects']`, 위하고대조 with the 프로젝트 rows, `xchk_meta` and `read_bank`) -> `cross_checks` -> pre-check of every target -> step A (CSV write, all-or-nothing) -> read-only listings on the replaced folder -> step B (`변환결과.txt`). A step B failure keeps the new CSVs, prints the error and exits 7.
- `read_bank` reads `계좌잔액.csv` / `입출금내역.csv` with `util.read_csv` only (None when missing or unreadable, never written, D-48).
- `[파일 사이 대조]` (five Checks, counted in `대조 불일치`, source side = 손익.csv): 손익 직접비 = 프로젝트집행 원가 줄 합계 259,500,000; 손익 직접비 = 위하고대조 (도) 원가 259,500,000; 손익 매출 = 위하고대조 매출 194,000,000; 손익 프로젝트 미연결 직접비 = 위하고대조 미연결원가 1,100,000; 손익 프로젝트 미연결 직접비 = 프로젝트집행 프로젝트.csv에 없는 번호의 원가 부분 1,100,000 (전표 22 '' 800,000 + 전표 23 '26999' 300,000). A check runs only when both files were written; D-50 (rows naming 5103 sum to 165,000,000) is asserted in the test on the written CSV.
- Snapshot money lines appear as `  대조 ... → 일치` exactly as the plan quotes (사전견적 820,000,000 / 0건, 실행가 610,000,000 / 1건, 지급요청 8 = 3 + 4 + 1, 265,264,000, 미확인 1건).
- D-46: `_kept_invoice_reason` builds `[계산서.csv] 만들지 않음 — <reason> → 기존 계산서.csv 유지 (갱신 안 됨, 작성일 YYYY-MM-DD)` (reason `매출 계산서 엑셀 없음` for state 자료 없음, the `load_sales` reason otherwise, e.g. a bad header first); with no 계산서.csv the line is `자료 없음 (매출 계산서 엑셀)` and `data.load` / `calc.compute` report the invoice data as missing (`in_missing`, `s5.issued` None), never 0. No snapshot -> `[<name>] 만들지 않음 — 인트라넷 스냅숏 없음 (기존 파일 그대로)` for 프로젝트, 프로젝트집행, 위하고대조 (also on stdout, bracket form).
- Listings in `변환결과.txt` (before the backup line, `대조 불일치 N건` stays the last line): `자금일정.csv와 겹칠 수 있는 줄 N건 (자금일정.csv는 바꾸지 않음)` with one `  겹침 ...` line per pair (a 출금/지급 row whose 금액 equals an unpaid 프로젝트집행 row's 공급가액 or 공급가액+부가세 and whose project digits or `norm_vendor` match; 1 with the added 2026-11-13 / 44,000,000 / 26201 / 가상음향 row, 0 on the plain sample; an unreadable 자금일정.csv reads `판단 불가`, not 0) and `보고서 입력 확인 필요 N건` with `  확인 <file> <line>번째 줄: <message>` (4 on the sample: 프로젝트집행 rows with '', 26999, 26299 and P26207; same N as `data.load`).
- Handoff notes applied: `build_execs(..., projects=links['projects'])`; Table.notes that already start with two spaces are written raw (no `  알림 ` prefix); `written=False` invoices keep the old file; bank/meta/match wired as 02-06 asked.
- `변환.py` docstring describes the five files; `main` prints `res.lines`: tables, 프로젝트 연결, 이전 파일, `대조 불일치`, overlap count, input-check count, `대조 내용: <path>`.

## Commits

| Task | RED | GREEN |
|---|---|---|
| 1 tracer (wiring, cross-file checks, snapshot lines) | 42d28fa test(02-07): RED Task 1 tracer | c8ed1b8 feat(02-07): GREEN Task 1 tracer |
| 2 (degraded runs, locks, rerun, listings, stdout) | 8c29a43 test(02-07): RED Task 2 | 8fe428c feat(02-07): GREEN Task 2 |

(`commits: 4` is `git rev-list --count 6d19215..HEAD` before this summary's own docs commit.)

## Tests

Full suite 854 -> 877 (+23), all OK. New: TestConvertEndToEnd 11, TestConvertDegraded 5, TestConvertRerun 2, TestConvertListings 5 (each also run alone with `-k`, ran >= 1). Protected-file diff `git diff --quiet cbc5497 -- ceo_report/calc.py ceo_report/data.py ceo_report/intranet.py ceo_report/snapshot.py 실행_주간.bat 실행_월간.bat 실행_승인검토.bat` exits 0; `git status --porcelain -- 입력 수집` is empty; convert.py, 변환.py and the new test parse with `ast.parse(..., feature_version=(3, 8))`. approval.py, approval_render.py, 승인검토.py untouched.

### RED evidence and fake-RED disclosure

- Task 1 RED: `FAILED (failures=7, errors=1)` of 10. Two tests passed before the code existed (manual/bank files untouched; previous 손익.csv kept in a stamp folder): they pin behaviour that must not break.
- Task 2 RED: `FAILED (failures=6)` of 12. **Six tests were not a real RED** and pass on the Task 1 code: no snapshot (the 3 `인트라넷 스냅숏 없음` lines and byte-identical files come from the tracer wiring), no sales file and no 계산서.csv (`자료 없음` line and calc `in_missing`), each locked target incl. 변환결과.txt (the single-step write of Task 1 already replaced nothing), both Rerun tests (builders already carry and are idempotent) and the RRN test (masking is in `table_bytes`/`_text_bytes`/`_say` and the snapshot writer). The real RED were: kept-with-작성일 line, bad-header reason line, overlap 0 / 1, input-check listing, stdout order.

## Deviations from Plan

**1. [Rule 1/3 - existing tests]** Three assertions in `tests/test_convert.py` (written by 02-01 when only 손익.csv existed) were updated because `run` now also writes 계산서.csv: the backup line `(손익.csv, 계산서.csv)`, removing both files before the "no backup folder" test, and the folder listing `["계산서.csv", "변환결과.txt", "손익.csv"]`. Commit c8ed1b8.

**2. [Plan wording] 건 suffix.** Builders print counts as plain numbers (their tests say `원본 0 · CSV 0`) but this plan's truths say `원본 0건 · CSV 0건`. `convert.check_text` adds `건` to checks whose label is a count (프로젝트 수, 지급요청 건수, 지급요청 금액 미확인, labels containing 건수 or ending in 빈칸 / 줄 수 / 원가 줄). A label-based rule is fragile; a `unit` field on `Check` would be cleaner but needs builder edits this plan forbids.

**3. [Rule 2] Pre-check of 변환결과.txt.** The plan's step A / step B split would let a locked 변환결과.txt fail after the CSVs were replaced. I added `precheck_writable` for all targets before step A so "any locked target -> nothing replaced" holds for the text file too.

**4. [Rule 2] All five tables unwritten when the books are bad (exit 3).** Previously only 손익.csv was listed; now all five show `만들지 않음 — WEHAGO 장부를 쓸 수 없음`, and stdout uses the bracket form `[<name>] 만들지 않음 — ...` for every unwritten table.

**5. [Rule 2] Unreadable previous files.** Besides 손익.csv, an unreadable previous 계산서 / 프로젝트 / 프로젝트집행 gets a note that carried rows could not be moved (the original is in the backup folder).

**6. [Heuristic]** The WEHAGO rows of 프로젝트집행 are recognised in `cross_checks` as rows whose 근거 starts with `WEHAGO ` and whose 상태 is not 집행계획미요청, because `extra['cost_portions']` has None both for unknown amounts and for non-WEHAGO rows (builders unchanged). A WEHAGO row with an unknown cost portion makes the check `판단 불가`, not 0.

**7. [Commit trailer]** Commits use the `Co-Authored-By: Claude Opus 5.5` line of the task template (02-04 .. 02-06 used the harness's Sonnet line); `Claude-Session` is the same.

**8. [Process]** I did not write the `.git/gsd-plan-head-before-02-07` ledger file; `plan_head_before` is `6d19215` (HEAD before the first RED commit), the same value, so `commits: 4` is correct.

## Notes on overstating / understating

- The 중복 가능 / ambiguous-group rows of 02-04 are written to 프로젝트집행.csv as before (may overstate); the `지급요청 건수` and `금액` checks count them (8 = 3 + 4 + 1, 265,264,000), and `변환결과.txt` carries the 중복 가능 notes. This plan adds no new rule that could understate an outflow. The 자금일정 overlap list only reports: `자금일정.csv` is never changed, so a payment present in both files may still be counted twice by the report until the user removes one; the count line makes that visible.
- Cash outflows of unreadable `자금일정.csv` give `판단 불가`, not `0건`.

## Not verified

- Python 3.8 runtime (only `ast.parse(..., feature_version=(3, 8))`; runtime 3.13) and Windows file locking: locks are simulated with `mock.patch` on `_check_writable`; no real Excel-held file was tried.
- Real WEHAGO downloads, real snapshot, real `입력/`, `수집/` or realbooks: not opened; all data synthetic. `git status --porcelain -- 입력 수집` is empty.
- The same-second rerun with a real clock (the rerun test fixes `now` and varies only the stamp; with `datetime.now()` the `변환 시각` row of 위하고대조.csv differs between runs by design).
- `report`-level checks on the converted folder (plan 02-10) and the `실행_변환.bat` double click.
- REQUIREMENTS.md checkboxes not ticked (orchestrator does it); ROADMAP.md not edited (as in 02-05 / 02-06).

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model: T-02-29 (pre-check of all targets, `written=False` files untouched; lock tests for all six targets), T-02-30 (five cross-file Checks; B3 request lines; 자금일정 overlap only reported), T-02-32 (RRN test over every written file and stdout, also with a masked snapshot title and a 자금일정 거래처), T-02-33 (degraded runs write what is provable and name what was kept).

## Self-Check: PASSED

- Files exist: ceo_report/convert.py, 변환.py, tests/test_convert_e2e.py (FOUND).
- Commits exist: 42d28fa, c8ed1b8, 8c29a43, 8fe428c (FOUND in git log).
- `python3 -m unittest discover -s tests` -> Ran 877 tests, OK.
