// CSV 읽기: 파이썬 csv.reader(excel 방언, newline="")·util.read_csv·csv.DictReader 를 그대로 흉내 낸다.
import { pyStrip } from "./py";
import { Issues, type Row } from "./util";

/** 입력 폴더의 파일 이름 → 글 (utf-8-sig 또는 cp949 로 이미 디코딩: 맨 앞 BOM 하나는 뗀 상태). */
export type FileSet = Record<string, string>;

export const TITLE_ROWS = 5;

/** StringIO(text, newline="") 의 줄 나누기: \r\n, \r, \n 에서 끊고 끝 글자는 남긴다. */
function splitLines(text: string): string[] {
  const out: string[] = [];
  let i = 0;
  const n = text.length;
  while (i < n) {
    let j = i;
    while (j < n && text[j] !== "\n" && text[j] !== "\r") j++;
    if (j < n) {
      j += text[j] === "\r" && text[j + 1] === "\n" ? 2 : 1;
    }
    out.push(text.slice(i, j));
    i = j;
  }
  return out;
}

const enum St { START_RECORD, START_FIELD, IN_FIELD, IN_QUOTED_FIELD, QUOTE_IN_QUOTED_FIELD, EAT_CRNL }

/** 파이썬 csv.reader: 기록마다 [칸 목록, 그 기록을 다 읽은 뒤의 reader.line_num]. 빈 줄은 []. */
export function parseCsv(text: string): { cells: string[]; lineNum: number }[] {
  const lines = splitLines(text);
  const out: { cells: string[]; lineNum: number }[] = [];
  let li = 0;
  let lineNum = 0;
  while (true) {
    let fields: string[] = [];
    let field = "";
    let fieldLen = 0;
    let st: St = St.START_RECORD;
    const save = () => { fields.push(field); field = ""; fieldLen = 0; };
    const add = (c: string) => { field += c; fieldLen++; };
    const proc = (c: string | null) => {
      // c === null 은 줄 끝(EOL)
      switch (st) {
        case St.START_RECORD:
          if (c === null) return;
          if (c === "\n" || c === "\r") { st = St.EAT_CRNL; return; }
          st = St.START_FIELD;
        // fallthrough
        case St.START_FIELD:
          if (c === "\n" || c === "\r" || c === null) { save(); st = c === null ? St.START_RECORD : St.EAT_CRNL; }
          else if (c === '"') st = St.IN_QUOTED_FIELD;
          else if (c === ",") save();
          else { add(c); st = St.IN_FIELD; }
          return;
        case St.IN_FIELD:
          if (c === "\n" || c === "\r" || c === null) { save(); st = c === null ? St.START_RECORD : St.EAT_CRNL; }
          else if (c === ",") { save(); st = St.START_FIELD; }
          else add(c);
          return;
        case St.IN_QUOTED_FIELD:
          if (c === null) return;
          if (c === '"') st = St.QUOTE_IN_QUOTED_FIELD;
          else add(c);
          return;
        case St.QUOTE_IN_QUOTED_FIELD:
          if (c === '"') { add(c); st = St.IN_QUOTED_FIELD; }
          else if (c === ",") { save(); st = St.START_FIELD; }
          else if (c === "\n" || c === "\r" || c === null) { save(); st = c === null ? St.START_RECORD : St.EAT_CRNL; }
          else { add(c); st = St.IN_FIELD; }
          return;
        case St.EAT_CRNL:
          if (c === "\n" || c === "\r") return;
          if (c === null) { st = St.START_RECORD; return; }
          throw new Error("new-line character seen in unquoted field");
      }
    };
    let eof = false;
    do {
      if (li >= lines.length) {
        if (fieldLen !== 0 || (st as St) === St.IN_QUOTED_FIELD) { save(); eof = true; break; }
        return out;
      }
      const line = lines[li++] as string;
      lineNum++;
      for (const c of line) proc(c);
      proc(null);
    } while ((st as St) !== St.START_RECORD);
    out.push({ cells: fields, lineNum });
    fields = [];
    if (eof) return out;
  }
}

export interface CsvInfo {
  missing?: string[];
  header?: string[];
}

function hasAll(required: readonly string[], cells: readonly string[]): boolean {
  const hs = cells.map((h) => pyStrip(h));
  return required.every((c) => hs.includes(c));
}


/**
 * util.read_csv(path, required, issues, info) — text 가 undefined 면 '파일 없음'.
 * 돌려주는 것: [행 목록, 읽었는가].
 */
export function readCsv(name: string, text: string | undefined, required: readonly string[], issues: Issues,
  info?: CsvInfo): [Row[], boolean] {
  if (info) info.missing = [...required];
  if (text === undefined) {
    issues.add(name, "-", "파일 없음 (이 묶음은 '자료 없음'으로 표시)");
    return [[], false];
  }
  if (text.startsWith("﻿")) text = text.slice(1);
  let records: [number, string[]][] = [];
  let prevEnd = 0;
  for (const { cells, lineNum } of parseCsv(text)) {
    const start = prevEnd + 1;
    prevEnd = lineNum;
    if (cells.length === 0) continue;
    records.push([start, cells]);
  }
  let at = 0;
  const first = records[0];
  if (first && !hasAll(required, first[1])) {
    for (let i = 1; i < Math.min(records.length, TITLE_ROWS + 1); i++) {
      const rec = records[i] as [number, string[]];
      if (hasAll(required, rec[1])) {
        at = i;
        issues.add(name, rec[0], `머리글 위 제목 줄 ${at}줄을 건너뛰고 ${rec[0]}번째 줄을 머리글로 읽음`);
        break;
      }
    }
  }
  const header = records.length ? (records[at] as [number, string[]])[1].map((h) => pyStrip(h)) : [];
  records = records.slice(at + 1);
  const missing = required.filter((c) => !header.includes(c));
  if (info) {
    info.missing = missing;
    info.header = [...header];
  }
  if (missing.length) issues.add(name, 1, "필수 열 없음: " + missing.join(", "));
  const seen = new Set<string>();
  const dups: string[] = [];
  for (const h of header) {
    if (seen.has(h)) continue;
    seen.add(h);
    if (h && header.filter((x) => x === h).length > 1) dups.push(h);
  }
  if (dups.length) {
    const hard = dups.filter((h) => required.includes(h));
    if (hard.length) {
      issues.add(name, 1, `머리글이 두 번 있음: ${hard.join(", ")} — 어느 칸 값을 쓸지 몰라 이 파일을 읽지 않음 (하나를 지우고 다시 저장)`);
      if (info) info.missing = [...hard];
      return [[], false];
    }
    issues.add(name, 1, `머리글이 두 번 있음: ${dups.join(", ")} — 앞 칸 값을 씀`);
  }
  const out: Row[] = [];
  for (const [line, cells] of records) {
    const clean: Record<string, string> = {};
    const n = Math.min(header.length, cells.length);
    for (let i = 0; i < n; i++) {
      const k = header[i] as string;
      if (!Object.prototype.hasOwnProperty.call(clean, k)) clean[k] = pyStrip(cells[i] ?? "");
    }
    for (const k of header.slice(cells.length)) {
      if (!Object.prototype.hasOwnProperty.call(clean, k)) clean[k] = "";
    }
    if (!Object.values(clean).some((v) => v)) continue;
    const row = { ...clean, _line: line, _file: name } as Row;
    // 새 안전장치 (파이썬에 없음): 칸이 머리글보다 많고, 천 단위 쉼표가 칸을 가른 모양('360','100','000')이 보이면
    // 금액에 따옴표 없는 쉼표가 든 줄이다. 값이 한 칸씩 밀렸으므로 이 줄의 숫자는 미확인(null)으로 둔다 (util.num 이 _overflow 를 본다).
    // 적요·비고 같은 글 칸의 쉼표는 숫자 칸을 밀지 않으므로 잡지 않는다.
    if (cells.slice(header.length).some((x) => pyStrip(x ?? "")) && splitNumber(cells)) {
      row._overflow = 1;
      issues.add(name, line, "칸이 머리글보다 많음 (금액에 따옴표 없는 쉼표가 있는지 확인) → 이 줄의 숫자는 미확인으로 처리");
    }
    out.push(row);
  }
  return [out, true];
}

/** 이웃한 두 칸이 '1~3자리 숫자' + '정확히 3자리 숫자' 인가 (천 단위 쉼표로 갈린 금액의 모양). */
function splitNumber(cells: string[]): boolean {
  for (let i = 0; i + 1 < cells.length; i++) {
    if (/^[-(]?\d{1,3}$/.test(pyStrip(cells[i] ?? "")) && /^\d{3}\)?$/.test(pyStrip(cells[i + 1] ?? ""))) return true;
  }
  return false;
}

/** csv.DictReader 한 줄: 칸이 모자라면 null (restval), 남으면 무시 (restkey 는 쓰지 않음). */
export type DictRow = Record<string, string | null>;

/** csv.DictReader(StringIO(text)) — 머리글은 다듬지 않고, 같은 머리글은 뒤 칸이 이긴다. */
export function dictReader(text: string): DictRow[] {
  if (text.startsWith("﻿")) text = text.slice(1);
  const recs = parseCsv(text).map((r) => r.cells);
  if (!recs.length) return [];
  const fieldnames = recs[0] as string[];
  const out: DictRow[] = [];
  for (const row of recs.slice(1)) {
    if (row.length === 0) continue;
    const d: DictRow = {};
    const n = Math.min(fieldnames.length, row.length);
    for (let i = 0; i < n; i++) d[fieldnames[i] as string] = row[i] as string;
    for (const k of fieldnames.slice(row.length)) d[k] = null;
    out.push(d);
  }
  return out;
}

/** 파이썬 csv.writer(QUOTE_MINIMAL, lineterminator="\r\n") 로 쓴 글. */
export function writeCsv(rows: readonly (readonly string[])[]): string {
  let s = "";
  for (const row of rows) {
    if (row.length === 1 && row[0] === "") {
      s += '""\r\n';
      continue;
    }
    s += row.map((f) => (/[",\r\n]/.test(f) ? '"' + f.replace(/"/g, '""') + '"' : f)).join(",") + "\r\n";
  }
  return s;
}

/** util.read_text: UTF-8(BOM 떼기) → CP949 순서로 읽는다. 둘 다 아니면 null. */
export function decodeText(raw: Uint8Array): string | null {
  for (const enc of ["utf-8", "euc-kr"]) {
    try {
      const t = new TextDecoder(enc, { fatal: true, ignoreBOM: true }).decode(raw);
      return enc === "utf-8" && t.startsWith("﻿") ? t.slice(1) : t;
    } catch {
      continue;
    }
  }
  return null;
}
