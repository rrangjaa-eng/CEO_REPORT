---
gsd_state_version: "1.0"
status: unknown
stopped_at: Completed 01.1-06-PLAN.md
last_updated: "2026-11-02T11:16:13.031Z"
last_activity: 2026-11-02
state_head: 1eed66db36fabcf9b905071425a35d79d2d61756
progress:
  total_phases: 4
  completed_phases: 0
  total_plans: 8
  completed_plans: 7
  percent: 0
current_phase_name: approval-screen
---

# State

## Project Reference

See: .planning/PROJECT.md (updated 2026-11-02)
**Core value:** 수익·현금·예정·예산 집행을 섞지 않고 미확인 값을 0으로 넣지 않는다
**Current focus:** Phase 01.1 — approval-screen

## Position

Phase 01.1 (approval-screen) · Plans 6 of 6 complete (01.1-01 .. 01.1-06) · Phase 1 plans 01-01, 01-02 complete · Next: orchestrator verification of 01.1 and ticking XCHK-01..04 / APPR-05 in REQUIREMENTS.md; human checks on the user's Windows PC pending (see .planning/WINDOWS.md) · Phase 02 (source-conversion): plans 02-01 (변환.py, 손익.csv company rows, safe write), 02-02 (linking.py D-38 engine, 프로젝트연결.csv template) and 02-03 (snapshot + linking in convert.run, 손익.csv 팀/프로젝트/미연결 rows with per-month sum checks, [연결] work list in 변환결과.txt) and 02-04 (convert_projects.py: build_projects / build_execs, B3 snapshot and request reconciliations, D-49 carried manual columns, D-50 larger-of invoice and request) complete; next 02-05
Last activity: 2026-11-02

## Decisions

- 연구 단계 생략(사용자 구성안 상세)
- gstack 미설치(세션에서 설치 거부) → Post-build 게이트는 GSD code-review/ui-review/verify-work로 대체(사용자 확인 대기)
- [Phase 1]: 01-01: known 사용제한금액 of a balance-unknown account stays subtracted from 사용 가능액 (A-11)
- [Phase 1]: 01-01: blank/missing/junk 설정 values use DEFAULT_SETTINGS only with an 입력 확인 entry and '기본값 사용(...)' mark in the risk note
- [Phase 1]: 01-02: 원가 예산 = 사전견적 x 예산_원가율 (default 0.70, valid 0<r<=1); invalid rate gives no budget for any project, blank/missing uses default with 입력 확인 entry
- [Phase 1]: 01-02: 미발행 is 판단 불가 whenever any invoice supply of the project is unknown; section 5/7 unknown amounts shown as counts next to totals
- [Phase 01.1] 01.1-01: A['amount_unknown'] = requests with unknown amount; unknown-amount schedule events are in A['amount_unknown_events']
- [Phase 01.1] 01.1-01: pending request with unreadable 등록일 and no 지급요청일 is 날짜 확인 불가; weeks table in won, headline/toggle in 백만원 (P-9)
- [Phase 01.1]: 01.1-02: page link equal to the current page after canonicalisation (page=1, no page name, trailing /0) is recognised but not fetched
- [Phase 01.1]: 01.1-02: any list row with a differing cell count, a blank 번호, or a page link that also changes a filter value stops the run (no partial rows)
- [Phase 01.1]: 01.1-03: structure_report ok also requires no cell-count mismatch and no paging stop, so 'matches' means a full run will not stop at page 1
- [Phase 01.1]: 01.1-03: disk failure after a successful collection exits 7 (separate try block); the password prompt refuses an echoing getpass fallback (exit 2)
- [Phase 01.1]: 01.1-04: duplicate project keys are 판단 불가 and never listed as 미요청 실행가; the 390px browser check runs in a 390px iframe because headless Chrome here has a 500px minimum window
- [Phase 01.1]: 01.1-05: books not 'ok' empty journal/ledger/einvoice (no partial use); read_book(path, kind, file_date, asof) is the public per-file reader and raises HeaderMismatch; a shared payment line gives '연결 불가 (지급 후보 N건)' with N = candidate lines (1), a shared invoice '연결 불가 (계산서 후보 공유)'
- [Phase 01.1]: 01.1-05: XCHK-01..04 stay unchecked until plan 01.1-06 (screen shows 장부 기준일/상태/차이; .gitignore '*.xlsx'); unknown ref date or missing folder gives 경과 / 자료 없음, never a guess
- [Phase 01.1]: 01.1-06: D-35b wins over the old must_have: an '이미 지급' request paid after the 잔액 기준일 stays as a fixed outflow on the payment date (rolled to the first schedule day if earlier); only payments on or before the 잔액 기준일 leave the schedule
- [Phase 01.1]: 01.1-06: WEHAGO screen texts (stop lines, summary, 장부 기준일) live in approval_render.py and are shared with the CLI; approval.build(d, snap, asof, now, wehago_dir=None) imports wehago inside the function to avoid a circular import

## Blockers

- WEHAGO 접근: 사용자가 Chrome 로그인 후 진행

## Performance Metrics

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 1 P01 | ~10m | 3 tasks | 5 files |
| Phase 1 P02 | ~30m | 3 tasks | 12 files |
| Phase 01.1 P01 | ~10min | 2 tasks | 8 files |
| Phase 01.1 P02 | 6 min | 3 tasks | 3 files |
| Phase 01.1 P03 | ~25min | 3 tasks | 4 files |
| Phase 01.1 P04 | ~14min | 3 tasks | 3 files |
| Phase 01.1 P05 | ~40min | 3 tasks | 2 files |
| Phase 01.1 P06 | ~50min | 3 tasks | 5 files |

## Session

**Last session:** 2026-11-02T11:16:12.987Z
**Stopped at:** Completed 01.1-06-PLAN.md
**Resume file:** None
