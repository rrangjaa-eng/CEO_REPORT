import { describe, expect, it } from "vitest";
import { diffPaths, listCases, loadCase } from "./golden";
import { parseCsv } from "../../src/model/csv";

describe("golden 읽기", () => {
  it("사례 목록", () => {
    expect(listCases().length).toBeGreaterThanOrEqual(46);
  });
  it("base: 입력 파일 + 변환 결과로 덮음", () => {
    const g = loadCase("base");
    expect(g.case.asof).toBe("2026-11-02");
    expect(g.files["계좌잔액.csv"]).toBeDefined();
    expect(g.files["계좌잔액.csv"]!.startsWith("﻿")).toBe(false);
    const want = g.expected.convert.files["손익.csv"]!;
    expect(parseCsv(g.files["손익.csv"]!).map((r) => r.cells)).toEqual(want);
    expect(g.files["장부잔액.csv"]).toBeDefined();
    expect(JSON.parse(g.files["확인할것.json"]!)).toEqual(g.expected.convert.json["확인할것.json"]);
    expect(g.expected.weekly?.R).toBeTruthy();
    expect(g.expected.monthly?.R).toBeTruthy();
  });
  it("diffPaths", () => {
    expect(diffPaths({ a: [1, 2], b: "x" }, { a: [1, 2], b: "x" })).toEqual([]);
    expect(diffPaths({ a: [1, 2], b: "x", c: 1 }, { a: [1, 3], b: "y", d: 2 })).toEqual([
      ".a[1]: 기대 2 실제 3", ".b: 기대 \"x\" 실제 \"y\"", ".c: 실제에 없음 (기대 1)", ".d: 기대에 없음 (실제 2)"]);
    expect(diffPaths([1, 2, 3], [1], 1)).toEqual(["$: 길이 기대 3 실제 1"]);
  });
});
