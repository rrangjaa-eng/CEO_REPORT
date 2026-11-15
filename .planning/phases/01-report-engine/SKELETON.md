# Walking Skeleton — CEO_REPORT (대표 주간·월간 보고 프로그램)

**Phase:** 1
**Generated:** 2026-11-02
**Status:** Skeleton already exists and runs (1차 code, commit 4d59073). This document records it as the contract later phases build on. Phase 1 does NOT scaffold a new skeleton; plans 01-01 and 01-02 harden it.

## Capability Proven End-to-End

A user runs one command and gets this week's 대표용 and 경영관리용 reports, computed from the CSV files in `입력/`, written as HTML (and PDF when Edge/Chrome is present) to the output folder.

Proof command (run from the repository root, verified 2026-11-02, exit 0, two files written):

    python3 보고서.py 주간 --기준일 2026-11-02 --출력 <any-temp-dir> --pdf 안함

Expected output files: `2026-11-02_주간_대표보고.html`, `2026-11-02_주간_경영관리보고.html`.
With `--pdf` omitted (default `만듦`) and a Chromium-family browser present, `2026-11-02_주간_대표보고.pdf` and `2026-11-02_주간_경영관리보고.pdf` are also written (verified here with /usr/bin/google-chrome, about 7 s).

Regression proof: `python3 -m unittest discover -s tests` (28 tests at phase start, all passing). `tests/test_report.py::TestChecksAndOutput.test_cli_writes_files` runs the command above as a subprocess.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Language / runtime | Python 3.8+ standard library only (no pip installs) | D-15: runs from the user's external drive on Windows with no install burden |
| Input ("storage read") | 12 CSV files in `입력/`, schema = `ceo_report.data.SCHEMA` (required columns per file); UTF-8 (BOM ok) or CP949; blank cell = unknown (None), never 0 | CSV-in decision (PROJECT.md Key Decisions); D-02 |
| Input validation | `ceo_report.util.Issues` collects (파일, 줄, 내용) tuples; shown in report section 7 "입력 자료 확인 필요"; missing files reported, never a crash | D-12, DATA-03 |
| Calculation | One pure pass `ceo_report.calc.compute(d, kind, asof, start)` → dict `R` with `s1`..`s7`, `events`, `risks`; both editions read the same `R` | D-13: numbers computed once, shared by both editions |
| Presentation | `ceo_report.render.render(R, mode)` with `mode` = `"ceo"` or `"mgmt"`; self-contained HTML (inline CSS, inline SVG chart, no JS, no external assets); `mgmt` only adds the risk section | D-13, D-14 one-page first screen + 상세 1~7 |
| HTML safety | Every CSV-derived string passes through `ceo_report.util.esc` (html.escape) or `_na`/`W`/`M` helpers | Local CSV text must not inject markup into the report |
| Output ("storage write") | `보고서.py` writes `<기준일>_<주간|월간>_<대표보고|경영관리보고>.html` (+ `.pdf`) into `--출력` (default `출력/`, git-ignored) | REP-03; reports contain company finances and stay out of git |
| PDF | Edge/Chrome headless `--print-to-pdf` via `subprocess.run` with a fixed argument list (no shell), 120 s timeout | D-15: no PDF library |
| Auth / secrets | None. No credentials are read, stored, or needed; WEHAGO login stays in the user's own browser (Phase 2) | PROJECT.md Constraints (보안) |
| Entry point ("routing") | CLI `보고서.py {주간,월간,weekly,monthly} [--기준일] [--시작일] [--입력] [--출력] [--pdf 만듦/안함]`; Windows launchers `실행_주간.bat` / `실행_월간.bat` added in plan 01-02 (R5) | REP-01: one command or one double-click |
| Deployment target | Local run from the repo folder. Phase 3 copies program + outputs to `F:\CLAUDE\CEO_REPORT` and uploads outputs to Google Drive | Deployment is Phase 3 (DEP-01..03), not this phase |
| Tests | `unittest`; `tests/test_report.py`; `setUpModule` regenerates the sample via `tools/make_sample.py`; probes copy `입력/` to a temp dir and change one cell | Existing convention, kept (CONTEXT Claude's Discretion) |
| Directory layout | `ceo_report/{util,data,calc,render}.py`, `보고서.py` (CLI), `tools/make_sample.py`, `tests/test_report.py`, `입력/` (sample data), `입력양식/` (blank templates), `출력/` (git-ignored) | Flat, stdlib-only package; no build step |

## Stack Touched in Phase 1

- [x] Project scaffold: package `ceo_report/`, CLI `보고서.py`, unittest runner (exists)
- [x] Routing: CLI sub-commands `주간` / `월간` (exists; launchers added in 01-02)
- [x] Data read: 12 CSVs via `data.load` (exists; 01-01 adds blank-balance and settings parsing hardening)
- [x] Data write: HTML + PDF report files via `보고서.py` (exists; 01-02 removes a stale PDF before printing)
- [n/a] Interactive UI wired to an API: the product is a static HTML report; there is no server or API in this project
- [x] Deployment: documented local run command above; real deployment is Phase 3

## Out of Scope (Deferred to Later Slices)

- WEHAGO Excel and intranet jsonl → input CSV converters (Phase 2, SRC-01/02)
- Copy to `F:\CLAUDE\CEO_REPORT`, Google Drive upload, GitHub PR (Phase 3, DEP-01..03)
- Automatic collection from WEHAGO or banks (v2 AUTO-01; user decision: CSV input only)
- Interpretation or recommendation wording in the 대표용 edition (user decision; permanently excluded)
- Storing any account credentials (security constraint; permanently excluded)

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without changing the decisions above:

- Phase 2: the user exports from WEHAGO and the intranet archive, runs a converter, and gets the same `입력/` CSVs this skeleton already reads (sums reconcile with the source)
- Phase 3: the user double-clicks a launcher on `F:\CLAUDE\CEO_REPORT` and finds the HTML/PDF in Google Drive; code lives in the GitHub CEO_REPORT repository
