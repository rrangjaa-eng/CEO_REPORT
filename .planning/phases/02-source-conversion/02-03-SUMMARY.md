---
phase: 02-source-conversion
plan: 03
subsystem: source-conversion
tags: [wehago, snapshot, linking, 손익, team, project, d-38, d-40, tdd, python-stdlib]
status: complete

requires:
  - phase: 02-source-conversion
    provides: "02-01: convert.run / Table / Check / write_files, build_pl company rows; 02-02: linking.requests_of / projects_of / read_links / link_costs / link_revenue / unused_links"
provides:
  - "convert.read_latest_snapshot(collect_dir) -> (snapshot or None, 변환결과 line); a missing or unreadable snapshot never stops the run"
  - "convert.build_links(books, cfg, snap, input_dir, asof, now) -> {costs, revenue, projects, snapshot, requests, overrides, notes, unused}; kept on Result.links for plans 02-04..02-08"
  - "convert.link_lines(links) / link_stdout_line(links): the [연결] section of 변환결과.txt and the stdout line"
  - "convert_pl.build_pl(books, cfg, prev_rows, links): 회사, 팀, 프로젝트 and 미연결 rows per month plus per-month unit-sum checks"
  - "tests/test_convert_pl.py: convert_with_snapshot(test, links_rows=None, snapshot=True, journal=..., setup=None) -> Ran(.code .res .csv_rows() .wehago_rows() .result_lines())"
affects: [02-04 (프로젝트집행 uses Result.links), 02-05, 02-06, 02-07 (reuses Result.links), 02-08 (D-47)]

plan_head_before: 24ec30685de72b707dcbe31a1ad4b194540a31a2
actuals:
  tokens: 10200
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - "Per month: 회사 row, then 팀 rows (name order, 미연결 last, only with a snapshot), then 프로젝트 rows (projects_of order; no snapshot: key order; 프로젝트 미연결 last)"
    - "A unit row exists only when it has a linked line in that month; 공통비 on 팀/프로젝트 rows is always ''; an unknown amount in any line makes the cell '' and its checks '판단 불가'"
    - "Check per month x measure(매출, 직접비) x unit(팀별 only with a snapshot, 프로젝트별): 회사 cell = sum of unit cells including 미연결"

key-files:
  created:
    - tests/test_convert_pl.py
  modified:
    - ceo_report/convert.py
    - ceo_report/convert_pl.py
    - tests/test_convert.py

key-decisions:
  - "Task 1 already writes the '프로젝트 미연결' row (not only linked projects): an unlinked amount may never be dropped (D-40), not even in an intermediate commit"
  - "The link hint line ('프로젝트연결.csv에 ... 연결됩니다') is printed once, and only when at least one 미연결 line is listed"
  - "read_links note '프로젝트연결.csv 없음 (수동 지정 0건)' is not printed in the [연결] section (the 원가 줄 line already says 수동 0건 and the '없는 수동 파일' line names the file); every other read_links note is printed as '알림'"
  - "Unreadable snapshot writes the same 손익.csv rows and the same note as no snapshot ('팀별 손익 없음 (인트라넷 스냅숏 없음)'); only the 인트라넷 스냅숏 line differs"
  - "Unknown amounts in the summary lines are shown next to the sum as '(금액 미확인 N건)'; the stdout line does the same for the unlinked totals"

requirements-completed: []

duration: ~25min
completed: 2026-11-02
---

# Phase 2 Plan 03: 손익 by team and project from the books + snapshot (D-38, D-40) Summary

**convert.run now reads the newest intranet snapshot, links every (도) cost line and 41200 revenue line with linking.py, and writes 팀 and 프로젝트 rows (with explicit 미연결 rows) into 손익.csv; 변환결과.txt proves that for every month the team rows and the project rows each add up to the company cell, and lists every unlinked line with the key to copy into 프로젝트연결.csv.**

## What was built

- `convert.run`: config -> books -> snapshot (`read_latest_snapshot`) -> `build_links` -> `build_pl(..., links)` -> safe write. The link inputs live on `Result.links` (costs, revenue, projects, snapshot flag, requests, overrides, notes, unused) so plan 02-07 does not recompute them.
- `build_pl`: on the FAKE data the 2026-10 block is 회사 -> 팀 1팀 / 2팀 / 미연결 -> 프로젝트 26201 / 26220 / 26221 / 26203 / 프로젝트 미연결, exactly the order and values of must_have truth 1 (a test compares the whole 12-row list as 8-tuples and then the 3 carried 인트라넷완료보고 rows).
- Without a snapshot: no 팀 rows (note `팀별 손익 없음 (인트라넷 스냅숏 없음)`), project rows by code sorted by key with 대상 = key alone; with a manual link and no snapshot the key is accepted as is.
- Checks: 8 lines on the fixture (`  대조 매출 2026-10 프로젝트별 합계(미연결 포함) = 회사: 원본 94,000,000 · CSV 94,000,000 → 일치`), 4 without a snapshot. They count in `대조 불일치 N건` / `대조 판단 불가 N건` like every other check.
- `[연결]` section of 변환결과.txt: 원가 줄 / 매출 줄 summaries (수동 · 코드 · 자동 · 미연결 with count and won), one `미연결 원가|매출 <date> <no>-<line> <거래처> <won> <적요> — <label>` line per unlinked line (cost first, then revenue, date / 전표번호 / 줄 order, no cap), the hint line, then `알림 프로젝트연결.csv <date> <no>-<line> → <project>: <reason>` for unused manual rows and `알림` for bad manual rows. Stdout gets `프로젝트 연결: 원가 미연결 N건 <won> · 매출 미연결 N건 <won> (변환결과.txt 목록)`.
- Manual link (2026-10-29, 22, 1, 26221): 26221 직접비 6,200,000, 1팀 46,200,000, 프로젝트 미연결 직접비 300,000, 원가 줄 `수동 1건 800,000`; the manual file's sha256 is unchanged and it is never created.

## Commits

| Task | RED | GREEN |
|---|---|---|
| 1 tracer | f4c4888 test(02-03): RED Task 1 tracer | 9c7de7a feat(02-03): GREEN Task 1 tracer |
| 2 팀/프로젝트/미연결, checks, [연결] | 7d277e9 test(02-03): RED Task 2 | 639705d feat(02-03): GREEN Task 2 |
| 3 no / unreadable snapshot | 0a16f34 test(02-03): RED Task 3 | dcce59c feat(02-03): GREEN Task 3 |

## Tests

Full suite 630 -> 657 (+27), all OK: `python3 -m unittest discover -s tests`. New: TestConvertPlTracer 5, TestConvertPlProjects 7, TestConvertPlLinks 6, TestConvertPlNoSnapshot 9 (each also run alone with `-k`, ran >= 1). `git diff --quiet cbc5497 -- ceo_report/calc.py data.py approval.py snapshot.py` exits 0; `ceo_report/linking.py` is not touched by this plan; convert.py, convert_pl.py and both test files parse with `ast.parse(feature_version=(3, 8))`.

### RED evidence (last line of each failing run)

- Task 1: `FAILED (failures=4)` of 5 (the guard "common cost is blank on every project row" passed because no project rows existed yet).
- Task 2: TestConvertPlProjects `FAILED (failures=4, errors=2)` of 7 (the "공통비 blank" guard passed vacuously on the Task 1 rows); TestConvertPlLinks `FAILED (failures=4)` of 6 (two passed: the run never creates 프로젝트연결.csv, and `Result.links` already existed from Task 1).
- Task 3: **no RED.** All 9 TestConvertPlNoSnapshot tests passed on the Task 2 code, because the no-snapshot / unreadable-snapshot mode (`read_latest_snapshot`, code-only links, no 팀 rows) was part of Tasks 1-2. The Task 3 tests are guards, not a proof that they drive the code. The `feat(02-03): GREEN Task 3` commit only updates the convert.py module docstring (no behaviour change). I also probed by hand a garbled 지급요청.csv, a missing 프로젝트목록.csv, an empty 수집정보.csv and a directory in place of a file: all return `읽지 못함 — <message>` without an exception (the corrupt-file case is pinned by a test).

## Deviations from Plan

**1. [Plan said "update in place", detail] tests/test_convert.py (02-01) changed.** Without a snapshot the run now also writes code-linked 프로젝트 rows, so the 02-01 tests that counted rows or took `rows[2]` were narrowed to WEHAGO 회사 rows through a new helper `company_rows(rows)`: row counts `5줄` -> `12줄` (and 6 -> 13 incl. header, 3 -> 10 in the missing-input-folder test), "carried rows" now `rows[-3:]`, and the 회사 rows are still asserted with identical values. One more change: the missing-amount test expected `대조 판단 불가 1건`; it is now 2 (the company revenue check plus the new 2026-10 프로젝트별 매출 check), with a comment. 02-01's `인트라넷 스냅숏: 없음` was not pinned by any test; the line now reads `인트라넷 스냅숏: 없음 — 자동 연결 안 함`.

**2. [Process] GREEN Task 2 commit was amended once.** The first GREEN Task 2 commit (45fe5a6) was made while one 02-01 test (the `판단 불가 1건` one above) still failed; I noticed it right after the commit, fixed the test and amended before any later commit. The resulting 639705d has a green suite.

**3. [Test fix] Task 3 test arithmetic.** My first expectation for the stdout line without a snapshot was `원가 미연결 2건 1,100,000 · 매출 미연결 4건 94,000,000`; the code was right (without a list 전표 23 `[26999]` is linked by code, so 원가 미연결 is 전표 22 only: 1건 800,000; revenue 31, 32, 38: 3건 94,000,000, which matches must_have truth 6). Fixed in the test before the RED commit.

**4. [Rule 2 - additions not named in the plan]**
- Note `팀·프로젝트 줄의 공통비는 비워 둠 (배분 규칙 없음)` in the 손익.csv section of 변환결과.txt.
- Team names `팀 미확인` (manual link to a project that is not in the list) and `팀 미지정` (blank 팀) as P3-1 says; both have tests.
- Summary lines show `(금액 미확인 N건)` when a basis has lines without an amount.
- The `읽지 못함` snapshot reason also catches `OSError` (listing the 수집 folder), not only `SnapshotError`.

## Notes on overstating / understating

- Nothing is dropped: every cost and revenue line is in exactly one project row (a coded / manual / automatic project or `프로젝트 미연결`), and the per-month checks prove it. Lines with no 전표일자 are in no month (the company rows exclude them too and 02-01 already notes them); they are still listed in the work list as `날짜 없음`.
- Auto-linking is conservative (02-02): shared or ambiguous candidates stay 미연결, so a project's linked cost can be lower than its true cost until the user adds a 프로젝트연결.csv row. The unlinked total is printed next to the linked totals in the summary lines and in the stdout line, as the 02-02 summary asked.
- 프로젝트 미연결 and 팀 미연결 carry the same amounts by construction (a line without a project has no team).
- No rule in this plan can overstate a cash outflow: the 손익 rows use the same amounts as the company rows (the '중복 가능' request rows start in plan 02-04).

## Not verified

- Python 3.8 runtime (only `ast.parse(..., feature_version=(3, 8))`; runtime was 3.13).
- A real WEHAGO download and a real intranet snapshot: only synthetic fixtures were used; no real company data was opened (`입력/`, `수집/`, realbooks untouched).
- `변환.py` / `실행_변환.bat` on Windows (the CLI is covered through `run_convert` on Linux only).
- A snapshot folder with a `.작성중` suffix is only tested as an empty directory (the ignore rule is `snapshot.latest_snapshot`'s, unchanged).
- Team rows for a project whose 팀 text in the intranet differs in spelling (e.g. '1팀 ' vs '1팀') are grouped by the text after `strip()` only; no further normalisation.

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model: T-02-14 (masked texts from wehago/linking pass `mask_rrn` again in `_text_bytes`; tests: no 6+7-digit run in 변환결과.txt, stdout, 손익.csv; the 전표 22 line reads `******-*******`), T-02-15 (8 per-month sum checks; 미연결 rows always written), T-02-16 (unreadable snapshot -> `읽지 못함 — <message>`, 손익.csv still written, exit 0).

## Self-Check: PASSED

- Files exist: ceo_report/convert.py, ceo_report/convert_pl.py, tests/test_convert_pl.py, tests/test_convert.py (all FOUND).
- Commits exist: f4c4888, 9c7de7a, 7d277e9, 639705d, 0a16f34, dcce59c (all FOUND in git log).
- `python3 -m unittest discover -s tests` -> Ran 657 tests, OK; `git diff --quiet cbc5497 -- ceo_report/calc.py ceo_report/data.py ceo_report/approval.py ceo_report/snapshot.py` exit 0.
