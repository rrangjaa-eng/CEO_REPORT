/** 받은 자료는 본인 크롬 프로필의 브라우저 저장소(IndexedDB)에만 둔다. 서버로 보내지 않는다. */
import { checkDoc, docKey, type CollectedDoc } from "./docs";

export interface Stored {
  key: string;
  savedAt: string;
  doc: CollectedDoc;
}

const DB = "ceo-report";
const STORE = "docs";
const BACKUP_KIND = "CEO 보고 백업";

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: "key" });
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

async function tx<T>(mode: IDBTransactionMode, run: (s: IDBObjectStore) => IDBRequest<T> | void): Promise<T | undefined> {
  const db = await open();
  try {
    return await new Promise<T | undefined>((resolve, reject) => {
      const t = db.transaction(STORE, mode);
      const req = run(t.objectStore(STORE));
      t.oncomplete = () => resolve(req ? req.result : undefined);
      t.onerror = () => reject(t.error);
      t.onabort = () => reject(t.error);
    });
  } finally {
    db.close();
  }
}

export async function saveDocs(docs: CollectedDoc[], now = new Date()): Promise<void> {
  const db = await open();
  try {
    await new Promise<void>((resolve, reject) => {
      const t = db.transaction(STORE, "readwrite");
      const s = t.objectStore(STORE);
      for (const doc of docs) s.put({ key: docKey(doc), savedAt: now.toISOString(), doc } satisfies Stored);
      t.oncomplete = () => resolve();
      t.onerror = () => reject(t.error);
    });
  } finally {
    db.close();
  }
}

export async function listDocs(): Promise<Stored[]> {
  const all = (await tx<Stored[]>("readonly", (s) => s.getAll() as IDBRequest<Stored[]>)) ?? [];
  return all.sort((a, b) => a.key.localeCompare(b.key));
}

export async function clearAll(): Promise<void> {
  await tx("readwrite", (s) => s.clear());
}

export async function exportBackup(): Promise<Blob> {
  const body = { 종류: BACKUP_KIND, 형식: 1, 자료: await listDocs() };
  return new Blob([JSON.stringify(body)], { type: "application/json" });
}

/** 백업 파일을 불러온다. 파일 전체가 맞을 때만 바꾼다(하나라도 틀리면 아무것도 바꾸지 않음). -> 불러온 자료 수 */
export async function importBackup(file: Blob): Promise<number> {
  let body: unknown;
  try {
    body = JSON.parse(await file.text());
  } catch {
    throw new Error("CEO 보고 백업 파일이 아님 (JSON 아님)");
  }
  const b = body as { 종류?: unknown; 자료?: unknown };
  if (b?.종류 !== BACKUP_KIND || !Array.isArray(b.자료)) throw new Error("CEO 보고 백업 파일이 아님");
  const items: Stored[] = [];
  for (const it of b.자료 as Stored[]) {
    const c = checkDoc(it?.doc);
    if (!c.ok) throw new Error(`백업 안 자료가 틀림: ${c.reason}`);
    items.push({ key: docKey(c.doc), savedAt: String(it.savedAt ?? ""), doc: c.doc });
  }
  const db = await open();
  try {
    await new Promise<void>((resolve, reject) => {
      const t = db.transaction(STORE, "readwrite");
      const s = t.objectStore(STORE);
      for (const it of items) s.put(it);
      t.oncomplete = () => resolve();
      t.onerror = () => reject(t.error);
    });
  } finally {
    db.close();
  }
  return items.length;
}
