// 화면이 쓰는 길 그대로: golden base 의 input 폴더를 '부모 폴더에서 고른 것처럼' 읽어 → 폴더 파일 → 변환 입력 → makeReport.
// R 은 golden weekly.json 의 R 과 같아야 한다 (calc golden 과 같은 비교, 범위 밖 키는 뺌).
// 단 auto_facts 는 뺀다: 파이썬 변환이 만드는 자동분석.json 을 TS 변환은 아직 만들지 않는다 (pipeline.STALE_INPUTS).
import { describe, expect, it } from "vitest";
import { forecastRecord } from "../../src/calc/accuracy";
import { OUT_OF_SCOPE_KEYS } from "../../src/calc/report";
import type { CollectedDoc } from "../../src/collect/docs";
import { readPicked, type FolderFile } from "../../src/collect/folder";
import { buildConvInput, type ExtDoc } from "../../src/collect/inputs";
import { makeReport, overlayInput, vsForecast } from "../../src/pipeline";
import { diffPaths, loadCase } from "../calc/golden";
import { KNOWN_CHANGES } from "../calc/known_changes";
import { caseInput } from "../convert/cases";

const c = loadCase("base");
const ASOF = c.case.asof;
const NOW = ASOF + " 09:00:00";
const JOURNAL = "수집/위하고/261031 분개장 자동수집.json";

/** golden input 을 '내 문서\CEO보고' 폴더의 부모에서 고른 것처럼 (윈도 경로, 고친 때는 모두 같음) */
async function picked(): Promise<FolderFile[]> {
  const list = Object.entries(caseInput("base")).map(([rel, bytes]) => ({
    rel: ("내 문서/CEO보고/" + rel).replace(/\//g, "\\"),
    file: new File([bytes as BlobPart], rel.split("/").pop()!, { lastModified: Date.UTC(2026, 10, 1) }),
  }));
  list.push({ rel: "내 문서\\CEO보고\\보고서.py", file: new File(["x"], "보고서.py") });
  const { files, skipped } = await readPicked(list);
  expect(skipped).toBe(1);
  return files;
}

function compareR(R: Record<string, unknown>, stop: string[]): string[] {
  const exp = c.expected.weekly!;
  const bad: string[] = [];
  const changed = (path: string) => KNOWN_CHANGES.find((k) => k.case === "base" && k.kind === "weekly" && k.path === path);
  const ch = changed("stop");
  bad.push(...(ch ? ch.check(exp.stop, stop) : diffPaths(exp.stop, stop)).map((d) => "stop " + d));
  for (const key of Object.keys(exp.R!)) {
    if ((OUT_OF_SCOPE_KEYS as readonly string[]).includes(key) || key === "auto_facts") continue;
    const k = changed(`R.${key}`);
    const want = (exp.R as Record<string, unknown>)[key];
    bad.push(...(k ? k.check(want, R[key]) : diffPaths(want, R[key])).map((d) => `${key} ${d}`));
  }
  return bad;
}

describe("사이트 보고서 만들기 (base)", () => {
  it("폴더만 불러온 경우: R 이 golden 주간 R 과 같다", async () => {
    const folder = await picked();
    expect(folder.some((f) => f.path === "입력/설정.csv")).toBe(true);
    const made = await makeReport(buildConvInput(folder, []), "weekly", ASOF, null, NOW);
    expect(made.conv.code).toBe(0);
    expect(made.ok).toBe(true);
    expect(compareR(made.R!, made.stop)).toEqual([]);
    console.log(`base 주간: 변환 ${made.ms.convert.toFixed(0)}ms · 계산 ${made.ms.report.toFixed(0)}ms`);
  });

  it("분개장이 확장 자료로만 온 경우 (확장이 준 파일 이름): 같은 R", async () => {
    const all = await picked();
    const jf = all.find((f) => f.path === JOURNAL)!;
    const folder = all.filter((f) => f !== jf);
    const doc = JSON.parse(new TextDecoder().decode(jf.bytes)) as CollectedDoc;
    const ext: ExtDoc[] = [{ doc, name: "261031 분개장 자동수집.json" }];
    const inp = buildConvInput(folder, ext);
    expect(inp.from[JOURNAL]).toBe("확장");
    const made = await makeReport(inp, "weekly", ASOF, null, NOW);
    expect(made.ok).toBe(true);
    expect(compareR(made.R!, made.stop)).toEqual([]);
  });

  it("분개장이 이름 없는 예전 확장 자료로만 온 경우: 지은 이름(수집시각 날짜)으로 읽어 보고가 만들어진다", async () => {
    const all = await picked();
    const jf = all.find((f) => f.path === JOURNAL)!;
    const doc = JSON.parse(new TextDecoder().decode(jf.bytes)) as CollectedDoc;
    const inp = buildConvInput(all.filter((f) => f !== jf), [{ doc }]);
    expect(Object.keys(inp.files)).toContain("수집/위하고/261105 분개장 자동수집.json");
    const made = await makeReport(inp, "weekly", ASOF, null, NOW);
    expect(made.conv.code).toBe(0);
    expect(made.ok).toBe(true);
    expect(made.conv.lines[0]).toMatch(/^WEHAGO 장부 기준일 /);
  });

  it("분개장이 하나도 없으면 변환 코드 3 → 숫자 없이 까닭만", async () => {
    const folder = (await picked()).filter((f) => f.path !== JOURNAL);
    const made = await makeReport(buildConvInput(folder, []), "weekly", ASOF, null, NOW);
    expect(made.conv.code).toBe(3);
    expect(made.ok).toBe(false);
    expect(made.R).toBeNull();
    expect(made.stop[0]).toMatch(/자료 변환을 하지 못해/);
  });

  it("입력 폴더의 예전 자동분석.json 은 읽지 않고 기록에 남긴다", () => {
    const enc = new TextEncoder();
    const { fs, dropped } = overlayInput({ "입력/자동분석.json": enc.encode("{}"), "입력/설정.csv": enc.encode("a"), "입력/x.xlsx": enc.encode("b") }, { "손익.csv": "﻿손익" });
    expect(dropped).toEqual(["자동분석.json"]);
    expect(fs).toEqual({ "설정.csv": "a", "손익.csv": "손익" });
  });

  it("지난 예상 대비 실제: 같은 자료로 한 주 앞 기록과 견준다", async () => {
    const made = await makeReport(buildConvInput(await picked(), []), "weekly", ASOF, null, NOW);
    const prev = { ...forecastRecord(made.R!), asof: "2026-10-26" };
    const a = vsForecast(prev, made.data!, made.R!);
    expect(a.from).toBe("2026-10-27");
    expect(a.to).toBe(ASOF);
    expect(a.end.actual).toBe(made.R!["s2"]["start"]);
  });
});
