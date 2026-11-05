# Phase 2: 원천자료 변환 — Patterns and shared contracts

Every Phase 2 plan reads this file. It fixes the module map, the shared data shapes, the synthetic fixtures and the
conventions, so plans that run in parallel agree without reading each other's code.

## 1. Module map and ownership

| Module / file | Created by | Changed by | Role |
|---|---|---|---|
| `ceo_report/convert.py` | 02-01 | 02-03, 02-07 | pipeline `run()`, `read_config()`, `Table`, `Check`, `write_table()`, backup and safe replace, `변환결과.txt` |
| `ceo_report/convert_pl.py` | 02-01 | 02-03 | `build_pl()` → 손익.csv |
| `변환.py` | 02-01 | 02-03, 02-07 | CLI (exit codes 0 / 2 / 3 / 7) |
| `실행_변환.bat` | 02-01 | — | Windows launcher (same shape as 실행_월간.bat) |
| `ceo_report/wehago.py` | (01.1) | 02-01 (journal `sort`, `stale_days=None`), 02-05 (sales kinds, `load_sales`), 02-08 (`project_costs(..., links=None)`) | xlsx reader |
| `ceo_report/linking.py` | 02-02 | — | D-38 engine: `requests_of`, `projects_of`, `line_keys`, `read_links`, `link_costs`, `link_revenue` |
| `입력양식/프로젝트연결.csv` | 02-02 | — | empty manual template (header only) |
| `ceo_report/convert_projects.py` | 02-04 | — | `build_projects()` → 프로젝트.csv, `build_execs()` → 프로젝트집행.csv |
| `ceo_report/convert_invoices.py` | 02-05 | — | `build_invoices()` → 계산서.csv |
| `ceo_report/convert_xchk.py` | 02-06 (wave 3) | — | `build_xchk()` → 위하고대조.csv (incl. 보통예금, D-48), `load_xchk()` for the monthly report |
| `ceo_report/render.py`, `보고서.py` | (1) | 02-09 (wave 4) | monthly section 8 'WEHAGO 기준 대조' |
| `tests/test_convert_reports.py` | 02-10 (wave 5) | — | report, approval and no-double-count checks on real 변환.py output |
| `ceo_report/approval.py`, `ceo_report/approval_render.py`, `승인검토.py` | (01.1) | 02-08 (D-47) | approval screen project costs through linking.py (same rule and settings as the monthly report) |

Files that NO Phase 2 plan changes (proof: `git diff --quiet cbc5497 -- <files>`): `ceo_report/calc.py`,
`ceo_report/data.py`, `ceo_report/intranet.py`, `ceo_report/snapshot.py`, `실행_주간.bat`, `실행_월간.bat`,
`실행_승인검토.bat`. `ceo_report/approval.py`, `ceo_report/approval_render.py` and `승인검토.py` stay unchanged through
waves 1-3 (plans 02-01..02-06 check them against cbc5497 when they run); only plan 02-08 (wave 4, D-47) changes them,
so plans 02-07, 02-09 (same wave) and 02-10 leave them out of their checks.

## 2. Output files (D-40..D-43)

| File in 입력/ | Kind | Written when | Columns |
|---|---|---|---|
| 손익.csv | generated | books 'ok' | `data.SCHEMA["손익.csv"]` |
| 계산서.csv | generated | books 'ok' and a usable sales source exists (D-41); otherwise an existing file is kept untouched and reported with its 작성일 (D-46) | `data.SCHEMA["계산서.csv"]` |
| 프로젝트.csv | generated | books 'ok' and a snapshot exists (otherwise an existing file is kept untouched) | `data.SCHEMA["프로젝트.csv"]` + extra column `실행가` (D-42; the report ignores it) |
| 프로젝트집행.csv | generated | books 'ok' and a snapshot exists (otherwise kept untouched) | `data.SCHEMA["프로젝트집행.csv"]` |
| 위하고대조.csv | generated | books 'ok' and a snapshot exists (otherwise kept untouched) | `convert_xchk.XCHK_COLUMNS` (D-44) |
| 변환결과.txt | generated log | every run that gets past argument checks | free text, format in §6 |
| 계좌잔액.csv, 설정.csv, 지급계획.csv, 변경내역.csv, 자료기준일.csv, 프로젝트연결.csv | manual (D-43) | never created, never written, never moved | — |
| 입출금내역.csv, 자금일정.csv, 자료차이.csv | not written by Phase 2 (D-48) | never written; 입출금내역.csv and 계좌잔액.csv are read for the 보통예금 facts, 자금일정.csv for the overlap list | — |

`convert.GENERATED = ("손익.csv", "계산서.csv", "프로젝트.csv", "프로젝트집행.csv", "위하고대조.csv", "변환결과.txt")`
`convert.MANUAL = ("계좌잔액.csv", "설정.csv", "지급계획.csv", "변경내역.csv", "자료기준일.csv", "프로젝트연결.csv")`
The pipeline may only write names in GENERATED. A test lists every path the run opened for writing.

## 3. Shared shapes

### 3.1 Table and Check (convert.py, plan 02-01)
- `Check = namedtuple("Check", "label source csv")`; `check_result(c)` → '일치' when both are not None and equal,
  '판단 불가' when either is None, else '불일치'.
- `Table(name, columns, rows, checks=(), notes=(), written=True, reason="", extra=None)` — a small class (not a
  namedtuple); rows are dicts column → str. `written=False` means "do not create this file"; `reason` is the one Korean
  line shown instead. `extra` is a dict (default {}) for values other builders or the run need but that are not CSV
  columns (e.g. 02-04 puts `extra['cost_portions']`, a list aligned with rows: the cost part of each WEHAGO row, None
  for request, diff and carried rows).
- `cell_amount(v)` → '' for None, else `str(int(v))` (no commas, '-' for negatives). `cell_date(d)` → '' or ISO.
- `write_table(path, table)` writes UTF-8 with BOM, `csv.writer`, header = `table.columns`; every text cell passes
  through `util.mask_rrn`; amount and date cells are produced by `cell_amount`/`cell_date` and are not masked.

### 3.2 Config (convert.read_config, plan 02-01; D-39 — never hard-coded in builders)
`read_config(input_dir)` → `(cfg, notes)`. Reads 설정.csv read-only with `util.read_csv`. Keys and defaults:

| 설정 항목 | cfg key | Default | Meaning |
|---|---|---|---|
| 변환_매출계정 | revenue_codes | 41200 | 매출 = 대변−차변 |
| 변환_매출채권계정 | receivable_codes | 10800 | 수금 = 이 계정 대변 중 같은 전표에 현금계정 차변이 있는 줄 |
| 변환_직접비코드 | direct_prefixes | 6 | 직접비 = 코드가 이 숫자로 시작하는 5자리 + 계정과목에 직접비표시 |
| 변환_직접비표시 | direct_mark | (도) | |
| 변환_공통비코드 | common_prefixes | 8 | 공통비 = 코드가 이 숫자로 시작 (표시 없어도 넣고 알림) |
| 변환_공통비표시 | common_mark | (판) | 이 표시가 없는 공통비 줄은 변환결과에 줄 수·금액으로 알림 |
| 변환_미지급계정 | payable_codes | 25300,26200 | |
| 변환_현금계정 | cash_codes | 10300 | |
| 변환_부가세대급금계정 | vat_codes | 13500 | |
| 변환_결산구분 | closing_sorts | 결차,결대 | 분개장 구분 값 (Q-3) |
| 변환_자동연결일수 | link_days | 90 | D-38 / Q-2 |
| 변환_카드거래처 | card_words | 카드 | 미지급 대변 거래처 이름에 이 낱말이 있으면 카드 |
| 변환_스냅숏경과일 | snapshot_days | 7 | 스냅숏이 기준일보다 이 일수를 넘게 오래됐으면 경고 (02-REVIEW WR-06) |

일수 항목(변환_자동연결일수, 변환_스냅숏경과일)은 1~3650 이다. 밖의 정수는 가까운 끝으로 바꾸고
`설정 <항목> 값 N 범위 밖 (1~3650) → M 사용` 알림을 남긴다 (02-REVIEW WR-02).

Lists are comma-separated; codes and prefixes must be digits; link_days an integer ≥ 0. A blank or invalid value uses
the default and adds a note `설정 <항목> 값 '<값>' 사용할 수 없음 → 기본값 <기본값>` (blank: `설정 <항목> 비어 있음 → 기본값 <기본값>`;
missing row: no note). 설정.csv missing → all defaults and the note `설정.csv 없음 → 변환 설정 기본값 사용`.

### 3.3 Requests and projects (linking.py, plan 02-02)
- `requests_of(snap, asof, now)` → list of dicts with exactly the keys approval.build gives `A['requests_all']`
  needs for matching: `id` ('r0'...), `번호`, `name` (행사명), `vendor` (파트너), `code` (approval.project_code),
  `registered` (approval.parse_registered), `status` (approval._status: 'approved' | 'pending' | 'status_unknown'),
  `amount` (util.num of 금액, None when blank), `request_date` (util.date of 지급요청일), `date`, `rule`
  (approval._expected_date). Text comes from approval._masked(snap.payments).
- `projects_of(snap)` → OrderedDict key → `{key, name, team, client, client_norm, estimate, quote, budget, event_date, dup}`.
  key = approval.project_code(행사명) or stripped 번호 (same rule as approval._projects); name = 행사명 without a leading
  `[code]`; estimate = 사전견적, quote = 견적금액, budget = 실행가 (util.num, None when blank); client_norm =
  wehago.norm_vendor(클라이언트); a repeated key keeps the first row and sets `dup=True` on it.

### 3.4 Line keys and link results (linking.py, plan 02-02)
- Line key (D-38 '전표일자·전표번호·줄'): `(date ISO or '', 전표번호 text, 줄)` where 줄 is the 1-based position of the line
  among 분개장 lines with the same 전표일자 and 전표번호, in file order. `line_keys(journal)` returns one key per journal row.
- `link_costs(...)` / `link_revenue(...)` return `{"lines": [...], "summary": {...}, "unused": [...]}`. Each line dict:
  `index` (journal index), `key`, `date`, `no`, `line`, `vendor`, `vendor_norm`, `memo`, `account_code`, `account`,
  `amount` (cost: 차변−대변; revenue: 대변−차변; None when both blank), `project` (key or None), `basis`
  ('수동' | '코드' | '자동' | '미연결'), `request` (번호 or None), `candidates` (int), `label` (Korean text), `code`
  (the [code] found in 적요, or None).
- summary: basis → `{"count", "sum", "unknown"}` (sum of known amounts; unknown = lines with amount None).

### 3.5 Exit codes of 변환.py
0 완료 (some files may be '자료 없음', listed) · 2 입력 문제 (bad 기준일) · 3 WEHAGO 장부를 쓸 수 없음 (자료 없음 /
머리글 다름 / 읽기 실패 — no CSV written, 변환결과.txt written) · 7 파일을 쓰지 못함 (a target is locked or a write
failed — nothing replaced). No traceback is printed; every printed line goes through `util.mask_rrn`.

## 4. Conventions

- Python 3.8 standard library only; every new or changed .py parses with `ast.parse(src, feature_version=(3, 8))`.
- Unknown is None, never 0 (D-02). A CSV amount cell is '' when unknown. 0 is written only when the source covers the
  period and holds no line of that kind (stated per file in each plan).
- Never understate outflows: when it is not certain that a payment already happened or is already represented,
  keep it as an outflow (요청미지급) and count it in 변환결과.txt.
- Every text that leaves the program (CSV text cells, 변환결과.txt, stdout, HTML) passes `util.mask_rrn` (D-45).
- Weekly report unchanged: weekly HTML for the sample equals the output of the `cbc5497` code (plan 02-06 test).
- 대표용 has facts only: no word from `test_report.FORBIDDEN` ('위험', '해결방안', '권고', '우려', '추천').
- Tests: unittest, synthetic data only, written to `tempfile.mkdtemp()` folders; never pass or open `입력/`,
  `수집/`, a scratchpad or any realbooks path; never pass the default CLI folders (always `--입력`, `--수집폴더`,
  `--위하고폴더` to temp folders). Import helpers and constants, never TestCase classes, from other test modules.
- Unknown contributor rule (B5): any total, sum or cell with an unknown contributor is '' / '판단 불가'; the number of
  unknown contributors goes to a note or 비고 only. A total over an explicitly named subset ('합계 (빈칸 제외)',
  '금액 있는 N건') is allowed when the blank / unknown count is reported next to it.
- Verify commands name each test class and fail on zero tests (W1):
  `bash -o pipefail -c "python3 -m unittest discover -s tests -k <Class> -v 2>&1 | grep 'Ran [1-9]'"` per class, then the
  full suite. grep without -q reads all output, so unittest is never cut off and pipefail keeps its exit status.
- TDD per task: commit `test(02-NN): RED <task>` with the failing tests, then `feat(02-NN): GREEN <task>`.
  RED evidence = the failing run's last line pasted in the SUMMARY.
- Full suite: `cd /home/user/CEO_REPORT && python3 -m unittest discover -s tests` stays green after every GREEN.

## 5. Synthetic fixtures (names are 가상, amounts chosen so every rule fires)

Helpers already in the repo: `tests/test_wehago.py` — `write_xlsx`, `write_fake_books(folder, stamp="20261031",
drop=(), journal=None, ledger=None, einvoice=None)`, `FAKE_JOURNAL`, `FAKE_LEDGER`, `FAKE_EINVOICE`,
`EINVOICE_HEADER`, `LEDGER_HEADER`, `JOURNAL_HEADER`, `_jl(date, no, code, account, debit, credit, vendor, memo)`
(구분 is always '대체'); `tests/test_approval.py` — `FAKE_PAYMENTS`, `FAKE_PROJECTS`, `write_fake_snapshot(root,
ids=None, extra=None)`, `as_dicts`; `tests/sample_input.py` — `SAMPLE`, `refresh()`.

FAKE_JOURNAL (01.1) in short: purchases 전표 1..8 (dated 2026-10-15..26; (도) 61101 행사외주비(도) debit = 공급가액,
13500 부가세대급금 debit = VAT, 25300 미지급금 credit = 합계; codes 26201 40,000,000 · 26220 150,000,000 + 1,000,000 +
5,000,000 + 2,000,000 · 26203 45,000,000 · 26221 2,700,000 × 2), 전표 20 (2026-10-30 25300 debit 49,500,000 가상부스
= payment of 전표 3), 21 (81900 임차료 3,000,000 / 26200 미지급비용 가상임대), 22 ((도) 800,000 가상강사, 적요 holds a
주민번호, cash), 23 ((도) 300,000 가상기타 [26999], cash), 24 (45100 (도)외주비 500,000 [26201], cash). (도) total
249,500,000.

### PL_EXTRA (tests/test_convert.py, plan 02-01) — `FAKE_PL_JOURNAL = FAKE_JOURNAL + PL_EXTRA`
| 전표 | 일자 | lines (code 계정 차변/대변 거래처 적요) |
|---|---|---|
| 30 | 2026-09-15 | 10800 수입수수료미수금 D 110,000,000 가상고객A "[26201] 가상 컨퍼런스 선금" · 41200 수입수수료 C 100,000,000 가상고객A (same 적요) · 25500 부가세예수금 C 10,000,000 가상고객A |
| 31 | 2026-10-27 | 10800 D 82,500,000 가상고객D "가상 전시부스 잔금" · 41200 C 75,000,000 가상고객D · 25500 C 7,500,000 가상고객D |
| 32 | 2026-10-28 | 10800 D 22,000,000 가상고객X "기타 용역" · 41200 C 20,000,000 가상고객X · 25500 C 2,000,000 가상고객X |
| 33 | 2026-10-05 | 10300 보통예금 D 110,000,000 가상고객A "선금 입금" · 10800 C 110,000,000 가상고객A "선금 입금" |
| 34 | 2026-09-30 | 81100 복리후생비(판) D 2,000,000 가상식당 "9월 식대" · 10300 C 2,000,000 |
| 35 | 2026-10-31 | 81100 복리후생비(판) D 1,500,000 가상식당 "10월 식대" · 10300 C 1,500,000 |
| 36 | 2026-10-31 | 93100 이자비용 D 400,000 가상은행 "이자" · 10300 C 400,000 |
| 37 | 2026-09-20 | 61101 행사외주비(도) D 10,000,000 가상인쇄 "[26201] 9월 인쇄" · 10300 C 10,000,000 |
| 38 | 2026-10-29 | 41200 수입수수료 D 1,000,000 가상고객X "매출 정정" · 25500 부가세예수금 D 100,000 가상고객X · 10800 C 1,100,000 가상고객X |

Derived facts (FAKE_PL_JOURNAL, book date 2026-10-31, no closing lines):
- 손익 회사 2026-09: 매출 100,000,000 · 직접비 10,000,000 · 공통비 2,000,000 · 잠정 Y.
- 손익 회사 2026-10: 매출 94,000,000 · 직접비 249,500,000 · 공통비 4,500,000 (81900 임차료 3,000,000 has no '(판)' → counted and noted) · 잠정 Y.
- Totals: 매출 194,000,000 · 직접비 259,500,000 · 공통비 6,500,000. Not in 손익: 45100 (도)외주비 500,000, 93100 이자비용 400,000.
- Revenue links (FAKE snapshot): 전표 30 코드 26201 100,000,000; 31 자동 26203 75,000,000 (가상고객D, 견적금액 75,000,000);
  32 미연결 20,000,000; 38 미연결 −1,000,000.

### LINK_EXTRA and LINK_REQUESTS (tests/test_linking.py, plan 02-02)
| 전표 | 일자 | lines |
|---|---|---|
| 40 | 2026-10-30 | 61101 행사외주비(도) D 200,000 가상조명 "조명 추가" · 13500 부가세대급금 D 20,000 가상조명 · 25300 미지급금 C 220,000 가상조명 |
| 41 | 2026-10-30 | 61101 D 500,000 가상케이터링 "케이터링" · 10300 C 500,000 |
| 42 | 2026-10-30 | 61101 D 300,000 가상숙박 "숙박 1" · 10300 C 300,000 |
| 43 | 2026-10-30 | 61101 D 300,000 가상숙박 "숙박 2" · 10300 C 300,000 |
| 44 | 2026-10-30 | 61101 D 1,000,000 가상음향 "음향 추가" · 10300 C 1,000,000 |

LINK_REQUESTS (PAYMENT_COLUMNS order: 번호, 행사명, 파트너, 등록일, 행사일, 금액, 지급요청일, 등록자, 팀장승인, 관리팀승인, 사장님승인):
- 6001 · [26220] 가상 전시 · 가상조명 · 2026-10-20 09:00:00 · 2026-11-12 · 220,000 · '' · 김철수 · 승인 · 승인 · 승인
- 6002 · [26201] 가상 컨퍼런스 · 가상케이터링 · 2026-10-25 09:00:00 · 2026-11-20 · 500,000 · '' · 홍길동 · 승인 · 승인 · 미승인
- 6003 · [26220] 가상 전시 · 가상케이터링 · 2026-10-26 09:00:00 · 2026-11-12 · 500,000 · '' · 김철수 · 승인 · 승인 · 미승인
- 6004 · [26221] 가상 워크숍 · 가상숙박 · 2026-10-28 09:00:00 · 2026-11-25 · 300,000 · '' · 이영희 · 승인 · 승인 · 미승인
- 6005 · [26201] 가상 컨퍼런스 · 가상음향 · 2026-06-01 09:00:00 · 2026-11-20 · 1,000,000 · '' · 홍길동 · 승인 · 승인 · 승인

Expected cost links on FAKE_JOURNAL + LINK_EXTRA with snapshot FAKE + LINK_REQUESTS, link_days 90:
전표 1..8 코드 (8 lines, 248,400,000); 40 자동 26220 via 6001 (200,000; 200,000 + VAT 20,000 = 220,000);
22, 23, 41 (후보 2건: 6002, 6003), 42 and 43 (후보 공유: 지급요청 6004), 44 (6005 registered 151 days before) 미연결
(6 lines, 3,200,000). Total 15 cost lines, 251,800,000. With link_days 200, 44 becomes 자동 26201 via 6005.

### OPENING_CASH, BANK_BALANCES, BANK_TX (tests/test_convert_xchk.py, plan 02-06; D-48)
- OPENING_CASH: 전표 80 2026-01-02 · 10300 보통예금 D 300,000,000 가상은행 '전기이월' · 37500 이월이익잉여금 C 300,000,000.
- BANK_BALANCES (계좌잔액.csv rows): 2026-10-31 운영계좌 가상은행 200,000,000 · 2026-10-31 프로젝트계좌 가상은행 145,000,000.
- BANK_TX (입출금내역.csv rows): 2026-10-05 운영계좌 입금 110,000,000 · 2026-10-30 운영계좌 출금 53,000,000.
- FAKE_PL_JOURNAL cash facts: 증감 45,000,000 (2026-09 −12,000,000; 2026-10 +57,000,000); with OPENING_CASH 잔액 345,000,000.

### SALES_EINVOICE (tests/test_convert_invoices.py, plan 02-05; file `전자세금계산서(매출)_20261031.xlsx`, EINVOICE_HEADER)
| 일자 | Code | 거래처 | 유형 | 품명 | 공급가액 | 부가세 | 합계 | 차변계정 | 대변계정 | 관리 | 전표상태 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 09-15 | C201 | 가상고객A | 일반 | [26201] 가상 컨퍼런스 선금 | 100,000,000 | 10,000,000 | 110,000,000 | 수입수수료미수금 | 수입수수료 | | 처리 |
| 10-27 | C202 | 가상고객D | 일반 | 가상 전시부스 잔금 | 75,000,000 | 7,500,000 | 82,500,000 | 수입수수료미수금 | 수입수수료 | | 처리 |
| 10-28 | C203 | 가상고객X | 일반 | 기타 용역 | 20,000,000 | 2,000,000 | 22,000,000 | 수입수수료미수금 | 수입수수료 | | 처리 |
| 10-29 | C203 | 가상고객X | 수정 | 매출 정정 | −1,000,000 | −100,000 | −1,100,000 | 수입수수료미수금 | 수입수수료 | | 처리 |

## 6. 변환결과.txt format (plan 02-01; later plans add sections in the same format)

```
변환 시각 YYYY-MM-DD HH:MM:SS · 기준일 YYYY-MM-DD
WEHAGO 장부: <state> · 장부 기준일 YYYY-MM-DD · 분개장 <file> · 매입매출장 <file> · 전자세금계산서(매입) <file>
인트라넷 스냅숏: <folder name> (수집 YYYY-MM-DD HH:MM:SS) · 지급요청 N건 · 프로젝트 N건      (or: 인트라넷 스냅숏: 없음)
설정: <one line per config note, or '변환 설정 기본값 사용' / '설정.csv 변환 항목 반영'>
[손익.csv] 만듦 N줄
  대조 <label>: 원본 <won> · CSV <won> → 일치
  알림 <note>
[계산서.csv] 만들지 않음 — 자료 없음 (매출 계산서 엑셀)
...
이전 파일: 입력/이전/<YYYYMMDD_HHMMSS>/ (<names>)          (or: 이전 파일: 없음)
손대지 않은 파일: 계좌잔액.csv, 설정.csv, 지급계획.csv, 변경내역.csv, 자료기준일.csv, 프로젝트연결.csv
대조 불일치 N건                                           (always printed; 0 on every fixture)
```
Amounts use `util.won` (commas, '−' for negatives, '미확인' for None). Tests read lines starting with '  대조 ' and
require the suffix '→ 일치'.
