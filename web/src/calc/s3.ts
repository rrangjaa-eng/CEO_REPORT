// calc.py 288-463: 3. 프로젝트별 예산·지급 → R.s3
import { EXEC_STATES, isPrior } from "../model/data";
import { budgetDue, eventDate } from "../model/dates";
import { pyRound, pyStrip, sortedBy } from "../model/py";
import { ssum, ssumOrNone } from "../model/util";
import type { Ctx, Obj } from "./ctx";
import { BUDGET_REASONS, BUDGET_VAT, INTRANET_IN_FUNDS, OLD_STATE, blankProj, costRateOf, fromIntranet, isClosed } from "./projects";

const add = (a: number | null, b: number | null) => (a === null || b === null ? null : a + b);
const st = (x: unknown): string => pyStrip(x ? String(x) : "");

export function section3(ctx: Ctx): void {
  const { d, R, checks, asof, p0, p1 } = ctx;
  const rateSetting = R["settings_num"]["예산_원가율"];
  const proj = new Map<string, Obj>();
  for (const pid of d.project_order) {
    const p = d.projects[pid] as unknown as Obj;
    proj.set(pid, blankProj(p, costRateOf(p, rateSetting, (d.team_targets || {}) as Record<string, Obj>, asof)));
  }
  const ym_asof = asof.slice(0, 7);
  const later = new Map<string, number>();
  for (const p of (d.pl || []) as Obj[]) {
    if (p["unit"] === "프로젝트" && p["source"] === "WEHAGO" && (p["ym"] || "") > ym_asof && p["revenue"]) {
      const k = String(p["target"] ?? "").split(" ")[0]!;
      later.set(k, (later.get(k) ?? 0) + p["revenue"]);
    }
  }
  for (const P of proj.values()) {
    const l = later.get(String(P["id"]));
    if (P["recognized"] !== null && P["recognized"] !== undefined && l) {
      P["recognized_after"] = l;
      P["recognized"] -= l;
    }
  }
  const unlinked_exec: Obj[] = [];
  const prior_exec: Obj[] = [];
  for (const e of d.execs as unknown as Obj[]) {
    if (fromIntranet(e) && !INTRANET_IN_FUNDS) {
      if (proj.has(e["project"]) && !isPrior(e)) {
        const Pq = proj.get(e["project"])!;
        if (e["supply"] === null) Pq["intranet_req_unknown"] += 1;
        else Pq["intranet_req"] += e["supply"];
      }
      continue;
    }
    if (isPrior(e)) {
      prior_exec.push(e);
      continue;
    }
    if (!proj.has(e["project"])) {
      unlinked_exec.push(e);
      continue;
    }
    const P = proj.get(e["project"])!;
    P["lines"].push(e);
    P["line_n"][e["state"]] += 1;
    const amt = e["supply"];
    if (amt === null) {
      P["unknown_cost"] += 1;
      P["line_unknown"][e["state"]] += 1;
      if (e["state"] === "지급완료") {
        P["paid_cash"] = null;
        P["paid_cash_reason"] = "금액 미확인";
      }
      continue;
    }
    const s = e["state"];
    const inPeriod = e["date"] && p0 <= e["date"] && e["date"] <= p1;
    if (s === "지급완료") {
      P["paid"] += amt;
      P["paid_cash"] = e["vat"] !== null ? add(P["paid_cash"], amt + (e["vat"] || 0)) : null;
      if (e["vat"] === null) {
        P["vat_unknown"] += 1;
        P["paid_cash_reason"] = P["paid_cash_reason"] || "부가세 미확인";
      }
      if (inPeriod) P["paid_period"] += amt;
    } else if (s === "카드결제완료") {
      P["card_paid"] += amt;
      if (inPeriod) P["paid_period"] += amt;
    } else if (s === "요청미지급") {
      P["requested"] += amt;
    } else if (s === "카드사용미결제") {
      P["card_unpaid"] += amt;
    } else if (s === "집행계획미요청") {
      P["planned"] += amt;
    }
  }
  for (const P of proj.values()) {
    P["paid_total"] = P["paid"] + P["card_paid"];
    P["expected"] = P["paid_total"] + P["requested"] + P["card_unpaid"] + P["planned"];
    const b = P["budget"];
    P["remain"] = b === null || P["unknown_cost"] ? null : b - P["expected"];
    P["unrecognized"] = P["contract"] === null || P["recognized"] === null ? null : P["contract"] - P["recognized"];
    P["committed"] = P["unknown_cost"] || P["intranet_req_unknown"] ? null : P["expected"] + P["intranet_req"];
    P["closed"] = isClosed(P);
    P["remain_all"] = b === null || P["committed"] === null ? null : b - P["committed"];
    if (P["committed"] === null) P["cost_end"] = null;
    else if (P["closed"] || b === null) P["cost_end"] = P["committed"];
    else P["cost_end"] = Math.max(P["committed"], b);
    P["profit_end"] = P["contract"] === null || P["cost_end"] === null ? null : P["contract"] - P["cost_end"];
    if (P["contract"] === null || P["committed"] === null || (!P["closed"] && P["budget"] === null)) P["profit_now"] = null;
    else P["profit_now"] = P["contract"] - (P["closed"] ? P["committed"] : Math.max(P["committed"], P["budget"]));
  }
  const plist = [...proj.values()].filter((P) => st(P["state"]) !== OLD_STATE);
  const sumk = (xs: Obj[], k: string) => xs.reduce((s, P) => s + P[k], 0);
  const tot: Obj = {};
  for (const k of ["paid_period", "paid_total", "paid", "card_paid", "requested", "card_unpaid", "planned", "expected"]) tot[k] = sumk(plist, k);
  [tot["budget"], tot["budget_missing"]] = ssum(plist.map((P) => P["budget"]));
  [tot["estimate"], tot["estimate_missing"]] = ssumOrNone(plist.map((P) => P["estimate"]));
  const remain_known = plist.filter((P) => P["remain"] !== null).map((P) => P["remain"] as number);
  tot["remain"] = remain_known.reduce((s, v) => s + v, 0);
  tot["remain_excluded"] = plist.filter((P) => P["budget"] !== null && P["remain"] === null).length;
  if ((plist.length && tot["budget_missing"] === plist.length) || !remain_known.length) tot["remain"] = null;
  if (plist.length && tot["budget_missing"] === plist.length) tot["budget"] = null;
  tot["line_n"] = Object.fromEntries(EXEC_STATES.map((s) => [s, plist.reduce((a, P) => a + P["line_n"][s], 0)]));
  tot["line_unknown"] = Object.fromEntries(EXEC_STATES.map((s) => [s, plist.reduce((a, P) => a + P["line_unknown"][s], 0)]));
  [tot["paid_cash"], tot["paid_cash_unknown"]] = ssumOrNone(plist.filter((P) => P["line_n"]["지급완료"] > 0).map((P) => P["paid_cash"]));
  const reasons = new Set(plist.filter((P) => P["paid_cash"] === null && P["line_n"]["지급완료"] > 0).map((P) => P["paid_cash_reason"]));
  tot["paid_cash_reason"] = reasons.size > 1 ? "금액·부가세 미확인" : (reasons.size ? [...reasons][0] : "부가세 미확인");
  tot["unknown_cost"] = sumk(plist, "unknown_cost");
  const budgeted = plist.filter((P) => P["budget"] !== null);
  tot["expected_budgeted"] = sumk(budgeted, "expected");
  tot["paid_budgeted"] = sumk(budgeted, "paid_total");
  const n_show = R["settings_num"]["첫화면_프로젝트_표시수"] as number;
  const ranked = sortedBy(plist, (P) => [-(P["budget"] !== null ? P["budget"] : -1), -P["expected"]]);
  const shown = ranked.slice(0, n_show);
  const rest = ranked.slice(n_show);
  const [ue_tot] = ssum(unlinked_exec.map((e) => e["supply"]));
  const reason_n: Obj = {};
  for (const reason of BUDGET_REASONS) {
    const n = plist.filter((P) => P["budget_reason"] === reason).length;
    if (n) reason_n[reason] = n;
  }
  for (const P of plist) {
    P["remain_due"] = null;
    P["remain_cash"] = null;
    if (isClosed(P) || P["budget"] === null) continue;
    if (P["remain"] !== null && P["remain"] > 0) {
      P["remain_cash"] = pyRound(P["remain"] * (1 + BUDGET_VAT));
      P["remain_due"] = budgetDue(eventDate(P["event_date"]), asof);
    }
  }
  const remain_unknown = plist.filter((P) => P["budget"] !== null && P["remain"] === null && !isClosed(P));
  const by_team = new Map<string, Obj>();
  for (const P of sortedBy(plist, (P) => P["team"])) {
    let t = by_team.get(P["team"]);
    if (!t) {
      t = { team: P["team"], n: 0, budget: 0, no_budget: 0, expected: 0, remain: 0, remain_unknown: 0, planned_pay: 0 };
      by_team.set(P["team"], t);
    }
    t["n"] += 1;
    t["expected"] += P["expected"];
    if (P["budget"] === null) {
      t["no_budget"] += 1;
      continue;
    }
    t["budget"] += P["budget"];
    if (P["remain"] === null) t["remain_unknown"] += 1;
    else t["remain"] += P["remain"];
    t["planned_pay"] += P["remain_cash"] || 0;
  }
  for (const t of by_team.values()) {
    if (t["n"] === t["no_budget"]) t["budget"] = t["remain"] = null;
    else if (t["remain_unknown"] === t["n"] - t["no_budget"]) t["remain"] = null;
  }
  R["s3"] = {
    projects: plist, ranked, shown, rest, total: tot,
    remain_unknown, by_team: [...by_team.values()],
    unlinked: unlinked_exec, unlinked_total: ue_tot,
    prior: prior_exec, prior_total: ssum(prior_exec.map((e) => e["supply"]))[0],
    cost_rate: rateSetting, no_budget_reasons: reason_n,
    team_rate_n: plist.filter((P) => P["cost_rate_source"] === "팀 목표" && P["cost_rate"] !== rateSetting).length,
  };
  const linked_lines = plist.reduce((s, P) => s + P["lines"].length, 0);
  const old_lines = [...proj.values()].filter((P) => st(P["state"]) === OLD_STATE).reduce((s, P) => s + P["lines"].length, 0);
  const compare_only = INTRANET_IN_FUNDS ? 0 : (d.execs as unknown as Obj[]).filter((e) => fromIntranet(e)).length;
  const counted = linked_lines + old_lines + unlinked_exec.length + compare_only + prior_exec.length;
  checks.push(["프로젝트집행 줄 수 = 프로젝트 반영 줄 + 미연결 줄" + (compare_only ? " + 인트라넷 비교만 줄" : "")
    + (prior_exec.length ? " + 지난해 참고 줄" : "") + (old_lines ? " + 예전 인트라넷 끝난 행사 줄" : ""),
    d.execs.length, counted, d.execs.length === counted]);
  const shown_exp = sumk(shown, "expected") + sumk(rest, "expected");
  checks.push(["첫 화면 표시 + 나머지 프로젝트 예상총집행 = 전체 합계", shown_exp, tot["expected"], shown_exp === tot["expected"]]);
  ctx.proj = proj;
  ctx.plist = plist;
}
