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
}

export async function exportBackup(): Promise<Blob> {
  const body = { 종류: BACKUP_KIND, 형식: 1, 자료: await listDocs() };
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
  const b = body as { 종류?: unknown; 자료?: unknown };
  if (b?.종류 !== BACKUP_KIND || !Array.isArray(b.자료)) throw new Error("CEO 보고 백업 파일이 아님");
  const items: Stored[] = [];
  for (const it of b.자료 as Stored[]) {
    const c = checkDoc(it?.doc);
    if (!c.ok) throw new Error(`백업 안 자료가 틀림: ${c.reason}`);
    items.push({ key: docKey(c.doc), savedAt: String(it.savedAt ?? ""), doc: c.doc });
  }
  return putNewer(items);
}
