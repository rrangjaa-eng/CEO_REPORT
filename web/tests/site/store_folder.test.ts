import "fake-indexeddb/auto";
import { beforeEach, describe, expect, it } from "vitest";
import { checkDoc, type CollectedDoc } from "../../src/collect/docs";
import type { FolderFile } from "../../src/collect/folder";
import { clearAll, exportBackup, importBackup, listDocs, listForecasts, loadFolder, replaceFolder, saveDocs } from "../../src/collect/store";

const doc = (taken = "2026-11-05 10:00:00"): CollectedDoc => {
  const r = checkDoc({ 종류: "자금계획", 형식: 1, 수집시각: taken, 회사: "가상회사", 기간: { from: "20261101" }, 줄수: 1, 열: ["date"], 줄: [["20261120"]] });
  if (!r.ok) throw new Error(r.reason);
  return r.doc;
};
const ff = (path: string, text: string, t = 1000): FolderFile => ({ path, lastModified: t, bytes: new TextEncoder().encode(text) });
const text = (f: FolderFile) => new TextDecoder().decode(f.bytes);

describe("보고 폴더 저장", () => {
  beforeEach(async () => { await clearAll(); });

  it("저장하고 그대로 읽는다 (바이트·경로·수정 시각·불러온 때)", async () => {
    const bin = new Uint8Array([0, 255, 1, 128]);
    await replaceFolder([ff("입력/설정.csv", "항목,값"), { path: "수집/위하고/a.xlsx", lastModified: 5, bytes: bin }], "2026-11-27T01:00:00.000Z");
    const got = await loadFolder();
    expect(got.importedAt).toBe("2026-11-27T01:00:00.000Z");
    expect(got.files.map((f) => f.path)).toEqual(["수집/위하고/a.xlsx", "입력/설정.csv"]);
    expect([...got.files[0]!.bytes]).toEqual([0, 255, 1, 128]);
    expect(text(got.files[1]!)).toBe("항목,값");
  });

  it("다시 불러오면 예전 폴더는 통째로 바뀐다", async () => {
    await replaceFolder([ff("입력/a.csv", "1"), ff("입력/b.csv", "2")]);
    await replaceFolder([ff("입력/c.csv", "3")]);
    expect((await loadFolder()).files.map((f) => f.path)).toEqual(["입력/c.csv"]);
  });

  it("확장 파일 이름을 같이 둔다", async () => {
    await saveDocs([doc()], new Date(), ["261105 자금계획 자동수집.json"]);
    expect((await listDocs())[0]?.name).toBe("261105 자금계획 자동수집.json");
  });
});

describe("백업 형식 3", () => {
  beforeEach(async () => { await clearAll(); });

  it("자료(이름 포함)·폴더가 그대로 되살아난다", async () => {
    await saveDocs([doc()], new Date(), ["261105 자금계획 자동수집.json"]);
    await replaceFolder([ff("입력/설정.csv", "항목,값\n회사명,가"), { path: "수집/위하고/x.xls", lastModified: 7, bytes: new Uint8Array(70000).fill(200) }], "2026-11-27T01:00:00.000Z");
    const docs = await listDocs();
    const folder = await loadFolder();
    const b = await exportBackup();
    const body = JSON.parse(await b.text());
    expect(body.형식).toBe(3);
    await clearAll();
    expect(await importBackup(b)).toBe(1);
    expect(await listDocs()).toEqual(docs);
    expect(await loadFolder()).toEqual(folder);
  });

  it("더 늦게 불러온 폴더는 옛 백업이 덮지 않는다", async () => {
    await replaceFolder([ff("입력/a.csv", "옛것")], "2026-11-01T00:00:00.000Z");
    const old = await exportBackup();
    await replaceFolder([ff("입력/a.csv", "새것")], "2026-11-20T00:00:00.000Z");
    await importBackup(old);
    expect(text((await loadFolder()).files[0]!)).toBe("새것");
  });

  it("폴더 안 경로가 틀리면 통째로 거절 (아무것도 바꾸지 않음)", async () => {
    const bad = new Blob([JSON.stringify({ 종류: "CEO 보고 백업", 형식: 3, 자료: [{ savedAt: "", doc: doc() }],
      폴더: { 불러온때: "2026-11-27T00:00:00.000Z", 파일: [{ path: "../밖/a.csv", lastModified: 1, base64: "" }] } })]);
    await expect(importBackup(bad)).rejects.toThrow("폴더");
    expect(await listDocs()).toEqual([]);
  });

  it("모르는 형식(4 이상)은 거절", async () => {
    await expect(importBackup(new Blob([JSON.stringify({ 종류: "CEO 보고 백업", 형식: 4, 자료: [] })]))).rejects.toThrow("형식");
  });

  it("형식 1 (자료만)과 형식 2 (자료+예상기록)도 받는다", async () => {
    const v1 = new Blob([JSON.stringify({ 종류: "CEO 보고 백업", 형식: 1, 자료: [{ key: "x", savedAt: "s", doc: doc("2026-11-01 00:00:00") }] })]);
    expect(await importBackup(v1)).toBe(1);
    expect((await listDocs())[0]?.name).toBeUndefined();
    expect((await loadFolder()).files).toEqual([]);
    const v2 = new Blob([JSON.stringify({ 종류: "CEO 보고 백업", 형식: 2, 자료: [{ key: "x", savedAt: "s", doc: doc("2026-11-03 00:00:00") }],
      예상기록: [{ asof: "2026-11-02", start: 1, rows: [] }] })]);
    expect(await importBackup(v2)).toBe(1);
    expect((await listDocs())[0]?.doc.수집시각).toBe("2026-11-03 00:00:00");
    expect((await listForecasts()).map((r) => r.asof)).toEqual(["2026-11-02"]);
  });
});
