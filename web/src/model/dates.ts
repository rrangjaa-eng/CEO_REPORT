// 날짜: "YYYY-MM-DD" 글자. 시간대를 타지 않게 Date 를 쓰지 않고 파이썬 date.toordinal 과 같은 정수 계산만 한다.
import { parseDate } from "./util";
import { PY_SPACE, floorDiv, pyMod } from "./py";

export type IsoDate = string;

const DIM = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];

export function isLeap(y: number): boolean {
  return y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0);
}

export function daysInMonth(y: number, m: number): number {
  return m === 2 && isLeap(y) ? 29 : (DIM[m] as number);
}

function daysBeforeYear(y: number): number {
  const y1 = y - 1;
  return y1 * 365 + floorDiv(y1, 4) - floorDiv(y1, 100) + floorDiv(y1, 400);
}

function daysBeforeMonth(y: number, m: number): number {
  let n = 0;
  for (let i = 1; i < m; i++) n += daysInMonth(y, i);
  return n;
}

export function ymd(y: number, m: number, d: number): IsoDate {
  if (y < 1 || y > 9999 || m < 1 || m > 12 || d < 1 || d > daysInMonth(y, m)) {
    throw new RangeError(`날짜 범위 밖: ${y}-${m}-${d}`);
  }
  return String(y).padStart(4, "0") + "-" + String(m).padStart(2, "0") + "-" + String(d).padStart(2, "0");
}

/** "YYYY-MM-DD" → [y, m, d]. */
export function parseIso(d: IsoDate): [number, number, number] {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(d);
  if (!m) throw new RangeError("IsoDate 아님: " + d);
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

/** 파이썬 date.toordinal() (0001-01-01 = 1). */
export function toOrdinal(d: IsoDate): number {
  const [y, m, dd] = parseIso(d);
  return daysBeforeYear(y) + daysBeforeMonth(y, m) + dd;
}

/** 파이썬 date.fromordinal(n). */
export function fromOrdinal(n: number): IsoDate {
  // 400년 = 146097일 주기
  let k = n - 1;
  const n400 = floorDiv(k, 146097);
  k = pyMod(k, 146097);
  const n100 = floorDiv(k, 36524);
  k = pyMod(k, 36524);
  const n4 = floorDiv(k, 1461);
  k = pyMod(k, 1461);
  const n1 = floorDiv(k, 365);
  k = pyMod(k, 365);
  const year = n400 * 400 + n100 * 100 + n4 * 4 + n1 + 1;
  if (n1 === 4 || n100 === 4) return ymd(year - 1, 12, 31);
  let month = 1;
  while (k >= daysInMonth(year, month)) {
    k -= daysInMonth(year, month);
    month += 1;
  }
  return ymd(year, month, k + 1);
}

export function addDays(d: IsoDate, n: number): IsoDate {
  return fromOrdinal(toOrdinal(d) + n);
}

/** (b - a).days */
export function daysBetween(a: IsoDate, b: IsoDate): number {
  return toOrdinal(b) - toOrdinal(a);
}

/** 파이썬 date.weekday(): 월=0 … 일=6. */
export function weekday(d: IsoDate): number {
  return pyMod(toOrdinal(d) + 6, 7);
}

/** calc._month_end */
export function monthEnd(d: IsoDate): IsoDate {
  const [y, m] = parseIso(d);
  return ymd(y, m, daysInMonth(y, m));
}

export function firstOfMonth(d: IsoDate): IsoDate {
  const [y, m] = parseIso(d);
  return ymd(y, m, 1);
}

/** calc._add_months: 달 끝을 넘으면 그 달 마지막 날. */
export function addMonths(d: IsoDate, n: number): IsoDate {
  const [y0, m0, d0] = parseIso(d);
  const y = y0 + floorDiv(m0 - 1 + n, 12);
  const m = pyMod(m0 - 1 + n, 12) + 1;
  return ymd(y, m, Math.min(d0, daysInMonth(y, m)));
}

/** calc._last_friday: 그 달 마지막 금요일. */
export function lastFriday(d: IsoDate): IsoDate {
  const e = monthEnd(d);
  return addDays(e, -pyMod(weekday(e) - 4, 7));
}

/** calc.budget_due */
export function budgetDue(eventDate: IsoDate | null, asof: IsoDate): IsoDate | null {
  if (eventDate === null) return null;
  const nxt = addMonths(firstOfMonth(eventDate), 1);
  let due = monthEnd(nxt);
  due = addDays(due, -pyMod(weekday(due) - 4, 7));
  if (due <= asof) {
    const first = addDays(asof, pyMod(4 - weekday(asof), 7) || 7);
    due = lastFriday(first);
    if (due <= first) due = lastFriday(addMonths(firstOfMonth(first), 1));
  }
  return due;
}

// 파이썬 \d = 유니코드 Nd, \s = 파이썬 공백, $ = 끝 또는 마지막 \n 앞
const S = "[" + PY_SPACE + "]*";
const D = "(\\p{Nd}{4}[.\\-/]\\p{Nd}{1,2}[.\\-/]\\p{Nd}{1,2})";
const RANGE_RE = new RegExp("^" + S + D + S + "[~\\-–]" + S + D + S + "(?=\\n?$)", "u");

/** calc._event_date: 기간('a~b'·'a-b')이면 끝난 날, 못 읽으면 null. */
export function eventDate(text: string | null | undefined): IsoDate | null {
  let t = text ?? "";
  const m = RANGE_RE.exec(t);
  if (m) t = m[2] as string;
  try {
    return parseDate(t);
  } catch {
    return null;
  }
}

/** calc.period_of */
export function periodOf(kind: string, asof: IsoDate, start?: IsoDate | null): [IsoDate, IsoDate] {
  if (start) return [start, asof];
  if (kind === "weekly") return [addDays(asof, -6), asof];
  return [firstOfMonth(asof), asof];
}

export const PAY_WEEKDAY = 4;

/** calc.pay_friday: 기준일 뒤 첫 금요일 (기준일이 금요일이면 다음 금요일). */
export function payFriday(asof: IsoDate): IsoDate {
  return addDays(asof, pyMod(PAY_WEEKDAY - weekday(asof) - 1, 7) + 1);
}

/** calc.period_ends */
export function periodEnds(kind: string, asof: IsoDate, payday?: IsoDate | null): [string, IsoDate][] {
  if (kind === "weekly") {
    const f = payday || payFriday(asof);
    const all = ["이번 주", "다음 주", "3주째", "4주째", "5주째"];
    const labs = all.slice(daysBetween(asof, f) >= 7 ? 1 : 0);
    return labs.slice(0, 4).map((lab, i) => [lab, addDays(f, 7 * i)] as [string, IsoDate]);
  }
  const out: [string, IsoDate][] = [];
  for (let i = 1; i < 4; i++) {
    const e = monthEnd(addMonths(asof, i));
    out.push([`${parseIso(e)[1]}월`, e]);
  }
  return out;
}
