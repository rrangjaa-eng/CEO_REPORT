// calc.py 의 모듈 수준 상수·도움 함수 (1-145, 1103-1335 중 절 1·3·5 와 다른 절이 함께 쓰는 것). 이름은 파이썬 이름의 camelCase.
import type { IsoDate } from "../model/dates";
import { daysBetween, eventDate } from "../model/dates";
import { EXEC_STATES } from "../model/data";
import { cmpStr, pyFixed, pyRound, pyStrip, sortedBy } from "../model/py";
import { isBlank, pyStr, ssum } from "../model/util";
import type { Obj } from "./ctx";

export const INTRANET_IN_FUNDS = false;
export const BUDGET_IN_FUNDS = true;
export const BUDGET_VAT = 0.1;
export const DONE_STATES = ["완료", "완료(예전 인트라넷)"] as const;
export const CEO_APPROVED = "대표이사";
export const OLD_STATE = "완료(예전 인트라넷)";

export const NUM_SETTINGS = ["첫화면_프로젝트_표시수", "위험_최소보유현금", "위험_미수경과일", "위험_미발행경과일", "위험_자료경과일",
  "위험_예산초과율", "예산_원가율"] as const;
export const BUDGET_REASONS = ["사전견적 없음", "사전견적 0원 또는 음수", "사전견적 금액 해석 불가", "원가율 설정 오류"] as const;
export const SETTING_LABELS: Record<string, string> = {
  "첫화면_프로젝트_표시수": "첫화면_프로젝트_표시수", "위험_최소보유현금": "최소 보유현금",
  "위험_미수경과일": "미수 경과일 기준", "위험_미발행경과일": "미발행 경과일 기준",
  "위험_자료경과일": "자료 경과일 기준", "위험_예산초과율": "예산 초과율 기준", "예산_원가율": "예산_원가율",
};

/** (x or "").strip() */
const st = (x: unknown): string => pyStrip(x ? String(x) : "");

/** calc.from_intranet */
export function fromIntranet(e: Obj): boolean {
  return e["state"] === "요청미지급" && (e["basis"] ? pyStr(e["basis"]) : "").startsWith("지급요청");
}

/** calc.is_closed */
export function isClosed(P: Obj): boolean {
  return (DONE_STATES as readonly string[]).includes(st(P["state"])) || st(P["approval"]) === CEO_APPROVED;
}

/** calc.revenue_basis */
export function revenueBasis(P: Obj): number | null {
  if (st(P["approval"]) === CEO_APPROVED && P["quote"] !== null && P["quote"] !== undefined) return P["quote"];
  return P["estimate"] ?? null;
}

/** calc.event_unissued */
export function eventUnissued(invProj: Obj[], asof: IsoDate, inMissing: unknown[]): Obj {
  const rows: Obj[] = [], unknown: Obj[] = [];
  for (const x of invProj) {
    const P = x["P"];
    const ev = eventDate(P["event_date"]);
    if (ev === null) {
      unknown.push({ P, why: st(P["event_date"]) ? "행사일 해석 불가" : "행사일 없음" });
      continue;
    }
    if (ev >= asof) continue;
    const base = revenueBasis(P);
    if (base === null) {
      unknown.push({ P, why: "사전견적 없음" });
      continue;
    }
    if (inMissing.length || x["issued"] === null || x["issued"] === undefined) {
      unknown.push({ P, why: "발행금액 미확인" });
      continue;
    }
    if (x["issued_unknown"]) {
      unknown.push({ P, why: `발행금액 일부 미확인 (${x["issued_unknown"]}장)` });
      continue;
    }
    const left = base - x["issued"];
    if (left > 0) {
      rows.push({ P, event: ev, days: daysBetween(ev, asof), estimate: base, quoted: base !== (P["estimate"] ?? null),
                  issued: x["issued"], unissued: left });
    }
  }
  const sorted = sortedBy(rows, (y) => [-y["days"], y["P"]["id"]]);
  return { rows: sorted, unknown, missing: inMissing.length > 0,
           total: inMissing.length ? null : sorted.reduce((s, y) => s + y["unissued"], 0) };
}

/** calc.with_vat: int(round(supply * 1.1)) */
export function withVat(supply: number): number {
  return pyRound(supply * 1.1);
}

/** calc.unissued_due */
export function unissuedDue(E: Obj): number | null {
  if (E["missing"] || E["total"] === null || E["total"] === undefined) return null;
  return ((E["rows"] || []) as Obj[]).reduce((s, y) => s + withVat(y["unissued"]), 0);
}

/** calc.left_basis */
export function leftBasis(P: Obj): number | null {
  const v = revenueBasis(P);
  return v !== null ? v : (P["contract"] ?? null);
}

/** calc.revenue_left */
export function revenueLeft(P: Obj): number | null {
  const base = leftBasis(P);
  const rec = P["recognized"];
  if (base === null || rec === null || rec === undefined) return null;
  return Math.max(base - rec, 0);
}

/** calc.year_revenue_left */
export function yearRevenueLeft(projects: Iterable<Obj>, year: string | number, team: string | null = null): Obj[] {
  const out: Obj[] = [];
  const y = Number(year);
  for (const P of projects) {
    if (st(P["state"]) === OLD_STATE) continue;
    if (team !== null && st(P["team"]) !== team) continue;
    const ev = eventDate(P["event_date"]);
    if (ev === null || Number(ev.slice(0, 4)) > y) continue;
    if (leftBasis(P) === null) continue;
    out.push({ P, event: ev, left: revenueLeft(P), prior: Number(ev.slice(0, 4)) < y });
  }
  return out;
}

/** calc.expected_revenue */
export function expectedRevenue(invProj: Obj[], asof: IsoDate, _inMissing: unknown[]): Obj {
  const groups: Record<string, [number, number]> = { past: [0, 0], this_year: [0, 0], later: [0, 0] };
  let estTotal = 0, estN = 0, noDate = 0, unknownLeft = 0, yearEst = 0, yearN = 0, quotedN = 0;
  const byTeam: Record<string, Obj> = {};
  const asofYear = asof.slice(0, 4);
  for (const x of invProj) {
    const P = x["P"];
    const base = leftBasis(P);
    if (base === null) continue;
    if (base === (P["quote"] ?? null) && base !== (P["estimate"] ?? null) && revenueBasis(P) !== null) quotedN += 1;
    estTotal += base;
    estN += 1;
    const ev = eventDate(P["event_date"]);
    if (ev === null) {
      noDate += 1;
      continue;
    }
    if (ev.slice(0, 4) === asofYear) {
      yearEst += base;
      yearN += 1;
    }
    const left = revenueLeft(P);
    if (left === null) {
      unknownLeft += 1;
      continue;
    }
    if (left <= 0) continue;
    const g = ev < asof ? "past" : (ev.slice(0, 4) === asofYear ? "this_year" : "later");
    groups[g]![0] += left;
    groups[g]![1] += 1;
    if (g !== "later") {
      const k = st(P["team"]);
      const t = byTeam[k] ?? (byTeam[k] = { past: 0, this_year: 0, n: 0 });
      t[g] += left;
      t["n"] += 1;
    }
  }
  return { missing: false, est_total: estTotal, est_n: estN,
           past: groups["past"]![0], past_n: groups["past"]![1],
           this_year: groups["this_year"]![0], this_year_n: groups["this_year"]![1],
           later: groups["later"]![0], later_n: groups["later"]![1],
           no_date_n: noDate, unknown_n: unknownLeft, year_est: yearEst, year_n: yearN, by_team: byTeam,
           quoted_n: quotedN };
}

const dateKey = (v: Obj): [boolean, string] => [v["date"] === null || v["date"] === undefined, v["date"] || ""];

/** calc._net_credits: 취소·수정 계산서의 음수 미수를 같은 프로젝트(·거래처)의 남은 미수에서 뺀다 (invs 를 고침). */
export function netCredits(invs: Obj[]): void {
  for (const c of invs) if (!("netted" in c)) c["netted"] = 0;
  const pos = (v: Obj) => v["outstanding"] !== null && v["outstanding"] !== undefined && v["outstanding"] > 0;
  for (const c of invs) {
    if (!(c["kind"] === "취소" || c["kind"] === "수정") || c["outstanding"] === null || c["outstanding"] === undefined
        || c["outstanding"] >= 0) continue;
    const credit = -c["outstanding"];
    if (!c["project"] && !c["client"]) {
      c["credit_applied"] = 0;
      c["credit_left"] = credit;
      continue;
    }
    const cands = invs.filter((v) => v !== c && v["kind"] !== "환불" && v["project"] === c["project"] && pos(v)
      && (c["project"] || c["client"] === v["client"])
      && (!c["client"] || !v["client"] || c["client"] === v["client"]));
    const exact = cands.filter((v) => v["outstanding"] === credit).slice(0, 1);
    const rest = sortedBy(cands.filter((v) => !exact.some((x) => x === v)), dateKey);
    let left = credit;
    for (const v of [...exact, ...rest]) {
      if (left <= 0) break;
      const take = Math.min(left, v["outstanding"]);
      v["outstanding"] -= take;
      v["netted"] += take;
      left -= take;
    }
    if (left > 0 && c["client"]) {
      const more = sortedBy(invs.filter((v) => v !== c && v["kind"] !== "환불" && v["client"] === c["client"] && pos(v)), dateKey);
      for (const v of more) {
        if (left <= 0) break;
        const take = Math.min(left, v["outstanding"]);
        v["outstanding"] -= take;
        v["netted"] += take;
        left -= take;
      }
    }
    c["credit_applied"] = credit - left;
    c["credit_left"] = left;
  }
}

/** calc._cost_rate_of → [원가율, '팀 목표'|'기본'] */
export function costRateOf(p: Obj, dflt: number | null, targets: Record<string, Obj>, asof: IsoDate): [number | null, string] {
  if (dflt === null || dflt === undefined) return [null, "기본"];
  const ev = eventDate(p["event_date"]);
  const year = String(Number((ev || asof).slice(0, 4)));
  const key = `${year}|${st(p["team"])}`;
  const t = Object.prototype.hasOwnProperty.call(targets, key) ? targets[key] : undefined;
  if (t && t["rate"] !== null && t["rate"] !== undefined && t["rate"] >= 0 && t["rate"] < 100) {
    return [Number(pyFixed(1 - t["rate"] / 100.0, 6)), "팀 목표"];
  }
  return [dflt, "기본"];
}

/** calc._blank_proj */
export function blankProj(p: Obj, rateIn: [number | null, string] | number | null): Obj {
  const P: Obj = { ...p };
  const [rate, src] = Array.isArray(rateIn) ? rateIn : [rateIn, "기본"];
  P["cost_rate_source"] = src;
  P["cost_rate"] = rate;
  const zeros = () => Object.fromEntries(EXEC_STATES.map((s) => [s, 0]));
  Object.assign(P, {
    lines: [], paid: 0, paid_cash: 0, paid_cash_reason: null, vat_unknown: 0, paid_period: 0, card_paid: 0,
    requested: 0, card_unpaid: 0, planned: 0, unknown_cost: 0, intranet_req: 0, intranet_req_unknown: 0,
    line_n: zeros(), line_unknown: zeros(),
  });
  const est = P["estimate"];
  P["budget"] = null;
  P["budget_reason"] = null;
  if (est === null || est === undefined) {
    P["budget_reason"] = isBlank(P["estimate_raw"]) ? "사전견적 없음" : "사전견적 금액 해석 불가";
  } else if (est <= 0) {
    P["budget_reason"] = "사전견적 0원 또는 음수";
  } else if (rate === null) {
    P["budget_reason"] = "원가율 설정 오류";
  } else {
    P["budget"] = pyRound(est * rate);
  }
  return P;
}

/** calc._pl_sum */
export function plSum(rows: Obj[] | null | undefined): Obj | null {
  if (!rows || !rows.length) return null;
  const [rev, ru] = ssum(rows.map((p) => p["revenue"]));
  const [dc, du] = ssum(rows.map((p) => p["direct"]));
  const [cc, cu] = ssum(rows.map((p) => p["common"]));
  const hasCommon = rows.some((p) => p["common"] !== null && p["common"] !== undefined);
  const gp = ru || du ? null : rev - dc;
  const np = gp === null || cu || !hasCommon ? null : gp - cc;
  return { revenue: ru ? null : rev, direct: du ? null : dc, common: hasCommon && !cu ? cc : null,
           gp, np, provisional: rows.some((p) => p["provisional"]),
           months: [...new Set(rows.map((p) => p["ym"] as string))].sort(cmpStr) };
}
