// 인트라넷 지급 요청서 세부사항 첫 줄을 출금 일정에 붙이기 — 파이썬 ceo_report/payreq.py attach (pid_of·_vn·_same_vendor).
import { PY_SPACE, sortedBy } from "../model/py";
import { normVendor } from "../model/vendor";
import type { Obj } from "./ctx";

export const SOURCE = "지출결의서";
const PID = /(?<![0-9])([0-9]{5})(?![0-9])/;
const VN_RE = new RegExp("\\(.*?\\)|[" + PY_SPACE + "()]", "g");

/** 파이썬 str(x or "") */
const so = (x: unknown): string => (x === null || x === undefined || x === "" || x === 0 || x === false ? "" : String(x));

export function pidOf(text: unknown): string {
  const m = PID.exec(so(text));
  return m ? m[1]! : "";
}

function vn(name: unknown): string {
  return normVendor(so(name)).replace(VN_RE, "");
}

function sameVendor(a: unknown, b: unknown): boolean {
  const x = vn(a), y = vn(b);
  return !!(x && y && (x.includes(y) || y.includes(x)));
}

export interface ReqRow { key?: string; project: string; vendor: string; amount: number | null; note: string }

/** 출금 일정 줄에 e.detail = 세부사항 첫 줄 (출처 '지출결의서'). 수기 상세는 바꾸지 않는다. -> 붙인 줄 수. */
export function attach(events: Obj[], reqs: ReqRow[] | null | undefined): number {
  const pool = (reqs || []).filter((r) => r.project && r.amount !== null && r.amount !== undefined && r.note);
  if (!pool.length) return 0;
  const used = new Set<number>();
  let n = 0;
  const outs = events.filter((e) => e["io"] === "out" && e["amount"] !== null && e["amount"] !== undefined && pidOf(e["project"])
    && e["detail_source"] !== "수기" && e["source"] !== "남은 예산");
  const sorted = sortedBy(outs, (e) => [e["date"] === null || e["date"] === undefined, e["date"] || "", -(e["amount"] || 0)]);
  for (const e of sorted) {
    const pid = pidOf(e["project"]);
    const cands = pool.map((_, i) => i).filter((i) => !used.has(i) && pidOf(pool[i]!.project) === pid);
    if (!cands.length) continue;
    const named = !!vn(e["desc"]);
    const fits = cands.filter((i) => !(named && vn(pool[i]!.vendor)) || sameVendor(pool[i]!.vendor, e["desc"]));
    let pick = fits.filter((i) => pool[i]!.amount === e["amount"]);
    if (pick.length > 1) pick = pick.filter((i) => sameVendor(pool[i]!.vendor, e["desc"]));
    if (pick.length !== 1) {
      pick = [];
      const sameV = cands.filter((i) => sameVendor(pool[i]!.vendor, e["desc"]));
      for (const group of named ? [sameV] : [sameV, cands]) {
        if (group.length > 1 && group.reduce((a, i) => a + (pool[i]!.amount as number), 0) === e["amount"]) {
          pick = group;
          break;
        }
      }
    }
    if (!pick.length) continue;
    for (const i of pick) used.add(i);
    e["detail"] = [...new Set(pick.map((i) => pool[i]!.note))].join(" · ");
    e["detail_source"] = SOURCE;
    n += 1;
  }
  return n;
}
