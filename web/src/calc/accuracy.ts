// 예상 대비 실제 (새 기능, 파이썬 원본 없음).
// 지난 보고가 낸 예상 입출금(ForecastRecord)을 남겨 두었다가, 다음 보고 때 그 사이 실제 통장 입출금과 비교한다.
// 순수 함수만 둔다: 기록을 어디에 저장할지는 화면·저장 쪽 일이다.
import { TRANSFER } from "../model/data";
import { addDays, daysBetween, type IsoDate } from "../model/dates";
import { normVendor } from "../model/vendor";
import type { Obj } from "./ctx";
import { countsIn } from "./schedule";

/** 예상 한 줄. firm = 확정 잔액에 넣는 줄(확정이거나 꼭 나갈 정기 지출). amount null = 금액 미확인(U1). */
export interface ForecastRow {
  date: IsoDate; io: "in" | "out"; amount: number | null; firm: boolean; source: string; desc: string; cat: string;
}
/** 보고 한 번의 예상: 기준일, 시작 자금(쓸 수 있는 돈), 기준일 뒤 RECORD_DAYS 일 안의 일정. */
export interface ForecastRecord { asof: IsoDate; start: number | null; rows: ForecastRow[] }
export interface ActualTxn { date: IsoDate; io: string; amount: number; vendor?: string; cat?: string }

export const RECORD_DAYS = 28;

const isNone = (x: unknown) => x === null || x === undefined;

/** compute 결과 R 에서 예상 기록을 뽑는다. 보고의 주차별 합계(R.s2.buckets)와 같은 일정에서 뽑는다. */
export function forecastRecord(R: Obj): ForecastRecord {
  const asof = R["asof"] as IsoDate;
  const end = addDays(asof, RECORD_DAYS);
  const s2 = R["s2"] as Obj;
  const unknown = (s2["amount_unknown"] as Obj[]).filter((ev) => !isNone(ev["date"]) && asof < ev["date"]);
  const rows: ForecastRow[] = [...(s2["dated"] as Obj[]), ...unknown]
    .filter((ev) => ev["date"] <= end)
    .map((ev) => ({
      date: ev["date"], io: ev["io"] === "in" ? "in" : "out", amount: isNone(ev["amount"]) ? null : ev["amount"],
      firm: countsIn(ev, "firm"), source: String(ev["source"] ?? ""), desc: String(ev["desc"] ?? ""), cat: String(ev["cat"] ?? ""),
    }));
  rows.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  return { asof, start: isNone(s2["start"]) ? null : s2["start"], rows };
}

export interface SideAccuracy { firm: number; all: number; actual: number; diff_firm: number; diff_all: number; unknown_n: number }
export interface Accuracy {
  from: IsoDate; to: IsoDate;
  in: SideAccuracy; out: SideAccuracy;
  /** 끝 잔액: 시작 + 입금 − 출금. 실제 값을 모르거나 예상에 미확인 금액이 있으면 null. */
  end: { firm: number | null; all: number | null; actual: number | null; diff_firm: number | null; diff_all: number | null };
  hit: { plan: ForecastRow; actual: ActualTxn; days: number }[];
  not_happened: ForecastRow[];
  unplanned: ActualTxn[];
  by_source: { source: string; io: "in" | "out"; planned: number; n: number; happened: number; hit_n: number }[];
}

/** 지난 예상(prev)과 그 뒤 실제 입출금(txns)을 prev.asof 다음 날 ~ upto 기간으로 비교한다. 차이 = 실제 − 예상.
 * endActual = upto 날의 실제 쓸 수 있는 돈(모르면 null). */
export function compareForecast(prev: ForecastRecord, txns: ActualTxn[], upto: IsoDate, endActual: number | null): Accuracy {
  const from = addDays(prev.asof, 1);
  const plan = prev.rows.filter((r) => from <= r.date && r.date <= upto)
    .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  const actual = txns.filter((t) => from <= t.date && t.date <= upto && t.cat !== TRANSFER);
  const side = (io: "in" | "out"): SideAccuracy => {
    const rows = plan.filter((r) => r.io === io);
    const known = rows.filter((r) => r.amount !== null);
    const firm = known.filter((r) => r.firm).reduce((t, r) => t + (r.amount as number), 0);
    const all = known.reduce((t, r) => t + (r.amount as number), 0);
    const act = actual.filter((t) => t.io === (io === "in" ? "입금" : "출금")).reduce((t, x) => t + x.amount, 0);
    return { firm, all, actual: act, diff_firm: act - firm, diff_all: act - all, unknown_n: rows.length - known.length };
  };
  const sin = side("in"), sout = side("out");
  const knownAll = prev.start !== null && !sin.unknown_n && !sout.unknown_n;
  const endFirm = knownAll ? (prev.start as number) + sin.firm - sout.firm : null;
  const endAll = knownAll ? (prev.start as number) + sin.all - sout.all : null;

  const used = new Set<number>();
  const hitOf = new Map<ForecastRow, number>();
  const cands = (r: ForecastRow) => actual.map((t, i) => [t, i] as const)
    .filter(([t, i]) => !used.has(i) && t.amount === r.amount && t.io === (r.io === "in" ? "입금" : "출금"));
  const nearest = (r: ForecastRow, xs: (readonly [ActualTxn, number])[]) =>
    xs.reduce<readonly [ActualTxn, number] | null>((b, x) =>
      b === null || Math.abs(daysBetween(r.date, x[0].date)) < Math.abs(daysBetween(r.date, b[0].date)) ? x : b, null);
  for (const sameName of [true, false]) {
    for (const r of plan) {
      if (r.amount === null || hitOf.has(r)) continue;
      const key = normVendor(r.desc);
      const best = nearest(r, cands(r).filter(([t]) => !sameName || (!!key && normVendor(t.vendor ?? "") === key)));
      if (best) { used.add(best[1]); hitOf.set(r, best[1]); }
    }
  }
  const hit = plan.filter((r) => hitOf.has(r)).map((r) => {
    const t = actual[hitOf.get(r)!]!;
    return { plan: r, actual: t, days: daysBetween(r.date, t.date) };
  });
  const groups = new Map<string, Accuracy["by_source"][number]>();
  for (const r of plan) {
    if (r.amount === null) continue;
    const k = r.source + "\u0000" + r.io;
    const g = groups.get(k) ?? { source: r.source, io: r.io, planned: 0, n: 0, happened: 0, hit_n: 0 };
    groups.set(k, g);
    g.planned += r.amount;
    g.n += 1;
    if (hitOf.has(r)) { g.happened += r.amount; g.hit_n += 1; }
  }
  const diff = (a: number | null, b: number | null) => (a === null || b === null ? null : a - b);
  return {
    from, to: upto, in: sin, out: sout,
    end: { firm: endFirm, all: endAll, actual: endActual, diff_firm: diff(endActual, endFirm), diff_all: diff(endActual, endAll) },
    hit,
    not_happened: plan.filter((r) => r.amount !== null && !hitOf.has(r)),
    unplanned: actual.filter((_, i) => !used.has(i)),
    by_source: [...groups.values()].sort((a, b) => (a.source < b.source ? -1 : a.source > b.source ? 1 : a.io < b.io ? -1 : a.io > b.io ? 1 : 0)),
  };
}

export interface LagStat { n: number; late_median: number | null; late_n: number; term_median: number }
export interface InvoiceLike { client: string; date: IsoDate | null; due: IsoDate | null; paid_date: IsoDate | null; kind?: string }

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m]! : Math.round((s[m - 1]! + s[m]!) / 2);
}

/** 입금된 계산서로 본 수금 습관. late = 실제 입금일 − 입금예정일(일, 양수면 늦음), term = 실제 입금일 − 발행일.
 * n = 입금일과 발행일을 아는 계산서 수. 환불 줄은 뺀다. 입금된 계산서가 없으면 all 은 null. */
export function collectionLag(invoices: InvoiceLike[]): { all: LagStat | null; by_client: Record<string, LagStat> } {
  const paid = invoices.filter((v) => v.paid_date && v.date && v.kind !== "환불");
  const stat = (xs: InvoiceLike[]): LagStat => {
    const late = xs.filter((v) => v.due).map((v) => daysBetween(v.due!, v.paid_date!));
    return { n: xs.length, late_median: late.length ? median(late) : null, late_n: late.filter((x) => x > 0).length,
             term_median: median(xs.map((v) => daysBetween(v.date!, v.paid_date!))) };
  };
  const by: Record<string, InvoiceLike[]> = {};
  for (const v of paid) (by[v.client] ??= []).push(v);
  return { all: paid.length ? stat(paid) : null, by_client: Object.fromEntries(Object.entries(by).map(([k, xs]) => [k, stat(xs)])) };
}
