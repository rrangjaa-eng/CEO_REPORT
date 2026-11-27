// 대표 보고의 숫자·날짜 글자 (한곳). 금액은 render.py 의 won 과 같은 글자: 천 단위 쉼표, 음수는 '−'(U+2212).
// 비율(%·배)도 같은 '−' 를 쓴다 (render.py 는 비율만 '-' 였음 — 한 화면에 빼기표가 두 가지로 보이지 않게 통일).
import { pyFixed } from "../model/py";
import { pct as pyPct, won } from "../model/util";
import { parseIso, weekday, type IsoDate } from "../model/dates";
import { h, type Html } from "./html";

export { won };

export const UNKNOWN = "미확인";

/** 숫자 칸 하나. data-k = 이 숫자가 온 자리(시험이 R 과 1원까지 맞춰 봄), data-v = 원래 값 (모르면 빈 글).
 *  모르는 값은 0 이 아니라 empty 글자('미확인' 등)를 눈에 띄게 보인다. */
export function money(v: number | null | undefined, key: string, empty = UNKNOWN, cls = ""): Html {
  const unknown = v === null || v === undefined;
  return h("span", {
    class: ["m", unknown ? "na" : v < 0 ? "neg" : "", cls].filter(Boolean).join(" "),
    "data-k": key,
    "data-v": unknown ? "" : String(v),
  }, unknown ? empty : won(v));
}

/** 부호를 늘 붙인 금액: +1,000 · −1,000 · 0 */
export function signed(v: number): string {
  return (v > 0 ? "+" : v < 0 ? "−" : "") + won(Math.abs(v));
}

export function unifyMinus(s: string): string {
  return s.replace(/^-/, "−");
}

/** util.pct 와 같고 빼기표만 '−' */
export function pct(a: number | null | undefined, b: number | null | undefined, empty = "판단 불가"): string {
  return unifyMinus(pyPct(a, b, empty));
}

/** '%.1f배' */
export function times(a: number, b: number): string {
  return unifyMinus(pyFixed(a / b, 1)) + "배";
}

/** 11/06 */
export function md(d: IsoDate): string {
  return d.slice(5).replace("-", "/");
}

/** 11/06(금) */
export function day(d: IsoDate): string {
  return `${md(d)}(${"월화수목금토일"[weekday(d)]})`;
}

/** '2026-10' → '10월' */
export function ymText(ym: string): string {
  const m = /^\d{4}-(\d{2})$/.exec(ym || "");
  return m ? `${parseInt(m[1]!, 10)}월` : ym;
}

export function monthOf(d: IsoDate): number {
  return parseIso(d)[1];
}
