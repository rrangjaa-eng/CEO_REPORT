// 자금 일정 도움 함수 — 파이썬 ceo_report/calc.py two_sources (119-142) · MUST_KINDS … available_periods (1006-1100).
// pay_friday·period_ends 는 model/dates.ts (payFriday·periodEnds).
import { addDays, type IsoDate } from "../model/dates";
import { PY_SPACE, pyRemoveSpace, sortedBy } from "../model/py";
import { normCode, normVendor } from "../model/vendor";
import type { Obj } from "./ctx";
import { KEYWORDS, NOT_TAX } from "./tax";

/** 파이썬 str(x or "") */
const so = (x: unknown): string => (x === null || x === undefined || x === "" || x === 0 || x === false ? "" : String(x));

export const TWO_SOURCE_KINDS = ["자금계획서", "자금일정", "프로젝트집행"];

/** 출금 출처 하나 원칙 점검: 기준일 뒤 같은 거래처·같은 달 출금이 두 출처 이상에 있으면 목록. 금액 큰 순. */
export function twoSources(events: Obj[], asof: IsoDate): Obj[] {
  const groups = new Map<string, Obj>();
  for (const ev of events) {
    if (ev["io"] !== "out" || ev["amount"] === null || ev["amount"] === undefined || ev["date"] === null
      || ev["date"] === undefined || ev["date"] <= asof) continue;
    const src = ev["source"];
    if (!TWO_SOURCE_KINDS.includes(src)) continue;
    const key = normCode(ev["vendor_code"]) || normVendor(ev["desc"] || "");
    if (!key) continue;
    const month = (ev["date"] as string).slice(0, 7);
    const gk = JSON.stringify([key, month]);
    let g = groups.get(gk);
    if (!g) {
      g = { vendor: ev["desc"] || key, vcode: normCode(ev["vendor_code"]), month, sources: new Map<string, number>() };
      groups.set(gk, g);
    }
    const m = g["sources"] as Map<string, number>;
    m.set(src, (m.get(src) ?? 0) + ev["amount"]);
  }
  const out = [...groups.values()].filter((g) => (g["sources"] as Map<string, number>).size > 1);
  const tot = (g: Obj) => [...(g["sources"] as Map<string, number>).values()].reduce((a, b) => a + b, 0);
  return sortedBy(out, (g) => -tot(g)).map((g) => ({ ...g, sources: Object.fromEntries(g["sources"] as Map<string, number>) }));
}

/** 입금 출처 둘 점검 (새 안전장치): 자금계획서 입금과 맞춰지지 않은 계산서·자금일정 입금이 같은 거래처·같은 달에 있으면
 * 같은 돈이 두 번 잡혔을 수 있다. 기준일 뒤, 금액·날짜를 아는 줄만(예정일 지난 입금 포함). 금액 큰 순. 숫자는 바꾸지 않고 목록만 낸다. */
export function twoSourcesIn(events: Obj[], asof: IsoDate, payday: IsoDate): Obj[] {
  const groups = new Map<string, { vendor: string; month: string; sources: Map<string, number> }>();
  for (const ev of events) {
    if (ev["io"] !== "in" || ev["amount"] === null || ev["amount"] === undefined || !ev["date"]) continue;
    // 예정일 지난 입금은 s2 가 출금일(payday)로 옮겨 이번 주 예상 입금으로 세므로 그 달로 본다
    const day: IsoDate = ev["date"] <= asof ? payday : ev["date"];
    const src = ev["source"] as string;
    if (!["자금계획서", "자금일정", "계산서"].includes(src)) continue;
    const key = normVendor(ev["desc"] || "");
    if (!key) continue;
    const month = day.slice(0, 7);
    const gk = JSON.stringify([key, month]);
    const g = groups.get(gk) ?? { vendor: ev["desc"] || key, month, sources: new Map<string, number>() };
    groups.set(gk, g);
    g.sources.set(src, (g.sources.get(src) ?? 0) + ev["amount"]);
  }
  const tot = (g: { sources: Map<string, number> }) => [...g.sources.values()].reduce((a, b) => a + b, 0);
  return sortedBy([...groups.values()].filter((g) => g.sources.has("자금계획서") && g.sources.size > 1), (g) => -tot(g))
    .map((g) => ({ ...g, sources: Object.fromEntries(g.sources) }));
}

export const MUST_KINDS = ["급여", "4대보험", "원천세", "부가세", "법인세", "법인지방소득세", "카드대금", "고정 지출"];
export const MUST_CAT_EXTRA = ["세금", "회사부담금"];
export const MUST_VENDOR = ["세무서", "구청", "시청", "군청", "공단"];
export const LOAN_WORDS = ["차입금", "대출", "이자"];
/** tax.CARD_PREFIX */
export const CARD_PREFIX = new RegExp("^(신한|롯데|비씨|BC|삼성|현대|국민|KB|하나|우리|농협|NH|씨티)[_" + PY_SPACE + "-]");

/** 꼭 나갈 정기 지출 (급여·4대보험·원천세·부가세·법인세·카드대금·고정 지출). 파이썬 must_pay. */
export function mustPay(ev: Obj, card = true, loans = false, pay = true): boolean {
  if (ev["io"] !== "out") return false;
  const kinds = MUST_KINDS.filter((k) => (card || k !== "카드대금") && (pay || k !== "급여"));
  if (ev["source"] === "세금예상") return kinds.includes(ev["kind"] || so(ev["cat"]).split(" (")[0]!);
  if (NOT_TAX.includes(ev["source"])) return false;
  const cat = pyRemoveSpace(so(ev["cat"]));
  const vendor = pyRemoveSpace(so(ev["desc"]));
  const words = [...kinds.flatMap((k) => [...(KEYWORDS[k] ?? [])]), ...MUST_CAT_EXTRA, ...(loans ? LOAN_WORDS : [])];
  return words.some((w) => cat.includes(w)) || MUST_VENDOR.some((w) => vendor.includes(w)) || (card && vendor.endsWith("카드"));
}

/** 통장에서 저절로 나가는 돈 (must_pay 에서 급여만 뺌 + 카드사_끝번호 거래처). 파이썬 auto_debit. */
export function autoDebit(ev: Obj): boolean {
  if (ev["io"] !== "out") return false;
  return mustPay(ev, true, false, false) || CARD_PREFIX.test(so(ev["desc"]).replace(new RegExp("^[" + PY_SPACE + "]+|[" + PY_SPACE + "]+$", "g"), ""));
}

/** 일정마다 ev.must 를 단다. 세금 줄과 맞춘 일정도 꼭 나갈 돈. 파이썬 mark_must. */
export function markMust(events: Obj[], taxInfo: Obj[] | null | undefined = null): void {
  for (const ev of events) ev["must"] = mustPay(ev);
  for (const t of taxInfo || []) {
    if (!MUST_KINDS.includes(t["kind"])) continue;
    for (const m of [t["matched"], ...(t["matched_all"] || [])]) {
      if (m && typeof m === "object" && !Array.isArray(m) && m["io"] === "out") m["must"] = true;
    }
  }
}

/** mode 에 넣는 일정인가 (firm·spend·all). 파이썬 counts_in. */
export function countsIn(ev: Obj, mode: string): boolean {
  if (mode === "all" || ev["firm"] || ev["must"]) return true;
  return mode === "spend" && ev["io"] === "out";
}

/** 기간별 가용자금. 파이썬 available_periods. */
export function availablePeriods(start: number | null, dated: Obj[], ends: [string, IsoDate][], minCash: number | null | undefined,
                                 asof: IsoDate): Obj[] {
  const out: Obj[] = [];
  let prev = asof;
  for (const [label, end] of ends) {
    const frm = label !== "지정일" ? prev : asof;
    if (label !== "지정일") prev = end;
    const row: Obj = { label, end, from: addDays(frm, 1) };
    for (const mode of ["firm", "spend", "all"]) {
      const daily = new Map<string, number>();
      let tin = 0, tout = 0;
      for (const e of dated) {
        if (!(asof < e["date"] && e["date"] <= end) || !countsIn(e, mode)) continue;
        if (e["io"] === "in") {
          tin += e["amount"];
          daily.set(e["date"], (daily.get(e["date"]) ?? 0) + e["amount"]);
        } else {
          tout += e["amount"];
          daily.set(e["date"], (daily.get(e["date"]) ?? 0) - e["amount"]);
        }
      }
      let pin = 0, pout = 0;
      for (const e of dated) {
        if (!(frm < e["date"] && e["date"] <= end) || !countsIn(e, mode)) continue;
        if (e["io"] === "in") pin += e["amount"];
        else if (e["io"] === "out") pout += e["amount"];
      }
      const r: Obj = { in: tin, out: tout, pin, pout, bal: null, low: null, low_date: null, avail: null };
      if (start !== null) {
        let bal = start, low = start, lowD: IsoDate = asof;
        for (const day of [...daily.keys()].sort()) {
          bal += daily.get(day)!;
          if (bal < low) { low = bal; lowD = day; }
        }
        Object.assign(r, { bal, low, low_date: lowD, avail: minCash === null || minCash === undefined ? null : low - minCash });
      }
      row[mode] = r;
    }
    out.push(row);
  }
  return out;
}
