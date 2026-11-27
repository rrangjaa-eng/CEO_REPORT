// 보고서.py main 에서 compute 뒤에 R 을 고치는 단계 중 계산 핵심 범위만 옮김 (그 순서 그대로).
// 범위 밖(월간 부록 xchk·cf·credit·re·taxadj·filing·payroll, 지난 보고 비교, gasu·recon 등)은 OUT_OF_SCOPE_KEYS.
import type { Data } from "../model/data";
import type { FileSet } from "../model/csv";
import type { IsoDate } from "../model/dates";
import type { Kind, Obj } from "./ctx";
import { compute } from "./compute";
import { problems } from "./gate";
import { blankFunds } from "./gate_blank";

export const OUT_OF_SCOPE_KEYS = [
  "out_group", "out_merge_only", "xchk", "cf", "credit_brief", "credit", "re", "taxadj", "filing", "filing_help",
  "payroll", "todo_decisions", "gasu", "recon", "recon_rows",
] as const;

/** insights.read_facts: 자동분석.json 이 객체면 그것, 아니면 null */
export function readFacts(files: FileSet): Obj | null {
  const t = files["자동분석.json"];
  if (t === undefined) return null;
  try {
    const x: unknown = JSON.parse(t.replace(/^﻿/, ""));
    return x !== null && typeof x === "object" && !Array.isArray(x) ? (x as Obj) : null;
  } catch {
    return null;
  }
}

export function buildReport(d: Data, files: FileSet, kind: Kind, asof: IsoDate,
                            payday: IsoDate | null = null): { R: Obj; stop: string[] } {
  const R = compute(d, kind, asof, null, null, payday);
  R["auto_facts"] = readFacts(files);
  blankFunds(R);
  // 주간 last_pay: 지난 보고 기록(week_prev)이 없으면 compute 가 낸 값과 같다 (새 시스템엔 지난 보고 폴더가 아직 없음)
  const stop = problems(R as never);
  return { R, stop };
}
