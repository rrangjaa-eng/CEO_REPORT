// 대표 보고에 보일 값 중 R 에 바로 없고 render.py 가 그리기 직전에 만들던 것 (그 규칙 그대로).
//   weekOutflows  = render.week_outflows (출금일 목록 · 다음 주 지급 예정)
//   vsLastWeek    = render._vs_last_week 의 한 줄 (지난주 출금 대비)
//   monthFlow     = render.month_flow (월간 그림: 그 달 1일부터)
//   teamBuild 등  = ceo_report/teamprofit.py (팀별 영업이익)
// R 은 고치지 않는다.
import { addDays, addMonths, firstOfMonth, payFriday, type IsoDate } from "../model/dates";
import { NO_DEPT } from "../model/data";
import { autoDebit, countsIn } from "../calc/schedule";
import type { Obj } from "../calc/ctx";
import { won } from "../model/util";
import { md, signed } from "./fmt";

type N = number | null;

// ── 출금 목록 ────────────────────────────────────────────────

export interface Sums { rows: Obj[]; firm: number; est: number; overdue: number; total: number; unknown_n: number }

function sums(rs: Obj[]): Sums {
  const known = rs.filter((e) => e["amount"] !== null && e["amount"] !== undefined);
  const add = (xs: Obj[]) => xs.reduce((s, e) => s + (e["amount"] as number), 0);
  return {
    rows: rs,
    firm: add(known.filter((e) => e["firm"] && !e["overdue"])),
    est: add(known.filter((e) => !e["firm"] && !e["overdue"])),
    overdue: add(known.filter((e) => e["overdue"])),
    total: add(known),
    unknown_n: rs.length - known.length,
  };
}

const byDateAmount = (a: Obj, b: Obj) =>
  a["date"] < b["date"] ? -1 : a["date"] > b["date"] ? 1 : -(a["amount"] ?? 0) + (b["amount"] ?? 0);

export interface WeekOut { fri: IsoDate; end: IsoDate; pay: Sums; pay_est: Sums; gap: Sums; next: Sums }

export function weekOutflows(R: Obj): WeekOut {
  const asof = R["asof"] as IsoDate;
  const fri = (R["payday"] as IsoDate | null) || payFriday(asof);
  const end = addDays(fri, 7);
  let rows: Obj[] = [];
  for (const e of R["events"] as Obj[]) {
    if (e["io"] !== "out" || !e["date"] || e["date"] > end) continue;
    if (e["date"] <= asof && e["date"] < fri) continue;
    rows.push({ ...e, overdue: false });
  }
  const plan = new Map<IsoDate, Obj[]>();
  for (const e of rows.filter((e) => e["source"] === "남은 예산")) {
    if (!plan.has(e["date"])) plan.set(e["date"], []);
    plan.get(e["date"])!.push(e);
  }
  if (plan.size) {
    rows = rows.filter((e) => e["source"] !== "남은 예산");
    for (const [d, es] of plan) {
      rows.push({
        date: d, io: "out", amount: es.reduce((s, e) => s + e["amount"], 0), firm: false, overdue: false,
        cat: "프로젝트 남은 예산", desc: `진행 프로젝트 ${es.length}개`, project: "",
        detail: "아직 요청 전 금액을 매주 나눠 잡은 예상", source: "남은 예산",
      });
    }
  }
  rows.sort(byDateAmount);   // 파이썬 sort 는 안정 정렬, JS sort 도 안정 정렬
  const gap = rows.filter((e) => e["gap"]);
  rows = rows.filter((e) => !e["gap"]);
  const upto = rows.filter((e) => e["date"] <= fri);
  const sure = (e: Obj) => e["firm"] && e["amount"] !== null && e["amount"] !== undefined;
  return {
    fri, end, gap: sums(gap),
    pay: sums(upto.filter(sure)),
    pay_est: sums(upto.filter((e) => !sure(e))),
    next: sums(rows.filter((e) => e["date"] > fri)),
  };
}

const CAT_SHOW: Record<string, string> = { "프로젝트 남은 예산": "프로젝트 지급 예정 (미요청·예상)" };
const USE_WORDS: [string, string[]][] = [
  ["대출 상환", ["차입금", "원금", "상환", "대출"]], ["이자", ["이자"]],
  ["세금", ["부가세", "원천세", "법인세", "지방소득세", "세금"]], ["4대보험", ["4대보험", "회사부담금", "사대보험"]],
  ["급여", ["인건비", "급여", "상여"]], ["카드값", ["카드"]], ["직원 복리후생", ["복리후생"]],
  ["사무실·운영비", ["임차", "관리비", "구독", "일반경비", "통신", "소모품"]],
  ["행사 외주·제작비", ["프로젝트", "남은 예산"]], ["거래처 대금", ["미지급", "거래처"]],
];

export function plainUse(cat: string): string {
  for (const [name, words] of USE_WORDS) if (words.some((w) => cat.includes(w))) return name;
  return cat;
}

function catName(e: Obj, dflt = ""): string {
  const c = String(e["cat"] || dflt).replace(" (장부 계산)", "");
  return CAT_SHOW[c] ?? c;
}

/** 출금 목록·다음 주 요약의 구분 칸 (render._use_name) */
export function useName(e: Obj, dflt = "기타"): string {
  return plainUse(catName(e, dflt)) + ((e["cat"] || "") === "프로젝트 남은 예산" ? " (미요청·예상)" : "");
}

/** 출금 목록의 내역 칸 [구분, 상세 또는 null, 상세 미입력인가] (render._cat_cell) */
export function catCell(e: Obj): [string, string | null, boolean] {
  const c = catName(e);
  const d = e["detail"] ? String(e["detail"]) : null;
  if (c.includes("지급요청")) return [plainUse(c), d ?? "상세 미입력", !d];
  return [useName(e, ""), d, false];
}

/** 프로젝트 번호 → '[번호] 이름' (render._pname) */
export function pname(R: Obj, pid: unknown): string {
  if (!pid) return "";
  const id = String(pid);
  for (const P of (R["s3"]?.["projects"] || []) as Obj[]) {
    if (P["id"] === id) {
      const name = String(P["name"] || "").replace(id, "").replace("[]", "").trim();
      return name ? `[${id}] ${name}` : `[${id}]`;
    }
  }
  return `[${id}]`;
}

export interface NextGroup { name: string; n: number; days: string; known: number; unknown: number; state: string }

/** 다음 주 지급 예정을 쓰임새별로 (render._next_week_summary): 금액 큰 순 */
export function nextWeekGroups(G: Sums): NextGroup[] {
  const groups = new Map<string, Obj[]>();
  for (const e of G.rows) {
    const k = useName(e);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k)!.push(e);
  }
  const out = [...groups.entries()].map(([name, rs]) => {
    const ds = rs.map((e) => e["date"] as string).sort();
    const known = rs.filter((e) => e["amount"] !== null && e["amount"] !== undefined).map((e) => e["amount"] as number);
    const firm = rs.filter((e) => e["firm"]).length;
    return {
      name, n: rs.length,
      days: ds[0] === ds[ds.length - 1] ? md(ds[0]!) : `${md(ds[0]!)}~${md(ds[ds.length - 1]!)}`,
      known: known.reduce((s, v) => s + v, 0), unknown: rs.length - known.length,
      state: firm === rs.length ? "확정" : !firm ? "예상" : `확정 ${firm} · 예상 ${rs.length - firm}`,
      sortKey: -rs.reduce((s, e) => s + (e["amount"] ?? 0), 0),
    };
  });
  out.sort((a, b) => a.sortKey - b.sortKey);
  return out.map(({ sortKey: _s, ...g }) => g);
}

/** 거래처 이름 맞추기 (render._vkey): NFKC, 공백·'(주)'·'주식회사' 제거 */
export function vkey(name: unknown): string {
  return String(name || "").normalize("NFKC").replace(/\s+/g, "").replace(/\(주\)/g, "").replace(/주식회사/g, "");
}

/** 지난주 대비 한 줄 (render._vs_last_week 의 대표용 줄). */
export function vsLastWeek(R: Obj, P: Sums): string {
  const L = R["last_pay"] as Obj | null;
  if (!L) {
    const d = addDays((R["payday"] || R["asof"]) as IsoDate, -7);
    return `지난주 대비: 지난주(${md(addDays(d, -6))}~${md(d)}) 출금 자료 없음 — 장부가 그날까지 들어오면 비교함`;
  }
  const week = L["start"] ? `${md(L["start"])}~${md(L["date"])}` : md(L["date"]);
  const prev = new Map<string, [string, number, number]>();
  const cur = new Map<string, [string, number, number]>();
  for (const r of L["rows"] as Obj[]) {
    const k = vkey(r["vendor"]);
    const v = prev.get(k) ?? [r["vendor"], 0, 0];
    v[1] += r["amount"]; v[2] += 1; prev.set(k, v);
  }
  for (const e of P.rows) {
    if (autoDebit(e)) continue;
    const k = vkey(e["desc"]);
    const v = cur.get(k) ?? [e["desc"] || "", 0, 0];
    v[1] += e["amount"] || 0; v[2] += 1; cur.set(k, v);
  }
  const rows: [string, N, N, number][] = [];
  for (const [k, [, a, n]] of prev) if (!cur.has(k)) rows.push(["빠진 것", a, null, n]);
  for (const [k, [, b, n]] of cur) {
    if (!prev.has(k)) rows.push(["추가된 것", null, b, n]);
    else if (prev.get(k)![1] !== b) rows.push(["변동된 것", prev.get(k)![1], b, n]);
  }
  const parts: string[] = [];
  for (const kind of ["빠진 것", "추가된 것", "변동된 것"]) {
    const rs = rows.filter((r) => r[0] === kind);
    if (rs.length) {
      parts.push(`${kind} ${rs.reduce((s, r) => s + r[3], 0)}건 ${signed(rs.reduce((s, r) => s + (r[2] ?? 0) - (r[1] ?? 0), 0))}`);
    }
  }
  parts.push("카드·세금 자동 출금은 빼고 비교");
  const curTotal = [...cur.values()].reduce((s, v) => s + v[1], 0);
  const top = `지난주(${week}) 출금 ${won(L["total"])} → 이번 출금 ${won(curTotal)} (${curTotal !== L["total"] ? signed(curTotal - L["total"]) : "변동 없음"})`;
  return `지난주 대비: ${top} · ${parts.join(" · ")}`;
}

// ── 월간 자금 흐름 그림 ──────────────────────────────────────

export interface Bucket { label: string; from?: IsoDate; to?: IsoDate; in_firm: number; in_est: number; out_firm: number; out_est: number; bal_firm: N; bal_all: N }

/** render.month_flow: 첫 막대 = 보고 달(1일~기준일 통장 실적 + 남은 예정), 그 뒤 달마다 예정. */
export function monthFlow(R: Obj): { buckets: Bucket[]; start: N; first: IsoDate } {
  const s1 = R["s1"] as Obj, s2 = R["s2"] as Obj, asof = R["asof"] as IsoDate;
  const first = firstOfMonth(asof);
  const bs: (Bucket & { ym: string })[] = [];
  for (let m = first; m <= s2["horizon"]; m = addMonths(m, 1)) {
    bs.push({ label: `${parseInt(m.slice(0, 4), 10)}년 ${parseInt(m.slice(5, 7), 10)}월`, ym: m.slice(0, 7),
      in_firm: 0, in_est: 0, out_firm: 0, out_est: 0, bal_firm: null, bal_all: null });
  }
  if (!bs.length) return { buckets: [], start: null, first };
  bs[0]!.in_firm = s1["in"];
  bs[0]!.out_firm = s1["out"];
  bs[0]!.label += addDays(asof, 1).slice(5, 7) !== asof.slice(5, 7) ? "(실적)" : "(실적+예정)";
  const idx = new Map(bs.map((b) => [b.ym, b]));
  for (const ev of s2["dated"] as Obj[]) {
    const b = idx.get(String(ev["date"]).slice(0, 7));
    if (!b) continue;
    const k = ((ev["io"] === "in" ? "in_" : "out_") + (countsIn(ev, "firm") ? "firm" : "est")) as "in_firm";
    b[k] += ev["amount"];
  }
  const known = new Set((s1["accounts"] as Obj[]).filter((a) => a["balance"] !== null).map((a) => a["account"]));
  const ext = ((s1["txns"] || []) as Obj[]).filter((t) => known.has(t["account"]) && t["cat"] !== "계좌간이체");
  const kIn = ext.filter((t) => t["io"] === "입금").reduce((s, t) => s + t["amount"], 0);
  const kOut = ext.filter((t) => t["io"] === "출금").reduce((s, t) => s + t["amount"], 0);
  const start: N = s2["start"] === null ? null : s2["start"] - kIn + kOut;
  let bf = start, ba = start;
  for (const b of bs) {
    if (start === null || bf === null || ba === null) continue;
    bf += b.in_firm - b.out_firm;
    ba += b.in_firm + b.in_est - b.out_firm - b.out_est;
    b.bal_firm = bf;
    b.bal_all = ba;
  }
  return { buckets: bs, start, first };
}

// ── 팀별 영업이익 (teamprofit.py) ────────────────────────────

const SPECIAL = ["미연결", "팀 미확인", "팀 미지정"];

function add(...vals: N[]): N {
  return vals.some((v) => v === null || v === undefined) ? null : (vals as number[]).reduce((s, v) => s + v, 0);
}

export interface TeamRow {
  label: string; kind: "team" | "hq_self" | "hq_total" | "other" | "unlinked" | "company";
  revenue: N; gp: N; salary: N; sga: N; net: N; heads: N; has_rev: boolean; alloc?: N; nonop_in?: N;
}
export interface Nonop { in: N; out: N; by_dept: [string, N, N][]; pretax: N; dep?: N }
export interface TeamTable { rows: TeamRow[]; company: TeamRow; dept_ok: boolean; nonop: Nonop }

interface Cost { salary: N; sga: N; heads: N; nonop_in: N; nonop_out: N; head_sum: N }

function deptCosts(rows: Obj[], months: string[]): Map<string, Cost> | null {
  const have = new Set(rows.map((r) => r["ym"]));
  if (!months.length || months.some((m) => !have.has(m))) return null;
  const out = new Map<string, Cost>();
  for (const r of rows) {
    if (!months.includes(r["ym"])) continue;
    const c = out.get(r["dept"]) ?? { salary: 0, sga: 0, heads: null, nonop_in: 0, nonop_out: 0, head_sum: 0 };
    c.salary = add(c.salary, r["salary"]);
    c.sga = add(c.sga, r["sga"]);
    const ok = r["has_nonop"] ?? false;
    c.nonop_in = add(c.nonop_in, ok ? r["nonop_in"] ?? null : null);
    c.nonop_out = add(c.nonop_out, ok ? r["nonop_out"] ?? null : null);
    c.head_sum = add(c.head_sum, r["heads"]);
    if (r["ym"] === months[months.length - 1]) c.heads = r["heads"];
    out.set(r["dept"], c);
  }
  if (months.length > 1) for (const c of out.values()) c.heads = c.head_sum === null ? null : c.head_sum / months.length;
  return out;
}

function monthsOf(ym: string, ytd: boolean): string[] {
  if (!ytd) return [ym];
  const y = ym.slice(0, 4), m = parseInt(ym.slice(5), 10);
  return Array.from({ length: m }, (_, i) => `${y}-${String(i + 1).padStart(2, "0")}`);
}

function row(label: string, kind: TeamRow["kind"], revenue: N = null, gp: N = null, salary: N = null, sga: N = null,
             heads: N = null, hasRev = true): TeamRow {
  const net = hasRev ? add(gp, salary !== null ? -salary : null, sga !== null ? -sga : null)
    : salary === null || sga === null ? null : -(salary + sga);
  return { label, kind, revenue, gp, salary, sga, net, heads, has_rev: hasRev };
}

/** teamprofit.build */
export function teamBuild(plTable: Obj[], deptRows: Obj[] | null, ym: string, ytd = false): TeamTable | null {
  const key = ytd ? "ytd" : "cur";
  const teams = new Map<string, Obj>();
  const special: [string, Obj][] = [];
  let company: Obj | null = null;
  for (const r of plTable) {
    const v = r[key] || { revenue: null, gp: null, common: null };
    if (r["unit"] === "회사") company = v;
    else if (r["unit"] === "팀") {
      if (r[key] === null || r[key] === undefined) continue;
      if (SPECIAL.includes(r["target"])) special.push([r["target"], v]);
      else teams.set(r["target"], v);
    }
  }
  if (company === null && !teams.size) return null;
  const costs = deptRows !== null && deptRows !== undefined ? deptCosts(deptRows, monthsOf(ym, ytd)) : null;
  const ckeys = costs ? [...costs.keys()] : [];
  const names = [...teams.keys(), ...ckeys.filter((d) => d.endsWith("팀") && !teams.has(d))];
  const zero = company !== null && company["revenue"] !== null && company["revenue"] !== undefined
    ? { revenue: 0, gp: 0 } : { revenue: null, gp: null };
  const nospace = (s: string) => s.split(/\s+/).join("");
  const cost = (d: string): [N, N, N] => {
    if (costs === null) return [null, null, null];
    const c = costs.get(d);
    if (!c) return ckeys.some((x) => nospace(x) === nospace(d)) ? [null, null, null] : [0, 0, 0];
    return [c.salary, c.sga, c.heads];
  };
  const teamRow = (t: string) => {
    const v = teams.get(t) ?? zero;
    const [s, g, hh] = cost(t);
    return row(t, "team", v["revenue"] ?? null, v["gp"] ?? null, s, g, hh);
  };
  let rows: TeamRow[] = [];
  const used = new Set<string>();
  for (const hq of ckeys.filter((d) => d.endsWith("본부"))) {
    const prefix = hq.slice(0, -2);
    const kids = names.filter((t) => t.startsWith(prefix) && t.endsWith("팀"));
    const group = kids.map(teamRow);
    const [s, g, hh] = cost(hq);
    const own = row(`${hq} 자체 비용`, "hq_self", null, null, s, g, hh, false);
    const tot = row(`${hq} 합계`, "hq_total", group.length ? add(...group.map((x) => x.revenue)) : 0,
      group.length ? add(...group.map((x) => x.gp)) : 0,
      add(...group.map((x) => x.salary), s), add(...group.map((x) => x.sga), g), add(...group.map((x) => x.heads), hh));
    rows.push(...group, own, tot);
    for (const k of [...kids, hq]) used.add(k);
  }
  rows = [...names.filter((t) => !used.has(t)).map(teamRow), ...rows];
  for (const d of ckeys) {
    if (used.has(d) || names.includes(d)) continue;
    const [s, g, hh] = cost(d);
    const r = row(d !== NO_DEPT ? d : "부서 없음 (분개장 부서명 빈칸)", "other", null, null, s, g, hh, false);
    r.nonop_in = costs!.get(d)!.nonop_in;
    rows.push(r);
  }
  for (const [name, v] of special) {
    rows.push(row(name === "미연결" ? `프로젝트 ${name}` : name, "unlinked", v["revenue"] ?? null, v["gp"] ?? null, 0, 0));
  }
  const cv = costs ? [...costs.values()] : [];
  const totalS = costs ? add(...cv.map((c) => c.salary)) : null;
  const totalG = costs ? add(...cv.map((c) => c.sga)) : null;
  const earners = costs ? [...costs.entries()].filter(([d]) => d.endsWith("팀") || d.endsWith("본부")).map(([, c]) => c.heads) : [];
  const comp = row("회사 전체 (영업이익)", "company", company ? company["revenue"] ?? null : null,
    company ? company["gp"] ?? null : null, totalS, totalG, earners.length ? add(...earners) : null);
  let nin: N = null, nout: N = null;
  let byDept: [string, N, N][] = [];
  if (costs && costs.size) {
    nin = add(...cv.map((c) => c.nonop_in));
    nout = add(...cv.map((c) => c.nonop_out));
    byDept = [...costs.entries()].filter(([, c]) => c.nonop_in || c.nonop_out).map(([d, c]) => [d, c.nonop_in, c.nonop_out]);
  }
  const nonop: Nonop = { in: nin, out: nout, by_dept: byDept, pretax: add(comp.net, nin, nout !== null ? -nout : null) };
  return { rows, company: comp, dept_ok: costs !== null, nonop };
}

/** teamprofit.allocate (인원 비율) */
export function teamAllocate(T: TeamTable): TeamTable {
  const teams = T.rows.filter((r) => r.kind === "team");
  for (const r of teams) r.alloc = null;
  const comp = T.company.net;
  if (!teams.length || comp === null || teams.some((r) => r.net === null || r.heads === null)) return T;
  const weight = teams.reduce((s, r) => s + (r.heads as number), 0);
  if (!weight) return T;
  const rest = comp - teams.reduce((s, r) => s + (r.net as number), 0);
  for (const r of teams) r.alloc = (r.net as number) + rest * (r.heads as number) / weight;
  return T;
}

/** teamprofit.build_ytd_alloc */
export function teamYtdAlloc(byMonth: [string, Obj[]][], deptRows: Obj[] | null): Map<string, N> {
  const out = new Map<string, N>();
  for (const [m, table] of byMonth) {
    const T = teamBuild(table, deptRows, m, false);
    if (T === null) return new Map();
    teamAllocate(T);
    for (const r of T.rows) if (r.kind === "team") out.set(r.label, add(out.has(r.label) ? out.get(r.label)! : 0, r.alloc ?? null));
  }
  return out;
}

/** render._dep_into 의 금액 부분: 감가상각비 예상을 결산 줄에 넣고 세전 이익에서 뺀다. 줄 이름 뒤 풀이를 돌려준다. */
export function depInto(R: Obj, T: TeamTable, ytd: boolean): string {
  const dep = (R["dep"] || {}) as Obj;
  const amount = dep[ytd ? "extra" : "cur"];
  if (amount === null || amount === undefined) return "";
  T.nonop.dep = amount;
  if (amount && T.nonop.pretax !== null) T.nonop.pretax -= amount;
  const src = ({ "작년 장부": "작년", "고정자산대장": "위하고 고정자산대장" } as Record<string, string>)[dep["source"]] ?? "입력";
  let note = ytd
    ? dep["mode"] === "prorate" ? `, ${src} ${won(dep["annual"])} × ${dep["months"]}/12` : `, ${src} 연간 ${won(dep["annual"])}`
    : `, ${src} ${won(dep["annual"])} ÷ 12`;
  if (dep["booked"]) note += ` − 장부 반영 ${won(dep["booked"])}`;
  return note;
}

/** 손익.csv 회사 줄 (cur·ytd), 없으면 null */
export function companyPl(R: Obj): { cur: Obj | null; ytd: Obj | null; src: Obj | null; key: string } {
  const src = (R["s4"]?.["sources"]?.["WEHAGO"] ?? null) as Obj | null;
  const i = src ? (src["table"] as Obj[]).findIndex((r) => r["unit"] === "회사") : -1;
  const co = i >= 0 ? (src!["table"] as Obj[])[i]! : null;
  return { cur: co?.["cur"] ?? null, ytd: co?.["ytd"] ?? null, src, key: `R:s4.sources.WEHAGO.table.${i}` };
}

/** 이번 달 회사 영업이익 = 팀 표 회사 영업이익이 있으면 그것 (render._month_rev_np) */
export function monthNp(R: Obj): N {
  const { cur, src } = companyPl(R);
  if (!cur || !src) return null;
  let np: N = cur["np"];
  const dept = R["s4"]["dept"];
  if (dept !== null && dept !== undefined) {
    const T = teamBuild(src["table"], dept, R["s4"]["ym"], false);
    if (T !== null && T.company.net !== null) np = T.company.net;
  }
  return np;
}

/** render._month_series: 1월~보고 달 [연월, 매출, 매입, 영업이익]. 매출·매입은 증빙월별(계산서 기준), 없으면 매출=손익·매입=null */
export function monthSeries(R: Obj): [string, N, N, N][] {
  const s4 = R["s4"] as Obj;
  const src = (s4["sources"]?.["WEHAGO"] || {}) as Obj;
  const year = String(s4["ym"]).slice(0, 4);
  const ev = (R["evid_month"] ?? null) as Record<string, [number, number]> | null;
  const pl = new Map<string, [N, N]>();
  for (const [m, table] of (src["by_month"] || []) as [string, Obj[]][]) {
    if (m.slice(0, 4) !== year || m > s4["ym"]) continue;
    const co = table.filter((r) => r["unit"] === "회사");
    if (!co.length || !co[0]!["cur"]) continue;
    const c = co[0]!["cur"];
    let np: N = c["np"];
    if (s4["dept"] !== null && s4["dept"] !== undefined) {
      const T = teamBuild(table, s4["dept"], m, false);
      if (T !== null && T.company.net !== null) np = T.company.net;
    }
    pl.set(m, [c["revenue"], np]);
  }
  const months = new Set(pl.keys());
  if (ev !== null) for (const m of Object.keys(ev)) if (m.slice(0, 4) === year && m <= s4["ym"]) months.add(m);
  return [...months].sort().map((m) => {
    const [rev, np] = pl.get(m) ?? [null, null];
    if (ev !== null) {
      const [sale, buy] = ev[m] ?? [0, 0];
      return [m, sale, buy, np] as [string, N, N, N];
    }
    return [m, rev, null, np] as [string, N, N, N];
  });
}

/** insights.missing_contracts */
export function missingContracts(R: Obj): number {
  return ((R["s3"]?.["projects"] || []) as Obj[]).filter((p) => !p["contract"]).length;
}
