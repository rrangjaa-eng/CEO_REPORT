// golden/RULES.md '새 시스템에서 바꿀 것'(사용자 결정 2026-11-27) 때문에 기대값과 달라야 하는 곳.
// C2 는 과대·과소 점검 고침(사용자 결정 2026-11-28, web/src/model/rules.ts overdueOutNextFriday).
// 여기 적은 (사례, 종류, 키)만 기대값 대신 check 로 본다. check 는 '정확히 그 결정만큼만' 달라졌는지 따진다.
import { diffPaths } from "./golden";

type O = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
export interface KnownChange {
  case: string; kind: "weekly" | "monthly"; path: string; rule: string;
  /** 차이 목록(비면 통과). want = 옛 기대값, got = 새 결과 */
  check: (want: any, got: any) => string[]; // eslint-disable-line @typescript-eslint/no-explicit-any
}

/** F6 사례: 거래처코드 없는 '가상이름갑'(자금계획서, 11-13)과 '가상이름을'(자금일정, 11-11)이 같은 4,410,000원이라
 *  옛 프로그램은 한 건으로 맞췄다. 새 결정은 이름이 다르면 다른 건 → 계획은 added, 일정은 missing 으로 남고 출금이 4,410,000 늘어난다. */
const F6_AMT = 4_410_000;
const isPlan = (x: O) => x?.["desc"] === "가상이름갑" && x?.["amount"] === F6_AMT;
const isOld = (x: O) => x?.["desc"] === "가상이름을" && x?.["amount"] === F6_AMT;

/** 숫자는 차이가 0 또는 F6_AMT, 글은 안의 금액들이 그만큼만 다를 때 통과 */
function onlyShiftedBy(want: unknown, got: unknown, amt: number): string[] {
  const bad: string[] = [];
  const nums = (s: string) => (s.match(/[−-]?\d[\d,]*/g) ?? []).map((t) => Number(t.replace(/[,−]/g, (c) => (c === "−" ? "-" : ""))));
  const walk = (w: unknown, g: unknown, p: string): void => {
    if (typeof w === "number" && typeof g === "number") {
      if (w !== g && Math.abs(w - g) !== amt) bad.push(`${p}: ${w} → ${g}`);
    } else if (typeof w === "string" && typeof g === "string") {
      if (w === g) return;
      const a = nums(w), b = nums(g);
      const sameText = w.replace(/[−-]?\d[\d,]*/g, "#") === g.replace(/[−-]?\d[\d,]*/g, "#");
      if (!sameText || a.length !== b.length || a.some((x, i) => x !== b[i] && Math.abs(x - b[i]!) !== amt)) bad.push(`${p}: ${w} → ${g}`);
    } else if (Array.isArray(w) && Array.isArray(g)) {
      if (w.length !== g.length) bad.push(`${p}: 길이 ${w.length} → ${g.length}`);
      else w.forEach((x, i) => walk(x, g[i], `${p}[${i}]`));
    } else if (w && g && typeof w === "object" && typeof g === "object") {
      const ks = new Set([...Object.keys(w), ...Object.keys(g)]);
      for (const k of ks) walk((w as O)[k], (g as O)[k], `${p}.${k}`);
    } else if (w !== g) bad.push(`${p}: ${JSON.stringify(w)} → ${JSON.stringify(g)}`);
  };
  walk(want, got, "");
  return bad;
}

const F6_SHIFT = (want: unknown, got: unknown) => {
  const d = onlyShiftedBy(want, got, F6_AMT);
  return d;
};

/** 옛 결과: 맞춘 계획 줄이 일정 줄을 대신함. 새 결과: 일정 줄(가상이름을)이 '자금계획서에 없음'으로 남아 한 줄 많고, 나머지는 같음. */
function eventsCheck(w: O[], g: O[]): string[] {
  const extra = g.filter(isOld);
  if (extra.length !== 1) return [`가상이름을 줄 수 ${extra.length} (1이어야 함)`];
  if (extra[0]!["plan_note"] !== "자금계획서에 없음") return ["가상이름을 줄에 '자금계획서에 없음' 표시 없음"];
  return diffPaths(w, g.filter((e) => !isOld(e)));
}

/** C2 (사용자 결정 2026-11-28): 예정일 지난 자금일정·프로젝트집행 지급 중 지급 기록이 없고 정기 지출이 아닌 줄은
 *  '지난 날짜'에서 빠져 다음 금요일의 예상 지출(dated, late_out 표시)로 온다. rows = [원래 예정일, 거래처, 금액]. */
function lateOutCheck(rows: [string, string, number][], friday: string) {
  const amt = rows.reduce((t, r) => t + r[2], 0);
  const isMoved = (e: O) => rows.some(([d, desc, a]) => e?.["date"] === d && e?.["desc"] === desc && e?.["amount"] === a);
  return (w: O, g: O): string[] => {
    const out: string[] = [];
    const late = (g["dated"] as O[]).filter((e) => e["late_out"]);
    const gotRows = late.map((e) => [e["orig_date"], e["desc"], e["amount"]]);
    if (JSON.stringify(gotRows) !== JSON.stringify(rows)) out.push(`옮긴 줄이 다름: ${JSON.stringify(gotRows)}`);
    if (late.some((e) => e["date"] !== friday || e["firm"] !== false || e["must"] !== false || e["io"] !== "out")) out.push("옮긴 줄이 다음 금요일의 예상(확정 아님) 지출이 아님");
    out.push(...diffPaths(w["dated"], (g["dated"] as O[]).filter((e) => !e["late_out"])).map((s) => "dated" + s));
    out.push(...diffPaths((w["past"] as O[]).filter((e) => !isMoved(e)), g["past"]).map((s) => "past" + s));
    if ((w["past"] as O[]).filter(isMoved).length !== rows.length) out.push("옛 기대값의 지난 날짜 표에 옮길 줄이 없음(사례가 바뀜)");
    if (g["past_out_n"] !== w["past_out_n"] - rows.length) out.push(`past_out_n: ${w["past_out_n"]} → ${g["past_out_n"]}`);
    out.push(...onlyShiftedBy({ ...w, dated: null, past: null, past_out_n: 0 }, { ...g, dated: null, past: null, past_out_n: 0 }, amt));
    return out;
  };
}
const C2_DONE: [string, string, number][] = [["2026-10-05", "가상창D", 1_400_000]];
const C2_YEAR: [string, string, number][] = [["2026-12-25", "건물관리", 8_000_000], ["2026-12-05", "소프트웨어", 1_200_000], ["2026-12-20", "기업은행", 800_000]];

export const KNOWN_CHANGES: KnownChange[] = [
  {
    case: "f_other_vendor_near", kind: "weekly", path: "R.fundplan", rule: "F6",
    check: (w: O, g: O) => {
      const out: string[] = [];
      const pair = (w.matched as O[]).find((m) => isPlan(m["plan"]) && isOld(m["old"]));
      if (!pair) out.push("옛 기대값에 가상이름갑↔가상이름을 맞춤이 없음(사례가 바뀜)");
      if (!(g.added as O[]).some(isPlan)) out.push("가상이름갑이 added 에 없음");
      if (!(g.missing as O[]).some(isOld)) out.push("가상이름을이 missing 에 없음");
      if ((g.matched as O[]).some((m) => isPlan(m["plan"]))) out.push("가상이름갑이 아직 matched 에 있음");
      const strip = (x: O) => ({ ...x, matched: (x.matched as O[]).filter((m) => !isPlan(m["plan"])),
        added: (x.added as O[]).filter((a) => !isPlan(a)), missing: (x.missing as O[]).filter((m) => !isOld(m)) });
      return [...out, ...diffPaths(strip(w), strip(g))];
    },
  },
  { case: "f_other_vendor_near", kind: "weekly", path: "R.events", rule: "F6", check: (w: O[], g: O[]) => eventsCheck(w, g) },
  {
    case: "f_other_vendor_near", kind: "weekly", path: "R.s2", rule: "F6",
    // dated(날짜 있는 일정)는 events 와 같은 규칙, 나머지 합계·잔액은 정확히 4,410,000 만큼만 다름
    check: (w: O, g: O) => [...eventsCheck(w["dated"], g["dated"]),
      ...F6_SHIFT({ ...w, dated: null }, { ...g, dated: null })],
  },
  { case: "f_other_vendor_near", kind: "weekly", path: "R.s7", rule: "F6", check: F6_SHIFT },
  { case: "f_other_vendor_near", kind: "weekly", path: "R.risks", rule: "F6", check: F6_SHIFT },
  {
    // U10: 자금계획서는 이 회사 것(설정 회사명과 같음)이므로 분개장 쪽만 알린다.
    case: "u_other_company", kind: "weekly", path: "stop", rule: "U10",
    check: (w: string[], g: string[]) => diffPaths(w.filter((s) => s.startsWith("분개장이 다른 회사")), g),
  },
  { case: "f_done_window", kind: "weekly", path: "R.s2", rule: "C2", check: lateOutCheck(C2_DONE, "2026-11-06") },
  { case: "f_done_window", kind: "weekly", path: "R.risks", rule: "C2", check: (w: unknown, g: unknown) => onlyShiftedBy(w, g, 1_400_000) },
  { case: "u_year_change", kind: "weekly", path: "R.s2", rule: "C2", check: lateOutCheck(C2_YEAR, "2027-01-08") },
  { case: "u_year_change", kind: "monthly", path: "R.s2", rule: "C2", check: lateOutCheck(C2_YEAR, "2027-01-08") },
];
