// .xlsx(zip) 풀기: 중앙 디렉터리를 읽고 부품을 꺼낸다. 압축은 저장(0)·deflate(8)만 (엑셀이 쓰는 것).
// 풀기는 플랫폼 DecompressionStream('deflate-raw') (브라우저·Node 22 모두 있음). 디스크에 풀지 않는다.

export class ZipError extends Error {}

interface Entry { name: string; method: number; csize: number; usize: number; local: number }

function u16(b: Uint8Array, o: number): number {
  if (o + 2 > b.length) throw new ZipError("잘린 zip");
  return b[o]! | (b[o + 1]! << 8);
}
function u32(b: Uint8Array, o: number): number {
  if (o + 4 > b.length) throw new ZipError("잘린 zip");
  return (b[o]! | (b[o + 1]! << 8) | (b[o + 2]! << 16) | (b[o + 3]! << 24)) >>> 0;
}

/** 중앙 디렉터리 항목들. zip 이 아니거나 깨졌으면 ZipError. */
export function zipEntries(b: Uint8Array): Entry[] {
  let eocd = -1;
  for (let i = b.length - 22; i >= Math.max(0, b.length - 22 - 65535); i--) {
    if (b[i] === 0x50 && b[i + 1] === 0x4b && b[i + 2] === 0x05 && b[i + 3] === 0x06) { eocd = i; break; }
  }
  if (eocd < 0) throw new ZipError("zip 아님");
  const n = u16(b, eocd + 10);
  let p = u32(b, eocd + 16);
  const out: Entry[] = [];
  const dec = new TextDecoder("utf-8");
  for (let k = 0; k < n; k++) {
    if (u32(b, p) !== 0x02014b50) throw new ZipError("중앙 디렉터리 깨짐");
    const method = u16(b, p + 10);
    const csize = u32(b, p + 20), usize = u32(b, p + 24);
    const nlen = u16(b, p + 28), elen = u16(b, p + 30), clen = u16(b, p + 32);
    const local = u32(b, p + 42);
    if (p + 46 + nlen > b.length) throw new ZipError("잘린 zip");
    const name = dec.decode(b.subarray(p + 46, p + 46 + nlen));
    out.push({ name, method, csize, usize, local });
    p += 46 + nlen + elen + clen;
  }
  return out;
}

async function inflateRaw(data: Uint8Array, limit: number): Promise<Uint8Array> {
  const ds = new DecompressionStream("deflate-raw");
  const writer = ds.writable.getWriter();
  const done = writer.write(data as unknown as BufferSource).then(() => writer.close()).catch(() => undefined);
  const reader = ds.readable.getReader();
  const parts: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { value, done: end } = await reader.read();
    if (end) break;
    total += value.length;
    if (total > limit) {
      await reader.cancel().catch(() => undefined);
      throw new ZipError("너무 큼");
    }
    parts.push(value);
  }
  await done;
  const out = new Uint8Array(total);
  let o = 0;
  for (const x of parts) { out.set(x, o); o += x.length; }
  return out;
}

export interface ZipReader {
  names: string[];
  /** 부품 크기(풀린 크기, 중앙 디렉터리 값). 없으면 undefined. */
  size(name: string): number | undefined;
  /** 부품 하나 풀기. 없으면 ZipError('없음'), limit 보다 크면 ZipError('너무 큼'), 풀기 실패는 ZipError('압축 풀기 실패'). */
  read(name: string, limit: number): Promise<Uint8Array>;
}

/** zip 열기 (부품은 필요할 때 푼다: 파이썬 zipfile 처럼 쓰지 않는 부품이 깨져도 상관없음). */
export function openZip(b: Uint8Array): ZipReader {
  const entries = new Map<string, Entry>();
  for (const e of zipEntries(b)) entries.set(e.name, e);   // 같은 이름은 뒤 항목 (zipfile.getinfo 와 같음)
  return {
    names: [...entries.keys()],
    size: (name) => entries.get(name)?.usize,
    async read(name, limit) {
      const e = entries.get(name);
      if (!e) throw new ZipError("없음");
      if (u32(b, e.local) !== 0x04034b50) throw new ZipError("로컬 머리 깨짐");
      const nlen = u16(b, e.local + 26), elen = u16(b, e.local + 28);
      const start = e.local + 30 + nlen + elen;
      if (start + e.csize > b.length) throw new ZipError("잘린 zip");
      const raw = b.subarray(start, start + e.csize);
      if (e.method === 0) {
        if (raw.length > limit) throw new ZipError("너무 큼");
        return raw.slice();
      }
      if (e.method !== 8) throw new ZipError("모르는 압축 방식");
      try {
        return await inflateRaw(raw, limit);
      } catch (err) {
        if (err instanceof ZipError) throw err;
        throw new ZipError("압축 풀기 실패");
      }
    },
  };
}
