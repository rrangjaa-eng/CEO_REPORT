---
phase: 02-source-conversion
plan: 05
subsystem: source-conversion
tags: [wehago, invoices, 계산서, receipts, d-41, d-51, tdd, python-stdlib]
status: complete

requires:
  - phase: 02-source-conversion
    provides: "02-01 Table/Check/cell_amount/cell_date/read_prev/read_config/build_links; 02-02 linking.link_revenue/projects_of (revenue lines with project and basis)"
provides:
  - "wehago.SALES_KINDS, _sales_kind_of, read_book(keep_sales=False) with info['sales_rows'], credit_account and type on 전자세금계산서 rows, load_sales(folder, asof, books)"
  - "ceo_report/convert_invoices.py: build_invoices(sales, books, revenue, projects, prev_rows, cfg) -> Table('계산서.csv') (extra['basis'] = project basis per row)"
  - "tests/test_convert_invoices.py: SALES_EINVOICE, OPENING_AR, RECEIPT_D, PURCHASE_LEDGER, write_sales, invoice_inputs, build, cell_rows, check_lines"
affects: [02-07 (wires load_sales + build_invoices into convert.run and keeps an existing 계산서.csv when written=False), 02-06 (위하고대조 may reuse the receipt facts), 02-10]

plan_head_before: 7a892cf479a89e92d3986733a77a75d2d529f4f9
actuals:
  tokens: 14800
  tasks: 3
  commits: 4

tech-stack:
  added: []
  patterns:
    - "Sales source priority a (매출 rows of the chosen 매입매출장) > b (newest 매입매출장(매출).xlsx) > c (newest 전자세금계산서(매출).xlsx); a failing chosen file never falls back to a lower source"
    - "Receipts are 10800 credits whose 전표 has a cash debit; the other credits are listed as 수정(계산서 감액) and never become cash; both groups are proved against the credit total"
    - "Pure builder: no file access, no account number literal (codes only from cfg)"

key-files:
  created:
    - ceo_report/convert_invoices.py
    - tests/test_convert_invoices.py
  modified:
    - ceo_report/wehago.py

key-decisions:
  - "An unknown 합계 (공급가액 or 부가세 blank) is never matched to a receipt, and a vendor that has such an invoice gets no oldest-first settlement; the receipt stays 미배분 and listed"
  - "A sales file with zero sales rows is treated as no source ('자료 없음 (매출 계산서 엑셀) — <file>에 매출 줄이 없음'), so plan 02-07 keeps the existing 계산서.csv instead of replacing it with an empty file"

requirements-completed: []

duration: ~1h
completed: 2026-11-02
---

# Phase 2 Plan 05: Sales invoices -> 계산서.csv (D-41, D-51) Summary

**`wehago.load_sales` finds the sales invoice source (chosen 매입매출장 매출 rows, a 매입매출장(매출) file, or a 전자세금계산서(매출) file) and `convert_invoices.build_invoices` turns it into 계산서.csv rows with a project (코드 -> 분개장 매출 줄 -> 클라이언트·견적금액 -> '' listed), a 구분, and 입금일/입금액 from 10800 receipts; every 10800 credit is accounted for (cash receipts + 수정(계산서 감액) = credit total); with no sales source the table is `written=False` and nothing is written as 0.**

## What was built

- `ceo_report/wehago.py`
  - `SALES_KINDS`, `_sales_kind_of(name)`; `_kind_of` now returns `('매입매출장', False)` for a 매입매출장 name with a sales kind, so a `매입매출장(매출)_*.xlsx` is listed in `books.unused` and can never be chosen as the purchase ledger (even when it is the newest). The sales 전자세금계산서 was already unreadable for purchases (W-1).
  - `read_book(..., keep_sales=False)`: `info['sales_rows']` is always present (`[]` unless keep_sales on a 매입매출장); the sales rows carry the same keys as purchase rows plus `type` (매입/매출유형). 전자세금계산서 rows gain `credit_account` and `type` (유형).
  - `load_sales(folder, asof, books)` -> `{state, reason, source, file, file_date, rows, notes}`; never raises. Notes: `쓰지 않은 매출 파일: ...`, `매입매출장(매출) 파일의 매출 아닌 줄 N건 무시`, `매출 계산서 파일 기준일 <d> — 장부 기준일 <bd>보다 N일 이전`. Reasons: `자료 없음 (매출 계산서 엑셀)[ — .xlsx만 읽음 (<name> 있음)]`, `매출 계산서 엑셀 머리글 다름 — <file>: 없는 열 <a, b>`, `매출 계산서 엑셀 읽기 실패 — <file>`.
- `ceo_report/convert_invoices.py` (`build_invoices`, 379 lines, no `open(`, no account-number literal):
  - project per invoice (I-1), 구분 (I-2), rows in 발행일 order (I-6), unknown amounts `''`.
  - receipts (I-3): pass 1 exact-amount match (invoice date <= receipt date), pass 2 oldest-first only when the 분개장 has a 전기이월/기초잔액 receivable line (opening balance first), leftovers listed as `미배분 수금`.
  - five checks (줄 수, 공급가액, 부가세, 수금 = 입금액 + 기초 미수 배분 + 미배분, 매출채권 대변 = 현금 입금 + 수정(계산서 감액)) and the notes of truth 3 (프로젝트 연결, 참고 매출, 참고 매출채권 잔액, per-vendor 매출채권 잔액 차이, 미배분, 수정 lines, unlinked invoices one per line).
  - previous 계산서.csv (I-5): only 입금예정일 and 예정일확정 are carried, on an exact (거래처, 발행일, 공급가액) match; counts and payment differences are notes.
- On the synthetic data the table is exactly the four rows of truth 3, the five checks read 일치, and written into a temp copy of the sample input `data.load` reports no 계산서.csv issue and `calc.compute(..., 'weekly', 2026-11-02)` gives 가상고객D 82,500,000 dated 2026-11-30 (firm, carried) and 가상고객X 20,900,000 undated (sum 103,400,000).

## Commits

| Task | RED | GREEN |
|---|---|---|
| 1 tracer | ba27262 test(02-05): RED Task 1 tracer | 96c8bf7 feat(02-05): GREEN Task 1 tracer |
| 2 sources / missing / guard | 77d718e test(02-05): RED Task 2 | none (see below) |
| 3 receipts / carry | 5f1b93c test(02-05): RED Task 3 | none (see below) |

## Tests

Full suite 715 -> 771 (+56), all OK: `python3 -m unittest discover -s tests`. New classes (each also run alone with `-k`, all ran >= 1 test): TestSalesRead 7, TestBuildInvoices 6, TestSalesSources 11, TestSalesMissing 11, TestInvoiceReceipts 11, TestInvoiceCarry 10. `git diff --quiet cbc5497 -- ceo_report/calc.py ceo_report/data.py ceo_report/approval.py` exits 0; `grep -c "open(" ceo_report/convert_invoices.py` is 0; no `10800`/`10300`/`41200` in convert_invoices.py code; wehago.py, convert_invoices.py and the test file parse with `feature_version=(3, 8)`. test_wehago.py and test_approval*.py were not touched and pass.

### RED evidence

- Task 1 (real RED): TestSalesRead `FAILED (failures=1, errors=6)` of 7, TestBuildInvoices `FAILED (errors=6)` of 6 (no `load_sales`, no `convert_invoices`).
- Task 2 and Task 3 are NOT real REDs. The plan told Task 1 to "write the full source order now" and to build the whole receipt/reconciliation/carry logic, so all 22 Task 2 tests and all 21 Task 3 tests passed on the Task 1 code the first time they ran (the only red lights were two typos in my own expectations, fixed before committing). The commits are still titled `test(02-05): RED Task 2/3` as the plan names them, their messages say they are guards, and there is no `feat(02-05): GREEN Task 2/3` commit because there was no code to change. The plan's done line "GREEN Task 2 / GREEN Task 3" is therefore not met literally.

## Deviations from Plan

**1. [Rule 3 - fixture] `invoice_inputs` defaults to a purchase-only ledger.** `test_wehago.FAKE_LEDGER` contains one 매출 row (전표 9, 가상고객A 100,000,000). With it, source (a) would win and truth 1 (source '전자세금계산서(매출)') could never hold. The helper therefore passes `PURCHASE_LEDGER` (FAKE_LEDGER minus the 매출 row); TestSalesSources builds the (a) case explicitly. Approval regression tests still use the untouched `write_fake_books` default.

**2. [Interface addition] 전자세금계산서 rows also gain `type` (유형).** The plan names only `credit_account`; I-2 needs the 유형 text ('수정') for the sales e-invoice, and both kinds share one reader. Existing tests do not compare these row dicts.

**3. [Decision] A sales file without any sales row is 'no source', not an empty 계산서.csv.** State '자료 없음', reason `자료 없음 (매출 계산서 엑셀) — <file>에 매출 줄이 없음`. Writing an empty table would wipe the user's invoices (02-07 keeps the old file for any written=False).

**4. [Rule 2 - safety additions, not in the plan]**
- A vendor with an invoice whose 합계 is unknown gets no oldest-first settlement (it could be the one the receipt belongs to); note `합계를 모르는 계산서가 있는 거래처는 기초 미수 순서 배분을 하지 않음: ...`.
- Invoices without a 발행일 are not paired with receipts; receipts without a date stay 미배분 (`날짜 없음`); note `발행일 없는 계산서 N건 (입금과 짝짓지 않음)`.
- Notes `수정(계산서 감액) N건 <won>` (count before the lines), `합계가 공급가액+부가세와 다른 계산서 N건 (공급가액+부가세로 처리)` (the sales file's own 합계 column is never used), and `이전 계산서.csv와 새 계산서에 같은 거래처·발행일·공급가액 줄이 여러 건 ... → 입금예정일 옮기지 않음` when either side has duplicates of a key.
- The previous-payment difference note is only written when the previous row recorded an 입금액 (a blank previous cell is "no record", not a conflict).

**5. [Interpretation] Opening balance in the 계산서 기준 remainder.** The per-vendor/overall 잔액 fact uses `opening net - opening applied` (so a credit-balance opening line, net < 0, appears as a negative remainder instead of being dropped); for the usual net > 0 case it equals the plan's "remaining opening items". Opening lines are not special-cased in the receipt/수정 classification: a credit on an opening line would be listed as 수정(계산서 감액).

**6. [Format, for 02-07]** Listing lines inside `Table.notes` start with two spaces exactly as the plan's truths print them (`  미배분 수금 ...`, `  수정(계산서 감액) ...`, `  미연결 계산서 ...`). `convert.result_lines` prefixes every note with `  알림 `, which would print `  알림   미배분 수금 ...`. 02-07 should write notes that start with two spaces without the `알림` prefix (convert.py is outside this plan's files).

## Risks and things to know (not hidden)

- **Overstate / understate:** this plan creates no cash outflow and no '중복 가능' row. Receipts can only lower the open amount: a wrongly paired receipt lowers expected inflow (conservative for cash), an unpaired one is listed as 미배분 and leaves the invoice open. The carried 입금예정일/예정일확정 ('Y') comes only from an exact (거래처, 발행일, 공급가액) match; if the amount changed the date is not carried. If a previous row said '확정' and the invoice is now fully paid, the date is carried but calc ignores a zero outstanding.
- **Assumption (c):** the 전자세금계산서(매출) header is assumed to equal the 전자세금계산서(매입) header; the real sales download has not been seen (Q-1 unanswered). A different header gives '머리글 다름' naming the missing columns, not a wrong table. Confirm at UAT.
- **Source (a) wins** whenever the chosen purchase ledger has at least one 매출 row, even if the user also downloaded a fuller 전자세금계산서(매출): the other files are named in `쓰지 않은 매출 파일` only.
- Receipts are evaluated per journal line as `대변 - 차변 > 0`; a 전표 with a blank 전표번호 shares its group with every other blank-numbered 전표 of the same date for the "has a cash debit" test.

## Not verified

- No real Excel sales download, no Windows run, no real company data (`입력/`, `수집/`, realbooks never opened); Python 3.8 only through `ast.parse(..., feature_version=(3, 8))`, runtime 3.13.
- `convert.run` is not wired (plan 02-07): the handling of `written=False` (keep the existing 계산서.csv, the '기존 계산서.csv 유지' line, exit codes) is not exercised here.
- REQUIREMENTS.md SRC-01 is not ticked (orchestrator).

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model: T-02-21 (exact pass first, oldest-first only with an opening line, leftovers listed, both receipt checks on every run, non-cash credits never cash), T-02-22 (corrupt/odd xlsx -> '읽기 실패' without exception, tested), T-02-23 (vendor 주민번호 masked in cells, notes and written bytes, tested), T-02-24 (sales-only 매입매출장 never the purchase ledger; approval.build xchk rows and summary equal with and without sales files).

## Self-Check: PASSED

- Files exist: ceo_report/convert_invoices.py, tests/test_convert_invoices.py, ceo_report/wehago.py (all FOUND).
- Commits exist: ba27262, 96c8bf7, 77d718e, 5f1b93c (all FOUND in git log).
- `python3 -m unittest discover -s tests` -> Ran 771 tests, OK.
