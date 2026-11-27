// calc.py last_payday_out · ACCOUNT_GROUP_ORDER · account_year.
import type { AccountRow, Txn } from "../model/data";
import { TRANSFER } from "../model/data";
import { addDays, type IsoDate } from "../model/dates";
import { cmpStr, pyIsDigit, pyStrip, asciiDigits, sortedBy } from "../model/py";
import { normVendor } from "../model/vendor";
import type { Obj } from "./ctx";
import { autoDebit } from "./schedule";

/** 지난주 출금일(payday − 7일)로 끝나는 7일 동안 통장에서 실제로 나간 돈. prev = weekdiff 기록 (없으면 null). */
export function lastPaydayOut(txns: Txn[], payday: IsoDate, prev: Obj | null = null): Obj | null {
  const day = addDays(payday, -7);
  const start = addDays(day, -6);
  if (!txns.length) return null;
  let mx = txns[0]!.date;
  for (const t of txns) if (t.date > mx) mx = t.date;
  if (mx < day) return null;
  let keys: Set<string> | null = null;
  if (prev && addDays(day, -7) <= prev["asof"] && prev["asof"] < day) {
    keys = new Set((prev["rows"] as Obj[])
      .filter((r) => r["firm"] && r["amount"] !== null && r["amount"] !== undefined && prev["asof"] < r["date"] && r["date"] <= day)
      .map((r) => normVendor(r["desc"] || "")));
  }
  const rows: Obj[] = [];
  for (const t of txns) {
    if (!(start <= t.date && t.date <= day) || t.io !== "출금" || t.cat === TRANSFER) continue;
    const vendor = pyStrip(t.vendor || "");
    if (autoDebit({ io: "out", desc: vendor, cat: `${t.cat || ""} ${t.memo || ""}` })) continue;
    if (keys !== null && !keys.has(normVendor(vendor))) continue;
    rows.push({ vendor: vendor || pyStrip(t.memo || "") || "(거래처 없음)", amount: t.amount, memo: t.memo || "", date: t.date });
  }
  return {
    start, date: day, rows, total: rows.reduce((s, r) => s + (r["amount"] as number), 0),
    listed: keys !== null, prev_asof: keys !== null ? prev!["asof"] : null,
  };
}

export const ACCOUNT_GROUP_ORDER = ["원가", "판매비와관리비", "영업외비용"];

interface Cell { m: number[]; unk: Set<number> }

/** 계정과목별 연간표: 올해 1월~보고월 칸만 채움. 칸에 금액 빈 줄이 있으면 그 칸은 null. */
export function accountYear(rows: AccountRow[] | null | undefined, ym: string, problem = ""): Obj {
  if (rows === null || rows === undefined) {
    return { state: problem || "자료 없음", year: ym.slice(0, 4), upto: parseInt(ym.slice(5, 7), 10), groups: [] };
  }
  const year = ym.slice(0, 4), upto = parseInt(ym.slice(5, 7), 10);
  const cells = new Map<string, { g: string; code: string; c: Cell }>();
  const names = new Map<string, string>();
  for (const r of rows) {
    const mm = r.ym.slice(5, 7);
    if (r.ym.slice(0, 4) !== year || !pyIsDigit(mm) || parseInt(asciiDigits(mm), 10) > upto) continue;
    const g = r.group || "구분 없음";
    const k = JSON.stringify([g, r.code]);
    if (!names.has(k)) names.set(k, r.name);
    const m = parseInt(asciiDigits(mm), 10) - 1;
    let e = cells.get(k);
    if (!e) { e = { g, code: r.code, c: { m: new Array<number>(12).fill(0), unk: new Set() } }; cells.set(k, e); }
    if (r.amount === null) e.c.unk.add(m);
    else e.c.m[m] = (e.c.m[m] as number) + r.amount;
  }
  const groups: Obj[] = [];
  const present = [...new Set([...cells.values()].map((e) => e.g))];
  const order = [...ACCOUNT_GROUP_ORDER, ...present.filter((g) => !ACCOUNT_GROUP_ORDER.includes(g)).sort(cmpStr)];
  const sortedCells = sortedBy([...cells.entries()], (kv) => kv[1].code);
  const range12 = [...Array(12).keys()];
  for (const g of order) {
    const accs: Obj[] = [];
    for (const [k, { g: gg, code, c }] of sortedCells) {
      if (gg !== g) continue;
      const months = range12.map((m) => (c.unk.has(m) || m >= upto ? null : c.m[m] as number));
      const known = months.slice(0, upto).filter((v) => v !== null) as number[];
      accs.push({
        code, name: names.get(k), months, unknown: [...c.unk].sort((a, b) => a - b),
        total: known.reduce((s, v) => s + v, 0), partial: c.unk.size > 0,
      });
    }
    if (!accs.length) continue;
    const sub = range12.map((m) => (accs.some((a) => (a["unknown"] as number[]).includes(m)) || m >= upto ? null
      : accs.reduce((s, a) => s + ((a["months"] as (number | null)[])[m] || 0), 0)));
    groups.push({
      name: g, accounts: accs, months: sub, total: accs.reduce((s, a) => s + (a["total"] as number), 0),
      partial: accs.some((a) => a["partial"]),
    });
  }
  const tot = range12.map((m) => (m >= upto || groups.some((g) => (g["months"] as (number | null)[])[m] === null) ? null
    : groups.reduce((s, g) => s + ((g["months"] as number[])[m] as number), 0)));
  return {
    state: groups.length ? "ok" : "올해 자료 없음", year, upto, groups, months: tot,
    total: groups.reduce((s, g) => s + (g["total"] as number), 0), partial: groups.some((g) => g["partial"]),
  };
}
