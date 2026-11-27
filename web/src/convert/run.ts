// convert.run 의 순수 판: 원천 파일 묶음 → 만든 CSV 글·종료 코드·화면 줄.
// 파일을 쓰지 않는다. 범위 밖 표(위하고대조·연간자료·현금흐름·계정잔액·위하고 화면 원본·잉여금·세무조정·신고일정·신고도우미·자료대조)와
// 홈택스 대조·거래처 계좌 등록·지급 요청서 옮기기·자동분석/확인할것 저장은 하지 않는다 (docs/superpowers/plans/2026-11-27-convert.md).
import { DEPT_ACCOUNT_FILE, DEPT_ACCOUNT_KEYS, DEPT_FILE, DEPT_KEYS, EVID_FILE, EVID_KEYS, SCHEMA, STAFF_FILE, STAFF_KEYS,
  ACCOUNT_FILE, ACCOUNT_KEYS, loadData } from "../model/data";
import { decodeText, type FileSet } from "../model/csv";
import { daysBetween, type IsoDate } from "../model/dates";
import { pyIsDigit } from "../model/py";
import { maskRrn, num, won } from "../model/util";
import { dropClosingPl } from "./closing";
import { readConfig, type Cfg } from "./config";
import { COLLECT, INPUT, WEHAGO, basename, exists, join, listDirs, listFiles, type ConvFiles } from "./files";
import { buildInvoices } from "./invoices";
import * as linking from "./linking";
import { DEPT_OPTIONAL, UNLINKED_PROJECT, buildAccounts, buildDept, buildDeptAccounts, buildPl, buildStaff } from "./pl";
import { buildExecs, buildProjects, outOfPeriod, periodText } from "./projects";
import { archivePaidSchedule, duplicateLines, overlapLines } from "./review";
import * as snapshot from "./snapshot";
import { Table, check, checkResult, tableText, type Check, type TRow } from "./table";
import { bookNoteTable, buildBank, buildDebts, buildEvidence, buildFundplan, buildTax, fundplanReceivedTable, keepIfUnreadable,
  readPrevRows, readPrevState } from "./tables";
import { loadBooks, loadSales, matchRequests, prepareBooks, type BookCtx, type Books, type Sales } from "./wehago";

export type { ConvFiles } from "./files";

/** 이 판이 만드는 CSV (GENERATED 중 범위 안). */
export const IN_SCOPE = ["손익.csv", "계산서.csv", "프로젝트.csv", "프로젝트집행.csv", "자금계획.csv", "자금계획받은달.csv", "부서비용.csv",
  "사원급여.csv", "부서계정비용.csv", "세금예상.csv", "계정별비용.csv", "증빙월별.csv", "장부잔액.csv", "장부입출금.csv", "장부채무.csv",
  "장부알림.csv"];
/** 변환이 함께 고치는 수동 파일 (review_checks.archive_paid_schedule). */
export const SIDE_FILES = ["자금일정.csv", "자금일정_지난기록.csv"];

export interface ConvertOpts {
  /** D7 고침: 받다 만 새 분개장은 버리고 예전 분개장으로 계산 (기본 켬). 끄면 옛 프로그램처럼 변환하지 않음(코드 3). */
  skipPartialJournal?: boolean;
  /** 파일 수정 시각 (원천 파일 경로 → 초). 같은 날짜 자료 고르기에만 쓴다. 없으면 0. */
  mtimes?: Record<string, number>;
  /** 입력 폴더 파일의 작성일 (경로 → YYYY-MM-DD). 계산서.csv 를 못 만들 때 알림에만 쓴다. */
  fileDays?: Record<string, IsoDate>;
  /** 이전 파일 폴더 이름. 없으면 now 로 'YYYYMMDD_HHMMSS'. */
  stamp?: string;
}

export interface ConvertResult {
  code: number;
  lines: string[];
  /** 입력 폴더 안 이름 → 쓸 글 (UTF-8 BOM 포함, csv.writer 와 같은 모양). */
  files: Record<string, string>;
}

interface Links {
  costs: linking.LinkResult; revenue: linking.LinkResult; projects: linking.Projects; snapshot: boolean;
  requests: ReturnType<typeof linking.requestsOf>; overrides: linking.Links; notes: string[];
}

function buildLinks(books: Books, cfg: Cfg, snap: snapshot.Snapshot | null, files: ConvFiles, asof: IsoDate, now: string): Links {
  const requests = linking.requestsOf(snap ? snap.payments : null, asof, now);
  const projects = linking.projectsOf(snap);
  let [overrides, notes] = linking.readLinks(files, INPUT);
  let more: string[];
  [overrides, more] = linking.checkLinks(books.journal, overrides);
  notes = [...notes, ...more];
  const old = snap?.old ?? null;
  if (old !== null) notes = [...notes, ...old.notes];
  const costs = linking.linkCosts(books, [...requests, ...linking.oldRequests(old, asof, now)], projects, overrides, cfg.link_days,
    cfg.direct_prefixes, cfg.direct_mark, cfg.vat_codes);
  const revenue = linking.linkRevenue(books, projects, overrides, cfg.revenue_codes);
  return { costs, revenue, projects, snapshot: snap !== null, requests, overrides, notes };
}

function unlinkedTotal(summary: Map<string, linking.BasisSum>): string {
  const s = summary.get("미연결") ?? { count: 0, sum: 0, unknown: 0 };
  return `${s.count}건 ${won(s.sum)}${s.unknown ? ` (금액 미확인 ${s.unknown}건)` : ""}`;
}

function linkStdoutLine(links: Links): string {
  return `프로젝트 연결: 원가 미연결 ${unlinkedTotal(links.costs.summary)} · 매출 미연결 ${unlinkedTotal(links.revenue.summary)} (변환결과.txt 목록)`;
}

function readLatestSnapshot(files: ConvFiles): [snapshot.Snapshot | null, string] {
  let snap: snapshot.Snapshot;
  try {
    const path = snapshot.latestSnapshot(files, COLLECT);
    if (path === null) return [null, "인트라넷 스냅숏: 없음 — 자동 연결 안 함"];
    snap = snapshot.readSnapshot(files, path);
  } catch (e) {
    if (e instanceof snapshot.SnapshotError) return [null, `인트라넷 스냅숏: 읽지 못함 — ${e.message}`];
    throw e;
  }
  snap.old = snapshot.loadOld(files, COLLECT);
  return [snap, ""];
}

function snapshotLines(snap: snapshot.Snapshot | null, snapLine: string, asof: IsoDate, cfg: Cfg): [string, string | null] {
  if (snap === null) return [snapLine, null];
  const stamp = snap.collected_at;
  const days = daysBetween(stamp.slice(0, 10), asof);
  const age = days > 0 ? `기준일보다 ${days}일 이전` : days === 0 ? "기준일과 같은 날" : `기준일보다 ${-days}일 뒤`;
  const line = `인트라넷 스냅숏 ${basename(snap.path)} (수집 ${stamp}, ${age})`;
  let warn: string | null = null;
  if (days < 0) {
    warn = `경고: 인트라넷 스냅숏이 기준일(${asof})보다 ${-days}일 뒤에 수집됨 (수집 ${stamp}) — 기준일 시점의 지급요청·프로젝트가 아닐 수 있음`;
  } else if (days > cfg.snapshot_days) {
    warn = `경고: 인트라넷 스냅숏이 기준일보다 ${days}일 이전 (수집 ${stamp}) — 설정 변환_스냅숏경과일 ${cfg.snapshot_days}일을 넘음: `
      + "지급요청·프로젝트가 오래됐을 수 있음 (승인검토.py로 새로 수집한 뒤 다시 변환)";
  }
  const skip = snapshot.skippedProjects(snap);
  if (skip) warn = (warn ? warn + " / " : "") + "경고: " + snapshot.SKIP_NOTE.replace("%d", String(skip)).replace("[확인] ", "");
  return [line, warn];
}

function statusWarning(links: Links | null): string | null {
  const requests = links?.requests ?? [];
  if (!requests.length || requests.some((rq) => rq.status_text)) return null;
  return `경고: 인트라넷 지급요청 ${requests.length}건 모두 사장님승인 빈칸 — 스냅숏 수집 확인 필요 `
    + "(모두 '상태 확인 필요'로 요청미지급(추정)·요청 누계에 넣음)";
}

function keptInvoiceReason(files: ConvFiles, sales: Sales, fileDays: Record<string, IsoDate>): string {
  let reason = sales.reason || "자료 없음 (매출 계산서 엑셀)";
  const path = join(INPUT, "계산서.csv");
  if (!exists(files, path)) return reason;
  const none = "자료 없음 (매출 계산서 엑셀)";
  if (sales.state === "자료 없음" && reason.startsWith(none)) reason = "매출 계산서 엑셀 없음" + reason.slice(none.length);
  return `${reason} → 기존 계산서.csv 유지 (갱신 안 됨, 작성일 ${fileDays[path] ?? "알 수 없음"})`;
}

function unwritten(reason: string, names: string[]): Table[] {
  return names.map((n) => new Table(n, SCHEMA[n] ?? [], [], { written: false, reason }));
}

const sumKnown = (vals: (number | null)[]): number | null => {
  let t = 0;
  for (const v of vals) {
    if (v === null) return null;
    t += v;
  }
  return t;
};

function firstCsv(t: Table, prefix: string): number | null {
  for (const c of t.checks) if (c.label.startsWith(prefix)) return c.csv;
  return null;
}

/** cross_checks 중 범위 안 (손익·프로젝트집행·프로젝트). 위하고대조 쪽 세 대조는 범위 밖. */
function crossChecks(tables: Table[]): Check[] {
  const by = new Map(tables.filter((t) => t.written).map((t) => [t.name, t]));
  const pl = by.get("손익.csv"), execs = by.get("프로젝트집행.csv"), projects = by.get("프로젝트.csv");
  const out: Check[] = [];
  if (pl === undefined || pl.checks.length < 3) return out;
  const plDirect = (pl.checks[1] as Check).csv;
  const s = (r: TRow, k: string) => (r[k] === null || r[k] === undefined ? "" : String(r[k]));
  const unlinked = pl.rows.filter((r) => s(r, "출처") === "WEHAGO" && s(r, "단위") === "프로젝트" && s(r, "대상") === UNLINKED_PROJECT);
  const plUnlinked = sumKnown(unlinked.map((r) => num(r["직접비"])));
  if (execs !== undefined && projects !== undefined) {
    out.push(check("손익 직접비 = 프로젝트집행 원가 줄 합계", plDirect, firstCsv(execs, "원가 줄 합계")));
    const keys = new Set(projects.rows.map((r) => s(r, "프로젝트번호").trim()));
    const portions = (execs.extra["cost_portions"] as (number | null)[] | undefined) ?? [];
    const mine: (number | null)[] = [];
    execs.rows.forEach((r, i) => {
      if (i >= portions.length) return;
      if (s(r, "상태") !== "집행계획미요청" && s(r, "근거").startsWith("WEHAGO ") && !keys.has(s(r, "프로젝트번호").trim())) mine.push(portions[i] ?? null);
    });
    out.push(check("손익 프로젝트 미연결 직접비 = 프로젝트집행 프로젝트.csv에 없는 번호의 원가 부분", plUnlinked, sumKnown(mine)));
  }
  return out;
}

function stampOf(now: string): string {
  return now.slice(0, 10).replace(/-/g, "") + "_" + now.slice(11, 19).replace(/:/g, "");
}

/** 입력 폴더 글 묶음 (data.load 가 읽는 모양): 입력/ 바로 아래 글 파일 + 이번에 쓴 글. */
function inputFileSet(files: ConvFiles, written: Record<string, string>): FileSet {
  const out: FileSet = {};
  for (const name of listFiles(files, INPUT)) {
    if (!/\.(csv|json|txt)$/i.test(name)) continue;
    const t = decodeText(files[join(INPUT, name)] as Uint8Array);
    if (t !== null) out[name] = t;
  }
  for (const [name, text] of Object.entries(written)) out[name] = text.startsWith("﻿") ? text.slice(1) : text;
  return out;
}

function inputCheckLines(fs: FileSet): string[] {
  const items = loadData(fs).issues.items;
  const out = [`보고서 입력 확인 필요 ${items.length}건`];
  for (const [name, line, msg] of items) out.push(`  확인 ${name} ${pyIsDigit(String(line)) ? `${line}번째 줄` : "전체"}: ${msg}`);
  return out;
}

const enc = new TextEncoder();

/** 변환 한 번 (convert.run). now = 'YYYY-MM-DD HH:MM:SS' (계산에 쓰는 지금, 정리일·이전 폴더 이름에도 씀). */
export async function convert(input: ConvFiles, asof: IsoDate, now: string, opts: ConvertOpts = {}): Promise<ConvertResult> {
  const mtimes = opts.mtimes ?? {};
  const today = now.slice(0, 10);
  const stamp = opts.stamp ?? stampOf(now);
  const [cfg] = readConfig(input, INPUT);
  const cache = await prepareBooks(input, WEHAGO);
  const ctx: BookCtx = { files: input, cache, folder: WEHAGO, mtimes };
  const books = loadBooks(ctx, asof, null, { skipPartialJournal: opts.skipPartialJournal ?? true });
  const [snap, snapLine] = readLatestSnapshot(input);
  let code = 0;
  let tables: Table[];
  let cross: Check[] = [];
  let links: Links | null = null;
  const states: Record<string, string> = {};
  if (books.state !== "ok") {
    code = 3;
    tables = unwritten("WEHAGO 장부를 쓸 수 없음", ["손익.csv", "계산서.csv", "프로젝트.csv", "프로젝트집행.csv"]);
  } else {
    dropClosingPl(books, cfg);
    const prev: Record<string, TRow[]> = {};
    for (const name of ["손익.csv", "계산서.csv", "프로젝트.csv", "프로젝트집행.csv"]) [prev[name], states[name]] = readPrevState(input, INPUT, name) as [TRow[], string];
    links = buildLinks(books, cfg, snap, input, asof, now);
    const sales = loadSales(ctx, asof, books);
    const invoices = buildInvoices(sales, books, links.revenue, links.projects, prev["계산서.csv"] as TRow[], cfg);
    if (!invoices.written) invoices.reason = keptInvoiceReason(input, sales, opts.fileDays ?? {});
    tables = [buildPl(books, cfg, prev["손익.csv"] as TRow[], links), invoices];
    if (snap === null) {
      tables.push(...unwritten("인트라넷 스냅숏 없음 (기존 파일 그대로)", ["프로젝트.csv", "프로젝트집행.csv"]));
    } else {
      const match = matchRequests(books, links.requests);
      const history = outOfPeriod(books, links.projects, links.requests);
      const projectTable = buildProjects(links.projects, links.revenue, prev["프로젝트.csv"] as TRow[], history, periodText(books));
      if (snap.projects.length) {
        projectTable.notes.push(`인트라넷 승인 칸 글자 — ${linking.approvalWords(snap.projects)} (끝남으로 읽는 글자: ${linking.APPROVAL_DONE.join("·")})`);
      }
      const execs = buildExecs(books, links.costs, links.requests, match, prev["프로젝트집행.csv"] as TRow[], cfg, links.projects);
      tables.push(projectTable, execs);
    }
    const fp = buildFundplan(input, books, cfg, WEHAGO, asof, mtimes);
    tables.push(fp, fundplanReceivedTable(fp));
    let p = readPrevRows(input, INPUT, DEPT_FILE, DEPT_KEYS, DEPT_OPTIONAL);
    tables.push(keepIfUnreadable(buildDept(books, cfg, p ?? []), p));
    p = readPrevRows(input, INPUT, STAFF_FILE, STAFF_KEYS);
    tables.push(keepIfUnreadable(buildStaff(books, cfg, p ?? []), p));
    p = readPrevRows(input, INPUT, DEPT_ACCOUNT_FILE, DEPT_ACCOUNT_KEYS);
    tables.push(keepIfUnreadable(buildDeptAccounts(books, cfg, p ?? []), p));
    tables.push(buildTax(input, books, cfg, asof, INPUT, WEHAGO, today));
    tables.push(...buildBank(books, cfg));
    tables.push(buildDebts(books, cfg));
    p = readPrevRows(input, INPUT, ACCOUNT_FILE, ACCOUNT_KEYS);
    tables.push(keepIfUnreadable(buildAccounts(books, cfg, p ?? []), p));
    p = readPrevRows(input, INPUT, EVID_FILE, EVID_KEYS);
    tables.push(keepIfUnreadable(buildEvidence(books, sales, p ?? []), p));
    tables.push(bookNoteTable(books));
    cross = crossChecks(tables);
  }
  // 이전 파일 폴더: 이번에 쓰는 이름 중 이미 있던 것 (변환결과.txt 포함)
  const names = [...tables.filter((t) => t.written).map((t) => t.name), "변환결과.txt"];
  const moved = names.filter((n) => exists(input, join(INPUT, n)));
  let backup: string | null = null;
  if (moved.length) {
    const taken = new Set(listDirs(input, join(INPUT, "이전")));
    backup = stamp;
    for (let n = 2; taken.has(backup); n++) backup = `${stamp}_${n}`;
  }
  const where = backup ? `입력/이전/${backup}/` : "";
  for (const t of tables) {
    if (t.written && states[t.name] === "읽지 못함") {
      t.notes.push(t.name === "손익.csv" ? `이전 손익.csv를 읽지 못해 WEHAGO 외 출처 줄을 옮기지 못함 (${where} 에 원본 보관)`
        : `이전 ${t.name}를 읽지 못해 옮길 줄을 옮기지 못함 (${where} 에 원본 보관)`);
    }
  }
  const backupLine = backup ? `이전 파일: ${where} (${moved.join(", ")})` : "이전 파일: 없음";
  const out: Record<string, string> = {};
  for (const t of tables) if (t.written) out[t.name] = tableText(t);
  const summary: string[] = [];
  if (books.state === "ok") {
    const tidy = archivePaidSchedule(input, INPUT, books.journal, books.book_date, cfg.cash_codes, today);
    Object.assign(out, tidy.files);
    const view: ConvFiles = { ...input };
    for (const [n, text] of Object.entries(tidy.files)) view[join(INPUT, n)] = enc.encode(text);
    const dups = duplicateLines(books.journal);
    const overlap = overlapLines(view, INPUT, tables, () => readPrevState(input, INPUT, "프로젝트집행.csv"));
    const checks = inputCheckLines(inputFileSet(input, out));
    summary.push(...(tidy.lines.length ? [tidy.lines[0] as string] : []), overlap[0] as string, dups[0] as string, checks[0] as string);
  }
  const [snapConsole, snapWarning] = snapshotLines(snap, snapLine, asof, cfg);
  const lines: string[] = [];
  if (books.state !== "ok") lines.push("변환하지 않음 — WEHAGO 장부를 쓸 수 없음: " + books.reason);
  else {
    const late = daysBetween(books.book_date as IsoDate, asof);
    lines.push(`WEHAGO 장부 기준일 ${books.book_date}${late > 0 ? ` · 기준일보다 ${late}일 이전` : ""}`);
  }
  lines.push(...books.dropped_partial);   // D7: 받다 만 분개장을 버렸다는 경고 (새 시스템)
  lines.push(snapConsole);
  if (snapWarning) lines.push(snapWarning);
  const warning = statusWarning(links);
  if (warning) lines.push(warning);
  for (const t of tables) lines.push(t.written ? `${t.name} 만듦 ${t.rows.length}줄` : `[${t.name}] 만들지 않음 — ${t.reason}`);
  if (links !== null) lines.push(maskRrn(linkStdoutLine(links)));
  if (backup) lines.push(backupLine);
  lines.push(...new Set([...tables.flatMap((t) => t.notes.map(String).filter((n) => n.startsWith("[확인]"))),
    ...books.notes.map(String).filter((n) => n.startsWith("[확인]"))]));
  const all = [...tables.filter((t) => t.written).flatMap((t) => t.checks), ...cross];
  const undecided = all.filter((c) => checkResult(c) === "판단 불가").length;
  if (undecided) lines.push(`대조 판단 불가 ${undecided}건`);
  lines.push(`대조 불일치 ${all.filter((c) => checkResult(c) === "불일치").length}건`);
  lines.push(...summary);
  lines.push("대조 내용: " + join(INPUT, "변환결과.txt"));
  return { code, lines, files: out };
}
