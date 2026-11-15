---
phase: 02-source-conversion
plan: 08
subsystem: source-conversion
tags: [approval-screen, linking, d-47, d-38, xchk, b5, tdd, python-stdlib]
status: complete

requires:
  - phase: 02-source-conversion
    provides: "02-02 linking.link_costs / projects_of / read_links; 02-01 convert.read_config; 02-06 build_xchk / load_xchk (monthly side of the equality tests); 02-05 / 02-03 convert.build_links"
provides:
  - "ceo_report/wehago.py: project_costs(books, project_keys, links=None) - links = linking.link_costs result; items add basis / label / request"
  - "ceo_report/approval.py: build(d, snap, asof, now, wehago_dir=None, input_dir=None) links (도) cost with linking.link_costs; A['xchk']['link_summary']; rows for linked keys outside the project list"
  - "ceo_report/approval_render.py: unlinked panel column '연결', ' · 연결: 수동 N줄 · 코드 N줄 · 자동 N줄 · 미연결 N줄', WEHAGO rule 5 reads the D-38 order"
  - "승인검토.py: make_screen passes input_dir to build"
  - "tests/test_approval_linking.py: screen / work_input / monthly_side / both helpers; TestApprovalLinking, TestApprovalLinkingCases, TestApprovalLinkingPanel, TestApprovalMonthlyEqual"
affects: [02-10 (pipeline-level comparison of 변환.py output and rendered section 8 against the approval screen)]

plan_head_before: 2549841eeb119fafd258f800146c99160b5743ef
actuals:
  tokens: 11000
  tasks: 3
  commits: 6

tech-stack:
  added: []
  patterns:
    - "One implementation of D-38 (linking.py) for both surfaces; wehago.project_costs only reshapes a link_costs result into the 01.1 panel shape"
    - "approval.build imports linking / convert inside the function (import cycle approval <-> linking <-> wehago); an AST test checks that neither approval.py nor wehago.py imports them at module level"
    - "Equality tests build the monthly side exactly as convert._build_tables does (read_config, build_links, match_requests, build_projects, build_xchk) and read it back through write_table -> load_xchk"

key-files:
  created:
    - tests/test_approval_linking.py
  modified:
    - ceo_report/wehago.py
    - ceo_report/approval.py
    - ceo_report/approval_render.py
    - 승인검토.py
    - tests/test_approval_wehago.py
    - tests/test_linking.py

key-decisions:
  - "Link settings and overrides come from the same readers 변환.py uses (linking.read_links, convert.read_config); without input_dir there are no overrides and linking's own keyword defaults (90 days, prefix 6, (도), 13500)"
  - "Notes: bad 프로젝트연결.csv rows and unusable 설정.csv 변환_* items go to A['issues']; '프로젝트연결.csv 없음' and '설정.csv 없음/읽지 못함' are not added, so 01.1 issue counts do not change (test compares issues with and without input_dir)"
  - "Books not 'ok': no linking, panels keep 판단 불가, link_summary None (A-4)"
  - "Rows for linked keys outside the list come after the listed projects in number order (monthly lists them the same way); A['xchk']['projects_without_cost'] counts only listed projects"
  - "' · 연결: ...' follows the first sentence of the panel line, before ' · 표시 N건 / 전체 M건'; the 0건 panel also shows it"

requirements-completed: []

duration: ~1h20
completed: 2026-11-02
---

# Phase 2 Plan 08: Approval screen uses the D-38 project linking (D-47) Summary

**The approval screen's project table and unlinked-cost panel now come from linking.link_costs (manual 프로젝트연결.csv -> [code] -> automatic -> 미연결) with the 설정.csv 변환_* values 변환.py uses; on the LINK fixture 26220 shows 158,200,000 (전표 40 via 지급요청 6001), the unlinked panel reads 6건 3,200,000 with a 연결 label per line, and tests prove the approval 원가, 요청 누계 and unlinked count/sum equal the monthly 위하고대조 facts per project for the default, link-days 200 and manual-link settings.**

## What was built

- `wehago.project_costs(books, keys, links=None)`: with `links` (a `link_costs` result) every line whose basis is not '미연결' goes under its project - any key, also one outside `project_keys` - and '미연결' lines go to `unlinked`; items keep date / vendor / memo / amount and add basis, label, request; sums stay `ssum_or_none`. `links=None` is the 01.1 code-only path (test_wehago.py untouched and green).
- `approval.build(..., input_dir=None)`: when the books are 'ok' it calls `linking.link_costs(books, req_all, projects_of(snap), overrides, link_days, direct_prefixes, direct_mark, vat_codes)` (lazy imports). With `input_dir`: overrides from `read_links`, the four settings from `read_config`; bad-row / bad-setting notes go to the issues list. `승인검토.make_screen` passes `input_dir=input_dir`.
- Project table: a row '26888' named '(프로젝트 목록에 없음)' for a manual link to a number that is not in the intranet list (실행가 '미확인', 요청 누계 '판단 불가', 원가 800,000 on the fixture). The cost is in the project table, not in the unlinked panel, never in neither.
- Unlinked panel: last column '연결' (`_w`: mask_rrn then esc) with the line's linking label, e.g. 전표 41 '미연결 (자동 연결 후보 2건: 지급요청 6002, 6003)', 전표 42/43 '미연결 (자동 연결 후보 공유: 지급요청 6004)'; the line keeps starting '프로젝트 미연결 원가 N건 <won>' and adds ' · 연결: 수동 0줄 · 코드 8줄 · 자동 1줄 · 미연결 6줄' (default LINK fixture). WEHAGO rule 5 now reads: 수동(프로젝트연결.csv) -> 적요의 [프로젝트 코드] -> 자동(거래처·금액·기간이 같은 지급요청이 후보 하나일 때만) -> 미연결, and says that accounts, mark and days follow 설정.csv 변환_*.
- Numbers (FAKE_JOURNAL + LINK_EXTRA, FAKE snapshot + LINK_REQUESTS, sample input): 26201 40,000,000 / 26220 158,200,000 / 26221 5,400,000 / 26203 45,000,000, unlinked 6건 3,200,000 (전표 22, 23, 41, 42, 43, 44); link-days 200: 26201 41,000,000 and 5건 2,200,000; manual 22 -> 26221: 6,200,000 and 5건 2,400,000; manual 22 -> 26888: row 26888 800,000 and 5건 2,400,000. Σ project rows + unlinked = 251,800,000 in all four cases. On the 01.1 fixtures (FAKE_JOURNAL, FAKE snapshot): 40 / 158 / 5.4 / 45 million and 2건 1,100,000 (전표 22, 23) as before.

## Commits

| Task | RED | GREEN |
|---|---|---|
| 1 tracer (project_costs links, build input_dir, make_screen) | 6e3b9be test(02-08): RED Task 1 tracer | f0e23c3 feat(02-08): GREEN Task 1 tracer |
| 2 (cases, 연결 column, summary, rule 5, 26888 row) | fa87a5f test(02-08): RED Task 2 | c1bc8f1 feat(02-08): GREEN Task 2 |
| 3 (approval = monthly per project) | 27abb94 test(02-08): RED Task 3 | 5ebbd49 test(02-08): Task 3 characterization (no code changed) |

(`commits: 6` is measured with `git rev-list --count 2549841..HEAD` before this summary's own docs commit; the ledger `.git/gsd-plan-head-before-02-08` was written before the first commit.)

## Tests

Full suite 877 -> 913 (+36), all OK (`python3 -m unittest discover -s tests`). New: TestApprovalLinking 12, TestApprovalLinkingCases 10, TestApprovalLinkingPanel 7, TestApprovalMonthlyEqual 7 (each also run alone with `-k`, ran >= 1). `git diff --quiet cbc5497 -- ceo_report/calc.py ceo_report/data.py tests/test_wehago.py` exits 0; `grep -n "^from .linking\|^from .convert\|^import .*linking" ceo_report/approval.py ceo_report/wehago.py` prints nothing; changed .py files parse with `ast.parse(..., feature_version=(3, 8))`.

### RED evidence

- Task 1: 11 of 12 failed (`FAILED (failures=4, errors=7)`: `project_costs() got an unexpected keyword argument 'links'` x6, `build() got an unexpected keyword argument 'input_dir'`, 26220 `158000000 != 158200000`, unlinked `(7, 3400000) != (6, 3200000)`, 26201 `40000000 != 41000000` for the pass-through test). **Not a real RED:** `test_no_module_level_import_of_linking_or_convert_in_approval_and_wehago` passed on the old code (it guards the cycle prohibition).
- Task 2: 9 of 17 new tests failed plus `test_approval_wehago.TestXchkPanels.test_unlinked_cost` (five-cell rows). **Eight tests were not a real RED** - they passed on the Task 1 code and pin it: `test_default_unlinked_panel_lists_the_lines_of_slips_22_23_41_42_43_44`, `test_link_days_200_moves_slip_41_to_26201`, `test_a_manual_link_of_slip_22_to_26221`, `test_the_01_1_fixtures_keep_their_numbers`, `test_a_bad_link_row_is_shown_in_the_approval_issues`, `test_an_unusable_conversion_setting_is_shown_in_the_approval_issues`, `test_a_missing_link_file_and_a_missing_settings_note_add_no_issue`, `test_the_real_screen_shows_no_social_security_number` (the Task 1 GREEN code already did the pass-through and the issue notes). One RED test (`test_the_unlinked_table_has_a_last_column...`) also had a wrong header regex that I fixed in the GREEN commit (the assertion would have failed on the missing column anyway).
- Task 3 (worktree proof, W6): the RED Task 3 tests passed on HEAD, so I ran them in `git worktree add --detach .../pre0208 6e3b9be` (the commit before `feat(02-08): GREEN Task 1 tracer`, `grep -c link_costs ceo_report/approval.py` = 0 there) with the final `tests/test_approval_linking.py` copied in: `python3 -m unittest tests.test_approval_linking.TestApprovalMonthlyEqual` -> `FAILED (failures=3, errors=1)` of 7, failing lines `AssertionError: 158000000 != 158200000 : default 26220 WEHAGO 원가` and `AssertionError: 7 != 6 : default` (unlinked count), plus the 26888 test (`TypeError: 'NoneType' object is not subscriptable`, no 26888 row) and the unknown-amount test (`158000000 != 158200000`). Three of the seven passed there (`test_the_known_numbers_of_the_three_settings` - it only reads the monthly side -, `test_a_request_total_with_an_unknown_amount_is_blank_on_both_surfaces`, `test_projects_without_a_cost_line_are_only_in_the_monthly_table_with_zero_lines`; the last two compare things the old code already did the same way). The worktree was removed (`git worktree list` shows only the main tree). Because the class fails without this plan's wiring, it is not labelled 'characterization'; the final commit is named `test(02-08): Task 3 characterization` only because no code had to change in Task 3, and it records this evidence in the class docstring.

## Deviations from Plan

**1. [Rule 3 - blocking] `tests/test_linking.py` scope guard.** `TestLinkingScope.test_approval_calc_data_unchanged_and_no_02_02_commit_touches_wehago` (plan 02-02) asserted `git diff --quiet cbc5497 -- approval.py calc.py data.py`; this plan changes approval.py on purpose (D-47), so it failed on the Task 1 GREEN run. I removed approval.py from that diff list (calc.py and data.py are still pinned, and the 02-02-commits-do-not-touch-wehago check is unchanged), renamed the test to `test_calc_data_unchanged_and_no_02_02_commit_touches_wehago` and left a comment. The file is not in the plan's `files_modified`.

**2. [Changed 01.1 assertion, as the plan states]** `test_approval_wehago.TestXchkPanels.test_unlinked_cost`: the rows have five cells now (first four unchanged, fifth = the line's label: '미연결 (코드 없음 · 자동 연결 후보 0건)' for 전표 22 and '미연결 (코드 26999 프로젝트 목록에 없음 · 자동 연결 후보 0건)' for 전표 23), comment cites D-47. No other 01.1 assertion changed; the 01.1 numbers (2건 1,100,000 and the 158,000,000 on the 01.1 fixtures) hold.

**3. [Rule 2 - additions the plan did not name]**
- `A['xchk']['link_summary']` (basis -> count / sum / unknown, None when books are not 'ok') feeds the panel line.
- `projects_without_cost` ignores rows for keys outside the list (otherwise the '원가 줄이 없는 프로젝트 N개' count would be wrong after the 26888 row).
- The '0건' unlinked panel also shows the ' · 연결: ...' summary; the plan only named the N>0 line.
- `wehago._cost_result` helper (the shared tail of the two paths), `approval.NOT_LISTED` (same text as convert_xchk's), `approval_render.LINK_BASES` (render must not import linking).

**4. [Interface wording]** The plan says the issues note for a bad 프로젝트연결.csv row is "added to the approval issues list"; I split `프로젝트연결.csv N번째 줄: ...` into file / line / message so the screen reads like the other issues. Notes of read_config that start with '설정.csv' (missing or unreadable file) are not added; only item-level notes ('설정 변환_... 값 ... 사용할 수 없음 → 기본값 ...') are.

**5. [Commit trailer]** Commits end with `Co-Authored-By: Claude Sonnet 5.5` (the attribution the harness gave this session, as in 02-04 .. 02-06) instead of the `Opus 5.5` line in the task template; the `Claude-Session` line is the same.

**6. [Process]** The Task 3 'GREEN' commit is test-only (a docstring); Task 3 needed no code change, so truth 5 was already met after Task 1 and 2. Test and code for the pass-through and the issue notes were therefore both in Task 1/2 rather than Task 3.

## Notes on overstating / understating

- **Approval versus monthly when a cost line has no amount:** the monthly 위하고대조 cell is blank (B5: any unknown contributor blanks the sum), the approval screen keeps its 01.1 presentation - the known part plus '외 금액 미확인 N줄' (`wehago.project_costs` uses `ssum_or_none`, not changed: D-47 scope). `test_a_cost_line_without_an_amount_is_unknown_on_the_monthly_side_and_flagged_on_the_screen` pins this; the two never show different known numbers, and neither shows an unknown as 0. The same holds for the unlinked sum.
- **Understate risk (noted):** a line shared between candidates (e.g. 전표 42/43 for 지급요청 6004) or with several candidates stays '미연결' until a person adds a 프로젝트연결.csv row, so a project's linked cost can be lower than its true cost; the unlinked count and sum are always printed next to it (and Σ rows + unlinked equals the books total in every case tested).
- **Overstating:** none added. The 중복 가능 ambiguous-group row of 프로젝트집행.csv (02-04) is not part of this plan.
- Requests whose status cannot be read stay out of 요청 누계 on both surfaces (the approval rule; the monthly table notes them).

## Not verified

- Python 3.8 runtime (only `ast.parse(..., feature_version=(3, 8))`; runtime was 3.13).
- The pipeline-level comparison on a real 변환.py output and the rendered section 8 (plan 02-10); here the monthly side is `build_xchk -> write_table -> load_xchk` on synthetic data.
- Real WEHAGO downloads and a real 프로젝트연결.csv saved by Excel; the approval screen in a browser (only the HTML was parsed); the Windows launcher. No real company data was opened (`입력/`, `수집/`, realbooks untouched).
- A project key that appears twice in the intranet list keeps its 01.1 behaviour (two rows, 판단 불가 differences); not compared with the monthly one-row view.
- REQUIREMENTS.md checkboxes not ticked (orchestrator does it); ROADMAP.md not edited.

## Known Stubs

None.

## Threat Flags

None beyond the plan's threat model: T-02-34 (one linking implementation + equality tests + Σ check), T-02-35 (every new cell goes through `_w`; handcrafted-A test with an RRN-shaped label / vendor / memo and HTML tags, plus the RRN sweep of the real screen), T-02-36 (read_links / read_config notes shown in the approval issues; bad-row and bad-setting tests).

## Self-Check: PASSED

- Files exist: tests/test_approval_linking.py, ceo_report/wehago.py, ceo_report/approval.py, ceo_report/approval_render.py, 승인검토.py (all FOUND).
- Commits exist: 6e3b9be, f0e23c3, fa87a5f, c1bc8f1, 27abb94, 5ebbd49 (all FOUND in git log).
- `python3 -m unittest discover -s tests` -> Ran 913 tests, OK.
