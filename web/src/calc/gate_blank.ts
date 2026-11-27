// gate.py blank_funds · plan_gaps · blank_plan_gaps: 막히거나 자금계획서가 빠진 달이 있으면 자금 숫자를 비운다.
import type { Obj } from "./ctx";
import { problems } from "./gate";
import { cmpStr } from "../model/py";
import { parseIso } from "../model/dates";

const isDict = (x: unknown): x is Obj => x !== null && typeof x === "object" && !Array.isArray(x);
const has = (o: Obj, k: string) => Object.prototype.hasOwnProperty.call(o, k);

/** 자료가 막히면 자금 숫자(통장 합계·여유 자금·예상 잔액·최저 잔액)를 비운다. 계산한 값은 R._gate_hidden 에. -> 막는 까닭 목록 */
export function blankFunds(R: Obj): string[] {
  const probs = problems(R as never);
  if (!probs.length || (R["_gate_hidden"] !== undefined && R["_gate_hidden"] !== null)) return probs;
  const hidden: Obj = {};
  const s1: Obj = R["s1"] || {}, s2: Obj = R["s2"] || {};
  for (const k of ["total", "available", "end", "start_calc", "start_bank"]) {
    if (has(s1, k)) { hidden["s1." + k] = s1[k]; s1[k] = null; }
  }
  for (const a of (s1["accounts"] as unknown[]) || []) {
    for (const k of ["balance", "available"]) {
      if (isDict(a) && has(a, k)) a[k] = null;
    }
  }
  if (has(s2, "start")) { hidden["s2.start"] = s2["start"]; s2["start"] = null; }
  if (isDict(s2["min"])) {
    const mn: Obj = {};
    for (const m of Object.keys(s2["min"])) mn[m] = [null, null];
    s2["min"] = mn;
  }
  for (const p of (s2["periods"] as Obj[]) || []) {
    for (const mode of ["firm", "spend", "all"]) {
      const r: Obj = p[mode] || {};
      for (const k of ["bal", "low", "low_date", "avail"]) if (has(r, k)) r[k] = null;
    }
  }
  for (const b of (s2["buckets"] as unknown[]) || []) {
    if (isDict(b)) for (const k of ["bal_firm", "bal_all"]) if (has(b, k)) b[k] = null;
  }
  const rs = R["risks"];
  if (Array.isArray(rs)) {
    const kept = rs.filter((r) => !(isDict(r) && r["area"] === "자금" && pyStrOr(r["fact"]).includes("최저 계산 잔액")));
    kept.unshift({
      level: "높음", area: "자금", fact: `자료 확인에서 막혀 앞으로의 잔액·여유 자금을 판단하지 않음: ${probs[0]}`,
      action: "맨 위 경고의 자료를 받아 넣고 다시 만드세요.",
    });
    R["risks"] = kept;
  }
  R["_gate_hidden"] = hidden;
  R["_gate_probs"] = probs;
  return probs;
}

function pyStrOr(x: unknown): string {
  return x === null || x === undefined || x === "" || x === 0 || x === false ? "" : String(x);
}

/** 보고 기간 안에 자금계획서를 받지 못한 달이 있는 기간 -> [[기간 이름, [빠진 달]]] */
export function planGaps(R: Obj): [string, string[]][] {
  const fp = R["fundplan"] as Obj | null | undefined;
  if (!fp || !fp["used"]) return [];
  const have = new Set<string>([...((fp["months"] as string[]) || []), ...((fp["received"] as string[]) || [])]);
  const out: [string, string[]][] = [];
  const [ay, am] = parseIso(R["asof"]);
  for (const p of ((R["s2"] || {})["periods"] as Obj[]) || []) {
    const end = p["end"] as string | null | undefined;
    if (end === null || end === undefined) continue;
    const [ey, em] = parseIso(end);
    let y = ay, m = am;
    const lack: string[] = [];
    while (y < ey || (y === ey && m <= em)) {
      const s = `${y}-${String(m).padStart(2, "0")}`;
      if (!have.has(s)) lack.push(s);
      if (m === 12) { y += 1; m = 1; } else m += 1;
    }
    if (lack.length) out.push([p["label"] || "", lack]);
  }
  return out;
}

/** 자금계획서가 빠진 달까지 걸친 기간의 잔액·최저 잔액·여유 자금을 비운다. -> 경고 한 줄 ('' 이면 없음) */
export function blankPlanGaps(R: Obj): string {
  const gaps = planGaps(R);
  if (!gaps.length) return "";
  const labels = new Set(gaps.map(([l]) => l));
  for (const p of ((R["s2"] || {})["periods"] as Obj[]) || []) {
    if (labels.has(p["label"] || "")) {
      p["plan_gap"] = true;
      for (const mode of ["firm", "spend", "all"]) {
        const r: Obj = p[mode] || {};
        for (const k of ["bal", "low", "low_date", "avail"]) if (has(r, k)) r[k] = null;
      }
    }
  }
  const months = [...new Set(gaps.flatMap(([, ms]) => ms))].sort(cmpStr);
  return `자금계획서를 받지 못한 달(${months.join(", ")})이 있어 ${gaps.map(([l]) => l).join("·")} 여유 자금은 비웠습니다 — `
    + "위하고 확장에서 '모두 받기'로 그 달을 받은 뒤 다시 만드세요";
}
