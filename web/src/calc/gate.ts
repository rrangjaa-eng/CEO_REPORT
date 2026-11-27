// 자금계획서·분개장이 반영됐는지 확인 (막는 까닭) — 파이썬 ceo_report/gate.py problems·company_problems·max_days·book_date.
// 시험용 끄개(_test_off, 환경변수)는 옮기지 않는다 — 늘 켜짐.
// 바꿀 것 U10: 자금계획서 회사는 설정 회사명(모르면 분개장 회사)과 견준다. 예전에는 분개장이 다른 회사면 이 회사 자금계획서까지
//   "자금계획서가 다른 회사"라고 알렸다 — 이제 실제로 다른 회사인 쪽만 이름을 댄다.
import { daysBetween, type IsoDate } from "../model/dates";
import { PY_SPACE } from "../model/py";

/** problems 가 읽는 R 의 칸 (compute 결과 R 그대로 넘기면 됨). */
export interface GateR {
  asof: IsoDate;
  fundplan?: { used?: boolean; reason?: string; [k: string]: unknown } | null;
  settings_num?: Record<string, unknown> | null;
  settings?: Record<string, unknown> | null;
  auto_facts?: { book_date?: unknown; book_company?: unknown; plan_companies?: unknown[] | null; [k: string]: unknown } | null;
  s7?: { asof?: { name?: string | null; date?: IsoDate | null; [k: string]: unknown }[] | null; [k: string]: unknown } | null;
  tax_missing?: boolean;
  [k: string]: unknown;
}

export const MAX_DAYS = 7;

/** 파이썬 str(x) (회사 이름 칸: 글자·숫자·None). */
function pyStr(x: unknown): string {
  if (x === null || x === undefined) return "None";
  if (x === true) return "True";
  if (x === false) return "False";
  return String(x);
}
const STRIP = new RegExp("^[" + PY_SPACE + "]+|[" + PY_SPACE + "]+$", "g");
const strip = (s: string) => s.replace(STRIP, "");
/** 파이썬 str(x or "").strip() */
const textOf = (x: unknown) => strip(x === null || x === undefined || x === "" || x === 0 || x === false ? "" : pyStr(x));

/** 파이썬 int(x): 정수·소수(버림)·정수 글자. 못 바꾸면 null. */
function pyInt(x: unknown): number | null {
  if (typeof x === "boolean") return x ? 1 : 0;
  if (typeof x === "number") return Number.isFinite(x) ? Math.trunc(x) : null;
  if (typeof x === "string" && /^[+-]?\d+(_\d+)*$/.test(strip(x))) return parseInt(strip(x).replace(/_/g, ""), 10);
  return null;
}

export function maxDays(R: GateR): number {
  const raw = (R.settings_num || {})["위험_자료경과일"];
  const v = pyInt(raw || MAX_DAYS) ?? MAX_DAYS;
  return Math.min(Math.max(v, 0), MAX_DAYS);
}

function isoOk(s: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const [y, m, d] = s.split("-").map(Number) as [number, number, number];
  const t = new Date(Date.UTC(y, m - 1, d));
  return y >= 1 && t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
}

/** 분개장 기준일: 자동분석의 book_date → 없으면 자료기준일의 '회계' 줄. */
export function bookDate(R: GateR): IsoDate | null {
  const v = (R.auto_facts || {}).book_date;
  if (v) {
    const s = pyStr(v).slice(0, 10);
    if (isoOk(s)) return s;
  }
  const book = ((R.s7 || {}).asof || []).filter((a) => (a.name || "").includes("회계"));
  return book.length && book[0]!.date ? book[0]!.date : null;
}

const CO_WORDS = new RegExp("주식회사|유한회사|\\(주\\)|\\(유\\)|㈜|[" + PY_SPACE + "]+", "g");
export function companyKey(name: unknown): string {
  const s = name === null || name === undefined || name === "" || name === 0 || name === false ? "" : pyStr(name);
  return s.normalize("NFKC").replace(CO_WORDS, "").toLowerCase();
}
/** 두 회사 이름이 같은 회사인가 (어느 하나라도 모르면 같다고 봄, 한쪽이 다른 쪽을 품으면 같음). */
export function sameCompany(a: unknown, b: unknown): boolean {
  const x = companyKey(a), y = companyKey(b);
  if (!x || !y) return true;
  return x === y || (Math.min([...x].length, [...y].length) >= 2 && (x.includes(y) || y.includes(x)));
}

export function companyProblems(R: GateR): string[] {
  const facts = R.auto_facts || {};
  let mine = textOf((R.settings || {})["회사명"]);
  if (mine === "회사명") mine = "";
  const book = textOf(facts.book_company);
  const plans = (facts.plan_companies || []).map((c) => strip(pyStr(c))).filter((c) => c);
  const out: string[] = [];
  if (mine && book && !sameCompany(mine, book)) {
    out.push(`분개장이 다른 회사(${book}) 장부임 — 설정 회사명은 ${mine}. 위하고에서 이 회사 SmartA 화면을 앞에 띄우고 다시 받으세요 `
      + "(이름만 다르게 적은 것이면 설정.csv 회사명을 위하고 회사 이름과 같게 고치세요)");
  }
  for (const c of plans) {
    const ref = mine || book;   // U10: 설정 회사명이 있으면 그것과 견준다 (분개장이 다른 회사여도 이 회사 자금계획서를 탓하지 않음)
    if (ref && !sameCompany(ref, c)) {
      out.push(`자금계획서가 다른 회사(${c}) 자료임 — ${mine ? "설정 회사명은" : "분개장은"} ${ref}. 위하고에서 이 회사 SmartA 화면을 앞에 띄우고 다시 받으세요`);
    }
  }
  return out;
}

/** 막는 까닭 목록 (없으면 []). */
export function problems(R: GateR): string[] {
  const out: string[] = [];
  const days = maxDays(R);
  const fp = R.fundplan;
  if (fp === null || fp === undefined) {
    out.push("자금계획서 없음 (수집\\위하고에 자금계획 파일이 없음 — 확장에서 '모두 받기' 또는 '바뀐 것 확인')");
  } else if (!fp.used) {
    out.push(fp.reason || "자금계획서를 쓰지 못함");
  }
  const bd = bookDate(R);
  if (bd === null) {
    out.push("분개장 자료일을 모름 (자료 변환을 다시 하세요)");
  } else if (daysBetween(bd, R.asof) > days) {
    out.push(`분개장 자료일 ${bd} — 기준일보다 ${daysBetween(bd, R.asof)}일 전 (허용 ${days}일)`);
  }
  if (R.tax_missing) {
    out.push("세금예상.csv 가 없거나 읽지 못함 — 급여·4대보험·원천세·부가세·법인세·카드 예상이 빠져 여유 자금이 크게 보임 "
      + "(자료 변환을 다시 하세요)");
  }
  out.push(...companyProblems(R));
  return out;
}
