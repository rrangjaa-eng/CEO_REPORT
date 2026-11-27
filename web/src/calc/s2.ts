// calc.py 절 2 (538-756): 앞으로의 입금·지급 일정 — events, intranet_only, fundplan, tax, tax_missing, events, debts, two_source, s2.
// 바꿀 것 F9: 남은 예산은 예상 지출에 그대로 두고, 따로 셀 수 있게 R.budget_left 를 더한다 (아래 budgetLeft).
import { addDays, addMonths, monthEnd, parseIso, payFriday, periodEnds, daysBetween, type IsoDate } from "../model/dates";
import { floorDiv, pyInt, sortedBy } from "../model/py";
import { d2s, ssum, won } from "../model/util";
import { isPrior } from "../model/data";
import { BUDGET_IN_FUNDS, INTRANET_IN_FUNDS } from "./projects";
import type { Ctx, Obj } from "./ctx";
import { applyFundplan, fillProjects, type FundEvent, type PlanRow, type Txn, type ExecRow } from "./fundplan";
import { mergeTax, type TaxRow } from "./tax";
import { compareDebts, type DebtRow } from "./debts";
import { attach as attachDetails, type DetailRow } from "./paydetail";
import { attach as attachReqs, type ReqRow } from "./payreq";
import { availablePeriods, countsIn, markMust, twoSources } from "./schedule";

const isNone = (x: unknown) => x === null || x === undefined;

export function section2(ctx: Ctx): void {
  const { d, asof, R, invs, ar_rows, in_missing, checks } = ctx;
  const pick = ctx.pick as IsoDate | null | undefined;
  let events: Obj[] = [];
  for (const s of d.schedule as unknown as Obj[]) {
    events.push({
      date: s["date"], io: s["io"] === "입금" ? "in" : "out", amount: s["amount"],
      firm: s["firm"], cat: s["cat"], desc: s["vendor"] || s["memo"], basis: s["basis"],
      project: s["project"], source: "자금일정", vendor_code: s["vendor_code"] || "",
    });
  }
  for (const v of ar_rows) {
    events.push({
      date: v["due"], io: "in", amount: v["outstanding"], firm: v["due_firm"],
      cat: "수금(발행 계산서)", desc: v["client"], basis: "계산서 " + (v["date"] || ""),
      project: v["project"], source: "계산서",
      inv_key: v["date"] ? [v["client"], v["date"]] : null,
    });
  }
  for (const v of invs) {
    if (v["kind"] === "환불" && !isNone(v["outstanding"]) && v["outstanding"] < 0 && !v["paid_date"]) {
      events.push({
        date: v["due"], io: "out", amount: -v["outstanding"], firm: v["due_firm"],
        cat: "환불", desc: v["client"], basis: "계산서 환불", project: v["project"], source: "계산서",
      });
    }
  }
  const skippedRequests: (number | null)[] = [], skippedBudget: number[] = [];
  for (const e of d.execs as unknown as Obj[]) {
    if (isPrior(e)) continue;
    if (e["state"] === "요청미지급" && !INTRANET_IN_FUNDS) {
      skippedRequests.push(isNone(e["supply"]) ? null : e["supply"] + (e["vat"] || 0));
      continue;
    }
    if (e["state"] === "요청미지급" || e["state"] === "집행계획미요청") {
      const amt = isNone(e["supply"]) ? null : e["supply"] + (e["vat"] || 0);
      events.push({
        date: e["date"], io: "out", amount: amt,
        firm: e["firm"] && e["state"] === "요청미지급",
        cat: "프로젝트 " + (e["state"] === "요청미지급" ? "지급요청" : "집행계획"),
        desc: e["vendor"] || e["item"], basis: e["basis"], project: e["project"],
        source: "프로젝트집행", vat_unknown: isNone(e["vat"]),
      });
    }
  }
  for (const a of R["s1"]["accounts"] as Obj[]) {
    if (a["release"] && a["release"] > asof && a["restricted"]) {
      events.push({
        date: a["release"], io: "in", amount: a["restricted"], firm: !a["release_guess"],
        cat: "사용제한 해제", desc: a["account"] + (a["reason"] ? " · " + a["reason"] : ""),
        basis: "계좌잔액.csv 제한해제일", project: "", source: "계좌잔액",
      });
    }
  }
  for (const P of R["s3"]["projects"] as Obj[]) {
    if (P["remain_cash"] && !(INTRANET_IN_FUNDS || BUDGET_IN_FUNDS)) {
      skippedBudget.push(P["remain_cash"]);
      continue;
    }
    if (P["remain_cash"]) {
      let days: (IsoDate | null)[] = [P["remain_due"]];
      if (!isNone(P["remain_due"])) {
        days = [];
        let f = payFriday(asof);
        while (f <= P["remain_due"]) {
          days.push(f);
          f = addDays(f, 7);
        }
        if (!days.length) days = [P["remain_due"]];
      }
      const n = days.length;
      const each = floorDiv(P["remain_cash"], n);
      days.forEach((day, k) => {
        const amt = k < n - 1 ? each : P["remain_cash"] - each * (n - 1);
        const tail = n > 1 ? `, ${d2s(days[0])}~${d2s(days[n - 1])} 매주 금요일 나눔 (${k + 1}/${n})`
          : day ? ", 행사일 다음 달 말 금요일" : "";
        events.push({
          date: day, io: "out", amount: amt, firm: false,
          cat: "프로젝트 남은 예산", desc: P["name"],
          basis: `남은 예산 ${won(P["remain"])}원 + 부가세 10%${tail}`,
          project: P["id"], source: "남은 예산", split: [k + 1, n],
        });
      });
    }
  }
  R["intranet_only"] = {
    requests: [skippedRequests.length, skippedRequests.reduce<number>((t, x) => t + (x ? x : 0), 0)],
    budget: [skippedBudget.length, skippedBudget.reduce((t, x) => t + x, 0)],
  };
  const known = (R["s1"]["accounts"] as Obj[]).filter((a) => !isNone(a["balance"])).map((a) => a["date"] as IsoDate);
  const minKnown = known.length ? known.reduce((a, b) => (b < a ? b : a)) : null;
  const staleLim = Math.min(pyInt(Number(R["settings_num"]["위험_자료경과일"] || 7)), 7);
  [events, R["fundplan"]] = applyFundplan(events as FundEvent[], (d.fundplan ?? null) as unknown as PlanRow[] | null, asof,
    staleLim, d.fundplan_problem || "", minKnown, d.txns as unknown as Txn[]) as [Obj[], Obj | null];
  if (R["fundplan"] && typeof R["fundplan"] === "object") {
    const lim = staleLim;
    const at = d.fundplan_received_at || {};
    R["fundplan"]["received"] = (d.fundplan_received || []).filter((m) => isNone(at[m]) || daysBetween(at[m]!, asof) <= lim);
  }
  fillProjects(events as FundEvent[], d.execs as unknown as ExecRow[]);
  [events, R["tax"]] = mergeTax(events as FundEvent[], (d.tax ?? null) as unknown as TaxRow[] | null, asof, minKnown) as [Obj[], Obj[]];
  R["tax_missing"] = isNone(d.tax);
  markMust(events, R["tax"]);
  attachDetails(events, (d.pay_details || []) as DetailRow[]);
  attachReqs(events, (d.pay_requests || []) as ReqRow[]);
  R["events"] = events;
  ctx.events = events;
  R["debts"] = compareDebts((d.debts ?? null) as unknown as DebtRow[] | null, events as FundEvent[], asof);
  R["two_source"] = twoSources(events, asof);

  const payday = R["payday"] as IsoDate;
  const weekEnds = [0, 1, 2, 3].map((i) => addDays(payday, 7 * i));
  const buckets: Obj[] = [];
  let s = addDays(asof, 1);
  weekEnds.forEach((we, i) => {
    buckets.push({ label: `${i + 1}주차`, from: s, to: we, type: "week" });
    s = addDays(we, 1);
  });
  const horizon = monthEnd(addMonths(asof, 6));
  const cut3 = monthEnd(addMonths(asof, 3));
  while (s <= horizon) {
    const me = monthEnd(s);
    const e_ = me < horizon ? me : horizon;
    const [y, m, dd] = parseIso(s);
    buckets.push({ label: `${y}년 ${m}월` + (dd !== 1 ? " (일부)" : ""), from: s, to: e_, type: "month", within3: e_ <= cut3 });
    s = addDays(e_, 1);
  }
  for (const b of buckets) for (const k of ["in_firm", "in_est", "out_firm", "out_est"]) b[k] = 0;
  const undated: Obj[] = [], past: Obj[] = [], beyond: Obj[] = [], amountUnknown: Obj[] = [], lateIn: Obj[] = [];
  for (let ev of events) {
    if (isNone(ev["amount"])) { amountUnknown.push(ev); continue; }
    if (isNone(ev["date"])) { undated.push(ev); continue; }
    if (ev["date"] <= asof) {
      if (ev["io"] !== "in") { past.push(ev); continue; }
      ev = { ...ev, orig_date: ev["date"], date: payday, firm: false, must: false, late_in: true,
        basis: (ev["basis"] || "") + `, 예정일 ${ev["date"]} 지난 입금 → 이번 주 예상 입금` };
      lateIn.push(ev);
    }
    if (ev["date"] > horizon) { beyond.push(ev); continue; }
    for (const b of buckets) {
      if (b["from"] <= ev["date"] && ev["date"] <= b["to"]) {
        b[(ev["io"] === "in" ? "in_" : "out_") + (countsIn(ev, "firm") ? "firm" : "est")] += ev["amount"];
        break;
      }
    }
  }
  let startCash: number | null = R["s1"]["available"];
  const outMissing = [...(d.out_missing || [])];
  if (outMissing.length) startCash = null;
  let balF = startCash, balA = startCash;
  for (const b of buckets) {
    if (startCash === null || isNone(startCash)) { b["bal_firm"] = b["bal_all"] = null; continue; }
    balF = (balF as number) + b["in_firm"] - b["out_firm"];
    balA = (balA as number) + b["in_firm"] + b["in_est"] - b["out_firm"] - b["out_est"];
    b["bal_firm"] = balF;
    b["bal_all"] = balA;
  }
  const dated = sortedBy([...events.filter((ev) => !isNone(ev["amount"]) && ev["date"] && asof < ev["date"] && ev["date"] <= horizon),
    ...lateIn], (x) => x["date"] as string);
  const mins: Obj = {};
  for (const mode of ["firm", "all"]) {
    if (isNone(startCash)) { mins[mode] = [null, null]; continue; }
    let bal = startCash as number, low = startCash as number, lowD: IsoDate = asof;
    const daily = new Map<string, number>();
    for (const ev of dated) {
      if (!countsIn(ev, mode)) continue;
      daily.set(ev["date"], (daily.get(ev["date"]) ?? 0) + (ev["io"] === "in" ? ev["amount"] : -ev["amount"]));
    }
    for (const day of [...daily.keys()].sort()) {
      bal += daily.get(day)!;
      if (bal < low) { low = bal; lowD = day; }
    }
    mins[mode] = [low, lowD];
  }
  const four = buckets.slice(0, 4);
  const minCash = R["settings_num"]["위험_최소보유현금"] ?? null;
  const ends: [string, IsoDate][] = periodEnds(R["kind"], asof, payday);
  if (!isNone(pick)) ends.push(["지정일", pick as IsoDate]);
  const periods = availablePeriods(isNone(startCash) ? null : startCash, dated, ends, minCash, asof);
  if (!isNone(pick)) periods[periods.length - 1]!["pick"] = true;
  const sumIo = (all: Obj[]) => {
    const out: Obj = {};
    for (const io of ["in", "out"]) {
      const evs = all.filter((ev) => ev["io"] === io);
      const [total, unknown] = ssum(evs.map((ev) => ev["amount"]));
      out[io] = [evs.length && unknown === evs.length ? null : total, evs.length, unknown];
    }
    return out;
  };
  const pastSum = sumIo([...past, ...amountUnknown.filter((ev) => !isNone(ev["date"]) && ev["date"] <= asof)]);
  const undatedSum = sumIo([...undated, ...amountUnknown.filter((ev) => isNone(ev["date"]))]);
  const schedVat = dated.filter((ev) => ev["vat_unknown"]);
  const outUnk = amountUnknown.filter((ev) => ev["io"] === "out" && !isNone(ev["date"]) && asof < ev["date"] && ev["date"] <= horizon);
  const lastTo = four[four.length - 1]!["to"] as IsoDate;
  const sumK = (xs: Obj[], k: string) => xs.reduce((t, b) => t + b[k], 0);
  R["s2"] = {
    start: R["s1"]["available"], out_missing: outMissing, in_missing, start_unknown: R["s1"]["bal_unknown"], buckets, undated, past, beyond,
    amount_unknown: amountUnknown, min: mins, horizon, pick_beyond: !isNone(pick) && (pick as IsoDate) > horizon,
    periods, min_cash: minCash, dated,
    in4_firm: sumK(four, "in_firm"), in4_est: sumK(four, "in_est"),
    out4_firm: sumK(four, "out_firm"), out4_est: sumK(four, "out_est"),
    undated_in: undatedSum["in"][0], undated_in_n: undatedSum["in"][1], undated_in_unknown: undatedSum["in"][2],
    undated_out: undatedSum["out"][0], undated_out_n: undatedSum["out"][1],
    undated_out_unknown: undatedSum["out"][2],
    past_in: pastSum["in"][0], past_in_n: pastSum["in"][1], past_in_unknown: pastSum["in"][2],
    late_in: lateIn, late_in_sum: sumK(lateIn, "amount"), late_in_n: lateIn.length,
    past_out: pastSum["out"][0], past_out_n: pastSum["out"][1], past_out_unknown: pastSum["out"][2],
    vat_unknown_n: schedVat.length,
    vat_unknown_n4: schedVat.filter((ev) => ev["date"] <= lastTo).length,
    vat_unknown_firm_n: schedVat.filter((ev) => ev["firm"]).length,
    out_unknown_n: outUnk.length, out_unknown_firm_n: outUnk.filter((ev) => ev["firm"]).length,
    out_unknown_n4: outUnk.filter((ev) => ev["date"] <= lastTo).length,
  };
  // 바꿀 것 F9 (사용자 결정 2026-11-27): 남은 예산은 예상 지출에 그대로 두고, 대표 보고에서 따로 보이게 합계·건수를 둔다.
  R["budget_left"] = budgetLeft(events, asof, horizon);

  const allAmt = events.filter((e) => !isNone(e["amount"])).reduce((t, e) => t + e["amount"], 0);
  let parts = 0;
  for (const b of buckets) for (const k of ["in_firm", "in_est", "out_firm", "out_est"]) parts += b[k];
  parts += [...undated, ...past, ...beyond].reduce((t, e) => t + e["amount"], 0);
  checks.push(["예정 일정 합계 = 기간별 + 날짜 없음 + 지난 날짜 + 기간 밖", parts, allAmt, parts === allAmt]);
}

/** F9: 일정(R.events) 중 '남은 예산' 줄로, 날짜가 기준일 뒤 ~ 일정 끝(horizon, 6개월 뒤 말일) 안인 것 — R.s2.dated 에 들어가
 * 예상 지출(spend·all)에 더해지는 바로 그 줄들. amount = 금액을 아는 줄의 합, n = 그 줄 수, unknown_n = 같은 기간 안 금액 미확인 줄 수. */
export function budgetLeft(events: Obj[], asof: IsoDate, horizon: IsoDate): { amount: number; n: number; unknown_n: number } {
  let amount = 0, n = 0, unknown = 0;
  for (const e of events) {
    if (e["source"] !== "남은 예산" || e["io"] !== "out" || isNone(e["date"]) || !(asof < e["date"] && e["date"] <= horizon)) continue;
    if (isNone(e["amount"])) unknown += 1;
    else { amount += e["amount"]; n += 1; }
  }
  return { amount, n, unknown_n: unknown };
}
