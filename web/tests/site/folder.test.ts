import { describe, expect, it } from "vitest";
import { mapPickedPath, readPicked, summarize } from "../../src/collect/folder";

describe("폴더 경로 바꾸기", () => {
  it("보고 폴더를 고르면 그 아래 입력/·수집/ 만", () => {
    expect(mapPickedPath("CEO보고/입력/계산서.csv")).toBe("입력/계산서.csv");
    expect(mapPickedPath("CEO보고/수집/위하고/261031 분개장 자동수집.json")).toBe("수집/위하고/261031 분개장 자동수집.json");
    expect(mapPickedPath("CEO보고/수집/인트라넷_20261101_180000/지급요청.csv")).toBe("수집/인트라넷_20261101_180000/지급요청.csv");
    expect(mapPickedPath("CEO보고/출력/보고.html")).toBeNull();
    expect(mapPickedPath("CEO보고/보고서.py")).toBeNull();
  });

  it("부모 폴더를 골라도 경로 조각에서 찾는다", () => {
    expect(mapPickedPath("문서/회사/CEO보고/입력/설정.csv")).toBe("입력/설정.csv");
  });

  it("윈도 구분자와 맥의 분해형 한글(NFD)", () => {
    expect(mapPickedPath("D:\\회사\\CEO보고\\수집\\위하고\\매입매출장_20261031.xlsx")).toBe("수집/위하고/매입매출장_20261031.xlsx");
    const nfd = "CEO보고/입력/계산서.csv".normalize("NFD");
    expect(mapPickedPath(nfd)).toBe("입력/계산서.csv");
  });

  it("숨김·엑셀 잠금 파일, 입력/이전, 폴더 이름만 있는 경로는 뺀다", () => {
    expect(mapPickedPath("보고/입력/.DS_Store")).toBeNull();
    expect(mapPickedPath("보고/수집/위하고/~$매입매출장.xlsx")).toBeNull();
    expect(mapPickedPath("보고/입력/Thumbs.db")).toBeNull();
    expect(mapPickedPath("보고/입력/이전/20261101_120000/손익.csv")).toBeNull();
    expect(mapPickedPath("보고/입력")).toBeNull();
  });

  it("파일을 읽고, 같은 경로가 둘이면 더 새로 고친 것", async () => {
    const f = (text: string, t: number) => new File([text], "x.csv", { lastModified: t });
    const { files, skipped } = await readPicked([
      { rel: "A/입력/설정.csv", file: f("old", 1000) },
      { rel: "B/입력/설정.csv", file: f("new", 2000) },
      { rel: "B/메모.txt", file: f("x", 3000) },
    ]);
    expect(skipped).toBe(1);
    expect(files.map((x) => [x.path, new TextDecoder().decode(x.bytes), x.lastModified])).toEqual([["입력/설정.csv", "new", 2000]]);
  });

  it("폴더마다 개수와 가장 늦게 고친 때", () => {
    const b = new Uint8Array();
    expect(summarize([
      { path: "입력/a.csv", lastModified: 5, bytes: b },
      { path: "입력/b.csv", lastModified: 9, bytes: b },
      { path: "수집/위하고/x.json", lastModified: 7, bytes: b },
      { path: "수집/인트라넷_20261101_180000/y.csv", lastModified: 3, bytes: b },
    ])).toEqual([
      { folder: "수집/위하고", count: 1, newest: 7 },
      { folder: "수집/인트라넷_20261101_180000", count: 1, newest: 3 },
      { folder: "입력", count: 2, newest: 9 },
    ]);
  });
});
