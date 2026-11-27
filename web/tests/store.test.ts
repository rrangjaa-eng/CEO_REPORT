import "fake-indexeddb/auto";
import { beforeEach, describe, expect, it } from "vitest";
import { checkDoc, type CollectedDoc } from "../src/collect/docs";
import { clearAll, exportBackup, importBackup, listDocs, saveDocs } from "../src/collect/store";

const doc = (rows: number, taken = "2026-11-05 10:00:00"): CollectedDoc => {
  const r = checkDoc({ 종류: "자금계획", 형식: 1, 수집시각: taken, 회사: "가상회사", 기간: { from: "20261101" },
    줄수: rows, 열: ["date"], 줄: Array.from({ length: rows }, () => ["20261120"]) });
  if (!r.ok) throw new Error(r.reason);
  return r.doc;
};

describe("store", () => {
  beforeEach(async () => { await clearAll(); });

  it("같은 자료를 다시 받으면 새 것으로 바꾼다", async () => {
    await saveDocs([doc(1, "2026-11-05 10:00:00")]);
    await saveDocs([doc(2, "2026-11-06 10:00:00")]);
    const all = await listDocs();
    expect(all).toHaveLength(1);
    expect(all[0]?.doc.줄수).toBe(2);
  });

  it("백업을 내보내고 지운 뒤 불러오면 그대로 되살아난다", async () => {
    await saveDocs([doc(3)]);
    const before = await listDocs();
    const blob = await exportBackup();
    await clearAll();
    expect(await listDocs()).toHaveLength(0);
    expect(await importBackup(blob)).toBe(1);
    expect(await listDocs()).toEqual(before);
  });

  it("백업 파일이 아니면 아무것도 바꾸지 않는다", async () => {
    await saveDocs([doc(1)]);
    await expect(importBackup(new Blob(["{\"x\":1}"]))).rejects.toThrow("CEO 보고 백업 파일이 아님");
    expect(await listDocs()).toHaveLength(1);
  });
});
