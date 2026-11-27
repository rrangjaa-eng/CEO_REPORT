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

/** 고른 파일들 → 저장할 폴더 파일. 같은 경로가 둘이면(부모 폴더 아래 보고 폴더가 둘 등) 더 새로 고친 것. */
export async function readPicked(files: Iterable<{ rel: string; file: File }>): Promise<{ files: FolderFile[]; skipped: number }> {
  const by = new Map<string, FolderFile>();
  let skipped = 0;
  for (const { rel, file } of files) {
    const path = mapPickedPath(rel);
    if (path === null) { skipped++; continue; }
    const had = by.get(path);
    if (had && had.lastModified >= file.lastModified) continue;
    by.set(path, { path, lastModified: file.lastModified, bytes: new Uint8Array(await file.arrayBuffer()) });
  }
  return { files: [...by.values()].sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0)), skipped };
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
