// 자금계획서 맞추기(applyFundplan) 시험.
// fixtures/*.json.gz: golden 사례를 파이썬으로 돌리며 fundplan.apply·tax.merge·debts.compare·gate.problems 에
// 들어간 값과 나온 값을 그 자리에서 JSON 으로 떠 둔 것 (가상 자료만. 날짜는 "YYYY-MM-DD", 튜플은 목록).
// 바꿀 것 F6(f_other_vendor_near)은 파이썬 결과와 일부러 다르게 나와야 한다 — 아래 따로 단언.
import { describe, expect, it } from "vitest";
import { applyFundplan, type FundEvent, type PlanRow } from "../../src/calc/fundplan";

declare const process: {
  getBuiltinModule(id: "node:fs"): { readFileSync(p: string): Uint8Array; readdirSync(p: string): string[] };
  getBuiltinModule(id: "node:zlib"): { gunzipSync(b: Uint8Array): Uint8Array };
};
const fs = process.getBuiltinModule("node:fs");
const zlib = process.getBuiltinModule("node:zlib");
const DIR = decodeURIComponent(new URL("./fixtures/", import.meta.url).pathname);

/* eslint-disable @typescript-eslint/no-explicit-any */
function fixture(id: string): any {
  return JSON.parse(new TextDecoder().decode(zlib.gunzipSync(fs.readFileSync(DIR + id + ".json.gz"))));
}
const ALL = fs.readdirSync(DIR).filter((n) => n.endsWith(".json.gz")).map((n) => n.replace(/\.json\.gz$/, "")).sort();
const CHANGED = new Set(["f_other_vendor_near"]); // F6

function run(fx: any): [FundEvent[], any, PlanRow[] | null] {
  const a = fx.apply.in;
  const plan = a.plan as PlanRow[] | null;
  const [ev, info] = applyFundplan(a.events, plan, a.asof, a.staleDays, a.problem, a.cashDate, a.txns);
  return [JSON.parse(JSON.stringify(ev)), info === null ? null : JSON.parse(JSON.stringify(info)), plan && JSON.parse(JSON.stringify(plan))];
}

describe("applyFundplan = 파이썬 fundplan.apply", () => {
  it("사례가 있다", () => expect(ALL.length).toBeGreaterThanOrEqual(19));
  for (const id of ALL.filter((x) => !CHANGED.has(x))) {
    it(id, () => {
      const fx = fixture(id);
      const [ev, info, planAfter] = run(fx);
      expect(ev).toEqual(fx.apply.out[0]);
      expect(info).toEqual(fx.apply.out[1]);
      expect(planAfter).toEqual(fx.apply.planAfter); // 파이썬처럼 계획 줄에 _by_name·_split 을 남긴다
    });
  }

  it("자금계획서 없음 → 기존 일정 그대로, 설명 null / 문제 글자가 있으면 이유", () => {
    const ev: FundEvent[] = [{ date: "2026-11-06", io: "out", amount: 1, source: "자금일정" }];
    expect(applyFundplan(ev, null, "2026-11-02", 7)).toEqual([ev, null]);
    expect(applyFundplan(ev, null, "2026-11-02", 7, "읽지 못함")[1]).toEqual({
      used: false, reason: "자금계획.csv 읽지 못함 → 기존 일정 사용" });
    expect(applyFundplan(ev, [], "2026-11-02", 7)[1]).toEqual({
      used: false, reason: "자금계획.csv 에 줄이 없음 → 기존 일정 사용" });
  });
});

describe("바꿀 것 F6: 거래처코드가 없어도 이름이 다르면 다른 건", () => {
  it("f_other_vendor_near: 가상이름갑(코드 있음)·가상이름을(코드 없음) 같은 금액 2일 차이 → added·missing 따로", () => {
    const fx = fixture("f_other_vendor_near");
    const [ev, info] = run(fx);
    const py = fx.apply.out[1];
    // 파이썬은 이름으로 맞췄다 (지금 결과 = 바꾸기 전)
    expect(py.matched.map((m: any) => m.plan.desc)).toContain("가상이름갑");
    expect(info.matched.map((m: any) => m.plan.desc)).not.toContain("가상이름갑");
    expect(info.matched).toEqual(py.matched.filter((m: any) => m.plan.desc !== "가상이름갑"));
    expect(info.added.map((e: any) => e.desc)).toEqual(["㈜가상제작", "(주)가상음향", "가상이름갑", "가상이름병", "가상코드갑", "주식회사 가상부스"]);
    const miss = info.missing.find((e: any) => e.desc === "가상이름을");
    expect(miss).toMatchObject({ amount: 4410000, date: "2026-11-11", plan_note: "자금계획서에 없음", source: "자금일정" });
    expect(info.missing.length).toBe(py.missing.length + 1);
    // 일정에는 두 줄 다 남는다 (같은 금액 4,410,000 두 건)
    expect(ev.filter((e) => e.amount === 4410000).map((e) => e.desc).sort()).toEqual(["가상이름갑", "가상이름을"]);
    expect(ev.length).toBe(fx.apply.out[0].length + 1);
    // 나머지 줄은 파이썬과 같음
    const strip = (xs: any[]) => xs.filter((e) => e.amount !== 4410000);
    expect(strip(ev)).toEqual(strip(fx.apply.out[0]));
  });

  it("이름이 같으면(코드 없음) 날짜가 멀어도 같은 건 — 그대로", () => {
    const plan: PlanRow[] = [{ date: "2026-11-20", io: "입금", cat: "외상대금 회수", vendor: "가상고객D", vendor_code: "", amount: 100,
      ym: "2026-11", stamp: "2026-11-01", state: "예정", basis: "", file: "f", project: "", origin: "" }];
    const ev: FundEvent[] = [{ date: "2026-12-26", io: "in", amount: 100, desc: "가상고객D", source: "계산서", project: "P" }];
    const [, info] = applyFundplan(ev, plan, "2026-11-02", 7);
    expect(info!.matched!.length).toBe(1);
  });

  it("이름이 다르고 코드가 없으면 7일 안 같은 금액이어도 다른 건", () => {
    const plan: PlanRow[] = [{ date: "2026-11-13", io: "지급", cat: "미지급금 지급", vendor: "가상갑", vendor_code: "", amount: 100,
      ym: "2026-11", stamp: "2026-11-01", state: "예정", basis: "", file: "f", project: "", origin: "" }];
    const ev: FundEvent[] = [{ date: "2026-11-12", io: "out", amount: 100, desc: "가상을", source: "자금일정", project: "" }];
    const [out, info] = applyFundplan(ev, plan, "2026-11-02", 7);
    expect(info!.matched).toEqual([]);
    expect(info!.added!.length).toBe(1);
    expect(info!.missing!.length).toBe(1);
    expect(out.length).toBe(2);
  });
});

describe("바꿀 것 U6: 숫자 아닌 거래처코드도 양쪽 같은 규칙", () => {
  it("자금계획서 쪽만 앞에 0이 붙은 코드(00C202 = C202)도 같은 거래처", () => {
    const plan: PlanRow[] = [{ date: "2026-11-13", io: "지급", cat: "미지급금 지급", vendor: "가상갑", vendor_code: "00C202", amount: 100,
      ym: "2026-11", stamp: "2026-11-01", state: "예정", basis: "", file: "f", project: "", origin: "" }];
    const ev: FundEvent[] = [{ date: "2026-11-30", io: "out", amount: 100, desc: "가상갑 다른 표기", source: "자금일정", project: "", vendor_code: "C202" }];
    const [, info] = applyFundplan(ev, plan, "2026-11-02", 7);
    expect(info!.matched!.length).toBe(1);
    expect(info!.matched![0]!.by_name).toBe(false); // 코드로 맞춤
  });
  it("000-00-00003 과 -00-00003 (자금계획서 변환이 앞 0을 뗀 것)도 같은 코드", () => {
    const plan: PlanRow[] = [{ date: "2026-12-04", io: "지급", cat: "미지급금 지급", vendor: "주식회사 가상부스", vendor_code: "-00-00003", amount: 5,
      ym: "2026-12", stamp: "2026-11-01", state: "예정", basis: "", file: "f", project: "", origin: "" }];
    const ev: FundEvent[] = [{ date: "2026-12-31", io: "out", amount: 5, desc: "다른이름", source: "프로젝트집행", project: "X", vendor_code: "000-00-00003" }];
    const [, info] = applyFundplan(ev, plan, "2026-11-02", 7);
    expect(info!.matched!.length).toBe(1);
  });
});
