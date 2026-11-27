// fundplan.py 의 변환 부분: 자금계획서(.xls 지출입금현황·현금대비잔액, 자동수집 .json) 읽기와 분개장 대조(settle).
// 보고서 계산 부분(apply·fill_projects)은 model 쪽에 있다.
import type { IsoDate } from "../model/dates";
import { addDays, daysBetween, ymd } from "../model/dates";
import { cmpKey, cmpStr, pyFloatParse, pyIntParse, pyIsDigit, pyRound, pyStrip, sortedBy, type SortKey } from "../model/py";
import { normCode, normVendor } from "../model/vendor";
import { basename, join, listFiles, readUtf8, type ConvFiles } from "./files";
import { isDict, pyStrJ, pyStrOr } from "./pyjson";
import { readXls, XlsError, type XlsCell } from "./xls";
import { squash, type Books, type JLine } from "./wehago";

const DETAIL_RE = /^예정일\s*:\s*(\p{Nd}{4})\.(\p{Nd}{1,2})\.(\p{Nd}{1,2})\s*-\s*(.*?)\s*\[(\p{Nd}+)\]\s*$/u;
const PERIOD_RE = /계획기간\s*:\s*(\p{Nd}{4})\s*년\s*(\p{Nd}{1,2})\s*월/u;
const SECTIONS: Record<string, string> = { "지급계획": "out", "입금계획": "in" };
export const COLUMNS = ["예정일", "입출금", "분류", "거래처", "거래처코드", "금액", "대상월", "자료일", "파일", "상태", "근거", "원전표", "프로젝트"];
const EARLY_DAYS: Record<string, number> = { "지급": 14, "입금": 45 };
export const STATES = ["예정", "예정일 지남", "이미 지급", "이미 입금"];

const toInt = (t: string) => pyIntParse(t) ?? NaN;

export function isFundplanName(name: string): boolean {
  const base = basename(name);
  return !base.startsWith("~$") && base.toLowerCase().endsWith(".xls") && base.includes("자금계획서")
    && (base.includes("지출입금") || base.includes("현금대비"));
}

const CASH_DETAIL_RE = /^예정일\s*:\s*(\p{Nd}{4})\.(\p{Nd}{1,2})\.(\p{Nd}{8})\s*-\s*(.*?)\s*\[(\p{Nd}+)\]\s*$/u;
const CASH_HEAD = ["일자", "항목명", "입금액", "지출액", "현금잔액"];
export const AUTO_PLAN_SUFFIX = "자금계획 자동수집.json";

export function isAutoPlanName(name: string): boolean {
  const base = basename(name);
  return !base.startsWith("~$") && base.endsWith(AUTO_PLAN_SUFFIX);
}

const RMK_ORIGIN_RE = /-\s*(\p{Nd}{10})\s*-\s*(\p{Nd}{8})\p{Nd}{2}\s*-/u;

/** dt.date(y, m, d) — 틀리면 null (ValueError). */
function mkDate(y: number, m: number, d: number): IsoDate | null {
  if (!Number.isInteger(y) || !Number.isInteger(m) || !Number.isInteger(d) || y < 1 || y > 9999 || m < 1 || m > 12 || d < 1) return null;
  const dim = [31, (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0 ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]!;
  if (d > dim) return null;
  return ymd(y, m, d);
}

const lstrip0 = (t: string) => t.replace(/^0+/, "");

export function originOf(remark: unknown, vendorCode: unknown): IsoDate | null {
  const m = RMK_ORIGIN_RE.exec(pyStrOr(remark));
  if (!m || lstrip0(m[1]!) !== lstrip0(pyStrOr(vendorCode))) return null;
  const s = m[2]!;
  return mkDate(toInt(s.slice(0, 4)), toInt(s.slice(4, 6)), toInt(s.slice(6)));
}

export interface PlanItem { date: IsoDate; cat: string; vendor: string; vendor_code: string; io: string | null; amount: number; origin?: IsoDate | null }
export interface MonthRes {
  month: [number, number] | null; items: PlanItem[]; checks: [string, number, number, boolean][]; ok: boolean; reason: string;
  opening?: number | null; settled?: Omit<PlanItem, "io" | "amount">[]; form: string; company?: string;
}

class FundplanError extends Error {}

/** parse_auto */
export function parseAuto(text: string): [MonthRes, IsoDate | null][] {
  let doc: unknown;
  try {
    doc = JSON.parse(text);
  } catch (e) {
    throw new FundplanError(e instanceof Error ? e.message : String(e));
  }
  if (!isDict(doc) || doc["종류"] !== "자금계획" || !Array.isArray(doc["줄"])) throw new XlsError("자금계획 자동수집 파일 모양이 아님");
  const cols0 = doc["열"];
  const cols: unknown[] = Array.isArray(cols0) ? cols0 : [];
  const need = ["date", "yn_inout", "nm_fitem", "cd_trade", "nm_trade", "mn_fplan"];
  if (need.some((c) => !cols.includes(c))) throw new XlsError("자금계획 자동수집 파일에 필요한 칸이 없음");
  const ix: Record<string, number> = {};
  for (const c of need) ix[c] = cols.indexOf(c);
  const taken = pyStrOr(doc["수집시각"]).slice(0, 10);
  let stamp: IsoDate | null = null;
  {
    const parts = taken.split("-");
    if (parts.length === 3) {
      const nums = parts.map((x) => pyIntParse(x));
      if (nums.every((x) => x !== null)) stamp = mkDate(nums[0]!, nums[1]!, nums[2]!);
    }
  }
  const doneRaw = doc["조회한달"];
  const done = new Set<string>(pyTruthyArr(doneRaw).map((d) => pyStrJ(d)));
  const period = isDict(doc["기간"]) ? doc["기간"] as Record<string, unknown> : {};
  const months: [number, number][] = [];
  if (!("from" in period) || !("to" in period)) throw new XlsError("자금계획 자동수집 파일에 기간이 없음");
  const f = pyStrJ(period["from"]), t = pyStrJ(period["to"]);
  let y = pyIntParse(f.slice(0, 4)), m = pyIntParse(f.slice(4, 6));
  const ey = pyIntParse(t.slice(0, 4)), em = pyIntParse(t.slice(4, 6));
  if (y === null || m === null || ey === null || em === null) throw new XlsError("자금계획 자동수집 파일에 기간이 없음");
  while (y < ey || (y === ey && m <= em)) {
    months.push([y, m]);
    [y, m] = m === 12 ? [y + 1, 1] : [y, m + 1];
  }
  const items = new Map<string, PlanItem[]>(months.map((mo) => [mo.join("-"), []]));
  let bad = 0;
  const rmkIdx = cols.indexOf("rmk_fplan");
  for (const row of doc["줄"] as unknown[]) {
    let day: IsoDate | null = null, io = "", amount = 0;
    if (!Array.isArray(row)) { bad++; continue; }
    const at = (i: number) => (i < row.length ? row[i] : undefined);
    {
      const dv = at(ix.date!);
      if (dv === undefined) { bad++; continue; }
      const d = pyStrJ(dv);
      const yy = pyIntParse(d.slice(0, 4)), mm = pyIntParse(d.slice(4, 6)), dd = pyIntParse(d.slice(6, 8));
      day = yy === null || mm === null || dd === null ? null : mkDate(yy, mm, dd);
      if (day === null) { bad++; continue; }
      const iv = at(ix.yn_inout!);
      if (iv !== "입금" && iv !== "지급") { bad++; continue; }
      io = iv === "입금" ? "in" : "out";
      const av = at(ix.mn_fplan!);
      let fv: number | null = null;
      if (typeof av === "number") fv = av;
      else if (typeof av === "boolean") fv = av ? 1 : 0;
      else if (typeof av === "string") fv = pyFloatParse(av);
      if (fv === null || !Number.isFinite(fv)) { bad++; continue; }
      amount = Math.trunc(pyRound(fv));
    }
    const key = `${Number(day.slice(0, 4))}-${Number(day.slice(5, 7))}`;
    if (!items.has(key)) { bad++; continue; }
    const code = lstrip0(pyStrOr(at(ix.cd_trade!)));
    const rmk = rmkIdx >= 0 && rmkIdx < row.length ? row[rmkIdx] : "";
    items.get(key)!.push({ date: day, cat: pyStrOr(at(ix.nm_fitem!)), vendor: pyStrOr(at(ix.nm_trade!)), vendor_code: code ? code.padStart(6, "0") : "",
      io, amount, origin: originOf(rmk, code) });
  }
  const out: [MonthRes, IsoDate | null][] = [];
  for (const mo of months) {
    let reason = "";
    if (!done.has(`${mo[0]}${String(mo[1]).padStart(2, "0")}`)) reason = "이 달은 받지 못함";
    else if (bad) reason = `읽지 못한 줄 ${bad}개`;
    out.push([{ month: mo, items: items.get(mo.join("-"))!, checks: [], ok: !reason, reason, opening: null, settled: [], form: "자동수집",
      company: pyStrip(pyStrOr(doc["회사"])) }, stamp]);
  }
  return out;
}

function pyTruthyArr(v: unknown): unknown[] {
  if (Array.isArray(v)) return v;
  if (typeof v === "string") return [...v];
  if (isDict(v)) return Object.keys(v);
  return [];
}

const isStr = (v: unknown): v is string => typeof v === "string";
const isNum = (v: unknown): v is number => typeof v === "number";

export function isCashForm(rows: XlsCell[][]): boolean {
  for (const row of rows.slice(0, 20)) {
    const head = row.slice(0, 5).map((v) => (isStr(v) ? squash(v) : ""));
    if (head.length === 5 && head.every((h, i) => h === CASH_HEAD[i])) return true;
  }
  return false;
}

function periodOf(v: XlsCell): [number, number] | null {
  if (!isStr(v)) return null;
  const m = PERIOD_RE.exec(v);
  return m ? [toInt(m[1]!), toInt(m[2]!)] : null;
}

/** parse_cash */
export function parseCash(rows: XlsCell[][]): MonthRes {
  let month: [number, number] | null = null, opening: number | null = null, total: [number, number] | null = null;
  let cat: string | null = null, catDay: number | null = null;
  const items: PlanItem[] = [], settled: Omit<PlanItem, "io" | "amount">[] = [];
  const cats = new Map<string, [number, number]>(), dets = new Map<string, [number, number]>();
  const catOrder: [number, string][] = [];
  let bad = 0;
  const numv = (v: XlsCell) => (isNum(v) ? v : 0.0);
  for (const row0 of rows) {
    const row = [...row0];
    while (row.length < 5) row.push("");
    const a = isStr(row[0]) ? pyStrip(row[0]) : "";
    const b = isStr(row[1]) ? pyStrip(row[1]) : "";
    for (const v of row) {
      const p = periodOf(v);
      if (p && month === null) month = p;
    }
    const sb = squash(b);
    if (sb.includes("전월이월")) { opening = numv(row[2]!) - numv(row[3]!); continue; }
    if (sb.includes("합계") && !a) { total = [numv(row[2]!), numv(row[3]!)]; continue; }
    if (pyIsDigit(a) && b) {
      cat = b; catDay = toInt(a);
      const key = catDay + "\u0000" + cat;
      if (!cats.has(key)) catOrder.push([catDay, cat]);
      const prev = cats.get(key) ?? [0, 0];
      cats.set(key, [prev[0] + numv(row[2]!), prev[1] + numv(row[3]!)]);
      continue;
    }
    const m = CASH_DETAIL_RE.exec(b);
    if (!m) continue;
    const s = m[3]!;
    const day = mkDate(toInt(s.slice(0, 4)), toInt(s.slice(4, 6)), toInt(s.slice(6)));
    if (day === null) { bad++; continue; }
    if (cat === null || Number(day.slice(8, 10)) !== catDay) bad++;
    const inn = numv(row[2]!), outv = numv(row[3]!);
    const key = catDay + "\u0000" + cat;
    const prev = dets.get(key) ?? [0, 0];
    dets.set(key, [prev[0] + inn, prev[1] + outv]);
    const base = { date: day, cat: cat || "", vendor: m[4]!, vendor_code: m[5]! };
    if (!inn && !outv) { settled.push(base); continue; }
    if (inn) items.push({ ...base, io: "in", amount: inn });
    if (outv) items.push({ ...base, io: "out", amount: outv });
  }
  const checks: [string, number, number, boolean][] = [];
  for (const [d, c] of catOrder) {
    const key = d + "\u0000" + c;
    const [ci, co] = cats.get(key)!;
    const [gi, go] = dets.get(key) ?? [0, 0];
    checks.push([`${d}일 ${c} 소계`, ci + co, gi + go, pyRound(ci) === pyRound(gi) && pyRound(co) === pyRound(go)]);
  }
  if (total !== null) {
    const si = items.filter((it) => it.io === "in").reduce((x, it) => x + it.amount, 0);
    const so = items.filter((it) => it.io === "out").reduce((x, it) => x + it.amount, 0);
    checks.push(["합계", total[0] + total[1], si + so, pyRound(total[0]) === pyRound(si) && pyRound(total[1]) === pyRound(so)]);
  }
  let reason = "";
  if (month === null) reason = "계획기간(연월)을 찾지 못함";
  else if (bad) reason = `날짜를 읽지 못했거나 분류 날짜와 다른 줄 ${bad}개`;
  else if (total === null) reason = "[합계] 줄을 찾지 못함";
  else if (!checks.every((c) => c[3])) reason = "소계·합계와 상세 합이 다름";
  else if ([...items, ...settled].some((it) => Number(it.date.slice(0, 4)) !== month![0] || Number(it.date.slice(5, 7)) !== month![1])) reason = "계획기간 밖 날짜의 줄이 있음";
  for (const it of items) it.amount = Math.trunc(pyRound(it.amount));
  return { month, items, checks, ok: !reason, reason, opening: opening === null ? null : Math.trunc(pyRound(opening)), settled, form: "현금대비잔액" };
}

/** file_date (fundplan) */
export function fileDate(name: string): IsoDate | null {
  const base = basename(name);
  const cands: [number, number, number][] = [];
  const m = /^(\p{Nd}{2})(\p{Nd}{2})(\p{Nd}{2})\P{Nd}/u.exec(base);
  if (m) cands.push([2000 + toInt(m[1]!), toInt(m[2]!), toInt(m[3]!)]);
  for (const mm of base.matchAll(/_(\p{Nd}{8})(?!\p{Nd})/gu)) {
    const s = mm[1]!;
    cands.push([toInt(s.slice(0, 4)), toInt(s.slice(4, 6)), toInt(s.slice(6))]);
  }
  for (const [y, mo, d] of cands) {
    const r = mkDate(y, mo, d);
    if (r !== null) return r;
  }
  return null;
}

/** parse (지출입금현황) */
export function parse(rows: XlsCell[][]): MonthRes {
  let month: [number, number] | null = null;
  outer: for (const row of rows) {
    for (const v of row) {
      const p = periodOf(v);
      if (p) { month = p; break outer; }
    }
  }
  type St = [string | null, string | null];
  let state: St = [null, null], start: St = [null, null], firstEnd: St | null = null, onFirst = false;
  let days: XlsCell[] | null = null;
  const cats = new Map<string, number>(), catKeys: St[] = [], dets = new Map<string, number>(), totals = new Map<string | null, number>();
  const items: PlanItem[] = [];
  let badDates = 0;
  const sk = (k: St) => (k[0] ?? "\u0001") + "\u0000" + (k[1] ?? "\u0001");
  for (const row of rows) {
    if (!row.length) continue;
    const a = isStr(row[0]) ? pyStrip(row[0]) : "";
    const cells: [number, number][] = [];
    row.forEach((v, i) => { if (i >= 1 && isNum(v) && v) cells.push([i, v]); });
    if (a === "자금구분") {
      if (onFirst) firstEnd = state;
      if (isStr(row[1]) && pyStrip(row[1]) === "1일") { start = firstEnd ?? [null, null]; onFirst = true; }
      else onFirst = false;
      state = start; days = row.slice(1);
      continue;
    }
    if (a.startsWith("▶")) { state = [SECTIONS[pyStrip(a.slice(1))] ?? null, null]; continue; }
    const m = DETAIL_RE.exec(a);
    if (m) {
      const key: St = [state[0], state[1]];
      for (const [i, v] of cells) {
        const day = days && i - 1 < days.length ? days[i - 1]! : "";
        const dtext = isStr(day) ? pyStrip(day).replace(/일+$/, "") : "";
        if (!(isStr(day) && pyIsDigit(dtext)) || toInt(dtext) !== toInt(m[3]!)) badDates++;
        dets.set(sk(key), (dets.get(sk(key)) ?? 0) + v);
      }
      const amount = cells.reduce((x, c) => x + c[1], 0);
      if (amount) {
        const d = mkDate(toInt(m[1]!), toInt(m[2]!), toInt(m[3]!));
        if (d === null) throw new FundplanError("day is out of range for month");
        items.push({ date: d, io: state[0], cat: state[1] || "", vendor: m[4]!, vendor_code: m[5]!, amount });
      }
      continue;
    }
    if (a === "계") { totals.set(state[0], (totals.get(state[0]) ?? 0) + cells.reduce((x, c) => x + c[1], 0)); continue; }
    if (!a || a.startsWith("회사명") || a.includes("자 금") || a.includes("계획기간")) continue;
    state = [state[0], a];
    if (!cats.has(sk(state))) catKeys.push(state);
    cats.set(sk(state), (cats.get(sk(state)) ?? 0) + cells.reduce((x, c) => x + c[1], 0));
  }
  const ioName = (io: string | null) => (io === "out" ? "지급" : io === "in" ? "입금" : "?");
  const checks: [string, number, number, boolean][] = [];
  for (const key of catKeys) {
    const sub = cats.get(sk(key))!, got = dets.get(sk(key)) ?? 0;
    checks.push([`${ioName(key[0])} ${key[1]} 소계`, sub, got, pyRound(sub) === pyRound(got)]);
  }
  for (const io of ["out", "in"]) {
    if (totals.has(io)) {
      const got = catKeys.filter((k) => k[0] === io).reduce((x, k) => x + cats.get(sk(k))!, 0);
      checks.push([`${ioName(io)} 계`, totals.get(io)!, got, pyRound(totals.get(io)!) === pyRound(got)]);
    }
  }
  let reason = "";
  if (month === null) reason = "계획기간(연월)을 찾지 못함";
  else if (items.some((it) => it.io === null)) reason = "지급/입금 구분을 알 수 없는 줄이 있음";
  else if (badDates) reason = `예정일과 금액 칸 날짜가 다른 줄 ${badDates}개`;
  else if (!checks.every((c) => c[3])) reason = "소계와 상세 합이 다름";
  else if (items.some((it) => Number(it.date.slice(0, 4)) !== month![0] || Number(it.date.slice(5, 7)) !== month![1])) reason = "계획기간 밖 날짜의 줄이 있음";
  for (const it of items) it.amount = Math.trunc(pyRound(it.amount));
  return { month, items, checks, ok: !reason, reason, form: "지출입금현황" };
}

export type PlanRow = Record<string, string | number>;
export interface FundLoad {
  rows: PlanRow[]; months: [string, string, IsoDate][]; notes: string[]; unused: string[]; companies?: Record<string, string>;
  openings?: [[number, number], number, string][]; settled?: Record<string, unknown>[];
}

const p2 = (n: number) => String(n).padStart(2, "0");
const fmt = (n: number) => n.toLocaleString("en-US");

/** 파일 수정 시각(초) → 날짜 (dt.date.fromtimestamp, 서울 시각). */
function mtimeDate(sec: number): IsoDate {
  const ms = Math.floor(sec * 1000) + 9 * 3600 * 1000;
  return new Date(ms).toISOString().slice(0, 10);
}

/** load */
export function load(files: ConvFiles, folder: string, mtimes: Record<string, number> = {}): FundLoad {
  const out: FundLoad = { rows: [], months: [], notes: [], unused: [] };
  const names = listFiles(files, folder).filter((n) => isFundplanName(n) || isAutoPlanName(n)).sort(cmpStr);
  const parsed: [[number, number], IsoDate, number, number, string, MonthRes][] = [];
  for (const n of names) {
    const path = join(folder, n);
    let found: [MonthRes, IsoDate | null][];
    try {
      if (isAutoPlanName(n)) {
        const text = readUtf8(files, path, false);
        if (text === null) throw new FundplanError("'utf-8' codec can't decode bytes");
        if (text.startsWith("﻿")) throw new FundplanError("Unexpected UTF-8 BOM (decode using utf-8-sig): line 1 column 1 (char 0)");
        found = parseAuto(text);
      } else {
        const grid = readXls(files[path]!);
        found = [[isCashForm(grid) ? parseCash(grid) : parse(grid), null]];
      }
    } catch (e) {
      if (!(e instanceof XlsError || e instanceof FundplanError)) throw e;
      out.notes.push(`${n} 읽지 못함 — ${e.message}`);
      out.unused.push(n);
      continue;
    }
    let usedAny = false;
    for (const [res, stamp0] of found) {
      const label = found.length === 1 ? n : `${n} ${res.month![0]}-${p2(res.month![1])}`;
      if (!res.ok) { out.notes.push(`${label} 쓰지 않음 — ${res.reason}`); continue; }
      usedAny = true;
      const mt = mtimes[path] ?? 0;
      const stamp = stamp0 || fileDate(n) || mtimeDate(mt);
      const rank = res.form === "자동수집" ? 2 : res.form === "현금대비잔액" ? 1 : 0;
      parsed.push([res.month!, stamp, rank, mt, n, res]);
    }
    if (!usedAny) out.unused.push(n);
  }
  const best = new Map<string, (typeof parsed)[number]>();
  const mk = (m: [number, number]) => `${m[0]}-${m[1]}`;
  const gt = (a: (typeof parsed)[number], b: (typeof parsed)[number]) => {
    if (a[1] !== b[1]) return a[1] > b[1];
    if (a[2] !== b[2]) return a[2] > b[2];
    return a[3] > b[3];
  };
  for (const p of parsed) {
    const k = mk(p[0]);
    if (!best.has(k) || gt(p, best.get(k)!)) best.set(k, p);
  }
  for (const p of parsed) {
    if (best.get(mk(p[0])) !== p) {
      out.unused.push(p[4]);
      out.notes.push(`${p[4]} 쓰지 않음 — 같은 달(${p[0][0]}-${p2(p[0][1])})의 더 새 파일 있음`);
    }
  }
  const order = sortedBy([...best.values()], (p) => [p[0][0], p[0][1]]);
  for (const [month, stamp, , , n, res] of order) {
    const ym = `${month[0]}-${p2(month[1])}`;
    out.months.push([ym, n, stamp]);
    if (res.company) (out.companies ??= {})[n] = res.company;
    if (res.opening !== null && res.opening !== undefined) (out.openings ??= []).push([month, res.opening, n]);
    if (res.settled && res.settled.length) (out.settled ??= []).push(...res.settled.map((s) => ({ ...s, file: n })));
    for (const it of sortedBy(res.items, (x) => [x.date, x.io ?? "", x.cat, x.vendor])) {
      out.rows.push({ "예정일": it.date, "입출금": it.io === "out" ? "지급" : "입금", "분류": it.cat, "거래처": it.vendor, "거래처코드": it.vendor_code,
        "금액": it.amount, "대상월": ym, "자료일": stamp, "파일": n, "상태": "", "근거": "", "원전표": it.origin ? it.origin : "", "프로젝트": "" });
    }
    const sum = (io: string) => res.items.filter((it) => it.io === io).reduce((x, it) => x + it.amount, 0);
    const cnt = (io: string) => res.items.filter((it) => it.io === io).length;
    out.notes.push(`${ym} ${n}: 지급 ${cnt("out")}줄 ${fmt(sum("out"))}원 · 입금 ${cnt("in")}줄 ${fmt(sum("in"))}원 (${res.form === "자동수집" ? "위하고 자금계획입력 계획월 조회" : "소계·계와 맞음"})`);
    if (res.settled && res.settled.length) out.notes.push(`${ym} ${n}: 위하고가 이미 반제한 줄 ${res.settled.length}건 (금액 없음, 일정에 넣지 않음)`);
  }
  out.unused.sort(cmpStr);
  return out;
}

export const PAYABLE_CODES = ["25300", "26200"];
export const RECEIVABLE_CODES = ["10800"];
export const CASH_CODES = ["10300"];
export const CARD_PREFIX = /^(신한|롯데|비씨|BC|삼성|현대|국민|KB|하나|우리|농협|NH|씨티)[_\s-]/u;

function originDay(r: PlanRow): IsoDate | null {
  const t = String(r["원전표"] ?? "").slice(0, 10);
  if (t.length !== 10) return null;
  const parts = t.split("-");
  if (parts.length !== 3) return null;
  const n = parts.map((x) => pyIntParse(x));
  if (n.some((x) => x === null)) return null;
  return mkDate(n[0]!, n[1]!, n[2]!);
}

function* combinations<T>(xs: T[], k: number): Generator<T[]> {
  const n = xs.length;
  if (k > n) return;
  const idx = Array.from({ length: k }, (_, i) => i);
  while (true) {
    yield idx.map((i) => xs[i]!);
    let i = k - 1;
    while (i >= 0 && idx[i] === i + n - k) i--;
    if (i < 0) return;
    idx[i]!++;
    for (let j = i + 1; j < k; j++) idx[j] = idx[j - 1]! + 1;
  }
}

type Cand = [number, number, boolean];
const ck = (c: Cand) => `${c[0]}|${c[1]}|${c[2] ? 1 : 0}`;

/** settle: 자금계획 줄마다 상태를 정한다. rows 를 고쳐 쓰고 상태별 건수를 돌려준다. */
export function settle(rows: PlanRow[], books: Books | null, asof: IsoDate, payable0: string[] = PAYABLE_CODES,
  receivable0: string[] = RECEIVABLE_CODES, cash0: string[] = CASH_CODES): Record<string, number> {
  const payable = payable0, receivable = receivable0, cash = cash0;
  const journal: JLine[] | null = books !== null && books.state === "ok" ? books.journal : null;
  const ref = journal !== null ? books!.book_date : null;
  const used = new Set<number>();
  const counts: Record<string, number> = {};
  for (const k of STATES) counts[k] = 0;
  const noOf = (ln: JLine) => String(ln.no || "");
  const bySlipLines = new Map<string, JLine[]>();
  for (const ln of journal ?? []) {
    const k = (ln.date ?? "") + "\u0000" + noOf(ln);
    if (!bySlipLines.has(k)) bySlipLines.set(k, []);
    bySlipLines.get(k)!.push(ln);
  }
  const mates = (line: JLine) => bySlipLines.get((line.date ?? "") + "\u0000" + noOf(line)) ?? [line];
  const paidOut = (line: JLine) => {
    let bankOut = false, moved = false;
    for (const x of mates(line)) {
      const c = squash(x.account_code);
      if (x === line || !(x.credit || 0)) continue;
      if (cash.includes(c) || c.startsWith("101") || c.startsWith("102") || c.startsWith("103")) bankOut = true;
      else if (payable.includes(c) && !CARD_PREFIX.test(pyStrip(x.vendor || ""))) moved = true;
    }
    return bankOut || !moved;
  };
  const kind = (line: JLine, io: string): [number | null, boolean] => {
    const code = squash(line.account_code);
    const debit = line.debit || 0, credit = line.credit || 0;
    if (io === "지급") {
      if (payable.includes(code) && debit && paidOut(line)) return [debit, true];
      if (cash.includes(code) && credit) return [credit, false];
    } else {
      if (receivable.includes(code) && credit) return [credit, true];
      if (cash.includes(code) && debit) return [debit, false];
    }
    return [null, false];
  };
  const windowOf = (r: PlanRow): [IsoDate, IsoDate] => {
    const due = String(r["예정일"]);
    let lo = addDays(due, -EARLY_DAYS[String(r["입출금"])]!);
    const file = String(r["파일"] || "");
    if ((file.includes("현금대비") || file.includes(AUTO_PLAN_SUFFIX)) && r["자료일"]) {
      const st = String(r["자료일"]);
      if (st > lo) lo = st;
    }
    const od = originDay(r);
    if (od !== null && od > lo) lo = od;
    return [due, lo];
  };
  const sameVendor = (r: PlanRow, line: JLine) => {
    const vcode = normCode(String(r["거래처코드"] ?? "")), key = normVendor(String(r["거래처"]));
    const pool = !cash.includes(squash(line.account_code)) ? [line] : mates(line);
    for (const x of pool) {
      const lcode = normCode(x.vendor_code);
      if (vcode && lcode) {
        if (lcode === vcode) return true;
        continue;
      }
      if (key && normVendor(x.vendor) === key) return true;
    }
    return false;
  };
  const slipKey = (line: JLine, i: number) => (line.date ?? "") + "\u0000" + (line.no ? String(line.no) : String(i));
  const candidates = (r: PlanRow): Cand[] => {
    const [, lo] = windowOf(r);
    const bySlip = new Map<string, Cand>();
    journal!.forEach((line, i) => {
      if (used.has(i) || line.date === null || line.date < lo || (ref !== null && line.date > ref)) return;
      const [amount, named] = kind(line, String(r["입출금"]));
      if (!amount || !sameVendor(r, line)) return;
      const k = slipKey(line, i);
      if (!bySlip.has(k) || (named && !bySlip.get(k)![2])) bySlip.set(k, [i, amount, named]);
    });
    return sortedBy([...bySlip.values()], (c) => [journal![c[0]]!.date as string, c[0]]);
  };
  const origin = new Map<string, JLine[]>();
  for (const line of journal ?? []) {
    const code = normCode(line.vendor_code);
    if (line.date === null || !code) continue;
    const ac = squash(line.account_code);
    let k: string | null = null;
    if (payable.includes(ac) && (line.credit || 0) > 0) k = ["지급", line.date, code, line.credit].join("\u0000");
    else if (receivable.includes(ac) && (line.debit || 0) > 0) k = ["입금", line.date, code, line.debit].join("\u0000");
    if (k !== null) {
      if (!origin.has(k)) origin.set(k, []);
      origin.get(k)!.push(line);
    }
  }
  const lost = new Set<number>();
  rows.forEach((r, n) => {
    const od = originDay(r);
    if (od === null || journal === null) return;
    const hits = origin.get([String(r["입출금"]), od, normCode(String(r["거래처코드"] ?? "")), r["금액"]].join("\u0000")) ?? [];
    if (hits.length) {
      const nos = [...new Set(hits.map((x) => String(x.no || "")))].sort(cmpStr);
      r["원전표"] = `${od} 전표 ${nos.join(", ")}`;
      const projs = new Set(hits.map((x) => x.line_project || ""));
      if (projs.size === 1 && [...projs][0]) r["프로젝트"] = [...projs][0]!;
    } else if (ref !== null && od <= ref) lost.add(n);
  });
  const found = new Map<number, number[]>();
  const slips = new Map<string, number[]>();
  (journal ?? []).forEach((line, i) => {
    const k = slipKey(line, i);
    if (!slips.has(k)) slips.set(k, []);
    slips.get(k)!.push(i);
  });
  const take = (idx: number[], r: PlanRow) => {
    for (const i of idx) {
      used.add(i);
      const namedI = kind(journal![i]!, String(r["입출금"]))[1];
      for (const j of slips.get(slipKey(journal![i]!, i)) ?? []) {
        if (used.has(j)) continue;
        const [amountJ, namedJ] = kind(journal![j]!, String(r["입출금"]));
        if (amountJ && namedJ !== namedI && sameVendor(r, journal![j]!)) used.add(j);
      }
    }
  };
  const absDays = (a: IsoDate, b: IsoDate) => Math.abs(daysBetween(b, a));
  if (journal !== null) {
    rows.forEach((r, n) => {
      const [due] = windowOf(r);
      let best: [[number, number], number] | null = null;
      for (const [i, amount, named] of candidates(r)) {
        if (amount !== r["금액"]) continue;
        const rank: [number, number] = [named ? 0 : 1, absDays(journal[i]!.date!, due)];
        if (best === null || rank[0] < best[0][0] || (rank[0] === best[0][0] && rank[1] < best[0][1])) best = [rank, i];
      }
      if (best !== null) { take([best[1]], r); found.set(n, [best[1]]); }
    });
    rows.forEach((r, n) => {
      if (found.has(n)) return;
      const [due, lo] = windowOf(r);
      const groups = new Map<string, { date: IsoDate; no: string; g: [number, number][] }>();
      journal.forEach((line, i) => {
        if (used.has(i) || line.date === null || line.date < lo || (ref !== null && line.date > ref)) return;
        const [amount, named] = kind(line, String(r["입출금"]));
        if (amount && named && sameVendor(r, line)) {
          const k = slipKey(line, i);
          if (!groups.has(k)) groups.set(k, { date: line.date, no: line.no ? String(line.no) : String(i), g: [] });
          groups.get(k)!.g.push([i, amount]);
        }
      });
      let best: [SortKey, number[]] | null = null;
      for (const { date, no, g } of groups.values()) {
        if (g.length >= 2 && g.reduce((x, c) => x + c[1], 0) === r["금액"]) {
          const rank: SortKey = [absDays(date, due), [date, no]];
          if (best === null || cmpKey(rank, best[0]) < 0) best = [rank, g.map((c) => c[0])];
        }
      }
      if (best !== null) { take(best[1], r); found.set(n, best[1]); }
    });
    rows.forEach((r, n) => {
      if (found.has(n)) return;
      const every = candidates(r).filter((c) => c[1] < (r["금액"] as number));
      const cands = every.slice(0, 12);
      let hit: number[] | null = null;
      for (const size of [2, 3, 4]) {
        for (const combo of combinations(cands, size)) {
          if (combo.reduce((x, c) => x + c[1], 0) === r["금액"]) { hit = combo.map((c) => c[0]); break; }
        }
        if (hit) break;
      }
      if (hit === null && every.length >= 5 && every.reduce((x, c) => x + c[1], 0) === r["금액"]) hit = every.map((c) => c[0]);
      if (hit) { take(hit, r); found.set(n, hit); }
    });
    const rest = new Map<string, number[]>();
    rows.forEach((r, n) => {
      if (found.has(n)) return;
      const k = String(r["입출금"]) + "\u0000" + (normCode(String(r["거래처코드"] ?? "")) || normVendor(String(r["거래처"])));
      if (!rest.has(k)) rest.set(k, []);
      rest.get(k)!.push(n);
    });
    for (const group of rest.values()) {
      if (group.length < 2) continue;
      const cache = new Map<number, Map<string, Cand>>();
      const cand = (n: number) => {
        if (!cache.has(n)) cache.set(n, new Map(candidates(rows[n]!).map((c) => [ck(c), c])));
        return cache.get(n)!;
      };
      for (const size of [4, 3, 2]) {
        const pool = group.filter((n) => !found.has(n)).slice(0, 8);
        for (const combo of combinations(pool, size)) {
          if (combo.some((n) => found.has(n))) continue;
          const total = combo.reduce((x, n) => x + (rows[n]!["금액"] as number), 0);
          const hit = sortedBy([...cand(combo[0]!).values()].filter((c) => c[1] === total && !used.has(c[0])
            && combo.slice(1).every((n) => cand(n).has(ck(c)))), (c) => [c[0], c[1], c[2]]);
          if (hit.length) {
            take([hit[0]![0]], rows[combo[0]!]!);
            for (const n of combo) found.set(n, [hit[0]![0]]);
          }
        }
      }
    }
  }
  rows.forEach((r, n) => {
    const [due] = windowOf(r);
    const io = String(r["입출금"]);
    const word = io === "지급" ? "지급" : "입금";
    if (found.has(n)) {
      const lines = found.get(n)!.map((i) => journal![i]!);
      r["상태"] = io === "지급" ? "이미 지급" : "이미 입금";
      const l0 = lines[0]!;
      if (lines.length === 1 && kind(l0, io)[0] !== r["금액"]) {
        r["근거"] = `분개장 ${l0.date} 전표 ${l0.no} ${l0.account} (같은 거래처 여러 줄을 한 번에 ${word})`;
      } else if (lines.length === 1) {
        r["근거"] = `분개장 ${l0.date} 전표 ${l0.no} ${l0.account}`;
      } else if (new Set(lines.map((x) => (x.date ?? "") + "\u0000" + String(x.no || ""))).size === 1) {
        r["근거"] = `분개장 ${l0.date} 전표 ${l0.no} ${l0.account} ${lines.length}줄 합계 (같은 거래처 여러 건을 한 전표로 ${word})`;
      } else {
        r["근거"] = `분개장 ${lines.length}건 합계로 나눠 ${word}: ${lines.map((x) => `${x.date} 전표 ${x.no}`).join(", ")}`;
      }
    } else if (due <= asof && journal !== null && ref !== null && due > ref) {
      r["상태"] = "예정";
      r["근거"] = `장부 기준일 ${ref} 뒤 예정일: 분개장으로 ${io === "지급" ? "출금" : "입금"} 확인 못함`;
    } else if (due <= asof) {
      r["상태"] = "예정일 지남";
      r["근거"] = journal !== null ? `분개장에 ${io === "지급" ? "출금" : "입금"} 없음 (장부 기준일 ${ref})` : "분개장 없음: 지급·입금 여부 확인 못함";
    } else {
      r["상태"] = "예정";
      r["근거"] = journal !== null ? "" : "분개장 없음: 미리 지급·입금했는지 확인 못함";
    }
    if (lost.has(n)) r["근거"] = (r["근거"] ? r["근거"] + " · " : "") + `원전표(${String(r["원전표"]).slice(0, 10)}·거래처코드·금액)를 장부에서 못 찾음`;
    counts[r["상태"] as string]!++;
  });
  return counts;
}


