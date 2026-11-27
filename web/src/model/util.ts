// ceo_report/util.py 의 계산 부분 (파일 읽기는 csv.ts). 값이 비면 null(미확인), 0 으로 바꾸지 않는다.
import type { IsoDate } from "./dates";
import { ymd } from "./dates";
import { PY_SPACE, asciiDigits, fmtComma, pyFixed, pyFloatParse, pyInt, pyRound, pyStrip } from "./py";

export type IssueLine = number | string;
export type IssueItem = [file: string, line: IssueLine, msg: string];

export class Issues {
  items: IssueItem[] = [];
  add(file: string, line: IssueLine, msg: string): void {
    this.items.push([file, line, msg]);
  }
}

/** 행: 머리글 → 칸 글자, 그리고 _file·_line (보통 줄 번호, 장부 정기예금 줄은 '정기예금 1' 같은 글자). */
export interface Row {
  [col: string]: string | number;
  _file: string;
  _line: number | string;
}

/** 파이썬 r.get(col): 칸이 없으면 undefined. */
export function rget(r: Row, col: string): string | undefined {
  if (!Object.prototype.hasOwnProperty.call(r, col)) return undefined;
  const v = r[col];
  return v === undefined ? undefined : String(v);
}

/** 파이썬 (r.get(col) or "") */
export function rs(r: Row, col: string): string {
  return rget(r, col) || "";
}

/** 파이썬 str(value) — None 은 "None". */
export function pyStr(v: unknown): string {
  if (v === null || v === undefined) return "None";
  if (v === true) return "True";
  if (v === false) return "False";
  return String(v);
}

const NUM_RE = /^[+-]?\p{Nd}+(\.\p{Nd}+)?(?=\n?$)/u;
const BLANKS = ["", "-", "미확인", "N/A", "n/a"];

/** 쉼표·'원'·공백(스페이스)을 없앤 글자. */
function plain(value: unknown): string {
  return pyStrip(pyStr(value)).replace(/,/g, "").replace(/원/g, "").replace(/ /g, "");
}

export function isBlank(value: unknown): boolean {
  return value === null || value === undefined || BLANKS.includes(plain(value));
}

/** util.num: '1,234,000' '-500' '(500)' → 숫자. 빈칸·'-'·'미확인' → null. */
export function num(value: unknown, issues?: Issues | null, row?: Row | null, col = ""): number | null {
  if (isBlank(value)) return null;
  if (row && row["_overflow"]) return null;   // 칸이 밀린 줄 (csv.ts 가 알림)
  let s = plain(value);
  const neg = s.startsWith("(") && s.endsWith(")");
  if (neg) s = s.slice(1, -1);
  if (!NUM_RE.test(s)) {
    if (issues && row) {
      issues.add(row._file, row._line, `${col} 값이 숫자가 아님: '${pyStr(value)}' (미확인으로 처리)`);
    }
    return null;
  }
  let v = pyFloatParse(s) as number;
  if (neg) v = -v;
  return pyRound(v);
}

/** util.setting_num → [값, 사유|null]. */
export function settingNum(settings: Record<string, string | undefined>, key: string, dflt: number): [number, string | null] {
  const raw = Object.prototype.hasOwnProperty.call(settings, key) ? settings[key] : undefined;
  if (isBlank(raw)) return [dflt, "설정 비어 있음"];
  const s = plain(raw).replace(/%/g, "");
  if (!NUM_RE.test(s)) return [dflt, "숫자 아님"];
  const v = pyFloatParse(s) as number;
  return [v === pyInt(v) ? pyInt(v) : v, null];
}

const SP = "[" + PY_SPACE + "]";
const DATE_RE1 = new RegExp("^(\\p{Nd}{4})[-./](\\p{Nd}{1,2})[-./](\\p{Nd}{1,2})\\.?(?=\\n?$)", "u");
const DATE_RE2 = /^(\p{Nd}{4})(\p{Nd}{2})(\p{Nd}{2})(?=\n?$)/u;

/** util.date: '2026-11-02' '2026.11.02' '2026/11/2' '20261102' → IsoDate. 빈칸 → null. */
export function parseDate(value: unknown, issues?: Issues | null, row?: Row | null, col = ""): IsoDate | null {
  if (value === null || value === undefined) return null;
  let s = pyStrip(pyStr(value));
  if (!s) return null;
  s = s.split(" ")[0] as string;
  const m = DATE_RE1.exec(s) ?? DATE_RE2.exec(s);
  if (m) {
    try {
      return ymd(Number(asciiDigits(m[1] as string)), Number(asciiDigits(m[2] as string)), Number(asciiDigits(m[3] as string)));
    } catch {
      // 날짜 범위 밖 → 아래 알림
    }
  }
  if (issues && row) {
    issues.add(row._file, row._line, `${col} 날짜 형식 오류: '${pyStr(value)}' (날짜 없음으로 처리)`);
  }
  return null;
}

/** util.ssum → [숫자 합, 미확인 개수]. */
export function ssum(values: Iterable<number | null | undefined>): [number, number] {
  let total = 0, unknown = 0;
  for (const v of values) {
    if (v === null || v === undefined) unknown += 1;
    else total += v;
  }
  return [total, unknown];
}

/** util.ssum_or_none: 값이 있는데 전부 미확인이면 합계 null. */
export function ssumOrNone(values: Iterable<number | null | undefined>): [number | null, number] {
  const vals = [...values];
  const [total, unknown] = ssum(vals);
  return [vals.length && unknown === vals.length ? null : total, unknown];
}

/** util.won */
export function won(v: number | null | undefined, empty = "미확인"): string {
  if (v === null || v === undefined) return empty;
  return (v < 0 ? "−" : "") + fmtComma(Math.abs(pyInt(v)));
}

/** util.man: 백만원 단위 소수 1자리. */
export function man(v: number | null | undefined, empty = "미확인"): string {
  if (v === null || v === undefined) return empty;
  const x = v / 1_000_000;
  return (x < 0 ? "−" : "") + pyFixed(Math.abs(x), 1, true);
}

/** util.pct */
export function pct(a: number | null | undefined, b: number | null | undefined, empty = "판단 불가"): string {
  if (a === null || a === undefined || b === null || b === undefined || b === 0) return empty;
  return pyFixed((a * 100.0) / b, 1) + "%";
}

/** util.d2s */
export function d2s(d: IsoDate | null | undefined, empty = "날짜 없음"): string {
  return d ? d : empty;
}

const RRN_RE = new RegExp("\\p{Nd}{6}" + SP + "*[-‐‑‒–—―−﹣－.．/／]?" + SP + "*\\p{Nd}{7}", "gu");

/** util.mask_rrn */
export function maskRrn(text: unknown): string {
  return (text === null || text === undefined ? "" : String(text)).replace(RRN_RE, "******-*******");
}

/** html.escape(s) (quote=True) */
export function htmlEscape(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#x27;");
}

/** util.esc */
export function esc(s: unknown): string {
  return htmlEscape(maskRrn(s));
}
