// 변환 → 보고서 끝까지: TS 변환이 만든 범위 안 CSV 로 입력 폴더를 덮고(범위 밖 파일은 기대값 그대로) loadData + buildReport 결과를
// calc golden 과 같은 방식으로 비교한다 (calc 의 KNOWN_CHANGES 를 그대로 씀). 새 변환 규칙 사례는 옛 규칙 스위치로 돌린다.
import { describe, expect, it } from "vitest";
import { loadData } from "../../src/model/data";
import { writeCsv, type FileSet } from "../../src/model/csv";
import { buildReport, OUT_OF_SCOPE_KEYS } from "../../src/calc/report";
import { IN_SCOPE, SIDE_FILES, convert } from "../../src/convert/run";
import { CASES_DIR, diffPaths, listCases, loadCase, readInputDir } from "../calc/golden";
import { KNOWN_CHANGES } from "../calc/known_changes";
import { caseInput } from "./cases";
import { CONVERT_KNOWN_CHANGES } from "./known_changes";

declare const process: { env: Record<string, string | undefined> };
const onlyCases = process.env["GOLDEN_CASES"]?.split(",").filter(Boolean);
const cases = listCases().filter((c) => !onlyCases || onlyCases.includes(c));
const scope = new Set([...IN_SCOPE, ...SIDE_FILES]);

/** 비교할 R 키: 기대값 R 의 키 중 보고서.py 단계의 범위 밖 키를 뺀 것 (calc golden.test 와 같음) */
const portedKeys = (R: Record<string, unknown>) => Object.keys(R).filter((k) => !(OUT_OF_SCOPE_KEYS as readonly string[]).includes(k));

for (const id of cases) {
  const c = loadCase(id);
  const kinds = (c.case.kinds ?? ["weekly", "monthly"]) as ("weekly" | "monthly")[];
  describe(`변환→보고서 ${id}`, () => {
    let files: FileSet | undefined;
    const prepare = async (): Promise<FileSet> => {
      if (files) return files;
      const exp = c.expected.convert;
      const known = CONVERT_KNOWN_CHANGES.find((k) => k.case === id);
      const got = await convert(caseInput(id), c.case.asof, c.case.asof + " 00:00:00", { stamp: "GOLDEN", ...(known ? known.oldOpts : {}) });
      const fs = readInputDir(CASES_DIR + id + "/input/입력");
      for (const [name, rows] of Object.entries(exp.files)) if (!scope.has(name)) fs[name] = writeCsv(rows);
      for (const [name, obj] of Object.entries(exp.json)) fs[name] = JSON.stringify(obj, null, 1);
      for (const [name, text] of Object.entries(got.files)) fs[name] = text.startsWith("﻿") ? text.slice(1) : text;
      files = fs;
      return fs;
    };
    for (const kind of kinds) {
      const exp = c.expected[kind];
      if (!exp) continue;
      if (exp.R === null) {
        it.skip(`${kind} (명령이 시작 전에 거부한 사례 — decisions.test.ts 가 봄)`, () => {});
        continue;
      }
      it(kind, async () => {
        const fs = await prepare();
        const r = buildReport(loadData(fs), fs, kind, c.case.asof, c.case.payday ?? null);
        const bad: string[] = [];
        const changed = (path: string) => KNOWN_CHANGES.find((k) => k.case === id && k.kind === kind && k.path === path);
        const ch = changed("stop");
        bad.push(...(ch ? ch.check(exp.stop, r.stop) : diffPaths(exp.stop, r.stop)).map((d) => "stop " + d));
        for (const key of portedKeys(exp.R!)) {
          const k = changed(`R.${key}`);
          const want = (exp.R as Record<string, unknown>)[key];
          bad.push(...(k ? k.check(want, r.R![key]) : diffPaths(want, r.R![key])).map((d) => `${key} ${d}`));
        }
        expect(bad).toEqual([]);
      });
    }
  });
}
