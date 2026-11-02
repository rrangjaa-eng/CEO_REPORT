---
phase: 02-source-conversion
verified: 2026-11-02T20:30:00Z
status: human_needed
score: 9/9 must-haves verified
covered_files:
  - .planning/REQUIREMENTS.md
  - .planning/phases/02-source-conversion/02-01-PLAN.md
  - .planning/phases/02-source-conversion/02-01-SUMMARY.md
  - .planning/phases/02-source-conversion/02-02-PLAN.md
  - .planning/phases/02-source-conversion/02-02-SUMMARY.md
  - .planning/phases/02-source-conversion/02-03-PLAN.md
  - .planning/phases/02-source-conversion/02-03-SUMMARY.md
  - .planning/phases/02-source-conversion/02-04-PLAN.md
  - .planning/phases/02-source-conversion/02-04-SUMMARY.md
  - .planning/phases/02-source-conversion/02-05-PLAN.md
  - .planning/phases/02-source-conversion/02-05-SUMMARY.md
  - .planning/phases/02-source-conversion/02-06-PLAN.md
  - .planning/phases/02-source-conversion/02-06-SUMMARY.md
  - .planning/phases/02-source-conversion/02-07-PLAN.md
  - .planning/phases/02-source-conversion/02-07-SUMMARY.md
  - .planning/phases/02-source-conversion/02-08-PLAN.md
  - .planning/phases/02-source-conversion/02-08-SUMMARY.md
  - .planning/phases/02-source-conversion/02-09-PLAN.md
  - .planning/phases/02-source-conversion/02-09-SUMMARY.md
  - .planning/phases/02-source-conversion/02-10-PLAN.md
  - .planning/phases/02-source-conversion/02-10-SUMMARY.md
  - .planning/phases/02-source-conversion/02-CONTEXT.md
  - ceo_report/approval.py
  - ceo_report/approval_render.py
  - ceo_report/convert.py
  - ceo_report/convert_invoices.py
  - ceo_report/convert_pl.py
  - ceo_report/convert_projects.py
  - ceo_report/convert_xchk.py
  - ceo_report/linking.py
  - ceo_report/render.py
  - ceo_report/wehago.py
  - 변환.py
  - 보고서.py
  - 승인검토.py
  - 실행_변환.bat
covered_digest: "v1:sha256:bbe1aa7b9614394fc071cd02fd379d13f4986343b8e41b4143a310bd758089f1"
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Windows PC: put the real 분개장, 매입매출장, 전자세금계산서(매입) and the sales invoice download (Q-1 screen name) into 수집\\위하고, double-click 실행_변환.bat"
    expected: "exit 0, 입력\\변환결과.txt ends '대조 불일치 0건', the 미연결 list is readable and can be reviewed (WINDOWS.md #3)"
    why_human: "Real WEHAGO downloads, the real column layout of the sales invoice download, and the Windows .bat launcher cannot be exercised here; only synthetic fixtures were used"
  - test: "Windows PC: run 실행_월간.bat after 실행_변환.bat"
    expected: "Section 8 'WEHAGO 기준 대조' present in both editions; the CEO edition shows facts only (no 경영관리 detail tables, no risk words); the 보통예금 line is shown (WINDOWS.md #4)"
    why_human: "Reading quality and layout on the user's PC with real data; launcher behaviour on Windows"
  - test: "Windows PC: run 실행_승인검토.bat after conversion"
    expected: "Per-project WEHAGO (도) 원가, 요청 누계 and 프로젝트 미연결 원가 count/sum equal monthly section 8 (요청 누계 differs only by the 상태 확인 필요 requests, D-52) (WINDOWS.md #5)"
    why_human: "Needs the real intranet snapshot and real books; Edge rendering and the .bat launcher"
  - test: "Answer open questions Q-1 (which SmartA screen produces the sales invoice download) and Q-2 (auto-link window, default 90 days) with the user"
    expected: "Q-1 screen name confirmed against the three sales readers in wehago.py/convert_invoices.py; Q-2 default kept or changed in 설정.csv 변환_자동연결일수 (WINDOWS.md #6)"
    why_human: "User decision; the real sales download layout has never been seen by the code"
  - test: "Windows PC: after conversion and the three reports, run git status"
    expected: "No file under 입력/ or 수집/ and no WEHAGO xlsx appears (WINDOWS.md #7)"
    why_human: "Checked here only by git check-ignore on synthetic paths, not on the user's real folders"
---

# Phase 2: 원천자료 변환 Verification Report

**Phase Goal:** 실제 WEHAGO 내려받기와 인트라넷 보관자료로 보고서를 만든다
**Verified:** 2026-11-02
**Status:** human_needed
**Re-verification:** No - initial verification (code review fixes CR-01..05 and WR-01..06 were checked as part of this pass)

All checks below were run on a synthetic company built from the test fixtures (`tests/test_convert_e2e.full_company`, copied to a scratchpad folder). No real data (`입력/`, `수집/`, realbooks) was opened. The working tree stayed clean (`git status` empty).

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1: WEHAGO Excel converts to 손익 and 계산서 CSV and totals equal the source | VERIFIED | `python3 변환.py` exit 0. I parsed the 분개장 xlsx independently with zipfile/regex: 매출 (41200) 194,000,000, (도) 직접비 259,500,000, 공통비 (8xxxx) 6,500,000. 손익.csv 회사 rows for 2026-09..10 sum to exactly those; 계산서.csv 공급가액 194,000,000 (4 rows, matching the sales source). 변환결과.txt: 52 `대조` lines, 0 not ending `일치`, last line `대조 불일치 0건` |
| 2 | SC2: Intranet snapshot converts to 프로젝트 and 프로젝트집행 CSV and counts and sums equal the collection | VERIFIED | 프로젝트.csv: 4 snapshot projects, 사전견적 820,000,000, 실행가 610,000,000 with 1 blank (blank counted, not zeroed). 프로젝트집행.csv: 지급요청 9건, 266,364,000 plus 1 amount-unknown request, all `일치`; 6 previous-only projects carried (WR-03) |
| 3 | SRC-01 second half: monthly report section 8 "WEHAGO 기준 대조" in both editions | VERIFIED | `보고서.py 월간 --기준일 2026-10-31` exit 0; `id='s8'` present in 대표 and 경영관리 HTML with the same summary table (7 rows incl. 보통예금) |
| 4 | Section 8 CEO edition is facts only and numbers are equal across editions | VERIFIED | 대표용 section 8 has the summary only (1,470 chars), no `xchk-detail`; no word of FORBIDDEN (위험, 해결방안, 권고, 우려, 추천) anywhere in the CEO page; summary table text identical in both editions; `numbers_of(대표) == numbers_of(경영관리)` is True (2,674 numbers). The 경영관리 page contains 위험/해결방안 only in its risk sections as designed |
| 5 | Approval screen shows the same per-project cost as section 8 (D-47) | VERIFIED | Both give 26201 50,000,000; 26220 158,000,000; 26221 5,400,000; 26203 45,000,000; 프로젝트 미연결 원가 2건 1,100,000 (`연결: 코드 9줄, 미연결 2줄` on both). 요청 누계 equal for 26220 (166,000,000), 26203 (49,500,000), 26221 판단 불가; 26201 differs by 1,100,000 = request 5107, the 상태 확인 필요 request, exactly as D-52 specifies |
| 6 | Weekly report HTML unchanged versus cbc5497 | VERIFIED | `git archive cbc5497` run on the converted folder: 주간 대표 and 경영관리 HTML identical to the current code's output after stripping the 작성 time. `git diff cbc5497 HEAD` on calc.py, data.py, intranet.py, snapshot.py and the three weekly/monthly/approval .bat files is empty; weekly has no section 8 |
| 7 | Unknowns are counted, never zeroed (D-02) | VERIFIED | 5106 amount blank in 프로젝트집행.csv, 지급요청 금액 미확인 1건 reconciled; section 8 shows `금액 판단 불가 (미확인 1건)`, 실행가 `판단 불가`, 보통예금 장부 잔액 `판단 불가 (기초 잔액 줄 없음)`, 계약금액 `미등록 2건`, 거래처 미지급 `판단 불가 2곳`; approval screen `금액 미확인 요청 1건 (일정 제외)` |
| 8 | Safe overwrite and source rules (D-43/D-45/D-46/D-48) | VERIFIED | 이전 backup folder made; manual files (계좌잔액, 설정, 지급계획, 변경내역, 자료기준일, 입출금내역, 자금일정, 자료차이) byte-identical to a fresh sample; 입출금내역.csv not written; re-run gives byte-identical five CSVs; with the sales xlsx removed 계산서.csv is kept byte-identical with the D-46 message `기존 계산서.csv 유지 (갱신 안 됨, 작성일 ...)`; 주민번호 masked (`******-*******`) in CSV, 변환결과, HTML; `.gitignore` covers 입력/, 수집/, *.xlsx; `git ls-files` shows no real data; no TBD/FIXME/XXX added since cbc5497 |
| 9 | Code review CR-01..05 and WR-01..06 are really fixed | VERIFIED | Re-ran the reviewer's seven repro scripts: A (auto-link double count) 220,000 not 440,000; B (paid diff) 차액 500,000 row, sum 6,000,000; C (unreadable status) now in 요청 누계, 프로젝트밖요청, section 8; D (partial 분개장) YTD 975,000,000 kept; E (partial receipts) 입금액 110,000,000; G (overflow) clamped to 90; F covered at `write_files` by TestWR01Rollback (rollback restores both files) plus a run-level test (exit 7). WR-03/04/05/06 are visible in the 변환결과 output above (previous-only projects, hand-entered rows carried, period labels, snapshot age line) |

**Score:** 9/9 truths verified (0 present, behavior-unverified)

Full suite: `python3 -m unittest discover -s tests` Ran 1057 tests, OK.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `변환.py`, `실행_변환.bat` | conversion CLI and launcher | VERIFIED | CLI ran end-to-end on a synthetic company; the .bat itself needs Windows (human item 1) |
| `ceo_report/convert.py`, `convert_pl.py`, `convert_invoices.py`, `convert_projects.py`, `convert_xchk.py` | CSV builders and 대조 | VERIFIED | All five CSVs written; every check matches |
| `ceo_report/linking.py` | D-38 link engine | VERIFIED | used by conversion and the approval screen (D-47); 코드 9줄, 미연결 2줄 on both surfaces |
| `ceo_report/render.py` section 8 | 월간 8번 | VERIFIED | both editions; CEO facts only |
| `ceo_report/approval.py`, `approval_render.py` | D-47 linking | VERIFIED | same per-project cost as section 8 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| 변환.py | 입력/*.csv, 변환결과.txt | `convert.run` | WIRED | five CSVs and result file written |
| 위하고대조.csv | 월간 section 8 | `load_xchk` | WIRED | values appear in both editions |
| linking.py | 승인검토 and 월간 | `link_costs` | WIRED | equal per-project 원가 |
| converted 입력/ | 주간 보고 | `data.load` | WIRED | weekly renders; identical to cbc5497 code |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| 손익.csv | 매출/직접비/공통비 | 분개장 xlsx | Yes (equal to the independent sums) | FLOWING |
| 프로젝트집행.csv | 지급요청 rows | snapshot 지급요청.csv | Yes (9 requests, 266,364,000) | FLOWING |
| section 8 | 프로젝트별 원가 | 위하고대조.csv | Yes (equals the approval screen) | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Conversion end-to-end | `python3 변환.py --기준일 2026-11-02 --입력 ... --수집폴더 ... --위하고폴더 ...` | exit 0, 불일치 0건 | PASS |
| Monthly both editions | `python3 보고서.py 월간 --기준일 2026-10-31 --입력 ... --pdf 안함` | exit 0, 2 HTML | PASS |
| Weekly vs cbc5497 | same command with both trees | identical after stripping 작성 time | PASS |
| Approval screen | `python3 승인검토.py --수집 안함 --열기 안함 ...` | exit 0; no network use | PASS |
| Idempotence | second `변환.py` run | five CSVs byte-identical | PASS |
| D-46 | sales xlsx removed, rerun | 계산서.csv unchanged, message shown | PASS |

### Probe Execution

SKIPPED: the phase declares no `probe-*.sh` scripts and `scripts/` has none.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| SRC-01 | 02-01, 02-03, 02-05..02-10 | WEHAGO Excel to 손익/계산서 input CSV and the monthly 기준 대조 | SATISFIED on synthetic data; real-data confirmation is human | Truths 1, 3, 4, 5, 6. 채권채무 (AR/AP) input: the plans deliberately do not produce a separate CSV (D-48: 미지급금·미지급비용 as 위하고대조 facts; AR via 계산서.csv 입금), which is a narrowing of the requirement text that is documented in CONTEXT |
| SRC-02 | 02-02, 02-04, 02-07, 02-08 | Intranet snapshot to 프로젝트/집행 CSV | SATISFIED on synthetic data; real snapshot is human | Truth 2 |

No ORPHANED requirements: only SRC-01 and SRC-02 map to Phase 2. REQUIREMENTS.md boxes remain unticked on purpose (not changed by this verification).

### Anti-Patterns Found

None blocking. No TBD/FIXME/XXX added in phase files. The code review's seven Info findings were left unfixed on purpose (Critical/Warning only). They are advisory, none breaks a must-have:

| ID | Concern | Severity |
|----|---------|----------|
| IN-05 (`convert_projects.py:293-304`) | A slip with any 보통예금 credit and no `payable_codes` credit marks the cost 지급완료. With a non-default chart (a liability outside the payable codes, e.g. 25100) this could understate an outflow | Advisory (default chart unaffected) |
| IN-01 | Section 8 label hard-codes `보통예금 (WEHAGO 10300)` although the account is a setting | Advisory |
| IN-04 | 프로젝트연결.csv keys depend on line position inside a 전표; a re-download that reorders lines can re-point an override | Advisory |
| IN-02, IN-03, IN-06, IN-07 | misleading note, midnight timestamp with `--기준일`, wrong file name in an error, duplicated helpers | Cosmetic |

### Notes

- D-52 treats a request with 사장님승인 `반려` like any unreadable status: it is kept as a 요청미지급 estimate and flagged `상태 확인 필요 1건`. That follows the locked decision (never understate outflows, never drop silently) but means a truly rejected request is counted until a person removes it. It is flagged on every surface, so it is not a gap.
- `.planning/ROADMAP.md` still shows Phase 2 as `[ ]` and the progress table as `0/10`, and REQUIREMENTS.md SRC-01/02 are unticked. Both are bookkeeping for the orchestrator after the human items are done.
- `.planning/WINDOWS.md` has 5 open phase-02 `unrun-verify` rows (ids 3-7); they are the human_verification items above.

### Human Verification Required

See the `human_verification` list in the frontmatter: five items, all on the user's Windows PC, with the real intranet snapshot, or needing the sales invoice download and a user answer (Q-1, Q-2).

### Gaps Summary

No gaps. Every roadmap success criterion and every locked decision that can be checked without the user's PC holds on the synthetic company. The phase is `human_needed` only because real WEHAGO downloads, the real intranet snapshot, the sales invoice download screen (Q-1) and the Windows launchers have not been exercised.

---

_Verified: 2026-11-02_
_Verifier: Claude (gsd-verifier)_
