// tax.py 의 변환 부분: 세금예상.csv 줄 (부가세·원천세·4대보험·급여·카드대금·정기예금·고정 지출).
// 보고서 쪽(merge)은 model 에 있다.
import type { IsoDate } from "../model/dates";
import { addDays, daysBetween, daysInMonth, parseIso, weekday, ymd } from "../model/dates";
import { cmpStr, fmtComma, pyFixed, pyIsDigit, pyRemoveSpace, pyRound, pyStrip, sortedBy } from "../model/py";
import { Issues } from "../model/util";
import { normCode } from "../model/vendor";
import { exists, join, readCsvFile, type ConvFiles } from "./files";
import type { JLine } from "./wehago";

export const COLUMNS = ["세목", "대상기간", "납부예정일", "금액", "상태", "근거", "과세표준", "산출세액", "기납부", "대손충당금", "세무조정",
  "거래처코드", "장부기준일"];
export const LOOKBACK_DAYS = 45;
export const AHEAD_MONTHS = 7;
export const FILE = "세금예상.csv";

export type TaxRow = Record<string, string>;
type YM = [number, number];

const sq = (text: unknown): string => pyRemoveSpace(text === null || text === undefined ? "" : String(text));
const code = (c: unknown): string => normCode(c as string);
const fmt = fmtComma;
const p2 = (n: number) => String(n).padStart(2, "0");
const ymNum = (k: YM) => k[0] * 12 + k[1];
const ymKey = (k: YM) => `${k[0]}-${k[1]}`;
const yOf = (d: IsoDate) => parseIso(d)[0];
const mOf = (d: IsoDate) => parseIso(d)[1];
const dOf = (d: IsoDate) => parseIso(d)[2];
const maxStr = (xs: string[]) => xs.reduce((a, b) => (b > a ? b : a));
const minStr = (xs: string[]) => xs.reduce((a, b) => (b < a ? b : a));
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

function netOf(ln: JLine, creditSide: boolean): number | null {
  const d = ln.debit, c = ln.credit;
  if (d === null && c === null) return null;
  return creditSide ? (c || 0) - (d || 0) : (d || 0) - (c || 0);
}

function quarter(d: IsoDate): [IsoDate, IsoDate] {
  const [y, m] = parseIso(d);
  const q = Math.floor((m - 1) / 3);
  const start = ymd(y, q * 3 + 1, 1);
  const end = addDays(ymd(y + (q === 3 ? 1 : 0), q === 3 ? 1 : q * 3 + 4, 1), -1);
  return [start, end];
}

function codes(lines: JLine[]): string[] {
  return [...new Set(lines.map((x) => code(x.vendor_code)).filter((c) => c))].sort(cmpStr);
}

function lastDate(journal: JLine[]): IsoDate | null {
  const dated = journal.map((ln) => ln.date).filter((d): d is string => d !== null);
  return dated.length ? maxStr(dated) : null;
}

const KR_HOLIDAYS = new Set([
  "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-02", "2026-05-05", "2026-05-25", "2026-06-03",
  "2026-08-17", "2026-09-24", "2026-09-25", "2026-09-28", "2026-10-05", "2026-10-09", "2026-12-25",
  "2027-01-01", "2027-02-08", "2027-02-09", "2027-03-01", "2027-05-05", "2027-05-13", "2027-08-16",
  "2027-09-14", "2027-09-15", "2027-09-16", "2027-10-04", "2027-10-11", "2027-12-27"]);
export const HOLIDAY_YEARS = new Set([...KR_HOLIDAYS].map(yOf));

const off = (d: IsoDate) => weekday(d) >= 5 || KR_HOLIDAYS.has(d);
function before(d: IsoDate): IsoDate {
  while (off(d)) d = addDays(d, -1);
  return d;
}
function after(d: IsoDate): IsoDate {
  while (off(d)) d = addDays(d, 1);
  return d;
}
function nextMonth(y: number, m: number, k = 1): YM {
  m += k;
  return [y + Math.floor((m - 1) / 12), (((m - 1) % 12) + 12) % 12 + 1];
}
function dayIn(y: number, m: number, day: number): IsoDate {
  return ymd(y, m, Math.min(day, daysInMonth(y, m)));
}

function stamp(rows: TaxRow[], journal: JLine[]): TaxRow[] {
  const last = lastDate(journal);
  for (const r of rows) {
    r["장부기준일"] = last ?? "";
    const y = r["납부예정일"] ? Number(r["납부예정일"].slice(0, 4)) : null;
    if (y && !HOLIDAY_YEARS.has(y)) r["근거"] += ` · 공휴일 표에 ${y}년 없음 (주말만 봄)`;
  }
  return rows;
}

const recent = (due: IsoDate, asof: IsoDate) => due > addDays(asof, -LOOKBACK_DAYS);

export function row(kind: string, period: string, due: IsoDate | null, amount: number | null, state: string, basis: string, cs: readonly string[] = []): TaxRow {
  return { "세목": kind, "대상기간": period, "납부예정일": due ?? "", "금액": amount === null ? "" : String(amount), "상태": state, "근거": basis,
    "과세표준": "", "산출세액": "", "기납부": "", "대손충당금": "", "세무조정": "", "거래처코드": cs.join(" "), "장부기준일": "" };
}

export const BANK_PREFIX = ["101", "102", "103"];
const startsAny = (s: string, ps: readonly string[]) => ps.some((p) => s.startsWith(p));
export function fromBank(lines: JLine[]): boolean {
  return lines.some((x) => startsAny(sq(x.account_code), BANK_PREFIX) && (x.credit || 0));
}

type SlipMap = Map<string, { date: IsoDate | null; no: string; lines: JLine[] }>;
function slipsOf(journal: JLine[], datedOnly = false): SlipMap {
  const out: SlipMap = new Map();
  for (const ln of journal) {
    if (datedOnly && ln.date === null) continue;
    const k = (ln.date ?? "\u0001") + "\u0000" + ln.no;
    if (!out.has(k)) out.set(k, { date: ln.date, no: ln.no, lines: [] });
    out.get(k)!.lines.push(ln);
  }
  return out;
}

/** vat */
export function vat(journal: JLine[], asof: IsoDate, outCodes0: string[] = ["25500"], inCodes0: string[] = ["13500"]): TaxRow[] {
  const outCodes = new Set(outCodes0.map(sq)), inCodes = new Set(inCodes0.map(sq));
  const both = (c: string) => outCodes.has(c) || inCodes.has(c);
  const slips = slipsOf(journal);
  const isPayment = (lines: JLine[]) => {
    const cs = lines.map((x) => sq(x.account_code));
    return lines.some((x) => outCodes.has(sq(x.account_code)) && (x.debit || 0)) && !cs.some((c) => inCodes.has(c)) && !cs.some((c) => c.startsWith("4"));
  };
  const payments = new Set<string>();
  for (const [k, s] of slips) if (s.date !== null && isPayment(s.lines)) payments.add(k);
  const isOffsetSettle = (lines: JLine[]) => lines.some((x) => outCodes.has(sq(x.account_code)) && (x.debit || 0))
    && lines.some((x) => inCodes.has(sq(x.account_code)) && (x.credit || 0))
    && lines.some((x) => !both(sq(x.account_code)) && (x.credit || 0))
    && !lines.some((x) => sq(x.account_code).startsWith("4"));
  for (const [k, s] of slips) if (s.date !== null && !payments.has(k) && isOffsetSettle(s.lines)) payments.add(k);
  const cash = new Set([...payments].filter((k) => fromBank(slips.get(k)!.lines)));
  const payableOf = (lines: JLine[]) => sum(lines.filter((x) => !both(sq(x.account_code))).map((x) => x.credit || 0));
  const cleared = (key: string) => {
    const s0 = slips.get(key)!;
    const acc = new Set(s0.lines.filter((x) => !both(sq(x.account_code)) && (x.credit || 0)).map((x) => sq(x.account_code)));
    const mine = codes(s0.lines.filter((x) => acc.has(sq(x.account_code))));
    const amt = payableOf(s0.lines);
    for (const [k2, s2] of slips) {
      if (s2.date === null || k2 === key || !(s0.date! <= s2.date && s2.date <= asof) || !fromBank(s2.lines)) continue;
      const hit = s2.lines.filter((x) => acc.has(sq(x.account_code)) && (x.debit || 0)
        && !(mine.length && code(x.vendor_code) && !mine.includes(code(x.vendor_code))));
      const t = sum(hit.map((x) => x.debit as number));
      if (t >= amt && amt > 0) return true;
    }
    return false;
  };
  const vcodes = codes([...[...payments].flatMap((k) => slips.get(k)!.lines.filter((x) => !startsAny(sq(x.account_code), BANK_PREFIX))),
    ...journal.filter((x) => sq(x.vendor).includes("세무서"))]);
  const dated = journal.map((ln) => ln.date).filter((d): d is string => d !== null);
  if (!dated.length) return [];
  const last = maxStr(dated);
  const starts = [...new Set(journal.filter((ln) => ln.date !== null && both(sq(ln.account_code))).map((ln) => quarter(ln.date!)[0]))].sort(cmpStr);
  const rows: TaxRow[] = [];
  for (const start of starts) {
    const [qStart, qEnd] = quarter(start);
    const [ey, em] = parseIso(qEnd);
    const due = after(ymd(ey + (em === 12 ? 1 : 0), em === 12 ? 1 : em + 1, 25));
    if (!recent(due, asof)) continue;
    let total = 0, unknown = 0, settled: number | null = null, paid = false;
    for (const [key, s] of slips) {
      const day = s.date;
      if (day === null) continue;
      if (payments.has(key)) {
        const inside = qStart <= day && day <= qEnd && isOffsetSettle(s.lines);
        if ((qEnd < day && day <= (due > asof ? due : asof)) || inside) {
          settled = (settled || 0) + payableOf(s.lines);
          paid = paid || (day <= asof && (cash.has(key) || cleared(key)));
        }
        continue;
      }
      if (!(qStart <= day && day <= qEnd)) continue;
      for (const x of s.lines) {
        const c = sq(x.account_code);
        if (!both(c)) continue;
        const v = netOf(x, outCodes.has(c));
        if (v === null) { unknown++; continue; }
        total += outCodes.has(c) ? v : -v;
      }
    }
    const [qy, qm] = parseIso(qStart);
    const period = `${qy}년 ${Math.floor((qm - 1) / 3) + 1}분기 (${qm}~${em}월)`;
    if (paid) continue;
    if (settled !== null) {
      rows.push(row("부가세", period, due, settled, "확정(전표)", "납부·미지급 전표 (부가세예수금 차변)", vcodes));
      continue;
    }
    let basis = "부가세예수금 − 부가세대급금 (앞 분기 납부 전표 제외)";
    if (last < qEnd) basis += `, ${last}까지 쌓인 금액 (남은 기간분은 더 늘어남)`;
    rows.push(row("부가세", period, due, unknown ? null : total, "예상", basis + (unknown ? ` · 금액 없는 줄 ${unknown}건` : ""), vcodes));
  }
  return stamp(rows, journal);
}

function months(start: IsoDate, end: IsoDate): YM[] {
  let [y, m] = parseIso(start);
  const [ey, em] = parseIso(end);
  const out: YM[] = [];
  while (y < ey || (y === ey && m <= em)) {
    out.push([y, m]);
    [y, m] = nextMonth(y, m);
  }
  return out;
}

/** withholding */
export function withholding(journal: JLine[], asof: IsoDate, codes0: string[] = ["25400"], vendors: string[] = ["세무서", "구청", "시청", "군청"],
  mode0 = "자동", screen: Map<string, number> | null = null): TaxRow[] {
  const cs = new Set(codes0.map(sq));
  const mine = journal.filter((ln) => ln.date !== null && cs.has(sq(ln.account_code)) && vendors.some((v) => sq(ln.vendor).includes(v)));
  if (!mine.length) return [];
  const paidDays = [...new Set(mine.filter((ln) => (ln.debit || 0) > 0).map((ln) => ln.date!))].sort(cmpStr);
  let mode = mode0;
  if (mode === "자동") {
    const maxY = paidDays.length ? Math.max(...paidDays.map(yOf)) : 0;
    const latest = paidDays.filter((d) => yOf(d) === maxY);
    mode = latest.length && latest.every((d) => mOf(d) === 1 || mOf(d) === 7) ? "반기" : "매월";
  }
  const last = maxStr(mine.map((ln) => ln.date!));
  const vcodes = codes(mine);
  const [uy, um] = nextMonth(yOf(asof), mOf(asof), AHEAD_MONTHS);
  const until = ymd(uy, um, 1);
  const periods: [string, IsoDate, IsoDate, IsoDate][] = [];
  if (mode === "반기") {
    const y0 = Math.min(...mine.map((ln) => yOf(ln.date!)));
    for (let year = y0; year <= uy; year++) {
      for (const h of [1, 2]) {
        const start = ymd(year, h === 1 ? 1 : 7, 1);
        const end = h === 1 ? ymd(year, 6, 30) : ymd(year, 12, 31);
        const due = after(ymd(year + (h === 2 ? 1 : 0), h === 2 ? 1 : 7, 10));
        if (start < until) periods.push([`${year}년 ${h === 1 ? "상" : "하"}반기 (${mOf(start)}~${mOf(end)}월)`, start, end, due]);
      }
    }
  } else {
    let [y, m] = sortedBy(mine.map((ln) => [yOf(ln.date!), mOf(ln.date!)] as YM), (k) => [k[0], k[1]])[0]!;
    while (ymd(y, m, 1) < until) {
      const start = ymd(y, m, 1);
      const end = addDays(ymd(y + (m === 12 ? 1 : 0), m === 12 ? 1 : m + 1, 1), -1);
      const [ey, em] = parseIso(end);
      const due = after(ymd(ey + (em === 12 ? 1 : 0), em === 12 ? 1 : em + 1, 10));
      periods.push([`${y}년 ${m}월분`, start, end, due]);
      [y, m] = nextMonth(y, m);
    }
  }
  const byMonth = new Map<string, [YM, number]>();
  for (const ln of mine) {
    if (ln.credit !== null) {
      const k: YM = [yOf(ln.date!), mOf(ln.date!)];
      const prev = byMonth.get(ymKey(k));
      byMonth.set(ymKey(k), [k, (prev ? prev[1] : 0) + ln.credit]);
    }
  }
  const filled = sortedBy([...byMonth.values()].filter((x) => x[1]), (x) => [x[0][0], x[0][1]]);
  const lastFilled = filled.length ? filled[filled.length - 1]! : null;
  const recentAmt = lastFilled ? lastFilled[1] : null;
  const side = (ln: JLine) => (sq(ln.vendor).includes("세무서") ? "세무서" : "지자체");
  const rows: TaxRow[] = [];
  for (const [label, start, end, due] of periods) {
    if (!recent(due, asof)) continue;
    let lines = mine.filter((ln) => start <= ln.date! && ln.date! <= end);
    const paidSides = new Set(mine.filter((ln) => end < ln.date! && ln.date! <= asof && (ln.debit || 0) > 0).map(side));
    let part = "";
    if (paidSides.size) {
      let owed = new Set(lines.filter((ln) => (ln.credit || 0) > 0).map(side));
      if (!owed.size) owed = new Set(["세무서", "지자체"]);
      if ([...owed].every((x) => paidSides.has(x))) continue;
      lines = lines.filter((ln) => !paidSides.has(side(ln)));
      part = ` · ${[...paidSides].filter((x) => owed.has(x)).sort(cmpStr).join("·")}분은 냄, 남은 ${[...owed].filter((x) => !paidSides.has(x)).sort(cmpStr).join("·")}분만`;
    }
    const vals = lines.filter((ln) => ln.credit !== null || ln.debit === null).map((ln) => ln.credit);
    const unknown = vals.filter((v) => v === null).length;
    let got = sum(vals.filter((v): v is number => v !== null));
    let basis = `예수금 중 ${vendors.slice(0, 2).join("·")} 거래처 대변 합계, ${mode === "반기" ? "반기" : "매월 "}납부`;
    basis += part;
    const ahead = !part ? months(start, end).filter((k) => lastFilled && ymNum(k) > ymNum(lastFilled[0])) : [];
    if (!got && !unknown && !ahead.length) continue;
    const fromScreen = ahead.filter((k) => (screen?.get(ymKey(k)) ?? 0));
    const guess = ahead.filter((k) => !fromScreen.includes(k));
    if (fromScreen.length) {
      const sv = sum(fromScreen.map((k) => screen!.get(ymKey(k))!));
      got += sv;
      basis += `${vals.length ? ", " : " — "} 급여 전표 전 ${fromScreen.map((k) => `${k[1]}월`).join("·")}은 위하고 급여·사업·기타소득 화면 값 ${fmt(sv)}원`;
    }
    if (guess.length && recentAmt) {
      got += recentAmt * guess.length;
      basis += `${vals.length || fromScreen.length ? ", " : " — "} 급여 전표 전 ${guess.length}달은 ${lastFilled![0][0]}-${p2(lastFilled![0][1])} 금액 ${fmt(recentAmt)}원으로 봄`;
    } else if (last < end) basis += `, ${last}까지 쌓인 금액`;
    rows.push(row("원천세", label, due, unknown ? null : got, "예상", basis, vcodes));
  }
  return stamp(rows, journal);
}

const ACCRUED = ["262", "253"];
export const INSURERS = ["국민연금", "건강보험", "근로복지", "고용보험"];

/** social */
export function social(journal: JLine[], asof: IsoDate, codes0: string[] = ["25400"], vendors: string[] = INSURERS): TaxRow[] {
  const cs = new Set(codes0.map(sq));
  const ins = (ln: JLine) => vendors.some((v) => sq(ln.vendor).includes(v));
  const who = (ln: JLine) => vendors.find((v) => sq(ln.vendor).includes(v)) ?? "";
  const mine = journal.filter((ln) => ln.date !== null && ins(ln));
  const withheld = mine.filter((ln) => cs.has(sq(ln.account_code)));
  if (!withheld.length) return [];
  const slips = slipsOf(journal, true);
  const pays: [IsoDate, number, number, Set<string>][] = [];
  const accrued = new Map<string, { key: YM; company: Map<string, number>; moved: Map<string, number>; day: IsoDate }>();
  for (const s of sortedBy([...slips.values()], (x) => [x.date!, x.no])) {
    const day = s.date!, lines = s.lines;
    const own = lines.filter(ins);
    const dr = (pred: (c: string) => boolean) => sum(own.filter((x) => pred(sq(x.account_code))).map((x) => x.debit || 0));
    const emp = dr((c) => cs.has(c));
    const cost = dr((c) => c.startsWith("8"));
    const accrDr = dr((c) => startsAny(c, ACCRUED));
    const accrCr = sum(own.filter((x) => startsAny(sq(x.account_code), ACCRUED)).map((x) => x.credit || 0));
    const bank = fromBank(lines);
    if (!bank && (cost || accrCr)) {
      const k: YM = [yOf(day), mOf(day)];
      if (!accrued.has(ymKey(k))) accrued.set(ymKey(k), { key: k, company: new Map(), moved: new Map(), day });
      const a = accrued.get(ymKey(k))!;
      if (day > a.day) a.day = day;
      for (const x of own) {
        const c = sq(x.account_code), w = who(x), v = x.debit || 0;
        if (v && c.startsWith("8")) a.company.set(w, (a.company.get(w) ?? 0) + v);
        else if (v && cs.has(c)) a.moved.set(w, (a.moved.get(w) ?? 0) + v);
      }
      continue;
    }
    if (emp || (bank && (cost || accrDr))) {
      pays.push([day, emp, cost + accrDr, new Set(own.filter((x) => (x.debit || 0) && (cs.has(sq(x.account_code))
        || startsAny(sq(x.account_code), [...ACCRUED, "8"]))).map(who))]);
    }
  }
  const byDay = new Map<IsoDate, [number, number]>();
  for (const p of pays) {
    if (!byDay.has(p[0])) byDay.set(p[0], [0, 0]);
    const t = byDay.get(p[0])!;
    t[0] += p[1]; t[1] += p[2];
  }
  const mapSum = (m: Map<string, number>) => sum([...m.values()]);
  const ratioSrc: [IsoDate, number, number, string][] = [...byDay].filter(([, [e]]) => e).map(([d, [e, c]]) => [d, e, c, `${d} 납부 비율`]);
  for (const a of accrued.values()) {
    if (mapSum(a.moved)) ratioSrc.push([a.day, mapSum(a.moved), mapSum(a.company), `${a.key[0]}-${p2(a.key[1])} 월말 전표 비율`]);
  }
  const rows: TaxRow[] = [];
  const vcodes = codes(mine);
  let recentV: [YM, number | null] | null = null;
  const ymsW = sortedBy([...new Map(withheld.map((ln) => [ymKey([yOf(ln.date!), mOf(ln.date!)]), [yOf(ln.date!), mOf(ln.date!)] as YM])).values()], (k) => [k[0], k[1]]);
  for (const [y, m] of ymsW) {
    const start = ymd(y, m, 1);
    const end = addDays(ymd(y + (m === 12 ? 1 : 0), m === 12 ? 1 : m + 1, 1), -1);
    const [ey, em] = parseIso(end);
    const due = after(ymd(ey + (em === 12 ? 1 : 0), em === 12 ? 1 : em + 1, 10));
    const monthLines = withheld.filter((ln) => start <= ln.date! && ln.date! <= end && (ln.credit !== null || ln.debit === null));
    const vals = monthLines.map((ln) => ln.credit);
    if (!vals.length) continue;
    const beforeSrc = ratioSrc.filter((s) => s[0] <= asof);
    let last: (typeof ratioSrc)[number] | null = null;
    for (const s of beforeSrc) if (last === null || s[0] > last[0]) last = s;
    const paid = pays.filter((p) => end < p[0] && p[0] <= asof);
    const paidWho = new Set<string>();
    for (const p of paid) for (const w of p[3]) paidWho.add(w);
    const owedWho = new Set(monthLines.filter((ln) => ln.credit).map(who));
    let part: string[] | (number | null)[] | null = null;
    const a = accrued.get(ymKey([y, m]));
    let owed: Map<string, number> | null = null;
    if (a) {
      const whBy = new Map<string, number>();
      for (const ln of monthLines) if (ln.credit) whBy.set(who(ln), (whBy.get(who(ln)) ?? 0) + ln.credit);
      owed = new Map();
      for (const w of new Set([...whBy.keys(), ...a.company.keys(), ...a.moved.keys()])) {
        owed.set(w, ((a.moved.get(w) || whBy.get(w)) ?? 0) + (a.company.get(w) ?? 0));
      }
      if (paidWho.size && ![...owed.keys()].every((w) => paidWho.has(w)) && sum(paid.map((p) => p[1] + p[2])) < mapSum(owed)) {
        part = [...owed.keys()].filter((w) => !paidWho.has(w)).sort(cmpStr);
      }
    } else {
      const paidEmp = sum(paid.map((p) => p[1]));
      const monthEmp = sum(monthLines.map((ln) => ln.credit || 0));
      if (paidWho.size && owedWho.size && ![...owedWho].every((w) => paidWho.has(w)) && paidEmp < monthEmp) {
        part = monthLines.filter((ln) => !paidWho.has(who(ln))).map((ln) => ln.credit);
      }
    }
    let state = "예상";
    const unknown = vals.some((v) => v === null);
    const emp = sum(vals.filter((v): v is number => v !== null));
    let note: string, amount: number | null, company: number;
    if (owed !== null) {
      company = mapSum(a!.company);
      if (mapSum(a!.moved)) note = `월말 전표로 잡은 낼 돈: 직원분 ${fmt(mapSum(owed) - company)}원(예수금에서 옮김) + 회사분 ${fmt(company)}원`;
      else note = `회사분 ${fmt(company)}원 (월말 전표)`;
      state = "확정(전표)";
      amount = unknown ? null : mapSum(owed);
    } else {
      let ratio: number;
      if (last && last[1]) {
        ratio = last[2] / last[1];
        note = `회사분 = 직원분 × ${pyFixed(ratio, 2)} (${last[3]})`;
      } else { ratio = 1.0; note = "회사분은 직원분과 같게 봄 (지난 납부 없음)"; }
      company = Math.trunc(pyRound(emp * ratio));
      amount = unknown ? null : emp + company;
    }
    if (emp) recentV = [[y, m], amount];
    if (!recent(due, asof)) continue;
    if (part !== null && owed !== null) {
      const ws = part as string[];
      const amt = unknown ? null : sum(ws.map((w) => owed!.get(w)!));
      rows.push(row("4대보험", `${y}년 ${m}월분`, due, amt, state,
        `${[...paidWho].filter((w) => owed!.has(w)).sort(cmpStr).join("·")} 납부 확인 — 남은 ${ws.join("·")} 낼 돈 (${note})`, vcodes));
      continue;
    }
    if (part !== null) {
      const vs = part as (number | null)[];
      const left = sum(vs.filter((v): v is number => v !== null));
      const share = emp ? left / emp : 0;
      const amt = vs.some((v) => v === null) || amount === null ? null : left + Math.trunc(pyRound(company * share));
      rows.push(row("4대보험", `${y}년 ${m}월분`, due, amt, state,
        `${[...paidWho].filter((w) => owedWho.has(w)).sort(cmpStr).join("·")} 납부 확인 — 남은 ${[...owedWho].filter((w) => !paidWho.has(w)).sort(cmpStr).join("·")} 직원분 ${fmt(left)}원 + 같은 비율의 회사분 (${note})`, vcodes));
      continue;
    }
    if (paid.length) continue;
    const basis = owed !== null && mapSum(a!.moved) ? note : `예수금 중 공단 거래처 대변(직원분) ${fmt(emp)}원 + ${note}`;
    rows.push(row("4대보험", `${y}년 ${m}월분`, due, amount, state, basis, vcodes));
  }
  const credited = withheld.filter((ln) => ln.credit).map((ln) => ln.date!);
  const first = credited.length ? maxStr(credited) : maxStr(withheld.map((ln) => ln.date!));
  let [y, m] = nextMonth(yOf(first), mOf(first));
  const until = nextMonth(yOf(asof), mOf(asof), AHEAD_MONTHS);
  while (recentV && recentV[1] !== null && ymNum([y, m]) < ymNum(until)) {
    const [ny, nm] = nextMonth(y, m);
    const due = after(ymd(ny, nm, 10));
    const end = addDays(ymd(ny, nm, 1), -1);
    if (recent(due, asof) && !pays.some((p) => end < p[0] && p[0] <= asof)) {
      rows.push(row("4대보험", `${y}년 ${m}월분`, due, recentV[1], "예상", `급여 전표 전 → ${recentV[0][0]}-${p2(recentV[0][1])} 납부액(직원분+회사분)으로 봄`, vcodes));
    }
    [y, m] = nextMonth(y, m);
  }
  return stamp(rows, journal);
}

/** salary */
export function salary(journal: JLine[], asof: IsoDate, salaryCodes0: string[] = ["80200"], accruedCodes0: string[] = ["26200"], payDay = 5,
  monthsAhead = AHEAD_MONTHS): TaxRow[] {
  const salaryCodes = new Set(salaryCodes0.map(sq)), accruedCodes = new Set(accruedCodes0.map(sq));
  const slips = slipsOf(journal, true);
  const accr = new Map<string, [YM, IsoDate, number]>();
  const paid: [IsoDate, number, string][] = [];
  const payLines: JLine[] = [];
  for (const s of slips.values()) {
    const day = s.date!, lines = s.lines;
    const cset = new Set(lines.map((x) => sq(x.account_code)));
    if ([...cset].some((c) => salaryCodes.has(c)) && lines.some((x) => salaryCodes.has(sq(x.account_code)) && (x.debit || 0))) {
      const net = sum(lines.filter((x) => accruedCodes.has(sq(x.account_code))).map((x) => x.credit || 0));
      if (net) {
        const k: YM = [yOf(day), mOf(day)];
        const prev = accr.get(ymKey(k));
        accr.set(ymKey(k), [k, prev ? (day > prev[1] ? day : prev[1]) : day, (prev ? prev[2] : 0) + net]);
        payLines.push(...lines.filter((x) => accruedCodes.has(sq(x.account_code)) && (x.credit || 0)));
      }
    } else if (fromBank(lines)) {
      for (const x of lines) if (accruedCodes.has(sq(x.account_code)) && (x.debit || 0)) paid.push([day, x.debit as number, code(x.vendor_code)]);
    }
  }
  if (!accr.size) return [];
  const scodes = codes(payLines);
  const gone = (afterDay: IsoDate, amt: number | null) => {
    const lines = paid.filter(([d]) => afterDay < d && d <= asof);
    const mine = lines.filter(([, , c]) => scodes.length && scodes.includes(c)).map(([, a]) => a);
    if (mine.length && (amt === null || sum(mine) >= amt)) return true;
    return amt !== null && lines.some(([, a, c]) => a === amt && !(scodes.length && c));
  };
  const rows: TaxRow[] = [];
  const maxK = sortedBy([...accr.values()], (v) => [v[0][0], v[0][1]]).pop()!;
  const lastAmt = maxK[2];
  const until = nextMonth(yOf(asof), mOf(asof), monthsAhead);
  const ms = new Map<string, YM>([...accr.values()].map((v) => [ymKey(v[0]), v[0]]));
  let ym = nextMonth(...maxK[0]);
  while (ymNum(ym) <= ymNum(until)) {
    ms.set(ymKey(ym), ym);
    ym = nextMonth(...ym);
  }
  for (const [y, m] of sortedBy([...ms.values()], (k) => [k[0], k[1]])) {
    const [ny, nm] = nextMonth(y, m);
    const due = before(dayIn(ny, nm, payDay));
    if (!recent(due, asof)) continue;
    const end = addDays(ymd(ny, nm, 1), -1);
    const got = accr.get(ymKey([y, m]));
    if (got) {
      const [, day, amt] = got;
      if (gone(day, amt)) continue;
      rows.push(row("급여", `${y}년 ${m}월분`, due, amt, "확정(전표)", "월말 급여 전표 미지급비용(실지급액, 세후)", scodes));
    } else if (ymNum([y, m]) > ymNum(maxK[0])) {
      if (due <= asof && gone(end, null)) continue;
      rows.push(row("급여", `${y}년 ${m}월분`, due, lastAmt, "예상", `직전 급여 전표(${maxK[0][0]}-${p2(maxK[0][1])}) 실지급액으로 봄`, scodes));
    }
  }
  return stamp(rows, journal);
}

export const CARD_PREFIX = /^(신한|롯데|비씨|BC|삼성|현대|국민|KB|하나|우리|농협|NH|씨티)[_\s-]/u;
export const CARD_FILE = "카드결제일.csv";
export const CARD_COLUMNS = ["카드사", "납부일", "기산일"];
const DEFAULT_CARDS: [string, number, number][] = [["신한", 15, 1], ["롯데", 14, 1], ["비씨", 25, 1]];

function cardName(text: unknown): string {
  const t = pyStrip(text === null || text === undefined ? "" : String(text)).replaceAll("카드", "");
  return ({ BC: "비씨", KB: "국민", NH: "농협" } as Record<string, string>)[t.toUpperCase()] ?? t;
}

export type CardDays = Map<string, [number, number]>;

/** read_card_days */
export function readCardDays(files: ConvFiles, inputDir: string): [CardDays, string[]] {
  const path = join(inputDir, CARD_FILE);
  if (!exists(files, path)) {
    return [new Map(DEFAULT_CARDS.map(([c, p, s]) => [c, [p, s]])),
      [`${CARD_FILE} 없음 → 기본값 ${DEFAULT_CARDS.map(([c, p]) => `${c} ${p}일`).join(" · ")} (기산일 1일)`]];
  }
  const info: { missing?: string[] } = {};
  const [rows, ok] = readCsvFile(files, path, CARD_COLUMNS, new Issues(), info);
  if (!ok || (info.missing && info.missing.length)) return [new Map(), [`${CARD_FILE} 를 읽지 못함 (머리글: 카드사,납부일,기산일) → 카드대금은 날짜 없이 알리기만 함`]];
  const out: CardDays = new Map();
  const notes: string[] = [];
  for (const r of rows) {
    const co = cardName(r["카드사"]);
    const pay = pyStrip(String(r["납부일"] || "")).replace(/일+$/, "");
    const start = pyStrip(String(r["기산일"] || "1")).replace(/일+$/, "") || "1";
    if (!co) continue;
    if (!(pyIsDigit(pay) && pyIsDigit(start) && 1 <= Number(pay) && Number(pay) <= 31 && 1 <= Number(start) && Number(start) <= 31)) {
      notes.push(`${CARD_FILE} ${co} 줄 날짜를 읽지 못함 (납부일·기산일은 1~31)`);
      continue;
    }
    out.set(co, [Number(pay), Number(start)]);
  }
  return [out, notes];
}

export function cardDue(day: IsoDate, pay: number, start: number): IsoDate {
  const [y, m] = parseIso(day);
  let nxt = dayIn(y, m, start);
  if (nxt <= day) nxt = dayIn(...nextMonth(y, m), start);
  const end = addDays(nxt, -1);
  const [ey, em] = parseIso(end);
  let due = dayIn(ey, em, pay);
  if (due <= end) due = dayIn(...nextMonth(ey, em), pay);
  return after(due);
}

export const CARD_AVG_MONTHS = 3;
export const CARD_THIN_RATE = 0.5;
export const CARD_THIN_MARK = "카드 전표 입력 전:";
export const CARD_OPEN_MARK = "카드 이번 달 사용 추정:";
export const CARD_REAL_MARK = "위하고 카드 사용:";
export const CARD_MIN_AVG = 100000;

export type CardActual = Map<string, [IsoDate, number][]>;

function periodEnd(bill: IsoDate, start: number): IsoDate {
  const [y, m] = parseIso(bill);
  let b = dayIn(y, m, start);
  if (b > bill) b = dayIn(...nextMonth(y, m, -1), start);
  return addDays(b, -1);
}

function openBills(asof: IsoDate, pay: number, start: number): IsoDate[] {
  const cur = cardDue(asof, pay, start);
  const [y, m] = parseIso(asof);
  let begin = dayIn(y, m, start);
  if (begin > asof) begin = dayIn(...nextMonth(y, m, -1), start);
  const prev = cardDue(addDays(begin, -1), pay, start);
  return [...new Set([prev, cur])].sort(cmpStr).filter((k) => k >= asof);
}

function actualFor(actual: CardActual | null, upto: IsoDate | null, card: string, lines: JLine[], bill: IsoDate, pay: number, start: number): number | null {
  if (!actual || !actual.size || upto === null) return null;
  const cs = [...new Set(lines.map((ln) => pyStrip(String(ln.vendor_code || "")).replace(/^0+/, "")))].filter((c) => c !== "").sort(cmpStr);
  let items: [IsoDate, number][] | null = null;
  for (const c of cs) {
    items = actual.get("code:" + c) ?? null;
    if (items && items.length) break;
  }
  if (items === null) items = actual.get(card) ?? null;
  if (items === null) return null;
  if (periodEnd(bill, start) > upto) return null;
  const got = items.filter(([d]) => cardDue(d, pay, start) === bill).map(([, a]) => a);
  if (!got.length) return null;
  return sum(got);
}

/** cards */
export function cards(journal: JLine[], asof: IsoDate, cardDays: CardDays, accruedCodes0: string[] = ["26200"], actual: CardActual | null = null,
  actualUpto: IsoDate | null = null): TaxRow[] {
  const accruedCodes = new Set(accruedCodes0.map(sq));
  const bankSlips = new Set(journal.filter((ln) => ln.date !== null && startsAny(sq(ln.account_code), BANK_PREFIX)).map((ln) => ln.date + "\u0000" + ln.no));
  const use = new Map<string, [IsoDate, number][]>(), pay = new Map<string, number>();
  const useCard = new Map<string, Map<string, [IsoDate, number][]>>(), payCard = new Map<string, Map<string, [IsoDate, number][]>>();
  const coLines = new Map<string, JLine[]>(), useLines = new Map<string, JLine[]>();
  const push = <K, V>(m: Map<K, V[]>, k: K, v: V) => { if (!m.has(k)) m.set(k, []); m.get(k)!.push(v); };
  const push2 = (m: Map<string, Map<string, [IsoDate, number][]>>, a: string, b: string, v: [IsoDate, number]) => {
    if (!m.has(a)) m.set(a, new Map());
    push(m.get(a)!, b, v);
  };
  for (const ln of journal) {
    if (ln.date === null || !accruedCodes.has(sq(ln.account_code))) continue;
    const vendor = pyStrip(String(ln.vendor || ""));
    const m = CARD_PREFIX.exec(vendor);
    if (!m) continue;
    const co = cardName(m[1]);
    push(coLines, co, ln);
    push(useLines, vendor, ln);
    if (ln.credit) {
      push(use, co, [ln.date, ln.credit]);
      push2(useCard, co, vendor, [ln.date, ln.credit]);
    }
    if (ln.debit) {
      if (ln.no && !bankSlips.has(ln.date + "\u0000" + ln.no)) {
        push(use, co, [ln.date, -ln.debit]);
        push2(useCard, co, vendor, [ln.date, -ln.debit]);
      } else {
        pay.set(co, (pay.get(co) ?? 0) + ln.debit);
        push2(payCard, co, vendor, [ln.date, ln.debit]);
      }
    }
  }
  const rows: TaxRow[] = [];
  for (const co of [...use.keys()].sort(cmpStr)) {
    const days = cardDays.get(co);
    const vcodes = codes(coLines.get(co) ?? []);
    if (!days) {
      const bal = sum(use.get(co)!.map(([, a]) => a)) - (pay.get(co) ?? 0);
      if (bal > 0) rows.push(row("카드대금", `${co}카드 미결제 잔액`, null, bal, "납부일 확인 필요", `창의 '카드 납부일'에 ${co} 납부일·기산일을 넣으면 자금 일정에 들어감`, vcodes));
      continue;
    }
    const span = new Map<string, [IsoDate, IsoDate]>();
    for (const [card, items] of useCard.get(co) ?? []) {
      const gd = items.filter(([, a]) => a > 0).map(([d]) => d);
      if (gd.length) span.set(card, [minStr(gd), maxStr(gd)]);
    }
    const retired = new Set([...span].filter(([c, [, lastUse]]) => [...span].some(([c2, [first]]) => c2 !== c && first > lastUse)).map(([c]) => c));
    const [p, s] = days;
    const byBill = new Map<IsoDate, number>();
    for (const [d, a] of use.get(co)!) {
      const k = cardDue(d, p, s);
      byBill.set(k, (byBill.get(k) ?? 0) + a);
    }
    const pastKeys = [...byBill.keys()].sort(cmpStr).filter((k) => k < asof).slice(-CARD_AVG_MONTHS);
    const fill = new Map<IsoDate, [string, number, number, boolean][]>();
    if (pastKeys.length >= CARD_AVG_MONTHS) {
      const opens = openBills(asof, p, s);
      for (const card of [...(useCard.get(co) ?? new Map()).keys()].sort(cmpStr)) {
        if (retired.has(card)) continue;
        const cb = new Map<IsoDate, number>();
        for (const [d, a] of useCard.get(co)!.get(card)!) {
          const k = cardDue(d, p, s);
          cb.set(k, (cb.get(k) ?? 0) + a);
        }
        const dues: number[] = [];
        for (const k of pastKeys) {
          const end = periodEnd(k, s);
          const used = sum([...cb].filter(([kk]) => kk <= k).map(([, a]) => a));
          const paidV = sum((payCard.get(co)?.get(card) ?? []).filter(([d]) => d <= end).map(([, a]) => a));
          dues.push(Math.max(0, used - paidV));
        }
        const avg = Math.floor(sum(dues) / CARD_AVG_MONTHS);
        for (const k of opens) {
          const got = Math.max(0, cb.get(k) ?? 0);
          if (periodEnd(k, s) < asof && useCard.get(co)!.get(card)!.some(([d, a]) => cardDue(d, p, s) === k && a > 0)) continue;
          const real = actualFor(actual, actualUpto, card, useLines.get(card) ?? [], k, p, s);
          if (real !== null) {
            if (real > got) push(fill, k, [card, got, real, true]);
            continue;
          }
          if (avg < CARD_MIN_AVG) continue;
          if (got < avg * CARD_THIN_RATE) push(fill, k, [card, got, avg, false]);
        }
      }
    }
    let left = pay.get(co) ?? 0;
    const byDue = new Map<IsoDate, number>();
    for (const k of [...byBill.keys()].sort(cmpStr)) {
      const take = Math.min(byBill.get(k)!, left);
      left -= take;
      if (byBill.get(k)! - take <= 0) continue;
      byDue.set(k, (byDue.get(k) ?? 0) + byBill.get(k)! - take);
    }
    for (const due of [...new Set([...byDue.keys(), ...fill.keys()])].sort(cmpStr)) {
      const [, dm, dd] = parseIso(due);
      if (byDue.get(due)) {
        rows.push(row("카드대금", `${co}카드 ${dm}월 ${dd}일 결제`, due, byDue.get(due)!, "확정(전표)", `미지급비용 ${co}카드 사용 − 결제 (납부일 ${p}일, 기산일 ${s}일)`, vcodes));
      }
      const f = fill.get(due);
      if (f && f.length) {
        const extra = sum(f.map(([, g, a]) => a - g));
        const cardsTxt = f.map(([c, g, a, r]) => `${c}(입력 ${fmt(g)} / ${r ? "위하고 사용" : "평균"} ${fmt(a)})`).join(", ");
        if (f.every(([, , , r]) => r)) {
          rows.push(row("카드대금", `${co}카드 ${dm}월 ${dd}일 결제 (위하고 카드 사용 기준)`, due, extra, "예상",
            `${CARD_REAL_MARK} ${co}카드 ${cardsTxt} — 장부 전표 전이라 위하고 카드 사용 화면(${actualUpto ?? "-"}까지)의 실제 사용으로 잡음 (전표를 넣으면 장부 금액으로 바뀜)`, vcodes));
          continue;
        }
        if (periodEnd(due, s) >= asof) {
          rows.push(row("카드대금", `${co}카드 ${dm}월 ${dd}일 결제 (이번 달 사용 추정)`, due, extra, "예상",
            `${CARD_OPEN_MARK} ${co}카드 ${cardsTxt} — 이용기간이 아직 끝나지 않아 전표는 다음 달 초에 들어옴. 그 카드 최근 ${CARD_AVG_MONTHS}달 평균과의 차이 ${fmt(extra)}원을 미리 잡음`, vcodes));
          continue;
        }
        rows.push(row("카드대금", `${co}카드 ${dm}월 ${dd}일 결제 (전표 입력 전 추정)`, due, extra, "예상",
          `${CARD_THIN_MARK} ${co}카드 ${cardsTxt} 사용 전표가 하나도 없음 → 그 카드 최근 ${CARD_AVG_MONTHS}달 평균과의 차이 ${fmt(extra)}원을 더 잡음 (전표를 넣으면 실제 금액으로 바뀜)`, vcodes));
      }
    }
  }
  return stamp(rows, journal);
}

const OTHER_SAVINGS = ["공제", "부금", "적금"];
export const DEPOSIT_IN = "정기예금 만기";
export const DEPOSIT_OUT = "정기예금 가입";

function addMonthsDay(d: IsoDate, k: number): IsoDate {
  const [y0, m0, dd] = parseIso(d);
  const [y, m] = nextMonth(y0, m0, k);
  return dayIn(y, m, dd);
}

/** deposits */
export function deposits(journal: JLine[], asof: IsoDate, codes0: string[] = ["10500"]): TaxRow[] {
  const cs = new Set(codes0.map(sq));
  const slips = slipsOf(journal, true);
  const mine = (x: JLine) => cs.has(sq(x.account_code)) && !OTHER_SAVINGS.some((w) => (sq(x.memo) + sq(x.vendor)).includes(w));
  const matured = (x: JLine) => {
    const lines = slips.get(x.date + "\u0000" + x.no)?.lines ?? [];
    return lines.some((y) => startsAny(sq(y.account_code), BANK_PREFIX) && (y.debit || 0)) || String(x.memo || "").includes("만기");
  };
  const put = sortedBy(journal.filter((x) => x.date !== null && mine(x) && (x.debit || 0) > 0).map((x) => [x.date!, x.debit as number] as [IsoDate, number]), (t) => [t[0], t[1]]);
  const took = sortedBy(journal.filter((x) => x.date !== null && mine(x) && (x.credit || 0) > 0).map((x) => [x.date!, x.credit as number, matured(x)] as [IsoDate, number, boolean]),
    (t) => [t[0], t[1], t[2]]);
  const open: [IsoDate, number][] = [], terms: number[] = [];
  const used = new Set<number>();
  for (const [d, a] of put) {
    const hit = took.findIndex(([d2, a2], i) => !used.has(i) && d2 >= d && a2 === a);
    if (hit < 0) { open.push([d, a]); continue; }
    used.add(hit);
    const [d2, , mat] = took[hit]!;
    if (mat) terms.push(Math.max(1, Math.trunc(pyRound(daysBetween(d, d2) / 30.4))));
  }
  let left = sum(took.filter((_, i) => !used.has(i)).map(([, a]) => a));
  const still: [IsoDate, number][] = [];
  for (const [d, a] of open) {
    const take = Math.min(a, left);
    left -= take;
    if (a - take > 0) still.push([d, a - take]);
  }
  let term = 1;
  if (terms.length) {
    const cnt = (k: number) => terms.filter((t) => t === k).length;
    term = sortedBy([...new Set(terms)], (k) => [cnt(k), -k], true)[0]!;
  }
  const why = terms.length ? `지난 예금 ${terms.length}건의 가입→만기 간격` : "지난 만기 기록 없음 → 1개월로 봄";
  const vcodes = codes(journal.filter((x) => x.date !== null && mine(x)));
  const rows: TaxRow[] = [];
  for (const [d, a] of still) {
    if (d > asof) rows.push(row(DEPOSIT_OUT, `${d} 가입`, d, a, "확정(전표)", "정기예금 가입 전표 (통장에서 나감)", vcodes));
    let due = after(addMonthsDay(d, term));
    let note = `가입 ${d} + ${term}개월 (${why})`;
    if (due < asof) { due = after(asof); note += " — 만기가 지났는데 해지 전표 없음"; }
    rows.push(row(DEPOSIT_IN, `${d} 가입분`, due, a, "예상", "원금만 (이자 제외). " + note, vcodes));
  }
  return stamp(rows, journal);
}

export const FIXED_KIND = "고정 지출";
const FIXED_MONTHS = 3;
const FIXED_TOL = 0.15;
const SETTLE_PREFIX = ["251", "252", "253", "254", "255", "261", "262"];

/** fixed_costs */
export function fixedCosts(journal: JLine[], asof: IsoDate, skipCodes: string[] = [], monthsAhead = AHEAD_MONTHS): TaxRow[] {
  const skip = new Set(skipCodes.map(code).filter((c) => c));
  const slips = slipsOf(journal, true);
  const per = new Map<string, Map<string, [YM, [IsoDate, number][]]>>();
  const names = new Map<string, string>();
  for (const s of slips.values()) {
    const day = s.date!, lines = s.lines;
    if (day > asof || !fromBank(lines)) continue;
    const by = new Map<string, number>();
    for (const x of lines) {
      const acct = sq(x.account_code);
      if (startsAny(acct, BANK_PREFIX) || startsAny(acct, SETTLE_PREFIX) || !(x.debit || 0)) continue;
      if (acct === "10500" && !OTHER_SAVINGS.some((w) => (sq(x.memo) + sq(x.vendor)).includes(w))) continue;
      const c = code(x.vendor_code);
      const name = String(x.vendor || "");
      if (!c || skip.has(c) || CARD_PREFIX.test(pyStrip(name)) || [...INSURERS, "세무서", "구청", "시청", "군청"].some((w) => sq(name).includes(w))) continue;
      by.set(c, (by.get(c) ?? 0) + (x.debit as number));
      names.set(c, pyStrip(name) || (names.get(c) ?? ""));
    }
    for (const [c, a] of by) {
      if (!per.has(c)) per.set(c, new Map());
      const M = per.get(c)!;
      const k: YM = [yOf(day), mOf(day)];
      if (!M.has(ymKey(k))) M.set(ymKey(k), [k, []]);
      M.get(ymKey(k))![1].push([day, a]);
    }
  }
  const rows: TaxRow[] = [];
  const prevM = nextMonth(yOf(asof), mOf(asof), -1);
  const until = nextMonth(yOf(asof), mOf(asof), monthsAhead);
  for (const c of [...per.keys()].sort(cmpStr)) {
    const M = per.get(c)!;
    const last = sortedBy([...M.values()].map((v) => v[0]), (k) => [k[0], k[1]]).pop()!;
    if (ymNum(last) < ymNum(prevM)) continue;
    const run: YM[] = [last];
    while (run.length < FIXED_MONTHS && M.has(ymKey(nextMonth(...run[run.length - 1]!, -1)))) run.push(nextMonth(...run[run.length - 1]!, -1));
    if (run.length < FIXED_MONTHS) continue;
    const amts = run.map((k) => sum(M.get(ymKey(k))![1].map(([, a]) => a)));
    const mid = [...amts].sort((a, b) => a - b)[Math.floor(amts.length / 2)]!;
    if (mid <= 0 || amts.some((a) => Math.abs(a - mid) > FIXED_TOL * mid)) continue;
    const dayOf = Math.min(...run.flatMap((k) => M.get(ymKey(k))![1].map(([d]) => dOf(d))));
    const amount = amts[0]!;
    const lo = Math.min(...amts), hi = Math.max(...amts);
    const spanTxt = lo === hi ? fmt(lo) : `${fmt(lo)}~${fmt(hi)}`;
    const r0 = run[run.length - 1]!;
    const basis = `장부 최근 ${FIXED_MONTHS}달(${r0[0]}-${p2(r0[1])}~${last[0]}-${p2(last[1])}) 매달 ${dayOf}일쯤 통장에서 나감 (${spanTxt}원) — 자금계획서에 없으면 꼭 나갈 정기 지출로 봄 (결정 g). 금액은 마지막 달 금액`;
    let ym = nextMonth(...last);
    while (ymNum(ym) <= ymNum(until)) {
      const due = after(dayIn(ym[0], ym[1], dayOf));
      if (recent(due, asof)) rows.push(row(FIXED_KIND, `${names.get(c) || `거래처 ${c}`} ${ym[0]}년 ${ym[1]}월분`, due, amount, "예상", basis, [c]));
      ym = nextMonth(...ym);
    }
  }
  return stamp(rows, journal);
}
