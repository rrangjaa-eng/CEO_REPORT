// golden/RULES.md '새 시스템에서 바꿀 것' 중 golden 비교만으로는 드러나지 않는 결정의 단언.
// (F6·U6·U10 은 fundplan.test.ts·tax.test.ts·gate.test.ts 와 known_changes.ts 에서 본다. D7 은 변환(다음 단계), U8 은 바꾸지 않음)
import { describe, expect, it } from "vitest";
import { loadCase } from "./golden";
import { loadData } from "../../src/model/data";
import { buildReport } from "../../src/calc/report";

describe("F12: 기준일과 같거나 앞선 출금일은 거부하지 않고 다음 금요일 + 안내", () => {
  const c = loadCase("f_payday_not_after"); // 기준일 2026-11-02, 넣은 출금일 2026-11-02
  const { R } = buildReport(loadData(c.files), c.files, "weekly", c.case.asof, c.case.payday ?? null);
  it("옛 프로그램은 보고를 만들지 않았음(rc=2)", () => {
    expect(c.expected.weekly!.rc).toBe(2);
    expect(c.expected.weekly!.R).toBeNull();
  });
  it("새 계산은 다음 금요일로 잡음", () => expect(R["payday"]).toBe("2026-11-06"));
  it("입력 확인 목록에 안내", () => {
    const msgs = (R["s7"]["issues"] as [string, unknown, string][]).map((i) => i[2]);
    expect(msgs).toContain("넣은 출금일 2026-11-02이 기준일 2026-11-02과 같거나 앞이라 다음 금요일 2026-11-06로 잡음");
  });
  it("나머지 숫자는 출금일을 안 넣은 base 와 같음", () => {
    const b = loadCase("base");
    const RB = buildReport(loadData(b.files), b.files, "weekly", b.case.asof).R;
    for (const k of ["s1", "s2", "events", "fundplan"]) expect(R[k]).toEqual(RB[k]);
  });
});

describe("F9: 남은 예산은 예상 지출에 넣되 따로 보이게 R.budget_left", () => {
  it("base: RULES.md 의심 칸의 49줄 226,655,000원과 같음", () => {
    const c = loadCase("base");
    const { R } = buildReport(loadData(c.files), c.files, "weekly", c.case.asof);
    expect(R["budget_left"]).toEqual({ amount: 226_655_000, n: 49, unknown_n: 0 });
  });
  it("예상 지출에는 그대로 들어 있음(일정에 남은 예산 줄이 있음)", () => {
    const c = loadCase("base");
    const { R } = buildReport(loadData(c.files), c.files, "weekly", c.case.asof);
    expect((R["events"] as { source: string }[]).filter((e) => e.source === "남은 예산").length).toBeGreaterThan(0);
  });
});
