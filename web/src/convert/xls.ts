// xls.py: 예전 엑셀(.xls, BIFF8) 첫 시트를 읽는다. 글자·숫자 칸만, 빈 칸은 ''. 읽을 수 없으면 XlsError.

export class XlsError extends Error {}

export type XlsCell = string | number;   // 글자 | 숫자(파이썬 float)

const MAGIC = [0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1];
const END = 0xfffffffe;
const FREE = 0xffffffff;
export const XLS_MAX_COLS = 256;
export const XLS_MAX_CELLS = 8_000_000;

class StructError extends Error {}

function u8(b: Uint8Array, o: number): number {
  if (o < 0 || o >= b.length) throw new StructError();
  return b[o]!;
}
function u16(b: Uint8Array, o: number): number {
  if (o < 0 || o + 2 > b.length) throw new StructError();
  return b[o]! | (b[o + 1]! << 8);
}
function u32(b: Uint8Array, o: number): number {
  if (o < 0 || o + 4 > b.length) throw new StructError();
  return (b[o]! | (b[o + 1]! << 8) | (b[o + 2]! << 16) | (b[o + 3]! << 24)) >>> 0;
}
function f64(b: Uint8Array, o: number): number {
  if (o < 0 || o + 8 > b.length) throw new StructError();
  return new DataView(b.buffer, b.byteOffset + o, 8).getFloat64(0, true);
}

function concat(parts: Uint8Array[]): Uint8Array {
  const n = parts.reduce((s, p) => s + p.length, 0);
  const out = new Uint8Array(n);
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

function utf16le(b: Uint8Array): string {
  return new TextDecoder("utf-16le", { fatal: true }).decode(b);
}
function latin1(b: Uint8Array): string {
  let s = "";
  for (const c of b) s += String.fromCharCode(c);
  return s;
}

/** CFB(복합 문서)의 스트림 이름 → 바이트. */
function streams(data: Uint8Array): Map<string, Uint8Array> {
  if (data.length < 512 || MAGIC.some((m, i) => data[i] !== m)) throw new XlsError("엑셀(.xls) 파일이 아님");
  const ssz = 1 << u16(data, 30);
  const msz = 1 << u16(data, 32);
  const nFat = u32(data, 44), dirStart = u32(data, 48);
  const cutoff = u32(data, 56), mfatStart = u32(data, 60), nMfat = u32(data, 64), difatStart = u32(data, 68), nDifat = u32(data, 72);
  const sector = (i: number): Uint8Array => {
    const off = ssz === 512 ? 512 + i * ssz : ssz * (i + 1);
    if (off + ssz > data.length + ssz) throw new XlsError("파일이 잘렸음");
    return data.subarray(off, off + ssz);
  };
  const ints = (s: Uint8Array): number[] => {
    if (s.length < ssz) throw new StructError();
    const out: number[] = [];
    for (let k = 0; k < ssz / 4; k++) out.push(u32(s, 4 * k));
    return out;
  };
  const difat: number[] = [];
  for (let k = 0; k < 109; k++) difat.push(u32(data, 76 + 4 * k));
  let nxt = difatStart, seen = 0;
  while (nxt !== END && nxt !== FREE && seen < nDifat) {
    const vals = ints(sector(nxt));
    difat.push(...vals.slice(0, -1));
    nxt = vals[vals.length - 1] as number;
    seen++;
  }
  const fat: number[] = [];
  for (const i of difat.slice(0, nFat)) fat.push(...ints(sector(i)));
  const chain = (start: number, table: number[], limit: number): number[] => {
    const out: number[] = [];
    let i = start, guard = 0;
    while (i !== END && i !== FREE) {
      if (i >= table.length || guard > limit) throw new XlsError("파일 구조가 깨졌음");
      out.push(i);
      i = table[i] as number;
      guard++;
    }
    return out;
  };
  const read = (start: number, size: number) => concat(chain(start, fat, fat.length).map(sector)).subarray(0, size);
  const dirBytes = concat(chain(dirStart, fat, fat.length).map(sector));
  const entries: [string, number, number, number][] = [];
  for (let off = 0; off < dirBytes.length - 127; off += 128) {
    const e = dirBytes.subarray(off, off + 128);
    const nlen = u16(e, 64);
    let name: string;
    try {
      name = new TextDecoder("utf-16le").decode(e.subarray(0, Math.max(nlen - 2, 0)));
    } catch {
      name = "";
    }
    entries.push([name, u8(e, 66), u32(e, 116), u32(e, 120)]);
  }
  if (!entries.length || entries[0]![1] !== 5) throw new XlsError("파일 구조가 깨졌음");
  const root = entries[0]!;
  const mini = root[2] !== END && root[2] !== FREE ? read(root[2], root[3]) : new Uint8Array(0);
  const mfat: number[] = [];
  if (nMfat && mfatStart !== END && mfatStart !== FREE) {
    for (const i of chain(mfatStart, fat, fat.length)) mfat.push(...ints(sector(i)));
  }
  const out = new Map<string, Uint8Array>();
  for (const [name, etype, start, size] of entries.slice(1)) {
    if (etype !== 2) continue;
    if (size < cutoff) {
      const b = size ? concat(chain(start, mfat, mfat.length).map((i) => mini.subarray(i * msz, (i + 1) * msz))) : new Uint8Array(0);
      out.set(name, b.subarray(0, size));
    } else out.set(name, read(start, size));
  }
  return out;
}

function* records(wb: Uint8Array, pos = 0): Generator<[number, number, Uint8Array]> {
  const n = wb.length;
  while (pos + 4 <= n) {
    const rid = u16(wb, pos), ln = u16(wb, pos + 2);
    yield [pos, rid, wb.subarray(pos + 4, pos + 4 + ln)];
    pos += 4 + ln;
  }
}

class Chunks {
  i = 0;
  p = 0;
  constructor(private chunks: Uint8Array[]) {}
  private ensure(): void {
    while (this.i < this.chunks.length && this.p >= this.chunks[this.i]!.length) { this.i++; this.p = 0; }
    if (this.i >= this.chunks.length) throw new XlsError("글자 표가 잘렸음");
  }
  take(n: number): Uint8Array {
    const parts: Uint8Array[] = [];
    while (n) {
      this.ensure();
      const c = this.chunks[this.i]!;
      const k = Math.min(n, c.length - this.p);
      parts.push(c.subarray(this.p, this.p + k));
      this.p += k;
      n -= k;
    }
    return concat(parts);
  }
  chars(cch: number, high: number): string {
    const parts: string[] = [];
    while (cch) {
      if (this.i < this.chunks.length && this.p >= this.chunks[this.i]!.length) {
        this.i++;
        this.p = 0;
        this.ensure();
        high = this.chunks[this.i]![this.p]! & 1;
        this.p++;
      }
      this.ensure();
      const c = this.chunks[this.i]!;
      const width = high ? 2 : 1;
      const k = Math.min(cch, Math.floor((c.length - this.p) / width));
      if (k === 0) throw new XlsError("글자 표가 깨졌음");
      const raw = c.subarray(this.p, this.p + k * width);
      parts.push(high ? utf16le(raw) : latin1(raw));
      this.p += k * width;
      cch -= k;
    }
    return parts.join("");
  }
}

function sst(chunks: Uint8Array[]): string[] {
  const r = new Chunks(chunks);
  const head = r.take(8);
  const uniq = u32(head, 4);
  const out: string[] = [];
  for (let k = 0; k < uniq; k++) {
    const cch = u16(r.take(2), 0);
    const flags = r.take(1)[0]!;
    const runs = flags & 8 ? u16(r.take(2), 0) : 0;
    const ext = flags & 4 ? u32(r.take(4), 0) : 0;
    out.push(r.chars(cch, flags & 1));
    if (runs) r.take(4 * runs);
    if (ext) r.take(ext);
  }
  return out;
}

function unicode(b: Uint8Array, off: number, lenBytes = 2): string {
  const cch = lenBytes === 2 ? u16(b, off) : u8(b, off);
  off += lenBytes;
  const flags = u8(b, off);
  off += 1;
  if (flags & 8) off += 2;
  if (flags & 4) off += 4;
  if (flags & 1) return utf16le(b.subarray(off, off + 2 * cch));
  return latin1(b.subarray(off, off + cch));
}

function rk(v: number): number {
  let x: number;
  if (v & 2) {
    let i = v >>> 2;
    if (i & 0x20000000) i -= 0x40000000;
    x = i;
  } else {
    const buf = new DataView(new ArrayBuffer(8));
    buf.setUint32(0, 0, true);
    buf.setUint32(4, (v & 0xfffffffc) >>> 0, true);
    x = buf.getFloat64(0, true);
  }
  return v & 1 ? x / 100 : x;
}

/** read_xls: 첫 시트 칸 → 행 목록 (글자·숫자·빈 칸 ''). */
export function readXls(data: Uint8Array): XlsCell[][] {
  let st: Map<string, Uint8Array>;
  try {
    st = streams(data);
  } catch (e) {
    if (e instanceof XlsError) throw e;
    throw new XlsError("파일 구조가 깨졌음");
  }
  const wb = st.get("Workbook") ?? st.get("Book");
  if (wb === undefined) throw new XlsError("엑셀 통합 문서가 아님");
  try {
    return firstSheet(wb);
  } catch (e) {
    if (e instanceof XlsError) throw e;
    throw new XlsError("엑셀 내용을 읽을 수 없음");
  }
}

function firstSheet(wb: Uint8Array): XlsCell[][] {
  let strings: string[] = [];
  let sheetPos: number | null = null;
  let chunks: Uint8Array[] | null = null;
  for (const [pos, rid, body] of records(wb)) {
    if (pos === 0 && (rid !== 0x809 || u16(body, 0) !== 0x600)) throw new XlsError("BIFF8 형식이 아님 (엑셀 97 이후 .xls 만 읽음)");
    if (chunks !== null && rid !== 0x3c) { strings = sst(chunks); chunks = null; }
    if (rid === 0xfc) chunks = [body];
    else if (rid === 0x3c && chunks !== null) chunks.push(body);
    else if (rid === 0x85 && sheetPos === null && u8(body, 5) === 0) sheetPos = u32(body, 0);
    else if (rid === 0x0a) break;
  }
  if (chunks !== null) strings = sst(chunks);
  if (sheetPos === null) throw new XlsError("시트가 없음");
  const cells = new Map<string, XlsCell>();
  let maxR = -1, maxC = -1;
  const put = (r: number, c: number, v: XlsCell) => {
    cells.set(r + "," + c, v);
    if (r > maxR) maxR = r;
    if (c > maxC) maxC = c;
  };
  let pending: [number, number] | null = null;
  for (const [, rid, body] of records(wb, sheetPos)) {
    if (rid === 0x0a) break;
    if (rid === 0xfd) {
      const r = u16(body, 0), c = u16(body, 2), i = u32(body, 6);
      put(r, c, i < strings.length ? (strings[i] as string) : "");
    } else if (rid === 0x204) {
      put(u16(body, 0), u16(body, 2), unicode(body, 6));
    } else if (rid === 0x203) {
      put(u16(body, 0), u16(body, 2), f64(body, 6));
    } else if (rid === 0x27e) {
      put(u16(body, 0), u16(body, 2), rk(u32(body, 6)));
    } else if (rid === 0xbd) {
      const r = u16(body, 0), c0 = u16(body, 2);
      const n = Math.floor((body.length - 6) / 6);
      for (let k = 0; k < n; k++) put(r, c0 + k, rk(u32(body, 4 + 6 * k + 2)));
    } else if (rid === 0x06) {
      const r = u16(body, 0), c = u16(body, 2);
      if (body.length < 14) throw new StructError();
      const res = body.subarray(6, 14);
      if (res[6] === 0xff && res[7] === 0xff) {
        pending = res[0] === 0 ? [r, c] : null;
        if (res[0] === 1) put(r, c, res[2]!);
      } else put(r, c, f64(body, 6));
    } else if (rid === 0x207 && pending !== null) {
      put(pending[0], pending[1], unicode(body, 0));
      pending = null;
    }
  }
  if (!cells.size) return [];
  const nrows = maxR + 1, ncols = maxC + 1;
  if (ncols > XLS_MAX_COLS || nrows * ncols > XLS_MAX_CELLS) {
    throw new XlsError(`표가 지나치게 큼 (${nrows}행 × ${ncols}열) — 엑셀에서 열어 확인하세요`);
  }
  const out: XlsCell[][] = [];
  for (let r = 0; r < nrows; r++) {
    const row: XlsCell[] = [];
    for (let c = 0; c < ncols; c++) row.push(cells.get(r + "," + c) ?? "");
    out.push(row);
  }
  return out;
}

/** 파이썬 repr(float) 과 같은 글자 (가장 짧은 표현, 지수 표기 규칙도 파이썬과 같게). */
export function pyReprFloat(v: number): string {
  if (Number.isNaN(v)) return "nan";
  if (!Number.isFinite(v)) return v > 0 ? "inf" : "-inf";
  if (v === 0) return Object.is(v, -0) ? "-0.0" : "0.0";
  const e = v.toExponential();   // 가장 짧은 자릿수
  const [mant, expS] = e.split("e") as [string, string];
  const exp = Number(expS);
  const digits = mant.replace("-", "").replace(".", "");
  const neg = v < 0 ? "-" : "";
  if (exp < -4 || exp >= 16) {
    const m = digits.length > 1 ? digits[0] + "." + digits.slice(1) : digits;
    return neg + m + "e" + (exp < 0 ? "-" : "+") + String(Math.abs(exp)).padStart(2, "0");
  }
  if (exp < 0) return neg + "0." + "0".repeat(-exp - 1) + digits;
  if (digits.length <= exp + 1) return neg + digits + "0".repeat(exp + 1 - digits.length) + ".0";
  return neg + digits.slice(0, exp + 1) + "." + digits.slice(exp + 1);
}
