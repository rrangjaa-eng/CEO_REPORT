---
schema_version: 1
open_count: 1
waived_count: 0
fixed_count: 0
total_count: 1
last_updated: 2026-11-02T10:25:34.514Z
---

# Broken Windows Ledger

> Cross-phase defect register. With `workflow.windows_enforce` enabled, `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 01.1 | unrun-verify | 실행_승인검토.bat |  | Plan 01.1-03 human checks 1-7 (구조 점검, double-click timing, toggles, D-17 dates, --수집 안함, git status, findstr) pending on the user's Windows PC | open |  | 2026-11-02T10:25:34.514Z |  |

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
  }
]
````
