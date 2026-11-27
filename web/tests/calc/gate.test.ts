// 막힘(problems) 시험. fixtures 설명은 fundplan.test.ts 머리말 (problems 입력은 R 중 gate 가 읽는 칸만 떠 둔 것).
import { describe, expect, it } from "vitest";
import { companyProblems, maxDays, problems, sameCompany } from "../../src/calc/gate";

declare const process: {
  getBuiltinModule(id: "node:fs"): { readFileSync(p: string): Uint8Array; readdirSync(p: string): string[] };
  getBuiltinModule(id: "node:zlib"): { gunzipSync(b: Uint8Array): Uint8Array };
};
const fs = process.getBuiltinModule("node:fs");
const zlib = process.getBuiltinModule("node:zlib");
const DIR = decodeURIComponent(new URL("./fixtures/", import.meta.url).pathname);
/* eslint-disable @typescript-eslint/no-explicit-any */
const fixture = (id: string): any =>
  JSON.parse(new TextDecoder().decode(zlib.gunzipSync(fs.readFileSync(DIR + id + ".json.gz"))));
const ALL = fs.readdirSync(DIR).filter((n) => n.endsWith(".json.gz")).map((n) => n.replace(/\.json\.gz$/, "")).sort();
const CHANGED = new Set(["u_other_company"]); // U10

describe("problems = 파이썬 gate.problems", () => {
  for (const id of ALL.filter((x) => !CHANGED.has(x))) {
    it(id, () => {
      for (const p of fixture(id).problems) expect(problems(p.in)).toEqual(p.out);
    });
  }
  it("막는 사례: 오래된 자금계획서·분개장 8일·세금예상 없음·자금계획서 없음", () => {
    expect(fixture("f_stale_plan").problems[0].out.length).toBeGreaterThan(0);
    expect(fixture("u_journal_8days").problems[0].out.length).toBeGreaterThan(0);
    expect(fixture("f_tax_missing").problems[0].out.length).toBeGreaterThan(0);
    expect(fixture("u_no_fundplan").problems[0].out.length).toBeGreaterThan(0);
  });
  it("자료경과일 설정은 7일보다 길게 못 씀, 글자면 7", () => {
    expect(maxDays({ asof: "2026-11-02", settings_num: { 위험_자료경과일: 30 } })).toBe(7);
    expect(maxDays({ asof: "2026-11-02", settings_num: { 위험_자료경과일: 3 } })).toBe(3);
    expect(maxDays({ asof: "2026-11-02", settings_num: { 위험_자료경과일: "x" } })).toBe(7);
    expect(maxDays({ asof: "2026-11-02", settings_num: { 위험_자료경과일: 0 } })).toBe(7);
  });
  it("회사 이름: (주)·띄어쓰기 무시, 한쪽이 다른 쪽을 품으면 같음, 모르면 같음", () => {
    expect(sameCompany("주식회사 플랜트8", "㈜플랜트8")).toBe(true);
    expect(sameCompany("플랜트8", "주식회사 플랜트8 본점")).toBe(true);
    expect(sameCompany("", "아무개")).toBe(true);
    expect(sameCompany("가상갑", "가상을")).toBe(false);
  });
});

describe("바꿀 것 U10: 다른 회사 자료인 쪽만 이름을 대어 알림 (u_other_company)", () => {
  it("분개장만 다른 회사 → 분개장 알림 하나 (이 회사 자금계획서는 탓하지 않음)", () => {
    const p = fixture("u_other_company").problems[0];
    // 파이썬(바꾸기 전)은 자금계획서도 다른 회사라고 알렸다
    expect(p.out.length).toBe(2);
    expect(p.out[1]).toMatch(/^자금계획서가 다른 회사\(\(샘플\) 플랜트에이트\)/);
    expect(problems(p.in)).toEqual([p.out[0]]);
    expect(p.out[0]).toMatch(/^분개장이 다른 회사\(\(샘플\) 가상다른회사\) 장부임 — 설정 회사명은 \(샘플\) 플랜트에이트/);
  });
  it("자금계획서만 다른 회사 → 자금계획서 알림 하나, 설정 회사명과 견줌", () => {
    const R = { asof: "2026-11-02", settings: { 회사명: "가상갑" },
      auto_facts: { book_company: "가상갑", plan_companies: ["가상을"] } };
    expect(companyProblems(R)).toEqual([
      "자금계획서가 다른 회사(가상을) 자료임 — 설정 회사명은 가상갑. 위하고에서 이 회사 SmartA 화면을 앞에 띄우고 다시 받으세요"]);
  });
  it("둘 다 다른 회사 → 둘 다 알림", () => {
    const R = { asof: "2026-11-02", settings: { 회사명: "가상갑" },
      auto_facts: { book_company: "가상병", plan_companies: ["가상을"] } };
    expect(companyProblems(R).length).toBe(2);
  });
  it("설정 회사명을 모르면 예전처럼 분개장과 견줌", () => {
    const R = { asof: "2026-11-02", settings: { 회사명: "회사명" },
      auto_facts: { book_company: "가상갑", plan_companies: ["가상을"] } };
    expect(companyProblems(R)).toEqual([
      "자금계획서가 다른 회사(가상을) 자료임 — 분개장은 가상갑. 위하고에서 이 회사 SmartA 화면을 앞에 띄우고 다시 받으세요"]);
  });
});
