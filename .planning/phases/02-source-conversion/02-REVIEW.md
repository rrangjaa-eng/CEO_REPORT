---
phase: 02-source-conversion
reviewed: 2026-11-02T19:49:08Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - ceo_report/convert.py
  - ceo_report/convert_pl.py
  - ceo_report/convert_projects.py
  - ceo_report/convert_invoices.py
  - ceo_report/convert_xchk.py
  - ceo_report/linking.py
  - ceo_report/wehago.py
  - ceo_report/approval.py
  - ceo_report/approval_render.py
  - ceo_report/render.py
  - 변환.py
  - 보고서.py
  - 승인검토.py
  - 실행_변환.bat
findings:
  critical: 5
  warning: 6
  info: 7
  total: 18
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-11-02T19:49:08Z
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

I reviewed every source change since `cbc5497` in the conversion pipeline, the D-38 linking engine, the WEHAGO reader changes,
the D-47 approval changes, monthly section 8 and the CLIs and launcher. I checked the findings against the phase invariants:
unknown values stay None or '' and never 0; outflows are never understated; a request is counted at most once and the larger
of invoice and request wins (D-50); the CEO edition shows facts only; writes are all-or-nothing; D-46 is followed; 주민번호 is
masked; no real data is committed.

All 1000 tests pass and the working tree stays clean after the run. That does not mean the output is right. Each Critical
finding below has a small synthetic reproduction in
`/tmp/claude-0/-home-user-CEO-REPORT/8bd5f933-589b-59f6-ab79-e1826aa1edc1/scratchpad/` (`repro_a`..`repro_g`, shared helper `harness.py`; run
with `PYTHONPATH=<scratchpad> python3 <script>`). In every Critical case the built-in 대조 checks report '일치'. The wrong
numbers reach 프로젝트집행.csv, 계산서.csv, 손익.csv or section 8, and they leave no trace outside a note in 변환결과.txt.

Checked and found sound: D-46 (with no usable sales source, 계산서.csv is not in `names`, so it is not backed up, prechecked or
replaced: `convert.py:655-656, 692`); the `GENERATED` guard means manual files are never written (`convert.py:246-248`); every
text path goes through `mask_rrn` (CSV via `table_bytes`, 변환결과.txt via `_text_bytes`, stdout via `변환.py:_say`, HTML via
`esc`); and no file under `입력/`, `수집/` or `*.xlsx` is tracked.

The known risk the orchestrator raised (requests whose status cannot be read are missing from section 8) is confirmed as
CR-03, and its effect is wider than described.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: A request that D-38 auto-linked to a WEHAGO cost line is counted again as its own 요청미지급 row

**File:** `ceo_report/convert_projects.py:142-156, 394-400, 441-452` (and `ceo_report/linking.py:284-286`)
**Issue:** `link_costs` gives a cost line `basis='자동', request='6001'` when exactly one request matches its vendor, amount
and date window. `build_execs` never reads `ln["request"]`: `_group_cost_lines` sets `g["request"] = None`, and nothing uses
it after that. The request is matched to a group only through `match_requests` status '계산서 있음'/'금액 차이' together
with an exact invoice total. Auto-linking exists because the memo has no `[code]`. In that case the 매입매출장 품명 usually
has no `[code]` either, so `match_requests` returns '계산서 없음'. The request then goes down the "요청 줄로 넣는다" path,
and the unpaid WEHAGO group stays in the file next to it. The same liability becomes two 요청미지급 outflows, and `calc.py:344-350`
turns both into cash-schedule events. This breaks the rule that a request is counted at most once, even though the code
already knows the line belongs to that request. All checks report 일치. The only signal is the note `중복 가능: 지급요청 6001`.
**Reproduction:** `repro_a_autolink_double.py`. The journal has 전표 40 (61101 200,000 + 13500 20,000 / 25300 220,000,
가상조명, memo without a code), the ledger has an invoice with no code, and request 6001 is [26220] 가상조명 220,000 승인.
Output: `link: 자동 26220 request 6001`, `match 6001: 계산서 없음`, and two rows `요청미지급 200000 20000` and `요청미지급 220000`.
That is `UNPAID OUTFLOW in 프로젝트집행 = 440000 (real liability 220,000)`.
**Fix:** Carry the D-38 request link into the execs grouping. A group whose lines were auto-linked to request N (or whose
`[code]`, vendor and total identify N) should be treated as that request's WEHAGO row whatever the match status is:
```python
# _group_cost_lines
reqs = set(ln["request"] for ln in g["lines"] if ln["request"])
g["request"] = reqs.pop() if len(reqs) == 1 else None
# _requests_part: before the has_invoice logic
linked = [g for g in groups if g["request"] == no]
if len(linked) == 1:
    found, has_invoice, invoice = linked, True, _group_total(linked[0])   # then annotate / diff row as today
```

### CR-02: D-50 "larger of invoice and request" is dropped when the matched invoice group is already paid

**File:** `ceo_report/convert_projects.py:433-440` (masking checks at `:470-477` and `:480-490`)
**Issue:** When the single matched group is '지급완료'/'카드결제완료' and `rq["amount"] > invoice`, the request is skipped.
The code adds a note ("차액은 넣지 않았으니 확인") but no 차액 row. D-50 says the rows that point to the request must add
up to `max(invoice, request)`. The annotate branch at `:428-431` adds the 차액 row, but this branch does not, and it does not
even tag the paid group with `지급요청 N`. The approval screen schedules `schedule_amount = max(...)` for the same request
(`approval.py:462-464`, D-30b), so the monthly data and the approval screen disagree. Both checks hide the gap. The amount
check counts `skipped_amount` as "covered" (`:470, 477`). The D-50 check only looks at requests in `part["naming"]`, and
skipped requests are never added there (`:483-484`). The result is an understated outflow.
**Reproduction:** `repro_b_paid_diff_dropped.py`. An invoice for [26220] 가상무대 5,500,000 is paid in cash in the same
전표, and request 6101 is 6,000,000 승인. Output: `match: 금액 차이 invoice 5500000 schedule_amount (approval screen D-30b)
6000000`, `rows naming 6101: 0`, `future outflow in CSV = 0`, and every check `일치`.
**Fix:** In the skip branch, add the positive 차액 row (`_request_row(rq, rq["amount"] - invoice, "지급요청 N 차액 (인트라넷
요청 − 계산서, 계산서는 이미 지급)")`) and append `· 지급요청 N` to `g["basis"]`. Then put skipped requests in the D-50
check: use `want += max(...)` and count the paid group plus the 차액 row.

### CR-03: Requests with an unreadable 사장님승인 status disappear from 프로젝트집행, 요청 누계 and 프로젝트밖요청, and section 8 shows 0

**File:** `ceo_report/convert_projects.py:384-389`, `ceo_report/convert_xchk.py:84-93, 110-112, 170-176, 353`,
`ceo_report/render.py:930-943, 1033-1038, 1101-1107, 1191-1207`
**Issue:** `approval._status` maps anything that is not '승인'/'미승인'/'수락요청중' to `status_unknown`. That covers 반려,
but also a blank cell (crawler drift, column moved) or any new state such as '보류'. The conversion then:
(1) leaves these requests out of 프로젝트집행.csv, so `calc` never schedules them as outflows;
(2) leaves them out of 요청 누계 and 프로젝트밖요청, which write a **known 0** (`금액 0, 건수 0`, not '' with a note);
(3) records the exclusion only in `Table.notes`, which reaches 변환결과.txt. 위하고대조.csv has no row for it, so `load_xchk`
cannot see it, and section 8 (both editions) never says '상태 확인 필요 N건'. The approval screen does show that count
(`approval_render.py:522, 604, 630`).
Section 8 also contradicts itself. The 요청상태 table counts these requests (under '연결 불가' etc., from `match_requests`),
while 요청 누계 and 프로젝트밖요청 show 0 with no explanation. If the 사장님승인 column comes through blank for every row,
every intranet request leaves the monthly report and the cash forecast, and the only record is a text file.
**Reproduction:** `repro_c_status_unknown.py`. Requests are 6201 (사장님승인 '', 30,000,000, [26220]) and 6202 ('보류',
7,000,000, outside code). Output: 프로젝트집행 has no request rows; `xchk 프로젝트원가 26220 요청 누계 0 0`;
`xchk 프로젝트밖요청 합계 인트라넷 요청 0 0`; `section 8 mentions 6201/6202/상태 확인: False`; 요청상태 shows
`('연결 불가', 2, 37000000)`.
**Fix:** Write a fact row such as `_row("요청상태확인필요", "합계", "", "인트라넷 요청", total, len(bad), "요청 누계·프로젝트밖요청·프로젝트집행에 넣지 않음")`.
Read it in `load_xchk` and show '상태 확인 필요 N건 금액 X' in the section 8 summary (a fact, so it is allowed in the CEO
edition) and in the detail tables. When unknown-status requests with that code exist, show 요청 누계 / 프로젝트밖요청 as
'' plus the count. For 프로젝트집행, keep blank or unrecognised statuses as 요청미지급/추정 rows and only drop a known
rejection value such as '반려'. This follows the "never understate outflows" rule.

### CR-04: Converting a partial-period 분개장 deletes every earlier WEHAGO month from 손익.csv (YTD silently collapses)

**File:** `ceo_report/convert_pl.py:257-267`
**Issue:** `replaced = [r for r in prev_rows if 출처 == "WEHAGO"]` throws away **all** previous WEHAGO rows, including months
the new 분개장 does not cover. The source and CSV checks only compare against the new journal, so they show 일치. WEHAGO
분개장 downloads take a date range. A user who downloads only October loses January to September, and the monthly report's
YTD (`calc.py:462-472`) falls to the October figure with no warning. The data survives only in `입력/이전/<stamp>/`.
**Reproduction:** `repro_d_pl_history_dropped.py`. The previous 손익.csv has 2026-01..09 WEHAGO 회사 rows at 100,000,000
each, and the new journal covers only 2026-10 (75,000,000). Output: `rows: [('2026-10', '75000000')]`,
`YTD 매출 before: 900000000 after: 75000000`, all checks `일치`, and the note `WEHAGO 줄 9건 ... 새로 만든 줄로 바꿈`.
**Fix:** Replace only WEHAGO rows whose 연월 is in the new journal's months (`per.keys()`), carry the others, and say so in a
note:
```python
covered = set(per)
replaced = [r for r in prev_rows if r.get("출처") == "WEHAGO" and r.get("연월", "")[:7] in covered]
carried = [r for r in prev_rows if r not in replaced]
```
Also print the journal's first and last 전표일자 in 변환결과.txt.

### CR-05: Installment or fee-deducted customer payments never reach the invoice, so 계산서.csv shows the full amount as still receivable

**File:** `ceo_report/convert_invoices.py:200-217` (also `:123-172`, `:338-353`)
**Issue:** A receipt is only allocated when its amount equals the whole invoice total (pass 1). The FIFO pass 2 runs only
when the 분개장 has a 전기이월/기초잔액 line. Common real cases all end up as '미배분 수금' while the invoice keeps
`입금액 ''`: payment in installments, a customer deducting a bank 송금수수료 (109,998,700 against 110,000,000), or one
payment covering two invoices. `calc.py:268-270` then sets `outstanding = total` and creates a 수금 event (`calc.py:334-337`).
That puts a phantom future inflow and receivable into the CEO cash forecast, which is the inflow mirror of the outflow rule.
The per-vendor balance note does not catch it, because `sheet_side` subtracts the leftover receipts (`:346`) and reports
"차이 0". Receipts into any bank account other than `cash_codes` (e.g. a second 보통예금 sub-code) go to '수정(계산서 감액)'
and leave the invoice unpaid in the same way.
**Reproduction:** `repro_e_partial_receipts.py`. The invoice is 가상고객A 100,000,000 + 10,000,000, paid as 55,000,000 on
2026-10-05 and 55,000,000 on 2026-10-20. Output: `입금일 '' 입금액 ''`, every check `일치`, `참고 매출채권 잔액: 분개장 0 ·
계산서 기준 0 (차이 0)`, `미배분 수금 2건 110,000,000`.
**Fix:** Run the oldest-first allocation per vendor for receipts dated on or after the invoice date even without an opening
line. When the vendor's pre-period balance is unknown, keep the result marked as an allocation by writing 입금일 and 입금액
and noting '배분 (금액 다름)'. If the team does not want that, write `입금액` as '' **with** `입금일` set for vendors that have
unallocated receipts, so `calc` treats the remainder as unknown (`calc.py:268`) instead of fully outstanding.

## Warnings

### WR-01: `write_files` is not all-or-nothing when a replace fails partway

**File:** `ceo_report/convert.py:278-284` (`run` at `:704-711`)
**Issue:** The precheck happens earlier than the `os.replace` loop. If replace number k fails (a Windows sharing violation,
an antivirus scan, or Excel opening the file after the precheck), files 1..k-1 are already new, the rest are old, and nothing
is restored from the backup copies made a moment before. `run` then returns 7 **without** writing 변환결과.txt, so the folder
holds a mixed set of new and old CSVs and a 변환결과.txt from the previous run.
**Reproduction:** `repro_f_partial_replace.py` makes the second `os.replace` fail. Output: `WriteFailed 계산서.csv
replaced: ['손익.csv']`, `손익.csv -> NEW`, `계산서.csv -> OLD 계산서.csv`, `변환결과.txt exists: False`.
**Fix:** On failure, roll back every name in `done` by copying it back from `이전/<backup>/` (or `os.replace` from a
second temp of the old file). Re-raise only after the rollback, and say in the error whether the rollback worked.

### WR-02: A large `변환_자동연결일수` crashes both 변환.py and 승인검토 with a traceback

**File:** `ceo_report/convert.py:131-132` (validation), `ceo_report/linking.py:268`, `ceo_report/approval.py:391-409`
**Issue:** The `정수` setting accepts any non-negative integer. `start + dt.timedelta(days=link_days)` raises `OverflowError`
once the result passes 9999-12-31. `변환.py` has no exception handler, which goes against the "no traceback" contract in
PATTERNS §3.5. 승인검토.py catches only `OSError`/`SnapshotError` around `make_screen` (`승인검토.py:199-203, 333`).
**Reproduction:** `repro_g_linkdays_overflow.py` with `설정.csv` `변환_자동연결일수,3000000` prints `link_days accepted: 3000000 []`
and then `CRASH: OverflowError date value out of range`.
**Fix:** Bound the value in `_parse_config_value` (for example `0 <= n <= 3650`, otherwise the default plus a note). Also wrap
`convert.run` in `변환.py` with a masked generic error line and exit code 7.

### WR-03: Projects that exist only in the previous 프로젝트.csv are dropped, along with their manual 계약금액, 상태 and 완료일

**File:** `ceo_report/convert_projects.py:99-102`
**Issue:** D-49 says the manual fields come from the previous 프로젝트.csv. `build_projects` only writes snapshot projects.
A project that the intranet list no longer shows (completed or archived), or one entered by hand, loses its row. That takes
its manual 계약금액 out of the monthly totals (`calc.py:303`). Its carried 집행계획미요청 rows and kept 계산서.csv rows then
point at a number that is no longer in 프로젝트.csv (a `data.load` issue). The only record is a 변환결과.txt note.
**Fix:** Carry previous-only rows unchanged (with a '스냅숏에 없음' 비고 or note), or at least keep those with a non-blank
계약금액 or 상태 other than 완료.

### WR-04: Previous hand-entered 요청미지급 / 카드사용미결제 rows in 프로젝트집행.csv are dropped on the first conversion

**File:** `ceo_report/convert_projects.py:494-512, 537-544`
**Issue:** Only `집행계획미요청` rows are carried. Outflows a person typed in that WEHAGO and the intranet do not know about
yet (a verbal order, a request not yet registered) disappear from the cash forecast. The note gives the total (`옮기지 않은 줄
중 아직 나가지 않은 돈 N건 …원`) but appears only in 변환결과.txt. This understates outflows on the very run where a person is
least likely to read the log.
**Fix:** Carry previous unpaid rows whose `근거` does not start with `WEHAGO `/`지급요청 `. For example, mark them `추정` with
`근거` '이전 프로젝트집행 (수동)' and list them as possible duplicates. Alternatively, print the dropped unpaid total on stdout
and in the section 8 summary.

### WR-05: Cumulative fields come from the journal's period only, so pre-period history shows as a known 0

**File:** `ceo_report/convert_projects.py:89-90` (매출반영누계), `:515-546` (집행 rows), `ceo_report/convert_xchk.py:100-105`
**Issue:** `매출반영누계` is the sum of the revenue lines in the downloaded 분개장. A project billed in December 2025, with a
2026-only journal, gets `매출반영누계 0`. That is a **known 0** where the true value is unknown (D-02), so `calc`'s
`unrecognized = 계약금액 − 0` (`calc.py:213`) overstates unbilled revenue. The same applies to 프로젝트집행 cost rows and
section 8 'WEHAGO 원가' for projects that span years. No coverage check compares the journal's first date with the project's
history.
**Fix:** Record the journal's first 전표일자. For projects with an 행사일 or registration earlier than that date, write ''
(and a note) instead of 0, or require a full-history journal and flag a shorter one in 변환결과.txt and on stdout.

### WR-06: Snapshot age is never checked and the snapshot used is not printed on the console

**File:** `ceo_report/convert.py:335-345, 726-744`
**Issue:** `read_latest_snapshot` uses the newest snapshot however old it is, and also when it was collected after
`--기준일`. The 프로젝트집행 request rows, 요청 누계 and auto-links all come from it, so a months-old snapshot keeps paid
requests as 요청미지급 and misses new ones. The snapshot line goes into 변환결과.txt only. The stdout summary (`res.lines`)
never says which snapshot was used or its age, while it does for the books (`:730-732`).
**Fix:** Add a console line `인트라넷 스냅숏 <name> (수집 <ts>, 기준일보다 N일 이전)`, and warn (or set a non-zero exit) when
it is older than a configurable number of days or newer than 기준일.

## Info

### IN-01: Section 8 label hard-codes the cash account

**File:** `ceo_report/render.py:1036, 1186`
**Issue:** "보통예금 (WEHAGO 10300)" is fixed text, but the cash account comes from `설정 변환_현금계정` (D-39 "하드코딩 금지").
With a different setting the label is wrong.
**Fix:** Write the configured code into the 위하고대조 `기준` meta and render it from there.

### IN-02: A single matched group in 카드사용미결제 state gets a misleading note

**File:** `ceo_report/convert_projects.py:420-446`
**Issue:** With `len(found) == 1` and `claims == 1` but `g["state"] == "카드사용미결제"`, neither branch applies. The request
is added with the note "원가 줄을 하나로 정하지 못함" although exactly one group was found. (No cash double count, because
`calc` ignores 카드사용미결제, but the text is wrong and the D-50 sum leaves out the card group.)
**Fix:** Handle the card-unpaid state explicitly: annotate the group or add a request row with an accurate note.

### IN-03: `--기준일` sets "now" to midnight, which skews the 변환 시각 and the backup stamp

**File:** `변환.py:43-51`
**Issue:** `now = combine(asof, 00:00)`, so 변환결과.txt and the 위하고대조 `변환 시각` show `YYYY-MM-DD 00:00:00`, not the
real run time. The pending-request `friday_after(now)` also moves. The newest books and snapshot are used even when they
postdate 기준일.
**Fix:** Keep `now = dt.datetime.now()` for timestamps and pass `asof` on its own.

### IN-04: Manual link keys depend on line position inside a 전표

**File:** `ceo_report/linking.py:75-84, 141-152`
**Issue:** `줄` is the 1-based position in file order. If a re-download reorders the lines in a 전표, or a line is added to
it, a `프로젝트연결.csv` override quietly attaches to a different cost line. `unused_links` only catches keys that vanish.
**Fix:** Store and check a fingerprint (account code and amount) with each override, and warn on mismatch.

### IN-05: The slip-level `cash_paid` check can mark an unpaid cost as 지급완료

**File:** `ceo_report/convert_projects.py:293-304`
**Issue:** Any 10300 credit in the 전표 (for example a 송금수수료 line) together with no `payable_codes` credit marks every
group in the slip 지급완료. That includes a cost booked against a liability outside `payable_codes` (25100 외상매입금, etc.),
which understates outflow for a non-default chart of accounts.
**Fix:** Require that the cash credits cover the group total, or check the group's vendor, before calling it paid; otherwise
use 요청미지급 with "지급 여부 확인 불가".

### IN-06: `WriteFailed` names the wrong file when the 이전 folder cannot be created

**File:** `ceo_report/convert.py:265-277`
**Issue:** If `os.makedirs` fails, `name` still holds the last target from the temp loop, so the user is told
`입력/<some csv>을(를) 쓸 수 없음` when the real failure is `입력/이전/...`.
**Fix:** Raise `WriteFailed("이전/" + backup_name, e)` from the makedirs branch.

### IN-07: Duplicated helpers and constants

**File:** `ceo_report/approval_render.py:794` (`LINK_BASES`), `ceo_report/approval.py:321` and `convert_xchk.py:22` (`NOT_LISTED`);
`_squash`, `_sum_or_none`, `_no_key`, `_norm_no`, `_is_opening` in `convert_pl.py`, `convert_projects.py`,
`convert_invoices.py`, `convert_xchk.py`, `linking.py`
**Issue:** These copies must stay in step by hand (the comments say "같은 글자" / "같은 순서"). Drift would quietly break the
D-47 approval and monthly equality.
**Fix:** Move them to `util.py` (or a small `convert_common.py`) and import them.

---

_Reviewed: 2026-11-02T19:49:08Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
