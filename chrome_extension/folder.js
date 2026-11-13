// 저장 폴더(F:\CLAUDE\CEO_REPORT\수집\위하고 등) 손잡이를 확장 IndexedDB 에 두고 쓴다 (2026-11-05 사용자 선택: 확장이 그 폴더에 직접 저장).
// 배경(서비스 워커)과 saver.html 이 함께 쓴다.
const FOLDER_DB = "ceoReport", FOLDER_STORE = "kv";

function folderDb() {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(FOLDER_DB, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(FOLDER_STORE);
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

async function idbGet(key) {
  const db = await folderDb();
  return new Promise((resolve, reject) => {
    const q = db.transaction(FOLDER_STORE).objectStore(FOLDER_STORE).get(key);
    q.onsuccess = () => resolve(q.result);
    q.onerror = () => reject(q.error);
  });
}

async function idbSet(key, value) {
  const db = await folderDb();
  return new Promise((resolve, reject) => {
    const t = db.transaction(FOLDER_STORE, "readwrite");
    t.objectStore(FOLDER_STORE).put(value, key);
    t.oncomplete = () => resolve();
    t.onerror = () => reject(t.error);
  });
}

const getFolder = () => idbGet("folder");
const setFolder = (h) => idbSet("folder", h);

// 폴더에 쓴다. -> "ok" | "nofolder" | "need" (허용 다시 필요·쓰기 실패)
async function writeToFolder(name, text, ask = false) {
  const dir = await getFolder();
  if (!dir) return "nofolder";
  try {
    let p = await dir.queryPermission({mode: "readwrite"});
    if (p !== "granted" && ask) p = await dir.requestPermission({mode: "readwrite"});
    if (p !== "granted") return "need";
    const fh = await dir.getFileHandle(name, {create: true});
    const w = await fh.createWritable();
    await w.write(text);
    await w.close();
    return "ok";
  } catch (e) {
    return "need";
  }
}
