// wehago.read_xlsx: .xlsx 첫 시트(workbook.xml 순서, rels 로 부품 찾기)의 행 목록. 칸은 글자, 빈 칸은 ''.
import { pyIntParse, pyIsDigit, pyStrip } from "../model/py";
import { openZip, ZipError, type ZipReader } from "./zip";
import { XmlError, attr, iterEl, parseXml, xmlText, type XEl } from "./xml";

export const MAX_PART_BYTES = 50 * 1024 * 1024;
export const MAX_COLS = 256;
export const BAD = "엑셀 내부 형식이 예상과 다름";

export class WehagoError extends Error {}

/** read_xlsx 결과: 행 목록 + 날짜 체계. read_journal_xls/json 은 period·company·knownExtra 를 더 둔다. */
export interface Rows {
  rows: string[][];
  date1904: boolean;
  knownExtra?: string[];
  period?: [string, string] | null;
  company?: string;
}

async function part(zf: ZipReader, name: string): Promise<Uint8Array> {
  const size = zf.size(name);
  if (size === undefined) throw new WehagoError(BAD);
  if (size > MAX_PART_BYTES) throw new WehagoError("엑셀 파일이 너무 큼");
  let data: Uint8Array;
  try {
    data = await zf.read(name, MAX_PART_BYTES);
  } catch (e) {
    if (e instanceof ZipError && e.message === "너무 큼") throw new WehagoError("엑셀 파일이 너무 큼");
    throw new WehagoError("엑셀 파일을 열 수 없음");
  }
  // DOCTYPE/ENTITY 검사 (utf-8·utf-16le·utf-16be 바이트로)
  const up = upperAscii(data);
  for (const tag of ["<!DOCTYPE", "<!ENTITY"]) {
    for (const enc of ["utf-8", "utf-16le", "utf-16be"]) {
      if (indexOfBytes(up, encodeAscii(tag, enc)) >= 0) throw new WehagoError(BAD);
    }
  }
  return data;
}

function upperAscii(b: Uint8Array): Uint8Array {
  const out = new Uint8Array(b.length);
  for (let i = 0; i < b.length; i++) {
    const c = b[i]!;
    out[i] = c >= 0x61 && c <= 0x7a ? c - 32 : c;
  }
  return out;
}

function encodeAscii(s: string, enc: string): Uint8Array {
  const w = enc === "utf-8" ? 1 : 2;
  const out = new Uint8Array(s.length * w);
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (w === 1) out[i] = c;
    else if (enc === "utf-16le") out[2 * i] = c;
    else out[2 * i + 1] = c;
  }
  return out;
}

function indexOfBytes(hay: Uint8Array, needle: Uint8Array): number {
  outer: for (let i = 0; i + needle.length <= hay.length; i++) {
    for (let k = 0; k < needle.length; k++) if (hay[i + k] !== needle[k]) continue outer;
    return i;
  }
  return -1;
}

function xml(b: Uint8Array): XEl {
  return parseXml(xmlText(b));
}

function siText(si: XEl): string {
  const parts: string[] = [];
  for (const ch of si.children) {
    if (ch.tag === "t") parts.push(ch.text);
    else if (ch.tag === "r") for (const t of ch.children) if (t.tag === "t") parts.push(t.text);
  }
  return parts.join("");
}

function colIndex(ref: string | undefined): number | null {
  const m = /^([A-Za-z]+)/.exec(ref || "");
  if (!m) return null;
  let n = 0;
  for (const c of (m[1] as string).toUpperCase()) n = n * 26 + c.charCodeAt(0) - 64;
  return n - 1;
}

/** posixpath.normpath (상대 경로만, 'xl/' 로 시작). */
function normpath(p: string): string {
  const out: string[] = [];
  for (const seg of p.split("/")) {
    if (seg === "" || seg === ".") continue;
    if (seg === "..") { if (out.length && out[out.length - 1] !== "..") out.pop(); else out.push(".."); }
    else out.push(seg);
  }
  return out.join("/") || ".";
}

async function sheetRows(zf: ZipReader): Promise<Rows> {
  const wb = xml(await part(zf, "xl/workbook.xml"));
  let date1904 = false;
  let rid: string | undefined;
  for (const el of iterEl(wb)) {
    if (el.tag === "workbookPr") date1904 = ["1", "true"].includes(attr(el, "date1904") ?? "");
    else if (el.tag === "sheet" && rid === undefined) rid = attr(el, "id", true);
  }
  let target: string | undefined;
  for (const el of xml(await part(zf, "xl/_rels/workbook.xml.rels")).children) {
    if (rid !== undefined && attr(el, "Id") === rid) target = attr(el, "Target");
  }
  if (!target) throw new WehagoError(BAD);
  const sheetPart = target.startsWith("/") ? target.replace(/^\/+/, "") : normpath("xl/" + target);
  let shared: string[] = [];
  if (zf.names.includes("xl/sharedStrings.xml")) {
    shared = xml(await part(zf, "xl/sharedStrings.xml")).children.filter((si) => si.tag === "si").map(siText);
  }
  const root = xml(await part(zf, sheetPart));
  const rows: string[][] = [];
  for (const row of iterEl(root)) {
    if (row.tag !== "row") continue;
    if (!rows.length) {
      const first = attr(row, "r");
      if (first && pyIsDigit(first) && Number(first) !== 1) rows.push([]);
    }
    const cells = new Map<number, string>();
    let prev = -1;
    for (const c of row.children) {
      if (c.tag !== "c") continue;
      let col = colIndex(attr(c, "r"));
      col = col === null ? prev + 1 : col;
      prev = col;
      if (col >= MAX_COLS) throw new WehagoError(BAD);
      const kind = attr(c, "t");
      let v = "";
      let inline: string | null = null;
      for (const ch of c.children) {
        if (ch.tag === "v") v = pyStrip(ch.text);
        else if (ch.tag === "is") inline = siText(ch);
      }
      if (kind === "s") {
        const k = pyIntParse(v);
        if (k === null) throw new WehagoError(BAD);
        const idx = k < 0 ? shared.length + k : k;
        if (idx < 0 || idx >= shared.length) throw new WehagoError(BAD);
        v = shared[idx] as string;
      } else if (kind === "inlineStr") v = inline || "";
      else if (kind === "e" || kind === "b") v = "";
      cells.set(col, v);
    }
    const width = cells.size ? Math.max(...cells.keys()) + 1 : 0;
    const out: string[] = [];
    for (let i = 0; i < width; i++) out.push(cells.get(i) ?? "");
    rows.push(out);
  }
  const width = rows.reduce((m, r) => Math.max(m, r.length), 0);
  for (const r of rows) while (r.length < width) r.push("");
  return { rows, date1904 };
}

/** read_xlsx: 실패는 WehagoError (파이썬과 같은 글). */
export async function readXlsx(data: Uint8Array): Promise<Rows> {
  let zf: ZipReader;
  try {
    zf = openZip(data);
  } catch {
    throw new WehagoError("엑셀 파일을 열 수 없음");
  }
  try {
    return await sheetRows(zf);
  } catch (e) {
    if (e instanceof WehagoError) throw e;
    if (e instanceof XmlError) throw new WehagoError(BAD);
    if (e instanceof ZipError) throw new WehagoError("엑셀 파일을 열 수 없음");
    throw new WehagoError(BAD);
  }
}
