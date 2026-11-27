// calc.py 절 6. 프로젝트 밖 지급과 지급의무 (784-841): R.s6
import type { Ctx, Obj } from "./ctx";
import { sortedBy } from "../model/py";
import { ssumOrNone } from "../model/util";
import { isPrior, type Sched } from "../model/data";

const DATE_MAX = "9999-12-31";

interface Cat6 { rows: Sched[]; total: number | null; unknown: number; undated: number }
interface Vend { total: number | null; next: string | null; n: number; unknown: number; vat_unknown: number }

export function section6(ctx: Ctx): void {
  const { d, R, issues } = ctx;
  const nonproj = d.schedule.filter((s) => s.io === "지급");
  const by_cat6 = new Map<string, Cat6>();
  for (const s of sortedBy(nonproj, (x) => [x.cat, x.date ?? DATE_MAX])) {
    let g = by_cat6.get(s.cat);
    if (!g) { g = { rows: [], total: 0, unknown: 0, undated: 0 }; by_cat6.set(s.cat, g); }
    g.rows.push(s);
    if (s.amount === null) g.unknown += 1;
    else g.total = (g.total as number) + s.amount;
    if (s.date === null) g.undated += 1;
  }
  for (const g of by_cat6.values()) {
    if (g.unknown === g.rows.length) g.total = null; // 분류 안의 모든 줄이 금액 미확인이면 합계는 미확인
  }
  const vendors = new Map<string, Vend>();
  const vendor = (name: string): Vend => {
    let v = vendors.get(name);
    if (!v) { v = { total: 0, next: null, n: 0, unknown: 0, vat_unknown: 0 }; vendors.set(name, v); }
    return v;
  };
  for (const s of nonproj) {
    if (!s.vendor) continue;
    const v = vendor(s.vendor);
    if (s.amount === null) v.unknown += 1;
    else v.total = (v.total as number) + s.amount;
    v.n += 1;
    if (s.date && (v.next === null || s.date < v.next)) v.next = s.date;
  }
  for (const e of d.execs) {
    if (e.state === "요청미지급" && e.vendor && !isPrior(e)) {
      const v = vendor(e.vendor);
      if (e.supply === null) v.unknown += 1;
      else {
        v.total = (v.total as number) + e.supply;
        if (e.vat === null) v.vat_unknown += 1;
        else v.total = (v.total as number) + e.vat;
      }
      v.n += 1;
      if (e.date && (v.next === null || e.date < v.next)) v.next = e.date;
    }
  }
  for (const v of vendors.values()) {
    if (v.unknown === v.n) v.total = null;
  }
  for (const s of d.schedule.filter((x) => x.cat.includes("프로젝트"))) {
    issues.add(s.row._file, s.row._line,
      `자금일정에 프로젝트 지급(${s.cat})이 있음 — 프로젝트집행.csv와 중복일 수 있음`);
  }
  const cats = [...by_cat6.values()];
  R["s6"] = {
    by_cat: Object.fromEntries(by_cat6) as Obj,
    vendors: sortedBy([...vendors.entries()], (kv) => [kv[1].total === null, -(kv[1].total ?? 0)]),
    total: ssumOrNone(cats.map((g) => g.total))[0],
    undated_n: cats.reduce((a, g) => a + g.undated, 0),
    unknown_n: cats.reduce((a, g) => a + g.unknown, 0),
  };
}
