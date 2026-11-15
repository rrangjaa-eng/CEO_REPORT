# Phase 1: 보고 엔진 검증 - Pattern Map

**Mapped:** 2026-11-02
**Files analyzed:** 7 (6 modified, 2 new .bat counted as 1 group)
**Analogs found:** 6 / 7 (the .bat files have no in-repo analog)

All analogs are git-tracked (verified via `git ls-files`). No external deps; stdlib only. The whole phase is self-analogous: every fix copies a pattern that already exists in the same file.

## File Classification

| File | Role | Data Flow | Closest Analog | Match |
|------|------|-----------|----------------|-------|
| `ceo_report/calc.py` (R1 :47/:73, R2 :322, R3 :239, R4 :136/:406-410) | service (compute) | transform | same file: `ssum` + `bal_unknown`/`restr_unknown` (:46-47), `g["unknown"]` (:310-313) | exact |
| `ceo_report/render.py` (R1/R3 first screen, R4 :572, DR1, DR2) | view (HTML) | transform | same file: `restr_note` + `_kpi` (:187-198), `scope` line (:204) | exact |
| `ceo_report/util.py` (R4: tolerant setting parsers) | utility | transform | `util.num` (:60-80) | exact |
| `ceo_report/data.py` (R1/R4 input-check items, if needed) | model/loader | file-I/O | `_check` (:44-47) + `num(..., issues, row, col)` | exact |
| `보고서.py` (only if CLI messaging changes) | CLI entry | request-response | itself | exact |
| `tests/test_report.py` | test | request-response | `TestSchedule`/`TestChecksAndOutput` + `test_missing_file_reported_not_crash` (:181-188) | exact |
| `실행_주간.bat`, `실행_월간.bat` (R5) | config/launcher | request-response | none in repo | no analog |

## Pattern Assignments

### R1 `ceo_report/calc.py` ~L46-47, L73 (blank balance counted as zero / hidden)

Finding: `ssum` already returns the unknown count and it is already stored (`bal_unknown`, `restr_unknown`) but never rendered. `start_bank` at :72 also discards the count (`start_bank, _ =`). Fix is mostly render-side plus propagating the count to s2/s7.

**Existing pattern (calc.py:46-47, 73-78):**
```python
total_bal, bal_unknown = ssum(a["balance"] for a in accounts)
restricted, restr_unknown = ssum(a["restricted"] for a in accounts)
...
"accounts": accounts, "total": total_bal, "bal_unknown": bal_unknown, "restricted": restricted,
"restr_unknown": restr_unknown, "available": total_bal - restricted, ...
```
Do: keep summing confirmed only (D-02). Add the list of unknown-balance accounts (names) to `R["s1"]` (e.g. `bal_unknown_names`) and add an entry to `d.issues` / `R["s7"]["issues"]` using the `Issues.add(file, line, msg)` shape (calc.py:335):
```python
d.issues.add(s["row"]["_file"], s["row"]["_line"], "...")   # tuple (파일, 줄, 내용)
```
Expose `bal_unknown` as `R["s2"]["start_unknown"]` (s2 start = `R["s1"]["available"]`, calc.py:249).

### R1/DR3 `ceo_report/render.py` first screen KPI (L187-193)

**Copy this sub-line pattern** (restr_unknown suffix):
```python
restr_note = "사용제한 %s" % man(s1["restricted"])
if s1["restr_unknown"]:
    restr_note += " · 제한금액 미확인 %d계좌" % s1["restr_unknown"]
...
h.append(_kpi("현재 현금 (계좌 합계)", M(s1["total"]), "%d개 계좌 · 은행 기준일 %s" % (len(s1["accounts"]), _bank_dates(s1))))
```
Add same style suffix `" · 잔액 미확인 %d계좌 (합계 제외)"` to the 현재 현금 sub-line and to the 사용 가능액 note; repeat in `_s1` table 1 and `_s2` start-balance line (see `h.append("<h3 ...시작: 사용 가능액 %s)" % man(s2["start"]))`, render.py:224). Sub-line text is passed through `esc`-less `%` into `_kpi` third arg, so wrap with `esc(...)` as done for `restr_note` at :194 usage.
Wording must stay factual (ceo mode forbids 위험/해결방안/권고/우려/추천).

### R2 `calc.py` ~L316-331 (vendor unpaid `s["amount"] or 0`)

**Analog in same block (calc.py:310-313)** counts unknowns per group:
```python
if s["amount"] is None:
    g["unknown"] += 1
else:
    g["total"] += s["amount"]
```
Apply to `vendors`: init `{"total": 0, "next": None, "n": 0, "unknown": 0}`; for schedule rows use the if/else above instead of `or 0`; for exec rows (:333-337) count unknown when both `supply` and `vat` are None (`ssum`-style). Render the `unknown` count in the 6번 vendor table with `_na("미확인 N건")`-style (render `W`/`M` at render.py:62-70 use `_na`).

### R3 `calc.py` ~L226-245 (past-due pending excluded from first screen)

**Existing bucketing (calc.py:231-245):** events with `date <= asof` go to `past`, `date is None` to `undated`. `past` is already collected; it is simply not shown on the first screen. Do not add `past` to buckets or `min` (D-04, R3). Expose `R["s2"]["past_in"]`/`["past_out"]` totals+counts (split by `ev["io"] == "in"/"out"`, using `ssum` if amounts nullable; `amount_unknown` events are already separate).
Render: add line next to the 4주 KPIs / schedule summary using the `kv`/`_na` helpers and the "표시 N건 / 전체 N건" style text of render.py:204-205. Label as fact: "예정일 지난 미처리 입금 N건 금액 / 지급 N건 금액 (일정·최저잔액 미포함)". DR4 = same.

### R4 `calc.py` L136, L406-410; `render.py` L572; `util.py` (int()/float() on settings)

**Analog:** `util.num` — tolerant of commas/원/blank, returns None, reports via Issues (util.py:60-80):
```python
def num(value, issues=None, row=None, col=""):
    ...
    s = str(value).strip().replace(",", "").replace("원", "").replace(" ", "")
    if s in ("", "-", "미확인", "N/A", "n/a"): return None
    ...
    if not _NUM_RE.match(s):
        if issues is not None and row is not None:
            issues.add(row["_file"], row["_line"], "%s 값이 숫자가 아님: '%s' (미확인으로 처리)" % (col, value))
        return None
    ... return int(round(v))
```
Add to util.py a helper like `setting_num(settings, key, default, issues=None)` that calls `num()` (float-capable for 예산초과율; note `num` returns rounded int, so for `위험_예산초과율` add a float path or accept int), returns `default` on None, and appends to Issues (file `설정.csv`, line "-" as used by `read_csv`: `issues.add(name, "-", msg)`). Replace the offending call sites:
```python
n_show = int(d.settings.get("첫화면_프로젝트_표시수", "10") or 10)      # calc.py:136
min_cash = int(st.get("위험_최소보유현금", "0") or 0)                   # calc.py:406
over_pct = float(st.get("위험_예산초과율", "100") or 100)               # calc.py:410
won(int(R["settings"].get("위험_최소보유현금", 0) or 0))                # render.py:572
```
Gotcha: `risks(R)` has only `R["settings"]`, not `d.issues`; parse once in `compute` (where `d.issues` is available, before `R["s7"]["issues"]` is built at calc.py:370) and store parsed values in `R["settings_num"]`, so render.py:572 reuses them (D-13: compute once). Note `or 0` treats a valid `0` as default 0 (fine) but `or 10` would turn `0` into 10; preserve with `None` check.

### DR1 / DR2 `render.py`
DR1: KPI values come from `M()` (백만원, `man()` util.py:107). Add unit text in `_kpi` label/value (e.g. label suffix "(백만원)") - change only `_kpi` call labels at :190-198. Meta line already says "첫 화면은 백만원"; numbers test (`test_same_numbers_in_both_versions`) extracts digits, so keep identical in both modes.
DR2: bottom card "프로젝트 밖 지급예정" at render.py ~:235-243 uses `kv([...])`; add "(등록분 전체)" to the label and `"날짜 없음 %d건"` using existing `R["s7"]["undated_out_n"]` (calc.py:422 shows it is present).

### `tests/test_report.py` (TDD: failing test first)

**Fixture pattern** (L27-33): `Base.setUpClass` loads `입력/` sample and computes `cls.R`. Probe-input pattern for single-cell changes (L181-188) copies to a temp dir, mutates, `load` -> `compute` -> `render`, asserts on `R["s7"]["issues"]`, then `shutil.rmtree`:
```python
tmp = tempfile.mkdtemp()
shutil.copy(os.path.join(SAMPLE, "프로젝트.csv"), tmp)
d = load(tmp); R = compute(d, "weekly", ASOF); render(R, "ceo")
self.assertTrue(any("파일 없음" in m for _, _, m in R["s7"]["issues"]))
shutil.rmtree(tmp)
```
For R1 probe: `shutil.copytree(SAMPLE, tmp)` then rewrite one 잔액 cell in `계좌잔액.csv` (read with `read_csv`/csv module, write utf-8-sig). Assert `R["s1"]["bal_unknown"] == 1`, `"잔액 미확인 1계좌" in render(R,"ceo")`, total excludes it. R4 probe: set `위험_최소보유현금` to `50,000,000` in 설정.csv, assert compute/render do not raise and (if invalid, e.g. `abc`) an issue appears. R3: assert `"예정일 지난 미처리"` in ceo html and that `events`/`min` unchanged. Keep existing guards green: `test_ceo_has_no_interpretation` (forbidden words) and `test_same_numbers_in_both_versions`; `test_all_reconciliations_match` iterates `R["s7"]["checks"]` tuples `(항목, 값A, 값B, 일치)`. Run: `python3 -m unittest discover -s tests`.
CLI test pattern for R5 (optional, static): `subprocess.run([sys.executable, os.path.join(ROOT, "보고서.py"), "주간", "--기준일", "2026-11-02", "--출력", out, "--pdf", "안함"], capture_output=True, text=True)` (L190-197). A .bat cannot be run on Linux; test only that the files exist and contain `chcp 65001` and `보고서.py 주간|월간`.

### `실행_주간.bat`, `실행_월간.bat` (R5) - no analog
Use 보고서.py CLI contract (docstring L1-11 and `BROWSERS`/`find_browser` L26-40): `python 보고서.py 주간|월간 [--기준일] [--입력 입력] [--출력 출력] [--pdf 안함]`. Plan: `@echo off`, `chcp 65001 >nul`, `cd /d "%~dp0"`, check `where python >nul 2>&1` else print Korean install guidance and `pause`, then `python 보고서.py 주간` (월간 in the other file; omit --기준일 to default to today), `pause`. Use CRLF line endings and no BOM; keep text ASCII or UTF-8 with chcp 65001 set before any Korean echo. Also check `.gitignore` does not exclude `*.bat` or `출력`.

## Shared Patterns

### Unknown = None, never 0 (D-02)
**Source:** `ceo_report/util.py:96-105` (`ssum`) and `render.py:62-70` (`W`/`M` use `_na`).
```python
def ssum(values):
    total, unknown = 0, 0
    for v in values:
        if v is None: unknown += 1
        else: total += v
    return total, unknown
```
Apply to R1, R2, R3: every new total must carry its unknown count and render "미확인 N건" next to it. Spots that still sum with `or 0`: calc.py:322, 333. Also `calc.py:128-129` `sum(P[k] ...)` totals and `tot["remain"]` skip None silently - leave unless touched.

### Input-issue reporting (7번 "입력 자료 확인 필요")
**Source:** `util.Issues.add(file, line, msg)` (util.py:14-19); surfaced as `R["s7"]["issues"]` (calc.py:370) and `len(s7["issues"])` on first screen (render.py:248). Any new "cannot parse / unconfirmed" condition (R1 unknown balance accounts, R4 bad setting) goes here. Tests read it as `for _, _, m in R["s7"]["issues"]`.

### One calculation, two versions (D-13)
**Source:** `render(R, mode)` render.py:~172-262 branches only on `mode == "mgmt"` for the risk section. New numbers/labels must be computed in `calc.compute` and rendered identically in both modes; wording in ceo mode must avoid 위험, 해결방안, 권고, 우려, 추천 (test_report.py:160-163).

### Fact-label wording style
Existing: `"제한금액 미확인 %d계좌"`, `"표시 %d건 / 전체 %d건"`, `M(P["budget"], "예산 미지정")`, `"판단 불가"`. Reuse this noun-phrase style (no interpretation).

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `실행_주간.bat`, `실행_월간.bat` | launcher | request-response | No batch/shell launchers in repo (`scripts/*.sh` are GSD installers, unrelated); use RESEARCH-less spec in D-15/R5 above |

## Metadata

**Analog search scope:** `ceo_report/`, `보고서.py`, `tests/`, `tools/`, `scripts/`
**Files scanned:** 8 (tracked sources; `.claude/` and `입력/` data skipped)
**Line numbers** verified against current HEAD; calc.py:73 in CONTEXT refers to the `available` entry of the `R["s1"]` dict.
**Pattern extraction date:** 2026-11-02
