// convert_projects.py: 프로젝트.csv · 프로젝트집행.csv
import { PRIOR_TAG, SCHEMA } from "../model/data";
import type { IsoDate } from "../model/dates";
import { daysBetween } from "../model/dates";
import { cmpStr, pyG, pyIsDigit, pyRound, pyStrip, sortedBy, type SortKey } from "../model/py";
import { isBlank, num, parseDate, won } from "../model/util";
import { normVendor } from "../model/vendor";
import type { Cfg } from "./config";
import { APPROVAL_STAGES, lineKeys, type LineKey, type LinkLine, type LinkResult, type Projects } from "./linking";
import { OLD_LAST_DAY, OLD_STATE } from "./snapshot";
import { cellAmount, check, Table, type Check, type TRow } from "./table";
import { journalFromStart, squash, type Books, type JLine, type Match, type Request } from "./wehago";

export const PROJECT_EXTRA = ["실행가", "견적금액", "승인단계"];
const CARRIED = ["상태", "예산수정일", "계약금액", "완료일"];
const DATE_MAX = "9999-12-31";

export const cellDate = (d: IsoDate | null | undefined): string => (d === null || d === undefined ? "" : d);

function digits(text: string | null | undefined): string {
  return [...(text || "")].filter((ch) => /\p{Nd}/u.test(ch)).join("");
}

function sumOrNone(values: Iterable<number | null | undefined>): number | null {
  let total = 0;
  for (const v of values) {
    if (v === null || v === undefined) return null;
    total += v;
  }
  return total;
}

const s = (v: unknown): string => (v === null || v === undefined ? "" : String(v));

function carryCell(column: string, raw: unknown, key: string, notes: string[]): string {
  const text = pyStrip(s(raw));
  if (column === "상태") return text;
  if (isBlank(text)) return "";
  if (column === "계약금액") {
    const value = num(text);
    if (value === null) { notes.push(`${key} 계약금액 이전 값 '${text}' 숫자 아님 → 빈칸`); return ""; }
    return cellAmount(value);
  }
  const day = parseDate(text);
  if (day === null) { notes.push(`${key} ${column} 이전 값 '${text}' 날짜 아님 → 빈칸`); return ""; }
  return cellDate(day);
}

export const CARRY_LABEL = "이전 프로젝트.csv에만 있는 프로젝트 → 옮긴 줄";
const AMOUNT_COLUMNS = ["사전견적예산", "계약금액", "매출반영누계", "실행가", "견적금액"];

function prevOnly(prevRows: TRow[], keys: string[]): Map<string, TRow[]> {
  const keyDigits = new Set(keys.map(digits));
  const out = new Map<string, TRow[]>();
  for (const r of prevRows) {
    const key = pyStrip(s(r["프로젝트번호"]));
    if (key && !keyDigits.has(digits(key))) {
      if (!out.has(key)) out.set(key, []);
      out.get(key)!.push(r);
    }
  }
  return out;
}

function carryCheck(prevRows: TRow[], keys: string[], rows: TRow[]): Check {
  const only = prevOnly(prevRows, keys);
  const written = rows.filter((r) => only.has(pyStrip(s(r["프로젝트번호"])))).length;
  return check(CARRY_LABEL, only.size, written);
}

function carriedProject(columns: string[], old: TRow, key: string, notes: string[]): TRow {
  const row: TRow = {};
  for (const column of columns) {
    const raw = pyStrip(s(old[column]));
    if (CARRIED.includes(column)) row[column] = carryCell(column, raw, key, notes);
    else if (AMOUNT_COLUMNS.includes(column)) {
      const value = num(raw);
      if (raw && value === null) notes.push(`${key} ${column} 이전 값 '${raw}' 숫자 아님 → 빈칸`);
      row[column] = raw ? cellAmount(value) : "";
    } else row[column] = raw;
  }
  row["프로젝트번호"] = key;
  return row;
}

export const PERIOD_LABEL = "분개장 시작 전 이력이 있는 프로젝트 → 매출반영누계 판단 불가 (빈칸)";

export function journalSpan(books: Books): [IsoDate | null, IsoDate | null] {
  let first: IsoDate | null = null, last: IsoDate | null = null;
  for (const ln of books.journal) {
    if (ln.date === null) continue;
    if (first === null || ln.date < first) first = ln.date;
    if (last === null || ln.date > last) last = ln.date;
  }
  return [first, last];
}

export function periodText(books: Books): string {
  const [first, last] = journalSpan(books);
  return first ? `${first}~${last}` : "";
}

/** out_of_period */
export function outOfPeriod(books: Books, projects: Projects, requests: Request[]): Map<string, string> {
  const [start] = journalSpan(books);
  const out = new Map<string, string>();
  if (start === null) return out;
  for (const [key, p] of projects) {
    const why: string[] = [];
    if (p.event_date !== null && p.event_date < start) why.push(`행사일 ${p.event_date}`);
    const early = requests.filter((rq) => rq.code === key && rq.registered !== null && rq.registered.slice(0, 10) < start)
      .map((rq) => (rq.registered as string).slice(0, 10)).sort(cmpStr);
    if (early.length) why.push(`지급요청 등록 ${early[0]}`);
    if (why.length) out.set(key, `분개장 시작 ${start} 전 ${why.join(" · ")}`);
  }
  return out;
}

function periodCheck(history: Map<string, string>, rows: TRow[]): Check {
  const marked = rows.filter((r) => history.has(pyStrip(s(r["프로젝트번호"]))) && isBlank(r["매출반영누계"])).length;
  return check(PERIOD_LABEL, history.size, marked);
}

/** build_projects */
export function buildProjects(projects: Projects, revenue: LinkResult, prevRows: TRow[], history: Map<string, string> | null = null,
  period = ""): Table {
  const notes: string[] = [];
  const byDigits = new Map<string, TRow[]>();
  for (const r of prevRows) {
    const d = digits(s(r["프로젝트번호"]));
    if (!byDigits.has(d)) byDigits.set(d, []);
    byDigits.get(d)!.push(r);
  }
  byDigits.delete("");
  const keys = [...projects.keys()];
  const amounts = new Map<string, (number | null)[]>();
  const linkedElsewhere: (number | null)[] = [], unlinkedAmounts: (number | null)[] = [];
  for (const ln of revenue.lines) {
    if (ln.project === null) unlinkedAmounts.push(ln.amount);
    else if (projects.has(ln.project)) {
      if (!amounts.has(ln.project)) amounts.set(ln.project, []);
      amounts.get(ln.project)!.push(ln.amount);
    } else linkedElsewhere.push(ln.amount);
  }
  const rows: TRow[] = [];
  const periodTotal = new Map<string, number | null>();
  let oldDone = 0;
  for (const key of keys) {
    const p = projects.get(key)!;
    if (p.dup) notes.push(`프로젝트번호 ${key} 겹침 → 첫 줄만`);
    const row: TRow = { "프로젝트번호": key, "프로젝트명": p.name, "팀": p.team, "클라이언트": p.client };
    for (const [column, field, text] of [["사전견적예산", "estimate", "estimate_text"], ["실행가", "budget", "budget_text"]] as const) {
      row[column] = cellAmount(p[field]);
      if (p[field] === null && !isBlank(p[text])) notes.push(`${key} ${field === "estimate" ? "사전견적" : "실행가"} 숫자 아님 → 빈칸`);
    }
    row["견적금액"] = cellAmount(p.quote);
    row["승인단계"] = p.approval || "";
    row["행사일"] = p.event_text !== null && p.event_text !== undefined ? p.event_text : cellDate(p.event_date);
    const total = sumOrNone(amounts.get(key) ?? []);
    periodTotal.set(key, total);
    row["매출반영누계"] = history && history.has(key) ? "" : cellAmount(total);
    const same = digits(key) ? byDigits.get(digits(key)) ?? [] : [];
    const old: TRow = same.length === 1 ? same[0]! : {};
    if (same.length > 1) {
      notes.push(`이전 프로젝트.csv에 ${key}와 숫자가 같은 프로젝트번호가 여러 줄 (${same.map((x) => s(x["프로젝트번호"] ?? "")).join(", ")}) → 상태·예산수정일·계약금액·완료일 옮기지 않음`);
    }
    for (const column of CARRIED) row[column] = carryCell(column, old[column], key, notes);
    if (p.old && ["", "완료", OLD_STATE].includes(row["상태"] as string) && (p.event_date === null || p.event_date <= OLD_LAST_DAY)) {
      row["상태"] = OLD_STATE;
      oldDone++;
    }
    rows.push(row);
  }
  const snapRows = [...rows];
  const nOld = keys.filter((k) => projects.get(k)!.old).length;
  if (nOld) {
    notes.push(`예전 인트라넷 프로젝트 ${nOld}건 더함 (지금 인트라넷에 없는 번호) · 그중 ${OLD_LAST_DAY} 이전 행사 ${oldDone}건은 상태 '완료(예전 인트라넷)' — 보고서 표·미발행에서 뺌`);
  }
  const stages = keys.filter((k) => !projects.get(k)!.old).map((k) => projects.get(k)!.approval || "");
  if (stages.some((x) => x)) {
    const cnt = (x: string) => stages.filter((y) => y === x).length;
    notes.push(`인트라넷 승인 단계: ${APPROVAL_STAGES.map((st) => `${st}까지 ${cnt(st)}건`).join(" · ")} · 승인 전 ${cnt("")}건 — 대표이사 승인 끝난 프로젝트는 종결로 봄 (남은 예산 지급 예정에서 뺌, 매출 예상은 견적금액 기준)`);
  }
  const columns = [...SCHEMA["프로젝트.csv"]!, ...PROJECT_EXTRA];
  const onlyPrev = prevOnly(prevRows, keys);
  const order = sortedBy([...onlyPrev.keys()], (k) => [digits(k) === "", Number(digits(k) || 0), k]);
  for (const key of order) {
    const olds = onlyPrev.get(key)!;
    if (olds.length > 1) notes.push(`이전 프로젝트.csv에 ${key} 줄이 여러 줄 → 첫 줄만 옮김`);
    rows.push(carriedProject(columns, olds[0]!, key, notes));
  }
  if (onlyPrev.size) notes.push(`이전 프로젝트.csv에만 있는 프로젝트 ${onlyPrev.size}건 → 옮김 (스냅숏에 없음, 이전 줄 그대로): ${order.join(", ")}`);

  const checks: Check[] = [check("프로젝트 수 (스냅숏 → CSV)", keys.length, snapRows.length)];
  for (const [column, field, label] of [["사전견적예산", "estimate", "사전견적"], ["실행가", "budget", "실행가"]] as const) {
    const source = keys.map((k) => projects.get(k)![field]);
    const cells = snapRows.map((r) => num(r[column]));
    checks.push(check(`${label} 합계 (빈칸 제외)`, source.reduce<number>((a, v) => a + (v ?? 0), 0), cells.reduce<number>((a, v) => a + (v ?? 0), 0)));
    checks.push(check(`${label} 빈칸`, source.filter((v) => v === null).length, snapRows.filter((c) => c[column] === "").length));
  }
  const csvTotal = sumOrNone([...snapRows.map((r) => (!(history && history.has(r["프로젝트번호"] as string)) ? num(r["매출반영누계"])
    : periodTotal.get(r["프로젝트번호"] as string) ?? null)), ...linkedElsewhere, ...unlinkedAmounts]);
  const sourceTotal = sumOrNone(revenue.lines.map((ln) => ln.amount));
  checks.push(check("매출 줄 합계 = 매출반영누계 합계 + 미연결 매출", sourceTotal, csvTotal));
  checks.push(carryCheck(prevRows, keys, rows));
  if (history !== null) checks.push(periodCheck(history, rows));
  if (period) notes.push(`매출반영누계는 분개장 기간 ${period} 합계 (그 앞의 매출은 모름)`);
  if (history && history.size) {
    notes.push(`매출반영누계 판단 불가 (기간 밖) ${history.size}건 — 0이 아니라 빈칸으로 둠: ${[...history].map(([k, v]) => `${k} (${v})`).join("; ")}`);
  }
  return new Table("프로젝트.csv", columns, rows, { checks, notes });
}

// ───────────── 프로젝트집행.csv: WEHAGO 원가 줄 ─────────────
const codeSet = (values: string[]) => new Set(values.map((v) => squash(v)));
const slipOf = (keys: LineKey[], i: number) => keys[i]![0] + "\u0000" + keys[i]![1];

function isOpening(row: JLine): boolean {
  const memo = squash(row.memo);
  return memo.includes("전기이월") || memo.includes("기초잔액");
}

function linePart(row: JLine, field: "debit" | "credit"): number | null {
  if (row.debit === null && row.credit === null) return null;
  return row[field] || 0;
}

interface Pay { idx: number; date: IsoDate; amount: number; left: number; used: boolean }
interface Item { idx: number | null; date: IsoDate | null; amount: number; remaining: number; applied: number; done: Pay | null }

export interface Group {
  day: IsoDate | null; no: string; vendor_norm: string; project: string; lines: LinkLine[]; vat: number | null; kind: string;
  request: string | null; prior: boolean; old_code: string; supply: number | null; basis: string; card: boolean; card_pay: boolean;
  paid_day: IsoDate | null; firm: boolean; state: string; item: string; vendor_text: string; supply_cell: string; vat_cell: string;
}

function groupCostLines(costs: LinkResult): Map<string, Group> {
  const groups = new Map<string, Group>();
  for (const ln of costs.lines) {
    const prior = !!ln.prior;
    const old = ln.code || ln.slip_code || "";
    const project = prior ? "" : (ln.project || ln.code || "");
    const gkey = [ln.key[0], ln.key[1], ln.vendor_norm, project, prior ? "1" : "0"].join("\u0000");
    let g = groups.get(gkey);
    if (g === undefined) {
      g = { day: ln.date, no: ln.no, vendor_norm: ln.vendor_norm, project, lines: [], vat: 0, kind: "wehago", request: null, prior,
        old_code: prior ? old : "", supply: null, basis: "", card: false, card_pay: false, paid_day: null, firm: false, state: "",
        item: "", vendor_text: "", supply_cell: "", vat_cell: "" };
      groups.set(gkey, g);
    }
    g.lines.push(ln);
  }
  for (const g of groups.values()) {
    const amounts = g.lines.map((ln) => ln.amount);
    g.supply = amounts.some((a) => a === null) ? null : amounts.reduce<number>((a, v) => a + (v as number), 0);
    const linked = new Set(g.lines.filter((ln) => ln.basis === "자동" && ln.request).map((ln) => ln.request as string));
    g.request = linked.size === 1 ? [...linked][0]! : null;
  }
  return groups;
}

const gSlip = (g: Group) => (g.day ?? "") + "\u0000" + g.no;

function placeVat(groups: Map<string, Group>, books: Books, keys: LineKey[], vatCodes: Set<string>): [number | null, [string, string, string, number | null][]] {
  const slips = new Set([...groups.values()].map(gSlip));
  const sums = new Map<string, [string, string, number | null]>();   // 열쇠 → [전표, 거래처, 금액]
  books.journal.forEach((row, i) => {
    if (!vatCodes.has(squash(row.account_code)) || !slips.has(slipOf(keys, i))) return;
    const slip = slipOf(keys, i), vn = row.vendor_norm || "";
    const k = slip + "\u0001" + vn;
    const part = linePart(row, "debit");
    const prev = sums.has(k) ? sums.get(k)![2] : 0;
    sums.set(k, [slip, vn, part === null || prev === null ? null : prev + part]);
  });
  const unplaced: [string, string, string, number | null][] = [];
  const gl = [...groups.values()];
  for (const [slip, vendorNorm, amount] of sums.values()) {
    const mine = gl.filter((g) => gSlip(g) === slip && g.vendor_norm === vendorNorm);
    if (!mine.length) {
      const sameSlip = gl.filter((g) => gSlip(g) === slip);
      if (sameSlip.length === 1) {
        const g = sameSlip[0]!;
        g.vat = amount === null || g.vat === null ? null : g.vat + amount;
        continue;
      }
      const [d, n] = slip.split("\u0000") as [string, string];
      unplaced.push([d, n, vendorNorm, amount]);
      continue;
    }
    let target = mine[0]!;
    for (const g of mine.slice(1)) {
      if (g.supply !== null && (target.supply === null || g.supply > target.supply)) target = g;
    }
    target.vat = amount === null || target.vat === null ? null : target.vat + amount;
  }
  return [sumOrNone([...sums.values()].map((x) => x[2])), unplaced];
}

function settle(books: Books, keys: LineKey[], payableCodes: Set<string>): [Map<number, Item>, number | null, number, string, string[]] {
  const notes: string[] = [];
  const ref = books.book_date;
  const byVendor = new Map<string, { items: Item[]; pays: Pay[]; open: number[] }>();
  let openingAny = false;
  books.journal.forEach((row, i) => {
    if (!payableCodes.has(squash(row.account_code))) return;
    const vn = row.vendor_norm || "";
    if (!byVendor.has(vn)) byVendor.set(vn, { items: [], pays: [], open: [] });
    const v = byVendor.get(vn)!;
    if (isOpening(row)) { openingAny = true; v.open.push(i); return; }
    const credit = row.credit, debit = row.debit;
    if (credit !== null && credit > 0) v.items.push({ idx: i, date: row.date, amount: credit, remaining: credit, applied: 0, done: null });
    if (debit !== null && debit > 0) {
      if (row.date === null) notes.push(`날짜 없는 미지급금 차변 줄 (전표 ${keys[i]![1]}, ${won(debit)}원)은 지급으로 보지 않음`);
      else if (ref === null || row.date <= ref) v.pays.push({ idx: i, date: row.date, amount: debit, left: debit, used: false });
    }
  });
  let unknownPay = false;
  for (const row of books.journal) {
    if (payableCodes.has(squash(row.account_code)) && !isOpening(row) && row.debit === null && row.credit === null
      && (ref === null || row.date === null || row.date <= ref)) unknownPay = true;
  }
  const fifo = openingAny || (books.journal.length > 0 && journalFromStart(books.journal));
  const itemsByIdx = new Map<number, Item>();
  const leftovers: number[] = [];
  let payTotal = 0;
  for (const v of byVendor.values()) {
    if (v.open.length) {
      const netv = v.open.reduce((a, i) => a + ((books.journal[i]!.credit || 0) - (books.journal[i]!.debit || 0)), 0);
      if (netv > 0) {
        const days = v.open.map((i) => books.journal[i]!.date).filter((d): d is string => d !== null).sort(cmpStr);
        v.items.push({ idx: null, date: days.length ? days[0]! : null, amount: netv, remaining: netv, applied: 0, done: null });
      }
    }
    v.items = sortedBy(v.items, (it) => [it.date ?? DATE_MAX, it.idx === null ? -1 : it.idx]);
    v.pays = sortedBy(v.pays, (p) => [p.date, p.idx]);
    for (const it of v.items) {
      if (it.date === null) continue;
      for (const p of v.pays) {
        if (!p.used && p.amount === it.amount && p.date >= it.date) {
          p.used = true; p.left = 0;
          it.remaining = 0; it.applied = it.amount; it.done = p;
          break;
        }
      }
    }
    if (fifo) {
      for (const p of v.pays) {
        if (p.used) continue;
        for (const it of v.items) {
          if (p.left <= 0) break;
          if (it.remaining <= 0 || it.date === null || it.date > p.date) continue;
          const take = Math.min(p.left, it.remaining);
          it.remaining -= take; it.applied += take; p.left -= take;
          if (it.remaining === 0) it.done = p;
        }
      }
      for (const p of v.pays) {
        if (p.left <= 0) continue;
        for (const it of v.items) {
          if (p.left <= 0) break;
          if (it.remaining <= 0 || it.date === null || it.date <= p.date) continue;
          const take = Math.min(p.left, it.remaining);
          it.remaining -= take; it.applied += take; p.left -= take;
          if (it.remaining === 0) it.done = { ...p, date: it.date };
        }
      }
    }
    for (const p of v.pays) {
      payTotal += p.amount;
      if (p.left > 0) leftovers.push(p.left);
    }
    for (const it of v.items) if (it.idx !== null) itemsByIdx.set(it.idx, it);
  }
  let allocated = 0;
  for (const v of byVendor.values()) for (const it of v.items) allocated += it.applied;
  const left = leftovers.reduce((a, b) => a + b, 0);
  const note = `미배분 지급 ${leftovers.length}건 ${won(left)}`;
  return [itemsByIdx, unknownPay ? null : payTotal, allocated + left, note, notes];
}

const CARD_NO = /^[^\s_]+_\d{4}$/u;

function noOrder(no: string): SortKey {
  return pyIsDigit(no) ? [0, Number(no), ""] : [1, 0, no];
}

function rowOrder(g: Group): SortKey {
  return [g.day ?? DATE_MAX, noOrder(g.no), g.lines[0]!.vendor];
}

function wehagoRows(books: Books, costs: LinkResult, cfg: Cfg): [Group[], Check[], string[]] {
  const keys = lineKeys(books.journal);
  const payable = codeSet(cfg.payable_codes), cash = codeSet(cfg.cash_codes), vat = codeSet(cfg.vat_codes);
  const groups = groupCostLines(costs);
  const [vatSource, unplaced] = placeVat(groups, books, keys, vat);
  const [items, paySource, payCsv, leftoverNote, notes] = settle(books, keys, payable);
  notes.push(leftoverNote);
  const slips = new Map<string, number[]>();
  for (let i = 0; i < books.journal.length; i++) {
    const k = slipOf(keys, i);
    if (!slips.has(k)) slips.set(k, []);
    slips.get(k)!.push(i);
  }
  const words = cfg.card_words;
  let mixed = 0;
  const J = books.journal;
  for (const g of groups.values()) {
    const idxs = slips.get(gSlip(g)) ?? [];
    const cashPaid = idxs.some((i) => cash.has(squash(J[i]!.account_code)) && (J[i]!.credit || 0) > 0);
    const payIdx = idxs.filter((i) => payable.has(squash(J[i]!.account_code)) && (J[i]!.credit || 0) > 0 && !isOpening(J[i]!));
    const base = `WEHAGO ${g.day ?? "날짜 없음"} 전표 ${g.no}`;
    g.basis = base; g.card = false; g.card_pay = false; g.paid_day = null; g.firm = false;
    if (cashPaid && !payIdx.length) { g.state = "지급완료"; g.paid_day = g.day; g.firm = true; continue; }
    if (!payIdx.length) {
      g.state = "요청미지급";
      g.basis = base + " · 지급 여부 확인 불가 (현금·미지급 대변 없음)";
      continue;
    }
    const sameV = payIdx.filter((i) => J[i]!.vendor_norm === g.vendor_norm);
    const same = sameV.length ? sameV : payIdx;
    let pick = same[0]!;
    for (const i of same.slice(1)) {
      const a = J[i]!.credit as number, b = J[pick]!.credit as number;
      if (a > b) pick = i;   // (credit, -i) 최대: 같으면 앞 줄
    }
    const payVendor = pyStrip(J[pick]!.vendor || "");
    g.card = words.some((w) => w && payVendor.includes(w)) || CARD_NO.test(payVendor);
    g.card_pay = g.card;
    const it = items.get(pick);
    if (it !== undefined && it.remaining === 0 && it.done !== null) {
      g.state = g.card ? "카드결제완료" : "지급완료";
      g.paid_day = it.done.date; g.firm = true;
      g.basis = base + ` · 지급 ${it.done.date} 전표 ${keys[it.done.idx]![1]}`;
      continue;
    }
    g.state = g.card ? "카드사용미결제" : "요청미지급";
    g.firm = g.card;
    let extra = "";
    if (it !== undefined && it.applied > 0) extra = ` · 일부 지급 ${won(it.applied)}`;
    if (cashPaid) { mixed++; extra += " · 현금·미지급 대변 함께 있음"; }
    g.basis = base + extra;
  }
  for (const g of groups.values()) {
    if (g.prior) g.basis += " · " + PRIOR_TAG + (g.old_code ? ` [${g.old_code}]` : "");
  }
  if (mixed) notes.push(`현금·미지급 대변이 함께 있는 전표의 원가 줄 ${mixed}건 → 지급 전(요청미지급)으로 둠 (일부 현금 지급일 수 있음)`);
  for (const [day, no, vendorNorm, amount] of unplaced) {
    notes.push(`부가세대급금 ${won(amount)}원 (전표 ${no} ${day || "날짜 없음"}, 거래처 ${vendorNorm || "(거래처 없음)"})은 같은 거래처의 원가 줄이 없어 부가세에 넣지 못함`);
  }
  const ordered = sortedBy([...groups.values()], rowOrder);
  for (const g of ordered) {
    const first = g.lines[0]!;
    g.item = first.memo || first.account;
    g.vendor_text = first.vendor;
    g.supply_cell = cellAmount(g.supply);
    g.vat_cell = cellAmount(g.vat);
  }
  const costSource = sumOrNone(costs.lines.map((ln) => ln.amount));
  const checks = [
    check("원가 줄 합계 ((도) 차변−대변)", costSource, sumOrNone(ordered.map((g) => g.supply))),
    check("원가 전표 부가세대급금", vatSource, sumOrNone(ordered.map((g) => g.vat))),
    check("원가 줄 수", costs.lines.length, ordered.reduce((a, g) => a + g.lines.length, 0)),
    check("미지급 지급 줄 배분", paySource, paySource !== null ? payCsv : null),
  ];
  return [ordered, checks, notes];
}

function rowOf(g: Group): TRow {
  return { "프로젝트번호": g.project, "항목": g.item, "거래처": g.vendor_text, "상태": g.state, "공급가액": g.supply_cell,
    "부가세": g.vat_cell, "일자": cellDate(g.paid_day), "확정여부": g.firm ? "확정" : "추정", "근거": g.basis };
}

// ───────────── 아직 장부에 없는 지급요청 (D-42, D-50) ─────────────
const groupTotal = (g: Group) => (g.supply === null || g.vat === null ? null : g.supply + g.vat);

function escRe(t: string): string {
  return t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function names(text: string | null | undefined, number: string): boolean {
  return new RegExp(`지급요청 ${escRe(number)}(?!\\p{Nd})`, "u").test(text || "");
}

function noKey(n: string): SortKey {
  return pyIsDigit(n) ? [0, Number(n), n] : [1, 0, n];
}

export function statusLabel(rq: Request): string {
  return `상태 확인 필요 (${rq.status_text || "빈칸"})`;
}

function tag(rq: Request): string {
  return rq.status !== "approved" && rq.status !== "pending" ? " " + statusLabel(rq) : "";
}

/** split_vat */
export function splitVat(amount: number | null): [number | null, number | null] {
  if (amount === null) return [null, null];
  const a = Math.abs(Math.trunc(amount)) * 10;
  const q = Math.floor(a / 11), r = a % 11;
  let supply = q + (r * 2 >= 11 ? 1 : 0);
  supply = amount >= 0 ? supply : -supply;
  return [supply, Math.trunc(amount) - supply];
}

export const WITHHOLDING_GROSS_UP = true;
const ROUND = 1000;
const WITHHOLDING = [0.033, 0.088];
const PAID_STATES = ["지급완료", "카드결제완료"];

function netOf(gross: number, rate: number): number {
  const national = Math.floor(Math.trunc(gross * (rate === 0.033 ? 0.03 : 0.08)) / 10) * 10;
  return gross - national - Math.floor(Math.floor(national / 10) / 10) * 10;
}

/** withholding_gross */
export function withholdingGross(amount: number | null): [number, number] | null {
  if (amount === null || amount <= 0) return null;
  if (amount % 11 === 0 && (Math.floor(amount / 11) * 10) % ROUND === 0) return null;
  const found: [number, number][] = [];
  for (const rate of WITHHOLDING) {
    const gross = Math.trunc(pyRound(amount / (1 - rate) / ROUND)) * ROUND;
    if (gross > 0 && Math.trunc(gross * (rate === 0.033 ? 0.03 : 0.08)) >= 1000 && Math.abs(netOf(gross, rate) - amount) <= 10) found.push([gross, rate]);
  }
  return found.length === 1 ? found[0]! : null;
}

function requestRow(rq: Request, amount: number | null, basis: string, gross: number | null = null): TRow {
  const [supply, vat] = gross === null ? splitVat(amount) : [gross, 0];
  return { "프로젝트번호": rq.code || "", "항목": rq.name, "거래처": rq.vendor, "상태": "요청미지급", "공급가액": cellAmount(supply),
    "부가세": cellAmount(vat), "일자": cellDate(rq.date), "확정여부": rq.status === "approved" ? "확정" : "추정", "근거": basis };
}

const CEO_APPROVED = ["수락완료", "승인"], CEO_PENDING = ["미승인", "수락요청중"];
export function isNewCeoValue(text: string | null | undefined): boolean {
  const t = pyStrip(text || "");
  return !!t && !CEO_APPROVED.includes(t) && !CEO_PENDING.includes(t);
}

type Entry = [SortKey, number, TRow];
interface Part {
  annotated: number; added: number; paid: number; skipped: number; paid_nos: string[]; skipped_nos: string[];
  invoice: Map<string, number | null>; covered: Map<string, number>; excess: Map<string, number>; grossed: Map<string, number>;
  entries: Entry[]; notes: string[]; active: Request[]; groups: Group[]; new_values: Request[];
}

function bookMatch(rq: Request, g: Group): boolean {
  const total = groupTotal(g), amount = rq.amount;
  if (total === null || amount === null) return false;
  if (total === amount) return true;
  return g.vat === 0 && WITHHOLDING.some((r) => Math.abs(Math.trunc(pyRound((g.supply as number) * (1 - r))) - amount) <= 10);
}

function pairWithBooks(toAdd: [Request, boolean, number | null][], groups: Group[], taken: Set<Group>,
  linked: Map<string, Group[]>): [Map<string, Group>, string[]] {
  const out = new Map<string, Group>();
  const ambiguous: string[] = [];
  const byProject = new Map<string, Group[]>();
  for (const g of groups) {
    if (taken.has(g) || !g.project || g.request || (g.basis || "").includes("지급요청")) continue;
    if (!byProject.has(g.project)) byProject.set(g.project, []);
    byProject.get(g.project)!.push(g);
  }
  const used = new Set<Group>();
  const order = (rq: Request): SortKey => [rq.registered === null, rq.registered ?? "", noKey(rq["번호"])];
  for (const [rq] of sortedBy(toAdd, (t) => order(t[0]))) {
    if (rq.amount === null || !rq.code || (linked.get(rq["번호"]) ?? []).length) continue;
    const reg = rq.registered ? rq.registered.slice(0, 10) : null;
    const cands: [boolean, number, SortKey, Group][] = [];
    for (const g of byProject.get(rq.code) ?? []) {
      if (used.has(g) || !bookMatch(rq, g)) continue;
      if (PAID_STATES.includes(g.state)) {
        const day = g.paid_day || g.day;
        if (rq.status !== "approved" || reg === null || day === null || day < reg) continue;
      } else if (g.state !== "요청미지급" && g.state !== "카드사용미결제") continue;
      const day = g.paid_day || g.day || DATE_MAX;
      cands.push([g.vendor_norm !== normVendor(rq.vendor), reg && day !== DATE_MAX ? Math.abs(daysBetween(reg, day)) : 0, rowOrder(g), g]);
    }
    if (cands.length) {
      const g = sortedBy(cands, (c) => [c[0], c[1], c[2]])[0]![3];
      used.add(g);
      out.set(rq["번호"], g);
      if (cands.length > 1) ambiguous.push(rq["번호"]);
    }
  }
  return [out, ambiguous];
}

function linkedTotal(mine: Group[]): number | null {
  return mine.length === 1 ? groupTotal(mine[0]!) : null;
}

function requestsPart(groups: Group[], requests: Request[], match: Match): Part {
  const notes: string[] = [];
  const newValues = requests.filter((rq) => isNewCeoValue(rq.status_text));
  if (newValues.length) {
    notes.push(`처음 보는 사장님승인 글자 ${newValues.length}건 → 프로젝트집행에 넣지 않음 (규칙 안전-07, 화면 확인 필요): ${sortedBy(newValues, (r) => noKey(r["번호"])).map((rq) => `${rq["번호"]} '${rq.status_text}'`).join(", ")}`);
  }
  const active = requests.filter((rq) => !isNewCeoValue(rq.status_text));
  const unknown = active.filter((rq) => rq.status !== "approved" && rq.status !== "pending");
  if (unknown.length) {
    notes.push(`상태 확인 필요 ${unknown.length}건 → 요청미지급(추정)으로 넣음 (D-52: 사장님승인이 빈칸이거나 알 수 없는 값)`);
    notes.push("상태 확인 필요 지급요청: " + sortedBy(unknown, (r) => noKey(r["번호"]))
      .map((rq) => `${rq["번호"]} ${rq.vendor} ${won(rq.amount, "금액 미확인")} (${rq.status_text || "빈칸"})`).join(", "));
  }
  const rowsOf = match.rows ?? {};
  const fallback = { status: "판단 불가", invoice_total: null as number | null, label: undefined as string | undefined };
  const get = (no: string) => (Object.prototype.hasOwnProperty.call(rowsOf, no) ? rowsOf[no]! : fallback);
  const candidates = new Map<string, Group[]>(), viaLink = new Map<string, boolean>();
  const claims = new Map<Group, number>();
  const linked = new Map<string, Group[]>();
  for (const g of groups) {
    if (g.request) {
      if (!linked.has(g.request)) linked.set(g.request, []);
      linked.get(g.request)!.push(g);
    }
  }
  for (const rq of active) {
    const m = get(rq["번호"]);
    let found: Group[] = [];
    const mine = linked.get(rq["번호"]) ?? [];
    if (mine.length === 1 && rq.amount !== null && groupTotal(mine[0]!) !== null) {
      found = mine;
      viaLink.set(rq["번호"], true);
    } else if ((m.status === "계산서 있음" || m.status === "금액 차이") && rq.amount !== null && m.invoice_total !== null && m.invoice_total !== undefined) {
      found = groups.filter((g) => g.vendor_norm === normVendor(rq.vendor) && g.project === (rq.code || "") && groupTotal(g) === m.invoice_total);
    }
    candidates.set(rq["번호"], found);
    for (const g of found) claims.set(g, (claims.get(g) ?? 0) + 1);
  }
  const unpaidByVendor = new Map<string, number>();
  for (const g of groups) if (g.state === "요청미지급" || g.state === "카드사용미결제") unpaidByVendor.set(g.vendor_norm, (unpaidByVendor.get(g.vendor_norm) ?? 0) + 1);
  const entries: Entry[] = [];
  const st: Part = { annotated: 0, added: 0, paid: 0, skipped: 0, paid_nos: [], skipped_nos: [], invoice: new Map(), covered: new Map(),
    excess: new Map(), grossed: new Map(), entries, notes, active, groups, new_values: newValues };
  const taken = new Set<Group>();
  const toAdd: [Request, boolean, number | null][] = [];
  for (const rq of sortedBy(active, (r) => noKey(r["번호"]))) {
    const no = rq["번호"];
    const m = get(no);
    const status = m.status;
    let invoice: number | null = m.invoice_total ?? null;
    if (status === "이미 지급") {
      st.paid++; st.paid_nos.push(no);
      notes.push(`지급요청 ${no}: ${m.label ?? "이미 지급"} → 넣지 않음`);
      continue;
    }
    const found = candidates.get(no)!;
    const hasInvoice = status === "계산서 있음" || status === "금액 차이";
    if (hasInvoice && rq.amount === null) notes.push(`지급요청 ${no} 금액 미확인 → 차액 판단 불가`);
    if ((hasInvoice || viaLink.get(no)) && found.length === 1 && claims.get(found[0]!) === 1) {
      const g = found[0]!;
      invoice = groupTotal(g) as number;
      const amt = rq.amount as number;
      taken.add(g);
      if (g.state === "요청미지급") {
        g.basis += ` · 지급요청 ${no}${tag(rq)}`;
        g.paid_day = rq.date;
        g.firm = rq.status === "approved";
        st.annotated++;
        st.invoice.set(no, invoice);
        st.covered.set(no, Math.min(amt, invoice));
        if (amt > invoice) {
          st.excess.set(no, amt - invoice);
          entries.push([noKey(no), 1, requestRow(rq, amt - invoice, `지급요청 ${no} 차액 (인트라넷 요청 ${won(amt)} − 계산서 ${won(invoice)})`)]);
        }
        continue;
      }
      if (PAID_STATES.includes(g.state)) {
        g.basis += ` · 지급요청 ${no}${tag(rq)}`;
        st.skipped++; st.skipped_nos.push(no);
        st.invoice.set(no, invoice);
        st.covered.set(no, Math.min(amt, invoice));
        if (amt > invoice) {
          st.excess.set(no, amt - invoice);
          const row = requestRow(rq, amt - invoice, `지급요청 ${no} 차액 (인트라넷 요청 ${won(amt)} − 계산서 ${won(invoice)}, 계산서는 이미 지급)`);
          row["확정여부"] = "추정";
          entries.push([noKey(no), 1, row]);
          notes.push(`지급요청 ${no}: 계산서의 원가 줄이 이미 지급완료 → 요청 금액이 계산서보다 큰 차액 ${won(amt - invoice)}원만 요청미지급(추정)으로 넣음 (확인 필요)`);
        } else notes.push(`지급요청 ${no}: 계산서의 원가 줄이 이미 지급완료 → 요청 줄 넣지 않음 (원가 줄에 번호 표시)`);
        continue;
      }
    }
    if ((hasInvoice || viaLink.get(no)) && found.length === 1) taken.add(found[0]!);
    toAdd.push([rq, hasInvoice, invoice]);
  }
  const [paired, ambiguous] = pairWithBooks(toAdd, groups, taken, linked);
  for (const [rq, hasInvoice, inv0] of toAdd) {
    let invoice = inv0;
    const no = rq["번호"];
    const g = paired.get(no);
    if (g !== undefined) {
      const total = groupTotal(g) as number;
      const how = total === rq.amount ? "프로젝트·금액" : "프로젝트·원천세 뗀 금액";
      g.basis += ` · 지급요청 ${no}${tag(rq)} (${how}으로 짝지음)`;
      st.invoice.set(no, total);
      st.covered.set(no, Math.min(rq.amount as number, total));
      if (g.state === "요청미지급") {
        g.paid_day = rq.date;
        g.firm = rq.status === "approved";
        st.annotated++;
      } else { st.skipped++; st.skipped_nos.push(no); }
      continue;
    }
    st.added++;
    if (!hasInvoice) invoice = linkedTotal(linked.get(no) ?? []);
    if (rq.amount !== null && invoice !== null) st.invoice.set(no, invoice);
    const wh = WITHHOLDING_GROSS_UP && invoice === null ? withholdingGross(rq.amount) : null;
    if (wh) {
      st.grossed.set(no, wh[0] - (rq.amount as number));
      entries.push([noKey(no), 0, requestRow(rq, rq.amount,
        `지급요청 ${no}${tag(rq)} (인트라넷 금액 ${won(rq.amount)}은 원천세 ${pyG(wh[1] * 100)}% 뗀 금액으로 보아 떼기 전 금액 추정, 부가세 없음)`, wh[0])]);
    } else {
      entries.push([noKey(no), 0, requestRow(rq, rq.amount, `지급요청 ${no}${tag(rq)} (인트라넷 금액, 부가세 포함으로 나눔)`)]);
    }
    if (rq.amount !== null && invoice !== null && invoice > rq.amount) {
      entries.push([noKey(no), 1, requestRow(rq, invoice - rq.amount, `지급요청 ${no} 차액 (계산서 ${won(invoice)} − 인트라넷 요청 ${won(rq.amount)})`)]);
    }
    if (hasInvoice) notes.push(`지급요청 ${no}: 계산서 있음이나 원가 줄을 하나로 정하지 못함 → 요청으로 넣음 (중복 가능)`);
    else if ((linked.get(no) ?? []).length) notes.push(`지급요청 ${no}: 자동 연결된 원가 줄을 하나로 정하지 못하거나 합계를 몰라 요청으로 넣음 (중복 가능)`);
    else if (unpaidByVendor.get(normVendor(rq.vendor))) {
      notes.push(`중복 가능: 지급요청 ${no} — 같은 거래처의 미지급 원가 줄 ${unpaidByVendor.get(normVendor(rq.vendor))}건`);
    }
  }
  if (paired.size) {
    const kinds = new Map<string, number>();
    for (const g of paired.values()) {
      const k = PAID_STATES.includes(g.state) ? "지급 끝난 줄" : "미지급 줄";
      kinds.set(k, (kinds.get(k) ?? 0) + 1);
    }
    notes.push(`장부 원가 줄과 프로젝트·금액으로 짝지은 지급요청 ${paired.size}건 → 요청 줄 넣지 않음 (${sortedBy([...kinds], (kv) => [kv[0], kv[1]]).map(([k, v]) => `${k} ${v}건`).join(" · ")}, 원가 줄 근거에 번호 표시)`);
  }
  if (ambiguous.length) {
    notes.push(`[확인] 지급요청 짝짓기: 같은 프로젝트·금액 원가 줄이 둘 이상이라 등록 순서로 짝지은 요청 ${ambiguous.length}건 (합계는 같음, 어느 줄인지만 확인): ${sortedBy(ambiguous, noKey).join(", ")}`);
  }
  const sorted = sortedBy(entries, (e) => [e[0], e[1]]);
  entries.length = 0;
  entries.push(...sorted);
  return st;
}

const REQUEST_ROW = /^지급요청 (\p{Nd}+)(?!\p{Nd}| 차액)/u;
const EXCESS_ROW = /^지급요청 (\p{Nd}+) 차액 \(인트라넷 요청/u;

function amountCheck(known: Request[], part: Part, rows: TRow[]): Check {
  const byNo = new Map(known.map((rq) => [rq["번호"], rq]));
  let covered = 0;
  for (const n of byNo.keys()) covered += part.covered.get(n) ?? 0;
  let paidAmount = 0;
  for (const n of part.paid_nos) if (byNo.has(n)) paidAmount += byNo.get(n)!.amount as number;
  let rowAmount = 0;
  for (const r of rows) {
    const text = s(r["근거"]);
    const excess = EXCESS_ROW.exec(text), request = REQUEST_ROW.exec(text);
    if ((excess && byNo.has(excess[1]!)) || (request && byNo.has(request[1]!))) {
      rowAmount += (num(r["공급가액"]) || 0) + (num(r["부가세"]) || 0);
      if (request && !excess) rowAmount -= part.grossed.get(request[1]!) ?? 0;
    }
  }
  const kinds = known.some((rq) => rq.status !== "approved" && rq.status !== "pending") ? "승인·대기·상태 확인 필요" : "승인·대기";
  return check(`지급요청 금액 (금액 있는 ${kinds} ${known.length}건) = 원가 줄 표시 + 요청 줄 + 이미 지급`,
    known.reduce((a, rq) => a + (rq.amount as number), 0), covered + rowAmount + paidAmount);
}

export const D50_LABEL = "계산서·요청 금액이 다르면 큰 쪽: 지급요청을 가리키는 줄 합계 = max(계산서, 요청)";
export const BASIS_LABEL = "지급요청마다 일정 근거 하나: 근거가 있는 지급요청 수 = 근거(원가 줄·요청 줄) 수";

function d50Check(active: Request[], match: Match, groups: Group[], rows: TRow[]): Check {
  const rowsOf = match.rows ?? {};
  const linked = new Map<string, Group[]>();
  for (const g of groups) {
    if (g.request) {
      if (!linked.has(g.request)) linked.set(g.request, []);
      linked.get(g.request)!.push(g);
    }
  }
  let want = 0, got = 0;
  for (const rq of active) {
    const no = rq["번호"];
    const m = Object.prototype.hasOwnProperty.call(rowsOf, no) ? rowsOf[no]! : null;
    if (rq.amount === null || m?.status === "이미 지급") continue;
    let wa = linkedTotal(linked.get(no) ?? []);
    if (wa === null && (m?.status === "계산서 있음" || m?.status === "금액 차이")) wa = m.invoice_total ?? null;
    if (wa === null) continue;
    want += Math.max(wa, rq.amount);
    for (const r of rows) if (names(s(r["근거"]), no)) got += (num(r["공급가액"]) || 0) + (num(r["부가세"]) || 0);
  }
  return check(D50_LABEL, want, got);
}

function requestChecks(part: Part, rows: TRow[], match: Match): Check[] {
  const active = part.active;
  const requestRows = part.entries.filter((e) => e[1] === 0).map((e) => e[2]);
  const known = active.filter((rq) => rq.amount !== null);
  const csvCount = part.annotated + part.added + part.paid + part.skipped;
  const unknown = active.filter((rq) => rq.status !== "approved" && rq.status !== "pending").length;
  let label = `지급요청 건수: 승인·대기 ${active.length - unknown}${unknown ? ` + 상태 확인 필요 ${unknown}` : ""} = 원가 줄에 표시 ${part.annotated} + 요청 줄 ${part.added} + 이미 지급 ${part.paid}`;
  if (part.skipped) label += ` + 이미 지급된 원가 줄 ${part.skipped}`;
  if (part.new_values.length) label += ` (처음 보는 사장님승인 글자 ${part.new_values.length}건은 넣지 않음, 안전-07)`;
  return [
    check(label, active.length, csvCount),
    amountCheck(known, part, rows),
    check("지급요청 금액 미확인", active.length - known.length, requestRows.filter((r) => r["공급가액"] === "").length),
    d50Check(active, match, part.groups, rows),
  ];
}

function allMatches(re: RegExp, text: string): string[] {
  const out: string[] = [];
  for (const m of text.matchAll(re)) out.push(m[1]!);
  return out;
}

function basisCheck(groups: Group[], requestRows: TRow[]): Check {
  const bases = new Map<string, number>();
  const add = (no: string) => bases.set(no, (bases.get(no) ?? 0) + 1);
  for (const g of groups) {
    const nos = new Set(g.lines.filter((ln) => ln.basis === "자동" && ln.request).map((ln) => ln.request as string));
    for (const n of allMatches(/지급요청 (\p{Nd}+)/gu, g.basis || "")) nos.add(n);
    for (const no of nos) add(no);
  }
  for (const r of requestRows) for (const no of new Set(allMatches(/지급요청 (\p{Nd}+)/gu, s(r["근거"])))) add(no);
  let total = 0;
  for (const v of bases.values()) total += v;
  return check(BASIS_LABEL, bases.size, total);
}

export const HAND_LABEL = "이전 프로젝트집행.csv 손으로 넣은 미지급 줄 → 옮긴 줄";
export const OVERLAP_LABEL = "손으로 넣은 미지급 줄 중 새로 만든 줄과 겹치는 줄 (같은 거래처·금액 또는 같은 지급요청)";
const UNPAID = ["요청미지급", "카드사용미결제"];

export function isHandUnpaid(row: TRow): boolean {
  const basis = pyStrip(s(row["근거"]));
  return UNPAID.includes(pyStrip(s(row["상태"]))) && !(basis.startsWith("WEHAGO ") || basis.startsWith("지급요청"));
}

function rowTotal(row: TRow): number | null {
  const supply = num(row["공급가액"]);
  return supply === null ? null : supply + (num(row["부가세"]) || 0);
}

function overlaps(hand: TRow[], made: TRow[]): [TRow, TRow[]][] {
  const out: [TRow, TRow[]][] = [];
  for (const h of hand) {
    const vendor = normVendor(s(h["거래처"])), total = rowTotal(h);
    const nos = new Set(allMatches(/지급요청 (\p{Nd}+)/gu, s(h["근거"])));
    const hits: TRow[] = [];
    for (const g of made) {
      const same = vendor && total !== null && normVendor(s(g["거래처"])) === vendor && rowTotal(g) === total;
      if (same || allMatches(/지급요청 (\p{Nd}+)/gu, s(g["근거"])).some((n) => nos.has(n))) hits.push(g);
    }
    if (hits.length) out.push([h, hits]);
  }
  return out;
}

function carryPlanRows(prevRows: TRow[], keyPool: string[]): [TRow[], TRow[], TRow[], string[]] {
  const byDigits = new Map<string, string[]>();
  for (const k of keyPool) {
    const d = digits(k);
    if (d) {
      if (!byDigits.has(d)) byDigits.set(d, []);
      byDigits.get(d)!.push(k);
    }
  }
  const carried: TRow[] = [], hand: TRow[] = [], dropped: TRow[] = [], odd: string[] = [];
  for (const r of prevRows) {
    const plan = pyStrip(s(r["상태"])) === "집행계획미요청";
    if (!plan && !isHandUnpaid(r)) { dropped.push(r); continue; }
    const row: TRow = {};
    for (const c of SCHEMA["프로젝트집행.csv"]!) row[c] = pyStrip(s(r[c]));
    const d = digits(row["프로젝트번호"] as string);
    const same = d ? byDigits.get(d) ?? [] : [];
    if (same.length === 1) row["프로젝트번호"] = same[0]!;
    else if (plan) odd.push(row["프로젝트번호"] as string);
    if (!plan) {
      for (const column of ["공급가액", "부가세"]) {
        const value = num(row[column]);
        if (value !== null) row[column] = cellAmount(value);
      }
    }
    (plan ? carried : hand).push(row);
  }
  return [carried, hand, dropped, odd];
}

/** build_execs */
export function buildExecs(books: Books, costs: LinkResult, requests: Request[], match: Match, prevRows: TRow[], cfg: Cfg,
  projects: Projects | null = null): Table {
  const [groups, checks0, notes0] = wehagoRows(books, costs, cfg);
  const part = requestsPart(groups, requests, match);
  const wehago = groups.map(rowOf);
  const requestRows = part.entries.map((e) => e[2]);
  const keyPool = projects !== null ? [...projects.keys()] : [...new Set([...costs.lines.filter((ln) => ln.project).map((ln) => ln.project as string),
    ...requests.filter((rq) => rq.code).map((rq) => rq.code as string)])].sort(cmpStr);
  const [carried, hand, dropped, odd] = carryPlanRows(prevRows, keyPool);
  const rows = [...wehago, ...requestRows, ...carried, ...hand];
  const checks = [...checks0, ...requestChecks(part, [...wehago, ...requestRows], match)];
  checks.push(basisCheck(groups, part.entries.filter((e) => e[1] === 0).map((e) => e[2])));
  const ov = overlaps(hand, [...wehago, ...requestRows]);
  checks.push(check(HAND_LABEL, prevRows.filter(isHandUnpaid).length, rows.filter(isHandUnpaid).length));
  checks.push(check(OVERLAP_LABEL, 0, ov.length));
  const notes = [...notes0, ...part.notes];
  if (hand.length) {
    const totals = hand.map(rowTotal);
    const unknown = totals.filter((t) => t === null).length;
    notes.push(`이전 프로젝트집행.csv 손으로 넣은 미지급 줄 ${hand.length}건 옮김 (근거가 'WEHAGO '·'지급요청'으로 시작하지 않는 요청미지급·카드사용미결제): 공급가액+부가세 ${won(totals.reduce<number>((a, t) => a + (t ?? 0), 0))}원${unknown ? ` (금액 미확인 ${unknown}건)` : ""}`);
  }
  for (const [h, hits] of ov) {
    const head = [s(h["프로젝트번호"]), s(h["거래처"] ?? ""), won(rowTotal(h))].filter((x) => x).join(" ");
    notes.push(`겹칠 수 있음: 손으로 넣은 줄 ${head} (${s(h["근거"] ?? "")}) — 새 줄 ${hits.map((g) => s(g["근거"] ?? "")).join(" / ")} → 같은 지출이면 이전 줄을 지우세요`);
  }
  if (carried.length) notes.push(`이전 프로젝트집행.csv 집행계획미요청 줄 ${carried.length}건 옮김`);
  if (odd.length) notes.push(`프로젝트번호를 새 번호로 바꾸지 못한 집행계획미요청 줄 ${odd.length}건은 번호 그대로 옮김 (${odd.map((o) => o || "(빈칸)").join(", ")})`);
  if (dropped.length) {
    notes.push(`이전 프로젝트집행.csv 줄 ${dropped.length}건 옮기지 않음 (WEHAGO·인트라넷으로 다시 만듦)`);
    const unpaid = dropped.filter((r) => UNPAID.includes(pyStrip(s(r["상태"]))));
    if (unpaid.length) {
      const known = unpaid.filter((r) => num(r["공급가액"]) !== null).map((r) => (num(r["공급가액"]) || 0) + (num(r["부가세"]) || 0));
      notes.push(`옮기지 않은 줄 중 아직 나가지 않은 돈(요청미지급·카드사용미결제) ${unpaid.length}건, 공급가액+부가세 ${won(known.reduce((a, b) => a + b, 0))}원${known.length < unpaid.length ? ` (금액 미확인 ${unpaid.length - known.length}건 제외)` : ""} — 새 줄에 같은 지출이 있는지 확인`);
    }
  }
  const portions = [...groups.map((g) => g.supply), ...new Array(requestRows.length + carried.length + hand.length).fill(null)];
  const cardVat = new Map<string, [number, number]>();
  for (const g of groups) {
    if (g.card_pay && g.project && g.vat) {
      if (!cardVat.has(g.project)) cardVat.set(g.project, [0, 0]);
      const cv = cardVat.get(g.project)!;
      cv[0] += g.vat; cv[1]++;
    }
  }
  return new Table("프로젝트집행.csv", SCHEMA["프로젝트집행.csv"]!, rows, { checks, notes, extra: { cost_portions: portions, card_vat: cardVat } });
}
