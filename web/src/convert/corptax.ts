// corptax.py(변환 쪽: read·from_journal·carry_rows)와 그 아래 taxlaw.value·taxreturn.load/credits·taxadj.adjust·dividend.read_settings.
import { dictReader } from "../model/csv";
import type { IsoDate } from "../model/dates";
import { daysInMonth, parseIso, weekday, addDays, ymd } from "../model/dates";
import { fmtComma, pyFloatParse, pyG, pyIntParse, pyIsDigit, pyRemoveSpace, pyRound, pyStrip } from "../model/py";
import { closingPlLine } from "./closing";
import type { Cfg } from "./config";
import { exists, join, readText, readUtf8, type ConvFiles } from "./files";
import { classify, net } from "./pl";
import { isDict } from "./pyjson";
import { assetRows, rawFiles } from "./screens";
import { fromBank, row as taxRow, type TaxRow } from "./tax";
import { squash, type JLine } from "./wehago";

const fmt = fmtComma;
const sq = (t: unknown) => pyRemoveSpace(t === null || t === undefined ? "" : String(t));
const s = (v: unknown) => (v === null || v === undefined ? "" : String(v));

/** CSV 파일을 DictReader 처럼 (UTF-8·CP949). 없으면 null, 못 읽으면 throw. */
function readDicts(files: ConvFiles, path: string): Record<string, string | null>[] | null {
  const text = readText(files, path);
  if (text === undefined) return null;
  if (text === null) throw new Error("글자 인코딩을 읽지 못함");
  return dictReader(text);
}

// ───────────── taxlaw ─────────────
type Unit = "글" | "비율" | "원" | "시간";
const UNIT: Record<string, Unit> = { "법인세율": "글", "최저한세율": "비율", "대손충당금률": "비율", "접대비기본한도": "원", "접대비수입비율": "비율",
  "인정이자율": "비율", "승용차상각한도": "원", "승용차기록없음한도": "원", "창업감면_과밀밖": "비율", "창업감면_과밀밖청년": "비율", "창업감면_과밀안청년": "비율",
  "고용공제_수도권": "원", "고용공제_지방": "원", "고용공제_수도권청년": "원", "고용공제_지방청년": "원", "금융소득기준": "원", "배당원천세율": "비율",
  "건강보험료율": "비율", "최저시급": "원", "월소정시간": "시간", "가산율": "비율", "국민연금요율": "비율", "국민연금상한": "원", "장기요양비율": "비율",
  "고용보험요율": "비율", "식대비과세": "원", "근로간이지급주기": "글", "사업기타간이지급주기": "글" };
const SRC = "공개 세법 자료 (2026-11-12 확인)";
type Def = [number | string | null, string, string, IsoDate | null];
const DEFAULTS: Record<number, Record<string, Def>> = {
  2025: {
    "법인세율": ["2억 9% · 200억 19% · 3천억 21% · 초과 24%", "자료확인", SRC, null], "최저한세율": [0.07, "자료확인", SRC, null],
    "대손충당금률": [0.01, "자료확인", SRC, null], "접대비기본한도": [36_000_000, "자료확인", SRC, null], "접대비수입비율": [0.003, "자료확인", SRC, null],
    "인정이자율": [0.046, "자료확인", SRC, null], "승용차상각한도": [8_000_000, "자료확인", SRC, null], "승용차기록없음한도": [15_000_000, "자료확인", SRC, null],
    "창업감면_과밀밖": [0.5, "자료확인", "조특법 6조 (2025년 창업 당시)", null], "창업감면_과밀밖청년": [1.0, "자료확인", "조특법 6조 (2025년 창업 당시)", null],
    "창업감면_과밀안청년": [0.5, "자료확인", "조특법 6조 (2025년 창업 당시)", null],
    "고용공제_수도권": [8_500_000, "자료확인", "조특법 29조의8 (3년 같은 금액)", null], "고용공제_지방": [9_500_000, "자료확인", "조특법 29조의8 (3년 같은 금액)", null],
    "고용공제_수도권청년": [14_500_000, "자료확인", "조특법 29조의8 (3년 같은 금액)", null], "고용공제_지방청년": [15_500_000, "자료확인", "조특법 29조의8 (3년 같은 금액)", null],
    "금융소득기준": [20_000_000, "자료확인", SRC, null], "배당원천세율": [0.14, "자료확인", SRC, null], "건강보험료율": [0.0709, "자료확인", SRC, null],
    "최저시급": [10_030, "자료확인", "2025년 적용 최저임금 고시", null], "월소정시간": [209, "자료확인", "근로기준법 (주 40시간 + 주휴 8시간) × 4.345주", null],
    "가산율": [0.5, "자료확인", "근로기준법 56조", null], "국민연금요율": [0.09, "자료확인", "국민연금법 88조", null],
    "국민연금상한": [6_170_000, "자료확인", "2024-07 ~ 2025-06 기준소득월액 상한", null], "장기요양비율": [0.1295, "자료확인", SRC, null],
    "고용보험요율": [0.018, "자료확인", "고용보험료징수법 시행령 12조", null], "식대비과세": [200_000, "자료확인", "소득세법 시행령 17조의2", null],
    "근로간이지급주기": ["반기 (1~6월분 7월 말, 7~12월분 다음 해 1월 말)", "자료확인", "국세청 — 매월 제출은 2027년 1월 지급분부터", null],
    "사업기타간이지급주기": ["매월 (지급한 달의 다음 달 말일)", "자료확인", SRC, null],
  },
  2026: {
    "법인세율": ["2억 10% · 200억 20% · 3천억 22% · 초과 25%", "자료확인", "2025-12 국회 통과, 2026년 시작 사업연도부터 1%p 인상", null],
    "건강보험료율": [0.0719, "자료확인", SRC, null], "최저시급": [10_320, "자료확인", "2026년 적용 최저임금 고시", null],
    "국민연금요율": [0.095, "자료확인", "2025 연금개혁, 2026년부터 해마다 0.5%p 인상", null],
    "국민연금상한": [6_370_000, "자료확인", "2025-07 ~ 2026-06 기준소득월액 상한 (7월마다 바뀜)", "2026-07-01"],
    "장기요양비율": [0.1314, "자료확인", SRC, null],
    "고용공제_수도권": [null, "미확인", "조특법 29조의8 개정 (시행 2026-07-01): 1·2·3년차 금액 다름 — 세무사 확인", "2026-07-01"],
    "고용공제_지방": [null, "미확인", "조특법 29조의8 개정 (시행 2026-07-01): 1·2·3년차 금액 다름 — 세무사 확인", "2026-07-01"],
    "고용공제_수도권청년": [null, "미확인", "조특법 29조의8 개정 (시행 2026-07-01): 1·2·3년차 금액 다름 — 세무사 확인", "2026-07-01"],
    "고용공제_지방청년": [null, "미확인", "조특법 29조의8 개정 (시행 2026-07-01): 1·2·3년차 금액 다름 — 세무사 확인", "2026-07-01"],
  },
};
const LATEST = 2026;
const PERIODS: Record<string, [IsoDate, IsoDate, number, string][]> = {
  "국민연금상한": [
    ["2024-07-01", "2025-06-30", 6_170_000, "보건복지부 고시 (2024-07 ~ 2025-06 기준소득월액 상한)"],
    ["2025-07-01", "2026-06-30", 6_370_000, "보건복지부 고시 (2025-07 ~ 2026-06 기준소득월액 상한)"],
    ["2026-07-01", "2027-06-30", 6_590_000, "보건복지부고시 제2026-31호 (2026-07 ~ 2027-06 기준소득월액 상한)"],
  ],
};

function lawParse(key: string, text: unknown): number | string | null {
  const t = pyStrip(s(text)).replaceAll(",", "").replaceAll("원", "");
  if (!t) return null;
  if (UNIT[key] === "글") return pyStrip(s(text));
  const pct = t.endsWith("%");
  let v = pyFloatParse(t.replace(/%+$/, ""));
  if (v === null) throw new RangeError("ValueError");
  if (pct || (UNIT[key] === "비율" && v > 1)) v /= 100.0;
  return UNIT[key] === "원" || UNIT[key] === "시간" ? Math.trunc(v) : v;
}

type Mine = [number | string | null, string, string, string, string];
function lawRead(files: ConvFiles, inputDir: string | null): Map<string, Mine> {
  const out = new Map<string, Mine>();
  if (!inputDir) return out;
  const rows = readDicts(files, join(inputDir, "세법기준.csv"));
  if (rows === null) return out;
  for (const r of rows) {
    const y = pyIntParse(s(r["연도"] || ""));
    const k = pyStrip(s(r["항목"] || ""));
    if (y === null || !(k in UNIT)) continue;
    let v: number | string | null;
    try {
      v = lawParse(k, r["값"]);
    } catch {
      continue;
    }
    out.set(`${y}\u0000${k}`, [v, pyStrip(s(r["확인일"] || "")), pyStrip(s(r["출처"] || "")), pyStrip(s(r["시행일"] || "")), pyStrip(s(r["확인한 사람"] || ""))]);
  }
  return out;
}

function lawDefault(year: number, key: string): Def {
  for (const y of Object.keys(DEFAULTS).map(Number).sort((a, b) => b - a)) {
    if (y <= year && key in DEFAULTS[y]!) {
      const [v, st, why, eff] = DEFAULTS[y]![key]!;
      if (y === year) return [v, st, why, eff];
      if (year > LATEST) return [v, "미확인", `${y}년 값을 그대로 씀 — ${year}년 개정 확인 필요`, null];
      return [v, st, why + ` (${y}년 값 그대로)`, eff];
    }
  }
  return [null, "미확인", "기준값 없음", null];
}

function isoDay(text: unknown): IsoDate | null {
  const t = pyStrip(s(text)).slice(0, 10);
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(t);
  if (!m) return null;
  try {
    return ymd(Number(m[1]), Number(m[2]), Number(m[3]));
  } catch {
    return null;
  }
}

function lawShow(key: string, v: number | string | null): string {
  if (v === null) return "모름";
  const u = UNIT[key];
  if (u === "원") return fmt(Math.trunc(Number(v))) + "원";
  if (u === "비율") return pyG(Math.round(Number(v) * 100 * 1e4) / 1e4) + "%";
  if (u === "시간") return pyG(Number(v)) + "시간";
  return String(v);
}

function lawFlags(files: ConvFiles, inputDir: string): Map<string, [string, string, string]> {
  const out = new Map<string, [string, string, string]>();
  const path = join(inputDir, "세법조문.json");
  if (!exists(files, path)) return out;
  const text = readUtf8(files, path, false);
  let S: unknown;
  try {
    if (text === null || text.startsWith("\ufeff")) return out;
    S = JSON.parse(text);
  } catch {
    return out;
  }
  if (!isDict(S)) return out;
  const items = isDict(S["items"]) ? S["items"] : {};
  for (const [tag, it] of Object.entries(items)) {
    if (!isDict(it) || !it["flag"]) continue;
    for (const k of Array.isArray(it["keys"]) ? it["keys"] : []) out.set(String(k), [tag, s(it["시행일자"] ?? ""), s(it["seen"] ?? "")]);
  }
  return out;
}

export interface Law { files: ConvFiles; inputDir: string | null; today: IsoDate }

function lawValueOn(L: Law, key: string, day: IsoDate): [number | string | null, boolean, string] {
  const per = PERIODS[key];
  if (!per) return lawValue(L, Number(day.slice(0, 4)), key);
  const hit = per.filter((p) => p[0] <= day && day <= p[1]);
  if (!hit.length) return [null, false, `${key}: ${day}이 든 기간의 값이 프로그램에 없음 — 고시를 확인해 창에서 넣어 주세요`];
  const [start, end, v, why] = hit[0]!;
  const mine = lawRead(L.files, L.inputDir).get(`${Number(day.slice(0, 4))}\u0000${key}`);
  if (mine !== undefined && mine[0] !== null) {
    const eff = isoDay(mine[3]);
    if (mine[0] === v || (eff && start <= eff && eff <= day)) {
      return [mine[0], true, `확인함 ${mine[1]}${mine[2] ? " · " + mine[2] : ""}${mine[3] ? ` (시행 ${mine[3]})` : ""}`];
    }
    return [v, true, `${mine[1] || "예전"}에 확인한 ${lawShow(key, mine[0])}은 이 기간(${start} ~ ${end}) 값과 다름 → ${lawShow(key, v)} 사용 (${why}). 창 '세법 기준 확인'에서 다시 확인해 주세요`];
  }
  return [v, true, `자료확인 · ${why}`];
}

/** taxlaw.value */
export function lawValue(L: Law, year: number, key: string): [number | string | null, boolean, string] {
  if (key in PERIODS) {
    const ty = Number(L.today.slice(0, 4));
    const day = year === ty ? L.today : year < ty ? ymd(year, 12, 31) : ymd(year, 1, 1);
    return lawValueOn(L, key, day);
  }
  const mine = lawRead(L.files, L.inputDir).get(`${year}\u0000${key}`);
  const [v, st, why, eff] = lawDefault(year, key);
  const fl = L.inputDir ? lawFlags(L.files, L.inputDir).get(key) : undefined;
  if (mine !== undefined && mine[0] !== null) {
    const day = isoDay(mine[1]);
    if (eff && day && day < eff && eff <= L.today) return [mine[0], false, `${mine[1]} 확인 뒤 ${eff} 시행 개정이 있어 다시 확인 필요`];
    if (fl && day && isoDay(fl[2]) && day < isoDay(fl[2])!) return [mine[0], false, `${mine[1]} 확인 뒤 ${fl[0]} 조문이 바뀜 (${fl[2]} 받음) — 다시 확인 필요`];
    return [mine[0], true, `확인함 ${mine[1]}${mine[2] ? " · " + mine[2] : ""}`];
  }
  if (fl) return [v, false, `법령 조문 확인 필요: ${fl[0]} (시행 ${fl[1] || "?"}, ${fl[2]} 받음)`];
  return [v, v !== null && st === "자료확인", `${st} · ${why}`];
}

export function lawChecked(L: Law, year: number, key: string, fallback: number | null = null): [number | null, boolean] {
  const [v, ok] = lawValue(L, year, key);
  return [ok && v !== null ? (v as number) : fallback, !!(ok && v !== null)];
}

// ───────────── taxreturn ─────────────
const TR_COLUMNS = ["연도", "구분", "사업연도", "수입금액", "장부세전이익", "과세표준", "산출세액", "공제감면세액", "총부담세액",
  "기납부세액", "차감납부세액", "지방소득세", "실제납부", "결산확정일", "신고일", "조정", "특별감면", "고용공제", "공제이월", "농특세", "승용차상각비", "승용차상각초과", "승용차취득일"];
const TR_NUMS = [...TR_COLUMNS.slice(3, 13), "특별감면", "고용공제", "공제이월", "농특세", "승용차상각비", "승용차상각초과"];
type TR = Record<string, string | number | null>;

function trN(t: unknown): number | null {
  const x = pyStrip(s(t || "").replaceAll(",", ""));
  if (!x) return null;
  const f = pyFloatParse(x);
  return f === null || !Number.isFinite(f) ? null : Math.trunc(f);
}

export function trLoad(files: ConvFiles, inputDir: string): Map<string, TR> {
  const out = new Map<string, TR>();
  const rows = readDicts(files, join(inputDir, "법인세신고.csv"));
  if (rows === null) return out;
  for (const r of rows) {
    const y = trN(r["연도"]);
    if (!y) continue;
    const d: TR = {};
    for (const k of TR_COLUMNS) d[k] = pyStrip(s(r[k] || ""));
    for (const k of TR_NUMS) d[k] = trN(r[k]);
    out.set(`${y}\u0000${d["구분"] || "확정"}`, d);
  }
  return out;
}

const MIN_RATE = 0.07, NONG_RATE = 0.20;

export interface Credits { corp: number; final: number; nong: number; national: number }

export function trCredits(L: Law, year: number, base: number | null, corp: number | null): Credits | null {
  if (!L.inputDir || base === null || corp === null) return null;
  const last = trLoad(L.files, L.inputDir).get(`${year - 1}\u0000확정`);
  if (!last || last["특별감면"] === null || last["공제이월"] === null) return null;
  const rate = last["산출세액"] ? (last["특별감면"] as number) / (last["산출세액"] as number) : 0.0;
  let mr: number;
  try {
    mr = lawChecked(L, year, "최저한세율", MIN_RATE)[0] || MIN_RATE;
  } catch {
    mr = MIN_RATE;
  }
  const floor = Math.trunc(Math.max(base, 0) * mr);
  const sp = Math.min(Math.trunc(corp * rate), Math.max(corp - floor, 0));
  const after = corp - sp;
  const avail = last["공제이월"] as number;
  const room = Math.max(after - floor, 0);
  const used = Math.min(avail, room);
  const final = after - used;
  const nong = Math.floor(Math.trunc(used * NONG_RATE) / 10) * 10;
  return { corp, final, nong, national: final + nong };
}

// ───────────── corptax ─────────────
const BRACKETS_2026: [number | null, number][] = [[200_000_000, 0.10], [20_000_000_000, 0.20], [300_000_000_000, 0.22], [null, 0.25]];
const BRACKETS_2023: [number | null, number][] = [[200_000_000, 0.09], [20_000_000_000, 0.19], [300_000_000_000, 0.21], [null, 0.24]];
export const LOCAL_RATE = 0.10;

export function corpTax(base: number | null, year: number): number | null {
  if (base === null) return null;
  if (base <= 0) return 0;
  let tax = 0.0, low = 0;
  for (const [top, rate] of year >= 2026 ? BRACKETS_2026 : BRACKETS_2023) {
    const hi = top === null ? base : Math.min(base, top);
    if (hi > low) tax += (hi - low) * rate;
    if (top === null || base <= top) break;
    low = top;
  }
  return Math.trunc(tax);
}

function national(L: Law, base: number | null, year: number): [number | null, number | null, Credits | null] {
  const corp = corpTax(base, year);
  if (corp === null || !L.inputDir) return [corp, corp, null];
  const C = trCredits(L, year, base, corp);
  return [C ? C.national : corp, corp, C];
}

function intOf(text: unknown): number | null {
  const t = pyStrip(s(text || "").replaceAll(",", "").replaceAll("원", ""));
  return pyIsDigit(t) ? Number(t) : null;
}

/** read_ledger: 위하고 고정자산대장 당기 상각 {연도: 합계} */
function readLedger(files: ConvFiles, inputDir: string | null, wehagoDir: string | null): Map<string, number> {
  let rows: Record<string, string | null>[] = [];
  if (wehagoDir) rows = assetRows(rawFiles(files, wehagoDir));
  if (!rows.length && inputDir && exists(files, join(inputDir, "고정자산.csv"))) {
    try {
      rows = readDicts(files, join(inputDir, "고정자산.csv")) ?? [];
    } catch {
      rows = [];
    }
  }
  const out = new Map<string, number>();
  for (const r of rows) {
    const y = pyStrip(s(r["기준연도"] || "")), v = intOf(r["당기상각"]);
    if (pyIsDigit(y) && v !== null) out.set(y, (out.get(y) ?? 0) + v);
  }
  return out;
}

export type Manual = Map<string, number>;   // 연도 → 직접 입력, "대장|연도" → 대장

/** corptax.read */
export function readManual(files: ConvFiles, inputDir: string): Manual {
  let out: Manual = new Map();
  try {
    const rows = readDicts(files, join(inputDir, "감가상각비.csv"));
    if (rows !== null) {
      for (const r of rows) {
        const y = pyStrip(s(r["연도"] || "")), v = intOf(r["연간감가상각비"]);
        if (pyIsDigit(y) && v !== null) out.set(y, v);
      }
    }
  } catch {
    out = new Map();
  }
  for (const [y, v] of readLedger(files, inputDir, null)) out.set("대장|" + y, v);
  return out;
}

interface DepLine { ym: string; name: string; amount: number | null }

function depreciation(accounts: DepLine[], manual: Manual, ym: string, ledger: Map<string, number>) {
  const year = ym.slice(0, 4), months = Number(ym.slice(5, 7));
  const depRows = (y: string) => accounts.filter((r) => r.ym.slice(0, 4) === y && (r.name || "").includes("감가상각비"));
  const booked = depRows(year).filter((r) => r.ym <= ym).reduce((a, r) => a + (r.amount || 0), 0);
  let annual: number | null;
  if (manual.get(year) !== undefined) annual = manual.get(year)!;
  else if (ledger.get(year) !== undefined || manual.get("대장|" + year) !== undefined) annual = ledger.has(year) ? ledger.get(year)! : manual.get("대장|" + year) ?? null;
  else {
    const last = depRows(String(Number(year) - 1));
    annual = last.length ? last.reduce((a, r) => a + (r.amount || 0), 0) : null;
  }
  const extra = annual === null ? null : Math.max(Math.trunc(pyRound(annual * months / 12.0)) - booked, 0);
  return { annual, booked, extra, months };
}

const BAD_DEBT_RATE = 0.01;
const FOUNDED = 2025;

function badDebt(L: Law, journal: JLine[], cfg: Cfg, ym: string) {
  const cs = new Set((cfg.receivable_codes ?? ["10800", "11000", "12000"]).map((c) => squash(c)));
  let rec = 0, allow = 0;
  const years = new Set<number>();
  let opening = false;
  for (const ln of journal) {
    const d = ln.date;
    if (d === null || d.slice(0, 7) > ym) continue;
    years.add(Number(d.slice(0, 4)));
    const code = squash(ln.account_code), name = squash(ln.account);
    const dr = ln.debit || 0, cr = ln.credit || 0;
    if (cs.has(code)) rec += dr - cr;
    else if (name.includes("대손충당금")) allow += cr - dr;
    else continue;
    if ((squash(ln.sort) + squash(ln.memo)).includes("전기이월")) opening = true;
  }
  const partial = years.size > 0 && Math.min(...years) > FOUNDED && !opening;
  rec = Math.max(rec, 0);
  const [rate0, rateOk] = lawChecked(L, Number(ym.slice(0, 4)), "대손충당금률", BAD_DEBT_RATE);
  const rate = rate0 as number;
  const amount = Math.max(Math.trunc(rec * rate) - allow, 0);
  let note = `받을 돈 ${fmt(rec)} × ${pyG(rate * 100)}% − 쌓인 충당금 ${fmt(allow)}`;
  if (partial) note += " (작년 말 잔액 없어 올해 늘어난 몫만 — 작게 잡힘)";
  if (!rateOk) note += ` (한도율이 '세법 기준 확인'에서 확인되지 않아 기본 ${pyG(BAD_DEBT_RATE * 100)}%로 봄)`;
  return { amount, note };
}

function badDebtSaving(L: Law, base: number, amount: number, year: number): number | null {
  const [nat, corp] = national(L, base, year);
  const [nat2, corp2] = national(L, base - amount, year);
  if (nat === null || corp === null || nat2 === null || corp2 === null) return null;
  return (nat + Math.trunc(corp * LOCAL_RATE)) - (nat2 + Math.trunc(corp2 * LOCAL_RATE));
}

function badDebtHint(amount: number, saving: number | null): string {
  return `대손충당금 예상 ${fmt(amount)}원은 세무사 확인 전이라 빼지 않음 (쌓으면 세금 −${saving === null ? "모름" : fmt(saving)}원)`;
}

const PREPAID_CODES = ["13600"];

export function lastFullMonth(asof: IsoDate): string {
  const [y, m, d] = parseIso(asof);
  if (d === daysInMonth(y, m)) return asof.slice(0, 7);
  return addDays(ymd(y, m, 1), -1).slice(0, 7);
}

function workday(d: IsoDate): IsoDate {
  while (weekday(d) >= 5) d = addDays(d, 1);
  return d;
}

// ───────────── taxadj.adjust ─────────────
const PENALTY = /벌금|과태료|가산세|과징금|범칙금|교통위반|주정차/u;

function readSettings(files: ConvFiles, inputDir: string): Record<string, string> {
  const out: Record<string, string> = {};
  const rows = readDicts(files, join(inputDir, "배당설정.csv"));
  for (const r of rows ?? []) {
    const k = pyStrip(s(r["항목"] || "")), v = pyStrip(s(r["값"] || ""));
    if (k && v) out[k] = v;
  }
  return out;
}

function ledgerCar(files: ConvFiles, inputDir: string | null, year: number, wehagoDir: string | null): number | null {
  let rows: Record<string, string | null>[] = [];
  if (wehagoDir) rows = assetRows(rawFiles(files, wehagoDir));
  if (!rows.length && inputDir && exists(files, join(inputDir, "고정자산.csv"))) rows = readDicts(files, join(inputDir, "고정자산.csv")) ?? [];
  let v = 0;
  for (const r of rows) {
    if (s(r["기준연도"]) === String(year) && s(r["계정"] || "").includes("차량")) {
      const n = pyIntParse(s(r["당기상각"] || "0"));
      if (n === null) throw new RangeError("ValueError");
      v += n;
    }
  }
  return v || null;
}

type AdjItem = [string, number | null, boolean, string];

function carDep(L: Law, year: number, limInfo: [number | string | null, boolean, string], wehagoDir: string | null): AdjItem | null {
  if (!L.inputDir) return null;
  const filed = trLoad(L.files, L.inputDir).get(`${year - 1}\u0000확정`);
  if (!filed || !filed["승용차상각비"]) return null;
  const [lim, ok] = limInfo;
  if (!lim) return null;
  const acq = isoDay(filed["승용차취득일"] || "");
  const owned = acq && Number(acq.slice(0, 4)) === year - 1 ? 12 - Number(acq.slice(5, 7)) + 1 : 12;
  const lastDep = filed["승용차상각비"] as number;
  let annual = Math.trunc(lastDep * 12 / owned);
  let allowed = Math.min(annual, Math.trunc(lim as number));
  const manual = readManual(L.files, L.inputDir).get(String(year)) !== undefined;
  const ledger = readLedger(L.files, L.inputDir, wehagoDir).get(String(year)) !== undefined;
  const carNow = ledgerCar(L.files, L.inputDir, year, wehagoDir);
  if (carNow) { annual = carNow; allowed = Math.min(annual, Math.trunc(lim as number)); }
  const head = `${year - 1}년 신고서: 승용차(${acq ?? "작년"} 취득) 감가상각비 ${fmt(lastDep)}원(${owned}달 치) 중 한도 넘은 ${fmt((filed["승용차상각초과"] as number) || 0)}원은 비용 인정 안 됨. `;
  let adj: number, why: string;
  if (manual || ledger) {
    adj = annual - allowed;
    why = head + `올해 감가상각비 예상은 ${manual ? "창에 직접 넣은 금액" : "위하고 고정자산대장 금액"}(이 차 1년 치 ${fmt(annual)}원) → 한도 ${fmt(allowed)}원 넘는 ${fmt(adj)}원을 과세표준에 더함${manual ? " (직접 넣은 금액에 이 차가 빠져 있으면 세무사 확인)" : ""}`;
  } else {
    adj = lastDep - allowed;
    why = head + `올해 감가상각비 예상은 작년 금액이라 이 차는 ${fmt(lastDep)}원만 들어 있지만, 올해 1년 치 약 ${fmt(annual)}원 중 세법이 인정하는 건 한도 ${fmt(allowed)}원 → 과세표준 ${fmt(Math.abs(adj))}원 ${adj < 0 ? "줄어듦" : "늘어남"}. 장부 감가상각비 예상은 1년 치보다 약 ${fmt(Math.max(annual - lastDep, 0))}원 적게 잡혀 있음 (창 ⑨에 올해 감가상각비를 넣으면 장부 이익도 맞춰짐)`;
  }
  return ["업무용 승용차 감가상각비 한도", adj, !!ok, why];
}

function taxAdjust(L: Law, journal: JLine[], ym: string, revenue: number | null, answers: Record<string, string>, wehagoDir: string | null) {
  const year = Number(ym.slice(0, 4)), months = Number(ym.slice(5, 7));
  const law = (k: string) => lawValue(L, year, k);
  let ent = 0, car = 0, gift = 0, pen = 0, penN = 0;
  let opening = false;
  const byMonth = new Map<string, number>();
  for (const ln of journal) {
    const d = ln.date;
    if (d === null || d.slice(0, 7) > ym) continue;
    const name = sq(ln.account), code = sq(ln.account_code);
    const dr = ln.debit || 0, cr = ln.credit || 0;
    if (name.includes("가지급금") || (name.includes("대여금") && (name.includes("주임종") || name.includes("임원")))) {
      byMonth.set(d.slice(0, 7), (byMonth.get(d.slice(0, 7)) ?? 0) + dr - cr);
      if ((sq(ln.sort) + sq(ln.memo)).includes("전기이월")) opening = true;
      continue;
    }
    if (Number(d.slice(0, 4)) !== year) continue;
    if (name.includes("접대비") || name.includes("기업업무추진비")) ent += dr - cr;
    else if ((name.includes("차량") && ["5", "8"].includes(code.slice(0, 1))) || (name.includes("차량") && name.includes("유지"))) car += dr - cr;
    else if (name.includes("기부금")) gift += dr - cr;
    if (dr && ["5", "8", "9"].includes(code.slice(0, 1)) && PENALTY.test(sq(ln.memo))) { pen += dr; penN++; }
  }
  const items: AdjItem[] = [];
  const [baseLim, ok1] = law("접대비기본한도");
  const [rate, ok2] = law("접대비수입비율");
  if (ent) {
    if (revenue !== null && baseLim && rate) {
      const lim = Math.trunc(((baseLim as number) + revenue * 12.0 / months * (rate as number)) * months / 12.0);
      const over = Math.max(ent - lim, 0);
      items.push(["접대비 한도 초과", over, ok1 && ok2 && over > 0,
        `1~${months}월 접대비 ${fmt(Math.trunc(ent))}원 vs 한도 ${fmt(lim)}원 (기본 ${fmt(baseLim as number)} + 매출 × ${pyG((rate as number) * 100)}%, ${months}달 몫)`]);
    } else items.push(["접대비 한도 초과", null, false, "매출이나 세법 기준을 몰라 계산 못 함"]);
  }
  items.push(["벌금·과태료·가산세", pen, pen > 0, penN ? `적요에 벌금·과태료·가산세 등이 적힌 비용 전표 ${penN}건` : "적요에서 찾은 건 없음 (적요가 없는 건은 못 찾음)"]);
  const [limCar] = law("승용차기록없음한도");
  const rec = answers["승용차기록"];
  if (car && limCar) {
    const part = Math.trunc((limCar as number) * months / 12.0);
    const over = Math.max(Math.trunc(car) - part, 0);
    const why = `1~${months}월 차량 비용 ${fmt(Math.trunc(car))}원 vs 운행기록부 없을 때 1대 한도 ${fmt(part)}원 (${months}달 몫)`;
    if (rec === "씀" || rec === "승용차 없음") items.push(["업무용 승용차 비용", 0, false, why + " — 운행기록부를 쓰거나 승용차가 아니라 조정 없음"]);
    else items.push(["업무용 승용차 비용", over, false, why + " — 승용차 대수·운행기록부 확인 필요 (차가 여러 대면 한도도 늘어남)"]);
  }
  const cd = carDep(L, year, law("승용차상각한도"), wehagoDir);
  if (cd) items.push(cd);
  const [irate, ok4] = law("인정이자율");
  if (byMonth.size) {
    let tot = 0, n = 0;
    const sortedKeys = [...byMonth.keys()].sort();
    for (let m = 1; m <= months; m++) {
      const key = `${year}-${String(m).padStart(2, "0")}`;
      const bal = sortedKeys.filter((k) => k < key).reduce((a, k) => a + byMonth.get(k)!, 0) + (byMonth.get(key) ?? 0);
      tot += Math.max(bal, 0);
      n++;
    }
    const avg = tot / (n || 1);
    const interest = irate ? Math.trunc(avg * (irate as number) * months / 12.0) : null;
    items.push(["가지급금 인정이자", interest, !!interest && ok4, `가지급금 월평균 ${fmt(Math.trunc(avg))}원 × ${pyG(((irate as number) || 0) * 100)}% × ${months}/12${opening ? "" : " (작년 말 잔액 없으면 작게 잡힘)"}`]);
  }
  if (gift) items.push(["기부금 한도", null, false, `1~${months}월 기부금 ${fmt(Math.trunc(gift))}원 — 종류별 한도는 세무사 계산`]);
  const total = items.filter(([, v, on]) => on && v).reduce((a, [, v]) => a + Math.trunc(v as number), 0);
  return { items, total };
}

function adjustFor(L: Law, journal: JLine[], cfg: Cfg, asof: IsoDate, wehagoDir: string | null) {
  const ym = lastFullMonth(asof);
  let rev = 0;
  for (const ln of journal) {
    const d = ln.date;
    if (d === null || d.slice(0, 7) > ym || Number(d.slice(0, 4)) !== Number(ym.slice(0, 4))) continue;
    if (classify(ln, cfg) === "revenue") rev += net(ln, "revenue") || 0;
  }
  const ans = L.inputDir ? readSettings(L.files, L.inputDir) : {};
  return taxAdjust(L, journal, ym, rev, ans, wehagoDir);
}

/** from_journal -> [세금예상 줄, 메모] */
export function fromJournal(L: Law, journal: JLine[], cfg: Cfg, asof: IsoDate, manual: Manual, wehagoDir: string | null): [TaxRow[], string] {
  const ym = lastFullMonth(asof);
  const year = ym.slice(0, 4);
  const nin = new Set(cfg.nonop_in_codes.map((c) => squash(c))), nout = new Set(cfg.nonop_out_codes.map((c) => squash(c)));
  const prepaidCodes = new Set(PREPAID_CODES.map((c) => squash(c)));
  let pretax = 0, unknown = 0, prepaid = 0;
  const depLines: DepLine[] = [];
  for (const ln0 of journal) {
    const ln = closingPlLine(ln0, cfg.closing_sorts);
    if (ln === null || ln.date === null) continue;
    const lym = ln.date.slice(0, 7);
    const code = squash(ln.account_code);
    if (squash(ln.account).includes("감가상각비") && (lym.slice(0, 4) === year || lym.slice(0, 4) === String(Number(year) - 1))) {
      depLines.push({ ym: lym, name: ln.account, amount: net(ln, "common") });
    }
    if (lym.slice(0, 4) !== year || lym > ym) continue;
    if (prepaidCodes.has(code)) { prepaid += (ln.debit || 0) - (ln.credit || 0); continue; }
    const kind = classify(ln, cfg);
    let v: number | null, sign: number;
    if (nin.has(code)) { v = net(ln, "revenue"); sign = 1; }
    else if (nout.has(code)) { v = net(ln, "common"); sign = -1; }
    else if (kind === "revenue") { v = net(ln, "revenue"); sign = 1; }
    else if (kind === "direct" || kind === "common" || kind === "common_unmarked") { v = net(ln, "common"); sign = -1; }
    else continue;
    if (v === null) unknown++;
    else pretax += sign * v;
  }
  const dep = depreciation(depLines, manual, ym, readLedger(L.files, L.inputDir, wehagoDir));
  const bd = badDebt(L, journal, cfg, ym);
  const adj = adjustFor(L, journal, cfg, asof, wehagoDir);
  const base = pretax - (dep.extra || 0) + adj.total;
  const [nat0, corp0, C] = national(L, base, Number(year));
  const nat = nat0 as number, corp = corp0 as number;
  const local = Math.trunc(corp * LOCAL_RATE);
  const pay = Math.max(nat - prepaid, 0);
  const nxt = Number(year) + 1;
  const period = `${year}년 (1월~${Number(ym.slice(5))}월 장부 기준)`;
  let basis = `세전 이익 ${fmt(pretax)} − 감가상각비 예상 ${fmt(dep.extra || 0)} = 과세표준 ${fmt(base)} → 법인세 ${fmt(corp)} − 중간예납 등 선납세금 ${fmt(prepaid)}`;
  if (C) basis = basis.replace(" − 중간예납 등", ` → 감면·공제 뒤 ${fmt(C.final)} + 농어촌특별세 ${fmt(C.nong)} (작년 신고서: 중소기업 특별세액감면, 넘어온 고용 공제) − 중간예납 등`);
  if (adj.total) basis = basis.replace(" = 과세표준", ` + 세무조정 예상 ${fmt(adj.total)} = 과세표준`);
  if (bd.amount) basis += " · " + badDebtHint(bd.amount, badDebtSaving(L, base, bd.amount, Number(year)));
  basis += " · 대손충당금 = " + bd.note;
  if (unknown) basis += ` · 금액 없는 손익 줄 ${unknown}건 뺌`;
  const r1 = { ...taxRow("법인세", period, workday(ymd(nxt, 3, 31)), unknown ? null : pay, "예상", basis),
    "과세표준": String(base), "산출세액": String(corp), "기납부": String(prepaid), "대손충당금": String(bd.amount), "세무조정": String(adj.total) };
  const r2 = { ...taxRow("법인지방소득세", period, workday(ymd(nxt, 4, 30)), unknown ? null : local, "예상", `법인세 산출세액 ${fmt(corp)} × 10%`),
    "과세표준": "", "산출세액": "", "기납부": "", "대손충당금": "", "세무조정": "" };
  return [[r1, r2], `법인세 ${period} → ${fmt(pay)}원 (${C ? "감면 뒤" : "산출"} ${fmt(nat)} − 선납 ${fmt(prepaid)}), 지방소득세 ${fmt(local)}원`];
}

const INTERIM_MIN = 500_000;

function bankTaxSlips(journal: JLine[], start: IsoDate, end: IsoDate, prepaidCodes: Set<string>): [boolean, number][] {
  const slips = new Map<string, JLine[]>();
  for (const ln of journal) {
    if (ln.date !== null && start <= ln.date && ln.date <= end) {
      const k = ln.date + "\u0000" + ln.no;
      if (!slips.has(k)) slips.set(k, []);
      slips.get(k)!.push(ln);
    }
  }
  const out: [boolean, number][] = [];
  for (const lines of slips.values()) {
    if (!fromBank(lines)) continue;
    const pre = lines.filter((x) => prepaidCodes.has(squash(x.account_code))).reduce((a, x) => a + (x.debit || 0), 0);
    const tax = lines.filter((x) => !prepaidCodes.has(squash(x.account_code)) && (squash(x.account).includes("법인세") || squash(x.account).includes("지방소득세")))
      .reduce((a, x) => a + (x.debit || 0), 0);
    if (pre) out.push([true, pre]);
    if (tax) out.push([false, tax]);
  }
  return out;
}

function paidLike(slips: [boolean, number][], amount: number | null, prepaid = false): boolean {
  return !!amount && slips.some(([p, v]) => p === prepaid && 0.5 * amount <= v && v <= 1.5 * amount);
}

/** carry_rows */
export function carryRows(L: Law, journal: JLine[], cfg: Cfg, asof: IsoDate, manual: Manual, wehagoDir: string | null): TaxRow[] {
  const Y = Number(asof.slice(0, 4));
  const prepaidCodes = new Set(PREPAID_CODES.map((c) => squash(c)));
  const paid = bankTaxSlips(journal, ymd(Y, 1, 1), asof, prepaidCodes);
  const D = L.inputDir ? trLoad(L.files, L.inputDir) : new Map<string, TR>();
  const last = D.get(`${Y - 1}\u0000확정`), lastMid = D.get(`${Y - 1}\u0000중간예납`);
  let prev: TaxRow[] | null = null;
  if (journal.some((ln) => ln.date !== null && Number(ln.date.slice(0, 4)) === Y - 1)) prev = fromJournal(L, journal, cfg, ymd(Y - 1, 12, 31), manual, wehagoDir)[0];
  const rows: TaxRow[] = [];
  if (Number(lastFullMonth(asof).slice(0, 4)) === Y) {
    let period = "";
    let items: [string, number, number, number | null, string, string][] = [];
    if (last && last["차감납부세액"] !== null) {
      period = `${Y - 1}년 (신고서)`;
      const natAmt = (last["차감납부세액"] as number) + ((last["농특세"] as number) || 0);
      items = [["법인세", 3, 31, last["실제납부"] !== null ? null : natAmt, `${Y - 1}년 법인세 신고서: 차감납부세액 ${fmt(last["차감납부세액"] as number)} + 농어촌특별세 ${fmt((last["농특세"] as number) || 0)}`, "확정(신고서)"],
        ["법인지방소득세", 4, 30, last["지방소득세"] as number | null, `${Y - 1}년 법인세 신고서 지방소득세`, "확정(신고서)"]];
    } else if (prev && prev.length) {
      period = prev[0]!["대상기간"]!;
      items = prev.map((r) => [r["세목"]!, r["세목"] === "법인세" ? 3 : 4, r["세목"] === "법인세" ? 31 : 30, r["금액"] === "" ? null : Number(r["금액"]), r["근거"]!, r["상태"]!]);
    }
    for (const [kind, m, day, amount, basis, state] of items) {
      const due = workday(ymd(Y, m, day));
      if (due < asof || amount === null || paidLike(paid, amount)) continue;
      const r = taxRow(kind, period, due, amount, state, basis);
      if (kind === "법인세" && prev && !last) for (const k of ["과세표준", "산출세액", "기납부", "대손충당금", "세무조정"]) r[k] = prev[0]![k] ?? "";
      rows.push(r);
    }
  }
  const due = workday(ymd(Y, 8, 31));
  if (asof <= due) {
    let baseTax: number | null = null, how = "";
    if (last && last["총부담세액"] !== null) {
      const w = Math.max(((last["기납부세액"] as number) || 0) - (((lastMid ?? {})["차감납부세액"] as number) || 0), 0);
      baseTax = (last["총부담세액"] as number) - w;
      how = `${Y - 1}년 신고서 총부담세액 ${fmt(last["총부담세액"] as number)} − 원천징수 등 ${fmt(w)}`;
    } else if (prev && prev[0]!["과세표준"]) {
      const [, corp, C] = national(L, Number(prev[0]!["과세표준"]), Y - 1);
      const total = C ? C.final : (corp as number);
      const midPrev = bankTaxSlips(journal, ymd(Y - 1, 7, 1), ymd(Y - 1, 12, 31), prepaidCodes).filter(([p]) => p).reduce((a, [, v]) => a + v, 0);
      const w = Math.max(Number(prev[0]!["기납부"] || 0) - midPrev, 0);
      baseTax = total - w;
      how = `${Y - 1}년 장부로 계산한 법인세 ${fmt(total)} − 원천징수 등 ${fmt(w)}`;
    }
    const amount = baseTax === null ? null : Math.trunc(baseTax * 6 / 12);
    if (amount && amount >= INTERIM_MIN && !paidLike(bankTaxSlips(journal, ymd(Y, 7, 1), asof, prepaidCodes), amount, true)) {
      rows.push(taxRow("법인세", `${Y}년 중간예납`, due, amount, "예상", how + " × 6/12 (50만 원 미만이면 안 냄)"));
    }
  }
  return rows;
}
