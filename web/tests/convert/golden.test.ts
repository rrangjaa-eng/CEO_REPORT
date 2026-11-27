// 변환 golden 비교: 46 사례마다 종료 코드·범위 안 CSV(글자까지)·화면 줄(범위 밖 줄을 뺀 뒤)을 기대값과 맞춘다.
// 사례만: GOLDEN_CASES=base,u_transfer npx vitest run tests/convert/golden.test.ts
import { describe, expect, it } from "vitest";
import { convert } from "../../src/convert/run";
import { listCases, loadCase } from "../calc/golden";
import { caseInput } from "./cases";
import { compareFiles, compareLines, countProblems } from "./golden";
import { CONVERT_KNOWN_CHANGES } from "./known_changes";

declare const process: { env: Record<string, string | undefined> };
const onlyCases = process.env["GOLDEN_CASES"]?.split(",").filter(Boolean);
const cases = listCases().filter((c) => !onlyCases || onlyCases.includes(c));

for (const id of cases) {
  describe(`변환 ${id}`, () => {
    const c = loadCase(id);
    const exp = c.expected.convert;
    const input = caseInput(id);
    const now = c.case.asof + " 00:00:00";
    const known = CONVERT_KNOWN_CHANGES.find((k) => k.case === id);
    it(known ? `옛 규칙(${known.rule} 끔)으로는 기대값과 같음` : "기대값과 같음", async () => {
      const got = await convert(input, c.case.asof, now, { stamp: "GOLDEN", ...(known ? known.oldOpts : {}) });
      expect(got.code).toBe(exp.code);
      expect(compareFiles(exp, got, input)).toEqual([]);
      expect(compareLines(exp.lines, got.lines)).toEqual([]);
      expect(countProblems(exp.lines, got.lines)).toEqual([]);
    });
    if (known) {
      it(`새 규칙 ${known.rule}: ${known.what}`, async () => {
        expect(await known.check(input, c.case.asof, now)).toEqual([]);
      });
    }
  });
}
