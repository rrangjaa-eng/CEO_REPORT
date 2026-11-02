---
schema_version: 1
open_count: 2
waived_count: 0
fixed_count: 0
total_count: 2
last_updated: 2026-11-02T10:40:15.142Z
---

# Broken Windows Ledger

> Cross-phase defect register. With `workflow.windows_enforce` enabled, `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 01.1 | unrun-verify | 실행_승인검토.bat |  | Plan 01.1-03 human checks 1-7 (구조 점검, double-click timing, toggles, D-17 dates, --수집 안함, git status, findstr) pending on the user's Windows PC | open |  | 2026-11-02T10:25:34.514Z |  |
| 2 | 01.1 | unrun-verify | ceo_report/approval_render.py |  | 01.1-04 human check on the user's PC: open 출력/승인검토_*.html in Edge, untick/re-tick one request, unplug network; narrow to phone width and check sticky headline and checkbox column | open |  | 2026-11-02T10:40:15.142Z |  |

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
  }
]
````
