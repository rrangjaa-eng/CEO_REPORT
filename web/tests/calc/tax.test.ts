// 세금 합치기(mergeTax)·장부 채무 비교(compareDebts) 시험. fixtures 설명은 fundplan.test.ts 머리말.
import { describe, expect, it } from "vitest";
import { compareDebts } from "../../src/calc/debts";
import type { FundEvent } from "../../src/calc/fundplan";
import { mergeTax, type TaxRow } from "../../src/calc/tax";

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
const plain = (x: unknown) => JSON.parse(JSON.stringify(x));

describe("mergeTax = 파이썬 tax.merge", () => {
  for (const id of ALL) {
    it(id, () => {
      const m = fixture(id).merge;
      const got = mergeTax(m.in.events, m.in.tax, m.in.asof, m.in.cashDate);
      expect(plain(got)).toEqual(m.out);
    });
  }
  it("세금예상이 없으면(null) 일정 그대로, 설명 []", () => {
    const ev: FundEvent[] = [{ date: "2026-11-06", io: "out", amount: 1 }];
    expect(mergeTax(ev, null, "2026-11-02", null)).toEqual([ev, []]);
  });
});

describe("compareDebts = 파이썬 debts.compare", () => {
  for (const id of ALL) {
    it(id, () => {
      const c = fixture(id).compare;
      expect(plain(compareDebts(c.in.debts, c.in.events, c.in.asof))).toEqual(c.out);
    });
  }
  it("장부채무가 없으면 null", () => expect(compareDebts(null, [], "2026-11-02")).toBeNull());
});

describe("바꿀 것 U6: 숫자 아닌 거래처코드도 양쪽 같은 규칙 (u_card_once)", () => {
  // u_card_once 는 숫자 코드(장부 9001 = 자금계획서 009001)라 파이썬도 한 번만 센다. 같은 자료의 코드를 숫자가 아닌 것으로 바꾸면
  // (장부 C9001, 자금계획서 변환이 zfill 한 00C9001) 파이썬은 코드가 달라 다른 지급으로 봤다 — 새 시스템은 같은 코드로 본다.
  const variant = () => {
    const m = fixture("u_card_once").merge;
    const tax: TaxRow[] = m.in.tax.map((t: any) => (t.codes.includes("9001") ? { ...t, codes: ["C9001"] } : t));
    const events: FundEvent[] = m.in.events.map((e: any) => (e.vendor_code === "009001" ? { ...e, vendor_code: "00C9001" } : e));
    return { m, tax, events };
  };
  it("파이썬과 같은 결과: 카드대금은 자금계획서 줄과 코드로 맞고 3,456,000 은 일정에 한 건", () => {
    const { m, tax, events } = variant();
    const [ev, info] = mergeTax(events, tax, m.in.asof, m.in.cashDate);
    const card = info.find((t) => t.kind === "카드대금" && t.codes.includes("C9001"))!;
    expect((card.matched as FundEvent).source).toBe("자금계획서");
    expect(card.by_name).toBe(false);
    expect(card.diff).toBe(0);
    expect(ev.filter((e) => e.amount === 3456000).length).toBe(1);
    // 원래 자료(숫자 코드)의 파이썬 결과와 코드만 빼고 같음
    const pyCard = m.out[1].find((t: any) => t.kind === "카드대금" && t.codes.includes("9001"));
    expect({ ...plain(card), codes: pyCard.codes, matched: pyCard.matched, matched_all: pyCard.matched_all }).toEqual(pyCard);
  });
});
