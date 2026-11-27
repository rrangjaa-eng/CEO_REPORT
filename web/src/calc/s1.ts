// calc.py 201-287: 1. 현재 자금과 기간 입출금 → R.s1
import { TRANSFER } from "../model/data";
import { addDays } from "../model/dates";
import { sortedBy } from "../model/py";
import { ssum, won } from "../model/util";
import type { Ctx, Obj } from "./ctx";

export function section1(ctx: Ctx): void {
  const { d, R, issues, checks, asof, p0, p1 } = ctx;
  const balSorted = sortedBy(d.balances as Obj[], (x) => x["date"]);
  const latest = new Map<string, Obj>();
  for (const b of balSorted) if (b["date"] <= p1) latest.set(b["account"], b);
  const accounts: Obj[] = [...latest.values()];
  let cover: string | null = null;
  for (const t of d.txns) if (t.date <= p1 && (cover === null || t.date > cover)) cover = t.date;
  const rolled: Obj[] = [];
  accounts.forEach((a, i) => {
    if (a["balance"] === null || cover === null || a["date"] >= cover) return;
    const mv = d.txns.filter((t) => t.account === a["account"] && a["date"] < t.date && t.date <= cover!);
    const adj = mv.reduce((s, t) => s + (t.io === "입금" ? t.amount : -t.amount), 0);
    accounts[i] = { ...a, balance: a["balance"] + adj, date: cover, bank_date: a["date"], bank_balance: a["balance"],
                    roll: adj, roll_n: mv.length };
    rolled.push(accounts[i]!);
  });
  let [total_bal, bal_unknown] = ssum(accounts.map((a) => a["balance"])) as [number | null, number];
  const released = accounts.filter((a) => a["release"] && a["release"] <= asof && a["restricted"] && !a["release_guess"]);
  for (const a of released) {
    issues.add(a["row"]["_file"], a["row"]["_line"],
      `제한해제일 ${a["release"]} 지남 (${a["account"]}) → 사용제한 ${won(a["restricted"])} 빼지 않음. 계좌잔액.csv 정리 필요`);
  }
  let [restricted, restr_unknown] = ssum(accounts.map((a) => (released.includes(a) ? 0 : a["restricted"]))) as [number | null, number];
  if (!accounts.length || bal_unknown === accounts.length) total_bal = null;
  if (!accounts.length) restricted = null;
  const stale_accounts = accounts.filter((a) => a["date"] < p1);
  const in_p = (d.txns as Obj[]).filter((t) => p0 <= t["date"] && t["date"] <= p1);
  const ext = in_p.filter((t) => t["cat"] !== TRANSFER);
  const sum = (xs: Obj[]) => xs.reduce((s, t) => s + t["amount"], 0);
  const tin = sum(ext.filter((t) => t["io"] === "입금"));
  const tout = sum(ext.filter((t) => t["io"] === "출금"));
  const tr_in = sum(in_p.filter((t) => t["cat"] === TRANSFER && t["io"] === "입금"));
  const tr_out = sum(in_p.filter((t) => t["cat"] === TRANSFER && t["io"] === "출금"));
  const by_cat = new Map<string, [number, number]>();
  for (const t of ext) {
    const v = by_cat.get(t["cat"]) ?? (by_cat.set(t["cat"], [0, 0]), by_cat.get(t["cat"])!);
    v[t["io"] === "입금" ? 0 : 1] += t["amount"];
  }
  const acct_flow = new Map<string, [number, number]>();
  for (const t of in_p) {
    const v = acct_flow.get(t["account"]) ?? (acct_flow.set(t["account"], [0, 0]), acct_flow.get(t["account"])!);
    v[t["io"] === "입금" ? 0 : 1] += t["amount"];
  }
  const unknown_bal = accounts.filter((a) => a["balance"] === null);
  const unknown_names: string[] = unknown_bal.map((a) => a["account"]);
  const [bal_unknown_restricted] = ssum(unknown_bal.map((a) => a["restricted"]));
  for (const a of unknown_bal) {
    issues.add(a["row"]["_file"], a["row"]["_line"], "잔액 미확인 (" + a["account"] + ") → 현재 현금·사용 가능액 합계에서 제외");
  }
  const dayBefore = addDays(p0, -1);
  const start_snap = new Map<string, Obj>();
  for (const b of balSorted) if (b["date"] === dayBefore) start_snap.set(b["account"], b);
  let start_calc: number | null = null;
  if (total_bal !== null) {
    start_calc = total_bal - tin + tout - tr_in + tr_out;
    for (const a of unknown_bal) {
      const [fin, fout] = acct_flow.get(a["account"]) ?? [0, 0];
      start_calc += fin - fout;
    }
  }
  let start_bank: number | null = null;
  const sameKeys = start_snap.size === latest.size && [...start_snap.keys()].every((k) => latest.has(k));
  if (total_bal !== null && start_snap.size && sameKeys) {
    const [sb, sbu] = ssum([...start_snap].filter(([n]) => !unknown_names.includes(n)).map(([, b]) => b["balance"]));
    start_bank = sbu ? null : sb;
  }
  R["s1"] = {
    accounts, total: total_bal, bal_unknown, restricted,
    restr_unknown, available: total_bal === null ? null : total_bal - (restricted as number),
    stale: stale_accounts, rolled, txn_cover: cover,
    bal_unknown_names: unknown_names, bal_unknown_restricted,
    in: tin, out: tout, start_calc, start_bank,
    end: total_bal, by_cat: Object.fromEntries(by_cat), transfer_in: tr_in, transfer_out: tr_out,
    acct_flow: Object.fromEntries(acct_flow), txns: sortedBy(in_p, (t) => t["date"]),
  };
  const catIn = [...by_cat.values()].reduce((s, v) => s + v[0], 0);
  const catOut = [...by_cat.values()].reduce((s, v) => s + v[1], 0);
  checks.push(["이번 기간 회사 계좌 간 이체 (입금 = 출금)", tr_in, tr_out, tr_in === tr_out]);
  checks.push(["분류별 입금 합 = 입금 합계", catIn, tin, catIn === tin]);
  checks.push(["분류별 출금 합 = 출금 합계", catOut, tout, catOut === tout]);
  if (start_bank !== null && start_calc !== null) {
    let label = "기간 시작 잔액 (은행 잔액 = 거래로 계산한 값)";
    if (bal_unknown) label += ` · 잔액 미확인 ${bal_unknown}계좌 제외`;
    checks.push([label, start_bank, start_calc, start_bank === start_calc]);
  }
  ctx.in_p = in_p;
  ctx.stale_accounts = stale_accounts;
}
