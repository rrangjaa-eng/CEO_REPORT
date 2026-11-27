// 보고 폴더 불러오기 (수동·엑셀 자료의 길). 사용자가 고른 폴더 안에서 '입력/'·'수집/' 아래만 골라 상대 경로로 바꾼다.
// 폴더는 보고 폴더 자체를 골라도, 그 위(부모) 폴더를 골라도 된다 — 경로 조각에서 '입력'·'수집'을 찾는다.

/** 브라우저 저장소에 두는 폴더 파일 하나. path 는 '입력/…' 또는 '수집/…' (구분자 '/'). lastModified 는 ms. */
export interface FolderFile {
  path: string;
  lastModified: number;
  bytes: Uint8Array;
}

export const ROOTS = ["입력", "수집"] as const;

/** 쓰지 않는 파일: 숨김 파일, 엑셀 잠금 파일(~$), 운영체제가 만드는 파일. */
function junk(name: string): boolean {
  return name.startsWith(".") || name.startsWith("~$") || /^(thumbs\.db|desktop\.ini)$/i.test(name);
}

/** 고른 폴더 안 상대 경로(webkitRelativePath·끌어 놓은 항목 경로) → '입력/…'·'수집/…'. 쓰지 않을 파일이면 null.
 *  - 윈도 구분자 '\' 도 받는다. 맥이 주는 분해형 한글(NFD)은 합친 꼴(NFC)로 바꾼다.
 *  - 경로 조각 중 처음 나오는 '입력' 또는 '수집'부터 쓴다 (부모 폴더를 골라도 됨).
 *  - '입력/이전/' (변환이 옮겨 둔 지난 파일)은 계산에 쓰지 않으므로 넣지 않는다. */
export function mapPickedPath(rel: string): string | null {
  const parts = rel.normalize("NFC").replace(/\\/g, "/").split("/").filter((p) => p !== "" && p !== ".");
  const i = parts.findIndex((p) => (ROOTS as readonly string[]).includes(p));
  if (i < 0) return null;
  const rest = parts.slice(i);
  if (rest.length < 2) return null;
  const name = rest[rest.length - 1] as string;
  if (junk(name) || rest.some((p) => p === "..")) return null;
  if (rest[0] === "입력" && rest[1] === "이전") return null;
  return rest.join("/");
}

/** 고른 경로에서 보고 폴더 자리(입력·수집 바로 위까지). 없으면 null */
function rootOf(rel: string): string | null {
  const parts = rel.normalize("NFC").replace(/\\/g, "/").split("/").filter((p) => p !== "" && p !== ".");
  const i = parts.findIndex((p) => (ROOTS as readonly string[]).includes(p));
  return i < 0 ? null : parts.slice(0, i).join("/");
}

/** 고른 파일들 → 저장할 폴더 파일.
 *  부모 폴더 아래 보고 폴더가 여럿이면(지난달 폴더 등) 섞으면 옛 자료가 들어가므로, 가장 새로 고친 파일이 있는 보고 폴더 하나만 쓴다. */
export async function readPicked(files: Iterable<{ rel: string; file: File }>): Promise<{ files: FolderFile[]; skipped: number; droppedRoots: string[] }> {
  const list = [...files];
  const newestByRoot = new Map<string, number>();
  for (const { rel, file } of list) {
    if (mapPickedPath(rel) === null) continue;
    const r = rootOf(rel) as string;
    newestByRoot.set(r, Math.max(newestByRoot.get(r) ?? -Infinity, file.lastModified));
  }
  const roots = [...newestByRoot.entries()].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1));
  const keep = roots[0]?.[0];
  const by = new Map<string, FolderFile>();
  let skipped = 0;
  for (const { rel, file } of list) {
    const path = mapPickedPath(rel);
    if (path === null) { skipped++; continue; }
    if (rootOf(rel) !== keep) continue;
    const had = by.get(path);
    if (had && had.lastModified >= file.lastModified) continue;
    by.set(path, { path, lastModified: file.lastModified, bytes: new Uint8Array(await file.arrayBuffer()) });
  }
  return { files: [...by.values()].sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0)), skipped,
    droppedRoots: roots.slice(1).map((r) => r[0]).sort() };
}

export interface FolderGroup { folder: string; count: number; newest: number }

/** 무엇을 불러왔는지: 폴더(입력, 수집/위하고, 수집/인트라넷_… 등)마다 파일 수와 가장 늦게 고친 때(ms). */
export function summarize(files: FolderFile[]): FolderGroup[] {
  const by = new Map<string, FolderGroup>();
  for (const f of files) {
    const parts = f.path.split("/");
    const folder = parts[0] === "수집" && parts.length > 2 ? `수집/${parts[1]}` : (parts[0] as string);
    const g = by.get(folder) ?? { folder, count: 0, newest: 0 };
    g.count++;
    g.newest = Math.max(g.newest, f.lastModified);
    by.set(folder, g);
  }
  return [...by.values()].sort((a, b) => (a.folder < b.folder ? -1 : a.folder > b.folder ? 1 : 0));
}
