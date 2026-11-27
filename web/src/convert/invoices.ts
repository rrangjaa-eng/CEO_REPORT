// convert_invoices.py: 계산서.csv (매출 계산서 원천 + 분개장 매출채권 수금).
import { SCHEMA } from "../model/data";
import { addDays, type IsoDate } from "../model/dates";
import { cmpStr, pyIsDigit, pyRound, pyStrip, sortedBy } from "../model/py";
import { maskRrn, num, parseDate, won } from "../model/util";
import { normVendor } from "../model/vendor";
import type { Cfg } from "./config";
import { isPrior, type LinkLine, type LinkResult, type Projects } from "./linking";
import { cellAmount, check, Table, type Check, type TRow } from "./table";
import { squash, type Books, type Sales, type SaleRow } from "./wehago";

const BASES = ["코드", "분개장 매출 줄", "자동", "미연결", "참고"];
const NONE_REASON = "자료 없음 (매출 계산서 엑셀)";
const FIRM = ["Y", "N", "확정", ""];
export const DUE_GUESS_DAYS = 60;
const FAR = "9999-12-31";
export const BALANCE_LABEL = "매출채권 잔액: 분개장 (차변−대변) = 계산서.csv 미수 (합계−입금액) + 기초 미수 남음";
const ASSET = /^10\d{3}$/;
const COLUMNS = SCHEMA["계산서.csv"] as string[];

const normNo = (t: unknown) => pyStrip(t === null || t === undefined ? "" : String(t)).replace(/^(\p{Nd}+)\.0+$/u, "$1");
const noKey = (no: string): [number, number, string] => (pyIsDigit(no) ? [0, Number(no), no] : [1, 0, no]);
const day = (d: IsoDate | null) => d ?? "날짜 없음";
const cellDate = (d: IsoDate | null | undefined) => d ?? "";

function sumOrNone(values: Iterable<number | null | undefined>): number | null {
  let total = 0;
  for (const v of values) {
    if (v === null || v === undefined) return null;
    total += v;
  }
  return total;
}

interface Inv {
  idx: number; date: IsoDate | null; vendor: string; vendor_norm: string; item: string; supply: number | null; vat: number | null;
  source_total: number | null; total: number | null; code: string | null; type: string; no: string; applied: number;
  paid_date: IsoDate | null; project: string; basis: string; why: string; deducted: number; advance: boolean | null | undefined;
  kind?: string; parts?: [string, number][] | null; exact?: boolean;
}

function kindOf(inv: Inv): string {
  const kind = inv.type;
  if (kind.includes("취소")) return "취소";
  if (kind.includes("수정") || (inv.supply !== null && inv.supply < 0)) return "수정";
  if (inv.advance !== null && inv.advance !== undefined) return inv.advance ? "선수금" : "발행";
  if (["선금", "선수", "계약금"].some((w) => inv.item.includes(w))) return "선수금";
  return "발행";
}

function projectOf(inv: Inv, revLines: LinkLine[], projects: Projects): [string, string, string] {
  const reasons: string[] = [];
  const code = inv.code;
  if (code) {
    if (!projects.size || projects.has(code)) return [code, "코드", ""];
    reasons.push(`코드 ${code} 프로젝트 목록에 없음`);
  }
  if (inv.supply === null) reasons.push("공급가액 미확인");
  else if (inv.date === null) reasons.push("발행일 없음");
  else {
    const same = revLines.filter((ln) => inv.vendor_norm && ln.vendor_norm === inv.vendor_norm && ln.date === inv.date && ln.amount === inv.supply);
    const linked = [...new Set(same.filter((ln) => ln.project !== null).map((ln) => ln.project as string))].sort(cmpStr);
    if (linked.length === 1) return [linked[0] as string, "분개장 매출 줄", ""];
    if (!same.length) reasons.push("분개장 매출 줄 없음");
    else if (!linked.length) reasons.push("분개장 매출 줄 미연결");
    else reasons.push(`분개장 매출 줄이 서로 다른 프로젝트 ${linked.length}건`);
  }
  if (!projects.size) reasons.push("프로젝트 목록 없음");
  else {
    const found = [...projects.entries()].filter(([, p]) => !p.dup && inv.vendor_norm && inv.supply !== null && p.client_norm === inv.vendor_norm
      && p.quote === inv.supply).map(([k]) => k).sort(cmpStr);
    if (found.length === 1) return [found[0] as string, "자동", ""];
    reasons.push(`클라이언트·견적금액 후보 ${found.length}건`);
  }
  return ["", "미연결", reasons.join(" · ")];
}

function portions(inv: Inv, revLines: LinkLine[]): [string, number][] | null {
  if (!inv.no || inv.date === null || !inv.supply) return null;
  const mine = revLines.filter((ln) => ln.date === inv.date && normNo(ln.no) === normNo(inv.no));
  if (mine.length < 2 || mine.some((ln) => ln.amount === null) || mine.reduce((s, ln) => s + (ln.amount as number), 0) !== inv.supply) return null;
  const parts = new Map<string, number>();
  for (const ln of mine) {
    const key = ln.prior ? "" : ln.project || "";
    parts.set(key, (parts.get(key) ?? 0) + (ln.amount as number));
  }
  if (parts.size < 2) return null;
  return [...parts].filter(([, v]) => v);
}

function share(total: number, parts: number[]): number[] {
  const base = parts.reduce((s, x) => s + x, 0);
  const out = parts.slice(0, -1).map((a) => Math.trunc(pyRound((total * a) / base)));
  return [...out, total - out.reduce((s, x) => s + x, 0)];
}

function invoicesOf(rows: SaleRow[]): Inv[] {
  return rows.map((r, i) => ({ idx: i, date: r.date, vendor: maskRrn(r.vendor), vendor_norm: r.vendor_norm || normVendor(r.vendor),
    item: maskRrn(r.item), supply: r.supply, vat: r.vat, source_total: r.total, total: r.supply === null || r.vat === null ? null : r.supply + r.vat,
    code: r.code, type: r.type || "", no: r.no || "", applied: 0, paid_date: null, project: "", basis: "미연결", why: "",
    deducted: r.deducted || 0, advance: r.advance }));
}

interface Receipt { date: IsoDate | null; no: string; vn: string; vendor: string; amount: number; left: number; fifo: boolean }
interface Opening { net: number; days: IsoDate[]; applied: number }

class Journal {
  receipts: Receipt[] = [];
  credits: Receipt[] = [];
  opening = new Map<string, Opening>();
  opening_any = false;
  balance = new Map<string, number | null>();
  names = new Map<string, string>();
  codes = new Map<string, Set<string>>();
  unknown = false;
  credit_all = 0;
  op(vn: string): Opening {
    if (!this.opening.has(vn)) this.opening.set(vn, { net: 0, days: [], applied: 0 });
    return this.opening.get(vn)!;
  }
  constructor(books: Books, cfg: Cfg) {
    const rec = new Set(cfg.receivable_codes.map(squash));
    const cash = new Set(cfg.cash_codes.map(squash));
    const asset = (code: string) => cash.has(code) || (ASSET.test(code) && !rec.has(code));
    const journal = books.journal;
    const groups = new Map<string, number[]>();
    journal.forEach((row, i) => {
      const k = (row.date ?? "") + "\u0000" + normNo(row.no);
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k)!.push(i);
    });
    journal.forEach((row) => {
      if (!rec.has(squash(row.account_code))) return;
      const vn = row.vendor_norm || normVendor(row.vendor);
      if (!this.names.has(vn)) this.names.set(vn, maskRrn(row.vendor));
      const vc = pyStrip(String(row.vendor_code || "")).replace(/^0+/, "");
      if (vc) {
        if (!this.codes.has(vn)) this.codes.set(vn, new Set());
        this.codes.get(vn)!.add(vc);
      }
      const d = row.debit, c = row.credit;
      if (d === null && c === null) {
        this.unknown = true;
        this.balance.set(vn, null);
        return;
      }
      const b = this.balance.has(vn) ? this.balance.get(vn)! : 0;
      if (b !== null) this.balance.set(vn, b + (d || 0) - (c || 0));
      const memo = squash(row.memo);
      if (memo.includes("전기이월") || memo.includes("기초잔액")) {
        this.opening_any = true;
        const o = this.op(vn);
        o.net += (d || 0) - (c || 0);
        if (row.date !== null) o.days.push(row.date);
      }
      const netCredit = (c || 0) - (d || 0);
      if (netCredit <= 0) return;
      this.credit_all += netCredit;
      const dd = row.date, no = normNo(row.no);
      let cashDebit = false;
      for (const j of groups.get((dd ?? "") + "\u0000" + no) ?? []) {
        const other = journal[j]!;
        if (asset(squash(other.account_code))) {
          if (other.debit === null && other.credit === null) this.unknown = true;
          else if ((other.debit || 0) > 0) cashDebit = true;
        }
      }
      const item: Receipt = { date: dd, no, vn, vendor: maskRrn(row.vendor), amount: netCredit, left: netCredit, fifo: false };
      (cashDebit ? this.receipts : this.credits).push(item);
    });
    const key = (r: Receipt) => [r.date ?? FAR, noKey(r.no), r.vn, r.amount] as never;
    this.receipts = sortedBy(this.receipts, key);
    this.credits = sortedBy(this.credits, key);
  }
}

const priorInv = (inv: Inv) => isPrior(inv.date, [inv.code]);

function settlePrior(invoices: Inv[]): [string, number][] {
  const byVendor = new Map<string, Inv[]>();
  for (const inv of invoices) {
    if (inv.total !== null && inv.date !== null) {
      if (!byVendor.has(inv.vendor_norm)) byVendor.set(inv.vendor_norm, []);
      byVendor.get(inv.vendor_norm)!.push(inv);
    }
  }
  const moved: [string, number][] = [];
  for (const [vn, invs] of byVendor) {
    const old = invs.filter((i) => i.basis === "참고");
    if (!old.length) continue;
    const rest = (i: Inv) => (i.total as number) - i.deducted - i.applied;
    const netv = old.reduce((s, i) => s + rest(i), 0);
    for (const o of old) {
      if (rest(o)) {
        o.applied += rest(o);
        o.paid_date = o.paid_date || o.date;
      }
    }
    let left = Math.abs(netv);
    if (netv === 0) continue;
    if (netv > 0) {
      const pool = sortedBy(invs.filter((i) => i.basis !== "참고" && (i.total as number) > 0 && i.applied > 0 && !i.exact), (i) => [i.date as string, i.idx], true);
      for (const n of pool) {
        const take = Math.min(left, n.applied);
        n.applied -= take;
        if (n.applied === 0) n.paid_date = null;
        left -= take;
        if (!left) break;
      }
    } else {
      const pool = sortedBy(invs.filter((i) => i.basis !== "참고" && (i.total as number) > 0 && rest(i) > 0), (i) => [i.date as string, i.idx]);
      const lastPaid = old.map((o) => o.paid_date).filter((d): d is string => d !== null).reduce((a, b) => (b > a ? b : a), "");
      for (const n of pool) {
        const give = Math.min(left, rest(n));
        n.applied += give;
        n.paid_date = n.paid_date || lastPaid || null;
        left -= give;
        if (!left) break;
      }
    }
    if (left) {
      const back = sortedBy(old, (i) => [i.date as string, i.idx]).pop() as Inv;
      back.applied -= netv > 0 ? left : -left;
    }
    if (Math.abs(netv) - left) moved.push([vn, (Math.abs(netv) - left) * (netv > 0 ? 1 : -1)]);
  }
  return moved;
}

interface Item { inv: Inv | null; date: IsoDate | null; remaining: number }

function allocate(invoices: Inv[], jr: Journal): Set<string> {
  const items = new Map<string, Item[]>();
  const skip = new Set<string>();
  for (const inv of sortedBy(invoices, (x) => [x.date ?? FAR, x.idx])) {
    if (inv.total === null) skip.add(inv.vendor_norm);
    if (inv.total !== null && inv.total > 0 && inv.date !== null) {
      if (!items.has(inv.vendor_norm)) items.set(inv.vendor_norm, []);
      items.get(inv.vendor_norm)!.push({ inv, date: inv.date, remaining: inv.total - inv.deducted });
    }
  }
  const opening = new Map<string, Item>();
  if (jr.opening_any) {
    for (const [vn, o] of jr.opening) {
      if (o.net > 0) opening.set(vn, { inv: null, date: o.days.length ? o.days.reduce((a, b) => (b < a ? b : a)) : null, remaining: o.net });
    }
  }
  const apply = (item: Item, r: Receipt, take: number) => {
    item.remaining -= take;
    r.left -= take;
    if (item.inv !== null) {
      item.inv.applied += take;
      const last = item.inv.paid_date;
      item.inv.paid_date = last === null || (r.date as string) > last ? r.date : last;
    } else jr.op(r.vn).applied += take;
  };
  for (const r of jr.receipts) {
    if (r.date === null) continue;
    for (const it of items.get(r.vn) ?? []) {
      const inv = it.inv as Inv;
      if (it.remaining === (inv.total as number) - inv.deducted && it.remaining === r.amount && (it.date as string) <= r.date) {
        apply(it, r, r.amount);
        inv.exact = true;
        break;
      }
    }
  }
  for (const r of jr.receipts) {
    if (r.left <= 0 || r.date === null || skip.has(r.vn)) continue;
    const queue = [...(opening.has(r.vn) ? [opening.get(r.vn)!] : []), ...(items.get(r.vn) ?? [])];
    for (const it of queue) {
      if (r.left <= 0) break;
      if (it.remaining <= 0 || (it.date !== null && it.date > r.date)) continue;
      apply(it, r, Math.min(r.left, it.remaining));
      r.fifo = true;
    }
  }
  return skip;
}

const sv = (r: TRow, k: string) => (r[k] === undefined || r[k] === null ? "" : String(r[k]));

export function balanceCheck(bookTotal: number | null, rows: TRow[], openingLeft: number | null, why: string): Check {
  const owed: (number | null)[] = [];
  for (const r of rows) {
    const supply = num(r["공급가액"] ?? null), vat = num(r["부가세"] ?? null);
    const text = pyStrip(sv(r, "입금액"));
    const got = !text ? 0 : num(text);
    owed.push(supply === null || vat === null || got === null ? null : supply + vat - got);
  }
  let csvSide = sumOrNone(owed);
  if (csvSide !== null && openingLeft !== null) csvSide += openingLeft;
  else if (openingLeft === null) csvSide = null;
  return check(BALANCE_LABEL, why ? null : bookTotal, csvSide);
}

const pkey = (p: TRow) => {
  const d = parseDate(p["발행일"] ?? null), s = num(p["공급가액"] ?? null);
  return normVendor(sv(p, "거래처")) + "\u0000" + (d ?? "\u0001") + "\u0000" + (s === null ? "\u0001" : String(s));
};
const ikey = (vn: string, d: IsoDate | null, s: number | null) => vn + "\u0000" + (d ?? "\u0001") + "\u0000" + (s === null ? "\u0001" : String(s));

function carry(rows: Inv[], prevRows: TRow[], notes: string[]): [Map<number, TRow>, number] {
  const index = new Map<string, TRow[]>();
  for (const p of prevRows) {
    const k = pkey(p);
    if (!index.has(k)) index.set(k, []);
    index.get(k)!.push(p);
  }
  const mine = new Map<string, number>();
  for (const r of rows) {
    const k = ikey(r.vendor_norm, r.date, r.supply);
    mine.set(k, (mine.get(k) ?? 0) + 1);
  }
  const picked = new Map<number, TRow>();
  let used = 0;
  const said = new Set<string>();
  for (const r of rows) {
    const k = ikey(r.vendor_norm, r.date, r.supply);
    if (!r.vendor_norm || r.date === null || r.supply === null || !index.has(k)) continue;
    if (index.get(k)!.length > 1 || mine.get(k)! > 1) {
      if (!said.has(k)) {
        said.add(k);
        notes.push(`이전 계산서.csv와 새 계산서에 같은 거래처·발행일·공급가액 줄이 여러 건 (${r.vendor} ${day(r.date)} ${won(r.supply)}원) → 입금예정일 옮기지 않음`);
      }
      continue;
    }
    picked.set(r.idx, index.get(k)![0]!);
    used++;
  }
  return [picked, prevRows.length - used];
}

/** build_invoices */
export function buildInvoices(sales: Sales, books: Books, revenue: LinkResult | null, projects: Projects, prevRows: TRow[], cfg: Cfg): Table {
  if (sales.state !== "ok") return new Table("계산서.csv", COLUMNS, [], { written: false, reason: sales.reason || NONE_REASON });
  const notes = [...sales.notes];
  const invoices = invoicesOf(sales.rows);
  const revLines = revenue ? revenue.lines : [];
  for (const inv of invoices) {
    if (priorInv(inv)) [inv.project, inv.basis, inv.why] = ["", "참고", "지난해 계산서"];
    else [inv.project, inv.basis, inv.why] = projectOf(inv, revLines, projects);
    inv.kind = kindOf(inv);
    inv.parts = portions(inv, revLines);
  }
  const order = sortedBy(invoices, (x) => [x.date ?? FAR, x.idx]);
  const jr = new Journal(books, cfg);
  const skipFifo = allocate(invoices, jr);
  const moved = settlePrior(invoices);
  if (moved.length) {
    notes.push(`지난해 계산서는 입금 끝난 것으로 봄 (사용자 2026-11-04): 남은 순 미수를 같은 거래처 올해 계산서로 옮김 ${moved.length}곳 `
      + `(올해 미수 늘어남 ${won(moved.filter((m) => m[1] > 0).reduce((s, m) => s + m[1], 0))} · 줄어듦 ${won(-moved.filter((m) => m[1] < 0).reduce((s, m) => s + m[1], 0))})`);
  }
  const carryNotes: string[] = [];
  const [picked, notCarried] = carry(order, prevRows, carryNotes);
  const rows: TRow[] = [], bases: string[] = [], mismatch: string[] = [];
  let splitN = 0, splitRows = 0;
  const guessed: Inv[] = [];
  const splitPrev = new Map<string, TRow>();
  const seenPrev = new Map<string, number>();
  for (const p of prevRows) seenPrev.set(pkey(p), (seenPrev.get(pkey(p)) ?? 0) + 1);
  for (const p of prevRows) if (seenPrev.get(pkey(p)) === 1) splitPrev.set(pkey(p), p);
  const firmOf = (r: TRow) => {
    const f = pyStrip(sv(r, "예정일확정"));
    return FIRM.includes(f) ? f : "";
  };
  for (const inv of order) {
    const old = picked.get(inv.idx);
    let due = "", firm = "";
    if (old !== undefined) {
      due = cellDate(parseDate(old["입금예정일"] ?? null));
      firm = firmOf(old);
      const prevPaid = num(old["입금액"] ?? null);
      const nowPaid = inv.total !== null ? inv.applied + inv.deducted : null;
      if (prevPaid !== null && prevPaid !== nowPaid) mismatch.push(`이전 계산서.csv와 입금 기록 다름: ${inv.vendor} ${day(inv.date)} 이전 ${won(prevPaid)} · WEHAGO ${won(nowPaid)}`);
    }
    const paid = inv.applied + inv.deducted !== 0;
    if (!due && inv.date !== null && inv.total !== null && inv.total > 0 && inv.applied + inv.deducted < inv.total && !priorInv(inv)) {
      due = addDays(inv.date, DUE_GUESS_DAYS);
      firm = "N";
      guessed.push(inv);
    }
    const parts = inv.vat !== null ? inv.parts : null;
    if (!parts || !parts.length) {
      rows.push({ "프로젝트번호": inv.project, "거래처": inv.vendor, "발행일": cellDate(inv.date), "구분": inv.kind, "공급가액": cellAmount(inv.supply),
        "부가세": cellAmount(inv.vat), "입금예정일": due, "예정일확정": firm, "입금일": paid ? cellDate(inv.paid_date) : "",
        "입금액": paid ? cellAmount(inv.applied + inv.deducted) : "" });
      bases.push(inv.basis);
      continue;
    }
    splitN++;
    const amounts = parts.map(([, a]) => a);
    const vats = share(inv.vat as number, amounts);
    const gots = share(inv.applied + inv.deducted, amounts);
    parts.forEach(([pid, amt], i) => {
      const mineOld = splitPrev.get(ikey(inv.vendor_norm, inv.date, amt));
      let d2 = due, f2 = firm;
      if (old === undefined && mineOld !== undefined) {
        d2 = cellDate(parseDate(mineOld["입금예정일"] ?? null));
        f2 = firmOf(mineOld);
      }
      rows.push({ "프로젝트번호": pid, "거래처": inv.vendor, "발행일": cellDate(inv.date), "구분": inv.kind, "공급가액": cellAmount(amt),
        "부가세": cellAmount(vats[i]), "입금예정일": d2, "예정일확정": f2, "입금일": paid ? cellDate(inv.paid_date) : "",
        "입금액": paid ? cellAmount(gots[i]) : "" });
      bases.push(pid ? "분개장 매출 줄" : inv.basis === "참고" ? "참고" : "미연결");
      splitRows++;
    });
  }
  const csvSupply = sumOrNone(rows.map((r) => (r["공급가액"] ? Number(r["공급가액"]) : null)));
  const csvVat = sumOrNone(rows.map((r) => (r["부가세"] ? Number(r["부가세"]) : null)));
  const cash = jr.unknown ? null : sumOrNone(jr.receipts.map((r) => r.amount));
  const creditTotal = jr.unknown ? null : jr.credit_all;
  const paidCsv = invoices.reduce((s, i) => s + i.applied, 0);
  const openingApplied = [...jr.opening.values()].reduce((s, o) => s + o.applied, 0);
  const leftover = jr.receipts.filter((r) => r.left > 0);
  const leftSum = leftover.reduce((s, r) => s + r.left, 0);
  const creditSum = jr.credits.reduce((s, r) => s + r.amount, 0);
  const checks: Check[] = [
    check("계산서 줄 수", sales.rows.length, rows.length - (splitRows - splitN)),
    check("공급가액 합계", sumOrNone(sales.rows.map((r) => r.supply)), csvSupply),
    check("부가세 합계", sumOrNone(sales.rows.map((r) => r.vat)), csvVat),
    check("수금 (매출채권 대변 · 같은 전표 자산 계정(현금 계정·10xxx) 차변) = 입금액 합계 + 기초 미수 배분 + 미배분", cash, paidCsv + openingApplied + leftSum),
    check("매출채권 대변 합계 = 입금 + 수정(계산서 감액)", creditTotal, jr.receipts.reduce((s, r) => s + r.amount, 0) + creditSum),
  ];
  const stat = new Map<string, [number, number, number]>(BASES.map((b) => [b, [0, 0, 0]]));
  for (const inv of invoices) {
    const s = stat.get(inv.basis)!;
    s[0]++;
    if (inv.supply === null) s[2]++;
    else s[1] += inv.supply;
  }
  const sp: string[] = [];
  for (const [b, [n, total, unknown]] of stat) {
    if (b === "참고" && !n) continue;
    const text = `${b} ${n}건 ${n && n === unknown ? "미확인" : won(total)}`;
    sp.push(text + (unknown && n !== unknown ? ` (금액 미확인 ${unknown}건)` : ""));
  }
  notes.push("프로젝트 연결: " + sp.join(" · "));
  if (splitN) notes.push(`여러 프로젝트로 나뉜 계산서 ${splitN}장 → 프로젝트마다 한 줄씩 ${splitRows}줄로 적음 (부가세·입금액은 공급가액 비율)`);
  for (const inv of order) if (inv.basis === "미연결") notes.push(`  미연결 계산서 ${day(inv.date)} ${inv.vendor} ${won(inv.supply)} — ${inv.why}`);
  let revenueSum: number | null = null;
  if (revenue && ![...revenue.summary.values()].some((s) => s.unknown)) revenueSum = [...revenue.summary.values()].reduce((s, x) => s + x.sum, 0);
  notes.push(`참고 매출 계산서 공급가액 ${won(checks[1]!.source)} · 분개장 매출 ${won(revenueSum)}`);
  const names = new Map(jr.names);
  const invTotal = new Map<string, number>(), invApplied = new Map<string, number>();
  const invUnknown = new Set<string>();
  for (const inv of invoices) {
    if (!names.has(inv.vendor_norm)) names.set(inv.vendor_norm, inv.vendor);
    if (inv.total === null) invUnknown.add(inv.vendor_norm);
    else invTotal.set(inv.vendor_norm, (invTotal.get(inv.vendor_norm) ?? 0) + inv.total);
    invApplied.set(inv.vendor_norm, (invApplied.get(inv.vendor_norm) ?? 0) + inv.applied + inv.deducted);
  }
  const leftBy = new Map<string, number>(), creditBy = new Map<string, number>();
  for (const r of leftover) leftBy.set(r.vn, (leftBy.get(r.vn) ?? 0) + r.left);
  for (const r of jr.credits) creditBy.set(r.vn, (creditBy.get(r.vn) ?? 0) + r.amount);
  const bookSide = new Map<string, number | null>(), sheetSide = new Map<string, number | null>();
  const diffs: string[] = [];
  let openingLeftAll = 0;
  for (const vn of names.keys()) {
    bookSide.set(vn, jr.balance.has(vn) ? jr.balance.get(vn)! : 0);
    const o = jr.opening_any ? jr.opening.get(vn) : undefined;
    const openingLeft = o && o.net > 0 ? o.net - o.applied : 0;
    openingLeftAll += openingLeft;
    sheetSide.set(vn, invUnknown.has(vn) ? null : (invTotal.get(vn) ?? 0) - (invApplied.get(vn) ?? 0) + openingLeft);
  }
  for (const vn of sortedBy([...names.keys()], (k) => [names.get(k)!, k])) {
    const c = bookSide.get(vn)!, d = sheetSide.get(vn)!;
    if (c === null || d === null || c !== d) {
      const why = [`차이 ${c !== null && d !== null ? won(c - d) : "미확인"}`];
      if (leftBy.get(vn)) why.push(`미배분 수금 ${won(leftBy.get(vn)!)}`);
      if (creditBy.get(vn)) why.push(`수정(계산서 감액) ${won(creditBy.get(vn)!)}`);
      diffs.push(`매출채권 잔액 차이 ${names.get(vn)}: 분개장 ${won(c)} · 계산서 기준 ${won(d)} (${why.join(" · ")})`);
    }
  }
  const cAll = sumOrNone(bookSide.values()), dAll = sumOrNone(sheetSide.values());
  notes.push(`참고 매출채권 잔액: 분개장 ${won(cAll)} · 계산서 기준 ${won(dAll)} (차이 ${cAll !== null && dAll !== null ? won(cAll - dAll) : "미확인"})`);
  notes.push(...diffs);
  const starts = books.journal.filter((ln) => ln.date !== null).map((ln) => ln.date as string);
  const minStart = starts.length ? starts.reduce((a, b) => (b < a ? b : a)) : null;
  const early = invoices.filter((inv) => minStart !== null && inv.date !== null && inv.date < minStart);
  let blind = "";
  if (!jr.opening_any && (leftover.length || early.length)) {
    const ps: string[] = [];
    if (leftover.length) ps.push(`미배분 수금 ${leftover.length}건 ${won(leftSum)}`);
    if (early.length) ps.push(`분개장 시작(${minStart}) 전 계산서 ${early.length}건`);
    blind = `분개장에 전기이월·기초잔액 줄이 없고 ${ps.join(" · ")} — 기간 앞 미수의 입금인지 선입금인지 알 수 없음`;
    notes.push("매출채권 잔액 대조 판단 불가: " + blind);
  }
  checks.push(balanceCheck(cAll, rows, openingLeftAll, blind));
  const ded = invoices.filter((inv) => inv.deducted);
  if (ded.length) notes.push(`매출 때 바로 차감된 금액(카드 수수료 등) ${ded.length}건 ${won(ded.reduce((s, i) => s + i.deducted, 0))} → 입금액에 포함 (분개장 매출채권은 차감 뒤 금액)`);
  const mixed = sortedBy([...jr.codes.entries()].filter(([, c]) => c.size > 1).map(([vn, c]) => [jr.names.get(vn) || vn, [...c].sort(cmpStr)] as [string, string[]]),
    (x) => [x[0], x[1]]);
  if (mixed.length) {
    notes.push(`[확인] 이름이 같고 거래처코드가 다른 거래처 ${mixed.length}곳 — 입금이 다른 코드의 계산서에 붙었을 수 있음`
      + `(회사 전체 받을 돈 합계는 맞음, 거래처별·계산서별 미수만 확인): ${mixed.slice(0, 5).map(([n, c]) => `${n}(코드 ${c.join("·")})`).join(" · ")}`);
  }
  notes.push(`미배분 수금 ${leftover.length}건 ${won(leftSum)}`);
  for (const r of leftover) notes.push(`  미배분 수금 ${day(r.date)} ${r.vendor} ${won(r.left)} (전표 ${r.no})`);
  const fifo = jr.receipts.filter((r) => r.fifo);
  if (fifo.length) notes.push(`오래된 것부터(기초 미수 → 계산서) 배분한 입금 ${fifo.length}건 ${won(fifo.reduce((s, r) => s + r.amount, 0))} (금액이 계산서 하나와 같지 않은 입금: 분할·합산·수수료 차감 등)`);
  const part = order.filter((inv) => inv.total !== null && 0 < inv.applied && inv.applied < inv.total - inv.deducted);
  if (part.length) notes.push(`부분 입금 계산서 ${part.length}건 남은 금액 ${won(part.reduce((s, i) => s + (i.total as number) - i.deducted - i.applied, 0))} (수수료 차감 등도 자동으로 지우지 않음 — 미수로 둠)`);
  for (const inv of part) notes.push(`  부분 입금 ${day(inv.date)} ${inv.vendor} 합계 ${won(inv.total)} · 입금 ${won(inv.applied)} · 남음 ${won((inv.total as number) - inv.deducted - inv.applied)}`);
  if (jr.credits.length) notes.push(`수정(계산서 감액) ${jr.credits.length}건 ${won(creditSum)}`);
  for (const r of jr.credits) {
    const twin = order.filter((inv) => inv.kind === "수정" && inv.vendor_norm === r.vn && inv.total === -r.amount);
    notes.push(`  수정(계산서 감액) ${day(r.date)} ${r.vendor} ${won(r.amount)} (전표 ${r.no}${twin.length ? ` · 같은 금액의 수정 계산서 ${day(twin[0]!.date)} 있음` : ""})`);
  }
  const undatedN = invoices.filter((inv) => inv.date === null).length;
  if (undatedN) notes.push(`발행일 없는 계산서 ${undatedN}건 (입금과 짝짓지 않음)`);
  if (skipFifo.size) notes.push("합계를 모르는 계산서가 있는 거래처는 오래된 것부터 배분하지 않음: " + [...skipFifo].map((vn) => names.get(vn) ?? vn).sort(cmpStr).join(", "));
  const differ = invoices.filter((inv) => inv.total !== null && inv.source_total !== null && inv.total !== inv.source_total).length;
  if (differ) notes.push(`합계가 공급가액+부가세와 다른 계산서 ${differ}건 (공급가액+부가세로 처리)`);
  notes.push(...carryNotes);
  if (guessed.length) {
    notes.push(`입금예정일 빈칸 계산서 ${guessed.length}건 ${won(guessed.reduce((s, v) => s + (v.total as number) - v.applied - v.deducted, 0))} → 작성일 + ${DUE_GUESS_DAYS}일로 채움 (예상, 확정 아님). 실제 날짜를 알면 계산서.csv 입금예정일을 고치세요`);
  }
  notes.push(...mismatch);
  if (notCarried) notes.push(`이전 계산서.csv 줄 ${notCarried}건 옮기지 않음 (매출 계산서 엑셀로 다시 만듦)`);
  return new Table("계산서.csv", COLUMNS, rows, { checks, notes, extra: { basis: bases } });
}
