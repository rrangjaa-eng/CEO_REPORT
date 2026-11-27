// 금요일 출금 목록의 상세 내역 붙이기 — 파이썬 ceo_report/paydetail.py attach.
import { sortedBy } from "../model/py";
import { normVendor } from "../model/vendor";
import type { Obj } from "./ctx";

export const MANUAL = "수기";
export const INTRANET = "지출결의서";

export interface DetailRow { vendor: string; amount: number; text: string; source: string }

/** 지급 일정 줄에 e.detail 을 붙인다 (같은 거래처·같은 금액, 수기 먼저, 상세 한 줄은 가장 이른 일정 한 줄에만). -> 붙인 줄 수. */
export function attach(events: Obj[], details: DetailRow[]): number {
  const by = new Map<string, DetailRow>();
  for (const d of details) {
    const k = JSON.stringify([normVendor(d.vendor), d.amount]);
    const had = by.get(k);
    if (!had || (d.source === MANUAL && had.source !== MANUAL)) by.set(k, d);
  }
  let n = 0;
  const used = new Set<string>();
  const outs = events.filter((e) => e["io"] === "out" && e["amount"] !== null && e["amount"] !== undefined);
  for (const e of sortedBy(outs, (e) => [e["date"] === null || e["date"] === undefined, e["date"] || ""])) {
    const k = JSON.stringify([normVendor(e["desc"] || ""), e["amount"]]);
    const d = by.get(k);
    if (d && !used.has(k)) {
      used.add(k);
      e["detail"] = d.text;
      e["detail_source"] = d.source;
      n += 1;
    }
  }
  return n;
}
