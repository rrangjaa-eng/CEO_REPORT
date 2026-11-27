import "fake-indexeddb/auto";
import { beforeEach, describe, expect, it } from "vitest";
import type { ForecastRecord } from "../src/calc/accuracy";
import { clearAll, exportBackup, importBackup, lastForecastBefore, listForecasts, saveForecast } from "../src/collect/store";

const rec = (asof: string, start: number): ForecastRecord => ({ asof, start, rows: [] });

describe("예상 기록", () => {
  beforeEach(async () => { await clearAll(); });

  it("기준일마다 하나, 같은 기준일은 새 것으로 바꾼다", async () => {
    await saveForecast(rec("2026-11-02", 1));
    await saveForecast(rec("2026-11-02", 2));
    await saveForecast(rec("2026-11-09", 3));
    const all = await listForecasts();
    expect(all.map((r) => [r.asof, r.start])).toEqual([["2026-11-02", 2], ["2026-11-09", 3]]);
  });

  it("이번 기준일보다 앞선 가장 늦은 기록을 찾는다", async () => {
    await saveForecast(rec("2026-10-26", 1));
    await saveForecast(rec("2026-11-02", 2));
    await saveForecast(rec("2026-11-09", 3));
    expect((await lastForecastBefore("2026-11-09"))?.asof).toBe("2026-11-02");
    expect(await lastForecastBefore("2026-10-26")).toBeNull();
  });

  it("백업에 예상 기록도 들어가고 되살아난다", async () => {
    await saveForecast(rec("2026-11-02", 7));
    const b = await exportBackup();
    await clearAll();
    await importBackup(b);
    expect((await listForecasts())[0]?.start).toBe(7);
  });
});
