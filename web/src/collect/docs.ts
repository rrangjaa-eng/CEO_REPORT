/** 확장이 위하고에서 받아 넘기는 자료 한 벌 (분개장·자금계획·결산 등). 모양은 chrome_extension 이 저장하던 JSON 그대로. */
export interface CollectedDoc {
  종류: string;
  형식?: number;
  수집시각?: string;
  회사?: string;
  기간?: unknown;
  줄수?: number;
  열?: string[];
  줄?: unknown[][];
  [k: string]: unknown;
}

export type Checked = { ok: true; doc: CollectedDoc } | { ok: false; reason: string };

const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);

/** 쓸 수 있는 자료인지 본다. 받다 만 자료는 0원이 아니라 '쓰지 않음'으로 (사용자 규칙: 모르는 값을 0으로 넣지 않음). */
export function checkDoc(raw: unknown): Checked {
  if (!isObj(raw)) return { ok: false, reason: "자료 모양이 아님" };
  if (typeof raw.종류 !== "string" || raw.종류 === "") return { ok: false, reason: "자료 종류가 없음" };
  const rows = raw.줄;
  const cols = raw.열;
  if (rows !== undefined) {
    if (!Array.isArray(rows)) return { ok: false, reason: "줄 목록이 아님" };
    if (typeof raw.줄수 === "number" && raw.줄수 !== rows.length) {
      return { ok: false, reason: `줄 ${raw.줄수}개를 받는다고 적혔는데 ${rows.length}개만 있음 — 받다 만 자료라 쓰지 않음` };
    }
    if (Array.isArray(cols)) {
      for (let i = 0; i < rows.length; i++) {
        const r = rows[i];
        if (!Array.isArray(r) || r.length !== cols.length) {
          return { ok: false, reason: `${i + 1}번째 줄의 칸 수(${Array.isArray(r) ? r.length : 0})가 열 수(${cols.length})와 다름` };
        }
      }
    }
  }
  return { ok: true, doc: raw as CollectedDoc };
}

/** 같은 자료(종류·기간·회사)를 알아보는 열쇠. 확장의 docKey 와 같은 식. */
export function docKey(doc: CollectedDoc): string {
  return `${doc.종류}|${JSON.stringify(doc.기간 ?? "")}|${doc.회사 ?? ""}`;
}
