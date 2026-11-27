// snapshot.py(읽기 부분)·old_intranet.py: 인트라넷 수집 스냅숏과 예전 인트라넷 CSV 읽기.
import { parseCsv } from "../model/csv";
import { cmpStr, pyIsDigit, pyStrip } from "../model/py";
import { Issues } from "../model/util";
import { basename, decodeTextOr, exists, join, listDirs, listFiles, readCsvFile, type ConvFiles } from "./files";

export const PAYMENT_COLUMNS = ["번호", "행사명", "파트너", "등록일", "행사일", "금액", "지급요청일", "등록자", "팀장승인", "관리팀승인", "사장님승인"];
export const PROJECT_COLUMNS = ["번호", "클라이언트", "담당자", "PO번호", "행사일", "행사명", "국", "팀", "등록자", "계산서", "사전견적", "견적금액",
  "실행가", "수익률", "승인_담당자", "승인_팀장", "승인_관리팀", "승인_대표이사", "pro_num"];
export const FORMAT = "1";
const FOLDER_RE = /^인트라넷_\d{8}_\d{6}$/;
export const PAYMENT_FILE = "지급요청.csv", PROJECT_FILE = "프로젝트목록.csv", INFO_FILE = "수집정보.csv";

export class SnapshotError extends Error {}

export type Rec = Record<string, string>;

export interface OldData { projects: Rec[]; payments: Rec[]; notes: string[]; files: string[] }

export interface Snapshot {
  path: string;                 // '수집/인트라넷_…'
  collected_at: string;         // 'YYYY-MM-DD HH:MM:SS'
  payments: Rec[];
  projects: Rec[];
  info: Record<string, string>;
  old: OldData | null;
}

/** latest_snapshot: 가장 최근 스냅숏 폴더 경로 또는 null. */
export function latestSnapshot(files: ConvFiles, root: string): string | null {
  const names = listDirs(files, root).filter((n) => FOLDER_RE.test(n) && exists(files, join(join(root, n), INFO_FILE)));
  if (!names.length) return null;
  return join(root, names.reduce((m, x) => (cmpStr(x, m) > 0 ? x : m)));
}

function readTable(files: ConvFiles, path: string, columns: string[]): Rec[] {
  const issues = new Issues();
  const name = basename(path);
  const [rows, ok] = readCsvFile(files, path, ["수집시각", ...columns], issues);
  if (issues.items.length) throw new SnapshotError(`${name}: ${issues.items.map((i) => i[2]).join("; ")}`);
  if (!ok) throw new SnapshotError(`${name}을(를) 읽지 못했습니다`);
  return rows.map((r) => {
    const o: Rec = {};
    for (const c of columns) o[c] = r[c] === undefined ? "" : String(r[c]);
    return o;
  });
}

const TIME_RE = /^(\d{4})-(\d{1,2})-(\d{1,2}) (\d{1,2}):(\d{1,2}):(\d{1,2})$/;

/** datetime.strptime(s, '%Y-%m-%d %H:%M:%S') 를 맞춘 'YYYY-MM-DD HH:MM:SS' 또는 null. */
export function parseStamp(s: string): string | null {
  const m = TIME_RE.exec(s);
  if (!m) return null;
  const [y, mo, d, h, mi, se] = m.slice(1).map(Number) as number[];
  const dim = [31, (y! % 4 === 0 && (y! % 100 !== 0 || y! % 400 === 0)) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (mo! < 1 || mo! > 12 || d! < 1 || d! > dim[mo! - 1]! || h! > 23 || mi! > 59 || se! > 59) return null;
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${p(y!, 4)}-${p(mo!)}-${p(d!)} ${p(h!)}:${p(mi!)}:${p(se!)}`;
}

/** read_snapshot */
export function readSnapshot(files: ConvFiles, path: string): Snapshot {
  const issues = new Issues();
  const [rows, ok] = readCsvFile(files, join(path, INFO_FILE), ["항목", "값"], issues);
  if (issues.items.length || !ok) throw new SnapshotError(`${INFO_FILE}: ${issues.items.map((i) => i[2]).join("; ") || "읽지 못했습니다"}`);
  const info: Record<string, string> = {};
  for (const r of rows) info[String(r["항목"])] = String(r["값"]);
  if (info["형식"] !== FORMAT) throw new SnapshotError(`${INFO_FILE}: 알 수 없는 형식 '${info["형식"] ?? ""}' (필요: ${FORMAT})`);
  const collected = parseStamp(info["수집시각"] ?? "");
  if (collected === null) throw new SnapshotError(`${INFO_FILE}: 수집시각을 읽지 못했습니다: '${info["수집시각"] ?? ""}'`);
  const payments = readTable(files, join(path, PAYMENT_FILE), PAYMENT_COLUMNS);
  const projects = readTable(files, join(path, PROJECT_FILE), PROJECT_COLUMNS);
  for (const [label, got, key] of [["지급요청", payments, "지급요청_건수"], ["프로젝트", projects, "프로젝트_건수"]] as const) {
    const want = info[key] ?? "";
    if (!pyIsDigit(want) || Number(want) !== got.length) {
      throw new SnapshotError(`${label} 건수가 수집정보와 다릅니다: 수집정보 ${want || "없음"}건, 파일 ${got.length}건`);
    }
  }
  checkNumbers(payments);
  return { path, collected_at: collected, payments, projects, info, old: null };
}

function checkNumbers(payments: Rec[]): void {
  const numbers = payments.map((p) => pyStrip(p["번호"] || ""));
  const empty = numbers.filter((n) => !n).length;
  const count = new Map<string, number>();
  for (const n of numbers) if (n) count.set(n, (count.get(n) ?? 0) + 1);
  const dup = [...count.entries()].filter(([, k]) => k > 1).map(([n]) => n).sort(cmpStr);
  const problems: string[] = [];
  if (empty) problems.push(`번호가 빈 줄 ${empty}건`);
  if (dup.length) problems.push(`번호가 겹치는 줄 ${dup.reduce((s, n) => s + count.get(n)!, 0)}건 (${dup.slice(0, 5).join(", ") + (dup.length > 5 ? " 외" : "")})`);
  if (problems.length) throw new SnapshotError(`${PAYMENT_FILE}: 지급요청 ${problems.join(" · ")} — 요청을 구별할 수 없어 멈춤`);
}

/** skipped_projects */
export function skippedProjects(snap: Snapshot | null): number {
  const v = pyStrip(String(snap?.info?.["프로젝트_건너뜀"] || ""));
  return pyIsDigit(v) ? Number(v) : 0;
}

export const SKIP_NOTE = "[확인] 인트라넷 프로젝트 목록에서 칸 모양이 달라 읽지 못한 줄 %d건 — 그 프로젝트의 사전견적·예상 매출·추정 예산이 보고에서 빠져 있음"
  + " (인트라넷 수집을 다시 하고, 계속되면 출력\\인트라넷_구조점검.txt 확인)";

// ───────────── 예전 인트라넷 (old_intranet.py) ─────────────
export const OLD_FOLDER = "예전인트라넷";
export const OLD_LAST_DAY = "2026-03-31";
export const OLD_STATE = "완료(예전 인트라넷)";
const NO_PREFIX = "구";
const PROJECT_RE = /^old_projects_\d{4}\.csv$/i;
const PAYMENT_RE = /^old_payments_\d{4}\.csv$/i;

const PROJECT_ALIASES: Record<string, string> = { "내부번호": "내부번호", "클라이언트": "클라이언트", "담당자": "담당자", "행사일": "행사일",
  "행사명": "행사명", "국": "국", "팀": "팀", "등록자": "등록자", "계산서": "계산서", "사전견적": "사전견적", "견적금액": "견적금액",
  "실행가": "실행가", "수익율": "수익률", "수익률": "수익률" };
const PAYMENT_ALIASES: Record<string, string> = { "내부번호": "내부번호", "번호": "번호", "파트너(페이먼트)": "파트너", "행사명": "행사명",
  "파트너": "파트너", "업체": "파트너", "업체명": "파트너", "등록일": "등록일", "행사일": "행사일", "금액": "금액", "지급요청일": "지급요청일",
  "등록자": "등록자", "팀장승인": "팀장승인", "팀장": "팀장승인", "관리팀승인": "관리팀승인", "관리팀": "관리팀승인", "사장님승인": "사장님승인",
  "사장님": "사장님승인", "대표이사승인": "사장님승인", "지불": "지불" };

const key = (t: string) => t.replace(/[\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000▲▼]+/g, "");
const AMPM = /^(\d{4}-\d{2}-\d{2})[\t\n\x0b\x0c\r ]*(오전|오후)[\t\n\x0b\x0c\r ]*(\d{1,2}):(\d{2})(?::(\d{2}))?$/;
const RANGE = /^[\t\n\x0b\x0c\r ]*(\d{4}-\d{2}-\d{2})[\t\n\x0b\x0c\r ]*~[\t\n\x0b\x0c\r ]*(\d{4}-\d{2}-\d{2})[\t\n\x0b\x0c\r ]*$/;

export function registeredText(text: string): string {
  const t = pyStrip(text || "");
  const m = AMPM.exec(t);
  if (!m) return t;
  const h = (Number(m[3]) % 12) + (m[2] === "오후" ? 12 : 0);
  return `${m[1]} ${String(h).padStart(2, "0")}:${m[4]}:${m[5] || "00"}`;
}

export function eventText(text: string): string {
  const t = pyStrip(text || "");
  const m = RANGE.exec(t);
  return m ? (m[2] as string) : t;
}

export function approvalText(text: string): string {
  const t = pyStrip(text || "");
  if (t.startsWith("수락완료")) return "승인";
  if (t.startsWith("진행중")) return "미승인";
  return t;
}

function readOld(text: string, aliases: Record<string, string>, columns: string[]): Rec[] {
  const rows = parseCsv(text).map((r) => r.cells);
  if (!rows.length) return [];
  const head = (rows[0] as string[]).map((h) => aliases[key(h)] ?? null);
  if (!head.includes("행사명")) throw new Error("머리글에 행사명이 없음");
  const out: Rec[] = [];
  for (const r of rows.slice(1)) {
    if (!r.some((c) => pyStrip(c))) continue;
    const d: Rec = {};
    for (const c of columns) d[c] = "";
    head.forEach((name, i) => {
      if (name && i < r.length && !d[name]) d[name] = pyStrip(r[i] as string);
    });
    if (!d["행사명"]) continue;
    out.push(d);
  }
  return out;
}

function yearOf(name: string): string {
  const m = /(\d{4})/.exec(name);
  return m ? (m[1] as string) : "";
}

/** old_intranet.load */
export function loadOld(files: ConvFiles, collectDir: string): OldData {
  const folder = join(collectDir, OLD_FOLDER);
  const projects: Rec[] = [], payments: Rec[] = [], notes: string[] = [], used: string[] = [];
  const names = listFiles(files, folder).sort((a, b) => cmpStr(yearOf(b), yearOf(a)) || cmpStr(b, a));
  const seenPay = new Set<string>();
  for (const n of names) {
    const kind = PROJECT_RE.test(n) ? "프로젝트" : PAYMENT_RE.test(n) ? "지급요청" : null;
    if (kind === null) continue;
    const year = yearOf(n);
    let rows: Rec[];
    try {
      const text = decodeTextOr(files, join(folder, n));
      if (text === undefined) throw new TypeError("UnicodeDecodeError");
      rows = readOld(text, kind === "프로젝트" ? PROJECT_ALIASES : PAYMENT_ALIASES,
        [...(kind === "프로젝트" ? PROJECT_COLUMNS : [...PAYMENT_COLUMNS, "지불"]), "내부번호"]);
    } catch (e) {
      notes.push(`예전 인트라넷 ${n} 읽지 못함: ${e instanceof TypeError ? e.message : (e as Error).message}`);
      continue;
    }
    let kept = 0;
    for (const d of rows) {
      if (kind === "프로젝트") {
        d["번호"] = "";
        d["pro_num"] = d["내부번호"] ?? "";
        delete d["내부번호"];
        d["행사일"] = eventText(d["행사일"] as string);
        projects.push(d);
      } else {
        let no = `${NO_PREFIX}${year}-${d["번호"] || d["내부번호"] || ""}`;
        if (seenPay.has(no)) no = `${no}-${kept}`;
        seenPay.add(no);
        d["번호"] = no;
        delete d["내부번호"];
        d["등록일"] = registeredText(d["등록일"] as string);
        for (const c of ["팀장승인", "관리팀승인", "사장님승인"]) d[c] = approvalText(d[c] as string);
        payments.push(d);
      }
      kept++;
    }
    used.push(n);
    notes.push(`예전 인트라넷 ${n}: ${kind} ${kept}건`);
  }
  return { projects, payments, notes, files: used };
}
