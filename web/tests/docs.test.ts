import { describe, expect, it } from "vitest";
import { checkDoc, docKey } from "../src/collect/docs";

const journal = (rows: number, said = rows) => ({
  종류: "분개장", 형식: 1, 수집시각: "2026-11-05 10:00:00", 회사: "가상회사",
  기간: { start_date: "20260101", end_date: "20261031" }, 줄수: said,
  열: ["da_date", "mn_bungae1"], 줄: Array.from({ length: rows }, (_, i) => ["20261001", i]),
});

describe("checkDoc", () => {
  it("받은 자료를 그대로 받아들인다", () => {
    const r = checkDoc(journal(3));
    expect(r.ok).toBe(true);
  });
  it("받다 만 자료(줄수와 실제 줄이 다름)는 쓰지 않는다", () => {
    const r = checkDoc(journal(58, 60));
    expect(r).toEqual({ ok: false, reason: "줄 60개를 받는다고 적혔는데 58개만 있음 — 받다 만 자료라 쓰지 않음" });
  });
  it("종류가 없으면 쓰지 않는다", () => {
    expect(checkDoc({ 줄: [] }).ok).toBe(false);
    expect(checkDoc(null).ok).toBe(false);
  });
  it("열과 줄 모양이 다르면 쓰지 않는다", () => {
    const d = journal(2);
    d.줄[1] = ["20261001"];
    expect(checkDoc(d)).toEqual({ ok: false, reason: "2번째 줄의 칸 수(1)가 열 수(2)와 다름" });
  });
});

describe("docKey", () => {
  it("종류·기간·회사로 같은 자료를 알아본다", () => {
    const r = checkDoc(journal(1));
    if (!r.ok) throw new Error(r.reason);
    expect(docKey(r.doc)).toBe('분개장|{"start_date":"20260101","end_date":"20261031"}|가상회사');
  });
});

describe("docKey 화면별 원본", () => {
  it("화면코드가 다른 대조 원본은 서로 덮지 않는다", async () => {
    const { docKey } = await import("../src/collect/docs");
    const a = docKey({ 종류: "대조원본", 화면코드: "A1", 연도: 2026 });
    const b = docKey({ 종류: "대조원본", 화면코드: "B2", 연도: 2026 });
    expect(a).not.toBe(b);
    expect(docKey({ 종류: "분개장", 기간: ["2026-01-01", "2026-11-26"], 회사: "X" }))
      .toBe(`분개장|${JSON.stringify(["2026-01-01", "2026-11-26"])}|X`);
  });
});
