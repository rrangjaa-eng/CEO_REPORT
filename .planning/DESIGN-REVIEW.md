# Design review: reports and approval screen

Date: 2026-11-02 · Method: gstack `/design-review` checklist (10 categories), run as a worker with recommended options picked automatically.
Branch: `claude/project-thread-jkflss` (main tree, not pushed).

The review used only the synthetic sample: `입력양식/샘플`, the fake snapshot from `tests/test_approval.py::write_fake_snapshot` and the fake WEHAGO books from `tests/test_wehago.py::write_fake_books`. Pages were rendered in headless Chromium (Playwright) at 1280px and 390px, full page, and printed to A4 PDF.

Caveat: the container has no Malgun Gothic, so pages rendered in WenQuanYi Zen Hei. Glyph widths in Malgun are close but not identical, so the widths and print fit still need one check in Edge on the user's PC. This adds to item 2 in `.planning/WINDOWS.md`.

## Who reads what

| Page | Reader | Main question the first screen must answer |
|---|---|---|
| 대표 보고 (weekly, monthly) | CEO, facts only | How much cash is there, and how low will it go? Which projects are over budget? |
| 경영관리 보고 | Finance/management | The same numbers as the CEO edition, plus what is at risk and the fix for each |
| 지급 승인 검토 | Finance, all week and especially Thursday before the 14:00 batch | If I approve these requests, what is the lowest balance in the next 8 weeks, is any week short, and what does each request change? |

## Scores (0–10)

| Dimension | Reports before | Reports after | Approval before | Approval after | What would make it 10 |
|---|---|---|---|---|---|
| Information structure (first screen answers the main question) | 5 | 8 | 8 | 8.5 | Reports: draw the 최소 보유현금 line and mark the lowest point on the chart. Approval: when only some requests are checked, also show the 전부 승인 baseline (needs a product decision). |
| Visual hierarchy | 6 | 7.5 | 7 | 7.5 | Fewer equal-weight muted lines under the approval headline. Group 일정 반영 기준, 확인 필요 항목 and 계산 기준 under one disclosure that is open by default (nothing hidden on print). |
| Components (tables, cards, notes, status labels) | 4 | 7.5 | 5 | 7.5 | A visible fade at the edge of tables that scroll sideways. One chip style shared by the report `.st` labels and the approval `.lv` and `.xs` labels. |
| Interaction (toggle, sticky headline, recompute feedback) | 7 | 7 | 7 | 8.5 | Reports: a back-to-top link after each section. Approval: show, next to the headline, which week the low falls in and link to that row of 주별 일정. |
| Korean typography | 3 | 8 | 3 | 8 | Check in Malgun Gothic on Windows. Use `text-wrap:balance` on h1 and h2. Stop the 3-line wrap of the narrow 이번 주 지급 header in the first-screen table. |
| Number formatting and alignment | 7 | 8 | 7 | 8 | Already tabular-nums and right-aligned. The remaining gap is that unknown-count notes in numeric cells wrap under the number instead of sitting in their own column. |
| Print (A4 via Edge) | 4 | 8 | 6 | 8 | Repeat the table header row on page breaks. Print the chip text at body size. Add a running footer with the 기준일 and the page number. |
| Phone width (390px) | 3 | 7 | 2 | 7 | Approval: a card per request on phones in place of an 11-column table that scrolls sideways. Reports: the chart text grows on small screens. |
| Accessibility (contrast, focus, labels) | 6 | 7.5 | 7 | 8 | Contrast already passes AA: sub text 5.96:1, warn 5.93:1, green 4.99:1. Remaining: a `<caption>` or `aria-label` on each data table, `scope` on header cells, and a text alternative for the chart that lists its values. |
| **Overall** | **5** | **7.5** | **5.5** | **8** | |

There are no AI-slop patterns: no gradients, no decorative icons, no centred marketing layout, no stacks of cards. The font stack is the platform Korean UI font, which is right for an offline internal document. Goodwill on the Thursday approval flow went from about 55 to 75. It lost points for the clipped columns and the 200px phone rows. It gains points because the headline answers the question at once, the screen recomputes as soon as a box changes, and the result is stated in words.

## Findings before fixes (by impact)

**High**
1. **Report first screen hid a column (on screen and in print).** The 9-column project table was 886px wide inside a 666px column. 예상 잔여예산 was cut off, and that column holds the over-budget figures (−28.2, −53.0). In print the column was simply missing.
2. **Korean text broke between single letters.** With no `word-break:keep-all`, 기획1팀 stacked as 기/획/1/팀, and the total row note took 6 lines. This affected every table on all pages.
3. **The report's main answer was buried.** The lowest calculated balance (19.8 백만원 on 2027-04-25, below 최소 보유현금 100.0) appeared only as a dotted key-value row under the chart. It was not in the KPI row, and nothing set it apart.
4. **The approval request table overflowed at 1280px when WEHAGO books were loaded.** It was 1149px wide in a 1140px box, so the 이 건 빼면·넣으면 column was clipped, and 근거 규칙 stacked one word per line. The existing width test did not catch this because it runs without books.
5. **The approval screen was unusable at 390px.** 11 columns were squeezed into the phone width, so each row was about 200px tall and mostly empty.
6. **The report's first page spilled onto a second A4 page** by one row of cards, which left a nearly empty page 2.

**Medium**
7. On phones, report detail tables broke dates at the hyphen (2026-/11-03/~/…), rows grew past 100px, and the monthly 경영관리 page was 17,900px tall.
8. The approval headline's safe state (부족·최소보유현금 미만 주 없음) was plain text, and nothing marked the recomputed value. Someone scrolled down the list saw no feedback when the number changed.
9. The 전부 체크 and 전부 해제 buttons and the sticky elements were also printed.
10. Focus used the browser's default 1px auto ring.

**Polish**
11. Captions on the approval WEHAGO tables were centred, unlike every other scope line.
12. The header of the sticky checkbox column had a white background on a grey header row.

## What was fixed (one commit each, test first where behaviour is involved)

| Commit | Fix | Test |
|---|---|---|
| `fix(design): first-screen project table no longer clips its last column` | `word-break:keep-all` and `overflow-wrap:break-word` on body. Headers and numeric notes in the first-screen table wrap at spaces. | `TestReportFirstScreenLayout` (table fits at 1280px for all 4 editions; no row over 80px) |
| `fix(design): lowest calculated balance gets its own card in the first KPI row` | A fifth KPI card shows 최저 계산 잔액 (확정 일정만): the existing `s2["min"]["firm"]` value, its date, the text label 최소 보유현금 X 미만 or 이상 (부족 below 0), and the unknown-count notes. Colour only repeats the label. If the start balance is unknown the card says 잔액 미확인. On phones the card comes first and spans the full width. Both editions show it, so CEO and 경영관리 numbers still match. | `TestLowestBalanceCard`; the KPI count in `test_report.py` goes from 4 to 5 (a presentation-only assertion) |
| `fix(design): approval request table fits at 1280 and stays readable on phones` | Headers and the 인트라넷 요청·차액 note wrap. Text columns get minimum widths and dates stay on one line. On phones the table has a 1040px minimum and scrolls sideways under the sticky checkbox column. | `TestApprovalTableWithBooks` (fits at 1280px with books; rows under 130px at 390px; no page-level horizontal scroll) |
| `style(design): A4 print keeps the first screen on one page and hides screen-only controls` | Tighter print spacing. `break-inside:avoid` on KPI cards and cards. Links print as text. The approval page prints without its buttons and with nothing sticky. | Checked visually in A4 PDFs (before and after paths below) |
| `style(design): approval headline shows the safe state and flashes the recomputed low` | `#headline.lv-ok` turns the existing safe-state text green and bold. `#h-low` gets a 0.7s highlight when its value changes, switched off under `prefers-reduced-motion`. A 2px accent `:focus-visible` ring on both page types. | `TestApprovalHeadlineFeedback` |
| `style(design): table captions on the approval screen align left like every other scope line` | `caption{text-align:left}` in the muted note style | none (CSS only) |
| `fix(design): report tables scroll sideways on phones instead of stacking dates` | Below 820px, data tables size to their content inside the existing `.tw` scroll box. The risk table (sentences) and the approval request table keep wrapping. | `TestReportPhoneTables` (no row over 80px at 390px; no page-level horizontal scroll) |

No computed number and no numeric string asserted by a test changed. No information was removed: the original 최저 계산 잔액 rows under the chart are still there. Pages remain offline, with no fonts or CDNs, and the Python side uses only the 3.8 standard library. Suite: 491 tests before, 502 after, all passing.

Page heights at 390px went from 19,370 to 12,035 (weekly CEO), 17,885 to 13,002 (monthly 경영관리) and 5,936 to 4,864 (approval).

## Left as is, and why

- **Chart reference line and lowest-point marker.** This adds a new visual encoding to the CEO chart. It is worth doing, but it is a product decision because it touches the facts-only CEO page. It is the next step toward 10 for information structure.
- **Card layout for approval requests on phones.** This is a larger restructure of the screen and its JS (`tr.closest`, row classes). Thursday approval happens on a desktop, and the phone view is now readable with sideways scrolling.
- **Collapsing the approval explanation blocks into `<details>`.** The brief says never remove information. Even a disclosure that is open by default changes what prints, so this needs the user's preference.
- **Showing the 전부 승인 baseline in a partly checked headline.** This needs a second computed value in the headline. That is a behaviour and product change, not styling.
- **The 3-line 이번 주 지급 header and edge fades on scrolling tables.** Low impact polish.
- **Checking in Malgun Gothic and Edge on the user's PC.** This cannot be done in this container. The check belongs with WINDOWS.md item 2.

## Screenshots

Before and after captures are in the session scratchpad, which is outside the repo:
`/tmp/claude-0/-home-user-CEO-REPORT/8bd5f933-589b-59f6-ab79-e1826aa1edc1/scratchpad/design/{before,after}/`. For each page there is `<page>-1280.png`, `<page>-390.png`, `<page>-1280-fold.png`, `<page>-390-fold.png`, `<page>.pdf` and `pdf-<page>-NN.png`. Pages are `w-ceo`, `w-mgmt`, `m-ceo`, `m-mgmt` and `approval`. Captures of the approval flow are `flow-focus.png` and `flow-scrolled.png`. To regenerate, run `gen.sh <dir>` and then `node shot.js <dir> <out>` in the same folder.
