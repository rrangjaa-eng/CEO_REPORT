import {beforeEach, describe, expect, it} from "vitest";
import {installFakeChrome} from "./fakeChrome";
import {docKey, listDocs, readDocs, storeDoc} from "../src/docs";

describe("docKey", () => {
  it("종류|기간(JSON)|회사", () => {
    const doc = {"종류": "분개장", "기간": {start_date: "20260101", end_date: "20261127"}, "회사": "가나상사"};
    expect(docKey(doc, "261127 분개장 자동수집.json")).toBe('분개장|{"start_date":"20260101","end_date":"20261127"}|가나상사');
  });
  it("기간·회사가 없으면 빈 칸", () => {
    expect(docKey({"종류": "자금계획"}, "x.json")).toBe('자금계획|""|');
  });
  it("종류가 없으면 파일 이름", () => {
    expect(docKey({"상태": "끝"}, "받기상태.txt")).toBe("받기상태.txt");
  });
  it("결산·대조 원본은 화면코드·연도로 나눈다 (종류만으로는 화면끼리 겹침)", () => {
    const a = docKey({"종류": "결산원본", "화면코드": "SACL0105", "연도": 2026}, "a");
    const b = docKey({"종류": "결산원본", "화면코드": "SACL0105", "연도": 2025}, "b");
    const c = docKey({"종류": "결산원본", "화면코드": "SACL0108", "연도": 2026}, "c");
    expect(a).toBe('결산원본|""||SACL0105|2026');
    expect(new Set([a, b, c]).size).toBe(3);
  });
});

describe("storeDoc", () => {
  beforeEach(() => { installFakeChrome(); });

  it("같은 key 는 새 것이 옛 것을 덮는다 (key 마다 하나)", async () => {
    const old = {"종류": "분개장", "기간": {start_date: "20260101"}, "회사": "가", "줄수": 1};
    const neu = {...old, "줄수": 2};
    await storeDoc("261126 분개장 자동수집.json", "2026-11-26 09:00:00", old);
    await storeDoc("261127 분개장 자동수집.json", "2026-11-27 09:00:00", neu);
    const docs = await readDocs();
    expect(Object.keys(docs)).toHaveLength(1);
    const only = Object.values(docs)[0]!;
    expect(only.name).toBe("261127 분개장 자동수집.json");
    expect(only.savedAt).toBe("2026-11-27 09:00:00");
    expect(only.doc["줄수"]).toBe(2);
  });

  it("다른 key 는 따로 두고, 목록은 최근 것부터", async () => {
    await storeDoc("a.json", "2026-11-26 09:00:00", {"종류": "분개장", "회사": "가"});
    await storeDoc("b.json", "2026-11-27 09:00:00", {"종류": "자금계획", "회사": "가"});
    const list = await listDocs();
    expect(list.map((d) => d.name)).toEqual(["b.json", "a.json"]);
  });
});
