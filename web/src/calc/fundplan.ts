// 자금계획서 줄로 자금 일정을 바꾼다 — 파이썬 ceo_report/fundplan.py apply (660-844) · fill_projects (847-882).
// 바꿀 것 (golden/RULES.md '새 시스템에서 바꿀 것'):
//   F6  거래처코드가 없어도 이름이 다르면 다른 건 (같은 금액·7일 안이라도 added·missing 따로). 이름을 모르는(빈) 쪽이 있을 때만
//       예전처럼 금액·날짜로 맞춘다.
//   U6  숫자가 아닌 거래처코드도 양쪽을 같은 규칙으로 맞춘다 (codeKey). 변환(fundplan.parse_auto)이 자금계획서 코드만 앞 0을 떼고
//       zfill(6) 해서 '00C202'·'-00-00003' 처럼 장부 코드 'C202'·'000-00-00003' 과 달라지던 것.
import { addDays, daysBetween, weekday, type IsoDate } from "../model/dates";
import { sortedBy } from "../model/py";
import { normCode, normVendor } from "../model/vendor";

/** 자금 일정 한 줄. 파이썬 dict 와 같은 키 (date, io, amount, firm, cat, desc, basis, project, source, …). 날짜는 "YYYY-MM-DD". */
export interface FundEvent {
  date: IsoDate | null;
  io: "in" | "out" | string;
  amount: number | null;
  firm?: boolean;
  cat?: string;
  desc?: string;
  basis?: string;
  project?: string;
  source?: string;
  vendor_code?: string;
  inv_key?: unknown;
  orig_date?: IsoDate;
  gap?: IsoDate;
  plan_state?: string;
  plan_note?: string;
  [k: string]: unknown;
}

/** data.load 의 d.fundplan 한 줄 (자금계획.csv). io 는 "지급"·"입금". 파이썬처럼 apply 가 _by_name·_split 을 붙인다. */
export interface PlanRow {
  date: IsoDate;
  io: string;
  cat: string;
  vendor: string;
  vendor_code: string;
  amount: number;
  ym: string;
  stamp: IsoDate;
  state: string;
  basis: string;
  file: string;
  project: string;
  origin: string;
  row?: unknown;
  _by_name?: boolean;
  _split?: FundEvent[];
  [k: string]: unknown;
}

export interface Txn {
  date?: IsoDate | null;
  io?: string;
  amount?: number | null;
  [k: string]: unknown;
}

export interface FundplanInfo {
  used: boolean;
  reason: string;
  stamp?: IsoDate;
  months?: string[];
  matched?: { plan: FundEvent; old: FundEvent; by_name: boolean; split: FundEvent[] }[];
  missing?: FundEvent[];
  done?: { plan: PlanRow; old: FundEvent | null }[];
  moved?: FundEvent[];
  late_in?: FundEvent[];
  added?: FundEvent[];
  [k: string]: unknown;
}

export const MATCH_DAYS = 7;
export const DONE_DAYS = 31;
export const DONE_AHEAD_DAYS = 15;
export const CENTS = 100;
export const FLAG_SOURCES = ["자금일정", "계산서", "프로젝트집행"];

/** U6: 비교용 거래처코드. norm_code(공백 제거, 숫자 코드는 앞 0 뗌)에 더해 숫자가 아닌 코드도 앞 0을 뗀다 (양쪽 같은 규칙). */
export function codeKey(code: unknown): string {
  const s = normCode(code as string | null | undefined);
  if (!s) return "";
  return s.replace(/^0+/, "") || "0";
}

/** 기준일 다음 금요일 (금요일이면 7일 뒤). 파이썬 _next_friday. */
export function nextFriday(asof: IsoDate): IsoDate {
  const k = (((4 - weekday(asof)) % 7) + 7) % 7;
  return addDays(asof, k || 7);
}

const REF = /장부 기준일 (\d{4}-\d{2}-\d{2})/;

function unverified(p: PlanRow): boolean {
  if (p.state === "예정") return true;
  const m = REF.exec(String(p.basis || ""));
  return p.state === "예정일 지남" && !!m && m[1]! < p.date;
}

function inBalance(p: PlanRow, cashDate: IsoDate | null, txns: Txn[] | null): string | null {
  if (cashDate === null || p.date > cashDate) return null;
  const io = p.io === "지급" ? "출금" : "입금";
  const lo = addDays(p.date, -3);
  const hit = (txns || []).filter((t) => t.io === io && t.amount === p.amount && t.date != null && lo <= t.date && t.date <= cashDate);
  if (hit.length) {
    const first = hit.map((t) => t.date as string).reduce((a, b) => (b < a ? b : a));
    return `통장 ${first} ${io} 같은 금액 → 이미 ${io === "출금" ? "지급" : "입금"} (분개장 미반영)`;
  }
  return `예정일이 통장 잔액 기준일 ${cashDate} 이전 → 잔액에 이미 반영된 것으로 봄 (분개장은 그 전까지만 있음)`;
}

function doneWindow(evDay: IsoDate | null, doneDay: IsoDate): boolean {
  if (evDay === null) return false;
  const gap = daysBetween(doneDay, evDay);
  return gap >= -DONE_DAYS && gap <= DONE_AHEAD_DAYS;
}

/** F6: 두 이름이 모두 있고 다르면 다른 거래처. 어느 하나라도 비었으면 이름으로는 모름. */
function namesDiffer(a: string, b: string): boolean {
  return !!a && !!b && a !== b;
}

type Rank = [number, number, number];
function rankLess(a: Rank, b: Rank): boolean {
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i]! < b[i]!;
  return false;
}

/** 자금계획서 줄로 일정을 바꾼다 (D-55 '자금계획서 기준'). -> [새 일정 목록, 설명 또는 null]. 파이썬 fundplan.apply. */
export function applyFundplan(
  events: FundEvent[], plan: PlanRow[] | null, asof: IsoDate, staleDays: number, problem = "",
  cashDate: IsoDate | null = null, txns: Txn[] | null = null,
): [FundEvent[], FundplanInfo | null] {
  if (plan === null || plan === undefined) {
    if (problem) return [events, { used: false, reason: "자금계획.csv " + problem + " → 기존 일정 사용" }];
    return [events, null];
  }
  if (!plan.length) return [events, { used: false, reason: "자금계획.csv 에 줄이 없음 → 기존 일정 사용" }];
  const stamp = plan.map((p) => p.stamp).reduce((a, b) => (b < a ? b : a));
  const months = [...new Set(plan.map((p) => p.ym))].sort();
  const info: FundplanInfo & Required<Pick<FundplanInfo, "matched" | "missing" | "done" | "moved" | "late_in" | "added">> = {
    used: false, stamp, months, reason: "", matched: [], missing: [], done: [], moved: [], late_in: [], added: [] };
  const age = daysBetween(stamp, asof);
  if (age > staleDays) {
    info.reason = `자금계획서 자료일 ${stamp}이 기준일보다 ${age}일 이전 (허용 ${staleDays}일) → 기존 일정 사용`;
    return [events, info];
  }
  info.used = true;
  const taken = new Set<number>();

  const splitInvoice = (p: PlanRow, io: string, key: string): FundEvent | null => {
    const groups = new Map<string, number[]>();
    events.forEach((ev, i) => {
      if (taken.has(i) || ev.io !== io || ev.source !== "계산서" || !ev.inv_key || ev.amount === null) return;
      if (Array.isArray(ev.inv_key) && ev.inv_key.length === 0) return;
      const k = JSON.stringify(ev.inv_key);
      const g = groups.get(k);
      if (g) g.push(i);
      else groups.set(k, [i]);
    });
    for (const idx of groups.values()) {
      if (idx.length < 2 || idx.reduce((s, i) => s + (events[i]!.amount as number), 0) !== p.amount) continue;
      const first = events[idx[0]!]!;
      const fname = normVendor(first.desc || "");
      const same = !!key && fname === key;
      const near = first.date !== null && Math.abs(daysBetween(p.date, first.date)) <= MATCH_DAYS;
      const done = p.state === "이미 지급" || p.state === "이미 입금";
      if (!(same || (near && !done && !namesDiffer(key, fname)))) continue;   // F6
      if (done && !doneWindow(first.date, p.date)) continue;
      for (const i of idx) taken.add(i);
      p._by_name = true;
      p._split = idx.map((i) => events[i]!);
      return first;
    }
    return null;
  };

  const find = (p: PlanRow): FundEvent | null => {
    delete p._by_name;
    delete p._split;
    const io = p.io === "지급" ? "out" : "in";
    const key = normVendor(p.vendor);
    const done = p.state === "이미 지급" || p.state === "이미 입금";
    let best: [Rank, number] | null = null;
    events.forEach((ev, i) => {
      if (taken.has(i) || ev.io !== io || ev.amount === null || !FLAG_SOURCES.includes(ev.source as string)) return;
      const pc = codeKey(p.vendor_code), ec = codeKey(ev.vendor_code);   // U6
      if (pc && ec && pc !== ec) return;
      const ename = normVendor(ev.desc || "");
      const same = pc && ec ? pc === ec : !!key && ename === key;
      if (ev.amount !== p.amount) {
        if (!(same && ev.source === "계산서" && p.amount !== null && Math.abs(ev.amount - p.amount) <= CENTS)) return;
      }
      const near = ev.date !== null && Math.abs(daysBetween(p.date, ev.date)) <= MATCH_DAYS;
      if (!(same || (near && !done && !namesDiffer(key, ename)))) return;   // F6: 이름이 다르면 다른 건
      if (done && !doneWindow(ev.date, p.date)) return;
      const rank: Rank = [same ? 0 : 1, ev.amount !== p.amount ? 1 : 0, ev.date ? Math.abs(daysBetween(p.date, ev.date)) : 999];
      if (best === null || rankLess(rank, best[0])) best = [rank, i];
    });
    if (best === null) return splitInvoice(p, io, key);
    const bi = (best as [Rank, number])[1];
    taken.add(bi);
    p._by_name = !(codeKey(p.vendor_code) && codeKey(events[bi]!.vendor_code));
    return events[bi]!;
  };

  const out: FundEvent[] = [];
  for (const p of sortedBy(plan, (x) => [x.date, x.io, x.vendor])) {
    const old = find(p);
    if (p.state === "이미 지급" || p.state === "이미 입금") {
      info.done.push({ plan: p, old });
      continue;
    }
    if (p.date <= asof && unverified(p)) {
      const why = inBalance(p, cashDate, txns);
      if (why !== null) {
        info.done.push({ plan: { ...p, state: "통장 잔액에 반영", basis: why }, old });
        continue;
      }
    }
    const io = p.io === "지급" ? "out" : "in";
    const ev: FundEvent = {
      date: p.date, io, amount: p.amount, firm: true,
      cat: "자금계획서 " + (p.cat || p.io), desc: p.vendor,
      basis: `자금계획서 예정일 ${p.date} (${p.file || "자료일 " + p.stamp})`,
      project: (old ? old.project : "") || p.project || "", source: "자금계획서", plan_state: p.state,
      vendor_code: p.vendor_code || "",
    };
    if (p.state === "예정일 지남" || (p.state === "예정" && p.date <= asof)) {
      if (io === "out") {
        ev.orig_date = p.date;
        ev.date = nextFriday(asof);
        ev.basis += ", 예정일 지난 미지급 → 다음 금요일";
        if (unverified(p)) {
          ev.basis += " (장부·통장 자료가 예정일 전까지만 있음: 이미 나갔으면 빼도 됨)";
          ev.gap = p.date;
        }
        info.moved.push(ev);
      } else {
        ev.firm = false;
        ev.basis += ", 입금 지연";
        info.late_in.push(ev);
      }
    }
    out.push(ev);
    if (old !== null) info.matched.push({ plan: ev, old, by_name: !!p._by_name, split: p._split || [] });
    else info.added.push(ev);
  }
  events.forEach((ev, i) => {
    if (taken.has(i)) return;
    if (FLAG_SOURCES.includes(ev.source as string) && ev.date !== null && months.includes(ev.date.slice(0, 7))) {
      ev = { ...ev, plan_note: "자금계획서에 없음" };
      info.missing.push(ev);
    }
    out.push(ev);
  });
  return [out, info];
}

/** 프로젝트집행 한 줄 (fill_projects 가 쓰는 칸만). */
export interface ExecRow {
  basis?: unknown;
  state?: unknown;
  project?: unknown;
  vendor?: string | null;
  supply?: number | null;
  vat?: number | null;
  [k: string]: unknown;
}

/** 자금계획서 지급 줄에 프로젝트를 채운다. 파이썬 fundplan.fill_projects. -> 채운 건수. */
export function fillProjects(events: FundEvent[], execs: ExecRow[] | null | undefined): number {
  const byVendor = new Map<string, ExecRow[]>();
  for (const e of execs || []) {
    if (!String(e.basis ?? "").startsWith("WEHAGO ") || !(e.state === "요청미지급" || e.state === "카드사용미결제")) continue;
    if (!String(e.project ?? "").trim()) continue;
    const k = normVendor(e.vendor || "");
    if (k) {
      const g = byVendor.get(k);
      if (g) g.push(e);
      else byVendor.set(k, [e]);
    }
  }
  let n = 0;
  for (const ev of events) {
    if (ev.io !== "out" || ev.source !== "자금계획서" || ev.project) continue;
    const cand = byVendor.get(normVendor(ev.desc || "")) || [];
    if (!cand.length) continue;
    const total = (e: ExecRow) => (e.supply || 0) + (e.vat || 0);
    const same = new Set(cand.filter((e) => total(e) === ev.amount).map((e) => e.project));
    const pool = same.size ? same : new Set(cand.map((e) => e.project));
    if (pool.size === 1) {
      ev.project = [...pool][0] as string;
      ev.basis = (ev.basis || "") + ", 프로젝트는 장부 미지급 원가 줄로 찾음";
      n++;
    } else {
      ev.basis = (ev.basis || "") + `, 거래처 미지급이 여러 프로젝트 (${pool.size}개)`;
    }
  }
  return n;
}
