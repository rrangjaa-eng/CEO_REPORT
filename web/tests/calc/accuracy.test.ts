// 예상 대비 실제: 지난 보고가 예상한 입출금과 그 뒤 실제 통장 입출금의 차이를 잰다.
import { describe, expect, it } from "vitest";
import { collectionLag, compareForecast, forecastRecord, type ForecastRecord } from "../../src/calc/accuracy";
import { compute } from "../../src/calc/compute";
import { loadData } from "../../src/model/data";
import { loadCase } from "./golden";

const row = (date: string, io: "in" | "out", amount: number | null, firm = true, desc = "가", source = "자금계획서") =>
  ({ date, io, amount, firm, desc, source, cat: "" });
const txn = (date: string, io: "입금" | "출금", amount: number, vendor = "가", cat = "거래처지급") =>
  ({ date, io, amount, vendor, cat });

describe("forecastRecord", () => {
  it("기준일 뒤 28일 안의 날짜·금액 있는 일정과 시작 자금을 남긴다", () => {
    const c = loadCase("base");
    const R = compute(loadData(c.files), "weekly", "2026-11-02");
    const rec = forecastRecord(R);
    expect(rec.asof).toBe("2026-11-02");
    expect(rec.start).toBe(542400000);
    expect(rec.rows.every((r) => r.date > "2026-11-02" && r.date <= "2026-11-30")).toBe(true);
    // 1~4주차(11-27까지) 합은 보고의 4주 합과 같아야 한다 (같은 일정에서 뽑으므로)
    const upto = rec.rows.filter((r) => r.date <= "2026-11-27");
    const sum = (io: string, firm: boolean) => upto.filter((r) => r.io === io && r.firm === firm).reduce((t, r) => t + (r.amount ?? 0), 0);
    expect(sum("out", true)).toBe(R["s2"]["out4_firm"]);
    expect(sum("out", false)).toBe(R["s2"]["out4_est"]);
    expect(sum("in", true)).toBe(R["s2"]["in4_firm"]);
    expect(sum("in", false)).toBe(R["s2"]["in4_est"]);
  });

  it("지난 날짜 입금을 이번 주로 옮긴 사본(late_in)도 예상에 넣는다", () => {
    const c = loadCase("f_late_invoice");
    const R = compute(loadData(c.files), "weekly", c.case.asof);
    const rec = forecastRecord(R);
    expect(rec.rows.some((r) => r.io === "in" && r.amount === 5500000 && r.date === R["payday"])).toBe(true);
  });
});

describe("compareForecast", () => {
  const prev: ForecastRecord = {
    asof: "2026-11-02", start: 100_000_000,
    rows: [row("2026-11-06", "out", 30_000_000), row("2026-11-06", "out", 5_000_000, false, "나", "남은 예산"),
           row("2026-11-05", "in", 20_000_000, false, "고객", "계산서"), row("2026-11-20", "out", 9_000_000)],
  };

  it("기간(지난 기준일 다음 날~이번 기준일)의 예상과 실제 합계, 차이(실제−예상)를 낸다", () => {
    const a = compareForecast(prev, [txn("2026-11-06", "출금", 30_000_000), txn("2026-11-09", "출금", 2_000_000, "다")], "2026-11-09", 68_000_000);
    expect(a.from).toBe("2026-11-03");
    expect(a.to).toBe("2026-11-09");
    expect(a.out).toEqual({ firm: 30_000_000, all: 35_000_000, actual: 32_000_000, diff_firm: 2_000_000, diff_all: -3_000_000, unknown_n: 0 });
    expect(a.in).toEqual({ firm: 0, all: 20_000_000, actual: 0, diff_firm: 0, diff_all: -20_000_000, unknown_n: 0 });
    // 끝 잔액: 시작 + 입금 − 출금
    expect(a.end).toEqual({ firm: 70_000_000, all: 85_000_000, actual: 68_000_000, diff_firm: -2_000_000, diff_all: -17_000_000 });
  });

  it("건별로 맞춘다: 맞음 · 예상했으나 없음 · 예상에 없던 실제", () => {
    const a = compareForecast(prev, [txn("2026-11-06", "출금", 30_000_000), txn("2026-11-09", "출금", 2_000_000, "다")], "2026-11-09", null);
    expect(a.hit.map((h) => [h.plan.amount, h.days])).toEqual([[30_000_000, 0]]);
    expect(a.not_happened.map((r) => [r.io, r.amount])).toEqual([["in", 20_000_000], ["out", 5_000_000]]);
    expect(a.unplanned.map((t) => [t.io, t.amount])).toEqual([["출금", 2_000_000]]);
    expect(a.end.actual).toBeNull();
    expect(a.end.diff_all).toBeNull();
  });

  it("계좌 간 이체는 실제 입출금에서 뺀다 (U5)", () => {
    const a = compareForecast(prev, [txn("2026-11-06", "출금", 7_000_000, "급여계좌", "계좌간이체"), txn("2026-11-06", "입금", 7_000_000, "운영계좌", "계좌간이체")], "2026-11-09", null);
    expect(a.out.actual).toBe(0);
    expect(a.in.actual).toBe(0);
    expect(a.unplanned).toEqual([]);
  });

  it("금액을 모르는 예상은 0으로 치지 않고 건수로 남긴다 (U1)", () => {
    const p: ForecastRecord = { asof: "2026-11-02", start: null, rows: [row("2026-11-06", "out", null)] };
    const a = compareForecast(p, [], "2026-11-09", 1);
    expect(a.out.unknown_n).toBe(1);
    expect(a.out.firm).toBe(0);
    expect(a.end.firm).toBeNull();
  });

  it("같은 금액이 둘이면 거래처 이름이 같은 쪽과 먼저 맞춘다", () => {
    const p: ForecastRecord = { asof: "2026-11-02", start: 0, rows: [row("2026-11-06", "out", 1_000_000, true, "(주)나라")] };
    const a = compareForecast(p, [txn("2026-11-05", "출금", 1_000_000, "다른곳"), txn("2026-11-07", "출금", 1_000_000, "나라 주식회사")], "2026-11-09", null);
    expect(a.hit[0]!.actual.vendor).toBe("나라 주식회사");
    expect(a.hit[0]!.days).toBe(1);
    expect(a.unplanned.map((t) => t.vendor)).toEqual(["다른곳"]);
  });

  it("출처별로 예상과 실현(맞은 금액)을 모은다", () => {
    const a = compareForecast(prev, [txn("2026-11-06", "출금", 30_000_000)], "2026-11-09", null);
    expect(a.by_source).toEqual([
      { source: "계산서", io: "in", planned: 20_000_000, n: 1, happened: 0, hit_n: 0 },
      { source: "남은 예산", io: "out", planned: 5_000_000, n: 1, happened: 0, hit_n: 0 },
      { source: "자금계획서", io: "out", planned: 30_000_000, n: 1, happened: 30_000_000, hit_n: 1 },
    ]);
  });
});

describe("collectionLag", () => {
  const inv = (client: string, date: string, due: string | null, paid_date: string | null, due_firm = false) =>
    ({ client, date, due, due_firm, paid_date, kind: "발행", supply: 1_000_000, vat: 100_000 });

  it("입금된 계산서로 예정일 대비 실제 입금일 차이(일)를 거래처별·전체로 낸다", () => {
    const L = collectionLag([
      inv("가", "2026-01-10", "2026-03-11", "2026-03-21"), inv("가", "2026-02-10", "2026-04-11", "2026-04-15"),
      inv("가", "2026-03-10", "2026-05-09", "2026-05-29"), inv("나", "2026-03-01", "2026-04-30", "2026-04-20"),
      inv("나", "2026-06-01", "2026-07-31", null),
    ]);
    expect(L.all).toEqual({ n: 4, late_median: 7, late_n: 3, term_median: 67 });
    expect(L.by_client["가"]).toEqual({ n: 3, late_median: 10, late_n: 3, term_median: 70 });
    expect(L.by_client["나"]).toEqual({ n: 1, late_median: -10, late_n: 0, term_median: 50 });
  });

  it("입금된 계산서가 없으면 전체는 null", () => {
    expect(collectionLag([inv("가", "2026-01-10", "2026-03-11", null)]).all).toBeNull();
  });
});
