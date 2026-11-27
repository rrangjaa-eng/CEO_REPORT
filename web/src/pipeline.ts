// 화면이 보고서를 만드는 길 하나: 변환 → 입력 폴더 글에 변환 결과 덮기 → loadData → buildReport.
// 시험(web/tests/site)도 이 함수를 그대로 부른다.
import { compareForecast, type Accuracy, type ForecastRecord } from "./calc/accuracy";
import type { Obj } from "./calc/ctx";
import { buildReport } from "./calc/report";
import { convert, type ConvertResult } from "./convert/run";
import { INPUT, listFiles, join, type ConvFiles } from "./convert/files";
import { decodeText, type FileSet } from "./model/csv";
import { loadData, type Data } from "./model/data";
import type { IsoDate } from "./model/dates";
import type { ConvInput } from "./collect/inputs";

export type Kind = "weekly" | "monthly";

/** 변환이 아직 새로 만들지 않는 입력 파일 (파이썬 변환만 만듦). 폴더에 예전 것이 있으면 이번 자료와 맞지 않으므로 읽지 않는다. */
export const STALE_INPUTS = ["자동분석.json", "확인할것.json"];

/** data.load 가 읽는 입력 글 묶음: 입력/ 바로 아래 글 파일(csv·json·txt) 위에 변환이 만든 글을 덮는다. */
export function overlayInput(input: ConvFiles, written: Record<string, string>): { fs: FileSet; dropped: string[] } {
  const fs: FileSet = {};
  const dropped: string[] = [];
  for (const name of listFiles(input, INPUT).sort()) {
    if (!/\.(csv|json|txt)$/i.test(name)) continue;
    if (STALE_INPUTS.includes(name)) { dropped.push(name); continue; }
    const t = decodeText(input[join(INPUT, name)] as Uint8Array);
    if (t !== null) fs[name] = t;
  }
  for (const [name, text] of Object.entries(written)) fs[name] = text.startsWith("﻿") ? text.slice(1) : text;
  return { fs, dropped };
}

export interface Made {
  conv: ConvertResult;
  /** 변환 기록에 덧붙인 화면 쪽 줄 */
  notes: string[];
  ok: boolean;
  /** 보고를 막은 까닭 (변환 실패 포함). ok 면 [] */
  stop: string[];
  R: Obj | null;
  data: Data | null;
  ms: { convert: number; report: number };
}

/** now = 'YYYY-MM-DD HH:MM:SS' (서울 시각). */
export async function makeReport(inp: ConvInput, kind: Kind, asof: IsoDate, payday: IsoDate | null, now: string,
                                 clock: () => number = () => performance.now()): Promise<Made> {
  const t0 = clock();
  const conv = await convert(inp.files, asof, now, { mtimes: inp.mtimes, fileDays: inp.fileDays });
  const t1 = clock();
  const notes: string[] = [];
  if (conv.code !== 0) {
    const why = conv.lines[0] ?? "변환하지 못함";
    return { conv, notes, ok: false, stop: [`자료 변환을 하지 못해 보고를 만들지 않음 (코드 ${conv.code}) — ${why}`], R: null, data: null,
             ms: { convert: t1 - t0, report: 0 } };
  }
  const { fs, dropped } = overlayInput(inp.files, conv.files);
  if (dropped.length) notes.push(`입력 폴더의 ${dropped.join(", ")} 는 예전 프로그램이 만든 것이라 읽지 않음 (이 화면의 변환은 아직 새로 만들지 않음)`);
  const data = loadData(fs);
  const { R, stop } = buildReport(data, fs, kind, asof, payday);
  const t2 = clock();
  return { conv, notes, ok: stop.length === 0, stop, R, data, ms: { convert: t1 - t0, report: t2 - t1 } };
}

/** 지난 예상(prev) 대비 실제: 지난 기준일 다음 날 ~ 이번 기준일의 통장 입출금, 끝 잔액 = 이번 보고의 시작 자금. */
export function vsForecast(prev: ForecastRecord, data: Data, R: Obj): Accuracy {
  const s2 = (R["s2"] || {}) as Obj;
  const end = typeof s2["start"] === "number" ? (s2["start"] as number) : null;
  const txns = data.txns.map((t) => ({ date: t.date, io: t.io, amount: t.amount, vendor: t.vendor, cat: t.cat }));
  return compareForecast(prev, txns, R["asof"] as IsoDate, end);
}
