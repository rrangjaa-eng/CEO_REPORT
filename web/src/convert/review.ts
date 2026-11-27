// review_checks.py 일부 (duplicate_lines · archive_paid_schedule) 와 convert.py 의 schedule_overlaps · overlap_lines.
// 파일을 직접 고치지 않고, 새로 쓸 글을 돌려준다 (호출한 쪽이 결과 파일 묶음에 넣는다).
import { SCHEMA, PRIOR_TAG } from "../model/data";
import { decodeText, parseCsv, writeCsv, type CsvInfo } from "../model/csv";
import { addDays, daysBetween, type IsoDate } from "../model/dates";
import { cmpKey, cmpStr, pyRemoveSpace, pyStrip, type SortKey } from "../model/py";
import { Issues, num, parseDate, rget, rs, won, type Row } from "../model/util";
import { normCode, normVendor } from "../model/vendor";
import { exists, join, readCsvFile, type ConvFiles } from "./files";
import { PRIOR_LAST_YEAR } from "./linking";
import type { TRow, Table } from "./table";
import type { JLine } from "./wehago";

export const SCHEDULE = "자금일정.csv";
export const ARCHIVE = "자금일정_지난기록.csv";
export const SCHED_OPTIONAL = ["거래처코드"];
const MATCH_DAYS = 3;
const DUP_SORTS = ["매입전표", "매출전표"];
const DUP_MIN = 100000;
const CONTROL: Record<string, [string, "debit" | "credit"]> = { 매입전표: ["25300", "debit"], 매출전표: ["10800", "credit"] };
const CANCEL_DAYS = 31;
const EARLY_DAYS: Record<string, number> = { 지급: 14, 입금: 45 };
const USED_RE = /분개장 (\d{4}-\d{2}-\d{2}) 전표 (\S+) 보통예금/;

const sq = (t: unknown) => pyRemoveSpace(String(t ?? ""));
const vnOf = (ln: JLine) => ln.vendor_norm || normVendor(ln.vendor);
const sortOf = (ln: JLine) => pyStrip(ln.sort || "");
const slipKey = (day: IsoDate, no: string) => day + "\u0000" + no;

type Dup = [IsoDate, string[], number];

/** duplicate_slips -> [(날짜, [전표번호…], 전표 차변 합)] 금액 큰 순. */
export function duplicateSlips(journal: JLine[]): Dup[] {
  const slips = new Map<string, [IsoDate, string, JLine[]]>();
  for (const ln of journal) {
    if (ln.date === null || Number(ln.date.slice(0, 4)) <= PRIOR_LAST_YEAR) continue;
    const k = slipKey(ln.date, String(ln.no || ""));
    const s = slips.get(k);
    if (s) s[2].push(ln);
    else slips.set(k, [ln.date, String(ln.no || ""), [ln]]);
  }
  const sig = new Map<string, [IsoDate, [string, number][]]>();
  for (const [day, no, lines] of slips.values()) {
    if (!lines.some((ln) => DUP_SORTS.includes(sortOf(ln)))) continue;
    if (lines.some((ln) => ln.debit === null && ln.credit === null)) continue;
    const total = lines.reduce((a, ln) => a + (ln.debit || 0), 0);
    if (total < DUP_MIN) continue;
    const parts: SortKey[] = lines.map((ln) => [sq(ln.account_code), vnOf(ln), ln.debit || 0, ln.credit || 0]);
    parts.sort(cmpKey);
    const key = JSON.stringify([day, parts]);
    const s = sig.get(key);
    if (s) s[1].push([no, total]);
    else sig.set(key, [day, [[no, total]]]);
  }
  const out: Dup[] = [];
  for (const [day, v] of sig.values()) {
    if (v.length > 1) out.push([day, v.map((x) => x[0]).sort(cmpStr), (v[0] as [string, number])[1]]);
  }
  out.sort((a, b) => cmpKey([-a[2], a[0]], [-b[2], b[0]]));
  return out;
}

export type DupClass = [IsoDate, string[], number, string, boolean];

/** classify_duplicates */
export function classifyDuplicates(journal: JLine[]): DupClass[] {
  const slips = new Map<string, JLine[]>();
  for (const ln of journal) {
    if (ln.date === null) continue;
    const k = slipKey(ln.date, String(ln.no || ""));
    const s = slips.get(k);
    if (s) s.push(ln);
    else slips.set(k, [ln]);
  }
  const distinct = (nos: string[], day: IsoDate, f: (ln: JLine) => string) =>
    new Set(nos.map((n) => JSON.stringify([...new Set((slips.get(slipKey(day, n)) ?? []).map(f))].sort(cmpStr))));
  const out: DupClass[] = [];
  for (const [day, nos, total] of duplicateSlips(journal)) {
    const lines = slips.get(slipKey(day, nos[0] as string)) ?? [];
    const sort = lines.map(sortOf).find((s) => s in CONTROL) ?? "";
    const memos = distinct(nos, day, (ln) => sq(ln.memo));
    const projs = distinct(nos, day, (ln) => sq(ln.project_name));
    let why = "", ok = false;
    const hasProj = projs.size > 0 && [...projs].every((p) => (JSON.parse(p) as string[]).some((x) => x));
    if (projs.size > 1 && hasProj) {
      why = "관리항목 프로젝트가 전표마다 다름 → 다른 거래로 봄"; ok = true;
    } else if (!hasProj && memos.size > 1) {
      why = "프로젝트 없음 · 적요가 전표마다 다름 → 다른 거래로 봄 (적요로 판단)"; ok = true;
    } else if (sort) {
      const [code, side] = CONTROL[sort] as [string, "debit" | "credit"];
      const other = side === "debit" ? "credit" : "debit";
      const party = lines.filter((ln) => sq(ln.account_code) === code);
      const amt = party.length ? ((party[0] as JLine)[other] || 0) : 0;
      const vn = party.length ? vnOf(party[0] as JLine) : "";
      const sameV = journal.filter((ln) => ln.date !== null && sq(ln.account_code) === code && vnOf(ln) === vn);
      const cancel = sameV.filter((ln) => (ln[other] || 0) === -amt && amt && Math.abs(daysBetween(day, ln.date as IsoDate)) <= CANCEL_DAYS);
      const settled = sameV.filter((ln) => (ln[side] || 0) === amt && amt && (ln.date as IsoDate) >= day);
      const word = sort === "매입전표" ? "지급" : "입금";
      if (cancel.length && cancel.length >= nos.length - 1) {
        why = `취소(−) 전표 ${cancel.map((c) => String(c.no || "")).sort(cmpStr).join(", ")} 있음 → 취소 후 다시 발행으로 봄`; ok = true;
      } else if (settled.length >= nos.length) {
        why = `같은 금액 ${word} ${settled.length}번 → 각각 실제로 오간 돈으로 봄`; ok = true;
      } else {
        why = `${hasProj ? "프로젝트" : "적요"} 같음 · 같은 금액 ${word} ${settled.length}번 (전표 ${nos.length}건) → 이중 입력 가능성 높음`;
      }
    } else {
      why = (hasProj ? "프로젝트 같음" : "적요 같음") + " → 이중 입력 가능성";
    }
    out.push([day, nos, total, why, ok]);
  }
  return out;
}

/** duplicate_lines */
export function duplicateLines(journal: JLine[], limit = 20): string[] {
  const cls = classifyDuplicates(journal);
  const sus = cls.filter((c) => !c[4]);
  const out = [`중복 입력 의심 전표 ${sus.length}묶음 (같은 날짜·계정·거래처·금액, 전표번호만 다름 · 장부로 따져 정상으로 본 ${cls.length - sus.length}묶음은 뺌 — 남은 것은 확인할 것 화면)`];
  for (const [day, nos, total, why] of sus.slice(0, limit)) out.push(`  중복 의심 ${day} 전표 ${nos.join(", ")} · 전표 금액 ${won(total)} · ${why}`);
  if (sus.length > limit) out.push(`  … 그 밖 ${sus.length - limit}묶음`);
  for (const [day, nos, total, why] of cls.filter((c) => c[4]).slice(0, limit)) out.push(`  정상으로 봄 ${day} 전표 ${nos.join(", ")} · ${won(total)} · ${why}`);
  return out;
}

type Bank = [IsoDate, number, string, string, "지급" | "입금", Set<string>, Set<string>];

function bankLines(journal: JLine[], cashCodes: readonly string[]): Bank[] {
  const codes = new Set(cashCodes.map(sq));
  const slips = new Map<string, JLine[]>();
  for (const ln of journal) {
    if (ln.date === null) continue;
    const k = slipKey(ln.date, String(ln.no || ""));
    const s = slips.get(k);
    if (s) s.push(ln);
    else slips.set(k, [ln]);
  }
  const out: Bank[] = [];
  for (const ln of journal) {
    if (!codes.has(sq(ln.account_code)) || ln.date === null) continue;
    const vn = vnOf(ln);
    const mates = slips.get(slipKey(ln.date, String(ln.no || ""))) ?? [ln];
    const names = new Set(mates.map(vnOf).filter((n) => n));
    const vcodes = new Set(mates.filter((x) => pyStrip(String(x.vendor_code || ""))).map((x) => normCode(x.vendor_code)).filter((c) => c));
    if ((ln.credit || 0) > 0) out.push([ln.date, ln.credit as number, vn, String(ln.no || ""), "지급", names, vcodes]);
    if ((ln.debit || 0) > 0) out.push([ln.date, ln.debit as number, vn, String(ln.no || ""), "입금", names, vcodes]);
  }
  return out;
}

type Archive = [string[], string[][]];

/** _read_archive -> (머리줄, 줄 목록) · 없으면 ([], []) · 읽지 못하면 null */
function readArchive(files: ConvFiles, path: string): Archive | null {
  if (!exists(files, path)) return [[], []];
  const text = decodeText(files[path] as Uint8Array);
  if (text === null) return null;
  const rows = parseCsv(text).map((r) => r.cells);
  if (!rows.length) return [[], []];
  return [(rows[0] as string[]).map((h) => pyStrip(h)), rows.slice(1).filter((r) => r.some((c) => pyStrip(c || "")))];
}

function usedBefore(arc: Archive | null): Set<string> {
  const used = new Set<string>();
  if (!arc) return used;
  const [header, rows] = arc;
  const iAmt = header.indexOf("금액");
  for (const cells of rows) {
    for (const c of cells) {
      const m = USED_RE.exec(c || "");
      if (!m) continue;
      const amt = iAmt >= 0 && iAmt < cells.length ? num(cells[iAmt]) : null;
      used.add(`${m[1]}\u0000${m[2]}\u0000${amt ? Math.abs(amt) : "None"}`);
      break;
    }
  }
  return used;
}

export interface Tidy { lines: string[]; files: Record<string, string> }

/** archive_paid_schedule -> 결과 글자 줄과 새로 쓸 파일 (입력 폴더 안 이름 → BOM 포함 글). today = 정리일. */
export function archivePaidSchedule(files: ConvFiles, inputDir: string, journal: JLine[], bookDate: IsoDate | null,
  cashCodes: readonly string[], today: IsoDate): Tidy {
  const path = join(inputDir, SCHEDULE);
  if (!exists(files, path) || bookDate === null) return { lines: [], files: {} };
  const info: CsvInfo = {};
  const [rows, ok] = readCsvFile(files, path, SCHEMA[SCHEDULE] as string[], new Issues(), info);
  if (!ok || info.missing?.length) return { lines: [`자금일정 정리: ${SCHEDULE}를 읽지 못해 그대로 둠`], files: {} };
  const hasCode = rows.some((r) => Object.prototype.hasOwnProperty.call(r, "거래처코드"));
  const arcPath = join(inputDir, ARCHIVE);
  const arc = readArchive(files, arcPath);
  if (arc === null) {
    return { lines: [`자금일정 정리: ${ARCHIVE} 을 읽지 못해 그대로 둠 — 엑셀에서 열려 있으면 닫고, 깨졌으면 파일을 다른 이름으로 옮긴 뒤 다시 변환하세요`], files: {} };
  }
  const before = usedBefore(arc);
  const bank = bankLines(journal, cashCodes).filter((b) => b[0] <= bookDate
    && !before.has(`${b[0]}\u0000${b[3]}\u0000${b[1]}`) && !before.has(`${b[0]}\u0000${b[3]}\u0000None`));
  const dayOf = (r: Row) => parseDate(rget(r, "예정일"));
  const used = new Set<number>();
  const hits = new Map<number, number>();
  const pairs: [number, number, number, number][] = [];
  const order = rows.map((_, i) => i).sort((a, b) => cmpKey([dayOf(rows[a] as Row) ?? "9999-12-31", a], [dayOf(rows[b] as Row) ?? "9999-12-31", b]));
  for (const i of order) {
    const r = rows[i] as Row;
    const day = dayOf(r);
    const amount = num(rget(r, "금액"));
    let io = pyStrip(rs(r, "입출금"));
    io = io === "출금" ? "지급" : io;
    if (!(io in EARLY_DAYS) || day === null || !amount) continue;
    const vn = normVendor(rs(r, "거래처"));
    const vc = pyStrip(rs(r, "거래처코드")) ? normCode(rget(r, "거래처코드")) : "";
    bank.forEach(([bday, bamt, bvn, , bio, bnames, bcodes], k) => {
      if (used.has(k) || bio !== io || bamt !== Math.abs(amount)) return;
      const gap = daysBetween(day, bday);
      if (gap < -(EARLY_DAYS[io] as number)) return;
      let same: boolean;
      if (vc && bcodes.size) {
        same = bcodes.has(vc);
        if (!same) return;
      } else {
        same = !!vn && (vn === bvn || bnames.has(vn));
        if (Math.abs(gap) <= MATCH_DAYS) {
          if (vn && bnames.size && !same) return;
        } else if (!same) return;
      }
      pairs.push([same ? 0 : 1, Math.abs(gap), i, k]);
    });
  }
  pairs.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2] || a[3] - b[3]);
  for (const [, , i, k] of pairs) {
    if (hits.has(i) || used.has(k)) continue;
    used.add(k);
    hits.set(i, k);
  }
  const keep: Row[] = [], moved: [Row, string][] = [];
  rows.forEach((r, i) => {
    const k = hits.get(i);
    if (k === undefined) { keep.push(r); return; }
    const [bday, , , bno, bio] = bank[k] as Bank;
    const day = dayOf(r) as IsoDate;
    const when = bday < addDays(day, -MATCH_DAYS) ? `예정일 ${daysBetween(bday, day)}일 전`
      : bday > addDays(day, MATCH_DAYS) ? `예정일 ${daysBetween(day, bday)}일 뒤` : "";
    moved.push([r, `분개장 ${bday} 전표 ${bno} 보통예금 ${bio === "지급" ? "출금" : "입금"}과 맞음${when ? ` (${when})` : ""}`]);
  });
  if (!moved.length) return { lines: ["자금일정 정리: 통장에서 이미 나가거나 들어온 줄 없음"], files: {} };
  const base = [...(SCHEMA[SCHEDULE] as string[]), ...(hasCode ? SCHED_OPTIONAL : [])];
  const cols = [...new Set([...(info.header ?? []).filter((h) => h), ...base])];
  const [oldHead, oldRows] = arc;
  const head = [...oldHead];
  for (const c of [...cols, "정리일", "정리 근거"]) if (!head.includes(c)) head.push(c);
  const cell = (r: Row, c: string) => rget(r, c) ?? "";
  const arcRows: string[][] = [head];
  for (const cells of oldRows) arcRows.push([...cells, ...Array(Math.max(0, head.length - cells.length)).fill("")]);
  for (const [r, why] of moved) {
    const val: Record<string, string> = {};
    for (const c of cols) val[c] = cell(r, c);
    val["정리일"] = today;
    val["정리 근거"] = why;
    arcRows.push(head.map((c) => val[c] ?? ""));
  }
  const schedRows: string[][] = [cols, ...keep.map((r) => cols.map((c) => cell(r, c)))];
  const sum = moved.reduce((a, [r]) => a + Math.abs(num(rget(r, "금액")) || 0), 0);
  const lines = [`자금일정 정리: 통장에서 이미 나가거나 들어온 ${moved.length}줄 ${won(sum)} → ${ARCHIVE} 로 옮김`];
  for (const [r, why] of moved) lines.push(`  옮김 ${rget(r, "예정일") ?? ""} ${won(Math.abs(num(rget(r, "금액")) || 0))}원 — ${why}`);
  return { lines, files: { [SCHEDULE]: "﻿" + writeCsv(schedRows), [ARCHIVE]: "﻿" + writeCsv(arcRows) } };
}

export const SCHEDULE_NOTE = "(자금일정.csv는 바꾸지 않음)";
const UNPAID = ["요청미지급", "카드사용미결제"];
const digits = (t: unknown) => String(t ?? "").replace(/\D/g, "");
const tget = (r: TRow, c: string) => (r[c] === null || r[c] === undefined ? "" : String(r[c]));

/** schedule_overlaps: prevExecs = 이번에 만들지 못했을 때 읽은 이전 프로젝트집행.csv ([줄, 상태]). */
export function scheduleOverlaps(files: ConvFiles, inputDir: string, tables: Table[], prevExecs: () => [TRow[], string]):
  [[Row, TRow, number][] | null, string] {
  const path = join(inputDir, SCHEDULE);
  if (!exists(files, path)) return [null, "자금일정.csv 없음"];
  const info: CsvInfo = {};
  const [sched, ok] = readCsvFile(files, path, SCHEMA[SCHEDULE] as string[], new Issues(), info);
  if (!ok || info.missing?.length) return [null, "자금일정.csv를 읽지 못함"];
  const made = tables.filter((t) => t.name === "프로젝트집행.csv" && t.written);
  let execs: TRow[];
  if (made.length) execs = (made[0] as Table).rows;
  else {
    const [rows, state] = prevExecs();
    if (state === "읽지 못함") return [null, "프로젝트집행.csv를 읽지 못함"];
    execs = rows;
  }
  const unpaid = execs.filter((e) => UNPAID.includes(pyStrip(tget(e, "상태"))) && !tget(e, "근거").includes(PRIOR_TAG));
  const pairs: [Row, TRow, number][] = [];
  for (const sr of sched) {
    if (!["출금", "지급"].includes(pyStrip(rs(sr, "입출금")))) continue;
    const amount = num(rget(sr, "금액"));
    if (amount === null) continue;
    for (const e of unpaid) {
      const supply = num(e["공급가액"]), vat = num(e["부가세"]);
      if (supply === null || !(vat === null ? [supply] : [supply, supply + vat]).includes(amount)) continue;
      const dp = digits(rget(sr, "프로젝트번호"));
      const sameProject = !!dp && dp === digits(e["프로젝트번호"]);
      const nv = normVendor(rget(sr, "거래처"));
      const sameVendor = !!nv && nv === normVendor(tget(e, "거래처"));
      if (sameProject || sameVendor) pairs.push([sr, e, amount]);
    }
  }
  return [pairs, ""];
}

/** overlap_lines */
export function overlapLines(files: ConvFiles, inputDir: string, tables: Table[], prevExecs: () => [TRow[], string]): string[] {
  const [pairs, why] = scheduleOverlaps(files, inputDir, tables, prevExecs);
  if (pairs === null) return [`자금일정.csv와 겹칠 수 있는 줄 판단 불가 (${why}) ${SCHEDULE_NOTE}`];
  const out = [`자금일정.csv와 겹칠 수 있는 줄 ${pairs.length}건 ${SCHEDULE_NOTE}`];
  for (const [sr, e, amount] of pairs) {
    const parts = [pyStrip(rs(sr, "예정일")) || "날짜 없음", pyStrip(rs(sr, "입출금")), won(amount), pyStrip(rs(sr, "프로젝트번호")), pyStrip(rs(sr, "거래처"))];
    const vat = num(e["부가세"]);
    const mine = [pyStrip(tget(e, "상태")), pyStrip(tget(e, "프로젝트번호")), pyStrip(tget(e, "거래처")),
      "공급가액 " + won(num(e["공급가액"])) + (vat !== null ? " + 부가세 " + won(vat) : "")];
    out.push("  겹침 자금일정 " + parts.filter((x) => x).join(" ") + " ↔ 프로젝트집행 " + mine.filter((x) => x).join(" "));
  }
  return out;
}
