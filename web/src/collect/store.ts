/** 받은 자료는 본인 크롬 프로필의 브라우저 저장소(IndexedDB)에만 둔다. 서버로 보내지 않는다. */
import type { ForecastRecord } from "../calc/accuracy";
import { checkDoc, docKey, type CollectedDoc } from "./docs";

export interface Stored {
  key: string;
  savedAt: string;
  doc: CollectedDoc;
}

const DB = "ceo-report";
const STORE = "docs";
/** 보고마다 남기는 '앞으로 들어오고 나갈 돈' 예상(기준일 하나에 하나). 다음 보고에서 실제와 비교한다. */
const FORECASTS = "forecasts";
const BACKUP_KIND = "CEO 보고 백업";

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(DB, 2);
    r.onupgradeneeded = () => {
      const db = r.result;
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "key" });
      if (!db.objectStoreNames.contains(FORECASTS)) db.createObjectStore(FORECASTS, { keyPath: "asof" });
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

export async function saveDocs(docs: CollectedDoc[], now = new Date()): Promise<number> {
  return putNewer(docs.map((doc) => ({ key: docKey(doc), savedAt: now.toISOString(), doc })));
}

export async function listDocs(): Promise<Stored[]> {
  const all = (await tx<Stored[]>("readonly", (s) => s.getAll() as IDBRequest<Stored[]>)) ?? [];
  return all.sort((a, b) => a.key.localeCompare(b.key));
}

export async function clearAll(): Promise<void> {
  await tx("readwrite", (s) => s.clear());
  await tx("readwrite", (s) => s.clear(), FORECASTS);
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

export async function exportBackup(): Promise<Blob> {
  const body = { 종류: BACKUP_KIND, 형식: 2, 자료: await listDocs(), 예상기록: await listForecasts() };
  return new Blob([JSON.stringify(body)], { type: "application/json" });
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
  const b = body as { 종류?: unknown; 자료?: unknown; 예상기록?: unknown };
  if (b?.종류 !== BACKUP_KIND || !Array.isArray(b.자료)) throw new Error("CEO 보고 백업 파일이 아님");
  if (b.예상기록 !== undefined && !Array.isArray(b.예상기록)) throw new Error("백업 안 예상 기록이 틀림");
  const forecasts = (b.예상기록 as unknown[] | undefined) ?? [];
  for (const f of forecasts) if (!isForecast(f)) throw new Error("백업 안 예상 기록이 틀림");
  const items: Stored[] = [];
  for (const it of b.자료 as Stored[]) {
    const c = checkDoc(it?.doc);
    if (!c.ok) throw new Error(`백업 안 자료가 틀림: ${c.reason}`);
    items.push({ key: docKey(c.doc), savedAt: String(it.savedAt ?? ""), doc: c.doc });
  }
  const n = await putNewer(items);
  // 예상 기록은 이미 있는 기준일은 그대로 둔다(그 기준일에 이 PC에서 만든 것이 더 정확함)
  const have = new Set((await listForecasts()).map((r) => r.asof));
  for (const f of forecasts as ForecastRecord[]) if (!have.has(f.asof)) await saveForecast(f);
  return n;
}
