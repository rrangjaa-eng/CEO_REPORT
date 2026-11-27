// golden/RULES.md '새 시스템에서 바꿀 것' 때문에 변환 기대값과 달라야 하는 사례 (calc 의 known_changes.ts 와 같은 방식).
// 옛 규칙 스위치(oldOpts)로 돌리면 기대값과 정확히 같아야 하고, 새 규칙으로는 check 가 '정확히 그 결정만큼만' 달라졌는지 본다.
import { convert, type ConvertOpts } from "../../src/convert/run";
import type { ConvFiles } from "../../src/convert/files";

export interface ConvertKnownChange {
  case: string; rule: string; what: string;
  oldOpts: ConvertOpts;
  check: (input: ConvFiles, asof: string, now: string) => Promise<string[]>;
}

const PARTIAL = "수집/위하고/261101 분개장 자동수집.json";

export const CONVERT_KNOWN_CHANGES: ConvertKnownChange[] = [
  {
    case: "d_partial_journal", rule: "D7",
    what: "받다 만 새 분개장을 버리고 예전 분개장으로 계산 — 그 파일을 뺀 변환과 같고 경고 한 줄만 더함, 코드 0",
    oldOpts: { skipPartialJournal: false },
    check: async (input, asof, now) => {
      const out: string[] = [];
      const got = await convert(input, asof, now, { stamp: "GOLDEN" });
      const rest = { ...input };
      if (!(PARTIAL in rest)) return [`${PARTIAL} 없음 (사례가 바뀜)`];
      delete rest[PARTIAL];
      const want = await convert(rest, asof, now, { stamp: "GOLDEN" });
      if (got.code !== 0) out.push(`코드 ${got.code} (0이어야 함)`);
      if (JSON.stringify(got.files) !== JSON.stringify(want.files)) out.push("만든 파일이 그 분개장을 뺀 변환과 다름");
      const warn = got.lines.filter((l) => !want.lines.includes(l));
      if (warn.length !== 1 || !/^경고: 받다 만 분개장은 쓰지 않음 — 261101 분개장 자동수집\.json.* → 예전 분개장 261031 분개장 자동수집\.json 으로 계산함/.test(warn[0]!)) {
        out.push("더한 줄이 경고 한 줄이 아님: " + JSON.stringify(warn));
      }
      const same = got.lines.filter((l) => want.lines.includes(l));
      if (JSON.stringify(same) !== JSON.stringify(want.lines)) out.push("나머지 줄이 그 분개장을 뺀 변환과 다름");
      return out;
    },
  },
];
