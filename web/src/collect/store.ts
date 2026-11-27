/** 받은 자료는 본인 크롬 프로필의 브라우저 저장소(IndexedDB)에만 둔다. 서버로 보내지 않는다. */
import type { ForecastRecord } from "../calc/accuracy";
import { checkDoc, docKey, type CollectedDoc } from "./docs";
import type { FolderFile } from "./folder";

export interface Stored {
  key: string;
  savedAt: string;
  doc: CollectedDoc;
  /** 확장이 저장한 파일 이름 ('261031 분개장 자동수집.json'). 이 이름을 받기 전에 저장한 자료에는 없음 (inputs.docFileName 으로 지음). */
  name?: string;
}

const DB = "ceo-report";
const STORE = "docs";
/** 보고마다 남기는 '앞으로 들어오고 나갈 돈' 예상(기준일 하나에 하나). 다음 보고에서 실제와 비교한다. */
const FORECASTS = "forecasts";
/** 불러온 보고 폴더의 파일 (입력/·수집/ 아래). 다시 불러오면 통째로 바뀐다. 열쇠 = path. */
const FOLDER = "folder";
const BACKUP_KIND = "CEO 보고 백업";
export const BACKUP_FORMAT = 3;

/** 판 3: folder 저장소를 더한다. 있던 저장소·자료는 그대로 둔다 (없는 것만 만든다). */
function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(DB, 3);
    r.onupgradeneeded = () => {
      const db = r.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "key" });
      if (!db.objectStoreNames.contains(FORECASTS)) db.createObjectStore(FORECASTS, { keyPath: "asof" });
      if (!db.objectStoreNames.contains(FOLDER)) db.createObjectStore(FOLDER, { keyPath: "path" });
    };
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

async function tx<T>(mode: IDBTransactionMode, run: (s: IDBObjectStore) => IDBRequest<T> | void, store = STORE): Promise<T | undefined> {
  const db = await open();
  try {
    return await new Promise<T | undefined>((resolve, reject) => {
      const t = db.transaction(store, mode);
      const req = run(t.objectStore(store));
      t.oncomplete = () => resolve(req ? req.result : undefined);
      t.onerror = () => reject(t.error);
      t.onabort = () => reject(t.error);
    });
  } finally {
    db.close();
  }
}

/** 같은 열쇠에 이미 더 새로 받은 자료(수집시각이 더 늦음)가 있으면 그대로 둔다. -> 실제로 쓴 수 */
async function putNewer(items: Stored[]): Promise<number> {
  const db = await open();
  try {
    return await new Promise<number>((resolve, reject) => {
      const t = db.transaction(STORE, "readwrite");
      const s = t.objectStore(STORE);
      let wrote = 0;
      for (const it of items) {
        const g = s.get(it.key);
        g.onsuccess = () => {
          const had = g.result as Stored | undefined;
          if (had && String(had.doc.수집시각 ?? "") > String(it.doc.수집시각 ?? "")) return;
          s.put(it);
          wrote++;
        };
      }
      t.oncomplete = () => resolve(wrote);
      t.onerror = () => reject(t.error);
      t.onabort = () => reject(t.error ?? new Error("저장이 중간에 취소됨 (브라우저 저장 공간이 모자랄 수 있음)"));
    });
  } finally {
    db.close();
  }
}

/** names[i] = docs[i] 의 확장 파일 이름 (모르면 비움). */
export async function saveDocs(docs: CollectedDoc[], now = new Date(), names: (string | null | undefined)[] = []): Promise<number> {
  return putNewer(docs.map((doc, i) => {
    const name = names[i];
    return { key: docKey(doc), savedAt: now.toISOString(), doc, ...(name ? { name } : {}) };
  }));
}

export async function listDocs(): Promise<Stored[]> {
  const all = (await tx<Stored[]>("readonly", (s) => s.getAll() as IDBRequest<Stored[]>)) ?? [];
  return all.sort((a, b) => a.key.localeCompare(b.key));
}

export async function clearAll(): Promise<void> {
  await tx("readwrite", (s) => s.clear());
  await tx("readwrite", (s) => s.clear(), FORECASTS);
  await tx("readwrite", (s) => s.clear(), FOLDER);
}

interface FolderRow extends FolderFile { importedAt: string }

/** 보고 폴더를 통째로 바꾼다 (한 번에: 중간에 실패하면 예전 폴더 그대로). importedAt = 불러온 때 (ISO). */
export async function replaceFolder(files: FolderFile[], importedAt = new Date().toISOString()): Promise<void> {
  const db = await open();
  try {
    await new Promise<void>((resolve, reject) => {
      const t = db.transaction(FOLDER, "readwrite");
      const s = t.objectStore(FOLDER);
      s.clear();
      for (const f of files) s.put({ path: f.path, lastModified: f.lastModified, bytes: f.bytes, importedAt } satisfies FolderRow);
      t.oncomplete = () => resolve();
      t.onerror = () => reject(t.error);
      t.onabort = () => reject(t.error ?? new Error("폴더 저장이 중간에 취소됨 (브라우저 저장 공간이 모자랄 수 있음)"));
    });
  } finally {
    db.close();
  }
}

/** 저장된 보고 폴더 (경로 순서)와 불러온 때 (없으면 null). */
export async function loadFolder(): Promise<{ files: FolderFile[]; importedAt: string | null }> {
  const rows = (await tx<FolderRow[]>("readonly", (s) => s.getAll() as IDBRequest<FolderRow[]>, FOLDER)) ?? [];
  rows.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
  return {
    files: rows.map((r) => ({ path: r.path, lastModified: r.lastModified, bytes: new Uint8Array(r.bytes) })),
    importedAt: rows[0]?.importedAt ?? null,
  };
}

export async function saveForecast(rec: ForecastRecord): Promise<void> {
  await tx("readwrite", (s) => s.put(rec), FORECASTS);
}

/** 기준일 순서로 */
export async function listForecasts(): Promise<ForecastRecord[]> {
  const all = (await tx<ForecastRecord[]>("readonly", (s) => s.getAll() as IDBRequest<ForecastRecord[]>, FORECASTS)) ?? [];
  return all.sort((a, b) => (a.asof < b.asof ? -1 : a.asof > b.asof ? 1 : 0));
}

/** 이번 기준일보다 앞선 기록 중 가장 늦은 것 (없으면 null) */
export async function lastForecastBefore(asof: string): Promise<ForecastRecord | null> {
  const earlier = (await listForecasts()).filter((r) => r.asof < asof);
  return earlier[earlier.length - 1] ?? null;
}

const isIso = (x: unknown) => typeof x === "string" && /^\d{4}-\d{2}-\d{2}$/.test(x);
const isNumOrNull = (x: unknown) => x === null || (typeof x === "number" && Number.isFinite(x));
/** 백업에서 온 예상 기록이 계산이 쓰는 모양인지 (줄 하나하나까지) */
const isForecast = (x: unknown): x is ForecastRecord => {
  if (typeof x !== "object" || x === null) return false;
  const r = x as ForecastRecord;
  if (!isIso(r.asof) || !isNumOrNull(r.start) || !Array.isArray(r.rows)) return false;
  return r.rows.every((row) => typeof row === "object" && row !== null && isIso(row.date) &&
    (row.io === "in" || row.io === "out") && isNumOrNull(row.amount) && typeof row.firm === "boolean");
};

function toB64(b: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < b.length; i += 0x8000) bin += String.fromCharCode.apply(null, Array.from(b.subarray(i, i + 0x8000)));
  return btoa(bin);
}

function fromB64(s: string): Uint8Array {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

interface BackupFolder { 불러온때: string | null; 파일: { path: string; lastModified: number; base64: string }[] }

/** 형식 3: 자료(확장 자료, 이름 포함)·예상기록·폴더(불러온 보고 폴더 파일, base64). */
export async function exportBackup(): Promise<Blob> {
  const folder = await loadFolder();
  const 폴더: BackupFolder = { 불러온때: folder.importedAt,
    파일: folder.files.map((f) => ({ path: f.path, lastModified: f.lastModified, base64: toB64(f.bytes) })) };
  const body = { 종류: BACKUP_KIND, 형식: BACKUP_FORMAT, 자료: await listDocs(), 예상기록: await listForecasts(), 폴더 };
  return new Blob([JSON.stringify(body)], { type: "application/json" });
}

/** 백업의 폴더 부분을 검사해 파일로. 틀리면 throw. */
function readBackupFolder(x: unknown): { files: FolderFile[]; importedAt: string } | null {
  if (x === undefined || x === null) return null;
  const bad = () => new Error("백업 안 폴더 자료가 틀림");
  const f = x as BackupFolder;
  if (typeof f !== "object" || !Array.isArray(f.파일)) throw bad();
  const files: FolderFile[] = [];
  for (const it of f.파일) {
    if (typeof it?.path !== "string" || !/^(입력|수집)\/./.test(it.path) || it.path.split("/").includes("..")) throw bad();
    if (typeof it.lastModified !== "number" || !Number.isFinite(it.lastModified) || typeof it.base64 !== "string") throw bad();
    let bytes: Uint8Array;
    try { bytes = fromB64(it.base64); } catch { throw bad(); }
    files.push({ path: it.path, lastModified: it.lastModified, bytes });
  }
  return files.length ? { files, importedAt: typeof f.불러온때 === "string" ? f.불러온때 : "" } : null;
}

/** 백업 파일을 불러온다. 파일 전체가 맞을 때만 바꾼다(하나라도 틀리면 아무것도 바꾸지 않음).
 *  더 새로 받은 같은 자료는 덮지 않는다. -> 실제로 되살린 자료 수 */
export async function importBackup(file: Blob): Promise<number> {
  let body: unknown;
  try {
    body = JSON.parse(await file.text());
  } catch {
    throw new Error("CEO 보고 백업 파일이 아님 (JSON 아님)");
  }
  const b = body as { 종류?: unknown; 형식?: unknown; 자료?: unknown; 예상기록?: unknown; 폴더?: unknown };
  if (b?.종류 !== BACKUP_KIND || !Array.isArray(b.자료)) throw new Error("CEO 보고 백업 파일이 아님");
  if (b.형식 !== undefined && !(typeof b.형식 === "number" && b.형식 >= 1 && b.형식 <= BACKUP_FORMAT && Number.isInteger(b.형식))) {
    throw new Error(`이 화면이 모르는 백업 형식 (${String(b.형식)}) — 사이트를 새로 고친 뒤 다시 불러오세요`);
  }
  if (b.예상기록 !== undefined && !Array.isArray(b.예상기록)) throw new Error("백업 안 예상 기록이 틀림");
  const forecasts = (b.예상기록 as unknown[] | undefined) ?? [];
  for (const f of forecasts) if (!isForecast(f)) throw new Error("백업 안 예상 기록이 틀림");
  const items: Stored[] = [];
  for (const it of b.자료 as Stored[]) {
    const c = checkDoc(it?.doc);
    if (!c.ok) throw new Error(`백업 안 자료가 틀림: ${c.reason}`);
    const name = typeof it.name === "string" && it.name ? it.name : undefined;
    items.push({ key: docKey(c.doc), savedAt: String(it.savedAt ?? ""), doc: c.doc, ...(name ? { name } : {}) });
  }
  const folder = readBackupFolder(b.폴더);
  const n = await putNewer(items);
  // 폴더는 이 크롬에 폴더가 없거나 백업 쪽을 더 늦게 불러왔을 때만 바꾼다 (더 새로 불러온 폴더를 옛 백업이 덮지 않게)
  if (folder) {
    const have = await loadFolder();
    if (!have.files.length || (have.importedAt ?? "") < folder.importedAt) await replaceFolder(folder.files, folder.importedAt);
  }
  // 예상 기록은 이미 있는 기준일은 그대로 둔다(그 기준일에 이 PC에서 만든 것이 더 정확함)
  const have = new Set((await listForecasts()).map((r) => r.asof));
  for (const f of forecasts as ForecastRecord[]) if (!have.has(f.asof)) await saveForecast(f);
  return n;
}
