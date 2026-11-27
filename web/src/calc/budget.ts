// ceo_report/budget.py compare (월간 보고 '예산 대비').
import type { BudgetConfirmedYear } from "../model/data";
import { cmpStr } from "../model/py";

export const COMPANY = "회사 전체";

/** actual_team = {팀: [[월, 매출, 매출총이익] ...]}. -> null (그 해 확정 예산 없음) 또는 {date, month, rows, tot, co} */
export function compare(confirmed: Record<string, BudgetConfirmedYear> | null | undefined, ym: string,
                        actualTeam: Map<string, [number, number | null, number | null][]>,
                        actualCo: Record<string, unknown> | null = null): Record<string, unknown> | null {
  const y = ym.slice(0, 4), m = parseInt(ym.slice(5, 7), 10);
  const C = (confirmed ?? {})[y];
  if (!C) return null;
  const split = (k: string): [number, string] => {
    const i = k.indexOf("|");
    return [parseInt(k.slice(0, i), 10), k.slice(i + 1)];
  };
  const teams = [...new Set(Object.keys(C.rows).map((k) => split(k)[1]).filter((w) => w !== COMPANY))].sort(cmpStr);
  const rowOf = (mm: number, who: string) => C.rows[`${mm}|${who}`];
  const rows: Record<string, number | null | string>[] = [];
  for (const t of teams) {
    const act = new Map<number, [number | null, number | null]>();
    for (const [mm, rv, g] of actualTeam.get(t) ?? []) act.set(mm, [rv, g]);
    const b = (mm: number, k: string) => rowOf(mm, t)?.[k] || 0;
    let ytd = 0, ytd_b = 0, gp = 0, gp_b = 0;
    for (let mm = 1; mm <= m; mm++) {
      ytd += (act.get(mm) ?? [0, 0])[0] || 0;
      ytd_b += b(mm, "매출");
      gp += (act.get(mm) ?? [0, 0])[1] || 0;
      gp_b += b(mm, "매출총이익");
    }
    rows.push({ team: t, cur: (act.get(m) ?? [null, null])[0], cur_b: b(m, "매출"), ytd, ytd_b, gp, gp_b });
  }
  const tot: Record<string, number> = {};
  for (const k of ["cur", "cur_b", "ytd", "ytd_b", "gp", "gp_b"]) tot[k] = rows.reduce((s, r) => s + ((r[k] as number) || 0), 0);
  let co: Record<string, unknown> | null = null;
  if (actualCo && Object.keys(actualCo).length) {
    const cb = (k: string) => { let s = 0; for (let mm = 1; mm <= m; mm++) s += rowOf(mm, COMPANY)?.[k] || 0; return s; };
    const c: Record<string, unknown> = { sal_b: cb("급여"), sga_b: cb("판관비"), dep_b: cb("감가상각비") };
    c["op_b"] = (tot["gp_b"] as number) - (c["sal_b"] as number) - (c["sga_b"] as number) - (c["dep_b"] as number);
    Object.assign(c, actualCo);
    co = c;
  }
  return { date: C.date, month: m, rows, tot, co };
}
