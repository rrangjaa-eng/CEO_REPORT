# QA Report: 보고서.py and 승인검토.py

- Date: 2026-11-02
- Branch: claude/project-thread-jkflss (starting point 3b17a8a)
- Method: gstack /qa, Standard tier (critical, high and medium findings get fixed). Every fix has a failing test written first and its own `fix(qa): ...` commit.
- Environment: Linux container on Python 3.13. The code is also checked to parse as Python 3.8 (`ast.parse(..., feature_version=(3, 8))`). Headless Chromium 1243 makes the PDFs, and Playwright (node) drives the approval screen.
- Data: synthetic only. Inputs come from `tools/make_sample.py` (입력양식/샘플), snapshots from `tests/test_approval.py write_fake_snapshot`, and WEHAGO books from `tests/test_wehago.py write_fake_books / write_xlsx`. No real 입력/, 수집/ or realbooks data was opened. `--수집 함` was not run against a network.
- Tests: 502 before, 519 after the first round (17 new in `tests/test_qa.py`), 529 after the L2 fix (10 more in `tests/test_qa.py`). The full suite passes.

## Health score

| Category (weight) | Before | After | Notes |
|---|---|---|---|
| Functional (20%) | 27 | 91 | Before: B1 critical, B2 high, B3/B5/B7 medium. Left: L3, L4, L6 low |
| UX (15%) | 92 | 100 | B4 |
| Console (15%) | 100 | 100 | No JS errors in any Playwright run |
| Accessibility (15%) | 100 | 100 | Keyboard-only flow works and focus has a 2px outline |
| Visual (10%) | 97 | 97 | L5 |
| Performance (10%) | 100 | 100 | Each toggle recalculates instantly (existing test: under 1 s) |
| Content (5%) | 94 | 97 | B6 fixed; L1 left |
| Links | not scored | not scored | Single-file pages, no navigation |
| **Score** | **82** | **98** | Weighted over the tested categories (0.90). 96 before the L2 fix (B7), 97.5 after |

Summary: QA found 12 issues and fixed 7 (all of them verified). Health went from 82 to 98. L2 was first deferred and then fixed as B7.

## Flows tested

### 보고서.py (주간/월간 reports, CEO and 경영관리 editions)
- 주간 and 월간 runs with PDFs through headless Chromium, and with `--pdf 안함`.
- `--출력` paths with spaces, Korean text, `#` and `%`. HTML and PDF are both made, and the file URL is encoded correctly.
- 기준일 values tested: 2026-11-01 (Sunday), 2026-11-07 (Saturday), 2026-10-31 and 2026-12-31 (month ends), 2027-01-01 and 2027-01-15 (January and year boundary), 2024-02-29 (leap day). All periods were correct.
- Bad dates (2026-13-01, 2026-02-30, abc) give `기준일 형식 오류` and rc 2. A 시작일 later than the 기준일 gives rc 2. An unknown 유형 gives argparse rc 2.
- A missing 입력 folder prints a Korean help message with rc 2. An empty 입력 folder gives a report with 19 input issues, and balances show 미확인 (not 0).
- The whole input folder saved as cp949 produces byte-identical HTML to the UTF-8 BOM version.
- Garbled bytes, a 0-byte file, a header-only file, a UTF-16 file, a tab-separated file and a title row above the header were tried. These found B1, B2 and L3.
- Without a browser, the run makes HTML only and prints a Korean hint. With a browser that exits without a PDF, the run found B6.
- Running twice in the same minute overwrites the same 기준일 files. This is intended, because the name comes from the 기준일 and the inputs are the same.
- `--출력` set to an existing file or an unwritable path found B4.
- The CEO and 경영관리 first screens produce identical text for every number.

### 승인검토.py (approval screen)
- Last-snapshot mode. Also tested: a missing 수집 folder (rc 2), a bad 기준일 (rc 2), a missing 입력 folder (rc 2), `--최대페이지 0` (argparse rc 2), a 기준일 on a weekend, at year end (the 8 weeks cross into 2027), and before the balance date (start shows 미확인).
- Two runs in the same minute with different 기준일 found B3.
- Playwright on Chromium at 1280px: each of the 4 checkable requests was toggled. The selections tried were all, none, each one alone, each one removed, and 10 random subsets (20 in total). For every selection the headline low, low day, estimated low, check sum, all 8 week rows (in, out, est, min, end, level) and every per-row "빼면/넣으면" value matched a fresh Python `scenario()` for the same selection. There were 0 mismatches.
- 전부 체크 and 전부 해제 by mouse and by keyboard (Enter and Space) work. The tab order is: attention links, then 전부 체크, 전부 해제, then the request boxes. Space toggles a box, and the focus outline is visible.
- With JS disabled, the headline (143.2 · 2026-12-25), start line, 8 week rows and every table still render from the HTML.
- At 390px the page itself has no horizontal scroll and wide tables scroll inside their box. At 1280px nothing overflows. L5 is cosmetic.
- Print to A4 PDF gives 5 pages, and the headline and start line are on page 1.
- Start balance 542.4 and 잔액 기준일 2026-11-02 match the report's 사용 가능액 and 은행 기준일.

### WEHAGO folder states (via the CLI and fake books)
- Tested: no folder, stale books (2026-09-01), header mismatch, an extra column, duplicate files of one kind (older date plus a `(1)` copy), a `~$` lock file, an xlsx that is really HTML, only a .csv or .xls of one kind, an upper-case `.XLSX` extension, file names without a date, and books dated after the 기준일.
- Every state gives a sensible Korean message. 판단 불가 means the schedule falls back to the intranet basis, which is more conservative (98.2 against 143.2 with books). No case crashed. L4 is a note.

## Bugs fixed

| # | Severity | Commit | What was wrong | Fix |
|---|---|---|---|---|
| B1 | Critical | 9cf168a | If 자금일정.csv or 프로젝트집행.csv was missing, unreadable (UTF-16, garbled) or lacked its amount/date columns, those payments counted as 0. Both reports showed a safe-looking lowest balance (sample: 542.4 instead of 19.8 백만원), and the approval screen did the same. This understated cash outflows. | The calculated balances and lowest balance now show 판단 불가 and name the file. The 4-week payment KPI says which file is missing, 경영관리 gets a 높음 자료 risk, and both CLIs print the reason. The start balance is still shown. Files: `ceo_report/data.py` (OUTFLOW_KEYS, `d.out_missing`), `calc.py`, `render.py`, `approval.py`, `approval_render.py` (`data.no_calc`, also in the JS), `보고서.py`, `승인검토.py`. |
| B2 | High | 7d0fa20 | If a CSV had a title row above the table (a common Excel habit), the title was read as the header and every row was dropped. | `read_csv` now uses the first of the top 6 rows that has every required column as the header. It notes the skipped lines and keeps the real file line numbers. |
| B3 | Medium | a16075d | The approval screen name `승인검토_YYYYMMDD_HHMM.html` came from the clock, so a second run in the same minute silently overwrote the first. | Later runs now get `_2`, `_3` and so on. The new names are still git-ignored under 출력/. |
| B4 | Medium | c53e8c2 | If `--출력` was an existing file or an unwritable folder, both tools stopped with a traceback. | Both now print a Korean message naming the folder and exit with rc 7. The exit code is documented in both docstrings. |
| B5 | Medium | d6eae92 | A CSV that could not be opened (on Windows, a CSV that is open in Excel raises PermissionError) crashed both tools. | It now appears in 입력 자료 확인 필요 as "파일을 열 수 없음 (엑셀에서 열려 있으면 닫고 다시 실행)", and the file is treated as unreadable. For a payment file, B1 then applies. |
| B7 (was L2) | Medium | `fix(qa): missing or unusable invoice CSV shows 자료 없음, not 0` (see git log) | If 계산서.csv was missing, unreadable or lacked a key column, the first screen showed 발행 후 미수 0.0, 발행금액 0.0, 미발행금액 = the whole contract, 완료 후 미발행 3건 and 향후 4주 입금예정 0.0, and 경영관리 got 미발행 risks built on a 0 issued amount. The missing-file message promised '자료 없음' but nothing used it. | `data.py` records `d.in_missing` (`INFLOW_KEYS`: 프로젝트번호, 공급가액, 부가세, 입금예정일, 입금액), the same way B1 records `out_missing`. `calc.py` then leaves the invoices out: 발행금액, 미발행금액, 발행 후 미수 and 입금예정일 경과 are None (totals and per project), no 계산서 inflows go into the schedule, and no 수금 risks are built. `render.py` shows '자료 없음 (계산서.csv)' in those cells (first screen and section 5, both editions). The 4-week inflow KPI reads 자료 없음 and names the file, keeping the 자금일정 part in the sub line. The undated and past inflow cells say the 계산서 part is missing. The lowest balance is still computed (missing inflows only make it lower) and its KPI says 계산서 입금예정 미반영. 경영관리 gets a 중간 자료 risk. The approval screen shows the reason under the headline and in 확인 필요, and both CLIs print it. Sample output is byte-identical. |
| B6 | Low | 57b4745 | A PDF failure printed a message without the file name or a next step. A timeout printed Python's English text with the temporary profile path in it. | Each failure now names its PDF, a timeout reads "브라우저가 120초 안에 끝나지 않음", and the run ends with the HTML → 인쇄 → 'PDF로 저장' fallback. |

## Left open (deferred)

| # | Severity | What | Why it is left |
|---|---|---|---|
| L2 | Medium | Fixed: see B7. | - |
| L1 | Low | argparse errors (unknown 유형, bad choice) are printed in English ("invalid choice"). | Cosmetic. The exit code is right and the usage line shows the Korean options. |
| L3 | Low | Excel "유니코드 텍스트" (UTF-16, tab-separated) is not read. | After B1/B5 it is flagged and handled safely: an unreadable payment file gives 판단 불가, never a number. The 보고서.py usage text already says to save as 'CSV UTF-8' or 'CSV', and the B1 risk item repeats it. |
| L4 | Low | WEHAGO books dated after the 기준일 (a past-기준일 what-if) are used without a note. | This only matters for back-dated what-if runs. Normal use has 기준일 = today. |
| L5 | Low | At 390px the headline date wraps mid-date ("2026-12-" / "25"). | Cosmetic. The design review owns the headline layout. |
| L6 | Low | `--기준일 ""` silently means today. | This only happens when someone types an empty argument. |

## Still needs the Windows PC
- Double-clicking 실행_주간.bat, 실행_월간.bat and 실행_승인검토.bat (chcp 65001 output, Python detection, `pause`). This is ledger items 1-2 in WINDOWS.md.
- Edge/Chrome PDF on Windows (the `C:\Program Files` paths, a profile folder while Edge is already open, the Acrobat lock on an old PDF).
- A real Excel lock on an open input CSV. B5 is simulated here with an OSError. Confirm that the message appears and the run finishes.
- `--수집 함` and `--구조점검` against the real intranet. Only the fake-site tests cover these.
- Real WEHAGO downloads: the file names, an `.xls` that is really HTML, and a `~$` lock file while the workbook is open in Excel.
- Opening 출력/승인검토_*.html in Edge: toggle requests, check behaviour with the network unplugged, and check phone width (ledger item 2).
- Excel saving cp949 vs "CSV UTF-8" from the real workbook, and whether its sheets carry title rows (B2).
