// 장부 채무(미지급금·차입금) 대 자금 일정 — 파이썬 ceo_report/debts.py compare (175-260).
// 바꿀 것 U6: 거래처코드 비교는 양쪽 같은 규칙(codeKey).
import type { IsoDate } from "../model/dates";
import { sortedBy } from "../model/py";
import { normVendor } from "../model/vendor";
import { codeKey, type FundEvent } from "./fundplan";

export const PAYABLE = "미지급금";
export const LOAN = "차입금";
export const DEPOSIT = "정기예금";

/** debts.load 한 줄 (장부채무.csv). */
export interface DebtRow {
  kind: string;
  code: string;
  account: string;
  vcode: string;
  vendor: string;
  balance: number | null;
  date: string;
  due: string;
  due_basis: string;
  opening?: boolean;
  yearly?: boolean;
  extend_note?: string;
  [k: string]: unknown;
}

export interface DebtLeft { vendor: string; vcode: string; balance: number; scheduled: number; left: number; by_name: boolean }
export interface DebtOver { vendor: string; vcode: string; balance: number; scheduled: number; over: number }
export interface DebtsInfo {
  opening: boolean;
  repaid_loans: DebtRow[];
  unscheduled: DebtLeft[];
  unscheduled_total: number;
  unknown_n: number;
  over: DebtOver[];
  over_total: number;
  payable_total: number;
  loans: DebtRow[];
  loan_total: number;
  loan_unknown_n: number;
  date: string;
}

function add(m: Map<string, number>, k: string, v: number) {
  m.set(k, (m.get(k) ?? 0) + v);
}

/** 장부 채무 대 자금 일정. debts 가 null 이면 null. */
export function compareDebts(debts: DebtRow[] | null | undefined, events: FundEvent[], asof: IsoDate): DebtsInfo | null {
  if (debts === null || debts === undefined) return null;
  const byCode = new Map<string, number>(), byName = new Map<string, number>();
  const planCode = new Map<string, number>(), planName = new Map<string, number>();
  for (const ev of events) {
    if (ev.io !== "out" || ev.amount === null || (ev.date !== null && ev.date <= asof)) continue;
    const vc = codeKey(ev.vendor_code);
    if (vc) add(byCode, vc, ev.amount);
    if (String(ev.cat ?? "").includes("미지급금")) {
      if (vc) add(planCode, vc, ev.amount);
      else add(planName, normVendor(ev.desc || ""), ev.amount);
    }
    const nm = normVendor(ev.desc || "");
    if (nm) add(byName, nm, ev.amount);
  }
  const pays = debts.filter((d) => d.kind === PAYABLE);
  const loans = debts.filter((d) => d.kind === LOAN);
  let leftRows: DebtLeft[] = [];
  let unknownN = 0;
  const spentLeft = new Map<string, number>();
  for (const d of pays) {
    if (d.balance === null) {
      unknownN++;
      continue;
    }
    if (d.balance <= 0) continue;
    const vc = codeKey(d.vcode);
    let sched: number, nameMatch: boolean, key: string;
    if (vc && byCode.has(vc)) {
      [sched, nameMatch, key] = [byCode.get(vc)!, false, "c\u0000" + vc];
    } else {
      const nm = normVendor(d.vendor);
      [sched, nameMatch, key] = [byName.get(nm) ?? 0, true, "n\u0000" + nm];
    }
    if (!spentLeft.has(key)) spentLeft.set(key, sched);
    sched = Math.min(sched, spentLeft.get(key)!);
    spentLeft.set(key, Math.max(spentLeft.get(key)! - Math.min(sched, d.balance), 0));
    const left = d.balance - sched;
    if (left > 0) {
      leftRows.push({ vendor: d.vendor || "(거래처 없음)", vcode: d.vcode, balance: d.balance, scheduled: sched, left,
        by_name: nameMatch && sched > 0 });
    }
  }
  leftRows = sortedBy(leftRows, (r) => -r.left);
  const balCode = new Map<string, number | null>(), balName = new Map<string, number | null>(), names = new Map<string, string>();
  const addBal = (t: Map<string, number | null>, k: string, bal: number | null) => {
    const cur = t.has(k) ? t.get(k)! : 0;
    t.set(k, bal === null || cur === null ? null : cur + bal);
  };
  for (const d of pays) {
    const vc = codeKey(d.vcode);
    if (vc) {
      addBal(balCode, vc, d.balance);
      names.set(vc, d.vendor || vc);
    }
    addBal(balName, normVendor(d.vendor), d.balance);
  }
  const planDesc = new Map<string, string>();
  for (const ev of events) {
    const vc = codeKey(ev.vendor_code);
    if (String(ev.cat ?? "").includes("미지급금") && vc && !planDesc.has(vc)) planDesc.set(vc, ev.desc || "");
  }
  let overRows: DebtOver[] = [];
  for (const [vc, plan] of planCode) {
    const name = names.get(vc) || planDesc.get(vc) || "";
    const bal = balCode.has(vc) ? balCode.get(vc)! : (balName.has(normVendor(name)) ? balName.get(normVendor(name))! : 0);
    if (bal !== null && plan > Math.max(bal, 0)) {
      overRows.push({ vendor: name, vcode: vc, balance: bal, scheduled: plan, over: plan - Math.max(bal, 0) });
    }
  }
  for (const [nm, plan] of planName) {
    const bal = balName.has(nm) ? balName.get(nm)! : 0;
    if (nm && bal !== null && plan > Math.max(bal, 0)) {
      overRows.push({ vendor: nm, vcode: "", balance: bal, scheduled: plan, over: plan - Math.max(bal, 0) });
    }
  }
  overRows = sortedBy(overRows, (r) => -r.over);
  const knownLoans = loans.filter((d) => d.balance !== null && d.balance > 0);
  const repaid = loans.filter((d) => d.balance !== null && d.balance < 0);
  const sum = (xs: number[]) => xs.reduce((s, x) => s + x, 0);
  return {
    opening: debts.every((d) => (d.opening === undefined ? true : !!d.opening)),
    repaid_loans: repaid,
    unscheduled: leftRows, unscheduled_total: sum(leftRows.map((r) => r.left)), unknown_n: unknownN,
    over: overRows, over_total: sum(overRows.map((r) => r.over)),
    payable_total: sum(pays.filter((d) => d.balance !== null).map((d) => d.balance as number)),
    loans: knownLoans, loan_total: sum(knownLoans.map((d) => d.balance as number)),
    loan_unknown_n: loans.filter((d) => d.balance === null).length,
    date: debts.find((d) => d.date)?.date ?? "",
  };
}
