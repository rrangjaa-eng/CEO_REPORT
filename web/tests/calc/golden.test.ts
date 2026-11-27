// 정답 예시 비교: 사례 × 종류마다 R 의 키를 하나씩 기대값과 1원·1글자까지 비교한다.
// 특정 키만 보려면: GOLDEN_KEYS=s1,payday npx vitest run tests/calc/golden.test.ts  (사례만: GOLDEN_CASES=base,u_transfer)
import { describe, expect, it } from "vitest";
import { listCases, loadCase, diffPaths } from "./golden";
import { loadData } from "../../src/model/data";
import { buildReport, OUT_OF_SCOPE_KEYS } from "../../src/calc/report";
import { KNOWN_CHANGES } from "./known_changes";

declare const process: { env: Record<string, string | undefined> };

/** calc.compute 가 만드는 키 + 보고서.py 가 붙이는 auto_facts. 범위 밖 키는 report.ts OUT_OF_SCOPE_KEYS */
export const PORTED_KEYS = [
  "kind", "asof", "payday", "period", "settings", "settings_num", "settings_default", "present",
  "s1", "s3", "s5", "intranet_only", "fundplan", "tax", "tax_missing", "events", "debts", "two_source",
  "s2", "s4", "s6", "s7", "targets", "budget_cmp", "budget_conf_rows", "evid_month", "dep", "acct_year",
  "last_pay", "plan_gap_note", "risks", "auto_facts",
] as const;

const onlyKeys = process.env["GOLDEN_KEYS"]?.split(",").filter(Boolean);
const onlyCases = process.env["GOLDEN_CASES"]?.split(",").filter(Boolean);
const keys = PORTED_KEYS.filter((k) => !onlyKeys || onlyKeys.includes(k));
const cases = listCases().filter((c) => !onlyCases || onlyCases.includes(c));

/** 기대값 R 에서 보고서.py 단계 중 범위 밖 키를 뺀 나머지가 PORTED_KEYS 와 정확히 같은지 (빠뜨린 키 없게) */
it("옮길 키 목록이 기대값 R 의 키와 맞음", () => {
  const exp = loadCase("base").expected.monthly!;
  const all = Object.keys(exp.R ?? {}).filter((k) => !(OUT_OF_SCOPE_KEYS as readonly string[]).includes(k));
  expect(all.sort()).toEqual([...PORTED_KEYS].sort());
});

for (const id of cases) {
  const c = loadCase(id);
  for (const kind of (c.case.kinds ?? ["weekly", "monthly"]) as ("weekly" | "monthly")[]) {
    const exp = c.expected[kind];
    if (!exp) continue;
    describe(`${id} ${kind}`, () => {
      let got: { R: Record<string, unknown> | null; stop: string[] } | undefined;
      const run = () => {
        if (!got) {
          const r = buildReport(loadData(c.files), c.files, kind, c.case.asof, c.case.payday ?? null);
          got = { R: r.R, stop: r.stop };
        }
        return got;
      };
      const changed = (path: string) => KNOWN_CHANGES.find((k) => k.case === id && k.kind === kind && k.path === path);
      if (!onlyKeys || onlyKeys.includes("stop")) {
        it("stop", () => {
          const ch = changed("stop");
          if (exp.rc === 2 && exp.R === null) return; // 명령이 시작 전에 거부한 사례(F12): decisions.test.ts 가 따로 본다
          expect(ch ? ch.check(exp.stop, run().stop) : diffPaths(exp.stop, run().stop)).toEqual([]);
        });
      }
      for (const key of keys) {
        it(key, () => {
          if (exp.R === null) return; // 위와 같음
          const ch = changed(`R.${key}`);
          const want = (exp.R as Record<string, unknown>)[key];
          expect(ch ? ch.check(want, run().R![key]) : diffPaths(want, run().R![key])).toEqual([]);
        });
      }
    });
  }
}
