// 과대·과소 점검(2026-11-27)에서 찾은 것 중, 정해 둔 규칙을 바꾸지 않는 안전장치.
import { describe, expect, it } from "vitest";
import { compute } from "../../src/calc/compute";
import { loadData } from "../../src/model/data";
import { loadCase } from "./golden";

const rep = (f: Record<string, string>, name: string, a: string, b: string) => {
  if (!f[name]!.includes(a)) throw new Error(`${name} 에 '${a}' 없음`);
  f[name] = f[name]!.replace(a, b);
};
const msgs = (d: { issues: { items: [string, unknown, string][] } }, file: string) =>
  d.issues.items.filter((x) => x[0] === file).map((x) => x[2]);

describe("금액에 따옴표 없는 쉼표가 든 줄", () => {
  it("계좌잔액: 잔액을 360원으로 읽지 않고 미확인으로 두고 알린다", () => {
    const c = loadCase("base");
    rep(c.files, "계좌잔액.csv", '"402,000,000",0,', "402,000,000,0,");
    const d = loadData(c.files);
    const b = d.balances.find((x) => x.account === "운영계좌")!;
    expect(b.balance).toBeNull();
    expect(msgs(d as never, "계좌잔액.csv").some((m) => m.includes("칸이 머리글보다 많음"))).toBe(true);
  });

  it("끝에 빈 칸만 남는 줄(엑셀이 붙인 쉼표)은 그대로 읽는다", () => {
    const c = loadCase("base");
    rep(c.files, "계좌잔액.csv", '"402,000,000",0,', '"402,000,000",0,,,');
    const d = loadData(c.files);
    expect(d.balances.find((x) => x.account === "운영계좌")!.balance).toBe(402000000);
    expect(msgs(d as never, "계좌잔액.csv").some((m) => m.includes("칸이 머리글보다 많음"))).toBe(false);
  });
});

describe("칸이 밀려도 숫자가 멀쩡한 줄은 그대로 읽는다 (검토 반영)", () => {
  it("적요에 따옴표 없는 쉼표가 있어도 그 거래 금액은 그대로", () => {
    const c = loadCase("base");
    rep(c.files, "입출금내역.csv", "A사 무대 1차", "A사 무대, 1차");
    const d = loadData(c.files);
    expect(d.txns.length).toBe(loadData(loadCase("base").files).txns.length);
    expect(msgs(d as never, "입출금내역.csv").some((m) => m.includes("칸이 머리글보다 많음"))).toBe(false);
  });

  it("제한사유에 쉼표가 있어도 잔액은 그대로", () => {
    const c = loadCase("base");
    rep(c.files, "계좌잔액.csv", "A사 선수금 중 행사 전용 금액", "A사 선수금, 행사 전용");
    expect(loadData(c.files).balances.filter((b) => b.balance === null).length).toBe(0);
  });
});

describe("손익 연월 형식", () => {
  const plRow = (c: ReturnType<typeof loadCase>) => c.files["손익.csv"]!.split("\n").find((l) => l.includes("2026-09"))!;

  it("'2026.9' 는 '2026-09' 로 읽는다 (글자 비교로 11월보다 뒤가 되지 않게)", () => {
    const c = loadCase("base");
    const line = plRow(c);
    rep(c.files, "손익.csv", line, line.replace("2026-09", "2026.9"));
    const d = loadData(c.files);
    expect(d.pl.some((p) => p.ym === "2026-9")).toBe(false);
    expect(d.pl.filter((p) => p.ym === "2026-09").length).toBe(loadData(loadCase("base").files).pl.filter((p) => p.ym === "2026-09").length);
  });

  it("'26-09' 처럼 해를 알 수 없는 연월은 알린다", () => {
    const c = loadCase("base");
    const line = plRow(c);
    rep(c.files, "손익.csv", line, line.replace("2026-09", "26-09"));
    expect(msgs(loadData(c.files) as never, "손익.csv").some((m) => m.includes("연월"))).toBe(true);
  });
});

describe("입금 출처 둘 (자금계획서와 계산서에 같은 거래처·같은 달)", () => {
  it("자금계획서 입금과 맞지 않은 계산서가 같은 거래처면 R.two_source_in 에 올린다", () => {
    const c = loadCase("base");
    rep(c.files, "자금계획.csv", "82500000", "80000000");
    rep(c.files, "계산서.csv", "2026-12-26,N", "2026-11-26,N");
    const R = compute(loadData(c.files), "weekly", "2026-11-02");
    expect(R["two_source_in"]).toEqual([
      { vendor: "가상고객D", month: "2026-11", sources: { 자금계획서: 80000000, 계산서: 82500000 } },
    ]);
  });

  it("예정일이 지나 이번 주 입금으로 옮겨진 계산서도 본다 (검토 반영)", () => {
    const c = loadCase("base");
    rep(c.files, "자금계획.csv", "82500000", "80000000");
    rep(c.files, "계산서.csv", "2026-12-26,N", "2026-10-30,N");
    const R = compute(loadData(c.files), "weekly", "2026-11-02");
    expect(R["two_source_in"]).toEqual([
      { vendor: "가상고객D", month: "2026-11", sources: { 자금계획서: 80000000, 계산서: 82500000 } },
    ]);
  });

  it("맞춰진 경우(기본 사례)는 비어 있다", () => {
    const c = loadCase("base");
    expect(compute(loadData(c.files), "weekly", "2026-11-02")["two_source_in"]).toEqual([]);
  });
});

describe("합계 나눠 보기 (R.totals_split): 음수가 다른 프로젝트 몫을 깎지 않게", () => {
  const R = compute(loadData(loadCase("base").files), "weekly", "2026-11-02");
  const T = R["totals_split"];

  it("잔여 예산: 진행 중 양수 · 끝난 프로젝트 잔여 · 예산 초과로 나눈다 (합치면 기존 합계)", () => {
    expect(T.remain).toEqual({ open: 206050000, closed: 87500000, over: 14000000, over_n: 1 });
    expect(T.remain.open + T.remain.closed - T.remain.over).toBe(R["s3"].total.remain);
    // 자금 일정에 '남은 예산'으로 들어가는 금액(부가세 10% 더한 값)의 바탕과 같다
    expect(Math.round(T.remain.open * 1.1)).toBe(R["budget_left"].amount);
  });

  it("미발행·매출 미반영: 계약보다 더 발행·반영한 몫(over)을 따로 둔다", () => {
    expect(T.unissued.open - T.unissued.over).toBe(R["s5"].unissued);
    expect(T.unrecognized.open - T.unrecognized.over).toBe(R["s4"].unrecognized);
    expect(T.unissued.over).toBeGreaterThanOrEqual(0);
    expect(T.unrecognized.over_n).toBe(R["s4"].projects.filter((P: any) => P.unrecognized < 0).length);
  });

  it("계약보다 많이 발행한 프로젝트가 있어도 다른 프로젝트 미발행(open)은 줄지 않는다", () => {
    const c = loadCase("base");
    const before = T.unissued.open;
    c.files["계산서.csv"] += "26203,가상고객D,2026-10-30,발행,300000000,30000000,2026-12-29,N,,\n";
    const R2 = compute(loadData(c.files), "weekly", "2026-11-02");
    const own = (R["s5"].by_project as any[]).find((x) => x.P.id === "26203").unissued;
    expect(R2["totals_split"].unissued.open).toBe(before - Math.max(own, 0));
    expect(R2["totals_split"].unissued.over).toBeGreaterThan(0);
  });
});
