---
schema_version: 1
open_count: 7
waived_count: 0
fixed_count: 0
total_count: 7
last_updated: 2026-11-02T19:37:10.610Z
---

# Broken Windows Ledger

> Cross-phase defect register. With `workflow.windows_enforce` enabled, `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 01.1 | unrun-verify | 실행_승인검토.bat |  | Plan 01.1-03 human checks 1-7 (구조 점검, double-click timing, toggles, D-17 dates, --수집 안함, git status, findstr) pending on the user's Windows PC | open |  | 2026-11-02T10:25:34.514Z |  |
| 2 | 01.1 | unrun-verify | ceo_report/approval_render.py |  | 01.1-04 human check on the user's PC: open 출력/승인검토_*.html in Edge, untick/re-tick one request, unplug network; narrow to phone width and check sticky headline and checkbox column | open |  | 2026-11-02T10:40:15.142Z |  |
| 3 | 02 | unrun-verify | 실행_변환.bat |  | Plan 02-10 human check 1 on the user's Windows PC: put 분개장, 매입매출장, 전자세금계산서(매입) and the sales invoice download (Q-1 screen name) into 수집\\위하고, double-click 실행_변환.bat; expect exit 0, 입력\\변환결과.txt ending '대조 불일치 0건', and a readable 미연결 list to review | open |  | 2026-11-02T19:37:03.235Z |  |
| 4 | 02 | unrun-verify | 실행_월간.bat |  | Plan 02-10 human check 2 on the user's PC: run 실행_월간.bat after 실행_변환.bat; section 8 'WEHAGO 기준 대조' present in both editions, 대표용 shows facts only (no 경영관리 detail tables, no risk words), 보통예금 line shown | open |  | 2026-11-02T19:37:09.995Z |  |
| 5 | 02 | unrun-verify | 실행_승인검토.bat |  | Plan 02-10 human check 3 on the user's PC: run 실행_승인검토.bat after conversion; per-project WEHAGO (도) 원가, 요청 누계 and 프로젝트 미연결 원가 count/sum equal monthly section 8 | open |  | 2026-11-02T19:37:10.193Z |  |
| 6 | 02 | unrun-verify | .planning/phases/02-source-conversion/02-CONTEXT.md |  | Plan 02-10 human check 4: confirm open questions Q-1 (sales invoice download screen name) and Q-2 with the user (Q-3 is decided in CONTEXT) | open |  | 2026-11-02T19:37:10.397Z |  |
| 7 | 02 | unrun-verify | .gitignore |  | Plan 02-10 human check 5 on the user's PC: after conversion and the three reports, git status shows no 입력/ or 수집/ file (and no WEHAGO xlsx) | open |  | 2026-11-02T19:37:10.610Z |  |

````json
[
  {
    "id": 1,
    "kind": "unrun-verify",
    "phase": "01.1",
    "file": "실행_승인검토.bat",
    "line": null,
    "description": "Plan 01.1-03 human checks 1-7 (구조 점검, double-click timing, toggles, D-17 dates, --수집 안함, git status, findstr) pending on the user's Windows PC",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-11-02T10:25:34.514Z",
    "resolved_at": null,
    "milestone": null
  },
  {
    "id": 2,
    "kind": "unrun-verify",
    "phase": "01.1",
    "file": "ceo_report/approval_render.py",
    "line": null,
    "description": "01.1-04 human check on the user's PC: open 출력/승인검토_*.html in Edge, untick/re-tick one request, unplug network; narrow to phone width and check sticky headline and checkbox column",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-11-02T10:40:15.142Z",
    "resolved_at": null,
    "milestone": null
  },
  {
    "id": 3,
    "kind": "unrun-verify",
    "phase": "02",
    "file": "실행_변환.bat",
    "line": null,
    "description": "Plan 02-10 human check 1 on the user's Windows PC: put 분개장, 매입매출장, 전자세금계산서(매입) and the sales invoice download (Q-1 screen name) into 수집\\위하고, double-click 실행_변환.bat; expect exit 0, 입력\\변환결과.txt ending '대조 불일치 0건', and a readable 미연결 list to review",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-11-02T19:37:03.235Z",
    "resolved_at": null,
    "milestone": null
  },
  {
    "id": 4,
    "kind": "unrun-verify",
    "phase": "02",
    "file": "실행_월간.bat",
    "line": null,
    "description": "Plan 02-10 human check 2 on the user's PC: run 실행_월간.bat after 실행_변환.bat; section 8 'WEHAGO 기준 대조' present in both editions, 대표용 shows facts only (no 경영관리 detail tables, no risk words), 보통예금 line shown",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-11-02T19:37:09.995Z",
    "resolved_at": null,
    "milestone": null
  },
  {
    "id": 5,
    "kind": "unrun-verify",
    "phase": "02",
    "file": "실행_승인검토.bat",
    "line": null,
    "description": "Plan 02-10 human check 3 on the user's PC: run 실행_승인검토.bat after conversion; per-project WEHAGO (도) 원가, 요청 누계 and 프로젝트 미연결 원가 count/sum equal monthly section 8",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-11-02T19:37:10.193Z",
    "resolved_at": null,
    "milestone": null
  },
  {
    "id": 6,
    "kind": "unrun-verify",
    "phase": "02",
    "file": ".planning/phases/02-source-conversion/02-CONTEXT.md",
    "line": null,
    "description": "Plan 02-10 human check 4: confirm open questions Q-1 (sales invoice download screen name) and Q-2 with the user (Q-3 is decided in CONTEXT)",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-11-02T19:37:10.397Z",
    "resolved_at": null,
    "milestone": null
  },
  {
    "id": 7,
    "kind": "unrun-verify",
    "phase": "02",
    "file": ".gitignore",
    "line": null,
    "description": "Plan 02-10 human check 5 on the user's PC: after conversion and the three reports, git status shows no 입력/ or 수집/ file (and no WEHAGO xlsx)",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-11-02T19:37:10.610Z",
    "resolved_at": null,
    "milestone": null
  }
]
````
