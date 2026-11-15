---
phase: 02-source-conversion
plan: 01
subsystem: source-conversion
tags: [wehago, conversion, 손익, safe-write, backup, settings, tdd, python-stdlib]
status: complete

requires:
  - phase: 01.1-approval-screen
    provides: "wehago.load_books / read_book (xlsx reader), util.read_csv / mask_rrn / won, data.SCHEMA"
provides:
  - "변환.py (CLI: --기준일 --입력 --수집폴더 --위하고폴더; exit 0/2/3/7) and 실행_변환.bat"
  - "ceo_report/convert.py: GENERATED, MANUAL, DEFAULT_CONFIG, Config, Check, check_result, Table, Result, cell_amount, cell_date, table_bytes, write_table, read_config, read_prev, plan_backup, write_files, WriteFailed, result_lines, run"
  - "ceo_report/convert_pl.py: build_pl(books, cfg, prev_rows, links=None) -> Table('손익.csv')"
  - "wehago.load_books(folder, asof, None) (age check skipped) and journal row key 'sort' (구분)"
  - "tests/test_convert.py: PL_EXTRA, FAKE_PL_JOURNAL, jl_sort, write_convert_books, convert_input, run_convert, read_result_lines (+ helpers converted, cli_argv, tree, sha, add_settings)"
affects: [02-02 .. 02-10 (all build on convert.run / Table / write_files), REQUIREMENTS SRC-01 (orchestrator ticks it)]

plan_head_before: c7972030b0afcae275b26716549b338915ad3260
actuals:
  tokens: 13700
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - "Account codes and marks live only in convert.DEFAULT_CONFIG; convert_pl.py reads cfg (grep for the default codes in convert_pl.py is 0)"
    - "One write path for every generated file: lock check (r+b) -> temp '<name>.변환중' -> copy old files to 입력/이전/<stamp>[_n]/ -> os.replace; names outside GENERATED raise ValueError"
    - "Unknown amount = '' in the CSV and 'CSV 미확인 -> 판단 불가' in 변환결과.txt, never 0"

key-files:
  created:
    - ceo_report/convert.py
    - ceo_report/convert_pl.py
    - 변환.py
    - 실행_변환.bat
    - tests/test_convert.py
  modified:
    - ceo_report/wehago.py
    - tests/test_review.py

key-decisions:
  - "Undated P&L lines count in the check's source total, so the check reads 불일치 (counted in '대조 불일치 N건') and a note lists them; the plan text said 'dated' only, but an undated cost line that is not in any month must not pass as 일치"
  - "write_files(input_dir, payloads, stamp, backup=None) and plan_backup(...) are separate so the 변환결과.txt '이전 파일' line can name the folder before writing and plan 02-07's step B can reuse the same 이전 folder"
  - "Every CSV cell goes through mask_rrn (not only text cells); an amount of 13+ digits (>= 1 trillion won) would be masked, accepted because the 6+7-digit invariant is the stronger rule"
  - "WEHAGO line in 변환결과.txt prints the books state as 'ok' (PATTERNS 6 '<state>'); not-ok prints the reason from load_books"

requirements-completed: []

duration: ~10min
completed: 2026-11-02
---

# Phase 2 Plan 01: WEHAGO books -> 손익.csv conversion (tracer) Summary

**One command (`변환.py` / `실행_변환.bat`) reads the WEHAGO 분개장 and writes 손익.csv company rows per month (매출 / 직접비 / 공통비, 잠정) with the old file backed up under 입력/이전/<시각>/, manual files untouched, and source-vs-CSV totals in 입력/변환결과.txt; account codes come from 설정.csv.**

## What was built

- `ceo_report/convert_pl.py` classifies each 분개장 line by account code from cfg (매출 = revenue codes 대변-차변, 직접비 = prefix + (도) mark, 공통비 = prefix, other 4..9 codes listed as "손익.csv에 넣지 않은 손익 계정"), groups by month of lines that have a date, applies the Q-3 rule (a year with a `변환_결산구분` line is final, '' 잠정), and carries over non-WEHAGO rows of the previous 손익.csv unchanged.
- `ceo_report/convert.py` has the config reader (12 `변환_*` items, notes on bad/blank/unknown values, 설정.csv only read), Table/Check, the safe write path, and the 변환결과.txt writer.
- On FAKE_PL_JOURNAL: 2026-09 = 100,000,000 / 10,000,000 / 2,000,000 / Y and 2026-10 = 94,000,000 / 249,500,000 / 4,500,000 / Y; checks 194,000,000 / 259,500,000 / 6,500,000 all '일치'; `calc.compute(..., 'monthly', 2026-10-31)` reads the file with no new 손익.csv input issue and the expected cur / ytd numbers.

## Commits

| Task | RED | GREEN |
|---|---|---|
| 1 tracer | 5f1615b test(02-01): RED Task 1 tracer | 1399e65 feat(02-01): GREEN Task 1 tracer |
| 2 safe overwrite | 84a3114 test(02-01): RED Task 2 | 42c4f3f feat(02-01): GREEN Task 2 |
| 3 config / 잠정 / launcher | 2430b63 test(02-01): RED Task 3 | a98f5cd feat(02-01): GREEN Task 3 |

## Tests

Full suite 529 -> 572 tests (+43), all OK (`python3 -m unittest discover -s tests`). New: TestConvertTracer 8, TestConvertSafety 17, TestConvertConfig 9, TestConvertProvisional 6, TestConvertLauncher 3; tests/test_review.py name tuples now include 실행_변환.bat (TestLaunchersPushd and test_launchers_tell still pass). `git diff --quiet cbc5497 -- calc.py data.py approval.py approval_render.py intranet.py snapshot.py 승인검토.py 실행_주간.bat 실행_월간.bat 실행_승인검토.bat` exits 0; all new .py parse with `feature_version=(3, 8)`; `git ls-files '*.xlsx' 입력 수집` is empty.

### RED evidence (last line of each failing run)

- Task 1: `FAILED (errors=7)` of 8 (one test, `test_unknown_book_date_is_still_stale_without_an_age_limit`, passed before the code: it pins an existing behaviour, so it is a guard, not a RED).
- Task 2: `FAILED (failures=4, errors=6)` of 17. Seven tests already passed on the Task 1 code and are guards (age never stops, git-ignored paths, carry-over order/text, manual files untouched, missing 입력 created, no backup folder when nothing existed, 주민번호 masking): the Task 1 code already satisfied them by construction.
- Task 3: `FAILED (failures=9, errors=6)` of 21 run (config/launcher classes plus the two existing launcher tests). Six passed already: default config, 설정.csv never written, the three 잠정 tests for closing lines that the plan told Task 1 to implement, and the undated-line test.

## Deviations from Plan

**1. [Rule 1 - Bug] RED test had a wrong row count.** The Task 1 RED test expected '[손익.csv] 만듦 2줄' / '손익.csv 만듦 2줄'; the file holds 5 rows (2 WEHAGO + 3 carried over). Fixed in the GREEN commit 1399e65 (test change only).

**2. [Decision, plan said 'dated'] Undated P&L lines are in the check's source total.** build_pl lists them ('날짜 없는 손익 줄 N건 (직접비) 700,000') and the category check shows 불일치 (source includes them, the CSV cannot). Reason: a cost line with no date is in no month, so a plan-literal 'known dated' source would show 일치 while money is missing from the CSV.

**3. [Rule 2 - missing safety, additions not in the plan]**
- `대조 판단 불가 N건` line (before '대조 불일치 N건', also on stdout) when a check cannot be decided (a month has a P&L line with no amount).
- `이전 손익.csv를 읽지 못해 WEHAGO 외 출처 줄을 옮기지 못함 (입력/이전/<시각>/ 에 원본 보관)` when the previous 손익.csv exists but cannot be parsed, so carried rows are never lost silently.
- `이전 손익.csv의 WEHAGO 줄 N건(회사 a · 팀 b)은 새로 만든 줄로 바꿈` note (see Risks).
- `설정 변환_xxx 알 수 없는 변환 항목 → 무시` for misspelt items; `설정.csv를 읽지 못함 → 변환 설정 기본값 사용`.
- `없는 수동 파일 (사람이 관리, 만들지 않음): ...` line; '손대지 않은 파일' lists only the manual files that exist (PATTERNS 6 showed all six).
- `이미 바뀐 파일` line on exit 7 if an os.replace fails after earlier files were replaced (cannot happen after the lock pre-check except for races).

**4. [Interface detail]** write path split into `plan_backup` + `write_files(..., backup=None)` and `_check_writable` / `_write_temp` seams (tests patch them to simulate Excel locks and a full disk); `Config` is a dict subclass with `.from_file` so `cfg == defaults` holds.

## Risks and things to know (not hidden)

- **Overstate / understate:** no cash-outflow rule fires in this plan (the 중복 가능 / 요청미지급 rows start in plans 02-04+). Two cases the user should read in 변환결과.txt: (a) 6xxxx accounts without the (도) mark are NOT in 직접비; they are listed under '손익.csv에 넣지 않은 손익 계정' and are not part of the check, so 직접비 could be lower than the user's own idea of cost; (b) 8xxxx lines without (판) ARE counted in 공통비 and listed ('공통비에 넣음'), which is the safe direction.
- **2025-12 zero row (Q-3 truth):** a month that has only a closing line (e.g. 결대 dated 2025-12-31 in a 2026 download) gets a company row 0 / 0 / 0 with 잠정 '' because "a month with no category line = 0 (the books cover that month)". If the download does not really cover December, that 0 is an assumption; the plan's truth 8 requires it.
- **팀 rows disappear until plan 02-03:** the sample's old `WEHAGO ... 팀` rows are replaced (truth 1 requires it); the monthly report has no team P&L from the converted file until 02-03 adds team/project rows. The note above says so in 변환결과.txt.
- A hard kill during writing can leave `<name>.변환중` temp files in 입력/ (git-ignored); the next run overwrites them.
- 장부 기준일 'N일 이전' is printed whenever the book date is before the 기준일 (also for 2 days), as P1-6 says.

## Not verified

- `실행_변환.bat` was not run (no Windows/cmd here); only its bytes (UTF-8, CRLF, no BOM, `chcp 65001` first), structure (identical to 실행_월간.bat except 3 lines) and the name tuples are tested. Needs the human Windows check (plan 02-10 records it).
- Real Excel file locking was only simulated (mock of `_check_writable`; the tests run as root, so chmod cannot be used).
- Runtime was Python 3.13; Python 3.8 compatibility checked only by `ast.parse(..., feature_version=(3, 8))`.
- No real company data was opened (`입력/`, `수집/` untouched); all fixtures are generated in temp folders.

## Known Stubs

None. (`인트라넷 스냅숏: 없음` in 변환결과.txt is the planned placeholder that plan 02-03 fills.)

## Threat Flags

None beyond the plan's threat model (T-02-01..04, 06 mitigated by tests: mask_rrn on every cell and printed line, GENERATED-only writes with ValueError, tree-diff and sha256 tests for manual files, lock/temp/backup order with exit 7, git check-ignore test for 입력/이전/ and 입력/변환결과.txt).

## Self-Check: PASSED

- Files exist: ceo_report/convert.py, ceo_report/convert_pl.py, 변환.py, 실행_변환.bat, tests/test_convert.py (all FOUND).
- Commits exist: 5f1615b, 1399e65, 84a3114, 42c4f3f, 2430b63, a98f5cd (all FOUND in git log).
- `python3 -m unittest discover -s tests` -> Ran 572 tests, OK.
