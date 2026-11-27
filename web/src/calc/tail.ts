// calc.py 887-905: targets·budget_cmp·budget_conf_rows·evid_month·dep·acct_year·last_pay·plan_gap_note·risks
import type { Ctx, Obj } from "./ctx";
import { compare as budgetCompare } from "./budget";
import { depreciation } from "./corptax";
import { accountYear, lastPaydayOut } from "./accounts";
import { blankPlanGaps } from "./gate_blank";
import { risks } from "./risks";
import { totalsSplit } from "./totals_split";

export function tail(ctx: Ctx): void {
  const { d, R, ym, pl_out } = ctx;
  const targets: Obj = {};
  for (const [k, v] of Object.entries(d.team_targets ?? {})) {
    const i = k.indexOf("|");
    if (k.slice(0, i) === ym.slice(0, 4)) targets[k.slice(i + 1)] = v;
  }
  R["targets"] = targets;
  // 예산 대비: 그 해 확정 예산이 있을 때만. 실적 = 손익 팀 줄 달별 (WEHAGO 우선)
  const src0 = pl_out && pl_out.size ? (pl_out.values().next().value as Obj) : null;
  const act = new Map<string, [number, number | null, number | null][]>();
  for (const [m_, rows_] of ((src0 ?? {})["by_month"] ?? []) as [string, Obj[]][]) {
    for (const r_ of rows_) {
      if (r_["unit"] === "팀" && r_["cur"]) {
        const a = act.get(r_["target"]) ?? [];
        a.push([parseInt(m_.slice(5, 7), 10), r_["cur"]["revenue"], r_["cur"]["gp"]]);
        act.set(r_["target"], a);
      }
    }
  }
  R["budget_cmp"] = budgetCompare(d.budget_confirmed ?? null, ym, act);
  R["budget_conf_rows"] = ((d.budget_confirmed ?? {})[ym.slice(0, 4)] ?? null)?.rows ?? null;
  R["evid_month"] = d.evid_month ?? null;
  R["dep"] = depreciation(d.accounts ?? null, d.dep_manual ?? {}, ym);
  R["acct_year"] = accountYear(d.accounts ?? null, ym, d.accounts_problem ?? "");
  R["last_pay"] = lastPaydayOut(d.txns, R["payday"]);
  R["plan_gap_note"] = blankPlanGaps(R);
  R["risks"] = risks(R);
  R["totals_split"] = totalsSplit(R);   // 새 값 (파이썬에 없음)
}
