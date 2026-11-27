// wehago.py: WEHAGO 장부(분개장·매입매출장·전자세금계산서(매입))를 골라 읽고, 매출 계산서 원천을 읽고, 인트라넷 요청과 대조한다.
// 엑셀(.xlsx)은 비동기로 풀어야 하므로 convert 가 먼저 prepareBooks 로 읽어 둔 결과(BookCache)를 쓴다.
import { CONVERT_RULES } from "./rules";
import { addDays, daysBetween, type IsoDate } from "../model/dates";
import { cmpStr, pyIsDigit, pyRemoveSpace, pyStrip, sortedBy, type SortKey } from "../model/py";
import { isBlank, maskRrn, parseDate, ssumOrNone, won } from "../model/util";
import { normVendor } from "../model/vendor";
import { basename, join, listFiles, readUtf8, type ConvFiles } from "./files";
import { isPyInt, isDict, pyD, pyStrJ, pyStrOr } from "./pyjson";
import { pyReprFloat, readXls, XlsError, type XlsCell } from "./xls";
import { readXlsx, WehagoError, type Rows } from "./xlsx";

export { WehagoError } from "./xlsx";

export const KIND_HEADERS: Record<string, string[]> = {
  "분개장": ["전표일자", "전표번호", "구분", "Code", "계정과목", "차변", "대변", "거래처", "Code", "적요"],
  "매입매출장": ["구분", "전표일자", "번호", "거래처", "사업자(주민)번호", "품명", "공급가액", "부가세", "합계", "신고월",
    "전자세금", "11일이내", "매입/매출유형", "분개유형"],
  "전자세금계산서(매입)": ["일자", "Code", "거래처", "유형", "품명", "공급가액", "부가세", "합계", "차변계정", "대변계정",
    "관리", "전표상태"],
};
export const KINDS = ["분개장", "매입매출장", "전자세금계산서(매입)"] as const;
export type Kind = (typeof KINDS)[number];
export const SALES_KINDS = ["매입매출장(매출)", "전자세금계산서(매출)"] as const;
const EPOCH_1900 = "1899-12-30";
const EPOCH_1904 = "1904-01-01";
export const DATE_MIN = "0001-01-01";

export class HeaderMismatch extends WehagoError {
  constructor(public file: string, public kind: string, public missing: string[], public extra: string[]) {
    super(`${file} 머리글이 예상과 다름 — ${[...(missing.length ? ["없음: " + missing.join(", ")] : []), ...(extra.length ? ["추가: " + extra.join(", ")] : [])].join(" · ")}`);
  }
}

/** 미리 읽은 엑셀: 경로 → 행 또는 오류. */
export type BookCache = Map<string, Rows | Error>;

/** .xlsx 를 모두 미리 푼다 (비동기). */
export async function prepareBooks(files: ConvFiles, folder: string): Promise<BookCache> {
  const cache: BookCache = new Map();
  for (const n of listFiles(files, folder)) {
    if (!n.toLowerCase().endsWith(".xlsx")) continue;
    const p = join(folder, n);
    try {
      cache.set(p, await readXlsx(files[p] as Uint8Array));
    } catch (e) {
      cache.set(p, e instanceof Error ? e : new Error(String(e)));
    }
  }
  return cache;
}

// ───────────── 글자·숫자·날짜 해석 ─────────────
export { normVendor as norm_vendor } from "../model/vendor";

/** wehago._squash: 모든 공백 제거. */
export function squash(text: string | null | undefined): string {
  return pyRemoveSpace(text || "");
}

const DEC_RE = /^[+-]?(?:(\d(?:_?\d)*)(?:\.(\d(?:_?\d)*)?)?|\.(\d(?:_?\d)*))(?:[eE]([+-]?\d(?:_?\d)*))?$/;

/** wehago._amount: 엑셀 칸 글자 → 정수 금액. 빈칸·오류·정수가 아닌 값은 null. */
export function amount(text: unknown): number | null {
  if (isBlank(text)) return null;
  let s = pyStrip(String(text)).replace(/,/g, "").replace(/원/g, "");
  const neg = s.startsWith("(") && s.endsWith(")");
  if (neg) s = s.slice(1, -1);
  const t = pyStrip(s);
  const m = DEC_RE.exec(t);
  if (!m) return null;
  const ip = (m[1] ?? "").replace(/_/g, "");
  const fp = (m[2] ?? m[3] ?? "").replace(/_/g, "");
  const exp = m[4] ? Number(m[4].replace(/_/g, "")) : 0;
  const sign = t.startsWith("-") ? -1 : 1;
  // 계수 digits, 지수 e: 값 = digits × 10^(exp - fp.length)
  const digits = (ip + fp).replace(/^0+/, "");
  const e = exp - fp.length;
  if (!digits) {
    // 0: adjusted() = 지수
    if (Math.abs(e) > 18) return null;
    return 0;
  }
  const adjusted = digits.length - 1 + e;
  if (Math.abs(adjusted) > 18) return null;
  let intDigits: string;
  if (e >= 0) intDigits = digits + "0".repeat(e);
  else {
    const frac = digits.slice(Math.max(0, digits.length + e));
    if (/[1-9]/.test(frac) || digits.length + e < 0 && /[1-9]/.test(digits)) return null;
    intDigits = digits.slice(0, digits.length + e) || "0";
  }
  const v = sign * Number(intDigits);
  return neg ? -v || 0 : v || 0;
}

/** wehago._parse_date */
export function parseBookDate(text: string, date1904 = false, yearRef: IsoDate | null = null): IsoDate | null {
  const s = pyStrip(text || "");
  if (!s) return null;
  if (/^\d+(\.\d+)?$/.test(s) && (s.split(".")[0] as string).length !== 8) {
    const n = Number(s.split(".")[0]);
    if (n >= 1 && n <= 2958465) return addDays(date1904 ? EPOCH_1904 : EPOCH_1900, n);
    return null;
  }
  const m = /^(\d{1,2})-(\d{1,2})$/.exec(s);
  if (m) {
    if (yearRef === null) return null;
    const mm = Number(m[1]), dd = Number(m[2]);
    const [ry, rm, rd] = yearRef.split("-").map(Number) as [number, number, number];
    const year = ry - (mm > rm || (mm === rm && dd > rd) ? 1 : 0);
    try {
      return isoOf(year, mm, dd);
    } catch {
      return null;
    }
  }
  return parseDate(s.replace(/T/g, " "));
}

function isoOf(y: number, m: number, d: number): IsoDate {
  const dim = [31, (y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0)) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (y < 1 || y > 9999 || m < 1 || m > 12 || d < 1 || d > (dim[m - 1] as number)) throw new RangeError("날짜");
  return String(y).padStart(4, "0") + "-" + String(m).padStart(2, "0") + "-" + String(d).padStart(2, "0");
}

export { isoOf };

// ───────────── 프로젝트 코드 (approval.project_code) ─────────────
const CODE_RE = /^[\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*\[(\p{Nd}+)\]/u;

/** approval.norm_project */
export function normProject(code: unknown): string {
  const s = pyStrip(code === null || code === undefined || code === "" || code === 0 ? "" : String(code));
  return pyIsDigit(s) ? s.replace(/^0+/, "") || "0" : s;
}

/** approval.project_code: 행사명 맨 앞 [숫자]. 없으면 null. */
export function projectCode(text: string | null | undefined): string | null {
  const m = CODE_RE.exec(text || "");
  return m ? normProject(m[1]) : null;
}

/** approval.parse_registered: 'YYYY-MM-DD HH:MM:SS' | 'YYYY-MM-DD HH:MM' | 'YYYY-MM-DD' → 'YYYY-MM-DDTHH:MM:SS' 또는 null. */
export function parseRegistered(text: string | null | undefined): string | null {
  const s = pyStrip(text || "");
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})(?: (\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?$/.exec(s);
  if (!m || !/^[0-9: -]+$/.test(s)) return null;
  try {
    const d = isoOf(Number(m[1]), Number(m[2]), Number(m[3]));
    const h = Number(m[4] ?? 0), mi = Number(m[5] ?? 0), se = Number(m[6] ?? 0);
    if (h > 23 || mi > 59 || se > 61) return null;
    if (se > 59) return null;
    return `${d}T${String(h).padStart(2, "0")}:${String(mi).padStart(2, "0")}:${String(se).padStart(2, "0")}`;
  } catch {
    return null;
  }
}

// ───────────── 장부 줄 ─────────────
export interface JLine {
  date: IsoDate | null;
  no: string;
  account_code: string;
  account: string;
  debit: number | null;
  credit: number | null;
  vendor: string;
  memo: string;
  sort: string;
  vendor_code: string;
  code: string | null;
  line_id?: string;
  dept?: string;
  employee?: string;
  project_name?: string;
  line_project?: string | null;
  vendor_norm: string;
}

/** 매입매출장·전자세금계산서 줄, 분개장에서 만든 계산서 줄. */
export interface LRow {
  date: IsoDate | null;
  no?: string;
  vendor: string;
  item: string;
  supply: number | null;
  vat: number | null;
  total: number | null;
  code: string | null;
  vendor_norm: string;
  type?: string;
  debit_account?: string;
  slip_state?: string;
  credit_account?: string;
  advance?: boolean;
  deducted?: number;
}

interface BookInfo {
  last_date: IsoDate | null;
  rows: number;
  skipped: number;
  undated: number;
  sales: number;
  other: number;
  after_ref: number;
  extra_columns: string[];
  extra_note: string;
  sales_rows: LRow[];
  slip_projects: Map<string, string>;   // 열쇠 'ISO|번호'
  period: [IsoDate, IsoDate] | null;
  company: string;
}

export const SUBTOTAL = ["일계", "월계", "누계", "합계", "소계"];

function checkHeader(rows: string[][], kind: string, name: string): [Map<string, number[]>, string[]] {
  const header = (rows[0] ?? []).map((h) => pyRemoveSpace(h));
  while (header.length && !header[header.length - 1]) header.pop();
  const remaining = [...header];
  const missing: string[] = [];
  for (const h of KIND_HEADERS[kind] as string[]) {
    const i = remaining.indexOf(h);
    if (i >= 0) remaining.splice(i, 1);
    else missing.push(h);
  }
  const extra = remaining.map((h) => h || "(빈칸)");
  if (missing.length) throw new HeaderMismatch(name, kind, missing, extra);
  const cols = new Map<string, number[]>();
  header.forEach((h, i) => {
    if (!cols.has(h)) cols.set(h, []);
    cols.get(h)!.push(i);
  });
  return [cols, extra];
}

function isSubtotal(row: string[]): boolean {
  for (const c of row) {
    let s = pyRemoveSpace(c);
    if (s.includes("거래처별소계")) return true;
    s = s.replace(/^[[\]()<>【】「」]+/, "");
    if (SUBTOTAL.some((w) => s.startsWith(w)) || s.startsWith("분기누계") || s.startsWith("반기누계")) return true;
  }
  return false;
}

const PRINT_JOURNAL: Record<string, string> = { "일자": "전표일자", "전표번호": "전표번호", "계정코드": "Code", "계정과목": "계정과목",
  "적요": "적요", "차변": "차변", "대변": "대변", "거래처코드": "거래처Code", "거래처명": "거래처" };

function xlsText(v: XlsCell): string {
  if (typeof v === "number") return v === Math.trunc(v) ? pyD(v) : pyReprFloat(v);
  return v;
}

const PERIOD_RE = new RegExp("기\\s*간\\s*:\\s*(\\d{4})\\s*년\\s*(\\d{1,2})\\s*월\\s*(\\d{1,2})\\s*일" +
  "(?:\\s*~\\s*(\\d{4})\\s*년\\s*(\\d{1,2})\\s*월\\s*(\\d{1,2})\\s*일)?");

/** read_journal_xls: 분개장 인쇄 저장 파일(.xls). */
export function readJournalXls(data: Uint8Array, name: string): Rows {
  let grid: XlsCell[][];
  try {
    grid = readXls(data);
  } catch (e) {
    if (e instanceof XlsError) throw new WehagoError(e.message);
    throw e;
  }
  let start: IsoDate | null = null, end: IsoDate | null = null, hdr: number | null = null;
  for (let i = 0; i < Math.min(grid.length, 40); i++) {
    const row = grid[i] as XlsCell[];
    for (const c of row) {
      if (typeof c !== "string") continue;
      const m = PERIOD_RE.exec(c);
      if (m && start === null) {
        start = isoOf(Number(m[1]), Number(m[2]), Number(m[3]));   // 틀리면 RangeError → load_books 가 '읽을 수 없음'
        try {
          end = m[4] ? isoOf(Number(m[4]), Number(m[5]), Number(m[6])) : null;
        } catch {
          end = null;
        }
      }
    }
    if (row.length && typeof row[0] === "string" && pyRemoveSpace(row[0]) === "일자") {
      hdr = i;
      break;
    }
  }
  if (hdr === null || start === null) throw new WehagoError("분개장 인쇄 파일 모양이 아님 (기간·머리글을 찾지 못함)");
  const names = (grid[hdr] as XlsCell[]).map((c) => (typeof c === "string" ? pyRemoveSpace(c) : ""));
  const missing = Object.keys(PRINT_JOURNAL).filter((h) => !names.includes(h));
  if (missing.length) throw new HeaderMismatch(name, "분개장", missing, []);
  const col: Record<string, number> = {};
  for (const h of Object.keys(PRINT_JOURNAL)) col[h] = names.indexOf(h);
  const sortCol = names.includes("유형") ? names.indexOf("유형") : null;
  const projCol = names.includes("프로젝트명") ? names.indexOf("프로젝트명") : null;
  const opt = ["부서명", "사원명"].filter((h) => names.includes(h));
  const out: string[][] = [["전표일자", "전표번호", "구분", "Code", "계정과목", "차변", "대변", "거래처", "Code", "적요",
    ...(projCol !== null ? ["프로젝트명"] : []), ...opt]];
  const [sy, sm, sd] = start.split("-").map(Number) as [number, number, number];
  for (const raw of grid.slice(hdr + 1)) {
    const row: XlsCell[] = [...raw];
    while (row.length < names.length) row.push("");
    const a = row[col["일자"] as number] as XlsCell;
    const m = typeof a === "string" ? /^[\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*(\d{1,2})\/(\d{1,2})[\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*$/.exec(a) : null;
    if (!m) continue;
    const mm = Number(m[1]), dd = Number(m[2]);
    const year = sy + (mm < sm || (mm === sm && dd < sd) ? 1 : 0);
    let day: string;
    try {
      day = isoOf(year, mm, dd);
    } catch {
      day = a as string;
    }
    const g = (h: string) => xlsText(row[col[h] as number] as XlsCell);
    out.push([day, g("전표번호"), sortCol !== null ? xlsText(row[sortCol] as XlsCell) : "", g("계정코드"), g("계정과목"), g("차변"),
      g("대변"), g("거래처명"), g("거래처코드"), g("적요"),
      ...(projCol !== null ? [xlsText(row[projCol] as XlsCell)] : []), ...opt.map((h) => xlsText(row[names.indexOf(h)] as XlsCell))]);
  }
  return { rows: out, date1904: false, knownExtra: ["프로젝트명", "부서명", "사원명"], period: end !== null && end >= start ? [start, end] : null };
}

const LEAD_CODE = /^[\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*\[[^\]]*\][\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]*/;
const CO_WORDS = /주식회사|유한회사|\(주\)|\(유\)|㈜|[\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/g;

/** wehago.company_key */
export function companyKey(name: unknown): string {
  return String(name ?? "").normalize("NFKC").replace(CO_WORDS, "").toLowerCase();
}

/** wehago.same_company */
export function sameCompany(a: unknown, b: unknown): boolean {
  const x = companyKey(a), y = companyKey(b);
  if (!x || !y) return true;
  return x === y || (Math.min(x.length, y.length) >= 2 && (x.includes(y) || y.includes(x)));
}

/** read_journal_json: 확장 자동수집 분개장(.json). */
export function readJournalJson(data: Uint8Array, name: string): Rows {
  let doc: unknown;
  let text: string | null;
  try {
    text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(data);
  } catch {
    throw new WehagoError(`${name} 를 읽지 못함 (UnicodeDecodeError)`);
  }
  if (text.startsWith("﻿")) text = text.slice(1);
  try {
    doc = JSON.parse(text);
  } catch {
    throw new WehagoError(`${name} 를 읽지 못함 (JSONDecodeError)`);
  }
  if (!isDict(doc) || doc["종류"] !== "분개장" || !Array.isArray(doc["줄"])) throw new WehagoError(`${name} 는 분개장 자동수집 파일 모양이 아님`);
  const cols = (Array.isArray(doc["열"]) ? doc["열"] : []) as unknown[];
  const need = ["da_date", "no_acct", "nm_yuh", "cd_acctit", "nm_acctit", "mn_bungae1", "mn_bungae2", "nm_trade", "cd_trade",
    "nm_remark", "nm_project", "nm_dept", "nm_emp"];
  const missing = need.filter((c) => !cols.includes(c));
  if (missing.length) throw new HeaderMismatch(name, "분개장", missing, []);
  const ix: Record<string, number> = {};
  for (const c of need) ix[c] = cols.indexOf(c);
  const gb = cols.includes("nm_gubun_bungae") ? cols.indexOf("nm_gubun_bungae") : null;
  const sq = cols.includes("sq_acttax2") ? cols.indexOf("sq_acttax2") : null;
  const day = (v: unknown): string => {
    const s = pyStrip(pyStrOr(v));
    if (s.length === 8 && pyIsDigit(s) && /^[0-9]+$/.test(s)) {
      try {
        return isoOf(Number(s.slice(0, 4)), Number(s.slice(4, 6)), Number(s.slice(6)));
      } catch {
        return s;
      }
    }
    return s;
  };
  const num = (v: unknown): string => {
    if (v === "" || v === null || v === undefined) return "";
    if (typeof v === "number" || typeof v === "boolean") {
      const x = Number(v);
      if (x === Math.trunc(x)) return pyD(x);
    }
    return pyStrJ(v);
  };
  const bare = (v: unknown) => pyStrip(pyStrOr(v).replace(LEAD_CODE, ""));
  const lines = doc["줄"] as unknown[];
  const out: string[][] = [["전표일자", "전표번호", "구분", "Code", "계정과목", "차변", "대변", "거래처", "Code", "적요",
    "프로젝트명", "부서명", "사원명", ...(sq !== null ? ["줄번호"] : [])]];
  const company = pyStrip(pyStrOr(doc["회사"]));
  const per = isDict(doc["기간"]) ? doc["기간"] : {};
  let period: [IsoDate, IsoDate] | null = null;
  try {
    const s = pyStrJ(per["start_date"] ?? ""), e = pyStrJ(per["end_date"] ?? "");
    const p8 = (x: string) => {
      const a = x.slice(0, 4), b = x.slice(4, 6), c = x.slice(6, 8);
      if (![a, b, c].every((t) => /^[+-]?\d+$/.test(pyStrip(t)))) throw new RangeError();
      return isoOf(Number(a), Number(b), Number(c));
    };
    const st = p8(s), en = p8(e);
    period = en >= st ? [st, en] : null;
  } catch {
    period = null;
  }
  const tot = doc["전표수"], nLines = doc["줄수"];
  if (isPyInt(nLines) && nLines !== lines.length) {
    throw new WehagoError(`${name}: 줄 ${nLines}개를 받는다고 적혔는데 ${lines.length}개만 있음 — 일부만 저장된 파일이라 쓰지 않음. 확장에서 분개장을 다시 받으세요`);
  }
  if (isPyInt(tot)) {
    const got = new Set<string>();
    for (const r of lines) {
      if (Array.isArray(r) && r.length >= cols.length) got.add(pyStrJ(r[ix["da_date"] as number]) + "\u0000" + pyStrip(pyStrJ(r[ix["no_acct"] as number])));
    }
    if (got.size !== tot) {
      throw new WehagoError(`${name}: 위하고가 알려 준 전표는 ${tot}개인데 받은 전표는 ${got.size}개 — 일부만 받았을 수 있어 쓰지 않음. 확장에서 분개장을 다시 받으세요`);
    }
  }
  const bad = lines.filter((r) => !Array.isArray(r) || r.length < cols.length).length;
  if (bad) throw new WehagoError(`${name}: 줄 ${bad}개가 모양이 달라 읽지 못함 (전체 ${lines.length}줄) — 깨진 파일이라 쓰지 않음. 확장에서 분개장을 다시 받으세요`);
  for (const r of lines as unknown[][]) {
    const g = (c: string) => r[ix[c] as number];
    const side = gb !== null ? pyStrip(pyStrJ(r[gb])) : "";
    const debit = side === "대변" ? "" : num(g("mn_bungae1"));
    const credit = side === "차변" ? "" : num(g("mn_bungae2"));
    out.push([day(g("da_date")), pyStrip(pyStrOr(g("no_acct"))), pyStrOr(g("nm_yuh")), pyStrOr(g("cd_acctit")), pyStrOr(g("nm_acctit")),
      debit, credit, pyStrOr(g("nm_trade")), pyStrOr(g("cd_trade")), pyStrOr(g("nm_remark")), bare(g("nm_project")), bare(g("nm_dept")),
      bare(g("nm_emp")), ...(sq !== null ? [pyStrip(r[sq] !== null && r[sq] !== undefined ? pyStrJ(r[sq]) : "")] : [])]);
  }
  return { rows: out, date1904: false, knownExtra: ["프로젝트명", "부서명", "사원명", "줄번호"], period, company };
}

export interface BookCtx { files: ConvFiles; cache: BookCache; folder: string; mtimes: Record<string, number> }

function rowsOf(ctx: BookCtx, path: string, kind: string): Rows {
  const name = basename(path);
  const lower = path.toLowerCase();
  if (kind === "분개장" && lower.endsWith(".json")) return readJournalJson(ctx.files[path] as Uint8Array, name);
  if (kind === "분개장" && lower.endsWith(".xls")) return readJournalXls(ctx.files[path] as Uint8Array, name);
  const got = ctx.cache.get(path);
  if (got === undefined) throw new WehagoError("엑셀 파일을 열 수 없음");
  if (got instanceof Error) throw got;
  return got;
}

/** read_book: 한 파일 → (행 목록, 요약). 머리글이 다르면 HeaderMismatch. */
export function readBook(ctx: BookCtx, path: string, kind: string, fileDate: IsoDate | null = null, asof: IsoDate | null = null,
  keepSales = false): [(JLine | LRow)[], BookInfo] {
  const name = basename(path);
  const R = rowsOf(ctx, path, kind);
  const rows = R.rows;
  const [cols, extra0] = checkHeader(rows, kind, name);
  const known = [...(R.knownExtra ?? []), ...(kind === "분개장" ? ["부서명", "사원명"] : [])];
  const extra = extra0.filter((h) => !known.includes(h));
  const yearRef = kind === "전자세금계산서(매입)" ? (fileDate || asof) : null;
  const d1904 = R.date1904;
  const dateCol = ({ "분개장": "전표일자", "매입매출장": "전표일자", "전자세금계산서(매입)": "일자" } as Record<string, string>)[kind] as string;
  const c = (h: string, n = 0) => (cols.get(h) as number[])[n] as number;
  const txt = (row: string[], header: string, n = 0) => maskRrn(pyStrip(row[c(header, n)] as string));
  const out: (JLine | LRow)[] = [];
  let last: IsoDate | null = null;
  const info: BookInfo = { last_date: null, rows: 0, skipped: 0, undated: 0, sales: 0, other: 0, after_ref: 0,
    extra_columns: [...extra], extra_note: extra.length ? "추가 열 무시: " + extra.join(", ") : "", sales_rows: [],
    slip_projects: new Map(), period: R.period ?? null, company: R.company || "" };
  const slips = new Map<string, string | null>();
  const setSlip = (k: string, p: string) => {
    slips.set(k, !slips.has(k) || slips.get(k) === p ? p : null);
  };
  for (const row of rows.slice(1)) {
    if (!row.some((x) => pyStrip(x))) { info.skipped++; continue; }
    const date = parseBookDate(row[c(dateCol)] as string, d1904, yearRef);
    if (date === null && isSubtotal(row)) { info.skipped++; continue; }
    info.rows++;
    if (date === null) info.undated++;
    else {
      last = last === null || date > (last as string) ? date : last;
      if (fileDate !== null && date > fileDate) info.after_ref++;
    }
    if (kind === "분개장") {
      const item: JLine = { date, no: txt(row, "전표번호"), account_code: txt(row, "Code", 0), account: txt(row, "계정과목"),
        debit: amount(row[c("차변")]), credit: amount(row[c("대변")]), vendor: txt(row, "거래처"), memo: txt(row, "적요"),
        sort: txt(row, "구분"), vendor_code: pyStrip(txt(row, "Code", 1)), code: null, vendor_norm: "" };
      item.code = projectCode(item.memo);
      if (cols.has("줄번호")) item.line_id = pyStrip(txt(row, "줄번호"));
      if (cols.has("부서명")) item.dept = pyStrip(txt(row, "부서명"));
      if (cols.has("사원명")) item.employee = pyStrip(txt(row, "사원명"));
      if (cols.has("프로젝트명")) {
        item.project_name = txt(row, "프로젝트명");
        const pcode = projectCode(item.project_name);
        item.line_project = pcode;
        if (pcode && date !== null) setSlip(date + "|" + item.no, pcode);
      }
      item.vendor_norm = normVendor(item.vendor);
      out.push(item);
      continue;
    }
    if (kind === "매입매출장") {
      const sort = pyStrip(row[c("구분")] as string);
      if (cols.has("프로젝트명") && date !== null) {
        const pcode = projectCode(txt(row, "프로젝트명"));
        if (pcode) setSlip(date + "|" + pyStrip(row[c("번호")] as string), pcode);
      }
      if (sort !== "매입") {
        if (sort === "매출") info.sales++;
        else info.other++;
        if (sort !== "매출" || !keepSales) continue;
      }
      const item: LRow = { date, no: txt(row, "번호"), vendor: txt(row, "거래처"), item: txt(row, "품명"),
        supply: amount(row[c("공급가액")]), vat: amount(row[c("부가세")]), total: amount(row[c("합계")]), code: null, vendor_norm: "" };
      item.code = projectCode(item.item);
      if (sort === "매출") {
        item.type = txt(row, "매입/매출유형");
        item.vendor_norm = normVendor(item.vendor);
        info.sales_rows.push(item);
        continue;
      }
      item.vendor_norm = normVendor(item.vendor);
      out.push(item);
      continue;
    }
    const item: LRow = { date, vendor: txt(row, "거래처"), item: txt(row, "품명"), supply: amount(row[c("공급가액")]),
      vat: amount(row[c("부가세")]), total: amount(row[c("합계")]), debit_account: txt(row, "차변계정"),
      slip_state: txt(row, "전표상태"), credit_account: txt(row, "대변계정"), type: txt(row, "유형"), code: null, vendor_norm: "" };
    item.code = projectCode(item.item);
    item.vendor_norm = normVendor(item.vendor);
    out.push(item);
  }
  info.last_date = last;
  for (const [k, v] of slips) if (v) info.slip_projects.set(k, v);
  return [out, info];
}

/** _file_date: 이름의 '_' 뒤 8자리, 없으면 앞 'YYMMDD '. */
export function fileDate(name: string): IsoDate | null {
  for (const m of name.matchAll(/_(\d+)/g)) {
    const g = m[1] as string;
    if (g.length === 8) {
      try {
        return isoOf(Number(g.slice(0, 4)), Number(g.slice(4, 6)), Number(g.slice(6)));
      } catch {
        continue;
      }
    }
  }
  const m = /^(\d{2})(\d{2})(\d{2})[\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/.exec(basename(name));
  if (m) {
    try {
      return isoOf(2000 + Number(m[1]), Number(m[2]), Number(m[3]));
    } catch {
      return null;
    }
  }
  return null;
}

function rankDate(name: string): IsoDate | null {
  const fd = fileDate(name);
  if (fd === null) return null;
  const base = basename(name).replace(/^\d{6}[\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/, "");
  const fy = Number(fd.slice(0, 4));
  const years = [...base.matchAll(/(?<!\d)(20\d\d)(?!\d)/g)].map((m) => Number(m[1])).filter((y) => y < fy);
  return years.length ? isoOf(Math.max(...years), 12, 31) : fd;
}

export function salesKindOf(name: string): string | null {
  if (name.includes("매입매출장") && name.replace(/매입매출장/g, "").includes("매출")) return "매입매출장(매출)";
  if (name.includes("전자세금계산서") && name.includes("매출")) return "전자세금계산서(매출)";
  return null;
}

const RAW_SCREEN = /(?:^|[\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000])(?:결산|대조|인사|연말정산)_/;

function kindOf(name: string): [Kind | null, boolean] {
  if (RAW_SCREEN.test(name)) return [null, false];
  if (name.includes("매입매출장")) return ["매입매출장", salesKindOf(name) === null];
  if (name.includes("분개장")) return ["분개장", true];
  if (name.includes("전자세금계산서")) return ["전자세금계산서(매입)", !name.includes("매출")];
  return [null, false];
}

function ext(n: string): string {
  const b = basename(n);
  const i = b.lastIndexOf(".");
  return i <= 0 ? "" : b.slice(i).toLowerCase();
}

export const OPENING_MEMO = ["전기이월", "기초잔액"];
export const CAPITAL_PREFIX = "331";

function ym(d: IsoDate): string {
  return d.slice(0, 7);
}

/** journal_from_start */
export function journalFromStart(journal: JLine[]): boolean {
  const dated = journal.filter((ln) => ln.date !== null);
  if (!dated.length) return true;
  if (journal.some((ln) => OPENING_MEMO.some((w) => squash(ln.memo).includes(w)))) return true;
  const first = dated.reduce((m, ln) => (ln.date! < m ? ln.date! : m), dated[0]!.date!);
  return dated.some((ln) => squash(ln.account_code).startsWith(CAPITAL_PREFIX) && (ln.credit || 0) > 0 && ym(ln.date!) === ym(first));
}

// ───────────── 분개장 매입·매출 전표 → 계산서 (D-57) ─────────────
const INVOICE_SORTS: Record<string, string> = { "매입전표": "매입", "매출전표": "매출" };
const VAT_IN_CODES = ["13500"];
const VAT_OUT_CODES = ["25500"];
export const ADVANCE_CODES = ["25900"];

export function isAdvance(line: JLine): boolean {
  return ADVANCE_CODES.includes(squash(line.account_code)) || squash(line.account).includes("선수금");
}

export function invoicesFromJournal(journal: JLine[]): [LRow[], LRow[]] {
  const groups = new Map<string, { kind: string; date: IsoDate; no: string; lines: JLine[] }>();
  for (const line of journal) {
    const kind = INVOICE_SORTS[pyStrip(line.sort || "")];
    if (kind === undefined || line.date === null) continue;
    const k = kind + "\u0000" + line.date + "\u0000" + line.no;
    if (!groups.has(k)) groups.set(k, { kind, date: line.date, no: line.no, lines: [] });
    groups.get(k)!.lines.push(line);
  }
  const buys: LRow[] = [], sales: LRow[] = [];
  for (const { kind, date, no, lines } of groups.values()) {
    const side = kind === "매입" ? "debit" : "credit";
    const other = kind === "매입" ? "credit" : "debit";
    const vatCodes = kind === "매입" ? VAT_IN_CODES : VAT_OUT_CODES;
    const total = lines.reduce((s, ln) => s + (ln[side] || 0), 0);
    const vat = lines.filter((ln) => vatCodes.includes(squash(ln.account_code))).reduce((s, ln) => s + (ln[side] || 0), 0);
    const main = lines.filter((ln) => ln[side] && !vatCodes.includes(squash(ln.account_code)));
    const party = lines.filter((ln) => ln[other] && ln.vendor);
    const withV = lines.filter((ln) => ln.vendor);
    const vendor = (party.length ? party : withV.length ? withV : [{ vendor: "" }])[0]!.vendor;
    const item = main.length ? main[0]!.memo : lines[0]!.memo || "";
    let code: string | null = null;
    for (const ln of lines) {
      const pc = projectCode(ln.project_name ?? "");
      if (pc) { code = pc; break; }
    }
    code = code || projectCode(item);
    const row: LRow = { date, no, vendor, item, supply: total - vat, vat, total, code, vendor_norm: normVendor(vendor) };
    if (kind === "매출") {
      row.type = "";
      row.advance = main.some(isAdvance);
      row.deducted = lines.filter((ln) => ln.debit && !squash(ln.account_code).startsWith("1")).reduce((s, ln) => s + (ln.debit || 0), 0);
      sales.push(row);
    } else buys.push(row);
  }
  return [buys, sales];
}

function compareInvoices(derived: LRow[], ledgerRows: LRow[], label: string): string[] {
  const byKey = (rows: LRow[]) => {
    const out = new Map<string, { k: [IsoDate | null, string]; v: number }>();
    for (const r of rows) {
      const no = String(r.no ?? "").replace(/^0+/, "");
      const k = (r.date ?? "") + "\u0000" + no;
      const cur = out.get(k);
      out.set(k, { k: [r.date, no], v: (cur?.v ?? 0) + (r.total || 0) });
    }
    return out;
  };
  const a = byKey(derived), b = byKey(ledgerRows);
  const all = new Map<string, [IsoDate | null, string]>();
  for (const [k, x] of a) all.set(k, x.k);
  for (const [k, x] of b) all.set(k, x.k);
  const keys = sortedBy([...all.entries()], ([, k]) => [k[0] ?? DATE_MIN, k[1]] as SortKey);
  const diffs = keys.filter(([k]) => a.get(k)?.v !== b.get(k)?.v).map(([k, kk]) => [kk, b.get(k)?.v ?? null, a.get(k)?.v ?? null] as const);
  const both = [...a.keys()].filter((k) => b.has(k)).length;
  const head = `매입매출장 대조(${label}): 분개장 ${a.size}건 · 매입매출장 ${b.size}건 · 같음 ${both - diffs.filter(([, x, y]) => x !== null && y !== null).length}건 · 다름 ${diffs.length}건`;
  const lines = [head];
  for (const [[d, no], x, y] of diffs.slice(0, 10)) {
    lines.push(`  ${label} ${d ?? "날짜 없음"} 전표 ${no}: 매입매출장 ${x === null ? "없음" : won(x) + "원"} · 분개장 ${y === null ? "없음" : won(y) + "원"}`);
  }
  if (diffs.length > 10) lines.push(`  … 그 밖에 ${diffs.length - 10}건`);
  return lines;
}

function years(rows: { date: IsoDate | null }[]): Set<number> {
  return new Set(rows.filter((r) => r.date !== null).map((r) => Number(r.date!.slice(0, 4))));
}

function inSpans(d: IsoDate, spans: [IsoDate, IsoDate][]): boolean {
  return spans.some(([a, b]) => a <= d && d <= b);
}

function gaps(spans: [IsoDate, IsoDate][]): [IsoDate, IsoDate][] {
  const out: [IsoDate, IsoDate][] = [];
  let cur: IsoDate | null = null;
  for (const [a, b] of sortedBy(spans, (s) => [s[0], s[1]])) {
    if (cur !== null && a > addDays(cur, 1)) out.push([addDays(cur, 1), addDays(a, -1)]);
    cur = cur === null || b > (cur as string) ? b : cur;
  }
  return out;
}

function monthEndOf(d: IsoDate): IsoDate {
  const y = Number(d.slice(0, 4)), m = Number(d.slice(5, 7));
  const ny = y + (m === 12 ? 1 : 0), nm = (m % 12) + 1;
  return addDays(isoOf(ny, nm, 1), -1);
}

function spanOf(rows: { date: IsoDate | null }[], info: BookInfo): [IsoDate, IsoDate] | null {
  if (info.period) return info.period;
  const days = rows.filter((r) => r.date !== null).map((r) => r.date!);
  if (!days.length) return null;
  const a = days.reduce((m, x) => (x < m ? x : m)), b = days.reduce((m, x) => (x > m ? x : m));
  return [a.slice(0, 8) + "01", monthEndOf(b)];
}

function readFail(name: string, err: unknown): string {
  const why = err instanceof WehagoError ? err.message : "내용을 읽을 수 없음";
  return `${name} — ${why}`;
}

type Foreign = [string, string][];

/** I8 고침(스위치 journalDedupLineId): 같은 해 안에서 줄 번호(line_id)가 두 번 나오면 앞 줄만 쓴다 (한 파일 안 같은 줄이 두 번 들어간 받기).
 *  꺼짐이면 그대로 돌려준다. */
export function dedupLineIds(journal: JLine[], notes: string[]): JLine[] {
  if (!CONVERT_RULES.journalDedupLineId) return journal;
  const seen = new Set<string>();
  const out: JLine[] = [];
  let dropped = 0;
  for (const ln of journal) {
    const k = ln.line_id && ln.date !== null ? ln.date.slice(0, 4) + "|" + ln.line_id : null;
    if (k !== null && seen.has(k)) { dropped++; continue; }
    if (k !== null) seen.add(k);
    out.push(ln);
  }
  if (dropped) notes.push(`[확인] 분개장에 같은 줄 번호가 두 번 나온 줄 ${dropped}건은 한 번만 셈 — 분개장을 다시 받아 넣으세요`);
  return out;
}

function sameYearLayers(ctx: BookCtx, names: string[], rows: JLine[], period: [IsoDate, IsoDate], asof: IsoDate | null, company: string,
  foreign: Foreign | null, gone: JLine[] = []): [JLine[], string[], string[], Map<string, string>, [IsoDate, IsoDate][]] {
  const spans: [IsoDate, IsoDate][] = [period];
  const added: JLine[] = [], used: string[] = [], rest: string[] = [];
  const slips = new Map<string, string>();
  const year0 = period[0].slice(0, 4) + "-01-01";
  const seen = new Set(rows.filter((r) => r.line_id).map((r) => r.line_id as string));
  for (const n of names) {
    let more: JLine[], info: BookInfo;
    try {
      [more, info] = readBook(ctx, join(ctx.folder, n), "분개장", fileDate(n), asof) as [JLine[], BookInfo];
    } catch {
      rest.push(n);
      continue;
    }
    if (!sameCompany(company, info.company)) {
      rest.push(n);
      if (foreign !== null) foreign.push([n, info.company]);
      continue;
    }
    const p = info.period;
    if (p === null || p[1] < year0) { rest.push(n); continue; }
    const keep = more.filter((r) => r.date !== null && p[0] <= r.date && r.date <= p[1] && !inSpans(r.date, spans)
      && !(r.line_id && seen.has(r.line_id)));
    // I8 고침(스위치): 더 새 파일이 맡은 기간에 있던 줄인데 그 줄 번호가 더 새 파일 어디에도 없음 → 날짜를 옛 기간으로 고쳤거나 지운 전표
    if (CONVERT_RULES.journalDedupLineId) {
      for (const r of more) {
        if (r.line_id && r.date !== null && p[0] <= r.date && r.date <= p[1] && inSpans(r.date, spans) && !seen.has(r.line_id)) gone.push(r);
      }
    }
    spans.push(p);
    for (const r of more) if (r.line_id && p[0] <= (r.date ?? p[0]) && (r.date ?? p[0]) <= p[1]) seen.add(r.line_id);
    if (keep.length) {
      added.push(...keep);
      used.push(n);
      const days = new Set(keep.map((r) => r.date as string));
      for (const [k, v] of info.slip_projects) if (days.has(k.split("|")[0] as string)) slips.set(k, v);
    } else rest.push(n);
  }
  return [added, used, rest, slips, spans];
}

function priorYears(ctx: BookCtx, kind: string, names: string[], rows: (JLine | LRow)[], asof: IsoDate | null, company: string,
  foreign: Foreign | null, period: [IsoDate, IsoDate] | null):
  [(JLine | LRow)[], string[], string[], Map<string, string>, [IsoDate, IsoDate][], string[]] {
  const ys = years(rows);
  let floor: number | null = ys.size ? Math.min(...ys) : null;
  if (floor === null) floor = period ? Number(period[0].slice(0, 4)) : asof ? Number(asof.slice(0, 4)) : null;
  const picks: [string, (JLine | LRow)[], BookInfo][] = [];
  const skipped: string[] = [], failed: string[] = [];
  for (const n of names) {
    let more: (JLine | LRow)[], mi: BookInfo;
    try {
      [more, mi] = readBook(ctx, join(ctx.folder, n), kind, fileDate(n), asof);
    } catch (e) {
      skipped.push(n);
      failed.push(readFail(n, e));
      continue;
    }
    if (!sameCompany(company, mi.company)) {
      skipped.push(n);
      if (foreign !== null) foreign.push([n, mi.company]);
      continue;
    }
    const y2 = years(more);
    if (floor === null || !y2.size || Math.max(...y2) >= floor) { skipped.push(n); continue; }
    picks.push([n, more, mi]);
  }
  const added: (JLine | LRow)[] = [], used: string[] = [], spans: [IsoDate, IsoDate][] = [];
  const slips = new Map<string, string>();
  const seen = new Set<string>();
  picks.forEach(([n, more, mi], i) => {
    const span = spanOf(more, mi);
    const lid = (r: JLine | LRow) => (r as JLine).line_id;
    const keep = more.filter((r) => (r.date === null && i === 0) || (r.date !== null && !inSpans(r.date, spans)
      && (span === null || (span[0] <= r.date && r.date <= span[1])) && !(lid(r) && seen.has(r.date.slice(0, 4) + "|" + lid(r)))));
    for (const r of more) {
      if (lid(r) && r.date !== null && (span === null || (span[0] <= r.date && r.date <= span[1]))) seen.add(r.date.slice(0, 4) + "|" + lid(r));
    }
    if (span !== null) spans.push(span);
    if (!keep.length) { skipped.push(n); return; }
    added.push(...keep);
    used.push(n);
    const days = new Set(keep.filter((r) => r.date !== null).map((r) => r.date as string));
    for (const [k, v] of mi.slip_projects) if (days.has(k.split("|")[0] as string) && !slips.has(k)) slips.set(k, v);
  });
  const sortedAdded = sortedBy(added, (r) => [r.date !== null, r.date ?? DATE_MIN]);
  return [sortedAdded, [...used].sort(cmpStr), skipped, slips, spans, failed];
}

export interface FileEntry {
  name: string; file_date: IsoDate | null; last_date: IsoDate | null; ref_date: IsoDate | null; rows: number; skipped: number;
  undated: number; after_ref: number; extra_columns: string[]; extra_note: string; prior: string[]; layers: string[];
  sales?: number; other?: number; error?: string; company?: string;
}

export class Books {
  state = "자료 없음";
  reason = "";
  book_date: IsoDate | null = null;
  after_ref = 0;
  files: Partial<Record<Kind, FileEntry>> = {};
  header: { file: string; kind: string; missing: string[]; extra: string[] } | null = null;
  unused: string[] = [];
  journal: JLine[] = [];
  ledger: LRow[] = [];
  einvoice: LRow[] = [];
  slip_projects = new Map<string, string>();
  from_journal = false;
  journal_sales: LRow[] = [];
  notes: string[] = [];
  from_start = true;
  journal_gaps: [IsoDate, IsoDate][] = [];
  start_gap = "";
  company = "";
  /** D7 (새 시스템): 받다 만 새 분개장을 버리고 예전 분개장을 썼을 때 그 알림 (없으면 빈 목록). */
  dropped_partial: string[] = [];
}

/** D7: 받다 만(일부만 저장된) 자동수집 분개장인가 — read_journal_json 이 '일부만'·'모양이 달라' 로 거부한 파일. */
export function isPartialJournal(e: unknown): boolean {
  return e instanceof WehagoError && !(e instanceof HeaderMismatch)
    && /(일부만 저장된 파일이라 쓰지 않음|일부만 받았을 수 있어 쓰지 않음|모양이 달라 읽지 못함)/.test(e.message);
}

export interface LoadOpts { /** D7 고침: 받다 만 새 분개장은 버리고 예전 분개장으로 (기본 켬). */ skipPartialJournal?: boolean }

/** load_books(folder, asof, stale_days) */
export function loadBooks(ctx: BookCtx, asof: IsoDate, staleDays: number | null, opts: LoadOpts = {}): Books {
  const books = new Books();
  const folder = ctx.folder;
  const names = listFiles(ctx.files, folder).sort(cmpStr);
  const folderOk = true;
  const candidates: Record<string, string[]> = {}, lookalikes: Record<string, string[]> = {};
  for (const k of KINDS) { candidates[k] = []; lookalikes[k] = []; }
  let unused: string[] = [];
  for (const n of names) {
    if (n.startsWith("~$")) continue;
    const [kind, readable] = kindOf(n);
    if (kind === null) continue;
    const e = ext(n);
    if (e === ".xlsx" || ([".xls", ".json"].includes(e) && kind === "분개장")) (readable ? candidates[kind]! : unused).push(n);
    else if (readable && [".xls", ".csv"].includes(e)) lookalikes[kind]!.push(n);
  }
  const mt = (n: string) => ctx.mtimes[join(folder, n)] ?? 0;
  const chosen: Partial<Record<Kind, string>> = {}, others: Partial<Record<Kind, string[]>> = {};
  for (const kind of KINDS) {
    if (!candidates[kind]!.length) continue;
    let ranked = sortedBy(candidates[kind]!, (n) => [rankDate(n) ?? DATE_MIN, mt(n), n]);
    if (kind === "분개장" && opts.skipPartialJournal) {
      // D7 (새 시스템에서 바꿀 것): 가장 새 분개장이 받다 만 파일이면 버리고 그 앞 파일을 고른다 (경고는 notes 와 dropped_partial)
      while (ranked.length > 1) {
        const top = ranked[ranked.length - 1] as string;
        try {
          readBook(ctx, join(folder, top), "분개장", fileDate(top), asof);
          break;
        } catch (e) {
          if (!isPartialJournal(e)) break;
          books.dropped_partial.push(`경고: 받다 만 분개장은 쓰지 않음 — ${(e as Error).message.replace(" 확장에서 분개장을 다시 받으세요", "")} → 예전 분개장 ${ranked[ranked.length - 2]} 으로 계산함 (확장에서 분개장을 다시 받으세요)`);
          unused.push(top);
          ranked = ranked.slice(0, -1);
        }
      }
    }
    chosen[kind] = ranked[ranked.length - 1];
    others[kind] = ranked.slice(0, -1).reverse();
  }
  const staged: Partial<Record<Kind, (JLine | LRow)[]>> = {};
  const mismatches: HeaderMismatch[] = [];
  let failures: string[] = [];
  let slipProjects = new Map<string, string>(), journalSlips = new Map<string, string>();
  let ledgerSales: LRow[] = [];
  const side: Partial<Record<Kind, string>> = {};
  for (const kind of KINDS) {
    const name = chosen[kind];
    if (name === undefined) continue;
    const fdate = fileDate(name);
    const entry: FileEntry = { name, file_date: fdate, last_date: null, ref_date: fdate, rows: 0, skipped: 0, undated: 0, after_ref: 0,
      extra_columns: [], extra_note: "", prior: [], layers: [] };
    books.files[kind] = entry;
    let rows: (JLine | LRow)[], info: BookInfo;
    try {
      [rows, info] = readBook(ctx, join(folder, name), kind, fdate, asof, kind === "매입매출장");
    } catch (e) {
      if (e instanceof HeaderMismatch) {
        entry.error = e.message;
        mismatches.push(e);
        side[kind] = e.message;
      } else if (e instanceof WehagoError) {
        entry.error = e.message;
        failures.push(`${name} 읽기 실패 — ${e.message}`);
        side[kind] = failures[failures.length - 1];
      } else {
        entry.error = "엑셀 내용을 읽을 수 없음";
        failures.push(`${name} 읽기 실패 — 엑셀 내용을 읽을 수 없음`);
        side[kind] = failures[failures.length - 1];
      }
      continue;
    }
    entry.last_date = info.last_date;
    entry.rows = info.rows;
    entry.skipped = info.skipped;
    entry.undated = info.undated;
    entry.sales = info.sales;
    entry.other = info.other;
    entry.after_ref = info.after_ref;
    entry.extra_columns = info.extra_columns;
    entry.extra_note = info.extra_note;
    entry.ref_date = fdate || info.last_date;
    let namesLeft = others[kind] ?? [];
    let layerSlips = new Map<string, string>();
    const foreign: Foreign = [];
    let spans: ([IsoDate, IsoDate] | null)[] = [spanOf(rows, info)];
    const company = info.company || "";
    if (kind === "분개장") { entry.company = company; books.company = company; }
    if (kind === "분개장" && info.period && namesLeft.length) {
      let layerRows: JLine[];
      let sp: [IsoDate, IsoDate][];
      const gone: JLine[] = [];
      [layerRows, entry.layers, namesLeft, layerSlips, sp] = sameYearLayers(ctx, namesLeft, rows as JLine[], info.period, asof, company, foreign, gone);
      spans = sp;
      const kept = new Set(layerRows.map((r) => r.line_id));
      const lost = gone.filter((r) => !kept.has(r.line_id));
      if (lost.length) {
        const ids = [...new Set(lost.map((r) => `${r.date} 전표 ${r.no}`))].slice(0, 5).join(", ");
        books.notes.push(`[확인] 이전 분개장에 있던 줄 ${lost.length}건(${ids})이 더 새 분개장 ${name} 에 없음 — 날짜를 옛 기간으로 고쳤다면 그 기간 분개장을 다시 받아 넣으세요 (지웠으면 그대로 두면 됨)`);
      }
      if (entry.layers.length) {
        const [a, b] = info.period;
        rows = sortedBy([...layerRows, ...rows], (r) => [r.date === null, r.date ?? DATE_MIN]);
        books.notes.push(`분개장 ${a}~${b} 는 ${name}, 그 밖의 날짜는 이전 파일(${entry.layers.join(", ")})`);
      }
    }
    const [priorRows, prior, skipped, priorSlips0, priorSpans, priorFailed] = priorYears(ctx, kind, namesLeft, rows, asof, company, foreign, info.period);
    entry.prior = prior;
    for (const [n, co] of foreign) {
      books.notes.unshift(`[확인] ${kind} ${n} 은 다른 회사(${co}) 장부로 적혀 있어 쓰지 않음 — 가장 새 파일 ${name} 은 ${company}. 다른 회사 자료면 지우고, 이 회사 장부가 맞는지 확인하세요`);
    }
    for (const f of priorFailed) {
      books.notes.unshift(`[확인] ${kind} 파일을 읽지 못해 쓰지 않음: ${f} — 지난해 장부라면 그 해 전표가 빠진 채 계산됩니다. 위하고에서 다시 받아 넣으세요`);
    }
    if (kind === "분개장") {
      books.journal_gaps = entry.layers.length || entry.prior.length ? gaps([...spans, ...priorSpans].filter((s): s is [IsoDate, IsoDate] => s !== null)) : [];
      for (const [g0, g1] of books.journal_gaps) books.notes.unshift(`[확인] 분개장 ${g0}~${g1} 전표가 어느 파일에도 없음 — 그 기간 분개장을 받아 넣으세요`);
    }
    const priorSlips = new Map(priorSlips0);
    for (const [k, v] of layerSlips) priorSlips.set(k, v);
    unused.push(...skipped);
    staged[kind] = [...priorRows, ...rows];
    if (kind === "매입매출장") {
      slipProjects = info.slip_projects;
      ledgerSales = info.sales_rows;
    } else if (kind === "분개장") {
      journalSlips = new Map(priorSlips);
      for (const [k, v] of info.slip_projects) journalSlips.set(k, v);
    }
  }
  const derived = staged["분개장"] ? invoicesFromJournal(staged["분개장"] as JLine[]) : [[], []] as [LRow[], LRow[]];
  const fromJournal = derived[0].length > 0 || derived[1].length > 0;
  let basis: readonly Kind[];
  let mm = mismatches;
  if (fromJournal) {
    basis = ["분개장"];
    mm = mismatches.filter((e) => e.kind === "분개장");
    const sideOther = Object.entries(side).filter(([k]) => k !== "분개장").map(([, v]) => v);
    failures = failures.filter((f) => !sideOther.includes(f));
    for (const [k, v] of Object.entries(side)) if (k !== "분개장") books.notes.push(`${k} 대조 못함 — ${v}`);
  } else basis = KINDS;
  for (const kind of KINDS) if (!staged[kind]) unused.push(...(others[kind] ?? []));
  books.unused = [...unused].sort(cmpStr);
  const refs = basis.filter((k) => books.files[k] && books.files[k]!.ref_date).map((k) => books.files[k]!.ref_date as IsoDate);
  books.book_date = refs.length ? refs.reduce((m, x) => (x < m ? x : m)) : null;
  books.after_ref = Object.values(books.files).reduce((s, e) => s + (e as FileEntry).after_ref, 0);
  const missing = basis.filter((k) => chosen[k] === undefined);
  if (mm.length) {
    books.state = "머리글 다름";
    books.reason = mm.map((e) => e.message).join("; ");
    const e = mm[0]!;
    books.header = { file: e.file, kind: e.kind, missing: [...e.missing], extra: [...e.extra] };
  } else if (failures.length) {
    books.state = "읽기 실패";
    books.reason = failures.join("; ");
  } else if (missing.length) {
    books.state = "자료 없음";
    books.reason = "자료 없음: " + missing.join(", ");
    const hints = missing.flatMap((k) => lookalikes[k]!.map((n) => `${n} 있음`));
    if (hints.length) books.reason += ` — .xlsx만 읽음 (${hints.join(", ")})`;
    if (!folderOk) books.reason += " (폴더를 찾을 수 없음)";
  } else {
    const refAll = basis.map((k) => books.files[k]!.ref_date);
    if (refAll.includes(null)) {
      books.state = "경과";
      books.reason = "장부 기준일을 알 수 없음 (파일 이름에 날짜가 없고 전표일자도 없음)";
    } else {
      const late = daysDiff(books.book_date as IsoDate, asof);
      if (staleDays !== null && late > staleDays) {
        const oldest = basis.filter((k) => books.files[k]!.ref_date === books.book_date)[0] as string;
        books.state = "경과";
        books.reason = `장부 기준일 ${books.book_date}, 기준일보다 ${late}일 이전 (${oldest})`;
      } else books.state = "ok";
    }
  }
  if (staged["분개장"]) {
    const j = staged["분개장"] as JLine[];
    books.from_start = journalFromStart(j);
    if (books.from_start && books.journal_gaps.length) {
      books.from_start = false;
      books.start_gap = `분개장에 빈 기간 있음 (${books.journal_gaps.map(([a, b]) => `${a}~${b}`).join(", ")})`;
    } else if (!books.from_start) {
      const dated = j.filter((ln) => ln.date !== null).map((ln) => ln.date as string);
      const first = dated.length ? dated.reduce((m, x) => (x < m ? x : m)) : null;
      books.notes.unshift(`[확인] 분개장이 ${first ?? "날짜 모름"}부터라 작년 분개장이 빠졌음 (전기이월·설립 자본금 줄 없음) — 수집\\위하고 에 `
        + `작년 분개장(예: 분개장_${first ? Number(first.slice(0, 4)) - 1 : 0}.xls)을 함께 넣으세요. 그 전까지 통장 잔액은 분개장으로 만들지 않고, `
        + "미지급금·차입금·매출채권은 올해 늘고 준 금액만입니다");
    }
  }
  if (books.state === "ok" && fromJournal) {
    books.journal = dedupLineIds(staged["분개장"] as JLine[], books.notes);
    books.ledger = derived[0];
    books.einvoice = [];
    books.journal_sales = derived[1];
    books.from_journal = true;
    books.slip_projects = journalSlips;
    books.notes.unshift(`계산서 자료: 분개장 매입전표 ${derived[0].length}건 · 매출전표 ${derived[1].length}건 (분개장 기준, 매입매출장·전자세금계산서는 있으면 대조만)`);
    if (staged["매입매출장"]) {
      books.notes.push(...compareInvoices(derived[0], staged["매입매출장"] as LRow[], "매입"));
      books.notes.push(...compareInvoices(derived[1], ledgerSales, "매출"));
    }
    if (staged["전자세금계산서(매입)"]) books.notes.push(`전자세금계산서(매입) ${books.files["전자세금계산서(매입)"]!.name} 은(는) 쓰지 않음 (분개장 매입전표 기준)`);
  } else if (books.state === "ok") {
    books.journal = dedupLineIds(staged["분개장"] as JLine[], books.notes);
    books.ledger = staged["매입매출장"] as LRow[];
    books.einvoice = staged["전자세금계산서(매입)"] as LRow[];
    books.slip_projects = slipProjects;
  }
  return books;
}

/** (b - a).days */
export function daysDiff(a: IsoDate, b: IsoDate): number {
  return daysBetween(a, b);
}

// ───────────── 매출 계산서 원천 (D-41) ─────────────
const SALES_NONE = "자료 없음 (매출 계산서 엑셀)";

export interface SaleRow {
  date: IsoDate | null; no: string; vendor: string; vendor_norm: string; item: string; supply: number | null; vat: number | null;
  total: number | null; code: string | null; type: string; credit_account: string; deducted: number; advance: boolean | null | undefined;
}

export interface Sales {
  state: string; reason: string; source: string; file: string; file_date: IsoDate | null; rows: SaleRow[]; notes: string[];
}

function salesRow(item: LRow): SaleRow {
  return { date: item.date, no: item.no ?? "", vendor: item.vendor, vendor_norm: item.vendor_norm, item: item.item, supply: item.supply,
    vat: item.vat, total: item.total, code: item.code, type: item.type ?? "", credit_account: item.credit_account ?? "",
    deducted: item.deducted || 0, advance: item.advance };
}

/** load_sales */
export function loadSales(ctx: BookCtx, asof: IsoDate, books: Books | null): Sales {
  const res: Sales = { state: "자료 없음", reason: SALES_NONE, source: "", file: "", file_date: null, rows: [], notes: [] };
  if (books !== null && books.from_journal) {
    const name = books.files["분개장"]!.name;
    res.source = "분개장 매출전표";
    res.file = name;
    res.file_date = fileDate(name);
    if (!books.journal_sales.length) {
      res.reason = `${SALES_NONE} — ${name}에 매출전표가 없음`;
      return res;
    }
    res.rows = books.journal_sales.map(salesRow);
    res.state = "ok";
    res.reason = "";
    return res;
  }
  const names = listFiles(ctx.files, ctx.folder).sort(cmpStr);
  const found: Record<string, string[]> = { "매입매출장(매출)": [], "전자세금계산서(매출)": [] };
  const lookalikes: string[] = [];
  for (const n of names) {
    if (n.startsWith("~$")) continue;
    const kind = salesKindOf(n);
    if (kind === null) continue;
    const e = ext(n);
    if (e === ".xlsx") found[kind]!.push(n);
    else if ([".xls", ".csv"].includes(e)) lookalikes.push(n);
  }
  const ledger = books !== null ? books.files["매입매출장"] : undefined;
  let chosen: [string, string, string, boolean] | null = null;
  if (ledger && !ledger.error && (ledger.sales || 0) > 0) chosen = ["매입매출장", ledger.name, "매입매출장", true];
  else {
    for (const [source, readKind] of [["매입매출장(매출)", "매입매출장"], ["전자세금계산서(매출)", "전자세금계산서(매입)"]] as const) {
      if (found[source]!.length) {
        const ranked = sortedBy(found[source]!, (n) => [fileDate(n) ?? DATE_MIN, ctx.mtimes[join(ctx.folder, n)] ?? 0, n]);
        chosen = [source, ranked[ranked.length - 1] as string, readKind, source === "매입매출장(매출)"];
        break;
      }
    }
  }
  if (chosen === null) {
    if (lookalikes.length) res.reason += ` — .xlsx만 읽음 (${lookalikes.map((n) => `${n} 있음`).join(", ")})`;
    return res;
  }
  const [source, name, readKind, keep] = chosen;
  const unusedNames = [...SALES_KINDS.flatMap((k) => found[k]!.filter((n) => n !== name))].sort(cmpStr);
  if (unusedNames.length) res.notes.push("쓰지 않은 매출 파일: " + unusedNames.join(", "));
  res.source = source;
  res.file = name;
  res.file_date = fileDate(name);
  let rows: (JLine | LRow)[], info: BookInfo;
  try {
    [rows, info] = readBook(ctx, join(ctx.folder, name), readKind, res.file_date, asof, keep);
  } catch (e) {
    if (e instanceof HeaderMismatch) {
      res.state = "머리글 다름";
      res.reason = `매출 계산서 엑셀 머리글 다름 — ${name}: 없는 열 ${e.missing.join(", ")}`;
      return res;
    }
    res.state = "읽기 실패";
    res.reason = `매출 계산서 엑셀 읽기 실패 — ${name}`;
    return res;
  }
  let picked: LRow[];
  if (source === "전자세금계산서(매출)") picked = rows as LRow[];
  else {
    picked = info.sales_rows;
    const ignored = source === "매입매출장(매출)" ? rows.length + info.other : 0;
    if (ignored) res.notes.push(`매입매출장(매출) 파일의 매출 아닌 줄 ${ignored}건 무시`);
  }
  if (!picked.length) {
    res.reason = `${SALES_NONE} — ${name}에 매출 줄이 없음`;
    return res;
  }
  res.rows = picked.map(salesRow);
  res.state = "ok";
  res.reason = "";
  const ref = books !== null ? books.book_date : null;
  if (res.file_date !== null && ref !== null && res.file_date < ref) {
    res.notes.push(`매출 계산서 파일 기준일 ${res.file_date} — 장부 기준일 ${ref}보다 ${daysDiff(res.file_date, ref)}일 이전`);
  }
  return res;
}

// ───────────── 요청 대조 (D-32) ─────────────
export const STATUSES = ["계산서 있음", "금액 차이", "계산서 없음", "이미 지급", "연결 불가", "판단 불가"];
const PAYABLE = ["미지급금", "미지급비용"];
const NOT_OK_LABEL: Record<string, string> = { "자료 없음": "판단 불가(WEHAGO 자료 없음)", "경과": "판단 불가(WEHAGO 자료 경과)",
  "머리글 다름": "판단 불가(머리글 다름)", "읽기 실패": "판단 불가(WEHAGO 읽기 실패)" };

/** linking.requests_of 의 요청 한 건. */
export interface Request {
  id: string; "번호": string; name: string; vendor: string; code: string | null; registered: string | null; status: string;
  amount: number | null; request_date: IsoDate | null; date: IsoDate | null; rule: string; status_text: string; old?: boolean;
}

export interface MatchRow {
  status: string; label: string; invoice_total: number | null; diff: number | null; schedule_amount: number | null; candidates: number;
  source: string | null; payment: { date: IsoDate; no: string; amount: number | null } | null;
}

export interface Match { rows: Record<string, MatchRow>; summary: Record<string, unknown> }

function signed(v: number): string {
  return (v > 0 ? "+" : "") + won(v);
}

export function isPayable(line: JLine): boolean {
  return PAYABLE.includes(squash(line.account));
}

function invoicesFor(books: Books, key: string, code: string): [string | null, [number, LRow][]] {
  for (const [source, rows] of [["매입매출장", books.ledger], ["전자세금계산서(매입)", books.einvoice]] as const) {
    const found = rows.map((r, i) => [i, r] as [number, LRow]).filter(([, r]) => r.vendor_norm === key && r.code === code);
    if (found.length) return [source, found];
  }
  return [null, []];
}

export function paidInvoices(books: Books): Set<string> {
  const ref = books.book_date;
  const lines = sortedBy(books.journal.map((line, i) => [line, i] as const)
    .filter(([line]) => isPayable(line) && line.debit !== null && line.date !== null && (ref === null || line.date <= ref)), ([l, i]) => [l.date as string, i])
    .map(([, i]) => i);
  const out = new Set<string>();
  for (const [source, rows] of [["매입매출장", books.ledger], ["전자세금계산서(매입)", books.einvoice]] as const) {
    const used = new Set<number>();
    const order = sortedBy(rows.map((_, i) => i), (i) => [rows[i]!.date ?? DATE_MIN, i]);
    for (const i of order) {
      const inv = rows[i]!;
      if (inv.total === null) continue;
      for (const j of lines) {
        const line = books.journal[j]!;
        if (used.has(j) || line.debit !== inv.total || line.vendor_norm !== inv.vendor_norm) continue;
        if (inv.date !== null && (line.date as string) < inv.date) continue;
        if (line.code !== null && line.code !== inv.code) continue;
        used.add(j);
        out.add(source + "|" + i);
        break;
      }
    }
  }
  return out;
}

function paymentLines(books: Books, rq: Request, key: string): number[] {
  const reg = rq.registered ? rq.registered.slice(0, 10) : null;
  if (reg === null) return [];
  const ref = books.book_date;
  const out: number[] = [];
  books.journal.forEach((line, i) => {
    if (!isPayable(line) || line.debit !== rq.amount || line.vendor_norm !== key) return;
    if (line.date === null || line.date < reg) return;
    if (ref !== null && line.date > ref) return;
    if (line.code !== null && line.code !== rq.code) return;
    out.push(i);
  });
  return out;
}

function mrow(rq: Request, status: string, label: string, more: Partial<MatchRow> = {}): MatchRow {
  return { status, label, invoice_total: null, diff: null, schedule_amount: rq.amount, candidates: 0, source: null, payment: null, ...more };
}

function summary(requests: Request[], rows: Record<string, MatchRow>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const status of STATUSES) {
    const items = requests.filter((rq) => rows[rq["번호"]]!.status === status);
    const picked = items.map((rq) => rows[rq["번호"]]!);
    const [total, unknown] = ssumOrNone(items.map((rq) => rq.amount));
    const invoices = picked.filter((r) => r.invoice_total !== null).map((r) => r.invoice_total as number);
    const diffStatus = status === "금액 차이";
    out[status] = { count: items.length, sum: total, unknown, diff: diffStatus ? picked.reduce((s, r) => s + (r.diff as number), 0) : null,
      invoice_sum: ["계산서 있음", "금액 차이"].includes(status) ? invoices.reduce((s, x) => s + x, 0) : null,
      schedule_sum: diffStatus ? picked.reduce((s, r) => s + (r.schedule_amount as number), 0) : null,
      lower: diffStatus ? picked.filter((r) => (r.diff as number) < 0).length : null };
  }
  return out;
}

/** match_requests */
export function matchRequests(books: Books, requests: Request[]): Match {
  const seen = new Set<string>();
  for (const rq of requests) {
    if (seen.has(rq["번호"])) throw new Error(`지급요청 번호가 겹침: '${rq["번호"]}' — 요청을 구별할 수 없음`);
    seen.add(rq["번호"]);
  }
  const rows: Record<string, MatchRow> = {};
  if (books.state !== "ok") {
    const text = NOT_OK_LABEL[books.state] ?? NOT_OK_LABEL["자료 없음"]!;
    for (const rq of requests) rows[rq["번호"]] = mrow(rq, "판단 불가", text);
    return { rows, summary: summary(requests, rows) };
  }
  const known = new Set<string>([...books.journal, ...books.ledger, ...books.einvoice].map((r) => r.vendor_norm));
  const settled = paidInvoices(books);
  interface Item { lines: number[]; source: string | null; found: [number, LRow][]; open: [number, LRow][]; exact: [number, LRow][] }
  const pending: Record<string, Item> = {};
  const payUsers = new Map<number, string[]>(), invUsers = new Map<string, string[]>(), loneUsers = new Map<string, string[]>();
  const push = <K>(m: Map<K, string[]>, k: K, v: string) => { if (!m.has(k)) m.set(k, []); m.get(k)!.push(v); };
  for (const rq of requests) {
    const no = rq["번호"], key = normVendor(rq.vendor);
    if (rq.amount === null) { rows[no] = mrow(rq, "연결 불가", "연결 불가 (금액 미확인)"); continue; }
    if (!known.has(key)) { rows[no] = mrow(rq, "연결 불가", "연결 불가 (거래처 후보 0건)"); continue; }
    const lines = paymentLines(books, rq, key);
    for (const i of lines) push(payUsers, i, no);
    const item: Item = { lines, source: null, found: [], open: [], exact: [] };
    if (!lines.length && rq.code) {
      [item.source, item.found] = invoicesFor(books, key, rq.code);
      item.open = item.found.filter(([i]) => !settled.has(item.source + "|" + i));
      item.exact = item.open.filter(([, r]) => r.total === rq.amount);
      if (item.exact.length === 1) push(invUsers, item.source + "|" + item.exact[0]![0], no);
      else if (!item.exact.length && item.open.length === 1) push(loneUsers, item.source + "|" + item.open[0]![0], no);
    }
    pending[no] = item;
  }
  for (const rq of requests) {
    const no = rq["번호"];
    if (rows[no]) continue;
    const item = pending[no]!;
    const lines = item.lines;
    if (lines.length) {
      if (rq.status !== "approved") {
        rows[no] = mrow(rq, "연결 불가", `연결 불가 (사장님 승인 전 요청인데 같은 금액 지급 기록 ${lines.length}건)`, { candidates: lines.length });
      } else if (lines.length === 1 && payUsers.get(lines[0]!)!.length === 1) {
        const line = books.journal[lines[0]!]!;
        rows[no] = mrow(rq, "이미 지급", `이미 지급 (분개장 ${line.date} 전표 ${line.no})`, { candidates: 1,
          payment: { date: line.date as string, no: line.no, amount: line.debit } });
      } else rows[no] = mrow(rq, "연결 불가", `연결 불가 (지급 후보 ${lines.length}건)`, { candidates: lines.length });
      continue;
    }
    if (!rq.code) { rows[no] = mrow(rq, "연결 불가", "연결 불가 (프로젝트 코드 없음)"); continue; }
    const { source, found, open, exact } = item;
    const suffix = source === "매입매출장" ? "" : " (전자세금계산서)";
    const more = { source, candidates: found.length };
    if (!found.length) rows[no] = mrow(rq, "계산서 없음", "계산서 없음", more);
    else if (!open.length) rows[no] = mrow(rq, "연결 불가", `연결 불가 (계산서 후보 ${found.length}건 모두 이미 지급됨)`, more);
    else if (exact.length === 1) {
      if (invUsers.get(source + "|" + exact[0]![0])!.length > 1) rows[no] = mrow(rq, "연결 불가", "연결 불가 (계산서 후보 공유)", more);
      else rows[no] = mrow(rq, "계산서 있음", "계산서 있음" + suffix, { ...more, invoice_total: exact[0]![1].total, diff: 0 });
    } else if (!exact.length && open.length === 1 && open[0]![1].total !== null) {
      const k = source + "|" + open[0]![0];
      if ((invUsers.get(k)?.length ?? 0) > 0 || loneUsers.get(k)!.length > 1) {
        rows[no] = mrow(rq, "연결 불가", "연결 불가 (계산서 후보 공유)", more);
        continue;
      }
      const total = open[0]![1].total as number;
      const diff = total - (rq.amount as number);
      const keep = diff < 0 ? " · 일정은 인트라넷 요청 금액" : "";
      rows[no] = mrow(rq, "금액 차이", `금액 차이 (계산서 ${won(total)} · 차액 ${signed(diff)}${keep})${suffix}`,
        { ...more, invoice_total: total, diff, schedule_amount: Math.max(total, rq.amount as number) });
    } else rows[no] = mrow(rq, "연결 불가", `연결 불가 (계산서 후보 ${open.length}건)`, more);
  }
  for (const rq of requests) {
    if (pending[rq["번호"]] && rq.registered === null && !rows[rq["번호"]]!.label.includes("판단 불가(등록일")) {
      rows[rq["번호"]]!.label += " · 이미 지급 판단 불가(등록일 없음)";
    }
  }
  return { rows, summary: summary(requests, rows) };
}
