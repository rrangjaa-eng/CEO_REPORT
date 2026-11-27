// calc.py 464-537: 5. 계산서·수금 → R.s5
import { daysBetween } from "../model/dates";
import { sortedBy } from "../model/py";
import { ssum, ssumOrNone } from "../model/util";
import type { Ctx, Obj } from "./ctx";
import { eventUnissued, expectedRevenue, netCredits } from "./projects";

export function section5(ctx: Ctx): void {
  const { R, asof, invs, in_missing, plist, proj } = ctx;
  const inv_by = new Map<string, Obj[]>();
  for (const v of invs) {
    const l = inv_by.get(v["project"]);
    if (l) l.push(v);
    else inv_by.set(v["project"], [v]);
  }
  const ar_rows: Obj[] = [], overdue: Obj[] = [], specials: Obj[] = [];
  for (const v of invs) {
    const total = v["supply"] === null || v["vat"] === null ? null : v["supply"] + v["vat"];
    v["total"] = total;
    if (total === null || (v["paid"] === null && v["paid_date"])) v["outstanding"] = null;
    else v["outstanding"] = total - (v["paid"] || 0);
  }
  netCredits(invs);
  for (const v of invs) {
    if (["선수금", "취소", "환불", "수정"].includes(v["kind"])) specials.push(v);
    if (v["outstanding"] && v["outstanding"] > 0 && v["kind"] !== "환불") {
      ar_rows.push(v);
      if (v["due"] && v["due"] < asof) {
        v["overdue_days"] = daysBetween(v["due"], asof);
        overdue.push(v);
      }
    }
  }
  const inv_proj: Obj[] = [];
  for (const P of plist) {
    const rows = inv_by.get(P["id"]) ?? [];
    const rows_i = rows.filter((v) => v["kind"] !== "환불");
    let [issued, issued_unknown] = ssum(rows_i.map((v) => v["supply"])) as [number | null, number];
    if (rows_i.length && issued_unknown === rows_i.length) issued = null;
    const rows_a = rows_i.filter((v) => v["outstanding"] === null || v["outstanding"] > 0);
    let [out, out_unknown] = ssum(rows_a.map((v) => v["outstanding"])) as [number | null, number];
    if (rows_a.length && out_unknown === rows_a.length) out = null;
    let unissued = P["contract"] === null || issued_unknown > 0 ? null : P["contract"] - (issued as number);
    if (in_missing.length) issued = out = unissued = null;
    let days: number | null = null;
    if (unissued && unissued > 0 && P["done_date"]) days = daysBetween(P["done_date"], asof);
    inv_proj.push({ P, issued, issued_unknown, unissued, ar: out, ar_unknown: out_unknown, unissued_days: days,
                    unknown: issued_unknown + out_unknown });
  }
  const no_proj_inv = invs.filter((v) => !proj.has(v["project"]));
  const [c_tot, c_missing] = ssumOrNone(plist.map((P) => P["contract"]));
  let [unissued_tot] = ssumOrNone(inv_proj.map((x) => x["unissued"]));
  let [issued_tot] = ssumOrNone(inv_proj.map((x) => x["issued"]));
  const ar_unknown_n = invs.filter((v) => v["kind"] !== "환불" && v["outstanding"] === null).length;
  let ar_tot: number | null = ar_rows.reduce((s, v) => s + v["outstanding"], 0);
  if (!ar_rows.length && ar_unknown_n) ar_tot = null;
  let overdue_tot: number | null = overdue.reduce((s, v) => s + v["outstanding"], 0);
  const overdue_unknown = invs.filter((v) => v["outstanding"] === null && v["kind"] !== "환불" && v["due"] && v["due"] < asof);
  if (in_missing.length) issued_tot = unissued_tot = ar_tot = overdue_tot = null;
  R["s5"] = {
    in_missing,
    by_project: inv_proj, ar_rows, overdue: sortedBy(overdue, (v) => -v["overdue_days"]),
    specials, no_project: no_proj_inv,
    contract: c_tot, contract_missing: c_missing,
    issued: issued_tot,
    issued_unknown_n: inv_proj.reduce((s, x) => s + x["issued_unknown"], 0),
    unissued_unknown_n: inv_proj.filter((x) => x["unissued"] === null).length,
    ar_unknown_n,
    unissued: unissued_tot,
    ar: ar_tot,
    overdue_total: overdue_tot,
    overdue_unknown_n: in_missing.length ? 0 : overdue_unknown.length,
    unissued_aged: inv_proj.filter((x) => x["unissued_days"] !== null),
    event_unissued: eventUnissued(inv_proj, asof, in_missing),
    expected: expectedRevenue(inv_proj, asof, in_missing),
  };
  ctx.ar_rows = ar_rows;
  ctx.inv_proj = inv_proj;
}
