// 1.0: 받은 자료(파일로 저장하는 것과 같은 JSON 문서)를 chrome.storage.local 'docs' 에도 둔다.
// 내 사이트(SITE_ORIGIN)가 externally_connectable 로 이 목록을 받아 간다. 같은 key 는 새 것이 옛 것을 덮는다 (key 마다 마지막 하나만).
export type CollectedDoc = Record<string, unknown> & {종류?: unknown; 기간?: unknown; 회사?: unknown; 화면코드?: unknown; 연도?: unknown};
export interface StoredDoc {
  name: string;      // 파일 이름 ('YYMMDD 분개장 자동수집.json')
  savedAt: string;   // 저장한 때 (YYYY-MM-DD HH:MM:SS, 문서의 수집시각과 같음)
  doc: CollectedDoc;
}
export type DocMap = Record<string, StoredDoc>;

export const DOCS_KEY = "docs";

// key = 종류|기간|회사 (종류가 없으면 파일 이름).
// 결산·대조·인사·연말정산 원본은 종류('결산원본' 등)만으로는 화면끼리 겹치므로(기간·회사 칸이 없음) 화면코드·연도를 덧붙인다.
export function docKey(doc: CollectedDoc, name: string): string {
  if (doc.종류 === undefined || doc.종류 === null || doc.종류 === "") return name;
  const base = `${String(doc.종류)}|${JSON.stringify(doc.기간 ?? "")}|${String(doc.회사 ?? "")}`;
  if (doc.화면코드 === undefined) return base;
  return `${base}|${String(doc.화면코드 ?? "")}|${String(doc.연도 ?? "")}`;
}

export async function readDocs(): Promise<DocMap> {
  const got = await chrome.storage.local.get(DOCS_KEY);
  const m = got[DOCS_KEY];
  return m && typeof m === "object" ? (m as DocMap) : {};
}

export async function storeDoc(name: string, savedAt: string, doc: CollectedDoc): Promise<string> {
  const key = docKey(doc, name);
  const docs = await readDocs();
  docs[key] = {name, savedAt, doc};
  await chrome.storage.local.set({[DOCS_KEY]: docs});
  return key;
}

export async function listDocs(): Promise<StoredDoc[]> {
  return Object.values(await readDocs()).sort((a, b) => (a.savedAt < b.savedAt ? 1 : a.savedAt > b.savedAt ? -1 : 0));
}
