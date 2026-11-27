// 파이썬이 JSON 값을 글자로 바꾸는 모양 (str(v), str(v or "")). JSON.parse 는 1 과 1.0 을 가르지 못하므로
// 정수 값의 실수(예: 1234.0)는 파이썬과 달리 '1234' 가 된다 (확장이 쓰는 파일에는 그런 값이 없음 — 계획 문서 '알려진 한계').
import { pyReprFloat } from "./xls";

/** 파이썬 str(v) (JSON 값). */
export function pyStrJ(v: unknown): string {
  if (v === null || v === undefined) return "None";
  if (v === true) return "True";
  if (v === false) return "False";
  if (typeof v === "number") return Number.isInteger(v) && Math.abs(v) < 1e16 ? String(v) : Number.isInteger(v) ? BigInt(v).toString() : pyReprFloat(v);
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

/** 파이썬 bool(v) (JSON 값). */
export function pyTruthy(v: unknown): boolean {
  if (v === null || v === undefined || v === false || v === 0 || v === "") return false;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === "object") return Object.keys(v as object).length > 0;
  return true;
}

/** 파이썬 str(v or "") */
export function pyStrOr(v: unknown): string {
  return pyTruthy(v) ? pyStrJ(v) : "";
}

/** isinstance(v, int) and not isinstance(v, bool) */
export function isPyInt(v: unknown): v is number {
  return typeof v === "number" && Number.isInteger(v);
}

export function isDict(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** "%d" % v (정수 값인 숫자). */
export function pyD(v: number): string {
  const t = Math.trunc(v);
  return Math.abs(t) < 1e16 ? String(t === 0 ? 0 : t) : BigInt(t).toString();
}
