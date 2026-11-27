// convert_pl.py: 손익.csv, 부서비용.csv, 사원급여.csv, 부서계정비용.csv, 계정별비용.csv
import { SCHEMA } from "../model/data";
import { cmpStr, pyStrip, sortedBy, type SortKey } from "../model/py";
import { num, won } from "../model/util";
import type { Cfg } from "./config";
import type { LinkResult, Projects } from "./linking";
import { CONVERT_RULES } from "./rules";
import { cellAmount, check, Table, type Check, type TRow } from "./table";
import { squash, type Books, type JLine } from "./wehago";

export const DEPT_FILE = "부서비용.csv";
export const DEPT_KEYS = ["연월", "부서", "급여", "판관비", "인원"];
export const DEPT_OPTIONAL = ["영업외수익", "영업외비용"];
export const DEPT_COLUMNS = [...DEPT_KEYS, ...DEPT_OPTIONAL];
export const NO_DEPT = "부서 없음";
export const STAFF_FILE = "사원급여.csv";
export const STAFF_KEYS = ["연월", "부서", "사원명", "급여"];
export const DEPT_ACCOUNT_FILE = "부서계정비용.csv";
export const DEPT_ACCOUNT_KEYS = ["연월", "부서", "계정코드", "계정과목", "금액"];
export const ACCOUNT_FILE = "계정별비용.csv";
export const ACCOUNT_KEYS = ["연월", "구분", "계정코드", "계정과목", "금액"];

type Cat = "revenue" | "direct" | "common";
const CATEGORIES: [Cat, string, string][] = [["revenue", "매출", "매출"], ["direct", "직접비", "직접비"], ["common", "공통비", "공통비"]];
type Pair = [number, number];

export function classify(line: JLine, cfg: Cfg): string | null {
  const code = squash(line.account_code);
  const name = squash(line.account);
  if (cfg.revenue_codes.includes(code)) return "revenue";
  if (/^[0-9]{5}$/.test(code)) {
    if (cfg.direct_prefixes.some((p) => code.startsWith(p)) && name.includes(squash(cfg.direct_mark))) return "direct";
    if (cfg.common_prefixes.some((p) => code.startsWith(p))) return name.includes(squash(cfg.common_mark)) ? "common" : "common_unmarked";
  }
  if (/^[4-9][0-9]*$/.test(code)) return "excluded";
  return null;
}

export function net(line: JLine, kind: string): number | null {
  const d = line.debit, c = line.credit;
  if (d === null && c === null) return null;
  return kind === "revenue" ? (c || 0) - (d || 0) : (d || 0) - (c || 0);
}

function prefixText(prefixes: string[]): string {
  return prefixes.map((p) => p + "x".repeat(Math.max(0, 5 - p.length))).join(",");
}

function labels(cfg: Cfg): Record<Cat, string> {
  return { revenue: `매출 (${cfg.revenue_codes.join(",")} 대변−차변)`, direct: `직접비 (${prefixText(cfg.direct_prefixes)} ${cfg.direct_mark} 차변−대변)`,
    common: `공통비 (${prefixText(cfg.common_prefixes)} 차변−대변)` };
}

const ymOf = (d: string) => d.slice(0, 7);
const yearOf = (d: string) => Number(d.slice(0, 4));

type Group = Map<string, { code: string; name: string; v: [number, number, number] }>;

function plRows(books: Books, cfg: Cfg) {
  const months = new Set<string>();
  const closed = new Set<number>();
  const closing = new Set(cfg.closing_sorts.map(squash));
  for (const line of books.journal) {
    if (line.date !== null) {
      months.add(ymOf(line.date));
      if (closing.has(squash(line.sort ?? ""))) closed.add(yearOf(line.date));
    }
  }
  const per = new Map<string, Record<Cat, Pair>>();
  for (const m of [...months].sort(cmpStr)) per.set(m, { revenue: [0, 0], direct: [0, 0], common: [0, 0] });
  const undated: Record<Cat, [number, number, number]> = { revenue: [0, 0, 0], direct: [0, 0, 0], common: [0, 0, 0] };
  const source: Record<Cat, number> = { revenue: 0, direct: 0, common: 0 };
  const excluded: Group = new Map(), unmarked: Group = new Map();
  const addG = (g: Group, line: JLine, amount: number | null) => {
    const code = squash(line.account_code);
    const k = code + "\u0000" + line.account;
    if (!g.has(k)) g.set(k, { code, name: line.account, v: [0, 0, 0] });
    const x = g.get(k)!.v;
    x[0]++;
    if (amount === null) x[2]++;
    else x[1] += amount;
  };
  for (const line of books.journal) {
    const kind = classify(line, cfg);
    if (kind === null) continue;
    if (kind === "excluded") { addG(excluded, line, net(line, "excluded")); continue; }
    const cat = (kind === "common_unmarked" ? "common" : kind) as Cat;
    const amount = net(line, cat);
    if (kind === "common_unmarked") addG(unmarked, line, amount);
    if (amount !== null) source[cat] += amount;
    if (line.date === null) {
      const u = undated[cat];
      u[0]++;
      if (amount === null) u[2]++;
      else u[1] += amount;
      continue;
    }
    const cell = per.get(ymOf(line.date))![cat];
    if (amount === null) cell[1]++;
    else cell[0] += amount;
  }
  return { per, undated, source, excluded, unmarked, closed };
}

function listing(groups: Group): string {
  return sortedBy([...groups.values()], (g) => [g.code, g.name]).map(({ code, name, v: [n, total, unknown] }) =>
    `${code} ${name} ${n}줄 ${won(total)}` + (unknown ? ` (금액 없음 ${unknown}줄 제외)` : "")).join(" · ");
}

export const UNLINKED_PROJECT = "프로젝트 미연결";
const UNLINKED_TEAM = "미연결";
const MEASURES: ["revenue" | "direct", string][] = [["revenue", "매출"], ["direct", "직접비"]];
const UNASSIGNED_TEAM = "팀 미지정";
type Cells = { revenue: Pair; direct: Pair };

export interface PlLinks { costs: LinkResult; revenue: LinkResult; projects: Projects; snapshot: boolean }

const NONE = "\u0000none";

function unitTotals(links: PlLinks): Map<string, Map<string, Cells>> {
  const acc = new Map<string, Map<string, Cells>>();
  for (const [measure, result] of [["direct", links.costs], ["revenue", links.revenue]] as const) {
    for (const ln of result.lines) {
      if (ln.date === null) continue;
      const ym = ymOf(ln.date);
      if (!acc.has(ym)) acc.set(ym, new Map());
      const units = acc.get(ym)!;
      const k = ln.project ?? NONE;
      if (!units.has(k)) units.set(k, { revenue: [0, 0], direct: [0, 0] });
      const cell = units.get(k)![measure];
      if (ln.amount === null) cell[1]++;
      else cell[0] += ln.amount;
    }
  }
  return acc;
}

function projectOrder(keys: string[], projects: Projects): string[] {
  const real = keys.filter((k) => k !== NONE);
  const listed = [...projects.keys()].filter((k) => real.includes(k));
  const rest = real.filter((k) => !projects.has(k)).sort(cmpStr);
  return [...listed, ...rest, ...(keys.includes(NONE) ? [NONE] : [])];
}

const cellOf = (p: Pair): number | null => (p[1] ? null : p[0]);

function teamOf(key: string, projects: Projects): string {
  if (key === NONE) return UNLINKED_TEAM;
  if (!projects.has(key)) return "팀 미확인";
  return pyStrip(projects.get(key)!.team || "") || "팀 미지정";
}

function teamTotals(units: Map<string, Cells>, projects: Projects): Map<string, Cells> {
  const teams = new Map<string, Cells>();
  for (const [key, cells] of units) {
    const name = teamOf(key, projects);
    if (!teams.has(name)) teams.set(name, { revenue: [0, 0], direct: [0, 0] });
    const t = teams.get(name)!;
    for (const [m] of MEASURES) { t[m][0] += cells[m][0]; t[m][1] += cells[m][1]; }
  }
  const names = [...[...teams.keys()].filter((n) => n !== UNLINKED_TEAM).sort(cmpStr), ...(teams.has(UNLINKED_TEAM) ? [UNLINKED_TEAM] : [])];
  return new Map(names.map((n) => [n, teams.get(n)!]));
}

function deptTeamTotals(books: Books, cfg: Cfg): Map<string, Map<string, Cells>> | null {
  if (!books.journal.some((ln) => "dept" in ln && ln.dept !== undefined)) return null;
  const out = new Map<string, Map<string, Cells>>();
  for (const ln of books.journal) {
    const kind = classify(ln, cfg);
    if ((kind !== "revenue" && kind !== "direct") || ln.date === null) continue;
    const dept = squash(ln.dept);
    const team = dept.endsWith("팀") ? dept : UNASSIGNED_TEAM;
    const ym = ymOf(ln.date);
    if (!out.has(ym)) out.set(ym, new Map());
    const t = out.get(ym)!;
    if (!t.has(team)) t.set(team, { revenue: [0, 0], direct: [0, 0] });
    const cell = t.get(team)![kind];
    const amount = net(ln, kind);
    if (amount === null) cell[1]++;
    else cell[0] += amount;
  }
  const res = new Map<string, Map<string, Cells>>();
  for (const ym of [...out.keys()].sort(cmpStr)) {
    const t = out.get(ym)!;
    res.set(ym, new Map(sortedBy([...t.keys()], (n) => [n === UNASSIGNED_TEAM, n]).map((n) => [n, t.get(n)!])));
  }
  return res;
}

const PL_COLUMNS = SCHEMA["손익.csv"] as string[];

function zip(columns: string[], values: (string | number | null)[]): TRow {
  const o: TRow = {};
  columns.forEach((c, i) => { if (i < values.length) o[c] = values[i]; });
  return o;
}

function teamRow(ym: string, name: string, cells: Cells, final: boolean): TRow {
  return zip(PL_COLUMNS, ["WEHAGO", ym, "팀", name, cellAmount(cellOf(cells.revenue)), cellAmount(cellOf(cells.direct)), "", final ? "" : "Y"]);
}

function unitChecks(ym: string, company: { revenue: number | null; direct: number | null }, kind: string, groups: Cells[]): Check[] {
  return MEASURES.map(([m, label]) => {
    const unknown = groups.some((g) => g[m][1]);
    return check(`${label} ${ym} ${kind} 합계(미연결 포함) = 회사`, company[m], unknown ? null : groups.reduce((s, g) => s + g[m][0], 0));
  });
}

function projectRow(ym: string, key: string, cells: Cells, projects: Projects, snapshot: boolean, final: boolean): TRow {
  let target: string;
  if (key === NONE) target = UNLINKED_PROJECT;
  else if (!snapshot) target = key;
  else if (projects.has(key)) target = pyStrip(`${key} ${projects.get(key)!.name}`);
  else target = `${key} (프로젝트 목록에 없음)`;
  return zip(PL_COLUMNS, ["WEHAGO", ym, "프로젝트", target, cellAmount(cellOf(cells.revenue)), cellAmount(cellOf(cells.direct)), "", final ? "" : "Y"]);
}

const nextYm = (y: number, m: number): [number, number] => (m === 12 ? [y + 1, 1] : [y, m + 1]);
const fmtYm = (y: number, m: number) => String(y).padStart(4, "0") + "-" + String(m).padStart(2, "0");

export function monthSpan(months: string[]): Set<string> {
  if (!months.length) return new Set();
  const first = months.reduce((a, b) => (cmpStr(b, a) < 0 ? b : a));
  const last = months.reduce((a, b) => (cmpStr(b, a) > 0 ? b : a));
  let y = Number(first.slice(0, 4)), m = Number(first.slice(5, 7));
  const out = new Set<string>();
  while (cmpStr(fmtYm(y, m), last) <= 0) {
    out.add(fmtYm(y, m));
    [y, m] = nextYm(y, m);
  }
  return out;
}

function ranges(months: string[]): string {
  const uniq = [...new Set(months)];
  const good = uniq.filter((m) => /^\d{4}-\d{2}$/.test(m)).sort(cmpStr);
  const odd = uniq.filter((m) => !/^\d{4}-\d{2}$/.test(m)).sort(cmpStr);
  const parts: string[] = [];
  let start: string | null = null, prev: string | null = null;
  for (const m of good) {
    if (prev !== null) {
      const sp = monthSpan([prev, m]);
      if (sp.size === 2 && sp.has(prev) && sp.has(m)) { prev = m; continue; }
    }
    if (start !== null) parts.push(start === prev ? start : `${start}~${prev}`);
    start = prev = m;
  }
  if (start !== null) parts.push(start === prev ? start : `${start}~${prev}`);
  return [...parts, ...odd.map((o) => o || "(연월 없음)")].join(", ");
}

const rv = (r: TRow, k: string): string => (r[k] === undefined || r[k] === null ? "" : String(r[k]));
const ymr = (r: TRow) => pyStrip(rv(r, "연월")).slice(0, 7);

function companySum(rows: TRow[], year: string, measure: string): number | null {
  let total = 0;
  for (const r of rows) {
    if (rv(r, "출처") === "WEHAGO" && rv(r, "단위") === "회사" && ymr(r).startsWith(year + "-")) {
      const v = num(r[measure] ?? null);
      if (v === null) return null;
      total += v;
    }
  }
  return total;
}

function keptRow(r: TRow): TRow {
  const out: TRow = {};
  for (const c of PL_COLUMNS) out[c] = pyStrip(rv(r, c));
  for (const c of ["매출", "직접비", "공통비"]) {
    const v = num(out[c]);
    if (v !== null) out[c] = cellAmount(v);
  }
  return out;
}

function ytdChecks(perCompany: Map<string, Record<Cat, number | null>>, prevRows: TRow[], rows: TRow[]): Check[] {
  const months = [...perCompany.keys()].sort(cmpStr);
  if (!months.length) return [];
  const covered = monthSpan(months);
  const year = (months[months.length - 1] as string).slice(0, 4);
  const kept = prevRows.filter((r) => rv(r, "출처") === "WEHAGO" && !covered.has(ymr(r)));
  return CATEGORIES.map(([key, label, measure]) => {
    let nw: number | null = 0;
    for (const ym of months) {
      if (ym.startsWith(year + "-")) {
        const v = perCompany.get(ym)![key];
        nw = v === null || nw === null ? null : nw + v;
      }
    }
    const old = companySum(kept, year, measure);
    const source = nw === null || old === null ? null : nw + old;
    return check(`올해(${year}) 누계 ${label}: 새 분개장 + 이전 변환 유지 달 = CSV 회사 줄`, source, companySum(rows, year, measure));
  });
}

/** build_pl */
export function buildPl(books: Books, cfg: Cfg, prevRows: TRow[], links: PlLinks | null): Table {
  const { per, undated, source, excluded, unmarked, closed } = plRows(books, cfg);
  let rows: TRow[] = [];
  const notes: string[] = [];
  const csvSum: Record<Cat, number> = { revenue: 0, direct: 0, common: 0 };
  const csvUnknown: Record<Cat, boolean> = { revenue: false, direct: false, common: false };
  const units0 = links !== null ? unitTotals(links) : new Map<string, Map<string, Cells>>();
  const byDept = deptTeamTotals(books, cfg);
  const unitCk: Check[] = [];
  const perCompany = new Map<string, Record<Cat, number | null>>();
  for (const [ym, cats] of per) {
    const cells: Record<Cat, number | null> = { revenue: null, direct: null, common: null };
    for (const [key, label] of CATEGORIES) {
      const [total, unknown] = cats[key];
      if (unknown) {
        cells[key] = null;
        csvUnknown[key] = true;
        notes.push(`금액 없는 손익 줄 ${unknown}건 (${ym} ${label}) → 그 달 칸 비움`);
      } else {
        cells[key] = total;
        csvSum[key] += total;
      }
    }
    perCompany.set(ym, { ...cells });
    const final = closed.has(Number(ym.slice(0, 4)));
    rows.push(zip(PL_COLUMNS, ["WEHAGO", ym, "회사", "회사 전체", cellAmount(cells.revenue), cellAmount(cells.direct), cellAmount(cells.common), final ? "" : "Y"]));
    if (byDept !== null) {
      const teams = byDept.get(ym) ?? new Map<string, Cells>();
      for (const [n, c] of teams) rows.push(teamRow(ym, n, c, final));
      unitCk.push(...unitChecks(ym, { revenue: cells.revenue, direct: cells.direct }, "팀별", [...teams.values()]));
    }
    if (links !== null) {
      const units = units0.get(ym) ?? new Map<string, Cells>();
      const company = { revenue: cells.revenue, direct: cells.direct };
      if (byDept === null && links.snapshot) {
        const teams = teamTotals(units, links.projects);
        for (const [n, c] of teams) rows.push(teamRow(ym, n, c, final));
        unitCk.push(...unitChecks(ym, company, "팀별", [...teams.values()]));
      }
      const keys = projectOrder([...units.keys()], links.projects);
      for (const k of keys) rows.push(projectRow(ym, k, units.get(k)!, links.projects, links.snapshot, final));
      unitCk.push(...unitChecks(ym, company, "프로젝트별", keys.map((k) => units.get(k)!)));
    }
  }
  const lb = labels(cfg);
  const checks: Check[] = CATEGORIES.map(([k]) => check(lb[k], source[k], csvUnknown[k] ? null : csvSum[k]));
  checks.push(...unitCk);
  if (links !== null) {
    if (byDept === null && !links.snapshot) notes.push("팀별 손익 없음 (분개장 부서명 칸·인트라넷 스냅숏 없음)");
    notes.push("팀·프로젝트 줄의 공통비는 비워 둠 (배분 규칙 없음)");
  }
  for (const [key, label] of CATEGORIES) {
    const [n, total, unknown] = undated[key];
    if (n) notes.push(`날짜 없는 손익 줄 ${n}건 (${label}) ${won(total)}` + (unknown ? ` · 금액 없음 ${unknown}건` : ""));
  }
  if (excluded.size) notes.push("손익.csv에 넣지 않은 손익 계정: " + listing(excluded));
  if (unmarked.size) notes.push(`공통비 중 ${cfg.common_mark} 표시 없음: ${listing(unmarked)} (공통비에 넣음)`);
  const dated = books.journal.filter((l) => l.date !== null).map((l) => l.date as string);
  if (dated.length) notes.push(`분개장 기간 ${dated.reduce((a, b) => (b < a ? b : a))}~${dated.reduce((a, b) => (b > a ? b : a))}`);
  const covered = monthSpan([...per.keys()]);
  const carried = prevRows.filter((r) => rv(r, "출처") !== "WEHAGO");
  const replaced = prevRows.filter((r) => rv(r, "출처") === "WEHAGO" && covered.has(ymr(r)));
  const kept = prevRows.filter((r) => rv(r, "출처") === "WEHAGO" && !covered.has(ymr(r)));
  const unitText = (group: TRow[]) => {
    const units = new Map<string, number>();
    for (const r of group) {
      const u = rv(r, "단위") || "(단위 없음)";
      units.set(u, (units.get(u) ?? 0) + 1);
    }
    return [...units].map(([u, n]) => `${u} ${n}`).join(" · ");
  };
  if (replaced.length) notes.push(`이전 손익.csv의 WEHAGO 줄 ${replaced.length}건(${unitText(replaced)})은 새로 만든 줄로 바꿈`);
  if (kept.length) {
    const cov = [...covered].sort(cmpStr);
    const span = cov.length ? `${cov[0]}~${cov[cov.length - 1]}` : "전표 없음";
    notes.push(`이전 변환 유지 ${ranges(kept.map(ymr))} (WEHAGO 줄 ${kept.length}건: ${unitText(kept)}) — 새 분개장(${span})에 없는 달`);
    const first = cov.length ? (cov[0] as string) : "";
    const before = kept.filter((r) => cov.length && cmpStr(ymr(r), first) < 0).map(keptRow);
    const after = kept.filter((r) => !(cov.length && cmpStr(ymr(r), first) < 0)).map(keptRow);
    rows = [...before, ...rows, ...after];
  }
  checks.push(...ytdChecks(perCompany, prevRows, rows));
  if (carried.length) {
    notes.push(`이전 손익.csv의 WEHAGO 외 출처 줄 ${carried.length}건 그대로 옮김`);
    for (const r of carried) {
      const o: TRow = {};
      for (const c of PL_COLUMNS) o[c] = r[c] === undefined ? "" : r[c];
      rows.push(o);
    }
  }
  return new Table("손익.csv", PL_COLUMNS, rows, { checks, notes });
}

// ───────────── 부서별 급여·판관비 ─────────────
interface DeptCell { salary: Pair; sga: Pair; nonop_in: Pair; nonop_out: Pair; names: Map<string, number | null>; nameless: number }
const deptCell = (): DeptCell => ({ salary: [0, 0], sga: [0, 0], nonop_in: [0, 0], nonop_out: [0, 0], names: new Map(), nameless: 0 });

const hasKey = (books: Books, k: "dept" | "employee") => books.journal.some((ln) => ln[k] !== undefined);

/** I6 고침 스위치: 켜면 새 분개장 기간(처음~마지막 전표 달)의 이전 줄은 모두 버린다 (그 달 줄이 다 사라져도 옛 값이 남지 않게). */
function keepPrev(prevRows: TRow[], months: Set<string>, books: Books): TRow[] {
  let drop = months;
  if (CONVERT_RULES.cumulativeDropCoveredMonths) {
    const dated = books.journal.filter((l) => l.date !== null).map((l) => ymOf(l.date as string));
    drop = new Set([...months, ...monthSpan(dated)]);
  }
  return prevRows.filter((r) => !drop.has(rv(r, "연월")));
}

export function buildDept(books: Books, cfg: Cfg, prevRows: TRow[] = []): Table {
  const lines = books.journal.filter((ln) => ["common", "common_unmarked"].includes(classify(ln, cfg) ?? ""));
  const nin = new Set(cfg.nonop_in_codes.map(squash)), nout = new Set(cfg.nonop_out_codes.map(squash));
  const nonop = books.journal.filter((ln) => nin.has(squash(ln.account_code)) || nout.has(squash(ln.account_code)));
  if (!hasKey(books, "dept")) return new Table(DEPT_FILE, DEPT_COLUMNS, [], { written: false, reason: "분개장에 부서명(관리항목) 칸 없음 (기존 파일 그대로)" });
  const salary = new Set(cfg.salary_codes.map(squash));
  const cells = new Map<string, [string, string, DeptCell]>();
  const get = (ym: string, dept: string) => {
    const k = ym + "\u0000" + dept;
    if (!cells.has(k)) cells.set(k, [ym, dept, deptCell()]);
    return cells.get(k)![2];
  };
  let source = 0, undatedN = 0, unknownLines = 0;
  for (const ln of lines) {
    if (ln.date === null) { undatedN++; continue; }
    const c = get(ymOf(ln.date), ln.dept || NO_DEPT);
    const isSalary = salary.has(squash(ln.account_code));
    const amount = net(ln, "common");
    const cell = c[isSalary ? "salary" : "sga"];
    if (amount === null) { cell[1]++; unknownLines++; }
    else { cell[0] += amount; source += amount; }
    if (isSalary) {
      if (ln.employee) {
        const got = c.names.has(ln.employee) ? c.names.get(ln.employee)! : 0;
        c.names.set(ln.employee, got === null || amount === null ? null : got + amount);
      } else c.nameless++;
    }
  }
  for (const ln of nonop) {
    if (ln.date === null) { undatedN++; continue; }
    const c = get(ymOf(ln.date), ln.dept || NO_DEPT);
    const isIn = nin.has(squash(ln.account_code));
    const amount = net(ln, isIn ? "revenue" : "common");
    const cell = c[isIn ? "nonop_in" : "nonop_out"];
    if (amount === null) { cell[1]++; unknownLines++; }
    else cell[0] += amount;
  }
  const months = new Set([...cells.values()].map((v) => v[0]));
  const rows = keepPrev(prevRows, months, books);
  for (const [ym, dept, c] of sortedBy([...cells.values()], (v) => [v[0], v[1]])) {
    const paid = [...c.names.entries()].filter(([, v]) => v === null || v > 0);
    const heads = c.nameless || !paid.length ? "" : String(paid.length);
    rows.push(zip(DEPT_COLUMNS, [ym, dept, cellAmount(cellOf(c.salary)), cellAmount(cellOf(c.sga)), heads, cellAmount(cellOf(c.nonop_in)), cellAmount(cellOf(c.nonop_out))]));
  }
  let csvSum = 0;
  for (const [, , c] of cells.values()) csvSum += c.salary[0] + c.sga[0];
  const notes = [`급여 = 계정 ${cfg.salary_codes.join(",")} · 판관비 = 그 밖의 공통비(판) · 영업외 수익 = 계정 ${cfg.nonop_in_codes.join(",")} · 영업외 비용 = 계정 ${cfg.nonop_out_codes.join(",")} · 부서는 분개장 관리항목 부서명`];
  const other9 = new Map<string, [string, string, number]>();
  for (const ln of books.journal) {
    const code = squash(ln.account_code);
    if (/^9[0-9]{4}$/.test(code) && !nin.has(code) && !nout.has(code)) {
      const k = code + "\u0000" + ln.account;
      if (!other9.has(k)) other9.set(k, [code, ln.account, 0]);
      other9.get(k)![2]++;
    }
  }
  if (other9.size) notes.push("영업외로 넣지 않은 9로 시작하는 계정: " + [...other9.values()].map(([a, b, n]) => `${a} ${b} ${n}줄`).join(" · "));
  const nodept = lines.filter((ln) => ln.date !== null && !ln.dept).length;
  if (nodept) notes.push(`부서명 없는 공통비 줄 ${nodept}건 → '${NO_DEPT}'`);
  const nameless = [...cells.values()].reduce((s, v) => s + v[2].nameless, 0);
  if (nameless) notes.push(`사원명 없는 급여 줄 ${nameless}건 → 그 부서·달 인원 칸 비움`);
  if (undatedN) notes.push(`날짜 없는 공통비 줄 ${undatedN}건 → 넣지 않음`);
  if (unknownLines) notes.push(`금액 없는 공통비 줄 ${unknownLines}건 → 그 칸 비움`);
  return new Table(DEPT_FILE, DEPT_COLUMNS, rows, { checks: [check("부서별 급여+판관비 합계 = 분개장 공통비 합계 (날짜 있는 줄)", source, csvSum)], notes });
}

export function buildStaff(books: Books, cfg: Cfg, prevRows: TRow[] = []): Table {
  if (!hasKey(books, "employee")) return new Table(STAFF_FILE, STAFF_KEYS, [], { written: false, reason: "분개장에 사원명(관리항목) 칸 없음 (기존 파일 그대로)" });
  const salary = new Set(cfg.salary_codes.map(squash));
  const cells = new Map<string, [string, string, string, Pair]>();
  const months = new Set<string>();
  let nameless = 0;
  for (const ln of books.journal) {
    if (!salary.has(squash(ln.account_code)) || ln.date === null) continue;
    const ym = ymOf(ln.date);
    months.add(ym);
    if (!ln.employee) { nameless++; continue; }
    const dept = ln.dept || NO_DEPT;
    const k = ym + "\u0000" + dept + "\u0000" + ln.employee;
    if (!cells.has(k)) cells.set(k, [ym, dept, ln.employee, [0, 0]]);
    const c = cells.get(k)![3];
    const amount = net(ln, "common");
    if (amount === null) c[1]++;
    else c[0] += amount;
  }
  const rows = keepPrev(prevRows, months, books);
  for (const [ym, dept, name, c] of sortedBy([...cells.values()], (v) => [v[0], v[1], v[2]])) rows.push(zip(STAFF_KEYS, [ym, dept, name, cellAmount(cellOf(c))]));
  const notes = [`사원별 급여 = 계정 ${cfg.salary_codes.join(",")}, 부서는 분개장 관리항목 부서명 · ${new Set([...cells.values()].map((v) => v[2])).size}명`];
  if (nameless) notes.push(`사원명 없는 급여 줄 ${nameless}건 → 넣지 않음 (그 팀·달 1인당 몫은 미확인)`);
  return new Table(STAFF_FILE, STAFF_KEYS, rows, { notes });
}

export function buildDeptAccounts(books: Books, cfg: Cfg, prevRows: TRow[] = []): Table {
  if (!hasKey(books, "dept")) return new Table(DEPT_ACCOUNT_FILE, DEPT_ACCOUNT_KEYS, [], { written: false, reason: "분개장에 부서명(관리항목) 칸 없음 (기존 파일 그대로)" });
  const salary = new Set(cfg.salary_codes.map(squash));
  const cells = new Map<string, [string, string, string, { name: string; sum: Pair }]>();
  const months = new Set<string>();
  const perDept = new Map<string, Pair>();
  for (const ln of books.journal) {
    if (!["common", "common_unmarked"].includes(classify(ln, cfg) ?? "") || ln.date === null) continue;
    const ym = ymOf(ln.date);
    months.add(ym);
    const code = squash(ln.account_code);
    if (salary.has(code)) continue;
    const dept = ln.dept || NO_DEPT;
    const k = ym + "\u0000" + dept + "\u0000" + code;
    if (!cells.has(k)) cells.set(k, [ym, dept, code, { name: squash(ln.account), sum: [0, 0] }]);
    const c = cells.get(k)![3];
    const amount = net(ln, "common");
    const dk = ym + "\u0000" + dept;
    if (!perDept.has(dk)) perDept.set(dk, [0, 0]);
    const t = perDept.get(dk)!;
    if (amount === null) { c.sum[1]++; t[1]++; }
    else { c.sum[0] += amount; t[0] += amount; }
  }
  let rows = keepPrev(prevRows, months, books);
  for (const [ym, dept, code, c] of sortedBy([...cells.values()], (v) => [v[0], v[1], v[2]])) {
    rows.push(zip(DEPT_ACCOUNT_KEYS, [ym, dept, code, c.name, cellAmount(cellOf(c.sum))]));
  }
  rows = sortedBy(rows, (r) => [rv(r, "연월"), rv(r, "부서"), rv(r, "계정코드")] as SortKey);
  const total = [...perDept.values()].some((t) => t[1]) ? null : [...perDept.values()].reduce((s, t) => s + t[0], 0);
  let csvTotal: number | null = 0;
  for (const r of rows) {
    if (months.has(rv(r, "연월"))) {
      const v = num(r["금액"] ?? null);
      csvTotal = v === null || csvTotal === null ? null : csvTotal + v;
    }
  }
  const notes = [`부서별 판관비(급여 계정 ${cfg.salary_codes.join(",")} 뺀 공통비) 계정과목별 · 부서는 분개장 관리항목 부서명`];
  return new Table(DEPT_ACCOUNT_FILE, DEPT_ACCOUNT_KEYS, rows, { checks: [check("부서계정비용 합계 = 분개장 판관비(급여 뺀 공통비) 합계", total, csvTotal)], notes });
}

const ACCOUNT_GROUPS: Record<string, string> = { direct: "원가", common: "판매비와관리비", common_unmarked: "판매비와관리비", nonop_out: "영업외비용" };

export function buildAccounts(books: Books, cfg: Cfg, prevRows: TRow[] = []): Table {
  const nout = new Set(cfg.nonop_out_codes.map(squash));
  const cells = new Map<string, [string, string, string, { name: string; sum: Pair }]>();
  let undatedN = 0;
  for (const ln of books.journal) {
    const kind = nout.has(squash(ln.account_code)) ? "nonop_out" : classify(ln, cfg);
    if (kind === null || !(kind in ACCOUNT_GROUPS)) continue;
    if (ln.date === null) { undatedN++; continue; }
    const group = ACCOUNT_GROUPS[kind] as string;
    const code = squash(ln.account_code);
    const k = ymOf(ln.date) + "\u0000" + group + "\u0000" + code;
    if (!cells.has(k)) cells.set(k, [ymOf(ln.date), group, code, { name: squash(ln.account), sum: [0, 0] }]);
    const c = cells.get(k)![3];
    const amount = net(ln, "common");
    if (amount === null) c.sum[1]++;
    else c.sum[0] += amount;
  }
  const months = new Set([...cells.values()].map((v) => v[0]));
  let rows = keepPrev(prevRows, months, books);
  for (const [ym, group, code, c] of sortedBy([...cells.values()], (v) => [v[0], v[1], v[2]])) {
    rows.push(zip(ACCOUNT_KEYS, [ym, group, code, c.name, cellAmount(cellOf(c.sum))]));
  }
  rows = sortedBy(rows, (r) => [rv(r, "연월"), rv(r, "계정코드")] as SortKey);
  const notes = [`원가 = 직접비(도) · 판매비와관리비 = 공통비 · 영업외비용 = 계정 ${cfg.nonop_out_codes.join(",")} · 금액 = 차변 − 대변`];
  if (undatedN) notes.push(`날짜 없는 비용 줄 ${undatedN}건 → 넣지 않음`);
  return new Table(ACCOUNT_FILE, ACCOUNT_KEYS, rows, { notes });
}
