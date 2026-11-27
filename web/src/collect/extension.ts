/** 수집 확장에서 자료 받기. 확장은 이 사이트 주소에만 답한다(externally_connectable). 같은 크롬 안에서만 오가고 인터넷으로 나가지 않는다. */
export const EXTENSION_ID = "dodaoiliemfamcfhmloenbkcepgpjdac";

export interface FromExtension {
  name: string;
  savedAt: string;
  doc: unknown;
}

export async function fetchFromExtension(extId = EXTENSION_ID): Promise<{ version: string; items: FromExtension[] }> {
  const rt = (globalThis as { chrome?: typeof chrome }).chrome?.runtime;
  if (!rt?.sendMessage) {
    throw new Error("이 크롬에 '대표보고 위하고 수집' 확장(1.0)이 없거나 꺼져 있습니다");
  }
  const reply = await new Promise<unknown>((resolve, reject) => {
    rt.sendMessage(extId, { type: "list" }, (r: unknown) => {
      const err = rt.lastError;
      if (err) reject(new Error("확장과 연결하지 못함: " + (err.message ?? "알 수 없음")));
      else resolve(r);
    });
  });
  const r = reply as { ok?: boolean; error?: string; version?: string; docs?: FromExtension[] };
  if (!r?.ok) throw new Error("확장이 자료를 주지 않음: " + (r?.error ?? "응답 없음"));
  return { version: String(r.version ?? ""), items: Array.isArray(r.docs) ? r.docs : [] };
}
