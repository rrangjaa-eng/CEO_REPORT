// calc.py 절 4. 매출·손익 (757-783): R.s4, ctx.ym·year·pl_out
import type { Ctx, Obj } from "./ctx";
import { sortedBy, cmpStr } from "../model/py";
import { ssumOrNone } from "../model/util";
import type { PlRow } from "../model/data";
import { plSum } from "./projects";

export function section4(ctx: Ctx): void {
  const { d, R } = ctx;
  const ym = ctx.asof.slice(0, 7);
  const year = ctx.asof.slice(0, 4);
  const pl_out = new Map<string, Obj>();
  const srcs = sortedBy([...new Set(d.pl.map((p) => p.source))], (x) => [x !== "WEHAGO", x]);
  for (const src of srcs) {
    const rows = d.pl.filter((p) => p.source === src);
    const months = [...new Set(rows.map((p) => p.ym))].sort(cmpStr);
    // OrderedDict (unit, target) -> [p...]
    const units = new Map<string, { unit: string; target: string; ps: PlRow[] }>();
    for (const p of rows) {
      const k = p.unit + "\u0000" + p.target;
      let u = units.get(k);
      if (!u) { u = { unit: p.unit, target: p.target, ps: [] }; units.set(k, u); }
      u.ps.push(p);
    }
    const table: Obj[] = [];
    for (const { unit, target, ps } of units.values()) {
      const cur = ps.filter((p) => p.ym === ym);
      const ytd = ps.filter((p) => p.ym.slice(0, 4) === year && cmpStr(p.ym, ym) <= 0);
      table.push({ unit, target, cur: plSum(cur), ytd: plSum(ytd) });
    }
    const by_month: [string, Obj[]][] = months
      .filter((m) => m.slice(0, 4) === year && cmpStr(m, ym) <= 0)
      .map((m) => [m, [...units.values()].map(({ unit, target, ps }) => (
        { unit, target, cur: plSum(ps.filter((p) => p.ym === m)), ytd: null }))]);
    pl_out.set(src, {
      table, latest: months.length ? months[months.length - 1] : null, has_cur: months.includes(ym), by_month,
    });
  }
  const plist = ctx.plist;
  R["s4"] = {
    ym, sources: Object.fromEntries(pl_out), projects: plist,
    unrecognized: ssumOrNone(plist.map((P) => P["unrecognized"] as number | null))[0],
    unrecognized_missing: plist.filter((P) => P["unrecognized"] === null || P["unrecognized"] === undefined).length,
    dept: d.dept ?? null, dept_problem: d.dept_problem ?? "",
    staff: d.staff ?? null,
  };
  ctx.ym = ym;
  ctx.year = year;
  ctx.pl_out = pl_out;
}
