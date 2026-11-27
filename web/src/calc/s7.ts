// calc.py 절 7. 변동과 자료 반영 범위 (842-886): R.s7
import type { Ctx, Obj } from "./ctx";
import { sortedBy } from "../model/py";
import { ssum, ssumOrNone } from "../model/util";
import { addDays, daysBetween } from "../model/dates";
import { TRANSFER } from "../model/data";

export function section7(ctx: Ctx): void {
  const { d, R, p0, p1, asof, plist, proj, in_p } = ctx;
  const changes = d.changes.filter((c) => c.date && p0 <= c.date && c.date <= p1);
  const undated_changes = d.changes.filter((c) => !c.date);
  // 지급계획 대비 실제
  const w0 = addDays(p0, -6);
  const plan_rows = d.plans.filter((p) => p.week && w0 <= p.week && p.week <= p1);
  const actual_out = in_p.filter((t) => t["io"] === "출금" && t["cat"] !== TRANSFER);
  const K = (project: string, vendor: string) => JSON.stringify([project, vendor]);
  const plan_amounts = new Map<string, (number | null)[]>();
  for (const p of plan_rows) {
    const k = K(p.project, p.vendor);
    const a = plan_amounts.get(k);
    if (a) a.push(p.amount); else plan_amounts.set(k, [p.amount]);
  }
  const plan_keys = new Map<string, number | null>();
  const plan_key_unknown = new Map<string, number>();
  for (const [k, amts] of plan_amounts) {
    const [total_k, unk_k] = ssum(amts);
    plan_keys.set(k, unk_k === amts.length ? null : total_k); // 계획 금액이 모두 빈칸이면 미확인
    plan_key_unknown.set(k, unk_k);
  }
  const act_keys = new Map<string, number>();
  for (const t of actual_out) {
    const k = K(t["project"], t["vendor"]);
    act_keys.set(k, (act_keys.get(k) ?? 0) + (t["amount"] as number));
  }
  const allKeys = [...new Set([...plan_keys.keys(), ...act_keys.keys()])].map((k) => JSON.parse(k) as [string, string]);
  const pva: Obj[] = [];
  for (const [project, vendor] of sortedBy(allKeys, (k) => [k[0], k[1]])) {
    const k = K(project, vendor);
    pva.push({
      project, vendor, plan: plan_keys.has(k) ? plan_keys.get(k) : null, actual: act_keys.get(k) ?? 0,
      plan_unknown: plan_key_unknown.get(k) ?? 0, unplanned: !plan_keys.has(k),
    });
  }
  const no_budget = plist.filter((P) => P["budget"] === null || P["budget"] === undefined);
  const unlinked_txn = in_p.filter((t) => t["io"] === "출금" && t["cat"] === "프로젝트지급"
    && (!t["project"] || !proj.has(t["project"])));
  const [plan_total, plan_unknown_n] = ssum(plan_rows.map((p) => p.amount));
  const [nb_contract, nb_contract_missing] = ssumOrNone(no_budget.map((P) => P["contract"] as number | null));
  const asof_rows = d.asof.map((a) => ({ ...a, age: a.date === null ? null : daysBetween(a.date, asof) }));
  const sum = (xs: number[]) => xs.reduce((s, x) => s + x, 0);
  const s2 = R["s2"] as Obj;
  R["s7"] = {
    changes, undated_changes, pva, plan_rows,
    plan_total, plan_unknown_n, actual_total: sum(actual_out.map((t) => t["amount"] as number)),
    unplanned_total: sum(pva.filter((x) => x["unplanned"]).map((x) => x["actual"] as number)),
    no_budget, no_budget_expected: sum(no_budget.map((P) => P["expected"] as number)),
    no_budget_contract: nb_contract, no_budget_contract_missing: nb_contract_missing,
    unlinked_txn, unlinked_txn_total: sum(unlinked_txn.map((t) => t["amount"] as number)),
    undated_out: s2["undated_out"], undated_out_n: s2["undated_out_n"],
    undated_out_unknown: s2["undated_out_unknown"],
    asof: asof_rows, diffs: d.diffs, issues: ctx.issues.items, checks: ctx.checks,
    stale: ctx.stale_accounts,
  };
}
