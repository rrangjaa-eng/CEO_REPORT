---
phase: 01-report-engine
reviewed: 2026-11-02T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - ceo_report/calc.py
  - ceo_report/data.py
  - ceo_report/render.py
  - ceo_report/util.py
  - 보고서.py
  - tools/make_sample.py
  - tests/test_report.py
  - 실행_주간.bat
  - 실행_월간.bat
  - .gitattributes
findings:
  critical: 3
  warning: 6
  info: 4
  total: 13
status: fixed
fixed_at: 2026-11-02
fix_summary:
  fixed: [CR-01, CR-02, CR-03, WR-01, WR-02, WR-03, WR-04, WR-05, WR-06]
  partial: [IN-04]
  not_attempted: [IN-01, IN-02, IN-03]
  skipped: []
  also_fixed: [verification-gap-first-screen-unknown-project-cost, D-04-first-screen-undated-counts]
---

# Phase 1: Code Review Report

**Reviewed:** 2026-11-02
**Depth:** standard
**Files Reviewed:** 10
**Status:** fixed (Critical and Warning all fixed; see Fix Status at the end)

## Summary

All 74 tests pass on Python 3.13 (Python 3.8 was not available to run). The partial-unknown cases the plans targeted are handled well: one blank account balance, blank invoice VAT, blank plan amounts and vendor sums. The failures are in the all-unknown and mixed-unknown paths. There, an unknown amount still becomes 0, or a figure is shown as if it were complete. This breaks the locked rule D-02 and D-09 in the chart, the first screen and the section totals.

HTML escaping is sound. Every CSV-sourced string in render.py goes through `esc()`, and `kv`/`table` only receive pre-escaped cells. I found no injection path. The PDF subprocess is called with an argument list and no shell, so there is no command injection. `tools/make_sample.py` has no defects beyond the notes below. I did not review its content line by line, since it only generates fixtures.

Each finding below marked "probed" was reproduced by running the code against a modified copy of the sample input.

## Critical Issues

### CR-01: Missing or all-unknown account balances become 0 cash, and the chart and minimum-balance figures are computed from 0

**File:** `ceo_report/calc.py:97,337-358` (display: `ceo_report/render.py:193-195,232`)
**Issue:** `ssum()` returns `(0, n)` when every value is unknown. The result is used directly as `total_bal`, `available` and `start_cash`. Probed: with `계좌잔액.csv` deleted, the first screen shows "현재 현금 0.0 백만원 · 0개 계좌 · 은행 기준일 자료 없음" and "사용 가능액 0.0". `s2["start"]` is 0, so the chart and the minimum balance are built from a fabricated starting balance. The reported minimum is `−522,600,000`. In the management edition this produces a spurious "높음" fund risk. The same happens when every account's balance cell is blank. `render.py:193` shows the "잔액 미확인 N계좌" note, but the 0.0 headline and the chart are still wrong. In the no-file case, `bal_unknown` is 0, so nothing flags the figure beyond the "파일 없음" row in section 7.
**Fix:** When there are no accounts, or every account's balance is unknown, set `total`, `available` and `start_cash` to `None`. Then:
```python
total_bal = None if (not accounts or bal_unknown == len(accounts)) else total_bal
# s1["available"] = None if total_bal is None else total_bal - restricted
# s2: if start_cash is None, skip bal_firm/bal_all and mins (set to None),
#     render the chart as "시작 잔액 판단 불가", and have risks() skip the 자금 check.
```
`start_calc`, the chart, `chart()`'s `vals` and the KPI `M()` calls need `None` guards. `M(None)` already renders "미확인".

### CR-02: Unknown project cost lines are dropped from expected spend, but remaining budget and payment rate are shown as exact figures

**File:** `ceo_report/calc.py:164-166,185-190`; `ceo_report/render.py:216,226,471-472`
**Issue:** A 집행 line with `supply is None` only increments `unknown_cost` and is excluded from `paid`, `requested` and `expected`. `profit_end` is guarded (D-09), but `remain = budget − expected` and the 지급률 are not. Probed on the sample: P26206 has `unknown_cost=1`, yet the first-screen row shows 지급률 `92.9%` and 예상 잔여예산 `2.0` with no marker. The first screen has no unknown-cost count at all. `unknown_cost` is shown only in the section 3 "금액 미확인" column and in the section 4 profit cell. The first-screen "전체" row adds up all the underestimated numbers without a note. The remaining budget is therefore overstated for exactly the projects where the cost is unknown. This is the "unknown treated as 0 to look better" case the rule forbids.
**Fix:** Mark remaining budget as undeterminable when cost lines are unknown, and show the count on the first screen:
```python
P["remain"] = None if (b is None or P["unknown_cost"]) else b - P["expected"]
```
In the first-screen project table, append `" (미확인 원가 %d건)"` to the 지급률 or 잔여 cell when `P["unknown_cost"]`. Add `tot["unknown_cost"]` to the "전체" note. Compute `tot["remain"]` only over projects with no unknown cost, and state how many were left out.

### CR-03: Totals that contain only unknown values are displayed as 0, and several partial totals hide their unknown counts

**File:** `ceo_report/calc.py:201,263,404-405,411-416`; `ceo_report/render.py:248,253,359,366,478,590-593`
**Issue:** All of these use the same `ssum` / `sum` pattern that turns "all unknown" into 0. Probed with the `프로젝트집행.csv` 지급완료 VAT cells blanked, and with all contract and revenue-to-date cells blanked:
- `tot["paid_cash"]` (calc.py:201) is 0 when every project's `paid_cash` is `None`. The section 3 "전체" row shows `0` in "지급 실출금(VAT포함)". The computed `paid_cash_unknown` (7) is never rendered; it is not referenced anywhere in render.py.
- `s5["contract"]` (calc.py:263), `s5["unissued"]` (calc.py:272) and `s4["unrecognized"]` (calc.py:404) are filtered sums, 0 when every project is unknown. The first screen shows "계약금액 0.0", "미발행금액 0.0" and "계약 중 매출 미반영 0.0". The unknown counts exist (`contract_missing`, `unissued_unknown_n`, `unrecognized_missing`). The first-screen "계약 중 매출 미반영" row and the section 4 total row do not render `unrecognized_missing`, and "미발행금액" has no count on the first screen.
- In section 6, `by_cat6[...]["total"]` starts at 0 and stays 0 when every row in a category has an unknown amount (calc.py:411-416). The category table shows `0` in the amount cell. The vendor table was fixed (calc.py:449-451) but the category table was not.

D-02 requires "확인된 것만의 합계 + 미확인 N건" for partial sums and a non-zero "판단 불가" for all-unknown.
**Fix:** Use one helper for every total. It returns `None` when the number of known values is zero and there is at least one unknown, and the call sites render the unknown count next to the number:
```python
def ssum_or_none(values):
    vals = list(values)
    total, unknown = ssum(vals)
    return (None if vals and unknown == len(vals) else total), unknown
```
Apply it to `tot["paid_cash"]`, `c_tot`, `s5["unissued"]`, `s4["unrecognized"]` and the section 6 category totals. Render with `_amt_unk(...)` as already done for `issued`/`ar`.

## Warnings

### WR-01: An invalid or out-of-order `--시작일` is silently ignored

**File:** `보고서.py:81`
**Issue:** `start = parse_date(a.시작일) if a.시작일 else None`. `parse_date` returns `None` on a bad format, so `--시작일 2026-13-45` falls back to the default period with no message. Probed: it printed "집계 기간 2026-10-27 ~ 2026-11-02". The user gets a report for a different period than requested. A start date after the reference date is also accepted and gives an empty period.
**Fix:**
```python
start = None
if a.시작일:
    start = parse_date(a.시작일)
    if start is None or start > asof:
        print("시작일 형식 오류 또는 기준일보다 늦음: %s" % a.시작일); return 2
```

### WR-02: PDF generation can fail silently when Edge or Chrome is already open, and the file URL is not escaped

**File:** `보고서.py:49-64`
**Issue:**
- The browser is started with the default profile. When Edge or Chrome is already running for the same profile (very likely on a CEO's PC), a headless launch can hand off to the running instance and exit without writing the PDF. The code then reports "PDF 실패 (브라우저가 파일을 만들지 않음)", so the primary deliverable is lost with no usable remedy. I could not test this on Windows; it is a known Chromium behavior.
- `url = "file:///" + path.replace("\\","/")` does not percent-encode. A folder or file name containing `#`, `?` or `%` produces a wrong URL. A UNC path (`\\server\share`) becomes `file:///server/share/...`, which is wrong.
- `--no-sandbox` is passed to a browser that renders a file built from CSV text. It is not needed on Windows.
- Success is `os.path.exists(pdf_path)`, so a zero-byte or truncated file counts as success.
**Fix:** Add `"--user-data-dir=" + tempfile.mkdtemp()` (and remove it afterwards), build the URL with `pathlib.Path(html_path).resolve().as_uri()`, drop `--no-sandbox` unless running as root on Linux, and require `os.path.getsize(pdf_path) > 0`.

### WR-03: Outstanding receivable treats a blank 입금액 as 0 paid

**File:** `ceo_report/calc.py:234`
**Issue:** `v["outstanding"] = total − (v["paid"] or 0)`. A row that has an 입금일 but a blank 입금액 is counted as fully unpaid. It then lands in `ar_rows`, in overdue totals and in the cash schedule as an incoming amount. D-02 says an unknown amount stays `None`. A blank 입금액 with a blank 입금일 is legitimately "not paid yet", but with an 입금일 present the amount is unknown.
**Fix:** If `v["paid_date"]` is set and `v["paid"] is None`, set `outstanding = None` (it is then counted under `ar_unknown_n` and shown as "미확인"). Otherwise use 0.

### WR-04: `read_csv` mangles multi-line cells and Unicode line separators

**File:** `ceo_report/util.py:43`
**Issue:** `csv.DictReader(text.splitlines())` breaks on `\x0b`, `\x0c`, `\x1c`-`\x1e`, `\x85`, `\u2028` and `\u2029` as well as `\n`. Excel cells with Alt+Enter (common in 적요 and 비고) lose their line break. Probed: `"줄1\n줄2"` was read as `줄1줄2`, and `"a\u2028b"` was read as `ab`. Reported line numbers are also record numbers, not file lines, so they drift when blank lines or multi-line cells exist.
**Fix:** `csv.DictReader(io.StringIO(text, newline=""))`, and use `reader.line_num` for the reported line. Do the same for the header fallback `csv.reader(...)`.

### WR-05: Batch launchers report success after a failure, and do not check the Python version

**File:** `실행_주간.bat:19-22`, `실행_월간.bat:19-22`
**Issue:**
- After `set "RC=%ERRORLEVEL%"`, the script always echoes a line saying the result files are in the output folder. It does this even when `RC` is non-zero (input folder missing, bad date, traceback). The CEO is told the files exist when they may not.
- `python --version` only proves that some `python` exists. The message demands 3.8 or later, but 2.7 or 3.5 would pass the check and then fail on the script. The Microsoft Store `python.exe` alias is handled correctly (it returns a non-zero code).
- `chcp 65001` is never restored. This is harmless for a double-clicked window.
**Fix:**
```bat
if not "%RC%"=="0" (echo 오류가 발생했습니다. 위 메시지를 확인하세요.) else (echo 결과 파일은 출력 폴더에 있습니다.)
```
For the version, test with `%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)"` and fall back to the next candidate.

### WR-06: `compute()` mutates the loaded `Data`, so a second call duplicates issues and keeps stale per-invoice state

**File:** `ceo_report/calc.py:69,86,117,454`, `ceo_report/calc.py:233,240`
**Issue:** `compute` appends to `d.issues` on every call, and `R["s7"]["issues"]` is the same list object (`d.issues.items`). It also writes `v["total"]`, `v["outstanding"]` and `v["overdue_days"]` into the shared invoice dicts. A second `compute` on the same `Data` (as `Base.cls.d` is reused in `test_monthly_period`) duplicates the 설정/잔액 messages in the first result, and a row that was overdue in the first call keeps its `overdue_days` key, so `render.py:562` (`"overdue_days" in v`) would show an overdue count for a row that is no longer overdue. The CLI calls it once, so this is latent today. It will bite the planned reuse of `compute` by the payment-approval screen (deferred idea in CONTEXT.md).
**Fix:** Copy `d.issues.items` into the result (`list(d.issues.items)`) and build invoice results in new dicts, or reset `v.pop("overdue_days", None)` at the start of the invoice loop and snapshot issues at the end of `compute`.

## Info

### IN-01: Several reconciliation checks can never fail

**File:** `ceo_report/calc.py:142-145,220-224`
**Issue:** "분류별 입금 합 = 입금 합계" compares sums built from the same `ext` list. The 집행 line count check and "표시 + 나머지 = 전체" (`shown + rest` is a partition of `plist`) are also identities. Only the transfer check and the start-balance check detect real input problems. The report displays "일치" for the others, which gives false assurance.
**Fix:** Keep them as internal asserts or compare against an independent source (for example, section 3 totals against the sum of the displayed table rows).

### IN-02: Dead development-environment path in the browser search

**File:** `보고서.py:42-46`
**Issue:** The `/opt/pw-browsers` lookup is specific to a Linux sandbox and cannot apply on the Windows target.
**Fix:** Remove it. It is also missing from the documented behavior.

### IN-03: The report prints a U+2212 minus that `num()` cannot read back

**File:** `ceo_report/util.py:60,137-141`
**Issue:** `won()` and `man()` emit `−` (U+2212). `_NUM_RE` accepts only ASCII `-`. A user who copies a figure from the report into a CSV gets "숫자 아님" for it. The error is visible, so it is not silent.
**Fix:** In `_plain`, also replace `"−"` with `"-"`.

### IN-04: Tests write into the repository and leak temp folders on failure

**File:** `tests/test_report.py:64-66,128,277`
**Issue:** `setUpModule` runs `tools/make_sample.py`, which rewrites the committed `입력/` folder on every test run. `test_cp949_csv` and `test_cli_writes_files` call `shutil.rmtree` after the assertions rather than through `addCleanup`, so a failing assertion leaves the temp folder behind.
**Fix:** Generate the sample into a temp folder and point `SAMPLE` at it, and use `self.addCleanup(shutil.rmtree, ...)` consistently.


## Fix Status

Fixed 2026-11-02 on the current branch, one RED test commit (`test(01-fix): RED ...`) then one fix commit (`fix(01-fix): ...`) per finding. After the fixes `python3 -m unittest discover -s tests` runs 118 tests, all OK (74 before).

| Finding | Status | Fix commit |
| --- | --- | --- |
| CR-01 no account balance becomes 0 cash | fixed | cf17d3f |
| CR-02 unknown project cost lines hidden in remaining budget / payment rate | fixed (also closes the 01-VERIFICATION gap) | be9af95 |
| CR-03 all-unknown totals shown as 0 | fixed | adde808 |
| WR-01 invalid `--시작일` ignored | fixed | aa2ed15 |
| WR-02 PDF profile, file URI, sandbox, empty file | fixed | b75b91d |
| WR-03 blank 입금액 treated as 0 paid | fixed | f6b6235 |
| WR-04 `read_csv` splitlines / line numbers | fixed | bcd473c |
| WR-05 launchers: success line and Python version | fixed (static test only; Windows run is a human check) | 5f5bb40 |
| WR-06 `compute()` mutates Data | fixed | 05fe2f7 |
| IN-04 test temp folders leak | partial: `addCleanup` for all three leaking tests (6cde565). Generating the sample into a temp folder was not done | 6cde565 |
| IN-01 reconciliation checks that cannot fail | not attempted (optional) | - |
| IN-02 dead `/opt/pw-browsers` lookup | not attempted (optional; the Linux test environment uses it) | - |
| IN-03 U+2212 minus not read back by `num()` | not attempted (optional) | - |

Also fixed, from the verification report: the first-screen `날짜 없는 입금예정 / 지급예정` line and the `입금예정일 경과 미수` line now show counts as well as amounts (D-04), commit f913e7c.

Notes:
- CR-01: with no known balance, 현재 현금 and 사용 가능액 are 미확인, the balance lines and the chart balance curve are not drawn, the minimum balance shows `잔액 미확인`, and the management edition adds a data item instead of a fund risk.
- CR-02: a project with an unknown cost line has 예상 잔여예산 `판단 불가 (미확인 원가 N건)`; the 전체 row leaves it out and says how many.
- WR-02: besides the requested changes, `--no-first-run --disable-field-trial-config` are passed. Without `--disable-field-trial-config` a fresh profile made the bundled Chrome hang in the Linux test environment.
- Fix verification ran in the main checkout (no worktree), Python 3.13 and 3.11. Python 3.8 was not available; the sources were parsed with `ast.parse(feature_version=(3, 8))`.

---

_Reviewed: 2026-11-02_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
