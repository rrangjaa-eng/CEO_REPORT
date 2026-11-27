// linking.py: WEHAGO 원가·매출 줄을 프로젝트에 잇는다 (수동 → 프로젝트명 칸 → 적요 [코드] → 자동 → 미연결).
import { addDays, weekday, type IsoDate } from "../model/dates";
import { cmpStr, pyIsDigit, pyStrip, sortedBy } from "../model/py";
import { Issues, maskRrn, num, parseDate, type Row } from "../model/util";
import { normCode, normVendor } from "../model/vendor";
import { join, readCsvFile, exists, type ConvFiles } from "./files";
import type { OldData, Rec, Snapshot } from "./snapshot";
import { normProject, parseRegistered, projectCode, squash, type Books, type JLine, type Request } from "./wehago";

export const LINK_FILE = "프로젝트연결.csv";
export const LINK_COLUMNS = ["전표일자", "전표번호", "줄", "프로젝트번호"];
export const BASES = ["수동", "코드", "자동", "미연결"];
export const MANUAL_LABEL = "수동 (프로젝트연결.csv)";
export const MANUAL_UNKNOWN_LABEL = "수동 (프로젝트연결.csv · 프로젝트 목록에 없는 번호)";
export const NO_LIST = "프로젝트 목록 없음";

// screen_values
export const CEO_APPROVED = ["수락완료", "승인"];
export const CEO_PENDING = ["미승인", "수락요청중"];
export const PROJECT_STAGE_DONE = ["완료", "수락완료", "승인완료", "반려"];
export const PROJECT_STAGE_ALL_DONE = ["완료", "수락완료", "승인완료"];

export function ceoStatus(text: string | null | undefined): string {
  const t = pyStrip(text || "");
  if (CEO_APPROVED.includes(t)) return "approved";
  if (CEO_PENDING.includes(t)) return "pending";
  return "status_unknown";
}

/** 'YYYY-MM-DDTHH:MM:SS' 날짜시각 → [날짜, 초(하루 안)] */
function splitDt(s: string): [IsoDate, number] {
  const d = s.slice(0, 10);
  const t = s.slice(11);
  const [h, m, sec] = (t ? t.split(":").map(Number) : [0, 0, 0]) as [number, number, number];
  return [d, (h || 0) * 3600 + (m || 0) * 60 + (sec || 0)];
}

/** approval.friday_after: ref 이후(엄격히) 처음 오는 목요일 14:00 마감의 다음 날 금요일. */
export function fridayAfter(ref: string): IsoDate {
  const [d, sec] = splitDt(ref);
  let day = addDays(d, (((3 - weekday(d)) % 7) + 7) % 7);
  if (day < d || (day === d && 14 * 3600 <= sec)) day = addDays(day, 7);
  return addDays(day, 1);
}

/** approval._expected_date */
export function expectedDate(rq: Request, asof: IsoDate, now: string): [IsoDate | null, string] {
  const req = rq.request_date;
  if (req && req > asof) return [req, "지급요청일"];
  if (rq.status === "pending") {
    if (req) return [fridayAfter(now), "지급요청일 지남·대기 중 → 목요일 14시 승인·금요일 지급 (지금 기준)"];
    if (rq.registered !== null) return [fridayAfter(now), "지급요청일 없음 → 목요일 14시 승인·금요일 지급 (지금 기준)"];
    return [null, ""];
  }
  if (req) return [req, "지급요청일"];
  if (rq.registered !== null) return [fridayAfter(rq.registered), "지급요청일 없음 → 목요일 14시 승인·금요일 지급 (등록 시각 기준)"];
  return [null, ""];
}

function masked(rows: Rec[]): Rec[] {
  return rows.map((r) => {
    const o: Rec = {};
    for (const [k, v] of Object.entries(r)) o[k] = maskRrn(v);
    return o;
  });
}

const g = (r: Rec, k: string) => r[k] ?? "";

/** requests_of */
export function requestsOf(payments: Rec[] | null, asof: IsoDate, now: string): Request[] {
  const out: Request[] = [];
  if (payments === null) return out;
  masked(payments).forEach((row, k) => {
    const rq: Request = { id: `r${k}`, "번호": g(row, "번호"), name: g(row, "행사명"), vendor: g(row, "파트너"),
      code: projectCode(g(row, "행사명")), registered: parseRegistered(g(row, "등록일")), status: ceoStatus(g(row, "사장님승인")),
      amount: num(row["금액"] ?? null), request_date: parseDate(row["지급요청일"] ?? null), date: null, rule: "",
      status_text: pyStrip(row["사장님승인"] || "") };
    [rq.date, rq.rule] = expectedDate(rq, asof, now);
    out.push(rq);
  });
  return out;
}

export function oldRequests(old: OldData | null, asof: IsoDate, now: string): Request[] {
  if (!old || !old.payments.length) return [];
  const out = requestsOf(old.payments, asof, now);
  for (const rq of out) { rq.id = "o" + rq.id; rq.old = true; }
  return out;
}

export interface Project {
  key: string; old: boolean; name: string; team: string; client: string; client_norm: string; estimate: number | null;
  quote: number | null; budget: number | null; approval: string; event_date: IsoDate | null; dup: boolean;
  estimate_text: string; budget_text: string; event_text: string;
}

export type Projects = Map<string, Project>;

export const APPROVAL_STAGES = ["담당자", "팀장", "관리팀", "대표이사"];
export const APPROVAL_DONE = PROJECT_STAGE_DONE;

export function approvalStage(p: Rec): string {
  const cells = APPROVAL_STAGES.map((s) => pyStrip(p["승인_" + s] || ""));
  if (PROJECT_STAGE_ALL_DONE.includes(cells[0] as string) && !cells.slice(1).some((c) => c)) return APPROVAL_STAGES[3] as string;
  let stage = "";
  APPROVAL_STAGES.forEach((name, i) => {
    if (APPROVAL_DONE.includes(cells[i] as string)) stage = name;
  });
  return stage;
}

/** approval_words */
export function approvalWords(rows: Rec[]): string {
  const out: string[] = [];
  for (const s of APPROVAL_STAGES) {
    const c = new Map<string, number>();
    for (const p of rows) {
      const t = pyStrip(p["승인_" + s] || "") || "(빈칸)";
      c.set(t, (c.get(t) ?? 0) + 1);
    }
    const items = sortedBy([...c.entries()], (kv) => -kv[1]);
    out.push(`${s} ${items.map(([k, v]) => `'${k}' ${v}`).join(", ")}`);
  }
  return out.join(" · ");
}

function addProjects(out: Projects, rows: Rec[], isOld: boolean): void {
  for (const p of rows) {
    const title = g(p, "행사명");
    const key = projectCode(title) || normProject(g(p, "번호"));
    if (!key) continue;
    if (out.has(key)) {
      if (isOld) continue;
      out.get(key)!.dup = true;
      continue;
    }
    out.set(key, { key, old: isOld, name: title.replace(/^[\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*\[\p{Nd}+\][\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*/u, ""),
      team: g(p, "팀"), client: g(p, "클라이언트"), client_norm: normVendor(g(p, "클라이언트")), estimate: num(p["사전견적"] ?? null),
      quote: num(p["견적금액"] ?? null), budget: num(p["실행가"] ?? null), approval: isOld ? "" : approvalStage(p),
      event_date: parseDate(p["행사일"] ?? null), dup: false, estimate_text: pyStrip(p["사전견적"] || ""),
      budget_text: pyStrip(p["실행가"] || ""), event_text: pyStrip(p["행사일"] || "") });
  }
}

/** projects_of */
export function projectsOf(snap: Snapshot | null, old: OldData | null = null): Projects {
  const out: Projects = new Map();
  if (old === null) old = snap?.old ?? null;
  if (snap !== null) addProjects(out, masked(snap.projects), false);
  if (old !== null && old.projects.length) addProjects(out, masked(old.projects), true);
  return out;
}

// ───────────── 줄 열쇠 ─────────────
export function normNo(text: unknown): string {
  const s = pyStrip(text === null || text === undefined ? "" : String(text));
  return s.replace(/^(\p{Nd}+)\.0+$/u, "$1");
}

export type LineKey = [string, string, number];
export const lk = (k: LineKey) => k[0] + "\u0000" + k[1] + "\u0000" + k[2];

export function lineKeys(journal: JLine[]): LineKey[] {
  const seen = new Map<string, number>();
  const keys: LineKey[] = [];
  for (const row of journal) {
    const day = row.date ?? "";
    const no = normNo(row.no);
    const k = day + "\u0000" + no;
    seen.set(k, (seen.get(k) ?? 0) + 1);
    keys.push([day, no, seen.get(k)!]);
  }
  return keys;
}

/** 열쇠 → 프로젝트번호 (+ checks·unchecked) */
export class Links extends Map<string, string> {
  keys_: Map<string, LineKey> = new Map();
  checks: Map<string, [string, number | null]> | null = null;
  unchecked = 0;
  setKey(key: LineKey, project: string): void {
    this.set(lk(key), project);
    this.keys_.set(lk(key), key);
  }
}

function issueNotes(issues: Issues): string[] {
  return issues.items.map(([, line, msg]) => `${LINK_FILE} ${pyIsDigit(String(line)) ? `${line}번째 줄: ` : ""}${msg}`);
}

/** read_links */
export function readLinks(files: ConvFiles, inputDir: string): [Links, string[]] {
  const path = join(inputDir, LINK_FILE);
  if (!exists(files, path)) return [new Links(), [`${LINK_FILE} 없음 (수동 지정 0건)`]];
  const issues = new Issues();
  const info: { missing?: string[] } = {};
  const [rows, ok] = readCsvFile(files, path, LINK_COLUMNS, issues, info);
  if (!ok || (info.missing && info.missing.length)) return [new Links(), [...issueNotes(issues), `${LINK_FILE} 수동 지정 0건`]];
  const notes = issueNotes(issues);
  const picked = new Map<string, [LineKey, string[]]>();
  const checks = new Map<string, [string, number | null]>();
  let unchecked = 0;
  const gs = (r: Row, k: string) => (r[k] === undefined ? "" : String(r[k]));
  for (const row of rows) {
    const line = row._line;
    const day = parseDate(row["전표일자"] ?? null);
    const no = normNo(row["전표번호"] ?? null);
    const nth = pyStrip(gs(row, "줄"));
    let project = normProject(row["프로젝트번호"] ?? null);
    const m = /^\[(.*)\]$/s.exec(project);
    if (m) project = pyStrip(m[1] as string);
    const code = pyStrip(gs(row, "거래처코드"));
    const amount = pyStrip(gs(row, "금액")) ? num(row["금액"]) : null;
    let why: string | null = null;
    if (day === null) why = "전표일자를 날짜로 읽지 못함";
    else if (!no) why = "전표번호가 비어 있음";
    else if (!/^\p{Nd}+(\.0+)?$/u.test(nth) || Math.trunc(Number(nth)) < 1) why = "줄 값이 1 이상 정수가 아님";
    else if (!project) why = "프로젝트번호가 비어 있음";
    else if (pyStrip(gs(row, "금액")) && amount === null) why = "금액을 숫자로 읽지 못함";
    if (why) {
      notes.push(`${LINK_FILE} ${line}번째 줄: ${why} → 무시`);
      continue;
    }
    const key: LineKey = [day as string, no, Math.trunc(Number(nth))];
    if (!picked.has(lk(key))) picked.set(lk(key), [key, []]);
    picked.get(lk(key))![1].push(project);
    if (code || amount !== null) checks.set(lk(key), [code, amount]);
    else unchecked++;
  }
  const overrides = new Links();
  for (const [k, [key, projects]] of picked) {
    if (new Set(projects).size > 1) notes.push(`${LINK_FILE} 같은 줄(${key[0]} ${key[1]}-${key[2]})에 다른 프로젝트 지정 → 둘 다 무시`);
    else overrides.setKey(key, projects[0] as string);
    void k;
  }
  overrides.checks = new Map([...checks].filter(([k]) => overrides.has(k)));
  overrides.unchecked = unchecked;
  return [overrides, notes];
}

function sameLine(row: JLine, code: string, amount: number | null): boolean {
  if (code && normCode(row.vendor_code) !== normCode(code)) return false;
  if (amount !== null && ![Math.abs(row.debit || 0), Math.abs(row.credit || 0)].includes(Math.abs(amount))) return false;
  return true;
}

/** check_links */
export function checkLinks(journal: JLine[], overrides: Links): [Links, string[]] {
  const checks = overrides.checks ?? new Map();
  if (!checks.size) return [overrides, []];
  const keys = lineKeys(journal);
  const byKey = new Map<string, JLine>();
  keys.forEach((k, i) => { if (!byKey.has(lk(k))) byKey.set(lk(k), journal[i]!); });
  // dict(zip(keys, journal)): 같은 열쇠는 뒤가 이김 (열쇠는 겹치지 않음)
  const bySlip = new Map<string, [LineKey, JLine][]>();
  keys.forEach((k, i) => {
    const s = k[0] + "\u0000" + k[1];
    if (!bySlip.has(s)) bySlip.set(s, []);
    bySlip.get(s)!.push([k, journal[i]!]);
  });
  const out = new Links();
  for (const [k, v] of overrides) out.setKey(overrides.keys_.get(k)!, v);
  out.unchecked = overrides.unchecked;
  out.checks = new Map();
  const notes: string[] = [];
  for (const k of [...overrides.keys()]) {
    if (!checks.has(k)) continue;
    const key = overrides.keys_.get(k)!;
    const [code, amount] = checks.get(k)!;
    const row = byKey.get(k);
    if (row !== undefined && sameLine(row, code, amount)) {
      out.checks.set(k, checks.get(k)!);
      continue;
    }
    const project = out.get(k)!;
    out.delete(k);
    const cands = (bySlip.get(key[0] + "\u0000" + key[1]) ?? []).filter(([, r]) => sameLine(r, code, amount)).map(([c]) => c);
    if (cands.length === 1 && !out.has(lk(cands[0]!)) && !overrides.has(lk(cands[0]!))) {
      out.setKey(cands[0]!, project);
      out.checks.set(lk(cands[0]!), checks.get(k)!);
      notes.push(`${LINK_FILE} ${key[0]} ${key[1]}-${key[2]} → ${project}: 거래처코드·금액이 같은 줄이 ${cands[0]![2]}번째로 옮겨져 그 줄에 연결함 (파일의 줄 번호를 ${cands[0]![2]}로 고치세요)`);
    } else {
      notes.push(`${LINK_FILE} ${key[0]} ${key[1]}-${key[2]} → ${project}: 그 줄의 거래처코드·금액이 적은 것과 달라 연결하지 않음 (장부를 다시 받으며 줄이 바뀌었을 수 있음 — 전표를 보고 줄 번호를 다시 적으세요)`);
    }
  }
  return [out, notes];
}

/** unused_links */
export function unusedLinks(books: Books, overrides: Links, used: Set<string>): [LineKey, string, string][] {
  const exist = new Set(lineKeys(books.journal).map(lk));
  const out: [LineKey, string, string][] = [];
  const ks = sortedBy([...overrides.keys()].map((k) => overrides.keys_.get(k)!), (k) => [k[0], k[1], k[2]]);
  for (const key of ks) {
    if (used.has(lk(key))) continue;
    out.push([key, overrides.get(lk(key))!, exist.has(lk(key)) ? "원가·매출 줄이 아님" : "지정한 줄 없음"]);
  }
  return out;
}

export const PRIOR = "참고";
export const PRIOR_LABEL = "참고 (지난해 프로젝트 · 연결하지 않음)";
export const PRIOR_LAST_YEAR = 2025;

export function isOldCode(code: unknown): boolean {
  const s = pyStrip(code === null || code === undefined || code === "" ? "" : String(code));
  return pyIsDigit(s) && [...s].length < 5;
}

export function isPrior(day: IsoDate | null, codes: (string | null | undefined)[] = []): boolean {
  const cs = codes.filter((c) => c).map((c) => pyStrip(String(c)));
  if (cs.some((c) => pyIsDigit(c) && [...c].length >= 5)) return false;
  if (cs.some((c) => isOldCode(c))) return true;
  return day !== null && Number(day.slice(0, 4)) <= PRIOR_LAST_YEAR;
}

export interface LinkLine {
  slip_code: string | null | undefined; index: number; key: LineKey; date: IsoDate | null; no: string; line: number; vendor: string;
  vendor_norm: string; memo: string; account_code: string; account: string; amount: number | null; project: string | null; basis: string;
  request: string | null; candidates: number; label: string; code: string | null; reason: string; prior?: boolean;
}

export interface BasisSum { count: number; sum: number; unknown: number }
export interface LinkResult { lines: LinkLine[]; summary: Map<string, BasisSum>; used: Set<string> }

function summarize(lines: LinkLine[]): Map<string, BasisSum> {
  const out = new Map<string, BasisSum>(BASES.map((b) => [b, { count: 0, sum: 0, unknown: 0 }]));
  for (const ln of lines) {
    if (ln.prior && !out.has(PRIOR)) out.set(PRIOR, { count: 0, sum: 0, unknown: 0 });
    const s = out.get(ln.prior ? PRIOR : ln.basis)!;
    s.count++;
    if (ln.amount === null) s.unknown++;
    else s.sum += ln.amount;
  }
  return out;
}

function slipsOf(books: Books): Map<string, string> {
  const out = new Map<string, string>();
  for (const [k, c] of books.slip_projects) {
    const i = k.indexOf("|");
    out.set(k.slice(0, i) + "\u0000" + normNo(k.slice(i + 1)), c);
  }
  return out;
}

function mkLine(index: number, key: LineKey, row: JLine, amount: number | null, slip: string | null | undefined): LinkLine {
  return { slip_code: slip ?? null, index, key, date: row.date, no: key[1], line: key[2], vendor: maskRrn(row.vendor),
    vendor_norm: row.vendor_norm || normVendor(row.vendor), memo: maskRrn(row.memo), account_code: squash(row.account_code),
    account: row.account ?? "", amount, project: null, basis: "미연결", request: null, candidates: 0, label: "",
    code: row.code || projectCode(row.memo), reason: "" };
}

function fixed(ln: LinkLine, overrides: Links, projects: Projects, used: Set<string>): boolean {
  const manual = overrides.get(lk(ln.key));
  if (manual !== undefined) {
    Object.assign(ln, { project: manual, basis: "수동", label: !projects.size || projects.has(manual) ? MANUAL_LABEL : MANUAL_UNKNOWN_LABEL });
    used.add(lk(ln.key));
    return true;
  }
  const slip = ln.slip_code;
  if (slip !== null && slip !== undefined && (!projects.size || projects.has(slip))) {
    let label = `프로젝트명 [${slip}]`;
    if (!projects.size) label += ` (${NO_LIST})`;
    else if (ln.code !== null && ln.code !== slip) label += ` (적요 코드 [${ln.code}]와 다름)`;
    Object.assign(ln, { project: slip, basis: "코드", label });
    return true;
  }
  const code = ln.code;
  if (code === null) { ln.reason = "코드 없음"; return false; }
  if (!projects.size) {
    Object.assign(ln, { project: code, basis: "코드", label: `코드 [${code}] (${NO_LIST})` });
    return true;
  }
  if (projects.has(code)) {
    Object.assign(ln, { project: code, basis: "코드", label: `코드 [${code}]` });
    return true;
  }
  ln.reason = `코드 ${code} 프로젝트 목록에 없음`;
  return false;
}

function unlinked(ln: LinkLine, tail: string): void {
  Object.assign(ln, { project: null, basis: "미연결", request: null });
  ln.label = `미연결 (${(ln.reason ? [ln.reason, tail] : [tail]).join(" · ")})`;
}

function noKey(n: string): [number, number, string] {
  return pyIsDigit(n) ? [0, Number(n), n] : [1, 0, n];
}

const priorLine = (ln: LinkLine) => isPrior(ln.date, [ln.slip_code, ln.code]);

/** link_costs */
export function linkCosts(books: Books, requests: Request[], projects: Projects, overrides: Links, linkDays = 90,
  directPrefixes: string[] = ["6"], directMark = "(도)", vatCodes: string[] = ["13500"]): LinkResult {
  const journal = books.journal;
  const keys = lineKeys(journal);
  const slips = slipsOf(books);
  const mark = squash(directMark);
  const vat = new Set(vatCodes.map(squash));
  const lines: LinkLine[] = [];
  journal.forEach((row, i) => {
    const code = squash(row.account_code);
    if (!(/^\p{Nd}{5}$/u.test(code) && directPrefixes.some((p) => code.startsWith(p)) && squash(row.account).includes(mark))) return;
    const d = row.debit, c = row.credit;
    const k = keys[i]!;
    lines.push(mkLine(i, k, row, d === null && c === null ? null : (d || 0) - (c || 0), row.line_project || slips.get(k[0] + "\u0000" + k[1])));
  });
  const used = new Set<string>();
  const pending: LinkLine[] = [];
  for (const ln of lines) {
    if (!overrides.has(lk(ln.key)) && priorLine(ln)) {
      Object.assign(ln, { prior: true, label: PRIOR_LABEL });
      continue;
    }
    if (!fixed(ln, overrides, projects, used)) pending.push(ln);
  }
  const vatSum = new Map<string, number | null>();
  journal.forEach((row, i) => {
    if (!vat.has(squash(row.account_code))) return;
    const k = keys[i]![0] + "\u0000" + keys[i]![1] + "\u0000" + (row.vendor_norm || normVendor(row.vendor));
    const d = row.debit, c = row.credit;
    const part = d === null && c === null ? null : d || 0;
    const prev = vatSum.has(k) ? vatSum.get(k)! : 0;
    vatSum.set(k, part === null || prev === null ? null : prev + part);
  });
  const perVendor = new Map<string, number>();
  for (const ln of lines) {
    const k = ln.key[0] + "\u0000" + ln.key[1] + "\u0000" + ln.vendor_norm;
    perVendor.set(k, (perVendor.get(k) ?? 0) + 1);
  }
  const eligible = new Map<string, Request[]>();
  if (projects.size) {
    for (const rq of requests) {
      const vn = normVendor(rq.vendor);
      if (rq.amount !== null && rq.registered !== null && rq.code !== null && projects.has(rq.code) && vn) {
        if (!eligible.has(vn)) eligible.set(vn, []);
        eligible.get(vn)!.push(rq);
      }
    }
  }
  const cand = new Map<number, string[]>();
  for (const ln of pending) {
    const found: string[] = [];
    if (ln.amount !== null && ln.date !== null && ln.vendor_norm && projects.size) {
      const k = ln.key[0] + "\u0000" + ln.key[1] + "\u0000" + ln.vendor_norm;
      const amounts = new Set([ln.amount]);
      if (perVendor.get(k) === 1 && vatSum.get(k) !== undefined && vatSum.get(k) !== null) amounts.add(ln.amount + (vatSum.get(k) as number));
      for (const rq of eligible.get(ln.vendor_norm) ?? []) {
        const start = (rq.registered as string).slice(0, 10);
        if (start <= ln.date && ln.date <= windowEnd(start, linkDays) && amounts.has(rq.amount as number)) found.push(rq["번호"]);
      }
    }
    cand.set(ln.index, sortedBy([...new Set(found)], noKey));
  }
  const backing = new Map<string, number>();
  for (const numbers of cand.values()) for (const n of numbers) backing.set(n, (backing.get(n) ?? 0) + 1);
  const byNo = new Map(requests.map((rq) => [rq["번호"], rq]));
  for (const ln of pending) {
    const numbers = cand.get(ln.index)!;
    ln.candidates = numbers.length;
    if (ln.amount === null) { ln.reason = ""; unlinked(ln, "금액 미확인"); }
    else if (!projects.size) unlinked(ln, NO_LIST);
    else if (numbers.length === 1 && backing.get(numbers[0]!) === 1) {
      const n = numbers[0]!;
      Object.assign(ln, { project: byNo.get(n)!.code, basis: "자동", request: n, label: `자동 (지급요청 ${n})` });
    } else if (numbers.length === 1) { ln.reason = ""; unlinked(ln, `자동 연결 후보 공유: 지급요청 ${numbers[0]}`); }
    else if (numbers.length) { ln.reason = ""; unlinked(ln, `자동 연결 후보 ${numbers.length}건: 지급요청 ${numbers.join(", ")}`); }
    else {
      if (ln.date === null) ln.reason = (ln.reason ? ln.reason + " · " : "") + "날짜 없음";
      unlinked(ln, "자동 연결 후보 0건");
    }
  }
  return { lines, summary: summarize(lines), used };
}

function windowEnd(start: IsoDate, days: number): IsoDate {
  try {
    return addDays(start, days);
  } catch {
    return "9999-12-31";
  }
}

/** link_revenue */
export function linkRevenue(books: Books, projects: Projects, overrides: Links, revenueCodes: string[] = ["41200"]): LinkResult {
  const journal = books.journal;
  const keys = lineKeys(journal);
  const slips = slipsOf(books);
  const codes = new Set(revenueCodes.map(squash));
  const lines: LinkLine[] = [];
  journal.forEach((row, i) => {
    if (!codes.has(squash(row.account_code))) return;
    const d = row.debit, c = row.credit;
    const k = keys[i]!;
    lines.push(mkLine(i, k, row, d === null && c === null ? null : (c || 0) - (d || 0), row.line_project || slips.get(k[0] + "\u0000" + k[1])));
  });
  const used = new Set<string>();
  for (const ln of lines) {
    if (!overrides.has(lk(ln.key)) && priorLine(ln)) {
      Object.assign(ln, { prior: true, label: PRIOR_LABEL });
      continue;
    }
    if (fixed(ln, overrides, projects, used)) continue;
    if (ln.amount === null) { ln.reason = ""; unlinked(ln, "금액 미확인"); continue; }
    if (!projects.size) { unlinked(ln, NO_LIST); continue; }
    const found = [...projects.entries()].filter(([, p]) => !p.dup && ln.vendor_norm && p.client_norm === ln.vendor_norm && p.quote === ln.amount)
      .map(([k]) => k).sort(cmpStr);
    ln.candidates = found.length;
    if (found.length === 1) Object.assign(ln, { project: found[0], basis: "자동", label: "자동 (클라이언트·견적금액)" });
    else {
      if (found.length) ln.reason = "";
      unlinked(ln, `클라이언트·견적금액 후보 ${found.length}건`);
    }
  }
  return { lines, summary: summarize(lines), used };
}
