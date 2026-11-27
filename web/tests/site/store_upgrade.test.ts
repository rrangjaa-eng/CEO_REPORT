// 판 2 DB(자료·예상기록만)가 있는 크롬에서 판 3을 열면 있던 자료는 그대로이고 폴더 저장소만 생긴다.
import "fake-indexeddb/auto";
import { describe, expect, it } from "vitest";
import { listDocs, listForecasts, loadFolder, replaceFolder } from "../../src/collect/store";

function makeV2(): Promise<void> {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open("ceo-report", 2);
    r.onupgradeneeded = () => {
      const db = r.result;
      db.createObjectStore("docs", { keyPath: "key" }).put({ key: "k", savedAt: "s", doc: { 종류: "자금계획", 수집시각: "2026-11-01 00:00:00" } });
      db.createObjectStore("forecasts", { keyPath: "asof" }).put({ asof: "2026-11-02", start: 5, rows: [] });
    };
    r.onsuccess = () => { r.result.close(); resolve(); };
    r.onerror = () => reject(r.error);
  });
}

describe("DB 판 2 → 3", () => {
  it("있던 자료·예상기록을 지키고 폴더 저장소를 더한다", async () => {
    await makeV2();
    expect((await listDocs()).map((d) => d.key)).toEqual(["k"]);
    expect((await listForecasts()).map((f) => f.start)).toEqual([5]);
    expect((await loadFolder()).files).toEqual([]);
    await replaceFolder([{ path: "입력/a.csv", lastModified: 1, bytes: new Uint8Array([65]) }]);
    expect((await loadFolder()).files).toHaveLength(1);
    expect((await listDocs()).map((d) => d.key)).toEqual(["k"]);
  });
});
