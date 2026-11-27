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

  it("맞춰진 경우(기본 사례)는 비어 있다", () => {
    const c = loadCase("base");
    expect(compute(loadData(c.files), "weekly", "2026-11-02")["two_source_in"]).toEqual([]);
  });
});
